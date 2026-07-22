import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.database import Database, ResultInterpretationRequestConflictError
from backend.app.main import createApp


def _createCompletedExperiment(database: Database, experimentId: str, ownerUserId: str) -> None:
    database.createExperiment(
        experimentId,
        ownerUserId,
        {"eventPackId": "spacex-synthetic-v1", "seedCount": 10},
        None,
    )
    database.updateExperiment(
        experimentId,
        ownerUserId,
        status="COMPLETED",
        result_json={"schemaVersion": "1.0.0", "experimentId": experimentId},
        completed_at=datetime.now(UTC).isoformat(),
    )


def _assistantMessage(messageId: str, language: str = "zh-CN") -> dict:
    answer = (
        "干预组的峰值价差更高 [result:primary-outcome]。"
        if language == "zh-CN"
        else "The intervention has a wider peak spread [result:primary-outcome]."
    )
    return {
        "id": messageId,
        "role": "assistant",
        "language": language,
        "answer": answer,
        "analysisSummary": "已核对主要指标。" if language == "zh-CN" else "Primary metric checked.",
        "groundingReferences": ["result:primary-outcome"],
        "followUpSuggestions": [],
        "toolActivity": [
            {
                "tool": "PRIMARY_METRICS",
                "label": "主要指标",
                "itemCount": 1,
                "truncated": False,
                "evidenceId": "result:primary-outcome",
            }
        ],
        "provider": "zhipu",
        "model": "glm-5.2",
        "thinkingEnabled": False,
        "streamed": True,
        "promptTokens": 10,
        "completionTokens": 20,
        "cachedTokens": 0,
        "totalTokens": 30,
        "modelCalls": 1,
        "transportAttempts": 1,
        "uncertainBillableAttempts": 0,
        "cacheHit": False,
        "repairUsed": False,
        "plannerUsed": True,
        "plannerFallbackUsed": False,
        "failureCodes": [],
        "promptVersion": "result-interpreter-v1",
        "latencyMs": 123.4,
        "createdAt": datetime.now(UTC).isoformat(),
    }


def _saveExchange(
    database: Database,
    *,
    ownerUserId: str = "usr-owner-one",
    experimentId: str = "exp-result-one",
    conversationId: str = "conversation-one",
    clientRequestId: str = "request-one",
    requestHash: str = "a" * 64,
    userMessage: str = "请解释主要差异。",
    assistantMessage: dict | None = None,
) -> tuple[dict, bool]:
    return database.saveResultInterpretationExchange(
        ownerUserId=ownerUserId,
        experimentId=experimentId,
        conversationId=conversationId,
        clientRequestId=clientRequestId,
        requestHash=requestHash,
        language="zh-CN",
        userMessage=userMessage,
        assistantMessage=assistantMessage or _assistantMessage(f"message-{clientRequestId}"),
    )


def test_completed_exchange_round_trip_survives_process_restart(tmp_path: Path) -> None:
    databasePath = tmp_path / "eventshock.db"
    database = Database(databasePath)
    database.initialize()
    _createCompletedExperiment(database, "exp-result-one", "usr-owner-one")

    saved, created = _saveExchange(database)
    restartedDatabase = Database(databasePath)
    restartedDatabase.initialize()
    recovered = restartedDatabase.getResultInterpretationExchangeByRequest(
        ownerUserId="usr-owner-one",
        experimentId="exp-result-one",
        clientRequestId="request-one",
        requestHash="a" * 64,
    )

    assert created is True
    assert recovered == saved
    assert recovered is not None
    assert recovered["assistantMessage"]["answer"].startswith("干预组")


