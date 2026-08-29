# BIDFinder MSC-to-Typesense Migration Plan

Status: Phase 0 audit and design baseline only.

Baseline reviewed: `refactor-phase-0-7` at `0dcab303bdb4cf23d661b6e53802057705afff49` (`Change UI`, 2026-08-29).

This document records the smallest viable migration path from the current Selenium/Postgres procurement-data path to the MuaSamCong (MSC) winning-bid APIs, a deterministic crawler/normalizer, Typesense, and the existing FastAPI/static-web product. It does not authorize or implement Phase 1 ingestion.

## 1. Scope and non-goals

### In scope

- Searchable winning-bid data from the seven HÀNG HÓA source tabs.
- Three logical data groups: `goods`, `medicines`, and `traditional_medicine`.
- MSC search-count and export-count validation.
- Versioned Typesense collections with stable logical aliases.
- Adaptation seams for the existing FastAPI routes and static UI.
- A later read-only chatbot that uses the same search/read path.

### Out of scope

- Crawler implementation, MSC contract discovery execution, normalization code, Typesense provisioning, or Typesense imports.
- Dịch vụ tư vấn and Dịch vụ phi tư vấn.
- Analytics warehouse, data lake, Parquet, ClickHouse, reports, dashboards, alerts, agents, and event bus/orchestrator work.
- Authentication, sessions, password reset, feedback, or forum data in Typesense.
- Deployment, push, production migration, or production-data writes.

## 2. Current architecture

The current production route is:

```text
Static apps/web UI
  -> Cloud Run FastAPI (primary) or Render FastAPI (backup)
  -> Neon Postgres
```

The legacy data path is:

```text
Selenium Chrome crawler
  -> Postgres packages / package_metadata / run and scan state
  -> downloaded PDF/DOCX/XLSX assets in local storage or R2
  -> Excel-oriented ETL and human-review workflows
  -> processed_medicines / processed_goods
  -> FastAPI SQL CTEs and query builders
  -> df1 / df2 result tables in the static UI
```

`crawler_engine/` intentionally remains at repository root. It is a legacy crawler backup and must not be moved, renamed, duplicated wholesale, or cleaned up as part of this migration.

## 3. Dependency inventory

### 3.1 Legacy crawler modules

