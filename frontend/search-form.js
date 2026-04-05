class CustomSearchForm extends HTMLElement {
    connectedCallback() {
        this.attachShadow({ mode: 'open' });
        this.shadowRoot.innerHTML = `
            <style>
                :host {
                    --c-primary: var(--color-primary, #127495);
                    --c-primary-hover: var(--color-primary-dark, #0f5b77);
                    --c-primary-light: rgba(18, 116, 149, 0.10);
                    --c-primary-soft: rgba(18, 116, 149, 0.16);
                    --c-accent: var(--color-accent, #1b866e);

                    --c-text: var(--color-text-primary, #111827);
                    --c-sub: var(--color-text-secondary, #56707f);
                    --c-muted: var(--color-text-muted, #7b919d);

                    --c-border: var(--color-border, #d3e2eb);
                    --c-border-strong: #b8d0dc;
                    --c-surface: var(--color-surface, #ffffff);
                    --c-surface-2: var(--color-surface-2, #f5fafc);
                    --c-surface-3: #edf6fa;
                    --c-sidebar: #f4f9fc;

                    --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.05);
                    --shadow-md: 0 10px 24px rgba(16, 34, 48, 0.08);
                    --shadow-lg: 0 18px 36px rgba(16, 34, 48, 0.12);

                    --radius-sm: 8px;

                    --control-h: 44px;
                    --field-pad-x: 14px;
                    --field-pad-y: 10px;

                    --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                }

                * {
                    box-sizing: border-box;
                }

                .search-form {
                    font-family: var(--font);
                    background: transparent;
                    color: var(--c-text);
                }

                /* =========================
                Topbar
                ========================= */
                .active-filters-topbar {
                    display: flex;
                    align-items: center;
                    gap: 16px;
                    padding: 12px 18px;
                    margin-bottom: 20px;
                    min-height: 56px;
                    background: var(--c-surface);
                    border: 1px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    box-shadow: var(--shadow-sm);
                }

                .active-filters-title {
                    flex-shrink: 0;
                    font-size: 13px;
                    font-weight: 700;
                    color: var(--c-sub);
                    white-space: nowrap;
                }

                .active-filters-list {
                    display: flex;
                    flex-wrap: wrap;
                    align-items: center;
                    gap: 8px;
                    flex: 1;
                    min-width: 0;
                }

                .empty-filters {
                    font-size: 13px;
                    color: var(--c-muted);
                }

                .filter-chip {
                    display: inline-flex;
                    align-items: flex-start;
                    gap: 6px;
                    max-width: 100%;
                    padding: 5px 8px 5px 10px;
                    border-radius: var(--radius-sm);
                    border: 1px solid rgba(18, 116, 149, 0.20);
                    background: var(--c-primary-light);
                    color: var(--c-primary-hover);
                    font-size: 12.5px;
                    line-height: 1.35;
                    white-space: normal;
                    word-break: break-word;
                }

                .filter-chip strong {
                    color: var(--c-primary-hover);
                    font-weight: 700;
                    flex-shrink: 0;
                }

                .filter-chip .chip-remove {
                    margin-left: 4px;
                    padding-left: 6px;
                    border-left: 1px solid rgba(18, 116, 149, 0.20);
                    color: var(--c-primary);
                    opacity: 0.58;
                    cursor: pointer;
                    font-size: 14px;
                    line-height: 1;
                }

                .filter-chip .chip-remove:hover {
                    opacity: 1;
                    color: var(--c-accent);
                }

                /* =========================
                Main layout
                ========================= */
                .filter-layout {
                    display: flex;
                    height: 500px;
                    overflow: hidden;
                    border: 1px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    background: var(--c-surface);
                    box-shadow: var(--shadow-md);
                }

                .filter-sidebar {
                    width: 264px;
                    padding: 14px 0;
                    overflow-y: auto;
                    background: linear-gradient(180deg, #f8fcfe 0%, #f2f9fc 100%);
                    border-right: 1px solid #dce8ef;
                }

                .filter-sidebar::-webkit-scrollbar {
                    width: 6px;
                }

                .filter-sidebar::-webkit-scrollbar-thumb {
                    background: #d5dbe7;
                    border-radius: var(--radius-sm);
                }

                .sidebar-group {
                    display: block;
                    margin: 22px 0 8px;
                    padding: 9px 18px 9px 20px;
                    background: #e7f1f6;
                    border-top: 1px solid #dce8ef;
                    border-bottom: 1px solid #dce8ef;
                    color: #537080;
                    font-size: 11px;
                    font-weight: 800;
                    letter-spacing: 0.08em;
                    text-transform: uppercase;
                    line-height: 1.2;
                }


                .sidebar-group:first-child {
                    margin-top: 4px;
                }

                .sidebar-item {
                    position: relative;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    min-height: 36px;
                    margin: 0;
                    padding: 8px 18px 8px 20px;
                    border-left: 3px solid transparent;
                    color: #374151;
                    font-size: 13px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
                }


                .sidebar-item:hover {
                    background: rgba(148, 163, 184, 0.10);
                    color: #111827;
                }

                .sidebar-item.active {
                    background: var(--c-primary);
                    border-left: 4px solid var(--c-primary-hover);
                    color: #ffffff;
                    font-weight: 800;
                }

                .sidebar-item.active::after {
                    background: rgba(255, 255, 255, 0.96);
                    box-shadow: none;
                }

                .sidebar-item.has-value::after {
                    content: '';
                    width: 7px;
                    height: 7px;
                    margin-left: 10px;
                    flex-shrink: 0;
                    border-radius: var(--radius-sm);
                    background: var(--c-primary);
                    box-shadow: 0 0 0 3px rgba(18, 116, 149, 0.14);
                }



                .filter-content {
                    flex: 1;
                    padding: 36px 40px;
                    overflow-y: auto;
                    background: var(--c-surface);
                }

                .filter-pane {
                    display: none;
                    animation: fadeIn 0.22s ease;
                }

                .filter-pane.active {
                    display: block;
                }

                @keyframes fadeIn {
                    from {
                        opacity: 0;
                        transform: translateY(8px);
                    }
                    to {
                        opacity: 1;
                        transform: translateY(0);
                    }
                }

                .filter-pane h3 {
                    margin: 0 0 8px;
                    color: var(--c-text);
                    font-size: 22px;
                    font-weight: 750;
                    letter-spacing: -0.3px;
                }

                .pane-desc {
                    margin: 0 0 28px;
                    color: var(--c-sub);
                    font-size: 14px;
                    line-height: 1.55;
                }

                .fields-row {
                    display: flex;
                    gap: 20px;
                }

                .fields-row .field {
                    flex: 1;
                }

                .field {
                    display: flex;
                    flex-direction: column;
                    margin-bottom: 20px;
                }

                label {
                    display: block;
                    margin-bottom: 8px;
                    color: var(--c-text);
                    font-size: 13px;
                    font-weight: 650;
                }

                /* =========================
                Controls
                ========================= */
                .field > input,
                .field > select,
                .field .multi-select-btn {
                    width: 100%;
                    min-height: var(--control-h);
                    height: var(--control-h);
                    padding: 0 var(--field-pad-x);
                    border: 2px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    background: var(--c-surface);
                    color: var(--c-text);
                    font-family: inherit;
                    font-size: 14px;
                    line-height: 1.4;
                    transition: border-color 0.18s ease, background 0.18s ease;
                    box-sizing: border-box;
                }

                .field > input:hover,
                .field > select:hover,
                .field .multi-select-btn:hover,
                .token-input-container:hover {
                    border-color: var(--c-border-strong);
                }

                .field > input:focus,
                .field > select:focus,
                .field .multi-select-btn:focus,
                .multi-select.open .multi-select-btn,
                .token-input-container:focus-within {
                    outline: none;
                    border-color: var(--c-primary-hover);
                    box-shadow: none;
                }

                .field > input::placeholder,
                .multi-select-search input::placeholder,
                .token-input-container input::placeholder,
                textarea::placeholder {
                    color: var(--c-muted);
                    opacity: 1;
                    font-size: 14px;
                    font-family: inherit;
                    font-weight: 400;
                    line-height: 1.4;
                }

                .field > select.is-placeholder {
                    color: var(--c-muted) !important;
                }

                select.js-hidden {
                    display: none !important;
                }

                /* =========================
                Token input
                ========================= */
                .token-input-container {
                    display: flex;
                    flex-wrap: wrap;
                    align-items: flex-start;
                    align-content: flex-start;
                    gap: 8px;
                    min-height: 44px;
                    max-height: 160px;
                    padding: 7px 12px;
                    overflow-x: hidden;
                    overflow-y: auto;
                    cursor: text;
                    border: 2px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    background: var(--c-surface);
                    transition: border-color 0.18s ease, background 0.18s ease;
                }

                .token-input-container::-webkit-scrollbar {
                    display: none;
                }

                .token-input-container input {
                    flex: 1 1 180px;
                    min-width: 180px;
                    height: 28px;
                    margin: 0;
                    padding: 0;
                    border: none !important;
                    outline: none;
                    box-shadow: none !important;
                    background: transparent;
                    color: var(--c-text);
                    font-family: inherit;
                    font-size: 14px;
                    font-weight: 400;
                    line-height: 1.4;
                }

                .token-input-container input:focus {
                    border: none;
                    box-shadow: none;
                    outline: none;
                }

                .token-tag {
                    display: inline-flex;
                    align-items: center;
                    flex-shrink: 0;
                    height: 28px;
                    padding: 2px 8px;
                    border: 1px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    background: var(--c-surface-2);
                    color: var(--c-text);
                    font-size: 13px;
                    font-weight: 500;
                }

                .token-operator {
                    display: inline-flex;
                    align-items: center;
                    flex-shrink: 0;
                    height: 28px;
                    padding: 2px 8px;
                    border-radius: var(--radius-sm);
                    background: var(--c-primary);
                    color: #fff;
                    font-size: 11px;
                    font-weight: 700;
                    letter-spacing: 0.4px;
                    cursor: pointer;
                    user-select: none;
                }

                .token-operator:hover {
                    background: var(--c-primary-hover);
                }

                .token-remove {
                    margin-left: 6px;
                    padding-left: 6px;
                    border-left: 1px solid var(--c-border);
                    color: var(--c-muted);
                    font-size: 16px;
                    line-height: 1;
                    cursor: pointer;
                }

                .token-remove:hover {
                    color: var(--c-accent);
                }

                /* =========================
                Autocomplete
                ========================= */
                .autocomplete-dropdown {
                    position: absolute;
                    top: calc(100% + 6px);
                    left: 0;
                    width: 100%;
                    max-height: 260px;
                    margin: 0;
                    padding: 6px;
                    overflow-x: hidden;
                    overflow-y: auto;
                    list-style: none;
                    z-index: 9999;
                    border: 1px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    background: var(--c-surface);
                    box-shadow: var(--shadow-lg);
                }

                .autocomplete-dropdown.hidden {
                    display: none;
                }

                .autocomplete-dropdown li {
                    padding: 10px 12px;
                    border-radius: var(--radius-sm);
                    color: var(--c-text);
                    font-size: 13.5px;
                    line-height: 1.4;
                    cursor: pointer;
                }

                .autocomplete-dropdown li:hover,
                .autocomplete-dropdown li.active {
                    background: var(--c-surface-2);
                    color: var(--c-primary-hover);
                }

                .autocomplete-dropdown li strong {
                    color: var(--c-primary-hover);
                    background: var(--c-primary-light);
                    padding: 0 2px;
                    border-radius: 2px;
                    text-decoration: none;
                }

                /* =========================
                Help / tooltip
                ========================= */
                .help-icon {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 20px;
                    height: 20px;
                    border: 1px solid var(--c-border);
                    border-radius: 8px;
                    background: var(--c-surface-2);
                    color: var(--c-muted);
                    font-size: 12px;
                    font-weight: 700;
                    cursor: help;
                }

                .help-icon:hover {
                    background: var(--c-primary);
                    border-color: var(--c-primary);
                    color: #fff;
                }

                /* =========================
                Multi-select
                ========================= */
                .multi-select {
                    position: relative;
                    width: 100%;
                }

                .multi-select-btn {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    color: var(--c-text);
                    cursor: pointer;
                }

                .multi-select-btn.is-placeholder,
                .multi-select-btn.is-placeholder .multi-select-btn-text {
                    color: var(--c-muted);
                }

                .multi-select-btn-text {
                    min-width: 0;
                    color: inherit;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }

                .multi-select-popover {
                    position: absolute;
                    top: calc(100% + 6px);
                    left: 0;
                    right: 0;
                    z-index: 10050;
                    display: none;
                    border: 1px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    background: #fff;
                    box-shadow: var(--shadow-lg);
                }

                .multi-select.open .multi-select-popover {
                    display: block;
                }

                .multi-select-search {
                    padding: 10px;
                    border-bottom: 1px solid var(--c-border);
                }

                .multi-select-search input {
                    width: 100%;
                    height: 36px;
                    padding: 6px 12px;
                    border: 2px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    background: var(--c-surface);
                    color: var(--c-text);
                    font-family: inherit;
                    font-size: 14px;
                    box-sizing: border-box;
                }

                .multi-select-search input:focus {
                    outline: none;
                    border-color: var(--c-primary-hover);
                    box-shadow: none;
                }

                .multi-select-options {
                    max-height: 200px;
                    overflow: auto;
                    padding: 6px;
                }

                .multi-select-option {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    padding: 8px 10px;
                    border-radius: var(--radius-sm);
                    font-size: 13.5px;
                    cursor: pointer;
                }

                .multi-select-option:hover {
                    background: var(--c-surface-2);
                }

                .multi-select-option input[type="checkbox"] {
                    width: 16px;
                    height: 16px;
                    accent-color: var(--c-primary);
                }

                .multi-select-footer {
                    display: flex;
                    justify-content: space-between;
                    padding: 10px;
                    border-top: 1px solid var(--c-border);
                    background: var(--c-surface-2);
                }

                .multi-select-footer button {
                    padding: 6px 12px;
                    border: none;
                    border-radius: var(--radius-sm);
                    font-size: 12px;
                    font-weight: 600;
                    cursor: pointer;
                }

                .multi-select-clear {
                    background: transparent;
                    color: var(--c-sub);
                }

                .multi-select-clear:hover {
                    background: rgba(10, 97, 123, 0.06);
                }

                .multi-select-done {
                    background: var(--c-primary);
                    color: #fff;
                }

                /* =========================
                Actions
                ========================= */
                .filter-pane .preview-result {
                    margin-top: 10px;
                    margin-right: 0;
                }

                .actions {
                    display: flex;
                    align-items: center;
                    flex-wrap: wrap;
                    justify-content: flex-end;
                    gap: 12px;
                    margin-top: 24px;
                }

                .preview-result {
                    min-height: 18px;
                    color: var(--c-sub);
                    font-size: 12.5px;
                    font-weight: 600;
                }

                .preview-result.is-loading {
                    color: var(--c-primary);
                }

                .preview-result.is-warning {
                    color: #b45309;
                }

                .preview-result.is-error {
                    color: #b91c1c;
                }

                .btn {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    min-width: 120px;
                    padding: 10px 16px;
                    border-radius: var(--radius-sm);
                    font-size: 13.5px;
                    font-weight: 650;
                    cursor: pointer;
                    transition: all 0.18s ease;
                }

                .btn-primary {
                    border: none;
                    background: var(--c-primary);
                    color: #fff;
                    box-shadow: 0 6px 16px rgba(10, 97, 123, 0.16);
                }

                .btn-primary:hover:not(:disabled) {
                    background: var(--c-primary-hover);
                    box-shadow: 0 10px 22px rgba(10, 97, 123, 0.18);
                    transform: translateY(-1px);
                }

                .btn-secondary {
                    border: 1px solid var(--c-border);
                    background: var(--c-surface);
                    color: var(--c-text);
                }

                .btn-secondary:hover:not(:disabled) {
                    background: var(--c-surface-2);
                    border-color: #d1d5db;
                }

                .btn:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                    box-shadow: none;
                }

                /* =========================
                Responsive
                ========================= */
                @media (max-width: 900px) {
                    .filter-layout {
                        flex-direction: column;
                        height: auto;
                        min-height: 500px;
                    }

                    .filter-sidebar {
                        display: flex;
                        width: 100%;
                        height: auto;
                        padding: 8px;
                        overflow-x: auto;
                        white-space: nowrap;
                        border-right: none;
                        border-bottom: 1px solid var(--c-border);
                    }

                    .sidebar-group {
                        display: none;
                    }

                    .sidebar-item {
                        flex-shrink: 0;
                        padding: 8px 16px;
                        border-left: none;
                        border-bottom: 3px solid transparent;
                        border-radius: 6px;
                    }

                    .sidebar-item.active {
                        border-left: none;
                        border-bottom-color: var(--c-primary);
                        box-shadow: none;
                        background: var(--c-primary);
                        color: #ffffff;
                    }

                    .sidebar-item.has-value::after {
                        position: absolute;
                        top: 4px;
                        right: 4px;
                    }

                    .filter-content {
                        padding: 24px 20px;
                    }

                    .fields-row {
                        flex-direction: column;
                        gap: 16px;
                    }
                }
            </style>



            <div class="search-form">
                <!-- Thanh trạng thái (Active Chips) -->
                <div class="active-filters-topbar">
                    <div class="active-filters-title">
                        Đang lọc theo:
                    </div>
                    <div class="active-filters-list" id="active-filters-list">
                        <span class="empty-filters">Chưa có điều kiện lọc nào</span>
                    </div>
                    
                </div>

                <!-- Khung Filter 2 Cột -->
                <div class="filter-layout">
                    <!-- Sidebar Trái -->
                    <div class="filter-sidebar">
                        
                        
                        <div class="sidebar-group">📋 Thông tin thầu</div>
                        <div class="sidebar-item" data-target="pane-investor">Chủ đầu tư</div>
                        <div class="sidebar-item" data-target="pane-qd">Quyết định phê duyệt</div>
                        <div class="sidebar-item" data-target="pane-date">Ngày phê duyệt</div>
                        <div class="sidebar-item" data-target="pane-method">Hình thức LCNT</div>
                        <div class="sidebar-item" data-target="pane-place">Tỉnh / Thành phố</div>
                        <div class="sidebar-item" data-target="pane-validity">Tình trạng hiệu lực</div>

                        <div class="sidebar-group">💊 Hàng hóa</div>
                        <div class="sidebar-item active" data-target="pane-drug">Tên thương mại</div>
                        <div class="sidebar-item" data-target="pane-active-ing">Tên hoạt chất</div>
                        <div class="sidebar-item" data-target="pane-conc">Nồng độ, hàm lượng</div>
                        <div class="sidebar-item" data-target="pane-route">Đường dùng</div>
                        <div class="sidebar-item" data-target="pane-dosage">Dạng bào chế</div>
                        <div class="sidebar-item" data-target="pane-spec">Quy cách đóng gói</div>
                        <div class="sidebar-item" data-target="pane-group">Nhóm thuốc</div>
                        <div class="sidebar-item" data-target="pane-reg">Số đăng ký</div>
                        <div class="sidebar-item" data-target="pane-unit">Đơn vị tính</div>

                        <div class="sidebar-group">🏭 Nhà sản xuất</div>
                        <div class="sidebar-item" data-target="pane-manu">Cơ sở sản xuất</div>
                        <div class="sidebar-item" data-target="pane-country">Nước sản xuất</div>
                    </div>

                    <!-- Nội dung Phải -->
                    <div class="filter-content">
                        <!-- Date Pane -->
                        <div class="filter-pane" id="pane-date">
                            <h3>Ngày phê duyệt</h3>
                            <p class="pane-desc"></p> <!-- Chọn khoảng thời gian phê duyệt kết quả LCNT. -->
                            <div class="fields-row">
                                <div class="field"><label>Từ ngày</label><input id="filter-date-from" type="text" placeholder="dd/mm/yyyy"></div>
                                <div class="field"><label>Đến ngày</label><input id="filter-date-to" type="text" placeholder="dd/mm/yyyy"></div>
                            </div>
                        </div>

                        <!-- Investor Pane -->
                        <div class="filter-pane" id="pane-investor">
                            <h3>Chủ đầu tư</h3>
                            <p class="pane-desc"></p> <!-- Gõ để tìm kiếm và thêm nhiều chủ đầu tư. -->
                            <div class="field">
                                <div class="token-input-container" id="investor-container"><input type="text" placeholder="Nhập chủ đầu tư..." /></div>
                                <input type="hidden" id="filter-investor" />
                            </div>
                        </div>

                        <!-- Drug Name Pane -->
                        <div class="filter-pane active" id="pane-drug">
                            <h3>Tên thương mại</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="drug-name-container"><input type="text" placeholder="Nhập tên thuốc..." /></div>
                                <input type="hidden" id="filter-drug-name" />
                            </div>
                        </div>

                        <!-- Active Ingredient Pane -->
                        <div class="filter-pane" id="pane-active-ing">
                            <h3>Tên hoạt chất</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="active-ingredient-container"><input type="text" placeholder="Nhập hoạt chất..." /></div>
                                <input type="hidden" id="filter-active-ingredient" />
                            </div>
                        </div>

                        <!-- Hình thức LCNT -->
                        <div class="filter-pane" id="pane-method">
                            <h3>Hình thức LCNT</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <select id="filter-selection-method" multiple>
                                    <option value="">-- Chọn hình thức --</option>
                                    <option value="Đấu thầu rộng rãi">Đấu thầu rộng rãi</option>
                                    <option value="Đấu thầu hạn chế">Đấu thầu hạn chế</option>
                                    <option value="Chỉ định thầu">Chỉ định thầu</option>
                                    <option value="Chào hàng cạnh tranh">Chào hàng cạnh tranh</option>
                                    <option value="Mua sắm trực tiếp">Mua sắm trực tiếp</option>
                                    <option value="Tự thực hiện">Tự thực hiện</option>
                                    <option value="Tham gia thực hiện của cộng đồng">Tham gia thực hiện của cộng đồng</option>
                                    <option value="Đàm phán giá">Đàm phán giá</option>
                                    <option value="Lựa chọn nhà thầu trong trường hợp đặc biệt">Lựa chọn nhà thầu trong trường hợp đặc biệt</option>
                                    <option value="Đặt hàng">Đặt hàng</option>
                                    <option value="Chào giá trực tuyến">Chào giá trực tuyến</option>
                                    <option value="Chào giá trực tuyến theo quy trình rút gọn">Chào giá trực tuyến theo quy trình rút gọn</option>
                                    <option value="Mua sắm trực tuyến">Mua sắm trực tuyến</option>
                                </select>
                                <div class="multi-select" data-for="filter-selection-method"></div>
                            </div>
                        </div>
                        
                        <!-- Tỉnh / Thành phố -->
                        <div class="filter-pane" id="pane-place">
                            <h3>Tỉnh / Thành phố</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <select id="filter-place" multiple>
                                    <option value="">-- Chọn địa điểm --</option>
                                    <option value="Tỉnh An Giang">An Giang</option>
                                    <option value="Tỉnh Bà Rịa - Vũng Tàu">Bà Rịa - Vũng Tàu</option>
                                    <option value="Tỉnh Bắc Giang">Bắc Giang</option>
                                    <option value="Tỉnh Bắc Kạn">Bắc Kạn</option>
                                    <option value="Tỉnh Bạc Liêu">Bạc Liêu</option>
                                    <option value="Tỉnh Bắc Ninh">Bắc Ninh</option>
                                    <option value="Tỉnh Bến Tre">Bến Tre</option>
                                    <option value="Tỉnh Bình Định">Bình Định</option>
                                    <option value="Tỉnh Bình Dương">Bình Dương</option>
                                    <option value="Tỉnh Bình Phước">Bình Phước</option>
                                    <option value="Tỉnh Bình Thuận">Bình Thuận</option>
                                    <option value="Tỉnh Cà Mau">Cà Mau</option>
                                    <option value="Thành phố Cần Thơ">Cần Thơ</option>
                                    <option value="Tỉnh Cao Bằng">Cao Bằng</option>
                                    <option value="Thành phố Đà Nẵng">Đà Nẵng</option>
                                    <option value="Tỉnh Đăk Lăk">Đăk Lăk</option>
                                    <option value="Tỉnh Đắk Nông">Đăk Nông</option>
                                    <option value="Tỉnh Điện Biên">Điện Biên</option>
                                    <option value="Tỉnh Đồng Nai">Đồng Nai</option>
                                    <option value="Tỉnh Đồng Tháp">Đồng Tháp</option>
                                    <option value="Tỉnh Gia Lai">Gia Lai</option>
                                    <option value="Tỉnh Hà Giang">Hà Giang</option>
                                    <option value="Tỉnh Hà Nam">Hà Nam</option>
                                    <option value="Thành phố Hà Nội">Hà Nội</option>
                                    <option value="Tỉnh Hà Tĩnh">Hà Tĩnh</option>
                                    <option value="Tỉnh Hải Dương">Hải Dương</option>
                                    <option value="Thành phố Hải Phòng">Hải Phòng</option>
                                    <option value="Tỉnh Hậu Giang">Hậu Giang</option>
                                    <option value="Thành phố Hồ Chí Minh">Hồ Chí Minh</option>
                                    <option value="Tỉnh Hòa Bình">Hòa Bình</option>
                                    <option value="Tỉnh Hưng Yên">Hưng Yên</option>
                                    <option value="Tỉnh Khánh Hòa">Khánh Hòa</option>
                                    <option value="Tỉnh Kiên Giang">Kiên Giang</option>
                                    <option value="Tỉnh Kon Tum">Kon Tum</option>
                                    <option value="Tỉnh Lai Châu">Lai Châu</option>
                                    <option value="Tỉnh Lâm Đồng">Lâm Đồng</option>
                                    <option value="Tỉnh Lạng Sơn">Lạng Sơn</option>
                                    <option value="Tỉnh Lào Cai">Lào Cai</option>
                                    <option value="Tỉnh Long An">Long An</option>
                                    <option value="Tỉnh Nam Định">Nam Định</option>
                                    <option value="Tỉnh Nghệ An">Nghệ An</option>
                                    <option value="Tỉnh Ninh Bình">Ninh Bình</option>
                                    <option value="Tỉnh Ninh Thuận">Ninh Thuận</option>
                                    <option value="Tỉnh Phú Thọ">Phú Thọ</option>
                                    <option value="Tỉnh Phú Yên">Phú Yên</option>
                                    <option value="Tỉnh Quảng Bình">Quảng Bình</option>
                                    <option value="Tỉnh Quảng Nam">Quảng Nam</option>
                                    <option value="Tỉnh Quảng Ngãi">Quảng Ngãi</option>
                                    <option value="Tỉnh Quảng Ninh">Quảng Ninh</option>
                                    <option value="Tỉnh Quảng Trị">Quảng Trị</option>
                                    <option value="Tỉnh Sóc Trăng">Sóc Trăng</option>
                                    <option value="Tỉnh Sơn La">Sơn La</option>
                                    <option value="Tỉnh Tây Ninh">Tây Ninh</option>
                                    <option value="Tỉnh Thái Bình">Thái Bình</option>
                                    <option value="Tỉnh Thái Nguyên">Thái Nguyên</option>
                                    <option value="Tỉnh Thanh Hóa">Thanh Hóa</option>
                                    <option value="Tỉnh Thừa Thiên Huế">Thừa Thiên Huế</option>
                                    <option value="Tỉnh Tiền Giang">Tiền Giang</option>
                                    <option value="Tỉnh Trà Vinh">Trà Vinh</option>
                                    <option value="Tỉnh Tuyên Quang">Tuyên Quang</option>
                                    <option value="Tỉnh Vĩnh Long">Vĩnh Long</option>
                                    <option value="Tỉnh Vĩnh Phúc">Vĩnh Phúc</option>
                                    <option value="Tỉnh Yên Bái">Yên Bái</option>
                                </select>
                                <div class="multi-select" data-for="filter-place"></div>
                            </div>
                        </div>

                        <!-- Tình trạng hiệu lực -->
                        <div class="filter-pane" id="pane-validity">
                            <h3>Tình trạng hiệu lực</h3>
                            <p class="pane-desc"></p> <!-- Lọc theo trạng thái hiệu lực của gói thầu. -->
                            <div class="field">
                                <select id="filter-validity">
                                    <option value="">-- Tất cả --</option>
                                    <option value="Còn hiệu lực">Còn hiệu lực</option>
                                    <option value="Hết hiệu lực">Hết hiệu lực</option>
                                </select>
                            </div>
                        </div>

                        <!-- Các Input Text Cơ Bản -->
                        <div class="filter-pane" id="pane-qd">
                            <h3>Quyết định phê duyệt</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="approval-decision-container">
                                <input type="text" placeholder="Nhập số quyết định..." />
                                </div>
                                <input type="hidden" id="filter-approval-decision" />
                            </div>
                        </div>

                        <div class="filter-pane" id="pane-conc">
                            <h3>Nồng độ, hàm lượng</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="concentration-container">
                                <input type="text" placeholder="Nhập nồng độ, hàm lượng..." />
                                </div>
                                <input type="hidden" id="filter-concentration" />
                            </div>
                        </div>

                        <div class="filter-pane" id="pane-route">
                            <h3>Đường dùng</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="route-container">
                                <input type="text" placeholder="Nhập đường dùng..." />
                                </div>
                                <input type="hidden" id="filter-route" />
                            </div>
                        </div>

                        <div class="filter-pane" id="pane-dosage">
                            <h3>Dạng bào chế</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="dosage-form-container">
                                <input type="text" placeholder="Nhập dạng bào chế..." />
                                </div>
                                <input type="hidden" id="filter-dosage-form" />
                            </div>
                        </div>

                        <div class="filter-pane" id="pane-spec">
                            <h3>Quy cách đóng gói</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="specification-container">
                                <input type="text" placeholder="Nhập quy cách đóng gói..." />
                                </div>
                                <input type="hidden" id="filter-specification" />
                            </div>
                        </div>

                        <div class="filter-pane" id="pane-group">
                            <h3>Nhóm thuốc</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="drug-group-container">
                                <input type="text" placeholder="Nhập nhóm thuốc..." />
                                </div>
                                <input type="hidden" id="filter-drug-group" />
                            </div>
                        </div>

                        <div class="filter-pane" id="pane-reg">
                            <h3>Số đăng ký</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="reg-no-container">
                                <input type="text" placeholder="Nhập số đăng ký..." />
                                </div>
                                <input type="hidden" id="filter-reg-no" />
                            </div>
                        </div>

                        <div class="filter-pane" id="pane-unit">
                            <h3>Đơn vị tính</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="unit-container">
                                <input type="text" placeholder="Nhập đơn vị tính..." />
                                </div>
                                <input type="hidden" id="filter-unit" />
                            </div>
                        </div>

                        <div class="filter-pane" id="pane-manu">
                            <h3>Cơ sở sản xuất</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="manufacturer-container">
                                <input type="text" placeholder="Nhập cơ sở sản xuất..." />
                                </div>
                                <input type="hidden" id="filter-manufacturer" />
                            </div>
                        </div>

                        <div class="filter-pane" id="pane-country">
                            <h3>Nước sản xuất</h3>
                            <p class="pane-desc"></p>
                            <div class="field">
                                <div class="token-input-container" id="country-container">
                                <input type="text" placeholder="Nhập nước sản xuất..." />
                                </div>
                                <input type="hidden" id="filter-country" />
                            </div>
                        </div>


                    </div> <!-- End Filter Content -->
                </div> <!-- End Filter Layout -->

                <!-- Buttons -->
                <div class="actions">
                    <button class="btn btn-secondary" id="reset-filters-btn">Đặt lại toàn bộ</button>
                    <button class="btn btn-primary" id="apply-filters-btn">Áp dụng bộ lọc</button>
                </div>
            </div>

        `;
        const previewEl = document.createElement('div');
        previewEl.className = 'preview-result';
        previewEl.id = 'preview-result';
        previewEl.textContent = '';
        this.shadowRoot.appendChild(previewEl);
        // ✅ Disable nút áp dụng lúc ban đầu + theo dõi input thay đổi
        this.attachInputListeners();
        this.updateApplyButtonState();
        this.previewDebounceTimer = null;
        this.setupSelectPlaceholderColors();
        this.setupDateEmptyState();
        this.initAdvancedFilters();
        this.setupTabs();
        this.mountPreviewResult();
        this.renderActiveChips();
        requestAnimationFrame(() => this.focusActiveField());

        this.createMultiSelectFromNative('filter-selection-method', {
            placeholder: '-- Chọn hình thức --',
            maxLabels: 2
        });

        this.createMultiSelectFromNative('filter-place', {
            placeholder: '-- Chọn địa điểm --',
            maxLabels: 2
        });

        const root = this.shadowRoot;
        const $from = root.getElementById('filter-date-from');
        const $to   = root.getElementById('filter-date-to');

        this.fpFrom = null;
        this.fpTo = null;

        if (window.flatpickr) {
            this.fpFrom = window.flatpickr($from, {
                dateFormat: 'Y-m-d',
                altInput: true,
                altFormat: 'd/m/Y',
                allowInput: true
            });

            this.fpTo = window.flatpickr($to, {
                dateFormat: 'Y-m-d',
                altInput: true,
                altFormat: 'd/m/Y',
                allowInput: true
            });
        }
        
        // Xử lý tooltip: chỉ bind nếu tooltip thực sự tồn tại
            const helpIcon = root.querySelector('.help-icon');
            const tooltipContent = root.querySelector('.help-tooltip');

            if (helpIcon && tooltipContent) {
                tooltipContent.style.display = 'none';

                let externalTooltip = null;

                helpIcon.addEventListener('mouseenter', () => {
                    externalTooltip = document.createElement('div');
                    externalTooltip.className = 'external-tooltip';
                    externalTooltip.innerHTML = tooltipContent.innerHTML;

                    externalTooltip.style.cssText = `
                        position: absolute;
                        background: #ffffff;
                        border: 1px solid #cfe0ea;
                        border-radius: var(--radius-sm);
                        padding: 16px 18px;
                        width: 420px;
                        max-width: 90vw;
                        box-shadow: 0 18px 36px rgba(16, 34, 48, 0.14);
                        z-index: 999999;
                        font-family: Inter, sans-serif;
                    `;

                    const rect = helpIcon.getBoundingClientRect();
                    externalTooltip.style.top = `${rect.bottom + 8}px`;
                    externalTooltip.style.left = `${rect.left + rect.width / 2 - 210}px`;

                    const style = document.createElement('style');
                    style.textContent = `
                        .external-tooltip .help-tooltip-title {
                            margin: 0 0 10px 0;
                            font-size: 14px;
                            font-weight: 600;
                            color: #0f5b77;
                        }
                        .external-tooltip ul {
                            margin: 0;
                            padding-left: 18px;
                            list-style: none;
                        }
                        .external-tooltip li {
                            margin-bottom: 8px;
                            font-size: 12px;
                            line-height: 1.5;
                            color: #56707f;
                            position: relative;
                        }
                        .external-tooltip li::before {
                            content: '•';
                            position: absolute;
                            left: -14px;
                            color: #127495;
                            font-weight: 700;
                        }
                        .external-tooltip strong {
                            color: #183445;
                            font-weight: 600;
                        }
                        .external-tooltip code {
                            background: rgba(18, 116, 149, 0.10);
                            padding: 2px 6px;
                            border-radius: 4px;
                            font-family: "Courier New", monospace;
                            font-size: 11px;
                            color: #0f5b77;
                            font-weight: 600;
                        }
                    `;

                    document.head.appendChild(style);
                    document.body.appendChild(externalTooltip);
                });

                helpIcon.addEventListener('mouseleave', () => {
                    if (externalTooltip) {
                        externalTooltip.remove();
                        externalTooltip = null;
                    }
                });
            }


        const inputs = root.querySelectorAll('input, select');
        inputs.forEach(input => {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    root.getElementById('apply-filters-btn').click();
                }
            });
        });

        this.bindActionButtons();
        this.updateApplyButtonState();


    }
    
    setupSelectPlaceholderColors() {
        const root = this.shadowRoot;
        const selects = root.querySelectorAll("select");

        const sync = (sel) => {
            sel.classList.toggle("is-placeholder", !sel.value);
        };

        selects.forEach((sel) => {
            if (sel.id === 'filter-selection-method' || sel.id === 'filter-place') return;
            sync(sel);
            sel.addEventListener("change", () => sync(sel));
        });
    }

    setupDateEmptyState() {
        const root = this.shadowRoot;
        const dates = root.querySelectorAll('input[type="date"]');

        const sync = (inp) => inp.classList.toggle("is-empty", !inp.value);

        dates.forEach(inp => {
            sync(inp);
            inp.addEventListener("change", () => sync(inp));
            inp.addEventListener("input", () => sync(inp));
        });
    }

    createMultiSelectFromNative(selectId, { placeholder, maxLabels = 2 }) {
        const root = this.shadowRoot;
        const sel = root.getElementById(selectId);
        const host = root.querySelector(`.multi-select[data-for="${selectId}"]`);
        
        if (!sel || !host) {
            console.error('Không tìm thấy Select hoặc Div Host cho:', selectId);
            return;
        }

        sel.classList.add('js-hidden');

        const getOptions = () => Array.from(sel.options)
            .map(o => ({ value: (o.value ?? '').trim(), label: (o.textContent ?? '').trim() }))
            .filter(o => o.value !== '');

        const options = getOptions();

        host.innerHTML = `
            <button type="button" class="multi-select-btn is-placeholder" aria-expanded="false">
                <span class="multi-select-btn-text"></span>
                <span class="multi-select-caret">▾</span>
            </button>
            <div class="multi-select-popover">
                <div class="multi-select-search"><input type="text" placeholder="Tìm nhanh..."></div>
                <div class="multi-select-options"></div>
                <div class="multi-select-footer">
                    <button type="button" class="multi-select-clear">Xoá chọn</button>
                    <button type="button" class="multi-select-done">Xong</button>
                </div>
            </div>
        `;

        const btn = host.querySelector('.multi-select-btn');
        const btnText = host.querySelector('.multi-select-btn-text');
        const search = host.querySelector('.multi-select-search input');
        const list = host.querySelector('.multi-select-options');
        const btnClear = host.querySelector('.multi-select-clear');
        const btnDone = host.querySelector('.multi-select-done');

        const readSelectedValuesFromSelect = () => Array.from(sel.selectedOptions || [])
            .map(o => (o.value ?? '').trim()).filter(Boolean);

        const renderList = (query, selectedValuesSet) => {
            const q = (query ?? '').trim().toLowerCase();
            const filtered = options.filter(o => !q || o.label.toLowerCase().includes(q));

            if (filtered.length === 0) {
                list.innerHTML = `<div style="padding:10px 12px;color:#93A0B2;font-size:13px;">Không có kết quả</div>`;
                return;
            }

            list.innerHTML = filtered.map(o => `
            <label class="multi-select-option">
                <input type="checkbox" value="${o.value.replace(/"/g, '&quot;')}" ${selectedValuesSet.has(o.value) ? 'checked' : ''}>
                <span>${o.label}</span>
            </label>
            `).join('');
        };

        const refreshFromSelect = () => {
            const selectedValues = readSelectedValuesFromSelect();
            const selectedSet = new Set(selectedValues);
            
            if (selectedValues.length === 0) {
                btnText.textContent = placeholder;
                btn.classList.add('is-placeholder');
            } else if (selectedValues.length <= maxLabels) {
                btnText.textContent = selectedValues.join(', ');
                btn.classList.remove('is-placeholder');
            } else {
                btnText.textContent = `Đã chọn ${selectedValues.length}`;
                btn.classList.remove('is-placeholder');
            }

            if (host.classList.contains('open')) renderList(search.value, selectedSet);
        };

        const open = () => {
            // Đóng tất cả các multi-select khác trước khi mở cái này
            root.querySelectorAll('.multi-select.open').forEach(el => el.classList.remove('open'));
            host.classList.add('open');
            btn.setAttribute('aria-expanded', 'true');
            renderList(search.value, new Set(readSelectedValuesFromSelect()));
        };

        const close = () => {
            host.classList.remove('open');
            btn.setAttribute('aria-expanded', 'false');
        };

        // Chống lặp Event
        if (host.dataset.bound === '1') { refreshFromSelect(); return; }
        host.dataset.bound = '1';

        btn.addEventListener('click', (e) => {
            e.stopPropagation(); // Ngăn sự kiện click nổi bọt ra ngoài
            if (host.classList.contains('open')) close(); else open();
        });

        btnDone.addEventListener('click', (e) => { e.stopPropagation(); close(); });

        btnClear.addEventListener('click', (e) => {
            e.stopPropagation();

            Array.from(sel.options).forEach(o => { o.selected = false; });
            const emptyOpt = Array.from(sel.options).find(o => (o.value || '').trim() === '');
            if (emptyOpt) emptyOpt.selected = false;

            sel.selectedIndex = -1;
            sel.value = '';
            sel.dispatchEvent(new Event('change', { bubbles: true }));

            this.clearFilterOrder(selectId);
            refreshFromSelect();
            this.updateApplyButtonState();
            this.renderActiveChips();
            this.queueFocusActiveField();
        });


        search.addEventListener('input', (e) => {
            e.stopPropagation();
            renderList(search.value, new Set(readSelectedValuesFromSelect()));
        });

        list.addEventListener('change', (e) => {
            e.stopPropagation();
            const cb = e.target?.closest('input[type="checkbox"]');
            if (!cb) return;

            const v = (cb.value ?? '').trim();
            const opt = Array.from(sel.options).find(o => (o.value ?? '').trim() === v);
            if (opt) {
                opt.selected = cb.checked;

                const emptyOpt = Array.from(sel.options).find(o => (o.value || '').trim() === '');
                if (emptyOpt) emptyOpt.selected = false;

                sel.dispatchEvent(new Event('change', { bubbles: true }));

                const hasAny = this.getNonEmptySelectedValues(selectId).length > 0;
                if (hasAny) this.rememberFilterOrder(selectId);
                else this.clearFilterOrder(selectId);

                refreshFromSelect();
                this.updateApplyButtonState();
                this.renderActiveChips();
            }
        });

        // Click ra ngoài để đóng
        document.addEventListener('click', (e) => {
            if (host.classList.contains('open') && !host.contains(e.composedPath()[0])) {
                close();
            }
        });

        refreshFromSelect();
    }


    updateApplyButtonState() {
        const root = this.shadowRoot;
        if (!root) return;

        const applyBtn = root.getElementById('apply-filters-btn');
        const resetBtn = root.getElementById('reset-filters-btn');
        if (!applyBtn || !resetBtn) return;

        const payload = this.collectFilterPayload();
        const filters = payload?.filters || {};

        const hasAnyValue = Object.values(filters).some(value => {
            if (Array.isArray(value)) return value.length > 0;
            if (value && typeof value === 'object' && Array.isArray(value.tokens)) {
                return value.tokens.length > 0;
            }
            return value !== null && value !== undefined && String(value).trim() !== '';
        });

        applyBtn.disabled = !hasAnyValue;
        resetBtn.disabled = !hasAnyValue;

        applyBtn.title = hasAnyValue ? '' : 'Vui lòng nhập hoặc chọn ít nhất một tiêu chí tìm kiếm';
        resetBtn.title = hasAnyValue ? '' : 'Không có điều kiện để đặt lại';
        this.queuePreviewUpdate(hasAnyValue);
    }

    queuePreviewUpdate(hasAnyValue = true) {
        clearTimeout(this.previewDebounceTimer);

        if (!hasAnyValue) {
            this.setPreviewResult({ idle: true });
            return;
        }

        this.setPreviewResult({ loading: true });
        this.previewDebounceTimer = setTimeout(() => {
            const payload = this.collectFilterPayload();
            this.dispatchEvent(new CustomEvent('preview-filters', {
                detail: payload,
                bubbles: true,
                composed: true
            }));
        }, 280);
    }

    mountPreviewResult() {
        const root = this.shadowRoot;
        const previewEl = root?.getElementById('preview-result');
        const activePane = root?.querySelector('.filter-pane.active');
        if (!previewEl || !activePane) return;

        const anchor = activePane.querySelector('.fields-row, .field, .multi-select, .token-input-container');
        if (anchor?.parentNode) {
            anchor.insertAdjacentElement('afterend', previewEl);
        } else {
            activePane.appendChild(previewEl);
        }
    }

    focusActiveField() {
        const root = this.shadowRoot;
        const activePane = root?.querySelector('.filter-pane.active');
        if (!activePane) return;

        const preferredInput = activePane.querySelector(
            '.token-input-container input, .field input, .field select, .multi-select-btn'
        );

        if (preferredInput) {
            preferredInput.focus();
            preferredInput.select?.();
        }
    }

    queueFocusActiveField() {
        requestAnimationFrame(() => this.focusActiveField());
        setTimeout(() => this.focusActiveField(), 60);
    }

    activatePane(paneKey, { focus = true } = {}) {
        const root = this.shadowRoot;
        if (!root || !paneKey) return;

        const targetId = `pane-${paneKey}`;
        const targetItem = root.querySelector(`.sidebar-item[data-target="${targetId}"]`);
        const targetPane = root.getElementById(targetId);
        if (!targetItem || !targetPane) return;

        root.querySelectorAll('.sidebar-item').forEach(i => i.classList.remove('active'));
        root.querySelectorAll('.filter-pane').forEach(p => p.classList.remove('active'));

        targetItem.classList.add('active');
        targetPane.classList.add('active');
        this.mountPreviewResult();

        if (focus) {
            this.queueFocusActiveField();
        }
    }

    setPreviewResult({ idle = false, loading = false, total = null, error = false } = {}) {
        const root = this.shadowRoot;
        const previewEl = root?.getElementById('preview-result');
        if (!previewEl) return;
        this.mountPreviewResult();

        previewEl.className = 'preview-result';

        if (idle) {
            previewEl.textContent = '';
            return;
        }

        if (loading) {
            previewEl.textContent = 'Đang ước tính...';
            previewEl.classList.add('is-loading');
            return;
        }

        if (error) {
            previewEl.textContent = 'Không ước tính được số kết quả';
            previewEl.classList.add('is-error');
            return;
        }

        if (typeof total === 'number') {
            previewEl.textContent = `Có ${total.toLocaleString('vi-VN')} kết quả`;
            if (total === 0) previewEl.classList.add('is-warning');
        }
    }


    bindActionButtons() {
        const root = this.shadowRoot;
        if (!root) return;

        const applyBtn = root.getElementById('apply-filters-btn');
        const resetBtn = root.getElementById('reset-filters-btn');

        if (applyBtn && !applyBtn.dataset.bound) {
            applyBtn.dataset.bound = '1';
            applyBtn.addEventListener('click', () => {
                if (applyBtn.disabled) return;

                const payload = this.collectFilterPayload();
                this.dispatchEvent(new CustomEvent('apply-filters', {
                    detail: payload,
                    bubbles: true,
                    composed: true
                }));
            });
        }

        if (resetBtn && !resetBtn.dataset.bound) {
            resetBtn.dataset.bound = '1';
            resetBtn.addEventListener('click', () => {
                this.resetAllFilters();
            });
        }
    }

    resetAllFilters() {
        const root = this.shadowRoot;
        if (!root) return;

        this.fpFrom?.clear();
        this.fpTo?.clear();

        if (this.advancedFilterManagers) {
            this.advancedFilterManagers.forEach(manager => {
                manager.tokens = [];
                if (manager.input) manager.input.value = '';
                manager.renderTokens();
                manager.syncToHiddenInput();
                if (manager.closeDropdown) manager.closeDropdown();
            });
        }

        ['filter-date-from', 'filter-date-to', 'filter-validity'].forEach(id => {
            const el = root.getElementById(id);
            if (!el) return;
            el.value = '';
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            this.clearFilterOrder(id);
        });

        [
            ['filter-selection-method', '-- Chọn hình thức --'],
            ['filter-place', '-- Chọn địa điểm --']
        ].forEach(([id, placeholder]) => {
            const sel = root.getElementById(id);
            const host = root.querySelector(`.multi-select[data-for="${id}"]`);
            if (!sel) return;

            Array.from(sel.options).forEach(o => o.selected = false);
            sel.selectedIndex = -1;
            sel.value = '';
            sel.dispatchEvent(new Event('change', { bubbles: true }));

            if (host) {
                host.classList.remove('open');
                const btn = host.querySelector('.multi-select-btn');
                const btnText = host.querySelector('.multi-select-btn-text');
                const search = host.querySelector('.multi-select-search input');
                const list = host.querySelector('.multi-select-options');

                if (btn) btn.classList.add('is-placeholder');
                if (btnText) btnText.textContent = placeholder;
                if (search) search.value = '';
                if (list) list.innerHTML = '';
            }

            this.clearFilterOrder(id);
        });

        this.filterOrder = [];
        this.updateApplyButtonState();
        this.renderActiveChips();
        this.setPreviewResult({ idle: true });

        this.dispatchEvent(new CustomEvent('reset-filters', {
            bubbles: true,
            composed: true
        }));

        this.queueFocusActiveField();
    }

    setFilterPayload(payload = {}) {
        const root = this.shadowRoot;
        if (!root) return;

        const filters = payload?.filters || {};

        if (this.advancedFilterManagers) {
            this.advancedFilterManagers.forEach(manager => {
                const normalized = filters[manager.fieldName];
                manager.tokens = [];

                if (normalized?.tokens?.length) {
                    normalized.tokens.forEach((token, index) => {
                        if (index > 0) {
                            manager.tokens.push({
                                type: 'operator',
                                text: token.op || 'OR'
                            });
                        }
                        manager.tokens.push({
                            type: 'value',
                            text: token.value || ''
                        });
                    });
                }

                if (manager.input) manager.input.value = '';
                manager.renderTokens();
                manager.syncToHiddenInput();
            });
        }

        const setMultiValues = (id, values = []) => {
            const select = root.getElementById(id);
            if (!select) return;

            const selected = new Set(values.map(v => String(v).trim()));
            Array.from(select.options).forEach(option => {
                option.selected = selected.has(String(option.value || '').trim());
            });
            select.dispatchEvent(new Event('change', { bubbles: true }));
        };

        setMultiValues('filter-selection-method', filters.selectionMethod || []);
        setMultiValues('filter-place', filters.place || []);

        const validity = root.getElementById('filter-validity');
        if (validity) validity.value = filters.validity || '';

        if (this.fpFrom) {
            this.fpFrom.clear();
            if (filters.dateFrom) this.fpFrom.setDate(filters.dateFrom, false, 'Y-m-d');
        } else {
            const fromInput = root.getElementById('filter-date-from');
            if (fromInput) fromInput.value = filters.dateFrom || '';
        }

        if (this.fpTo) {
            this.fpTo.clear();
            if (filters.dateTo) this.fpTo.setDate(filters.dateTo, false, 'Y-m-d');
        } else {
            const toInput = root.getElementById('filter-date-to');
            if (toInput) toInput.value = filters.dateTo || '';
        }

        this.filterOrder = [];
        this.updateApplyButtonState();
        this.renderActiveChips();
        this.mountPreviewResult();
        this.queueFocusActiveField();
    }

    attachInputListeners() {
        const root = this.shadowRoot;
        if (!root) return;

        const ids = [
            'filter-date-from',
            'filter-date-to',
            'filter-selection-method',
            'filter-place',
            'filter-validity'
        ];

        ids.forEach(id => {
            const el = root.getElementById(id);
            if (!el) return;

            const handler = () => {
            const hasValue = el.tagName === 'SELECT' && el.multiple
                ? Array.from(el.selectedOptions).some(o => o.value.trim())
                : !!el.value?.toString().trim();

            if (id === 'filter-date-from' || id === 'filter-date-to') {
                const from = root.getElementById('filter-date-from')?.value?.trim();
                const to = root.getElementById('filter-date-to')?.value?.trim();
                if (from || to) this.rememberFilterOrder('date');
                else this.clearFilterOrder('date');
            } else {
                if (hasValue) this.rememberFilterOrder(id);
                else this.clearFilterOrder(id);
            }

            this.updateApplyButtonState();
            this.renderActiveChips();
            };

            el.addEventListener('input', handler);
            el.addEventListener('change', handler);
        });
    }


    getDynamicFieldConfigs() {
        return [
            { containerId: 'investor-container', field: 'investor', hiddenId: 'filter-investor', label: 'Chủ đầu tư', pane: 'investor' },
            { containerId: 'approval-decision-container', field: 'approvalDecision', hiddenId: 'filter-approval-decision', label: 'QĐ phê duyệt', pane: 'qd' },
            { containerId: 'drug-name-container', field: 'drugName', hiddenId: 'filter-drug-name', label: 'Thuốc / hàng hóa', pane: 'drug' },
            { containerId: 'active-ingredient-container', field: 'activeIngredient', hiddenId: 'filter-active-ingredient', label: 'Hoạt chất', pane: 'active-ing' },
            { containerId: 'concentration-container', field: 'concentration', hiddenId: 'filter-concentration', label: 'Nồng độ, hàm lượng', pane: 'conc' },
            { containerId: 'route-container', field: 'route', hiddenId: 'filter-route', label: 'Đường dùng', pane: 'route' },
            { containerId: 'dosage-form-container', field: 'dosageForm', hiddenId: 'filter-dosage-form', label: 'Dạng bào chế', pane: 'dosage' },
            { containerId: 'specification-container', field: 'specification', hiddenId: 'filter-specification', label: 'Quy cách đóng gói', pane: 'spec' },
            { containerId: 'drug-group-container', field: 'drugGroup', hiddenId: 'filter-drug-group', label: 'Nhóm thuốc', pane: 'group' },
            { containerId: 'reg-no-container', field: 'regNo', hiddenId: 'filter-reg-no', label: 'Số đăng ký', pane: 'reg' },
            { containerId: 'unit-container', field: 'unit', hiddenId: 'filter-unit', label: 'Đơn vị tính', pane: 'unit' },
            { containerId: 'manufacturer-container', field: 'manufacturer', hiddenId: 'filter-manufacturer', label: 'Cơ sở sản xuất', pane: 'manu' },
            { containerId: 'country-container', field: 'country', hiddenId: 'filter-country', label: 'Nước sản xuất', pane: 'country' }
        ];
    }

    initAdvancedFilters() {
        const root = this.shadowRoot;
        if (!root) return;

        this.advancedFilterManagers = [];
        this.dynamicFieldMeta = new Map();

        this.getDynamicFieldConfigs().forEach(config => {
            const container = root.getElementById(config.containerId);
            if (!container) return;

            this.dynamicFieldMeta.set(config.field, config);

            const manager = new AdvancedFilterManager({
            containerElement: container,
            fieldName: config.field,
            shadowRoot: root,
            hiddenInputId: config.hiddenId,
            getContextFilters: () => this.collectFilterPayload(config.field),
            onStateChange: () => {
                const normalized = manager.getNormalizedValue();
                if (normalized) this.rememberFilterOrder(config.hiddenId);
                else this.clearFilterOrder(config.hiddenId);
                this.updateApplyButtonState();
                this.renderActiveChips();
            }
            });

            this.advancedFilterManagers.push(manager);
        });
    }


    collectFilterPayload({ excludeField = null } = {}) {
        const root = this.shadowRoot;
        const filters = {};

        const managerMap = new Map(
            (this.advancedFilterManagers || []).map(m => [m.fieldName, m])
        );

        for (const [fieldName, manager] of managerMap.entries()) {
            if (fieldName === excludeField) continue;
            const normalized = manager.getNormalizedValue();
            if (normalized && normalized.tokens && normalized.tokens.length) {
            filters[fieldName] = normalized;
            }
        }

        const getSelectedValues = (id) =>
            Array.from(root.getElementById(id)?.selectedOptions || [])
            .map(o => (o.value || '').trim())
            .filter(Boolean);

        const selectionMethod = getSelectedValues('filter-selection-method');
        const place = getSelectedValues('filter-place');
        const validity = root.getElementById('filter-validity')?.value?.trim();
        const dateFrom = root.getElementById('filter-date-from')?.value?.trim();
        const dateTo = root.getElementById('filter-date-to')?.value?.trim();

        if (selectionMethod.length) filters.selectionMethod = selectionMethod;
        if (place.length) filters.place = place;
        if (validity) filters.validity = validity;
        if (dateFrom) filters.dateFrom = dateFrom;
        if (dateTo) filters.dateTo = dateTo;

        return {
            scope: 'all',
            filters
        };
    }


    setupTabs() {
        const root = this.shadowRoot;
        const items = root.querySelectorAll('.sidebar-item');
        const panes = root.querySelectorAll('.filter-pane');
        
        items.forEach(item => {
            item.addEventListener('click', () => {
                const targetId = item.getAttribute('data-target') || '';
                const paneKey = targetId.replace(/^pane-/, '');
                this.activatePane(paneKey);
            });
        });
    }

    renderActiveChips() {
        const root = this.shadowRoot;
        const list = root.getElementById('active-filters-list');
        const sidebarItems = root.querySelectorAll('.sidebar-item');

        if (!this.filterOrder) this.filterOrder = [];
        sidebarItems.forEach(i => i.classList.remove('has-value'));

        const markSidebar = (paneId) => {
            const item = root.querySelector(`[data-target="pane-${paneId}"]`);
            if (item) item.classList.add('has-value');
        };

        const filterMap = new Map();

        const dFrom = root.getElementById('filter-date-from')?.value?.trim();
        const dTo = root.getElementById('filter-date-to')?.value?.trim();
        if (dFrom || dTo) {
            const fromText = this.formatDisplayDate(dFrom);
            const toText = this.formatDisplayDate(dTo);

            filterMap.set('date', {
                label: 'Ngày phê duyệt:',
                value: [fromText, toText].filter(Boolean).join(' → '),
                pane: 'date'
            });
        }

        (this.advancedFilterManagers || []).forEach(manager => {
            const normalized = manager.getNormalizedValue();
            if (!normalized?.tokens?.length) return;

            const meta = this.dynamicFieldMeta?.get(manager.fieldName);
            if (!meta) return;

            const display = normalized.tokens.reduce((parts, t, index) => {
                const value = String(t.value || '').trim();
                if (!value) return parts;

                if (index === 0) {
                    parts.push(value);
                } else {
                    parts.push(`(${t.op || 'OR'})`);
                    parts.push(value);
                }

                return parts;
            }, []).join(' ');

            filterMap.set(meta.hiddenId, {
            label: `${meta.label}:`,
            value: display,
            pane: meta.pane
            });
        });

        [
            { id: 'filter-selection-method', label: 'Hình thức LCNT', pane: 'method' },
            { id: 'filter-place', label: 'Tỉnh/TP', pane: 'place' }
        ].forEach(f => {
            const values = this.getNonEmptySelectedValues(f.id);
            if (values.length > 0) {
            filterMap.set(f.id, {
                label: `${f.label}:`,
                value: values.map(v => v.label).join(', '),
                pane: f.pane
            });
            }
        });

        [
            { id: 'filter-validity', label: 'Tình trạng hiệu lực', pane: 'validity' }
        ].forEach(f => {
            const value = root.getElementById(f.id)?.value?.trim();
            if (value) {
            filterMap.set(f.id, {
                label: `${f.label}:`,
                value,
                pane: f.pane
            });
            }
        });

        this.filterOrder = this.filterOrder.filter(id => filterMap.has(id));
        for (const id of filterMap.keys()) {
            if (!this.filterOrder.includes(id)) this.filterOrder.push(id);
        }

        if (this.filterOrder.length === 0) {
            list.innerHTML = `<span class="empty-filters">Chưa có điều kiện lọc nào</span>`;
            return;
        }

        list.innerHTML = this.filterOrder
            .filter(id => filterMap.has(id))
            .map(id => {
            const item = filterMap.get(id);
            markSidebar(item.pane);
            return `<div class="filter-chip"><strong>${item.label}</strong> ${item.value}<span class="chip-remove" data-clear="${id}">&times;</span></div>`;
            })
            .join('');

        list.querySelectorAll('.chip-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
            const id = e.target.getAttribute('data-clear');
            const chipMeta = filterMap.get(id);

            if (id === 'date') {
                const from = root.getElementById('filter-date-from');
                const to = root.getElementById('filter-date-to');
                if (from) from.value = '';
                if (to) to.value = '';
                from?.dispatchEvent(new Event('input', { bubbles: true }));
                to?.dispatchEvent(new Event('input', { bubbles: true }));
            } else if ((this.advancedFilterManagers || []).some(m => m.hiddenInput?.id === id)) {
                const manager = this.advancedFilterManagers.find(m => m.hiddenInput?.id === id);
                if (manager) {
                manager.tokens = [];
                if (manager.input) manager.input.value = '';
                manager.renderTokens();
                manager.syncToHiddenInput();
                }
            } else if (['filter-selection-method', 'filter-place'].includes(id)) {
                const select = root.getElementById(id);
                if (select) {
                Array.from(select.options).forEach(o => { o.selected = false; });
                select.selectedIndex = -1;
                select.value = '';
                select.dispatchEvent(new Event('change', { bubbles: true }));
                }
            } else {
                const inp = root.getElementById(id);
                if (inp) {
                inp.value = '';
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                }
            }

            this.filterOrder = this.filterOrder.filter(x => x !== id);
            this.updateApplyButtonState();
            this.renderActiveChips();
            if (chipMeta?.pane) {
                this.activatePane(chipMeta.pane, { focus: false });
            }
            this.queueFocusActiveField();
            });
        });
    }


    formatDisplayDate(value) {
        const s = String(value || '').trim();
        if (!s) return '';

        if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
            const [y, m, d] = s.split('-');
            return `${d}/${m}/${y}`;
        }

        if (/^\d{2}\/\d{2}\/\d{4}$/.test(s)) {
            return s;
        }

        return s;
    }


    rememberFilterOrder(id) {
        if (!this.filterOrder) this.filterOrder = [];
        this.filterOrder = this.filterOrder.filter(x => x !== id);
        this.filterOrder.push(id);
    }

    clearFilterOrder(id) {
        if (!this.filterOrder) this.filterOrder = [];
        this.filterOrder = this.filterOrder.filter(x => x !== id);
    }

    getNonEmptySelectedValues(selectId) {
        const sel = this.shadowRoot.getElementById(selectId);
        if (!sel) return [];

        return Array.from(sel.options)
            .filter(o => o.selected && (o.value || '').trim() !== '')
            .map(o => ({
                value: (o.value || '').trim(),
                label: (o.textContent || '').trim()
            }));
    }

    formatFilterDisplayValue(filterId, raw) {
        if (!raw) return '';

        const tokenizedFields = [
            'filter-investor',
            'filter-drug-name',
            'filter-active-ingredient'
        ];

        if (!tokenizedFields.includes(filterId)) return raw;

        return raw
            .replace(/\s+/g, ' ')
            .replace(/\s*-\s*/g, ' NOT ')
            .replace(/\s*OR\s*/gi, ' OR ')
            .replace(/\s*AND\s*/gi, ' AND ')
            .trim();
    }

}


