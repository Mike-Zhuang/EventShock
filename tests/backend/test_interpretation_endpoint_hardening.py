from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient

from backend.app.cognition import (
    FailureCode,
    ModelGatewayError,
    ModelUsage,
    ResultEvidenceTool,
    ResultInterpretationAnswer,
    ResultInterpretationRun,
    ResultToolActivity,
)
from backend.app.cognition.streaming import ModelStreamProgress, ModelStreamStage
from backend.app.main import createApp
from backend.app.schemas import ResultInterpretationChatRequest
from backend.app.service import _hashJson

SESSION_ID = "interpretation-session-12345"
EXPERIMENT_ID = "exp-interpretation-hardening"


def _sseFrames(body: str) -> list[tuple[str, dict[str, object], str]]:
    """解析应用公开 SSE，并要求每个 data 字段都是规范、完整的 JSON 对象。"""

    frames: list[tuple[str, dict[str, object], str]] = []
    for rawFrame in body.strip().split("\n\n"):
        lines = rawFrame.splitlines()
        eventLines = [line[7:].strip() for line in lines if line.startswith("event: ")]
        dataLines = [line[6:] for line in lines if line.startswith("data: ")]
        assert len(eventLines) == 1
        assert len(dataLines) == 1
        serialized = dataLines[0]
        payload = json.loads(serialized)
        assert isinstance(payload, dict)
        assert serialized == json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        frames.append((eventLines[0], payload, serialized))
    return frames


def _experimentPayload() -> dict:
    return {
        "eventPackId": "spacex-synthetic-v1",
        "question": "How does lower liquidity change the simulated distribution?",
        "intervention": {
            "parameter": "marketMakerCapacity",
            "baselineValue": 1.0,
            "interventionValue": 0.65,
        },
        "seedCount": 10,
        "populationSize": 14,
        "steps": 30,
        "seedRoot": 123_000,
    }


def _persistedResult() -> dict:
    return {
        "experimentId": EXPERIMENT_ID,
        "metricSummaries": {"maxSpreadBps": {"delta": {"median": 1.5}}},
        "pairedRuns": [{"seed": 101, "delta": {"maxSpreadBps": 1.5}}],
        "limitations": ["Synthetic scenario analysis only."],
        "manifest": {"validPairedSeeds": 1},
    }


def _requestPayload(clientRequestId: str, content: str = "请解释结果。") -> dict:
    return {
        "schemaVersion": "1.0.0",
        "conversationId": (
            f"conversation-{hashlib.sha256(clientRequestId.encode()).hexdigest()[:24]}"
        ),
        "clientRequestId": clientRequestId,
        "mode": "INITIAL",
        "language": "zh-CN",
        "reasoningSummaryRequested": True,
        "messages": [{"role": "user", "content": content}],
    }


def _interpretationRun(result: dict) -> ResultInterpretationRun:
    return ResultInterpretationRun(
        interpretation=ResultInterpretationAnswer(
            answer="这是有条件的情景分析，不是预测，也不构成投资建议。[result:overview]",
            analysis_summary="核对了实验边界和有效配对数量。",
            grounding_references=("result:overview",),
            follow_up_suggestions=("要继续查看配对差异吗？",),
        ),
        result_hash=_hashJson(result),
        provider="zhipu",
        model="glm-5.2",
        tool_activity=(
            ResultToolActivity(
                tool=ResultEvidenceTool.OVERVIEW,
                label="实验概览",
                item_count=1,
                truncated=False,
                evidence_id="result:overview",
            ),
        ),
        usage=ModelUsage(promptTokens=100, completionTokens=50, cachedTokens=0),
        latency_ms=12.5,
        model_calls=1,
        cache_hit=False,
        repair_used=False,
        planner_used=False,
        prompt_version="result_interpretation_v1.0.0",
    )


def _prepareExperiment(client: TestClient, result: dict) -> None:
    database = client.app.state.database
    database.createExperiment(EXPERIMENT_ID, SESSION_ID, _experimentPayload(), None)
    database.updateExperiment(
        EXPERIMENT_ID,
        SESSION_ID,
        status="COMPLETED",
        result_json=result,
        progress=1.0,
        completed_pairs=1,
        completed_at="2026-07-20T20:00:00+00:00",
    )


