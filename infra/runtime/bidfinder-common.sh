#!/usr/bin/env bash
set -Eeuo pipefail

BIDFINDER_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/bidfinder"

load_env_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    local line key value
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line#"${line%%[![:space:]]*}"}"
      [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
      [[ "$line" == export\ * ]] && line="${line#export }"
      if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
        if [[ "$value" == '"'*'"' ]]; then
          value="${value:1:${#value}-2}"
        elif [[ "$value" == "'"*"'" ]]; then
          value="${value:1:${#value}-2}"
        else
          value="${value%%[[:space:]]#*}"
          value="${value%"${value##*[![:space:]]}"}"
        fi
        export "$key=$value"
      fi
    done < "$path"
  fi
}

BIDFINDER_REPO_ROOT="${BIDFINDER_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
load_env_file "$BIDFINDER_CONFIG_DIR/typesense.env"
load_env_file "$BIDFINDER_CONFIG_DIR/runtime.env"
load_env_file "$BIDFINDER_CONFIG_DIR/backend.env"

BIDFINDER_RUNTIME_ROOT="${BIDFINDER_RUNTIME_ROOT:-$HOME/.local/share/bidfinder/runtime}"
BIDFINDER_PYTHON="${BIDFINDER_PYTHON:-python3}"
BIDFINDER_TYPESENSE_ROOT="${BIDFINDER_TYPESENSE_ROOT:-$HOME/.local/share/bidfinder/typesense}"
BIDFINDER_TYPESENSE_DATA_DIR="${BIDFINDER_TYPESENSE_DATA_DIR:-$BIDFINDER_TYPESENSE_ROOT/data}"
BIDFINDER_TYPESENSE_CHECKPOINT="${BIDFINDER_TYPESENSE_CHECKPOINT:-$BIDFINDER_TYPESENSE_ROOT/checkpoints/serving_v1_20260901.sqlite3}"
BIDFINDER_TYPESENSE_PROVENANCE="${BIDFINDER_TYPESENSE_PROVENANCE:-$BIDFINDER_TYPESENSE_ROOT/checkpoints/serving_v1_20260901.uuid.sqlite3}"
BIDFINDER_SERVING_REPORT_PATH="${BIDFINDER_SERVING_REPORT_PATH:-$BIDFINDER_TYPESENSE_ROOT/reports/serving-state-serving_v1_20260901.json}"
BIDFINDER_SERVING_MARKDOWN_PATH="${BIDFINDER_SERVING_MARKDOWN_PATH:-$BIDFINDER_TYPESENSE_ROOT/reports/serving-state-serving_v1_20260901.md}"
BIDFINDER_INCREMENTAL_STATUS_PATH="${BIDFINDER_INCREMENTAL_STATUS_PATH:-$BIDFINDER_TYPESENSE_ROOT/reports/incremental-status.json}"
BIDFINDER_SNAPSHOT_STATUS_PATH="${BIDFINDER_SNAPSHOT_STATUS_PATH:-$BIDFINDER_TYPESENSE_ROOT/reports/snapshot-status.json}"
BIDFINDER_SERVING_GENERATION="${BIDFINDER_SERVING_GENERATION:-serving_v1_20260901}"
BIDFINDER_TYPESENSE_SERVING_GENERATION="${BIDFINDER_TYPESENSE_SERVING_GENERATION:-$BIDFINDER_SERVING_GENERATION}"
BIDFINDER_API_URL="${BIDFINDER_API_URL:-http://127.0.0.1:8001}"
BIDFINDER_API_HOST="${BIDFINDER_API_HOST:-127.0.0.1}"
BIDFINDER_API_PORT="${BIDFINDER_API_PORT:-8001}"
BIDFINDER_LOOKBACK_DAYS="${BIDFINDER_LOOKBACK_DAYS:-3}"
BIDFINDER_MAX_PARTITIONS="${BIDFINDER_MAX_PARTITIONS:-500}"
BIDFINDER_DISK_WARNING_PERCENT="${BIDFINDER_DISK_WARNING_PERCENT:-25}"
BIDFINDER_DISK_CRITICAL_PERCENT="${BIDFINDER_DISK_CRITICAL_PERCENT:-15}"
BIDFINDER_RAM_WARNING_BYTES="${BIDFINDER_RAM_WARNING_BYTES:-2147483648}"
BIDFINDER_RAM_CRITICAL_BYTES="${BIDFINDER_RAM_CRITICAL_BYTES:-1073741824}"
BIDFINDER_SWAP_WARNING_BYTES="${BIDFINDER_SWAP_WARNING_BYTES:-1073741824}"
BIDFINDER_SNAPSHOT_RETENTION="${BIDFINDER_SNAPSHOT_RETENTION:-3}"

ensure_runtime_dirs() {
  mkdir -p "$BIDFINDER_RUNTIME_ROOT/locks" "$BIDFINDER_TYPESENSE_ROOT/recovery"
}

acquire_maintenance_lock() {
  ensure_runtime_dirs
  exec 9>"$BIDFINDER_RUNTIME_ROOT/locks/serving-maintenance.lock"
  if ! flock -n 9; then
    echo "already running"
    exit 0
  fi
}

disk_free_bytes() {
  df -Pk "$BIDFINDER_TYPESENSE_ROOT" | awk 'NR == 2 { print $4 * 1024 }'
}

disk_free_percent() {
  df -Pk "$BIDFINDER_TYPESENSE_ROOT" | awk 'NR == 2 { printf "%.1f", ($4 / $2) * 100 }'
}

mem_available_bytes() {
  awk '/^MemAvailable:/ { print $2 * 1024; exit }' /proc/meminfo
}

swap_used_bytes() {
  awk '/^SwapTotal:/ { total=$2 } /^SwapFree:/ { free=$2 } END { print (total - free) * 1024 }' /proc/meminfo
}

typesense_pid() {
  pgrep -f -- "typesense-server.*--data-dir=$BIDFINDER_TYPESENSE_DATA_DIR" | awk 'NR == 1 { print; exit }'
}

typesense_rss_bytes() {
  local pid
  pid="$(typesense_pid 2>/dev/null || true)"
  [[ -n "$pid" && -r "/proc/$pid/status" ]] || return 0
  awk '/^VmRSS:/ { print $2 * 1024; exit }' "/proc/$pid/status"
}

resource_status() {
  local disk_bytes disk_percent available swap rss
  disk_bytes="$(disk_free_bytes)"
  disk_percent="$(disk_free_percent)"
  available="$(mem_available_bytes)"
  swap="$(swap_used_bytes)"
  rss="$(typesense_rss_bytes || true)"
  printf 'disk_free_bytes=%s disk_free_percent=%s warning_percent=%s critical_percent=%s\n' \
    "$disk_bytes" "$disk_percent" "$BIDFINDER_DISK_WARNING_PERCENT" "$BIDFINDER_DISK_CRITICAL_PERCENT"
  printf 'typesense_rss_bytes=%s mem_available_bytes=%s ram_warning_bytes=%s ram_critical_bytes=%s swap_used_bytes=%s swap_warning_bytes=%s\n' \
    "${rss:-unknown}" "$available" "$BIDFINDER_RAM_WARNING_BYTES" "$BIDFINDER_RAM_CRITICAL_BYTES" "$swap" "$BIDFINDER_SWAP_WARNING_BYTES"
}

resource_guard() {
  local disk_percent available swap
  disk_percent="$(disk_free_percent)"
  available="$(mem_available_bytes)"
  swap="$(swap_used_bytes)"
  awk -v value="$disk_percent" -v critical="$BIDFINDER_DISK_CRITICAL_PERCENT" 'BEGIN { exit !(value < critical) }' && {
    echo "critical disk guard: free_percent=$disk_percent critical_percent=$BIDFINDER_DISK_CRITICAL_PERCENT" >&2
    return 2
  }
  if awk -v value="$disk_percent" -v warning="$BIDFINDER_DISK_WARNING_PERCENT" 'BEGIN { exit !(value < warning) }'; then
    echo "warning disk guard: free_percent=$disk_percent warning_percent=$BIDFINDER_DISK_WARNING_PERCENT" >&2
  fi
  if (( available < BIDFINDER_RAM_CRITICAL_BYTES )); then
    echo "critical RAM guard: mem_available_bytes=$available critical_bytes=$BIDFINDER_RAM_CRITICAL_BYTES" >&2
    return 2
  fi
  if (( available < BIDFINDER_RAM_WARNING_BYTES )); then
    echo "warning RAM guard: mem_available_bytes=$available warning_bytes=$BIDFINDER_RAM_WARNING_BYTES" >&2
  fi
  if (( swap > BIDFINDER_SWAP_WARNING_BYTES )); then
    echo "warning swap growth: swap_used_bytes=$swap warning_bytes=$BIDFINDER_SWAP_WARNING_BYTES" >&2
  fi
}

write_backend_mode() {
  local mode="$1"
  install -d -m 700 "$BIDFINDER_CONFIG_DIR"
  umask 077
  printf 'BIDFINDER_PROCUREMENT_BACKEND=%s\nBIDFINDER_PROCUREMENT_FALLBACK_ENABLED=true\n' "$mode" > "$BIDFINDER_CONFIG_DIR/backend.env"
}
