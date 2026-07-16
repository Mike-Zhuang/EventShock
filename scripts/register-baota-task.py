#!/www/server/panel/pyenv/bin/python3
"""通过宝塔 10.x 自身的 crontab 类注册并验收 EventShock 计划任务。"""

import argparse
import fcntl
import json
import os
import re
import stat
import sys
import time

PANEL_ROOT = "/www/server/panel"
TASK_NAME = "EventShock GitHub 自动同步部署"
TASK_WRAPPER = "/opt/eventshock/bin/baota-eventshock-task.sh"
REGISTER_LOCK = "/run/lock/eventshock-baota-task-register.lock"
TASK_COMMAND = """trap 'rm -f -- "${0}.pl"' EXIT
/opt/eventshock/bin/baota-eventshock-task.sh
taskStatus=$?
if [[ "${taskStatus}" -ne 0 ]]; then
    echo "[eventshock-baota] ERROR: synchronization failed with status ${taskStatus}"
    exit "${taskStatus}"
fi"""


def loadPanelModules():
    if not os.path.isdir(PANEL_ROOT):
        raise RuntimeError(f"未找到宝塔面板目录：{PANEL_ROOT}")
    os.chdir(PANEL_ROOT)
    sys.path.insert(0, PANEL_ROOT)
    sys.path.insert(0, os.path.join(PANEL_ROOT, "class"))
    import public  # pylint: disable=import-outside-toplevel
    from crontab import crontab  # pylint: disable=import-outside-toplevel

    return public, crontab


def acquireRegistrationLock():
    os.makedirs(os.path.dirname(REGISTER_LOCK), mode=0o755, exist_ok=True)
    lockHandle = open(REGISTER_LOCK, "a+")
    fcntl.flock(lockHandle.fileno(), fcntl.LOCK_EX)
    return lockHandle


def validateWrapper():
    wrapperStat = os.lstat(TASK_WRAPPER)
    if stat.S_ISLNK(wrapperStat.st_mode) or not stat.S_ISREG(wrapperStat.st_mode):
        raise RuntimeError("宝塔任务包装器必须是普通文件，不能是符号链接")
    if wrapperStat.st_uid != 0:
        raise RuntimeError("宝塔任务包装器必须由 root 拥有")
    if wrapperStat.st_mode & 0o022:
        raise RuntimeError("宝塔任务包装器不能由组或其他用户写入")
    if not os.access(TASK_WRAPPER, os.X_OK):
        raise RuntimeError("宝塔任务包装器不可执行")


def findTask(publicModule):
    tasks = (
        publicModule.M("crontab")
        .where("name=?", (TASK_NAME,))
        .field("id,name,type,where1,where_hour,where_minute,echo,status,sType,sBody")
        .select()
    )
    if len(tasks) > 1:
        raise RuntimeError("宝塔中存在重复的 EventShock 同名任务，拒绝自动选择")
    return tasks[0] if tasks else None


def taskMatches(task):
    return bool(
        task
        and task.get("type") == "minute-n"
        and str(task.get("where1")) == "10"
        and task.get("sType") == "toShell"
        and task.get("sBody", "").strip() == TASK_COMMAND.strip()
        and int(task.get("status", 0)) == 1
    )


def validateTaskArtifacts(task):
    echo = task.get("echo", "")
    if not re.fullmatch(r"[0-9a-f]{32}", echo):
        raise RuntimeError("宝塔任务 echo 标识不合法")
    scriptPath = f"/www/server/cron/{echo}"
    logPath = scriptPath + ".log"
    scriptStat = os.lstat(scriptPath)
    if stat.S_ISLNK(scriptStat.st_mode) or not stat.S_ISREG(scriptStat.st_mode):
        raise RuntimeError("宝塔生成的任务入口不是普通文件")
    if scriptStat.st_uid != 0 or scriptStat.st_mode & 0o022:
        raise RuntimeError("宝塔生成的任务入口权限不安全")
    if not os.access(scriptPath, os.X_OK):
        raise RuntimeError("宝塔生成的任务入口不可执行")
    if TASK_COMMAND.strip() not in open(scriptPath).read():
        raise RuntimeError("宝塔生成的任务入口未包含预期命令")

    cronContent = ""
    for cronPath in ("/var/spool/cron/crontabs/root", "/var/spool/cron/root"):
        if os.path.isfile(cronPath):
            cronContent += open(cronPath).read()
    cronPattern = re.compile(
        rf"(?m)^\*/10 \* \* \* \*\s+{re.escape(scriptPath)}\s+>>\s+"
        rf"{re.escape(logPath)}\s+2>&1\s*$"
    )
    if not cronPattern.search(cronContent):
        raise RuntimeError("root crontab 未包含预期的 10 分钟宝塔任务")
    return {"scriptPath": scriptPath, "logPath": logPath}


