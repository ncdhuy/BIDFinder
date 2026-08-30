# BIDFinder MSC-to-Typesense Migration Plan

Status: Phase 3A-L live Typesense integration PASS; Phase 3B historical backfill pending.

Baseline reviewed: `refactor-phase-0-7` at `0dcab303bdb4cf23d661b6e53802057705afff49` (`Change UI`, 2026-08-29).

This document records the smallest viable migration path from the current Selenium/Postgres procurement-data path to the MuaSamCong (MSC) winning-bid APIs, a deterministic crawler/normalizer, Typesense, and the existing FastAPI/static-web product. Phases 1A-1C add proof tooling; Phase 2 adds the production MSC crawler core.

## 1. Scope and non-goals

### In scope

- Searchable winning-bid data from the seven HÀNG HÓA source tabs.
- Three logical data groups: `goods`, `medicines`, and `traditional_medicine`.
- Public MSC search-count and paginated completeness validation.
- Versioned Typesense collections with stable logical aliases.
- Adaptation seams for the existing FastAPI routes and static UI.
- A later read-only chatbot that uses the same search/read path.

### Out of scope

- Production crawler implementation, normalization code, Typesense provisioning, or Typesense imports.
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
| `repair_missing_local_files.py` | Reads/updates `daily_manifest` paths and may recover local assets | Obsolete for public-search ingestion |
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
| `goods` | Hàng hóa ngoài thuốc, thiết bị, vật tư y tế | `HANG_HOA` |
| `goods` | Thiết bị, vật tư y tế | `THIET_BI_VAT_TU_Y_TE` |
| `medicines` | Gói thầu thuốc Generic | `THUOC_TAN_DUOC` (`medicines=0`) |
| `medicines` | Gói thầu thuốc biệt dược gốc | `THUOC_TAN_DUOC` (`medicines=1`) |
| `medicines` | Gói thầu thuốc dược liệu | `THUOC_TAN_DUOC` (`medicines=2`) |
| `traditional_medicine` | Dược liệu | `DUOC_LIEU` (`medicine_type=[0,null]`) |
| `traditional_medicine` | Vị thuốc cổ truyền | `VI_THUOC_CO_TRUYEN` (`medicine_type=[0,null]`) |

`source_tab_label` is the exact human-readable label above. `source_tab` preserves the verified MSC discriminator for that source. The full canonical field contract is in [msc-source-schema-v1.md](msc-source-schema-v1.md).

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
- Normal search pagination is bounded by a 10,000-result window.
- A page is safe only when `pageNumber × pageSize < 10000`; deep pagination at or beyond that boundary has returned HTTP 400.
- Phase 1B selected `pageSize=1000`: requests for 100, 500, and 1000 all returned HTTP 200 without clamping on a public full-day probe.
- The source document `id` is a UUID and is the planned stable Typesense document ID.

### Export — historical/manual reference only

```text
POST https://muasamcong.mpi.gov.vn/o/egp-portal-winning-bid-data/services/smart/search_prc/export
```

Verified behavior:

- Response JSON is `{"resultList": [...]}`.
- `pageSize=10000` does not cap output at 10,000 rows.
- A sample export returned 25,545 rows in one response.
- Export hard-truncates at exactly 30,000 rows; a known 33,543-row query returned 30,000.
- `pageNumber=1` returns HTTP 400.
- These findings remain historical reference evidence only. MSC export requires interactive username/password login, reCAPTCHA, Google Authenticator OTP/MFA, and an expiring authenticated session.
- Production ingestion must not automate login, reCAPTCHA, MFA, copied cookies, or a human-authenticated browser session. `/export` is not a production dependency.

The historical count/export/normalize/import invariant was:

```text
search agg docCount
= export resultList length
= normalized row count
= successful Typesense imports
```

Any mismatch fails closed. It is retained as manual/reference evidence and is not a production ingestion contract.

## 8. Historical MSC contract discovery checklist

