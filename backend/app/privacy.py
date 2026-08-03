"""账号数据导出与删除。

该服务只读取明确列入白名单的账号和研究表。导出不会包含密码摘要、会话
token、CSRF 摘要、验证码摘要、API Key 或实验 checkpoint 二进制；删除会
覆盖当前 SQLite 主库中的账号数据，但主机备份仍按运营方保留策略到期。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from backend.app.database import Database

PRIVACY_EXPORT_SCHEMA_VERSION = "account_data_export_v1.0.0"

_SENSITIVE_COLUMNS = frozenset(
    {
        "password_hash",
        "token_hash",
        "csrf_hash",
        "code_hash",
        "checkpoint_blob",
        "encrypted_payload",
        "key_id",
    }
)


class LastAdministratorDeletionError(RuntimeError):
    """最后一个启用中的管理员不能通过自助流程删除。"""


class AccountNotFoundError(RuntimeError):
    pass


class AccountPrivacyService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def exportAccountData(self, *, userId: str) -> dict[str, Any]:
        """生成当前账号拥有的数据快照，不读取任何凭据字段。"""

        with self.database.connection() as connection:
            account = self._accountRow(connection, userId)
            if account is None:
                raise AccountNotFoundError("account does not exist")
            exports = {
                "account": _exportRows(
                    connection,
                    """
                    SELECT id, email_normalized, role, status, email_verified_at,
                           created_at, updated_at, last_login_at, password_changed_at
                    FROM auth_users WHERE id=?
                    """,
                    (userId,),
                ),
                "preferences": _exportRows(
                    connection,
                    "SELECT * FROM auth_user_preferences WHERE user_id=?",
                    (userId,),
                ),
                "legalAcceptances": _exportRows(
                    connection,
                    "SELECT * FROM auth_legal_acceptances WHERE user_id=?",
                    (userId,),
                ),
                "legalAcceptanceEvents": _exportRows(
                    connection,
                    "SELECT * FROM auth_legal_acceptance_events WHERE user_id=?",
                    (userId,),
                ),
                "accountActivity": _exportRows(
                    connection,
                    "SELECT * FROM auth_activity_events WHERE user_id=? ORDER BY created_at",
                    (userId,),
                ),
                "guidedWorkflows": _exportRows(
                    connection,
                    "SELECT * FROM guided_workflows WHERE owner_user_id=?",
                    (userId,),
                ),
                "guidedMessages": _exportRows(
                    connection,
                    """
                    SELECT message.*
                    FROM guided_workflow_messages AS message
                    JOIN guided_workflows AS workflow ON workflow.id=message.workflow_id
                    WHERE workflow.owner_user_id=?
                    ORDER BY message.created_at, message.sequence_number
                    """,
                    (userId,),
                ),
                "guidedArchivedProposals": _exportRows(
                    connection,
                    """
                    SELECT proposal.*
                    FROM guided_workflow_proposal_history AS proposal
                    JOIN guided_workflows AS workflow ON workflow.id=proposal.workflow_id
                    WHERE workflow.owner_user_id=?
                    ORDER BY proposal.archived_at, proposal.id
                    """,
                    (userId,),
                ),
                "factoryBuilds": _exportRows(
                    connection,
                    "SELECT * FROM event_pack_factory_builds WHERE owner_user_id=?",
                    (userId,),
                ),
                "factorySources": _exportRows(
                    connection,
                    """
                    SELECT source.*
                    FROM event_pack_factory_sources AS source
                    JOIN event_pack_factory_builds AS build ON build.id=source.build_id
                    WHERE build.owner_user_id=?
                    ORDER BY source.created_at
                    """,
                    (userId,),
                ),
                "factorySourceBodies": _exportRows(
                    connection,
                    """
                    SELECT source_id, build_id, raw_text, created_at, updated_at
                    FROM event_pack_factory_source_payloads
                    WHERE owner_user_id=?
                    """,
                    (userId,),
                ),
                "customEventPacks": _exportRows(
                    connection,
                    "SELECT * FROM custom_event_packs WHERE owner_user_id=?",
                    (userId,),
                ),
                "eventPackDrafts": _exportRows(
                    connection,
                    "SELECT * FROM event_pack_drafts WHERE owner_user_id=?",
                    (userId,),
                ),
                "scenarios": _exportRows(
                    connection,
                    "SELECT * FROM scenarios WHERE owner_user_id=?",
                    (userId,),
                ),
                "experiments": _exportRows(
                    connection,
                    """
                    SELECT id, session_id, owner_user_id, idempotency_key, status,
                           request_json, result_json, error_code, progress,
                           completed_pairs, total_pairs, cancel_requested, created_at,
                           updated_at, started_at, completed_at, runtime_json,
                           invalidated_at, invalidation_reason_code, invalidation_reason
                    FROM experiments WHERE owner_user_id=?
                    """,
                    (userId,),
                ),
                "resultInterpretations": _exportRows(
                    connection,
                    """
                    SELECT * FROM result_interpretation_exchanges
                    WHERE owner_user_id=? ORDER BY created_at, id
                    """,
                    (userId,),
                ),
                "studyRuns": _exportRows(
                    connection,
                    "SELECT * FROM study_runs WHERE owner_user_id=?",
                    (userId,),
                ),
                "researchAuditEvents": _exportRows(
                    connection,
                    "SELECT * FROM audit_events WHERE owner_user_id=? ORDER BY created_at, id",
                    (userId,),
                ),
            }
        return {
            "schemaVersion": PRIVACY_EXPORT_SCHEMA_VERSION,
            "generatedAt": datetime.now(UTC).isoformat(),
            "retentionNotice": (
                "This export reflects the live application database. Deleted records may "
                "remain in encrypted or access-controlled host backups until their normal "
                "retention period expires."
            ),
            "excludedSecrets": sorted(_SENSITIVE_COLUMNS),
            "data": exports,
        }

    def deleteAccountData(self, *, userId: str) -> dict[str, int]:
        """在一个事务内删除账号及其所有活动研究对象。"""

        deleted: dict[str, int] = {}
        with self.database.writeLock, self.database.connection() as connection:
            connection.execute("PRAGMA secure_delete=ON")
            account = self._accountRow(connection, userId)
            if account is None:
                raise AccountNotFoundError("account does not exist")
            if account["role"] == "ADMIN":
                activeAdmins = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM auth_users
                        WHERE role='ADMIN' AND status='ACTIVE'
                        """
                    ).fetchone()[0]
                )
                if activeAdmins <= 1:
                    raise LastAdministratorDeletionError(
                        "the final active administrator cannot self-delete"
                    )

            email = str(account["email_normalized"])
            # 先解除来源的自引用，再由 build 的级联删除清理来源与暂存正文。
            if _tableExists(connection, "event_pack_factory_sources"):
                connection.execute(
                    """
                    UPDATE event_pack_factory_sources
                    SET parent_source_id=NULL
                    WHERE build_id IN (
                        SELECT id FROM event_pack_factory_builds WHERE owner_user_id=?
                    )
                    """,
                    (userId,),
                )
            for tableName, predicate, value in (
                ("guided_workflows", "owner_user_id=?", userId),
                ("event_pack_factory_builds", "owner_user_id=?", userId),
                ("result_interpretation_exchanges", "owner_user_id=?", userId),
                ("result_interpretation_tombstones", "owner_user_id=?", userId),
                ("study_runs", "owner_user_id=?", userId),
                ("experiments", "owner_user_id=?", userId),
                ("audit_events", "owner_user_id=?", userId),
                ("scenarios", "owner_user_id=?", userId),
                ("event_pack_drafts", "owner_user_id=?", userId),
                ("custom_event_packs", "owner_user_id=?", userId),
                ("auth_user_preferences", "user_id=?", userId),
                ("auth_persistent_llm_credentials", "user_id=?", userId),
                ("auth_legal_acceptance_events", "user_id=?", userId),
                ("auth_legal_acceptances", "user_id=?", userId),
                ("auth_sessions", "user_id=?", userId),
                ("auth_activity_events", "user_id=?", userId),
                ("auth_challenges", "email_normalized=? COLLATE NOCASE", email),
            ):
                if not _tableExists(connection, tableName):
                    continue
                cursor = connection.execute(
                    f"DELETE FROM {tableName} WHERE {predicate}",  # noqa: S608
                    (value,),
                )
                deleted[tableName] = max(cursor.rowcount, 0)
            cursor = connection.execute("DELETE FROM auth_users WHERE id=?", (userId,))
            deleted["auth_users"] = max(cursor.rowcount, 0)
            # 保留不含账号、邮箱或会话标识的最小运维计数，不再能关联回个人。
            connection.execute(
                """
                INSERT INTO auth_activity_events(user_id, action, status, metadata_json, created_at)
                VALUES (NULL, 'ACCOUNT_DELETED', 'SUCCEEDED', '{}', ?)
                """,
                (datetime.now(UTC).isoformat(),),
            )
        # 截断 WAL，减少已删除账号数据在活动日志中的驻留时间；主机备份不受此影响。
        with self.database.connection() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return deleted

    @staticmethod
    def _accountRow(
        connection: sqlite3.Connection,
        userId: str,
    ) -> sqlite3.Row | None:
        if not _tableExists(connection, "auth_users"):
            return None
        return connection.execute("SELECT * FROM auth_users WHERE id=?", (userId,)).fetchone()


def _exportRows(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...],
) -> list[dict[str, Any]]:
    try:
        rows = connection.execute(query, parameters).fetchall()
    except sqlite3.OperationalError as error:
        if "no such table" in str(error):
            return []
        raise
    return [_safeRow(dict(row)) for row in rows]


def _safeRow(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if key in _SENSITIVE_COLUMNS or isinstance(value, bytes):
            continue
        if key.endswith("_json") and isinstance(value, str):
            try:
                result[key.removesuffix("_json")] = json.loads(value)
            except json.JSONDecodeError:
                result[key.removesuffix("_json")] = value
            continue
        result[key] = value
    return result


def _tableExists(connection: sqlite3.Connection, tableName: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (tableName,),
        ).fetchone()
        is not None
    )
