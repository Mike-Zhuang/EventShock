"""Event Pack Factory 的编排与安全边界。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.app.event_pack_factory.errors import (
    FactoryErrorCode,
    FactoryIdempotencyError,
    FactoryRevisionConflictError,
    FactoryValidationError,
)
from backend.app.event_pack_factory.models import (
    BuildSnapshot,
    EventPackFactoryBuild,
    EventPackFactorySource,
    EvidenceRole,
    FactoryMutationResult,
    FactorySourceRawText,
    PasteSourceInput,
    ReaderSourceInput,
    SearchRunRecord,
    SourceInputKind,
    SourceReviewInput,
    SourceReviewStatus,
    SourceSecurityDecision,
    WebSearchRequest,
)
from backend.app.event_pack_factory.reader import ZhipuReaderClient
from backend.app.event_pack_factory.repository import (
    EventPackFactoryRepository,
    utcNowDateTime,
)
from backend.app.event_pack_factory.search import ZhipuWebSearchClient
from backend.app.event_pack_factory.urls import normalizePublicHttpsUrl
from backend.app.security import (
    ContentPolicyDecision,
    ContentScanResult,
    redactReviewableText,
    scanEventPackContent,
    scanTextContent,
)

MAX_REVIEW_SUMMARY_CHARACTERS = 2_000
MAX_VERIFIED_QUOTE_CHARACTERS = 500
MAX_VERIFIED_QUOTES_CHARACTERS = 4_000
_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")


@dataclass(frozen=True, slots=True)
class _PreparedEvidence:
    source: EventPackFactorySource
    rawText: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _ApprovedEvidenceInput:
    """只供后端物化编排使用；原文不会进入 Pydantic 响应序列化。"""

    source: EventPackFactorySource
    rawText: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class IdempotentJsonResult:
    payload: dict[str, object]
    replayed: bool


class EventPackFactoryService:
    def __init__(
        self,
        repository: EventPackFactoryRepository,
        searchClient: ZhipuWebSearchClient,
        readerClient: ZhipuReaderClient | None = None,
    ) -> None:
        self._repository = repository
        self._searchClient = searchClient
        self._readerClient = readerClient

    def createBuild(self, *, ownerUserId: str, title: str) -> EventPackFactoryBuild:
        self._cleanupExpired()
        owner = _validatedOwner(ownerUserId)
        normalizedTitle = _plainText(title, maximum=200, fieldName="title")
        return self._repository.createBuild(
            buildId=f"epfb-{uuid.uuid4().hex}",
            ownerUserId=owner,
            title=normalizedTitle,
        )

    def getBuild(self, *, ownerUserId: str, buildId: str) -> BuildSnapshot:
        self._cleanupExpired()
        return self._repository.getSnapshot(
            ownerUserId=_validatedOwner(ownerUserId),
            buildId=_validatedId(buildId, "buildId"),
        )

    def listBuilds(self, *, ownerUserId: str) -> tuple[EventPackFactoryBuild, ...]:
        self._cleanupExpired()
        return self._repository.listBuilds(ownerUserId=_validatedOwner(ownerUserId))

    def addPasteSource(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        expectedRevision: int,
        sourceInput: PasteSourceInput,
    ) -> FactoryMutationResult:
        self._cleanupExpired()
        owner = _validatedOwner(ownerUserId)
        normalizedBuildId = _validatedId(buildId, "buildId")
        prepared = self._prepareEvidenceSource(
            buildId=normalizedBuildId,
            kind=SourceInputKind.PASTE,
            title=sourceInput.title,
            publisher=sourceInput.publisher,
            rawText=sourceInput.rawText,
            url=sourceInput.url,
            publishedAt=sourceInput.publishedAt,
            knownAt=sourceInput.knownAt,
            reviewSummary=sourceInput.reviewSummary,
            verifiedEvidenceQuotes=sourceInput.verifiedEvidenceQuotes,
        )
        build = self._repository.addSource(
            ownerUserId=owner,
            buildId=normalizedBuildId,
            expectedRevision=_validatedRevision(expectedRevision),
            source=prepared.source,
            rawText=prepared.rawText,
        )
        return FactoryMutationResult(build=build, sources=(prepared.source,))

    async def searchSources(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        expectedRevision: int,
        request: WebSearchRequest,
        apiKey: str,
        clientRequestId: str | None = None,
    ) -> FactoryMutationResult:
        self._cleanupExpired()
        owner = _validatedOwner(ownerUserId)
        normalizedBuildId = _validatedId(buildId, "buildId")
        normalizedRevision = _validatedRevision(expectedRevision)
        _requireSafeSearchQuery(request.query)

        normalizedClientRequestId = clientRequestId or f"epfs-{uuid.uuid4().hex}"
        payloadHash = self.canonicalPayloadHash(
            "SEARCH",
            normalizedBuildId,
            {
                "expectedRevision": normalizedRevision,
                "request": request.model_dump(mode="json"),
            },
        )
        claim = self._repository.claimIdempotency(
            ownerUserId=owner,
            operation="SEARCH",
            clientRequestId=normalizedClientRequestId,
            buildId=normalizedBuildId,
            payloadHash=payloadHash,
        )
        if claim.state == "SUCCEEDED" and claim.responseJson is not None:
            return FactoryMutationResult.model_validate_json(claim.responseJson).model_copy(
                update={"idempotencyReplayed": True}
            )

        pseudonymousUserId = f"factory-{hashlib.sha256(owner.encode()).hexdigest()[:24]}"
        try:
            # 已完成请求必须先恢复，否则该请求自身推进的 revision 会阻止重放。
            snapshot = self._repository.getSnapshot(
                ownerUserId=owner,
                buildId=normalizedBuildId,
            )
            if snapshot.build.revision != normalizedRevision:
                raise FactoryRevisionConflictError(
                    expectedRevision=normalizedRevision,
                    actualRevision=snapshot.build.revision,
                )
            response = await self._searchClient.search(
                request,
                apiKey=apiKey,
                requestId=(
                    "epfs-"
                    + hashlib.sha256(f"{owner}:{normalizedClientRequestId}".encode()).hexdigest()[
                        :32
                    ]
                ),
                userId=pseudonymousUserId,
            )
            searchRunId = f"epfsr-{uuid.uuid4().hex}"
            sources: list[EventPackFactorySource] = []
            safetyDroppedCount = 0
            for result in response.results:
                prepared = self._prepareDiscoverySource(
                    buildId=normalizedBuildId,
                    searchRunId=searchRunId,
                    title=result.title,
                    publisher=result.publisher,
                    content=result.content,
                    url=result.url,
                    publishedAt=result.publishedAt,
                    knownAt=response.createdAt,
                )
                if prepared is None:
                    safetyDroppedCount += 1
                    continue
                sources.append(prepared)

            searchRun = SearchRunRecord(
                id=searchRunId,
                buildId=normalizedBuildId,
                engine=request.engine,
                query=request.query,
                queryHash=hashlib.sha256(request.query.encode("utf-8")).hexdigest(),
                requestParameters={
                    "engine": request.engine.value,
                    "searchIntent": request.searchIntent,
                    "count": request.count,
                    "domainFilter": request.domainFilter,
                    "recency": request.recency.value,
                    "contentSize": request.contentSize.value,
                },
                providerRequestId=response.providerRequestId,
                estimatedCostCny=response.estimatedCostCny,
                resultCount=len(sources),
                droppedResultCount=response.droppedResultCount + safetyDroppedCount,
                createdAt=response.createdAt,
            )
            build = self._repository.recordSearch(
                ownerUserId=owner,
                buildId=normalizedBuildId,
                expectedRevision=normalizedRevision,
                searchRun=searchRun,
                sources=sources,
            )
            result = FactoryMutationResult(
                build=build,
                sources=tuple(sources),
                searchRun=searchRun,
            )
            self._repository.completeIdempotency(
                ownerUserId=owner,
                operation="SEARCH",
                clientRequestId=normalizedClientRequestId,
                payloadHash=payloadHash,
                responseJson=result.model_dump_json(),
            )
            return result
        except Exception as error:
            self._repository.failIdempotency(
                ownerUserId=owner,
                operation="SEARCH",
                clientRequestId=normalizedClientRequestId,
                payloadHash=payloadHash,
                failureCode=type(error).__name__,
            )
            raise

    def addReaderSource(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        expectedRevision: int,
        sourceInput: ReaderSourceInput,
    ) -> FactoryMutationResult:
        self._cleanupExpired()
        owner = _validatedOwner(ownerUserId)
        normalizedBuildId = _validatedId(buildId, "buildId")
        parent = self._approvedReaderParent(
            ownerUserId=owner,
            buildId=normalizedBuildId,
            sourceId=sourceInput.searchResultSourceId,
        )
        normalizedUrl = normalizePublicHttpsUrl(parent.url)
        knownAt = _awareUtc(sourceInput.knownAt, "knownAt")
        if parent.publishedAt is not None and knownAt < parent.publishedAt:
            raise FactoryValidationError(
                FactoryErrorCode.INVALID_SOURCE,
                "knownAt must not be earlier than publishedAt.",
            )
        prepared = self._prepareEvidenceSource(
            buildId=normalizedBuildId,
            kind=SourceInputKind.READER,
            title=parent.title,
            publisher=parent.publisher,
            rawText=sourceInput.rawText,
            url=normalizedUrl,
            publishedAt=parent.publishedAt,
            knownAt=knownAt,
            reviewSummary=sourceInput.reviewSummary,
            verifiedEvidenceQuotes=sourceInput.verifiedEvidenceQuotes,
            searchRunId=parent.searchRunId,
            parentSourceId=parent.id,
        )
        build = self._repository.addSource(
            ownerUserId=owner,
            buildId=normalizedBuildId,
            expectedRevision=_validatedRevision(expectedRevision),
            source=prepared.source,
            rawText=prepared.rawText,
        )
        return FactoryMutationResult(build=build, sources=(prepared.source,))

    async def fetchReaderSource(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        expectedRevision: int,
        searchResultSourceId: str,
        knownAt: datetime,
        apiKey: str,
        clientRequestId: str | None = None,
    ) -> FactoryMutationResult:
        """由服务端 Reader 抓取已批准搜索结果，不接受客户端回传正文。"""

        self._cleanupExpired()
        owner = _validatedOwner(ownerUserId)
        normalizedBuildId = _validatedId(buildId, "buildId")
        normalizedRevision = _validatedRevision(expectedRevision)
        normalizedKnownAt = _awareUtc(knownAt, "knownAt")
        normalizedClientRequestId = clientRequestId or f"epfr-{uuid.uuid4().hex}"
        payloadHash = self.canonicalPayloadHash(
            "READER",
            normalizedBuildId,
            {
                "expectedRevision": normalizedRevision,
                "searchResultSourceId": searchResultSourceId,
                "knownAt": normalizedKnownAt.isoformat(),
            },
        )
        claim = self._repository.claimIdempotency(
            ownerUserId=owner,
            operation="READER",
            clientRequestId=normalizedClientRequestId,
            buildId=normalizedBuildId,
            payloadHash=payloadHash,
        )
        if claim.state == "SUCCEEDED" and claim.responseJson is not None:
            return FactoryMutationResult.model_validate_json(claim.responseJson).model_copy(
                update={"idempotencyReplayed": True}
            )

        readerClient = self._readerClient
        ownsReaderClient = readerClient is None
        if readerClient is None:
            readerClient = ZhipuReaderClient()
        try:
            snapshot = self._repository.getSnapshot(
                ownerUserId=owner,
                buildId=normalizedBuildId,
            )
            if snapshot.build.revision != normalizedRevision:
                raise FactoryRevisionConflictError(
                    expectedRevision=normalizedRevision,
                    actualRevision=snapshot.build.revision,
                )
            parent = self._approvedReaderParent(
                ownerUserId=owner,
                buildId=normalizedBuildId,
                sourceId=searchResultSourceId,
            )
            normalizedUrl = normalizePublicHttpsUrl(parent.url)
            if parent.publishedAt is not None and normalizedKnownAt < parent.publishedAt:
                raise FactoryValidationError(
                    FactoryErrorCode.INVALID_SOURCE,
                    "knownAt must not be earlier than publishedAt.",
                )
            fetched = await readerClient.read(normalizedUrl, apiKey=apiKey)
            prepared = self._prepareEvidenceSource(
                buildId=normalizedBuildId,
                kind=SourceInputKind.READER,
                title=parent.title,
                publisher=parent.publisher,
                rawText=fetched.rawText,
                url=normalizedUrl,
                publishedAt=parent.publishedAt,
                knownAt=normalizedKnownAt,
                reviewSummary=None,
                verifiedEvidenceQuotes=(),
                searchRunId=parent.searchRunId,
                parentSourceId=parent.id,
            )
            build = self._repository.addSource(
                ownerUserId=owner,
                buildId=normalizedBuildId,
                expectedRevision=normalizedRevision,
                source=prepared.source,
                rawText=prepared.rawText,
            )
            result = FactoryMutationResult(build=build, sources=(prepared.source,))
            self._repository.completeIdempotency(
                ownerUserId=owner,
                operation="READER",
                clientRequestId=normalizedClientRequestId,
                payloadHash=payloadHash,
                responseJson=result.model_dump_json(),
            )
            return result
        except Exception as error:
            self._repository.failIdempotency(
                ownerUserId=owner,
                operation="READER",
                clientRequestId=normalizedClientRequestId,
                payloadHash=payloadHash,
                failureCode=type(error).__name__,
            )
            raise
        finally:
            if ownsReaderClient:
                await readerClient.aclose()

    def reviewSource(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        sourceId: str,
        expectedRevision: int,
        reviewInput: SourceReviewInput,
    ) -> FactoryMutationResult:
        self._cleanupExpired()
        build, source = self._repository.reviewSource(
            ownerUserId=_validatedOwner(ownerUserId),
            buildId=_validatedId(buildId, "buildId"),
            sourceId=_validatedId(sourceId, "sourceId"),
            expectedRevision=_validatedRevision(expectedRevision),
            reviewStatus=reviewInput.status,
        )
        return FactoryMutationResult(build=build, sources=(source,))

    def getSourceRawText(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        sourceId: str,
    ) -> FactorySourceRawText:
        self._cleanupExpired()
        return self._repository.getSourceRawText(
            ownerUserId=_validatedOwner(ownerUserId),
            buildId=_validatedId(buildId, "buildId"),
            sourceId=_validatedId(sourceId, "sourceId"),
        )

    def updateSourceRawText(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        sourceId: str,
        expectedRevision: int,
        rawText: str,
        reviewSummary: str | None,
        verifiedEvidenceQuotes: tuple[str, ...],
    ) -> FactoryMutationResult:
        self._cleanupExpired()
        owner = _validatedOwner(ownerUserId)
        normalizedBuildId = _validatedId(buildId, "buildId")
        normalizedSourceId = _validatedId(sourceId, "sourceId")
        existing = self._repository.getSource(
            ownerUserId=owner,
            buildId=normalizedBuildId,
            sourceId=normalizedSourceId,
        )
        prepared = self._prepareEvidenceSource(
            buildId=normalizedBuildId,
            kind=existing.kind,
            title=existing.title,
            publisher=existing.publisher,
            rawText=rawText,
            url=existing.url,
            publishedAt=existing.publishedAt,
            knownAt=existing.knownAt,
            reviewSummary=(
                reviewSummary if reviewSummary is not None else "[RAW_TEXT_REVISED_REVIEW_REQUIRED]"
            ),
            verifiedEvidenceQuotes=verifiedEvidenceQuotes,
            searchRunId=existing.searchRunId,
            parentSourceId=existing.parentSourceId,
        )
        revisedSource = prepared.source.model_copy(
            update={
                "id": existing.id,
                "createdAt": existing.createdAt,
            }
        )
        build, source = self._repository.updateSourceRawText(
            ownerUserId=owner,
            buildId=normalizedBuildId,
            sourceId=normalizedSourceId,
            expectedRevision=_validatedRevision(expectedRevision),
            source=revisedSource,
            rawText=prepared.rawText,
        )
        return FactoryMutationResult(build=build, sources=(source,))

    def eligibleEvidenceSources(
        self,
        *,
        ownerUserId: str,
        buildId: str,
    ) -> tuple[EventPackFactorySource, ...]:
        self._cleanupExpired()
        return self._repository.listEligibleEvidenceSources(
            ownerUserId=_validatedOwner(ownerUserId),
            buildId=_validatedId(buildId, "buildId"),
        )

    def assertReadyForClaimExtraction(
        self,
        *,
        ownerUserId: str,
        buildId: str,
    ) -> tuple[EventPackFactorySource, ...]:
        sources = self.eligibleEvidenceSources(ownerUserId=ownerUserId, buildId=buildId)
        if not sources:
            raise FactoryValidationError(
                FactoryErrorCode.BUILD_NOT_READY,
                "At least one human-approved PASTE or READER source is required.",
            )
        return sources

    def approvedEvidenceInputsForMaterialization(
        self,
        *,
        ownerUserId: str,
        buildId: str,
    ) -> tuple[_ApprovedEvidenceInput, ...]:
        """读取批准来源及原文；调用方不得把返回对象用作 HTTP 响应。"""

        self._cleanupExpired()
        owner = _validatedOwner(ownerUserId)
        normalizedBuildId = _validatedId(buildId, "buildId")
        snapshot = self._repository.getSnapshot(
            ownerUserId=owner,
            buildId=normalizedBuildId,
        )
        pendingEvidence = [
            source.id
            for source in snapshot.sources
            if source.evidenceRole is EvidenceRole.EVIDENCE
            and source.reviewStatus is SourceReviewStatus.PENDING
        ]
        if pendingEvidence:
            raise FactoryValidationError(
                FactoryErrorCode.SOURCE_REVIEW_REQUIRED,
                "Every retained evidence source must be approved or rejected before "
                "materialization.",
            )
        payloads = self._repository._listApprovedEvidencePayloads(
            ownerUserId=owner,
            buildId=normalizedBuildId,
        )
        if not payloads:
            raise FactoryValidationError(
                FactoryErrorCode.BUILD_NOT_READY,
                "At least one approved source with retained text is required.",
            )
        return tuple(
            _ApprovedEvidenceInput(source=payload.source, rawText=payload.rawText)
            for payload in payloads
        )

    def deleteBuild(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        expectedRevision: int,
    ) -> bool:
        self._cleanupExpired()
        return self._repository.deleteBuild(
            ownerUserId=_validatedOwner(ownerUserId),
            buildId=_validatedId(buildId, "buildId"),
            expectedRevision=_validatedRevision(expectedRevision),
        )

    async def executeIdempotentJson(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        operation: str,
        clientRequestId: str,
        payloadHash: str,
        callback: Callable[[], Awaitable[dict[str, object]]],
        recovery: Callable[[], Awaitable[dict[str, object] | None]] | None = None,
    ) -> IdempotentJsonResult:
        """为 materialize 等异步创建型操作提供持久幂等边界。"""

        self._cleanupExpired()
        owner = _validatedOwner(ownerUserId)
        normalizedBuildId = _validatedId(buildId, "buildId")
        claim = self._repository.claimIdempotency(
            ownerUserId=owner,
            operation=operation,
            clientRequestId=_validatedId(clientRequestId, "clientRequestId"),
            buildId=normalizedBuildId,
            payloadHash=payloadHash,
        )
        if claim.state == "SUCCEEDED" and claim.responseJson is not None:
            restored = json.loads(claim.responseJson)
            if not isinstance(restored, dict):
                raise RuntimeError("stored idempotent response is invalid")
            return IdempotentJsonResult(payload=restored, replayed=True)
        if claim.state in {"PENDING", "FAILED"}:
            recovered = await recovery() if recovery is not None else None
            if recovered is not None:
                serializedRecovery = json.dumps(
                    recovered,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self._repository.recoverIdempotency(
                    ownerUserId=owner,
                    operation=operation,
                    clientRequestId=clientRequestId,
                    payloadHash=payloadHash,
                    responseJson=serializedRecovery,
                )
                return IdempotentJsonResult(payload=recovered, replayed=True)
            if claim.state == "PENDING":
                raise FactoryIdempotencyError(
                    FactoryErrorCode.IDEMPOTENCY_IN_PROGRESS,
                    "The same request is already in progress; wait before retrying.",
                    statusCode=409,
                )
            raise FactoryIdempotencyError(
                FactoryErrorCode.IDEMPOTENCY_OUTCOME_UNKNOWN,
                (
                    "The prior request did not reach a recoverable terminal result. "
                    "It will not be dispatched again because provider billing may have occurred."
                ),
                statusCode=409,
            )
        try:
            result = await callback()
            self._repository.completeIdempotency(
                ownerUserId=owner,
                operation=operation,
                clientRequestId=clientRequestId,
                payloadHash=payloadHash,
                responseJson=json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            return IdempotentJsonResult(payload=result, replayed=False)
        except Exception as error:
            self._repository.failIdempotency(
                ownerUserId=owner,
                operation=operation,
                clientRequestId=clientRequestId,
                payloadHash=payloadHash,
                failureCode=type(error).__name__,
            )
            raise

    @staticmethod
    def canonicalPayloadHash(
        operation: str,
        buildId: str,
        payload: dict[str, object],
    ) -> str:
        serialized = json.dumps(
            {
                "operation": operation,
                "buildId": buildId,
                "payload": payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _cleanupExpired(self) -> None:
        self._repository.cleanupExpiredBuilds()

    def assertSourceCanSupportClaims(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        sourceId: str,
    ) -> EventPackFactorySource:
        self._cleanupExpired()
        source = self._repository.getSource(
            ownerUserId=_validatedOwner(ownerUserId),
            buildId=_validatedId(buildId, "buildId"),
            sourceId=_validatedId(sourceId, "sourceId"),
        )
        if source.evidenceRole is EvidenceRole.DISCOVERY_ONLY:
            raise FactoryValidationError(
                FactoryErrorCode.DISCOVERY_SOURCE_NOT_EVIDENCE,
                "Search summaries are discovery-only and cannot support claims or freezing.",
            )
        if source.reviewStatus is not SourceReviewStatus.APPROVED:
            raise FactoryValidationError(
                FactoryErrorCode.SOURCE_REVIEW_REQUIRED,
                "The source requires explicit human approval.",
            )
        return source

    def _prepareEvidenceSource(
        self,
        *,
        buildId: str,
        kind: SourceInputKind,
        title: str,
        publisher: str,
        rawText: str,
        url: str | None,
        publishedAt: datetime | None,
        knownAt: datetime,
        reviewSummary: str | None,
        verifiedEvidenceQuotes: tuple[str, ...],
        searchRunId: str | None = None,
        parentSourceId: str | None = None,
    ) -> _PreparedEvidence:
        normalizedRaw = _normalizedRawText(rawText)
        normalizedUrl = normalizePublicHttpsUrl(url) if url is not None else None
        normalizedPublishedAt = (
            _awareUtc(publishedAt, "publishedAt") if publishedAt is not None else None
        )
        normalizedKnownAt = _awareUtc(knownAt, "knownAt")
        if normalizedPublishedAt is not None and normalizedKnownAt < normalizedPublishedAt:
            raise FactoryValidationError(
                FactoryErrorCode.INVALID_SOURCE,
                "knownAt must not be earlier than publishedAt.",
            )
        metadata = {
            "title": title,
            "publisher": publisher,
            "url": normalizedUrl or "",
            "sourceType": kind.value,
        }
        scan = scanEventPackContent(normalizedRaw, metadata)
        _rejectBlockedContent(scan)

        summaryCandidate = reviewSummary if reviewSummary is not None else normalizedRaw
        summary = _safeReviewText(summaryCandidate, MAX_REVIEW_SUMMARY_CHARACTERS)
        quotes = _verifiedQuotes(normalizedRaw, verifiedEvidenceQuotes)
        timestamp = utcNowDateTime()
        return _PreparedEvidence(
            source=EventPackFactorySource(
                id=f"epfsrc-{uuid.uuid4().hex}",
                buildId=buildId,
                kind=kind,
                evidenceRole=EvidenceRole.EVIDENCE,
                reviewStatus=SourceReviewStatus.PENDING,
                securityDecision=SourceSecurityDecision(scan.decision.value),
                title=_plainText(title, maximum=300, fieldName="title"),
                publisher=_plainText(publisher, maximum=200, fieldName="publisher"),
                url=normalizedUrl,
                publishedAt=normalizedPublishedAt,
                knownAt=normalizedKnownAt,
                contentHash=hashlib.sha256(normalizedRaw.encode("utf-8")).hexdigest(),
                contentLength=len(normalizedRaw),
                reviewSummary=summary,
                verifiedEvidenceQuotes=quotes,
                searchRunId=searchRunId,
                parentSourceId=parentSourceId,
                createdAt=timestamp,
                updatedAt=timestamp,
            ),
            rawText=normalizedRaw,
        )

    def _prepareDiscoverySource(
        self,
        *,
        buildId: str,
        searchRunId: str,
        title: str,
        publisher: str,
        content: str,
        url: str,
        publishedAt: datetime | None,
        knownAt: datetime,
    ) -> EventPackFactorySource | None:
        normalizedContent = _normalizedRawText(content)
        normalizedUrl = normalizePublicHttpsUrl(url)
        scan = scanEventPackContent(
            normalizedContent,
            {
                "title": title,
                "publisher": publisher,
                "url": normalizedUrl,
                "sourceType": SourceInputKind.SEARCH_RESULT.value,
            },
        )
        if scan.decision is ContentPolicyDecision.BLOCK:
            return None
        normalizedKnownAt = _awareUtc(knownAt, "knownAt")
        normalizedPublishedAt = (
            _awareUtc(publishedAt, "publishedAt") if publishedAt is not None else None
        )
        if normalizedPublishedAt is not None and normalizedPublishedAt > normalizedKnownAt:
            normalizedPublishedAt = None
        timestamp = utcNowDateTime()
        return EventPackFactorySource(
            id=f"epfsrc-{uuid.uuid4().hex}",
            buildId=buildId,
            kind=SourceInputKind.SEARCH_RESULT,
            evidenceRole=EvidenceRole.DISCOVERY_ONLY,
            reviewStatus=SourceReviewStatus.PENDING,
            securityDecision=SourceSecurityDecision(scan.decision.value),
            title=_plainText(title, maximum=300, fieldName="title"),
            publisher=_plainText(publisher, maximum=200, fieldName="publisher"),
            url=normalizedUrl,
            publishedAt=normalizedPublishedAt,
            knownAt=normalizedKnownAt,
            contentHash=hashlib.sha256(normalizedContent.encode("utf-8")).hexdigest(),
            contentLength=len(normalizedContent),
            reviewSummary=_safeReviewText(normalizedContent, MAX_REVIEW_SUMMARY_CHARACTERS),
            verifiedEvidenceQuotes=(),
            searchRunId=searchRunId,
            createdAt=timestamp,
            updatedAt=timestamp,
        )

    def _approvedReaderParent(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        sourceId: str,
    ) -> EventPackFactorySource:
        parent = self._repository.getSource(
            ownerUserId=ownerUserId,
            buildId=buildId,
            sourceId=_validatedId(sourceId, "searchResultSourceId"),
        )
        if (
            parent.kind is not SourceInputKind.SEARCH_RESULT
            or parent.evidenceRole is not EvidenceRole.DISCOVERY_ONLY
            or parent.searchRunId is None
            or parent.url is None
        ):
            raise FactoryValidationError(
                FactoryErrorCode.READER_SOURCE_NOT_ALLOWED,
                "Reader input must reference a search result from this build.",
            )
        if parent.reviewStatus is not SourceReviewStatus.APPROVED:
            raise FactoryValidationError(
                FactoryErrorCode.SOURCE_REVIEW_REQUIRED,
                "Approve the selected search result before adding Reader evidence.",
            )
        return parent


def _rejectBlockedContent(scan: ContentScanResult) -> None:
    if scan.decision is not ContentPolicyDecision.BLOCK:
        return
    findingCodes = sorted({finding.code for finding in scan.findings})
    raise FactoryValidationError(
        FactoryErrorCode.CONTENT_BLOCKED,
        "The source failed the deterministic content safety boundary.",
        details={"findingCodes": findingCodes},
    )


def _normalizedRawText(value: str) -> str:
    if not isinstance(value, str):
        raise FactoryValidationError(
            FactoryErrorCode.INVALID_SOURCE,
            "rawText must be a string.",
        )
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized or len(normalized) > 100_000:
        raise FactoryValidationError(
            FactoryErrorCode.INVALID_SOURCE,
            "rawText must contain 1 to 100000 characters.",
        )
    return normalized


def _safeReviewText(value: str, maximum: int) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    scan = scanTextContent(normalized)
    _rejectBlockedContent(scan)
    if scan.decision is ContentPolicyDecision.REVIEW:
        normalized = redactReviewableText(normalized)
    return " ".join(normalized.split())[:maximum].strip()


def _verifiedQuotes(rawText: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) > 12:
        raise FactoryValidationError(
            FactoryErrorCode.INVALID_SOURCE,
            "No more than 12 verified evidence quotes are allowed.",
        )
    normalizedQuotes: list[str] = []
    totalCharacters = 0
    for value in values:
        quote = unicodedata.normalize("NFKC", value).strip()
        if not quote or len(quote) > MAX_VERIFIED_QUOTE_CHARACTERS:
            raise FactoryValidationError(
                FactoryErrorCode.INVALID_SOURCE,
                "Each verified evidence quote must contain 1 to 500 characters.",
            )
        if quote not in rawText:
            raise FactoryValidationError(
                FactoryErrorCode.INVALID_SOURCE,
                "Every verified evidence quote must occur verbatim in rawText.",
            )
        quoteScan = scanTextContent(quote)
        if quoteScan.decision is not ContentPolicyDecision.ALLOW:
            raise FactoryValidationError(
                FactoryErrorCode.CONTENT_BLOCKED,
                "Verified evidence quotes must pass the content safety boundary.",
                details={"findingCodes": sorted({finding.code for finding in quoteScan.findings})},
            )
        totalCharacters += len(quote)
        if totalCharacters > MAX_VERIFIED_QUOTES_CHARACTERS:
            raise FactoryValidationError(
                FactoryErrorCode.INVALID_SOURCE,
                "Verified evidence quotes exceed the 4000-character total limit.",
            )
        if quote not in normalizedQuotes:
            normalizedQuotes.append(quote)
    return tuple(normalizedQuotes)


def _requireSafeSearchQuery(query: str) -> None:
    scan = scanTextContent(query, field="searchQuery")
    if scan.decision is ContentPolicyDecision.ALLOW:
        return
    raise FactoryValidationError(
        FactoryErrorCode.INVALID_SEARCH_REQUEST,
        "The search query contains content that must not be sent to a provider.",
        details={"findingCodes": sorted({finding.code for finding in scan.findings})},
    )


def _plainText(value: str, *, maximum: int, fieldName: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).split()).strip()
    if not normalized or len(normalized) > maximum:
        raise FactoryValidationError(
            FactoryErrorCode.INVALID_SOURCE,
            f"{fieldName} must contain 1 to {maximum} characters.",
        )
    scan = scanTextContent(normalized, field=fieldName)
    _rejectBlockedContent(scan)
    if scan.decision is ContentPolicyDecision.REVIEW:
        normalized = redactReviewableText(normalized)
    return normalized


def _awareUtc(value: datetime, fieldName: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FactoryValidationError(
            FactoryErrorCode.INVALID_SOURCE,
            f"{fieldName} must include a timezone.",
        )
    return value.astimezone(UTC)


def _validatedOwner(value: str) -> str:
    normalized = value.strip()
    if not _SAFE_IDENTIFIER_PATTERN.fullmatch(normalized):
        raise FactoryValidationError(
            FactoryErrorCode.INVALID_SOURCE,
            "ownerUserId is invalid.",
        )
    return normalized


def _validatedId(value: str, fieldName: str) -> str:
    normalized = value.strip()
    if not 8 <= len(normalized) <= 80 or not _SAFE_IDENTIFIER_PATTERN.fullmatch(normalized):
        raise FactoryValidationError(
            FactoryErrorCode.INVALID_SOURCE,
            f"{fieldName} is invalid.",
        )
    return normalized


def _validatedRevision(value: int) -> int:
    if isinstance(value, bool) or value < 0:
        raise FactoryValidationError(
            FactoryErrorCode.INVALID_SOURCE,
            "expectedRevision must be a non-negative integer.",
        )
    return value
