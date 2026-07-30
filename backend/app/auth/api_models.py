"""认证 HTTP 接口模型；禁止额外字段，避免客户端误传敏感信息。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from backend.app.auth.models import (
    AssistancePreference,
    AuthLocale,
    ChallengePurpose,
    ExperienceLevel,
    FirstGoal,
    UserStatus,
    WorkspaceMode,
)


class AuthLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    language: AuthLocale = "en"


class VerificationCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    purpose: ChallengePurpose
    language: AuthLocale = "en"


class AuthPasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    verificationCode: str = Field(pattern=r"^[0-9]{6}$")
    language: AuthLocale = "en"


class LegalConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: AuthLocale = "en"
    version: str = Field(min_length=6, max_length=64)
    documentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    acceptedTerms: StrictBool
    acknowledgedPrivacy: StrictBool
    confirmedMinimumAge: StrictBool
    acknowledgedAiBoundary: StrictBool


class AuthRegistrationRequest(LegalConsentRequest):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    verificationCode: str = Field(pattern=r"^[0-9]{6}$")


class UserPreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experienceLevel: ExperienceLevel
    workspaceMode: WorkspaceMode
    assistancePreference: AssistancePreference
    firstGoal: FirstGoal


class UserStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: UserStatus


class AccountDataExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=128)


class AccountDeletionRequest(AccountDataExportRequest):
    confirmation: Literal["DELETE"]
