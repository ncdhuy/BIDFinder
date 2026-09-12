const API_BASE_URL =
  window.API_BASE_URL ||
  window.BIDFINDER_CONFIG?.apiBaseUrl ||
  ((window.location.protocol === 'file:' ||
      window.location.hostname === 'localhost' ||
      window.location.hostname === '127.0.0.1')
    ? 'http://127.0.0.1:8001'
    : 'https://api.bidfinder.vn');

window.API_BASE_URL = API_BASE_URL;

function getAuthorizedFetch() {
    return window.bidfinderAuthorizedFetch || fetch;
}

function getProcurementSearchForm() {
    return document.querySelector('typesense-search-form, custom-search-form');
}

// Keep legacy payload aliases only for compatibility with older responses and
// legacy search surfaces. Result-table columns themselves use canonical ids.
const LEGACY_FIELD_ALIASES = {
    'Tên hoạt chất': ['active_ingredient_or_herbal_component'],
    'Tên thuốc': ['medicine_name'],
    'Nồng độ, hàm lượng': ['strength'],
    'Đường dùng': ['route_of_administration'],
    'Dạng bào chế': ['dosage_form'],
    'Quy cách': ['packaging'],
    'GĐKLH hoặc GPNK': ['marketing_authorization_or_import_permit', 'registration_or_import_permit_number'],
    'Mã thuốc': ['medicine_code', 'id'],
    'Cơ sở sản xuất': ['manufacturer'],
    'Xuất xứ': ['production_country', 'country_of_origin', 'origin'],
    'Nhóm thuốc': ['medicine_group'],
    'Đơn vị tính': ['unit'],
    'Số lượng': ['quantity'],
    'Đơn giá trúng thầu (VND)': ['winning_unit_price'],
    'Thành tiền (VND)': ['total_value', 'winning_total_value'],
    'Mã TBMT': ['bid_invitation_code'],
    'Chủ đầu tư': ['procuring_entity_name'],
    'Quyết định phê duyệt': ['decision_number'],
    'Ngày phê duyệt': ['decision_issued_at', 'result_posted_at'],
    'Hình thức LCNT': ['selection_method'],
    'Địa điểm': ['location'],
    'Ngày hết hiệu lực': ['valid_until', 'expiration_date', 'shelf_life'],
    'Tình trạng hiệu lực': ['validity_status'],
    'Nhà thầu trúng thầu': ['winning_bidder_name'],
    'Tên phần/lô': ['lot_name', 'item_name'],
    'Danh mục hàng hóa': ['item_name'],
    'Tính năng kỹ thuật': ['technical_specification'],
    'Mặt hàng dự thầu': ['bid_item', 'item_name'],
    'Nhãn hiệu': ['brand'],
    'Ký mã hiệu': ['model_mark', 'model'],
    'Khối lượng': ['quantity'],
    'Hãng sản xuất': ['manufacturer'],
    'Tên dược liệu / vị thuốc': ['item_name', 'medicine_name'],
    'Tên khoa học': ['scientific_name'],
    'Nguồn gốc': ['origin', 'country_of_origin'],
    'Bộ phận dùng': ['used_part'],
    'Phương pháp chế biến': ['processing_method'],
    'Số lượng / khối lượng': ['quantity']
};

const LEGACY_CANONICAL_LABELS = {
    item_name: 'Tên hàng hóa / dược liệu',
    medicine_name: 'Tên thuốc',
    unit: 'Đơn vị tính',
    quantity: 'Số lượng / khối lượng',
    country_of_origin: 'Xuất xứ',
    hs_code: 'Mã HS',
    model_mark: 'Ký mã hiệu',
    brand: 'Nhãn hiệu',
    production_year: 'Năm sản xuất',
    manufacturer: 'Hãng / cơ sở sản xuất',
    technical_specification: 'Cấu hình / tính năng kỹ thuật',
    model: 'Chủng loại',
    registration_or_import_permit_number: 'Số lưu hành / giấy phép nhập khẩu',
    winning_unit_price: 'Đơn giá trúng thầu',
    winning_bidder_id: 'Mã nhà thầu trúng thầu',
    winning_bidder_name: 'Nhà thầu trúng thầu',
    bid_invitation_code: 'Mã TBMT',
    procuring_entity_id: 'Mã chủ đầu tư',
    procuring_entity_name: 'Chủ đầu tư',
    selection_method: 'Hình thức lựa chọn nhà thầu',
    result_posted_at: 'Thời điểm đăng kết quả',
    decision_number: 'Số quyết định',
    decision_issued_at: 'Ngày ban hành quyết định',
    bidder_count: 'Số nhà thầu tham dự',
    location: 'Địa điểm',
    active_ingredient_or_herbal_component: 'Hoạt chất / thành phần dược liệu',
    strength: 'Nồng độ / hàm lượng',
    marketing_authorization_or_import_permit: 'GĐKLH hoặc GPNK',
    route_of_administration: 'Đường dùng',
    dosage_form: 'Dạng bào chế',
    shelf_life: 'Hạn dùng',
    production_country: 'Nước sản xuất',
    packaging: 'Quy cách đóng gói',
    medicine_group: 'Nhóm thuốc',
    used_part: 'Bộ phận dùng',
    scientific_name: 'Tên khoa học',
    origin: 'Nguồn gốc',
    processing_method: 'Phương pháp chế biến',
    technical_group: 'Nhóm tiêu chí kỹ thuật'
};

const RESULT_COLUMN_ALIASES = {
    // Accept the historical misspelling from older saved/result payloads,
    // while keeping the canonical field and its display label.
    wining_unit_price: 'winning_unit_price'
};

const LEGACY_DATASET_GROUPS = {
    goods: {
        scope: 'goods',
        resultPanel: 'df2-panel',
        subtypes: [
            ['goods_general', 'Hàng hóa ngoài thuốc, thiết bị, vật tư y tế'],
            ['medical_devices', 'Thiết bị, vật tư y tế']
        ]
    },
    medicines: {
        scope: 'medicine',
        resultPanel: 'df1-panel',
        subtypes: [
            ['medicine_generic', 'Thuốc Generic'],
            ['medicine_originator', 'Thuốc biệt dược gốc'],
            ['medicine_herbal', 'Thuốc dược liệu']
        ]
    },
    traditional_medicine: {
        scope: 'traditional',
        resultPanel: 'df3-panel',
        subtypes: [
            ['herbal_material', 'Dược liệu'],
            ['traditional_medicine', 'Vị thuốc cổ truyền']
        ]
    }
};

let activeLegacyDatasetGroup = 'medicines';
let advancedSearchContract = null;
let advancedSearchContractPromise = null;

function legacyDatasetDefinition(group = activeLegacyDatasetGroup) {
    return LEGACY_DATASET_GROUPS[group] || LEGACY_DATASET_GROUPS.medicines;
}

function getSelectedLegacySourceTypes() {
    const searchForm = getProcurementSearchForm();
    if (searchForm?.matches?.('typesense-search-form') && typeof searchForm.collectFilterPayload === 'function') {
        return searchForm.collectFilterPayload().sourceTypes || [];
    }
    return Array.from(document.querySelectorAll('#advanced-subtype-list input[data-legacy-source]:checked'))
        .map(input => input.value);
}

function renderLegacySubtypeOptions(group = activeLegacyDatasetGroup, selectedTypes = null) {
    const container = document.getElementById('advanced-subtype-list');
    if (!container) return;
    const definition = legacyDatasetDefinition(group);
    const selected = new Set(
        selectedTypes?.length ? selectedTypes : definition.subtypes.map(([value]) => value)
    );
    container.replaceChildren();

    const allLabel = document.createElement('label');
    allLabel.className = 'advanced-subtype-option advanced-subtype-all';
    const allInput = document.createElement('input');
    allInput.type = 'checkbox';
    allInput.dataset.legacySourceAll = 'true';
    allInput.checked = definition.subtypes.every(([value]) => selected.has(value));
    const allText = document.createElement('span');
    allText.textContent = 'Tất cả';
    allLabel.append(allInput, allText);
    container.appendChild(allLabel);

    definition.subtypes.forEach(([value, labelText]) => {
        const label = document.createElement('label');
        label.className = 'advanced-subtype-option';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.value = value;
        input.dataset.legacySource = value;
        input.checked = selected.has(value);
        input.addEventListener('change', () => {
            if (!getSelectedLegacySourceTypes().length) input.checked = true;
            if (allInput) {
                allInput.checked = definition.subtypes.every(([item]) =>
                    container.querySelector(`[data-legacy-source="${item}"]`)?.checked
                );
            }
            enableLegacyDatasetSearch();
        });
        const text = document.createElement('span');
        text.textContent = labelText;
        label.append(input, text);
        container.appendChild(label);
    });
    allInput.addEventListener('change', () => {
        const shouldSelectAll = allInput.checked;
        container.querySelectorAll('[data-legacy-source]').forEach(input => {
            input.checked = shouldSelectAll;
        });
        if (!shouldSelectAll && !getSelectedLegacySourceTypes().length) {
            allInput.checked = true;
            container.querySelectorAll('[data-legacy-source]').forEach(input => {
                input.checked = true;
            });
        }
        enableLegacyDatasetSearch();
    });
    enableLegacyDatasetSearch();
}

function enableLegacyDatasetSearch() {
    const root = getProcurementSearchForm()?.shadowRoot;
    const applyButton = root?.getElementById('apply-filters-btn') || root?.querySelector('[data-action="apply"]');
    if (applyButton) applyButton.disabled = false;
}

function normalizeLegacyDatasetGroup(group) {
    if (group === 'goods') return 'goods';
    if (group === 'medicines' || group === 'medicine') return 'medicines';
    if (group === 'traditional' || group === 'traditional_medicine') return 'traditional_medicine';
    return null;
}

function syncLegacyDatasetControlsFromRequest(request = {}) {
    const group = normalizeLegacyDatasetGroup(request.group) || activeLegacyDatasetGroup;
    activeLegacyDatasetGroup = group;
    const searchForm = getProcurementSearchForm();
    if (searchForm?.matches?.('typesense-search-form')) return;
    document.querySelectorAll('.advanced-group-tab').forEach(button => {
        const active = button.dataset.legacyGroup === group;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', String(active));
    });
    renderLegacySubtypeOptions(group, Array.isArray(request.sourceTypes) ? request.sourceTypes : null);
}

function getLegacyDatasetRequest() {
    const definition = legacyDatasetDefinition();
    return {
        scope: definition.scope,
        group: activeLegacyDatasetGroup,
        sourceTypes: getSelectedLegacySourceTypes()
    };
}

function enrichLegacyQueryRequest(payload = {}) {
    const safePayload = payload && typeof payload === 'object' ? payload : {};
    const crossGroupSearch = safePayload.crossGroupSearch === true;
    const requestedGroup = crossGroupSearch
        ? null
        : (normalizeLegacyDatasetGroup(safePayload.group) || activeLegacyDatasetGroup);
    const definition = legacyDatasetDefinition(requestedGroup);
    if (requestedGroup) activeLegacyDatasetGroup = requestedGroup;
    const filters = safePayload.filters && typeof safePayload.filters === 'object'
        ? { ...safePayload.filters }
        : {};
    const dateRanges = safePayload.dateRanges && typeof safePayload.dateRanges === 'object'
        ? { ...safePayload.dateRanges }
        : {};
    if (filters.dateFrom || filters.dateTo) {
        dateRanges.partition_date = {
            ...(dateRanges.partition_date || {}),
            ...(filters.dateFrom ? { from: filters.dateFrom } : {}),
            ...(filters.dateTo ? { to: filters.dateTo } : {})
        };
        delete filters.dateFrom;
        delete filters.dateTo;
    }
    const sourceTypes = crossGroupSearch
        ? []
        : (Array.isArray(safePayload.sourceTypes)
        ? safePayload.sourceTypes
        : getLegacyDatasetRequest().sourceTypes);
    if (requestedGroup) syncLegacyDatasetControlsFromRequest({ group: requestedGroup, sourceTypes });
    return buildQueryRequest({
        ...safePayload,
        scope: crossGroupSearch ? 'all' : definition.scope,
        group: requestedGroup,
        sourceTypes,
        crossGroupSearch,
        filters,
        text: safePayload.text || '',
        searchFields: safePayload.searchFields || [],
        structuredFilters: safePayload.structuredFilters || {},
        ranges: safePayload.ranges || {},
        dateRanges,
        exactIdentifiers: safePayload.exactIdentifiers || {},
        sort: safePayload.sort || []
    });
}

async function loadAdvancedSearchContract() {
    if (advancedSearchContract) return advancedSearchContract;
    if (!advancedSearchContractPromise) {
        advancedSearchContractPromise = getAuthorizedFetch()(`${API_BASE_URL}/api/search-contract`)
            .then(async response => {
                const payload = await response.json();
                if (!response.ok || !payload?.contract?.groups) {
                    throw new Error(payload?.message || `HTTP ${response.status}`);
                }
                return payload.contract;
            })
            .then(contract => {
                advancedSearchContract = contract;
                renderBulkFieldPanels();
                return contract;
            })
            .catch(error => {
                advancedSearchContractPromise = null;
                const status = document.getElementById('advanced-contract-status');
                if (status) status.textContent = 'Không tải được các tiêu chí mở rộng.';
                const bulkStatus = document.getElementById('bulk-contract-status');
                if (bulkStatus) bulkStatus.textContent = 'Không tải được danh mục trường tìm kiếm. Vui lòng tải lại trang.';
                console.warn('Search contract unavailable:', error);
                return null;
            });
    }
    return advancedSearchContractPromise;
}

function initAdvancedContractControls() {
    loadAdvancedSearchContract();
}

function requireAuthenticatedSession(mode = 'login', requirement = 'preview') {
    const auth = window.BIDFinderAuth;
    if (!auth) return true;
    if (auth.isAuthenticated?.()) return true;

    const config = auth.getConfig?.() || {};

    if (requirement === 'full_query') {
        if (!config.require_auth_for_full_query) return true;
        return auth.ensureAuthenticated(mode);
    }

    if (requirement === 'preview') {
        if (config.allow_anonymous_preview) return true;
        if (!config.require_auth_for_data_access) return true;
        return auth.ensureAuthenticated(mode);
    }

    if (requirement === 'metadata') {
        if (config.allow_anonymous_metadata) {
            return !config.require_auth_for_data_access || auth.ensureAuthenticated(mode);
        }
        return auth.ensureAuthenticated(mode);
    }

    if (!config.require_auth_for_data_access) return true;
    return auth.ensureAuthenticated(mode);
}

// ============================== 
// UTILS
// ============================== 

// ========= 1. FORMAT
function formatNumber(value, options = {}) {
    if (value === null || value === undefined || value === '') return '';
    const num = Number(value);
    if (isNaN(num)) return value;
    return num.toLocaleString('vi-VN', options);
}

function formatBidderCount(value) {
    if (value === null || value === undefined || value === '') return '';
    const num = Number(value);
    if (!Number.isFinite(num)) return value;
    return Math.floor(num + 0.5).toLocaleString('vi-VN');
}

function formatCurrency(v) {
    return formatNumber(v, { maximumFractionDigits: 2 });
}

function formatDate(dateValue, returnOriginal = false) {
    if (!dateValue) return '';
    const s = String(dateValue).trim();

    // Đã đúng format DD/MM/YYYY → trả về ngay, không cần parse
    if (/^\d{2}\/\d{2}\/\d{4}$/.test(s)) return s;

    // ISO / các format khác → parse rồi format lại
    try {
        const date = new Date(s);
        if (isNaN(date.getTime())) return returnOriginal ? s : '';
        const day   = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year  = date.getFullYear();
        return `${day}/${month}/${year}`;
    } catch (e) {
        return returnOriginal ? s : '';
    }
}

// ========= 2. STORAGE
const RESULT_TABLE_GROUPS = {
    'standard-table': 'medicines',
    'extended-table': 'goods',
    'traditional-table': 'traditional'
};
const RESULT_COLUMN_CATALOG = window.BIDFinderDataColumns || {
    order: { goods: [], medicines: [], traditional: [] },
    labels: { goods: {}, medicines: {}, traditional: {} }
};

// Keep stable canonical field ids in the DOM. The existing drag/drop and
// localStorage order machinery can then customize columns without depending
// on translated display labels.
const DF1_COLUMNS_ORDER = [...(RESULT_COLUMN_CATALOG.order.medicines || [])];
const DF2_COLUMNS_ORDER = [...(RESULT_COLUMN_CATALOG.order.goods || [])];
const DF3_COLUMNS_ORDER = [...(RESULT_COLUMN_CATALOG.order.traditional || [])];

function getResultColumnLabel(tableId, columnName) {
    const group = RESULT_TABLE_GROUPS[tableId];
    const canonicalName = RESULT_COLUMN_ALIASES[columnName] || columnName;
    return RESULT_COLUMN_CATALOG.labels?.[group]?.[canonicalName]
        || RESULT_COLUMN_CATALOG.labels?.[group]?.[columnName]
        || LEGACY_CANONICAL_LABELS[canonicalName]
        || columnName;
}

let currentColumnOrderDf1 = [...DF1_COLUMNS_ORDER];
let currentColumnOrderDf2 = [...DF2_COLUMNS_ORDER];
let currentColumnOrderDf3 = [...DF3_COLUMNS_ORDER];
const TABLE_DEFAULT_COLUMNS = {
    'standard-table': DF1_COLUMNS_ORDER,
    'extended-table': DF2_COLUMNS_ORDER,
    'traditional-table': DF3_COLUMNS_ORDER
};
const TABLE_COLUMN_WIDTH_KEYS = {
    'standard-table': 'colWidthDf1',
    'extended-table': 'colWidthDf2',
    'traditional-table': 'colWidthDf3'
};
const STORAGE_KEYS = {
    hiddenColumns: 'hiddenColumnsByTable',
    wrappedColumns: 'wrappedColumnsByTable',
    frozenColumns: 'frozenColumnsByTable',
    sortRule: 'activeTableSortRule'
};
const RESETTABLE_UI_STORAGE_KEYS = [
    'colWidthDf1',
    'colWidthDf2',
    'colWidthDf3',
    STORAGE_KEYS.hiddenColumns,
    STORAGE_KEYS.wrappedColumns,
    STORAGE_KEYS.frozenColumns,
    STORAGE_KEYS.sortRule
];
const RESETTABLE_UI_SESSION_KEYS = [
    'bidfinder:view'
];

function clearResettableUiStateOnRefresh() {
    RESETTABLE_UI_STORAGE_KEYS.forEach(key => localStorage.removeItem(key));
    RESETTABLE_UI_SESSION_KEYS.forEach(key => sessionStorage.removeItem(key));
}

clearResettableUiStateOnRefresh();

function readJsonStorage(key, fallback) {
    try {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : fallback;
    } catch (error) {
        console.warn(`Khong doc duoc localStorage key ${key}:`, error);
        localStorage.removeItem(key);
        return fallback;
    }
}

function writeJsonStorage(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
}

function normalizeStoredColumnSet(values, tableId) {
    const allowed = new Set(TABLE_DEFAULT_COLUMNS[tableId] || []);
    if (!Array.isArray(values)) return new Set();
    return new Set(values.filter(value => allowed.has(value)));
}

function loadPersistentColumnSets(storageKey) {
    const stored = readJsonStorage(storageKey, {});
    return {
        'standard-table': normalizeStoredColumnSet(stored?.['standard-table'], 'standard-table'),
        'extended-table': normalizeStoredColumnSet(stored?.['extended-table'], 'extended-table'),
        'traditional-table': normalizeStoredColumnSet(stored?.['traditional-table'], 'traditional-table')
    };
}

function persistColumnSet(storageKey, tableId, valueSet) {
    const stored = readJsonStorage(storageKey, {});
    stored[tableId] = Array.from(valueSet);
    writeJsonStorage(storageKey, stored);
}

function loadStoredSortRule() {
    const stored = readJsonStorage(STORAGE_KEYS.sortRule, null);
    if (!stored || typeof stored !== 'object') return null;
    if (typeof stored.column !== 'string') return null;
    if (!['asc', 'desc'].includes(stored.order)) return null;
    return { column: stored.column, order: stored.order };
}

function persistSortRule(rule) {
    if (!rule) {
        localStorage.removeItem(STORAGE_KEYS.sortRule);
        return;
    }
    writeJsonStorage(STORAGE_KEYS.sortRule, rule);
}

function validateColumnOrder(parsed, defaultOrder, storageKey) {
    if (!Array.isArray(parsed) || 
        parsed.length !== defaultOrder.length ||
        !parsed.every(col => defaultOrder.includes(col))) {
        localStorage.removeItem(storageKey);
        return [...defaultOrder];
    }
    return parsed;
}

function restoreColumnOrderFromStorage() {
    const configs = [
        { key: 'columnOrderDf1', default: DF1_COLUMNS_ORDER, target: 'currentColumnOrderDf1' },
        { key: 'columnOrderDf2', default: DF2_COLUMNS_ORDER, target: 'currentColumnOrderDf2' },
        { key: 'columnOrderDf3', default: DF3_COLUMNS_ORDER, target: 'currentColumnOrderDf3' }
    ];

    configs.forEach(({ key, default: defaultOrder, target }) => {
        const saved = localStorage.getItem(key);
        if (!saved) return;

        try {
            const parsed = JSON.parse(saved);
            const validated = validateColumnOrder(parsed, defaultOrder, key);
            
            if (target === 'currentColumnOrderDf1') {
                currentColumnOrderDf1 = validated;
            } else if (target === 'currentColumnOrderDf2') {
                currentColumnOrderDf2 = validated;
            } else {
                currentColumnOrderDf3 = validated;
            }
            
            if (validated !== defaultOrder) {
                console.log(`✅ Khôi phục thứ tự cột ${target} từ storage`);
            }
        } catch (e) {
            console.warn(`Không parse được ${key}, dùng mặc định`);
            localStorage.removeItem(key);
        }
    });
}


// ============================== 
// TABLES
// ============================== 

// ========= 1. RENDER
let standardTbody;
let extendedTbody;
let traditionalTbody;
const wrappedColumnsState = loadPersistentColumnSets(STORAGE_KEYS.wrappedColumns);
const frozenColumnsState = loadPersistentColumnSets(STORAGE_KEYS.frozenColumns);
const hiddenColumnsState = loadPersistentColumnSets(STORAGE_KEYS.hiddenColumns);
const columnValueFilterState = {
    'standard-table': {},
    'extended-table': {},
    'traditional-table': {}
};
const columnTextFilterState = {
    'standard-table': {},
    'extended-table': {},
    'traditional-table': {}
};
const TEXT_FILTER_OPERATOR_LABELS = Object.freeze({
    equals: 'Bằng',
    notEquals: 'Không bằng',
    beginsWith: 'Bắt đầu bằng',
    endsWith: 'Kết thúc bằng',
    contains: 'Chứa',
    notContains: 'Không chứa'
});
const TEXT_FILTER_OPERATORS = new Set(Object.keys(TEXT_FILTER_OPERATOR_LABELS));
let activeSortRule = loadStoredSortRule();
const selectionState = {
    'standard-table': { rows: new Set(), columns: new Set(), lastRow: null, lastColumn: null },
    'extended-table': { rows: new Set(), columns: new Set(), lastRow: null, lastColumn: null },
    'traditional-table': { rows: new Set(), columns: new Set(), lastRow: null, lastColumn: null }
};
let currentDisplayedDf1 = [];
let currentDisplayedDf2 = [];
let currentDisplayedDf3 = [];
let serverBaseDf1 = [];
let serverBaseDf2 = [];
let serverBaseDf3 = [];
let baseWorkingDf1 = null;
let baseWorkingDf2 = null;
let baseWorkingDf3 = null;
let orderedWorkingDf1 = null;
let orderedWorkingDf2 = null;
let orderedWorkingDf3 = null;
const workingSetAvailable = {
    'standard-table': false,
    'extended-table': false,
    'traditional-table': false
};
let currentQueryMeta = {
    df1HasMore: false,
    df2HasMore: false,
    df3HasMore: false,
    df1Displayed: 0,
    df1Total: 0,
    df1WorkingCount: 0,
    df1WorkingSetTruncated: false,
    df1TotalLabel: '0',
    df2Displayed: 0,
    df2Total: 0,
    df2WorkingCount: 0,
    df2WorkingSetTruncated: false,
    df2TotalLabel: '0',
    df3Displayed: 0,
    df3Total: 0,
    df3WorkingCount: 0,
    df3WorkingSetTruncated: false,
    df3TotalLabel: '0',
    page: 1,
    totalCount: 0,
    totalCountExact: true,
    totalCountLabel: '0',
    searchMode: 'standard',
    bulkSearchMode: 'standard',
    appliedTotalLimit: 0,
    appliedLimitPerScope: 0
};
let fullSearchInFlight = false;

// Configuration object cho từng loại table
const TABLE_CONFIGS = {
    df1: {
        tbody: () => standardTbody,
        columnOrder: () => currentColumnOrderDf1,
        rightAlignColumns: ['quantity', 'winning_unit_price', 'bidder_count'],
        fieldMappers: {
            result_posted_at: formatDate,
            decision_issued_at: formatDate,
            quantity: formatNumber,
            winning_unit_price: formatCurrency,
            bidder_count: formatBidderCount
        }
    },
    df2: {
        tbody: () => extendedTbody,
        columnOrder: () => currentColumnOrderDf2,
        rightAlignColumns: ['quantity', 'winning_unit_price', 'bidder_count'],
        fieldMappers: {
            result_posted_at: formatDate,
            decision_issued_at: formatDate,
            quantity: formatNumber,
            winning_unit_price: formatCurrency,
            bidder_count: formatBidderCount
        }
    },
    df3: {
        tbody: () => traditionalTbody,
        columnOrder: () => currentColumnOrderDf3,
        rightAlignColumns: ['quantity', 'winning_unit_price', 'bidder_count'],
        fieldMappers: {
            result_posted_at: formatDate,
            decision_issued_at: formatDate,
            quantity: formatNumber,
            winning_unit_price: formatCurrency,
            bidder_count: formatBidderCount
        }
    }
};

const DEFAULT_COLUMN_WIDTHS = {
    'standard-table': {
        medicine_name: 180,
        active_ingredient_or_herbal_component: 230,
        strength: 170,
        marketing_authorization_or_import_permit: 190,
        route_of_administration: 140,
        dosage_form: 160,
        shelf_life: 150,
        manufacturer: 190,
        production_country: 150,
        packaging: 180,
        unit: 120,
        quantity: 120,
        winning_unit_price: 170,
        winning_bidder_id: 190,
        winning_bidder_name: 210,
        medicine_group: 150,
        bid_invitation_code: 150,
        procuring_entity_id: 180,
        procuring_entity_name: 180,
        selection_method: 180,
        result_posted_at: 170,
        decision_number: 160,
        decision_issued_at: 170,
        bidder_count: 140,
        location: 150
    },
    'extended-table': {
        item_name: 190,
        unit: 120,
        quantity: 130,
        country_of_origin: 150,
        hs_code: 120,
        model_mark: 150,
        brand: 140,
        production_year: 130,
        manufacturer: 180,
        technical_specification: 260,
        model: 170,
        registration_or_import_permit_number: 190,
        winning_unit_price: 170,
        winning_bidder_id: 190,
        winning_bidder_name: 210,
        bid_invitation_code: 150,
        procuring_entity_id: 180,
        procuring_entity_name: 180,
        selection_method: 180,
        result_posted_at: 170,
        decision_number: 160,
        decision_issued_at: 170,
        bidder_count: 140,
        location: 150
    },
    'traditional-table': {
        item_name: 240,
        used_part: 160,
        scientific_name: 190,
        origin: 150,
        processing_method: 190,
        registration_or_import_permit_number: 190,
        manufacturer: 190,
        production_country: 150,
        packaging: 180,
        unit: 120,
        quantity: 120,
        winning_unit_price: 170,
        winning_bidder_id: 190,
        winning_bidder_name: 210,
        technical_group: 180,
        bid_invitation_code: 150,
        procuring_entity_id: 180,
        procuring_entity_name: 180,
        selection_method: 180,
        result_posted_at: 170,
        decision_number: 160,
        decision_issued_at: 170,
        bidder_count: 140,
        location: 150
    }
};

const DEFAULT_COMPACT_COLUMN_WIDTH = 120;
const DEFAULT_STANDARD_TEXT_WIDTH = 160;
const DEFAULT_LONG_TEXT_WIDTH = 220;
const MAX_REASONABLE_COLUMN_WIDTH = 600;

function inferDefaultColumnWidth(tableId, columnName) {
    const explicitWidth = DEFAULT_COLUMN_WIDTHS[tableId]?.[columnName];
    if (Number.isFinite(explicitWidth) && explicitWidth > 0) {
        return explicitWidth;
    }

    const normalized = getResultColumnLabel(tableId, columnName).toLocaleLowerCase('vi');
    if (!normalized) return DEFAULT_STANDARD_TEXT_WIDTH;

    if (
        normalized.includes('ngày') ||
        normalized.includes('mã ') ||
        normalized.includes('số lượng') ||
        normalized.includes('khối lượng') ||
        normalized.includes('đơn vị') ||
        normalized.includes('đơn giá') ||
        normalized.includes('thành tiền')
    ) {
        return DEFAULT_COMPACT_COLUMN_WIDTH;
    }

    if (
        normalized.includes('tên ') ||
        normalized.includes('chủ đầu tư') ||
        normalized.includes('nhà thầu') ||
        normalized.includes('danh mục') ||
        normalized.includes('tính năng') ||
        normalized.includes('mặt hàng')
    ) {
        return DEFAULT_LONG_TEXT_WIDTH;
    }

    return DEFAULT_STANDARD_TEXT_WIDTH;
}

function getResultTableIdForConfig(configKey) {
    if (configKey === 'df2') return 'extended-table';
    if (configKey === 'df3') return 'traditional-table';
    return 'standard-table';
}

function legacyDetailLabel(fieldName, tableId = null) {
    if (['id', 'data_group', 'source_tab', 'source_tab_label', 'partition_date'].includes(fieldName) || fieldName.startsWith('__')) return '';
    if (tableId && RESULT_COLUMN_CATALOG.labels?.[RESULT_TABLE_GROUPS[tableId]]?.[fieldName]) {
        return getResultColumnLabel(tableId, fieldName);
    }
    if (Object.prototype.hasOwnProperty.call(LEGACY_FIELD_ALIASES, fieldName)) return fieldName;
    const known = Object.entries(LEGACY_FIELD_ALIASES)
        .find(([, aliases]) => aliases.includes(fieldName));
    if (known?.[0]) return known[0];
    if (LEGACY_CANONICAL_LABELS[fieldName]) return LEGACY_CANONICAL_LABELS[fieldName];
    return Object.values(advancedSearchContract?.groups || {})
        .flatMap(group => group.fields || [])
        .find(field => field.name === fieldName)?.label || '';
}

let legacyDetailPreviousFocus = null;

function closeLegacyRowDetail({ restoreFocus = true } = {}) {
    const detail = document.getElementById('legacy-row-detail');
    if (!detail) return;
    detail.classList.remove('show');
    detail.hidden = true;
    detail.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('legacy-detail-open');
    if (restoreFocus && legacyDetailPreviousFocus?.isConnected) legacyDetailPreviousFocus.focus();
    legacyDetailPreviousFocus = null;
}

function openLegacyRowDetail(item, configKey) {
    const detail = document.getElementById('legacy-row-detail');
    const fields = document.getElementById('legacy-row-detail-fields');
    if (!detail || !fields || !item) return;

    // The detail dialog is declared inside the result layout, whose responsive
    // container can create a local containing block/clipping context. Move the
    // open dialog to body so its fixed backdrop always covers the full viewport.
    if (detail.parentElement !== document.body) {
        document.body.appendChild(detail);
    }

    fields.replaceChildren();
    const tableId = getResultTableIdForConfig(configKey);
    const preferred = TABLE_CONFIGS[configKey]?.columnOrder?.() || [];
    const orderedFields = [...preferred, ...Object.keys(item)];
    const seen = new Set();
    orderedFields.forEach(fieldName => {
        if (seen.has(fieldName) || fieldName.startsWith('__')) return;
        seen.add(fieldName);
        const rawValue = item[fieldName];
        const label = legacyDetailLabel(fieldName, tableId);
        if (!label || rawValue === undefined || rawValue === null || rawValue === '') return;
        const dt = document.createElement('dt');
        dt.textContent = label;
        const dd = document.createElement('dd');
        dd.textContent = Array.isArray(rawValue) ? rawValue.join(', ') : String(rawValue);
        fields.append(dt, dd);
    });

    legacyDetailPreviousFocus = document.activeElement;
    detail.hidden = false;
    detail.classList.add('show');
    detail.setAttribute('aria-hidden', 'false');
    document.body.classList.add('legacy-detail-open');
    detail.querySelector('#close-legacy-row-detail')?.focus();
}

function renderTableData(data, configKey) {
    const config = TABLE_CONFIGS[configKey];
    const tbody = config.tbody();
    const tableId = configKey === 'df1'
        ? 'standard-table'
        : configKey === 'df2' ? 'extended-table' : 'traditional-table';
    const columnOrder = getVisibleColumnOrder(tableId);

    tbody.replaceChildren();
    resetCellSelection();

    if (!data?.length) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = columnOrder.length + 1;
        td.className = 'table-empty-state';
        td.textContent = 'Chưa có dữ liệu. Vui lòng thực hiện tìm kiếm.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
    }
    
    console.log(`📊 Rendering ${data.length} rows for ${configKey.toUpperCase()} with order:`, columnOrder);
    
    const fragment = document.createDocumentFragment();
    
    data.forEach((item, index) => {
        const tr = document.createElement('tr');
        tr.className = index % 2 === 0 ? 'bg-white' : 'bg-gray-50';
        if (item?.__has_duplicate_warning) {
            tr.classList.add('row-duplicate-warning');
            tr.title = 'Phát hiện dòng trùng trong hồ sơ nguồn. BidFinder giữ nguyên dữ liệu gốc và chỉ hiển thị cảnh báo.';
        }
        tr.dataset.rowIndex = index;
        tr.title = item?.__has_duplicate_warning
            ? 'Phát hiện dòng trùng. Nhấp đúp để xem chi tiết.'
            : 'Nhấp để chọn ô, kéo để chọn vùng; nhấp đúp để xem chi tiết';
        tr.addEventListener('dblclick', () => openLegacyRowDetail(item, configKey));

        const selectorTd = document.createElement('td');
        selectorTd.className = 'row-selector-cell';
        selectorTd.dataset.rowIndex = index;
        selectorTd.textContent = index + 1;
        tr.appendChild(selectorTd);
        
        columnOrder.forEach(colName => {
            const td = document.createElement('td');
            td.className = 'px-4 py-2';
            td.dataset.colName = colName;
            
            if (config.rightAlignColumns.includes(colName)) {
                td.classList.add('text-right');
            }
            
            const value = mapField(item, colName, config.fieldMappers);
            td.textContent = value ?? '';
            tr.appendChild(td);
        });
        
        fragment.appendChild(tr);
    });
    
    tbody.appendChild(fragment);
    syncHeaderDecorations(tableId);
    syncWrappedColumns(tableId);
    syncSelectedColumns(tableId);
    syncSelectedRows(tableId);
    syncFrozenColumns(tableId);
}

function getColumnFieldCandidates(columnName) {
    const canonicalName = RESULT_COLUMN_ALIASES[columnName] || columnName;
    const legacyLabels = Object.entries(LEGACY_FIELD_ALIASES)
        .filter(([, aliases]) => aliases.includes(columnName))
        .map(([label]) => label);
    return [...new Set([
        columnName,
        canonicalName,
        ...(LEGACY_FIELD_ALIASES[canonicalName] || []),
        ...(LEGACY_FIELD_ALIASES[columnName] || []),
        ...legacyLabels
    ])];
}

function getRawColumnValue(item, colName) {
    return getColumnFieldCandidates(colName)
        .map(field => item?.[field])
        .find(value => value !== undefined && value !== null && value !== '');
}

function getFirstRawColumnValue(item, columnNames) {
    return columnNames
        .map(columnName => getRawColumnValue(item, columnName))
        .find(value => value !== undefined && value !== null && value !== '');
}

function getChartTotalValue(item) {
    const explicitTotal = Number(getFirstRawColumnValue(item, ['total_value', 'winning_total_value']));
    if (Number.isFinite(explicitTotal) && explicitTotal > 0) return explicitTotal;

    // Typesense rows expose quantity and unit price; derive total for charts.
    const quantity = Number(getFirstRawColumnValue(item, ['quantity']));
    const unitPrice = Number(getFirstRawColumnValue(item, ['winning_unit_price']));
    return Number.isFinite(quantity) && quantity > 0 && Number.isFinite(unitPrice) && unitPrice > 0
        ? quantity * unitPrice
        : 0;
}

const LOCATION_PROVINCE_PREFIX_RE = /^(?:T\u1ec9nh|Th\u00e0nh ph\u1ed1|TP\.?|City)\s+/i;
const LOCATION_LOCALITY_PREFIX_RE = /^(?:X\u00e3|Ph\u01b0\u1eddng|Th\u1ecb tr\u1ea5n|Qu\u1eadn|Huy\u1ec7n|Th\u1ecb x\u00e3)\s+/i;

function reorderLocationDisplayEntry(value) {
    const parts = String(value ?? '')
        .split(',')
        .map(part => part.trim())
        .filter(Boolean);
    if (parts.length < 2) return parts.join(', ');

    const provinceIndex = parts.findIndex(part => LOCATION_PROVINCE_PREFIX_RE.test(part));
    if (provinceIndex < 0) return parts.join(', ');

    const hasLocalityAfterProvince = parts
        .slice(provinceIndex + 1)
        .some(part => LOCATION_LOCALITY_PREFIX_RE.test(part));
    if (hasLocalityAfterProvince) parts.push(parts.splice(provinceIndex, 1)[0]);
    return parts.join(', ');
}

function formatLocationDisplayValue(value) {
    if (Array.isArray(value)) {
        return value.map(entry => {
            if (entry && typeof entry === 'object') {
                const province = entry.provName || entry.provinceName || entry.cityName
                    || entry.provCode || entry.provinceCode || entry.cityCode;
                const locality = entry.districtName || entry.wardName || entry.communeName
                    || entry.districtCode || entry.wardCode || entry.communeCode;
                return [locality, province].filter(Boolean).join(', ');
            }
            return reorderLocationDisplayEntry(entry);
        }).filter(Boolean).join('; ');
    }
    if (typeof value !== 'string') return value ?? '';
    return value.split(';').map(reorderLocationDisplayEntry).filter(Boolean).join('; ');
}

function mapField(item, colName, fieldMappers) {
    const canonicalName = RESULT_COLUMN_ALIASES[colName] || colName;
    const formatter = fieldMappers[canonicalName] || fieldMappers[colName];
    const rawValue = getRawColumnValue(item, colName);
    const displayValue = canonicalName === 'location'
        ? formatLocationDisplayValue(rawValue)
        : rawValue;
    const value = formatter ? formatter(displayValue) : (displayValue ?? '');
    return Array.isArray(value) ? value.join(', ') : value;
}

// Wrapper functions giữ lại interface cũ
function renderStandardData(data) {
    renderTableData(data, 'df1');
}

function renderExtendedData(data) {
    renderTableData(data, 'df2');
}

function renderTraditionalData(data) {
    renderTableData(data, 'df3');
}

// ========= 2. RESIZE COLUMNS
const autofitMeasureCanvas = document.createElement('canvas');
const autofitMeasureContext = autofitMeasureCanvas.getContext('2d');

function getCellDisplayLines(cell) {
    const raw = String(cell?.innerText || cell?.textContent || '')
        .replace(/\u00a0/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();

    if (!raw) return [''];

    return [raw];
}

function measureTextWidth(text, style) {
    if (!autofitMeasureContext || !style) return 0;

    autofitMeasureContext.font = [
        style.fontStyle,
        style.fontVariant,
        style.fontWeight,
        style.fontSize,
        style.fontFamily
    ].filter(Boolean).join(' ');

    const safeText = String(text || '');
    const baseWidth = autofitMeasureContext.measureText(safeText).width;
    const letterSpacing = parseFloat(style.letterSpacing);
    const spacingWidth = Number.isFinite(letterSpacing) && safeText.length > 1
        ? letterSpacing * (safeText.length - 1)
        : 0;

    return baseWidth + Math.max(0, spacingWidth);
}

function measureCellContentWidth(cell, extraWidth = 0) {
    if (!cell || !autofitMeasureContext) return 60;

    const style = window.getComputedStyle(cell);

    const textWidth = getCellDisplayLines(cell).reduce((maxWidth, line) => {
        return Math.max(maxWidth, measureTextWidth(line, style));
    }, 0);

    const paddingWidth =
        (parseFloat(style.paddingLeft) || 0) +
        (parseFloat(style.paddingRight) || 0) +
        (parseFloat(style.borderLeftWidth) || 0) +
        (parseFloat(style.borderRightWidth) || 0);

    return Math.ceil(textWidth + paddingWidth + extraWidth);
}

function getHeaderMinimumWidth(headerCell) {
    if (!headerCell) return 110;

    const label = headerCell.querySelector('.column-header-label');
    const target = label || headerCell;
    const style = window.getComputedStyle(target);
    const labelText = String(label?.textContent || headerCell.dataset.colName || headerCell.textContent || '')
        .replace(/\s+/g, ' ')
        .trim();

    const labelWidth = measureTextWidth(labelText, style);
    const headerStyle = window.getComputedStyle(headerCell);
    const shellStyle = window.getComputedStyle(headerCell.querySelector('.column-header-shell') || headerCell);
    const horizontalPadding =
        (parseFloat(headerStyle.paddingLeft) || 0) +
        (parseFloat(headerStyle.paddingRight) || 0) +
        (parseFloat(shellStyle.paddingLeft) || 0) +
        (parseFloat(shellStyle.paddingRight) || 0);

    const reservedControlsWidth = 56;
    return Math.ceil(Math.max(110, labelWidth + horizontalPadding + reservedControlsWidth));
}

function getAutoFitColumnWidth(table, columnIndex) {
    if (!table || columnIndex < 0) return 60;

    const headerCell = table.querySelectorAll('thead th')[columnIndex];
    if (!headerCell || headerCell.classList.contains('row-selector-header')) {
        return 60;
    }

    let maxWidth = getHeaderMinimumWidth(headerCell);

    table.querySelectorAll('tbody tr').forEach(row => {
        const cell = row.cells[columnIndex];
        if (!cell) return;
        maxWidth = Math.max(maxWidth, measureCellContentWidth(cell, 18));
    });

    return Math.max(60, maxWidth);
}

function getStoredColumnWidths(storageKey) {
    const stored = readJsonStorage(storageKey, {});
    if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return {};

    return Object.fromEntries(
        Object.entries(stored).filter(([, value]) => {
            const width = Number(value);
            return Number.isFinite(width) && width > 0 && width <= MAX_REASONABLE_COLUMN_WIDTH;
        })
    );
}

function syncTableWidthToColumns(table, colgroup) {
    if (!table || !colgroup) return;

    const totalWidth = Array.from(colgroup.children).reduce((sum, col) => {
        const width = parseFloat(col.style.width);
        return sum + (Number.isFinite(width) ? width : 0);
    }, 0);

    const scrollContainer = table.closest('.table-scroll');
    const scrollStyle = scrollContainer ? window.getComputedStyle(scrollContainer) : null;
    const horizontalPadding =
        (parseFloat(scrollStyle?.paddingLeft) || 0) +
        (parseFloat(scrollStyle?.paddingRight) || 0);
    const containerWidth = Math.max(0, (scrollContainer?.clientWidth || 0) - horizontalPadding);
    const resolvedWidth = Math.max(totalWidth, containerWidth, 0);

    if (resolvedWidth > 0) {
        table.style.width = `${Math.ceil(resolvedWidth)}px`;
        table.style.minWidth = `${Math.ceil(containerWidth || resolvedWidth)}px`;
    }
}

function persistColumnWidth(table, colgroup, storageKey, columnName, columnIndex, width) {
    if (!table || !columnName || !colgroup?.children?.[columnIndex]) return;

    colgroup.children[columnIndex].style.width = `${width}px`;
    table.classList.add("user-resized");

    const current = getStoredColumnWidths(storageKey);
    current[columnName] = width;
    writeJsonStorage(storageKey, current);
    syncTableWidthToColumns(table, colgroup);
    syncFrozenColumns(table.id);
}

function syncStoredColumnWidths(tableId) {
    const table = document.getElementById(tableId);
    const storageKey = TABLE_COLUMN_WIDTH_KEYS[tableId];
    if (!table || !storageKey) return;

    const colgroup = ensureColGroup(table);
    const storedWidths = getStoredColumnWidths(storageKey);
    const headers = Array.from(table.querySelectorAll("thead th"));

    headers.forEach((th, index) => {
        const col = colgroup.children[index];
        if (!col) return;

        if (th.classList.contains('row-selector-header')) {
            col.style.width = '40px';
            return;
        }

        const columnName = th.dataset.colName;
        const storedWidth = Number(storedWidths[columnName]);
        const defaultWidth = inferDefaultColumnWidth(tableId, columnName);
        col.style.width = Number.isFinite(storedWidth) && storedWidth > 0
            ? `${storedWidth}px`
            : `${defaultWidth}px`;
    });

    syncTableWidthToColumns(table, colgroup);
}

function initColumnResize(tableId, storageKey) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const colgroup = ensureColGroup(table);
    syncStoredColumnWidths(tableId);

    Array.from(table.querySelectorAll("thead th")).forEach(th => {
        if (th.classList.contains('row-selector-header')) return;
        if (th.querySelector(".col-resizer")) return;

        const handle = document.createElement("div");
        handle.className = "col-resizer";
        th.appendChild(handle);

        let startX = 0;
        let startW = 0;
        const MIN_COL_WIDTH = 60;

        const onMove = (e) => {
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const dx = clientX - startX;
            const newW = Math.max(MIN_COL_WIDTH, startW + dx);
            const currentIndex = Array.from(th.parentElement.children).indexOf(th);
            persistColumnWidth(table, colgroup, storageKey, th.dataset.colName, currentIndex, newW);
        };

        const onUp = () => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.removeEventListener("touchmove", onMove);
            document.removeEventListener("touchend", onUp);
            table.classList.remove("resizing");
            syncFrozenColumns(table.id);
        };

        const onDown = (e) => {
            e.preventDefault();
            e.stopPropagation();

            startX = e.touches ? e.touches[0].clientX : e.clientX;
            startW = th.getBoundingClientRect().width;

            const currentIndex = Array.from(th.parentElement.children).indexOf(th);
            if (!colgroup.children[currentIndex].style.width) {
                colgroup.children[currentIndex].style.width = `${startW}px`;
            }

            document.addEventListener("mousemove", onMove);
            document.addEventListener("mouseup", onUp);
            document.addEventListener("touchmove", onMove, { passive: false });
            document.addEventListener("touchend", onUp);
            table.classList.add("resizing");
        };

        const onAutoFit = (e) => {
            e.preventDefault();
            e.stopPropagation();

            const currentIndex = Array.from(th.parentElement.children).indexOf(th);
            const autoWidth = getAutoFitColumnWidth(table, currentIndex);
            persistColumnWidth(table, colgroup, storageKey, th.dataset.colName, currentIndex, autoWidth);
        };

        handle.addEventListener("mousedown", onDown);
        handle.addEventListener("touchstart", onDown, { passive: false });
        handle.addEventListener("dblclick", onAutoFit);
    });
}

function ensureColGroup(table) {
    let colgroup = table.querySelector("colgroup");
    
    if (!colgroup) {
        colgroup = document.createElement("colgroup");
        table.insertBefore(colgroup, table.firstChild);
    }
    
    const thCount = table.querySelectorAll("thead th").length;
    const colCount = colgroup.children.length;
    
    if (colCount < thCount) {
        for (let i = colCount; i < thCount; i++) {
            colgroup.appendChild(document.createElement("col"));
        }
    } else if (colCount > thCount) {
        for (let i = colCount; i > thCount; i--) {
            colgroup.removeChild(colgroup.lastChild);
        }
    }
    
    return colgroup;
}

// ========= 3. DRAG-DROP
let dragState = {
    columnIndex: null,
    table: null,
    dropPosition: 'before'
};

const DRAG_EVENTS = [
    'dragstart', 'dragover', 'drop', 'dragend', 'dragenter', 'dragleave'
];

const TABLE_MAP = {
    'standard-table': {
        columnOrder: () => currentColumnOrderDf1,
        setColumnOrder: (order) => { currentColumnOrderDf1 = order; },
        storageKey: 'columnOrderDf1',
        defaultOrder: DF1_COLUMNS_ORDER,
        renderFn: renderStandardData,
        currentData: () => currentDisplayedDf1
    },
    'extended-table': {
        columnOrder: () => currentColumnOrderDf2,
        setColumnOrder: (order) => { currentColumnOrderDf2 = order; },
        storageKey: 'columnOrderDf2',
        defaultOrder: DF2_COLUMNS_ORDER,
        renderFn: renderExtendedData,
        currentData: () => currentDisplayedDf2
    },
    'traditional-table': {
        columnOrder: () => currentColumnOrderDf3,
        setColumnOrder: (order) => { currentColumnOrderDf3 = order; },
        storageKey: 'columnOrderDf3',
        defaultOrder: DF3_COLUMNS_ORDER,
        renderFn: renderTraditionalData,
        currentData: () => currentDisplayedDf3
    }
};

// ==== 3.1. OPERATION
function initTableColumnDragDrop() {
    console.log('🎯 Initializing column drag & drop...');
    Object.keys(TABLE_MAP).forEach(initTableHeaderDrag);
}

function initTableHeaderDrag(tableId) {
    const table = document.getElementById(tableId);
    if (!table) {
        console.warn(`Table ${tableId} not found`);
        return;
    }
    
    const headers = table.querySelectorAll('thead th[data-col-name]');
    console.log(`📋 Found ${headers.length} headers in ${tableId}`);
    
    headers.forEach((header, index) => {
        setupHeaderDragDrop(header, index);
    });
    
    console.log(`✅ Drag & drop initialized for ${tableId}`);
}

function setupHeaderDragDrop(header, index) {
    header.setAttribute('draggable', 'true');
    header.dataset.columnIndex = index;
    header.style.cursor = 'move';
    
    if (!header.querySelector('.drag-indicator')) {
        const dragIndicator = document.createElement('span');
        dragIndicator.className = 'drag-indicator';
        header.insertBefore(dragIndicator, header.firstChild);
    }
    
    // Remove and re-add all event listeners
    DRAG_EVENTS.forEach(event => {
        header.removeEventListener(event, DRAG_HANDLERS[event]);
        header.addEventListener(event, DRAG_HANDLERS[event]);
    });
}

function getDragDropPosition(header, event) {
    const rect = header?.getBoundingClientRect?.();
    if (!rect) return 'before';

    const clientX = event?.clientX ?? 0;
    return clientX >= rect.left + (rect.width / 2) ? 'after' : 'before';
}

function clearDragOverState(table) {
    table?.querySelectorAll('thead th').forEach(header => {
        header.classList.remove('drag-over', 'drag-over-before', 'drag-over-after');
    });
}

function applyDragOverState(header, position) {
    const table = header?.closest('table');
    if (!table || !header) return;

    clearDragOverState(table);
    header.classList.add('drag-over');
    header.classList.add(position === 'after' ? 'drag-over-after' : 'drag-over-before');
}

const DRAG_HANDLERS = {
    dragstart: function(e) {
        if (e.target?.closest('.column-menu-trigger, .col-resizer')) {
            e.preventDefault();
            return false;
        }

        dragState.columnIndex = parseInt(this.dataset.columnIndex);
        dragState.table = this.closest('table');
        dragState.dropPosition = 'before';
        
        console.log(`🎬 Drag start: column ${dragState.columnIndex}`);
        
        this.style.opacity = '0.4';
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/html', this.innerHTML);
        
        dragState.table.classList.add('column-dragging');
    },
    
    dragover: function(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        if (this.closest('table') === dragState.table) {
            const dropPosition = getDragDropPosition(this, e);
            dragState.dropPosition = dropPosition;
            applyDragOverState(this, dropPosition);
        }
        return false;
    },
    
    dragenter: function(e) {
        if (this.closest('table') === dragState.table && 
            parseInt(this.dataset.columnIndex) !== dragState.columnIndex) {
            const dropPosition = getDragDropPosition(this, e);
            dragState.dropPosition = dropPosition;
            applyDragOverState(this, dropPosition);
        }
    },
    
    dragleave: function() {
        this.classList.remove('drag-over', 'drag-over-before', 'drag-over-after');
    },
    
    drop: function(e) {
        e.stopPropagation();
        
        const dropIndex = parseInt(this.dataset.columnIndex);
        const dropPosition = getDragDropPosition(this, e);
        dragState.dropPosition = dropPosition;
        console.log(`📍 Drop: from ${dragState.columnIndex} to ${dropIndex} (${dropPosition})`);
        
        if (this.closest('table') === dragState.table && 
            dragState.columnIndex !== dropIndex) {
            reorderTableColumns(dragState.table, dragState.columnIndex, dropIndex, dropPosition);
        }
        
        return false;
    },
    
    dragend: function() {
        this.style.opacity = '1';
        console.log('🏁 Drag end');
        
        if (dragState.table) {
            clearDragOverState(dragState.table);
            dragState.table.classList.remove('column-dragging');
        }
        
        dragState = { columnIndex: null, table: null, dropPosition: 'before' };
    }
};

// ==== 3.2. REORDER & UPDATE
let currentFilteredDf1 = [];
let currentFilteredDf2 = [];
let currentFilteredDf3 = [];

function getVisibleColumnOrder(tableId) {
    const config = TABLE_MAP[tableId];
    if (!config) return [];

    const hiddenColumns = hiddenColumnsState[tableId] || new Set();
    return config.columnOrder().filter(columnName => !hiddenColumns.has(columnName));
}

function mergeVisibleOrderIntoFullOrder(fullOrder, visibleOrder, hiddenColumns) {
    const nextVisible = [...visibleOrder];
    return fullOrder.map(columnName => (
        hiddenColumns.has(columnName) ? columnName : nextVisible.shift()
    ));
}

function getTableScopeKey(tableId) {
    if (tableId === 'extended-table') return 'df2';
    if (tableId === 'traditional-table') return 'df3';
    return 'df1';
}

const TABLE_QUERY_GROUPS = RESULT_TABLE_GROUPS;

function getCanonicalColumnField(tableId, columnName) {
    const group = TABLE_QUERY_GROUPS[tableId];
    const contractFields = advancedSearchContract?.groups?.[group]?.fields || [];
    const fieldNames = new Set(contractFields.map(field => field.name));
    const candidates = getColumnFieldCandidates(columnName);
    if (TABLE_DEFAULT_COLUMNS[tableId]?.includes(columnName)) return columnName;
    if (!contractFields.length) return candidates.find(candidate => candidate !== columnName) || null;
    const direct = candidates.find(candidate => fieldNames.has(candidate));
    if (direct) return direct;

    const labelMatch = contractFields.find(field => field.label === columnName);
    return labelMatch?.name || null;
}

function getColumnFilterStateKey(tableId, columnName) {
    const safeColumnName = String(columnName || '');
    return getCanonicalColumnField(tableId, safeColumnName) || safeColumnName;
}

function getColumnFilterStateKeys(state, tableId, columnName) {
    const canonical = getColumnFilterStateKey(tableId, columnName);
    return Object.keys(state || {}).filter(key => (
        key === columnName
        || key === canonical
        || getColumnFilterStateKey(tableId, key) === canonical
    ));
}

function replaceColumnFilterState(state, tableId, columnName, value) {
    const canonical = getColumnFilterStateKey(tableId, columnName);
    getColumnFilterStateKeys(state, tableId, columnName).forEach(key => delete state[key]);
    if (value !== undefined) state[canonical] = value;
    return canonical;
}

function getColumnTextFilterEntries(tableId) {
    const entries = new Map();
    Object.entries(columnTextFilterState[tableId] || {}).forEach(([columnName, rule]) => {
        entries.set(getColumnFilterStateKey(tableId, columnName), rule);
    });
    return entries;
}

function getColumnTextFilterRule(tableId, columnName) {
    return getColumnTextFilterEntries(tableId).get(getColumnFilterStateKey(tableId, columnName));
}

function getColumnValueFilterEntries(tableId) {
    const entries = new Map();
    Object.entries(columnValueFilterState[tableId] || {}).forEach(([columnName, values]) => {
        entries.set(getColumnFilterStateKey(tableId, columnName), values);
    });
    return entries;
}

function getColumnValueFilter(tableId, columnName) {
    return getColumnValueFilterEntries(tableId).get(getColumnFilterStateKey(tableId, columnName));
}

function areColumnValueSetsEqual(left, right) {
    if (!(left instanceof Set) || !(right instanceof Set)) return left === right;
    if (left.size !== right.size) return false;
    const normalizedRight = new Set(Array.from(right, normalizeColumnFilterValue));
    return Array.from(left, normalizeColumnFilterValue)
        .every(value => normalizedRight.has(value));
}

function getWorkingSetData(tableId) {
    if (!workingSetAvailable[tableId]) return [];
    if (tableId === 'extended-table') return orderedWorkingDf2 || baseWorkingDf2 || serverBaseDf2;
    if (tableId === 'traditional-table') return orderedWorkingDf3 || baseWorkingDf3 || serverBaseDf3;
    return orderedWorkingDf1 || baseWorkingDf1 || serverBaseDf1;
}

function normalizeColumnFilterValue(value) {
    return String(value ?? '').trim().toLocaleLowerCase('vi');
}

function normalizeColumnTextFilterRule(rule) {
    if (!rule || typeof rule !== 'object') return null;
    const operator = TEXT_FILTER_OPERATORS.has(rule.operator) ? rule.operator : 'equals';
    const secondOperator = TEXT_FILTER_OPERATORS.has(rule.secondOperator)
        ? rule.secondOperator
        : 'equals';
    const value = String(rule.value ?? '');
    const secondValue = String(rule.secondValue ?? '');
    const isCustom = Boolean(rule.custom || rule.secondOperator || rule.secondValue);
    if (!isCustom && !TEXT_FILTER_OPERATORS.has(rule.operator)) return null;
    return {
        operator,
        value,
        logic: rule.logic === 'or' ? 'or' : 'and',
        ...(isCustom ? { custom: true, secondOperator, secondValue } : {})
    };
}

function escapeTextFilterRegex(value) {
    return String(value).replace(/[\\^$.*+?()[\]{}|]/g, '\\$&');
}

function textFilterPattern(value) {
    let pattern = '';
    for (const character of normalizeColumnFilterValue(value)) {
        if (character === '*') pattern += '.*';
        else if (character === '?') pattern += '.';
        else pattern += escapeTextFilterRegex(character);
    }
    return pattern;
}

function matchesColumnTextFilterCondition(value, operator, query) {
    const candidate = normalizeColumnFilterValue(value);
    const target = normalizeColumnFilterValue(query);
    const hasWildcard = /[*?]/.test(target);
    if (!hasWildcard) {
        switch (operator) {
            case 'equals': return candidate === target;
            case 'notEquals': return candidate !== target;
            case 'beginsWith': return candidate.startsWith(target);
            case 'endsWith': return candidate.endsWith(target);
            case 'contains': return candidate.includes(target);
            case 'notContains': return !candidate.includes(target);
            default: return true;
        }
    }

    const pattern = textFilterPattern(target);
    const matches = (source) => new RegExp(source).test(candidate);
    switch (operator) {
        case 'equals': return matches(`^${pattern}$`);
        case 'notEquals': return !matches(`^${pattern}$`);
        case 'beginsWith': return matches(`^${pattern}`);
        case 'endsWith': return matches(`${pattern}$`);
        case 'contains': return matches(pattern);
        case 'notContains': return !matches(pattern);
        default: return true;
    }
}

function matchesColumnTextFilter(rawValues, rule) {
    const normalizedRule = normalizeColumnTextFilterRule(rule);
    if (!normalizedRule) return true;
    const values = Array.isArray(rawValues) ? rawValues : [rawValues];
    const firstMatch = values.some(value => matchesColumnTextFilterCondition(
        value,
        normalizedRule.operator,
        normalizedRule.value
    ));
    if (!normalizedRule.custom || !String(normalizedRule.secondValue || '').trim()) return firstMatch;

    const secondMatch = values.some(value => matchesColumnTextFilterCondition(
        value,
        normalizedRule.secondOperator,
        normalizedRule.secondValue
    ));
    return normalizedRule.logic === 'or'
        ? firstMatch || secondMatch
        : firstMatch && secondMatch;
}

function getColumnRawValues(tableId, columnName, row) {
    const canonical = getCanonicalColumnField(tableId, columnName);
    const candidates = [...new Set([
        ...getColumnFieldCandidates(canonical),
        ...getColumnFieldCandidates(columnName)
    ].filter(Boolean))];
    const rawValue = candidates
        .map(field => row?.[field])
        .find(value => value !== undefined && value !== null && value !== '');
    if (Array.isArray(rawValue)) return rawValue.map(value => String(value ?? '').trim());
    return [rawValue === undefined || rawValue === null ? '' : String(rawValue).trim()];
}

function getFilteredWorkingSet(tableId, excludedColumnName = null) {
    const filters = getColumnValueFilterEntries(tableId);
    const textFilters = getColumnTextFilterEntries(tableId);
    const excludedKey = excludedColumnName === null
        ? null
        : getColumnFilterStateKey(tableId, excludedColumnName);
    return getWorkingSetData(tableId).filter(row => {
        const matchesValues = Array.from(filters.entries()).every(([columnName, selectedValues]) => {
            if (getColumnFilterStateKey(tableId, columnName) === excludedKey || !(selectedValues instanceof Set)) return true;
            const selected = new Set(Array.from(selectedValues, normalizeColumnFilterValue));
            return getColumnRawValues(tableId, columnName, row)
                .some(value => selected.has(normalizeColumnFilterValue(value)));
        });
        if (!matchesValues) return false;

        return Array.from(textFilters.entries()).every(([columnName, rule]) => (
            columnName === excludedKey
                || matchesColumnTextFilter(getColumnRawValues(tableId, columnName, row), rule)
        ));
    });
}

function getBoundedColumnValueOptions(tableId, columnName) {
    if (!workingSetAvailable[tableId]) return [];
    const counts = new Map();
    getFilteredWorkingSet(tableId, columnName).forEach(row => {
        const seenInRow = new Set();
        getColumnRawValues(tableId, columnName, row).forEach(rawValue => {
            const value = String(rawValue || '').trim();
            const key = normalizeColumnFilterValue(value);
            if (seenInRow.has(key)) return;
            seenInRow.add(key);
            const current = counts.get(key) || { value, count: 0 };
            current.count += 1;
            counts.set(key, current);
        });
    });
    return Array.from(counts.values()).sort((left, right) =>
        left.value.localeCompare(right.value, 'vi', { numeric: true, sensitivity: 'base' })
    );
}

function collectColumnFiltersForUrl() {
    const grouped = {};
    Object.keys(TABLE_QUERY_GROUPS).forEach(tableId => {
        const group = TABLE_QUERY_GROUPS[tableId];
        const scoped = {};
        const valueFilters = getColumnValueFilterEntries(tableId);
        const textFilters = getColumnTextFilterEntries(tableId);
        const columnNames = new Set([...valueFilters.keys(), ...textFilters.keys()]);
        columnNames.forEach(columnName => {
            const values = valueFilters.get(getColumnFilterStateKey(tableId, columnName));
            const textRule = normalizeColumnTextFilterRule(
                textFilters.get(getColumnFilterStateKey(tableId, columnName))
            );
            if (!(values instanceof Set) && !textRule) return;
            const canonical = getCanonicalColumnField(tableId, columnName);
            if (!canonical) return;
            const serializedValues = values instanceof Set ? Array.from(values) : null;
            if (serializedValues && textRule) {
                scoped[canonical] = { values: serializedValues, text: textRule };
            } else if (serializedValues) {
                scoped[canonical] = serializedValues;
            } else {
                scoped[canonical] = { text: textRule };
            }
        });
        if (Object.keys(scoped).length) grouped[group] = scoped;
    });
    return grouped;
}

function restoreColumnFiltersFromRequest(queryRequest = {}) {
    Object.keys(columnValueFilterState).forEach(tableId => {
        columnValueFilterState[tableId] = {};
        columnTextFilterState[tableId] = {};
    });

    const raw = queryRequest?.columnFilters;
    if (!raw || typeof raw !== 'object') return;
    const groupKeys = new Set(Object.values(TABLE_QUERY_GROUPS));
    const isGrouped = Object.keys(raw).some(key => groupKeys.has(key) || key === 'traditional_medicine');
    const requestedGroup = queryRequest?.group === 'traditional_medicine'
        ? 'traditional'
        : queryRequest?.group;
    const grouped = isGrouped ? raw : {
        [TABLE_QUERY_GROUPS[Object.keys(TABLE_QUERY_GROUPS).find(tableId =>
            TABLE_QUERY_GROUPS[tableId] === requestedGroup
        ) || 'standard-table']]: raw
    };

    Object.entries(grouped).forEach(([group, columns]) => {
        if (!columns || typeof columns !== 'object') return;
        const tableId = Object.keys(TABLE_QUERY_GROUPS).find(id =>
            TABLE_QUERY_GROUPS[id] === group
            || (group === 'traditional_medicine' && TABLE_QUERY_GROUPS[id] === 'traditional')
        );
        if (!tableId) return;
        Object.entries(columns).forEach(([canonical, filter]) => {
            const values = Array.isArray(filter) ? filter : filter?.values;
            const textRule = normalizeColumnTextFilterRule(
                Array.isArray(filter) ? null : filter?.text || filter
            );
            const columnName = (TABLE_DEFAULT_COLUMNS[tableId] || [])
                .find(name => getCanonicalColumnField(tableId, name) === canonical);
            if (!columnName) return;
            if (Array.isArray(values)) replaceColumnFilterState(
                columnValueFilterState[tableId], tableId, columnName, new Set(values.map(String))
            );
            if (textRule) replaceColumnFilterState(
                columnTextFilterState[tableId], tableId, columnName, textRule
            );
        });
    });
}

function getDisplayedData(tableId) {
    if (tableId === 'extended-table') return currentDisplayedDf2;
    if (tableId === 'traditional-table') return currentDisplayedDf3;
    return currentDisplayedDf1;
}

function getExportData(tableId) {
    return workingSetAvailable[tableId]
        ? getFilteredWorkingSet(tableId)
        : getDisplayedData(tableId);
}

function getInsightChartData(tableId, displayedData) {
    // Charts summarize the complete filtered working set, not only the page
    // currently rendered in the table.
    const data = workingSetAvailable[tableId]
        ? getFilteredWorkingSet(tableId)
        : displayedData;
    return Array.isArray(data) ? data : [];
}

function getInsightChartDataSets() {
    return {
        df1: getInsightChartData('standard-table', currentFilteredDf1),
        df2: getInsightChartData('extended-table', currentFilteredDf2),
        df3: getInsightChartData('traditional-table', currentFilteredDf3)
    };
}

function getWorkingSetPage(tableId, page) {
    const rows = getFilteredWorkingSet(tableId);
    const pageSize = Math.max(1, Math.min(Number(currentQueryRequest?.limit || 50), 250));
    const offset = Math.max(0, (Math.max(1, Number(page || 1)) - 1) * pageSize);
    return {
        rows: rows.slice(offset, offset + pageSize),
        total: rows.length,
        hasMore: offset + pageSize < rows.length
    };
}

function refreshBoundedWorkingSetViews({ page = currentQueryRequest?.page || 1, resetScroll = true, redrawCharts = true } = {}) {
    const nextPage = Math.max(1, Number(page || 1));
    const df1 = getWorkingSetPage('standard-table', nextPage);
    const df2 = getWorkingSetPage('extended-table', nextPage);
    const df3 = getWorkingSetPage('traditional-table', nextPage);

    currentQueryRequest = buildQueryRequest(currentQueryRequest, { page: nextPage });
    currentQueryMeta.page = nextPage;
    currentQueryMeta.df1Displayed = df1.rows.length;
    currentQueryMeta.df1WorkingCount = df1.total;
    currentQueryMeta.df1HasMore = df1.hasMore;
    currentQueryMeta.df2Displayed = df2.rows.length;
    currentQueryMeta.df2WorkingCount = df2.total;
    currentQueryMeta.df2HasMore = df2.hasMore;
    currentQueryMeta.df3Displayed = df3.rows.length;
    currentQueryMeta.df3WorkingCount = df3.total;
    currentQueryMeta.df3HasMore = df3.hasMore;
    currentFilteredDf1 = df1.rows;
    currentFilteredDf2 = df2.rows;
    currentFilteredDf3 = df3.rows;

    refreshRenderedTables({ resetScroll, redrawCharts });
    updateLegacyPagination();
}

function updateColumnOrder(table) {
    const config = TABLE_MAP[table.id];
    if (!config) return;
    
    const visibleHeaders = Array.from(table.querySelectorAll('thead th[data-col-name]'));
    const reorderedVisible = visibleHeaders
        .map(header => header.dataset.colName)
        .filter(Boolean);

    const hiddenColumns = hiddenColumnsState[table.id] || new Set();
    const fullOrder = config.columnOrder();
    const expectedVisibleCount = fullOrder.filter(columnName => !hiddenColumns.has(columnName)).length;

    if (reorderedVisible.length !== expectedVisibleCount) {
        console.error(`❌ ${table.id}: So luong cot hien thi khong khop, khong luu localStorage`);
        return;
    }

    const mergedOrder = mergeVisibleOrderIntoFullOrder(fullOrder, reorderedVisible, hiddenColumns);
    config.setColumnOrder(mergedOrder);
    localStorage.setItem(config.storageKey, JSON.stringify(mergedOrder));
    console.log(`✅ Cập nhật thứ tự cột ${table.id}:`, mergedOrder);
}

function reorderTableColumns(table, fromIndex, toIndex, dropPosition = 'before') {
    console.log(`🔄 Reordering columns: ${fromIndex} → ${toIndex} (${dropPosition})`);
    
    const theadRow = table.querySelector('thead tr');
    if (!theadRow) return;
    
    const visibleHeaders = Array.from(theadRow.querySelectorAll('th[data-col-name]'));
    if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= visibleHeaders.length ||
        toIndex >= visibleHeaders.length
    ) {
        return;
    }

    const draggedHeader = visibleHeaders[fromIndex];
    const targetHeader = visibleHeaders[toIndex];
    if (!draggedHeader || !targetHeader || draggedHeader === targetHeader) return;

    draggedHeader.remove();

    if (dropPosition === 'after') {
        theadRow.insertBefore(draggedHeader, targetHeader.nextElementSibling);
    } else {
        theadRow.insertBefore(draggedHeader, targetHeader);
    }
    
    // Update column indices
    theadRow.querySelectorAll('th[data-col-name]').forEach((h, idx) => {
        h.dataset.columnIndex = idx;
    });
    
    updateColumnOrder(table);
    
    console.log(`🔄 Re-rendering ${table.id} with new order`);
    refreshHeaderStructure({ resetScroll: false, redrawCharts: false });
}

function syncHeadersWithLocalStorage() {
    console.log('🔄 Syncing headers with localStorage...');
    
    Object.entries(TABLE_MAP).forEach(([tableId, config]) => {
        const table = document.getElementById(tableId);
        if (!table) return;
        
        const thead = table.querySelector('thead tr');
        if (!thead) return;

        thead.replaceChildren();
        const selectorTh = document.createElement('th');
        selectorTh.className = 'row-selector-header';
        selectorTh.textContent = 'STT';
        thead.appendChild(selectorTh);
        
        getVisibleColumnOrder(tableId).forEach((colName, index) => {
            const th = createHeaderCell(tableId, colName, index);
            thead.appendChild(th);
        });

        ensureColGroup(table);
        syncStoredColumnWidths(tableId);
        initColumnResize(tableId, TABLE_COLUMN_WIDTH_KEYS[tableId]);
        initTableHeaderDrag(tableId);
        syncHeaderDecorations(tableId);
        
        console.log(`✅ ${tableId} header synced:`, getVisibleColumnOrder(tableId));
    });
}

function createHeaderCell(tableId, colName, index) {
    const displayLabel = getResultColumnLabel(tableId, colName);
    const th = document.createElement('th');
    th.className = 'px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider bg-gray-100';
    th.setAttribute('draggable', 'true');
    th.dataset.columnIndex = index;
    th.dataset.colName = colName;
    th.style.cursor = 'move';

    const dragIndicator = document.createElement('span');
    dragIndicator.className = 'drag-indicator';
    th.appendChild(dragIndicator);

    const headerInner = document.createElement('div');
    headerInner.className = 'column-header-shell';

    const label = document.createElement('span');
    label.className = 'column-header-label';
    label.textContent = displayLabel;
    headerInner.appendChild(label);

    const sortIndicator = document.createElement('span');
    sortIndicator.className = 'column-sort-indicator';
    sortIndicator.setAttribute('aria-hidden', 'true');
    headerInner.appendChild(sortIndicator);

    const menuTrigger = document.createElement('button');
    menuTrigger.type = 'button';
    menuTrigger.className = 'column-menu-trigger';
    menuTrigger.dataset.tableId = tableId;
    menuTrigger.dataset.colName = colName;
    menuTrigger.setAttribute('aria-label', `Tuy chon cot ${displayLabel}`);
    menuTrigger.setAttribute('aria-haspopup', 'true');
    menuTrigger.setAttribute('aria-expanded', 'false');
    const triggerText = document.createElement('span');
    triggerText.setAttribute('aria-hidden', 'true');
    triggerText.textContent = '▾';
    menuTrigger.appendChild(triggerText);
    headerInner.appendChild(menuTrigger);

    th.appendChild(headerInner);
    
    return th;
}


// ============================== 
// FILTERS
// ============================== 

let currentQueryRequest = {
    scope: 'all',
    filters: {}
};
let currentAppliedPreview = null;
let latestFilterPreview = null;

function getAppliedWorkingSetLimit(tableId = null) {
    const responseLimit = Number(currentQueryMeta.appliedLimitPerScope || 0);
    if (Number.isFinite(responseLimit) && responseLimit > 0) return responseLimit;

    if (tableId === 'standard-table') {
        const inferredLimit = Number(currentQueryMeta.df1WorkingCount || 0);
        return inferredLimit > 0 ? inferredLimit : Number.POSITIVE_INFINITY;
    }
    if (tableId === 'extended-table') {
        const inferredLimit = Number(currentQueryMeta.df2WorkingCount || 0);
        return inferredLimit > 0 ? inferredLimit : Number.POSITIVE_INFINITY;
    }
    if (tableId === 'traditional-table') {
        const inferredLimit = Number(currentQueryMeta.df3WorkingCount || 0);
        return inferredLimit > 0 ? inferredLimit : Number.POSITIVE_INFINITY;
    }
    return Number.POSITIVE_INFINITY;
}

function hasMoreRowsBeyondWorkingSet(tableId) {
    const scopeKey = tableId === 'standard-table'
        ? 'df1'
        : tableId === 'extended-table'
            ? 'df2'
            : tableId === 'traditional-table' ? 'df3' : null;
    if (!scopeKey) return false;

    if (workingSetAvailable[tableId]) {
        // A bounded response is authoritative.  Guard the truncation flag
        // with the actual working-set size so a stale/legacy `has_more` value
        // cannot enable Full Search for a complete 257-row result.
        const workingSetCount = Number(currentQueryMeta[`${scopeKey}WorkingCount`] || 0);
        const workingSetLimit = getAppliedWorkingSetLimit(tableId);
        if (workingSetCount > 0 && Number.isFinite(workingSetLimit) && workingSetCount < workingSetLimit) {
            return false;
        }
        return Boolean(currentQueryMeta[`${scopeKey}WorkingSetTruncated`]);
    }

    // Compatibility path for an older API response that has not yet returned
    // `working_set`.  Never use its page-level `has_more` as the Full Search
    // gate: it describes the visible page, not the Standard working set.
    const rawTotal = Number(currentQueryMeta[`${scopeKey}Total`] || 0);
    if (Number.isFinite(rawTotal)) {
        return rawTotal > getStandardWorkingSetLimitForLegacyResponse();
    }
    return false;
}

function getStandardWorkingSetLimitForLegacyResponse() {
    const reportedLimit = Number(currentQueryMeta.appliedLimitPerScope || 0);
    return Math.max(1000, Number.isFinite(reportedLimit) ? reportedLimit : 0);
}


// ======== 1. APPLY
function buildQueryRequest(baseRequest = {}, overrides = {}) {
    const safeBase = baseRequest && typeof baseRequest === 'object' ? baseRequest : {};

    const request = {
        scope: safeBase.scope || 'all',
        filters: safeBase.filters && typeof safeBase.filters === 'object' ? { ...safeBase.filters } : {},
        ...overrides
    };
    [
        'group', 'sourceTypes', 'text', 'searchFields', 'structuredFilters',
        'ranges', 'dateRanges', 'exactIdentifiers', 'columnFilters', 'sort', 'page', 'limit', 'queryMode', 'crossGroupSearch', 'crossGroupSearchFields'
    ].forEach(key => {
        if (Object.prototype.hasOwnProperty.call(safeBase, key) && !Object.prototype.hasOwnProperty.call(overrides, key)) {
            request[key] = safeBase[key];
        }
    });
    return request;
}

function stableStringify(value) {
    if (Array.isArray(value)) {
        return `[${value.map(stableStringify).join(',')}]`;
    }
    if (value && typeof value === 'object') {
        return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(',')}}`;
    }
    return JSON.stringify(value);
}

function hasActiveQueryFilters(queryRequest) {
    if (!queryRequest || typeof queryRequest !== 'object') return false;

    if (queryRequest.group || String(queryRequest.text || '').trim()) return true;
    if (Array.isArray(queryRequest.sourceTypes) && queryRequest.sourceTypes.length) return true;
    if (Array.isArray(queryRequest.searchFields) && queryRequest.searchFields.length) return true;
    if (queryRequest.structuredFilters && Object.keys(queryRequest.structuredFilters).length) return true;
    if (queryRequest.ranges && Object.keys(queryRequest.ranges).length) return true;
    if (queryRequest.dateRanges && Object.keys(queryRequest.dateRanges).length) return true;
    if (queryRequest.exactIdentifiers && Object.keys(queryRequest.exactIdentifiers).length) return true;
    if (queryRequest.columnFilters && Object.keys(queryRequest.columnFilters).length) return true;
    if (Array.isArray(queryRequest.sort) && queryRequest.sort.length) return true;

    const filters = queryRequest.filters || {};
    return Object.values(filters).some(value => {
        if (value == null) return false;
        if (Array.isArray(value)) return value.length > 0;
        if (typeof value === 'string') return value.trim() !== '';
        if (typeof value === 'object' && Array.isArray(value.tokens)) return value.tokens.length > 0;
        return false;
    });
}

function clearFilterUrlState() {
    const url = new URL(window.location.href);
    url.searchParams.delete('q');
    url.searchParams.delete('bq');
    window.history.replaceState({}, '', url);
}

function clearLegacyBulkUrlState() {
    const url = new URL(window.location.href);
    if (!url.searchParams.has('bq')) return;
    url.searchParams.delete('bq');
    window.history.replaceState({}, '', url);
}

function encodeUrlState(payload) {
    return encodeURIComponent(JSON.stringify(payload));
}

function decodeUrlState(rawValue) {
    if (!rawValue) return null;

    try {
        return JSON.parse(decodeURIComponent(rawValue));
    } catch (error) {
        try {
            return JSON.parse(rawValue);
        } catch (fallbackError) {
            console.warn('Unable to parse URL state:', fallbackError);
            return null;
        }
    }
}

function encodeFilterUrlState(queryRequest) {
    return encodeUrlState(buildQueryRequest(queryRequest));
}

function decodeFilterUrlState(rawValue) {
    const decoded = decodeUrlState(rawValue);
    return decoded ? buildQueryRequest(decoded) : null;
}

function readFilterUrlState() {
    const rawValue = new URL(window.location.href).searchParams.get('q');
    return decodeFilterUrlState(rawValue);
}

function setFilterUrlState(queryRequest) {
    const request = buildQueryRequest(queryRequest);
    if (!hasActiveQueryFilters(request)) {
        clearFilterUrlState();
        return;
    }

    const url = new URL(window.location.href);
    url.searchParams.set('q', encodeFilterUrlState(request));
    url.searchParams.delete('bq');
    window.history.replaceState({ bidfinderFilters: request }, '', url);
}

async function restoreFilterUrlState({ apply = true } = {}) {
    const queryRequest = readFilterUrlState();
    if (!queryRequest || !hasActiveQueryFilters(queryRequest)) return false;

    const searchForm = getProcurementSearchForm();
    if (typeof searchForm?.setFilterPayload === 'function') {
        searchForm.setFilterPayload(queryRequest);
        searchForm.setPreviewResult?.({ loading: true });
    }

    currentQueryRequest = queryRequest;
    restoreColumnFiltersFromRequest(queryRequest);
    if (apply) {
        const result = await applyFilters(queryRequest, { resetMiniFilters: false });
        if (result?.success) {
            const total = Number(result?.total_count || 0);
            searchForm?.setPreviewResult?.({
                total,
                totalLabel: String(result?.total_count_label || total.toLocaleString('vi-VN')),
                exact: result?.total_count_exact !== false
            });
        }
    }

    return true;
}

function getFullSearchQuotaState() {
    const config = window.BIDFinderAuth?.getConfig?.() || {};
    return {
        enabled: config.full_search_enabled !== false,
        limit: Number(config.full_search_daily_limit || 0),
        used: Number(config.full_search_daily_used || 0),
        remaining: Number(config.full_search_daily_remaining || 0),
        message: config.full_search_limit_message || 'Bạn đã dùng hết lượt tìm kiếm mở rộng hôm nay.'
    };
}

function setFullSearchQuotaState({ used, remaining } = {}) {
    const applyAuthConfig = window.BIDFinderAuth?.applyAuthConfig;
    if (typeof applyAuthConfig !== 'function') return;

    applyAuthConfig({
        full_search_daily_used: Math.max(0, Number(used) || 0),
        full_search_daily_remaining: Math.max(0, Number(remaining) || 0)
    });
}

function reserveFullSearchQuota(quota) {
    fullSearchInFlight = true;
    setFullSearchQuotaState({
        used: Number(quota.used || 0) + 1,
        remaining: Number(quota.remaining || 0) - 1
    });
    updateInsightEntryPoint();
}

function releaseFullSearchQuotaReservation() {
    fullSearchInFlight = false;
    updateInsightEntryPoint();
}

function rollbackFullSearchQuota(quota) {
    fullSearchInFlight = false;
    setFullSearchQuotaState(quota);
    updateInsightEntryPoint();
}

async function fetchQueryResults(
    queryRequest,
    sortRule = activeSortRule,
    options = {}
) {
    await window.BIDFinderAuth?.whenReady?.();

    if (!requireAuthenticatedSession('login', 'full_query')) {
        throw new Error(window.BIDFinderAuth?.getFullQueryGateMessage?.() || 'Bạn cần đăng nhập để tìm kiếm dữ liệu.');
    }

    const searchMode = options?.searchMode === 'full' ? 'full' : 'standard';
    window.BIDFinderAnalytics?.trackSearchSubmitted?.(queryRequest, { searchMode });
    document.dispatchEvent(new CustomEvent('bidfinder:query-start', {
        detail: { query: queryRequest, searchMode }
    }));
    const requestBody = {
        scope: queryRequest?.scope || 'all',
        group: queryRequest?.group,
        sourceTypes: queryRequest?.sourceTypes || [],
        filters: queryRequest?.filters || {},
        text: queryRequest?.text || '',
        searchFields: queryRequest?.searchFields || [],
        structuredFilters: queryRequest?.structuredFilters || {},
        ranges: queryRequest?.ranges || {},
        dateRanges: queryRequest?.dateRanges || {},
        exactIdentifiers: queryRequest?.exactIdentifiers || {},
        sort: Array.isArray(queryRequest?.sort) && queryRequest.sort.length
            ? queryRequest.sort
            : buildSortPayload(sortRule),
        // The API treats this as display page size. Standard/Full working-set
        // limits are selected server-side from searchMode.
        limit: Math.max(1, Math.min(Number(queryRequest?.limit || 50), 250)),
        page: Number(queryRequest?.page || 1),
        queryMode: queryRequest?.queryMode || 'search',
        crossGroupSearch: queryRequest?.crossGroupSearch === true,
        crossGroupSearchFields: queryRequest?.crossGroupSearchFields || [],
        searchMode
    };

    const response = await getAuthorizedFetch()(`${API_BASE_URL}/api/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody)
    });

    const payload = await response.json();

    if (!response.ok || payload?.success === false) {
        let message = `HTTP ${response.status}`;
        message = payload?.message || payload?.error || message;
        throw new Error(message);
    }

    if (payload?.auth) {
        window.BIDFinderAuth?.applyAuthConfig?.(payload.auth);
    }

    markDatabaseWarm();
    window.BIDFinderAnalytics?.trackSearchCompleted?.(payload);
    return payload;
}

async function fetchQueryPreview(queryRequest, signal = null) {
    await window.BIDFinderAuth?.whenReady?.();

    if (!requireAuthenticatedSession('login', 'preview')) {
        throw new Error('Bạn cần đăng nhập để tìm kiếm dữ liệu.');
    }

    const response = await getAuthorizedFetch()(`${API_BASE_URL}/api/query-preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            scope: queryRequest?.scope || 'all',
            group: queryRequest?.group,
            sourceTypes: queryRequest?.sourceTypes || [],
            filters: queryRequest?.filters || {},
            text: queryRequest?.text || '',
            searchFields: queryRequest?.searchFields || [],
            structuredFilters: queryRequest?.structuredFilters || {},
            ranges: queryRequest?.ranges || {},
            dateRanges: queryRequest?.dateRanges || {},
            exactIdentifiers: queryRequest?.exactIdentifiers || {},
            crossGroupSearch: queryRequest?.crossGroupSearch === true,
            crossGroupSearchFields: queryRequest?.crossGroupSearchFields || []
        }),
        signal
    });

    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
            const errorPayload = await response.json();
            message = errorPayload?.message || errorPayload?.error || message;
        } catch (e) {
            // Ignore non-JSON error payloads.
        }
        throw new Error(message);
    }

    const payload = await response.json();
    markDatabaseWarm();
    window.BIDFinderAnalytics?.track?.('search_preview_completed', {
        scope: queryRequest?.scope || 'all',
        total_count: Number(payload?.total || 0)
    });
    return payload;
}

let dbWarmupPromise = null;
let dbWarmupReadyUntil = 0;
const DB_WARM_TTL_MS = 4 * 60 * 1000;
const LOADING_CONNECTION_MESSAGE_MS = 700;
const PREVIEW_REQUEST_TIMEOUT_MS = 25000;
const DB_WARMUP_ENABLED = window.BIDFINDER_CONFIG?.dbWarmupEnabled === true;

function markDatabaseWarm() {
    dbWarmupReadyUntil = Date.now() + DB_WARM_TTL_MS;
}

function isDatabaseRecentlyWarm() {
    return Date.now() < dbWarmupReadyUntil;
}

function shouldWarmDatabase() {
    if (!DB_WARMUP_ENABLED) return false;
    const auth = window.BIDFinderAuth;
    if (auth?.requiresDataAuth?.() && !auth?.isAuthenticated?.()) return false;
    return true;
}

function warmupDatabase({ force = false } = {}) {
    if (!shouldWarmDatabase()) return Promise.resolve({ skipped: true });
    if (isDatabaseRecentlyWarm() && !force) return Promise.resolve({ ready: true });
    if (dbWarmupPromise && !force) return dbWarmupPromise;

    const startedAt = performance.now();
    dbWarmupPromise = getAuthorizedFetch()(`${API_BASE_URL}/api/warmup`)
        .then(async response => {
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || payload?.success === false) {
                throw new Error(payload?.message || payload?.error || `HTTP ${response.status}`);
            }
            markDatabaseWarm();
            return {
                ...payload,
                client_elapsed_ms: Math.round(performance.now() - startedAt)
            };
        })
        .catch(error => {
            dbWarmupReadyUntil = 0;
            throw error;
        })
        .finally(() => {
            dbWarmupPromise = null;
        });

    return dbWarmupPromise;
}

async function waitForWarmupWithUi(searchForm, signal = null) {
    if (isDatabaseRecentlyWarm() || !shouldWarmDatabase()) return;
    if (signal?.aborted) return;

    try {
        await warmupDatabase();
    } catch (error) {
        console.warn('Database warmup failed:', error);
    }
}

function startConnectionMessageTimer(searchForm, signal = null) {
    const timer = window.setTimeout(() => {
        if (signal?.aborted) return;
        searchForm?.setPreviewResult?.({ loading: true, warming: true });
    }, LOADING_CONNECTION_MESSAGE_MS);

    return () => window.clearTimeout(timer);
}

function normalizeQueryResult(result) {
    return {
        df1: {
            data: [],
            count: 0,
            count_exact: true,
            count_label: '0',
            count_summary: '0',
            displayed: 0,
            has_more: false,
            approx_total: null,
            working_set: [],
            working_set_count: 0,
            working_set_limit: 0,
            working_set_truncated: false,
            ...(result?.df1 || {})
        },
        df2: {
            data: [],
            count: 0,
            count_exact: true,
            count_label: '0',
            count_summary: '0',
            displayed: 0,
            has_more: false,
            approx_total: null,
            working_set: [],
            working_set_count: 0,
            working_set_limit: 0,
            working_set_truncated: false,
            ...(result?.df2 || {})
        },
        df3: {
            data: [],
            count: 0,
            count_exact: true,
            count_label: '0',
            count_summary: '0',
            displayed: 0,
            has_more: false,
            approx_total: null,
            working_set: [],
            working_set_count: 0,
            working_set_limit: 0,
            working_set_truncated: false,
            ...(result?.df3 || {})
        },
        totalCount: Number(result?.total_count || 0),
        totalCountExact: result?.total_count_exact !== false,
        totalCountLabel: result?.total_count_label || String(Number(result?.total_count || 0)),
        totalCountSummary: result?.total_count_summary || String(Number(result?.total_count || 0)),
        searchMode: result?.search_mode === 'full' ? 'full' : (result?.search_mode === 'bulk' ? 'bulk' : 'standard'),
        bulkSearchMode: result?.bulk?.search_mode === 'full' ? 'full' : 'standard',
        appliedTotalLimit: Number(result?.applied_total_limit || 0),
        appliedLimitPerScope: Number(result?.applied_limit_per_scope || 0)
    };
}

function handleQuerySuccess(result, options = {}) {
    const normalized = normalizeQueryResult(result);
    const nextDf1 = normalized.df1.data || [];
    const nextDf2 = normalized.df2.data || [];
    const nextDf3 = normalized.df3.data || [];
    const hasWorkingDf1 = Array.isArray(result?.df1?.working_set);
    const hasWorkingDf2 = Array.isArray(result?.df2?.working_set);
    const hasWorkingDf3 = Array.isArray(result?.df3?.working_set);
    const workingDf1 = hasWorkingDf1 ? normalized.df1.working_set : nextDf1;
    const workingDf2 = hasWorkingDf2 ? normalized.df2.working_set : nextDf2;
    const workingDf3 = hasWorkingDf3 ? normalized.df3.working_set : nextDf3;

    const totalCount = Number(normalized.totalCount || 0);
    hideLimitWarning();

    if (!hasWorkingDf1 && !hasWorkingDf2 && !hasWorkingDf3) {
        // Keep the Full Search gate in sync even when an older API process
        // returns only the page payload.  Leaving the previous metadata alive
        // makes a complete small result inherit a stale `has_more` state.
        Object.keys(workingSetAvailable).forEach(tableId => {
            workingSetAvailable[tableId] = false;
        });
        Object.assign(currentQueryMeta, {
            df1HasMore: Boolean(normalized.df1.has_more),
            df2HasMore: Boolean(normalized.df2.has_more),
            df3HasMore: Boolean(normalized.df3.has_more),
            df1Displayed: nextDf1.length,
            df1Total: Number(normalized.df1.count || nextDf1.length || 0),
            df1WorkingCount: 0,
            df1WorkingSetTruncated: false,
            df1TotalLabel: String(normalized.df1.count_label || normalized.df1.count_summary || Number(normalized.df1.count || nextDf1.length || 0).toLocaleString('vi-VN')),
            df2Displayed: nextDf2.length,
            df2Total: Number(normalized.df2.count || nextDf2.length || 0),
            df2WorkingCount: 0,
            df2WorkingSetTruncated: false,
            df2TotalLabel: String(normalized.df2.count_label || normalized.df2.count_summary || Number(normalized.df2.count || nextDf2.length || 0).toLocaleString('vi-VN')),
            df3Displayed: nextDf3.length,
            df3Total: Number(normalized.df3.count || nextDf3.length || 0),
            df3WorkingCount: 0,
            df3WorkingSetTruncated: false,
            df3TotalLabel: String(normalized.df3.count_label || normalized.df3.count_summary || Number(normalized.df3.count || nextDf3.length || 0).toLocaleString('vi-VN')),
            page: Number(currentQueryRequest?.page || 1),
            totalCount,
            totalCountExact: Boolean(normalized.totalCountExact),
            totalCountLabel: String(normalized.totalCountLabel || totalCount),
            searchMode: normalized.searchMode,
            bulkSearchMode: normalized.bulkSearchMode,
            appliedTotalLimit: normalized.appliedTotalLimit,
            appliedLimitPerScope: normalized.appliedLimitPerScope
        });
        updateResults(nextDf1, nextDf2, nextDf3, options);
        return;
    }

    baseWorkingDf1 = [...workingDf1];
    baseWorkingDf2 = [...workingDf2];
    baseWorkingDf3 = [...workingDf3];
    serverBaseDf1 = baseWorkingDf1;
    serverBaseDf2 = baseWorkingDf2;
    serverBaseDf3 = baseWorkingDf3;
    orderedWorkingDf1 = [...baseWorkingDf1];
    orderedWorkingDf2 = [...baseWorkingDf2];
    orderedWorkingDf3 = [...baseWorkingDf3];
    workingSetAvailable['standard-table'] = hasWorkingDf1;
    workingSetAvailable['extended-table'] = hasWorkingDf2;
    workingSetAvailable['traditional-table'] = hasWorkingDf3;
    currentQueryMeta = {
        df1HasMore: Boolean(normalized.df1.has_more),
        df2HasMore: Boolean(normalized.df2.has_more),
        df3HasMore: Boolean(normalized.df3.has_more),
        df1Displayed: nextDf1.length,
        df1Total: Number(normalized.df1.count || nextDf1.length || 0),
        df1WorkingCount: workingDf1.length,
        df1WorkingSetTruncated: Boolean(normalized.df1.working_set_truncated),
        df1TotalLabel: String(normalized.df1.count_label || normalized.df1.count_summary || Number(normalized.df1.count || nextDf1.length || 0).toLocaleString('vi-VN')),
        df2Displayed: nextDf2.length,
        df2Total: Number(normalized.df2.count || nextDf2.length || 0),
        df2WorkingCount: workingDf2.length,
        df2WorkingSetTruncated: Boolean(normalized.df2.working_set_truncated),
        df2TotalLabel: String(normalized.df2.count_label || normalized.df2.count_summary || Number(normalized.df2.count || nextDf2.length || 0).toLocaleString('vi-VN')),
        df3Displayed: nextDf3.length,
        df3Total: Number(normalized.df3.count || nextDf3.length || 0),
        df3WorkingCount: workingDf3.length,
        df3WorkingSetTruncated: Boolean(normalized.df3.working_set_truncated),
        df3TotalLabel: String(normalized.df3.count_label || normalized.df3.count_summary || Number(normalized.df3.count || nextDf3.length || 0).toLocaleString('vi-VN')),
        page: Number(currentQueryRequest?.page || 1),
        totalCount,
        totalCountExact: Boolean(normalized.totalCountExact),
        totalCountLabel: String(normalized.totalCountLabel || totalCount),
        searchMode: normalized.searchMode,
        bulkSearchMode: normalized.bulkSearchMode,
        appliedTotalLimit: normalized.appliedTotalLimit,
        appliedLimitPerScope: normalized.appliedLimitPerScope
    };

    if (options.resetMiniFilters !== false) resetMiniFilters();
    refreshBoundedWorkingSetViews({
        page: currentQueryRequest?.page || 1,
        resetScroll: options.resetScroll !== false,
        redrawCharts: true
    });
    selectResultViewWithMostRows();
    document.dispatchEvent(new CustomEvent('bidfinder:query-result', {
        detail: { result, query: currentQueryRequest }
    }));
}


async function applyFilters(payload, options = {}) {
    currentQueryRequest = enrichLegacyQueryRequest(payload);
    closeFloatingTableUi();

    console.log('Applying filters with query request:', currentQueryRequest);

    try {
        const result = await fetchQueryResults(
            currentQueryRequest,
            activeSortRule,
            { searchMode: 'standard' }
        );

        if (result.success) {
            handleQuerySuccess(result, {
                resetMiniFilters: options.resetMiniFilters !== false,
                resetScroll: options.resetScroll !== false
            });
            setFilterUrlState(currentQueryRequest);
            currentAppliedPreview = {
                requestKey: stableStringify(currentQueryRequest),
                payload: getPreviewPayloadForRequest(currentQueryRequest, result)
            };
            return result;
        } else {
            throw new Error(result.error || 'Query failed');
        }
    } catch (err) {
        const authRequired = document.getElementById('auth-modal')?.classList.contains('show') &&
            /đăng nhập/i.test(err?.message || '');
        (authRequired ? console.info : console.error)('Filter failed:', err);
        document.dispatchEvent(new CustomEvent('bidfinder:query-error', {
            detail: { message: err?.message || 'Không tải được kết quả.' }
        }));
        window.BIDFinderAnalytics?.track?.('search_failed', {
            search_mode: 'standard',
            error: err?.message || 'unknown'
        });
        resetQueryResultMeta();
        updateResults([], [], { resetMiniFilters: true });
        hideLimitWarning();
        if (err?.message && !authRequired) {
            alert(err.message);
        }
        return null;
    }
}

async function triggerFullSearch() {
    const quota = getFullSearchQuotaState();
    window.BIDFinderAnalytics?.track?.('full_search_clicked', {
        quota_remaining: quota.remaining,
        quota_limit: quota.limit,
        quota_enabled: quota.enabled
    });
    if (!quota.enabled || quota.remaining <= 0) {
        window.BIDFinderAnalytics?.track?.('quota_limit_reached', {
            feature: 'full_search',
            quota_remaining: quota.remaining,
            quota_limit: quota.limit
        });
        alert(quota.message || 'Bạn đã dùng hết lượt tìm kiếm mở rộng hôm nay.');
        return;
    }

    const quotaSnapshot = {
        used: quota.used,
        remaining: quota.remaining
    };
    reserveFullSearchQuota(quotaSnapshot);
    let serverAccepted = false;

    try {
        if (currentQueryMeta.searchMode === 'bulk' && lastBulkSearchPayloads?.length) {
            const completed = await runBulkSearch({ searchMode: 'full', reuseLastPayloads: true });
            if (completed === false) {
                throw new Error('tìm kiếm hàng loạt thất bại.');
            }
            serverAccepted = true;
            return;
        }

        const result = await fetchQueryResults(
            currentQueryRequest,
            activeSortRule,
            { searchMode: 'full' }
        );
        if (result.success) {
            serverAccepted = true;
            handleQuerySuccess(result, { resetMiniFilters: false });
            return;
        }
        throw new Error(result.error || 'Full search failed');
    } catch (error) {
        updateInsightEntryPoint();
        console.error('Full search failed:', error);
        window.BIDFinderAnalytics?.track?.('search_failed', {
            search_mode: 'full',
            error: error?.message || 'unknown'
        });
        if (error?.message) {
            alert(error.message);
        }
    } finally {
        if (serverAccepted) {
            releaseFullSearchQuotaReservation();
        } else {
            rollbackFullSearchQuota(quotaSnapshot);
        }
    }
}


// Helper: Show limit warning
function showLimitWarning({
    totalCount,
    totalCountExact,
    totalCountLabel,
    displayedCount,
    searchMode = 'standard',
    bulkSearchMode = 'standard',
    fullSearchRemaining = 0,
    fullSearchDailyLimit = 0,
    fullSearchEnabled = true
}) {
    updateInsightEntryPoint();
}

// Helper: Hide limit warning
function hideLimitWarning() {
    updateInsightEntryPoint();
}

function resetQueryResultMeta() {
    serverBaseDf1 = [];
    serverBaseDf2 = [];
    serverBaseDf3 = [];
    baseWorkingDf1 = null;
    baseWorkingDf2 = null;
    baseWorkingDf3 = null;
    orderedWorkingDf1 = null;
    orderedWorkingDf2 = null;
    orderedWorkingDf3 = null;
    Object.keys(workingSetAvailable).forEach(tableId => {
        workingSetAvailable[tableId] = false;
    });
    currentAppliedPreview = null;
    latestFilterPreview = null;
    currentQueryMeta = {
        df1HasMore: false,
        df2HasMore: false,
        df3HasMore: false,
        df1Displayed: 0,
        df1Total: 0,
        df1WorkingCount: 0,
        df1WorkingSetTruncated: false,
        df1TotalLabel: '0',
        df2Displayed: 0,
        df2Total: 0,
        df2WorkingCount: 0,
        df2WorkingSetTruncated: false,
        df2TotalLabel: '0',
        df3Displayed: 0,
        df3Total: 0,
        df3WorkingCount: 0,
        df3WorkingSetTruncated: false,
        df3TotalLabel: '0',
        page: 1,
        totalCount: 0,
        totalCountExact: true,
        totalCountLabel: '0',
        searchMode: 'standard',
        bulkSearchMode: 'standard',
        appliedTotalLimit: 0,
        appliedLimitPerScope: 0
    };
    updateLegacyPagination();
}

function resetMiniFilters(tableId = null) {
    if (tableId) {
        columnValueFilterState[tableId] = {};
        columnTextFilterState[tableId] = {};
        syncHeaderDecorations(tableId);
        return;
    }

    Object.keys(columnValueFilterState).forEach(key => {
        columnValueFilterState[key] = {};
        columnTextFilterState[key] = {};
        syncHeaderDecorations(key);
    });
}

function refreshRenderedTables({ resetScroll = true, redrawCharts = true } = {}) {
    const preservedScrollPositions = resetScroll
        ? []
        : Array.from(
            document.querySelectorAll('#df1-panel .table-scroll, #df2-panel .table-scroll, #df3-panel .table-scroll'),
            container => ({ container, top: container.scrollTop, left: container.scrollLeft })
        );

    // Render the current page from the bounded working set, never from only
    // the last 50 rows returned by the API.
    currentDisplayedDf1 = Array.isArray(currentFilteredDf1) ? currentFilteredDf1 : [];
    currentDisplayedDf2 = Array.isArray(currentFilteredDf2) ? currentFilteredDf2 : [];
    currentDisplayedDf3 = Array.isArray(currentFilteredDf3) ? currentFilteredDf3 : [];

    updateScopeSwitcherCounts(currentDisplayedDf1.length, currentDisplayedDf2.length, currentDisplayedDf3.length);
    updateDuplicateWarning(currentDisplayedDf1, currentDisplayedDf2, currentDisplayedDf3);
    requestAnimationFrame(syncScopeSwitcherSlider);

    renderStandardData(currentDisplayedDf1);
    renderExtendedData(currentDisplayedDf2);
    renderTraditionalData(currentDisplayedDf3);

    if (resetScroll) {
        resetTableScrollPositions();
    } else {
        preservedScrollPositions.forEach(({ container, top, left }) => {
            container.scrollTop = top;
            container.scrollLeft = left;
        });
    }

    if (redrawCharts) {
        insightChartsDirty = true;
        if (isInsightDrawerOpen()) {
            const chartData = getInsightChartDataSets();
            void drawCharts(chartData.df1, chartData.df2, chartData.df3);
        }
    }
}

function getResultTableCountLabel(tableId, fallbackCount = 0) {
    const key = tableId === 'extended-table'
        ? 'df2'
        : tableId === 'traditional-table'
            ? 'df3'
            : 'df1';
    const hasWorkingSet = workingSetAvailable[tableId];
    const workingCount = Number(currentQueryMeta[`${key}WorkingCount`]);
    const serverTotal = Number(currentQueryMeta[`${key}Total`]);
    const fallback = Number(fallbackCount);
    const total = hasWorkingSet
        ? (Number.isFinite(workingCount) ? workingCount : fallback)
        : (Number.isFinite(serverTotal) ? serverTotal : fallback);
    const safeTotal = Math.max(0, Math.floor(Number.isFinite(total) ? total : 0));
    const limit = Number(currentQueryMeta.appliedLimitPerScope || 0);
    const isFullSearch = currentQueryMeta.searchMode === 'full'
        || (currentQueryMeta.searchMode === 'bulk' && currentQueryMeta.bulkSearchMode === 'full');
    const isWorkingSetTruncated = Boolean(currentQueryMeta[`${key}WorkingSetTruncated`]);

    if (limit > 0 && (safeTotal > limit || (isWorkingSetTruncated && safeTotal >= limit))) {
        return `${limit}+`;
    }
    return String(safeTotal);
}

function updateScopeSwitcherCounts(df1Count, df2Count, df3Count = 0) {
    const counts = {
        'df1-panel': Number(currentQueryMeta.df1Displayed || df1Count || 0),
        'df2-panel': Number(currentQueryMeta.df2Displayed || df2Count || 0),
        'df3-panel': Number(currentQueryMeta.df3Displayed || df3Count || 0)
    };
    const tabTotalCounts = {
        'df1-panel': getResultTableCountLabel('standard-table', counts['df1-panel']),
        'df2-panel': getResultTableCountLabel('extended-table', counts['df2-panel']),
        'df3-panel': getResultTableCountLabel('traditional-table', counts['df3-panel'])
    };

    const df1CountEl = document.getElementById('df1-count-switcher');
    const df2CountEl = document.getElementById('df2-count-switcher');
    const df3CountEl = document.getElementById('df3-count-switcher');
    const updateTabCountElement = (element, view) => {
        if (!element) return;
        const label = tabTotalCounts[view];
        const cappedMatch = /^(\d+)\+$/.exec(label);
        if (cappedMatch) {
            element.replaceChildren(
                document.createTextNode(cappedMatch[1]),
                Object.assign(document.createElement('span'), {
                    className: 'scope-count-plus',
                    textContent: '+'
                })
            );
        } else {
            element.textContent = label;
        }
        element.classList.toggle('has-value', label !== '0');
    };
    updateTabCountElement(df1CountEl, 'df1-panel');
    updateTabCountElement(df2CountEl, 'df2-panel');
    updateTabCountElement(df3CountEl, 'df3-panel');

    document.querySelectorAll('.scope-btn').forEach(button => {
        const view = button.getAttribute('data-view');
        const count = counts[view] || 0;
        const countLabel = tabTotalCounts[view] || String(count);
        button.classList.toggle('has-results', count > 0);
        button.classList.toggle('is-empty', count <= 0);
        button.dataset.count = String(count);
        button.setAttribute('aria-label', `${button.querySelector('.scope-text')?.textContent || ''}: ${countLabel} kết quả`);
    });
}

function selectResultViewWithMostRows() {
    const resultCounts = [
        { view: 'df2-panel', count: Number(currentQueryMeta.df2WorkingCount) || currentDisplayedDf2.length },
        { view: 'df1-panel', count: Number(currentQueryMeta.df1WorkingCount) || currentDisplayedDf1.length },
        { view: 'df3-panel', count: Number(currentQueryMeta.df3WorkingCount) || currentDisplayedDf3.length }
    ];
    const largestCount = Math.max(...resultCounts.map(({ count }) => count));
    if (largestCount <= 0) return;

    const activeView = document.querySelector('.scope-btn.active')?.getAttribute('data-view');
    if (resultCounts.some(({ view, count }) => view === activeView && count === largestCount)) return;

    const largestResult = resultCounts.find(({ count }) => count === largestCount);
    if (largestResult) activateResultView(largestResult.view);
}

function updateResults(df1, df2, df3 = [], options = {}) {
    if (typeof df3 === 'object' && !Array.isArray(df3)) {
        options = df3;
        df3 = [];
    }
    currentFilteredDf1 = Array.isArray(df1) ? df1 : [];
    currentFilteredDf2 = Array.isArray(df2) ? df2 : [];
    currentFilteredDf3 = Array.isArray(df3) ? df3 : [];

    if (options.resetMiniFilters) {
        closeColumnMenu();
        resetMiniFilters();
    }

    refreshRenderedTables({
        resetScroll: options.resetScroll !== false,
        redrawCharts: options.redrawCharts !== false
    });

    selectResultViewWithMostRows();
}

function updateDuplicateWarning(df1Rows, df2Rows, df3Rows = []) {
    const warningDiv = document.getElementById('duplicate-warning');
    if (!warningDiv) return;

    const duplicateCount = [...(df1Rows || []), ...(df2Rows || []), ...(df3Rows || [])]
        .filter(row => Boolean(row?.__has_duplicate_warning))
        .length;

    if (duplicateCount <= 0) {
        warningDiv.style.display = 'none';
        setInfoBannerMessage(
            warningDiv,
            'Cảnh báo dữ liệu trùng',
            'Có dòng trùng trong kết quả hiện tại.'
        );
        return;
    }

    setInfoBannerMessage(
        warningDiv,
        'Cảnh báo dữ liệu trùng',
        `Có ${duplicateCount.toLocaleString('vi-VN')} dòng trùng trong kết quả hiện tại.`
    );
    warningDiv.style.display = 'block';
}

function resetTableScrollPositions() {
    document.querySelectorAll('#df1-panel .table-scroll, #df2-panel .table-scroll, #df3-panel .table-scroll').forEach(container => {
        container.scrollTop = 0;
        container.scrollLeft = 0;
    });
}

// ======== 2. PANELS
const PANEL_CONFIG = {
    filter: {
        panel: 'filter-panel',
        openBtn: 'open-filter-panel',
        closeBtn: 'close-filter-panel',
        onOpen: null
    }
};

function initPanels() {
    const overlay = document.getElementById('panel-overlay');
    if (!overlay) {
        console.warn('⚠️ Overlay element not found');
        return;
    }

    const panels = Object.entries(PANEL_CONFIG).map(([key, config]) => 
        initPanel(config, overlay)
    ).filter(Boolean);

    if (panels.length === 0) {
        console.warn('⚠️ No panels initialized');
        return;
    }

    // Close all panels on overlay click
    overlay.addEventListener('click', () => {
        hideAllPanels();
    });

    console.log('✅ Panels initialized');
}

function initPanel(config, overlay) {
    const panel = document.getElementById(config.panel);
    const openBtn = document.getElementById(config.openBtn);
    const closeBtn = document.getElementById(config.closeBtn);

    if (!panel) return null;

    if (openBtn) {
        openBtn.addEventListener('click', () => {
            showPanel(config.panel);
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            hideAllPanels();
        });
    }

    return { panel, openBtn, closeBtn };
}

function showPanel(panelId) {
    const panel = document.getElementById(panelId);
    const overlay = document.getElementById('panel-overlay');
    if (!panel || !overlay) return;

    hideAllPanels();
    closeFloatingTableUi();
    panel.classList.add('show');
    overlay.classList.add('show');

    if (panelId === 'filter-panel') {
        const searchForm = getProcurementSearchForm();
        if (typeof searchForm?.activatePane === 'function') {
            const paneKey = typeof searchForm.getPreferredPaneForOpen === 'function'
                ? searchForm.getPreferredPaneForOpen()
                : 'active-ing';
            searchForm.activatePane(paneKey || 'active-ing', { focus: false });
        }
        restoreAppliedFilterPreview(searchForm);

        requestAnimationFrame(() => {
            focusActiveFilterField();
            setTimeout(() => focusActiveFilterField(), 80);
        });
    }
}

function getAppliedPreviewPayload() {
    if (!hasActiveQueryFilters(currentQueryRequest)) return null;
    if (currentAppliedPreview?.payload) return currentAppliedPreview.payload;

    return {
        total: Number(currentQueryMeta.totalCount || 0),
        totalLabel: String(currentQueryMeta.totalCountLabel || Number(currentQueryMeta.totalCount || 0).toLocaleString('vi-VN')),
        exact: currentQueryMeta.totalCountExact !== false
    };
}

function buildResultPreviewPayload(result) {
    const total = Number(result?.total_count || 0);
    return {
        total,
        totalLabel: String(result?.total_count_label || total.toLocaleString('vi-VN')),
        exact: result?.total_count_exact !== false
    };
}

function getPreviewPayloadForRequest(queryRequest, fallbackResult = null) {
    const requestKey = stableStringify(buildQueryRequest(queryRequest));
    if (latestFilterPreview?.requestKey === requestKey && latestFilterPreview?.payload) {
        return latestFilterPreview.payload;
    }
    return fallbackResult ? buildResultPreviewPayload(fallbackResult) : null;
}

function restoreAppliedFilterPreview(searchForm) {
    if (!searchForm || typeof searchForm.setPreviewResult !== 'function') return;
    if (typeof searchForm.collectFilterPayload !== 'function') return;

    const formRequest = buildQueryRequest(searchForm.collectFilterPayload());
    const appliedRequest = buildQueryRequest(currentQueryRequest);
    const sameFilters = stableStringify(formRequest) === stableStringify(appliedRequest);
    const previewPayload = sameFilters ? getAppliedPreviewPayload() : null;

    if (previewPayload) {
        searchForm.setPreviewResult(previewPayload);
    }
}

function hideAllPanels() {
    ['filter-panel', 'panel-overlay'].forEach(id => {
        document.getElementById(id)?.classList.remove('show');
    });
}

function closeTransientUi() {
    hideAllPanels();
    closeInsightDrawer();
    closeFloatingTableUi();
    ['history-modal', 'readme-modal', 'contact-modal'].forEach(id => {
        document.getElementById(id)?.classList.remove('show');
    });
}

function focusSearchFormPrimaryInput() {
    const searchForm = getProcurementSearchForm();
    const root = searchForm?.shadowRoot;
    if (!root) return;

    const primaryInput = root.querySelector(
        '.filter-pane.active .token-input-container input, ' +
        '.filter-pane.active .field input, ' +
        '.filter-pane.active select, ' +
        '.token-input-container input, .field input, select'
    );

    if (primaryInput) {
        primaryInput.focus();
        primaryInput.select?.();
    }
}

function focusActiveFilterField() {
    const searchForm = getProcurementSearchForm();
    if (!searchForm) return;

    if (typeof searchForm.focusActiveField === 'function') {
        searchForm.focusActiveField();
        return;
    }

    focusSearchFormPrimaryInput();
}

function initGlobalKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        const key = e.key?.toLowerCase();

        if ((e.ctrlKey || e.metaKey) && key === 'f') {
            e.preventDefault();
            showPanel('filter-panel');
            return;
        }

        if (e.key === 'Escape') {
            closeTransientUi();
        }
    });
}

function initLandingShell() {
    const landingShell = document.getElementById('landing-shell');
    const enterButtons = [
        document.getElementById('enter-app-btn'),
        document.getElementById('enter-app-btn-hero'),
        document.getElementById('enter-app-btn-bottom')
    ].filter(Boolean);
    const homeTrigger = document.getElementById('app-home-trigger');
    if (!landingShell || enterButtons.length === 0) return;

    const applyLandingView = (view) => {
        sessionStorage.setItem('bidfinder:view', view);
        document.body.classList.toggle('landing-active', view === 'landing');
        requestAnimationFrame(() => {
            syncScopeSwitcherSlider();
            updateInsightEntryPoint();
        });
    };

    const syncLandingView = (view) => {
        if (document.startViewTransition) {
            document.startViewTransition(() => applyLandingView(view));
            return;
        }
        applyLandingView(view);
    };

    const hasSharedQueryUrl = hasActiveQueryFilters(readFilterUrlState());
    const currentView = sessionStorage.getItem('bidfinder:view') || (hasSharedQueryUrl ? 'app' : 'landing');
    const canOpenSavedApp =
        (currentView === 'app' || hasSharedQueryUrl) &&
        (
            window.BIDFinderAuth?.isAuthenticated() ||
            !window.BIDFinderAuth?.requiresDataAuth?.()
        );
    applyLandingView(canOpenSavedApp ? 'app' : 'landing');

    const enterApp = () => {
        const mustLogin = window.BIDFinderAuth?.requiresDataAuth?.();
        window.BIDFinderAnalytics?.track?.('enter_app_clicked', {
            auth_required: Boolean(mustLogin),
            authenticated: Boolean(window.BIDFinderAuth?.isAuthenticated?.())
        });

        if (mustLogin && !window.BIDFinderAuth?.isAuthenticated()) {
            window.BIDFinderAuth?.requestIntent('enter-app');
            window.BIDFinderAuth?.openAuthModal('register');
            return;
        }

        syncLandingView('app');
        window.BIDFinderAnalytics?.page?.({ view: 'app' });
        initializeAppData();
    };

    const goLanding = () => {
        if (isInsightDrawerOpen()) closeInsightDrawer();
        syncLandingView('landing');
        window.BIDFinderAnalytics?.page?.({ view: 'landing' });
        landingShell.scrollTo({ top: 0, behavior: 'smooth' });
    };

    enterButtons.forEach(btn => btn.addEventListener('click', enterApp));
    homeTrigger?.addEventListener('click', goLanding);

    document.addEventListener('keydown', (e) => {
        const tagName = e.target?.tagName || '';
        const isTypingContext = ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(tagName);
        const authModalOpen = document.getElementById('auth-modal')?.classList.contains('show');

        if (document.body.classList.contains('landing-active') && e.key === 'Enter' && !isTypingContext && !authModalOpen) {
            enterApp();
        }
    });

    window.addEventListener('bidfinder:auth-ready', (event) => {
        const authed = Boolean(event.detail?.authenticated);
        const savedView = sessionStorage.getItem('bidfinder:view') || 'landing';
        const hasSharedQueryUrl = hasActiveQueryFilters(readFilterUrlState());
        const mustLogin = Boolean(event.detail?.config?.require_auth_for_data_access);

        if (mustLogin && !authed) {
            applyLandingView('landing');
            return;
        }

        const nextView = savedView === 'app' || hasSharedQueryUrl ? 'app' : 'landing';
        applyLandingView(nextView);
        if (nextView === 'app') {
            initializeAppData();
        }
    });

    window.addEventListener('bidfinder:auth-changed', (event) => {
        const authed = Boolean(event.detail?.authenticated);
        const intent = event.detail?.intent;
        const reason = event.detail?.reason;
        const mustLogin = window.BIDFinderAuth?.requiresDataAuth?.();

        if (authed) {
            if (intent === 'enter-app') {
                syncLandingView('app');
            }

            if ((sessionStorage.getItem('bidfinder:view') || 'landing') === 'app' || intent === 'enter-app') {
                initializeAppData();
            }
            return;
        }

        if (reason === 'logout') {
            metadata = null;
            appDataInitialized = false;
            currentQueryRequest = { scope: 'all', filters: {} };
            clearFilterUrlState();
            resetQueryResultMeta();
            hideLimitWarning();
            updateResults([], [], { resetMiniFilters: true });
            initEmptyCharts();
            syncLandingView('landing');
            return;
        }

        if (!mustLogin) {
            metadata = null;
            appDataInitialized = false;
            if ((sessionStorage.getItem('bidfinder:view') || 'landing') === 'app') {
                initializeAppData();
            }
            return;
        }

        metadata = null;
        appDataInitialized = false;
        currentQueryRequest = { scope: 'all', filters: {} };
        resetQueryResultMeta();
        hideLimitWarning();
        updateResults([], [], { resetMiniFilters: true });
        initEmptyCharts();
        syncLandingView('landing');
    });
}

function initFilterHelpExternalTooltip() {
    const helpBtn = document.getElementById("filter-help-btn");
    const contentEl = document.getElementById("filter-help-tooltip-content");
    if (!helpBtn || !contentEl) return;

    let externalTooltip = null;
    let pinnedOpen = false;

    injectTooltipStyles();

    const positionTooltip = () => {
        if (!externalTooltip) return;

        const rect = helpBtn.getBoundingClientRect();
        const tooltipWidth = externalTooltip.offsetWidth || 420;
        const margin = 12;
        const desiredLeft = rect.left + (rect.width / 2) - (tooltipWidth / 2);
        const maxLeft = Math.max(margin, window.innerWidth - tooltipWidth - margin);
        const left = Math.max(margin, Math.min(desiredLeft, maxLeft));

        externalTooltip.style.top = `${rect.bottom + 8}px`;
        externalTooltip.style.left = `${left}px`;
    };

    const showTooltip = ({ pinned = false } = {}) => {
        if (!externalTooltip) {
            externalTooltip = createTooltip(helpBtn, contentEl);
            document.body.appendChild(externalTooltip);
        }

        pinnedOpen = pinned || pinnedOpen;
        helpBtn.setAttribute("aria-expanded", pinnedOpen ? "true" : "false");
        positionTooltip();
    };

    const hideTooltip = (force = false) => {
        if (!force && pinnedOpen) return;
        if (externalTooltip) {
            externalTooltip.remove();
            externalTooltip = null;
        }
        pinnedOpen = false;
        helpBtn.setAttribute("aria-expanded", "false");
    };

    const openPinnedTooltip = () => {
        showTooltip({ pinned: true });
        helpBtn.focus({ preventScroll: true });
    };

    window.BIDFinderOpenFilterHelp = openPinnedTooltip;

    helpBtn.addEventListener("mouseenter", () => showTooltip());
    helpBtn.addEventListener("mouseleave", () => hideTooltip());
    helpBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();

        if (externalTooltip && pinnedOpen) {
            hideTooltip(true);
            return;
        }

        openPinnedTooltip();
    });

    document.addEventListener("click", (e) => {
        if (!externalTooltip || !pinnedOpen) return;
        if (helpBtn.contains(e.target) || externalTooltip.contains(e.target)) return;
        hideTooltip(true);
    });

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") hideTooltip(true);
    });

    document.addEventListener("bidfinder:open-filter-help", () => {
        openPinnedTooltip();
    });

    window.addEventListener("resize", positionTooltip);
    window.addEventListener("scroll", positionTooltip, true);
}

function injectTooltipStyles() {
    const styleId = "external-tooltip-style-filter-help";
    if (document.getElementById(styleId)) return;

    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = `
        .external-tooltip {
            position: fixed;
            background: #ffffff;
            border: 1px solid #cfe0ea;
            border-radius: 10px;
            padding: 16px 18px;
            width: 420px;
            max-width: 90vw;
            box-shadow: 0 18px 36px rgba(16, 34, 48, 0.14);
            z-index: 999999;
            font-family: Inter, sans-serif;
        }
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
        .external-tooltip li:last-child {
            margin-bottom: 0;
        }
        .external-tooltip li::before {
            content: "•";
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
            font-family: 'Courier New', monospace;
            font-size: 11px;
            color: #0f5b77;
            font-weight: 600;
        }
    `;
    document.head.appendChild(style);
}

function setInfoBannerMessage(target, title, message) {
    if (!target) return;

    target.replaceChildren();

    const strong = document.createElement('strong');
    strong.textContent = title;
    target.appendChild(strong);
    target.appendChild(document.createElement('br'));
    target.appendChild(document.createTextNode(message));
}

function createTooltip(targetElement, contentNode) {
    const tooltip = document.createElement("div");
    tooltip.className = "external-tooltip";
    if (contentNode) {
        Array.from(contentNode.childNodes).forEach((child) => {
            tooltip.appendChild(child.cloneNode(true));
        });
    }

    const rect = targetElement.getBoundingClientRect();
    tooltip.style.top = `${rect.bottom + 8}px`;
    tooltip.style.left = `${rect.left + rect.width / 2 - 210}px`;

    return tooltip;
}

// ============================== 
// SORT
// ============================== 
const SORTABLE_COLUMNS = {
    logical: [
        { key: 'ma_tbmt', label: 'Mã TBMT' },
        { key: 'investor', label: 'Chủ đầu tư' },
        { key: 'approvalDecision', label: 'Quyết định phê duyệt' },
        { key: 'approvalDate', label: 'Ngày phê duyệt' },
        { key: 'expiryDate', label: 'Ngày hết hiệu lực' },
        { key: 'unit', label: 'Đơn vị tính' },
        { key: 'quantity', label: 'Số lượng' },
        { key: 'unitPrice', label: 'Đơn giá trúng thầu (VND)' },
        { key: 'amount', label: 'Thành tiền (VND)' },
        { key: 'drugName', label: 'Tên thuốc' },
        { key: 'lotName', label: 'Tên phần/lô' },
        { key: 'activeIngredient', label: 'Tên hoạt chất' },
        { key: 'strength', label: 'Nồng độ, hàm lượng' },
        { key: 'route', label: 'Đường dùng' },
        { key: 'dosageForm', label: 'Dạng bào chế' },
        { key: 'packaging', label: 'Quy cách' },
        { key: 'drugGroup', label: 'Nhóm thuốc' },
        { key: 'license', label: 'GĐKLH hoặc GPNK' },
        { key: 'bidItem', label: 'Mặt hàng dự thầu' },
        { key: 'brand', label: 'Nhãn hiệu' },
        { key: 'model', label: 'Ký mã hiệu' },
        { key: 'technicalSpec', label: 'Tính năng kỹ thuật' },
        { key: 'manufacturer', label: 'Cơ sở sản xuất' },
        { key: 'origin', label: 'Xuất xứ' },
        { key: 'winner', label: 'Nhà thầu trúng thầu' },
        { key: 'method', label: 'Hình thức LCNT' },
        { key: 'place', label: 'Địa điểm' },
        { key: 'validity', label: 'Tình trạng hiệu lực' }
    ],
    physical: {
        df1: {
            ma_tbmt: 'bid_invitation_code',
            investor: 'procuring_entity_name',
            approvalDecision: 'decision_number',
            approvalDate: 'decision_issued_at',
            unit: 'unit',
            quantity: 'quantity',
            unitPrice: 'winning_unit_price',
            drugName: 'medicine_name',
            activeIngredient: 'active_ingredient_or_herbal_component',
            strength: 'strength',
            route: 'route_of_administration',
            dosageForm: 'dosage_form',
            packaging: 'packaging',
            drugGroup: 'medicine_group',
            license: 'marketing_authorization_or_import_permit',
            manufacturer: 'manufacturer',
            origin: 'production_country',
            winner: 'winning_bidder_name',
            method: 'selection_method',
            place: 'location'
        },
        df2: {
            ma_tbmt: 'bid_invitation_code',
            investor: 'procuring_entity_name',
            approvalDecision: 'decision_number',
            approvalDate: 'decision_issued_at',
            unit: 'unit',
            quantity: 'quantity',
            unitPrice: 'winning_unit_price',
            drugName: 'item_name',
            brand: 'brand',
            model: 'model_mark',
            technicalSpec: 'technical_specification',
            manufacturer: 'manufacturer',
            origin: 'country_of_origin',
            winner: 'winning_bidder_name',
            method: 'selection_method',
            place: 'location'
        },
        df3: {
            ma_tbmt: 'bid_invitation_code',
            investor: 'procuring_entity_name',
            approvalDecision: 'decision_number',
            approvalDate: 'decision_issued_at',
            unit: 'unit',
            quantity: 'quantity',
            unitPrice: 'winning_unit_price',
            drugName: 'item_name',
            activeIngredient: 'scientific_name',
            route: 'processing_method',
            packaging: 'packaging',
            drugGroup: 'technical_group',
            license: 'registration_or_import_permit_number',
            manufacturer: 'manufacturer',
            origin: 'origin',
            winner: 'winning_bidder_name',
            method: 'selection_method',
            place: 'location'
        }
    }
};
const LOCAL_NUMERIC_SORT_KEYS = new Set(['quantity', 'unitPrice', 'amount']);
const LOCAL_DATE_SORT_KEYS = new Set(['approvalDate', 'expiryDate']);
const LOCAL_VALIDITY_SORT_ORDER = {
    'Hết hiệu lực': 0,
    'Chưa xác định': 1,
    'Còn hiệu lực': 2
};

// Typesense only accepts fields declared as sortable in the public contract.
// Other visible columns stay sortable on the bounded working set instead of
// sending an unsupported sort rule to /api/query.
const TYPESENSE_SORT_FIELD_BY_LOGICAL = {
    approvalDate: 'partition_date',
    quantity: 'quantity',
    unitPrice: 'winning_unit_price',
    productionYear: 'production_year',
    bidderCount: 'bidder_count'
};
const TYPESENSE_SORTABLE_LOGICAL_FALLBACK = {
    df1: new Set(['approvalDate', 'quantity', 'unitPrice', 'bidderCount']),
    df2: new Set(['approvalDate', 'quantity', 'unitPrice', 'productionYear', 'bidderCount']),
    df3: new Set(['approvalDate', 'quantity', 'unitPrice', 'bidderCount'])
};

let activeColumnMenuState = null;
let activeColumnsPopoverState = null;

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderFeatherIcon(name, className = 'menu-inline-icon') {
    return window.feather?.icons?.[name]?.toSvg({
        class: className,
        width: 14,
        height: 14,
        'stroke-width': 2
    }) || '';
}

function createFeatherIconElement(name, className = 'menu-inline-icon') {
    const icon = document.createElement('i');
    icon.setAttribute('data-feather', name);
    icon.className = className;
    return icon;
}

function finalizeDynamicMarkup(root) {
    if (!root || !window.feather?.replace) return;
    window.feather.replace();
}

function encodeColumnName(columnName) {
    return encodeURIComponent(columnName || '');
}

function decodeColumnName(encoded) {
    try {
        return decodeURIComponent(encoded || '');
    } catch (error) {
        return encoded || '';
    }
}

function getSortLabelForScope(sortKey, scopeKey) {
    const override = SORTABLE_COLUMNS.physical[scopeKey]?.[sortKey];
    if (override) return override;
    return SORTABLE_COLUMNS.logical.find(item => item.key === sortKey)?.label || '';
}

function getLogicalSortKeyForColumn(tableId, columnName) {
    const scopeKey = getTableScopeKey(tableId);
    const match = SORTABLE_COLUMNS.logical.find(item => getSortLabelForScope(item.key, scopeKey) === columnName);
    return match?.key || null;
}

function getSortStateForColumn(tableId, columnName) {
    const logicalKey = getLogicalSortKeyForColumn(tableId, columnName);
    if (!logicalKey || activeSortRule?.column !== logicalKey) return null;
    return activeSortRule.order;
}

function buildSortPayload(sortRule = activeSortRule) {
    if (!sortRule?.column || !sortRule?.order) return null;
    return [sortRule];
}

function getSortTargetTableIds() {
    const scope = currentQueryRequest?.scope || 'all';
    if (scope === 'medicine') return ['standard-table'];
    if (scope === 'goods') return ['extended-table'];
    if (scope === 'traditional') return ['traditional-table'];
    return ['standard-table', 'extended-table', 'traditional-table'];
}

function isTypesenseSortSupported(sortRule = activeSortRule) {
    if (!sortRule?.column) return true;

    const fieldName = TYPESENSE_SORT_FIELD_BY_LOGICAL[sortRule.column];
    if (!fieldName) return false;

    return getSortTargetTableIds().every(tableId => {
        const scopeKey = getTableScopeKey(tableId);
        const group = TABLE_QUERY_GROUPS[tableId];
        const contractFields = advancedSearchContract?.groups?.[group]?.fields;
        if (!Array.isArray(contractFields) || !contractFields.length) {
            return TYPESENSE_SORTABLE_LOGICAL_FALLBACK[scopeKey]?.has(sortRule.column) === true;
        }

        return contractFields.some(field => field.name === fieldName && field.sortable === true);
    });
}

function shouldUseClientSideSort() {
    if (currentQueryMeta.searchMode === 'bulk') {
        return true;
    }
    if (activeSortRule && !isTypesenseSortSupported(activeSortRule)) {
        return true;
    }
    const scope = currentQueryRequest?.scope || 'all';
    if (scope === 'all') {
        return !currentQueryMeta.df1HasMore && !currentQueryMeta.df2HasMore && !currentQueryMeta.df3HasMore;
    }
    if (scope === 'medicine') {
        return !currentQueryMeta.df1HasMore;
    }
    if (scope === 'goods') {
        return !currentQueryMeta.df2HasMore;
    }
    if (scope === 'traditional') {
        return !currentQueryMeta.df3HasMore;
    }
    return false;
}

function parseLocalSortDate(value) {
    const raw = String(value || '').trim();
    if (!raw) return Number.NaN;
    if (/^\d{2}\/\d{2}\/\d{4}$/.test(raw)) {
        const [day, month, year] = raw.split('/').map(Number);
        return new Date(year, month - 1, day).getTime();
    }

    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? Number.NaN : parsed.getTime();
}

function parseLocalSortValue(value, logicalKey) {
    if (value === null || value === undefined || value === '') {
        return { empty: true, value: null };
    }

    if (LOCAL_NUMERIC_SORT_KEYS.has(logicalKey)) {
        const numeric = Number(value);
        return { empty: Number.isNaN(numeric), value: numeric };
    }

    if (LOCAL_DATE_SORT_KEYS.has(logicalKey)) {
        const dateValue = parseLocalSortDate(value);
        return { empty: Number.isNaN(dateValue), value: dateValue };
    }

    if (logicalKey === 'validity') {
        const mapped = LOCAL_VALIDITY_SORT_ORDER[String(value).trim()];
        return {
            empty: mapped === undefined,
            value: mapped ?? -1
        };
    }

    return {
        empty: false,
        value: String(value).trim().toLowerCase()
    };
}

function compareLocalSortEntries(leftRow, rightRow, logicalKey, scopeKey, order, leftIndex, rightIndex) {
    const label = getSortLabelForScope(logicalKey, scopeKey);
    if (!label) return leftIndex - rightIndex;

    const logicalLabel = SORTABLE_COLUMNS.logical.find(item => item.key === logicalKey)?.label;
    const aliases = logicalLabel ? (LEGACY_FIELD_ALIASES[logicalLabel] || []) : [];
    const candidates = [label, ...aliases];
    const leftParsed = parseLocalSortValue(getFirstRawColumnValue(leftRow, candidates), logicalKey);
    const rightParsed = parseLocalSortValue(getFirstRawColumnValue(rightRow, candidates), logicalKey);

    if (leftParsed.empty && rightParsed.empty) return leftIndex - rightIndex;
    if (leftParsed.empty) return 1;
    if (rightParsed.empty) return -1;

    let comparison = 0;
    if (typeof leftParsed.value === 'number' && typeof rightParsed.value === 'number') {
        comparison = leftParsed.value - rightParsed.value;
    } else {
        comparison = String(leftParsed.value).localeCompare(
            String(rightParsed.value),
            'vi',
            { numeric: true, sensitivity: 'base' }
        );
    }

    if (comparison === 0) {
        return leftIndex - rightIndex;
    }

    return order === 'asc' ? comparison : -comparison;
}

function sortRowsLocally(rows, scopeKey, sortRule = activeSortRule) {
    if (!Array.isArray(rows)) return [];
    if (!sortRule?.column || !sortRule?.order) return [...rows];

    return rows
        .map((row, index) => ({ row, index }))
        .sort((left, right) => compareLocalSortEntries(
            left.row,
            right.row,
            sortRule.column,
            scopeKey,
            sortRule.order,
            left.index,
            right.index
        ))
        .map(item => item.row);
}

function applyClientSideSort({ preserveMiniFilters = true } = {}) {
    const sourceDf1 = serverBaseDf1.length ? serverBaseDf1 : currentFilteredDf1;
    const sourceDf2 = serverBaseDf2.length ? serverBaseDf2 : currentFilteredDf2;
    const sourceDf3 = serverBaseDf3.length ? serverBaseDf3 : currentFilteredDf3;
    orderedWorkingDf1 = activeSortRule ? sortRowsLocally(sourceDf1, 'df1', activeSortRule) : null;
    orderedWorkingDf2 = activeSortRule ? sortRowsLocally(sourceDf2, 'df2', activeSortRule) : null;
    orderedWorkingDf3 = activeSortRule ? sortRowsLocally(sourceDf3, 'df3', activeSortRule) : null;

    if (!preserveMiniFilters) {
        closeColumnMenu();
        resetMiniFilters();
    }

    if (Object.values(workingSetAvailable).some(Boolean)) {
        refreshBoundedWorkingSetViews({ resetScroll: false, redrawCharts: true });
    } else {
        if (activeSortRule) {
            currentFilteredDf1 = orderedWorkingDf1 || [];
            currentFilteredDf2 = orderedWorkingDf2 || [];
            currentFilteredDf3 = orderedWorkingDf3 || [];
        }
        refreshRenderedTables({
            resetScroll: false,
            redrawCharts: true
        });
    }
    syncAllHeaderDecorations();
}

function getTableWrapper(tableId) {
    return document.querySelector(`.table-wrapper[data-table-id="${tableId}"]`);
}

function getColumnMenuTrigger(tableId, columnName) {
    return document.querySelector(
        `.column-menu-trigger[data-table-id="${tableId}"][data-col-name="${CSS.escape(columnName)}"]`
    );
}

function positionFloatingLayer(wrapper, anchor, floating) {
    if (!wrapper || !anchor || !floating) return;

    const wrapperRect = wrapper.getBoundingClientRect();
    const anchorRect = anchor.getBoundingClientRect();
    const floatingWidth = floating.offsetWidth || 260;
    const maxLeft = Math.max(12, wrapper.clientWidth - floatingWidth - 12);
    const columnHeaderRect = floating.classList.contains('column-menu-popover')
        ? anchor.closest('th')?.getBoundingClientRect()
        : null;
    const preferredLeft = columnHeaderRect
        ? columnHeaderRect.left - wrapperRect.left
        : anchorRect.right - wrapperRect.left - floatingWidth;
    const left = Math.max(12, Math.min(preferredLeft, maxLeft));
    const top = Math.max(54, anchorRect.bottom - wrapperRect.top + 8);

    floating.style.left = `${left}px`;
    floating.style.top = `${top}px`;
}

function syncFloatingWrapperState() {
    document.querySelectorAll('.table-wrapper').forEach(wrapper => {
        const isActive =
            activeColumnMenuState?.wrapper === wrapper ||
            activeColumnsPopoverState?.wrapper === wrapper;
        wrapper.classList.toggle('table-tools-open', Boolean(isActive));
    });
}

function syncHeaderDecorations(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const wrappedColumns = wrappedColumnsState[tableId] || new Set();
    const pinnedColumns = frozenColumnsState[tableId] || new Set();

    table.querySelectorAll('thead th[data-col-name]').forEach(th => {
        const columnName = th.dataset.colName;
        const sortState = getSortStateForColumn(tableId, columnName);
        const hasValueFilter = getColumnValueFilter(tableId, columnName) instanceof Set;
        const hasTextFilter = Boolean(getColumnTextFilterRule(tableId, columnName));
        const hasMiniFilter = hasValueFilter || hasTextFilter;
        const isWrapped = wrappedColumns.has(columnName);
        const isPinned = pinnedColumns.has(columnName);

        th.dataset.sortState = sortState || '';
        th.classList.toggle('has-mini-filter', hasMiniFilter);
        th.classList.toggle('is-wrapped-col', isWrapped);
        th.classList.toggle('is-pinned-col', isPinned);

        const indicator = th.querySelector('.column-sort-indicator');
        if (indicator) {
            indicator.textContent = sortState === 'asc' ? '↑' : sortState === 'desc' ? '↓' : '';
        }

        const trigger = th.querySelector('.column-menu-trigger');
        if (trigger) {
            trigger.classList.toggle('is-active', Boolean(sortState || hasMiniFilter || isWrapped || isPinned));
        }
    });
}

function syncAllHeaderDecorations() {
    Object.keys(TABLE_MAP).forEach(syncHeaderDecorations);
}

function refreshHeaderStructure(options = {}) {
    closeColumnMenu();
    syncHeadersWithLocalStorage();
    refreshRenderedTables(options);
}

async function applyActiveSortRule({ preserveMiniFilters = true } = {}) {
    const hasFilter = hasActiveQueryFilters(currentQueryRequest);
    const hasData = (currentFilteredDf1?.length || 0) > 0
        || (currentFilteredDf2?.length || 0) > 0
        || (currentFilteredDf3?.length || 0) > 0;

    if (!hasFilter && !hasData) {
        syncAllHeaderDecorations();
        return;
    }

    if (shouldUseClientSideSort()) {
        applyClientSideSort({ preserveMiniFilters });
        return;
    }

    try {
        const result = await fetchQueryResults(
            currentQueryRequest,
            activeSortRule,
            { searchMode: currentQueryMeta.searchMode }
        );
        if (result.success) {
            handleQuerySuccess(result, {
                resetMiniFilters: !preserveMiniFilters,
                resetScroll: false
            });
        } else {
            throw new Error(result.error || 'Sort failed');
        }
    } catch (error) {
        console.error('Server sort failed:', error);
        if (error?.message) {
            alert(error.message);
        }
    }
}

async function applySortForColumn(tableId, columnName, order) {
    const logicalKey = getLogicalSortKeyForColumn(tableId, columnName);
    if (!logicalKey) return;

    activeSortRule = { column: logicalKey, order };
    persistSortRule(activeSortRule);
    syncAllHeaderDecorations();
    await applyActiveSortRule({ preserveMiniFilters: true });
}

async function clearActiveSortRule() {
    activeSortRule = null;
    persistSortRule(null);
    syncAllHeaderDecorations();
    await applyActiveSortRule({ preserveMiniFilters: true });
}

function toggleWrappedColumn(tableId, columnName) {
    const wrappedColumns = wrappedColumnsState[tableId];
    if (!wrappedColumns) return;

    if (wrappedColumns.has(columnName)) wrappedColumns.delete(columnName);
    else wrappedColumns.add(columnName);

    persistColumnSet(STORAGE_KEYS.wrappedColumns, tableId, wrappedColumns);
    syncWrappedColumns(tableId);
    syncHeaderDecorations(tableId);
}

function togglePinnedColumn(tableId, columnName) {
    const pinnedColumns = frozenColumnsState[tableId];
    if (!pinnedColumns) return;

    if (pinnedColumns.has(columnName)) pinnedColumns.delete(columnName);
    else pinnedColumns.add(columnName);

    persistColumnSet(STORAGE_KEYS.frozenColumns, tableId, pinnedColumns);
    syncFrozenColumns(tableId);
    syncHeaderDecorations(tableId);
}

function autosizeTableColumn(tableId, columnName) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const header = table.querySelector(`thead th[data-col-name="${CSS.escape(columnName)}"]`);
    if (!header) return;

    const columnIndex = Array.from(header.parentElement.children).indexOf(header);
    const storageKey = TABLE_COLUMN_WIDTH_KEYS[tableId];
    const colgroup = ensureColGroup(table);
    const autoWidth = getAutoFitColumnWidth(table, columnIndex);
    persistColumnWidth(table, colgroup, storageKey, columnName, columnIndex, autoWidth);
}

function setTableColumnVisibility(tableId, columnName, shouldShow) {
    const hiddenColumns = hiddenColumnsState[tableId];
    if (!hiddenColumns) return false;

    const visibleColumns = getVisibleColumnOrder(tableId);
    if (!shouldShow && visibleColumns.length <= 1 && visibleColumns.includes(columnName)) {
        alert('Cần giữ lại ít nhất một cột đang hiển thị.');
        return false;
    }

    if (shouldShow) hiddenColumns.delete(columnName);
    else hiddenColumns.add(columnName);

    selectionState[tableId]?.columns.delete(columnName);
    persistColumnSet(STORAGE_KEYS.hiddenColumns, tableId, hiddenColumns);
    refreshHeaderStructure({ resetScroll: false, redrawCharts: false });
    return true;
}

function closeColumnMenu() {
    if (!activeColumnMenuState) return;

    activeColumnMenuState.menu?.remove();
    activeColumnMenuState.trigger?.classList.remove('is-open');
    activeColumnMenuState.trigger?.setAttribute('aria-expanded', 'false');
    activeColumnMenuState = null;
    syncFloatingWrapperState();
}

function createColumnMenuActionButton({
    action,
    tableId,
    columnName,
    icon,
    label,
    isActive = false,
    isSecondary = false,
    isDanger = false
}) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'column-menu-action';
    if (isActive) button.classList.add('is-active');
    if (isSecondary) button.classList.add('is-secondary');
    if (isDanger) button.classList.add('is-danger');
    button.dataset.action = action;
    button.dataset.tableId = tableId;
    button.dataset.columnName = encodeColumnName(columnName);
    button.appendChild(createFeatherIconElement(icon, 'column-menu-icon'));

    const span = document.createElement('span');
    span.textContent = label;
    button.appendChild(span);
    return button;
}

function getDistinctColumnValues(tableId, columnName) {
    return getBoundedColumnValueOptions(tableId, columnName)
        .map(option => option.value)
        .sort((a, b) => a.localeCompare(b, 'vi', { numeric: true, sensitivity: 'base' }));
}

function createTextFilterOperatorSelect(className) {
    const select = document.createElement('select');
    select.className = className;
    select.setAttribute(
        'aria-label',
        className.endsWith('-1') ? 'Điều kiện lọc văn bản' : 'Điều kiện lọc văn bản thứ hai'
    );
    Object.entries(TEXT_FILTER_OPERATOR_LABELS).forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label.toLocaleLowerCase('vi');
        select.appendChild(option);
    });
    return select;
}

function createColumnTextFilterPanel(tableId, columnName) {
    const currentRule = normalizeColumnTextFilterRule(getColumnTextFilterRule(tableId, columnName));
    const panel = document.createElement('div');
    panel.className = 'column-text-filter-panel';
    panel.hidden = true;
    panel.setAttribute('role', 'group');
    panel.setAttribute('aria-label', 'Bộ lọc văn bản');

    const options = document.createElement('div');
    options.className = 'column-text-filter-options';
    [
        ['equals', 'Bằng...'],
        ['notEquals', 'Không bằng...'],
        ['beginsWith', 'Bắt đầu bằng...'],
        ['endsWith', 'Kết thúc bằng...'],
        ['contains', 'Chứa...'],
        ['notContains', 'Không chứa...'],
        ['custom', 'Bộ lọc tùy chỉnh...']
    ].forEach(([operator, label]) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'column-text-filter-option';
        button.dataset.operator = operator;
        button.textContent = label;
        options.appendChild(button);
    });

    if (currentRule) {
        const clearButton = document.createElement('button');
        clearButton.type = 'button';
        clearButton.className = 'column-text-filter-clear';
        clearButton.dataset.action = 'clear-text-filter';
        clearButton.dataset.tableId = tableId;
        clearButton.dataset.columnName = encodeColumnName(columnName);
        clearButton.textContent = 'Bỏ lọc văn bản';
        options.appendChild(clearButton);
    }

    const editor = document.createElement('div');
    editor.className = 'column-text-filter-editor';
    editor.hidden = true;
    editor.dataset.tableId = tableId;
    editor.dataset.columnName = encodeColumnName(columnName);

    const firstRow = document.createElement('div');
    firstRow.className = 'column-text-filter-row';
    const firstOperator = createTextFilterOperatorSelect('column-text-filter-operator-1');
    const firstValue = document.createElement('input');
    firstValue.type = 'text';
    firstValue.className = 'column-text-filter-value-1';
    firstValue.placeholder = 'Nhập giá trị';
    firstValue.setAttribute('aria-label', 'Giá trị lọc văn bản');
    firstValue.autocomplete = 'off';
    firstRow.append(firstOperator, firstValue);
    editor.appendChild(firstRow);

    const logicRow = document.createElement('div');
    logicRow.className = 'column-text-filter-logic';
    logicRow.innerHTML = `
        <label><input type="radio" name="column-text-filter-logic-${tableId}-${encodeColumnName(columnName)}" value="and" checked> Và</label>
        <label><input type="radio" name="column-text-filter-logic-${tableId}-${encodeColumnName(columnName)}" value="or"> Hoặc</label>
    `;
    editor.appendChild(logicRow);

    const secondRow = document.createElement('div');
    secondRow.className = 'column-text-filter-row column-text-filter-second-row';
    const secondOperator = createTextFilterOperatorSelect('column-text-filter-operator-2');
    const secondValue = document.createElement('input');
    secondValue.type = 'text';
    secondValue.className = 'column-text-filter-value-2';
    secondValue.placeholder = 'Nhập giá trị';
    secondValue.setAttribute('aria-label', 'Giá trị lọc văn bản thứ hai');
    secondValue.autocomplete = 'off';
    secondRow.append(secondOperator, secondValue);
    editor.appendChild(secondRow);

    const hint = document.createElement('p');
    hint.className = 'column-text-filter-hint';
    hint.textContent = 'Dùng ? cho một ký tự, * cho nhiều ký tự.';
    editor.appendChild(hint);

    const error = document.createElement('p');
    error.className = 'column-text-filter-error';
    error.hidden = true;
    editor.appendChild(error);

    const footer = document.createElement('div');
    footer.className = 'column-text-filter-footer';
    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'column-text-filter-cancel';
    cancelButton.textContent = 'Hủy';
    const applyButton = document.createElement('button');
    applyButton.type = 'button';
    applyButton.className = 'column-text-filter-apply';
    applyButton.textContent = 'OK';
    footer.append(cancelButton, applyButton);
    editor.appendChild(footer);

    editor.addEventListener('keydown', event => {
        if (event.key !== 'Enter' || event.isComposing) return;
        event.preventDefault();
        event.stopPropagation();
        applyColumnTextFilterFromMenu(panel.closest('.column-menu-popover'), tableId, columnName);
    });

    panel.append(options, editor);

    if (currentRule) {
        firstOperator.value = currentRule.operator;
        firstValue.value = currentRule.value;
        if (currentRule.custom) {
            secondOperator.value = currentRule.secondOperator;
            secondValue.value = currentRule.secondValue;
            editor.querySelector(`input[value="${currentRule.logic}"]`)?.click();
        }
    }
    secondRow.hidden = true;
    logicRow.hidden = true;
    return panel;
}

function showColumnTextFilterEditor(panel, operator) {
    const options = panel?.querySelector('.column-text-filter-options');
    const editor = panel?.querySelector('.column-text-filter-editor');
    if (!options || !editor) return;

    const firstOperator = editor.querySelector('.column-text-filter-operator-1');
    const firstValue = editor.querySelector('.column-text-filter-value-1');
    const secondRow = editor.querySelector('.column-text-filter-second-row');
    const logicRow = editor.querySelector('.column-text-filter-logic');
    const currentRule = normalizeColumnTextFilterRule(getColumnTextFilterRule(
        editor.dataset.tableId,
        decodeColumnName(editor.dataset.columnName)
    ));
    const isCustom = operator === 'custom';
    editor.dataset.operator = isCustom ? 'custom' : operator;
    options.hidden = true;
    editor.hidden = false;
    firstOperator.value = isCustom ? currentRule?.operator || 'equals' : operator;
    firstValue.value = currentRule?.value || '';
    secondRow.hidden = !isCustom;
    logicRow.hidden = !isCustom;
    if (isCustom) {
        editor.querySelector('.column-text-filter-operator-2').value = currentRule?.secondOperator || 'equals';
        editor.querySelector('.column-text-filter-value-2').value = currentRule?.secondValue || '';
        editor.querySelector(`input[value="${currentRule?.logic || 'and'}"]`)?.click();
    }
    const error = editor.querySelector('.column-text-filter-error');
    error.hidden = true;
    error.textContent = '';
    firstValue.focus();
}

function showColumnTextFilterOptions(panel) {
    const options = panel?.querySelector('.column-text-filter-options');
    const editor = panel?.querySelector('.column-text-filter-editor');
    if (!options || !editor) return;
    options.hidden = false;
    editor.hidden = true;
}

function toggleColumnTextFilterPanel() {
    const panel = activeColumnMenuState?.menu?.querySelector('.column-text-filter-panel');
    const trigger = activeColumnMenuState?.menu?.querySelector('[data-action="toggle-text-filter"]');
    if (!panel || !trigger) return;
    panel.hidden = !panel.hidden;
    trigger.classList.toggle('is-open', !panel.hidden);
    trigger.setAttribute('aria-expanded', String(!panel.hidden));
    if (!panel.hidden) {
        showColumnTextFilterOptions(panel);
        requestAnimationFrame(() => {
            const rect = panel.getBoundingClientRect();
            const opensLeft = rect.right > window.innerWidth - 12;
            panel.style.left = opensLeft ? 'auto' : 'calc(100% + 6px)';
            panel.style.right = opensLeft ? 'calc(100% + 6px)' : 'auto';
        });
    }
}

function commitColumnFilterChange(tableId) {
    syncHeaderDecorations(tableId);
    closeColumnMenu();
    currentQueryRequest = buildQueryRequest(currentQueryRequest, {
        page: 1,
        columnFilters: collectColumnFiltersForUrl()
    });
    getProcurementSearchForm()?.setPage?.(1);
    refreshBoundedWorkingSetViews({ page: 1, resetScroll: false, redrawCharts: true });
    setFilterUrlState(currentQueryRequest);
}

function applyColumnValueFilterFromMenu(menu, tableId, columnName) {
    const facetOptions = getBoundedColumnValueOptions(tableId, columnName);
    const draft = menu?.querySelector('.column-value-list')?.columnFilterDraft;
    if (!draft) return;
    const distinctValues = facetOptions.map(option => option.value);
    const selectedValues = Array.from(draft.selectedKeys)
        .map(key => draft.valuesByKey.get(key))
        .filter(value => value !== undefined);
    const nextValueSet = selectedValues.length === distinctValues.length
        ? null
        : new Set(selectedValues);
    const currentValueSet = getColumnValueFilter(tableId, columnName);
    const currentHasValueFilter = currentValueSet instanceof Set;
    const nextHasValueFilter = nextValueSet instanceof Set;
    if (!getColumnTextFilterRule(tableId, columnName)
        && currentHasValueFilter === nextHasValueFilter
        && (!currentHasValueFilter || areColumnValueSetsEqual(currentValueSet, nextValueSet))) {
        closeColumnMenu();
        return;
    }

    if (!nextHasValueFilter) {
        replaceColumnFilterState(columnValueFilterState[tableId], tableId, columnName);
    } else {
        replaceColumnFilterState(columnValueFilterState[tableId], tableId, columnName, nextValueSet);
    }
    replaceColumnFilterState(columnTextFilterState[tableId], tableId, columnName);

    commitColumnFilterChange(tableId);
}

function applyColumnTextFilterFromMenu(menu, tableId, columnName) {
    const editor = menu?.querySelector('.column-text-filter-editor');
    if (!editor) return;

    const operator = editor.dataset.operator || 'equals';
    const value = editor.querySelector('.column-text-filter-value-1')?.value || '';
    const secondOperator = editor.querySelector('.column-text-filter-operator-2')?.value || 'equals';
    const secondValue = editor.querySelector('.column-text-filter-value-2')?.value || '';
    const isCustom = operator === 'custom';
    const requiresValue = (candidateOperator, candidateValue) => (
        !['equals', 'notEquals'].includes(candidateOperator) && !candidateValue.trim()
    );
    const error = editor.querySelector('.column-text-filter-error');
    if (requiresValue(isCustom ? editor.querySelector('.column-text-filter-operator-1')?.value : operator, value)
        || (isCustom && requiresValue(secondOperator, secondValue))) {
        error.textContent = 'Vui lòng nhập giá trị cho điều kiện đã chọn.';
        error.hidden = false;
        return;
    }

    const rule = isCustom
        ? {
            custom: true,
            operator: editor.querySelector('.column-text-filter-operator-1')?.value || 'equals',
            value,
            logic: editor.querySelector('.column-text-filter-logic input:checked')?.value || 'and',
            secondOperator,
            secondValue
        }
        : { operator, value };
    const normalizedRule = normalizeColumnTextFilterRule(rule);
    const currentRule = normalizeColumnTextFilterRule(getColumnTextFilterRule(tableId, columnName));
    if (!(getColumnValueFilter(tableId, columnName) instanceof Set)
        && stableStringify(currentRule) === stableStringify(normalizedRule)) {
        closeColumnMenu();
        return;
    }
    replaceColumnFilterState(columnValueFilterState[tableId], tableId, columnName);
    replaceColumnFilterState(
        columnTextFilterState[tableId],
        tableId,
        columnName,
        normalizedRule
    );
    commitColumnFilterChange(tableId);
}

function clearColumnTextFilter(tableId, columnName) {
    replaceColumnFilterState(columnTextFilterState[tableId], tableId, columnName);
    replaceColumnFilterState(columnValueFilterState[tableId], tableId, columnName);
    commitColumnFilterChange(tableId);
}

const MAX_COLUMN_VALUES_RENDERED = 250;

function getMatchingColumnValueOptions(facetOptions, searchTerm = '') {
    const normalizedSearch = String(searchTerm || '').trim().toLocaleLowerCase('vi');
    return facetOptions.filter(option => (
        !normalizedSearch
        || String(option.value || '(Trống)').toLocaleLowerCase('vi').includes(normalizedSearch)
    ));
}

function renderColumnValueOptions(valueList, facetOptions, draft, searchTerm = '') {
    valueList.replaceChildren();
    const normalizedSearch = String(searchTerm || '').trim().toLocaleLowerCase('vi');
    const matchingOptions = getMatchingColumnValueOptions(facetOptions, searchTerm);
    const visibleOptions = matchingOptions.slice(0, MAX_COLUMN_VALUES_RENDERED);

    const selectAll = document.createElement('label');
    selectAll.className = 'column-value-option is-select-all';
    const selectAllCheckbox = document.createElement('input');
    selectAllCheckbox.type = 'checkbox';
    selectAllCheckbox.className = 'column-value-filter-checkbox';
    selectAllCheckbox.dataset.role = 'all';
    selectAllCheckbox.checked = draft.selectedKeys.size === draft.valuesByKey.size;
    selectAllCheckbox.indeterminate = draft.selectedKeys.size > 0 && draft.selectedKeys.size < draft.valuesByKey.size;
    const selectAllLabel = document.createElement('span');
    selectAllLabel.textContent = '(Chọn tất cả)';
    selectAll.append(selectAllCheckbox, selectAllLabel);
    valueList.appendChild(selectAll);

    visibleOptions.forEach(({ value, count }) => {
        const option = document.createElement('label');
        option.className = 'column-value-option';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'column-value-filter-checkbox';
        checkbox.dataset.value = encodeColumnName(value);
        checkbox.checked = draft.selectedKeys.has(normalizeColumnFilterValue(value));
        const label = document.createElement('span');
        label.textContent = value || '(Trống)';
        label.title = label.textContent;
        const countLabel = document.createElement('small');
        countLabel.className = 'column-value-count';
        countLabel.textContent = Number.isFinite(count) ? count.toLocaleString('vi-VN') : '';
        option.append(checkbox, label, countLabel);
        valueList.appendChild(option);
    });

    if (!visibleOptions.length) {
        const empty = document.createElement('div');
        empty.className = 'column-value-empty';
        empty.textContent = normalizedSearch ? 'Không tìm thấy giá trị phù hợp' : 'Không có giá trị trong kết quả hiện tại';
        valueList.appendChild(empty);
    } else if (visibleOptions.length < matchingOptions.length) {
        const hint = document.createElement('div');
        hint.className = 'column-value-empty';
        hint.textContent = 'Nhập từ khóa để tìm thêm giá trị';
        valueList.appendChild(hint);
    }
}

function renderColumnMenuShell(tableId, columnName) {
    const sortState = getSortStateForColumn(tableId, columnName);
    const isWrapped = wrappedColumnsState[tableId]?.has(columnName);
    const isPinned = frozenColumnsState[tableId]?.has(columnName);
    const displayLabel = getResultColumnLabel(tableId, columnName);
    const fragment = document.createDocumentFragment();

    const title = document.createElement('div');
    title.className = 'column-menu-title';
    title.textContent = displayLabel;
    fragment.appendChild(title);

    const primarySection = document.createElement('div');
    primarySection.className = 'column-menu-section';

    primarySection.appendChild(createColumnMenuActionButton({
        action: 'sort-asc',
        tableId,
        columnName,
        icon: 'arrow-up',
        label: 'Sắp xếp tăng dần',
        isActive: sortState === 'asc'
    }));
    primarySection.appendChild(createColumnMenuActionButton({
        action: 'sort-desc',
        tableId,
        columnName,
        icon: 'arrow-down',
        label: 'Sắp xếp giảm dần',
        isActive: sortState === 'desc'
    }));
    if (sortState) {
        primarySection.appendChild(createColumnMenuActionButton({
            action: 'clear-sort',
            tableId,
            columnName,
            icon: 'rotate-ccw',
            label: 'Bỏ sắp xếp',
            isSecondary: true
        }));
    }
    fragment.appendChild(primarySection);

    const divider = document.createElement('hr');
    divider.className = 'column-menu-divider';
    fragment.appendChild(divider);

    const secondarySection = document.createElement('div');
    secondarySection.className = 'column-menu-section';
    secondarySection.appendChild(createColumnMenuActionButton({
        action: 'autosize',
        tableId,
        columnName,
        icon: 'code',
        label: 'Tự căn độ rộng'
    }));
    secondarySection.appendChild(createColumnMenuActionButton({
        action: 'toggle-wrap',
        tableId,
        columnName,
        icon: 'corner-down-right',
        label: 'Ngắt dòng',
        isActive: isWrapped
    }));
    secondarySection.appendChild(createColumnMenuActionButton({
        action: 'toggle-pin',
        tableId,
        columnName,
        icon: 'tag',
        label: 'Ghim cột',
        isActive: isPinned
    }));
    secondarySection.appendChild(createColumnMenuActionButton({
        action: 'hide-column',
        tableId,
        columnName,
        icon: 'eye-off',
        label: 'Ẩn cột',
        isDanger: true
    }));
    fragment.appendChild(secondarySection);

    const textFilterDivider = document.createElement('hr');
    textFilterDivider.className = 'column-menu-divider';
    fragment.appendChild(textFilterDivider);

    const textFilterSection = document.createElement('div');
    textFilterSection.className = 'column-text-filter-section';
    const textFilterButton = createColumnMenuActionButton({
        action: 'toggle-text-filter',
        tableId,
        columnName,
        icon: 'type',
        label: 'Bộ lọc văn bản',
        isActive: Boolean(getColumnTextFilterRule(tableId, columnName))
    });
    textFilterButton.setAttribute('aria-haspopup', 'true');
    textFilterButton.setAttribute('aria-expanded', 'false');
    textFilterButton.appendChild(createFeatherIconElement('chevron-right', 'column-menu-submenu-icon'));
    textFilterSection.appendChild(textFilterButton);
    textFilterSection.appendChild(createColumnTextFilterPanel(tableId, columnName));
    fragment.appendChild(textFilterSection);

    const filterDivider = document.createElement('hr');
    filterDivider.className = 'column-menu-divider';
    fragment.appendChild(filterDivider);

    const filterSection = document.createElement('div');
    filterSection.className = 'column-value-filter-section';
    const field = document.createElement('div');
    field.className = 'column-menu-field';
    const inputWrap = document.createElement('div');
    inputWrap.className = 'column-menu-input-wrap';
    inputWrap.appendChild(createFeatherIconElement('search', 'column-menu-icon'));

    const input = document.createElement('input');
    input.className = 'column-mini-filter-input';
    input.type = 'search';
    input.dataset.tableId = tableId;
    input.dataset.columnName = encodeColumnName(columnName);
    input.placeholder = 'Tìm kiếm';
    input.setAttribute('aria-label', `Tìm trong các giá trị của cột ${displayLabel}`);
    inputWrap.appendChild(input);
    field.appendChild(inputWrap);
    filterSection.appendChild(field);

    // Values are rendered once by renderColumnValueOptions below. Keep this
    // shell free of a second unbounded DOM build for high-cardinality columns.
    const facetOptions = [];
    const distinctValues = [];
    const selectedValues = getColumnValueFilter(tableId, columnName);
    const valueList = document.createElement('div');
    valueList.className = 'column-value-list';

    const selectAll = document.createElement('label');
    selectAll.className = 'column-value-option is-select-all';
    const selectAllCheckbox = document.createElement('input');
    selectAllCheckbox.type = 'checkbox';
    selectAllCheckbox.className = 'column-value-filter-checkbox';
    selectAllCheckbox.dataset.role = 'all';
    selectAllCheckbox.dataset.tableId = tableId;
    selectAllCheckbox.dataset.columnName = encodeColumnName(columnName);
    selectAllCheckbox.checked = !selectedValues || selectedValues.size === distinctValues.length;
    selectAllCheckbox.indeterminate = Boolean(
        selectedValues && selectedValues.size > 0 && selectedValues.size < distinctValues.length
    );
    const selectAllLabel = document.createElement('span');
    selectAllLabel.textContent = '(Chọn tất cả)';
    selectAll.append(selectAllCheckbox, selectAllLabel);
    valueList.appendChild(selectAll);

    facetOptions.forEach(({ value, count }) => {
        const option = document.createElement('label');
        option.className = 'column-value-option';
        option.dataset.searchValue = (value || '(Trống)').toLocaleLowerCase('vi');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'column-value-filter-checkbox';
        checkbox.dataset.tableId = tableId;
        checkbox.dataset.columnName = encodeColumnName(columnName);
        checkbox.dataset.value = encodeColumnName(value);
        checkbox.checked = !selectedValues || selectedValues.has(value);
        const label = document.createElement('span');
        label.textContent = value || '(Trống)';
        label.title = label.textContent;
        const countLabel = document.createElement('small');
        countLabel.className = 'column-value-count';
        countLabel.textContent = Number.isFinite(count) ? count.toLocaleString('vi-VN') : '';
        option.append(checkbox, label, countLabel);
        valueList.appendChild(option);
    });

    if (!distinctValues.length) {
        const empty = document.createElement('div');
        empty.className = 'column-value-empty';
        empty.textContent = workingSetAvailable[tableId]
            ? 'Không có giá trị trong kết quả hiện tại'
            : 'Facet server chưa khả dụng cho cột này';
        valueList.appendChild(empty);
    }

    filterSection.appendChild(valueList);
    fragment.appendChild(filterSection);

    const footer = document.createElement('div');
    footer.className = 'column-value-filter-footer';
    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'column-filter-cancel';
    cancelButton.textContent = 'Hủy';
    const applyButton = document.createElement('button');
    applyButton.type = 'button';
    applyButton.className = 'column-filter-apply';
    applyButton.dataset.tableId = tableId;
    applyButton.dataset.columnName = encodeColumnName(columnName);
    applyButton.textContent = 'OK';
    footer.append(cancelButton, applyButton);
    fragment.appendChild(footer);

    return fragment;
}

function renderColumnMenu(tableId, columnName) {
    const fragment = renderColumnMenuShell(tableId, columnName);
    const valueList = fragment.querySelector('.column-value-list');
    if (!valueList) return fragment;

    const facetOptions = getBoundedColumnValueOptions(tableId, columnName);
    const valuesByKey = new Map(facetOptions.map(option => [
        normalizeColumnFilterValue(option.value),
        option.value
    ]));
    const selectedValues = getColumnValueFilter(tableId, columnName);
    const selectedKeys = selectedValues instanceof Set
        ? new Set(Array.from(selectedValues, normalizeColumnFilterValue))
        : new Set(valuesByKey.keys());
    const draft = {
        facetOptions,
        valuesByKey,
        selectedKeys
    };
    valueList.columnFilterDraft = draft;
    const searchInput = fragment.querySelector('.column-mini-filter-input');
    const rerenderValueOptions = ({ syncSelection = false } = {}) => {
        const searchTerm = searchInput?.value || '';
        if (syncSelection) {
            const matchingOptions = getMatchingColumnValueOptions(draft.facetOptions, searchTerm);
            draft.selectedKeys = searchTerm.trim()
                ? new Set(matchingOptions.map(({ value }) => normalizeColumnFilterValue(value)))
                : new Set(draft.valuesByKey.keys());
        }
        renderColumnValueOptions(valueList, draft.facetOptions, draft, searchInput?.value || '');
    };
    const handleSearchInput = () => {
        rerenderValueOptions({ syncSelection: true });
    };
    searchInput?.addEventListener('input', handleSearchInput);
    searchInput?.addEventListener('search', handleSearchInput);
    searchInput?.addEventListener('keydown', event => {
        if (event.key !== 'Enter' || event.isComposing) return;
        event.preventDefault();
        event.stopPropagation();
    });
    rerenderValueOptions();
    return fragment;
}

function rerenderActiveColumnMenu() {
    if (!activeColumnMenuState) return;

    const { tableId, columnName, menu, wrapper } = activeColumnMenuState;
    const trigger = getColumnMenuTrigger(tableId, columnName);
    if (!trigger || !wrapper?.isConnected || !menu?.isConnected) {
        closeColumnMenu();
        return;
    }

    activeColumnMenuState.trigger = trigger;
    menu.replaceChildren(renderColumnMenu(tableId, columnName));
    finalizeDynamicMarkup(menu);
    trigger.classList.add('is-open');
    trigger.setAttribute('aria-expanded', 'true');
    positionFloatingLayer(wrapper, trigger, menu);
}

function openColumnMenu(tableId, columnName, trigger) {
    if (!tableId || !columnName || !trigger) return;

    if (
        activeColumnMenuState?.tableId === tableId &&
        activeColumnMenuState?.columnName === columnName
    ) {
        closeColumnMenu();
        return;
    }

    closeColumnMenu();
    closeColumnsPopover();

    const wrapper = getTableWrapper(tableId);
    if (!wrapper) return;

    const menu = document.createElement('div');
    menu.className = 'column-menu-popover';
    menu.replaceChildren(renderColumnMenu(tableId, columnName));
    wrapper.appendChild(menu);
    finalizeDynamicMarkup(menu);

    activeColumnMenuState = { tableId, columnName, wrapper, trigger, menu };
    trigger.classList.add('is-open');
    trigger.setAttribute('aria-expanded', 'true');
    syncFloatingWrapperState();

    requestAnimationFrame(() => {
        positionFloatingLayer(wrapper, trigger, menu);
        const input = menu.querySelector('.column-mini-filter-input');
        input?.focus({ preventScroll: true });
        input?.select?.();
    });
}

function closeColumnsPopover() {
    if (!activeColumnsPopoverState) return;

    activeColumnsPopoverState.button?.setAttribute('aria-expanded', 'false');
    if (activeColumnsPopoverState.popover) {
        activeColumnsPopoverState.popover.hidden = true;
        activeColumnsPopoverState.popover.replaceChildren();
    }

    activeColumnsPopoverState = null;
    syncFloatingWrapperState();
}

function renderColumnsPopover(tableId) {
    const config = TABLE_MAP[tableId];
    if (!config) return document.createDocumentFragment();

    const hiddenColumns = hiddenColumnsState[tableId] || new Set();
    const visibleCount = getVisibleColumnOrder(tableId).length;
    const fragment = document.createDocumentFragment();

    const header = document.createElement('div');
    header.className = 'table-columns-header';

    const title = document.createElement('strong');
    title.textContent = 'Ẩn/Hiện cột';
    header.appendChild(title);

    const resetButton = document.createElement('button');
    resetButton.className = 'table-columns-reset';
    resetButton.type = 'button';
    resetButton.dataset.tableId = tableId;
    resetButton.appendChild(createFeatherIconElement('eye', 'table-columns-icon'));
    const resetLabel = document.createElement('span');
    resetLabel.textContent = 'Hiện tất cả';
    resetButton.appendChild(resetLabel);
    header.appendChild(resetButton);
    fragment.appendChild(header);

    const list = document.createElement('div');
    list.className = 'table-columns-list';
    config.columnOrder().forEach((columnName) => {
        const isVisible = !hiddenColumns.has(columnName);
        const isLocked = isVisible && visibleCount === 1;

        const option = document.createElement('label');
        option.className = 'table-columns-option';
        if (!isVisible) option.classList.add('is-hidden');

        const checkbox = document.createElement('input');
        checkbox.className = 'table-columns-checkbox';
        checkbox.type = 'checkbox';
        checkbox.dataset.tableId = tableId;
        checkbox.dataset.columnName = encodeColumnName(columnName);
        checkbox.checked = isVisible;
        checkbox.disabled = isLocked;
        option.appendChild(checkbox);

        option.appendChild(createFeatherIconElement(isVisible ? 'eye' : 'eye-off', 'table-columns-icon'));
        const labelText = document.createElement('span');
        labelText.textContent = getResultColumnLabel(tableId, columnName);
        option.appendChild(labelText);
        list.appendChild(option);
    });
    fragment.appendChild(list);

    return fragment;
}

function openColumnsPopover(button) {
    const tableId = button?.dataset.tableId;
    const wrapper = getTableWrapper(tableId);
    const popover = wrapper?.querySelector('.table-columns-popover');
    if (!tableId || !wrapper || !popover) return;

    if (activeColumnsPopoverState?.tableId === tableId && !popover.hidden) {
        closeColumnsPopover();
        return;
    }

    closeColumnMenu();
    closeColumnsPopover();

    if (popover.parentElement !== wrapper) {
        wrapper.appendChild(popover);
    }

    popover.replaceChildren(renderColumnsPopover(tableId));
    popover.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    activeColumnsPopoverState = { tableId, wrapper, button, popover };
    syncFloatingWrapperState();
    finalizeDynamicMarkup(popover);

    requestAnimationFrame(() => {
        positionFloatingLayer(wrapper, button, popover);
    });
}

function rerenderColumnsPopover() {
    if (!activeColumnsPopoverState) return;
    const { tableId, button, popover, wrapper } = activeColumnsPopoverState;
    if (!button?.isConnected || !popover?.isConnected || !wrapper?.isConnected) {
        closeColumnsPopover();
        return;
    }

    popover.replaceChildren(renderColumnsPopover(tableId));
    popover.hidden = false;
    finalizeDynamicMarkup(popover);
    positionFloatingLayer(wrapper, button, popover);
}

function closeFloatingTableUi() {
    closeColumnMenu();
    closeColumnsPopover();
}

async function handleColumnMenuAction(action, tableId, columnName) {
    switch (action) {
        case 'sort-asc':
            await applySortForColumn(tableId, columnName, 'asc');
            rerenderActiveColumnMenu();
            return;
        case 'sort-desc':
            await applySortForColumn(tableId, columnName, 'desc');
            rerenderActiveColumnMenu();
            return;
        case 'clear-sort':
            await clearActiveSortRule();
            rerenderActiveColumnMenu();
            return;
        case 'autosize':
            autosizeTableColumn(tableId, columnName);
            rerenderActiveColumnMenu();
            return;
        case 'toggle-wrap':
            toggleWrappedColumn(tableId, columnName);
            rerenderActiveColumnMenu();
            return;
        case 'toggle-pin':
            togglePinnedColumn(tableId, columnName);
            rerenderActiveColumnMenu();
            return;
        case 'hide-column':
            if (setTableColumnVisibility(tableId, columnName, false)) {
                closeColumnMenu();
                rerenderColumnsPopover();
            }
            return;
        case 'toggle-text-filter':
            toggleColumnTextFilterPanel();
            return;
        default:
            break;
    }
}

function syncFullscreenButtons() {
    const activeElement = document.fullscreenElement;
    document.querySelectorAll('.table-tool-btn[data-action="fullscreen"]').forEach(button => {
        const tableId = button.dataset.tableId;
        const card = getTableWrapper(tableId)?.closest('.data-card');
        button.classList.toggle('is-active', Boolean(card && activeElement === card));
    });
}

async function toggleTableFullscreen(tableId) {
    const card = getTableWrapper(tableId)?.closest('.data-card');
    if (!card || typeof card.requestFullscreen !== 'function') return;

    try {
        if (document.fullscreenElement === card && typeof document.exitFullscreen === 'function') {
            await document.exitFullscreen();
        } else {
            await card.requestFullscreen();
        }
    } catch (error) {
        console.error('Fullscreen failed:', error);
    }
}

function initTableWorkspaceControls() {
    if (document.body.dataset.tableWorkspaceBound === '1') return;
    document.body.dataset.tableWorkspaceBound = '1';

    document.addEventListener('click', async (e) => {
        const trigger = e.target.closest('.column-menu-trigger');
        if (trigger) {
            e.preventDefault();
            e.stopPropagation();
            openColumnMenu(trigger.dataset.tableId, trigger.dataset.colName, trigger);
            return;
        }

        const textFilterOption = e.target.closest('.column-text-filter-option');
        if (textFilterOption) {
            e.preventDefault();
            e.stopPropagation();
            showColumnTextFilterEditor(
                textFilterOption.closest('.column-text-filter-panel'),
                textFilterOption.dataset.operator
            );
            return;
        }

        const clearTextFilterButton = e.target.closest('.column-text-filter-clear');
        if (clearTextFilterButton) {
            e.preventDefault();
            e.stopPropagation();
            clearColumnTextFilter(
                clearTextFilterButton.dataset.tableId,
                decodeColumnName(clearTextFilterButton.dataset.columnName)
            );
            return;
        }

        const applyTextFilterButton = e.target.closest('.column-text-filter-apply');
        if (applyTextFilterButton) {
            e.preventDefault();
            e.stopPropagation();
            const editor = applyTextFilterButton.closest('.column-text-filter-editor');
            applyColumnTextFilterFromMenu(
                applyTextFilterButton.closest('.column-menu-popover'),
                editor?.dataset.tableId,
                decodeColumnName(editor?.dataset.columnName || '')
            );
            return;
        }

        const cancelTextFilterButton = e.target.closest('.column-text-filter-cancel');
        if (cancelTextFilterButton) {
            e.preventDefault();
            e.stopPropagation();
            showColumnTextFilterOptions(cancelTextFilterButton.closest('.column-text-filter-panel'));
            return;
        }

        const menuAction = e.target.closest('.column-menu-action');
        if (menuAction) {
            e.preventDefault();
            e.stopPropagation();
            await handleColumnMenuAction(
                menuAction.dataset.action,
                menuAction.dataset.tableId,
                decodeColumnName(menuAction.dataset.columnName)
            );
            return;
        }

        const applyFilterButton = e.target.closest('.column-filter-apply');
        if (applyFilterButton) {
            e.preventDefault();
            e.stopPropagation();
            applyColumnValueFilterFromMenu(
                applyFilterButton.closest('.column-menu-popover'),
                applyFilterButton.dataset.tableId,
                decodeColumnName(applyFilterButton.dataset.columnName)
            );
            return;
        }

        const cancelFilterButton = e.target.closest('.column-filter-cancel');
        if (cancelFilterButton) {
            e.preventDefault();
            e.stopPropagation();
            closeColumnMenu();
            return;
        }

        const toolButton = e.target.closest('.table-tool-btn');
        if (toolButton) {
            e.preventDefault();
            e.stopPropagation();

            const { action, tableId } = toolButton.dataset;
            if (action === 'toggle-columns') {
                openColumnsPopover(toolButton);
            } else if (action === 'download') {
                exportTableToExcel(tableId);
            } else if (action === 'fullscreen') {
                await toggleTableFullscreen(tableId);
            }
            return;
        }

        const resetButton = e.target.closest('.table-columns-reset');
        if (resetButton) {
            e.preventDefault();
            e.stopPropagation();

            const tableId = resetButton.dataset.tableId;
            hiddenColumnsState[tableId] = new Set();
            persistColumnSet(STORAGE_KEYS.hiddenColumns, tableId, hiddenColumnsState[tableId]);
            refreshHeaderStructure({ resetScroll: false, redrawCharts: false });
            rerenderColumnsPopover();
            return;
        }

        if (activeColumnMenuState && !activeColumnMenuState.menu.contains(e.target)) {
            closeColumnMenu();
        }

        if (
            activeColumnsPopoverState &&
            !activeColumnsPopoverState.popover.contains(e.target) &&
            !activeColumnsPopoverState.button.contains(e.target)
        ) {
            closeColumnsPopover();
        }
    });

    document.addEventListener('change', (e) => {
        const valueCheckbox = e.target.closest('.column-value-filter-checkbox');
        if (valueCheckbox) {
            const valueList = valueCheckbox.closest('.column-value-list');
            const draft = valueList?.columnFilterDraft;
            if (!draft) return;
            if (valueCheckbox.dataset.role === 'all') {
                draft.selectedKeys = valueCheckbox.checked
                    ? new Set(draft.valuesByKey.keys())
                    : new Set();
            } else {
                const key = normalizeColumnFilterValue(decodeColumnName(valueCheckbox.dataset.value));
                if (valueCheckbox.checked) draft.selectedKeys.add(key);
                else draft.selectedKeys.delete(key);
            }
            const input = valueList.closest('.column-value-filter-section')?.querySelector('.column-mini-filter-input');
            renderColumnValueOptions(valueList, draft.facetOptions, draft, input?.value || '');
            return;
        }

        const checkbox = e.target.closest('.table-columns-checkbox');
        if (!checkbox) return;

        const tableId = checkbox.dataset.tableId;
        const columnName = decodeColumnName(checkbox.dataset.columnName);
        const didUpdate = setTableColumnVisibility(tableId, columnName, checkbox.checked);

        if (!didUpdate) {
            checkbox.checked = !checkbox.checked;
        }

        rerenderColumnsPopover();
    });

    document.querySelectorAll('.table-wrapper .table-scroll').forEach(container => {
        container.addEventListener('scroll', () => {
            closeColumnMenu();
        });
    });
    document.addEventListener('fullscreenchange', syncFullscreenButtons);
    syncFullscreenButtons();
}



// ============================== 
// CHARTS
// ============================== 

// ======== 1. CHART INSTANCES
const chartInstances = {
    histogram: null,
    timeline: null
};

const CHART_JS_URL = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
let chartJsLoadPromise = null;
let insightChartsDirty = true;
let vietnamMapDefinition = null;
let vietnamMapLoadPromise = null;
let lastProvinceMapData = [];

const CHART_THEME = {
    primary: '#127495',
    accent: '#1b866e',
    accentSoft: 'rgba(27, 134, 110, 0.14)',
    axis: '#5d7280',
    axisStrong: '#1f3448',
    grid: '#dde7ec',
    border: '#d1dde4',
    surface: '#ffffff',
    mapNoData: '#fdfefe',
    mapLow: '#8fc7d2',
    mapHigh: '#0a516d'
};

function ensureChartJsLoaded() {
    if (window.Chart) return Promise.resolve(window.Chart);
    if (chartJsLoadPromise) return chartJsLoadPromise;

    chartJsLoadPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = CHART_JS_URL;
        script.async = true;
        script.onload = () => window.Chart
            ? resolve(window.Chart)
            : reject(new Error('Chart.js loaded without exposing window.Chart'));
        script.onerror = () => reject(new Error('Unable to load Chart.js'));
        document.head.appendChild(script);
    }).catch(error => {
        chartJsLoadPromise = null;
        throw error;
    });

    return chartJsLoadPromise;
}

const VIETNAM_PROVINCE_NAMES = [
    'An Giang', 'Bà Rịa - Vũng Tàu', 'Bắc Giang', 'Bắc Kạn', 'Bạc Liêu', 'Bắc Ninh',
    'Bến Tre', 'Bình Định', 'Bình Dương', 'Bình Phước', 'Bình Thuận', 'Cà Mau',
    'Cần Thơ', 'Cao Bằng', 'Đà Nẵng', 'Đắk Lắk', 'Đắk Nông', 'Điện Biên',
    'Đồng Nai', 'Đồng Tháp', 'Gia Lai', 'Hà Giang', 'Hà Nam', 'Hà Nội',
    'Hà Tĩnh', 'Hải Dương', 'Hải Phòng', 'Hậu Giang', 'Hòa Bình', 'Hưng Yên',
    'Khánh Hòa', 'Kiên Giang', 'Kon Tum', 'Lai Châu', 'Lâm Đồng', 'Lạng Sơn',
    'Lào Cai', 'Long An', 'Nam Định', 'Nghệ An', 'Ninh Bình', 'Ninh Thuận',
    'Phú Thọ', 'Phú Yên', 'Quảng Bình', 'Quảng Nam', 'Quảng Ngãi', 'Quảng Ninh',
    'Quảng Trị', 'Sóc Trăng', 'Sơn La', 'Tây Ninh', 'Thái Bình', 'Thái Nguyên',
    'Thanh Hóa', 'Thừa Thiên Huế', 'Tiền Giang', 'TP. Hồ Chí Minh', 'Trà Vinh',
    'Tuyên Quang', 'Vĩnh Long', 'Vĩnh Phúc', 'Yên Bái', 'Hoàng Sa', 'Trường Sa'
];

function normalizeVietnameseText(text) {
    return String(text || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/đ/g, 'd')
        .replace(/Đ/g, 'D')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .trim();
}

const VIETNAM_PROVINCE_LOOKUP = VIETNAM_PROVINCE_NAMES.map(name => ({
    name,
    normalized: normalizeVietnameseText(name)
}));

const PROVINCE_MAP_ALIASES = new Map([
    ['tp ho chi minh', 'ho chi minh'],
    ['thanh pho ho chi minh', 'ho chi minh'],
    ['thanh pho ho chi minh city', 'ho chi minh'],
    ['ho chi minh city', 'ho chi minh'],
    ['hcm', 'ho chi minh'],
    ['tp hcm', 'ho chi minh'],
    ['ba ria vung tau', 'ba ria vung tau'],
    ['thua thien hue', 'thua thien hue'],
    ['hue', 'thua thien hue'],
    ['ha tay', 'ha noi'],
    ['quan dao hoang sa', 'hoang sa'],
    ['quan dao truong sa', 'truong sa']
]);

const ADMIN_UNITS_2025 = [
    { name: 'Thành phố Hà Nội', parts: ['Hà Nội'] },
    { name: 'Cao Bằng', parts: ['Cao Bằng'] },
    { name: 'Tuyên Quang', parts: ['Tuyên Quang','Hà Giang'] },
    { name: 'Điện Biên', parts: ['Điện Biên'] },
    { name: 'Lai Châu', parts: ['Lai Châu'] },
    { name: 'Sơn La', parts: ['Sơn La'] },
    { name: 'Lào Cai', parts: ['Lào Cai', 'Yên Bái'] },
    { name: 'Thái Nguyên', parts: ['Thái Nguyên', 'Bắc Kạn'] },
    { name: 'Lạng Sơn', parts: ['Lạng Sơn'] },
    { name: 'Quảng Ninh', parts: ['Quảng Ninh'] },
    { name: 'Bắc Ninh', parts: ['Bắc Ninh', 'Bắc Giang'] },
    { name: 'Phú Thọ', parts: ['Phú Thọ', 'Vĩnh Phúc', 'Hòa Bình'] },
    { name: 'Thành phố Hải Phòng', parts: ['Hải Phòng', 'Hải Dương'] },
    { name: 'Hưng Yên', parts: ['Hưng Yên', 'Thái Bình'] },
    { name: 'Ninh Bình', parts: ['Ninh Bình', 'Hà Nam', 'Nam Định'] },
    { name: 'Thanh Hóa', parts: ['Thanh Hóa'] },
    { name: 'Nghệ An', parts: ['Nghệ An'] },
    { name: 'Hà Tĩnh', parts: ['Hà Tĩnh'] },
    { name: 'Quảng Trị', parts: ['Quảng Trị', 'Quảng Bình'] },
    { name: 'Thành phố Huế', parts: ['Thừa Thiên Huế'] },
    { name: 'Thành phố Đà Nẵng', parts: ['Đà Nẵng', 'Quảng Nam'] },
    { name: 'Quảng Ngãi', parts: ['Quảng Ngãi', 'Kon Tum'] },
    { name: 'Gia Lai', parts: ['Gia Lai', 'Bình Định'] },
    { name: 'Khánh Hòa', parts: ['Khánh Hòa', 'Ninh Thuận'] },
    { name: 'Đắk Lắk', parts: ['Đắk Lắk', 'Phú Yên'] },
    { name: 'Lâm Đồng', parts: ['Lâm Đồng', 'Đắk Nông', 'Bình Thuận'] },
    { name: 'Đồng Nai', parts: ['Đồng Nai', 'Bình Phước'] },
    { name: 'Thành phố Hồ Chí Minh', parts: ['TP. Hồ Chí Minh', 'Bình Dương', 'Bà Rịa - Vũng Tàu'] },
    { name: 'Tây Ninh', parts: ['Tây Ninh', 'Long An'] },
    { name: 'Đồng Tháp', parts: ['Đồng Tháp', 'Tiền Giang'] },
    { name: 'Vĩnh Long', parts: ['Vĩnh Long', 'Bến Tre', 'Trà Vinh'] },
    { name: 'An Giang', parts: ['An Giang', 'Kiên Giang'] },
    { name: 'Thành phố Cần Thơ', parts: ['Cần Thơ', 'Hậu Giang', 'Sóc Trăng'] },
    { name: 'Cà Mau', parts: ['Cà Mau', 'Bạc Liêu'] }
];

const ADMIN_2025_BY_LEGACY_KEY = new Map();

ADMIN_UNITS_2025.forEach(unit => {
    const adminKey = getProvinceMapKey(unit.name);
    const partNames = unit.parts.join(' + ');
    ADMIN_2025_BY_LEGACY_KEY.set(adminKey, { key: adminKey, name: unit.name, parts: partNames });
    unit.parts.forEach(part => {
        ADMIN_2025_BY_LEGACY_KEY.set(getProvinceMapKey(part), { key: adminKey, name: unit.name, parts: partNames });
    });
});

[
    ['Hoàng Sa', 'Thành phố Đà Nẵng'],
    ['Trường Sa', 'Khánh Hòa']
].forEach(([islandName, adminName]) => {
    const adminUnit = ADMIN_2025_BY_LEGACY_KEY.get(getProvinceMapKey(adminName));
    if (adminUnit) {
        ADMIN_2025_BY_LEGACY_KEY.set(getProvinceMapKey(islandName), adminUnit);
    }
});

function getProvinceMapKey(name) {
    let key = normalizeVietnameseText(name)
        .replace(/\bt\s+p\b/g, 'tp')
        .replace(/\btp\b/g, ' ')
        .replace(/\btinh\b/g, ' ')
        .replace(/\bthanh pho\b/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();

    key = PROVINCE_MAP_ALIASES.get(key) || key;
    return key;
}

const LOCATION_PROVINCE_MATCHES = VIETNAM_PROVINCE_LOOKUP
    .map(province => ({
        ...province,
        mapKey: getProvinceMapKey(province.name)
    }))
    .filter(province => province.mapKey)
    .sort((a, b) => b.mapKey.length - a.mapKey.length);

function getLocationProvinceMatchKey(value) {
    let key = normalizeVietnameseText(value)
        .replace(/\bt\s+p\b/g, 'tp')
        .replace(/\btp\b|\btinh\b|\bthanh pho\b|\bcity\b/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();

    // Expand aliases inside a long location string (for example "HCM,
    // Thành phố Thủ Đức"), not only when the whole value is an alias.
    let paddedKey = ` ${key} `;
    [...PROVINCE_MAP_ALIASES.entries()]
        .filter(([alias, target]) => alias !== target)
        .sort(([a], [b]) => b.length - a.length)
        .forEach(([alias, target]) => {
            paddedKey = paddedKey.replaceAll(` ${alias} `, ` ${target} `);
        });

    return paddedKey.replace(/\s+/g, ' ').trim();
}

function getLocationTextForMatching(place) {
    if (Array.isArray(place)) {
        return place.map(getLocationTextForMatching).filter(Boolean).join('; ');
    }
    if (place && typeof place === 'object') {
        return [
            place.provName,
            place.provinceName,
            place.cityName,
            place.province,
            place.provCode,
            place.provinceCode,
            place.cityCode,
            place.districtName,
            place.wardName,
            place.communeName
        ].find(value => value !== undefined && value !== null && String(value).trim()) || '';
    }
    return String(place ?? '');
}

function findProvinceMatchInLocation(value) {
    const normalizedLocation = getLocationProvinceMatchKey(value);
    if (!normalizedLocation) return null;

    const paddedLocation = ` ${normalizedLocation} `;
    return LOCATION_PROVINCE_MATCHES.find(province =>
        paddedLocation.includes(` ${province.mapKey} `)
    ) || null;
}

function extractProvinceFromPlace(place) {
    const rawPlace = getLocationTextForMatching(place).replace(/\s+/g, ' ').trim();
    if (!rawPlace) return 'Không xác định';

    const segments = rawPlace
        .split(/[;|\n]+/)
        .map(part => part.trim())
        .filter(Boolean);
    const matchedProvince = segments
        .map(findProvinceMatchInLocation)
        .find(Boolean) || findProvinceMatchInLocation(rawPlace);

    // Only return a value from the canonical catalog. Unknown free-form
    // fragments must not become phantom map regions or inflate the legend.
    return matchedProvince?.name || 'Không xác định';
}

function getProvinceValueEntries(data) {
    const adminValueMap = new Map();

    data.forEach(r => {
        const province = extractProvinceFromPlace(getFirstRawColumnValue(r, ['location']));
        const value = getChartTotalValue(r);
        if (value <= 0) return;

        const provinceKey = getProvinceMapKey(province);
        // Do not let an unrecognised location become a phantom region. It is
        // not rendered on the 34-region map, so including it here would make
        // the legend max differ from every visible province.
        const adminUnit = ADMIN_2025_BY_LEGACY_KEY.get(provinceKey);
        if (!adminUnit) return;
        const current = adminValueMap.get(adminUnit.key) || {
            name: adminUnit.name,
            parts: adminUnit.parts,
            value: 0
        };
        current.value += value;
        adminValueMap.set(adminUnit.key, current);
    });

    return adminValueMap;
}

function interpolateHexColor(startColor, endColor, ratio) {
    const clampedRatio = Math.max(0, Math.min(1, ratio));
    const start = startColor.replace('#', '').match(/.{1,2}/g).map(value => parseInt(value, 16));
    const end = endColor.replace('#', '').match(/.{1,2}/g).map(value => parseInt(value, 16));
    const mixed = start.map((channel, index) =>
        Math.round(channel + (end[index] - channel) * clampedRatio)
    );
    return `#${mixed.map(value => value.toString(16).padStart(2, '0')).join('')}`;
}

function getProvinceFill(value, maxValue) {
    if (!value || !maxValue) return CHART_THEME.mapNoData;
    const ratio = Math.sqrt(value / maxValue);
    return interpolateHexColor(CHART_THEME.mapLow, CHART_THEME.mapHigh, ratio);
}

function getProvinceMergeStatus(provinceName, provinceValue, mapProperties = {}) {
    const sourceMerge = String(mapProperties.sap_nhap || '').replace(/\s+/g, ' ').trim();
    if (sourceMerge) {
        return normalizeVietnameseText(sourceMerge) === 'khong sap nhap'
            ? 'Không sáp nhập'
            : `Sáp nhập: ${sourceMerge}`;
    }

    const parts = String(provinceValue?.parts || '').replace(/\s+/g, ' ').trim();
    if (!parts || getProvinceMapKey(parts) === getProvinceMapKey(provinceName)) {
        return 'Không sáp nhập';
    }

    return `Sáp nhập: ${parts}`;
}

function createProvinceMapLegend(maxValue) {
    const legend = document.createElement('div');
    legend.className = 'province-map-legend';
    legend.setAttribute('aria-hidden', 'true');

    const title = document.createElement('span');
    title.className = 'province-map-legend-title';
    title.textContent = 'Tổng giá trị';

    const scale = document.createElement('span');
    scale.className = 'province-map-legend-scale';
    scale.style.setProperty('--map-zero', CHART_THEME.mapNoData);
    scale.style.setProperty('--map-low', CHART_THEME.mapLow);
    scale.style.setProperty('--map-high', CHART_THEME.mapHigh);

    const labels = document.createElement('span');
    labels.className = 'province-map-legend-labels';

    const minLabel = document.createElement('span');
    minLabel.textContent = '0';

    const maxLabel = document.createElement('span');
    maxLabel.textContent = formatCurrencyTooltip(maxValue);

    labels.append(minLabel, maxLabel);
    legend.append(title, scale, labels);
    return legend;
}

function getOrCreateProvinceMapTooltip(container) {
    let tooltip = container.querySelector('.province-map-tooltip');
    if (tooltip) return tooltip;

    tooltip = document.createElement('div');
    tooltip.className = 'province-map-tooltip';
    container.appendChild(tooltip);
    return tooltip;
}

function moveProvinceMapTooltip(container, tooltip, event) {
    const rect = container.getBoundingClientRect();
    const offset = 14;
    const tooltipRect = tooltip.getBoundingClientRect();
    let left = event.clientX - rect.left + offset;
    let top = event.clientY - rect.top + offset;

    if (left + tooltipRect.width > rect.width - 8) {
        left = event.clientX - rect.left - tooltipRect.width - offset;
    }
    if (top + tooltipRect.height > rect.height - 8) {
        top = event.clientY - rect.top - tooltipRect.height - offset;
    }

    tooltip.style.left = `${Math.max(8, left)}px`;
    tooltip.style.top = `${Math.max(8, top)}px`;
}

function fitProvinceMapViewBox(svg) {
    try {
        const box = svg.getBBox();
        if (!box.width || !box.height) return;

        const paddingX = box.width * 0.04;
        const paddingY = box.height * 0.03;
        svg.setAttribute(
            'viewBox',
            `${box.x - paddingX} ${box.y - paddingY} ${box.width + paddingX * 2} ${box.height + paddingY * 2}`
        );
    } catch (error) {
        // Keep the source viewBox if the browser cannot measure the SVG yet.
    }
}

function loadVietnamProvinceMap() {
    if (vietnamMapDefinition?.features?.length) {
        return Promise.resolve(vietnamMapDefinition);
    }

    if (!vietnamMapLoadPromise) {
        vietnamMapLoadPromise = fetch('Vietnam34.map.json', { cache: 'force-cache' })
            .then(response => {
                if (!response.ok) throw new Error(`Vietnam34.map.json returned ${response.status}`);
                return response.json();
            })
            .then(payload => {
                vietnamMapDefinition = {
                    viewBox: payload.viewBox || '0 0 980 1500',
                    features: (payload.features || []).map(feature => ({
                        path: feature.path,
                        properties: {
                            ten_tinh: feature.name,
                            sap_nhap: feature.sap_nhap
                        }
                    })).filter(feature => feature.path)
                };
                return vietnamMapDefinition;
            })
            .catch(error => {
                console.error('Unable to load Vietnam map data', error);
                window.BIDFinderVietnamMapLoadFailed = true;
                throw error;
            });
    }

    return vietnamMapLoadPromise;
}

function renderProvinceValueMap(data = []) {
    lastProvinceMapData = data;
    const container = document.getElementById('chart-province-map');
    if (!container) return;

    if (!vietnamMapDefinition?.features?.length) {
        showNoDataMessage('chart-province-map', 'Đang tải bản đồ Việt Nam...');
        loadVietnamProvinceMap()
            .then(() => renderProvinceValueMap(lastProvinceMapData))
            .catch(() => showNoDataMessage('chart-province-map', 'Không tải được bản đồ Việt Nam 34 tỉnh/thành.'));
        return;
    }

    const valueByProvince = getProvinceValueEntries(data);
    const values = Array.from(valueByProvince.values()).map(item => item.value);
    const maxValue = Math.max(...values, 0);

    if (!maxValue) {
        container.replaceChildren();
        showNoDataMessage('chart-province-map', 'Không có dữ liệu tỉnh/thành để hiển thị.');
        return;
    }

    hideNoDataMessage('chart-province-map');
    container.replaceChildren();
    const tooltip = getOrCreateProvinceMapTooltip(container);

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', vietnamMapDefinition.viewBox);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.setAttribute('aria-hidden', 'true');

    let activeProvincePath = null;
    let activeProvinceOutline = null;
    const clearActiveProvincePath = () => {
        if (activeProvincePath) {
            activeProvincePath.classList.remove('is-active');
            activeProvincePath = null;
        }
        activeProvinceOutline?.remove();
        activeProvinceOutline = null;
        tooltip.classList.remove('visible');
    };

    const showProvinceOutline = (path) => {
        activeProvinceOutline?.remove();
        activeProvinceOutline = path.cloneNode(false);
        activeProvinceOutline.removeAttribute('tabindex');
        activeProvinceOutline.removeAttribute('aria-label');
        activeProvinceOutline.classList.add('province-hover-outline');
        activeProvinceOutline.setAttribute('fill', 'none');
        activeProvinceOutline.setAttribute('stroke', '#073c52');
        activeProvinceOutline.setAttribute('stroke-width', '1.55');
        activeProvinceOutline.setAttribute('pointer-events', 'none');
        activeProvinceOutline.setAttribute('vector-effect', 'non-scaling-stroke');
        svg.appendChild(activeProvinceOutline);
    };

    container.onpointerleave = clearActiveProvincePath;
    container.onmouseleave = clearActiveProvincePath;

    vietnamMapDefinition.features.forEach(({ path: pathData, properties }) => {
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const provinceName = properties.ten_tinh || properties.name || 'Không xác định';
        const provinceKey = getProvinceMapKey(provinceName);
        const provinceValue = valueByProvince.get(provinceKey);
        const value = provinceValue?.value || 0;
        const fillColor = getProvinceFill(value, maxValue);
        const displayName = provinceValue?.name || provinceName;
        const mergeStatus = getProvinceMergeStatus(provinceName, provinceValue, properties);
        const valueText = value ? formatCurrencyTooltip(value) : 'Không có dữ liệu';

        path.setAttribute('d', pathData);
        path.setAttribute('fill', fillColor);
        path.setAttribute('stroke', '#c2d2da');
        path.setAttribute('stroke-width', '0.7');
        path.setAttribute('stroke-linejoin', 'round');
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('fill-rule', 'evenodd');
        path.setAttribute('vector-effect', 'non-scaling-stroke');
        path.dataset.adminKey = provinceKey;
        path.dataset.province = displayName;
        path.dataset.mapRegion = displayName;
        path.dataset.value = String(value);
        path.dataset.valueText = valueText;
        path.setAttribute('tabindex', '0');
        path.setAttribute('aria-label', `${displayName}: ${valueText}`);

        path.addEventListener('pointerenter', (event) => {
            if (activeProvincePath && activeProvincePath !== path) {
                activeProvincePath.classList.remove('is-active');
            }
            activeProvincePath = path;
            path.classList.add('is-active');
            showProvinceOutline(path);
            tooltip.replaceChildren();
            const nameEl = document.createElement('strong');
            const valueEl = document.createElement('span');
            const partsEl = document.createElement('span');
            nameEl.textContent = displayName;
            valueEl.textContent = valueText;
            partsEl.textContent = mergeStatus;
            tooltip.append(nameEl, valueEl, partsEl);
            tooltip.classList.add('visible');
            moveProvinceMapTooltip(container, tooltip, event);
        });
        path.addEventListener('pointermove', (event) => {
            moveProvinceMapTooltip(container, tooltip, event);
        });
        path.addEventListener('pointerleave', (event) => {
            if (event.relatedTarget?.closest?.('#chart-province-map svg path')) {
                return;
            }
            if (activeProvincePath === path) {
                clearActiveProvincePath();
            } else {
                path.classList.remove('is-active');
            }
        });
        path.addEventListener('focus', () => {
            if (activeProvincePath && activeProvincePath !== path) {
                activeProvincePath.classList.remove('is-active');
            }
            activeProvincePath = path;
            path.classList.add('is-active');
            showProvinceOutline(path);
        });
        path.addEventListener('blur', () => {
            if (activeProvincePath === path) {
                clearActiveProvincePath();
            } else {
                path.classList.remove('is-active');
            }
        });

        svg.appendChild(path);
    });

    container.appendChild(svg);
    container.appendChild(createProvinceMapLegend(maxValue));
    provincePreviewVersion += 1;
    requestAnimationFrame(() => fitProvinceMapViewBox(svg));
}

function renderInsightPreviewBars(containerId, values = []) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const bars = Array.from(container.querySelectorAll('span'));
    const maxValue = Math.max(...values, 0);

    bars.forEach((bar, index) => {
        const value = Number(values[index] || 0);
        const ratio = maxValue > 0 ? value / maxValue : 0;
        bar.style.height = `${Math.max(8, Math.round(12 + ratio * 34))}px`;
        bar.classList.toggle('is-empty', !value);
    });
}

function renderInsightPreviewLine(values = []) {
    const container = document.getElementById('insight-preview-timeline');
    if (!container) return;

    const points = Array.from(container.querySelectorAll('span'));
    const maxValue = Math.max(...values, 0);
    const minValue = Math.min(...values.filter(value => value > 0), maxValue);
    const range = Math.max(1, maxValue - minValue);

    points.forEach((point, index) => {
        const value = Number(values[index] || 0);
        const ratio = maxValue > 0 ? (value - minValue) / range : 0;
        point.style.left = `${12 + index * 18}%`;
        point.style.right = 'auto';
        point.style.top = 'auto';
        point.style.bottom = `${12 + Math.max(0, ratio) * 38}px`;
        point.classList.toggle('is-empty', !value);
    });

    container.style.setProperty('--preview-line-gradient', buildPreviewLineGradient(values));
}

function buildPreviewLineGradient(values = []) {
    if (!values.length || !Math.max(...values, 0)) {
        return 'linear-gradient(90deg, transparent, transparent)';
    }

    return 'linear-gradient(135deg, transparent 0 18%, #1b866e 19% 22%, transparent 23% 44%, #1b866e 45% 48%, transparent 49% 67%, #1b866e 68% 71%, transparent 72%)';
}

function renderInsightPreviewProvinceMap() {
    // Keep the sidebar thumbnail lightweight; the full map is rendered in the
    // selected chart panel.
}

function updateInsightDataPreviews(totalRecords = getInsightResultCounts().total) {
    if (!isInsightDrawerOpen()) return;

    if (!totalRecords) {
        if (insightPreviewSignature === 'empty') return;
        insightPreviewSignature = 'empty';
        renderInsightPreviewBars('insight-preview-price', []);
        renderInsightPreviewLine([]);
        return;
    }

    const histogramData = (chartInstances.histogram?.data?.datasets?.[0]?.data || [])
        .map(point => typeof point === 'object' ? point?.y : point)
        .filter(value => Number.isFinite(Number(value)))
        .slice(0, 5);
    const timelineData = (chartInstances.timeline?.data?.datasets?.[0]?.data || []).slice(-4);
    const nextSignature = [
        totalRecords,
        provincePreviewVersion,
        histogramData.join(','),
        timelineData.join(',')
    ].join('|');

    if (nextSignature === insightPreviewSignature) return;
    insightPreviewSignature = nextSignature;

    renderInsightPreviewBars('insight-preview-price', histogramData);
    renderInsightPreviewLine(timelineData);
    renderInsightPreviewProvinceMap();
}

const MAX_EXACT_PRICE_VALUES = 10;
const MAX_PRICE_BINS = 10;
// Temporary chart-only guard for rows whose monetary fields are clearly
// contaminated (for example, total value copied into unit price). The source
// row remains untouched in the result tables and exports.
const CHART_OUTLIER_THRESHOLD_VND = 50_000_000_000;

function isChartOutlier(row) {
    const unitPrice = Number(getFirstRawColumnValue(row, ['winning_unit_price']));
    const explicitTotal = Number(getFirstRawColumnValue(row, ['total_value', 'winning_total_value']));
    const quantity = Number(getFirstRawColumnValue(row, ['quantity']));
    const derivedTotal = !Number.isFinite(explicitTotal) && Number.isFinite(quantity) && quantity > 0
        && Number.isFinite(unitPrice) && unitPrice > 0
        ? quantity * unitPrice
        : 0;

    return [unitPrice, explicitTotal, derivedTotal]
        .some(value => Number.isFinite(value) && value > CHART_OUTLIER_THRESHOLD_VND);
}

function getChartRows(data = []) {
    return (Array.isArray(data) ? data : []).filter(row => !isChartOutlier(row));
}

function buildPriceDistribution(priceValues = []) {
    const priceMap = new Map();
    priceValues.forEach(value => {
        const price = Number(value);
        if (Number.isFinite(price) && price > 0) {
            priceMap.set(price, (priceMap.get(price) || 0) + 1);
        }
    });

    const sorted = Array.from(priceMap.entries())
        .map(([price, count]) => ({ price, count }))
        .sort((a, b) => a.price - b.price);
    const formatPrice = value => Number(value).toLocaleString('vi-VN', { maximumFractionDigits: 2 });

    if (sorted.length <= MAX_EXACT_PRICE_VALUES) {
        return {
            mode: 'exact',
            labels: sorted.map(item => item.price),
            values: sorted.map(item => item.count),
            datasetData: sorted.map(item => ({ x: item.price, y: item.count }))
        };
    }

    const minPrice = sorted[0].price;
    const maxPrice = sorted[sorted.length - 1].price;
    const rawStep = (maxPrice - minPrice) / MAX_PRICE_BINS;
    const magnitude = 10 ** Math.floor(Math.log10(rawStep));
    const normalizedStep = rawStep / magnitude;
    const stepMultiplier = normalizedStep <= 1 ? 1 : normalizedStep <= 2 ? 2 : normalizedStep <= 5 ? 5 : 10;
    const step = stepMultiplier * magnitude;
    const firstBinStart = Math.floor(minPrice / step) * step;
    const binCount = Math.max(1, Math.ceil((maxPrice - firstBinStart) / step));
    const bins = Array.from({ length: binCount }, (_, index) => ({
        start: firstBinStart + index * step,
        end: firstBinStart + (index + 1) * step,
        count: 0
    }));

    sorted.forEach(item => {
        const index = Math.min(bins.length - 1, Math.floor((item.price - firstBinStart) / step));
        bins[index].count += item.count;
    });

    return {
        mode: 'binned',
        labels: bins.map(bin => `${formatPrice(bin.start)} – ${formatPrice(bin.end)}`),
        values: bins.map(bin => bin.count),
        binSize: step
    };
}

const CHART_CONFIG = {
    histogram: {
        canvasId: 'chart-price-histogram',
        type: 'bar',
        color: CHART_THEME.primary,
        getData: (data) => buildPriceDistribution(
            data.map(row => getFirstRawColumnValue(row, ['winning_unit_price']))
        ),
        getType: (chartData = {}) => chartData.mode === 'exact' && chartData.labels?.length > 1 ? 'scatter' : 'bar',
        getOptions: (chartData = {}) => ({
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'nearest', axis: 'x', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: CHART_THEME.surface,
                    titleColor: CHART_THEME.axisStrong,
                    bodyColor: CHART_THEME.axis,
                    borderColor: CHART_THEME.border,
                    borderWidth: 1,
                    padding: 10,
                    displayColors: false,
                    callbacks: {
                        title: (items) => {
                            const item = items[0];
                            if (chartData.mode === 'exact') {
                                const price = Number(chartData.labels?.length > 1
                                    ? item?.parsed?.x
                                    : item?.label);
                                return `Giá: ${formatPriceAxis(price)}`;
                            }
                            return `Khoảng giá: ${item?.label || ''}`;
                        },
                        label: (item) => `Số bản ghi: ${item.formattedValue}`
                    }
                }
            },
            scales: {
                x: {
                    type: chartData.mode === 'exact' && chartData.labels?.length > 1 ? 'linear' : 'category',
                    offset: !(chartData.mode === 'exact' && chartData.labels?.length > 1),
                    grid: { display: false },
                    ticks: chartData.mode === 'exact' && chartData.labels?.length > 1
                        ? {
                            autoSkip: true,
                            maxTicksLimit: 8,
                            maxRotation: 45,
                            minRotation: 0,
                            callback: value => formatPriceAxis(value),
                            font: { size: 12 },
                            color: CHART_THEME.axis
                        }
                        : {
                            autoSkip: true,
                            maxRotation: 45,
                            minRotation: 45,
                            font: { size: 12 },
                            color: CHART_THEME.axis
                        }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: CHART_THEME.grid },
                    ticks: { stepSize: 1, font: { size: 12 }, color: CHART_THEME.axis }
                }
            },
            layout: { padding: { top: 10, bottom: 10 } }
        })
    },
    
    timeline: {
        canvasId: 'chart-timeline-value',
        type: 'line',
        color: CHART_THEME.accent,
        getData: (data) => {
            const monthlyValue = {};
            
            data.forEach(r => {
                const dateStr = getFirstRawColumnValue(r, ['decision_issued_at', 'result_posted_at']);
                const value = getChartTotalValue(r);
                if (!dateStr || value === 0) return;
                
                const monthKey = parseMonthKey(dateStr);
                if (monthKey) {
                    monthlyValue[monthKey] = (monthlyValue[monthKey] || 0) + value;
                }
            });
            
            const sorted = Object.entries(monthlyValue).sort((a, b) => a[0].localeCompare(b[0]));
            
            return {
                labels: sorted.map(([month]) => {
                    const [year, m] = month.split('-');
                    return `${m}/${year}`;
                }),
                values: sorted.map(([, value]) => value)
            };
        },
        getOptions: () => ({
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'nearest', axis: 'x', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: CHART_THEME.surface,
                    titleColor: CHART_THEME.axisStrong,
                    bodyColor: CHART_THEME.axis,
                    borderColor: CHART_THEME.border,
                    borderWidth: 1,
                    padding: 10,
                    displayColors: false,
                    callbacks: {
                        label: (item) => formatCurrencyTooltip(Number(item.raw))
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { maxRotation: 45, minRotation: 45, font: { size: 12 }, color: CHART_THEME.axis }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: CHART_THEME.grid },
                    ticks: {
                        callback: (value) => formatCurrencyAxis(value),
                        font: { size: 12 },
                        color: CHART_THEME.axis
                    }
                }
            },
            layout: { padding: { top: 10, bottom: 10 } }
        }),
        datasetConfig: {
            backgroundColor: CHART_THEME.accentSoft,
            borderWidth: 3,
            fill: true,
            tension: 0.4,
            pointRadius: 5,
            pointBorderColor: '#fff',
            pointBorderWidth: 2,
            pointHoverRadius: 7,
            pointHitRadius: 20
        }
    }
};

// Helper functions
function formatPriceAxis(value) {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue)) return '';
    return numericValue.toLocaleString('vi-VN', { maximumFractionDigits: 2 });
}

function formatCurrencyAxis(value) {
    if (value >= 1_000_000_000) {
        return `${(value / 1_000_000_000).toLocaleString('vi-VN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} tỷ`;
    }
    if (value >= 1_000_000) {
        return `${(value / 1_000_000).toLocaleString('vi-VN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} triệu`;
    }
    return value.toLocaleString('vi-VN', { maximumFractionDigits: 0 });
}

function formatCurrencyTooltip(value) {
    if (value >= 1_000_000_000) {
        return `${(value / 1_000_000_000).toLocaleString('vi-VN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} tỷ`;
    }
    if (value >= 1_000_000) {
        return `${(value / 1_000_000).toLocaleString('vi-VN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} triệu`;
    }
    return value.toLocaleString('vi-VN', { maximumFractionDigits: 0 });
}

function parseMonthKey(dateStr) {
    try {
        if (dateStr instanceof Date) {
            return isNaN(dateStr.getTime())
                ? null
                : `${dateStr.getFullYear()}-${String(dateStr.getMonth() + 1).padStart(2, '0')}`;
        }

        dateStr = String(dateStr || '').trim();
        let dateObj;
        if (dateStr.includes('/')) {
            const parts = dateStr.split('/');
            if (parts.length === 3) {
                dateObj = new Date(parts[2], parts[1] - 1, parts[0]);
            }
        } else if (dateStr.includes('-')) {
            dateObj = new Date(dateStr);
        }
        
        if (dateObj && !isNaN(dateObj.getTime())) {
            return `${dateObj.getFullYear()}-${String(dateObj.getMonth() + 1).padStart(2, '0')}`;
        }
    } catch (e) {
        // Skip invalid dates
    }
    return null;
}

const INSIGHT_CHART_META = {
    province: {
        title: 'Theo tỉnh/thành',
        description: 'Bản đồ tổng giá trị trúng thầu theo từng tỉnh/thành trong kết quả hiện tại.'
    },
    price: {
        title: 'Phân bố đơn giá',
        description: 'Hiển thị từng mức giá khi có tối đa 10 giá khác nhau; nhiều hơn sẽ chia theo khoảng giá.'
    },
    timeline: {
        title: 'Theo thời gian',
        description: 'Đường xu hướng tổng giá trị trúng thầu theo tháng phê duyệt.'
    }
};

let activeInsightChart = 'province';
let insightEntryPointUpdateFrame = null;
let pendingInsightTotalRecords = null;
let provincePreviewVersion = 0;
let insightPreviewSignature = '';
let insightDrawerCloseTimer = null;

function getInsightResultCounts() {
    const df1Count = currentFilteredDf1?.length || 0;
    const df2Count = currentFilteredDf2?.length || 0;
    const df3Count = currentFilteredDf3?.length || 0;
    return {
        df1Count,
        df2Count,
        df3Count,
        total: df1Count + df2Count + df3Count
    };
}

function formatInsightResultSummary(counts = getInsightResultCounts()) {
    const totalText = Number(counts.total || 0).toLocaleString('vi-VN');
    const df1Text = Number(counts.df1Count || 0).toLocaleString('vi-VN');
    const df2Text = Number(counts.df2Count || 0).toLocaleString('vi-VN');
    const df3Text = Number(counts.df3Count || 0).toLocaleString('vi-VN');
    return `${totalText} bản ghi: ${df1Text} thuốc, ${df2Text} hàng hóa, ${df3Text} dược liệu`;
}

function formatDockQuotaLine(quota = getFullSearchQuotaState()) {
    if (!quota.enabled || Number(quota.limit || 0) <= 0) {
        return 'Tìm kiếm mở rộng hiện chưa khả dụng';
    }

    return `Bạn còn ${Number(quota.remaining || 0).toLocaleString('vi-VN')}/${Number(quota.limit || 0).toLocaleString('vi-VN')} lượt hôm nay`;
}

function canRunDockFullSearch(quota = getFullSearchQuotaState()) {
    const hasQuery = Boolean(currentQueryRequest);
    const hasLoadedRows = Number(currentQueryMeta.df1Displayed || 0)
        + Number(currentQueryMeta.df2Displayed || 0)
        + Number(currentQueryMeta.df3Displayed || 0) > 0;
    const hasMoreRows = ['standard-table', 'extended-table', 'traditional-table']
        .some(hasMoreRowsBeyondWorkingSet);
    const alreadyFullSearch = currentQueryMeta.searchMode === 'full'
        || (currentQueryMeta.searchMode === 'bulk' && currentQueryMeta.bulkSearchMode === 'full');

    return hasQuery
        && hasLoadedRows
        && hasMoreRows
        && !fullSearchInFlight
        && !alreadyFullSearch
        && quota.enabled
        && Number(quota.limit || 0) > 0
        && Number(quota.remaining || 0) > 0;
}

function isDataDockContextAllowed() {
    const dataTabActive = document.getElementById('data-tab')?.classList.contains('active');

    return dataTabActive && !document.body.classList.contains('landing-active');
}

function scheduleInsightEntryPointUpdate(totalRecords = null) {
    pendingInsightTotalRecords = totalRecords;
    if (insightEntryPointUpdateFrame !== null) return;

    insightEntryPointUpdateFrame = requestAnimationFrame(() => {
        const nextTotalRecords = pendingInsightTotalRecords;
        pendingInsightTotalRecords = null;
        insightEntryPointUpdateFrame = null;
        updateInsightEntryPoint(nextTotalRecords ?? getInsightResultCounts().total);
    });
}

function updateInsightEntryPoint(totalRecords = getInsightResultCounts().total) {
    const dockFullSearchButton = document.getElementById('insight-full-search');
    const dockFullSearchLabel = document.getElementById('insight-full-search-label');
    const openButton = document.getElementById('open-insight-drawer');
    if (!dockFullSearchButton && !openButton) return;

    if (!isDataDockContextAllowed()) {
        if (isInsightDrawerOpen()) closeInsightDrawer();
        return;
    }

    const counts = getInsightResultCounts();
    const hasData = Number(totalRecords || counts.total) > 0;
    const quota = getFullSearchQuotaState();

    if (dockFullSearchButton) {
        dockFullSearchButton.disabled = !canRunDockFullSearch(quota);
        dockFullSearchButton.classList.toggle('is-empty', !quota.enabled || quota.remaining <= 0);
        if (dockFullSearchLabel) dockFullSearchLabel.textContent = Number(quota.remaining || 0).toLocaleString('vi-VN');
        const quotaText = formatDockQuotaLine(quota);
        setActionTooltip(dockFullSearchButton, `Tìm kiếm mở rộng. ${quotaText}`);
    }
    if (openButton) {
        openButton.disabled = false;
        openButton.classList.toggle('is-empty', !hasData);
        openButton.classList.toggle('is-open', isInsightDrawerOpen());
        setActionTooltip(openButton, hasData
            ? 'Phân tích trực quan'
            : 'Phân tích trực quan');
    }
}

function refreshVisibleInsightChart() {
    requestAnimationFrame(() => {
        Object.values(chartInstances).forEach(chart => chart?.resize?.());

        if (activeInsightChart === 'province') {
            const svg = document.querySelector('#chart-province-map svg');
            if (svg) fitProvinceMapViewBox(svg);
        }
    });
}

function setActiveInsightChart(chartKey = 'province', { redraw = false } = {}) {
    if (!INSIGHT_CHART_META[chartKey]) return;
    activeInsightChart = chartKey;

    document.querySelectorAll('[data-chart-view]').forEach(button => {
        const isActive = button.dataset.chartView === chartKey;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-pressed', String(isActive));
    });

    document.querySelectorAll('[data-chart-panel]').forEach(panel => {
        panel.classList.toggle('active', panel.dataset.chartPanel === chartKey);
    });

    updateInsightEntryPoint();

    if (redraw && insightChartsDirty) {
        requestAnimationFrame(() => {
            const chartData = getInsightChartDataSets();
            void drawCharts(chartData.df1, chartData.df2, chartData.df3);
        });
    } else {
        refreshVisibleInsightChart();
    }
}

function openInsightDrawer() {
    const drawer = document.getElementById('insight-drawer');
    const openButton = document.getElementById('open-insight-drawer');
    if (!drawer || !openButton) return;

    closeFloatingTableUi();
    if (insightDrawerCloseTimer) {
        window.clearTimeout(insightDrawerCloseTimer);
        insightDrawerCloseTimer = null;
    }
    drawer.classList.remove('is-closing');
    drawer.classList.add('show');
    drawer.setAttribute('aria-hidden', 'false');
    openButton.setAttribute('aria-expanded', 'true');
    openButton.classList.add('is-open');
    document.body.classList.add('insight-drawer-open');

    setActiveInsightChart(activeInsightChart, { redraw: true });
}

function closeInsightDrawer() {
    const drawer = document.getElementById('insight-drawer');
    const openButton = document.getElementById('open-insight-drawer');
    if (!drawer) return;
    const isOpen = drawer.classList.contains('show');
    if (!isOpen && drawer.getAttribute('aria-hidden') === 'true' && !document.body.classList.contains('insight-drawer-open')) {
        openButton?.setAttribute('aria-expanded', 'false');
        openButton?.classList.remove('is-open');
        return;
    }

    openButton?.setAttribute('aria-expanded', 'false');
    openButton?.classList.remove('is-open');
    if (drawer.classList.contains('is-closing')) return;

    drawer.classList.add('is-closing');
    drawer.classList.remove('show');
    insightDrawerCloseTimer = window.setTimeout(() => {
        insightDrawerCloseTimer = null;
        drawer.classList.remove('is-closing');
        if (drawer.getAttribute('aria-hidden') !== 'true') drawer.setAttribute('aria-hidden', 'true');
        if (document.body.classList.contains('insight-drawer-open')) {
            document.body.classList.remove('insight-drawer-open');
        }
    }, 440);
}

function isInsightDrawerOpen() {
    const drawer = document.getElementById('insight-drawer');
    return Boolean(drawer?.classList.contains('show') || drawer?.classList.contains('is-closing'));
}

function initInsightDrawerEvents() {
    document.getElementById('open-insight-drawer')?.addEventListener('click', () => {
        if (isInsightDrawerOpen()) {
            closeInsightDrawer();
        } else {
            openInsightDrawer();
        }
    });
    document.querySelector('[data-insight-close]')?.addEventListener('click', closeInsightDrawer);
    document.getElementById('close-insight-drawer')?.addEventListener('click', closeInsightDrawer);
    document.getElementById('insight-full-search')?.addEventListener('click', () => {
        void triggerFullSearch();
    });

    document.querySelectorAll('[data-chart-view]').forEach(button => {
        button.addEventListener('click', () => setActiveInsightChart(button.dataset.chartView, { redraw: true }));
    });

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && document.getElementById('insight-drawer')?.classList.contains('show')) {
            closeInsightDrawer();
        }
    });

    const dockVisibilityObserver = new MutationObserver(() => scheduleInsightEntryPointUpdate());
    dockVisibilityObserver.observe(document.body, {
        attributes: true,
        attributeFilter: ['class']
    });
    document.querySelectorAll('.side-panel, .history-modal, .readme-modal, .contact-modal, .bulk-search-modal, .feedback-modal, .auth-modal, .panel-overlay').forEach(element => {
        dockVisibilityObserver.observe(element, {
            attributes: true,
            attributeFilter: ['class', 'aria-hidden']
        });
    });

    setActiveInsightChart(activeInsightChart);
    updateInsightEntryPoint(0);
}

function initEmptyCharts() {
    destroyCharts();
    Object.values(CHART_CONFIG).forEach(config => {
        const canvas = document.getElementById(config.canvasId);
        if (!canvas) return;

        hideNoDataMessage(config.canvasId);
        const ctx = canvas.getContext('2d');
        if (ctx) {
            ctx.clearRect(0, 0, canvas.width || canvas.clientWidth || 300, canvas.height || canvas.clientHeight || 150);
        }
    });
    document.getElementById('chart-province-map')?.replaceChildren();
    lastProvinceMapData = [];
    insightPreviewSignature = '';
    insightChartsDirty = true;
    updateInsightEntryPoint(0);
}

function destroyCharts() {
    Object.keys(chartInstances).forEach(key => {
        if (chartInstances[key]) {
            chartInstances[key].destroy();
            chartInstances[key] = null;
        }
    });
}

async function drawCharts(df1Data, df2Data, df3Data = []) {
    const totalRecords = (df1Data?.length || 0) + (df2Data?.length || 0) + (df3Data?.length || 0);
    const noDataMsg = 'Chưa có dữ liệu. Vui lòng thực hiện tìm kiếm.';
    
    destroyCharts();
    updateInsightEntryPoint(totalRecords);

    if (!isInsightDrawerOpen()) {
        insightChartsDirty = true;
        return;
    }
    
    if (totalRecords === 0) {
        showNoDataMessage('chart-province-map', noDataMsg);
        Object.values(CHART_CONFIG).forEach(config => {
            showNoDataMessage(config.canvasId, noDataMsg);
        });
        updateInsightDataPreviews(0);
        insightChartsDirty = false;
        return;
    }

    try {
        await ensureChartJsLoaded();
    } catch (error) {
        console.error('Unable to load Chart.js for visual analysis', error);
        Object.values(CHART_CONFIG).forEach(config => {
            showNoDataMessage(config.canvasId, 'Không tải được thư viện biểu đồ.');
        });
        return;
    }

    if (!isInsightDrawerOpen()) {
        insightChartsDirty = true;
        return;
    }
    
    const allData = [...df1Data, ...df2Data, ...df3Data];
    const chartData = getChartRows(allData);
    renderProvinceValueMap(chartData);
    
    // Draw each chart
    Object.entries(CHART_CONFIG).forEach(([key, config]) => {
        try {
            drawChart(key, config, chartData);
        } catch (error) {
            console.error(`Unable to draw ${key} insight chart`, error);
            showNoDataMessage(config.canvasId, 'Không thể hiển thị biểu đồ này.');
        }
    });
    updateInsightDataPreviews(totalRecords);
    insightChartsDirty = false;
}

function showNoDataMessage(canvasId, message) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    
    canvas.classList.add('hidden');
    
    let msg = canvas.parentElement.querySelector('.no-data-msg');
    if (!msg) {
        msg = document.createElement('p');
        msg.className = 'no-data-msg';
        msg.textContent = message;
        canvas.parentElement.appendChild(msg);
    }
    msg.classList.add('visible');
}

function hideNoDataMessage(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    
    const msg = canvas.parentElement.querySelector('.no-data-msg');
    if (msg) msg.classList.remove('visible');
    canvas.classList.remove('hidden');
}

function drawChart(key, config, data) {
    const canvas = document.getElementById(config.canvasId);
    if (!canvas) return;
    
    const chartData = config.getData(data);
    
    if (!chartData.labels.length || !chartData.values.length) {
        showNoDataMessage(config.canvasId, 'Chưa đủ dữ liệu để hiển thị biểu đồ.');
        return;
    }
    
    hideNoDataMessage(config.canvasId);
    
    const ctx = canvas.getContext('2d');
    const chartType = config.getType ? config.getType(chartData) : config.type;
    const dataset = {
        label: key === 'histogram' ? 'Số lượng bản ghi' : 'Tổng trị giá (VND)',
        // Point objects are only valid for the exact-price scatter chart.
        // A singleton exact-price result is rendered as a category bar chart,
        // so it must receive plain numeric values instead of { x, y } points.
        data: chartType === 'scatter'
            ? (chartData.datasetData || chartData.values)
            : chartData.values,
        ...config.datasetConfig
    };
    // Apply colors
    if (chartType === 'bar' && key === 'histogram') {
        dataset.backgroundColor = config.color;
        dataset.borderRadius = 6;
        dataset.maxBarThickness = 48;
    } else if (chartType === 'scatter' && key === 'histogram') {
        dataset.backgroundColor = config.color;
        dataset.borderColor = config.color;
        dataset.showLine = false;
        dataset.parsing = { xAxisKey: 'x', yAxisKey: 'y' };
        dataset.pointRadius = 6;
        dataset.pointHoverRadius = 8;
        dataset.pointHitRadius = 20;
    } else if (chartType === 'line') {
        dataset.borderColor = config.color;
        dataset.pointBackgroundColor = config.color;
    }
    
    chartInstances[key] = new window.Chart(ctx, {
        type: chartType,
        data: {
            ...(chartType === 'scatter' ? {} : { labels: chartData.labels }),
            datasets: [dataset]
        },
        options: config.getOptions(chartData)
    });
}

// ======== 2. METADATA
let metadata = null;
let appDataInitialized = false;
let historyTimelineChart = null;
let activeHistoryRangeDays = 30;

function getHistoryDayKey(value) {
    const parsed = value instanceof Date ? new Date(value) : (value ? new Date(value) : null);
    if (!parsed || Number.isNaN(parsed.getTime())) return null;
    parsed.setHours(0, 0, 0, 0);
    const year = parsed.getFullYear();
    const month = String(parsed.getMonth() + 1).padStart(2, '0');
    const day = String(parsed.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function buildHistoryTimelineData(timeline, rangeDays = 30) {
    const countsByDay = new Map();
    (Array.isArray(timeline) ? timeline : []).forEach((item) => {
        const dayKey = getHistoryDayKey(item?.date);
        if (!dayKey) return;
        countsByDay.set(dayKey, Number(item?.count || 0));
    });

    const labels = [];
    const values = [];
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    for (let offset = rangeDays - 1; offset >= 0; offset -= 1) {
        const date = new Date(today);
        date.setDate(today.getDate() - offset);
        const dayKey = getHistoryDayKey(date);
        labels.push(date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }));
        values.push(countsByDay.get(dayKey) || 0);
    }

    return { labels, values };
}

function destroyHistoryTimelineChart() {
    if (historyTimelineChart) {
        historyTimelineChart.destroy();
        historyTimelineChart = null;
    }
}

function updateHistoryRangeButtons() {
    document.querySelectorAll('[data-history-range]').forEach((btn) => {
        btn.classList.toggle('active', Number(btn.dataset.historyRange) === activeHistoryRangeDays);
    });
}

function renderHistoryTimelineChart(timeline) {
    const chartCanvas = document.getElementById('history-timeline-chart');
    const emptyState = document.querySelector('#history-list .history-empty');
    if (!chartCanvas) return;

    const normalizedTimeline = Array.isArray(timeline) ? timeline.filter((item) => item?.date) : [];
    if (!normalizedTimeline.length) {
        destroyHistoryTimelineChart();
        chartCanvas.hidden = true;
        if (emptyState) emptyState.hidden = false;
        return;
    }

    const { labels, values } = buildHistoryTimelineData(normalizedTimeline, activeHistoryRangeDays);
    chartCanvas.hidden = false;
    if (emptyState) emptyState.hidden = true;

    destroyHistoryTimelineChart();

    const ctx = chartCanvas.getContext('2d');
    if (!ctx) return;

    const gradient = ctx.createLinearGradient(0, 0, 0, chartCanvas.height || 280);
    gradient.addColorStop(0, 'rgba(18, 116, 149, 0.24)');
    gradient.addColorStop(1, 'rgba(18, 116, 149, 0.02)');

    historyTimelineChart = new window.Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Số gói thầu đăng tải KQLCNT',
                data: values,
                borderColor: '#127495',
                backgroundColor: gradient,
                fill: true,
                tension: 0.35,
                cubicInterpolationMode: 'monotone',
                spanGaps: true,
                pointRadius: 0,
                pointHoverRadius: 4,
                pointHoverBackgroundColor: '#127495',
                pointHoverBorderColor: '#ffffff',
                pointHoverBorderWidth: 2,
                borderWidth: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 34, 48, 0.92)',
                    titleColor: '#ffffff',
                    bodyColor: '#e8f2f6',
                    displayColors: false,
                    padding: 12,
                    callbacks: {
                        title(items) {
                            return items?.[0]?.label || '';
                        },
                        label(context) {
                            return `${Number(context.parsed?.y || 0).toLocaleString('vi-VN')} gói thầu`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        color: '#6f8594',
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 8
                    },
                    border: {
                        color: 'rgba(191, 214, 223, 0.8)'
                    }
                },
                y: {
                    beginAtZero: true,
                    ticks: {
                        color: '#6f8594',
                        precision: 0
                    },
                    grid: {
                        color: 'rgba(213, 226, 231, 0.78)'
                    },
                    border: {
                        color: 'rgba(191, 214, 223, 0.8)'
                    }
                }
            }
        }
    });
}

async function loadMetadata() {
    if (!requireAuthenticatedSession('login', 'metadata')) {
        metadata = null;
        return;
    }

    try {
        console.log('🔄 Đang tải metadata...');
        const res = await getAuthorizedFetch()(`${API_BASE_URL}/api/metadata`);
        const meta = await res.json();
        
        console.log('📦 Response từ API:', meta);
        
        if (meta.success) {
            metadata = meta;
            markDatabaseWarm();
            console.log('✅ Load metadata thành công:', metadata);
        } else {
            console.warn('⚠️ API trả về success=false:', meta.message);
        }
    } catch (e) {
        console.error('❌ Load metadata error:', e);
    }
}

function showHistoryModal() {
    if (!requireAuthenticatedSession('login', 'metadata')) return;

    const modal = document.getElementById('history-modal');
    const updateTimeline = metadata?.update_timeline || [];
    const hasData = Array.isArray(updateTimeline) && updateTimeline.length > 0;
    updateHistoryRangeButtons();
    
    modal.classList.add('show');
    feather.replace();

    if (hasData) {
        void ensureChartJsLoaded()
            .then(() => renderHistoryData(updateTimeline))
            .catch(error => console.error('Unable to load Chart.js for history', error));
    } else {
        renderEmptyHistory();
    }
}

function renderHistoryData(historyTimeline) {
    renderHistoryTimelineChart(historyTimeline || []);
}

function renderEmptyHistory() {
    renderHistoryTimelineChart([]);
}

// ============================== 
// CELL/RANGE OPERATION & FORMULA BAR
// ============================== 
function getCellPos(td){
    const tr = td.parentElement;
    const table = td.closest("table");
    const tbody = table.tBodies[0];
    const rowIndex = Array.prototype.indexOf.call(tbody.rows, tr);      // index trong tbody
    const colIndex = Array.prototype.indexOf.call(tr.cells, td);        // index trong row
    return { rowIndex, colIndex };
}

function clearRange(table){
    table.querySelectorAll("td.cell-range, td.cell-active, td.cell-selected").forEach(td=>{
        td.classList.remove("cell-range","cell-active","cell-selected");
    });
}

function applyRange(tableId){
    const table = document.getElementById(tableId);
    if (!table) return;

    const st = tableSel[tableId];
    if (!st.start || !st.end) return;

    clearRange(table);

    const r1 = Math.min(st.start.rowIndex, st.end.rowIndex);
    const r2 = Math.max(st.start.rowIndex, st.end.rowIndex);
    const c1 = Math.min(st.start.colIndex, st.end.colIndex);
    const c2 = Math.max(st.start.colIndex, st.end.colIndex);
    const isSingleCell = r1 === r2 && c1 === c2;

    const rows = table.tBodies[0]?.rows || [];
    for (let r=r1; r<=r2; r++){
        const cells = rows[r]?.cells || [];
        for (let c=c1; c<=c2; c++){
        const td = cells[c];
        if (!td) continue;
        td.classList.add(isSingleCell ? "cell-selected" : "cell-range");
        }
    }

    // active cell: end
    const endTd = (rows[st.end.rowIndex]?.cells || [])[st.end.colIndex];
    if (endTd) endTd.classList.add("cell-active");

    // build clipboard text (TSV)
    const lines = [];
    for (let r=r1; r<=r2; r++){
        const cells = rows[r]?.cells || [];
        const line = [];
        for (let c=c1; c<=c2; c++){
        const v = (cells[c]?.textContent || "").trim().replace(/\s+/g, " ");
        line.push(v);
        }
        lines.push(line.join("\t"));
    }
    st.text = lines.join("\n");
    st.lastActive = Date.now();
    st.suppressRowClick = true;
    setBarText(tableId, getTopLeftCellText(tableId));
}

function getNavigableCellIndexes(row) {
    return Array.from(row?.cells || [])
        .map((cell, index) => ({ cell, index }))
        .filter(({ cell }) => {
            if (cell.classList.contains('row-selector-cell') || cell.classList.contains('table-empty-state')) return false;
            return !cell.hidden && window.getComputedStyle(cell).display !== 'none';
        })
        .map(({ index }) => index);
}

function moveTableActiveCell(tableId, rowDelta, columnDelta, extendRange = false) {
    const table = document.getElementById(tableId);
    const state = tableSel[tableId];
    const rows = table?.tBodies?.[0]?.rows || [];
    if (!table || !state?.end || !rows.length) return false;

    const current = state.end;
    const currentRow = rows[current.rowIndex];
    const currentIndexes = getNavigableCellIndexes(currentRow);
    if (!currentRow || !currentIndexes.includes(current.colIndex)) return false;

    const targetRowIndex = Math.max(0, Math.min(rows.length - 1, current.rowIndex + rowDelta));
    const targetRow = rows[targetRowIndex];
    const targetIndexes = getNavigableCellIndexes(targetRow);
    if (!targetIndexes.length) return false;

    let targetColIndex = current.colIndex;
    if (columnDelta) {
        const currentPosition = currentIndexes.indexOf(current.colIndex);
        const targetPosition = Math.max(0, Math.min(
            currentIndexes.length - 1,
            currentPosition + columnDelta,
        ));
        targetColIndex = currentIndexes[targetPosition];
    }

    if (!targetIndexes.includes(targetColIndex)) {
        targetColIndex = targetIndexes.reduce((closest, index) => (
            Math.abs(index - current.colIndex) < Math.abs(closest - current.colIndex) ? index : closest
        ), targetIndexes[0]);
    }

    const next = { rowIndex: targetRowIndex, colIndex: targetColIndex };
    if (extendRange) {
        state.start = state.start || { ...state.end };
    } else {
        state.start = { ...next };
    }
    state.end = next;
    clearRowSelection(tableId);
    clearColumnSelection(tableId);
    applyRange(tableId);

    rows[targetRowIndex]?.cells?.[targetColIndex]?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
    return true;
}

function initTableKeyboardNavigation(tableId) {
    const table = document.getElementById(tableId);
    if (!table || table.dataset.keyboardNavigationBound === '1') return;

    table.dataset.keyboardNavigationBound = '1';
    table.tabIndex = 0;
    table.addEventListener('mousedown', event => {
        const cell = event.target.closest('td');
        if (!cell || cell.classList.contains('row-selector-cell')) return;
        try {
            table.focus({ preventScroll: true });
        } catch (_) {
            table.focus();
        }
    });
    table.addEventListener('keydown', event => {
        const tagName = event.target?.tagName?.toLowerCase();
        if (['input', 'select', 'textarea', 'button'].includes(tagName) || event.target?.isContentEditable) return;

        const movement = {
            ArrowUp: [-1, 0],
            ArrowDown: [1, 0],
            ArrowLeft: [0, -1],
            ArrowRight: [0, 1],
        }[event.key];
        if (!movement || !tableSel[tableId]?.end) return;

        event.preventDefault();
        event.stopPropagation();
        moveTableActiveCell(tableId, movement[0], movement[1], event.shiftKey);
    });
}

function initTableRangeSelect(tableId){
    const table = document.getElementById(tableId);
    if (!table) return;

    // Ngăn browser bôi đen text khi drag
    table.addEventListener("selectstart", (e) => e.preventDefault());

    table.addEventListener("mousedown", (e) => {
        const td = e.target.closest("td");
        if (!td || td.classList.contains('row-selector-cell')) return;

        // chỉ xử lý click trái
        if (e.button !== 0) return;

        const st = tableSel[tableId];
        st.isDown = true;
        st.dragMoved = false;

        if (!(e.ctrlKey || e.metaKey || e.shiftKey)) {
            clearRowSelection(tableId);
            clearColumnSelection(tableId);
            clearCellSelectionForTable(tableId);
        }

        const cellPos = getCellPos(td);
        if (!e.shiftKey || !st.start) {
            st.start = cellPos;
        }
        st.end = cellPos;
        st.suppressRowClick = false;
        st.startTd = td;
        window.getSelection?.().removeAllRanges();
    });

    table.addEventListener("mouseover", (e) => {
        const st = tableSel[tableId];
        if (!st.isDown) return;

        const td = e.target.closest("td");
        if (!td || td.classList.contains('row-selector-cell')) return;

        const nextPos = getCellPos(td);
        if (
            nextPos.rowIndex !== st.end?.rowIndex ||
            nextPos.colIndex !== st.end?.colIndex
        ) {
            st.dragMoved = true;
        }

        st.end = nextPos;
        applyRange(tableId);
        e.preventDefault();
    });

    document.addEventListener("mouseup", () => {
        const st = tableSel[tableId];
        if (!st.isDown) return;

        if (!st.dragMoved && st.startTd) {
            st.start = getCellPos(st.startTd);
            st.end = getCellPos(st.startTd);
            applyRange(tableId);
        }

        st.isDown = false;
        st.suppressRowClick = !!st.dragMoved;
        st.dragMoved = false;
        st.startTd = null;
    });
}

function clearCopiedCellRange() {
    document.querySelectorAll('.table-copy-outline').forEach(outline => outline.remove());
}

function showCopiedCellRange(tableId) {
    clearCopiedCellRange();

    const table = document.getElementById(tableId);
    const state = tableSel[tableId];
    if (!table || !state?.start || !state?.end) return;

    const rows = table.tBodies?.[0]?.rows || [];
    const rowStart = Math.min(state.start.rowIndex, state.end.rowIndex);
    const rowEnd = Math.max(state.start.rowIndex, state.end.rowIndex);
    const colStart = Math.min(state.start.colIndex, state.end.colIndex);
    const colEnd = Math.max(state.start.colIndex, state.end.colIndex);
    const firstCell = rows[rowStart]?.cells?.[colStart];
    const lastCell = rows[rowEnd]?.cells?.[colEnd];
    const scrollContainer = table.closest('.table-scroll');
    if (!firstCell || !lastCell || !scrollContainer) return;

    const firstRect = firstCell.getBoundingClientRect();
    const lastRect = lastCell.getBoundingClientRect();
    const containerRect = scrollContainer.getBoundingClientRect();
    const pixelRatio = window.devicePixelRatio || 1;
    const snapToDevicePixel = value => Math.round(value * pixelRatio) / pixelRatio;
    const left = snapToDevicePixel(firstRect.left - containerRect.left + scrollContainer.scrollLeft);
    const top = snapToDevicePixel(firstRect.top - containerRect.top + scrollContainer.scrollTop);
    const right = snapToDevicePixel(lastRect.right - containerRect.left + scrollContainer.scrollLeft);
    const bottom = snapToDevicePixel(lastRect.bottom - containerRect.top + scrollContainer.scrollTop);
    const width = Math.max(0, right - left);
    const height = Math.max(0, bottom - top);
    const strokeWidth = 1 / pixelRatio;
    const outline = document.createElement('div');
    outline.className = 'table-copy-outline';
    outline.setAttribute('aria-hidden', 'true');
    outline.style.left = `${left}px`;
    outline.style.top = `${top}px`;
    outline.style.width = `${width}px`;
    outline.style.height = `${height}px`;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    const border = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    border.setAttribute('class', 'table-copy-outline-border');
    border.setAttribute('x', String(strokeWidth / 2));
    border.setAttribute('y', String(strokeWidth / 2));
    border.setAttribute('width', String(Math.max(0, width - strokeWidth)));
    border.setAttribute('height', String(Math.max(0, height - strokeWidth)));
    border.setAttribute('stroke-width', String(strokeWidth));
    svg.appendChild(border);
    outline.appendChild(svg);
    scrollContainer.appendChild(outline);
}

function initRangeCopy() {
    // ✅ FIX BUG 1: Copy table được select gần nhất
    document.addEventListener("copy", (e) => {
        // Tìm table có lastActive lớn nhất (được select gần nhất)
        const tables = Object.keys(tableSel);
        const activeTable = tables.reduce((prev, curr) => 
            tableSel[curr].lastActive > tableSel[prev].lastActive ? curr : prev
        );
        
        let text = tableSel[activeTable].text;
        if (!text) {
            text = buildSelectionClipboardText(activeTable);
        }
        if (!text) return;

        e.clipboardData.setData("text/plain", text);
        e.preventDefault();
        showCopiedCellRange(activeTable);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') clearCopiedCellRange();
    });
}

function buildSelectionClipboardText(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return '';

    const state = selectionState[tableId];
    if (!state) return '';

    if (state.rows.size > 0) {
        const rows = Array.from(state.rows).sort((a, b) => a - b);
        return rows
            .map(rowIndex => {
                const row = table.tBodies?.[0]?.rows?.[rowIndex];
                if (!row) return '';
                return Array.from(row.cells)
                    .slice(1)
                    .map(cell => (cell.textContent || '').trim().replace(/\s+/g, ' '))
                    .join('\t');
            })
            .filter(Boolean)
            .join('\n');
    }

    if (state.columns.size > 0) {
        const columnOrder = getVisibleColumnOrder(tableId);
        const selectedColumns = columnOrder.filter(col => state.columns.has(col));
        if (!selectedColumns.length) return '';

        const headerLine = selectedColumns
            .map(columnName => getResultColumnLabel(tableId, columnName))
            .join('\t');
        const bodyLines = Array.from(table.tBodies?.[0]?.rows || []).map(row => {
            return selectedColumns
                .map(columnName => {
                    const cell = row.querySelector(`[data-col-name="${CSS.escape(columnName)}"]`);
                    return (cell?.textContent || '').trim().replace(/\s+/g, ' ');
                })
                .join('\t');
        });

        return [headerLine, ...bodyLines].join('\n');
    }

    return '';
}

// Formula bar
const TABLE_BARS = {
    'standard-table': 'std-cell-value',
    'extended-table': 'ext-cell-value',
    'traditional-table': 'trad-cell-value'
};

function setBarText(tableId, text) {
    const barId = TABLE_BARS[tableId];
    if (!barId) return;

    const el = document.getElementById(barId);
    if (!el) return;

    const safe = (text ?? "").toString().trim();
    el.textContent = safe;
    el.title = safe;
}

/* Lấy text ô top-left của range hiện tại */
function getTopLeftCellText(tableId) {
    const table = document.getElementById(tableId);
    const st = tableSel?.[tableId];
    
    if (!table || !st?.start || !st?.end) return "";

    const r1 = Math.min(st.start.rowIndex, st.end.rowIndex);
    const c1 = Math.min(st.start.colIndex, st.end.colIndex);
    const td = table.tBodies[0]?.rows?.[r1]?.cells?.[c1];
    
    return (td?.textContent || "").trim();
}

function resetCellSelection() {
    clearCopiedCellRange();
    document.querySelectorAll('.cell-selected, .cell-range, .cell-active')
        .forEach(el => el.classList.remove('cell-selected', 'cell-range', 'cell-active'));
    document.querySelectorAll('.row-selected')
        .forEach(el => el.classList.remove('row-selected'));
    document.querySelectorAll('.column-selected')
        .forEach(el => el.classList.remove('column-selected'));
    Object.values(selectionState).forEach(state => {
        state.rows.clear();
        state.columns.clear();
        state.lastRow = null;
        state.lastColumn = null;
    });
    
    ['#std-cell-bar', '#ext-cell-bar', '#trad-cell-bar'].forEach(selector => {
        const bar = document.querySelector(selector);
        if (!bar) return;
        
        const label = bar.querySelector('.cell-display-label');
        const value = bar.querySelector('.cell-display-value');
        
        if (label) label.textContent = '';
        if (value) value.textContent = '';
    });
}

function clearCellSelectionForTable(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    table.querySelectorAll('.cell-selected, .cell-range, .cell-active')
        .forEach(el => el.classList.remove('cell-selected', 'cell-range', 'cell-active'));

    const st = tableSel[tableId];
    if (st) {
        st.start = null;
        st.end = null;
        st.text = '';
    }
}

function clearRowSelection(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    table.querySelectorAll('tr.row-selected').forEach(row => row.classList.remove('row-selected'));
    selectionState[tableId].rows.clear();
}

function clearColumnSelection(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    table.querySelectorAll('.column-selected').forEach(el => el.classList.remove('column-selected'));
    selectionState[tableId].columns.clear();
}

function syncSelectedRows(tableId) {
    const table = document.getElementById(tableId);
    const tbody = table?.tBodies?.[0];
    if (!table || !tbody) return;

    tbody.querySelectorAll('tr.row-selected').forEach(row => row.classList.remove('row-selected'));
    selectionState[tableId].rows.forEach(rowIndex => {
        const row = tbody.rows?.[rowIndex];
        if (row) row.classList.add('row-selected');
    });
}

function syncSelectedColumns(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    table.querySelectorAll('.column-selected').forEach(el => el.classList.remove('column-selected'));
    selectionState[tableId].columns.forEach(columnName => {
        const selector = `[data-col-name="${CSS.escape(columnName)}"]`;
        table.querySelectorAll(selector).forEach(el => el.classList.add('column-selected'));
    });
}

function selectTableRow(tableId, rowIndex, modifiers = {}) {
    const { ctrlKey = false, shiftKey = false } = modifiers;
    const table = document.getElementById(tableId);
    const tbody = table?.tBodies?.[0];
    if (!table || !tbody) return;
    const state = selectionState[tableId];

    if (!ctrlKey && !shiftKey) {
        clearCellSelectionForTable(tableId);
        clearColumnSelection(tableId);
        clearRowSelection(tableId);
        state.rows.add(rowIndex);
    } else if (shiftKey && state.lastRow !== null) {
        const start = Math.min(state.lastRow, rowIndex);
        const end = Math.max(state.lastRow, rowIndex);
        if (!ctrlKey) clearRowSelection(tableId);
        for (let idx = start; idx <= end; idx++) state.rows.add(idx);
    } else if (ctrlKey) {
        if (state.rows.has(rowIndex)) state.rows.delete(rowIndex);
        else state.rows.add(rowIndex);
    } else {
        state.rows.add(rowIndex);
    }

    state.lastRow = rowIndex;
    syncSelectedRows(tableId);

    const row = tbody.rows?.[rowIndex];
    if (!row) return;

    const firstCells = Array.from(row.cells)
        .slice(1, 4)
        .map(cell => (cell.textContent || '').trim())
        .filter(Boolean);

    setBarText(tableId, firstCells.join(' | '));
}

function selectTableColumn(tableId, columnName, modifiers = {}) {
    const { ctrlKey = false, shiftKey = false } = modifiers;
    const table = document.getElementById(tableId);
    if (!table || !columnName) return;
    const state = selectionState[tableId];
    const columnOrder = getVisibleColumnOrder(tableId);
    const columnIndex = columnOrder.indexOf(columnName);
    if (columnIndex < 0) return;

    if (!ctrlKey && !shiftKey) {
        clearCellSelectionForTable(tableId);
        clearRowSelection(tableId);
        clearColumnSelection(tableId);
        state.columns.add(columnName);
    } else if (shiftKey && state.lastColumn !== null) {
        const start = Math.min(state.lastColumn, columnIndex);
        const end = Math.max(state.lastColumn, columnIndex);
        if (!ctrlKey) clearColumnSelection(tableId);
        for (let idx = start; idx <= end; idx++) {
            state.columns.add(columnOrder[idx]);
        }
    } else if (ctrlKey) {
        if (state.columns.has(columnName)) state.columns.delete(columnName);
        else state.columns.add(columnName);
    } else {
        state.columns.add(columnName);
    }

    state.lastColumn = columnIndex;
    syncSelectedColumns(tableId);
    setBarText(
        tableId,
        Array.from(state.columns)
            .map(column => getResultColumnLabel(tableId, column))
            .join(' | '),
    );
}

function syncWrappedColumns(tableId) {
    const table = document.getElementById(tableId);
    const wrappedColumns = wrappedColumnsState[tableId];
    if (!table || !wrappedColumns) return;

    table.querySelectorAll('tbody tr').forEach(row => {
        row.classList.toggle('row-content-wrap', wrappedColumns.size > 0);
    });
    table.querySelectorAll('.column-wrap').forEach(el => el.classList.remove('column-wrap'));
    wrappedColumns.forEach(columnName => {
        const selector = `[data-col-name="${CSS.escape(columnName)}"]`;
        table.querySelectorAll(selector).forEach(el => el.classList.add('column-wrap'));
    });
}

function initRowSelection(tableId) {
    const table = document.getElementById(tableId);
    const tbody = table?.tBodies?.[0];
    if (!table || !tbody || tbody.dataset.rowSelectionBound === '1') return;

    tbody.dataset.rowSelectionBound = '1';
    tbody.addEventListener('click', (e) => {
        const selectorCell = e.target.closest('.row-selector-cell');
        if (!selectorCell) return;

        const rowIndex = Number(selectorCell.dataset.rowIndex);
        if (!Number.isNaN(rowIndex)) {
            selectTableRow(tableId, rowIndex, { ctrlKey: e.ctrlKey || e.metaKey, shiftKey: e.shiftKey });
        }
    });
}

function initColumnSelection(tableId) {
    const table = document.getElementById(tableId);
    const thead = table?.querySelector('thead');
    if (!table || !thead || thead.dataset.columnSelectionBound === '1') return;

    thead.dataset.columnSelectionBound = '1';
    thead.addEventListener('click', (e) => {
        if (e.target.closest('.column-menu-trigger, .col-resizer')) return;

        const th = e.target.closest('th');
        if (!th || th.classList.contains('row-selector-header')) return;

        const columnName = th.dataset.colName;
        if (columnName) {
            selectTableColumn(tableId, columnName, { ctrlKey: e.ctrlKey || e.metaKey, shiftKey: e.shiftKey });
        }
    });
}

function syncFrozenColumns(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const headerCells = Array.from(table.querySelectorAll('thead th'));
    const visibleColumnOrder = getVisibleColumnOrder(tableId);
    const frozenColumns = frozenColumnsState[tableId] || new Set();
    const rows = Array.from(table.tBodies?.[0]?.rows || []);

    table.querySelectorAll('.is-frozen-col, .is-last-frozen-col').forEach(cell => {
        cell.classList.remove('is-frozen-col', 'is-last-frozen-col');
        cell.style.left = '';
    });

    const frozenIndices = [0];
    visibleColumnOrder.forEach((columnName, orderIndex) => {
        if (frozenColumns.has(columnName)) {
            frozenIndices.push(orderIndex + 1);
        }
    });

    if (!frozenIndices.length) return;

    let cumulativeLeft = 0;
    frozenIndices.forEach((colIndex, frozenOrder) => {
        const isLastFrozen = frozenOrder === frozenIndices.length - 1;
        const left = `${cumulativeLeft}px`;
        const headerCell = headerCells[colIndex];
        cumulativeLeft += headerCell?.getBoundingClientRect().width || 0;

        if (headerCell) {
            headerCell.classList.add('is-frozen-col');
            if (isLastFrozen) headerCell.classList.add('is-last-frozen-col');
            headerCell.style.left = left;
        }

        rows.forEach(row => {
            const cell = row.cells[colIndex];
            if (!cell) return;

            cell.classList.add('is-frozen-col');
            if (isLastFrozen) cell.classList.add('is-last-frozen-col');
            cell.style.left = left;
        });
    });
}

function syncAllFrozenColumns() {
    ['standard-table', 'extended-table', 'traditional-table'].forEach(syncFrozenColumns);
}


// ============================== 
// INIT: DOMContentLoaded
// ============================== 
let df1 = [];
let df2 = [];

const tableSel = {
    "standard-table": { isDown: false, start: null, end: null, text: "", lastActive: 0 },
    "extended-table": { isDown: false, start: null, end: null, text: "", lastActive: 0 },
    "traditional-table": { isDown: false, start: null, end: null, text: "", lastActive: 0 }
};

function initStorageAndElements() {
    restoreColumnOrderFromStorage();

    standardTbody = document.getElementById('standard-data');
    extendedTbody = document.getElementById('extended-data');
    traditionalTbody = document.getElementById('traditional-data');

    syncHeadersWithLocalStorage();
    Object.keys(TABLE_MAP).forEach(initColumnSelection);
    syncAllFrozenColumns();

    initPanels();
    initTableWorkspaceControls();
    initFilterHelpExternalTooltip();
}


function initModalEvents() {
    const modalEvents = {
        'open-run-history': () => showHistoryModal(),
        'close-history': () => document.getElementById('history-modal').classList.remove('show')
    };
    
    Object.entries(modalEvents).forEach(([id, handler]) => {
        document.getElementById(id)?.addEventListener('click', handler);
    });
    
    document.querySelector('.history-overlay')?.addEventListener('click', () => {
        document.getElementById('history-modal').classList.remove('show');
    });

    document.querySelectorAll('[data-history-range]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const nextRange = Number(btn.dataset.historyRange || 30);
            if (!Number.isFinite(nextRange) || nextRange <= 0) return;
            activeHistoryRangeDays = nextRange;
            updateHistoryRangeButtons();
            void ensureChartJsLoaded()
                .then(() => renderHistoryTimelineChart(metadata?.update_timeline || []))
                .catch(error => console.error('Unable to load Chart.js for history', error));
        });
    });
}

const BULK_GROUP_ORDER = ['goods', 'medicines', 'traditional'];
const BULK_GROUP_LABELS = {
    goods: 'Hàng hóa',
    medicines: 'Thuốc',
    traditional: 'Dược liệu'
};
const BULK_GROUP_ICONS = {
    goods: 'package',
    medicines: 'pill',
    traditional: 'leaf'
};
const BULK_GROUP_ICON_PATHS = {
    goods: '<path d="m16.5 9.4-9-5.19M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="M3.27 6.96 12 12.01l8.73-5.05M12 22.08V12"/>',
    medicines: '<path d="m10.5 20.5 9.5-9.5a4.95 4.95 0 0 0-7-7l-9.5 9.5a4.95 4.95 0 0 0 7 7Z"/><path d="m8.5 8.5 7 7"/>',
    traditional: '<path d="M20.9 3.1C12.8 3.3 6.4 6.2 4 11.2c-1.5 3.1-.5 6.7 2.4 8.1 3.1 1.5 6.7-.1 8.1-3.2 1.2-2.7.7-5.7-.9-7.7"/><path d="M3 21c2.4-3.8 5.6-6.2 10-8"/>'
};
const BULK_GROUP_SCOPES = {
    goods: 'goods',
    medicines: 'medicine',
    traditional: 'traditional'
};
const BULK_DEFAULT_FIELDS = {
    goods: ['item_name', 'technical_specification'],
    medicines: ['active_ingredient_or_herbal_component', 'strength', 'route_of_administration', 'dosage_form', 'medicine_group'],
    traditional: ['item_name', 'used_part', 'processing_method', 'technical_group']
};
const BULK_SEARCH_FIELD_LABELS = {
    goods: {
        item_name: 'Tên hàng hóa / dược liệu',
        unit: 'Đơn vị tính',
        quantity: 'Số lượng / khối lượng',
        country_of_origin: 'Xuất xứ',
        hs_code: 'Mã HS',
        model_mark: 'Ký mã hiệu',
        brand: 'Nhãn hiệu',
        manufacturer: 'Hãng / cơ sở sản xuất',
        technical_specification: 'Cấu hình / tính năng kỹ thuật',
        model: 'Chủng loại',
        registration_or_import_permit_number: 'Số lưu hành / giấy phép nhập khẩu',
        winning_bidder_name: 'Nhà thầu trúng thầu',
        bid_invitation_code: 'Mã TBMT',
        procuring_entity_name: 'Chủ đầu tư'
    },
    medicines: {
        medicine_name: 'Tên thuốc',
        active_ingredient_or_herbal_component: 'Hoạt chất / thành phần dược liệu',
        strength: 'Nồng độ / hàm lượng',
        marketing_authorization_or_import_permit: 'GĐKLH hoặc GPNK',
        route_of_administration: 'Đường dùng',
        dosage_form: 'Dạng bào chế',
        shelf_life: 'Hạn dùng',
        manufacturer: 'Hãng / cơ sở sản xuất',
        production_country: 'Nước sản xuất',
        packaging: 'Quy cách đóng gói',
        unit: 'Đơn vị tính',
        medicine_group: 'Nhóm thuốc',
        winning_bidder_name: 'Nhà thầu trúng thầu',
        bid_invitation_code: 'Mã TBMT',
        procuring_entity_name: 'Chủ đầu tư'
    },
    traditional: {
        item_name: 'Tên hàng hóa / dược liệu',
        used_part: 'Bộ phận dùng',
        scientific_name: 'Tên khoa học',
        origin: 'Nguồn gốc',
        processing_method: 'Phương pháp chế biến',
        registration_or_import_permit_number: 'Số lưu hành / giấy phép nhập khẩu',
        manufacturer: 'Hãng / cơ sở sản xuất',
        production_country: 'Nước sản xuất',
        packaging: 'Quy cách đóng gói',
        unit: 'Đơn vị tính',
        technical_group: 'Nhóm tiêu chí kỹ thuật',
        winning_bidder_name: 'Nhà thầu trúng thầu',
        bid_invitation_code: 'Mã TBMT',
        procuring_entity_name: 'Chủ đầu tư'
    }
};
const BULK_COLUMN_ALIASES = {
    goods: {
        item_name: ['Danh mục hàng hóa', 'Tên hàng hóa', 'Tên hàng hoá', 'Hàng hóa', 'Hàng hoá', 'Tên mặt hàng'],
        technical_specification: ['Tính năng kỹ thuật', 'Thông số kỹ thuật', 'Thông số kĩ thuật', 'Mô tả kỹ thuật'],
        model_mark: ['Ký mã hiệu', 'Kí mã hiệu', 'Model', 'Mã hiệu', 'Ký hiệu'],
        country_of_origin: ['Xuất xứ', 'Nước sản xuất', 'Quốc gia sản xuất', 'Quốc gia'],
        manufacturer: ['Hãng sản xuất', 'Nhà sản xuất', 'Cơ sở sản xuất', 'Đơn vị sản xuất'],
        unit: ['Đơn vị tính', 'ĐVT', 'Đơn vị']
    },
    medicines: {
        medicine_name: ['Tên thuốc', 'Tên thương mại', 'Tên hàng hóa', 'Tên mặt hàng', 'Thuốc'],
        active_ingredient_or_herbal_component: ['Tên hoạt chất', 'Hoạt chất', 'Thành phần dược liệu'],
        strength: ['Nồng độ, hàm lượng', 'Nồng độ hoặc hàm lượng', 'Hàm lượng', 'Nồng độ'],
        route_of_administration: ['Đường dùng'],
        dosage_form: ['Dạng bào chế'],
        medicine_group: ['Nhóm thuốc', 'Nhóm TCKT', 'Nhóm'],
        unit: ['Đơn vị tính', 'ĐVT', 'Đơn vị'],
        marketing_authorization_or_import_permit: ['GĐKLH hoặc GPNK', 'GĐKLH/GPNK', 'Số đăng ký', 'SĐK', 'GPNK'],
        packaging: ['Quy cách', 'Quy cách đóng gói'],
        manufacturer: ['Cơ sở sản xuất', 'Nhà sản xuất', 'Hãng sản xuất', 'Đơn vị sản xuất'],
        production_country: ['Xuất xứ', 'Nước sản xuất', 'Quốc gia sản xuất', 'Quốc gia']
    },
    traditional: {
        item_name: ['Tên dược liệu', 'Tên vị thuốc', 'Tên hàng hóa', 'Tên mặt hàng'],
        used_part: ['Bộ phận dùng'],
        scientific_name: ['Tên khoa học'],
        origin: ['Nguồn gốc'],
        processing_method: ['Phương pháp chế biến'],
        registration_or_import_permit_number: ['Số lưu hành', 'Giấy phép nhập khẩu'],
        production_country: ['Xuất xứ', 'Nước sản xuất', 'Quốc gia sản xuất'],
        manufacturer: ['Cơ sở sản xuất', 'Hãng sản xuất', 'Nhà sản xuất'],
        packaging: ['Quy cách', 'Quy cách đóng gói'],
        unit: ['Đơn vị tính', 'ĐVT', 'Đơn vị'],
        technical_group: ['Nhóm TCKT', 'Nhóm tiêu chí kỹ thuật']
    }
};

let bulkImportedRows = [];
let bulkImportedColumns = [];
let bulkActiveScope = 'goods';
let lastBulkSearchPayloads = null;
let lastBulkSearchWarnings = [];
let bulkImportReadToken = 0;
let bulkSearchRunToken = 0;
let lastBulkExportResult = null;

const BULK_EXCEL_ACCEPTED_EXTENSIONS = ['.xlsx', '.xls', '.csv'];
const BULK_SEARCH_EXPORT_LIMIT = 1000;
const BULK_EXPORT_SOURCE_INDEX_FIELD = 'Bulk query';
const BULK_EXPORT_SOURCE_LABEL_FIELD = 'Bulk query row';
const BULK_EXPORT_LEGACY_SOURCE_INDEX_FIELD = 'tìm kiếm hàng loạt';
const BULK_EXPORT_LEGACY_SOURCE_LABEL_FIELD = 'Dòng tìm kiếm';
const BULK_EXPORT_EXCLUDED_FIELDS = new Set([
    '_dataset',
    '__row_id',
    '__has_duplicate_warning',
    BULK_EXPORT_SOURCE_INDEX_FIELD,
    BULK_EXPORT_SOURCE_LABEL_FIELD,
    BULK_EXPORT_LEGACY_SOURCE_INDEX_FIELD,
    BULK_EXPORT_LEGACY_SOURCE_LABEL_FIELD
]);

function normalizeBulkColumnName(value) {
    return String(value || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/đ/g, 'd')
        .replace(/Đ/g, 'D')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .trim();
}

function getBulkDiversitySelection() {
    const selected = document.querySelector('input[name="bulk-diversity-limit"]:checked');
    const [mode, rawLimit] = String(selected?.value || 'price:3').split(':');
    const limit = Number(rawLimit || 3);
    return {
        mode: mode === 'product' ? 'product' : 'price',
        limit: [3, 5, 10].includes(limit) ? limit : 3
    };
}

function getBulkPriceLimit() {
    const selection = getBulkDiversitySelection();
    return selection.mode === 'price' ? selection.limit : 0;
}

function getBulkProductLimit() {
    const selection = getBulkDiversitySelection();
    return selection.mode === 'product' ? selection.limit : 0;
}

function getBulkGroupContract(group) {
    return advancedSearchContract?.groups?.[group] || null;
}

function getBulkFieldDefinitions(group) {
    const fields = getBulkGroupContract(group)?.fields;
    const definitions = Array.isArray(fields) && fields.length
        ? fields.filter(field => field.searchable)
        : Object.keys(BULK_SEARCH_FIELD_LABELS[group] || {}).map(name => ({
        name,
        label: BULK_SEARCH_FIELD_LABELS[group][name],
        searchable: true
    }));
    const dataColumnOrder = RESULT_COLUMN_CATALOG.order?.[group] || [];
    const orderIndex = new Map(dataColumnOrder.map((name, index) => [name, index]));
    const originalIndex = new Map(definitions.map((field, index) => [field.name, index]));
    return definitions.slice().sort((left, right) => {
        const leftIndex = orderIndex.get(left.name) ?? Number.MAX_SAFE_INTEGER;
        const rightIndex = orderIndex.get(right.name) ?? Number.MAX_SAFE_INTEGER;
        return leftIndex - rightIndex
            || (originalIndex.get(left.name) ?? 0) - (originalIndex.get(right.name) ?? 0);
    });
}

function getBulkFieldLabel(group, field) {
    return getBulkGroupContract(group)?.fields?.find(item => item.name === field)?.label
        || BULK_SEARCH_FIELD_LABELS[group]?.[field]
        || field;
}

function renderBulkGroupIcon(group) {
    const iconName = BULK_GROUP_ICONS[group];
    return renderFeatherIcon(iconName, 'bulk-group-nav-svg')
        || `<svg class="bulk-group-nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${BULK_GROUP_ICON_PATHS[group] || ''}</svg>`;
}

function getSelectedBulkSourceTypes() {
    return [];
}

function renderBulkFieldPanels() {
    const root = document.getElementById('bulk-field-panels');
    if (!root) return;
    if (!advancedSearchContract?.groups) {
        root.innerHTML = '<p class="bulk-contract-status" id="bulk-contract-status">Đang tải danh mục trường tìm kiếm…</p>';
        return;
    }
    root.innerHTML = `<div class="bulk-field-layout">
        <div class="bulk-group-nav" role="tablist" aria-label="Nhóm trường tham chiếu">
            ${BULK_GROUP_ORDER.map(group => `<button id="bulk-group-tab-${group}" type="button" class="bulk-group-nav-button ${group === bulkActiveScope ? 'is-active' : ''}" data-bulk-group-tab="${group}" role="tab" aria-selected="${group === bulkActiveScope}" aria-controls="bulk-group-panel-${group}"><span class="bulk-group-nav-icon" aria-hidden="true">${renderBulkGroupIcon(group)}</span><span>${escapeHtml(BULK_GROUP_LABELS[group])}</span></button>`).join('')}
        </div>
        <div class="bulk-group-content">
            ${BULK_GROUP_ORDER.map(group => {
                const fields = getBulkFieldDefinitions(group);
                const isActive = group === bulkActiveScope;
                const rowCount = Math.max(1, Math.ceil(fields.length / 2));
                return `<section id="bulk-group-panel-${group}" class="bulk-field-panel ${isActive ? 'is-active' : ''}" data-bulk-fields="${group}" role="tabpanel" aria-labelledby="bulk-group-tab-${group}"${isActive ? '' : ' hidden'}>
                    <div class="bulk-field-options" style="--bulk-field-rows: ${rowCount};">${fields.map(field => `<label><input type="checkbox" value="${escapeHtml(field.name)}" ${BULK_DEFAULT_FIELDS[group]?.includes(field.name) ? 'checked' : ''}> ${escapeHtml(field.label || field.name)}</label>`).join('')}</div>
                </section>`;
            }).join('')}
        </div>
    </div>`;
    setBulkActiveScope(bulkActiveScope, { resetOutput: false });
}

function getSelectedBulkFields(scope) {
    return Array.from(document.querySelectorAll(`[data-bulk-fields="${scope}"] input[type="checkbox"]:checked`))
        .map(input => input.value)
        .filter(Boolean);
}

function getAllSelectedBulkScopes() {
    return BULK_GROUP_ORDER.filter(group => getSelectedBulkFields(group).length);
}

function setBulkActiveScope(scope, options = {}) {
    if (!BULK_GROUP_ORDER.includes(scope)) return;
    bulkActiveScope = scope;
    document.querySelectorAll('[data-bulk-group-tab]').forEach(button => {
        const isActive = button.dataset.bulkGroupTab === scope;
        button.classList.toggle('is-active', isActive);
        button.setAttribute('aria-selected', String(isActive));
    });
    document.querySelectorAll('[data-bulk-fields]').forEach(panel => {
        const isActive = panel.dataset.bulkFields === scope;
        panel.classList.toggle('is-active', isActive);
        panel.hidden = !isActive;
        panel.setAttribute('aria-hidden', String(!isActive));
    });
    if (options.resetOutput !== false) {
        resetBulkDownloadUi();
        setBulkSearchWarnings([]);
    }
}

function findBulkColumnForField(scope, field, normalizedColumns) {
    const aliases = [getBulkFieldLabel(scope, field), field, ...(BULK_COLUMN_ALIASES[scope]?.[field] || [])]
        .map(normalizeBulkColumnName)
        .filter(Boolean);
    const aliasSet = new Set(aliases);
    const exactMatch = normalizedColumns.find(item => aliasSet.has(item.normalized));
    if (exactMatch) return exactMatch.name;
    const looseMatch = normalizedColumns.find(item => aliases.some(alias => alias && item.normalized.includes(alias)));
    return looseMatch?.name || null;
}

function buildBulkMappedRows(scope) {
    const selectedFields = getSelectedBulkFields(scope);
    const normalizedColumns = bulkImportedColumns.map(name => ({
        name,
        normalized: normalizeBulkColumnName(name)
    }));
    const fieldColumnMap = {};
    const availableFields = [];
    const missingFields = [];

    selectedFields.forEach(field => {
        const columnName = findBulkColumnForField(scope, field, normalizedColumns);
        if (columnName) {
            fieldColumnMap[field] = columnName;
            availableFields.push(field);
        } else {
            missingFields.push(field);
        }
    });

    const rows = bulkImportedRows
        .map(sourceRow => availableFields.reduce((row, field) => {
            row[field] = String(sourceRow[fieldColumnMap[field]] ?? '').trim();
            return row;
        }, {}))
        .filter(row => Object.values(row).some(value => String(value || '').trim()));

    return { fields: availableFields, rows, missingFields };
}

function setBulkSearchWarnings(warnings = []) {
    const container = document.getElementById('bulk-search-warnings');
    if (!container) return;
    container.hidden = warnings.length === 0;
    container.innerHTML = warnings.length
        ? warnings.map(message => `<div>${escapeHtml(message)}</div>`).join('')
        : '';
}

function setBulkSearchStatus(message, type = '') {
    const status = document.getElementById('bulk-search-status');
    if (status) {
        status.textContent = '';
        status.classList.toggle('is-success', false);
        status.classList.toggle('is-error', false);
    }
    const inlineStatus = document.getElementById('bulk-inline-status');
    if (!inlineStatus) return;
    inlineStatus.textContent = message || '';
    inlineStatus.classList.toggle('is-error', type === 'error');
}

function isSupportedBulkExcelFile(file) {
    const fileName = String(file?.name || '').toLowerCase();
    return BULK_EXCEL_ACCEPTED_EXTENSIONS.some(extension => fileName.endsWith(extension));
}

function setBulkImportDragState(isDragging) {
    document.getElementById('bulk-import-card')?.classList.toggle('is-dragging', Boolean(isDragging));
}

function openBulkSearchModal() {
    const modal = document.getElementById('bulk-search-modal');
    if (!modal) return;
    void loadAdvancedSearchContract();
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
    setBulkSearchStatus('');
    setBulkActiveScope(bulkActiveScope, { resetOutput: false });
    requestAnimationFrame(() => document.getElementById('bulk-import-excel')?.focus());
    window.feather?.replace?.();
}

function closeBulkSearchModal() {
    const modal = document.getElementById('bulk-search-modal');
    if (!modal) return;
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
}

function updateBulkImportFileName(text, hasFile = false) {
    const label = document.getElementById('bulk-import-file-name');
    if (label) {
        label.textContent = text || 'Chưa chọn file';
        label.hidden = false;
    }
    const selected = document.getElementById('bulk-import-selected');
    if (selected) selected.hidden = !hasFile;
    const downloadCopy = document.getElementById('bulk-download-copy');
    if (downloadCopy) downloadCopy.hidden = true;
    const downloadButton = document.getElementById('download-bulk-excel');
    if (downloadButton) {
        downloadButton.hidden = true;
        downloadButton.disabled = true;
    }

    const clearButton = document.getElementById('bulk-clear-excel');
    if (clearButton) {
        clearButton.hidden = !hasFile;
        clearButton.disabled = !hasFile;
    }

    document.getElementById('bulk-excel-dropzone')?.classList.toggle('has-file', hasFile);
}

function resetBulkInputState({ message = '' } = {}) {
    bulkImportReadToken += 1;
    bulkSearchRunToken += 1;
    bulkImportedRows = [];
    bulkImportedColumns = [];
    lastBulkSearchPayloads = null;
    lastBulkSearchWarnings = [];
    resetBulkDownloadUi();
    setBulkSearchWarnings([]);
    updateBulkImportFileName('Chưa chọn file', false);

    const input = document.getElementById('bulk-excel-file');
    if (input) input.value = '';
    setBulkSearchStatus(message);
}

function clearBulkImportedFile() {
    resetBulkInputState();
}

async function handleBulkExcelFile(file) {
    if (!file) return;
    if (!isSupportedBulkExcelFile(file)) {
        setBulkSearchStatus('Chỉ hỗ trợ file .xlsx, .xls hoặc .csv.', 'error');
        return;
    }
    if (!window.XLSX) {
        setBulkSearchStatus('Không tải được thư viện đọc Excel. Vui lòng thử tải lại trang.', 'error');
        return;
    }

    const readToken = ++bulkImportReadToken;
    bulkImportedRows = [];
    bulkImportedColumns = [];
    lastBulkSearchPayloads = null;
    lastBulkSearchWarnings = [];
    resetBulkDownloadUi();
    updateBulkImportFileName(file.name, false);
    setBulkSearchStatus('Đang đọc file Excel...');
    setBulkSearchWarnings([]);

    try {
        const buffer = await file.arrayBuffer();
        const workbook = window.XLSX.read(buffer, { type: 'array' });
        if (readToken !== bulkImportReadToken) return;
        const firstSheetName = workbook.SheetNames?.[0];
        if (!firstSheetName) {
            throw new Error('File Excel không có sheet dữ liệu.');
        }
        const sheet = workbook.Sheets[firstSheetName];
        const rows = window.XLSX.utils.sheet_to_json(sheet, { defval: '', raw: false });
        bulkImportedRows = rows;
        bulkImportedColumns = rows.length ? Object.keys(rows[0]) : [];

        if (!bulkImportedRows.length || !bulkImportedColumns.length) {
            throw new Error('File Excel chưa có dữ liệu hoặc chưa có dòng tiêu đề cột.');
        }

        updateBulkImportFileName(`${file.name} (${bulkImportedRows.length} dòng)`, true);
        setBulkSearchStatus('');
    } catch (error) {
        if (readToken !== bulkImportReadToken) return;
        bulkImportedRows = [];
        bulkImportedColumns = [];
        updateBulkImportFileName('Chưa chọn file', false);
        setBulkSearchStatus(error?.message || 'Không đọc được file Excel.', 'error');
    }
}

function buildEmptyBulkScope() {
    return {
        data: [],
        count: 0,
        count_exact: true,
        count_label: '0',
        count_summary: '0',
        displayed: 0,
        has_more: false,
        approx_total: null
    };
}

function combineBulkResults(results) {
    const resultFor = group => results.find(item => (item.group || getBulkGroupFromScope(item.scope)) === group)?.result || {};
    const medicineResult = resultFor('medicines');
    const goodsResult = resultFor('goods');
    const traditionalResult = resultFor('traditional');
    const medicineData = medicineResult.df1 || buildEmptyBulkScope();
    const goodsData = goodsResult.df2 || buildEmptyBulkScope();
    const traditionalData = traditionalResult.df3 || buildEmptyBulkScope();
    const dataByGroup = { medicines: medicineData, goods: goodsData, traditional: traditionalData };
    const displayedTotal = Object.values(dataByGroup).reduce((sum, data) => sum + Number(data.data?.length || 0), 0);
    const hasMore = Object.values(dataByGroup).some(data => data.has_more);
    const totalCount = Object.values(dataByGroup).reduce((sum, data) => sum + Number(data.count || 0), 0);
    const totalCountExact = Object.values(dataByGroup).every(data => data.count_exact !== false);
    const totalCountLabel = totalCountExact ? String(totalCount) : `${totalCount}+`;
    const totalCountSummary = totalCountExact ? String(totalCount) : `hơn ${totalCount}`;
    const appliedTotalLimit = BULK_SEARCH_EXPORT_LIMIT;

    return {
        success: true,
        search_mode: 'bulk',
        bulk: {
            scope: results.length > 1 ? 'all' : (results[0]?.group || getBulkGroupFromScope(results[0]?.scope) || 'all'),
            input_count: Math.max(...results.map(item => Number(item.result?.bulk?.input_count || 0)), 0),
            matched_count: displayedTotal,
            matched_input_count: results.reduce((sum, item) => sum + Number(item.result?.bulk?.matched_input_count || 0), 0),
            diversity_mode: getBulkDiversitySelection().mode,
            price_limit: getBulkPriceLimit(),
            product_limit: getBulkProductLimit(),
            search_mode: results.some(item => item.result?.bulk?.search_mode === 'full') ? 'full' : 'standard',
            result_limit: BULK_SEARCH_EXPORT_LIMIT,
            truncated: hasMore,
            fields: results.reduce((fields, item) => fields.concat(item.result?.bulk?.fields || []), [])
        },
        total_count: totalCount,
        total_count_exact: totalCountExact,
        total_count_label: totalCountLabel,
        total_count_summary: totalCountSummary,
        applied_total_limit: appliedTotalLimit,
        applied_limit_per_scope: BULK_SEARCH_EXPORT_LIMIT,
        df1: medicineData,
        df2: goodsData,
        df3: traditionalData,
        auth: goodsResult.auth || medicineResult.auth || traditionalResult.auth,
        full_search_daily_used: goodsResult.full_search_daily_used ?? medicineResult.full_search_daily_used ?? traditionalResult.full_search_daily_used,
        full_search_daily_remaining: goodsResult.full_search_daily_remaining ?? medicineResult.full_search_daily_remaining ?? traditionalResult.full_search_daily_remaining
    };
}

function getBulkGroupFromScope(scope) {
    return scope === 'medicine' ? 'medicines'
        : scope === 'goods' ? 'goods'
            : ['traditional', 'traditional_medicine'].includes(scope) ? 'traditional'
                : scope;
}

function getBulkResultKey(group) {
    return group === 'medicines' ? 'df1' : group === 'goods' ? 'df2' : 'df3';
}

function getBulkResultRows(result, scope) {
    const scopeData = result?.[getBulkResultKey(getBulkGroupFromScope(scope))];
    return Array.isArray(scopeData?.data) ? scopeData.data : [];
}

function getBulkSourceIndex(row) {
    return Number(row?.[BULK_EXPORT_SOURCE_INDEX_FIELD] || row?.[BULK_EXPORT_LEGACY_SOURCE_INDEX_FIELD] || 0);
}

function getBulkDisplayedTotal(result) {
    return BULK_GROUP_ORDER.reduce((sum, group) => sum + getBulkResultRows(result, group).length, 0);
}

function getBulkMatchedSourceCount(result) {
    const serverCount = Number(result?.bulk?.matched_input_count || 0);
    if (serverCount > 0) return serverCount;
    const indexes = new Set();
    BULK_GROUP_ORDER.forEach(scope => {
        getBulkResultRows(result, scope).forEach(row => {
            const index = getBulkSourceIndex(row);
            if (index > 0) indexes.add(index);
        });
    });
    return indexes.size;
}

function getBulkInputSourceCount() {
    return Math.max(...(lastBulkSearchPayloads || []).map(payload => Number(payload?.rows?.length || 0)), 0);
}

function sanitizeBulkExportRows(rows = []) {
    return rows.map(row => Object.entries(row || {}).reduce((cleaned, [key, value]) => {
        if (!BULK_EXPORT_EXCLUDED_FIELDS.has(key)) {
            cleaned[key] = value ?? '';
        }
        return cleaned;
    }, {}));
}

function getBulkPayloadForScope(scope) {
    const group = getBulkGroupFromScope(scope);
    return (lastBulkSearchPayloads || []).find(payload => (payload.group || getBulkGroupFromScope(payload.scope)) === group) || null;
}

function buildBulkSourceDisplayRow(sourceRow = {}, fields = [], scope = 'goods') {
    return fields.reduce((row, field) => {
        const label = getBulkFieldLabel(scope, field);
        row[label] = sourceRow?.[field] ?? '';
        return row;
    }, {});
}

function getBulkUiColumns(scope = 'goods') {
    const group = getBulkGroupFromScope(scope);
    if (group === 'goods') return [...DF2_COLUMNS_ORDER];
    if (group === 'traditional') return [...DF3_COLUMNS_ORDER];
    return [...DF1_COLUMNS_ORDER];
}

function buildBulkExportSheet(rows = [], scope = 'goods') {
    const uiColumns = getBulkUiColumns(scope);
    const cleanedRows = sanitizeBulkExportRows(rows).map(row => (
        uiColumns.reduce((filtered, columnName) => {
            filtered[columnName] = row[columnName] ?? '';
            return filtered;
        }, {})
    ));
    const payload = getBulkPayloadForScope(scope);
    const sourceRows = Array.isArray(payload?.rows) ? payload.rows : [];
    const fields = Array.isArray(payload?.fields) ? payload.fields : [];

    const headers = [...uiColumns];
    sourceRows.forEach(row => {
        Object.keys(buildBulkSourceDisplayRow(row, fields, scope)).forEach(key => {
            if (!headers.includes(key)) headers.push(key);
        });
    });
    if (!headers.length) headers.push('Không có kết quả');

    const resultGroups = rows.reduce((groups, row) => {
        const index = getBulkSourceIndex(row);
        if (index > 0) {
            if (!groups.has(index)) groups.set(index, []);
            groups.get(index).push(row);
        }
        return groups;
    }, new Map());

    const aoa = [
        ['Nguồn: BIDFinder – Hệ thống quản lý dữ liệu đấu thầu y tế'],
        [],
        headers
    ];
    const sourceExcelRows = [];

    sourceRows.forEach((sourceRow, index) => {
        const excelRowIndex = aoa.length;
        sourceExcelRows.push(excelRowIndex);
        const sourceDisplayRow = buildBulkSourceDisplayRow(sourceRow, fields, scope);
        aoa.push(headers.map(header => sourceDisplayRow[header] ?? ''));

        const matchedRows = resultGroups.get(index + 1) || [];
        matchedRows.forEach(resultRow => {
            const cleaned = sanitizeBulkExportRows([resultRow])[0] || {};
            aoa.push(headers.map(header => cleaned[header] ?? ''));
        });
    });

    if (!sourceRows.length && cleanedRows.length) {
        cleanedRows.forEach(row => aoa.push(headers.map(header => row[header] ?? '')));
    }

    const ws = window.XLSX.utils.aoa_to_sheet(aoa);
    sourceExcelRows.forEach(rowIndex => {
        headers.forEach((_, columnIndex) => {
            const cellAddress = window.XLSX.utils.encode_cell({ r: rowIndex, c: columnIndex });
            if (!ws[cellAddress]) ws[cellAddress] = { t: 's', v: '' };
            ws[cellAddress].s = {
                fill: { patternType: 'solid', fgColor: { rgb: 'FFF2CC' } },
                font: { bold: true }
            };
        });
    });
    return ws;
}

function getBulkExportFilename() {
    const rowCount = getBulkDisplayedTotal(lastBulkExportResult);
    return `BIDFinder_KQ_TCHL_${rowCount}.xlsx`;
}

function resetBulkDownloadUi() {
    lastBulkExportResult = null;
    const uploadName = document.getElementById('bulk-import-file-name');
    const copy = document.getElementById('bulk-download-copy');
    const title = document.getElementById('bulk-download-title');
    const summary = document.getElementById('bulk-download-summary');
    const button = document.getElementById('download-bulk-excel');
    if (uploadName) uploadName.hidden = false;
    if (copy) copy.hidden = true;
    if (title) title.textContent = '';
    if (summary) summary.textContent = '';
    if (button) {
        button.hidden = true;
        button.disabled = true;
    }
    const runButton = document.getElementById('run-bulk-search');
    if (runButton) runButton.disabled = false;
}

function updateBulkDownloadUi(result) {
    lastBulkExportResult = result || null;
    const selected = document.getElementById('bulk-import-selected');
    const uploadName = document.getElementById('bulk-import-file-name');
    const copy = document.getElementById('bulk-download-copy');
    const title = document.getElementById('bulk-download-title');
    const summary = document.getElementById('bulk-download-summary');
    const button = document.getElementById('download-bulk-excel');
    const clearButton = document.getElementById('bulk-clear-excel');
    if (!selected || !uploadName || !copy || !title || !summary || !button) return;

    const displayed = getBulkDisplayedTotal(result);
    const total = Number(result?.total_count || displayed || 0);
    const totalLabel = String(result?.total_count_label || total.toLocaleString('vi-VN'));
    selected.hidden = false;
    uploadName.hidden = true;
    copy.hidden = false;
    button.hidden = false;
    button.disabled = displayed <= 0;
    const runButton = document.getElementById('run-bulk-search');
    if (runButton) runButton.disabled = true;
    if (clearButton) {
        clearButton.hidden = false;
        clearButton.disabled = false;
    }
    document.getElementById('bulk-excel-dropzone')?.classList.toggle('has-file', true);
    title.textContent = getBulkExportFilename();
    const matchedSources = getBulkMatchedSourceCount(result);
    const inputSources = getBulkInputSourceCount();
    const productLine = `${matchedSources.toLocaleString('vi-VN')}/${inputSources.toLocaleString('vi-VN')} sản phẩm có kết quả`;
    const rowLine = displayed > 0
        ? `${displayed.toLocaleString('vi-VN')}/${totalLabel} dòng sẵn sàng tải về.`
        : 'Không có dòng kết quả để tải về.';
    summary.textContent = displayed > 0
        ? `${productLine}\n${rowLine}`
        : 'Không có dòng kết quả để tải về.';
}

function downloadBulkSearchExcel() {
    if (!lastBulkExportResult) return;
    if (!window.XLSX) {
        setBulkSearchStatus('Không tải được thư viện tạo Excel. Vui lòng thử tải lại trang.', 'error');
        return;
    }

    const rowsByGroup = BULK_GROUP_ORDER.map(group => ({ group, rows: getBulkResultRows(lastBulkExportResult, group) }))
        .filter(item => item.rows.length);
    if (!rowsByGroup.length) {
        setBulkSearchStatus('Không có dữ liệu để tải Excel.', 'error');
        return;
    }

    const workbook = window.XLSX.utils.book_new();
    const sheetNames = { goods: 'Hang hoa', medicines: 'Thuoc', traditional: 'Duoc lieu' };
    rowsByGroup.forEach(({ group, rows }) => {
        window.XLSX.utils.book_append_sheet(workbook, buildBulkExportSheet(rows, group), sheetNames[group]);
    });

    window.XLSX.writeFile(workbook, getBulkExportFilename());
    window.BIDFinderAnalytics?.track?.('bulk_search_excel_downloaded', {
        row_count: getBulkDisplayedTotal(lastBulkExportResult),
        total_count: Number(lastBulkExportResult?.total_count || 0)
    });
}

async function runBulkSearch(options = {}) {
    const searchMode = options.searchMode === 'full' ? 'full' : 'standard';
    const reuseLastPayloads = Boolean(options.reuseLastPayloads);
    await window.BIDFinderAuth?.whenReady?.();
    if (!requireAuthenticatedSession('login', 'full_query')) return;

    if (!reuseLastPayloads && !bulkImportedRows.length) {
        setBulkSearchStatus('Chưa có dữ liệu để tìm kiếm.', 'error');
        return;
    }

    let warnings = [];
    let payloads = [];

    if (reuseLastPayloads && lastBulkSearchPayloads?.length) {
        payloads = lastBulkSearchPayloads;
        warnings = lastBulkSearchWarnings || [];
    } else {
        const selectedScopes = getAllSelectedBulkScopes();
        if (!selectedScopes.length) {
            setBulkSearchStatus('Cần chọn ít nhất một biến để tìm kiếm.', 'error');
            return;
        }

        payloads = selectedScopes
            .map(scope => {
                const mapped = buildBulkMappedRows(scope);
                if (!mapped.fields.length) {
                    return null;
                }
                if (!mapped.rows.length) {
                    setBulkSearchStatus('Chưa có dữ liệu hợp lệ để tìm kiếm.', 'error');
                    return null;
                }
                return {
                    scope: BULK_GROUP_SCOPES[scope],
                    group: scope,
                    sourceTypes: getSelectedBulkSourceTypes(scope),
                    fields: mapped.fields,
                    rows: mapped.rows
                };
            })
            .filter(Boolean);
    }

    setBulkSearchWarnings([]);
    if (!payloads.length) {
        setBulkSearchStatus('Chưa có dữ liệu hợp lệ để tìm kiếm.', 'error');
        return;
    }

    const runButton = document.getElementById('run-bulk-search');
    const defaultText = runButton?.textContent || 'tìm kiếm';
    if (runButton) {
        runButton.disabled = true;
        runButton.textContent = searchMode === 'full' ? 'Đang thực hiện...' : 'Đang tìm kiếm...';
    }
    const totalInputRows = payloads.reduce((sum, item) => sum + item.rows.length, 0);
    const runToken = ++bulkSearchRunToken;
    resetBulkDownloadUi();
    setBulkSearchStatus(`${searchMode === 'full' ? 'Đang thực hiện...' : 'Đang tìm kiếm...'}`);
    let completed = false;

    try {
        const results = [];
        let remainingLimit = BULK_SEARCH_EXPORT_LIMIT;
        for (const payload of payloads) {
            if (remainingLimit <= 0) break;
            const response = await getAuthorizedFetch()(`${API_BASE_URL}/api/bulk-query`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...payload,
                    diversityMode: getBulkDiversitySelection().mode,
                    priceLimit: getBulkPriceLimit(),
                    productLimit: getBulkProductLimit(),
                    limit: remainingLimit,
                    searchMode
                })
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok || result.success === false) {
                throw new Error(result.message || result.error || 'tìm kiếm hàng loạt thất bại.');
            }
            results.push({ group: payload.group, scope: payload.scope, result });
            const resultRows = getBulkResultRows(result, payload.group || payload.scope).length;
            remainingLimit = Math.max(0, remainingLimit - resultRows);
            if (result?.bulk?.truncated) break;
        }

        const result = combineBulkResults(results);
        if (result?.auth) {
            window.BIDFinderAuth?.applyAuthConfig?.(result.auth);
        }
        markDatabaseWarm();
        if (runToken !== bulkSearchRunToken) return;

        lastBulkSearchPayloads = payloads;
        lastBulkSearchWarnings = warnings;
        updateBulkDownloadUi(result);
        setBulkSearchWarnings([]);
        setBulkSearchStatus('');
        window.BIDFinderAnalytics?.track?.('bulk_search_completed', {
            scope: result.bulk?.scope || 'all',
            search_mode: searchMode,
            input_count: totalInputRows,
            matched_count: Number(result.total_count || 0),
            diversity_mode: getBulkDiversitySelection().mode,
            price_limit: getBulkPriceLimit(),
            product_limit: getBulkProductLimit()
        });
        completed = true;
    } catch (error) {
        if (runToken !== bulkSearchRunToken) return;
        console.error('Bulk search failed:', error);
        setBulkSearchStatus(error?.message || 'Không thể tìm kiếm hàng loạt lúc này.', 'error');
        if (searchMode === 'full') throw error;
    } finally {
    if (runButton) {
        runButton.disabled = Boolean(lastBulkExportResult);
        runButton.textContent = defaultText;
    }
    }
    return completed;
}

function initBulkSearchEvents() {
    document.getElementById('open-bulk-search-modal')?.addEventListener('click', openBulkSearchModal);
    document.getElementById('close-bulk-search-modal')?.addEventListener('click', closeBulkSearchModal);
    document.querySelector('#bulk-search-modal .bulk-search-overlay')?.addEventListener('click', closeBulkSearchModal);
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && document.getElementById('bulk-search-modal')?.classList.contains('show')) {
            closeBulkSearchModal();
        }
    });
    const bulkFieldPanels = document.getElementById('bulk-field-panels');
    bulkFieldPanels?.addEventListener('click', event => {
        const tab = event.target.closest('[data-bulk-group-tab]');
        if (tab) {
            event.preventDefault();
            setBulkActiveScope(tab.dataset.bulkGroupTab);
            return;
        }
        const panel = event.target.closest('[data-bulk-fields]');
        if (panel) setBulkActiveScope(panel.dataset.bulkFields);
    });
    bulkFieldPanels?.addEventListener('focusin', event => {
        const panel = event.target.closest('[data-bulk-fields]');
        if (panel) setBulkActiveScope(panel.dataset.bulkFields);
    });
    bulkFieldPanels?.addEventListener('change', event => {
        if (!event.target.matches('input[type="checkbox"]')) return;
        resetBulkDownloadUi();
        setBulkSearchWarnings([]);
    });
    document.querySelectorAll('input[name="bulk-diversity-limit"]').forEach(input => {
        input.addEventListener('change', () => {
            resetBulkDownloadUi();
            setBulkSearchWarnings([]);
        });
    });
    document.getElementById('bulk-import-excel')?.addEventListener('click', () => {
        document.getElementById('bulk-excel-file')?.click();
    });
    document.getElementById('bulk-excel-file')?.addEventListener('change', event => {
        handleBulkExcelFile(event.target.files?.[0]);
        event.target.value = '';
    });
    document.getElementById('bulk-clear-excel')?.addEventListener('click', () => {
        clearBulkImportedFile();
    });

    const dropZone = document.getElementById('bulk-import-card');
    if (dropZone) {
        let dragDepth = 0;
        dropZone.addEventListener('dragenter', event => {
            event.preventDefault();
            dragDepth += 1;
            setBulkImportDragState(true);
        });
        dropZone.addEventListener('dragover', event => {
            event.preventDefault();
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
            setBulkImportDragState(true);
        });
        dropZone.addEventListener('dragleave', event => {
            event.preventDefault();
            dragDepth = Math.max(0, dragDepth - 1);
            if (dragDepth === 0) setBulkImportDragState(false);
        });
        dropZone.addEventListener('drop', event => {
            event.preventDefault();
            dragDepth = 0;
            setBulkImportDragState(false);
            const files = Array.from(event.dataTransfer?.files || []);
            const file = files.find(isSupportedBulkExcelFile) || files[0];
            handleBulkExcelFile(file);
        });
    }

    document.getElementById('run-bulk-search')?.addEventListener('click', runBulkSearch);
    document.getElementById('download-bulk-excel')?.addEventListener('click', downloadBulkSearchExcel);
    updateBulkImportFileName('Chưa chọn file', false);
    resetBulkDownloadUi();
    setBulkActiveScope(bulkActiveScope, { resetOutput: false });
    void loadAdvancedSearchContract();
}

function getFeedbackContextText() {
    const user = window.BIDFinderAuth?.getUser?.();
    const lines = [
        '',
        '---',
        'Ngữ cảnh:',
        `URL: ${window.location.href}`,
        `Thời gian: ${new Date().toLocaleString('vi-VN')}`
    ];

    if (user?.email) {
        lines.push(`Tài khoản: ${user.email}`);
    }

    if (hasActiveQueryFilters(currentQueryRequest)) {
        lines.push(`Filter: ${JSON.stringify(currentQueryRequest)}`);
    }

    return lines.join('\n');
}

function getFeedbackContextPayload() {
    return {
        url: window.location.href,
        createdAt: new Date().toISOString(),
        filters: hasActiveQueryFilters(currentQueryRequest) ? currentQueryRequest : {}
    };
}

function collectFeedbackAnswers() {
    return Array.from(document.querySelectorAll('.feedback-choice-row')).map((row) => {
        const question = row.dataset.feedbackQuestion || row.querySelector('span')?.textContent?.trim() || '';
        const answer = row.querySelector('input[type="radio"]:checked')?.value || 'Chưa chọn';
        return { question, answer };
    }).filter(item => item.question);
}

function hasFeedbackContent() {
    const hasAnswer = collectFeedbackAnswers().some(item => item.answer !== 'Chưa chọn');
    const hasTask = Boolean(document.getElementById('feedback-task')?.value?.trim());
    const hasNote = Boolean(document.getElementById('feedback-message')?.value?.trim());
    return hasAnswer || hasTask || hasNote;
}

function buildFeedbackMessage() {
    const answers = collectFeedbackAnswers();
    const task = document.getElementById('feedback-task')?.value?.trim() || '';
    const message = document.getElementById('feedback-message')?.value?.trim() || '';
    const parts = [
        'Feedback nhanh:',
        ...answers.map(item => `- ${item.question}: ${item.answer}`),
        task ? `\nTask muốn làm nhưng app chưa hỗ trợ:\n${task}` : '',
        message ? `\nGhi chú thêm:\n${message}` : '',
        getFeedbackContextText()
    ];

    return parts.filter(Boolean).join('\n');
}

function buildFeedbackPayload() {
    return {
        answers: collectFeedbackAnswers(),
        task: document.getElementById('feedback-task')?.value?.trim() || '',
        note: document.getElementById('feedback-message')?.value?.trim() || '',
        context: getFeedbackContextPayload()
    };
}

function setFeedbackStatus(message, type = '') {
    const status = document.getElementById('feedback-status');
    if (!status) return;

    status.textContent = message || '';
    status.classList.toggle('is-success', type === 'success');
    status.classList.toggle('is-error', type === 'error');
}

let feedbackBoardState = {
    topics: [],
    topicDetails: new Map(),
    activeTopicId: null,
    activeTopic: null,
    replies: [],
    repliesNextOffset: 0,
    repliesHasMore: false,
    repliesLoading: false,
    topicFilter: 'all',
    isAdmin: false
};

const FEEDBACK_REPLY_BATCH_SIZE = 20;
const FEEDBACK_TOPIC_CACHE_TTL_MS = 45 * 1000;

const FEEDBACK_STATUS_ICONS = {
    open: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="9"></circle><circle cx="12" cy="12" r="2.7" fill="currentColor" stroke="none"></circle></svg>',
    closed: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"><path d="M9 12l2 2 4-4"></path><circle cx="12" cy="12" r="9"></circle></svg>'
};

const FEEDBACK_LOCK_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"><rect x="5" y="11" width="14" height="9" rx="2"></rect><path d="M8 11V8a4 4 0 0 1 8 0v3"></path></svg>';

const FEEDBACK_STATUS_LABELS = {
    open: 'Mở',
    planned: 'Đã ghi nhận',
    in_progress: 'Đang xử lý',
    resolved: 'Đã xử lý',
    closed: 'Đóng'
};

const FEEDBACK_CATEGORY_LABELS = {
    idea: 'Ý tưởng',
    bug: 'Lỗi',
    question: 'Câu hỏi',
    data: 'Dữ liệu',
    other: 'Khác'
};

const FEEDBACK_TOPIC_FILTER_LABELS = {
    all: 'Tất cả',
    admin: 'BIDFinder'
};

function formatFeedbackDate(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
}

function getFeedbackAuthorLabel(authorName, email, isAdmin = false) {
    if (isAdmin) return 'BIDFinder';
    const name = String(authorName || '').trim();
    if (name) return name;
    const value = String(email || '').trim();
    return value || 'Người dùng';
}

function getFeedbackAuthorInitial(authorName, email, isAdmin = false) {
    if (isAdmin) return 'B';
    const name = String(authorName || '').trim();
    if (name) return name[0].toUpperCase();
    const value = String(email || '').trim();
    return (value[0] || 'U').toUpperCase();
}

function getVisibleFeedbackTopics() {
    if (feedbackBoardState.topicFilter === 'admin') {
        return feedbackBoardState.topics.filter(topic => topic.is_admin_topic);
    }
    return feedbackBoardState.topics;
}

function isFeedbackUserAuthenticated() {
    return Boolean(window.BIDFinderAuth?.isAuthenticated?.());
}

function requireFeedbackAuthentication() {
    if (isFeedbackUserAuthenticated()) return true;

    const auth = window.BIDFinderAuth;
    if (!auth) return true;
    auth.requestIntent?.('feedback-write');
    auth.openAuthModal?.('login');
    setFeedbackStatus('Vui lòng đăng nhập để tạo chủ đề hoặc bình luận.', 'error');
    return false;
}

function syncFeedbackComposerAuthState() {
    const replyBody = document.getElementById('feedback-reply-body');
    const isClosedForUser = feedbackBoardState.activeTopic?.status === 'closed' && !feedbackBoardState.isAdmin;
    const isAuthenticated = isFeedbackUserAuthenticated();
    if (replyBody) {
        replyBody.disabled = isClosedForUser;
        replyBody.readOnly = false;
        replyBody.placeholder = 'Viết bình luận...';
    }
    updateFeedbackReplyButtonState();
}

function updateFeedbackReplyButtonState() {
    const replyBody = document.getElementById('feedback-reply-body');
    const sendButton = document.getElementById('send-feedback-reply');
    if (!replyBody || !sendButton) return;
    const isClosedForUser = feedbackBoardState.activeTopic?.status === 'closed' && !feedbackBoardState.isAdmin;
    sendButton.disabled = isClosedForUser || !replyBody.value.trim();
}

function renderFeedbackReplies(replies = []) {
    const replyList = document.getElementById('feedback-reply-list');
    if (!replyList) return;
    const replyMarkup = replies.length
        ? replies.map(reply => `
            <article class="feedback-reply${reply.is_admin ? ' is-admin' : ''}">
                <span class="feedback-avatar${reply.is_admin ? ' is-admin' : ''}">${escapeHtml(getFeedbackAuthorInitial(reply.author_name, reply.user_email, reply.is_admin))}</span>
                <div class="feedback-comment-content">
                    <div class="feedback-comment-bubble">
                        <div class="feedback-reply-meta">
                            <strong>${escapeHtml(getFeedbackAuthorLabel(reply.author_name, reply.user_email, reply.is_admin))}</strong>
                            ${reply.is_admin ? '<span class="feedback-admin-pill">Admin</span>' : ''}
                        </div>
                        <p>${escapeHtml(reply.body || '')}</p>
                    </div>
                    <div class="feedback-comment-foot">${formatFeedbackDate(reply.created_at)}</div>
                </div>
            </article>
        `).join('')
        : '';
    const closedEvent = feedbackBoardState.activeTopic?.status === 'closed'
        ? `
            <div class="feedback-lock-event">
                <span class="feedback-lock-icon">${FEEDBACK_LOCK_ICON}</span>
                <span><strong>BIDFinder</strong> đã đóng chủ đề này.</span>
            </div>
        `
        : '';
    replyList.innerHTML = `${replyMarkup}${closedEvent}`;
}

function renderFeedbackTopicList() {
    const list = document.getElementById('feedback-topic-list');
    if (!list) return;

    const filterLabel = document.getElementById('feedback-topic-filter-label');
    if (filterLabel) filterLabel.textContent = FEEDBACK_TOPIC_FILTER_LABELS[feedbackBoardState.topicFilter] || 'Tất cả';
    document.querySelectorAll('[data-feedback-filter-value]').forEach(button => {
        const isActive = button.dataset.feedbackFilterValue === feedbackBoardState.topicFilter;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-selected', String(isActive));
    });

    const visibleTopics = getVisibleFeedbackTopics();
    if (!visibleTopics.length) {
        const isAdminFilter = feedbackBoardState.topicFilter === 'admin';
        list.innerHTML = `
            <div class="feedback-topic-empty">
                <strong>${isAdminFilter ? 'Chưa có thông báo BIDFinder' : 'Chưa có chủ đề nào'}</strong>
                <span>${isAdminFilter ? 'Các topic do admin đăng sẽ xuất hiện tại đây.' : 'Hãy tạo chủ đề đầu tiên cho cộng đồng BIDFinder.'}</span>
            </div>
        `;
        return;
    }

    list.innerHTML = visibleTopics.map(topic => `
        <button class="feedback-topic-item${topic.id === feedbackBoardState.activeTopicId ? ' active' : ''}" type="button" data-topic-id="${topic.id}">
            <span class="feedback-topic-item-meta">
                ${topic.is_admin_topic ? '<span class="feedback-topic-admin-badge">BIDFinder</span>' : ''}
                <span class="feedback-topic-item-status${topic.status === 'closed' ? ' is-closed' : ' is-open'}">
                    ${FEEDBACK_STATUS_ICONS[topic.status] || FEEDBACK_STATUS_ICONS.open}
                    ${FEEDBACK_STATUS_LABELS[topic.status] || topic.status}
                </span>
            </span>
            <strong>${escapeHtml(topic.title || '')}</strong>
            <span>${FEEDBACK_CATEGORY_LABELS[topic.category] || 'Chủ đề'} · ${Number(topic.reply_count || 0)} phản hồi · ${formatFeedbackDate(topic.created_at)}</span>
        </button>
    `).join('');
}

function showFeedbackEmptyDetail(message = 'Chọn một chủ đề để xem trao đổi') {
    const empty = document.getElementById('feedback-empty-detail');
    const detail = document.getElementById('feedback-topic-detail');
    const form = document.getElementById('feedback-topic-form');
    feedbackBoardState.activeTopic = null;
    feedbackBoardState.replies = [];
    feedbackBoardState.repliesNextOffset = 0;
    feedbackBoardState.repliesHasMore = false;
    feedbackBoardState.repliesLoading = false;
    if (empty) {
        empty.hidden = false;
        const strong = empty.querySelector('strong');
        if (strong) strong.textContent = message;
    }
    if (detail) detail.hidden = true;
    if (form) form.hidden = true;
}

function showFeedbackTopicForm() {
    if (!requireFeedbackAuthentication()) return;

    document.getElementById('feedback-empty-detail')?.setAttribute('hidden', '');
    document.getElementById('feedback-topic-detail')?.setAttribute('hidden', '');
    feedbackBoardState.activeTopic = null;
    feedbackBoardState.replies = [];
    feedbackBoardState.repliesNextOffset = 0;
    feedbackBoardState.repliesHasMore = false;
    feedbackBoardState.repliesLoading = false;
    const form = document.getElementById('feedback-topic-form');
    if (form) {
        form.hidden = false;
        requestAnimationFrame(() => document.getElementById('feedback-topic-input')?.focus());
    }
}

function renderFeedbackTopicPreview(topic) {
    if (!topic) return;
    renderFeedbackTopicDetail(
        { ...topic, body: topic.body || '' },
        [],
        { loading: !topic.body }
    );
}

function renderFeedbackTopicDetail(topic, replies = [], options = {}) {
    const empty = document.getElementById('feedback-empty-detail');
    const detail = document.getElementById('feedback-topic-detail');
    const form = document.getElementById('feedback-topic-form');
    if (empty) empty.hidden = true;
    if (form) form.hidden = true;
    if (!detail) return;

    detail.hidden = false;
    feedbackBoardState.activeTopic = topic;
    const statusEl = document.getElementById('feedback-topic-status');
    if (statusEl) {
        statusEl.textContent = FEEDBACK_STATUS_LABELS[topic.status] || topic.status;
        statusEl.hidden = true;
    }
    document.getElementById('feedback-topic-title').textContent = topic.title || '';
    const bodyEl = document.getElementById('feedback-topic-body');
    if (bodyEl) {
        bodyEl.classList.toggle('is-loading', Boolean(options.loading));
        bodyEl.textContent = options.loading ? '' : (topic.body || '');
    }
    document.getElementById('feedback-topic-actions').hidden = !feedbackBoardState.isAdmin;

    const closeButton = document.getElementById('close-feedback-topic');
    const reopenButton = document.getElementById('reopen-feedback-topic');
    if (closeButton) closeButton.hidden = topic.status === 'closed';
    if (reopenButton) reopenButton.hidden = topic.status !== 'closed';

    const replyBody = document.getElementById('feedback-reply-body');
    const currentAvatar = document.getElementById('feedback-current-avatar');
    const currentUser = window.BIDFinderAuth?.getUser?.();
    if (currentAvatar) {
        currentAvatar.textContent = getFeedbackAuthorInitial(currentUser?.full_name, currentUser?.email, feedbackBoardState.isAdmin);
        currentAvatar.classList.toggle('is-admin', feedbackBoardState.isAdmin);
    }
    if (replyBody) replyBody.value = '';
    syncFeedbackComposerAuthState();

    renderFeedbackReplies(replies);
}

async function loadFeedbackTopics({ selectFirst = true } = {}) {
    setFeedbackStatus('');
    const response = await getAuthorizedFetch()(`${API_BASE_URL}/api/feedback/topics`);
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.success === false) {
        throw new Error(result.message || result.detail || 'Không tải được danh sách chủ đề.');
    }
    feedbackBoardState.topics = Array.isArray(result.topics) ? result.topics : [];
    feedbackBoardState.isAdmin = Boolean(result.is_admin);
    if (selectFirst && !feedbackBoardState.activeTopicId && feedbackBoardState.topics.length) {
        const adminTopics = feedbackBoardState.topics.filter(topic => topic.is_admin_topic);
        const defaultTopic = adminTopics.reduce((newest, topic) => {
            const newestTime = new Date(newest?.created_at || 0).getTime();
            const topicTime = new Date(topic.created_at || 0).getTime();
            return topicTime > newestTime ? topic : newest;
        }, adminTopics[0]) || feedbackBoardState.topics[0];
        feedbackBoardState.activeTopicId = defaultTopic.id;
    }
    renderFeedbackTopicList();
    setFeedbackStatus('');
    if (feedbackBoardState.activeTopicId) {
        await loadFeedbackTopicDetail(feedbackBoardState.activeTopicId);
    } else {
        showFeedbackEmptyDetail();
    }
}

async function loadFeedbackTopicDetail(topicId) {
    const numericTopicId = Number(topicId);
    feedbackBoardState.activeTopicId = numericTopicId;
    feedbackBoardState.replies = [];
    feedbackBoardState.repliesNextOffset = 0;
    feedbackBoardState.repliesHasMore = false;
    feedbackBoardState.repliesLoading = false;
    renderFeedbackTopicList();
    setFeedbackStatus('');

    const cached = feedbackBoardState.topicDetails.get(numericTopicId);
    const cachedAt = Number(cached?.cachedAt || 0);
    const isFreshCache = cached?.topic && Date.now() - cachedAt < FEEDBACK_TOPIC_CACHE_TTL_MS;
    if (cached?.topic) {
        feedbackBoardState.replies = Array.isArray(cached.replies) ? cached.replies.slice() : [];
        feedbackBoardState.repliesHasMore = Boolean(cached.repliesHasMore);
        feedbackBoardState.repliesNextOffset = Number(cached.repliesNextOffset || feedbackBoardState.replies.length);
        renderFeedbackTopicDetail(cached.topic, feedbackBoardState.replies);
        const scroller = document.querySelector('#feedback-topic-detail .feedback-discussion-scroll');
        if (scroller) scroller.scrollTop = 0;
    } else {
        const topicMeta = feedbackBoardState.topics.find(topic => topic.id === numericTopicId);
        if (topicMeta) {
            renderFeedbackTopicPreview(topicMeta);
            const scroller = document.querySelector('#feedback-topic-detail .feedback-discussion-scroll');
            if (scroller) scroller.scrollTop = 0;
        }
    }
    if (isFreshCache) {
        setFeedbackStatus('');
        return;
    }

    const params = new URLSearchParams({
        comments_limit: String(FEEDBACK_REPLY_BATCH_SIZE),
        comments_offset: '0'
    });
    let response;
    try {
        response = await getAuthorizedFetch()(`${API_BASE_URL}/api/feedback/topics/${topicId}?${params.toString()}`);
    } catch (error) {
        if (feedbackBoardState.activeTopicId !== numericTopicId) return;
        throw error;
    }
    const result = await response.json().catch(() => ({}));
    if (feedbackBoardState.activeTopicId !== numericTopicId) return;
    if (!response.ok || result.success === false) {
        throw new Error(result.message || result.detail || 'Không tải được chủ đề này.');
    }
    feedbackBoardState.isAdmin = Boolean(result.is_admin);
    feedbackBoardState.replies = Array.isArray(result.replies) ? result.replies : [];
    feedbackBoardState.repliesHasMore = Boolean(result.replies_has_more);
    feedbackBoardState.repliesNextOffset = Number(result.replies_next_offset || feedbackBoardState.replies.length);
    feedbackBoardState.topicDetails.set(numericTopicId, {
        topic: result.topic,
        replies: feedbackBoardState.replies.slice(),
        repliesHasMore: feedbackBoardState.repliesHasMore,
        repliesNextOffset: feedbackBoardState.repliesNextOffset,
        cachedAt: Date.now()
    });
    renderFeedbackTopicDetail(result.topic, feedbackBoardState.replies);
    const scroller = document.querySelector('#feedback-topic-detail .feedback-discussion-scroll');
    if (scroller) scroller.scrollTop = 0;
    setFeedbackStatus('');
}

async function loadMoreFeedbackReplies() {
    const topicId = feedbackBoardState.activeTopicId;
    if (!topicId || !feedbackBoardState.repliesHasMore || feedbackBoardState.repliesLoading) return;
    feedbackBoardState.repliesLoading = true;
    try {
        const params = new URLSearchParams({
            comments_limit: String(FEEDBACK_REPLY_BATCH_SIZE),
            comments_offset: String(feedbackBoardState.repliesNextOffset)
        });
        const response = await getAuthorizedFetch()(`${API_BASE_URL}/api/feedback/topics/${topicId}?${params.toString()}`);
        const result = await response.json().catch(() => ({}));
        if (feedbackBoardState.activeTopicId !== topicId) return;
        if (!response.ok || result.success === false) return;
        const nextReplies = Array.isArray(result.replies) ? result.replies : [];
        const existingIds = new Set(feedbackBoardState.replies.map(reply => reply.id));
        feedbackBoardState.replies = feedbackBoardState.replies.concat(nextReplies.filter(reply => !existingIds.has(reply.id)));
        feedbackBoardState.repliesHasMore = Boolean(result.replies_has_more);
        feedbackBoardState.repliesNextOffset = Number(result.replies_next_offset || feedbackBoardState.replies.length);
        const cached = feedbackBoardState.topicDetails.get(Number(topicId));
        if (cached) {
            cached.replies = feedbackBoardState.replies.slice();
            cached.repliesHasMore = feedbackBoardState.repliesHasMore;
            cached.repliesNextOffset = feedbackBoardState.repliesNextOffset;
            cached.cachedAt = Date.now();
        }
        renderFeedbackReplies(feedbackBoardState.replies);
    } finally {
        feedbackBoardState.repliesLoading = false;
    }
}

function handleFeedbackDiscussionScroll(event) {
    const scroller = event.currentTarget;
    if (!scroller || feedbackBoardState.repliesLoading || !feedbackBoardState.repliesHasMore) return;
    const remaining = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
    if (remaining < 160) {
        loadMoreFeedbackReplies();
    }
}

function openFeedbackModal() {
    const modal = document.getElementById('feedback-modal');
    if (!modal) return;

    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
    setFeedbackStatus('');
    feedbackBoardState.activeTopicId = null;
    feedbackBoardState.activeTopic = null;
    loadFeedbackTopics().catch(error => {
        console.error('Feedback topics load failed:', error);
        setFeedbackStatus(error?.message || 'Không tải được thông báo lúc này.', 'error');
        showFeedbackEmptyDetail('Không tải được thông báo');
    });
    window.feather?.replace?.();
    window.BIDFinderAnalytics?.track?.('feedback_opened');
}

function closeFeedbackModal() {
    const modal = document.getElementById('feedback-modal');
    if (!modal) return;

    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
}

async function createFeedbackTopic(event) {
    event?.preventDefault?.();
    if (!requireFeedbackAuthentication()) return;

    const title = document.getElementById('feedback-topic-input')?.value?.trim() || '';
    const body = document.getElementById('feedback-topic-body-input')?.value?.trim() || '';
    const category = document.getElementById('feedback-category-input')?.value || 'idea';
    const button = document.getElementById('send-feedback-topic');
    const defaultText = button?.textContent || 'Đăng chủ đề';
    if (button) {
        button.disabled = true;
        button.textContent = 'Đang đăng...';
    }
    try {
        const response = await getAuthorizedFetch()(`${API_BASE_URL}/api/feedback/topics`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, body, category })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.success === false) {
            throw new Error(result.message || result.detail || 'Không tạo được chủ đề.');
        }
        document.getElementById('feedback-topic-form')?.reset?.();
        feedbackBoardState.activeTopicId = result.topic?.id || null;
        await loadFeedbackTopics({ selectFirst: false });
        setFeedbackStatus('Đã đăng chủ đề.', 'success');
    } catch (error) {
        setFeedbackStatus(error?.message || 'Không tạo được chủ đề.', 'error');
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = defaultText;
        }
    }
}

async function sendFeedbackReply() {
    if (!requireFeedbackAuthentication()) return;

    const topicId = feedbackBoardState.activeTopicId;
    if (!topicId) return;
    if (feedbackBoardState.activeTopic?.status === 'closed' && !feedbackBoardState.isAdmin) {
        setFeedbackStatus('', 'error');
        return;
    }
    const body = document.getElementById('feedback-reply-body')?.value?.trim() || '';
    if (!body) {
        updateFeedbackReplyButtonState();
        return;
    }
    const button = document.getElementById('send-feedback-reply');
    if (button) {
        button.disabled = true;
    }
    try {
        const response = await getAuthorizedFetch()(`${API_BASE_URL}/api/feedback/topics/${topicId}/replies`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ body })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.success === false) {
            throw new Error(result.message || result.detail || '');
        }
        const replyBody = document.getElementById('feedback-reply-body');
        if (replyBody) replyBody.value = '';
        updateFeedbackReplyButtonState();
        if (result.reply) {
            const currentUser = window.BIDFinderAuth?.getUser?.();
            if (!result.reply.author_name && currentUser?.full_name) {
                result.reply.author_name = currentUser.full_name;
            }
            const existingIds = new Set(feedbackBoardState.replies.map(reply => reply.id));
            if (!existingIds.has(result.reply.id)) {
                feedbackBoardState.replies = feedbackBoardState.replies.concat([result.reply]);
            }
            renderFeedbackReplies(feedbackBoardState.replies);
            const cached = feedbackBoardState.topicDetails.get(Number(topicId));
            if (cached) {
                cached.replies = feedbackBoardState.replies.slice();
                cached.repliesHasMore = feedbackBoardState.repliesHasMore;
                cached.repliesNextOffset = feedbackBoardState.repliesNextOffset;
                cached.cachedAt = Date.now();
            }
            const scroller = document.querySelector('#feedback-topic-detail .feedback-discussion-scroll');
            requestAnimationFrame(() => {
                if (scroller) scroller.scrollTop = scroller.scrollHeight;
            });
        }
        feedbackBoardState.topics = feedbackBoardState.topics.map(topic => (
            topic.id === topicId
                ? { ...topic, reply_count: Number(topic.reply_count || 0) + 1 }
                : topic
        ));
        renderFeedbackTopicList();
        setFeedbackStatus('', 'success');
    } catch (error) {
        setFeedbackStatus('', 'error');
    } finally {
        updateFeedbackReplyButtonState();
    }
}

async function updateFeedbackTopicStatus(status) {
    const topicId = feedbackBoardState.activeTopicId;
    if (!topicId || !feedbackBoardState.isAdmin) return;
    const closeButton = document.getElementById('close-feedback-topic');
    const reopenButton = document.getElementById('reopen-feedback-topic');
    [closeButton, reopenButton].forEach(button => {
        if (button) button.disabled = true;
    });
    try {
        const response = await getAuthorizedFetch()(`${API_BASE_URL}/api/feedback/topics/${topicId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.success === false) {
            throw new Error(result.message || result.detail || 'Không cập nhật được chủ đề.');
        }
        feedbackBoardState.topicDetails.delete(Number(topicId));
        await loadFeedbackTopics({ selectFirst: false });
        await loadFeedbackTopicDetail(topicId);
        setFeedbackStatus(status === 'closed' ? 'Đã đóng chủ đề.' : 'Đã mở lại chủ đề.', 'success');
    } catch (error) {
        setFeedbackStatus(error?.message || 'Không cập nhật được chủ đề.', 'error');
    } finally {
        [closeButton, reopenButton].forEach(button => {
            if (button) button.disabled = false;
        });
    }
}

async function copyFeedbackText() {
    if (!hasFeedbackContent()) {
        setFeedbackStatus('Bạn chọn ít nhất một mục hoặc nhập nội dung góp ý trước nhé.', 'error');
        return;
    }

    const text = buildFeedbackMessage();

    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
        } else {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.setAttribute('readonly', '');
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            textarea.remove();
        }
        setFeedbackStatus('Đã sao chép nội dung góp ý.', 'success');
        window.BIDFinderAnalytics?.track?.('feedback_copied');
    } catch (error) {
        setFeedbackStatus('Không sao chép được. Bạn có thể dùng nút gửi góp ý.', 'error');
    }
}

function resetFeedbackForm() {
    document.querySelectorAll('.feedback-choice-row input[type="radio"]').forEach(input => {
        input.checked = false;
    });
    const task = document.getElementById('feedback-task');
    const message = document.getElementById('feedback-message');
    if (task) task.value = '';
    if (message) message.value = '';
}

async function sendFeedback() {
    if (!hasFeedbackContent()) {
        setFeedbackStatus('Bạn chọn ít nhất một mục hoặc nhập nội dung góp ý trước nhé.', 'error');
        return;
    }

    const sendButton = document.getElementById('send-feedback');
    const defaultText = sendButton?.textContent || 'Gửi góp ý';
    if (sendButton) {
        sendButton.disabled = true;
        sendButton.textContent = 'Đang gửi...';
    }

    try {
        const response = await getAuthorizedFetch()(`${API_BASE_URL}/api/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(buildFeedbackPayload())
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.success === false) {
            throw new Error(result.message || 'Không thể gửi góp ý lúc này.');
        }

        resetFeedbackForm();
        setFeedbackStatus(result.message || 'Cảm ơn bạn đã góp ý. BIDFinder đã ghi nhận phản hồi của bạn.', 'success');
        window.BIDFinderAnalytics?.track?.('feedback_submitted');
    } catch (error) {
        console.error('Feedback submit failed:', error);
        setFeedbackStatus(error?.message || 'Không thể gửi góp ý lúc này. Bạn thử lại sau nhé.', 'error');
    } finally {
        if (sendButton) {
            sendButton.disabled = false;
            sendButton.textContent = defaultText;
        }
    }
}

function initFeedbackModalEvents() {
    document.getElementById('open-feedback-modal')?.addEventListener('click', openFeedbackModal);
    document.getElementById('close-feedback-modal')?.addEventListener('click', closeFeedbackModal);
    document.querySelector('#feedback-modal .feedback-overlay')?.addEventListener('click', closeFeedbackModal);
    document.getElementById('new-feedback-topic')?.addEventListener('click', showFeedbackTopicForm);
    document.getElementById('cancel-feedback-topic')?.addEventListener('click', () => {
        feedbackBoardState.activeTopicId
            ? loadFeedbackTopicDetail(feedbackBoardState.activeTopicId).catch(() => showFeedbackEmptyDetail())
            : showFeedbackEmptyDetail();
    });
    document.getElementById('feedback-topic-form')?.addEventListener('submit', createFeedbackTopic);
    document.getElementById('send-feedback-reply')?.addEventListener('click', sendFeedbackReply);
    document.getElementById('feedback-reply-body')?.addEventListener('input', updateFeedbackReplyButtonState);
    window.addEventListener('bidfinder:auth-changed', syncFeedbackComposerAuthState);
    document.querySelector('#feedback-topic-detail .feedback-discussion-scroll')?.addEventListener('scroll', handleFeedbackDiscussionScroll);
    document.getElementById('feedback-reply-body')?.addEventListener('keydown', event => {
        if (event.key !== 'Enter' || event.isComposing) return;
        event.preventDefault();
        if (!document.getElementById('send-feedback-reply')?.disabled) {
            sendFeedbackReply();
        }
    });
    document.getElementById('close-feedback-topic')?.addEventListener('click', () => updateFeedbackTopicStatus('closed'));
    document.getElementById('reopen-feedback-topic')?.addEventListener('click', () => updateFeedbackTopicStatus('open'));
    const filterButton = document.getElementById('feedback-topic-filter-button');
    const filterMenu = document.getElementById('feedback-topic-filter-menu');
    filterButton?.addEventListener('click', event => {
        event.stopPropagation();
        const nextHidden = !filterMenu?.hidden ? true : false;
        if (filterMenu) filterMenu.hidden = nextHidden;
        filterButton.setAttribute('aria-expanded', String(!nextHidden));
    });
    filterMenu?.addEventListener('click', event => {
        const option = event.target.closest('[data-feedback-filter-value]');
        if (!option) return;
        const filter = option.dataset.feedbackFilterValue || 'all';
        feedbackBoardState.topicFilter = filter;
        filterMenu.hidden = true;
        filterButton?.setAttribute('aria-expanded', 'false');
        const visibleTopics = getVisibleFeedbackTopics();
        if (!visibleTopics.some(topic => topic.id === feedbackBoardState.activeTopicId)) {
            feedbackBoardState.activeTopicId = visibleTopics[0]?.id || null;
            if (feedbackBoardState.activeTopicId) {
                loadFeedbackTopicDetail(feedbackBoardState.activeTopicId).catch(error => {
                    setFeedbackStatus(error?.message || 'Không tải được chủ đề.', 'error');
                });
            } else {
                showFeedbackEmptyDetail(filter === 'admin' ? 'Chưa có thông báo BIDFinder' : 'Chọn một chủ đề để xem trao đổi');
            }
        }
        renderFeedbackTopicList();
    });
    document.addEventListener('click', event => {
        if (!filterMenu || filterMenu.hidden) return;
        if (event.target.closest('.feedback-topic-filter')) return;
        filterMenu.hidden = true;
        filterButton?.setAttribute('aria-expanded', 'false');
    });
    document.getElementById('feedback-topic-list')?.addEventListener('click', event => {
        const item = event.target.closest('[data-topic-id]');
        if (!item) return;
        loadFeedbackTopicDetail(Number(item.dataset.topicId)).catch(error => {
            setFeedbackStatus(error?.message || 'Không tải được chủ đề.', 'error');
        });
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && document.getElementById('feedback-modal')?.classList.contains('show')) {
            closeFeedbackModal();
        }
    });
}

function getActiveResultViewContext() {
    const fallbackView = legacyDatasetDefinition().resultPanel;
    const view = document.querySelector('.scope-btn.active')?.getAttribute('data-view') || fallbackView;
    const contexts = {
        'df1-panel': { key: 'df1', tableId: 'standard-table' },
        'df2-panel': { key: 'df2', tableId: 'extended-table' },
        'df3-panel': { key: 'df3', tableId: 'traditional-table' }
    };
    return contexts[view] || contexts[fallbackView] || contexts['df1-panel'];
}

function updateLegacyPagination() {
    const { key, tableId: activeTableId } = getActiveResultViewContext();
    const page = Math.max(1, Number(currentQueryMeta.page || currentQueryRequest?.page || 1));
    const pageMeta = currentQueryMeta;
    const displayed = Number(pageMeta[`${key}Displayed`] || 0);
    const pageSize = Math.max(1, Number(currentQueryRequest?.limit || displayed || 1));
    const total = workingSetAvailable[activeTableId]
        ? Number(pageMeta[`${key}WorkingCount`] || 0)
        : Number(pageMeta[`${key}Total`] || 0);
    const cumulativeDisplayed = Math.max(0, (page - 1) * pageSize + displayed);
    const shownThrough = total > 0 ? Math.min(cumulativeDisplayed, total) : cumulativeDisplayed;
    const resultLimit = getAppliedWorkingSetLimit(activeTableId);
    const resultLimitReached = Number.isFinite(resultLimit) && cumulativeDisplayed >= resultLimit;
    const totalLabel = getResultTableCountLabel(activeTableId, displayed);
    const hasMore = Boolean(pageMeta[`${key}HasMore`]);
    const previous = document.getElementById('legacy-prev-page');
    const next = document.getElementById('legacy-next-page');
    const label = document.getElementById('legacy-page-label');
    if (previous) previous.disabled = page <= 1;
    if (next) next.disabled = !hasMore || resultLimitReached;
    if (label) label.textContent = `Trang ${page} · ${shownThrough.toLocaleString('vi-VN')}/${totalLabel}`;
}

function initLegacyDatasetControls() {
    const searchForm = getProcurementSearchForm();
    if (!searchForm?.matches?.('typesense-search-form')) return;
    searchForm.addEventListener('dataset-group-change', event => {
        const group = normalizeLegacyDatasetGroup(event.detail?.group);
        if (!group || !LEGACY_DATASET_GROUPS[group]) return;
        activeLegacyDatasetGroup = group;
        const definition = legacyDatasetDefinition(group);
        currentQueryRequest = buildQueryRequest({ ...currentQueryRequest, filters: {} }, {
            scope: definition.scope,
            group,
            sourceTypes: [],
            columnFilters: {},
            page: 1
        });
        resetQueryResultMeta();
        updateResults([], [], [], { resetMiniFilters: true });
        activateResultView(definition.resultPanel);
        updateLegacyPagination();
    });
    initAdvancedContractControls();
}

function initLegacyPagination() {
    document.getElementById('legacy-prev-page')?.addEventListener('click', () => {
        const page = Math.max(1, Number(currentQueryRequest?.page || currentQueryMeta.page || 1) - 1);
        document.dispatchEvent(new CustomEvent('bidfinder:page-request', { detail: { page } }));
    });
    document.getElementById('legacy-next-page')?.addEventListener('click', () => {
        const page = Math.max(1, Number(currentQueryRequest?.page || currentQueryMeta.page || 1) + 1);
        document.dispatchEvent(new CustomEvent('bidfinder:page-request', { detail: { page } }));
    });
    document.getElementById('close-legacy-row-detail')?.addEventListener('click', () => {
        closeLegacyRowDetail();
    });
    document.querySelector('[data-close-legacy-row-detail]')?.addEventListener('click', () => closeLegacyRowDetail());
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && document.getElementById('legacy-row-detail')?.classList.contains('show')) {
            closeLegacyRowDetail();
        }
    });
    updateLegacyPagination();
}

function initResultViewSwitching() {
    const viewButtons = document.querySelectorAll('.scope-btn');

    viewButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetId = button.getAttribute('data-view');
            activateResultView(targetId);
        });
    });
}

function activateResultView(targetId) {
    if (!targetId) return;

    const viewButtons = document.querySelectorAll('.scope-btn');
    const resultPanels = document.querySelectorAll('.result-panel');
    const button = document.querySelector(`.scope-btn[data-view="${targetId}"]`);
    const activeButton = document.querySelector('.scope-btn.active');
    if (!button) return;
    if (activeButton === button) {
        updateLegacyPagination();
        return;
    }

    const targetPanel = document.getElementById(targetId);

    viewButtons.forEach(btn => {
        btn.classList.remove('active');
        btn.setAttribute('aria-selected', 'false');
    });

    button.classList.add('active');
    button.setAttribute('aria-selected', 'true');
    syncScopeSwitcherSlider();

    if (!targetPanel) {
        updateLegacyPagination();
        return;
    }
    resultPanels.forEach(panel => panel.classList.remove('active'));
    targetPanel.classList.add('active');
    updateLegacyPagination();
}

function syncScopeSwitcherSlider() {
    const switcher = document.querySelector('.data-scope-options, .result-table-tabs');
    if (!switcher || switcher.offsetParent === null) return;

    const slider = switcher.querySelector('.data-scope-slider');
    const activeBtn = switcher.querySelector('.scope-btn.active');
    if (!activeBtn) return;

    switcher.dataset.activeView = activeBtn.getAttribute('data-view') || '';
    if (slider) {
        slider.style.width = `${Math.ceil(activeBtn.offsetWidth)}px`;
        slider.style.transform = `translateX(${Math.round(activeBtn.offsetLeft)}px)`;
    }
}

function generateExportFilename(suffix = '') {
    const now = new Date();
    const timestamp = [
        now.getFullYear(),
        String(now.getMonth() + 1).padStart(2, '0'),
        String(now.getDate()).padStart(2, '0')
    ].join('') + '_' + [
        String(now.getHours()).padStart(2, '0'),
        String(now.getMinutes()).padStart(2, '0')
    ].join('');
    
    return `DuLieuTrungThau${suffix ? `_${suffix}` : ''}_${timestamp}.xlsx`;
}

function prepareExportData(data, headerOrder, currentOrder, tableId) {
    const columnOrder = headerOrder || currentOrder || [];
    const configKey = tableId === 'extended-table'
        ? 'df2'
        : tableId === 'traditional-table' ? 'df3' : 'df1';
    const fieldMappers = TABLE_CONFIGS[configKey]?.fieldMappers || {};
    return data.map(row => Object.fromEntries(columnOrder.map(columnName => {
        // Export the same display value as the table, including location
        // ordering and bidder-count rounding.
        const value = mapField(row, columnName, fieldMappers);
        return [getResultColumnLabel(tableId, columnName), value ?? ''];
    })));
}

function buildExportWorksheet(data, headerOrder, currentOrder, tableId) {
    const cleanHeaderOrder = (headerOrder || currentOrder || []).filter(col => col !== 'STT');
    const exportHeaders = cleanHeaderOrder.map(columnName => getResultColumnLabel(tableId, columnName));
    const preparedData = prepareExportData(data, cleanHeaderOrder, currentOrder, tableId);
    const ws = XLSX.utils.json_to_sheet(preparedData, {
        header: exportHeaders,
        origin: 'A3'
    });

    XLSX.utils.sheet_add_aoa(ws, [
        ['Nguồn: BIDFinder – Hệ thống quản lý dữ liệu đấu thầu y tế']
    ], { origin: 'A1' });

    return ws;
}

function exportTableToExcel(tableId) {
    const exportDefinitions = [
        {
            tableId: 'standard-table',
            sheetName: 'Kết quả mua sắm thuốc'
        },
        {
            tableId: 'extended-table',
            sheetName: 'Kết quả mua sắm hàng hóa'
        },
        {
            tableId: 'traditional-table',
            sheetName: 'Kết quả mua sắm dược liệu'
        }
    ];
    const exportTables = exportDefinitions
        .map(definition => {
            const data = getExportData(definition.tableId);
            if (!data.length) return null;
            const headerOrder = getVisibleColumnOrder(definition.tableId);
            return {
                ...definition,
                data,
                headerOrder,
                worksheet: buildExportWorksheet(
                    data,
                    headerOrder,
                    TABLE_MAP[definition.tableId]?.columnOrder?.() || headerOrder,
                    definition.tableId
                )
            };
        })
        .filter(Boolean);

    if (!exportTables.length) {
        alert('Không có dữ liệu để xuất!');
        return;
    }

    const wb = XLSX.utils.book_new();
    exportTables.forEach(({ sheetName, worksheet }) => {
        XLSX.utils.book_append_sheet(wb, worksheet, sheetName);
    });

    const filename = generateExportFilename('TatCa');
    XLSX.writeFile(wb, filename);
    const rowCount = exportTables.reduce((total, table) => total + table.data.length, 0);
    window.BIDFinderAnalytics?.track?.('export_clicked', {
        table_id: 'all',
        source_table_id: tableId,
        row_count: rowCount,
        sheet_count: exportTables.length,
        visible_column_count: exportTables.reduce((total, table) => total + table.headerOrder.length, 0),
        table_row_counts: Object.fromEntries(exportTables.map(table => [table.tableId, table.data.length]))
    });
    console.log(`✅ Exported ${rowCount} records from ${exportTables.length} result tables to ${filename}`);
}

function initSearchFormEvents() {
    const searchForm = getProcurementSearchForm();
    if (!searchForm) return;
    let previewRequestId = 0;
    let previewAbortController = null;
    
    searchForm.addEventListener('apply-filters', async (e) => {
        previewRequestId += 1;
        previewAbortController?.abort();
        previewAbortController = null;

        const stopConnectionMessageTimer = startConnectionMessageTimer(searchForm);
        let appliedResult = null;
        try {
            await waitForWarmupWithUi(searchForm);
            appliedResult = await applyFilters(e.detail);
        } finally {
            stopConnectionMessageTimer();
            searchForm.setApplyLoading?.(false);
        }

        if (appliedResult?.success) {
            searchForm.setPreviewResult?.(getPreviewPayloadForRequest(e.detail, appliedResult));
        }

        const filterPanel = document.getElementById('filter-panel');
        const overlay = document.getElementById('panel-overlay');
        if (filterPanel) filterPanel.classList.remove('show');
        if (overlay) overlay.classList.remove('show');
    });
    
    searchForm.addEventListener('reset-filters', () => {
        const dataset = getLegacyDatasetRequest();
        currentQueryRequest = { ...dataset, filters: {}, columnFilters: {}, page: 1 };
        enableLegacyDatasetSearch();
        clearFilterUrlState();
        resetQueryResultMeta();
        updateResults([], [], [], { resetMiniFilters: true });
        document.dispatchEvent(new CustomEvent('bidfinder:query-reset'));
        hideLimitWarning();
    });

    document.addEventListener('bidfinder:page-request', async event => {
        const page = Math.max(1, Number(event.detail?.page || 1));
        const currentPage = Math.max(1, Number(currentQueryRequest?.page || currentQueryMeta.page || 1));
        const pageSize = Math.max(1, Number(currentQueryRequest?.limit || 1));
        const { tableId: activeTableId } = getActiveResultViewContext();
        if (workingSetAvailable[activeTableId]) {
            currentQueryRequest = buildQueryRequest(currentQueryRequest, { page });
            searchForm.setPage?.(page);
            refreshBoundedWorkingSetViews({ page, resetScroll: false, redrawCharts: true });
            setFilterUrlState(currentQueryRequest);
            return;
        }
        const resultLimit = getAppliedWorkingSetLimit(activeTableId);
        if (page > currentPage && Number.isFinite(resultLimit) && (page - 1) * pageSize >= resultLimit) {
            updateLegacyPagination();
            return;
        }
        const nextRequest = buildQueryRequest(currentQueryRequest, { page });
        searchForm.setPage?.(page);
        try {
            await applyFilters(nextRequest, { resetMiniFilters: false, resetScroll: false });
        } finally {
            searchForm.setApplyLoading?.(false);
        }
    });

    searchForm.addEventListener('preview-filters', async (e) => {
        const requestId = ++previewRequestId;
        previewAbortController?.abort();
        const controller = new AbortController();
        previewAbortController = controller;
        const stopConnectionMessageTimer = startConnectionMessageTimer(searchForm, controller.signal);
        let didTimeout = false;
        const timeoutId = window.setTimeout(() => {
            didTimeout = true;
            controller.abort();
        }, PREVIEW_REQUEST_TIMEOUT_MS);
        try {
            await waitForWarmupWithUi(searchForm, controller.signal);
            if (requestId !== previewRequestId || controller.signal.aborted) return;

            const previewRequest = enrichLegacyQueryRequest(e.detail);
            const result = await fetchQueryPreview(
                previewRequest,
                controller.signal
            );
            if (requestId !== previewRequestId) return;

            const previewPayload = {
                total: Number(result?.total || 0),
                totalLabel: String(result?.display || Number(result?.total || 0).toLocaleString('vi-VN')),
                exact: Boolean(result?.exact)
            };
            latestFilterPreview = {
                requestKey: stableStringify(previewRequest),
                payload: previewPayload
            };
            searchForm.setPreviewResult?.(previewPayload);
        } catch (err) {
            const aborted = controller.signal.aborted
                || err?.name === 'AbortError'
                || /abort/i.test(String(err?.message || ''));
            if (aborted && !didTimeout) return;
            if (requestId !== previewRequestId) return;
            console.warn('Query preview failed:', err);
            if (typeof searchForm.hasVisiblePreviewEstimate === 'function' && searchForm.hasVisiblePreviewEstimate()) {
                return;
            }
            searchForm.setPreviewResult?.({
                error: true,
                errorMessage: didTimeout || err?.name === 'TimeoutError'
                    ? 'Ước tính quá lâu, vui lòng thử lại hoặc thu hẹp điều kiện'
                    : ''
            });
        } finally {
            window.clearTimeout(timeoutId);
            stopConnectionMessageTimer();
        }
    });
}

function initFilterUrlEvents() {
    window.addEventListener('popstate', () => {
        const queryRequest = readFilterUrlState();
        const searchForm = getProcurementSearchForm();

        if (!queryRequest || !hasActiveQueryFilters(queryRequest)) {
            currentQueryRequest = { scope: 'all', filters: {} };
            searchForm?.setFilterPayload?.(currentQueryRequest);
            searchForm?.setPreviewResult?.({ idle: true });
            resetQueryResultMeta();
            updateResults([], [], { resetMiniFilters: true });
            hideLimitWarning();
            return;
        }

        restoreFilterUrlState().catch(error => {
            console.error('Unable to restore filters from URL:', error);
        });
    });
}

// ==============================
// PRODUCT JOURNEY
// ==============================
const PRODUCT_JOURNEY_STORAGE_KEY = 'bidfinder:product_journey_seen';
const PRODUCT_JOURNEY_TIMING = {
    clickStartDelay: 760,
    cursorPressDelay: 520,
    surfaceOpenDelay: 840,
    cursorHideDelay: 1320,
    repositionDelay: 180
};
let productJourneyState = null;

function getActiveTableIdForJourney() {
    return document.querySelector('.result-panel.active .table-wrapper')?.dataset.tableId || 'standard-table';
}

function getActiveTableWrapperForJourney() {
    return getTableWrapper(getActiveTableIdForJourney()) || document.querySelector('.table-wrapper');
}

function getFirstColumnMenuTriggerForJourney() {
    const tableId = getActiveTableIdForJourney();
    return document.querySelector(`.result-panel.active .column-menu-trigger[data-table-id="${tableId}"]`)
        || document.querySelector('.column-menu-trigger');
}

function getVisibleTableToolButtonForJourney(action) {
    const tableId = getActiveTableIdForJourney();
    return document.querySelector(`.result-panel.active .table-tool-btn[data-action="${action}"][data-table-id="${tableId}"]`)
        || document.querySelector(`.table-tool-btn[data-action="${action}"]`);
}

function getVisibleTableControlsForJourney() {
    const tableId = getActiveTableIdForJourney();
    return document.querySelector(`.result-panel.active .table-hover-controls[data-table-id="${tableId}"]`)
        || document.querySelector('.table-hover-controls');
}

function setJourneyTableToolsVisible(visible = true) {
    const wrapper = getActiveTableWrapperForJourney();
    wrapper?.classList.toggle('table-tools-open', Boolean(visible));
}

function setJourneyCardVisible(visible) {
    productJourneyState?.root
        ?.querySelector('.product-journey-card')
        ?.classList.toggle('is-hidden', !visible);
}

function markJourneySurface(element) {
    if (!element) return;
    element.classList.remove('product-journey-surface-pop');
    void element.offsetWidth;
    element.classList.add('product-journey-surface-pop');
    window.setTimeout(() => element.classList.remove('product-journey-surface-pop'), 620);
}

function closeJourneySurfaces() {
    closeFloatingTableUi();
    setJourneyTableToolsVisible(false);
    hideAllPanels();
    closeBulkSearchModal();
    closeFeedbackModal();
    document.getElementById('history-modal')?.classList.remove('show');
}

function openHistoryForJourney() {
    closeJourneySurfaces();
    const modal = document.getElementById('history-modal');
    if (!modal) return;
    if (typeof renderEmptyHistory === 'function') {
        renderEmptyHistory();
    }
    modal.classList.add('show');
    markJourneySurface(modal.querySelector('.history-content'));
    window.feather?.replace?.();
}

function openBulkForJourney() {
    closeJourneySurfaces();
    openBulkSearchModal();
    markJourneySurface(document.querySelector('#bulk-search-modal .bulk-search-dialog'));
}

function openFilterForJourney() {
    closeJourneySurfaces();
    showPanel('filter-panel');
    markJourneySurface(document.getElementById('filter-panel'));
}

function openColumnMenuForJourney() {
    closeJourneySurfaces();
    const trigger = getFirstColumnMenuTriggerForJourney();
    if (!trigger) return;
    openColumnMenu(trigger.dataset.tableId, trigger.dataset.colName, trigger);
}

function openColumnsPopoverForJourney() {
    closeJourneySurfaces();
    const button = getVisibleTableToolButtonForJourney('toggle-columns');
    if (button) openColumnsPopover(button);
}

function openFeedbackForJourney() {
    closeJourneySurfaces();
    openFeedbackModal();
    markJourneySurface(document.querySelector('#feedback-modal .feedback-dialog'));
}

function ensureAppViewForJourney() {
    document.body.classList.remove('landing-active');
    try {
        sessionStorage.setItem('bidfinder:view', 'app');
    } catch (error) {
        // Session storage can be unavailable in private contexts.
    }
}

function getProductJourneySteps() {
    return [
        {
            title: 'Làm quen với BIDFinder',
            body: '2 phút khám phá các chức năng chính của BIDFinder.',
            selector: '.main-content',
            placement: 'center',
            dialogOnly: true,
            before: () => {
                ensureAppViewForJourney();
                closeJourneySurfaces();
            }
        },
        {
            title: 'Cụm chức năng chính',
            body: 'Xem lịch sử cập nhật, tìm kiếm hàng loạt từ file Excel, tìm kiếm nâng cao hoặc phân tích trực quan',
            selector: '.workspace-actions',
            placement: 'bottom',
            before: closeJourneySurfaces
        },
        {
            title: 'Lịch sử cập nhật',
            body: 'Theo dõi gói thầu được cập nhật theo khoảng thời gian.',
            afterTitle: 'Lịch sử cập nhật',
            afterBody: 'Theo dõi gói thầu được cập nhật theo khoảng thời gian.',
            selector: '#open-run-history',
            focusAfterSelector: '#history-modal .history-content',
            afterClick: openHistoryForJourney
        },
        {
            title: 'Tìm kiếm hàng loạt',
            body: 'Tìm kiếm hàng loạt sản phẩm từ file Excel.',
            afterTitle: 'Tìm kiếm hàng loạt',
            afterBody: 'Tìm kiếm dựa trên file Excel có danh sách sản phẩm cần tìm kiếm. BIDFinder không lưu trữ file này.',
            selector: '#open-bulk-search-modal',
            focusAfterSelector: '#bulk-search-modal .bulk-search-dialog',
            before: closeJourneySurfaces,
            afterClick: openBulkForJourney
        },
        {
            title: 'Tìm kiếm nâng cao',
            body: 'Tìm kiếm với bộ lọc nâng cao.',
            afterTitle: 'Tìm kiếm nâng cao',
            afterBody: 'Tìm kiếm với bộ lọc nâng cao.',
            selector: '#open-filter-panel',
            focusAfterSelector: '#filter-panel',
            before: closeJourneySurfaces,
            afterClick: openFilterForJourney
        },
        {
            title: 'Ba nhóm dữ liệu',
            body: 'Kết quả tìm kiếm được phân loại theo ba nhóm: Hàng hóa, Thuốc và Dược liệu / Vị thuốc cổ truyền.',
            selector: '#data-view-switcher .result-table-tab-list',
            placement: 'bottom',
            before: () => {
                closeJourneySurfaces();
                activateResultView('df1-panel');
            }
        },
        {
            title: 'Không gian bảng dữ liệu',
            body: 'Bảng hỗ trợ thao tác tương tự làm việc với spreadsheet.',
            getElement: getActiveTableWrapperForJourney,
            placement: 'top',
            before: closeJourneySurfaces
        },
        {
            title: 'Thao tác trên từng cột',
            body: 'Mở menu cột để sắp xếp, tự căn độ rộng, ngắt dòng, ghim hoặc ẩn cột đang xem, tìm kiếm nhanh.',
            getElement: () => document.querySelector('.column-menu-popover') || getFirstColumnMenuTriggerForJourney(),
            placement: 'right',
            before: openColumnMenuForJourney
        },
        {
            title: 'Cụm chức năng trên bảng',
            body: 'Các chức năng ẩn/hiện cột, tải Excel và chế độ toàn màn hình.',
            getElement: getVisibleTableControlsForJourney,
            before: () => {
                closeJourneySurfaces();
                setJourneyTableToolsVisible(true);
            }
        },
        {
            title: 'Ẩn/hiện cột',
            body: 'Tùy chỉnh trên danh sách cột.',
            afterTitle: 'Ẩn/hiện cột',
            afterBody: 'Tùy chỉnh trên danh sách cột.',
            getElement: () => getVisibleTableToolButtonForJourney('toggle-columns'),
            focusAfterSelector: '.table-columns-popover:not([hidden])',
            before: () => {
                closeJourneySurfaces();
                setJourneyTableToolsVisible(true);
            },
            afterClick: openColumnsPopoverForJourney
        },
        {
            title: 'Tải Excel',
            body: 'Tải dữ liệu đang hiển thị.',
            afterTitle: 'Tải Excel',
            afterBody: 'Tải dữ liệu đang hiển thị.',
            getElement: () => getVisibleTableToolButtonForJourney('download'),
            before: () => {
                closeJourneySurfaces();
                setJourneyTableToolsVisible(true);
            },
            afterClick: () => setJourneyTableToolsVisible(true)
        },
        {
            title: 'Toàn màn hình',
            body: 'Mở rộng không gian hiển thị bảng dữ liệu.',
            afterTitle: 'Toàn màn hình',
            afterBody: 'Mở rộng không gian hiển thị bảng dữ liệu.',
            getElement: () => getVisibleTableToolButtonForJourney('fullscreen'),
            before: () => {
                closeJourneySurfaces();
                setJourneyTableToolsVisible(true);
            },
            afterClick: () => setJourneyTableToolsVisible(true)
        },
        {
            title: 'Hướng dẫn, thông báo và tài khoản',
            body: 'Xem hướng dẫn sử dụng, theo dõi thông báo từ BIDFinder và quản lý tài khoản.',
            selector: '.app-header-links',
            placement: 'bottom',
            before: closeJourneySurfaces
        },
        {
            title: 'Thông báo',
            body: 'Nơi theo dõi thông báo, cập nhật và trao đổi thông tin trong lĩnh vực đấu thầu.',
            afterTitle: 'Thông báo',
            afterBody: 'Bạn có thể theo dõi thông báo và cập nhật mới nhất trong lĩnh vực đấu thầu.',
            selector: '#open-feedback-modal',
            focusAfterSelector: '#feedback-modal .feedback-dialog',
            before: closeJourneySurfaces,
            afterClick: openFeedbackForJourney
        },
        {
            title: 'Sẵn sàng tìm kiếm',
            body: 'Bạn đã đi qua các chức năng chính của BIDFinder. Chúc bạn một ngày làm việc hiệu quả.',
            selector: '#open-filter-panel',
            placement: 'center',
            dialogOnly: true,
            before: closeJourneySurfaces
        }
    ];
}

function createProductJourneyDom() {
    if (document.getElementById('product-journey-root')) return;

    const root = document.createElement('div');
    root.id = 'product-journey-root';
    root.className = 'product-journey-root';
    root.hidden = true;
    root.innerHTML = `
        <div class="product-journey-dim"></div>
        <div class="product-journey-highlight" aria-hidden="true"></div>
        <div class="product-journey-cursor" aria-hidden="true"></div>
        <section class="product-journey-card" role="dialog" aria-live="polite" aria-label="Hướng dẫn sử dụng BIDFinder">
            <div class="product-journey-kicker"></div>
            <h3></h3>
            <p></p>
            <div class="product-journey-footer">
                <span class="product-journey-hint">Nhấn phím bất kỳ để tiếp tục.</span>
                <div class="product-journey-actions">
                    <button type="button" data-journey-action="prev" aria-label="Quay lại" title="Quay lại"></button>
                    <button type="button" data-journey-action="next" aria-label="Tiếp" title="Tiếp"></button>
                    <button type="button" data-journey-action="skip" aria-label="Tắt hướng dẫn" title="Tắt"></button>
                </div>
            </div>
        </section>
    `;
    document.body.appendChild(root);
}

function getJourneyTargetPoint(target) {
    const rect = target?.getBoundingClientRect?.();
    if (!rect) return null;
    return {
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2
    };
}

function simulateJourneyClick(target, onClick) {
    const state = productJourneyState;
    const cursor = state?.root?.querySelector('.product-journey-cursor');
    const point = getJourneyTargetPoint(target);
    if (!cursor || !point) {
        productJourneyState?.pendingClickComplete?.();
        onClick?.();
        return;
    }

    cursor.style.left = `${point.x}px`;
    cursor.style.top = `${point.y}px`;
    cursor.classList.add('is-visible');
    cursor.classList.remove('is-pressing');

    state.animationTimers.push(window.setTimeout(() => {
        cursor.classList.add('is-pressing');
    }, PRODUCT_JOURNEY_TIMING.cursorPressDelay));

    state.animationTimers.push(window.setTimeout(() => {
        state.pendingClickComplete?.();
        onClick?.();
        cursor.classList.remove('is-pressing');
    }, PRODUCT_JOURNEY_TIMING.surfaceOpenDelay));

    state.animationTimers.push(window.setTimeout(() => {
        cursor.classList.remove('is-visible');
    }, PRODUCT_JOURNEY_TIMING.cursorHideDelay));
}

function clearJourneyAnimationTimers() {
    if (!productJourneyState) return;
    (productJourneyState.animationTimers || []).forEach(timerId => window.clearTimeout(timerId));
    productJourneyState.animationTimers = [];
}

function completeJourneyClickAnimation() {
    const state = productJourneyState;
    if (!state?.isAnimating) return false;
    clearJourneyAnimationTimers();
    state.root?.querySelector('.product-journey-cursor')?.classList.remove('is-visible', 'is-pressing');
    state.pendingClickComplete?.();
    return true;
}

function finishJourneyClickStep(step) {
    const state = productJourneyState;
    if (!state) return;

    state.pendingClickComplete = null;
    step.afterClick?.();
    if (step.afterTitle) {
        state.root.querySelector('h3').textContent = step.afterTitle;
    }
    if (step.afterBody) {
        state.root.querySelector('p').textContent = step.afterBody;
    }
    const nextTarget = step.focusAfterSelector
        ? document.querySelector(step.focusAfterSelector)
        : resolveJourneyElement(step);
    if (nextTarget) {
        state.activeTarget = nextTarget;
        setTimeout(() => {
            setJourneyCardVisible(true);
            positionProductJourney(step, nextTarget);
        }, PRODUCT_JOURNEY_TIMING.repositionDelay);
    }
    state.isAnimating = false;
}

function resolveJourneyElement(step) {
    if (typeof step.getElement === 'function') return step.getElement();
    if (step.selector) return document.querySelector(step.selector);
    return null;
}

function positionProductJourney(step, target) {
    const state = productJourneyState;
    if (!state?.root || !target) return;

    const rect = target.getBoundingClientRect();
    const highlight = state.root.querySelector('.product-journey-highlight');
    const card = state.root.querySelector('.product-journey-card');

    if (step.dialogOnly) {
        highlight.hidden = true;
        const cardRect = card.getBoundingClientRect();
        card.style.left = `${Math.max(12, (window.innerWidth - cardRect.width) / 2)}px`;
        card.style.top = `${Math.max(12, (window.innerHeight - cardRect.height) / 2)}px`;
        return;
    }

    highlight.hidden = false;
    const margin = 8;
    const highlightRect = {
        left: Math.max(8, rect.left - margin),
        top: Math.max(8, rect.top - margin),
        width: Math.min(window.innerWidth - 16, rect.width + margin * 2),
        height: Math.min(window.innerHeight - 16, rect.height + margin * 2)
    };

    highlight.style.left = `${highlightRect.left}px`;
    highlight.style.top = `${highlightRect.top}px`;
    highlight.style.width = `${Math.max(44, highlightRect.width)}px`;
    highlight.style.height = `${Math.max(36, highlightRect.height)}px`;

    const cardRect = card.getBoundingClientRect();
    const gap = 16;
    let left = highlightRect.left + highlightRect.width + gap;
    let top = highlightRect.top + (highlightRect.height - cardRect.height) / 2;

    if (step.placement === 'center') {
        left = (window.innerWidth - cardRect.width) / 2;
        top = (window.innerHeight - cardRect.height) / 2;
    } else {
        const spaces = {
            right: window.innerWidth - (highlightRect.left + highlightRect.width),
            left: highlightRect.left,
            bottom: window.innerHeight - (highlightRect.top + highlightRect.height),
            top: highlightRect.top
        };
        const canFit = {
            right: spaces.right >= cardRect.width + gap + 12,
            left: spaces.left >= cardRect.width + gap + 12,
            bottom: spaces.bottom >= cardRect.height + gap + 12,
            top: spaces.top >= cardRect.height + gap + 12
        };
        const preferredOrder = window.innerWidth < 920
            ? ['bottom', 'top', 'right', 'left']
            : ['right', 'left', 'bottom', 'top'];
        const placement = preferredOrder.find(side => canFit[side])
            || preferredOrder.sort((a, b) => spaces[b] - spaces[a])[0];

        if (placement === 'left') {
            left = highlightRect.left - cardRect.width - gap;
            top = highlightRect.top + (highlightRect.height - cardRect.height) / 2;
        } else if (placement === 'bottom') {
            left = highlightRect.left + (highlightRect.width - cardRect.width) / 2;
            top = highlightRect.top + highlightRect.height + gap;
        } else if (placement === 'top') {
            left = highlightRect.left + (highlightRect.width - cardRect.width) / 2;
            top = highlightRect.top - cardRect.height - gap;
        }
    }

    left = Math.max(12, Math.min(left, window.innerWidth - cardRect.width - 12));
    top = Math.max(12, Math.min(top, window.innerHeight - cardRect.height - 12));
    card.style.left = `${left}px`;
    card.style.top = `${top}px`;
}

function renderProductJourneyStep() {
    const state = productJourneyState;
    if (!state) return;

    const steps = state.steps;
    const step = steps[state.index];
    if (!step) {
        endProductJourney({ completed: true });
        return;
    }

    state.isAnimating = false;
    clearJourneyAnimationTimers();
    state.pendingClickComplete = null;
    step.before?.();

    requestAnimationFrame(() => {
        const target = resolveJourneyElement(step);
        if (!target) {
            nextProductJourneyStep();
            return;
        }

        target.scrollIntoView?.({ block: 'center', inline: 'center', behavior: 'smooth' });
        state.activeTarget = target;
        state.root.hidden = false;
        state.root.classList.toggle('is-dialog-only', Boolean(step.dialogOnly));
        document.body.classList.add('product-journey-active');
        setJourneyCardVisible(typeof step.afterClick !== 'function');

        state.root.querySelector('.product-journey-kicker').textContent = `${state.index + 1}/${steps.length}`;
        state.root.querySelector('h3').textContent = step.title;
        state.root.querySelector('p').textContent = step.body;
        state.root.querySelector('[data-journey-action="prev"]').disabled = state.index === 0;
        state.root.querySelector('[data-journey-action="next"]').classList.toggle('is-final', state.index === steps.length - 1);

        setTimeout(() => positionProductJourney(step, target), 80);
        if (typeof step.afterClick === 'function') {
            state.isAnimating = true;
            state.pendingClickComplete = () => finishJourneyClickStep(step);
            state.animationTimers.push(window.setTimeout(() => {
                simulateJourneyClick(target);
            }, PRODUCT_JOURNEY_TIMING.clickStartDelay));
        }
        window.BIDFinderAnalytics?.track?.('product_journey_step_viewed', {
            step_index: state.index + 1,
            step_title: step.title
        });
    });
}

function nextProductJourneyStep() {
    if (!productJourneyState) return;
    if (completeJourneyClickAnimation()) return;
    productJourneyState.index += 1;
    renderProductJourneyStep();
}

function previousProductJourneyStep() {
    if (!productJourneyState || productJourneyState.index === 0) return;
    clearJourneyAnimationTimers();
    productJourneyState.index -= 1;
    renderProductJourneyStep();
}

function endProductJourney({ completed = false } = {}) {
    if (!productJourneyState) return;
    const { root } = productJourneyState;
    root.hidden = true;
    clearJourneyAnimationTimers();
    document.body.classList.remove('product-journey-active');
    closeJourneySurfaces();
    productJourneyState = null;
    try {
        localStorage.setItem(PRODUCT_JOURNEY_STORAGE_KEY, '1');
    } catch (error) {
        // Ignore storage failures.
    }
    window.BIDFinderAnalytics?.track?.('product_journey_closed', { completed });
}

function handleProductJourneyKeydown(event) {
    if (!productJourneyState) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.key === 'Escape') {
        endProductJourney({ completed: false });
        return;
    }
    if (productJourneyState.isAnimating) {
        completeJourneyClickAnimation();
        return;
    }
    if (event.key === 'ArrowLeft') {
        previousProductJourneyStep();
        return;
    }
    if (event.key === 'ArrowRight') {
        nextProductJourneyStep();
        return;
    }
    nextProductJourneyStep();
}

function handleProductJourneyClick(event) {
    if (!productJourneyState) return;
    event.preventDefault();
    event.stopPropagation();

    const action = event.target.closest('[data-journey-action]')?.dataset.journeyAction;
    if (productJourneyState.isAnimating && action !== 'skip') {
        if (action === 'next' || !action) completeJourneyClickAnimation();
        return;
    }
    if (action === 'prev') {
        previousProductJourneyStep();
        return;
    }
    if (action === 'skip') {
        endProductJourney({ completed: false });
        return;
    }
    nextProductJourneyStep();
}

function startProductJourney() {
    createProductJourneyDom();
    productJourneyState = {
        root: document.getElementById('product-journey-root'),
        steps: getProductJourneySteps(),
        index: 0,
        activeTarget: null,
        animationTimers: [],
        pendingClickComplete: null
    };
    renderProductJourneyStep();
    window.BIDFinderAnalytics?.track?.('product_journey_started');
}

function initProductJourney() {
    createProductJourneyDom();
    document.getElementById('open-product-journey')?.addEventListener('click', (event) => {
        event.preventDefault();
        startProductJourney();
    });

    document.addEventListener('keydown', handleProductJourneyKeydown, true);
    document.addEventListener('click', handleProductJourneyClick, true);
    window.addEventListener('resize', () => {
        if (!productJourneyState) return;
        const step = productJourneyState.steps[productJourneyState.index];
        positionProductJourney(step, productJourneyState.activeTarget);
    });
    window.addEventListener('scroll', () => {
        if (!productJourneyState) return;
        const step = productJourneyState.steps[productJourneyState.index];
        positionProductJourney(step, productJourneyState.activeTarget);
    }, true);
}



let actionTooltipElement = null;
let actionTooltipAnchor = null;

function getActionTooltipElement() {
    if (actionTooltipElement) return actionTooltipElement;
    actionTooltipElement = document.createElement('div');
    actionTooltipElement.className = 'bf-action-tooltip';
    actionTooltipElement.id = 'bf-action-tooltip';
    actionTooltipElement.setAttribute('role', 'tooltip');
    actionTooltipElement.setAttribute('aria-hidden', 'true');
    document.body.appendChild(actionTooltipElement);
    return actionTooltipElement;
}

function positionActionTooltip() {
    if (!actionTooltipElement || !actionTooltipAnchor || !actionTooltipElement.classList.contains('is-visible')) return;

    const anchorRect = actionTooltipAnchor.getBoundingClientRect();
    const tooltipRect = actionTooltipElement.getBoundingClientRect();
    const viewportMargin = 10;
    const gap = 8;
    const centeredLeft = anchorRect.left + (anchorRect.width - tooltipRect.width) / 2;
    const left = Math.max(
        viewportMargin,
        Math.min(centeredLeft, window.innerWidth - tooltipRect.width - viewportMargin)
    );
    const aboveTop = anchorRect.top - tooltipRect.height - gap;
    const belowTop = anchorRect.bottom + gap;
    const top = aboveTop >= viewportMargin || belowTop + tooltipRect.height > window.innerHeight - viewportMargin
        ? Math.max(viewportMargin, aboveTop)
        : belowTop;

    actionTooltipElement.style.left = `${left}px`;
    actionTooltipElement.style.top = `${top}px`;
}

function showActionTooltip(button) {
    if (!button?.dataset.title) return;
    const tooltip = getActionTooltipElement();
    actionTooltipAnchor = button;
    tooltip.textContent = button.dataset.title;
    tooltip.setAttribute('aria-hidden', 'false');
    tooltip.classList.add('is-visible');
    button.setAttribute('aria-describedby', tooltip.id);
    positionActionTooltip();
}

function hideActionTooltip(button) {
    if (actionTooltipAnchor !== button || !actionTooltipElement) return;
    actionTooltipElement.classList.remove('is-visible');
    actionTooltipElement.setAttribute('aria-hidden', 'true');
    button.removeAttribute('aria-describedby');
    actionTooltipAnchor = null;
}

function setActionTooltip(button, label) {
    if (!button || !label) return;
    button.setAttribute('aria-label', label);
    button.dataset.title = label;
    button.removeAttribute('title');
    if (actionTooltipAnchor === button && actionTooltipElement) {
        actionTooltipElement.textContent = label;
        positionActionTooltip();
    }
}

function initActionTooltips() {
    const tooltipTargets = document.querySelectorAll(
        '.action-btn, .btn-meta-simple, .full-search-credit, .app-icon-btn'
    );
    tooltipTargets.forEach(button => {
        const label = button.getAttribute('aria-label')
            || button.getAttribute('title')
            || button.dataset.title;
        setActionTooltip(button, label);
        if (button.dataset.tooltipBound === 'true') return;
        button.dataset.tooltipBound = 'true';
        button.addEventListener('mouseenter', () => showActionTooltip(button));
        button.addEventListener('mouseleave', () => hideActionTooltip(button));
        button.addEventListener('focusin', () => showActionTooltip(button));
        button.addEventListener('focusout', () => hideActionTooltip(button));
    });
    window.addEventListener('resize', positionActionTooltip);
    window.addEventListener('scroll', positionActionTooltip, true);
}

async function initializeAppData() {
    if (window.BIDFinderAuth?.requiresDataAuth?.() && !window.BIDFinderAuth?.isAuthenticated()) {
        appDataInitialized = false;
        metadata = null;
        initEmptyCharts();
        return;
    }

    if (appDataInitialized) {
        return;
    }

    try {
        appDataInitialized = true;
        // ✅ Không load df1/df2 nữa vì filter từ database
        if (DB_WARMUP_ENABLED) {
            warmupDatabase().catch(error => {
                console.warn('Database warmup failed:', error);
            });
        }
        await loadMetadata();
        initEmptyCharts();
        await restoreFilterUrlState();
        
        console.log('✅ App initialized - Ready for filtering from database');
        
    } catch (err) {
        appDataInitialized = false;
        console.error('❌ Error initializing app:', err);
        console.error('⚠️ Server có thể đang khởi động, vui lòng đợi 30s và refresh lại');
        await loadMetadata();
        initEmptyCharts();
    }
}


function initTableRangeSelection() {
    Object.keys(tableSel).forEach(tableId => {
        initTableRangeSelect(tableId);
        initTableKeyboardNavigation(tableId);
        initRowSelection(tableId);
        initColumnSelection(tableId);
    });
    initRangeCopy();
}

// Main initialization
document.addEventListener('DOMContentLoaded', function() {
    clearLegacyBulkUrlState();
    initStorageAndElements();
    initLandingShell();
    window.BIDFinderAuth?.init();
    initModalEvents();
    initBulkSearchEvents();
    initFeedbackModalEvents();
    initInsightDrawerEvents();
    initProductJourney();
    initResultViewSwitching();
    initLegacyDatasetControls();
    initLegacyPagination();
    initSearchFormEvents();
    initFilterUrlEvents();
    initActionTooltips();
    initGlobalKeyboardShortcuts();
    initializeAppData();
    syncScopeSwitcherSlider();
});

window.addEventListener('load', function() {
    console.log('🚀 Window loaded, initializing drag & drop...');
    setTimeout(() => {
        initTableColumnDragDrop();
        initTableRangeSelection();
        syncAllFrozenColumns();
        syncScopeSwitcherSlider();
    }, 1000);
});

window.addEventListener('resize', () => {
    syncAllFrozenColumns();
    syncScopeSwitcherSlider();
    rerenderActiveColumnMenu();
    rerenderColumnsPopover();
    Object.values(chartInstances || {}).forEach(chart => chart?.resize?.());
    historyTimelineChart?.resize?.();
});