Phase 1A recorded one executable request/response fixture per source tab and froze the discovered contract. The original checklist was:

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
- Keep checkpoint state per `date × source_tab` with status, expected count, search page count, normalized count, imported count, contract version, and failure reason. Candidate storage is a small durable control-plane record, not a query collection.
- Treat the daily partition as the parent; recursively split only by `ngay_dang_tai_kqlcnt` until every safe leaf is at or below `MAX_SAFE_SEARCH_RESULTS=9500`, then fail closed if time granularity or depth prevents a safe leaf.
- Refuse a partition when any equality in the search-count/page/normalize/import invariant fails.
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
2. Use one natural daily parent per source tab, with adaptive intraday safe leaves when needed.
3. Count with `/search_prc`.
4. Fetch with paginated `/search_prc` only.
5. Keep every safe leaf at or below `MAX_SAFE_SEARCH_RESULTS=9500`; fail closed if a leaf cannot be made safe or any page offset reaches 10,000.
6. Fail closed if the UUID union differs from the full-parent `agg[0].buckets[0].docCount`, or if pre/post parent counts differ.
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
| Search result window near 10,000 | Silent data loss | `MAX_SAFE_SEARCH_RESULTS=9500`, adaptive time leaves, page/count/UUID validation, fail-closed unsplittable overflow |
| Count path changes or has multiple aggregation buckets | Incorrect completeness proof | Store raw count evidence and validate aggregation interpretation per tab |
| Date timezone/boundary mismatch | Missing or duplicated days | Preserve official day bounds; use deterministic one-second sibling overlap and UUID union; keep timezone meaning explicit until separately proven |
| UUID collision or instability | Upsert overwrites unrelated rows | Verify UUID uniqueness/stability across tabs and partitions before index design |
| Legacy fields absent in MSC | UI/API compatibility lies | Field-by-field source mapping; return null/missing and retire unsupported filters/sorts |
| Three groups forced through two-scope UI | Traditional data becomes hidden or mislabelled | Decide response/UI compatibility contract before endpoint implementation |
| Typesense schema changes mid-index | Failed import or partial cutover | Version physical collections; validate schema and full counts before alias switch |
| OR/AND/NOT semantic drift | Search results change unexpectedly | Golden query corpus comparing old semantics to compiler behavior |
| Control-plane and search storage coupled | Auth/forum outage during search migration | Separate DB control-plane repository from Typesense procurement repository |
| Ingestion checkpoint loss | Repeated work or untracked partial imports | Durable per-partition checkpoint with explicit terminal states and counts |
| Legacy repair assumptions leak into V1 | Silent row fabrication or deletion | No legacy repair calls from MSC adapter; fail closed on validation error |
| Typesense operational failure | Search outage or incomplete cutover | Keep aliases on last known-good collection; rollback is alias switch, not data rewrite |

Production crawler implementation cannot start until Phase 1B overflow handling is resolved in addition to the seven request contracts, field mappings, date semantics, ID behavior, and the three-group API compatibility decision.

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
3. Search-count/page/normalize/import equality tests, with deliberate mismatch tests that fail closed.
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
- Test public-search completeness without importing production data.

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

## Phase 1A — contract discovery, fixtures, and schema freeze

Status: complete for seven source-contract discovery and offline fixture infrastructure; not Phase 1 complete. No production crawler, historical backfill, Typesense connection, FastAPI runtime change, frontend change, deployment, database write, or push was performed.

Evidence locations:

- Seven per-source fixtures: `docs/msc-contracts/{goods-general,medical-devices,medicine-generic,medicine-originator,medicine-herbal,herbal-material,traditional-medicine}/`.
- Reproducible read-only probe: `tools/msc_contract_probe.py`.
- Documentation-only collection schema: `docs/msc-typesense-schema-v1.md`.

The official winning-bid-data page's inline Vue definitions resolved the exact source contracts:

| Source | `data_group` | `type` | `tab` | Special filter | `matchFields` |
| --- | --- | --- | --- | --- | --- |
| Hàng hóa ngoài thuốc, thiết bị, vật tư y tế | `goods` | `HANG_HOA` | `HANG_HOA` | none | `danh_muc_hang_hoa`, `ma_hs`, `xuat_xu`, `ma_tbmt`, `ky_ma_hieu`, `nhan_hieu`, `hang_san_xuat` |
| Thiết bị, vật tư y tế | `goods` | `HANG_HOA` | `THIET_BI_VAT_TU_Y_TE` | none | `ten_thiet_bi`, `ma_hs`, `xuat_xu`, `ma_tbmt`, `ky_ma_hieu`, `nhan_hieu`, `hang_san_xuat` |
| Gói thầu thuốc Generic | `medicines` | `HANG_HOA` | `THUOC_TAN_DUOC` | `medicines=["0"]` | `ten_thuoc`, `ten_hoat_chat`, `ma_tbmt` |
| Gói thầu thuốc biệt dược gốc | `medicines` | `HANG_HOA` | `THUOC_TAN_DUOC` | `medicines=["1"]` | `ten_thuoc`, `ten_hoat_chat`, `ma_tbmt` |
| Gói thầu thuốc dược liệu | `medicines` | `HANG_HOA` | `THUOC_TAN_DUOC` | `medicines=["2"]` | `ten_thuoc`, `ten_hoat_chat`, `ma_tbmt` |
| Dược liệu | `traditional_medicine` | `HANG_HOA` | `DUOC_LIEU` | `medicine_type=[0,null]` | `ten_duoc_lieu`, `ten_khoa_hoc`, `ten_san_pham`, `ma_tbmt` |
| Vị thuốc cổ truyền | `traditional_medicine` | `HANG_HOA` | `VI_THUOC_CO_TRUYEN` | `medicine_type=[0,null]` | `ten_duoc_lieu`, `ten_khoa_hoc`, `ten_san_pham`, `ma_tbmt` |

Search responses use `page.content` and count `agg[0].buckets[0].docCount`. The Phase 1B probe paginates public search, validates page metadata, rejects duplicate UUIDs and count mismatches, and retries only transient network/429/5xx failures. Historical export responses use `resultList` only in offline fixture parsing; no export request is made by the probe.