def test_interpretation_endpoint_single_flight_reuses_response_and_audit(
    tmp_path: Path,
) -> None:
    result = _persistedResult()
    providerStarted = threading.Event()
    releaseProvider = threading.Event()
    executeJoined = threading.Event()
    counterLock = threading.Lock()
    providerCallCount = 0
    executeCallCount = 0

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        nonlocal providerCallCount
        with counterLock:
            providerCallCount += 1
        providerStarted.set()
        await asyncio.to_thread(releaseProvider.wait, 5)
        return _interpretationRun(result)

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        singleFlight = client.app.state.resultInterpretationSingleFlight
        originalExecute = singleFlight.execute

        async def trackingExecute(**kwargs: object) -> dict:
            nonlocal executeCallCount
            with counterLock:
                executeCallCount += 1
                if executeCallCount >= 2:
                    executeJoined.set()
            return await originalExecute(**kwargs)

        singleFlight.execute = trackingExecute
        url = f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat"
        headers = {
            "X-Session-ID": SESSION_ID,
            "X-Forwarded-For": "203.0.113.31",
        }
        with ThreadPoolExecutor(max_workers=2) as executor:
            firstFuture = executor.submit(
                client.post,
                url,
                headers=headers,
                json=_requestPayload("request-hardening-001"),
            )
            assert providerStarted.wait(timeout=2)
            duplicateFuture = executor.submit(
                client.post,
                url,
                headers=headers,
                json=_requestPayload("request-hardening-001"),
            )
            assert executeJoined.wait(timeout=2)
            conflict = client.post(
                url,
                headers=headers,
                json=_requestPayload(
                    "request-hardening-001",
                    content="请改用另一种问题解释。",
                ),
            )
            releaseProvider.set()
            first = firstFuture.result(timeout=5)
            duplicate = duplicateFuture.result(timeout=5)
            completedRetry = client.post(
                url,
                headers=headers,
                json=_requestPayload("request-hardening-001"),
            )

        auditItems = client.get(
            "/api/v1/audit-events",
            headers={"X-Session-ID": SESSION_ID},
        ).json()["items"]

    assert first.status_code == duplicate.status_code == 200
    assert first.json() == duplicate.json()
    assert completedRetry.status_code == 200
    assert completedRetry.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "CLIENT_REQUEST_ID_REUSED"
    assert providerCallCount == 1
    assert len([item for item in auditItems if item["action"] == "INTERPRETATION_GENERATED"]) == 1


def test_interpretation_endpoint_has_dedicated_ip_and_session_rate_limit(
    tmp_path: Path,
) -> None:
    result = _persistedResult()

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        return _interpretationRun(result)

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        url = f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat"
        headers = {
            "X-Session-ID": SESSION_ID,
            "X-Forwarded-For": "203.0.113.32",
        }
        responses = [
            client.post(
                url,
                headers=headers,
                json=_requestPayload(f"request-rate-limit-{index:03d}"),
            )
            for index in range(9)
        ]

    assert [response.status_code for response in responses[:8]] == [200] * 8
    assert responses[8].status_code == 429
    assert responses[8].json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(responses[8].headers["Retry-After"]) >= 1


