import logging
import base64
import json
import os
import re
import time
import unicodedata
from collections import Counter
from urllib.parse import urlencode

import pandas as pd
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    SessionNotCreatedException,
    TimeoutException,
    UnexpectedAlertPresentException,
)
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
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
TEST_OUTPUT_DIR = os.path.join(BASE_DIR, "test_outputs")
TEST_DOWNLOAD_DIR = os.path.join(TEST_OUTPUT_DIR, "downloads")
CHROME_PROFILE_PATH = os.getenv("CHROME_PROFILE_PATH")
CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH")
USE_LOCAL_CHROMEDRIVER = _get_env_bool("USE_LOCAL_CHROMEDRIVER", False)
KEY = os.getenv("KEY")
KEY_BATCHES = os.getenv("KEY_BATCHES")
EXC_KEY = (os.getenv("EXC_KEY") or "").strip()
SEARCH_MATCH_MODE = (os.getenv("SEARCH_MATCH_MODE") or "exact").strip()
SEARCH_MATCH_MODE_MAP = os.getenv("SEARCH_MATCH_MODE_MAP")
SEARCH_NOTICE_TYPE = os.getenv("SEARCH_NOTICE_TYPE")
SEARCH_NOTICE_TYPES = os.getenv("SEARCH_NOTICE_TYPES")
MAX_PAGES = _get_env_int("MAX_PAGES")
RESULTS_PAGE_SIZE = _get_env_int("RESULTS_PAGE_SIZE", 50) or 50
ENABLE_KEYWORD_NGRAMS = _get_env_bool("ENABLE_KEYWORD_NGRAMS", True)
TEST_CRAWL_TASK = str(os.getenv("TEST_CRAWL_TASK") or "1").strip()
OUTPUT_NAME = str(os.getenv("OUTPUT_NAME") or "all_results.xlsx").strip()

if TEST_CRAWL_TASK not in {"1", "2"}:
    raise ValueError("TEST_CRAWL_TASK không hợp lệ. Giá trị cho phép: 1 hoặc 2.")

DEFAULT_SEARCH_NOTICE_TYPE = "Thông báo mời thầu"
KHLCNT_SEARCH_NOTICE_TYPE = "Kế hoạch lựa chọn nhà thầu"
SEARCH_NOTICE_TYPE_LABELS = {
    "tbmt": DEFAULT_SEARCH_NOTICE_TYPE,
    "thong-bao-moi-thau": DEFAULT_SEARCH_NOTICE_TYPE,
    "thông báo mời thầu": DEFAULT_SEARCH_NOTICE_TYPE,
    "kh-lcnt": KHLCNT_SEARCH_NOTICE_TYPE,
    "ke-hoach-lua-chon-nha-thau": KHLCNT_SEARCH_NOTICE_TYPE,
    "kế hoạch lựa chọn nhà thầu": KHLCNT_SEARCH_NOTICE_TYPE,
}

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


def resolve_search_notice_type_label(value):
    label = (value or "").strip()
    if not label:
        return DEFAULT_SEARCH_NOTICE_TYPE
    return SEARCH_NOTICE_TYPE_LABELS.get(label.lower(), label)


def parse_search_notice_types(raw_types, raw_type):
    raw_value = raw_types if raw_types and str(raw_types).strip() else raw_type
    if raw_value and str(raw_value).strip():
        parts = re.split(r"\r?\n|\|\|", str(raw_value))
        labels = []
        for part in parts:
            label = resolve_search_notice_type_label(part)
            if label and label not in labels:
                labels.append(label)
        if labels:
            return labels
    return [DEFAULT_SEARCH_NOTICE_TYPE]


SEARCH_NOTICE_TYPE_LIST = parse_search_notice_types(SEARCH_NOTICE_TYPES, SEARCH_NOTICE_TYPE)


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
            "download.default_directory": os.path.abspath(TEST_DOWNLOAD_DIR),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return options


def init_runtime():
    global driver, wait

    if driver is not None:
        return

    os.makedirs(TEST_DOWNLOAD_DIR, exist_ok=True)
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
    try:
        driver.execute_cdp_cmd("Network.enable", {})
    except Exception:
        logger.warning("Không bật được Chrome DevTools Network; mã TBMT từ XHR có thể không được ghi nhận.")


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
    "vật nuôi", "gia súc", "gia cầm", "chó", "mèo", "ruồi", "gà", "trâu", "bò", "vịt", "chuột", "cá", "tôm", "heo", "lợn", "tả heo",
    "muỗi", "mối", "lở mồm", "cúm gia cầm",
    "vị thuốc", "thuốc y học cổ truyền", "chế phẩm y học cổ truyền", "thuốc cổ truyền", "đông y", "sinh học", "shpt", 
    "thuốc dược liệu", "thuốc thành phẩm y học cổ truyền", "tủ", "kho thuốc", "thuốc nổ",
    "sản xuất", "cứu hỏa", "lao động", "công nghiệp", "bão", "lụt", "hàng hóa dịch vụ", "phần mềm", "thuốc lá",
    "quặng", "nhuộm", "văn phòng", "bảo quản", "bao đựng", "rác", "túi đựng", "mực in", "giấy in", "linh kiện",
    "nghiên cứu", "kiểm nghiệm", "mỹ thuật", "nhu yếu phẩm", "tài sản", "lương thực", "in ấn", "sửa chữa",
    "thí nghiệm", "nhu yếu phẩm", "vận chuyển","công nghệ thông tin", "hệ thống mạng", "tin học", "máy tính",
    "mạng lan", "chống sét", "xử lý nước thải", "sắc ký", "quang phổ", "sửa chữa", "máy phun thuốc", "thuốc hàn",
    "truyền thông", "xe", "máy soi thuốc", "cây thuốc", "đông dược", "dịch chiết", "tinh dầu",
    "máy chiết xơ", "nội độc tố", "dung môi", "chất chuẩn", "chuẩn hóa", "kiểm tra", "độ hòa tan", "bình phun thuốc",
    "ma túy", "phun thuốc"
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
    ("kiểm nghiệm", []),
]

tu_khoa_luu_lai = [
    "generic", "biệt dược gốc", "bdg", "khám chữa bệnh", 
    "thiết bị y tế", "vật tư y tế", "thực phẩm chức năng", "thực phẩm bảo vệ sức khỏe", "thực phẩm dinh dưỡng"
]


def _normalize_keyword_value(value):
    return unicodedata.normalize("NFC", str(value or "")).strip().lower()


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


def handle_connection_alert_once(timeout=6, post_wait=3):
    try:
        alert = WebDriverWait(driver, timeout).until(EC.alert_is_present())
        alert_text = alert.text
        alert.accept()
        logger.warning("Đã đóng alert khi thao tác tab/detail: %s", alert_text)
        wait_overlay_gone(timeout=post_wait)
        return True
    except TimeoutException:
        return False
    except Exception as error:
        logger.warning("Không xử lý được alert: %s", error)
        return False


def is_khlcnt_notice_type(notice_type: str):
    return resolve_search_notice_type_label(notice_type) == KHLCNT_SEARCH_NOTICE_TYPE


def should_crawl_khlcnt_details():
    return TEST_CRAWL_TASK == "2"


def split_notice_code(raw_code: str):
    raw = str(raw_code or "").strip()
    if not raw:
        return "", ""
    if "-" not in raw:
        return raw, ""
    code, version = raw.split("-", 1)
    return code.strip(), version.strip()


def get_notice_code_full(box):
    try:
        code_elem = wait_presence(
            box,
            By.CSS_SELECTOR,
            "p.content__body__left__item__infor__code",
            timeout=10,
        )
        code_text = code_elem.text.strip()
        return code_text.split(":")[-1].strip()
    except Exception:
        return ""


def get_ma_tbmt(box):
    code, _version = split_notice_code(get_notice_code_full(box))
    return code


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


def get_box_detail_url(box):
    try:
        return box.find_element(
            By.XPATH,
            ".//a[.//h5[contains(@class,'content__body__left__item__infor__contract__name')]]",
        ).get_attribute("href")
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


def xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "concat(" + ', "\"", '.join(f"'{part}'" for part in value.split('"')) + ")"


def select_search_notice_type(notice_type: str):
    label = resolve_search_notice_type_label(notice_type)
    selected_xpath = (
        "//div[contains(@class,'width_date_antdv')]"
        "//div[contains(@class,'ant-select-selection--single')]"
        "[.//div[contains(@class,'ant-select-selection-selected-value')]]"
    )
    select_box = wait_clickable(driver, By.XPATH, selected_xpath, timeout=20)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", select_box)
    driver.execute_script("arguments[0].click();", select_box)

    label_xpath = xpath_literal(label)
    option_xpaths = [
        f"//li[contains(@class,'ant-select-dropdown-menu-item') and normalize-space()={label_xpath}]",
        f"//div[contains(@class,'ant-select-dropdown')]//*[contains(@class,'ant-select-dropdown-menu-item') and contains(normalize-space(), {label_xpath})]",
    ]

    last_error = None
    for option_xpath in option_xpaths:
        try:
            option = wait_clickable(driver, By.XPATH, option_xpath, timeout=20)
            driver.execute_script("arguments[0].click();", option)
            WebDriverWait(driver, 20).until(
                EC.text_to_be_present_in_element(
                    (By.XPATH, selected_xpath),
                    label,
                )
            )
            logger.info("Loại thông tin tìm kiếm: %s", label)
            wait_dom_settled(timeout=15)
            return label
        except Exception as error:
            last_error = error

    raise TimeoutException(f"Không chọn được loại thông tin tìm kiếm: {label}") from last_error


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


