#!/usr/bin/env bash

set -Eeuo pipefail
export LC_ALL=C

readonly TARGET_ROOT="/opt/eventshock"
readonly SHARED_DIR="${TARGET_ROOT}/shared"
readonly BIN_DIR="${TARGET_ROOT}/bin"
readonly OPERATIONS_ROOT="${TARGET_ROOT}/operations"
readonly LOG_DIR="${SHARED_DIR}/logs"
readonly CONFIG_FILE="${SHARED_DIR}/github-sync.env"
readonly SOURCE_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

fail() {
  printf '[eventshock-sync-install] 错误：%s\n' "$*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "请使用 sudo 运行此脚本。"
[[ -f "${SOURCE_ROOT}/scripts/sync-from-github.sh" ]] \
  || fail "缺少 scripts/sync-from-github.sh。"
[[ -f "${SOURCE_ROOT}/scripts/baota-eventshock-task.sh" ]] \
  || fail "缺少 scripts/baota-eventshock-task.sh。"
[[ -f "${SOURCE_ROOT}/scripts/register-baota-task.py" ]] \
  || fail "缺少 scripts/register-baota-task.py。"
[[ -f "${SOURCE_ROOT}/scripts/register-baota-site.py" ]] \
  || fail "缺少 scripts/register-baota-site.py。"
[[ -f "${SOURCE_ROOT}/scripts/install-nginx-systemd-override.sh" ]] \
  || fail "缺少 scripts/install-nginx-systemd-override.sh。"

missingSystemCommand=0
for localCommand in curl flock git jq tar timeout; do
  if ! command -v "${localCommand}" >/dev/null 2>&1; then
    missingSystemCommand=1
  fi
done
if ((missingSystemCommand == 1)); then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates coreutils curl git jq tar util-linux
fi
command -v docker >/dev/null 2>&1 \
  && docker compose version >/dev/null 2>&1 \
  || fail "Docker Engine 与 Compose 插件尚不可用；请先运行一次 deploy-server.sh。"

for managedPath in "${SHARED_DIR}" "${OPERATIONS_ROOT}" "${LOG_DIR}" "${CONFIG_FILE}"; do
  [[ ! -L "${managedPath}" ]] || fail "受管路径不能是符号链接：${managedPath}"
done
install -d -m 0755 "${SHARED_DIR}" "${OPERATIONS_ROOT}"
install -d -m 0750 "${LOG_DIR}"
chown root:root "${SHARED_DIR}" "${OPERATIONS_ROOT}" "${LOG_DIR}"
chmod 0755 "${SHARED_DIR}" "${OPERATIONS_ROOT}"
chmod 0750 "${LOG_DIR}"

if [[ -e "${BIN_DIR}" ]] && [[ ! -L "${BIN_DIR}" ]]; then
  legacyBin="${OPERATIONS_ROOT}/legacy-$(date -u +'%Y%m%dT%H%M%SZ')-$$"
  mv "${BIN_DIR}" "${legacyBin}"
fi
bootstrapRelease="${OPERATIONS_ROOT}/bootstrap-$(date -u +'%Y%m%dT%H%M%SZ')-$$"
install -d -m 0755 "${bootstrapRelease}"
for scriptName in \
  sync-from-github.sh \
  baota-eventshock-task.sh \
  register-baota-task.py \
  register-baota-site.py \
  install-nginx-systemd-override.sh \
  install-github-sync.sh; do
  install -m 0755 \
    "${SOURCE_ROOT}/scripts/${scriptName}" \
    "${bootstrapRelease}/${scriptName}"
done
ln -sfnT "${bootstrapRelease}" "${BIN_DIR}"
[[ "$(readlink -f "${BIN_DIR}")" == "${bootstrapRelease}" ]] \
  || fail "无法激活原子运维脚本目录。"

# 初次安装时即写入开机顺序；如果宝塔 Nginx 尚未安装，则由后续站点
# 注册流程再次执行同一个安装器。
if [[ -x /etc/init.d/nginx ]]; then
  "${bootstrapRelease}/install-nginx-systemd-override.sh"
else
  printf '[eventshock-sync-install] 宝塔 Nginx 尚未安装，systemd drop-in 延后到站点注册时安装。\n'
fi

if [[ ! -f "${CONFIG_FILE}" ]]; then
  cat >"${CONFIG_FILE}" <<'EOF'
# 公开仓库使用匿名 HTTPS 拉取，不在此文件保存 Token。
EVENTSHOCK_GITHUB_URL=https://github.com/Mike-Zhuang/EventShock.git
EVENTSHOCK_GITHUB_BRANCH=main
EVENTSHOCK_GITHUB_REPOSITORY=Mike-Zhuang/EventShock
EOF
fi
chown root:root "${CONFIG_FILE}"
chmod 0600 "${CONFIG_FILE}"

[[ ! -L /etc/logrotate.d/eventshock-github-sync ]] \
  || fail "logrotate 配置不能是符号链接。"
cat >/etc/logrotate.d/eventshock-github-sync <<'EOF'
/opt/eventshock/shared/logs/github-sync.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    su root root
}
EOF
chmod 0644 /etc/logrotate.d/eventshock-github-sync

printf '[eventshock-sync-install] 已安装：%s\n' "${BIN_DIR}/sync-from-github.sh"
printf '[eventshock-sync-install] 宝塔任务入口：%s\n' "${BIN_DIR}/baota-eventshock-task.sh"
printf '[eventshock-sync-install] 配置：%s\n' "${CONFIG_FILE}"
printf '[eventshock-sync-install] 本脚本不会自行写系统 crontab；必须通过宝塔 AddCrontab 注册，前端与原生日志才会同步可见。\n'
