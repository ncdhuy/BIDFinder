# MSC Ingestion Runbook — Phase 2

Phase 2 provides an independently runnable MSC public-search ingestion engine.
It ends at canonical records plus a pluggable sink. Typesense integration and
historical import are Phase 3 work.

## Architecture

```text
MSC anonymous /search_prc
  -> one verified source/date parent
  -> pre-count
  -> adaptive time leaves (only secondary partition dimension)
  -> page.content pagination
  -> UUID union and content-conflict check
  -> parent post-count
  -> pure canonical normalization
  -> in-memory or atomic JSONL sink
  -> local SQLite checkpoint
```

The engine never calls `/export`, performs login, uses cookies, automates
reCAPTCHA/MFA, invokes Selenium, imports application Postgres modules, or
contacts Typesense.

## Source keys

| Source key | MSC label | Group | Exact tab | Fixed discriminator |
| --- | --- | --- | --- | --- |
| `goods_general` | Hàng hóa ngoài thuốc, thiết bị, vật tư y tế | `goods` | `HANG_HOA` | `type=HANG_HOA` |
| `medical_devices` | Thiết bị, vật tư y tế | `goods` | `THIET_BI_VAT_TU_Y_TE` | `type=HANG_HOA` |
| `medicine_generic` | Gói thầu thuốc Generic | `medicines` | `THUOC_TAN_DUOC` | `medicines=0` |
| `medicine_originator` | Gói thầu thuốc biệt dược gốc | `medicines` | `THUOC_TAN_DUOC` | `medicines=1` |
| `medicine_herbal` | Gói thầu thuốc dược liệu | `medicines` | `THUOC_TAN_DUOC` | `medicines=2` |
| `herbal_material` | Dược liệu | `traditional_medicine` | `DUOC_LIEU` | `medicine_type=[0,null]` |
| `traditional_medicine` | Vị thuốc cổ truyền | `traditional_medicine` | `VI_THUOC_CO_TRUYEN` | `medicine_type=[0,null]` |

Use `all` only when an explicit date range is also supplied.

## Commands

Validate one partition without a persistent sink or checkpoint:

```powershell
python -m crawler_engine.msc.cli validate `
  --source goods_general `
  --date 2026-08-25
```

Write one validated partition to local canonical JSONL:

```powershell
python -m crawler_engine.msc.cli validate `
  --source goods_general `
  --date 2026-08-25 `
  --output-dir .\crawler_engine\msc-output
```

Crawl an explicit range sequentially:

```powershell
python -m crawler_engine.msc.cli crawl `
  --from 2026-08-25 `
  --to 2026-08-27 `
  --sources goods_general,medical_devices `
  --output-dir .\crawler_engine\msc-output `
  --checkpoint .\crawler_engine\.msc_state\checkpoints.sqlite3
```

Useful controls: `--force` reprocesses a closed completed partition;
`--dry-run` selects the in-memory sink; `--timeout` controls request timeout;
`--request-delay` sets minimum delay between live requests; `--max-retries`
sets bounded retry attempts; `--max-partitions` caps a developer run;
`--allow-open-day` permits current-day validation without allowing permanent
`COMPLETED` state. There is no concurrency option in V1.

Bulk crawl requires both `--from` and `--to`. Reversed and future dates are
rejected. No command defaults to a multi-year range.

## Closed and open days

Dates before the current Vietnamese operational date (`Asia/Ho_Chi_Minh`) are
closed-day candidates and may become `COMPLETED`. The current day requires
`--allow-open-day` and ends in `VALIDATED`, never permanent `COMPLETED`. MSC
record timestamps are not converted to Vietnamese time; only the operational
date decision uses that timezone.

## Completeness gates

Every safe leaf has `expected_count <= 9500`, uses page size `1000`, and keeps
all required page offsets below the MSC result window `10000`. Each response
must have the expected `agg[0].buckets[0].docCount`, page metadata, and object
array `page.content`. UUIDs must be present and unique within a leaf and across
pages.

Sibling leaves overlap by one second: the left end is `midpoint + 1s` and the
right start is `midpoint`. Identical duplicate UUID content is deduplicated at
parent union. Different content for one UUID fails the parent. A duplicate in
non-overlapping leaves fails the parent.

Before sink completion:

```text
parent_pre_count
= parent_post_count
= unique_source_count
= normalized_count
= sink_accepted_count
```

No failed page, malformed record, normalization error, count change, or
incomplete sink write is silently skipped.

## Checkpoint and resume

The default local operational database is
`crawler_engine/.msc_state/checkpoints.sqlite3`; it is ignored by Git and is
not application/search data. Key is `source_key × partition_date`.

States:

```text
PENDING -> RUNNING -> COMPLETED
                    -> VALIDATED (open day)
                    -> FAILED
                    -> QUARANTINED
FAILED/QUARANTINED/VALIDATED/RUNNING -> RUNNING (rerun)
COMPLETED -> RUNNING only with --force
```

`RUNNING` is deliberately recoverable: a later sequential invocation claims it
again and increments `attempt_count`. A completed closed partition is skipped
by default. Failed and quarantined rows remain visible and are never treated as
done.

