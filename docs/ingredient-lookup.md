# Tra cứu mã hoạt chất

Nguồn: `D:/startup/app_vss/qlt_realtime/combined.csv`, được tạo bởi `download_vss_data.py` của dự án `app_vss`. Các cột dùng cho tra cứu là `ma`, `hoatchat`, `ten`, `sodk`, `duongdung`, `congbo`. Không dùng `processed_medicines` của BIDFinder: `ma_thuoc` trong bảng đó là mã thuốc, không phải mã hoạt chất eLMIS.

Chạy xem trước số dòng nguồn và số tổ hợp (không ghi DB):

```powershell
rtk python tools/import_vss_ingredients.py --csv D:/startup/app_vss/qlt_realtime/combined.csv
```

Sau khi kiểm tra đúng đích `DATABASE_URL`, nạp bảng tra cứu:

```powershell
rtk python tools/import_vss_ingredients.py --csv D:/startup/app_vss/qlt_realtime/combined.csv --apply
```

Lệnh nạp gom các dòng theo `(ma, hoatchat, ten, sodk, duongdung, năm từ congbo)` và lưu số lần xuất hiện. Nó tạo bảng nếu thiếu, chuẩn bị dữ liệu trong bảng tạm rồi thay toàn bộ bảng tra cứu trong một transaction. Chạy lại sau khi CSV nguồn được cập nhật. Mã hoạt chất lưu dưới dạng `TEXT` để giữ các giá trị như `40.048` nguyên vẹn. Ngày trống hoặc không hợp lệ có năm `NULL`.

API `/api/ingredient-lookup` lọc chuỗi con không phân biệt hoa thường. Năm điều kiện kết hợp AND. API trả tổng số tổ hợp, tổng số dòng nguồn sau lọc, số lần xuất hiện lớn nhất, và một trang kết quả đã gom. UI xuất toàn bộ tổ hợp sau lọc thành `.xlsx` bằng thư viện XLSX hiện có. Khi chưa nạp bảng, API trả HTTP 503 để UI hiển thị lỗi cấu hình dữ liệu.
