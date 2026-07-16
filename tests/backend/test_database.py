import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.app.database import Database


def test_initialize_marks_interrupted_experiment_retryable(tmp_path: Path) -> None:
    databasePath = tmp_path / "eventshock.db"
    database = Database(databasePath)
    database.initialize()
    requestData = {
        "eventPackId": "spacex-synthetic-v1",
        "seedCount": 10,
    }
    database.createExperiment(
        "exp-recovery-test",
        "test-session-recovery",
        requestData,
        None,
    )
    database.updateExperiment("exp-recovery-test", status="RUNNING", started_at="now")

    restartedDatabase = Database(databasePath)
    restartedDatabase.initialize()
    recovered = restartedDatabase.getExperiment("exp-recovery-test", "test-session-recovery")

    assert recovered is not None
    assert recovered["status"] == "FAILED_RETRYABLE"
    assert recovered["errorCode"] == "SERVER_RESTARTED"
    assert recovered["completedAt"] is not None


def test_ready_experiment_can_be_claimed_for_queue_only_once(tmp_path: Path) -> None:
    databasePath = tmp_path / "eventshock.db"
    firstDatabase = Database(databasePath)
    secondDatabase = Database(databasePath)
    firstDatabase.initialize()
    firstDatabase.createExperiment(
        "exp-atomic-start",
        "test-session-atomic",
        {"eventPackId": "spacex-synthetic-v1", "seedCount": 10},
        None,
    )
    barrier = threading.Barrier(2)

    def claim(database: Database) -> bool:
        barrier.wait()
        return database.claimExperimentForQueue("exp-atomic-start", "test-session-atomic")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, (firstDatabase, secondDatabase)))

    assert sorted(results) == [False, True]
    experiment = firstDatabase.getExperiment("exp-atomic-start", "test-session-atomic")
    assert experiment is not None
    assert experiment["status"] == "QUEUED"


