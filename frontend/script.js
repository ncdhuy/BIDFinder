const API_BASE_URL =
  (window.location.protocol === 'file:' ||
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1')
    ? 'http://127.0.0.1:8000'
    : 'https://bidfinder.onrender.com';

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

function getCurrentHeaderOrder(tableId) {
    const headers = document.getElementById(tableId)?.querySelectorAll('thead th');
    return headers ? Array.from(headers).map(h => h.textContent.trim()) : null;
}

// ========= 3. STORAGE
const DF1_COLUMNS_ORDER = [
    'Mã TBMT','Chủ đầu tư','Quyết định phê duyệt','Ngày phê duyệt','Ngày hết hiệu lực',
    'Đơn vị tính','Số lượng','Đơn giá trúng thầu (VND)','Thành tiền (VND)','Tên thuốc',
    'Tên hoạt chất','Nồng độ, hàm lượng','Đường dùng','Dạng bào chế','Quy cách',
    'Nhóm thuốc','GĐKLH hoặc GPNK','Cơ sở sản xuất','Xuất xứ','Nhà thầu trúng thầu',
    'Hình thức LCNT','Địa điểm','Tình trạng hiệu lực'
];

const DF2_COLUMNS_ORDER = [
    'Mã TBMT','Chủ đầu tư','Quyết định phê duyệt','Ngày phê duyệt','Ngày hết hiệu lực',
    'Đơn vị tính','Khối lượng','Đơn giá trúng thầu (VND)','Thành tiền (VND)','Tên hàng hóa',
    'Nhãn hiệu','Ký mã hiệu','Tính năng kỹ thuật','Xuất xứ','Hãng sản xuất',
    'Nhà thầu trúng thầu','Hình thức LCNT','Địa điểm','Tình trạng hiệu lực'
];

let currentColumnOrderDf1 = [...DF1_COLUMNS_ORDER];
let currentColumnOrderDf2 = [...DF2_COLUMNS_ORDER];

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

function renderTableData(data, configKey) {
    const config = TABLE_CONFIGS[configKey];
    const tbody = config.tbody();
    const columnOrder = config.columnOrder();
    
    tbody.innerHTML = '';
    resetCellSelection();

    if (!data?.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="${columnOrder.length}" class="table-empty-state">
                    Chưa có dữ liệu. Vui lòng thực hiện tìm kiếm.
                </td>
            </tr>
        `;
        return;
    }
    
    console.log(`📊 Rendering ${data.length} rows for ${configKey.toUpperCase()} with order:`, columnOrder);
    
    const fragment = document.createDocumentFragment();
    
    data.forEach((item, index) => {
        const tr = document.createElement('tr');
        tr.className = index % 2 === 0 ? 'bg-white' : 'bg-gray-50';
        
        columnOrder.forEach(colName => {
            const td = document.createElement('td');
            td.className = 'px-4 py-2';
            
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
function initColumnResize(tableId, storageKey) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const colgroup = ensureColGroup(table);
    const ths = Array.from(table.querySelectorAll("thead th"));

    ths.forEach((th, idx) => {
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
            
            // ✅ FIX BUG 2: Lấy index thực tế từ DOM, không dùng idx từ forEach
            const currentIndex = Array.from(th.parentElement.children).indexOf(th);
            
            colgroup.children[currentIndex].style.width = newW + "px";
            table.classList.add("user-resized");

            // ✅ FIX BUG 2: Lưu theo index thực tế
            const current = JSON.parse(localStorage.getItem(storageKey) || "{}");
            current[currentIndex] = newW;
            localStorage.setItem(storageKey, JSON.stringify(current));
        };

        const onUp = () => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.removeEventListener("touchmove", onMove);
            document.removeEventListener("touchend", onUp);
            table.classList.remove("resizing");
        };

        const onDown = (e) => {
            e.preventDefault();
            e.stopPropagation();

            startX = e.touches ? e.touches[0].clientX : e.clientX;
            startW = th.getBoundingClientRect().width;

            // ✅ FIX BUG 2: Lấy index thực tế
            const currentIndex = Array.from(th.parentElement.children).indexOf(th);
            
            if (!colgroup.children[currentIndex].style.width) {
                colgroup.children[currentIndex].style.width = startW + "px";
            }

            document.addEventListener("mousemove", onMove);
            document.addEventListener("mouseup", onUp);
            document.addEventListener("touchmove", onMove, { passive: false });
            document.addEventListener("touchend", onUp);
            table.classList.add("resizing");
        };

        handle.addEventListener("mousedown", onDown);
        handle.addEventListener("touchstart", onDown, { passive: false });
    });
}

function createResizeHandle(th, idx, colgroup, table, storageKey) {
    const handle = document.createElement("div");
    handle.className = "col-resizer";
    
    const MIN_COL_WIDTH = 60;
    let startX = 0;
    let startW = 0;

    const saveWidth = (newWidth) => {
        const current = JSON.parse(localStorage.getItem(storageKey) || "{}");
        current[idx] = newWidth;
        localStorage.setItem(storageKey, JSON.stringify(current));
    };

    const onMove = (e) => {
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const newW = Math.max(MIN_COL_WIDTH, startW + (clientX - startX));
        
        colgroup.children[idx].style.width = `${newW}px`;
        table.classList.add("user-resized");
        saveWidth(newW);
    };

    const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.removeEventListener("touchmove", onMove);
        document.removeEventListener("touchend", onUp);
        table.classList.remove("resizing");
    };

    const onDown = (e) => {
        e.preventDefault();
        e.stopPropagation();

        startX = e.touches ? e.touches[0].clientX : e.clientX;
        startW = th.getBoundingClientRect().width;

        if (!colgroup.children[idx].style.width) {
            colgroup.children[idx].style.width = `${startW}px`;
        }

        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
        document.addEventListener("touchmove", onMove, { passive: false });
        document.addEventListener("touchend", onUp);
        table.classList.add("resizing");
    };

    handle.addEventListener("mousedown", onDown);
    handle.addEventListener("touchstart", onDown, { passive: false });
    
    return handle;
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
    table: null
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
        currentData: () => currentFilteredDf1
    },
    'extended-table': {
        columnOrder: () => currentColumnOrderDf2,
        setColumnOrder: (order) => { currentColumnOrderDf2 = order; },
        storageKey: 'columnOrderDf2',
        defaultOrder: DF2_COLUMNS_ORDER,
        renderFn: renderExtendedData,
        currentData: () => currentFilteredDf2
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
    
    const headers = table.querySelectorAll('thead th');
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

const DRAG_HANDLERS = {
    dragstart: function(e) {
        dragState.columnIndex = parseInt(this.dataset.columnIndex);
        dragState.table = this.closest('table');
        
        console.log(`🎬 Drag start: column ${dragState.columnIndex}`);
        
        this.style.opacity = '0.4';
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/html', this.innerHTML);
        
        dragState.table.classList.add('column-dragging');
    },
    
    dragover: function(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        return false;
    },
    
    dragenter: function() {
        if (this.closest('table') === dragState.table && 
            parseInt(this.dataset.columnIndex) !== dragState.columnIndex) {
            this.classList.add('drag-over');
        }
    },
    
    dragleave: function() {
        this.classList.remove('drag-over');
    },
    
    drop: function(e) {
        e.stopPropagation();
        
        const dropIndex = parseInt(this.dataset.columnIndex);
        console.log(`📍 Drop: from ${dragState.columnIndex} to ${dropIndex}`);
        
        if (this.closest('table') === dragState.table && 
            dragState.columnIndex !== dropIndex) {
            reorderTableColumns(dragState.table, dragState.columnIndex, dropIndex);
        }
        
        return false;
    },
    
    dragend: function() {
        this.style.opacity = '1';
        console.log('🏁 Drag end');
        
        if (dragState.table) {
            dragState.table.querySelectorAll('thead th').forEach(h => {
                h.classList.remove('drag-over');
            });
            dragState.table.classList.remove('column-dragging');
        }
        
        dragState = { columnIndex: null, table: null };
    }
};

// ==== 3.2. REORDER & UPDATE
let currentFilteredDf1 = [];
let currentFilteredDf2 = [];

function updateColumnOrder(table) {
    const config = TABLE_MAP[table.id];
    if (!config) return;
    
    const headers = table.querySelectorAll('thead th');
    const newOrder = Array.from(headers).map(h => h.textContent.trim());
    
    if (newOrder.length === config.defaultOrder.length) {
        config.setColumnOrder(newOrder);
        localStorage.setItem(config.storageKey, JSON.stringify(newOrder));
        console.log(`✅ Cập nhật thứ tự cột ${table.id}:`, newOrder);
    } else {
        console.error(`❌ ${table.id}: Số lượng cột không khớp, không lưu localStorage`);
    }
}

function reorderTableColumns(table, fromIndex, toIndex) {
    console.log(`🔄 Reordering columns: ${fromIndex} → ${toIndex}`);
    
    const theadRow = table.querySelector('thead tr');
    if (!theadRow) return;
    
    const headers = Array.from(theadRow.children);
    if (fromIndex >= headers.length || toIndex >= headers.length) return;
    
    const draggedHeader = headers[fromIndex];
    draggedHeader.remove();
    
    if (toIndex >= theadRow.children.length) {
        theadRow.appendChild(draggedHeader);
    } else {
        theadRow.insertBefore(draggedHeader, theadRow.children[toIndex]);
    }
    
    // Update column indices
    theadRow.querySelectorAll('th').forEach((h, idx) => {
        h.dataset.columnIndex = idx;
    });
    
    updateColumnOrder(table);
    
    // Re-render with new order
    const config = TABLE_MAP[table.id];
    if (config) {
        console.log(`🔄 Re-rendering ${table.id} with new order`);
        config.renderFn(config.currentData());
    }
}

function syncHeadersWithLocalStorage() {
    console.log('🔄 Syncing headers with localStorage...');
    
    Object.entries(TABLE_MAP).forEach(([tableId, config]) => {
        const table = document.getElementById(tableId);
        if (!table) return;
        
        const thead = table.querySelector('thead tr');
        if (!thead) return;
        
        thead.innerHTML = '';
        const columnOrder = config.columnOrder();
        
        columnOrder.forEach((colName, index) => {
            const th = createHeaderCell(colName, index);
            thead.appendChild(th);
        });
        
        console.log(`✅ ${tableId} header synced:`, columnOrder);
    });
}

function createHeaderCell(colName, index) {
    const th = document.createElement('th');
    th.className = 'px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider bg-gray-100';
    th.textContent = colName;
    th.setAttribute('draggable', 'true');
    th.dataset.columnIndex = index;
    th.style.cursor = 'move';
    
    const dragIndicator = document.createElement('span');
    dragIndicator.className = 'drag-indicator';
    th.insertBefore(dragIndicator, th.firstChild);
    
    return th;
}


// ============================== 
// FILTERS
// ============================== 

const MAX_RESULTS_PER_TABLE = 200;
let currentQueryRequest = {
    scope: 'all',
    filters: {}
};


// ======== 1. APPLY
function buildQueryRequest(baseRequest = {}, overrides = {}) {
    const safeBase = baseRequest && typeof baseRequest === 'object' ? baseRequest : {};

    return {
        scope: safeBase.scope || 'all',
        filters: safeBase.filters && typeof safeBase.filters === 'object' ? { ...safeBase.filters } : {},
        ...overrides
    };
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

async function fetchQueryResults(queryRequest, customSortRules = sortRules, limit = MAX_RESULTS_PER_TABLE) {
    const requestBody = {
        scope: queryRequest?.scope || 'all',
        filters: queryRequest?.filters || {},
        sort: Array.isArray(customSortRules) && customSortRules.length > 0 ? customSortRules : null,
        limit
    };

    const response = await fetch(`${API_BASE_URL}/api/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody)
    });

    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }

    return response.json();
}

