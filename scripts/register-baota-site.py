#!/www/server/panel/pyenv/bin/python3
"""用宝塔自身站点/反代 API 注册 EventShock，并限制 Nginx 只监听 Docker 网关。"""

import argparse
import glob
import ipaddress
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
import urllib.request

PANEL_ROOT = "/www/server/panel"
SITE_NAME = "eventshock.mikezhuang.cn"
SITE_PATH = "/www/wwwroot/eventshock.mikezhuang.cn"
SITE_PORT = 18080
APP_URL = "http://127.0.0.1:18000"
NGINX_BINARY = "/www/server/nginx/sbin/nginx"
NGINX_CONFIG_PATH = "/www/server/nginx/conf/nginx.conf"
VHOST_PATH = f"/www/server/panel/vhost/nginx/{SITE_NAME}.conf"
DEFAULT_VHOST_PATH = "/www/server/panel/vhost/nginx/0.default.conf"
DISABLED_DEFAULT_VHOST_PATH = DEFAULT_VHOST_PATH + ".eventshock-disabled"
PHPFPM_STATUS_PATH = "/www/server/panel/vhost/nginx/phpfpm_status.conf"
DISABLED_PHPFPM_STATUS_PATH = PHPFPM_STATUS_PATH + ".eventshock-disabled"
EXTENSION_DIR = f"/www/server/panel/vhost/nginx/extension/{SITE_NAME}"
EXTENSION_PATH = os.path.join(EXTENSION_DIR, "99-eventshock.conf")
NGINX_INIT_SCRIPT = "/etc/init.d/nginx"
SITE_TOTAL_SOCKET = "/tmp/site_total.sock"
SITE_TOTAL_EXTENSION_PATH = os.path.join(EXTENSION_DIR, "site_total.conf")
SITE_TOTAL_DATA_GLOB = f"/www/server/site_total/data/total/{SITE_NAME}/*.json"
PANEL_LOOPBACK_LISTENER = "127.0.0.1:888"
UFW_BINARY_PATH = "/usr/sbin/ufw"
UFW_RULE_COMMENT = "EventShock-Caddy-Nginx"


def loadPanelModules():
    os.chdir(PANEL_ROOT)
    sys.path.insert(0, PANEL_ROOT)
    sys.path.insert(0, os.path.join(PANEL_ROOT, "class"))
    import public  # pylint: disable=import-outside-toplevel
    from firewalls import firewalls  # pylint: disable=import-outside-toplevel
    from mod.base.free_site_total import (  # pylint: disable=import-outside-toplevel
        SiteTotalConfig,
    )
    from panelSite import panelSite  # pylint: disable=import-outside-toplevel

    return public, panelSite, firewalls, SiteTotalConfig


def panelRequestContext():
    # 宝塔 10.0.2 的 DelAcceptPort 会读取 Flask request 来保护面板端口。
    # CLI 注册器没有天然请求上下文，因此仅为调用官方防火墙 API 创建本地上下文。
    from flask import Flask  # pylint: disable=import-outside-toplevel

    contextApp = Flask("eventshock-baota-cli")
    return contextApp.test_request_context("/", headers={"Host": "127.0.0.1:65535"})


def validateListenAddress(value):
    address = ipaddress.ip_address(value)
    if address.version != 4 or not address.is_private or address.is_loopback:
        raise RuntimeError("Nginx 监听地址必须是私有 IPv4 Docker host-gateway")
    listenAddress = str(address)

    containerIds = subprocess.check_output(
        [
            "docker",
            "ps",
            "--filter",
            "label=com.docker.compose.project=eventshock",
            "--filter",
            "label=com.docker.compose.service=caddy",
            "--format",
            "{{.ID}}",
        ],
        text=True,
    ).split()
    if len(containerIds) != 1:
        raise RuntimeError("无法唯一识别正在运行的 EventShock Caddy 容器")
    resolvedAddress = subprocess.check_output(
        ["docker", "exec", containerIds[0], "getent", "hosts", "host.docker.internal"],
        text=True,
    ).split()[0]
    if resolvedAddress != listenAddress:
        raise RuntimeError(
            f"监听地址 {listenAddress} 与 Caddy host.docker.internal={resolvedAddress} 不一致"
        )

    dockerAddresses = re.findall(
        r"\binet\s+([0-9.]+)/",
        subprocess.check_output(["ip", "-4", "-o", "address", "show", "docker0"], text=True),
    )
    if listenAddress not in dockerAddresses:
        raise RuntimeError("Caddy host-gateway 并非宿主机 docker0 地址，拒绝继续")
    return listenAddress, containerIds[0]


