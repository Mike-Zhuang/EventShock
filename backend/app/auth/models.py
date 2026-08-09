"""认证领域模型；公开视图与内部秘密载体严格分离。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AuthLocale = Literal["en", "zh-CN"]


class UserRole(StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ChallengePurpose(StrEnum):
    REGISTER = "REGISTER"
    RESET_PASSWORD = "RESET_PASSWORD"


class ExperienceLevel(StrEnum):
    NEW = "NEW"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class WorkspaceMode(StrEnum):
    GUIDED = "GUIDED"
    EXPERT = "EXPERT"


class AssistancePreference(StrEnum):
    STEP_BY_STEP = "STEP_BY_STEP"
    PROPOSE_AND_ADJUST = "PROPOSE_AND_ADJUST"
    DIRECT_CONTROL = "DIRECT_CONTROL"


class FirstGoal(StrEnum):
    TRY_DEMO = "TRY_DEMO"
    RESEARCH_NEW_EVENT = "RESEARCH_NEW_EVENT"
    DESIGN_FULL_EXPERIMENT = "DESIGN_FULL_EXPERIMENT"


class LegalAcceptanceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool
    version: str
    acceptedAt: datetime | None = None


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    onboardingRequired: bool
    experienceLevel: ExperienceLevel | None = None
    workspaceMode: WorkspaceMode | None = None
    assistancePreference: AssistancePreference | None = None
    firstGoal: FirstGoal | None = None
    onboardingVersion: str | None = None
    onboardingCompletedAt: datetime | None = None
    updatedAt: datetime | None = None
    preferredLlmProvider: str | None = Field(default=None, max_length=32)
    preferredLlmModel: str | None = Field(default=None, max_length=128)


class PublicUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    role: UserRole
    status: UserStatus
    emailVerifiedAt: datetime
    createdAt: datetime
    lastLoginAt: datetime | None = None


class SessionView(BaseModel):
    """只暴露会话治理所需元数据，不返回令牌或 CSRF 摘要。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    current: bool
    createdAt: datetime
    lastSeenAt: datetime
    expiresAt: datetime


class AdminUserView(PublicUser):
    experimentCount: int = Field(default=0, ge=0)
    activityCount: int = Field(default=0, ge=0)
    lastActivityAt: datetime | None = None


class ActivityView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    userId: str | None
    userEmail: str | None = None
    action: str
    status: str
    entityType: str | None = None
    entityId: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime


class ChallengeDispatch(BaseModel):
    """可以返回给客户端的验证码发送结果，不包含验证码本身。"""

    model_config = ConfigDict(extra="forbid")

    challengeId: str
    expiresAt: datetime
    resendAfter: datetime


@dataclass(frozen=True, slots=True)
class AuthContext:
    userId: str
    authSessionId: str
    email: str
    role: UserRole
    status: UserStatus

    @property
    def isAdmin(self) -> bool:
        return self.role is UserRole.ADMIN


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """只在服务层与 HTTP Cookie 适配层之间短暂传递的原始令牌。"""

    sessionId: str
    user: PublicUser
    expiresAt: datetime
    token: str = field(repr=False)
    csrfToken: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ChallengeRecord:
    id: str
    email: str
    purpose: ChallengePurpose
    codeHash: str = field(repr=False)
    locale: AuthLocale
    attemptCount: int
    maximumAttempts: int
    expiresAt: datetime
    resendAfter: datetime
    consumedAt: datetime | None
    createdAt: datetime


@dataclass(frozen=True, slots=True)
class ActiveSessionRecord:
    context: AuthContext
    csrfHash: str = field(repr=False)
    expiresAt: datetime
