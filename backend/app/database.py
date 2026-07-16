"""SQLite 控制面持久化；每个调用使用独立连接以兼容后台线程。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

MAX_CHECKPOINT_UNCOMPRESSED_BYTES = 32 * 1024 * 1024


def utcNow() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, databasePath: Path) -> None:
        self.databasePath = databasePath
        self.writeLock = threading.RLock()

    def initialize(self) -> None:
        self.databasePath.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS event_pack_drafts (
                    session_id TEXT NOT NULL,
                    event_pack_id TEXT NOT NULL,
                    claims_json TEXT NOT NULL,
                    frozen INTEGER NOT NULL DEFAULT 0,
                    frozen_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, event_pack_id)
                );
                CREATE TABLE IF NOT EXISTS custom_event_packs (
                    session_id TEXT NOT NULL,
                    event_pack_id TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    claims_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, event_pack_id)
                );
                CREATE TABLE IF NOT EXISTS scenarios (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    frozen INTEGER NOT NULL DEFAULT 0,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scenarios_session_updated
                ON scenarios(session_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS audit_events (
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
                CREATE INDEX IF NOT EXISTS idx_audit_session_created
                ON audit_events(session_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    idempotency_key TEXT,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    error_code TEXT,
                    progress REAL NOT NULL DEFAULT 0,
                    completed_pairs INTEGER NOT NULL DEFAULT 0,
                    total_pairs INTEGER NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    runtime_json TEXT,
                    checkpoint_blob BLOB,
                    invalidated_at TEXT,
                    invalidation_reason_code TEXT,
                    invalidation_reason TEXT,
                    UNIQUE (session_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_experiments_session_created
                ON experiments(session_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS study_runs (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    event_pack_id TEXT NOT NULL,
                    study_id TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    spec_hash TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_study_runs_session_created
                ON study_runs(session_id, created_at DESC);
                """
            )
            experimentColumns = {
                row["name"] for row in connection.execute("PRAGMA table_info(experiments)")
            }
            if "runtime_json" not in experimentColumns:
                connection.execute("ALTER TABLE experiments ADD COLUMN runtime_json TEXT")
            if "checkpoint_blob" not in experimentColumns:
                connection.execute("ALTER TABLE experiments ADD COLUMN checkpoint_blob BLOB")
            if "invalidated_at" not in experimentColumns:
                connection.execute("ALTER TABLE experiments ADD COLUMN invalidated_at TEXT")
            if "invalidation_reason_code" not in experimentColumns:
                connection.execute(
                    "ALTER TABLE experiments ADD COLUMN invalidation_reason_code TEXT"
                )
            if "invalidation_reason" not in experimentColumns:
                connection.execute("ALTER TABLE experiments ADD COLUMN invalidation_reason TEXT")
            now = utcNow()
            connection.execute(
                """
                UPDATE experiments
                SET status='FAILED_RETRYABLE', error_code='SERVER_RESTARTED',
                    completed_at=?, updated_at=?
                WHERE status IN ('QUEUED', 'RUNNING', 'AGGREGATING', 'CANCEL_REQUESTED')
                """,
                (now, now),
            )
        self.enforceRetention()

    def ping(self) -> bool:
        try:
            with self.connection() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.databasePath, timeout=15, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def getEventPackDraft(self, sessionId: str, eventPackId: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM event_pack_drafts WHERE session_id=? AND event_pack_id=?",
                (sessionId, eventPackId),
            ).fetchone()
        if row is None:
            return None
        return {
            "claims": json.loads(row["claims_json"]),
            "frozen": bool(row["frozen"]),
            "frozenAt": row["frozen_at"],
            "updatedAt": row["updated_at"],
        }

    def saveEventPackDraft(
        self,
        sessionId: str,
        eventPackId: str,
        claims: list[dict[str, Any]],
        frozen: bool,
        frozenAt: str | None,
    ) -> None:
        now = utcNow()
        with self.writeLock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO event_pack_drafts(
                    session_id, event_pack_id, claims_json, frozen, frozen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, event_pack_id) DO UPDATE SET
                    claims_json=excluded.claims_json,
                    frozen=excluded.frozen,
                    frozen_at=excluded.frozen_at,
                    updated_at=excluded.updated_at
                """,
                (
                    sessionId,
                    eventPackId,
                    json.dumps(claims, ensure_ascii=False, separators=(",", ":")),
                    int(frozen),
                    frozenAt,
                    now,
                ),
            )

    def saveCustomEventPack(
        self,
        sessionId: str,
        eventPackId: str,
        manifest: dict[str, Any],
        claims: list[dict[str, Any]],
    ) -> None:
        """保存匿名会话创建的 Event Pack；不会覆盖仓库内的规范包。"""
        now = utcNow()
        manifestJson = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
        claimsJson = json.dumps(claims, ensure_ascii=False, separators=(",", ":"))
        with self.writeLock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO custom_event_packs(
                    session_id, event_pack_id, manifest_json, claims_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, event_pack_id) DO UPDATE SET
                    manifest_json=excluded.manifest_json,
                    claims_json=excluded.claims_json,
                    updated_at=excluded.updated_at
                """,
                (sessionId, eventPackId, manifestJson, claimsJson, now, now),
            )

    def getCustomEventPack(self, sessionId: str, eventPackId: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT manifest_json, claims_json, created_at, updated_at
                FROM custom_event_packs WHERE session_id=? AND event_pack_id=?
                """,
                (sessionId, eventPackId),
            ).fetchone()
        if row is None:
            return None
        manifest = json.loads(row["manifest_json"])
        manifest["claims"] = json.loads(row["claims_json"])
        manifest["createdAt"] = row["created_at"]
        manifest["updatedAt"] = row["updated_at"]
        return manifest

    def listCustomEventPacks(self, sessionId: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT event_pack_id, manifest_json, created_at, updated_at
                FROM custom_event_packs WHERE session_id=? ORDER BY updated_at DESC
                """,
                (sessionId,),
            ).fetchall()
        return [
            {
                **json.loads(row["manifest_json"]),
                "id": row["event_pack_id"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
            for row in rows
        ]

    def saveScenario(
        self,
        scenarioId: str,
        sessionId: str,
        name: str,
        config: dict[str, Any],
        frozen: bool,
    ) -> dict[str, Any]:
        now = utcNow()
        configJson = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        contentHash = hashlib.sha256(configJson.encode()).hexdigest()
        with self.writeLock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO scenarios(
                    id, session_id, name, config_json, frozen, content_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    config_json=excluded.config_json,
                    frozen=excluded.frozen,
                    content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at
                WHERE scenarios.session_id=excluded.session_id
                """,
                (scenarioId, sessionId, name, configJson, int(frozen), contentHash, now, now),
            )
        scenario = self.getScenario(scenarioId, sessionId)
        if scenario is None:
            raise RuntimeError("scenario could not be persisted")
        return scenario

    def getScenario(self, scenarioId: str, sessionId: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM scenarios WHERE id=? AND session_id=?",
                (scenarioId, sessionId),
            ).fetchone()
        return self._scenarioFromRow(row) if row is not None else None

    def listScenarios(self, sessionId: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM scenarios WHERE session_id=? ORDER BY updated_at DESC LIMIT 100",
                (sessionId,),
            ).fetchall()
        return [self._scenarioFromRow(row) for row in rows]

    def deleteScenario(self, scenarioId: str, sessionId: str) -> bool:
        with self.writeLock, self.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM scenarios WHERE id=? AND session_id=? AND frozen=0",
                (scenarioId, sessionId),
            )
        return cursor.rowcount == 1

    def appendAuditEvent(
        self,
        sessionId: str,
        entityType: str,
        entityId: str,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """追加 hash-chain 审计事件，历史记录没有更新或删除接口。"""
        createdAt = utcNow()
        payloadJson = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.writeLock, self.connection() as connection:
            previousRow = connection.execute(
                "SELECT event_hash FROM audit_events WHERE session_id=? ORDER BY id DESC LIMIT 1",
                (sessionId,),
            ).fetchone()
            previousHash = previousRow["event_hash"] if previousRow else None
            material = "|".join(
                (
                    sessionId,
                    entityType,
                    entityId,
                    action,
                    payloadJson,
                    previousHash or "",
                    createdAt,
                )
            )
            eventHash = hashlib.sha256(material.encode()).hexdigest()
            cursor = connection.execute(
                """
                INSERT INTO audit_events(
                    session_id, entity_type, entity_id, action, payload_json,
                    previous_hash, event_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sessionId,
                    entityType,
                    entityId,
                    action,
                    payloadJson,
                    previousHash,
                    eventHash,
                    createdAt,
                ),
            )
        return {
            "id": cursor.lastrowid,
            "entityType": entityType,
            "entityId": entityId,
            "action": action,
            "payload": payload,
            "previousHash": previousHash,
            "eventHash": eventHash,
            "createdAt": createdAt,
        }

    def listAuditEvents(self, sessionId: str, limit: int = 100) -> list[dict[str, Any]]:
        safeLimit = max(1, min(limit, 500))
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM audit_events WHERE session_id=? ORDER BY id DESC LIMIT ?
                """,
                (sessionId, safeLimit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "entityType": row["entity_type"],
                "entityId": row["entity_id"],
                "action": row["action"],
                "payload": json.loads(row["payload_json"]),
                "previousHash": row["previous_hash"],
                "eventHash": row["event_hash"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def verifyAuditChain(self, sessionId: str) -> dict[str, Any]:
        """从头重算会话审计链，检测历史记录或链指针是否被篡改。"""
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE session_id=? ORDER BY id ASC",
                (sessionId,),
            ).fetchall()
        previousHash: str | None = None
        for row in rows:
            material = "|".join(
                (
                    sessionId,
                    row["entity_type"],
                    row["entity_id"],
                    row["action"],
                    row["payload_json"],
                    previousHash or "",
                    row["created_at"],
                )
            )
            calculatedHash = hashlib.sha256(material.encode()).hexdigest()
            if row["previous_hash"] != previousHash or row["event_hash"] != calculatedHash:
                return {
                    "valid": False,
                    "eventCount": len(rows),
                    "firstInvalidEventId": row["id"],
                    "headHash": previousHash,
                }
            previousHash = row["event_hash"]
        return {
            "valid": True,
            "eventCount": len(rows),
            "firstInvalidEventId": None,
            "headHash": previousHash,
        }

    def createExperiment(
        self,
        experimentId: str,
        sessionId: str,
        requestData: dict[str, Any],
        idempotencyKey: str | None,
    ) -> tuple[dict[str, Any], bool]:
        now = utcNow()
        with self.writeLock, self.connection() as connection:
            if idempotencyKey:
                existingRow = connection.execute(
                    "SELECT * FROM experiments WHERE session_id=? AND idempotency_key=?",
                    (sessionId, idempotencyKey),
                ).fetchone()
                if existingRow is not None:
                    return self._experimentFromRow(existingRow), False
            connection.execute(
                """
                INSERT INTO experiments(
                    id, session_id, idempotency_key, status, request_json, total_pairs,
                    created_at, updated_at, runtime_json
                ) VALUES (?, ?, ?, 'READY', ?, ?, ?, ?, ?)
                """,
                (
                    experimentId,
                    sessionId,
                    idempotencyKey,
                    json.dumps(requestData, ensure_ascii=False, separators=(",", ":")),
                    requestData["seedCount"],
                    now,
                    now,
                    json.dumps(
                        {
                            "phase": "READY",
                            "logs": [
                                {
                                    "timestamp": now,
                                    "level": "INFO",
                                    "message": "Experiment configuration is ready for execution.",
                                }
                            ],
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
            )
            row = connection.execute(
                "SELECT * FROM experiments WHERE id=?", (experimentId,)
            ).fetchone()
        return self._experimentFromRow(row), True

    def getExperimentByIdempotencyKey(
        self, sessionId: str, idempotencyKey: str
    ) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM experiments WHERE session_id=? AND idempotency_key=?",
                (sessionId, idempotencyKey),
            ).fetchone()
        return self._experimentFromRow(row) if row is not None else None

    def claimExperimentForQueue(self, experimentId: str, sessionId: str) -> bool:
        now = utcNow()
        with self.writeLock, self.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE experiments
                SET status='QUEUED', error_code=NULL, progress=0,
                    completed_pairs=CASE WHEN status='READY' THEN 0 ELSE completed_pairs END,
                    checkpoint_blob=CASE WHEN status='READY' THEN NULL ELSE checkpoint_blob END,
                    cancel_requested=0, started_at=NULL,
                    completed_at=NULL, updated_at=?
                WHERE id=? AND session_id=?
                  AND status IN ('READY', 'FAILED_RETRYABLE')
                """,
                (now, experimentId, sessionId),
            )
            return cursor.rowcount == 1

    def countExperiments(self, sessionId: str | None = None) -> int:
        with self.connection() as connection:
            if sessionId is None:
                row = connection.execute("SELECT COUNT(*) FROM experiments").fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) FROM experiments WHERE session_id=?", (sessionId,)
                ).fetchone()
        return int(row[0])

    def enforceRetention(
        self,
        retentionDays: int = 7,
        readyRetentionHours: int = 24,
        maxStoredExperiments: int = 500,
    ) -> None:
        cutoff = (datetime.now(UTC) - timedelta(days=retentionDays)).isoformat()
        auditCutoff = (datetime.now(UTC) - timedelta(days=max(30, retentionDays))).isoformat()
        readyCutoff = (datetime.now(UTC) - timedelta(hours=readyRetentionHours)).isoformat()
        terminalStatuses = "'COMPLETED','FAILED_FINAL','FAILED_RETRYABLE','CANCELLED','INVALIDATED'"
        prunableStatuses = f"'READY',{terminalStatuses}"
        with self.writeLock, self.connection() as connection:
            connection.execute("DELETE FROM event_pack_drafts WHERE updated_at < ?", (cutoff,))
            connection.execute("DELETE FROM custom_event_packs WHERE updated_at < ?", (cutoff,))
            connection.execute("DELETE FROM scenarios WHERE updated_at < ?", (cutoff,))
            # 审计链只能整条删除；部分截断会让 remaining previous_hash 无法验证。
            connection.execute(
                """
                DELETE FROM audit_events
                WHERE session_id IN (
                    SELECT session_id FROM audit_events
                    GROUP BY session_id HAVING MAX(created_at) < ?
                )
                """,
                (auditCutoff,),
            )
            connection.execute(
                "DELETE FROM experiments WHERE status='READY' AND updated_at < ?",
                (readyCutoff,),
            )
            connection.execute(
                f"""
                DELETE FROM experiments
                WHERE status IN ({terminalStatuses})
                  AND COALESCE(completed_at, updated_at) < ?
                """,  # noqa: S608
                (cutoff,),
            )
            totalCount = int(connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0])
            # 始终为下一次创建保留一个槽位，达到上限时滚动淘汰最旧的非活跃实验。
            overflow = max(0, totalCount - max(0, maxStoredExperiments - 1))
            if overflow:
                connection.execute(
                    f"""
                    DELETE FROM experiments WHERE id IN (
                        SELECT id FROM experiments
                        WHERE status IN ({prunableStatuses})
                        ORDER BY updated_at ASC
                        LIMIT ?
                    )
                    """,  # noqa: S608
                    (overflow,),
                )

    def pruneSessionExperiments(self, sessionId: str, maxRetained: int) -> None:
        prunableStatuses = (
            "'READY','COMPLETED','FAILED_FINAL','FAILED_RETRYABLE','CANCELLED','INVALIDATED'"
        )
        with self.writeLock, self.connection() as connection:
            sessionCount = int(
                connection.execute(
                    "SELECT COUNT(*) FROM experiments WHERE session_id=?", (sessionId,)
                ).fetchone()[0]
            )
            overflow = max(0, sessionCount - maxRetained)
            if overflow:
                connection.execute(
                    f"""
                    DELETE FROM experiments WHERE id IN (
                        SELECT id FROM experiments
                        WHERE session_id=? AND status IN ({prunableStatuses})
                        ORDER BY updated_at ASC
                        LIMIT ?
                    )
                    """,  # noqa: S608
                    (sessionId, overflow),
                )

    def getExperiment(self, experimentId: str, sessionId: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM experiments WHERE id=? AND session_id=?",
                (experimentId, sessionId),
            ).fetchone()
        return self._experimentFromRow(row) if row is not None else None

    def listExperiments(self, sessionId: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM experiments WHERE session_id=? ORDER BY created_at DESC LIMIT 100",
                (sessionId,),
            ).fetchall()
        return [self._experimentFromRow(row, includeCheckpoint=False) for row in rows]

    def invalidateCompletedExperiment(
        self,
        experimentId: str,
        sessionId: str,
        *,
        reasonCode: str,
        reason: str,
    ) -> bool:
        """原子失效已完成实验；结果列保持原样，重复调用不会重写原因。"""

        now = utcNow()
        with self.writeLock, self.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE experiments
                SET status='INVALIDATED', invalidated_at=?,
                    invalidation_reason_code=?, invalidation_reason=?, updated_at=?
                WHERE id=? AND session_id=? AND status='COMPLETED' AND result_json IS NOT NULL
                """,
                (now, reasonCode, reason, now, experimentId, sessionId),
            )
        return cursor.rowcount == 1

    def saveStudyRun(
        self,
        *,
        runId: str,
        sessionId: str,
        eventPackId: str,
        studyId: str,
        spec: dict[str, Any],
        result: dict[str, Any],
        specHash: str,
        resultHash: str,
    ) -> dict[str, Any]:
        """只追加完整 Study；没有更新接口，预注册与结果不可原地改写。"""

        createdAt = utcNow()
        with self.writeLock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO study_runs(
                    run_id, session_id, event_pack_id, study_id, spec_json,
                    result_json, spec_hash, result_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    runId,
                    sessionId,
                    eventPackId,
                    studyId,
                    json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    specHash,
                    resultHash,
                    createdAt,
                ),
            )
            row = connection.execute(
                "SELECT * FROM study_runs WHERE run_id=? AND session_id=?",
                (runId, sessionId),
            ).fetchone()
            connection.execute(
                """
                DELETE FROM study_runs WHERE run_id IN (
                    SELECT run_id FROM study_runs WHERE session_id=?
                    ORDER BY created_at DESC LIMIT -1 OFFSET 20
                )
                """,
                (sessionId,),
            )
            connection.execute(
                """
                DELETE FROM study_runs WHERE run_id IN (
                    SELECT run_id FROM study_runs
                    ORDER BY created_at DESC LIMIT -1 OFFSET 100
                )
                """
            )
        if row is None:
            raise RuntimeError("study run could not be persisted")
        return self._studyRunFromRow(row)

    def getStudyRun(self, runId: str, sessionId: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM study_runs WHERE run_id=? AND session_id=?",
                (runId, sessionId),
            ).fetchone()
        return self._studyRunFromRow(row) if row is not None else None

    def listStudyRuns(self, sessionId: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM study_runs
                WHERE session_id=? ORDER BY created_at DESC LIMIT 20
                """,
                (sessionId,),
            ).fetchall()
        return [self._studyRunFromRow(row) for row in rows]

    def updateExperiment(self, experimentId: str, **changes: Any) -> None:
        allowedColumns = {
            "status",
            "result_json",
            "error_code",
            "progress",
            "completed_pairs",
            "cancel_requested",
            "started_at",
            "completed_at",
            "runtime_json",
            "checkpoint_blob",
        }
        invalidColumns = set(changes) - allowedColumns
        if invalidColumns:
            raise ValueError(f"invalid experiment columns: {sorted(invalidColumns)}")
        if not changes:
            return
        changes["updated_at"] = utcNow()
        assignments = ", ".join(f"{column}=?" for column in changes)
        values = [
            json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if column in {"result_json", "runtime_json"} and value is not None
            else _encodeCheckpoint(value)
            if column == "checkpoint_blob" and value is not None
            else value
            for column, value in changes.items()
        ]
        with self.writeLock, self.connection() as connection:
            connection.execute(
                f"UPDATE experiments SET {assignments} WHERE id=?",  # noqa: S608
                (*values, experimentId),
            )

    def cancelRequested(self, experimentId: str) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM experiments WHERE id=?", (experimentId,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

    @staticmethod
    def _experimentFromRow(
        row: sqlite3.Row,
        *,
        includeCheckpoint: bool = True,
    ) -> dict[str, Any]:
        checkpoint = _decodeCheckpoint(row["checkpoint_blob"]) if includeCheckpoint else None
        return {
            "id": row["id"],
            "sessionId": row["session_id"],
            "status": row["status"],
            "request": json.loads(row["request_json"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "errorCode": row["error_code"],
            "progress": row["progress"],
            "completedPairs": row["completed_pairs"],
            "totalPairs": row["total_pairs"],
            "cancelRequested": bool(row["cancel_requested"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "startedAt": row["started_at"],
            "completedAt": row["completed_at"],
            "invalidatedAt": row["invalidated_at"],
            "invalidationReasonCode": row["invalidation_reason_code"],
            "invalidationReason": row["invalidation_reason"],
            "runtime": json.loads(row["runtime_json"]) if row["runtime_json"] else None,
            "checkpoint": checkpoint,
            "checkpointCorrupted": bool(
                includeCheckpoint and row["checkpoint_blob"] and checkpoint is None
            ),
        }

    @staticmethod
    def _scenarioFromRow(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "config": json.loads(row["config_json"]),
            "frozen": bool(row["frozen"]),
            "contentHash": row["content_hash"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _studyRunFromRow(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "runId": row["run_id"],
            "sessionId": row["session_id"],
            "eventPackId": row["event_pack_id"],
            "studyId": row["study_id"],
            "status": "COMPLETED",
            "spec": json.loads(row["spec_json"]),
            "result": json.loads(row["result_json"]),
            "specHash": row["spec_hash"],
            "resultHash": row["result_hash"],
            "historicalValidityEstablished": False,
            "createdAt": row["created_at"],
        }


def _encodeCheckpoint(value: Any) -> bytes:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(serialized) > MAX_CHECKPOINT_UNCOMPRESSED_BYTES:
        raise ValueError("experiment checkpoint exceeds the 32 MiB safety limit")
    return zlib.compress(serialized, level=6)


def _decodeCheckpoint(value: bytes | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(value, MAX_CHECKPOINT_UNCOMPRESSED_BYTES + 1)
        if len(decoded) > MAX_CHECKPOINT_UNCOMPRESSED_BYTES or not decompressor.eof:
            return None
        payload = json.loads(decoded)
        return payload if isinstance(payload, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, zlib.error):
        return None
