from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.app.auth import (
    AuthContext,
    AuthenticationError,
    AuthorizationError,
    AuthRepository,
    AuthService,
    ChallengePurpose,
    ChallengeVerificationError,
    PasswordPolicyError,
    UserRole,
    UserStatus,
    hashPassword,
    normalizeEmail,
    verifyPassword,
)
from backend.app.auth.bootstrap_admin import bootstrapAdmin
from backend.app.auth.mailer import _message
from backend.app.auth.models import AuthLocale
from backend.app.database import Database
from backend.app.legal import (
    CURRENT_TERMS_VERSION,
    currentDocumentHashes,
    legalDocument,
    validateCurrentAcceptance,
)

AUTH_SECRET = "test-auth-secret-with-at-least-thirty-two-bytes"
USER_PASSWORD = "Correct horse battery staple!"
NEW_PASSWORD = "A different long password!"
EXPECTED_LEGAL_DOCUMENT_HASHES = {
    "2026-07-22-v1": {
        "en": "cd08923873839602425d9343553decb727a7b616e2b6507e64c216cf4326a192",
        "zh-CN": "1558c4bec885da6ad1c3a44b7bde504f883b760004112f7fcc30c317678d467a",
    }
}


def _legalArguments(locale: AuthLocale = "en") -> dict[str, object]:
    document = legalDocument(locale)
    return {
        "legalVersion": document.version,
        "legalDocumentHash": document.documentHash,
        "legalLocale": locale,
        "acceptedTerms": True,
        "acknowledgedPrivacy": True,
        "confirmedMinimumAge": True,
        "acknowledgedAiBoundary": True,
    }


@dataclass
class SentCode:
    recipient: str
    code: str
    purpose: ChallengePurpose
    locale: AuthLocale


@dataclass
class FakeMailer:
    messages: list[SentCode] = field(default_factory=list)

    async def sendVerificationCode(
        self,
        *,
        recipient: str,
        code: str,
        purpose: ChallengePurpose,
        locale: AuthLocale,
        expiresMinutes: int,
    ) -> None:
        assert expiresMinutes == 10
        self.messages.append(SentCode(recipient, code, purpose, locale))


def _authFixture(
    tmp_path: Path,
) -> tuple[Database, AuthRepository, AuthService, FakeMailer, list[datetime]]:
    database = Database(tmp_path / "eventshock.db")
    database.initialize()
    repository = AuthRepository(database)
    repository.initialize()
    mailer = FakeMailer()
    now = [datetime(2026, 7, 20, 12, 0, tzinfo=UTC)]
    service = AuthService(
        repository=repository,
        mailer=mailer,
        authSecret=AUTH_SECRET,
        clock=lambda: now[0],
    )
    return database, repository, service, mailer, now


def _register(service: AuthService, mailer: FakeMailer, email: str) -> str:
    dispatch = asyncio.run(service.requestRegistrationCode(email=email, locale="en"))
    assert mailer.messages[-1].recipient == normalizeEmail(email)
    user = asyncio.run(
        service.register(
            challengeId=dispatch.challengeId,
            code=mailer.messages[-1].code,
            password=USER_PASSWORD,
            **_legalArguments(),
        )
    )
    return user.id


def test_legal_document_content_change_requires_intentional_version_snapshot() -> None:
    """正文变更不能在不更新版本快照的情况下悄然进入生产。"""

    assert CURRENT_TERMS_VERSION in EXPECTED_LEGAL_DOCUMENT_HASHES
    assert currentDocumentHashes() == EXPECTED_LEGAL_DOCUMENT_HASHES[CURRENT_TERMS_VERSION]


@pytest.mark.parametrize(
    "statement",
    ["acceptedTerms", "confirmedMinimumAge", "acknowledgedAiBoundary"],
)
def test_legal_consent_validation_rejects_false_statements(statement: str) -> None:
    """任一必需声明显式为 false 时都不构成有效同意，必须整体拒绝。"""

    document = legalDocument("en")
    statements = {
        "acceptedTerms": True,
        "confirmedMinimumAge": True,
        "acknowledgedAiBoundary": True,
        statement: False,
    }
    with pytest.raises(ValueError, match="must be affirmed"):
        validateCurrentAcceptance(
            version=document.version,
            documentHash=document.documentHash,
            locale="en",
            **statements,
        )