### Phase 1A findings and remaining risks

- Daily parent request bounds remain exactly `T00:00:00.000Z` through `T23:59:59.059Z`; `.059Z` was not changed. Response timestamps are naive strings without timezone markers. The page's helper adds seven hours. Phase 1C proved arbitrary sub-day filtering and uses a one-second sibling overlap because inclusive/exclusive semantics remain unspecified.
- Repeating one goods query returned the same UUID and timestamp. One UUID appeared per committed sample, and sampled UUIDs across seven source tabs are distinct. This is not universal export-wide uniqueness proof.
- Numeric values remain numeric. Quantity maps from `khoiLuongDouble` or `soLuong`; prices map from the verified source price field; fractional `soNhaThauThamDu` makes canonical bidder count `float`; descriptive production-year strings remain nullable rather than coerced.
- Text normalization is limited to future NFC normalization, whitespace collapse, trim, and safe null handling. Legacy Excel inference is excluded.
- Intended collections are `bidfinder_goods`, `bidfinder_medicines`, and `bidfinder_traditional`; no collection was created. High-cardinality values are searchable without unnecessary facets. Raw source dates remain strings until timezone proof supports a new typed field.
- Anonymous export probing is not part of Phase 1B. Interactive MSC export requires username/password, reCAPTCHA, Google Authenticator OTP/MFA, and an expiring session; it remains manual/reference-only and is not a production prerequisite.

### Three-group FastAPI compatibility decision

This is a documentation decision only; endpoints remain unchanged in Phase 1A.

Request vocabulary for the future API:

- `all`: default; searches all three logical groups.
- `goods`: goods collection only.
- `medicines`: medicines collection only.
- `traditional`: traditional-medicine collection only.

Keep accepting legacy `medicine` as a temporary alias for `medicines`; keep `goods` and `all` unchanged. Do not expose MSC tab enums as browser scope values. The existing browser-facing FastAPI boundary remains the only search boundary.

For response compatibility, retain current `df1` (medicine) and `df2` (goods) objects with their current pagination/count shape for existing `all`, `medicine`, and `goods` callers. Add a canonical `groups` object keyed by `medicines`, `goods`, and `traditional`; for `all`, populate all applicable groups, while retaining `df1`/`df2` as transitional aliases. A `traditional` scope returns its group under `groups.traditional` and may expose a same-named transitional top-level alias; no traditional data is forced into `df1` or `df2`.

MSC does not supply legacy package joins, `qd_display`, version/approval/expiry/validity fields, duplicate-warning flags, goods `Search blob`, old medicine filter classifications, or Excel-only columns. Future responses must omit or return null for these fields and retire unsupported filters/sorts. Verified-but-optional MSC fields, including medical-device model/registration, shelf life, bidder count, location, and production year, remain nullable during transition. Auth, sessions, feedback/forum state, quotas, and control-plane Postgres behavior remain separate and unchanged.

Phase 1A and Phase 1B did not approve production ingestion. Phase 1C provided
the approved search-retrieval strategy for overflow parents; Phase 2 now
promotes that strategy through the dedicated production MSC engine described
below.

## Phase 1B — Search-only ingestion proof and contract finalization

Status: `PARTIAL` as historical evidence. Public search pagination and field parity pass for seven controlled nonzero daily partitions. Phase 1C adds the secondary time-partition strategy for overflow parents.

### Authoritative production path

```text
MSC /search_prc
  -> source tab
  -> official day parent range and agg[0].buckets[0].docCount
  -> adaptive intraday safe leaves when parent exceeds MAX_SAFE_SEARCH_RESULTS
  -> paginate each safe leaf's page.content
  -> UUID union, pre/post full-parent count validation
  -> normalize
  -> later Typesense upsert
```

`/search_prc/export` is an authenticated manual/reference endpoint only. It requires interactive username/password login, reCAPTCHA, Google Authenticator OTP/MFA, and a session that expires after inactivity. Production must not automate login, bypass reCAPTCHA, automate MFA, copy browser cookies, or depend on a human-authenticated browser session. Historical export findings and fixtures remain only for occasional human validation and offline parser tests.

### Live evidence

Sanitized evidence is committed in [search-only-validation.json](msc-contracts/search-only-validation.json). Requests used no credentials, cookies, or authenticated session. The probe used empty `keyWord` with each verified source contract and the official daily range.

Page-size probe on `goods-general`, 2026-08-28:

| Requested | HTTP | Returned `pageSize` | `page.content` | `agg docCount` | Qualitative latency |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 200 | 100 | 100 | 16248 | 310 ms |
| 500 | 200 | 500 | 500 | 16248 | 287 ms |
| 1000 | 200 | 1000 | 1000 | 16248 | 462 ms |

V1 selects `pageSize=1000`: server accepted it without clamping, while keeping request count low enough for controlled proof. Reliability still depends on the safe count gate, not page size alone.

