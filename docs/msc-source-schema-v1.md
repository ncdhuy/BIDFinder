# MSC Source Schema V1 Baseline

Status: Phase 1B public-search field and pagination contract. This remains documentation and fixture infrastructure, not a production ingestion implementation.

Source scope is limited to the seven HÀNG HÓA tabs listed below. Dịch vụ tư vấn and Dịch vụ phi tư vấn are excluded.

## 1. Naming and provenance rules

Normalized field keys use stable English `snake_case` names. `source_tab_label` preserves the official human-readable label. `source_tab` preserves the exact MSC request discriminator discovered during Phase 1A contract discovery; all seven values are now fixture-backed. Do not replace them with a guessed enum.

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
- The exact public-search field name and alias for every canonical key must be recorded in the seven-tab contract fixtures before implementation.

## 2. Seven source tabs and three logical groups

| `data_group` | Exact source-tab label | `source_tab` |
| --- | --- | --- |
| `goods` | Hàng hóa ngoài thuốc, thiết bị, vật tư y tế | `HANG_HOA` |
| `goods` | Thiết bị, vật tư y tế | `THIET_BI_VAT_TU_Y_TE` |
| `medicines` | Gói thầu thuốc Generic | `THUOC_TAN_DUOC` + `medicines=["0"]` |
| `medicines` | Gói thầu thuốc biệt dược gốc | `THUOC_TAN_DUOC` + `medicines=["1"]` |
| `medicines` | Gói thầu thuốc dược liệu | `THUOC_TAN_DUOC` + `medicines=["2"]` |
| `traditional_medicine` | Dược liệu | `DUOC_LIEU` + `medicine_type=[0,null]` |
| `traditional_medicine` | Vị thuốc cổ truyền | `VI_THUOC_CO_TRUYEN` + `medicine_type=[0,null]` |

Phase 1A fixture-backed evidence for exact request contracts is recorded under `docs/msc-contracts/`. The outer `type` is `HANG_HOA` for all seven sources; the table records each exact `tab` and special discriminator.

## 3. Group A — `goods`

Sources:

- Hàng hóa ngoài thuốc, thiết bị, vật tư y tế
- Thiết bị, vật tư y tế

| Canonical key | Public-search source concept | Proposed type |
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
| `bidder_count` | Số nhà thầu tham dự | float, sortable |
| `location` | Địa điểm | string, facet/searchable |

`model` and `registration_or_import_permit_number` remain optional. Their device mappings are verified for medical devices; their canonical meaning for general goods is `UNKNOWN` and must not become a production dependency.

## 4. Group B — `medicines`

Sources:

- Gói thầu thuốc Generic
- Gói thầu thuốc biệt dược gốc
- Gói thầu thuốc dược liệu

| Canonical key | Public-search source concept | Proposed type |
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
| `bidder_count` | Số nhà thầu tham dự | float, sortable |
| `location` | Địa điểm | string, facet/searchable |

`medicine_group` is a source-backed field, not automatically the legacy `BDG`/`N1`-`N5` classification. The old `drug_group_parser.py` may be considered only after exports prove equivalent values.

## 5. Group C — `traditional_medicine`

Sources:

- Dược liệu
- Vị thuốc cổ truyền

| Canonical key | Public-search source concept | Proposed type |
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
| `bidder_count` | Số nhà thầu tham dự | float, sortable |
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

Phase 1A freezes the documentation-only field matrices, facet choices, and evidence-based `query_by` order in [`docs/msc-typesense-schema-v1.md`](msc-typesense-schema-v1.md). Typo tolerance, ranking, and runtime collection aliases remain later-phase decisions.

## 7. Legacy compatibility boundaries

The current backend/UI uses fields that do not appear in this V1 source contract, including:

- legacy `df1`/`df2` names;
- package-level `package_metadata` joins;
- approval/expiry/validity display fields;
- `qd_display`, version, legacy QĐ relations, duplicate-warning flags, and goods `Search blob`;
- legacy medicine `nhom_thuoc_filter` values;
- Excel-derived fields such as `Mã phần/lô`, `Tên phần/lô`, `Mặt hàng dự thầu`, and `Thành tiền` where not present in the public MSC search contract.

