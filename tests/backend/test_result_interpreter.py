from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from backend.app.cognition import (
    CognitionService,
    FailureCode,
    ImmutableDecisionCache,
    ModelGatewayError,
    ModelPolicy,
    ModelRequest,
    ModelResult,
    ModelUsage,
    ResultEvidenceTool,
    ResultInterpretationAnswer,
    ResultToolPlan,
)
from backend.app.cognition.gateway import validateEvidenceReferences
from backend.app.cognition.result_interpreter import (
    DEFAULT_RESULT_TOOLS,
    INITIAL_RESULT_TOOLS,
    MAX_TOOL_CONTEXT_BYTES,
    buildResultIndex,
    executeResultTools,
    toolResultsPayload,
)
from backend.app.cognition.result_semantics import SemanticViolationCode
from backend.app.cognition.streaming import ModelStreamProgress, ModelStreamStage
from backend.app.schemas import ResultInterpretationChatRequest

SESSION_ID = "result-interpreter-session-001"
API_KEY = "result-interpreter-test-key"


def sampleResult() -> dict[str, object]:
    return {
        "experimentId": "exp-result-001",
        "question": "How does lower liquidity capacity change market stress?",
        "questionZh": "更低的流动性容量如何改变市场压力？",
        "scenarioDiff": {
            "parameter": "marketMakerCapacity",
            "baselineValue": 1.0,
            "interventionValue": 0.65,
        },
        "metricSummaries": {
            "maxSpreadBps": {
                "delta": {
                    "median": 1.5,
                    "validN": 10,
                    "interval95": {"lower": -0.2, "upper": 3.1},
                }
            },
            "maxDrawdownPct": {"delta": {"median": 0.4, "validN": 10}},
        },
        "pairedRuns": [
            {
                "seed": index,
                "delta": {"maxSpreadBps": float(index), "maxDrawdownPct": index / 10},
            }
            for index in range(10)
        ],
        "medianPaths": {
            "step": list(range(120)),
            "baseline": {
                "price": [100 + index for index in range(120)],
                "spreadBps": [2 + index / 10 for index in range(120)],
            },
            "intervention": {
                "price": [100 - index for index in range(120)],
                "spreadBps": [3 + index / 10 for index in range(120)],
            },
            "delta": {
                "price": [-2 * index for index in range(120)],
                "spreadBps": [1.0 for _index in range(120)],
            },
        },
        "traces": [
            {
                "traceId": f"trace-{index}",
                "parentTraceId": f"trace-{index - 1}" if index else None,
                "step": index,
                "eventType": "ORDER_ARRIVED",
                "agentId": "agent-1",
                "summary": "Order arrived.",
                "summaryZh": "订单到达。",
                "payload": {"side": "SELL", "quantity": index + 1},
            }
            for index in range(100)
        ],
        "agentFlows": {
            "retail": {
                "baseline": {"netVolume": 2},
                "intervention": {"netVolume": 6},
            }
        },
        "agentPnl": {
            "retail": {
                "equityChangeCents": {
                    "baseline": {"median": 50},
                    "intervention": {"median": 0},
                    "delta": {"median": -50, "validN": 10},
                }
            }
        },
        "runSummaries": {"networkMetrics": {"reach": {"delta": {"median": 0.1}}}},
        "cognition": {
            "resolvedMode": "HYBRID_LLM",
            "provider": "zhipu",
            "resolvedModel": "glm-5.2",
            "calls": 2,
            "decisions": [
                {
                    "agentId": f"agent-{index}",
                    "direction": "NEGATIVE",
                    "decisionSummary": "A bounded simulated preference.",
                }
                for index in range(25)
            ],
        },
        "analysisDiagnostics": {
            "preregisteredPrimaryOutcome": "maxSpreadBps",
            "outcomeFamily": ["maxSpreadBps", "maxDrawdownPct"],
            "negativeControl": {"status": "COMPLETED", "passed": True},
        },
        "stoppingRule": {"reason": "FIXED_PAIR_COUNT_REACHED", "validPairs": 10},
        "limitations": ["Synthetic scenario analysis only."],
        "limitationsZh": ["仅用于合成情景分析。"],
        "manifest": {"engineVersion": "test-v1", "validPairedSeeds": 10},
        "eventPackManifest": {
            "id": "event-pack-test",
            "sources": [
                {
                    "sourceId": "source-1",
                    "title": "Official source",
                    "rawText": "SECRET RAW SOURCE BODY MUST NOT REACH THE MODEL",
                }
            ],
            "claims": [{"claimId": "claim-1", "text": "Approved claim."}],
        },
    }


