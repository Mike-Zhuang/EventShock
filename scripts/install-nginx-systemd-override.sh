#!/usr/bin/env bash

set -Eeuo pipefail
export LC_ALL=C

readonly DROP_IN_DIR="/etc/systemd/system/nginx.service.d"
readonly DROP_IN_PATH="${DROP_IN_DIR}/eventshock-docker-order.conf"
readonly NGINX_INIT_SCRIPT="/etc/init.d/nginx"

fail() {
  printf '[eventshock-nginx-systemd] 错误：%s\n' "$*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "请使用 sudo 运行此脚本。"
command -v systemctl >/dev/null 2>&1 || fail "系统缺少 systemctl。"
[[ -x "${NGINX_INIT_SCRIPT}" ]] || fail "未找到宝塔 Nginx init 脚本。"
[[ ! -L "${DROP_IN_DIR}" ]] || fail "systemd drop-in 目录不能是符号链接。"
[[ ! -L "${DROP_IN_PATH}" ]] || fail "systemd drop-in 文件不能是符号链接。"

install -d -o root -g root -m 0755 "${DROP_IN_DIR}"
[[ "$(stat -c '%u:%g' "${DROP_IN_DIR}")" == "0:0" ]] \
  || fail "systemd drop-in 目录必须由 root 所有。"
dropInMode="$(stat -c '%a' "${DROP_IN_DIR}")"
(( (8#${dropInMode} & 8#022) == 0 )) \
  || fail "systemd drop-in 目录不能被 group/world 写入。"

temporaryPath="$(mktemp "${DROP_IN_DIR}/.eventshock-docker-order.XXXXXX")"
backupPath="$(mktemp "${DROP_IN_DIR}/.eventshock-docker-order-backup.XXXXXX")"
rm -f -- "${backupPath}"
previousDropInExists=false
dropInReplaced=false
if [[ -f "${DROP_IN_PATH}" ]]; then
  cp -a -- "${DROP_IN_PATH}" "${backupPath}"
  previousDropInExists=true
fi
cleanup() {
  local exitCode=$?
  trap - EXIT
  if ((exitCode != 0)) && [[ "${dropInReplaced}" == "true" ]]; then
    if [[ "${previousDropInExists}" == "true" ]]; then
      mv -f -- "${backupPath}" "${DROP_IN_PATH}" || true
    else
      rm -f -- "${DROP_IN_PATH}"
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true
  fi
  rm -f -- "${temporaryPath}" "${backupPath}"
  exit "${exitCode}"
}
trap cleanup EXIT

printf '%s\n' \
  '[Unit]' \
  'Wants=docker.service' \
  'After=docker.service' \
  'StartLimitIntervalSec=60' \
  'StartLimitBurst=6' \
  '' \
  '[Service]' \
  'Restart=on-failure' \
  'RestartSec=5s' \
  >"${temporaryPath}"
chown root:root "${temporaryPath}"
chmod 0644 "${temporaryPath}"

changed=false
if [[ ! -f "${DROP_IN_PATH}" ]] || ! cmp -s "${temporaryPath}" "${DROP_IN_PATH}"; then
  mv -f -- "${temporaryPath}" "${DROP_IN_PATH}"
  dropInReplaced=true
  changed=true
fi

systemctl daemon-reload
systemctl enable nginx.service >/dev/null

unitAfter="$(systemctl show nginx.service --property=After --value)"
unitWants="$(systemctl show nginx.service --property=Wants --value)"
unitRestart="$(systemctl show nginx.service --property=Restart --value)"
unitDropIns="$(systemctl show nginx.service --property=DropInPaths --value)"
[[ " ${unitAfter} " == *' docker.service '* ]] \
  || fail "nginx.service 尚未排序到 docker.service 之后。"
[[ " ${unitWants} " == *' docker.service '* ]] \
  || fail "nginx.service 尚未建立对 docker.service 的弱依赖。"
[[ "${unitRestart}" == "on-failure" ]] \
  || fail "nginx.service 的启动失败重试策略未生效。"
[[ " ${unitDropIns} " == *" ${DROP_IN_PATH} "* ]] \
  || fail "systemd 未加载 EventShock Nginx drop-in。"

printf '[eventshock-nginx-systemd] changed=%s path=%s\n' \
  "${changed}" "${DROP_IN_PATH}"
