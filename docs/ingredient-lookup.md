# Tra cứu mã hoạt chất eLMIS

BIDFinder lưu mã crawl tại `crawler_engine/vss/download_vss_data.py` và dành `crawler_engine/vss_data/` cho dữ liệu eLMIS. Tab tra cứu dùng một collection Typesense local riêng (`vss_ingredient_lookup`), không dùng bảng Neon. Các tab BIDFinder khác giữ nguyên nguồn dữ liệu hiện tại.

## Chuyển dữ liệu cũ

Nguồn hiện tại: `D:\startup\app_vss\qlt_realtime`. Người vận hành chạy từ thư mục gốc BIDFinder:

```powershell
robocopy 'D:\startup\app_vss\qlt_realtime\downloads' '.\crawler_engine\vss_data\downloads' *.xml /E /Z /R:2 /W:2
Copy-Item -LiteralPath 'D:\startup\app_vss\qlt_realtime\crawl_manifest.csv' -Destination '.\crawler_engine\vss_data\crawl_manifest.csv'
```

Giữ nguyên cấu trúc `downloads/YYYY/MM/vss_export_YYYYMMDD.xml`. XML là nguồn duy nhất để nạp Typesense. Dữ liệu thô được Git bỏ qua; file CSV cũ không tham gia luồng cập nhật và không cần xóa.

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

Sau khi kiểm tra dữ liệu và đích Typesense local, thêm `--apply` để nạp. Mỗi lần nạp tạo collection mới từ toàn bộ XML; chỉ chuyển alias sau khi tất cả batch được nhận và số document khớp. Collection cũ vẫn được giữ để có thể phục hồi.

## Cập nhật hằng ngày

Timer WSL `bidfinder-vss.timer` chạy **17:00 mỗi ngày, giờ Việt Nam**. Service dùng mã và dữ liệu XML trong checkout BIDFinder trên máy local; không dùng dữ liệu trong release production vì dữ liệu thô không được đưa vào Git. Mỗi lần chạy:

1. Crawl bù các ngày chưa được xuất bản và tải lại ba ngày gần nhất để bắt thay đổi muộn.
2. Kiểm tra manifest và file XML của từng ngày vừa crawl. Nếu thiếu hoặc lỗi, giữ nguyên alias Typesense đang phục vụ.
3. Gom nhóm toàn bộ XML, nạp collection mới, kiểm tra số document, rồi chuyển alias `vss_ingredient_lookup`.
4. Lưu `crawler_engine/vss_data/vss_refresh_status.json` và giữ ba phiên bản collection mới nhất để có đường quay lại.

Xem kế hoạch ngày chạy tiếp theo mà không crawl hay ghi Typesense:

```powershell
rtk python tools/update_vss_ingredients.py --plan
```

Trong WSL, kiểm tra lịch và log bằng `systemctl --user status bidfinder-vss.timer` và `journalctl --user-unit=bidfinder-vss.service -n 100`. Timer được cài cùng các unit BIDFinder qua `bidfinder-install.sh install` hoặc `bidfinder-prod-deploy.sh deploy`.

Mỗi document đại diện một tổ hợp `(ma, hoatchat, ten, sodk, duongdung, năm từ congbo)` và có `occurrences` là số dòng nguồn. Mã hoạt chất lưu dạng chuỗi để giữ nguyên `40.048`. Ngày trống hoặc sai có năm rỗng. API đọc collection Typesense vào bộ nhớ khi có lượt tra cứu đầu tiên, rồi lọc chuỗi con không phân biệt hoa thường như `ILIKE '%...%'`; khoảng trắng liên tiếp được chuẩn hóa khi so khớp. Năm trường kết hợp AND, kể cả năm công bố. Bộ nhớ tra cứu được nạp lại khi alias trỏ sang collection mới. Gợi ý lấy từ cùng bộ dữ liệu, có xét các điều kiện đã nhập ở ô khác. `total_records` là tổng `occurrences` của các tổ hợp sau lọc; tỷ lệ của mỗi dòng dựa trên tổng này. Bảng phân trang các tổ hợp, còn xuất Excel lấy toàn bộ tổ hợp đã lọc theo từng batch 250 dòng.
