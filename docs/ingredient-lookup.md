# Tra cứu mã hoạt chất eLMIS

BIDFinder sở hữu mã crawl trong `crawler_engine/vss/download_vss_data.py` và dữ liệu vận hành trong `crawler_engine/vss_data/`. Thư mục dữ liệu được Git bỏ qua; không đưa XML, CSV, manifest hay thông tin kết nối DB vào commit.

## Chuyển dữ liệu cũ (người vận hành thực hiện)

Nguồn hiện tại: `D:\startup\app_vss\qlt_realtime`. Từ PowerShell ở thư mục gốc BIDFinder:

```powershell
robocopy 'D:\startup\app_vss\qlt_realtime\downloads' '.\crawler_engine\vss_data\downloads' *.xml /E /Z /R:2 /W:2
Copy-Item -LiteralPath 'D:\startup\app_vss\qlt_realtime\combined.csv' -Destination '.\crawler_engine\vss_data\combined.csv'
Copy-Item -LiteralPath 'D:\startup\app_vss\qlt_realtime\crawl_manifest.csv' -Destination '.\crawler_engine\vss_data\crawl_manifest.csv'
```

Giữ nguyên cấu trúc `downloads/YYYY/MM/vss_export_YYYYMMDD.xml`. Hiện nguồn có khoảng 1.639 XML (~2,96 GB); `combined.csv` khoảng 318 MB. `processed_dates.csv` và các CSV/XLSX khác là dữ liệu lưu trữ tùy chọn, không cần cho tab này. Script crawl tự ánh xạ lại đường dẫn trong manifest cũ sang thư mục XML mới, không tiếp tục tham chiếu đường dẫn `app_vss`.

## Chạy và cập nhật dữ liệu

Sau khi cài dependencies của `crawler_engine/requirements.txt`, crawl ngày mới bằng:

```powershell
rtk python crawler_engine/vss/download_vss_data.py --start-date 2026-09-30 --end-date 2026-09-30
```

Script lưu XML gốc và manifest vào `crawler_engine/vss_data/`; `--build-excel` là tùy chọn. Tab tra cứu không cần bước xuất Excel hay chạy `preprocess_data.py` của project cũ. Các trường tra cứu có sẵn trong XML: `ma`, `hoatchat`, `ten`, `sodk`, `duongdung`, `congbo`.

Xem trước số dòng và số tổ hợp, không ghi DB (chọn **một** nguồn):

```powershell
rtk python tools/import_vss_ingredients.py --csv crawler_engine/vss_data/combined.csv
rtk python tools/import_vss_ingredients.py --raw-dir crawler_engine/vss_data/downloads
```

`combined.csv` cho phép khởi động nhanh với dữ liệu đã xử lý trước đây; nhập trực tiếp XML cho phạm vi lịch sử đầy đủ và các đợt crawl tiếp theo. Không chạy đồng thời cả hai nguồn vì sẽ đếm trùng. Sau khi kiểm tra đúng đích `DATABASE_URL`, thêm `--apply` vào lệnh được chọn để thay bảng `vss_ingredient_counts` trong một transaction. Lặp lại sau khi dữ liệu nguồn thay đổi. API trả HTTP 503 cho đến khi bảng được nạp.

Mỗi dòng bảng là một tổ hợp `(ma, hoatchat, ten, sodk, duongdung, năm từ congbo)` và số lần xuất hiện. Mã lưu dưới dạng `TEXT` để giữ nguyên `40.048`. Ngày trống hoặc không hợp lệ có năm `NULL`. API lọc chuỗi con không phân biệt hoa thường; 5 điều kiện kết hợp AND. Tỷ lệ dùng tổng dòng nguồn sau lọc. UI phân trang tổ hợp và xuất toàn bộ tổ hợp sau lọc thành `.xlsx`.
