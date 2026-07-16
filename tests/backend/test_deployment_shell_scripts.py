from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def readScript(scriptName: str) -> str:
    return (SCRIPTS_DIR / scriptName).read_text()


@pytest.mark.parametrize(
    "scriptName",
    (
        "baota-eventshock-task.sh",
        "deploy-server.sh",
        "install-github-sync.sh",
        "sync-from-github.sh",
    ),
)
def testDeploymentShellScriptHasValidBashSyntax(scriptName: str) -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPTS_DIR / scriptName)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def testBaotaWrapperPreservesSyncFailureAndWritesBothLogs() -> None:
    script = readScript("baota-eventshock-task.sh")

    assert "set -Eeuo pipefail" in script
    assert 'tee -a "${AUDIT_LOG}"' in script
    assert 'pipelineStatuses=("${PIPESTATUS[@]}")' in script
    assert 'exit "${pipelineStatuses[0]}"' in script
    assert 'exit "${pipelineStatuses[1]}"' in script


def testGitHubSyncEnforcesCiFastForwardAndExactRuntimeCommit() -> None:
    script = readScript("sync-from-github.sh")

    for checkName in (
        "Backend / Python 3.12.13",
        "Frontend / Node 22",
        "Production container",
    ):
        assert f'"{checkName}"' in script
    assert "filter=latest" in script
    assert "successCount != checkCount" in script
    assert '.app.slug == "github-actions"' in script
    assert "merge-base --is-ancestor" in script
    assert '"+refs/heads/${DEPLOY_BRANCH}:${DEPLOY_REF}"' in script
    assert '[[ "${containerCommit}" == "${expectedCommit}" ]]' in script
    assert '.status == "ok" and .releaseCommit == $expectedCommit' in script

    ciGate = script.index('if verify_github_checks "${targetCommit}"')
    backoffGate = script.index('if check_deployment_backoff "${targetCommit}"')
    extraction = script.index('extract_commit "${targetCommit}"')
    deployment = script.index('bash "${STAGING_DIR}/scripts/deploy-server.sh"')
    assert ciGate < backoffGate < extraction < deployment


def testGitHubSyncUsesCommitArchiveAndAtomicImmutableOperationsRelease() -> None:
    script = readScript("sync-from-github.sh")

    assert 'archive --format=tar "${commitSha}"' in script
    assert 'operationsRelease="${OPERATIONS_ROOT}/${commitSha}"' in script
    assert 'install -m 0755 "${sourceScript}" "${operationsTemp}/${scriptName}"' in script
    assert 'mv "${operationsTemp}" "${operationsRelease}"' in script
    assert 'ln -sfnT "${operationsRelease}" "${BIN_DIR}"' in script
    assert 'write_state "${targetCommit}"' in script
    assert "git reset --hard" not in script
    assert "git clean -" not in script


def testGitHubSyncQuarantinesFailedCommitWithBoundedBackoff() -> None:
    script = readScript("sync-from-github.sh")

    assert "delay=1800" in script
    assert "delay=3600" in script
    assert 'mv -f "${failedTemp}" "${FAILED_STATE_FILE}"' in script
    assert "DEPLOY_QUARANTINED" in script
    assert "DEPLOY_BACKOFF" in script
    assert 'rm -f -- "${FAILED_STATE_FILE}"' in script


def testDeployServerBacksUpSqliteAtomicallyAndRetainsThreeBackups() -> None:
    script = readScript("deploy-server.sh")

    assert "source.backup(target)" in script
    assert 'target.execute("PRAGMA quick_check")' in script
    assert "os.fsync(backup_file.fileno())" in script
    assert "os.replace(temporary_path, target_path)" in script
    assert "os.fsync(directory_fd)" in script
    assert "for stale_backup in backups[3:]:" in script


def testDeployServerPublishesCurrentOnlyAfterContainerAndPublicShaChecks() -> None:
    script = readScript("deploy-server.sh")
    deployRelease = script.split("deploy_release() {", 1)[1].split("\n}\n\nmain() {", 1)[0]

    containerHealth = deployRelease.index('wait_for_health "${releaseDir}"')
    publicHealth = deployRelease.index('verify_public_endpoint "${releaseDir}" "${RELEASE_COMMIT}"')
    activateRelease = deployRelease.index('ln -sfnT "${releaseDir}" "${TARGET_ROOT}/current"')
    assert containerHealth < publicHealth < activateRelease
    assert '[[ "${RELEASE_COMMIT}" =~ ^[0-9a-f]{40}$ ]]' in script
    assert '.status == "ok" and .releaseCommit == $expectedCommit' in script


def testDeployServerRollbackIsVerifiedAndRetentionProtectsActiveReleases() -> None:
    script = readScript("deploy-server.sh")
    rollback = script.split("rollback_on_exit() {", 1)[1].split(
        "\n}\n\ncleanup_created_release() {", 1
    )[0]
    retention = script.split("cleanup_old_releases() {", 1)[1].split(
        "\n}\n\ndeploy_release() {", 1
    )[0]

    restartPrevious = rollback.index('run_compose "${ROLLBACK_RELEASE}" up -d')
    verifyContainer = rollback.index('wait_for_health "${ROLLBACK_RELEASE}"')
    verifyPublic = rollback.index(
        'verify_public_endpoint "${ROLLBACK_RELEASE}" "${rollbackCommit}"'
    )
    activatePrevious = rollback.index('ln -sfnT "${ROLLBACK_RELEASE}" "${TARGET_ROOT}/current"')
    assert restartPrevious < verifyContainer < verifyPublic < activatePrevious
    assert "index <= 5" in retention
    assert '[[ "${releaseDir}" == "${currentRelease}" ]]' in retention
    assert '[[ "${releaseDir}" == "${ROLLBACK_RELEASE}" ]]' in retention