def addTask(publicModule, crontabClass):
    parameters = {
        "name": TASK_NAME,
        "type": "minute-n",
        "where1": "10",
        "hour": "0",
        "minute": "0",
        "save": "30",
        "backupTo": "localhost",
        "sType": "toShell",
        "sName": "",
        "sBody": TASK_COMMAND,
        "urladdress": "",
        "db_type": "",
        "split_type": "",
        "split_value": "",
        "keyword": "",
        "post_param": "",
        "flock": 0,
        "time_set": "",
        "backup_mode": "",
        "db_backup_path": "",
        "time_type": "",
        "special_time": "",
        "log_cut_path": "",
        "user_agent": "",
        "version": "",
        "table_list": "",
        "result": 1,
        "second": "",
        "stop_site": "",
        "rname": TASK_NAME,
        "notice": 0,
        "notice_channel": "",
    }
    result = crontabClass().AddCrontab(publicModule.to_dict_obj(parameters))
    if not result.get("status"):
        raise RuntimeError("宝塔 AddCrontab 失败：{}".format(result.get("msg", result)))
    return result


def removeTask(publicModule, crontabClass, task):
    if not task:
        return {"status": True, "message": "任务原本不存在"}
    result = crontabClass().DelCrontab(publicModule.to_dict_obj({"id": int(task["id"])}))
    if not result.get("status"):
        raise RuntimeError("宝塔 DelCrontab 失败：{}".format(result.get("msg", result)))
    return result


def startTask(publicModule, crontabClass, task):
    if not taskMatches(task):
        raise RuntimeError("同名任务配置不一致，拒绝以 root 立即执行")
    artifacts = validateTaskArtifacts(task)
    logPath = artifacts["logPath"]
    previousSize = os.path.getsize(logPath) if os.path.isfile(logPath) else 0
    result = crontabClass().StartTask(publicModule.to_dict_obj({"id": int(task["id"])}))
    if not result.get("status"):
        raise RuntimeError("宝塔 StartTask 失败：{}".format(result.get("msg", result)))

    pidPath = artifacts["scriptPath"] + ".pl"
    deadline = time.monotonic() + 900
    observedExecution = False
    while time.monotonic() < deadline:
        currentSize = os.path.getsize(logPath) if os.path.isfile(logPath) else 0
        if os.path.exists(pidPath) or currentSize > previousSize:
            observedExecution = True
        if observedExecution and not os.path.exists(pidPath) and currentSize > previousSize:
            break
        time.sleep(1)
    else:
        raise RuntimeError("宝塔任务在 15 分钟内没有完成")

    with open(logPath, errors="replace") as logFile:
        logFile.seek(previousSize)
        newLogText = logFile.read()
    logResult = crontabClass().GetLogs(publicModule.to_dict_obj({"id": int(task["id"])}))
    if not isinstance(logResult, dict) or not logResult.get("status"):
        raise RuntimeError("宝塔前端 GetLogs 无法读取本次任务日志")
    if (
        "[eventshock-baota] ERROR" in newLogText
        or "★[" not in newLogText
        or "Successful" not in newLogText
    ):
        raise RuntimeError("宝塔任务已结束，但原生日志未显示成功")
    return {
        "start": result,
        "logsReadableInPanel": True,
        "artifacts": artifacts,
        "logTail": newLogText[-2_000:],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace", action="store_true", help="替换同名但配置不同的任务")
    parser.add_argument("--remove", action="store_true", help="删除 EventShock 任务")
    parser.add_argument("--run", action="store_true", help="通过宝塔立即执行并等待验收")
    parser.add_argument("--show", action="store_true", help="只显示任务，不写入配置")
    arguments = parser.parse_args()

    _registrationLock = acquireRegistrationLock()
    publicModule, crontabClass = loadPanelModules()
    task = findTask(publicModule)

    if arguments.remove:
        print(json.dumps(removeTask(publicModule, crontabClass, task), ensure_ascii=False))
        return

    validateWrapper()
    if arguments.show:
        artifacts = validateTaskArtifacts(task) if task and taskMatches(task) else None
        print(
            json.dumps(
                {"status": True, "task": task or None, "artifacts": artifacts},
                ensure_ascii=False,
            )
        )
        return
    if arguments.run:
        if not task:
            raise RuntimeError("计划任务尚未注册")
        print(
            json.dumps(
                startTask(publicModule, crontabClass, task),
                ensure_ascii=False,
            )
        )
        return

    if task and not taskMatches(task):
        if not arguments.replace:
            raise RuntimeError("同名任务已存在但配置不同；核对后使用 --replace")
        removeTask(publicModule, crontabClass, task)
        task = None
    if not task:
        addTask(publicModule, crontabClass)
        task = findTask(publicModule)

    if not taskMatches(task):
        raise RuntimeError("任务写入后未通过一致性检查")
    artifacts = validateTaskArtifacts(task)
    print(
        json.dumps(
            {
                "status": True,
                "message": "任务已注册",
                "task": task,
                "artifacts": artifacts,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # 宝塔一次性管理脚本需要把错误明确写入 SSH/面板日志。
        print(json.dumps({"status": False, "error": str(error)}, ensure_ascii=False))
        sys.exit(1)
