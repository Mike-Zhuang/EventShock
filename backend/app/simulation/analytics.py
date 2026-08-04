"""Matched-seed 结果汇总与稳健的经验区间。"""

from __future__ import annotations

import hashlib
import statistics
from collections.abc import Callable
from typing import Any

from backend.app.validation.statistics import analyzePairedExperiment

METRIC_KEYS = (
    "maxDrawdownPct",
    "realizedVolatilityPct",
    "maxSpreadBps",
    "minDepth",
    "recoverySteps",
    "totalVolume",
    "orderImbalance",
    "cascadeScore",
    "networkReachRate",
    "informationDelaySteps",
    "liquidityStressIndex",
    "tailLossProbability",
    "agentPnlDispersionCents",
    "systemEquityChangeCents",
    "forcedLiquidationVolume",
    "ledgerRejectedOrders",
    "cognitiveOrderCount",
    "validCognitionDecisionCount",
    "cognitionSignalConsumedCount",
    "validCognitionSignalConsumedCount",
    "cognitionChangedIntentCount",
    "cognitionInfluencedOrderCount",
    "cognitionRiskBlockedCount",
    "cognitionNoActionCount",
    "cognitionEffectRate",
    "cognitionOrderEffectRate",
    "benchmarkReturnPct",
    "abnormalReturnPct",
    "haltCount",
    "haltedSteps",
    "totalFeesPaidCents",
)

BASE_PATH_KEYS = (
    "price",
    "fundamentalPrice",
    "benchmark",
    "spreadBps",
    "depth",
    "volume",
    "sentiment",
)
OPTIONAL_PATH_KEYS = (
    "networkReach",
    "liquidityStress",
    "tailRisk",
    "systemEquityCents",
)
FLOW_KEYS = (
    "buyVolume",
    "sellVolume",
    "netVolume",
    "orderCount",
    "riskRejectedCount",
    "forcedVolume",
    "realizedPnlCents",
    "unrealizedPnlCents",
    "endingEquityCents",
)
RUN_SUMMARY_SECTIONS = (
    "networkMetrics",
    "liquidityMetrics",
    "tailRiskMetrics",
    "systemMetrics",
)
AGENT_PNL_KEYS = (
    "realizedPnlCents",
    "unrealizedPnlCents",
    "endingEquityCents",
    "equityChangeCents",
)