def test_scrypt_password_hash_is_versioned_salted_and_non_reversible() -> None:
    first = hashPassword(USER_PASSWORD)
    second = hashPassword(USER_PASSWORD)

    assert first.startswith("scrypt$v=1$n=16384$r=8$p=1$")
    assert first != second
    assert USER_PASSWORD not in first
    assert verifyPassword(USER_PASSWORD, first)
    assert not verifyPassword("not the password", first)
    assert not verifyPassword(USER_PASSWORD, "malformed")
    assert verifyPassword("Eight8!!", hashPassword("Eight8!!"))
    with pytest.raises(ValueError):
        hashPassword("Short7")


def test_registration_login_csrf_logout_and_password_reset_are_isolated(
    tmp_path: Path,
) -> None:
    database, repository, service, mailer, now = _authFixture(tmp_path)
    email = "Analyst@Example.com"
    userId = _register(service, mailer, email)

    with pytest.raises(ChallengeVerificationError):
        dispatch = asyncio.run(
            service.requestRegistrationCode(email="second@example.com", locale="en")
        )
        asyncio.run(
            service.register(
                challengeId=dispatch.challengeId,
                code="000000",
                password=USER_PASSWORD,
                **_legalArguments(),
            )
        )

    with pytest.raises(AuthenticationError):
        service.login(email=email, password="wrong password")

    issued = service.login(email=email, password=USER_PASSWORD)
    assert service.csrfToken(issued.token) == issued.csrfToken
    restartedService = AuthService(
        repository=repository,
        mailer=mailer,
        authSecret=AUTH_SECRET,
        clock=lambda: now[0],
    )
    assert restartedService.csrfToken(issued.token) == issued.csrfToken
    context = service.authenticate(token=issued.token)
    assert context.userId == userId
    assert context.authSessionId == issued.sessionId
    with pytest.raises(AuthenticationError):
        service.authenticate(
            token=issued.token,
            csrfToken="wrong-csrf-token",
            requireCsrf=True,
        )
    assert (
        service.authenticate(
            token=issued.token,
            csrfToken=issued.csrfToken,
            requireCsrf=True,
        ).userId
        == userId
    )

    reset = asyncio.run(service.requestPasswordResetCode(email=email, locale="zh-CN"))
    resetMessage = mailer.messages[-1]
    assert resetMessage.locale == "zh-CN"
    asyncio.run(
        service.resetPassword(
            challengeId=reset.challengeId,
            code=resetMessage.code,
            newPassword=NEW_PASSWORD,
        )
    )
    with pytest.raises(AuthenticationError):
        service.authenticate(token=issued.token)
    with pytest.raises(AuthenticationError):
        service.login(email=email, password=USER_PASSWORD)
    replacement = service.login(email=email, password=NEW_PASSWORD)
    assert service.logout(token=replacement.token) == userId
    with pytest.raises(AuthenticationError):
        service.authenticate(token=replacement.token)

    databaseBytes = database.databasePath.read_bytes()
    for secret in (
        USER_PASSWORD,
        NEW_PASSWORD,
        issued.token,
        issued.csrfToken,
        resetMessage.code,
    ):
        assert secret.encode() not in databaseBytes
    assert repository.getUserByEmail(normalizeEmail(email)) is not None


