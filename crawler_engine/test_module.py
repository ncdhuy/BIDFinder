import logging
import os
import re
import time
from collections import Counter

import pandas as pd
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    SessionNotCreatedException,
    TimeoutException,
)
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, ".env")
load_dotenv(ENV_PATH)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _get_env_int(name, default=None):
    raw = os.getenv(name)
    if raw is None:
        return default

    raw_clean = str(raw).strip()
    if raw_clean == "" or raw_clean.lower() in {"none", "null"}:
        return default

    try:
        return int(raw_clean)
    except ValueError as error:
        raise ValueError(f"Biến môi trường {name} phải là số nguyên, giá trị hiện tại: {raw}") from error


def _get_env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


BASE_DIR = os.getenv("BASE_DIR") or SCRIPT_DIR
CHROME_PROFILE_PATH = os.getenv("CHROME_PROFILE_PATH")
CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH")
USE_LOCAL_CHROMEDRIVER = _get_env_bool("USE_LOCAL_CHROMEDRIVER", False)
KEY = os.getenv("KEY")
KEY_BATCHES = os.getenv("KEY_BATCHES")
EXC_KEY = (os.getenv("EXC_KEY") or "").strip()
SEARCH_MATCH_MODE = (os.getenv("SEARCH_MATCH_MODE") or "exact").strip()
SEARCH_MATCH_MODE_MAP = os.getenv("SEARCH_MATCH_MODE_MAP")
MAX_PAGES = _get_env_int("MAX_PAGES")
RESULTS_PAGE_SIZE = _get_env_int("RESULTS_PAGE_SIZE", 50) or 50
ENABLE_KEYWORD_NGRAMS = _get_env_bool("ENABLE_KEYWORD_NGRAMS", True)

MATCH_MODE_LABELS = {
    "all-1": "Khớp tất cả từ (Phân biệt dấu)",
    "all-0": "Khớp tất cả từ (Không phân biệt dấu)",
    "any-1": "Khớp từ hoặc một số từ (Phân biệt dấu)",
    "any-0": "Khớp từ hoặc một số từ (Không phân biệt dấu)",
    "exact": "Khớp chính xác cụm từ",
}

if SEARCH_MATCH_MODE not in MATCH_MODE_LABELS:
    raise ValueError(
        f"SEARCH_MATCH_MODE không hợp lệ: {SEARCH_MATCH_MODE}. "
        f"Giá trị cho phép: {', '.join(MATCH_MODE_LABELS.keys())}"
    )


def parse_keyword_batches(raw_batches, fallback_key):
    if raw_batches and str(raw_batches).strip():
        parts = re.split(r"\r?\n|\|\|", str(raw_batches))
        batches = [part.strip() for part in parts if part and part.strip()]
        if batches:
            return batches

    fallback = (fallback_key or "").strip()
    return [fallback] if fallback else []


def parse_match_mode_map(raw_value):
    mapping = {}
    if not raw_value or not str(raw_value).strip():
        return mapping

    parts = re.split(r"\r?\n|\|\|", str(raw_value))
    for part in parts:
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"SEARCH_MATCH_MODE_MAP sai định dạng: '{item}'. Dùng dạng keyword:mode")

        keyword, mode = item.split(":", 1)
        keyword = keyword.strip().lower()
        mode = mode.strip()

        if not keyword:
            raise ValueError(f"SEARCH_MATCH_MODE_MAP có keyword rỗng: '{item}'")
        if mode not in MATCH_MODE_LABELS:
            raise ValueError(
                f"SEARCH_MATCH_MODE_MAP có mode không hợp lệ: {mode}. "
                f"Giá trị cho phép: {', '.join(MATCH_MODE_LABELS.keys())}"
            )
        mapping[keyword] = mode

    return mapping


SEARCH_KEYWORDS = parse_keyword_batches(KEY_BATCHES, KEY)
SEARCH_MATCH_MODE_BY_KEYWORD = parse_match_mode_map(SEARCH_MATCH_MODE_MAP)
driver = None
wait = None