def test_interpretation_stream_emits_safe_progress_and_strict_final_json(
    tmp_path: Path,
) -> None:
    result = _persistedResult()
    answerSentinel = "RAW_ANSWER_SENTINEL"
    reasoningSentinel = "REASONING_SUMMARY_SENTINEL"

    async def fakeInterpretation(**kwargs: object) -> ResultInterpretationRun:
        progressObserver = kwargs.get("progressObserver")
        assert callable(progressObserver)
        await progressObserver(
            ModelStreamProgress(
                stage=ModelStreamStage.GENERATING,
                chunkCount=7,
                answerChunkCount=4,
                reasoningChunkCount=3,
                attempt=1,
                repair=False,
            )
        )
        # 给事件生成器一次调度机会，确保安全进度先于最终回答被消费。
        await asyncio.sleep(0.01)
        interpretation = ResultInterpretationAnswer(
            answer=f"{answerSentinel}：这是有界情景分析。[result:overview]",
            analysis_summary=(f"{reasoningSentinel}：仅核对结果证据，不展示私有思维链。"),
            grounding_references=("result:overview",),
        )
        return _interpretationRun(result).model_copy(
            update={"interpretation": interpretation, "streamed": True}
        )

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        response = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat/stream",
            headers={
                "X-Session-ID": SESSION_ID,
                "X-Forwarded-For": "203.0.113.41",
            },
            json=_requestPayload("request-stream-success-001"),
        )
        sseMetrics = client.get("/api/v1/system/metrics").json()["runtime"][
            "resultInterpretationSse"
        ]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["x-accel-buffering"] == "no"
    frames = _sseFrames(response.text)
    assert [event for event, _payload, _serialized in frames] == [
        "status",
        "progress",
        "final",
    ]

    statusPayload = frames[0][1]
    assert statusPayload == {
        "schemaVersion": "1.0.0",
        "stage": "PREPARING",
        "elapsedMs": 0,
    }
    progressPayload = frames[1][1]
    assert progressPayload["stage"] == "GENERATING"
    assert progressPayload["chunkCount"] == 7
    assert progressPayload["answerChunkCount"] == 4
    assert progressPayload["reasoningChunkCount"] == 3
    assert set(progressPayload) == {
        "schemaVersion",
        "stage",
        "elapsedMs",
        "chunkCount",
        "answerChunkCount",
        "reasoningChunkCount",
        "attempt",
        "repair",
    }
    progressFrames = "\n".join(serialized for _event, _payload, serialized in frames[:-1])
    assert answerSentinel not in progressFrames
    assert reasoningSentinel not in progressFrames

    finalPayload = frames[-1][1]
    assert finalPayload["schemaVersion"] == "1.0.0"
    assert finalPayload["experimentId"] == EXPERIMENT_ID
    assert finalPayload["clientRequestId"] == "request-stream-success-001"
    finalMessage = finalPayload["message"]
    assert isinstance(finalMessage, dict)
    assert answerSentinel in str(finalMessage["answer"])
    assert reasoningSentinel in str(finalMessage["analysisSummary"])
    assert finalMessage["streamed"] is True
    assert sseMetrics["terminalCount"] == 1
    assert sseMetrics["successCount"] == 1
    assert sseMetrics["errorCount"] == 0
    assert sseMetrics["cancelledCount"] == 0
    assert sseMetrics["latencyWindowSize"] == 1


def test_interpretation_stream_converts_api_error_to_stable_safe_event(
    tmp_path: Path,
) -> None:
    result = _persistedResult()
    internalSchemaSentinel = "SECRET_INTERNAL_RESULT_SCHEMA_AND_VALIDATION_TEXT"

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        raise ValueError(internalSchemaSentinel)

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        response = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat/stream",
            headers={
                "X-Session-ID": SESSION_ID,
                "X-Forwarded-For": "203.0.113.42",
            },
            json=_requestPayload("request-stream-error-001"),
        )
        sseMetrics = client.get("/api/v1/system/metrics").json()["runtime"][
            "resultInterpretationSse"
        ]

    assert response.status_code == 200
    assert internalSchemaSentinel not in response.text
    frames = _sseFrames(response.text)
    assert [event for event, _payload, _serialized in frames] == ["status", "error"]
    errorPayload = frames[-1][1]
    assert errorPayload["schemaVersion"] == "1.0.0"
    assert errorPayload["code"] == "RESULT_INTERPRETATION_CONTEXT_INVALID"
    assert errorPayload["message"] == "The result interpretation context was invalid."
    assert errorPayload["httpStatus"] == 422
    assert errorPayload["retryable"] is False
    assert isinstance(errorPayload["traceId"], str)
    assert sseMetrics["terminalCount"] == 1
    assert sseMetrics["successCount"] == 0
    assert sseMetrics["errorCount"] == 1
    assert sseMetrics["cancelledCount"] == 0