The confirmed operational result window is 10,000 records. A page is admissible only when `pageNumber × pageSize < 10000`; deep pagination at or beyond that boundary has returned HTTP 400. Phase 1B fetched only offsets 0 through 9000 and did not issue a boundary-crossing request.

`MAX_SAFE_SEARCH_RESULTS=9500` is the selected conservative leaf threshold. It is below the 10,000-record result window and leaves headroom for safe page offsets; 9,500 is safe at page size 1,000 because the last offset is 9,000. A safe leaf with `expected_count <= 9500` may be paginated; a leaf above it fails closed. The daily partition is the natural parent, not the required search-window-sized leaf.

### Seven-source pagination result

All rows below came from public `/search_prc`; all requested pages returned HTTP 200, page numbers were zero-based and correct, server `totalElements` matched `docCount`, UUIDs were unique, and no page overlap was found.

| Source | `data_group` | Exact `tab` | Date | `docCount` | Pages / lengths | Collected | Unique UUIDs | Overlap | Repeat page 0 | Result |
| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| Hàng hóa ngoài thuốc, thiết bị, vật tư y tế | `goods` | `HANG_HOA` | 2026-08-25 | 9257 | 10 / 1000×9 + 257 | 9257 | 9257 | 0 | same | PASS |
| Thiết bị, vật tư y tế | `goods` | `THIET_BI_VAT_TU_Y_TE` | 2026-08-28 | 1727 | 2 / 1000 + 727 | 1727 | 1727 | 0 | same | PASS |
| Gói thầu thuốc Generic | `medicines` | `THUOC_TAN_DUOC`, `medicines=0` | 2026-08-28 | 125 | 1 / 125 | 125 | 125 | 0 | same | PASS |
| Gói thầu thuốc biệt dược gốc | `medicines` | `THUOC_TAN_DUOC`, `medicines=1` | 2026-08-27 | 17 | 1 / 17 | 17 | 17 | 0 | same | PASS |
| Gói thầu thuốc dược liệu | `medicines` | `THUOC_TAN_DUOC`, `medicines=2` | 2026-08-28 | 30 | 1 / 30 | 30 | 30 | 0 | same | PASS |
| Dược liệu | `traditional_medicine` | `DUOC_LIEU`, `medicine_type=[0,null]` | 2026-08-22 | 25 | 1 / 25 | 25 | 25 | 0 | same | PASS |
| Vị thuốc cổ truyền | `traditional_medicine` | `VI_THUOC_CO_TRUYEN`, `medicine_type=[0,null]` | 2026-08-27 | 62 | 1 / 62 | 62 | 62 | 0 | same | PASS |

Completeness invariant for this phase:

```text
agg[0].buckets[0].docCount
= collected page.content row count
= unique UUID count
```

Normalization and Typesense import counts are intentionally not tested or implemented in Phase 1B.

### Public-search field-parity gate

The matrix below uses only the full live `page.content` unions recorded in the evidence fixture. It does not infer availability from Excel or export data.

Status meanings:

- `AVAILABLE_IN_SEARCH`: direct field observed and required for the canonical identity or provenance mapping.
- `OPTIONAL_AND_AVAILABLE_WHEN_PRESENT`: direct field observed in public search; individual records may omit it or return an empty value.
- `NOT_AVAILABLE_IN_SEARCH`: no public-search field supports the canonical field.
- `UNKNOWN`: a similarly named field was observed, but its canonical meaning is not frozen by the verified mapping.

Common provenance:

| Canonical field | Goods | Medicines | Traditional | Basis |
| --- | --- | --- | --- | --- |
| `id` | AVAILABLE_IN_SEARCH | AVAILABLE_IN_SEARCH | AVAILABLE_IN_SEARCH | Direct `id` string |
| `data_group` | AVAILABLE_IN_SEARCH* | AVAILABLE_IN_SEARCH* | AVAILABLE_IN_SEARCH* | Derived from verified contract |
| `source_tab` | AVAILABLE_IN_SEARCH* | AVAILABLE_IN_SEARCH* | AVAILABLE_IN_SEARCH* | Derived from verified `tab` filter |
| `source_tab_label` | AVAILABLE_IN_SEARCH* | AVAILABLE_IN_SEARCH* | AVAILABLE_IN_SEARCH* | Verified contract label |
| `partition_date` | AVAILABLE_IN_SEARCH* | AVAILABLE_IN_SEARCH* | AVAILABLE_IN_SEARCH* | Derived from requested daily range |

`*` These four values are deterministic ingestion provenance, not fabricated source-record fields.

Goods canonical fields:

| Canonical field | Hàng hóa ngoài thuốc | Thiết bị, vật tư y tế |
| --- | --- | --- |
| `item_name`, `unit`, `quantity`, `country_of_origin`, `hs_code`, `model_mark`, `brand`, `production_year`, `manufacturer`, `technical_specification`, `winning_unit_price`, `winning_bidder_id`, `winning_bidder_name`, `bid_invitation_code`, `procuring_entity_id`, `procuring_entity_name`, `selection_method`, `result_posted_at`, `decision_number`, `decision_issued_at`, `bidder_count`, `location` | OPTIONAL_AND_AVAILABLE_WHEN_PRESENT | OPTIONAL_AND_AVAILABLE_WHEN_PRESENT |
| `model` | UNKNOWN; no verified goods-general canonical mapping | OPTIONAL_AND_AVAILABLE_WHEN_PRESENT (`chungLoai`) |
| `registration_or_import_permit_number` | UNKNOWN; no verified goods-general canonical mapping | OPTIONAL_AND_AVAILABLE_WHEN_PRESENT (`soLuuHanh`) |

