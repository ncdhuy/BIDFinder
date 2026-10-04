from __future__ import annotations

import json
import os
from pathlib import Path
import unittest


class BrowserUiRecoveryTest(unittest.TestCase):
    """Authenticated browser regression for the legacy Typesense workflow."""

    @classmethod
    def setUpClass(cls):
        url = os.getenv("BIDFINDER_BROWSER_TEST_URL")
        email = os.getenv("BIDFINDER_BROWSER_AUTH_EMAIL")
        password = os.getenv("BIDFINDER_BROWSER_AUTH_PASSWORD")
        if not url or not email or not password:
            raise unittest.SkipTest(
                "set BIDFINDER_BROWSER_TEST_URL, BIDFINDER_BROWSER_AUTH_EMAIL, "
                "and BIDFINDER_BROWSER_AUTH_PASSWORD to run the live browser check"
            )

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as error:
            raise unittest.SkipTest(f"Selenium unavailable: {error}") from error

        cls.By = By
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1365,900")
        options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        cls.driver = webdriver.Chrome(options=options)
        cls.wait = WebDriverWait(cls.driver, 40)
        cls.url = url
        cls.email = email
        cls.password = password
        cls.screenshot_dir = Path(os.getenv("BIDFINDER_BROWSER_SCREENSHOT_DIR", "ui-search-recovery-screenshots"))
        cls.screenshot_dir.mkdir(parents=True, exist_ok=True)

        api_base_url = os.getenv("BIDFINDER_BROWSER_API_BASE_URL")
        if api_base_url:
            cls.driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": f"window.API_BASE_URL = {json.dumps(api_base_url)};"},
            )
        cls.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    window.__bidfinderQueryResponses = [];
                    const __bidfinderFetch = window.fetch.bind(window);
                    window.fetch = async (...args) => {
                      const response = await __bidfinderFetch(...args);
                      const requestUrl = String(args[0]?.url || args[0] || '');
                      if (new URL(requestUrl, location.href).pathname === '/api/query') {
                        let requestBody = args[1]?.body || '';
                        try { requestBody = JSON.parse(requestBody); } catch (_) {}
                        response.clone().json().then(payload =>
                          window.__bidfinderQueryResponses.push({status: response.status, payload, request: requestBody})
                        );
                      }
                      return response;
                    };
                """,
            },
        )
        cls.open_app()

    @classmethod
    def open_app(cls):
        cls.driver.get(cls.url)
        cls.driver.implicitly_wait(2)
        body = cls.driver.find_element(cls.By.TAG_NAME, "body")
        if "landing-active" in body.get_attribute("class").split():
            cls.driver.find_element(cls.By.ID, "open-login-nav").click()
            cls.wait.until(lambda driver: "show" in driver.find_element(cls.By.ID, "auth-modal").get_attribute("class"))
            login_mode = cls.driver.find_element(cls.By.CSS_SELECTOR, '[data-auth-mode="login"]')
            if login_mode.is_displayed():
                login_mode.click()
            cls.driver.find_element(cls.By.ID, "login-email").send_keys(cls.email)
            cls.driver.find_element(cls.By.ID, "login-password").send_keys(cls.password)
            cls.driver.find_element(cls.By.CSS_SELECTOR, "#auth-login-form button[type=submit]").click()
            cls.wait.until(lambda driver: "show" not in driver.find_element(cls.By.ID, "auth-modal").get_attribute("class"))

        if "landing-active" in cls.driver.find_element(cls.By.TAG_NAME, "body").get_attribute("class").split():
            cls.driver.find_element(cls.By.ID, "enter-app-btn-hero").click()
        cls.wait.until(
            lambda driver: driver.execute_script(
                "return !document.body.classList.contains('landing-active') && "
                "Boolean(document.querySelector('typesense-search-form')?.shadowRoot)"
            )
        )

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            try:
                cls.driver.save_screenshot(str(cls.screenshot_dir / "final-state.png"))
            finally:
                cls.driver.quit()

    def shot(self, name: str):
        self.driver.save_screenshot(str(self.screenshot_dir / f"{name}.png"))

    def open_advanced(self):
        panel = self.driver.find_element(self.By.ID, "filter-panel")
        if "show" not in panel.get_attribute("class"):
            self.driver.find_element(self.By.ID, "open-filter-panel").click()
        self.wait.until(lambda driver: "show" in driver.find_element(self.By.ID, "filter-panel").get_attribute("class"))

    def close_advanced(self):
        panel = self.driver.find_element(self.By.ID, "filter-panel")
        if "show" in panel.get_attribute("class"):
            self.driver.find_element(self.By.ID, "close-filter-panel").click()
            self.wait.until(lambda driver: "show" not in driver.find_element(self.By.ID, "filter-panel").get_attribute("class"))

    def select_group_and_subtype(self, group: str, subtype: str | None = None):
        self.open_advanced()
        form = self.driver.find_element(self.By.CSS_SELECTOR, "typesense-search-form")
        shadow = form.shadow_root
        shadow.find_element(self.By.CSS_SELECTOR, f'[data-group="{group}"]').click()
        self.wait.until(lambda driver: len(form.shadow_root.find_elements(self.By.CSS_SELECTOR, "input[data-source-type]")) > 0)
        if subtype:
            form.shadow_root.find_element(self.By.CSS_SELECTOR, f'[data-source-type="{subtype}"]').click()

    def apply_advanced_search(self):
        self.open_advanced()
        form = self.driver.find_element(self.By.CSS_SELECTOR, "typesense-search-form")
        before = self.driver.execute_script("return window.__bidfinderQueryResponses.length")
        apply_button = form.shadow_root.find_element(self.By.CSS_SELECTOR, '[data-action="apply"]')
        self.driver.execute_script("arguments[0].disabled = false;", apply_button)
        apply_button.click()
        response = self.wait.until(
            lambda driver: driver.execute_script(
                "return window.__bidfinderQueryResponses.length > arguments[0] "
                "? window.__bidfinderQueryResponses.at(-1) : null",
                before,
            )
        )
        self.assertEqual(200, response["status"], response)
        self.assertEqual("typesense", response["payload"].get("backend"), response)
        request = response.get("request") or {}
        self.assertIn("group", request, request)
        self.assertIn("sourceTypes", request, request)
        self.assertIn("filters", request, request)
        self.assertNotIn("query_by", request, request)
        self.assertNotIn("filter_by", request, request)
        page = next(
            (response["payload"].get(key) or {} for key in ("df1", "df2", "df3") if response["payload"].get(key)),
            {},
        )
        self.assertGreater(len(page.get("data") or []), 0, response)
        self.wait.until(
            lambda driver: driver.execute_script(
                "return [...document.querySelectorAll('.result-panel.active tbody tr')].some(row => "
                "!row.querySelector('.table-empty-state'));"
            )
        )
        self.assertNotIn("Dịch vụ tìm kiếm tạm thời không khả dụng", self.driver.find_element(self.By.TAG_NAME, "body").text)
        return response, page

    def test_legacy_shell_and_toolbar_are_visible(self):
        state = self.driver.execute_script(
            """
            const visible = element => {
              if (!element) return false;
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const toolbar = document.querySelector('.result-table-tabs');
            const viewport = document.documentElement.clientWidth;
            return {
              topScope: Boolean(document.getElementById('legacy-dataset-controls')),
              resultTabs: visible(document.getElementById('data-view-switcher')),
              advancedButton: visible(document.getElementById('open-filter-panel')),
              insightButton: visible(document.getElementById('open-insight-drawer')),
              insightRight: document.getElementById('open-insight-drawer')?.getBoundingClientRect().right,
              toolbarRight: toolbar?.getBoundingClientRect().right,
              viewport
            };
            """
        )
        self.assertFalse(state["topScope"], state)
        self.assertTrue(state["resultTabs"], state)
        self.assertTrue(state["advancedButton"], state)
        self.assertTrue(state["insightButton"], state)
        self.assertLessEqual(state["insightRight"], state["viewport"] + 1, state)
        self.assertLessEqual(state["toolbarRight"], state["viewport"] + 1, state)
        self.shot("01-legacy-table-toolbar")

    def test_advanced_scope_and_contract_controls_are_in_legacy_panel(self):
        self.open_advanced()
        panel = self.driver.find_element(self.By.ID, "filter-panel")
        form = panel.find_element(self.By.CSS_SELECTOR, "typesense-search-form")
        scope = form.shadow_root
        self.assertEqual(3, len(scope.find_elements(self.By.CSS_SELECTOR, "[data-group]")))
        self.assertEqual(3, len(scope.find_elements(self.By.CSS_SELECTOR, "input[data-source-type]")))
        self.assertGreater(len(scope.find_elements(self.By.CSS_SELECTOR, "[data-filter-target]")), 0)
        self.assertTrue(scope.find_element(self.By.CSS_SELECTOR, ".ts-filter-sidebar").is_displayed())
        self.shot("02-advanced-search-open")

        for group, expected_count, screenshot in (
            ("goods", 2, "03-advanced-search-goods"),
            ("medicines", 3, "04-advanced-search-medicines"),
            ("traditional", 2, "05-advanced-search-traditional"),
        ):
            scope.find_element(self.By.CSS_SELECTOR, f'[data-group="{group}"]').click()
            self.assertEqual(
                expected_count,
                len(scope.find_elements(self.By.CSS_SELECTOR, "input[data-source-type]")),
            )
            self.shot(screenshot)

        self.close_advanced()

    def test_authenticated_typesense_rows_all_subtypes_and_pagination(self):
        journeys = (
            ("goods", ("goods_general", "medical_devices"), "df2-panel"),
            ("medicines", ("medicine_generic", "medicine_originator", "medicine_herbal"), "df1-panel"),
            ("traditional", ("herbal_material", "traditional_medicine"), "df3-panel"),
        )
        seen = {}
        for group, subtypes, panel_id in journeys:
            for subtype in subtypes:
                self.select_group_and_subtype(group, subtype)
                response, page = self.apply_advanced_search()
                seen[subtype] = page["data"][0].get("id")
                self.shot(f"06-result-{subtype}")
                self.assertTrue(response["payload"].get("success"))
                self.assertTrue(self.driver.find_element(self.By.ID, panel_id).is_displayed())

            if group == "goods":
                first_id = response["payload"]["df2"]["data"][0]["id"]
                next_button = self.driver.find_element(self.By.ID, "legacy-next-page")
                self.assertTrue(next_button.is_enabled())
                before = self.driver.execute_script("return window.__bidfinderQueryResponses.length")
                next_button.click()
                next_response = self.wait.until(
                    lambda driver: driver.execute_script(
                        "return window.__bidfinderQueryResponses.length > arguments[0] "
                        "? window.__bidfinderQueryResponses.at(-1) : null",
                        before,
                    )
                )
                self.assertEqual(200, next_response["status"], next_response)
                self.assertEqual("typesense", next_response["payload"].get("backend"), next_response)
                self.assertNotEqual(first_id, next_response["payload"]["df2"]["data"][0]["id"])
                self.assertIn("Trang 2", self.driver.find_element(self.By.ID, "legacy-page-label").text)
                self.shot("07-pagination-page-2")
                self.driver.find_element(self.By.ID, "legacy-prev-page").click()
                self.wait.until(lambda driver: "Trang 1" in driver.find_element(self.By.ID, "legacy-page-label").text)

            panel = self.driver.find_element(self.By.ID, panel_id)
            row = panel.find_element(self.By.CSS_SELECTOR, "tbody tr")
            cell = row.find_elements(self.By.TAG_NAME, "td")[1]
            self.driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('click', {bubbles:true}));", cell)
            self.assertTrue(self.driver.find_element(self.By.ID, "legacy-row-detail").get_attribute("hidden"))
            self.driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('dblclick', {bubbles:true}));", cell)
            self.wait.until(lambda driver: "show" in driver.find_element(self.By.ID, "legacy-row-detail").get_attribute("class"))
            detail_text = self.driver.find_element(self.By.ID, "legacy-row-detail").text
            self.assertTrue(detail_text.strip())
            self.assertNotIn("serving_v1_", detail_text)
            self.assertNotIn("typesense-search-contract-v1", detail_text)
            self.assertNotRegex(detail_text, r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", detail_text)
            self.assertEqual("fixed", self.driver.execute_script("return getComputedStyle(document.getElementById('legacy-row-detail')).position"))
            self.shot(f"08-detail-{group}")
            self.driver.find_element(self.By.ID, "close-legacy-row-detail").click()
            self.wait.until(lambda driver: driver.find_element(self.By.ID, "legacy-row-detail").get_attribute("hidden"))

        self.assertEqual(
            {
                "goods_general", "medical_devices", "medicine_generic", "medicine_originator",
                "medicine_herbal", "herbal_material", "traditional_medicine",
            },
            set(seen),
        )

    def test_no_fatal_browser_errors_or_generic_search_error(self):
        fatal_logs = [
            entry for entry in self.driver.get_log("browser")
            if entry["level"] == "SEVERE" and not any(
                allowed in entry["message"]
                for allowed in ("favicon.ico", "accounts.google.com/gsi", "posthog", "frame-ancestors")
            )
        ]
        self.assertEqual([], fatal_logs, json.dumps(fatal_logs, ensure_ascii=False))
        self.assertNotIn("Dịch vụ tìm kiếm tạm thời không khả dụng", self.driver.find_element(self.By.TAG_NAME, "body").text)


if __name__ == "__main__":
    unittest.main()