def build_chrome_options():
    if not CHROME_PROFILE_PATH:
        raise ValueError("Thiếu CHROME_PROFILE_PATH trong .env")

    options = webdriver.ChromeOptions()
    options.add_argument(f"user-data-dir={CHROME_PROFILE_PATH}")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    options.add_experimental_option(
        "prefs",
        {
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    return options


def init_runtime():
    global driver, wait

    if driver is not None:
        return

    options = build_chrome_options()

    try:
        driver = webdriver.Chrome(options=options)
    except Exception as first_error:
        if USE_LOCAL_CHROMEDRIVER and CHROMEDRIVER_PATH:
            try:
                logger.warning(
                    "Selenium Manager không khởi tạo được Chrome (%s). Thử fallback sang CHROMEDRIVER_PATH...",
                    first_error,
                )
                service = Service(executable_path=CHROMEDRIVER_PATH, log_output=os.devnull)
                driver = webdriver.Chrome(service=service, options=options)
            except SessionNotCreatedException as error:
                raise RuntimeError(
                    f"ChromeDriver tại CHROMEDRIVER_PATH không khớp version Chrome: {error.msg}"
                ) from error
        else:
            raise RuntimeError(
                "Không thể khởi tạo Chrome bằng Selenium Manager. "
                "Nếu muốn dùng ChromeDriver local, hãy cấu hình USE_LOCAL_CHROMEDRIVER=true "
                "và CHROMEDRIVER_PATH trong .env."
            ) from first_error

    wait = WebDriverWait(driver, 20)


def shutdown_runtime():
    global driver, wait

    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass
        driver = None
        wait = None


loai_tu_gian_giao_thau = [
    "kích thích", "môi trường", "nông nghiệp", "khuyến nông", "nông dân", "vườn", "thức ăn", "bvtv", "bảo vệ thực vật",
    "lúa", "cao su", "giống", "phân bón", "diệt cỏ", "thuốc cỏ", "trừ cỏ", "thuốc sâu", "tưới nước", "cắt cỏ",
    "trừ sâu", "trừ bệnh", "rầy côn trùng", "phấn trắng", "đạo ôn", "chăn nuôi", "thủy sản", "thú y",
    "vật nuôi", "gia súc", "gia cầm", "chó", "mèo", "ruồi", "gà", "trâu", "bò", "vịt", "chuột", "cá", "tôm", "tả heo",
    "muỗi", "mối", "lở mồm", "cúm gia cầm",
    "vị thuốc", "thuốc y học cổ truyền", "chế phẩm y học cổ truyền", "thuốc cổ truyền", "đông y", "sinh học", "shpt", 
    "thuốc dược liệu", "thuốc thành phẩm y học cổ truyền", "tủ", "kho thuốc", "thuốc nổ",
    "sản xuất", "cứu hỏa", "lao động", "công nghiệp", "bão", "lụt", "hàng hóa dịch vụ", "phần mềm", "thuốc lá",
    "quặng", "nhuộm", "văn phòng", "bảo quản", "bao đựng", "rác", "túi đựng", "mực in", "giấy in", "linh kiện",
    "nghiên cứu", "kiểm nghiệm", "mỹ thuật", "nhu yếu phẩm", "tài sản", "lương thực", "in ấn", "sửa chữa",
    "thí nghiệm", "nhu yếu phẩm", "vận chuyển","công nghệ thông tin", "hệ thống mạng", "tin học", "máy tính",
    "mạng lan", "chống sét", "xử lý nước thải", "sắc ký", "quang phổ", "sửa chữa", "máy phun thuốc", "thuốc hàn",
    "truyền thông", "xe", "máy soi thuốc", "cây thuốc", "đông dược", "dịch chiết", "tinh dầu",
    "máy chiết xơ", "nội độc tố", "dung môi", "chất chuẩn", "chuẩn hóa", "kiểm tra", "độ hòa tan", "bình phun thuốc"
]
 
loai_chu_dau_tu = [
    ("nông", ["bệnh viện", "trung tâm y tế", "phòng khám", "trạm y tế", "sở y tế"]),
    ("nuôi", ["nuôi dưỡng"]),
    ("trồng", []),
    ("lâm nghiệp", []),
    ("kiểm lâm", []),
    ("cao su", []),
    ("xây dựng", []),
    ("phòng kinh tế", []),
    ("thuốc lá", []),
    ("viện nghiên cứu", []),
    ("chế biến", []),
    ("nông lâm", []),
    ("nước sạch", []),
    ("vệ sinh", []),
    ("công ty", []),
    ("chăn nuôi", []),
    ("thú y", []),
]

tu_khoa_luu_lai = [
    "generic", "biệt dược gốc", "bdg", "thuốc bổ sung",
    "thực phẩm chức năng", "thực phẩm bảo vệ sức khỏe", "thực phẩm dinh dưỡng",
    "mỹ phẩm", "vật tư y tế", "thiết bị y tế",
]


def _normalize_keyword_value(value):
    return str(value or "").strip().lower()


def _normalize_keyword_list(values):
    normalized_values = []
    for value in values:
        normalized = _normalize_keyword_value(value)
        if normalized and normalized not in normalized_values:
            normalized_values.append(normalized)
    return normalized_values


def _normalize_investor_rules(rules):
    normalized_rules = []
    for keyword, exclude_list in rules:
        normalized_keyword = _normalize_keyword_value(keyword)
        normalized_excludes = _normalize_keyword_list(exclude_list)
        if normalized_keyword:
            normalized_rules.append((normalized_keyword, normalized_excludes))
    return normalized_rules


loai_tu_gian_giao_thau = _normalize_keyword_list(loai_tu_gian_giao_thau)
tu_khoa_luu_lai = _normalize_keyword_list(tu_khoa_luu_lai)
loai_chu_dau_tu = _normalize_investor_rules(loai_chu_dau_tu)


def wait_presence(context, by, locator, timeout=10):
    return WebDriverWait(context, timeout).until(
        EC.presence_of_element_located((by, locator))
    )


def wait_clickable(context, by, locator, timeout=10):
    return WebDriverWait(context, timeout).until(
        EC.element_to_be_clickable((by, locator))
    )


def wait_overlay_gone(timeout=15):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, ".ant-spin-blur")) == 0
        )
        return True
    except TimeoutException:
        return False