class AdvancedFilterManager {
    constructor({
        containerElement,
        fieldName,
        shadowRoot,
        hiddenInputId,
        getContextFilters = () => ({ scope: 'all', filters: {} }),
        onStateChange = () => {}
    }) {
        this.container = containerElement;
        this.fieldName = fieldName;
        this.shadowRoot = shadowRoot;
        this.hiddenInput = shadowRoot.getElementById(hiddenInputId);
        this.getContextFilters = getContextFilters;
        this.onStateChange = onStateChange;

        this.tokens = [];
        this.input = this.container.querySelector('input');
        this.debounceTimer = null;
        this.abortController = null;
        this.cache = new Map();
        this.currentIndex = -1;

        this.dropdown = document.createElement('ul');
        this.dropdown.className = 'autocomplete-dropdown hidden';
        this.container.parentNode.style.position = 'relative';
        this.container.parentNode.appendChild(this.dropdown);

        this.initEvents();
    }

    initEvents() {
        // Focus vào input khi click vùng trống
        this.container.addEventListener('click', (e) => {
            if (e.target === this.container) this.input.focus();
        });

        this.input.addEventListener('input', () => this.onInput());
        this.input.addEventListener('focus', () => this.onInput());
        
        // Xử lý phím (Backspace để xóa tag, Mũi tên để chọn dropdown)
        this.input.addEventListener('keydown', e => {
            const raw = String(this.input.value || '').trim();

            if (e.key === 'Enter') {
                e.preventDefault();

                if (this.currentIndex >= 0) {
                    const active = this.dropdown.querySelector(`li[data-index="${this.currentIndex}"]`);
                    if (active) {
                        active.click();
                        return;
                    }
                }

                if (raw) {
                    this.appendValueToken(raw);
                    this.input.value = '';
                    this.closeDropdown();
                    this.syncToHiddenInput();
                    requestAnimationFrame(() => {
                        this.input?.focus();
                    });
                }
                return;
            }

            if (e.key === 'Backspace' && !this.input.value) {
                if (this.tokens.length > 0) {
                    this.tokens.splice(-2);
                    this.renderTokens();
                    this.syncToHiddenInput();
                    requestAnimationFrame(() => this.input?.focus());
                }
                return;
            }

            this.onKeyDown(e);
        });

        document.addEventListener('click', (e) => {
            const path = e.composedPath();
            if (!path.includes(this.container) && !path.includes(this.dropdown)) {
                this.closeDropdown();
            }
        });
    }

