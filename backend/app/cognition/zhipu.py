"""智谱 Chat Completions 的异步、严格结构化 REST 适配器。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.cognition.cache import (
    ImmutableDecisionCache,
    buildDecisionCacheKey,
    canonicalModelBytes,
)
from backend.app.cognition.catalog import (
    ZHIPU_CHAT_COMPLETIONS_URL,
    ZHIPU_PROVIDER,
    getZhipuModel,
)
from backend.app.cognition.gateway import (
    FailureCode,
    ModelGatewayError,
    ModelPolicy,
    ModelRequest,
    ModelResult,
    ModelUsage,
    buildRuleFallback,
    validateAdvancedModelParameters,
    validateAllowedAction,
    validateEvidenceReferences,
)
from backend.app.cognition.models import ActionPreference
from backend.app.cognition.prompts import (
    MODEL_OUTPUT_VALIDATOR,
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
from backend.app.security import UnsafeModelOutputError

RETRYABLE_PROVIDER_CODES = frozenset({"1302", "1305"})


class ZhipuRestGateway:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        cache: ImmutableDecisionCache | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        randomSource: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if transport is not None and client is not None:
            raise ValueError("provide transport or client, not both")
        self._client = client or httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
        )
        self._ownsClient = client is None
        self._cache = cache
        self._sleeper = sleeper
        self._randomSource = randomSource
        self._clock = clock

    async def __aenter__(self) -> ZhipuRestGateway:
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

        payload = self._buildPayload(request)
        totalUsage = ModelUsage()
        totalAttempts = 0
        uncertainBillableAttempts = 0
        failureCodes: list[FailureCode] = []
        repairUsed = False
        lastError: ModelGatewayError | None = None
        rawContent = ""

        try:
            body, rawBody, attempts, uncertainAttempts = await self._postWithRetry(
                payload=payload,
                request=request,
                policy=policy,
                repair=False,
            )
            totalAttempts += attempts
            uncertainBillableAttempts += uncertainAttempts
            # 200 响应即可能产生费用；先登记 usage，再解析内容或执行语义校验。
            callUsage = self._usageFromBillableBody(body)
            totalUsage = totalUsage.plus(callUsage)
            rawContent = self._contentFromBody(body)
            await emitModelStreamProgress(
                request.streamObserver,
                ModelStreamProgress(
                    stage=ModelStreamStage.VALIDATING,
                    elapsedMs=self._elapsedMilliseconds(startedAt),
                    attempt=attempts,
                ),
            )
            data = self._validateContent(
                rawContent,
                schema,
                request,
            )
            responseHash = hashlib.sha256(rawBody).hexdigest()
        except ModelGatewayError as error:
            totalAttempts += error.attempts
            uncertainBillableAttempts += error.uncertainBillableAttempts
            lastError = error
            failureCodes.append(error.code)
            data = None
            responseHash = ""

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
            repairPayload = self._buildRepairPayload(
                request=request,
                invalidContent=rawContent,
                error=lastError,
            )
            try:
                body, rawBody, attempts, uncertainAttempts = await self._postWithRetry(
                    payload=repairPayload,
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
                data = self._validateContent(
                    repairedContent,
                    schema,
                    request,
                )
                responseHash = hashlib.sha256(rawBody).hexdigest()
                lastError = None
            except ModelGatewayError as error:
                totalAttempts += error.attempts
                uncertainBillableAttempts += error.uncertainBillableAttempts
                lastError = error
                failureCodes.append(error.code)

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
            fallbackBytes = canonicalModelBytes(data)
            responseHash = hashlib.sha256(fallbackBytes).hexdigest()
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
                uncertainBillableAttempts=uncertainBillableAttempts,
                failureCodes=tuple(failureCodes),
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
            uncertainBillableAttempts=uncertainBillableAttempts,
            failureCodes=tuple(failureCodes),
        )

    def _validateRequest(self, request: ModelRequest) -> None:
        if request.provider != ZHIPU_PROVIDER:
            raise ValueError("ZhipuRestGateway only accepts the zhipu provider")
        descriptor = getZhipuModel(request.model)
        if request.samplingConfig.max_tokens > descriptor.max_output_tokens:
            raise ValueError("max_tokens exceeds the selected model limit")
        if request.samplingConfig.thinking_enabled and not descriptor.supports_thinking:
            raise ValueError("the selected model does not support thinking")
        validateAdvancedModelParameters(
            request.provider,
            request.samplingConfig.advancedParameters(),
        )
        if request.samplingConfig.reasoning_effort is not None and request.model != "glm-5.2":
            raise ValueError("reasoning_effort is only supported by glm-5.2")
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
        if hashlib.sha256(request.systemPrompt.encode("utf-8")).hexdigest() != request.promptHash:
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
            tenantHash=hashlib.sha256(request.userId.encode("utf-8")).hexdigest(),
            provider=request.provider,
            model=request.model,
            promptHash=request.promptHash,
            schemaVersion=request.schemaVersion,
            agentConfigHash=request.agentConfigHash,
            observationHash=request.observationHash,
            samplingConfig=request.samplingConfig.model_dump(mode="json"),
        )

    @staticmethod
    def _buildPayload(request: ModelRequest) -> dict[str, Any]:
        descriptor = getZhipuModel(request.model)
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.systemPrompt},
                {"role": "user", "content": request.userContent},
            ],
            "stream": request.streamResponse,
            "do_sample": request.samplingConfig.do_sample,
            "max_tokens": request.samplingConfig.max_tokens,
            "response_format": {"type": "json_object"},
            "request_id": request.requestId,
            "user_id": request.userId,
        }
        # 智谱仅为 GLM-4.5 及以上模型声明 thinking 参数。对不支持该参数的
        # 旧免费模型完全省略字段，避免“显式关闭”仍被供应商判定为非法参数。
        if descriptor.supports_thinking:
            payload["thinking"] = {
                "type": "enabled" if request.samplingConfig.thinking_enabled else "disabled"
            }
        if request.samplingConfig.reasoning_effort is not None:
            payload["reasoning_effort"] = request.samplingConfig.reasoning_effort
        if request.samplingConfig.temperature is not None:
            payload["temperature"] = request.samplingConfig.temperature
        if request.samplingConfig.top_p is not None:
            payload["top_p"] = request.samplingConfig.top_p
        return payload

    @staticmethod
    def _buildRepairPayload(
        *,
        request: ModelRequest,
        invalidContent: str,
        error: ModelGatewayError,
    ) -> dict[str, Any]:
        payload = ZhipuRestGateway._buildPayload(request)
        descriptor = getZhipuModel(request.model)
        # 修复轮必须最大化严格 JSON 的稳定性，即使调用方错误地为首轮打开了
        # thinking，也不能把该偏好继续传进结构修复请求。
        if descriptor.supports_thinking:
            payload["thinking"] = {"type": "disabled"}
        payload.pop("reasoning_effort", None)
        # 修复轮已经携带上一轮的有界无效 JSON；为提高一次修复成功率并避免
        # 再次处理半截结构，按“结构化 JSON 不适合边生成边展示”的例外非流式接收。
        payload["stream"] = False
        # repair 是一次新的供应商调用，必须使用独立的请求标识。只发送随机 ID，
        # 不把原始应用请求 ID 拼接进去，避免供应商追踪记录混淆两次计费请求。
        payload["request_id"] = ZhipuRestGateway._newRepairRequestId(request.requestId)
        payload["messages"] = [
            {"role": "system", "content": request.systemPrompt},
            {"role": "user", "content": request.userContent},
            {
                "role": "assistant",
                "content": encodeUntrustedPromptText(invalidContent[:12_000]) or "{}",
            },
            {
                "role": "user",
                "content": buildRepairInstruction(
                    validationCode=error.code.value,
                    validationDetail=str(error),
                    allowedEvidenceIds=request.allowedEvidenceIds,
                ),
            },
        ]
        return payload

    async def _postWithRetry(
        self,
        *,
        payload: dict[str, Any],
        request: ModelRequest,
        policy: ModelPolicy,
        repair: bool,
    ) -> tuple[dict[str, Any], bytes, int, int]:
        lastError: ModelGatewayError | None = None
        uncertainBillableAttempts = 0
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
                        ZHIPU_CHAT_COMPLETIONS_URL,
                        headers={
                            "Authorization": f"Bearer {request.apiKey}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        json=payload,
                        timeout=self._httpxTimeout(policy),
                        follow_redirects=False,
                    )
                    statusCode = response.status_code
                    responseHeaders = response.headers
                    body = self._decodeBody(response, request.apiKey)
                    rawBody = response.content
            except (httpx.TimeoutException, TimeoutError) as error:
                uncertainBillableAttempts += 1
                lastError = ModelGatewayError(
                    FailureCode.MODEL_TIMEOUT,
                    "model request timed out",
                    retryable=True,
                    attempts=attemptNumber,
                    uncertainBillableAttempts=uncertainBillableAttempts,
                )
                if attemptNumber < policy.max_transport_attempts:
                    await self._backoff(policy, attemptIndex, None)
                    continue
                raise lastError from error
            except httpx.TransportError as error:
                uncertainBillableAttempts += 1
                lastError = ModelGatewayError(
                    FailureCode.MODEL_TRANSPORT_ERROR,
                    "model transport failed",
                    retryable=True,
                    attempts=attemptNumber,
                    uncertainBillableAttempts=uncertainBillableAttempts,
                )
                if attemptNumber < policy.max_transport_attempts:
                    await self._backoff(policy, attemptIndex, None)
                    continue
                raise lastError from error
            except ModelGatewayError as error:
                if error.httpStatus == 200:
                    uncertainBillableAttempts += 1
                error.attempts = attemptNumber
                error.uncertainBillableAttempts = uncertainBillableAttempts
                if error.retryable and attemptNumber < policy.max_transport_attempts:
                    await self._backoff(policy, attemptIndex, None)
                    continue
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
                    # 200 但无法解析 usage 时，账单状态仍未知，必须保留单次响应上界。
                    uncertainBillableAttempts += 1
                error.attempts = attemptNumber
                error.uncertainBillableAttempts = uncertainBillableAttempts
                if error.retryable and attemptNumber < policy.max_transport_attempts:
                    await self._backoff(
                        policy,
                        attemptIndex,
                        responseHeaders.get("Retry-After"),
                    )
                    continue
                raise
            if statusCode == 200:
                return body, rawBody, attemptNumber, uncertainBillableAttempts

            lastError = self._classifyError(statusCode, body, request.apiKey)
            lastError.attempts = attemptNumber
            lastError.uncertainBillableAttempts = uncertainBillableAttempts
            if lastError.retryable and attemptNumber < policy.max_transport_attempts:
                await self._backoff(
                    policy,
                    attemptIndex,
                    responseHeaders.get("Retry-After"),
                )
                continue
            raise lastError

        if lastError is None:
            lastError = ModelGatewayError(
                FailureCode.MODEL_TRANSPORT_ERROR,
                "model request failed without a response",
            )
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
        """消费智谱 SSE 并仅公开安全进度；完整 JSON 在流结束后统一校验。"""

        accumulator = ProviderStreamAccumulator("zhipu")
        startedAt = self._clock()
        headers = {
            "Authorization": f"Bearer {request.apiKey}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        async with asyncio.timeout(policy.timeout_seconds):
            async with self._client.stream(
                "POST",
                ZHIPU_CHAT_COMPLETIONS_URL,
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

    @classmethod
    def _decodeBody(cls, response: httpx.Response, apiKey: str) -> dict[str, Any]:
        return cls._decodeRawBody(response.content, response.status_code, apiKey)

    @classmethod
    def _decodeRawBody(
        cls,
        rawBody: bytes,
        statusCode: int,
        apiKey: str,
    ) -> dict[str, Any]:
        try:
            body = json.loads(rawBody)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            if statusCode != 200:
                # CDN、WAF 和供应商网关可能以 HTML 返回认证、限流或服务错误。
                # 此时只信任 HTTP 状态，绝不把不可信正文写入异常或响应。
                raise cls._classifyError(statusCode, {}, apiKey) from error
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "provider returned non-JSON response",
                httpStatus=statusCode,
            ) from error
        if not isinstance(body, dict):
            if statusCode != 200:
                raise cls._classifyError(statusCode, {}, apiKey)
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
        apiKey: str = "",
    ) -> ModelGatewayError:
        errorBody = body.get("error")
        rawProviderCode = str(errorBody.get("code", "")) if isinstance(errorBody, dict) else ""
        providerCodeForClassification = rawProviderCode
        for secret in (f"Bearer {apiKey}", apiKey):
            if secret:
                providerCodeForClassification = providerCodeForClassification.replace(
                    secret,
                    "[REDACTED]",
                )
        providerCode = ZhipuRestGateway._sanitizeProviderCode(providerCodeForClassification)

        if providerCodeForClassification in {"1000", "1001", "1003", "1005"} or statusCode == 401:
            code = FailureCode.MODEL_AUTHENTICATION_ERROR
            retryable = False
        elif providerCodeForClassification in {"1220", "1311"} or statusCode == 403:
            code = FailureCode.MODEL_PERMISSION_ERROR
            retryable = False
        elif providerCodeForClassification == "1302":
            code = FailureCode.MODEL_RATE_LIMITED
            retryable = True
        elif providerCodeForClassification == "1305" or statusCode == 503:
            code = FailureCode.MODEL_OVERLOADED
            retryable = True
        elif providerCodeForClassification in {
            "1113",
            "1308",
            "1309",
            "1310",
            "1313",
            "1314",
            "1315",
            "1316",
            "1317",
            "1318",
            "1319",
            "1320",
            "1321",
        }:
            code = FailureCode.MODEL_QUOTA_EXHAUSTED
            retryable = False
        elif providerCodeForClassification == "1301":
            code = FailureCode.CONTENT_FILTERED
            retryable = False
        elif statusCode == 429:
            code = FailureCode.MODEL_RATE_LIMITED
            retryable = (
                providerCodeForClassification in RETRYABLE_PROVIDER_CODES
                or not providerCodeForClassification
            )
        elif statusCode >= 500:
            code = FailureCode.MODEL_TRANSPORT_ERROR
            retryable = True
        else:
            code = FailureCode.MODEL_REQUEST_INVALID
            retryable = False
        safeMessages = {
            FailureCode.MODEL_AUTHENTICATION_ERROR: "model provider rejected the API credential",
            FailureCode.MODEL_PERMISSION_ERROR: "model provider denied this request",
            FailureCode.MODEL_RATE_LIMITED: "model provider rate limit was reached",
            FailureCode.MODEL_OVERLOADED: "model provider is temporarily overloaded",
            FailureCode.MODEL_QUOTA_EXHAUSTED: "model provider quota is exhausted",
            FailureCode.CONTENT_FILTERED: "model provider filtered the request",
            FailureCode.MODEL_TRANSPORT_ERROR: "model provider returned a server error",
            FailureCode.MODEL_REQUEST_INVALID: "model provider rejected the request",
        }
        return ModelGatewayError(
            code,
            safeMessages[code],
            retryable=retryable,
            httpStatus=statusCode,
            providerCode=providerCode,
        )

    @staticmethod
    def _sanitizeProviderCode(providerCode: str) -> str | None:
        candidate = providerCode.strip()
        if not candidate or len(candidate) > 80:
            return None
        if any(
            not character.isascii() or not (character.isalnum() or character in "._:-")
            for character in candidate
        ):
            return None
        return candidate

    @staticmethod
    def _contentFromBody(body: dict[str, Any]) -> str:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            if body.get("content_filter"):
                raise ModelGatewayError(
                    FailureCode.CONTENT_FILTERED,
                    "provider returned content filtering metadata without a choice",
                )
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
        if finishReason in {"sensitive", "safety"}:
            raise ModelGatewayError(FailureCode.CONTENT_FILTERED, "provider filtered content")
        if finishReason == "network_error":
            raise ModelGatewayError(
                FailureCode.MODEL_TRANSPORT_ERROR,
                "provider stopped because generation transport failed",
                retryable=True,
            )
        if finishReason != "stop":
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "provider returned an unsupported finish reason",
            )
        message = firstChoice.get("message") if isinstance(firstChoice, dict) else None
        refusal = message.get("refusal") if isinstance(message, dict) else None
        if isinstance(refusal, str) and refusal.strip():
            raise ModelGatewayError(FailureCode.REFUSAL, "model refused structured output")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "model returned no structured content",
            )
        return content

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
        try:
            MODEL_OUTPUT_VALIDATOR.validateModelOutput(
                value,
                protectedSecrets=(request.apiKey,),
            )
        except UnsafeModelOutputError as error:
            raise ModelGatewayError(
                FailureCode.PROMPT_DISCLOSURE_BLOCKED,
                "model output failed deterministic disclosure safety validation",
                safeDiagnostics=error.auditMetadata(),
            ) from error
        return value

    @staticmethod
    def _usageFromBody(body: dict[str, Any]) -> ModelUsage:
        usage = body.get("usage")
        if not isinstance(usage, dict):
            raise ModelGatewayError(
                FailureCode.MODEL_USAGE_MISSING,
                "provider response did not contain token usage",
            )
        promptTokens = ZhipuRestGateway._requiredUsageInt(usage, "prompt_tokens")
        completionTokens = ZhipuRestGateway._requiredUsageInt(usage, "completion_tokens")
        totalTokens = ZhipuRestGateway._requiredUsageInt(usage, "total_tokens")
        if totalTokens != promptTokens + completionTokens:
            raise ModelGatewayError(
                FailureCode.MODEL_USAGE_MISSING,
                "provider total_tokens did not equal prompt_tokens plus completion_tokens",
            )
        promptDetails = usage.get("prompt_tokens_details")
        cachedTokens = (
            ZhipuRestGateway._safeInt(promptDetails.get("cached_tokens"))
            if isinstance(promptDetails, dict)
            else 0
        )
        if cachedTokens > promptTokens:
            raise ModelGatewayError(
                FailureCode.MODEL_USAGE_MISSING,
                "provider cached_tokens exceeded prompt_tokens",
            )
        return ModelUsage(
            promptTokens=promptTokens,
            completionTokens=completionTokens,
            cachedTokens=cachedTokens,
        )

    @staticmethod
    def _usageFromBillableBody(body: dict[str, Any]) -> ModelUsage:
        """HTTP 200 缺失可信 usage 时必须保留一次未知计费尝试。"""

        try:
            return ZhipuRestGateway._usageFromBody(body)
        except ModelGatewayError as error:
            if error.code == FailureCode.MODEL_USAGE_MISSING:
                error.uncertainBillableAttempts = max(1, error.uncertainBillableAttempts)
            raise

    @staticmethod
    def _newRepairRequestId(originalRequestId: str) -> str:
        # 官方限制为 6–64 字符。随机 repair ID 与原始应用 ID 解耦，且循环保证
        # 即使调用方恰好使用同形字符串也绝不复用同一标识。
        while True:
            candidate = f"repair-{uuid.uuid4().hex}"
            if candidate != originalRequestId:
                return candidate

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
    def _safeInt(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

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
