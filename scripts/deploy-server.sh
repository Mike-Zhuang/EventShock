#!/usr/bin/env bash

set -Eeuo pipefail
export LC_ALL=C

readonly TARGET_ROOT="/opt/eventshock"
readonly SHARED_DIR="${TARGET_ROOT}/shared"
readonly SHARED_SECRETS_DIR="${SHARED_DIR}/secrets"
readonly ADMIN_API_KEY_ENCRYPTION_KEY_FILE="${SHARED_SECRETS_DIR}/admin-api-key-encryption-key"
readonly ADMIN_BOOTSTRAP_PASSWORD_FILE="${SHARED_SECRETS_DIR}/admin-bootstrap-password.once"
readonly RELEASES_DIR="${TARGET_ROOT}/releases"
DEFAULT_SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly DEFAULT_SOURCE_ROOT
SOURCE_ROOT="${1:-${DEFAULT_SOURCE_ROOT}}"
readonly SOURCE_ROOT
ROLLBACK_RELEASE=""
DEPLOY_ATTEMPTED=0
DEPLOY_SUCCEEDED=0
CREATED_RELEASE_DIR=""
RELEASE_COMMIT="${EVENTSHOCK_RELEASE_COMMIT:-manual}"
readonly RELEASE_COMMIT

log() {
  printf '[eventshock] %s\n' "$*"
}

fail() {
  printf '[eventshock] 错误：%s\n' "$*" >&2
  exit 1
}

run_compose() {
  local releaseDir="$1"
  shift
  local composeArguments=(
    --project-directory "${releaseDir}"
    --file "${releaseDir}/compose.yml"
    --env-file "${SHARED_DIR}/.env"
  )
  if [[ -f "${releaseDir}/.release.env" ]]; then
    composeArguments+=(--env-file "${releaseDir}/.release.env")
  fi
  env \
    -u APP_DOMAIN \
    -u APP_ENV \
    -u CADDY_STARTUP_GATE_TIMEOUT_SECONDS \
    -u CADDY_UPSTREAM \
    -u COMPOSE_FILE \
    -u COMPOSE_PROJECT_NAME \
    -u EVENTSHOCK_ADMIN_EMAIL \
    -u EVENTSHOCK_APP_HOST_PORT \
    -u EVENTSHOCK_APP_IMAGE \
    -u EVENTSHOCK_AUTH_COOKIE_SECURE \
    -u EVENTSHOCK_AUTH_REQUIRED \
    -u EVENTSHOCK_DEPLOYMENT_STATUS_FILE \
    -u EVENTSHOCK_RELEASE_COMMIT \
    -u EVENTSHOCK_SECRETS_DIR \
    -u EVENTSHOCK_SMTP_HOST \
    -u EVENTSHOCK_SMTP_PORT \
    -u EVENTSHOCK_SMTP_SENDER \
    -u EVENTSHOCK_SMTP_USERNAME \
    -u LOG_LEVEL \
    docker compose --project-name eventshock "${composeArguments[@]}" "$@"
}

rollback_on_exit() {
  local exitCode=$?
  trap - EXIT

  if ((exitCode == 0)) || ((DEPLOY_SUCCEEDED == 1)); then
    return
  fi
  if ((DEPLOY_ATTEMPTED == 0)); then
    cleanup_created_release
    exit "${exitCode}"
  fi
  if [[ -z "${ROLLBACK_RELEASE}" ]] || [[ ! -d "${ROLLBACK_RELEASE}" ]]; then
    printf '[eventshock] 部署失败，且没有可用的上一版本可自动恢复。\n' >&2
    set +e
    if [[ -n "${CREATED_RELEASE_DIR}" ]] && [[ -d "${CREATED_RELEASE_DIR}" ]]; then
      run_compose "${CREATED_RELEASE_DIR}" down --remove-orphans
    fi
    cleanup_created_release
    set -e
    exit "${exitCode}"
  fi

  printf '[eventshock] 部署失败，正在恢复并验证上一版本：%s\n' "${ROLLBACK_RELEASE}" >&2
  set +e
  run_compose "${ROLLBACK_RELEASE}" up -d --remove-orphans
  local rollbackStatus=$?
  local rollbackCommit
  rollbackCommit="$(release_commit_for "${ROLLBACK_RELEASE}" 2>/dev/null)"
  if ((rollbackStatus == 0)); then
    wait_for_health "${ROLLBACK_RELEASE}"
    rollbackStatus=$?
  fi
  if ((rollbackStatus == 0)); then
    ensure_baota_proxy "${ROLLBACK_RELEASE}"
    rollbackStatus=$?
  fi
  if ((rollbackStatus == 0)) && [[ -n "${rollbackCommit}" ]]; then
    verify_public_endpoint "${ROLLBACK_RELEASE}" "${rollbackCommit}"
    rollbackStatus=$?
  elif ((rollbackStatus == 0)); then
    printf '[eventshock] 上一版本缺少可验证的 release commit，不能声称精确回滚成功。\n' >&2
    rollbackStatus=1
  fi
  if ((rollbackStatus == 0)); then
    ln -sfnT "${ROLLBACK_RELEASE}" "${TARGET_ROOT}/current"
    rollbackStatus=$?
  fi
  set -e
  if ((rollbackStatus == 0)); then
    printf '[eventshock] 上一版本已恢复，并通过容器健康与公网 SHA 检查。\n' >&2
    cleanup_created_release
  else
    printf '[eventshock] 自动恢复未通过完整验证，请立即检查 Docker 与公网日志。\n' >&2
  fi
  exit "${exitCode}"
}