def test_reaccepting_same_version_repairs_stale_document_hash(tmp_path: Path) -> None:
    database, repository, service, mailer, _now = _authFixture(tmp_path)
    userId = _register(service, mailer, "reaccept@example.com")
    issued = service.login(email="reaccept@example.com", password=USER_PASSWORD)
    currentDocument = legalDocument("en")

    with database.writeLock, database.connection() as connection:
        initialEventRows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM auth_legal_acceptance_events
                WHERE user_id=? AND document_version=?
                ORDER BY id
                """,
                (userId, currentDocument.version),
            ).fetchall()
        ]
        assert len(initialEventRows) == 3
        assert {row["acceptance_method"] for row in initialEventRows} == {"REGISTRATION"}
        connection.execute(
            """
            UPDATE auth_legal_acceptances
            SET document_sha256=?
            WHERE user_id=? AND document_version=?
            """,
            ("0" * 64, userId, currentDocument.version),
        )

    assert repository.getLegalAcceptanceStatus(userId).required is True
    accepted = service.acceptCurrentLegalDocuments(
        service.authenticate(
            token=issued.token,
            csrfToken=issued.csrfToken,
            requireCsrf=True,
        ),
        version=currentDocument.version,
        documentHash=currentDocument.documentHash,
        locale="en",
        acceptedTerms=True,
        acknowledgedPrivacy=True,
        confirmedMinimumAge=True,
        acknowledgedAiBoundary=True,
    )

    assert accepted.required is False
    with database.connection() as connection:
        rows = connection.execute(
            """
            SELECT document_sha256, acceptance_method
            FROM auth_legal_acceptances
            WHERE user_id=? AND document_version=?
            """,
            (userId, currentDocument.version),
        ).fetchall()
        eventRows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM auth_legal_acceptance_events
                WHERE user_id=? AND document_version=?
                ORDER BY id
                """,
                (userId, currentDocument.version),
            ).fetchall()
        ]
    assert {row["document_sha256"] for row in rows} == {currentDocument.documentHash}
    assert {row["acceptance_method"] for row in rows} == {"REACCEPTANCE"}
    assert len(eventRows) == 6

    # 当前状态可以修复，但已产生的电子同意证据必须逐条原样保留。
    initialEventIds = {row["id"] for row in initialEventRows}
    preservedInitialEvents = [row for row in eventRows if row["id"] in initialEventIds]
    assert preservedInitialEvents == initialEventRows
    reacceptanceEvents = [row for row in eventRows if row["id"] not in initialEventIds]
    assert len(reacceptanceEvents) == 3
    assert {row["acceptance_method"] for row in reacceptanceEvents} == {"REACCEPTANCE"}
    assert {row["document_sha256"] for row in reacceptanceEvents} == {currentDocument.documentHash}
    assert {row["acceptance_state_id"] for row in reacceptanceEvents} == {
        row["acceptance_state_id"] for row in initialEventRows
    }


def test_challenge_is_one_time_bounded_and_expires(tmp_path: Path) -> None:
    _database, _repository, service, mailer, now = _authFixture(tmp_path)
    dispatch = asyncio.run(
        service.requestRegistrationCode(email="bounded@example.com", locale="en")
    )
    code = mailer.messages[-1].code

    for _ in range(5):
        with pytest.raises(ChallengeVerificationError):
            asyncio.run(
                service.register(
                    challengeId=dispatch.challengeId,
                    code="999999" if code != "999999" else "888888",
                    password=USER_PASSWORD,
                    **_legalArguments(),
                )
            )
    with pytest.raises(ChallengeVerificationError):
        asyncio.run(
            service.register(
                challengeId=dispatch.challengeId,
                code=code,
                password=USER_PASSWORD,
                **_legalArguments(),
            )
        )

    now[0] += timedelta(seconds=61)
    expiring = asyncio.run(
        service.requestRegistrationCode(email="expiring@example.com", locale="en")
    )
    expiringCode = mailer.messages[-1].code
    now[0] += timedelta(minutes=11)
    with pytest.raises(ChallengeVerificationError):
        asyncio.run(
            service.register(
                challengeId=expiring.challengeId,
                code=expiringCode,
                password=USER_PASSWORD,
                **_legalArguments(),
            )
        )


def test_admin_can_view_activity_and_disable_only_regular_users(tmp_path: Path) -> None:
    _database, repository, service, mailer, _now = _authFixture(tmp_path)
    admin, _created = repository.ensureAdmin(
        userId="usr-admin0000000000000000000000000000",
        email="admin@example.com",
        passwordHash=hashPassword("Administrator password!"),
    )
    userId = _register(service, mailer, "member@example.com")
    service.login(email="member@example.com", password=USER_PASSWORD)
    adminContext = AuthContext(
        userId=admin.id,
        authSessionId="auth-admin00000000000000000000000000",
        email=admin.email,
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
    )
    userContext = AuthContext(
        userId=userId,
        authSessionId="auth-user000000000000000000000000000",
        email="member@example.com",
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
    )

    with pytest.raises(AuthorizationError):
        service.listUsers(userContext)
    users = service.listUsers(adminContext)
    assert {item.email for item in users} == {"admin@example.com", "member@example.com"}
    assert any(item.action == "ACCOUNT_REGISTERED" for item in service.listActivity(adminContext))

    disabled = service.setUserStatus(
        adminContext,
        userId=userId,
        status=UserStatus.DISABLED,
    )
    assert disabled.status is UserStatus.DISABLED
    statusActivity = next(
        item
        for item in service.listActivity(adminContext)
        if item.action == "ACCOUNT_STATUS_CHANGED"
    )
    assert statusActivity.userId == admin.id
    assert statusActivity.metadata["targetUserId"] == userId
    with pytest.raises(AuthorizationError):
        service.setUserStatus(
            adminContext,
            userId=admin.id,
            status=UserStatus.DISABLED,
        )