def get_visible_text_input_candidates():
    inputs = driver.find_elements(
        By.XPATH,
        "//input[not(@type='hidden') and not(@type='checkbox') and not(@type='radio')]",
    )
    candidates = []
    for item in inputs:
        try:
            if item.is_displayed() and item.is_enabled():
                candidates.append(item)
        except Exception:
            continue
    return candidates


def find_search_keyword_input():
    exact_placeholders = [
        "Nhập số TBMT/Tên gói thầu (ví dụ: IB0123456789 hoặc Thiết bị)",
    ]
    for placeholder in exact_placeholders:
        try:
            return wait_presence(driver, By.XPATH, f"//input[@placeholder={xpath_literal(placeholder)}]", timeout=3)
        except TimeoutException:
            pass

    keyword_tokens = [
        "tbmt",
        "mã tbmt",
        "tên gói thầu",
        "khlcnt",
        "mã kế hoạch",
        "tên kế hoạch",
        "kế hoạch lựa chọn nhà thầu",
    ]
    excluded_tokens = [
        "áp dụng cho tất cả",
        "không chứa",
        "từ ngày",
        "đến ngày",
        "ngày đăng tải",
    ]

    end_time = time.time() + 20
    while time.time() < end_time:
        for item in get_visible_text_input_candidates():
            placeholder = (item.get_attribute("placeholder") or "").strip()
            placeholder_norm = placeholder.lower()
            if not placeholder_norm:
                continue
            if any(token in placeholder_norm for token in excluded_tokens):
                continue
            if any(token in placeholder_norm for token in keyword_tokens):
                logger.info("Dùng ô keyword có placeholder: %s", placeholder)
                return item
        time.sleep(0.5)

    visible_placeholders = [
        (item.get_attribute("placeholder") or "").strip()
        for item in get_visible_text_input_candidates()
    ]
    raise TimeoutException(
        "Không tìm thấy ô nhập keyword. Các placeholder input đang thấy: "
        + " | ".join([value for value in visible_placeholders if value])
    )


def apply_post_search_filters(active_notice_type: str):
    if active_notice_type != DEFAULT_SEARCH_NOTICE_TYPE:
        logger.info("Bỏ qua filter Đã đóng thầu/Có nhà thầu trúng thầu cho loại: %s", active_notice_type)
        return

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


def prepare_search_form(search_keyword: str, notice_type: str = DEFAULT_SEARCH_NOTICE_TYPE):
    driver.get("https://muasamcong.mpi.gov.vn/web/guest/home")
    close_popup_if_present()

    wait_clickable(driver, By.XPATH, "//button[contains(text(), 'Tìm kiếm nâng cao')]", timeout=20).click()
    active_notice_type = select_search_notice_type(notice_type)

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

    input_tim_kiem = find_search_keyword_input()
    input_tim_kiem.clear()
    input_tim_kiem.send_keys(search_keyword)
    input()
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
    apply_post_search_filters(active_notice_type)
    time.sleep(2)
    wait_dom_settled(timeout=20)
    select_results_page_size()
    return active_notice_type


def setup_search_form(search_keyword: str, notice_type: str = DEFAULT_SEARCH_NOTICE_TYPE):
    return prepare_search_form(search_keyword, notice_type=notice_type)


def extract_box_info(box, search_keyword: str, page: int, match_mode: str, notice_type: str):
    notice_code_full = get_notice_code_full(box)
    notice_code, notice_version = split_notice_code(notice_code_full)
    is_khlcnt = is_khlcnt_notice_type(notice_type)
    if not should_crawl_khlcnt_details():
        return {
            "Loại thông tin": notice_type,
            "Keyword crawl": search_keyword,
            "Chế độ khớp": match_mode,
            "Trang kết quả": page,
            "Mã TBMT": notice_code,
            "Tên gói thầu": get_ten_goi_thau(box),
            "Chủ đầu tư": get_chu_dau_tu(box),
        }

    return {
        "Loại thông tin": notice_type,
        "Keyword crawl": search_keyword,
        "Chế độ khớp": match_mode,
        "Trang kết quả": page,
        "Mã TBMT": "" if is_khlcnt else notice_code,
        "Mã KHLCNT": notice_code if is_khlcnt else "",
        "Mã KHLCNT đầy đủ": notice_code_full if is_khlcnt else "",
        "Phiên bản KHLCNT": notice_version if is_khlcnt else "",
        "Tên KHLCNT": get_ten_goi_thau(box) if is_khlcnt else "",
        "Tên gói thầu": "" if is_khlcnt else get_ten_goi_thau(box),
        "Chủ đầu tư": get_chu_dau_tu(box),
        "URL chi tiết": get_box_detail_url(box),
    }


def get_box_info(
    search_keyword: str,
    page: int = 1,
    match_mode: str | None = None,
    notice_type: str = DEFAULT_SEARCH_NOTICE_TYPE,
):
    records = []
    active_match_mode = match_mode or resolve_match_mode(search_keyword)
    active_notice_type = resolve_search_notice_type_label(notice_type)
    boxes = get_box_elements()

    if not boxes:
        logger.warning("[%s] Không tìm thấy box gói thầu trên trang %s.", search_keyword, page)
        return records

    for box in boxes:
        records.append(extract_box_info(box, search_keyword, page, active_match_mode, active_notice_type))
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


def open_url_in_new_tab(url):
    main_window = driver.current_window_handle
    current_handles = set(driver.window_handles)
    driver.execute_script("window.open(arguments[0], '_blank');", url)
    WebDriverWait(driver, 10).until(lambda d: len(set(d.window_handles) - current_handles) == 1)
    new_window = list(set(driver.window_handles) - current_handles)[0]
    driver.switch_to.window(new_window)
    wait_dom_settled(timeout=20)
    return main_window


def close_current_tab_and_return(main_window):
    try:
        driver.close()
    finally:
        driver.switch_to.window(main_window)
        wait_dom_settled(timeout=15)


def clear_test_downloads():
    os.makedirs(TEST_DOWNLOAD_DIR, exist_ok=True)
    for name in os.listdir(TEST_DOWNLOAD_DIR):
        path = os.path.join(TEST_DOWNLOAD_DIR, name)
        if not os.path.isfile(path):
            continue
        if name.lower().endswith(".crdownload"):
            continue
        try:
            os.remove(path)
        except OSError:
            continue


def get_latest_download_file():
    files = []
    for name in os.listdir(TEST_DOWNLOAD_DIR):
        path = os.path.join(TEST_DOWNLOAD_DIR, name)
        if not os.path.isfile(path):
            continue
        if name.lower().endswith(".crdownload"):
            continue
        files.append(path)
    if not files:
        return None
    return max(files, key=os.path.getctime)


def wait_for_new_test_download(old_file=None, timeout=30, exts=None):
    old_norm = os.path.normcase(old_file) if old_file else None
    normalized_exts = None
    if exts:
        normalized_exts = tuple(ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in exts)

    end_time = time.time() + timeout
    while time.time() < end_time:
        latest = get_latest_download_file()
        if latest:
            latest_norm = os.path.normcase(latest)
            if latest_norm != old_norm:
                if not normalized_exts or latest.lower().endswith(normalized_exts):
                    return latest
        time.sleep(0.3)
    return None


def click_khlcnt_package_tab():
    tab_xpath = "//ul[contains(@class,'nav-tabs')]//a[contains(normalize-space(),'Thông tin gói thầu')]"
    tab = wait_clickable(driver, By.XPATH, tab_xpath, timeout=20)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tab)
    driver.execute_script("arguments[0].click();", tab)
    wait_dom_settled(timeout=15)


def get_khlcnt_package_rows():
    click_khlcnt_package_tab()
    table_xpath = (
        "//table[.//th[contains(normalize-space(),'Tên gói thầu')] "
        "and .//th[contains(normalize-space(),'Số thông báo liên kết')]]"
    )
    table = wait_presence(driver, By.XPATH, table_xpath, timeout=20)
    rows = table.find_elements(By.XPATH, ".//tbody/tr")
    parsed_rows = []

    for row_position, row in enumerate(rows, start=1):
        cells = row.find_elements(By.XPATH, "./td")
        if len(cells) < 5:
            continue

        child_name = cells[1].text.strip()
        approved_estimate = cells[2].text.strip()
        package_price = cells[3].text.strip()
        linked_notice = cells[4].text.strip()

        parsed_rows.append(
            {
                "STT gói thầu con": cells[0].text.strip(),
                "Dòng gói thầu con": row_position,
                "Tên gói thầu con": child_name,
                "Dự toán gói thầu sau KHLCNT": approved_estimate,
                "Giá gói thầu": package_price,
                "Số thông báo liên kết": linked_notice,
            }
        )

    return parsed_rows


