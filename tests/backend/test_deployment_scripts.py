from __future__ import annotations

import importlib.util
import io
import json
import stat
from contextlib import AbstractContextManager
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def loadBaotaSiteModule():
    scriptPath = PROJECT_ROOT / "scripts" / "register-baota-site.py"
    spec = importlib.util.spec_from_file_location("register_baota_site", scriptPath)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def loadBaotaTaskModule():
    scriptPath = PROJECT_ROOT / "scripts" / "register-baota-task.py"
    spec = importlib.util.spec_from_file_location("register_baota_task", scriptPath)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeHealthResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    @staticmethod
    def read() -> bytes:
        return json.dumps({"status": "ok"}).encode()


@pytest.mark.parametrize(
    ("isRunning", "forceRestart", "expectedAction"),
    ((True, False, "reload"), (True, True, "restart"), (False, False, "start")),
)
def testValidateAndStartNginxUsesCorrectServiceAction(
    monkeypatch: pytest.MonkeyPatch,
    isRunning: bool,
    forceRestart: bool,
    expectedAction: str,
) -> None:
    module = loadBaotaSiteModule()
    checkCalls: list[list[str]] = []
    isActiveChecks = 0
    monkeypatch.setattr(module, "nginxIsRunning", lambda: isRunning)

    def fakeCall(command, **_kwargs):
        nonlocal isActiveChecks
        if command[:3] == ["systemctl", "is-active", "--quiet"]:
            isActiveChecks += 1
            if isRunning or isActiveChecks > 1:
                return 0
            return 1
        assert command[:2] == ["systemctl", "reset-failed"]
        return 0

    monkeypatch.setattr(module.subprocess, "call", fakeCall)
    monkeypatch.setattr(
        module.subprocess,
        "check_call",
        lambda command: checkCalls.append(command) or 0,
    )
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda command, **_kwargs: (
            'LISTEN 0 511 127.0.0.1:888 0.0.0.0:* users:(("nginx",pid=8,fd=8))\n'
            'LISTEN 0 511 172.17.0.1:18080 0.0.0.0:* users:(("nginx",pid=8,fd=9))\n'
        ),
    )
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeHealthResponse()
    )

    module.validateAndStartNginx("172.17.0.1", forceRestart=forceRestart)

    assert checkCalls == [
        [module.NGINX_BINARY, "-t"],
        ["systemctl", expectedAction, module.NGINX_SYSTEMD_SERVICE],
    ]


def testValidateAndStartNginxReconcilesOrphanProcess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    checkCalls: list[list[str]] = []
    activeChecks = iter((1, 0))
    monkeypatch.setattr(module, "nginxIsRunning", lambda: True)

    def fakeCall(command, **_kwargs):
        if command[:3] == ["systemctl", "is-active", "--quiet"]:
            return next(activeChecks)
        assert command[:2] == ["systemctl", "reset-failed"]
        return 0

    monkeypatch.setattr(module.subprocess, "call", fakeCall)
    monkeypatch.setattr(
        module.subprocess,
        "check_call",
        lambda command: checkCalls.append(command) or 0,
    )
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda command, **_kwargs: (
            'LISTEN 0 511 127.0.0.1:888 0.0.0.0:* users:(("nginx",pid=8,fd=8))\n'
            'LISTEN 0 511 172.17.0.1:18080 0.0.0.0:* users:(("nginx",pid=8,fd=9))\n'
        ),
    )
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeHealthResponse()
    )

    module.validateAndStartNginx("172.17.0.1")

    assert checkCalls == [
        [module.NGINX_BINARY, "-t"],
        [module.NGINX_INIT_SCRIPT, "stop"],
        ["systemctl", "start", module.NGINX_SYSTEMD_SERVICE],
    ]


