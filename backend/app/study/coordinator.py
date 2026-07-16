"""可注入运行器的 Study 调度、配对统计与审计摘要。"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum

from backend.app.study.models import (
    ControlExpectation,
    EvidenceBasis,
    ExpectedDirection,
    NegativeControlKind,
    ParameterSetting,
    ScalarValue,
    StudyCellRole,
    StudyClaimLevel,
    StudySpec,
)
from backend.app.validation.statistics import (
    HolmResult,
    NegativeControlResult,
    PairedAnalysis,
    SensitivityIndex,
    analyzePairedExperiment,
    evaluateNegativeControl,
    holmBonferroni,
    pairedDifferences,
    rankCorrelationSensitivity,
)


class SensitivityInterpretation(StrEnum):
    MODEL_INTERNAL = "MODEL_INTERNAL"
    EXPLORATORY_UNSUPPORTED_PARAMETER = "EXPLORATORY_UNSUPPORTED_PARAMETER"
    INCONCLUSIVE_NO_RANK_SIGNAL = "INCONCLUSIVE_NO_RANK_SIGNAL"


@dataclass(frozen=True, slots=True)
class ExecutionCellSpec:
    cellId: str
    role: StudyCellRole
    sourceId: str
    sourceKind: str
    settings: tuple[ParameterSetting, ...]

    @property
    def parameterValues(self) -> dict[str, ScalarValue]:
        return {setting.path: setting.value for setting in self.settings}


@dataclass(frozen=True, slots=True)
class StudyRunRequest:
    studyId: str
    cellId: str
    cellRole: StudyCellRole
    sourceId: str
    sourceKind: str
    seed: int
    settings: tuple[ParameterSetting, ...]
    claimLevel: StudyClaimLevel

    @property
    def parameterValues(self) -> dict[str, ScalarValue]:
        return {setting.path: setting.value for setting in self.settings}


@dataclass(frozen=True, slots=True)
class OutcomeValue:
    outcomeId: str
    value: float

    def __post_init__(self) -> None:
        if not self.outcomeId:
            raise ValueError("outcomeId must not be empty")
        if isinstance(self.value, bool) or not isinstance(self.value, int | float):
            raise ValueError("outcome value must be numeric")
        if not math.isfinite(float(self.value)):
            raise ValueError("outcome value must be finite")
        object.__setattr__(self, "value", float(self.value))


@dataclass(frozen=True, slots=True)
class DiagnosticValue:
    name: str
    value: ScalarValue
    unit: str

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise ValueError("diagnostic name must not be empty")
        if not self.unit or self.unit != self.unit.strip():
            raise ValueError("diagnostic unit must not be empty")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("numeric diagnostic values must be finite")
        if isinstance(self.value, str) and (not self.value or self.value != self.value.strip()):
            raise ValueError("string diagnostic values must not be empty")


@dataclass(frozen=True, slots=True)
class RunOutput:
    outcomes: tuple[OutcomeValue, ...]
    diagnostics: tuple[DiagnosticValue, ...] = ()
    artifactReferences: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        outcomes = tuple(sorted(self.outcomes, key=lambda item: item.outcomeId))
        diagnostics = tuple(sorted(self.diagnostics, key=lambda item: item.name))
        if len({item.outcomeId for item in outcomes}) != len(outcomes):
            raise ValueError("run output contains duplicate outcomes")
        if len({item.name for item in diagnostics}) != len(diagnostics):
            raise ValueError("run output contains duplicate diagnostics")
        for artifactReference in self.artifactReferences:
            if not artifactReference or artifactReference != artifactReference.strip():
                raise ValueError("artifact references must not be empty")
        object.__setattr__(self, "outcomes", outcomes)
        object.__setattr__(self, "diagnostics", diagnostics)

    @classmethod
    def fromMappings(
        cls,
        outcomes: Mapping[str, float],
        *,
        diagnostics: tuple[DiagnosticValue, ...] = (),
        artifactReferences: tuple[str, ...] = (),
    ) -> RunOutput:
        return cls(
            outcomes=tuple(
                OutcomeValue(outcomeId=outcomeId, value=value)
                for outcomeId, value in outcomes.items()
            ),
            diagnostics=diagnostics,
            artifactReferences=artifactReferences,
        )


StudyRunFunction = Callable[[StudyRunRequest], RunOutput | Mapping[str, float]]


@dataclass(frozen=True, slots=True)
class StudyRunResult:
    request: StudyRunRequest
    output: RunOutput


@dataclass(frozen=True, slots=True)
class CellOutcomeAnalysis:
    hypothesisId: str
    familyId: str
    cellId: str
    outcomeId: str
    expectedDirection: ExpectedDirection
    analysis: PairedAnalysis
    exactSignPValue: float


@dataclass(frozen=True, slots=True)
class HolmFamilySummary:
    familyId: str
    alpha: float
    results: tuple[HolmResult, ...]


@dataclass(frozen=True, slots=True)
class NegativeControlOutcomeSummary:
    outcomeId: str
    result: NegativeControlResult


@dataclass(frozen=True, slots=True)
class NegativeControlSummary:
    controlId: str
    kind: NegativeControlKind
    expectation: ControlExpectation
    cellId: str
    outcomeResults: tuple[NegativeControlOutcomeSummary, ...]
    interpretationBoundary: str


@dataclass(frozen=True, slots=True)
class SensitivityOutcomeSummary:
    outcomeId: str
    method: str
    indices: tuple[SensitivityIndex, ...]
    dominantParameter: str | None
    dominantEvidenceBasis: EvidenceBasis | None
    interpretation: SensitivityInterpretation
    warning: str


@dataclass(frozen=True, slots=True)
class StudyAuditManifest:
    specHash: str
    resultHash: str
    runnerName: str
    expectedRunCount: int
    completedRunCount: int
    commonRandomSeedScheduleVerified: bool
    historicalValidityEstablished: bool
    validityBoundary: str


@dataclass(frozen=True, slots=True)
class StudyResult:
    studyId: str
    cells: tuple[ExecutionCellSpec, ...]
    runs: tuple[StudyRunResult, ...]
    cellOutcomeAnalyses: tuple[CellOutcomeAnalysis, ...]
    holmFamilies: tuple[HolmFamilySummary, ...]
    negativeControls: tuple[NegativeControlSummary, ...]
    sensitivity: tuple[SensitivityOutcomeSummary, ...]
    audit: StudyAuditManifest


class StudyRunExecutionError(RuntimeError):
    def __init__(self, cellId: str, seed: int, detail: str) -> None:
        super().__init__(f"study run failed for cell={cellId}, seed={seed}: {detail}")
        self.cellId = cellId
        self.seed = seed


def executeStudy(
    spec: StudySpec,
    run: StudyRunFunction,
    *,
    runnerName: str,
) -> StudyResult:
    """对每个 cell 注入同一 seed 集，并生成完整的模型内部统计结果。"""

    if not runnerName or runnerName != runnerName.strip() or len(runnerName) > 128:
        raise ValueError("runnerName must be a non-empty stable label of at most 128 chars")
    cells = buildExecutionCells(spec)
    expectedOutcomeIds = {outcome.outcomeId for outcome in spec.preregistration.allOutcomes}
    runs: list[StudyRunResult] = []
    for cell in cells:
        for seed in spec.seeds:
            request = StudyRunRequest(
                studyId=spec.preregistration.studyId,
                cellId=cell.cellId,
                cellRole=cell.role,
                sourceId=cell.sourceId,
                sourceKind=cell.sourceKind,
                seed=seed,
                settings=cell.settings,
                claimLevel=spec.preregistration.claimLevel,
            )
            try:
                rawOutput = run(request)
                output = _normalizedRunOutput(rawOutput, expectedOutcomeIds)
            except Exception as error:
                raise StudyRunExecutionError(cell.cellId, seed, str(error)) from error
            runs.append(StudyRunResult(request=request, output=output))

    runResults = tuple(runs)
    _verifyCommonSeedSchedule(cells, runResults, spec.seeds)
    cellAnalyses = _analyzeCells(spec, cells, runResults)
    holmFamilies = _holmFamilies(spec, cellAnalyses)
    negativeControls = _analyzeNegativeControls(spec, runResults)
    sensitivity = _analyzeSensitivity(spec, runResults)
    expectedRunCount = len(cells) * len(spec.seeds)
    resultCore = {
        "studyId": spec.preregistration.studyId,
        "cells": cells,
        "runs": runResults,
        "cellOutcomeAnalyses": cellAnalyses,
        "holmFamilies": holmFamilies,
        "negativeControls": negativeControls,
        "sensitivity": sensitivity,
    }
    audit = StudyAuditManifest(
        specHash=_canonicalHash(spec),
        resultHash=_canonicalHash(resultCore),
        runnerName=runnerName,
        expectedRunCount=expectedRunCount,
        completedRunCount=len(runResults),
        commonRandomSeedScheduleVerified=True,
        historicalValidityEstablished=False,
        validityBoundary=(
            "This coordinator establishes deterministic model-internal comparisons only; "
            "it does not establish historical fit, real-world causality, or predictive validity."
        ),
    )
    return StudyResult(
        studyId=spec.preregistration.studyId,
        cells=cells,
        runs=runResults,
        cellOutcomeAnalyses=cellAnalyses,
        holmFamilies=holmFamilies,
        negativeControls=negativeControls,
        sensitivity=sensitivity,
        audit=audit,
    )


def buildExecutionCells(spec: StudySpec) -> tuple[ExecutionCellSpec, ...]:
    baseline = ExecutionCellSpec(
        cellId="baseline",
        role=StudyCellRole.BASELINE,
        sourceId="baseline",
        sourceKind="BASELINE",
        settings=spec.baselineSettings,
    )
    designCells = tuple(
        ExecutionCellSpec(
            cellId=f"design.{cell.cellId}",
            role=StudyCellRole.DESIGN,
            sourceId=cell.cellId,
            sourceKind=cell.designKind.value,
            settings=_mergedSettings(spec.baselineSettings, cell.settings),
        )
        for cell in spec.designCells
    )
    controlCells = tuple(
        ExecutionCellSpec(
            cellId=f"control.{control.controlId}",
            role=StudyCellRole.NEGATIVE_CONTROL,
            sourceId=control.controlId,
            sourceKind=control.kind.value,
            settings=_mergedSettings(spec.baselineSettings, control.settings),
        )
        for control in spec.negativeControls
    )
    ablationCells = tuple(
        ExecutionCellSpec(
            cellId=f"ablation.{ablation.ablationId}",
            role=StudyCellRole.ABLATION,
            sourceId=ablation.ablationId,
            sourceKind=ablation.kind.value,
            settings=_mergedSettings(spec.baselineSettings, ablation.settings),
        )
        for ablation in spec.ablations
    )
    return (baseline, *designCells, *controlCells, *ablationCells)


def exactMatchedSignPValue(
    baseline: tuple[float, ...],
    intervention: tuple[float, ...],
    *,
    direction: ExpectedDirection,
) -> float:
    """忽略零差值，返回预注册方向下的精确二项 sign-test p 值。"""

    differences = pairedDifferences(baseline, intervention)
    positiveCount = sum(value > 0 for value in differences)
    negativeCount = sum(value < 0 for value in differences)
    nonZeroCount = positiveCount + negativeCount
    if nonZeroCount == 0:
        return 1.0
    denominator = 2**nonZeroCount
    if direction is ExpectedDirection.INCREASE:
        numerator = sum(
            math.comb(nonZeroCount, count) for count in range(positiveCount, nonZeroCount + 1)
        )
        return numerator / denominator
    if direction is ExpectedDirection.DECREASE:
        numerator = sum(math.comb(nonZeroCount, count) for count in range(positiveCount + 1))
        return numerator / denominator
    lowerTail = sum(math.comb(nonZeroCount, count) for count in range(positiveCount + 1))
    upperTail = sum(
        math.comb(nonZeroCount, count) for count in range(positiveCount, nonZeroCount + 1)
    )
    return min(1.0, 2 * min(lowerTail, upperTail) / denominator)


def _normalizedRunOutput(
    rawOutput: RunOutput | Mapping[str, float],
    expectedOutcomeIds: set[str],
) -> RunOutput:
    if isinstance(rawOutput, Mapping):
        output = RunOutput.fromMappings(rawOutput)
    elif isinstance(rawOutput, RunOutput):
        output = rawOutput
    else:
        raise TypeError("run function must return RunOutput or a mapping of outcome values")
    actualOutcomeIds = {item.outcomeId for item in output.outcomes}
    if actualOutcomeIds != expectedOutcomeIds:
        missing = sorted(expectedOutcomeIds - actualOutcomeIds)
        unexpected = sorted(actualOutcomeIds - expectedOutcomeIds)
        raise ValueError(
            f"run output must exactly match preregistered outcomes; "
            f"missing={missing}; unexpected={unexpected}"
        )
    return output


def _analyzeCells(
    spec: StudySpec,
    cells: tuple[ExecutionCellSpec, ...],
    runs: tuple[StudyRunResult, ...],
) -> tuple[CellOutcomeAnalysis, ...]:
    values = _outcomeLookup(runs)
    analyses = []
    analysisIndex = 0
    for cell in cells:
        if cell.role is StudyCellRole.BASELINE:
            continue
        for outcome in spec.preregistration.allOutcomes:
            baselineValues = tuple(
                values[("baseline", seed, outcome.outcomeId)] for seed in spec.seeds
            )
            cellValues = tuple(
                values[(cell.cellId, seed, outcome.outcomeId)] for seed in spec.seeds
            )
            hypothesisId = f"{outcome.familyId}.{cell.cellId}.{outcome.outcomeId}"
            analyses.append(
                CellOutcomeAnalysis(
                    hypothesisId=hypothesisId,
                    familyId=outcome.familyId,
                    cellId=cell.cellId,
                    outcomeId=outcome.outcomeId,
                    expectedDirection=outcome.expectedDirection,
                    analysis=analyzePairedExperiment(
                        baselineValues,
                        cellValues,
                        bootstrapResamples=spec.bootstrapResamples,
                        seed=spec.analysisSeed + analysisIndex,
                    ),
                    exactSignPValue=exactMatchedSignPValue(
                        baselineValues,
                        cellValues,
                        direction=outcome.expectedDirection,
                    ),
                )
            )
            analysisIndex += 1
    return tuple(analyses)


def _holmFamilies(
    spec: StudySpec,
    analyses: tuple[CellOutcomeAnalysis, ...],
) -> tuple[HolmFamilySummary, ...]:
    familyIds = sorted({analysis.familyId for analysis in analyses})
    return tuple(
        HolmFamilySummary(
            familyId=familyId,
            alpha=spec.alpha,
            results=holmBonferroni(
                {
                    analysis.hypothesisId: analysis.exactSignPValue
                    for analysis in analyses
                    if analysis.familyId == familyId
                },
                alpha=spec.alpha,
            ),
        )
        for familyId in familyIds
    )


def _analyzeNegativeControls(
    spec: StudySpec,
    runs: tuple[StudyRunResult, ...],
) -> tuple[NegativeControlSummary, ...]:
    values = _outcomeLookup(runs)
    summaries = []
    analysisIndex = 0
    for control in spec.negativeControls:
        cellId = f"control.{control.controlId}"
        outcomeResults = []
        if control.expectation is ControlExpectation.NULL_EFFECT:
            toleranceByOutcome = {
                tolerance.outcomeId: tolerance.absoluteTolerance for tolerance in control.tolerances
            }
            for outcome in spec.preregistration.primaryOutcomes:
                baselineValues = tuple(
                    values[("baseline", seed, outcome.outcomeId)] for seed in spec.seeds
                )
                controlValues = tuple(
                    values[(cellId, seed, outcome.outcomeId)] for seed in spec.seeds
                )
                result = evaluateNegativeControl(
                    control.controlId,
                    baselineValues,
                    controlValues,
                    tolerance=toleranceByOutcome[outcome.outcomeId],
                    bootstrapResamples=spec.bootstrapResamples,
                    seed=spec.analysisSeed + 100_000 + analysisIndex,
                )
                outcomeResults.append(
                    NegativeControlOutcomeSummary(
                        outcomeId=outcome.outcomeId,
                        result=result,
                    )
                )
                analysisIndex += 1
        summaries.append(
            NegativeControlSummary(
                controlId=control.controlId,
                kind=control.kind,
                expectation=control.expectation,
                cellId=cellId,
                outcomeResults=tuple(outcomeResults),
                interpretationBoundary=(
                    "Null-effect placebo check."
                    if control.expectation is ControlExpectation.NULL_EFFECT
                    else "Model-mechanism diagnostic; a difference is not real-world causal proof."
                ),
            )
        )
    return tuple(summaries)


def _analyzeSensitivity(
    spec: StudySpec,
    runs: tuple[StudyRunResult, ...],
) -> tuple[SensitivityOutcomeSummary, ...]:
    values = _outcomeLookup(runs)
    parameterSettings = {setting.path: setting for setting in spec.designCells[0].settings}
    parameterSamples = {
        path: tuple(
            float(next(setting.value for setting in cell.settings if setting.path == path))
            for cell in spec.designCells
        )
        for path in parameterSettings
    }
    summaries = []
    for outcome in spec.preregistration.allOutcomes:
        outcomeMeans = tuple(
            statistics.fmean(
                values[(f"design.{cell.cellId}", seed, outcome.outcomeId)] for seed in spec.seeds
            )
            for cell in spec.designCells
        )
        indices = rankCorrelationSensitivity(parameterSamples, outcomeMeans)
        hasSignal = any(index.varianceImportanceProxy > 0 for index in indices)
        if not hasSignal:
            dominantParameter = None
            dominantEvidenceBasis = None
            interpretation = SensitivityInterpretation.INCONCLUSIVE_NO_RANK_SIGNAL
            warning = "No rank signal was identified; do not infer parameter importance."
        else:
            dominantParameter = indices[0].parameter
            dominantEvidenceBasis = parameterSettings[dominantParameter].evidenceBasis
            if dominantEvidenceBasis is EvidenceBasis.EVIDENCE_BOUND:
                interpretation = SensitivityInterpretation.MODEL_INTERNAL
                warning = (
                    "Normalized squared Spearman correlation is a screening proxy, "
                    "not a Sobol decomposition or real-world causal share."
                )
            else:
                interpretation = SensitivityInterpretation.EXPLORATORY_UNSUPPORTED_PARAMETER
                warning = (
                    "The dominant parameter is assumption-based or synthetic; "
                    "the finding is automatically downgraded to exploratory."
                )
        summaries.append(
            SensitivityOutcomeSummary(
                outcomeId=outcome.outcomeId,
                method="SPEARMAN_SQUARED_NORMALIZED_VARIANCE_PROXY",
                indices=indices,
                dominantParameter=dominantParameter,
                dominantEvidenceBasis=dominantEvidenceBasis,
                interpretation=interpretation,
                warning=warning,
            )
        )
    return tuple(summaries)


def _outcomeLookup(
    runs: tuple[StudyRunResult, ...],
) -> dict[tuple[str, int, str], float]:
    return {
        (run.request.cellId, run.request.seed, outcome.outcomeId): outcome.value
        for run in runs
        for outcome in run.output.outcomes
    }


def _verifyCommonSeedSchedule(
    cells: tuple[ExecutionCellSpec, ...],
    runs: tuple[StudyRunResult, ...],
    expectedSeeds: tuple[int, ...],
) -> None:
    for cell in cells:
        actualSeeds = tuple(run.request.seed for run in runs if run.request.cellId == cell.cellId)
        if actualSeeds != expectedSeeds:
            raise RuntimeError(f"common random seed schedule mismatch for {cell.cellId}")


def _mergedSettings(
    baseline: tuple[ParameterSetting, ...],
    overrides: tuple[ParameterSetting, ...],
) -> tuple[ParameterSetting, ...]:
    merged = {setting.path: setting for setting in baseline}
    merged.update({setting.path: setting for setting in overrides})
    return tuple(sorted(merged.values(), key=lambda setting: setting.path))


def _canonicalHash(value: object) -> str:
    payload = _canonicalValue(value)
    serialized = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{hashlib.sha256(serialized.encode()).hexdigest()}"


def _canonicalValue(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return _canonicalValue(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalValue(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, tuple | list):
        return [_canonicalValue(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value