These are not silently added to this schema. Phase 1 must produce one of:

1. a verified direct MSC mapping;
2. an explicitly documented deterministic derived field;
3. a nullable/missing response with the old filter/sort/display path retired or adapted.

No compatibility field may be populated from a guessed package join or copied neighboring row.

## 8. Phase 1B public-search evidence record

Before writing the MSC adapter, fixture-backed evidence for each source tab must contain:

- exact request body, including `index`, `tab`, `type`, `medicines`, `matchFields`, filters, date range, page size, and page number;
- exact public search response body shape, with sensitive/nonessential values minimized but field names retained;
- aggregation path and count interpretation;
- page metadata, safe page offsets, required-page calculation, and pagination result;
- source field-to-canonical-key mapping, aliases, null markers, numeric/date parsing rules;
- UUID stability and duplicate behavior;
- accepted errors, retry rules, and rate-limit observations;
- proof that the request selects only one of the seven in-scope tabs.

All seven records now exist under [`docs/msc-contracts/`](msc-contracts/README.md). The seven source request contracts are verified; do not rediscover or rename their discriminators without contradictory official evidence.

## 9. Search-only completeness invariant

For every successful `partition_date × source_tab`:

```text
search agg[0].buckets[0].docCount
= collected page.content length
= unique UUID count
```

The partition fails closed if:

- expected count reaches `MAX_SAFE_DAILY_RESULTS=9500`;
- any required search page returns a non-200 response or malformed envelope/metadata;
- a page offset reaches the 10,000-result search window;
- collected `page.content` length differs from the search aggregation count;
- a UUID is missing, duplicated within a page, or overlaps another page;
- normalization drops, duplicates, or produces a different row count;
- Typesense reports fewer successful upserts than normalized rows;
- source UUIDs are missing, duplicated unexpectedly, or unstable.

Phase 1B validates the search-only portion with a pure offline helper and a public live probe. Normalization and Typesense import checks remain future-phase gates.

## 10. Phase 1A contract freeze, finalized by Phase 1B

Phase 1A evidence lives under [`docs/msc-contracts/`](msc-contracts/README.md). All seven source contracts are verified from the official page's inline Vue definitions plus read-only `/search_prc` captures. The public-search pagination and field-parity evidence is recorded in [`search-only-validation.json`](msc-contracts/search-only-validation.json). Export request shape and historical `resultList` behavior remain reference metadata only; interactive login, reCAPTCHA, Google Authenticator OTP/MFA, and expiring sessions make `/export` unsuitable as a production dependency.

| Data group | Source label | Exact `type` | Exact `tab` | Special filter |
| --- | --- | --- | --- | --- |
| `goods` | Hàng hóa ngoài thuốc, thiết bị, vật tư y tế | `HANG_HOA` | `HANG_HOA` | none |
| `goods` | Thiết bị, vật tư y tế | `HANG_HOA` | `THIET_BI_VAT_TU_Y_TE` | none |
| `medicines` | Gói thầu thuốc Generic | `HANG_HOA` | `THUOC_TAN_DUOC` | `medicines=["0"]` |
| `medicines` | Gói thầu thuốc biệt dược gốc | `HANG_HOA` | `THUOC_TAN_DUOC` | `medicines=["1"]` |
| `medicines` | Gói thầu thuốc dược liệu | `HANG_HOA` | `THUOC_TAN_DUOC` | `medicines=["2"]` |
| `traditional_medicine` | Dược liệu | `HANG_HOA` | `DUOC_LIEU` | `medicine_type=[0,null]` when official `medicineType=0` |
| `traditional_medicine` | Vị thuốc cổ truyền | `HANG_HOA` | `VI_THUOC_CO_TRUYEN` | `medicine_type=[0,null]` when official `medicineType=0` |

The first label is rendered by current page markup as `Hàng hóa ngoài thuốc,thiết bị, vật tư y tế` without a space after the comma. Repository metadata keeps the Phase 0 human label with spacing; this punctuation difference does not alter the exact MSC discriminator.