## Sinks

`InMemorySink` is used by tests and validation-only runs. `JsonlValidationSink`
writes one deterministic UTF-8 JSON object per line under
`<output>/<data_group>/<source_key>__<date>.jsonl`, sorted by MSC UUID. It
writes a temporary file in the target directory, flushes/syncs it, then
atomically replaces the target. It never appends partial duplicate runs and is
not a data-lake or R2 architecture.

## Error categories

Stable categories include `MSC_HTTP_ERROR`, `MSC_CONTRACT_ERROR`,
`SEARCH_WINDOW_OVERFLOW`, `COUNT_MISMATCH`, `UUID_DUPLICATE`,
`UUID_CONTENT_CONFLICT`, `UNSTABLE_PARENT`, `NORMALIZATION_ERROR`,
`SINK_INCOMPLETE`, and `SCHEMA_DRIFT` diagnostics. Network errors, HTTP 429,
and HTTP 5xx receive bounded exponential retry. HTTP 400, malformed JSON, and
structural/type errors do not retry.

## Traffic safety

Requests are sequential with a conservative default one-second minimum delay.
No concurrency is implemented. Logs report source/date, counts, request/retry
metrics, elapsed time, and actionable error categories without response bodies,
cookies, credentials, or session data.

The MSC endpoint has been observed to fail with Python/OpenSSL's default
verified context as `ssl.SSLError: [SSL: DH_KEY_TOO_SMALL] dh key too small`.
The production client uses an MSC-scoped verified context from
`crawler_engine.msc.tls.create_msc_ssl_context()`. It requires TLS 1.2 or newer
and offers only ECDHE AES-GCM/ChaCha20 suites for TLS 1.2 or older; TLS 1.3
remains available normally. CA validation and hostname verification remain
enabled, and OpenSSL's security level is not lowered. The tested runtime is
Python 3.12.4 with OpenSSL 3.0.13; deployments require a Python/OpenSSL runtime
with TLS 1.2 ECDHE support and a trusted system CA store.

Run the developer-only TLS diagnostic when troubleshooting:

```powershell
python -m tools.msc_tls_diagnostic
```

It reports runtime versions, effective cipher policy, handshake status, and
negotiated protocol/cipher without cookies, credentials, or response bodies.
Research compatibility overrides are not part of the production CLI.

## Typesense data-plane sink (Phase 3A)

Typesense is an optional crawler sink. Configure `TYPESENSE_HOST`,
`TYPESENSE_PORT`, `TYPESENSE_PROTOCOL`, `TYPESENSE_API_KEY`,
`TYPESENSE_TIMEOUT_SECONDS`, and `TYPESENSE_IMPORT_BATCH_SIZE`. The API key
is crawler/admin configuration only and is never sent to the browser. HTTPS
uses normal certificate and hostname verification; MSC's special TLS context
is not reused.

Create and validate a physical generation before crawling into it:

```powershell
python -m crawler_engine.msc.cli typesense create-generation --generation dev1
python -m crawler_engine.msc.cli typesense validate-generation --generation dev1
python -m crawler_engine.msc.cli crawl `
  --from 2026-08-25 --to 2026-08-25 --sources all `
  --sink typesense --generation dev1 `
  --checkpoint crawler_engine/.msc_state/phase3a.sqlite3
```

`--generation` is mandatory for Typesense writes. The sink writes only to
`bidfinder_<group>_v1_<generation>`, never to the stable aliases. Each batch
uses `documents/import?action=upsert`; every response line must be successful
and response count must equal request count. A partial HTTP-200 response fails
the sink and leaves the checkpoint non-completed.

After the controlled generation passes schema, count, UUID, idempotency, and
search smoke checks, activate explicitly:

```powershell
python -m crawler_engine.msc.cli typesense activate-generation --generation dev1
python -m crawler_engine.msc.cli typesense inspect
```

Rollback is an alias operation, not a data rewrite:

```powershell
python -m crawler_engine.msc.cli typesense rollback-alias --group goods --generation previous
```

For the full lifecycle, search allow-lists, seven-source controlled proof,
overflow proof, and troubleshooting, see
[`typesense-data-plane-runbook.md`](typesense-data-plane-runbook.md). Phase 3A
does not run historical backfill or modify FastAPI/frontend behavior.

## Phase 3B-R readiness controls

Historical backfill is not part of normal `crawl`. Use the dedicated
`backfill` command only after a plan-only manifest and capacity review:

```powershell
python -m crawler_engine.msc.cli backfill `
  --from 2023-02-01 --to 2026-08-29 `
  --sources all --generation hist_2026g1 `
  --checkpoint crawler_engine/.msc_state/historical.sqlite3 `
  --manifest backfill-plan.json --plan-only
```

This command performs seven aggregation counts, creates no Typesense
collection, imports no records, and never writes an alias. Actual execution
also requires `--max-partitions` and `--acknowledge-readiness`; it must use a
fresh physical generation, a dedicated checkpoint database, and the UUID audit
database. See [`historical-backfill-runbook.md`](historical-backfill-runbook.md).
