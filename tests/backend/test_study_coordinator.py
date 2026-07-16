from __future__ import annotations

import math
from dataclasses import replace

import pytest

from backend.app.study import (
    ControlExpectation,
    DiagnosticValue,
    EvidenceBasis,
    ExpectedDirection,
    FactorLevelSpec,
    FrozenArtifact,
    OutcomeSpec,
    ParameterRangeSpec,
    ParameterSetting,
    RunOutput,
    SensitivityInterpretation,
    StudyClaimLevel,
    StudyPreregistration,
    StudyRunExecutionError,
    StudySpec,
    buildRequiredAblations,
    buildRequiredNegativeControls,
    exactMatchedSignPValue,
    executeStudy,
    generateFullFactorialCells,
    generateLatinHypercubeCells,
)


def makeOutcomes() -> tuple[tuple[OutcomeSpec, ...], tuple[OutcomeSpec, ...]]:
    primary = (
        OutcomeSpec(
            outcomeId="peak-drawdown",
            unit="bps",
            familyId="primary-risk",
            expectedDirection=ExpectedDirection.INCREASE,
            rationale="Preregister tail loss before running the study.",
            minimumEffectOfInterest=5.0,
        ),
        OutcomeSpec(
            outcomeId="quoted-spread",
            unit="bps",
            familyId="primary-risk",
            expectedDirection=ExpectedDirection.INCREASE,
            rationale="Preregister liquidity deterioration before observing results.",
            minimumEffectOfInterest=1.0,
        ),
    )
    secondary = (
        OutcomeSpec(
            outcomeId="turnover",
            unit="shares",
            familyId="secondary-exploratory",
            expectedDirection=ExpectedDirection.TWO_SIDED,
            rationale="Treat activity as a secondary exploratory outcome.",
        ),
    )
    return primary, secondary


def makeStudySpec() -> StudySpec:
    primary, secondary = makeOutcomes()
    factors = (
        FactorLevelSpec(
            parameterPath="model.assumption_x",
            unit="ratio",
            levels=(0.0, 1.0),
            rationale="Synthetic sensitivity factor with no external calibration.",
            evidenceBasis=EvidenceBasis.ASSUMPTION,
        ),
        FactorLevelSpec(
            parameterPath="model.evidence_y",
            unit="ratio",
            levels=(0.0, 1.0),
            rationale="Evidence-bound sensitivity factor.",
            evidenceBasis=EvidenceBasis.EVIDENCE_BOUND,
            sourceReference="event-pack://frozen/evidence-y",
        ),
    )
    preregistration = StudyPreregistration(
        studyId="study-core-test",
        question="Which model parameters dominate the synthetic response?",
        claimLevel=StudyClaimLevel.MODEL_INTERNAL_SENSITIVITY,
        primaryOutcomes=primary,
        secondaryOutcomes=secondary,
        exclusionRules=("Exclude only explicit invariant failures.",),
        supportCriterion="A paired effect has the preregistered direction.",
        contradictionCriterion="The paired effect has the opposite direction.",
        inconclusiveCriterion="Intervals remain too wide or controls fail.",
        knownLimitations=("No historical calibration is performed by this unit test.",),
        frozenArtifacts=(
            FrozenArtifact(
                artifactId="synthetic-event-pack",
                sha256=f"sha256:{'a' * 64}",
            ),
        ),
    )
    return StudySpec(
        preregistration=preregistration,
        baselineSettings=(
            ParameterSetting(
                path="model.assumption_x",
                value=0.0,
                unit="ratio",
                rationale="Frozen baseline assumption.",
            ),
            ParameterSetting(
                path="model.evidence_y",
                value=0.0,
                unit="ratio",
                rationale="Frozen baseline evidence parameter.",
                evidenceBasis=EvidenceBasis.EVIDENCE_BOUND,
                sourceReference="event-pack://frozen/evidence-y",
            ),
        ),
        designCells=generateFullFactorialCells(factors),
        negativeControls=buildRequiredNegativeControls(
            primary,
            nullToleranceByOutcome={
                "peak-drawdown": 0.01,
                "quoted-spread": 0.01,
            },
        ),
        ablations=buildRequiredAblations(),
        seeds=(29, 3, 17, 11),
        bootstrapResamples=100,
        analysisSeed=719,
    )


