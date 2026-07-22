from starlette.requests import Request

from backend.app.main import _clientIp


def _request(
    peer: str,
    *,
    realIp: str | None = None,
    forwardedFor: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if realIp is not None:
        headers.append((b"x-real-ip", realIp.encode()))
    if forwardedFor is not None:
        headers.append((b"x-forwarded-for", forwardedFor.encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/api/health",
            "raw_path": b"/api/health",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("eventshock.test", 443),
        }
    )


def test_public_direct_peer_cannot_spoof_forwarding_headers() -> None:
    request = _request(
        "8.8.8.8",
        realIp="1.1.1.1",
        forwardedFor="9.9.9.9",
    )

    assert _clientIp(request) == "8.8.8.8"


def test_trusted_private_proxy_prefers_valid_real_ip() -> None:
    request = _request(
        "172.19.0.5",
        realIp="2001:4860:4860::8888",
        forwardedFor="198.51.100.10, 172.19.0.4",
    )

    assert _clientIp(request) == "2001:4860:4860::8888"


def test_trusted_proxy_uses_rightmost_valid_forwarded_address_as_fallback() -> None:
    request = _request(
        "127.0.0.1",
        realIp="invalid",
        forwardedFor="198.51.100.10, 1.1.1.1",
    )

    assert _clientIp(request) == "1.1.1.1"


def test_non_ip_test_transport_does_not_trust_forwarding_headers() -> None:
    request = _request("testclient", realIp="1.1.1.1")

    assert _clientIp(request) == "testclient"
