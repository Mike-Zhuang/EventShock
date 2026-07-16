"""把 BeliefDecision 转换为受约束订单意图的确定性策略。"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Literal

from pydantic import Field

from backend.app.cognition.gateway import canonicalHash
from backend.app.cognition.models import (
    ActionPreference,
    BeliefDecision,
    Observation,
    StrictFrozenModel,
)


class IntentStatus(StrEnum):
    APPROVED = "APPROVED"
    NO_ACTION = "NO_ACTION"
    BLOCKED = "BLOCKED"


class IntentSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


class IntentOrderType(StrEnum):
    PASSIVE_LIMIT = "PASSIVE_LIMIT"
    AGGRESSIVE_LIMIT = "AGGRESSIVE_LIMIT"
    MARKETABLE_LIMIT = "MARKETABLE_LIMIT"
    NONE = "NONE"


class IntentTimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    NONE = "NONE"


class DeterministicOrderPolicyConfig(StrictFrozenModel):
    policy_version: Literal["belief_order_policy_v1.0.0"] = "belief_order_policy_v1.0.0"
    max_order_quantity: int = Field(default=100, ge=1, le=1_000_000)
    participation_cap: float = Field(default=0.1, ge=0.001, le=1.0)
    max_slippage_bps: int = Field(default=100, ge=1, le=5_000)
    minimum_confidence: float = Field(default=0.1, ge=0.0, le=1.0)
    allow_short_selling: bool = False


class CognitiveOrderIntent(StrictFrozenModel):
    policy_version: str = Field(min_length=3, max_length=80)
    source_decision_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    agent_id: str = Field(min_length=3, max_length=128)
    instrument_id: str = Field(min_length=1, max_length=32)
    status: IntentStatus
    target_position: int
    delta_quantity_raw: int
    delta_quantity_approved: int
    side: IntentSide
    quantity: int = Field(ge=0)
    urgency: float = Field(ge=0.0, le=1.0)
    max_slippage_bps: int = Field(ge=0, le=5_000)
    time_in_force: IntentTimeInForce
    order_type: IntentOrderType
    limit_price_ticks: int | None = Field(default=None, ge=1)
    modifications: tuple[str, ...]


def beliefToOrderIntent(
    decision: BeliefDecision,
    observation: Observation,
    config: DeterministicOrderPolicyConfig | None = None,
) -> CognitiveOrderIntent:
    config = config or DeterministicOrderPolicyConfig()
    targetPosition = round(decision.target_position_fraction * observation.portfolio.max_position)
    rawDelta = targetPosition - observation.portfolio.position
    modifications: list[str] = []

    if decision.action_preference in {
        ActionPreference.ABSTAIN,
        ActionPreference.HOLD,
        ActionPreference.POST_ONLY,
    }:
        modifications.append(f"ACTION_{decision.action_preference.value}")
        return _noActionIntent(
            decision, observation, config, targetPosition, rawDelta, modifications
        )
    if decision.confidence < config.minimum_confidence:
        modifications.append("CONFIDENCE_BELOW_MINIMUM")
        return _noActionIntent(
            decision, observation, config, targetPosition, rawDelta, modifications
        )
    if rawDelta == 0:
        modifications.append("TARGET_ALREADY_REACHED")
        return _noActionIntent(
            decision, observation, config, targetPosition, rawDelta, modifications
        )

    confidenceScale = decision.confidence
    uncertaintyScale = max(0.0, 1.0 - 0.75 * decision.uncertainty)
    scaledMagnitude = round(abs(rawDelta) * confidenceScale * uncertaintyScale)
    if scaledMagnitude < abs(rawDelta):
        modifications.extend(("CONFIDENCE_SCALE", "UNCERTAINTY_SCALE"))
    if scaledMagnitude == 0:
        modifications.append("SCALED_QUANTITY_ZERO")
        return _noActionIntent(
            decision, observation, config, targetPosition, rawDelta, modifications
        )

    side = IntentSide.BUY if rawDelta > 0 else IntentSide.SELL
    quantityCaps: list[tuple[str, int]] = [
        ("MAX_ORDER_CAP", config.max_order_quantity),
        (
            "PARTICIPATION_CAP",
            math.floor(observation.market.depth_10bps * config.participation_cap),
        ),
    ]
    if side == IntentSide.BUY:
        quantityCaps.extend(
            (
                (
                    "CASH_CAP",
                    observation.portfolio.cash_cents // observation.market.mid_price_ticks,
                ),
                (
                    "POSITION_CAP",
                    observation.portfolio.max_position - observation.portfolio.position,
                ),
            )
        )
    else:
        sellCapacity = (
            observation.portfolio.max_position + observation.portfolio.position
            if config.allow_short_selling
            else max(0, observation.portfolio.position)
        )
        quantityCaps.append(("POSITION_CAP", sellCapacity))

    quantity = scaledMagnitude
    for capName, capValue in quantityCaps:
        safeCap = max(0, capValue)
        if quantity > safeCap:
            quantity = safeCap
            modifications.append(capName)
    if quantity == 0:
        modifications.append("RISK_CAP_BLOCKED_ORDER")
        return _noActionIntent(
            decision,
            observation,
            config,
            targetPosition,
            rawDelta,
            modifications,
            status=IntentStatus.BLOCKED,
        )

    maxSlippageBps = min(
        config.max_slippage_bps,
        max(1, round(10 + decision.urgency * config.max_slippage_bps)),
    )
    orderType, timeInForce, limitPriceTicks = _executionStyle(
        side=side,
        urgency=decision.urgency,
        observation=observation,
        maxSlippageBps=maxSlippageBps,
    )
    approvedDelta = quantity if side == IntentSide.BUY else -quantity
    return CognitiveOrderIntent(
        policy_version=config.policy_version,
        source_decision_hash=canonicalHash(decision),
        agent_id=observation.agent.id,
        instrument_id=observation.market.instrument_id,
        status=IntentStatus.APPROVED,
        target_position=targetPosition,
        delta_quantity_raw=rawDelta,
        delta_quantity_approved=approvedDelta,
        side=side,
        quantity=quantity,
        urgency=decision.urgency,
        max_slippage_bps=maxSlippageBps,
        time_in_force=timeInForce,
        order_type=orderType,
        limit_price_ticks=limitPriceTicks,
        modifications=tuple(dict.fromkeys(modifications)),
    )


def _noActionIntent(
    decision: BeliefDecision,
    observation: Observation,
    config: DeterministicOrderPolicyConfig,
    targetPosition: int,
    rawDelta: int,
    modifications: list[str],
    *,
    status: IntentStatus = IntentStatus.NO_ACTION,
) -> CognitiveOrderIntent:
    return CognitiveOrderIntent(
        policy_version=config.policy_version,
        source_decision_hash=canonicalHash(decision),
        agent_id=observation.agent.id,
        instrument_id=observation.market.instrument_id,
        status=status,
        target_position=targetPosition,
        delta_quantity_raw=rawDelta,
        delta_quantity_approved=0,
        side=IntentSide.NONE,
        quantity=0,
        urgency=decision.urgency,
        max_slippage_bps=0,
        time_in_force=IntentTimeInForce.NONE,
        order_type=IntentOrderType.NONE,
        limit_price_ticks=None,
        modifications=tuple(dict.fromkeys(modifications)),
    )


def _executionStyle(
    *,
    side: IntentSide,
    urgency: float,
    observation: Observation,
    maxSlippageBps: int,
) -> tuple[IntentOrderType, IntentTimeInForce, int]:
    market = observation.market
    if urgency < 0.34:
        priceTicks = (
            market.best_bid_ticks or max(1, market.mid_price_ticks - 1)
            if side == IntentSide.BUY
            else market.best_ask_ticks or market.mid_price_ticks + 1
        )
        return IntentOrderType.PASSIVE_LIMIT, IntentTimeInForce.GTC, priceTicks
    if urgency < 0.7:
        if side == IntentSide.BUY:
            if market.best_bid_ticks is not None and market.best_ask_ticks is not None:
                priceTicks = min(
                    market.best_ask_ticks - 1,
                    market.best_bid_ticks
                    + max(1, (market.best_ask_ticks - market.best_bid_ticks) // 2),
                )
            else:
                priceTicks = market.mid_price_ticks
        elif market.best_bid_ticks is not None and market.best_ask_ticks is not None:
            priceTicks = max(
                market.best_bid_ticks + 1,
                market.best_ask_ticks
                - max(1, (market.best_ask_ticks - market.best_bid_ticks) // 2),
            )
        else:
            priceTicks = market.mid_price_ticks
        return IntentOrderType.AGGRESSIVE_LIMIT, IntentTimeInForce.GTC, max(1, priceTicks)

    # 使用整数 half-up，避免二进制浮点和 bankers rounding 破坏跨平台重放。
    collarNumerator = 10_000 + maxSlippageBps if side == IntentSide.BUY else 10_000 - maxSlippageBps
    priceTicks = (market.mid_price_ticks * collarNumerator + 5_000) // 10_000
    return IntentOrderType.MARKETABLE_LIMIT, IntentTimeInForce.IOC, max(1, priceTicks)