Every request uses index `es-smart-pricing`, `matchType=all-1`, empty `keyWordNotMatch`, a source-specific `matchFields` list, and the official date filter when partitioned. Search records are under `page.content`; count is `agg[0].buckets[0].docCount`. The production proof uses public search only; `resultList` remains an offline historical parser shape.

### 10.1 Source-to-canonical mapping

Mapping policy values: `text` means NFC Unicode normalization, whitespace collapse, and trim; `number` means preserve JSON numbers and parse numeric-looking strings only where the source fixture proves that field representation; `date-raw` means preserve the source string; `array` means preserve all array members; `location-join` means deterministic source-order display joining of `diaDiem` components.

#### Goods

| Canonical key | Source JSON field: general / device | Source type(s) | Canonical type | Null/blank policy | Normalization | Search | Facet | Sort | Sources / optional |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `item_name` | `danhMucHangHoa` / `tenThietBi` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `unit` | `donViTinh` / `donViTinh` | string | string | absent/blank -> null | text | yes | yes | no | both / yes |
| `quantity` | `khoiLuongDouble` / `khoiLuongDouble` | JSON number | float | absent/invalid -> null | number | no | no | yes | both / yes |
| `country_of_origin` | `xuatXu` / `xuatXu` | string | string | absent/blank -> null | text | yes | yes | no | both / yes |
| `hs_code` | `maHs` / `maHs` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `model_mark` | `kyMaHieu` / `kyMaHieu` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `brand` | `nhanHieu` / `nhanHieu` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `production_year` | `namSanXuat` / `namSanXuat` | string | int32 | non-four-digit -> null | strict year | no | no | yes | both / yes |
| `manufacturer` | `hangSanXuat` / `hangSanXuat` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `technical_specification` | `cauHinh` / `cauHinh` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `model` | absent / `chungLoai` | string or absent | string | absent/blank -> null | text | yes | no | no | device / yes |
| `registration_or_import_permit_number` | absent / `soLuuHanh` | string or absent | string | absent/blank -> null | text | yes | no | no | device / yes |
| `winning_unit_price` | `donGiaDuThau` / `donGia` | JSON number | float | absent/invalid -> null | number | no | no | yes | both / yes |
| `winning_bidder_id` | `winningCode` / `winningCode` | string[] | string[] | absent/empty -> null | array + text | yes | no | no | both / yes |
| `winning_bidder_name` | `winningName` / `winningName` | string[] | string[] | absent/empty -> null | array + text | yes | no | no | both / yes |
| `bid_invitation_code` | `maTbmt` / `maTbmt` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `procuring_entity_id` | `maCdt` / `maCdt` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `procuring_entity_name` | `tenCdtBmt` / `tenCdtBmt` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `selection_method` | `bidForm` / `bidForm` | string | string | absent/blank -> null | text | yes | yes | no | both / yes |
| `result_posted_at` | `ngayDangTaiKqlcnt` / `ngayDangTaiKqlcnt` | date string | string | absent -> null | date-raw | no | no | no | both / yes |
| `decision_number` | `soQuyetDinh` / `soQuyetDinh` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `decision_issued_at` | `ngayBanHanhQuyetDinh` / `ngayBanHanhQuyetDinh` | date string | string | absent -> null | date-raw | no | no | no | both / yes |
| `bidder_count` | `soNhaThauThamDu` / `soNhaThauThamDu` | JSON number, often absent | float | absent/invalid -> null | number | no | no | yes | both / yes |
| `location` | `diaDiem` / `diaDiem` | object[] | string | absent/empty -> null | location-join | yes | no | no | both / yes |

#### Medicines

