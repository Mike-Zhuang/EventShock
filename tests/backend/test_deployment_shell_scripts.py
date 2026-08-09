from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def readScript(scriptName: str) -> str:
    return (SCRIPTS_DIR / scriptName).read_text()


def testCaddyRetriesStartupRaceWithoutSyntheticHealthTraffic() -> None:
    caddyfile = (PROJECT_ROOT / "Caddyfile").read_text()
    composeFile = (PROJECT_ROOT / "compose.yml").read_text()
    startupGate = readScript("caddy-startup-gate.sh")

    assert "lb_try_duration 5s" in caddyfile
    assert "lb_try_interval 250ms" in caddyfile
    assert "header_up X-Real-IP {remote_host}" in caddyfile
    assert "style-src 'self';" in caddyfile
    assert "'unsafe-inline'" not in caddyfile
    assert "health_uri" not in caddyfile
    assert "health_interval" not in caddyfile
    assert "/usr/local/bin/caddy-startup-gate.sh" in composeFile
    assert "http://127.0.0.1:2019/config/" in composeFile
    assert "caddy\n      - validate" not in composeFile
    assert 'CADDY_STARTUP_GATE_TIMEOUT_SECONDS: "${CADDY_STARTUP_GATE_TIMEOUT_SECONDS:-90}"' in (
        composeFile
    )

    applicationWait = startupGate.index("waitForUrl application")
    proxyWait = startupGate.index('waitForUrl proxy "${upstreamHealthUrl}"')
    caddyExec = startupGate.index('exec "$@"')
    assert applicationWait < proxyWait < caddyExec
    assert "http://app:8000/api/health?startup-gate=application" in startupGate
    assert "/api/health?startup-gate=proxy" in startupGate
    assert '--header "Host: ${waitHost}"' in startupGate
    assert "--noproxy '*'" in startupGate
    assert 'if [ "${responseCode}" = 200 ]' in startupGate
    assert 'proxyHost="${proxyHost#https://}"' in startupGate
    assert "startup gate timed out" in startupGate


