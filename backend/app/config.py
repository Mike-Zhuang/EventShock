"""运行时配置；仅从受信任的进程环境读取，不接受 HTTP 文件路径。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    projectRoot: Path
    dataDir: Path
    databasePath: Path
    frontendDist: Path
    appEnv: str
    releaseCommit: str

    @property
    def production(self) -> bool:
        return self.appEnv.lower() == "production"


def loadSettings(dataDir: Path | None = None) -> Settings:
    projectRoot = Path(__file__).resolve().parents[2]
    configuredDataDir = dataDir or Path(
        os.environ.get("EVENTSHOCK_DATA_DIR", projectRoot / ".eventshock-data")
    )
    resolvedDataDir = configuredDataDir.expanduser().resolve()
    return Settings(
        projectRoot=projectRoot,
        dataDir=resolvedDataDir,
        databasePath=resolvedDataDir / "eventshock.db",
        frontendDist=projectRoot / "frontend" / "dist",
        appEnv=os.environ.get("APP_ENV", "development"),
        releaseCommit=os.environ.get("EVENTSHOCK_RELEASE_COMMIT", "development")[:64],
    )
