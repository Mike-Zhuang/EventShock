#!/usr/bin/env bash

set -Eeuo pipefail
export LC_ALL=C

readonly TARGET_ROOT="/opt/eventshock"
readonly SHARED_DIR="${TARGET_ROOT}/shared"
readonly BIN_DIR="${TARGET_ROOT}/bin"
readonly OPERATIONS_ROOT="${TARGET_ROOT}/operations"
readonly MIRROR_DIR="${SHARED_DIR}/github-mirror.git"
readonly STAGING_ROOT="${TARGET_ROOT}/github-staging"
readonly STATE_FILE="${SHARED_DIR}/github-sync.state"
readonly FAILED_STATE_FILE="${SHARED_DIR}/github-sync.failed"
readonly CONFIG_FILE="${EVENTSHOCK_GITHUB_SYNC_CONFIG:-${SHARED_DIR}/github-sync.env}"
readonly LOCK_FILE="/run/lock/eventshock-github-sync.lock"
readonly DEPLOY_REF="refs/remotes/origin/eventshock-deploy"

REPOSITORY_URL="https://github.com/Mike-Zhuang/EventShock.git"
DEPLOY_BRANCH="codex/self-hosted-mvp"
GITHUB_REPOSITORY="Mike-Zhuang/EventShock"
STAGING_DIR=""

