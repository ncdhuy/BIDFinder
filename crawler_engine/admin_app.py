import streamlit as st
import pandas as pd
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import logging

# ==========================================
# CẤU HÌNH & KẾT NỐI DB
# ==========================================
st.set_page_config(page_title="BIDFinder Admin", layout="wide")
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Đảm bảo định dạng URL đúng chuẩn cho SQLAlchemy (postgresql:// thay vì postgres://)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Khởi tạo SQLAlchemy Engine (Pool manager tự động của SQLAlchemy)
# st.cache_resource đảm bảo engine chỉ được tạo 1 lần duy nhất trong suốt vòng đời app
@st.cache_resource
def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)

engine = get_engine()

st.title("🛠️ Hệ Thống Quản Trị Dữ Liệu Mua Sắm Công")

# TẠO MENU SIDEBAR
tab1, tab2 = st.tabs(["📋 Quản lý Lỗi (Anomalies)", "🔗 Cấu hình QĐ (Relations)"])

# ==========================================
# TAB 1: SCAN ANOMALIES MANAGER
# ==========================================
with tab1:
    st.header("Danh sách gói thầu cần kiểm tra")
    
    # Đọc dữ liệu an toàn qua engine
    df_anomalies = pd.read_sql("""
        SELECT id, scan_date, ma_tbmt, so_qd, version, issue_type, priority, files_involved, status, details 
        FROM scan_anomalies 
        WHERE status = 'PENDING'
        ORDER BY priority, scan_date DESC
    """, con=engine)

    if df_anomalies.empty:
        st.success("🎉 Tuyệt vời! Không có bất thường nào đang Pending.")
    else:
        issue_options = ["Tất cả"] + sorted(df_anomalies["issue_type"].dropna().unique().tolist())
        selected_issue = st.selectbox("Lọc theo loại lỗi:", issue_options)

        if selected_issue != "Tất cả":
            df_anomalies = df_anomalies[df_anomalies["issue_type"] == selected_issue].copy()

        st.warning(f"⚠️ Đang có {len(df_anomalies)} lỗi cần xử lý.")
        # Hiển thị bảng dữ liệu 
        st.dataframe(df_anomalies, hide_index=True)
        
        # Tool thao tác nhanh
        st.subheader("Đánh dấu đã xử lý")
        col1, col2 = st.columns([3, 1])
        with col1:
            selected_ids = st.multiselect("Chọn ID lỗi đã xử lý xong:", df_anomalies['id'].tolist())
        with col2:
            st.write("") # Căn lề
            st.write("")
            if st.button("✅ Mark as PROCESSED", type="primary"):
                if selected_ids:
                    # engine.begin() tự động commit khi thoát khối with
                    with engine.begin() as conn:
                        query = text("""
                            UPDATE scan_anomalies 
                            SET status = 'PROCESSED' 
                            WHERE id IN :ids
                        """)
                        conn.execute(query, {"ids": tuple(selected_ids)})
                        
                    st.success("Đã cập nhật trạng thái thành công!")
                    st.rerun()

# ==========================================
# TAB 2: QD RELATIONS MANAGER
# ==========================================
with tab2:
    st.header("Gán quan hệ Quyết Định (Gốc - Điều Chỉnh - Thay Thế)")
    
    df_multi = pd.read_sql("""
        SELECT DISTINCT ma_tbmt
        FROM scan_anomalies
        WHERE issue_type = 'Multi-QD' AND status = 'PENDING'
    """, con=engine)
    multi_tbmts = df_multi['ma_tbmt'].tolist() if not df_multi.empty else []
    
    col_a, col_b = st.columns([1, 2])
    with col_a:
        tbmt_input = st.selectbox("1. Chọn TBMT bị Multi-QD (Hoặc gõ TBMT tùy ý):", [""] + multi_tbmts)
        custom_tbmt = st.text_input("Hoặc nhập mã TBMT thủ công:")
        target_tbmt = custom_tbmt if custom_tbmt else tbmt_input

    if target_tbmt:
        st.write(f"**2. Cấu hình QĐ cho TBMT: {target_tbmt}**")
        
        # Join data lấy số QĐ đang lưu ở DB
        query = text("""
            SELECT 
                p.so_qd, p.version, 
                COALESCE(r.so_qd_original, p.so_qd) as so_qd_original,
                COALESCE(r.relation_type, 'INDEPENDENT') as relation_type,
                COALESCE(r.note, '') as note
            FROM packages p
            LEFT JOIN qd_relations r 
              ON p.ma_tbmt = r.ma_tbmt AND p.so_qd = r.so_qd AND p.version = r.version
            WHERE p.ma_tbmt = :tbmt AND p.is_latest = 1
            ORDER BY p.so_qd, p.version
        """)
        
        df_qd = pd.read_sql(query, con=engine, params={"tbmt": target_tbmt})
            
        if df_qd.empty:
            st.error("Không tìm thấy dữ liệu package nào cho TBMT này.")
        else:
            st.info("💡 **Hướng dẫn:** Chỉnh sửa trực tiếp trên bảng như Excel. Sửa cột `so_qd_original` và `relation_type`.")
            
            edited_df = st.data_editor(
                df_qd,
                column_config={
                    "so_qd": st.column_config.TextColumn("QĐ hiện tại (Raw)", disabled=True),
                    "version": st.column_config.TextColumn("Version", disabled=True),
                    "so_qd_original": st.column_config.TextColumn("QĐ Gốc (Sửa tay)"),
                    "relation_type": st.column_config.SelectboxColumn(
                        "Loại quan hệ",
                        help="BASE: QĐ gốc, ADJUSTMENT: Vá một phần, REPLACEMENT: Thay thế hoàn toàn, INDEPENDENT: Độc lập",
                        options=["BASE", "ADJUSTMENT", "REPLACEMENT", "INDEPENDENT"],
                        required=True
                    ),
                    "note": st.column_config.TextColumn("Ghi chú")
                },
                hide_index=True
            )
            
            if st.button("💾 Lưu cấu hình QĐ", type="primary"):
                # Dùng engine.begin() để đảm bảo nếu lỗi 1 dòng thì rollback toàn bộ, không bị data rác
                with engine.begin() as conn:
                    upsert_query = text("""
                        INSERT INTO qd_relations (ma_tbmt, so_qd, version, so_qd_original, relation_type, note, updated_at)
                        VALUES (:ma_tbmt, :so_qd, :version, :so_qd_original, :relation_type, :note, NOW())
                        ON CONFLICT (ma_tbmt, so_qd, version) 
                        DO UPDATE SET 
                            so_qd_original = EXCLUDED.so_qd_original,
                            relation_type = EXCLUDED.relation_type,
                            note = EXCLUDED.note,
                            updated_at = EXCLUDED.updated_at
                    """)
                    
                    for _, row in edited_df.iterrows():
                        conn.execute(upsert_query, {
                            "ma_tbmt": target_tbmt,
                            "so_qd": row['so_qd'],
                            "version": row['version'],
                            "so_qd_original": row['so_qd_original'],
                            "relation_type": row['relation_type'],
                            "note": row['note']
                        })
                st.success("✅ Đã lưu cấu hình QĐ vào Database!")