def wait_dom_settled(timeout=15):
    wait_overlay_gone(timeout=timeout)
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
    )


def get_ma_tbmt(box):
    try:
        code_elem = wait_presence(
            box,
            By.CSS_SELECTOR,
            "p.content__body__left__item__infor__code",
            timeout=10,
        )
        code_text = code_elem.text.strip()
        return code_text.split(":")[-1].strip().split("-")[0]
    except Exception:
        return ""


def get_ten_goi_thau(box):
    try:
        return box.find_element(
            By.XPATH,
            ".//a/h5[contains(@class,'content__body__left__item__infor__contract__name')]",
        ).text.strip()
    except Exception:
        try:
            return box.find_element(
                By.XPATH,
                ".//h5[contains(@class,'content__body__left__item__infor__contract__name')]",
            ).text.strip()
        except Exception:
            return ""


def get_chu_dau_tu(box):
    try:
        return box.find_element(
            By.XPATH,
            ".//h6[contains(normalize-space(),'Chủ đầu tư')]/span",
        ).text.strip()
    except Exception:
        return ""


def get_box_elements():
    wait_dom_settled(timeout=15)

    try:
        container = wait_presence(driver, By.ID, "bid-closed", timeout=20)
        boxes = container.find_elements(By.CSS_SELECTOR, "div.content__body__left__item")
        if boxes:
            return boxes
    except TimeoutException:
        pass

    return driver.find_elements(By.CSS_SELECTOR, "div.content__body__left__item")


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