function normalizeQueryResult(result) {
    return {
        df1: result?.df1 || { data: [], count: 0, displayed: 0 },
        df2: result?.df2 || { data: [], count: 0, displayed: 0 }
    };
}

function handleQuerySuccess(result) {
    const normalized = normalizeQueryResult(result);

    currentFilteredDf1 = normalized.df1.data || [];
    currentFilteredDf2 = normalized.df2.data || [];

    const totalCount = Number(normalized.df1.count || 0) + Number(normalized.df2.count || 0);
    const displayedCount = currentFilteredDf1.length + currentFilteredDf2.length;

    if (totalCount > displayedCount) {
        showLimitWarning(totalCount, displayedCount);
    } else {
        hideLimitWarning();
    }

    updateResults(currentFilteredDf1, currentFilteredDf2);
}


async function applyFilters(payload) {
    currentQueryRequest = buildQueryRequest(payload);

    console.log('Applying filters with query request:', currentQueryRequest);

    try {
        const result = await fetchQueryResults(currentQueryRequest, sortRules, MAX_RESULTS_PER_TABLE);

        if (result.success) {
        handleQuerySuccess(result);
        } else {
        throw new Error(result.error || 'Query failed');
        }
    } catch (err) {
        console.error('Filter failed:', err);
        currentFilteredDf1 = [];
        currentFilteredDf2 = [];
        updateResults([], []);
        hideLimitWarning();
    }
}