def build_khlcnt_child_base_record(plan_record, child_row):
    return {
        "Loại thông tin": KHLCNT_SEARCH_NOTICE_TYPE,
        "Keyword crawl": plan_record.get("Keyword crawl", ""),
        "Chế độ khớp": plan_record.get("Chế độ khớp", ""),
        "Trang kết quả": plan_record.get("Trang kết quả", ""),
        "Mã KHLCNT": plan_record.get("Mã KHLCNT", ""),
        "Mã KHLCNT đầy đủ": plan_record.get("Mã KHLCNT đầy đủ", ""),
        "Phiên bản KHLCNT": plan_record.get("Phiên bản KHLCNT", ""),
        "Tên KHLCNT": plan_record.get("Tên KHLCNT", ""),
        "Chủ đầu tư": plan_record.get("Chủ đầu tư", ""),
        **child_row,
    }


def package_name_contains_search_keyword(package_name, search_keyword):
    keyword = _normalize_keyword_value(search_keyword)
    name = _normalize_keyword_value(package_name)
    if not keyword:
        return True
    return keyword in name


def classify_khlcnt_child_package(child_name, search_keyword):
    if is_luu_lai_theo_ten_goi_thau(child_name):
        return "CHỌN", ""
    if not package_name_contains_search_keyword(child_name, search_keyword):
        return "LOẠI", "Không chứa keyword crawl"
    if is_loai_ten_goi_thau(child_name):
        return "LOẠI", "Loại theo từ khóa tên gói thầu con"
    return "CHỌN", ""


def classify_khlcnt_plan_package(plan_name, search_keyword):
    reasons = []
    if not is_luu_lai_theo_ten_goi_thau(plan_name) and is_loai_ten_goi_thau(plan_name):
        reasons.append("Tên KHLCNT bị loại theo từ khóa filter")
    if reasons:
        return "FILTERED_SKIP", "; ".join(reasons)
    return "CHỌN", ""


def extract_tbmt_codes(data) -> list[str]:
    ib_pattern = re.compile(r"\bIB\d{10}\b")
    found = []
    seen = set()

    def add_codes(value):
        for code in ib_pattern.findall(str(value or "")):
            if code not in seen:
                seen.add(code)
                found.append(code)

    def parse_json_string(value):
        text = str(value or "").strip()
        if not text or text[0] not in "[{":
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    def walk_notify_no(value):
        parsed = parse_json_string(value) if isinstance(value, str) else None
        if parsed is not None:
            walk_notify_no(parsed)
            return

        if isinstance(value, dict):
            result_dto = value.get("resultDTO")
            if isinstance(result_dto, dict) and "notifyNo" in result_dto:
                add_codes(result_dto.get("notifyNo"))
            if "notifyNo" in value:
                add_codes(value.get("notifyNo"))
            link_notify_info = value.get("linkNotifyInfo")
            if isinstance(link_notify_info, dict) and "notifyNo" in link_notify_info:
                add_codes(link_notify_info.get("notifyNo"))
            for key, child_value in value.items():
                if key == "notifyNo":
                    add_codes(child_value)
                walk_notify_no(child_value)
            return

        if isinstance(value, list):
            for item in value:
                walk_notify_no(item)
            return

        if isinstance(value, str):
            add_codes(value)

    walk_notify_no(data)
    return found


def test_extract_tbmt_codes_example():
    sample = {
        "resultDTO": {"notifyNo": "IB2600031044"},
        "linkNotifyInfo": None,
    }
    assert extract_tbmt_codes(sample) == ["IB2600031044"]


def parse_json_body(value):
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        decoder = json.JSONDecoder()
        parsed, _idx = decoder.raw_decode(text)
        return parsed
    except Exception:
        return None


def walk_json_objects(data):
    parsed = parse_json_body(data) if isinstance(data, str) else data
    if isinstance(parsed, dict):
        yield parsed
        for value in parsed.values():
            yield from walk_json_objects(value)
    elif isinstance(parsed, list):
        for item in parsed:
            yield from walk_json_objects(item)


