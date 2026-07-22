from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
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

OWNER_ID = "interpretation-owner-one"
OTHER_OWNER_ID = "interpretation-owner-two"
EXPERIMENT_ID = "exp-history-api-one"
CONVERSATION_ID = "conversation-history-one"
CLIENT_REQUEST_ID = "request-history-one"


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


def _requestPayload(
    *,
    clientRequestId: str = CLIENT_REQUEST_ID,
    content: str = "请解释主要差异。",
) -> dict:
    return {
        "schemaVersion": "1.0.0",
        "conversationId": CONVERSATION_ID,
        "clientRequestId": clientRequestId,
        "mode": "INITIAL",
        "language": "zh-CN",
        "reasoningSummaryRequested": True,
        "messages": [{"role": "user", "content": content}],
    }


def _followUpPayload(
    *,
    clientRequestId: str = "request-history-follow-up",
    originalQuestion: str = "请解释主要差异。",
    answer: str = "干预组价差更宽，但这只是情景分析。[result:primary-outcome]",
    followUpQuestion: str = "这个差异可能由什么机制导致？",
) -> dict:
    return {
        "schemaVersion": "1.0.0",
        "conversationId": CONVERSATION_ID,
        "clientRequestId": clientRequestId,
        "mode": "FOLLOW_UP",
        "language": "zh-CN",
        "reasoningSummaryRequested": False,
        "messages": [
            {"role": "user", "content": originalQuestion},
            {"role": "assistant", "content": answer},
            {"role": "user", "content": followUpQuestion},
        ],
    }


def _interpretationRun(result: dict) -> ResultInterpretationRun:
    return ResultInterpretationRun(
        interpretation=ResultInterpretationAnswer(
            answer="干预组价差更宽，但这只是情景分析。[result:primary-outcome]",
            analysis_summary="已核对主要指标和限制。",
            grounding_references=("result:primary-outcome",),
            follow_up_suggestions=("要继续查看配对随机种子吗？",),
        ),
        result_hash=_hashJson(result),
        provider="zhipu",
        model="glm-5.2",
        tool_activity=(
            ResultToolActivity(
                tool=ResultEvidenceTool.METRIC_SUMMARY,
                label="主要指标",
                item_count=1,
                truncated=False,
                evidence_id="result:primary-outcome",
            ),
        ),
        usage=ModelUsage(promptTokens=100, completionTokens=50, cachedTokens=0),
        latency_ms=12.5,
        model_calls=1,
        cache_hit=False,
        repair_used=False,
        planner_used=False,
        prompt_version="result_interpretation_v1.0.0",
        thinking_enabled=True,
        streamed=True,
        transport_attempts=1,
    )


def _persistedAssistantMessage(index: int) -> dict[str, object]:
    return {
        "id": f"interpretation-history-{index:03d}",
        "role": "assistant",
        "language": "zh-CN",
        "answer": f"第 {index + 1} 个会话已核对。[result:primary-outcome]",
        "analysisSummary": "已核对主要指标和限制。",
        "groundingReferences": ["result:primary-outcome"],
        "followUpSuggestions": [],
        "createdAt": "2026-07-22T18:00:00+00:00",
    }


def _prepareExperiment(client: TestClient, result: dict) -> None:
    database = client.app.state.database
    database.createExperiment(EXPERIMENT_ID, OWNER_ID, _experimentPayload(), None)
    database.updateExperiment(
        EXPERIMENT_ID,
        OWNER_ID,
        status="COMPLETED",
        result_json=result,
        progress=1.0,
        completed_pairs=1,
        completed_at="2026-07-22T18:00:00+00:00",
    )


