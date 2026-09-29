(() => {
    const form = document.getElementById('ingredient-lookup-form');
    if (!form) return;
    const body = document.getElementById('ingredient-lookup-body');
    const range = document.getElementById('ingredient-lookup-range');
    const pages = document.getElementById('ingredient-lookup-pages');
    const exportButton = document.getElementById('ingredient-lookup-export');
    const countFormat = new Intl.NumberFormat('vi-VN');
    const percentFormat = new Intl.NumberFormat('vi-VN', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    const pageSize = 10;
    const headers = ['Mã hoạt chất', 'Tên hoạt chất', 'Tên thuốc', 'Số đăng ký', 'Đường dùng', 'Năm công bố', 'Số lần xuất hiện', 'Tỷ lệ (%)'];
    const fields = ['ma', 'hoatchat', 'ten', 'sodk', 'duongdung', 'nam_congbo'];
    let filters = {};
    let currentPage = 1;
    let currentResult = null;
    let controller = null;
    let loaded = false;

    function filterValues() {
        return Object.fromEntries([...new FormData(form)].map(([key, value]) => [key, String(value).trim()]));
    }

    async function request(page, limit = pageSize, signal) {
        const params = new URLSearchParams({ ...filters, page: String(page), limit: String(limit) });
        const response = await fetch(`${window.API_BASE_URL}/api/ingredient-lookup?${params}`, { signal });
        if (!response.ok) {
            let message = 'Không tải được dữ liệu tra cứu.';
            try { message = (await response.json()).detail || message; } catch (_) { /* Keep fallback. */ }
            throw new Error(message);
        }
        return response.json();
    }

    function showMessage(message, state = '') {
        body.replaceChildren();
        const row = body.insertRow();
        const cell = row.insertCell();
        cell.colSpan = 9;
        cell.className = `ingredient-lookup-message ${state}`;
        cell.textContent = message;
    }

    function addText(row, value, className = '') {
        const cell = row.insertCell();
        cell.className = className;
        const text = value == null ? '' : String(value);
        cell.textContent = text;
        cell.title = text;
        return cell;
    }

    function render(result) {
        currentResult = result;
        body.replaceChildren();
        exportButton.disabled = !result.total_groups;
        if (!result.total_groups) {
            showMessage('Không tìm thấy dữ liệu phù hợp với điều kiện tra cứu.');
        } else {
            result.rows.forEach((item, index) => {
                const row = body.insertRow();
                addText(row, countFormat.format((currentPage - 1) * pageSize + index + 1), 'ingredient-lookup-rank');
                fields.forEach((field, fieldIndex) => addText(row, item[field], fieldIndex === 0 ? 'ingredient-lookup-code' : ''));
                const countCell = row.insertCell();
                countCell.className = 'ingredient-lookup-count';
                const countContent = document.createElement('div');
                countContent.className = 'ingredient-lookup-count-inner';
                const track = document.createElement('span');
                track.className = 'ingredient-lookup-track';
                const fill = document.createElement('span');
                fill.className = 'ingredient-lookup-fill';
                fill.style.width = `${result.max_count ? item.occurrences / result.max_count * 100 : 0}%`;
                track.append(fill);
                const number = document.createElement('strong');
                number.textContent = countFormat.format(item.occurrences);
                countContent.append(track, number);
                countCell.append(countContent);
                addText(row, `${percentFormat.format(item.occurrences / result.total_records * 100)}%`, 'ingredient-lookup-percent');
            });
        }
        const first = result.total_groups ? (currentPage - 1) * pageSize + 1 : 0;
        const last = Math.min(currentPage * pageSize, result.total_groups);
        range.textContent = `Hiển thị ${countFormat.format(first)} - ${countFormat.format(last)} trong ${countFormat.format(result.total_groups)} bản ghi`;
        pages.replaceChildren();
        const pageCount = Math.ceil(result.total_groups / pageSize);
        if (pageCount <= 1) return;
        const pageNumbers = new Set([1, pageCount, currentPage - 1, currentPage, currentPage + 1]);
        const addButton = (label, page, disabled = false) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = label;
            button.disabled = disabled;
            button.classList.toggle('active', page === currentPage && label === String(page));
            button.addEventListener('click', () => load(page));
            pages.append(button);
        };
        addButton('‹', currentPage - 1, currentPage === 1);
        let previous = 0;
        [...pageNumbers].filter(n => n >= 1 && n <= pageCount).sort((a, b) => a - b).forEach(n => {
            if (n > previous + 1) {
                const gap = document.createElement('span');
                gap.textContent = '…';
                pages.append(gap);
            }
            addButton(String(n), n);
            previous = n;
        });
        addButton('›', currentPage + 1, currentPage === pageCount);
    }

    async function load(page = 1) {
        controller?.abort();
        controller = new AbortController();
        currentPage = page;
        showMessage('Đang tải kết quả…', 'loading');
        exportButton.disabled = true;
        pages.replaceChildren();
        try {
            render(await request(page, pageSize, controller.signal));
        } catch (error) {
            if (error.name === 'AbortError') return;
            currentResult = null;
            range.textContent = '';
            showMessage(error.message, 'error');
        }
    }

    form.addEventListener('submit', event => {
        event.preventDefault();
        filters = filterValues();
        void load();
    });
    document.getElementById('ingredient-lookup-clear').addEventListener('click', () => {
        form.reset();
        filters = {};
        void load();
    });
    document.querySelector('[data-view="ingredient-lookup-panel"]').addEventListener('click', () => {
        if (!loaded) {
            loaded = true;
            void load();
        }
    });
    exportButton.addEventListener('click', async () => {
        if (!currentResult?.total_groups) return;
        if (!window.XLSX) {
            showMessage('Không tải được thư viện xuất Excel.', 'error');
            return;
        }
        exportButton.disabled = true;
        const snapshot = { ...filters };
        const { total_groups: groupTotal, total_records: recordTotal } = currentResult;
        const rows = [];
        try {
            const batchSize = 1000;
            const batches = Math.ceil(groupTotal / batchSize);
            for (let page = 1; page <= batches; page++) {
                const params = new URLSearchParams({ ...snapshot, page: String(page), limit: String(batchSize) });
                const response = await fetch(`${window.API_BASE_URL}/api/ingredient-lookup?${params}`);
                if (!response.ok) throw new Error('Không xuất được dữ liệu tra cứu.');
                rows.push(...(await response.json()).rows);
            }
            const values = rows.map(item => [
                ...fields.map(field => item[field] ?? ''), item.occurrences,
                recordTotal ? Number((item.occurrences / recordTotal * 100).toFixed(1)) : 0,
            ]);
            const sheet = XLSX.utils.aoa_to_sheet([headers, ...values]);
            sheet['!cols'] = [12, 30, 30, 20, 18, 14, 20, 14].map(wch => ({ wch }));
            const workbook = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(workbook, sheet, 'Tra cứu mã hoạt chất');
            XLSX.writeFile(workbook, 'TraCuuMaHoatChat.xlsx');
        } catch (error) {
            range.textContent = error.message;
        } finally {
            exportButton.disabled = !currentResult?.total_groups;
        }
    });
})();
