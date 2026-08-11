from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace

import httpx
import pytest

from backend.app.cognition import (
    EVENT_EXTRACTION_PROMPT,
    AnthropicRestGateway,
    DeepSeekRestGateway,
    EventExtractionResult,
    FailureCode,
    GeminiRestGateway,
    ImmutableDecisionCache,
    KimiRestGateway,
    ModelGatewayError,
    ModelPolicy,
    ModelRequest,
    OpenAIRestGateway,
    QwenRestGateway,
    ResultInterpretationAnswer,
    SamplingConfig,
    canonicalHash,
)
from backend.app.cognition.catalog import getProvider
from backend.app.cognition.provider_gateways import StructuredProviderRestGateway

API_KEY = "provider-test-secret-key-8842"
STRUCTURED_PAYLOAD = {
    "schema_version": "event_extraction_v1.0.0",
    "claims": [],
    "source_summary": "The connectivity probe contains no event claim.",
    "abstain_reason": "No event fact was supplied.",
}

GatewayFactory = Callable[..., StructuredProviderRestGateway]


def makeRequest(
    provider: str,
    model: str,
    *,
    samplingConfig: SamplingConfig | None = None,
) -> ModelRequest:
    observation = {"workflow": "provider-gateway-test", "provider": provider}
    return ModelRequest(
        provider=provider,
        model=model,
        requestId="request-provider-001",
        userId="anonymous-provider-session-001",
        systemPrompt=EVENT_EXTRACTION_PROMPT.systemPrompt,
        userContent="Return JSON for the source-bound connectivity probe.",
        promptHash=EVENT_EXTRACTION_PROMPT.promptHash,
        schemaVersion=EVENT_EXTRACTION_PROMPT.schemaVersion,
        agentConfigHash=canonicalHash({"model": model}),
        observationHash=canonicalHash(observation),
        allowedEvidenceIds=frozenset({"connection_probe"}),
        samplingConfig=samplingConfig or SamplingConfig(max_tokens=2_048),
        apiKey=API_KEY,
    )


def providerResponse(provider: str) -> dict:
    content = json.dumps(STRUCTURED_PAYLOAD, separators=(",", ":"))
    if provider == "openai":
        return {
            "id": "resp-test",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": content}],
                }
            ],
            "usage": {
                "input_tokens": 11,
                "output_tokens": 7,
                "total_tokens": 18,
                "input_tokens_details": {"cached_tokens": 2},
            },
        }
    if provider == "anthropic":
        return {
            "id": "msg-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": content}],
            "usage": {
                "input_tokens": 8,
                "cache_read_input_tokens": 2,
                "cache_creation_input_tokens": 1,
                "output_tokens": 7,
            },
        }
    if provider == "google":
        return {
            "id": "interaction-test",
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": content}],
                }
            ],
            "usage": {
                "total_input_tokens": 11,
                "total_output_tokens": 5,
                "total_thought_tokens": 2,
                "total_cached_tokens": 2,
                "total_tokens": 18,
            },
        }
    response = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
            "prompt_tokens_details": {"cached_tokens": 2},
        },
    }
    if provider == "moonshot":
        response["usage"].pop("prompt_tokens_details")
        response["usage"]["cached_tokens"] = 2
    elif provider == "deepseek":
        response["usage"].pop("prompt_tokens_details")
        response["usage"]["prompt_cache_hit_tokens"] = 2
    return response


PROVIDER_CASES = (
    ("openai", "gpt-5.6-luna", OpenAIRestGateway),
    ("anthropic", "claude-sonnet-5", AnthropicRestGateway),
    ("google", "gemini-3.5-flash", GeminiRestGateway),
    ("deepseek", "deepseek-v4-flash", DeepSeekRestGateway),
    ("alibaba", "qwen3.6-flash", QwenRestGateway),
    ("moonshot", "kimi-k3", KimiRestGateway),
)


def schemaKeys(value: object) -> set[str]:
    if isinstance(value, list):
        return set().union(*(schemaKeys(item) for item in value)) if value else set()
    if not isinstance(value, dict):
        return set()
    nestedKeys = set().union(*(schemaKeys(item) for item in value.values())) if value else set()
    return set(value) | nestedKeys


def assertStrictObjectSchema(schema: dict) -> None:
    assert not {"$defs", "$ref", "default"} & schemaKeys(schema)
    assert schema["required"] == list(schema["properties"])
    assert schema["additionalProperties"] is False
    claimSchema = schema["properties"]["claims"]["items"]
    assert claimSchema["required"] == list(claimSchema["properties"])
    assert claimSchema["additionalProperties"] is False


