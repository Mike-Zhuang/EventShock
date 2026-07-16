"""规则智能体与 LLM 智能体共享的观察、决策和订单意图协议。

模型只能产生 ``BeliefDecision``。``DeterministicActionTranslator`` 使用固定政策把
目标仓位转换为 ``ActionIntent``，风险引擎再返回 ``RiskResult``；任何认知实现都
不能直接写账本或设置价格。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.information.models import SourceTier


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BeliefDirection(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


class ActionPreference(StrEnum):
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    HOLD = "HOLD"
    EXIT = "EXIT"
    ABSTAIN = "ABSTAIN"
    POST_ONLY = "POST_ONLY"


class EvidenceStance(StrEnum):
    SUPPORTS_UPSIDE = "SUPPORTS_UPSIDE"
    SUPPORTS_DOWNSIDE = "SUPPORTS_DOWNSIDE"
    NEUTRAL = "NEUTRAL"
    CONTRADICTS = "CONTRADICTS"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class TimeInForce(StrEnum):
    GTC = "GTC"
    DAY = "DAY"
    IOC = "IOC"


class OrderStyle(StrEnum):
    NO_ORDER = "NO_ORDER"
    PASSIVE_LIMIT = "PASSIVE_LIMIT"
    NEAR_TOUCH_LIMIT = "NEAR_TOUCH_LIMIT"
    MARKETABLE_LIMIT = "MARKETABLE_LIMIT"


class RiskStatus(StrEnum):
    APPROVED = "APPROVED"
    APPROVED_WITH_MODIFICATION = "APPROVED_WITH_MODIFICATION"
    REJECTED = "REJECTED"


class RiskCheckStatus(StrEnum):
    PASS = "PASS"
    MODIFIED = "MODIFIED"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AgentDescriptor(StrictModel):
    agentId: str = Field(min_length=1)
    role: str = Field(min_length=1)
    instrumentId: str = Field(min_length=1)
    riskTolerance: float = Field(ge=0.0, le=1.0)
    lossAversion: float = Field(ge=0.0)
    horizonMinutes: int = Field(ge=1, le=525_600)
    confirmationBias: float = Field(ge=0.0, le=1.0)
    trustProfile: dict[str, float] = Field(default_factory=dict)

    @field_validator("trustProfile")
    @classmethod
    def validateTrustProfile(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not key for key in values):
            raise ValueError("trustProfile keys must not be empty")
        if any(not 0.0 <= value <= 1.0 for value in values.values()):
            raise ValueError("trustProfile values must be between 0 and 1")
        return dict(values)


class PortfolioObservation(StrictModel):
    cashAvailableCents: int = Field(ge=0)
    position: int
    reservedPosition: int = Field(default=0, ge=0)
    unrealizedPnlBps: int
    maxAbsolutePosition: int = Field(ge=0)

    @model_validator(mode="after")
    def validateReservedPosition(self) -> PortfolioObservation:
        if self.reservedPosition > max(0, self.position):
            raise ValueError("reservedPosition cannot exceed the available long position")
        if abs(self.position) > self.maxAbsolutePosition:
            raise ValueError("position exceeds maxAbsolutePosition")
        return self


class MarketObservation(StrictModel):
    bestBidTicks: int = Field(gt=0)
    bestAskTicks: int = Field(gt=0)
    returnOneMinuteBps: int
    returnFifteenMinutesBps: int
    spreadBps: int = Field(ge=0)
    depthWithinTenBps: int = Field(ge=0)
    orderImbalance: float = Field(ge=-1.0, le=1.0)
    volatilityRegime: str = Field(min_length=1)

    @model_validator(mode="after")
    def validateBook(self) -> MarketObservation:
        if self.bestBidTicks >= self.bestAskTicks:
            raise ValueError("bestBidTicks must be below bestAskTicks")
        return self


class EvidenceObservation(StrictModel):
    evidenceId: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    sourceTier: SourceTier
    knownAt: datetime
    credibility: float = Field(ge=0.0, le=1.0)

    @field_validator("knownAt")
    @classmethod
    def validateKnownAt(cls, value: datetime) -> datetime:
        _requireAware(value, "knownAt")
        return value


class SocialPostObservation(StrictModel):
    postId: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=1_000)
    authorTrust: float = Field(ge=0.0, le=1.0)
    seenAt: datetime
    evidenceIds: tuple[str, ...] = ()

    @field_validator("seenAt")
    @classmethod
    def validateSeenAt(cls, value: datetime) -> datetime:
        _requireAware(value, "seenAt")
        return value


class MemoryObservation(StrictModel):
    memoryId: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=500)
    salience: float = Field(ge=0.0, le=1.0)
    validFrom: datetime

    @field_validator("validFrom")
    @classmethod
    def validateValidFrom(cls, value: datetime) -> datetime:
        _requireAware(value, "validFrom")
        return value


class Observation(StrictModel):
    """传给任一认知实现的最小、点时安全观察。"""

    schemaVersion: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    observationId: str = Field(min_length=1)
    simTime: datetime
    agent: AgentDescriptor
    portfolio: PortfolioObservation
    market: MarketObservation
    newEvidence: tuple[EvidenceObservation, ...] = ()
    socialFeed: tuple[SocialPostObservation, ...] = ()
    memorySummary: tuple[MemoryObservation, ...] = ()
    allowedActions: tuple[ActionPreference, ...]

    @field_validator("simTime")
    @classmethod
    def validateSimTime(cls, value: datetime) -> datetime:
        _requireAware(value, "simTime")
        return value

    @model_validator(mode="after")
    def validatePointInTimeBoundary(self) -> Observation:
        if not self.allowedActions:
            raise ValueError("allowedActions must not be empty")
        if len(set(self.allowedActions)) != len(self.allowedActions):
            raise ValueError("allowedActions must not contain duplicates")
        evidenceIds = [evidence.evidenceId for evidence in self.newEvidence]
        if len(set(evidenceIds)) != len(evidenceIds):
            raise ValueError("newEvidence contains duplicate evidence IDs")
        futureEvidence = [
            evidence.evidenceId for evidence in self.newEvidence if evidence.knownAt > self.simTime
        ]
        if futureEvidence:
            raise ValueError(f"observation contains future evidence: {sorted(futureEvidence)}")
        futurePosts = [post.postId for post in self.socialFeed if post.seenAt > self.simTime]
        if futurePosts:
            raise ValueError(f"observation contains future social posts: {sorted(futurePosts)}")
        futureMemories = [
            memory.memoryId for memory in self.memorySummary if memory.validFrom > self.simTime
        ]
        if futureMemories:
            raise ValueError(f"observation contains future memories: {sorted(futureMemories)}")
        visibleEvidenceIds = set(evidenceIds)
        unknownPostEvidence = {
            evidenceId
            for post in self.socialFeed
            for evidenceId in post.evidenceIds
            if evidenceId not in visibleEvidenceIds
        }
        if unknownPostEvidence:
            raise ValueError(
                f"social posts reference unseen evidence: {sorted(unknownPostEvidence)}"
            )
        return self


class EvidenceAssessment(StrictModel):
    evidenceId: str = Field(min_length=1)
    stance: EvidenceStance
    weight: float = Field(ge=0.0, le=1.0)


class BeliefDecision(StrictModel):
    """认知层的结构化输出，不包含可直接成交的订单。"""

    schemaVersion: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    decisionId: str = Field(min_length=1)
    direction: BeliefDirection
    expectedValueChangeBps: int = Field(ge=-10_000, le=10_000)
    uncertainty: float = Field(ge=0.0, le=1.0)
    perceivedTailRisk: float = Field(ge=0.0, le=1.0)
    horizonMinutes: int = Field(ge=1, le=10_080)
    evidence: tuple[EvidenceAssessment, ...] = ()
    actionPreference: ActionPreference
    targetPositionFraction: float = Field(ge=-1.0, le=1.0)
    urgency: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    decisionSummary: str = Field(min_length=1, max_length=500)
    publicMessage: str | None = Field(default=None, max_length=500)
    abstainReason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validateActionSemantics(self) -> BeliefDecision:
        evidenceIds = [assessment.evidenceId for assessment in self.evidence]
        if len(set(evidenceIds)) != len(evidenceIds):
            raise ValueError("evidence assessments must not contain duplicate IDs")
        if self.actionPreference is ActionPreference.ABSTAIN and not self.abstainReason:
            raise ValueError("ABSTAIN requires abstainReason")
        if self.actionPreference is not ActionPreference.ABSTAIN and self.abstainReason:
            raise ValueError("abstainReason is only valid for ABSTAIN")
        return self


class TranslationStep(StrictModel):
    step: str = Field(min_length=1)
    inputValue: str
    outputValue: str
    reason: str = Field(min_length=1)


class ActionIntent(StrictModel):
    """确定性政策的输出；它仍需通过风险引擎，不能直接进入账本。"""

    intentId: str = Field(min_length=1)
    agentId: str = Field(min_length=1)
    sourceDecisionId: str = Field(min_length=1)
    instrumentId: str = Field(min_length=1)
    targetPosition: int
    deltaQuantityRaw: int
    side: OrderSide | None
    proposedQuantity: int = Field(ge=0)
    orderStyle: OrderStyle
    limitPriceTicks: int | None = Field(default=None, gt=0)
    urgency: float = Field(ge=0.0, le=1.0)
    maxSlippageBps: int = Field(ge=0)
    timeInForce: TimeInForce
    generatedByPolicyVersion: str = Field(min_length=1)
    trace: tuple[TranslationStep, ...]

    @model_validator(mode="after")
    def validateOrderPresence(self) -> ActionIntent:
        noOrder = self.proposedQuantity == 0
        if noOrder and any(
            (
                self.side is not None,
                self.orderStyle is not OrderStyle.NO_ORDER,
                self.limitPriceTicks is not None,
            )
        ):
            raise ValueError("a zero-quantity intent must use NO_ORDER and no side or price")
        if not noOrder and any(
            (
                self.side is None,
                self.orderStyle is OrderStyle.NO_ORDER,
                self.limitPriceTicks is None,
            )
        ):
            raise ValueError("an executable intent requires side, style and limit price")
        return self


class RiskResult(StrictModel):
    """风险引擎对意图的统一输出。"""

    intentId: str = Field(min_length=1)
    status: RiskStatus
    approvedQuantity: int = Field(ge=0)
    orderStyle: OrderStyle
    limitPriceTicks: int | None = Field(default=None, gt=0)
    modifications: tuple[str, ...] = ()
    checks: dict[str, RiskCheckStatus]
    rejectionReason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validateRiskOutcome(self) -> RiskResult:
        if not self.checks:
            raise ValueError("risk checks must not be empty")
        if self.status is RiskStatus.REJECTED:
            if self.approvedQuantity != 0 or not self.rejectionReason:
                raise ValueError("REJECTED requires zero quantity and rejectionReason")
            if self.orderStyle is not OrderStyle.NO_ORDER or self.limitPriceTicks is not None:
                raise ValueError("REJECTED must not contain an executable order")
        else:
            if self.approvedQuantity <= 0:
                raise ValueError("an approved result requires positive quantity")
            if self.orderStyle is OrderStyle.NO_ORDER or self.limitPriceTicks is None:
                raise ValueError("an approved result requires style and limit price")
        if self.status is RiskStatus.APPROVED_WITH_MODIFICATION and not self.modifications:
            raise ValueError("APPROVED_WITH_MODIFICATION requires modifications")
        if self.status is RiskStatus.APPROVED and self.modifications:
            raise ValueError("APPROVED cannot contain modifications")
        return self


class OrderPolicyConfig(StrictModel):
    policyVersion: str = Field(min_length=1)
    lotSize: int = Field(default=1, ge=1)
    participationCap: float = Field(default=0.05, gt=0.0, le=1.0)
    lowUrgencyThreshold: float = Field(default=0.35, ge=0.0, le=1.0)
    highUrgencyThreshold: float = Field(default=0.75, ge=0.0, le=1.0)
    maximumSlippageBps: int = Field(default=100, ge=0, le=10_000)
    uncertaintyPenalty: float = Field(default=0.75, ge=0.0, le=1.0)
    minimumSizingMultiplier: float = Field(default=0.1, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validateThresholds(self) -> OrderPolicyConfig:
        if self.lowUrgencyThreshold >= self.highUrgencyThreshold:
            raise ValueError("lowUrgencyThreshold must be below highUrgencyThreshold")
        return self


@runtime_checkable
class CognitiveAgentProtocol(Protocol):
    """规则与 LLM 认知实现必须共同满足的异步接口。"""

    @property
    def agentId(self) -> str: ...

    async def decide(self, observation: Observation) -> BeliefDecision: ...


@runtime_checkable
class ActionTranslatorProtocol(Protocol):
    def translate(
        self,
        observation: Observation,
        decision: BeliefDecision,
    ) -> ActionIntent: ...


@runtime_checkable
class RiskEngineProtocol(Protocol):
    def evaluate(self, observation: Observation, intent: ActionIntent) -> RiskResult: ...


class DeterministicActionTranslator:
    """把结构化认知结果转成可审计订单意图的固定政策。"""

    def __init__(self, config: OrderPolicyConfig) -> None:
        self.config = config

    def translate(
        self,
        observation: Observation,
        decision: BeliefDecision,
    ) -> ActionIntent:
        validateDecisionEvidence(observation, decision)
        if decision.actionPreference not in observation.allowedActions:
            raise ValueError(
                f"action {decision.actionPreference.value} is not allowed by the observation"
            )
        trace: list[TranslationStep] = []
        currentPosition = observation.portfolio.position
        maximumPosition = observation.portfolio.maxAbsolutePosition
        if decision.actionPreference in {
            ActionPreference.HOLD,
            ActionPreference.ABSTAIN,
            ActionPreference.POST_ONLY,
        }:
            targetPosition = currentPosition
            sizingMultiplier = Decimal(0)
        elif decision.actionPreference is ActionPreference.EXIT:
            targetPosition = 0
            sizingMultiplier = Decimal(1)
        else:
            uncertaintyMultiplier = max(
                Decimal(str(self.config.minimumSizingMultiplier)),
                Decimal(1)
                - Decimal(str(decision.uncertainty)) * Decimal(str(self.config.uncertaintyPenalty)),
            )
            confidenceMultiplier = max(
                Decimal(str(self.config.minimumSizingMultiplier)),
                Decimal(str(decision.confidence)),
            )
            sizingMultiplier = uncertaintyMultiplier * confidenceMultiplier
            rawTarget = (
                Decimal(str(decision.targetPositionFraction))
                * Decimal(maximumPosition)
                * sizingMultiplier
            )
            targetPosition = _roundHalfAwayFromZero(rawTarget)
        targetPosition = max(-maximumPosition, min(maximumPosition, targetPosition))
        trace.append(
            TranslationStep(
                step="TARGET_POSITION",
                inputValue=str(decision.targetPositionFraction),
                outputValue=str(targetPosition),
                reason=f"confidence/uncertainty multiplier={sizingMultiplier}",
            )
        )

        deltaQuantityRaw = targetPosition - currentPosition
        trace.append(
            TranslationStep(
                step="RAW_DELTA",
                inputValue=f"target={targetPosition},current={currentPosition}",
                outputValue=str(deltaQuantityRaw),
                reason="目标仓位减当前仓位",
            )
        )
        maximumParticipationQuantity = _roundDownToLot(
            int(
                Decimal(observation.market.depthWithinTenBps)
                * Decimal(str(self.config.participationCap))
            ),
            self.config.lotSize,
        )
        proposedQuantity = min(abs(deltaQuantityRaw), maximumParticipationQuantity)
        proposedQuantity = _roundDownToLot(proposedQuantity, self.config.lotSize)
        trace.append(
            TranslationStep(
                step="PARTICIPATION_AND_LOT_CAP",
                inputValue=str(abs(deltaQuantityRaw)),
                outputValue=str(proposedQuantity),
                reason=(f"depth cap={maximumParticipationQuantity}, lotSize={self.config.lotSize}"),
            )
        )

        if proposedQuantity == 0:
            return self._noOrderIntent(
                observation,
                decision,
                targetPosition,
                deltaQuantityRaw,
                trace,
            )

        side = OrderSide.BUY if deltaQuantityRaw > 0 else OrderSide.SELL
        orderStyle, timeInForce = self._executionStyle(decision.urgency)
        maxSlippageBps = _roundHalfAwayFromZero(
            Decimal(self.config.maximumSlippageBps) * Decimal(str(decision.urgency))
        )
        limitPriceTicks = self._limitPrice(
            side,
            orderStyle,
            observation.market,
            maxSlippageBps,
        )
        trace.append(
            TranslationStep(
                step="EXECUTION_STYLE",
                inputValue=str(decision.urgency),
                outputValue=f"{orderStyle.value}/{timeInForce.value}",
                reason="固定 urgency 阈值",
            )
        )
        trace.append(
            TranslationStep(
                step="PRICE_PROTECTION",
                inputValue=f"bid={observation.market.bestBidTicks},ask={observation.market.bestAskTicks}",
                outputValue=str(limitPriceTicks),
                reason=f"maxSlippageBps={maxSlippageBps}",
            )
        )
        intentId = self._intentId(observation, decision)
        return ActionIntent(
            intentId=intentId,
            agentId=observation.agent.agentId,
            sourceDecisionId=decision.decisionId,
            instrumentId=observation.agent.instrumentId,
            targetPosition=targetPosition,
            deltaQuantityRaw=deltaQuantityRaw,
            side=side,
            proposedQuantity=proposedQuantity,
            orderStyle=orderStyle,
            limitPriceTicks=limitPriceTicks,
            urgency=decision.urgency,
            maxSlippageBps=maxSlippageBps,
            timeInForce=timeInForce,
            generatedByPolicyVersion=self.config.policyVersion,
            trace=tuple(trace),
        )

    def _noOrderIntent(
        self,
        observation: Observation,
        decision: BeliefDecision,
        targetPosition: int,
        deltaQuantityRaw: int,
        trace: list[TranslationStep],
    ) -> ActionIntent:
        return ActionIntent(
            intentId=self._intentId(observation, decision),
            agentId=observation.agent.agentId,
            sourceDecisionId=decision.decisionId,
            instrumentId=observation.agent.instrumentId,
            targetPosition=targetPosition,
            deltaQuantityRaw=deltaQuantityRaw,
            side=None,
            proposedQuantity=0,
            orderStyle=OrderStyle.NO_ORDER,
            limitPriceTicks=None,
            urgency=decision.urgency,
            maxSlippageBps=0,
            timeInForce=TimeInForce.DAY,
            generatedByPolicyVersion=self.config.policyVersion,
            trace=tuple(trace),
        )

    def _executionStyle(self, urgency: float) -> tuple[OrderStyle, TimeInForce]:
        if urgency < self.config.lowUrgencyThreshold:
            return OrderStyle.PASSIVE_LIMIT, TimeInForce.GTC
        if urgency < self.config.highUrgencyThreshold:
            return OrderStyle.NEAR_TOUCH_LIMIT, TimeInForce.DAY
        return OrderStyle.MARKETABLE_LIMIT, TimeInForce.IOC

    @staticmethod
    def _limitPrice(
        side: OrderSide,
        orderStyle: OrderStyle,
        market: MarketObservation,
        maxSlippageBps: int,
    ) -> int:
        if orderStyle is OrderStyle.PASSIVE_LIMIT:
            return market.bestBidTicks if side is OrderSide.BUY else market.bestAskTicks
        if orderStyle is OrderStyle.NEAR_TOUCH_LIMIT:
            return market.bestAskTicks if side is OrderSide.BUY else market.bestBidTicks
        if side is OrderSide.BUY:
            protectedPrice = Decimal(market.bestAskTicks) * (
                Decimal(10_000 + maxSlippageBps) / Decimal(10_000)
            )
            return int(protectedPrice.to_integral_value(rounding=ROUND_CEILING))
        protectedPrice = Decimal(market.bestBidTicks) * (
            Decimal(10_000 - maxSlippageBps) / Decimal(10_000)
        )
        return max(1, int(protectedPrice.to_integral_value(rounding=ROUND_FLOOR)))

    def _intentId(self, observation: Observation, decision: BeliefDecision) -> str:
        payload = {
            "observation": observation.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
            "policy": self.config.model_dump(mode="json"),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        return f"intent-{digest}"


def validateDecisionEvidence(
    observation: Observation,
    decision: BeliefDecision,
) -> None:
    """确认决策引用的证据全部出现在当前观察中。"""

    visibleEvidenceIds = {evidence.evidenceId for evidence in observation.newEvidence}
    assessedEvidenceIds = {assessment.evidenceId for assessment in decision.evidence}
    unknownEvidenceIds = assessedEvidenceIds - visibleEvidenceIds
    if unknownEvidenceIds:
        raise ValueError(f"decision references unseen evidence: {sorted(unknownEvidenceIds)}")
    if (
        decision.actionPreference is not ActionPreference.ABSTAIN
        and visibleEvidenceIds
        and not assessedEvidenceIds
    ):
        raise ValueError("a non-abstaining decision must assess visible evidence")


def _roundHalfAwayFromZero(value: Decimal) -> int:
    if value >= 0:
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return -int((-value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _roundDownToLot(quantity: int, lotSize: int) -> int:
    if quantity <= 0:
        return 0
    return quantity - quantity % lotSize


def _requireAware(value: datetime, fieldName: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{fieldName} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{fieldName} must be timezone-aware")
