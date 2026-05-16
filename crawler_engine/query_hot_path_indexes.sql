CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_medicines_qd_display_trgm
ON processed_medicines USING gin (qd_display gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_medicines_quy_cach_trgm
ON processed_medicines USING gin (quy_cach gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_medicines_so_dk_gpnk_trgm
ON processed_medicines USING gin (so_dk_gpnk gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_medicines_don_vi_tinh_trgm
ON processed_medicines USING gin (don_vi_tinh gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_goods_qd_display_trgm
ON processed_goods USING gin (qd_display gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_goods_ky_ma_hieu_trgm
ON processed_goods USING gin (ky_ma_hieu gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_goods_nhan_hieu_trgm
ON processed_goods USING gin (nhan_hieu gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_goods_mat_hang_du_thau_trgm
ON processed_goods USING gin (mat_hang_du_thau gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_goods_tinh_nang_ky_thuat_trgm
ON processed_goods USING gin (tinh_nang_ky_thuat gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_goods_don_vi_tinh_trgm
ON processed_goods USING gin (don_vi_tinh gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_metadata_approval_join_sort
ON package_metadata (ngay_phe_duyet_date DESC NULLS LAST, ma_tbmt, so_qd, version);

CREATE INDEX IF NOT EXISTS idx_metadata_validity_join
ON package_metadata (tinh_trang_hieu_luc, ma_tbmt, so_qd, version);
