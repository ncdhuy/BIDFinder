#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$script_dir/bidfinder-common.sh"

python_bin="${BIDFINDER_PYTHON:-python3}"
recovery_root="$BIDFINDER_TYPESENSE_ROOT/recovery"
snapshot_staging_root="$recovery_root/.snapshot-staging"
status_path="${BIDFINDER_SNAPSHOT_STATUS_PATH:-$BIDFINDER_TYPESENSE_ROOT/reports/snapshot-status.json}"
nonce="$(od -An -N8 -tx1 /dev/urandom | tr -d '[:space:]')-$$"
bundle_name="bundle-$(date -u +%Y%m%dT%H%M%SZ)-$nonce"
temporary="$recovery_root/.$bundle_name.tmp"
target="$recovery_root/$bundle_name"
staging="$snapshot_staging_root/$bundle_name"

ensure_runtime_dirs
acquire_maintenance_lock
resource_guard
mkdir -p "$snapshot_staging_root" "$temporary"
export BIDFINDER_TYPESENSE_ROOT
export BIDFINDER_TYPESENSE_CONFIG="${BIDFINDER_TYPESENSE_CONFIG:-$BIDFINDER_CONFIG_DIR/typesense.env}"

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$BIDFINDER_REPO_ROOT/infra/typesense/local-typesense.sh" snapshot "$staging" >/dev/null
[[ -d "$staging/state" ]] || { echo "snapshot missing state directory" >&2; exit 2; }
mv "$staging" "$temporary/typesense-snapshot"

cp -- "$BIDFINDER_TYPESENSE_CHECKPOINT" "$temporary/checkpoint.sqlite3"
cp -- "$BIDFINDER_TYPESENSE_PROVENANCE" "$temporary/uuid-provenance.sqlite3"
cp -- "$BIDFINDER_SERVING_REPORT_PATH" "$temporary/incremental-serving-audit.json"
if [[ -f "${BIDFINDER_INCREMENTAL_STATUS_PATH:-$BIDFINDER_TYPESENSE_ROOT/reports/incremental-status.json}" ]]; then
  cp -- "${BIDFINDER_INCREMENTAL_STATUS_PATH:-$BIDFINDER_TYPESENSE_ROOT/reports/incremental-status.json}" "$temporary/incremental-status.json"
fi

"$python_bin" - "$temporary" "$BIDFINDER_SERVING_GENERATION" "$started_at" <<'PY'
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

bundle = Path(sys.argv[1])
generation = sys.argv[2]
started = sys.argv[3]
report = json.loads((bundle / "incremental-serving-audit.json").read_text(encoding="utf-8"))
for name in ("checkpoint.sqlite3", "uuid-provenance.sqlite3"):
    path = bundle / name
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit(f"SQLite integrity check failed: {name}")
if report.get("serving_generation") != generation:
    raise SystemExit("serving report generation mismatch")
metadata = {
    "bundle_version": "bidfinder-early-user-recovery-v1",
    "status": "VALIDATED",
    "generation": generation,
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "snapshot_started_at": started,
    "coverage_through": report.get("coverage_through"),
    "last_successful_incremental_run": report.get("last_successful_incremental_run"),
    "physical_counts": report.get("physical_counts", {}),
    "files": {
        name: (bundle / name).stat().st_size
        for name in ("checkpoint.sqlite3", "uuid-provenance.sqlite3", "incremental-serving-audit.json")
    },
}
(bundle / "serving-state-manifest.json").write_text(
    json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
(bundle / "bundle.json").write_text(
    json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

mv "$temporary" "$target"

retention="$BIDFINDER_SNAPSHOT_RETENTION"
mapfile -t bundles < <(find "$recovery_root" -mindepth 1 -maxdepth 1 -type d -name 'bundle-*' -printf '%f\n' | sort)
if (( ${#bundles[@]} > retention )); then
  for name in "${bundles[@]:0:${#bundles[@]}-retention}"; do
    [[ "$name" =~ ^bundle-[0-9TZ-]+-[0-9a-f-]+$ ]] || continue
    rm -rf -- "$recovery_root/$name"
  done
fi

"$python_bin" - "$status_path" "$target" "$BIDFINDER_SERVING_GENERATION" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
target = Path(sys.argv[2])
generation = sys.argv[3]
metadata = json.loads((target / "bundle.json").read_text(encoding="utf-8"))
payload = {
    "result": "PASS",
    "bundle": str(target),
    "generation": generation,
    "coverage_through": metadata.get("coverage_through"),
    "retained_validated_bundles": len(list(target.parent.glob("bundle-*"))),
}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
PY
echo "snapshot validated bundle=$target coverage_through=$(grep -o '"coverage_through": "[^"]*"' "$target/bundle.json" | head -1 | cut -d'"' -f4)"
