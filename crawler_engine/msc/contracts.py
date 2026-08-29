"""Frozen, verified MSC source contracts from Phase 1A/1B."""

from __future__ import annotations

from .models import FieldMapping, FilterSpec, SourceContract


def _filter(field_name: str, *values: object) -> FilterSpec:
    return FilterSpec(field_name, "in", tuple(values))


def _mapping(*pairs: tuple[str, str]) -> tuple[FieldMapping, ...]:
    return tuple(FieldMapping(canonical, source) for canonical, source in pairs)


_GOODS_FIELDS = (
    "bidForm", "cauHinh", "chungLoai", "danhMucHangHoa", "decisions", "diaDiem",
    "donGia", "donGiaDuThau", "donViTinh", "hangSanXuat", "id", "khoiLuongDouble",
    "kyMaHieu", "maCdt", "maHs", "maTbmt", "namSanXuat", "ngayBanHanhQuyetDinh",
    "ngayDangTaiKqlcnt", "nhanHieu", "soLuuHanh", "soNhaThauThamDu", "soQuyetDinh",
    "tab", "tenCdtBmt", "type", "winningCode", "winningName", "xuatXu",
)
_DEVICE_FIELDS = (
    "bidForm", "cauHinh", "chungLoai", "decisions", "diaDiem", "donGia", "donGiaDuThau",
    "donViTinh", "hangSanXuat", "id", "khoiLuongDouble", "kyMaHieu", "maCdt", "maHs",
    "maTbmt", "namSanXuat", "ngayBanHanhQuyetDinh", "ngayDangTaiKqlcnt", "nhanHieu",
    "soLuuHanh", "soNhaThauThamDu", "soQuyetDinh", "tab", "tenCdtBmt", "tenThietBi",
    "type", "winningCode", "winningName", "xuatXu",
)
_MEDICINE_FIELDS = (
    "bidForm", "dangBaoChe", "decisions", "diaDiem", "donGia", "donViTinh", "duongDung",
    "gdklh_GPNK", "hanDung", "id", "maCdt", "maTbmt", "medicines", "ngayBanHanhQuyetDinh",
    "ngayDangTaiKqlcnt", "nhomThuoc", "nongDo", "nuocSanXuat", "quyCachDongGoi", "soLuong",
    "soNhaThauThamDu", "soQuyetDinh", "tab", "tenCdtBmt", "tenCoSoSanXuat", "tenHoatChat",
    "tenThuoc", "type", "winningCode", "winningName",
)
_ORIGINATOR_FIELDS = tuple(field for field in _MEDICINE_FIELDS if field != "decisions")
_HERBAL_MATERIAL_FIELDS = (
    "bidForm", "boPhanDung", "dangBaoChe", "diaDiem", "donGia", "donViTinh", "gdklh_GPNK",
    "id", "maCdt", "maTbmt", "medicineType", "ngayBanHanhQuyetDinh", "ngayDangTaiKqlcnt",
    "nguonGoc", "nhomTCKT", "nuocSanXuat", "phuongPhapCheBien", "quyCachDongGoi", "soLuong",
    "soQuyetDinh", "tab", "tenCdtBmt", "tenCoSoSanXuat", "tenDuocLieu", "tenKhoaHoc",
    "tenSanPham", "type", "winningCode", "winningName",
)
_TRADITIONAL_FIELDS = (
    "bidForm", "boPhanDung", "dangBaoChe", "diaDiem", "donGia", "donGiaDuThau", "donViTinh",
    "gdklh_GPNK", "id", "maCdt", "maTbmt", "ngayBanHanhQuyetDinh", "ngayDangTaiKqlcnt",
    "nguonGoc", "nhomTCKT", "nuocSanXuat", "phuongPhapCheBien", "quyCachDongGoi", "soLuong",
    "soNhaThauThamDu", "soQuyetDinh", "tab", "tenCdtBmt", "tenCoSoSanXuat", "tenKhoaHoc",
    "tenSanPham", "tenViThuocCoTruyen", "type", "winningCode", "winningName",
)