def testRestoreNginxFallsBackToInitWhenSystemdTakeoverFails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    runningStates = iter((False, False, True))
    checkCalls: list[list[str]] = []
    plainCalls: list[list[str]] = []

    monkeypatch.setattr(module, "nginxIsRunning", lambda: next(runningStates))
    monkeypatch.setattr(
        module.subprocess,
        "call",
        lambda command, **_kwargs: plainCalls.append(command) or 0,
    )

    def fakeCheckCall(command, **_kwargs):
        checkCalls.append(command)
        if command == ["systemctl", "start", module.NGINX_SYSTEMD_SERVICE]:
            raise module.subprocess.CalledProcessError(1, command)
        return 0

    monkeypatch.setattr(module.subprocess, "check_call", fakeCheckCall)

    module.restoreNginxProcessState(True)

    assert plainCalls == [["systemctl", "reset-failed", module.NGINX_SYSTEMD_SERVICE]]
    assert checkCalls == [
        [module.NGINX_BINARY, "-t"],
        ["systemctl", "start", module.NGINX_SYSTEMD_SERVICE],
        [module.NGINX_INIT_SCRIPT, "start"],
    ]


@pytest.mark.parametrize(
    ("installerOutput", "expectedChanged"),
    (
        ("[eventshock-nginx-systemd] changed=true path=/tmp/unit\n", True),
        ("[eventshock-nginx-systemd] changed=false path=/tmp/unit\n", False),
    ),
)
def testInstallNginxSystemdOverrideParsesUniqueResult(
    monkeypatch: pytest.MonkeyPatch,
    installerOutput: str,
    expectedChanged: bool,
) -> None:
    module = loadBaotaSiteModule()
    monkeypatch.setattr(module.os.path, "isfile", lambda _path: True)
    monkeypatch.setattr(module.os, "access", lambda *_args: True)
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda command, **_kwargs: installerOutput,
    )

    assert module.installNginxSystemdOverride() is expectedChanged


def testInstallNginxSystemdOverrideFallsBackToCurrentRelease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        module.os.path,
        "isfile",
        lambda path: path == module.NGINX_SYSTEMD_FALLBACK_INSTALLER,
    )
    monkeypatch.setattr(
        module.os,
        "access",
        lambda path, _mode: path == module.NGINX_SYSTEMD_FALLBACK_INSTALLER,
    )
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda command, **_kwargs: (
            calls.append(command) or "[eventshock-nginx-systemd] changed=false path=/tmp/unit\n"
        ),
    )

    assert module.installNginxSystemdOverride() is False
    assert calls == [[module.NGINX_SYSTEMD_FALLBACK_INSTALLER]]


@pytest.mark.parametrize(
    ("returnCode", "processOutput", "expectedRunning"),
    ((1, "", False), (0, "42\n43\n", True)),
)
def testNginxRunningUsesProcessIdentityInsteadOfBrokenInitStatus(
    monkeypatch: pytest.MonkeyPatch,
    returnCode: int,
    processOutput: str,
    expectedRunning: bool,
) -> None:
    module = loadBaotaSiteModule()
    calls: list[list[str]] = []

    def fakeRun(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=returnCode, stdout=processOutput)

    def fakeRealpath(path):
        if str(path).startswith("/proc/"):
            return module.NGINX_BINARY
        return str(path)

    monkeypatch.setattr(module.subprocess, "run", fakeRun)
    monkeypatch.setattr(module.os.path, "realpath", fakeRealpath)

    assert module.nginxIsRunning() is expectedRunning
    assert calls == [["pgrep", "-x", "nginx"]]


def testValidateEffectiveNginxConfigRejectsPublicListeners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    monkeypatch.setattr(module.subprocess, "check_call", lambda _command: 0)
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda *_args, **_kwargs: (
            "server { listen 172.17.0.1:18080; }\nlisten 80 default_server;\n"
        ),
    )

    with pytest.raises(RuntimeError, match="只允许一个"):
        module.validateEffectiveNginxConfig("172.17.0.1")