| Component | Current dependencies and responsibility | Reuse for MSC V1 | Must not survive as V1 dependency |
| --- | --- | --- | --- |
| `crawler_engine/s0_init_db.py` | `psycopg2`, `python-dotenv`; creates/evolves legacy Postgres tables and indexes, including `packages`, `package_metadata`, `daily_manifest`, processed tables, scan state, and app control-plane tables | None of procurement schema; use only as historical reference for control-plane boundaries | Legacy procurement table migration and schema ownership |
| `crawler_engine/s1_crawler.py` | Selenium Chrome, pandas, psycopg2, local/R2 file movement; navigates the public portal, crawls notice/package detail pages, downloads files, tracks versions, writes package metadata and scan history | Small, separately tested text/date/identifier cleaning ideas only if they are source-agnostic | Selenium navigation, browser waits, DOM selectors, download handling, PDF/Excel attachment reconciliation, old package/version logic, Postgres writes |
| `crawler_engine/s2_daily_manager.py` | Human workspace and daily-manager menu; imports `schema_config`, `storage_adapter`, `web_winner_facts`, `s3_etl_pipeline`, and shared Excel helpers; performs anomaly scans, manifest finalization, OCR/manual review import, purge, and cleanup | None of its orchestration; review invariants may inform fail-closed behavior | Human Excel/OCR/manual-review workflow, manifest lifecycle, purge workflow, legacy package reconciliation |
| `crawler_engine/s3_etl_pipeline.py` | pandas/NumPy/SQLAlchemy/psycopg2; reads Excel through local/R2 resolution, applies schema mapping and grouped-row repair, reconciles QĐ relations, writes processed tables, duplicate flags, manifests, and metadata | Deterministic cell-cleaning rules only after review; reuse must be extracted narrowly and proven against MSC samples | Excel-header inference, grouped-row repair, vendor-header repair, QĐ relation reconciliation, Postgres ETL, package deletion/archive, legacy `medicine`/`goods` table assumptions |
| `crawler_engine/schema_config.py` | Two legacy `MEDICINE_STANDARD` and `GOODS_STANDARD` configurations; header aliases, mandatory/output columns, DB mappings, merge keys, indexes | No direct schema; use as evidence of old UI/data assumptions | Treating Excel aliases or old DB mappings as MSC contract |
| `crawler_engine/schema_normalization_shared.py` | pandas/openpyxl helpers for whitespace/header normalization, smart Excel column mapping, duplicate-column collapse, numeric cleaning, header-row detection, invalid-row filtering, and legacy `.xls` conversion | `clean_col_str`, Unicode/whitespace normalization, and carefully selected numeric/date primitives may be candidates | Excel header detection, workbook/sheet selection, openpyxl repair, `excelcnv`/COM conversion, schema inference |
| `crawler_engine/storage_adapter.py` | boto3-compatible R2 adapter plus local temporary-file resolution, upload/download/move/delete, R2-key detection | None for the minimal API-to-Typesense path unless a later decision requires a small raw-response cache | R2/local asset archive as an implicit source of truth; PDF/DOCX/XLSX storage pipeline |
| `crawler_engine/web_winner_facts.py` | pandas/NumPy helper for sparse winner/vendor inference and manual-review escalation | None unless an MSC export proves the same deterministic gap | Vendor fallback and human-review rules derived from legacy web tables |
| `crawler_engine/drug_group_parser.py` | Accent-insensitive parsing of old medicine group labels into `BDG`, `N1`-`N5`, `UNKNOWN` | Candidate only if MSC exports the same semantic field and values; must not be silently applied otherwise | Assuming old `nhom_thuoc_filter` values are MSC source values |
| `crawler_engine/admin_app.py` | Streamlit/SQLAlchemy admin UI for scan anomalies and QĐ relations | None | Legacy admin UI and direct Postgres editing |

### 3.2 Internal callers, scheduled workflows, and side effects

- `s0_init_db.py`, `s1_crawler.py`, `s2_daily_manager.py`, and `s3_etl_pipeline.py` are primarily executable scripts with `__main__` entry points, not a clean application package.
- `s1_crawler.py` is run directly and imports `storage_adapter`; no repository scheduler was found that imports it.
- `s2_daily_manager.py` imports `s3_etl_pipeline`, `schema_config`, `storage_adapter`, `web_winner_facts`, and `schema_normalization_shared`; it is an interactive daily-management tool, not the future MSC scheduler.
- `s3_etl_pipeline.py` is imported by `s2_daily_manager.py` and by audit scripts through dynamic module loading. It also imports `schema_config`, `storage_adapter`, `drug_group_parser`, `web_winner_facts`, and `schema_normalization_shared`.
- `schema_normalization_shared.py` is used by the legacy ETL, Excel merge/audit scripts, and `tests/crawler/test_schema_normalization.py`.
- `storage_adapter.py` is used by the crawler, ETL, archive tool, and audit/repair scripts.
- `.github/workflows/checks.yml` runs unit tests, JavaScript syntax checks, and Python compile checks. It does not schedule crawling or ETL.
- No cron, GitHub Actions crawler schedule, or deployment-managed crawler job was found in the inspected repository. Existing daily behavior is operator-invoked through the legacy scripts.

### 3.3 Audit and repair artifacts affecting processed data

These files are project artifacts and remain in place. They were inspected but not executed.