def test_interpretation_stream_records_client_cancellation_without_model_content(
    tmp_path: Path,
) -> None:
    result = _persistedResult()

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        route = next(
            route
            for route in client.app.routes
            if getattr(route, "path", None)
            == "/api/v1/experiments/{experimentId}/interpretation-chat/stream"
        )

        async def closeAfterInitialStatus() -> str:
            scope = {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat/stream",
                "raw_path": (
                    f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat/stream"
                ).encode(),
                "query_string": b"",
                "headers": [],
                "client": ("203.0.113.48", 12345),
                "server": ("testserver", 80),
                "app": client.app,
            }
            request = Request(scope)
            request.state.traceId = "http-cancelled-stream-test"
            response = await route.endpoint(
                experimentId=EXPERIMENT_ID,
                interpretationRequest=ResultInterpretationChatRequest.model_validate(
                    _requestPayload("request-stream-cancelled-001")
                ),
                request=request,
                sessionId=SESSION_ID,
            )
            iterator = response.body_iterator
            firstFrame = await anext(iterator)
            await iterator.aclose()
            return firstFrame.decode() if isinstance(firstFrame, bytes) else firstFrame

        firstFrame = asyncio.run(closeAfterInitialStatus())
        sseMetrics = client.get("/api/v1/system/metrics").json()["runtime"][
            "resultInterpretationSse"
        ]

    assert "event: status" in firstFrame
    assert sseMetrics["terminalCount"] == 1
    assert sseMetrics["successCount"] == 0
    assert sseMetrics["errorCount"] == 0
    assert sseMetrics["cancelledCount"] == 1
    assert sseMetrics["latencyWindowSize"] == 1


def test_interpretation_stream_returns_and_caches_final_when_audit_write_fails(
    tmp_path: Path,
    caplog,
    monkeypatch,
) -> None:
    result = _persistedResult()
    auditSentinel = "SECRET_AUDIT_DATABASE_PATH_AND_SQL"
    providerCallCount = 0

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        nonlocal providerCallCount
        providerCallCount += 1
        return _interpretationRun(result).model_copy(update={"streamed": True})

    def failAudit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(auditSentinel)

    caplog.set_level("ERROR", logger="backend.app.main")
    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        monkeypatch.setattr(client.app.state.database, "appendAuditEvent", failAudit)
        url = f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat/stream"
        headers = {
            "X-Session-ID": SESSION_ID,
            "X-Forwarded-For": "203.0.113.44",
        }
        payload = _requestPayload("request-stream-audit-failure-001")
        first = client.post(url, headers=headers, json=payload)
        completedRetry = client.post(url, headers=headers, json=payload)

    firstFrames = _sseFrames(first.text)
    retryFrames = _sseFrames(completedRetry.text)
    assert [event for event, _payload, _serialized in firstFrames] == ["status", "final"]
    assert [event for event, _payload, _serialized in retryFrames] == ["status", "final"]
    assert firstFrames[-1][1] == retryFrames[-1][1]
    assert providerCallCount == 1
    assert auditSentinel not in first.text
    assert auditSentinel not in completedRetry.text
    assert auditSentinel not in caplog.text
    assert "INTERPRETATION_GENERATED" in caplog.text


def test_interpretation_stream_preserves_safe_model_error_when_failure_audit_fails(
    tmp_path: Path,
    caplog,
    monkeypatch,
) -> None:
    result = _persistedResult()
    providerSentinel = "SECRET_PROVIDER_RESPONSE_AND_API_KEY"
    auditSentinel = "SECRET_AUDIT_DATABASE_PATH_AND_SQL"

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        raise ModelGatewayError(
            FailureCode.MODEL_TIMEOUT,
            providerSentinel,
            retryable=True,
            attempts=1,
            uncertainBillableAttempts=1,
        )

    def failAudit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(auditSentinel)

    caplog.set_level("ERROR", logger="backend.app.main")
    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        monkeypatch.setattr(client.app.state.database, "appendAuditEvent", failAudit)
        response = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat/stream",
            headers={
                "X-Session-ID": SESSION_ID,
                "X-Forwarded-For": "203.0.113.45",
            },
            json=_requestPayload("request-stream-failed-audit-001"),
        )

    frames = _sseFrames(response.text)
    assert [event for event, _payload, _serialized in frames] == ["status", "error"]
    errorPayload = frames[-1][1]
    assert errorPayload["code"] == "MODEL_TIMEOUT"
    assert errorPayload["message"] == ("The model provider did not finish within the bounded time.")
    assert errorPayload["retryable"] is True
    assert errorPayload["providerAttempts"] == 1
    assert errorPayload["uncertainBillableAttempts"] == 1
    assert providerSentinel not in response.text
    assert auditSentinel not in response.text
    assert providerSentinel not in caplog.text
    assert auditSentinel not in caplog.text
    assert "INTERPRETATION_FAILED" in caplog.text