def testRestrictPanelAuxiliaryListenersIsSafeAndIdempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = loadBaotaSiteModule()
    nginxConfig = tmp_path / "nginx.conf"
    statusConfig = tmp_path / "phpfpm_status.conf"
    disabledStatusConfig = tmp_path / "phpfpm_status.conf.eventshock-disabled"
    nginxConfig.write_text("http {\nserver {\n    listen 888;\n    server_name phpmyadmin;\n}\n}\n")
    statusConfig.write_text("server {\n    listen 80;\n    server_name 127.0.0.1;\n}\n")
    monkeypatch.setattr(module, "NGINX_CONFIG_PATH", str(nginxConfig))
    monkeypatch.setattr(module, "PHPFPM_STATUS_PATH", str(statusConfig))
    monkeypatch.setattr(module, "DISABLED_PHPFPM_STATUS_PATH", str(disabledStatusConfig))

    module.restrictPanelAuxiliaryListeners()
    module.restrictPanelAuxiliaryListeners()

    assert "listen 127.0.0.1:888;" in nginxConfig.read_text()
    assert "listen 888;" not in nginxConfig.read_text()
    assert not statusConfig.exists()
    assert disabledStatusConfig.read_text().startswith("server {")


def testEventShockNginxExtensionDisablesStreamingBuffers() -> None:
    module = loadBaotaSiteModule()
    source = Path(module.__file__).read_text()

    assert '"proxy_buffering off;\\n"' in source
    assert '"proxy_cache off;\\n"' in source


def testValidateCurrentSiteRequiresExpectedDomain() -> None:
    module = loadBaotaSiteModule()

    class FakeQuery:
        def where(self, *_args):
            return self

        def field(self, *_args):
            return self

        @staticmethod
        def find():
            return None

    publicModule = SimpleNamespace(M=lambda _table: FakeQuery())
    site = {
        "id": 9,
        "name": module.SITE_NAME,
        "path": module.SITE_PATH,
        "status": 1,
        "project_type": "PHP",
    }

    with pytest.raises(RuntimeError, match="域名记录"):
        module.validateCurrentSite(publicModule, site)


def testRemoveFirewallRuleUsesRequestContextForBaotaApi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    contextState = {"active": False, "entered": 0}

    class FakeContext(AbstractContextManager):
        def __enter__(self):
            contextState["active"] = True
            contextState["entered"] += 1
            return self

        def __exit__(self, *_args):
            contextState["active"] = False
            return False

    class FakeQuery:
        def where(self, *_args):
            return self

        def field(self, *_args):
            return self

        @staticmethod
        def select():
            return [{"id": 7, "port": "18080", "ps": module.SITE_NAME}]

    class FakeFirewall:
        @staticmethod
        def DelAcceptPort(parameters):
            assert contextState["active"] is True
            assert parameters == {"id": 7, "port": "18080"}
            return {"status": True}

    publicModule = SimpleNamespace(
        M=lambda _table: FakeQuery(),
        to_dict_obj=lambda value: value,
    )
    monkeypatch.setattr(module, "panelRequestContext", FakeContext)

    module.removeOwnedFirewallRules(publicModule, FakeFirewall)

    assert contextState == {"active": False, "entered": 1}


def testCaddyNetworkDetailsDerivesVerifiedBridgeAndSubnet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    networkId = "607487476fbf" + ("0" * 52)
    containerPayload = [
        {
            "NetworkSettings": {
                "Networks": {
                    "eventshock_default": {
                        "NetworkID": networkId,
                        "IPAddress": "172.19.0.2",
                        "IPPrefixLen": 16,
                    }
                }
            }
        }
    ]
    networkPayload = [
        {
            "Id": networkId,
            "Driver": "bridge",
            "Scope": "local",
            "IPAM": {"Config": [{"Subnet": "172.19.0.0/16"}]},
            "Options": {},
            "Labels": {"com.docker.compose.project": "eventshock"},
        }
    ]

    def fakeCheckOutput(command, **_kwargs):
        if command == ["docker", "inspect", "caddy-id"]:
            return json.dumps(containerPayload)
        assert command == ["docker", "network", "inspect", networkId]
        return json.dumps(networkPayload)

    monkeypatch.setattr(module.subprocess, "check_output", fakeCheckOutput)
    monkeypatch.setattr(
        module.os.path,
        "isdir",
        lambda path: path == "/sys/class/net/br-607487476fbf",
    )

    assert module.caddyNetworkDetails("caddy-id") == (
        "172.19.0.0/16",
        "br-607487476fbf",
    )


def fakeFirewallPublicModule():
    class FakeQuery:
        def where(self, *_args):
            return self

        @staticmethod
        def count():
            return 0

    return SimpleNamespace(M=lambda _table: FakeQuery())