def test_exchange_idempotency_replays_final_and_hash_conflict_is_rejected(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    _createCompletedExperiment(database, "exp-result-one", "usr-owner-one")

    first, firstCreated = _saveExchange(database)
    replay, replayCreated = _saveExchange(
        database,
        # 即使调用方误传不同正文，相同幂等请求也只能取回首次严格验证的 final。
        userMessage="这段正文绝不能覆盖首次问答。",
        assistantMessage=_assistantMessage("message-overwrite-attempt"),
    )

    assert firstCreated is True
    assert replayCreated is False
    assert replay == first
    assert database.countResultInterpretationExchanges("usr-owner-one") == 1
    with pytest.raises(ResultInterpretationRequestConflictError):
        _saveExchange(database, requestHash="b" * 64)
    with pytest.raises(ResultInterpretationRequestConflictError):
        database.getResultInterpretationExchangeByRequest(
            ownerUserId="usr-owner-one",
            experimentId="exp-result-one",
            clientRequestId="request-one",
            requestHash="b" * 64,
        )


def test_conversations_are_strictly_isolated_by_owner_and_experiment(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    for experimentId, ownerUserId in (
        ("exp-result-one", "usr-owner-one"),
        ("exp-result-two", "usr-owner-one"),
        ("exp-result-three", "usr-owner-two"),
    ):
        _createCompletedExperiment(database, experimentId, ownerUserId)
    _saveExchange(database)
    _saveExchange(
        database,
        experimentId="exp-result-two",
        clientRequestId="request-two",
        requestHash="b" * 64,
    )
    _saveExchange(
        database,
        ownerUserId="usr-owner-two",
        experimentId="exp-result-three",
        clientRequestId="request-three",
        requestHash="c" * 64,
    )

    assert len(database.listResultInterpretationConversations("usr-owner-one")) == 2
    assert (
        len(
            database.listResultInterpretationConversations(
                "usr-owner-one", experimentId="exp-result-one"
            )
        )
        == 1
    )
    assert (
        database.listResultInterpretationConversations("usr-owner-two")[0]["experimentId"]
        == "exp-result-three"
    )
    assert (
        database.getResultInterpretationConversation(
            ownerUserId="usr-owner-two",
            experimentId="exp-result-one",
            conversationId="conversation-one",
        )
        is None
    )
    assert (
        database.getResultInterpretationConversation(
            ownerUserId="usr-owner-one",
            experimentId="exp-result-two",
            conversationId="conversation-one",
        )["experimentId"]
        == "exp-result-two"
    )


def test_conversation_history_orders_exchanges_and_delete_is_owner_scoped(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    _createCompletedExperiment(database, "exp-result-one", "usr-owner-one")
    _createCompletedExperiment(database, "exp-result-two", "usr-owner-two")
    _saveExchange(database)
    _saveExchange(
        database,
        clientRequestId="request-follow-up",
        requestHash="d" * 64,
        userMessage="这个差异可能由什么机制导致？",
    )
    _saveExchange(
        database,
        ownerUserId="usr-owner-two",
        experimentId="exp-result-two",
        clientRequestId="request-other-owner",
        requestHash="e" * 64,
    )

    conversation = database.getResultInterpretationConversation(
        ownerUserId="usr-owner-one",
        experimentId="exp-result-one",
        conversationId="conversation-one",
    )
    assert conversation is not None
    assert [item["clientRequestId"] for item in conversation["exchanges"]] == [
        "request-one",
        "request-follow-up",
    ]
    assert conversation["exchanges"][-1]["userMessage"].startswith("这个差异")
    assert (
        database.deleteResultInterpretationConversation(
            ownerUserId="usr-owner-two",
            experimentId="exp-result-one",
            conversationId="conversation-one",
        )
        is False
    )
    assert (
        database.deleteResultInterpretationConversation(
            ownerUserId="usr-owner-one",
            experimentId="exp-result-one",
            conversationId="conversation-one",
        )
        is True
    )
    assert database.countResultInterpretationExchanges("usr-owner-one") == 0
    assert database.countResultInterpretationExchanges("usr-owner-two") == 1


def test_delete_and_audit_commit_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    _createCompletedExperiment(database, "exp-result-one", "usr-owner-one")
    _saveExchange(database)

    def failAudit(*_args: object, **_kwargs: object) -> dict:
        raise RuntimeError("simulated audit storage failure")

    monkeypatch.setattr(
        Database,
        "_appendAuditEventInConnection",
        staticmethod(failAudit),
    )
    with pytest.raises(RuntimeError, match="simulated audit storage failure"):
        database.deleteResultInterpretationConversation(
            ownerUserId="usr-owner-one",
            experimentId="exp-result-one",
            conversationId="conversation-one",
            auditPayload={"conversationHash": "a" * 64},
        )

    assert database.countResultInterpretationExchanges("usr-owner-one") == 1


@pytest.mark.parametrize(
    ("forbiddenField", "value"),
    [
        ("apiKey", "super-secret-key"),
        ("rawReasoning", "private chain of thought"),
        ("thought", "private thought"),
        ("streamChunk", {"delta": "unverified fragment"}),
    ],
)
def test_private_or_unverified_fields_are_never_persisted(
    tmp_path: Path,
    forbiddenField: str,
    value: object,
) -> None:
    database = Database(tmp_path / f"{forbiddenField}.db")
    database.initialize()
    _createCompletedExperiment(database, "exp-result-one", "usr-owner-one")
    unsafeMessage = {**_assistantMessage("message-unsafe"), forbiddenField: value}

    with pytest.raises(ValueError):
        _saveExchange(database, assistantMessage=unsafeMessage)

    assert database.countResultInterpretationExchanges() == 0
    with sqlite3.connect(database.databasePath) as connection:
        connection.row_factory = sqlite3.Row
        rows = [
            dict(row) for row in connection.execute("SELECT * FROM result_interpretation_exchanges")
        ]
    serializedRows = json.dumps(rows, ensure_ascii=False)
    assert "super-secret-key" not in serializedRows
    assert "private chain of thought" not in serializedRows
    assert "unverified fragment" not in serializedRows


def test_credential_like_text_is_rejected_before_persistence(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    _createCompletedExperiment(database, "exp-result-one", "usr-owner-one")

    with pytest.raises(ValueError, match="credential-like"):
        _saveExchange(
            database,
            userMessage="My API key is sk-this-is-a-fake-but-secret-token-123456.",
        )
    unsafeAnswer = _assistantMessage("message-secret-answer")
    unsafeAnswer["answer"] = "API key is sk-this-is-another-fake-secret-token-987654."
    with pytest.raises(ValueError, match="credential-like"):
        _saveExchange(
            database,
            clientRequestId="request-secret-answer",
            requestHash="f" * 64,
            assistantMessage=unsafeAnswer,
        )

    assert database.countResultInterpretationExchanges() == 0


def test_text_beyond_security_scanner_limit_is_rejected_instead_of_partially_scanned(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    _createCompletedExperiment(database, "exp-result-one", "usr-owner-one")
    oversizedMessage = _assistantMessage("message-oversized")
    oversizedMessage["toolActivity"][0]["label"] = "x" * 100_100

    with pytest.raises(ValueError, match="safe scanning limit"):
        _saveExchange(database, assistantMessage=oversizedMessage)

    assert database.countResultInterpretationExchanges() == 0


def test_retention_prunes_expired_and_excess_exchanges(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    _createCompletedExperiment(database, "exp-result-one", "usr-owner-one")
    for index in range(4):
        _saveExchange(
            database,
            clientRequestId=f"request-{index:04d}",
            requestHash=f"{index + 1:064x}",
        )
    expiredAt = (datetime.now(UTC) - timedelta(days=91)).isoformat()
    with database.connection() as connection:
        connection.execute(
            """
            UPDATE result_interpretation_exchanges SET updated_at=?
            WHERE client_request_id='request-0000'
            """,
            (expiredAt,),
        )

    database.enforceResultInterpretationRetention(
        retentionDays=90,
        maxPerOwner=2,
        maxStored=10,
    )

    assert database.countResultInterpretationExchanges("usr-owner-one") == 2
    conversation = database.getResultInterpretationConversation(
        ownerUserId="usr-owner-one",
        experimentId="exp-result-one",
        conversationId="conversation-one",
    )
    assert conversation is not None
    assert [exchange["clientRequestId"] for exchange in conversation["exchanges"]] == [
        "request-0002",
        "request-0003",
    ]


def test_expired_exchange_is_hidden_immediately_and_pruned_when_app_restarts(
    tmp_path: Path,
) -> None:
    databasePath = tmp_path / "eventshock.db"
    database = Database(databasePath)
    database.initialize()
    _createCompletedExperiment(database, "exp-result-one", "usr-owner-one")
    _saveExchange(database)
    expiredAt = (datetime.now(UTC) - timedelta(days=91)).isoformat()
    with database.connection() as connection:
        connection.execute(
            """
            UPDATE result_interpretation_exchanges SET updated_at=?
            WHERE owner_user_id=? AND experiment_id=? AND client_request_id=?
            """,
            (expiredAt, "usr-owner-one", "exp-result-one", "request-one"),
        )

    # 读取路径本身必须执行 90 天边界，不能等下一次写入或进程重启才隐藏旧内容。
    assert database.listResultInterpretationConversations("usr-owner-one") == []
    assert (
        database.getResultInterpretationConversation(
            ownerUserId="usr-owner-one",
            experimentId="exp-result-one",
            conversationId="conversation-one",
        )
        is None
    )
    assert (
        database.getResultInterpretationExchangeByRequest(
            ownerUserId="usr-owner-one",
            experimentId="exp-result-one",
            clientRequestId="request-one",
            requestHash="a" * 64,
        )
        is None
    )
    assert database.countResultInterpretationExchanges("usr-owner-one") == 1

    # FastAPI 生命周期启动时执行物理清理，避免到期正文无限留在 SQLite 中。
    with TestClient(createApp(tmp_path)) as restartedClient:
        assert (
            restartedClient.app.state.database.countResultInterpretationExchanges("usr-owner-one")
            == 0
        )
