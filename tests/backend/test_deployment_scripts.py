from __future__ import annotations

import importlib.util
import io
import json
import stat
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
    ("isRunning", "expectedAction"),
    ((True, "reload"), (False, "start")),
)
def testValidateAndStartNginxUsesCorrectServiceAction(
    monkeypatch: pytest.MonkeyPatch,
    isRunning: bool,
    expectedAction: str,
) -> None:
    module = loadBaotaSiteModule()
    serviceCalls: list[list[str]] = []
    monkeypatch.setattr(module, "nginxIsRunning", lambda: isRunning)
    monkeypatch.setattr(
        module.subprocess,
        "check_call",
        lambda command: serviceCalls.append(command) or 0,
    )
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda command, **_kwargs: (
            'LISTEN 0 511 172.17.0.1:18080 0.0.0.0:* users:(("nginx",pid=8,fd=9))\n'
        ),
    )
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeHealthResponse()
    )

    module.validateAndStartNginx("172.17.0.1")

    assert serviceCalls == [[module.NGINX_INIT_SCRIPT, expectedAction]]


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