| Files | Behavior | Migration handling |
| --- | --- | --- |
| `audit_docx_conversion.py`, `audit_khlcnt_no_linked_identity.py`, `audit_processed_unit_row_counts.py`, `audit_summary_rule_risk.py`, `temp_audit_existing_vendor_fill_risk.py` | Read legacy files and/or Postgres; produce audit findings, CSV/XLSX output, or manual-review evidence | Do not port as ingestion logic; preserve as historical evidence until legacy shutdown |
| `backfill_nhom_thuoc_filter.py` | Optional/dry-run-aware `UPDATE processed_medicines` for old drug-group filter values | Obsolete for MSC unless a verified MSC field requires the same classification; never run as part of MSC ingestion |
| `repair_processed_relations.py` | Deletes/updates `processed_medicines` and `processed_goods` based on legacy relation state | Obsolete for MSC; no equivalent inferred without a source contract |
| `repair_numeric_x10_bug.py` | Updates legacy processed tables and writes a repair backup table | Obsolete for MSC; source numeric parsing must be deterministic before import |
| `temp_repair_mismatch_units_from_audit.py` | Deletes/reinserts processed rows and updates manifest/issues | Obsolete for MSC; fail the partition instead of repairing silently |
| `repair_missing_local_files.py` | Reads/updates `daily_manifest` paths and may recover local assets | Obsolete for API/export ingestion |
| `archive_to_r2.py`, `merge_extracted_excels.py`, temporary CSV/TXT/XLSX/Notebook files | Archive or inspect legacy assets and analysis outputs | Keep as legacy artifacts; do not duplicate or fold into V1 |

The legacy repair scripts make broad Postgres changes. Phase 0 did not connect to Postgres, write to files outside the requested documentation, or run any repair/backfill/crawler workflow.

## 4. Backend procurement-data dependency map

`apps/api/server.py` currently owns FastAPI routes, auth/access policy, in-memory rate/quota/cache state, SQL query construction, serialization, and database-pool lifecycle. `apps/api/auth_utils.py` owns password/session/reset/Google-auth helpers. `apps/api/explain_hot_queries.py` is a read-only Postgres inspection utility.

### 4.1 Procurement-data Postgres dependencies to replace

| Current dependency | Current role | Required future seam |
| --- | --- | --- |
| `DF1_CTE` and `DF1_SEARCH_CTE` | `processed_medicines` rows, joined to `package_metadata`, with duplicate-warning flags and legacy display aliases | Typesense medicine collection search document; no SQL join |
| `DF2_CTE` and `DF2_SEARCH_CTE` | `processed_goods` rows, joined to `package_metadata`, with duplicate-warning flags, display aliases, and a goods search blob | Typesense goods collection search document; build explicit searchable fields instead of an opaque SQL blob |
| `DF1_PREVIEW_CTE` / `DF2_PREVIEW_CTE` and preview builders | Bounded preview counts based on Postgres query results | Typesense count/preview service with equivalent access policy and clearly labeled exact/estimated results |
| `processed_medicines` / `processed_goods` | Main procurement line-item stores | Replaced by `bidfinder_medicines`, `bidfinder_goods`, and `bidfinder_traditional` logical aliases |
| `package_metadata` | Package-level investor, approval, selection-method, place, validity, and approval-timeline data | MSC export fields become document fields where supplied; fields absent from MSC are not fabricated |
| `processed_duplicate_flags` | Legacy duplicate warning joined into result rows | Must be explicitly re-decided for MSC. Do not carry it forward as a synthetic flag without a source or deterministic duplicate policy |
| `BULK_SEARCH_FIELDS` and `build_bulk_item_query` | Two-scope SQL field maps, per-row matching, price/product diversity, and result truncation | Typesense multi-search or batched per-row queries compiled from the stable bulk payload; preserve response semantics and limits |
| `FIELD_REGISTRY` and `build_scope_filters` | Token, fixed-list, validity, drug-group, and date filter compilation to SQL | Typesense query compiler preserving user semantics; each field must map to a verified normalized field |
| `ALLOWED_SORT_DF1` / `ALLOWED_SORT_DF2` | SQL sort allow-lists and approval-date default | Typesense sort fields with typed numeric/date values; remove sort options whose source values do not exist |
| `/api/metadata` | Mixes legacy crawler `run_sessions` history with a `package_metadata` approval timeline | Replace or narrow to migration-appropriate operational metadata; do not make this a reason to keep procurement queries in Postgres |
| `/api/warmup` | `SELECT 1` database warmup | Future health/warmup must cover Typesense search availability; auth/control-plane DB health remains separate |

