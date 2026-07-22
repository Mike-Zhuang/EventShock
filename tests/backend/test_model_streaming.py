from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from backend.app.cognition import (
    EVENT_EXTRACTION_PROMPT,
    EventExtractionResult,
    FailureCode,
    ModelGatewayError,
    ModelPolicy,
    ModelRequest,
    SamplingConfig,
    ZhipuRestGateway,
    canonicalHash,
)
from backend.app.cognition.streaming import (
    MAX_PROVIDER_STREAM_BYTES,
    ModelStreamProgress,
    ModelStreamStage,
    ProviderStreamAccumulator,
    SseEvent,
    iterSseEvents,
)

API_KEY = "stream-test-secret-key"
STRUCTURED_PAYLOAD = {
    "schema_version": "event_extraction_v1.0.0",
    "claims": [],
    "source_summary": "The bounded stream contains no event claim.",
    "abstain_reason": "No event fact was supplied.",
}


def encodeSse(*events: tuple[str | None, object]) -> bytes:
    lines: list[str] = []
    for eventName, payload in events:
        if eventName is not None:
            lines.append(f"event: {eventName}")
        data = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
        lines.append(f"data: {data}")
        lines.append("")
    return "\n".join(lines).encode()


def makeRequest(*, streamObserver=None) -> ModelRequest:
    return ModelRequest(
        provider="zhipu",
        model="glm-5.2",
        requestId="request-stream-001",
        userId="anonymous-stream-session-001",
        systemPrompt=EVENT_EXTRACTION_PROMPT.systemPrompt,
        userContent="Return JSON for this bounded connectivity probe.",
        promptHash=EVENT_EXTRACTION_PROMPT.promptHash,
        schemaVersion=EVENT_EXTRACTION_PROMPT.schemaVersion,
        agentConfigHash=canonicalHash({"model": "glm-5.2"}),
        observationHash=canonicalHash({"workflow": "stream-test"}),
        allowedEvidenceIds=frozenset(),
        samplingConfig=SamplingConfig(max_tokens=2_048),
        apiKey=API_KEY,
        streamResponse=True,
        streamObserver=streamObserver,
    )


def test_sse_parser_supports_comments_named_events_and_multiline_data() -> None:
    raw = b': heartbeat\r\nevent: sample\r\ndata: {"left":\r\ndata: 1}\r\n\r\ndata: [DONE]\n\n'
    response = httpx.Response(200, content=raw)

    async def collect() -> list[SseEvent]:
        return [event async for event in iterSseEvents(response)]

    events = asyncio.run(collect())

    assert events == [
        SseEvent(event="sample", data='{"left":\n1}'),
        SseEvent(event="message", data="[DONE]"),
    ]


def test_sse_parser_rejects_oversized_stream_without_a_newline() -> None:
    response = httpx.Response(
        200,
        content=b"x" * (MAX_PROVIDER_STREAM_BYTES + 1),
        headers={"Content-Type": "text/event-stream"},
    )

    async def collect() -> list[SseEvent]:
        return [event async for event in iterSseEvents(response)]

    with pytest.raises(ValueError, match="bounded response limit"):
        asyncio.run(collect())


def test_sse_parser_rejects_invalid_utf8_without_echoing_bytes() -> None:
    response = httpx.Response(
        200,
        content=b"data: \xff\n\n",
        headers={"Content-Type": "text/event-stream"},
    )

    async def collect() -> list[SseEvent]:
        return [event async for event in iterSseEvents(response)]

    with pytest.raises(ValueError, match="invalid UTF-8") as captured:
        asyncio.run(collect())
    assert "\\xff" not in str(captured.value)


def test_zhipu_chat_stream_counts_reasoning_without_exposing_it() -> None:
    accumulator = ProviderStreamAccumulator("zhipu")
    secretReasoning = "private chain of thought must never leave the accumulator"

    accumulator.accept(
        SseEvent(
            event="message",
            data=json.dumps(
                {
                    "choices": [
                        {"delta": {"reasoning_content": secretReasoning}, "finish_reason": None}
                    ]
                }
            ),
        )
    )
    accumulator.accept(
        SseEvent(
            event="message",
            data=json.dumps({"choices": [{"delta": {"content": '{"ok":'}, "finish_reason": None}]}),
        )
    )
    accumulator.accept(
        SseEvent(
            event="message",
            data=json.dumps(
                {"choices": [{"delta": {"content": "true}"}, "finish_reason": "stop"}]}
            ),
        )
    )
    accumulator.accept(
        SseEvent(
            event="message",
            data=json.dumps(
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "total_tokens": 5,
                    },
                }
            ),
        )
    )
    accumulator.accept(SseEvent(event="message", data="[DONE]"))

    body = accumulator.buildBody()

    assert body["choices"][0]["message"]["content"] == '{"ok":true}'
    assert body["usage"]["total_tokens"] == 5
    assert accumulator.reasoningChunkCount == 1
    assert accumulator.answerChunkCount == 2
    assert secretReasoning not in json.dumps(body)
    assert secretReasoning not in accumulator.content


