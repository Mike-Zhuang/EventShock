"""SQLite 控制面持久化；每个调用使用独立连接以兼容后台线程。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.app.security import scanTextContent

MAX_CHECKPOINT_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
DEFAULT_EXPERIMENT_RETENTION_DAYS = 90
DEFAULT_INTERPRETATION_RETENTION_DAYS = 90
MAX_INTERPRETATION_EXCHANGES_PER_OWNER = 300
MAX_STORED_INTERPRETATION_EXCHANGES = 5_000
MAX_INTERPRETATION_ASSISTANT_JSON_BYTES = 128 * 1024

_INTERPRETATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,79}$")
_REQUEST_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ASSISTANT_MESSAGE_FIELDS = frozenset(
    {
        "id",
        "role",
        "language",
        "answer",
        "analysisSummary",
        "groundingReferences",
        "followUpSuggestions",
        "toolActivity",
        "provider",
        "model",
        "thinkingEnabled",
        "streamed",
        "promptTokens",
        "completionTokens",
        "cachedTokens",
        "totalTokens",
        "modelCalls",
        "transportAttempts",
        "uncertainBillableAttempts",
        "cacheHit",
        "repairUsed",
        "plannerUsed",
        "plannerFallbackUsed",
        "failureCodes",
        "promptVersion",
        "latencyMs",
        "createdAt",
    }
)
_FORBIDDEN_INTERPRETATION_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "secret",
        "rawreasoning",
        "reasoning",
        "reasoningcontent",
        "thought",
        "thoughts",
        "chainofthought",
        "rawresponse",
        "providerresponse",
        "streamchunk",
        "chunk",
        "delta",
        "partial",
    }
)
_SECRET_FINDING_CODES = frozenset(
    {
        "PRIVATE_KEY_MATERIAL",
        "API_KEY_OR_TOKEN",
        "PASSWORD_VALUE",
        "URL_EMBEDDED_CREDENTIAL",
    }
)


class ResultInterpretationRequestConflictError(ValueError):
    """相同 clientRequestId 被绑定到不同请求时拒绝覆盖持久化结果。"""


class ResultInterpretationConversationDeletedError(ValueError):
    """已删除会话的旧请求不得通过缓存或重放重新写回。"""


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
                    owner_user_id TEXT NOT NULL,
                    event_pack_id TEXT NOT NULL,
                    claims_json TEXT NOT NULL,
                    frozen INTEGER NOT NULL DEFAULT 0,
                    frozen_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, event_pack_id)
                );
                CREATE TABLE IF NOT EXISTS custom_event_packs (
                    session_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
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
                    owner_user_id TEXT NOT NULL,
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
                    owner_user_id TEXT NOT NULL,
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
                    owner_user_id TEXT NOT NULL,
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
                CREATE TABLE IF NOT EXISTS result_interpretation_exchanges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_user_id TEXT NOT NULL CHECK(
                        length(owner_user_id) BETWEEN 1 AND 128
                    ),
                    experiment_id TEXT NOT NULL CHECK(
                        length(experiment_id) BETWEEN 1 AND 128
                    ),
                    conversation_id TEXT NOT NULL CHECK(
                        length(conversation_id) BETWEEN 8 AND 80
                    ),
                    client_request_id TEXT NOT NULL CHECK(
                        length(client_request_id) BETWEEN 8 AND 80
                    ),
                    request_hash TEXT NOT NULL CHECK(length(request_hash)=64),
                    language TEXT NOT NULL CHECK(language IN ('en', 'zh-CN')),
                    user_message TEXT NOT NULL CHECK(length(user_message) BETWEEN 1 AND 4000),
                    assistant_message_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
                    UNIQUE (owner_user_id, experiment_id, client_request_id)
                );
                CREATE INDEX IF NOT EXISTS idx_interpretation_owner_experiment_conversation
                ON result_interpretation_exchanges(
                    owner_user_id, experiment_id, conversation_id, id
                );
                CREATE INDEX IF NOT EXISTS idx_interpretation_owner_updated
                ON result_interpretation_exchanges(owner_user_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS result_interpretation_tombstones (
                    owner_user_id TEXT NOT NULL CHECK(
                        length(owner_user_id) BETWEEN 1 AND 128
                    ),
                    experiment_id TEXT NOT NULL CHECK(
                        length(experiment_id) BETWEEN 1 AND 128
                    ),
                    conversation_hash TEXT NOT NULL CHECK(length(conversation_hash)=64),
                    deleted_at TEXT NOT NULL,
                    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
                    PRIMARY KEY (owner_user_id, experiment_id, conversation_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_interpretation_tombstones_owner
                ON result_interpretation_tombstones(owner_user_id, deleted_at DESC);
                CREATE TABLE IF NOT EXISTS study_runs (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
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
            # 旧版以匿名浏览器 session_id 作为所有权。新增 owner_user_id 后保留
            # 原 session_id，避免复合主键碰撞，并保证历史审计哈希仍可重算。
            for tableName in (
                "event_pack_drafts",
                "custom_event_packs",
                "scenarios",
                "audit_events",
                "experiments",
                "study_runs",
            ):
                columns = {
                    row["name"] for row in connection.execute(f"PRAGMA table_info({tableName})")
                }
                if "owner_user_id" not in columns:
                    connection.execute(
                        f"ALTER TABLE {tableName} ADD COLUMN owner_user_id TEXT"  # noqa: S608
                    )
                connection.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{tableName}_owner "  # noqa: S608
                    f"ON {tableName}(owner_user_id)"
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

    def claimLegacyRecords(self, ownerUserId: str) -> dict[str, int]:
        """把尚未归属账号的历史匿名数据声明给管理员，同时保留原审计链。"""

        if not ownerUserId.strip():
            raise ValueError("ownerUserId must not be empty")
        claimed: dict[str, int] = {}
        with self.writeLock, self.connection() as connection:
            for tableName in (
                "event_pack_drafts",
                "custom_event_packs",
                "scenarios",
                "audit_events",
                "experiments",
                "study_runs",
            ):
                cursor = connection.execute(
                    f"UPDATE {tableName} SET owner_user_id=? "  # noqa: S608
                    "WHERE owner_user_id IS NULL OR owner_user_id=''",
                    (ownerUserId,),
                )
                claimed[tableName] = cursor.rowcount
        return claimed

    def countUnownedRecords(self) -> dict[str, int]:
        """返回尚未完成账号归属的数据量，供启动检查和部署验证使用。"""

        counts: dict[str, int] = {}
        with self.connection() as connection:
            for tableName in (
                "event_pack_drafts",
                "custom_event_packs",
                "scenarios",
                "audit_events",
                "experiments",
                "study_runs",
            ):
                row = connection.execute(
                    f"SELECT COUNT(*) FROM {tableName} "  # noqa: S608
                    "WHERE owner_user_id IS NULL OR owner_user_id=''"
                ).fetchone()
                counts[tableName] = int(row[0])
        return counts

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
                """
                SELECT * FROM event_pack_drafts
                WHERE COALESCE(owner_user_id, session_id)=? AND event_pack_id=?
                ORDER BY updated_at DESC LIMIT 1
                """,
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
            self._saveEventPackDraftInConnection(
                connection,
                sessionId,
                eventPackId,
                claims,
                frozen,
                frozenAt,
                now,
            )

    def saveEventPackDraftWithAudit(
        self,
        sessionId: str,
        eventPackId: str,
        claims: list[dict[str, Any]],
        *,
        frozen: bool = False,
        frozenAt: str | None = None,
        auditEntityType: str = "EVENT_PACK",
        auditEntityId: str | None = None,
        auditAction: str,
        auditPayload: dict[str, Any],
    ) -> dict[str, Any]:
        """在同一事务中保存整包审核结果并追加不可变审计事件。"""

        now = utcNow()
        with self.writeLock, self.connection() as connection:
            self._saveEventPackDraftInConnection(
                connection,
                sessionId,
                eventPackId,
                claims,
                frozen,
                frozenAt,
                now,
            )
            return self._appendAuditEventInConnection(
                connection,
                sessionId,
                auditEntityType,
                auditEntityId or eventPackId,
                auditAction,
                auditPayload,
                now,
            )

    @staticmethod
    def _saveEventPackDraftInConnection(
        connection: sqlite3.Connection,
        sessionId: str,
        eventPackId: str,
        claims: list[dict[str, Any]],
        frozen: bool,
        frozenAt: str | None,
        updatedAt: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO event_pack_drafts(
                session_id, owner_user_id, event_pack_id, claims_json,
                frozen, frozen_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, event_pack_id) DO UPDATE SET
                owner_user_id=excluded.owner_user_id,
                claims_json=excluded.claims_json,
                frozen=excluded.frozen,
                frozen_at=excluded.frozen_at,
                updated_at=excluded.updated_at
            """,
            (
                sessionId,
                sessionId,
                eventPackId,
                json.dumps(claims, ensure_ascii=False, separators=(",", ":")),
                int(frozen),
                frozenAt,
                updatedAt,
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
        with self.writeLock, self.connection() as connection:
            manifestJson = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
            claimsJson = json.dumps(claims, ensure_ascii=False, separators=(",", ":"))
            try:
                connection.execute(
                    """
                    INSERT INTO custom_event_packs(
                        session_id, owner_user_id, event_pack_id, manifest_json,
                        claims_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sessionId,
                        sessionId,
                        eventPackId,
                        manifestJson,
                        claimsJson,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "an Event Pack with this immutable version ID already exists"
                ) from error

    def saveCustomEventPackWithAudit(
        self,
        sessionId: str,
        eventPackId: str,
        manifest: dict[str, Any],
        claims: list[dict[str, Any]],
        *,
        auditAction: str,
        auditPayload: dict[str, Any],
    ) -> dict[str, Any]:
        """原子创建不可变 Event Pack 并追加审计，消除对象与审计之间的崩溃窗口。"""

        now = utcNow()
        manifestJson = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
        claimsJson = json.dumps(claims, ensure_ascii=False, separators=(",", ":"))
        with self.writeLock, self.connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO custom_event_packs(
                        session_id, owner_user_id, event_pack_id, manifest_json,
                        claims_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sessionId,
                        sessionId,
                        eventPackId,
                        manifestJson,
                        claimsJson,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "an Event Pack with this immutable version ID already exists"
                ) from error
            return self._appendAuditEventInConnection(
                connection,
                sessionId,
                "EVENT_PACK",
                eventPackId,
                auditAction,
                auditPayload,
                now,
            )

    def saveExtractedEventPackWithAudit(
        self,
        sessionId: str,
        eventPackId: str,
        manifest: dict[str, Any],
        claims: list[dict[str, Any]],
        *,
        auditAction: str,
        auditPayload: dict[str, Any],
    ) -> dict[str, Any]:
        """在同一事务中替换重抽取结果、重置草稿并追加审计事件。"""

        now = utcNow()
        with self.writeLock, self.connection() as connection:
            self._saveCustomEventPackInConnection(
                connection,
                sessionId,
                eventPackId,
                manifest,
                claims,
                now,
            )
            self._saveEventPackDraftInConnection(
                connection,
                sessionId,
                eventPackId,
                claims,
                False,
                None,
                now,
            )
            return self._appendAuditEventInConnection(
                connection,
                sessionId,
                "EVENT_PACK",
                eventPackId,
                auditAction,
                auditPayload,
                now,
            )

    @staticmethod
    def _saveCustomEventPackInConnection(
        connection: sqlite3.Connection,
        sessionId: str,
        eventPackId: str,
        manifest: dict[str, Any],
        claims: list[dict[str, Any]],
        updatedAt: str,
    ) -> None:
        manifestJson = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
        claimsJson = json.dumps(claims, ensure_ascii=False, separators=(",", ":"))
        connection.execute(
            """
            INSERT INTO custom_event_packs(
                session_id, owner_user_id, event_pack_id, manifest_json,
                claims_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, event_pack_id) DO UPDATE SET
                owner_user_id=excluded.owner_user_id,
                manifest_json=excluded.manifest_json,
                claims_json=excluded.claims_json,
                updated_at=excluded.updated_at
            """,
            (sessionId, sessionId, eventPackId, manifestJson, claimsJson, updatedAt, updatedAt),
        )

    def getCustomEventPack(self, sessionId: str, eventPackId: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT manifest_json, claims_json, created_at, updated_at
                FROM custom_event_packs
                WHERE COALESCE(owner_user_id, session_id)=? AND event_pack_id=?
                ORDER BY updated_at DESC LIMIT 1
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
                FROM custom_event_packs
                WHERE COALESCE(owner_user_id, session_id)=? ORDER BY updated_at DESC
                """,
                (sessionId,),
            ).fetchall()
        # 多个旧匿名会话可能创建过同名包；管理员视图保留最新版本，旧审计
        # 与数据库行仍完整保留，不会因迁移而发生覆盖。
        uniqueRows: dict[str, sqlite3.Row] = {}
        for row in rows:
            uniqueRows.setdefault(row["event_pack_id"], row)
        return [
            {
                **json.loads(row["manifest_json"]),
                "id": row["event_pack_id"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
            for row in uniqueRows.values()
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
                    id, session_id, owner_user_id, name, config_json,
                    frozen, content_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    owner_user_id=excluded.owner_user_id,
                    name=excluded.name,
                    config_json=excluded.config_json,
                    frozen=excluded.frozen,
                    content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at
                WHERE COALESCE(scenarios.owner_user_id, scenarios.session_id)=excluded.owner_user_id
                """,
                (
                    scenarioId,
                    sessionId,
                    sessionId,
                    name,
                    configJson,
                    int(frozen),
                    contentHash,
                    now,
                    now,
                ),
            )
        scenario = self.getScenario(scenarioId, sessionId)
        if scenario is None:
            raise RuntimeError("scenario could not be persisted")
        return scenario

    def getScenario(self, scenarioId: str, sessionId: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM scenarios WHERE id=? AND COALESCE(owner_user_id, session_id)=?",
                (scenarioId, sessionId),
            ).fetchone()
        return self._scenarioFromRow(row) if row is not None else None

    def listScenarios(self, sessionId: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM scenarios
                WHERE COALESCE(owner_user_id, session_id)=?
                ORDER BY updated_at DESC LIMIT 100
                """,
                (sessionId,),
            ).fetchall()
        return [self._scenarioFromRow(row) for row in rows]

    def deleteScenario(self, scenarioId: str, sessionId: str) -> bool:
        with self.writeLock, self.connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM scenarios
                WHERE id=? AND COALESCE(owner_user_id, session_id)=? AND frozen=0
                """,
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
        with self.writeLock, self.connection() as connection:
            return self._appendAuditEventInConnection(
                connection,
                sessionId,
                entityType,
                entityId,
                action,
                payload,
                createdAt,
            )

    @staticmethod
    def _appendAuditEventInConnection(
        connection: sqlite3.Connection,
        sessionId: str,
        entityType: str,
        entityId: str,
        action: str,
        payload: dict[str, Any],
        createdAt: str,
    ) -> dict[str, Any]:
        payloadJson = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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
                session_id, owner_user_id, entity_type, entity_id, action,
                payload_json, previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sessionId,
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
                SELECT * FROM audit_events
                WHERE COALESCE(owner_user_id, session_id)=?
                ORDER BY id DESC LIMIT ?
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

    def eventPackWasMaterializedFromFactoryBuild(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        eventPackId: str,
    ) -> bool:
        """验证 Factory build 与 Event Pack 的不可伪造审计关联。"""

        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM audit_events
                WHERE COALESCE(owner_user_id, session_id)=?
                  AND entity_type='EVENT_PACK_FACTORY'
                  AND entity_id=?
                  AND action='EVENT_PACK_MATERIALIZED'
                ORDER BY id DESC
                """,
                (ownerUserId, buildId),
            ).fetchall()
        return any(
            json.loads(row["payload_json"]).get("eventPackId") == eventPackId for row in rows
        )

    def verifyAuditChain(self, sessionId: str) -> dict[str, Any]:
        """重算账号名下全部原始审计链；迁移不会重写历史哈希。"""
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM audit_events
                WHERE COALESCE(owner_user_id, session_id)=?
                ORDER BY session_id ASC, id ASC
                """,
                (sessionId,),
            ).fetchall()
        previousByChain: dict[str, str | None] = {}
        for row in rows:
            chainId = row["session_id"]
            previousHash = previousByChain.get(chainId)
            material = "|".join(
                (
                    chainId,
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
                    "chainCount": len({item["session_id"] for item in rows}),
                }
            previousByChain[chainId] = row["event_hash"]
        chainHeads = [
            f"{chainId}:{headHash or ''}" for chainId, headHash in sorted(previousByChain.items())
        ]
        aggregateHead = (
            next(iter(previousByChain.values()))
            if len(previousByChain) == 1
            else hashlib.sha256("|".join(chainHeads).encode()).hexdigest()
            if chainHeads
            else None
        )
        return {
            "valid": True,
            "eventCount": len(rows),
            "firstInvalidEventId": None,
            "headHash": aggregateHead,
            **({"chainCount": len(previousByChain)} if len(previousByChain) > 1 else {}),
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
                    """
                    SELECT * FROM experiments
                    WHERE COALESCE(owner_user_id, session_id)=? AND idempotency_key=?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (sessionId, idempotencyKey),
                ).fetchone()
                if existingRow is not None:
                    return self._experimentFromRow(existingRow), False
            connection.execute(
                """
                INSERT INTO experiments(
                    id, session_id, owner_user_id, idempotency_key, status,
                    request_json, total_pairs, created_at, updated_at, runtime_json
                ) VALUES (?, ?, ?, ?, 'READY', ?, ?, ?, ?, ?)
                """,
                (
                    experimentId,
                    sessionId,
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
                """
                SELECT * FROM experiments
                WHERE COALESCE(owner_user_id, session_id)=? AND idempotency_key=?
                ORDER BY created_at DESC LIMIT 1
                """,
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
                WHERE id=? AND COALESCE(owner_user_id, session_id)=?
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
                    """
                    SELECT COUNT(*) FROM experiments
                    WHERE COALESCE(owner_user_id, session_id)=?
                    """,
                    (sessionId,),
                ).fetchone()
        return int(row[0])

    def enforceRetention(
        self,
        retentionDays: int = DEFAULT_EXPERIMENT_RETENTION_DAYS,
        readyRetentionHours: int = 24,
        maxStoredExperiments: int = 500,
    ) -> None:
        cutoff = (datetime.now(UTC) - timedelta(days=retentionDays)).isoformat()
        auditCutoff = (datetime.now(UTC) - timedelta(days=max(30, retentionDays))).isoformat()
        readyCutoff = (datetime.now(UTC) - timedelta(hours=readyRetentionHours)).isoformat()
        terminalStatuses = "'COMPLETED','FAILED_FINAL','FAILED_RETRYABLE','CANCELLED','INVALIDATED'"
        prunableStatuses = f"'READY',{terminalStatuses}"
        with self.writeLock, self.connection() as connection:
            # 所有权迁移是保留期清理的硬前置条件。守卫放在数据库层，确保
            # 启动路径和实验创建路径都不能误删尚未认领的匿名历史记录。
            for tableName in (
                "event_pack_drafts",
                "custom_event_packs",
                "scenarios",
                "audit_events",
                "experiments",
                "study_runs",
            ):
                unowned = connection.execute(
                    f"SELECT 1 FROM {tableName} "  # noqa: S608
                    "WHERE owner_user_id IS NULL OR owner_user_id='' LIMIT 1"
                ).fetchone()
                if unowned is not None:
                    return
            connection.execute("DELETE FROM event_pack_drafts WHERE updated_at < ?", (cutoff,))
            connection.execute("DELETE FROM custom_event_packs WHERE updated_at < ?", (cutoff,))
            connection.execute("DELETE FROM scenarios WHERE updated_at < ?", (cutoff,))
            self._pruneResultInterpretationExchangesInConnection(connection)
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
                    """
                    SELECT COUNT(*) FROM experiments
                    WHERE COALESCE(owner_user_id, session_id)=?
                    """,
                    (sessionId,),
                ).fetchone()[0]
            )
            overflow = max(0, sessionCount - maxRetained)
            if overflow:
                connection.execute(
                    f"""
                    DELETE FROM experiments WHERE id IN (
                        SELECT id FROM experiments
                        WHERE COALESCE(owner_user_id, session_id)=?
                          AND status IN ({prunableStatuses})
                        ORDER BY updated_at ASC
                        LIMIT ?
                    )
                    """,  # noqa: S608
                    (sessionId, overflow),
                )

    def getExperiment(self, experimentId: str, sessionId: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM experiments
                WHERE id=? AND COALESCE(owner_user_id, session_id)=?
                """,
                (experimentId, sessionId),
            ).fetchone()
        return self._experimentFromRow(row) if row is not None else None

    def listExperiments(self, sessionId: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM experiments
                WHERE COALESCE(owner_user_id, session_id)=?
                ORDER BY created_at DESC LIMIT 100
                """,
                (sessionId,),
            ).fetchall()
        return [self._experimentFromRow(row, includeCheckpoint=False) for row in rows]

    def saveResultInterpretationExchange(
        self,
        *,
        ownerUserId: str,
        experimentId: str,
        conversationId: str,
        clientRequestId: str,
        requestHash: str,
        language: str,
        userMessage: str,
        assistantMessage: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """原子保存一次完整问答；相同请求返回原结果，不覆盖既有正文。

        调用方只能传入已经通过结果解释 Schema、证据边界与语言检查的最终
        assistant message。这里再用字段白名单阻止密钥、私有推理和流片段进入
        SQLite，形成独立于接口层的纵深防护。
        """

        normalizedOwner = ownerUserId.strip()
        normalizedExperiment = experimentId.strip()
        normalizedUserMessage = userMessage.strip()
        self._validateInterpretationIdentifier("conversationId", conversationId)
        self._validateInterpretationIdentifier("clientRequestId", clientRequestId)
        if not normalizedOwner or len(normalizedOwner) > 128:
            raise ValueError("ownerUserId must contain between 1 and 128 characters")
        if not normalizedExperiment or len(normalizedExperiment) > 128:
            raise ValueError("experimentId must contain between 1 and 128 characters")
        if _REQUEST_HASH_PATTERN.fullmatch(requestHash) is None:
            raise ValueError("requestHash must be a lowercase SHA-256 digest")
        if language not in {"en", "zh-CN"}:
            raise ValueError("language must be en or zh-CN")
        if not normalizedUserMessage or len(normalizedUserMessage) > 4_000:
            raise ValueError("userMessage must contain between 1 and 4000 characters")
        self._rejectInterpretationSecretsInText(normalizedUserMessage)
        assistantMessageJson = self._serializeSafeAssistantMessage(assistantMessage, language)
        now = utcNow()

        with self.writeLock, self.connection() as connection:
            # 先清除已经到期的幂等键；否则同一 clientRequestId 在保留期结束后
            # 仍会被唯一约束绑定到一条用户已经无法读取的旧回答。
            self._pruneResultInterpretationExchangesInConnection(
                connection,
                ownerUserId=normalizedOwner,
            )
            experiment = connection.execute(
                """
                SELECT 1 FROM experiments
                WHERE id=? AND COALESCE(owner_user_id, session_id)=?
                  AND status='COMPLETED' AND result_json IS NOT NULL
                """,
                (normalizedExperiment, normalizedOwner),
            ).fetchone()
            if experiment is None:
                raise ValueError("completed experiment does not exist for this owner")

            if self._isResultInterpretationConversationDeletedInConnection(
                connection,
                ownerUserId=normalizedOwner,
                experimentId=normalizedExperiment,
                conversationId=conversationId,
            ):
                raise ResultInterpretationConversationDeletedError(
                    "deleted result interpretation conversation cannot be recreated"
                )

            existingRow = connection.execute(
                """
                SELECT * FROM result_interpretation_exchanges
                WHERE owner_user_id=? AND experiment_id=? AND client_request_id=?
                """,
                (normalizedOwner, normalizedExperiment, clientRequestId),
            ).fetchone()
            if existingRow is not None:
                self._ensureMatchingInterpretationRequest(existingRow, requestHash)
                return self._resultInterpretationExchangeFromRow(existingRow), False

            insertCursor = connection.execute(
                """
                INSERT INTO result_interpretation_exchanges(
                    owner_user_id, experiment_id, conversation_id,
                    client_request_id, request_hash, language, user_message,
                    assistant_message_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_user_id, experiment_id, client_request_id) DO NOTHING
                """,
                (
                    normalizedOwner,
                    normalizedExperiment,
                    conversationId,
                    clientRequestId,
                    requestHash,
                    language,
                    normalizedUserMessage,
                    assistantMessageJson,
                    now,
                    now,
                ),
            )
            storedRow = connection.execute(
                """
                SELECT * FROM result_interpretation_exchanges
                WHERE owner_user_id=? AND experiment_id=? AND client_request_id=?
                """,
                (normalizedOwner, normalizedExperiment, clientRequestId),
            ).fetchone()
            if storedRow is None:
                raise RuntimeError("result interpretation exchange could not be persisted")
            self._ensureMatchingInterpretationRequest(storedRow, requestHash)
            created = insertCursor.rowcount == 1
            self._pruneResultInterpretationExchangesInConnection(
                connection,
                ownerUserId=normalizedOwner,
            )
        return self._resultInterpretationExchangeFromRow(storedRow), created

    def getResultInterpretationExchangeByRequest(
        self,
        *,
        ownerUserId: str,
        experimentId: str,
        clientRequestId: str,
        requestHash: str,
    ) -> dict[str, Any] | None:
        """按账号和实验恢复已完成响应；请求哈希不同视为幂等键冲突。"""

        cutoff = (
            datetime.now(UTC) - timedelta(days=DEFAULT_INTERPRETATION_RETENTION_DAYS)
        ).isoformat()
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM result_interpretation_exchanges
                WHERE owner_user_id=? AND experiment_id=? AND client_request_id=?
                  AND updated_at>=?
                """,
                (ownerUserId, experimentId, clientRequestId, cutoff),
            ).fetchone()
        if row is None:
            return None
        self._ensureMatchingInterpretationRequest(row, requestHash)
        return self._resultInterpretationExchangeFromRow(row)

    def listResultInterpretationConversations(
        self,
        ownerUserId: str,
        *,
        experimentId: str | None = None,
        limit: int = MAX_INTERPRETATION_EXCHANGES_PER_OWNER,
    ) -> list[dict[str, Any]]:
        """列出当前账号的会话摘要，可进一步限定到单个实验。"""

        # 每个账号最多只保留 300 轮；即使每轮各自属于一个会话，也必须让用户
        # 能从列表枚举并删除全部已存内容，不能产生“库里存在、界面不可发现”的记录。
        safeLimit = max(1, min(limit, MAX_INTERPRETATION_EXCHANGES_PER_OWNER))
        cutoff = (
            datetime.now(UTC) - timedelta(days=DEFAULT_INTERPRETATION_RETENTION_DAYS)
        ).isoformat()
        parameters: list[Any] = [ownerUserId, cutoff]
        experimentFilter = ""
        if experimentId is not None:
            experimentFilter = "AND experiment_id=?"
            parameters.append(experimentId)
        parameters.append(safeLimit)
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    owner_user_id, experiment_id, conversation_id,
                    COUNT(*) AS exchange_count,
                    MIN(created_at) AS created_at,
                    MAX(updated_at) AS updated_at,
                    (
                        SELECT latest.language
                        FROM result_interpretation_exchanges AS latest
                        WHERE latest.owner_user_id=exchanges.owner_user_id
                          AND latest.experiment_id=exchanges.experiment_id
                          AND latest.conversation_id=exchanges.conversation_id
                        ORDER BY latest.id DESC LIMIT 1
                    ) AS language,
                    (
                        SELECT latest.user_message
                        FROM result_interpretation_exchanges AS latest
                        WHERE latest.owner_user_id=exchanges.owner_user_id
                          AND latest.experiment_id=exchanges.experiment_id
                          AND latest.conversation_id=exchanges.conversation_id
                        ORDER BY latest.id DESC LIMIT 1
                    ) AS last_user_message
                FROM result_interpretation_exchanges AS exchanges
                WHERE owner_user_id=? AND updated_at>=? {experimentFilter}
                GROUP BY owner_user_id, experiment_id, conversation_id
                ORDER BY updated_at DESC
                LIMIT ?
                """,  # noqa: S608 -- experimentFilter 只可能是固定 SQL 片段。
                tuple(parameters),
            ).fetchall()
        return [
            {
                "conversationId": row["conversation_id"],
                "experimentId": row["experiment_id"],
                "language": row["language"],
                "exchangeCount": int(row["exchange_count"]),
                "lastUserMessage": row["last_user_message"][:240],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
            for row in rows
        ]

    def getResultInterpretationConversation(
        self,
        *,
        ownerUserId: str,
        experimentId: str,
        conversationId: str,
    ) -> dict[str, Any] | None:
        """读取一个账号、实验和会话三重作用域内的全部已完成问答。"""

        cutoff = (
            datetime.now(UTC) - timedelta(days=DEFAULT_INTERPRETATION_RETENTION_DAYS)
        ).isoformat()
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM result_interpretation_exchanges
                WHERE owner_user_id=? AND experiment_id=? AND conversation_id=?
                  AND updated_at>=?
                ORDER BY id ASC
                """,
                (ownerUserId, experimentId, conversationId, cutoff),
            ).fetchall()
        if not rows:
            return None
        exchanges = [self._resultInterpretationExchangeFromRow(row) for row in rows]
        return {
            "conversationId": conversationId,
            "experimentId": experimentId,
            "language": exchanges[-1]["language"],
            "createdAt": exchanges[0]["createdAt"],
            "updatedAt": exchanges[-1]["updatedAt"],
            "exchanges": exchanges,
        }

    def deleteResultInterpretationConversation(
        self,
        *,
        ownerUserId: str,
        experimentId: str,
        conversationId: str,
        auditPayload: dict[str, Any] | None = None,
    ) -> bool:
        """删除会话并写最小墓碑，阻止旧请求或短期缓存把正文复活。"""

        self._validateInterpretationIdentifier("conversationId", conversationId)
        conversationHash = hashlib.sha256(conversationId.encode("utf-8")).hexdigest()
        deletedAt = utcNow()
        with self.writeLock, self.connection() as connection:
            existingTombstone = self._isResultInterpretationConversationDeletedInConnection(
                connection,
                ownerUserId=ownerUserId,
                experimentId=experimentId,
                conversationId=conversationId,
            )
            cursor = connection.execute(
                """
                DELETE FROM result_interpretation_exchanges
                WHERE owner_user_id=? AND experiment_id=? AND conversation_id=?
                """,
                (ownerUserId, experimentId, conversationId),
            )
            # 只有确实存在过的会话才创建墓碑。随机 DELETE 不得无限制造
            # 墓碑与审计记录；同进程生成和删除由账号级单飞锁串行化。
            if cursor.rowcount > 0 and not existingTombstone:
                connection.execute(
                    """
                    INSERT INTO result_interpretation_tombstones(
                        owner_user_id, experiment_id, conversation_hash, deleted_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (ownerUserId, experimentId, conversationHash, deletedAt),
                )
            if cursor.rowcount > 0 and auditPayload is not None:
                self._appendAuditEventInConnection(
                    connection,
                    ownerUserId,
                    "RESULT_INTERPRETATION",
                    experimentId,
                    "INTERPRETATION_CONVERSATION_DELETED",
                    auditPayload,
                    deletedAt,
                )
        return cursor.rowcount > 0

    def isResultInterpretationConversationDeleted(
        self,
        *,
        ownerUserId: str,
        experimentId: str,
        conversationId: str,
    ) -> bool:
        """只查询不可逆删除标记；墓碑不含用户问题、回答或供应商数据。"""

        self._validateInterpretationIdentifier("conversationId", conversationId)
        with self.connection() as connection:
            return self._isResultInterpretationConversationDeletedInConnection(
                connection,
                ownerUserId=ownerUserId,
                experimentId=experimentId,
                conversationId=conversationId,
            )

    def countResultInterpretationExchanges(self, ownerUserId: str | None = None) -> int:
        with self.connection() as connection:
            if ownerUserId is None:
                row = connection.execute(
                    "SELECT COUNT(*) FROM result_interpretation_exchanges"
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT COUNT(*) FROM result_interpretation_exchanges
                    WHERE owner_user_id=?
                    """,
                    (ownerUserId,),
                ).fetchone()
        return int(row[0])

    def enforceResultInterpretationRetention(
        self,
        *,
        retentionDays: int = DEFAULT_INTERPRETATION_RETENTION_DAYS,
        maxPerOwner: int = MAX_INTERPRETATION_EXCHANGES_PER_OWNER,
        maxStored: int = MAX_STORED_INTERPRETATION_EXCHANGES,
    ) -> None:
        with self.writeLock, self.connection() as connection:
            self._pruneResultInterpretationExchangesInConnection(
                connection,
                retentionDays=retentionDays,
                maxPerOwner=maxPerOwner,
                maxStored=maxStored,
            )

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
                WHERE id=? AND COALESCE(owner_user_id, session_id)=?
                  AND status='COMPLETED' AND result_json IS NOT NULL
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
                    run_id, session_id, owner_user_id, event_pack_id, study_id,
                    spec_json, result_json, spec_hash, result_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    runId,
                    sessionId,
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
                """
                SELECT * FROM study_runs
                WHERE run_id=? AND COALESCE(owner_user_id, session_id)=?
                """,
                (runId, sessionId),
            ).fetchone()
            connection.execute(
                """
                DELETE FROM study_runs WHERE run_id IN (
                    SELECT run_id FROM study_runs
                    WHERE COALESCE(owner_user_id, session_id)=?
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
                """
                SELECT * FROM study_runs
                WHERE run_id=? AND COALESCE(owner_user_id, session_id)=?
                """,
                (runId, sessionId),
            ).fetchone()
        return self._studyRunFromRow(row) if row is not None else None

    def listStudyRuns(self, sessionId: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM study_runs
                WHERE COALESCE(owner_user_id, session_id)=?
                ORDER BY created_at DESC LIMIT 20
                """,
                (sessionId,),
            ).fetchall()
        return [self._studyRunFromRow(row) for row in rows]

    def updateExperiment(self, experimentId: str, ownerUserId: str, **changes: Any) -> None:
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
                f"UPDATE experiments SET {assignments} "  # noqa: S608
                "WHERE id=? AND COALESCE(owner_user_id, session_id)=?",
                (*values, experimentId, ownerUserId),
            )

    def cancelRequested(self, experimentId: str, ownerUserId: str) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT cancel_requested FROM experiments
                WHERE id=? AND COALESCE(owner_user_id, session_id)=?
                """,
                (experimentId, ownerUserId),
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

    @staticmethod
    def _validateInterpretationIdentifier(fieldName: str, value: str) -> None:
        if _INTERPRETATION_ID_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{fieldName} has an invalid format")

    @staticmethod
    def _serializeSafeAssistantMessage(
        assistantMessage: dict[str, Any],
        language: str,
    ) -> str:
        if not isinstance(assistantMessage, dict):
            raise ValueError("assistantMessage must be an object")
        unknownFields = set(assistantMessage) - _SAFE_ASSISTANT_MESSAGE_FIELDS
        if unknownFields:
            raise ValueError(
                f"assistantMessage contains unsupported fields: {sorted(unknownFields)}"
            )
        requiredFields = {
            "id",
            "role",
            "language",
            "answer",
            "groundingReferences",
            "createdAt",
        }
        missingFields = requiredFields - set(assistantMessage)
        if missingFields:
            raise ValueError(
                f"assistantMessage is missing required fields: {sorted(missingFields)}"
            )
        if assistantMessage["role"] != "assistant":
            raise ValueError("assistantMessage.role must be assistant")
        if assistantMessage["language"] != language:
            raise ValueError("assistantMessage.language must match the exchange language")
        answer = assistantMessage["answer"]
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 12_000:
            raise ValueError("assistantMessage.answer must contain between 1 and 12000 characters")
        references = assistantMessage["groundingReferences"]
        if not isinstance(references, list) or not references or len(references) > 20:
            raise ValueError("assistantMessage.groundingReferences must contain 1 to 20 items")
        Database._rejectSensitiveInterpretationKeys(assistantMessage)
        try:
            serialized = json.dumps(
                assistantMessage,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as error:
            raise ValueError("assistantMessage must be JSON serializable") from error
        if len(serialized.encode("utf-8")) > MAX_INTERPRETATION_ASSISTANT_JSON_BYTES:
            raise ValueError("assistantMessage exceeds the 128 KiB storage limit")
        Database._rejectInterpretationSecretsInText(serialized)
        return serialized

    @staticmethod
    def _rejectInterpretationSecretsInText(value: str) -> None:
        findings = scanTextContent(value, field="resultInterpretationPersistence").findings
        findingCodes = {finding.code for finding in findings}
        if findingCodes & _SECRET_FINDING_CODES:
            raise ValueError("result interpretation exchange contains credential-like content")
        # 安全扫描器只检查前 100,000 个字符。大于该上限时必须拒绝整条记录，
        # 不能让后半段未经扫描的文本进入账号数据库。
        if "CONTENT_SIZE_LIMIT_EXCEEDED" in findingCodes:
            raise ValueError("result interpretation exchange exceeds the safe scanning limit")

    @staticmethod
    def _rejectSensitiveInterpretationKeys(value: Any) -> None:
        if isinstance(value, dict):
            for key, nestedValue in value.items():
                normalizedKey = re.sub(r"[^a-z0-9]", "", str(key).lower())
                if normalizedKey in _FORBIDDEN_INTERPRETATION_KEYS:
                    raise ValueError(
                        "assistantMessage contains a private or unverified response field"
                    )
                Database._rejectSensitiveInterpretationKeys(nestedValue)
        elif isinstance(value, list):
            for nestedValue in value:
                Database._rejectSensitiveInterpretationKeys(nestedValue)

    @staticmethod
    def _ensureMatchingInterpretationRequest(row: sqlite3.Row, requestHash: str) -> None:
        if row["request_hash"] != requestHash:
            raise ResultInterpretationRequestConflictError(
                "clientRequestId is bound to a different persisted request"
            )

    @staticmethod
    def _isResultInterpretationConversationDeletedInConnection(
        connection: sqlite3.Connection,
        *,
        ownerUserId: str,
        experimentId: str,
        conversationId: str,
    ) -> bool:
        conversationHash = hashlib.sha256(conversationId.encode("utf-8")).hexdigest()
        row = connection.execute(
            """
            SELECT 1 FROM result_interpretation_tombstones
            WHERE owner_user_id=? AND experiment_id=? AND conversation_hash=?
            """,
            (ownerUserId, experimentId, conversationHash),
        ).fetchone()
        return row is not None

    @staticmethod
    def _resultInterpretationExchangeFromRow(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "conversationId": row["conversation_id"],
            "experimentId": row["experiment_id"],
            "clientRequestId": row["client_request_id"],
            "requestHash": row["request_hash"],
            "language": row["language"],
            "userMessage": row["user_message"],
            "assistantMessage": json.loads(row["assistant_message_json"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _pruneResultInterpretationExchangesInConnection(
        connection: sqlite3.Connection,
        *,
        ownerUserId: str | None = None,
        retentionDays: int = DEFAULT_INTERPRETATION_RETENTION_DAYS,
        maxPerOwner: int = MAX_INTERPRETATION_EXCHANGES_PER_OWNER,
        maxStored: int = MAX_STORED_INTERPRETATION_EXCHANGES,
    ) -> None:
        if retentionDays < 1 or maxPerOwner < 1 or maxStored < 1:
            raise ValueError("interpretation retention limits must be positive")
        cutoff = (datetime.now(UTC) - timedelta(days=retentionDays)).isoformat()
        connection.execute(
            "DELETE FROM result_interpretation_exchanges WHERE updated_at < ?",
            (cutoff,),
        )
        if ownerUserId is None:
            owners = connection.execute(
                "SELECT DISTINCT owner_user_id FROM result_interpretation_exchanges"
            ).fetchall()
            ownerIds = [row["owner_user_id"] for row in owners]
        else:
            ownerIds = [ownerUserId]
        for ownerId in ownerIds:
            connection.execute(
                """
                DELETE FROM result_interpretation_exchanges WHERE id IN (
                    SELECT id FROM result_interpretation_exchanges
                    WHERE owner_user_id=?
                    ORDER BY updated_at DESC, id DESC LIMIT -1 OFFSET ?
                )
                """,
                (ownerId, maxPerOwner),
            )
        connection.execute(
            """
            DELETE FROM result_interpretation_exchanges WHERE id IN (
                SELECT id FROM result_interpretation_exchanges
                ORDER BY updated_at DESC, id DESC LIMIT -1 OFFSET ?
            )
            """,
            (maxStored,),
        )


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
