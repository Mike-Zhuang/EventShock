"""认证 HTTP 接口模型；禁止额外字段，避免客户端误传敏感信息。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.app.auth.models import AuthLocale, ChallengePurpose, UserStatus


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


class AuthCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    verificationCode: str = Field(pattern=r"^[0-9]{6}$")
    language: AuthLocale = "en"


class UserStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: UserStatus
