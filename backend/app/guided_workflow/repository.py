"""SQLite 持久化的引导工作流；只保存清理后的消息和严格草稿。"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.app.database import Database
from backend.app.guided_workflow.models import (
    GuidedArchivedProposal,
    GuidedArchivedProposalReason,
    GuidedArchivedProposalStatus,
    GuidedStage,
    GuidedTurnOperationStatus,
    GuidedTurnOperationView,
    GuidedTurnRecoveryAction,
    GuidedWorkflowDraft,
    GuidedWorkflowMessage,
    GuidedWorkflowProposal,
    GuidedWorkflowStatus,
    GuidedWorkflowView,
)
from backend.app.guided_workflow.stage_openings import (
    guidedStageOpening,
    guidedStageOpeningMessageId,
)


class GuidedWorkflowConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class GuidedTurnClaim:
    """持久化的回合执行权；只有持有 claimToken 的请求可以提交模型结果。"""

    workflow: GuidedWorkflowView
    requestHash: str
    claimToken: str | None
    replayed: bool


@dataclass(frozen=True)
class GuidedCachedTurn:
    """无需再次调用供应商即可重提的已校验回合。"""

    claim: GuidedTurnClaim
    message: str
    language: str
    proposal: GuidedWorkflowProposal


class GuidedWorkflowRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def initialize(self) -> None:
        with self.database.writeLock, self.database.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS guided_workflows (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    language TEXT NOT NULL CHECK(language IN ('en', 'zh-CN')),
                    draft_json TEXT NOT NULL,
                    pending_proposal_json TEXT,
                    pending_proposal_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_guided_workflows_owner_updated
                ON guided_workflows(owner_user_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS guided_workflow_messages (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL REFERENCES guided_workflows(id) ON DELETE CASCADE,
                    owner_user_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    stage TEXT NOT NULL,
                    content TEXT NOT NULL,
                    proposal_id TEXT,
                    sequence_number INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_guided_messages_workflow_created
                ON guided_workflow_messages(workflow_id, created_at);
                CREATE TABLE IF NOT EXISTS guided_workflow_proposal_history (
                    id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL
                        REFERENCES guided_workflows(id) ON DELETE CASCADE,
                    owner_user_id TEXT NOT NULL,
                    proposal_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'APPLIED', 'SUPERSEDED', 'DISMISSED'
                    )),
                    reason TEXT NOT NULL CHECK(reason IN (
                        'APPLIED_BY_HUMAN',
                        'REPLACED_BY_NEW_PROPOSAL',
                        'STAGE_ADVANCED_BY_HUMAN',
                        'WORKFLOW_ARCHIVED_BY_HUMAN'
                    )),
                    archived_at TEXT NOT NULL,
                    PRIMARY KEY(workflow_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_guided_proposal_history_workflow
                ON guided_workflow_proposal_history(
                    workflow_id, owner_user_id, archived_at, id
                );
                CREATE TABLE IF NOT EXISTS guided_workflow_requests (
                    workflow_id TEXT NOT NULL REFERENCES guided_workflows(id) ON DELETE CASCADE,
                    owner_user_id TEXT NOT NULL,
                    client_request_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    response_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(workflow_id, client_request_id)
                );
                """
            )
            self._initializeTurnOperationTables(connection)
            messageColumns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(guided_workflow_messages)"
                ).fetchall()
            }
            if "sequence_number" not in messageColumns:
                # 已创建的开发/生产数据库可能还没有显式消息序号。先增量迁移，
                # 再按旧的时间与插入顺序回填，避免同一时刻写入的对话被按随机 ID 重排。
                connection.execute(
                    """
                    ALTER TABLE guided_workflow_messages
                    ADD COLUMN sequence_number INTEGER NOT NULL DEFAULT 0
                    """
                )
                rows = connection.execute(
                    """
                    SELECT rowid, workflow_id
                    FROM guided_workflow_messages
                    ORDER BY workflow_id, created_at, rowid
                    """
                ).fetchall()
                nextSequenceByWorkflow: dict[str, int] = {}
                for row in rows:
                    workflowId = row["workflow_id"]
                    sequenceNumber = nextSequenceByWorkflow.get(workflowId, 0) + 1
                    connection.execute(
                        """
                        UPDATE guided_workflow_messages
                        SET sequence_number=?
                        WHERE rowid=?
                        """,
                        (sequenceNumber, row["rowid"]),
                    )
                    nextSequenceByWorkflow[workflowId] = sequenceNumber
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_guided_messages_workflow_sequence
                ON guided_workflow_messages(workflow_id, sequence_number)
                """
            )
            self._backfillStageOpenings(connection)
            # 旧版只有成功后的 request 记录。将其迁移成已完成 operation，使升级后
            # 相同 clientRequestId 不会重新调用供应商；旧数据没有响应快照时只能返回
            # 当前工作流视图，新写入的 operation 会保存精确的首次响应。
            legacyRows = connection.execute(
                """
                SELECT workflow_id, owner_user_id, client_request_id, request_hash,
                       response_version, created_at
                FROM guided_workflow_requests
                ORDER BY created_at, workflow_id, client_request_id
                """
            ).fetchall()
            for row in legacyRows:
                try:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO guided_workflow_turn_operations(
                            workflow_id, owner_user_id, client_request_id, request_hash,
                            expected_version, status, response_version, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'SUCCEEDED', ?, ?, ?)
                        """,
                        (
                            row["workflow_id"],
                            row["owner_user_id"],
                            row["client_request_id"],
                            row["request_hash"],
                            max(1, int(row["response_version"]) - 1),
                            int(row["response_version"]),
                            row["created_at"],
                            row["created_at"],
                        ),
                    )
                except sqlite3.IntegrityError:
                    # 极旧或人工修复过的数据可能违反新的 expectedVersion 唯一约束。
                    # 保留原 request 记录，claim 时仍会识别并安全重放，绝不重新调用模型。
                    continue

    @staticmethod
    def _backfillStageOpenings(connection: sqlite3.Connection) -> None:
        """为旧库补齐当前阶段开场；不改工作流版本，也不重复插入。"""

        workflows = connection.execute(
            """
            SELECT id, owner_user_id, stage, language, updated_at
            FROM guided_workflows
            ORDER BY created_at, id
            """
        ).fetchall()
        for workflow in workflows:
            existing = connection.execute(
                """
                SELECT 1
                FROM guided_workflow_messages
                WHERE workflow_id=? AND owner_user_id=?
                  AND role='assistant' AND stage=?
                LIMIT 1
                """,
                (
                    workflow["id"],
                    workflow["owner_user_id"],
                    workflow["stage"],
                ),
            ).fetchone()
            if existing is not None:
                continue
            sequenceRow = connection.execute(
                """
                SELECT COALESCE(MAX(sequence_number), 0) AS maximum_sequence
                FROM guided_workflow_messages
                WHERE workflow_id=? AND owner_user_id=?
                """,
                (workflow["id"], workflow["owner_user_id"]),
            ).fetchone()
            stage = GuidedStage(workflow["stage"])
            connection.execute(
                """
                INSERT INTO guided_workflow_messages(
                    id, workflow_id, owner_user_id, role, stage, content,
                    proposal_id, sequence_number, created_at
                ) VALUES (?, ?, ?, 'assistant', ?, ?, NULL, ?, ?)
                """,
                (
                    guidedStageOpeningMessageId(workflow["id"], stage),
                    workflow["id"],
                    workflow["owner_user_id"],
                    stage.value,
                    guidedStageOpening(stage, workflow["language"]),
                    int(sequenceRow["maximum_sequence"]) + 1,
                    workflow["updated_at"],
                ),
            )

    @staticmethod
    def _initializeTurnOperationTables(connection: sqlite3.Connection) -> None:
        """兼容迁移旧 CHECK 约束，并只让活动操作占用工作流版本。"""

        existing = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='guided_workflow_turn_operations'
            """
        ).fetchone()
        requiredColumns = {
            "request_message",
            "language",
            "validated_proposal_json",
            "supersedes_client_request_id",
            "authorized_retry_client_request_id",
        }
        if existing is not None:
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(guided_workflow_turn_operations)"
                ).fetchall()
            }
            if not requiredColumns.issubset(columns):
                connection.execute("DROP INDEX IF EXISTS idx_guided_turn_operation_version")
                connection.execute(
                    """
                    ALTER TABLE guided_workflow_turn_operations
                    RENAME TO guided_workflow_turn_operations_legacy
                    """
                )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS guided_workflow_turn_operations (
                workflow_id TEXT NOT NULL REFERENCES guided_workflows(id) ON DELETE CASCADE,
                owner_user_id TEXT NOT NULL,
                client_request_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                expected_version INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN (
                    'PENDING', 'RESULT_READY', 'SUCCEEDED', 'UNKNOWN',
                    'ABANDONED_BY_USER'
                )),
                claim_token TEXT,
                request_message TEXT,
                language TEXT CHECK(language IS NULL OR language IN ('en', 'zh-CN')),
                validated_proposal_json TEXT,
                response_version INTEGER,
                response_json TEXT,
                error_code TEXT,
                supersedes_client_request_id TEXT,
                authorized_retry_client_request_id TEXT,
                provider_request_id TEXT,
                http_response_received INTEGER CHECK(
                    http_response_received IS NULL OR http_response_received IN (0, 1)
                ),
                usage_received INTEGER CHECK(
                    usage_received IS NULL OR usage_received IN (0, 1)
                ),
                parse_completed INTEGER CHECK(
                    parse_completed IS NULL OR parse_completed IN (0, 1)
                ),
                failure_stage TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(workflow_id, client_request_id)
            )
            """
        )
        legacy = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='guided_workflow_turn_operations_legacy'
            """
        ).fetchone()
        if legacy is not None:
            connection.execute(
                """
                INSERT INTO guided_workflow_turn_operations(
                    workflow_id, owner_user_id, client_request_id, request_hash,
                    expected_version, status, claim_token, response_version,
                    response_json, error_code, created_at, updated_at
                )
                SELECT workflow_id, owner_user_id, client_request_id, request_hash,
                       expected_version, status, claim_token, response_version,
                       response_json, error_code, created_at, updated_at
                FROM guided_workflow_turn_operations_legacy
                """
            )
            connection.execute("DROP TABLE guided_workflow_turn_operations_legacy")
        operationColumns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(guided_workflow_turn_operations)"
            ).fetchall()
        }
        evidenceColumns = {
            "provider_request_id": "TEXT",
            "http_response_received": "INTEGER",
            "usage_received": "INTEGER",
            "parse_completed": "INTEGER",
            "failure_stage": "TEXT",
        }
        for columnName, columnType in evidenceColumns.items():
            if columnName not in operationColumns:
                connection.execute(
                    f"ALTER TABLE guided_workflow_turn_operations "
                    f"ADD COLUMN {columnName} {columnType}"
                )
        connection.execute("DROP INDEX IF EXISTS idx_guided_turn_operation_version")
        connection.execute(
            """
            CREATE UNIQUE INDEX idx_guided_turn_operation_version
            ON guided_workflow_turn_operations(
                workflow_id, owner_user_id, expected_version
            )
            WHERE status IN ('PENDING', 'RESULT_READY', 'UNKNOWN')
            """
        )
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS guided_workflow_turn_recoveries (
                workflow_id TEXT NOT NULL REFERENCES guided_workflows(id) ON DELETE CASCADE,
                owner_user_id TEXT NOT NULL,
                recovery_request_id TEXT NOT NULL,
                client_request_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN (
                    'RETRY_CACHED_COMMIT', 'ABANDON_AND_AUTHORIZE_RETRY'
                )),
                new_client_request_id TEXT,
                response_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(workflow_id, recovery_request_id)
            );
            CREATE INDEX IF NOT EXISTS idx_guided_turn_recoveries_operation
            ON guided_workflow_turn_recoveries(
                workflow_id, owner_user_id, client_request_id, created_at
            );
            """
        )

    def create(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        language: str,
        greeting: str,
        now: datetime,
    ) -> GuidedWorkflowView:
        timestamp = _timestamp(now)
        with self.database.writeLock, self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO guided_workflows(
                    id, owner_user_id, stage, status, version, language, draft_json,
                    created_at, updated_at
                ) VALUES (?, ?, 'EVENT_GOAL', 'ACTIVE', 1, ?, ?, ?, ?)
                """,
                (
                    workflowId,
                    ownerUserId,
                    language,
                    GuidedWorkflowDraft().model_dump_json(),
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO guided_workflow_messages(
                    id, workflow_id, owner_user_id, role, stage, content,
                    sequence_number, created_at
                ) VALUES (?, ?, ?, 'assistant', 'EVENT_GOAL', ?, 1, ?)
                """,
                (
                    guidedStageOpeningMessageId(workflowId, GuidedStage.EVENT_GOAL),
                    workflowId,
                    ownerUserId,
                    greeting,
                    timestamp,
                ),
            )
        return self.get(workflowId, ownerUserId)

    def get(self, workflowId: str, ownerUserId: str) -> GuidedWorkflowView:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM guided_workflows
                WHERE id=? AND owner_user_id=?
                """,
                (workflowId, ownerUserId),
            ).fetchone()
            if row is None:
                raise LookupError("guided workflow does not exist")
            messages = connection.execute(
                """
                SELECT * FROM guided_workflow_messages
                WHERE workflow_id=? AND owner_user_id=?
                ORDER BY sequence_number, created_at, id
                """,
                (workflowId, ownerUserId),
            ).fetchall()
            archivedProposals = _proposalHistoryRows(
                connection,
                workflowId,
                ownerUserId,
            )
        return _view(row, messages, archivedProposals)

    def list(self, ownerUserId: str, *, limit: int = 20) -> list[GuidedWorkflowView]:
        safeLimit = max(1, min(limit, 50))
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id FROM guided_workflows
                WHERE owner_user_id=? AND status!='ARCHIVED'
                ORDER BY updated_at DESC LIMIT ?
                """,
                (ownerUserId, safeLimit),
            ).fetchall()
        return [self.get(row["id"], ownerUserId) for row in rows]

    def claimTurn(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        expectedVersion: int,
        clientRequestId: str,
        requestHash: str,
        requestMessage: str,
        language: str,
        now: datetime,
    ) -> GuidedTurnClaim:
        """在调用模型前原子占用 expectedVersion，或恢复首次成功响应。"""

        timestamp = _timestamp(now)
        claimToken = f"guided-turn-claim-{uuid.uuid4().hex}"
        with self.database.writeLock, self.database.connection() as connection:
            operation = connection.execute(
                """
                SELECT * FROM guided_workflow_turn_operations
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                """,
                (workflowId, ownerUserId, clientRequestId),
            ).fetchone()
            if operation is not None:
                if operation["request_hash"] != requestHash:
                    raise GuidedWorkflowConflictError(
                        "clientRequestId is already bound to a different guided turn"
                    )
                if operation["status"] == "SUCCEEDED":
                    return GuidedTurnClaim(
                        workflow=self._operationResponse(
                            connection,
                            workflowId,
                            ownerUserId,
                            operation["response_json"],
                        ),
                        requestHash=requestHash,
                        claimToken=None,
                        replayed=True,
                    )
                raise GuidedWorkflowConflictError(
                    "the original guided turn outcome is pending or unknown; "
                    "automatic provider retry is disabled"
                )

            legacy = connection.execute(
                """
                SELECT request_hash FROM guided_workflow_requests
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                """,
                (workflowId, ownerUserId, clientRequestId),
            ).fetchone()
            if legacy is not None:
                if legacy["request_hash"] != requestHash:
                    raise GuidedWorkflowConflictError(
                        "clientRequestId is already bound to a different guided turn"
                    )
                return GuidedTurnClaim(
                    workflow=self._operationResponse(
                        connection,
                        workflowId,
                        ownerUserId,
                        None,
                    ),
                    requestHash=requestHash,
                    claimToken=None,
                    replayed=True,
                )

            workflowRow = connection.execute(
                """
                SELECT * FROM guided_workflows
                WHERE id=? AND owner_user_id=?
                """,
                (workflowId, ownerUserId),
            ).fetchone()
            if workflowRow is None:
                raise LookupError("guided workflow does not exist")
            if (
                workflowRow["status"] != GuidedWorkflowStatus.ACTIVE.value
                or int(workflowRow["version"]) != expectedVersion
            ):
                raise GuidedWorkflowConflictError(
                    "guided workflow changed; reload before sending another turn"
                )
            abandoned = connection.execute(
                """
                SELECT client_request_id, authorized_retry_client_request_id
                FROM guided_workflow_turn_operations
                WHERE workflow_id=? AND owner_user_id=? AND expected_version=?
                  AND status='ABANDONED_BY_USER'
                ORDER BY updated_at DESC LIMIT 1
                """,
                (workflowId, ownerUserId, expectedVersion),
            ).fetchone()
            supersedesClientRequestId = None
            if abandoned is not None:
                if abandoned["authorized_retry_client_request_id"] != clientRequestId:
                    raise GuidedWorkflowConflictError(
                        "the abandoned guided turn only authorizes its declared retry request"
                    )
                supersedesClientRequestId = str(abandoned["client_request_id"])
            try:
                connection.execute(
                    """
                    INSERT INTO guided_workflow_turn_operations(
                        workflow_id, owner_user_id, client_request_id, request_hash,
                        expected_version, status, claim_token, request_message, language,
                        supersedes_client_request_id, failure_stage, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?,
                              'BEFORE_PROVIDER_DISPATCH', ?, ?)
                    """,
                    (
                        workflowId,
                        ownerUserId,
                        clientRequestId,
                        requestHash,
                        expectedVersion,
                        claimToken,
                        requestMessage,
                        language,
                        supersedesClientRequestId,
                        timestamp,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as error:
                # 不同 clientRequestId 对同一 expectedVersion 的并发请求也只能有
                # 一个取得模型调用权，避免双花供应商费用。
                raise GuidedWorkflowConflictError(
                    "another guided turn already owns this workflow version; reload before retrying"
                ) from error
            messages = connection.execute(
                """
                SELECT * FROM guided_workflow_messages
                WHERE workflow_id=? AND owner_user_id=?
                ORDER BY sequence_number, created_at, id
                """,
                (workflowId, ownerUserId),
            ).fetchall()
            workflow = _view(
                workflowRow,
                messages,
                _proposalHistoryRows(connection, workflowId, ownerUserId),
            )
        return GuidedTurnClaim(
            workflow=workflow,
            requestHash=requestHash,
            claimToken=claimToken,
            replayed=False,
        )

    def replayTurnIfKnown(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        clientRequestId: str,
        requestHash: str,
    ) -> GuidedWorkflowView | None:
        """只读检查幂等键；未知新请求不会写数据库。"""

        with self.database.connection() as connection:
            operation = connection.execute(
                """
                SELECT * FROM guided_workflow_turn_operations
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                """,
                (workflowId, ownerUserId, clientRequestId),
            ).fetchone()
            if operation is not None:
                if operation["request_hash"] != requestHash:
                    raise GuidedWorkflowConflictError(
                        "clientRequestId is already bound to a different guided turn"
                    )
                if operation["status"] == "SUCCEEDED":
                    return self._operationResponse(
                        connection,
                        workflowId,
                        ownerUserId,
                        operation["response_json"],
                    )
                raise GuidedWorkflowConflictError(
                    "the original guided turn outcome is pending or unknown; "
                    "automatic provider retry is disabled"
                )
            legacy = connection.execute(
                """
                SELECT request_hash FROM guided_workflow_requests
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                """,
                (workflowId, ownerUserId, clientRequestId),
            ).fetchone()
            if legacy is None:
                return None
            if legacy["request_hash"] != requestHash:
                raise GuidedWorkflowConflictError(
                    "clientRequestId is already bound to a different guided turn"
                )
            return self._operationResponse(
                connection,
                workflowId,
                ownerUserId,
                None,
            )

    def cacheValidatedProposal(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        clientRequestId: str,
        requestHash: str,
        claimToken: str,
        proposal: GuidedWorkflowProposal,
        now: datetime,
    ) -> None:
        """先保存已通过本地校验的提议，使后续提交失败无需再次调用模型。"""

        with self.database.writeLock, self.database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE guided_workflow_turn_operations
                SET status='RESULT_READY', validated_proposal_json=?,
                    parse_completed=1, failure_stage='DATABASE_COMMIT_PENDING',
                    updated_at=?
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                  AND request_hash=? AND status='PENDING' AND claim_token=?
                """,
                (
                    proposal.model_dump_json(),
                    _timestamp(now),
                    workflowId,
                    ownerUserId,
                    clientRequestId,
                    requestHash,
                    claimToken,
                ),
            )
            if cursor.rowcount != 1:
                raise GuidedWorkflowConflictError(
                    "the guided turn claim could not cache its validated proposal"
                )

    def recordTurnProviderEvidence(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        clientRequestId: str,
        requestHash: str,
        claimToken: str,
        providerRequestId: str | None,
        httpResponseReceived: bool | None,
        usageReceived: bool | None,
        parseCompleted: bool | None,
        failureStage: str,
        now: datetime,
    ) -> None:
        """记录供应商边界证据，但不保存未校验的模型正文。"""

        with self.database.writeLock, self.database.connection() as connection:
            connection.execute(
                """
                UPDATE guided_workflow_turn_operations
                SET provider_request_id=COALESCE(?, provider_request_id),
                    http_response_received=COALESCE(?, http_response_received),
                    usage_received=COALESCE(?, usage_received),
                    parse_completed=COALESCE(?, parse_completed),
                    failure_stage=?, updated_at=?
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                  AND request_hash=? AND status IN ('PENDING', 'RESULT_READY')
                  AND claim_token=?
                """,
                (
                    providerRequestId,
                    int(httpResponseReceived) if httpResponseReceived is not None else None,
                    int(usageReceived) if usageReceived is not None else None,
                    int(parseCompleted) if parseCompleted is not None else None,
                    failureStage[:80],
                    _timestamp(now),
                    workflowId,
                    ownerUserId,
                    clientRequestId,
                    requestHash,
                    claimToken,
                ),
            )

    def completeTurn(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        expectedVersion: int,
        clientRequestId: str,
        requestHash: str,
        claimToken: str,
        userMessage: GuidedWorkflowMessage,
        assistantMessage: GuidedWorkflowMessage,
        proposal: GuidedWorkflowProposal,
        proposalId: str,
        language: str,
        now: datetime,
        auditPayload: dict[str, Any] | None = None,
    ) -> GuidedWorkflowView:
        timestamp = _timestamp(now)
        with self.database.writeLock, self.database.connection() as connection:
            operation = connection.execute(
                """
                SELECT request_hash, status, claim_token
                FROM guided_workflow_turn_operations
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                """,
                (workflowId, ownerUserId, clientRequestId),
            ).fetchone()
            if (
                operation is None
                or operation["request_hash"] != requestHash
                or operation["status"] not in {"PENDING", "RESULT_READY"}
                or operation["claim_token"] != claimToken
            ):
                raise GuidedWorkflowConflictError("the guided turn claim is no longer valid")
            previousWorkflowRow = connection.execute(
                """
                SELECT * FROM guided_workflows
                WHERE id=? AND owner_user_id=?
                """,
                (workflowId, ownerUserId),
            ).fetchone()
            if previousWorkflowRow is None:
                raise LookupError("guided workflow does not exist")
            cursor = connection.execute(
                """
                UPDATE guided_workflows
                SET version=version+1, language=?, pending_proposal_json=?,
                    pending_proposal_id=?, updated_at=?
                WHERE id=? AND owner_user_id=? AND version=? AND status='ACTIVE'
                """,
                (
                    language,
                    proposal.model_dump_json(),
                    proposalId,
                    timestamp,
                    workflowId,
                    ownerUserId,
                    expectedVersion,
                ),
            )
            if cursor.rowcount != 1:
                raise GuidedWorkflowConflictError(
                    "guided workflow changed; reload before sending another turn"
                )
            _archivePendingProposalInConnection(
                connection,
                workflowRow=previousWorkflowRow,
                status=GuidedArchivedProposalStatus.SUPERSEDED,
                reason=GuidedArchivedProposalReason.REPLACED_BY_NEW_PROPOSAL,
                timestamp=timestamp,
            )
            sequenceRow = connection.execute(
                """
                SELECT COALESCE(MAX(sequence_number), 0) AS maximum_sequence
                FROM guided_workflow_messages
                WHERE workflow_id=? AND owner_user_id=?
                """,
                (workflowId, ownerUserId),
            ).fetchone()
            nextSequence = int(sequenceRow["maximum_sequence"]) + 1
            for offset, message in enumerate((userMessage, assistantMessage)):
                connection.execute(
                    """
                    INSERT INTO guided_workflow_messages(
                        id, workflow_id, owner_user_id, role, stage, content,
                        proposal_id, sequence_number, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.id,
                        workflowId,
                        ownerUserId,
                        message.role,
                        message.stage.value,
                        message.content,
                        message.proposalId,
                        nextSequence + offset,
                        message.createdAt.isoformat(),
                    ),
                )
            connection.execute(
                """
                INSERT INTO guided_workflow_requests(
                    workflow_id, owner_user_id, client_request_id, request_hash,
                    response_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    workflowId,
                    ownerUserId,
                    clientRequestId,
                    requestHash,
                    expectedVersion + 1,
                    timestamp,
                ),
            )
            workflowRow = connection.execute(
                """
                SELECT * FROM guided_workflows
                WHERE id=? AND owner_user_id=?
                """,
                (workflowId, ownerUserId),
            ).fetchone()
            messages = connection.execute(
                """
                SELECT * FROM guided_workflow_messages
                WHERE workflow_id=? AND owner_user_id=?
                ORDER BY sequence_number, created_at, id
                """,
                (workflowId, ownerUserId),
            ).fetchall()
            response = _view(
                workflowRow,
                messages,
                _proposalHistoryRows(connection, workflowId, ownerUserId),
            )
            if auditPayload is not None:
                # 回合提交、审计追加与幂等成功标记处于同一个 SQLite 事务，
                # 因而成功重放既不会漏记，也不会重复 TURN_PROPOSED。
                self.database._appendAuditEventInConnection(
                    connection,
                    ownerUserId,
                    "GUIDED_WORKFLOW",
                    workflowId,
                    "TURN_PROPOSED",
                    auditPayload,
                    timestamp,
                )
            connection.execute(
                """
                UPDATE guided_workflow_turn_operations
                SET status='SUCCEEDED', claim_token=NULL, response_version=?,
                    response_json=?, error_code=NULL, failure_stage='COMPLETED',
                    updated_at=?
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                  AND request_hash=? AND status IN ('PENDING', 'RESULT_READY')
                  AND claim_token=?
                """,
                (
                    response.version,
                    response.model_dump_json(),
                    timestamp,
                    workflowId,
                    ownerUserId,
                    clientRequestId,
                    requestHash,
                    claimToken,
                ),
            )
        return response

    def markTurnUnknown(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        clientRequestId: str,
        requestHash: str,
        claimToken: str,
        errorCode: str,
        now: datetime,
    ) -> None:
        """供应商或提交结果不确定时 fail-closed，禁止自动重新计费。"""

        with self.database.writeLock, self.database.connection() as connection:
            connection.execute(
                """
                UPDATE guided_workflow_turn_operations
                SET status='UNKNOWN', claim_token=NULL, error_code=?, updated_at=?
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                  AND request_hash=? AND status IN ('PENDING', 'RESULT_READY')
                  AND claim_token=?
                """,
                (
                    errorCode[:120],
                    _timestamp(now),
                    workflowId,
                    ownerUserId,
                    clientRequestId,
                    requestHash,
                    claimToken,
                ),
            )

    def listTurnOperations(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
    ) -> list[GuidedTurnOperationView]:
        # 先验证所有权，避免用空列表泄露其他账号是否存在该工作流。
        self.get(workflowId, ownerUserId)
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM guided_workflow_turn_operations
                WHERE workflow_id=? AND owner_user_id=?
                ORDER BY created_at, client_request_id
                """,
                (workflowId, ownerUserId),
            ).fetchall()
        return [_operationView(row) for row in rows]

    def recoverCachedTurn(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        clientRequestId: str,
        recoveryRequestId: str,
        expectedVersion: int,
        now: datetime,
    ) -> GuidedCachedTurn | GuidedWorkflowView:
        """为 UNKNOWN 的已缓存提议重新取得提交权，不进行供应商调用。"""

        timestamp = _timestamp(now)
        claimToken = f"guided-recovery-claim-{uuid.uuid4().hex}"
        with self.database.writeLock, self.database.connection() as connection:
            recovery = connection.execute(
                """
                SELECT * FROM guided_workflow_turn_recoveries
                WHERE workflow_id=? AND owner_user_id=? AND recovery_request_id=?
                """,
                (workflowId, ownerUserId, recoveryRequestId),
            ).fetchone()
            if recovery is not None:
                if (
                    recovery["client_request_id"] != clientRequestId
                    or recovery["action"] != GuidedTurnRecoveryAction.RETRY_CACHED_COMMIT.value
                ):
                    raise GuidedWorkflowConflictError(
                        "recoveryRequestId is already bound to a different recovery"
                    )
                if recovery["response_json"]:
                    return GuidedWorkflowView.model_validate_json(recovery["response_json"])
            else:
                connection.execute(
                    """
                    INSERT INTO guided_workflow_turn_recoveries(
                        workflow_id, owner_user_id, recovery_request_id,
                        client_request_id, action, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'RETRY_CACHED_COMMIT', ?, ?)
                    """,
                    (
                        workflowId,
                        ownerUserId,
                        recoveryRequestId,
                        clientRequestId,
                        timestamp,
                        timestamp,
                    ),
                )

            operation = connection.execute(
                """
                SELECT * FROM guided_workflow_turn_operations
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                """,
                (workflowId, ownerUserId, clientRequestId),
            ).fetchone()
            if operation is None:
                raise LookupError("guided turn operation does not exist")
            if int(operation["expected_version"]) != expectedVersion:
                raise GuidedWorkflowConflictError(
                    "guided turn recovery expectedVersion does not match the operation"
                )
            if operation["status"] == GuidedTurnOperationStatus.SUCCEEDED.value:
                response = self._operationResponse(
                    connection,
                    workflowId,
                    ownerUserId,
                    operation["response_json"],
                )
                self._completeRecoveryInConnection(
                    connection,
                    workflowId=workflowId,
                    ownerUserId=ownerUserId,
                    recoveryRequestId=recoveryRequestId,
                    response=response,
                    timestamp=timestamp,
                )
                return response
            if operation["status"] not in {
                GuidedTurnOperationStatus.UNKNOWN.value,
                GuidedTurnOperationStatus.RESULT_READY.value,
            }:
                raise GuidedWorkflowConflictError(
                    "only an unknown cached guided turn can retry its database commit"
                )
            if (
                not operation["validated_proposal_json"]
                or not operation["request_message"]
                or not operation["language"]
            ):
                raise GuidedWorkflowConflictError(
                    "the unknown guided turn has no validated proposal to recommit"
                )
            workflowRow = connection.execute(
                """
                SELECT * FROM guided_workflows
                WHERE id=? AND owner_user_id=?
                """,
                (workflowId, ownerUserId),
            ).fetchone()
            if (
                workflowRow is None
                or workflowRow["status"] != GuidedWorkflowStatus.ACTIVE.value
                or int(workflowRow["version"]) != expectedVersion
            ):
                raise GuidedWorkflowConflictError(
                    "guided workflow changed; cached proposal cannot be recommitted"
                )
            connection.execute(
                """
                UPDATE guided_workflow_turn_operations
                SET status='RESULT_READY', claim_token=?, error_code=NULL, updated_at=?
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                  AND status IN ('UNKNOWN', 'RESULT_READY')
                """,
                (
                    claimToken,
                    timestamp,
                    workflowId,
                    ownerUserId,
                    clientRequestId,
                ),
            )
            messages = connection.execute(
                """
                SELECT * FROM guided_workflow_messages
                WHERE workflow_id=? AND owner_user_id=?
                ORDER BY sequence_number, created_at, id
                """,
                (workflowId, ownerUserId),
            ).fetchall()
            workflow = _view(
                workflowRow,
                messages,
                _proposalHistoryRows(connection, workflowId, ownerUserId),
            )
            proposal = GuidedWorkflowProposal.model_validate_json(
                operation["validated_proposal_json"]
            )
            return GuidedCachedTurn(
                claim=GuidedTurnClaim(
                    workflow=workflow,
                    requestHash=str(operation["request_hash"]),
                    claimToken=claimToken,
                    replayed=False,
                ),
                message=str(operation["request_message"]),
                language=str(operation["language"]),
                proposal=proposal,
            )

    def abandonAndAuthorizeRetry(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        clientRequestId: str,
        recoveryRequestId: str,
        expectedVersion: int,
        newClientRequestId: str,
        now: datetime,
    ) -> GuidedTurnOperationView:
        """由用户明确放弃未知结果，并仅授权一个新的幂等请求 ID。"""

        timestamp = _timestamp(now)
        with self.database.writeLock, self.database.connection() as connection:
            recovery = connection.execute(
                """
                SELECT * FROM guided_workflow_turn_recoveries
                WHERE workflow_id=? AND owner_user_id=? AND recovery_request_id=?
                """,
                (workflowId, ownerUserId, recoveryRequestId),
            ).fetchone()
            if recovery is not None:
                if (
                    recovery["client_request_id"] != clientRequestId
                    or recovery["action"]
                    != GuidedTurnRecoveryAction.ABANDON_AND_AUTHORIZE_RETRY.value
                    or recovery["new_client_request_id"] != newClientRequestId
                ):
                    raise GuidedWorkflowConflictError(
                        "recoveryRequestId is already bound to a different recovery"
                    )
                if recovery["response_json"]:
                    return GuidedTurnOperationView.model_validate_json(recovery["response_json"])
            else:
                connection.execute(
                    """
                    INSERT INTO guided_workflow_turn_recoveries(
                        workflow_id, owner_user_id, recovery_request_id,
                        client_request_id, action, new_client_request_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'ABANDON_AND_AUTHORIZE_RETRY', ?, ?, ?)
                    """,
                    (
                        workflowId,
                        ownerUserId,
                        recoveryRequestId,
                        clientRequestId,
                        newClientRequestId,
                        timestamp,
                        timestamp,
                    ),
                )
            operation = connection.execute(
                """
                SELECT * FROM guided_workflow_turn_operations
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                """,
                (workflowId, ownerUserId, clientRequestId),
            ).fetchone()
            if operation is None:
                raise LookupError("guided turn operation does not exist")
            if int(operation["expected_version"]) != expectedVersion:
                raise GuidedWorkflowConflictError(
                    "guided turn recovery expectedVersion does not match the operation"
                )
            if operation["status"] == GuidedTurnOperationStatus.UNKNOWN.value:
                connection.execute(
                    """
                    UPDATE guided_workflow_turn_operations
                    SET status='ABANDONED_BY_USER',
                        authorized_retry_client_request_id=?, updated_at=?
                    WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                      AND status='UNKNOWN'
                    """,
                    (
                        newClientRequestId,
                        timestamp,
                        workflowId,
                        ownerUserId,
                        clientRequestId,
                    ),
                )
                operation = connection.execute(
                    """
                    SELECT * FROM guided_workflow_turn_operations
                    WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                    """,
                    (workflowId, ownerUserId, clientRequestId),
                ).fetchone()
            elif (
                operation["status"] != GuidedTurnOperationStatus.ABANDONED_BY_USER.value
                or operation["authorized_retry_client_request_id"] != newClientRequestId
            ):
                raise GuidedWorkflowConflictError(
                    "only an unknown guided turn can be abandoned for retry"
                )
            view = _operationView(operation)
            connection.execute(
                """
                UPDATE guided_workflow_turn_recoveries
                SET response_json=?, updated_at=?
                WHERE workflow_id=? AND owner_user_id=? AND recovery_request_id=?
                """,
                (
                    view.model_dump_json(),
                    timestamp,
                    workflowId,
                    ownerUserId,
                    recoveryRequestId,
                ),
            )
            return view

    def completeTurnRecovery(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        recoveryRequestId: str,
        response: GuidedWorkflowView,
        now: datetime,
    ) -> None:
        with self.database.writeLock, self.database.connection() as connection:
            self._completeRecoveryInConnection(
                connection,
                workflowId=workflowId,
                ownerUserId=ownerUserId,
                recoveryRequestId=recoveryRequestId,
                response=response,
                timestamp=_timestamp(now),
            )

    @staticmethod
    def _completeRecoveryInConnection(
        connection: sqlite3.Connection,
        *,
        workflowId: str,
        ownerUserId: str,
        recoveryRequestId: str,
        response: GuidedWorkflowView,
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            UPDATE guided_workflow_turn_recoveries
            SET response_json=?, updated_at=?
            WHERE workflow_id=? AND owner_user_id=? AND recovery_request_id=?
            """,
            (
                response.model_dump_json(),
                timestamp,
                workflowId,
                ownerUserId,
                recoveryRequestId,
            ),
        )

    @staticmethod
    def _operationResponse(
        connection: sqlite3.Connection,
        workflowId: str,
        ownerUserId: str,
        responseJson: str | None,
    ) -> GuidedWorkflowView:
        if responseJson:
            return GuidedWorkflowView.model_validate_json(responseJson)
        workflowRow = connection.execute(
            """
            SELECT * FROM guided_workflows
            WHERE id=? AND owner_user_id=?
            """,
            (workflowId, ownerUserId),
        ).fetchone()
        if workflowRow is None:
            raise LookupError("guided workflow does not exist")
        messages = connection.execute(
            """
            SELECT * FROM guided_workflow_messages
            WHERE workflow_id=? AND owner_user_id=?
            ORDER BY sequence_number, created_at, id
            """,
            (workflowId, ownerUserId),
        ).fetchall()
        return _view(
            workflowRow,
            messages,
            _proposalHistoryRows(connection, workflowId, ownerUserId),
        )

    def archive(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        expectedVersion: int,
        now: datetime,
    ) -> GuidedWorkflowView:
        timestamp = _timestamp(now)
        with self.database.writeLock, self.database.connection() as connection:
            workflowRow = connection.execute(
                """
                SELECT * FROM guided_workflows
                WHERE id=? AND owner_user_id=?
                """,
                (workflowId, ownerUserId),
            ).fetchone()
            cursor = connection.execute(
                """
                UPDATE guided_workflows
                SET version=version+1, status='ARCHIVED',
                    pending_proposal_json=NULL, pending_proposal_id=NULL, updated_at=?
                WHERE id=? AND owner_user_id=? AND version=? AND status!='ARCHIVED'
                """,
                (
                    timestamp,
                    workflowId,
                    ownerUserId,
                    expectedVersion,
                ),
            )
            if cursor.rowcount != 1:
                raise GuidedWorkflowConflictError("guided workflow changed or is already archived")
            if workflowRow is None:
                raise LookupError("guided workflow does not exist")
            _archivePendingProposalInConnection(
                connection,
                workflowRow=workflowRow,
                status=GuidedArchivedProposalStatus.DISMISSED,
                reason=GuidedArchivedProposalReason.WORKFLOW_ARCHIVED_BY_HUMAN,
                timestamp=timestamp,
            )
        return self.get(workflowId, ownerUserId)

    def applyProposal(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        proposalId: str,
        expectedVersion: int,
        now: datetime,
    ) -> GuidedWorkflowView:
        current = self.get(workflowId, ownerUserId)
        if current.version != expectedVersion:
            raise GuidedWorkflowConflictError("guided workflow changed; reload before applying")
        if current.pendingProposalId != proposalId or current.pendingProposal is None:
            raise GuidedWorkflowConflictError("the pending proposal is no longer current")
        proposal = current.pendingProposal
        if not proposal.readyForHumanReview or proposal.missingFields or proposal.unresolvedFields:
            # 前端会禁用“应用”按钮，但后端仍必须独立执行同一权限边界，避免直接
            # 调用 API 将 unknown/TBD 等未解决内容推进到正式草稿。
            raise GuidedWorkflowConflictError(
                "the pending proposal is not ready for human application; "
                "resolve every missing field first"
            )
        draft = current.draft.model_copy(deep=True)
        if proposal.proposedEventMetadata is not None:
            draft.eventMetadata = proposal.proposedEventMetadata
        if proposal.proposedSourceMethod is not None:
            draft.sourceMethod = proposal.proposedSourceMethod
        if proposal.proposedSearchQueries:
            draft.searchQueries = proposal.proposedSearchQueries
        if proposal.proposedIntervention is not None:
            draft.intervention = proposal.proposedIntervention
        timestamp = _timestamp(now)
        with self.database.writeLock, self.database.connection() as connection:
            workflowRow = connection.execute(
                """
                SELECT * FROM guided_workflows
                WHERE id=? AND owner_user_id=?
                """,
                (workflowId, ownerUserId),
            ).fetchone()
            cursor = connection.execute(
                """
                UPDATE guided_workflows
                SET version=version+1, draft_json=?, pending_proposal_json=NULL,
                    pending_proposal_id=NULL, updated_at=?
                WHERE id=? AND owner_user_id=? AND version=? AND pending_proposal_id=?
                """,
                (
                    draft.model_dump_json(),
                    timestamp,
                    workflowId,
                    ownerUserId,
                    expectedVersion,
                    proposalId,
                ),
            )
            if cursor.rowcount != 1:
                raise GuidedWorkflowConflictError("guided workflow changed; reload before applying")
            if workflowRow is None:
                raise LookupError("guided workflow does not exist")
            _archivePendingProposalInConnection(
                connection,
                workflowRow=workflowRow,
                status=GuidedArchivedProposalStatus.APPLIED,
                reason=GuidedArchivedProposalReason.APPLIED_BY_HUMAN,
                timestamp=timestamp,
            )
        return self.get(workflowId, ownerUserId)

    def advance(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        expectedVersion: int,
        nextStage: GuidedStage,
        openingMessage: GuidedWorkflowMessage,
        now: datetime,
    ) -> GuidedWorkflowView:
        if (
            openingMessage.role != "assistant"
            or openingMessage.stage is not nextStage
            or openingMessage.proposalId is not None
        ):
            raise ValueError("guided stage opening message does not match the next stage")
        status = (
            GuidedWorkflowStatus.COMPLETED.value
            if nextStage is GuidedStage.COMPLETED
            else GuidedWorkflowStatus.ACTIVE.value
        )
        timestamp = _timestamp(now)
        with self.database.writeLock, self.database.connection() as connection:
            workflowRow = connection.execute(
                """
                SELECT * FROM guided_workflows
                WHERE id=? AND owner_user_id=?
                """,
                (workflowId, ownerUserId),
            ).fetchone()
            cursor = connection.execute(
                """
                UPDATE guided_workflows
                SET version=version+1, stage=?, status=?, pending_proposal_json=NULL,
                    pending_proposal_id=NULL, updated_at=?
                WHERE id=? AND owner_user_id=? AND version=? AND status='ACTIVE'
                """,
                (
                    nextStage.value,
                    status,
                    timestamp,
                    workflowId,
                    ownerUserId,
                    expectedVersion,
                ),
            )
            if cursor.rowcount != 1:
                raise GuidedWorkflowConflictError(
                    "guided workflow changed; reload before continuing"
                )
            if workflowRow is None:
                raise LookupError("guided workflow does not exist")
            _archivePendingProposalInConnection(
                connection,
                workflowRow=workflowRow,
                status=GuidedArchivedProposalStatus.DISMISSED,
                reason=GuidedArchivedProposalReason.STAGE_ADVANCED_BY_HUMAN,
                timestamp=timestamp,
            )
            sequenceRow = connection.execute(
                """
                SELECT COALESCE(MAX(sequence_number), 0) AS maximum_sequence
                FROM guided_workflow_messages
                WHERE workflow_id=? AND owner_user_id=?
                """,
                (workflowId, ownerUserId),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO guided_workflow_messages(
                    id, workflow_id, owner_user_id, role, stage, content,
                    proposal_id, sequence_number, created_at
                ) VALUES (?, ?, ?, 'assistant', ?, ?, NULL, ?, ?)
                """,
                (
                    openingMessage.id,
                    workflowId,
                    ownerUserId,
                    nextStage.value,
                    openingMessage.content,
                    int(sequenceRow["maximum_sequence"]) + 1,
                    _timestamp(openingMessage.createdAt),
                ),
            )
        return self.get(workflowId, ownerUserId)

    def linkArtifacts(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        expectedVersion: int,
        draft: GuidedWorkflowDraft,
        now: datetime,
    ) -> GuidedWorkflowView:
        with self.database.writeLock, self.database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE guided_workflows
                SET version=version+1, draft_json=?, updated_at=?
                WHERE id=? AND owner_user_id=? AND version=? AND status='ACTIVE'
                """,
                (
                    draft.model_dump_json(),
                    _timestamp(now),
                    workflowId,
                    ownerUserId,
                    expectedVersion,
                ),
            )
            if cursor.rowcount != 1:
                raise GuidedWorkflowConflictError(
                    "guided workflow changed; reload before linking an artifact"
                )
        return self.get(workflowId, ownerUserId)


def _archivePendingProposalInConnection(
    connection: sqlite3.Connection,
    *,
    workflowRow: sqlite3.Row,
    status: GuidedArchivedProposalStatus,
    reason: GuidedArchivedProposalReason,
    timestamp: str,
) -> None:
    proposalId = workflowRow["pending_proposal_id"]
    proposalJson = workflowRow["pending_proposal_json"]
    if proposalId is None and proposalJson is None:
        return
    if not proposalId or not proposalJson:
        raise RuntimeError("guided pending proposal identity and payload are inconsistent")
    # 旧库中的待审提议也必须先通过当前严格模型，不能把损坏或宽松 JSON
    # 静默复制到只读历史。
    proposal = GuidedWorkflowProposal.model_validate_json(proposalJson)
    connection.execute(
        """
        INSERT INTO guided_workflow_proposal_history(
            id, workflow_id, owner_user_id, proposal_json,
            status, reason, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            proposalId,
            workflowRow["id"],
            workflowRow["owner_user_id"],
            proposal.model_dump_json(),
            status.value,
            reason.value,
            timestamp,
        ),
    )


