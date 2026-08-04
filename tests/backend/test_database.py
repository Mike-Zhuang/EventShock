import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import backend.app.database as databaseModule
from backend.app.database import (
    DEFAULT_EXPERIMENT_RETENTION_DAYS,
    CheckpointTooLargeError,
    Database,
)


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
    database.updateExperiment(
        "exp-recovery-test",
        "test-session-recovery",
        status="RUNNING",
        started_at="now",
    )

    restartedDatabase = Database(databasePath)
    restartedDatabase.initialize()
    recovered = restartedDatabase.getExperiment("exp-recovery-test", "test-session-recovery")

    assert recovered is not None
    assert recovered["status"] == "FAILED_RETRYABLE"
    assert recovered["errorCode"] == "SERVER_RESTARTED"
    assert recovered["completedAt"] is not None


def test_event_pack_draft_and_audit_are_committed_atomically(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    sessionId = "test-session-atomic-review"
    eventPackId = "event-pack-atomic-review"
    claims = [{"claimId": "claim-1", "reviewStatus": "HUMAN_APPROVED"}]

    # 审计 payload 无法序列化时，之前执行的 draft UPSERT 也必须回滚。
    with pytest.raises(TypeError):
        database.saveEventPackDraftWithAudit(
            sessionId,
            eventPackId,
            claims,
            auditAction="BULK_CLAIMS_APPROVED",
            auditPayload={"invalid": object()},
        )

    assert database.getEventPackDraft(sessionId, eventPackId) is None
    assert database.listAuditEvents(sessionId) == []


def test_reextracted_pack_draft_and_audit_are_committed_atomically(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    sessionId = "test-session-atomic-extraction"
    eventPackId = "event-pack-atomic-extraction"
    originalClaims = [{"claimId": "claim-old", "reviewStatus": "HUMAN_APPROVED"}]
    database.saveCustomEventPack(
        sessionId,
        eventPackId,
        {"id": eventPackId, "title": "Original"},
        originalClaims,
    )
    database.saveEventPackDraft(sessionId, eventPackId, originalClaims, False, None)

    # 最后的审计序列化失败时，manifest 与 draft 都不能停留在新版本。
    with pytest.raises(TypeError):
        database.saveExtractedEventPackWithAudit(
            sessionId,
            eventPackId,
            {"id": eventPackId, "title": "Replacement"},
            [{"claimId": "claim-new", "reviewStatus": "AI_PROPOSED"}],
            auditAction="CLAIMS_EXTRACTED",
            auditPayload={"invalid": object()},
        )

    storedPack = database.getCustomEventPack(sessionId, eventPackId)
    storedDraft = database.getEventPackDraft(sessionId, eventPackId)
    assert storedPack is not None and storedPack["title"] == "Original"
    assert storedPack["claims"] == originalClaims
    assert storedDraft is not None and storedDraft["claims"] == originalClaims
    assert database.listAuditEvents(sessionId) == []


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
        "test-session-retention",
        status="COMPLETED",
        result_json={"large": "result"},
        completed_at="2000-01-01T00:00:00+00:00",
    )

    database.enforceRetention(retentionDays=7)

    assert database.countExperiments() == 0


def test_default_terminal_result_retention_is_ninety_days(tmp_path: Path) -> None:
    assert DEFAULT_EXPERIMENT_RETENTION_DAYS == 90
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    now = datetime.now(UTC)
    for experimentId, ageDays in (("exp-retained", 89), ("exp-expired", 91)):
        database.createExperiment(
            experimentId,
            "test-session-default-retention",
            {"eventPackId": "spacex-synthetic-v1", "seedCount": 10},
            None,
        )
        database.updateExperiment(
            experimentId,
            "test-session-default-retention",
            status="COMPLETED",
            result_json={"large": "result"},
            completed_at=(now - timedelta(days=ageDays)).isoformat(),
        )

    database.enforceRetention()

    assert database.getExperiment("exp-retained", "test-session-default-retention") is not None
    assert database.getExperiment("exp-expired", "test-session-default-retention") is None


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


def test_retention_never_deletes_unowned_legacy_records(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    database.saveScenario(
        "scn-unowned-legacy",
        "legacy-browser-session",
        "Legacy scenario",
        {"eventPackId": "spacex-synthetic-v1"},
        False,
    )
    with database.connection() as connection:
        connection.execute(
            """
            UPDATE scenarios
            SET owner_user_id='', updated_at='2000-01-01T00:00:00+00:00'
            WHERE id='scn-unowned-legacy'
            """
        )

    database.enforceRetention(retentionDays=7)

    with database.connection() as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM scenarios WHERE id='scn-unowned-legacy'"
        ).fetchone()[0]
    assert remaining == 1


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
        "checkpoint-session",
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


@pytest.mark.parametrize("seedCount", [25, 50])
def test_normalized_checkpoint_pairs_round_trip_without_growing_metadata_blob(
    tmp_path: Path,
    seedCount: int,
) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    experimentId = "exp-normalized-checkpoint"
    owner = "checkpoint-session"
    database.createExperiment(
        experimentId,
        owner,
        {"eventPackId": "spacex-synthetic-v1", "seedCount": seedCount},
        None,
    )
    metadata = {
        "schemaVersion": "2.0.0",
        "pairStorage": "NORMALIZED_V1",
        "completedPairs": 0,
        "cognitionRun": {"signals": []},
    }
    database.updateExperiment(
        experimentId,
        owner,
        checkpoint_blob=metadata,
        completed_pairs=0,
    )
    with database.connection() as connection:
        initialMetadataBytes = len(
            connection.execute(
                "SELECT checkpoint_blob FROM experiments WHERE id=?",
                (experimentId,),
            ).fetchone()[0]
        )

    for pairIndex in range(seedCount):
        seed = 2026070700 + pairIndex
        telemetry = database.saveExperimentCheckpointPair(
            experimentId=experimentId,
            ownerUserId=owner,
            pairIndex=pairIndex,
            seed=seed,
            baselineRun={"seed": seed, "metrics": {"maxSpreadBps": 10 + pairIndex}},
            interventionRun={"seed": seed, "metrics": {"maxSpreadBps": 12 + pairIndex}},
            populationSize=56,
            steps=120,
        )
        metadata["completedPairs"] = pairIndex + 1
        database.updateExperiment(
            experimentId,
            owner,
            checkpoint_blob=metadata,
            completed_pairs=pairIndex + 1,
        )

    # 模拟服务进程重启：新实例必须能从 SQLite 恢复元数据和所有配对行。
    restartedDatabase = Database(tmp_path / "eventshock.db")
    restartedDatabase.initialize()
    restored = restartedDatabase.getExperiment(experimentId, owner)
    with database.connection() as connection:
        finalMetadataBytes = len(
            connection.execute(
                "SELECT checkpoint_blob FROM experiments WHERE id=?",
                (experimentId,),
            ).fetchone()[0]
        )
    estimate = restartedDatabase.estimateCheckpointCapacity(
        populationSize=56,
        steps=120,
        seedCount=seedCount,
    )

    assert restored is not None
    assert restored["checkpoint"]["completedPairs"] == seedCount
    assert len(restored["checkpointPairs"]) == seedCount
    assert restored["checkpointPairs"][0]["seed"] == 2026070700
    assert restored["checkpointPairs"][-1]["seed"] == 2026070700 + seedCount - 1
    assert telemetry["pairCount"] == seedCount
    assert finalMetadataBytes - initialMetadataBytes < 32
    assert estimate["sampleCount"] == seedCount
    assert estimate["estimatedStoredBytes"] > 0


def test_normalized_checkpoint_detects_hash_corruption_and_pair_size_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    experimentId = "exp-normalized-corrupt"
    owner = "checkpoint-session"
    database.createExperiment(experimentId, owner, {"seedCount": 10}, None)
    database.updateExperiment(
        experimentId,
        owner,
        checkpoint_blob={
            "schemaVersion": "2.0.0",
            "pairStorage": "NORMALIZED_V1",
            "completedPairs": 1,
        },
        completed_pairs=1,
    )
    database.saveExperimentCheckpointPair(
        experimentId=experimentId,
        ownerUserId=owner,
        pairIndex=0,
        seed=101,
        baselineRun={"seed": 101, "metrics": {}},
        interventionRun={"seed": 101, "metrics": {}},
        populationSize=56,
        steps=120,
    )
    with database.writeLock, database.connection() as connection:
        connection.execute(
            "UPDATE experiment_checkpoint_pairs SET payload_hash=? WHERE experiment_id=?",
            ("0" * 64, experimentId),
        )
    corrupted = database.getExperiment(experimentId, owner)
    assert corrupted is not None
    assert corrupted["checkpointCorrupted"] is True
    assert corrupted["checkpointErrorCode"] == "CHECKPOINT_CORRUPTED"

    monkeypatch.setattr(databaseModule, "MAX_CHECKPOINT_PAIR_UNCOMPRESSED_BYTES", 256)
    with pytest.raises(CheckpointTooLargeError, match="reviewed limit"):
        database.saveExperimentCheckpointPair(
            experimentId=experimentId,
            ownerUserId=owner,
            pairIndex=1,
            seed=102,
            baselineRun={"seed": 102, "padding": "x" * 1_000},
            interventionRun={"seed": 102, "metrics": {}},
            populationSize=56,
            steps=120,
        )


def test_retryable_claim_preserves_checkpoint_but_ready_claim_starts_clean(tmp_path: Path) -> None:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    request = {"eventPackId": "spacex-synthetic-v1", "seedCount": 10}
    checkpoint = {"schemaVersion": "1.0.0", "baselineRuns": [{"seed": 101}]}

    database.createExperiment("exp-ready-clean", "checkpoint-session", request, None)
    database.updateExperiment(
        "exp-ready-clean",
        "checkpoint-session",
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
        "checkpoint-session",
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
        "owner-session",
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


def test_legacy_anonymous_records_are_claimed_without_collisions_or_audit_rewrite(
    tmp_path: Path,
) -> None:
    databasePath = tmp_path / "legacy.db"
    with sqlite3.connect(databasePath) as connection:
        connection.executescript(
            """
            CREATE TABLE custom_event_packs (
                session_id TEXT NOT NULL,
                event_pack_id TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                claims_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, event_pack_id)
            );
            CREATE TABLE audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_hash TEXT,
                event_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            """
        )
        for sessionId, title, createdAt in (
            ("legacy-session-one", "Older pack", "2026-07-01T00:00:00+00:00"),
            ("legacy-session-two", "Latest pack", "2026-07-02T00:00:00+00:00"),
        ):
            connection.execute(
                """
                INSERT INTO custom_event_packs(
                    session_id, event_pack_id, manifest_json, claims_json,
                    created_at, updated_at
                ) VALUES (?, 'duplicate-pack', ?, '[]', ?, ?)
                """,
                (sessionId, json.dumps({"title": title}), createdAt, createdAt),
            )
            payloadJson = "{}"
            material = "|".join(
                (sessionId, "EVENT_PACK", "duplicate-pack", "CREATED", payloadJson, "", createdAt)
            )
            connection.execute(
                """
                INSERT INTO audit_events(
                    session_id, entity_type, entity_id, action, payload_json,
                    previous_hash, event_hash, created_at
                ) VALUES (?, 'EVENT_PACK', 'duplicate-pack', 'CREATED', ?, NULL, ?, ?)
                """,
                (sessionId, payloadJson, hashlib.sha256(material.encode()).hexdigest(), createdAt),
            )

    database = Database(databasePath)
    database.initialize()
    before = database.countUnownedRecords()
    assert before["custom_event_packs"] == 2
    assert before["audit_events"] == 2

    claimed = database.claimLegacyRecords("usr-admin-owner")

    assert claimed["custom_event_packs"] == 2
    assert claimed["audit_events"] == 2
    assert all(count == 0 for count in database.countUnownedRecords().values())
    assert all(count == 0 for count in database.claimLegacyRecords("usr-admin-owner").values())
    packs = database.listCustomEventPacks("usr-admin-owner")
    assert len(packs) == 1
    assert packs[0]["title"] == "Latest pack"
    verification = database.verifyAuditChain("usr-admin-owner")
    assert verification["valid"] is True
    assert verification["eventCount"] == 2
    assert verification["chainCount"] == 2
    with database.connection() as connection:
        sessions = {
            row["session_id"]
            for row in connection.execute("SELECT session_id FROM audit_events").fetchall()
        }
    assert sessions == {"legacy-session-one", "legacy-session-two"}
