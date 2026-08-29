# MSC Source Schema V1 Baseline

Status: Phase 0 design baseline. This is a normalized contract proposal, not an implementation and not a claim that all fields have already been verified in every MSC tab export.

Source scope is limited to the seven HÀNG HÓA tabs listed below. Dịch vụ tư vấn and Dịch vụ phi tư vấn are excluded.

## 1. Naming and provenance rules

Normalized field keys use stable English `snake_case` names. `source_tab_label` preserves the exact official tab label. `source_tab` preserves the exact MSC request discriminator discovered during contract discovery; its value is intentionally `TBD` for all seven sources in this Phase 0 document. Do not replace it with a guessed enum.

Every document carries these provenance fields:

| Field | Proposed type | Meaning |
| --- | --- | --- |
| `id` | string | MSC source document UUID; stable Typesense document ID |
| `data_group` | facet/string | `goods`, `medicines`, or `traditional_medicine` |
| `source_tab` | facet/string | Exact MSC source discriminator; opaque until discovered |
| `source_tab_label` | facet/string | Exact official human-readable tab label |
| `partition_date` | string/date | Natural ingestion partition date; derived from the documented MSC date rule, not guessed from local time |

`partition_date` is ingestion metadata, not a substitute for the source's result-posted timestamp. If a later implementation stores an ingestion timestamp or contract version, those are operational fields and must not replace the four provenance fields above.

Rules for all groups:

- Use source UUID as `id`; do not generate a second product ID.
- Preserve source values after deterministic whitespace/Unicode cleanup. Do not invent legacy columns, package joins, validity states, or derived values that MSC does not supply.
- Empty/unknown source values remain empty/null according to the API serializer. They must not become `0`, `UNKNOWN`, a copied neighboring row, or a fabricated legacy value.
- Text fields remain text. Numeric fields are parsed only with a documented deterministic rule; parse failure is a validation error or null according to the field's Phase 1 policy, never an implicit zero.
- Source date fields retain their source meaning. Typesense may store a typed epoch value for filtering/sorting, but the API must render the documented user-facing date consistently.
- The exact export field name and alias for every canonical key must be recorded in the seven-tab contract fixtures before implementation.

## 2. Seven source tabs and three logical groups

| `data_group` | Exact source-tab label | `source_tab` |
| --- | --- | --- |
| `goods` | Hàng hóa ngoài thuốc, thiết bị, vật tư y tế | TBD — discover exact MSC discriminator |
| `goods` | Thiết bị, vật tư y tế | TBD — discover exact MSC discriminator |
| `medicines` | Gói thầu thuốc Generic | TBD — discover exact MSC discriminator |
| `medicines` | Gói thầu thuốc biệt dược gốc | TBD — discover exact MSC discriminator |
| `medicines` | Gói thầu thuốc dược liệu | TBD — discover exact MSC discriminator |
| `traditional_medicine` | Dược liệu | TBD — discover exact MSC discriminator |
| `traditional_medicine` | Vị thuốc cổ truyền | TBD — discover exact MSC discriminator |

Known observations are recorded separately from this source map: `HANG_HOA` was observed for a generic-goods request; `THUOC_TAN_DUOC` and `medicines=["0"]` were observed for one medicine request. Neither observation is promoted to a complete seven-tab enum.

## 3. Group A — `goods`

Sources:

- Hàng hóa ngoài thuốc, thiết bị, vật tư y tế
- Thiết bị, vật tư y tế

| Canonical key | Official/export concept | Proposed type |
| --- | --- | --- |
| `item_name` | Danh mục hàng hóa | string, searchable |
| `unit` | Đơn vị tính | string, facet/searchable |
| `quantity` | Khối lượng | number, sortable |
| `country_of_origin` | Xuất xứ | string, facet/searchable |
| `hs_code` | Mã HS | string, searchable |
| `model_mark` | Kỹ/Ký mã hiệu | string, searchable |
| `brand` | Nhãn hiệu | string, searchable |
| `production_year` | Năm sản xuất | integer, sortable |
| `manufacturer` | Hãng sản xuất | string, searchable/facet |
| `technical_specification` | Cấu hình, tính năng kỹ thuật cơ bản | string, searchable |
| `model` | Chủng loại (model) | string, optional, searchable |
| `registration_or_import_permit_number` | Số lưu hành hoặc số giấy phép nhập khẩu | string, optional, searchable |
| `winning_unit_price` | Đơn giá trúng thầu | number, sortable |
| `winning_bidder_id` | Mã định danh NT trúng thầu | string, searchable |
| `winning_bidder_name` | Tên NT trúng thầu | string, searchable/facet |
| `bid_invitation_code` | Mã TBMT | string, searchable/facet |
| `procuring_entity_id` | Mã định danh CĐT | string, searchable |
| `procuring_entity_name` | Tên CĐT | string, searchable/facet |
| `selection_method` | Hình thức LCNT | string, facet/searchable |
| `result_posted_at` | Ngày đăng tải KQLCNT | date/time, sortable/filterable |
| `decision_number` | Số quyết định | string, searchable |
| `decision_issued_at` | Ngày ban hành quyết định | date/time, sortable/filterable |
| `bidder_count` | Số nhà thầu tham dự | integer, sortable |
| `location` | Địa điểm | string, facet/searchable |

