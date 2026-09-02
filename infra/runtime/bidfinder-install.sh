#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: bidfinder-install.sh install|start|stop|restart|status|daily|catch-up|snapshot|restore|fallback|typesense|logs

install  Create the WSL venv, external runtime config, and systemd user units.
start    Start Typesense and FastAPI.
stop     Stop FastAPI and Typesense gracefully.
restart  Restart both services gracefully.
status   Show service, readiness, freshness, resource, and timer status.
daily    Run the incremental oneshot now (safe catch-up equivalent).
catch-up Alias for daily.
snapshot Create and validate one bounded recovery bundle.
restore  Activate a validated bundle and retain the prior live data.
fallback Temporarily route procurement to the degraded Postgres fallback.
typesense Return procurement to Typesense primary.
logs     Show recent service journal entries.
EOF
  exit 2
}

command_name="${1:-}"
[[ -n "$command_name" ]] || usage

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/bidfinder"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
runtime_root="${BIDFINDER_RUNTIME_ROOT:-$HOME/.local/share/bidfinder/runtime}"
typesense_root="${BIDFINDER_TYPESENSE_ROOT:-$HOME/.local/share/bidfinder/typesense}"
venv_dir="$runtime_root/venv"
typesense_config="$config_dir/typesense.env"

require_typesense_config() {
  [[ -f "$typesense_config" ]] || {
    echo "missing $typesense_config; create it outside Git with TYPESENSE_API_KEY" >&2
    exit 2
  }
}

write_if_missing() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    umask 077
    shift
    printf '%s\n' "$@" > "$path"
  fi
}

