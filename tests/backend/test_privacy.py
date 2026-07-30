from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.auth.models import UserRole
from backend.app.auth.passwords import hashPassword
from backend.app.auth.repository import AuthRepository
from backend.app.database import Database, utcNow
from backend.app.event_pack_factory.repository import EventPackFactoryRepository
from backend.app.guided_workflow.repository import GuidedWorkflowRepository
from backend.app.privacy import (
    AccountNotFoundError,
    AccountPrivacyService,
    LastAdministratorDeletionError,
)


def initializedServices(tmp_path: Path) -> tuple[Database, AuthRepository, AccountPrivacyService]:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    authRepository = AuthRepository(database)
    authRepository.initialize()
    GuidedWorkflowRepository(database).initialize()
    EventPackFactoryRepository(database.databasePath).initialize()
    return database, authRepository, AccountPrivacyService(database)


def test_account_export_excludes_authentication_secrets(tmp_path: Path) -> None:
    database, authRepository, privacy = initializedServices(tmp_path)
    user = authRepository.createUser(
        userId="usr-privacy-export",
        email="researcher@example.com",
        passwordHash=hashPassword("ValidPassword-123"),
    )
    authRepository.recordActivity(
        userId=user.id,
        action="LOGIN_SUCCEEDED",
        metadata={"safe": True},
    )
    with database.writeLock, database.connection() as connection:
        timestamp = utcNow()
        connection.execute(
            """
            INSERT INTO guided_workflows(
                id, owner_user_id, stage, status, version, language, draft_json,
                pending_proposal_json, pending_proposal_id, created_at, updated_at
            ) VALUES (?, ?, 'EVENT', 'ACTIVE', 1, 'en', ?, NULL, NULL, ?, ?)
            """,
            (
                "gw-privacy-export",
                user.id,
                json.dumps({"event": {"title": "Example event"}}),
                timestamp,
                timestamp,
            ),
        )

    exported = privacy.exportAccountData(userId=user.id)
    assert exported["schemaVersion"] == "account_data_export_v1.0.0"
    assert exported["data"]["account"][0]["email_normalized"] == "researcher@example.com"
    assert exported["data"]["guidedWorkflows"][0]["draft"]["event"]["title"] == "Example event"
    exportedKeys = {key for rows in exported["data"].values() for row in rows for key in row}
    assert (
        not {
            "password_hash",
            "token_hash",
            "csrf_hash",
            "code_hash",
            "checkpoint_blob",
        }
        & exportedKeys
    )


def test_account_deletion_removes_owned_data_and_account(tmp_path: Path) -> None:
    database, authRepository, privacy = initializedServices(tmp_path)
    user = authRepository.createUser(
        userId="usr-privacy-delete",
        email="delete-me@example.com",
        passwordHash=hashPassword("ValidPassword-123"),
    )
    with database.writeLock, database.connection() as connection:
        timestamp = utcNow()
        connection.execute(
            """
            INSERT INTO scenarios(
                id, session_id, owner_user_id, name, config_json, frozen,
                content_hash, created_at, updated_at
            ) VALUES ('scenario-delete', ?, ?, 'Delete me', '{}', 0, ?, ?, ?)
            """,
            (user.id, user.id, "0" * 64, timestamp, timestamp),
        )

    deleted = privacy.deleteAccountData(userId=user.id)

    assert deleted["auth_users"] == 1
    assert deleted["scenarios"] == 1
    assert authRepository.getUserById(user.id) is None
    with pytest.raises(AccountNotFoundError):
        privacy.exportAccountData(userId=user.id)


def test_final_active_administrator_cannot_self_delete(tmp_path: Path) -> None:
    _database, authRepository, privacy = initializedServices(tmp_path)
    admin = authRepository.createUser(
        userId="usr-final-admin",
        email="admin@example.com",
        passwordHash=hashPassword("ValidPassword-123"),
        role=UserRole.ADMIN,
    )

    with pytest.raises(LastAdministratorDeletionError):
        privacy.deleteAccountData(userId=admin.id)

    assert authRepository.getUserById(admin.id) is not None
