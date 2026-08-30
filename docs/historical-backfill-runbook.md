# Historical backfill runbook (Phase 3B-R)

Phase 3B-R makes the 2023-to-present bootstrap measurable and resumable. It
does not run the bootstrap. There is no FastAPI/UI cutover, chatbot, deploy,
Neon/Postgres write, or alias activation in this phase.

## Readiness preflight

The intended starting date is `2023-02-01`. The upper bound must be an
explicit, fully closed Vietnam calendar day. Do not use the current day and do
not omit either date argument.

Run the read-only seven-source count preflight:

```powershell
python -m crawler_engine.msc.cli preflight `
  --from 2023-02-01 --to 2026-08-29
```

The preflight makes exactly one `/search_prc` aggregation request per selected
source contract and records `agg.docCount`. The MSC protocol requires a
positive page size, so the client uses the smallest valid page size, discards
any returned records, and never paginates or processes records for this check.
For the initial readiness range, the measured total is 9,801,385 documents:
`goods=9,183,937`, `medicines=585,426`, and
`traditional_medicine=32,022`.

## Manifest and capacity

Create a reproducible plan without Typesense writes:

```powershell
python -m crawler_engine.msc.cli backfill `
  --from 2023-02-01 --to 2026-08-29 --sources all `
  --generation hist_2026g1 `
  --checkpoint crawler_engine/.msc_state/historical.sqlite3 `
  --manifest backfill-plan.json --plan-only
```

The manifest stores version/generation, engine and source/schema versions,
closed range, creation time, seven source totals, three group totals, overall
expected total, page/batch/overflow settings, and contract/canonical/
Typesense fingerprints. It is an input to actual execution. A changed frozen
contract or schema invalidates the old plan.

Estimate bounded sample sizing:

```powershell
python -m crawler_engine.msc.cli capacity `
  --plan backfill-plan.json --output capacity-estimate.json
```

The default sample is one verified search-response document from each source.
The result reports canonical bytes, p50-like and p95-like sizes, bytes for
fields that are searchable/facet/filterable/sortable, projected raw bytes,
projected indexed bytes, and the official Typesense keyword-search RAM
estimate of 2x–3x indexed/searchable/filterable field bytes. It also reports a
minimum raw-data disk estimate and a separate 50% operational disk margin.
These values are estimates, not guarantees. Use a larger bounded live sample
or disposable Typesense test when final sizing matters.

Current V1 indexed-field review finds no safe obvious index removal:

- long technical configuration/specification fields are full-text searchable;
- names, ingredients, manufacturers, bidders, and tender codes are searchable;
- provenance and selection fields needed for filtering remain facets;
- price, quantity, production year, and partition date remain sortable where
  configured;
- IDs, verbose locations, result/decision metadata are display-only.

Removing a searchable field to save RAM would change intended BIDFinder search
behavior, so no schema optimization is proposed in Phase 3B-R.

## Production target starting point

The fixture projection is approximately 11.40 GB raw canonical data and 7.61
GB indexed fields. The 2x–3x rule yields 15.22–22.83 GB keyword-search RAM
before headroom. A reasonable self-hosted starting shape is three HA nodes,
each with at least 32 GB RAM, 4–8 vCPU, and 200 GB persistent SSD. This is a
starting capacity, not a guarantee; measure the actual generation and scale
before RAM stays above the chosen operating threshold or SSD free space falls
below 40%.