def resolve_match_mode(search_keyword: str) -> str:
    keyword_norm = _normalize_keyword_value(search_keyword)
    return SEARCH_MATCH_MODE_BY_KEYWORD.get(keyword_norm, SEARCH_MATCH_MODE)


def close_popup_if_present():
    try:
        close_button = wait.until(EC.element_to_be_clickable((By.ID, "popup-close")))
        close_button.click()
        logger.info("Đã đóng hộp thông báo quan trọng.")
    except (TimeoutException, NoSuchElementException):
        logger.info("Không có hộp thông báo cần đóng.")


def select_results_page_size():
    select_elem = wait_presence(driver, By.XPATH, "//div[contains(text(),'Hiển thị')]/select", timeout=20)
    select = Select(select_elem)
    available_values = [option.get_attribute("value") for option in select.options]
    desired_value = str(RESULTS_PAGE_SIZE)

    if desired_value not in available_values and "50" in available_values:
        logger.warning("RESULTS_PAGE_SIZE=%s không có trong UI, fallback sang 50.", desired_value)
        desired_value = "50"

    if desired_value in available_values:
        current_value = select.first_selected_option.get_attribute("value")
        if current_value != desired_value:
            select.select_by_value(desired_value)
            time.sleep(1)
            wait_dom_settled(timeout=15)


def prepare_search_form(search_keyword: str):
    driver.get("https://muasamcong.mpi.gov.vn/web/guest/home")
    close_popup_if_present()

    wait_clickable(driver, By.XPATH, "//button[contains(text(), 'Tìm kiếm nâng cao')]", timeout=20).click()

    match_mode = resolve_match_mode(search_keyword)
    select_keyword_match_mode(match_mode)
    logger.info("Chế độ khớp từ khóa: %s (%s)", MATCH_MODE_LABELS[match_mode], match_mode)
    wait_dom_settled(timeout=15)

    input_khong_chua_tu = wait_presence(
        driver,
        By.XPATH,
        "//input[@placeholder='Áp dụng cho tất cả các trường thông tin tìm kiếm']",
        timeout=20,
    )
    input_khong_chua_tu.clear()
    if EXC_KEY:
        input_khong_chua_tu.send_keys(EXC_KEY)

    input_tim_kiem = wait_presence(
        driver,
        By.XPATH,
        "//input[@placeholder='Nhập số TBMT/Tên gói thầu (ví dụ: IB0123456789 hoặc Thiết bị)']",
        timeout=20,
    )
    input_tim_kiem.clear()
    input_tim_kiem.send_keys(search_keyword)

    goods_checkbox = wait_clickable(
        driver,
        By.XPATH,
        "//input[@name='ck-investField' and @value='HH']",
        timeout=20,
    )
    if not goods_checkbox.is_selected():
        goods_checkbox.click()

    wait_clickable(driver, By.XPATH, "//button[contains(text(), 'Tìm kiếm')]", timeout=20).click()
    time.sleep(1)
    wait_clickable(
        driver,
        By.XPATH,
        "//ul[contains(@class, 'nav-tabs')]//a[contains(text(),'Đã đóng thầu')]",
        timeout=20,
    ).click()
    time.sleep(1)
    wait_clickable(
        driver,
        By.XPATH,
        "//div[contains(@class, 'content__body__option')]//span[contains(normalize-space(),'Có nhà thầu trúng thầu')]",
        timeout=20,
    ).click()
    time.sleep(2)
    wait_dom_settled(timeout=20)
    select_results_page_size()


def setup_search_form(search_keyword: str):
    prepare_search_form(search_keyword)


def extract_box_info(box, search_keyword: str, page: int, match_mode: str):
    return {
        "Keyword crawl": search_keyword,
        "Chế độ khớp": match_mode,
        "Trang kết quả": page,
        "Mã TBMT": get_ma_tbmt(box),
        "Tên gói thầu": get_ten_goi_thau(box),
        "Chủ đầu tư": get_chu_dau_tu(box),
    }


