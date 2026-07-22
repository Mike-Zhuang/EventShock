from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

import backend.app.main as mainModule
from backend.app.auth import ChallengePurpose
from backend.app.auth.bootstrap_admin import bootstrapAdmin
from backend.app.database import Database
from backend.app.main import createApp

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Administrator password!"
AUTH_SECRET = "integration-auth-secret-with-at-least-thirty-two-bytes"


@dataclass(frozen=True)
class CapturedCode:
    recipient: str
    code: str
    purpose: ChallengePurpose
    locale: str


class CapturingMailer:
    messages: ClassVar[list[CapturedCode]] = []

    def __init__(self, **_kwargs: object) -> None:
        self.messages.clear()

    async def sendVerificationCode(
        self,
        *,
        recipient: str,
        code: str,
        purpose: ChallengePurpose,
        locale: str,
        expiresMinutes: int,
    ) -> None:
        assert expiresMinutes == 10
        self.messages.append(CapturedCode(recipient, code, purpose, locale))


def configureProduction(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "EVENTSHOCK_AUTH_SECRET_FILE",
        "EVENTSHOCK_SMTP_PASSWORD_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EVENTSHOCK_AUTH_SECRET", AUTH_SECRET)
    monkeypatch.setenv("EVENTSHOCK_ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("EVENTSHOCK_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EVENTSHOCK_SMTP_PORT", "465")
    monkeypatch.setenv("EVENTSHOCK_SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("EVENTSHOCK_SMTP_PASSWORD", "test-smtp-password")
    monkeypatch.setenv("EVENTSHOCK_SMTP_SENDER", "sender@example.com")


def bootstrapTestAdmin(dataDir: Path) -> str:
    database = Database(dataDir / "eventshock.db")
    database.initialize()
    database.saveScenario(
        "legacy-scenario",
        "legacy-browser-session",
        "Legacy scenario",
        {"eventPackId": "spacex-synthetic-v1"},
        False,
    )
    with database.connection() as connection:
        connection.execute("UPDATE scenarios SET owner_user_id='' WHERE id='legacy-scenario'")
    userId, created, claimed = bootstrapAdmin(
        database=database,
        adminEmail=ADMIN_EMAIL,
        password=ADMIN_PASSWORD,
    )
    assert created is True
    assert claimed["scenarios"] == 1
    return userId


def test_production_auth_cookie_csrf_owner_migration_and_session_only_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configureProduction(monkeypatch)
    monkeypatch.setattr(mainModule, "SmtpVerificationMailer", CapturingMailer)
    adminId = bootstrapTestAdmin(tmp_path)

    with TestClient(createApp(tmp_path), base_url="https://testserver") as client:
        unauthorized = client.get("/api/v1/cases")
        assert unauthorized.status_code == 401

        wrong = client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": "incorrect", "language": "en"},
        )
        assert wrong.status_code == 401

        login = client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "language": "en"},
        )
        assert login.status_code == 200
        csrfToken = login.json()["csrfToken"]
        cookieHeader = login.headers["set-cookie"]
        assert "HttpOnly" in cookieHeader
        assert "Secure" in cookieHeader
        assert "SameSite=lax" in cookieHeader
        assert login.json()["user"]["id"] == adminId

        refreshed = client.get("/api/v1/auth/session")
        assert refreshed.status_code == 200
        assert refreshed.json()["csrfToken"] == csrfToken

        # 登录账号所有权覆盖客户端伪造的旧匿名 Session-ID。
        scenarios = client.get(
            "/api/v1/scenarios",
            headers={"X-Session-ID": "attacker-session-id"},
        )
        assert [item["id"] for item in scenarios.json()["items"]] == ["legacy-scenario"]

        missingCsrf = client.put(
            "/api/v1/llm/config",
            json={
                "provider": "zhipu",
                "model": "glm-4.5-air",
                "apiKey": "temporary-api-key",
                "thinkingEnabled": False,
                "maxTokens": 2048,
            },
        )
        assert missingCsrf.status_code == 403
        configured = client.put(
            "/api/v1/llm/config",
            headers={"X-CSRF-Token": csrfToken, "Origin": "https://testserver"},
            json={
                "provider": "zhipu",
                "model": "glm-4.5-air",
                "apiKey": "temporary-api-key",
                "thinkingEnabled": False,
                "maxTokens": 2048,
            },
        )
        assert configured.status_code == 200, configured.json()
        assert configured.json()["configured"] is True

        users = client.get("/api/v1/admin/users")
        activity = client.get("/api/v1/admin/activity")
        assert users.status_code == 200
        assert users.json()["total"] == 1
        assert users.json()["items"][0]["email"] == ADMIN_EMAIL
        assert activity.status_code == 200
        assert activity.json()["total"] >= 3

        logout = client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": csrfToken, "Origin": "https://testserver"},
        )
        assert logout.status_code == 204
        relogin = client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "language": "en"},
        )
        assert relogin.status_code == 200
        assert client.get("/api/v1/llm/config").json()["configured"] is False

    assert b"temporary-api-key" not in (tmp_path / "eventshock.db").read_bytes()