def test_interpretation_stream_converts_unexpected_coordinator_error_to_safe_event(
    tmp_path: Path,
    caplog,
    monkeypatch,
) -> None:
    result = _persistedResult()
    internalSentinel = "SECRET_INTERNAL_COORDINATOR_STATE_AND_PATH"

    async def failSingleFlight(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError(internalSentinel)

    caplog.set_level("ERROR", logger="backend.app.main")
    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        monkeypatch.setattr(
            client.app.state.resultInterpretationSingleFlight,
            "execute",
            failSingleFlight,
        )
        response = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat/stream",
            headers={
                "X-Session-ID": SESSION_ID,
                "X-Forwarded-For": "203.0.113.46",
            },
            json=_requestPayload("request-stream-coordinator-failure-001"),
        )

    frames = _sseFrames(response.text)
    assert [event for event, _payload, _serialized in frames] == ["status", "error"]
    errorPayload = frames[-1][1]
    assert errorPayload == {
        "schemaVersion": "1.0.0",
        "code": "RESULT_INTERPRETATION_INTERNAL_ERROR",
        "message": "The result interpretation stream ended unexpectedly.",
        "retryable": True,
        "httpStatus": 500,
        "uncertainBillableAttempts": 1,
        "traceId": errorPayload["traceId"],
    }
    assert isinstance(errorPayload["traceId"], str)
    assert internalSentinel not in response.text
    assert internalSentinel not in caplog.text
    assert "RuntimeError" in caplog.text


def test_interpretation_stream_caches_sanitized_unexpected_model_failure(
    tmp_path: Path,
    caplog,
) -> None:
    result = _persistedResult()
    internalSentinel = "SECRET_PROVIDER_OBJECT_WITH_AUTHORIZATION_HEADER"
    providerCallCount = 0

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        nonlocal providerCallCount
        providerCallCount += 1
        raise RuntimeError(internalSentinel)

    caplog.set_level("ERROR", logger="backend.app.main")
    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        url = f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat/stream"
        headers = {
            "X-Session-ID": SESSION_ID,
            "X-Forwarded-For": "203.0.113.47",
        }
        payload = _requestPayload("request-stream-model-internal-001")
        first = client.post(url, headers=headers, json=payload)
        completedRetry = client.post(url, headers=headers, json=payload)

    for response in (first, completedRetry):
        frames = _sseFrames(response.text)
        assert [event for event, _payload, _serialized in frames] == ["status", "error"]
        errorPayload = frames[-1][1]
        assert errorPayload["code"] == "RESULT_INTERPRETATION_INTERNAL_ERROR"
        assert errorPayload["message"] == (
            "The result interpretation could not be completed safely."
        )
        assert errorPayload["retryable"] is True
        assert errorPayload["uncertainBillableAttempts"] == 1
        assert internalSentinel not in response.text
    assert providerCallCount == 1
    assert internalSentinel not in caplog.text
    assert "RuntimeError" in caplog.text


def test_deleting_unrelated_conversation_keeps_uncertain_failure_cache(
    tmp_path: Path,
) -> None:
    """删除 B 不能让会话 A 的同请求重试再次触发可能计费的供应商调用。"""

    result = _persistedResult()
    providerCallCount = 0

    async def timeoutInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        nonlocal providerCallCount
        providerCallCount += 1
        raise ModelGatewayError(
            FailureCode.MODEL_TIMEOUT,
            "private provider timeout",
            retryable=True,
            attempts=1,
            uncertainBillableAttempts=1,
        )

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = timeoutInterpretation
        chatUrl = f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat"
        headers = {"X-Session-ID": SESSION_ID}
        payload = _requestPayload("request-timeout-cache-survives-delete")
        first = client.post(chatUrl, headers=headers, json=payload)
        deleted = client.delete(
            (
                f"/api/v1/experiments/{EXPERIMENT_ID}/"
                "interpretation-conversations/conversation-unrelated-delete"
            ),
            headers=headers,
        )
        replay = client.post(chatUrl, headers=headers, json=payload)

    assert first.status_code == replay.status_code == 504
    assert first.json()["error"]["code"] == replay.json()["error"]["code"] == "MODEL_TIMEOUT"
    assert deleted.status_code == 200
    assert providerCallCount == 1


