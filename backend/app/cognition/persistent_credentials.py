"""仅供部署指定管理员使用的服务器端加密模型凭据库。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from pydantic import Field

from backend.app.auth import normalizeEmail
from backend.app.cognition.catalog import ProviderId
from backend.app.cognition.config_store import (
    SESSION_PATTERN,
    RuntimeProviderConfig,
    SessionProviderConfigView,
    validateApiKey,
    validateProviderConfiguration,
)
from backend.app.cognition.gateway import AdvancedModelParameters
from backend.app.cognition.models import StrictFrozenModel
from backend.app.database import Database

ADMIN_CREDENTIAL_REFERENCE_PREFIX = "admin-vault"
ENCRYPTION_VERSION = "fernet-v1"
ENVELOPE_SCHEMA_VERSION = "admin_llm_credential_v1.0.0"


class PersistentCredentialUnavailableError(RuntimeError):
    """主密钥、密文或信封异常时统一失败关闭，避免泄露具体秘密状态。"""


class PersistentCredentialEnvelope(StrictFrozenModel):
    schemaVersion: Literal["admin_llm_credential_v1.0.0"] = ENVELOPE_SCHEMA_VERSION
    ownerUserId: str = Field(min_length=8, max_length=128)
    provider: ProviderId
    model: str = Field(min_length=3, max_length=128)
    thinkingEnabled: bool = False
    maxTokens: int = Field(ge=1)
    advancedParameters: AdvancedModelParameters = Field(default_factory=AdvancedModelParameters)
    apiKey: str = Field(min_length=8, max_length=4_096, repr=False)


class AdminPersistentCredentialView(StrictFrozenModel):
    available: bool = True
    configured: bool
    storageScope: Literal["ADMIN_SERVER_ENCRYPTED"] = "ADMIN_SERVER_ENCRYPTED"
    provider: ProviderId | None = None
    model: str | None = None
    thinkingEnabled: bool | None = None
    maxTokens: int | None = Field(default=None, ge=1)
    advancedParameters: AdvancedModelParameters | None = None
    credentialHint: str | None = None
    persistedAt: datetime | None = None
    updatedAt: datetime | None = None


def adminCredentialReference(*, userId: str, authSessionId: str) -> str:
    """构造管理员凭据作用域；会话后缀只隔离临时覆盖，不授予访问权限。"""

    return f"{ADMIN_CREDENTIAL_REFERENCE_PREFIX}:{userId}:{authSessionId}"


class AdminPersistentCredentialVault:
    """数据库只保存认证密文；明文仅在受信任调用栈内短暂存在。"""

    def __init__(
        self,
        *,
        database: Database,
        encryptionKey: str,
        configuredAdminEmail: str,
    ) -> None:
        try:
            self._fernet = Fernet(encryptionKey.encode("ascii"))
        except (ValueError, TypeError, UnicodeEncodeError) as error:
            raise ValueError("administrator API key encryption key is invalid") from error
        self._database = database
        self._configuredAdminEmail = normalizeEmail(configuredAdminEmail)
        self._keyId = hashlib.sha256(encryptionKey.encode("ascii")).hexdigest()[:16]

    def initialize(self) -> None:
        with self._database.writeLock, self._database.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_persistent_llm_credentials (
                    user_id TEXT PRIMARY KEY
                        REFERENCES auth_users(id) ON DELETE CASCADE,
                    encryption_version TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    encrypted_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def save(
        self,
        *,
        userId: str,
        apiKey: str,
        provider: ProviderId,
        model: str,
        thinkingEnabled: bool,
        maxTokens: int,
        advancedParameters: AdvancedModelParameters,
    ) -> AdminPersistentCredentialView:
        self._requireConfiguredAdministrator(userId)
        validateApiKey(apiKey)
        validatedAdvancedParameters = validateProviderConfiguration(
            provider=provider,
            model=model,
            thinkingEnabled=thinkingEnabled,
            maxTokens=maxTokens,
            advancedParameters=advancedParameters,
        )
        envelope = PersistentCredentialEnvelope(
            ownerUserId=userId,
            provider=provider,
            model=model,
            thinkingEnabled=thinkingEnabled,
            maxTokens=maxTokens,
            advancedParameters=validatedAdvancedParameters,
            apiKey=apiKey,
        )
        serialized = json.dumps(
            envelope.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        encryptedPayload = self._fernet.encrypt(serialized).decode("ascii")
        now = datetime.now(UTC).isoformat()
        with self._database.writeLock, self._database.connection() as connection:
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute(
                """
                INSERT INTO auth_persistent_llm_credentials(
                    user_id, encryption_version, key_id, encrypted_payload,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    encryption_version=excluded.encryption_version,
                    key_id=excluded.key_id,
                    encrypted_payload=excluded.encrypted_payload,
                    updated_at=excluded.updated_at
                """,
                (userId, ENCRYPTION_VERSION, self._keyId, encryptedPayload, now, now),
            )
        self._checkpointWal()
        return self.getView(userId)

    def getView(self, userId: str) -> AdminPersistentCredentialView:
        self._requireConfiguredAdministrator(userId)
        row = self._credentialRow(userId)
        if row is None:
            return AdminPersistentCredentialView(configured=False)
        envelope = self._decryptRow(row, expectedUserId=userId)
        return AdminPersistentCredentialView(
            configured=True,
            provider=envelope.provider,
            model=envelope.model,
            thinkingEnabled=envelope.thinkingEnabled,
            maxTokens=envelope.maxTokens,
            advancedParameters=envelope.advancedParameters,
            credentialHint=f"••••{envelope.apiKey[-4:]}",
            persistedAt=datetime.fromisoformat(str(row["created_at"])),
            updatedAt=datetime.fromisoformat(str(row["updated_at"])),
        )

    def delete(self, userId: str) -> AdminPersistentCredentialView:
        self._requireConfiguredAdministrator(userId)
        with self._database.writeLock, self._database.connection() as connection:
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute(
                "DELETE FROM auth_persistent_llm_credentials WHERE user_id=?",
                (userId,),
            )
        self._checkpointWal()
        return AdminPersistentCredentialView(configured=False)

    def resolveRuntimeReference(self, reference: str) -> RuntimeProviderConfig | None:
        userId = self._referenceUserId(reference)
        if userId is None or not self._isConfiguredAdministrator(userId):
            return None
        row = self._credentialRow(userId)
        if row is None:
            return None
        envelope = self._decryptRow(row, expectedUserId=userId)
        return RuntimeProviderConfig(
            provider=envelope.provider,
            model=envelope.model,
            thinkingEnabled=envelope.thinkingEnabled,
            maxTokens=envelope.maxTokens,
            advancedParameters=envelope.advancedParameters,
            apiKey=envelope.apiKey,
        )

    def resolveViewReference(self, reference: str) -> SessionProviderConfigView | None:
        userId = self._referenceUserId(reference)
        if userId is None or not self._isConfiguredAdministrator(userId):
            return None
        row = self._credentialRow(userId)
        if row is None:
            return None
        envelope = self._decryptRow(row, expectedUserId=userId)
        return SessionProviderConfigView(
            configured=True,
            provider=envelope.provider,
            model=envelope.model,
            thinking_enabled=envelope.thinkingEnabled,
            max_tokens=envelope.maxTokens,
            advanced_parameters=envelope.advancedParameters,
            credential_hint=f"••••{envelope.apiKey[-4:]}",
            expires_at=None,
            credential_source="ADMIN_SERVER_ENCRYPTED",
        )

    def _credentialRow(self, userId: str):
        with self._database.connection() as connection:
            return connection.execute(
                "SELECT * FROM auth_persistent_llm_credentials WHERE user_id=?",
                (userId,),
            ).fetchone()

    def _checkpointWal(self) -> None:
        """替换或删除高价值密文后截断活动 WAL，降低旧密文驻留时间。"""

        with self._database.writeLock, self._database.connection() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _decryptRow(self, row, *, expectedUserId: str) -> PersistentCredentialEnvelope:
        try:
            if (
                str(row["encryption_version"]) != ENCRYPTION_VERSION
                or str(row["key_id"]) != self._keyId
            ):
                raise PersistentCredentialUnavailableError(
                    "stored administrator model credential is unavailable"
                )
            decrypted = self._fernet.decrypt(str(row["encrypted_payload"]).encode("ascii"))
            payload = json.loads(decrypted.decode("utf-8"))
            envelope = PersistentCredentialEnvelope.model_validate(payload)
            if envelope.ownerUserId != expectedUserId:
                raise PersistentCredentialUnavailableError(
                    "stored administrator model credential is unavailable"
                )
            validateApiKey(envelope.apiKey)
            validateProviderConfiguration(
                provider=envelope.provider,
                model=envelope.model,
                thinkingEnabled=envelope.thinkingEnabled,
                maxTokens=envelope.maxTokens,
                advancedParameters=envelope.advancedParameters,
            )
            return envelope
        except PersistentCredentialUnavailableError:
            raise
        except (InvalidToken, ValueError, TypeError, UnicodeError, json.JSONDecodeError) as error:
            raise PersistentCredentialUnavailableError(
                "stored administrator model credential is unavailable"
            ) from error

    def _requireConfiguredAdministrator(self, userId: str) -> None:
        if not self._isConfiguredAdministrator(userId):
            raise PermissionError("configured administrator access is required")

    def _isConfiguredAdministrator(self, userId: str) -> bool:
        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT email_normalized, role, status FROM auth_users WHERE id=?
                """,
                (userId,),
            ).fetchone()
        return bool(
            row is not None
            and str(row["email_normalized"]).casefold() == self._configuredAdminEmail.casefold()
            and str(row["role"]) == "ADMIN"
            and str(row["status"]) == "ACTIVE"
        )

    @staticmethod
    def _referenceUserId(reference: str) -> str | None:
        # authSessionId 只让当前登录会话的临时 Key 保持隔离。持久凭据的授权
        # 始终由 userId 对应的实时邮箱、角色和账号状态决定，后台任务因此可在
        # 原登录会话结束后继续完成已经获准的实验。
        parts = reference.split(":", maxsplit=2)
        if len(parts) != 3 or parts[0] != ADMIN_CREDENTIAL_REFERENCE_PREFIX:
            return None
        userId, authSessionId = parts[1], parts[2]
        if not SESSION_PATTERN.fullmatch(userId) or not SESSION_PATTERN.fullmatch(authSessionId):
            return None
        return userId
