"""固定官方端点的多供应商结构化输出网关。

本模块只接受统一目录中的供应商和模型，不允许调用方覆盖 ``base_url``。
所有供应商响应最终都必须通过本地 Pydantic、证据引用和动作边界验证；
供应商侧的 JSON Schema/JSON object 只是第一道格式约束，不能替代本地验证。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.cognition.cache import (
    ImmutableDecisionCache,
    buildDecisionCacheKey,
    canonicalModelBytes,
)
from backend.app.cognition.catalog import ProviderId, getModel, getProvider
from backend.app.cognition.gateway import (
    FailureCode,
    ModelGatewayError,
    ModelPolicy,
    ModelRequest,
    ModelResult,
    ModelUsage,
    buildRuleFallback,
    validateAllowedAction,
    validateEvidenceReferences,
)
from backend.app.cognition.models import ActionPreference
from backend.app.cognition.prompts import (
    buildRepairInstruction,
    encodeUntrustedPromptText,
)
from backend.app.cognition.streaming import (
    ModelStreamProgress,
    ModelStreamStage,
    ProviderStreamAccumulator,
    emitModelStreamProgress,
    iterSseEvents,
)
from backend.app.cognition.zhipu import ZhipuRestGateway

NON_ZHIPU_PROVIDERS: tuple[ProviderId, ...] = (
    "openai",
    "anthropic",
    "google",
    "deepseek",
    "alibaba",
    "moonshot",
)

# Anthropic 原生结构化输出会拒绝 SDK 通常会在客户端移除的校验关键字；
# Gemini 也只接受 JSON Schema 的有限子集。原始 Pydantic 模型仍在响应落地后
# 完整验证，因此运输层删减约束不会降低应用侧的数据边界。
_ANTHROPIC_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "default",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "multipleOf",
        "pattern",
    }
)
_GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "$schema",
        "const",
        "default",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "examples",
        "maxLength",
        "minLength",
        "multipleOf",
        "pattern",
    }
)


@dataclass(frozen=True, slots=True)
class _RepairContext:
    invalidContent: str
    error: ModelGatewayError


def _resolveJsonPointer(root: dict[str, Any], pointer: str) -> Any:
    """只解析当前 schema 内的 JSON Pointer，绝不读取外部引用。"""

    if not pointer.startswith("#/"):
        raise ValueError("external JSON Schema references are not supported")
    value: Any = root
    for rawPart in pointer[2:].split("/"):
        part = rawPart.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise ValueError("JSON Schema reference could not be resolved")
        value = value[part]
    return value


def _inlineSchemaReferences(
    value: Any,
    root: dict[str, Any],
    activeReferences: tuple[str, ...] = (),
) -> Any:
    """内联 Pydantic 的本地 ``$ref``，便于供应商子集可靠接收。"""

    if isinstance(value, list):
        return [_inlineSchemaReferences(item, root, activeReferences) for item in value]
    if not isinstance(value, dict):
        return value

    reference = value.get("$ref")
    if isinstance(reference, str):
        if reference in activeReferences:
            raise ValueError("recursive JSON Schema references are not supported")
        target = _resolveJsonPointer(root, reference)
        resolved = _inlineSchemaReferences(
            target,
            root,
            activeReferences + (reference,),
        )
        if not isinstance(resolved, dict):
            raise ValueError("JSON Schema reference target must be an object")
        siblings = {
            key: _inlineSchemaReferences(item, root, activeReferences)
            for key, item in value.items()
            if key != "$ref"
        }
        return {**resolved, **siblings}

    return {
        key: _inlineSchemaReferences(item, root, activeReferences)
        for key, item in value.items()
        if key not in {"$defs", "definitions"}
    }


def _removeSchemaKeywords(value: Any, unsupportedKeys: frozenset[str]) -> Any:
    if isinstance(value, list):
        return [_removeSchemaKeywords(item, unsupportedKeys) for item in value]
    if not isinstance(value, dict):
        return value

    normalized: dict[str, Any] = {}
    for key, item in value.items():
        # Gemini 不接受 const，但 enum 是其明确支持的等价表达。
        if key == "const" and key in unsupportedKeys:
            normalized["enum"] = [item]
            continue
        if key in unsupportedKeys:
            continue
        normalized[key] = _removeSchemaKeywords(item, unsupportedKeys)
    return normalized


def _makeStrictObjectSchema(value: Any) -> Any:
    """满足 OpenAI/Kimi strict 模式：对象属性完整 required 且禁止额外键。"""

    if isinstance(value, list):
        return [_makeStrictObjectSchema(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {
        key: _makeStrictObjectSchema(item) for key, item in value.items() if key != "default"
    }
    properties = normalized.get("properties")
    if isinstance(properties, dict):
        normalized["required"] = list(properties)
        normalized["additionalProperties"] = False
    return normalized


def _transportSchema(provider: ProviderId, schema: type[BaseModel]) -> dict[str, Any]:
    """按供应商真实 wire contract 生成 schema；本地验证仍使用原模型。"""

    rawSchema = schema.model_json_schema()
    inlined = _inlineSchemaReferences(rawSchema, rawSchema)
    if not isinstance(inlined, dict):
        raise ValueError("model JSON Schema root must be an object")
    if provider in {"openai", "moonshot"}:
        strictSchema = _makeStrictObjectSchema(inlined)
        if not isinstance(strictSchema, dict):
            raise ValueError("strict JSON Schema root must be an object")
        return strictSchema
    if provider == "anthropic":
        normalized = _removeSchemaKeywords(inlined, _ANTHROPIC_UNSUPPORTED_SCHEMA_KEYS)
    elif provider == "google":
        normalized = _removeSchemaKeywords(inlined, _GEMINI_UNSUPPORTED_SCHEMA_KEYS)
    else:
        normalized = inlined
    if not isinstance(normalized, dict):
        raise ValueError("transport JSON Schema root must be an object")
    return normalized


class StructuredProviderRestGateway:
    """六家非智谱供应商共用的缓存、重试、修复和本地验证管线。"""

    def __init__(
        self,
        provider: ProviderId,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        cache: ImmutableDecisionCache | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        randomSource: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if provider not in NON_ZHIPU_PROVIDERS:
            raise ValueError("StructuredProviderRestGateway requires a non-Zhipu provider")
        if transport is not None and client is not None:
            raise ValueError("provide transport or client, not both")
        # endpoint 只从受信目录读取，构造器故意不接受 URL，避免 SSRF 和密钥外送。
        self._provider = provider
        self._endpoint = getProvider(provider).api_endpoint
        self._client = client or httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
        )
        self._ownsClient = client is None
        self._cache = cache
        self._sleeper = sleeper
        self._randomSource = randomSource
        self._clock = clock

    async def __aenter__(self) -> StructuredProviderRestGateway:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._ownsClient:
            await self._client.aclose()

    async def generateStructured[ModelT: BaseModel](
        self,
        request: ModelRequest,
        schema: type[ModelT],
        policy: ModelPolicy,
    ) -> ModelResult[ModelT]:
        self._validateRequest(request)
        cacheKey = self._cacheKey(request)
        startedAt = self._clock()

        if self._cache is not None:
            cached = self._cache.get(cacheKey, schema)
            if cached is not None:
                data, cacheEntry = cached
                return ModelResult(
                    data=data,
                    provider=request.provider,
                    model=request.model,
                    requestId=request.requestId,
                    promptHash=request.promptHash,
                    responseHash=cacheEntry.responseHash,
                    cacheKey=cacheKey,
                    usage=ModelUsage(),
                    latencyMs=self._elapsedMilliseconds(startedAt),
                    transportAttempts=0,
                    repairUsed=False,
                    fallbackUsed=False,
                    cacheHit=True,
                )

        totalUsage = ModelUsage()
        totalAttempts = 0
        uncertainBillableAttempts = 0
        failureCodes: list[FailureCode] = []
        rawContent = ""
        responseHash = ""
        data: ModelT | None = None
        lastError: ModelGatewayError | None = None
        repairUsed = False

        try:
            body, rawBody, attempts, uncertainAttempts = await self._postWithRetry(
                payload=self._buildPayload(request, schema),
                request=request,
                policy=policy,
                repair=False,
            )
            totalAttempts += attempts
            uncertainBillableAttempts += uncertainAttempts
            # 200 响应即可能产生费用；先登记 usage，再处理拒答、截断或坏 JSON。
            totalUsage = totalUsage.plus(self._usageFromBillableBody(body))
            rawContent = self._contentFromBody(body)
            await emitModelStreamProgress(
                request.streamObserver,
                ModelStreamProgress(
                    stage=ModelStreamStage.VALIDATING,
                    elapsedMs=self._elapsedMilliseconds(startedAt),
                    attempt=attempts,
                ),
            )
            data = self._validateContent(rawContent, schema, request)
            responseHash = hashlib.sha256(rawBody).hexdigest()
        except ModelGatewayError as error:
            totalAttempts += error.attempts
            uncertainBillableAttempts += self._uncertainAttemptsFromError(error)
            failureCodes.append(error.code)
            lastError = error

        if data is None and lastError is not None and self._isRepairable(lastError):
            repairUsed = True
            await emitModelStreamProgress(
                request.streamObserver,
                ModelStreamProgress(
                    stage=ModelStreamStage.REPAIRING,
                    elapsedMs=self._elapsedMilliseconds(startedAt),
                    attempt=max(1, totalAttempts + 1),
                    repair=True,
                ),
            )
            try:
                body, rawBody, attempts, uncertainAttempts = await self._postWithRetry(
                    payload=self._buildPayload(
                        request,
                        schema,
                        repairContext=_RepairContext(rawContent, lastError),
                    ),
                    request=request,
                    policy=policy,
                    repair=True,
                )
                totalAttempts += attempts
                uncertainBillableAttempts += uncertainAttempts
                totalUsage = totalUsage.plus(self._usageFromBillableBody(body))
                repairedContent = self._contentFromBody(body)
                await emitModelStreamProgress(
                    request.streamObserver,
                    ModelStreamProgress(
                        stage=ModelStreamStage.VALIDATING,
                        elapsedMs=self._elapsedMilliseconds(startedAt),
                        attempt=attempts,
                        repair=True,
                    ),
                )
                data = self._validateContent(repairedContent, schema, request)
                responseHash = hashlib.sha256(rawBody).hexdigest()
                lastError = None
            except ModelGatewayError as error:
                totalAttempts += error.attempts
                uncertainBillableAttempts += self._uncertainAttemptsFromError(error)
                failureCodes.append(error.code)
                lastError = error

        if data is None:
            if lastError is None:
                lastError = ModelGatewayError(
                    FailureCode.MODEL_RESPONSE_INVALID,
                    "model did not produce a validated result",
                )
            if not policy.allow_rule_fallback:
                lastError.attempts = max(lastError.attempts, totalAttempts)
                lastError.uncertainBillableAttempts = uncertainBillableAttempts
                lastError.repairUsed = repairUsed
                raise lastError
            data = buildRuleFallback(schema, lastError.code)
            responseHash = hashlib.sha256(canonicalModelBytes(data)).hexdigest()
            failureCodes.extend((FailureCode.FALLBACK_USED, FailureCode.RULE_FALLBACK_USED))
            return ModelResult(
                data=data,
                provider=request.provider,
                model=request.model,
                requestId=request.requestId,
                promptHash=request.promptHash,
                responseHash=responseHash,
                cacheKey=cacheKey,
                usage=totalUsage,
                latencyMs=self._elapsedMilliseconds(startedAt),
                transportAttempts=totalAttempts,
                repairUsed=repairUsed,
                fallbackUsed=True,
                cacheHit=False,
                failureCodes=tuple(failureCodes),
                uncertainBillableAttempts=uncertainBillableAttempts,
            )

        if self._cache is not None:
            self._cache.put(
                cacheKey=cacheKey,
                decision=data,
                provider=request.provider,
                model=request.model,
                promptHash=request.promptHash,
                responseHash=responseHash,
            )
        return ModelResult(
            data=data,
            provider=request.provider,
            model=request.model,
            requestId=request.requestId,
            promptHash=request.promptHash,
            responseHash=responseHash,
            cacheKey=cacheKey,
            usage=totalUsage,
            latencyMs=self._elapsedMilliseconds(startedAt),
            transportAttempts=totalAttempts,
            repairUsed=repairUsed,
            fallbackUsed=False,
            cacheHit=False,
            failureCodes=tuple(failureCodes),
            uncertainBillableAttempts=uncertainBillableAttempts,
        )

    def _validateRequest(self, request: ModelRequest) -> None:
        if request.provider != self._provider:
            raise ValueError(f"{type(self).__name__} only accepts the {self._provider} provider")
        descriptor = getModel(request.provider, request.model)
        if descriptor.max_output_tokens is None:
            raise ValueError("selected model has no verified maximum output limit")
        if request.samplingConfig.max_tokens > descriptor.max_output_tokens:
            raise ValueError("max_tokens exceeds the selected model limit")
        if request.samplingConfig.thinking_enabled and not descriptor.supports_thinking:
            raise ValueError("the selected model does not support thinking")
        if (
            self._provider == "anthropic"
            and request.model == "claude-haiku-4-5-20251001"
            and request.samplingConfig.thinking_enabled
            and request.samplingConfig.max_tokens <= 1_024
        ):
            raise ValueError("Claude Haiku 4.5 thinking requires max_tokens greater than 1024")
        if not 6 <= len(request.requestId) <= 64:
            raise ValueError("requestId must contain 6 to 64 characters")
        if not 6 <= len(request.userId) <= 128:
            raise ValueError("userId must contain 6 to 128 characters")
        if not request.apiKey or request.apiKey != request.apiKey.strip():
            raise ValueError("invalid API key")
        if request.allowedActionValues and ActionPreference.ABSTAIN.value not in (
            request.allowedActionValues
        ):
            raise ValueError("allowedActionValues must include ABSTAIN")
        if hashlib.sha256(request.systemPrompt.encode()).hexdigest() != request.promptHash:
            raise ValueError("promptHash does not match systemPrompt")
        for name, value in (
            ("promptHash", request.promptHash),
            ("agentConfigHash", request.agentConfigHash),
            ("observationHash", request.observationHash),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")

    @staticmethod
    def _cacheKey(request: ModelRequest) -> str:
        return buildDecisionCacheKey(
            tenantHash=hashlib.sha256(request.userId.encode()).hexdigest(),
            provider=request.provider,
            model=request.model,
            promptHash=request.promptHash,
            schemaVersion=request.schemaVersion,
            agentConfigHash=request.agentConfigHash,
            observationHash=request.observationHash,
            samplingConfig=request.samplingConfig.model_dump(mode="json"),
        )

    def _buildPayload[ModelT: BaseModel](
        self,
        request: ModelRequest,
        schema: type[ModelT],
        *,
        repairContext: _RepairContext | None = None,
    ) -> dict[str, Any]:
        jsonSchema = _transportSchema(self._provider, schema)
        userContent = request.userContent
        # 首轮启用流式；修复轮聚焦一次性重建完整 JSON，不把半截修复结果当作
        # 可展示内容。无论是否流式，落地后都执行同一套严格本地校验。
        streamEnabled = request.streamResponse and repairContext is None
        if repairContext is not None:
            repairInstruction = buildRepairInstruction(
                validationCode=repairContext.error.code.value,
                validationDetail=str(repairContext.error),
                allowedEvidenceIds=request.allowedEvidenceIds,
            )
            userContent = (
                f"{request.userContent}\n\n<BEGIN_INVALID_MODEL_OUTPUT>\n"
                f"{encodeUntrustedPromptText(repairContext.invalidContent[:12_000]) or '{}'}\n"
                f"<END_INVALID_MODEL_OUTPUT>\n{repairInstruction}"
            )

        if self._provider == "openai":
            payload: dict[str, Any] = {
                "model": request.model,
                "instructions": request.systemPrompt,
                "input": userContent,
                "max_output_tokens": request.samplingConfig.max_tokens,
                "store": False,
                "stream": streamEnabled,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": self._schemaName(schema),
                        "strict": True,
                        "schema": jsonSchema,
                    }
                },
            }
            if request.samplingConfig.thinking_enabled:
                payload["reasoning"] = {
                    "effort": request.samplingConfig.reasoning_effort or "medium"
                }
            return payload

        if self._provider == "anthropic":
            payload = {
                "model": request.model,
                "system": request.systemPrompt,
                "messages": [{"role": "user", "content": userContent}],
                "max_tokens": request.samplingConfig.max_tokens,
                "stream": streamEnabled,
                "output_config": {"format": {"type": "json_schema", "schema": jsonSchema}},
            }
            if request.samplingConfig.thinking_enabled:
                if request.model == "claude-haiku-4-5-20251001":
                    payload["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": self._anthropicThinkingBudget(
                            request.samplingConfig.max_tokens
                        ),
                    }
                else:
                    payload["thinking"] = {"type": "adaptive"}
            return payload

        if self._provider == "google":
            generationConfig: dict[str, Any] = {
                "max_output_tokens": request.samplingConfig.max_tokens,
                "thinking_level": (
                    self._googleThinkingLevel(request.samplingConfig.reasoning_effort)
                    if request.samplingConfig.thinking_enabled
                    else "minimal"
                ),
                "thinking_summaries": "none",
            }
            return {
                "model": request.model,
                "system_instruction": request.systemPrompt,
                "input": userContent,
                "store": False,
                "stream": streamEnabled,
                "generation_config": generationConfig,
                "response_format": {
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": jsonSchema,
                },
            }

        messages = [
            {"role": "system", "content": request.systemPrompt},
            {"role": "user", "content": userContent},
        ]
        if self._provider == "moonshot":
            payload = {
                "model": request.model,
                "messages": messages,
                "stream": streamEnabled,
                "max_completion_tokens": request.samplingConfig.max_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": self._schemaName(schema),
                        "strict": True,
                        "schema": jsonSchema,
                    },
                },
                # Kimi K3 始终推理且不接受 thinking.type；关闭开关时使用官方
                # 最低推理档，开启时才提升力度，避免发送会被拒绝的参数。
                "reasoning_effort": self._kimiEffort(
                    request.samplingConfig.thinking_enabled,
                    request.samplingConfig.reasoning_effort,
                ),
            }
            if streamEnabled:
                payload["stream_options"] = {"include_usage": True}
            return payload

        payload = {
            "model": request.model,
            "messages": messages,
            "stream": streamEnabled,
            "max_tokens": request.samplingConfig.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if self._provider == "deepseek":
            payload["thinking"] = {
                "type": ("enabled" if request.samplingConfig.thinking_enabled else "disabled")
            }
            if request.samplingConfig.reasoning_effort is not None:
                payload["reasoning_effort"] = self._deepSeekEffort(
                    request.samplingConfig.reasoning_effort
                )
        elif self._provider == "alibaba":
            payload["enable_thinking"] = request.samplingConfig.thinking_enabled
        if streamEnabled:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _headers(self, apiKey: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._provider == "anthropic":
            headers.update(
                {
                    "x-api-key": apiKey,
                    "anthropic-version": "2023-06-01",
                }
            )
        elif self._provider == "google":
            headers["x-goog-api-key"] = apiKey
        else:
            headers["Authorization"] = f"Bearer {apiKey}"
        return headers

    async def _postWithRetry(
        self,
        *,
        payload: dict[str, Any],
        request: ModelRequest,
        policy: ModelPolicy,
        repair: bool,
    ) -> tuple[dict[str, Any], bytes, int, int]:
        lastError: ModelGatewayError | None = None
        uncertainAttempts = 0
        for attemptIndex in range(policy.max_transport_attempts):
            attemptNumber = attemptIndex + 1
            try:
                if payload.get("stream") is True:
                    statusCode, responseHeaders, body, rawBody = await self._postStreaming(
                        payload=payload,
                        request=request,
                        policy=policy,
                        attempt=attemptNumber,
                        repair=repair,
                    )
                else:
                    response = await self._client.post(
                        self._endpoint,
                        headers=self._headers(request.apiKey),
                        json=payload,
                        timeout=self._httpxTimeout(policy),
                        follow_redirects=False,
                    )
                    statusCode = response.status_code
                    responseHeaders = response.headers
                    body = self._decodeBody(response, request.apiKey)
                    rawBody = response.content
            except (httpx.TimeoutException, TimeoutError) as error:
                uncertainAttempts += 1
                lastError = ModelGatewayError(
                    FailureCode.MODEL_TIMEOUT,
                    "model request timed out",
                    retryable=True,
                    attempts=attemptNumber,
                )
                if attemptNumber < policy.max_transport_attempts:
                    await self._backoff(policy, attemptIndex, None)
                    continue
                self._recordUncertainAttempts(lastError, uncertainAttempts)
                raise lastError from error
            except httpx.TransportError as error:
                uncertainAttempts += 1
                lastError = ModelGatewayError(
                    FailureCode.MODEL_TRANSPORT_ERROR,
                    "model transport failed",
                    retryable=True,
                    attempts=attemptNumber,
                )
                if attemptNumber < policy.max_transport_attempts:
                    await self._backoff(policy, attemptIndex, None)
                    continue
                self._recordUncertainAttempts(lastError, uncertainAttempts)
                raise lastError from error
            except ModelGatewayError as error:
                if error.httpStatus == 200:
                    uncertainAttempts += 1
                error.attempts = attemptNumber
                if error.retryable and attemptNumber < policy.max_transport_attempts:
                    await self._backoff(policy, attemptIndex, None)
                    continue
                self._recordUncertainAttempts(error, uncertainAttempts)
                raise

            try:
                if not isinstance(body, dict):
                    raise ModelGatewayError(
                        FailureCode.MODEL_RESPONSE_INVALID,
                        "provider response root must be an object",
                        retryable=statusCode >= 500,
                        httpStatus=statusCode,
                    )
            except ModelGatewayError as error:
                if statusCode == 200:
                    # 成功状态但响应无法解码时无法取得 usage，也无法证明未计费。
                    uncertainAttempts += 1
                error.attempts = attemptNumber
                if error.retryable and attemptNumber < policy.max_transport_attempts:
                    await self._backoff(
                        policy,
                        attemptIndex,
                        responseHeaders.get("Retry-After"),
                    )
                    continue
                self._recordUncertainAttempts(error, uncertainAttempts)
                raise
            if statusCode == 200:
                return body, rawBody, attemptNumber, uncertainAttempts

            lastError = self._classifyError(statusCode, body, request.apiKey)
            lastError.attempts = attemptNumber
            if lastError.retryable and attemptNumber < policy.max_transport_attempts:
                await self._backoff(
                    policy,
                    attemptIndex,
                    responseHeaders.get("Retry-After"),
                )
                continue
            self._recordUncertainAttempts(lastError, uncertainAttempts)
            raise lastError

        if lastError is None:
            lastError = ModelGatewayError(
                FailureCode.MODEL_TRANSPORT_ERROR,
                "model request failed without a response",
            )
        self._recordUncertainAttempts(lastError, uncertainAttempts)
        raise lastError

    async def _postStreaming(
        self,
        *,
        payload: dict[str, Any],
        request: ModelRequest,
        policy: ModelPolicy,
        attempt: int,
        repair: bool,
    ) -> tuple[int, httpx.Headers, dict[str, Any], bytes]:
        """消费供应商 SSE；只向调用方公开阶段和片段计数。"""

        accumulator = ProviderStreamAccumulator(self._provider)
        startedAt = self._clock()
        headers = {**self._headers(request.apiKey), "Accept": "text/event-stream"}
        async with asyncio.timeout(policy.timeout_seconds):
            async with self._client.stream(
                "POST",
                self._endpoint,
                headers=headers,
                json=payload,
                timeout=self._httpxTimeout(policy),
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    rawBody = await response.aread()
                    body = self._decodeRawBody(
                        rawBody,
                        response.status_code,
                        request.apiKey,
                    )
                    return response.status_code, response.headers, body, rawBody

                contentType = response.headers.get("content-type", "").lower()
                if "text/event-stream" not in contentType:
                    rawBody = await response.aread()
                    body = self._decodeRawBody(
                        rawBody,
                        response.status_code,
                        request.apiKey,
                    )
                    return response.status_code, response.headers, body, rawBody

                try:
                    async for event in iterSseEvents(response):
                        previousReasoning = accumulator.reasoningChunkCount
                        accumulator.accept(event)
                        if (
                            accumulator.chunkCount == 1
                            or accumulator.chunkCount % 8 == 0
                            or accumulator.reasoningChunkCount > previousReasoning
                        ):
                            stage = (
                                ModelStreamStage.REASONING
                                if accumulator.reasoningChunkCount > previousReasoning
                                else ModelStreamStage.GENERATING
                            )
                            await emitModelStreamProgress(
                                request.streamObserver,
                                ModelStreamProgress(
                                    stage=stage,
                                    elapsedMs=self._elapsedMilliseconds(startedAt),
                                    chunkCount=accumulator.chunkCount,
                                    answerChunkCount=accumulator.answerChunkCount,
                                    reasoningChunkCount=accumulator.reasoningChunkCount,
                                    attempt=attempt,
                                    repair=repair,
                                ),
                            )
                except ValueError as error:
                    raise ModelGatewayError(
                        FailureCode.MODEL_RESPONSE_INVALID,
                        str(error),
                        httpStatus=response.status_code,
                    ) from error
                try:
                    body = accumulator.buildBody()
                except ValueError as error:
                    raise ModelGatewayError(
                        FailureCode.MODEL_RESPONSE_INVALID,
                        str(error),
                        httpStatus=response.status_code,
                    ) from error
                rawBody = json.dumps(
                    body,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                return response.status_code, response.headers, body, rawBody

    @staticmethod
    def _httpxTimeout(policy: ModelPolicy) -> httpx.Timeout:
        return httpx.Timeout(
            policy.timeout_seconds,
            connect=min(10.0, policy.timeout_seconds),
            write=min(30.0, policy.timeout_seconds),
            pool=min(10.0, policy.timeout_seconds),
        )

    @staticmethod
    def _recordUncertainAttempts(error: ModelGatewayError, attempts: int) -> None:
        # ModelGatewayError 兼容旧调用方，附加内部账单提示而不改变公开错误文案。
        error.uncertainBillableAttempts = attempts

    @staticmethod
    def _uncertainAttemptsFromError(error: ModelGatewayError) -> int:
        value = getattr(error, "uncertainBillableAttempts", 0)
        return value if isinstance(value, int) and value >= 0 else 0

    async def _backoff(
        self,
        policy: ModelPolicy,
        attemptIndex: int,
        retryAfter: str | None,
    ) -> None:
        delay: float | None = None
        if retryAfter is not None:
            try:
                delay = min(30.0, max(0.0, float(retryAfter)))
            except ValueError:
                delay = None
        if delay is None:
            jitterMultiplier = 0.5 + min(1.0, max(0.0, self._randomSource()))
            delay = policy.base_backoff_seconds * (2**attemptIndex) * jitterMultiplier
        await self._sleeper(delay)

    def _decodeBody(self, response: httpx.Response, apiKey: str) -> dict[str, Any]:
        return self._decodeRawBody(response.content, response.status_code, apiKey)

    def _decodeRawBody(
        self,
        rawBody: bytes,
        statusCode: int,
        apiKey: str,
    ) -> dict[str, Any]:
        try:
            body = json.loads(rawBody)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            if statusCode != 200:
                raise self._classifyError(statusCode, {}, apiKey) from error
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "provider returned non-JSON response",
                httpStatus=statusCode,
            ) from error
        if not isinstance(body, dict):
            if statusCode != 200:
                raise self._classifyError(statusCode, {}, apiKey)
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "provider response root must be an object",
                httpStatus=statusCode,
            )
        return body

    @staticmethod
    def _classifyError(
        statusCode: int,
        body: dict[str, Any],
        apiKey: str,
    ) -> ModelGatewayError:
        errorBody = body.get("error")
        if isinstance(errorBody, dict):
            rawProviderCode = str(errorBody.get("code") or errorBody.get("type") or "")
            providerMessage = str(errorBody.get("message") or "provider request failed")
        else:
            rawProviderCode = str(body.get("code") or body.get("type") or "")
            providerMessage = str(
                body.get("message") or body.get("detail") or "provider request failed"
            )
        providerCodeForClassification = StructuredProviderRestGateway._redactProviderMessage(
            rawProviderCode, apiKey
        )
        providerMessageForClassification = StructuredProviderRestGateway._redactProviderMessage(
            providerMessage,
            apiKey,
        )
        normalizedCode = providerCodeForClassification.lower()
        normalizedMessage = providerMessageForClassification.lower()
        if (
            statusCode == 401
            or "authentication" in normalizedCode
            or "invalid_api_key" in normalizedCode
        ):
            code = FailureCode.MODEL_AUTHENTICATION_ERROR
            retryable = False
        elif statusCode == 403 or "permission" in normalizedCode:
            code = FailureCode.MODEL_PERMISSION_ERROR
            retryable = False
        elif "insufficient_quota" in normalizedCode or "quota" in normalizedCode:
            code = FailureCode.MODEL_QUOTA_EXHAUSTED
            retryable = False
        elif statusCode == 429:
            code = FailureCode.MODEL_RATE_LIMITED
            retryable = True
        elif statusCode in {502, 503, 504} or "overloaded" in normalizedCode:
            code = FailureCode.MODEL_OVERLOADED
            retryable = True
        elif statusCode >= 500:
            code = FailureCode.MODEL_TRANSPORT_ERROR
            retryable = True
        elif "content" in normalizedCode and "filter" in normalizedCode + normalizedMessage:
            code = FailureCode.CONTENT_FILTERED
            retryable = False
        else:
            code = FailureCode.MODEL_REQUEST_INVALID
            retryable = False
        safeMessages = {
            FailureCode.MODEL_AUTHENTICATION_ERROR: "model provider rejected the API credential",
            FailureCode.MODEL_PERMISSION_ERROR: "model provider denied this request",
            FailureCode.MODEL_QUOTA_EXHAUSTED: "model provider quota is exhausted",
            FailureCode.MODEL_RATE_LIMITED: "model provider rate limit was reached",
            FailureCode.MODEL_OVERLOADED: "model provider is temporarily overloaded",
            FailureCode.MODEL_TRANSPORT_ERROR: "model provider returned a server error",
            FailureCode.CONTENT_FILTERED: "model provider filtered the request",
            FailureCode.MODEL_REQUEST_INVALID: "model provider rejected the request",
        }
        return ModelGatewayError(
            code,
            safeMessages[code],
            retryable=retryable,
            httpStatus=statusCode,
            providerCode=StructuredProviderRestGateway._sanitizeProviderCode(
                providerCodeForClassification
            ),
        )

    @staticmethod
    def _redactProviderMessage(message: str, apiKey: str) -> str:
        redacted = message
        for secret in (f"Bearer {apiKey}", apiKey):
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        return " ".join(redacted.split())[:300]

    @staticmethod
    def _sanitizeProviderCode(providerCode: str) -> str | None:
        """错误 code 只保留机器可识别字符，拒绝把供应商自由文本透传给前端。"""

        candidate = providerCode.strip()
        if not candidate or len(candidate) > 80:
            return None
        if any(
            not character.isascii() or not (character.isalnum() or character in "._:-")
            for character in candidate
        ):
            return None
        return candidate

    def _contentFromBody(self, body: dict[str, Any]) -> str:
        if self._provider == "openai":
            status = body.get("status")
            if status == "incomplete":
                reason = self._nestedString(body, "incomplete_details", "reason")
                code = (
                    FailureCode.CONTENT_FILTERED
                    if reason == "content_filter"
                    else FailureCode.MODEL_RESPONSE_INVALID
                )
                raise ModelGatewayError(
                    code, f"provider response was incomplete: {reason or 'unknown'}"
                )
            if status in {"failed", "cancelled"}:
                raise ModelGatewayError(
                    FailureCode.MODEL_RESPONSE_INVALID,
                    f"provider response status was {status}",
                )
            outputText = body.get("output_text")
            if isinstance(outputText, str) and outputText.strip():
                return outputText
            return self._textFromBlocks(body.get("output"), containerType="message")

        if self._provider == "anthropic":
            stopReason = body.get("stop_reason")
            if stopReason == "max_tokens":
                raise ModelGatewayError(
                    FailureCode.MODEL_RESPONSE_INVALID,
                    "provider truncated structured output at max_tokens",
                )
            if stopReason in {"refusal", "content_filter"}:
                code = (
                    FailureCode.REFUSAL if stopReason == "refusal" else FailureCode.CONTENT_FILTERED
                )
                raise ModelGatewayError(code, f"provider stopped with {stopReason}")
            if stopReason != "end_turn":
                raise ModelGatewayError(
                    FailureCode.MODEL_RESPONSE_INVALID,
                    "provider returned an unsupported stop reason",
                )
            return self._textFromBlocks(body.get("content"))

        if self._provider == "google":
            status = body.get("status")
            if status == "incomplete":
                finishReason = body.get("finish_reason")
                filteredReasons = {
                    "SAFETY",
                    "BLOCKLIST",
                    "PROHIBITED_CONTENT",
                    "IMAGE_SAFETY",
                    "RECITATION",
                }
                code = (
                    FailureCode.CONTENT_FILTERED
                    if finishReason in filteredReasons
                    else FailureCode.MODEL_RESPONSE_INVALID
                )
                raise ModelGatewayError(
                    code,
                    "provider returned an incomplete interaction",
                )
            if status in {"failed", "cancelled"}:
                raise ModelGatewayError(
                    FailureCode.MODEL_RESPONSE_INVALID,
                    f"provider interaction status was {status}",
                )
            steps = body.get("steps")
            if isinstance(steps, list):
                texts: list[str] = []
                for step in steps:
                    if not isinstance(step, dict) or step.get("type") != "model_output":
                        continue
                    texts.append(self._textFromBlocks(step.get("content")))
                joined = "".join(texts).strip()
                if joined:
                    return joined
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "model returned no structured content",
            )

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "provider response did not contain choices",
            )
        firstChoice = choices[0]
        if not isinstance(firstChoice, dict):
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "provider choice was not an object",
            )
        finishReason = firstChoice.get("finish_reason")
        if finishReason == "length":
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "provider truncated structured output at max_tokens",
            )
        if finishReason == "content_filter":
            raise ModelGatewayError(FailureCode.CONTENT_FILTERED, "provider filtered content")
        if finishReason == "insufficient_system_resource":
            raise ModelGatewayError(
                FailureCode.MODEL_OVERLOADED,
                "provider stopped because inference capacity was unavailable",
                retryable=True,
            )
        if finishReason != "stop":
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "provider returned an unsupported finish reason",
            )
        message = firstChoice.get("message")
        if not isinstance(message, dict):
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "provider response did not contain a message",
            )
        refusal = message.get("refusal")
        if isinstance(refusal, str) and refusal.strip():
            raise ModelGatewayError(FailureCode.REFUSAL, "model refused structured output")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "model returned no structured content",
            )
        return content

    @staticmethod
    def _textFromBlocks(value: object, *, containerType: str | None = None) -> str:
        if not isinstance(value, list):
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "model returned no structured content",
            )
        texts: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            if containerType is not None and item.get("type") != containerType:
                continue
            nested = item.get("content") if containerType is not None else None
            blocks = nested if isinstance(nested, list) else [item]
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") in {"refusal", "blocked"}:
                    raise ModelGatewayError(FailureCode.REFUSAL, "model refused structured output")
                text = block.get("text")
                if block.get("type") in {"text", "output_text"} and isinstance(text, str):
                    texts.append(text)
        joined = "".join(texts).strip()
        if not joined:
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "model returned no structured content",
            )
        return joined

    @staticmethod
    def _validateContent[ModelT: BaseModel](
        content: str,
        schema: type[ModelT],
        request: ModelRequest,
    ) -> ModelT:
        try:
            value = schema.model_validate_json(content)
        except ValidationError as error:
            details = error.errors(include_url=False, include_input=False)
            safeDetails = json.dumps(
                details,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )[:600]
            raise ModelGatewayError(
                FailureCode.SCHEMA_INVALID,
                f"structured output failed schema validation: {safeDetails}",
            ) from error
        validateEvidenceReferences(value, request.allowedEvidenceIds)
        validateAllowedAction(value, request.allowedActionValues)
        return value

    def _usageFromBody(self, body: dict[str, Any]) -> ModelUsage:
        usage = body.get("usage")
        if not isinstance(usage, dict):
            raise ModelGatewayError(
                FailureCode.MODEL_USAGE_MISSING,
                "provider response did not contain token usage",
            )
        if self._provider == "openai":
            promptTokens = self._requiredUsageInt(usage, "input_tokens")
            completionTokens = self._requiredUsageInt(usage, "output_tokens")
            cachedTokens = self._nestedUsageInt(usage, "input_tokens_details", "cached_tokens")
            self._validateReportedTotal(usage, promptTokens + completionTokens)
        elif self._provider == "anthropic":
            promptTokens = self._requiredUsageInt(usage, "input_tokens")
            cacheRead = self._optionalUsageInt(usage, "cache_read_input_tokens")
            cacheWrite = self._optionalUsageInt(usage, "cache_creation_input_tokens")
            promptTokens += cacheRead + cacheWrite
            completionTokens = self._requiredUsageInt(usage, "output_tokens")
            cachedTokens = cacheRead
        elif self._provider == "google":
            promptTokens = self._requiredUsageInt(usage, "total_input_tokens")
            visibleOutput = self._requiredUsageInt(usage, "total_output_tokens")
            thoughtTokens = self._optionalUsageInt(usage, "total_thought_tokens")
            completionTokens = visibleOutput + thoughtTokens
            cachedTokens = self._optionalUsageInt(usage, "total_cached_tokens")
            self._validateReportedTotal(usage, promptTokens + completionTokens)
        else:
            promptTokens = self._requiredUsageInt(usage, "prompt_tokens")
            completionTokens = self._requiredUsageInt(usage, "completion_tokens")
            if self._provider == "deepseek":
                cachedTokens = self._optionalUsageInt(usage, "prompt_cache_hit_tokens")
            elif self._provider == "moonshot":
                cachedTokens = self._optionalUsageInt(usage, "cached_tokens")
            else:
                cachedTokens = self._nestedUsageInt(
                    usage,
                    "prompt_tokens_details",
                    "cached_tokens",
                )
            self._validateReportedTotal(usage, promptTokens + completionTokens)
        if cachedTokens > promptTokens:
            raise ModelGatewayError(
                FailureCode.MODEL_USAGE_MISSING,
                "provider cached token count exceeded input token count",
            )
        return ModelUsage(
            promptTokens=promptTokens,
            completionTokens=completionTokens,
            cachedTokens=cachedTokens,
        )

    def _usageFromBillableBody(self, body: dict[str, Any]) -> ModelUsage:
        """成功 HTTP 响应缺少可信 usage 时，显式标记一次不确定计费尝试。"""

        try:
            return self._usageFromBody(body)
        except ModelGatewayError as error:
            if error.code == FailureCode.MODEL_USAGE_MISSING:
                self._recordUncertainAttempts(error, 1)
            raise

    @staticmethod
    def _requiredUsageInt(usage: dict[str, Any], key: str) -> int:
        value = usage.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ModelGatewayError(
                FailureCode.MODEL_USAGE_MISSING,
                f"provider usage field {key} was missing or invalid",
            )
        return value

    @staticmethod
    def _optionalUsageInt(usage: dict[str, Any], key: str) -> int:
        value = usage.get(key, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ModelGatewayError(
                FailureCode.MODEL_USAGE_MISSING,
                f"provider usage field {key} was invalid",
            )
        return value

    @classmethod
    def _nestedUsageInt(cls, usage: dict[str, Any], parent: str, key: str) -> int:
        details = usage.get(parent)
        if details is None:
            return 0
        if not isinstance(details, dict):
            raise ModelGatewayError(
                FailureCode.MODEL_USAGE_MISSING,
                f"provider usage field {parent} was invalid",
            )
        return cls._optionalUsageInt(details, key)

    @staticmethod
    def _validateReportedTotal(usage: dict[str, Any], expectedTotal: int) -> None:
        totalKey = "total_tokens"
        if totalKey not in usage:
            return
        total = StructuredProviderRestGateway._requiredUsageInt(usage, totalKey)
        if total != expectedTotal:
            raise ModelGatewayError(
                FailureCode.MODEL_USAGE_MISSING,
                "provider total token count did not match input plus output tokens",
            )

    @staticmethod
    def _nestedString(body: dict[str, Any], parent: str, key: str) -> str:
        value = body.get(parent)
        nested = value.get(key) if isinstance(value, dict) else None
        return nested if isinstance(nested, str) else ""

    @staticmethod
    def _schemaName(schema: type[BaseModel]) -> str:
        return f"eventshock_{schema.__name__.lower()}"[:64]

    @staticmethod
    def _googleThinkingLevel(reasoningEffort: str | None) -> str:
        if reasoningEffort in {"minimal", "low", "medium", "high"}:
            return reasoningEffort
        if reasoningEffort in {"max", "xhigh"}:
            return "high"
        return "medium"

    @staticmethod
    def _deepSeekEffort(reasoningEffort: str) -> str:
        return "max" if reasoningEffort in {"max", "xhigh"} else "high"

    @staticmethod
    def _anthropicThinkingBudget(maxTokens: int) -> int:
        # Anthropic 要求 budget_tokens >= 1024 且严格小于 max_tokens。
        return min(16_000, max(1_024, maxTokens // 2), maxTokens - 1)

    @staticmethod
    def _kimiEffort(thinkingEnabled: bool, reasoningEffort: str | None) -> str:
        if not thinkingEnabled:
            return "low"
        if reasoningEffort in {"max", "xhigh"}:
            return "max"
        if reasoningEffort == "low":
            return "low"
        return "high"

    @staticmethod
    def _isRepairable(error: ModelGatewayError) -> bool:
        return error.code in {
            FailureCode.SCHEMA_INVALID,
            FailureCode.EVIDENCE_ID_UNKNOWN,
            FailureCode.ACTION_NOT_ALLOWED,
            FailureCode.MODEL_RESPONSE_INVALID,
        }

    def _elapsedMilliseconds(self, startedAt: float) -> float:
        return max(0.0, round((self._clock() - startedAt) * 1_000, 3))


class OpenAIRestGateway(StructuredProviderRestGateway):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("openai", **kwargs)


class AnthropicRestGateway(StructuredProviderRestGateway):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("anthropic", **kwargs)


class GeminiRestGateway(StructuredProviderRestGateway):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("google", **kwargs)


class DeepSeekRestGateway(StructuredProviderRestGateway):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("deepseek", **kwargs)


class QwenRestGateway(StructuredProviderRestGateway):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("alibaba", **kwargs)


class KimiRestGateway(StructuredProviderRestGateway):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("moonshot", **kwargs)


class ProviderGatewayRouter:
    """按 ``ModelRequest.provider`` 分发，且只实例化 allowlist 内的网关。"""

    def __init__(
        self,
        *,
        cache: ImmutableDecisionCache | None = None,
        transportByProvider: Mapping[str, httpx.AsyncBaseTransport] | None = None,
    ) -> None:
        self._cache = cache
        self._transportByProvider = dict(transportByProvider or {})
        unknownProviders = set(self._transportByProvider) - {
            "zhipu",
            *NON_ZHIPU_PROVIDERS,
        }
        if unknownProviders:
            raise ValueError(
                f"unsupported provider transports: {', '.join(sorted(unknownProviders))}"
            )
        self._gateways: dict[str, Any] = {}

    async def generateStructured[ModelT: BaseModel](
        self,
        request: ModelRequest,
        schema: type[ModelT],
        policy: ModelPolicy,
    ) -> ModelResult[ModelT]:
        gateway = self._gateways.get(request.provider)
        if gateway is None:
            gateway = self._createGateway(request.provider)
            self._gateways[request.provider] = gateway
        return await gateway.generateStructured(request, schema, policy)

    async def aclose(self) -> None:
        gateways = tuple(self._gateways.values())
        self._gateways.clear()
        for gateway in gateways:
            await gateway.aclose()

    def _createGateway(self, provider: str) -> Any:
        transport = self._transportByProvider.get(provider)
        kwargs = {"cache": self._cache, "transport": transport}
        factories: dict[str, type[Any]] = {
            "zhipu": ZhipuRestGateway,
            "openai": OpenAIRestGateway,
            "anthropic": AnthropicRestGateway,
            "google": GeminiRestGateway,
            "deepseek": DeepSeekRestGateway,
            "alibaba": QwenRestGateway,
            "moonshot": KimiRestGateway,
        }
        factory = factories.get(provider)
        if factory is None:
            raise ModelGatewayError(
                FailureCode.MODEL_REQUEST_INVALID,
                f"unsupported model provider: {provider}",
            )
        return factory(**kwargs)