| Canonical key | Source JSON field | Source type | Canonical type | Null/blank policy | Normalization | Search | Facet | Sort | Sources / optional |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `medicine_name` | `tenThuoc` | string or absent | string | absent/blank -> null | text | yes | no | no | all / yes |
| `active_ingredient_or_herbal_component` | `tenHoatChat` | string | string | absent/blank -> null | text | yes | no | no | all / yes |
| `strength` | `nongDo` | string | string | absent/blank -> null | text | yes | no | no | all / yes |
| `marketing_authorization_or_import_permit` | `gdklh_GPNK` | string | string | absent/blank -> null | text | yes | no | no | all / yes |
| `route_of_administration` | `duongDung` | string | string | absent/blank -> null | text | yes | yes | no | all / yes |
| `dosage_form` | `dangBaoChe` | string | string | absent/blank -> null | text | yes | yes | no | all / yes |
| `shelf_life` | `hanDung` | string or absent | string | absent/blank -> null | text | yes | no | no | all / yes |
| `manufacturer` | `tenCoSoSanXuat` | string | string | absent/blank -> null | text | yes | no | no | all / yes |
| `production_country` | `nuocSanXuat` | string | string | absent/blank -> null | text | yes | yes | no | all / yes |
| `packaging` | `quyCachDongGoi` | string | string | absent/blank -> null | text | yes | no | no | all / yes |
| `unit` | `donViTinh` | string | string | absent/blank -> null | text | yes | yes | no | all / yes |
| `quantity` | `soLuong` | JSON number | float | absent/invalid -> null | number | no | no | yes | all / yes |
| `winning_unit_price` | `donGia` | JSON number | float | absent/invalid -> null | number | no | no | yes | all / yes |
| `winning_bidder_id` | `winningCode` | string[] | string[] | absent/empty -> null | array + text | yes | no | no | all / yes |
| `winning_bidder_name` | `winningName` | string[] | string[] | absent/empty -> null | array + text | yes | no | no | all / yes |
| `medicine_group` | `nhomThuoc` | string | string | absent/blank -> null | text | yes | yes | no | all / yes |
| `bid_invitation_code` | `maTbmt` | string | string | absent/blank -> null | text | yes | no | no | all / yes |
| `procuring_entity_id` | `maCdt` | string | string | absent/blank -> null | text | yes | no | no | all / yes |
| `procuring_entity_name` | `tenCdtBmt` | string | string | absent/blank -> null | text | yes | no | no | all / yes |
| `selection_method` | `bidForm` | string | string | absent/blank -> null | text | yes | yes | no | all / yes |
| `result_posted_at` | `ngayDangTaiKqlcnt` | date string | string | absent -> null | date-raw | no | no | no | all / yes |
| `decision_number` | `soQuyetDinh` | string | string | absent/blank -> null | text | yes | no | no | all / yes |
| `decision_issued_at` | `ngayBanHanhQuyetDinh` | date string | string | absent -> null | date-raw | no | no | no | all / yes |
| `bidder_count` | `soNhaThauThamDu` | JSON number or absent | float | absent/invalid -> null | number | no | no | yes | all / yes |
| `location` | `diaDiem` | object[] | string | absent/empty -> null | location-join | yes | no | no | all / yes |

#### Traditional medicine

| Canonical key | Source JSON field: Dược liệu / Vị thuốc | Source type(s) | Canonical type | Null/blank policy | Normalization | Search | Facet | Sort | Sources / optional |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `item_name` | `tenDuocLieu` / `tenViThuocCoTruyen` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `used_part` | `boPhanDung` / `boPhanDung` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `scientific_name` | `tenKhoaHoc` / `tenKhoaHoc` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `origin` | `nguonGoc` / `nguonGoc` | string | string | absent/blank -> null | text | yes | yes | no | both / yes |
| `processing_method` | `phuongPhapCheBien` / `phuongPhapCheBien` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `registration_or_import_permit_number` | `gdklh_GPNK` / `gdklh_GPNK` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `manufacturer` | `tenCoSoSanXuat` / `tenCoSoSanXuat` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `production_country` | `nuocSanXuat` / `nuocSanXuat` | string | string | absent/blank -> null | text | yes | yes | no | both / yes |
| `packaging` | `quyCachDongGoi` / `quyCachDongGoi` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `unit` | `donViTinh` / `donViTinh` | string | string | absent/blank -> null | text | yes | yes | no | both / yes |
| `quantity` | `soLuong` / `soLuong` | JSON number | float | absent/invalid -> null | number | no | no | yes | both / yes |
| `winning_unit_price` | `donGia` / `donGia` | JSON number | float | absent/invalid -> null | number | no | no | yes | both / yes |
| `winning_bidder_id` | `winningCode` / `winningCode` | string[] | string[] | absent/empty -> null | array + text | yes | no | no | both / yes |
| `winning_bidder_name` | `winningName` / `winningName` | string[] | string[] | absent/empty -> null | array + text | yes | no | no | both / yes |
| `technical_group` | `nhomTCKT` / `nhomTCKT` | string | string | absent/blank -> null | text | yes | yes | no | both / yes |
| `bid_invitation_code` | `maTbmt` / `maTbmt` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `procuring_entity_id` | `maCdt` / `maCdt` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `procuring_entity_name` | `tenCdtBmt` / `tenCdtBmt` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `selection_method` | `bidForm` / `bidForm` | string | string | absent/blank -> null | text | yes | yes | no | both / yes |
| `result_posted_at` | `ngayDangTaiKqlcnt` / `ngayDangTaiKqlcnt` | date string | string | absent -> null | date-raw | no | no | no | both / yes |
| `decision_number` | `soQuyetDinh` / `soQuyetDinh` | string | string | absent/blank -> null | text | yes | no | no | both / yes |
| `decision_issued_at` | `ngayBanHanhQuyetDinh` / `ngayBanHanhQuyetDinh` | date string | string | absent -> null | date-raw | no | no | no | both / yes |
| `bidder_count` | `soNhaThauThamDu` / `soNhaThauThamDu` | JSON number or absent | float | absent/invalid -> null | number | no | no | yes | both / yes |
| `location` | `diaDiem` / `diaDiem` | object[] | string | absent/empty -> null | location-join | yes | no | no | both / yes |

