# Historical backfill runbook (Phase 3B-R / Phase 3B-S)

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

## Empirical sizing result (Phase 3B-S — 2026-08-30)

Phase 3B-S passed against a fresh disposable Typesense `30.2` physical
generation. It used the production MSC partitioner, pagination validation,
canonical normalizer, `TypesenseSink`, default 500-document batches, and a
one-second MSC request delay. The sample stopped at 500,013 documents; it did
not start the full historical range and did not write to Neon/Postgres.

| Source contract | Sample documents |
| --- | ---: |
| `goods_general` | 391,435 |
| `medical_devices` | 35,408 |
| `medicine_generic` | 40,332 |
| `medicine_originator` | 5,013 |
| `medicine_herbal` | 10,002 |
| `herbal_material` | 9,554 |
| `traditional_medicine` | 8,269 |
| **Total** | **500,013** |

Dates were selected deterministically from monthly day-15 anchors, additional
day 01/04/08/12/20/22/26/28 anchors, then a daily fallback for sparse sources.
Every contract contributed records from 2023, 2024, 2025, and 2026. Milestone
RSS delta / `/data` delta were `50k: 200,744,960 / 117,593,620`,
`100k: 246,554,624 / 220,767,449`, `250k: 436,113,408 / 564,214,374`, and
`500k: 561,414,144 / 1,111,889,208` bytes. Typesense-specific memory metrics
were unavailable from this disposable endpoint; OS RSS and filesystem usage
are the authoritative empirical measurements in
[`typesense-sizing-report.json`](../typesense-sizing-report.json).

After graceful stop/start of the same data directory, all 500,013 documents
reloaded and group counts remained `goods=426,843`, `medicines=55,347`, and
`traditional_medicine=17,823`. Restart RSS delta was 597,524,480 bytes and
`/data` delta was 1,140,740,603 bytes. The expected UUID union equaled actual
Typesense counts for every group; all 1,569 import batches accepted all
500,013 documents with zero rejects.

The largest-sample empirical slopes were 1,122.824 RSS bytes/document and
2,223.721 data-directory bytes/document. Regression slopes were 960.567 and
2,229.868 bytes/document. At 9,801,385 documents, the largest-sample
projection is 11.01 GB RAM and 21.80 GB data directory; the regression RAM
projection is 9.52 GB. The actual-sample analytical comparison is 14.86–22.29
GB at 2x–3x indexed input; the earlier 7-document fixture estimate was
15.22–22.83 GB. The empirical result is therefore not relying on the small
fixture estimate.

The 32 GB/node decision is **PASS**: the conservative largest-sample RAM
projection is 32.0% of 32 GiB, below the 70% steady-state target. Growth
planning is approximately:

| Scenario | Documents | RAM | Data directory |
| --- | ---: | ---: | ---: |
| Current | 9,801,385 | 11.01 GB | 21.80 GB |
| +20% | 11,761,662 | 13.21 GB | 26.15 GB |
| +50% | 14,702,078 | 16.51 GB | 32.69 GB |

### Recommended production shape

Preferred: Typesense Cloud HA, 3 nodes, 32 GB RAM and 8 vCPU per node, with
provider disk allocation of at least 200 GB per node plus the provider's
backup policy. Self-hosted alternative: Typesense `30.2`, 3 nodes, 32 GB RAM,
8 vCPU, and at least 200 GB persistent SSD per node. Cloud remains preferred
for managed HA, replacement, upgrades, and backups; ingestion remains
provider-neutral.

The single-generation empirical disk projection is 21.80 GB and two physical
generations require 43.59 GB before snapshots and free-space margin. Keep at
least 50% free before creating another generation, warn below 35% free, and
block new generation creation below 20% free. Do not automatically delete a
rollback generation. The 200 GB recommendation provides useful room for
active, staging, rollback, snapshot, and growth needs.

The largest indexed-field contributions were goods `winning_bidder_name`
(3.72%), `source_tab_label` (3.62%), `technical_specification` (3.43%), and
`procuring_entity_name` (3.41%), plus medicines active ingredient (3.52%) and
authorization/permit (3.29%). No single field dominated the empirical input;
no schema field is removed in this phase.

Full-backfill authorization remains a separate decision. Before starting it,
create a new named physical generation, regenerate and approve the exact
closed-range manifest, verify target capacity and backups, run the final
source/UUID/count/search audits, and explicitly acknowledge the historical
write. Alias activation and application cutover require a later approval.

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

## Local dogfood / local production-like mode

