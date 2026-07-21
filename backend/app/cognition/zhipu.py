"""智谱 Chat Completions 的异步、严格结构化 REST 适配器。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
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
    validateAllowedAction,
    validateEvidenceReferences,
)
from backend.app.cognition.models import ActionPreference
from backend.app.cognition.prompts import buildRepairInstruction

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
        failureCodes: list[FailureCode] = []
        repairUsed = False
        lastError: ModelGatewayError | None = None
        rawContent = ""

        try:
            body, rawBody, attempts = await self._postWithRetry(
                payload=payload,
                request=request,
                policy=policy,
            )
            totalAttempts += attempts
            callUsage = self._usageFromBody(body)
            totalUsage = totalUsage.plus(callUsage)
            rawContent = self._contentFromBody(body)
            data = self._validateContent(
                rawContent,
                schema,
                request.allowedEvidenceIds,
                request.allowedActionValues,
            )
            responseHash = hashlib.sha256(rawBody).hexdigest()
        except ModelGatewayError as error:
            totalAttempts += error.attempts
            lastError = error
            failureCodes.append(error.code)
            data = None
            responseHash = ""

        if data is None and lastError is not None and self._isRepairable(lastError):
            repairUsed = True
            repairPayload = self._buildRepairPayload(
                request=request,
                invalidContent=rawContent,
                error=lastError,
            )
            try:
                body, rawBody, attempts = await self._postWithRetry(
                    payload=repairPayload,
                    request=request,
                    policy=policy,
                )
                totalAttempts += attempts
                totalUsage = totalUsage.plus(self._usageFromBody(body))
                repairedContent = self._contentFromBody(body)
                data = self._validateContent(
                    repairedContent,
                    schema,
                    request.allowedEvidenceIds,
                    request.allowedActionValues,
                )
                responseHash = hashlib.sha256(rawBody).hexdigest()
                lastError = None
            except ModelGatewayError as error:
                totalAttempts += error.attempts
                lastError = error
                failureCodes.append(error.code)

        if data is None:
            if lastError is None:
                lastError = ModelGatewayError(
                    FailureCode.MODEL_RESPONSE_INVALID,
                    "model did not produce a validated result",
                )
            if not policy.allow_rule_fallback:
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
            "stream": False,
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
        return payload

    @staticmethod
    def _buildRepairPayload(
        *,
        request: ModelRequest,
        invalidContent: str,
        error: ModelGatewayError,
    ) -> dict[str, Any]:
        payload = ZhipuRestGateway._buildPayload(request)
        payload["messages"] = [
            {"role": "system", "content": request.systemPrompt},
            {"role": "user", "content": request.userContent},
            {
                "role": "assistant",
                "content": invalidContent[:12_000] or "{}",
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
    ) -> tuple[dict[str, Any], bytes, int]:
        lastError: ModelGatewayError | None = None
        for attemptIndex in range(policy.max_transport_attempts):
            attemptNumber = attemptIndex + 1
            try:
                response = await self._client.post(
                    ZHIPU_CHAT_COMPLETIONS_URL,
                    headers={
                        "Authorization": f"Bearer {request.apiKey}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                    timeout=policy.timeout_seconds,
                    follow_redirects=False,
                )
            except httpx.TimeoutException as error:
                lastError = ModelGatewayError(
                    FailureCode.MODEL_TIMEOUT,
                    "model request timed out",
                    retryable=True,
                    attempts=attemptNumber,
                )
                if attemptNumber < policy.max_transport_attempts:
                    await self._backoff(policy, attemptIndex, None)
                    continue
                raise lastError from error
            except httpx.TransportError as error:
                lastError = ModelGatewayError(
                    FailureCode.MODEL_TRANSPORT_ERROR,
                    "model transport failed",
                    retryable=True,
                    attempts=attemptNumber,
                )
                if attemptNumber < policy.max_transport_attempts:
                    await self._backoff(policy, attemptIndex, None)
                    continue
                raise lastError from error

            try:
                body = self._decodeBody(response)
            except ModelGatewayError as error:
                error.attempts = attemptNumber
                if error.retryable and attemptNumber < policy.max_transport_attempts:
                    await self._backoff(
                        policy,
                        attemptIndex,
                        response.headers.get("Retry-After"),
                    )
                    continue
                raise
            if response.status_code == 200:
                return body, response.content, attemptNumber

            lastError = self._classifyError(response.status_code, body)
            lastError.attempts = attemptNumber
            if lastError.retryable and attemptNumber < policy.max_transport_attempts:
                await self._backoff(
                    policy,
                    attemptIndex,
                    response.headers.get("Retry-After"),
                )
                continue
            raise lastError

        if lastError is None:
            lastError = ModelGatewayError(
                FailureCode.MODEL_TRANSPORT_ERROR,
                "model request failed without a response",
            )
        raise lastError

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

    @staticmethod
    def _decodeBody(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except json.JSONDecodeError as error:
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "provider returned non-JSON response",
                retryable=response.status_code >= 500,
                httpStatus=response.status_code,
            ) from error
        if not isinstance(body, dict):
            raise ModelGatewayError(
                FailureCode.MODEL_RESPONSE_INVALID,
                "provider response root must be an object",
                retryable=response.status_code >= 500,
                httpStatus=response.status_code,
            )
        return body

    @staticmethod
    def _classifyError(statusCode: int, body: dict[str, Any]) -> ModelGatewayError:
        errorBody = body.get("error")
        providerCode = str(errorBody.get("code", "")) if isinstance(errorBody, dict) else ""
        providerMessage = (
            str(errorBody.get("message", "provider request failed"))
            if isinstance(errorBody, dict)
            else "provider request failed"
        )
        safeMessage = " ".join(providerMessage.split())[:300]

        if providerCode in {"1000", "1001", "1003", "1005"} or statusCode == 401:
            code = FailureCode.MODEL_AUTHENTICATION_ERROR
            retryable = False
        elif providerCode in {"1220", "1311"} or statusCode == 403:
            code = FailureCode.MODEL_PERMISSION_ERROR
            retryable = False
        elif providerCode == "1302":
            code = FailureCode.MODEL_RATE_LIMITED
            retryable = True
        elif providerCode == "1305" or statusCode == 503:
            code = FailureCode.MODEL_OVERLOADED
            retryable = True
        elif providerCode in {
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
        elif providerCode == "1301":
            code = FailureCode.CONTENT_FILTERED
            retryable = False
        elif statusCode == 429:
            code = FailureCode.MODEL_RATE_LIMITED
            retryable = providerCode in RETRYABLE_PROVIDER_CODES or not providerCode
        elif statusCode >= 500:
            code = FailureCode.MODEL_TRANSPORT_ERROR
            retryable = True
        else:
            code = FailureCode.MODEL_REQUEST_INVALID
            retryable = False
        return ModelGatewayError(
            code,
            safeMessage,
            retryable=retryable,
            httpStatus=statusCode,
            providerCode=providerCode or None,
        )

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
        message = firstChoice.get("message") if isinstance(firstChoice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ModelGatewayError(FailureCode.REFUSAL, "model returned no structured content")
        return content

    @staticmethod
    def _validateContent[ModelT: BaseModel](
        content: str,
        schema: type[ModelT],
        allowedEvidenceIds: frozenset[str],
        allowedActionValues: frozenset[str],
    ) -> ModelT:
        try:
            value = schema.model_validate_json(content)
        except ValidationError as error:
            details = error.errors(include_url=False, include_input=False)
            safeDetails = json.dumps(details, ensure_ascii=False, separators=(",", ":"))[:600]
            raise ModelGatewayError(
                FailureCode.SCHEMA_INVALID,
                f"structured output failed schema validation: {safeDetails}",
            ) from error
        validateEvidenceReferences(value, allowedEvidenceIds)
        validateAllowedAction(value, allowedActionValues)
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
            FailureCode.REFUSAL,
        }

    def _elapsedMilliseconds(self, startedAt: float) -> float:
        return max(0.0, round((self._clock() - startedAt) * 1_000, 3))