Every procurement-data route must eventually stop querying Postgres. This includes ordinary search, full search, preview, autocomplete, bulk query, data metadata, and any procurement-specific warmup/count path. A temporary dual-read or shadow comparison may exist during a later cutover only if explicitly scoped, observable, and removable.

### 4.2 Postgres control-plane exception to preserve

Neon/Postgres may remain temporarily as the control-plane store for existing behavior. It must not be conflated with procurement-data storage.

- `app_users`: registration, password login, Google login identity, profile updates, admin identity.
- `app_user_sessions`: session token hashes, expiry, last-use/touch, revocation.
- `app_password_reset_tokens`: password-reset token lifecycle.
- `app_feedback`, `app_feedback_topics`, `app_feedback_replies`: feedback and forum state.
- Database access policy, session cookies/bearer tokens, password reset transport, and admin checks remain in `auth_utils.py`/`server.py`.

Passwords, users, sessions, password resets, and feedback/forum records must never be stored in Typesense. Existing rate limiting, anonymous access levels, full-search quotas, CORS/security headers, and authentication behavior remain unchanged unless a separate product decision says otherwise.

Operational ingestion checkpoints are not browser-facing procurement documents. Phase 1 must choose a durable checkpoint store per `date × source_tab`; a small control-plane table is a candidate, but it must not be read by procurement query routes or become a hidden product-data dependency.

## 5. Frontend dependency map

The UI is static and must remain static. Phase 0 does not redesign styling, analytics, layout, or interaction language.

| File | Current assumption | Later adaptation required |
| --- | --- | --- |
| `apps/web/index.html` | Two result panels/tabs: `df1-panel` labelled Thuốc and `df2-panel` labelled Hàng hóa; count switchers, hide/show columns, Excel download, full-search controls, advanced filter panel, bulk modal, map/chart/metadata UI | Add or expose traditional-medicine results without discarding current panels. Exact compatibility shape must be chosen before implementation; preserve existing styling and controls |
| `apps/web/script.js` | `DF1_COLUMNS_ORDER` and `DF2_COLUMNS_ORDER`; `TABLE_CONFIGS`/`TABLE_MAP`; result normalization expects `result.df1` and `result.df2`; renders old Vietnamese column names; applies local mini-filters and local sorting; posts `/api/query`, `/api/query-preview`, `/api/bulk-query`, `/api/metadata` | Consume three logical groups, stable normalized field labels, typed dates/numbers, and any compatibility response. Do not silently map missing source fields to old legacy columns |
| `apps/web/search-form.js` | Shadow-DOM custom search form; token filters for investor, drug name, active ingredient, approval decision, winner, concentration, route, dosage, specification, registration number, unit, manufacturer, country; multi-select selection method/place/drug group; validity and approval-date controls; autocomplete posts `scope: 'all'`, field, keyword, current filters, `excludeSelf`, and limit | Keep user filter payload and OR/AND/NOT semantics. Add only source-backed fields and a third logical scope when the data contract requires it |
| `apps/web/auth.js` | Auth API base selection, bearer token plus `credentials: 'include'`, session verification, access flags, login/register/logout/password-reset/profile/feedback flows | No Typesense calls from browser. Keep auth endpoints, cookies/tokens, and access gating unchanged |
| `apps/web/config.js` | Central API base URL selection for Cloud Run/Render | No direct Typesense URL or admin/search key in frontend configuration |

