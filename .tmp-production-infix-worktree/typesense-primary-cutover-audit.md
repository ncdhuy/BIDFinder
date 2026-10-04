# Phase 4C Typesense Primary Cutover Audit

- Status: **PASS**
- Branch: `refactor-msc-typesense-v1`
- Starting HEAD: `3d131d08ba6e8be49576ca57262dc7f186fa77d6`
- Serving generation: `serving_v1_20260901`
- Initial worktree: clean

## Cutover and serving state

Typesense is the procurement-search primary. Postgres remains available for control-plane functionality and as an infrastructure-only, degraded fallback. The final default is `typesense`; aliases remain inactive and exactly one full serving generation is live.

| Metric | Result |
|---|---|
| Backend before → after | `postgres` → `typesense` |
| Fallback | Enabled; `SHADOW_INFRA_ERROR` only |
| Fallback telemetry | `DEGRADED_POSTGRES_FALLBACK` |
| Typesense health | PASS |
| Live documents | 10,211,267 |
| Aliases | Intentionally inactive |
| Physical generations | 1 |

## Three-group, seven-subtype UI

The UI exposes three top-level groups and subtype checkboxes within each group. `/api/search-contract` is loaded at runtime and drives search fields, filters, sorts, and autocomplete. Requests carry canonical application-level parameters only; frontend code does not emit `query_by`, `filter_by`, or `sort_by`.

| Group | Subtypes | Live documents |
|---|---|---:|
| Hàng hóa | goods_general; medical_devices | 9,593,796 |
| Thuốc | medicine_generic; medicine_originator; medicine_herbal | 585,449 |
| Dược liệu / Vị thuốc cổ truyền | herbal_material; traditional_medicine | 32,022 |

## Search-contract completeness

The table below is generated from `typesense-search-contract.json`. `primary+detail` means a field appears in the useful default result columns and the expandable row detail; `detail` means it remains accessible in expandable detail. `not-approved` is intentional: the Phase 4B contract does not approve that capability for the field, so no control is rendered.

