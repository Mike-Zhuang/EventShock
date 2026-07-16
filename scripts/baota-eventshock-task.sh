#!/usr/bin/env bash

set -Eeuo pipefail
export LC_ALL=C

readonly SYNC_SCRIPT="/opt/eventshock/bin/sync-from-github.sh"
readonly LOG_DIR="/opt/eventshock/shared/logs"
readonly AUDIT_LOG="${LOG_DIR}/github-sync.log"

[[ "${EUID}" -eq 0 ]] || {
  printf '[eventshock-baota] 错误：任务必须由 root 运行。\n' >&2
  exit 1
}
[[ -x "${SYNC_SCRIPT}" ]] || {
  printf '[eventshock-baota] 错误：同步脚本不存在或不可执行：%s\n' "${SYNC_SCRIPT}" >&2
  exit 1
}

install -d -m 0750 "${LOG_DIR}"

# tee 同时保留稳定审计日志与宝塔原生任务日志；PIPESTATUS 确保部署失败不会被吞掉。
set +e
"${SYNC_SCRIPT}" 2>&1 | tee -a "${AUDIT_LOG}"
pipelineStatuses=("${PIPESTATUS[@]}")
set -e
if ((pipelineStatuses[0] != 0)); then
  exit "${pipelineStatuses[0]}"
fi
exit "${pipelineStatuses[1]}"
