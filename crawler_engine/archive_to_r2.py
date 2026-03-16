# archive_to_r2.py
import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

from storage_adapter import upload_file, build_r2_key, is_r2_key

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
LOCAL_RAW_ROOT = os.getenv("LOCAL_RAW_ROOT") or os.getenv("ROOT_DATA_DIR")

if not DATABASE_URL:
    raise ValueError("Thiếu biến môi trường DATABASE_URL trong file .env")

if not LOCAL_RAW_ROOT:
    raise ValueError("Thiếu biến môi trường LOCAL_RAW_ROOT hoặc ROOT_DATA_DIR trong file .env")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def archive_day(target_date: str, delete_local: bool = True):
    day_root = os.path.normpath(os.path.join(LOCAL_RAW_ROOT, target_date))
    latest_dir = os.path.normpath(os.path.join(day_root, "latest"))
    archive_dir = os.path.normpath(os.path.join(day_root, "archive"))

    if not os.path.exists(latest_dir) and not os.path.exists(archive_dir):
        print(f"❌ Không tìm thấy dữ liệu local cho ngày {target_date}")
        print(f"   latest:  {latest_dir}")
        print(f"   archive: {archive_dir}")
        return

    uploaded_count = 0
    skipped_count = 0
    failed_count = 0
    found_count = 0
    deleted_count = 0

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT ma_tbmt, so_qd, version, file_type, file_path
            FROM packages
            WHERE file_path IS NOT NULL
              AND file_path LIKE '%%' || %s || '%%'
        """, (target_date,))
        rows = cur.fetchall()

        for ma_tbmt, so_qd, version, file_type, file_path in rows:
            try:
                if not file_path:
                    continue

                if is_r2_key(file_path):
                    continue

                normalized_path = os.path.normpath(file_path)

                if not normalized_path.startswith(day_root):
                    continue

                found_count += 1

                if not os.path.exists(normalized_path):
                    print(f"⚠️ Skip vì file không tồn tại local: {normalized_path}")
                    skipped_count += 1
                    continue

                if normalized_path.startswith(archive_dir):
                    zone = "archive"
                elif normalized_path.startswith(latest_dir):
                    zone = "latest"
                else:
                    zone = "latest"

                filename = os.path.basename(normalized_path)
                r2_key = build_r2_key("raw_data", target_date, zone, filename)

                upload_file(normalized_path, r2_key)

                cur.execute("""
                    UPDATE packages
                    SET file_path = %s
                    WHERE ma_tbmt = %s
                      AND so_qd = %s
                      AND version = %s
                      AND file_type = %s
                      AND file_path = %s
                """, (r2_key, ma_tbmt, so_qd, version, file_type, file_path))

                if delete_local:
                    try:
                        os.remove(normalized_path)
                        deleted_count += 1
                    except Exception as e:
                        print(f"⚠️ Upload xong nhưng không xóa được local file: {normalized_path} | {e}")

                uploaded_count += 1

            except Exception as e:
                failed_count += 1
                print(f"❌ Lỗi archive file [{file_path}]: {e}")

        conn.commit()

    if found_count == 0:
        print(f"⚠️ Không tìm thấy record packages nào thuộc ngày {target_date}.")
        print("💡 Nghĩa là folder local có file nhưng DB packages chưa map tới các file đó.")
        return

    print(f"\n✅ Hoàn tất archive ngày {target_date}")
    print(f" - Found in DB: {found_count}")
    print(f" - Uploaded:    {uploaded_count}")
    print(f" - Deleted:     {deleted_count}")
    print(f" - Skipped:     {skipped_count}")
    print(f" - Failed:      {failed_count}")


if __name__ == "__main__":
    default_date = datetime.now().strftime("%Y%m%d")
    user_input = input(f"Nhập ngày YYYYMMDD [Enter = {default_date}]: ").strip()
    target_date = user_input if user_input else default_date
    archive_day(target_date, delete_local=True)
