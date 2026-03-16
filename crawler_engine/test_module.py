import os
import re
import time
from collections import Counter

import pandas as pd
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()

BASE_DIR = os.getenv("BASE_DIR") or os.getcwd()
CHROME_PROFILE_PATH = os.getenv("CHROME_PROFILE_PATH")
CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH")
KEY = os.getenv("KEY", "").strip()
KEY_BATCHES = os.getenv("KEY_BATCHES", "").strip()
EXC_KEY = os.getenv("EXC_KEY", "").strip()
MAX_PAGES = None if (v := (os.getenv("MAX_PAGES") or "").strip().lower()) in ("", "none") else int(v)
ENABLE_KEYWORD_NGRAMS = str(os.getenv("ENABLE_KEYWORD_NGRAMS", "true")).strip().lower() in {"1", "true", "yes", "y", "on"}

if not CHROME_PROFILE_PATH or not CHROMEDRIVER_PATH:
    raise ValueError("Thiếu CHROME_PROFILE_PATH hoặc CHROMEDRIVER_PATH trong .env")


def parse_keyword_batches(raw_batches: str, fallback_key: str):
    if raw_batches:
        parts = re.split(r"\r?\n|\|\|", raw_batches)
        batches = [p.strip() for p in parts if p and p.strip()]
        if batches:
            return batches
    return [fallback_key] if fallback_key else []


SEARCH_KEYWORDS = parse_keyword_batches(KEY_BATCHES, KEY)
if not SEARCH_KEYWORDS:
    raise ValueError("Thiếu KEY hoặc KEY_BATCHES để test.")


options = webdriver.ChromeOptions()
options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")
options.add_argument("--log-level=3")
options.add_experimental_option("excludeSwitches", ["enable-logging"])
options.add_experimental_option("prefs", {
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True,
})

service = Service(executable_path=CHROMEDRIVER_PATH, log_output=os.devnull)
driver = webdriver.Chrome(service=service, options=options)
wait = WebDriverWait(driver, 20)


loai_tu_gian_giao_thau = [
    "kích thích", "môi trường", "nông nghiệp", "khuyến nông", "nông dân", "vườn", "thức ăn",
    "lúa", "cao su", "cây giống", "hạt giống", "phân bón", "diệt cỏ", "thuốc cỏ", "trừ cỏ", "thuốc sâu",
    "trừ sâu", "trừ bệnh", "rầy côn trùng", "phấn trắng", "đạo ôn", "chăn nuôi", "thủy sản", "thú y",
    "vật nuôi", "gia súc", "gia cầm", "chó", "mèo", "ruồi", "gà", "trâu", "bò", "vịt", "chuột", "cá",
    "muỗi", "mối", "lở mồm", "cúm gia cầm",
    "không phải là thuốc", "vị thuốc", "sữa",
    "thuốc y học cổ truyền", "thuốc cổ truyền", "đông y", "sinh học",
    "dây truyền", "tủ", "thuốc thử", "phân liều", "vòng", "que", "sắc", "stent", "test", "kít", "kit",
    "sản xuất", "cứu hỏa", "lao động", "công nghiệp", "bão", "lụt", "hàng hóa dịch vụ", "phần mềm",
    "quặng", "nhuộm", "văn phòng", "bảo quản", "bao đựng", "rác", "phủ thuốc", "thiết bị y tế dạng thuốc", "vật tư y tế dạng thuốc",
    "vật tư y tế tiêu hao dạng thuốc", "nghiên cứu",
    "thiết bị", "kiểm nghiệm", "mỹ thuật", "nhu yếu phẩm", "tài sản", "lương thực", "in ấn"
]

loai_chu_dau_tu = [
    ("nông", ["bệnh viện"]),
    ("nuôi", ["nuôi dưỡng"]),
    ("trồng", []),
    ("lâm nghiệp", []),
    ("kiểm lâm", []),
    ("cao su", []),
    ("xây dựng", [])
]

tu_khoa_luu_lai = [
    "generic", "biệt dược gốc", "bdg", "thuốc bổ sung", "bổ sung thuốc",
    "thực phẩm chức năng", "thực phẩm bảo vệ sức khỏe", "thực phẩm dinh dưỡng",
    "mỹ phẩm"
]