def caddyNetworkDetails(containerId):
    container = json.loads(subprocess.check_output(["docker", "inspect", containerId], text=True))[
        0
    ]
    networks = container.get("NetworkSettings", {}).get("Networks", {})
    if len(networks) != 1:
        raise RuntimeError("Caddy 必须只连接一个 EventShock Docker 网络")
    attachment = next(iter(networks.values()))
    networkId = attachment.get("NetworkID")
    address = attachment.get("IPAddress")
    prefixLength = attachment.get("IPPrefixLen")
    if (
        not isinstance(networkId, str)
        or not re.fullmatch(r"[0-9a-f]{64}", networkId)
        or not address
        or not prefixLength
    ):
        raise RuntimeError("无法读取 Caddy Docker 网络标识或 IPv4 范围")

    network = json.loads(
        subprocess.check_output(["docker", "network", "inspect", networkId], text=True)
    )[0]
    networkLabels = network.get("Labels") or {}
    if (
        network.get("Id") != networkId
        or network.get("Driver") != "bridge"
        or network.get("Scope") != "local"
        or networkLabels.get("com.docker.compose.project") != "eventshock"
    ):
        raise RuntimeError("Caddy 必须连接本机 bridge 类型的 Docker 网络")

    caddyAddress = ipaddress.ip_address(address)
    configuredNetworks = []
    for item in network.get("IPAM", {}).get("Config", []):
        subnet = item.get("Subnet")
        if not subnet:
            continue
        candidate = ipaddress.ip_network(subnet, strict=True)
        if candidate.version == 4 and caddyAddress in candidate:
            configuredNetworks.append(candidate)
    if len(configuredNetworks) != 1:
        raise RuntimeError("无法唯一识别包含 Caddy 地址的 Docker IPv4 子网")

    trustedNetwork = configuredNetworks[0]
    attachedNetwork = ipaddress.ip_network(f"{address}/{prefixLength}", strict=False)
    if (
        trustedNetwork != attachedNetwork
        or trustedNetwork.version != 4
        or not trustedNetwork.is_private
    ):
        raise RuntimeError("Caddy Docker 网络不是私有 IPv4 范围")

    options = network.get("Options") or {}
    bridgeInterface = options.get("com.docker.network.bridge.name") or f"br-{networkId[:12]}"
    if (
        not isinstance(bridgeInterface, str)
        or len(bridgeInterface) > 15
        or not re.fullmatch(r"[A-Za-z0-9_.:-]+", bridgeInterface)
        or not os.path.isdir(f"/sys/class/net/{bridgeInterface}")
    ):
        raise RuntimeError("无法验证 Caddy Docker bridge 接口")
    return str(trustedNetwork), bridgeInterface


