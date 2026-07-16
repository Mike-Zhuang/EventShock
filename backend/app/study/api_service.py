"""Study 设计预览、受限执行与不可变审计持久化。"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import uuid
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from backend.app.database import Database
from backend.app.errors import ApiError
from backend.app.simulation.engine import runScenario
from backend.app.study.api_models import (
    StudyDesignInput,
    StudyDesignPreviewRequest,
    StudyFactorInput,
    StudyRunApiRequest,
)
from backend.app.study.coordinator import (
    DiagnosticValue,
    RunOutput,
    StudyRunExecutionError,
    StudyRunRequest,
    executeStudy,
)
from backend.app.study.design import (
    FactorLevelSpec,
    ParameterRangeSpec,
    generateFullFactorialCells,
    generateLatinHypercubeCells,
)
from backend.app.study.models import (
    REQUIRED_ABLATION_KINDS,
    REQUIRED_NEGATIVE_CONTROL_KINDS,
    DesignKind,
    FrozenArtifact,
    OutcomeSpec,
    ParameterSetting,
    StudyPreregistration,
    StudySpec,
)
from backend.app.study.presets import buildRequiredAblations, buildRequiredNegativeControls

MAXIMUM_DESIGN_CELLS = 16
MAXIMUM_STUDY_RUNS = 96
MAXIMUM_STUDY_WORK_UNITS = 150_000
STUDY_RUNNER_NAME = "eventshock-deterministic-study-runner-v1"

OUTCOME_REGISTRY: dict[str, tuple[str, str]] = {
    "max-drawdown-pct": ("maxDrawdownPct", "percent"),
    "realized-volatility-pct": ("realizedVolatilityPct", "percent"),
    "max-spread-bps": ("maxSpreadBps", "basis-points"),
    "min-depth": ("minDepth", "shares"),
    "recovery-steps": ("recoverySteps", "simulation-steps"),
    "total-volume": ("totalVolume", "shares"),
    "order-imbalance": ("orderImbalance", "ratio"),
    "cascade-score": ("cascadeScore", "score-0-100"),
    "network-reach-rate": ("networkReachRate", "ratio"),
    "information-delay-steps": ("informationDelaySteps", "simulation-steps"),
    "liquidity-stress-index": ("liquidityStressIndex", "index"),
    "tail-loss-probability": ("tailLossProbability", "probability"),
    "abnormal-return-pct": ("abnormalReturnPct", "percent"),
}

FACTOR_REGISTRY: dict[str, tuple[str, float, float]] = {
    "intervention.value": ("multiplier", 0.05, 4.0),
    "market.fee_bps": ("basis-points", 0.0, 100.0),
    "market.latency_ms": ("milliseconds", 0.0, 60_000.0),
    "market.price_collar_bps": ("basis-points", 1.0, 5_000.0),
    "network.correction_reach": ("ratio", 0.0, 1.0),
    "network.echo_chamber_strength": ("ratio", 0.0, 1.0),
    "network.rewiring_probability": ("ratio", 0.0, 1.0),
    "population.institutional_share": ("ratio", 0.0, 1.0),
}


class StudyApiService:
    """单进程只执行一个 Study，避免匿名演示服务被 CPU 请求挤占。"""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.executionLock = threading.Lock()

    def presets(self) -> dict[str, Any]:
        return {
            "schemaVersion": "1.0.0",
            "historicalValidityEstablished": False,
            "validityBoundary": (
                "Presets are preregistration templates for model-internal studies; "
                "they are not executed evidence, historical validation, or forecasts."
            ),
            "requiredNegativeControlCount": len(REQUIRED_NEGATIVE_CONTROL_KINDS),
            "requiredAblationCount": len(REQUIRED_ABLATION_KINDS),
            "supportedOutcomes": [
                {"outcomeId": outcomeId, "unit": metadata[1]}
                for outcomeId, metadata in OUTCOME_REGISTRY.items()
            ],
            "supportedFactors": [
                {
                    "parameterPath": parameterPath,
                    "unit": metadata[0],
                    "minimum": metadata[1],
                    "maximum": metadata[2],
                }
                for parameterPath, metadata in FACTOR_REGISTRY.items()
            ],
            "items": _presetItems(),
        }

    def preview(self, requestData: StudyDesignPreviewRequest) -> dict[str, Any]:
        designCells = _buildDesignCells(requestData.design)
        budget = _studyBudget(
            len(designCells),
            requestData.matchedSeedCount,
            requestData.populationSize,
            requestData.steps,
        )
        return {
            "designKind": requestData.design.kind.value,
            "designCellCount": len(designCells),
            "requiredNegativeControlCount": len(REQUIRED_NEGATIVE_CONTROL_KINDS),
            "requiredAblationCount": len(REQUIRED_ABLATION_KINDS),
            **budget,
            "withinResourceLimits": True,
            "historicalValidityEstablished": False,
            "cells": [_jsonValue(cell) for cell in designCells],
        }

    def run(
        self,
        requestData: StudyRunApiRequest,
        *,
        sessionId: str,
        eventPack: dict[str, Any],
    ) -> dict[str, Any]:
        if eventPack.get("status") != "FROZEN":
            raise ApiError(
                "STUDY_EVENT_PACK_NOT_FROZEN",
                422,
                "A Study can run only against an Event Pack frozen for this session.",
            )
        if not self.executionLock.acquire(blocking=False):
            raise ApiError(
                "STUDY_RUNNER_BUSY",
                409,
                "Another bounded Study is already running on this instance.",
            )
        try:
            try:
                spec = _buildStudySpec(requestData, eventPack)
            except ValueError as error:
                raise ApiError("INVALID_STUDY_SPEC", 422, str(error)) from error
            budget = _studyBudget(
                len(spec.designCells),
                len(spec.seeds),
                requestData.execution.populationSize,
                requestData.execution.steps,
            )
            try:
                result = executeStudy(
                    spec,
                    lambda runRequest: _executeSimulationCell(
                        runRequest,
                        requestData=requestData,
                        eventPack=eventPack,
                    ),
                    runnerName=STUDY_RUNNER_NAME,
                )
            except StudyRunExecutionError as error:
                raise ApiError(
                    "STUDY_RUN_FAILED",
                    500,
                    f"Study execution failed for cell={error.cellId}, seed={error.seed}.",
                ) from error
            serializedSpec = _jsonValue(spec)
            serializedCoreResult = _jsonValue(result)
            runId = f"study-run-{uuid.uuid4().hex[:20]}"
            resultDocument = {
                "schemaVersion": "1.0.0",
                "runId": runId,
                "studyId": result.studyId,
                "status": "COMPLETED",
                "eventPackId": requestData.eventPackId,
                "historicalValidityEstablished": False,
                "validityBoundary": result.audit.validityBoundary,
                "resourceBudget": budget,
                "executionProtocol": {
                    "runner": STUDY_RUNNER_NAME,
                    "marketKernel": "DETERMINISTIC_DISCRETE_EVENT_LIMIT_ORDER_BOOK",
                    "cognitionMode": "FROZEN_EVIDENCE_BOUND_COGNITIVE_TAPE_NOT_LIVE_LLM",
                    "matchedSeeds": True,
                    "requiredNegativeControlsIncluded": len(REQUIRED_NEGATIVE_CONTROL_KINDS),
                    "requiredAblationsIncluded": len(REQUIRED_ABLATION_KINDS),
                    "proxyAblationsAcknowledged": requestData.acknowledgedProxyAblations,
                    "mechanismSemantics": _mechanismSemantics(),
                },
                "preregistration": serializedSpec["preregistration"],
                "result": serializedCoreResult,
            }
            storedResultHash = _canonicalHash(resultDocument)
            stored = self.database.saveStudyRun(
                runId=runId,
                sessionId=sessionId,
                eventPackId=requestData.eventPackId,
                studyId=result.studyId,
                spec=serializedSpec,
                result=resultDocument,
                specHash=result.audit.specHash,
                resultHash=storedResultHash,
            )
            self.database.appendAuditEvent(
                sessionId,
                "STUDY",
                runId,
                "STUDY_COMPLETED",
                {
                    "studyId": result.studyId,
                    "eventPackId": requestData.eventPackId,
                    "specHash": result.audit.specHash,
                    "resultHash": storedResultHash,
                    "coreResultHash": result.audit.resultHash,
                    "completedRunCount": result.audit.completedRunCount,
                    "historicalValidityEstablished": False,
                },
            )
            return _publicStudyRun(_verifyStoredStudyRun(stored))
        finally:
            self.executionLock.release()

    def listRuns(self, sessionId: str) -> list[dict[str, Any]]:
        return [
            _publicStudyRun(_verifyStoredStudyRun(item), includeResult=False)
            for item in self.database.listStudyRuns(sessionId)
        ]

    def getRun(self, runId: str, sessionId: str) -> dict[str, Any]:
        item = self.database.getStudyRun(runId, sessionId)
        if item is None:
            raise ApiError("STUDY_RUN_NOT_FOUND", 404, "The Study run does not exist.")
        return _publicStudyRun(_verifyStoredStudyRun(item))


def _buildStudySpec(
    requestData: StudyRunApiRequest,
    eventPack: dict[str, Any],
) -> StudySpec:
    primaryOutcomes = tuple(
        _outcomeSpec(item) for item in requestData.preregistration.primaryOutcomes
    )
    secondaryOutcomes = tuple(
        _outcomeSpec(item) for item in requestData.preregistration.secondaryOutcomes
    )
    requestHash = _canonicalHash(requestData.model_dump(mode="json"))
    eventPackHash = _canonicalHash(eventPack)
    preregistration = StudyPreregistration(
        studyId=requestData.preregistration.studyId,
        question=requestData.preregistration.question,
        claimLevel=requestData.preregistration.claimLevel,
        primaryOutcomes=primaryOutcomes,
        secondaryOutcomes=secondaryOutcomes,
        exclusionRules=tuple(requestData.preregistration.exclusionRules),
        supportCriterion=requestData.preregistration.supportCriterion,
        contradictionCriterion=requestData.preregistration.contradictionCriterion,
        inconclusiveCriterion=requestData.preregistration.inconclusiveCriterion,
        knownLimitations=(
            *requestData.preregistration.knownLimitations,
            (
                "Several required ablations are bounded executable proxies because the current "
                "kernel does not expose a direct subsystem switch; proxy semantics are returned "
                "with every result and cannot establish historical validity."
            ),
        ),
        frozenArtifacts=(
            FrozenArtifact(artifactId="event-pack", sha256=eventPackHash),
            FrozenArtifact(artifactId="study-request", sha256=requestHash),
        ),
    )
    baselineSettings = tuple(_baselineSetting(factor) for factor in requestData.design.factors)
    designCells = _buildDesignCells(requestData.design)
    seeds = tuple(
        requestData.execution.seedRoot + index * 1_009
        for index in range(requestData.execution.matchedSeedCount)
    )
    return StudySpec(
        preregistration=preregistration,
        baselineSettings=baselineSettings,
        designCells=designCells,
        negativeControls=buildRequiredNegativeControls(
            primaryOutcomes,
            nullToleranceByOutcome=requestData.nullToleranceByOutcome,
        ),
        ablations=buildRequiredAblations(),
        seeds=seeds,
        alpha=requestData.alpha,
        bootstrapResamples=requestData.bootstrapResamples,
        analysisSeed=requestData.analysisSeed,
    )


def _outcomeSpec(item: Any) -> OutcomeSpec:
    return OutcomeSpec(
        outcomeId=item.outcomeId,
        unit=OUTCOME_REGISTRY[item.outcomeId][1],
        familyId=item.familyId,
        expectedDirection=item.expectedDirection,
        rationale=item.rationale,
        minimumEffectOfInterest=item.minimumEffectOfInterest,
    )


def _buildDesignCells(design: StudyDesignInput) -> tuple[Any, ...]:
    _validateFactorValues(design)
    if design.kind is DesignKind.FULL_FACTORIAL:
        factors = tuple(
            FactorLevelSpec(
                parameterPath=factor.parameterPath,
                unit=FACTOR_REGISTRY[factor.parameterPath][0],
                levels=tuple(factor.levels or ()),
                rationale=factor.rationale,
                evidenceBasis=factor.evidenceBasis,
                sourceReference=factor.sourceReference,
            )
            for factor in design.factors
        )
        try:
            designCells = generateFullFactorialCells(
                factors,
                maximumCells=MAXIMUM_DESIGN_CELLS,
            )
        except ValueError as error:
            raise ApiError("STUDY_DESIGN_LIMIT", 422, str(error)) from error
        if len(designCells) < 3:
            raise ApiError(
                "STUDY_DESIGN_TOO_SMALL",
                422,
                "A Study design requires at least 3 cells for rank sensitivity analysis.",
            )
        return designCells
    ranges = tuple(
        ParameterRangeSpec(
            parameterPath=factor.parameterPath,
            unit=FACTOR_REGISTRY[factor.parameterPath][0],
            lower=float(factor.lower),
            upper=float(factor.upper),
            rationale=factor.rationale,
            evidenceBasis=factor.evidenceBasis,
            sourceReference=factor.sourceReference,
        )
        for factor in design.factors
    )
    try:
        return generateLatinHypercubeCells(
            ranges,
            sampleCount=int(design.sampleCount or 0),
            seed=design.designSeed,
            maximumCells=MAXIMUM_DESIGN_CELLS,
        )
    except ValueError as error:
        raise ApiError("STUDY_DESIGN_LIMIT", 422, str(error)) from error


def _baselineSetting(factor: StudyFactorInput) -> ParameterSetting:
    return ParameterSetting(
        path=factor.parameterPath,
        value=factor.baselineValue,
        unit=FACTOR_REGISTRY[factor.parameterPath][0],
        rationale=f"Frozen preregistered baseline. {factor.rationale}",
        evidenceBasis=factor.evidenceBasis,
        sourceReference=factor.sourceReference,
    )


def _validateFactorValues(design: StudyDesignInput) -> None:
    for factor in design.factors:
        _, minimum, maximum = FACTOR_REGISTRY[factor.parameterPath]
        values = [factor.baselineValue]
        if factor.levels is not None:
            values.extend(factor.levels)
        else:
            values.extend((float(factor.lower), float(factor.upper)))
        if any(not math.isfinite(value) or value < minimum or value > maximum for value in values):
            raise ApiError(
                "STUDY_FACTOR_OUT_OF_RANGE",
                422,
                f"{factor.parameterPath} values must be between {minimum} and {maximum}.",
            )
        if factor.parameterPath == "market.latency_ms" and any(
            value != round(value) for value in values
        ):
            raise ApiError(
                "STUDY_FACTOR_REQUIRES_INTEGER",
                422,
                "market.latency_ms values must be whole milliseconds.",
            )


def _studyBudget(
    designCellCount: int,
    matchedSeedCount: int,
    populationSize: int,
    steps: int,
) -> dict[str, int]:
    totalExecutionCells = (
        1 + designCellCount + len(REQUIRED_NEGATIVE_CONTROL_KINDS) + len(REQUIRED_ABLATION_KINDS)
    )
    expectedRunCount = totalExecutionCells * matchedSeedCount
    workUnits = expectedRunCount * populationSize * steps
    if expectedRunCount > MAXIMUM_STUDY_RUNS or workUnits > MAXIMUM_STUDY_WORK_UNITS:
        raise ApiError(
            "STUDY_RESOURCE_LIMIT",
            422,
            (
                f"The design requires {expectedRunCount} runs and {workUnits} work units; "
                f"limits are {MAXIMUM_STUDY_RUNS} runs and "
                f"{MAXIMUM_STUDY_WORK_UNITS} work units."
            ),
        )
    return {
        "totalExecutionCells": totalExecutionCells,
        "matchedSeedCount": matchedSeedCount,
        "expectedRunCount": expectedRunCount,
        "estimatedWorkUnits": workUnits,
        "maximumRunCount": MAXIMUM_STUDY_RUNS,
        "maximumWorkUnits": MAXIMUM_STUDY_WORK_UNITS,
    }


def _executeSimulationCell(
    runRequest: StudyRunRequest,
    *,
    requestData: StudyRunApiRequest,
    eventPack: dict[str, Any],
) -> RunOutput:
    values = runRequest.parameterValues
    execution = requestData.execution
    scenarioConfig = {
        "market": execution.market.model_dump(mode="json"),
        "population": execution.population.model_dump(mode="json"),
        "network": execution.network.model_dump(mode="json"),
    }
    scenarioParameter = execution.interventionParameter.value
    scenarioValue = float(values.get("intervention.value", execution.baselineInterventionValue))
    _applyFactorSettings(values, scenarioConfig)
    transformedPack = copy.deepcopy(eventPack)
    cognitiveCount = execution.frozenCognitiveRepresentativeCount
    proxyApplied = False

    cognitionMode = values.get("cognition.mode")
    if cognitionMode == "RULE_ONLY" or values.get("cognition.llm_enabled") is False:
        cognitiveCount = 0
    elif cognitionMode == "LLM_REPRESENTATIVES_MIN_LIQUIDITY":
        cognitiveCount = min(execution.populationSize - 1, max(4, cognitiveCount * 2))
        scenarioParameter = "marketMakerCapacity"
        scenarioValue = 0.5
        proxyApplied = True
    elif cognitionMode == "HYBRID":
        cognitiveCount = execution.frozenCognitiveRepresentativeCount

    if values.get("network.social_enabled") is False:
        scenarioConfig["network"].update(
            {
                "averageDegree": 2,
                "echoChamberStrength": 0.0,
                "correctionReach": 0.0,
                "rewiringProbability": 1.0,
            }
        )
        proxyApplied = True
    if values.get("market_maker.inventory_constraint_enabled") is False:
        scenarioParameter = "marketMakerCapacity"
        scenarioValue = 3.0
        proxyApplied = True
    if values.get("population.passive_fund_enabled") is False:
        scenarioParameter = "passiveFlowMultiplier"
        scenarioValue = 0.05
        proxyApplied = True
    if values.get("cognition.memory_enabled") is False:
        cognitiveCount = 0
        proxyApplied = True
    if values.get("cognition.fixed_llm_decisions") is True:
        proxyApplied = True
    if values.get("market.risk_off_factor_enabled") is False:
        _moveMechanismClaimsOutsideWindow(transformedPack, execution.steps)
        scenarioParameter = "stopLossSensitivity"
        scenarioValue = 0.05
        proxyApplied = True
    if (
        values.get("execution.price_impact_enabled") is False
        or values.get("execution.slippage_enabled") is False
    ):
        scenarioParameter = "liquidityDepthMultiplier"
        scenarioValue = 3.0
        proxyApplied = True

    if values.get("control.irrelevant_event_injected") is True:
        transformedPack.setdefault("claims", []).append(_irrelevantControlClaim(transformedPack))
    if values.get("control.label_swap_text_held") is True:
        _swapMechanismClaimLabel(transformedPack)
    if values.get("control.seeded_event_time_placebo") is True:
        _misplaceMechanismClaim(transformedPack, execution.steps, runRequest.seed)
    if values.get("control.non_event_day") is True:
        _moveMechanismClaimsOutsideWindow(transformedPack, execution.steps)
        proxyApplied = True

    cognitiveSignals = _frozenCognitiveTape(
        transformedPack,
        representativeCount=cognitiveCount,
        studyId=runRequest.studyId,
        cellId=runRequest.cellId,
    )
    simulation = runScenario(
        seed=runRequest.seed,
        populationSize=execution.populationSize,
        steps=execution.steps,
        parameter=scenarioParameter,
        value=scenarioValue,
        eventPack=transformedPack,
        cognitiveSignals=cognitiveSignals,
        scenarioConfig=scenarioConfig,
    )
    metrics = simulation["metrics"]
    selectedOutcomes: dict[str, float] = {}
    recoveryCensored = False
    requestedOutcomes = (
        requestData.preregistration.primaryOutcomes + requestData.preregistration.secondaryOutcomes
    )
    for outcome in requestedOutcomes:
        metricName = OUTCOME_REGISTRY[outcome.outcomeId][0]
        rawValue = metrics[metricName]
        if rawValue is None:
            if metricName != "recoverySteps":
                raise RuntimeError(f"simulator metric {metricName} is unexpectedly null")
            rawValue = execution.steps + 1
            recoveryCensored = True
        selectedOutcomes[outcome.outcomeId] = float(rawValue)
    invariants = simulation["invariants"]
    invariantsValid = all(
        bool(invariants[key])
        for key in (
            "positionConserved",
            "cashConserved",
            "allTradesRecorded",
            "selfTradePrevented",
            "scientificLedgerValid",
        )
    )
    if not invariantsValid:
        raise RuntimeError("study simulation failed a preregistered ledger invariant")
    return RunOutput.fromMappings(
        selectedOutcomes,
        diagnostics=(
            DiagnosticValue(
                name="cognitiveTapeRepresentatives",
                value=cognitiveCount,
                unit="agents",
            ),
            DiagnosticValue(
                name="invariantsValid",
                value=invariantsValid,
                unit="boolean",
            ),
            DiagnosticValue(
                name="proxyMechanismApplied",
                value=proxyApplied,
                unit="boolean",
            ),
            DiagnosticValue(
                name="recoveryRightCensored",
                value=recoveryCensored,
                unit="boolean",
            ),
        ),
        artifactReferences=(f"sha256:{simulation['eventLogHash']}",),
    )


def _applyFactorSettings(
    values: Mapping[str, Any],
    scenarioConfig: dict[str, dict[str, Any]],
) -> None:
    mappings = {
        "market.fee_bps": ("market", "feeBps"),
        "market.latency_ms": ("market", "latencyMs"),
        "market.price_collar_bps": ("market", "priceCollarBps"),
        "network.correction_reach": ("network", "correctionReach"),
        "network.echo_chamber_strength": ("network", "echoChamberStrength"),
        "network.rewiring_probability": ("network", "rewiringProbability"),
        "population.institutional_share": ("population", "institutionalShare"),
    }
    for path, (section, fieldName) in mappings.items():
        if path not in values:
            continue
        value = values[path]
        scenarioConfig[section][fieldName] = round(value) if path == "market.latency_ms" else value


def _frozenCognitiveTape(
    eventPack: Mapping[str, Any],
    *,
    representativeCount: int,
    studyId: str,
    cellId: str,
) -> tuple[dict[str, Any], ...]:
    if representativeCount <= 0:
        return ()
    acceptedClaimIds = [
        str(claim["claimId"])
        for claim in eventPack.get("claims", [])
        if claim.get("claimId")
        and claim.get("preFreezeReviewStatus", claim.get("reviewStatus"))
        in {"HUMAN_APPROVED", "EDITED", "FROZEN"}
    ]
    if not acceptedClaimIds:
        return ()
    return tuple(
        {
            "representativeIndex": index,
            "decisionId": f"study-{studyId}-{index:02d}",
            "decisionRound": 0,
            "activeFromStep": 0,
            "direction": "NEGATIVE" if index % 2 == 0 else "POSITIVE",
            "actionPreference": "SELL" if index % 2 == 0 else "BUY",
            "evidenceIds": acceptedClaimIds[:4],
            "confidence": 0.62,
            "uncertainty": 0.38,
            "role": f"frozen-study-proxy:{cellId}"[:100],
        }
        for index in range(representativeCount)
    )


def _eventPackStart(eventPack: Mapping[str, Any]) -> datetime:
    rawValue = eventPack.get("asOf")
    if not isinstance(rawValue, str):
        return datetime(2026, 1, 1, tzinfo=UTC)
    parsed = datetime.fromisoformat(rawValue.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def _mechanismClaimIds(eventPack: Mapping[str, Any]) -> set[str]:
    rules = eventPack.get("mechanismRules", {})
    if not isinstance(rules, Mapping):
        return set()
    return {
        str(claimId)
        for key, claimId in rules.items()
        if key.endswith("ClaimId") and isinstance(claimId, str)
    }


def _moveMechanismClaimsOutsideWindow(eventPack: dict[str, Any], steps: int) -> None:
    outsideWindow = _eventPackStart(eventPack) + timedelta(seconds=(steps + 10) * 5)
    mechanismIds = _mechanismClaimIds(eventPack)
    for claim in eventPack.get("claims", []):
        if claim.get("claimId") in mechanismIds:
            claim["knownAt"] = outsideWindow.isoformat()


def _misplaceMechanismClaim(eventPack: dict[str, Any], steps: int, seed: int) -> None:
    mechanismIds = _mechanismClaimIds(eventPack)
    if not mechanismIds:
        return
    misplacedStep = 1 + seed % max(1, steps - 2)
    misplacedAt = _eventPackStart(eventPack) + timedelta(seconds=misplacedStep * 5)
    for claim in eventPack.get("claims", []):
        if claim.get("claimId") in mechanismIds:
            claim["knownAt"] = misplacedAt.isoformat()
            break


def _swapMechanismClaimLabel(eventPack: dict[str, Any]) -> None:
    mechanismIds = _mechanismClaimIds(eventPack)
    for claim in eventPack.get("claims", []):
        if claim.get("claimId") in mechanismIds:
            claim["claimType"] = "PLACEBO_LABEL_TEXT_HELD"
            return


def _irrelevantControlClaim(eventPack: Mapping[str, Any]) -> dict[str, Any]:
    knownAt = _eventPackStart(eventPack).isoformat()
    return {
        "claimId": "control-irrelevant-weather",
        "text": "A declared synthetic weather event occurs in an unrelated region.",
        "textZh": "一个明确标注的合成天气事件发生在无关地区。",
        "knownAt": knownAt,
        "sourceIds": [],
        "reviewStatus": "FROZEN",
        "preFreezeReviewStatus": "HUMAN_APPROVED",
        "synthetic": True,
    }


def _mechanismSemantics() -> list[dict[str, str]]:
    return [
        {
            "kind": "BASELINE_SELF/IRRELEVANT_EVENT/LABEL_SWAP_TEXT_HELD",
            "status": "DIRECT_NULL_CONTROL",
            "boundary": (
                "The same kernel and seeds are retained; only declared control metadata changes."
            ),
        },
        {
            "kind": "MISPLACED_EVENT_TIME/NON_EVENT_DAY",
            "status": "DIRECT_INFORMATION_TIMING_WITH_BOUNDED_EVENT_PROXY",
            "boundary": (
                "Claim timing is changed; the synthetic market-flow kernel is not "
                "a historical day replay."
            ),
        },
        {
            "kind": "RULE_ONLY/HYBRID/LLM_REPRESENTATIVES_MIN_LIQUIDITY/FIXED_LLM_DECISIONS",
            "status": "FROZEN_COGNITIVE_TAPE_PROXY",
            "boundary": (
                "No provider call occurs; the tape exercises the deterministic "
                "cognition-policy boundary only."
            ),
        },
        {
            "kind": (
                "NO_SOCIAL/NO_MEMORY/NO_MM_INVENTORY_CONSTRAINT/NO_PASSIVE_FUND/"
                "NO_RISK_OFF_FACTOR/NO_PRICE_IMPACT_SLIPPAGE"
            ),
            "status": "BOUNDED_EXECUTABLE_PROXY",
            "boundary": (
                "The current kernel applies the documented nearest executable mechanism; "
                "this is not a literal subsystem removal."
            ),
        },
    ]


def _publicStudyRun(item: dict[str, Any], *, includeResult: bool = True) -> dict[str, Any]:
    public = {key: value for key, value in item.items() if key != "sessionId"}
    if not includeResult:
        public.pop("result", None)
        public.pop("spec", None)
    return public


def _verifyStoredStudyRun(item: dict[str, Any]) -> dict[str, Any]:
    if _canonicalHash(item["spec"]) != item["specHash"]:
        raise ApiError(
            "STUDY_INTEGRITY_FAILURE",
            500,
            "The stored Study preregistration does not match its immutable hash.",
        )
    if _canonicalHash(item["result"]) != item["resultHash"]:
        raise ApiError(
            "STUDY_INTEGRITY_FAILURE",
            500,
            "The stored Study result does not match its immutable hash.",
        )
    return item


def _canonicalHash(value: object) -> str:
    payload = json.dumps(
        _jsonValue(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _jsonValue(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonValue(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonValue(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonValue(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _presetItems() -> list[dict[str, Any]]:
    return [
        {
            "presetId": "spacex-s1-index-demand-liquidity",
            "eventPackId": "spacex-nasdaq100-2026-v1",
            "title": "SpaceX S1 — Index demand and liquidity",
            "titleZh": "SpaceX S1——指数需求与流动性",
            "question": (
                "Under which modeled conditions does passive demand amplify liquidity stress?"
            ),
            "questionZh": "在什么模型条件下，被动需求会放大流动性压力？",
            "recommendedInterventionParameter": "marketMakerCapacity",
            "factorPaths": [
                "intervention.value",
                "population.institutional_share",
                "market.price_collar_bps",
            ],
            "primaryOutcomeIds": ["max-spread-bps", "max-drawdown-pct", "total-volume"],
        },
        {
            "presetId": "spacex-s2-analyst-disagreement-narrative",
            "eventPackId": "spacex-nasdaq100-2026-v1",
            "title": "SpaceX S2 — Disagreement and narrative",
            "titleZh": "SpaceX S2——分歧与叙事",
            "question": (
                "How do modeled network homophily and institutional mix alter herding proxies?"
            ),
            "questionZh": "模型中的网络同质性和机构占比如何改变羊群代理指标？",
            "recommendedInterventionParameter": "socialAmplification",
            "factorPaths": [
                "intervention.value",
                "network.echo_chamber_strength",
                "population.institutional_share",
            ],
            "primaryOutcomeIds": ["order-imbalance", "cascade-score", "total-volume"],
        },
        {
            "presetId": "spacex-s3-misinformation-clarification",
            "eventPackId": "spacex-nasdaq100-2026-v1",
            "title": "SpaceX S3 — Misinformation and clarification",
            "titleZh": "SpaceX S3——错误信息与澄清",
            "question": "How do clarification delay and correction reach alter model recovery?",
            "questionZh": "澄清延迟和纠正触达如何改变模型恢复过程？",
            "recommendedInterventionParameter": "clarificationDelay",
            "factorPaths": [
                "intervention.value",
                "network.correction_reach",
                "network.rewiring_probability",
            ],
            "primaryOutcomeIds": [
                "recovery-steps",
                "network-reach-rate",
                "max-drawdown-pct",
            ],
        },
        {
            "presetId": "crowdstrike-c1-communication-timing",
            "eventPackId": "crowdstrike-outage-2024-v1",
            "title": "CrowdStrike C1 — Communication timing",
            "titleZh": "CrowdStrike C1——沟通时序",
            "question": "How does modeled clarification timing change liquidity and recovery?",
            "questionZh": "模型中的澄清时序如何改变流动性与恢复？",
            "recommendedInterventionParameter": "clarificationDelay",
            "factorPaths": ["intervention.value", "network.correction_reach"],
            "primaryOutcomeIds": ["recovery-steps", "max-spread-bps"],
        },
        {
            "presetId": "crowdstrike-c2-damage-uncertainty",
            "eventPackId": "crowdstrike-outage-2024-v1",
            "title": "CrowdStrike C2 — Damage uncertainty",
            "titleZh": "CrowdStrike C2——损害范围不确定性",
            "question": "How do information latency and institutional mix alter tail-risk proxies?",
            "questionZh": "信息延迟和机构占比如何改变尾部风险代理指标？",
            "recommendedInterventionParameter": "informationLatency",
            "factorPaths": ["intervention.value", "population.institutional_share"],
            "primaryOutcomeIds": ["tail-loss-probability", "max-drawdown-pct"],
        },
        {
            "presetId": "gamestop-g1-network-topology",
            "eventPackId": "gamestop-meme-2021-v1",
            "title": "GameStop G1 — Network topology",
            "titleZh": "GameStop G1——网络拓扑",
            "question": "How do rewiring and echo-chamber strength alter propagation?",
            "questionZh": "重连概率和回音室强度如何改变传播？",
            "recommendedInterventionParameter": "socialAmplification",
            "factorPaths": [
                "network.rewiring_probability",
                "network.echo_chamber_strength",
            ],
            "primaryOutcomeIds": ["network-reach-rate", "cascade-score"],
        },
        {
            "presetId": "gamestop-g2-market-mechanisms",
            "eventPackId": "gamestop-meme-2021-v1",
            "title": "GameStop G2 — Market mechanisms",
            "titleZh": "GameStop G2——市场机制",
            "question": "How do liquidity capacity and execution assumptions alter stress metrics?",
            "questionZh": "流动性容量和执行假设如何改变压力指标？",
            "recommendedInterventionParameter": "liquidityDepthMultiplier",
            "factorPaths": ["intervention.value", "market.fee_bps", "market.latency_ms"],
            "primaryOutcomeIds": ["max-spread-bps", "min-depth", "total-volume"],
        },
    ]