Medicine canonical fields:

| Canonical fields | Generic | Biệt dược gốc | Dược liệu |
| --- | --- | --- | --- |
| `medicine_name`, `active_ingredient_or_herbal_component`, `strength`, `marketing_authorization_or_import_permit`, `route_of_administration`, `dosage_form`, `shelf_life`, `manufacturer`, `production_country`, `packaging`, `unit`, `quantity`, `winning_unit_price`, `winning_bidder_id`, `winning_bidder_name`, `medicine_group`, `bid_invitation_code`, `procuring_entity_id`, `procuring_entity_name`, `selection_method`, `result_posted_at`, `decision_number`, `decision_issued_at`, `bidder_count`, `location` | OPTIONAL_AND_AVAILABLE_WHEN_PRESENT | OPTIONAL_AND_AVAILABLE_WHEN_PRESENT | OPTIONAL_AND_AVAILABLE_WHEN_PRESENT |

Traditional-medicine canonical fields:

| Canonical fields | Dược liệu | Vị thuốc cổ truyền |
| --- | --- | --- |
| `item_name`, `used_part`, `scientific_name`, `origin`, `processing_method`, `registration_or_import_permit_number`, `manufacturer`, `production_country`, `packaging`, `unit`, `quantity`, `winning_unit_price`, `winning_bidder_id`, `winning_bidder_name`, `technical_group`, `bid_invitation_code`, `procuring_entity_id`, `procuring_entity_name`, `selection_method`, `result_posted_at`, `decision_number`, `decision_issued_at`, `location` | OPTIONAL_AND_AVAILABLE_WHEN_PRESENT | OPTIONAL_AND_AVAILABLE_WHEN_PRESENT |
| `bidder_count` | UNKNOWN; `soNhaThauThamDu` absent from the selected full Dược liệu partition | OPTIONAL_AND_AVAILABLE_WHEN_PRESENT (`soNhaThauThamDu`) |

`herbal-material.bidder_count` was absent from the selected full partition, so its status is `UNKNOWN` until a public-search record for that tab supplies the mapped field. It remains optional and is not a production-required field.

No mapped canonical field was classified `NOT_AVAILABLE_IN_SEARCH`. `model` and `registration_or_import_permit_number` for general goods remain `UNKNOWN`, not silently retained as required fields. The current Typesense design does not require either field. Source-only fields such as `decisions`, `medicines`, `medicineType`, and `tenSanPham` are not fabricated canonical fields.

Observed source JSON types across the full controlled partitions are recorded per canonical mapping in the evidence fixture: `id` is a string; quantity, price, and bidder count are JSON numbers; bidder IDs/names and `diaDiem` are arrays; date fields are strings without an explicit timezone; `namSanXuat` is a string; nullable/omitted fields remain nullable. No numeric-looking string is coerced without a documented normalization rule.

### Schema and UI impact

The three logical collections remain `bidfinder_goods`, `bidfinder_medicines`, and `bidfinder_traditional`. `id` remains the only required source identity field; canonical data fields stay optional because public records can omit them. No Typesense server call or schema creation was made. The V1 schema document now treats public search as the production source and marks general-goods device model/registration concepts as unknown/optional rather than required.

Phase 1B makes no UI runtime change. Future UI work must not expose general-goods device model/registration filters as guaranteed fields, and must retire or mark missing legacy package, approval, validity, and Excel-only columns. Traditional-medicine results, advanced filters, result columns, and bulk-search mappings require the later UI contract adaptation; none is implemented here.

### Phase 1B gate

Public search proves all seven verified tabs, safe representative pagination, exact counts, UUID uniqueness/overlap, and availability of all production-required canonical mappings without authenticated MSC state. Phase 1B status remains historical `PARTIAL`; Phase 1C closes its overflow retrieval gate below without starting production ingestion.

## Phase 1C — Overflow time-partition proof

Status: `PASS`. This phase proves public retrieval for overflowing daily parents using only the existing `ngay_dang_tai_kqlcnt` range filter. It adds no crawler, database, Typesense, FastAPI, frontend, deployment, authentication, or `/export` behavior.

### Approved retrieval strategy

The daily source partition remains the natural parent:

```text
MSC public /search_prc
  -> source tab and official full-day parent range
  -> pre-count agg[0].buckets[0].docCount
  -> if count <= MAX_SAFE_SEARCH_RESULTS, fetch one safe leaf
  -> otherwise split time range at midpoint and recurse
  -> count every child; fail on unexplained child deficit
  -> fetch every safe leaf with pageSize=1000
  -> reject page/within-leaf UUID duplicates and metadata drift
  -> union records by UUID; accept only identical cross-leaf overlap
  -> require unique UUID union == parent pre-count
  -> post-count parent again before completion
  -> later normalize and upsert to Typesense
```