def testAssertInternalPortClosedRejectsDestinationSpecificPublicUfwRule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    monkeypatch.setattr(
        module.os.path,
        "isfile",
        lambda path: path == module.UFW_BINARY_PATH,
    )
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda command, **_kwargs: (
            ("Added user rules:\nufw allow from any to 172.17.0.1 port 18080 proto tcp\n")
            if command == ["ufw", "show", "added"]
            else ""
        ),
    )

    with pytest.raises(RuntimeError, match="非预期或重复"):
        module.assertInternalPortClosed(
            fakeFirewallPublicModule(),
            "br-607487476fbf",
            "172.19.0.0/16",
            "172.17.0.1",
        )


def testAssertInternalPortClosedAllowsSingleExactScopedUfwRule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    exactRule = (
        "ufw allow in on br-607487476fbf from 172.19.0.0/16 "
        "to 172.17.0.1 port 18080 proto tcp comment 'EventShock-Caddy-Nginx'\n"
    )
    monkeypatch.setattr(
        module.os.path,
        "isfile",
        lambda path: path == module.UFW_BINARY_PATH,
    )
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda command, **_kwargs: exactRule if command == ["ufw", "show", "added"] else "",
    )

    module.assertInternalPortClosed(
        fakeFirewallPublicModule(),
        "br-607487476fbf",
        "172.19.0.0/16",
        "172.17.0.1",
    )


@pytest.mark.parametrize(
    ("tokenIndex", "unsafeValue"),
    (
        (4, "eth0"),
        (6, "172.16.0.0/12"),
        (8, "172.17.0.2"),
        (12, "udp"),
        (14, "Manual-Rule"),
    ),
)
def testOwnedScopedUfwRuleRejectsOverbroadOrUnownedVariants(
    tokenIndex: int,
    unsafeValue: str,
) -> None:
    module = loadBaotaSiteModule()
    rule = module.scopedUfwRule(
        "br-607487476fbf",
        "172.19.0.0/16",
        "172.17.0.1",
    )
    assert module.ownedScopedUfwRule(rule, "172.17.0.1")

    rule[tokenIndex] = unsafeValue

    assert not module.ownedScopedUfwRule(rule, "172.17.0.1")


def testValidateScopedUfwStatusRequiresOneCompleteRuleLine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda *_args, **_kwargs: (
            "Status: active\n"
            "172.17.0.1 18080/tcp ALLOW IN 172.19.0.0/16\n"
            "br-607487476fbf # EventShock-Caddy-Nginx\n"
        ),
    )

    with pytest.raises(RuntimeError, match="运行状态未显示完整"):
        module.validateScopedUfwStatus(
            "br-607487476fbf",
            "172.19.0.0/16",
            "172.17.0.1",
        )


def testEnsureScopedUfwRuleAddsOnlyExactCaddyBridgeRule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    state = {"created": False}
    calls: list[list[str]] = []
    expectedRule = module.scopedUfwRule(
        "br-607487476fbf",
        "172.19.0.0/16",
        "172.17.0.1",
    )

    def fakeCheckOutput(command, **_kwargs):
        if command == ["ufw", "show", "added"]:
            if not state["created"]:
                return "Added user rules:\n"
            return " ".join(expectedRule[:-1]) + f" '{expectedRule[-1]}'\n"
        if command == ["ufw", "status"]:
            if not state["created"]:
                return "Status: active\n"
            return (
                "Status: active\n"
                "172.17.0.1 18080/tcp on br-607487476fbf ALLOW IN "
                "172.19.0.0/16 # EventShock-Caddy-Nginx\n"
            )
        raise AssertionError(command)

    def fakeCheckCall(command, **_kwargs):
        calls.append(command)
        assert command == expectedRule
        state["created"] = True
        return 0

    monkeypatch.setattr(module.os.path, "isfile", lambda path: path == module.UFW_BINARY_PATH)
    monkeypatch.setattr(module.subprocess, "check_output", fakeCheckOutput)
    monkeypatch.setattr(module.subprocess, "check_call", fakeCheckCall)

    assert module.ensureScopedUfwRule(
        "br-607487476fbf",
        "172.19.0.0/16",
        "172.17.0.1",
    ) == {"before": [], "listenAddress": "172.17.0.1"}
    assert calls == [expectedRule]


