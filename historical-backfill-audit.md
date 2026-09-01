# Phase 3B-F — Final Historical Audit

Status: **PASS**

Generation: `hist_v1_20260829`

Frozen range: `2023-02-01` through `2026-08-29` (Asia/Ho_Chi_Minh, closed upper boundary)

Starting HEAD: `fd87d841a8e214ea77325ec912c649621013c3b4`
Branch: `refactor-msc-typesense-v1`

## Runtime and coverage

No historical writer was active before finalization. Typesense 30.2 was healthy on loopback `127.0.0.1:8108`, using data path `/home/ncdhuy/.local/share/bidfinder/typesense/data`.

Checkpoint DB integrity: **PASS**. Sink `typesense:hist_v1_20260829` has **9,142/9,142** logical partitions in final state:

- COMPLETED: 9,142
- FAILED: 0
- QUARANTINED: 0
- RUNNING/stale: 0
- missing: 0

| Source | Expected | Completed | Fresh MSC count | Checkpoint parent sum | Parity |
|---|---:|---:|---:|---:|---|
| goods_general | 1,306 | 1,306 | 8,219,041 | 8,219,041 | PASS |
| medical_devices | 1,306 | 1,306 | 964,685 | 964,685 | PASS |
| medicine_generic | 1,306 | 1,306 | 494,698 | 494,698 | PASS |
| medicine_originator | 1,306 | 1,306 | 55,239 | 55,239 | PASS |
| medicine_herbal | 1,306 | 1,306 | 35,489 | 35,489 | PASS |
| herbal_material | 1,306 | 1,306 | 9,554 | 9,554 | PASS |
| traditional_medicine | 1,306 | 1,306 | 22,468 | 22,468 | PASS |
| **Total** | **9,142** | **9,142** | **9,801,174** | **9,801,174** | **PASS** |

Traversal accounting: run-local completed 373 + skipped previous checkpoints 8,769 = 9,142; normalized 9,801,174; accepted 9,801,174; attempted 9,801,174; expected 9,801,174; rejected 0; failed 0; quarantined 0.

## Manifest lineage and reconciliation

| Manifest | Total | goods_general | Other six sources | Fingerprint |
|---|---:|---:|---|---|
| Authorized start | 9,801,380 | 8,219,247 | unchanged | `717bd0a5...bffb9e` |
| R2 observed | 9,801,174 | 8,219,041 | unchanged | `1c5736db...3750d` |
| Final observed | 9,801,174 | 8,219,041 | unchanged | `507609bb...d06d5c` |

The only observed lineage change was authorized → R2 goods_general -206. R2 → final changed no source.

Fresh broad aggregation made exactly **7** current MSC count requests, with zero retries and no pagination. Every source matched its completed checkpoint parent sum. Recursive COUNT-ONLY requests: **0**. Changed historical source/date partitions: **none**. Final reconciliation status: **PASS**; bounded reconciliation remained stable.

## Provenance, Typesense, and rejection accounting

UUID provenance DB integrity: **PASS**; unique UUIDs: **9,801,174**; unresolved UUID conflicts: **0**.

| Logical group | Provenance unique UUIDs | Physical Typesense documents | Parity |
|---|---:|---:|---|
| goods | 9,183,726 | 9,183,726 | PASS |
| medicines | 585,426 | 585,426 | PASS |
| traditional_medicine | 32,022 | 32,022 | PASS |
| **Total** | **9,801,174** | **9,801,174** | **PASS** |

Final broad source rows, accepted partition rows, authoritative UUIDs, and physical documents are each 9,801,174. No cross-partition UUID reuse was observed.

R4’s historical timeout at `goods_general:2026-06-01` produced a failed-attempt evidence report with 500 rejected transport writes. The safe reattempt reconciled the partial physical write. Final unresolved rejected count is **0**; the failed-attempt evidence remains preserved.

Operational lineage:

- R1: generic snapshot timeout around 6.025M.
- R2: upstream historical count drift and recovery-resume hardening.
- R3: Typesense HTTP 500 Copy failed from reused/pre-created snapshot destination; unique staging introduced.
- R4: batch transport timeout with a 500-document partial write; exact UUID reconciliation resolved it without source loss.

## Schema and deterministic parity

Schema drift status: **PASS**. Additive observations remain diagnostic:

- herbal_material: `donGiaDuThau`, `soNhaThauThamDu`, `decisions`
- medicine_originator: `decisions`
- traditional_medicine: `medicineType`, `decisions`

Breaking drift: none.

Deterministic source → normalization → Typesense parity: **21/21 PASS**, zero mismatch, zero no-record samples, zero errors, zero retries. Coverage was 7 early-period, 7 middle-period, and 7 recent-frozen samples across all seven source contracts.