def checkApplicationHealth():
    request = urllib.request.Request(APP_URL + "/api/health", method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "ok":
        raise RuntimeError("应用回环健康检查失败")
    if payload.get("service") != "eventshock-api" or not payload.get("releaseCommit"):
        raise RuntimeError("应用健康响应缺少服务标识或发布 SHA")
    return payload


def addSite(publicModule, panelSiteClass):
    parameters = publicModule.to_dict_obj(
        {
            "webname": json.dumps({"domain": SITE_NAME, "domainlist": [], "count": 0}),
            "path": SITE_PATH,
            "port": str(SITE_PORT),
            "version": "00",
            "ps": "EventShock Lab（Caddy TLS → 宝塔 Nginx → FastAPI）",
            "ftp": "false",
            "sql": "false",
            "type_id": 0,
            "project_type": "PHP",
        }
    )
    # multiple=1 会跳过 AddSite 末尾的 serviceReload；在 listener 收口前绝不能
    # 让宝塔尝试启动 Nginx。
    result = panelSiteClass().AddSite(parameters, multiple=1)
    if isinstance(result, dict) and result.get("status") is False:
        raise RuntimeError("宝塔 AddSite 失败：{}".format(result.get("msg", result)))
    return result


def removeOwnedFirewallRules(publicModule, firewallsClass):
    rules = (
        publicModule.M("firewall").where("port=?", (str(SITE_PORT),)).field("id,port,ps").select()
    )
    for rule in rules:
        if rule.get("ps") != SITE_NAME:
            raise RuntimeError("18080 已存在非 EventShock 防火墙规则，拒绝自动修改")
        # 继续使用宝塔自身 DelAcceptPort，让 UFW/firewalld 与面板记录同步删除；
        # 请求上下文只用于满足该 API 对 public.GetHost(True) 的依赖。
        with panelRequestContext():
            result = firewallsClass().DelAcceptPort(
                publicModule.to_dict_obj({"id": int(rule["id"]), "port": str(SITE_PORT)})
            )
        if not result.get("status"):
            raise RuntimeError("宝塔自动放行了 18080，但撤销该规则失败")


def ufwEnvironment():
    return {**os.environ, "LC_ALL": "C"}


def scopedUfwRuleSpec(bridgeInterface, trustedCaddyNetwork, listenAddress):
    return [
        "allow",
        "in",
        "on",
        bridgeInterface,
        "from",
        trustedCaddyNetwork,
        "to",
        listenAddress,
        "port",
        str(SITE_PORT),
        "proto",
        "tcp",
    ]


def scopedUfwRule(bridgeInterface, trustedCaddyNetwork, listenAddress):
    return [
        "ufw",
        *scopedUfwRuleSpec(bridgeInterface, trustedCaddyNetwork, listenAddress),
        "comment",
        UFW_RULE_COMMENT,
    ]


def configuredUfwRules():
    if not os.path.isfile(UFW_BINARY_PATH):
        return []
    output = subprocess.check_output(
        ["ufw", "show", "added"],
        text=True,
        env=ufwEnvironment(),
    )
    rules = []
    for line in output.splitlines():
        if not line.startswith("ufw "):
            continue
        tokens = shlex.split(line)
        if tokens and tokens[0] == "ufw":
            rules.append(tokens)
    return rules


def ufwRuleTargetsInternalPort(rule):
    portPattern = re.compile(rf"(?:^|[,:]){SITE_PORT}(?:$|[/:,])")
    return any(portPattern.search(token) for token in rule[1:])


def ufwIsActive():
    if not os.path.isfile(UFW_BINARY_PATH):
        return False
    status = subprocess.check_output(
        ["ufw", "status"],
        text=True,
        env=ufwEnvironment(),
    )
    return "Status: active" in status


def scopedUfwRulePresent(bridgeInterface, trustedCaddyNetwork, listenAddress):
    expectedRule = scopedUfwRule(bridgeInterface, trustedCaddyNetwork, listenAddress)
    internalPortRules = [rule for rule in configuredUfwRules() if ufwRuleTargetsInternalPort(rule)]
    return internalPortRules == [expectedRule]


def assertInternalPortClosed(
    publicModule,
    bridgeInterface,
    trustedCaddyNetwork,
    listenAddress,
):
    if publicModule.M("firewall").where("port=?", (str(SITE_PORT),)).count():
        raise RuntimeError("宝塔防火墙数据库仍包含 18080 放行规则")
    expectedRule = scopedUfwRule(bridgeInterface, trustedCaddyNetwork, listenAddress)
    internalPortRules = [rule for rule in configuredUfwRules() if ufwRuleTargetsInternalPort(rule)]
    if internalPortRules not in ([], [expectedRule]):
        raise RuntimeError("UFW 存在非预期或重复的 18080 放行规则")
    if os.path.isfile("/usr/bin/firewall-cmd"):
        activeZones = subprocess.check_output(["firewall-cmd", "--get-active-zones"], text=True)
        zones = [
            line.split()[0] for line in activeZones.splitlines() if line and not line[0].isspace()
        ]
        defaultZone = subprocess.check_output(
            ["firewall-cmd", "--get-default-zone"], text=True
        ).strip()
        for zone in sorted(set(zones + [defaultZone])):
            if (
                zone
                and subprocess.call(
                    [
                        "firewall-cmd",
                        "--quiet",
                        "--zone",
                        zone,
                        "--query-port",
                        f"{SITE_PORT}/tcp",
                    ]
                )
                == 0
            ):
                raise RuntimeError(f"firewalld zone={zone} 仍对外放行 18080")


def removeScopedUfwRule(bridgeInterface, trustedCaddyNetwork, listenAddress):
    subprocess.check_call(
        [
            "ufw",
            "--force",
            "delete",
            *scopedUfwRuleSpec(bridgeInterface, trustedCaddyNetwork, listenAddress),
        ],
        env=ufwEnvironment(),
    )
    if scopedUfwRulePresent(bridgeInterface, trustedCaddyNetwork, listenAddress):
        raise RuntimeError("本次新增的 Caddy→Nginx UFW 规则删除后仍然存在")


def ensureScopedUfwRule(bridgeInterface, trustedCaddyNetwork, listenAddress):
    if not ufwIsActive():
        return False

    expectedRule = scopedUfwRule(bridgeInterface, trustedCaddyNetwork, listenAddress)
    rules = configuredUfwRules()
    internalPortRules = [rule for rule in rules if ufwRuleTargetsInternalPort(rule)]
    if internalPortRules == [expectedRule]:
        return False
    if internalPortRules:
        raise RuntimeError("UFW 存在非预期或重复的 18080 放行规则")

    created = False
    try:
        subprocess.check_call(expectedRule, env=ufwEnvironment())
        created = True
        if not scopedUfwRulePresent(bridgeInterface, trustedCaddyNetwork, listenAddress):
            raise RuntimeError("UFW 未保存精确的 Caddy→Nginx 内部放行规则")
        status = subprocess.check_output(
            ["ufw", "status"],
            text=True,
            env=ufwEnvironment(),
        )
        requiredValues = (
            bridgeInterface,
            trustedCaddyNetwork,
            listenAddress,
            str(SITE_PORT),
            UFW_RULE_COMMENT,
        )
        if not all(value in status for value in requiredValues):
            raise RuntimeError("UFW 运行状态未显示完整的 Caddy→Nginx 内部放行边界")
    except Exception:
        if created:
            try:
                removeScopedUfwRule(bridgeInterface, trustedCaddyNetwork, listenAddress)
            except Exception as rollbackError:
                raise RuntimeError("UFW 规则添加失败，且本次新增规则无法回滚") from rollbackError
        raise
    return True


def ensureProxy(publicModule, panelSiteClass):
    proxyParameters = publicModule.to_dict_obj(
        {
            "proxyname": "EventShock FastAPI",
            "sitename": SITE_NAME,
            "proxydir": "/",
            "proxysite": APP_URL,
            "todomain": "$host",
            "type": "1",
            "cache": "0",
            "subfilter": "[]",
            "advanced": "0",
            "cachetime": "1",
            "nocheck": "1",
        }
    )
    proxyList = panelSiteClass().GetProxyList(publicModule.to_dict_obj({"sitename": SITE_NAME}))
    for proxy in proxyList:
        if proxy.get("proxyname") == "EventShock FastAPI":
            if (
                proxy.get("proxysite") != APP_URL
                or proxy.get("proxydir") != "/"
                or proxy.get("todomain") != "$host"
                or int(proxy.get("type", 0)) != 1
                or int(proxy.get("cache", 1)) != 0
                or int(proxy.get("advanced", 1)) != 0
                or bool(proxy.get("subfilter"))
            ):
                raise RuntimeError("同名宝塔反向代理配置与预期不一致")
            if proxyConfigurationPresent():
                return proxy
            removeResult = panelSiteClass().RemoveProxy(proxyParameters, multiple=1)
            if not removeResult or not removeResult.get("status"):
                raise RuntimeError("宝塔代理记录存在但配置缺失，且自动修复删除失败")
            break
    result = panelSiteClass().CreateProxy(proxyParameters)
    if not result.get("status"):
        raise RuntimeError("宝塔 CreateProxy 失败：{}".format(result.get("msg", result)))
    return result


def proxyConfigurationPresent():
    proxyRoot = f"/www/server/panel/vhost/nginx/proxy/{SITE_NAME}"
    if not os.path.isdir(proxyRoot):
        return False
    for fileName in os.listdir(proxyRoot):
        filePath = os.path.join(proxyRoot, fileName)
        if not fileName.endswith(".conf") or not os.path.isfile(filePath):
            continue
        content = open(filePath).read()
        if f"proxy_pass {APP_URL}" in content and "proxy_set_header Host $host" in content:
            return True
    return False


def disableDefaultPublicVhost():
    if not os.path.isfile(DEFAULT_VHOST_PATH):
        return
    content = open(DEFAULT_VHOST_PATH).read()
    if not re.search(r"(?m)^\s*server_name\s+_;\s*$", content):
        raise RuntimeError("0.default.conf 似乎不是宝塔默认站点，拒绝自动停用")
    if not re.search(r"(?m)^\s*listen\s+(?:\[::\]:|(?:0\.0\.0\.0:)?)80\b", content):
        raise RuntimeError("0.default.conf 不包含预期的默认 80 listener，拒绝自动停用")
    if os.path.exists(DISABLED_DEFAULT_VHOST_PATH):
        raise RuntimeError("默认 vhost 的停用备份已存在，拒绝覆盖")
    os.replace(DEFAULT_VHOST_PATH, DISABLED_DEFAULT_VHOST_PATH)


def restrictPanelAuxiliaryListeners():
    if not os.path.isfile(NGINX_CONFIG_PATH):
        raise RuntimeError("宝塔 Nginx 主配置不存在")
    content = open(NGINX_CONFIG_PATH).read()
    if "server_name phpmyadmin;" not in content:
        raise RuntimeError("无法识别宝塔内置 phpMyAdmin server")
    publicPattern = r"(?m)^(\s*)listen\s+888;\s*$"
    loopbackPattern = r"(?m)^\s*listen\s+127\.0\.0\.1:888;\s*$"
    publicCount = len(re.findall(publicPattern, content))
    loopbackCount = len(re.findall(loopbackPattern, content))
    if publicCount == 1 and loopbackCount == 0:
        content = re.sub(
            publicPattern,
            rf"\1listen {PANEL_LOOPBACK_LISTENER};",
            content,
            count=1,
        )
        atomicWrite(
            NGINX_CONFIG_PATH,
            content,
            os.stat(NGINX_CONFIG_PATH).st_mode & 0o777,
        )
    elif publicCount != 0 or loopbackCount != 1:
        raise RuntimeError("宝塔 phpMyAdmin listener 与预期不一致")

    if os.path.isfile(PHPFPM_STATUS_PATH):
        statusContent = open(PHPFPM_STATUS_PATH).read()
        if (
            "server_name 127.0.0.1;" not in statusContent
            or len(re.findall(r"(?m)^\s*listen\s+80;\s*$", statusContent)) != 1
        ):
            raise RuntimeError("phpfpm_status.conf 不是预期的宝塔默认状态站点")
        if os.path.exists(DISABLED_PHPFPM_STATUS_PATH):
            raise RuntimeError("phpfpm_status.conf 的停用备份已存在，拒绝覆盖")
        os.replace(PHPFPM_STATUS_PATH, DISABLED_PHPFPM_STATUS_PATH)
    elif not os.path.isfile(DISABLED_PHPFPM_STATUS_PATH):
        raise RuntimeError("未找到可核验的 phpfpm_status.conf 或停用备份")


def atomicWrite(path, content, mode=0o644):
    temporaryPath = path + ".eventshock-next"
    with open(temporaryPath, "wb") as output:
        output.write(content if isinstance(content, bytes) else content.encode("utf-8"))
        output.flush()
        os.fsync(output.fileno())
    os.chmod(temporaryPath, mode)
    os.replace(temporaryPath, path)


def snapshotFiles(paths):
    snapshots = {}
    for path in paths:
        if os.path.isfile(path):
            snapshots[path] = (open(path, "rb").read(), os.stat(path).st_mode & 0o777)
        else:
            snapshots[path] = None
    return snapshots


def restoreFiles(snapshots):
    for path, snapshot in snapshots.items():
        if snapshot is None:
            if os.path.exists(path):
                os.remove(path)
            continue
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent, 0o755)
        atomicWrite(path, snapshot[0], snapshot[1])