def select_keyword_match_mode(match_value: str):
    radio_xpath = f"//input[@type='radio' and @name='check-1' and @value='{match_value}']"
    radio = wait.until(EC.presence_of_element_located((By.XPATH, radio_xpath)))
    group = wait.until(EC.presence_of_element_located((By.XPATH, f"{radio_xpath}/ancestor::div[contains(@class,'check-radio-group')]")))

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", group)

    try:
        driver.execute_script("arguments[0].click();", group)
    except Exception:
        pass

    try:
        wait.until(lambda d: d.find_element(By.XPATH, radio_xpath).is_selected())
        return
    except TimeoutException:
        pass

    try:
        clickable_label = group.find_elements(By.TAG_NAME, "label")[-1]
        driver.execute_script("arguments[0].click();", clickable_label)
        wait.until(lambda d: d.find_element(By.XPATH, radio_xpath).is_selected())
        return
    except Exception:
        pass

    driver.execute_script(
        """
        const radio = arguments[0];
        radio.checked = true;
        radio.dispatchEvent(new Event('input', { bubbles: true }));
        radio.dispatchEvent(new Event('change', { bubbles: true }));
        radio.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        """,
        radio,
    )
    wait.until(lambda d: d.find_element(By.XPATH, radio_xpath).is_selected())


def setup_search_form(search_keyword: str):
    driver.get("https://muasamcong.mpi.gov.vn/web/guest/home")
    try:
        close_button = wait.until(EC.element_to_be_clickable((By.ID, "popup-close")))
        close_button.click()
    except TimeoutException:
        pass

    wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Tìm kiếm nâng cao')]"))).click()
    select_keyword_match_mode("any-1")
    time.sleep(0.5)

    input_khong_chua_tu = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@placeholder='Áp dụng cho tất cả các trường thông tin tìm kiếm']")))
    input_khong_chua_tu.clear()
    if EXC_KEY:
        input_khong_chua_tu.send_keys(EXC_KEY)

    input_tim_kiem = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@placeholder='Nhập số TBMT/Tên gói thầu (ví dụ: IB0123456789 hoặc Thiết bị)']")))
    input_tim_kiem.clear()
    input_tim_kiem.send_keys(search_keyword)

    wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@name='ck-investField' and @value='HH']"))).click()
    input()
    wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Tìm kiếm')]"))).click()
    time.sleep(1)

    wait.until(EC.element_to_be_clickable((By.XPATH, "//ul[contains(@class, 'nav-tabs')]//a[contains(text(),'Đã đóng thầu')]"))).click()
    time.sleep(1)
    wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'content__body__option')]//span[contains(normalize-space(),'Có nhà thầu trúng thầu')]"))).click()
    time.sleep(1)

    select_elem = wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(text(),'Hiển thị')]/select")))
    Select(select_elem).select_by_value("50")
    time.sleep(1.5)
    input()

def get_box_info(search_keyword: str):
    results = []
    try:
        boxes = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.content__body__left__item")))
    except TimeoutException:
        print("Không tìm thấy box gói thầu trên trang.")
        return results

    for box in boxes:
        try:
            code_text = box.find_element(By.CSS_SELECTOR, "p.content__body__left__item__infor__code").text.strip()
            ma_tbmt = code_text.split(":")[-1].strip().split("-")[0]
        except Exception:
            ma_tbmt = "N/A"

        try:
            name = box.find_element(By.XPATH, ".//h5[contains(@class, 'content__body__left__item__infor__contract__name')]").text.strip()
        except Exception:
            name = "N/A"

        try:
            chu_dau_tu = box.find_element(By.XPATH, ".//h6[contains(normalize-space(),'Chủ đầu tư')]/span").text.strip()
        except Exception:
            chu_dau_tu = "N/A"

        results.append({
            "Keyword crawl": search_keyword,
            "Mã TBMT": ma_tbmt,
            "Tên gói thầu": name,
            "Chủ đầu tư": chu_dau_tu,
        })
    return results


def scrape_pages(search_keyword: str, max_pages: int):
    all_info = []
    page = 1

    while True:
        print(f"🔹 [{search_keyword}] Đang lấy trang {page}...")
        all_info.extend(get_box_info(search_keyword))

        if max_pages and page >= max_pages:
            break

        try:
            next_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".el-pagination .btn-next:not(.is-disabled)")))
            next_button.click()
            page += 1
            time.sleep(2)
        except TimeoutException:
            print(f"✅ [{search_keyword}] Đã lấy hết trang khả dụng.")
            break

    return all_info


def is_luu_lai_theo_ten_goi_thau(ten_goi_thau):
    ten_thap = ten_goi_thau.lower()
    return any(re.search(rf"\b{re.escape(kw)}\b", ten_thap) for kw in tu_khoa_luu_lai)


def is_loai_chu_dau_tu(ten_chu_dau_tu):
    ten_thap = ten_chu_dau_tu.lower()
    for keyword, exclude_list in loai_chu_dau_tu:
        if re.search(rf"\b{re.escape(keyword)}\b", ten_thap):
            if any(re.search(rf"\b{re.escape(ex)}\b", ten_thap) for ex in exclude_list):
                continue
            return True
    return False


