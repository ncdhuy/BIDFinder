#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: bidfinder-prod-deploy.sh deploy [commit] | rollback [commit] | status" >&2
  exit 2
}

command_name="${1:-}"
[[ -n "$command_name" ]] || usage
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
prod_root="${BIDFINDER_PRODUCTION_ROOT:-$HOME/.local/share/bidfinder/production}"
release_root="$prod_root/releases"
current_link="$prod_root/current"
shared_root="$prod_root/shared"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/bidfinder"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
runtime_root="${BIDFINDER_RUNTIME_ROOT:-$HOME/.local/share/bidfinder/runtime}"
typesense_root="${BIDFINDER_TYPESENSE_ROOT:-$HOME/.local/share/bidfinder/typesense}"
venv_dir="$shared_root/venv"
helper="$repo_root/infra/runtime/bidfinder-serving-state.py"

state_json() {
  if [[ -n "${BIDFINDER_SERVING_REPORT_PATH:-}" ]]; then
    python3 "$helper" --reports-root "$typesense_root/reports" --report "$BIDFINDER_SERVING_REPORT_PATH"
  else
    python3 "$helper" --reports-root "$typesense_root/reports"
  fi
}

json_value() {
  local key="$1"
  python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$key"
}

ensure_state() {
  local state generation
  state="$(state_json)"
  generation="$(printf '%s' "$state" | json_value generation)"
  [[ -n "$generation" ]] || { echo "serving state has no generation" >&2; exit 2; }
  [[ "$(curl --fail --silent --max-time 10 http://127.0.0.1:8108/health)" == *'true'* ]] || {
    echo "Typesense health is not true; refusing deployment" >&2
    exit 2
  }
  printf '%s\n' "$state"
}

upsert_runtime_env() {
  local target="$config_dir/runtime.env" state="$1" tmp
  local generation checkpoint provenance report markdown
  generation="$(printf '%s' "$state" | json_value generation)"
  checkpoint="$(printf '%s' "$state" | json_value checkpoint)"
  provenance="$(printf '%s' "$state" | json_value provenance)"
  report="$(printf '%s' "$state" | json_value report)"
  markdown="$(printf '%s' "$state" | json_value markdown)"
  tmp="$(mktemp "$config_dir/runtime.env.XXXXXX")"
  [[ -f "$target" ]] && cp -- "$target" "$tmp"
  python3 - "$tmp" \
    "BIDFINDER_REPO_ROOT=$current_link" \
    "BIDFINDER_RUNTIME_ROOT=$runtime_root" \
    "BIDFINDER_TYPESENSE_ROOT=$typesense_root" \
    "BIDFINDER_TYPESENSE_DATA_DIR=$typesense_root/data" \
    "BIDFINDER_TYPESENSE_CHECKPOINT=$checkpoint" \
    "BIDFINDER_TYPESENSE_PROVENANCE=$provenance" \
    "BIDFINDER_SERVING_REPORT_PATH=$report" \
    "BIDFINDER_SERVING_MARKDOWN_PATH=$markdown" \
    "BIDFINDER_SERVING_GENERATION=$generation" \
    "BIDFINDER_TYPESENSE_SERVING_GENERATION=$generation" \
    "BIDFINDER_PYTHON=$venv_dir/bin/python" \
    "ENV=production" <<'PY'
import re
import sys
from pathlib import Path
path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
updates = {}
for item in sys.argv[2:]:
    key, value = item.split("=", 1)
    updates[key] = value
seen = set()
out = []
for line in lines:
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
    if match and match.group(1) in updates:
        key = match.group(1)
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  chmod 600 "$tmp"
  mv -f -- "$tmp" "$target"
}

render_units() {
  local release="$1" template target rendered tmp
  mkdir -p "$unit_dir"
  for template in "$release"/infra/systemd/*.in; do
    target="$unit_dir/$(basename "$template" .in)"
    tmp="$(mktemp "$target.XXXXXX")"
    sed -e "s|@BIDFINDER_REPO@|$current_link|g" -e "s|@BIDFINDER_VENV@|$venv_dir|g" "$template" > "$tmp"
    chmod 600 "$tmp"
    mv -f -- "$tmp" "$target"
  done
  systemctl --user daemon-reload
  systemctl --user enable bidfinder-typesense.service bidfinder-api.service \
    bidfinder-incremental.timer bidfinder-snapshot.timer bidfinder-log-prune.timer >/dev/null
}

switch_release() {
  local release="$1" temporary
  temporary="$prod_root/.current.$$"
  ln -s -- "$release" "$temporary"
  mv -Tf -- "$temporary" "$current_link"
}

deploy() {
  local requested_commit="${1:-}" commit release state
  commit="${requested_commit:-$(git -C "$repo_root" rev-parse HEAD)}"
  git -C "$repo_root" cat-file -e "$commit^{commit}"
  [[ -n "$requested_commit" || -z "$(git -C "$repo_root" status --porcelain --untracked-files=all)" ]] || {
    echo "refusing deploy from a dirty checkout; commit or stash first" >&2
    exit 2
  }
  state="$(ensure_state)"
  [[ "$(systemctl --user is-active bidfinder-incremental.service 2>/dev/null || true)" != active ]] || {
    echo "incremental service is active; refusing release switch" >&2
    exit 2
  }
  release="$release_root/$commit"
  mkdir -p "$release_root" "$shared_root" "$config_dir"
  if [[ ! -e "$venv_dir" ]]; then
    ln -s -- "$runtime_root/venv" "$venv_dir"
  fi
  if [[ ! -f "$release/.release-commit" ]]; then
    mkdir -p "$release"
    git -C "$repo_root" archive --format=tar "$commit" | tar -x -C "$release"
    printf '%s\n' "$commit" > "$release/.release-commit"
  fi
  "$venv_dir/bin/python" -m compileall -q "$release/apps/api" "$release/crawler_engine"
  switch_release "$release"
  upsert_runtime_env "$state"
  render_units "$release"
  systemctl --user restart bidfinder-api.service
  curl --fail --silent --show-error --max-time 30 http://127.0.0.1:8001/ready >/dev/null
  echo "deployed commit=$commit release=$release; Typesense was not restarted"
}

rollback() {
  local commit="${1:-}" release state
  [[ -n "$commit" ]] || usage
  release="$release_root/$commit"
  [[ -d "$release" ]] || { echo "release not found: $release" >&2; exit 2; }
  state="$(ensure_state)"
  [[ "$(systemctl --user is-active bidfinder-incremental.service 2>/dev/null || true)" != active ]] || {
    echo "incremental service is active; refusing rollback" >&2
    exit 2
  }
  switch_release "$release"
  upsert_runtime_env "$state"
  render_units "$release"
  systemctl --user restart bidfinder-api.service
  curl --fail --silent --show-error --max-time 30 http://127.0.0.1:8001/ready >/dev/null
  echo "rolled back API code to commit=$commit; Typesense was not restarted"
}

case "$command_name" in
  deploy) deploy "${2:-}" ;;
  rollback) rollback "${2:-}" ;;
  status) exec "$repo_root/infra/runtime/bidfinder-status.sh" ;;
  *) usage ;;
esac