cleanup_created_release() {
  local imageName
  [[ -n "${CREATED_RELEASE_DIR}" ]] || return
  [[ "${CREATED_RELEASE_DIR}" == "${RELEASES_DIR}"/* ]] || return
  [[ -d "${CREATED_RELEASE_DIR}" ]] || return
  imageName="$(
    sed -n 's/^EVENTSHOCK_APP_IMAGE=//p' \
      "${CREATED_RELEASE_DIR}/.release.env" 2>/dev/null \
      | tail -n 1 \
      || true
  )"
  if [[ "${imageName}" =~ ^eventshock-app:[A-Za-z0-9_.-]+$ ]] \
    && docker image inspect "${imageName}" >/dev/null 2>&1; then
    if ! docker image rm "${imageName}" >/dev/null 2>&1; then
      printf '[eventshock] 失败发布镜像仍被引用，保留发布元数据：%s\n' \
        "${CREATED_RELEASE_DIR}" >&2
      return
    fi
  fi
  if rm -rf -- "${CREATED_RELEASE_DIR}"; then
    printf '[eventshock] 已清理失败发布：%s\n' "${CREATED_RELEASE_DIR}" >&2
  else
    printf '[eventshock] 无法清理失败发布：%s\n' "${CREATED_RELEASE_DIR}" >&2
  fi
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || fail "请使用 sudo 运行此脚本。"
}

check_platform() {
  [[ -r /etc/os-release ]] || fail "无法读取 /etc/os-release。"

  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || fail "此脚本仅支持 Ubuntu。"
  [[ "${VERSION_ID:-}" == "22.04" ]] || fail "目标服务器必须是 Ubuntu 22.04。"
  [[ "$(dpkg --print-architecture)" == "amd64" ]] || fail "目标服务器必须是 x86_64/amd64。"
}

check_source() {
  [[ -d "${SOURCE_ROOT}" ]] || fail "源码目录不存在：${SOURCE_ROOT}"

  local requiredFile
  for requiredFile in Dockerfile compose.yml Caddyfile .env.example pyproject.toml; do
    [[ -f "${SOURCE_ROOT}/${requiredFile}" ]] || fail "源码目录缺少 ${requiredFile}。"
  done

  [[ -f "${SOURCE_ROOT}/frontend/package-lock.json" ]] || fail "源码目录缺少 frontend/package-lock.json。"
  [[ -f "${SOURCE_ROOT}/frontend/dist/index.html" ]] || fail "源码目录缺少已验证的 frontend/dist/index.html。"
  [[ -f "${SOURCE_ROOT}/backend/app/main.py" ]] || fail "源码目录缺少 backend/app/main.py。"
  [[ -x "${SOURCE_ROOT}/scripts/register-baota-site.py" ]] \
    || fail "源码目录缺少可执行的 scripts/register-baota-site.py。"
  [[ -x "${SOURCE_ROOT}/scripts/install-nginx-systemd-override.sh" ]] \
    || fail "源码目录缺少可执行的 Nginx systemd 安装器。"
  [[ -x "${SOURCE_ROOT}/scripts/caddy-startup-gate.sh" ]] \
    || fail "源码目录缺少可执行的 Caddy 启动门控。"
  [[ -x "${SOURCE_ROOT}/scripts/verify-restart-recovery.sh" ]] \
    || fail "源码目录缺少可执行的受控重启恢复验证器。"
  compgen -G "${SOURCE_ROOT}/event-packs/*/manifest.json" >/dev/null \
    || fail "源码目录没有可部署的 event-packs/*/manifest.json。"
}

check_release_commit() {
  if [[ "${RELEASE_COMMIT}" == "manual" ]]; then
    return
  fi
  [[ "${RELEASE_COMMIT}" =~ ^[0-9a-f]{40}$ ]] \
    || fail "EVENTSHOCK_RELEASE_COMMIT 必须是完整的 40 位小写 Git SHA。"
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    if ! command -v curl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
      export DEBIAN_FRONTEND=noninteractive
      apt-get update
      apt-get install -y --no-install-recommends ca-certificates curl jq
    fi
    systemctl enable --now docker
    docker version >/dev/null
    log "Docker Engine 与 Compose 插件已存在，跳过 APT 配置和软件包升级。"
    return
  fi

  log "配置 Docker 官方 APT 软件源。"
  export DEBIAN_FRONTEND=noninteractive

  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl jq
  install -m 0755 -d /etc/apt/keyrings
  curl --fail --silent --show-error --location \
    https://download.docker.com/linux/ubuntu/gpg \
    --output /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  # shellcheck disable=SC1091
  source /etc/os-release
  printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' \
    "${VERSION_CODENAME}" "$(dpkg --print-architecture)" \
    > /etc/apt/sources.list.d/docker.sources

  apt-get update
  apt-get install -y --no-install-recommends \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

  systemctl enable --now docker
  docker version >/dev/null
  docker compose version >/dev/null
}

verify_firewall() {
  if ! command -v ufw >/dev/null 2>&1; then
    log "未检测到 UFW；请在云安全组确认 TCP 80/443 已放行。"
    return
  fi

  local ufwStatus
  ufwStatus="$(ufw status)"
  printf '%s\n' "${ufwStatus}"

  if grep -q '^Status: inactive' <<<"${ufwStatus}"; then
    log "UFW 当前未启用；脚本不会启用或修改它。请在阿里云安全组确认 TCP 80/443。"
    return
  fi

  local port
  for port in 80 443; do
    if ! grep -Eq "^(${port}(/tcp)?|([0-9]+,)*${port}(,[0-9]+)*/tcp|Anywhere)[[:space:]]+ALLOW" <<<"${ufwStatus}"; then
      fail "UFW 未显示 TCP ${port} 的允许规则；脚本不会自动修改现有规则。"
    fi
  done

  log "UFW 已显示 TCP 80/443 允许规则；未修改任何防火墙规则。"
}

report_existing_listeners() {
  local listeners
  listeners="$(ss -ltnp '( sport = :80 or sport = :443 )' 2>/dev/null || true)"
  if [[ -n "${listeners}" ]] && [[ "$(wc -l <<<"${listeners}")" -gt 1 ]]; then
    log "检测到 80/443 已有监听。脚本不会停止宝塔或其他服务；若不是现有 EventShock Caddy，部署会因端口冲突而安全失败。"
    printf '%s\n' "${listeners}"
  fi
}

create_release() {
  local releaseId releaseDir
  if [[ "${RELEASE_COMMIT}" == "manual" ]]; then
    releaseId="$(date -u +'%Y%m%dT%H%M%SZ')-manual-$$"
  else
    releaseId="$(date -u +'%Y%m%dT%H%M%SZ')-${RELEASE_COMMIT:0:12}"
  fi
  releaseDir="${RELEASES_DIR}/${releaseId}"

  install -d -m 0755 "${SHARED_DIR}" "${RELEASES_DIR}" "${releaseDir}"

  tar \
    --exclude='./.git' \
    --exclude='.env' \
    --exclude='.env.*' \
    --exclude='.npmrc' \
    --exclude='.pypirc' \
    --exclude='.netrc' \
    --exclude='*.pem' \
    --exclude='*.key' \
    --exclude='*.p12' \
    --exclude='*.pfx' \
    --exclude='.eventshock-data' \
    --exclude='.eventshock-secrets' \
    --exclude='*.db' \
    --exclude='*.db-*' \
    --exclude='*.sqlite' \
    --exclude='*.sqlite3' \
    --exclude='./frontend/node_modules' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='.ruff_cache' \
    -C "${SOURCE_ROOT}" -cf - . \
    | tar -C "${releaseDir}" -xf -
  install -m 0644 "${SOURCE_ROOT}/.env.example" "${releaseDir}/.env.example"

  if [[ ! -f "${SHARED_DIR}/.env" ]]; then
    install -m 0600 "${releaseDir}/.env.example" "${SHARED_DIR}/.env"
    log "已从 .env.example 创建 ${SHARED_DIR}/.env。"
  fi
  ln -s "${SHARED_DIR}/.env" "${releaseDir}/.env"
  {
    printf 'EVENTSHOCK_APP_IMAGE=eventshock-app:%s\n' "${releaseId}"
    printf 'EVENTSHOCK_RELEASE_COMMIT=%s\n' "${RELEASE_COMMIT}"
  } >"${releaseDir}/.release.env"
  chmod 0600 "${releaseDir}/.release.env"
  CREATED_RELEASE_DIR="${releaseDir}"
}

shared_env_value() {
  local key="$1"
  sed -n "s/^${key}=//p" "${SHARED_DIR}/.env" | tail -n 1
}

ensure_admin_api_key_encryption_key() {
  local directoryOwner directoryGroup directoryMode temporaryPath

  [[ -d "${SHARED_SECRETS_DIR}" ]] && [[ ! -L "${SHARED_SECRETS_DIR}" ]] \
    || fail "密钥目录必须是普通目录且不能是符号链接。"
  read -r directoryOwner directoryGroup directoryMode \
    < <(stat -c '%u %g %a' "${SHARED_SECRETS_DIR}")
  [[ "${directoryOwner}:${directoryGroup}:${directoryMode}" == "0:10001:750" ]] \
    || fail "密钥目录权限必须精确为 root:10001 0750。"

  # 既有文件（包括悬空符号链接）绝不被覆盖；其安全性由下一步
  # 统一校验。这使重试和失败回滚都继续使用同一把主密钥。
  if [[ -e "${ADMIN_API_KEY_ENCRYPTION_KEY_FILE}" ]] \
    || [[ -L "${ADMIN_API_KEY_ENCRYPTION_KEY_FILE}" ]]; then
    return
  fi

  temporaryPath="$(
    mktemp "${SHARED_SECRETS_DIR}/.admin-api-key-encryption-key.XXXXXX"
  )" || fail "无法创建管理员 API Key 加密主密钥临时文件。"
  if ! head -c 32 /dev/urandom \
    | base64 --wrap=0 \
    | tr '+/' '-_' \
    >"${temporaryPath}"; then
    rm -f -- "${temporaryPath}"
    fail "无法生成管理员 API Key 加密主密钥。"
  fi
  if ! chown root:10001 "${temporaryPath}" || ! chmod 0440 "${temporaryPath}"; then
    rm -f -- "${temporaryPath}"
    fail "无法收紧管理员 API Key 加密主密钥权限。"
  fi

  # 同目录硬链接创建是原子的，且目标已存在时必然失败，避免并发
  # 部署把已投入使用的主密钥替换掉。
  if ln -- "${temporaryPath}" "${ADMIN_API_KEY_ENCRYPTION_KEY_FILE}" 2>/dev/null; then
    log "已生成服务器端管理员 API Key 加密主密钥。"
  elif [[ ! -e "${ADMIN_API_KEY_ENCRYPTION_KEY_FILE}" ]] \
    && [[ ! -L "${ADMIN_API_KEY_ENCRYPTION_KEY_FILE}" ]]; then
    rm -f -- "${temporaryPath}"
    fail "无法原子安装管理员 API Key 加密主密钥。"
  fi
  rm -f -- "${temporaryPath}"
}

