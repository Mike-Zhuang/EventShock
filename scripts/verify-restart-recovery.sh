#!/usr/bin/env bash

set -Eeuo pipefail
export LC_ALL=C

readonly TARGET_ROOT="/opt/eventshock"
readonly SHARED_DIR="${TARGET_ROOT}/shared"
readonly STATE_DIR="/var/lib/eventshock-restart-verification"
readonly PENDING_FILE="${STATE_DIR}/pending.json"
readonly LOG_DIR="${SHARED_DIR}/logs"
readonly BAOTA_ACCESS_LOG="/www/wwwlogs/eventshock.mikezhuang.cn.log"
readonly SITE_TOTAL_ROOT="/www/server/site_total/data/total/eventshock.mikezhuang.cn"
readonly REBOOT_CONFIRMATION="REBOOT_EVENTSHOCK_PRODUCTION_IN_MAINTENANCE_WINDOW"

log() {
  printf '[eventshock-restart-verify] %s\n' "$*"
}

fail() {
  printf '[eventshock-restart-verify] 错误：%s\n' "$*" >&2
  exit 1
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || fail "请使用 sudo 运行此脚本。"
}

require_commands() {
  local commandName
  for commandName in curl docker find jq readlink ss stat systemctl timeout; do
    command -v "${commandName}" >/dev/null 2>&1 \
      || fail "缺少必需命令：${commandName}"
  done
}

current_release() {
  local releasePath
  releasePath="$(readlink -f "${TARGET_ROOT}/current" 2>/dev/null || true)"
  [[ -d "${releasePath}" ]] || return 1
  [[ -x "${releasePath}/scripts/compose-current.sh" ]] || return 1
  printf '%s\n' "${releasePath}"
}

release_commit() {
  local releasePath="$1"
  sed -n 's/^EVENTSHOCK_RELEASE_COMMIT=\([0-9a-f]\{40\}\)$/\1/p' \
    "${releasePath}/.release.env" 2>/dev/null \
    | head -n 1
}

