from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from backend.app.auth.bootstrap_admin import bootstrapAdmin
from backend.app.auth.models import UserRole
from backend.app.auth.passwords import hashPassword
from backend.app.auth.repository import AuthRepository
from backend.app.cognition.config_store import SessionConfigStore
from backend.app.cognition.gateway import AdvancedModelParameters
from backend.app.cognition.persistent_credentials import (
    AdminPersistentCredentialVault,
    PersistentCredentialUnavailableError,
    adminCredentialReference,
)
from backend.app.database import Database

ADMIN_EMAIL = "administrator@example.com"
ADMIN_PASSWORD = "Administrator password!"


def createVault(
    dataDir: Path,
    *,
    encryptionKey: bytes,
) -> tuple[Database, AdminPersistentCredentialVault, str]:
    database = Database(dataDir / "eventshock.db")
    database.initialize()
    userId, _created, _claimed = bootstrapAdmin(
        database=database,
        adminEmail=ADMIN_EMAIL,
        password=ADMIN_PASSWORD,
    )
    vault = AdminPersistentCredentialVault(
        database=database,
        encryptionKey=encryptionKey.decode("ascii"),
        configuredAdminEmail=ADMIN_EMAIL,
    )
    vault.initialize()
    return database, vault, userId


def saveCredential(
    vault: AdminPersistentCredentialVault,
    *,
    userId: str,
    apiKey: str,
) -> None:
    vault.save(
        userId=userId,
        apiKey=apiKey,
        provider="zhipu",
        model="glm-4.5-air",
        thinkingEnabled=False,
        maxTokens=2_048,
        advancedParameters=AdvancedModelParameters(),
    )


def test_admin_credential_is_encrypted_and_survives_vault_restart(tmp_path: Path) -> None:
    encryptionKey = Fernet.generate_key()
    database, vault, userId = createVault(tmp_path, encryptionKey=encryptionKey)
    apiKey = "persistent-provider-key-4826"

    saveCredential(vault, userId=userId, apiKey=apiKey)

    with database.connection() as connection:
        row = connection.execute(
            "SELECT * FROM auth_persistent_llm_credentials WHERE user_id=?",
            (userId,),
        ).fetchone()
    assert row is not None
    assert apiKey not in str(row["encrypted_payload"])
    assert row["encryption_version"] == "fernet-v1"
    assert len(str(row["key_id"])) == 16

    restartedVault = AdminPersistentCredentialVault(
        database=database,
        encryptionKey=encryptionKey.decode("ascii"),
        configuredAdminEmail=ADMIN_EMAIL,
    )
    restartedVault.initialize()
    view = restartedVault.getView(userId)
    runtime = restartedVault.resolveRuntimeReference(
        adminCredentialReference(
            userId=userId,
            authSessionId="auth-session-12345678",
        )
    )

    assert view.configured is True
    assert view.credentialHint == "••••4826"
    assert view.storageScope == "ADMIN_SERVER_ENCRYPTED"
    assert runtime is not None
    assert runtime.apiKey == apiKey
    assert apiKey not in repr(runtime)
    databaseBytes = database.databasePath.read_bytes()
    walPath = Path(f"{database.databasePath}-wal")
    if walPath.exists():
        databaseBytes += walPath.read_bytes()
    assert apiKey.encode("utf-8") not in databaseBytes


def test_admin_can_update_model_settings_without_resubmitting_api_key(tmp_path: Path) -> None:
    database, vault, userId = createVault(tmp_path, encryptionKey=Fernet.generate_key())
    apiKey = "persistent-provider-key-keep-4826"
    saveCredential(vault, userId=userId, apiKey=apiKey)
    before = vault.getView(userId)

    updated = vault.updateConfiguration(
        userId=userId,
        model="glm-5.2",
        thinkingEnabled=False,
        maxTokens=4_096,
        advancedParameters=AdvancedModelParameters(temperature=0.2),
    )
    runtime = vault.resolveRuntimeReference(
        adminCredentialReference(
            userId=userId,
            authSessionId="auth-session-update-12345678",
        )
    )

    assert updated.model == "glm-5.2"
    assert updated.maxTokens == 4_096
    assert updated.credentialHint == "••••4826"
    assert updated.persistedAt == before.persistedAt
    assert runtime is not None
    assert runtime.apiKey == apiKey
    assert runtime.advancedParameters.temperature == 0.2
    databaseBytes = database.databasePath.read_bytes()
    walPath = Path(f"{database.databasePath}-wal")
    if walPath.exists():
        databaseBytes += walPath.read_bytes()
    assert apiKey.encode("utf-8") not in databaseBytes