    renderTokens() {
        const oldTags = this.container.querySelectorAll('.token-tag, .token-operator');
        oldTags.forEach(tag => tag.remove());

        this.tokens.forEach((token, index) => {
            const el = document.createElement('span');
            
            if (token.type === 'operator') {
                el.className = 'token-operator';
                el.textContent = token.text;
                el.addEventListener('click', () => {
                    const ops = ['OR', 'AND', 'NOT'];
                    let nextIdx = (ops.indexOf(token.text) + 1) % ops.length;
                    token.text = ops[nextIdx];
                    this.renderTokens();
                    this.syncToHiddenInput();
                });
            } else {
                el.className = 'token-tag';
                const displayText = token.text.length > 30 ? token.text.substring(0, 30) + '...' : token.text;
                
                el.innerHTML = `
                    <span class="tag-text">${displayText}</span>
                    <span class="token-remove">&times;</span>
                `;
                
                el.querySelector('.token-remove').addEventListener('click', () => {
                    if (index === 0 && this.tokens.length > 1) {
                        this.tokens.splice(0, 2);
                    } else if (index > 0) {
                        this.tokens.splice(index - 1, 2);
                    } else {
                        this.tokens = [];
                    }
                    this.renderTokens();
                    this.syncToHiddenInput();
                    requestAnimationFrame(() => this.input?.focus());
                });
            }
            
            this.container.insertBefore(el, this.input);
        });
    }