validate_auth_configuration() {
  local directoryOwner directoryGroup directoryMode path fileOwner fileGroup fileMode fileSize
  [[ -f "${SHARED_DIR}/.env" ]] || fail "缺少 root 专用共享配置：${SHARED_DIR}/.env"
  [[ "$(shared_env_value EVENTSHOCK_AUTH_REQUIRED)" == "true" ]] \
    || fail "EVENTSHOCK_AUTH_REQUIRED 必须为 true。"
  [[ "$(shared_env_value EVENTSHOCK_AUTH_COOKIE_SECURE)" == "true" ]] \
    || fail "EVENTSHOCK_AUTH_COOKIE_SECURE 必须为 true。"
  [[ "$(shared_env_value EVENTSHOCK_DEPLOYMENT_STATUS_FILE)" == "/data/deployment-status.json" ]] \
    || fail "EVENTSHOCK_DEPLOYMENT_STATUS_FILE 必须精确为 /data/deployment-status.json。"
  [[ -n "$(shared_env_value EVENTSHOCK_ADMIN_EMAIL)" ]] \
    || fail "EVENTSHOCK_ADMIN_EMAIL 不能为空。"
  [[ -n "$(shared_env_value EVENTSHOCK_SMTP_HOST)" ]] \
    || fail "EVENTSHOCK_SMTP_HOST 不能为空。"
  [[ -n "$(shared_env_value EVENTSHOCK_SMTP_USERNAME)" ]] \
    || fail "EVENTSHOCK_SMTP_USERNAME 不能为空。"
  [[ -n "$(shared_env_value EVENTSHOCK_SMTP_SENDER)" ]] \
    || fail "EVENTSHOCK_SMTP_SENDER 不能为空。"
  [[ "$(shared_env_value EVENTSHOCK_SECRETS_DIR)" == "${SHARED_SECRETS_DIR}" ]] \
    || fail "EVENTSHOCK_SECRETS_DIR 必须精确指向 ${SHARED_SECRETS_DIR}。"

  [[ -d "${SHARED_SECRETS_DIR}" ]] && [[ ! -L "${SHARED_SECRETS_DIR}" ]] \
    || fail "密钥目录必须是普通目录且不能是符号链接。"
  read -r directoryOwner directoryGroup directoryMode \
    < <(stat -c '%u %g %a' "${SHARED_SECRETS_DIR}")
  [[ "${directoryOwner}:${directoryGroup}:${directoryMode}" == "0:10001:750" ]] \
    || fail "密钥目录权限必须精确为 root:10001 0750。"

  for path in \
    "${SHARED_SECRETS_DIR}/auth-secret" \
    "${ADMIN_API_KEY_ENCRYPTION_KEY_FILE}" \
    "${SHARED_SECRETS_DIR}/smtp-password"; do
    [[ -f "${path}" ]] && [[ ! -L "${path}" ]] \
      || fail "长期密钥必须是普通文件且不能是符号链接：$(basename "${path}")"
    read -r fileOwner fileGroup fileMode < <(stat -c '%u %g %a' "${path}")
    [[ "${fileOwner}:${fileGroup}:${fileMode}" == "0:10001:440" ]] \
      || fail "长期密钥权限必须精确为 root:10001 0440：$(basename "${path}")"
    fileSize="$(stat -c '%s' "${path}")"
    [[ "${fileSize}" -ge 1 ]] && [[ "${fileSize}" -le 4096 ]] \
      || fail "长期密钥文件大小不合法：$(basename "${path}")"
  done
  [[ "$(stat -c '%s' "${SHARED_SECRETS_DIR}/auth-secret")" -ge 32 ]] \
    || fail "认证随机密钥至少需要 32 字节。"
  [[ "$(stat -c '%s' "${ADMIN_API_KEY_ENCRYPTION_KEY_FILE}")" -eq 44 ]] \
    || fail "管理员 API Key 加密主密钥必须是 44 字节 Fernet 密钥。"
  LC_ALL=C grep -Eq '^[A-Za-z0-9_-]{43}=$' "${ADMIN_API_KEY_ENCRYPTION_KEY_FILE}" \
    || fail "管理员 API Key 加密主密钥格式无效。"

  if [[ -e "${ADMIN_BOOTSTRAP_PASSWORD_FILE}" ]]; then
    [[ -f "${ADMIN_BOOTSTRAP_PASSWORD_FILE}" ]] \
      && [[ ! -L "${ADMIN_BOOTSTRAP_PASSWORD_FILE}" ]] \
      || fail "一次性管理员引导路径必须是普通文件且不能是符号链接。"
    read -r fileOwner fileGroup fileMode \
      < <(stat -c '%u %g %a' "${ADMIN_BOOTSTRAP_PASSWORD_FILE}")
    [[ "${fileOwner}:${fileGroup}:${fileMode}" == "0:0:400" ]] \
      || fail "一次性管理员引导文件权限必须精确为 root:root 0400。"
    fileSize="$(stat -c '%s' "${ADMIN_BOOTSTRAP_PASSWORD_FILE}")"
    [[ "${fileSize}" -ge 8 ]] && [[ "${fileSize}" -le 513 ]] \
      || fail "一次性管理员密码文件大小必须为 8–513 字节（含可选换行）。"
  fi
}