def answerWithReferences(
    references: tuple[str, ...], *, includeSummary: bool
) -> ResultInterpretationAnswer:
    citations = " ".join(f"[{reference}]" for reference in references)
    return ResultInterpretationAnswer(
        answer=(
            f"The result is conditional scenario evidence, not a forecast or investment "
            f"advice. {citations}"
        ),
        analysis_summary=(
            "Checked the paired design, result boundary, and selected evidence slices."
            if includeSummary
            else None
        ),
        grounding_references=references,
        follow_up_suggestions=("Which interval matters most?",),
    )


def metricAnswer(statement: str) -> ResultInterpretationAnswer:
    return ResultInterpretationAnswer(
        answer=f"{statement} [result:metric-summary]",
        grounding_references=("result:metric-summary",),
        follow_up_suggestions=("Which limitation matters most?",),
    )


def validPrimaryAnswer(
    references: tuple[str, ...],
    *,
    includeSummary: bool,
    language: str = "en",
) -> ResultInterpretationAnswer:
    citations = " ".join(f"[{reference}]" for reference in references)
    if language == "zh-CN":
        answer = (
            f"maxSpreadBps 的配对中位变化上升 1.5，95% 区间为 [-0.2, 3.1]，且跨过零。{citations}"
        )
    else:
        answer = (
            "The maxSpreadBps paired median increased by 1.5, and its 95% interval "
            f"[-0.2, 3.1] crosses zero. {citations}"
        )
    return ResultInterpretationAnswer(
        answer=answer,
        analysis_summary=(
            "Checked the paired design, result boundary, and selected evidence slices."
            if includeSummary
            else None
        ),
        grounding_references=references,
        follow_up_suggestions=("Which limitation matters most?",),
    )


@dataclass(frozen=True, slots=True)
class FakeOutcome:
    data: BaseModel | ModelGatewayError
    cacheHit: bool = False
    repairUsed: bool = False


class FakeGateway:
    def __init__(self, outcome: FakeOutcome, harness: GatewayHarness) -> None:
        self.outcome = outcome
        self.harness = harness
        self.closed = False

    async def generateStructured[ModelT: BaseModel](
        self,
        request: ModelRequest,
        schema: type[ModelT],
        policy: ModelPolicy,
    ) -> ModelResult[ModelT]:
        self.harness.requests.append(request)
        self.harness.schemas.append(schema)
        self.harness.policies.append(policy)
        if isinstance(self.outcome.data, ModelGatewayError):
            raise self.outcome.data
        if not isinstance(self.outcome.data, schema):
            raise AssertionError("fake outcome does not match the requested schema")
        return ModelResult(
            data=self.outcome.data,
            provider=request.provider,
            model=request.model,
            requestId=request.requestId,
            promptHash=request.promptHash,
            responseHash="a" * 64,
            cacheKey="b" * 64,
            usage=ModelUsage(promptTokens=100, completionTokens=50, cachedTokens=10),
            latencyMs=5.0,
            transportAttempts=0 if self.outcome.cacheHit else 1,
            repairUsed=self.outcome.repairUsed,
            fallbackUsed=False,
            cacheHit=self.outcome.cacheHit,
        )  # type: ignore[arg-type,return-value]

    async def aclose(self) -> None:
        self.closed = True


