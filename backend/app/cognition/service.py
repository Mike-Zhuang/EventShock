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
    RuntimeProviderConfig,
    SessionConfigStore,
    SessionProviderConfigView,
)
from backend.app.cognition.evaluation import EvalSample, EvalSuiteResult, runEvaluationSuite
from backend.app.cognition.gateway import (
    FailureCode,
    ModelGatewayError,
    ModelPolicy,
    ModelRequest,
    ModelResult,
    SamplingConfig,
    canonicalHash,
    validateAllowedAction,
    validateEvidenceReferences,
)
from backend.app.cognition.models import (
    BeliefDecision,
    EventExtractionResult,
    Observation,
    StrictFrozenModel,
)
from backend.app.cognition.pricing import ModelCostBudget
from backend.app.cognition.prompts import (
    EVENT_EXTRACTION_PROMPT,
    HYBRID_BELIEF_PROMPT,
    PROMPT_REGISTRY,
    PromptSpec,
    buildBeliefUserMessage,
    buildEvidenceUserMessage,
)
from backend.app.cognition.provider_gateways import ProviderGatewayRouter

SourceType = Literal["OFFICIAL", "REPORTING", "ESTIMATE", "USER_PROVIDED"]


class ExternalEvidenceSource(StrictFrozenModel):
    """来自上传或外部抓取的最小来源；正文始终按不可信数据处理。"""

    sourceId: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    rawText: str = Field(min_length=1, max_length=50_000)
    sourceType: SourceType
    knownAt: datetime

    @model_validator(mode="after")
    def validateKnownAt(self) -> ExternalEvidenceSource:
        if self.knownAt.tzinfo is None or self.knownAt.utcoffset() is None:
            raise ValueError("knownAt must include a timezone")
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


GatewayFactory = Callable[[ImmutableDecisionCache], ClosableModelGateway]
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
    }
)


def _defaultGatewayFactory(cache: ImmutableDecisionCache) -> ClosableModelGateway:
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
    ) -> SessionProviderConfigView:
        return self._configStore.setConfig(
            sessionId=sessionId,
            apiKey=apiKey,
            model=model,
            provider=provider,
            thinkingEnabled=thinkingEnabled,
            maxTokens=maxTokens,
        )

    def getConfig(self, sessionId: str) -> SessionProviderConfigView:
        return self._configStore.getView(sessionId)

    def clearConfig(self, sessionId: str) -> bool:
        return self._configStore.clear(sessionId)

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
    ) -> EventClaimExtractionRun:
        runtime = self._configStore.getRuntimeConfig(sessionId)
        if not 1 <= len(sources) <= 8:
            raise ValueError("sources must contain between 1 and 8 items")
        if not 1 <= maximumClaims <= 50:
            raise ValueError("maximumClaims must be between 1 and 50")
        sourceIds = [source.sourceId for source in sources]
        if len(sourceIds) != len(set(sourceIds)):
            raise ValueError("sources contain duplicate sourceId values")

        sourcePayloads = [source.model_dump(mode="json") for source in sources]
        payload = {
            "source_fragments": sourcePayloads,
            "maximum_claims": maximumClaims,
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

        result = await self._execute(
            request=request,
            schema=EventExtractionResult,
            policy=self._modelPolicy,
            resultValidator=validateExtraction,
        )
        claims = self._toEventPackClaims(result.data, sourceById)
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
    ) -> ModelResult[ModelT]:
        startedAt = self._clock()
        reservation = None
        if costBudget is not None:
            try:
                reservation = costBudget.reserve(request, policy)
            except ModelGatewayError as error:
                self._recordError(error.code, self._elapsedMilliseconds(startedAt))
                raise

        gateway = self._gatewayFactory(self._decisionCache)
        try:
            try:
                result = await gateway.generateStructured(request, schema, policy)
                if costBudget is not None and reservation is not None:
                    activeReservation = reservation
                    reservation = None
                    settlement = costBudget.settle(activeReservation, result)
                    result = replace(
                        result,
                        costUpperBoundUsd=float(settlement.chargedUsdUpperBound),
                    )
                if result.fallbackUsed and not policy.allow_rule_fallback:
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
    ) -> ModelRequest:
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
                thinking_enabled=runtime.thinkingEnabled,
                do_sample=False,
                max_tokens=runtime.maxTokens,
            ),
            apiKey=runtime.apiKey,
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
                    "impactChannels": ["belief"],
                    "reviewStatus": "AI_PROPOSED",
                    "isRequired": index == 0,
                    "evidenceQuote": candidate.claim[:500],
                    "instructionLikeTextDetected": (candidate.instruction_like_text_detected),
                    "synthetic": False,
                }
            )
        return tuple(claims)
