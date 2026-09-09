(function () {
    const GROUP_SCOPE = { goods: 'goods', medicines: 'medicine', traditional: 'traditional' };
    const GROUP_LABELS = { goods: 'Hàng hóa', medicines: 'Thuốc', traditional: 'Dược liệu' };
    const FIELD_ORDER = {
        goods: ['item_name', 'model_mark', 'brand', 'technical_specification', 'unit', 'quantity', 'winning_unit_price', 'winning_bidder_name', 'bid_invitation_code', 'procuring_entity_name', 'decision_number', 'decision_issued_at', 'selection_method', 'manufacturer', 'production_year', 'country_of_origin', 'model', 'registration_or_import_permit_number', 'hs_code', 'winning_bidder_id', 'procuring_entity_id', 'result_posted_at', 'bidder_count', 'location'],
        medicines: ['medicine_name', 'active_ingredient_or_herbal_component', 'strength', 'marketing_authorization_or_import_permit', 'unit', 'quantity', 'winning_unit_price', 'medicine_group', 'winning_bidder_name', 'bid_invitation_code', 'procuring_entity_name', 'decision_number', 'decision_issued_at', 'selection_method', 'route_of_administration', 'dosage_form', 'packaging', 'shelf_life', 'manufacturer', 'production_country', 'winning_bidder_id', 'procuring_entity_id', 'result_posted_at', 'bidder_count', 'location'],
        traditional: ['item_name', 'used_part', 'scientific_name', 'registration_or_import_permit_number', 'unit', 'quantity', 'winning_unit_price', 'technical_group', 'winning_bidder_name', 'bid_invitation_code', 'procuring_entity_name', 'decision_number', 'decision_issued_at', 'selection_method', 'origin', 'processing_method', 'packaging', 'manufacturer', 'production_country', 'winning_bidder_id', 'procuring_entity_id', 'result_posted_at', 'bidder_count', 'location']
    };
    const FIELD_LABELS = {
        goods: {
            item_name: 'Tên hàng hóa', unit: 'Đơn vị tính', quantity: 'Khối lượng', country_of_origin: 'Xuất xứ', hs_code: 'Mã HS', model_mark: 'Ký mã hiệu', brand: 'Nhãn hiệu', production_year: 'Năm sản xuất', manufacturer: 'Hãng sản xuất', technical_specification: 'Cấu hình, tính năng kỹ thuật', model: 'Chủng loại (model)', registration_or_import_permit_number: 'Số ĐKLH / Giấy phép NK', winning_unit_price: 'Đơn giá trúng thầu', winning_bidder_id: 'Mã định danh NT trúng thầu', winning_bidder_name: 'Tên NT trúng thầu', bid_invitation_code: 'Mã TBMT', procuring_entity_id: 'Mã định danh CĐT', procuring_entity_name: 'Tên CĐT', selection_method: 'Hình thức LCNT', result_posted_at: 'Ngày đăng tải KQLCNT', decision_number: 'Số quyết định', decision_issued_at: 'Ngày ban hành quyết định', bidder_count: 'Số nhà thầu tham dự', location: 'Địa điểm'
        },
        medicines: {
            medicine_name: 'Tên thuốc', active_ingredient_or_herbal_component: 'Tên hoạt chất / dược liệu', strength: 'Nồng độ, hàm lượng', marketing_authorization_or_import_permit: 'GĐKLH hoặc GPNK', route_of_administration: 'Đường dùng', dosage_form: 'Dạng bào chế', shelf_life: 'Hạn dùng (Tuổi thọ)', manufacturer: 'Tên cơ sở sản xuất', production_country: 'Nước sản xuất', packaging: 'Quy cách đóng gói', unit: 'Đơn vị tính', quantity: 'Số lượng', winning_unit_price: 'Đơn giá trúng thầu', winning_bidder_id: 'Mã định danh NT trúng thầu', winning_bidder_name: 'Tên NT trúng thầu', medicine_group: 'Nhóm thuốc', bid_invitation_code: 'Mã TBMT', procuring_entity_id: 'Mã định danh CĐT', procuring_entity_name: 'Tên CĐT', selection_method: 'Hình thức LCNT', result_posted_at: 'Ngày đăng tải KQLCNT', decision_number: 'Số quyết định', decision_issued_at: 'Ngày ban hành quyết định', bidder_count: 'Số nhà thầu tham dự', location: 'Địa điểm'
        },
        traditional: {
            item_name: 'Tên dược liệu / vị thuốc cổ truyền', used_part: 'Bộ phận dùng', scientific_name: 'Tên khoa học', origin: 'Nguồn gốc', processing_method: 'Phương pháp chế biến', registration_or_import_permit_number: 'Số ĐKLH / Giấy phép NK', manufacturer: 'Tên cơ sở sản xuất', production_country: 'Nước sản xuất', packaging: 'Quy cách đóng gói', unit: 'Đơn vị tính', quantity: 'Số lượng', winning_unit_price: 'Đơn giá trúng thầu', winning_bidder_id: 'Mã định danh NT trúng thầu', winning_bidder_name: 'Tên NT trúng thầu', technical_group: 'Nhóm TCKT', bid_invitation_code: 'Mã TBMT', procuring_entity_id: 'Mã định danh CĐT', procuring_entity_name: 'Tên CĐT', selection_method: 'Hình thức LCNT', result_posted_at: 'Ngày đăng tải KQLCNT', decision_number: 'Số quyết định', decision_issued_at: 'Ngày ban hành quyết định', bidder_count: 'Số nhà thầu tham dự', location: 'Địa điểm'
        }
    };
    // The result tables use the same canonical field catalog as Advanced Search.
    // Expose it once so headers, filters, detail and export stay in sync.
    window.BIDFinderDataColumns = {
        order: FIELD_ORDER,
        labels: FIELD_LABELS
    };
    const FIELD_HINTS = {
        item_name: 'VD: Máy điện tim...', unit: 'VD: Bộ, chiếc...', quantity: 'VD: 100, 500...',
        country_of_origin: 'VD: Việt Nam...', hs_code: 'VD: 1001...', model_mark: 'VD: ABC-123...', brand: 'VD: XXX...',
        production_year: 'VD: 2026...', manufacturer: 'VD: Công ty ABC...', technical_specification: 'VD: Tính chất, kích thước...',
        model: 'VD: X111...', registration_or_import_permit_number: 'VD: VN-12345-67...', winning_unit_price: 'VD: 100000...',
        winning_bidder_id: 'VD: Mã nhà thầu...', winning_bidder_name: 'VD: Công ty XYZ...', bid_invitation_code: 'VD: IB2500123456...',
        procuring_entity_id: 'VD: Mã chủ đầu tư...', procuring_entity_name: 'VD: Sở Y tế...', selection_method: 'VD: Đấu thầu rộng rãi...',
        result_posted_at: 'VD: 01/01/2026...', decision_number: 'VD: 123/QĐ-SYT...', decision_issued_at: 'VD: 01/01/2026...',
        bidder_count: 'VD: 3...', location: 'VD: Hà Nội...', medicine_name: 'VD: Paracetamol...',
        active_ingredient_or_herbal_component: 'VD: Paracetamol...', strength: 'VD: 500mg, 5mg/ml...',
        marketing_authorization_or_import_permit: 'VD: VN-12345-67...', route_of_administration: 'VD: Uống, tiêm...',
        dosage_form: 'VD: Viên nén', shelf_life: 'VD: 24 tháng...', production_country: 'VD: Việt Nam, Ấn Độ...',
        packaging: 'VD: Hộp 10 vỉ x 10 viên...', medicine_group: 'VD: Nhóm 1...', used_part: 'VD: Rễ, lá, thân...',
        scientific_name: 'VD: Herba Lactucae indicae...', origin: 'VD: Việt Nam...', processing_method: 'VD: Thái lát, sấy...',
        technical_group: 'VD: Nhóm 1,...'
    };
    const GROUP_FIELD_HINTS = {
        medicines: {
            marketing_authorization_or_import_permit: 'VD: VN-18589-15...',
            unit: 'VD: Viên, hộp, chai...',
            packaging: 'VD: Hộp 5 ống 2ml, hộp 10 vỉ...'
        },
        traditional: {
            item_name: 'VD: Bạch linh, đan sâm...',
            registration_or_import_permit_number: 'VD: VCT-123456-78...',
            unit: 'VD: Kg, gram, gói...',
            packaging: 'VD: Gói 1-5kg, túi 500g...'
        }
    };
    const TENDER_FIELD_NAMES = new Set(['winning_unit_price', 'winning_bidder_id', 'winning_bidder_name', 'bid_invitation_code', 'procuring_entity_id', 'procuring_entity_name', 'selection_method', 'result_posted_at', 'decision_number', 'decision_issued_at', 'bidder_count', 'location']);
    const ADVANCED_FILTER_EXCLUDED_FIELDS = new Set(['quantity', 'winning_unit_price', 'winning_bidder_id', 'procuring_entity_id', 'bidder_count']);
    const GOODS_SHARED_SEARCH_FIELDS = new Set(['item_name', 'model_mark', 'brand', 'technical_specification']);
    const CROSS_GROUP_PRODUCT_SEARCH_FIELDS = [
        'item_name', 'model_mark', 'brand', 'technical_specification',
        'medicine_name', 'active_ingredient_or_herbal_component'
    ];
    const CROSS_GROUP_PRODUCT_TRIGGER_FIELDS = {
        medicines: new Set(['medicine_name', 'active_ingredient_or_herbal_component']),
        traditional: new Set(['item_name'])
    };
    // Existing FilterRequest aliases. Keeping these aliases reuses the legacy
    // token translator (including AND / OR / NOT) without changing the API.
    const LEGACY_TOKEN_FILTER_KEYS = {
        goods: {
            item_name: 'goodsKeyword', model_mark: 'goodsKeyword', brand: 'goodsKeyword', technical_specification: 'goodsKeyword', registration_or_import_permit_number: 'regNo',
            unit: 'unit', manufacturer: 'manufacturer', country_of_origin: 'country', winning_bidder_name: 'winner',
            procuring_entity_name: 'investor', decision_number: 'approvalDecision'
        },
        medicines: {
            medicine_name: 'crossGroupProductKeyword', active_ingredient_or_herbal_component: 'crossGroupProductKeyword', strength: 'concentration',
            route_of_administration: 'route', dosage_form: 'dosageForm', packaging: 'specification',
            marketing_authorization_or_import_permit: 'regNo', unit: 'unit', manufacturer: 'manufacturer',
            production_country: 'country', winning_bidder_name: 'winner', procuring_entity_name: 'investor',
            decision_number: 'approvalDecision'
        },
        traditional: {
            item_name: 'crossGroupProductKeyword', scientific_name: 'activeIngredient', processing_method: 'route', packaging: 'specification',
            registration_or_import_permit_number: 'regNo', unit: 'unit', manufacturer: 'manufacturer',
            production_country: 'country', winning_bidder_name: 'winner', procuring_entity_name: 'investor',
            decision_number: 'approvalDecision'
        }
    };
    function isCrossGroupProductField(group, fieldName) {
        return Boolean(CROSS_GROUP_PRODUCT_TRIGGER_FIELDS[group]?.has(fieldName));
    }
    const SELECTION_METHODS = ['Đấu thầu rộng rãi', 'Đấu thầu hạn chế', 'Chỉ định thầu', 'Chào hàng cạnh tranh', 'Mua sắm trực tiếp', 'Tự thực hiện', 'Tham gia thực hiện của cộng đồng', 'Đàm phán giá', 'Lựa chọn nhà thầu trong trường hợp đặc biệt', 'Đặt hàng', 'Chào giá trực tuyến', 'Chào giá trực tuyến theo quy trình rút gọn', 'Mua sắm trực tuyến'];
    const SELECTION_METHOD_LABELS = new Map([
        ['DTRR', 'Đấu thầu rộng rãi'], ['LCNT_DB', 'Đấu thầu rộng rãi'],
        ['DTHC', 'Đấu thầu hạn chế'], ['LCNT_HC', 'Đấu thầu hạn chế'],
        ['CDT', 'Chỉ định thầu'], ['CDTRG', 'Chào hàng cạnh tranh'],
        ['MSTT', 'Mua sắm trực tiếp'], ['TTH', 'Tự thực hiện']
    ]);
    const MEDICINE_GROUPS = [['BDG', 'Biệt dược gốc'], ['N1', 'Nhóm 1'], ['N2', 'Nhóm 2'], ['N3', 'Nhóm 3'], ['N4', 'Nhóm 4'], ['N5', 'Nhóm 5'], ['UNKNOWN', 'Chưa xác định được']];
    // Traditional TCKT values use the same cleaned group vocabulary as medicines.
    const TECHNICAL_GROUPS = MEDICINE_GROUPS;
    // Values copied from the legacy 3d131d0 filter. Prefixes are part of the API value.
    const LOCATIONS = [
        ['Tỉnh An Giang', 'An Giang'], ['Tỉnh Bà Rịa - Vũng Tàu', 'Bà Rịa - Vũng Tàu'], ['Tỉnh Bắc Giang', 'Bắc Giang'], ['Tỉnh Bắc Kạn', 'Bắc Kạn'], ['Tỉnh Bạc Liêu', 'Bạc Liêu'], ['Tỉnh Bắc Ninh', 'Bắc Ninh'], ['Tỉnh Bến Tre', 'Bến Tre'], ['Tỉnh Bình Định', 'Bình Định'], ['Tỉnh Bình Dương', 'Bình Dương'], ['Tỉnh Bình Phước', 'Bình Phước'], ['Tỉnh Bình Thuận', 'Bình Thuận'], ['Tỉnh Cà Mau', 'Cà Mau'], ['Thành phố Cần Thơ', 'Cần Thơ'], ['Tỉnh Cao Bằng', 'Cao Bằng'], ['Thành phố Đà Nẵng', 'Đà Nẵng'], ['Tỉnh Đăk Lăk', 'Đăk Lăk'], ['Tỉnh Đắk Nông', 'Đăk Nông'], ['Tỉnh Điện Biên', 'Điện Biên'], ['Tỉnh Đồng Nai', 'Đồng Nai'], ['Tỉnh Đồng Tháp', 'Đồng Tháp'], ['Tỉnh Gia Lai', 'Gia Lai'], ['Tỉnh Hà Giang', 'Hà Giang'], ['Tỉnh Hà Nam', 'Hà Nam'], ['Thành phố Hà Nội', 'Hà Nội'], ['Tỉnh Hà Tĩnh', 'Hà Tĩnh'], ['Tỉnh Hải Dương', 'Hải Dương'], ['Thành phố Hải Phòng', 'Hải Phòng'], ['Tỉnh Hậu Giang', 'Hậu Giang'], ['Thành phố Hồ Chí Minh', 'Hồ Chí Minh'], ['Tỉnh Hòa Bình', 'Hòa Bình'], ['Tỉnh Hưng Yên', 'Hưng Yên'], ['Tỉnh Khánh Hòa', 'Khánh Hòa'], ['Tỉnh Kiên Giang', 'Kiên Giang'], ['Tỉnh Kon Tum', 'Kon Tum'], ['Tỉnh Lai Châu', 'Lai Châu'], ['Tỉnh Lâm Đồng', 'Lâm Đồng'], ['Tỉnh Lạng Sơn', 'Lạng Sơn'], ['Tỉnh Lào Cai', 'Lào Cai'], ['Tỉnh Long An', 'Long An'], ['Tỉnh Nam Định', 'Nam Định'], ['Tỉnh Nghệ An', 'Nghệ An'], ['Tỉnh Ninh Bình', 'Ninh Bình'], ['Tỉnh Ninh Thuận', 'Ninh Thuận'], ['Tỉnh Phú Thọ', 'Phú Thọ'], ['Tỉnh Phú Yên', 'Phú Yên'], ['Tỉnh Quảng Bình', 'Quảng Bình'], ['Tỉnh Quảng Nam', 'Quảng Nam'], ['Tỉnh Quảng Ngãi', 'Quảng Ngãi'], ['Tỉnh Quảng Ninh', 'Quảng Ninh'], ['Tỉnh Quảng Trị', 'Quảng Trị'], ['Tỉnh Sóc Trăng', 'Sóc Trăng'], ['Tỉnh Sơn La', 'Sơn La'], ['Tỉnh Tây Ninh', 'Tây Ninh'], ['Tỉnh Thái Bình', 'Thái Bình'], ['Tỉnh Thái Nguyên', 'Thái Nguyên'], ['Tỉnh Thanh Hóa', 'Thanh Hóa'], ['Tỉnh Thừa Thiên Huế', 'Thừa Thiên Huế'], ['Tỉnh Tiền Giang', 'Tiền Giang'], ['Tỉnh Trà Vinh', 'Trà Vinh'], ['Tỉnh Tuyên Quang', 'Tuyên Quang'], ['Tỉnh Vĩnh Long', 'Vĩnh Long'], ['Tỉnh Vĩnh Phúc', 'Vĩnh Phúc'], ['Tỉnh Yên Bái', 'Yên Bái']
    ];

    function apiBaseUrl() {
        if (window.API_BASE_URL) return window.API_BASE_URL;
        const local = window.location.protocol === 'file:' || ['localhost', '127.0.0.1'].includes(window.location.hostname);
        return local ? 'http://127.0.0.1:8001' : 'https://bidfinder-api-staging-774667987564.asia-southeast1.run.app';
    }
    function contractPromise() {
        if (!window.BIDFinderSearchContractPromise) {
            const fetcher = window.bidfinderAuthorizedFetch || fetch;
            window.BIDFinderSearchContractPromise = fetcher(`${apiBaseUrl()}/api/search-contract`)
                .then(response => response.json().then(payload => {
                    if (!response.ok || !payload?.contract?.groups) throw new Error(payload?.message || `HTTP ${response.status}`);
                    return payload.contract;
                })).catch(error => { window.BIDFinderSearchContractPromise = null; throw error; });
        }
        return window.BIDFinderSearchContractPromise;
    }
    function html(value) {
        return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    const ICON_PATHS = {
        package: '<path d="m16.5 9.4-9-5.19M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="M3.27 6.96 12 12.01l8.73-5.05M12 22.08V12"/>',
        pill: '<path d="m10.5 20.5 9.5-9.5a4.95 4.95 0 0 0-7-7l-9.5 9.5a4.95 4.95 0 0 0 7 7Z"/><path d="m8.5 8.5 7 7"/>',
        leaf: '<path d="M20.9 3.1C12.8 3.3 6.4 6.2 4 11.2c-1.5 3.1-.5 6.7 2.4 8.1 3.1 1.5 6.7-.1 8.1-3.2 1.2-2.7.7-5.7-.9-7.7"/><path d="M3 21c2.4-3.8 5.6-6.2 10-8"/>',
        product: '<path d="M6 2h12v20H6z"/><path d="M9 6h6M9 10h6M9 14h3"/>',
        tender: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18M10 12v2h4v-2"/>'
    };
    function icon(name) { return `<svg class="search-form-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICON_PATHS[name] || ''}</svg>`; }
    function splitValues(value) { return String(value || '').split(',').map(item => item.trim()).filter(Boolean); }
    function quoteSearchPhrase(value) {
        const normalized = String(value || '').trim().replace(/\s+/g, ' ');
        return `"${normalized.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
    }

    class TypesenseSearchForm extends HTMLElement {
        constructor() {
            super();
            const shadow = this.attachShadow({ mode: 'open' });
            const style = document.createElement('style');
            style.textContent = this.styles();
            const contentRoot = document.createElement('div');
            contentRoot.className = 'search-form-root';
            shadow.append(style, contentRoot);
            this._contentRoot = contentRoot;
            this._autocompleteTimer = null;
            this._autocompleteAbortController = null;
            this._autocompleteRequestSeq = 0;
            this._autocompleteCache = new Map();
            this._autocompleteIndex = -1;
            this._previewState = { idle: true };
            this._handleDropdownRootClick = event => {
                const path = typeof event.composedPath === 'function' ? event.composedPath() : [];
                const insideDropdown = path.some(node => node?.classList?.contains?.('filter-dropdown'));
                const insideAutocomplete = path.some(node => node?.classList?.contains?.('autocomplete-dropdown'));
                const insideTokenEditor = path.some(node => node?.classList?.contains?.('token-input-container') || node?.id === 'criterion-keyword');
                if (!insideDropdown) this.closeDropdowns();
                if (!insideAutocomplete && !insideTokenEditor) this.closeAutocompleteDropdown();
            };
            if (typeof contentRoot.addEventListener === 'function') contentRoot.addEventListener('click', this._handleDropdownRootClick);
            this._handleOutsideDropdownClick = event => {
                const path = typeof event.composedPath === 'function' ? event.composedPath() : [];
                if (!path.includes(this)) {
                    this.closeDropdowns();
                    this.closeAutocompleteDropdown();
                }
            };
        }
        connectedCallback() {
            if (typeof document.addEventListener === 'function' && !this._outsideDropdownBound) {
                document.addEventListener('click', this._handleOutsideDropdownClick);
                this._outsideDropdownBound = true;
            }
            if (this._initialized) return;
            this._initialized = true;
            this.state = { group: 'medicines', sourceTypes: [], criteria: {}, activeField: '', page: 1, limit: 50, loading: false, contract: null, pendingPayload: null };
            this.renderShell('Đang tải danh mục tìm kiếm…');
            contractPromise().then(contract => {
                this.state.contract = contract;
                if (this.state.pendingPayload) this.applyPayload(this.state.pendingPayload);
                this.ensureActiveField();
                this.render();
            }).catch(error => this.showError(error?.message || 'Không tải được danh mục tìm kiếm.'));
        }
        disconnectedCallback() {
            this.cancelAutocomplete();
            if (typeof document.removeEventListener === 'function' && this._outsideDropdownBound) {
                document.removeEventListener('click', this._handleOutsideDropdownClick);
                this._outsideDropdownBound = false;
            }
        }
        renderShell(message) { this._contentRoot.innerHTML = `<div class="ts-loading">${html(message)}</div>`; }
        styles() {
            return `
                :host {
                    --c-primary: var(--color-primary, #127495);
                    --c-primary-hover: var(--color-primary-dark, #0f5b77);
                    --c-primary-light: rgba(18, 116, 149, 0.10);
                    --c-accent: var(--color-accent, #1b866e);
                    --c-text: var(--color-text-primary, #111827);
                    --c-sub: var(--color-text-secondary, #56707f);
                    --c-muted: var(--color-text-muted, #7b919d);
                    --c-border: var(--color-border, #d3e2eb);
                    --c-border-strong: #b8d0dc;
                    --c-surface: var(--color-surface, #ffffff);
                    --c-surface-2: var(--color-surface-2, #f5fafc);
                    --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.05);
                    --shadow-md: 0 10px 24px rgba(16, 34, 48, 0.08);
                    --shadow-lg: 0 18px 36px rgba(16, 34, 48, 0.12);
                    --radius-sm: 8px;
                    --control-h: 44px;
                    --field-pad-x: 14px;
                    display: block;
                    height: auto;
                    min-height: 0;
                    color: var(--c-text);
                    font: 14px/1.45 Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                }

                *, *::before, *::after { box-sizing: border-box; }
                button, input, select { font: inherit; }
                button { appearance: none; }
                .ts-loading, .ts-error { padding: 18px; border: 1px solid var(--c-border); border-radius: var(--radius-sm); background: var(--c-surface-2); color: var(--c-sub); }
                .ts-error { color: #a63d3d; background: #fff7f7; border-color: #f0caca; }

                .search-form { display: flex; flex-direction: column; min-height: 0; overflow: hidden; color: var(--c-text); }

                .active-filters-topbar {
                    display: flex;
                    align-items: flex-start;
                    gap: 12px;
                    flex: 0 0 auto;
                    min-height: 72px;
                    height: clamp(72px, 8vh, 84px);
                    max-height: 84px;
                    margin-bottom: 5px;
                    padding: 6px 10px;
                    overflow: hidden;
                    background: var(--c-surface);
                    border: 1px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    box-shadow: var(--shadow-sm);
                }
                .active-filters-title { flex-shrink: 0; padding-top: 0; color: var(--c-sub); font-size: 13px; font-weight: 700; line-height: 1.35; white-space: nowrap; }
                .active-filters-list { display: block; flex: 1; min-width: 0; max-height: 68px; padding: 0 4px 4px 0; overflow-y: auto; text-align: left; }
                .active-filters-topbar.empty { align-items: baseline; }
                .active-filters-topbar.empty .active-filters-list { display: contents; }
                .active-filters-list::-webkit-scrollbar { width: 6px; }
                .active-filters-list::-webkit-scrollbar-thumb { background: #d5dbe7; border-radius: var(--radius-sm); }
                .filter-chip {
                    display: inline-flex;
                    align-items: flex-start;
                    gap: 6px;
                    max-width: 100%;
                    margin: 0 6px 4px 0;
                    padding: 5px 8px 5px 10px;
                    border: 1px solid rgba(18, 116, 149, 0.20);
                    border-radius: var(--radius-sm);
                    background: var(--c-primary-light);
                    color: var(--c-primary-hover);
                    font-size: 12.5px;
                    line-height: 1.35;
                    white-space: normal;
                    word-break: break-word;
                }
                .filter-chip strong { flex-shrink: 0; color: var(--c-primary-hover); font-weight: 700; }
                .filter-chip .chip-select, .filter-chip .chip-remove { padding: 0; border: 0; background: transparent; color: inherit; cursor: pointer; }
                .filter-chip .chip-select { text-align: left; }
                .filter-chip .chip-remove { margin-left: 4px; padding-left: 6px; border-left: 1px solid rgba(18, 116, 149, 0.20); opacity: 0.58; font-size: 14px; line-height: 1; }
                .filter-chip .chip-remove:hover { opacity: 1; color: var(--c-accent); }
                .empty-filters { display: block; padding-top: 0; color: var(--c-muted); font-size: 12px; line-height: 1.35; }

                .filter-layout {
                    display: grid;
                    grid-template-columns: clamp(130px, 9vw, 150px) minmax(400px, 460px) clamp(430px, 32vw, 520px);
                    justify-content: start;
                    flex: 1 1 auto;
                    align-items: stretch;
                    gap: 5px;
                    min-height: 320px;
                    height: min(500px, calc(100dvh - 250px));
                    padding: 4px;
                    overflow: hidden;
                    background: var(--c-surface);
                    border: 1px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    box-shadow: var(--shadow-md);
                }
                .filter-sidebar {
                    display: contents;
                }
                .sidebar-column { display: flex; min-width: 0; min-height: 0; flex-direction: column; gap: 2px; overflow-y: auto; }
                .sidebar-column + .sidebar-column { padding-left: 0; border-left: 0; }
                .sidebar-column::-webkit-scrollbar { width: 6px; }
                .sidebar-column::-webkit-scrollbar-thumb { background: #d5dbe7; border-radius: var(--radius-sm); }
                .sidebar-group { display: flex; align-items: center; gap: 7px; margin: 0 0 2px; padding: 5px 8px; background: #e7f1f6; border: 1px solid #dce8ef; border-radius: var(--radius-sm); color: #537080; font-size: 12px; font-weight: 800; letter-spacing: 0.08em; line-height: 1.2; text-transform: uppercase; }
                .group-choice, .sidebar-item {
                    position: relative;
                    display: flex;
                    width: 100%;
                    min-height: 34px;
                    flex-direction: column;
                    align-items: flex-start;
                    justify-content: center;
                    gap: 2px;
                    margin: 0;
                    padding: 4px 6px 4px 5px;
                    border: 0;
                    border-left: 3px solid transparent;
                    border-radius: var(--radius-sm);
                    background: transparent;
                    color: #374151;
                    cursor: pointer;
                    text-align: left;
                    transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
                }
                .group-choice { flex-direction: row; align-items: center; gap: 7px; }
                .search-form-icon { width: 16px; height: 16px; flex: 0 0 16px; fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.8; }
                .group-choice-label { min-width: 0; }
                .group-choice:hover, .group-choice:focus-visible, .sidebar-item:hover, .sidebar-item:focus-visible { outline: 0; background: rgba(148, 163, 184, 0.10); color: #111827; }
                .group-choice.active, .sidebar-item.active { border-left: 4px solid var(--c-primary-hover); background: var(--c-primary); color: #fff; font-weight: 800; }
                .category-panel .group-choice.active { border-left-color: #6e604d; background: #8a795e; color: #fff; }
                .group-choice.active:focus-visible, .sidebar-item.active:focus-visible { outline: 2px solid rgba(18, 116, 149, 0.28); outline-offset: 1px; }
                .sidebar-item-main { font-size: 12.5px; font-weight: 650; line-height: 1.2; }
                .sidebar-item-hint { color: var(--c-muted); font-size: 11px; font-weight: 400; line-height: 1.2; }
                .sidebar-item.active .sidebar-item-hint { color: rgba(255, 255, 255, 0.78); }
                .sidebar-item.has-value::after { content: ''; position: absolute; top: 10px; right: 10px; width: 7px; height: 7px; border-radius: 50%; background: var(--c-primary); box-shadow: 0 0 0 3px rgba(18, 116, 149, 0.14); }
                .sidebar-item.active.has-value::after { background: rgba(255, 255, 255, 0.96); box-shadow: none; }

                .filter-content { display: flex; grid-column: 3; min-width: 0; min-height: 0; flex: 1; flex-direction: column; overflow: auto; padding: 12px 20px 18px 14px; background: var(--c-surface); }
                .filter-pane { display: none; animation: fadeIn 0.22s ease; }
                .filter-pane.active { display: flex; min-height: 100%; flex-direction: column; }
                .filter-pane h3 { margin: 0 0 6px; color: var(--c-text); font-size: 20px; font-weight: 750; letter-spacing: -0.3px; }
                .pane-desc { margin: 0 0 14px; color: var(--c-sub); font-size: 14px; line-height: 1.55; }
                .fields-row, .range-row { display: flex; gap: 20px; }
                .fields-row .field, .range-row > div { min-width: 0; flex: 1; }
                .sidebar-panel-title { margin: 0 0 5px; padding: 7px 6px; border-bottom: 2px solid #c7dce6; color: #345a6c; font-size: 13px; font-weight: 800; letter-spacing: 0.04em; line-height: 1.25; }
                .category-panel { grid-column: 1; padding: 3px; background: #eaf5ed; border: 1px solid #cfe4d5; border-radius: var(--radius-sm); }
                .category-panel .sidebar-panel-title { border-bottom-color: #c5ddcc; color: #356044; }
                .category-panel .group-choice { min-height: 36px; justify-content: flex-start; padding: 5px 5px 5px 4px; color: #2f6845; font-size: 13px; font-weight: 700; text-align: left; }
                .category-panel .group-choice:hover, .category-panel .group-choice:focus-visible { background: rgba(27, 134, 110, 0.10); color: #205c3b; }
                .category-panel .group-choice.active { border-left-color: #176b48; background: #2f865b; color: #fff; }
                .condition-panel { grid-column: 2; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-content: start; gap: 0 6px; padding: 4px; overflow: hidden; background: #eef7fb; border: 1px solid #cfe2eb; border-radius: var(--radius-sm); }
                .condition-panel .sidebar-panel-title { grid-column: 1 / -1; }
                .condition-section { display: flex; min-width: 0; min-height: 0; flex-direction: column; overflow-y: auto; }
                .condition-section + .condition-section { margin: 0; padding: 0 0 0 6px; border-top: 0; border-left: 1px solid #cfe2eb; }
                .condition-section .sidebar-group { margin-bottom: 3px; }
                .field { display: flex; min-width: 0; flex-direction: column; margin-bottom: 0; }
                .field label { display: block; margin-bottom: 6px; color: var(--c-sub); font-size: 13px; font-weight: 700; }
                .field input, .field select {
                    width: 100%;
                    min-height: var(--control-h);
                    padding: 10px var(--field-pad-x);
                    border: 2px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    background: var(--c-surface);
                    color: var(--c-text);
                    font-family: inherit;
                    font-size: 14px;
                    line-height: 1.4;
                    transition: border-color 0.18s ease, background 0.18s ease;
                }
                .field select[multiple] { height: auto; min-height: 170px; padding: 7px 10px; }
                .field select[multiple] option { padding: 5px 7px; }
                .field select[multiple] option:checked { background: var(--c-primary); color: #fff; }
                .field input:hover, .field select:hover { border-color: var(--c-border-strong); }
                .field input:focus, .field select:focus { outline: none; border-color: var(--c-primary-hover); box-shadow: 0 0 0 3px rgba(18, 116, 149, 0.10); }
                .field input::placeholder { color: var(--c-muted); opacity: 1; }
                .filter-dropdown { position: relative; width: 100%; }
                .filter-dropdown-trigger {
                    display: flex;
                    width: 100%;
                    min-height: var(--control-h);
                    align-items: center;
                    justify-content: space-between;
                    gap: 10px;
                    padding: 10px var(--field-pad-x);
                    border: 2px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    background: var(--c-surface);
                    color: var(--c-text);
                    cursor: pointer;
                    font: inherit;
                    text-align: left;
                }
                .filter-dropdown-trigger:hover, .filter-dropdown-trigger[aria-expanded="true"] { border-color: var(--c-primary-hover); }
                .filter-dropdown-trigger:focus-visible { outline: 2px solid rgba(18, 116, 149, 0.28); outline-offset: 2px; }
                .filter-dropdown-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .filter-dropdown-chevron { flex: 0 0 auto; color: var(--c-muted); font-size: 12px; }
                .filter-dropdown-menu {
                    position: absolute;
                    z-index: 20;
                    top: calc(100% + 5px);
                    right: 0;
                    left: 0;
                    max-height: 260px;
                    overflow-y: auto;
                    padding: 5px;
                    border: 1px solid var(--c-border-strong);
                    border-radius: var(--radius-sm);
                    background: var(--c-surface);
                    box-shadow: 0 12px 28px rgba(15, 48, 63, 0.16);
                }
                .filter-dropdown-menu[hidden] { display: none; }
                .filter-dropdown-option { display: flex; min-height: 32px; align-items: center; gap: 8px; padding: 5px 7px; border-radius: 4px; color: var(--c-text); cursor: pointer; font-size: 13px; line-height: 1.35; }
                .filter-dropdown-option:hover { background: var(--c-surface-2); }
                .filter-dropdown-option input { width: 16px; min-height: 16px; flex: 0 0 16px; accent-color: var(--c-primary); }
                .date-range-control { display: flex; gap: 12px; }
                .date-range-field { position: relative; min-width: 0; flex: 1; }
                .date-range-field label { display: block; margin-bottom: 6px; color: var(--c-sub); font-size: 12px; font-weight: 700; }
                .date-range-field input[data-date-text] { cursor: text; }
                .date-picker-proxy { position: absolute; right: 0; bottom: 0; width: 42px !important; height: 40px; min-height: 40px !important; padding: 0 !important; border: 0 !important; opacity: 0; cursor: pointer; }
                .date-range-field::after { content: '▣'; position: absolute; right: 12px; bottom: 12px; color: var(--c-muted); font-size: 13px; pointer-events: none; }
                .token-input-container {
                    display: flex;
                    width: 100%;
                    position: relative;
                    min-height: var(--control-h);
                    flex-wrap: wrap;
                    align-items: center;
                    gap: 8px;
                    padding: 7px 12px;
                    border: 2px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    background: var(--c-surface);
                }
                .token-input-container:focus-within { border-color: var(--c-primary-hover); box-shadow: 0 0 0 3px rgba(18, 116, 149, 0.10); }
                .field .token-input-container input {
                    width: auto;
                    min-width: 180px;
                    min-height: 28px;
                    height: 28px;
                    flex: 1 1 180px;
                    padding: 0;
                    border: 0;
                    border-radius: 0;
                    box-shadow: none;
                }
                .token-tag, .token-operator { display: inline-flex; height: 28px; flex: 0 0 auto; align-items: center; border-radius: var(--radius-sm); }
                .token-tag { max-width: 100%; padding: 2px 8px; border: 1px solid var(--c-border); background: var(--c-surface-2); color: var(--c-text); font-size: 13px; }
                .token-operator { padding: 2px 8px; border: 0; background: var(--c-primary); color: #fff; font-size: 11px; font-weight: 800; cursor: pointer; }
                .token-operator:hover, .token-operator:focus-visible { outline: 0; background: var(--c-primary-hover); }
                .tag-text { min-width: 0; padding: 0; overflow: hidden; border: 0; background: transparent; color: inherit; cursor: text; font: inherit; text-overflow: ellipsis; white-space: nowrap; }
                .token-remove { margin-left: 6px; padding: 0 0 0 6px; border: 0; border-left: 1px solid var(--c-border); background: transparent; color: var(--c-muted); cursor: pointer; font-weight: 700; }
                .token-remove:hover, .token-remove:focus-visible { color: #a63d3d; }
                .autocomplete-dropdown {
                    position: absolute;
                    z-index: 20;
                    top: calc(100% + 6px);
                    left: 0;
                    width: 100%;
                    max-height: 260px;
                    margin: 0;
                    padding: 6px;
                    overflow-y: auto;
                    list-style: none;
                    border: 1px solid var(--c-border);
                    border-radius: var(--radius-sm);
                    background: var(--c-surface);
                    box-shadow: 0 12px 28px rgba(15, 48, 63, 0.16);
                }
                .autocomplete-dropdown.hidden { display: none; }
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
                    font-weight: 750;
                }
                .range-row { gap: 20px; }
                .pane-help { margin: 16px 0 0; padding: 0; border: 0; background: transparent; color: var(--c-sub); font-size: 14px; line-height: 1.55; }
                .pane-help p { margin: 0 0 7px; }
                .pane-help p:last-child { margin-bottom: 0; }
                .pane-help-link { padding: 0; border: 0; background: transparent; color: var(--c-primary-hover); font: inherit; text-decoration: underline; cursor: pointer; }
                .pane-help-link:hover, .pane-help-link:focus-visible { color: var(--c-accent); }
                .editor-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin-top: auto; padding-top: 16px; }
                .btn { display: inline-flex; align-items: center; justify-content: center; min-width: 120px; min-height: 40px; padding: 10px 16px; border-radius: var(--radius-sm); font-size: 13.5px; font-weight: 650; cursor: pointer; transition: all 0.18s ease; }
                .btn-primary { border: 0; background: var(--c-primary); color: #fff; box-shadow: 0 6px 16px rgba(10, 97, 123, 0.16); }
                .btn-primary:hover:not(:disabled) { background: var(--c-primary-hover); box-shadow: 0 10px 22px rgba(10, 97, 123, 0.18); }
                .btn-primary:disabled { border: 1px solid #cbd5dc; background: #e3e8ec; color: #8796a0; opacity: 1; cursor: not-allowed; box-shadow: none; }
                .btn-secondary { border: 1px solid var(--c-border); background: var(--c-surface); color: var(--c-text); }
                .btn-secondary:hover:not(:disabled) { background: var(--c-surface-2); border-color: var(--c-border-strong); }
                .btn:focus-visible { outline: 2px solid rgba(18, 116, 149, 0.28); outline-offset: 2px; }
                .btn:disabled { opacity: 0.5; cursor: not-allowed; box-shadow: none; }
                .preview-estimate { min-height: 24px; margin-top: 7px; color: var(--c-text); font-size: 13px; font-weight: 800; line-height: 24px; }
                .preview-estimate.loading { color: var(--c-primary); }
                .preview-estimate.zero-result { color: #b42318; }
                .preview-estimate.error { color: #a63d3d; }

                @keyframes fadeIn { from { opacity: 0; transform: translateY(2px); } to { opacity: 1; transform: translateY(0); } }
                @media (min-width: 981px) and (max-width: 1199px) {
                    .filter-layout { grid-template-columns: 130px minmax(400px, 450px) minmax(380px, 430px); }
                }
                @media (max-width: 980px) {
                    .active-filters-topbar { min-height: 72px; height: 72px; flex-direction: column; gap: 3px; }
                    .active-filters-topbar.empty { flex-direction: row; }
                    .active-filters-list { width: 100%; max-height: 68px; }
                    .filter-layout { display: flex; height: auto; max-height: calc(100dvh - 220px); flex-direction: column; padding: 0; }
                    .filter-sidebar { display: contents; }
                    .category-panel, .condition-panel, .filter-content { width: 100%; min-width: 0; max-width: none; grid-column: auto; }
                    .category-panel { max-height: 160px; }
                    .condition-panel { max-height: 285px; }
                    .filter-content { min-height: 250px; padding: 12px 16px 16px 14px; }
                    .editor-actions .btn { flex: 1; }
                }
                @media (max-width: 520px) {
                    .condition-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                    .category-panel + .condition-panel { padding-left: 5px; border-top: 0; border-left: 0; padding-top: 5px; }
                    .range-row { flex-direction: column; gap: 0; }
                }
            `;
        }
        groupContract() { return this.state.contract?.groups?.[this.state.group] || null; }
        fields() {
            const byName = new Map((this.groupContract()?.fields || []).map(field => [field.name, field]));
            return (FIELD_ORDER[this.state.group] || []).map(name => byName.get(name)).filter(Boolean);
        }
        fieldLabel(name) { return FIELD_LABELS[this.state.group]?.[name] || name; }
        fieldHint(name) { return GROUP_FIELD_HINTS[this.state.group]?.[name] || FIELD_HINTS[name] || 'VD: chọn hoặc nhập giá trị'; }
        fieldMeta(name) { return this.fields().find(field => field.name === name) || null; }
        ensureActiveField() { if (!this.fieldMeta(this.state.activeField)) this.state.activeField = this.fields()[0]?.name || ''; }
        renderFieldButton(field) {
            return `<button type="button" class="sidebar-item ${field.name === this.state.activeField ? 'active' : ''} ${this.state.criteria[field.name] ? 'has-value' : ''}" data-field="${field.name}" aria-current="${field.name === this.state.activeField}"><span class="sidebar-item-main">${html(this.fieldLabel(field.name))}</span><span class="sidebar-item-hint">${html(this.fieldHint(field.name))}</span></button>`;
        }
        renderVariableSections() {
            const fields = this.fields().filter(field => !ADVANCED_FILTER_EXCLUDED_FIELDS.has(field.name));
            const productFields = fields.filter(field => !TENDER_FIELD_NAMES.has(field.name));
            const tenderFields = fields.filter(field => TENDER_FIELD_NAMES.has(field.name));
            return [
                ['product-fields', 'Tính chất sản phẩm', 'product', productFields],
                ['tender-fields', 'Thông tin thầu', 'tender', tenderFields]
            ].map(([className, title, iconName, sectionFields]) => `<section class="condition-section ${className}"><div class="sidebar-group">${icon(iconName)}<span>${title}</span></div>${sectionFields.map(field => this.renderFieldButton(field)).join('')}</section>`).join('');
        }
        renderEditorHelp() {
            return `<div class="pane-help"><p>1. Gõ từ khóa</p><p>2. Nhấn Enter để tạo một thẻ từ khóa</p><p>3. Nếu có nhiều điều kiện, lặp lại bước 1 và 2</p><p>4. Điều chỉnh bằng cách click OR AND NOT để tạo điều kiện</p><p>5. Lưu ý vùng <strong>"Điều kiện tìm kiếm"</strong> ở trên cùng để quản lý điều kiện tìm kiếm</p><p><span class="pane-help-prefix">Xem </span><button class="pane-help-link" type="button" data-open-filter-help>Mẹo tìm kiếm</button></p></div>`;
        }
        render() {
            if (!this.state.contract) return;
            this.ensureActiveField();
            this.cancelAutocomplete();
            const groupButtons = Object.keys(GROUP_LABELS).map(key => `<button type="button" class="sidebar-item group-choice ${key === this.state.group ? 'active' : ''}" data-group="${key}" aria-pressed="${key === this.state.group}">${icon(key === 'goods' ? 'package' : key === 'medicines' ? 'pill' : 'leaf')}<span class="group-choice-label">${GROUP_LABELS[key]}</span></button>`).join('');
            this._contentRoot.innerHTML = `<section class="search-form" aria-label="Tìm kiếm nâng cao">${this.renderSummary()}<div class="filter-layout"><aside class="filter-sidebar"><div class="sidebar-column category-panel" aria-label="Danh mục"><div class="sidebar-panel-title">Danh mục</div>${groupButtons}</div><div class="sidebar-column condition-panel" aria-label="Điều kiện"><div class="sidebar-panel-title">Điều kiện</div>${this.renderVariableSections()}</div></aside><div class="filter-content">${this.renderEditor()}</div></div></section>`;
            this.setPreviewResult(this._previewState);
            this.bindEvents();
        }
        renderSummary() {
            const chips = this.renderSummaryChips();
            return `<div class="active-filters-topbar${chips ? '' : ' empty'}"><div class="active-filters-title">Điều kiện tìm kiếm:</div><div class="active-filters-list">${chips || '<span class="empty-filters">Chưa có điều kiện tìm kiếm nào</span>'}</div></div>`;
        }
        renderSummaryChips() {
            return Object.entries(this.state.criteria).map(([name, criterion]) => {
                const display = criterion.kind === 'date-range'
                    ? [criterion.from ? `Từ ${this.formatVietnameseDate(criterion.from)}` : '', criterion.to ? `Đến ${this.formatVietnameseDate(criterion.to)}` : ''].filter(Boolean).join(' · ')
                    : criterion.kind === 'range'
                    ? [criterion.min !== '' ? `Từ ${criterion.min}` : '', criterion.max !== '' ? `Đến ${criterion.max}` : ''].filter(Boolean).join(' · ')
                    : criterion.kind === 'tokens'
                        ? this.criterionTokens(criterion).map((token, index) => `${index ? `(${token.op}) ` : ''}${this.optionLabel(name, token.value)}`).join(' ')
                        : (criterion.values || []).map(value => this.optionLabel(name, value)).join(', ');
                return `<span class="filter-chip"><button type="button" class="chip-select" data-chip-field="${name}"><strong>${html(this.fieldLabel(name))}:</strong> ${html(display)}</button><button type="button" class="chip-remove" data-remove-field="${name}" aria-label="Bỏ điều kiện ${html(this.fieldLabel(name))}">×</button></span>`;
            }).join('');
        }
        isDateField(name) { return name === 'result_posted_at' || name === 'decision_issued_at'; }
        dropdownOptions(name) {
            if (name === 'medicine_group' || name === 'technical_group') return name === 'technical_group' ? TECHNICAL_GROUPS : MEDICINE_GROUPS;
            if (name === 'selection_method') return SELECTION_METHODS.map(value => [value, value]);
            if (name === 'location') return LOCATIONS;
            return [];
        }
        optionLabel(name, value) {
            if (name === 'selection_method') return SELECTION_METHOD_LABELS.get(String(value || '').trim().toUpperCase()) || value;
            return this.dropdownOptions(name).find(([key]) => key === value)?.[1] || value;
        }
        dropdownDisplayLabel(name, values) {
            const labels = values.map(value => this.optionLabel(name, value));
            if (!labels.length) return 'Chọn giá trị';
            if (labels.length === 1) return labels[0];
            return `${labels.length} giá trị đã chọn`;
        }
        renderDropdownControl(name, criterion) {
            const selectedValues = (criterion?.values || []).map(value => name === 'selection_method' ? this.optionLabel(name, value) : value);
            const selected = new Set(selectedValues);
            const options = this.dropdownOptions(name);
            return `<div class="filter-dropdown" data-dropdown-field="${name}"><button type="button" class="filter-dropdown-trigger" data-dropdown-toggle="${name}" aria-expanded="false"><span class="filter-dropdown-label" data-dropdown-label="${name}">${html(this.dropdownDisplayLabel(name, [...selected]))}</span><span class="filter-dropdown-chevron" aria-hidden="true">⌄</span></button><div class="filter-dropdown-menu" data-dropdown-menu="${name}" hidden>${options.map(([value, label]) => `<label class="filter-dropdown-option"><input type="checkbox" data-dropdown-option="${name}" value="${html(value)}" ${selected.has(value) ? 'checked' : ''}><span>${html(label)}</span></label>`).join('')}</div></div>`;
        }
        parseVietnameseDate(raw) {
            const value = String(raw || '').trim();
            if (!value) return '';
            if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
            const match = value.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
            if (!match) return null;
            const [, day, month, year] = match;
            const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
            if (date.getUTCFullYear() !== Number(year) || date.getUTCMonth() !== Number(month) - 1 || date.getUTCDate() !== Number(day)) return null;
            return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        }
        formatVietnameseDate(value) {
            const iso = this.parseVietnameseDate(value);
            if (!iso) return '';
            const [year, month, day] = iso.split('-');
            return `${day}/${month}/${year}`;
        }
        renderDateRangeControl(name, criterion) {
            const from = criterion?.kind === 'date-range' ? criterion.from : '';
            const to = criterion?.kind === 'date-range' ? criterion.to : '';
            return `<div class="date-range-control" data-date-range="${name}"><div class="date-range-field" data-open-date-picker="from"><label for="criterion-date-from">Từ ngày</label><input id="criterion-date-from" data-date-text="from" type="text" inputmode="numeric" autocomplete="off" placeholder="dd/mm/yyyy" value="${html(this.formatVietnameseDate(from))}"><input class="date-picker-proxy" data-date-picker="from" type="date" tabindex="-1" aria-hidden="true" value="${html(from || '')}"></div><div class="date-range-field" data-open-date-picker="to"><label for="criterion-date-to">Đến ngày</label><input id="criterion-date-to" data-date-text="to" type="text" inputmode="numeric" autocomplete="off" placeholder="dd/mm/yyyy" value="${html(this.formatVietnameseDate(to))}"><input class="date-picker-proxy" data-date-picker="to" type="date" tabindex="-1" aria-hidden="true" value="${html(to || '')}"></div></div>`;
        }
        refreshCriteriaUI() {
            const root = this.shadowRoot;
            const chips = this.renderSummaryChips();
            const topbar = root.querySelector('.active-filters-topbar');
            const list = root.querySelector('.active-filters-list');
            if (list) list.innerHTML = chips || '<span class="empty-filters">Chưa có điều kiện tìm kiếm nào</span>';
            topbar?.classList.toggle('empty', !chips);
            this.bindSummaryEvents();
            root.querySelector(`[data-field="${this.state.activeField}"]`)?.classList.toggle('has-value', Boolean(this.state.criteria[this.state.activeField]));
            this.syncEditorActions();
        }
        syncDropdownField(name) {
            const values = Array.from(this.shadowRoot.querySelectorAll('[data-dropdown-option]'))
                .filter(input => input.dataset.dropdownOption === name && input.checked)
                .map(input => input.value);
            if (values.length) this.state.criteria[name] = { kind: 'values', values }; else delete this.state.criteria[name];
            this.state.page = 1;
            this.updateDropdownLabel(name, values);
            this.refreshCriteriaUI();
            this.requestPreview();
        }
        updateDropdownLabel(name, values) {
            const label = this.shadowRoot.querySelector(`[data-dropdown-label="${name}"]`);
            if (label) label.textContent = this.dropdownDisplayLabel(name, values);
        }
        closeDropdowns() {
            const root = this.shadowRoot;
            root.querySelectorAll('[data-dropdown-menu]').forEach(menu => { menu.hidden = true; });
            root.querySelectorAll('[data-dropdown-toggle]').forEach(trigger => trigger.setAttribute('aria-expanded', 'false'));
        }
        toggleDropdown(name) {
            const root = this.shadowRoot;
            const menu = root.querySelector(`[data-dropdown-menu="${name}"]`);
            const trigger = root.querySelector(`[data-dropdown-toggle="${name}"]`);
            if (!menu || !trigger) return;
            const shouldOpen = menu.hidden;
            this.closeDropdowns();
            menu.hidden = !shouldOpen;
            trigger.setAttribute('aria-expanded', String(shouldOpen));
        }
        openDatePicker(field) {
            const picker = field.querySelector('[data-date-picker]');
            if (!picker) return;
            try {
                if (typeof picker.showPicker === 'function') picker.showPicker();
                else { picker.focus(); picker.click(); }
            } catch (_) { picker.focus(); }
        }
        commitDateRange() {
            const field = this.fieldMeta(this.state.activeField);
            if (!field || !this.isDateField(field.name)) return;
            const root = this.shadowRoot;
            const rawFrom = root.querySelector('[data-date-text="from"]')?.value || '';
            const rawTo = root.querySelector('[data-date-text="to"]')?.value || '';
            const from = this.parseVietnameseDate(rawFrom);
            const to = this.parseVietnameseDate(rawTo);
            if ((rawFrom && !from) || (rawTo && !to)) return this.showStatus('Vui lòng nhập ngày theo dạng dd/mm/yyyy.', true);
            if (from && to && from > to) return this.showStatus('Từ ngày không được lớn hơn đến ngày.', true);
            // Selecting the first date is only editing the range. Wait for the
            // second endpoint before sending a preview request; otherwise the
            // API receives an incomplete range and reports an estimation error.
            if (Boolean(from) !== Boolean(to)) return;
            if (!from && !to) delete this.state.criteria[field.name];
            else this.state.criteria[field.name] = { kind: 'date-range', from, to };
            this.state.page = 1;
            this.refreshCriteriaUI();
            this.requestPreview();
        }
        criterionTokens(criterion) {
            if (criterion?.kind === 'tokens') return (criterion.tokens || []).map((token, index) => ({ value: String(token.value || '').trim(), op: index ? (['OR', 'AND', 'NOT'].includes(token.op) ? token.op : 'OR') : 'OR' })).filter(token => token.value);
            return (criterion?.values || []).map(value => ({ value: String(value).trim(), op: 'OR' })).filter(token => token.value);
        }
        renderTokenEditor(criterion) {
            return `<div class="token-input-container" data-token-editor>${this.renderTokenEditorContents(criterion)}</div>`;
        }
        renderTokenEditorContents(criterion) {
            const tokens = this.criterionTokens(criterion);
            const tokenMarkup = tokens.map((token, index) => `${index ? `<button type="button" class="token-operator" data-token-operator="${index}" aria-label="Đổi toán tử ${token.op}">${token.op}</button>` : ''}<span class="token-tag"><button type="button" class="tag-text" data-token-edit="${index}" title="${html(token.value)}">${html(token.value.length > 30 ? `${token.value.slice(0, 30)}...` : token.value)}</button><button type="button" class="token-remove" data-token-remove="${index}" aria-label="Xóa từ khóa ${html(token.value)}">×</button></span>`).join('');
            const field = this.fieldMeta(this.state.activeField);
            const autocomplete = this.isAutocompleteField(field)
                ? '<ul class="autocomplete-dropdown hidden" data-autocomplete-dropdown role="listbox" aria-label="Gợi ý từ khóa"></ul>'
                : '';
            return `${tokenMarkup}<input id="criterion-keyword" type="text" placeholder="Gõ từ khóa và nhấn Enter" autocomplete="off" aria-label="Từ khóa tìm kiếm">${autocomplete}`;
        }
        syncEditorActions() {
            const hasCriteria = Object.keys(this.state.criteria || {}).length > 0;
            const resetButton = this.shadowRoot?.querySelector('[data-action="reset"]');
            const applyButton = this.shadowRoot?.querySelector('[data-action="apply"]');
            if (resetButton) resetButton.disabled = !hasCriteria;
            if (applyButton) applyButton.disabled = !hasCriteria || Boolean(this.state.loading);
        }
        renderEditor() {
            const field = this.fieldMeta(this.state.activeField);
            if (!field) return '<p>Nhóm này chưa có biến tìm kiếm.</p>';
            const criterion = this.state.criteria[field.name];
            const hasCriteria = Object.keys(this.state.criteria).length > 0;
            let control;
            if (this.isDateField(field.name)) {
                control = this.renderDateRangeControl(field.name, criterion);
            } else if (field.type === 'float' || field.type === 'int32') {
                control = `<div class="range-row"><div><label for="criterion-min">Từ</label><input id="criterion-min" type="number" step="any" value="${html(criterion?.min ?? '')}" placeholder="Giá trị nhỏ nhất"></div><div><label for="criterion-max">Đến</label><input id="criterion-max" type="number" step="any" value="${html(criterion?.max ?? '')}" placeholder="Giá trị lớn nhất"></div></div>`;
            } else if (this.dropdownOptions(field.name).length) {
                control = this.renderDropdownControl(field.name, criterion);
            } else {
                control = this.renderTokenEditor(criterion);
            }
            return `<div class="filter-pane active" data-editor-field="${field.name}"><h3>${html(this.fieldLabel(field.name))}</h3><div class="field">${control}</div><div class="preview-estimate" role="status" aria-live="polite"></div>${this.renderEditorHelp()}<div class="editor-actions"><button type="button" class="btn btn-secondary" data-action="reset" ${hasCriteria ? '' : 'disabled'}>Đặt lại</button><button type="button" class="btn btn-primary" data-action="apply" ${this.state.loading || !hasCriteria ? 'disabled' : ''}>${this.state.loading ? 'Đang tìm kiếm…' : 'Tìm kiếm nâng cao'}</button></div></div>`;
        }
        bindEvents() {
            const root = this.shadowRoot;
            root.querySelectorAll('[data-group]').forEach(button => button.addEventListener('click', () => {
                this.state.group = button.dataset.group; this.state.sourceTypes = []; this.state.criteria = {}; this.state.activeField = ''; this.state.page = 1; this._previewState = { idle: true }; this.render();
            }));
            root.querySelectorAll('[data-field]').forEach(button => button.addEventListener('click', () => { this.state.activeField = button.dataset.field; this.render(); this.focusActiveField(); }));
            root.querySelectorAll('[data-open-filter-help]').forEach(link => link.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); this.dispatchEvent(new CustomEvent('bidfinder:open-filter-help', { bubbles: true, composed: true })); }));
            root.querySelector('[data-action="reset"]')?.addEventListener('click', () => this.resetAllFilters());
            root.querySelector('[data-action="apply"]')?.addEventListener('click', () => this.submit());
            root.querySelectorAll('[data-dropdown-toggle]').forEach(button => button.addEventListener('click', event => { event.preventDefault(); this.toggleDropdown(button.dataset.dropdownToggle); }));
            root.querySelectorAll('[data-dropdown-option]').forEach(input => input.addEventListener('change', () => this.syncDropdownField(input.dataset.dropdownOption)));
            root.querySelectorAll('[data-open-date-picker]').forEach(field => field.addEventListener('click', () => this.openDatePicker(field)));
            root.querySelectorAll('[data-date-picker]').forEach(input => input.addEventListener('change', () => {
                const text = root.querySelector(`[data-date-text="${input.dataset.datePicker}"]`);
                if (text) text.value = this.formatVietnameseDate(input.value);
                this.commitDateRange();
            }));
            root.querySelectorAll('[data-date-text]').forEach(input => {
                input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); this.commitDateRange(); } });
                input.addEventListener('blur', () => this.commitDateRange());
            });
            root.querySelectorAll('#criterion-min,#criterion-max').forEach(input => input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); this.saveActiveCriterion(); } }));
            this.bindSummaryEvents();
            this.bindTokenEditorEvents();
        }
        bindSummaryEvents() {
            const root = this.shadowRoot;
            root.querySelectorAll('[data-chip-field]').forEach(button => button.addEventListener('click', () => { this.state.activeField = button.dataset.chipField; this.render(); this.focusActiveField(); }));
            root.querySelectorAll('[data-remove-field]').forEach(button => button.addEventListener('click', () => { delete this.state.criteria[button.dataset.removeField]; this.render(); this.requestPreview(); }));
        }
        isAutocompleteField(field) {
            return Boolean(field?.autocomplete);
        }
        autocompleteFilters(field) {
            const payload = this.collectFilterPayload();
            const filters = { ...(payload.filters || {}) };
            if (field?.name === 'selection_method') delete filters.selectionMethod;
            if (field?.name === 'location') delete filters.place;
            if (field?.name === 'medicine_group' || field?.name === 'technical_group') delete filters.drugGroup;
            const legacyFilterKey = LEGACY_TOKEN_FILTER_KEYS[this.state.group]?.[field?.name];
            if (legacyFilterKey) delete filters[legacyFilterKey];
            return filters;
        }
        autocompletePayload(field, keyword) {
            const crossGroup = isCrossGroupProductField(this.state.group, field.name);
            return {
                scope: crossGroup ? 'all' : GROUP_SCOPE[this.state.group],
                group: crossGroup ? null : this.state.group,
                sourceTypes: crossGroup ? [] : [...this.state.sourceTypes],
                searchFields: crossGroup
                    ? [...CROSS_GROUP_PRODUCT_SEARCH_FIELDS]
                    : (this.state.group === 'goods' && GOODS_SHARED_SEARCH_FIELDS.has(field.name)
                        ? [...GOODS_SHARED_SEARCH_FIELDS]
                        : [field.name]),
                field: field.name,
                keyword,
                filters: this.autocompleteFilters(field),
                excludeSelf: true,
                limit: 5
            };
        }
        closeAutocompleteDropdown(scope = this.shadowRoot) {
            const dropdown = scope?.querySelector?.('[data-autocomplete-dropdown]');
            if (!dropdown) return;
            dropdown.classList.add('hidden');
            dropdown.innerHTML = '';
            this._autocompleteIndex = -1;
        }
        cancelAutocomplete({ close = true } = {}) {
            clearTimeout(this._autocompleteTimer);
            this._autocompleteTimer = null;
            this._autocompleteRequestSeq += 1;
            if (this._autocompleteAbortController) {
                this._autocompleteAbortController.abort();
                this._autocompleteAbortController = null;
            }
            if (close) this.closeAutocompleteDropdown();
        }
        autocompleteItems(scope = this.shadowRoot) {
            const dropdown = scope?.querySelector?.('[data-autocomplete-dropdown]');
            return dropdown ? [...dropdown.querySelectorAll('[data-autocomplete-index]')] : [];
        }
        updateAutocompleteActiveItem(items) {
            items.forEach((item, index) => item.classList.toggle('active', index === this._autocompleteIndex));
            const active = items[this._autocompleteIndex];
            active?.scrollIntoView?.({ block: 'nearest' });
        }
        handleAutocompleteKey(event, scope) {
            const items = this.autocompleteItems(scope);
            if (!items.length) return false;
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                this._autocompleteIndex = (this._autocompleteIndex + 1) % items.length;
                this.updateAutocompleteActiveItem(items);
                return true;
            }
            if (event.key === 'ArrowUp') {
                event.preventDefault();
                this._autocompleteIndex = this._autocompleteIndex <= 0 ? items.length - 1 : this._autocompleteIndex - 1;
                this.updateAutocompleteActiveItem(items);
                return true;
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                this.closeAutocompleteDropdown(scope);
                return true;
            }
            return false;
        }
        renderAutocompleteSuggestions(values, currentQuery, scope = this.shadowRoot) {
            const dropdown = scope?.querySelector?.('[data-autocomplete-dropdown]');
            if (!dropdown) return;
            const uniqueValues = [...new Set((Array.isArray(values) ? values : []).map(value => String(value || '').trim()).filter(Boolean))];
            if (!uniqueValues.length) {
                this.closeAutocompleteDropdown(scope);
                return;
            }
            const safeQuery = String(currentQuery || '').trim();
            const queryPattern = safeQuery ? new RegExp(safeQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'ig') : null;
            dropdown.innerHTML = '';
            uniqueValues.forEach((value, index) => {
                const item = document.createElement('li');
                item.dataset.autocompleteIndex = String(index);
                item.dataset.autocompleteValue = value;
                item.setAttribute('role', 'option');
                const safeValue = html(value);
                const safeSearch = queryPattern ? html(safeQuery) : '';
                item.innerHTML = queryPattern ? safeValue.replace(new RegExp(safeSearch.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'ig'), match => `<strong>${match}</strong>`) : safeValue;
                item.addEventListener('mousedown', event => event.preventDefault());
                item.addEventListener('click', () => this.appendValueToken(value));
                dropdown.append(item);
            });
            dropdown.classList.remove('hidden');
            this._autocompleteIndex = -1;
        }
        onAutocompleteInput(input) {
            const field = this.fieldMeta(this.state.activeField);
            if (!this.isAutocompleteField(field)) return;
            const query = String(input.value || '').trim();
            this.cancelAutocomplete();
            this._autocompleteIndex = -1;
            if (!query) return;
            this.renderAutocompleteSuggestions([query], query, input.parentNode || this.shadowRoot);
            this._autocompleteTimer = setTimeout(() => this.fetchAutocomplete(query, field, input), 250);
        }
        async fetchAutocomplete(query, field, input) {
            const payload = this.autocompletePayload(field, query);
            const cacheKey = JSON.stringify(payload);
            const requestSeq = ++this._autocompleteRequestSeq;
            const scope = input.parentNode || this.shadowRoot;
            if (this._autocompleteCache.has(cacheKey)) {
                if (requestSeq === this._autocompleteRequestSeq && input.value.trim() === query) this.renderAutocompleteSuggestions(this._autocompleteCache.get(cacheKey), query, scope);
                return;
            }
            const auth = window.BIDFinderAuth;
            const authConfig = auth?.getConfig?.() || {};
            if (!auth?.isAuthenticated?.() && authConfig.allow_anonymous_autocomplete === false) {
                auth?.openAuthModal?.('login');
                this.closeAutocompleteDropdown(scope);
                return;
            }
            const controller = typeof AbortController === 'function' ? new AbortController() : null;
            this._autocompleteAbortController = controller;
            try {
                const fetcher = window.bidfinderAuthorizedFetch || fetch;
                const response = await fetcher(`${apiBaseUrl()}/api/autocomplete`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                    ...(controller ? { signal: controller.signal } : {})
                });
                const raw = await response.text();
                if (!response.ok) return;
                const result = raw ? JSON.parse(raw) : {};
                const suggestions = Array.isArray(result?.data) ? result.data : [];
                this._autocompleteCache.set(cacheKey, suggestions);
                if (requestSeq === this._autocompleteRequestSeq && input.value.trim() === query) this.renderAutocompleteSuggestions(suggestions, query, scope);
            } catch (error) {
                if (error?.name !== 'AbortError') this.closeAutocompleteDropdown(scope);
            } finally {
                if (requestSeq === this._autocompleteRequestSeq) this._autocompleteAbortController = null;
            }
        }
        bindTokenEditorEvents(scope = this.shadowRoot) {
            const keywordInput = scope.querySelector('#criterion-keyword');
            keywordInput?.addEventListener('keydown', event => {
                if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    const active = this.autocompleteItems(scope)[this._autocompleteIndex];
                    if (active?.dataset?.autocompleteValue) this.appendValueToken(active.dataset.autocompleteValue);
                    else this.appendValueToken(keywordInput.value);
                } else if (this.handleAutocompleteKey(event, scope)) {
                    return;
                }
                else if (event.key === 'Backspace' && !keywordInput.value) this.moveValueTokenToInputForEditing(this.criterionTokens(this.state.criteria[this.state.activeField]).length - 1);
            });
            if (this.isAutocompleteField(this.fieldMeta(this.state.activeField))) {
                keywordInput?.addEventListener('input', () => this.onAutocompleteInput(keywordInput));
                keywordInput?.addEventListener('focus', () => this.onAutocompleteInput(keywordInput));
            }
            scope.querySelectorAll('[data-token-operator]').forEach(button => button.addEventListener('click', () => this.cycleTokenOperator(Number(button.dataset.tokenOperator))));
            scope.querySelectorAll('[data-token-edit]').forEach(button => button.addEventListener('click', () => this.moveValueTokenToInputForEditing(Number(button.dataset.tokenEdit))));
            scope.querySelectorAll('[data-token-remove]').forEach(button => button.addEventListener('click', () => this.removeValueToken(Number(button.dataset.tokenRemove))));
        }
        refreshTokenCriterion(editValue = '') {
            this.cancelAutocomplete();
            const root = this.shadowRoot;
            const container = root.querySelector('[data-token-editor]');
            if (!container) { this.render(); return; }
            container.innerHTML = this.renderTokenEditorContents(this.state.criteria[this.state.activeField]);
            this.bindTokenEditorEvents(container);
            const input = container.querySelector('#criterion-keyword');
            if (input) { input.value = editValue; input.focus(); input.setSelectionRange?.(editValue.length, editValue.length); }

            const chips = this.renderSummaryChips();
            const topbar = root.querySelector('.active-filters-topbar');
            const list = root.querySelector('.active-filters-list');
            if (list) list.innerHTML = chips || '<span class="empty-filters">Chưa có điều kiện tìm kiếm nào</span>';
            topbar?.classList.toggle('empty', !chips);
            this.bindSummaryEvents();
            root.querySelector(`[data-field="${this.state.activeField}"]`)?.classList.toggle('has-value', Boolean(this.state.criteria[this.state.activeField]));
            this.syncEditorActions();
        }
        // State-based port of legacy AdvancedFilterManager's token behavior.
        appendValueToken(rawValue) {
            const value = String(rawValue || '').trim();
            if (!value || !this.state.activeField) return;
            const tokens = this.criterionTokens(this.state.criteria[this.state.activeField]);
            tokens.push({ value, op: tokens.length ? 'OR' : 'OR' });
            this.state.criteria[this.state.activeField] = { kind: 'tokens', tokens };
            this.state.page = 1; this.refreshTokenCriterion(); this.requestPreview();
        }
        cycleTokenOperator(index) {
            const tokens = this.criterionTokens(this.state.criteria[this.state.activeField]);
            if (index <= 0 || !tokens[index]) return;
            const operators = ['OR', 'AND', 'NOT'];
            tokens[index].op = operators[(operators.indexOf(tokens[index].op) + 1) % operators.length];
            this.state.criteria[this.state.activeField] = { kind: 'tokens', tokens };
            this.refreshTokenCriterion(); this.requestPreview();
        }
        removeValueToken(index) {
            const tokens = this.criterionTokens(this.state.criteria[this.state.activeField]);
            if (!tokens[index]) return;
            tokens.splice(index, 1);
            if (tokens[0]) tokens[0].op = 'OR';
            if (tokens.length) this.state.criteria[this.state.activeField] = { kind: 'tokens', tokens }; else delete this.state.criteria[this.state.activeField];
            this.state.page = 1; this.refreshTokenCriterion(); this.requestPreview();
        }
        moveValueTokenToInputForEditing(index) {
            const tokens = this.criterionTokens(this.state.criteria[this.state.activeField]);
            if (!tokens[index]) return;
            const [{ value }] = tokens.splice(index, 1);
            if (tokens[0]) tokens[0].op = 'OR';
            if (tokens.length) this.state.criteria[this.state.activeField] = { kind: 'tokens', tokens }; else delete this.state.criteria[this.state.activeField];
            this.refreshTokenCriterion(value);
            this.requestPreview();
        }
        saveActiveCriterion() {
            const field = this.fieldMeta(this.state.activeField);
            if (!field) return;
            if (this.isDateField(field.name)) return this.commitDateRange();
            if (field.type === 'float' || field.type === 'int32') {
                const min = this.shadowRoot.getElementById('criterion-min')?.value ?? '';
                const max = this.shadowRoot.getElementById('criterion-max')?.value ?? '';
                if (min !== '' && max !== '' && Number(min) > Number(max)) return this.showStatus('Giá trị tối thiểu không được lớn hơn giá trị tối đa.', true);
                if (min === '' && max === '') delete this.state.criteria[field.name]; else this.state.criteria[field.name] = { kind: 'range', min, max };
            } else {
                const input = this.shadowRoot.getElementById('criterion-value');
                const values = input?.multiple ? Array.from(input.selectedOptions).map(option => option.value).filter(Boolean) : splitValues(input?.value);
                if (values.length) this.state.criteria[field.name] = { kind: 'values', values }; else delete this.state.criteria[field.name];
            }
            this.state.page = 1; this.render(); this.requestPreview();
        }
        collectFilterPayload() {
            const filters = {}, structuredFilters = {}, ranges = {};
            const textFields = [], textValues = [];
            const crossGroupSearchFields = [];
            let crossGroupSearch = false;
            const addTextFields = name => {
                const crossGroup = isCrossGroupProductField(this.state.group, name);
                if (crossGroup) {
                    crossGroupSearch = true;
                    if (!crossGroupSearchFields.includes(name)) crossGroupSearchFields.push(name);
                }
                const names = crossGroup
                    ? [...CROSS_GROUP_PRODUCT_SEARCH_FIELDS]
                    : (this.state.group === 'goods' && GOODS_SHARED_SEARCH_FIELDS.has(name)
                        ? [...GOODS_SHARED_SEARCH_FIELDS]
                        : [name]);
                names.forEach(fieldName => { if (!textFields.includes(fieldName)) textFields.push(fieldName); });
            };
            for (const [name, criterion] of Object.entries(this.state.criteria)) {
                const field = this.fieldMeta(name);
                if (!field) continue;
                const values = criterion.kind === 'tokens' ? this.criterionTokens(criterion).map(token => token.value) : (criterion.values || []);
                if (isCrossGroupProductField(this.state.group, name)) {
                    crossGroupSearch = true;
                    if (!crossGroupSearchFields.includes(name)) crossGroupSearchFields.push(name);
                }
                const legacyFilterKey = LEGACY_TOKEN_FILTER_KEYS[this.state.group]?.[name];
                if (criterion.kind === 'date-range') continue;
                if (criterion.kind === 'range') ranges[name] = { ...(criterion.min !== '' ? { min: Number(criterion.min) } : {}), ...(criterion.max !== '' ? { max: Number(criterion.max) } : {}) };
                else if (name === 'selection_method') filters.selectionMethod = values;
                else if (name === 'location') filters.place = values;
                else if (name === 'medicine_group' || name === 'technical_group') filters.drugGroup = values;
                else if (criterion.kind === 'tokens' && values.length === 1 && /\s/.test(values[0]) && (field.type === 'string' || field.type === 'string[]')) {
                    addTextFields(name);
                    textValues.push(quoteSearchPhrase(values[0]));
                }
                else if (criterion.kind === 'tokens' && legacyFilterKey) filters[legacyFilterKey] = { tokens: this.criterionTokens(criterion) };
                else if (field.filterable) structuredFilters[name] = values.length === 1 ? { eq: values[0] } : { in: values };
                else if (field.type === 'string' || field.type === 'string[]') { textFields.push(name); textValues.push(...values); }
            }
            const dateRanges = {};
            for (const [name, criterion] of Object.entries(this.state.criteria)) {
                if (criterion.kind === 'date-range') dateRanges[name] = { ...(criterion.from ? { from: criterion.from } : {}), ...(criterion.to ? { to: criterion.to } : {}) };
            }
            return {
                scope: crossGroupSearch ? 'all' : GROUP_SCOPE[this.state.group],
                group: crossGroupSearch ? null : this.state.group,
                sourceTypes: crossGroupSearch ? [] : [...this.state.sourceTypes],
                crossGroupSearch,
                crossGroupSearchFields,
                text: textValues.join(' '), searchFields: textFields, filters, structuredFilters, ranges, dateRanges,
                exactIdentifiers: {}, sort: [], page: this.state.page, limit: this.state.limit, queryMode: 'search'
            };
        }
        requestPreview() {
            clearTimeout(this.previewTimer);
            if (!Object.keys(this.state.criteria).length) { this.setPreviewResult({ idle: true }); return; }
            this.setPreviewResult({ loading: true });
            this.previewTimer = setTimeout(() => this.dispatchEvent(new CustomEvent('preview-filters', { detail: this.collectFilterPayload(), bubbles: true, composed: true })), 300);
        }
        activeSummary() { const count = Object.keys(this.state.criteria).length; return count ? `${count} điều kiện đang chọn` : ''; }
        submit() {
            if (!Object.keys(this.state.criteria).length) return;
            const request = this.collectFilterPayload();
            this.setApplyLoading(true);
            this.dispatchEvent(new CustomEvent('apply-filters', { detail: request, bubbles: true, composed: true }));
        }
        resetAllFilters() { this.state.criteria = {}; this.state.sourceTypes = []; this.state.page = 1; this.state.loading = false; this._previewState = { idle: true }; this.render(); this.dispatchEvent(new CustomEvent('reset-filters', { bubbles: true, composed: true })); }
        applyPayload(payload = {}) {
            const next = payload || {};
            if (next.group) this.state.group = next.group === 'traditional_medicine' ? 'traditional' : next.group === 'medicine' ? 'medicines' : next.group;
            this._previewState = { idle: true };
            this.state.pendingPayload = null; this.state.sourceTypes = Array.isArray(next.sourceTypes) ? [...next.sourceTypes] : []; this.state.criteria = {};
            Object.entries(next.structuredFilters || {}).forEach(([name, value]) => { const values = value?.in || (value?.eq !== undefined ? [value.eq] : []); if (values.length) this.state.criteria[name] = { kind: 'values', values }; });
            Object.entries(next.ranges || {}).forEach(([name, value]) => { this.state.criteria[name] = { kind: 'range', min: value?.min ?? '', max: value?.max ?? '' }; });
            Object.entries(next.dateRanges || {}).forEach(([name, value]) => { this.state.criteria[name] = { kind: 'date-range', from: value?.from ?? '', to: value?.to ?? '' }; });
            if (next.filters?.selectionMethod?.length) this.state.criteria.selection_method = { kind: 'values', values: next.filters.selectionMethod.map(value => this.optionLabel('selection_method', value)) };
            if (next.filters?.place?.length) this.state.criteria.location = { kind: 'values', values: next.filters.place };
            if (next.filters?.drugGroup?.length) this.state.criteria[this.state.group === 'traditional' ? 'technical_group' : 'medicine_group'] = { kind: 'values', values: next.filters.drugGroup };
            Object.entries(LEGACY_TOKEN_FILTER_KEYS[this.state.group] || {}).forEach(([name, filterKey]) => {
                const tokens = next.filters?.[filterKey]?.tokens;
                if (Array.isArray(tokens) && tokens.length) this.state.criteria[name] = { kind: 'tokens', tokens: tokens.map((token, index) => ({ value: token.value, op: index ? token.op : 'OR' })) };
            });
            this.state.page = Math.max(1, Number(next.page || 1)); this.state.limit = Math.min(1000, Math.max(25, Number(next.limit || 50))); this.ensureActiveField();
        }
        setFilterPayload(payload = {}) { if (!this.state.contract) this.state.pendingPayload = payload; else { this.applyPayload(payload); this.render(); } }
        setPage(page) { this.state.page = Math.max(1, Number(page || 1)); }
        setApplyLoading(loading = false) {
            this.state.loading = Boolean(loading);
            const button = this.shadowRoot?.querySelector('[data-action="apply"]');
            if (!button) return;
            if (loading) {
                button.dataset.defaultText = button.dataset.defaultText || button.textContent;
                button.textContent = 'Đang tìm kiếm…';
                button.disabled = true;
            } else {
                button.textContent = button.dataset.defaultText || 'Tìm kiếm nâng cao';
            }
            this.syncEditorActions();
        }
        setPreviewResult({ idle = false, loading = false, error = false, errorMessage = '', total = null, totalLabel = '' } = {}) {
            this._previewState = { idle, loading, error, errorMessage, total, totalLabel };
            const status = this.shadowRoot?.querySelector('.preview-estimate'); if (!status) return; status.classList.toggle('error', error); status.classList.toggle('loading', loading); status.classList.remove('zero-result');
            if (idle) status.textContent = ''; else if (loading) status.textContent = 'Đang ước tính...'; else if (error) status.textContent = errorMessage || 'Không ước tính được số kết quả.'; else if (total !== null || totalLabel) {
                const count = Number(total);
                const hasCount = total !== null && total !== undefined && total !== '' && Number.isFinite(count);
                const isOverThreshold = (hasCount && count > 100) || /^\s*100\+/.test(String(totalLabel));
                status.textContent = isOverThreshold ? 'Có 100+ kết quả' : !hasCount || count <= 0 ? 'Có 0 kết quả' : `Có ${count} kết quả`;
                status.classList.toggle('zero-result', !isOverThreshold && (!hasCount || count <= 0));
            }
        }
        showStatus(message, error = false) { const status = this.shadowRoot?.querySelector('.preview-estimate'); if (status) { status.textContent = message; status.classList.toggle('error', error); } }
        showError(message) { this.renderShell(message); this.shadowRoot.querySelector('.ts-loading')?.classList.add('ts-error'); }
        hasVisiblePreviewEstimate() { return /Có\s+(?:100\+|\d+)\s+kết quả/.test(this.shadowRoot?.querySelector('.preview-estimate')?.textContent || ''); }
        activatePane(pane = '', { focus = false } = {}) { if (this.fieldMeta(pane)) this.state.activeField = pane; if (this.state.contract) this.render(); if (focus) this.focusActiveField(); }
        getPreferredPaneForOpen() { return this.state.activeField || this.fields()[0]?.name || ''; }
        focusActiveField() { this.shadowRoot?.querySelector('#criterion-keyword,[data-date-text="from"],[data-dropdown-toggle],#criterion-min,#criterion-max')?.focus(); }
    }
    customElements.define('typesense-search-form', TypesenseSearchForm);
})();
