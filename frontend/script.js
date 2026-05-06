const API_BASE_URL =
  (window.location.protocol === 'file:' ||
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1')
    ? 'http://127.0.0.1:8000'
    : 'https://bidfinder.onrender.com';

window.API_BASE_URL = API_BASE_URL;

function getAuthorizedFetch() {
    return window.bidfinderAuthorizedFetch || fetch;
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

function formatDateForExcel(dateValue) {
    return formatDate(dateValue, true);
}

// ========= 2. ORDER COLUMNS
function reorderDataByColumns(data, columnOrder) {
    if (!data?.length || !columnOrder) return data;

    return data.map(row => 
        columnOrder.reduce((reordered, colName) => {
            const actualCol = Object.keys(row).find(k => k.trim() === colName.trim());
            reordered[colName] = actualCol ? row[actualCol] : '';
            return reordered;
        }, {})
    );
}

// ========= 3. STORAGE
const DF1_COLUMNS_ORDER = [
    'Tên hoạt chất','Tên thuốc','Nồng độ, hàm lượng',
    'Đường dùng','Dạng bào chế','Quy cách','GĐKLH hoặc GPNK','Mã thuốc',
    'Cơ sở sản xuất','Xuất xứ','Nhóm thuốc',
    'Đơn vị tính','Số lượng','Đơn giá trúng thầu (VND)','Thành tiền (VND)',    
    'Mã TBMT','Chủ đầu tư','Quyết định phê duyệt','Ngày phê duyệt',
    'Hình thức LCNT','Địa điểm','Ngày hết hiệu lực','Tình trạng hiệu lực','Nhà thầu trúng thầu'
];

const DF2_COLUMNS_ORDER = [
    'Tên phần/lô','Danh mục hàng hóa','Tính năng kỹ thuật',
    'Mặt hàng dự thầu','Nhãn hiệu','Ký mã hiệu',
    'Xuất xứ','Hãng sản xuất',
    'Đơn vị tính','Khối lượng','Đơn giá trúng thầu (VND)','Thành tiền (VND)',
    'Mã TBMT','Chủ đầu tư','Quyết định phê duyệt','Ngày phê duyệt',
    'Hình thức LCNT','Địa điểm','Ngày hết hiệu lực','Tình trạng hiệu lực','Nhà thầu trúng thầu'
];

let currentColumnOrderDf1 = [...DF1_COLUMNS_ORDER];
let currentColumnOrderDf2 = [...DF2_COLUMNS_ORDER];
const TABLE_DEFAULT_COLUMNS = {
    'standard-table': DF1_COLUMNS_ORDER,
    'extended-table': DF2_COLUMNS_ORDER
};
const TABLE_COLUMN_WIDTH_KEYS = {
    'standard-table': 'colWidthDf1',
    'extended-table': 'colWidthDf2'
};
const STORAGE_KEYS = {
    hiddenColumns: 'hiddenColumnsByTable',
    wrappedColumns: 'wrappedColumnsByTable',
    frozenColumns: 'frozenColumnsByTable',
    sortRule: 'activeTableSortRule'
};
const RESETTABLE_UI_STORAGE_KEYS = [
    'columnOrderDf1',
    'columnOrderDf2',
    'colWidthDf1',
    'colWidthDf2',
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
        'extended-table': normalizeStoredColumnSet(stored?.['extended-table'], 'extended-table')
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
        { key: 'columnOrderDf2', default: DF2_COLUMNS_ORDER, target: 'currentColumnOrderDf2' }
    ];

    configs.forEach(({ key, default: defaultOrder, target }) => {
        const saved = localStorage.getItem(key);
        if (!saved) return;

        try {
            const parsed = JSON.parse(saved);
            const validated = validateColumnOrder(parsed, defaultOrder, key);
            
            if (target === 'currentColumnOrderDf1') {
                currentColumnOrderDf1 = validated;
            } else {
                currentColumnOrderDf2 = validated;
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
const wrappedColumnsState = loadPersistentColumnSets(STORAGE_KEYS.wrappedColumns);
const frozenColumnsState = loadPersistentColumnSets(STORAGE_KEYS.frozenColumns);
const hiddenColumnsState = loadPersistentColumnSets(STORAGE_KEYS.hiddenColumns);
const miniFilterState = {
    'standard-table': {},
    'extended-table': {}
};
let activeSortRule = loadStoredSortRule();
const selectionState = {
    'standard-table': { rows: new Set(), columns: new Set(), lastRow: null, lastColumn: null },
    'extended-table': { rows: new Set(), columns: new Set(), lastRow: null, lastColumn: null }
};
let currentDisplayedDf1 = [];
let currentDisplayedDf2 = [];
let serverBaseDf1 = [];
let serverBaseDf2 = [];
let currentQueryMeta = {
    df1HasMore: false,
    df2HasMore: false,
    totalCount: 0,
    totalCountExact: true,
    totalCountLabel: '0',
    searchMode: 'standard',
    bulkSearchMode: 'standard',
    appliedTotalLimit: 0
};

// Configuration object cho từng loại table
const TABLE_CONFIGS = {
    df1: {
        tbody: () => standardTbody,
        columnOrder: () => currentColumnOrderDf1,
        rightAlignColumns: ['Số lượng', 'Đơn giá trúng thầu (VND)', 'Thành tiền (VND)'],
        fieldMappers: {
            'Ngày phê duyệt': formatDate,
            'Ngày hết hiệu lực': formatDate,
            'Số lượng': formatNumber,
            'Đơn giá trúng thầu (VND)': formatCurrency,
            'Thành tiền (VND)': formatCurrency
        }
    },
    df2: {
        tbody: () => extendedTbody,
        columnOrder: () => currentColumnOrderDf2,
        rightAlignColumns: ['Khối lượng', 'Đơn giá trúng thầu (VND)', 'Thành tiền (VND)'],
        fieldMappers: {
            'Ngày phê duyệt': formatDate,
            'Ngày hết hiệu lực': formatDate,
            'Khối lượng': formatNumber,
            'Đơn giá trúng thầu (VND)': formatCurrency,
            'Thành tiền (VND)': formatCurrency
        }
    }
};

const DEFAULT_COLUMN_WIDTHS = {
    'standard-table': {
        'Mã TBMT': 118,
        'Chủ đầu tư': 130,
        'Quyết định phê duyệt': 200,
        'Ngày phê duyệt': 150,
        'Mã thuốc': 120,
        'Tên thuốc': 150,
        'Tên hoạt chất': 150,
        'Nồng độ, hàm lượng': 200,
        'Đơn vị tính': 130,
        'Số lượng': 120,
        'Đơn giá trúng thầu (VND)': 220,
        'Thành tiền (VND)': 180,
        'Đường dùng': 140,
        'Dạng bào chế': 150,
        'Quy cách': 130,
        'Nhóm thuốc': 130,
        'GĐKLH hoặc GPNK': 180,
        'Cơ sở sản xuất': 160,
        'Xuất xứ': 130,
        'Nhà thầu trúng thầu': 210,
        'Hình thức LCNT': 150,
        'Địa điểm': 150,
        'Ngày hết hiệu lực': 180,
        'Tình trạng hiệu lực': 180
    },
    'extended-table': {
        'Mã TBMT': 118,
        'Chủ đầu tư': 130,
        'Quyết định phê duyệt': 200,
        'Ngày phê duyệt': 150,
        'Tên phần/lô': 160,
        'Danh mục hàng hóa': 210,
        'Tính năng kỹ thuật': 260,
        'Đơn vị tính': 130,
        'Khối lượng': 120,
        'Đơn giá trúng thầu (VND)': 220,
        'Thành tiền (VND)': 180,
        'Mặt hàng dự thầu': 180,
        'Nhãn hiệu': 145,
        'Ký mã hiệu': 145,
        'Xuất xứ': 130,
        'Hãng sản xuất': 170,
        'Nhà thầu trúng thầu': 210,
        'Hình thức LCNT': 150,
        'Địa điểm': 160,
        'Ngày hết hiệu lực': 180,
        'Tình trạng hiệu lực': 180
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

    const normalized = String(columnName || '').toLowerCase();
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

function renderTableData(data, configKey) {
    const config = TABLE_CONFIGS[configKey];
    const tbody = config.tbody();
    const tableId = configKey === 'df1' ? 'standard-table' : 'extended-table';
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
            tr.title = 'Phat hien dong trung trong ho so nguon. BidFinder giu nguyen du lieu goc va chi hien thi canh bao.';
        }
        tr.dataset.rowIndex = index;

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

function mapField(item, colName, fieldMappers) {
    const formatter = fieldMappers[colName];
    const rawValue = item[colName];
    return formatter ? formatter(rawValue) : (rawValue ?? '');
}

// Wrapper functions giữ lại interface cũ
function renderStandardData(data) {
    renderTableData(data, 'df1');
}

function renderExtendedData(data) {
    renderTableData(data, 'df2');
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
    const containerWidth = scrollContainer?.clientWidth || 0;
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
    return tableId === 'extended-table' ? 'df2' : 'df1';
}

function getDisplayedData(tableId) {
    return tableId === 'extended-table' ? currentDisplayedDf2 : currentDisplayedDf1;
}

function getRawFilteredData(tableId) {
    return tableId === 'extended-table' ? currentFilteredDf2 : currentFilteredDf1;
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
    label.textContent = colName;
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
    menuTrigger.setAttribute('aria-label', `Tuy chon cot ${colName}`);
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

const MAX_RESULTS_PER_TABLE = 200;
const FULL_SEARCH_TOTAL_LIMIT = 1000;
let currentQueryRequest = {
    scope: 'all',
    filters: {}
};
let currentAppliedPreview = null;


// ======== 1. APPLY
function buildQueryRequest(baseRequest = {}, overrides = {}) {
    const safeBase = baseRequest && typeof baseRequest === 'object' ? baseRequest : {};

    return {
        scope: safeBase.scope || 'all',
        filters: safeBase.filters && typeof safeBase.filters === 'object' ? { ...safeBase.filters } : {},
        ...overrides
    };
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
    window.history.replaceState({}, '', url);
}

function encodeFilterUrlState(queryRequest) {
    return encodeURIComponent(JSON.stringify(buildQueryRequest(queryRequest)));
}

function decodeFilterUrlState(rawValue) {
    if (!rawValue) return null;

    try {
        return buildQueryRequest(JSON.parse(decodeURIComponent(rawValue)));
    } catch (error) {
        try {
            return buildQueryRequest(JSON.parse(rawValue));
        } catch (fallbackError) {
            console.warn('Unable to parse filter URL state:', fallbackError);
            return null;
        }
    }
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
    window.history.replaceState({ bidfinderFilters: request }, '', url);
}

async function restoreFilterUrlState({ apply = true } = {}) {
    const queryRequest = readFilterUrlState();
    if (!queryRequest || !hasActiveQueryFilters(queryRequest)) return false;

    const searchForm = document.querySelector('custom-search-form');
    if (typeof searchForm?.setFilterPayload === 'function') {
        searchForm.setFilterPayload(queryRequest);
        searchForm.setPreviewResult?.({ loading: true });
    }

    currentQueryRequest = queryRequest;
    if (apply) {
        const result = await applyFilters(queryRequest);
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
        message: config.full_search_limit_message || 'Bạn đã dùng hết lượt full search hôm nay.'
    };
}

async function fetchQueryResults(
    queryRequest,
    sortRule = activeSortRule,
    limit = MAX_RESULTS_PER_TABLE,
    options = {}
) {
    await window.BIDFinderAuth?.whenReady?.();

    if (!requireAuthenticatedSession('login', 'full_query')) {
        throw new Error(window.BIDFinderAuth?.getFullQueryGateMessage?.() || 'Bạn cần đăng nhập để tra cứu dữ liệu.');
    }

    const searchMode = options?.searchMode === 'full' ? 'full' : 'standard';
    window.BIDFinderAnalytics?.trackSearchSubmitted?.(queryRequest, { searchMode });
    const requestBody = {
        scope: queryRequest?.scope || 'all',
        filters: queryRequest?.filters || {},
        sort: buildSortPayload(sortRule),
        limit,
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
        throw new Error('Bạn cần đăng nhập để tra cứu dữ liệu.');
    }

    const response = await getAuthorizedFetch()(`${API_BASE_URL}/api/query-preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            scope: queryRequest?.scope || 'all',
            filters: queryRequest?.filters || {}
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

function markDatabaseWarm() {
    dbWarmupReadyUntil = Date.now() + DB_WARM_TTL_MS;
}

function isDatabaseRecentlyWarm() {
    return Date.now() < dbWarmupReadyUntil;
}

function shouldWarmDatabase() {
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
            ...(result?.df2 || {})
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

    const totalCount = Number(normalized.totalCount || 0);
    const displayedCount = nextDf1.length + nextDf2.length;
    const totalCountExact = Boolean(normalized.totalCountExact);
    const totalCountLabel = String(normalized.totalCountLabel || totalCount);
    const hasMore = Boolean(normalized.df1.has_more || normalized.df2.has_more);
    const quota = getFullSearchQuotaState();

    if (hasMore) {
        showLimitWarning({
            totalCount,
            totalCountExact,
            totalCountLabel,
            displayedCount,
            searchMode: normalized.searchMode,
            bulkSearchMode: normalized.bulkSearchMode,
            fullSearchRemaining: quota.remaining,
            fullSearchDailyLimit: quota.limit,
            fullSearchEnabled: quota.enabled
        });
    } else {
        hideLimitWarning();
    }

    serverBaseDf1 = [...nextDf1];
    serverBaseDf2 = [...nextDf2];
    currentQueryMeta = {
        df1HasMore: Boolean(normalized.df1.has_more),
        df2HasMore: Boolean(normalized.df2.has_more),
        totalCount,
        totalCountExact,
        totalCountLabel,
        searchMode: normalized.searchMode,
        bulkSearchMode: normalized.bulkSearchMode,
        appliedTotalLimit: normalized.appliedTotalLimit
    };

    updateResults(nextDf1, nextDf2, { resetMiniFilters: options.resetMiniFilters !== false });
}


async function applyFilters(payload) {
    currentQueryRequest = buildQueryRequest(payload);
    closeFloatingTableUi();

    console.log('Applying filters with query request:', currentQueryRequest);

    try {
        const result = await fetchQueryResults(
            currentQueryRequest,
            activeSortRule,
            MAX_RESULTS_PER_TABLE,
            { searchMode: 'standard' }
        );

        if (result.success) {
            handleQuerySuccess(result);
            setFilterUrlState(currentQueryRequest);
            currentAppliedPreview = {
                requestKey: stableStringify(currentQueryRequest),
                payload: {
                    total: Number(result?.total_count || 0),
                    totalLabel: String(result?.total_count_label || Number(result?.total_count || 0).toLocaleString('vi-VN')),
                    exact: result?.total_count_exact !== false
                }
            };
            return result;
        } else {
            throw new Error(result.error || 'Query failed');
        }
    } catch (err) {
        console.error('Filter failed:', err);
        window.BIDFinderAnalytics?.track?.('search_failed', {
            search_mode: 'standard',
            error: err?.message || 'unknown'
        });
        resetQueryResultMeta();
        updateResults([], [], { resetMiniFilters: true });
        hideLimitWarning();
        if (err?.message) {
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
        alert(quota.message || 'Bạn đã dùng hết lượt full search hôm nay.');
        return;
    }

    const warningDiv = document.getElementById('result-warning');
    const actionButton = warningDiv?.querySelector('.result-warning-button');
    if (actionButton) {
        actionButton.disabled = true;
        actionButton.textContent = 'Đang tải...';
    }

    if (currentQueryMeta.searchMode === 'bulk' && lastBulkSearchPayloads?.length) {
        try {
            await runBulkSearch({ searchMode: 'full', reuseLastPayloads: true });
            return;
        } catch (error) {
            console.error('Bulk full search failed:', error);
        } finally {
            if (actionButton) {
                actionButton.disabled = false;
                actionButton.textContent = 'Full search';
            }
        }
    }

    try {
        const result = await fetchQueryResults(
            currentQueryRequest,
            activeSortRule,
            FULL_SEARCH_TOTAL_LIMIT,
            { searchMode: 'full' }
        );
        if (result.success) {
            handleQuerySuccess(result, { resetMiniFilters: false });
            return;
        }
        throw new Error(result.error || 'Full search failed');
    } catch (error) {
        if (actionButton) {
            actionButton.disabled = false;
            actionButton.textContent = 'Full search';
        }
        console.error('Full search failed:', error);
        window.BIDFinderAnalytics?.track?.('search_failed', {
            search_mode: 'full',
            error: error?.message || 'unknown'
        });
        if (error?.message) {
            alert(error.message);
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
    const localizedTotal = Number(totalCount || 0).toLocaleString('vi-VN');
    const summaryText = String(totalCountLabel || (totalCountExact ? localizedTotal : `${localizedTotal}+`));
    const displayedText = Number(displayedCount || 0).toLocaleString('vi-VN');
    const canOfferFullSearch =
        searchMode !== 'full'
        && !(searchMode === 'bulk' && bulkSearchMode === 'full')
        && fullSearchEnabled
        && Number(fullSearchDailyLimit || 0) > 0
        && Number(fullSearchRemaining || 0) > 0;

    const warningDiv = document.getElementById('result-warning');
    if (!warningDiv) {
        return;
    }

    warningDiv.replaceChildren();

    const title = document.createElement('strong');
    title.textContent = searchMode === 'bulk'
        ? 'Kết quả tra cứu hàng loạt đã đạt giới hạn hiển thị'
        : (searchMode === 'full' ? 'Kết quả full search vẫn còn bị giới hạn' : 'Giới hạn kết quả tìm kiếm');
    warningDiv.appendChild(title);
    warningDiv.appendChild(document.createElement('br'));
    warningDiv.appendChild(document.createTextNode(`Hiện đang hiển thị ${displayedText}/${summaryText} dòng.`));

    const detail = document.createElement('div');
    detail.className = 'result-warning-actions';

    const quota = document.createElement('span');
    quota.className = 'result-warning-quota';
    if (canOfferFullSearch) {
        quota.textContent = `Bạn còn ${Number(fullSearchRemaining).toLocaleString('vi-VN')}/${Number(fullSearchDailyLimit).toLocaleString('vi-VN')} lượt full search hôm nay.`;
    } else if (searchMode === 'full' || (searchMode === 'bulk' && bulkSearchMode === 'full')) {
        quota.textContent = 'Bạn đang ở chế độ full search. Hãy thu hẹp bộ lọc nếu cần ít nhiễu hơn.';
    } else if (Number(fullSearchDailyLimit || 0) > 0) {
        quota.textContent = `Bạn đã dùng hết ${Number(fullSearchDailyLimit).toLocaleString('vi-VN')} lượt full search hôm nay.`;
    } else {
        quota.textContent = 'Full search hiện chưa khả dụng.';
    }
    detail.appendChild(quota);

    if (canOfferFullSearch) {
        const actionButton = document.createElement('button');
        actionButton.type = 'button';
        actionButton.className = 'result-warning-button';
        actionButton.textContent = 'Full search';
        actionButton.addEventListener('click', () => {
            void triggerFullSearch();
        });
        detail.appendChild(actionButton);
    }

    warningDiv.appendChild(detail);
    warningDiv.style.display = 'block';
}

// Helper: Hide limit warning
function hideLimitWarning() {
    const warningDiv = document.getElementById('result-warning');
    if (warningDiv) {
        setInfoBannerMessage(
            warningDiv,
            'Giới hạn kết quả tìm kiếm',
            'Vui lòng thu hẹp điều kiện tìm kiếm.'
        );
        warningDiv.style.display = 'none';
    }
}

function resetQueryResultMeta() {
    serverBaseDf1 = [];
    serverBaseDf2 = [];
    currentAppliedPreview = null;
    currentQueryMeta = {
        df1HasMore: false,
        df2HasMore: false,
        totalCount: 0,
        totalCountExact: true,
        totalCountLabel: '0',
        searchMode: 'standard',
        bulkSearchMode: 'standard',
        appliedTotalLimit: 0
    };
}

// Helper: Update results and render
function applyMiniFiltersToRows(tableId, rows) {
    const filters = miniFilterState[tableId] || {};
    const activeFilters = Object.entries(filters)
        .map(([columnName, rawValue]) => [columnName, String(rawValue || '').trim().toLowerCase()])
        .filter(([, value]) => value);

    if (!activeFilters.length) return rows;

    const configKey = getTableScopeKey(tableId);
    const config = TABLE_CONFIGS[configKey];
    if (!config) return rows;

    return rows.filter(row => (
        activeFilters.every(([columnName, keyword]) => {
            const displayValue = String(mapField(row, columnName, config.fieldMappers) ?? '').toLowerCase();
            return displayValue.includes(keyword);
        })
    ));
}

function resetMiniFilters(tableId = null) {
    if (tableId) {
        miniFilterState[tableId] = {};
        syncHeaderDecorations(tableId);
        return;
    }

    Object.keys(miniFilterState).forEach(key => {
        miniFilterState[key] = {};
        syncHeaderDecorations(key);
    });
}

function refreshRenderedTables({ resetScroll = true, redrawCharts = true } = {}) {
    currentDisplayedDf1 = applyMiniFiltersToRows('standard-table', currentFilteredDf1);
    currentDisplayedDf2 = applyMiniFiltersToRows('extended-table', currentFilteredDf2);

    updateScopeSwitcherCounts(currentDisplayedDf1.length, currentDisplayedDf2.length);
    updateDuplicateWarning(currentDisplayedDf1, currentDisplayedDf2);
    requestAnimationFrame(syncScopeSwitcherSlider);

    renderStandardData(currentDisplayedDf1);
    renderExtendedData(currentDisplayedDf2);

    if (resetScroll) {
        resetTableScrollPositions();
    }

    if (redrawCharts) {
        drawCharts(currentFilteredDf1, currentFilteredDf2);
    }
}

function updateScopeSwitcherCounts(df1Count, df2Count) {
    const counts = {
        'df1-panel': Number(df1Count || 0),
        'df2-panel': Number(df2Count || 0)
    };

    const df1CountEl = document.getElementById('df1-count-switcher');
    const df2CountEl = document.getElementById('df2-count-switcher');
    if (df1CountEl) df1CountEl.textContent = counts['df1-panel'].toLocaleString('vi-VN');
    if (df2CountEl) df2CountEl.textContent = counts['df2-panel'].toLocaleString('vi-VN');

    document.querySelectorAll('.scope-btn').forEach(button => {
        const view = button.getAttribute('data-view');
        const count = counts[view] || 0;
        button.classList.toggle('has-results', count > 0);
        button.classList.toggle('is-empty', count <= 0);
        button.dataset.count = String(count);
        button.setAttribute('aria-label', `${button.querySelector('.scope-text')?.textContent || ''}: ${count.toLocaleString('vi-VN')} kết quả`);
    });
}

function autoSwitchToAvailableResult() {
    const activeButton = document.querySelector('.scope-btn.active');
    const activeView = activeButton?.getAttribute('data-view') || 'df1-panel';
    const shouldFavorDf2 = currentDisplayedDf2.length >= Math.max(20, currentDisplayedDf1.length * 5);
    const shouldFavorDf1 = currentDisplayedDf1.length >= Math.max(20, currentDisplayedDf2.length * 5);

    if (activeView === 'df1-panel' && currentDisplayedDf1.length === 0 && currentDisplayedDf2.length > 0) {
        activateResultView('df2-panel', { animate: false });
    } else if (activeView === 'df2-panel' && currentDisplayedDf2.length === 0 && currentDisplayedDf1.length > 0) {
        activateResultView('df1-panel', { animate: false });
    } else if (activeView === 'df1-panel' && currentDisplayedDf1.length > 0 && shouldFavorDf2) {
        activateResultView('df2-panel', { animate: false });
    } else if (activeView === 'df2-panel' && currentDisplayedDf2.length > 0 && shouldFavorDf1) {
        activateResultView('df1-panel', { animate: false });
    }
}

function updateResults(df1, df2, options = {}) {
    currentFilteredDf1 = Array.isArray(df1) ? df1 : [];
    currentFilteredDf2 = Array.isArray(df2) ? df2 : [];

    if (options.resetMiniFilters) {
        closeColumnMenu();
        resetMiniFilters();
    }

    refreshRenderedTables({
        resetScroll: options.resetScroll !== false,
        redrawCharts: options.redrawCharts !== false
    });

    if (options.autoSwitchToResults !== false) {
        autoSwitchToAvailableResult();
    }
}

function updateDuplicateWarning(df1Rows, df2Rows) {
    const warningDiv = document.getElementById('duplicate-warning');
    if (!warningDiv) return;

    const duplicateCount = [...(df1Rows || []), ...(df2Rows || [])]
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
    document.querySelectorAll('#df1-panel .table-scroll, #df2-panel .table-scroll').forEach(container => {
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
        const searchForm = document.querySelector('custom-search-form');
        if (typeof searchForm?.activatePane === 'function') {
            searchForm.activatePane('drug', { focus: false });
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
    closeFloatingTableUi();
    ['history-modal', 'readme-modal', 'contact-modal'].forEach(id => {
        document.getElementById(id)?.classList.remove('show');
    });
}

function focusSearchFormPrimaryInput() {
    const searchForm = document.querySelector('custom-search-form');
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
    const searchForm = document.querySelector('custom-search-form');
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
        requestAnimationFrame(() => syncScopeSwitcherSlider());
    };

    const syncLandingView = (view) => {
        if (document.startViewTransition) {
            document.startViewTransition(() => applyLandingView(view));
            return;
        }
        applyLandingView(view);
    };

    const currentView = sessionStorage.getItem('bidfinder:view') || 'landing';
    const canOpenSavedApp =
        currentView === 'app' &&
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
        const mustLogin = Boolean(event.detail?.config?.require_auth_for_data_access);

        if (mustLogin && !authed) {
            applyLandingView('landing');
            return;
        }

        applyLandingView(savedView === 'app' ? 'app' : 'landing');
        if (savedView === 'app') {
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
            quantity: 'Số lượng',
            drugName: 'Tên thuốc',
            activeIngredient: 'Tên hoạt chất',
            strength: 'Nồng độ, hàm lượng',
            route: 'Đường dùng',
            dosageForm: 'Dạng bào chế',
            packaging: 'Quy cách',
            drugGroup: 'Nhóm thuốc',
            license: 'GĐKLH hoặc GPNK',
            manufacturer: 'Cơ sở sản xuất'
        },
        df2: {
            quantity: 'Khối lượng',
            drugName: 'Danh mục hàng hóa',
            lotName: 'Tên phần/lô',
            bidItem: 'Mặt hàng dự thầu',
            brand: 'Nhãn hiệu',
            model: 'Ký mã hiệu',
            technicalSpec: 'Tính năng kỹ thuật',
            manufacturer: 'Hãng sản xuất'
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

function shouldUseClientSideSort() {
    if (currentQueryMeta.searchMode === 'bulk') {
        return true;
    }
    const scope = currentQueryRequest?.scope || 'all';
    if (scope === 'all') {
        return !currentQueryMeta.df1HasMore && !currentQueryMeta.df2HasMore;
    }
    if (scope === 'medicine') {
        return !currentQueryMeta.df1HasMore;
    }
    if (scope === 'goods') {
        return !currentQueryMeta.df2HasMore;
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

    const leftParsed = parseLocalSortValue(leftRow?.[label], logicalKey);
    const rightParsed = parseLocalSortValue(rightRow?.[label], logicalKey);

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
    currentFilteredDf1 = activeSortRule
        ? sortRowsLocally(serverBaseDf1, 'df1', activeSortRule)
        : [...serverBaseDf1];
    currentFilteredDf2 = activeSortRule
        ? sortRowsLocally(serverBaseDf2, 'df2', activeSortRule)
        : [...serverBaseDf2];

    if (!preserveMiniFilters) {
        closeColumnMenu();
        resetMiniFilters();
    }

    refreshRenderedTables({
        resetScroll: true,
        redrawCharts: true
    });
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
    const preferredLeft = anchorRect.right - wrapperRect.left - floatingWidth;
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

    const miniFilters = miniFilterState[tableId] || {};
    const wrappedColumns = wrappedColumnsState[tableId] || new Set();
    const pinnedColumns = frozenColumnsState[tableId] || new Set();

    table.querySelectorAll('thead th[data-col-name]').forEach(th => {
        const columnName = th.dataset.colName;
        const sortState = getSortStateForColumn(tableId, columnName);
        const hasMiniFilter = Boolean(String(miniFilters[columnName] || '').trim());
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
    const hasData = (currentFilteredDf1?.length || 0) > 0 || (currentFilteredDf2?.length || 0) > 0;

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
            currentQueryMeta.searchMode === 'full' ? FULL_SEARCH_TOTAL_LIMIT : MAX_RESULTS_PER_TABLE,
            { searchMode: currentQueryMeta.searchMode }
        );
        if (result.success) {
            handleQuerySuccess(result, { resetMiniFilters: !preserveMiniFilters });
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

function setTableMiniFilter(tableId, columnName, rawValue) {
    const nextValue = String(rawValue || '');
    if (!miniFilterState[tableId]) {
        miniFilterState[tableId] = {};
    }

    if (nextValue.trim()) {
        miniFilterState[tableId][columnName] = nextValue;
    } else {
        delete miniFilterState[tableId][columnName];
    }

    syncHeaderDecorations(tableId);
    refreshRenderedTables({ resetScroll: false, redrawCharts: false });
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

function renderColumnMenu(tableId, columnName) {
    const miniFilterValue = miniFilterState[tableId]?.[columnName] || '';
    const sortState = getSortStateForColumn(tableId, columnName);
    const isWrapped = wrappedColumnsState[tableId]?.has(columnName);
    const isPinned = frozenColumnsState[tableId]?.has(columnName);
    const fragment = document.createDocumentFragment();

    const title = document.createElement('div');
    title.className = 'column-menu-title';
    title.textContent = columnName;
    fragment.appendChild(title);

    const primarySection = document.createElement('div');
    primarySection.className = 'column-menu-section';

    const field = document.createElement('div');
    field.className = 'column-menu-field';
    const inputWrap = document.createElement('div');
    inputWrap.className = 'column-menu-input-wrap';
    inputWrap.appendChild(createFeatherIconElement('search', 'column-menu-icon'));

    const input = document.createElement('input');
    input.className = 'column-mini-filter-input';
    input.type = 'text';
    input.value = miniFilterValue;
    input.dataset.tableId = tableId;
    input.dataset.columnName = encodeColumnName(columnName);
    input.placeholder = '';
    inputWrap.appendChild(input);
    field.appendChild(inputWrap);
    primarySection.appendChild(field);

    primarySection.appendChild(createColumnMenuActionButton({
        action: 'sort-asc',
        tableId,
        columnName,
        icon: 'arrow-up',
        label: 'Sort ascending',
        isActive: sortState === 'asc'
    }));
    primarySection.appendChild(createColumnMenuActionButton({
        action: 'sort-desc',
        tableId,
        columnName,
        icon: 'arrow-down',
        label: 'Sort descending',
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
        label: 'Autosize'
    }));
    secondarySection.appendChild(createColumnMenuActionButton({
        action: 'toggle-wrap',
        tableId,
        columnName,
        icon: 'corner-down-right',
        label: 'Wrap text',
        isActive: isWrapped
    }));
    secondarySection.appendChild(createColumnMenuActionButton({
        action: 'toggle-pin',
        tableId,
        columnName,
        icon: 'tag',
        label: 'Pin column',
        isActive: isPinned
    }));
    secondarySection.appendChild(createColumnMenuActionButton({
        action: 'hide-column',
        tableId,
        columnName,
        icon: 'eye-off',
        label: 'Hide column',
        isDanger: true
    }));
    fragment.appendChild(secondarySection);

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
    title.textContent = 'Show/hide columns';
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
        labelText.textContent = columnName;
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

    document.addEventListener('input', (e) => {
        const input = e.target.closest('.column-mini-filter-input');
        if (!input) return;

        setTableMiniFilter(
            input.dataset.tableId,
            decodeColumnName(input.dataset.columnName),
            input.value
        );
    });

    document.addEventListener('change', (e) => {
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
        .replace(/\btp\b/g, ' ')
        .replace(/\btinh\b/g, ' ')
        .replace(/\bthanh pho\b/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();

    key = PROVINCE_MAP_ALIASES.get(key) || key;
    return key;
}

function extractProvinceFromPlace(place) {
    const rawPlace = String(place || '').replace(/\s+/g, ' ').trim();
    if (!rawPlace) return 'Không xác định';

    const normalizedPlace = ` ${normalizeVietnameseText(rawPlace)} `;
    const matchedProvince = VIETNAM_PROVINCE_LOOKUP.find(province =>
        normalizedPlace.includes(` ${province.normalized} `)
    );
    if (matchedProvince) return matchedProvince.name;

    const lastSegment = rawPlace
        .split(',')
        .map(part => part.trim())
        .filter(Boolean)
        .pop();

    return lastSegment || rawPlace || 'Không xác định';
}

function getProvinceValueEntries(data) {
    const adminValueMap = new Map();

    data.forEach(r => {
        const province = extractProvinceFromPlace(r['Địa điểm']);
        const value = Number(r['Thành tiền (VND)']) || 0;
        if (value <= 0) return;

        const provinceKey = getProvinceMapKey(province);
        const adminUnit = ADMIN_2025_BY_LEGACY_KEY.get(provinceKey) || {
            key: provinceKey,
            name: province,
            parts: province
        };
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

        path.addEventListener('mouseenter', (event) => {
            svg.appendChild(path);
            path.classList.add('is-active');
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
        path.addEventListener('mousemove', (event) => {
            moveProvinceMapTooltip(container, tooltip, event);
        });
        path.addEventListener('mouseleave', () => {
            path.classList.remove('is-active');
            tooltip.classList.remove('visible');
        });
        path.addEventListener('focus', () => {
            svg.appendChild(path);
            path.classList.add('is-active');
        });
        path.addEventListener('blur', () => {
            path.classList.remove('is-active');
        });

        svg.appendChild(path);
    });

    container.appendChild(svg);
    container.appendChild(createProvinceMapLegend(maxValue));
    requestAnimationFrame(() => fitProvinceMapViewBox(svg));
}

const CHART_CONFIG = {
    histogram: {
        canvasId: 'chart-price-histogram',
        type: 'bar',
        color: CHART_THEME.primary,
        getData: (data) => {
            const priceMap = {};
            data.forEach(r => {
                const price = Number(r['Đơn giá trúng thầu (VND)']);
                if (!isNaN(price) && price > 0) {
                    priceMap[price] = (priceMap[price] || 0) + 1;
                }
            });

            const sorted = Object.entries(priceMap)
                .map(([price, count]) => ({ price: Number(price), count }))
                .sort((a, b) => a.price - b.price);

            return {
                labels: sorted.map(x => x.price.toLocaleString('vi-VN')),
                values: sorted.map(x => x.count)
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
                        title: (items) => `Giá: ${items[0].label}`,
                        label: (item) => `Số bản ghi: ${item.formattedValue}`
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { autoSkip: true, maxRotation: 45, minRotation: 45, font: { size: 12 }, color: CHART_THEME.axis }
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
                const dateStr = r['Ngày phê duyệt'];
                const value = Number(r['Thành tiền (VND)']) || 0;
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
        let dateObj;
        if (dateStr.includes('/')) {
            const parts = dateStr.split('/');
            if (parts.length === 3) {
                dateObj = new Date(parts[2], parts[1] - 1, parts[0]);
            }
        } else if (dateStr.includes('-')) {
            dateObj = new Date(dateStr);
        } else if (dateStr instanceof Date) {
            dateObj = dateStr;
        }
        
        if (dateObj && !isNaN(dateObj.getTime())) {
            return `${dateObj.getFullYear()}-${String(dateObj.getMonth() + 1).padStart(2, '0')}`;
        }
    } catch (e) {
        // Skip invalid dates
    }
    return null;
}

function initEmptyCharts() {
    Object.values(CHART_CONFIG).forEach(config => {
        const canvas = document.getElementById(config.canvasId);
        if (!canvas) return;
        
        const ctx = canvas.getContext('2d');
        if (ctx) {
            ctx.clearRect(0, 0, canvas.width || canvas.clientWidth || 300, canvas.height || canvas.clientHeight || 150);
        }
    });
    renderProvinceValueMap([]);
}

function destroyCharts() {
    Object.keys(chartInstances).forEach(key => {
        if (chartInstances[key]) {
            chartInstances[key].destroy();
            chartInstances[key] = null;
        }
    });
}

function drawCharts(df1Data, df2Data) {
    const totalRecords = (df1Data?.length || 0) + (df2Data?.length || 0);
    const noDataMsg = 'Chưa có dữ liệu. Vui lòng thực hiện tìm kiếm.';
    
    destroyCharts();
    
    if (totalRecords === 0) {
        showNoDataMessage('chart-province-map', noDataMsg);
        Object.values(CHART_CONFIG).forEach(config => {
            showNoDataMessage(config.canvasId, noDataMsg);
        });
        return;
    }
    
    const allData = [...df1Data, ...df2Data];
    renderProvinceValueMap(allData);
    
    // Draw each chart
    Object.entries(CHART_CONFIG).forEach(([key, config]) => {
        drawChart(key, config, allData);
    });
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
    
    if (!chartData.labels.length || !chartData.values.length) return;
    
    hideNoDataMessage(config.canvasId);
    
    const ctx = canvas.getContext('2d');
    const dataset = {
        label: key === 'histogram' ? 'Số lượng bản ghi' : 'Tổng trị giá (VND)',
        data: chartData.values,
        ...config.datasetConfig
    };
    
    // Apply colors
    if (config.type === 'bar' && key === 'histogram') {
        dataset.backgroundColor = config.color;
        dataset.borderRadius = 6;
    } else if (config.type === 'line') {
        dataset.borderColor = config.color;
        dataset.pointBackgroundColor = config.color;
    }
    
    chartInstances[key] = new Chart(ctx, {
        type: config.type,
        data: {
            labels: chartData.labels,
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

function formatDuration(seconds) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}m ${s.toString().padStart(2, '0')}s`;
}

function formatRelative(lastStr) {
    const diffMs = new Date() - new Date(lastStr);
    const diffMin = Math.round(diffMs / 60000);
    
    if (diffMin < 60) return `Cách đây ${diffMin} phút`;
    
    const diffH = Math.round(diffMin / 60);
    if (diffH < 24) return `Cách đây ${diffH} giờ`;
    
    return `Cách đây ${Math.round(diffH / 24)} ngày`;
}

function getHistorySortTimestamp(run) {
    const raw = run?.end_time || run?.start_time;
    const parsed = raw ? Date.parse(raw) : NaN;
    return Number.isFinite(parsed) ? parsed : 0;
}

function formatHistoryDateTime(value) {
    if (!value) return 'Chưa kết thúc';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return 'Chưa kết thúc';
    return parsed.toLocaleString('vi-VN');
}

function formatHistoryBoxes(value) {
    return Number(value || 0).toLocaleString('vi-VN');
}

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

    historyTimelineChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Số gói thầu được phê duyệt',
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
    const hasData = Array.isArray(metadata?.approval_timeline) && metadata.approval_timeline.length > 0;
    updateHistoryRangeButtons();
    
    if (hasData) {
        renderHistoryData(metadata.approval_timeline);
    } else {
        renderEmptyHistory();
    }
    
    modal.classList.add('show');
    feather.replace();
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

        const headerLine = selectedColumns.join('\t');
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
    'extended-table': 'ext-cell-value'
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
    
    ['#std-cell-bar', '#ext-cell-bar'].forEach(selector => {
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
    setBarText(tableId, Array.from(state.columns).join(' | '));
}

function syncWrappedColumns(tableId) {
    const table = document.getElementById(tableId);
    const wrappedColumns = wrappedColumnsState[tableId];
    if (!table || !wrappedColumns) return;

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
    ['standard-table', 'extended-table'].forEach(syncFrozenColumns);
}


// ============================== 
// INIT: DOMContentLoaded
// ============================== 
let df1 = [];
let df2 = [];
let resultPanelSwitchTimer = null;

const CONFIG = {
    tabs: {
        charts: 'charts-tab',
        data: 'data-tab'
    }
};

const tableSel = {
    "standard-table": { isDown: false, start: null, end: null, text: "", lastActive: 0 },
    "extended-table": { isDown: false, start: null, end: null, text: "", lastActive: 0 }
};

function initStorageAndElements() {
    restoreColumnOrderFromStorage();

    standardTbody = document.getElementById('standard-data');
    extendedTbody = document.getElementById('extended-data');

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
            renderHistoryTimelineChart(metadata?.approval_timeline || []);
        });
    });
}

const BULK_SEARCH_FIELD_LABELS = {
    medicine: {
        drugName: 'Tên thuốc',
        activeIngredient: 'Tên hoạt chất',
        concentration: 'Nồng độ, hàm lượng',
        route: 'Đường dùng',
        dosageForm: 'Dạng bào chế',
        drugGroup: 'Nhóm thuốc',
        unit: 'Đơn vị tính',
        regNo: 'GĐKLH hoặc GPNK',
        specification: 'Quy cách',
        manufacturer: 'Cơ sở sản xuất',
        country: 'Xuất xứ'
    },
    goods: {
        lotName: 'Tên phần/lô',
        goodsName: 'Danh mục hàng hóa',
        technicalSpec: 'Tính năng kỹ thuật',
        bidItem: 'Mặt hàng dự thầu',
        model: 'Ký mã hiệu',
        brand: 'Nhãn hiệu',
        country: 'Xuất xứ',
        manufacturer: 'Hãng sản xuất',
        unit: 'Đơn vị tính'
    }
};

const BULK_COLUMN_ALIASES = {
    medicine: {
        drugName: ['Tên thuốc', 'Tên thương mại', 'Tên hàng hóa', 'Tên mặt hàng', 'Thuốc'],
        activeIngredient: ['Tên hoạt chất', 'Hoạt chất'],
        concentration: ['Nồng độ, hàm lượng', 'Nồng độ hoặc hàm lượng', 'Nồng độ hàm lượng', 'Hàm lượng', 'Nồng độ'],
        route: ['Đường dùng'],
        dosageForm: ['Dạng bào chế'],
        drugGroup: ['Nhóm thuốc', 'Nhóm TCKT', 'Nhóm TCKT (nhóm thuốc)', 'Nhóm'],
        unit: ['Đơn vị tính', 'ĐVT', 'Đơn vị'],
        regNo: ['GĐKLH hoặc GPNK', 'GĐKLH/GPNK', 'Số đăng ký', 'SĐK', 'GPNK', 'Giấy đăng ký lưu hành'],
        specification: ['Quy cách', 'Quy cách đóng gói'],
        manufacturer: ['Cơ sở sản xuất', 'Nhà sản xuất', 'Hãng sản xuất', 'Đơn vị sản xuất'],
        country: ['Xuất xứ', 'Nước sản xuất', 'Quốc gia sản xuất', 'Quốc gia']
    },
    goods: {
        lotName: ['Tên phần/lô', 'Tên phần', 'Tên lô', 'Phần/lô', 'Tên gói'],
        goodsName: ['Danh mục hàng hóa', 'Tên hàng hóa', 'Tên hàng hoá', 'Hàng hóa', 'Hàng hoá', 'Tên mặt hàng'],
        technicalSpec: ['Tính năng kỹ thuật', 'Thông số kỹ thuật', 'Thông số kĩ thuật', 'Mô tả kỹ thuật', 'Mô tả kĩ thuật'],
        bidItem: ['Mặt hàng dự thầu', 'Tên mặt hàng dự thầu'],
        brand: ['Nhãn hiệu', 'Thương hiệu'],
        model: ['Ký mã hiệu', 'Kí mã hiệu', 'Model', 'Mã hiệu', 'Ký hiệu'],
        country: ['Xuất xứ', 'Nước sản xuất', 'Quốc gia sản xuất', 'Quốc gia'],
        manufacturer: ['Hãng sản xuất', 'Nhà sản xuất', 'Cơ sở sản xuất', 'Đơn vị sản xuất'],
        unit: ['Đơn vị tính', 'ĐVT', 'Đơn vị']
    }
};

let bulkImportedRows = [];
let bulkImportedColumns = [];
let bulkActiveScope = 'medicine';
let lastBulkSearchPayloads = null;
let lastBulkSearchWarnings = [];

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

function getBulkPriceLimit() {
    const selected = document.querySelector('input[name="bulk-price-limit"]:checked');
    const value = Number(selected?.value || 3);
    return [3, 5, 10].includes(value) ? value : 3;
}

function getSelectedBulkFields(scope) {
    return Array.from(document.querySelectorAll(`[data-bulk-fields="${scope}"] input[type="checkbox"]:checked`))
        .map(input => input.value)
        .filter(Boolean);
}

function getAllSelectedBulkScopes() {
    return getSelectedBulkFields(bulkActiveScope).length ? [bulkActiveScope] : [];
}

function setBulkActiveScope(scope) {
    if (!['medicine', 'goods'].includes(scope)) return;
    bulkActiveScope = scope;
    document.querySelectorAll('[data-bulk-fields]').forEach(panel => {
        const isActive = panel.dataset.bulkFields === scope;
        panel.classList.toggle('is-active', isActive);
        panel.setAttribute('aria-pressed', String(isActive));
    });
    setBulkSearchWarnings([]);
}

function findBulkColumnForField(scope, field, normalizedColumns) {
    const aliases = [BULK_SEARCH_FIELD_LABELS[scope]?.[field], ...(BULK_COLUMN_ALIASES[scope]?.[field] || [])]
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
    if (!status) return;
    status.textContent = message || '';
    status.classList.toggle('is-success', type === 'success');
    status.classList.toggle('is-error', type === 'error');
}

function openBulkSearchModal() {
    const modal = document.getElementById('bulk-search-modal');
    if (!modal) return;
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
    setBulkSearchStatus('');
    setBulkSearchWarnings([]);
    setBulkActiveScope(bulkActiveScope);
    requestAnimationFrame(() => document.getElementById('bulk-import-excel')?.focus());
    window.feather?.replace?.();
}

function closeBulkSearchModal() {
    const modal = document.getElementById('bulk-search-modal');
    if (!modal) return;
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
}

function updateBulkImportFileName(text) {
    const label = document.getElementById('bulk-import-file-name');
    if (label) label.textContent = text || 'Chưa chọn file';
}

async function handleBulkExcelFile(file) {
    if (!file) return;
    if (!window.XLSX) {
        setBulkSearchStatus('Không tải được thư viện đọc Excel. Vui lòng thử tải lại trang.', 'error');
        return;
    }

    setBulkSearchStatus('Đang đọc file Excel...');
    setBulkSearchWarnings([]);

    try {
        const buffer = await file.arrayBuffer();
        const workbook = window.XLSX.read(buffer, { type: 'array' });
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

        updateBulkImportFileName(`${file.name} (${bulkImportedRows.length} dòng)`);
        setBulkSearchStatus(`Đã import ${bulkImportedRows.length} dòng từ sheet "${firstSheetName}".`, 'success');
    } catch (error) {
        bulkImportedRows = [];
        bulkImportedColumns = [];
        updateBulkImportFileName('Chưa chọn file');
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
    const medicineResult = results.find(item => item.scope === 'medicine')?.result || {};
    const goodsResult = results.find(item => item.scope === 'goods')?.result || {};
    const medicineData = medicineResult.df1 || buildEmptyBulkScope();
    const goodsData = goodsResult.df2 || buildEmptyBulkScope();
    const displayedTotal = Number(medicineData.data?.length || 0) + Number(goodsData.data?.length || 0);
    const hasMore = Boolean(medicineData.has_more || goodsData.has_more);
    const totalCount = Number(medicineData.count || 0) + Number(goodsData.count || 0);
    const totalCountLabel = hasMore ? `${totalCount}+` : String(totalCount);
    const totalCountSummary = hasMore ? `hơn ${totalCount}` : String(totalCount);
    const appliedTotalLimit = results.reduce((sum, item) => sum + Number(item.result?.applied_total_limit || 0), 0)
        || (hasMore ? displayedTotal : totalCount);

    return {
        success: true,
        search_mode: 'bulk',
        bulk: {
            scope: results.length === 2 ? 'all' : (results[0]?.scope || 'all'),
            input_count: Math.max(...results.map(item => Number(item.result?.bulk?.input_count || 0)), 0),
            matched_count: displayedTotal,
            price_limit: getBulkPriceLimit(),
            search_mode: results.some(item => item.result?.bulk?.search_mode === 'full') ? 'full' : 'standard',
            result_limit: appliedTotalLimit,
            truncated: hasMore,
            fields: results.reduce((fields, item) => fields.concat(item.result?.bulk?.fields || []), [])
        },
        total_count: totalCount,
        total_count_exact: !hasMore,
        total_count_label: totalCountLabel,
        total_count_summary: totalCountSummary,
        applied_total_limit: appliedTotalLimit,
        applied_limit_per_scope: appliedTotalLimit,
        df1: medicineData,
        df2: goodsData,
        auth: goodsResult.auth || medicineResult.auth,
        full_search_daily_used: goodsResult.full_search_daily_used ?? medicineResult.full_search_daily_used,
        full_search_daily_remaining: goodsResult.full_search_daily_remaining ?? medicineResult.full_search_daily_remaining
    };
}

async function runBulkSearch(options = {}) {
    const searchMode = options.searchMode === 'full' ? 'full' : 'standard';
    const reuseLastPayloads = Boolean(options.reuseLastPayloads);
    await window.BIDFinderAuth?.whenReady?.();
    if (!requireAuthenticatedSession('login', 'full_query')) return;

    if (!reuseLastPayloads && !bulkImportedRows.length) {
        setBulkSearchStatus('Bạn import file Excel trước khi tra cứu.', 'error');
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
            setBulkSearchStatus('Bạn chọn ít nhất một trường tra cứu.', 'error');
            return;
        }

        payloads = selectedScopes
            .map(scope => {
                const mapped = buildBulkMappedRows(scope);
                mapped.missingFields.forEach(field => {
                    warnings.push(`Không tìm thấy cột "${BULK_SEARCH_FIELD_LABELS[scope]?.[field] || field}".`);
                });
                if (!mapped.fields.length) {
                    // warnings.push(`Nhóm ${scope === 'medicine' ? 'thuốc' : 'hàng hóa'} chưa có cột nào khớp để tra cứu.`);
                    return null;
                }
                if (!mapped.rows.length) {
                    // warnings.push(`Nhóm ${scope === 'medicine' ? 'thuốc' : 'hàng hóa'} không có dòng nào có dữ liệu ở các cột đã map.`);
                    return null;
                }
                return { scope, fields: mapped.fields, rows: mapped.rows };
            })
            .filter(Boolean);
    }

    setBulkSearchWarnings(warnings);
    if (!payloads.length) {
        setBulkSearchStatus('Chưa có dữ liệu hợp lệ để tra cứu.', 'error');
        return;
    }

    const runButton = document.getElementById('run-bulk-search');
    const defaultText = runButton?.textContent || 'Tra cứu hàng loạt';
    if (runButton) {
        runButton.disabled = true;
        runButton.textContent = searchMode === 'full' ? 'Đang full search...' : 'Đang tra cứu...';
    }
    const totalInputRows = payloads.reduce((sum, item) => sum + item.rows.length, 0);
    setBulkSearchStatus(`${searchMode === 'full' ? 'Đang full search' : 'Đang tra cứu'} ${totalInputRows} dòng...`);

    try {
        const results = [];
        const limit = searchMode === 'full' ? FULL_SEARCH_TOTAL_LIMIT : MAX_RESULTS_PER_TABLE;
        for (const payload of payloads) {
            const response = await getAuthorizedFetch()(`${API_BASE_URL}/api/bulk-query`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...payload,
                    priceLimit: getBulkPriceLimit(),
                    limit,
                    searchMode
                })
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok || result.success === false) {
                throw new Error(result.message || result.error || 'Tra cứu hàng loạt thất bại.');
            }
            results.push({ scope: payload.scope, result });
        }

        const result = combineBulkResults(results);
        if (result?.auth) {
            window.BIDFinderAuth?.applyAuthConfig?.(result.auth);
        }
        markDatabaseWarm();

        currentQueryRequest = { scope: result.bulk?.scope || 'all', filters: {} };
        clearFilterUrlState();
        lastBulkSearchPayloads = payloads;
        lastBulkSearchWarnings = warnings;
        handleQuerySuccess(result);
        setBulkSearchStatus(`Đã tìm thấy ${Number(result.total_count || 0).toLocaleString('vi-VN')} kết quả.`, 'success');
        if (!warnings.length && searchMode !== 'full') {
            closeBulkSearchModal();
        }
        window.BIDFinderAnalytics?.track?.('bulk_search_completed', {
            scope: result.bulk?.scope || 'all',
            search_mode: searchMode,
            input_count: totalInputRows,
            matched_count: Number(result.total_count || 0),
            price_limit: getBulkPriceLimit()
        });
    } catch (error) {
        console.error('Bulk search failed:', error);
        setBulkSearchStatus(error?.message || 'Không thể tra cứu hàng loạt lúc này.', 'error');
    } finally {
        if (runButton) {
            runButton.disabled = false;
            runButton.textContent = defaultText;
        }
    }
}

function initBulkSearchEvents() {
    document.getElementById('open-bulk-search-modal')?.addEventListener('click', openBulkSearchModal);
    document.getElementById('close-bulk-search-modal')?.addEventListener('click', closeBulkSearchModal);
    document.querySelector('#bulk-search-modal .bulk-search-overlay')?.addEventListener('click', closeBulkSearchModal);
    document.querySelectorAll('[data-bulk-fields]').forEach(panel => {
        panel.addEventListener('click', () => setBulkActiveScope(panel.dataset.bulkFields));
        panel.addEventListener('focusin', () => setBulkActiveScope(panel.dataset.bulkFields));
    });
    document.querySelectorAll('[data-bulk-fields] input[type="checkbox"]').forEach(input => {
        input.addEventListener('change', () => setBulkSearchWarnings([]));
    });
    document.getElementById('bulk-import-excel')?.addEventListener('click', () => {
        document.getElementById('bulk-excel-file')?.click();
    });
    document.getElementById('bulk-excel-file')?.addEventListener('change', event => {
        handleBulkExcelFile(event.target.files?.[0]);
    });
    document.getElementById('run-bulk-search')?.addEventListener('click', runBulkSearch);
    setBulkActiveScope(bulkActiveScope);
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

function openFeedbackModal() {
    const modal = document.getElementById('feedback-modal');
    const firstChoice = document.querySelector('#feedback-modal input[type="radio"]');
    if (!modal) return;

    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
    setFeedbackStatus('');
    requestAnimationFrame(() => firstChoice?.focus());
    window.feather?.replace?.();
    window.BIDFinderAnalytics?.track?.('feedback_opened');
}

function closeFeedbackModal() {
    const modal = document.getElementById('feedback-modal');
    if (!modal) return;

    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
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
    document.getElementById('copy-feedback')?.addEventListener('click', copyFeedbackText);
    document.getElementById('send-feedback')?.addEventListener('click', sendFeedback);

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && document.getElementById('feedback-modal')?.classList.contains('show')) {
            closeFeedbackModal();
        }
    });
}

function initTabSwitching() {
    const tabBtns = document.querySelectorAll('.primary-tab');
    const tabContents = document.querySelectorAll('.tab-content');
    const dataViewSwitcher = document.getElementById('data-view-switcher');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.id === 'open-run-history') return;
            
            // Update active states
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));
            
            btn.classList.add('active');
            const tabId = btn.getAttribute('data-tab');
            document.getElementById(tabId)?.classList.add('active');

            if (dataViewSwitcher) {
                dataViewSwitcher.style.display = tabId === CONFIG.tabs.data ? 'flex' : 'none';
            }

            syncPrimaryTabIndicator();
            requestAnimationFrame(syncScopeSwitcherSlider);

            if (tabId === CONFIG.tabs.charts) {
                drawCharts(currentFilteredDf1, currentFilteredDf2);
            }
        });
    });
}