backup_database() {
  local releaseDir="$1"
  local currentRelease appContainerId backupName
  currentRelease="$(readlink -f "${TARGET_ROOT}/current" 2>/dev/null || true)"
  if [[ -z "${currentRelease}" ]] || [[ ! -d "${currentRelease}" ]]; then
    log "首次部署没有现有数据库，跳过发布前备份。"
    return
  fi
  appContainerId="$(run_compose "${currentRelease}" ps -q app)"
  [[ -n "${appContainerId}" ]] || fail "发布前找不到当前 app 容器，拒绝更新。"
  backupName="pre-$(basename "${releaseDir}").db"
  log "使用 SQLite online backup 创建发布前备份：${backupName}"
  docker exec -i "${appContainerId}" python - "${backupName}" <<'PY'
import os
import sqlite3
import sys
from pathlib import Path

source_path = Path("/data/eventshock.db")
backup_dir = Path("/data/deployment-backups")
if not source_path.is_file():
    raise SystemExit("source database does not exist")
backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
target_path = backup_dir / sys.argv[1]
temporary_path = backup_dir / f".{sys.argv[1]}.tmp"
temporary_path.unlink(missing_ok=True)
try:
    with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as source:
        with sqlite3.connect(temporary_path) as target:
            source.backup(target)
            check_result = target.execute("PRAGMA quick_check").fetchone()
            if check_result != ("ok",):
                raise RuntimeError(f"backup quick_check failed: {check_result!r}")
    with temporary_path.open("rb") as backup_file:
        os.fsync(backup_file.fileno())
    os.replace(temporary_path, target_path)
    directory_fd = os.open(backup_dir, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    # WAL 模式会为临时备份建立同名前缀的 sidecar。只清理本轮精确路径，
    # 避免历史垃圾增长，也不触碰已经原子落盘的正式备份。
    for temporary_artifact in (
        temporary_path,
        Path(f"{temporary_path}-wal"),
        Path(f"{temporary_path}-shm"),
    ):
        temporary_artifact.unlink(missing_ok=True)
backups = sorted(backup_dir.glob("pre-*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
for stale_backup in backups[3:]:
    stale_backup.unlink()
PY
}

bootstrap_admin_if_requested() {
  local releaseDir="$1"
  local appContainerId fileOwner fileMode

  [[ -e "${ADMIN_BOOTSTRAP_PASSWORD_FILE}" ]] || {
    log "未检测到一次性管理员引导文件，跳过管理员引导。"
    return
  }
  [[ -f "${ADMIN_BOOTSTRAP_PASSWORD_FILE}" ]] \
    && [[ ! -L "${ADMIN_BOOTSTRAP_PASSWORD_FILE}" ]] \
    || fail "一次性管理员引导路径必须是普通文件且不能是符号链接。"

  fileOwner="$(stat -c '%u' "${ADMIN_BOOTSTRAP_PASSWORD_FILE}")"
  fileMode="$(stat -c '%a' "${ADMIN_BOOTSTRAP_PASSWORD_FILE}")"
  [[ "${fileOwner}" == "0" ]] || fail "一次性管理员引导文件必须由 root 拥有。"
  [[ "${fileMode}" == "400" ]] || fail "一次性管理员引导文件权限必须精确为 0400。"

  appContainerId="$(run_compose "${releaseDir}" ps -q app)"
  [[ -n "${appContainerId}" ]] || fail "管理员引导前找不到新版本 app 容器。"

  log "通过受限标准输入执行一次性管理员引导。"
  if ! docker exec -i "${appContainerId}" \
    python -m backend.app.auth.bootstrap_admin \
    <"${ADMIN_BOOTSTRAP_PASSWORD_FILE}"; then
    fail "管理员引导失败；一次性凭据已保留以便安全重试。"
  fi
  rm -f -- "${ADMIN_BOOTSTRAP_PASSWORD_FILE}" \
    || fail "管理员已引导，但一次性凭据未能删除，拒绝继续发布。"
  log "管理员引导完成，一次性凭据已删除。"
}

verify_auth_migration() {
  local releaseDir="$1"
  local appContainerId
  appContainerId="$(run_compose "${releaseDir}" ps -q app)"
  [[ -n "${appContainerId}" ]] || fail "认证迁移验证前找不到新版本 app 容器。"

  log "验证管理员存在且历史数据已完成账号归属。"
  docker exec -i "${appContainerId}" python - <<'PY'
from backend.app.auth import AuthRepository, UserRole, normalizeEmail
from backend.app.config import loadSettings
from backend.app.database import Database

settings = loadSettings()
if not settings.adminEmail:
    raise SystemExit("configured administrator email is missing")
database = Database(settings.databasePath)
database.initialize()
repository = AuthRepository(database)
repository.initialize()
admin = repository.getUserByEmail(normalizeEmail(settings.adminEmail))
if admin is None or admin["role"] != UserRole.ADMIN.value:
    raise SystemExit("configured administrator account does not exist")
unowned = database.countUnownedRecords()
if any(unowned.values()):
    raise SystemExit("legacy ownership migration is incomplete")
print("authentication ownership migration verified")
PY
}

wait_for_health() {
  local composeDirectory="$1"
  local appContainerId healthStatus remaining

  appContainerId="$(run_compose "${composeDirectory}" ps -q app)"
  if [[ -z "${appContainerId}" ]]; then
    log "未找到 app 容器。"
    return 1
  fi

  remaining=30
  while ((remaining > 0)); do
    healthStatus="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${appContainerId}")"
    if [[ "${healthStatus}" == "healthy" ]]; then
      log "应用健康检查通过。"
      return
    fi
    if [[ "${healthStatus}" == "unhealthy" ]] || [[ "${healthStatus}" == "exited" ]]; then
      run_compose "${composeDirectory}" logs --tail=100 app >&2
      log "应用容器状态为 ${healthStatus}。"
      return 1
    fi
    sleep 2
    remaining=$((remaining - 1))
  done

  run_compose "${composeDirectory}" logs --tail=100 app >&2
  log "应用未在 60 秒内通过健康检查。"
  return 1
}

release_commit_for() {
  local releaseDir="$1"
  local releaseCommit
  [[ -f "${releaseDir}/.release.env" ]] || return 1
  releaseCommit="$(sed -n 's/^EVENTSHOCK_RELEASE_COMMIT=//p' \
    "${releaseDir}/.release.env" | tail -n 1)"
  [[ "${releaseCommit}" == "manual" ]] || [[ "${releaseCommit}" =~ ^[0-9a-f]{40}$ ]] \
    || return 1
  printf '%s\n' "${releaseCommit}"
}

verify_public_endpoint() {
  local composeDirectory="$1"
  local expectedCommit="$2"
  local appDomain endpoint healthResponse remaining
  appDomain="$(sed -n 's/^APP_DOMAIN=//p' "${SHARED_DIR}/.env" | tail -n 1)"
  [[ -n "${appDomain}" ]] || appDomain="eventshock.mikezhuang.cn"

  if [[ ! "${appDomain}" =~ ^(https?://)?[A-Za-z0-9.-]+(:[0-9]{1,5})?$ ]]; then
    log "APP_DOMAIN 格式不受支持；请使用无引号的域名或 http(s) URL。"
    return 1
  fi

  if [[ "${appDomain}" == http://* ]] || [[ "${appDomain}" == https://* ]]; then
    endpoint="${appDomain%/}/api/health"
  else
    endpoint="https://${appDomain}/api/health"
  fi

  remaining=12
  while ((remaining > 0)); do
    if healthResponse="$(curl --fail --silent --location --connect-timeout 2 --max-time 5 "${endpoint}")"; then
      if jq -e --arg expectedCommit "${expectedCommit}" \
        '.status == "ok" and .releaseCommit == $expectedCommit' \
        <<<"${healthResponse}" >/dev/null 2>&1; then
        log "公网健康检查通过：${endpoint}，release=${expectedCommit}"
        return
      fi
      log "公网端点可访问，但尚未返回目标版本 ${expectedCommit}。"
    fi
    remaining=$((remaining - 1))
    if ((remaining > 0)); then
      sleep 5
    fi
  done

  log "容器已启动，但公网健康检查未通过：${endpoint}"
  run_compose "${composeDirectory}" logs --tail=60 caddy >&2 || true
  return 1
}

baota_proxy_enabled() {
  local configuredUpstream
  configuredUpstream="$(sed -n 's/^CADDY_UPSTREAM=//p' "${SHARED_DIR}/.env" 2>/dev/null \
    | tail -n 1)"
  [[ "${configuredUpstream}" == "host.docker.internal:18080" ]]
}

ensure_baota_proxy() {
  local composeDirectory="$1"
  local gatewayAddress registrar
  if ! baota_proxy_enabled; then
    log "生产部署要求 CADDY_UPSTREAM=host.docker.internal:18080，拒绝绕过宝塔流量统计链路。"
    return 1
  fi
  registrar="${composeDirectory}/scripts/register-baota-site.py"
  if [[ ! -x "${registrar}" ]]; then
    log "当前发布缺少可执行的宝塔站点注册器。"
    return 1
  fi
  gatewayAddress="$(
    run_compose "${composeDirectory}" exec -T caddy \
      getent hosts host.docker.internal \
      | awk 'NR == 1 {print $1}'
  )"
  if [[ ! "${gatewayAddress}" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
    log "无法从 Caddy 容器解析 Docker host-gateway。"
    return 1
  fi
  log "校验并自愈 Caddy → 宝塔 Nginx → 应用链路。"
  timeout 180 "${registrar}" --listen-address "${gatewayAddress}"
}

prepare_baota_logging_before_auth() {
  local releaseDir="$1"
  local currentRelease
  currentRelease="$(readlink -f "${TARGET_ROOT}/current" 2>/dev/null || true)"
  if [[ -z "${currentRelease}" ]] || [[ ! -d "${currentRelease}" ]]; then
    log "首次部署尚无公网认证流量，宝塔站点将在应用启动后初始化。"
    return
  fi
  log "认证应用启动前先安装并验收宝塔凭据脱敏日志格式。"
  if ! ensure_baota_proxy "${releaseDir}"; then
    fail "无法在认证应用启动前完成宝塔日志脱敏，拒绝发布。"
  fi
}

cleanup_old_releases() {
  local currentRelease releaseDir imageName index cleanupFailed
  currentRelease="$(readlink -f "${TARGET_ROOT}/current" 2>/dev/null || true)"
  index=0
  cleanupFailed=0
  while IFS= read -r releaseDir; do
    index=$((index + 1))
    if ((index <= 5)) \
      || [[ "${releaseDir}" == "${currentRelease}" ]] \
      || [[ "${releaseDir}" == "${ROLLBACK_RELEASE}" ]]; then
      continue
    fi
    [[ "${releaseDir}" == "${RELEASES_DIR}"/* ]] || continue
    imageName="$(
      sed -n 's/^EVENTSHOCK_APP_IMAGE=//p' \
        "${releaseDir}/.release.env" 2>/dev/null \
        | tail -n 1 \
        || true
    )"
    if [[ ! "${imageName}" =~ ^eventshock-app:[A-Za-z0-9_.-]+$ ]]; then
      log "旧发布缺少受管镜像标签，保留以便人工核对：${releaseDir}"
      cleanupFailed=1
      continue
    fi
    if docker image inspect "${imageName}" >/dev/null 2>&1; then
      if ! docker image rm "${imageName}" >/dev/null 2>&1; then
        log "旧镜像仍被引用，连同发布元数据一起保留：${imageName}"
        cleanupFailed=1
        continue
      fi
    fi
    if rm -rf -- "${releaseDir}"; then
      log "已删除超过保留窗口的旧发布目录：${releaseDir}"
    else
      log "无法删除旧发布目录，已保留：${releaseDir}"
      cleanupFailed=1
    fi
  done < <(find "${RELEASES_DIR}" -mindepth 1 -maxdepth 1 -type d \
    -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)
  return "${cleanupFailed}"
}

deploy_release() {
  local releaseDir="$1"

  ensure_admin_api_key_encryption_key
  validate_auth_configuration

  log "校验 Compose 配置。"
  run_compose "${releaseDir}" config --quiet

  log "构建应用镜像。"
  run_compose "${releaseDir}" build --pull app

  backup_database "${releaseDir}"
  prepare_baota_logging_before_auth "${releaseDir}"

  log "启动 EventShock 服务。"
  DEPLOY_ATTEMPTED=1
  run_compose "${releaseDir}" up -d --remove-orphans

  if ! wait_for_health "${releaseDir}"; then
    fail "新应用未通过容器健康检查。"
  fi
  bootstrap_admin_if_requested "${releaseDir}"
  verify_auth_migration "${releaseDir}"
  run_compose "${releaseDir}" ps
  if ! ensure_baota_proxy "${releaseDir}"; then
    fail "宝塔 Nginx 内部反向代理未能自愈。"
  fi
  if ! verify_public_endpoint "${releaseDir}" "${RELEASE_COMMIT}"; then
    fail "请检查 DNS、阿里云安全组 TCP 80/443、端口占用和 Caddy 日志。"
  fi
  ln -sfnT "${releaseDir}" "${TARGET_ROOT}/current"
}

main() {
  require_root
  check_platform
  check_source
  check_release_commit
  report_existing_listeners
  install_docker
  verify_firewall

  local releaseDir
  create_release
  releaseDir="${CREATED_RELEASE_DIR}"
  [[ -n "${releaseDir}" ]] || fail "未能创建发布目录。"
  ROLLBACK_RELEASE="$(readlink -f "${TARGET_ROOT}/current" 2>/dev/null || true)"
  trap rollback_on_exit EXIT
  deploy_release "${releaseDir}"
  DEPLOY_SUCCEEDED=1
  if ! cleanup_old_releases; then
    log "发布已成功，但旧发布清理未完成；保留旧文件不影响当前版本。"
  fi

  log "部署完成。当前版本：${releaseDir}"
  log "持久配置：${SHARED_DIR}/.env"
  log "脚本未修改宝塔、SSH 或现有 UFW 规则。"
}

main "$@"