    syncToHiddenInput() {
        const normalized = this.getNormalizedValue();
        if (this.hiddenInput) {
            this.hiddenInput.value = normalized ? JSON.stringify(normalized) : '';
            this.hiddenInput.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
            this.hiddenInput.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
        }
        this.onStateChange(normalized);
    }


    async onInput() {
        const query = this.input.value.trim();
        this.currentIndex = -1;
        this.resetDropdownScroll();

        if (query.length < 2) {
            this.closeDropdown();
            return;
        }

        clearTimeout(this.debounceTimer);
        this.debounceTimer = setTimeout(() => this.fetchData(query), 280);
    }


    async fetchData(query) {
        if (this.abortController) this.abortController.abort();
        this.abortController = new AbortController();

        const payload = {
            filters: (this.getContextFilters?.() || {}).filters || {},
            scope: 'all',
            field: this.fieldName,
            keyword: query,
            excludeSelf: true,
            limit: 10
        };

        const cacheKey = JSON.stringify(payload);
        if (this.cache.has(cacheKey)) {
            this.renderDropdown(this.cache.get(cacheKey), query);
            return;
        }

        try {
            const apiBase = this.getApiBaseUrl();
            const res = await fetch(`${apiBase}/api/autocomplete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            signal: this.abortController.signal
            });

            const rawText = await res.text();

            if (!res.ok) {
            console.log('Autocomplete field:', this.fieldName, 'payload:', payload);
            console.error('Autocomplete HTTP error:', res.status, rawText);
            this.closeDropdown();
            return;
            }

            if (!rawText || !rawText.trim()) {
            console.error('Autocomplete trả về body rỗng');
            this.closeDropdown();
            return;
            }

            let result;
            try {
            result = JSON.parse(rawText);
            } catch (parseErr) {
            console.error('Autocomplete response không phải JSON hợp lệ:', rawText);
            this.closeDropdown();
            return;
            }

            const suggestions = Array.isArray(result?.data) ? result.data : [];
            this.cache.set(cacheKey, suggestions);
            this.renderDropdown(suggestions, query);
        } catch (err) {
            if (err.name !== 'AbortError') {
            console.error('Fetch autocomplete lỗi:', err);
            this.closeDropdown();
            }
        }
    }



    appendValueToken(selectedText) {
        const cleanText = (selectedText || '').trim();
        if (!cleanText) return;

        const hasValueToken = this.tokens.some(t => t.type === 'value');
        if (hasValueToken) {
            this.tokens.push({ type: 'operator', text: 'OR' });
        }

        this.tokens.push({ type: 'value', text: cleanText });

        this.input.value = '';
        this.currentIndex = -1;
        this.closeDropdown();
        requestAnimationFrame(() => {
            this.input?.focus();
        });
        this.renderTokens();
        this.syncToHiddenInput();
    }



    renderDropdown(items, currentQuery) {
        this.dropdown.innerHTML = '';
        if (!Array.isArray(items) || items.length === 0) {
            this.closeDropdown();
            return;
        }

        const safeQuery = (currentQuery || '').trim();
        const regex = safeQuery
            ? new RegExp(`(${safeQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
            : null;

        items.forEach((item, index) => {
            const li = document.createElement('li');
            li.dataset.index = index;
            li.dataset.value = item;

            li.innerHTML = regex
                ? item.replace(regex, '<strong>$1</strong>')
                : item;

            li.addEventListener('click', () => {
                const selectedText = li.dataset.value;
                this.appendValueToken(selectedText);
                requestAnimationFrame(() => {
                    this.input?.focus();
                });
            });

            this.dropdown.appendChild(li);
        });

        this.dropdown.classList.remove('hidden');
        this.currentIndex = -1;
        this.resetDropdownScroll();
    }

    onKeyDown(e) {
        if (this.dropdown.classList.contains('hidden')) return;

        const items = this.dropdown.querySelectorAll('li');
        if (items.length === 0) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.currentIndex = (this.currentIndex + 1) % items.length;
            this.updateActiveItem(items);
        } 
        else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.currentIndex = (this.currentIndex - 1 + items.length) % items.length;
            this.updateActiveItem(items);
        }
        else if (e.key === 'Enter') {
            e.preventDefault();

            if (this.currentIndex >= 0 && this.currentIndex < items.length) {
                const itemValue = items[this.currentIndex].dataset.value;
                this.appendValueToken(itemValue);
            } else {
                const rawText = this.input.value.trim();
                if (rawText !== '') {
                    this.appendValueToken(rawText);
                }
            }
        }
        else if (e.key === 'Escape') {
            this.closeDropdown();
        }
    }


    closeDropdown() { 
        this.dropdown.classList.add('hidden'); 
    }

    resetDropdownScroll() {
        if (this.dropdown) {
            this.dropdown.scrollTop = 0;
        }
    }


    updateActiveItem(items) {
        items.forEach(item => item.classList.remove('active'));
        if (this.currentIndex >= 0) {
            const activeItem = items[this.currentIndex];
            activeItem.classList.add('active');
            activeItem.scrollIntoView({ block: 'nearest' });
        }
    }

    getNormalizedValue() {
        if (!Array.isArray(this.tokens) || this.tokens.length === 0) return null;

        const normalized = [];
        let pendingOp = 'OR';

        for (const token of this.tokens) {
            if (!token) continue;

            if (token.type === 'operator') {
                pendingOp = token.text || 'OR';
                continue;
            }

            if (token.type === 'value') {
                const value = String(token.text || '').trim();
                if (!value) continue;

                normalized.push({
                    value,
                    op: normalized.length === 0 ? 'OR' : pendingOp || 'OR'
                });

                pendingOp = 'OR';
            }
        }

        if (!normalized.length) return null;

        return { tokens: normalized };
    }



    getApiBaseUrl() {
        if (window.API_BASE_URL && typeof window.API_BASE_URL === 'string') {
            return window.API_BASE_URL;
        }

        const isLocal =
            window.location.protocol === 'file:' ||
            window.location.hostname === 'localhost' ||
            window.location.hostname === '127.0.0.1';

        return isLocal
            ? 'http://127.0.0.1:8000'
            : 'https://bidfinder.onrender.com';
    }


}


customElements.define('custom-search-form', CustomSearchForm);