Current frontend assumptions that must change later:

1. `df1`/`df2` are not a complete model for three Typesense collections.
2. `scope` is currently `all|medicine|goods`; traditional medicine needs a defined scope/group contract.
3. Column definitions and local formatters include legacy package metadata such as approval/validity fields that MSC may not provide.
4. Bulk field checkboxes currently support only medicine/goods legacy field maps.
5. Preview, autocomplete, sorting, and chart/map/metadata code is coupled to old response columns and must be checked field-by-field.
6. Existing full/standard search and anonymous/authenticated access behavior must remain visible at the API boundary while the storage implementation changes.

## 6. Seven source tabs to three logical groups

| Logical group | MSC source-tab label | Exact `source_tab` value |
| --- | --- | --- |
| `goods` | Hàng hóa ngoài thuốc, thiết bị, vật tư y tế | Unknown; discover from the official request contract |
| `goods` | Thiết bị, vật tư y tế | Unknown; discover from the official request contract |
| `medicines` | Gói thầu thuốc Generic | Unknown; discover from the official request contract |
| `medicines` | Gói thầu thuốc biệt dược gốc | Unknown; discover from the official request contract |
| `medicines` | Gói thầu thuốc dược liệu | Unknown; discover from the official request contract |
| `traditional_medicine` | Dược liệu | Unknown; discover from the official request contract |
| `traditional_medicine` | Vị thuốc cổ truyền | Unknown; discover from the official request contract |

`source_tab_label` is the exact human-readable label above. `source_tab` must preserve the exact MSC discriminator discovered for that source. No enum is invented in Phase 0. The full canonical field contract is in [msc-source-schema-v1.md](msc-source-schema-v1.md).

## 7. Known MSC API contract

### Search

```text
POST https://muasamcong.mpi.gov.vn/o/egp-portal-winning-bid-data/services/smart/search_prc
```

Observed request envelope:

```json
[
  {
    "pageSize": 20,
    "pageNumber": 0,
    "query": [
      {
        "index": "es-smart-pricing",
        "keyWord": "",
        "keyWordNotMatch": "",
        "matchType": "all-1",
        "matchFields": [],
        "filters": []
      }
    ]
  }
]
```

Observed date filter:

```json
{
  "fieldName": "ngay_dang_tai_kqlcnt",
  "searchType": "range",
  "from": "YYYY-MM-DDT00:00:00.000Z",
  "to": "YYYY-MM-DDT23:59:59.059Z"
}
```

Verified behavior:

- The real match count is `agg[0].buckets[0].docCount`.
- Normal search pagination is effectively bounded near 10,000 results.
- Deep pagination beyond that returns HTTP 400.
- Daily partitions tested so far remain below the export ceiling; observed peak is approximately 9,000.
- The source document `id` is a UUID and is the planned stable Typesense document ID.

### Export

```text
POST https://muasamcong.mpi.gov.vn/o/egp-portal-winning-bid-data/services/smart/search_prc/export
```

Verified behavior:

- Response JSON is `{"resultList": [...]}`.
- `pageSize=10000` does not cap output at 10,000 rows.
- A sample export returned 25,545 rows in one response.
- Export hard-truncates at exactly 30,000 rows; a known 33,543-row query returned 30,000.
- `pageNumber=1` returns HTTP 400.
- Daily partitioning is therefore mandatory.

The count/export/normalize/import invariant for every successful partition is:

```text
search agg docCount
= export resultList length
= normalized row count
= successful Typesense imports
```

Any mismatch fails closed. This invariant is recorded here only; it is not implemented in Phase 0.

## 8. MSC contracts still requiring discovery

Before Phase 1 implementation, record one executable request/response fixture per source tab and freeze the discovered contract. At minimum, resolve:

- Exact `tab` discriminator for all seven source tabs. Do not assume the labels or `HANG_HOA`/`THUOC_TAN_DUOC` observations cover every tab.
- Exact `type` and `tab` filters required for each source, including whether both are required, optional, or different.
- Exact medicine-only filters, including whether `medicines=["0"]` is required and what values select Generic, biệt dược gốc, and dược liệu.
- Exact `matchFields` for each tab and which fields participate in keyword search.
- Exact `matchType`, `keyWord`, `keyWordNotMatch`, filter operators, array encoding, and empty-value behavior.
- Request pagination and sorting fields accepted by each endpoint; confirm that the export endpoint intentionally rejects `pageNumber=1`.
- Complete response shape per tab: record path, aggregation path, error shape, pagination metadata, and nullability of every canonical export field.
- Whether `agg[0].buckets[0].docCount` remains reliable for zero-result and multi-bucket responses.
- Date boundary semantics, UTC/local-time interpretation, inclusive/exclusive behavior, and whether the observed `.059Z` ending is required or an artifact.
- Exact export request limits, payload limits, timeouts, rate limits, transient-error classes, and safe retry rules.
- UUID uniqueness/stability across source tabs and dates; behavior when the same UUID appears in multiple partitions.
- Per-tab export headers/field names, aliases, numeric formats, date formats, missing-value markers, and Vietnamese Unicode variants.
- Mapping of each official tab to the three logical groups and proof that no out-of-scope service tab is admitted.

Known observations are not a substitute for this discovery record: `type=HANG_HOA` and `tab=HANG_HOA` were observed for generic goods, while `tab=THUOC_TAN_DUOC`, `medicines=["0"]`, and medicine-specific `matchFields` were observed for one medicine request. They must not be generalized to the other five source tabs without evidence.

## 9. Target minimal V1 architecture

```text
MuaSamCong winning-bid API
  -> lightweight crawler_engine MSC adapter
  -> deterministic clean/normalize/validate
  -> one natural daily partition per date × source_tab
  -> 3 versioned Typesense physical collections
  -> atomic logical aliases:
       bidfinder_goods
       bidfinder_medicines
       bidfinder_traditional
  -> FastAPI search repository/compiler
  -> existing static BIDFinder UI
  -> later read-only chatbot using FastAPI search/read APIs
```

### Typesense design

- Use MSC UUID as Typesense document `id`.
- Use three logical collections, not one heterogeneous collection.
- Version physical collection names so a complete reindex can be validated before an atomic alias switch.
- Preserve `data_group`, exact `source_tab`, and exact `source_tab_label` on every document.
- Use idempotent bulk upsert. Re-running a successful partition must not create duplicate documents.
- Keep checkpoint state per `date × source_tab` with status, expected count, export count, normalized count, imported count, contract version, and failure reason. Candidate storage is a small durable control-plane record, not a query collection.
- Refuse a partition when expected count is at least 30,000; do not attempt to recover truncated exports by increasing `pageSize`.
- Refuse a partition when any equality in the count/export/normalize/import invariant fails.
- Preserve each source's original discriminator; group normalization must not erase provenance.

### FastAPI seam

Introduce a procurement search-store boundary in a later phase. It should be the only layer that knows whether data comes from Typesense or a temporary legacy comparison path.

- Keep browser-facing FastAPI routes: `/api/query`, `/api/query-preview`, `/api/autocomplete`, `/api/bulk-query`, `/api/filter-config`, and a reviewed replacement for procurement metadata.
- Preserve standard/full search, rate limits, anonymous access policy, auth gates, result-count labels, sorting, preview, and bulk result limits.
- Preserve existing OR/AND/NOT user search semantics. Compile the existing request model into Typesense queries; do not silently redefine user meaning to fit a Typesense default.
- Use Typesense multi-search for `scope=all` across the three logical collections.
- Keep Typesense host and keys server-side. The browser calls FastAPI only; no Typesense admin key or direct collection endpoint is exposed.
- Keep auth/session/password-reset/feedback/forum routes on their current control-plane path.
- Remove procurement SQL from query endpoints after parity is proven. Do not delete control-plane Postgres access as part of the data-store cutover.