def build_kqlcnt_url(data: dict, base_url: str = "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection") -> str:
    result = data.get("resultDTO") or {}

    input_result_id = result.get("id")
    notify_no = result.get("notifyNo")
    plan_no = data.get("planNo") or result.get("planNo")
    process_apply = data.get("processApply") or result.get("processApply")
    bid_mode = data.get("bidMode") or result.get("bidMode")
    bid_form = data.get("bidForm") or result.get("bidForm") or ""

    required = {
        "resultDTO.id": input_result_id,
        "resultDTO.notifyNo": notify_no,
        "planNo": plan_no,
        "processApply": process_apply,
        "bidMode": bid_mode,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ValueError(f"Thiếu field bắt buộc: {', '.join(missing)}")

    params = {
        "p_p_id": "egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2",
        "p_p_lifecycle": "0",
        "p_p_state": "normal",
        "p_p_mode": "view",
        "_egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2_render": "detail-v2",
        "type": "es-notify-contractor",
        "stepCode": "notify-contractor-step-4-kqlcnt",
        "id": "",
        "notifyId": "",
        "inputResultId": input_result_id,
        "bidOpenId": "",
        "processApply": process_apply,
        "bidMode": bid_mode,
        "notifyNo": notify_no,
        "planNo": plan_no,
        "step": "kqlcnt",
        "isInternet": "",
        "bidForm": bid_form,
    }
    return f"{base_url}?{urlencode(params)}"


def find_kqlcnt_result_payload(data):
    for obj in walk_json_objects(data):
        result = obj.get("resultDTO") if isinstance(obj, dict) else None
        if not isinstance(result, dict):
            continue
        notify_codes = extract_tbmt_codes(result.get("notifyNo"))
        if not notify_codes:
            continue
        try:
            url = build_kqlcnt_url(obj)
        except ValueError:
            url = ""
        return {
            "data": obj,
            "tbmt_codes": notify_codes,
            "tbmt_code": notify_codes[0],
            "so_qd": result.get("decisionNo") or "",
            "version": result.get("resultVersion") or result.get("notifyVersion") or "",
            "url_goi_thau_con": url,
        }
    return None


def clear_performance_logs():
    try:
        driver.get_log("performance")
    except Exception:
        pass


def extract_tbmt_codes_from_performance_logs():
    codes = []
    seen = set()
    try:
        entries = driver.get_log("performance")
    except Exception:
        return codes

    for entry in entries:
        try:
            message = json.loads(entry.get("message", "{}")).get("message", {})
        except Exception:
            continue
        if message.get("method") != "Network.responseReceived":
            continue
        params = message.get("params", {})
        response = params.get("response", {})
        mime_type = str(response.get("mimeType") or "").lower()
        url = str(response.get("url") or "")
        is_muasamcong_response = "muasamcong.mpi.gov.vn" in url
        is_text_like = any(token in mime_type for token in ("json", "text", "javascript", "html"))
        if not is_muasamcong_response and not is_text_like:
            continue
        request_id = params.get("requestId")
        if not request_id:
            continue
        try:
            body_payload = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        except Exception:
            continue
        body = body_payload.get("body", "")
        if body_payload.get("base64Encoded"):
            try:
                body = base64.b64decode(body).decode("utf-8", errors="ignore")
            except Exception:
                continue
        for code in extract_tbmt_codes(body):
            if code not in seen:
                seen.add(code)
                codes.append(code)
    return codes


def extract_kqlcnt_result_from_performance_logs():
    try:
        entries = driver.get_log("performance")
    except Exception:
        return None

    fallback_payload = None
    for entry in entries:
        try:
            message = json.loads(entry.get("message", "{}")).get("message", {})
        except Exception:
            continue
        if message.get("method") != "Network.responseReceived":
            continue
        params = message.get("params", {})
        response = params.get("response", {})
        mime_type = str(response.get("mimeType") or "").lower()
        url = str(response.get("url") or "")
        is_muasamcong_response = "muasamcong.mpi.gov.vn" in url
        is_text_like = any(token in mime_type for token in ("json", "text", "javascript", "html"))
        if not is_muasamcong_response and not is_text_like:
            continue
        request_id = params.get("requestId")
        if not request_id:
            continue
        try:
            body_payload = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        except Exception:
            continue
        body = body_payload.get("body", "")
        if body_payload.get("base64Encoded"):
            try:
                body = base64.b64decode(body).decode("utf-8", errors="ignore")
            except Exception:
                continue
        result_payload = find_kqlcnt_result_payload(body)
        if not result_payload:
            continue
        if result_payload.get("url_goi_thau_con"):
            return result_payload
        fallback_payload = fallback_payload or result_payload
    return fallback_payload


def normalize_info_label(value):
    text = " ".join(str(value or "").replace("\xa0", " ").split()).strip()
    return text


def normalize_info_key(value):
    text = normalize_info_label(value).lower()
    text = re.sub(r"[():]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_text_content(element):
    return normalize_info_label(driver.execute_script("return arguments[0].textContent || '';", element))


def get_detail_info_pairs():
    try:
        pairs = driver.execute_script(
            """
            return Array.from(document.querySelectorAll('div.infomation__content')).map(item => {
                const title = item.querySelector('div.infomation__content__title');
                if (!title) return null;
                let value = '';
                for (const child of Array.from(item.children)) {
                    if (child !== title && child.tagName && child.tagName.toLowerCase() === 'div') {
                        value = child.textContent || '';
                        break;
                    }
                }
                return {
                    title: title.textContent || '',
                    value: value
                };
            }).filter(Boolean);
            """
        )
    except Exception:
        return []

    normalized_pairs = []
    for pair in pairs or []:
        title = normalize_info_key(pair.get("title"))
        value = normalize_info_label(pair.get("value"))
        if title:
            normalized_pairs.append((title, value))
    return normalized_pairs


def count_populated_detail_pairs():
    try:
        return sum(1 for _title, value in get_detail_info_pairs() if value)
    except Exception:
        return 0


def wait_for_khlcnt_child_detail_ready(timeout=20):
    card_header_xpath = (
        "//div[contains(@class,'card-header') and "
        "("
        "contains(normalize-space(),'Thông tin gói thầu') or "
        "contains(normalize-space(),'Thông tin chi tiết gói thầu') or "
        "contains(normalize-space(),'Thông tin kết quả lựa chọn nhà thầu') or "
        "contains(normalize-space(),'Thông tin phê duyệt kết quả') or "
        "contains(normalize-space(),'Danh sách quyết định phê duyệt')"
        ")]"
    )
    wait_presence(driver, By.XPATH, card_header_xpath, timeout=timeout)
    WebDriverWait(driver, timeout).until(lambda _d: count_populated_detail_pairs() >= 4)


def wait_for_detail_info_stable(timeout=20, min_pairs=6, stable_rounds=3, interval=0.4):
    end_time = time.time() + timeout
    last_signature = None
    stable_count = 0
    best_pairs = []

    while time.time() < end_time:
        pairs = get_detail_info_pairs()
        populated = [(title, value) for title, value in pairs if value]
        if len(populated) >= min_pairs:
            signature = tuple(populated)
            if signature == last_signature:
                stable_count += 1
            else:
                last_signature = signature
                stable_count = 1
            best_pairs = populated
            if stable_count >= stable_rounds:
                return pairs
        time.sleep(interval)

    return best_pairs or get_detail_info_pairs()


def normalize_version_code(raw_text):
    text = normalize_info_label(raw_text)
    if not text:
        return "00"
    match = re.search(r"\d{1,3}", text)
    if not match:
        return text
    return match.group(0).zfill(2)


def click_kqlcnt_tab_safely(index, timeout=20):
    try:
        ket_qua_tab = wait_clickable(
            driver,
            By.XPATH,
            "//a[contains(text(),'Kết quả lựa chọn nhà thầu')]",
            timeout=timeout,
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", ket_qua_tab)
        ket_qua_tab.click()
        wait_dom_settled(timeout=15)
        return True
    except UnexpectedAlertPresentException:
        logger.warning("Gói thầu con %s: alert trong lúc click tab KQLCNT.", index)
        handled = handle_connection_alert_once(timeout=10)
        if not handled:
            logger.warning("Gói thầu con %s: không bắt được alert, có thể đã tự hết.", index)
        wait_dom_settled(timeout=15)
        return False
    except TimeoutException:
        logger.info("Gói thầu con %s: chưa có tab Kết quả lựa chọn nhà thầu, ghi pending treo.", index)
        return False
    except Exception as error:
        logger.warning("Gói thầu con %s: không click được tab KQLCNT, ghi pending treo: %s", index, error)
        wait_dom_settled(timeout=15)
        return False


def wait_after_linked_notice_click(current_url, current_handles, timeout=12):
    WebDriverWait(driver, timeout).until(
        lambda d: len(set(d.window_handles) - current_handles) >= 1
        or d.current_url != current_url
        or len(d.find_elements(By.XPATH, "//a[contains(text(),'Kết quả lựa chọn nhà thầu')]")) > 0
    )
    new_handles = list(set(driver.window_handles) - current_handles)
    if new_handles:
        new_window = new_handles[0]
        driver.switch_to.window(new_window)
        wait_dom_settled(timeout=20)
        return {
            "navigation": "new_tab",
            "opened_window": new_window,
        }
    wait_dom_settled(timeout=20)
    return {"navigation": "same_tab"}


def get_current_result_version():
    try:
        select_elem = driver.find_element(
            By.XPATH,
            "//div[contains(@class,'infomation__content')][.//div[contains(@class,'infomation__content__title') and contains(normalize-space(),'Phiên bản')]]//select"
        )
        selected = Select(select_elem).first_selected_option
        return normalize_version_code(selected.text)
    except Exception:
        return ""


def find_target_item_card(timeout=10):
    header_xpath = (
        "//div[contains(@class,'card')][.//div[contains(@class,'card-header') and ("
        "contains(normalize-space(),'Danh sách thuốc') or "
        "contains(normalize-space(),'Danh mục thuốc') or "
        "contains(normalize-space(),'Danh sách hàng hóa') or "
        "contains(normalize-space(),'Danh mục hàng hóa')"
        ")]]"
    )
    card = wait_presence(driver, By.XPATH, header_xpath, timeout=timeout)
    header = wait_presence(
        card,
        By.XPATH,
        ".//div[contains(@class,'card-header')]",
        timeout=timeout,
    )
    card_name = normalize_info_label(header.text)
    return card, card_name


def get_target_card_export_button(card):
    try:
        return card.find_element(By.XPATH, ".//button[contains(normalize-space(),'Xuất Excel')]")
    except NoSuchElementException:
        return None


def get_target_card_attachment(card):
    try:
        return card.find_element(By.XPATH, ".//tags[contains(@class,'tags-fileAttach')]")
    except NoSuchElementException:
        try:
            return driver.find_element(By.XPATH, "//tags[contains(@class,'tags-fileAttach')]")
        except NoSuchElementException:
            return None


def extract_target_card_page(card):
    return driver.execute_script(
        """
        const card = arguments[0];
        const table = card.querySelector('table');
        if (!table) {
            return {headers: [], rows: []};
        }
        const headers = Array.from(table.querySelectorAll('thead th')).map((th, index) => {
            const text = (th.textContent || '').replace(/\\u00a0/g, ' ').trim();
            return text || `COL_${index + 1}`;
        });
        const rows = [];
        const trs = Array.from(table.querySelectorAll('tbody tr'));
        for (const tr of trs) {
            const cells = Array.from(tr.querySelectorAll('td'));
            if (!cells.length) continue;
            rows.push(cells.map(td => (td.textContent || '').replace(/\\u00a0/g, ' ').trim()));
        }
        return {headers, rows};
        """,
        card,
    )


def get_target_card_active_page(card):
    try:
        active = card.find_element(By.XPATH, ".//li[contains(@class,'ant-pagination-item-active')]")
        return normalize_info_label(active.text)
    except NoSuchElementException:
        return ""


def build_table_page_signature(page_data):
    headers = tuple(normalize_info_label(item) for item in page_data.get("headers", []))
    rows = tuple(
        tuple(normalize_info_label(value) for value in row)
        for row in page_data.get("rows", [])
    )
    return headers, rows


def click_target_card_next_page(card):
    next_button = card.find_elements(
        By.XPATH,
        ".//li[contains(@class,'ant-pagination-next') and not(contains(@class,'ant-pagination-disabled'))]",
    )
    if not next_button:
        return False

    before_data = extract_target_card_page(card)
    before_signature = build_table_page_signature(before_data)
    before_page = get_target_card_active_page(card)

    button = next_button[0]
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
    driver.execute_script("arguments[0].click();", button)
    wait_dom_settled(timeout=10)

    def page_changed(_driver):
        try:
            refreshed_card, _ = find_target_item_card(timeout=3)
            after_page = get_target_card_active_page(refreshed_card)
            after_data = extract_target_card_page(refreshed_card)
            after_signature = build_table_page_signature(after_data)
            if after_page and before_page and after_page != before_page:
                return True
            return after_signature != before_signature
        except Exception:
            return False

    try:
        WebDriverWait(driver, 12).until(page_changed)
    except TimeoutException:
        return False
    return True


def collect_target_card_table_rows(card, card_name, base_record):
    headers = []
    row_records = []
    seen_signatures = set()
    page_number = 1

    while True:
        page_data = extract_target_card_page(card)
        current_headers = [normalize_info_label(item) or f"COL_{idx + 1}" for idx, item in enumerate(page_data.get("headers", []))]
        if current_headers:
            headers = current_headers

        current_rows = page_data.get("rows", [])
        for row_index, row_values in enumerate(current_rows, start=1):
            normalized_values = [normalize_info_label(value) for value in row_values]
            if not any(normalized_values):
                continue
            signature = tuple(normalized_values)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            row_record = {
                "Mã KHLCNT": base_record.get("Mã KHLCNT", ""),
                "Mã KHLCNT đầy đủ": base_record.get("Mã KHLCNT đầy đủ", ""),
                "Tên KHLCNT": base_record.get("Tên KHLCNT", ""),
                "Tên gói thầu con": base_record.get("Tên gói thầu con", ""),
                "Mã TBMT hiệu lực": base_record.get("Mã TBMT hiệu lực", ""),
                "Card dữ liệu": card_name,
                "Trang bảng": page_number,
                "Dòng trên trang": row_index,
            }
            for idx, header in enumerate(headers):
                row_record[header] = normalized_values[idx] if idx < len(normalized_values) else ""
            if len(normalized_values) > len(headers):
                for idx in range(len(headers), len(normalized_values)):
                    row_record[f"COL_{idx + 1}"] = normalized_values[idx]
            row_records.append(row_record)

        if not click_target_card_next_page(card):
            break
        page_number += 1
        card, _ = find_target_item_card(timeout=10)

    return headers, row_records


def collect_target_card_artifacts(base_record):
    summary = {
        "Card dữ liệu": "",
        "Có nút Xuất Excel": "Không",
        "Phương thức thu thập bảng": "",
        "Số cột bảng": 0,
        "Số dòng bảng": 0,
        "Số trang bảng": 0,
        "Tên file tải thử": "",
        "Đường dẫn file tải thử": "",
        "Tên attachment fallback": "",
    }
    row_records = []

    try:
        card, card_name = find_target_item_card(timeout=8)
    except TimeoutException:
        summary["Phương thức thu thập bảng"] = "Không tìm thấy card đích"
        return summary, row_records

    summary["Card dữ liệu"] = card_name
    export_button = get_target_card_export_button(card)
    if export_button:
        summary["Có nút Xuất Excel"] = "Có"
        summary["Phương thức thu thập bảng"] = "Xuất Excel đúng card"
        clear_test_downloads()
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", export_button)
        driver.execute_script("arguments[0].click();", export_button)
        downloaded = wait_for_new_test_download(old_file=None, timeout=25, exts=[".xlsx", ".xls"])
        if downloaded:
            summary["Tên file tải thử"] = os.path.basename(downloaded)
            summary["Đường dẫn file tải thử"] = downloaded
            return summary, row_records
        else:
            summary["Phương thức thu thập bảng"] = "Có nút Xuất Excel nhưng chưa bắt được file"

    headers, row_records = collect_target_card_table_rows(card, card_name, base_record)
    summary["Số cột bảng"] = len(headers)
    summary["Số dòng bảng"] = len(row_records)
    summary["Số trang bảng"] = max([int(row.get("Trang bảng", 0) or 0) for row in row_records], default=0)

    if not row_records:
        attachment = get_target_card_attachment(card)
        if attachment:
            summary["Tên attachment fallback"] = normalize_info_label(attachment.text)
            if summary["Phương thức thu thập bảng"]:
                summary["Phương thức thu thập bảng"] += " + fallback attachment"
            else:
                summary["Phương thức thu thập bảng"] = "Fallback attachment"
    elif not summary["Phương thức thu thập bảng"]:
        summary["Phương thức thu thập bảng"] = "Đọc trực tiếp từ bảng web"

    return summary, row_records


def collect_info_card_fields():
    target_fields = [
        ("tên chủ đầu tư", "Chủ đầu tư"),
        ("chủ đầu tư", "Chủ đầu tư"),
        ("tên gói thầu", "Tên gói thầu"),
        ("đấu thầu qua mạng", "Đấu thầu qua mạng"),
        ("trong nước/ quốc tế", "Trong nước/ Quốc tế"),
        ("giá gói thầu", "Giá gói thầu"),
        ("lĩnh vực", "Lĩnh vực"),
        ("hình thức lcnt", "Hình thức LCNT"),
        ("hình thức lựa chọn nhà thầu", "Hình thức lựa chọn nhà thầu"),
        ("phương thức lựa chọn nhà thầu", "Phương thức lựa chọn nhà thầu"),
        ("loại hợp đồng", "Loại hợp đồng"),
        ("phân loại gói thầu", "Phân loại gói thầu"),
        ("thời gian thực hiện gói thầu", "Thời gian thực hiện gói thầu"),
        ("ngày đăng tải", "Ngày đăng tải"),
        ("ngày phê duyệt", "Ngày phê duyệt"),
        ("cơ quan phê duyệt", "Cơ quan phê duyệt"),
        ("số quyết định phê duyệt", "Số quyết định phê duyệt"),
    ]
    info = {field: "" for _label, field in target_fields}

    wait_presence(driver, By.CSS_SELECTOR, "div.infomation__content", timeout=20)
    pairs = get_detail_info_pairs()
    for title_key, value in pairs:
        if not title_key or not value:
            continue
        for label_key, mapped_field in target_fields:
            if title_key == label_key:
                info[mapped_field] = value
                break

    if not info.get("Hình thức lựa chọn nhà thầu") and info.get("Hình thức LCNT"):
        info["Hình thức lựa chọn nhà thầu"] = info.get("Hình thức LCNT", "")
    if not info.get("Hình thức LCNT") and info.get("Hình thức lựa chọn nhà thầu"):
        info["Hình thức LCNT"] = info.get("Hình thức lựa chọn nhà thầu", "")
    return info


def click_khlcnt_child_name_detail(child_row):
    row_index = int(child_row.get("Dòng gói thầu con") or 0)
    if row_index <= 0:
        raise ValueError("Thiếu Dòng gói thầu con để click detail.")

    click_khlcnt_package_tab()
    table_xpath = (
        "//table[.//th[contains(normalize-space(),'Tên gói thầu')] "
        "and .//th[contains(normalize-space(),'Số thông báo liên kết')]]"
    )
    row_xpath = f"({table_xpath}//tbody/tr)[{row_index}]//td[2]//a"
    child_link = wait_clickable(driver, By.XPATH, row_xpath, timeout=20)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", child_link)
    current_url = driver.current_url
    clear_performance_logs()
    driver.execute_script("arguments[0].click();", child_link)
    wait_dom_settled(timeout=20)
    return {
        "navigation": "same_tab",
        "previous_url": current_url,
    }


def click_khlcnt_linked_notice_detail(child_row):
    row_index = int(child_row.get("Dòng gói thầu con") or 0)
    if row_index <= 0:
        raise ValueError("Thiếu Dòng gói thầu con để click Số thông báo liên kết.")

    click_khlcnt_package_tab()
    table_xpath = (
        "//table[.//th[contains(normalize-space(),'Tên gói thầu')] "
        "and .//th[contains(normalize-space(),'Số thông báo liên kết')]]"
    )
    linked_cell_xpath = f"({table_xpath}//tbody/tr)[{row_index}]//td[5]"
    linked_span_xpath = f"{linked_cell_xpath}//span[normalize-space()]"
    linked_target_xpaths = [
        f"{linked_cell_xpath}//a[normalize-space()]",
        linked_span_xpath,
        linked_cell_xpath,
    ]

    linked_cell = wait_presence(driver, By.XPATH, linked_cell_xpath, timeout=20)
    linked_text = normalize_info_label(linked_cell.text)
    linked_target = None
    for target_xpath in linked_target_xpaths:
        try:
            linked_target = wait_clickable(driver, By.XPATH, target_xpath, timeout=3)
            break
        except TimeoutException:
            continue
    if linked_target is None:
        linked_target = linked_cell

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", linked_cell)
    current_url = driver.current_url
    current_window = driver.current_window_handle
    current_handles = set(driver.window_handles)
    clear_performance_logs()

    click_attempts = [
        ("native target", lambda: linked_target.click()),
        ("action target", lambda: ActionChains(driver).move_to_element(linked_target).click().perform()),
        ("native cell", lambda: linked_cell.click()),
        ("action cell", lambda: ActionChains(driver).move_to_element(linked_cell).click().perform()),
        ("js cell", lambda: driver.execute_script("arguments[0].click();", linked_cell)),
    ]
    last_error = None
    for label, click_func in click_attempts:
        try:
            logger.info("Dòng %s: click Số thông báo liên kết bằng %s: %s", row_index, label, linked_text)
            click_func()
            nav_result = wait_after_linked_notice_click(current_url, current_handles, timeout=8)
            return {
                **nav_result,
                "main_window": current_window,
                "previous_url": current_url,
            }
        except TimeoutException as error:
            last_error = error
            logger.warning(
                "Dòng %s: click %s chưa điều hướng khỏi KHLCNT, thử cách tiếp theo.",
                row_index,
                label,
            )
            continue
        except Exception as error:
            last_error = error
            logger.warning("Dòng %s: click %s lỗi: %s", row_index, label, error)
            continue

    raise TimeoutException(
        f"Click Số thông báo liên kết dòng {row_index} ({linked_text}) không điều hướng khỏi trang KHLCNT"
    ) from last_error


def return_to_khlcnt_package_table(nav_context):
    try:
        if nav_context.get("navigation") == "new_tab":
            opened_window = nav_context.get("opened_window")
            main_window = nav_context.get("main_window")
            try:
                if opened_window in driver.window_handles:
                    driver.close()
            finally:
                if main_window in driver.window_handles:
                    driver.switch_to.window(main_window)
                    wait_dom_settled(timeout=20)
        else:
            previous_url = nav_context.get("previous_url", "")
            if driver.current_url != previous_url:
                driver.back()
                wait_dom_settled(timeout=20)
    except Exception:
        pass
    click_khlcnt_package_tab()


def collect_khlcnt_child_detail(child_row, base_record):
    linked_notice = normalize_info_label(child_row.get("Số thông báo liên kết", ""))
    if linked_notice:
        nav_context = click_khlcnt_linked_notice_detail(child_row)
    else:
        nav_context = click_khlcnt_child_name_detail(child_row)
    try:
        detail_info = {
            "Mã TBMT từ XHR": "",
            "Danh sách mã TBMT từ XHR": [],
            "Mã TBMT hiệu lực": linked_notice,
            "Nhánh xử lý": "TBMT_LINKED" if linked_notice else "KHLCNT_NO_LINKED_TBMT",
            "Có tab KQLCNT": "Không",
            "URL gói thầu con": "",
            "Phiên bản KQLCNT": "",
            "Cho phép ghi nhận DB": "Không",
            "Dữ liệu bảng card": [],
        }

        if linked_notice:
            child_index = child_row.get("Dòng gói thầu con") or child_row.get("STT gói thầu con") or "?"
            if not click_kqlcnt_tab_safely(child_index, timeout=5):
                try:
                    wait_for_khlcnt_child_detail_ready(timeout=10)
                    wait_for_detail_info_stable(timeout=10, min_pairs=4, stable_rounds=2, interval=0.4)
                    detail_info.update(collect_info_card_fields())
                except Exception:
                    pass
                return detail_info
            detail_info["Có tab KQLCNT"] = "Có"

        try:
            wait_for_khlcnt_child_detail_ready(timeout=20)
            wait_for_detail_info_stable(timeout=20, min_pairs=6, stable_rounds=3, interval=0.4)
            card_info = collect_info_card_fields()
            if len([value for value in card_info.values() if value]) < 6:
                wait_for_detail_info_stable(timeout=10, min_pairs=4, stable_rounds=2, interval=0.5)
                card_info = collect_info_card_fields()
            detail_info.update(card_info)
        except TimeoutException:
            detail_info["Phương thức thu thập bảng"] = "Không load được trang detail gói thầu con"
            return detail_info

        wait_dom_settled(timeout=10)
        time.sleep(0.4)
        result_payload = extract_kqlcnt_result_from_performance_logs()
        tbmt_codes = result_payload.get("tbmt_codes", []) if result_payload else []
        effective_tbmt = linked_notice or (tbmt_codes[0] if tbmt_codes else "")
        detail_info["Mã TBMT từ XHR"] = ", ".join(tbmt_codes)
        detail_info["Danh sách mã TBMT từ XHR"] = tbmt_codes
        detail_info["Mã TBMT hiệu lực"] = effective_tbmt
        if result_payload:
            if not linked_notice:
                detail_info["URL gói thầu con"] = result_payload.get("url_goi_thau_con", "") or driver.current_url
            if result_payload.get("so_qd") and not detail_info.get("Số quyết định phê duyệt"):
                detail_info["Số quyết định phê duyệt"] = result_payload.get("so_qd", "")
            detail_info["Phiên bản KQLCNT"] = normalize_version_code(result_payload.get("version", ""))
        if linked_notice and not detail_info.get("Phiên bản KQLCNT"):
            detail_info["Phiên bản KQLCNT"] = get_current_result_version() or "00"

        if linked_notice:
            detail_info["Cho phép ghi nhận DB"] = "Có" if detail_info.get("Có tab KQLCNT") == "Có" else "Không"
        else:
            if not effective_tbmt:
                return detail_info
            detail_info["Cho phép ghi nhận DB"] = "Có"

        artifact_summary, artifact_rows = collect_target_card_artifacts(
            {
                **base_record,
                **detail_info,
                "Mã TBMT hiệu lực": effective_tbmt,
            }
        )
        detail_info.update(artifact_summary)
        detail_info["Dữ liệu bảng card"] = artifact_rows
        return detail_info
    finally:
        return_to_khlcnt_package_table(nav_context)


def process_khlcnt_plan_detail(plan_record, search_keyword):
    matched_records = []
    filtered_records = []
    linked_records = []
    pending_records = []
    plan_skip_records = []
    table_row_records = []
    filtered_child_count = 0
    valid_child_count = 0
    pending_child_count = 0
    khlcnt_name = plan_record.get("Tên KHLCNT", "")
    detail_url = plan_record.get("URL chi tiết", "")

    plan_filter_result, plan_filter_reason = classify_khlcnt_plan_package(khlcnt_name, search_keyword)
    if plan_filter_result == "FILTERED_SKIP":
        plan_skip_records.append(
            {
                **plan_record,
                "Kết quả lọc": "FILTERED_SKIP",
                "Lý do": plan_filter_reason,
            }
        )
        return matched_records, filtered_records, linked_records, pending_records, plan_skip_records, table_row_records

    if not detail_url:
        logger.info(
            "[%s] Bỏ qua KHLCNT vì không có URL chi tiết. Không ghi filtered_skip/scan_logs.",
            plan_record.get("Mã KHLCNT", ""),
        )
        return matched_records, filtered_records, linked_records, pending_records, plan_skip_records, table_row_records

    main_window = open_url_in_new_tab(detail_url)
    try:
        child_rows = get_khlcnt_package_rows()

        if not child_rows:
            logger.info(
                "[%s] Không đọc được dòng gói thầu con từ detail KHLCNT. Không ghi filtered_skip/scan_logs.",
                plan_record.get("Mã KHLCNT", ""),
            )
            return matched_records, filtered_records, linked_records, pending_records, plan_skip_records, table_row_records

        for child_row in child_rows:
            base_record = build_khlcnt_child_base_record(plan_record, child_row)
            linked_notice = child_row.get("Số thông báo liên kết", "").strip()

            child_result, child_reason = classify_khlcnt_child_package(
                child_row.get("Tên gói thầu con", ""),
                search_keyword,
            )
            output_record = {
                **base_record,
                "Kết quả lọc": child_result,
                "Lý do": child_reason,
                "Mã TBMT hiệu lực": normalize_info_label(linked_notice),
                "Nhánh xử lý": "TBMT_LINKED" if linked_notice else "KHLCNT_NO_LINKED_TBMT",
            }
            if child_result == "CHỌN":
                valid_child_count += 1
                if linked_notice:
                    output_record.update(
                        {
                            "Mã TBMT hiệu lực": normalize_info_label(linked_notice),
                            "Mã TBMT từ XHR": "",
                            "Danh sách mã TBMT từ XHR": [],
                            "Có tab KQLCNT": "Không xử lý",
                            "URL gói thầu con": "",
                            "Phiên bản KQLCNT": "",
                            "Cho phép ghi nhận DB": "Có",
                            "Phương thức thu thập bảng": "Không xử lý TBMT_LINKED; chỉ ghi metadata KHLCNT cho Mã TBMT liên kết",
                            "Lý do": "TBMT_LINKED: chỉ đọc Số thông báo liên kết và ghi metadata KHLCNT",
                        }
                    )
                    linked_records.append(output_record)
                    continue
                try:
                    detail_info = collect_khlcnt_child_detail(child_row, base_record)
                    output_record.update(detail_info)
                    table_row_records.extend(detail_info.get("Dữ liệu bảng card", []))
                except Exception as error:
                    logger.exception(
                        "Lỗi khi lấy detail gói thầu con %s / %s: %s",
                        plan_record.get("Mã KHLCNT", ""),
                        child_row.get("Tên gói thầu con", ""),
                        error,
                    )
                    output_record["Lý do"] = f"Lỗi lấy detail: {error}"
                    output_record["Cho phép ghi nhận DB"] = "Không"
                output_record.pop("Dữ liệu bảng card", None)
                if not linked_notice and not output_record.get("Mã TBMT hiệu lực"):
                    output_record["Kết quả lọc"] = "PENDING_TEST_REVIEW"
                    if output_record.get("Phương thức thu thập bảng") == "Không load được trang detail gói thầu con":
                        output_record["Lý do"] = "KHLCNT_NO_LINKED_TBMT: không load được trang detail gói thầu con"
                    else:
                        output_record["Lý do"] = "KHLCNT_NO_LINKED_TBMT: resultDTO null hoặc không có notifyNo để xác định Mã TBMT"
                    output_record["Cho phép ghi nhận DB"] = "Không"
                    pending_records.append(output_record)
                    pending_child_count += 1
                    continue
                if (
                    not linked_notice
                    and (
                        output_record.get("Phương thức thu thập bảng") == "Không tìm thấy card đích"
                        or (
                            int(output_record.get("Số dòng bảng") or 0) == 0
                            and not output_record.get("Tên file tải thử")
                            and not output_record.get("Tên attachment fallback")
                        )
                    )
                ):
                    output_record["Kết quả lọc"] = "PENDING_TEST_REVIEW"
                    if output_record.get("Phương thức thu thập bảng") == "Không tìm thấy card đích":
                        output_record["Lý do"] = "KHLCNT_NO_LINKED_TBMT: không có card Danh sách thuốc/Danh sách hàng hóa"
                    else:
                        output_record["Lý do"] = "KHLCNT_NO_LINKED_TBMT: không đọc được bảng và không tải được attachment"
                    output_record["Cho phép ghi nhận DB"] = "Không"
                    pending_records.append(output_record)
                    pending_child_count += 1
                    continue
                if linked_notice:
                    linked_records.append(output_record)
                else:
                    matched_records.append(output_record)
            else:
                filtered_child_count += 1
                filtered_records.append(output_record)
    finally:
        close_current_tab_and_return(main_window)

    if pending_child_count > 0:
        logger.info(
            "[%s] Ghi pending test review cho %s gói thầu con đang treo/chưa có KQTT. Không ghi filtered_skip/scan_logs.",
            plan_record.get("Mã KHLCNT", ""),
            pending_child_count,
        )
        return matched_records, filtered_records, linked_records, pending_records, plan_skip_records, table_row_records

    if valid_child_count == 0 and filtered_child_count > 0:
        plan_skip_records.append(
            {
                **plan_record,
                "Kết quả lọc": "FILTERED_SKIP",
                "Lý do": "Không có gói thầu con nào hợp lệ sau filter",
                "Số dòng con": len(child_rows),
                "Số dòng con hợp lệ": valid_child_count,
                "Số dòng con bị loại": filtered_child_count,
            }
        )

    return matched_records, filtered_records, linked_records, pending_records, plan_skip_records, table_row_records


def crawl_khlcnt_current_results(
    search_keyword: str,
    start_page: int = 1,
    page_limit: int | None = None,
    notice_type: str = KHLCNT_SEARCH_NOTICE_TYPE,
):
    plan_records = []
    matched_child_records = []
    filtered_child_records = []
    linked_child_records = []
    pending_child_records = []
    plan_skip_records = []
    table_row_records = []
    page = max(start_page, 1)
    effective_page_limit = page_limit if page_limit is not None else MAX_PAGES
    match_mode = resolve_match_mode(search_keyword)
    active_notice_type = resolve_search_notice_type_label(notice_type)

    while True:
        logger.info("[%s | %s] Đang lấy trang %s và đọc child packages...", active_notice_type, search_keyword, page)
        page_plan_records = get_box_info(
            search_keyword,
            page=page,
            match_mode=match_mode,
            notice_type=active_notice_type,
        )

        if not page_plan_records:
            logger.info("[%s | %s] Không còn KHLCNT hợp lệ ở trang %s.", active_notice_type, search_keyword, page)
            break

        for idx, plan_record in enumerate(page_plan_records, start=1):
            plan_filter_result, plan_filter_reason = classify_khlcnt_plan_package(
                plan_record.get("Tên KHLCNT", ""),
                search_keyword,
            )
            if plan_filter_result == "FILTERED_SKIP":
                logger.info(
                    "[%s] Bỏ qua KHLCNT %s/%s theo filter tên: %s | %s",
                    plan_record.get("Mã KHLCNT", ""),
                    idx,
                    len(page_plan_records),
                    plan_record.get("Tên KHLCNT", ""),
                    plan_filter_reason,
                )
                plan_records.append(plan_record)
                plan_skip_records.append(
                    {
                        **plan_record,
                        "Kết quả lọc": "FILTERED_SKIP",
                        "Lý do": plan_filter_reason,
                    }
                )
                continue

            logger.info(
                "[%s] Đọc KHLCNT %s/%s: %s",
                plan_record.get("Mã KHLCNT", ""),
                idx,
                len(page_plan_records),
                plan_record.get("Tên KHLCNT", ""),
            )
            try:
                matched, filtered, linked, pending, skipped, table_rows = process_khlcnt_plan_detail(plan_record, search_keyword)
                if not any([matched, filtered, linked, pending, skipped, table_rows]):
                    continue
                plan_records.append(plan_record)
                matched_child_records.extend(matched)
                filtered_child_records.extend(filtered)
                linked_child_records.extend(linked)
                pending_child_records.extend(pending)
                plan_skip_records.extend(skipped)
                table_row_records.extend(table_rows)
            except Exception as error:
                logger.exception("Lỗi khi đọc chi tiết KHLCNT %s: %s", plan_record.get("Mã KHLCNT", ""), error)
                plan_records.append(plan_record)
                plan_skip_records.append(
                    {
                        **plan_record,
                        "Kết quả lọc": "ERROR",
                        "Lý do": str(error),
                    }
                )

        if effective_page_limit and page >= effective_page_limit:
            logger.info("[%s | %s] Dừng theo MAX_PAGES=%s.", active_notice_type, search_keyword, effective_page_limit)
            break

        try:
            go_to_next_results_page()
            page += 1
        except TimeoutException:
            logger.info("[%s | %s] Đã lấy hết trang khả dụng.", active_notice_type, search_keyword)
            break

    return {
        "plans": plan_records,
        "matched_child_packages": matched_child_records,
        "filtered_child_packages": filtered_child_records,
        "linked_child_packages": linked_child_records,
        "pending_child_packages": pending_child_records,
        "plan_skips": plan_skip_records,
        "child_table_rows": table_row_records,
    }


def crawl_current_results(
    search_keyword: str,
    start_page: int = 1,
    page_limit: int | None = None,
    notice_type: str = DEFAULT_SEARCH_NOTICE_TYPE,
):
    all_info = []
    page = max(start_page, 1)
    effective_page_limit = page_limit if page_limit is not None else MAX_PAGES
    match_mode = resolve_match_mode(search_keyword)
    active_notice_type = resolve_search_notice_type_label(notice_type)

    while True:
        logger.info("[%s | %s] Đang lấy trang %s...", active_notice_type, search_keyword, page)
        page_records = get_box_info(
            search_keyword,
            page=page,
            match_mode=match_mode,
            notice_type=active_notice_type,
        )

        if not page_records:
            logger.info("[%s | %s] Không còn dữ liệu hợp lệ ở trang %s.", active_notice_type, search_keyword, page)
            break

        all_info.extend(page_records)

        if effective_page_limit and page >= effective_page_limit:
            logger.info("[%s | %s] Dừng theo MAX_PAGES=%s.", active_notice_type, search_keyword, effective_page_limit)
            break

        try:
            go_to_next_results_page()
            page += 1
        except TimeoutException:
            logger.info("[%s | %s] Đã lấy hết trang khả dụng.", active_notice_type, search_keyword)
            break

    return all_info


def scrape_pages(
    search_keyword: str,
    max_pages: int | None,
    notice_type: str = DEFAULT_SEARCH_NOTICE_TYPE,
):
    return crawl_current_results(
        search_keyword,
        start_page=1,
        page_limit=max_pages,
        notice_type=notice_type,
    )


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


def classify_package_name(ten_goi_thau):
    if is_luu_lai_theo_ten_goi_thau(ten_goi_thau):
        return "CHỌN"
    if is_loai_ten_goi_thau(ten_goi_thau):
        return "LOẠI"
    return "CHỌN"


def classify_records(records):
    for item in records:
        ten_goi_thau = item.get("Tên gói thầu") or item.get("Tên KHLCNT", "")
        ten_chu_dau_tu = item.get("Chủ đầu tư", "")

        if is_luu_lai_theo_ten_goi_thau(ten_goi_thau):
            item["Kết quả lọc"] = "CHỌN"
            continue

        if is_loai_chu_dau_tu(ten_chu_dau_tu) or is_loai_ten_goi_thau(ten_goi_thau):
            item["Kết quả lọc"] = "LOẠI"
            continue

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


def save_outputs(all_records, khlcnt_outputs=None):
    out_dir = os.path.join(BASE_DIR, "test_outputs")
    os.makedirs(out_dir, exist_ok=True)
    legacy_output_columns = [
        "Loại thông tin",
        "Keyword crawl",
        "Chế độ khớp",
        "Trang kết quả",
        "Mã TBMT",
        "Tên gói thầu",
        "Chủ đầu tư",
        "Kết quả lọc",
    ]
    khlcnt_output_columns = [
        "Loại thông tin",
        "Keyword crawl",
        "Chế độ khớp",
        "Trang kết quả",
        "Mã KHLCNT",
        "Mã KHLCNT đầy đủ",
        "Phiên bản KHLCNT",
        "Tên KHLCNT",
        "Tên gói thầu",
        "Chủ đầu tư",
        "Kết quả lọc",
    ]
    output_columns = khlcnt_output_columns if should_crawl_khlcnt_details() else legacy_output_columns
    legacy_dedup_subset = ["Loại thông tin", "Keyword crawl", "Mã TBMT", "Chủ đầu tư", "Tên gói thầu"]
    khlcnt_dedup_subset = [
        "Loại thông tin",
        "Keyword crawl",
        "Mã KHLCNT",
        "Chủ đầu tư",
        "Tên KHLCNT",
        "Tên gói thầu",
    ]
    dedup_subset = khlcnt_dedup_subset if should_crawl_khlcnt_details() else legacy_dedup_subset

    dedup_all = pd.DataFrame(all_records)
    for column in output_columns:
        if column not in dedup_all.columns:
            dedup_all[column] = None
    dedup_all = dedup_all[output_columns].drop_duplicates(subset=dedup_subset)

    if not should_crawl_khlcnt_details():
        dedup_all.to_excel(os.path.join(out_dir, OUTPUT_NAME), index=False, engine="openpyxl")

        selected_count = int((dedup_all["Kết quả lọc"] == "CHỌN").sum()) if not dedup_all.empty else 0
        filtered_count = int((dedup_all["Kết quả lọc"] == "LOẠI").sum()) if not dedup_all.empty else 0
        logger.info(
            "Đã lưu %s: %s dòng | CHỌN: %s | LOẠI: %s",
            OUTPUT_NAME,
            len(dedup_all),
            selected_count,
            filtered_count,
        )
    else:
        logger.info("TEST_CRAWL_TASK=2: bỏ qua xuất %s, chỉ xuất workbook KHLCNT test metadata + excel/attachment.", OUTPUT_NAME)

    if ENABLE_KEYWORD_NGRAMS and not should_crawl_khlcnt_details():
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
        logger.info("Không xuất keyword_ngrams.xlsx trong mode hiện tại.")

    if should_crawl_khlcnt_details() and khlcnt_outputs:
        child_columns = [
            "Loại thông tin",
            "Keyword crawl",
            "Chế độ khớp",
            "Trang kết quả",
            "Mã TBMT hiệu lực",
            "Mã TBMT từ XHR",
            "URL gói thầu con",
            "Có tab KQLCNT",
            "Cho phép ghi nhận DB",
            "Phiên bản KQLCNT",
            "Mã KHLCNT",
            "Mã KHLCNT đầy đủ",
            "Phiên bản KHLCNT",
            "Tên KHLCNT",
            "Chủ đầu tư",
            "STT gói thầu con",
            "Tên gói thầu con",
            "Tên gói thầu",
            "Dự toán gói thầu sau KHLCNT",
            "Giá gói thầu",
            "Số thông báo liên kết",
            "Nhánh xử lý",
            "Card dữ liệu",
            "Có nút Xuất Excel",
            "Phương thức thu thập bảng",
            "Số cột bảng",
            "Số dòng bảng",
            "Số trang bảng",
            "Tên file tải thử",
            "Đường dẫn file tải thử",
            "Tên attachment fallback",
            "Đấu thầu qua mạng",
            "Trong nước/ Quốc tế",
            "Lĩnh vực",
            "Hình thức LCNT",
            "Hình thức lựa chọn nhà thầu",
            "Phương thức lựa chọn nhà thầu",
            "Loại hợp đồng",
            "Phân loại gói thầu",
            "Thời gian thực hiện gói thầu",
            "Ngày đăng tải",
            "Ngày phê duyệt",
            "Cơ quan phê duyệt",
            "Số quyết định phê duyệt",
            "Kết quả lọc",
            "Lý do",
        ]
        plan_skip_columns = khlcnt_output_columns + [
            "Lý do",
            "Số dòng con",
            "Số dòng con hợp lệ",
            "Số dòng con bị loại",
        ]
        linked_child_columns = [
            "Loại thông tin",
            "Keyword crawl",
            "Chế độ khớp",
            "Trang kết quả",
            "Mã TBMT hiệu lực",
            "Mã KHLCNT",
            "Mã KHLCNT đầy đủ",
            "Phiên bản KHLCNT",
            "Tên KHLCNT",
            "Chủ đầu tư",
            "STT gói thầu con",
            "Tên gói thầu con",
            "Dự toán gói thầu sau KHLCNT",
            "Giá gói thầu",
            "Số thông báo liên kết",
            "Nhánh xử lý",
            "Cho phép ghi nhận DB",
            "Phương thức thu thập bảng",
            "Kết quả lọc",
            "Lý do",
        ]
        table_row_columns = [
            "Mã KHLCNT",
            "Mã KHLCNT đầy đủ",
            "Tên KHLCNT",
            "Tên gói thầu con",
            "Mã TBMT hiệu lực",
            "Card dữ liệu",
            "Trang bảng",
            "Dòng trên trang",
        ]
        khlcnt_path = os.path.join(out_dir, "khlcnt_child_packages.xlsx")
        with pd.ExcelWriter(khlcnt_path, engine="openpyxl") as writer:
            for sheet_name, columns in [
                ("matched_child_packages", child_columns),
                ("pending_child_packages", child_columns),
                ("filtered_child_packages", child_columns),
                ("linked_child_packages", linked_child_columns),
                ("child_table_rows", table_row_columns),
                ("filtered_skip_khlcnt", plan_skip_columns),
                ("khlcnt_plans", khlcnt_output_columns),
            ]:
                rows = khlcnt_outputs.get(sheet_name, [])
                df = pd.DataFrame(rows)
                for column in columns:
                    if column not in df.columns:
                        df[column] = None
                if sheet_name == "child_table_rows":
                    dynamic_columns = [col for col in df.columns if col not in columns]
                    df[columns + dynamic_columns].to_excel(writer, sheet_name=sheet_name[:31], index=False)
                else:
                    df[columns].to_excel(writer, sheet_name=sheet_name[:31], index=False)
        logger.info(
            "Đã lưu khlcnt_child_packages.xlsx: CHỌN child=%s | child bị loại=%s | child có TBMT=%s | child treo=%s | KHLCNT skip=%s",
            len(khlcnt_outputs.get("matched_child_packages", [])),
            len(khlcnt_outputs.get("filtered_child_packages", [])),
            len(khlcnt_outputs.get("linked_child_packages", [])),
            len(khlcnt_outputs.get("pending_child_packages", [])),
            len(khlcnt_outputs.get("filtered_skip_khlcnt", [])),
        )


def main():
    if not SEARCH_KEYWORDS:
        raise ValueError("Thiếu KEY hoặc KEY_BATCHES để test.")

    test_extract_tbmt_codes_example()
    all_records = []
    khlcnt_outputs = {
        "matched_child_packages": [],
        "filtered_child_packages": [],
        "linked_child_packages": [],
        "pending_child_packages": [],
        "filtered_skip_khlcnt": [],
        "khlcnt_plans": [],
        "child_table_rows": [],
    }

    try:
        init_runtime()
        logger.info("TEST_CRAWL_TASK=%s", TEST_CRAWL_TASK)
        for notice_type in SEARCH_NOTICE_TYPE_LIST:
            for keyword in SEARCH_KEYWORDS:
                logger.info("=" * 60)
                logger.info("Đang test loại thông tin: %s | keyword: %s", notice_type, keyword)
                logger.info("=" * 60)
                active_notice_type = prepare_search_form(keyword, notice_type=notice_type)
                if should_crawl_khlcnt_details() and is_khlcnt_notice_type(active_notice_type):
                    khlcnt_result = crawl_khlcnt_current_results(
                        keyword,
                        page_limit=MAX_PAGES,
                        notice_type=active_notice_type,
                    )
                    all_records.extend(khlcnt_result["plans"])
                    khlcnt_outputs["khlcnt_plans"].extend(khlcnt_result["plans"])
                    khlcnt_outputs["matched_child_packages"].extend(khlcnt_result["matched_child_packages"])
                    khlcnt_outputs["filtered_child_packages"].extend(khlcnt_result["filtered_child_packages"])
                    khlcnt_outputs["linked_child_packages"].extend(khlcnt_result["linked_child_packages"])
                    khlcnt_outputs["pending_child_packages"].extend(khlcnt_result["pending_child_packages"])
                    khlcnt_outputs["filtered_skip_khlcnt"].extend(khlcnt_result["plan_skips"])
                    khlcnt_outputs["child_table_rows"].extend(khlcnt_result.get("child_table_rows", []))
                else:
                    all_records.extend(
                        crawl_current_results(
                            keyword,
                            page_limit=MAX_PAGES,
                            notice_type=active_notice_type,
                        )
                    )

        classified_records = classify_records(all_records)
        save_outputs(classified_records, khlcnt_outputs=khlcnt_outputs)
    finally:
        shutdown_runtime()


if __name__ == "__main__":
    main()
