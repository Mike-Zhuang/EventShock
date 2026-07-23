"""SQLite 持久化的引导工作流；只保存清理后的消息和严格草稿。"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.app.database import Database
from backend.app.guided_workflow.models import (
    GuidedStage,
    GuidedWorkflowDraft,
    GuidedWorkflowMessage,
    GuidedWorkflowProposal,
    GuidedWorkflowStatus,
    GuidedWorkflowView,
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
                CREATE TABLE IF NOT EXISTS guided_workflow_requests (
                    workflow_id TEXT NOT NULL REFERENCES guided_workflows(id) ON DELETE CASCADE,
                    owner_user_id TEXT NOT NULL,
                    client_request_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    response_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(workflow_id, client_request_id)
                );
                CREATE TABLE IF NOT EXISTS guided_workflow_turn_operations (
                    workflow_id TEXT NOT NULL REFERENCES guided_workflows(id) ON DELETE CASCADE,
                    owner_user_id TEXT NOT NULL,
                    client_request_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    expected_version INTEGER NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('PENDING', 'SUCCEEDED', 'UNKNOWN')),
                    claim_token TEXT,
                    response_version INTEGER,
                    response_json TEXT,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(workflow_id, client_request_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_guided_turn_operation_version
                ON guided_workflow_turn_operations(
                    workflow_id, owner_user_id, expected_version
                );
                """
            )
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
                (f"msg-{workflowId}-welcome", workflowId, ownerUserId, greeting, timestamp),
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
        return _view(row, messages)

    def list(self, ownerUserId: str, *, limit: int = 20) -> list[GuidedWorkflowView]:
        safeLimit = max(1, min(limit, 50))
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id FROM guided_workflows
                WHERE owner_user_id=?
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
            try:
                connection.execute(
                    """
                    INSERT INTO guided_workflow_turn_operations(
                        workflow_id, owner_user_id, client_request_id, request_hash,
                        expected_version, status, claim_token, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
                    """,
                    (
                        workflowId,
                        ownerUserId,
                        clientRequestId,
                        requestHash,
                        expectedVersion,
                        claimToken,
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
            workflow = _view(workflowRow, messages)
        return GuidedTurnClaim(
            workflow=workflow,
            requestHash=requestHash,
            claimToken=claimToken,
            replayed=False,
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
                or operation["status"] != "PENDING"
                or operation["claim_token"] != claimToken
            ):
                raise GuidedWorkflowConflictError("the guided turn claim is no longer valid")
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
            response = _view(workflowRow, messages)
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
                    response_json=?, error_code=NULL, updated_at=?
                WHERE workflow_id=? AND owner_user_id=? AND client_request_id=?
                  AND request_hash=? AND status='PENDING' AND claim_token=?
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
                  AND request_hash=? AND status='PENDING' AND claim_token=?
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
        return _view(workflowRow, messages)

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
        draft = current.draft.model_copy(deep=True)
        proposal = current.pendingProposal
        if proposal.proposedEventMetadata is not None:
            draft.eventMetadata = proposal.proposedEventMetadata
        if proposal.proposedSourceMethod is not None:
            draft.sourceMethod = proposal.proposedSourceMethod
        if proposal.proposedSearchQueries:
            draft.searchQueries = proposal.proposedSearchQueries
        if proposal.proposedIntervention is not None:
            draft.intervention = proposal.proposedIntervention
        with self.database.writeLock, self.database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE guided_workflows
                SET version=version+1, draft_json=?, pending_proposal_json=NULL,
                    pending_proposal_id=NULL, updated_at=?
                WHERE id=? AND owner_user_id=? AND version=? AND pending_proposal_id=?
                """,
                (
                    draft.model_dump_json(),
                    _timestamp(now),
                    workflowId,
                    ownerUserId,
                    expectedVersion,
                    proposalId,
                ),
            )
            if cursor.rowcount != 1:
                raise GuidedWorkflowConflictError("guided workflow changed; reload before applying")
        return self.get(workflowId, ownerUserId)

    def advance(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        expectedVersion: int,
        nextStage: GuidedStage,
        now: datetime,
    ) -> GuidedWorkflowView:
        status = (
            GuidedWorkflowStatus.COMPLETED.value
            if nextStage is GuidedStage.COMPLETED
            else GuidedWorkflowStatus.ACTIVE.value
        )
        with self.database.writeLock, self.database.connection() as connection:
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
                    _timestamp(now),
                    workflowId,
                    ownerUserId,
                    expectedVersion,
                ),
            )
            if cursor.rowcount != 1:
                raise GuidedWorkflowConflictError(
                    "guided workflow changed; reload before continuing"
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


def _timestamp(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat()


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _view(
    row: sqlite3.Row,
    messageRows: list[sqlite3.Row],
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
