#!/usr/bin/env bash
set -euo pipefail

# WSL/Linux operator wrapper.  Ingestion/search code stays platform-neutral.
readonly TYPESENSE_VERSION="30.2"
readonly DEFAULT_HOST="127.0.0.1"
readonly DEFAULT_PORT="8108"
readonly DOWNLOAD_URL="https://dl.typesense.org/releases/30.2/typesense-server-30.2-linux-amd64.tar.gz"

CONFIG_FILE="${BIDFINDER_TYPESENSE_CONFIG:-$HOME/.config/bidfinder/typesense.env}"
if [[ -f "$CONFIG_FILE" ]]; then
  # This file is operator-owned and must contain only local configuration.
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
  set +a
fi

ROOT="${BIDFINDER_TYPESENSE_ROOT:-$HOME/.local/share/bidfinder/typesense}"
DATA_DIR="$ROOT/data"
SNAPSHOTS_DIR="$ROOT/snapshots"
CHECKPOINTS_DIR="$ROOT/checkpoints"
REPORTS_DIR="$ROOT/reports"
LOGS_DIR="$ROOT/logs"
RUN_DIR="$ROOT/run"
BIN="${BIDFINDER_TYPESENSE_BIN:-$HOME/.local/lib/bidfinder/typesense/$TYPESENSE_VERSION/typesense-server}"
HOST="${TYPESENSE_HOST:-$DEFAULT_HOST}"
PORT="${TYPESENSE_PORT:-$DEFAULT_PORT}"
PROTOCOL="${TYPESENSE_PROTOCOL:-http}"
PID_FILE="$RUN_DIR/typesense.pid"
LOG_FILE="$LOGS_DIR/typesense.log"

die() {
  echo "local-typesense: $*" >&2
  exit 2
}

require_local_config() {
  [[ -n "${TYPESENSE_API_KEY:-}" ]] || die "TYPESENSE_API_KEY is missing; create $CONFIG_FILE with mode 600"
  [[ "$PROTOCOL" == "http" ]] || die "local target requires TYPESENSE_PROTOCOL=http"
  [[ "$HOST" == "127.0.0.1" || "$HOST" == "localhost" ]] || die "local target requires loopback TYPESENSE_HOST"
  [[ "$PORT" =~ ^[0-9]+$ && "$PORT" -ge 1 && "$PORT" -le 65535 ]] || die "invalid TYPESENSE_PORT"
}

ensure_dirs() {
  mkdir -p "$DATA_DIR" "$SNAPSHOTS_DIR" "$CHECKPOINTS_DIR" "$REPORTS_DIR" "$LOGS_DIR" "$RUN_DIR"
}

pid_value() {
  [[ -s "$1" ]] || return 1
  read -r pid < "$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$pid"
}

pid_alive() {
  local pid state
  pid="$(pid_value "$1" 2>/dev/null)" || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  state="$(ps -o stat= -p "$pid" 2>/dev/null | tr -d '[:space:]')"
  [[ -n "$state" && "${state:0:1}" != "Z" ]]
}