function initResultViewSwitching() {
    const viewButtons = document.querySelectorAll('.scope-btn');

    viewButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetId = button.getAttribute('data-view');
            activateResultView(targetId, { animate: false });
        });
    });
}

function activateResultView(targetId, { animate = true } = {}) {
    if (!targetId) return;

    const viewButtons = document.querySelectorAll('.scope-btn');
    const resultPanels = document.querySelectorAll('.result-panel');
    const button = document.querySelector(`.scope-btn[data-view="${targetId}"]`);
    const activeButton = document.querySelector('.scope-btn.active');
    if (!button || activeButton === button) return;

    const currentPanel = document.querySelector('.result-panel.active');
    const targetPanel = document.getElementById(targetId);

    viewButtons.forEach(btn => {
        btn.classList.remove('active');
        btn.setAttribute('aria-selected', 'false');
    });

    button.classList.add('active');
    button.setAttribute('aria-selected', 'true');
    syncScopeSwitcherSlider();

    if (!targetPanel) return;
    if (!animate || !currentPanel || currentPanel === targetPanel) {
        resultPanels.forEach(panel => panel.classList.remove('active'));
        targetPanel.classList.add('active');
        return;
    }

    transitionResultPanels(currentPanel, targetPanel, resultPanels);
}

function transitionResultPanels(currentPanel, targetPanel, allPanels) {
    if (!currentPanel || !targetPanel || currentPanel === targetPanel) return;

    if (resultPanelSwitchTimer) {
        window.clearTimeout(resultPanelSwitchTimer);
        resultPanelSwitchTimer = null;
    }

    currentPanel.animate(
        [
            { opacity: 1, transform: 'translateY(0px)' },
            { opacity: 0, transform: 'translateY(6px)' }
        ],
        {
            duration: 150,
            easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
            fill: 'forwards'
        }
    );

    resultPanelSwitchTimer = window.setTimeout(() => {
        allPanels.forEach(panel => panel.classList.remove('active'));
        targetPanel.classList.add('active');

        targetPanel.animate(
            [
                { opacity: 0, transform: 'translateY(6px)' },
                { opacity: 1, transform: 'translateY(0px)' }
            ],
            {
                duration: 180,
                easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
                fill: 'both'
            }
        );
        resultPanelSwitchTimer = null;
    }, 120);
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

function syncPrimaryTabIndicator() {
    const switcher = document.querySelector('.primary-tab-switcher');
    if (!switcher) return;

    const indicator = switcher.querySelector('.primary-tab-indicator');
    const activeBtn = switcher.querySelector('.primary-tab.active');
    if (!indicator || !activeBtn) return;

    const switcherRect = switcher.getBoundingClientRect();
    const btnRect = activeBtn.getBoundingClientRect();

    indicator.style.width = `${btnRect.width}px`;
    indicator.style.transform = `translateX(${btnRect.left - switcherRect.left - 4}px)`;
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

function prepareExportData(data, headerOrder, currentOrder) {
    return reorderDataByColumns(data, headerOrder || currentOrder)
        .map(row => ({
            ...row,
            'Ngày phê duyệt': formatDateForExcel(row['Ngày phê duyệt']),
            'Ngày hết hiệu lực': formatDateForExcel(row['Ngày hết hiệu lực'])
        }));
}

function buildExportWorksheet(data, headerOrder, currentOrder) {
    const cleanHeaderOrder = (headerOrder || currentOrder || []).filter(col => col !== 'STT');
    const preparedData = prepareExportData(data, cleanHeaderOrder, currentOrder);
    const ws = XLSX.utils.json_to_sheet(preparedData, {
        header: cleanHeaderOrder,
        origin: 'A3'
    });

    XLSX.utils.sheet_add_aoa(ws, [
        ['Nguồn: BIDFinder – Hệ thống quản lý dữ liệu đấu thầu y tế']
    ], { origin: 'A1' });

    return ws;
}

function exportTableToExcel(tableId) {
    const tableData = getDisplayedData(tableId);
    if (!tableData.length) {
        alert('Không có dữ liệu để xuất!');
        return;
    }

    const sheetName = tableId === 'extended-table'
        ? 'Kết quả mua sắm hàng hóa'
        : 'Kết quả mua sắm thuốc';
    const filenameSuffix = tableId === 'extended-table' ? 'HangHoa' : 'Thuoc';
    const headerOrder = getVisibleColumnOrder(tableId);
    const wb = XLSX.utils.book_new();
    const ws = buildExportWorksheet(tableData, headerOrder, TABLE_MAP[tableId]?.columnOrder?.() || headerOrder);

    XLSX.utils.book_append_sheet(wb, ws, sheetName);

    const filename = generateExportFilename(filenameSuffix);
    XLSX.writeFile(wb, filename);
    window.BIDFinderAnalytics?.track?.('export_clicked', {
        table_id: tableId,
        row_count: tableData.length,
        visible_column_count: headerOrder.length
    });
    console.log(`✅ Exported ${tableData.length} records from ${tableId} to ${filename}`);
}

function initSearchFormEvents() {
    const searchForm = document.querySelector('custom-search-form');
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
            searchForm.setPreviewResult?.({
                total: Number(appliedResult?.total_count || 0),
                totalLabel: String(appliedResult?.total_count_label || Number(appliedResult?.total_count || 0).toLocaleString('vi-VN')),
                exact: appliedResult?.total_count_exact !== false
            });
        }

        const filterPanel = document.getElementById('filter-panel');
        const overlay = document.getElementById('panel-overlay');
        if (filterPanel) filterPanel.classList.remove('show');
        if (overlay) overlay.classList.remove('show');
    });
    
    searchForm.addEventListener('reset-filters', () => {
        currentQueryRequest = { scope: 'all', filters: {} };
        clearFilterUrlState();
        resetQueryResultMeta();
        updateResults([], [], { resetMiniFilters: true });
        hideLimitWarning();
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

            const result = await fetchQueryPreview(
                buildQueryRequest(e.detail),
                controller.signal
            );
            if (requestId !== previewRequestId) return;

            searchForm.setPreviewResult?.({
                total: Number(result?.total || 0),
                totalLabel: String(result?.display || Number(result?.total || 0).toLocaleString('vi-VN')),
                exact: Boolean(result?.exact)
            });
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
        const searchForm = document.querySelector('custom-search-form');

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



function disableDefaultTooltips() {
    document.querySelectorAll('.action-btn, .btn-meta-simple')
        .forEach(button => {
            button.removeAttribute('title');
            button.removeAttribute('data-title');
        });
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
        warmupDatabase().catch(error => {
            console.warn('Database warmup failed:', error);
        });
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
        initRowSelection(tableId);
        initColumnSelection(tableId);
    });
    initRangeCopy();
}

// Main initialization
document.addEventListener('DOMContentLoaded', function() {
    initStorageAndElements();
    initLandingShell();
    window.BIDFinderAuth?.init();
    initModalEvents();
    initBulkSearchEvents();
    initFeedbackModalEvents();
    initTabSwitching();
    initResultViewSwitching();
    initSearchFormEvents();
    initFilterUrlEvents();
    disableDefaultTooltips();
    initGlobalKeyboardShortcuts();
    initializeAppData();
    syncPrimaryTabIndicator();
    syncScopeSwitcherSlider();
});

window.addEventListener('load', function() {
    console.log('🚀 Window loaded, initializing drag & drop...');
    setTimeout(() => {
        initTableColumnDragDrop();
        initTableRangeSelection();
        syncAllFrozenColumns();
        syncPrimaryTabIndicator();
        syncScopeSwitcherSlider();
    }, 1000);
});

window.addEventListener('resize', () => {
    syncAllFrozenColumns();
    syncPrimaryTabIndicator();
    syncScopeSwitcherSlider();
    rerenderActiveColumnMenu();
    rerenderColumnsPopover();
});