def test_email_registration_reset_and_user_data_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configureProduction(monkeypatch)
    monkeypatch.setattr(mainModule, "SmtpVerificationMailer", CapturingMailer)
    bootstrapTestAdmin(tmp_path)
    userEmail = "analyst@example.com"
    userPassword = "Analyst password 123!"
    replacementPassword = "Replacement password 456!"

    with TestClient(createApp(tmp_path), base_url="https://testserver") as client:
        sent = client.post(
            "/api/v1/auth/verification-code",
            json={"email": userEmail, "purpose": "REGISTER", "language": "zh-CN"},
        )
        assert sent.status_code == 202
        registrationCode = CapturingMailer.messages[-1]
        assert registrationCode.locale == "zh-CN"
        registered = client.post(
            "/api/v1/auth/register",
            json={
                "email": userEmail,
                "password": userPassword,
                "verificationCode": registrationCode.code,
                "language": "zh-CN",
            },
        )
        assert registered.status_code == 201
        csrfToken = registered.json()["csrfToken"]
        assert registered.json()["user"]["role"] == "USER"
        assert client.get("/api/v1/scenarios").json()["items"] == []
        adminResponse = client.get("/api/v1/admin/users")
        assert adminResponse.status_code == 403, adminResponse.json()

        client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": csrfToken, "Origin": "https://testserver"},
        )
        resetSent = client.post(
            "/api/v1/auth/verification-code",
            json={
                "email": userEmail,
                "purpose": "RESET_PASSWORD",
                "language": "en",
            },
        )
        assert resetSent.status_code == 202
        resetCode = CapturingMailer.messages[-1]
        reset = client.post(
            "/api/v1/auth/password-reset",
            json={
                "email": userEmail,
                "password": replacementPassword,
                "verificationCode": resetCode.code,
                "language": "en",
            },
        )
        assert reset.status_code == 200
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": userEmail, "password": userPassword, "language": "en"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": userEmail, "password": replacementPassword, "language": "en"},
            ).status_code
            == 200
        )


def test_production_authentication_configuration_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configureProduction(monkeypatch)
    monkeypatch.delenv("EVENTSHOCK_SMTP_PASSWORD")

    with pytest.raises(RuntimeError, match="required settings are missing"):
        with TestClient(createApp(tmp_path), base_url="https://testserver"):
            pass


def test_production_blocks_account_writes_until_admin_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configureProduction(monkeypatch)
    monkeypatch.setattr(mainModule, "SmtpVerificationMailer", CapturingMailer)

    with TestClient(createApp(tmp_path), base_url="https://testserver") as client:
        health = client.get("/api/health")
        session = client.get("/api/v1/auth/session")
        verification = client.post(
            "/api/v1/auth/verification-code",
            json={"email": "user@example.com", "purpose": "REGISTER", "language": "en"},
        )

    assert health.status_code == 200
    assert session.status_code == 200
    assert session.json()["authenticated"] is False
    assert verification.status_code == 503
    assert verification.json()["error"]["code"] == "AUTHENTICATION_INITIALIZING"
    assert CapturingMailer.messages == []


