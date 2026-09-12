from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TypesenseUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / "typesense-search-contract.json").read_text(encoding="utf-8"))
        cls.script_source = (ROOT / "apps/web/script.js").read_text(encoding="utf-8")
        cls.index_source = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
        cls.form_source = (ROOT / "apps/web/typesense-search-form.js").read_text(encoding="utf-8")
        cls.legacy_form_source = (ROOT / "apps/web/search-form.js").read_text(encoding="utf-8")
        cls.api_typesense_shadow_source = (ROOT / "apps/api/typesense_shadow.py").read_text(encoding="utf-8")
        cls.api_source = (ROOT / "apps/api/server.py").read_text(encoding="utf-8")

    def test_contract_has_three_groups_seven_subtypes_and_88_fields(self):
        groups = self.contract["groups"]
        self.assertEqual({"goods", "medicines", "traditional"}, set(groups))
        self.assertEqual(7, sum(len(group["source_types"]) for group in groups.values()))
        self.assertEqual(88, sum(len(group["fields"]) for group in groups.values()))

    def test_advanced_search_is_the_unified_typesense_panel(self):
        for token in (
            'id="filter-panel"',
            '<typesense-search-form>',
            'id="data-view-switcher"',
            'id="legacy-pagination"',
            'id="legacy-row-detail"',
        ):
            self.assertIn(token, self.index_source)
        self.assertNotIn('id="legacy-dataset-controls"', self.index_source)
        self.assertNotIn("Phạm vi dữ liệu", self.index_source)
        self.assertNotIn("<typesense-results-ui", self.index_source)
        self.assertNotIn("<custom-search-form", self.index_source)
        self.assertNotIn("serving_v1_20260901", self.index_source)
        self.assertNotIn("typesense-search-contract-v1", self.index_source)
        self.assertIn('Dược liệu</span>', self.index_source)
        for label in (
            "Hàng hóa ngoài thuốc, thiết bị, vật tư y tế",
            "Thiết bị, vật tư y tế",
            "Generic",
            "biệt dược gốc",
            "Thuốc dược liệu",
            "Dược liệu",
            "Vị thuốc cổ truyền",
        ):
            self.assertIn(label, self.script_source)

    def test_advanced_search_uses_group_specific_hints_without_changing_field_order(self):
        self.assertIn("const GROUP_FIELD_HINTS = {", self.form_source)
        self.assertIn("traditional: {", self.form_source)
        self.assertIn("item_name: 'VD: Bạch linh, đan sâm...'", self.form_source)
        self.assertIn("registration_or_import_permit_number: 'VD: VCT-123456-78...'", self.form_source)
        self.assertIn("unit: 'VD: Kg, gram, gói...'", self.form_source)
        self.assertIn("packaging: 'VD: Gói 1-5kg, túi 500g...'", self.form_source)
        self.assertIn("fieldHint(name) { return GROUP_FIELD_HINTS[this.state.group]?.[name]", self.form_source)

        traditional_order = re.search(r"traditional: \[(.*?)\]", self.form_source, re.DOTALL)
        self.assertIsNotNone(traditional_order)
        self.assertLess(traditional_order.group(1).index("item_name"), traditional_order.group(1).index("used_part"))
        self.assertLess(traditional_order.group(1).index("registration_or_import_permit_number"), traditional_order.group(1).index("unit"))

    def test_cross_group_product_fields_share_one_search_contract(self):
        self.assertIn("const CROSS_GROUP_PRODUCT_SEARCH_FIELDS = [", self.form_source)
        self.assertIn("medicines: new Set(['medicine_name', 'active_ingredient_or_herbal_component'])", self.form_source)
        self.assertIn("traditional: new Set(['item_name'])", self.form_source)
        self.assertIn("crossGroupProductKeyword", self.form_source)
        self.assertIn("scope: crossGroupSearch ? 'all'", self.form_source)
        self.assertIn("group: crossGroupSearch ? null", self.form_source)
        self.assertIn("crossGroupSearchFields", self.form_source)
        self.assertIn("crossGroupSearch ? 'all' : definition.scope", self.script_source)
        query_body_start = self.script_source.index("const requestBody = {")
        query_body_end = self.script_source.index("body: JSON.stringify(requestBody)", query_body_start)
        self.assertIn(
            "crossGroupSearch: queryRequest?.crossGroupSearch === true",
            self.script_source[query_body_start:query_body_end],
        )
        preview_start = self.script_source.index("async function fetchQueryPreview(")
        preview_body_start = self.script_source.index("body: JSON.stringify({", preview_start)
        preview_body_end = self.script_source.index("}),", preview_body_start)
        self.assertIn(
            "crossGroupSearch: queryRequest?.crossGroupSearch === true",
            self.script_source[preview_body_start:preview_body_end],
        )
        self.assertIn(
            "crossGroupSearchFields: queryRequest?.crossGroupSearchFields || []",
            self.script_source[query_body_start:query_body_end],
        )
        for fields in (
            '("item_name", "model_mark", "brand", "technical_specification")',
            '("medicine_name", "active_ingredient_or_herbal_component")',
            '("item_name",)',
        ):
            self.assertIn(f'"crossGroupProductKeyword": {fields}', self.api_typesense_shadow_source)

    def test_advanced_search_uses_closed_multi_select_dropdowns_and_vietnamese_date_ranges(self):
        self.assertIn("const TECHNICAL_GROUPS = MEDICINE_GROUPS;", self.form_source)
        self.assertIn("this.renderDropdownControl(field.name, criterion)", self.form_source)
        self.assertIn('data-dropdown-toggle', self.form_source)
        self.assertIn('data-dropdown-option', self.form_source)
        self.assertIn('this.syncDropdownField(input.dataset.dropdownOption)', self.form_source)
        self.assertIn('data-date-range', self.form_source)
        self.assertIn('placeholder="dd/mm/yyyy"', self.form_source)
        self.assertIn('this.parseVietnameseDate', self.form_source)
        self.assertIn('dateRanges', self.form_source)
        self.assertNotIn('data-dropdown-apply', self.form_source)
        self.assertNotIn('data-dropdown-cancel', self.form_source)
        self.assertIn("'UNKNOWN', 'Chưa xác định được'", self.form_source)
        self.assertIn("SELECTION_METHOD_LABELS.get", self.form_source)
        self.assertIn("if (Boolean(from) !== Boolean(to)) return;", self.form_source)
        self.assertNotIn('<select id="criterion-value" multiple>', self.form_source)
        self.assertNotIn('field.name === \'medicine_group\') {\n                const selected = new Set', self.form_source)

    def test_result_tabs_follow_goods_medicine_traditional_order_and_themes(self):
        tab_markup = self.index_source[self.index_source.index('class="result-table-tab-choice"'):self.index_source.index('id="insight-full-search"')]
        self.assertLess(tab_markup.index('data-view="df2-panel"'), tab_markup.index('data-view="df1-panel"'))
        self.assertLess(tab_markup.index('data-view="df1-panel"'), tab_markup.index('data-view="df3-panel"'))
        self.assertEqual(tab_markup.count('class="tab-plate"'), 3)

        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        for rule in (
            '--genoffice-tabstrip-bg: #ebebeb;',
            '--genoffice-tabstrip-text: #454746;',
            '--genoffice-tabstrip-text-active: #1f1f1f;',
            '--genoffice-tab-separator: rgba(0, 0, 0, 0.22);',
            "font-family: -apple-system, var(--genoffice-ui-cjk), 'Segoe UI', 'Microsoft YaHei', sans-serif;",
            'height: 40px;',
            'margin-top: 6px;',
            'padding: 0 11px 6px 12px;',
            'flex: 0 0 160px;',
            'width: 160px;',
            'min-width: 160px;',
            'max-width: 160px;',
            'gap: 8px;',
            'border-radius: 10px 10px 0 0;',
            'inset: 0 3px 6px;',
            'background: rgba(255, 255, 255, 0.85);',
            'text-overflow: ellipsis;',
            'overflow-x: auto;',
            'height: 16px;',
            'white-space: nowrap;',
        ):
            self.assertIn(rule, style_source)
        self.assertIn('--tab-accent: var(--insight-action-ink);', style_source)
        self.assertIn('--tab-accent: var(--history-action-ink);', style_source)
        self.assertIn('--tab-accent: var(--advanced-action-ink);', style_source)
        self.assertNotIn('border-bottom: var(--action-border-width) solid var(--tab-border);', style_source)

    def test_result_tabs_keep_equal_fixed_widths_when_counts_differ(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        tab_start = style_source.index(".result-table-tabs .result-table-tab.scope-btn {")
        tab_end = style_source.index("}", tab_start)
        tab_rule = style_source[tab_start:tab_end]
        self.assertIn("width: 160px;", tab_rule)
        self.assertIn("min-width: 160px;", tab_rule)
        self.assertIn("max-width: 160px;", tab_rule)
        self.assertIn("flex: 0 0 160px;", tab_rule)
        self.assertNotIn("min-width: max-content;", tab_rule)

    def test_wrapped_column_expands_the_whole_row(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        self.assertIn(
            ".data-table tbody tr.row-content-wrap > td:not(.row-selector-cell)",
            style_source,
        )
        self.assertIn("white-space: normal !important;", style_source)
        self.assertIn("text-overflow: clip !important;", style_source)
        self.assertIn("row.classList.toggle('row-content-wrap', wrappedColumns.size > 0);", self.script_source)

    def test_result_tab_counts_are_single_capped_notification_badges(self):
        for element_id in ("df1-count-switcher", "df2-count-switcher", "df3-count-switcher"):
            self.assertIn(f'<span class="scope-count" id="{element_id}">0</span>', self.index_source)

        self.assertIn("function getResultTableCountLabel(tableId, fallbackCount = 0)", self.script_source)
        self.assertIn("if (limit > 0 && (safeTotal > limit || (isWorkingSetTruncated && safeTotal >= limit)))", self.script_source)
        self.assertIn("const updateTabCountElement = (element, view) => {", self.script_source)
        self.assertIn("className: 'scope-count-plus'", self.script_source)
        self.assertIn("element.classList.toggle('has-value', label !== '0');", self.script_source)
        self.assertIn("updateTabCountElement(df1CountEl, 'df1-panel');", self.script_source)
        self.assertIn("updateTabCountElement(df2CountEl, 'df2-panel');", self.script_source)
        self.assertIn("updateTabCountElement(df3CountEl, 'df3-panel');", self.script_source)

        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        badge_start = style_source.index(".result-table-tab .scope-count {")
        badge_end = style_source.index("}", badge_start)
        badge_rule = style_source[badge_start:badge_end]
        self.assertIn("background: var(--color-surface);", badge_rule)
        self.assertIn("color: var(--genoffice-tabstrip-text);", badge_rule)
        self.assertIn("border-radius: 999px !important;", badge_rule)
        self.assertIn("white-space: nowrap;", badge_rule)

        value_start = style_source.index(".result-table-tab .scope-count.has-value {")
        value_end = style_source.index("}", value_start)
        value_rule = style_source[value_start:value_end]
        self.assertIn("background: #d92d20;", value_rule)
        self.assertIn("color: #fff;", value_rule)
        self.assertIn("min-width: 20px;", value_rule)

    def test_main_toolbar_is_one_chrome_surface_with_accessible_icon_commands(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        toolbar_start = self.index_source.index('<div class="result-table-tabs toolbar"')
        toolbar_end = self.index_source.index('<!-- Bảng DF1 -->', toolbar_start)
        toolbar_markup = self.index_source[toolbar_start:toolbar_end]

        self.assertIn('class="result-table-tab-list toolbar-navigation"', toolbar_markup)
        self.assertEqual(1, toolbar_markup.count('class="toolbar-divider"'))
        self.assertIn('class="workspace-actions toolbar-actions"', toolbar_markup)
        action_order = (
            'id="insight-full-search"',
            'id="open-run-history"',
            'id="open-bulk-search-modal"',
            'id="open-filter-panel"',
            'id="open-insight-drawer"',
        )
        action_positions = [toolbar_markup.index(token) for token in action_order]
        self.assertEqual(sorted(action_positions), action_positions)

        for action_id, label in (
            ("open-run-history", "Lịch sử cập nhật"),
            ("open-bulk-search-modal", "Tìm kiếm hàng loạt"),
            ("open-filter-panel", "Tìm kiếm nâng cao"),
            ("open-insight-drawer", "Phân tích trực quan"),
        ):
            button = re.search(rf'<button[^>]*id="{action_id}"[^>]*>(?P<body>[\s\S]*?)</button>', toolbar_markup)
            self.assertIsNotNone(button)
            self.assertIn(f'aria-label="{label}"', button.group(0))
            self.assertIn(f'title="{label}"', button.group(0))
            self.assertNotIn("action-btn-label", button.group("body"))
            self.assertNotRegex(button.group("body"), rf">\s*{re.escape(label)}\s*<")

        script_source = (ROOT / "apps/web/script.js").read_text(encoding="utf-8")
        self.assertIn("function initActionTooltips()", script_source)
        self.assertIn("function setActionTooltip(button, label)", script_source)
        self.assertIn(".full-search-credit, .app-icon-btn", script_source)
        self.assertIn("button.dataset.title = label", script_source)
        self.assertNotIn("disableDefaultTooltips", script_source)
        self.assertNotIn("openButton.title =", script_source)
        self.assertNotIn("formatDockResultLine", script_source)
        self.assertIn(".bf-action-tooltip {", style_source)
        self.assertIn("position: fixed;", style_source)
        self.assertIn("z-index: 2147483000;", style_source)
        for tooltip_target in (
            "function getActionTooltipElement()",
            "function positionActionTooltip()",
            "function showActionTooltip(button)",
            "button.addEventListener('mouseenter'",
            "button.addEventListener('focusin'",
        ):
            self.assertIn(tooltip_target, script_source)

        for button_id in (
            "open-product-journey",
            "auth-edit-profile-btn",
            "open-feedback-modal",
        ):
            button = re.search(rf'<button[^>]*id="{button_id}"[^>]*>', self.index_source)
            self.assertIsNotNone(button)
            self.assertIn("aria-label=", button.group(0))
            self.assertIn("title=", button.group(0))

        auth_source = (ROOT / "apps/web/auth.js").read_text(encoding="utf-8")
        self.assertIn("els['auth-edit-profile-btn'].dataset.title = 'Tài khoản'", auth_source)
        self.assertIn("els['auth-edit-profile-btn'].removeAttribute('title')", auth_source)

        for rule in (
            ".result-table-tabs.toolbar {",
            "width: 100%;",
            "background: var(--genoffice-tabstrip-bg);",
            ".result-table-tabs .toolbar-divider {",
            "flex: 0 0 1px;",
            "height: 16px;",
            ".result-table-tabs .toolbar-actions {",
            "margin-left: auto;",
            "flex-wrap: nowrap;",
            "gap: 8px;",
            "width: 34px;",
            "min-width: 34px;",
            "white-space: nowrap;",
            "@media (max-width: 900px)",
        ):
            self.assertIn(rule, style_source)
        for stale_tone in (
            ".workspace-actions .action-tone-history",
            ".workspace-actions .action-tone-bulk",
            ".workspace-actions .action-tone-advanced",
            ".workspace-actions .action-tone-insight",
        ):
            self.assertNotIn(stale_tone, style_source)

    def test_header_utility_buttons_use_compact_group_spacing(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        self.assertIn(".app-header-links {\n  gap: 8px;\n}", style_source)
        self.assertNotIn("gap: clamp(14px, 1.8vw, 28px);", style_source)

    def test_result_panel_switch_is_immediate_without_animation(self):
        self.assertIn("function activateResultView(targetId) {", self.script_source)
        self.assertIn("resultPanels.forEach(panel => panel.classList.remove('active'));", self.script_source)
        self.assertIn("targetPanel.classList.add('active');", self.script_source)
        self.assertNotIn("resultPanelSwitchTimer", self.script_source)
        self.assertNotIn("transitionResultPanels", self.script_source)
        self.assertNotIn("currentPanel.animate", self.script_source)

    def test_new_query_selects_tab_from_bounded_working_set_counts(self):
        self.assertIn("function selectResultViewWithMostRows() {", self.script_source)
        self.assertIn("currentQueryMeta.df2WorkingCount", self.script_source)
        self.assertIn("currentQueryMeta.df1WorkingCount", self.script_source)
        self.assertIn("currentQueryMeta.df3WorkingCount", self.script_source)
        self.assertNotIn("function autoSwitchToAvailableResult()", self.script_source)
        self.assertNotIn("autoSwitchToResults", self.script_source)

        query_success_start = self.script_source.index("function handleQuerySuccess(result, options = {}) {")
        query_success_end = self.script_source.index("async function applyFilters", query_success_start)
        query_success = self.script_source[query_success_start:query_success_end]
        self.assertIn("selectResultViewWithMostRows();", query_success)

        page_refresh_start = self.script_source.index("function refreshBoundedWorkingSetViews(")
        page_refresh_end = self.script_source.index("function updateColumnOrder", page_refresh_start)
        page_refresh = self.script_source[page_refresh_start:page_refresh_end]
        self.assertNotIn("selectResultViewWithMostRows();", page_refresh)

        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        self.assertIn("#data-tab > .result-panel {\n  display: none !important;", style_source)
        self.assertIn("#data-tab > .result-panel.active {\n  display: flex !important;", style_source)
        self.assertNotIn("transitionResultPanels", style_source)

    def test_all_result_tables_always_reserve_the_horizontal_scrollbar_track(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        rule_start = style_source.index("#data-tab .table-scroll {")
        rule_end = style_source.index("}", rule_start)
        scroll_rule = style_source[rule_start:rule_end]
        self.assertIn("overflow-x: scroll !important;", scroll_rule)
        self.assertIn("overflow-y: scroll !important;", scroll_rule)
        self.assertIn("scrollbar-gutter: stable;", scroll_rule)
        self.assertIn("padding: 0;", scroll_rule)
        self.assertNotIn("overflow: auto !important;", scroll_rule)
        self.assertEqual(style_source.count("scrollbar-gutter: stable;"), 1)
        self.assertNotIn("#df1-panel .table-scroll", style_source)
        self.assertNotIn("#df2-panel .table-scroll", style_source)
        self.assertNotIn("#df3-panel .table-scroll", style_source)

        script_source = (ROOT / "apps/web/script.js").read_text(encoding="utf-8")
        self.assertIn("const horizontalPadding =", script_source)
        self.assertIn("(scrollContainer?.clientWidth || 0) - horizontalPadding", script_source)

    def test_sponsor_side_space_scales_smoothly_with_viewport(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        self.assertIn(
            "--sponsor-side-space: clamp(0px, calc(25vw - 192px), 180px);",
            style_source,
        )
        self.assertIn(
            "width: calc(100% - (2 * var(--sponsor-side-space)));",
            style_source,
        )
        self.assertNotIn("calc(60vw - 768px)", style_source)

    def test_all_result_tables_use_one_always_visible_scrollbar_style(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        shared_rule_start = style_source.index("#data-tab .table-wrapper .table-scroll {")
        shared_rule_end = style_source.index("}", shared_rule_start)
        shared_rule = style_source[shared_rule_start:shared_rule_end]
        webkit_rule_start = style_source.index("#data-tab .table-wrapper .table-scroll::-webkit-scrollbar{")
        webkit_rule_end = style_source.index("}", webkit_rule_start)
        webkit_rule = style_source[webkit_rule_start:webkit_rule_end]
        scrollbar_start = style_source.index("#data-tab .table-wrapper .table-scroll::-webkit-scrollbar-track{")
        scrollbar_end = style_source.index("/* =========================\n   TABLE CORE", scrollbar_start)
        scrollbar_rules = style_source[scrollbar_start:scrollbar_end]

        for token in (
            "--table-scroll-thumb: #6f7d86;",
            "--table-scroll-thumb-hover: #596972;",
            "--table-scroll-track: #e6ebee;",
        ):
            self.assertIn(token, style_source)
        self.assertIn("scrollbar-width: thin !important;", shared_rule)
        self.assertIn("scrollbar-color: var(--table-scroll-thumb) var(--table-scroll-track) !important;", shared_rule)
        self.assertIn("width: 8px; height: 8px;", webkit_rule)
        self.assertNotIn("--t-scroll-thumb:", style_source)
        self.assertIn("background: var(--table-scroll-track);", scrollbar_rules)
        self.assertIn("background: var(--table-scroll-thumb);", scrollbar_rules)
        self.assertNotIn("background: var(--t-scroll-thumb);", scrollbar_rules)
        self.assertNotIn("background: var(--t-scroll-thumb-hover);", scrollbar_rules)

    def test_table_does_not_render_scroll_hint_and_supports_cell_keyboard_navigation(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        script_source = (ROOT / "apps/web/script.js").read_text(encoding="utf-8")
        self.assertNotIn("horizontal-scroll-hint", style_source)
        self.assertNotIn("initHorizontalScrollHint", script_source)
        self.assertIn("function initTableKeyboardNavigation(tableId)", script_source)
        for key in ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"):
            self.assertIn(key, script_source)

    def test_result_table_intrinsic_width_cannot_resize_active_panel(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        main_start = style_source.index(".main-content {")
        main_end = style_source.index("}", main_start)
        main_rule = style_source[main_start:main_end]
        self.assertIn("display: grid;", main_rule)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr);", main_rule)
        self.assertIn("min-height: 0;", main_rule)

        workspace_start = style_source.index("#data-tab.tab-content.active {")
        workspace_end = style_source.index("}", workspace_start)
        workspace_rule = style_source[workspace_start:workspace_end]
        self.assertIn("grid-template-rows: auto minmax(0, 1fr);", workspace_rule)
        self.assertIn("flex: 0 0 auto !important;", workspace_rule)
        self.assertIn("height: 100% !important;", workspace_rule)
        self.assertIn("overflow: hidden !important;", workspace_rule)

        active_panel_start = style_source.index("#data-tab > .result-panel.active {")
        active_panel_end = style_source.index("}", active_panel_start)
        active_panel_rule = style_source[active_panel_start:active_panel_end]
        self.assertIn("flex: 0 0 auto;", active_panel_rule)
        self.assertIn("height: 100%;", active_panel_rule)

        for selector in (
            "#data-tab > .result-panel {",
            "#data-tab > .result-panel > .data-card {",
            "#data-tab .table-wrapper {",
            "#data-tab .table-scroll {",
        ):
            rule_start = style_source.index(selector)
            rule_end = style_source.index("}", rule_start)
            rule = style_source[rule_start:rule_end]
            self.assertIn("width: 100%;", rule)
            self.assertIn("min-width: 0;", rule)

        self.assertNotIn("overflow: visible !important;", workspace_rule)
        self.assertNotRegex(style_source, r"(?m)^\.tab-content\.active\s*\{")

    def test_all_result_tables_share_controls_headers_and_cell_value_bar(self):
        for table_id, bar_id in (
            ("standard-table", "std-cell-bar"),
            ("extended-table", "ext-cell-bar"),
            ("traditional-table", "trad-cell-bar"),
        ):
            self.assertIn(f'class="table-wrapper" data-table-id="{table_id}"', self.index_source)
            self.assertIn(f'class="table-hover-controls" data-table-id="{table_id}"', self.index_source)
            self.assertIn(f'class="cell-display-bar" id="{bar_id}"', self.index_source)
            self.assertIn(f'class="data-table" id="{table_id}"', self.index_source)

        self.assertIn("function createHeaderCell(tableId, colName, index)", self.script_source)
        self.assertIn("Object.entries(TABLE_MAP).forEach(([tableId, config]) =>", self.script_source)
        self.assertIn("'traditional-table': 'trad-cell-value'", self.script_source)
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: auto minmax(0, 1fr) auto;", style_source)
        self.assertIn(".column-value-option .column-value-count", style_source)
        self.assertIn(".data-table thead th", style_source)
        self.assertIn(".cell-display-bar", style_source)

    def test_table_meta_row_unifies_cell_detail_and_table_actions(self):
        for table_id in ("standard-table", "extended-table", "traditional-table"):
            wrapper_start = self.index_source.index(f'class="table-wrapper" data-table-id="{table_id}"')
            wrapper_end = self.index_source.index('</div>\n                        </div>', wrapper_start)
            wrapper_markup = self.index_source[wrapper_start:wrapper_end]
            self.assertIn('class="table-meta-bar"', wrapper_markup)
            self.assertIn('class="table-hover-controls"', wrapper_markup)
            self.assertIn('class="table-meta-divider"', wrapper_markup)
            self.assertIn('class="cell-display-bar"', wrapper_markup)

        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        meta_start = style_source.index("#data-tab .table-meta-bar {")
        meta_end = style_source.index("}", meta_start)
        meta_rule = style_source[meta_start:meta_end]
        self.assertIn("display: flex;", meta_rule)
        self.assertIn("--table-meta-divider: rgba(0, 0, 0, 0.22);", meta_rule)
        self.assertIn("border-radius: 0 !important;", meta_rule)
        self.assertIn("#data-tab .table-meta-divider", style_source)
        divider_start = style_source.index("#data-tab .table-meta-divider {")
        divider_end = style_source.index("}", divider_start)
        divider_rule = style_source[divider_start:divider_end]
        self.assertIn("display: block;", divider_rule)
        self.assertIn("height: 16px;", divider_rule)
        self.assertIn("margin: 0 14px;", divider_rule)
        self.assertIn("background: var(--table-meta-divider);", divider_rule)
        self.assertIn("opacity: 1;", divider_rule)
        self.assertIn("#data-tab .table-meta-bar .table-hover-controls", style_source)
        controls_start = style_source.index("#data-tab .table-meta-bar .table-hover-controls")
        controls_end = style_source.index("}", controls_start)
        controls_rule = style_source[controls_start:controls_end]
        self.assertIn("position: static;", controls_rule)
        self.assertIn("order: 3;", controls_rule)
        self.assertIn("opacity: 1;", controls_rule)
        self.assertIn("#data-tab .data-card,", style_source)
        self.assertIn("border-radius: 0 !important;", style_source[style_source.index("#data-tab .data-card,"):])

    def test_result_cards_keep_themes_but_table_chrome_is_shared(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        for selector, token in (
            (".data-card.df1{", "--t-main: var(--history-action-ink);"),
            (".data-card.df2{", "--t-main: var(--insight-action-ink);"),
            (".data-card.df3{", "--t-main: var(--advanced-action-ink);"),
        ):
            block_start = style_source.index(selector)
            block_end = style_source.index("}", block_start)
            self.assertIn(token, style_source[block_start:block_end])
        self.assertIn(
            ".data-table thead th {\n  background: var(--table-header-bg) !important;\n  color: var(--table-chrome-ink) !important;",
            style_source,
        )
        self.assertIn("--table-chrome-bg: var(--color-surface);", style_source)
        self.assertIn("--table-chrome-ink: var(--nav-ink);", style_source)
        self.assertIn("--table-header-bg: #eef2f3;", style_source)
        table_behavior_start = style_source.index(".data-table{\n  --tbl-head-bg:")
        table_behavior_end = style_source.index("}", table_behavior_start)
        self.assertIn("--tbl-row-hover-bg: var(--table-interaction-hover-bg);", style_source[table_behavior_start:table_behavior_end])
        selection_start = style_source.index(".data-table {\n  --tbl-selection-bg:")
        selection_end = style_source.index("}", selection_start)
        self.assertIn("--tbl-selection-bg: var(--table-interaction-selected-bg);", style_source[selection_start:selection_end])
        self.assertIn("--tbl-selection-border: var(--table-interaction-selected-border);", style_source[selection_start:selection_end])
        self.assertIn("--table-interaction-hover-bg: color-mix(in srgb, var(--accent-tint) 55%, var(--color-surface));", style_source)
        self.assertIn("--table-interaction-selected-bg: var(--accent-tint);", style_source)
        self.assertIn("--table-interaction-selected-border: var(--accent-ink);", style_source)
        self.assertIn(
            ".table-wrapper .cell-display-bar::before{",
            style_source,
        )
        self.assertIn(".table-wrapper .cell-display-bar{\n  position: relative;\n  border-bottom: 1px solid var(--shell-border);\n  box-shadow: none;", style_source)
        self.assertIn(".table-wrapper .cell-display-bar {\n  box-shadow: none;", style_source)
        self.assertIn(
            ".data-table thead th.column-selected {\n  background: var(--color-surface) !important;\n  color: var(--table-interaction-selected-border) !important;\n  box-shadow: inset 0 0 0 2px var(--table-interaction-selected-border);",
            style_source,
        )
        self.assertIn(".data-table thead th.column-selected .column-header-label", style_source)
        self.assertIn("font-weight: 700;\n  color: var(--accent-ink);", style_source)
        self.assertIn(
            ".data-table tbody td.column-selected {\n  background: var(--table-interaction-selected-bg) !important;\n  color: var(--color-text-primary) !important;\n  box-shadow: inset 0 0 0 9999px color-mix(in srgb, var(--table-interaction-selected-border) 28%, transparent) !important;",
            style_source,
        )
        self.assertIn(
            ".data-table tbody tr.row-selected,\n.data-table tbody tr.row-selected td {\n  background: var(--table-interaction-selected-bg) !important;\n  box-shadow: inset 0 0 0 9999px color-mix(in srgb, var(--table-interaction-selected-border) 28%, transparent) !important;",
            style_source,
        )
        self.assertIn("color: var(--accent-ink);\n  white-space: nowrap;", style_source)
        self.assertNotIn(".table-wrapper.no-divider .cell-display-bar", style_source)
        self.assertIn(".result-table-tabs {", style_source)
        self.assertIn("border-bottom: 0;", style_source[style_source.index(".result-table-tabs {"):style_source.index("}", style_source.index(".result-table-tabs {"))])
        data_tab_card_start = style_source.index("#data-tab .data-card {")
        data_tab_card_end = style_source.index("}", data_tab_card_start)
        self.assertIn("border-top: 0;", style_source[data_tab_card_start:data_tab_card_end])
        self.assertIn("background: var(--table-chrome-bg);", style_source)
        self.assertIn("background: var(--table-chrome-ink);", style_source)
        self.assertNotIn("--tbl-head-bg: var(--history-action-active-bg);", style_source)
        self.assertNotIn("--tbl-head-bg: var(--insight-action-active-bg);", style_source)
        self.assertNotIn("--tbl-head-bg: var(--advanced-action-active-bg);", style_source)
        self.assertNotIn("--bar-bg", style_source)
        self.assertNotIn("--bar-accent", style_source)
        self.assertIn(
            ".data-table td.cell-selected,\n.data-table td.cell-range,\n.data-table td.cell-active{\n  background: var(--table-interaction-selected-bg);\n  box-shadow: inset 0 0 0 9999px color-mix(in srgb, var(--table-interaction-selected-border) 28%, transparent);",
            style_source,
        )
        self.assertNotIn("#standard-table tbody tr:hover,", style_source)
        self.assertNotIn("#standard-table td.cell-selected,", style_source)
        self.assertIn("--action-border-width: 1.5px;", style_source)

    def test_legacy_query_adapter_carries_complete_dataset_selection(self):
        for token in (
            "LEGACY_DATASET_GROUPS",
            "goods_general",
            "medical_devices",
            "medicine_generic",
            "medicine_originator",
            "medicine_herbal",
            "herbal_material",
            "traditional_medicine",
            "enrichLegacyQueryRequest",
            "advancedSearchContract",
            "['id', 'data_group', 'source_tab', 'source_tab_label', 'partition_date'].includes(fieldName)",
            "sourceTypes",
            "df3",
        ):
            self.assertIn(token, self.script_source)

    def test_column_filters_use_bounded_working_set_and_keep_dataset_mapping_explicit(self):
        self.assertIn("async function applyFilters(payload, options = {})", self.script_source)
        self.assertIn("resetMiniFilters: options.resetMiniFilters !== false", self.script_source)
        self.assertIn("function getWorkingSetData(tableId)", self.script_source)
        self.assertIn("function getFilteredWorkingSet(tableId, excludedColumnName = null)", self.script_source)
        self.assertIn("function getBoundedColumnValueOptions(tableId, columnName)", self.script_source)
        self.assertIn("function refreshBoundedWorkingSetViews(", self.script_source)
        self.assertIn("workingSetAvailable", self.script_source)
        self.assertIn("columnFilterDraft", self.script_source)
        self.assertIn("working_set", self.script_source)
        self.assertNotIn("currentQueryFacets", self.script_source)
        self.assertNotIn("currentQueryFacetAvailability", self.script_source)
        self.assertNotIn("function getColumnFacetOptions", self.script_source)
        self.assertNotIn("function collectServerColumnFilters", self.script_source)
        self.assertNotIn("function restoreServerColumnFiltersFromRequest", self.script_source)

        distinct_start = self.script_source.index("function getBoundedColumnValueOptions(tableId, columnName) {")
        distinct_end = self.script_source.index("\n}\n\nfunction collectColumnFiltersForUrl", distinct_start)
        distinct_source = self.script_source[distinct_start:distinct_end]
        self.assertIn("getFilteredWorkingSet(tableId, columnName)", distinct_source)
        self.assertIn("getFilteredWorkingSet(tableId, columnName).forEach", distinct_source)
        self.assertIn("const matchesValues = Array.from(filters.entries()).every", self.script_source)
        self.assertIn(".some(value => selected.has", self.script_source)
        self.assertIn("replaceColumnFilterState(columnValueFilterState[tableId], tableId, columnName, nextValueSet);", self.script_source)
        self.assertIn("page: 1", self.script_source[self.script_source.index("function applyColumnValueFilterFromMenu"):])
        self.assertNotIn("currentFilteredDf1", distinct_source)
        self.assertNotIn("currentFilteredDf2", distinct_source)
        self.assertNotIn("currentFilteredDf3", distinct_source)

        self.assertNotIn("function applyMiniFiltersToRows", self.script_source)
        self.assertIn("bounded working set, never from only", self.script_source)
        self.assertIn("columnFilters: collectColumnFiltersForUrl()", self.script_source)
        self.assertIn("if (workingSetAvailable[activeTableId])", self.script_source)
        self.assertIn("if (tableId === 'traditional-table') return currentDisplayedDf3;", self.script_source)
        self.assertIn("return getWorkingSetData(tableId).filter", self.script_source)
        self.assertIn("const MAX_COLUMN_VALUES_RENDERED = 250", self.script_source)
        self.assertIn("searchInput?.addEventListener('input', handleSearchInput);", self.script_source)
        self.assertIn("searchInput?.addEventListener('search', handleSearchInput);", self.script_source)
        self.assertIn("searchInput?.addEventListener('keydown', event => {", self.script_source)
        self.assertIn("if (event.key !== 'Enter' || event.isComposing) return;", self.script_source)
        self.assertIn("applyColumnValueFilterFromMenu(", self.script_source)
        self.assertIn("function getMatchingColumnValueOptions(facetOptions, searchTerm = '')", self.script_source)
        self.assertIn("rerenderValueOptions({ syncSelection: true });", self.script_source)
        self.assertNotIn("function applyColumnTextFilterFromInput", self.script_source)
        self.assertNotIn("refreshBoundedWorkingSetViews({ page: 1, resetScroll: false, redrawCharts: true });\n        rerenderValueOptions", self.script_source)
        self.assertNotIn("document.addEventListener('input', (e) => {\n        const input = e.target.closest('.column-mini-filter-input');", self.script_source)

        menu_start = self.script_source.index("function renderColumnMenu(tableId, columnName) {")
        menu_end = self.script_source.index("\n}\n\nfunction rerenderActiveColumnMenu", menu_start)
        menu_source = self.script_source[menu_start:menu_end]
        self.assertIn("const handleSearchInput = () => {", menu_source)
        self.assertIn("rerenderValueOptions({ syncSelection: true });", menu_source)
        self.assertNotIn("refreshBoundedWorkingSetViews(", menu_source)
        keydown_start = menu_source.index("searchInput?.addEventListener('keydown'")
        keydown_source = menu_source[keydown_start:]
        self.assertNotIn("applyColumnValueFilterFromMenu(", keydown_source)
        self.assertIn("event.preventDefault();", keydown_source)

        request_start = self.script_source.index("async function fetchQueryResults(")
        request_end = self.script_source.index("async function fetchQueryPreview(", request_start)
        request_source = self.script_source[request_start:request_end]
        self.assertIn("getAuthorizedFetch()", request_source)
        self.assertIn("body: JSON.stringify(requestBody)", request_source)
        self.assertNotIn("columnFilters", request_source)

    def test_result_tables_use_new_canonical_columns_and_keep_custom_ordering(self):
        for field in (
            "item_name",
            "medicine_name",
            "active_ingredient_or_herbal_component",
            "technical_specification",
            "registration_or_import_permit_number",
            "winning_bidder_id",
            "procuring_entity_id",
            "decision_issued_at",
            "bidder_count",
        ):
            self.assertIn(field, self.form_source)

        for token in (
            "window.BIDFinderDataColumns",
            "const RESULT_TABLE_GROUPS = {",
            "'standard-table': 'medicines'",
            "'extended-table': 'goods'",
            "'traditional-table': 'traditional'",
            "const DF1_COLUMNS_ORDER = [...(RESULT_COLUMN_CATALOG.order.medicines || [])];",
            "const DF2_COLUMNS_ORDER = [...(RESULT_COLUMN_CATALOG.order.goods || [])];",
            "const DF3_COLUMNS_ORDER = [...(RESULT_COLUMN_CATALOG.order.traditional || [])];",
            "function getResultColumnLabel(tableId, columnName)",
            "const RESULT_COLUMN_ALIASES = {",
            "wining_unit_price: 'winning_unit_price'",
            "label.textContent = displayLabel;",
            "getRawColumnValue(item, colName)",
            "function formatLocationDisplayValue(value)",
            "const value = mapField(row, columnName, fieldMappers);",
            "bidder-count rounding",
            "map(column => getResultColumnLabel(tableId, column))",
            "localStorage.setItem(config.storageKey, JSON.stringify(mergedOrder));",
            "function buildExportWorksheet(data, headerOrder, currentOrder, tableId)",
        ):
            self.assertIn(token, self.script_source)

        for colspan in ("colspan=\"26\"", "colspan=\"25\""):
            self.assertIn(colspan, self.index_source)

        self.assertNotIn("const DF1_COLUMNS_ORDER = [\n    'Tên hoạt chất'", self.script_source)
        self.assertNotIn("const DF2_COLUMNS_ORDER = [\n    'Tên phần/lô'", self.script_source)
        self.assertNotIn("const DF3_COLUMNS_ORDER = [\n    'Tên dược liệu / vị thuốc'", self.script_source)

    def test_browser_request_contract_does_not_emit_raw_typesense_syntax(self):
        self.assertIsNone(re.search(r"\b(query_by|filter_by|sort_by)\b", self.script_source))

    def test_legacy_surface_has_compact_responsive_controls(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        self.assertIn(".active-filters-topbar", self.form_source)
        self.assertIn(".filter-layout", self.form_source)
        self.assertIn(".filter-sidebar", self.form_source)
        self.assertIn(".filter-content", self.form_source)
        self.assertIn("renderEditor()", self.form_source)
        self.assertIn(".legacy-detail-dialog", style_source)
        self.assertIn(".result-table-tabs .workspace-status", style_source)
        self.assertIn(".legacy-pagination", style_source)
        self.assertIn(".legacy-row-detail", style_source)
        self.assertIn("@media (max-width: 700px)", style_source)

    def test_shadow_dom_advanced_search_has_legacy_visual_contract(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        css_match = re.search(r"styles\(\)\s*\{\s*return `(?P<css>[\s\S]*?)`;\s*\}", self.form_source)
        self.assertIsNotNone(css_match)
        component_css = css_match.group("css")

        for token in (
            'class="search-form"',
            'class="sidebar-item group-choice',
            'class="sidebar-item ${field.name',
            'class="filter-chip"',
            ".search-form",
            ".active-filters-topbar",
            ".filter-layout",
            ".filter-sidebar",
            ".sidebar-column",
            ".sidebar-group",
            ".group-choice.active",
            ".sidebar-item.active",
            ".sidebar-item-hint",
            ".filter-chip .chip-remove",
            ".filter-content",
            ".filter-pane.active",
            ".field input",
            ".field select",
            ".btn-primary",
            ".btn-secondary",
            "appearance: none",
        ):
            self.assertIn(token, self.form_source if token.startswith("class=") else component_css)

        self.assertNotIn('class="active-filter-chip', self.form_source)
        self.assertIn("grid-template-columns: clamp(130px, 9vw, 150px) minmax(400px, 460px) clamp(430px, 32vw, 520px);", component_css)
        self.assertIn("grid-column: 3;", component_css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);", component_css)
        self.assertIn("background: #eaf5ed;", component_css)
        self.assertIn("background: #eef7fb;", component_css)
        self.assertIn("width: min(1180px, calc(100vw - 24px));", style_source)
        self.assertIn("padding: clamp(6px, 0.9vh, 10px);", style_source)

        self.assertNotIn("width: 124px;", style_source)
        self.assertIn("width: auto;", style_source)
        self.assertIn("min-width: max-content;", style_source)
        self.assertIn("flex-shrink: 0;", style_source)
        self.assertIn(".result-table-tabs .toolbar-actions > button", style_source)
        self.assertIn("flex-wrap: wrap;", style_source)
        self.assertIn("@media (max-width: 900px)", style_source)
        self.assertIn(".result-table-tabs .scope-count", style_source)
        self.assertIn(".toolbar-actions {", style_source)

    def test_advanced_search_editor_keeps_legacy_compact_controls(self):
        for removed in (
            "Nhập điều kiện cho biến đang chọn. Chỉ trình soạn thảo này được hiển thị.",
            ">Giá trị</label>",
            "Xóa điều kiện",
            "Thêm tiêu chí",
            "Chọn biến, nhập điều kiện rồi thêm vào bộ lọc.",
            'data-action="clear-criterion"',
            'data-action="save-criterion"',
        ):
            self.assertNotIn(removed, self.form_source)
        self.assertIn("padding: 0; border: 0; background: transparent;", self.form_source)

    def test_advanced_search_compact_refinement_contract(self):
        current_feature_source = self.index_source + self.form_source + self.script_source + self.legacy_form_source
        self.assertIn("Tìm kiếm nâng cao", current_feature_source)
        self.assertNotIn("Tra cứu nâng cao", current_feature_source)
        self.assertIn("ADVANCED_FILTER_EXCLUDED_FIELDS", self.form_source)
        for field in ("quantity", "winning_unit_price", "winning_bidder_id", "procuring_entity_id", "bidder_count"):
            self.assertIn(repr(field), self.form_source)
        self.assertNotIn('class="ts-footer"', self.form_source)
        self.assertIn('class="preview-estimate"', self.form_source)
        self.assertIn("active-filters-topbar${chips ? '' : ' empty'}", self.form_source)
        self.assertIn("@media (max-width: 980px)", self.form_source)
        self.assertIn("@media (min-width: 981px) and (max-width: 1199px)", self.form_source)
        self.assertIn("height: clamp(72px, 8vh, 84px);", self.form_source)
        self.assertIn("max-height: 84px;", self.form_source)
        self.assertIn("margin-top: auto;", self.form_source)
        self.assertIn("clamp(430px, 32vw, 520px)", self.form_source)
        self.assertIn("min-height: 24px;", self.form_source)
        self.assertIn(".preview-estimate.zero-result", self.form_source)
        self.assertIn("'Có 0 kết quả'", self.form_source)
        self.assertIn("'Có 100+ kết quả'", self.form_source)
        render_editor_source = self.form_source[self.form_source.index("        renderEditor() {"):self.form_source.index("        bindEvents() {")]
        field_position = render_editor_source.index('<div class="field">')
        estimate_position = render_editor_source.index('<div class="preview-estimate"')
        help_position = render_editor_source.index('this.renderEditorHelp()')
        actions_position = render_editor_source.index('class="editor-actions"')
        self.assertLess(field_position, estimate_position)
        self.assertLess(estimate_position, help_position)
        self.assertLess(help_position, actions_position)

    def test_advanced_search_reuses_legacy_keyword_tokens(self):
        for token in (
            "LEGACY_TOKEN_FILTER_KEYS",
            'class="token-input-container"',
            'class="token-tag"',
            'class="token-operator"',
            "const operators = ['OR', 'AND', 'NOT'];",
            "this.appendValueToken(keywordInput.value)",
            "this.moveValueTokenToInputForEditing",
            "data-chip-field",
        ):
            self.assertIn(token, self.form_source)
        self.assertNotIn("Nhập một hoặc nhiều giá trị, cách nhau bằng dấu phẩy", self.form_source)

    def test_goods_keyword_fields_share_the_legacy_four_column_search_scope(self):
        self.assertIn("const GOODS_SHARED_SEARCH_FIELDS = new Set(['item_name', 'model_mark', 'brand', 'technical_specification']);", self.form_source)
        for field in ("item_name", "model_mark", "brand", "technical_specification"):
            self.assertIn(f"{field}: 'goodsKeyword'", self.form_source)
        self.assertIn("this.state.group === 'goods' && GOODS_SHARED_SEARCH_FIELDS.has(field.name)", self.form_source)
        self.assertIn('"goodsKeyword": ("item_name", "model_mark", "brand", "technical_specification")', self.api_typesense_shadow_source)

    def test_location_cleanup_reads_new_and_legacy_province_segment_order(self):
        for token in (
            "const LOCATION_PROVINCE_PREFIX_RE =",
            "const provinceIndex = parts.findIndex",
            "ADMIN_UNITS_2025",
            "LOCATION_PROVINCE_MATCHES.find",
        ):
            self.assertIn(token, self.script_source)

    def test_keyword_entry_updates_in_place_and_group_switch_stays_in_modal(self):
        append_source = self.form_source[self.form_source.index("        appendValueToken(rawValue) {"):self.form_source.index("        cycleTokenOperator(index) {")]
        self.assertIn("this.refreshTokenCriterion()", append_source)
        self.assertNotIn("this.render()", append_source)
        self.assertIn("this.setPreviewResult({ loading: true })", self.form_source)
        self.assertIn("'Đang ước tính...'", self.form_source)
        self.assertIn("this.setApplyLoading(true)", self.form_source)
        self.assertNotIn("submit() { const request = this.collectFilterPayload(); this.state.loading = true; this.render();", self.form_source)
        group_binding = self.form_source[self.form_source.index("root.querySelectorAll('[data-group]')"):self.form_source.index("root.querySelectorAll('[data-field]')")]
        self.assertNotIn("dataset-group-change", group_binding)

    def test_query_limits_and_cumulative_pagination_contract(self):
        api_source = (ROOT / "apps/api/server.py").read_text(encoding="utf-8")
        shadow_source = (ROOT / "apps/api/typesense_shadow.py").read_text(encoding="utf-8")
        self.assertIn("function getAppliedWorkingSetLimit(tableId = null)", self.script_source)
        self.assertIn("function hasMoreRowsBeyondWorkingSet(tableId)", self.script_source)
        self.assertIn("function getStandardWorkingSetLimitForLegacyResponse()", self.script_source)
        self.assertIn("WorkingSetTruncated", self.script_source)
        self.assertIn("const workingSetCount = Number(currentQueryMeta[`${scopeKey}WorkingCount`] || 0);", self.script_source)
        self.assertIn("return rawTotal > getStandardWorkingSetLimitForLegacyResponse();", self.script_source)
        self.assertIn("Object.assign(currentQueryMeta, {", self.script_source)
        self.assertIn("['standard-table', 'extended-table', 'traditional-table']", self.script_source)
        self.assertIn("Number(currentQueryMeta.appliedLimitPerScope || 0)", self.script_source)
        self.assertIn("const resultLimit = getAppliedWorkingSetLimit(activeTableId);", self.script_source)
        self.assertNotIn("const MAX_RESULTS_PER_TABLE =", self.script_source)
        self.assertNotIn("const FULL_SEARCH_TOTAL_LIMIT =", self.script_source)
        self.assertIn('DEFAULT_QUERY_LIMIT", 1000', api_source)
        self.assertIn('MAX_QUERY_LIMIT", 5000', api_source)
        self.assertIn("limit: int = 1000", shadow_source)
        self.assertIn("limit: int = 1000,", shadow_source)
        self.assertIn("const cumulativeDisplayed = Math.max(0, (page - 1) * pageSize + displayed);", self.script_source)
        self.assertIn("const shownThrough = total > 0 ? Math.min(cumulativeDisplayed, total) : cumulativeDisplayed;", self.script_source)
        self.assertIn("shownThrough.toLocaleString('vi-VN')", self.script_source)
        self.assertIn("next.disabled = !hasMore || resultLimitReached;", self.script_source)
        self.assertIn("if (page > currentPage && Number.isFinite(resultLimit) && (page - 1) * pageSize >= resultLimit)", self.script_source)

        dock_start = self.script_source.index("function canRunDockFullSearch(")
        dock_end = self.script_source.index("\n}\n\nfunction isDataDockContextAllowed", dock_start)
        dock_source = self.script_source[dock_start:dock_end]
        self.assertIn(".some(hasMoreRowsBeyondWorkingSet)", dock_source)
        self.assertNotIn("Boolean(currentQueryMeta.df1HasMore || currentQueryMeta.df2HasMore)", dock_source)

        full_search_start = self.script_source.index("async function triggerFullSearch()")
        full_search_end = self.script_source.index("\n\n// Helper: Show limit warning", full_search_start)
        full_search_source = self.script_source[full_search_start:full_search_end]
        self.assertIn("{ searchMode: 'full' }", full_search_source)
        self.assertNotIn("FULL_SEARCH_TOTAL_LIMIT", full_search_source)

    def test_full_search_disabled_state_is_visually_distinct(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        self.assertIn(".result-table-tabs .toolbar-actions .full-search-credit:disabled,", style_source)
        self.assertIn("background: #e4e9eb;", style_source)
        self.assertIn("filter: grayscale(1);", style_source)
        self.assertIn("opacity: 0.52;", style_source)

    def test_advanced_search_navigation_uses_inline_legacy_style_icons(self):
        for token in (
            'class="search-form-icon"',
            "package: '<path",
            "pill: '<path",
            "leaf: '<path",
            "product: '<path",
            "tender: '<rect",
            'class="sidebar-item group-choice',
            'class="sidebar-group">${icon(iconName)}',
        ):
            self.assertIn(token, self.form_source)

    def test_advanced_search_has_legacy_panel_architecture_and_help(self):
        for token in (
            'category-panel',
            'condition-panel',
            'class="sidebar-panel-title">Danh mục</div>',
            'class="sidebar-panel-title">Điều kiện</div>',
            'Tính chất sản phẩm',
            'Thông tin thầu',
            "renderVariableSections()",
            "renderEditorHelp()",
            "1. Gõ từ khóa",
            "2. Nhấn Enter để tạo một thẻ từ khóa",
            "3. Nếu có nhiều điều kiện, lặp lại bước 1 và 2",
            "4. Điều chỉnh bằng cách click OR AND NOT để tạo điều kiện",
            '5. Lưu ý vùng <strong>\"Điều kiện tìm kiếm\"</strong> ở trên cùng để quản lý điều kiện tìm kiếm',
            'data-open-filter-help',
        ):
            self.assertIn(token, self.form_source)
        for forbidden in ("Nhóm dữ liệu", "Mã nguồn MSC", "Loại nguồn", "Sắp xếp", "Phân trang"):
            self.assertNotIn(forbidden, self.form_source)
        self.assertNotIn("Phạm vi tra cứu", self.form_source)
        self.assertNotIn(">Biến lọc<", self.form_source)

    def test_shadow_dom_style_lifecycle_runtime(self):
        for token in (
            "constructor()",
            "attachShadow({ mode: 'open' })",
            "className = 'search-form-root'",
            "this._contentRoot.innerHTML",
        ):
            self.assertIn(token, self.form_source)
        self.assertNotIn("this.shadowRoot.innerHTML", self.form_source)
        lifecycle_test = ROOT / "tests/web/typesense-search-form-lifecycle.test.js"
        result = subprocess.run(
            ["node", str(lifecycle_test)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_advanced_search_uses_only_approved_groups_and_fields(self):
        for label in ("Hàng hóa", "Thuốc", "Dược liệu", "Điều kiện tìm kiếm:"):
            self.assertIn(label, self.form_source)
        for hidden_label in ("Nhóm dữ liệu", "Mã nguồn MSC", "Loại nguồn", "Sắp xếp và phân trang"):
            self.assertNotIn(hidden_label, self.form_source)

        expected = {
            "goods": ["Tên hàng hóa", "Khối lượng", "Mã HS", "Cấu hình, tính năng kỹ thuật", "Ngày đăng tải KQLCNT"],
            "medicines": ["Tên thuốc", "Tên hoạt chất / dược liệu", "Hạn dùng (Tuổi thọ)", "Nhóm thuốc"],
            "traditional": ["Tên dược liệu / vị thuốc cổ truyền", "Bộ phận dùng", "Phương pháp chế biến", "Nhóm TCKT"],
        }
        for labels in expected.values():
            for label in labels:
                self.assertIn(label, self.form_source)

    def test_row_detail_requires_double_click_and_uses_modal(self):
        self.assertNotIn("selectLegacyRow", self.script_source)
        self.assertNotIn("legacy-row-selected", self.script_source)
        self.assertNotIn("legacy-row-selected", (ROOT / "apps/web/style.css").read_text(encoding="utf-8"))
        self.assertNotIn("tr.addEventListener('click'", self.script_source)
        self.assertNotIn("tr.tabIndex = 0", self.script_source)
        self.assertIn("tr.addEventListener('dblclick', () => openLegacyRowDetail(item, configKey))", self.script_source)
        self.assertIn("const td = e.target.closest(\"td\")", self.script_source)
        self.assertIn("td.classList.add(isSingleCell ? \"cell-selected\" : \"cell-range\")", self.script_source)
        self.assertIn("const selectorCell = e.target.closest('.row-selector-cell')", self.script_source)
        self.assertIn("if (!selectorCell) return", self.script_source)
        self.assertIn('role="dialog" aria-modal="true"', self.index_source)
        self.assertIn("position: fixed", (ROOT / "apps/web/style.css").read_text(encoding="utf-8"))

    def test_legacy_search_form_and_result_workflow_remain_mounted(self):
        search_form_source = (ROOT / "apps/web/typesense-search-form.js").read_text(encoding="utf-8")
        for token in (
            'id="open-filter-panel"',
            'id="close-filter-panel"',
            'data-action="apply"',
            'id="standard-table"',
            'id="extended-table"',
            'id="traditional-table"',
            'id="open-run-history"',
        ):
            self.assertIn(token, self.index_source + search_form_source)

    def test_capability_counts_match_phase_4b_contract(self):
        expected = {
            "goods": {"searchable": 14, "filterable": 11, "sortable": 5, "autocomplete": 5},
            "medicines": {"searchable": 16, "filterable": 13, "sortable": 4, "autocomplete": 6},
            "traditional": {"searchable": 15, "filterable": 12, "sortable": 4, "autocomplete": 6},
        }
        for group, counts in expected.items():
            fields = self.contract["groups"][group]["fields"]
            actual = {key: sum(bool(field[key]) for field in fields) for key in counts}
            self.assertEqual(counts, actual, group)

    def test_history_uses_typesense_update_timeline_contract(self):
        self.assertIn("metadata?.update_timeline", self.script_source)
        self.assertNotIn("metadata?.approval_timeline", self.script_source)
        self.assertIn("đăng tải KQLCNT", self.index_source)
        self.assertIn('"source": "typesense"', self.api_source)
        metadata_start = self.api_source.index('@app.get("/api/metadata")')
        metadata_source = self.api_source[metadata_start:metadata_start + 5000]
        self.assertIn("typesense_search_repository.update_timeline()", metadata_source)
        self.assertNotIn("run_sessions", metadata_source)
        self.assertNotIn("package_metadata", metadata_source)


if __name__ == "__main__":
    unittest.main()
