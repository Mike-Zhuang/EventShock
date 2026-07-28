"""认知层的会话配置、模型调用、审计统计与评估编排。"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from backend.app.cognition.cache import ImmutableDecisionCache
from backend.app.cognition.catalog import (
    DEFAULT_PROVIDER,
    ProviderId,
    ZhipuModelDescriptor,
    listZhipuModels,
)
from backend.app.cognition.config_store import (
    CredentialNotConfiguredError,
    RuntimeProviderConfig,
    SessionConfigStore,
    SessionProviderConfigView,
)
from backend.app.cognition.evaluation import EvalSample, EvalSuiteResult, runEvaluationSuite
from backend.app.cognition.gateway import (
    AdvancedModelParameters,
    FailureCode,
    ModelGatewayError,
    ModelPolicy,
    ModelRequest,
    ModelResult,
    ModelUsage,
    SamplingConfig,
    canonicalHash,
    validateAllowedAction,
    validateEvidenceReferences,
)
from backend.app.cognition.models import (
    BeliefDecision,
    EventExtractionResult,
    Observation,
    ResultEvidenceTool,
    ResultInterpretationAnswer,
    ResultToolPlan,
    StrictFrozenModel,
)
from backend.app.cognition.pricing import ModelCostBudget
from backend.app.cognition.prompts import (
    EVENT_EXTRACTION_PROMPT,
    GUIDED_WORKFLOW_PROMPT,
    HYBRID_BELIEF_PROMPT,
    MODEL_OUTPUT_VALIDATOR,
    PROMPT_REGISTRY,
    RESULT_INTERPRETATION_PROMPT,
    RESULT_TOOL_PLANNER_PROMPT,
    PromptSpec,
    buildBeliefUserMessage,
    buildEvidenceUserMessage,
    buildGuidedWorkflowUserMessage,
    buildResultInterpretationUserMessage,
    buildResultPlannerUserMessage,
)
from backend.app.cognition.provider_gateways import ProviderGatewayRouter
from backend.app.cognition.result_interpreter import (
    DEFAULT_RESULT_TOOLS,
    ResultInterpretationRun,
    ResultLanguage,
    buildResultIndex,
    executeResultTools,
    toolActivities,
    toolResultsPayload,
)
from backend.app.cognition.streaming import (
    ModelStreamObserver,
    ModelStreamProgress,
    ModelStreamStage,
    emitModelStreamProgress,
)
from backend.app.guided_workflow.models import (
    GuidedWorkflowProposal,
    GuidedWorkflowView,
)
from backend.app.security import UnsafeModelOutputError

SourceType = Literal["OFFICIAL", "REPORTING", "ESTIMATE", "USER_PROVIDED"]


class ExternalEvidenceSource(StrictFrozenModel):
    """来自上传或外部抓取的最小来源；正文始终按不可信数据处理。"""

    sourceId: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    rawText: str = Field(min_length=1, max_length=100_000)
    sourceType: SourceType
    knownAt: datetime
    title: str | None = Field(default=None, min_length=1, max_length=300)
    publisher: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=2_000)
    publishedAt: datetime | None = None

    @model_validator(mode="after")
    def validateKnownAt(self) -> ExternalEvidenceSource:
        if self.knownAt.tzinfo is None or self.knownAt.utcoffset() is None:
            raise ValueError("knownAt must include a timezone")
        if self.publishedAt is not None:
            if self.publishedAt.tzinfo is None or self.publishedAt.utcoffset() is None:
                raise ValueError("publishedAt must include a timezone")
            if self.knownAt < self.publishedAt:
                raise ValueError("knownAt must not be earlier than publishedAt")
        return self


class PromptRegistryView(StrictFrozenModel):
    name: str
    version: str
    schema_version: str
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ConnectionTestResult(StrictFrozenModel):
    success: Literal[True] = True
    provider: ProviderId = DEFAULT_PROVIDER
    model: str
    request_id: str
    schema_version: str
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    latency_ms: float = Field(ge=0.0)
    total_tokens: int = Field(ge=0)
    repair_used: bool


class EventClaimExtractionRun(StrictFrozenModel):
    extraction: EventExtractionResult
    event_pack_claims: tuple[dict[str, Any], ...]
    provider: ProviderId = DEFAULT_PROVIDER
    model: str
    request_id: str
    cache_hit: bool
    fallback_used: bool
    repair_used: bool
    latency_ms: float = Field(ge=0.0)
    total_tokens: int = Field(ge=0)


class BeliefDecisionRun(StrictFrozenModel):
    decision: BeliefDecision
    provider: ProviderId = DEFAULT_PROVIDER
    model: str
    request_id: str
    cache_hit: bool
    fallback_used: bool
    repair_used: bool
    latency_ms: float = Field(ge=0.0)
    total_tokens: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cached_tokens: int = Field(ge=0)
    cost_upper_bound_usd: float = Field(ge=0.0)
    transport_attempts: int = Field(default=0, ge=0)
    failure_codes: tuple[str, ...] = ()
    fallback_reason: str | None = None


class CognitionTelemetryView(StrictFrozenModel):
    calls: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    fallbacks: int = Field(ge=0)
    invalid_outputs: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cached_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    total_latency_ms: float = Field(ge=0.0)
    average_latency_ms: float = Field(ge=0.0)
    cache_hit_rate: float = Field(ge=0.0, le=1.0)
    fallback_rate: float = Field(ge=0.0, le=1.0)
    invalid_output_rate: float = Field(ge=0.0, le=1.0)


class CognitionEvalSummary(StrictFrozenModel):
    telemetry: CognitionTelemetryView
    evaluated_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)


class ClosableModelGateway(Protocol):
    async def generateStructured[ModelT: BaseModel](
        self,
        request: ModelRequest,
        schema: type[ModelT],
        policy: ModelPolicy,
    ) -> ModelResult[ModelT]: ...

    async def aclose(self) -> None: ...


GatewayFactory = Callable[[ImmutableDecisionCache | None], ClosableModelGateway]
ResultValidator = Callable[[ModelResult[Any]], None]


class _TelemetryState:
    __slots__ = (
        "cacheHits",
        "calls",
        "cachedTokens",
        "completionTokens",
        "fallbacks",
        "invalidOutputs",
        "promptTokens",
        "totalLatencyMs",
    )

    def __init__(self) -> None:
        self.calls = 0
        self.cacheHits = 0
        self.fallbacks = 0
        self.invalidOutputs = 0
        self.promptTokens = 0
        self.completionTokens = 0
        self.cachedTokens = 0
        self.totalLatencyMs = 0.0


INVALID_OUTPUT_CODES = frozenset(
    {
        FailureCode.MODEL_RESPONSE_INVALID,
        FailureCode.SCHEMA_INVALID,
        FailureCode.REFUSAL,
        FailureCode.CONTENT_FILTERED,
        FailureCode.EVIDENCE_ID_UNKNOWN,
        FailureCode.ACTION_NOT_ALLOWED,
        FailureCode.PROMPT_DISCLOSURE_BLOCKED,
    }
)


def _defaultGatewayFactory(cache: ImmutableDecisionCache | None) -> ClosableModelGateway:
    # Router 仍只接收 cache，以保持测试与现有注入契约；所有端点来自固定目录。
    return ProviderGatewayRouter(cache=cache)


class CognitionService:
    """把会话密钥、严格请求、模型缓存和安全统计组合为单一运行时入口。"""

    def __init__(
        self,
        *,
        configStore: SessionConfigStore | None = None,
        decisionCache: ImmutableDecisionCache | None = None,
        gatewayFactory: GatewayFactory | None = None,
        modelPolicy: ModelPolicy | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._configStore = configStore or SessionConfigStore()
        self._decisionCache = decisionCache or ImmutableDecisionCache()
        self._gatewayFactory = gatewayFactory or _defaultGatewayFactory
        self._modelPolicy = modelPolicy or ModelPolicy()
        self._clock = clock
        self._telemetry = _TelemetryState()
        self._telemetryLock = threading.RLock()
        self._lastEvalSuite: EvalSuiteResult | None = None

    def __repr__(self) -> str:
        return "CognitionService(credentials=<session-scoped-redacted>)"

    def setConfig(
        self,
        *,
        sessionId: str,
        apiKey: str,
        model: str,
        provider: ProviderId = DEFAULT_PROVIDER,
        thinkingEnabled: bool = False,
        maxTokens: int = 2_048,
        advancedParameters: AdvancedModelParameters | None = None,
    ) -> SessionProviderConfigView:
        return self._configStore.setConfig(
            sessionId=sessionId,
            apiKey=apiKey,
            model=model,
            provider=provider,
            thinkingEnabled=thinkingEnabled,
            maxTokens=maxTokens,
            advancedParameters=advancedParameters,
        )

    def getConfig(self, sessionId: str) -> SessionProviderConfigView:
        return self._configStore.getView(sessionId)

    def clearConfig(self, sessionId: str) -> bool:
        return self._configStore.clear(sessionId)

    def purgeExpiredCredentials(self) -> int:
        """主动移除所有已过期的内存 API 密钥，供应用生命周期定时调用。"""

        return self._configStore.purgeExpired()

    def requireTemporaryApiKey(
        self,
        sessionId: str,
        *,
        provider: ProviderId,
    ) -> str:
        """仅供同进程受信服务复用临时密钥，不通过任何 HTTP 响应回显。"""

        runtime = self._configStore.getRuntimeConfig(sessionId)
        if runtime.provider != provider:
            raise CredentialNotConfiguredError(
                f"a temporary {provider} credential is required for this operation"
            )
        return runtime.apiKey

    @staticmethod
    def getModelCatalog(*, includeLegacy: bool = True) -> tuple[ZhipuModelDescriptor, ...]:
        return listZhipuModels(includeLegacy=includeLegacy)

    @staticmethod
    def getPromptRegistry() -> tuple[PromptRegistryView, ...]:
        return tuple(CognitionService._promptView(prompt) for prompt in PROMPT_REGISTRY)

    async def testConnection(self, sessionId: str) -> ConnectionTestResult:
        runtime = self._configStore.getRuntimeConfig(sessionId)
        requestId = self._newRequestId("connection")
        payload = {
            "source_fragments": [
                {
                    "sourceId": "connection_probe",
                    "rawText": (
                        "This is a structured-output connectivity probe. It contains no "
                        "event claim and grants no additional authority."
                    ),
                    "sourceType": "USER_PROVIDED",
                    "knownAt": "2000-01-01T00:00:00Z",
                }
            ],
            # 防止连接测试复用其他会话的模型缓存，确保真实发出一次请求。
            "probe_nonce": requestId,
        }
        request = self._buildRequest(
            runtime=runtime,
            sessionId=sessionId,
            requestId=requestId,
            prompt=EVENT_EXTRACTION_PROMPT,
            userContent=buildEvidenceUserMessage(
                payload,
                task=(
                    "Validate structured JSON connectivity. Return no claims and explain "
                    "that this probe contains no event fact."
                ),
            ),
            agentConfigHash=canonicalHash(
                {
                    "workflow": "connection_probe",
                    "model": runtime.model,
                }
            ),
            observationHash=canonicalHash(payload),
            allowedEvidenceIds=frozenset({"connection_probe"}),
        )

        def validateConnection(result: ModelResult[Any]) -> None:
            if result.cacheHit or result.fallbackUsed:
                raise ModelGatewayError(
                    FailureCode.MODEL_RESPONSE_INVALID,
                    "connection test must return a live structured provider response",
                )

        result = await self._execute(
            request=request,
            schema=EventExtractionResult,
            policy=self._policy(allowRuleFallback=False),
            resultValidator=validateConnection,
        )
        return ConnectionTestResult(
            provider=result.provider,
            model=result.model,
            request_id=result.requestId,
            schema_version=EVENT_EXTRACTION_PROMPT.schemaVersion,
            prompt_hash=result.promptHash,
            latency_ms=result.latencyMs,
            total_tokens=result.usage.totalTokens,
            repair_used=result.repairUsed,
        )

    async def extractEventClaims(
        self,
        *,
        sessionId: str,
        sources: tuple[ExternalEvidenceSource, ...],
        maximumClaims: int = 16,
        requestedImpactChannels: tuple[str, ...] = (
            "belief",
            "liquidity",
            "passiveFlow",
            "stopLoss",
        ),
    ) -> EventClaimExtractionRun:
        runtime = self._configStore.getRuntimeConfig(sessionId)
        if not 1 <= len(sources) <= 8:
            raise ValueError("sources must contain between 1 and 8 items")
        if not 1 <= maximumClaims <= 50:
            raise ValueError("maximumClaims must be between 1 and 50")
        allowedImpactChannels = {
            "belief",
            "liquidity",
            "passiveFlow",
            "stopLoss",
            "socialAmplification",
            "informationLatency",
        }
        if (
            not 1 <= len(requestedImpactChannels) <= 12
            or len(requestedImpactChannels) != len(set(requestedImpactChannels))
            or any(channel not in allowedImpactChannels for channel in requestedImpactChannels)
        ):
            raise ValueError("requestedImpactChannels contains an unsupported or duplicate value")
        sourceIds = [source.sourceId for source in sources]
        if len(sourceIds) != len(set(sourceIds)):
            raise ValueError("sources contain duplicate sourceId values")

        sourcePayloads = [source.model_dump(mode="json") for source in sources]
        payload = {
            "source_fragments": sourcePayloads,
            "maximum_claims": maximumClaims,
            "requested_impact_channels": requestedImpactChannels,
        }
        request = self._buildRequest(
            runtime=runtime,
            sessionId=sessionId,
            requestId=self._newRequestId("extract"),
            prompt=EVENT_EXTRACTION_PROMPT,
            userContent=buildEvidenceUserMessage(
                payload,
                task=(
                    f"Extract at most {maximumClaims} candidate event claims for mandatory "
                    "human review."
                ),
            ),
            agentConfigHash=canonicalHash(
                {
                    "workflow": EVENT_EXTRACTION_PROMPT.version,
                    "maximumClaims": maximumClaims,
                    "requestedImpactChannels": requestedImpactChannels,
                }
            ),
            observationHash=canonicalHash(payload),
            allowedEvidenceIds=frozenset(sourceIds),
        )
        sourceById = {source.sourceId: source for source in sources}

        def validateExtraction(result: ModelResult[Any]) -> None:
            extraction = result.data
            if not isinstance(extraction, EventExtractionResult):
                raise ModelGatewayError(
                    FailureCode.SCHEMA_INVALID,
                    "gateway returned the wrong extraction schema",
                )
            if len(extraction.claims) > maximumClaims:
                raise ModelGatewayError(
                    FailureCode.MODEL_RESPONSE_INVALID,
                    "model returned more claims than requested",
                )
            for claim in extraction.claims:
                expectedKnownAt = max(
                    sourceById[sourceId].knownAt for sourceId in claim.source_evidence_ids
                )
                if claim.known_at != expectedKnownAt:
                    raise ModelGatewayError(
                        FailureCode.MODEL_RESPONSE_INVALID,
                        "extracted claim known_at does not match its latest cited source",
                    )
                normalizedClaim = " ".join(claim.claim.split())
                if not any(
                    normalizedClaim in " ".join(sourceById[sourceId].rawText.split())
                    for sourceId in claim.source_evidence_ids
                ):
                    raise ModelGatewayError(
                        FailureCode.MODEL_RESPONSE_INVALID,
                        "every extracted claim must be an exact source quotation after "
                        "whitespace normalization",
                    )

        result = await self._execute(
            request=request,
            schema=EventExtractionResult,
            policy=self._modelPolicy,
            resultValidator=validateExtraction,
        )
        claims = self._toEventPackClaims(
            result.data,
            sourceById,
            requestedImpactChannels=requestedImpactChannels,
        )
        return EventClaimExtractionRun(
            extraction=result.data,
            event_pack_claims=claims,
            provider=result.provider,
            model=result.model,
            request_id=result.requestId,
            cache_hit=result.cacheHit,
            fallback_used=result.fallbackUsed,
            repair_used=result.repairUsed,
            latency_ms=result.latencyMs,
            total_tokens=result.usage.totalTokens,
        )

    async def proposeGuidedWorkflow(
        self,
        *,
        sessionId: str,
        workflow: GuidedWorkflowView,
        latestUserMessage: str,
        language: Literal["en", "zh-CN"],
    ) -> GuidedWorkflowProposal:
        """生成单阶段、待人工应用的工作流候选，不授予任何写入权限。"""

        runtime = self._configStore.getRuntimeConfig(sessionId)
        if workflow.status.value != "ACTIVE":
            raise ValueError("guided workflow must be active")
        if workflow.language != language:
            # 语言变更可以从本次请求开始生效，但旧消息保持原样以保留审计历史。
            requestedLanguage = language
        else:
            requestedLanguage = workflow.language
        recentMessages = [
            {
                "role": message.role,
                "stage": message.stage.value,
                "content": message.content,
            }
            for message in workflow.messages[-6:]
        ]
        payload = {
            "current_stage": workflow.stage.value,
            "requested_language": requestedLanguage,
            "current_draft": workflow.draft.model_dump(mode="json"),
            "recent_messages": recentMessages,
            "latest_user_message": latestUserMessage,
        }
        request = self._buildRequest(
            runtime=runtime,
            sessionId=sessionId,
            requestId=self._newRequestId("guided"),
            prompt=GUIDED_WORKFLOW_PROMPT,
            userContent=buildGuidedWorkflowUserMessage(payload),
            agentConfigHash=canonicalHash(
                {
                    "workflow": GUIDED_WORKFLOW_PROMPT.version,
                    "stage": workflow.stage.value,
                    "language": requestedLanguage,
                }
            ),
            observationHash=canonicalHash(payload),
            allowedEvidenceIds=frozenset(),
            maxTokens=2_048,
            streamResponse=False,
        )

        def validateProposal(modelResult: ModelResult[Any]) -> None:
            proposal = modelResult.data
            if not isinstance(proposal, GuidedWorkflowProposal):
                raise ModelGatewayError(
                    FailureCode.SCHEMA_INVALID,
                    "gateway returned the wrong guided-workflow schema",
                )
            if proposal.stage is not workflow.stage:
                raise ModelGatewayError(
                    FailureCode.ACTION_NOT_ALLOWED,
                    "guided proposal attempted to change the deterministic workflow stage",
                )

        result = await self._execute(
            request=request,
            schema=GuidedWorkflowProposal,
            policy=self._policy(allowRuleFallback=False),
            resultValidator=validateProposal,
            useDecisionCache=False,
        )
        return result.data

    async def generateBeliefDecision(
        self,
        *,
        sessionId: str,
        observation: Observation,
        costBudget: ModelCostBudget | None = None,
        allowRuleFallback: bool = True,
    ) -> BeliefDecisionRun:
        runtime = self._configStore.getRuntimeConfig(sessionId)
        request = self._buildRequest(
            runtime=runtime,
            sessionId=sessionId,
            requestId=self._newRequestId("belief"),
            prompt=HYBRID_BELIEF_PROMPT,
            userContent=buildBeliefUserMessage(observation),
            agentConfigHash=canonicalHash(observation.agent),
            observationHash=canonicalHash(observation),
            allowedEvidenceIds=observation.evidenceIds(),
            allowedActionValues=frozenset(action.value for action in observation.allowed_actions),
        )
        result = await self._execute(
            request=request,
            schema=BeliefDecision,
            policy=self._policy(allowRuleFallback=allowRuleFallback),
            costBudget=costBudget,
        )
        failureCodes = tuple(code.value for code in result.failureCodes)
        fallbackReason = next(
            (
                code.value
                for code in reversed(result.failureCodes)
                if code not in {FailureCode.FALLBACK_USED, FailureCode.RULE_FALLBACK_USED}
            ),
            None,
        )
        return BeliefDecisionRun(
            decision=result.data,
            provider=result.provider,
            model=result.model,
            request_id=result.requestId,
            cache_hit=result.cacheHit,
            fallback_used=result.fallbackUsed,
            repair_used=result.repairUsed,
            latency_ms=result.latencyMs,
            total_tokens=result.usage.totalTokens,
            prompt_tokens=result.usage.promptTokens,
            completion_tokens=result.usage.completionTokens,
            cached_tokens=result.usage.cachedTokens,
            cost_upper_bound_usd=result.costUpperBoundUsd or 0.0,
            transport_attempts=result.transportAttempts,
            failure_codes=failureCodes,
            fallback_reason=fallbackReason,
        )

    async def interpretExperimentResult(
        self,
        *,
        sessionId: str,
        result: dict[str, Any],
        messages: tuple[dict[str, str], ...],
        language: ResultLanguage,
        initial: bool,
        includeAnalysisSummary: bool,
        progressObserver: ModelStreamObserver | None = None,
    ) -> ResultInterpretationRun:
        """用会话级 BYOK 对已完成结果进行只读、可引用的解释。"""

        runtime = self._configStore.getRuntimeConfig(sessionId)
        if not messages or messages[-1].get("role") != "user":
            raise ValueError("messages must end with a user turn")
        if language not in {"en", "zh-CN"}:
            raise ValueError("language must be en or zh-CN")
        resultHash = canonicalHash(result)
        plannerResult: ModelResult[ResultToolPlan] | None = None
        plannerError: ModelGatewayError | None = None
        await emitModelStreamProgress(
            progressObserver,
            ModelStreamProgress(stage=ModelStreamStage.PREPARING),
        )

        if initial:
            selectedTools = DEFAULT_RESULT_TOOLS
        else:
            await emitModelStreamProgress(
                progressObserver,
                ModelStreamProgress(stage=ModelStreamStage.PLANNING),
            )
            resultIndex = buildResultIndex(result)
            latestQuestion = messages[-1]["content"]
            plannerPayload = {
                "requested_language": language,
                "latest_user_question": latestQuestion,
                # 只给 Planner 最近两轮短上下文，支持“那第二个呢”一类指代追问；
                # 完整结果仍只能由白名单工具读取。
                "recent_conversation": list(messages[-4:]),
                "result_index": resultIndex,
            }
            plannerRequest = self._buildRequest(
                runtime=runtime,
                sessionId=sessionId,
                requestId=self._newRequestId("result-plan"),
                prompt=RESULT_TOOL_PLANNER_PROMPT,
                userContent=buildResultPlannerUserMessage(plannerPayload),
                agentConfigHash=canonicalHash(
                    {
                        "workflow": RESULT_TOOL_PLANNER_PROMPT.version,
                        "language": language,
                    }
                ),
                observationHash=canonicalHash(
                    {
                        "resultHash": resultHash,
                        "latestQuestion": latestQuestion,
                        "resultIndex": resultIndex,
                    }
                ),
                allowedEvidenceIds=frozenset(),
                maxTokens=1_024,
                thinkingEnabled=False,
                streamResponse=True,
                streamObserver=progressObserver,
            )
            try:
                plannerResult = await self._execute(
                    request=plannerRequest,
                    schema=ResultToolPlan,
                    policy=self._interpretationPolicy(stage="planner"),
                    useDecisionCache=False,
                )
                # 即使 Planner 遗漏，解释也必须读取研究边界与局限。
                selectedTools = tuple(
                    dict.fromkeys(
                        (
                            ResultEvidenceTool.OVERVIEW,
                            ResultEvidenceTool.LIMITATIONS,
                            *plannerResult.data.tools,
                        )
                    )
                )
            except ModelGatewayError as error:
                # Planner 只是选择只读切片的辅助模型，失败时读取全部有界工具比
                # 让整轮解释失败更安全；答案阶段仍必须通过完整结构与证据校验。
                plannerError = error
                selectedTools = DEFAULT_RESULT_TOOLS

        await emitModelStreamProgress(
            progressObserver,
            ModelStreamProgress(stage=ModelStreamStage.READING_RESULTS),
        )
        toolResults = executeResultTools(result, selectedTools)
        allowedEvidenceIds = frozenset(item.evidence_id for item in toolResults)
        answerPayload = {
            "requested_language": language,
            "reasoning_summary_requested": includeAnalysisSummary,
            "result_snapshot_hash": resultHash,
            "conversation": list(messages),
            "result_tool_outputs": toolResultsPayload(toolResults),
        }
        answerRequest = self._buildRequest(
            runtime=runtime,
            sessionId=sessionId,
            requestId=self._newRequestId("result-answer"),
            prompt=RESULT_INTERPRETATION_PROMPT,
            userContent=buildResultInterpretationUserMessage(answerPayload),
            agentConfigHash=canonicalHash(
                {
                    "workflow": RESULT_INTERPRETATION_PROMPT.version,
                    "language": language,
                    "includeAnalysisSummary": includeAnalysisSummary,
                    "tools": [tool.value for tool in selectedTools],
                }
            ),
            observationHash=canonicalHash(answerPayload),
            allowedEvidenceIds=allowedEvidenceIds,
            maxTokens=4_096,
            streamResponse=True,
            streamObserver=progressObserver,
        )

        def validateInterpretation(modelResult: ModelResult[Any]) -> None:
            answer = modelResult.data
            if not isinstance(answer, ResultInterpretationAnswer):
                raise ModelGatewayError(
                    FailureCode.SCHEMA_INVALID,
                    "gateway returned the wrong result-interpretation schema",
                )

        await emitModelStreamProgress(
            progressObserver,
            ModelStreamProgress(stage=ModelStreamStage.GENERATING),
        )
        answerResult = await self._execute(
            request=answerRequest,
            schema=ResultInterpretationAnswer,
            policy=self._interpretationPolicy(stage="answer"),
            resultValidator=validateInterpretation,
            useDecisionCache=False,
        )
        answerResult = replace(
            answerResult,
            data=self._normalizeInterpretationAnswer(
                answerResult.data,
                language=language,
                includeAnalysisSummary=includeAnalysisSummary,
            ),
        )
        usage = answerResult.usage
        latencyMs = answerResult.latencyMs
        cacheHit = answerResult.cacheHit
        repairUsed = answerResult.repairUsed
        transportAttempts = answerResult.transportAttempts
        uncertainBillableAttempts = answerResult.uncertainBillableAttempts
        failureCodes = list(answerResult.failureCodes)
        if plannerResult is not None:
            usage = plannerResult.usage.plus(usage)
            latencyMs += plannerResult.latencyMs
            cacheHit = plannerResult.cacheHit and cacheHit
            repairUsed = plannerResult.repairUsed or repairUsed
            transportAttempts += plannerResult.transportAttempts
            uncertainBillableAttempts += plannerResult.uncertainBillableAttempts
            failureCodes = [*plannerResult.failureCodes, *failureCodes]
        elif plannerError is not None:
            cacheHit = False
            repairUsed = plannerError.repairUsed or repairUsed
            transportAttempts += max(0, plannerError.attempts)
            uncertainBillableAttempts += max(0, plannerError.uncertainBillableAttempts)
            failureCodes.insert(0, plannerError.code)

        await emitModelStreamProgress(
            progressObserver,
            ModelStreamProgress(
                stage=ModelStreamStage.COMPLETED,
                elapsedMs=latencyMs,
                chunkCount=0,
            ),
        )

        return ResultInterpretationRun(
            interpretation=answerResult.data,
            result_hash=resultHash,
            provider=answerResult.provider,
            model=answerResult.model,
            tool_activity=toolActivities(toolResults, language),
            usage=ModelUsage(
                promptTokens=usage.promptTokens,
                completionTokens=usage.completionTokens,
                cachedTokens=usage.cachedTokens,
            ),
            latency_ms=latencyMs,
            model_calls=max(1, transportAttempts),
            cache_hit=cacheHit,
            repair_used=repairUsed,
            planner_used=not initial,
            prompt_version=RESULT_INTERPRETATION_PROMPT.version,
            planner_fallback_used=plannerError is not None,
            thinking_enabled=runtime.thinkingEnabled,
            streamed=True,
            transport_attempts=transportAttempts,
            uncertain_billable_attempts=uncertainBillableAttempts,
            failure_codes=tuple(code.value for code in failureCodes),
        )

    def getTelemetry(self) -> CognitionTelemetryView:
        with self._telemetryLock:
            state = self._telemetry
            calls = state.calls
            totalTokens = state.promptTokens + state.completionTokens
            return CognitionTelemetryView(
                calls=calls,
                cache_hits=state.cacheHits,
                fallbacks=state.fallbacks,
                invalid_outputs=state.invalidOutputs,
                prompt_tokens=state.promptTokens,
                completion_tokens=state.completionTokens,
                cached_tokens=state.cachedTokens,
                total_tokens=totalTokens,
                total_latency_ms=round(state.totalLatencyMs, 6),
                average_latency_ms=(round(state.totalLatencyMs / calls, 6) if calls else 0.0),
                cache_hit_rate=(round(state.cacheHits / calls, 6) if calls else 0.0),
                fallback_rate=(round(state.fallbacks / calls, 6) if calls else 0.0),
                invalid_output_rate=(round(state.invalidOutputs / calls, 6) if calls else 0.0),
            )

    def runEvaluation(self, samples: tuple[EvalSample, ...]) -> EvalSuiteResult:
        result = runEvaluationSuite(samples)
        with self._telemetryLock:
            self._lastEvalSuite = result
        return result

    def getEvalSummary(self) -> CognitionEvalSummary:
        with self._telemetryLock:
            suite = self._lastEvalSuite
        return CognitionEvalSummary(
            telemetry=self.getTelemetry(),
            evaluated_cases=suite.total_cases if suite is not None else 0,
            passed_cases=suite.passed_cases if suite is not None else 0,
            pass_rate=suite.pass_rate if suite is not None else 0.0,
        )

    async def _execute[ModelT: BaseModel](
        self,
        *,
        request: ModelRequest,
        schema: type[ModelT],
        policy: ModelPolicy,
        resultValidator: ResultValidator | None = None,
        costBudget: ModelCostBudget | None = None,
        useDecisionCache: bool = True,
    ) -> ModelResult[ModelT]:
        startedAt = self._clock()
        effectivePolicy = (
            policy.model_copy(update={"timeout_seconds": request.samplingConfig.timeout_seconds})
            if request.samplingConfig.timeout_seconds is not None
            else policy
        )
        reservation = None
        if costBudget is not None:
            try:
                reservation = costBudget.reserve(request, effectivePolicy)
            except ModelGatewayError as error:
                self._recordError(error.code, self._elapsedMilliseconds(startedAt))
                raise

        # 自由对话不得进入用于实验确定性重放的不可变缓存：其中可能含用户问题，
        # 且无限唯一输入会挤满全局缓存。端点层另以 clientRequestId 做瞬时单飞。
        gateway = self._gatewayFactory(self._decisionCache if useDecisionCache else None)
        try:
            try:
                result = await gateway.generateStructured(request, schema, effectivePolicy)
                if costBudget is not None and reservation is not None:
                    activeReservation = reservation
                    reservation = None
                    settlement = costBudget.settle(activeReservation, result)
                    result = replace(
                        result,
                        costUpperBoundUsd=float(settlement.chargedUsdUpperBound),
                    )
                if result.fallbackUsed and not effectivePolicy.allow_rule_fallback:
                    failureCode = next(
                        (
                            code
                            for code in reversed(result.failureCodes)
                            if code
                            not in {FailureCode.FALLBACK_USED, FailureCode.RULE_FALLBACK_USED}
                        ),
                        FailureCode.RULE_FALLBACK_USED,
                    )
                    raise ModelGatewayError(
                        failureCode,
                        "the model result used a deterministic fallback while "
                        "fallback was disabled",
                    )
                # 即使注入的网关实现有缺陷，运行时仍执行最后一道确定性边界检查。
                validateEvidenceReferences(result.data, request.allowedEvidenceIds)
                validateAllowedAction(result.data, request.allowedActionValues)
                try:
                    MODEL_OUTPUT_VALIDATOR.validateModelOutput(
                        result.data,
                        protectedSecrets=(request.apiKey,),
                    )
                except UnsafeModelOutputError as error:
                    raise ModelGatewayError(
                        FailureCode.PROMPT_DISCLOSURE_BLOCKED,
                        "model output failed deterministic disclosure safety validation",
                    ) from error
                if resultValidator is not None:
                    resultValidator(result)
            except ModelGatewayError as error:
                if costBudget is not None and reservation is not None:
                    costBudget.failClosed(reservation)
                    reservation = None
                self._recordError(error.code, self._elapsedMilliseconds(startedAt))
                raise
            except Exception:
                if costBudget is not None and reservation is not None:
                    costBudget.failClosed(reservation)
                    reservation = None
                self._recordError(None, self._elapsedMilliseconds(startedAt))
                raise
        finally:
            await gateway.aclose()

        self._recordResult(result)
        return result

    def _buildRequest(
        self,
        *,
        runtime: RuntimeProviderConfig,
        sessionId: str,
        requestId: str,
        prompt: PromptSpec,
        userContent: str,
        agentConfigHash: str,
        observationHash: str,
        allowedEvidenceIds: frozenset[str],
        allowedActionValues: frozenset[str] = frozenset(),
        maxTokens: int | None = None,
        thinkingEnabled: bool | None = None,
        streamResponse: bool = False,
        streamObserver: ModelStreamObserver | None = None,
    ) -> ModelRequest:
        advanced = runtime.advancedParameters
        samplingRequested = any(
            value is not None
            for value in (
                advanced.temperature,
                advanced.topP,
                advanced.presencePenalty,
                advanced.frequencyPenalty,
                advanced.seed,
            )
        )
        return ModelRequest(
            provider=runtime.provider,
            model=runtime.model,
            requestId=requestId,
            userId=self._hashedUserId(sessionId),
            systemPrompt=prompt.systemPrompt,
            userContent=userContent,
            promptHash=prompt.promptHash,
            schemaVersion=prompt.schemaVersion,
            agentConfigHash=agentConfigHash,
            observationHash=observationHash,
            allowedEvidenceIds=allowedEvidenceIds,
            allowedActionValues=allowedActionValues,
            samplingConfig=SamplingConfig(
                thinking_enabled=(
                    runtime.thinkingEnabled if thinkingEnabled is None else thinkingEnabled
                ),
                do_sample=samplingRequested,
                max_tokens=min(runtime.maxTokens, maxTokens or runtime.maxTokens),
                temperature=advanced.temperature,
                top_p=advanced.topP,
                presence_penalty=advanced.presencePenalty,
                frequency_penalty=advanced.frequencyPenalty,
                seed=advanced.seed,
                timeout_seconds=advanced.timeoutSeconds,
            ),
            apiKey=runtime.apiKey,
            streamResponse=streamResponse,
            streamObserver=streamObserver,
        )

    def _recordResult(self, result: ModelResult[Any]) -> None:
        invalid = any(code in INVALID_OUTPUT_CODES for code in result.failureCodes)
        with self._telemetryLock:
            self._telemetry.calls += 1
            self._telemetry.cacheHits += int(result.cacheHit)
            self._telemetry.fallbacks += int(result.fallbackUsed)
            self._telemetry.invalidOutputs += int(invalid)
            self._telemetry.promptTokens += result.usage.promptTokens
            self._telemetry.completionTokens += result.usage.completionTokens
            self._telemetry.cachedTokens += result.usage.cachedTokens
            self._telemetry.totalLatencyMs += max(result.latencyMs, 0.0)

    def _recordError(self, failureCode: FailureCode | None, latencyMs: float) -> None:
        with self._telemetryLock:
            self._telemetry.calls += 1
            self._telemetry.invalidOutputs += int(failureCode in INVALID_OUTPUT_CODES)
            self._telemetry.totalLatencyMs += max(latencyMs, 0.0)

    def _policy(self, *, allowRuleFallback: bool) -> ModelPolicy:
        return self._modelPolicy.model_copy(
            update={"allow_rule_fallback": allowRuleFallback},
        )

    def _interpretationPolicy(self, *, stage: Literal["planner", "answer"]) -> ModelPolicy:
        """分离规划与回答预算；流式刷新体验但仍保留单次调用总上限。"""

        return self._modelPolicy.model_copy(
            update={
                # 最坏为 Planner 初次+修复 50 秒、答案初次+修复 240 秒，仍低于
                # 生产代理 300 秒上限；单次传输不做自动重试，避免重复计费。
                "timeout_seconds": 25.0 if stage == "planner" else 120.0,
                "max_transport_attempts": 1,
                "base_backoff_seconds": 0.0,
                "allow_rule_fallback": False,
            }
        )

    @staticmethod
    def _normalizeInterpretationAnswer(
        answer: ResultInterpretationAnswer,
        *,
        language: ResultLanguage,
        includeAnalysisSummary: bool,
    ) -> ResultInterpretationAnswer:
        """由服务端固定研究边界，并使“解释摘要”开关具有确定行为。"""

        boundary = (
            "This is scenario analysis conditional on synthetic assumptions, not a "
            "prediction and not investment advice."
            if language == "en"
            else "这是以合成假设为条件的情景分析，不是预测，也不构成投资建议。"
        )
        normalizedAnswer = answer.answer.strip()
        if not normalizedAnswer.startswith(boundary):
            # 固定边界必须先于模型叙事出现；只移除完全相同的尾注，避免重复，
            # 不改写模型正文或证据引用。
            answerBody = normalizedAnswer.removesuffix(boundary).rstrip()
            normalizedAnswer = f"{boundary}\n\n{answerBody}" if answerBody else boundary
        analysisSummary = answer.analysis_summary if includeAnalysisSummary else None
        if includeAnalysisSummary and analysisSummary is None:
            analysisSummary = (
                "Reviewable summary unavailable: the explanation still uses only the "
                "listed result evidence slices."
                if language == "en"
                else "未返回可核验的分析摘要；正文仍仅依据所列实验结果证据切片。"
            )
        return answer.model_copy(
            update={
                "answer": normalizedAnswer,
                "analysis_summary": analysisSummary,
            }
        )

    @staticmethod
    def _promptView(prompt: PromptSpec) -> PromptRegistryView:
        return PromptRegistryView(
            name=prompt.name,
            version=prompt.version,
            schema_version=prompt.schemaVersion,
            prompt_hash=prompt.promptHash,
        )

    @staticmethod
    def _newRequestId(workflow: str) -> str:
        return f"{workflow}-{uuid.uuid4().hex}"

    @staticmethod
    def _hashedUserId(sessionId: str) -> str:
        digest = hashlib.sha256(sessionId.encode("utf-8")).hexdigest()
        return f"anonymous-{digest[:32]}"

    def _elapsedMilliseconds(self, startedAt: float) -> float:
        return max((self._clock() - startedAt) * 1_000.0, 0.0)

    @staticmethod
    def _toEventPackClaims(
        extraction: EventExtractionResult,
        sourceById: dict[str, ExternalEvidenceSource],
        *,
        requestedImpactChannels: tuple[str, ...],
    ) -> tuple[dict[str, Any], ...]:
        claims: list[dict[str, Any]] = []
        for index, candidate in enumerate(extraction.claims):
            sourceTypes = {
                sourceById[sourceId].sourceType for sourceId in candidate.source_evidence_ids
            }
            sourceTier = next(iter(sourceTypes)) if len(sourceTypes) == 1 else "MIXED"
            claims.append(
                {
                    "claimId": candidate.candidate_claim_id,
                    "text": candidate.claim,
                    "claimType": candidate.claim_type.value,
                    "sourceIds": list(candidate.source_evidence_ids),
                    "sourceTier": sourceTier,
                    "knownAt": candidate.known_at.isoformat(),
                    "confidence": candidate.confidence,
                    "impactChannels": list(requestedImpactChannels),
                    "reviewStatus": "AI_PROPOSED",
                    "isRequired": index == 0,
                    "evidenceQuote": candidate.claim[:500],
                    "instructionLikeTextDetected": (candidate.instruction_like_text_detected),
                    "synthetic": False,
                }
            )
        return tuple(claims)