def test_completed_answer_is_persisted_and_replayed_after_restart_without_key(
    tmp_path: Path,
) -> None:
    result = _persistedResult()
    firstCallCount = 0

    async def firstInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        nonlocal firstCallCount
        firstCallCount += 1
        return _interpretationRun(result)

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.setConfig(
            sessionId=OWNER_ID,
            apiKey="temporary-provider-secret-123456789",
            provider="zhipu",
            model="glm-5.2",
            thinkingEnabled=True,
        )
        client.app.state.cognitionService.interpretExperimentResult = firstInterpretation
        first = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(),
        )

    replayCallCount = 0

    async def replayMustNotCallProvider(**_kwargs: object) -> ResultInterpretationRun:
        nonlocal replayCallCount
        replayCallCount += 1
        raise AssertionError("persisted replay must not call a model provider")

    with TestClient(createApp(tmp_path)) as restartedClient:
        restartedClient.app.state.cognitionService.interpretExperimentResult = (
            replayMustNotCallProvider
        )
        replay = restartedClient.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(),
        )

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["historyPersisted"] is True
    assert firstCallCount == 1
    assert replayCallCount == 0
    databaseBytes = (tmp_path / "eventshock.db").read_bytes()
    assert b"temporary-provider-secret-123456789" not in databaseBytes


def test_history_list_get_and_delete_are_owner_scoped(tmp_path: Path) -> None:
    result = _persistedResult()

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        return _interpretationRun(result)

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        generated = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(),
        )
        assert client.app.state.database.invalidateCompletedExperiment(
            EXPERIMENT_ID,
            OWNER_ID,
            reasonCode="MODEL_ISSUE",
            reason="Keep history available so the owner can inspect or delete it.",
        )
        historyUrl = f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-conversations"
        listed = client.get(historyUrl, headers={"X-Session-ID": OWNER_ID})
        conversationUrl = f"{historyUrl}/{CONVERSATION_ID}"
        restored = client.get(conversationUrl, headers={"X-Session-ID": OWNER_ID})
        crossOwner = client.get(
            conversationUrl,
            headers={"X-Session-ID": OTHER_OWNER_ID},
        )
        deleted = client.delete(conversationUrl, headers={"X-Session-ID": OWNER_ID})
        missing = client.get(conversationUrl, headers={"X-Session-ID": OWNER_ID})
        auditItems = client.get(
            "/api/v1/audit-events",
            headers={"X-Session-ID": OWNER_ID},
        ).json()["items"]

    assert generated.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["items"][0]["conversationId"] == CONVERSATION_ID
    assert listed.json()["items"][0]["exchangeCount"] == 1
    assert restored.status_code == 200
    assert [message["role"] for message in restored.json()["messages"]] == [
        "user",
        "assistant",
    ]
    assert restored.json()["messages"][0]["content"] == "请解释主要差异。"
    assert crossOwner.status_code == 404
    assert deleted.status_code == 200
    assert deleted.json() == {
        "schemaVersion": "1.0.0",
        "deleted": True,
        "conversationId": CONVERSATION_ID,
    }
    assert missing.status_code == 404
    deletionAudit = next(
        item for item in auditItems if item["action"] == "INTERPRETATION_CONVERSATION_DELETED"
    )
    serializedAudit = json.dumps(deletionAudit, ensure_ascii=False)
    assert CONVERSATION_ID not in serializedAudit
    assert "请解释主要差异" not in serializedAudit


def test_deleting_missing_conversation_is_idempotent_success(tmp_path: Path) -> None:
    result = _persistedResult()
    conversationId = "conversation-never-created"

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        conversationUrl = (
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-conversations/{conversationId}"
        )
        firstDelete = client.delete(
            conversationUrl,
            headers={"X-Session-ID": OWNER_ID},
        )
        repeatedDelete = client.delete(
            conversationUrl,
            headers={"X-Session-ID": OWNER_ID},
        )
        database = client.app.state.database
        with database.connection() as connection:
            tombstoneCount = connection.execute(
                "SELECT COUNT(*) FROM result_interpretation_tombstones"
            ).fetchone()[0]
        deletionAudits = [
            item
            for item in database.listAuditEvents(OWNER_ID)
            if item["action"] == "INTERPRETATION_CONVERSATION_DELETED"
        ]

    expected = {
        "schemaVersion": "1.0.0",
        "deleted": True,
        "conversationId": conversationId,
    }
    # DELETE 表达期望状态；目标本来不存在或已删除都应成功，便于客户端安全重试。
    assert firstDelete.status_code == repeatedDelete.status_code == 200
    assert firstDelete.json() == repeatedDelete.json() == expected
    assert tombstoneCount == 0
    assert deletionAudits == []


