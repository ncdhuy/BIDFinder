import os
import psycopg2
from dotenv import load_dotenv

# Load biến môi trường từ file .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ Thiếu biến môi trường DATABASE_URL.")

class DatabaseMigrator:
    def __init__(self):
        print("🔄 Đang kết nối tới PostgreSQL...")
        self.conn = psycopg2.connect(DATABASE_URL)
        self.cursor = self.conn.cursor()

    def migrate(self):
        try:
            print("🚀 Bắt đầu khởi tạo các bảng (Tables)...")

            # 1. Bảng Packages (Quản lý file gốc tải về)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS packages (
                    ma_tbmt TEXT,
                    so_qd TEXT,
                    version TEXT DEFAULT '00',
                    file_type TEXT,
                    file_path TEXT,
                    num_cols INTEGER,
                    crawled_at TIMESTAMP,
                    status TEXT,
                    is_latest INTEGER DEFAULT 1,
                    PRIMARY KEY (ma_tbmt, so_qd, file_type, version)
                )
            """)

            # 2. Bảng Scan Logs (Lịch sử crawl)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS scan_logs (
                    id SERIAL PRIMARY KEY,
                    run_id INTEGER,
                    ma_tbmt TEXT,
                    so_qd TEXT,
                    version TEXT,
                    action_type TEXT,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. Bảng Metadata (Chứa thông tin thẻ meta HTML)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS package_metadata (
                    ma_tbmt TEXT,
                    so_qd TEXT,
                    version TEXT,
                                
                    -- Thông tin chung
                    ngay_dang_tai TEXT,
                    trang_thai_dang_tai_kq TEXT,
                    chu_dau_tu TEXT,
                    ten_goi_thau TEXT,
                    linh_vuc TEXT,
                    
                    -- Hình thức đấu thầu
                    hinh_thuc_lcnt TEXT,
                    phuong_thuc_lcnt TEXT,
                    dau_thau_qua_mang TEXT,
                    trong_nuoc_quoc_te TEXT,
                    
                    -- Giá trị
                    gia_goi_thau TEXT,
                    gia_du_toan TEXT,
                    
                    -- Quyết định & Phê duyệt
                    ngay_phe_duyet TEXT,
                    ngay_phe_duyet_date DATE,
                    trang_thai_phe_duyet TEXT,
                    co_quan_phe_duyet TEXT,
                    
                    -- Hợp đồng & Thực hiện
                    loai_hop_dong TEXT,
                    thoi_gian_thuc_hien TEXT,
                    ket_qua_dau_thau TEXT,
                    
                    -- Khác
                    dia_diem TEXT,
                    cach_thuc_tai_ve TEXT,
                    updated_at TIMESTAMP,
                    tinh_trang_hieu_luc TEXT,
                    ngay_het_hieu_luc DATE,
                                
                    PRIMARY KEY (ma_tbmt, so_qd, version)
                )
            """)
            self.cursor.execute("""
                ALTER TABLE package_metadata
                ADD COLUMN IF NOT EXISTS ngay_phe_duyet_date DATE
            """)

            # 4. Bảng Run Sessions
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS run_sessions (
                    id SERIAL PRIMARY KEY,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    duration_seconds INTEGER,
                    boxes_selected INTEGER
                )
            """)

            # 5. Bảng Dữ liệu Đã Xử Lý (Thuốc)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_medicines (
                    id SERIAL PRIMARY KEY,
                    ma_tbmt TEXT,
                    so_qd TEXT,
                    qd_display TEXT,
                    version TEXT,
                    ma_phan_lo TEXT,
                    ma_thuoc TEXT,
                    ten_thuoc TEXT,
                    ten_hoat_chat TEXT,
                    nong_do_ham_luong TEXT,
                    duong_dung TEXT,
                    dang_bao_che TEXT,
                    quy_cach TEXT,
                    nhom_thuoc TEXT,
                    han_dung TEXT,
                    so_dk_gpnk TEXT,
                    co_so_san_xuat TEXT,
                    xuat_xu TEXT,
                    don_vi_tinh TEXT,
                    so_luong NUMERIC,
                    don_gia_trung_thau NUMERIC,
                    thanh_tien NUMERIC,
                    nha_thau_trung_thau TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 6. Bảng Dữ liệu Đã Xử Lý (Hàng hóa)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_goods (
                    id SERIAL PRIMARY KEY,
                    ma_tbmt TEXT,
                    so_qd TEXT,
                    qd_display TEXT,
                    version TEXT,
                    ma_phan_lo TEXT,
                    ten_phan_lo TEXT,
                    nha_thau_trung_thau TEXT,
                    danh_muc_hang_hoa TEXT,
                    ky_ma_hieu TEXT,
                    nhan_hieu TEXT,
                    hang_san_xuat TEXT,
                    mat_hang_du_thau TEXT,
                    don_vi_tinh TEXT,
                    khoi_luong NUMERIC,
                    xuat_xu TEXT,
                    nam_san_xuat TEXT,
                    tinh_nang_ky_thuat TEXT,
                    ky_ma_hieu_hash TEXT GENERATED ALWAYS AS (md5(COALESCE(ky_ma_hieu, ''))) STORED,
                    nhan_hieu_hash TEXT GENERATED ALWAYS AS (md5(COALESCE(nhan_hieu, ''))) STORED,
                    tinh_nang_ky_thuat_hash TEXT GENERATED ALWAYS AS (md5(COALESCE(tinh_nang_ky_thuat, ''))) STORED,
                    don_gia_trung_thau NUMERIC,
                    thanh_tien NUMERIC,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 7. Bảng Quản lý Lỗi (Anomalies)
            self.cursor.execute("""
                ALTER TABLE processed_medicines
                ADD COLUMN IF NOT EXISTS qd_display TEXT
            """)
            self.cursor.execute("""
                ALTER TABLE processed_medicines
                ADD COLUMN IF NOT EXISTS ma_thuoc TEXT
            """)
            self.cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints
                        WHERE table_name = 'processed_medicines'
                          AND constraint_name = 'uq_medicines'
                    ) THEN
                        ALTER TABLE processed_medicines DROP CONSTRAINT uq_medicines;
                    END IF;
                END $$;
            """)
            self.cursor.execute("""
                ALTER TABLE processed_goods
                ADD COLUMN IF NOT EXISTS qd_display TEXT
            """)
            self.cursor.execute("""
                ALTER TABLE processed_goods
                ADD COLUMN IF NOT EXISTS ky_ma_hieu_hash TEXT GENERATED ALWAYS AS (md5(COALESCE(ky_ma_hieu, ''))) STORED
            """)
            self.cursor.execute("""
                ALTER TABLE processed_goods
                ADD COLUMN IF NOT EXISTS nhan_hieu_hash TEXT GENERATED ALWAYS AS (md5(COALESCE(nhan_hieu, ''))) STORED
            """)
            self.cursor.execute("""
                ALTER TABLE processed_goods
                ADD COLUMN IF NOT EXISTS tinh_nang_ky_thuat_hash TEXT GENERATED ALWAYS AS (md5(COALESCE(tinh_nang_ky_thuat, ''))) STORED
            """)
            self.cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints
                        WHERE table_name = 'processed_goods'
                          AND constraint_name = 'uq_goods'
                    ) THEN
                        ALTER TABLE processed_goods DROP CONSTRAINT uq_goods;
                    END IF;
                END $$;
            """)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_duplicate_flags (
                    id SERIAL PRIMARY KEY,
                    dataset_scope TEXT NOT NULL,
                    processed_row_id INTEGER NOT NULL,
                    ma_tbmt TEXT NOT NULL,
                    so_qd TEXT NOT NULL,
                    version TEXT NOT NULL,
                    duplicate_key TEXT NOT NULL,
                    duplicate_count INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_processed_duplicate_flag UNIQUE (dataset_scope, processed_row_id)
                )
            """)
            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_processed_duplicate_flags_unit
                ON processed_duplicate_flags (dataset_scope, ma_tbmt, so_qd, version)
            """)
            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_processed_duplicate_flags_row
                ON processed_duplicate_flags (dataset_scope, processed_row_id)
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS scan_anomalies (
                    id SERIAL PRIMARY KEY,
                    scan_date TEXT,
                    ma_tbmt TEXT,
                    so_qd TEXT,
                    version TEXT,
                    issue_type TEXT,
                    priority TEXT,
                    details TEXT,
                    files_involved TEXT,
                    status TEXT DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                
                    CONSTRAINT unique_scan_anomaly UNIQUE(scan_date, ma_tbmt, so_qd, version, issue_type)
                )
            """)

            self.cursor.execute("""
                ALTER TABLE scan_anomalies
                ADD COLUMN IF NOT EXISTS so_qd TEXT
            """)
            self.cursor.execute("""
                ALTER TABLE scan_anomalies
                ADD COLUMN IF NOT EXISTS version TEXT
            """)

            self.cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints
                        WHERE table_name = 'scan_anomalies'
                          AND constraint_name = 'unique_scan_anomaly'
                    ) THEN
                        ALTER TABLE scan_anomalies DROP CONSTRAINT unique_scan_anomaly;
                    END IF;
                END $$;
            """)
            self.cursor.execute("""
                ALTER TABLE scan_anomalies
                ADD CONSTRAINT unique_scan_anomaly
                UNIQUE (scan_date, ma_tbmt, so_qd, version, issue_type)
            """)

            # 8. Bảng Manifest (Kiểm duyệt Data)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_manifest (
                    id SERIAL PRIMARY KEY,
                    manifest_date TEXT,
                    ma_tbmt TEXT,
                    so_qd TEXT,
                    version TEXT, 
                    filename TEXT,
                    schema_type TEXT,
                    full_path TEXT,
                    file_size_kb NUMERIC,
                    status TEXT DEFAULT 'READY',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    CONSTRAINT uq_manifest UNIQUE(manifest_date, filename)
                )
            """)
            
            # 9. Bảng audit issue từ manifest
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS manifest_issues (
                    id SERIAL PRIMARY KEY,
                    issue_date TEXT NOT NULL,
                    ma_tbmt TEXT NOT NULL,
                    so_qd TEXT NOT NULL,
                    version TEXT NOT NULL,
                    filename TEXT,
                    issue_type TEXT NOT NULL,
                    issue_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    CONSTRAINT uq_manifest_issues UNIQUE(issue_date, ma_tbmt, so_qd, version, issue_type)
                )
            """)

            # 10. Bảng tác vụ xử lý có người tham gia (OCR / MANUAL)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS human_task_queue (
                    id SERIAL PRIMARY KEY,
                    work_date TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    ma_tbmt TEXT NOT NULL,
                    so_qd TEXT NOT NULL,
                    version TEXT NOT NULL,
                    source_filename TEXT,
                    source_path TEXT,
                    source_files_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    workspace_source_dir TEXT,
                    workspace_result_dir TEXT,
                    expected_output_filename TEXT,
                    issue_reason TEXT,
                    status TEXT DEFAULT 'PENDING_EXPORT',
                    validation_message TEXT,
                    result_filename TEXT,
                    import_attempts INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    CONSTRAINT uq_human_task UNIQUE(work_date, task_type, ma_tbmt, so_qd, version)
                )
            """)

            # 11. Bảng facts nhà thầu trúng thầu lấy từ web detail
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS web_winner_facts (
                    ma_tbmt TEXT NOT NULL,
                    so_qd TEXT NOT NULL,
                    version TEXT NOT NULL,
                    capture_status TEXT NOT NULL,
                    only_winner_name TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    PRIMARY KEY (ma_tbmt, so_qd, version)
                )
            """)
            self.cursor.execute("""
                ALTER TABLE web_winner_facts
                DROP COLUMN IF EXISTS winner_count,
                DROP COLUMN IF EXISTS winner_names_json,
                DROP COLUMN IF EXISTS capture_note,
                DROP COLUMN IF EXISTS created_at
            """)
            self.cursor.execute("""
                DROP INDEX IF EXISTS idx_web_winner_facts_status
            """)

            # 12. Bảng quan hệ QĐ
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS qd_relations (
                    ma_tbmt      TEXT NOT NULL,
                    so_qd        TEXT NOT NULL,   -- QĐ hiện tại (gốc hoặc điều chỉnh)
                    version      TEXT NOT NULL,   -- version crawl, vẫn giữ như cũ
                    so_qd_original TEXT NOT NULL, -- QĐ gốc (theo bạn gán tay, đổi từ qd_original thành so_qd_original cho đồng bộ)
                    relation_type TEXT NOT NULL,  -- 'BASE' | 'ADJUSTMENT' | 'INDEPENDENT'
                    note         TEXT,
                    updated_at   TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (ma_tbmt, so_qd, version)
                )
            """)

            # 13. Kích hoạt extension hỗ trợ tìm kiếm chuỗi con siêu tốc
            self.cursor.execute("""
                CREATE EXTENSION IF NOT EXISTS pg_trgm;
            """)

            # 14. Tạo GIN Index cho các cột cần làm autocomplete
            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_medicines_join_keys
                ON processed_medicines (ma_tbmt, so_qd, version);
                CREATE INDEX IF NOT EXISTS idx_goods_join_keys
                ON processed_goods (ma_tbmt, so_qd, version);
                CREATE INDEX IF NOT EXISTS idx_medicines_ten_thuoc_trgm ON processed_medicines USING gin (ten_thuoc gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_medicines_ten_hoat_chat_trgm ON processed_medicines USING gin (ten_hoat_chat gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_medicines_nong_do_ham_luong_trgm ON processed_medicines USING gin (nong_do_ham_luong gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_medicines_duong_dung_trgm ON processed_medicines USING gin (duong_dung gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_medicines_dang_bao_che_trgm ON processed_medicines USING gin (dang_bao_che gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_medicines_nhom_thuoc_trgm ON processed_medicines USING gin (nhom_thuoc gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_medicines_co_so_san_xuat_trgm ON processed_medicines USING gin (co_so_san_xuat gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_medicines_xuat_xu_trgm ON processed_medicines USING gin (xuat_xu gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_medicines_nha_thau_trung_thau_trgm ON processed_medicines USING gin (nha_thau_trung_thau gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_goods_danh_muc_hang_hoa_trgm ON processed_goods USING gin (danh_muc_hang_hoa gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_goods_ten_phan_lo_trgm ON processed_goods USING gin (ten_phan_lo gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_goods_hang_san_xuat_trgm ON processed_goods USING gin (hang_san_xuat gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_goods_xuat_xu_trgm ON processed_goods USING gin (xuat_xu gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_goods_nha_thau_trung_thau_trgm ON processed_goods USING gin (nha_thau_trung_thau gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_goods_search_blob_trgm
                ON processed_goods
                USING gin (((
                    COALESCE(ten_phan_lo, '') || ' | ' ||
                    COALESCE(danh_muc_hang_hoa, '') || ' | ' ||
                    COALESCE(ky_ma_hieu, '') || ' | ' ||
                    COALESCE(nhan_hieu, '') || ' | ' ||
                    COALESCE(mat_hang_du_thau, '') || ' | ' ||
                    COALESCE(tinh_nang_ky_thuat, '')
                )) gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_metadata_chu_dau_tu_trgm ON package_metadata USING gin (chu_dau_tu gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_metadata_hinh_thuc_lcnt ON package_metadata (hinh_thuc_lcnt);
                CREATE INDEX IF NOT EXISTS idx_metadata_dia_diem ON package_metadata (dia_diem);
                CREATE INDEX IF NOT EXISTS idx_metadata_tinh_trang_hieu_luc ON package_metadata (tinh_trang_hieu_luc);
                CREATE INDEX IF NOT EXISTS idx_metadata_ngay_phe_duyet_date ON package_metadata (ngay_phe_duyet_date);
                CREATE INDEX IF NOT EXISTS idx_human_task_queue_lookup ON human_task_queue (work_date, task_type, status);
                CREATE INDEX IF NOT EXISTS idx_web_winner_facts_status ON web_winner_facts (capture_status);
            """)

            self.conn.commit()
            print("✅ Đã khởi tạo thành công cấu trúc Database chuẩn Enterprise trên PostgreSQL.")

        except Exception as e:
            print(f"❌ Lỗi khi khởi tạo Database: {e}")
            self.conn.rollback()
        finally:
            self.cursor.close()
            self.conn.close()

if __name__ == "__main__":
    print("="*60)
    print("      DATABASE MIGRATION (POSTGRESQL / NEON DB)")
    print("="*60)
    migrator = DatabaseMigrator()
    migrator.migrate()