The first long-lived Typesense target is a single Typesense `30.2` node in
native Ubuntu/WSL storage. It is private-only (`127.0.0.1:8108`) and is not an
HA target. Start it from WSL with:

```bash
bash infra/typesense/local-typesense.sh start
bash infra/typesense/local-typesense.sh health
bash infra/typesense/local-typesense.sh status
bash infra/typesense/local-typesense.sh restart
bash infra/typesense/local-typesense.sh stop
```

Primary data lives at `~/.local/share/bidfinder/typesense/data`; snapshots,
checkpoints, reports, logs, and run state are separate sibling directories.
The local canary uses a generation-aware checkpoint and UUID audit database
under `checkpoints/`; it never uses the sizing or future historical
checkpoint. Create snapshots with the supported `/operations/snapshot` API,
never by copying live data. Restore only into a separate disposable data
directory and validate counts/search before stopping it.

Keep normal Typesense requests conservative with `TYPESENSE_TIMEOUT_SECONDS`
(default `10`). Set `TYPESENSE_SNAPSHOT_TIMEOUT_SECONDS` independently (default
`300`) because `/operations/snapshot` is a long-running administration
operation. Do not add blind snapshot retries after a client timeout; validate
the snapshot directory and persistent state before any operator retry.

Before a future historical run, verify free disk for the projected generation,
a snapshot, and a second generation; monitor WSL available memory, Typesense
RSS, CPU, and swap. Avoid large local LLM or other memory-heavy workloads
during backfill, and prevent Windows Sleep/Hibernate during ingestion or
serving. Full historical execution remains locked behind explicit `--from`,
`--to`, `--generation`, `--checkpoint`, `--manifest`, readiness acknowledgement,
matching fingerprints, and
`--authorize-full-run AUTHORIZE_PHASE_3B_HISTORICAL_BACKFILL`. Do not supply
that authorization during local-target validation.

The intended local generation is `hist_v1_20260829`; the authorized Phase 3B
coordinator is `tools/phase3b_historical_backfill.py`.
It freezes the closed `2023-02-01..2026-08-29` range and the seven-source
totals in the signed-off manifest, keeps stable aliases inactive, and writes
only to the generation-specific Typesense collections.

Run it from WSL with the Typesense environment loaded:

```bash
python3 tools/phase3b_historical_backfill.py \
  --from 2023-02-01 --to 2026-08-29 --generation hist_v1_20260829 \
  --manifest "$HOME/.local/share/bidfinder/typesense/reports/historical-manifest-hist_v1_20260829.json" \
  --checkpoint "$HOME/.local/share/bidfinder/typesense/checkpoints/hist_v1_20260829.sqlite3" \
  --uuid-audit "$HOME/.local/share/bidfinder/typesense/checkpoints/hist_v1_20260829.uuid.sqlite3" \
  --report "$HOME/.local/share/bidfinder/typesense/reports/hist_v1_20260829.backfill-report.json" \
  --recovery-dir "$HOME/.local/share/bidfinder/typesense/recovery/hist_v1_20260829" \
  --audit-json historical-backfill-audit.json \
  --audit-markdown historical-backfill-audit.md \
  --max-partitions 9142 --acknowledge-readiness \
  --authorize-full-run AUTHORIZE_PHASE_3B_HISTORICAL_BACKFILL
```

The coordinator checkpoints each source/date parent, records UUID provenance
on disk, stops at `MemAvailable < 2 GiB`, critical disk pressure, or sustained
swap growth, and creates validated Typesense/SQLite recovery bundles initially,
about every 1,000,000 accepted documents, and at final completion. A controlled
SIGINT/SIGTERM is resumable: wait for the process to exit, inspect the JSON
report, then rerun the same command with `--resume` (never global `--force`).
On resume, the authorized start manifest is preserved; mutable broad source
counts are recorded in a separate `.observed.json` manifest. Count-only
completed-prefix reconciliation identifies changed dates recursively. Only
those dates are replaced, including exact stale UUID deletion; suffix-only
drift does not rewrite completed partitions. Never use SIGKILL.

The final audit is PASS only after source-coverage reconciliation, UUID and
Typesense count parity, zero rejected imports, representative MSC-to-Typesense
document parity, search and concurrency benchmarks, a final recovery bundle,
and a clean Typesense restart. Alias activation remains a separate operation.
Later migration to Hetzner/Linux can use a validated snapshot or a fresh
historical generation with the same collections, checkpoints, and engine; only
the operator service wrapper changes.