| Group | Contract field | Search | Filter | Sort | Autocomplete | Display |
|---|---|---|---|---|---|---|
| Hàng hóa | `id` | not-approved | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `data_group` | not-approved | exposed | not-approved | not-approved | detail |
| Hàng hóa | `source_tab` | not-approved | exposed | not-approved | not-approved | detail |
| Hàng hóa | `source_tab_label` | not-approved | exposed | not-approved | not-approved | detail |
| Hàng hóa | `partition_date` | not-approved | exposed | exposed | not-approved | primary+detail |
| Hàng hóa | `item_name` | exposed | not-approved | not-approved | exposed | primary+detail |
| Hàng hóa | `unit` | exposed | exposed | not-approved | not-approved | primary+detail |
| Hàng hóa | `quantity` | not-approved | exposed | exposed | not-approved | primary+detail |
| Hàng hóa | `country_of_origin` | exposed | exposed | not-approved | not-approved | detail |
| Hàng hóa | `hs_code` | exposed | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `model_mark` | exposed | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `brand` | exposed | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `production_year` | not-approved | exposed | exposed | not-approved | detail |
| Hàng hóa | `manufacturer` | exposed | not-approved | not-approved | exposed | detail |
| Hàng hóa | `technical_specification` | exposed | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `model` | exposed | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `registration_or_import_permit_number` | exposed | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `winning_unit_price` | not-approved | exposed | exposed | not-approved | primary+detail |
| Hàng hóa | `winning_bidder_id` | not-approved | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `winning_bidder_name` | exposed | not-approved | not-approved | exposed | primary+detail |
| Hàng hóa | `bid_invitation_code` | exposed | not-approved | not-approved | exposed | primary+detail |
| Hàng hóa | `procuring_entity_id` | not-approved | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `procuring_entity_name` | exposed | not-approved | not-approved | exposed | primary+detail |
| Hàng hóa | `selection_method` | exposed | exposed | not-approved | not-approved | detail |
| Hàng hóa | `result_posted_at` | not-approved | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `decision_number` | not-approved | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `decision_issued_at` | not-approved | not-approved | not-approved | not-approved | detail |
| Hàng hóa | `bidder_count` | not-approved | exposed | exposed | not-approved | detail |
| Hàng hóa | `location` | not-approved | not-approved | not-approved | not-approved | detail |
| Thuốc | `id` | not-approved | not-approved | not-approved | not-approved | detail |
| Thuốc | `data_group` | not-approved | exposed | not-approved | not-approved | detail |
| Thuốc | `source_tab` | not-approved | exposed | not-approved | not-approved | detail |
| Thuốc | `source_tab_label` | not-approved | exposed | not-approved | not-approved | detail |
| Thuốc | `partition_date` | not-approved | exposed | exposed | not-approved | primary+detail |
| Thuốc | `medicine_name` | exposed | not-approved | not-approved | exposed | primary+detail |
| Thuốc | `active_ingredient_or_herbal_component` | exposed | not-approved | not-approved | exposed | primary+detail |
| Thuốc | `strength` | exposed | not-approved | not-approved | not-approved | primary+detail |
| Thuốc | `marketing_authorization_or_import_permit` | exposed | not-approved | not-approved | not-approved | detail |
| Thuốc | `route_of_administration` | exposed | exposed | not-approved | not-approved | detail |
| Thuốc | `dosage_form` | exposed | exposed | not-approved | not-approved | primary+detail |
| Thuốc | `shelf_life` | exposed | not-approved | not-approved | not-approved | detail |
| Thuốc | `manufacturer` | exposed | not-approved | not-approved | exposed | primary+detail |
| Thuốc | `production_country` | exposed | exposed | not-approved | not-approved | detail |
| Thuốc | `packaging` | exposed | not-approved | not-approved | not-approved | detail |
| Thuốc | `unit` | exposed | exposed | not-approved | not-approved | detail |
| Thuốc | `quantity` | not-approved | exposed | exposed | not-approved | primary+detail |
| Thuốc | `winning_unit_price` | not-approved | exposed | exposed | not-approved | primary+detail |
| Thuốc | `winning_bidder_id` | not-approved | not-approved | not-approved | not-approved | detail |
| Thuốc | `winning_bidder_name` | exposed | not-approved | not-approved | exposed | primary+detail |
| Thuốc | `medicine_group` | exposed | exposed | not-approved | not-approved | detail |
| Thuốc | `bid_invitation_code` | exposed | not-approved | not-approved | exposed | primary+detail |
| Thuốc | `procuring_entity_id` | not-approved | not-approved | not-approved | not-approved | detail |
| Thuốc | `procuring_entity_name` | exposed | not-approved | not-approved | exposed | detail |
| Thuốc | `selection_method` | exposed | exposed | not-approved | not-approved | detail |
| Thuốc | `result_posted_at` | not-approved | not-approved | not-approved | not-approved | detail |
| Thuốc | `decision_number` | not-approved | not-approved | not-approved | not-approved | detail |
| Thuốc | `decision_issued_at` | not-approved | not-approved | not-approved | not-approved | detail |
| Thuốc | `bidder_count` | not-approved | exposed | exposed | not-approved | detail |
| Thuốc | `location` | not-approved | not-approved | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `id` | not-approved | not-approved | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `data_group` | not-approved | exposed | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `source_tab` | not-approved | exposed | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `source_tab_label` | not-approved | exposed | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `partition_date` | not-approved | exposed | exposed | not-approved | primary+detail |
| Dược liệu / Vị thuốc cổ truyền | `item_name` | exposed | not-approved | not-approved | exposed | primary+detail |
| Dược liệu / Vị thuốc cổ truyền | `used_part` | exposed | not-approved | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `scientific_name` | exposed | not-approved | not-approved | exposed | primary+detail |
| Dược liệu / Vị thuốc cổ truyền | `origin` | exposed | exposed | not-approved | not-approved | primary+detail |
| Dược liệu / Vị thuốc cổ truyền | `processing_method` | exposed | not-approved | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `registration_or_import_permit_number` | exposed | not-approved | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `manufacturer` | exposed | not-approved | not-approved | exposed | primary+detail |
| Dược liệu / Vị thuốc cổ truyền | `production_country` | exposed | exposed | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `packaging` | exposed | not-approved | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `unit` | exposed | exposed | not-approved | not-approved | primary+detail |
| Dược liệu / Vị thuốc cổ truyền | `quantity` | not-approved | exposed | exposed | not-approved | primary+detail |
| Dược liệu / Vị thuốc cổ truyền | `winning_unit_price` | not-approved | exposed | exposed | not-approved | primary+detail |
| Dược liệu / Vị thuốc cổ truyền | `winning_bidder_id` | not-approved | not-approved | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `winning_bidder_name` | exposed | not-approved | not-approved | exposed | primary+detail |
| Dược liệu / Vị thuốc cổ truyền | `technical_group` | exposed | exposed | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `bid_invitation_code` | exposed | not-approved | not-approved | exposed | primary+detail |
| Dược liệu / Vị thuốc cổ truyền | `procuring_entity_id` | not-approved | not-approved | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `procuring_entity_name` | exposed | not-approved | not-approved | exposed | detail |
| Dược liệu / Vị thuốc cổ truyền | `selection_method` | exposed | exposed | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `result_posted_at` | not-approved | not-approved | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `decision_number` | not-approved | not-approved | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `decision_issued_at` | not-approved | not-approved | not-approved | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `bidder_count` | not-approved | exposed | exposed | not-approved | detail |
| Dược liệu / Vị thuốc cổ truyền | `location` | not-approved | not-approved | not-approved | not-approved | detail |

