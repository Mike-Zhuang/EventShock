"""智谱官方 Reader 固定端点客户端。

客户端只接受经过本应用静态边界校验的公网 HTTPS URL；它调用固定的智谱官方
Reader 端点且本身不跟随该端点的重定向，也不重试可能计费的请求。目标网页实际
抓取、DNS 解析和网页重定向由供应商完成，不能误称为已被本应用完整验证。异常对象
不会包含 API Key、供应商响应正文或抓取正文。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.event_pack_factory.errors import (
    FactoryErrorCode,
    FactoryReaderError,
    FactoryValidationError,
)
from backend.app.event_pack_factory.models import (
    ReaderBillingStatus,
    ReaderCapabilityDescriptor,
)
from backend.app.event_pack_factory.urls import normalizePublicHttpsUrl

ZHIPU_READER_URL = "https://open.bigmodel.cn/api/paas/v4/reader"
MAX_READER_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_READER_TEXT_CHARACTERS = 100_000

READER_CAPABILITY = ReaderCapabilityDescriptor(
    endpoint=ZHIPU_READER_URL,
    billingStatus=ReaderBillingStatus.UNKNOWN,
    pricingNote=(
        "Reader pricing is not asserted by EventShock Lab. "
        "Confirm current billing in the Zhipu console before use."
    ),
)


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _ProviderReaderResult(_ProviderModel):
    content: str = Field(min_length=1, max_length=MAX_READER_TEXT_CHARACTERS)
    description: str = Field(default="", max_length=8_000)
    title: str = Field(default="", max_length=4_000)
    url: str = Field(default="", max_length=4_000)


class _ProviderReaderResponse(_ProviderModel):
    id: str = Field(default="", max_length=256)
    created: int = Field(ge=0, le=4_102_444_800)
    request_id: str = Field(min_length=1, max_length=256)
    model: str = Field(default="", max_length=256)
    reader_result: _ProviderReaderResult


@dataclass(frozen=True, slots=True)
class _ReaderFetchResult:
    """仅供 Factory 服务层消费，不能作为 HTTP 响应模型使用。"""

    rawText: str = field(repr=False)
    providerRequestId: str
    createdAt: datetime


class ZhipuReaderClient:
    """只调用智谱官方 Reader 固定端点的异步客户端。"""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if transport is not None and client is not None:
            raise ValueError("provide transport or client, not both")
        if client is not None and client.follow_redirects:
            raise ValueError("Reader client must not follow redirects")
        self._client = client or httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
        )
        self._ownsClient = client is None

    async def __aenter__(self) -> ZhipuReaderClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._ownsClient:
            await self._client.aclose()

    async def read(self, url: str, *, apiKey: str) -> _ReaderFetchResult:
        normalizedUrl = normalizePublicHttpsUrl(url)
        if not apiKey or apiKey != apiKey.strip() or len(apiKey) > 4_096:
            raise FactoryValidationError(
                FactoryErrorCode.READER_SOURCE_NOT_ALLOWED,
                "A valid in-memory Zhipu API key is required.",
            )

        payload: dict[str, object] = {
            "url": normalizedUrl,
            "return_format": "text",
            "retain_images": False,
            "keep_img_data_url": False,
            "with_images_summary": False,
        }
        headers = {
            "Authorization": f"Bearer {apiKey}",
            "Content-Type": "application/json",
        }
        try:
            body = await self._postBounded(payload, headers)
        except httpx.TimeoutException:
            raise FactoryReaderError(
                FactoryErrorCode.READER_PROVIDER_UNAVAILABLE,
                "The Reader provider timed out.",
                statusCode=504,
            ) from None
        except httpx.TransportError:
            raise FactoryReaderError(
                FactoryErrorCode.READER_PROVIDER_UNAVAILABLE,
                "The Reader provider could not be reached.",
                statusCode=502,
            ) from None

        parsed = self._parseProviderResponse(body)
        return _ReaderFetchResult(
            rawText=parsed.reader_result.content,
            providerRequestId=parsed.request_id,
            createdAt=datetime.fromtimestamp(parsed.created, tz=UTC),
        )

    async def _postBounded(
        self,
        payload: dict[str, object],
        headers: dict[str, str],
    ) -> bytes:
        timeout = httpx.Timeout(connect=5.0, read=45.0, write=10.0, pool=5.0)
        async with self._client.stream(
            "POST",
            ZHIPU_READER_URL,
            json=payload,
            headers=headers,
            timeout=timeout,
        ) as response:
            self._raiseForStatus(response.status_code)
            chunks: list[bytes] = []
            totalBytes = 0
            async for chunk in response.aiter_bytes():
                totalBytes += len(chunk)
                if totalBytes > MAX_READER_RESPONSE_BYTES:
                    raise FactoryReaderError(
                        FactoryErrorCode.READER_RESPONSE_INVALID,
                        "The Reader provider response exceeded the safe size limit.",
                        statusCode=502,
                    )
                chunks.append(chunk)
            return b"".join(chunks)

    @staticmethod
    def _raiseForStatus(statusCode: int) -> None:
        if statusCode in {401, 403}:
            raise FactoryReaderError(
                FactoryErrorCode.READER_AUTHENTICATION_FAILED,
                "The Reader provider rejected the API credentials.",
                statusCode=401,
            )
        if statusCode == 429:
            raise FactoryReaderError(
                FactoryErrorCode.READER_RATE_LIMITED,
                "The Reader provider rate limit was reached.",
                statusCode=429,
            )
        if statusCode >= 500:
            raise FactoryReaderError(
                FactoryErrorCode.READER_PROVIDER_UNAVAILABLE,
                "The Reader provider is temporarily unavailable.",
                statusCode=502,
            )
        if statusCode < 200 or statusCode >= 300:
            raise FactoryReaderError(
                FactoryErrorCode.READER_REQUEST_FAILED,
                "The Reader provider rejected the request.",
                statusCode=502,
            )

    @staticmethod
    def _parseProviderResponse(body: bytes) -> _ProviderReaderResponse:
        try:
            decoded: Any = json.loads(body)
            if not isinstance(decoded, dict) or "error" in decoded:
                raise ValueError("provider error envelope")
            return _ProviderReaderResponse.model_validate(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
            raise FactoryReaderError(
                FactoryErrorCode.READER_RESPONSE_INVALID,
                "The Reader provider returned an invalid response.",
                statusCode=502,
            ) from None
