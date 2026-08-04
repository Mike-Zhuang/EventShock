"""注册、登录、验证码、会话和管理员操作的认证服务。"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from backend.app.auth.mailer import VerificationMailer
from backend.app.auth.models import (
    ActivityView,
    AdminUserView,
    AssistancePreference,
    AuthContext,
    AuthLocale,
    ChallengeDispatch,
    ChallengePurpose,
    ExperienceLevel,
    FirstGoal,
    IssuedSession,
    LegalAcceptanceStatus,
    PublicUser,
    UserPreferences,
    UserRole,
    UserStatus,
    WorkspaceMode,
)
from backend.app.auth.passwords import hashPassword, verifyPassword
from backend.app.auth.repository import (
    AuthRepository,
    ChallengeVerificationError,
)
from backend.app.legal import validateCurrentAcceptance

EMAIL_LOCAL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")


class AuthenticationError(RuntimeError):
    pass


class CsrfValidationError(AuthenticationError):
    pass


class AuthorizationError(RuntimeError):
    pass


class AuthService:
    def __init__(
        self,
        *,
        repository: AuthRepository,
        mailer: VerificationMailer,
        authSecret: str,
        clock: Callable[[], datetime] | None = None,
        challengeLifetime: timedelta = timedelta(minutes=10),
        resendCooldown: timedelta = timedelta(seconds=60),
        sessionLifetime: timedelta = timedelta(days=7),
        maximumCodeAttempts: int = 5,
    ) -> None:
        secretBytes = authSecret.encode("utf-8")
        if len(secretBytes) < 32:
            raise ValueError("authSecret must contain at least 32 UTF-8 bytes")
        if not timedelta(minutes=2) <= challengeLifetime <= timedelta(minutes=30):
            raise ValueError("challenge lifetime must be between 2 and 30 minutes")
        if not timedelta(seconds=30) <= resendCooldown <= timedelta(minutes=10):
            raise ValueError("resend cooldown must be between 30 seconds and 10 minutes")
        if not timedelta(hours=1) <= sessionLifetime <= timedelta(days=30):
            raise ValueError("session lifetime must be between 1 hour and 30 days")
        if not 3 <= maximumCodeAttempts <= 10:
            raise ValueError("maximum code attempts must be between 3 and 10")
        self.repository = repository
        self.mailer = mailer
        self._authSecret = secretBytes
        self._clock = clock or (lambda: datetime.now(UTC))
        self.challengeLifetime = challengeLifetime
        self.resendCooldown = resendCooldown
        self.sessionLifetime = sessionLifetime
        self.maximumCodeAttempts = maximumCodeAttempts
        # 不存在的邮箱也执行同成本哈希，降低登录账号枚举的时序差异。
        self._dummyPasswordHash = hashPassword(secrets.token_urlsafe(24))

    def __repr__(self) -> str:
        return "AuthService(secret=<redacted>)"

    async def requestRegistrationCode(
        self,
        *,
        email: str,
        locale: AuthLocale,
    ) -> ChallengeDispatch:
        normalized = normalizeEmail(email)
        return await self._requestCode(
            email=normalized,
            purpose=ChallengePurpose.REGISTER,
            locale=locale,
        )

    async def register(
        self,
        *,
        challengeId: str,
        code: str,
        password: str,
        legalVersion: str,
        legalDocumentHash: str,
        legalLocale: AuthLocale,
        acceptedTerms: bool,
        acknowledgedPrivacy: bool,
        confirmedMinimumAge: bool,
        acknowledgedAiBoundary: bool,
    ) -> PublicUser:
        now = self._now()
        # 先验证条款版本和密码策略，避免输入错误消耗一次性验证码。
        document = validateCurrentAcceptance(
            version=legalVersion,
            documentHash=legalDocumentHash,
            locale=legalLocale,
            acceptedTerms=acceptedTerms and acknowledgedPrivacy,
            confirmedMinimumAge=confirmedMinimumAge,
            acknowledgedAiBoundary=acknowledgedAiBoundary,
        )
        passwordHash = hashPassword(password)
        challenge = self.repository.getChallenge(challengeId)
        if challenge is None or challenge.purpose is not ChallengePurpose.REGISTER:
            raise ChallengeVerificationError("verification code is invalid or expired")
        codeHash = self._codeHash(challenge.id, challenge.email, challenge.purpose, code)
        user = self.repository.consumeRegistrationChallengeAndCreateUser(
            challengeId=challenge.id,
            codeHash=codeHash,
            userId=f"usr-{uuid.uuid4().hex}",
            passwordHash=passwordHash,
            legalVersion=document.version,
            legalDocumentHash=document.documentHash,
            legalLocale=legalLocale,
            now=now,
        )
        self.repository.recordActivity(
            userId=user.id,
            action="ACCOUNT_REGISTERED",
            metadata={"legalVersion": document.version, "legalLocale": legalLocale},
        )
        return user

    async def registerWithLatestChallenge(
        self,
        *,
        email: str,
        code: str,
        password: str,
        legalVersion: str,
        legalDocumentHash: str,
        legalLocale: AuthLocale,
        acceptedTerms: bool,
        acknowledgedPrivacy: bool,
        confirmedMinimumAge: bool,
        acknowledgedAiBoundary: bool,
    ) -> PublicUser:
        normalized = normalizeEmail(email)
        challenge = self.repository.getLatestChallenge(
            email=normalized,
            purpose=ChallengePurpose.REGISTER,
        )
        if challenge is None:
            raise ChallengeVerificationError("verification code is invalid or expired")
        return await self.register(
            challengeId=challenge.id,
            code=code,
            password=password,
            legalVersion=legalVersion,
            legalDocumentHash=legalDocumentHash,
            legalLocale=legalLocale,
            acceptedTerms=acceptedTerms,
            acknowledgedPrivacy=acknowledgedPrivacy,
            confirmedMinimumAge=confirmedMinimumAge,
            acknowledgedAiBoundary=acknowledgedAiBoundary,
        )

    def legalAcceptanceStatus(self, userId: str) -> LegalAcceptanceStatus:
        return self.repository.getLegalAcceptanceStatus(userId)

    def acceptCurrentLegalDocuments(
        self,
        requester: AuthContext,
        *,
        version: str,
        documentHash: str,
        locale: AuthLocale,
        acceptedTerms: bool,
        acknowledgedPrivacy: bool,
        confirmedMinimumAge: bool,
        acknowledgedAiBoundary: bool,
    ) -> LegalAcceptanceStatus:
        document = validateCurrentAcceptance(
            version=version,
            documentHash=documentHash,
            locale=locale,
            acceptedTerms=acceptedTerms and acknowledgedPrivacy,
            confirmedMinimumAge=confirmedMinimumAge,
            acknowledgedAiBoundary=acknowledgedAiBoundary,
        )
        status = self.repository.acceptLegalDocuments(
            userId=requester.userId,
            version=document.version,
            documentHash=document.documentHash,
            locale=locale,
            authSessionId=requester.authSessionId,
        )
        self.repository.recordActivity(
            userId=requester.userId,
            action="LEGAL_TERMS_ACCEPTED",
            metadata={"version": document.version, "locale": locale},
        )
        return status

    def getUserPreferences(self, requester: AuthContext) -> UserPreferences:
        return self.repository.getUserPreferences(requester.userId)

    def saveUserPreferences(
        self,
        requester: AuthContext,
        *,
        experienceLevel: ExperienceLevel,
        workspaceMode: WorkspaceMode,
        assistancePreference: AssistancePreference,
        firstGoal: FirstGoal,
    ) -> UserPreferences:
        if self.repository.getLegalAcceptanceStatus(requester.userId).required:
            raise AuthorizationError("current legal terms must be accepted before onboarding")
        preferences = self.repository.saveUserPreferences(
            userId=requester.userId,
            experienceLevel=experienceLevel,
            workspaceMode=workspaceMode,
            assistancePreference=assistancePreference,
            firstGoal=firstGoal,
        )
        self.repository.recordActivity(
            userId=requester.userId,
            action="ONBOARDING_COMPLETED",
            metadata={
                "experienceLevel": experienceLevel.value,
                "workspaceMode": workspaceMode.value,
                "assistancePreference": assistancePreference.value,
                "firstGoal": firstGoal.value,
            },
        )
        return preferences

    def saveLlmPreference(
        self,
        requester: AuthContext,
        *,
        provider: str,
        model: str,
    ) -> UserPreferences:
        """记录模型选择但不记录凭据；目录校验由模型配置接口负责。"""

        if not 1 <= len(provider) <= 32 or not 3 <= len(model) <= 128:
            raise ValueError("model preference is invalid")
        self.repository.saveLlmPreference(
            userId=requester.userId,
            provider=provider,
            model=model,
        )
        return self.repository.getUserPreferences(requester.userId)

    async def requestPasswordResetCode(
        self,
        *,
        email: str,
        locale: AuthLocale,
    ) -> ChallengeDispatch:
        normalized = normalizeEmail(email)
        return await self._requestCode(
            email=normalized,
            purpose=ChallengePurpose.RESET_PASSWORD,
            locale=locale,
        )

    async def resetPassword(
        self,
        *,
        challengeId: str,
        code: str,
        newPassword: str,
    ) -> None:
        now = self._now()
        # 与注册路径一致，策略错误不能提前消费有效验证码。
        passwordHash = hashPassword(newPassword)
        challenge = self.repository.getChallenge(challengeId)
        if challenge is None or challenge.purpose is not ChallengePurpose.RESET_PASSWORD:
            raise ChallengeVerificationError("verification code is invalid or expired")
        codeHash = self._codeHash(challenge.id, challenge.email, challenge.purpose, code)
        verified = self.repository.consumeChallenge(
            challengeId=challenge.id,
            purpose=ChallengePurpose.RESET_PASSWORD,
            codeHash=codeHash,
            now=now,
        )
        userRow = self.repository.getUserByEmail(verified.email)
        if userRow is None:
            raise ChallengeVerificationError("verification code is invalid or expired")
        self.repository.updatePassword(str(userRow["id"]), passwordHash)
        self.repository.recordActivity(
            userId=str(userRow["id"]),
            action="PASSWORD_RESET",
        )

    async def resetPasswordWithLatestChallenge(
        self,
        *,
        email: str,
        code: str,
        newPassword: str,
    ) -> None:
        normalized = normalizeEmail(email)
        challenge = self.repository.getLatestChallenge(
            email=normalized,
            purpose=ChallengePurpose.RESET_PASSWORD,
        )
        if challenge is None:
            raise ChallengeVerificationError("verification code is invalid or expired")
        await self.resetPassword(
            challengeId=challenge.id,
            code=code,
            newPassword=newPassword,
        )

    def login(self, *, email: str, password: str) -> IssuedSession:
        normalized = normalizeEmail(email)
        userRow = self.repository.getUserByEmail(normalized)
        encodedHash = str(userRow["password_hash"]) if userRow else self._dummyPasswordHash
        validPassword = verifyPassword(password, encodedHash)
        if userRow is None or not validPassword or userRow["status"] != UserStatus.ACTIVE.value:
            if userRow is not None:
                self.repository.recordActivity(
                    userId=str(userRow["id"]),
                    action="LOGIN_ATTEMPT",
                    status="FAILED",
                )
            raise AuthenticationError("email or password is incorrect")

        userId = str(userRow["id"])
        token = secrets.token_urlsafe(32)
        # CSRF 值由 HttpOnly 会话 token 确定性派生；页面刷新后服务端可以恢复，
        # 浏览器仍无法仅凭可读 Cookie 反推出会话 token。
        csrfToken = self.csrfToken(token)
        now = self._now()
        expiresAt = now + self.sessionLifetime
        sessionId = f"auth-{uuid.uuid4().hex}"
        self.repository.createSession(
            sessionId=sessionId,
            userId=userId,
            tokenHash=_tokenHash(token),
            csrfHash=_tokenHash(csrfToken),
            expiresAt=expiresAt,
            now=now,
        )
        self.repository.markLogin(userId)
        self.repository.recordActivity(userId=userId, action="LOGIN_SUCCEEDED")
        user = self.repository.getUserById(userId)
        if user is None:
            raise RuntimeError("authenticated user disappeared")
        return IssuedSession(
            sessionId=sessionId,
            user=user,
            expiresAt=expiresAt,
            token=token,
            csrfToken=csrfToken,
        )

    def csrfToken(self, token: str) -> str:
        """为已认证 session endpoint 重建同一 CSRF token。"""

        if not token:
            raise AuthenticationError("authentication is required")
        return hmac.new(
            self._authSecret,
            f"csrf|{token}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def authenticate(
        self,
        *,
        token: str,
        csrfToken: str | None = None,
        requireCsrf: bool = False,
    ) -> AuthContext:
        if not token:
            raise AuthenticationError("authentication is required")
        now = self._now()
        session = self.repository.getActiveSession(_tokenHash(token), now)
        if session is None:
            raise AuthenticationError("authentication session is invalid or expired")
        if requireCsrf:
            if not csrfToken or not hmac.compare_digest(
                session.csrfHash,
                _tokenHash(csrfToken),
            ):
                raise CsrfValidationError("CSRF validation failed")
        self.repository.touchSession(session.context.authSessionId, now)
        return session.context

    def verifyCurrentPassword(self, requester: AuthContext, password: str) -> None:
        """敏感账号操作前重新验证当前密码，不创建新会话。"""

        userRow = self.repository.getUserAuthenticationRecord(requester.userId)
        encodedHash = (
            str(userRow["password_hash"]) if userRow is not None else self._dummyPasswordHash
        )
        if userRow is None or not verifyPassword(password, encodedHash):
            self.repository.recordActivity(
                userId=requester.userId if userRow is not None else None,
                action="SENSITIVE_ACCOUNT_REAUTH",
                status="FAILED",
            )
            raise AuthenticationError("current password is incorrect")
        self.repository.recordActivity(
            userId=requester.userId,
            action="SENSITIVE_ACCOUNT_REAUTH",
            status="SUCCEEDED",
        )

    def logout(self, *, token: str) -> str | None:
        if not token:
            return None
        userId = self.repository.revokeSessionByTokenHash(_tokenHash(token))
        if userId is not None:
            self.repository.recordActivity(userId=userId, action="LOGOUT")
        return userId

    def listUsers(
        self,
        requester: AuthContext,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AdminUserView]:
        self._requireAdmin(requester)
        return self.repository.listUsers(limit=limit, offset=offset)

    def userStatistics(self, requester: AuthContext) -> dict[str, int]:
        self._requireAdmin(requester)
        return self.repository.userStatistics()

    def listActivity(
        self,
        requester: AuthContext,
        *,
        userId: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ActivityView]:
        self._requireAdmin(requester)
        return self.repository.listActivity(userId=userId, limit=limit, offset=offset)

    def countActivity(self, requester: AuthContext, *, userId: str | None = None) -> int:
        self._requireAdmin(requester)
        return self.repository.countActivity(userId=userId)

    def setUserStatus(
        self,
        requester: AuthContext,
        *,
        userId: str,
        status: UserStatus,
    ) -> PublicUser:
        self._requireAdmin(requester)
        target = self.repository.getUserById(userId)
        if target is None:
            raise LookupError("user does not exist")
        if target.role is UserRole.ADMIN or target.id == requester.userId:
            raise AuthorizationError("administrator accounts cannot be changed here")
        updated = self.repository.setUserStatus(userId, status)
        self.repository.recordActivity(
            userId=requester.userId,
            action="ACCOUNT_STATUS_CHANGED",
            metadata={"targetUserId": userId, "status": status.value},
        )
        return updated

    async def _requestCode(
        self,
        *,
        email: str,
        purpose: ChallengePurpose,
        locale: AuthLocale,
    ) -> ChallengeDispatch:
        now = self._now()
        challengeId = f"challenge-{uuid.uuid4().hex}"
        code = f"{secrets.randbelow(1_000_000):06d}"
        expiresAt = now + self.challengeLifetime
        resendAfter = now + self.resendCooldown
        challenge = self.repository.createChallenge(
            challengeId=challengeId,
            email=email,
            purpose=purpose,
            codeHash=self._codeHash(challengeId, email, purpose, code),
            locale=locale,
            expiresAt=expiresAt,
            resendAfter=resendAfter,
            maximumAttempts=self.maximumCodeAttempts,
            now=now,
        )
        # 无论账号是否存在都走同一 SMTP 路径，避免响应时间和 503/202
        # 差异成为账号枚举旁路；验证码本身仍受后续账号状态约束。
        try:
            await self.mailer.sendVerificationCode(
                recipient=email,
                code=code,
                purpose=purpose,
                locale=locale,
                expiresMinutes=max(1, int(self.challengeLifetime.total_seconds() // 60)),
            )
        except Exception:
            self.repository.invalidateChallenge(challenge.id)
            raise
        return ChallengeDispatch(
            challengeId=challenge.id,
            expiresAt=challenge.expiresAt,
            resendAfter=challenge.resendAfter,
        )

    def _codeHash(
        self,
        challengeId: str,
        email: str,
        purpose: ChallengePurpose,
        code: str,
    ) -> str:
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            # 仍生成固定长度摘要，由统一错误路径处理，避免格式形成旁路。
            code = "invalid"
        material = "|".join((challengeId, purpose.value, email, code)).encode("utf-8")
        return hmac.new(self._authSecret, material, hashlib.sha256).hexdigest()

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    @staticmethod
    def _requireAdmin(context: AuthContext) -> None:
        if not context.isAdmin or context.status is not UserStatus.ACTIVE:
            raise AuthorizationError("administrator access is required")


def normalizeEmail(value: str) -> str:
    if not isinstance(value, str) or "\r" in value or "\n" in value:
        raise ValueError("invalid email address")
    candidate = value.strip()
    if not 3 <= len(candidate) <= 254 or candidate.count("@") != 1:
        raise ValueError("invalid email address")
    local, domain = candidate.rsplit("@", maxsplit=1)
    if (
        not 1 <= len(local) <= 64
        or not EMAIL_LOCAL_PATTERN.fullmatch(local)
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
    ):
        raise ValueError("invalid email address")
    try:
        asciiDomain = domain.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("invalid email address") from error
    labels = asciiDomain.split(".")
    if len(labels) < 2 or any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not re.fullmatch(r"[a-z0-9-]+", label)
        for label in labels
    ):
        raise ValueError("invalid email address")
    return f"{local.casefold()}@{asciiDomain}"


def _tokenHash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