`model` and `registration_or_import_permit_number` are optional because the non-medical-device goods source may not provide them. The medical-device source may use the same concepts under different export labels; that mapping must be fixture-backed.

## 4. Group B — `medicines`

Sources:

- Gói thầu thuốc Generic
- Gói thầu thuốc biệt dược gốc
- Gói thầu thuốc dược liệu

| Canonical key | Official/export concept | Proposed type |
| --- | --- | --- |
| `medicine_name` | Tên thuốc | string, searchable |
| `active_ingredient_or_herbal_component` | Tên hoạt chất / thành phần dược liệu | string, searchable |
| `strength` | Nồng độ, hàm lượng | string, searchable |
| `marketing_authorization_or_import_permit` | GĐKLH hoặc GPNK | string, searchable |
| `route_of_administration` | Đường dùng | string, searchable/facet |
| `dosage_form` | Dạng bào chế | string, searchable/facet |
| `shelf_life` | Hạn dùng (Tuổi thọ) | string, searchable |
| `manufacturer` | Tên cơ sở sản xuất | string, searchable/facet |
| `production_country` | Nước sản xuất | string, facet/searchable |
| `packaging` | Quy cách đóng gói | string, searchable |
| `unit` | Đơn vị tính | string, facet/searchable |
| `quantity` | Số lượng | number, sortable |
| `winning_unit_price` | Đơn giá trúng thầu | number, sortable |
| `winning_bidder_id` | Mã định danh NT trúng thầu | string, searchable |
| `winning_bidder_name` | Tên NT trúng thầu | string, searchable/facet |
| `medicine_group` | Nhóm thuốc | string, facet/searchable |
| `bid_invitation_code` | Mã TBMT | string, searchable/facet |
| `procuring_entity_id` | Mã định danh CĐT | string, searchable |
| `procuring_entity_name` | Tên CĐT | string, searchable/facet |
| `selection_method` | Hình thức LCNT | string, facet/searchable |
| `result_posted_at` | Ngày đăng tải KQLCNT | date/time, sortable/filterable |
| `decision_number` | Số quyết định | string, searchable |
| `decision_issued_at` | Ngày ban hành quyết định | date/time, sortable/filterable |
| `bidder_count` | Số nhà thầu tham dự | integer, sortable |
| `location` | Địa điểm | string, facet/searchable |

`medicine_group` is a source-backed field, not automatically the legacy `BDG`/`N1`-`N5` classification. The old `drug_group_parser.py` may be considered only after exports prove equivalent values.

## 5. Group C — `traditional_medicine`

Sources:

- Dược liệu
- Vị thuốc cổ truyền