Phase 1B field-parity evidence classifies `herbal-material.bidder_count` as `UNKNOWN`: the mapped field was absent from its selected full public-search partition. Keep it optional; do not fabricate zero.

Source-only classifier and display fields (`medicines`, `medicineType`, `dangBaoChe`, and observed duplicate price aliases) remain provenance, not fabricated canonical columns. They may be retained in raw evidence/control metadata later.

### 10.2 Numeric and text rules

- `khoiLuongDouble`, `soLuong`, `donGia`, `donGiaDuThau`, and `medicineType` are JSON numbers in public-search evidence. Keep them numeric. `soNhaThauThamDu` is a fractional JSON number in device and traditional samples, while absent in the selected Dược liệu partition; canonical `bidder_count` is `float` when present, otherwise null.
- `namSanXuat` is a string. Strict four-digit values may become `production_year`; values such as `2025 trở về sau` stay raw-only and canonical `production_year` remains null. No numeric-looking string is silently coerced elsewhere.
- Missing fields and empty strings become null during future normalization. Invalid numeric/date values become validation failures or null by field policy, never zero.
- Reuse only narrow future primitives from `crawler_engine/schema_normalization_shared.py`: NFC Unicode normalization, whitespace cleanup, and safe null handling. Do not import the Excel pipeline or its inference rules.

### 10.3 Date and UUID findings

The official page defines `convertDateFrom`/`convertDateTo` and emits the observed range form `T00:00:00.000Z` through `T23:59:59.059Z`; V1 reproduces this byte-for-byte and does not change `.059Z` to `.999Z`. Response values are strings such as `2026-08-28T23:57:28` with no timezone marker. The page adds seven hours in its date helper, but the server's timezone interpretation cannot be proven from these small captures.

A repeated public goods query returned the same UUID and timestamp. Phase 1B full controlled partitions had no duplicate UUIDs or page overlap, and repeated page 0 returned the same UUID order. This is sampled stability evidence only, not universal cross-day uniqueness proof.

Boundary fixture limitation: no record exactly at `23:59:59.059Z` or `00:00:00.000Z` was available, so inclusive/exclusive behavior and timezone meaning remain unresolved. Daily official ranges are retained exactly for V1; do not start production ingestion until a boundary capture proves the missing edge cases.

## 11. Phase 1A status

All seven source request contracts are resolved and fixture-backed for exact type/tab/match fields/special filters, public search envelope, count path, source field names, and pagination evidence. Phase 1A is complete for contract discovery and offline infrastructure. Phase 1B is partial: safe representative partitions pass, but overflow days require a future secondary strategy; exact timestamp boundary semantics remain unresolved. No authenticated MSC session is required for the proven search path.
