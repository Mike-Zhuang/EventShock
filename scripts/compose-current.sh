#!/usr/bin/env bash

set -Eeuo pipefail

readonly TARGET_ROOT="/opt/eventshock"
readonly SHARED_ENV="${TARGET_ROOT}/shared/.env"
readonly CURRENT_RELEASE="$(readlink -f "${TARGET_ROOT}/current")"

[[ -d "${CURRENT_RELEASE}" ]] || {
  printf '[eventshock-compose] 当前发布目录不存在。\n' >&2
  exit 1
}
[[ -f "${SHARED_ENV}" ]] || {
  printf '[eventshock-compose] 共享环境配置不存在：%s\n' "${SHARED_ENV}" >&2
  exit 1
}

composeArguments=(
  --project-directory "${CURRENT_RELEASE}"
  --file "${CURRENT_RELEASE}/compose.yml"
  --env-file "${SHARED_ENV}"
)
if [[ -f "${CURRENT_RELEASE}/.release.env" ]]; then
  composeArguments+=(--env-file "${CURRENT_RELEASE}/.release.env")
fi

exec env \
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
  -u EVENTSHOCK_RELEASE_COMMIT \
  -u EVENTSHOCK_SECRETS_DIR \
  -u EVENTSHOCK_SMTP_HOST \
  -u EVENTSHOCK_SMTP_PORT \
  -u EVENTSHOCK_SMTP_SENDER \
  -u EVENTSHOCK_SMTP_USERNAME \
  -u LOG_LEVEL \
  docker compose --project-name eventshock "${composeArguments[@]}" "$@"