`MAX_SAFE_SEARCH_RESULTS=9500` remains conservative: the confirmed public search window is 10,000 records, and a 1,000-row leaf's final offset is 9,000. The threshold is generic because it applies to every safe search interval, not only a day.

Sibling intervals intentionally overlap by one second: `left=[start, midpoint+1s]`, `right=[midpoint, end]`. This protects records at unknown inclusive/exclusive boundaries and possible millisecond precision. Overlap is never counted as missing or failure by itself; same UUID with different content is a source consistency failure. An interval that cannot make positive progress because of maximum depth, minimum span, or overlap granularity fails closed. No province, brand, bidder, TBMT, or other business-field fallback is approved.

### Live validation

The complete sanitized evidence is [partition-evidence.json](msc-contracts/partition-evidence.json). All rows below used verified `goods-general` / `HANG_HOA`, anonymous public `/search_prc`, the official day bounds, page size 1,000, and post-count validation.

| Date | Parent `agg.docCount` | Safe leaves | Leaf counts | Pages | Raw fetched | Unique UUIDs | Pre=Post | Result |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- |
| 2026-08-28 | 16,248 | 4 | 3,608; 2,676; 7,267; 2,697 | 18 | 16,248 | 16,248 | 16,248=16,248 | PASS |
| 2026-08-27 | 13,971 | 3 | 4,045; 7,302; 2,624 | 16 | 13,971 | 13,971 | 13,971=13,971 | PASS |
| 2026-08-26 | 15,605 | 3 | 5,628; 7,951; 2,026 | 17 | 15,605 | 15,605 | 15,605=15,605 | PASS |
| 2026-08-21 | 10,251 | 2 | 2,572; 7,679 | 11 | 10,251 | 10,251 | 10,251=10,251 | PASS |

Child-count sums equaled parent counts in all four live runs; overlap surplus was zero, and no boundary duplicate was needed at planner-selected split points. A deliberate boundary probe at `2026-08-28T16:00:53` returned two same-content UUID duplicates across the one-second overlap; raw count was 16,250 and UUID union was 16,248. No same-UUID content conflict occurred.

The two-range arbitrary intraday proof for 2026-08-28 also passed: `[00:00:00.000Z,16:00:00.000Z]` counted/fetched 8,993 and `[16:00:00.000Z,23:59:59.059Z]` counted/fetched 7,255, both HTTP 200, with union 16,248. The first range's maximum observed timestamp was `15:59:51`; the second range's minimum was `16:00:53` and contained two records near the boundary.

The safe 9,257-row normal day 2026-08-25 remained one leaf, fetched 9,257 rows in 10 pages, and passed 9,257 pre-count, post-count, and unique UUID checks.

## Phase 2 — Production MSC ingestion engine core

Status: `PASS`: the production engine and its actual MSC client transport pass
the live smoke gates. The MSC endpoint's default finite-field DHE path can fail
with `DH_KEY_TOO_SMALL`; the MSC-scoped verified context selects ECDHE instead.
The isolated
`crawler_engine/msc/` package promotes the Phase 1C retrieval algorithm into a
sequential production crawler core:

```text
public /search_prc
  -> verified source contract and official date parent
  -> pre-count and adaptive time leaves
  -> bounded page.content pagination
  -> page metadata and UUID validation
  -> identical-overlap UUID union
  -> parent pre/post parity
  -> deterministic canonical normalization
  -> pluggable sink
  -> SQLite checkpoint completion
```

Phase 2 has no Typesense sink, application/Postgres dependency, Selenium,
authentication, `/export` call, historical backfill, or FastAPI/frontend change.
The default validation sink is in-memory; the optional JSONL sink is local
staging only. See [msc-ingestion-runbook.md](msc-ingestion-runbook.md) for
operator usage, TLS troubleshooting, and failure handling. Phase 2 uses
`ssl.CERT_REQUIRED`, hostname verification, TLS 1.2+, and normal OpenSSL
security level; it does not use `verify=False`, `CERT_NONE`, or a security-level
downgrade.

### Mutable/current partition policy

The production engine counts the full parent as `pre_count`, fetches and unions all safe leaves, then counts the same parent as `post_count`. Completion requires `pre_count == post_count == unique_union_count` before the sink can complete the checkpoint. A count change must not publish or upsert a partial partition as complete; the failed checkpoint can be retried later and eventually quarantined if it remains unstable. Historical closed days should normally be stable.

Production daily synchronization should not declare the actively changing current source day complete. The Phase 2 engine distinguishes closed historical partitions from current/open partitions; current-day ingestion requires explicit opt-in and ends in `VALIDATED`, never permanent `COMPLETED`. This phase does not invent a cron time or implement retry scheduling.

