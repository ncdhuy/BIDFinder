# Phase 4A FastAPI Typesense shadow reads

Phase 4A keeps Postgres procurement reads as the API authority. FastAPI builds
one canonical procurement query, executes the existing Postgres query first,
returns that unchanged response, then schedules a bounded Typesense read for
parity diagnostics.

```text
Browser
   ↓
FastAPI
   ↓
Canonical procurement query
   ├─────────────→ Postgres PRIMARY → user response
   │
   └─────────────→ Typesense SHADOW
                         ↓
                    parity metrics
```

## Read-path inventory and contract freeze

| Frontend use | Route | Current primary read | Request contract | Response contract | Shadow status |
| --- | --- | --- | --- | --- | --- |
| Normal/filter/text search, sort, first result window | `POST /api/query` | `fetch_result_page` → `build_result_query` → `DF1/DF2_*` CTEs and Postgres | `scope=all\|medicine\|goods`, `filters`, optional `sort[{column,order}]`, `limit`, `searchMode=standard\|full` | Existing `success`, `search_mode`, `df1`/`df2` pages, `count*`, `displayed`, `has_more`, `approx_total`, auth/quota fields, `total_count*` | Enabled by flag; Postgres result returned |
| Filter-only preview/count estimate | `POST /api/query-preview` | `fetch_preview_bucket_cached` / `fetch_combined_preview_meta` | `scope`, `filters` | Existing `success`, `total`, `exact`, `display`, `summary`, `total_estimate`, `bucket_limit`, optional scope estimate | Bounded count probe |
| Bulk/multi-query export | `POST /api/bulk-query` | `build_bulk_item_query` for each validated row, current diversity/truncation rules | `scope`, `fields`, `rows`, `diversityMode`, `priceLimit`, `productLimit`, `limit`, `searchMode` | Existing `bulk`, `df1`/`df2`, count and truncation fields | Up to first 20 row queries per sampled request |
| Autocomplete/suggestions | `POST /api/autocomplete` | `fetch_autocomplete_suggestions` with current cache, filters, scope, exclude-self rules | `scope`, `field`, `keyword`, `filters`, `excludeSelf`, `limit` | Existing `success`, `field`, `data`, `timing_ms` | Bounded suggestion probe |
| Filter metadata | `GET /api/filter-config` | Static field registry/options | No procurement query | Existing config payload | Not a procurement read |
| History/approval timeline | `GET /api/metadata` | `run_sessions`, `package_metadata` control-plane reads | No procurement query | Existing metadata payload | Excluded: control plane |
| Warmup | `GET /api/warmup` | `SELECT 1` / DB readiness | No procurement query | Existing health payload | Excluded: control plane health |

Current UI semantics remain authoritative: token filters use existing
OR/AND/NOT behavior, empty keyword autocomplete returns empty data, standard
search caps each scope at the existing default limit, full search keeps its
existing quota/allocation behavior, and the browser still receives `df1` and
`df2` only. No frontend files or public response fields changed.

The current Postgres tables expose serial `__row_id`; MSC/Typesense documents
use the authoritative MSC UUID. The comparator never compares those unrelated
identifiers. If a shared authoritative UUID is not present in both rows, it
uses an internal SHA-256 fingerprint over normalized stable source fields that
exist in both representations. Fingerprints use multiset/count semantics and
ambiguous duplicate groups are recorded as `IDENTITY_NOT_COMPARABLE` rather
than reported as false mismatches. The fingerprint and raw row contents are
never exposed through the public API or written to parity artifacts.

## Serving target and configuration

The adapter resolves only versioned physical collections:

```text
bidfinder_goods_v1_serving_v1_20260901
bidfinder_medicines_v1_serving_v1_20260901
bidfinder_traditional_v1_serving_v1_20260901
```

Stable aliases remain inactive and are never resolved by the adapter. The
default is safe: shadow reads are disabled unless explicitly enabled.

```text
BIDFINDER_TYPESENSE_SHADOW_ENABLED=false
BIDFINDER_TYPESENSE_SERVING_GENERATION=serving_v1_20260901
BIDFINDER_TYPESENSE_SHADOW_SAMPLE_RATE=0
BIDFINDER_TYPESENSE_SHADOW_TIMEOUT_SECONDS=0.5
BIDFINDER_TYPESENSE_SHADOW_REPORT_DESTINATION=
BIDFINDER_TYPESENSE_SHADOW_DEBUG_QUERIES=false
BIDFINDER_TYPESENSE_HOST=127.0.0.1
BIDFINDER_TYPESENSE_PORT=8108
BIDFINDER_TYPESENSE_PROTOCOL=http
BIDFINDER_TYPESENSE_API_KEY=<server-only search key>
```

The Typesense key is read only by FastAPI. It is never included in response
payloads, frontend configuration, parity reports, or browser requests.

## Query classes and failure policy

The canonical model classifies requests as `filter_only`,
`exact_identifier`, `full_text_relevance`, or `explicit_sort`. Filter and sort
translation uses the frozen V1 group schemas and records unsupported legacy
fields rather than fabricating fields. Date filters must be checked against the
live adapter and serving semantics; any remaining date-range discrepancy is
evidence for follow-up parity work, not a reason to weaken the comparator.

`SHADOW_INFRA_ERROR` covers timeout, unavailable service, malformed response,
missing key, and query errors. `SHADOW_PARITY_MISMATCH` is reserved for a
comparable semantic difference. Relevance ordering alone is P2; deterministic
filter, exact-identifier, explicit-sort, or field correctness failures are P0.
Totals/pagination/default mismatches are P1. Slow Typesense reads above 500 ms
are P3 and retain query class, filter names, sort, page size, result count,
and latency without raw query text.

Shadow work runs in an independent asyncio task after the primary response is
assembled. A Typesense failure cannot change the user-visible status or body.

## Offline harness

Run the deterministic synthetic three-group corpus:

```powershell
rtk python tools/typesense_shadow_parity.py
```

The harness writes `typesense-shadow-parity.json` and
`typesense-shadow-parity.md`. Reports contain fingerprints and aggregate
statistics only; raw user queries are not persisted. These artifacts are local
diagnostics and must not contain credentials or runtime databases.

## Operational gate

Before interpreting live mismatches, verify the Phase 3C.1 serving baseline:

- checkpoint coverage `9,738/9,738`;
- provenance integrity PASS;
- conflict 0 and unresolved reject 0;
- physical/provenance parity PASS;
- one live generation only: `serving_v1_20260901`;
- stable aliases inactive.

During a controlled local validation run, override the timeout to a bounded
diagnostic value of about 3 seconds (the safe default remains 0.5 seconds),
sample shadow traffic at 1.0, capture
Postgres/Typesense p50 and p95, enumerate Typesense reads over 500 ms, and
record Typesense RSS, WSL `MemAvailable`, swap, FastAPI RSS, and CPU. Do not
create another generation, activate an alias, change frontend behavior, or
make Typesense primary in Phase 4A.