def is_loai_ten_goi_thau(ten_goi_thau):
    ten_thap = ten_goi_thau.lower()
    if any(re.search(rf"\b{re.escape(word)}\b", ten_thap) for word in loai_tu_gian_giao_thau):
        return True
    if re.search(r"\bnhà thuốc\b", ten_thap):
        matches = [m.start() for m in re.finditer(r"\bthuốc\b", ten_thap)]
        if len(matches) == 1:
            return True
    return False


def classify_records(records):
    for item in records:
        ten_goi_thau = item.get("Tên gói thầu", "").lower()
        ten_chu_dau_tu = item.get("Chủ đầu tư", "").lower()

        if is_luu_lai_theo_ten_goi_thau(ten_goi_thau):
            item["Kết quả lọc"] = "CHỌN"
            continue

        if is_loai_chu_dau_tu(ten_chu_dau_tu) or is_loai_ten_goi_thau(ten_goi_thau):
            item["Kết quả lọc"] = "LOẠI"
        else:
            item["Kết quả lọc"] = "CHỌN"
    return records


def tokenize(text: str):
    return re.findall(r"[0-9A-Za-zÀ-ỹ]+", str(text or "").lower())


def build_ngram_counter(records, n):
    counter = Counter()
    for item in records:
        tokens = tokenize(item.get("Tên gói thầu", ""))
        if len(tokens) < n:
            continue
        for i in range(len(tokens) - n + 1):
            gram = " ".join(tokens[i:i + n]).strip()
            if len(gram) >= 3:
                counter[gram] += 1
    return counter


def counter_to_df(counter: Counter, min_count=2):
    rows = [{"Cụm từ": key, "Số lần": val} for key, val in counter.most_common() if val >= min_count]
    return pd.DataFrame(rows)


def save_outputs(all_records):
    out_dir = os.path.join(BASE_DIR, "test_outputs")
    os.makedirs(out_dir, exist_ok=True)

    dedup_all = pd.DataFrame(all_records).drop_duplicates(subset=["Keyword crawl", "Mã TBMT", "Chủ đầu tư", "Tên gói thầu"])

    dedup_all.to_excel(os.path.join(out_dir, "all_results.xlsx"), index=False, engine="openpyxl")

    print(f"✅ Đã lưu all_results.xlsx: {len(dedup_all)} dòng")
    if ENABLE_KEYWORD_NGRAMS:
        with pd.ExcelWriter(os.path.join(out_dir, "keyword_ngrams.xlsx"), engine="openpyxl") as writer:
            counter_to_df(build_ngram_counter(all_records, 1)).to_excel(writer, sheet_name="all_1gram", index=False)
            counter_to_df(build_ngram_counter(all_records, 2)).to_excel(writer, sheet_name="all_2gram", index=False)
            counter_to_df(build_ngram_counter(all_records, 3)).to_excel(writer, sheet_name="all_3gram", index=False)
            counter_to_df(build_ngram_counter([r for r in all_records if r.get("Kết quả lọc") == "CHỌN"], 1)).to_excel(writer, sheet_name="chon_1gram", index=False)
            counter_to_df(build_ngram_counter([r for r in all_records if r.get("Kết quả lọc") == "CHỌN"], 2)).to_excel(writer, sheet_name="chon_2gram", index=False)
            counter_to_df(build_ngram_counter([r for r in all_records if r.get("Kết quả lọc") == "CHỌN"], 3)).to_excel(writer, sheet_name="chon_3gram", index=False)
            counter_to_df(build_ngram_counter([r for r in all_records if r.get("Kết quả lọc") == "LOẠI"], 1)).to_excel(writer, sheet_name="loai_1gram", index=False)
            counter_to_df(build_ngram_counter([r for r in all_records if r.get("Kết quả lọc") == "LOẠI"], 2)).to_excel(writer, sheet_name="loai_2gram", index=False)
            counter_to_df(build_ngram_counter([r for r in all_records if r.get("Kết quả lọc") == "LOẠI"], 3)).to_excel(writer, sheet_name="loai_3gram", index=False)
        print("✅ Đã lưu keyword_ngrams.xlsx để phân tích biến thể từ khóa.")
    else:
        print("ℹ️ Đã tắt phân tích keyword_ngrams theo cấu hình ENABLE_KEYWORD_NGRAMS.")


def main():
    all_records = []
    try:
        for keyword in SEARCH_KEYWORDS:
            print("=" * 60)
            print(f"Đang test keyword: {keyword}")
            print("=" * 60)
            setup_search_form(keyword)
            all_records.extend(scrape_pages(keyword, MAX_PAGES))

        all_records = classify_records(all_records)
        save_outputs(all_records)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
