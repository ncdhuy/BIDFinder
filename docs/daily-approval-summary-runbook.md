# Daily Approval Summary

The approval chart reads `daily_approval_summary` in Neon/Postgres. The daily
KPI cards read `daily_update_dashboard`. Both are serving rollups, separate
from account and user-information tables. The chart table has one row per
calendar day, including zero-count days.

## Initial migration and full backfill

The table DDL is included in `crawler_engine/s0_init_db.py` and is also
idempotently applied by the sync job. Run the sync job once against the active
Typesense serving generation:

```bash
python -m crawler_engine.sync_daily_approval_summary \
  --from 2023-02-01 \
  --to "$(TZ=Asia/Ho_Chi_Minh date +%F)" \
  --generation "$BIDFINDER_SERVING_GENERATION"
```

The command reads the Typesense API settings and `DATABASE_URL` from the
runtime environment. It upserts the complete date range, so rerunning it is
safe and also corrects counts for dates whose serving documents changed.

## Ongoing refresh

After every successful Typesense incremental run,
`infra/runtime/bidfinder-incremental.sh` passes that run's report to the rollup
sync. The sync refreshes the current day and configured lookback, every changed
partition date in the report, and every missing date in the latest 180 chart
days. It also materializes the KPI summary for selected dates in the latest two
days. All Postgres rollup writes occur in one transaction.

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