def get_box_info(search_keyword: str, page: int = 1, match_mode: str | None = None):
    records = []
    active_match_mode = match_mode or resolve_match_mode(search_keyword)
    boxes = get_box_elements()

    if not boxes:
        logger.warning("[%s] Không tìm thấy box gói thầu trên trang %s.", search_keyword, page)
        return records

    for box in boxes:
        records.append(extract_box_info(box, search_keyword, page, active_match_mode))
    return records


def go_to_next_results_page():
    selectors = [
        (By.CSS_SELECTOR, "button.btn-next:not([disabled])"),
        (By.CSS_SELECTOR, ".el-pagination .btn-next:not(.is-disabled)"),
    ]

    last_error = None
    for by, locator in selectors:
        try:
            next_button = wait.until(EC.element_to_be_clickable((by, locator)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
            next_button.click()
            time.sleep(2)
            wait_dom_settled(timeout=15)
            return True
        except Exception as error:
            last_error = error

    raise TimeoutException("Không tìm thấy nút qua trang tiếp theo.") from last_error


def crawl_current_results(search_keyword: str, start_page: int = 1, page_limit: int | None = None):
    all_info = []
    page = max(start_page, 1)
    effective_page_limit = page_limit if page_limit is not None else MAX_PAGES
    match_mode = resolve_match_mode(search_keyword)

    while True:
        logger.info("[%s] Đang lấy trang %s...", search_keyword, page)
        page_records = get_box_info(search_keyword, page=page, match_mode=match_mode)

        if not page_records:
            logger.info("[%s] Không còn dữ liệu hợp lệ ở trang %s.", search_keyword, page)
            break

        all_info.extend(page_records)

        if effective_page_limit and page >= effective_page_limit:
            logger.info("[%s] Dừng theo MAX_PAGES=%s.", search_keyword, effective_page_limit)
            break

        try:
            go_to_next_results_page()
            page += 1
        except TimeoutException:
            logger.info("[%s] Đã lấy hết trang khả dụng.", search_keyword)
            break

    return all_info


def scrape_pages(search_keyword: str, max_pages: int | None):
    return crawl_current_results(search_keyword, start_page=1, page_limit=max_pages)


def is_luu_lai_theo_ten_goi_thau(ten_goi_thau):
    ten_thap = _normalize_keyword_value(ten_goi_thau)
    return any(re.search(rf"\b{re.escape(kw)}\b", ten_thap) for kw in tu_khoa_luu_lai)


def is_loai_chu_dau_tu(ten_chu_dau_tu):
    ten_thap = _normalize_keyword_value(ten_chu_dau_tu)
    for keyword, exclude_list in loai_chu_dau_tu:
        if re.search(rf"\b{re.escape(keyword)}\b", ten_thap):
            if any(re.search(rf"\b{re.escape(ex)}\b", ten_thap) for ex in exclude_list):
                continue
            return True
    return False


def is_loai_ten_goi_thau(ten_goi_thau):
    ten_thap = _normalize_keyword_value(ten_goi_thau)
    if any(re.search(rf"\b{re.escape(word)}\b", ten_thap) for word in loai_tu_gian_giao_thau):
        return True
    return False


def classify_records(records):
    for item in records:
        ten_goi_thau = item.get("Tên gói thầu", "")
        ten_chu_dau_tu = item.get("Chủ đầu tư", "")

        if is_loai_chu_dau_tu(ten_chu_dau_tu) or is_loai_ten_goi_thau(ten_goi_thau):
            item["Kết quả lọc"] = "LOẠI"
            continue

        if is_luu_lai_theo_ten_goi_thau(ten_goi_thau):
            item["Kết quả lọc"] = "CHỌN"
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
    if not rows:
        return pd.DataFrame(columns=["Cụm từ", "Số lần"])
    return pd.DataFrame(rows)


def save_outputs(all_records):
    out_dir = os.path.join(BASE_DIR, "test_outputs")
    os.makedirs(out_dir, exist_ok=True)
    output_columns = [
        "Keyword crawl",
        "Chế độ khớp",
        "Trang kết quả",
        "Mã TBMT",
        "Tên gói thầu",
        "Chủ đầu tư",
        "Kết quả lọc",
    ]
    dedup_subset = ["Keyword crawl", "Mã TBMT", "Chủ đầu tư", "Tên gói thầu"]

    dedup_all = pd.DataFrame(all_records)
    for column in output_columns:
        if column not in dedup_all.columns:
            dedup_all[column] = None
    dedup_all = dedup_all[output_columns].drop_duplicates(subset=dedup_subset)

    dedup_all.to_excel(os.path.join(out_dir, "all_results.xlsx"), index=False, engine="openpyxl")

    selected_count = int((dedup_all["Kết quả lọc"] == "CHỌN").sum()) if not dedup_all.empty else 0
    filtered_count = int((dedup_all["Kết quả lọc"] == "LOẠI").sum()) if not dedup_all.empty else 0
    logger.info(
        "Đã lưu all_results.xlsx: %s dòng | CHỌN: %s | LOẠI: %s",
        len(dedup_all),
        selected_count,
        filtered_count,
    )
    if ENABLE_KEYWORD_NGRAMS:
        with pd.ExcelWriter(os.path.join(out_dir, "keyword_ngrams.xlsx"), engine="openpyxl") as writer:
            all_rows = dedup_all.to_dict("records")
            counter_to_df(build_ngram_counter(all_rows, 1)).to_excel(writer, sheet_name="all_1gram", index=False)
            counter_to_df(build_ngram_counter(all_rows, 2)).to_excel(writer, sheet_name="all_2gram", index=False)
            counter_to_df(build_ngram_counter(all_rows, 3)).to_excel(writer, sheet_name="all_3gram", index=False)
            counter_to_df(build_ngram_counter([row for row in all_rows if row.get("Kết quả lọc") == "CHỌN"], 1)).to_excel(writer, sheet_name="chon_1gram", index=False)
            counter_to_df(build_ngram_counter([row for row in all_rows if row.get("Kết quả lọc") == "CHỌN"], 2)).to_excel(writer, sheet_name="chon_2gram", index=False)
            counter_to_df(build_ngram_counter([row for row in all_rows if row.get("Kết quả lọc") == "CHỌN"], 3)).to_excel(writer, sheet_name="chon_3gram", index=False)
            counter_to_df(build_ngram_counter([row for row in all_rows if row.get("Kết quả lọc") == "LOẠI"], 1)).to_excel(writer, sheet_name="loai_1gram", index=False)
            counter_to_df(build_ngram_counter([row for row in all_rows if row.get("Kết quả lọc") == "LOẠI"], 2)).to_excel(writer, sheet_name="loai_2gram", index=False)
            counter_to_df(build_ngram_counter([row for row in all_rows if row.get("Kết quả lọc") == "LOẠI"], 3)).to_excel(writer, sheet_name="loai_3gram", index=False)
        logger.info("Đã lưu keyword_ngrams.xlsx để phân tích biến thể từ khóa.")
    else:
        logger.info("Đã tắt phân tích keyword_ngrams theo cấu hình ENABLE_KEYWORD_NGRAMS.")


def main():
    if not SEARCH_KEYWORDS:
        raise ValueError("Thiếu KEY hoặc KEY_BATCHES để test.")

    all_records = []

    try:
        init_runtime()
        for keyword in SEARCH_KEYWORDS:
            logger.info("=" * 60)
            logger.info("Đang test keyword: %s", keyword)
            logger.info("=" * 60)
            prepare_search_form(keyword)
            all_records.extend(crawl_current_results(keyword, page_limit=MAX_PAGES))

        classified_records = classify_records(all_records)
        save_outputs(classified_records)
    finally:
        shutdown_runtime()


if __name__ == "__main__":
    main()
