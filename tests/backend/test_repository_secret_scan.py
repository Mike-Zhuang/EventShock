from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "check-repository-secrets.py"


def loadScanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("repository_secret_scan", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_secret_scanner_detects_credentials_without_echoing_values() -> None:
    scanner = loadScanner()
    sensitiveValue = "R7zQ2pLm9Xv4Nc8K"

    findings = scanner.scanText(
        f'smtp_password = "{sensitiveValue}"',
        locationPrefix="settings.env",
    )

    assert [(item.rule, item.location) for item in findings] == [
        ("PLAINTEXT_CREDENTIAL_ASSIGNMENT", "settings.env:1")
    ]
    assert all(sensitiveValue not in repr(item) for item in findings)


def test_secret_scanner_allows_documented_placeholders_and_ci_fixtures() -> None:
    scanner = loadScanner()
    text = "\n".join(
        (
            'api_key = "${EVENTSHOCK_API_KEY}"',
            'password = "change-me-before-production"',
            'secret = "ci-auth-secret-with-at-least-thirty-two-bytes"',
            'password = "ValidPassword123!"',
        )
    )

    assert scanner.scanText(text, locationPrefix="fixture.txt") == []


def test_secret_scanner_detects_private_keys_bearer_tokens_and_credential_urls() -> None:
    scanner = loadScanner()
    bearerFixture = 'Authorization: "Bearer ' + 'Ab3dE5fGh7jKl9mNp2qRs4tUv6wXy8zA"'
    credentialUrlFixture = "smtp://" + "sender:" + "Q7xN4vLm8pR2sT6k" + "@smtp.example.net"
    text = "\n".join(
        (
            "-----BEGIN PRIVATE KEY-----",
            bearerFixture,
            credentialUrlFixture,
        )
    )

    findings = scanner.scanText(text, locationPrefix="leak.txt")

    assert {item.rule for item in findings} == {
        "PRIVATE_KEY_MATERIAL",
        "BEARER_TOKEN",
        "URL_EMBEDDED_CREDENTIAL",
    }


def test_secret_scanner_includes_nonignored_untracked_files(tmp_path: Path) -> None:
    scanner = loadScanner()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored.env\n")
    (tmp_path / "new-config.txt").write_text("placeholder\n")
    (tmp_path / "ignored.env").write_text("ignored\n")

    discovered = {path.relative_to(tmp_path).as_posix() for path in scanner.trackedFiles(tmp_path)}

    assert ".gitignore" in discovered
    assert "new-config.txt" in discovered
    assert "ignored.env" not in discovered