def test_bootstrap_claims_legacy_rows_without_rewriting_session_id(tmp_path: Path) -> None:
    databasePath = tmp_path / "legacy.db"
    with sqlite3.connect(databasePath) as connection:
        connection.executescript(
            """
            CREATE TABLE event_pack_drafts (
                session_id TEXT NOT NULL,
                event_pack_id TEXT NOT NULL,
                claims_json TEXT NOT NULL,
                frozen INTEGER NOT NULL DEFAULT 0,
                frozen_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, event_pack_id)
            );
            INSERT INTO event_pack_drafts(
                session_id, event_pack_id, claims_json, frozen, updated_at
            ) VALUES
                ('legacy-session-one', 'same-pack', '[]', 0, '2026-07-20T00:00:00+00:00'),
                ('legacy-session-two', 'same-pack', '[]', 1, '2026-07-20T01:00:00+00:00');
            """
        )
    database = Database(databasePath)
    database.initialize()
    adminId, created, claimed = bootstrapAdmin(
        database=database,
        adminEmail="owner@example.com",
        password="Administrator password!",
    )

    assert created is True
    assert claimed["event_pack_drafts"] == 2
    with database.connection() as connection:
        rows = connection.execute(
            """
            SELECT session_id, owner_user_id FROM event_pack_drafts
            ORDER BY session_id
            """
        ).fetchall()
    assert [row["session_id"] for row in rows] == [
        "legacy-session-one",
        "legacy-session-two",
    ]
    assert {row["owner_user_id"] for row in rows} == {adminId}
    latest = database.getEventPackDraft(adminId, "same-pack")
    assert latest is not None and latest["frozen"] is True


def test_bootstrap_accepts_eight_character_initial_password(tmp_path: Path) -> None:
    database = Database(tmp_path / "bootstrap-password.db")
    database.initialize()

    adminId, created, _claimed = bootstrapAdmin(
        database=database,
        adminEmail="admin@example.com",
        password="Eight8!!",
    )

    repository = AuthRepository(database)
    stored = repository.getUserByEmail("admin@example.com")
    assert created is True
    assert stored is not None
    assert stored["id"] == adminId
    assert verifyPassword("Eight8!!", str(stored["password_hash"]))


def test_password_policy_rejects_seven_characters() -> None:
    with pytest.raises(PasswordPolicyError):
        hashPassword("Seven7!")


def test_bilingual_mail_templates_do_not_mix_languages() -> None:
    chinese = _message(
        sender="no-reply@example.com",
        recipient="user@example.com",
        code="123456",
        purpose=ChallengePurpose.RESET_PASSWORD,
        locale="zh-CN",
        expiresMinutes=10,
    )
    english = _message(
        sender="no-reply@example.com",
        recipient="user@example.com",
        code="654321",
        purpose=ChallengePurpose.REGISTER,
        locale="en",
        expiresMinutes=10,
    )

    assert "重置密码" in str(chinese["Subject"])
    assert "123456" in chinese.get_content()
    assert "Verification code" not in chinese.get_content()
    assert str(english["Subject"]) == "Your EventShock Lab verification code"
    assert "Verification code: 654321" in english.get_content()
    assert "验证码" not in english.get_content()


@pytest.mark.parametrize(
    "value",
    (
        "missing-at.example.com",
        "a@localhost",
        "a..b@example.com",
        "bad\nheader@example.com",
    ),
)
def test_email_normalization_rejects_invalid_or_header_injection(value: str) -> None:
    with pytest.raises(ValueError):
        normalizeEmail(value)
