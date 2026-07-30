"""部署证据的只读、最小披露视图。"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_STATUS_FILE_BYTES = 32 * 1024
COMMIT_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
SAFE_CODE_PATTERN = re.compile(r"^[A-Z0-9_:-]{1,80}$")
SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 ._:/()-]{1,120}$")
ALLOWED_DOCUMENT_KEYS = {
    "branch",
    "deployedCommit",
    "githubMainCommit",
    "lastDeployAt",
    "lastFailureAt",
    "lastFailureCode",
    "lastSyncAt",
    "lastSyncResult",
    "observedAt",
    "requiredChecks",
}
ALLOWED_CHECK_KEYS = {"completedAt", "name", "status"}
ALLOWED_CHECK_STATUSES = {"PASS", "FAIL", "PENDING", "UNKNOWN"}
ALLOWED_SYNC_RESULTS = {"SUCCEEDED", "FAILED", "PENDING", "NOT_RUN", "UNKNOWN"}
LEGACY_STATE_KEYS = {"branch", "commit", "deployedAt"}
REQUIRED_CHECK_NAMES = {
    "Backend / Python 3.12.13",
    "Frontend / Node 22",
    "Production container",
}


def deploymentStatusSnapshot(
    *,
    releaseCommit: str,
    statusPath: Path | None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """读取受限状态摘要；任何异常都返回 fail-closed 状态而不泄露文件内容。"""

    observedAt = _utcNow(clock).isoformat()
    base = {
        "schemaVersion": "1.0.0",
        "deployedCommit": _safeCommit(releaseCommit, field="releaseCommit"),
        "healthCommit": _safeCommit(releaseCommit, field="releaseCommit"),
        "reportedDeployedCommit": None,
        "githubMainCommit": None,
        "branch": None,
        "commitAlignment": "HEALTH_ONLY",
        "requiredChecks": [],
        "requiredChecksStatus": "UNKNOWN",
        "lastSyncAt": None,
        "lastSyncResult": "UNKNOWN",
        "lastDeployAt": None,
        "lastFailureAt": None,
        "lastFailureCode": None,
        "evidenceObservedAt": None,
        "statusSource": "RELEASE_ENVIRONMENT_ONLY",
        "statusFileState": "NOT_CONFIGURED",
        "statusErrorCode": None,
        "observedAt": observedAt,
    }
    if statusPath is None:
        return base

    try:
        document = _readRestrictedStatusFile(statusPath)
        payload = _normalizeStatusDocument(document)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return {
            **base,
            "statusSource": "RESTRICTED_STATUS_FILE",
            "statusFileState": "INVALID_FAIL_CLOSED",
            "statusErrorCode": "DEPLOYMENT_STATUS_FILE_INVALID",
        }

    reportedCommit = payload.get("deployedCommit")
    mainCommit = payload.get("githubMainCommit")
    checks = payload.get("requiredChecks", [])
    return {
        **base,
        **payload,
        "reportedDeployedCommit": reportedCommit,
        # 健康端点的进程环境是当前运行版本的权威来源，状态文件只能补充比较证据。
        "deployedCommit": base["deployedCommit"],
        "healthCommit": base["healthCommit"],
        "commitAlignment": _commitAlignment(
            healthCommit=base["healthCommit"],
            reportedCommit=reportedCommit,
            mainCommit=mainCommit,
        ),
        "requiredChecksStatus": _requiredChecksStatus(checks),
        "statusSource": "RESTRICTED_STATUS_FILE",
        "statusFileState": "VERIFIED",
        "statusErrorCode": None,
        "observedAt": observedAt,
    }


def _readRestrictedStatusFile(path: Path) -> Mapping[str, Any]:
    if not path.is_absolute():
        raise ValueError("deployment status path must be absolute")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        fileStat = os.fstat(descriptor)
        if not stat.S_ISREG(fileStat.st_mode):
            raise ValueError("deployment status must be a regular non-symlink file")
        if fileStat.st_uid not in {0, os.geteuid()}:
            raise ValueError("deployment status has an untrusted owner")
        if fileStat.st_mode & 0o022:
            raise ValueError("deployment status must not be group- or world-writable")
        if fileStat.st_size > MAX_STATUS_FILE_BYTES:
            raise ValueError("deployment status file is too large")
        with os.fdopen(descriptor, "rb") as statusFile:
            descriptor = -1
            rawContent = statusFile.read(MAX_STATUS_FILE_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(rawContent) > MAX_STATUS_FILE_BYTES:
        raise ValueError("deployment status file is too large")
    text = rawContent.decode("utf-8")
    if "\x00" in text:
        raise ValueError("deployment status contains NUL")
    if path.suffix.casefold() == ".json" or text.lstrip().startswith("{"):
        document = json.loads(text)
        if not isinstance(document, Mapping):
            raise ValueError("deployment status JSON must be an object")
        return document
    return _parseLegacyState(text)


def _parseLegacyState(text: str) -> dict[str, Any]:
    values: dict[str, str] = {}
    for rawLine in text.splitlines():
        if not rawLine:
            continue
        key, separator, value = rawLine.partition("=")
        if separator != "=" or key not in LEGACY_STATE_KEYS or key in values:
            raise ValueError("legacy deployment status contains an invalid field")
        values[key] = value
    if "commit" not in values:
        raise ValueError("legacy deployment status is missing commit")
    return {
        "branch": values.get("branch"),
        "deployedCommit": values["commit"],
        "lastDeployAt": values.get("deployedAt"),
        "lastSyncAt": values.get("deployedAt"),
        "lastSyncResult": "SUCCEEDED",
        "requiredChecks": [],
    }


def _normalizeStatusDocument(document: Mapping[str, Any]) -> dict[str, Any]:
    unknownKeys = set(document) - ALLOWED_DOCUMENT_KEYS
    if unknownKeys:
        raise ValueError("deployment status contains fields outside the allowlist")
    checksValue = document.get("requiredChecks", [])
    if not isinstance(checksValue, list) or len(checksValue) > 20:
        raise ValueError("requiredChecks must be a bounded list")
    checks = [_normalizeCheck(item) for item in checksValue]
    checkNames = [item["name"] for item in checks]
    if len(checkNames) != len(set(checkNames)):
        raise ValueError("requiredChecks names must be unique")
    result: dict[str, Any] = {
        "reportedDeployedCommit": None,
        "githubMainCommit": _optionalCommit(document.get("githubMainCommit")),
        "branch": _optionalSafeName(document.get("branch")),
        "requiredChecks": checks,
        "lastSyncAt": _optionalTimestamp(document.get("lastSyncAt")),
        "lastSyncResult": _enumValue(
            document.get("lastSyncResult", "UNKNOWN"),
            ALLOWED_SYNC_RESULTS,
            field="lastSyncResult",
        ),
        "lastDeployAt": _optionalTimestamp(document.get("lastDeployAt")),
        "lastFailureAt": _optionalTimestamp(document.get("lastFailureAt")),
        "lastFailureCode": _optionalSafeCode(document.get("lastFailureCode")),
        "evidenceObservedAt": _optionalTimestamp(document.get("observedAt")),
    }
    deployedCommit = document.get("deployedCommit")
    if deployedCommit is not None:
        result["deployedCommit"] = _safeCommit(deployedCommit, field="deployedCommit")
    return result


def _normalizeCheck(value: Any) -> dict[str, str | None]:
    if not isinstance(value, Mapping) or set(value) - ALLOWED_CHECK_KEYS:
        raise ValueError("required check contains fields outside the allowlist")
    return {
        "name": _safeName(value.get("name"), field="requiredChecks.name"),
        "status": _enumValue(
            value.get("status"),
            ALLOWED_CHECK_STATUSES,
            field="requiredChecks.status",
        ),
        "completedAt": _optionalTimestamp(value.get("completedAt")),
    }


def _requiredChecksStatus(checks: list[dict[str, Any]]) -> str:
    statuses = {item["status"] for item in checks}
    if not statuses:
        return "UNKNOWN"
    if "FAIL" in statuses:
        return "FAIL"
    if not REQUIRED_CHECK_NAMES.issubset({str(item["name"]) for item in checks}):
        return "INCOMPLETE"
    if statuses <= {"PASS"}:
        return "PASS"
    return "PENDING"


def _commitAlignment(
    *,
    healthCommit: str,
    reportedCommit: str | None,
    mainCommit: str | None,
) -> str:
    if reportedCommit is not None and reportedCommit != healthCommit:
        return "STATUS_FILE_MISMATCH"
    if mainCommit is None:
        return "HEALTH_MATCH" if reportedCommit is not None else "HEALTH_ONLY"
    return "MATCH" if mainCommit == healthCommit else "MAIN_MISMATCH"


def _safeCommit(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not COMMIT_PATTERN.fullmatch(value):
        raise ValueError(f"{field} is invalid")
    return value


def _optionalCommit(value: Any) -> str | None:
    return None if value is None else _safeCommit(value, field="commit")


def _safeName(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME_PATTERN.fullmatch(value):
        raise ValueError(f"{field} is invalid")
    return value


def _optionalSafeName(value: Any) -> str | None:
    return None if value is None else _safeName(value, field="branch")


def _optionalSafeCode(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not SAFE_CODE_PATTERN.fullmatch(value):
        raise ValueError("lastFailureCode is invalid")
    return value


def _enumValue(value: Any, allowed: set[str], *, field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{field} is invalid")
    return value


def _optionalTimestamp(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("deployment timestamp is invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("deployment timestamp must include a timezone")
    return parsed.astimezone(UTC).isoformat()


def _utcNow(clock: Callable[[], datetime] | None) -> datetime:
    now = clock() if clock is not None else datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("deployment status clock must return a timezone-aware datetime")
    return now.astimezone(UTC)