// Helper: Show limit warning
function showLimitWarning(totalCount, displayedCount) {
    alert(
        `⚠️ GIỚI HẠN KẾT QUẢ TÌM KIẾM\n\n` +
        `Hệ thống ghi nhận ${totalCount.toLocaleString('vi-VN')} bản ghi phù hợp.\n` +
        `Hiện tại chỉ ${displayedCount.toLocaleString('vi-VN')} kết quả đầu tiên được hiển thị.\n\n` +
        `Để truy xuất đầy đủ, đề nghị:\n` +
        `- Bổ sung từ khóa tìm kiếm\n` +
        `- Thu hẹp khoảng thời gian\n`
    );

    const warningDiv = document.getElementById('result-warning');
    if (warningDiv) warningDiv.style.display = 'block';
}

// Helper: Hide limit warning
function hideLimitWarning() {
    const warningDiv = document.getElementById('result-warning');
    if (warningDiv) warningDiv.style.display = 'none';
}

// Helper: Update results and render
function updateResults(df1, df2) {
    currentFilteredDf1 = df1;
    currentFilteredDf2 = df2;

    document.getElementById('df1-count-switcher').textContent = df1.length;
    document.getElementById('df2-count-switcher').textContent = df2.length;

    renderStandardData(df1);
    renderExtendedData(df2);
    drawCharts(df1, df2);
}

// ======== 2. PANELS
const PANEL_CONFIG = {
    filter: {
        panel: 'filter-panel',
        openBtn: 'open-filter-panel',
        closeBtn: 'close-filter-panel',
        onOpen: null
    },
    sort: {
        panel: 'sort-panel',
        openBtn: 'open-sort-panel',
        closeBtn: 'close-sort-panel',
        onOpen: () => {
            initSortRuleMoveButtons();
            renderSortRules();
            updateSortButtonsState();
        }
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
        panels.forEach(({ panel }) => panel.classList.remove('show'));
        overlay.classList.remove('show');
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
            panel.classList.add('show');
            overlay.classList.add('show');
            config.onOpen?.();
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            panel.classList.remove('show');
            overlay.classList.remove('show');
        });
    }

    return { panel, openBtn, closeBtn };
}

