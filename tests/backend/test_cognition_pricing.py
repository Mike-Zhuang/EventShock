from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_UP, Decimal

import pytest
from pydantic import BaseModel

from backend.app.cognition import (
    FailureCode,
    ModelCostBudget,
    ModelGatewayError,
    ModelPolicy,
    ModelRequest,
    ModelResult,
    ModelUsage,
    SamplingConfig,
    SessionConfigStore,
    estimateReservation,
    getTokenPrice,
    getTokenPriceSnapshot,
    getZhipuTokenPrice,
    pricingSnapshotStatus,
    sha256Text,
    usageCostUpperBoundUsd,
)


class _ResultPayload(BaseModel):
    value: str


def _request(*, model: str = "glm-5.2", maxTokens: int = 2_048) -> ModelRequest:
    systemPrompt = "Return one strict JSON object."
    return ModelRequest(
        provider="zhipu",
        model=model,
        requestId="request-cost-001",
        userId="anonymous-cost-user-001",
        systemPrompt=systemPrompt,
        userContent="Use only evidence item evidence-001.",
        promptHash=sha256Text(systemPrompt),
        schemaVersion="cost_test_v1",
        agentConfigHash="a" * 64,
        observationHash="b" * 64,
        allowedEvidenceIds=frozenset({"evidence-001"}),
        samplingConfig=SamplingConfig(max_tokens=maxTokens),
        apiKey="test-cost-secret-key",
    )


def _result(
    usage: ModelUsage,
    *,
    cacheHit: bool = False,
    transportAttempts: int = 1,
    uncertainBillableAttempts: int = 0,
) -> ModelResult[_ResultPayload]:
    return ModelResult(
        data=_ResultPayload(value="ok"),
        provider="zhipu",
        model="glm-5.2",
        requestId="request-cost-001",
        promptHash="a" * 64,
        responseHash="b" * 64,
        cacheKey="c" * 64,
        usage=usage,
        latencyMs=5.0,
        transportAttempts=transportAttempts,
        repairUsed=False,
        fallbackUsed=False,
        cacheHit=cacheHit,
        uncertainBillableAttempts=uncertainBillableAttempts,
    )


def test_official_price_snapshot_is_explicit_and_unknown_prices_fail_closed() -> None:
    glm52 = getZhipuTokenPrice("glm-5.2")
    assert glm52 is not None
    assert glm52.inputCnyPerMillion == Decimal("8")
    assert glm52.outputCnyPerMillion == Decimal("28")
    assert getZhipuTokenPrice("glm-4.7-flash").free is True  # type: ignore[union-attr]
    assert getZhipuTokenPrice("glm-4.6") is None

    with pytest.raises(ValueError, match="no verified public token price"):
        SessionConfigStore().setConfig(
            sessionId="session-price-unknown-001",
            apiKey="test-price-secret-key",
            model="glm-4.6",
        )


def test_expired_price_snapshot_fails_closed_with_an_injected_clock() -> None:
    def freshClock() -> datetime:
        return datetime(2026, 7, 29, tzinfo=UTC)

    def staleClock() -> datetime:
        return datetime(2026, 8, 21, tzinfo=UTC)

    currentPrice = getTokenPrice("zhipu", "glm-5.2", clock=freshClock)
    rawSnapshot = getTokenPriceSnapshot("zhipu", "glm-5.2")
    assert currentPrice is not None
    assert rawSnapshot is not None
    assert rawSnapshot.validUntil == "2026-08-20T00:00:00Z"
    assert pricingSnapshotStatus(clock=freshClock) == "CURRENT"
    assert getTokenPrice("zhipu", "glm-5.2", clock=staleClock) is None
    assert getZhipuTokenPrice("glm-5.2", clock=staleClock) is None
    assert pricingSnapshotStatus(clock=staleClock) == "STALE_FAIL_CLOSED"

    with pytest.raises(ModelGatewayError) as staleReservation:
        ModelCostBudget(100, clock=staleClock).reserve(_request(), ModelPolicy())
    assert staleReservation.value.code == FailureCode.MODEL_PRICING_UNAVAILABLE


def test_snapshot_expiry_during_an_active_reservation_consumes_the_full_bound() -> None:
    now = [datetime(2026, 7, 29, tzinfo=UTC)]

    def mutableClock() -> datetime:
        return now[0]

    budget = ModelCostBudget(10, clock=mutableClock)
    reservation = budget.reserve(_request(), ModelPolicy())
    now[0] = datetime(2026, 8, 21, tzinfo=UTC)

    with pytest.raises(ModelGatewayError) as staleSettlement:
        budget.settle(
            reservation,
            _result(ModelUsage(promptTokens=1_000, completionTokens=500)),
        )

    assert staleSettlement.value.code == FailureCode.MODEL_PRICING_UNAVAILABLE
    assert budget.snapshot()["chargedUsdUpperBound"] == float(reservation.maximumUsd)
    assert budget.snapshot()["unknownUsageCalls"] == 1


def test_full_context_and_one_repair_define_pre_dispatch_reservation() -> None:
    reservation = estimateReservation(
        modelId="glm-5.2",
        maxOutputTokens=2_048,
        policy=ModelPolicy(),
    )

    assert reservation.maximumBillableResponses == 6
    assert reservation.maximumPromptTokens == 1_000_000 * 6
    assert reservation.maximumCompletionTokens == 2_048 * 6
    assert reservation.maximumUsd == Decimal("8.057344000")


