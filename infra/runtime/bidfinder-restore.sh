#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$script_dir/bidfinder-common.sh"

bundle_arg="${1:-}"
[[ -n "$bundle_arg" ]] || { echo "usage: bidfinder-restore.sh /absolute/path/to/validated-bundle" >&2; exit 2; }
bundle="$(cd "$bundle_arg" 2>/dev/null && pwd)" || { echo "bundle not found" >&2; exit 2; }
recovery_root="$(cd "$BIDFINDER_TYPESENSE_ROOT/recovery" && pwd)"
[[ "$bundle" == "$recovery_root"/bundle-* ]] || { echo "bundle must be inside $recovery_root" >&2; exit 2; }
[[ -f "$bundle/bundle.json" && -d "$bundle/typesense-snapshot/state" ]] || { echo "validated bundle contents are missing" >&2; exit 2; }

python_bin="${BIDFINDER_PYTHON:-python3}"
"$python_bin" - "$bundle/bundle.json" "$BIDFINDER_SERVING_GENERATION" <<'PY'
import json
import sys
from pathlib import Path

metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if metadata.get("status") != "VALIDATED":
    raise SystemExit("bundle is not VALIDATED")
if metadata.get("generation") != sys.argv[2]:
    raise SystemExit("bundle generation does not match the active generation")
PY

ensure_runtime_dirs
acquire_maintenance_lock
resource_guard
systemctl --user stop bidfinder-api.service bidfinder-typesense.service

live_data="$BIDFINDER_TYPESENSE_DATA_DIR"
quarantine="$BIDFINDER_TYPESENSE_ROOT/recovery/live-data-before-restore-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mv "$live_data" "$quarantine"
cp -a "$bundle/typesense-snapshot" "$live_data"

rollback() {
  systemctl --user stop bidfinder-api.service bidfinder-typesense.service || true
  rm -rf -- "$live_data"
  mv "$quarantine" "$live_data"
  systemctl --user start bidfinder-typesense.service
  systemctl --user start bidfinder-api.service || true
}
trap rollback ERR

systemctl --user start bidfinder-typesense.service
for _ in $(seq 1 1200); do
  if "$BIDFINDER_REPO_ROOT/infra/typesense/local-typesense.sh" health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
"$BIDFINDER_REPO_ROOT/infra/typesense/local-typesense.sh" health >/dev/null
systemctl --user start bidfinder-api.service
trap - ERR
echo "restore validated and activated bundle=$bundle; prior live data retained at $quarantine"