def deterministicRunner(request: object) -> dict[str, float]:
    parameterValues = request.parameterValues  # type: ignore[attr-defined]
    seed = request.seed  # type: ignore[attr-defined]
    assumptionX = float(parameterValues.get("model.assumption_x", 0.0))
    evidenceY = float(parameterValues.get("model.evidence_y", 0.0))
    seedNoise = seed / 100.0
    return {
        "peak-drawdown": seedNoise + 10.0 * assumptionX + evidenceY,
        "quoted-spread": 2.0 * seedNoise + 5.0 * assumptionX - evidenceY,
        "turnover": 100.0 + seedNoise + 2.0 * evidenceY,
    }


def test_full_factorial_is_deterministic_and_input_order_independent() -> None:
    left = FactorLevelSpec(
        parameterPath="factor.left",
        unit="ratio",
        levels=(1.0, -1.0),
        rationale="Exercise both levels.",
    )
    right = FactorLevelSpec(
        parameterPath="factor.right",
        unit="minutes",
        levels=(30.0, 5.0, 120.0),
        rationale="Exercise all timing levels.",
    )

    first = generateFullFactorialCells((right, left))
    second = generateFullFactorialCells((left, right))

    assert first == second
    assert len(first) == 6
    combinations = {tuple(setting.value for setting in cell.settings) for cell in first}
    assert combinations == {
        (-1.0, 5.0),
        (-1.0, 30.0),
        (-1.0, 120.0),
        (1.0, 5.0),
        (1.0, 30.0),
        (1.0, 120.0),
    }
    with pytest.raises(ValueError, match="above 5"):
        generateFullFactorialCells((left, right), maximumCells=5)


def test_latin_hypercube_is_seeded_and_uses_every_stratum_once() -> None:
    ranges = (
        ParameterRangeSpec(
            parameterPath="factor.zero_one",
            unit="ratio",
            lower=0.0,
            upper=1.0,
            rationale="Unit interval factor.",
        ),
        ParameterRangeSpec(
            parameterPath="factor.ten_twenty",
            unit="bps",
            lower=10.0,
            upper=20.0,
            rationale="Ten-to-twenty factor.",
        ),
    )
    first = generateLatinHypercubeCells(ranges, sampleCount=8, seed=43)
    reordered = generateLatinHypercubeCells(tuple(reversed(ranges)), sampleCount=8, seed=43)
    differentSeed = generateLatinHypercubeCells(ranges, sampleCount=8, seed=44)

    assert first == reordered
    assert first != differentSeed
    zeroOne = [float(cell.settings[1].value) for cell in first]
    tenTwenty = [float(cell.settings[0].value) for cell in first]
    assert sorted(int(value * 8) for value in zeroOne) == list(range(8))
    assert sorted(int((value - 10.0) / 10.0 * 8) for value in tenTwenty) == list(range(8))


def test_spec_requires_every_control_ablation_and_exact_primary_units() -> None:
    spec = makeStudySpec()
    with pytest.raises(ValueError, match="negative controls must match the required set"):
        replace(spec, negativeControls=spec.negativeControls[:-1])
    with pytest.raises(ValueError, match="ablations must match the required set"):
        replace(spec, ablations=spec.ablations[:-1])

    baselineSelf = next(
        control for control in spec.negativeControls if control.controlId == "baseline-self"
    )
    wrongTolerance = replace(
        baselineSelf.tolerances[0],
        unit="percent",
    )
    invalidBaselineSelf = replace(
        baselineSelf,
        tolerances=(wrongTolerance, *baselineSelf.tolerances[1:]),
    )
    invalidControls = tuple(
        invalidBaselineSelf if control.controlId == "baseline-self" else control
        for control in spec.negativeControls
    )
    with pytest.raises(ValueError, match="matching units"):
        replace(spec, negativeControls=invalidControls)

    with pytest.raises(ValueError, match="not a valid StudyClaimLevel"):
        StudyClaimLevel("HISTORICAL_CAUSAL_PROOF")


def test_execute_study_uses_common_seeds_and_returns_every_cell_seed() -> None:
    spec = makeStudySpec()
    observed: list[tuple[str, int]] = []

    def recordingRunner(request: object) -> dict[str, float]:
        observed.append((request.cellId, request.seed))  # type: ignore[attr-defined]
        return deterministicRunner(request)

    result = executeStudy(spec, recordingRunner, runnerName="deterministic-test-runner")

    assert len(result.cells) == 1 + 4 + 8 + 10
    assert len(result.runs) == len(result.cells) * len(spec.seeds)
    assert len(set(observed)) == len(observed)
    for cell in result.cells:
        assert tuple(seed for cellId, seed in observed if cellId == cell.cellId) == spec.seeds
    assert result.audit.expectedRunCount == result.audit.completedRunCount == len(result.runs)
    assert result.audit.commonRandomSeedScheduleVerified
    assert not result.audit.historicalValidityEstablished
    assert "does not establish historical fit" in result.audit.validityBoundary