def test_budget_reserves_before_dispatch_and_settles_reported_usage() -> None:
    budget = ModelCostBudget(8.057344)
    request = _request()
    reservation = budget.reserve(request, ModelPolicy())

    with pytest.raises(ModelGatewayError) as blocked:
        budget.reserve(request, ModelPolicy())
    assert blocked.value.code == FailureCode.MODEL_COST_BUDGET_EXCEEDED

    usage = ModelUsage(promptTokens=1_000, completionTokens=500, cachedTokens=100)
    settlement = budget.settle(reservation, _result(usage))
    snapshot = budget.snapshot()

    assert settlement.chargedUsdUpperBound == Decimal("0.003666667")
    assert usageCostUpperBoundUsd("glm-5.2", usage) == settlement.chargedUsdUpperBound
    assert snapshot["chargedUsdUpperBound"] == pytest.approx(0.003666667)
    assert snapshot["remainingUsd"] == pytest.approx(8.053677333)
    assert snapshot["actualPromptTokens"] == 1_000
    assert snapshot["actualCompletionTokens"] == 500
    assert snapshot["cachedPromptTokens"] == 100
    assert snapshot["settledCalls"] == 1
    assert snapshot["blockedCalls"] == 1
    assert snapshot["activeReservationUsd"] == 0


def test_missing_usage_consumes_reservation_and_cannot_be_reused() -> None:
    reservationAmount = estimateReservation(
        modelId="glm-5.2",
        maxOutputTokens=2_048,
        policy=ModelPolicy(),
    ).maximumUsd
    budget = ModelCostBudget(reservationAmount)
    request = _request()
    reservation = budget.reserve(request, ModelPolicy())

    with pytest.raises(ModelGatewayError) as missing:
        budget.settle(reservation, _result(ModelUsage()))
    assert missing.value.code == FailureCode.MODEL_USAGE_MISSING
    snapshot = budget.snapshot()
    assert snapshot["chargedUsdUpperBound"] == float(reservationAmount)
    assert snapshot["remainingUsd"] == 0
    assert snapshot["unknownUsageCalls"] == 1

    with pytest.raises(ModelGatewayError) as blocked:
        budget.reserve(request, ModelPolicy())
    assert blocked.value.code == FailureCode.MODEL_COST_BUDGET_EXCEEDED


def test_free_model_allows_zero_cap_but_unpriced_model_never_reserves() -> None:
    freeBudget = ModelCostBudget(0)
    freeRequest = _request(model="glm-4.7-flash")
    freeReservation = freeBudget.reserve(freeRequest, ModelPolicy())
    freeBudget.settle(
        freeReservation,
        _result(ModelUsage(promptTokens=500, completionTokens=100)),
    )
    assert freeBudget.snapshot()["chargedUsdUpperBound"] == 0

    with pytest.raises(ModelGatewayError) as unavailable:
        ModelCostBudget(100).reserve(_request(model="glm-4.6"), ModelPolicy())
    assert unavailable.value.code == FailureCode.MODEL_PRICING_UNAVAILABLE


def test_cache_hit_releases_reservation_without_token_charge() -> None:
    budget = ModelCostBudget(10)
    reservation = budget.reserve(_request(), ModelPolicy())
    settlement = budget.settle(
        reservation,
        _result(ModelUsage(), cacheHit=True, transportAttempts=0),
    )
    assert settlement.chargedUsdUpperBound == 0
    assert budget.snapshot()["remainingUsd"] == 10


def test_uncertain_transport_attempt_keeps_its_worst_case_budget_charge() -> None:
    reservationAmount = estimateReservation(
        modelId="glm-5.2",
        maxOutputTokens=2_048,
        policy=ModelPolicy(),
    ).maximumUsd
    budget = ModelCostBudget(reservationAmount)
    reservation = budget.reserve(_request(), ModelPolicy())
    usage = ModelUsage(promptTokens=1_000, completionTokens=500, cachedTokens=100)

    settlement = budget.settle(
        reservation,
        _result(
            usage,
            transportAttempts=2,
            uncertainBillableAttempts=1,
        ),
    )
    expectedUnknownCharge = (reservationAmount / Decimal(6)).quantize(
        Decimal("0.000000001"),
        rounding=ROUND_UP,
    )
    expectedCharge = usageCostUpperBoundUsd("glm-5.2", usage) + expectedUnknownCharge
    snapshot = budget.snapshot()

    assert settlement.chargedUsdUpperBound == expectedCharge
    assert snapshot["chargedUsdUpperBound"] == float(expectedCharge)
    assert snapshot["unknownUsageCalls"] == 1
    assert snapshot["remainingUsd"] == float(reservationAmount - expectedCharge)


def test_invalid_uncertain_attempt_metadata_consumes_the_full_reservation() -> None:
    reservationAmount = estimateReservation(
        modelId="glm-5.2",
        maxOutputTokens=2_048,
        policy=ModelPolicy(),
    ).maximumUsd
    budget = ModelCostBudget(reservationAmount)
    reservation = budget.reserve(_request(), ModelPolicy())

    with pytest.raises(ModelGatewayError) as invalid:
        budget.settle(
            reservation,
            _result(
                ModelUsage(promptTokens=1_000, completionTokens=500),
                transportAttempts=1,
                uncertainBillableAttempts=2,
            ),
        )

    assert invalid.value.code == FailureCode.MODEL_USAGE_MISSING
    assert budget.snapshot()["chargedUsdUpperBound"] == float(reservationAmount)
