# BIDFinder Typesense schema V1 (Phase 1A freeze)

Status: documentation/configuration only. No Typesense server or collection was contacted or created.

Physical collections must be versioned later and switched through aliases only after full count, normalization, search, sort, and facet validation. Future Typesense `id` is the MSC UUID. The `source_tab` values below are opaque MSC values, not repository directory names.

## Common fields

| Field | Typesense type | Optional | Facet | Sort | Search | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | string | no | no | no | no | Source UUID; document ID |
| `data_group` | string | no | yes | no | no | `goods`, `medicines`, `traditional_medicine` |
| `source_tab` | string | no | yes | no | no | Exact MSC discriminator |
| `source_tab_label` | string | no | yes | no | no | Stable human label |
| `partition_date` | string | no | yes | yes | no | `YYYY-MM-DD`; natural daily partition |

Dates remain raw strings in V1 because response timestamps have no explicit timezone. Do not manufacture epoch values until timezone semantics are proven. `partition_date` is the ingestion partition, not a replacement for the source timestamp.

## `bidfinder_goods`

| Field | Typesense type | Optional | Facet | Sort | Search | Query-by role |
| --- | --- | --- | --- | --- | --- | --- |
| `item_name` | string | yes | no | no | yes | primary |
| `unit` | string | yes | yes | no | yes | |
| `quantity` | float | yes | no | yes | no | |
| `country_of_origin` | string | yes | yes | no | yes | |
| `hs_code` | string | yes | no | no | yes | |
| `model_mark` | string | yes | no | no | yes | |
| `brand` | string | yes | no | no | yes | |
| `production_year` | int32 | yes | no | yes | no | strict four-digit source value only |
| `manufacturer` | string | yes | no | no | yes | |
| `technical_specification` | string | yes | no | no | yes | |
| `model` | string | yes | no | no | yes | medical-device optional concept |
| `registration_or_import_permit_number` | string | yes | no | no | yes | medical-device optional concept |
| `winning_unit_price` | float | yes | no | yes | no | |
| `winning_bidder_id` | string[] | yes | no | no | yes | preserve all returned IDs |
| `winning_bidder_name` | string[] | yes | no | no | yes | preserve all returned names |
| `bid_invitation_code` | string | yes | no | no | yes | |
| `procuring_entity_id` | string | yes | no | no | yes | |
| `procuring_entity_name` | string | yes | no | no | yes | |
| `selection_method` | string | yes | yes | no | yes | |
| `result_posted_at` | string | yes | no | no | no | raw local-naive MSC timestamp |
| `decision_number` | string | yes | no | no | yes | |
| `decision_issued_at` | string | yes | no | no | no | raw local-naive MSC timestamp |
| `bidder_count` | float | yes | no | yes | no | fractional values observed |
| `location` | string | yes | no | no | yes | deterministic display join from `diaDiem` |

`query_by` order: `item_name,country_of_origin,hs_code,model_mark,brand,manufacturer,technical_specification,model,registration_or_import_permit_number,winning_bidder_name,bid_invitation_code,procuring_entity_name,selection_method,unit`.

## `bidfinder_medicines`

| Field | Typesense type | Optional | Facet | Sort | Search |
| --- | --- | --- | --- | --- | --- |
| `medicine_name` | string | yes | no | no | yes |
| `active_ingredient_or_herbal_component` | string | yes | no | no | yes |
| `strength` | string | yes | no | no | yes |
| `marketing_authorization_or_import_permit` | string | yes | no | no | yes |
| `route_of_administration` | string | yes | yes | no | yes |
| `dosage_form` | string | yes | yes | no | yes |
| `shelf_life` | string | yes | no | no | yes |
| `manufacturer` | string | yes | no | no | yes |
| `production_country` | string | yes | yes | no | yes |
| `packaging` | string | yes | no | no | yes |
| `unit` | string | yes | yes | no | yes |
| `quantity` | float | yes | no | yes | no |
| `winning_unit_price` | float | yes | no | yes | no |
| `winning_bidder_id` | string[] | yes | no | no | yes |
| `winning_bidder_name` | string[] | yes | no | no | yes |
| `medicine_group` | string | yes | yes | no | yes |
| `bid_invitation_code` | string | yes | no | no | yes |
| `procuring_entity_id` | string | yes | no | no | yes |
| `procuring_entity_name` | string | yes | no | no | yes |
| `selection_method` | string | yes | yes | no | yes |
| `result_posted_at` | string | yes | no | no | no |
| `decision_number` | string | yes | no | no | yes |
| `decision_issued_at` | string | yes | no | no | no |
| `bidder_count` | float | yes | no | yes | no |
| `location` | string | yes | no | no | yes |

`query_by` order: `medicine_name,active_ingredient_or_herbal_component,strength,marketing_authorization_or_import_permit,route_of_administration,dosage_form,shelf_life,manufacturer,production_country,packaging,winning_bidder_name,medicine_group,bid_invitation_code,procuring_entity_name,selection_method,unit`.

## `bidfinder_traditional`

| Field | Typesense type | Optional | Facet | Sort | Search |
| --- | --- | --- | --- | --- | --- |
| `item_name` | string | yes | no | no | yes |
| `used_part` | string | yes | no | no | yes |
| `scientific_name` | string | yes | no | no | yes |
| `origin` | string | yes | yes | no | yes |
| `processing_method` | string | yes | no | no | yes |
| `registration_or_import_permit_number` | string | yes | no | no | yes |
| `manufacturer` | string | yes | no | no | yes |
| `production_country` | string | yes | yes | no | yes |
| `packaging` | string | yes | no | no | yes |
| `unit` | string | yes | yes | no | yes |
| `quantity` | float | yes | no | yes | no |
| `winning_unit_price` | float | yes | no | yes | no |
| `winning_bidder_id` | string[] | yes | no | no | yes |
| `winning_bidder_name` | string[] | yes | no | no | yes |
| `technical_group` | string | yes | yes | no | yes |
| `bid_invitation_code` | string | yes | no | no | yes |
| `procuring_entity_id` | string | yes | no | no | yes |
| `procuring_entity_name` | string | yes | no | no | yes |
| `selection_method` | string | yes | yes | no | yes |
| `result_posted_at` | string | yes | no | no | no |
| `decision_number` | string | yes | no | no | yes |
| `decision_issued_at` | string | yes | no | no | no |
| `bidder_count` | float | yes | no | yes | no |
| `location` | string | yes | no | no | yes |

`query_by` order: `item_name,used_part,scientific_name,origin,processing_method,registration_or_import_permit_number,manufacturer,production_country,packaging,winning_bidder_name,technical_group,bid_invitation_code,procuring_entity_name,selection_method,unit`.

## Freeze boundaries

- High-cardinality names, IDs, codes, manufacturers, bidders, and procuring entities are searchable but not facets.
- Numeric JSON values stay numeric. Arrays remain arrays until an explicit API presentation rule is chosen.
- Unsupported legacy fields (`df1`/`df2` names, package joins, validity/approval fields, Excel-only columns) are absent or nullable; no guessed compatibility values enter these collections.
- `result_posted_at` and `decision_issued_at` keep raw source strings in V1. A future typed date field requires a new schema version and proven timezone handling.
