#!/bin/sh

set -eu

trap 'exit 0' TERM INT

gateTimeoutSeconds="${CADDY_STARTUP_GATE_TIMEOUT_SECONDS:-90}"
case "${gateTimeoutSeconds}" in
  '' | *[!0-9]*)
    printf '[eventshock-caddy] invalid startup gate timeout: %s\n' "${gateTimeoutSeconds}" >&2
    exit 64
    ;;
esac
currentEpoch="$(date +%s)"
gateDeadline=$((currentEpoch + gateTimeoutSeconds))

waitForUrl() {
  waitName="$1"
  waitUrl="$2"
  waitHost="${3:-}"
  attempt=0

  while true; do
    if [ -n "${waitHost}" ]; then
      responseCode="$(
        curl --silent --output /dev/null --noproxy '*' \
          --connect-timeout 2 --max-time 3 --user-agent EventShock-Caddy-Startup-Gate \
          --header "Host: ${waitHost}" --write-out '%{http_code}' "${waitUrl}" \
          || true
      )"
    else
      responseCode="$(
        curl --silent --output /dev/null --noproxy '*' \
          --connect-timeout 2 --max-time 3 --user-agent EventShock-Caddy-Startup-Gate \
          --write-out '%{http_code}' "${waitUrl}" || true
      )"
    fi
    if [ "${responseCode}" = 200 ]; then
      break
    fi

    attempt=$((attempt + 1))
    if [ "${attempt}" -eq 1 ] || [ $((attempt % 30)) -eq 0 ]; then
      printf '[eventshock-caddy] waiting for %s: %s\n' "${waitName}" "${waitUrl}"
    fi
    if [ "$(date +%s)" -ge "${gateDeadline}" ]; then
      return 1
    fi
    sleep 1
  done

  printf '[eventshock-caddy] %s is ready\n' "${waitName}"
}

# Docker 在守护进程重启时会并行恢复容器，不会重新执行 Compose 的
# depends_on。正常启动时先确认应用，再确认生产代理链，避免把短暂窗口
# 暴露为 502；永久故障超过上限后仍启动 Caddy，保留 TLS 与错误可观测性。
gateReady=true
if ! waitForUrl application 'http://app:8000/api/health?startup-gate=application'; then
  gateReady=false
fi

upstream="${CADDY_UPSTREAM:-app:8000}"
case "${upstream}" in
  http://* | https://*) upstreamHealthUrl="${upstream%/}/api/health?startup-gate=proxy" ;;
  *) upstreamHealthUrl="http://${upstream}/api/health?startup-gate=proxy" ;;
esac

if [ "${gateReady}" = true ] \
  && [ "${upstreamHealthUrl}" != 'http://app:8000/api/health?startup-gate=proxy' ]; then
  proxyHost="${APP_DOMAIN:-eventshock.mikezhuang.cn}"
  proxyHost="${proxyHost#http://}"
  proxyHost="${proxyHost#https://}"
  proxyHost="${proxyHost%%/*}"
  if ! waitForUrl proxy "${upstreamHealthUrl}" "${proxyHost}"; then
    gateReady=false
  fi
fi

if [ "${gateReady}" != true ]; then
  printf '[eventshock-caddy] startup gate timed out after %ss; starting Caddy for observability\n' \
    "${gateTimeoutSeconds}" >&2
fi

exec "$@"