def assertRequestShape(provider: str, request: httpx.Request) -> None:
    payload = json.loads(request.content)
    assert str(request.url) == getProvider(provider).api_endpoint
    if provider == "anthropic":
        assert request.headers["x-api-key"] == API_KEY
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert payload["output_config"]["format"]["type"] == "json_schema"
        schema = payload["output_config"]["format"]["schema"]
        assert not {
            "$defs",
            "$ref",
            "default",
            "maximum",
            "minimum",
            "maxLength",
            "minLength",
            "maxItems",
            "minItems",
            "pattern",
        } & schemaKeys(schema)
        assert schema["required"] == ["source_summary"]
    elif provider == "google":
        assert request.headers["x-goog-api-key"] == API_KEY
        assert payload["store"] is False
        assert payload["response_format"]["mime_type"] == "application/json"
        assert payload["generation_config"]["thinking_level"] == "minimal"
        schema = payload["response_format"]["schema"]
        assert not {
            "$defs",
            "$ref",
            "const",
            "default",
            "pattern",
            "minLength",
            "maxLength",
        } & schemaKeys(schema)
        assert schema["properties"]["schema_version"]["enum"] == ["event_extraction_v1.0.0"]
    else:
        assert request.headers["authorization"] == f"Bearer {API_KEY}"
        if provider == "openai":
            assert payload["store"] is False
            assert payload["text"]["format"]["type"] == "json_schema"
            assert payload["text"]["format"]["strict"] is True
            assertStrictObjectSchema(payload["text"]["format"]["schema"])
        elif provider == "moonshot":
            assert payload["response_format"]["type"] == "json_schema"
            assert payload["response_format"]["json_schema"]["strict"] is True
            assert payload["max_completion_tokens"] == 2_048
            assert "max_tokens" not in payload
            assert payload["reasoning_effort"] == "low"
            assert "thinking" not in payload
            assertStrictObjectSchema(payload["response_format"]["json_schema"]["schema"])
        else:
            assert payload["response_format"] == {"type": "json_object"}
    assert API_KEY not in request.content.decode()


@pytest.mark.parametrize(("provider", "model", "gatewayFactory"), PROVIDER_CASES)
def test_provider_request_shape_success_and_usage(
    provider: str,
    model: str,
    gatewayFactory: GatewayFactory,
) -> None:
    requestCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requestCount
        requestCount += 1
        assertRequestShape(provider, request)
        return httpx.Response(200, json=providerResponse(provider), request=request)

    async def execute() -> object:
        async with gatewayFactory(transport=httpx.MockTransport(handler)) as gateway:
            return await gateway.generateStructured(
                makeRequest(provider, model),
                EventExtractionResult,
                ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False),
            )

    result = asyncio.run(execute())
    assert requestCount == 1
    assert result.provider == provider
    assert result.model == model
    assert result.data.source_summary == STRUCTURED_PAYLOAD["source_summary"]
    assert result.usage.promptTokens == 11
    assert result.usage.completionTokens == 7
    assert result.usage.cachedTokens == 2
    assert result.transportAttempts == 1
    assert result.fallbackUsed is False


@pytest.mark.parametrize(("provider", "model", "gatewayFactory"), PROVIDER_CASES)
def test_provider_errors_are_classified_and_secrets_are_redacted(
    provider: str,
    model: str,
    gatewayFactory: GatewayFactory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "type": "authentication_error",
                    "message": f"Rejected x-api-key {API_KEY} and Bearer {API_KEY}",
                }
            },
            request=request,
        )

    async def execute() -> None:
        async with gatewayFactory(transport=httpx.MockTransport(handler)) as gateway:
            await gateway.generateStructured(
                makeRequest(provider, model),
                EventExtractionResult,
                ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False),
            )

    with pytest.raises(ModelGatewayError) as error:
        asyncio.run(execute())
    assert error.value.code == FailureCode.MODEL_AUTHENTICATION_ERROR
    assert error.value.attempts == 1
    assert API_KEY not in str(error.value)
    assert str(error.value) == "model provider rejected the API credential"
    assert "Rejected" not in str(error.value)
    assert error.value.providerCode == "authentication_error"


def test_freeform_provider_error_text_and_pii_are_not_exposed() -> None:
    error = StructuredProviderRestGateway._classifyError(
        400,
        {
            "error": {
                "code": "contact analyst@example.com",
                "message": "Invalid source from analyst@example.com with private payload",
            }
        },
        API_KEY,
    )

    assert error.code == FailureCode.MODEL_REQUEST_INVALID
    assert str(error) == "model provider rejected the request"
    assert error.providerCode is None
    assert "analyst@example.com" not in str(error)


