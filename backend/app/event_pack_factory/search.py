"""智谱 Web Search API 的固定端点客户端。

网络搜索是候选来源发现工具，不是事实裁判。客户端不保留 API Key，不自动重试可能
计费的请求，也不把供应商响应正文写入错误对象。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.event_pack_factory.errors import (
    EventPackFactoryError,
    FactoryErrorCode,
    FactorySearchError,
    FactoryValidationError,
)
from backend.app.event_pack_factory.models import (
    SearchEngine,
    SearchEngineDescriptor,
    WebSearchRequest,
    WebSearchResponse,
    WebSearchResult,
)
from backend.app.event_pack_factory.urls import (
    normalizeDomainFilter,
    normalizePublicHttpsUrl,
)

ZHIPU_WEB_SEARCH_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"
MAX_SEARCH_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_SEARCH_RESULT_TEXT = 12_000
MAX_SEARCH_RESULTS = 50

SEARCH_ENGINE_CATALOG: dict[SearchEngine, SearchEngineDescriptor] = {
    SearchEngine.STANDARD: SearchEngineDescriptor(
        engine=SearchEngine.STANDARD,
        displayName="Zhipu Standard Search",
        priceCnyPerCall=0.01,
        supportsCount=True,
        supportsDomainFilter=True,
        supportsRecencyFilter=True,
        supportsContentSize=True,
    ),
    SearchEngine.PRO: SearchEngineDescriptor(
        engine=SearchEngine.PRO,
        displayName="Zhipu Pro Search",
        priceCnyPerCall=0.03,
        supportsCount=True,
        supportsDomainFilter=True,
        supportsRecencyFilter=True,
        supportsContentSize=True,
    ),
    SearchEngine.SOGOU: SearchEngineDescriptor(
        engine=SearchEngine.SOGOU,
        displayName="Sogou Search via Zhipu",
        priceCnyPerCall=0.05,
        supportsCount=True,
        supportedCounts=(10, 20, 30, 40, 50),
        supportsDomainFilter=True,
        supportsRecencyFilter=True,
        supportsContentSize=True,
    ),
    SearchEngine.QUARK: SearchEngineDescriptor(
        engine=SearchEngine.QUARK,
        displayName="Quark Search via Zhipu",
        priceCnyPerCall=0.05,
        supportsCount=False,
        supportsDomainFilter=False,
        supportsRecencyFilter=True,
        supportsContentSize=True,
    ),
}


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _ProviderSearchResult(_ProviderModel):
    title: str = Field(default="", max_length=4_000)
    content: str = Field(default="", max_length=100_000)
    link: str = Field(default="", max_length=4_000)
    media: str = Field(default="", max_length=1_000)
    publish_date: str = Field(default="", max_length=200)


class _ProviderSearchResponse(_ProviderModel):
    id: str = Field(default="", max_length=256)
    created: int = Field(ge=0, le=4_102_444_800)
    request_id: str = Field(min_length=1, max_length=256)
    search_result: list[_ProviderSearchResult] = Field(
        default_factory=list,
        max_length=MAX_SEARCH_RESULTS,
    )


class ZhipuWebSearchClient:
    """只调用智谱官方 Web Search 固定端点的异步客户端。"""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if transport is not None and client is not None:
            raise ValueError("provide transport or client, not both")
        if client is not None and client.follow_redirects:
            raise ValueError("Web Search client must not follow redirects")
        self._client = client or httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
        )
        self._ownsClient = client is None

    async def __aenter__(self) -> ZhipuWebSearchClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._ownsClient:
            await self._client.aclose()

    async def search(
        self,
        request: WebSearchRequest,
        *,
        apiKey: str,
        requestId: str,
        userId: str,
    ) -> WebSearchResponse:
        payload = validateAndBuildSearchPayload(
            request,
            requestId=requestId,
            userId=userId,
        )
        if not apiKey or apiKey != apiKey.strip() or len(apiKey) > 4_096:
            raise FactoryValidationError(
                FactoryErrorCode.INVALID_SEARCH_REQUEST,
                "A valid in-memory Zhipu API key is required.",
            )

        headers = {
            "Authorization": f"Bearer {apiKey}",
            "Content-Type": "application/json",
        }
        try:
            body = await self._postBounded(payload, headers)
        except httpx.TimeoutException:
            raise FactorySearchError(
                FactoryErrorCode.SEARCH_PROVIDER_UNAVAILABLE,
                "The search provider timed out.",
                statusCode=504,
            ) from None
        except httpx.TransportError:
            raise FactorySearchError(
                FactoryErrorCode.SEARCH_PROVIDER_UNAVAILABLE,
                "The search provider could not be reached.",
                statusCode=502,
            ) from None

        parsed = self._parseProviderResponse(body)
        results: list[WebSearchResult] = []
        droppedResultCount = 0
        for item in parsed.search_result:
            try:
                normalizedUrl = normalizePublicHttpsUrl(item.link)
            except EventPackFactoryError:
                droppedResultCount += 1
                continue
            title = _boundedText(item.title, 300)
            content = _boundedText(item.content, MAX_SEARCH_RESULT_TEXT)
            if not title or not content:
                droppedResultCount += 1
                continue
            results.append(
                WebSearchResult(
                    title=title,
                    content=content,
                    url=normalizedUrl,
                    publisher=_boundedText(item.media, 200) or _publisherFromUrl(normalizedUrl),
                    publishedAt=_parsePublishedAt(item.publish_date),
                )
            )

        createdAt = datetime.fromtimestamp(parsed.created, tz=UTC)
        descriptor = SEARCH_ENGINE_CATALOG[request.engine]
        return WebSearchResponse(
            providerRequestId=parsed.request_id,
            createdAt=createdAt,
            engine=request.engine,
            estimatedCostCny=descriptor.priceCnyPerCall,
            results=tuple(results),
            droppedResultCount=droppedResultCount,
        )

    async def _postBounded(
        self,
        payload: dict[str, object],
        headers: dict[str, str],
    ) -> bytes:
        timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
        async with self._client.stream(
            "POST",
            ZHIPU_WEB_SEARCH_URL,
            json=payload,
            headers=headers,
            timeout=timeout,
        ) as response:
            self._raiseForStatus(response.status_code)
            chunks: list[bytes] = []
            totalBytes = 0
            async for chunk in response.aiter_bytes():
                totalBytes += len(chunk)
                if totalBytes > MAX_SEARCH_RESPONSE_BYTES:
                    raise FactorySearchError(
                        FactoryErrorCode.SEARCH_RESPONSE_INVALID,
                        "The search provider response exceeded the safe size limit.",
                        statusCode=502,
                    )
                chunks.append(chunk)
            return b"".join(chunks)

    @staticmethod
    def _raiseForStatus(statusCode: int) -> None:
        if statusCode in {401, 403}:
            raise FactorySearchError(
                FactoryErrorCode.SEARCH_AUTHENTICATION_FAILED,
                "The search provider rejected the API credentials.",
                statusCode=401,
            )
        if statusCode == 429:
            raise FactorySearchError(
                FactoryErrorCode.SEARCH_RATE_LIMITED,
                "The search provider rate limit was reached.",
                statusCode=429,
            )
        if statusCode >= 500:
            raise FactorySearchError(
                FactoryErrorCode.SEARCH_PROVIDER_UNAVAILABLE,
                "The search provider is temporarily unavailable.",
                statusCode=502,
            )
        if statusCode < 200 or statusCode >= 300:
            raise FactorySearchError(
                FactoryErrorCode.SEARCH_REQUEST_FAILED,
                "The search provider rejected the request.",
                statusCode=502,
            )

    @staticmethod
    def _parseProviderResponse(body: bytes) -> _ProviderSearchResponse:
        try:
            decoded: Any = json.loads(body)
            if not isinstance(decoded, dict) or "error" in decoded:
                raise ValueError("provider error envelope")
            return _ProviderSearchResponse.model_validate(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
            # Pydantic/JSON 异常可能保留供应商原始输入，不能挂到可记录的异常因果链。
            raise FactorySearchError(
                FactoryErrorCode.SEARCH_RESPONSE_INVALID,
                "The search provider returned an invalid response.",
                statusCode=502,
            ) from None


def validateAndBuildSearchPayload(
    request: WebSearchRequest,
    *,
    requestId: str,
    userId: str,
) -> dict[str, object]:
    if not 6 <= len(requestId) <= 64:
        raise _invalidSearch("requestId must contain 6 to 64 characters.")
    if not 6 <= len(userId) <= 128:
        raise _invalidSearch("userId must contain 6 to 128 characters.")

    descriptor = SEARCH_ENGINE_CATALOG[request.engine]
    payload: dict[str, object] = {
        "search_query": request.query,
        "search_engine": request.engine.value,
        "search_intent": request.searchIntent,
        "search_recency_filter": request.recency.value,
        "content_size": request.contentSize.value,
        "request_id": requestId,
        "user_id": userId,
    }

    if descriptor.supportsCount:
        if request.count is None:
            raise _invalidSearch("count is required for the selected search engine.")
        if (
            descriptor.supportedCounts is not None
            and request.count not in descriptor.supportedCounts
        ):
            allowed = ", ".join(str(value) for value in descriptor.supportedCounts)
            raise _invalidSearch(f"count must be one of {allowed} for the selected engine.")
        payload["count"] = request.count
    elif request.count is not None:
        raise _invalidSearch("count is not supported by the selected search engine.")

    if request.domainFilter is not None:
        if not descriptor.supportsDomainFilter:
            raise _invalidSearch("domainFilter is not supported by the selected search engine.")
        payload["search_domain_filter"] = normalizeDomainFilter(request.domainFilter)
    return payload


def _invalidSearch(message: str) -> FactoryValidationError:
    return FactoryValidationError(FactoryErrorCode.INVALID_SEARCH_REQUEST, message)


def _boundedText(value: str, maximum: int) -> str:
    return " ".join(value.split())[:maximum].strip()


def _publisherFromUrl(url: str) -> str:
    return url.split("/", 3)[2]


def _parsePublishedAt(value: str) -> datetime | None:
    candidate = value.strip()
    if not candidate:
        return None
    normalized = candidate.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(candidate[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
