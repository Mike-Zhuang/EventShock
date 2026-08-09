"""SQLite 认证仓储；令牌、验证码与密码均只保存不可逆摘要。"""

from __future__ import annotations

import hmac
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.auth.models import (
    ActiveSessionRecord,
    ActivityView,
    AdminUserView,
    AssistancePreference,
    AuthContext,
    AuthLocale,
    ChallengePurpose,
    ChallengeRecord,
    ExperienceLevel,
    FirstGoal,
    LegalAcceptanceStatus,
    PublicUser,
    SessionView,
    UserPreferences,
    UserRole,
    UserStatus,
    WorkspaceMode,
)
from backend.app.database import Database, utcNow
from backend.app.legal import CURRENT_TERMS_VERSION, currentDocumentHashes

CURRENT_ONBOARDING_VERSION = "2026-07-22-v1"
LEGAL_DOCUMENT_TYPES = (
    ("TERMS_OF_USE", "AGREED"),
    ("PRIVACY_NOTICE", "ACKNOWLEDGED"),
    ("RESEARCH_AI_RISK_NOTICE", "ACKNOWLEDGED"),
)


class DuplicateUserError(RuntimeError):
    pass


class ChallengeCooldownError(RuntimeError):
    def __init__(self, retryAfterSeconds: int) -> None:
        super().__init__("verification challenge cooldown is active")
        self.retryAfterSeconds = max(1, retryAfterSeconds)


class ChallengeVerificationError(RuntimeError):
    pass


class AuthRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def initialize(self) -> None:
        with self.database.writeLock, self.database.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    id TEXT PRIMARY KEY,
                    email_normalized TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('USER', 'ADMIN')),
                    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'DISABLED')),
                    email_verified_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT,
                    password_changed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    csrf_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_active
                ON auth_sessions(user_id, revoked_at, expires_at);
                CREATE TABLE IF NOT EXISTS auth_challenges (
                    id TEXT PRIMARY KEY,
                    email_normalized TEXT NOT NULL COLLATE NOCASE,
                    purpose TEXT NOT NULL CHECK(purpose IN ('REGISTER', 'RESET_PASSWORD')),
                    code_hash TEXT NOT NULL,
                    locale TEXT NOT NULL CHECK(locale IN ('en', 'zh-CN')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    maximum_attempts INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    resend_after TEXT NOT NULL,
                    consumed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_challenge_lookup
                ON auth_challenges(email_normalized, purpose, created_at DESC);
                CREATE TABLE IF NOT EXISTS auth_activity_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT REFERENCES auth_users(id) ON DELETE SET NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_activity_user_created
                ON auth_activity_events(user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS auth_legal_acceptances (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE RESTRICT,
                    document_type TEXT NOT NULL CHECK(
                        document_type IN (
                            'TERMS_OF_USE',
                            'PRIVACY_NOTICE',
                            'RESEARCH_AI_RISK_NOTICE'
                        )
                    ),
                    document_version TEXT NOT NULL,
                    document_sha256 TEXT NOT NULL CHECK(length(document_sha256)=64),
                    action TEXT NOT NULL CHECK(action IN ('AGREED', 'ACKNOWLEDGED')),
                    locale TEXT NOT NULL CHECK(locale IN ('en', 'zh-CN')),
                    acceptance_method TEXT NOT NULL CHECK(
                        acceptance_method IN ('REGISTRATION', 'POST_LOGIN_GATE', 'REACCEPTANCE')
                    ),
                    auth_session_id TEXT REFERENCES auth_sessions(id) ON DELETE SET NULL,
                    accepted_at TEXT NOT NULL,
                    UNIQUE(user_id, document_type, document_version)
                );
                CREATE INDEX IF NOT EXISTS idx_auth_legal_user_version
                ON auth_legal_acceptances(user_id, document_version);
                CREATE TABLE IF NOT EXISTS auth_legal_acceptance_events (
                    id TEXT PRIMARY KEY,
                    acceptance_state_id TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE RESTRICT,
                    document_type TEXT NOT NULL CHECK(
                        document_type IN (
                            'TERMS_OF_USE',
                            'PRIVACY_NOTICE',
                            'RESEARCH_AI_RISK_NOTICE'
                        )
                    ),
                    document_version TEXT NOT NULL,
                    document_sha256 TEXT NOT NULL CHECK(length(document_sha256)=64),
                    action TEXT NOT NULL CHECK(action IN ('AGREED', 'ACKNOWLEDGED')),
                    locale TEXT NOT NULL CHECK(locale IN ('en', 'zh-CN')),
                    acceptance_method TEXT NOT NULL CHECK(
                        acceptance_method IN ('REGISTRATION', 'POST_LOGIN_GATE', 'REACCEPTANCE')
                    ),
                    auth_session_id TEXT REFERENCES auth_sessions(id) ON DELETE SET NULL,
                    accepted_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_legal_event_user_time
                ON auth_legal_acceptance_events(user_id, accepted_at DESC);
                CREATE TABLE IF NOT EXISTS auth_user_preferences (
                    user_id TEXT PRIMARY KEY REFERENCES auth_users(id) ON DELETE CASCADE,
                    experience_level TEXT NOT NULL CHECK(
                        experience_level IN ('NEW', 'INTERMEDIATE', 'ADVANCED')
                    ),
                    workspace_mode TEXT NOT NULL CHECK(workspace_mode IN ('GUIDED', 'EXPERT')),
                    assistance_preference TEXT NOT NULL CHECK(
                        assistance_preference IN (
                            'STEP_BY_STEP',
                            'PROPOSE_AND_ADJUST',
                            'DIRECT_CONTROL'
                        )
                    ),
                    first_goal TEXT NOT NULL CHECK(
                        first_goal IN (
                            'TRY_DEMO',
                            'RESEARCH_NEW_EVENT',
                            'DESIGN_FULL_EXPERIMENT'
                        )
                    ),
                    onboarding_version TEXT NOT NULL,
                    onboarding_completed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO auth_legal_acceptance_events(
                    id, acceptance_state_id, user_id, document_type, document_version,
                    document_sha256, action, locale, acceptance_method,
                    auth_session_id, accepted_at
                )
                SELECT
                    'legacy-' || id, id, user_id, document_type, document_version,
                    document_sha256, action, locale, acceptance_method,
                    auth_session_id, accepted_at
                FROM auth_legal_acceptances;
                """
            )
            preferenceColumns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(auth_user_preferences)").fetchall()
            }
            # 供应商和模型只是普通偏好，不含 API Key。使用增量列迁移，避免
            # 破坏已经完成 onboarding 的账号及其首页模式选择。
            if "preferred_llm_provider" not in preferenceColumns:
                connection.execute(
                    "ALTER TABLE auth_user_preferences ADD COLUMN preferred_llm_provider TEXT"
                )
            if "preferred_llm_model" not in preferenceColumns:
                connection.execute(
                    "ALTER TABLE auth_user_preferences ADD COLUMN preferred_llm_model TEXT"
                )
        self.purgeExpired()

    def createUser(
        self,
        *,
        userId: str,
        email: str,
        passwordHash: str,
        role: UserRole = UserRole.USER,
    ) -> PublicUser:
        now = utcNow()
        try:
            with self.database.writeLock, self.database.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO auth_users(
                        id, email_normalized, password_hash, role, status,
                        email_verified_at, created_at, updated_at, password_changed_at
                    ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
                    """,
                    (userId, email, passwordHash, role.value, now, now, now, now),
                )
        except sqlite3.IntegrityError as error:
            raise DuplicateUserError("an account already exists for this email") from error
        user = self.getUserById(userId)
        if user is None:
            raise RuntimeError("user could not be persisted")
        return user

    def consumeRegistrationChallengeAndCreateUser(
        self,
        *,
        challengeId: str,
        codeHash: str,
        userId: str,
        passwordHash: str,
        legalVersion: str,
        legalDocumentHash: str,
        legalLocale: AuthLocale,
        now: datetime,
    ) -> PublicUser:
        """原子完成验证码消费、账户创建和初始 clickwrap 记录。

        任何持久化步骤失败都会回滚，避免出现验证码已消费但账号或法律记录缺失。
        错误验证码的失败次数仍需单独提交，因此在事务退出后再抛出统一异常。
        """

        codeMatched = False
        try:
            with self.database.writeLock, self.database.connection() as connection:
                row = connection.execute(
                    "SELECT * FROM auth_challenges WHERE id=?",
                    (challengeId,),
                ).fetchone()
                if row is None or row["purpose"] != ChallengePurpose.REGISTER.value:
                    raise ChallengeVerificationError("verification code is invalid or expired")
                challenge = _challenge(row)
                if (
                    challenge.consumedAt is not None
                    or challenge.expiresAt <= now
                    or challenge.attemptCount >= challenge.maximumAttempts
                ):
                    raise ChallengeVerificationError("verification code is invalid or expired")
                if not hmac.compare_digest(challenge.codeHash, codeHash):
                    connection.execute(
                        "UPDATE auth_challenges SET attempt_count=attempt_count+1 WHERE id=?",
                        (challengeId,),
                    )
                else:
                    codeMatched = True
                    timestamp = now.isoformat()
                    connection.execute(
                        """
                        INSERT INTO auth_users(
                            id, email_normalized, password_hash, role, status,
                            email_verified_at, created_at, updated_at, password_changed_at
                        ) VALUES (?, ?, ?, 'USER', 'ACTIVE', ?, ?, ?, ?)
                        """,
                        (
                            userId,
                            challenge.email,
                            passwordHash,
                            timestamp,
                            timestamp,
                            timestamp,
                            timestamp,
                        ),
                    )
                    self._insertLegalAcceptances(
                        connection,
                        userId=userId,
                        version=legalVersion,
                        documentHash=legalDocumentHash,
                        locale=legalLocale,
                        method="REGISTRATION",
                        authSessionId=None,
                        acceptedAt=now,
                    )
                    connection.execute(
                        """
                        UPDATE auth_challenges
                        SET consumed_at=?
                        WHERE id=? AND consumed_at IS NULL
                        """,
                        (timestamp, challengeId),
                    )
        except sqlite3.IntegrityError as error:
            if "auth_users.email_normalized" in str(error):
                raise DuplicateUserError("an account already exists for this email") from error
            raise
        if not codeMatched:
            raise ChallengeVerificationError("verification code is invalid or expired")
        user = self.getUserById(userId)
        if user is None:
            raise RuntimeError("user and legal acceptance could not be persisted")
        return user

    def acceptLegalDocuments(
        self,
        *,
        userId: str,
        version: str,
        documentHash: str,
        locale: AuthLocale,
        authSessionId: str,
    ) -> LegalAcceptanceStatus:
        now = datetime.now(UTC)
        method = "REACCEPTANCE" if self.hasAnyLegalAcceptance(userId) else "POST_LOGIN_GATE"
        with self.database.writeLock, self.database.connection() as connection:
            self._insertLegalAcceptances(
                connection,
                userId=userId,
                version=version,
                documentHash=documentHash,
                locale=locale,
                method=method,
                authSessionId=authSessionId,
                acceptedAt=now,
            )
        return self.getLegalAcceptanceStatus(userId)

    def hasAnyLegalAcceptance(self, userId: str) -> bool:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM auth_legal_acceptances WHERE user_id=? LIMIT 1",
                (userId,),
            ).fetchone()
        return row is not None

    def hasCurrentLegalAcceptance(self, userId: str) -> bool:
        return not self.getLegalAcceptanceStatus(userId).required

    def getLegalAcceptanceStatus(self, userId: str) -> LegalAcceptanceStatus:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT document_type, accepted_at, locale, document_sha256
                FROM auth_legal_acceptances
                WHERE user_id=? AND document_version=?
                """,
                (userId, CURRENT_TERMS_VERSION),
            ).fetchall()
        currentHashes = currentDocumentHashes()
        validRows = [
            row
            for row in rows
            if row["locale"] in currentHashes
            and hmac.compare_digest(
                str(row["document_sha256"]),
                currentHashes[row["locale"]],
            )
        ]
        acceptedTypes = {str(row["document_type"]) for row in validRows}
        requiredTypes = {item[0] for item in LEGAL_DOCUMENT_TYPES}
        latest = max((_datetime(row["accepted_at"]) for row in validRows), default=None)
        return LegalAcceptanceStatus(
            required=acceptedTypes != requiredTypes,
            version=CURRENT_TERMS_VERSION,
            acceptedAt=latest if acceptedTypes == requiredTypes else None,
        )

    def getUserPreferences(self, userId: str) -> UserPreferences:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM auth_user_preferences WHERE user_id=?",
                (userId,),
            ).fetchone()
        if row is None:
            return UserPreferences(onboardingRequired=True)
        preferredFields = {
            "preferredLlmProvider": row["preferred_llm_provider"],
            "preferredLlmModel": row["preferred_llm_model"],
        }
        if row["onboarding_version"] != CURRENT_ONBOARDING_VERSION:
            return UserPreferences(onboardingRequired=True, **preferredFields)
        return UserPreferences(
            onboardingRequired=False,
            experienceLevel=ExperienceLevel(row["experience_level"]),
            workspaceMode=WorkspaceMode(row["workspace_mode"]),
            assistancePreference=AssistancePreference(row["assistance_preference"]),
            firstGoal=FirstGoal(row["first_goal"]),
            onboardingVersion=row["onboarding_version"],
            onboardingCompletedAt=_datetime(row["onboarding_completed_at"]),
            updatedAt=_datetime(row["updated_at"]),
            **preferredFields,
        )

    def saveUserPreferences(
        self,
        *,
        userId: str,
        experienceLevel: ExperienceLevel,
        workspaceMode: WorkspaceMode,
        assistancePreference: AssistancePreference,
        firstGoal: FirstGoal,
    ) -> UserPreferences:
        now = utcNow()
        with self.database.writeLock, self.database.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO auth_user_preferences(
                    user_id, experience_level, workspace_mode, assistance_preference,
                    first_goal, onboarding_version, onboarding_completed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    experience_level=excluded.experience_level,
                    workspace_mode=excluded.workspace_mode,
                    assistance_preference=excluded.assistance_preference,
                    first_goal=excluded.first_goal,
                    onboarding_version=excluded.onboarding_version,
                    onboarding_completed_at=excluded.onboarding_completed_at,
                    updated_at=excluded.updated_at
                """,
                (
                    userId,
                    experienceLevel.value,
                    workspaceMode.value,
                    assistancePreference.value,
                    firstGoal.value,
                    CURRENT_ONBOARDING_VERSION,
                    now,
                    now,
                ),
            )
            if cursor.rowcount < 1:
                raise RuntimeError("user preferences were not persisted")
        return self.getUserPreferences(userId)

    def saveLlmPreference(
        self,
        *,
        userId: str,
        provider: str,
        model: str,
    ) -> bool:
        """保存非秘密模型偏好；绝不在此表写入或派生 API Key。"""

        now = utcNow()
        with self.database.writeLock, self.database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE auth_user_preferences
                SET preferred_llm_provider=?, preferred_llm_model=?, updated_at=?
                WHERE user_id=?
                """,
                (provider, model, now, userId),
            )
        return cursor.rowcount == 1

    @staticmethod
    def _insertLegalAcceptances(
        connection: sqlite3.Connection,
        *,
        userId: str,
        version: str,
        documentHash: str,
        locale: AuthLocale,
        method: str,
        authSessionId: str | None,
        acceptedAt: datetime,
    ) -> None:
        for documentType, action in LEGAL_DOCUMENT_TYPES:
            acceptanceStateId = f"legal-{documentType.lower()}-{userId}-{version}"
            # 当前状态表用于快速门禁；事件表永久追加每次明示同意，确保同版本
            # 文档摘要修复或重新接受不会销毁先前的电子签署证据。
            connection.execute(
                """
                INSERT INTO auth_legal_acceptance_events(
                    id, acceptance_state_id, user_id, document_type, document_version,
                    document_sha256, action, locale, acceptance_method,
                    auth_session_id, accepted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"legal-event-{uuid.uuid4().hex}",
                    acceptanceStateId,
                    userId,
                    documentType,
                    version,
                    documentHash,
                    action,
                    locale,
                    method,
                    authSessionId,
                    acceptedAt.isoformat(),
                ),
            )
            # 版本号原则上必须随正文变化而递增；这里仍允许用户对同版本的新摘要重新
            # 明示同意，避免一次错误发布把账号永久锁在法律门禁之外。每次重新同意还会
            # 由 AuthService 追加独立活动事件，因此该恢复路径不会静默发生。
            connection.execute(
                """
                INSERT INTO auth_legal_acceptances(
                    id, user_id, document_type, document_version, document_sha256,
                    action, locale, acceptance_method, auth_session_id, accepted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, document_type, document_version) DO UPDATE SET
                    document_sha256=excluded.document_sha256,
                    action=excluded.action,
                    locale=excluded.locale,
                    acceptance_method=excluded.acceptance_method,
                    auth_session_id=excluded.auth_session_id,
                    accepted_at=excluded.accepted_at
                """,
                (
                    acceptanceStateId,
                    userId,
                    documentType,
                    version,
                    documentHash,
                    action,
                    locale,
                    method,
                    authSessionId,
                    acceptedAt.isoformat(),
                ),
            )

    def getUserByEmail(self, email: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM auth_users WHERE email_normalized=? COLLATE NOCASE",
                (email,),
            ).fetchone()
        return dict(row) if row is not None else None

    def getUserAuthenticationRecord(self, userId: str) -> dict[str, Any] | None:
        """仅供服务端重新认证使用；调用方不得序列化或记录返回值。"""

        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT id, password_hash, status FROM auth_users WHERE id=?",
                (userId,),
            ).fetchone()
        return dict(row) if row is not None else None

    def getUserById(self, userId: str) -> PublicUser | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM auth_users WHERE id=?", (userId,)).fetchone()
        return _publicUser(row) if row is not None else None

    def updatePassword(self, userId: str, passwordHash: str) -> None:
        now = utcNow()
        with self.database.writeLock, self.database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE auth_users
                SET password_hash=?, password_changed_at=?, updated_at=?
                WHERE id=?
                """,
                (passwordHash, now, now, userId),
            )
            if cursor.rowcount != 1:
                raise LookupError("user does not exist")
            connection.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, userId),
            )

    def markLogin(self, userId: str) -> None:
        now = utcNow()
        with self.database.writeLock, self.database.connection() as connection:
            connection.execute(
                "UPDATE auth_users SET last_login_at=?, updated_at=? WHERE id=?",
                (now, now, userId),
            )

    def ensureAdmin(
        self,
        *,
        userId: str,
        email: str,
        passwordHash: str,
    ) -> tuple[PublicUser, bool]:
        existing = self.getUserByEmail(email)
        if existing is not None:
            if existing["role"] != UserRole.ADMIN.value:
                raise DuplicateUserError("the configured administrator email belongs to a user")
            user = self.getUserById(str(existing["id"]))
            if user is None:
                raise RuntimeError("administrator record is inconsistent")
            return user, False
        return (
            self.createUser(
                userId=userId,
                email=email,
                passwordHash=passwordHash,
                role=UserRole.ADMIN,
            ),
            True,
        )

    def createChallenge(
        self,
        *,
        challengeId: str,
        email: str,
        purpose: ChallengePurpose,
        codeHash: str,
        locale: AuthLocale,
        expiresAt: datetime,
        resendAfter: datetime,
        maximumAttempts: int,
        now: datetime,
    ) -> ChallengeRecord:
        with self.database.writeLock, self.database.connection() as connection:
            latest = connection.execute(
                """
                SELECT resend_after FROM auth_challenges
                WHERE email_normalized=? AND purpose=? AND consumed_at IS NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (email, purpose.value),
            ).fetchone()
            if latest is not None:
                availableAt = _datetime(latest["resend_after"])
                if availableAt > now:
                    raise ChallengeCooldownError(int((availableAt - now).total_seconds()) + 1)
            connection.execute(
                """
                UPDATE auth_challenges SET consumed_at=?
                WHERE email_normalized=? AND purpose=? AND consumed_at IS NULL
                """,
                (now.isoformat(), email, purpose.value),
            )
            connection.execute(
                """
                INSERT INTO auth_challenges(
                    id, email_normalized, purpose, code_hash, locale,
                    maximum_attempts, expires_at, resend_after, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    challengeId,
                    email,
                    purpose.value,
                    codeHash,
                    locale,
                    maximumAttempts,
                    expiresAt.isoformat(),
                    resendAfter.isoformat(),
                    now.isoformat(),
                ),
            )
        challenge = self.getChallenge(challengeId)
        if challenge is None:
            raise RuntimeError("challenge could not be persisted")
        return challenge

    def getChallenge(self, challengeId: str) -> ChallengeRecord | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM auth_challenges WHERE id=?", (challengeId,)
            ).fetchone()
        return _challenge(row) if row is not None else None

    def countRecentChallenges(
        self,
        *,
        email: str,
        purpose: ChallengePurpose,
        since: datetime,
    ) -> int:
        """按邮箱和用途统计发送意图，避免轮换 IP 绕过邮件配额。"""

        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total FROM auth_challenges
                WHERE email_normalized=? AND purpose=? AND created_at>=?
                """,
                (email, purpose.value, since.isoformat()),
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def getLatestChallenge(
        self,
        *,
        email: str,
        purpose: ChallengePurpose,
    ) -> ChallengeRecord | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM auth_challenges
                WHERE email_normalized=? AND purpose=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (email, purpose.value),
            ).fetchone()
        return _challenge(row) if row is not None else None

    def consumeChallenge(
        self,
        *,
        challengeId: str,
        purpose: ChallengePurpose,
        codeHash: str,
        now: datetime,
    ) -> ChallengeRecord:
        codeMatched = False
        with self.database.writeLock, self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM auth_challenges WHERE id=?", (challengeId,)
            ).fetchone()
            if row is None or row["purpose"] != purpose.value:
                raise ChallengeVerificationError("verification code is invalid")
            challenge = _challenge(row)
            if (
                challenge.consumedAt is not None
                or challenge.expiresAt <= now
                or challenge.attemptCount >= challenge.maximumAttempts
            ):
                raise ChallengeVerificationError("verification code is invalid or expired")
            if not hmac.compare_digest(challenge.codeHash, codeHash):
                connection.execute(
                    "UPDATE auth_challenges SET attempt_count=attempt_count+1 WHERE id=?",
                    (challengeId,),
                )
            else:
                connection.execute(
                    "UPDATE auth_challenges SET consumed_at=? WHERE id=? AND consumed_at IS NULL",
                    (now.isoformat(), challengeId),
                )
                codeMatched = True
        # 失败计数必须先提交；如果在 connection 上下文内抛出，事务会回滚，
        # 攻击者便可无限尝试同一个六位验证码。
        if not codeMatched:
            raise ChallengeVerificationError("verification code is invalid or expired")
        return challenge

    def invalidateChallenge(self, challengeId: str) -> None:
        with self.database.writeLock, self.database.connection() as connection:
            connection.execute(
                "UPDATE auth_challenges SET consumed_at=? WHERE id=? AND consumed_at IS NULL",
                (utcNow(), challengeId),
            )

    def createSession(
        self,
        *,
        sessionId: str,
        userId: str,
        tokenHash: str,
        csrfHash: str,
        expiresAt: datetime,
        now: datetime,
    ) -> None:
        with self.database.writeLock, self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO auth_sessions(
                    id, user_id, token_hash, csrf_hash, created_at, last_seen_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sessionId,
                    userId,
                    tokenHash,
                    csrfHash,
                    now.isoformat(),
                    now.isoformat(),
                    expiresAt.isoformat(),
                ),
            )

    def getActiveSession(
        self,
        tokenHash: str,
        now: datetime,
        idleCutoff: datetime,
    ) -> ActiveSessionRecord | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT s.id AS session_id, s.csrf_hash, s.expires_at,
                       u.id AS user_id, u.email_normalized, u.role, u.status
                FROM auth_sessions s
                JOIN auth_users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>?
                  AND s.last_seen_at>?
                  AND u.status='ACTIVE'
                """,
                (tokenHash, now.isoformat(), idleCutoff.isoformat()),
            ).fetchone()
        if row is None:
            return None
        return ActiveSessionRecord(
            context=AuthContext(
                userId=row["user_id"],
                authSessionId=row["session_id"],
                email=row["email_normalized"],
                role=UserRole(row["role"]),
                status=UserStatus(row["status"]),
            ),
            csrfHash=row["csrf_hash"],
            expiresAt=_datetime(row["expires_at"]),
        )

    def touchSession(self, sessionId: str, now: datetime) -> None:
        threshold = (now - timedelta(minutes=5)).isoformat()
        with self.database.writeLock, self.database.connection() as connection:
            connection.execute(
                """
                UPDATE auth_sessions SET last_seen_at=?
                WHERE id=? AND last_seen_at<? AND revoked_at IS NULL
                """,
                (now.isoformat(), sessionId, threshold),
            )

    def revokeSessionByTokenHash(self, tokenHash: str) -> str | None:
        now = utcNow()
        with self.database.writeLock, self.database.connection() as connection:
            row = connection.execute(
                "SELECT id, user_id FROM auth_sessions WHERE token_hash=? AND revoked_at IS NULL",
                (tokenHash,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE id=?",
                (now, row["id"]),
            )
            return str(row["user_id"])

    def revokeAllUserSessions(self, userId: str) -> None:
        with self.database.writeLock, self.database.connection() as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (utcNow(), userId),
            )

    def listActiveSessions(
        self,
        *,
        userId: str,
        currentSessionId: str,
        now: datetime,
        idleCutoff: datetime,
    ) -> list[SessionView]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, last_seen_at, expires_at
                FROM auth_sessions
                WHERE user_id=? AND revoked_at IS NULL AND expires_at>? AND last_seen_at>?
                ORDER BY last_seen_at DESC
                """,
                (userId, now.isoformat(), idleCutoff.isoformat()),
            ).fetchall()
        return [
            SessionView(
                id=str(row["id"]),
                current=str(row["id"]) == currentSessionId,
                createdAt=_datetime(row["created_at"]),
                lastSeenAt=_datetime(row["last_seen_at"]),
                expiresAt=_datetime(row["expires_at"]),
            )
            for row in rows
        ]

    def revokeUserSession(self, *, userId: str, sessionId: str) -> bool:
        with self.database.writeLock, self.database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE auth_sessions SET revoked_at=?
                WHERE id=? AND user_id=? AND revoked_at IS NULL
                """,
                (utcNow(), sessionId, userId),
            )
        return cursor.rowcount == 1

    def setUserStatus(self, userId: str, status: UserStatus) -> PublicUser:
        now = utcNow()
        with self.database.writeLock, self.database.connection() as connection:
            cursor = connection.execute(
                "UPDATE auth_users SET status=?, updated_at=? WHERE id=?",
                (status.value, now, userId),
            )
            if cursor.rowcount != 1:
                raise LookupError("user does not exist")
            if status is UserStatus.DISABLED:
                connection.execute(
                    "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                    (now, userId),
                )
        user = self.getUserById(userId)
        if user is None:
            raise RuntimeError("user status update was not persisted")
        return user

    def recordActivity(
        self,
        *,
        userId: str | None,
        action: str,
        status: str = "SUCCESS",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        safeMetadata = metadata or {}
        with self.database.writeLock, self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO auth_activity_events(
                    user_id, action, status, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    userId,
                    action[:80],
                    status[:32],
                    json.dumps(safeMetadata, ensure_ascii=False, separators=(",", ":")),
                    utcNow(),
                ),
            )

    def listUsers(self, *, limit: int = 100, offset: int = 0) -> list[AdminUserView]:
        safeLimit = max(1, min(limit, 500))
        safeOffset = max(0, offset)
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT u.*,
                       (SELECT COUNT(*) FROM experiments e
                        WHERE e.owner_user_id=u.id) AS experiment_count,
                       ((SELECT COUNT(*) FROM auth_activity_events a
                         WHERE a.user_id=u.id) +
                        (SELECT COUNT(*) FROM audit_events b
                         WHERE b.owner_user_id=u.id)) AS activity_count,
                       MAX(
                         COALESCE((SELECT MAX(a.created_at) FROM auth_activity_events a
                                   WHERE a.user_id=u.id), ''),
                         COALESCE((SELECT MAX(b.created_at) FROM audit_events b
                                   WHERE b.owner_user_id=u.id), '')
                       ) AS last_activity_at
                FROM auth_users u
                ORDER BY u.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (safeLimit, safeOffset),
            ).fetchall()
        return [_adminUser(row) for row in rows]

    def userStatistics(self) -> dict[str, int]:
        activeCutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total_users,
                       COUNT(*) AS verified_users,
                       SUM(CASE WHEN last_login_at>=? THEN 1 ELSE 0 END) AS active_users
                FROM auth_users
                """,
                (activeCutoff,),
            ).fetchone()
            authCount = int(
                connection.execute("SELECT COUNT(*) FROM auth_activity_events").fetchone()[0]
            )
            auditCount = int(connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
        return {
            "totalUsers": int(row["total_users"]),
            "verifiedUsers": int(row["verified_users"]),
            "activeUsersLastSevenDays": int(row["active_users"] or 0),
            "totalActivities": authCount + auditCount,
        }

    def listActivity(
        self,
        *,
        userId: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ActivityView]:
        safeLimit = max(1, min(limit, 500))
        safeOffset = max(0, offset)
        ownerFilter = "WHERE user_id=?" if userId is not None else ""
        parameters: tuple[Any, ...] = (
            (userId, safeLimit, safeOffset) if userId is not None else (safeLimit, safeOffset)
        )
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                WITH combined AS (
                    SELECT 'auth-' || id AS activity_id, user_id, action, status,
                           NULL AS entity_type, NULL AS entity_id,
                           metadata_json, created_at
                    FROM auth_activity_events
                    UNION ALL
                    SELECT 'audit-' || id AS activity_id, owner_user_id AS user_id,
                           action, 'SUCCESS' AS status, entity_type, entity_id,
                           '{{}}' AS metadata_json, created_at
                    FROM audit_events
                    WHERE owner_user_id IS NOT NULL
                )
                SELECT combined.*, u.email_normalized AS user_email
                FROM combined
                LEFT JOIN auth_users u ON u.id=combined.user_id
                {ownerFilter}
                ORDER BY created_at DESC LIMIT ? OFFSET ?
                """,  # noqa: S608 -- 条件片段不是用户输入。
                parameters,
            ).fetchall()
        return [
            ActivityView(
                id=row["activity_id"],
                userId=row["user_id"],
                userEmail=row["user_email"],
                action=row["action"],
                status=row["status"],
                entityType=row["entity_type"],
                entityId=row["entity_id"],
                metadata=json.loads(row["metadata_json"]),
                createdAt=_datetime(row["created_at"]),
            )
            for row in rows
        ]

    def countActivity(self, *, userId: str | None = None) -> int:
        with self.database.connection() as connection:
            if userId is None:
                authCount = int(
                    connection.execute("SELECT COUNT(*) FROM auth_activity_events").fetchone()[0]
                )
                auditCount = int(
                    connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
                )
            else:
                authCount = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM auth_activity_events WHERE user_id=?",
                        (userId,),
                    ).fetchone()[0]
                )
                auditCount = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM audit_events WHERE owner_user_id=?",
                        (userId,),
                    ).fetchone()[0]
                )
        return authCount + auditCount

    def purgeExpired(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        challengeCutoff = (current - timedelta(days=1)).isoformat()
        sessionCutoff = (current - timedelta(days=30)).isoformat()
        with self.database.writeLock, self.database.connection() as connection:
            connection.execute(
                "DELETE FROM auth_challenges WHERE expires_at<? OR consumed_at<?",
                (challengeCutoff, challengeCutoff),
            )
            connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at<? OR revoked_at<?",
                (sessionCutoff, sessionCutoff),
            )


def _publicUser(row: sqlite3.Row) -> PublicUser:
    return PublicUser(
        id=row["id"],
        email=row["email_normalized"],
        role=UserRole(row["role"]),
        status=UserStatus(row["status"]),
        emailVerifiedAt=_datetime(row["email_verified_at"]),
        createdAt=_datetime(row["created_at"]),
        lastLoginAt=_datetime(row["last_login_at"]) if row["last_login_at"] else None,
    )


def _adminUser(row: sqlite3.Row) -> AdminUserView:
    public = _publicUser(row)
    return AdminUserView(
        **public.model_dump(),
        experimentCount=int(row["experiment_count"]),
        activityCount=int(row["activity_count"]),
        lastActivityAt=(_datetime(row["last_activity_at"]) if row["last_activity_at"] else None),
    )


def _challenge(row: sqlite3.Row) -> ChallengeRecord:
    return ChallengeRecord(
        id=row["id"],
        email=row["email_normalized"],
        purpose=ChallengePurpose(row["purpose"]),
        codeHash=row["code_hash"],
        locale=row["locale"],
        attemptCount=int(row["attempt_count"]),
        maximumAttempts=int(row["maximum_attempts"]),
        expiresAt=_datetime(row["expires_at"]),
        resendAfter=_datetime(row["resend_after"]),
        consumedAt=_datetime(row["consumed_at"]) if row["consumed_at"] else None,
        createdAt=_datetime(row["created_at"]),
    )


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