_GOODS_MAPPING = _mapping(
    ("item_name", "danhMucHangHoa"), ("unit", "donViTinh"), ("quantity", "khoiLuongDouble"),
    ("country_of_origin", "xuatXu"), ("hs_code", "maHs"), ("model_mark", "kyMaHieu"),
    ("brand", "nhanHieu"), ("production_year", "namSanXuat"), ("manufacturer", "hangSanXuat"),
    ("technical_specification", "cauHinh"), ("winning_unit_price", "donGiaDuThau"),
    ("winning_bidder_id", "winningCode"), ("winning_bidder_name", "winningName"),
    ("bid_invitation_code", "maTbmt"), ("procuring_entity_id", "maCdt"),
    ("procuring_entity_name", "tenCdtBmt"), ("selection_method", "bidForm"),
    ("result_posted_at", "ngayDangTaiKqlcnt"), ("decision_number", "soQuyetDinh"),
    ("decision_issued_at", "ngayBanHanhQuyetDinh"), ("bidder_count", "soNhaThauThamDu"),
    ("location", "diaDiem"),
)
_DEVICE_MAPPING = _mapping(
    ("item_name", "tenThietBi"), ("unit", "donViTinh"), ("quantity", "khoiLuongDouble"),
    ("country_of_origin", "xuatXu"), ("hs_code", "maHs"), ("model_mark", "kyMaHieu"),
    ("brand", "nhanHieu"), ("production_year", "namSanXuat"), ("manufacturer", "hangSanXuat"),
    ("technical_specification", "cauHinh"), ("model", "chungLoai"),
    ("registration_or_import_permit_number", "soLuuHanh"), ("winning_unit_price", "donGia"),
    ("winning_bidder_id", "winningCode"), ("winning_bidder_name", "winningName"),
    ("bid_invitation_code", "maTbmt"), ("procuring_entity_id", "maCdt"),
    ("procuring_entity_name", "tenCdtBmt"), ("selection_method", "bidForm"),
    ("result_posted_at", "ngayDangTaiKqlcnt"), ("decision_number", "soQuyetDinh"),
    ("decision_issued_at", "ngayBanHanhQuyetDinh"), ("bidder_count", "soNhaThauThamDu"),
    ("location", "diaDiem"),
)
_MEDICINE_MAPPING = _mapping(
    ("medicine_name", "tenThuoc"), ("active_ingredient_or_herbal_component", "tenHoatChat"),
    ("strength", "nongDo"), ("marketing_authorization_or_import_permit", "gdklh_GPNK"),
    ("route_of_administration", "duongDung"), ("dosage_form", "dangBaoChe"),
    ("shelf_life", "hanDung"), ("manufacturer", "tenCoSoSanXuat"),
    ("production_country", "nuocSanXuat"), ("packaging", "quyCachDongGoi"),
    ("unit", "donViTinh"), ("quantity", "soLuong"), ("winning_unit_price", "donGia"),
    ("winning_bidder_id", "winningCode"), ("winning_bidder_name", "winningName"),
    ("medicine_group", "nhomThuoc"), ("bid_invitation_code", "maTbmt"),
    ("procuring_entity_id", "maCdt"), ("procuring_entity_name", "tenCdtBmt"),
    ("selection_method", "bidForm"), ("result_posted_at", "ngayDangTaiKqlcnt"),
    ("decision_number", "soQuyetDinh"), ("decision_issued_at", "ngayBanHanhQuyetDinh"),
    ("bidder_count", "soNhaThauThamDu"), ("location", "diaDiem"),
)
_TRADITIONAL_MAPPING = _mapping(
    ("item_name", "tenDuocLieu"), ("used_part", "boPhanDung"), ("scientific_name", "tenKhoaHoc"),
    ("origin", "nguonGoc"), ("processing_method", "phuongPhapCheBien"),
    ("registration_or_import_permit_number", "gdklh_GPNK"), ("manufacturer", "tenCoSoSanXuat"),
    ("production_country", "nuocSanXuat"), ("packaging", "quyCachDongGoi"),
    ("unit", "donViTinh"), ("quantity", "soLuong"), ("winning_unit_price", "donGia"),
    ("winning_bidder_id", "winningCode"), ("winning_bidder_name", "winningName"),
    ("technical_group", "nhomTCKT"), ("bid_invitation_code", "maTbmt"),
    ("procuring_entity_id", "maCdt"), ("procuring_entity_name", "tenCdtBmt"),
    ("selection_method", "bidForm"), ("result_posted_at", "ngayDangTaiKqlcnt"),
    ("decision_number", "soQuyetDinh"), ("decision_issued_at", "ngayBanHanhQuyetDinh"),
    ("bidder_count", "soNhaThauThamDu"), ("location", "diaDiem"),
)


