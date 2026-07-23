"""EventShock 账号、邮箱验证和会话认证。"""

from backend.app.auth.mailer import MailDeliveryError, SmtpVerificationMailer, VerificationMailer
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
from backend.app.auth.passwords import PasswordPolicyError, hashPassword, verifyPassword
from backend.app.auth.repository import (
    AuthRepository,
    ChallengeCooldownError,
    ChallengeVerificationError,
    DuplicateUserError,
)
from backend.app.auth.service import (
    AuthenticationError,
    AuthorizationError,
    AuthService,
    CsrfValidationError,
    normalizeEmail,
)

__all__ = [
    "ActivityView",
    "AdminUserView",
    "AssistancePreference",
    "AuthContext",
    "AuthLocale",
    "AuthRepository",
    "AuthService",
    "AuthenticationError",
    "AuthorizationError",
    "ChallengeCooldownError",
    "ChallengeDispatch",
    "ChallengePurpose",
    "ChallengeVerificationError",
    "CsrfValidationError",
    "DuplicateUserError",
    "ExperienceLevel",
    "FirstGoal",
    "IssuedSession",
    "LegalAcceptanceStatus",
    "MailDeliveryError",
    "PasswordPolicyError",
    "PublicUser",
    "SmtpVerificationMailer",
    "UserRole",
    "UserStatus",
    "UserPreferences",
    "VerificationMailer",
    "hashPassword",
    "normalizeEmail",
    "verifyPassword",
    "WorkspaceMode",
]