install_units() {
  local template target rendered
  mkdir -p "$config_dir" "$unit_dir" "$runtime_root/locks" "$typesense_root/recovery"
  chmod 700 "$config_dir" "$runtime_root" "$runtime_root/locks" || true
  require_typesense_config

  if [[ ! -x "$venv_dir/bin/python" ]]; then
    python3 -m venv --without-pip "$venv_dir"
  fi
  if ! "$venv_dir/bin/python" -c 'import pip' >/dev/null 2>&1; then
    curl -fsSL --max-time 60 https://bootstrap.pypa.io/get-pip.py | "$venv_dir/bin/python" -
  fi
  if ! "$venv_dir/bin/python" -c 'import fastapi, uvicorn, asyncpg' >/dev/null 2>&1; then
    "$venv_dir/bin/python" -m pip install --upgrade pip
    if "$venv_dir/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)'; then
      # asyncpg 0.29 has no CPython 3.14 wheel and building it would require
      # a compiler on the temporary host. The newer ABI-compatible wheel is
      # sufficient for the existing asyncpg API usage in this service.
      "$venv_dir/bin/python" -m pip install --only-binary=:all: 'asyncpg>=0.30.0'
      "$venv_dir/bin/python" -m pip install -r <(grep -v '^asyncpg' "$repo_root/apps/api/requirements.txt")
    else
      "$venv_dir/bin/python" -m pip install -r "$repo_root/apps/api/requirements.txt"
    fi
  fi

  write_if_missing "$config_dir/runtime.env" \
    "BIDFINDER_REPO_ROOT=$repo_root" \
    "BIDFINDER_RUNTIME_ROOT=$runtime_root" \
    "BIDFINDER_TYPESENSE_ROOT=$typesense_root" \
    "BIDFINDER_TYPESENSE_DATA_DIR=$typesense_root/data" \
    "BIDFINDER_TYPESENSE_CHECKPOINT=$typesense_root/checkpoints/serving_v1_20260901.sqlite3" \
    "BIDFINDER_TYPESENSE_PROVENANCE=$typesense_root/checkpoints/serving_v1_20260901.uuid.sqlite3" \
    "BIDFINDER_SERVING_REPORT_PATH=$typesense_root/reports/serving-state-serving_v1_20260901.json" \
    "BIDFINDER_SERVING_MARKDOWN_PATH=$typesense_root/reports/serving-state-serving_v1_20260901.md" \
    "BIDFINDER_SERVING_GENERATION=serving_v1_20260901" \
    "BIDFINDER_TYPESENSE_SERVING_GENERATION=serving_v1_20260901" \
    "BIDFINDER_TYPESENSE_SHADOW_TIMEOUT_SECONDS=5.0" \
    "BIDFINDER_PYTHON=$venv_dir/bin/python" \
    "BIDFINDER_API_URL=http://127.0.0.1:8001" \
    "BIDFINDER_API_HOST=127.0.0.1" \
    "BIDFINDER_API_PORT=8001" \
    "BIDFINDER_LOOKBACK_DAYS=3" \
    "BIDFINDER_MAX_PARTITIONS=500" \
    "BIDFINDER_DISK_WARNING_PERCENT=25" \
    "BIDFINDER_DISK_CRITICAL_PERCENT=15" \
    "BIDFINDER_RAM_WARNING_BYTES=2147483648" \
    "BIDFINDER_RAM_CRITICAL_BYTES=1073741824" \
    "BIDFINDER_SWAP_WARNING_BYTES=1073741824" \
    "BIDFINDER_SNAPSHOT_RETENTION=3" \
    "BIDFINDER_SCHEDULE_TIMEZONE=Asia/Ho_Chi_Minh"
  write_if_missing "$config_dir/backend.env" \
    "BIDFINDER_PROCUREMENT_BACKEND=typesense" \
    "BIDFINDER_PROCUREMENT_FALLBACK_ENABLED=true"

  for template in "$repo_root"/infra/systemd/*.in; do
    target="$unit_dir/$(basename "$template" .in)"
    rendered="$(sed -e "s|@BIDFINDER_REPO@|$repo_root|g" -e "s|@BIDFINDER_VENV@|$venv_dir|g" "$template")"
    printf '%s\n' "$rendered" > "$target"
    chmod 600 "$target"
  done

  systemctl --user daemon-reload
  systemctl --user enable bidfinder-typesense.service bidfinder-api.service \
    bidfinder-incremental.timer bidfinder-snapshot.timer bidfinder-log-prune.timer
  if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "$USER" 2>/dev/null || echo "NOTE: enable lingering manually with: sudo loginctl enable-linger $USER" >&2
  fi
  echo "installed systemd user units; runtime config is $config_dir"
}

load_runtime() {
  # shellcheck disable=SC1091
  source "$config_dir/runtime.env"
  # shellcheck disable=SC1091
  source "$config_dir/backend.env"
}

case "$command_name" in
  install)
    install_units
    ;;
  start)
    require_typesense_config
    systemctl --user start bidfinder-typesense.service bidfinder-api.service
    ;;
  stop)
    systemctl --user stop bidfinder-api.service bidfinder-typesense.service
    ;;
  restart)
    systemctl --user restart bidfinder-typesense.service
    systemctl --user restart bidfinder-api.service
    ;;
  status)
    load_runtime
    systemctl --user --no-pager --plain status bidfinder-typesense.service bidfinder-api.service || true
    echo "-- readiness --"
    curl --fail-with-body --max-time 10 --silent "$BIDFINDER_API_URL/ready" || true
    echo
    echo "-- resources --"
    # shellcheck disable=SC1091
    source "$script_dir/bidfinder-common.sh"
    resource_status
    echo "-- incremental --"
    if [[ -f "$BIDFINDER_INCREMENTAL_STATUS_PATH" ]]; then
      "$BIDFINDER_PYTHON" - "$BIDFINDER_INCREMENTAL_STATUS_PATH" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
keys = (
    "result", "last_run_start", "last_run_end", "latest_closed_day",
    "coverage_through", "dates_processed", "partitions_processed",
    "records_accepted", "retries", "rejected", "conflicts", "next_expected_date",
)
print(json.dumps({key: payload.get(key) for key in keys}, ensure_ascii=False, sort_keys=True))
PY
    else
      echo "incremental status not available"
    fi
    echo "-- timers --"
    systemctl --user list-timers --all --no-pager 'bidfinder-*' || true
    ;;
  daily|catch-up)
    systemctl --user start bidfinder-incremental.service
    ;;
  snapshot)
    systemctl --user start bidfinder-snapshot.service
    ;;
  restore)
    shift
    [[ $# -eq 1 ]] || { echo "restore requires one validated bundle path" >&2; exit 2; }
    BIDFINDER_RESTORE_BUNDLE="$1" bash "$script_dir/bidfinder-restore.sh" "$1"
    ;;
  fallback)
    # shellcheck disable=SC1091
    source "$script_dir/bidfinder-common.sh"
    write_backend_mode postgres
    systemctl --user restart bidfinder-api.service
    echo "procurement backend set to postgres fallback"
    ;;
  typesense)
    # shellcheck disable=SC1091
    source "$script_dir/bidfinder-common.sh"
    write_backend_mode typesense
    systemctl --user restart bidfinder-api.service
    echo "procurement backend set to Typesense primary"
    ;;
  logs)
    journalctl --user-unit=bidfinder-api.service --user-unit=bidfinder-typesense.service \
      --user-unit=bidfinder-incremental.service --no-pager -n 120
    ;;
  *)
    usage
    ;;
esac
