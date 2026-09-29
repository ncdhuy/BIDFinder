# Tra cứu mã hoạt chất eLMIS

BIDFinder lưu mã crawl tại `crawler_engine/vss/download_vss_data.py` và dành `crawler_engine/vss_data/` cho dữ liệu eLMIS. Tab tra cứu dùng một collection Typesense local riêng (`vss_ingredient_lookup`), không dùng bảng Neon. Các tab BIDFinder khác giữ nguyên nguồn dữ liệu hiện tại.

## Chuyển dữ liệu cũ

Nguồn hiện tại: `D:\startup\app_vss\qlt_realtime`. Người vận hành chạy từ thư mục gốc BIDFinder:

```powershell
robocopy 'D:\startup\app_vss\qlt_realtime\downloads' '.\crawler_engine\vss_data\downloads' *.xml /E /Z /R:2 /W:2
Copy-Item -LiteralPath 'D:\startup\app_vss\qlt_realtime\combined.csv' -Destination '.\crawler_engine\vss_data\combined.csv'
Copy-Item -LiteralPath 'D:\startup\app_vss\qlt_realtime\crawl_manifest.csv' -Destination '.\crawler_engine\vss_data\crawl_manifest.csv'
```

Giữ nguyên cấu trúc `downloads/YYYY/MM/vss_export_YYYYMMDD.xml`. XML là nguồn đầy đủ hơn; `combined.csv` có thể dùng để khởi động nhanh. Chỉ chọn **một** nguồn khi nạp, vì nhập cả hai sẽ đếm trùng. Dữ liệu thô được Git bỏ qua.

## Cấu hình Typesense

API và lệnh import cần kết nối được tới **cùng một** Typesense. Cấu hình server API trong `apps/api/.env` và môi trường chạy lệnh import bằng `BIDFINDER_TYPESENSE_HOST`, `BIDFINDER_TYPESENSE_PORT`, `BIDFINDER_TYPESENSE_PROTOCOL`, `BIDFINDER_TYPESENSE_API_KEY`; có thể dùng các biến `TYPESENSE_*` tương ứng. Giá trị mặc định của host, port và protocol là `127.0.0.1`, `8108`, `http`. Không commit API key. Lệnh import cần key có quyền tạo collection, nhập document và cập nhật alias; API chỉ cần quyền đọc collection.

Nếu API chạy trên máy hoặc container khác, `127.0.0.1` trỏ về chính môi trường đó. Hãy đặt host Typesense mà API thực sự truy cập được. Tab này sẽ trả HTTP 503 cho đến khi Typesense hoạt động và alias đã được nạp.

## Crawl và nạp dữ liệu

Cài dependencies của `crawler_engine/requirements.txt`. Crawl ngày mới:

```powershell
rtk python crawler_engine/vss/download_vss_data.py --start-date 2026-09-30 --end-date 2026-09-30
```

Xem trước tổng số dòng và nhóm, không ghi Typesense:

```powershell
rtk python tools/import_vss_ingredients.py --raw-dir crawler_engine/vss_data/downloads
```

Sau khi kiểm tra dữ liệu và đích Typesense local, thêm `--apply` để nạp. Hoặc dùng `--csv crawler_engine/vss_data/combined.csv` thay cho `--raw-dir`. Mỗi lần nạp tạo collection mới; chỉ chuyển alias sau khi tất cả batch được nhận và số document khớp. Collection cũ vẫn được giữ để có thể phục hồi; người vận hành có thể dọn sau khi kiểm tra bản mới. Nạp lại từ toàn bộ nguồn khi XML thay đổi, không chỉ từ những file mới.

Mỗi document đại diện một tổ hợp `(ma, hoatchat, ten, sodk, duongdung, năm từ congbo)` và có `occurrences` là số dòng nguồn. Mã hoạt chất lưu dạng chuỗi để giữ nguyên `40.048`. Ngày trống hoặc sai có năm rỗng. Các điều kiện nhập kết hợp AND. Typesense lọc các trường văn bản theo từ, năm theo giá trị đầy đủ; cách này có thể khác tìm chuỗi con `ILIKE` trước đây. `total_records` là tổng `occurrences` sau lọc lấy từ numeric facet; tỷ lệ của mỗi dòng dựa trên tổng này. Bảng phân trang các tổ hợp, còn xuất Excel lấy toàn bộ tổ hợp đã lọc theo từng batch 250 dòng.
