#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$script_dir/bidfinder-common.sh"

python_bin="${BIDFINDER_PYTHON:-python3}"
status_path="${BIDFINDER_INCREMENTAL_STATUS_PATH:-$BIDFINDER_TYPESENSE_ROOT/reports/incremental-status.json}"
request_delay="${BIDFINDER_MSC_REQUEST_DELAY_SECONDS:-1.0}"
timeout_seconds="${BIDFINDER_MSC_TIMEOUT_SECONDS:-30.0}"
profile="${BIDFINDER_INCREMENTAL_PROFILE:-reconciliation}"
lookback_days="${BIDFINDER_LOOKBACK_DAYS:-3}"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

write_status() {
  local result="$1" ended_at="$2" exit_code="$3" cli_output="${4:-}" summary_through="${5:-}"
  "$python_bin" - "$status_path" "$started_at" "$ended_at" "$result" "$exit_code" \
    "$BIDFINDER_SERVING_GENERATION" "$BIDFINDER_SERVING_REPORT_PATH" "$cli_output" "$profile" "$lookback_days" "$summary_through" <<'PY'
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

path, started, ended, result, exit_code, generation, report_path, cli_output, profile, lookback_days, summary_through = sys.argv[1:]
payload = {
    "last_run_start": started,
    "last_run_end": ended,
    "result": result,
    "exit_code": int(exit_code),
    "serving_generation": generation,
    "profile": profile,
    "lookback_days": int(lookback_days),
}
if summary_through:
    payload["approval_summary_through"] = summary_through
try:
    vietnam_today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    payload["latest_closed_day"] = (vietnam_today - timedelta(days=1)).isoformat()
    payload["vietnam_today"] = vietnam_today.isoformat()
except Exception:
    payload["latest_closed_day"] = None
try:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    counts = report.get("counts", {})
    results = report.get("results", [])
    dates = sorted({
        str(item.get("partition_date"))
        for item in results
        if item.get("partition_date")
    })
    payload.update({
        "coverage_through": report.get("coverage_through"),
        "current_day_included": report.get("current_day_included", False),
        "records_accepted": report.get("records_accepted", 0),
        "records_added_by_source": report.get("records_added_by_source", {}),
        "changed_partitions": report.get("changed_partitions", []),
        "unresolved_errors": report.get("unresolved_errors", []),
        "next_expected_date": report.get("next_expected_date"),
        "dates_processed": dates,
        "partitions_processed": len(results),
        "retries": counts.get("retries", 0),
        "rejected": counts.get("typesense_rejected", 0),
        "conflicts": report.get("provenance", {}).get("conflicts", 0),
    })
except (OSError, ValueError, TypeError):
    payload["report_status"] = "unavailable"
if cli_output:
    try:
        cli = json.loads(Path(cli_output).read_text(encoding="utf-8"))
        if cli.get("status") == "SKIPPED":
            payload.update({
                "status": "SKIPPED",
                "reason": cli.get("reason"),
                "dates_processed": [],
                "partitions_processed": 0,
                "records_accepted": 0,
                "records_added_by_source": {},
                "current_day_included": False,
                "changed_partitions": [],
                "retries": 0,
                "rejected": 0,
                "conflicts": 0,
            })
    except (OSError, ValueError, TypeError):
        pass
path = Path(path)
path.parent.mkdir(parents=True, exist_ok=True)
temporary = path.with_name(f".{path.name}.tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(path)
PY
}

ensure_runtime_dirs
require_serving_state
acquire_maintenance_lock
resource_guard
bash "$BIDFINDER_REPO_ROOT/infra/typesense/local-typesense.sh" health >/dev/null

base_fingerprint="${BIDFINDER_BASE_MANIFEST_FINGERPRINT:-}"
if [[ -z "$base_fingerprint" ]]; then
  base_fingerprint="$("$python_bin" - "$BIDFINDER_SERVING_REPORT_PATH" <<'PY'
import json
import sys
print(json.loads(open(sys.argv[1], encoding="utf-8").read())["base_manifest_fingerprint"])
PY
  )"
fi

write_status RUNNING "$started_at" 0
cli_output="$(mktemp "$BIDFINDER_RUNTIME_ROOT/.incremental-cli.XXXXXX")"
set +e
"$python_bin" -m crawler_engine.msc.cli incremental \
  --generation "$BIDFINDER_SERVING_GENERATION" \
  --checkpoint "$BIDFINDER_TYPESENSE_CHECKPOINT" \
  --provenance "$BIDFINDER_TYPESENSE_PROVENANCE" \
  --base-manifest-fingerprint "$base_fingerprint" \
  --include-current-day \
  --lookback "$lookback_days" \
  --resume \
  --max-partitions "$BIDFINDER_MAX_PARTITIONS" \
  --request-delay "$request_delay" \
  --timeout "$timeout_seconds" \
  --report "$BIDFINDER_SERVING_REPORT_PATH" \
  --markdown "$BIDFINDER_SERVING_MARKDOWN_PATH" >"$cli_output"
exit_code=$?
set -e
ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if (( exit_code == 0 )); then
  summary_today="$("$python_bin" - <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
print(datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat())
PY
  )"
  summary_from="$("$python_bin" - "$summary_today" "$lookback_days" <<'PY'
from datetime import date, timedelta
import sys
today = date.fromisoformat(sys.argv[1])
lookback = max(0, int(sys.argv[2]))
print((today - timedelta(days=lookback)).isoformat())
PY
  )"
  summary_output="$(mktemp "$BIDFINDER_RUNTIME_ROOT/.daily-approval-summary.XXXXXX")"
  set +e
  "$python_bin" -m crawler_engine.sync_daily_approval_summary \
    --from "$summary_from" \
    --to "$summary_today" \
    --generation "$BIDFINDER_SERVING_GENERATION" \
    --incremental-report "$cli_output" \
    --repair-history-days 180 \
    --workers "${BIDFINDER_DAILY_SUMMARY_WORKERS:-24}" \
    --timeout "${BIDFINDER_DAILY_SUMMARY_TIMEOUT_SECONDS:-30}" >"$summary_output"
  summary_exit_code=$?
  set -e
  if (( summary_exit_code != 0 )); then
    echo "ERROR: daily approval summary sync failed; the API will use its Typesense fallback" >&2
    cat "$summary_output" >&2
    exit_code="$summary_exit_code"
  else
    cat "$summary_output"
  fi
  rm -f -- "$summary_output"
  ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if (( exit_code == 0 )); then
    write_status PASS "$ended_at" "$exit_code" "$cli_output" "$summary_today"
  else
    write_status FAILED "$ended_at" "$exit_code" "$cli_output"
  fi
else
  write_status FAILED "$ended_at" "$exit_code" "$cli_output"
fi
rm -f -- "$cli_output"
exit "$exit_code"
