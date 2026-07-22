from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.cognition import (
    ModelUsage,
    ResultEvidenceTool,
    ResultInterpretationAnswer,
    ResultInterpretationRun,
    ResultToolActivity,
)
from backend.app.main import createApp
from backend.app.service import _hashJson

SESSION_ID = "interpretation-session-12345"
EXPERIMENT_ID = "exp-interpretation-hardening"


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
        "conversationId": "conversation-hardening-001",
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
    assert len(
        [item for item in auditItems if item["action"] == "INTERPRETATION_GENERATED"]
    ) == 1


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