## Search and concurrency benchmarks

All benchmarks targeted physical `hist_v1_20260829` collections; aliases were not used.

- Expanded search benchmark: 48 requests, 0 errors, p50 **9.560 ms**, p95 **2,387.846 ms**, max **2,448.825 ms**. Coverage included goods item/manufacturer/bidder/tender/source-tab/price filters and both price sorts; medicine name/ingredient/manufacturer/bidder-tender; traditional item/scientific/manufacturer-source/bidder-tender; and one multi-search spanning all three collections.
- Concurrency 1 client: 42.861 req/s, p50 10.245 ms, p95 10.245 ms, errors 0%.
- Concurrency 10 clients: 736.748 req/s, p50 5.042 ms, p95 6.755 ms, errors 0%.
- Concurrency 25 clients: 1,077.756 req/s, p50 8.425 ms, p95 12.929 ms, max 13.428 ms, errors 0%.

The price-filter sort cases account for the high bounded-search p95/max; no material errors occurred.

## Resources

Pre-restart steady state: Typesense RSS 7,145,013,248 bytes; WSL total 20,971,155,456 bytes; MemAvailable 11,126,685,696 bytes; swap 8,589,934,592 total / 3,145,728 used; 16 CPUs; data directory 6,204,912,850 bytes; free disk 970,634,117,120 bytes.

Post-restart steady state: Typesense RSS metric 7,220,207,616 bytes (ps RSS 7,176,988 KB); WSL total 20,971,155,456 bytes; MemAvailable 11,585,949,696 bytes; swap 8,589,934,592 total / 12,132,352 used; data directory 6,201,196,856 bytes; free disk 956,119,764,992 bytes.

The measured full-generation footprint is below the Phase 3B-S projections of approximately 11–11.7 GB RAM and 22 GB disk; headroom is safe.

## Recovery bundle

Existing validated bundles were preserved: `bundle-00002-milestone-5021039`, `bundle-00003-milestone-6025897`, `bundle-00004-milestone-6199994`, `bundle-00005-milestone-7209518`, `bundle-00006-milestone-8216273`, and `bundle-00007-milestone-9216663`. Quarantined failed artifacts preserved: `quarantine-bundle-00002-milestone-6025055.tmp` and `quarantine-bundle-00005-milestone-7208917.tmp`. The final snapshot staging directory remains preserved.

Final coherent bundle: `/home/ncdhuy/.local/share/bidfinder/typesense/recovery/hist_v1_20260829/final-bundle-hist_v1_20260829-20260901-a513d2c1c0774028aa8769c148043663`

- Status: VALIDATED
- 169 files / 8,363,691,317 bytes
- Typesense snapshot: 160 files / 6,176,307,805 bytes; HTTP 201; unique staging; 900-second snapshot-specific timeout
- Checkpoint and provenance SQLite integrity: `ok`
- UUID conflicts: 0
- Snapshot tree SHA-256: `264b471b...d408b`
- Checkpoint SHA-256: `97578ccc...e3eeb`
- Provenance SHA-256: `ffde82ee...bab425`

The bundle contains the supported snapshot, checkpoint/provenance copies, final report, final manifest, manifest lineage, reconciliation metadata, source/group counts, fingerprints, and bundle metadata.

## Clean restart, generations, aliases, and tests

Exactly one clean restart operation was performed. The lifecycle helper’s bounded stop/health waits expired, but the old PID 853 then exited gracefully with the logged `Bye`, and the new PID 41164 eventually completed its full-data reload. Final health is `{"ok":true}`; Typesense is 30.2. Post-restart physical collection counts, representative UUID retrieval for all three groups, representative searches, and multi-search all passed. No recovery crash was detected.

The live envelope is exactly two generations: `local_canary_20260831_29ef44` and `hist_v1_20260829`, six physical collections total, with no third live generation. Stable application aliases `bidfinder_goods`, `bidfinder_medicines`, and `bidfinder_traditional` remain inactive (Typesense aliases list is empty).

Validation completed:

- `uv run --with pytest pytest tests/msc -q`: **130 passed, 1 skipped, 5 subtests passed**
- compileall: PASS
- lifecycle shell syntax: PASS
- audit/manifest JSON validation: PASS
- `git diff --check`: PASS
- secret scan: known unrelated baseline failure in tracked `conversation.md` (credentialed-Postgres-URL pattern); no new secret was added and that file was not modified

Phase 3B final gate: **PASS**. Completion commit message: `Phase 3B: complete historical Typesense backfill`.

Later phases were not started: no incremental catch-up, alias activation, FastAPI change, or frontend change.
