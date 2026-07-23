"""Event Pack Factory 的严格 API 请求包装模型。

这些模型只描述 HTTP 边界，不执行 Event Pack 的最终物化。粘贴正文使用
``SecretStr``，避免框架或调试日志在对象表示中直接输出未审阅原文。
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, SecretStr, StrictBool, field_validator, model_validator

from backend.app.event_pack_factory.errors import (
    FactoryErrorCode,
    FactoryValidationError,
)
from backend.app.event_pack_factory.models import (
    PasteSourceInput,
    SourceReviewStatus,
    StrictFactoryModel,
    WebSearchRequest,
)

CLIENT_REQUEST_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{7,79}$"
ALLOWED_IMPACT_CHANNELS = frozenset(
    {
        "belief",
        "liquidity",
        "passiveFlow",
        "stopLoss",
        "socialAmplification",
        "informationLatency",
    }
)


class FactoryBuildCreateRequest(StrictFactoryModel):
    title: str = Field(min_length=1, max_length=200)


class FactoryPasteSourceApiInput(StrictFactoryModel):
    title: str = Field(min_length=1, max_length=300)
    publisher: str = Field(min_length=1, max_length=200)
    rawText: SecretStr
    url: str | None = Field(default=None, max_length=2_000)
    publishedAt: datetime | None = None
    knownAt: datetime
    reviewSummary: str | None = Field(default=None, max_length=2_000)
    verifiedEvidenceQuotes: tuple[str, ...] = Field(default=(), max_length=12)

    def toDomainInput(self) -> PasteSourceInput:
        """在服务调用点显式解封原文，禁止调用方意外记录普通字符串。"""

        rawText = self.rawText.get_secret_value()
        if not 1 <= len(rawText) <= 100_000:
            raise FactoryValidationError(
                FactoryErrorCode.INVALID_SOURCE,
                "rawText must contain 1 to 100000 characters.",
            )
        if self.knownAt.tzinfo is None or self.knownAt.utcoffset() is None:
            raise FactoryValidationError(
                FactoryErrorCode.INVALID_SOURCE,
                "knownAt must include a timezone.",
            )
        if self.publishedAt is not None and (
            self.publishedAt.tzinfo is None or self.publishedAt.utcoffset() is None
        ):
            raise FactoryValidationError(
                FactoryErrorCode.INVALID_SOURCE,
                "publishedAt must include a timezone.",
            )
        if self.publishedAt is not None and self.knownAt < self.publishedAt:
            raise FactoryValidationError(
                FactoryErrorCode.INVALID_SOURCE,
                "knownAt must not be earlier than publishedAt.",
            )
        return PasteSourceInput(
            title=self.title,
            publisher=self.publisher,
            rawText=rawText,
            url=self.url,
            publishedAt=self.publishedAt,
            knownAt=self.knownAt,
            reviewSummary=self.reviewSummary,
            verifiedEvidenceQuotes=self.verifiedEvidenceQuotes,
        )


class FactoryPasteMutationRequest(StrictFactoryModel):
    expectedRevision: int = Field(ge=0)
    source: FactoryPasteSourceApiInput


class FactorySearchMutationRequest(StrictFactoryModel):
    clientRequestId: str = Field(pattern=CLIENT_REQUEST_ID_PATTERN)
    expectedRevision: int = Field(ge=0)
    request: WebSearchRequest


class FactoryReviewMutationRequest(StrictFactoryModel):
    expectedRevision: int = Field(ge=0)
    status: SourceReviewStatus

    @model_validator(mode="after")
    def requireFinalStatus(self) -> FactoryReviewMutationRequest:
        if self.status is SourceReviewStatus.PENDING:
            raise ValueError("status must be APPROVED or REJECTED")
        return self


class FactoryReaderMutationRequest(StrictFactoryModel):
    clientRequestId: str = Field(pattern=CLIENT_REQUEST_ID_PATTERN)
    expectedRevision: int = Field(ge=0)
    searchResultSourceId: str = Field(min_length=8, max_length=80)
    knownAt: datetime


class FactoryMaterializeRequest(StrictFactoryModel):
    """物化元数据；调用该模型本身不会新建或冻结 Event Pack。"""

    clientRequestId: str = Field(pattern=CLIENT_REQUEST_ID_PATTERN)
    expectedRevision: int = Field(ge=0)
    title: str = Field(min_length=3, max_length=200)
    titleZh: str | None = Field(default=None, max_length=200)
    summary: str = Field(min_length=8, max_length=1_000)
    summaryZh: str | None = Field(default=None, max_length=1_000)
    asOf: datetime
    instrument: str = Field(default="CUSTOM", min_length=1, max_length=32)
    maximumClaims: int = Field(default=16, ge=1, le=50)
    requestedImpactChannels: tuple[str, ...] = Field(
        default=("belief", "liquidity", "passiveFlow", "stopLoss"),
        min_length=1,
        max_length=12,
    )
    acknowledgedContentReview: StrictBool

    @field_validator("acknowledgedContentReview")
    @classmethod
    def requireExplicitContentReview(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("acknowledgedContentReview must be true")
        return value

    @model_validator(mode="after")
    def validateMaterializationMetadata(self) -> FactoryMaterializeRequest:
        if self.asOf.tzinfo is None or self.asOf.utcoffset() is None:
            raise ValueError("asOf must include a timezone")
        self.asOf = self.asOf.astimezone(UTC)
        if len(self.requestedImpactChannels) != len(set(self.requestedImpactChannels)):
            raise ValueError("requestedImpactChannels must not contain duplicates")
        unsupported = set(self.requestedImpactChannels) - ALLOWED_IMPACT_CHANNELS
        if unsupported:
            raise ValueError("requestedImpactChannels contains unsupported values")
        return self


class FactoryDeleteBuildRequest(StrictFactoryModel):
    expectedRevision: int = Field(ge=0)


class FactorySourceRawTextUpdateRequest(StrictFactoryModel):
    expectedRevision: int = Field(ge=0)
    rawText: SecretStr
    reviewSummary: str | None = Field(default=None, max_length=2_000)
    verifiedEvidenceQuotes: tuple[str, ...] = Field(default=(), max_length=12)

    def revealedRawText(self) -> str:
        rawText = self.rawText.get_secret_value()
        if not 1 <= len(rawText) <= 100_000:
            raise FactoryValidationError(
                FactoryErrorCode.INVALID_SOURCE,
                "rawText must contain 1 to 100000 characters.",
            )
        return rawText