| Canonical key | Official/export concept | Proposed type |
| --- | --- | --- |
| `item_name` | Common item-name field representing either Tên dược liệu or Tên vị thuốc cổ truyền | string, searchable |
| `used_part` | Bộ phận dùng | string, searchable |
| `scientific_name` | Tên khoa học | string, searchable |
| `origin` | Nguồn gốc | string, searchable/facet |
| `processing_method` | Phương pháp chế biến | string, searchable |
| `registration_or_import_permit_number` | Số ĐKLH / Giấy phép NK | string, searchable |
| `manufacturer` | Tên cơ sở sản xuất | string, searchable/facet |
| `production_country` | Nước sản xuất | string, facet/searchable |
| `packaging` | Quy cách đóng gói | string, searchable |
| `unit` | Đơn vị tính | string, facet/searchable |
| `quantity` | Số lượng | number, sortable |
| `winning_unit_price` | Đơn giá trúng thầu | number, sortable |
| `winning_bidder_id` | Mã định danh NT trúng thầu | string, searchable |
| `winning_bidder_name` | Tên NT trúng thầu | string, searchable/facet |
| `technical_group` | Nhóm TCKT | string, facet/searchable |
| `bid_invitation_code` | Mã TBMT | string, searchable/facet |
| `procuring_entity_id` | Mã định danh CĐT | string, searchable |
| `procuring_entity_name` | Tên CĐT | string, searchable/facet |
| `selection_method` | Hình thức LCNT | string, facet/searchable |
| `result_posted_at` | Ngày đăng tải KQLCNT | date/time, sortable/filterable |
| `decision_number` | Số quyết định | string, searchable |
| `decision_issued_at` | Ngày ban hành quyết định | date/time, sortable/filterable |
| `bidder_count` | Số nhà thầu tham dự | integer, sortable |
| `location` | Địa điểm | string, facet/searchable |

The two traditional-medicine source tabs share one logical collection but retain their exact `source_tab` and `source_tab_label`. The common `item_name` key is the normalized search surface; the original concept distinction remains in the provenance label and tab discriminator.

## 6. Typesense collection baseline

Logical aliases:

- `bidfinder_goods`
- `bidfinder_medicines`
- `bidfinder_traditional`

Physical collection names must be versioned and later switched through aliases after full validation. Suggested document-shape rules:

- `id`: string, MSC UUID.
- Provenance fields: string/facet fields.
- Search text: string fields included in group-specific `query_by` configuration.
- Numeric values: typed numeric fields, never formatted display strings.
- Dates: one typed representation selected after boundary fixtures; API serialization may render Vietnamese display dates.
- Facets: only fields with stable source semantics, such as group/provenance, selection method, location, country, and verified category/group fields.
- Sort fields: only typed fields with deterministic null ordering, such as result-posted time, decision-issued time, quantity, and winning unit price.

This document does not freeze the final Typesense `fields` array, typo tolerance, ranking, facet list, or `query_by` ordering. Those depend on the seven verified export contracts and the existing API's golden query behavior.

## 7. Legacy compatibility boundaries

The current backend/UI uses fields that do not appear in this V1 source contract, including:

- legacy `df1`/`df2` names;
- package-level `package_metadata` joins;
- approval/expiry/validity display fields;
- `qd_display`, version, legacy QĐ relations, duplicate-warning flags, and goods `Search blob`;
- legacy medicine `nhom_thuoc_filter` values;
- Excel-derived fields such as `Mã phần/lô`, `Tên phần/lô`, `Mặt hàng dự thầu`, and `Thành tiền` where not present in the MSC export contract.

These are not silently added to this schema. Phase 1 must produce one of:

1. a verified direct MSC mapping;
2. an explicitly documented deterministic derived field;
3. a nullable/missing response with the old filter/sort/display path retired or adapted.

No compatibility field may be populated from a guessed package join or copied neighboring row.

## 8. Required contract-discovery record

Before writing the MSC adapter, create fixture-backed evidence for each source tab containing:

- exact request body, including `index`, `tab`, `type`, `medicines`, `matchFields`, filters, date range, page size, and page number;
- exact response body shape for search and export, with sensitive/nonessential values minimized but field names retained;
- aggregation path and count interpretation;
- export record path and truncation/empty behavior;
- source field-to-canonical-key mapping, aliases, null markers, numeric/date parsing rules;
- UUID stability and duplicate behavior;
- accepted errors, retry rules, and rate-limit observations;
- proof that the request selects only one of the seven in-scope tabs.

Until this record exists, `source_tab` values, medicine filter values, tab-specific match fields, and per-tab field assumptions remain unresolved.

## 9. Completeness invariant

For every successful `partition_date × source_tab`:

```text
search agg[0].buckets[0].docCount
= export resultList.length
= normalized row count
= successful Typesense import count
```

The partition fails closed if:

- expected count is greater than or equal to 30,000;
- export returns HTTP failure or a malformed `resultList`;
- export length differs from the search aggregation count;
- normalization drops, duplicates, or produces a different row count;
- Typesense reports fewer successful upserts than normalized rows;
- source UUIDs are missing, duplicated unexpectedly, or unstable.

No Phase 0 code enforces this invariant. It is the acceptance contract for the future ingestion implementation.