class GatewayHarness:
    def __init__(self, outcomes: Sequence[FakeOutcome]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[ModelRequest] = []
        self.schemas: list[type[BaseModel]] = []
        self.policies: list[ModelPolicy] = []
        self.gateways: list[FakeGateway] = []
        self.caches: list[ImmutableDecisionCache | None] = []

    def __call__(self, cache: ImmutableDecisionCache | None) -> FakeGateway:
        self.caches.append(cache)
        gateway = FakeGateway(self.outcomes.pop(0), self)
        self.gateways.append(gateway)
        return gateway


def configuredService(
    outcomes: Sequence[FakeOutcome],
    *,
    thinkingEnabled: bool = False,
) -> tuple[CognitionService, GatewayHarness]:
    harness = GatewayHarness(outcomes)
    service = CognitionService(gatewayFactory=harness)
    service.setConfig(
        sessionId=SESSION_ID,
        apiKey=API_KEY,
        provider="zhipu",
        model="glm-5.2",
        thinkingEnabled=thinkingEnabled,
        maxTokens=4_096,
    )
    return service, harness


def test_result_tools_cover_every_output_family_without_raw_source_text() -> None:
    toolResults = executeResultTools(sampleResult(), DEFAULT_RESULT_TOOLS)
    serialized = json.dumps(toolResultsPayload(toolResults), ensure_ascii=False)

    assert {result.tool for result in toolResults} == set(ResultEvidenceTool)
    assert len({result.evidence_id for result in toolResults}) == len(ResultEvidenceTool)
    assert "SECRET RAW SOURCE BODY" not in serialized
    pathResult = next(
        result for result in toolResults if result.tool is ResultEvidenceTool.PATH_SERIES
    )
    assert pathResult.truncated is True
    assert pathResult.item_count == 120
    assert len(pathResult.payload["series"]["step"]) == 60
    assert len(pathResult.payload["series"]["baseline"]["price"]) == 60
    assert (
        next(result for result in toolResults if result.tool is ResultEvidenceTool.TRACE).item_count
        == 100
    )
    tracePayload = next(
        result for result in toolResults if result.tool is ResultEvidenceTool.TRACE
    ).payload
    assert any(node.get("parentTraceId") for node in tracePayload["nodes"])
    assert all(node.get("summaryZh") == "订单到达。" for node in tracePayload["nodes"])
    assert all("quantity" in node["payload"] for node in tracePayload["nodes"])
    agentPayload = next(
        result for result in toolResults if result.tool is ResultEvidenceTool.AGENT_OUTCOMES
    ).payload
    assert agentPayload["agentFlows"]["retail"]["intervention"]["netVolume"] == 6
    assert "networkMetrics" in agentPayload["runSummaries"]
    assert (
        next(
            result
            for result in toolResults
            if result.tool is ResultEvidenceTool.COGNITION_DECISIONS
        ).truncated
        is True
    )


def test_result_index_counts_mapping_agent_sections() -> None:
    resultIndex = buildResultIndex(sampleResult())

    assert resultIndex["agentFlowCount"] == 1
    assert resultIndex["agentPnlCount"] == 1


def test_paired_delta_tool_discloses_omitted_metrics() -> None:
    result = sampleResult()
    result["metricSummaries"] = {
        f"metric-{index:02d}": {"delta": {"median": index}} for index in range(22)
    }
    result["analysisDiagnostics"] = {
        "preregisteredPrimaryOutcome": "metric-00",
        "outcomeFamily": ["metric-00", "metric-01"],
    }

    pairedResult = executeResultTools(
        result,
        (ResultEvidenceTool.PAIRED_DELTAS,),
    )[0]

    assert pairedResult.truncated is True
    assert pairedResult.payload["totalMetricCount"] == 22
    assert pairedResult.payload["includedMetricCount"] == 16
    assert len(pairedResult.payload["omittedMetricIds"]) == 6


def test_all_tools_remain_within_aggregate_context_limit_for_large_result() -> None:
    result = sampleResult()
    longText = "结构化结果字段" * 2_000
    result["metricSummaries"] = {
        f"metric-{index:02d}": {"delta": {"median": index, "diagnostic": longText}}
        for index in range(24)
    }
    result["limitations"] = [longText for _index in range(30)]
    result["eventPackManifest"] = {
        "id": "event-pack-large",
        "sources": [{"sourceId": f"source-{index}", "title": longText} for index in range(20)],
        "claims": [{"claimId": f"claim-{index}", "text": longText} for index in range(30)],
    }

    toolResults = executeResultTools(result, DEFAULT_RESULT_TOOLS)
    serialized = json.dumps(
        toolResultsPayload(toolResults),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert len(serialized) <= MAX_TOOL_CONTEXT_BYTES
    assert any(item.truncated for item in toolResults)


def test_initial_interpretation_uses_bounded_summary_tools_and_one_model_call() -> None:
    references = ("result:overview", "result:metric-summary", "result:limitations")
    service, harness = configuredService(
        [FakeOutcome(validPrimaryAnswer(references, includeSummary=True))]
    )

    run = asyncio.run(
        service.interpretExperimentResult(
            sessionId=SESSION_ID,
            result=sampleResult(),
            messages=({"role": "user", "content": "Explain this result simply."},),
            language="en",
            initial=True,
            includeAnalysisSummary=True,
        )
    )

    assert run.model_calls == 1
    assert run.planner_used is False
    assert run.usage.totalTokens == 150
    assert {activity.tool for activity in run.tool_activity} == set(INITIAL_RESULT_TOOLS)
    assert harness.schemas == [ResultInterpretationAnswer]
    assert harness.requests[0].allowedEvidenceIds == {
        f"result:{tool.value.lower().replace('_', '-')}" for tool in INITIAL_RESULT_TOOLS
    }
    assert "SECRET RAW SOURCE BODY" not in harness.requests[0].userContent
    assert all(gateway.closed for gateway in harness.gateways)
    assert all(not policy.allow_rule_fallback for policy in harness.policies)
    assert all(policy.timeout_seconds == 120 for policy in harness.policies)
    assert all(policy.max_transport_attempts == 1 for policy in harness.policies)
    assert harness.caches == [None]
    assert harness.requests[0].samplingConfig.max_tokens == 4_096
    assert run.semantic_validation_status == "PASSED"
    assert run.deterministic_fallback_used is False
    assert run.semantic_violation_codes == ()


def test_semantic_heuristic_mismatch_keeps_the_model_answer_without_repair() -> None:
    answer = metricAnswer("The maxSpreadBps paired median decreased by 1.5.")
    service, harness = configuredService([FakeOutcome(answer)])

    run = asyncio.run(
        service.interpretExperimentResult(
            sessionId=SESSION_ID,
            result=sampleResult(),
            messages=({"role": "user", "content": "Explain the primary result."},),
            language="en",
            initial=True,
            includeAnalysisSummary=False,
        )
    )

    assert run.interpretation.answer.endswith(answer.answer)
    assert run.semantic_validation_status == "COMPLETED_WITH_WARNINGS"
    assert run.deterministic_fallback_used is False
    assert run.semantic_violation_codes == (SemanticViolationCode.DIRECTION_MISMATCH.value,)
    assert run.repair_used is False
    assert run.model_calls == 1
    assert run.usage.totalTokens == 150
    assert harness.schemas == [ResultInterpretationAnswer]


def test_semantic_heuristics_never_replace_a_model_answer_with_server_fallback() -> None:
    answer = metricAnswer("The maxSpreadBps paired median decreased by 1.5.")
    service, harness = configuredService([FakeOutcome(answer)])

    run = asyncio.run(
        service.interpretExperimentResult(
            sessionId=SESSION_ID,
            result=sampleResult(),
            messages=({"role": "user", "content": "Explain the primary result."},),
            language="en",
            initial=True,
            includeAnalysisSummary=True,
        )
    )

    assert run.semantic_validation_status == "COMPLETED_WITH_WARNINGS"
    assert run.deterministic_fallback_used is False
    assert run.interpretation.answer.endswith(answer.answer)
    assert SemanticViolationCode.DIRECTION_MISMATCH.value in run.semantic_violation_codes
    assert len(harness.requests) == 1


def test_semantic_warning_does_not_dispatch_a_second_provider_request() -> None:
    answer = metricAnswer("The maxSpreadBps paired median decreased by 1.5.")
    service, harness = configuredService(
        [
            FakeOutcome(answer),
            FakeOutcome(
                ModelGatewayError(
                    FailureCode.MODEL_TIMEOUT,
                    "semantic repair timed out",
                    retryable=True,
                    attempts=1,
                    uncertainBillableAttempts=1,
                )
            ),
        ]
    )

    run = asyncio.run(
        service.interpretExperimentResult(
            sessionId=SESSION_ID,
            result=sampleResult(),
            messages=({"role": "user", "content": "Explain the primary result."},),
            language="en",
            initial=True,
            includeAnalysisSummary=False,
        )
    )

    assert run.semantic_validation_status == "COMPLETED_WITH_WARNINGS"
    assert run.deterministic_fallback_used is False
    assert run.repair_used is False
    assert FailureCode.MODEL_TIMEOUT.value not in run.failure_codes
    assert len(harness.requests) == 1


def test_advisory_semantic_findings_do_not_hide_a_usable_model_answer() -> None:
    answer = metricAnswer(
        "The maxSpreadBps paired median increased by 1.5 across 42 reported observations."
    )
    service, harness = configuredService([FakeOutcome(answer)])

    run = asyncio.run(
        service.interpretExperimentResult(
            sessionId=SESSION_ID,
            result=sampleResult(),
            messages=({"role": "user", "content": "Explain the primary result."},),
            language="en",
            initial=True,
            includeAnalysisSummary=False,
        )
    )

    assert run.semantic_validation_status == "COMPLETED_WITH_WARNINGS"
    assert run.deterministic_fallback_used is False
    assert run.interpretation.answer.endswith(answer.answer)
    assert SemanticViolationCode.METRIC_NUMBER_UNSUPPORTED.value in run.semantic_violation_codes
    assert len(harness.requests) == 1


def test_follow_up_plans_tools_and_keeps_mandatory_boundary_slices() -> None:
    plan = ResultToolPlan(
        tools=(ResultEvidenceTool.METRIC_SUMMARY, ResultEvidenceTool.PAIRED_DELTAS),
        plan_summary="Read aggregate and paired differences.",
    )
    references = (
        "result:overview",
        "result:limitations",
        "result:metric-summary",
        "result:paired-deltas",
    )
    service, harness = configuredService(
        [FakeOutcome(plan), FakeOutcome(answerWithReferences(references, includeSummary=False))],
        thinkingEnabled=True,
    )

    run = asyncio.run(
        service.interpretExperimentResult(
            sessionId=SESSION_ID,
            result=sampleResult(),
            messages=(
                {"role": "user", "content": "Explain this result."},
                {"role": "assistant", "content": "A previous bounded explanation."},
                {"role": "user", "content": "Why does the interval cross zero?"},
            ),
            language="en",
            initial=False,
            includeAnalysisSummary=False,
        )
    )

    assert run.model_calls == 2
    assert run.planner_used is True
    assert run.usage.totalTokens == 300
    assert harness.schemas == [ResultToolPlan, ResultInterpretationAnswer]
    assert {activity.tool for activity in run.tool_activity} == {
        ResultEvidenceTool.OVERVIEW,
        ResultEvidenceTool.LIMITATIONS,
        ResultEvidenceTool.METRIC_SUMMARY,
        ResultEvidenceTool.PAIRED_DELTAS,
    }
    assert "result_tool_outputs" not in harness.requests[0].userContent
    assert "result_tool_outputs" in harness.requests[1].userContent
    assert harness.caches == [None, None]
    assert [request.samplingConfig.max_tokens for request in harness.requests] == [
        1_024,
        4_096,
    ]
    assert [request.samplingConfig.thinking_enabled for request in harness.requests] == [
        False,
        False,
    ]
    assert run.thinking_preference_enabled is True
    assert run.thinking_enabled is False


def test_follow_up_planner_failure_falls_back_to_all_bounded_tools() -> None:
    references = ("result:overview", "result:limitations")
    service, harness = configuredService(
        [
            FakeOutcome(
                ModelGatewayError(
                    FailureCode.MODEL_TIMEOUT,
                    "planner timed out with internal provider detail",
                    retryable=True,
                    attempts=1,
                    uncertainBillableAttempts=1,
                )
            ),
            FakeOutcome(answerWithReferences(references, includeSummary=False)),
        ]
    )
    progressEvents: list[ModelStreamProgress] = []

    async def observeProgress(progress: ModelStreamProgress) -> None:
        progressEvents.append(progress)

    run = asyncio.run(
        service.interpretExperimentResult(
            sessionId=SESSION_ID,
            result=sampleResult(),
            messages=({"role": "user", "content": "Why did the interval widen?"},),
            language="en",
            initial=False,
            includeAnalysisSummary=False,
            progressObserver=observeProgress,
        )
    )

    assert run.planner_used is True
    assert run.planner_fallback_used is True
    assert run.transport_attempts == 2
    assert run.uncertain_billable_attempts == 1
    assert run.failure_codes == (FailureCode.MODEL_TIMEOUT.value,)
    assert {activity.tool for activity in run.tool_activity} == set(ResultEvidenceTool)
    assert harness.policies[0].timeout_seconds == 25
    assert harness.policies[1].timeout_seconds == 120
    assert [event.stage for event in progressEvents] == [
        ModelStreamStage.PREPARING,
        ModelStreamStage.PLANNING,
        ModelStreamStage.READING_RESULTS,
        ModelStreamStage.GENERATING,
        ModelStreamStage.COMPLETED,
    ]


def test_requested_reviewable_summary_has_safe_deterministic_fallback() -> None:
    references = ("result:overview",)
    service, _harness = configuredService(
        [FakeOutcome(validPrimaryAnswer(references, includeSummary=False, language="zh-CN"))]
    )

    run = asyncio.run(
        service.interpretExperimentResult(
            sessionId=SESSION_ID,
            result=sampleResult(),
            messages=({"role": "user", "content": "请解释结果。"},),
            language="zh-CN",
            initial=True,
            includeAnalysisSummary=True,
        )
    )

    assert run.interpretation.analysis_summary == (
        "未返回可核验的分析摘要；正文仍仅依据所列实验结果证据切片。"
    )
    assert run.interpretation.answer.startswith(
        "这是以合成假设为条件的情景分析，不是预测，也不构成投资建议。"
    )


def test_interpretation_rejects_unknown_grounding_reference() -> None:
    answer = answerWithReferences(("result:not-a-real-tool",), includeSummary=False)
    service, _harness = configuredService([FakeOutcome(answer)])

    run = asyncio.run(
        service.interpretExperimentResult(
            sessionId=SESSION_ID,
            result=sampleResult(),
            messages=({"role": "user", "content": "Explain this result."},),
            language="en",
            initial=True,
            includeAnalysisSummary=False,
        )
    )

    assert run.semantic_validation_status == "DETERMINISTIC_FALLBACK"
    assert run.deterministic_fallback_used is True
    assert FailureCode.EVIDENCE_ID_UNKNOWN.value in run.failure_codes
    assert "result:not-a-real-tool" not in run.interpretation.evidenceIds()


def test_interpretation_answer_collects_unlisted_inline_reference_for_gateway_validation() -> None:
    answer = ResultInterpretationAnswer(
        answer=(
            "This is scenario evidence, not a forecast or investment advice. [result:overview]"
        ),
        analysis_summary="An invented slice was also checked. [result:not-supplied]",
        grounding_references=("result:overview",),
    )

    assert answer.grounding_references == ("result:overview", "result:not-supplied")
    assert answer.evidenceIds() == {"result:overview", "result:not-supplied"}


def test_interpretation_answer_normalizes_duplicate_and_uncited_legal_references() -> None:
    answer = ResultInterpretationAnswer(
        answer=(
            "The paired result changed under the scenario. [result:overview] "
            "The interval remains uncertain. [result:paired-deltas]"
        ),
        analysis_summary="Checked the study limitations. [result:limitations]",
        grounding_references=(
            "result:overview",
            "result:overview",
            "result:metric-summary",
            "result:paired-deltas",
            "result:limitations",
        ),
    )

    assert answer.grounding_references == (
        "result:overview",
        "result:paired-deltas",
        "result:limitations",
    )
    assert answer.model_dump()["grounding_references"] == (
        "result:overview",
        "result:paired-deltas",
        "result:limitations",
    )
    assert "_reported_grounding_references" not in answer.model_dump()
    # 网关仍能看到被规范化清理的原始 ID，以便执行请求级 allowlist 检查。
    assert answer.evidenceIds() == {
        "result:overview",
        "result:metric-summary",
        "result:paired-deltas",
        "result:limitations",
    }


def test_interpretation_answer_auto_indexes_inline_references() -> None:
    answer = ResultInterpretationAnswer(
        answer=(
            "The overview and paired delta were checked. [result:overview] [result:paired-deltas]"
        ),
        grounding_references=("result:overview",),
    )

    assert answer.grounding_references == ("result:overview", "result:paired-deltas")


def test_interpretation_answer_does_not_hide_uncited_unknown_reference() -> None:
    answer = ResultInterpretationAnswer(
        answer="This is bounded scenario evidence. [result:overview]",
        grounding_references=("result:overview", "result:not-supplied"),
    )

    assert answer.grounding_references == ("result:overview",)
    with pytest.raises(ModelGatewayError) as error:
        validateEvidenceReferences(answer, frozenset({"result:overview"}))

    assert error.value.code is FailureCode.EVIDENCE_ID_UNKNOWN


def test_interpretation_answer_rejects_invalid_uncited_reference_before_cleanup() -> None:
    with pytest.raises(ValueError, match="invalid evidence ID"):
        ResultInterpretationAnswer(
            answer="This is bounded scenario evidence. [result:overview]",
            grounding_references=("result:overview", "result:invalid reference"),
        )


def test_interpretation_allows_conditional_buy_discussion_with_disclaimer() -> None:
    answer = ResultInterpretationAnswer(
        answer=(
            "Under this scenario, the evidence supports higher liquidity risk, so I would "
            "not use this experiment alone as a reason to buy. This does not constitute "
            "investment advice. [result:overview]"
        ),
        grounding_references=("result:overview",),
    )

    assert "reason to buy" in answer.answer
    assert answer.investment_advice_provided is False


def test_interpretation_normalizes_recoverable_provider_shape() -> None:
    answer = ResultInterpretationAnswer.model_validate(
        {
            "schemaVersion": "unexpected-but-recoverable",
            "answer": "Bounded scenario explanation. [result:overview]",
            "analysisSummary": "",
            "groundingReferences": [],
            "followUpSuggestions": [
                f"{'x' * 401} [result:overview]",
                "",
                "What is uncertain?",
                "A fourth suggestion is ignored.",
            ],
            "scenarioNotForecast": False,
            "investmentAdviceProvided": True,
            "harmlessExtraField": "ignored",
        }
    )

    assert answer.schema_version == "result_interpretation_v1.0.0"
    assert answer.analysis_summary is None
    assert answer.grounding_references == ("result:overview",)
    assert answer.follow_up_suggestions == (
        "x" * 400,
        "What is uncertain?",
        "A fourth suggestion is ignored.",
    )
    assert answer.scenario_not_forecast is True
    assert answer.investment_advice_provided is False


@pytest.mark.parametrize(
    "suggestion",
    (
        "Can you explain the interval [result:metric-summary]?",
        "Review this historical marker [result:legacy.v2:detail].",
        "What does the empty marker [result:] mean?",
    ),
)
def test_interpretation_strips_result_references_from_follow_up_suggestions(
    suggestion: str,
) -> None:
    answer = ResultInterpretationAnswer(
        answer="Bounded scenario explanation. [result:overview]",
        grounding_references=("result:overview",),
        follow_up_suggestions=(suggestion,),
    )

    assert answer.follow_up_suggestions
    assert "[result:" not in answer.follow_up_suggestions[0]


def test_public_chat_request_requires_bounded_alternating_history() -> None:
    request = ResultInterpretationChatRequest.model_validate(
        {
            "conversationId": "conversation-001",
            "clientRequestId": "request-001",
            "mode": "FOLLOW_UP",
            "language": "zh-CN",
            "reasoningSummaryRequested": True,
            "messages": [
                {"role": "user", "content": "先解释结果。"},
                {"role": "assistant", "content": "这是情景分析。"},
                {"role": "user", "content": "区间跨零是什么意思？"},
            ],
        }
    )
    assert request.messages[-1].role == "user"

    with pytest.raises(ValueError, match="alternate"):
        ResultInterpretationChatRequest.model_validate(
            {
                "conversationId": "conversation-002",
                "clientRequestId": "request-002",
                "mode": "FOLLOW_UP",
                "language": "en",
                "messages": [
                    {"role": "user", "content": "one"},
                    {"role": "user", "content": "two"},
                    {"role": "user", "content": "three"},
                ],
            }
        )