def testEnsureScopedUfwRuleRollsBackFailedPostAddVerification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    state = {"created": False}
    calls: list[list[str]] = []
    expectedRule = module.scopedUfwRule(
        "br-607487476fbf",
        "172.19.0.0/16",
        "172.17.0.1",
    )
    expectedDelete = [
        "ufw",
        "--force",
        "delete",
        *module.scopedUfwRuleSpec(
            "br-607487476fbf",
            "172.19.0.0/16",
            "172.17.0.1",
        ),
    ]

    monkeypatch.setattr(module.os.path, "isfile", lambda path: path == module.UFW_BINARY_PATH)

    def fakeCheckOutput(command, **_kwargs):
        if command == ["ufw", "show", "added"]:
            if state["created"]:
                return " ".join(expectedRule[:-1]) + f" '{expectedRule[-1]}'\n"
            return "Added user rules:\n"
        if command == ["ufw", "status"]:
            return "Status: active\n"
        raise AssertionError(command)

    def fakeCheckCall(command, **_kwargs):
        calls.append(command)
        if command == expectedRule:
            state["created"] = True
        elif command == expectedDelete:
            state["created"] = False
        else:
            raise AssertionError(command)
        return 0

    monkeypatch.setattr(module.subprocess, "check_output", fakeCheckOutput)
    monkeypatch.setattr(module.subprocess, "check_call", fakeCheckCall)

    with pytest.raises(RuntimeError, match="运行状态未显示完整"):
        module.ensureScopedUfwRule(
            "br-607487476fbf",
            "172.19.0.0/16",
            "172.17.0.1",
        )

    assert calls == [expectedRule, expectedDelete]


def testEnsureScopedUfwRuleMigratesOwnedDockerBridgeRuleAndCanRollBack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    oldRule = module.scopedUfwRule(
        "br-111111111111",
        "172.18.0.0/16",
        "172.17.0.1",
    )
    newRule = module.scopedUfwRule(
        "br-222222222222",
        "172.19.0.0/16",
        "172.17.0.1",
    )
    oldDelete = ["ufw", "--force", "delete", *oldRule[1:13]]
    newDelete = ["ufw", "--force", "delete", *newRule[1:13]]
    state = {"rules": [oldRule]}
    calls: list[list[str]] = []

    def renderedRules():
        lines = ["Added user rules:"]
        for rule in state["rules"]:
            lines.append(" ".join(rule[:-1]) + f" '{rule[-1]}'")
        return "\n".join(lines) + "\n"

    def fakeCheckOutput(command, **_kwargs):
        if command == ["ufw", "show", "added"]:
            return renderedRules()
        if command == ["ufw", "status"]:
            return (
                "Status: active\n"
                "172.17.0.1 18080/tcp on br-222222222222 ALLOW IN "
                "172.19.0.0/16 # EventShock-Caddy-Nginx\n"
            )
        raise AssertionError(command)

    def fakeCheckCall(command, **_kwargs):
        calls.append(command)
        if command == newRule:
            state["rules"].append(newRule)
        elif command == oldDelete:
            state["rules"].remove(oldRule)
        elif command == newDelete:
            state["rules"].remove(newRule)
        elif command == oldRule:
            state["rules"].append(oldRule)
        else:
            raise AssertionError(command)
        return 0

    monkeypatch.setattr(module.os.path, "isfile", lambda path: path == module.UFW_BINARY_PATH)
    monkeypatch.setattr(module.subprocess, "check_output", fakeCheckOutput)
    monkeypatch.setattr(module.subprocess, "check_call", fakeCheckCall)

    mutation = module.ensureScopedUfwRule(
        "br-222222222222",
        "172.19.0.0/16",
        "172.17.0.1",
    )

    assert mutation == {"before": [oldRule], "listenAddress": "172.17.0.1"}
    assert state["rules"] == [newRule]
    module.rollbackScopedUfwMutation(mutation)
    assert state["rules"] == [oldRule]
    assert calls == [newRule, oldDelete, oldRule, newDelete]