### UI seam

The existing static UI remains the product shell. The later UI change is a data-contract adaptation, not a redesign:

- retain current result-table styling, local column controls, sort controls, preview, full-search entry point, bulk upload/export, autocomplete, analytics hooks, map/chart areas, and auth/forum behavior;
- add a traditional-medicine result surface or an explicitly documented compatibility presentation;
- replace old columns only where MSC supplies a verified equivalent;
- show missing source values as missing, never as fabricated legacy metadata;
- keep all user-facing search semantics and Vietnamese labels stable unless a third group requires a clear new label.

## 10. Recorded design decisions

1. Use source MSC UUID as Typesense document `id`.
2. Use one natural daily partition per source tab.
3. Count with `/search_prc`.
4. Fetch with `/search_prc/export`.
5. Fail closed if expected count is at least 30,000.
6. Fail closed if export count differs from expected count.
7. Use idempotent Typesense bulk upsert.
8. Keep ingestion checkpoint state per `date × source_tab`.
9. Keep each source's exact original discriminator.
10. Use three Typesense collections rather than one heterogeneous collection.
11. Use Typesense multi-search for `scope=all`.
12. Preserve FastAPI as the only browser-facing data API.
13. Do not expose Typesense admin keys to the frontend.
14. Preserve existing OR/AND/NOT user search semantics; build a Typesense query compiler later.
15. Reuse only relevant deterministic clean/normalization helpers from the legacy crawler.
16. Do not carry forward Excel-header inference, Selenium logic, old package reconciliation, or Postgres ETL merely for compatibility.
17. Do not fabricate legacy fields that the new source schema no longer provides.

## 11. Risk register and Phase 1 gates

| Risk | Consequence | Required gate/mitigation |
| --- | --- | --- |
| Undiscovered per-tab request contract | Empty, mixed, or wrong source data | Seven contract fixtures and tab-by-tab approval before crawler code |
| Export truncation at 30,000 | Silent data loss | Daily partitions, preflight count, hard ceiling, fail-closed invariant |
| Count path changes or has multiple aggregation buckets | Incorrect completeness proof | Store raw count evidence and validate aggregation interpretation per tab |
| Date timezone/boundary mismatch | Missing or duplicated days | Confirm official timestamp semantics with boundary fixtures; use one documented timezone rule |
| UUID collision or instability | Upsert overwrites unrelated rows | Verify UUID uniqueness/stability across tabs and partitions before index design |
| Legacy fields absent in MSC | UI/API compatibility lies | Field-by-field source mapping; return null/missing and retire unsupported filters/sorts |
| Three groups forced through two-scope UI | Traditional data becomes hidden or mislabelled | Decide response/UI compatibility contract before endpoint implementation |
| Typesense schema changes mid-index | Failed import or partial cutover | Version physical collections; validate schema and full counts before alias switch |
| OR/AND/NOT semantic drift | Search results change unexpectedly | Golden query corpus comparing old semantics to compiler behavior |
| Control-plane and search storage coupled | Auth/forum outage during search migration | Separate DB control-plane repository from Typesense procurement repository |
| Ingestion checkpoint loss | Repeated work or untracked partial imports | Durable per-partition checkpoint with explicit terminal states and counts |
| Legacy repair assumptions leak into V1 | Silent row fabrication or deletion | No legacy repair calls from MSC adapter; fail closed on validation error |
| Typesense operational failure | Search outage or incomplete cutover | Keep aliases on last known-good collection; rollback is alias switch, not data rewrite |

Phase 1 cannot start implementation until the seven request contracts, field mappings, date semantics, ID behavior, and the three-group API compatibility decision are recorded.

