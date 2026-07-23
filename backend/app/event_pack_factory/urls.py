"""Reader 与搜索结果共用的公共 HTTPS URL 边界。"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import SplitResult, urlsplit, urlunsplit

from backend.app.event_pack_factory.errors import (
    FactoryErrorCode,
    FactoryValidationError,
)

MAX_PUBLIC_URL_LENGTH = 2_000
_BLOCKED_HOST_SUFFIXES = (
    ".internal",
    ".invalid",
    ".local",
    ".localhost",
    ".home.arpa",
)
_HOST_PATTERN = re.compile(
    r"(?=.{1,253}\.?$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.?"
)


def normalizePublicHttpsUrl(value: str) -> str:
    """规范化公共 HTTPS URL，并拒绝典型 SSRF 目标。

    本函数不执行网络请求。若未来加入服务端抓取器，抓取器还必须在连接时解析 DNS、
    校验全部 A/AAAA 地址并固定已校验地址，以抵御 DNS rebinding。
    """

    candidate = value.strip()
    if not candidate or len(candidate) > MAX_PUBLIC_URL_LENGTH:
        raise _invalidUrl()
    try:
        parsed = urlsplit(candidate)
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise _invalidUrl() from error
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise _invalidUrl()

    normalizedHost = _normalizePublicHost(host)
    address = _asIpAddress(normalizedHost)
    renderedHost = (
        f"[{normalizedHost}]" if address is not None and address.version == 6 else normalizedHost
    )
    netloc = renderedHost if port is None else f"{renderedHost}:443"
    normalized = SplitResult(
        scheme="https",
        netloc=netloc,
        path=parsed.path or "/",
        query=parsed.query,
        fragment="",
    )
    return urlunsplit(normalized)


def normalizeDomainFilter(value: str) -> str:
    candidate = value.strip().rstrip(".")
    if not candidate or any(character in candidate for character in "/:@?#"):
        raise FactoryValidationError(
            FactoryErrorCode.INVALID_SEARCH_REQUEST,
            "domainFilter must be a bare public DNS hostname.",
        )
    try:
        return _normalizePublicHost(candidate)
    except FactoryValidationError as error:
        raise FactoryValidationError(
            FactoryErrorCode.INVALID_SEARCH_REQUEST,
            "domainFilter must be a bare public DNS hostname.",
        ) from error


def _normalizePublicHost(host: str) -> str:
    directAddress = _asIpAddress(host.rstrip("."))
    if directAddress is not None:
        if not directAddress.is_global:
            raise _invalidUrl()
        return directAddress.compressed
    try:
        normalized = host.rstrip(".").encode("idna").decode("ascii").casefold()
    except UnicodeError as error:
        raise _invalidUrl() from error
    if not _HOST_PATTERN.fullmatch(normalized):
        raise _invalidUrl()
    if normalized == "localhost" or normalized.endswith(_BLOCKED_HOST_SUFFIXES):
        raise _invalidUrl()
    if all(label.isdecimal() for label in normalized.split(".")):
        # 拒绝 127.1、0177.0.0.1 等不同网络栈可能按 IPv4 解释的歧义写法。
        raise _invalidUrl()
    # 单标签主机名通常依赖本地 DNS 搜索域，不属于可验证的公共 URL。
    if "." not in normalized:
        raise _invalidUrl()
    return normalized


def _asIpAddress(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _invalidUrl() -> FactoryValidationError:
    return FactoryValidationError(
        FactoryErrorCode.READER_SOURCE_NOT_ALLOWED,
        "Only credential-free public HTTPS URLs on port 443 are allowed.",
    )
