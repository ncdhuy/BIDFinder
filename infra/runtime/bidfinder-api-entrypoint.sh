#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="${BIDFINDER_REPO_ROOT:?BIDFINDER_REPO_ROOT is required}"
python_bin="${BIDFINDER_PYTHON:?BIDFINDER_PYTHON is required}"
cd "$repo_root/apps/api"
health_url="http://${BIDFINDER_TYPESENSE_HOST:-127.0.0.1}:${BIDFINDER_TYPESENSE_PORT:-8108}/health"
for _ in {1..60}; do
  if curl --fail --silent --show-error --max-time 2 "$health_url" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl --fail --silent --show-error --max-time 2 "$health_url" >/dev/null
proxy_args=()
if [[ "${TRUST_PROXY_HEADERS:-false}" == "1" || "${TRUST_PROXY_HEADERS:-false}" == "true" || "${TRUST_PROXY_HEADERS:-false}" == "yes" || "${TRUST_PROXY_HEADERS:-false}" == "on" || -n "${BIDFINDER_PUBLIC_URL:-}" ]]; then
  proxy_args=(
    --proxy-headers
    "--forwarded-allow-ips=${TRUSTED_PROXY_IPS:-127.0.0.1,::1}"
  )
fi
exec "$python_bin" -m uvicorn server:app \
  --host "${BIDFINDER_API_HOST:-127.0.0.1}" \
  --port "${BIDFINDER_API_PORT:-8001}" \
  --workers 1 \
  --log-level "${BIDFINDER_LOG_LEVEL:-info}" \
  --no-access-log \
  "${proxy_args[@]}"
