# Phase 4D — Early-User Production Stabilization Audit

Status: **PASS for the local Windows + WSL2 runtime**.

Starting state matched the requested branch and Phase 4C HEAD:

```text
branch: refactor-msc-typesense-v1
HEAD:   4622b6ca8ebf9ffc2bb619e06af1c179385ffd39
```

## Runtime

```text
Windows/network -> WSL2
  ├── bidfinder-typesense.service -> Typesense 30.2, loopback 8108/8107
  ├── bidfinder-api.service       -> FastAPI/uvicorn, loopback 8001
  └── bidfinder-incremental.timer -> MSC incremental ingestion
```

Typesense remains the primary procurement backend. Postgres is enabled only as an infrastructure-failure fallback. The active physical generation is still `serving_v1_20260901`; no new generation or historical generation was created or activated.

Operator commands:

```text
wsl.exe -d Ubuntu -- bash -lc 'bash /mnt/d/startup/muasamcong/BIDFinder/infra/runtime/bidfinder-install.sh start'
wsl.exe -d Ubuntu -- bash -lc 'bash /mnt/d/startup/muasamcong/BIDFinder/infra/runtime/bidfinder-install.sh stop'
wsl.exe -d Ubuntu -- bash -lc 'bash /mnt/d/startup/muasamcong/BIDFinder/infra/runtime/bidfinder-install.sh restart'
wsl.exe -d Ubuntu -- bash -lc 'bash /mnt/d/startup/muasamcong/BIDFinder/infra/runtime/bidfinder-install.sh status'
```

The lifecycle is Linux-native systemd user services with user lingering enabled. Typesense stops with SIGTERM and `SendSIGKILL=no`; the wrapper waits up to five minutes for a graceful stop. No interactive tmux session is required.

## Freshness and incremental ingestion

Coverage was complete through `2026-08-31` before catch-up and through `2026-09-01` afterward. Runtime latest fully closed Vietnam day was `2026-09-01`; the active next expected date is `2026-09-02`, which is not permanently completed.

Catch-up result: **PASS**.

- 21 partitions processed: 7 source contracts across 2026-08-30, 2026-08-31, and 2026-09-01.
- 18,651 records accepted; 0 retries, rejects, conflicts, or unresolved errors.
- Exact replacement was applied to changed goods partitions.
- Immediate second run skipped cleanly with 0 partitions and 0 records.
- Current physical counts: goods `9,596,715`; medicines `585,449`; traditional `32,022`; total `10,214,186`.

The operator status report exposes generation, coverage-through, latest closed day, next expected date, last successful run, unresolved errors, counts, and resource state without opening SQLite or printing credentials.

## Scheduling and locking

Timezone is explicitly `Asia/Ho_Chi_Minh`.

- Incremental: daily at 04:00, before Vietnam business hours.
- Log prune: daily at 03:30.
- Recovery snapshot: Sunday at 05:30.

The incremental and snapshot jobs share a `flock` maintenance lock. A concurrent invocation exits safely with `already running`; the lock test passed. A normal second incremental run is idempotent and skips completed closed partitions.

## Recovery snapshots

The snapshot service uses unique staging paths, copies Typesense state plus checkpoint/provenance/freshness files, checks SQLite integrity and generation, atomically publishes a `VALIDATED` bundle, and retains at most three validated bundles. It never prunes the only known-good recovery point.

One recovery proof completed successfully:

```text
bundle:     bundle-20260902T140327Z-30577ab677b553c7-2248
generation: serving_v1_20260901
coverage:   2026-09-01
size:       approximately 14G
status:     PASS / VALIDATED
```

Restore validates the bundle and uses a recoverable quarantine before replacing live data. A live restore was deliberately not performed against the 10M-document dataset; the snapshot’s integrity/generation validation is the safe recovery proof for this phase.

## Resource and log safety

At the final check:

- Typesense RSS: approximately 7.5 GB.
- WSL MemAvailable: approximately 10.7 GB.
- Swap used: approximately 12 MB of 8 GB.
- Free space on the WSL filesystem holding Typesense: 76.2%.
- Disk guard: warning at 25%, critical at 15%.
- RAM guard: warning at 2 GB available, critical at 1 GB.
- Idle Typesense CPU was 0%; one representative query showed short samples of 110%, 99%, and 17%, then returned to idle. This is not treated as sustained saturation.