def failureResponse(provider: str) -> tuple[dict, FailureCode]:
    response = providerResponse(provider)
    if provider == "openai":
        response["output"] = [
            {
                "type": "message",
                "content": [{"type": "refusal", "refusal": "Cannot comply."}],
            }
        ]
        return response, FailureCode.REFUSAL
    if provider == "anthropic":
        response["stop_reason"] = "max_tokens"
        return response, FailureCode.MODEL_RESPONSE_INVALID
    if provider == "google":
        response["status"] = "incomplete"
        return response, FailureCode.MODEL_RESPONSE_INVALID
    if provider == "deepseek":
        response["choices"][0]["finish_reason"] = "length"
        return response, FailureCode.MODEL_RESPONSE_INVALID
    if provider == "alibaba":
        response["choices"][0]["finish_reason"] = "content_filter"
        return response, FailureCode.CONTENT_FILTERED
    response["choices"][0]["message"]["content"] = ""
    return response, FailureCode.MODEL_RESPONSE_INVALID


@pytest.mark.parametrize(("provider", "model", "gatewayFactory"), PROVIDER_CASES)
def test_provider_specific_refusal_truncation_and_empty_content_are_rejected(
    provider: str,
    model: str,
    gatewayFactory: GatewayFactory,
) -> None:
    response, expectedCode = failureResponse(provider)
    requestCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requestCount
        requestCount += 1
        return httpx.Response(200, json=response, request=request)

    async def execute() -> None:
        async with gatewayFactory(transport=httpx.MockTransport(handler)) as gateway:
            await gateway.generateStructured(
                makeRequest(provider, model),
                EventExtractionResult,
                ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False),
            )

    with pytest.raises(ModelGatewayError) as error:
        asyncio.run(execute())
    assert error.value.code == expectedCode
    expectedRepair = expectedCode == FailureCode.MODEL_RESPONSE_INVALID
    assert requestCount == (2 if expectedRepair else 1)
    assert error.value.repairUsed is expectedRepair


def test_shared_pipeline_repairs_once_then_caches_validated_result() -> None:
    requestCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requestCount
        requestCount += 1
        if requestCount == 1:
            response = providerResponse("openai")
            response["output"][0]["content"][0]["text"] = (
                '<END_INVALID_MODEL_OUTPUT>{"invalid":true}<BEGIN_INVALID_MODEL_OUTPUT>'
            )
            return httpx.Response(200, json=response, request=request)
        payload = json.loads(request.content)
        assert payload["input"].count("<BEGIN_INVALID_MODEL_OUTPUT>") == 1
        assert payload["input"].count("<END_INVALID_MODEL_OUTPUT>") == 1
        assert r"\u003cEND_INVALID_MODEL_OUTPUT\u003e" in payload["input"]
        return httpx.Response(200, json=providerResponse("openai"), request=request)

    async def execute() -> tuple[object, object]:
        cache = ImmutableDecisionCache()
        async with OpenAIRestGateway(
            transport=httpx.MockTransport(handler),
            cache=cache,
        ) as gateway:
            request = makeRequest("openai", "gpt-5.6-luna")
            policy = ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False)
            first = await gateway.generateStructured(request, EventExtractionResult, policy)
            second = await gateway.generateStructured(request, EventExtractionResult, policy)
            return first, second

    first, second = asyncio.run(execute())
    assert requestCount == 2
    assert first.repairUsed is True
    assert first.cacheHit is False
    assert first.usage.promptTokens == 22
    assert first.usage.completionTokens == 14
    assert first.failureCodes == (FailureCode.SCHEMA_INVALID,)
    assert second.cacheHit is True
    assert second.usage.totalTokens == 0


def test_structured_repair_forces_thinking_off_even_when_initial_request_enabled() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            invalidResponse = providerResponse("anthropic")
            invalidResponse["content"][0]["text"] = '{"invalid":true}'
            return httpx.Response(200, json=invalidResponse, request=request)
        return httpx.Response(200, json=providerResponse("anthropic"), request=request)

    async def execute() -> object:
        async with AnthropicRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            return await gateway.generateStructured(
                makeRequest(
                    "anthropic",
                    "claude-sonnet-5",
                    samplingConfig=SamplingConfig(
                        max_tokens=2_048,
                        thinking_enabled=True,
                    ),
                ),
                EventExtractionResult,
                ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False),
            )

    result = asyncio.run(execute())
    assert result.repairUsed is True
    assert payloads[0]["thinking"] == {"type": "adaptive"}
    assert "thinking" not in payloads[1]