def _contract(
    key: str,
    label: str,
    group: str,
    source_tab: str,
    match_fields: tuple[str, ...],
    fixed: tuple[FilterSpec, ...],
    fields: tuple[str, ...],
    numeric: tuple[str, ...],
    mapping: tuple[FieldMapping, ...],
    slug: str,
    special_filters: tuple[str, ...] = (),
) -> SourceContract:
    return SourceContract(
        key=key, source_tab_label=label, data_group=group, source_tab=source_tab,
        type="HANG_HOA", tab=source_tab, match_fields=match_fields,
        fixed_filters=fixed, special_filters=special_filters, observed_source_fields=fields,
        known_numeric_fields=numeric,
        date_fields=("ngayDangTaiKqlcnt", "ngayBanHanhQuyetDinh"),
        canonical_mapping=mapping, fixture_slug=slug,
    )


SOURCE_CONTRACTS: dict[str, SourceContract] = {
    "goods_general": _contract(
        "goods_general", "Hàng hóa ngoài thuốc, thiết bị, vật tư y tế", "goods", "HANG_HOA",
        ("danh_muc_hang_hoa", "ma_hs", "xuat_xu", "ma_tbmt", "ky_ma_hieu", "nhan_hieu", "hang_san_xuat"),
        (_filter("type", "HANG_HOA"), _filter("tab", "HANG_HOA")), _GOODS_FIELDS,
        ("khoiLuongDouble", "donGiaDuThau"), _GOODS_MAPPING, "goods-general",
    ),
    "medical_devices": _contract(
        "medical_devices", "Thiết bị, vật tư y tế", "goods", "THIET_BI_VAT_TU_Y_TE",
        ("ten_thiet_bi", "ma_hs", "xuat_xu", "ma_tbmt", "ky_ma_hieu", "nhan_hieu", "hang_san_xuat"),
        (_filter("type", "HANG_HOA"), _filter("tab", "THIET_BI_VAT_TU_Y_TE")), _DEVICE_FIELDS,
        ("khoiLuongDouble", "donGia", "donGiaDuThau", "soNhaThauThamDu"), _DEVICE_MAPPING, "medical-devices",
    ),
    "medicine_generic": _contract(
        "medicine_generic", "Gói thầu thuốc Generic", "medicines", "THUOC_TAN_DUOC",
        ("ten_thuoc", "ten_hoat_chat", "ma_tbmt"),
        (_filter("medicines", "0"), _filter("type", "HANG_HOA"), _filter("tab", "THUOC_TAN_DUOC")),
        _MEDICINE_FIELDS, ("donGia", "soLuong", "soNhaThauThamDu"), _MEDICINE_MAPPING, "medicine-generic",
        ("medicines=[\"0\"]",),
    ),
    "medicine_originator": _contract(
        "medicine_originator", "Gói thầu thuốc biệt dược gốc", "medicines", "THUOC_TAN_DUOC",
        ("ten_thuoc", "ten_hoat_chat", "ma_tbmt"),
        (_filter("medicines", "1"), _filter("type", "HANG_HOA"), _filter("tab", "THUOC_TAN_DUOC")),
        _ORIGINATOR_FIELDS, ("donGia", "soLuong", "soNhaThauThamDu"), _MEDICINE_MAPPING, "medicine-originator",
        ("medicines=[\"1\"]",),
    ),
    "medicine_herbal": _contract(
        "medicine_herbal", "Gói thầu thuốc dược liệu", "medicines", "THUOC_TAN_DUOC",
        ("ten_thuoc", "ten_hoat_chat", "ma_tbmt"),
        (_filter("medicines", "2"), _filter("type", "HANG_HOA"), _filter("tab", "THUOC_TAN_DUOC")),
        _MEDICINE_FIELDS, ("donGia", "soLuong", "soNhaThauThamDu"), _MEDICINE_MAPPING, "medicine-herbal",
        ("medicines=[\"2\"]",),
    ),
    "herbal_material": _contract(
        "herbal_material", "Dược liệu", "traditional_medicine", "DUOC_LIEU",
        ("ten_duoc_lieu", "ten_khoa_hoc", "ten_san_pham", "ma_tbmt"),
        (_filter("medicine_type", 0, None), _filter("type", "HANG_HOA"), _filter("tab", "DUOC_LIEU")),
        _HERBAL_MATERIAL_FIELDS, ("donGia", "soLuong", "medicineType", "soNhaThauThamDu"),
        _TRADITIONAL_MAPPING, "herbal-material",
        ("medicine_type=[0,null] when official medicineType is 0",),
    ),
    "traditional_medicine": _contract(
        "traditional_medicine", "Vị thuốc cổ truyền", "traditional_medicine", "VI_THUOC_CO_TRUYEN",
        ("ten_duoc_lieu", "ten_khoa_hoc", "ten_san_pham", "ma_tbmt"),
        (_filter("medicine_type", 0, None), _filter("type", "HANG_HOA"), _filter("tab", "VI_THUOC_CO_TRUYEN")),
        _TRADITIONAL_FIELDS, ("donGia", "donGiaDuThau", "soLuong", "soNhaThauThamDu"),
        _mapping(
            ("item_name", "tenViThuocCoTruyen"), ("used_part", "boPhanDung"), ("scientific_name", "tenKhoaHoc"),
            ("origin", "nguonGoc"), ("processing_method", "phuongPhapCheBien"),
            ("registration_or_import_permit_number", "gdklh_GPNK"), ("manufacturer", "tenCoSoSanXuat"),
            ("production_country", "nuocSanXuat"), ("packaging", "quyCachDongGoi"), ("unit", "donViTinh"),
            ("quantity", "soLuong"), ("winning_unit_price", "donGia"), ("winning_bidder_id", "winningCode"),
            ("winning_bidder_name", "winningName"), ("technical_group", "nhomTCKT"),
            ("bid_invitation_code", "maTbmt"), ("procuring_entity_id", "maCdt"),
            ("procuring_entity_name", "tenCdtBmt"), ("selection_method", "bidForm"),
            ("result_posted_at", "ngayDangTaiKqlcnt"), ("decision_number", "soQuyetDinh"),
            ("decision_issued_at", "ngayBanHanhQuyetDinh"), ("bidder_count", "soNhaThauThamDu"),
            ("location", "diaDiem"),
        ), "traditional-medicine",
        ("medicine_type=[0,null] when official medicineType is 0",),
    ),
}


def get_contract(source_key: str) -> SourceContract:
    try:
        return SOURCE_CONTRACTS[source_key]
    except KeyError as exc:
        raise ValueError(f"unknown MSC source key: {source_key}") from exc