public_origin() {
  local appDomain
  appDomain="$(sed -n 's/^APP_DOMAIN=//p' "${SHARED_DIR}/.env" 2>/dev/null | tail -n 1)"
  [[ -n "${appDomain}" ]] || appDomain="eventshock.mikezhuang.cn"
  [[ "${appDomain}" =~ ^(https?://)?[A-Za-z0-9.-]+(:[0-9]{1,5})?$ ]] || return 1
  if [[ "${appDomain}" == http://* ]] || [[ "${appDomain}" == https://* ]]; then
    printf '%s\n' "${appDomain%/}"
  else
    printf 'https://%s\n' "${appDomain}"
  fi
}

file_size() {
  local path="$1"
  if [[ -f "${path}" ]] && [[ ! -L "${path}" ]]; then
    stat -c '%s' "${path}"
  else
    printf '0\n'
  fi
}

latest_site_total_epoch() {
  if [[ ! -d "${SITE_TOTAL_ROOT}" ]] || [[ -L "${SITE_TOTAL_ROOT}" ]]; then
    printf '0\n'
    return
  fi
  find "${SITE_TOTAL_ROOT}" -type f -printf '%T@\n' 2>/dev/null \
    | sort -nr \
    | head -n 1 \
    | cut -d. -f1 \
    || printf '0\n'
}

cookie_file_is_safe() {
  local cookieFile="$1"
  local mode owner
  [[ "${cookieFile}" == /* ]] || return 1
  [[ -f "${cookieFile}" ]] && [[ ! -L "${cookieFile}" ]] \
    || return 1
  owner="$(stat -c '%u' "${cookieFile}")"
  mode="$(stat -c '%a' "${cookieFile}")"
  [[ "${owner}" == "0" ]] || return 1
  (( (8#${mode} & 8#077) == 0 ))
}

validate_cookie_file() {
  local cookieFile="$1"
  cookie_file_is_safe "${cookieFile}" \
    || fail "Cookie 文件必须是 root 拥有、权限 0600 或更严格的普通绝对路径，且不能是符号链接。"
}

write_pending_state() {
  local expectedCommit="$1"
  local origin="$2"
  local cookieFile="$3"
  local experimentId="$4"
  local accessLogBytes siteTotalEpoch temporaryPath
  accessLogBytes="$(file_size "${BAOTA_ACCESS_LOG}")"
  siteTotalEpoch="$(latest_site_total_epoch)"
  install -d -m 0700 -o root -g root "${STATE_DIR}"
  [[ ! -L "${PENDING_FILE}" ]] || fail "待验证状态文件不能是符号链接。"
  temporaryPath="$(mktemp "${STATE_DIR}/.pending.XXXXXX")"
  jq -cn \
    --arg expectedCommit "${expectedCommit}" \
    --arg publicOrigin "${origin}" \
    --arg preparedAt "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
    --arg cookieFile "${cookieFile}" \
    --arg experimentId "${experimentId}" \
    --argjson accessLogBytes "${accessLogBytes}" \
    --argjson siteTotalEpoch "${siteTotalEpoch}" \
    '{
      schemaVersion: "eventshock_restart_verification_v1",
      expectedCommit: $expectedCommit,
      publicOrigin: $publicOrigin,
      preparedAt: $preparedAt,
      accessLogBytes: $accessLogBytes,
      siteTotalEpoch: $siteTotalEpoch,
      cookieFile: (if $cookieFile == "" then null else $cookieFile end),
      experimentId: (if $experimentId == "" then null else $experimentId end)
    }' >"${temporaryPath}"
  chmod 0600 "${temporaryPath}"
  mv -f -- "${temporaryPath}" "${PENDING_FILE}"
  sync -f "${PENDING_FILE}"
}

prepare_verification() {
  local cookieFile=""
  local experimentId=""
  local requestReboot="false"
  while (($# > 0)); do
    case "$1" in
      --cookie-file)
        (($# >= 2)) || fail "--cookie-file 缺少路径。"
        cookieFile="$2"
        shift 2
        ;;
      --experiment-id)
        (($# >= 2)) || fail "--experiment-id 缺少值。"
        experimentId="$2"
        shift 2
        ;;
      --reboot)
        requestReboot="true"
        shift
        ;;
      *)
        fail "未知 prepare 参数：$1"
        ;;
    esac
  done

  local releasePath expectedCommit origin
  releasePath="$(current_release)" || fail "找不到当前不可变发布目录。"
  expectedCommit="$(release_commit "${releasePath}")"
  [[ "${expectedCommit}" =~ ^[0-9a-f]{40}$ ]] || fail "当前发布缺少可验证的 40 位 SHA。"
  origin="$(public_origin)" || fail "APP_DOMAIN 格式不受支持。"

  if [[ -n "${cookieFile}" ]]; then
    validate_cookie_file "${cookieFile}"
  fi
  if [[ -n "${experimentId}" ]] && [[ -z "${cookieFile}" ]]; then
    fail "提供实验 ID 时必须同时提供 root 专用 Cookie 文件。"
  fi
  if [[ -z "${experimentId}" ]] && [[ -n "${cookieFile}" ]]; then
    experimentId="$(
      curl --fail --silent --show-error \
        --connect-timeout 3 --max-time 10 \
        --cookie "${cookieFile}" \
        "${origin}/api/v1/experiments" \
        | jq -r '.items[]? | select(.status == "COMPLETED") | .id' \
        | head -n 1
    )"
    [[ "${experimentId}" =~ ^exp-[A-Za-z0-9_-]{8,}$ ]] \
      || fail "账号下没有可用于重启后 SSE 与历史验证的已完成实验。"
  fi

  write_pending_state "${expectedCommit}" "${origin}" "${cookieFile}" "${experimentId}"
  log "已保存重启前证据：SHA=${expectedCommit}。"
  if [[ -z "${cookieFile}" ]]; then
    log "尚未提供 Cookie 文件；重启后只能生成基础设施证据，最终门禁会保持 INCOMPLETE。"
  fi
  log "重启后 systemd 会自动运行：${TARGET_ROOT}/bin/verify-restart-recovery.sh verify"

  if [[ "${requestReboot}" == "true" ]]; then
    [[ "${EVENTSHOCK_REBOOT_CONFIRMATION:-}" == "${REBOOT_CONFIRMATION}" ]] \
      || fail "拒绝重启。请在维护窗口显式设置 EVENTSHOCK_REBOOT_CONFIRMATION。"
    log "已确认维护窗口，正在请求系统重启。"
    systemctl reboot
  fi
}

append_check() {
  local checksJson="$1"
  local checkName="$2"
  local status="$3"
  local detail="$4"
  jq -cn \
    --argjson checks "${checksJson}" \
    --arg name "${checkName}" \
    --arg status "${status}" \
    --arg detail "${detail}" \
    '$checks + [{name: $name, status: $status, detail: $detail}]'
}

wait_for_runtime() {
  local expectedCommit="$1"
  local releasePath="$2"
  local deadline=$((SECONDS + 240))
  while ((SECONDS < deadline)); do
    if systemctl is-active --quiet docker.service \
      && systemctl is-active --quiet nginx.service \
      && curl --fail --silent --connect-timeout 2 --max-time 4 \
        http://127.0.0.1:18000/api/health \
        | jq -e --arg expectedCommit "${expectedCommit}" \
          '.status == "ok" and .releaseCommit == $expectedCommit' >/dev/null 2>&1 \
      && "${releasePath}/scripts/compose-current.sh" ps --status running app caddy \
        | grep -q 'app'; then
      return 0
    fi
    sleep 2
  done
  return 1
}

verify_after_reboot() {
  [[ -f "${PENDING_FILE}" ]] && [[ ! -L "${PENDING_FILE}" ]] \
    || fail "没有待验证的重启证据；请先运行 prepare。"
  jq -e '
    .schemaVersion == "eventshock_restart_verification_v1"
    and (.expectedCommit | test("^[0-9a-f]{40}$"))
    and (.publicOrigin | type == "string")
  ' "${PENDING_FILE}" >/dev/null || fail "待验证状态文件格式无效。"

  local expectedCommit origin cookieFile experimentId releasePath
  local checksJson="[]"
  expectedCommit="$(jq -r '.expectedCommit' "${PENDING_FILE}")"
  origin="$(jq -r '.publicOrigin' "${PENDING_FILE}")"
  cookieFile="$(jq -r '.cookieFile // ""' "${PENDING_FILE}")"
  experimentId="$(jq -r '.experimentId // ""' "${PENDING_FILE}")"
  releasePath="$(current_release)" || fail "重启后找不到当前发布目录。"

  if wait_for_runtime "${expectedCommit}" "${releasePath}"; then
    checksJson="$(append_check "${checksJson}" "runtimeRecovery" "PASS" \
      "Docker、Nginx 和本地应用在 240 秒门限内恢复。")"
  else
    checksJson="$(append_check "${checksJson}" "runtimeRecovery" "FAIL" \
      "Docker、Nginx 或本地应用未在 240 秒内恢复。")"
  fi

  local currentCommit appContainer caddyContainer appHealth caddyHealth
  currentCommit="$(release_commit "${releasePath}")"
  appContainer="$("${releasePath}/scripts/compose-current.sh" ps -q app 2>/dev/null || true)"
  caddyContainer="$("${releasePath}/scripts/compose-current.sh" ps -q caddy 2>/dev/null || true)"
  appHealth="$(docker inspect --format \
    '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
    "${appContainer}" 2>/dev/null || true)"
  caddyHealth="$(docker inspect --format \
    '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
    "${caddyContainer}" 2>/dev/null || true)"
  if [[ "${currentCommit}" == "${expectedCommit}" ]] \
    && [[ "${appHealth}" == "healthy" ]] \
    && [[ "${caddyHealth}" == "healthy" ]]; then
    checksJson="$(append_check "${checksJson}" "releaseAndContainers" "PASS" \
      "当前发布 SHA、app 与 caddy 健康状态一致。")"
  else
    checksJson="$(append_check "${checksJson}" "releaseAndContainers" "FAIL" \
      "发布 SHA 或容器健康状态不一致。")"
  fi

  local nginxAfter nginxWants nginxRestart
  nginxAfter="$(systemctl show nginx.service --property=After --value 2>/dev/null || true)"
  nginxWants="$(systemctl show nginx.service --property=Wants --value 2>/dev/null || true)"
  nginxRestart="$(systemctl show nginx.service --property=Restart --value 2>/dev/null || true)"
  if [[ " ${nginxAfter} " == *" docker.service "* ]] \
    && [[ " ${nginxWants} " == *" docker.service "* ]] \
    && [[ "${nginxRestart}" == "on-failure" ]]; then
    checksJson="$(append_check "${checksJson}" "nginxSystemdDependency" "PASS" \
      "Nginx 的 Docker 启动顺序和失败重试 drop-in 生效。")"
  else
    checksJson="$(append_check "${checksJson}" "nginxSystemdDependency" "FAIL" \
      "Nginx 的 Docker 启动顺序或失败重试配置缺失。")"
  fi

  local listenerState
  listenerState="$(ss -ltnH 2>/dev/null || true)"
  if grep -Eq '127\.0\.0\.1:18000[[:space:]]' <<<"${listenerState}" \
    && ! grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\[::\]|\*):18000[[:space:]]' <<<"${listenerState}" \
    && ! grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\[::\]|\*):18080[[:space:]]' <<<"${listenerState}"; then
    checksJson="$(append_check "${checksJson}" "privatePorts" "PASS" \
      "应用 18000 仅回环监听，18080 未绑定公网通配地址。")"
  else
    checksJson="$(append_check "${checksJson}" "privatePorts" "FAIL" \
      "18000 或 18080 的监听边界不符合生产要求。")"
  fi

  local internalProxy
  internalProxy="$(
    timeout 15 "${releasePath}/scripts/compose-current.sh" exec -T caddy \
      curl --fail --silent --connect-timeout 3 --max-time 8 \
      --header 'Host: eventshock.mikezhuang.cn' \
      http://host.docker.internal:18080/api/health 2>/dev/null \
      || true
  )"
  if jq -e --arg expectedCommit "${expectedCommit}" \
    '.status == "ok" and .releaseCommit == $expectedCommit' \
    <<<"${internalProxy}" >/dev/null 2>&1; then
    checksJson="$(append_check "${checksJson}" "caddyToBaotaToApp" "PASS" \
      "Caddy 容器经宝塔 Nginx 到应用的内部健康检查通过。")"
  else
    checksJson="$(append_check "${checksJson}" "caddyToBaotaToApp" "FAIL" \
      "Caddy 经宝塔 Nginx 的内部代理链未返回目标 SHA。")"
  fi

  local publicHealth=""
  local requestIndex
  for requestIndex in 1 2 3; do
    publicHealth="$(
      curl --fail --silent --show-error --connect-timeout 3 --max-time 10 \
        --user-agent EventShock-Restart-Verification \
        "${origin}/api/health?restart-verification=${requestIndex}" 2>/dev/null \
        || true
    )"
  done
  if jq -e --arg expectedCommit "${expectedCommit}" \
    '.status == "ok" and .releaseCommit == $expectedCommit' \
    <<<"${publicHealth}" >/dev/null 2>&1; then
    checksJson="$(append_check "${checksJson}" "publicHealth" "PASS" \
      "公网健康接口返回预期 release SHA。")"
  else
    checksJson="$(append_check "${checksJson}" "publicHealth" "FAIL" \
      "公网健康接口未返回预期 release SHA。")"
  fi

  local beforeAccess currentAccess beforeSiteTotal currentSiteTotal
  beforeAccess="$(jq -r '.accessLogBytes' "${PENDING_FILE}")"
  beforeSiteTotal="$(jq -r '.siteTotalEpoch' "${PENDING_FILE}")"
  currentAccess="$(file_size "${BAOTA_ACCESS_LOG}")"
  currentSiteTotal="$(latest_site_total_epoch)"
  local trafficDeadline=$((SECONDS + 30))
  while ((SECONDS < trafficDeadline)) \
    && ((currentAccess <= beforeAccess || currentSiteTotal <= beforeSiteTotal)); do
    sleep 2
    currentAccess="$(file_size "${BAOTA_ACCESS_LOG}")"
    currentSiteTotal="$(latest_site_total_epoch)"
  done
  if ((currentAccess > beforeAccess)) && ((currentSiteTotal > beforeSiteTotal)); then
    checksJson="$(append_check "${checksJson}" "baotaTraffic" "PASS" \
      "真实公网请求使宝塔 access log 增长，site_total 数据未倒退。")"
  else
    checksJson="$(append_check "${checksJson}" "baotaTraffic" "FAIL" \
      "宝塔 access log 或 site_total 未记录重启后的公网请求。")"
  fi

  local taskDocument
  taskDocument="$(
    /opt/eventshock/bin/register-baota-task.py --show 2>/dev/null || true
  )"
  if jq -e '
    .status == true
    and .task.status == 1
    and .task.type == "minute-n"
    and (.task.where1 | tostring) == "10"
    and (.artifacts.logPath | type == "string")
  ' <<<"${taskDocument}" >/dev/null 2>&1; then
    checksJson="$(append_check "${checksJson}" "baotaScheduledTask" "PASS" \
      "宝塔原生十分钟任务存在、启用且日志路径可读。")"
  else
    checksJson="$(append_check "${checksJson}" "baotaScheduledTask" "FAIL" \
      "宝塔原生任务不存在、被禁用、周期不符或日志不可读。")"
  fi

  if [[ -n "${cookieFile}" ]] && [[ -n "${experimentId}" ]]; then
    if cookie_file_is_safe "${cookieFile}" \
      && curl --fail --silent --connect-timeout 3 --max-time 10 \
        --cookie "${cookieFile}" "${origin}/api/v1/auth/session" \
        | jq -e '.authenticated == true' >/dev/null 2>&1 \
      && curl --fail --silent --connect-timeout 3 --max-time 10 \
        --cookie "${cookieFile}" "${origin}/api/v1/experiments" \
        | jq -e --arg experimentId "${experimentId}" \
          'any(.items[]?; .id == $experimentId)' >/dev/null 2>&1 \
      && curl --fail --silent --no-buffer --connect-timeout 3 --max-time 15 \
        --cookie "${cookieFile}" \
        "${origin}/api/v1/experiments/${experimentId}/events" \
        | grep -Eq '^event: experiment$'; then
      checksJson="$(append_check "${checksJson}" "authenticatedApiAndSse" "PASS" \
        "登录会话、实验历史与实验 SSE 在重启后可用。")"
    else
      checksJson="$(append_check "${checksJson}" "authenticatedApiAndSse" "FAIL" \
        "登录会话、实验历史或实验 SSE 的重启后冒烟测试失败。")"
    fi
  else
    checksJson="$(append_check "${checksJson}" "authenticatedApiAndSse" "NOT_RUN" \
      "未提供 root 专用 Cookie 文件和实验 ID，不能把认证与 SSE 标记为通过。")"
  fi

  local overallStatus evidencePath temporaryEvidence
  if jq -e 'all(.[]; .status == "PASS")' <<<"${checksJson}" >/dev/null; then
    overallStatus="PASS"
  elif jq -e 'any(.[]; .status == "FAIL")' <<<"${checksJson}" >/dev/null; then
    overallStatus="FAIL"
  else
    overallStatus="INCOMPLETE"
  fi
  install -d -m 0750 -o root -g root "${LOG_DIR}"
  evidencePath="${LOG_DIR}/restart-verification-$(date -u +'%Y%m%dT%H%M%SZ').json"
  temporaryEvidence="$(mktemp "${LOG_DIR}/.restart-verification.XXXXXX")"
  jq -cn \
    --arg status "${overallStatus}" \
    --arg expectedCommit "${expectedCommit}" \
    --arg verifiedAt "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
    --argjson checks "${checksJson}" \
    '{
      schemaVersion: "eventshock_restart_evidence_v1",
      status: $status,
      expectedCommit: $expectedCommit,
      verifiedAt: $verifiedAt,
      checks: $checks
    }' >"${temporaryEvidence}"
  chmod 0640 "${temporaryEvidence}"
  mv -f -- "${temporaryEvidence}" "${evidencePath}"
  log "验证状态：${overallStatus}；脱敏证据：${evidencePath}"

  if [[ "${overallStatus}" == "PASS" ]]; then
    rm -f -- "${PENDING_FILE}"
    return 0
  fi
  return 2
}

usage() {
  cat <<'EOF'
用法：
  sudo verify-restart-recovery.sh prepare [--cookie-file /root/cookies.txt] \
    [--experiment-id exp-...] [--reboot]
  sudo verify-restart-recovery.sh verify

prepare 默认不会重启。只有同时传入 --reboot 且环境变量
EVENTSHOCK_REBOOT_CONFIRMATION=REBOOT_EVENTSHOCK_PRODUCTION_IN_MAINTENANCE_WINDOW
时才会请求重启。Cookie 文件只读取、不复制，必须由 root 拥有且权限为 0600；
生成的证据不包含 Cookie、API Key、响应正文或个人信息。
EOF
}

main() {
  require_root
  require_commands
  local commandName="${1:-}"
  case "${commandName}" in
    prepare)
      shift
      prepare_verification "$@"
      ;;
    verify)
      shift
      (($# == 0)) || fail "verify 不接受额外参数。"
      verify_after_reboot
      ;;
    *)
      usage
      exit 64
      ;;
  esac
}

main "$@"
