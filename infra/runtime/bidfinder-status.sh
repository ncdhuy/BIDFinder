#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$script_dir/bidfinder-common.sh"

overall=0
pass() { printf 'PASS %-18s %s\n' "$1" "$2"; }
warn() { printf 'WARN %-18s %s\n' "$1" "$2"; overall=$(( overall < 1 ? 1 : overall )); }
fail() { printf 'FAIL %-18s %s\n' "$1" "$2"; overall=2; }

if health="$(curl --fail --silent --max-time 5 http://127.0.0.1:8108/health 2>/dev/null)" && [[ "$health" == *'true'* ]]; then
  pass typesense-health "127.0.0.1:8108 health=true"
else
  fail typesense-health "127.0.0.1:8108 unavailable"
fi

if ready="$(curl --fail --silent --max-time 10 http://127.0.0.1:8001/ready 2>/dev/null)"; then
  if summary="$(printf '%s' "$ready" | python3 -c 'import json,sys; p=json.load(sys.stdin); t=p.get("typesense",{}); print("ready={} procurement_ready={} generation={} counts={}".format(p.get("status")=="ready", p.get("procurement_ready") is True, t.get("generation"), t.get("counts", t.get("physical_counts", t.get("collections"))))); raise SystemExit(0 if p.get("status")=="ready" and p.get("procurement_ready") is True else 1)')"; then
    pass api-readiness "$summary"
  else
    fail api-readiness "API response was not ready/procurement_ready"
  fi
else
  fail api-readiness "127.0.0.1:8001 unavailable"
fi

if require_serving_state >/dev/null 2>&1; then
  pass serving-state "generation=$BIDFINDER_SERVING_GENERATION checkpoint/provenance/report present"
else
  fail serving-state "configured serving state is missing or inconsistent"
fi

for unit in bidfinder-typesense.service bidfinder-api.service; do
  if [[ "$(systemctl --user is-active "$unit" 2>/dev/null || true)" == active ]]; then
    pass "$unit" active
  else
    fail "$unit" inactive
  fi
done
for timer in bidfinder-incremental.timer bidfinder-snapshot.timer bidfinder-log-prune.timer; do
  if [[ "$(systemctl --user is-enabled "$timer" 2>/dev/null || true)" == enabled ]]; then
    pass "$timer" enabled
  else
    warn "$timer" not-enabled
  fi
done
if [[ "$(systemctl --user is-active bidfinder-ingress.service 2>/dev/null || true)" == active ]]; then
  pass cloudflared active
else
  warn cloudflared "not active (credentials/config may be pending)"
fi

while IFS= read -r line; do printf 'INFO %-18s %s\n' resources "$line"; done < <(resource_status)
if [[ -f "$BIDFINDER_INCREMENTAL_STATUS_PATH" ]]; then
  python3 - "$BIDFINDER_INCREMENTAL_STATUS_PATH" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(f"INFO {'incremental':18} result={payload.get('result')} coverage_through={payload.get('coverage_through')} last_run={payload.get('last_run_end')}")
PY
else
  warn incremental "status file missing"
fi
if (( overall == 0 )); then
  echo 'OVERALL PASS'
elif (( overall == 1 )); then
  echo 'OVERALL WARN'
else
  echo 'OVERALL FAIL'
fi
exit "$overall"