def _interpretationRequestPayload(clientRequestId: str) -> dict[str, object]:
    return {
        "schemaVersion": "1.0.0",
        "conversationId": "auth-rate-limit-conversation",
        "clientRequestId": clientRequestId,
        "mode": "INITIAL",
        "language": "en",
        "reasoningSummaryRequested": False,
        "messages": [{"role": "user", "content": "Explain the saved result."}],
    }


def test_anonymous_requests_cannot_exhaust_authenticated_interpretation_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configureProduction(monkeypatch)
    monkeypatch.setattr(mainModule, "SmtpVerificationMailer", CapturingMailer)
    bootstrapTestAdmin(tmp_path)
    url = "/api/v1/experiments/missing-experiment/interpretation-chat/stream"
    sharedIp = "203.0.113.81"

    with TestClient(createApp(tmp_path), base_url="https://testserver") as client:
        anonymousResponses = [
            client.post(
                url,
                headers={"Origin": "https://testserver", "X-Forwarded-For": sharedIp},
                json=_interpretationRequestPayload(f"anonymous-request-{index:03d}"),
            )
            for index in range(12)
        ]
        login = client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "language": "en"},
        )
        authenticated = client.post(
            url,
            headers={
                "Origin": "https://testserver",
                "X-CSRF-Token": login.json()["csrfToken"],
                "X-Forwarded-For": sharedIp,
            },
            json=_interpretationRequestPayload("authenticated-request-001"),
        )

    assert [response.status_code for response in anonymousResponses] == [401] * 12
    assert login.status_code == 200
    assert authenticated.status_code == 404
    assert authenticated.json()["error"]["code"] == "EXPERIMENT_NOT_FOUND"


def test_authenticated_users_on_same_nat_have_independent_interpretation_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configureProduction(monkeypatch)
    monkeypatch.setattr(mainModule, "SmtpVerificationMailer", CapturingMailer)
    bootstrapTestAdmin(tmp_path)
    userEmail = "shared-nat-analyst@example.com"
    userPassword = "Analyst password 123!"
    url = "/api/v1/experiments/missing-experiment/interpretation-chat/stream"
    sharedIp = "203.0.113.82"

    with TestClient(createApp(tmp_path), base_url="https://testserver") as client:
        adminLogin = client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "language": "en"},
        )
        assert adminLogin.status_code == 200
        adminCsrf = adminLogin.json()["csrfToken"]
        adminToken = client.cookies.get(mainModule.AUTH_COOKIE_NAME)
        assert adminToken

        codeResponse = client.post(
            "/api/v1/auth/verification-code",
            json={"email": userEmail, "purpose": "REGISTER", "language": "en"},
        )
        assert codeResponse.status_code == 202
        registered = client.post(
            "/api/v1/auth/register",
            json={
                "email": userEmail,
                "password": userPassword,
                "verificationCode": CapturingMailer.messages[-1].code,
                "language": "en",
            },
        )
        assert registered.status_code == 201
        userCsrf = registered.json()["csrfToken"]
        userToken = client.cookies.get(mainModule.AUTH_COOKIE_NAME)
        assert userToken
        assert userToken != adminToken

        client.cookies.clear()
        client.cookies.set(mainModule.AUTH_COOKIE_NAME, adminToken)
        adminResponses = [
            client.post(
                url,
                headers={
                    "Origin": "https://testserver",
                    "X-CSRF-Token": adminCsrf,
                    "X-Forwarded-For": sharedIp,
                },
                json=_interpretationRequestPayload(f"admin-request-{index:03d}"),
            )
            for index in range(8)
        ]

        client.cookies.clear()
        client.cookies.set(mainModule.AUTH_COOKIE_NAME, userToken)
        userResponse = client.post(
            url,
            headers={
                "Origin": "https://testserver",
                "X-CSRF-Token": userCsrf,
                "X-Forwarded-For": sharedIp,
            },
            json=_interpretationRequestPayload("user-request-001"),
        )

    assert [response.status_code for response in adminResponses] == [404] * 8
    assert userResponse.status_code == 404
    assert userResponse.json()["error"]["code"] == "EXPERIMENT_NOT_FOUND"
