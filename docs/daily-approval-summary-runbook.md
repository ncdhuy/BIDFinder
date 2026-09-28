# Daily Approval Summary

The approval chart reads `daily_approval_summary` in Neon/Postgres. The daily
KPI cards read `daily_update_dashboard`. Both group records by
`decision_issued_at` through the normalized, indexed `decision_date` field.
`partition_date` is the crawl partition and must not be used as the approval
date. The chart table has one row per calendar day, including zero-count days.

The rollup stores a `:decision_date` suffix in `serving_generation` so API reads
cannot mistake older partition-based rows for approval-date rows.

## Required serving migration

Build and activate a new Typesense serving generation with the updated schema
and normalized `decision_date` on **all** historical documents. Existing serving
collections do not acquire this field from an application deploy. Finish the
generation build before deploying the API change or running the rollup sync.
Records without a valid `decision_issued_at` are intentionally excluded from
daily approval counts and value rankings.

For an existing generation, pause both incremental timers, wait for any active
incremental service to finish, and run the checkpointed stream migration:

```bash
python tools/migrate_typesense_vietnamese_locale.py \
  --source-generation "$BIDFINDER_SERVING_GENERATION" \
  --target-generation "$TARGET_GENERATION" \
  --checkpoint-dir "$BIDFINDER_TYPESENSE_ROOT/checkpoints/decision-date-v1" \
  --report "$BIDFINDER_TYPESENSE_ROOT/reports/decision-date-migration-v1.json" \
  --add-decision-date --verify-timeout-seconds 120 --apply
```

Keep the source generation for rollback. Cut over only after all three target
collections pass document parity, schema, sample and search checks. Switch the
runtime generation and deploy API/ingestion code together, then resume both
incremental timers. If an environment uses Typesense aliases, point all three
to the verified target in the same cutover. If the copy fails, the old
generation remains live; rerun with the same target and checkpoint paths.

## Initial migration and full backfill

The table DDL is included in `crawler_engine/s0_init_db.py` and is also
idempotently applied by the sync job. Run the sync job once against the active
Typesense serving generation:

```bash
python -m crawler_engine.sync_daily_approval_summary \
  --from 2022-01-01 \
  --to "$(TZ=Asia/Ho_Chi_Minh date +%F)" \
  --generation "$BIDFINDER_SERVING_GENERATION" \
  --dashboard-history-days 6
```

The command reads the Typesense API settings and `DATABASE_URL` from the
runtime environment. It upserts the complete date range, so rerunning it is
safe and also corrects counts for dates whose serving documents changed. Set
`--dashboard-history-days` to the number of existing KPI dates that need
rewriting; routine incremental runs keep the default of two latest days.

## Ongoing refresh

After every successful Typesense incremental run,
`infra/runtime/bidfinder-incremental.sh` passes that run's report to the rollup
sync. The sync refreshes every decision date in the latest 180 chart days, since
a changed crawl partition may contain decisions from other dates. It also
materializes the KPI summary for the latest two days. All Postgres rollup writes
occur in one transaction. Corrections to decision dates older than the 180-day
window require a historical rerun with `--from` and `--to` covering those dates.

If a sync fails, the incremental service reports `FAILED` and exits nonzero.
The next timer run detects missing rows and retries them. The API falls back to
Typesense for missing dates or dashboard summaries while recovery is pending.
The serving sync module must be present in the deployed production checkout;
verify this when deploying a release.

## Rollback and verification

The API checks serving generation before using either rollup. Missing chart
dates are fetched individually from Typesense. A missing KPI summary falls back
to the previous day or Typesense according to the existing display rules.

Useful read-only verification:

```sql
SELECT MIN(data_date), MAX(data_date), COUNT(*) AS days,
       COUNT(*) FILTER (WHERE approved_package_count > 0) AS non_zero_days,
       MAX(computed_at)
FROM daily_approval_summary;

SELECT data_date, serving_generation, computed_at
FROM daily_update_dashboard
ORDER BY data_date DESC
LIMIT 2;
```