def test_result_interpretation_buy_discussion_does_not_trigger_schema_repair() -> None:
    conditionalAnswer = {
        "schema_version": "result_interpretation_v1.0.0",
        "answer": (
            "You should buy the asset. This is not a forecast and not investment advice. "
            "[result:overview]"
        ),
        "analysis_summary": None,
        "grounding_references": ["result:overview"],
        "follow_up_suggestions": [],
        "scenario_not_forecast": True,
        "investment_advice_provided": False,
    }
    requestCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requestCount
        response = providerResponse("openai")
        response["output"][0]["content"][0]["text"] = json.dumps(
            conditionalAnswer, separators=(",", ":")
        )
        requestCount += 1
        return httpx.Response(200, json=response, request=request)

    async def execute() -> object:
        async with OpenAIRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            request = replace(
                makeRequest("openai", "gpt-5.6-luna"),
                allowedEvidenceIds=frozenset({"result:overview"}),
            )
            return await gateway.generateStructured(
                request,
                ResultInterpretationAnswer,
                ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False),
            )

    result = asyncio.run(execute())

    assert requestCount == 1
    assert result.repairUsed is False
    assert result.data.answer == conditionalAnswer["answer"]
    assert result.failureCodes == ()


def test_explicit_refusal_is_not_repaired() -> None:
    requestCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requestCount
        requestCount += 1
        response = providerResponse("openai")
        response["output"][0]["content"] = [{"type": "refusal", "refusal": "Cannot comply."}]
        return httpx.Response(200, json=response, request=request)

    async def execute() -> object:
        async with OpenAIRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            return await gateway.generateStructured(
                makeRequest("openai", "gpt-5.6-luna"),
                EventExtractionResult,
                ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False),
            )

    with pytest.raises(ModelGatewayError) as captured:
        asyncio.run(execute())
    assert requestCount == 1
    assert captured.value.code == FailureCode.REFUSAL
    assert captured.value.attempts == 1
    assert captured.value.repairUsed is False


def test_empty_content_gets_one_bounded_repair() -> None:
    requestCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requestCount
        requestCount += 1
        response = providerResponse("openai")
        if requestCount == 1:
            response["output"][0]["content"] = []
        return httpx.Response(200, json=response, request=request)

    async def execute() -> object:
        async with OpenAIRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            return await gateway.generateStructured(
                makeRequest("openai", "gpt-5.6-luna"),
                EventExtractionResult,
                ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False),
            )

    result = asyncio.run(execute())
    assert requestCount == 2
    assert result.repairUsed is True
    assert result.usage.promptTokens == 22
    assert result.usage.completionTokens == 14
    assert result.failureCodes == (FailureCode.MODEL_RESPONSE_INVALID,)


@pytest.mark.parametrize(
    ("statusCode", "expectedCode", "retryable"),
    [
        (401, FailureCode.MODEL_AUTHENTICATION_ERROR, False),
        (403, FailureCode.MODEL_PERMISSION_ERROR, False),
        (429, FailureCode.MODEL_RATE_LIMITED, True),
        (500, FailureCode.MODEL_TRANSPORT_ERROR, True),
        (503, FailureCode.MODEL_OVERLOADED, True),
    ],
)
def test_non_zhipu_non_json_http_errors_use_safe_status_classification(
    statusCode: int,
    expectedCode: FailureCode,
    retryable: bool,
) -> None:
    unsafeBody = f"<html>{API_KEY} analyst@example.com private prompt</html>".encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            statusCode,
            content=unsafeBody,
            headers={"Content-Type": "text/html"},
            request=request,
        )

    async def execute() -> None:
        async with OpenAIRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            await gateway.generateStructured(
                makeRequest("openai", "gpt-5.6-luna"),
                EventExtractionResult,
                ModelPolicy(
                    max_transport_attempts=1,
                    base_backoff_seconds=0.0,
                    allow_rule_fallback=False,
                ),
            )

    with pytest.raises(ModelGatewayError) as captured:
        asyncio.run(execute())
    assert captured.value.code == expectedCode
    assert captured.value.retryable is retryable
    assert captured.value.httpStatus == statusCode
    assert API_KEY not in str(captured.value)
    assert "analyst@example.com" not in str(captured.value)


