"""运行时配置；仅从受信任的进程环境读取，不接受 HTTP 文件路径。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    projectRoot: Path
    dataDir: Path
    databasePath: Path
    frontendDist: Path
    appEnv: str
    releaseCommit: str
    deploymentStatusPath: Path | None
    authenticationRequired: bool
    authCookieSecure: bool
    authSecret: str | None = field(repr=False)
    adminEmail: str | None = None
    smtpHost: str | None = None
    smtpPort: int = 465
    smtpUsername: str | None = None
    smtpPassword: str | None = field(default=None, repr=False)
    smtpSender: str | None = None

    @property
    def production(self) -> bool:
        return self.appEnv.lower() == "production"


def loadSettings(dataDir: Path | None = None) -> Settings:
    projectRoot = Path(__file__).resolve().parents[2]
    appEnv = os.environ.get("APP_ENV", "development")
    production = appEnv.lower() == "production"
    configuredDataDir = dataDir or Path(
        os.environ.get("EVENTSHOCK_DATA_DIR", projectRoot / ".eventshock-data")
    )
    resolvedDataDir = configuredDataDir.expanduser().resolve()
    return Settings(
        projectRoot=projectRoot,
        dataDir=resolvedDataDir,
        databasePath=resolvedDataDir / "eventshock.db",
        frontendDist=projectRoot / "frontend" / "dist",
        appEnv=appEnv,
        releaseCommit=os.environ.get("EVENTSHOCK_RELEASE_COMMIT", "development")[:64],
        deploymentStatusPath=_optionalPath("EVENTSHOCK_DEPLOYMENT_STATUS_FILE"),
        # 正式环境不可通过误配关闭登录或 Secure Cookie；开关只服务本地测试。
        authenticationRequired=production
        or _environmentFlag("EVENTSHOCK_AUTH_REQUIRED", default=False),
        authCookieSecure=production
        or _environmentFlag("EVENTSHOCK_AUTH_COOKIE_SECURE", default=False),
        authSecret=_secretValue("EVENTSHOCK_AUTH_SECRET", "EVENTSHOCK_AUTH_SECRET_FILE"),
        adminEmail=os.environ.get("EVENTSHOCK_ADMIN_EMAIL"),
        smtpHost=os.environ.get("EVENTSHOCK_SMTP_HOST"),
        smtpPort=int(os.environ.get("EVENTSHOCK_SMTP_PORT", "465")),
        smtpUsername=os.environ.get("EVENTSHOCK_SMTP_USERNAME"),
        smtpPassword=_secretValue(
            "EVENTSHOCK_SMTP_PASSWORD",
            "EVENTSHOCK_SMTP_PASSWORD_FILE",
        ),
        smtpSender=os.environ.get("EVENTSHOCK_SMTP_SENDER"),
    )


def _environmentFlag(name: str, *, default: bool) -> bool:
    rawValue = os.environ.get(name)
    if rawValue is None:
        return default
    normalized = rawValue.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _optionalPath(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def _secretValue(valueName: str, fileName: str) -> str | None:
    """优先读取受限文件；环境变量仅用于本地开发兼容。"""

    secretPath = os.environ.get(fileName)
    if secretPath:
        path = Path(secretPath).expanduser()
        if not path.is_file():
            return None
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
        return value or None
    value = os.environ.get(valueName)
    return value if value else None