Typesense, FastAPI, and ingestion output goes to the user journal. A daily prune bounds the user journal to 14 days/250 MB. Incremental output is also recorded compactly in `incremental-status.json`; massive CLI JSON is not sent to the service journal. Runtime logs, databases, snapshots, and recovery bundles are not committed.

## Network and security boundary

The final listeners were:

```text
127.0.0.1:8001  FastAPI
127.0.0.1:8108  Typesense API
127.0.0.1:8107  Typesense peering
```

Typesense is not publicly exposed. Its key is external, mode-600, and server-side; the frontend does not contain it. Debug query logging and shadow mode are disabled by default. The production full-query endpoint returned HTTP 401 without authentication, while the public preview path returned HTTP 200.

External ingress is intentionally **not configured**. A future reverse proxy or tunnel must expose FastAPI only, with authentication/TLS/network controls; do not expose Typesense directly. This is the only material limitation to opening the service beyond the local machine.

## HTTP Search Core smoke

The actual HTTP smoke used a persistent systemd-managed uvicorn process. Because the production environment is correctly anonymous-preview/auth-gated, a temporary loopback-only port 8002 process enabled anonymous full query access through environment variables only; it was stopped immediately after the suite.

Seven source journeys passed search, pagination, date filtering, and display/detail row checks:

```text
goods_general        PASS
medical_devices      PASS
medicine_generic     PASS
medicine_originator  PASS
medicine_herbal      PASS
herbal_material      PASS
traditional_medicine PASS
```

Full advertised-field contract passed over HTTP with zero failures:

```text
45 searchable / 36 filterable / 13 sortable / 17 autocomplete
```

Production-boundary checks passed: `/health` 200, `/ready` 200, `/api/search-contract` 200, unauthenticated `/api/query` 401, and `/api/query-preview` 200.

## Performance and concurrency

Five-sample HTTP measurements on the bounded local corpus:

| Operation | p50 | p95 | max |
|---|---:|---:|---:|
| Search | 482.823 ms | 510.693 ms | 596.537 ms |
| Filter | 14.040 ms | 14.083 ms | 14.795 ms |
| Broad quantity sort | 1001.405 ms | 1014.912 ms | 1020.725 ms |
| Autocomplete | 39.873 ms | 41.159 ms | 44.417 ms |

Modest concurrency passed with zero errors:

```text
1 client:  p95 470.643 ms
5 clients: p95 918.728 ms
10 clients: p95 1783.687 ms
```

## Fallback and restart proof

An isolated process with Typesense pointed at an unavailable loopback port returned HTTP 200 from `/api/query-preview` using the legacy Postgres subset, included `DEGRADED_POSTGRES_FALLBACK`, and emitted the same telemetry in the service journal. The production Typesense-primary process remained unchanged and healthy.

FastAPI clean restart passed, with startup journal output explicitly showing backend mode, `serving_v1_20260901`, Typesense availability, Postgres status, and coverage. A clean WSL shutdown/recovery simulation also passed: enabled user services auto-started, Typesense reloaded the same generation, and readiness returned after the normal disk-load window. No destructive power-loss test was performed.

## Validation

```text
repository tests: 190 passed, 1 skipped, 5 subtests passed
Python compile checks: PASS
Shell syntax checks: PASS
Frontend Node syntax checks: PASS
git diff --check: PASS
```

The broad repository root test command was not used as the gate because it has unrelated collection failures from a raw-data DrvFs I/O path and missing Selenium; the maintained `tests` suite passed completely apart from its existing skip.

## Known limitations and recommendation

- Postgres fallback is a legacy subset, not the complete corpus.
- Broad global quantity sorting is approximately one second p50.
- Serving generation is explicit rather than alias-based.
- Availability depends on Windows power, sleep/hibernate, updates, network, and WSL lifecycle.
- This is single-machine hosting, not HA.
- External FastAPI ingress is not configured.

Recommendation: the local runtime is ready for local/single-machine early-user operation without a continuously open Codex session. Do **not** open it to users outside this machine until a secured FastAPI-only ingress is added. Windows sleep/hibernate should be disabled while plugged in, and Windows Update/restart windows should be planned.