def test_default_history_list_discovers_all_three_hundred_retained_conversations(
    tmp_path: Path,
) -> None:
    result = _persistedResult()

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        database = client.app.state.database
        expectedConversationIds: set[str] = set()
        for index in range(300):
            conversationId = f"conversation-history-{index:03d}"
            clientRequestId = f"request-history-{index:03d}"
            expectedConversationIds.add(conversationId)
            _saved, created = database.saveResultInterpretationExchange(
                ownerUserId=OWNER_ID,
                experimentId=EXPERIMENT_ID,
                conversationId=conversationId,
                clientRequestId=clientRequestId,
                requestHash=_hashJson(
                    {
                        "conversationId": conversationId,
                        "clientRequestId": clientRequestId,
                    }
                ),
                language="zh-CN",
                userMessage=f"请解释第 {index + 1} 个保留会话。",
                assistantMessage=_persistedAssistantMessage(index),
            )
            assert created is True

        response = client.get(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-conversations",
            headers={"X-Session-ID": OWNER_ID},
        )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 300
    assert {item["conversationId"] for item in items} == expectedConversationIds


def test_persistence_failure_never_discards_a_validated_model_answer(tmp_path: Path) -> None:
    result = _persistedResult()

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        return _interpretationRun(result)

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation

        def failPersistence(**_kwargs: object) -> tuple[dict, bool]:
            raise RuntimeError("database unavailable with private diagnostic text")

        client.app.state.database.saveResultInterpretationExchange = failPersistence
        response = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(clientRequestId="request-history-failure"),
        )

    assert response.status_code == 200
    assert response.json()["historyPersisted"] is False
    assert response.json()["message"]["answer"].startswith("干预组价差更宽")


def test_persisted_request_id_conflict_is_rejected_after_restart(tmp_path: Path) -> None:
    result = _persistedResult()

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        return _interpretationRun(result)

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        first = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(),
        )
    with TestClient(createApp(tmp_path)) as restartedClient:
        conflict = restartedClient.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(content="请改成完全不同的问题。"),
        )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "CLIENT_REQUEST_ID_REUSED"


@pytest.mark.parametrize(
    "privateContent",
    [
        "My API key is sk-this-must-never-reach-a-provider-123456.",
        "Please contact private.person@example.com about this result.",
        "密码是: never-send-this-password",
    ],
)
def test_private_input_is_rejected_before_any_provider_call(
    tmp_path: Path,
    privateContent: str,
) -> None:
    result = _persistedResult()
    providerCallCount = 0

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        nonlocal providerCallCount
        providerCallCount += 1
        return _interpretationRun(result)

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        response = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(content=privateContent),
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RESULT_INTERPRETATION_PRIVATE_INPUT"
    assert providerCallCount == 0