def testEnsureScopedUfwRuleConvergesAfterInterruptedMigration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    oldRule = module.scopedUfwRule(
        "br-111111111111",
        "172.18.0.0/16",
        "172.17.0.1",
    )
    expectedRule = module.scopedUfwRule(
        "br-222222222222",
        "172.19.0.0/16",
        "172.17.0.1",
    )
    oldDelete = ["ufw", "--force", "delete", *oldRule[1:13]]
    expectedDelete = ["ufw", "--force", "delete", *expectedRule[1:13]]
    state = {"rules": [oldRule, expectedRule, expectedRule]}
    calls: list[list[str]] = []

    def fakeCheckOutput(command, **_kwargs):
        if command == ["ufw", "show", "added"]:
            return "\n".join(
                ["Added user rules:"]
                + [" ".join(rule[:-1]) + f" '{rule[-1]}'" for rule in state["rules"]]
            )
        if command == ["ufw", "status"]:
            return (
                "Status: active\n"
                "172.17.0.1 18080/tcp on br-222222222222 ALLOW IN "
                "172.19.0.0/16 # EventShock-Caddy-Nginx\n"
            )
        raise AssertionError(command)

    def fakeCheckCall(command, **_kwargs):
        calls.append(command)
        if command == oldDelete:
            state["rules"].remove(oldRule)
        elif command == expectedDelete:
            state["rules"].remove(expectedRule)
        else:
            raise AssertionError(command)
        return 0

    monkeypatch.setattr(module.os.path, "isfile", lambda path: path == module.UFW_BINARY_PATH)
    monkeypatch.setattr(module.subprocess, "check_output", fakeCheckOutput)
    monkeypatch.setattr(module.subprocess, "check_call", fakeCheckCall)

    mutation = module.ensureScopedUfwRule(
        "br-222222222222",
        "172.19.0.0/16",
        "172.17.0.1",
    )

    assert mutation == {
        "before": [oldRule, expectedRule, expectedRule],
        "listenAddress": "172.17.0.1",
    }
    assert state["rules"] == [expectedRule]
    assert calls == [oldDelete, expectedDelete]


def testEnsureScopedUfwRuleNeverDeletesUnownedRule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaSiteModule()
    unsafeRule = module.scopedUfwRule(
        "br-111111111111",
        "172.18.0.0/16",
        "172.17.0.1",
    )
    unsafeRule[-1] = "Manual-Rule"
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "ufwIsActive", lambda: True)
    monkeypatch.setattr(module, "internalPortUfwRules", lambda: [unsafeRule])
    monkeypatch.setattr(
        module.subprocess,
        "check_call",
        lambda command, **_kwargs: calls.append(command) or 0,
    )

    with pytest.raises(RuntimeError, match="非预期或重复"):
        module.ensureScopedUfwRule(
            "br-222222222222",
            "172.19.0.0/16",
            "172.17.0.1",
        )

    assert calls == []


@pytest.mark.parametrize(
    ("releaseCommit", "shouldPass"),
    (("abc123", True), ("wrong-sha", False)),
)
def testValidateCaddyToNginxRequiresExpectedReleaseCommit(
    monkeypatch: pytest.MonkeyPatch,
    releaseCommit: str,
    shouldPass: bool,
) -> None:
    module = loadBaotaSiteModule()
    expectedCommand = [
        "docker",
        "exec",
        "caddy-id",
        "wget",
        "-q",
        "-O-",
        "-T",
        "8",
        f"--header=Host:{module.SITE_NAME}",
        f"http://host.docker.internal:{module.SITE_PORT}/api/health",
    ]

    def fakeCheckOutput(command, **kwargs):
        assert command == expectedCommand
        assert kwargs["timeout"] == 12
        return json.dumps(
            {
                "status": "ok",
                "service": "eventshock-api",
                "releaseCommit": releaseCommit,
            }
        )

    monkeypatch.setattr(module.subprocess, "check_output", fakeCheckOutput)

    if shouldPass:
        payload = module.validateCaddyToNginx("caddy-id", "abc123")
        assert payload["releaseCommit"] == "abc123"
    else:
        with pytest.raises(RuntimeError, match="发布版本不一致"):
            module.validateCaddyToNginx("caddy-id", "abc123")


