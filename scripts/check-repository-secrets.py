#!/usr/bin/env python3
"""扫描当前受跟踪文件和 Git 补丁历史中的高风险凭据。

输出只包含规则、文件、行号或提交号，永不回显疑似密钥本身。该工具是提交
门禁，不替代凭据轮换、服务器日志检查或专业 secret scanner。
"""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 2_000_000

_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    (?:
      ["'](?P<quoted_name>
        [a-z][a-z0-9_-]*?
        (?:api[_-]?key|password|passwd|secret|access[_-]?token|refresh[_-]?token)
      )["']
      |
      (?<!["'a-z0-9_:-])(?P<bare_name>
        [a-z][a-z0-9_-]*?
        (?:api[_-]?key|password|passwd|secret|access[_-]?token|refresh[_-]?token)
      )
    )
    \s*[:=]\s*["']
    (?P<value>[^"'\s]{8,})
    ["']
    """
)
_BEARER_PATTERN = re.compile(
    r"""(?ix)\bauthorization\s*[:=]\s*["']bearer\s+(?P<value>[a-z0-9._~+/-]{16,})["']"""
)
_CREDENTIAL_URL_PATTERN = re.compile(
    r"""(?i)\b(?:https?|smtp|postgres(?:ql)?|mysql)://[^/\s:@]+:(?P<value>[^@\s/]{8,})@"""
)
_JWT_PATTERN = re.compile(
    r"\b(?P<value>eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,})\b"
)
_PRIVATE_KEY_MARKER = "-----BEGIN " + "PRIVATE KEY-----"
_ENCRYPTED_PRIVATE_KEY_MARKER = "-----BEGIN ENCRYPTED " + "PRIVATE KEY-----"
_SAFE_VALUE_TOKENS = (
    "change-me",
    "changeme",
    "placeholder",
    "example",
    "dummy",
    "fake",
    "test",
    "validpassword",
    "researchpass",
    "administrator",
    "correcthorse",
    "supersecret",
    "reader-secret",
    "provider-key",
    "integration-auth",
    "ci-",
    "current-password",
    "new-password",
    "${",
    "{{",
    "{",
    "<",
)
_PRIVATE_KEY_FIXTURE_PATHS = (
    "tests/backend/test_content_security.py",
    "tests/backend/test_repository_secret_scan.py",
)


@dataclass(frozen=True, slots=True)
class SecretFinding:
    rule: str
    location: str


def runGit(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def trackedFiles(repository: Path) -> tuple[Path, ...]:
    # 提交前必须同时覆盖已跟踪文件与准备纳入仓库的未跟踪文件；否则新文件
    # 只有提交进入历史后才会首次被扫描，门禁就失去了预防作用。
    output = runGit(
        repository,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
    )
    return tuple(
        repository / value
        for value in output.split("\0")
        if value and not value.startswith(".git/")
    )


def scanText(text: str, *, locationPrefix: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for lineNumber, line in enumerate(text.splitlines(), start=1):
        location = f"{locationPrefix}:{lineNumber}"
        privateKeyFixture = any(
            locationPrefix.startswith(path) or f":{path}:" in locationPrefix
            for path in _PRIVATE_KEY_FIXTURE_PATHS
        )
        if (
            _PRIVATE_KEY_MARKER in line or _ENCRYPTED_PRIVATE_KEY_MARKER in line
        ) and not privateKeyFixture:
            findings.append(SecretFinding("PRIVATE_KEY_MATERIAL", location))
        for rule, pattern in (
            ("PLAINTEXT_CREDENTIAL_ASSIGNMENT", _ASSIGNMENT_PATTERN),
            ("BEARER_TOKEN", _BEARER_PATTERN),
            ("URL_EMBEDDED_CREDENTIAL", _CREDENTIAL_URL_PATTERN),
            ("JWT_TOKEN", _JWT_PATTERN),
        ):
            for match in pattern.finditer(line):
                if (
                    rule == "PLAINTEXT_CREDENTIAL_ASSIGNMENT"
                    and (match.group("quoted_name") or match.group("bare_name") or "").isupper()
                ):
                    continue
                value = match.group("value")
                if _looksLikeRealSecret(value):
                    findings.append(SecretFinding(rule, location))
    return findings


def scanTrackedFiles(repository: Path) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in trackedFiles(repository):
        try:
            if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                continue
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings.extend(
            scanText(
                content,
                locationPrefix=str(path.relative_to(repository)),
            )
        )
    return findings


def scanPatchHistory(repository: Path) -> list[SecretFinding]:
    """扫描所有可达提交新增的补丁行，发现已删除但仍在历史中的凭据。"""

    history = runGit(
        repository,
        "log",
        "--all",
        "--format=@@EVENTSHOCK_COMMIT %H",
        "--no-ext-diff",
        "--unified=0",
        "-p",
        "--",
        ".",
    )
    findings: list[SecretFinding] = []
    commit = "unknown"
    path = "unknown"
    addedLine = 0
    for line in history.splitlines():
        if line.startswith("@@EVENTSHOCK_COMMIT "):
            commit = line.split(maxsplit=1)[1][:12]
            path = "unknown"
            addedLine = 0
            continue
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if line.startswith("@@ "):
            match = re.search(r"\+(\d+)", line)
            addedLine = int(match.group(1)) - 1 if match else 0
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        addedLine += 1
        findings.extend(
            scanText(
                line[1:],
                locationPrefix=f"{commit}:{path}:{addedLine}",
            )
        )
    return findings


def _looksLikeRealSecret(value: str) -> bool:
    normalized = value.strip().casefold()
    if any(token in normalized for token in _SAFE_VALUE_TOKENS):
        return False
    if normalized.startswith(("env:", "file:", "/run/", "/opt/")):
        return False
    if len(value) < 8:
        return False
    return _shannonEntropy(value) >= 3.0


def _shannonEntropy(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def parseArguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path.cwd(),
        help="Git repository to scan.",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Also scan added lines in all reachable Git commits.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parseArguments()
    repository = arguments.repository.resolve()
    findings = scanTrackedFiles(repository)
    if arguments.history:
        findings.extend(scanPatchHistory(repository))
    uniqueFindings = sorted(
        set(findings),
        key=lambda item: (item.location, item.rule),
    )
    if not uniqueFindings:
        print("Repository secret scan passed.")
        return 0
    print(
        "Repository secret scan failed. Suspected values are intentionally redacted.",
        file=sys.stderr,
    )
    for finding in uniqueFindings:
        print(f"- {finding.rule} at {finding.location}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