wait_health() {
  local port="$1"
  local url="http://127.0.0.1:$port/health"
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

start_instance() {
  local data_dir="$1" port="$2" pid_file="$3" log_file="$4" peering_port="${5:-8107}"
  [[ -x "$BIN" ]] || die "Typesense binary missing: run '$0 install'"
  if pid_alive "$pid_file"; then
    echo "running pid=$(pid_value "$pid_file") port=$port"
    return 0
  fi
  rm -f "$pid_file"
  mkdir -p "$data_dir" "$(dirname "$pid_file")" "$(dirname "$log_file")"
  # API key stays in the environment, not argv or operator output.
  TYPESENSE_API_KEY="$TYPESENSE_API_KEY" nohup "$BIN" \
    --data-dir="$data_dir" \
    --api-address="$HOST" \
    --api-port="$port" \
    --peering-address=127.0.0.1 \
    --peering-port="$peering_port" \
    >"$log_file" 2>&1 < /dev/null &
  printf '%s\n' "$!" > "$pid_file"
  wait_health "$port" || die "Typesense did not become healthy; inspect $log_file"
  echo "started pid=$(pid_value "$pid_file") port=$port"
}

stop_pid() {
  local pid_file="$1"
  local pid
  if ! pid="$(pid_value "$pid_file" 2>/dev/null)"; then
    rm -f "$pid_file"
    echo "stopped"
    return 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "stopped"
    return 0
  fi
  kill -TERM "$pid"
  for _ in $(seq 1 30); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pid_file"
      echo "stopped"
      return 0
    fi
    sleep 1
  done
  die "Typesense did not stop cleanly; pid=$pid"
}

install_binary() {
  local tmp_dir archive extracted
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"' RETURN
  archive="$tmp_dir/typesense-server.tar.gz"
  curl -fL --retry 3 --retry-delay 2 "$DOWNLOAD_URL" -o "$archive"
  mkdir -p "$(dirname "$BIN")"
  tar -xzf "$archive" -C "$tmp_dir"
  extracted="$tmp_dir/typesense-server"
  [[ -x "$extracted" ]] || die "download did not contain typesense-server"
  install -m 0755 "$extracted" "$BIN"
  echo "installed $TYPESENSE_VERSION"
}

snapshot() {
  local snapshot_path="${1:-}"
  [[ -n "$snapshot_path" && "$snapshot_path" == /* ]] || die "snapshot path must be an absolute Linux path"
  [[ "$snapshot_path" != "$DATA_DIR" && "$snapshot_path" != "$DATA_DIR/"* ]] || die "snapshot must not be inside live data"
  require_local_config
  ensure_dirs
  mkdir -p "$snapshot_path"
  curl -fsS -X POST --get --data-urlencode "snapshot_path=$snapshot_path" \
    "http://$HOST:$PORT/operations/snapshot"
  echo
}

restore_start() {
  local snapshot_path="${1:-}" restore_port="${2:-}" restore_data="${3:-$ROOT/restore-validation/${2:-8109}-data}"
  [[ -d "$snapshot_path" ]] || die "snapshot directory missing: $snapshot_path"
  [[ "$snapshot_path" == /* && "$restore_data" == /* ]] || die "restore paths must be absolute Linux paths"
  [[ "$restore_data" != "$DATA_DIR" && "$restore_data" != "$DATA_DIR/"* ]] || die "restore data must not be live data"
  [[ "$restore_data" != "$snapshot_path" && "$restore_data" != "$snapshot_path/"* ]] || die "restore data must be separate from snapshot"
  [[ "$restore_port" =~ ^[0-9]+$ ]] || die "restore port is required"
  require_local_config
  [[ ! -e "$restore_data" || -z "$(find "$restore_data" -mindepth 1 -print -quit 2>/dev/null)" ]] || die "restore data directory is not empty: $restore_data"
  mkdir -p "$restore_data"
  cp -a "$snapshot_path"/. "$restore_data"/
  start_instance "$restore_data" "$restore_port" "$RUN_DIR/restore-$restore_port.pid" "$LOGS_DIR/restore-$restore_port.log" "$((restore_port + 1))"
}

restore_stop() {
  local restore_port="${1:-}"
  [[ "$restore_port" =~ ^[0-9]+$ ]] || die "restore port is required"
  stop_pid "$RUN_DIR/restore-$restore_port.pid"
}

require_local_config
case "${1:-}" in
  install)
    install_binary
    ;;
  start)
    ensure_dirs
    start_instance "$DATA_DIR" "$PORT" "$PID_FILE" "$LOG_FILE"
    ;;
  stop)
    stop_pid "$PID_FILE"
    ;;
  restart)
    stop_pid "$PID_FILE"
    ensure_dirs
    start_instance "$DATA_DIR" "$PORT" "$PID_FILE" "$LOG_FILE"
    ;;
  status)
    if pid_alive "$PID_FILE"; then
      echo "running pid=$(pid_value "$PID_FILE") port=$PORT data_dir=$DATA_DIR"
    else
      echo "stopped"
      exit 1
    fi
    ;;
  health)
    curl -fsS "http://$HOST:$PORT/health"
    echo
    ;;
  version)
    # Typesense prints version then exits with usage status when no data-dir is
    # supplied; retain only the version line for a deterministic operator check.
    "$BIN" --version 2>&1 | sed -n '1p' || true
    ;;
  snapshot)
    snapshot "${2:-}"
    ;;
  restore-start)
    restore_start "${2:-}" "${3:-}" "${4:-}"
    ;;
  restore-stop)
    restore_stop "${2:-}"
    ;;
  *)
    die "usage: $0 {install|start|stop|restart|status|health|snapshot PATH|restore-start SNAPSHOT PORT DATA_DIR|restore-stop PORT}"
    ;;
esac