def test_results_include_controls_holm_and_exploratory_sensitivity() -> None:
    spec = makeStudySpec()
    result = executeStudy(spec, deterministicRunner, runnerName="deterministic-test-runner")

    baselineSelf = next(
        control for control in result.negativeControls if control.controlId == "baseline-self"
    )
    assert baselineSelf.expectation is ControlExpectation.NULL_EFFECT
    assert all(item.result.passed for item in baselineSelf.outcomeResults)
    disableSocial = next(
        control
        for control in result.negativeControls
        if control.controlId == "disable-social-control"
    )
    assert disableSocial.expectation is ControlExpectation.MECHANISM_DIAGNOSTIC
    assert disableSocial.outcomeResults == ()

    assert {family.familyId for family in result.holmFamilies} == {
        "primary-risk",
        "secondary-exploratory",
    }
    assert all(family.results for family in result.holmFamilies)
    peakSensitivity = next(item for item in result.sensitivity if item.outcomeId == "peak-drawdown")
    assert peakSensitivity.dominantParameter == "model.assumption_x"
    assert peakSensitivity.dominantEvidenceBasis is EvidenceBasis.ASSUMPTION
    assert (
        peakSensitivity.interpretation
        is SensitivityInterpretation.EXPLORATORY_UNSUPPORTED_PARAMETER
    )
    assert sum(index.varianceImportanceProxy for index in peakSensitivity.indices) == pytest.approx(
        1.0
    )


def test_study_result_and_audit_hashes_are_deterministic() -> None:
    spec = makeStudySpec()
    first = executeStudy(spec, deterministicRunner, runnerName="deterministic-test-runner")
    second = executeStudy(spec, deterministicRunner, runnerName="deterministic-test-runner")

    assert first == second
    assert first.audit.specHash.startswith("sha256:")
    assert first.audit.resultHash.startswith("sha256:")


def test_run_output_keeps_diagnostics_and_artifacts() -> None:
    spec = makeStudySpec()

    def detailedRunner(request: object) -> RunOutput:
        return RunOutput.fromMappings(
            deterministicRunner(request),
            diagnostics=(DiagnosticValue(name="invariant-status", value="PASS", unit="category"),),
            artifactReferences=(f"artifact://{request.cellId}/{request.seed}",),  # type: ignore[attr-defined]
        )

    result = executeStudy(spec, detailedRunner, runnerName="detailed-test-runner")

    assert all(run.output.diagnostics[0].value == "PASS" for run in result.runs)
    assert all(len(run.output.artifactReferences) == 1 for run in result.runs)


@pytest.mark.parametrize(
    "badOutput",
    [
        {"peak-drawdown": 1.0, "quoted-spread": 2.0},
        {
            "peak-drawdown": math.inf,
            "quoted-spread": 2.0,
            "turnover": 3.0,
        },
        {
            "peak-drawdown": 1.0,
            "quoted-spread": 2.0,
            "turnover": 3.0,
            "post-hoc-outcome": 4.0,
        },
    ],
)
def test_runner_rejects_missing_non_finite_or_post_hoc_outcomes(
    badOutput: dict[str, float],
) -> None:
    spec = makeStudySpec()

    with pytest.raises(StudyRunExecutionError, match="study run failed"):
        executeStudy(spec, lambda _request: badOutput, runnerName="invalid-runner")


def test_exact_sign_test_respects_preregistered_direction() -> None:
    baseline = (0.0, 0.0, 0.0, 0.0)
    increase = (1.0, 1.0, 1.0, 1.0)

    assert exactMatchedSignPValue(
        baseline,
        increase,
        direction=ExpectedDirection.INCREASE,
    ) == pytest.approx(0.0625)
    assert exactMatchedSignPValue(
        baseline,
        increase,
        direction=ExpectedDirection.TWO_SIDED,
    ) == pytest.approx(0.125)
    assert (
        exactMatchedSignPValue(
            baseline,
            baseline,
            direction=ExpectedDirection.TWO_SIDED,
        )
        == 1.0
    )
