from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.governance.deployment_status import deploymentStatusSnapshot
from backend.app.main import createApp


def _fixedClock() -> datetime:
    return datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def test_deployment_status_reads_only_allowlisted_evidence(tmp_path: Path) -> None:
    commit = "a" * 40
    statusPath = tmp_path / "deployment-status.json"
    statusPath.write_text(
        json.dumps(
            {
                "deployedCommit": commit,
                "githubMainCommit": commit,
                "branch": "main",
                "lastSyncAt": "2026-07-29T11:50:00Z",
                "lastSyncResult": "SUCCEEDED",
                "lastDeployAt": "2026-07-29T11:55:00Z",
                "requiredChecks": [
                    {
                        "name": "Backend / Python 3.12.13",
                        "status": "PASS",
                        "completedAt": "2026-07-29T11:45:00Z",
                    },
                    {
                        "name": "Production container",
                        "status": "PASS",
                        "completedAt": "2026-07-29T11:47:00Z",
                    },
                    {
                        "name": "Frontend / Node 22",
                        "status": "PASS",
                        "completedAt": "2026-07-29T11:46:00Z",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    statusPath.chmod(0o640)

    status = deploymentStatusSnapshot(
        releaseCommit=commit,
        statusPath=statusPath,
        clock=_fixedClock,
    )

    assert status["deployedCommit"] == commit
    assert status["healthCommit"] == commit
    assert status["reportedDeployedCommit"] == commit
    assert status["githubMainCommit"] == commit
    assert status["commitAlignment"] == "MATCH"
    assert status["requiredChecksStatus"] == "PASS"
    assert status["statusFileState"] == "VERIFIED"
    assert status["observedAt"] == "2026-07-29T12:00:00+00:00"
    assert set(status) == {
        "branch",
        "commitAlignment",
        "deployedCommit",
        "evidenceObservedAt",
        "githubMainCommit",
        "healthCommit",
        "lastDeployAt",
        "lastFailureAt",
        "lastFailureCode",
        "lastSyncAt",
        "lastSyncResult",
        "observedAt",
        "reportedDeployedCommit",
        "requiredChecks",
        "requiredChecksStatus",
        "schemaVersion",
        "statusErrorCode",
        "statusFileState",
        "statusSource",
    }


def test_deployment_status_rejects_unknown_or_mutable_files_without_leaking(
    tmp_path: Path,
) -> None:
    statusPath = tmp_path / "deployment-status.json"
    secretMarker = "must-not-leak-secret-value"
    statusPath.write_text(
        json.dumps(
            {
                "deployedCommit": "b" * 40,
                "rawLog": secretMarker,
            }
        ),
        encoding="utf-8",
    )
    statusPath.chmod(0o666)

    status = deploymentStatusSnapshot(
        releaseCommit="a" * 40,
        statusPath=statusPath,
        clock=_fixedClock,
    )

    assert status["statusFileState"] == "INVALID_FAIL_CLOSED"
    assert status["statusErrorCode"] == "DEPLOYMENT_STATUS_FILE_INVALID"
    assert secretMarker not in json.dumps(status)
    assert str(statusPath) not in json.dumps(status)

    statusPath.chmod(0o640)
    unknownFieldStatus = deploymentStatusSnapshot(
        releaseCommit="a" * 40,
        statusPath=statusPath,
        clock=_fixedClock,
    )
    assert unknownFieldStatus["statusFileState"] == "INVALID_FAIL_CLOSED"
    assert secretMarker not in json.dumps(unknownFieldStatus)


def test_deployment_status_supports_existing_github_sync_state(tmp_path: Path) -> None:
    commit = "c" * 40
    statusPath = tmp_path / "github-sync.state"
    statusPath.write_text(
        f"commit={commit}\nbranch=main\ndeployedAt=2026-07-29T10:00:00Z\n",
        encoding="utf-8",
    )
    statusPath.chmod(0o644)

    status = deploymentStatusSnapshot(
        releaseCommit=commit,
        statusPath=statusPath,
        clock=_fixedClock,
    )

    assert status["reportedDeployedCommit"] == commit
    assert status["commitAlignment"] == "HEALTH_MATCH"
    assert status["lastSyncResult"] == "SUCCEEDED"
    assert status["requiredChecksStatus"] == "UNKNOWN"


def test_deployment_status_rejects_symbolic_links(tmp_path: Path) -> None:
    targetPath = tmp_path / "target.json"
    targetPath.write_text(
        json.dumps({"deployedCommit": "a" * 40}),
        encoding="utf-8",
    )
    targetPath.chmod(0o640)
    statusPath = tmp_path / "deployment-status.json"
    statusPath.symlink_to(targetPath)

    status = deploymentStatusSnapshot(
        releaseCommit="a" * 40,
        statusPath=statusPath,
        clock=_fixedClock,
    )

    assert status["statusFileState"] == "INVALID_FAIL_CLOSED"
    assert status["statusErrorCode"] == "DEPLOYMENT_STATUS_FILE_INVALID"


def test_deployment_status_api_uses_release_commit_and_disables_caching(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commit = "d" * 40
    statusPath = tmp_path / "deployment-status.json"
    statusPath.write_text(
        json.dumps(
            {
                "deployedCommit": commit,
                "githubMainCommit": "e" * 40,
                "requiredChecks": [],
            }
        ),
        encoding="utf-8",
    )
    statusPath.chmod(0o640)
    monkeypatch.setenv("EVENTSHOCK_RELEASE_COMMIT", commit)
    monkeypatch.setenv("EVENTSHOCK_DEPLOYMENT_STATUS_FILE", str(statusPath))

    with TestClient(createApp(tmp_path / "data")) as client:
        response = client.get("/api/v1/governance/deployment-status")

    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json()["deployedCommit"] == commit
    assert response.json()["healthCommit"] == commit
    assert response.json()["commitAlignment"] == "MAIN_MISMATCH"