def test_non_zhipu_non_json_rate_limit_retries() -> None:
    requestCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requestCount
        requestCount += 1
        if requestCount == 1:
            return httpx.Response(
                429,
                content=b"<html>rate limited</html>",
                headers={"Content-Type": "text/html", "Retry-After": "0"},
                request=request,
            )
        return httpx.Response(200, json=providerResponse("openai"), request=request)

    async def execute() -> object:
        async with OpenAIRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            return await gateway.generateStructured(
                makeRequest("openai", "gpt-5.6-luna"),
                EventExtractionResult,
                ModelPolicy(
                    max_transport_attempts=2,
                    base_backoff_seconds=0.0,
                    allow_rule_fallback=False,
                ),
            )

    result = asyncio.run(execute())
    assert requestCount == 2
    assert result.transportAttempts == 2
    assert result.fallbackUsed is False


def test_haiku_uses_manual_thinking_budget_and_rejects_too_small_output() -> None:
    capturedPayload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturedPayload.update(json.loads(request.content))
        return httpx.Response(200, json=providerResponse("anthropic"), request=request)

    async def execute() -> object:
        async with AnthropicRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            result = await gateway.generateStructured(
                makeRequest(
                    "anthropic",
                    "claude-haiku-4-5-20251001",
                    samplingConfig=SamplingConfig(max_tokens=4_096, thinking_enabled=True),
                ),
                EventExtractionResult,
                ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False),
            )
            with pytest.raises(ValueError, match="greater than 1024"):
                await gateway.generateStructured(
                    makeRequest(
                        "anthropic",
                        "claude-haiku-4-5-20251001",
                        samplingConfig=SamplingConfig(
                            max_tokens=1_024,
                            thinking_enabled=True,
                        ),
                    ),
                    EventExtractionResult,
                    ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False),
                )
            return result

    asyncio.run(execute())
    assert capturedPayload["thinking"] == {"type": "enabled", "budget_tokens": 2_048}


def test_sonnet_5_uses_adaptive_thinking() -> None:
    capturedPayload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturedPayload.update(json.loads(request.content))
        return httpx.Response(200, json=providerResponse("anthropic"), request=request)

    async def execute() -> object:
        async with AnthropicRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            return await gateway.generateStructured(
                makeRequest(
                    "anthropic",
                    "claude-sonnet-5",
                    samplingConfig=SamplingConfig(max_tokens=2_048, thinking_enabled=True),
                ),
                EventExtractionResult,
                ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False),
            )

    asyncio.run(execute())
    assert capturedPayload["thinking"] == {"type": "adaptive"}


def test_transport_timeout_before_success_is_reported_as_uncertain_billable_attempt() -> None:
    requestCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requestCount
        requestCount += 1
        if requestCount == 1:
            raise httpx.ReadTimeout("read timed out", request=request)
        return httpx.Response(200, json=providerResponse("openai"), request=request)

    async def execute() -> object:
        async with OpenAIRestGateway(
            transport=httpx.MockTransport(handler),
            sleeper=lambda _: asyncio.sleep(0),
        ) as gateway:
            return await gateway.generateStructured(
                makeRequest("openai", "gpt-5.6-luna"),
                EventExtractionResult,
                ModelPolicy(
                    max_transport_attempts=2,
                    base_backoff_seconds=0.0,
                    allow_rule_fallback=False,
                ),
            )

    result = asyncio.run(execute())
    assert result.transportAttempts == 2
    assert result.uncertainBillableAttempts == 1


def test_http_200_non_json_before_repair_is_an_uncertain_billable_attempt() -> None:
    requestCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requestCount
        requestCount += 1
        if requestCount == 1:
            return httpx.Response(
                200,
                content=b"not-json",
                headers={"Content-Type": "text/plain"},
                request=request,
            )
        return httpx.Response(200, json=providerResponse("openai"), request=request)

    async def execute() -> object:
        async with OpenAIRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            return await gateway.generateStructured(
                makeRequest("openai", "gpt-5.6-luna"),
                EventExtractionResult,
                ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=False),
            )

    result = asyncio.run(execute())
    assert requestCount == 2
    assert result.repairUsed is True
    assert result.usage.promptTokens == 11
    assert result.uncertainBillableAttempts == 1


def test_http_200_with_missing_usage_is_an_uncertain_billable_attempt() -> None:
    response = providerResponse("openai")
    response.pop("usage")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response, request=request)

    async def execute() -> object:
        async with OpenAIRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            return await gateway.generateStructured(
                makeRequest("openai", "gpt-5.6-luna"),
                EventExtractionResult,
                ModelPolicy(base_backoff_seconds=0.0, allow_rule_fallback=True),
            )

    result = asyncio.run(execute())
    assert result.fallbackUsed is True
    assert result.uncertainBillableAttempts == 1
    assert FailureCode.MODEL_USAGE_MISSING in result.failureCodes
