"""基于标准库 scrypt 的版本化密码哈希。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

SCRYPT_VERSION = 1
SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_KEY_LENGTH = 32
SCRYPT_SALT_LENGTH = 16
MINIMUM_PASSWORD_LENGTH = 8
MAXIMUM_PASSWORD_LENGTH = 128
COMMON_PASSWORDS = frozenset(
    {
        "12345678",
        "123456789",
        "1234567890",
        "admin123",
        "iloveyou",
        "letmein123",
        "password",
        "password1",
        "password123",
        "qwerty123",
        "welcome1",
    }
)


class PasswordPolicyError(ValueError):
    pass


def _identityFragments(identity: str | None) -> frozenset[str]:
    if not identity:
        return frozenset()
    localPart = identity.partition("@")[0].casefold()
    candidates = {localPart, *re.split(r"[._+\-]+", localPart)}
    return frozenset(
        re.sub(r"[^a-z0-9]", "", candidate)
        for candidate in candidates
        if len(re.sub(r"[^a-z0-9]", "", candidate)) >= 3
    )


def validatePassword(password: str, *, identity: str | None = None) -> None:
    """允许长口令短语，同时拒绝最常见、重复和顺序型弱口令。"""

    if not isinstance(password, str):
        raise PasswordPolicyError("password must be a string")
    if not MINIMUM_PASSWORD_LENGTH <= len(password) <= MAXIMUM_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"password must contain {MINIMUM_PASSWORD_LENGTH} to "
            f"{MAXIMUM_PASSWORD_LENGTH} characters"
        )
    if len(password.encode("utf-8")) > 512:
        raise PasswordPolicyError("password UTF-8 representation is too large")
    normalized = password.casefold().strip()
    if normalized in COMMON_PASSWORDS:
        raise PasswordPolicyError("password is too common; choose a less predictable password")
    if len(set(normalized)) <= 2:
        raise PasswordPolicyError("password contains too little variation")
    normalizedAlphanumeric = re.sub(r"[^a-z0-9]", "", normalized)
    if any(fragment in normalizedAlphanumeric for fragment in _identityFragments(identity)):
        raise PasswordPolicyError("password must not contain the account email name")
    if (
        normalized in "0123456789abcdefghijklmnopqrstuvwxyz"
        or normalized in ("0123456789abcdefghijklmnopqrstuvwxyz"[::-1])
    ):
        raise PasswordPolicyError("password must not be a simple sequence")


def hashPassword(password: str, *, identity: str | None = None) -> str:
    validatePassword(password, identity=identity)
    return _hashValidatedPassword(password)


def _hashValidatedPassword(password: str) -> str:
    salt = secrets.token_bytes(SCRYPT_SALT_LENGTH)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_KEY_LENGTH,
    )
    return "$".join(
        (
            "scrypt",
            f"v={SCRYPT_VERSION}",
            f"n={SCRYPT_N}",
            f"r={SCRYPT_R}",
            f"p={SCRYPT_P}",
            _encode(salt),
            _encode(derived),
        )
    )


def verifyPassword(password: str, encodedHash: str) -> bool:
    """解析参数前先限制到当前受信任配置，避免恶意哈希触发资源耗尽。"""

    try:
        if not isinstance(password, str) or len(password.encode("utf-8")) > 512:
            return False
        parts = encodedHash.split("$")
        if len(parts) != 7 or parts[0] != "scrypt":
            return False
        version = int(parts[1].removeprefix("v="))
        n = int(parts[2].removeprefix("n="))
        r = int(parts[3].removeprefix("r="))
        p = int(parts[4].removeprefix("p="))
        if (version, n, r, p) != (SCRYPT_VERSION, SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        salt = _decode(parts[5])
        expected = _decode(parts[6])
        if len(salt) != SCRYPT_SALT_LENGTH or len(expected) != SCRYPT_KEY_LENGTH:
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (TypeError, ValueError, UnicodeEncodeError):
        return False
    return hmac.compare_digest(candidate, expected)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)