log() {
  printf '[%s] [eventshock-github-sync] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

fail() {
  log "ERROR: $*" >&2
  exit 1
}

cleanup() {
  if [[ -n "${STAGING_DIR}" ]] \
    && [[ "${STAGING_DIR}" == "${STAGING_ROOT}"/release.* ]] \
    && [[ -d "${STAGING_DIR}" ]]; then
    rm -rf -- "${STAGING_DIR}"
  fi
}

validate_configuration() {
  [[ "${EUID}" -eq 0 ]] || fail "must run as root"
  [[ "${REPOSITORY_URL}" =~ ^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git$ ]] \
    || fail "REPOSITORY_URL must be a public GitHub HTTPS clone URL"
  git check-ref-format --branch "${DEPLOY_BRANCH}" >/dev/null 2>&1 \
    || fail "DEPLOY_BRANCH is not a valid Git branch name"
  [[ "${GITHUB_REPOSITORY}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] \
    || fail "GITHUB_REPOSITORY must use owner/name format"
  [[ "${REPOSITORY_URL}" == "https://github.com/${GITHUB_REPOSITORY}.git" ]] \
    || fail "REPOSITORY_URL and GITHUB_REPOSITORY must identify the same repository"
  local requiredCommand managedPath statePath stateMode resolvedBin
  for requiredCommand in cmp curl docker flock git jq tar timeout; do
    command -v "${requiredCommand}" >/dev/null 2>&1 \
      || fail "required command is unavailable: ${requiredCommand}"
  done
  for managedPath in "${SHARED_DIR}" "${OPERATIONS_ROOT}" "${STAGING_ROOT}" "${MIRROR_DIR}"; do
    [[ ! -L "${managedPath}" ]] || fail "managed path must not be a symbolic link: ${managedPath}"
    if [[ -e "${managedPath}" ]]; then
      [[ "$(stat -c '%u' "${managedPath}")" == "0" ]] \
        || fail "managed path must be owned by root: ${managedPath}"
    fi
  done
  [[ -L "${BIN_DIR}" ]] || fail "${BIN_DIR} must be an atomic operations symlink"
  resolvedBin="$(readlink -f "${BIN_DIR}")"
  [[ -d "${resolvedBin}" ]] || fail "operations symlink target is unavailable"
  [[ "${resolvedBin}" == "${OPERATIONS_ROOT}"/* ]] \
    || fail "operations symlink must resolve below ${OPERATIONS_ROOT}"
  [[ "$(stat -c '%u' "${resolvedBin}")" == "0" ]] \
    || fail "operations release must be owned by root"
  for statePath in "${STATE_FILE}" "${FAILED_STATE_FILE}"; do
    [[ ! -L "${statePath}" ]] || fail "state file must not be a symbolic link: ${statePath}"
    if [[ -e "${statePath}" ]]; then
      [[ "$(stat -c '%u' "${statePath}")" == "0" ]] \
        || fail "state file must be owned by root: ${statePath}"
      stateMode="$(stat -c '%a' "${statePath}")"
      (( (8#${stateMode} & 8#022) == 0 )) \
        || fail "state file must not be group- or world-writable: ${statePath}"
    fi
  done
}

load_configuration() {
  if [[ -f "${CONFIG_FILE}" ]]; then
    [[ ! -L "${CONFIG_FILE}" ]] || fail "configuration file must not be a symbolic link"
    local configOwner configMode
    configOwner="$(stat -c '%u' "${CONFIG_FILE}")"
    configMode="$(stat -c '%a' "${CONFIG_FILE}")"
    [[ "${configOwner}" == "0" ]] || fail "configuration file must be owned by root"
    (( (8#${configMode} & 8#022) == 0 )) \
      || fail "configuration file must not be group- or world-writable"
    local configLine configKey configValue
    while IFS= read -r configLine || [[ -n "${configLine}" ]]; do
      configLine="${configLine%$'\r'}"
      [[ -z "${configLine}" ]] && continue
      [[ "${configLine}" == \#* ]] && continue
      [[ "${configLine}" =~ ^([A-Z0-9_]+)=(.*)$ ]] \
        || fail "configuration contains an invalid line"
      configKey="${BASH_REMATCH[1]}"
      configValue="${BASH_REMATCH[2]}"
      case "${configKey}" in
        EVENTSHOCK_GITHUB_URL) REPOSITORY_URL="${configValue}" ;;
        EVENTSHOCK_GITHUB_BRANCH) DEPLOY_BRANCH="${configValue}" ;;
        EVENTSHOCK_GITHUB_REPOSITORY) GITHUB_REPOSITORY="${configValue}" ;;
        *) fail "configuration contains an unsupported key: ${configKey}" ;;
      esac
    done <"${CONFIG_FILE}"
  fi
}

acquire_lock() {
  install -d -m 0755 "$(dirname "${LOCK_FILE}")"
  exec 9>"${LOCK_FILE}"
  if ! flock -n 9; then
    log "SKIP: another synchronization is still running"
    exit 0
  fi
}

prepare_mirror() {
  install -d -m 0755 "${SHARED_DIR}" "${OPERATIONS_ROOT}" "${STAGING_ROOT}"
  if [[ ! -e "${MIRROR_DIR}" ]]; then
    log "initializing read-only GitHub mirror"
    local mirrorTemp
    mirrorTemp="$(mktemp -d "${SHARED_DIR}/github-mirror.tmp.XXXXXX")"
    rmdir "${mirrorTemp}"
    if ! timeout 120 env GIT_TERMINAL_PROMPT=0 \
      git clone --mirror "${REPOSITORY_URL}" "${mirrorTemp}"; then
      rm -rf -- "${mirrorTemp}"
      fail "GitHub mirror clone failed or timed out"
    fi
    mv "${mirrorTemp}" "${MIRROR_DIR}"
  fi
  [[ -d "${MIRROR_DIR}" ]] || fail "mirror path exists but is not a directory"

  local configuredUrl
  configuredUrl="$(git --git-dir="${MIRROR_DIR}" remote get-url origin)"
  [[ "${configuredUrl}" == "${REPOSITORY_URL}" ]] \
    || fail "mirror origin does not match configured repository"

  if ! timeout 120 env GIT_TERMINAL_PROMPT=0 git --git-dir="${MIRROR_DIR}" fetch \
    --no-tags \
    --prune \
    origin \
    "+refs/heads/${DEPLOY_BRANCH}:${DEPLOY_REF}"; then
    fail "GitHub fetch failed or timed out"
  fi
}

read_deployed_commit() {
  if [[ -f "${STATE_FILE}" ]]; then
    sed -n 's/^commit=\([0-9a-f]\{40\}\)$/\1/p' "${STATE_FILE}" | head -n 1
  fi
}

read_current_release_commit() {
  local currentRelease releaseCommit
  currentRelease="$(readlink -f "${TARGET_ROOT}/current" 2>/dev/null || true)"
  [[ -d "${currentRelease}" ]] || return 1
  [[ -f "${currentRelease}/.release.env" ]] || return 1
  releaseCommit="$(sed -n 's/^EVENTSHOCK_RELEASE_COMMIT=\([0-9a-f]\{40\}\)$/\1/p' \
    "${currentRelease}/.release.env" | head -n 1)"
  [[ -n "${releaseCommit}" ]] || return 1
  printf '%s\n' "${releaseCommit}"
}

configured_health_endpoint() {
  local appDomain
  appDomain="$(sed -n 's/^APP_DOMAIN=//p' "${SHARED_DIR}/.env" 2>/dev/null | tail -n 1)"
  [[ -n "${appDomain}" ]] || appDomain="eventshock.mikezhuang.cn"
  [[ "${appDomain}" =~ ^(https?://)?[A-Za-z0-9.-]+(:[0-9]{1,5})?$ ]] \
    || return 1
  if [[ "${appDomain}" == http://* ]] || [[ "${appDomain}" == https://* ]]; then
    printf '%s/api/health\n' "${appDomain%/}"
  else
    printf 'https://%s/api/health\n' "${appDomain}"
  fi
}

verify_runtime_commit() {
  local expectedCommit="$1"
  local currentRelease releaseCommit appContainerId healthStatus containerCommit
  local endpoint response
  currentRelease="$(readlink -f "${TARGET_ROOT}/current" 2>/dev/null || true)"
  [[ -d "${currentRelease}" ]] || return 1
  releaseCommit="$(read_current_release_commit 2>/dev/null || true)"
  [[ "${releaseCommit}" == "${expectedCommit}" ]] || return 1
  [[ -x "${currentRelease}/scripts/compose-current.sh" ]] || return 1
  appContainerId="$("${currentRelease}/scripts/compose-current.sh" ps -q app 2>/dev/null)"
  [[ -n "${appContainerId}" ]] || return 1
  healthStatus="$(docker inspect --format \
    '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
    "${appContainerId}" 2>/dev/null || true)"
  [[ "${healthStatus}" == "healthy" ]] || return 1
  containerCommit="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' \
    "${appContainerId}" 2>/dev/null \
    | sed -n 's/^EVENTSHOCK_RELEASE_COMMIT=//p' | head -n 1)"
  [[ "${containerCommit}" == "${expectedCommit}" ]] || return 1
  endpoint="$(configured_health_endpoint)" || return 1
  response="$(curl --fail --silent --location --connect-timeout 3 --max-time 8 \
    "${endpoint}" 2>/dev/null)" || return 1
  jq -e --arg expectedCommit "${expectedCommit}" \
    '.status == "ok" and .releaseCommit == $expectedCommit' \
    <<<"${response}" >/dev/null 2>&1
}

failed_state_value() {
  local key="$1"
  [[ -f "${FAILED_STATE_FILE}" ]] || return 1
  sed -n "s/^${key}=//p" "${FAILED_STATE_FILE}" | head -n 1
}

check_deployment_backoff() {
  local targetCommit="$1"
  local failedCommit nextRetry now
  failedCommit="$(failed_state_value commit 2>/dev/null || true)"
  if [[ -n "${failedCommit}" ]] && [[ "${failedCommit}" != "${targetCommit}" ]]; then
    rm -f -- "${FAILED_STATE_FILE}"
    return
  fi
  [[ "${failedCommit}" == "${targetCommit}" ]] || return
  nextRetry="$(failed_state_value nextRetryAtEpoch 2>/dev/null || true)"
  [[ "${nextRetry}" =~ ^[0-9]+$ ]] || fail "failed deployment state is malformed"
  now="$(date +%s)"
  if ((now < nextRetry)); then
    log "DEPLOY_BACKOFF: commit=${targetCommit} next_retry_epoch=${nextRetry}"
    return 10
  fi
}

record_deployment_failure() {
  local targetCommit="$1"
  local previousCommit attempts delay now failedTemp
  previousCommit="$(failed_state_value commit 2>/dev/null || true)"
  attempts="$(failed_state_value attempts 2>/dev/null || true)"
  if [[ "${previousCommit}" != "${targetCommit}" ]] || [[ ! "${attempts}" =~ ^[0-9]+$ ]]; then
    attempts=0
  fi
  attempts=$((attempts + 1))
  delay=1800
  if ((attempts > 1)); then
    delay=3600
  fi
  now="$(date +%s)"
  failedTemp="$(mktemp "${SHARED_DIR}/github-sync.failed.XXXXXX")"
  {
    printf 'commit=%s\n' "${targetCommit}"
    printf 'attempts=%s\n' "${attempts}"
    printf 'failedAtEpoch=%s\n' "${now}"
    printf 'nextRetryAtEpoch=%s\n' "$((now + delay))"
  } >"${failedTemp}"
  chmod 0644 "${failedTemp}"
  mv -f "${failedTemp}" "${FAILED_STATE_FILE}"
  log "DEPLOY_QUARANTINED: commit=${targetCommit} attempts=${attempts} retry_in=${delay}s"
}

verify_fast_forward() {
  local deployedCommit="$1"
  local targetCommit="$2"
  [[ -z "${deployedCommit}" ]] && return
  git --git-dir="${MIRROR_DIR}" cat-file -e "${deployedCommit}^{commit}" 2>/dev/null \
    || fail "deployed commit is no longer present in the GitHub history"
  git --git-dir="${MIRROR_DIR}" merge-base --is-ancestor \
    "${deployedCommit}" "${targetCommit}" \
    || fail "refusing non-fast-forward deployment: ${deployedCommit} -> ${targetCommit}"
}

write_state() {
  local commitSha="$1"
  local stateTemp
  stateTemp="$(mktemp "${SHARED_DIR}/github-sync.state.XXXXXX")"
  {
    printf 'commit=%s\n' "${commitSha}"
    printf 'branch=%s\n' "${DEPLOY_BRANCH}"
    printf 'deployedAt=%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  } >"${stateTemp}"
  chmod 0644 "${stateTemp}"
  mv -f "${stateTemp}" "${STATE_FILE}"
}

verify_github_checks() {
  local commitSha="$1"
  local response checkName checkCount successCount incompleteCount failedCount
  local -a requiredChecks=(
    "Backend / Python 3.12.13"
    "Frontend / Node 22"
    "Production container"
  )
  local -a waitingChecks=()
  local -a failedChecks=()

  if ! response="$(curl \
      --fail \
      --silent \
      --show-error \
      --retry 2 \
      --connect-timeout 5 \
      --max-time 20 \
      -H 'Accept: application/vnd.github+json' \
      -H 'X-GitHub-Api-Version: 2022-11-28' \
      -H 'User-Agent: EventShock-Server-Sync' \
      "https://api.github.com/repos/${GITHUB_REPOSITORY}/commits/${commitSha}/check-runs?per_page=100&filter=latest")"; then
    log "ERROR: GitHub Checks API request failed for commit=${commitSha}" >&2
    return 30
  fi
  if ! jq -e '.check_runs | type == "array"' <<<"${response}" >/dev/null; then
    log "ERROR: GitHub Checks API returned an unexpected response" >&2
    return 30
  fi

  for checkName in "${requiredChecks[@]}"; do
    if ! checkCount="$(jq --arg checkName "${checkName}" \
      '[.check_runs[] | select(.name == $checkName and .app.slug == "github-actions")] | length' \
      <<<"${response}")"; then
      log "ERROR: could not count GitHub check ${checkName}" >&2
      return 30
    fi
    if ! successCount="$(jq --arg checkName "${checkName}" \
      '[.check_runs[] | select(
        .name == $checkName and
        .app.slug == "github-actions" and
        .status == "completed" and
        .conclusion == "success"
      )] | length' <<<"${response}")"; then
      log "ERROR: could not inspect GitHub check ${checkName}" >&2
      return 30
    fi
    if ! incompleteCount="$(jq --arg checkName "${checkName}" \
      '[.check_runs[] | select(
        .name == $checkName and
        .app.slug == "github-actions" and
        .status != "completed"
      )] | length' <<<"${response}")"; then
      log "ERROR: could not inspect GitHub check state ${checkName}" >&2
      return 30
    fi
    if ! failedCount="$(jq --arg checkName "${checkName}" \
      '[.check_runs[] | select(
        .name == $checkName and
        .app.slug == "github-actions" and
        .status == "completed" and
        .conclusion != "success"
      )] | length' <<<"${response}")"; then
      log "ERROR: could not inspect GitHub check conclusions ${checkName}" >&2
      return 30
    fi
    if ((failedCount > 0)); then
      failedChecks+=("${checkName}")
    elif ((checkCount == 0)) || ((incompleteCount > 0)); then
      waitingChecks+=("${checkName}")
    elif ((successCount != checkCount)); then
      failedChecks+=("${checkName}")
    else
      continue
    fi
  done

  local IFS=,
  if ((${#failedChecks[@]} > 0)); then
    log "CI_BLOCKED: commit=${commitSha} checks=${failedChecks[*]}" >&2
    return 20
  fi
  if ((${#waitingChecks[@]} > 0)); then
    log "WAIT_CI: commit=${commitSha} checks=${waitingChecks[*]}"
    return 10
  fi
  log "CI_PASSED: commit=${commitSha} required_checks=3"
}

extract_commit() {
  local commitSha="$1"
  STAGING_DIR="$(mktemp -d "${STAGING_ROOT}/release.XXXXXX")"
  git --git-dir="${MIRROR_DIR}" archive --format=tar "${commitSha}" \
    | tar -C "${STAGING_DIR}" -xf -

  [[ -f "${STAGING_DIR}/scripts/deploy-server.sh" ]] \
    || fail "commit does not contain scripts/deploy-server.sh"
  [[ -f "${STAGING_DIR}/scripts/sync-from-github.sh" ]] \
    || fail "commit does not contain scripts/sync-from-github.sh"
  [[ -f "${STAGING_DIR}/frontend/dist/index.html" ]] \
    || fail "commit does not contain a prebuilt frontend/dist/index.html"
  [[ -f "${STAGING_DIR}/backend/app/main.py" ]] \
    || fail "commit does not contain backend/app/main.py"
}

install_operational_scripts() {
  local sourceRoot="$1"
  local commitSha="$2"
  local scriptName sourceScript targetScript operationsRelease operationsTemp
  local -a scriptNames=(
    "sync-from-github.sh"
    "baota-eventshock-task.sh"
    "register-baota-task.py"
    "register-baota-site.py"
    "install-github-sync.sh"
  )
  [[ "${commitSha}" =~ ^[0-9a-f]{40}$ ]] || fail "invalid operations commit"
  operationsRelease="${OPERATIONS_ROOT}/${commitSha}"
  operationsTemp="${OPERATIONS_ROOT}/.${commitSha}.next.$$"

  if [[ -d "${operationsRelease}" ]]; then
    for scriptName in "${scriptNames[@]}"; do
      sourceScript="${sourceRoot}/scripts/${scriptName}"
      targetScript="${operationsRelease}/${scriptName}"
      [[ -f "${sourceScript}" ]] || fail "commit does not contain scripts/${scriptName}"
      [[ -f "${targetScript}" ]] && cmp -s "${sourceScript}" "${targetScript}" \
        || fail "existing operations release does not match commit ${commitSha}"
    done
  else
    [[ ! -e "${operationsTemp}" ]] || fail "temporary operations path already exists"
    install -d -m 0755 "${operationsTemp}"
    for scriptName in "${scriptNames[@]}"; do
      sourceScript="${sourceRoot}/scripts/${scriptName}"
      [[ -f "${sourceScript}" ]] || fail "commit does not contain scripts/${scriptName}"
      install -m 0755 "${sourceScript}" "${operationsTemp}/${scriptName}"
    done
    mv "${operationsTemp}" "${operationsRelease}"
  fi

  for scriptName in "${scriptNames[@]}"; do
    [[ -x "${operationsRelease}/${scriptName}" ]] \
      || fail "operations script is not executable: ${scriptName}"
  done
  ln -sfnT "${operationsRelease}" "${BIN_DIR}"
  [[ "$(readlink -f "${BIN_DIR}")" == "${operationsRelease}" ]] \
    || fail "could not activate atomic operations release"
}

cleanup_old_operational_releases() {
  local activeRelease releaseDir index
  activeRelease="$(readlink -f "${BIN_DIR}")"
  index=0
  while IFS= read -r releaseDir; do
    index=$((index + 1))
    if ((index <= 5)) || [[ "${releaseDir}" == "${activeRelease}" ]]; then
      continue
    fi
    [[ "${releaseDir}" == "${OPERATIONS_ROOT}"/* ]] || continue
    if rm -rf -- "${releaseDir}"; then
      log "removed stale immutable operations release: ${releaseDir}"
    else
      log "WARNING: could not remove stale operations release: ${releaseDir}"
    fi
  done < <(find "${OPERATIONS_ROOT}" -mindepth 1 -maxdepth 1 -type d \
    -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)
}

main() {
  trap cleanup EXIT
  load_configuration
  validate_configuration
  acquire_lock
  prepare_mirror

  local targetCommit deployedCommit currentCommit shortCommit subject
  targetCommit="$(git --git-dir="${MIRROR_DIR}" rev-parse "${DEPLOY_REF}^{commit}")"
  deployedCommit="$(read_deployed_commit || true)"
  if [[ "${targetCommit}" == "${deployedCommit}" ]]; then
    if verify_runtime_commit "${targetCommit}"; then
      log "NO_CHANGE: branch, state, current release, container and public health remain at ${targetCommit}"
      exit 0
    fi
    log "RUNTIME_DRIFT: state=${deployedCommit} target=${targetCommit}; attempting verified repair"
  fi
  verify_fast_forward "${deployedCommit}" "${targetCommit}"

  local checkStatus
  if verify_github_checks "${targetCommit}"; then
    checkStatus=0
  else
    checkStatus=$?
    if ((checkStatus == 10)); then
      exit 0
    fi
    exit 1
  fi

  local backoffStatus
  if check_deployment_backoff "${targetCommit}"; then
    backoffStatus=0
  else
    backoffStatus=$?
    if ((backoffStatus == 10)); then
      exit 0
    fi
    exit 1
  fi

  shortCommit="${targetCommit:0:12}"
  subject="$(git --git-dir="${MIRROR_DIR}" show -s --format=%s "${targetCommit}" \
    | tr '\r\n' ' ' | tr -cd '[:print:]' | cut -c1-160)"
  log "DEPLOY_START: branch=${DEPLOY_BRANCH} commit=${shortCommit} subject=${subject}"
  extract_commit "${targetCommit}"

  currentCommit="$(read_current_release_commit 2>/dev/null || true)"
  if [[ "${currentCommit}" == "${targetCommit}" ]] \
    && verify_runtime_commit "${targetCommit}"; then
    install_operational_scripts "${STAGING_DIR}" "${targetCommit}"
    write_state "${targetCommit}"
    rm -f -- "${FAILED_STATE_FILE}"
    cleanup_old_operational_releases
    log "STATE_RECONCILED: running deployment was already healthy at ${targetCommit}"
    exit 0
  fi

  if ! EVENTSHOCK_RELEASE_COMMIT="${targetCommit}" \
    bash "${STAGING_DIR}/scripts/deploy-server.sh" "${STAGING_DIR}"; then
    record_deployment_failure "${targetCommit}"
    fail "deployment failed; the commit entered bounded backoff"
  fi
  install_operational_scripts "${STAGING_DIR}" "${targetCommit}"
  write_state "${targetCommit}"
  rm -f -- "${FAILED_STATE_FILE}"
  cleanup_old_operational_releases
  log "DEPLOY_SUCCESS: branch=${DEPLOY_BRANCH} commit=${targetCommit}"
}

main "$@"
