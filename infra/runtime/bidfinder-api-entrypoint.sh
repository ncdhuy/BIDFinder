#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="${BIDFINDER_REPO_ROOT:?BIDFINDER_REPO_ROOT is required}"
python_bin="${BIDFINDER_PYTHON:?BIDFINDER_PYTHON is required}"
cd "$repo_root/apps/api"
exec "$python_bin" -m uvicorn server:app \
  --host "${BIDFINDER_API_HOST:-127.0.0.1}" \
  --port "${BIDFINDER_API_PORT:-8001}" \
  --workers 1 \
  --log-level "${BIDFINDER_LOG_LEVEL:-info}" \
  --no-access-log