def test_openai_responses_accumulator_requires_and_uses_final_response() -> None:
    accumulator = ProviderStreamAccumulator("openai")
    accumulator.accept(
        SseEvent(
            event="response.output_text.delta",
            data=json.dumps({"type": "response.output_text.delta", "delta": '{"ok":true}'}),
        )
    )
    accumulator.accept(
        SseEvent(
            event="response.reasoning_summary_text.delta",
            data=json.dumps(
                {"type": "response.reasoning_summary_text.delta", "delta": "safe summary"}
            ),
        )
    )
    accumulator.accept(
        SseEvent(
            event="response.completed",
            data=json.dumps(
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp-stream",
                        "status": "completed",
                        "output": [],
                        "usage": {
                            "input_tokens": 3,
                            "output_tokens": 2,
                            "total_tokens": 5,
                        },
                    },
                }
            ),
        )
    )

    body = accumulator.buildBody()

    assert body["status"] == "completed"
    assert body["output"][0]["content"][0]["text"] == '{"ok":true}'
    assert accumulator.reasoningChunkCount == 1


def test_anthropic_accumulator_ignores_tool_json_and_signature() -> None:
    accumulator = ProviderStreamAccumulator("anthropic")
    events = (
        (
            "message_start",
            {"type": "message_start", "message": {"usage": {"input_tokens": 4}}},
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": "hidden reasoning"},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": '{"tool":"secret"}'},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "delta": {"type": "signature_delta", "signature": "opaque-signature"},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": '{"ok":true}'},
            },
        ),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 2},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    )
    for eventName, payload in events:
        accumulator.accept(SseEvent(event=eventName, data=json.dumps(payload)))

    body = accumulator.buildBody()
    serialized = json.dumps(body)

    assert body["content"][0]["text"] == '{"ok":true}'
    assert body["usage"] == {"input_tokens": 4, "output_tokens": 2}
    assert accumulator.reasoningChunkCount == 1
    assert "tool" not in serialized
    assert "opaque-signature" not in serialized


def test_gemini_interactions_accumulator_handles_thought_summary_and_final_json() -> None:
    accumulator = ProviderStreamAccumulator("google")
    accumulator.accept(
        SseEvent(
            event="step.delta",
            data=json.dumps(
                {
                    "event_type": "step.delta",
                    "delta": {
                        "type": "thought_summary",
                        "content": {"type": "text", "text": "bounded summary"},
                    },
                }
            ),
        )
    )
    accumulator.accept(
        SseEvent(
            event="step.delta",
            data=json.dumps(
                {
                    "event_type": "step.delta",
                    "delta": {"type": "text", "text": '{"ok":true}'},
                }
            ),
        )
    )
    accumulator.accept(
        SseEvent(
            event="interaction.completed",
            data=json.dumps(
                {
                    "event_type": "interaction.completed",
                    "interaction": {
                        "id": "interaction-stream",
                        "status": "completed",
                        "steps": [],
                        "usage": {
                            "total_input_tokens": 3,
                            "total_output_tokens": 2,
                            "total_tokens": 5,
                        },
                    },
                }
            ),
        )
    )

    body = accumulator.buildBody()

    assert body["steps"][0]["content"][0]["text"] == '{"ok":true}'
    assert accumulator.reasoningChunkCount == 1


def test_gemini_legacy_accumulator_normalizes_usage_and_discards_thought_signature() -> None:
    accumulator = ProviderStreamAccumulator("google")
    accumulator.accept(
        SseEvent(
            event="message",
            data=json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "hidden", "thought": True},
                                    {"text": '{"ok":true}', "thoughtSignature": "opaque"},
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 3,
                        "candidatesTokenCount": 2,
                        "thoughtsTokenCount": 1,
                        "totalTokenCount": 6,
                    },
                }
            ),
        )
    )

    body = accumulator.buildBody()

    assert body["steps"][0]["content"][0]["text"] == '{"ok":true}'
    assert body["usage"]["total_tokens"] == 6
    assert accumulator.reasoningChunkCount == 1
    assert "hidden" not in json.dumps(body)
    assert "opaque" not in json.dumps(body)


