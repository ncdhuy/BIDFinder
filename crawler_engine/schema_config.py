SCHEMAS = {
    "MEDICINE_STANDARD": {
        "description": "Gói thầu Thuốc",
        "table_name": "processed_medicines",
        "signature_columns": ["Tên thuốc", "Số lượng", "Đơn giá trúng thầu (VND)"],
        
        # CÁC CỘT BẮT BUỘC PHẢI CÓ 
        "mandatory_columns": [
            "Tên thuốc", 
            "Tên hoạt chất", 
            "Nồng độ, hàm lượng",
            "Đơn vị tính", 
            "Số lượng", 
            "Đơn giá trúng thầu (VND)"
        ],

        "db_mapping": {
            "Mã TBMT": "ma_tbmt",
            "so_qd_sanitized": "so_qd",          
            "version_code": "version",          
            "Mã phần/lô": "ma_phan_lo",
            "Tên thuốc": "ten_thuoc",
            "Tên hoạt chất": "ten_hoat_chat",
            "Nồng độ, hàm lượng": "nong_do_ham_luong",
            "Đường dùng": "duong_dung",
            "Dạng bào chế": "dang_bao_che",
            "Quy cách": "quy_cach",
            "Nhóm thuốc": "nhom_thuoc",
            "Hạn dùng (tuổi thọ)": "han_dung",
            "GĐKLH hoặc GPNK": "so_dk_gpnk",
            "Cơ sở sản xuất": "co_so_san_xuat",
            "Xuất xứ": "xuat_xu",
            "Đơn vị tính": "don_vi_tinh",
            "Số lượng": "so_luong",
            "Đơn giá trúng thầu (VND)": "don_gia_trung_thau",
            "Thành tiền (VND)": "thanh_tien",
            "Nhà thầu trúng thầu": "nha_thau_trung_thau",
        },

        "column_mapping": {
            "Tên hoạt chất/ Tên thành phần của thuốc": "Tên hoạt chất",
            "Nhóm TCKT": "Nhóm thuốc",
            "GĐKLH": "GĐKLH hoặc GPNK",
            "SĐK hoặc số GPNK": "GĐKLH hoặc GPNK",
            "SĐK/GPNK": "GĐKLH hoặc GPNK",
            "Đon giá trúng thầu": "Đơn giá trúng thầu (VND)",
            "Thành tiền": "Thành tiền (VND)",
            "Tên cơ sở sản xuất": "Cơ sở sản xuất",
            "Nước sản xuất": "Xuất xứ",
            "Mã phần lô": "Mã phần/lô"
        },

        "primary_merge_key": ["Mã phần/lô"],
        "fallback_merge_key": ["Tên thuốc", "Số lượng", "Đơn giá trúng thầu (VND)"],
        
        "output_columns": [
            "Mã phần/lô", "Tên thuốc", "Tên hoạt chất", "Nồng độ, hàm lượng",
            "Đường dùng", "Dạng bào chế", "Quy cách", "Nhóm thuốc", "Hạn dùng (tuổi thọ)",
            "GĐKLH hoặc GPNK", "Cơ sở sản xuất", "Xuất xứ", "Đơn vị tính", "Số lượng",
            "Đơn giá trúng thầu (VND)", "Thành tiền (VND)", "Nhà thầu trúng thầu"
        ],

        "db_indexes": [
            "ma_tbmt", 
            "so_qd",            
            "ten_thuoc", 
            "don_vi_tinh", 
            "so_luong", 
            "don_gia_trung_thau", 
            "thanh_tien", 
            "nha_thau_trung_thau", 
            "xuat_xu"
        ]
    },

    "GOODS_STANDARD": {
        "description": "Gói thầu Hàng hóa",
        "table_name": "processed_goods",
        "signature_columns": ["Tên hàng hóa"],

        "mandatory_columns": [
            "Tên hàng hóa",
            "Đơn vị tính",
            "Khối lượng",
            "Đơn giá trúng thầu (VND)"
        ],

        "db_mapping": {
            "Mã TBMT": "ma_tbmt",
            "so_qd_sanitized": "so_qd",           
            "version_code": "version",           
            "Nhà thầu trúng thầu": "nha_thau_trung_thau",
            "Mã phần/lô": "ma_phan_lo",
            "Tên hàng hóa": "ten_hang_hoa",
            "Ký mã hiệu": "ky_ma_hieu",
            "Nhãn hiệu": "nhan_hieu",
            "Năm sản xuất": "nam_san_xuat",
            "Xuất xứ": "xuat_xu",
            "Hãng sản xuất": "hang_san_xuat",
            "Tính năng kỹ thuật": "tinh_nang_ky_thuat",
            "Đơn vị tính": "don_vi_tinh",
            "Khối lượng": "khoi_luong",
            "Mã HS": "ma_hs",
            "Đơn giá trúng thầu (VND)": "don_gia_trung_thau",
            "Thành tiền (VND)": "thanh_tien"
        },

        "column_mapping": {
            "Cấu hình, tính năng kỹ thuật cơ bản": "Tính năng kỹ thuật",
            "Thông số kỹ thuật": "Tính năng kỹ thuật",
            "Danh mục hàng hóa": "Tên hàng hóa",
            "Đơn giá trúng thầu": "Đơn giá trúng thầu (VND)",
            "Đơn giá dự thầu (đã bao gồm thuế, phí, lệ phí (nếu có))": "Đơn giá trúng thầu (VND)",
            "Thành tiền đã bao gồm thuế, phí, lệ phí (nếu có))": "Thành tiền (VND)",
            "Ký mã hiệu, xuất xứ của sản phẩm": "Ký mã hiệu",
            "Mã phần (lô)": "Mã phần/lô"
        },

        "primary_merge_key": ["Mã phần/lô"],
        "fallback_merge_key": ["Tên hàng hóa", "Khối lượng", "Đơn giá trúng thầu (VND)"],

        "output_columns": [
            "Nhà thầu trúng thầu", "Mã phần/lô", "Tên hàng hóa", "Ký mã hiệu", "Nhãn hiệu",
            "Năm sản xuất", "Xuất xứ", "Hãng sản xuất", "Tính năng kỹ thuật",
            "Đơn vị tính", "Khối lượng", "Đơn giá trúng thầu (VND)", "Thành tiền (VND)"
        ],

        "db_indexes": [
            "ma_tbmt", 
            "so_qd",            
            "ten_hang_hoa", 
            "don_vi_tinh", 
            "khoi_luong", 
            "don_gia_trung_thau", 
            "thanh_tien", 
            "nha_thau_trung_thau", 
            "xuat_xu"
        ]
    }
}
