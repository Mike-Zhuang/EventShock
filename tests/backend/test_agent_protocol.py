from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.app.information.models import SourceTier
from backend.app.simulation.agent_protocol import (
    ActionPreference,
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
    RiskCheckStatus,
    RiskResult,
    RiskStatus,
    TimeInForce,
)

SIM_TIME = datetime(2026, 7, 7, 13, 30, tzinfo=UTC)


def makeObservation(*, position: int = 10, depth: int = 1_000) -> Observation:
    return Observation(
        schemaVersion="1.0.0",
        observationId="observation-1",
        simTime=SIM_TIME,
        agent=AgentDescriptor(
            agentId="agent-1",
            role="event_driven_analyst",
            instrumentId="SPCX",
            riskTolerance=0.6,
            lossAversion=1.5,
            horizonMinutes=120,
            confirmationBias=0.2,
            trustProfile={"official": 0.99},
        ),
        portfolio=PortfolioObservation(
            cashAvailableCents=100_000,
            position=position,
            unrealizedPnlBps=-100,
            maxAbsolutePosition=100,
        ),
        market=MarketObservation(
            bestBidTicks=10_000,
            bestAskTicks=10_010,
            returnOneMinuteBps=-20,
            returnFifteenMinutesBps=-100,
            spreadBps=10,
            depthWithinTenBps=depth,
            orderImbalance=-0.2,
            volatilityRegime="high",
        ),
        newEvidence=(
            EvidenceObservation(
                evidenceId="evidence-1",
                claim="An official event was announced.",
                sourceTier=SourceTier.T1,
                knownAt=SIM_TIME - timedelta(minutes=5),
                credibility=0.99,
            ),
        ),
        allowedActions=tuple(ActionPreference),
    )


def makeDecision(
    *,
    actionPreference: ActionPreference = ActionPreference.INCREASE,
    targetPositionFraction: float = 1.0,
    urgency: float = 0.8,
    uncertainty: float = 0.0,
    confidence: float = 1.0,
) -> BeliefDecision:
    return BeliefDecision(
        schemaVersion="1.0.0",
        decisionId="decision-1",
        direction=BeliefDirection.POSITIVE,
        expectedValueChangeBps=200,
        uncertainty=uncertainty,
        perceivedTailRisk=0.2,
        horizonMinutes=120,
        evidence=(
            EvidenceAssessment(
                evidenceId="evidence-1",
                stance=EvidenceStance.SUPPORTS_UPSIDE,
                weight=0.8,
            ),
        ),
        actionPreference=actionPreference,
        targetPositionFraction=targetPositionFraction,
        urgency=urgency,
        confidence=confidence,
        decisionSummary="Official evidence supports a bounded position increase.",
    )


def makeTranslator() -> DeterministicActionTranslator:
    return DeterministicActionTranslator(
        OrderPolicyConfig(
            policyVersion="order-policy-1.0.0",
            lotSize=5,
            participationCap=0.05,
            maximumSlippageBps=100,
        )
    )


def test_observation_rejects_future_evidence() -> None:
    data = makeObservation().model_dump()
    data["newEvidence"] = (
        EvidenceObservation(
            evidenceId="future",
            claim="Future result",
            sourceTier=SourceTier.T1,
            knownAt=SIM_TIME + timedelta(seconds=1),
            credibility=1.0,
        ),
    )
    with pytest.raises(ValidationError, match="future evidence"):
        Observation.model_validate(data)


def test_translation_is_deterministic_bounded_and_auditable() -> None:
    observation = makeObservation()
    decision = makeDecision()
    translator = makeTranslator()

    first = translator.translate(observation, decision)
    second = translator.translate(observation, decision)

    assert first == second
    assert first.intentId == second.intentId
    assert first.targetPosition == 100
    assert first.deltaQuantityRaw == 90
    assert first.proposedQuantity == 50
    assert first.side is OrderSide.BUY
    assert first.orderStyle is OrderStyle.MARKETABLE_LIMIT
    assert first.timeInForce is TimeInForce.IOC
    assert first.limitPriceTicks == 10_091
    assert [step.step for step in first.trace] == [
        "TARGET_POSITION",
        "RAW_DELTA",
        "PARTICIPATION_AND_LOT_CAP",
        "EXECUTION_STYLE",
        "PRICE_PROTECTION",
    ]


def test_uncertainty_confidence_and_hold_reduce_or_remove_orders() -> None:
    translator = makeTranslator()
    reduced = translator.translate(
        makeObservation(position=0),
        makeDecision(uncertainty=1.0, confidence=0.5, urgency=0.2),
    )
    assert reduced.targetPosition == 13
    assert reduced.orderStyle is OrderStyle.PASSIVE_LIMIT
    assert reduced.proposedQuantity == 10

    held = translator.translate(
        makeObservation(position=10),
        makeDecision(actionPreference=ActionPreference.HOLD),
    )
    assert held.targetPosition == 10
    assert held.deltaQuantityRaw == 0
    assert held.proposedQuantity == 0
    assert held.side is None
    assert held.orderStyle is OrderStyle.NO_ORDER


def test_unseen_evidence_and_disallowed_action_are_rejected() -> None:
    translator = makeTranslator()
    decisionData = makeDecision().model_dump()
    decisionData["evidence"] = (
        EvidenceAssessment(
            evidenceId="unseen",
            stance=EvidenceStance.SUPPORTS_UPSIDE,
            weight=0.5,
        ),
    )
    with pytest.raises(ValueError, match="unseen evidence"):
        translator.translate(
            makeObservation(),
            BeliefDecision.model_validate(decisionData),
        )

    observationData = makeObservation().model_dump()
    observationData["allowedActions"] = (ActionPreference.HOLD,)
    with pytest.raises(ValueError, match="not allowed"):
        translator.translate(
            Observation.model_validate(observationData),
            makeDecision(),
        )


def test_risk_result_enforces_approved_and_rejected_shapes() -> None:
    approved = RiskResult(
        intentId="intent-1",
        status=RiskStatus.APPROVED_WITH_MODIFICATION,
        approvedQuantity=10,
        orderStyle=OrderStyle.MARKETABLE_LIMIT,
        limitPriceTicks=10_000,
        modifications=("PARTICIPATION_CAP",),
        checks={
            "cash": RiskCheckStatus.PASS,
            "maxOrder": RiskCheckStatus.MODIFIED,
        },
    )
    assert approved.approvedQuantity == 10

    rejected = RiskResult(
        intentId="intent-2",
        status=RiskStatus.REJECTED,
        approvedQuantity=0,
        orderStyle=OrderStyle.NO_ORDER,
        checks={"cash": RiskCheckStatus.FAIL},
        rejectionReason="insufficient cash",
    )
    assert rejected.status is RiskStatus.REJECTED
    with pytest.raises(ValidationError, match="rejectionReason"):
        RiskResult(
            intentId="intent-3",
            status=RiskStatus.REJECTED,
            approvedQuantity=0,
            orderStyle=OrderStyle.NO_ORDER,
            checks={"cash": RiskCheckStatus.FAIL},
        )
    with pytest.raises(ValidationError, match="cannot contain modifications"):
        RiskResult(
            intentId="intent-4",
            status=RiskStatus.APPROVED,
            approvedQuantity=1,
            orderStyle=OrderStyle.PASSIVE_LIMIT,
            limitPriceTicks=10_000,
            modifications=("UNEXPECTED",),
            checks={"cash": RiskCheckStatus.PASS},
        )