def restrictVhostListener(listenAddress, trustedCaddyNetwork):
    if not os.path.isfile(VHOST_PATH):
        raise RuntimeError("宝塔没有生成 EventShock Nginx vhost")
    content = open(VHOST_PATH).read()
    content = re.sub(
        r"(?m)^\s*listen\s+(?:[0-9.]+:)?18080;\s*$",
        f"    listen {listenAddress}:{SITE_PORT};",
        content,
    )
    content = re.sub(r"(?m)^\s*listen\s+\[::\]:18080;\s*$", "", content)
    expected = f"listen {listenAddress}:{SITE_PORT};"
    if content.count(expected) != 1:
        raise RuntimeError("无法把 EventShock vhost 唯一绑定到 Docker host-gateway")
    atomicWrite(VHOST_PATH, content, os.stat(VHOST_PATH).st_mode & 0o777)

    if not os.path.isdir(EXTENSION_DIR):
        os.makedirs(EXTENSION_DIR, 0o755)
    os.chmod(EXTENSION_DIR, 0o755)
    atomicWrite(
        EXTENSION_PATH,
        "client_max_body_size 2m;\n"
        "proxy_cache off;\n"
        "proxy_buffering off;\n"
        "proxy_no_cache 1;\n"
        "proxy_cache_bypass 1;\n"
        "proxy_connect_timeout 5s;\n"
        "proxy_send_timeout 300s;\n"
        "proxy_read_timeout 300s;\n"
        f"set_real_ip_from {trustedCaddyNetwork};\n"
        "real_ip_header X-Forwarded-For;\n"
        "real_ip_recursive on;\n",
    )


