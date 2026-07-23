"""Event Pack Factory 的领域模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictFactoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuildStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEW_READY = "REVIEW_READY"


class SourceInputKind(StrEnum):
    PASTE = "PASTE"
    SEARCH_RESULT = "SEARCH_RESULT"
    READER = "READER"


class EvidenceRole(StrEnum):
    EVIDENCE = "EVIDENCE"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"


class SourceReviewStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SourceSecurityDecision(StrEnum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"


class EventPackFactoryBuild(StrictFactoryModel):
    id: str
    ownerUserId: str
    title: str
    status: BuildStatus
    revision: int = Field(ge=0)
    createdAt: datetime
    updatedAt: datetime
    retentionExpiresAt: datetime


class EventPackFactorySource(StrictFactoryModel):
    id: str
    buildId: str
    kind: SourceInputKind
    evidenceRole: EvidenceRole
    reviewStatus: SourceReviewStatus
    securityDecision: SourceSecurityDecision
    title: str
    publisher: str
    url: str | None = None
    publishedAt: datetime | None = None
    knownAt: datetime
    contentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contentLength: int = Field(ge=0)
    reviewSummary: str
    verifiedEvidenceQuotes: tuple[str, ...] = ()
    searchRunId: str | None = None
    parentSourceId: str | None = None
    createdAt: datetime
    updatedAt: datetime

    @property
    def canSupportClaims(self) -> bool:
        return (
            self.evidenceRole is EvidenceRole.EVIDENCE
            and self.reviewStatus is SourceReviewStatus.APPROVED
        )


class SearchEngine(StrEnum):
    STANDARD = "search_std"
    PRO = "search_pro"
    SOGOU = "search_pro_sogou"
    QUARK = "search_pro_quark"


class SearchRecency(StrEnum):
    ONE_DAY = "oneDay"
    ONE_WEEK = "oneWeek"
    ONE_MONTH = "oneMonth"
    ONE_YEAR = "oneYear"
    NO_LIMIT = "noLimit"


class SearchContentSize(StrEnum):
    MEDIUM = "medium"
    HIGH = "high"


class SearchEngineDescriptor(StrictFactoryModel):
    engine: SearchEngine
    displayName: str
    priceCnyPerCall: float = Field(ge=0)
    supportsCount: bool
    supportedCounts: tuple[int, ...] | None = None
    supportsDomainFilter: bool
    supportsRecencyFilter: bool
    supportsContentSize: bool


class ReaderBillingStatus(StrEnum):
    UNKNOWN = "UNKNOWN"


class ReaderCapabilityDescriptor(StrictFactoryModel):
    endpoint: str
    billingStatus: ReaderBillingStatus = ReaderBillingStatus.UNKNOWN
    pricingNote: str


class WebSearchRequest(StrictFactoryModel):
    query: str = Field(min_length=1, max_length=70)
    engine: SearchEngine = SearchEngine.STANDARD
    searchIntent: bool = False
    count: int | None = Field(default=10, ge=1, le=50)
    domainFilter: str | None = Field(default=None, max_length=253)
    recency: SearchRecency = SearchRecency.NO_LIMIT
    contentSize: SearchContentSize = SearchContentSize.MEDIUM

    @model_validator(mode="after")
    def stripQuery(self) -> WebSearchRequest:
        normalized = self.query.strip()
        if not normalized:
            raise ValueError("query must not be blank")
        self.query = normalized
        return self


class WebSearchResult(StrictFactoryModel):
    title: str
    content: str
    url: str
    publisher: str
    publishedAt: datetime | None = None


class WebSearchResponse(StrictFactoryModel):
    providerRequestId: str
    createdAt: datetime
    engine: SearchEngine
    estimatedCostCny: float = Field(ge=0)
    results: tuple[WebSearchResult, ...]
    droppedResultCount: int = Field(default=0, ge=0)


class SearchRunRecord(StrictFactoryModel):
    id: str
    buildId: str
    engine: SearchEngine
    query: str
    queryHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    requestParameters: dict[str, object]
    providerRequestId: str
    estimatedCostCny: float = Field(ge=0)
    resultCount: int = Field(ge=0)
    droppedResultCount: int = Field(ge=0)
    createdAt: datetime


class BuildSnapshot(StrictFactoryModel):
    build: EventPackFactoryBuild
    sources: tuple[EventPackFactorySource, ...]
    searchRuns: tuple[SearchRunRecord, ...]


class FactoryMutationResult(StrictFactoryModel):
    build: EventPackFactoryBuild
    sources: tuple[EventPackFactorySource, ...] = ()
    searchRun: SearchRunRecord | None = None
    idempotencyReplayed: bool = False


class FactorySourceRawText(StrictFactoryModel):
    """仅允许来源所属 owner 按需读取的敏感原文载荷。"""

    buildId: str
    sourceId: str
    revision: int = Field(ge=0)
    rawText: str = Field(min_length=1, max_length=100_000, repr=False)
    contentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contentLength: int = Field(ge=1)
    retentionExpiresAt: datetime


class PasteSourceInput(StrictFactoryModel):
    title: str = Field(min_length=1, max_length=300)
    publisher: str = Field(min_length=1, max_length=200)
    rawText: str = Field(min_length=1, max_length=100_000, repr=False)
    url: str | None = Field(default=None, max_length=2_000)
    publishedAt: datetime | None = None
    knownAt: datetime
    reviewSummary: str | None = Field(default=None, max_length=2_000)
    verifiedEvidenceQuotes: tuple[str, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def validatePointInTime(self) -> PasteSourceInput:
        if self.publishedAt is not None and self.knownAt < self.publishedAt:
            raise ValueError("knownAt must not be earlier than publishedAt")
        return self


class ReaderSourceInput(StrictFactoryModel):
    searchResultSourceId: str = Field(min_length=8, max_length=80)
    rawText: str = Field(min_length=1, max_length=100_000, repr=False)
    knownAt: datetime
    reviewSummary: str | None = Field(default=None, max_length=2_000)
    verifiedEvidenceQuotes: tuple[str, ...] = Field(default=(), max_length=12)


class SourceReviewInput(StrictFactoryModel):
    status: SourceReviewStatus

    @model_validator(mode="after")
    def requireFinalStatus(self) -> SourceReviewInput:
        if self.status is SourceReviewStatus.PENDING:
            raise ValueError("review status must be APPROVED or REJECTED")
        return self
