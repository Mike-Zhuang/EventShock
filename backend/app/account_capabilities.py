"""按账户授予的内部产品能力；配置只保存在服务器数据库中。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from backend.app.database import Database


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


class AccountCapabilityRepository:
    """保存稀疏账户能力，避免把账号或邮箱硬编码进产品逻辑。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def initialize(self) -> None:
        with self.database.writeLock, self.database.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS account_capabilities (
                    user_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    configuration_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, capability)
                );
                CREATE INDEX IF NOT EXISTS idx_account_capabilities_capability
                ON account_capabilities(capability, updated_at DESC);
                """
            )

    def grant(
        self,
        *,
        userId: str,
        capability: str,
        configuration: dict[str, Any],
    ) -> None:
        now = _timestamp()
        serialized = json.dumps(configuration, ensure_ascii=False, sort_keys=True)
        with self.database.writeLock, self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO account_capabilities(
                    user_id, capability, configuration_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, capability) DO UPDATE SET
                    configuration_json=excluded.configuration_json,
                    updated_at=excluded.updated_at
                """,
                (userId, capability, serialized, now, now),
            )

    def revoke(self, *, userId: str, capability: str) -> bool:
        with self.database.writeLock, self.database.connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM account_capabilities
                WHERE user_id=? AND capability=?
                """,
                (userId, capability),
            )
        return cursor.rowcount > 0

    def getConfiguration(self, *, userId: str, capability: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT configuration_json
                FROM account_capabilities
                WHERE user_id=? AND capability=?
                """,
                (userId, capability),
            ).fetchone()
        if row is None:
            return None
        configuration = json.loads(row["configuration_json"])
        if not isinstance(configuration, dict):
            raise ValueError("account capability configuration must be a JSON object")
        return configuration
