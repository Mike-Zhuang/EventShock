import math
from datetime import UTC, datetime

import pytest

from backend.app.validation.ladder import (
    EvidenceStatus,
    EvidenceType,
    LevelStatus,
    ValidationEvidence,
    ValidationLadder,
    ValidationLevel,
)
from backend.app.validation.statistics import (
    TailDirection,
    analyzePairedExperiment,
    bootstrap95ConfidenceInterval,
    empiricalTailProbability,
    evaluateKnockout,
    evaluateNegativeControl,
    holmBonferroni,
    rankCorrelationSensitivity,
)


def makeEvidence(evidenceId: str) -> ValidationEvidence:
    return ValidationEvidence(
        evidenceId=evidenceId,
        evidenceType=EvidenceType.TEST_REPORT,
        title="Deterministic invariant test report",
        artifactUri=f"artifacts/{evidenceId}.json",
        artifactHash=f"sha256:{'a' * 64}",
        recordedAt=datetime(2026, 7, 15, tzinfo=UTC),
        reviewer="independent-reviewer",
        status=EvidenceStatus.VERIFIED,
        summary="All preregistered invariant checks passed.",
    )


def test_bootstrap_interval_is_deterministic_and_contains_estimate() -> None:
    values = (-2.0, -1.0, 0.0, 1.0, 4.0, 5.0)
    first = bootstrap95ConfidenceInterval(values, resamples=1_000, seed=719)
    second = bootstrap95ConfidenceInterval(values, resamples=1_000, seed=719)

    assert first == second
    assert first.lower <= first.estimate <= first.upper
    assert first.confidenceLevel == 0.95
    constant = bootstrap95ConfidenceInterval((3.0, 3.0, 3.0), resamples=100)
    assert (constant.lower, constant.upper) == (3.0, 3.0)


def test_paired_analysis_effect_size_tail_and_sign_are_consistent() -> None:
    baseline = (10.0, 11.0, 9.0, 12.0, 8.0)
    intervention = (12.0, 12.0, 12.0, 14.0, 10.0)
    analysis = analyzePairedExperiment(
        baseline,
        intervention,
        bootstrapResamples=500,
        seed=3,
    )

    assert analysis.differences == (2.0, 1.0, 3.0, 2.0, 2.0)
    assert analysis.meanDifference == 2.0
    assert analysis.medianDifference == 2.0
    assert analysis.signConsistency == 1.0
    assert analysis.effectSize.cohensDz is not None
    assert analysis.effectSize.cohensDz > 0
    tail = empiricalTailProbability(
        analysis.differences,
        threshold=2.0,
        direction=TailDirection.GREATER_EQUAL,
    )
    assert tail.exceedanceCount == 4
    assert tail.probability == 0.8


def test_holm_bonferroni_is_monotone_and_stops_after_first_failure() -> None:
    results = holmBonferroni(
        {"h1": 0.001, "h2": 0.02, "h3": 0.03, "h4": 0.5},
        alpha=0.05,
    )
    byId = {result.hypothesisId: result for result in results}

    assert byId["h1"].rejected
    assert not byId["h2"].rejected
    assert not byId["h3"].rejected
    assert not byId["h4"].rejected
    adjusted = [result.adjustedPValue for result in results]
    assert adjusted == sorted(adjusted)


def test_rank_sensitivity_reports_direction_and_normalized_importance() -> None:
    outcomes = (1.0, 2.0, 3.0, 4.0, 5.0)
    results = rankCorrelationSensitivity(
        {
            "liquidity": (10.0, 20.0, 30.0, 40.0, 50.0),
            "delay": (5.0, 4.0, 3.0, 2.0, 1.0),
            "constant": (1.0, 1.0, 1.0, 1.0, 1.0),
        },
        outcomes,
    )
    byParameter = {result.parameter: result for result in results}

    assert byParameter["liquidity"].spearmanCorrelation == pytest.approx(1.0)
    assert byParameter["delay"].spearmanCorrelation == pytest.approx(-1.0)
    assert byParameter["constant"].spearmanCorrelation == 0.0
    assert sum(result.varianceImportanceProxy for result in results) == pytest.approx(1.0)