def test_interpretation_stream_has_dedicated_ip_and_session_rate_limit(
    tmp_path: Path,
) -> None:
    result = _persistedResult()

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        return _interpretationRun(result).model_copy(update={"streamed": True})

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        url = f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat/stream"
        headers = {
            "X-Session-ID": SESSION_ID,
            "X-Forwarded-For": "203.0.113.43",
        }
        responses = [
            client.post(
                url,
                headers=headers,
                json=_requestPayload(f"request-stream-rate-limit-{index:03d}"),
            )
            for index in range(9)
        ]

    assert [response.status_code for response in responses[:8]] == [200] * 8
    assert all(_sseFrames(response.text)[-1][0] == "final" for response in responses[:8])
    assert responses[8].status_code == 429
    assert responses[8].json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(responses[8].headers["Retry-After"]) >= 1


def test_llm_connection_test_redacts_model_gateway_error(tmp_path: Path) -> None:
    providerSentinel = "SECRET_PROVIDER_RESPONSE_WITH_API_KEY"

    async def failConnection(_credentialId: str) -> object:
        raise ModelGatewayError(
            FailureCode.MODEL_AUTHENTICATION_ERROR,
            providerSentinel,
            retryable=False,
            attempts=1,
            uncertainBillableAttempts=1,
        )

    with TestClient(createApp(tmp_path)) as client:
        client.app.state.cognitionService.testConnection = failConnection
        response = client.post(
            "/api/v1/llm/test",
            headers={"X-Session-ID": SESSION_ID},
        )

    assert response.status_code == 422
    assert providerSentinel not in response.text
    assert response.json()["error"] == {
        "code": "MODEL_AUTHENTICATION_ERROR",
        "message": "The model provider rejected the temporary API key.",
        "traceId": response.json()["error"]["traceId"],
        "retryable": False,
        "providerAttempts": 1,
        "uncertainBillableAttempts": 1,
        "repairUsed": False,
    }


def test_live_evaluation_redacts_model_gateway_error(tmp_path: Path) -> None:
    providerSentinel = "SECRET_PROVIDER_TRANSPORT_AND_AUTHORIZATION_HEADER"

    async def failGeneration(**_kwargs: object) -> object:
        raise ModelGatewayError(
            FailureCode.MODEL_TRANSPORT_ERROR,
            providerSentinel,
            retryable=True,
            attempts=2,
            uncertainBillableAttempts=1,
            repairUsed=True,
        )

    with TestClient(createApp(tmp_path)) as client:
        configured = client.put(
            "/api/v1/llm/config",
            headers={"X-Session-ID": SESSION_ID},
            json={
                "provider": "zhipu",
                "model": "glm-5.2",
                "apiKey": "temporary-test-key",
                "thinkingEnabled": False,
                "maxTokens": 2_048,
            },
        )
        assert configured.status_code == 200
        client.app.state.cognitionService.generateBeliefDecision = failGeneration
        response = client.post(
            "/api/v1/evals/run",
            headers={"X-Session-ID": SESSION_ID},
            json={"mode": "LIVE_CONFIGURED_MODEL", "maximumCases": 1},
        )

    assert response.status_code == 503
    assert providerSentinel not in response.text
    assert response.json()["error"] == {
        "code": "MODEL_TRANSPORT_ERROR",
        "message": "The model provider connection failed temporarily.",
        "traceId": response.json()["error"]["traceId"],
        "retryable": True,
        "providerAttempts": 2,
        "uncertainBillableAttempts": 1,
        "repairUsed": True,
    }