def validBaotaTask(module):
    return {
        "id": 17,
        "name": module.TASK_NAME,
        "type": "minute-n",
        "where1": "10",
        "echo": "a" * 32,
        "status": "1",
        "sType": "toShell",
        "sBody": module.TASK_COMMAND,
    }


@pytest.mark.parametrize(
    ("fieldName", "fieldValue"),
    (
        ("type", "day"),
        ("where1", "5"),
        ("sType", "toUrl"),
        ("sBody", "/bin/true"),
        ("status", 0),
    ),
)
def testBaotaTaskMatchesRejectsEveryConfigurationDrift(
    fieldName: str,
    fieldValue: object,
) -> None:
    module = loadBaotaTaskModule()
    task = validBaotaTask(module)

    assert module.taskMatches(task)
    task[fieldName] = fieldValue
    assert not module.taskMatches(task)


def testFindBaotaTaskRejectsDuplicateTaskNames() -> None:
    module = loadBaotaTaskModule()

    class FakeQuery:
        def where(self, *_args):
            return self

        def field(self, *_args):
            return self

        def select(self):
            return [validBaotaTask(module), validBaotaTask(module)]

    publicModule = SimpleNamespace(M=lambda tableName: FakeQuery())

    with pytest.raises(RuntimeError, match="重复"):
        module.findTask(publicModule)


def testValidateBaotaTaskArtifactsAcceptsNativeScriptAndCron(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaTaskModule()
    task = validBaotaTask(module)
    scriptPath = f"/www/server/cron/{task['echo']}"
    logPath = scriptPath + ".log"
    cronPath = "/var/spool/cron/crontabs/root"
    safeScriptStat = SimpleNamespace(st_mode=stat.S_IFREG | 0o700, st_uid=0)
    fileContents = {
        scriptPath: f"#!/bin/bash\n{module.TASK_COMMAND}\n",
        cronPath: f"*/10 * * * * {scriptPath} >> {logPath} 2>&1\n",
    }

    def fakeOpen(path, *_args, **_kwargs):
        return io.StringIO(fileContents[str(path)])

    monkeypatch.setattr(module.os, "lstat", lambda path: safeScriptStat)
    monkeypatch.setattr(module.os, "access", lambda path, mode: path == scriptPath)
    monkeypatch.setattr(module.os.path, "isfile", lambda path: path in fileContents)
    monkeypatch.setattr(module, "open", fakeOpen, raising=False)

    assert module.validateTaskArtifacts(task) == {
        "scriptPath": scriptPath,
        "logPath": logPath,
    }


def testValidateBaotaTaskArtifactsRejectsSymlinkEntry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loadBaotaTaskModule()
    task = validBaotaTask(module)
    symlinkStat = SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0)
    monkeypatch.setattr(module.os, "lstat", lambda _path: symlinkStat)

    with pytest.raises(RuntimeError, match="不是普通文件"):
        module.validateTaskArtifacts(task)


def testStartBaotaTaskRequiresPanelReadableSuccessfulNativeLog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = loadBaotaTaskModule()
    task = validBaotaTask(module)
    scriptPath = tmp_path / task["echo"]
    logPath = tmp_path / f"{task['echo']}.log"
    logPath.write_text("existing log\n")

    monkeypatch.setattr(
        module,
        "validateTaskArtifacts",
        lambda _task: {"scriptPath": str(scriptPath), "logPath": str(logPath)},
    )

    class FakeCrontab:
        def StartTask(self, parameters):
            assert parameters == {"id": task["id"]}
            with logPath.open("a") as logFile:
                logFile.write("★[2026-07-15 12:00:00] Successful\n")
            return {"status": True}

        def GetLogs(self, parameters):
            assert parameters == {"id": task["id"]}
            return {"status": True, "msg": logPath.read_text()}

    publicModule = SimpleNamespace(to_dict_obj=lambda value: value)

    result = module.startTask(publicModule, FakeCrontab, task)

    assert result["logsReadableInPanel"] is True
    assert "Successful" in result["logTail"]
    assert result["artifacts"]["logPath"] == str(logPath)