## 12. Validation strategy

Phase 0 validation is documentation/static only:

- confirm branch and baseline commit;
- inspect worktree before and after changes;
- inspect all required crawler, backend, frontend, deployment, CI, and load-test files;
- run harmless documentation checks and repository static checks only;
- do not hit production DB with writes, run crawler/backfill, modify Typesense, deploy, or push.

Future Phase 1 validation must include:

1. Contract fixtures for all seven tabs, including zero-result, one-result, date-boundary, and near-ceiling partitions.
2. Normalization unit tests for each canonical field and every source-tab mapping.
3. Count/export/normalize/import equality tests, with deliberate mismatch tests that fail closed.
4. Duplicate UUID and idempotent-upsert tests.
5. Typesense schema/search/sort/facet tests per collection.
6. Golden API tests for standard search, full search, preview, autocomplete, bulk query, all-scope multi-search, auth gating, rate limiting, and feedback/forum behavior.
7. Browser regression checks for existing two-scope workflows plus traditional-medicine presentation.
8. Staged shadow-read parity and load tests before any production alias switch.

## 13. Rollback strategy

- Before cutover, keep legacy procurement reads available and do not change the browser contract.
- Build and validate a new versioned physical collection set off to the side.
- Switch logical aliases atomically only after all seven sources, partition counts, normalized counts, import counts, and query smoke tests pass.
- Roll back by pointing aliases to the previous known-good physical collections. Do not delete the previous set during the release window.
- If API parity fails, route procurement reads back to the legacy store while keeping auth/session/feedback unchanged.
- If a partition fails validation, leave its checkpoint non-terminal/failed, do not mark it complete, and do not expose a partially accepted collection as current.
- Decommission legacy procurement queries only after an explicit observation window, parity evidence, and a documented recovery point. Control-plane Postgres remains until its separate replacement is approved.

## 14. Phased implementation order

### Phase 0 — complete in this branch

- Audit current crawler, backend, frontend, deployment, and load-test dependencies.
- Record the seven-to-three source/data model.
- Record known MSC behavior and unresolved per-tab contracts.
- Record Typesense, FastAPI, UI, validation, and rollback seams.
- Make no runtime behavior change.

### Phase 1 — contract and fixture discovery

- Capture official request/response fixtures for all seven tabs.
- Freeze exact discriminators, match fields, filters, response paths, field aliases, date/number formats, and error/retry rules.
- Define the normalized V1 schema and Typesense field types from fixtures.

### Phase 2 — isolated crawler/normalizer

- Add a narrow MSC API adapter under the existing crawler area without moving or duplicating the legacy crawler.
- Implement daily `date × source_tab` partitioning, deterministic normalization, validation, and durable checkpoints.
- Test export completeness without importing production data.

### Phase 3 — versioned Typesense indexing

- Create versioned physical collections and the three logical aliases.
- Import only validated partitions with idempotent upsert.
- Prove count/import parity and alias rollback in a non-production environment.

### Phase 4 — FastAPI search seam

- Add server-side Typesense client/repository and query compiler.
- Adapt query, preview, autocomplete, bulk, metadata, and all-scope behavior.
- Keep auth/session/feedback/forum on the Postgres control plane.

### Phase 5 — UI contract adaptation

- Preserve static architecture and styling.
- Add traditional-medicine presentation and update columns/filters/bulk mappings from the verified schema.
- Keep browser calls FastAPI-only.

### Phase 6 — shadow, load, and controlled cutover

- Run parity and load tests using the existing k6 workflows adapted to the new backend contract.
- Observe error rates, latency, Typesense health, and control-plane DB behavior.
- Switch aliases under the rollback plan; do not deploy or push as part of this Phase 0 work.

### Phase 7 — later read-only chatbot

- Add only after search/API contracts are stable.
- Use FastAPI read APIs and existing access policy; no write actions, agents, analytics, or independent data store.