def test_retention_removes_expired_terminal_results(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    database.createExperiment(
        "exp-expired",
        "test-session-retention",
        {"eventPackId": "spacex-synthetic-v1", "seedCount": 10},
        None,
    )
    database.updateExperiment(
        "exp-expired",
        status="COMPLETED",
        result_json={"large": "result"},
        completed_at="2000-01-01T00:00:00+00:00",
    )

    database.enforceRetention(retentionDays=7)

    assert database.countExperiments() == 0


def test_retention_removes_stale_ready_and_rolls_session_history(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    for index in range(3):
        database.createExperiment(
            f"exp-ready-{index}",
            "test-session-ready-retention",
            {"eventPackId": "spacex-synthetic-v1", "seedCount": 10},
            None,
        )
    with database.connection() as connection:
        connection.execute(
            "UPDATE experiments SET updated_at='2000-01-01T00:00:00+00:00' WHERE id='exp-ready-0'"
        )

    database.enforceRetention(readyRetentionHours=24)
    assert database.countExperiments("test-session-ready-retention") == 2

    database.pruneSessionExperiments("test-session-ready-retention", maxRetained=1)
    assert database.countExperiments("test-session-ready-retention") == 1


def test_audit_hash_chain_detects_history_tampering(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    sessionId = "test-session-audit-chain"
    first = database.appendAuditEvent(
        sessionId,
        "EVENT_PACK",
        "pack-1",
        "CREATED",
        {"claimCount": 3},
    )
    second = database.appendAuditEvent(
        sessionId,
        "EVENT_PACK",
        "pack-1",
        "FROZEN",
        {"claimCount": 3},
    )

    verified = database.verifyAuditChain(sessionId)
    assert verified == {
        "valid": True,
        "eventCount": 2,
        "firstInvalidEventId": None,
        "headHash": second["eventHash"],
    }
    assert second["previousHash"] == first["eventHash"]

    with database.connection() as connection:
        connection.execute(
            "UPDATE audit_events SET payload_json=? WHERE id=?",
            ('{"claimCount":999}', first["id"]),
        )

    invalid = database.verifyAuditChain(sessionId)
    assert invalid["valid"] is False
    assert invalid["firstInvalidEventId"] == first["id"]


def test_retention_removes_session_artifacts_and_only_whole_audit_chains(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    expiredSession = "expired-session-artifacts"
    activeSession = "active-session-artifacts"
    database.saveCustomEventPack(
        expiredSession,
        "custom-expired-pack",
        {"id": "custom-expired-pack"},
        [],
    )
    database.saveScenario(
        "scn-expired-artifact",
        expiredSession,
        "Expired scenario",
        {"eventPackId": "custom-expired-pack"},
        False,
    )
    database.appendAuditEvent(expiredSession, "SCENARIO", "scn-1", "CREATED", {})
    database.appendAuditEvent(activeSession, "SCENARIO", "scn-2", "CREATED", {})
    with database.connection() as connection:
        connection.execute("UPDATE custom_event_packs SET updated_at='2000-01-01T00:00:00+00:00'")
        connection.execute("UPDATE scenarios SET updated_at='2000-01-01T00:00:00+00:00'")
        connection.execute(
            "UPDATE audit_events SET created_at='2000-01-01T00:00:00+00:00' WHERE session_id=?",
            (expiredSession,),
        )

    database.enforceRetention()

    assert database.getCustomEventPack(expiredSession, "custom-expired-pack") is None
    assert database.getScenario("scn-expired-artifact", expiredSession) is None
    assert database.verifyAuditChain(expiredSession)["eventCount"] == 0
    assert database.verifyAuditChain(activeSession)["eventCount"] == 1


def test_experiment_runtime_and_compressed_checkpoint_round_trip(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    database.createExperiment(
        "exp-checkpoint-roundtrip",
        "checkpoint-session",
        {"eventPackId": "spacex-synthetic-v1", "seedCount": 10},
        None,
    )
    runtime = {
        "phase": "INTERVENTION",
        "currentSeed": 123_456,
        "logs": [{"timestamp": "now", "level": "INFO", "message": "Pair completed."}],
    }
    checkpoint = {
        "schemaVersion": "1.0.0",
        "baselineRuns": [{"seed": 123_456, "metrics": {"maxSpreadBps": 12.5}}],
        "interventionRuns": [{"seed": 123_456, "metrics": {"maxSpreadBps": 18.0}}],
        "cognitionRun": {"signals": []},
    }

    database.updateExperiment(
        "exp-checkpoint-roundtrip",
        runtime_json=runtime,
        checkpoint_blob=checkpoint,
        completed_pairs=1,
    )
    restored = database.getExperiment("exp-checkpoint-roundtrip", "checkpoint-session")

    assert restored is not None
    assert restored["runtime"] == runtime
    assert restored["checkpoint"] == checkpoint
    assert restored["checkpointCorrupted"] is False
    with database.connection() as connection:
        row = connection.execute(
            "SELECT checkpoint_blob FROM experiments WHERE id='exp-checkpoint-roundtrip'"
        ).fetchone()
    assert row is not None
    assert b'"baselineRuns"' not in row["checkpoint_blob"]


def test_retryable_claim_preserves_checkpoint_but_ready_claim_starts_clean(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    request = {"eventPackId": "spacex-synthetic-v1", "seedCount": 10}
    checkpoint = {"schemaVersion": "1.0.0", "baselineRuns": [{"seed": 101}]}

    database.createExperiment("exp-ready-clean", "checkpoint-session", request, None)
    database.updateExperiment(
        "exp-ready-clean",
        checkpoint_blob=checkpoint,
        completed_pairs=1,
    )
    assert database.claimExperimentForQueue("exp-ready-clean", "checkpoint-session") is True
    readyClaim = database.getExperiment("exp-ready-clean", "checkpoint-session")
    assert readyClaim is not None
    assert readyClaim["checkpoint"] is None
    assert readyClaim["completedPairs"] == 0

    database.createExperiment("exp-retry-resume", "checkpoint-session", request, None)
    database.updateExperiment(
        "exp-retry-resume",
        status="RUNNING",
        checkpoint_blob=checkpoint,
        completed_pairs=1,
    )
    database.initialize()
    interrupted = database.getExperiment("exp-retry-resume", "checkpoint-session")
    assert interrupted is not None
    assert interrupted["status"] == "FAILED_RETRYABLE"
    assert database.claimExperimentForQueue("exp-retry-resume", "checkpoint-session") is True
    retryClaim = database.getExperiment("exp-retry-resume", "checkpoint-session")
    assert retryClaim is not None
    assert retryClaim["checkpoint"] == checkpoint
    assert retryClaim["completedPairs"] == 1


def test_corrupt_checkpoint_is_reported_without_breaking_experiment_listing(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    database.createExperiment(
        "exp-corrupt-checkpoint",
        "checkpoint-session",
        {"eventPackId": "spacex-synthetic-v1", "seedCount": 10},
        None,
    )
    with database.connection() as connection:
        connection.execute(
            "UPDATE experiments SET checkpoint_blob=? WHERE id=?",
            (b"not-a-valid-zlib-payload", "exp-corrupt-checkpoint"),
        )

    restored = database.getExperiment("exp-corrupt-checkpoint", "checkpoint-session")
    assert restored is not None
    assert restored["checkpoint"] is None
    assert restored["checkpointCorrupted"] is True
    assert database.listExperiments("checkpoint-session")[0]["id"] == "exp-corrupt-checkpoint"


def test_completed_experiment_invalidation_is_atomic_session_scoped_and_preserves_result(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    database.createExperiment(
        "exp-invalidation",
        "owner-session",
        {"eventPackId": "spacex-synthetic-v1", "seedCount": 10},
        None,
    )
    result = {"manifest": {"engineVersion": "test-v1"}, "pairedRuns": [{"seed": 101}]}
    database.updateExperiment(
        "exp-invalidation",
        status="COMPLETED",
        result_json=result,
        completed_at="2026-07-15T00:00:00+00:00",
    )

    assert (
        database.invalidateCompletedExperiment(
            "exp-invalidation",
            "other-session",
            reasonCode="MODEL_ISSUE",
            reason="Wrong session must not change this experiment.",
        )
        is False
    )
    assert (
        database.invalidateCompletedExperiment(
            "exp-invalidation",
            "owner-session",
            reasonCode="MODEL_ISSUE",
            reason="The model version failed a post-release validation check.",
        )
        is True
    )
    # 重复请求必须幂等，不能覆盖首次审计原因。
    assert (
        database.invalidateCompletedExperiment(
            "exp-invalidation",
            "owner-session",
            reasonCode="OTHER",
            reason="A later request must not rewrite the original reason.",
        )
        is False
    )

    invalidated = database.getExperiment("exp-invalidation", "owner-session")
    assert invalidated is not None
    assert invalidated["status"] == "INVALIDATED"
    assert invalidated["result"] == result
    assert invalidated["completedAt"] == "2026-07-15T00:00:00+00:00"
    assert invalidated["invalidatedAt"] is not None
    assert invalidated["invalidationReasonCode"] == "MODEL_ISSUE"
    assert (
        invalidated["invalidationReason"]
        == "The model version failed a post-release validation check."
    )