def test_negative_control_and_knockout_helpers_distinguish_mechanisms() -> None:
    baseline = (10.0, 11.0, 9.0, 12.0, 8.0)
    negativeControl = evaluateNegativeControl(
        "baseline-self",
        baseline,
        baseline,
        tolerance=0.1,
        bootstrapResamples=200,
    )
    assert negativeControl.passed

    knockout = evaluateKnockout(
        "disable-stop-loss",
        baseline,
        tuple(value + 4.0 for value in baseline),
        tuple(value + 1.0 for value in baseline),
        bootstrapResamples=200,
    )
    assert knockout.fullEffect == 4.0
    assert knockout.knockoutEffect == 1.0
    assert knockout.attenuationFraction == 0.75
    assert knockout.mechanismSupported


def test_statistics_reject_mismatched_or_non_finite_samples() -> None:
    with pytest.raises(ValueError, match="equal lengths"):
        analyzePairedExperiment((1.0, 2.0), (1.0, 2.0, 3.0))
    with pytest.raises(ValueError, match="finite"):
        bootstrap95ConfidenceInterval((1.0, math.inf))
    with pytest.raises(ValueError, match="at least 100"):
        bootstrap95ConfidenceInterval((1.0, 2.0), resamples=99)
    with pytest.raises(ValueError, match="invalid p-value"):
        holmBonferroni({"bad": 1.1})


def test_validation_ladder_enforces_lower_level_and_evidence_gates() -> None:
    ladder = ValidationLadder()
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)

    assert len(ladder.snapshot().records) == 9
    assert ladder.highestPassedLevel() is None
    with pytest.raises(ValueError, match="BLOCKED"):
        ladder.updateStatus(
            ValidationLevel.L0,
            LevelStatus.BLOCKED,
            statusSummary="blocked",
            updatedAt=now,
        )
    with pytest.raises(ValueError, match="without verified evidence"):
        ladder.updateStatus(
            ValidationLevel.L0,
            LevelStatus.PASS,
            statusSummary="passed",
            updatedAt=now,
        )
    ladder.addEvidence(ValidationLevel.L1, makeEvidence("l1-evidence"))
    with pytest.raises(ValueError, match="gated by lower levels"):
        ladder.updateStatus(
            ValidationLevel.L1,
            LevelStatus.PASS,
            statusSummary="passed",
            updatedAt=now,
        )

    ladder.addEvidence(ValidationLevel.L0, makeEvidence("l0-evidence"))
    ladder.updateStatus(
        ValidationLevel.L0,
        LevelStatus.PASS,
        statusSummary="L0 invariants passed",
        updatedAt=now,
    )
    ladder.updateStatus(
        ValidationLevel.L1,
        LevelStatus.PASS,
        statusSummary="L1 microstructure passed",
        updatedAt=now,
    )
    assert ladder.canInterpret(ValidationLevel.L1)
    assert ladder.highestPassedLevel() is ValidationLevel.L1


def test_invalidated_ladder_evidence_fails_level_and_blocks_upper_levels() -> None:
    ladder = ValidationLadder()
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    for level in (ValidationLevel.L0, ValidationLevel.L1):
        evidenceId = f"{level.label.lower()}-evidence"
        ladder.addEvidence(level, makeEvidence(evidenceId))
        ladder.updateStatus(
            level,
            LevelStatus.PASS,
            statusSummary=f"{level.label} passed",
            updatedAt=now,
        )

    ladder.invalidateEvidence(
        "l0-evidence",
        invalidatedAt=now,
        reason="checksum mismatch",
    )
    assert ladder.get(ValidationLevel.L0).status is LevelStatus.FAIL
    assert ladder.get(ValidationLevel.L1).status is LevelStatus.BLOCKED
    assert not ladder.canInterpret(ValidationLevel.L1)