def test_zhipu_stream_is_reassembled_then_validated_as_final_json() -> None:
    content = json.dumps(STRUCTURED_PAYLOAD, separators=(",", ":"))
    progress: list[ModelStreamProgress] = []

    async def observe(item: ModelStreamProgress) -> None:
        progress.append(item)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        stream = encodeSse(
            (
                None,
                {
                    "choices": [
                        {
                            "delta": {"reasoning_content": "private provider reasoning"},
                            "finish_reason": None,
                        }
                    ]
                },
            ),
            (None, {"choices": [{"delta": {"content": content[:25]}, "finish_reason": None}]}),
            (None, {"choices": [{"delta": {"content": content[25:]}, "finish_reason": "stop"}]}),
            (
                None,
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 7,
                        "total_tokens": 12,
                    },
                },
            ),
            (None, "[DONE]"),
        )
        return httpx.Response(
            200,
            content=stream,
            headers={"Content-Type": "text/event-stream; charset=utf-8"},
            request=request,
        )

    async def execute():
        async with ZhipuRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            return await gateway.generateStructured(
                makeRequest(streamObserver=observe),
                EventExtractionResult,
                ModelPolicy(
                    max_transport_attempts=1,
                    base_backoff_seconds=0.0,
                    allow_rule_fallback=False,
                ),
            )

    result = asyncio.run(execute())

    assert result.data.source_summary == STRUCTURED_PAYLOAD["source_summary"]
    assert result.usage.totalTokens == 12
    assert result.uncertainBillableAttempts == 0
    assert any(item.stage == ModelStreamStage.REASONING for item in progress)
    assert any(item.stage == ModelStreamStage.VALIDATING for item in progress)
    assert max(item.reasoningChunkCount for item in progress) == 1


def test_interrupted_stream_is_not_accepted_and_records_uncertain_billing() -> None:
    requestCount = 0
    content = json.dumps(STRUCTURED_PAYLOAD, separators=(",", ":"))

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requestCount
        requestCount += 1
        payload = json.loads(request.content)
        if payload["stream"] is True:
            # 即使 JSON 和 finish_reason 已完整到达，缺少 [DONE] 仍可能是连接中断。
            stream = encodeSse(
                (
                    None,
                    {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}]},
                )
            )
            return httpx.Response(
                200,
                content=stream,
                headers={"Content-Type": "text/event-stream"},
                request=request,
            )
        assert request.headers["accept"] == "application/json"
        return httpx.Response(
            400,
            json={"error": {"code": "1210", "message": "repair rejected"}},
            request=request,
        )

    async def execute() -> None:
        async with ZhipuRestGateway(transport=httpx.MockTransport(handler)) as gateway:
            await gateway.generateStructured(
                makeRequest(),
                EventExtractionResult,
                ModelPolicy(
                    max_transport_attempts=1,
                    base_backoff_seconds=0.0,
                    allow_rule_fallback=False,
                ),
            )

    with pytest.raises(ModelGatewayError) as captured:
        asyncio.run(execute())

    assert requestCount == 2
    assert captured.value.code == FailureCode.MODEL_REQUEST_INVALID
    assert captured.value.attempts == 2
    assert captured.value.uncertainBillableAttempts == 1
    assert captured.value.repairUsed is True


@pytest.mark.parametrize("provider", ["zhipu", "deepseek", "alibaba", "moonshot"])
def test_chat_stream_requires_done_and_finish_reason(provider: str) -> None:
    accumulator = ProviderStreamAccumulator(provider)
    accumulator.accept(
        SseEvent(
            event="message",
            data=json.dumps(
                {"choices": [{"delta": {"content": '{"ok":true}'}, "finish_reason": "stop"}]}
            ),
        )
    )

    with pytest.raises(ValueError, match=r"terminal \[DONE\]"):
        accumulator.buildBody()


def test_typed_stream_requires_provider_terminal_event() -> None:
    accumulator = ProviderStreamAccumulator("openai")
    accumulator.accept(
        SseEvent(
            event="response.output_text.delta",
            data=json.dumps({"type": "response.output_text.delta", "delta": '{"ok":true}'}),
        )
    )

    with pytest.raises(ValueError, match="terminal event"):
        accumulator.buildBody()


def test_stream_error_payload_is_redacted_from_exception() -> None:
    accumulator = ProviderStreamAccumulator("anthropic")
    secret = "user@example.com private payload"

    with pytest.raises(ValueError) as captured:
        accumulator.accept(
            SseEvent(
                event="error",
                data=json.dumps({"type": "error", "error": {"message": secret}}),
            )
        )

    assert str(captured.value) == "provider stream reported an error"
    assert secret not in str(captured.value)