def testCaddyStartupGateHasValidPosixShellSyntax() -> None:
    result = subprocess.run(
        ["sh", "-n", str(SCRIPTS_DIR / "caddy-startup-gate.sh")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def testCaddyStartupGateWaitsBeforeExecutingCaddy(tmp_path: Path) -> None:
    fakeBin = tmp_path / "bin"
    fakeBin.mkdir()
    stateDir = tmp_path / "state"
    stateDir.mkdir()

    fakeCurl = fakeBin / "curl"
    fakeCurl.write_text(
        """#!/bin/sh
countFile="${EVENTSHOCK_GATE_TEST_DIR}/curl-count"
count=0
if [ -f "${countFile}" ]; then count=$(cat "${countFile}"); fi
count=$((count + 1))
printf '%s' "${count}" > "${countFile}"
printf '%s\\n' "$*" >> "${EVENTSHOCK_GATE_TEST_DIR}/curl-arguments"
if [ "${count}" -ge 3 ]; then printf '200'; else printf '000'; exit 1; fi
"""
    )
    fakeSleep = fakeBin / "sleep"
    fakeSleep.write_text("#!/bin/sh\nexit 0\n")
    fakeCaddy = fakeBin / "caddy"
    fakeCaddy.write_text(
        """#!/bin/sh
cat "${EVENTSHOCK_GATE_TEST_DIR}/curl-count" > "${EVENTSHOCK_GATE_TEST_DIR}/caddy-after"
printf '%s\\n' "$*" > "${EVENTSHOCK_GATE_TEST_DIR}/caddy-arguments"
"""
    )
    for fakeCommand in (fakeCurl, fakeSleep, fakeCaddy):
        fakeCommand.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "APP_DOMAIN": "https://eventshock.mikezhuang.cn",
            "CADDY_UPSTREAM": "host.docker.internal:18080",
            "EVENTSHOCK_GATE_TEST_DIR": str(stateDir),
            "PATH": f"{fakeBin}:{environment['PATH']}",
        }
    )
    result = subprocess.run(
        [
            "sh",
            str(SCRIPTS_DIR / "caddy-startup-gate.sh"),
            "caddy",
            "run",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert (stateDir / "curl-count").read_text() == "4"
    assert (stateDir / "caddy-after").read_text() == "4"
    assert (stateDir / "caddy-arguments").read_text().strip() == (
        "run --config /etc/caddy/Caddyfile --adapter caddyfile"
    )
    curlArguments = (stateDir / "curl-arguments").read_text()
    assert "startup-gate=application" in curlArguments
    assert "startup-gate=proxy" in curlArguments
    assert "Host: eventshock.mikezhuang.cn" in curlArguments


def testCaddyStartupGateFailsOpenAfterBoundedTimeout(tmp_path: Path) -> None:
    fakeBin = tmp_path / "bin"
    fakeBin.mkdir()
    stateDir = tmp_path / "state"
    stateDir.mkdir()

    fakeCurl = fakeBin / "curl"
    fakeCurl.write_text("#!/bin/sh\nprintf '000'\nexit 1\n")
    fakeSleep = fakeBin / "sleep"
    fakeSleep.write_text("#!/bin/sh\nexit 99\n")
    fakeCaddy = fakeBin / "caddy"
    fakeCaddy.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" > "${EVENTSHOCK_GATE_TEST_DIR}/caddy-arguments"
"""
    )
    for fakeCommand in (fakeCurl, fakeSleep, fakeCaddy):
        fakeCommand.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "CADDY_STARTUP_GATE_TIMEOUT_SECONDS": "0",
            "EVENTSHOCK_GATE_TEST_DIR": str(stateDir),
            "PATH": f"{fakeBin}:{environment['PATH']}",
        }
    )
    result = subprocess.run(
        ["sh", str(SCRIPTS_DIR / "caddy-startup-gate.sh"), "caddy", "run"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert "startup gate timed out after 0s" in result.stderr
    assert (stateDir / "caddy-arguments").read_text().strip() == "run"


def testDeploymentRequiresExecutableCaddyStartupGate() -> None:
    deployScript = readScript("deploy-server.sh")

    assert '[[ -x "${SOURCE_ROOT}/scripts/caddy-startup-gate.sh" ]]' in deployScript
    assert "源码目录缺少可执行的 Caddy 启动门控" in deployScript


@pytest.mark.parametrize(
    "scriptName",
    (
        "baota-eventshock-task.sh",
        "deploy-server.sh",
        "install-github-sync.sh",
        "install-nginx-systemd-override.sh",
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
    assert 'DEPLOY_BRANCH="main"' in script

    selfHeal = script.index("attempting local proxy self-heal before GitHub access")
    githubAccess = script.index("prepare_mirror", script.index("main() {"))
    ciGate = script.index('if verify_github_checks "${targetCommit}"')
    backoffGate = script.index('if check_deployment_backoff "${targetCommit}"')
    extraction = script.index('extract_commit "${targetCommit}"')
    deployment = script.index('bash "${STAGING_DIR}/scripts/deploy-server.sh"')
    assert selfHeal < githubAccess < ciGate < extraction < backoffGate < deployment


def testDeploymentStatusUsesPersistentVolumeAndFixedReadOnlyApiPath() -> None:
    composeFile = (PROJECT_ROOT / "compose.yml").read_text()
    environmentExample = (PROJECT_ROOT / ".env.example").read_text()
    deployScript = readScript("deploy-server.sh")
    syncScript = readScript("sync-from-github.sh")
    writeStatus = syncScript.split("write_deployment_status() {", 1)[1].split(
        "\n}\n\nsync_on_exit() {", 1
    )[0]
    buildDocument = syncScript.split("build_deployment_status_document() {", 1)[1].split(
        "\n}\n\nwrite_deployment_status() {", 1
    )[0]

    assert "EVENTSHOCK_DEPLOYMENT_STATUS_FILE: /data/deployment-status.json" in composeFile
    assert "- eventshock-data:/data" in composeFile
    assert "EVENTSHOCK_DEPLOYMENT_STATUS_FILE=/data/deployment-status.json" in (environmentExample)
    assert "EVENTSHOCK_DEPLOYMENT_STATUS_FILE 必须精确为" in deployScript
    assert 'DATA_VOLUME_NAME="eventshock-data"' in syncScript
    assert 'DEPLOYMENT_STATUS_FILE_NAME="deployment-status.json"' in syncScript
    assert "docker volume inspect --format '{{ .Mountpoint }}'" in syncScript
    assert 'statusTemp="$(mktemp "${mountpoint}/.${DEPLOYMENT_STATUS_FILE_NAME}.XXXXXX")"' in (
        writeStatus
    )
    assert 'chmod 0644 "${statusTemp}"' in writeStatus
    assert 'sync -f "${statusTemp}"' in writeStatus
    assert 'mv -f -- "${statusTemp}" "${statusPath}"' in writeStatus
    assert 'sync -f "${mountpoint}"' in writeStatus
    for allowedField in (
        "deployedCommit",
        "githubMainCommit",
        "branch",
        "requiredChecks",
        "lastSyncAt",
        "lastSyncResult",
        "lastDeployAt",
        "lastFailureAt",
        "lastFailureCode",
        "observedAt",
    ):
        assert allowedField in buildDocument
    for forbiddenField in ("token", "password", "logContent", "responseBody"):
        assert forbiddenField not in buildDocument


def testGitHubSyncPublishesFailClosedEvidenceForEveryTerminalBranch() -> None:
    script = readScript("sync-from-github.sh")
    mainBody = script.split("main() {", 1)[1].split('\n}\n\nmain "$@"', 1)[0]

    assert "reset_required_check_evidence" in mainBody
    assert 'deployment_status_has_verified_checks "${targetCommit}"' in mainBody
    assert "EVIDENCE_REFRESH" in mainBody
    assert '"SUCCEEDED" "${deployedCommit}" "${targetCommit}" "" "false" "true"' in mainBody
    assert '"PENDING" "${deployedCommit}" "${targetCommit}"' in mainBody
    assert '"SUCCEEDED" "${targetCommit}" "${targetCommit}" "" "true"' in mainBody
    assert 'STATUS_FAILURE_CODE="REQUIRED_CHECKS_FAILED"' in mainBody
    assert 'STATUS_FAILURE_CODE="GITHUB_CHECKS_API_FAILED"' in mainBody
    assert 'STATUS_FAILURE_CODE="DEPLOYMENT_FAILED"' in mainBody
    assert "trap sync_on_exit EXIT" in mainBody
    assert '.status == "PASS"' in script
    assert "$previous.requiredChecks" in script
    assert "reuseVerifiedChecks" in script
    evidenceCheck = script.split("deployment_status_has_verified_checks() {", 1)[1].split(
        "\n}\n\nbuild_deployment_status_document() {", 1
    )[0]
    assert ".deployedCommit == $expectedCommit" in evidenceCheck
    assert ".githubMainCommit == $expectedCommit" in evidenceCheck
    assert 'all(.requiredChecks[]; .status == "PASS")' in evidenceCheck


def testGitHubSyncRepairsInfrastructureWithoutQuarantiningKnownGoodCommit() -> None:
    script = readScript("sync-from-github.sh")
    mainBody = script.split("main() {", 1)[1].split('\n}\n\nmain "$@"', 1)[0]

    repairAttempt = mainBody.index('repair_baota_proxy "${deployedCommit}"')
    infrastructureStop = mainBody.index("INFRASTRUCTURE_BLOCKED")
    targetRepair = mainBody.index('"${STAGING_DIR}/scripts/register-baota-site.py"')
    ciGate = mainBody.index('verify_github_checks "${targetCommit}"')
    quarantine = mainBody.index('record_deployment_failure "${targetCommit}"')
    assert repairAttempt < infrastructureStop < ciGate < targetRepair < quarantine
    assert "RUNTIME_SELF_HEAL_SUCCESS" in script
    assert "host.docker.internal:18080" in script
    assert 'verify_local_runtime_commit "${deployedCommit}"' in mainBody


def testGitHubSyncUsesCommitArchiveAndAtomicImmutableOperationsRelease() -> None:
    script = readScript("sync-from-github.sh")

    assert 'archive --format=tar "${commitSha}"' in script
    assert 'operationsRelease="${OPERATIONS_ROOT}/${commitSha}"' in script
    assert 'install -m 0755 "${sourceScript}" "${operationsTemp}/${scriptName}"' in script
    assert 'mv "${operationsTemp}" "${operationsRelease}"' in script
    assert 'ln -sfnT "${operationsRelease}" "${BIN_DIR}"' in script
    assert 'write_state "${targetCommit}"' in script
    assert '"install-nginx-systemd-override.sh"' in script
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


def testGitHubSyncTreatsMissingFailureStateAsNoBackoff() -> None:
    script = readScript("sync-from-github.sh")
    functionBody = script.split("check_deployment_backoff() {", 1)[1].split(
        "\n}\n\nrecord_deployment_failure() {", 1
    )[0]
    probe = f"""
failed_state_value() {{ return 1; }}
log() {{ :; }}
check_deployment_backoff() {{{functionBody}
}}
check_deployment_backoff "{"a" * 40}"
"""

    result = subprocess.run(
        ["bash", "-c", probe],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def testDeployServerBacksUpSqliteAtomicallyAndRetainsThreeBackups() -> None:
    script = readScript("deploy-server.sh")

    assert "source.backup(target)" in script
    assert 'target.execute("PRAGMA quick_check")' in script
    assert "os.fsync(backup_file.fileno())" in script
    assert "os.replace(temporary_path, target_path)" in script
    assert "os.fsync(directory_fd)" in script
    assert "for stale_backup in backups[3:]:" in script


def testAdminApiKeyEncryptionKeyProvisioningPrecedesDeploymentValidation() -> None:
    script = readScript("deploy-server.sh")
    ensureBody = script.split("ensure_admin_api_key_encryption_key() {", 1)[1].split(
        "\n}\n\nvalidate_auth_configuration() {",
        1,
    )[0]
    deployRelease = script.split("deploy_release() {", 1)[1].split("\n}\n\nmain() {", 1)[0]

    assert "普通目录且不能是符号链接" in ensureBody
    assert '"0:10001:750"' in ensureBody
    assert ensureBody.index('[[ -e "${ADMIN_API_KEY_ENCRYPTION_KEY_FILE}" ]]') < (
        ensureBody.index("head -c 32 /dev/urandom")
    )
    assert 'ln -- "${temporaryPath}" "${ADMIN_API_KEY_ENCRYPTION_KEY_FILE}"' in ensureBody
    assert deployRelease.index("ensure_admin_api_key_encryption_key") < deployRelease.index(
        "validate_auth_configuration"
    )


def testDeployServerPublishesCurrentOnlyAfterContainerAndPublicShaChecks() -> None:
    script = readScript("deploy-server.sh")
    deployRelease = script.split("deploy_release() {", 1)[1].split("\n}\n\nmain() {", 1)[0]

    containerHealth = deployRelease.index('wait_for_health "${releaseDir}"')
    baotaHealth = deployRelease.index('ensure_baota_proxy "${releaseDir}"')
    publicHealth = deployRelease.index('verify_public_endpoint "${releaseDir}" "${RELEASE_COMMIT}"')
    activateRelease = deployRelease.index('ln -sfnT "${releaseDir}" "${TARGET_ROOT}/current"')
    assert containerHealth < baotaHealth < publicHealth < activateRelease
    assert '[[ "${RELEASE_COMMIT}" =~ ^[0-9a-f]{40}$ ]]' in script
    assert '.status == "ok" and .releaseCommit == $expectedCommit' in script
    assert "拒绝绕过宝塔流量统计链路" in script


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
    verifyBaota = rollback.index('ensure_baota_proxy "${ROLLBACK_RELEASE}"')
    verifyPublic = rollback.index(
        'verify_public_endpoint "${ROLLBACK_RELEASE}" "${rollbackCommit}"'
    )
    activatePrevious = rollback.index('ln -sfnT "${ROLLBACK_RELEASE}" "${TARGET_ROOT}/current"')
    assert restartPrevious < verifyContainer < verifyBaota < verifyPublic < activatePrevious
    assert "index <= 5" in retention
    assert '[[ "${releaseDir}" == "${currentRelease}" ]]' in retention
    assert '[[ "${releaseDir}" == "${ROLLBACK_RELEASE}" ]]' in retention


def testNginxSystemdOverrideWaitsForDockerWithBoundedRetries() -> None:
    script = readScript("install-nginx-systemd-override.sh")

    assert 'DROP_IN_PATH="${DROP_IN_DIR}/eventshock-docker-order.conf"' in script
    assert "'Wants=docker.service'" in script
    assert "'After=docker.service'" in script
    assert "'StartLimitIntervalSec=60'" in script
    assert "'StartLimitBurst=6'" in script
    assert "'Restart=on-failure'" in script
    assert "'RestartSec=5s'" in script
    assert "Requires=docker.service" not in script
    assert "PartOf=docker.service" not in script
    assert "RemainAfterExit=" not in script
    assert "PIDFile=" not in script

    installDropIn = script.index('mv -f -- "${temporaryPath}" "${DROP_IN_PATH}"')
    daemonReload = script.index("systemctl daemon-reload", installDropIn)
    enableService = script.index("systemctl enable nginx.service")
    assert installDropIn < daemonReload < enableService
    assert 'cp -a -- "${DROP_IN_PATH}" "${backupPath}"' in script
    assert 'mv -f -- "${backupPath}" "${DROP_IN_PATH}" || true' in script
    assert 'if ((exitCode != 0)) && [[ "${dropInReplaced}" == "true" ]]' in script


def testOperationalBootstrapIncludesNginxSystemdInstaller() -> None:
    script = readScript("install-github-sync.sh")

    assert "scripts/install-nginx-systemd-override.sh" in script
    assert "install-nginx-systemd-override.sh \\" in script
    assert '"${bootstrapRelease}/install-nginx-systemd-override.sh"' in script
    assert "EVENTSHOCK_GITHUB_BRANCH=main" in script


def testControlledRestartVerifierIsInstalledButNeverRebootsImplicitly() -> None:
    installer = readScript("install-github-sync.sh")
    verifier = readScript("verify-restart-recovery.sh")

    assert "verify-restart-recovery.sh \\" in installer
    assert "eventshock-restart-verification.service" in installer
    assert "ConditionPathExists=/var/lib/eventshock-restart-verification/pending.json" in installer
    assert "After=docker.service nginx.service network-online.target" in installer
    assert "systemctl enable eventshock-restart-verification.service" in installer

    assert 'requestReboot="false"' in verifier
    assert '[[ "${requestReboot}" == "true" ]]' in verifier
    assert "REBOOT_EVENTSHOCK_PRODUCTION_IN_MAINTENANCE_WINDOW" in verifier
    assert verifier.index('[[ "${EVENTSHOCK_REBOOT_CONFIRMATION:-}"') < verifier.index(
        "systemctl reboot"
    )


def testControlledRestartVerifierRequiresDirectRecoveryEvidence() -> None:
    verifier = readScript("verify-restart-recovery.sh")

    for evidenceName in (
        "runtimeRecovery",
        "releaseAndContainers",
        "nginxSystemdDependency",
        "privatePorts",
        "caddyToBaotaToApp",
        "publicHealth",
        "baotaTraffic",
        "baotaScheduledTask",
        "authenticatedApiAndSse",
    ):
        assert f'"{evidenceName}"' in verifier
    assert 'all(.[]; .status == "PASS")' in verifier
    assert 'overallStatus="INCOMPLETE"' in verifier
    assert "restart-verification-" in verifier
    assert verifier.index('if [[ "${overallStatus}" == "PASS" ]]') < verifier.index(
        'rm -f -- "${PENDING_FILE}"'
    )
    assert "Cookie 文件只读取、不复制" in verifier


def testControlledRestartVerifierHasValidBashSyntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPTS_DIR / "verify-restart-recovery.sh")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