`/search_prc/export` remains non-production because it requires interactive authentication, reCAPTCHA, MFA, and expiring session state. The Phase 1C helper and probe remain developer-only, pure/read-only validation infrastructure. Phase 2 production crawler implementation is now present, but no Typesense integration or historical import was started here.

### Phase 3A — Typesense data-plane integration and controlled indexing proof

Phase 3A adds the first crawler-to-Typesense path without changing FastAPI,
the frontend, production routing, or Postgres procurement reads. The runtime
promotes the frozen three-collection schemas from
[`msc-typesense-schema-v1.md`](msc-typesense-schema-v1.md), uses versioned
physical collections, and keeps stable logical aliases for a later cutover.

The operator workflow is explicit:

```text
create-generation -> controlled crawl to physical generation
-> validate schemas/counts/searches -> activate aliases explicitly
```

The Typesense sink uses sequential, deterministic NDJSON batches with
`documents/import?action=upsert`. It parses every import response line and
requires one successful result per attempted document; HTTP 200 alone never
completes a partition. A failed or partial batch remains retryable through the
stable MSC UUID.

Checkpoint identity is now `source_key × partition_date × sink_target`.
Existing Phase 2 state is preserved as `validation-jsonl`; Typesense writes
use `typesense:<generation>`. This prevents a completion in one destination
generation from skipping the same partition in another.

Phase 3A is limited to a small controlled proof covering all seven MSC source
contracts, with the known 2026-08-28 goods overflow day included when local
resources permit. It does not start the 2023-to-present backfill, change
FastAPI search behavior, expose Typesense to the browser, or activate aliases
for user traffic. See [typesense-data-plane-runbook.md](typesense-data-plane-runbook.md).

### Phase 3A-L live gate — 2026-08-30

Status: `PASS` against a real disposable Typesense `30.2` server running from
the official WSL2 Linux binary. The run used generation
`live_gate_20260830g`, a dedicated SQLite checkpoint database, public MSC
`/search_prc`, and no Postgres/Neon connection.

| Proof | Result |
| --- | --- |
| Seven source partitions | 27,491 documents; every `pre_count`, `post_count`, unique source count, normalized count, and Typesense accepted count matched; 61 import batches; 0 rejects |
| Overflow `goods_general / 2026-08-28` | 16,248 pre/post/unique/normalized/accepted; 4 adaptive leaves; 26 MSC page requests; 33 Typesense batches; 0 rejects; `COMPLETED` checkpoint |
| Physical count parity | `goods=27,232`, `medicines=172`, `traditional_medicine=87`; each equaled its expected UUID union |
| Idempotency/checkpoints | Forced same-generation upsert preserved counts and sample IDs; next run skipped; generation B did not skip; old `validation-jsonl` state did not suppress Typesense ingestion |
| Search/filter/sort/multi-search | All configured smoke checks passed; all three groups returned from one `/multi_search` request; ascending/descending price order verified programmatically |
| Alias lifecycle | A activated, goods temporarily pointed to B, then rolled back to A; searches worked before and after rollback |
| Partial import | Real fixture returned HTTP 200 with 1 accepted and 1 rejected line; parser returned `TYPESENSE_PARTIAL_IMPORT`; production sink rejected invalid canonical input fail-closed and left checkpoint `RUNNING` |

Detailed redacted evidence is in
[`typesense-integration-report.json`](../typesense-integration-report.json).
Development observations: 500-document batches, 5,664 accepted documents/sec
over the main import window, 51.20 ms mean / 51.07 ms median batch latency,
15.07 ms multi-search latency, and 82.413 seconds total gate time. These are
disposable development measurements, not production capacity guarantees.

Phase 3B-S sizing is now `PASS`; the full historical backfill and application
cutover remain explicitly pending. No historical backfill or application
cutover was performed.

## Phase 3B-R — historical backfill readiness

Phase 3B-R prepares, but does not start, the historical bootstrap. The
readiness range used for the first plan was the explicitly closed Vietnam
calendar range `2023-02-01` through `2026-08-29`; the active day was excluded.
The read-only `/search_prc` aggregation preflight made seven requests and did
not paginate records:

| Source | Group | `agg.docCount` |
| --- | --- | ---: |
| `goods_general` | goods | 8,219,252 |
| `medical_devices` | goods | 964,685 |
| `medicine_generic` | medicines | 494,698 |
| `medicine_originator` | medicines | 55,239 |
| `medicine_herbal` | medicines | 35,489 |
| `herbal_material` | traditional_medicine | 9,554 |
| `traditional_medicine` | traditional_medicine | 22,468 |
| **Total** |  | **9,801,385** |

Group totals are `goods=9,183,937`, `medicines=585,426`, and
`traditional_medicine=32,022`. These are source aggregation counts, not a
Typesense count and not a completed-backfill claim.

`crawler_engine.msc.backfill` provides the durable plan/report/audit layer.
`backfill --plan-only` is the only preparation path: it requires explicit
`--from`, `--to`, `--generation`, and `--checkpoint`, performs the seven count
requests, and writes a manifest. The manifest fingerprints all selected
source contracts, canonical mappings, and Typesense schemas. A changed frozen
contract or schema rejects an old manifest.

