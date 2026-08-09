"""从标准输入一次性创建管理员并认领旧匿名记录。"""

from __future__ import annotations

import sys
import uuid

from backend.app.auth.passwords import hashPassword
from backend.app.auth.repository import AuthRepository
from backend.app.auth.service import normalizeEmail
from backend.app.config import loadSettings
from backend.app.database import Database


def bootstrapAdmin(
    *,
    database: Database,
    adminEmail: str,
    password: str,
) -> tuple[str, bool, dict[str, int]]:
    repository = AuthRepository(database)
    repository.initialize()
    normalizedEmail = normalizeEmail(adminEmail)
    user, created = repository.ensureAdmin(
        userId=f"usr-{uuid.uuid4().hex}",
        email=normalizedEmail,
        passwordHash=hashPassword(password, identity=normalizedEmail),
    )
    claimed = database.claimLegacyRecords(user.id)
    if created:
        repository.recordActivity(userId=user.id, action="ADMIN_BOOTSTRAPPED")
    return user.id, created, claimed


def _passwordFromStdin() -> str:
    if sys.stdin.isatty():
        raise RuntimeError("administrator password must be provided through standard input")
    # 只移除管道天然附带的换行，不改变密码本身的其他字符。
    return sys.stdin.read().rstrip("\r\n")


def main() -> int:
    settings = loadSettings()
    if not settings.adminEmail:
        raise RuntimeError("EVENTSHOCK_ADMIN_EMAIL is required")
    database = Database(settings.databasePath)
    database.initialize()
    _userId, created, claimed = bootstrapAdmin(
        database=database,
        adminEmail=settings.adminEmail,
        password=_passwordFromStdin(),
    )
    claimedCount = sum(claimed.values())
    state = "created" if created else "already-present"
    print(f"administrator bootstrap {state}; legacy records claimed: {claimedCount}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
