# BIDFinder UI search recovery audit

Status: **PARTIAL**. Initial local UI is usable and complete for discovery, contract selection, preview counts, error handling, and login prompting. PASS is withheld because existing runtime policy requires authentication for result queries and no authorized browser session was available to validate real result rows, pagination, and expanded details.

## Root cause and missed regression

`<typesense-search-form>` existed only inside `.side-panel`, which is fixed-position and hidden until explicitly opened. Phase 4C then hid `#data-view-switcher`, `#df1-panel`, and `#df2-panel`, but not their flex-filling parent `#data-tab`. The hidden search form plus empty flex container produced the observed header, large blank center, and bottom empty-result card.

Earlier tests passed because they only checked contract counts, JavaScript source tokens, responsive CSS tokens, and raw Typesense syntax absence. They never loaded the application in a rendered browser or asserted visibility, placement, size, console errors, or failed requests.

Regression guard: `tests/web/test_browser_ui_recovery.py` uses real Chrome and asserts a visible group control, keyword input, search button, result area, sensible panel height, one contract request, no fatal JavaScript initialization error, seven subtype preview journeys, contract counts, historical date reachability, advanced-filter visibility, auth prompting, and 800 px layout. `tests/web/test_typesense_ui_contract.py` also asserts that the sole form is in main flow before `#data-tab`.

## Fixes

- Moved metadata-driven search form into a visible main-content card below the existing header.
- Kept Hàng hóa as initial group and rendered all group/subtype choices immediately.
- Kept keyword input, field selector, and primary Tìm kiếm action visible.
- Put 36 filter controls and 13 sort choices behind discoverable `Bộ lọc và sắp xếp` progressive disclosure.
- Hid the entire empty legacy `#data-tab` under Typesense-primary UI and allowed natural page flow/scroll.
- Added visible contract-load error with `Thử tải lại` and retry-safe promise handling.
- Preserved guest browsing: contract, metadata, autocomplete, and preview counts remain public. Result queries retain the existing login requirement and open the login panel without a fatal console error.
- Preserved application-level query payloads; frontend still sends group, sourceTypes/subtype, searchFields, structuredFilters, ranges/dateRanges, sort, page, and limit. No raw Typesense syntax is emitted.

## Runtime proof

- Branch: `refactor-msc-typesense-v1`
- Starting HEAD: `04f84bf63d06695afb3756aba638d74c0726eb08`
- Typesense: HTTP 200, `{"ok":true}`
- FastAPI: `/health` OK; `/ready` ready
- Backend: `typesense`
- Generation: `serving_v1_20260901`
- Collections: goods 9,596,715; medicines 585,449; traditional 32,022
- Data plane, schemas, ingestion, serving generation, and Cloudflare: unchanged

## Real-browser proof

Chrome 152.0.7977.66, 1440×1000 and 800×900.

- Initial page: three groups, default Hàng hóa, subtype choices, keyword, field selector, Tìm kiếm, filter/sort disclosure, and compact result state visible.
- Seven subtype preview counts from actual UI: `goods_general` 8,631,874; `medical_devices` 964,841; `medicine_generic` 494,717; `medicine_originator` 55,239; `medicine_herbal` 35,490; `herbal_material` 9,554; `traditional_medicine` 22,468.
- Historical browser/UI previews: 2022 goods 9,718; January 2023 goods 36,772; 2026-09-01 goods 3,003.
- Contract load requests on initial page: 1. No fatal JavaScript initialization errors.
- Login-required behavior: visible login panel and inline result-area explanation; API auth policy unchanged.

Screenshot paths are under `ui-search-recovery-screenshots/`; binaries are intentionally uncommitted.

## Field-contract mapping

Every capability is derived from the active group’s `fields` and `sort_fields` metadata:

- Searchable 45: group tab → `Tất cả trường tìm kiếm` or one approved field → keyword input.
- Filterable 36: group tab → `Bộ lọc và sắp xếp` → string/multi-value, numeric range, or date range control.
- Sortable 13: group tab → `Bộ lọc và sắp xếp` → `Sắp xếp theo` plus ascending/descending.
- Autocomplete 17: group tab → approved autocomplete field → keyword suggestion list.

Goods searchable: `item_name`, `unit`, `country_of_origin`, `hs_code`, `model_mark`, `brand`, `manufacturer`, `technical_specification`, `model`, `registration_or_import_permit_number`, `winning_bidder_name`, `bid_invitation_code`, `procuring_entity_name`, `selection_method`. Filters: `data_group`, `source_tab`, `source_tab_label`, `partition_date`, `unit`, `quantity`, `country_of_origin`, `production_year`, `winning_unit_price`, `selection_method`, `bidder_count`. Sorts: `partition_date`, `quantity`, `production_year`, `winning_unit_price`, `bidder_count`. Autocomplete: `item_name`, `manufacturer`, `winning_bidder_name`, `bid_invitation_code`, `procuring_entity_name`.

Medicines searchable: `medicine_name`, `active_ingredient_or_herbal_component`, `strength`, `marketing_authorization_or_import_permit`, `route_of_administration`, `dosage_form`, `shelf_life`, `manufacturer`, `production_country`, `packaging`, `unit`, `winning_bidder_name`, `medicine_group`, `bid_invitation_code`, `procuring_entity_name`, `selection_method`. Filters: `data_group`, `source_tab`, `source_tab_label`, `partition_date`, `route_of_administration`, `dosage_form`, `production_country`, `unit`, `quantity`, `winning_unit_price`, `medicine_group`, `selection_method`, `bidder_count`. Sorts: `partition_date`, `quantity`, `winning_unit_price`, `bidder_count`. Autocomplete: `medicine_name`, `active_ingredient_or_herbal_component`, `manufacturer`, `winning_bidder_name`, `bid_invitation_code`, `procuring_entity_name`.

Traditional searchable: `item_name`, `used_part`, `scientific_name`, `origin`, `processing_method`, `registration_or_import_permit_number`, `manufacturer`, `production_country`, `packaging`, `unit`, `winning_bidder_name`, `technical_group`, `bid_invitation_code`, `procuring_entity_name`, `selection_method`. Filters: `data_group`, `source_tab`, `source_tab_label`, `partition_date`, `origin`, `production_country`, `unit`, `quantity`, `winning_unit_price`, `technical_group`, `selection_method`, `bidder_count`. Sorts: `partition_date`, `quantity`, `winning_unit_price`, `bidder_count`. Autocomplete: `item_name`, `scientific_name`, `manufacturer`, `winning_bidder_name`, `bid_invitation_code`, `procuring_entity_name`.

## Validation

- Real Chrome/Selenium regression suite: 4 passed, including the explicit landing-screen exit and 800x900 rendered-layout guard.
- Frontend contract tests: 6 passed; JavaScript syntax checks: 3 passed; browser test `py_compile`: passed.
- Relevant maintained backend tests: 39 passed.
- Targeted secret scan across the nine recovery source/test/audit files: clean.
- `git diff --check`: passed.

## Remaining PASS blockers

- Authenticate in a browser authorized for this local runtime.
- Run result-producing searches for all seven subtypes.
- Capture actual goods, medicine, and traditional result screenshots.
- Exercise next/previous pagination and expand a real result’s `Chi tiết đầy đủ` section.

No commit was created because the task permits commit only after full browser PASS.