Capability totals: goods 29 fields / 14 searchable / 11 filterable / 5 sortable / 5 autocomplete; medicines 30 / 16 / 13 / 4 / 6; traditional 29 / 15 / 12 / 4 / 6. Total: 88 fields.

## Seven-subtype journey audit

| Subtype | Group selector | Search + filter | Result detail | Pagination | Status |
|---|---|---|---|---|---|
| `goods_general` | source_tab=HANG_HOA | PASS | PASS | PASS | **PASS** |
| `medical_devices` | source_tab=THIET_BI_VAT_TU_Y_TE | PASS | PASS | PASS | **PASS** |
| `medicine_generic` | source_tab_label=Gói thầu thuốc Generic | PASS | PASS | PASS | **PASS** |
| `medicine_originator` | source_tab_label=Gói thầu thuốc biệt dược gốc | PASS | PASS | PASS | **PASS** |
| `medicine_herbal` | source_tab_label=Gói thầu thuốc dược liệu | PASS | PASS | PASS | **PASS** |
| `herbal_material` | source_tab=DUOC_LIEU | PASS | PASS | PASS | **PASS** |
| `traditional_medicine` | source_tab=VI_THUOC_CO_TRUYEN | PASS | PASS | PASS | **PASS** |

Each journey selected its group/subtype, queried a live contract field/value, applied a relevant filter, opened expanded result detail, and paginated where practical.

## Full-data proof

| Proof | Live evidence |
|---|---|
| 2022 goods | 8,647 hits; sample `2022-11-30` |
| January 2023 goods | 36,772 hits; sample `2023-01-18` |
| Recent 2026 goods | 61,150 hits; sample `2026-07-31` |
| Medical devices | 964,765 hits |
| Generic medicine | 494,717 hits |
| Originator medicine | 55,239 hits |
| Herbal medicine | 35,490 hits |
| Herbal material | 9,554 hits |
| Traditional medicine | 22,468 hits |

## API, fallback, and rollback tests

| Test | Result |
|---|---|
| Typesense-primary search / contract / subtype / text / filter / sort / pagination | **PASS** |
| Autocomplete | **PASS**; 200, live suggestions returned |
| Query preview | **PASS**; total 562,653 |
| Bulk query | **PASS**; matched 2, child errors 0 |
| Infrastructure fallback | **PASS**; valid Postgres response + `DEGRADED_POSTGRES_FALLBACK` |
| Semantic/query-contract failure | **PASS**; propagated without fallback |
| Rollback to Postgres mode | **PASS**; valid legacy page; frontend rollback not required |

## Latency and resources

| Measurement | Result |
|---|---:|
| Normal text API sample | 613.335 ms |
| Filter equality Typesense p50 / p95 | 5.386 / 1,578.911 ms |
| Pagination API sample | 490.069 ms |
| Broad quantity sort API sample | 1,626.476 ms |
| Autocomplete Typesense p50 / p95 | 9.004 / 350.049 ms |
| Typesense RSS | 7,362,288 KB |
| Typesense CPU sample | 22.9% |
| WSL MemAvailable | 11.55 GB |
| WSL swap free | 7.995 GB |
| Typesense processes | 1 |
| FastAPI resource state | No persistent daemon; bounded TestClient only |

## Compatibility and rollback

The incremental CLI remains generation-explicit and targets `serving_v1_20260901`; no backfill or write migration ran. To roll back, set `BIDFINDER_PROCUREMENT_BACKEND=postgres` (and optionally `BIDFINDER_PROCUREMENT_FALLBACK_ENABLED=false`), then restart/reload FastAPI. This requires no frontend rollback. The expected limitation is legacy-subset Postgres coverage.

## Validation

- Focused unittest suite: PASS.
- Full explicit module unittest suite: PASS, 191 tests, 0 failures, 0 errors.
- Node syntax checks, Python compileall, JSON validation, secret scan, and `git diff --check`: PASS.
- `pytest` was unavailable; ordinary unittest discovery also has an existing `tests/msc` import-path defect, so the explicit module loader was used for the complete 189-test result.
- Responsive sanity was verified with native CSS/static assertions; no browser visual harness was available.

## Known limitations

- Postgres fallback is degraded legacy coverage, not full-data equivalence.
- Broad quantity sort is a documented performance outlier and remains accepted MVP behavior.
- Explicit serving generation is used; aliases remain intentionally inactive.
- No persistent FastAPI daemon was started during local validation.


**BIDFinder is ready for real early-stage users to search the complete MSC dataset through Typesense, subject to the documented degraded fallback and runtime deployment restart/reload assumptions.**
