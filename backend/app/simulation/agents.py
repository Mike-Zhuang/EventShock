"""可解释规则智能体，以及 LLM 信念到订单意图的确定性适配。"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from backend.app.information.models import SourceTier
from backend.app.simulation.agent_protocol import (
    ActionPreference as ProtocolActionPreference,
)
from backend.app.simulation.agent_protocol import (
    AgentDescriptor,
    BeliefDecision,
    BeliefDirection,
    DeterministicActionTranslator,
    EvidenceAssessment,
    EvidenceObservation,
    EvidenceStance,
    MarketObservation,
    Observation,
    OrderPolicyConfig,
    OrderSide,
    OrderStyle,
    PortfolioObservation,
)
from backend.app.simulation.order_book import Side


class AgentType(StrEnum):
    NOISE = "noise"
    VALUE = "value"
    MOMENTUM = "momentum"
    MEAN_REVERSION = "meanReversion"
    MARKET_MAKER = "marketMaker"
    PASSIVE = "passive"
    STOP_LOSS = "stopLoss"
    INSTITUTIONAL = "institutionalExecution"
    DELEVERAGING = "deleveraging"
    LIQUIDATION = "forcedLiquidation"
    ARBITRAGE = "arbitrage"


@dataclass(slots=True)
class AgentState:
    agentId: str
    agentType: AgentType
    institutional: bool = False
    position: int = 0
    cashCents: int = 10_000_000
    maxObservedPriceTicks: int = 1_350_000
    initialPosition: int = 0
    maxAbsolutePosition: int = 180


@dataclass(slots=True, frozen=True)
class MarketContext:
    step: int
    steps: int
    midPriceTicks: float
    fundamentalPriceTicks: float
    recentPricesTicks: tuple[float, ...]
    sentiment: float
    stopLossSensitivity: float
    passiveFlowMultiplier: float = 1.0
    bestBidTicks: int | None = None
    bestAskTicks: int | None = None
    depthWithinTenBps: int = 100
    priceCollarBps: int = 180
    instrumentId: str = "SPCX"
    simTime: datetime | None = None


@dataclass(slots=True, frozen=True)
class OrderIntent:
    side: Side
    quantity: int
    urgency: float
    useMarket: bool
    reason: str
    limitPriceTicks: int | None = None
    timeInForce: str = "GTC"
    sourceDecisionId: str | None = None
    policyTrace: tuple[dict[str, str], ...] = ()
    cognitive: bool = False
    tailRisk: float = 0.0
    forced: bool = False


def buildPopulation(
    populationSize: int,
    *,
    profileId: str = "mixed-event-risk-v1",
    institutionalShare: float = 0.2,
    initialPriceTicks: int = 1_350_000,
) -> list[AgentState]:
    """按冻结 profile 与机构占比生成可重放人口。

    ``profileId`` 既是配置版本，也是人口实现的确定性命名空间；相同版本始终
    生成相同 cohort 和类型排列，不同版本不会悄悄复用完全相同的人口。机构
    cohort 使用执行、做市、被动、套利与去杠杆策略，非机构 cohort 使用散户、
    价值、趋势、反转、止损与强平策略。
    """

    if populationSize < 14:
        raise ValueError("populationSize must be at least 14")
    if not profileId:
        raise ValueError("profileId must not be empty")
    if not 0 <= institutionalShare <= 1:
        raise ValueError("institutionalShare must be between 0 and 1")
    if initialPriceTicks <= 0:
        raise ValueError("initialPriceTicks must be positive")

    institutionalPattern, nonInstitutionalPattern = _populationPatterns(profileId)
    profileDigest = hashlib.blake2s(profileId.encode("utf-8"), digest_size=16).digest()
    institutionalOffset = int.from_bytes(profileDigest[:4], "big") % len(institutionalPattern)
    nonInstitutionalOffset = int.from_bytes(profileDigest[4:8], "big") % len(
        nonInstitutionalPattern
    )
    institutionalCount = round(populationSize * institutionalShare)
    rankedIndices = sorted(
        range(populationSize),
        key=lambda index: hashlib.blake2s(
            f"{profileId}:cohort:{index}".encode(), digest_size=8
        ).digest(),
    )
    institutionalIndices = set(rankedIndices[:institutionalCount])
    initialPositions = {
        AgentType.MARKET_MAKER: 80,
        AgentType.STOP_LOSS: 40,
        AgentType.INSTITUTIONAL: 20,
        AgentType.DELEVERAGING: 90,
        AgentType.LIQUIDATION: 120,
    }
    population = []
    institutionalSequence = 0
    nonInstitutionalSequence = 0
    for index in range(populationSize):
        institutional = index in institutionalIndices
        if institutional:
            agentType = institutionalPattern[
                (institutionalSequence + institutionalOffset) % len(institutionalPattern)
            ]
            institutionalSequence += 1
        else:
            agentType = nonInstitutionalPattern[
                (nonInstitutionalSequence + nonInstitutionalOffset) % len(nonInstitutionalPattern)
            ]
            nonInstitutionalSequence += 1
        initialPosition = initialPositions.get(agentType, 0)
        population.append(
            AgentState(
                agentId=f"agent-{index + 1:03d}",
                agentType=agentType,
                institutional=institutional,
                position=initialPosition,
                initialPosition=initialPosition,
                maxObservedPriceTicks=initialPriceTicks,
            )
        )
    return population


def _populationPatterns(profileId: str) -> tuple[tuple[AgentType, ...], tuple[AgentType, ...]]:
    normalizedProfile = profileId.casefold()
    if "narrative" in normalizedProfile or "retail" in normalizedProfile:
        return (
            AgentType.PASSIVE,
            AgentType.MARKET_MAKER,
            AgentType.INSTITUTIONAL,
            AgentType.ARBITRAGE,
            AgentType.DELEVERAGING,
        ), (
            AgentType.NOISE,
            AgentType.MOMENTUM,
            AgentType.STOP_LOSS,
            AgentType.NOISE,
            AgentType.VALUE,
            AgentType.LIQUIDATION,
            AgentType.MEAN_REVERSION,
        )
    if "liquidity" in normalizedProfile or "institutional" in normalizedProfile:
        return (
            AgentType.MARKET_MAKER,
            AgentType.INSTITUTIONAL,
            AgentType.PASSIVE,
            AgentType.MARKET_MAKER,
            AgentType.ARBITRAGE,
            AgentType.DELEVERAGING,
        ), (
            AgentType.VALUE,
            AgentType.MEAN_REVERSION,
            AgentType.MOMENTUM,
            AgentType.STOP_LOSS,
            AgentType.NOISE,
            AgentType.LIQUIDATION,
        )
    return (
        AgentType.INSTITUTIONAL,
        AgentType.PASSIVE,
        AgentType.MARKET_MAKER,
        AgentType.ARBITRAGE,
        AgentType.DELEVERAGING,
    ), (
        AgentType.NOISE,
        AgentType.VALUE,
        AgentType.MOMENTUM,
        AgentType.MEAN_REVERSION,
        AgentType.STOP_LOSS,
        AgentType.LIQUIDATION,
    )


def makeOrderIntent(
    agent: AgentState,
    context: MarketContext,
    behaviorRandom: random.Random,
    orderSizeRandom: random.Random,
) -> OrderIntent | None:
    """生成规则意图；这里只表达方向和数量，不直接改变价格或账本。"""

    if agent.agentType == AgentType.MARKET_MAKER:
        return None

    score = _strategyScore(agent, context, behaviorRandom)
    if abs(score) < 0.12:
        return None
    side = Side.BUY if score > 0 else Side.SELL
    urgency = min(1.0, 0.2 + abs(score) * 0.55)
    if agent.agentType == AgentType.DELEVERAGING:
        urgency = max(urgency, 0.78)
    elif agent.agentType == AgentType.LIQUIDATION:
        urgency = max(urgency, 0.95)
    elif agent.agentType == AgentType.INSTITUTIONAL:
        urgency = max(urgency, 0.45)

    quantity = max(1, round((2 + orderSizeRandom.random() * 7) * (0.65 + urgency)))
    if agent.agentType in {AgentType.PASSIVE, AgentType.INSTITUTIONAL}:
        quantity = max(1, round(quantity * max(0.1, context.passiveFlowMultiplier)))
    elif agent.agentType == AgentType.DELEVERAGING and side is Side.SELL:
        quantity = max(quantity, max(1, abs(agent.position) // 8))
    elif agent.agentType == AgentType.LIQUIDATION and side is Side.SELL:
        quantity = max(quantity, max(1, abs(agent.position) // 3))

    # 规则风险上限防止单一策略无限累积；最终仍需通过组合账本风控。
    projectedPosition = agent.position + (quantity if side == Side.BUY else -quantity)
    if abs(projectedPosition) > agent.maxAbsolutePosition:
        side = Side.SELL if agent.position > 0 else Side.BUY
        quantity = min(quantity, max(1, abs(agent.position) // 4))
    if agent.agentType in {AgentType.DELEVERAGING, AgentType.LIQUIDATION} and side is Side.SELL:
        quantity = min(quantity, max(agent.position, 1))

    reason = _reasonFor(agent.agentType, score)
    return OrderIntent(
        side=side,
        quantity=quantity,
        urgency=urgency,
        useMarket=urgency >= 0.52,
        reason=reason,
        forced=agent.agentType in {AgentType.DELEVERAGING, AgentType.LIQUIDATION},
    )


def makeCognitiveOrderIntent(
    agent: AgentState,
    context: MarketContext,
    signal: Mapping[str, Any],
) -> OrderIntent | None:
    """把 LLM 的信念字段交给固定政策；忽略任何供应商给出的价格或订单字段。"""

    try:
        actionPreference = ProtocolActionPreference(str(signal["actionPreference"]))
        direction = BeliefDirection(str(signal.get("direction", "NEUTRAL")))
    except (KeyError, ValueError, TypeError):
        return None

    evidenceIds = tuple(
        dict.fromkeys(
            evidenceId
            for evidenceId in signal.get("evidenceIds", ())
            if isinstance(evidenceId, str) and evidenceId
        )
    )[:64]
    if (
        actionPreference
        not in {
            ProtocolActionPreference.HOLD,
            ProtocolActionPreference.ABSTAIN,
            ProtocolActionPreference.POST_ONLY,
        }
        and not evidenceIds
    ):
        return None

    bestBidTicks, bestAskTicks = _safeTopOfBook(context)
    simTime = context.simTime or (
        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=context.step)
    )
    observation = Observation(
        schemaVersion="1.0.0",
        observationId=f"simulation-observation-{context.step}-{agent.agentId}",
        simTime=simTime,
        agent=AgentDescriptor(
            agentId=agent.agentId,
            role=str(signal.get("role", "bounded_llm_agent"))[:100] or "bounded_llm_agent",
            instrumentId=context.instrumentId,
            riskTolerance=0.5,
            lossAversion=1.5,
            horizonMinutes=120,
            confirmationBias=0.25,
            trustProfile={"official": 0.95, "news": 0.7, "social": 0.3},
        ),
        portfolio=PortfolioObservation(
            cashAvailableCents=max(0, agent.cashCents),
            position=agent.position,
            reservedPosition=0,
            unrealizedPnlBps=_unrealizedPnlBps(agent, context.midPriceTicks),
            maxAbsolutePosition=agent.maxAbsolutePosition,
        ),
        market=MarketObservation(
            bestBidTicks=bestBidTicks,
            bestAskTicks=bestAskTicks,
            returnOneMinuteBps=_recentReturnBps(context.recentPricesTicks, 1),
            returnFifteenMinutesBps=_recentReturnBps(context.recentPricesTicks, 8),
            spreadBps=round((bestAskTicks - bestBidTicks) / context.midPriceTicks * 10_000),
            depthWithinTenBps=max(0, context.depthWithinTenBps),
            orderImbalance=max(-1.0, min(1.0, context.sentiment)),
            volatilityRegime="stressed" if abs(context.sentiment) >= 0.35 else "normal",
        ),
        newEvidence=tuple(
            EvidenceObservation(
                evidenceId=evidenceId,
                claim=f"Approved scenario evidence reference: {evidenceId}",
                sourceTier=SourceTier.T1,
                knownAt=simTime,
                credibility=0.9,
            )
            for evidenceId in evidenceIds
        ),
        allowedActions=tuple(ProtocolActionPreference),
    )
    stance = _stanceForDirection(direction)
    decisionId = _safeDecisionId(signal, agent, context)
    decision = BeliefDecision(
        schemaVersion="1.0.0",
        decisionId=decisionId,
        direction=direction,
        expectedValueChangeBps=_expectedChangeBps(direction),
        uncertainty=_boundedFloat(signal.get("uncertainty"), default=1.0),
        perceivedTailRisk=_boundedFloat(signal.get("tailRisk"), default=1.0),
        horizonMinutes=120,
        evidence=tuple(
            EvidenceAssessment(
                evidenceId=evidenceId,
                stance=stance,
                weight=round(1 / len(evidenceIds), 6),
            )
            for evidenceId in evidenceIds
        ),
        actionPreference=actionPreference,
        targetPositionFraction=_boundedFloat(
            signal.get("targetPositionFraction"),
            default=0.0,
            lower=-1.0,
        ),
        urgency=_boundedFloat(signal.get("urgency"), default=0.0),
        confidence=_boundedFloat(signal.get("confidence"), default=0.0),
        decisionSummary=(
            str(signal.get("decisionSummary", "Bounded model belief."))[:500]
            or "Bounded model belief."
        ),
        abstainReason=(
            "The model abstained from an actionable simulated preference."
            if actionPreference is ProtocolActionPreference.ABSTAIN
            else None
        ),
    )
    translator = DeterministicActionTranslator(
        OrderPolicyConfig(
            policyVersion="simulation-cognitive-policy-1.0.0",
            lotSize=1,
            participationCap=0.25,
            maximumSlippageBps=max(0, min(context.priceCollarBps, 5_000)),
        )
    )
    try:
        translated = translator.translate(observation, decision)
    except ValueError:
        return None
    if translated.proposedQuantity == 0 or translated.side is None:
        return None
    return OrderIntent(
        side=Side.BUY if translated.side is OrderSide.BUY else Side.SELL,
        quantity=translated.proposedQuantity,
        urgency=translated.urgency,
        useMarket=translated.orderStyle is OrderStyle.MARKETABLE_LIMIT,
        reason=f"cognitive-policy-{actionPreference.value.lower()}",
        limitPriceTicks=translated.limitPriceTicks,
        timeInForce=translated.timeInForce.value,
        sourceDecisionId=decisionId,
        policyTrace=tuple(
            {
                "step": item.step,
                "input": item.inputValue,
                "output": item.outputValue,
                "reason": item.reason,
            }
            for item in translated.trace
        ),
        cognitive=True,
        tailRisk=decision.perceivedTailRisk,
    )


def _strategyScore(
    agent: AgentState,
    context: MarketContext,
    behaviorRandom: random.Random,
) -> float:
    priceScale = max(context.midPriceTicks, 1.0)
    fundamentalGap = (context.fundamentalPriceTicks - context.midPriceTicks) / priceScale
    recentPrices = context.recentPricesTicks
    momentum = (
        (recentPrices[-1] - recentPrices[max(0, len(recentPrices) - 4)]) / priceScale
        if len(recentPrices) >= 2
        else 0.0
    )
    movingAverage = sum(recentPrices[-8:]) / min(len(recentPrices), 8)
    deviation = (context.midPriceTicks - movingAverage) / priceScale
    recentPeak = max(recentPrices, default=context.midPriceTicks)
    drawdown = max(0.0, (recentPeak - context.midPriceTicks) / max(recentPeak, 1.0))

    if agent.agentType == AgentType.NOISE:
        return behaviorRandom.uniform(-0.75, 0.75) + context.sentiment * 0.45
    if agent.agentType == AgentType.VALUE:
        return fundamentalGap * 75 + context.sentiment * 0.12
    if agent.agentType == AgentType.MOMENTUM:
        return momentum * 90 + context.sentiment * 0.35
    if agent.agentType == AgentType.MEAN_REVERSION:
        return -deviation * 115 + fundamentalGap * 20
    if agent.agentType == AgentType.PASSIVE:
        inclusionStart = round(context.steps * 0.32)
        inclusionEnd = round(context.steps * 0.47)
        return (
            0.72 * max(0.1, context.passiveFlowMultiplier)
            if inclusionStart <= context.step <= inclusionEnd
            else 0.0
        )
    if agent.agentType == AgentType.INSTITUTIONAL:
        executionStart = round(context.steps * 0.28)
        executionEnd = round(context.steps * 0.58)
        return (
            0.58 * max(0.1, context.passiveFlowMultiplier)
            if executionStart <= context.step <= executionEnd
            else fundamentalGap * 35
        )
    if agent.agentType == AgentType.STOP_LOSS:
        agent.maxObservedPriceTicks = max(agent.maxObservedPriceTicks, round(context.midPriceTicks))
        lifetimeDrawdown = (agent.maxObservedPriceTicks - context.midPriceTicks) / max(
            agent.maxObservedPriceTicks,
            1,
        )
        triggerThreshold = 0.012 / max(context.stopLossSensitivity, 0.1)
        if agent.position > 0 and lifetimeDrawdown >= triggerThreshold:
            return -min(1.5, 0.75 + lifetimeDrawdown * 25)
        return fundamentalGap * 25 + context.sentiment * 0.08
    if agent.agentType == AgentType.DELEVERAGING:
        if agent.position > 0 and (context.sentiment <= -0.12 or drawdown >= 0.006):
            return -min(1.6, 0.65 + abs(context.sentiment) + drawdown * 35)
        return fundamentalGap * 20
    if agent.agentType == AgentType.LIQUIDATION:
        if agent.position > 0 and (context.sentiment <= -0.3 or drawdown >= 0.01):
            return -min(2.0, 1.05 + abs(context.sentiment) + drawdown * 50)
        return 0.0
    if agent.agentType == AgentType.ARBITRAGE:
        return fundamentalGap * 145 - momentum * 45
    return 0.0


def _reasonFor(agentType: AgentType, score: float) -> str:
    direction = "buy" if score > 0 else "sell"
    reasons = {
        AgentType.NOISE: f"noise-and-sentiment-{direction}",
        AgentType.VALUE: f"fundamental-gap-{direction}",
        AgentType.MOMENTUM: f"short-horizon-momentum-{direction}",
        AgentType.MEAN_REVERSION: f"mean-reversion-{direction}",
        AgentType.PASSIVE: "scheduled-index-flow-buy",
        AgentType.INSTITUTIONAL: f"institutional-schedule-{direction}",
        AgentType.STOP_LOSS: (
            "stop-loss-triggered-sell" if score < -0.7 else f"risk-rule-{direction}"
        ),
        AgentType.DELEVERAGING: f"deleveraging-{direction}",
        AgentType.LIQUIDATION: "forced-liquidation-sell",
        AgentType.ARBITRAGE: f"cross-signal-arbitrage-{direction}",
    }
    return reasons.get(agentType, f"rule-{direction}")


def _safeTopOfBook(context: MarketContext) -> tuple[int, int]:
    fallbackMid = max(2, round(context.midPriceTicks))
    bestBid = context.bestBidTicks or fallbackMid - 1
    bestAsk = context.bestAskTicks or fallbackMid + 1
    bestBid = max(1, min(bestBid, fallbackMid))
    bestAsk = max(bestBid + 1, bestAsk)
    return bestBid, bestAsk


def _recentReturnBps(prices: tuple[float, ...], lookback: int) -> int:
    if len(prices) < 2:
        return 0
    start = prices[max(0, len(prices) - 1 - lookback)]
    return round((prices[-1] / max(start, 1.0) - 1) * 10_000)


def _unrealizedPnlBps(agent: AgentState, midPriceTicks: float) -> int:
    if agent.position == 0:
        return 0
    return round((midPriceTicks / max(agent.maxObservedPriceTicks, 1) - 1) * 10_000)


def _boundedFloat(
    value: object,
    *,
    default: float,
    lower: float = 0.0,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    resolved = float(value)
    if resolved != resolved:
        return default
    return max(lower, min(1.0, resolved))


def _safeDecisionId(
    signal: Mapping[str, Any],
    agent: AgentState,
    context: MarketContext,
) -> str:
    supplied = signal.get("decisionId")
    if isinstance(supplied, str) and supplied:
        return supplied[:160]
    material = {
        "agentId": agent.agentId,
        "step": context.step,
        "direction": signal.get("direction"),
        "actionPreference": signal.get("actionPreference"),
        "targetPositionFraction": signal.get("targetPositionFraction"),
        "urgency": signal.get("urgency"),
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"simulation-decision-{digest}"


def _stanceForDirection(direction: BeliefDirection) -> EvidenceStance:
    if direction is BeliefDirection.POSITIVE:
        return EvidenceStance.SUPPORTS_UPSIDE
    if direction is BeliefDirection.NEGATIVE:
        return EvidenceStance.SUPPORTS_DOWNSIDE
    return EvidenceStance.NEUTRAL


def _expectedChangeBps(direction: BeliefDirection) -> int:
    if direction is BeliefDirection.POSITIVE:
        return 100
    if direction is BeliefDirection.NEGATIVE:
        return -100
    return 0