function initFilterHelpExternalTooltip() {
    const helpBtn = document.getElementById("filter-help-btn");
    const contentEl = document.getElementById("filter-help-tooltip-content");
    if (!helpBtn || !contentEl) return;

    let externalTooltip = null;

    injectTooltipStyles();

    const showTooltip = () => {
        if (externalTooltip) return;

        externalTooltip = createTooltip(helpBtn, contentEl.innerHTML);
        document.body.appendChild(externalTooltip);
    };

    const hideTooltip = () => {
        if (externalTooltip) {
            externalTooltip.remove();
            externalTooltip = null;
        }
    };

    helpBtn.addEventListener("mouseenter", showTooltip);
    helpBtn.addEventListener("mouseleave", hideTooltip);
}

function injectTooltipStyles() {
    const styleId = "external-tooltip-style-filter-help";
    if (document.getElementById(styleId)) return;

    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = `
        .external-tooltip {
            position: absolute;
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

function createTooltip(targetElement, content) {
    const tooltip = document.createElement("div");
    tooltip.className = "external-tooltip";
    tooltip.innerHTML = content;

    const rect = targetElement.getBoundingClientRect();
    tooltip.style.top = `${rect.bottom + 8}px`;
    tooltip.style.left = `${rect.left + rect.width / 2 - 210}px`;

    return tooltip;
}

// ============================== 
// SORT
// ============================== 
let sortRules = [];

// ======== 1. RULES
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
        { key: 'origin', label: 'Xuất xứ' },
        { key: 'winner', label: 'Nhà thầu trúng thầu' },
        { key: 'place', label: 'Địa điểm' },
        { key: 'validity', label: 'Tình trạng hiệu lực' }
    ],
    // chỉ map những key thực sự khác nhau giữa df1 và df2
    physical: {
        df1: {
        quantity: 'Số lượng',
        drugName: 'Tên thuốc'
        },
        df2: {
        quantity: 'Khối lượng',
        drugName: 'Tên hàng hóa'
        }
    }
};

const SORT_TEMPLATES = {
    empty: `
        <div class="sort-rules-empty">
            <div style="font-size: 48px; margin-bottom: 12px;">📋</div>
            <p>Chưa có quy tắc sắp xếp nào</p>
            <p style="font-size: 13px; margin-top: 8px; opacity: 0.7;">
                Nhấn "+ Thêm cột" để bắt đầu
            </p>
        </div>
    `,

    // logicalColumns: SORTABLE_COLUMNS.logical
    rule: (rule, index, logicalColumns) => `
        <div class="sort-rule-item" data-index="${index}">
            <span class="sort-rule-number">${index + 1}</span>
            
            <div class="sort-move">
                <button class="btn-move-up" data-index="${index}" type="button" title="Lên">▲</button>
                <button class="btn-move-down" data-index="${index}" type="button" title="Xuống">▼</button>
            </div>
            
            <div class="sort-rule-column">
                <select data-index="${index}" data-field="column">
                    ${logicalColumns.map(col => 
                        `<option value="${col.key}" ${rule.column === col.key ? 'selected' : ''}>${col.label}</option>`
                    ).join('')}
                </select>
            </div>
            
            <div class="sort-rule-order">
                <select data-index="${index}" data-field="order">
                <option value="asc" ${rule.order === 'asc' ? 'selected' : ''}>Tăng dần</option>
                <option value="desc" ${rule.order === 'desc' ? 'selected' : ''}>Giảm dần</option>
                </select>
            </div>
            
            <button class="btn-remove-rule" data-index="${index}" type="button" title="Xóa">✕</button>
        </div>
    `
};

function addSortRule() {
    const firstKey = SORTABLE_COLUMNS.logical[0]?.key || 'ma_tbmt';
    sortRules.push({
        column: firstKey,
        order: 'asc'
    });

    renderSortRules();
    updateSortButtonsState();
}

function moveSortRule(fromIndex, toIndex) {
    if (toIndex < 0 || toIndex >= sortRules.length) return;
    const [item] = sortRules.splice(fromIndex, 1);
    sortRules.splice(toIndex, 0, item);
    renderSortRules();
}

function updateSortButtonsState() {
    const applyBtn = document.getElementById('apply-sort');
    const resetBtn = document.getElementById('reset-sort');
    if (!applyBtn || !resetBtn) return;

    const hasRules = sortRules.length > 0;
    applyBtn.disabled = !hasRules;
    resetBtn.disabled = !hasRules;
}

function renderSortRules() {
    const container = document.getElementById('sort-rules-list');
    if (!container) return;

    if (sortRules.length === 0) {
        container.innerHTML = SORT_TEMPLATES.empty;
        updateSortButtonsState();
        return;
    }

    const logicalColumns = SORTABLE_COLUMNS.logical;

    container.innerHTML = sortRules
        .map((rule, index) => SORT_TEMPLATES.rule(rule, index, logicalColumns))
        .join('');

    attachSortRuleEventHandlers(container);
    updateMoveButtonsState(container);
    updateSortButtonsState();
}

function attachSortRuleEventHandlers(container) {
    // Handle select changes
    container.querySelectorAll('select').forEach(select => {
        select.addEventListener('change', (e) => {
            const idx = parseInt(e.target.dataset.index, 10);
            const field = e.target.dataset.field;
            if (sortRules[idx]) {
                sortRules[idx][field] = e.target.value;
            }
        });
    });

    // Handle remove buttons
    container.querySelectorAll('.btn-remove-rule').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const idx = parseInt(e.currentTarget.dataset.index, 10);
            if (!Number.isNaN(idx)) {
                sortRules.splice(idx, 1);
                if (sortRules.length === 0) {
                    await resetSortToDefault();
                } else {
                    renderSortRules();
                }
            }
        });
    });
}

function updateMoveButtonsState(container) {
    container.querySelectorAll('.sort-rule-item').forEach(item => {
        const idx = parseInt(item.dataset.index, 10);
        const upBtn = item.querySelector('.btn-move-up');
        const downBtn = item.querySelector('.btn-move-down');
        
        if (upBtn) upBtn.disabled = (idx === 0);
        if (downBtn) downBtn.disabled = (idx === sortRules.length - 1);
    });
}

function initSortRuleMoveButtons() {
    const container = document.getElementById('sort-rules-list');
    if (!container || container.dataset.moveBound === '1') return;

    container.dataset.moveBound = '1';

    container.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-move-up, .btn-move-down');
        if (!btn) return;

        const idx = parseInt(btn.dataset.index, 10);
        if (Number.isNaN(idx)) return;

        const isUp = btn.classList.contains('btn-move-up');
        const targetIdx = isUp ? idx - 1 : idx + 1;

        if ((isUp && idx > 0) || (!isUp && idx < sortRules.length - 1)) {
            moveSortRule(idx, targetIdx);
        }
    });
}

async function applySortRules() {
    if (sortRules.length === 0) {
        console.log('No sort rules to apply');
        return;
    }

    const hasFilter = hasActiveQueryFilters(currentQueryRequest);
    const hasData = (currentFilteredDf1?.length || 0) > 0 || (currentFilteredDf2?.length || 0) > 0;

    if (!hasFilter && !hasData) {
        console.log('No data to sort or no filters applied - keep empty state');
        ['sort-panel', 'panel-overlay'].forEach(id => document.getElementById(id)?.classList.remove('show'));
        return;
    }

    console.log('Applying sort rules with query request:', currentQueryRequest, sortRules);

    try {
        const result = await fetchQueryResults(currentQueryRequest, sortRules, MAX_RESULTS_PER_TABLE);

        if (result.success) {
        handleQuerySuccess(result);
        ['sort-panel', 'panel-overlay'].forEach(id => document.getElementById(id)?.classList.remove('show'));
        console.log('Server sort applied:', sortRules);
        } else {
        throw new Error(result.error || 'Sort failed');
        }
    } catch (err) {
        console.error('Server sort failed:', err);
    }
}


function initSortPanel() {
  const sortEvents = {
    'add-sort-rule': addSortRule,
    'apply-sort': applySortRules,
    'reset-sort': resetSortToDefault    // dùng hàm chung
  };

  Object.entries(sortEvents).forEach(([id, handler]) => {
    document.getElementById(id)?.addEventListener('click', handler);
  });
}

async function resetSortToDefault() {
    sortRules = [];
    renderSortRules();
    updateSortButtonsState();

    console.log('Reset sort to server default');

    ['sort-panel', 'panel-overlay'].forEach(id => document.getElementById(id)?.classList.remove('show'));

    const hasFilter = hasActiveQueryFilters(currentQueryRequest);
    const hasData = (currentFilteredDf1?.length || 0) > 0 || (currentFilteredDf2?.length || 0) > 0;

    if (!hasFilter && !hasData) {
        console.log('No filters or data - skip re-fetch on sort reset');
        return;
    }

    try {
        const result = await fetchQueryResults(currentQueryRequest, [], MAX_RESULTS_PER_TABLE);

        if (result.success) {
        handleQuerySuccess(result);
        console.log('Sort reset to server default ORDER BY');
        } else {
        throw new Error(result.error || 'Reset sort failed');
        }
    } catch (err) {
        console.error('Reset sort failed:', err);
    }
}



// ============================== 
// CHARTS
// ============================== 

// ======== 1. CHART INSTANCES
const chartInstances = {
    histogram: null,
    boxplot: null,
    timeline: null,
    method: null
};

const CHART_THEME = {
    primary: '#127495',
    primaryDark: '#0f5b77',
    primarySoft: 'rgba(18, 116, 149, 0.18)',
    accent: '#1b866e',
    accentDark: '#146653',
    accentSoft: 'rgba(27, 134, 110, 0.14)',
    axis: '#5d7280',
    axisStrong: '#1f3448',
    grid: '#dde7ec',
    border: '#d1dde4',
    surface: '#ffffff',
    methodColors: ['#127495', '#1b866e', '#5caac3', '#72b9a7', '#315e79', '#2c7665', '#9fd0dd', '#acd7cb']
};

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
    
    boxplot: {
        canvasId: 'chart-price-boxplot',
        type: 'boxplot',
        color: CHART_THEME.primaryDark,
        getData: (data) => {
            const prices = data
                .map(r => Number(r['Đơn giá trúng thầu (VND)']))
                .filter(p => !isNaN(p) && p > 0);
            
            return {
                labels: ['Giá'],
                values: [prices]
            };
        },
        getOptions: () => ({
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'nearest', axis: 'xy', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: true,
                    mode: 'nearest',
                    intersect: false,
                    axis: 'xy',
                    hitRadius: 30,
                    backgroundColor: CHART_THEME.surface,
                    titleColor: CHART_THEME.axisStrong,
                    bodyColor: CHART_THEME.axis,
                    borderColor: CHART_THEME.border,
                    borderWidth: 1,
                    padding: 10,
                    displayColors: false,
                    callbacks: {
                        label: (context) => {
                            const v = context.parsed;
                            if (v.min !== undefined) {
                                return [
                                    `Max: ${v.max.toLocaleString('vi-VN')}`,
                                    `Q3: ${v.q3.toLocaleString('vi-VN')}`,
                                    `Median: ${v.median.toLocaleString('vi-VN')}`,
                                    `Q1: ${v.q1.toLocaleString('vi-VN')}`,
                                    `Min: ${v.min.toLocaleString('vi-VN')}`
                                ];
                            }
                            return `${v.toLocaleString('vi-VN')}`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: CHART_THEME.grid },
                    ticks: {
                        callback: (value) => formatCurrencyAxis(value),
                        font: { size: 12 },
                        color: CHART_THEME.axis
                    }
                },
                x: {
                    grid: { display: false },
                    ticks: { font: { size: 12 }, color: CHART_THEME.axis }
                }
            },
            layout: { padding: { top: 10, bottom: 10 } }
        }),
        datasetConfig: {
            backgroundColor: CHART_THEME.primarySoft,
            borderColor: CHART_THEME.primary,
            borderWidth: 2,
            outlierBackgroundColor: CHART_THEME.accentDark,
            outlierBorderColor: CHART_THEME.accentDark,
            itemRadius: 0,
            outlierRadius: 3,
            medianColor: CHART_THEME.accent
        }
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
    },
    
    method: {
        canvasId: 'chart-selection-method',
        type: 'bar',
        colors: CHART_THEME.methodColors,
        getData: (data) => {
            const methodMap = {};
            
            data.forEach(r => {
                const method = r['Hình thức LCNT'] || 'Không xác định';
                const value = Number(r['Thành tiền (VND)']) || 0;
                if (value > 0) {
                    methodMap[method] = (methodMap[method] || 0) + value;
                }
            });
            
            const sorted = Object.entries(methodMap)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 8);
            
            return {
                labels: sorted.map(x => x[0].length > 25 ? x[0].substring(0, 25) + '...' : x[0]),
                values: sorted.map(x => x[1])
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
                    ticks: { autoSkip: false, maxRotation: 45, minRotation: 45, font: { size: 11 }, color: CHART_THEME.axis }
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
            borderRadius: 8,
            borderWidth: 0
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
        Object.values(CHART_CONFIG).forEach(config => {
            showNoDataMessage(config.canvasId, noDataMsg);
        });
        return;
    }
    
    const allData = [...df1Data, ...df2Data];
    
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
        label: config.type === 'boxplot' ? 'Phân bố giá' : 
               config.type === 'line' ? 'Tổng trị giá (VND)' : 
               'Số lượng bản ghi',
        data: chartData.values,
        ...config.datasetConfig
    };
    
    // Apply colors
    if (config.type === 'bar' && key === 'histogram') {
        dataset.backgroundColor = config.color;
        dataset.borderRadius = 6;
    } else if (config.type === 'bar' && key === 'method') {
        dataset.backgroundColor = config.colors;
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
        options: config.getOptions()
    });
}

// ======== 2. METADATA
let metadata = null;

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

async function loadMetadata() {
    try {
        console.log('🔄 Đang tải metadata...');
        const res = await fetch(`${API_BASE_URL}/api/metadata`);
        const meta = await res.json();
        
        console.log('📦 Response từ API:', meta);
        
        if (meta.success) {
            metadata = meta;
            console.log('✅ Load metadata thành công:', metadata);
        } else {
            console.warn('⚠️ API trả về success=false:', meta.message);
        }
    } catch (e) {
        console.error('❌ Load metadata error:', e);
    }
}

function showHistoryModal() {
    const modal = document.getElementById('history-modal');
    const hasData = metadata?.success && metadata?.history?.length > 0;
    
    if (hasData) {
        renderHistoryData(metadata.history);
    } else {
        renderEmptyHistory();
    }
    
    modal.classList.add('show');
    feather.replace();
}

function renderHistoryData(history) {
    const sortedHistory = [...history]
        .sort((a, b) => new Date(b.end_time) - new Date(a.end_time));
    const latestRun = sortedHistory[0];
    const historyHTML = sortedHistory
        .map(run => `
            <div class="history-item">
                <div>
                    <div class="history-datetime">
                        ${new Date(run.end_time).toLocaleString('vi-VN')}
                    </div>
                </div>
                <div class="history-boxes">
                    ${run.boxes_selected.toLocaleString()}
                </div>
            </div>
        `)
        .join('');

    document.getElementById('modal-last-update').textContent = new Date(latestRun.end_time).toLocaleString('vi-VN');
    document.getElementById('modal-freshness').textContent = formatRelative(latestRun.end_time);
    document.getElementById('modal-boxes-total').textContent = latestRun.boxes_selected.toLocaleString();
    
    document.getElementById('history-list').innerHTML = historyHTML;
}

function renderEmptyHistory() {
    document.getElementById('modal-last-update').textContent = 'Chưa có dữ liệu';
    document.getElementById('modal-freshness').textContent = '--';
    document.getElementById('modal-boxes-total').textContent = '0';
    document.getElementById('history-list').innerHTML = `
        <div class="history-empty">
            <i data-feather="clock"></i>
            <p>Chưa có lịch sử cập nhật dữ liệu</p>
        </div>
    `;
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
    table.querySelectorAll("td.cell-range, td.cell-active").forEach(td=>{
        td.classList.remove("cell-range","cell-active");
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

    const rows = table.tBodies[0]?.rows || [];
    for (let r=r1; r<=r2; r++){
        const cells = rows[r]?.cells || [];
        for (let c=c1; c<=c2; c++){
        const td = cells[c];
        if (td) td.classList.add("cell-range");
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
    setBarText(tableId, getTopLeftCellText(tableId));
}

function initTableRangeSelect(tableId){
    const table = document.getElementById(tableId);
    if (!table) return;

    // Ngăn browser bôi đen text khi drag
    table.addEventListener("selectstart", (e) => e.preventDefault());

    table.addEventListener("mousedown", (e) => {
        const td = e.target.closest("td");
        if (!td) return;

        // chỉ xử lý click trái
        if (e.button !== 0) return;

        const st = tableSel[tableId];
        st.isDown = true;

        // Shift+click: mở rộng từ start cũ; không có start thì set mới
        if (!e.shiftKey || !st.start) {
        st.start = getCellPos(td);
        }
        st.end = getCellPos(td);

        applyRange(tableId);
        window.getSelection?.().removeAllRanges();
        e.preventDefault();
    });

    table.addEventListener("mouseover", (e) => {
        const st = tableSel[tableId];
        if (!st.isDown) return;

        const td = e.target.closest("td");
        if (!td) return;

        st.end = getCellPos(td);
        applyRange(tableId);
        e.preventDefault();
    });

    document.addEventListener("mouseup", () => {
        tableSel[tableId].isDown = false;
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
        
        const text = tableSel[activeTable].text;
        if (!text) return;

        e.clipboardData.setData("text/plain", text);
        e.preventDefault();
    });
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
    document.querySelectorAll('.cell-selected, .cell-range')
        .forEach(el => el.classList.remove('cell-selected', 'cell-range'));
    
    ['#std-cell-bar', '#ext-cell-bar'].forEach(selector => {
        const bar = document.querySelector(selector);
        if (!bar) return;
        
        const label = bar.querySelector('.cell-display-label');
        const value = bar.querySelector('.cell-display-value');
        
        if (label) label.textContent = '';
        if (value) value.textContent = '';
    });
}


// ============================== 
// INIT: DOMContentLoaded
// ============================== 
let df1 = [];
let df2 = [];
let resultPanelSwitchTimer = null;

const CONFIG = {
    tables: {
        standard: { id: 'standard-table', storageKey: 'colWidthDf1' },
        extended: { id: 'extended-table', storageKey: 'colWidthDf2' }
    },
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

    Object.values(CONFIG.tables).forEach(table => {
        initColumnResize(table.id, table.storageKey);
    });

    initPanels();
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
}

function initTabSwitching() {
    const tabBtns = document.querySelectorAll('.primary-tab');
    const tabContents = document.querySelectorAll('.tab-content');
    const exportBtn = document.getElementById('export-excel-btn');
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
                dataViewSwitcher.style.display = tabId === CONFIG.tabs.data ? 'inline-flex' : 'none';
            }

            syncPrimaryTabIndicator();
            requestAnimationFrame(syncScopeSwitcherSlider);
            
            // Show export button
            if (exportBtn) exportBtn.style.display = 'flex';
            
            // Re-render charts on switch
            if (tabId === CONFIG.tabs.charts) {
                drawCharts(currentFilteredDf1, currentFilteredDf2);
            }
        });
    });
}

function initResultViewSwitching() {
    const viewButtons = document.querySelectorAll('.scope-btn');
    const resultPanels = document.querySelectorAll('.result-panel');

    viewButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetId = button.getAttribute('data-view');
            const activeButton = document.querySelector('.scope-btn.active');
            if (activeButton === button) return;
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
            if (!currentPanel || currentPanel === targetPanel) {
                resultPanels.forEach(panel => panel.classList.remove('active'));
                targetPanel.classList.add('active');
                return;
            }

            transitionResultPanels(currentPanel, targetPanel, resultPanels);
        });
    });
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
    const switcher = document.querySelector('.data-scope-options');
    if (!switcher || switcher.offsetParent === null) return;

    const slider = switcher.querySelector('.data-scope-slider');
    const activeBtn = switcher.querySelector('.scope-btn.active');
    if (!slider || !activeBtn) return;

    const switcherRect = switcher.getBoundingClientRect();
    const btnRect = activeBtn.getBoundingClientRect();

    switcher.dataset.activeView = activeBtn.getAttribute('data-view') || '';
    slider.style.width = `${btnRect.width}px`;
    slider.style.transform = `translateX(${btnRect.left - switcherRect.left - 2}px)`;
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

function generateExportFilename() {
    const now = new Date();
    const timestamp = [
        now.getFullYear(),
        String(now.getMonth() + 1).padStart(2, '0'),
        String(now.getDate()).padStart(2, '0')
    ].join('') + '_' + [
        String(now.getHours()).padStart(2, '0'),
        String(now.getMinutes()).padStart(2, '0')
    ].join('');
    
    return `DuLieuTrungThau_${timestamp}.xlsx`;
}

function prepareExportData(data, headerOrder, currentOrder) {
    return reorderDataByColumns(data, headerOrder || currentOrder)
        .map(row => ({
            ...row,
            'Ngày phê duyệt': formatDateForExcel(row['Ngày phê duyệt']),
            'Ngày hết hiệu lực': formatDateForExcel(row['Ngày hết hiệu lực'])
        }));
}

function initExcelExport() {
    document.getElementById('export-excel-btn')?.addEventListener('click', () => {
        if (currentFilteredDf1.length === 0 && currentFilteredDf2.length === 0) {
            alert('Không có dữ liệu để xuất!');
            return;
        }
        
        const wb = XLSX.utils.book_new();
        
        // Export DF1
        if (currentFilteredDf1.length > 0) {
            const headerOrder = getCurrentHeaderOrder('standard-table');
            const data = prepareExportData(currentFilteredDf1, headerOrder, currentColumnOrderDf1);
            const ws = XLSX.utils.json_to_sheet(data);
            XLSX.utils.book_append_sheet(wb, ws, 'Kết quả mua sắm thuốc');
            console.log('✅ DF1 export với thứ tự:', headerOrder || currentColumnOrderDf1);
        }
        
        // Export DF2
        if (currentFilteredDf2.length > 0) {
            const headerOrder = getCurrentHeaderOrder('extended-table');
            const data = prepareExportData(currentFilteredDf2, headerOrder, currentColumnOrderDf2);
            const ws = XLSX.utils.json_to_sheet(data);
            XLSX.utils.book_append_sheet(wb, ws, 'Kết quả mua sắm hàng hóa');
            console.log('✅ DF2 export với thứ tự:', headerOrder || currentColumnOrderDf2);
        }
        
        const filename = generateExportFilename();
        XLSX.writeFile(wb, filename);
        
        console.log(`✅ Exported ${currentFilteredDf1.length + currentFilteredDf2.length} records to ${filename}`);
    });
}

function initSearchFormEvents() {
    const searchForm = document.querySelector('custom-search-form');
    if (!searchForm) return;
    
    searchForm.addEventListener('apply-filters', async (e) => {
        await applyFilters(e.detail);
        
        const filterPanel = document.getElementById('filter-panel');
        const overlay = document.getElementById('panel-overlay');
        if (filterPanel) filterPanel.classList.remove('show');
        if (overlay) overlay.classList.remove('show');
    });
    
    searchForm.addEventListener('reset-filters', () => {
        currentFilterState = {};
        currentFilteredDf1 = [];
        currentFilteredDf2 = [];
        updateResults([], []);
        hideLimitWarning();
    });
}



function disableDefaultTooltips() {
    document.querySelectorAll('.action-btn, .btn-export, .btn-meta-simple')
        .forEach(button => {
            const title = button.getAttribute('title');
            if (title) {
                button.setAttribute('data-title', title);
                button.removeAttribute('title');
            }
        });
}

async function initializeAppData() {
    try {
        // ✅ Không load df1/df2 nữa vì filter từ database
        await loadMetadata();
        initEmptyCharts();
        
        console.log('✅ App initialized - Ready for filtering from database');
        
    } catch (err) {
        console.error('❌ Error initializing app:', err);
        console.error('⚠️ Server có thể đang khởi động, vui lòng đợi 30s và refresh lại');
        await loadMetadata();
        initEmptyCharts();
    }
}


function initTableRangeSelection() {
    Object.keys(tableSel).forEach(tableId => {
        initTableRangeSelect(tableId);
    });
    initRangeCopy();
}

// Main initialization
document.addEventListener('DOMContentLoaded', function() {
    initStorageAndElements();
    initModalEvents();
    initTabSwitching();
    initResultViewSwitching();
    initExcelExport();
    initSearchFormEvents();
    initSortPanel();
    disableDefaultTooltips();
    initializeAppData();
    syncPrimaryTabIndicator();
    syncScopeSwitcherSlider();
});

window.addEventListener('load', function() {
    console.log('🚀 Window loaded, initializing drag & drop...');
    setTimeout(() => {
        initTableColumnDragDrop();
        initTableRangeSelection();
        syncPrimaryTabIndicator();
        syncScopeSwitcherSlider();
    }, 1000);
});

window.addEventListener('resize', () => {
    syncPrimaryTabIndicator();
    syncScopeSwitcherSlider();
});
