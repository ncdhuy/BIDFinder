# Phase 3C.1 historical prefix extension audit

Status: **PASS**  
Starting HEAD: `0fd6754ff8dc609e43b3913ce04ea8e36eadc283`  
Branch: `refactor-msc-typesense-v1`

Prior Phase 3B/3C audits, manifests, checkpoint/provenance copies, and the historical recovery bundle were preserved unchanged.

## Source floors

Production `MSCClient.count_interval` preflight evidence is in `/home/ncdhuy/.local/share/bidfinder/typesense/reports/phase3c1-preflight-*.json`.

| Source | Verified floor | Evidence |
|---|---:|---|
| goods_general | 2022-01-01 | 2021 full year = 0; 2022 full year = 284,190 |
| medical_devices | 2023-01-01 | 2022 = 0; Jan 2023 = 80 |
| medicine_generic | 2023-01-01 | 2022 = 0; Jan 2023 = 0; Feb 2023 = 74 |
| medicine_originator | 2023-01-01 | 2022 = 0; Jan 2023 = 0 |
| medicine_herbal | 2023-01-01 | 2022 = 0; Jan 2023 = 0; Feb 2023 = 17 |
| herbal_material | 2023-01-01 | 2022 = 0; Jan 2023 = 0 |
| traditional_medicine | 2023-01-01 | 2022 = 0; Jan 2023 = 0 |

## Prefix execution

- `goods_general`: `2022-01-01..2023-01-31`, 396 partitions.
- Other six sources: `2023-01-01..2023-01-31`, 186 partitions total.
- Total completed: **582/582**.
- All completed partitions preserved the pre-count/post-count/unique/normalized/accepted invariants; unresolved rejects = 0.
- Records added by source: goods_general `394,288`; medical_devices `80`; all other prefix sources `0`.
- Target remained `serving_v1_20260901`; no third generation was created.

## Historical retirement and RAM

The historical final bundle was validated before retirement and remains offline-preserved:

`/home/ncdhuy/.local/share/bidfinder/typesense/recovery/hist_v1_20260829/final-bundle-hist_v1_20260829-20260901-a513d2c1c0774028aa8769c148043663`

It contains the Phase 3B final manifest/audit, snapshot state, checkpoint and provenance; both SQLite integrity checks returned `ok`.

Exactly these three live collections were deleted:

- `bidfinder_goods_v1_hist_v1_20260829`
- `bidfinder_medicines_v1_hist_v1_20260829`
- `bidfinder_traditional_v1_hist_v1_20260829`

Aliases were inactive. After retirement and after clean restart, the only live generation was `serving_v1_20260901`.

| Measurement | Typesense RSS | WSL MemAvailable | Swap free |
|---|---:|---:|---:|
| Before retirement | 13,827,440 KB | 4,792,472 KB | 8,376,580 KB |
| After retirement, before restart | 12,759,928 KB | 5,654,044 KB | 8,376,244 KB |
| Warm after restart | 7,308,576 KB | 11,215,936 KB | 8,374,524 KB |

Warm one-generation state also measured 99.94% CPU idle, 14,084 KB swap used, and 819,408,752 KB free disk. This is safe for temporary serving-only operation with headroom; a second full generation or broad backfill should not run concurrently.

## Coverage and parity

Checkpoint coverage is **9,738/9,738** logical source-day partitions through `2026-08-31`:

- goods_general: 1,704 dates from `2022-01-01`.
- Each other source: 1,339 dates from `2023-01-01`.
- Failed/quarantined/pending/stale RUNNING: all zero.

Final broad MSC counts versus checkpoint sums:

| Source | MSC broad count | Checkpoint sum |
|---|---:|---:|
| goods_general | 8,629,031 | 8,629,031 |
| medical_devices | 964,765 | 964,765 |
| medicine_generic | 494,720 | 494,720 |
| medicine_originator | 55,239 | 55,239 |
| medicine_herbal | 35,490 | 35,490 |
| herbal_material | 9,554 | 9,554 |
| traditional_medicine | 22,468 | 22,468 |

The initial broad reconciliation found a 7-row `goods_general` difference in the 2025 calendar-year interval (`2,557,868` current MSC count versus `2,557,875` checkpoint sum). Repeated count calls were stable. Recursive COUNT-only descent used 19 requests and pruned nine matching intervals, locating the complete drift at `2025-09-13` (`5,756` old versus `5,749` current). The normal production ingestion engine then re-fetched that date with parent pre/post counts, adaptive retrieval, normalization, and exact UUID replacement. It retained `5,749`, added `0`, removed `7`, and issued exactly `7` Typesense stale-ID deletes. No unrelated date was reprocessed.

Final seven-source broad parity is **PASS** after the bounded one-round reconciliation. All source broad counts now equal their serving checkpoint sums.

Provenance and Typesense group parity passed:

- goods: `9,593,796 = 9,593,796`
- medicines: `585,449 = 585,449`
- traditional_medicine: `32,022 = 32,022`
- UUID conflicts: `0`; unresolved rejects: `0`.

Boundary audit `2023-01-31 -> 2023-02-01` passed: all 14 source-day rows completed, duplicate source/date keys = 0, and UUID overlap = 0 for every source.

## Idempotency, recovery, restart, and smoke

No-force reruns passed with 396/396 and 186/186 result rows marked `skipped=true`; ingestion request count was zero (only one and six source preflight count calls respectively), and physical counts did not change.

A new serving recovery bundle was created and validated:

`/home/ncdhuy/.local/share/bidfinder/typesense/recovery/serving_v1_20260901/final-bundle-phase3c1-validated-20260902-f011f1aba46d461485ed9bd60965f1f6`

It includes the serving snapshot, checkpoint, provenance, final counts/fingerprints, coverage-floor registry, final serving manifest/report, prefix reports, reconciliation metadata, and lineage. Snapshot creation used one unique staging path and a snapshot-specific timeout; snapshot state and both SQLite integrity checks passed. Bundle status is `VALIDATED`. The prior `VALIDATED_PARTIAL` bundle remains preserved unchanged as evidence:

`/home/ncdhuy/.local/share/bidfinder/typesense/recovery/serving_v1_20260901/final-bundle-phase3c1-partial-20260902T0140Z`

Clean restart passed with unchanged physical counts, health `{"ok": true}`, no SIGKILL, inactive aliases, and one live generation.

Search smoke passed:

- 2022 goods (`2022-12-02`): found `6,815`, UUID read PASS.
- January 2023 (`2023-01-31`): found `5,127`, UUID read PASS.
- Recent 2026 (`2026-08-31`): found `12,437`, UUID read PASS.
- Filter + descending sort: found `5,127`; returned values were descending.

## Tests and disposition

- `python -m compileall -q crawler_engine/msc tests/msc tools`: PASS.
- `python -m unittest discover -s tests/msc -p "test_*.py"`: 140 tests, OK, 1 skipped.
- Recursive reconciliation, partition replacement/deletion, coverage-floor, and Phase 3C.1 tests are included in the full MSC unittest run.
- CLI help, audit JSON validation, `git diff --check`, and secret scan: PASS.
- `pytest -q tests/msc`: no tests collected because this suite is unittest-based.
- FastAPI/frontend unchanged.
- Phase 4 FastAPI shadow-read: **not started**.
- Commit: Phase 3C.1 completion commit; SHA recorded in completion handoff; no push.

Overall result: **PASS**. Phase 3C.1 is complete. Historical generation remains retired offline, stable aliases remain inactive, and Phase 4 has not started.