def _timestamp(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat()


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _proposalHistoryRows(
    connection: sqlite3.Connection,
    workflowId: str,
    ownerUserId: str,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT *
        FROM guided_workflow_proposal_history
        WHERE workflow_id=? AND owner_user_id=?
        ORDER BY archived_at, id
        """,
        (workflowId, ownerUserId),
    ).fetchall()


def _view(
    row: sqlite3.Row,
    messageRows: list[sqlite3.Row],
    archivedProposalRows: list[sqlite3.Row],
) -> GuidedWorkflowView:
    pending = (
        GuidedWorkflowProposal.model_validate_json(row["pending_proposal_json"])
        if row["pending_proposal_json"]
        else None
    )
    return GuidedWorkflowView(
        id=row["id"],
        stage=GuidedStage(row["stage"]),
        status=GuidedWorkflowStatus(row["status"]),
        version=int(row["version"]),
        language=row["language"],
        draft=GuidedWorkflowDraft.model_validate_json(row["draft_json"]),
        pendingProposal=pending,
        pendingProposalId=row["pending_proposal_id"],
        archivedProposals=tuple(
            GuidedArchivedProposal(
                id=archived["id"],
                proposal=GuidedWorkflowProposal.model_validate_json(archived["proposal_json"]),
                status=GuidedArchivedProposalStatus(archived["status"]),
                archivedAt=_datetime(archived["archived_at"]),
                reason=GuidedArchivedProposalReason(archived["reason"]),
            )
            for archived in archivedProposalRows
        ),
        messages=tuple(
            GuidedWorkflowMessage(
                id=message["id"],
                role=message["role"],
                stage=GuidedStage(message["stage"]),
                content=message["content"],
                proposalId=message["proposal_id"],
                createdAt=_datetime(message["created_at"]),
            )
            for message in messageRows
        ),
        createdAt=_datetime(row["created_at"]),
        updatedAt=_datetime(row["updated_at"]),
    )


def _operationView(row: sqlite3.Row) -> GuidedTurnOperationView:
    status = GuidedTurnOperationStatus(row["status"])
    cachedProposalAvailable = bool(row["validated_proposal_json"])
    recoveryOptions: list[GuidedTurnRecoveryAction] = []
    if status is GuidedTurnOperationStatus.UNKNOWN:
        if cachedProposalAvailable:
            recoveryOptions.append(GuidedTurnRecoveryAction.RETRY_CACHED_COMMIT)
        recoveryOptions.append(GuidedTurnRecoveryAction.ABANDON_AND_AUTHORIZE_RETRY)
    return GuidedTurnOperationView(
        workflowId=row["workflow_id"],
        clientRequestId=row["client_request_id"],
        expectedVersion=int(row["expected_version"]),
        status=status,
        errorCode=row["error_code"],
        requestMessage=row["request_message"],
        language=row["language"],
        cachedProposalAvailable=cachedProposalAvailable,
        supersedesClientRequestId=row["supersedes_client_request_id"],
        authorizedRetryClientRequestId=row["authorized_retry_client_request_id"],
        recoveryOptions=tuple(recoveryOptions),
        providerRequestId=row["provider_request_id"],
        httpResponseReceived=(
            bool(row["http_response_received"])
            if row["http_response_received"] is not None
            else None
        ),
        usageReceived=(bool(row["usage_received"]) if row["usage_received"] is not None else None),
        parseCompleted=(
            bool(row["parse_completed"]) if row["parse_completed"] is not None else None
        ),
        failureStage=row["failure_stage"],
        createdAt=_datetime(row["created_at"]),
        updatedAt=_datetime(row["updated_at"]),
    )
