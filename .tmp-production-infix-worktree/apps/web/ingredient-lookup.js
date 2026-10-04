(() => {
    const form = document.getElementById('ingredient-lookup-form');
    if (!form) return;
    const body = document.getElementById('ingredient-lookup-body');
    const table = body.closest('table');
    const range = document.getElementById('ingredient-lookup-range');
    const pages = document.getElementById('ingredient-lookup-pages');
    const exportButton = document.getElementById('ingredient-lookup-export');
    const countFormat = new Intl.NumberFormat('vi-VN');
    const percentFormat = new Intl.NumberFormat('vi-VN', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    const pageSize = 10;
    const headers = ['Mã hoạt chất', 'Tên hoạt chất', 'Tên thuốc', 'Số đăng ký', 'Đường dùng', 'Năm công bố', 'Số lần xuất hiện', 'Tỷ lệ (%)'];
    const fields = ['ma', 'hoatchat', 'ten', 'sodk', 'duongdung', 'nam_congbo'];
    const sortableHeaders = [...document.querySelectorAll('.ingredient-lookup-results th[data-sort]')];
    let filters = {};
    let sortBy = null;
    let sortOrder = 'asc';
    let currentPage = 1;
    let currentResult = null;
    let controller = null;
    let suggestionTimer = null;
    let suggestionController = null;
    let suggestionRequest = 0;
    let activeSuggestion = -1;
    let activeDropdown = null;
    let suggestionOwner = null;

    function filterValues() {
        return Object.fromEntries([...new FormData(form)].map(([key, value]) => [key, String(value).trim()]));
    }

    function sortParams() {
        return sortBy ? { sort_by: sortBy, sort_order: sortOrder } : {};
    }

    function updateSortHeaders() {
        sortableHeaders.forEach(header => {
            const selected = header.dataset.sort === sortBy;
            const isDefault = !sortBy && header.dataset.sort === 'occurrences';
            header.classList.toggle('is-sorted', selected);
            header.textContent = `${header.dataset.label}${selected ? (sortOrder === 'asc' ? ' ↑' : ' ↓') : (isDefault ? ' ↓' : '')}`;
            header.setAttribute('aria-sort', selected ? (sortOrder === 'asc' ? 'ascending' : 'descending') : (isDefault ? 'descending' : 'none'));
            header.title = selected ? (sortOrder === 'asc' ? 'Bấm để sắp xếp giảm dần' : 'Bấm để trở về thứ tự mặc định') : 'Bấm để sắp xếp tăng dần';
        });
    }

    sortableHeaders.forEach(header => {
        header.dataset.label = header.textContent.replace(/\s*[↑↓]$/, '').trim();
        header.tabIndex = 0;
        const toggle = () => {
            if (sortBy !== header.dataset.sort) {
                sortBy = header.dataset.sort;
                sortOrder = 'asc';
            } else if (sortOrder === 'asc') {
                sortOrder = 'desc';
            } else {
                sortBy = null;
                sortOrder = 'asc';
            }
            updateSortHeaders();
            if (Object.values(filters).some(Boolean)) void load(1);
        };
        header.addEventListener('click', toggle);
        header.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                toggle();
            }
        });
    });
    updateSortHeaders();

    function closeSuggestions() {
        clearTimeout(suggestionTimer);
        suggestionController?.abort();
        suggestionController = null;
        suggestionRequest += 1;
        activeSuggestion = -1;
        suggestionOwner = null;
        if (activeDropdown) {
            activeDropdown.hidden = true;
            activeDropdown.replaceChildren();
            activeDropdown.previousElementSibling.setAttribute('aria-expanded', 'false');
            activeDropdown.previousElementSibling.removeAttribute('aria-activedescendant');
            activeDropdown = null;
        }
    }

    form.querySelectorAll('input[name]').forEach(input => {
        const dropdown = document.createElement('ul');
        dropdown.className = 'ingredient-lookup-suggestions';
        dropdown.id = `ingredient-lookup-suggestions-${input.name}`;
        dropdown.setAttribute('role', 'listbox');
        dropdown.hidden = true;
        input.autocomplete = 'off';
        input.setAttribute('aria-autocomplete', 'list');
        input.setAttribute('aria-controls', dropdown.id);
        input.setAttribute('aria-expanded', 'false');
        input.after(dropdown);

        const renderSuggestions = (items, query) => {
            dropdown.replaceChildren();
            activeSuggestion = -1;
            items.forEach((value, index) => {
                const option = document.createElement('li');
                option.id = `${dropdown.id}-${index}`;
                option.setAttribute('role', 'option');
                option.setAttribute('aria-selected', 'false');
                const at = value.toLocaleLowerCase('vi').indexOf(query.toLocaleLowerCase('vi'));
                if (at < 0) option.textContent = value;
                else {
                    option.append(document.createTextNode(value.slice(0, at)));
                    const strong = document.createElement('strong');
                    strong.textContent = value.slice(at, at + query.length);
                    option.append(strong, document.createTextNode(value.slice(at + query.length)));
                }
                option.addEventListener('mousedown', event => event.preventDefault());
                option.addEventListener('click', () => {
                    input.value = value;
                    closeSuggestions();
                    input.focus();
                });
                dropdown.append(option);
            });
            dropdown.hidden = !items.length;
            input.setAttribute('aria-expanded', String(Boolean(items.length)));
            if (items.length) activeDropdown = dropdown;
        };

        input.addEventListener('focus', () => {
            if (suggestionOwner !== input) closeSuggestions();
            suggestionOwner = input;
        });
        input.addEventListener('input', () => {
            closeSuggestions();
            suggestionOwner = input;
            const query = input.value.trim();
            if (!query) return;
            const requestId = suggestionRequest;
            suggestionTimer = setTimeout(async () => {
                suggestionController = new AbortController();
                const params = new URLSearchParams({ ...filterValues(), field: input.name, q: query });
                try {
                    const response = await fetch(`${window.API_BASE_URL}/api/ingredient-lookup/suggest?${params}`, { signal: suggestionController.signal });
                    if (!response.ok) return;
                    const result = await response.json();
                    if (requestId === suggestionRequest && input.value.trim() === query) renderSuggestions(result.data || [], query);
                } catch (error) {
                    if (error.name !== 'AbortError') closeSuggestions();
                }
            }, 250);
        });

        input.addEventListener('keydown', event => {
            const options = [...dropdown.children];
            if (dropdown.hidden || !options.length) return;
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                activeSuggestion = (activeSuggestion + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
                options.forEach((option, index) => option.setAttribute('aria-selected', String(index === activeSuggestion)));
                input.setAttribute('aria-activedescendant', options[activeSuggestion].id);
                options[activeSuggestion].scrollIntoView({ block: 'nearest' });
            } else if (event.key === 'Enter' && activeSuggestion >= 0) {
                event.preventDefault();
                options[activeSuggestion].click();
            } else if (event.key === 'Escape') {
                closeSuggestions();
            }
        });
        input.addEventListener('blur', () => setTimeout(() => {
            if (suggestionOwner === input) closeSuggestions();
        }, 120));
    });

    async function request(page, limit = pageSize, signal) {
        const params = new URLSearchParams({ ...filters, ...sortParams(), page: String(page), limit: String(limit) });
        const response = await fetch(`${window.API_BASE_URL}/api/ingredient-lookup?${params}`, { signal });
        if (!response.ok) {
            let message = 'Không tải được dữ liệu tra cứu.';
            try { message = (await response.json()).detail || message; } catch (_) { /* Keep fallback. */ }
            throw new Error(message);
        }
        return response.json();
    }

    function showMessage(message, state = '') {
        clearCellSelectionForTable(table.id);
        clearCopiedCellRange();
        body.replaceChildren();
        const row = body.insertRow();
        const cell = row.insertCell();
        cell.colSpan = 9;
        cell.className = `ingredient-lookup-message ${state}`;
        cell.textContent = message;
    }

    function resetResults() {
        controller?.abort();
        controller = null;
        currentPage = 1;
        currentResult = null;
        sortBy = null;
        sortOrder = 'asc';
        updateSortHeaders();
        exportButton.disabled = true;
        range.textContent = '';
        pages.replaceChildren();
        showMessage('Chưa có dữ liệu, thực hiện tìm kiếm để hiển thị kết quả');
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
        clearCellSelectionForTable(table.id);
        clearCopiedCellRange();
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
        closeSuggestions();
        filters = filterValues();
        if (Object.values(filters).some(Boolean)) void load();
        else resetResults();
    });
    document.getElementById('ingredient-lookup-clear').addEventListener('click', () => {
        closeSuggestions();
        form.reset();
        filters = {};
        resetResults();
    });
    exportButton.addEventListener('click', async () => {
        if (!currentResult?.total_groups) return;
        if (!window.XLSX) {
            showMessage('Không tải được thư viện xuất Excel.', 'error');
            return;
        }
        exportButton.disabled = true;
        const snapshot = { ...filters, ...sortParams() };
        const { total_groups: groupTotal, total_records: recordTotal } = currentResult;
        const rows = [];
        try {
            const batchSize = 250;
            const batches = Math.ceil(groupTotal / batchSize);
            for (let page = 1; page <= batches; page++) {
                const params = new URLSearchParams({ ...snapshot, page: String(page), limit: String(batchSize), include_totals: 'false' });
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
