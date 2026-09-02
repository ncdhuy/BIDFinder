# BIDFinder Typesense Search Contract v1

Serving generation: `serving_v1_20260901`  
Machine-readable catalog: [`typesense-search-contract.json`](typesense-search-contract.json)  
Runtime metadata endpoint: `GET /api/search-contract`

Three public query families map to three physical collections: `goods`,
`medicines`, and `traditional` (`traditional_medicine` remains an internal
compatibility key). All rows expose canonical API fields. `detail` is used for
large identifiers that remain available in result/details payloads but are not
shown in dense lists.

## Counts

| Group | Fields | Search | Filter | Sort | Autocomplete | Subtypes |
|---|---:|---:|---:|---:|---:|---|
| goods | 29 | 14 | 11 | 5 | 5 | goods_general, medical_devices |
| medicines | 30 | 16 | 13 | 4 | 6 | medicine_generic, medicine_originator, medicine_herbal |
| traditional | 29 | 15 | 12 | 4 | 6 | herbal_material, traditional_medicine |

Flags: `D` display, `S` full-text search, `F` structured filter, `O` sort,
`A` autocomplete. Subtype column lists source keys, never localized labels.
The JSON catalog additionally records `raw_aliases` for every field, including
source-specific aliases such as `danhMucHangHoa`/`tenThietBi` and `tenThuoc`.
`example_source` identifies the MSC fixture used; `null` means the provided
fixture did not populate a non-null example for that field.

## GOODS

| Field | Flags | Subtypes |
|---|---|---|
| `id` | D(detail) | both |
| `data_group` | D F | both |
| `source_tab` | D F | both |
| `source_tab_label` | D F | both |
| `partition_date` | D F O | both |
| `item_name` | D S A | both |
| `unit` | D S F | both |
| `quantity` | D F O | both |
| `country_of_origin` | D S F | both |
| `hs_code` | D S | both |
| `model_mark` | D S | both |
| `brand` | D S | both |
| `production_year` | D O | both |
| `manufacturer` | D S A | both |
| `technical_specification` | D S | both |
| `model` | D S | medical_devices |
| `registration_or_import_permit_number` | D S | medical_devices |
| `winning_unit_price` | D F O | both |
| `winning_bidder_id` | D(detail) | both |
| `winning_bidder_name` | D S A | both |
| `bid_invitation_code` | D S A | both |
| `procuring_entity_id` | D(detail) | both |
| `procuring_entity_name` | D S A | both |
| `selection_method` | D S F | both |
| `result_posted_at` | D | both |
| `decision_number` | D | both |
| `decision_issued_at` | D | both |
| `bidder_count` | D F O | both |
| `location` | D S | both |

## MEDICINES

| Field | Flags | Subtypes |
|---|---|---|
| `id` | D(detail) | all |
| `data_group` | D F | all |
| `source_tab` | D F | all |
| `source_tab_label` | D F | all |
| `partition_date` | D F O | all |
| `medicine_name` | D S A | all |
| `active_ingredient_or_herbal_component` | D S A | all |
| `strength` | D S | all |
| `marketing_authorization_or_import_permit` | D S | all |
| `route_of_administration` | D S F | all |
| `dosage_form` | D S F | all |
| `shelf_life` | D S | all |
| `manufacturer` | D S A | all |
| `production_country` | D S F | all |
| `packaging` | D S | all |
| `unit` | D S F | all |
| `quantity` | D F O | all |
| `winning_unit_price` | D F O | all |
| `winning_bidder_id` | D(detail) | all |
| `winning_bidder_name` | D S A | all |
| `medicine_group` | D S F | all |
| `bid_invitation_code` | D S A | all |
| `procuring_entity_id` | D(detail) | all |
| `procuring_entity_name` | D S A | all |
| `selection_method` | D S F | all |
| `result_posted_at` | D | all |
| `decision_number` | D | all |
| `decision_issued_at` | D | all |
| `bidder_count` | D F O | all |
| `location` | D S | all |

## TRADITIONAL

| Field | Flags | Subtypes |
|---|---|---|
| `id` | D(detail) | all |
| `data_group` | D F | all |
| `source_tab` | D F | all |
| `source_tab_label` | D F | all |
| `partition_date` | D F O | all |
| `item_name` | D S A | all |
| `used_part` | D S | all |
| `scientific_name` | D S A | all |
| `origin` | D S F | all |
| `processing_method` | D S | all |
| `registration_or_import_permit_number` | D S | all |
| `manufacturer` | D S A | all |
| `production_country` | D S F | all |
| `packaging` | D S | all |
| `unit` | D S F | all |
| `quantity` | D F O | all |
| `winning_unit_price` | D F O | all |
| `winning_bidder_id` | D(detail) | all |
| `winning_bidder_name` | D S A | all |
| `technical_group` | D S F | all |
| `bid_invitation_code` | D S A | all |
| `procuring_entity_id` | D(detail) | all |
| `procuring_entity_name` | D S A | all |
| `selection_method` | D S F | all |
| `result_posted_at` | D | all |
| `decision_number` | D | all |
| `decision_issued_at` | D | all |
| `bidder_count` | D F O | all |
| `location` | D S | all |

## Semantics

- `source_types` maps stable source keys to exact `source_tab` values, or to
  exact `source_tab_label` values when several sources share one MSC tab (the
  three medicine subtypes).
- `text` plus optional `search_fields` drives `q` and `query_by`; clients never
  send Typesense `filter_by` or `sort_by` strings.
- `exactIdentifiers` uses direct document lookup for `id`; other approved code
  fields use field-specific zero-typo search.
- Numeric `0` is a real value. Missing, null, blank, and empty-array values are
  omitted and never translated to numeric zero.
- `partition_date` is the only date range/sort field in V1. Source timestamps
  remain display-only because the schema stores them as raw strings.
- Every explicit sort is deterministic across repeated reads. The frozen live
  Typesense schema treats `id` as an implicit identifier and rejects `id:asc`
  in `sort_by`, so the adapter sends only the advertised sort field and relies
  on Typesense insertion order for the final tie-break.
- `GET /api/query-preview`, `POST /api/bulk-query`, and legacy request fields
  remain compatible. New group-aware fields are active only when the backend
  switch explicitly selects Typesense.

## Phase 4C freeze

The first user-facing Typesense release must let users select one family,
optionally select one or more listed subtypes, use every approved field above,
sort approved fields, and paginate the complete serving generation. A UI that
only exposes legacy Postgres fields is not releasable.