The capacity sample used the seven verified search-response fixtures (one
document per source). It sampled 7 canonical documents: goods 2, medicines 3,
traditional medicine 2. Average canonical bytes were 1,160, 1,211, and 1,141;
average searchable/filterable/sortable bytes were 771, 856.67, and 819. The
overall projection is approximately 11.40 GB canonical raw data and 7.61 GB
indexed fields. The official 2x–3x keyword-search RAM rule gives an estimated
15.22–22.83 GB RAM range. A separate 50% operational disk margin gives
approximately 17.10 GB raw-data working space. These are estimates, not
guarantees; a larger bounded live sample and disposable empirical Typesense
run should precede final provisioning.

The dedicated runner traverses `date ascending -> source registry order`,
sequentially. It wraps the existing partition engine and Typesense sink,
uses `typesense:<generation>` checkpoint identity, writes only physical
collections, and never activates aliases. Actual execution requires a
manifest, explicit `--max-partitions`, and `--acknowledge-readiness`; plan-only
has no Typesense writes. Ctrl+C leaves the active checkpoint recoverable and
atomically marks the report `INTERRUPTED`. V1 stops on the first failed or
quarantined partition; transient Typesense/source failures remain resumable.

The final audit compares each source broad aggregation count with the sum of
completed daily parent counts, checks physical Typesense counts against a
disk-backed SQLite UUID provenance table, and fails on conflicting UUID
provenance/content. Alias activation remains a separate gate after coverage,
count parity, deterministic sample parity, and search benchmark pass.

See [`historical-backfill-runbook.md`](historical-backfill-runbook.md) for
operator controls, capacity safety, backup, monitoring, and recovery.

## Phase 3B-S — empirical Typesense sizing — 2026-08-30

Status: `PASS`. A fresh disposable Typesense `30.2` generation indexed
500,013 real canonical documents through the existing MSC adaptive partition,
pagination-validation, canonical-normalization, checkpoint, UUID-audit, and
`TypesenseSink` path. The run used deterministic multi-year date anchors plus
a daily fallback for sparse contracts; all seven source contracts contributed
records from 2023, 2024, 2025, and 2026. It used 500-document Typesense
batches and a one-second MSC request delay.

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

Milestone OS RSS deltas were 200,744,960 B at 55,741 documents,
246,554,624 B at 100,467, 436,113,408 B at 253,253, and 561,414,144 B at
500,013. `/data` deltas were 117,593,620 B, 220,767,449 B, 564,214,374 B,
and 1,111,889,208 B respectively. Restarting the same data directory restored
all counts: `goods=426,843`, `medicines=55,347`, and
`traditional_medicine=17,823`; the expected UUID union equaled the actual
physical collection counts and all 1,569 batches had zero rejects.

The largest-sample empirical projection for the current 9,801,385-document
dataset is 11.01 GB steady-state process RSS and 21.80 GB Typesense data
directory. Regression gives 9.52 GB RSS and 21.85 GB data directory. The
analytical comparison is 14.86–22.29 GB from the actual sample's indexed input
at 2x–3x (the earlier fixture estimate was 15.22–22.83 GB). Growth projections are 13.21/26.15 GB at +20% and 16.51/32.69 GB
at +50% for RAM/data directory. Therefore 32 GB/node passes the 70% target
with projected utilization of 32.0%.

Recommended starting target is Typesense Cloud HA, three nodes, 32 GB RAM and
8 vCPU per node, with at least 200 GB provider disk allocation per node.
Self-hosted remains valid as three Typesense `30.2` nodes with the same RAM,
CPU, and persistent SSD. Keep 50% disk free before creating a new generation,
warn below 35%, and block below 20%; do not automatically delete rollback
generations. Cloud remains preferred for managed HA, node replacement,
upgrades, and backups.

The largest indexed-field contributions were goods
`winning_bidder_name` (3.72%), `source_tab_label` (3.62%),
`technical_specification` (3.43%), and `procuring_entity_name` (3.41%), plus
medicines active ingredient (3.52%) and authorization/permit (3.29%). No
field is removed based on this recommendation-only review.

Observed active ingestion was 3,586 documents/second at 500-document batches;
the order-of-magnitude full run is about 51,142 MSC requests and 19,603
Typesense batches, excluding pacing pauses, retries, and source availability.
Keep the one-second MSC delay and batch size 500; add Typesense write
throttling only if production read-during-write monitoring shows material
latency degradation. Full-backfill authorization still requires a new
physical generation, regenerated closed-range manifest, capacity/backups
approval, final source/UUID/count/search audits, and a separate alias/cutover
approval.

Detailed evidence is in
[`typesense-sizing-report.json`](../typesense-sizing-report.json) and
[`typesense-sizing-report.md`](../typesense-sizing-report.md). The disposable
generation was stopped after the experiment; no FastAPI/UI change, alias
activation, full historical backfill, or Neon/Postgres write occurred.