def test_session_config_precedes_then_falls_back_to_admin_vault(tmp_path: Path) -> None:
    database, vault, userId = createVault(tmp_path, encryptionKey=Fernet.generate_key())
    saveCredential(vault, userId=userId, apiKey="persistent-provider-key-1111")
    reference = adminCredentialReference(
        userId=userId,
        authSessionId="auth-session-87654321",
    )
    store = SessionConfigStore(
        persistentRuntimeResolver=vault.resolveRuntimeReference,
        persistentViewResolver=vault.resolveViewReference,
    )

    assert store.getView(reference).credential_source == "ADMIN_SERVER_ENCRYPTED"
    assert store.getRuntimeConfig(reference).apiKey == "persistent-provider-key-1111"

    store.setConfig(
        sessionId=reference,
        apiKey="temporary-provider-key-2222",
        provider="zhipu",
        model="glm-4.5-air",
    )
    assert store.getView(reference).credential_source == "SESSION"
    assert store.getRuntimeConfig(reference).apiKey == "temporary-provider-key-2222"

    assert store.clear(reference) is True
    assert store.getView(reference).credential_source == "ADMIN_SERVER_ENCRYPTED"
    assert store.getRuntimeConfig(reference).apiKey == "persistent-provider-key-1111"


def test_wrong_master_key_and_tampered_ciphertext_fail_closed(tmp_path: Path) -> None:
    database, vault, userId = createVault(tmp_path, encryptionKey=Fernet.generate_key())
    saveCredential(vault, userId=userId, apiKey="persistent-provider-key-3333")

    wrongKeyVault = AdminPersistentCredentialVault(
        database=database,
        encryptionKey=Fernet.generate_key().decode("ascii"),
        configuredAdminEmail=ADMIN_EMAIL,
    )
    with pytest.raises(
        PersistentCredentialUnavailableError,
        match="stored administrator model credential is unavailable",
    ):
        wrongKeyVault.getView(userId)

    with database.writeLock, database.connection() as connection:
        connection.execute(
            """
            UPDATE auth_persistent_llm_credentials
            SET encrypted_payload='invalid-authenticated-ciphertext'
            WHERE user_id=?
            """,
            (userId,),
        )
    with pytest.raises(
        PersistentCredentialUnavailableError,
        match="stored administrator model credential is unavailable",
    ):
        vault.getView(userId)


def test_unknown_or_non_admin_references_do_not_resolve(tmp_path: Path) -> None:
    database, vault, userId = createVault(tmp_path, encryptionKey=Fernet.generate_key())
    saveCredential(vault, userId=userId, apiKey="persistent-provider-key-4444")

    repository = AuthRepository(database)
    otherAdmin = repository.createUser(
        userId="usr-other-administrator-12345678",
        email="other-administrator@example.com",
        passwordHash=hashPassword("Other administrator password!"),
        role=UserRole.ADMIN,
    )
    with pytest.raises(PermissionError, match="configured administrator access is required"):
        saveCredential(
            vault,
            userId=otherAdmin.id,
            apiKey="other-administrator-key-5555",
        )

    assert vault.resolveRuntimeReference("ordinary-session-12345678") is None
    assert (
        vault.resolveRuntimeReference(
            adminCredentialReference(
                userId="usr-not-the-configured-admin",
                authSessionId="auth-session-12345678",
            )
        )
        is None
    )