def aggregatePairedResults(
    baselineRuns: list[dict[str, Any]],
    interventionRuns: list[dict[str, Any]],
    *,
    representativeRunLoader: Callable[[int], tuple[dict[str, Any], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if len(baselineRuns) != len(interventionRuns):
        raise ValueError("baseline and intervention run counts differ")
    if not baselineRuns:
        raise ValueError("at least one paired run is required")

    pairedRuns: list[dict[str, Any]] = []
    for baselineRun, interventionRun in zip(baselineRuns, interventionRuns, strict=True):
        if baselineRun["seed"] != interventionRun["seed"]:
            raise ValueError("matched runs must use identical seeds")
        deltas = {
            metricKey: _numericDelta(
                baselineRun["metrics"].get(metricKey),
                interventionRun["metrics"].get(metricKey),
            )
            for metricKey in METRIC_KEYS
        }
        pairedRuns.append(
            {
                "seed": baselineRun["seed"],
                "baseline": baselineRun["metrics"],
                "intervention": interventionRun["metrics"],
                "delta": deltas,
                "baselineEventLogHash": baselineRun["eventLogHash"],
                "interventionEventLogHash": interventionRun["eventLogHash"],
            }
        )

    metricSummaries = {
        metricKey: _summarizeMetric(metricKey, baselineRuns, interventionRuns, pairedRuns)
        for metricKey in METRIC_KEYS
    }
    selectedIndex = _representativeRunIndex(
        baselineRuns,
        interventionRuns,
        metricSummaries,
    )
    representativeRuns = (
        representativeRunLoader(selectedIndex) if representativeRunLoader is not None else None
    )
    return {
        "pairedRuns": pairedRuns,
        "metricSummaries": metricSummaries,
        "medianPaths": _aggregatePaths(baselineRuns, interventionRuns),
        "agentFlows": _aggregateAgentFlows(baselineRuns, interventionRuns),
        "agentPnl": _aggregateAgentPnl(baselineRuns, interventionRuns),
        "runSummaries": {
            section: _aggregateRunSection(section, baselineRuns, interventionRuns)
            for section in RUN_SUMMARY_SECTIONS
        },
        "traces": _selectRepresentativeTraces(
            baselineRuns,
            interventionRuns,
            metricSummaries,
            selectedIndex=selectedIndex,
            representativeRuns=representativeRuns,
        ),
        "orderExecutionSummary": _selectRepresentativeOrderSummaries(
            baselineRuns,
            interventionRuns,
            metricSummaries,
            selectedIndex=selectedIndex,
            representativeRuns=representativeRuns,
        ),
    }


def _numericDelta(baselineValue: Any, interventionValue: Any) -> float | None:
    if baselineValue is None or interventionValue is None:
        return None
    return round(float(interventionValue) - float(baselineValue), 6)


def _summarizeMetric(
    metricKey: str,
    baselineRuns: list[dict[str, Any]],
    interventionRuns: list[dict[str, Any]],
    pairedRuns: list[dict[str, Any]],
) -> dict[str, Any]:
    baselineValues = [
        float(run["metrics"][metricKey])
        for run in baselineRuns
        if run["metrics"].get(metricKey) is not None
    ]
    interventionValues = [
        float(run["metrics"][metricKey])
        for run in interventionRuns
        if run["metrics"].get(metricKey) is not None
    ]
    deltaValues = [
        float(run["delta"][metricKey])
        for run in pairedRuns
        if run["delta"].get(metricKey) is not None
    ]
    pairedValues = [
        (
            float(baselineRun["metrics"][metricKey]),
            float(interventionRun["metrics"][metricKey]),
        )
        for baselineRun, interventionRun in zip(
            baselineRuns,
            interventionRuns,
            strict=True,
        )
        if baselineRun["metrics"].get(metricKey) is not None
        and interventionRun["metrics"].get(metricKey) is not None
    ]
    return {
        "baseline": _distributionSummary(baselineValues),
        "intervention": _distributionSummary(interventionValues),
        "delta": {
            **_distributionSummary(deltaValues),
            "directionConsistencyRate": _directionConsistency(deltaValues),
            "validN": len(deltaValues),
            **_pairedDiagnostics(metricKey, pairedValues),
        },
    }


def _pairedDiagnostics(
    metricKey: str,
    pairedValues: list[tuple[float, float]],
) -> dict[str, Any]:
    positiveTailProbability = (
        round(
            sum(intervention > baseline for baseline, intervention in pairedValues)
            / len(pairedValues),
            6,
        )
        if pairedValues
        else None
    )
    negativeTailProbability = (
        round(
            sum(intervention < baseline for baseline, intervention in pairedValues)
            / len(pairedValues),
            6,
        )
        if pairedValues
        else None
    )
    if len(pairedValues) < 2:
        return {
            "bootstrap95": None,
            "effectSize": None,
            "positiveTailProbability": positiveTailProbability,
            "negativeTailProbability": negativeTailProbability,
        }

    baselineValues = [value[0] for value in pairedValues]
    interventionValues = [value[1] for value in pairedValues]
    bootstrapSeed = int.from_bytes(
        hashlib.blake2s(metricKey.encode("utf-8"), digest_size=4).digest(),
        "big",
    )
    analysis = analyzePairedExperiment(
        baselineValues,
        interventionValues,
        bootstrapResamples=5_000,
        seed=bootstrapSeed,
    )
    return {
        "meanDifference": round(analysis.meanDifference, 6),
        "medianDifference": round(analysis.medianDifference, 6),
        "percentile95": {
            "lower": round(analysis.percentileLower, 6),
            "upper": round(analysis.percentileUpper, 6),
        },
        "bootstrap95": {
            "estimate": round(analysis.bootstrap95.estimate, 6),
            "lower": round(analysis.bootstrap95.lower, 6),
            "upper": round(analysis.bootstrap95.upper, 6),
            "confidenceLevel": analysis.bootstrap95.confidenceLevel,
            "resamples": analysis.bootstrap95.resamples,
            "seed": analysis.bootstrap95.seed,
            "containsZero": analysis.bootstrap95.containsZero,
        },
        "effectSize": {
            "cohensDz": (
                round(analysis.effectSize.cohensDz, 6)
                if analysis.effectSize.cohensDz is not None
                else None
            ),
            "matchedRankBiserial": round(
                analysis.effectSize.matchedRankBiserial,
                6,
            ),
            "standardDeviationDifference": round(
                analysis.effectSize.standardDeviationDifference,
                6,
            ),
        },
        "signConsistency": round(analysis.signConsistency, 6),
        "positiveTailProbability": round(analysis.positiveTailProbability, 6),
        "negativeTailProbability": round(analysis.negativeTailProbability, 6),
    }


def _distributionSummary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"median": None, "interval95": {"lower": None, "upper": None}}
    return {
        "median": round(statistics.median(values), 6),
        "interval95": {
            "lower": round(_quantile(values, 0.025), 6),
            "upper": round(_quantile(values, 0.975), 6),
        },
    }


def _quantile(values: list[float], probability: float) -> float:
    orderedValues = sorted(values)
    if len(orderedValues) == 1:
        return orderedValues[0]
    position = (len(orderedValues) - 1) * probability
    lowerIndex = int(position)
    upperIndex = min(lowerIndex + 1, len(orderedValues) - 1)
    fraction = position - lowerIndex
    return orderedValues[lowerIndex] * (1 - fraction) + orderedValues[upperIndex] * fraction


def _directionConsistency(values: list[float]) -> float | None:
    if not values:
        return None
    medianValue = statistics.median(values)
    if medianValue == 0:
        return round(sum(value == 0 for value in values) / len(values), 6)
    alignedCount = sum((value > 0) == (medianValue > 0) for value in values if value != 0)
    return round(alignedCount / len(values), 6)


def _aggregatePaths(
    baselineRuns: list[dict[str, Any]], interventionRuns: list[dict[str, Any]]
) -> dict[str, Any]:
    allRuns = [*baselineRuns, *interventionRuns]
    pathKeys = (
        *BASE_PATH_KEYS,
        *(
            pathKey
            for pathKey in OPTIONAL_PATH_KEYS
            if all(pathKey in run.get("paths", {}) for run in allRuns)
        ),
    )
    completedSteps = min(
        len(run["paths"][pathKey]) for run in allRuns for pathKey in ("step", *pathKeys)
    )
    baselinePaths = {
        pathKey: [
            round(
                statistics.median(float(run["paths"][pathKey][step]) for run in baselineRuns),
                6,
            )
            for step in range(completedSteps)
        ]
        for pathKey in pathKeys
    }
    interventionPaths = {
        pathKey: [
            round(
                statistics.median(float(run["paths"][pathKey][step]) for run in interventionRuns),
                6,
            )
            for step in range(completedSteps)
        ]
        for pathKey in pathKeys
    }
    return {
        "step": list(range(completedSteps)),
        "baseline": baselinePaths,
        "intervention": interventionPaths,
        "delta": {
            pathKey: [
                round(interventionValue - baselineValue, 6)
                for baselineValue, interventionValue in zip(
                    baselinePaths[pathKey], interventionPaths[pathKey], strict=True
                )
            ]
            for pathKey in pathKeys
        },
    }


def _aggregateAgentFlows(
    baselineRuns: list[dict[str, Any]], interventionRuns: list[dict[str, Any]]
) -> dict[str, Any]:
    agentTypes = sorted(
        set().union(*(run["agentFlows"].keys() for run in [*baselineRuns, *interventionRuns]))
    )
    return {
        agentType: {
            "baseline": {
                flowKey: round(
                    statistics.median(
                        run["agentFlows"].get(agentType, {}).get(flowKey, 0) for run in baselineRuns
                    ),
                    6,
                )
                for flowKey in FLOW_KEYS
            },
            "intervention": {
                flowKey: round(
                    statistics.median(
                        run["agentFlows"].get(agentType, {}).get(flowKey, 0)
                        for run in interventionRuns
                    ),
                    6,
                )
                for flowKey in FLOW_KEYS
            },
        }
        for agentType in agentTypes
    }


def _aggregateAgentPnl(
    baselineRuns: list[dict[str, Any]], interventionRuns: list[dict[str, Any]]
) -> dict[str, Any]:
    """按智能体类型汇总每次运行的组合损益，避免把单个智能体当成独立样本。"""

    agentTypes = sorted(
        {
            str(row["agentType"])
            for run in [*baselineRuns, *interventionRuns]
            for row in run.get("agentPnl", [])
            if row.get("agentType") is not None
        }
    )
    return {
        agentType: {
            metricKey: _summarizePairedValues(
                _agentTypeRunValues(baselineRuns, agentType, metricKey),
                _agentTypeRunValues(interventionRuns, agentType, metricKey),
            )
            for metricKey in AGENT_PNL_KEYS
        }
        for agentType in agentTypes
    }


def _agentTypeRunValues(
    runs: list[dict[str, Any]],
    agentType: str,
    metricKey: str,
) -> list[float | None]:
    values: list[float | None] = []
    for run in runs:
        rows = [
            row
            for row in run.get("agentPnl", [])
            if row.get("agentType") == agentType and _isNumeric(row.get(metricKey))
        ]
        values.append(sum(float(row[metricKey]) for row in rows) if rows else None)
    return values


def _aggregateRunSection(
    section: str,
    baselineRuns: list[dict[str, Any]],
    interventionRuns: list[dict[str, Any]],
) -> dict[str, Any]:
    sectionKeys = sorted(
        {key for run in [*baselineRuns, *interventionRuns] for key in run.get(section, {})}
    )
    output: dict[str, Any] = {}
    for key in sectionKeys:
        baselineValues = [run.get(section, {}).get(key) for run in baselineRuns]
        interventionValues = [run.get(section, {}).get(key) for run in interventionRuns]
        numericValues = [*baselineValues, *interventionValues]
        if any(_isNumeric(value) for value in numericValues):
            output[key] = _summarizePairedValues(
                [float(value) if _isNumeric(value) else None for value in baselineValues],
                [float(value) if _isNumeric(value) else None for value in interventionValues],
            )
        else:
            output[key] = {
                "baselineValues": _uniqueValues(baselineValues),
                "interventionValues": _uniqueValues(interventionValues),
            }
    return output


def _summarizePairedValues(
    baselineValues: list[float | None],
    interventionValues: list[float | None],
) -> dict[str, Any]:
    pairedValues = [
        (baselineValue, interventionValue)
        for baselineValue, interventionValue in zip(
            baselineValues,
            interventionValues,
            strict=True,
        )
        if baselineValue is not None and interventionValue is not None
    ]
    deltas = [
        interventionValue - baselineValue for baselineValue, interventionValue in pairedValues
    ]
    return {
        "baseline": _distributionSummary([baselineValue for baselineValue, _ in pairedValues]),
        "intervention": _distributionSummary(
            [interventionValue for _, interventionValue in pairedValues]
        ),
        "delta": {
            **_distributionSummary(deltas),
            "directionConsistencyRate": _directionConsistency(deltas),
            "validN": len(deltas),
        },
    }


def _isNumeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _uniqueValues(values: list[Any]) -> list[Any]:
    return sorted(
        {value for value in values if value is not None},
        key=lambda value: str(value),
    )


def _selectRepresentativeTraces(
    baselineRuns: list[dict[str, Any]],
    interventionRuns: list[dict[str, Any]],
    metricSummaries: dict[str, Any],
    *,
    selectedIndex: int | None = None,
    representativeRuns: tuple[dict[str, Any], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if selectedIndex is None:
        selectedIndex = _representativeRunIndex(
            baselineRuns,
            interventionRuns,
            metricSummaries,
        )
    selectedBaseline, selectedIntervention = representativeRuns or (
        baselineRuns[selectedIndex],
        interventionRuns[selectedIndex],
    )
    if selectedBaseline.get("seed") != baselineRuns[selectedIndex].get(
        "seed"
    ) or selectedIntervention.get("seed") != interventionRuns[selectedIndex].get("seed"):
        raise ValueError("representative run loader returned the wrong matched seed")
    baselineBySequence = {
        int(trace["globalSequence"]): trace
        for trace in selectedBaseline.get("traces", [])
        if isinstance(trace.get("globalSequence"), int)
    }
    selectedTraces: list[dict[str, Any]] = []
    for scenarioName, run in (
        ("baseline", selectedBaseline),
        ("intervention", selectedIntervention),
    ):
        initialTraces = run["traces"][:40]
        importantTraces = [trace for trace in run["traces"] if trace.get("important")]
        deduplicatedTraces = {
            trace["traceId"]: trace for trace in [*initialTraces, *importantTraces]
        }
        for trace in list(deduplicatedTraces.values())[:80]:
            globalSequence = trace.get("globalSequence")
            baselineTrace = (
                baselineBySequence.get(globalSequence) if isinstance(globalSequence, int) else None
            )
            selectedTraces.append(
                {
                    **trace,
                    "scenario": scenarioName,
                    "seed": run["seed"],
                    "isInterventionDifference": (
                        scenarioName == "intervention"
                        and _traceDiffersFromBaseline(trace, baselineTrace)
                    ),
                }
            )
    scenarioOrder = {"baseline": 0, "intervention": 1}
    return sorted(
        selectedTraces,
        key=lambda trace: (
            scenarioOrder[str(trace["scenario"])],
            int(trace.get("globalSequence", 0)),
            str(trace["traceId"]),
        ),
    )[:160]


def _selectRepresentativeOrderSummaries(
    baselineRuns: list[dict[str, Any]],
    interventionRuns: list[dict[str, Any]],
    metricSummaries: dict[str, Any],
    *,
    selectedIndex: int | None = None,
    representativeRuns: tuple[dict[str, Any], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if selectedIndex is None:
        selectedIndex = _representativeRunIndex(
            baselineRuns,
            interventionRuns,
            metricSummaries,
        )
    selectedBaseline, selectedIntervention = representativeRuns or (
        baselineRuns[selectedIndex],
        interventionRuns[selectedIndex],
    )
    if selectedBaseline.get("seed") != baselineRuns[selectedIndex].get(
        "seed"
    ) or selectedIntervention.get("seed") != interventionRuns[selectedIndex].get("seed"):
        raise ValueError("representative run loader returned the wrong matched seed")
    baselineBySequence = {
        int(item["submissionSequence"]): item
        for item in selectedBaseline.get("orderExecutionSummary", [])
    }
    summaries: list[dict[str, Any]] = []
    for scenarioName, run in (
        ("baseline", selectedBaseline),
        ("intervention", selectedIntervention),
    ):
        for item in run.get("orderExecutionSummary", []):
            submissionSequence = int(item["submissionSequence"])
            baselineItem = baselineBySequence.get(submissionSequence)
            summaries.append(
                {
                    **item,
                    "scenario": scenarioName,
                    "seed": run["seed"],
                    "isInterventionDifference": (
                        scenarioName == "intervention"
                        and _orderSummaryDiffersFromBaseline(item, baselineItem)
                    ),
                }
            )
    scenarioOrder = {"baseline": 0, "intervention": 1}
    return sorted(
        summaries,
        key=lambda item: (
            scenarioOrder[str(item["scenario"])],
            int(item["submissionSequence"]),
            str(item["orderId"]),
        ),
    )


def _representativeRunIndex(
    baselineRuns: list[dict[str, Any]],
    interventionRuns: list[dict[str, Any]],
    metricSummaries: dict[str, Any],
) -> int:
    targetDelta = metricSummaries["maxSpreadBps"]["delta"]["median"] or 0.0
    return min(
        range(len(baselineRuns)),
        key=lambda index: abs(
            (
                interventionRuns[index]["metrics"]["maxSpreadBps"]
                - baselineRuns[index]["metrics"]["maxSpreadBps"]
            )
            - targetDelta
        ),
    )


def _traceDiffersFromBaseline(
    interventionTrace: dict[str, Any],
    baselineTrace: dict[str, Any] | None,
) -> bool:
    if baselineTrace is None:
        return True
    excludedKeys = {
        "isInterventionDifference",
        "parentTraceId",
        "summary",
        "summaryZh",
        "traceId",
    }
    return {key: value for key, value in interventionTrace.items() if key not in excludedKeys} != {
        key: value for key, value in baselineTrace.items() if key not in excludedKeys
    }


def _orderSummaryDiffersFromBaseline(
    interventionSummary: dict[str, Any],
    baselineSummary: dict[str, Any] | None,
) -> bool:
    if baselineSummary is None:
        return True
    excludedKeys = {"isInterventionDifference", "orderTraceId", "tradeTraceIds"}
    return {
        key: value for key, value in interventionSummary.items() if key not in excludedKeys
    } != {key: value for key, value in baselineSummary.items() if key not in excludedKeys}