def listenerPort(endpoint):
    if endpoint.isdigit():
        return int(endpoint)
    match = re.search(r":(\d+)$", endpoint)
    return int(match.group(1)) if match else None


def validateEffectiveNginxConfig(listenAddress):
    subprocess.check_call([NGINX_BINARY, "-t"])
    effectiveConfig = subprocess.check_output(
        [NGINX_BINARY, "-T"], stderr=subprocess.STDOUT, text=True
    )
    endpoints = [
        directive.split()[0]
        for directive in re.findall(r"(?m)^\s*listen\s+([^;]+);", effectiveConfig)
    ]
    expectedEndpoint = f"{listenAddress}:{SITE_PORT}"
    expectedEndpoints = sorted((PANEL_LOOPBACK_LISTENER, expectedEndpoint))
    if len(endpoints) != len(expectedEndpoints) or sorted(set(endpoints)) != expectedEndpoints:
        raise RuntimeError(
            "宝塔 Nginx 只允许一个非回环业务 listener；实际为：{}".format(
                ", ".join(endpoints) or "<none>"
            )
        )


def nginxIsRunning():
    # 宝塔 10.0.2 的 init 脚本把“stopped”返回为 0、把“running”返回为 1，
    # 不能按常规 service 退出码判断。直接核对进程名与 /proc 可执行文件，
    # 同时拒绝同名但并非宝塔二进制的进程。
    result = subprocess.run(
        ["pgrep", "-x", "nginx"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 1:
        return False
    if result.returncode != 0:
        raise RuntimeError("无法判断宝塔 Nginx 进程状态")
    processIds = [value for value in result.stdout.splitlines() if value.isdigit()]
    if not processIds:
        return False
    expectedBinary = os.path.realpath(NGINX_BINARY)
    processBinaries = {os.path.realpath(f"/proc/{processId}/exe") for processId in processIds}
    if processBinaries != {expectedBinary}:
        raise RuntimeError("检测到并非宝塔二进制的同名 Nginx 进程")
    return True


def validateAndStartNginx(listenAddress):
    isRunning = nginxIsRunning()
    action = "reload" if isRunning else "start"
    subprocess.check_call([NGINX_INIT_SCRIPT, action])

    listeners = subprocess.check_output(["ss", "-H", "-ltnp"], text=True)
    nginxListeners = []
    for line in listeners.splitlines():
        if "nginx" not in line:
            continue
        fields = line.split()
        if len(fields) >= 4:
            nginxListeners.append(fields[3])
    expectedListener = f"{listenAddress}:{SITE_PORT}"
    expectedListeners = sorted((PANEL_LOOPBACK_LISTENER, expectedListener))
    if sorted(set(nginxListeners)) != expectedListeners:
        raise RuntimeError(
            "Nginx 进程监听不符合唯一内部端口约束：{}".format(", ".join(nginxListeners) or "<none>")
        )

    request = urllib.request.Request(
        f"http://{listenAddress}:{SITE_PORT}/api/health",
        headers={"Host": SITE_NAME},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "ok":
        raise RuntimeError("宝塔 Nginx 反向代理健康检查失败")


def validateCaddyToNginx(caddyContainerId, expectedReleaseCommit):
    command = [
        "docker",
        "exec",
        caddyContainerId,
        "wget",
        "-q",
        "-O-",
        "-T",
        "8",
        f"--header=Host:{SITE_NAME}",
        f"http://host.docker.internal:{SITE_PORT}/api/health",
    ]
    try:
        output = subprocess.check_output(command, text=True, timeout=12)
        payload = json.loads(output)
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as error:
        raise RuntimeError("Caddy 容器无法通过宝塔 Nginx 完成健康检查") from error

    if (
        payload.get("status") != "ok"
        or payload.get("service") != "eventshock-api"
        or payload.get("releaseCommit") != expectedReleaseCommit
    ):
        raise RuntimeError("Caddy→宝塔 Nginx 健康响应与当前应用发布版本不一致")
    return payload


def enableSiteTraffic(siteTotalConfigClass, siteId):
    result = siteTotalConfigClass().one_site_status(int(siteId), True)
    if result:
        raise RuntimeError(f"启用宝塔 free_site_total 失败：{result}")

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if (
            os.path.isfile(SITE_TOTAL_EXTENSION_PATH)
            and os.path.exists(SITE_TOTAL_SOCKET)
            and stat.S_ISSOCK(os.stat(SITE_TOTAL_SOCKET).st_mode)
            and subprocess.call(["systemctl", "is-active", "--quiet", "site_total"]) == 0
        ):
            break
        time.sleep(1)
    else:
        raise RuntimeError("宝塔 free_site_total 服务、Unix socket 或站点配置未就绪")

    content = open(SITE_TOTAL_EXTENSION_PATH).read()
    expectedTag = f"tag={int(siteId)}__access"
    if SITE_TOTAL_SOCKET not in content or expectedTag not in content:
        raise RuntimeError("宝塔站点流量统计配置未绑定正确的站点 ID 或 Unix socket")

    config = siteTotalConfigClass().get_status()
    enabledSiteIds = {
        int(item["site_id"]) for item in config.get("sites", []) if item.get("is_open")
    }
    if not config.get("is_open", False) or int(siteId) not in enabledSiteIds:
        raise RuntimeError("宝塔 free_site_total 配置未显示 EventShock 已启用")


def siteTrafficRequests():
    requestCount = 0
    for filePath in glob.glob(SITE_TOTAL_DATA_GLOB):
        try:
            payload = json.loads(open(filePath).read())
            requestCount += int(payload.get("requests", 0))
        except (OSError, ValueError, TypeError):
            continue
    return requestCount


def validateSiteTraffic(listenAddress, previousRequests):
    for sequence in range(3):
        request = urllib.request.Request(
            f"http://{listenAddress}:{SITE_PORT}/api/health?baota-stat-check={sequence}",
            headers={
                "Host": SITE_NAME,
                "User-Agent": "EventShock-BaoTa-Validation",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("宝塔流量统计验证请求失败")

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if siteTrafficRequests() >= previousRequests + 3:
            return
        time.sleep(1)
    raise RuntimeError("真实请求未写入宝塔 free_site_total 统计数据")


def currentSite(publicModule):
    return (
        publicModule.M("sites")
        .where("name=?", (SITE_NAME,))
        .field("id,name,path,status,ps,project_type,addtime")
        .find()
    )


def validateCurrentSite(publicModule, site):
    if (
        not site
        or site.get("project_type") != "PHP"
        or site.get("path") != SITE_PATH
        or str(site.get("status")) != "1"
    ):
        raise RuntimeError("宝塔站点状态、路径或项目类型与预期不一致")
    domain = (
        publicModule.M("domain")
        .where("pid=? and name=? and port=?", (int(site["id"]), SITE_NAME, SITE_PORT))
        .field("id,pid,name,port")
        .find()
    )
    if not domain:
        raise RuntimeError("宝塔站点缺少 eventshock.mikezhuang.cn:18080 域名记录")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-address", required=True)
    parser.add_argument("--show", action="store_true")
    arguments = parser.parse_args()

    if not os.path.isfile(NGINX_BINARY):
        raise RuntimeError("宝塔 Nginx 尚未安装")
    listenAddress, caddyContainerId = validateListenAddress(arguments.listen_address)
    trustedCaddyNetwork, trustedCaddyInterface = caddyNetworkDetails(caddyContainerId)
    publicModule, panelSiteClass, firewallsClass, siteTotalConfigClass = loadPanelModules()
    site = currentSite(publicModule)
    if arguments.show:
        trafficConfig = siteTotalConfigClass().get_status()
        print(
            json.dumps(
                {
                    "status": True,
                    "site": site or None,
                    "listen": f"{listenAddress}:{SITE_PORT}",
                    "trustedCaddyNetwork": trustedCaddyNetwork,
                    "trustedCaddyInterface": trustedCaddyInterface,
                    "scopedUfwRulePresent": scopedUfwRulePresent(
                        trustedCaddyInterface,
                        trustedCaddyNetwork,
                        listenAddress,
                    ),
                    "siteTotal": {
                        "config": trafficConfig,
                        "serviceActive": subprocess.call(
                            ["systemctl", "is-active", "--quiet", "site_total"]
                        )
                        == 0,
                        "socketReady": os.path.exists(SITE_TOTAL_SOCKET)
                        and stat.S_ISSOCK(os.stat(SITE_TOTAL_SOCKET).st_mode),
                        "extensionReady": os.path.isfile(SITE_TOTAL_EXTENSION_PATH),
                        "requests": siteTrafficRequests(),
                    },
                },
                ensure_ascii=False,
            )
        )
        return

    applicationHealth = checkApplicationHealth()
    wasNginxRunning = nginxIsRunning()
    if not site:
        addSite(publicModule, panelSiteClass)
        site = currentSite(publicModule)
    # AddSite 可能自动把站点端口写入宝塔防火墙；18080 只允许 Docker
    # 网关访问。每次运行都做幂等清理，避免上次中途失败留下规则。
    removeOwnedFirewallRules(publicModule, firewallsClass)
    validateCurrentSite(publicModule, site)
    assertInternalPortClosed(
        publicModule,
        trustedCaddyInterface,
        trustedCaddyNetwork,
        listenAddress,
    )

    managedPaths = [
        NGINX_CONFIG_PATH,
        VHOST_PATH,
        DEFAULT_VHOST_PATH,
        DISABLED_DEFAULT_VHOST_PATH,
        PHPFPM_STATUS_PATH,
        DISABLED_PHPFPM_STATUS_PATH,
        EXTENSION_PATH,
        SITE_TOTAL_EXTENSION_PATH,
    ]
    snapshots = snapshotFiles(managedPaths)
    scopedUfwRuleCreated = False
    try:
        # CreateProxy 会调用宝塔 serviceReload，故必须先把所有 listener 收口。
        disableDefaultPublicVhost()
        restrictPanelAuxiliaryListeners()
        restrictVhostListener(listenAddress, trustedCaddyNetwork)
        validateEffectiveNginxConfig(listenAddress)

        ensureProxy(publicModule, panelSiteClass)
        # 宝塔生成代理配置时可能重写主 vhost；再次强制并验证内部监听。
        restrictVhostListener(listenAddress, trustedCaddyNetwork)
        enableSiteTraffic(siteTotalConfigClass, int(site["id"]))
        trafficRequestsBefore = siteTrafficRequests()
        validateEffectiveNginxConfig(listenAddress)
        scopedUfwRuleCreated = ensureScopedUfwRule(
            trustedCaddyInterface,
            trustedCaddyNetwork,
            listenAddress,
        )
        validateAndStartNginx(listenAddress)
        validateCaddyToNginx(caddyContainerId, applicationHealth["releaseCommit"])
        validateSiteTraffic(listenAddress, trafficRequestsBefore)
    except Exception as originalError:
        firewallRollbackError = None
        if scopedUfwRuleCreated:
            try:
                removeScopedUfwRule(
                    trustedCaddyInterface,
                    trustedCaddyNetwork,
                    listenAddress,
                )
            except Exception as rollbackError:
                firewallRollbackError = rollbackError
        restoreFiles(snapshots)
        if wasNginxRunning:
            try:
                subprocess.check_call([NGINX_BINARY, "-t"])
                subprocess.check_call([NGINX_INIT_SCRIPT, "reload"])
            except Exception as recoveryError:
                raise RuntimeError("宝塔配置失败，且恢复原 Nginx 配置也失败") from recoveryError
        else:
            subprocess.call([NGINX_INIT_SCRIPT, "stop"])
            if nginxIsRunning():
                raise RuntimeError("宝塔配置失败，且 Nginx 未能保持停止状态") from originalError
        if firewallRollbackError:
            raise RuntimeError(
                "宝塔配置失败，且本次新增的窄范围 UFW 规则无法回滚"
            ) from firewallRollbackError
        raise

    print(
        json.dumps(
            {
                "status": True,
                "message": "宝塔 PHP 项目与真实反向代理已注册",
                "site": currentSite(publicModule),
                "listen": f"{listenAddress}:{SITE_PORT}",
                "upstream": APP_URL,
                "trustedCaddyNetwork": trustedCaddyNetwork,
                "trustedCaddyInterface": trustedCaddyInterface,
                "scopedUfwRulePresent": scopedUfwRulePresent(
                    trustedCaddyInterface,
                    trustedCaddyNetwork,
                    listenAddress,
                ),
                "siteTotalRequests": siteTrafficRequests(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": False, "error": str(error)}, ensure_ascii=False))
        sys.exit(1)
