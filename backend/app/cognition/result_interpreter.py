"""实验结果解释器的只读工具、上下文裁剪与响应契约。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field

from backend.app.cognition.gateway import ModelUsage
from backend.app.cognition.models import (
    ResultEvidenceTool,
    ResultInterpretationAnswer,
    StrictFrozenModel,
)

ResultLanguage = Literal["en", "zh-CN"]
# 11 个工具全部启用时仍需为外层 evidence 元数据预留空间，避免单项均合法但
# 聚合后超过上下文上限。6 KB × 11 加包装字段可稳定控制在 72 KB 以内。
MAX_TOOL_PAYLOAD_BYTES = 6_000
MAX_TOOL_CONTEXT_BYTES = 72_000

DEFAULT_RESULT_TOOLS: tuple[ResultEvidenceTool, ...] = tuple(ResultEvidenceTool)

TOOL_LABELS: dict[ResultEvidenceTool, tuple[str, str]] = {
    ResultEvidenceTool.OVERVIEW: ("Experiment overview", "实验概览"),
    ResultEvidenceTool.METRIC_SUMMARY: ("Metric summaries", "指标汇总"),
    ResultEvidenceTool.PAIRED_DELTAS: ("Paired-seed differences", "配对随机种子差异"),
    ResultEvidenceTool.PATH_SERIES: ("Median market paths", "市场中位路径"),
    ResultEvidenceTool.TRACE: ("Mechanism traces", "机制链路"),
    ResultEvidenceTool.AGENT_OUTCOMES: ("Agent outcomes", "Agent 结果"),
    ResultEvidenceTool.COGNITION_SUMMARY: ("Cognition run summary", "认知层运行汇总"),
    ResultEvidenceTool.COGNITION_DECISIONS: ("Cognition decisions", "认知层决策"),
    ResultEvidenceTool.ANALYSIS_DIAGNOSTICS: ("Analysis diagnostics", "分析诊断"),
    ResultEvidenceTool.LIMITATIONS: ("Limitations", "局限性"),
    ResultEvidenceTool.MANIFEST: ("Versions and provenance", "版本与来源"),
}


class ResultToolResult(StrictFrozenModel):
    """单个工具返回的有界、可引用结果切片。"""

    tool: ResultEvidenceTool
    evidence_id: str = Field(pattern=r"^result:[a-z-]+$")
    payload: dict[str, Any]
    item_count: int = Field(ge=0)
    truncated: bool = False


class ResultToolActivity(StrictFrozenModel):
    tool: ResultEvidenceTool
    label: str
    item_count: int = Field(ge=0)
    truncated: bool
    evidence_id: str


class ResultInterpretationRun(StrictFrozenModel):
    interpretation: ResultInterpretationAnswer
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    model: str
    tool_activity: tuple[ResultToolActivity, ...]
    usage: ModelUsage
    latency_ms: float = Field(ge=0.0)
    model_calls: int = Field(ge=1, le=2)
    cache_hit: bool
    repair_used: bool
    planner_used: bool
    prompt_version: str


def buildResultIndex(result: Mapping[str, Any]) -> dict[str, Any]:
    """只暴露结构索引给 Planner，避免在规划调用中复制整份结果。"""

    metrics = _asMapping(result.get("metricSummaries"))
    cognition = _asMapping(result.get("cognition"))
    diagnostics = _asMapping(result.get("analysisDiagnostics"))
    return {
        "experimentId": _boundedText(result.get("experimentId"), 160),
        "question": _boundedText(result.get("question"), 800),
        "questionZh": _boundedText(result.get("questionZh"), 800),
        "topLevelSections": sorted(str(key) for key in result),
        "metricIds": list(metrics)[:100],
        "primaryOutcome": diagnostics.get("preregisteredPrimaryOutcome"),
        "pairedRunCount": len(_asSequence(result.get("pairedRuns"))),
        "pathSeriesAvailable": sorted(_asMapping(result.get("medianPaths"))),
        "traceCount": len(_asSequence(result.get("traces"))),
        "agentFlowCount": len(_asMapping(result.get("agentFlows"))),
        "agentPnlCount": len(_asMapping(result.get("agentPnl"))),
        "cognitionDecisionCount": len(_asSequence(cognition.get("decisions"))),
        "availableTools": [tool.value for tool in ResultEvidenceTool],
    }


def executeResultTools(
    result: Mapping[str, Any],
    tools: Sequence[ResultEvidenceTool],
) -> tuple[ResultToolResult, ...]:
    """按白名单执行确定性读取；工具绝不访问网络、文件、SQL 或修改状态。"""

    orderedTools = tuple(dict.fromkeys(tools))
    outputs = tuple(_executeResultTool(result, tool) for tool in orderedTools)
    if len(_toolContextJson(outputs).encode("utf-8")) > MAX_TOOL_CONTEXT_BYTES:
        raise ValueError("result tool context exceeds the bounded interpretation limit")
    return outputs


def toolResultsPayload(results: Sequence[ResultToolResult]) -> list[dict[str, Any]]:
    return [
        {
            "tool": result.tool.value,
            "evidenceId": result.evidence_id,
            "itemCount": result.item_count,
            "truncated": result.truncated,
            "payload": result.payload,
        }
        for result in results
    ]


def toolActivities(
    results: Sequence[ResultToolResult], language: ResultLanguage
) -> tuple[ResultToolActivity, ...]:
    return tuple(
        ResultToolActivity(
            tool=result.tool,
            label=TOOL_LABELS[result.tool][1 if language == "zh-CN" else 0],
            item_count=result.item_count,
            truncated=result.truncated,
            evidence_id=result.evidence_id,
        )
        for result in results
    )


def _executeResultTool(
    result: Mapping[str, Any], tool: ResultEvidenceTool
) -> ResultToolResult:
    metricIds = _outcomeMetricIds(result)
    truncated = False

    if tool is ResultEvidenceTool.OVERVIEW:
        payload = {
            "experimentId": result.get("experimentId"),
            "question": result.get("question"),
            "questionZh": result.get("questionZh"),
            "scenarioDiff": result.get("scenarioDiff"),
            "stoppingRule": result.get("stoppingRule"),
            "narrativeReport": result.get("narrativeReport"),
            "validPairedSeeds": _asMapping(result.get("manifest")).get("validPairedSeeds"),
        }
        itemCount = 1
    elif tool is ResultEvidenceTool.METRIC_SUMMARY:
        summaries = _asMapping(result.get("metricSummaries"))
        includedIds = _orderedSubset((*metricIds, *summaries.keys()), limit=20)
        payload = {
            "totalMetrics": len(summaries),
            "includedMetricIds": includedIds,
            "summaries": {metricId: summaries[metricId] for metricId in includedIds},
        }
        itemCount = len(summaries)
        truncated = len(includedIds) < len(summaries)
    elif tool is ResultEvidenceTool.PAIRED_DELTAS:
        summaries = _asMapping(result.get("metricSummaries"))
        pairedRuns = _asSequence(result.get("pairedRuns"))
        includedRuns = pairedRuns[:50]
        payload = {
            "metricIds": metricIds,
            "totalMetricCount": len(summaries),
            "includedMetricCount": len(metricIds),
            "omittedMetricIds": [
                str(metricId) for metricId in summaries if metricId not in metricIds
            ],
            "totalPairs": len(pairedRuns),
            "pairs": [
                {
                    "seed": _asMapping(run).get("seed"),
                    "delta": {
                        metricId: _asMapping(_asMapping(run).get("delta")).get(metricId)
                        for metricId in metricIds
                    },
                }
                for run in includedRuns
            ],
        }
        itemCount = len(pairedRuns)
        truncated = (
            len(includedRuns) < len(pairedRuns) or len(metricIds) < len(summaries)
        )
    elif tool is ResultEvidenceTool.PATH_SERIES:
        paths = _asMapping(result.get("medianPaths"))
        steps = _asSequence(paths.get("step"))
        if steps:
            sampleIndices = _sampleIndices(len(steps), 60)
            projectedPaths: dict[str, Any] = {
                "step": [steps[index] for index in sampleIndices],
            }
            for scenarioName in ("baseline", "intervention", "delta"):
                scenario = _asMapping(paths.get(scenarioName))
                projectedPaths[scenarioName] = {
                    str(pathName): [
                        series[index]
                        for index in sampleIndices
                        if index < len(series)
                    ]
                    for pathName, rawSeries in scenario.items()
                    if (series := _asSequence(rawSeries))
                }
            payload = {
                "totalSteps": len(steps),
                "includedSteps": len(sampleIndices),
                "series": projectedPaths,
            }
            itemCount = len(steps)
            truncated = len(sampleIndices) < len(steps)
        else:
            # 兼容旧版结果，其中每个键直接对应一列点序列。
            projectedLegacyPaths: dict[str, Any] = {}
            totalPoints = 0
            for name, value in paths.items():
                sequence = _asSequence(value)
                totalPoints += len(sequence)
                projectedLegacyPaths[str(name)] = _sampleSequence(sequence, 60)
                truncated = truncated or len(sequence) > 60
            payload = {"totalPoints": totalPoints, "series": projectedLegacyPaths}
            itemCount = totalPoints
    elif tool is ResultEvidenceTool.TRACE:
        traces = _asSequence(result.get("traces"))
        includedTraces = traces[:80]
        payload = {
            "totalTraceNodes": len(traces),
            "nodes": [_projectTrace(node) for node in includedTraces],
        }
        itemCount = len(traces)
        truncated = len(includedTraces) < len(traces)
    elif tool is ResultEvidenceTool.AGENT_OUTCOMES:
        flows = _asMapping(result.get("agentFlows"))
        pnl = _asMapping(result.get("agentPnl"))
        runSummaries = _asMapping(result.get("runSummaries"))
        agentTypes = sorted(set(flows) | set(pnl))
        payload = {
            "agentTypes": agentTypes,
            "agentFlows": dict(flows),
            "agentPnl": dict(pnl),
            "runSummaries": dict(runSummaries),
        }
        itemCount = len(agentTypes) + len(runSummaries)
    elif tool is ResultEvidenceTool.COGNITION_SUMMARY:
        cognition = _asMapping(result.get("cognition"))
        payload = {key: value for key, value in cognition.items() if key != "decisions"}
        itemCount = 1 if cognition else 0
    elif tool is ResultEvidenceTool.COGNITION_DECISIONS:
        decisions = _asSequence(_asMapping(result.get("cognition")).get("decisions"))
        includedDecisions = decisions[:20]
        payload = {
            "totalDecisions": len(decisions),
            "decisions": [_projectDecision(decision) for decision in includedDecisions],
        }
        itemCount = len(decisions)
        truncated = len(includedDecisions) < len(decisions)
    elif tool is ResultEvidenceTool.ANALYSIS_DIAGNOSTICS:
        payload = {
            "analysisDiagnostics": result.get("analysisDiagnostics"),
            "stoppingRule": result.get("stoppingRule"),
        }
        itemCount = 1 if result.get("analysisDiagnostics") is not None else 0
    elif tool is ResultEvidenceTool.LIMITATIONS:
        limitations = _asSequence(result.get("limitations"))
        limitationsZh = _asSequence(result.get("limitationsZh"))
        payload = {
            "limitations": [_projectLimitation(item) for item in limitations[:30]],
            "limitationsZh": [_boundedText(item, 1_500) for item in limitationsZh[:30]],
        }
        itemCount = max(len(limitations), len(limitationsZh))
        truncated = len(limitations) > 30 or len(limitationsZh) > 30
    else:
        manifest = _asMapping(result.get("manifest"))
        eventPack = _asMapping(result.get("eventPackManifest"))
        sources = _asSequence(eventPack.get("sources"))
        claims = _asSequence(eventPack.get("claims"))
        payload = {
            "manifest": manifest,
            "eventPack": {
                "id": eventPack.get("id"),
                "title": eventPack.get("title"),
                "titleZh": eventPack.get("titleZh"),
                "summary": _boundedText(eventPack.get("summary"), 1_000),
                "summaryZh": _boundedText(eventPack.get("summaryZh"), 1_000),
                "asOf": eventPack.get("asOf"),
                "instrument": eventPack.get("instrument"),
                "sourceCount": len(sources),
                "claimCount": len(claims),
                "sources": [_projectSource(source) for source in sources[:20]],
                "claims": [_projectClaim(claim) for claim in claims[:30]],
            },
        }
        itemCount = 1 + len(sources) + len(claims)
        truncated = len(sources) > 20 or len(claims) > 30

    boundedPayload, payloadTruncated = _boundPayload(payload)
    return ResultToolResult(
        tool=tool,
        evidence_id=f"result:{tool.value.lower().replace('_', '-')}",
        payload=boundedPayload,
        item_count=itemCount,
        truncated=truncated or payloadTruncated,
    )


def _outcomeMetricIds(result: Mapping[str, Any]) -> tuple[str, ...]:
    diagnostics = _asMapping(result.get("analysisDiagnostics"))
    primary = diagnostics.get("preregisteredPrimaryOutcome")
    family = _asSequence(diagnostics.get("outcomeFamily"))
    summaries = _asMapping(result.get("metricSummaries"))
    candidates = [primary, *family, *summaries]
    return tuple(
        item
        for item in _orderedSubset((str(value) for value in candidates if value), limit=16)
        if item in summaries
    )


def _projectTrace(value: Any) -> dict[str, Any]:
    trace = _asMapping(value)
    allowedKeys = (
        "traceId",
        "parentTraceId",
        "step",
        "eventType",
        "agentType",
        "agentId",
        "summary",
        "summaryZh",
        "important",
        "scenario",
        "seed",
    )
    projected = {key: trace.get(key) for key in allowedKeys if key in trace}
    payload = _asMapping(trace.get("payload"))
    if payload:
        projected["payload"] = _compactValue(
            payload,
            listLimit=12,
            stringLimit=500,
            depthLimit=3,
        )
    return projected


def _projectDecision(value: Any) -> dict[str, Any]:
    decision = _asMapping(value)
    allowedKeys = (
        "agentId",
        "representativeIndex",
        "role",
        "actionPreference",
        "direction",
        "confidence",
        "uncertainty",
        "evidenceIds",
        "decisionSummary",
        "fallbackUsed",
        "repairUsed",
        "failureReason",
        "failureCodes",
        "decisionRound",
        "activeFromStep",
        "promptTokens",
        "completionTokens",
        "costUpperBoundUsd",
    )
    return {key: decision.get(key) for key in allowedKeys if key in decision}


def _projectSource(value: Any) -> dict[str, Any]:
    source = _asMapping(value)
    allowedKeys = (
        "sourceId",
        "title",
        "publisher",
        "url",
        "sourceType",
        "publishedAt",
        "knownAt",
        "contentHash",
    )
    return {key: source.get(key) for key in allowedKeys if key in source}


def _projectLimitation(value: Any) -> dict[str, Any] | str | None:
    limitation = _asMapping(value)
    if not limitation:
        return _boundedText(value, 1_500)
    return {
        key: _boundedText(limitation.get(key), 1_500)
        for key in ("code", "text", "textZh")
        if limitation.get(key) is not None
    }


def _projectClaim(value: Any) -> dict[str, Any]:
    claim = _asMapping(value)
    allowedKeys = (
        "claimId",
        "text",
        "textZh",
        "claimType",
        "sourceIds",
        "sourceTier",
        "knownAt",
        "confidence",
        "impactChannels",
        "reviewStatus",
        "synthetic",
    )
    projected = {key: claim.get(key) for key in allowedKeys if key in claim}
    if "text" in projected:
        projected["text"] = _boundedText(projected["text"], 700)
    if "textZh" in projected:
        projected["textZh"] = _boundedText(projected["textZh"], 700)
    return projected


def _boundPayload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    initial = dict(payload)
    if _jsonSize(initial) <= MAX_TOOL_PAYLOAD_BYTES:
        return initial, False
    compact = _compactValue(initial, listLimit=20, stringLimit=600, depthLimit=4)
    if isinstance(compact, dict) and _jsonSize(compact) <= MAX_TOOL_PAYLOAD_BYTES:
        return compact, True
    compact = _compactValue(initial, listLimit=8, stringLimit=240, depthLimit=3)
    if isinstance(compact, dict) and _jsonSize(compact) <= MAX_TOOL_PAYLOAD_BYTES:
        return compact, True
    return {
        "contextOmittedDueToLimit": True,
        "availableKeys": list(initial)[:80],
        "originalJsonBytes": _jsonSize(initial),
    }, True


def _compactValue(
    value: Any,
    *,
    listLimit: int,
    stringLimit: int,
    depthLimit: int,
    depth: int = 0,
) -> Any:
    if isinstance(value, str):
        return _boundedText(value, stringLimit)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth >= depthLimit:
        if isinstance(value, Mapping):
            return {"availableKeys": [str(key) for key in list(value)[:40]]}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return {"itemCount": len(value), "itemsOmittedAtDepthLimit": True}
        return _boundedText(value, stringLimit)
    if isinstance(value, Mapping):
        return {
            str(key): _compactValue(
                item,
                listLimit=listLimit,
                stringLimit=stringLimit,
                depthLimit=depthLimit,
                depth=depth + 1,
            )
            for key, item in list(value.items())[:60]
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        sampled = _sampleSequence(value, listLimit)
        return [
            _compactValue(
                item,
                listLimit=listLimit,
                stringLimit=stringLimit,
                depthLimit=depthLimit,
                depth=depth + 1,
            )
            for item in sampled
        ]
    return _boundedText(value, stringLimit)


def _sampleSequence(value: Sequence[Any], maximum: int) -> list[Any]:
    items = list(value)
    if len(items) <= maximum:
        return items
    indices = _sampleIndices(len(items), maximum)
    return [items[index] for index in indices]


def _sampleIndices(length: int, maximum: int) -> list[int]:
    if length <= 0 or maximum <= 0:
        return []
    if length <= maximum:
        return list(range(length))
    if maximum == 1:
        return [0]
    return sorted(
        {
            round(index * (length - 1) / (maximum - 1))
            for index in range(maximum)
        }
    )


def _orderedSubset(values: Sequence[Any] | Any, *, limit: int) -> tuple[str, ...]:
    output: list[str] = []
    for value in values:
        normalized = str(value)
        if normalized not in output:
            output.append(normalized)
        if len(output) >= limit:
            break
    return tuple(output)


def _boundedText(value: Any, maximum: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= maximum else f"{text[: maximum - 1]}…"


def _asMapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _asSequence(value: Any) -> Sequence[Any]:
    return (
        value
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
        else ()
    )


def _jsonSize(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _toolContextJson(results: Sequence[ResultToolResult]) -> str:
    return json.dumps(
        toolResultsPayload(results),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