Typesense recommends HA multi-node operation for self-hosted production
([system requirements](https://typesense.org/docs/guide/system-requirements.html),
[HA guidance](https://typesense.org/docs/guide/high-availability.html)). Use
persistent SSD and a tested restore path. Typesense Cloud is the preferred
operational choice for BIDFinder's expected search workload when managed HA,
backups, and lower operator burden outweigh provider cost and sizing control.
Self-hosting is reasonable when data residency, network control, or predictable
infrastructure ownership matters. Keep host, port, protocol, and API key
configuration provider-neutral.

## Start, resume, and interruption

The traversal is frozen as `date ascending -> source registry order`. V1 is
sequential; no concurrency is assumed. Actual execution is deliberately
guarded:

- `--from`, `--to`, `--generation`, and `--checkpoint` are mandatory;
- the range must end before the current Vietnam day;
- a manifest must match range, source set, and current fingerprints;
- `--max-partitions` is mandatory for an actual run;
- `--acknowledge-readiness` is mandatory for an actual run;
- writes use only `typesense:<generation>` and physical collections;
- aliases are never created, changed, or activated by the runner.

Example future start:

```powershell
python -m crawler_engine.msc.cli backfill `
  --from 2023-02-01 --to 2026-08-29 --sources all `
  --generation hist_2026g1 `
  --checkpoint crawler_engine/.msc_state/historical.sqlite3 `
  --manifest backfill-plan.json --report backfill-report.json `
  --max-partitions 10000 --acknowledge-readiness
```

Use `--resume` after a stopped run. Use `--force` only to deliberately rerun
completed partitions into the same physical generation. Do not use `--force`
as a substitute for a new generation after schema drift.

Ctrl+C leaves the active checkpoint `RUNNING` rather than falsely completing
it, atomically records report state `INTERRUPTED`, and allows the next
`--resume` to reclaim it. The checkpoint database is the durable source of
truth; the report is an operator summary.

## Plan-only output and progress

Plan-only reports range, source set, source-date parent count, broad counts,
expected documents, completed/remaining checkpoint partitions, a lower-bound
MSC request estimate, and Typesense batch estimate. It does not promise a
wall-clock completion time.

The report is atomically replaced after each parent partition. It contains
completed/skipped/failed/quarantined counts, expected and accepted records,
Typesense batches, MSC requests, retries, source/group progress, compact
errors, last completed partition, and state. It contains no credentials and no
millions-long UUID list.

## Checkpoint audit and failure policy

Checkpoint identity is `source_key × partition_date × sink_target`, so one
generation cannot inherit completion from another. Summarize a generation:

```powershell
python -m crawler_engine.msc.cli backfill-audit `
  --plan backfill-plan.json `
  --checkpoint crawler_engine/.msc_state/historical.sqlite3 `
  --uuid-audit crawler_engine/.msc_state/historical.uuid.sqlite3 `
  --output historical-backfill-audit.json
```

The audit reports expected, completed, failed, quarantined, pending, running,
and stale partitions by source. A final PASS requires every required closed
source-date partition to be `COMPLETED`; the bootstrap target is zero failed
or quarantined partitions.

V1 stops on the first failure so later partitions are not silently presented
as complete. The failed parent remains resumable. MSC/source failures include
count mismatch, unstable parent, overflow, unsplittable windows, and contract
drift. Typesense infrastructure failures include connection failure, 503 or
backpressure, schema mismatch, and partial import. Data failures include
normalization and UUID identity/content conflicts. Already-quarantined rows
remain visible and prevent final PASS.

## Coverage, UUID, and final count invariants

For each source, compare the preflight broad-range count with the sum of
`parent_pre_count` from completed daily checkpoints:

```text
broad_range_count == sum(completed parent source counts)
```

This is a source coverage check; a Typesense count cannot replace it.

The runner wraps the existing sink with a disk-backed SQLite provenance table.
It stores UUID, group, source, partition date, and canonical content
fingerprint. Same UUID with identical provenance/content is idempotent. Same
UUID with different provenance or content fails the partition and is never
silently overwritten. The UUID set is not held in Python RAM.

For a fresh empty physical generation, expected group unique counts from that
table must equal physical Typesense document counts. A cross-partition
collision is detected rather than hidden by upsert semantics.

## Final audit and sampling

`historical-backfill-audit.json` records generation/range/server version, all
seven broad counts and completed sums, per-source parity, group expected and
physical counts, UUID conflicts, partition failures/quarantines, rejects,
batch/retry totals, schema drift, deterministic sampling rules, benchmark
status, and overall PASS/FAIL. It never stores credentials.

After completion, sample deterministically with seed `20230830` across early,
middle, and recent closed dates and across all source tabs. Retrieve selected
UUIDs from physical Typesense and compare normalized MSC results and important
fields. A small reproducible sample is required; thousands of samples are not.

Run the search benchmark before any alias gate. The bounded query set covers
item/medicine name, active ingredient, manufacturer, bidder, tender code,
source tab, price range, sort, and multi-search all. Capture p50-like and
p95-like latency:

```powershell
python -m crawler_engine.msc.cli benchmark `
  --generation hist_2026g1 --repeats 3 --output search-benchmark.json
```

The command issues only a bounded physical-generation query set; it performs
no writes. Do not run this benchmark against a 12M-document generation before
authorization.

## Backups, monitoring, and recovery

For self-hosted Typesense, use persistent SSD and the supported snapshot API;
do not copy the live Typesense data directory while the server is running
([backup procedure](https://typesense.org/docs/guide/backups.html)). Test
restore before bootstrap. For Typesense Cloud, document provider-managed HA
and backup assumptions and retain an independent export/restore decision.

During backfill and serving, monitor `/health`, RAM, CPU, SSD usage, request
latency, write rejection/backpressure, and MSC retry/error counts. Pause or
abort before knowingly exhausting disk or RAM. The current readiness tooling
offers a simple capacity preflight and remote `/metrics.json` read; it does
not install a monitoring stack.

Recovery is: stop safely, inspect report/checkpoint audit, resolve the source
or Typesense/data failure, rerun with `--resume`, and rerun final coverage,
UUID, count, sample, and benchmark audits. Alias activation is a separate
explicit operation after all gates pass.

## Phase boundary

No full historical import ran for Phase 3B-R. No production alias was
activated. Do not begin Phase 3B until production capacity and target are
approved from fresh measurements.