def test_follow_up_must_match_saved_server_conversation(tmp_path: Path) -> None:
    result = _persistedResult()
    providerCallCount = 0

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        nonlocal providerCallCount
        providerCallCount += 1
        return _interpretationRun(result)

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        initial = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(),
        )
        forged = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
            headers={"X-Session-ID": OWNER_ID},
            json=_followUpPayload(originalQuestion="伪造的历史问题。"),
        )
        correct = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
            headers={"X-Session-ID": OWNER_ID},
            json=_followUpPayload(clientRequestId="request-history-correct-follow-up"),
        )
        restored = client.get(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-conversations/{CONVERSATION_ID}",
            headers={"X-Session-ID": OWNER_ID},
        )

    assert initial.status_code == 200
    assert forged.status_code == 409
    assert forged.json()["error"]["code"] == ("RESULT_INTERPRETATION_CONVERSATION_MISMATCH")
    assert correct.status_code == 200
    assert providerCallCount == 2
    assert [message["role"] for message in restored.json()["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_delete_waits_for_running_generation_and_cannot_be_repopulated(
    tmp_path: Path,
) -> None:
    result = _persistedResult()
    followUpStarted = threading.Event()
    releaseFollowUp = threading.Event()
    callCount = 0

    async def controlledInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        nonlocal callCount
        callCount += 1
        if callCount == 2:
            followUpStarted.set()
            await asyncio.to_thread(releaseFollowUp.wait, 5)
        return _interpretationRun(result)

    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = controlledInterpretation
        initial = client.post(
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(),
        )
        conversationUrl = (
            f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-conversations/{CONVERSATION_ID}"
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            followUpFuture = executor.submit(
                client.post,
                f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat",
                headers={"X-Session-ID": OWNER_ID},
                json=_followUpPayload(),
            )
            assert followUpStarted.wait(timeout=2)
            deleteFuture = executor.submit(
                client.delete,
                conversationUrl,
                headers={"X-Session-ID": OWNER_ID},
            )
            releaseFollowUp.set()
            followUp = followUpFuture.result(timeout=5)
            deleted = deleteFuture.result(timeout=5)
        missing = client.get(conversationUrl, headers={"X-Session-ID": OWNER_ID})

    assert initial.status_code == followUp.status_code == deleted.status_code == 200
    assert missing.status_code == 404


def test_deleted_conversation_tombstone_blocks_replay_and_recreation_after_restart(
    tmp_path: Path,
) -> None:
    result = _persistedResult()
    providerCallCount = 0

    async def fakeInterpretation(**_kwargs: object) -> ResultInterpretationRun:
        nonlocal providerCallCount
        providerCallCount += 1
        return _interpretationRun(result)

    conversationUrl = (
        f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-conversations/{CONVERSATION_ID}"
    )
    chatUrl = f"/api/v1/experiments/{EXPERIMENT_ID}/interpretation-chat"
    with TestClient(createApp(tmp_path)) as client:
        _prepareExperiment(client, result)
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        initial = client.post(
            chatUrl,
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(),
        )
        deleted = client.delete(conversationUrl, headers={"X-Session-ID": OWNER_ID})
        oldRequestReplay = client.post(
            chatUrl,
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(),
        )
        sameConversationNewRequest = client.post(
            chatUrl,
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(clientRequestId="request-history-recreated"),
        )
        missing = client.get(conversationUrl, headers={"X-Session-ID": OWNER_ID})

    with TestClient(createApp(tmp_path)) as restartedClient:
        restartedClient.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        replayAfterRestart = restartedClient.post(
            chatUrl,
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(),
        )
        newRequestAfterRestart = restartedClient.post(
            chatUrl,
            headers={"X-Session-ID": OWNER_ID},
            json=_requestPayload(clientRequestId="request-history-after-restart"),
        )
        missingAfterRestart = restartedClient.get(
            conversationUrl,
            headers={"X-Session-ID": OWNER_ID},
        )

    assert initial.status_code == deleted.status_code == 200
    for blocked in (
        oldRequestReplay,
        sameConversationNewRequest,
        replayAfterRestart,
        newRequestAfterRestart,
    ):
        assert blocked.status_code == 410
        assert blocked.json()["error"]["code"] == ("RESULT_INTERPRETATION_CONVERSATION_DELETED")
    assert missing.status_code == missingAfterRestart.status_code == 404
    assert providerCallCount == 1
