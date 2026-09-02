(function () {
    const GROUP_SCOPE = { goods: 'goods', medicines: 'medicine', traditional: 'traditional' };
    const GROUP_LABELS = {
        goods: 'Hàng hóa',
        medicines: 'Thuốc',
        traditional: 'Dược liệu / Vị thuốc cổ truyền'
    };

    function apiBaseUrl() {
        if (window.API_BASE_URL) return window.API_BASE_URL;
        const local = window.location.protocol === 'file:' ||
            window.location.hostname === 'localhost' ||
            window.location.hostname === '127.0.0.1';
        return local
            ? 'http://127.0.0.1:8001'
            : 'https://bidfinder-api-staging-774667987564.asia-southeast1.run.app';
    }

    function contractPromise() {
        if (!window.BIDFinderSearchContractPromise) {
            const fetcher = window.bidfinderAuthorizedFetch || fetch;
            window.BIDFinderSearchContractPromise = fetcher(`${apiBaseUrl()}/api/search-contract`)
                .then(response => response.json().then(payload => {
                    if (!response.ok || !payload?.contract?.groups) {
                        throw new Error(payload?.message || `HTTP ${response.status}`);
                    }
                    return payload.contract;
                }));
        }
        return window.BIDFinderSearchContractPromise;
    }

    function html(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function splitValues(value) {
        return String(value || '')
            .split(',')
            .map(item => item.trim())
            .filter(Boolean);
    }

    class TypesenseSearchForm extends HTMLElement {
        connectedCallback() {
            this.state = {
                group: 'goods',
                sourceTypes: [],
                text: '',
                searchField: '',
                structuredFilters: {},
                ranges: {},
                dateRanges: {},
                sortField: '',
                sortOrder: 'desc',
                page: 1,
                limit: 50,
                loading: false,
                contract: null,
                pendingPayload: null
            };
            this.abortController = null;
            this.previewTimer = null;
            this.autocompleteTimer = null;
            this.autocompleteSeq = 0;
            this.attachShadow({ mode: 'open' });
            this.renderShell('Đang tải danh mục tìm kiếm…');
            contractPromise()
                .then(contract => {
                    this.state.contract = contract;
                    if (this.state.pendingPayload) this.applyPayload(this.state.pendingPayload);
                    this.render();
                })
                .catch(error => this.showError(error?.message || 'Không tải được danh mục tìm kiếm.'));
        }

        renderShell(message) {
            this.shadowRoot.innerHTML = `
                <style>${this.styles()}</style>
                <section class="ts-search" aria-label="Tìm kiếm dữ liệu MSC">
                    <div class="ts-loading">${html(message)}</div>
                </section>`;
        }

        styles() {
            return `
                :host { display:block; color:#183445; font:14px/1.45 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
                * { box-sizing:border-box; }
                .ts-search { display:flex; flex-direction:column; gap:14px; padding:4px; }
                .ts-loading, .ts-error { padding:18px; border:1px solid #d3e2eb; border-radius:10px; background:#f7fbfd; color:#56707f; }
                .ts-error { color:#a63d3d; background:#fff7f7; border-color:#f0caca; }
                .ts-heading { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
                .ts-heading h2 { margin:0; font-size:18px; color:#0f5b77; }
                .ts-heading p { margin:3px 0 0; color:#6b8190; font-size:12px; }
                .ts-contract { color:#6b8190; font-size:11px; white-space:nowrap; }
                .ts-tabs { display:flex; gap:8px; flex-wrap:wrap; }
                .ts-tab { border:1px solid #c8dce7; border-radius:9px; background:#fff; color:#345566; padding:9px 13px; cursor:pointer; font-weight:700; }
                .ts-tab[aria-selected="true"] { background:#0f6f8e; border-color:#0f6f8e; color:#fff; box-shadow:0 3px 10px rgba(15,111,142,.18); }
                .ts-subtypes { display:flex; flex-wrap:wrap; gap:8px 14px; padding:10px 12px; border:1px solid #d8e6ed; border-radius:9px; background:#f7fbfd; }
                .ts-subtypes legend { width:100%; margin-bottom:2px; color:#56707f; font-size:12px; font-weight:800; }
                .ts-check { display:flex; align-items:flex-start; gap:7px; min-width:190px; color:#345566; font-size:13px; }
                .ts-check input { margin-top:3px; accent-color:#0f6f8e; }
                .ts-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
                .ts-field { min-width:0; }
                .ts-field label { display:block; margin-bottom:4px; color:#345566; font-size:12px; font-weight:700; }
                .ts-field input, .ts-field select { width:100%; min-height:38px; border:1px solid #c8dce7; border-radius:7px; background:#fff; color:#183445; padding:8px 10px; }
                .ts-field input:focus, .ts-field select:focus, .ts-tab:focus, .ts-action:focus { outline:3px solid rgba(18,116,149,.18); outline-offset:1px; border-color:#0f6f8e; }
                .ts-keyword { grid-column:1/-1; position:relative; }
                .ts-keyword-row { display:grid; grid-template-columns:minmax(0,2fr) minmax(180px,1fr); gap:10px; }
                .ts-suggestions { position:absolute; z-index:20; left:0; right:0; top:66px; margin:0; padding:4px; list-style:none; border:1px solid #c8dce7; border-radius:8px; background:#fff; box-shadow:0 10px 24px rgba(16,34,48,.12); }
                .ts-suggestions[hidden] { display:none; }
                .ts-suggestions button { width:100%; padding:8px 10px; border:0; border-radius:5px; background:transparent; color:#183445; text-align:left; cursor:pointer; }
                .ts-suggestions button:hover, .ts-suggestions button:focus { background:#edf6fa; outline:0; }
                .ts-section-title { grid-column:1/-1; margin:6px 0 0; padding-top:10px; border-top:1px solid #e1edf2; color:#0f5b77; font-size:13px; }
                .ts-range { display:grid; grid-template-columns:1fr 1fr; gap:7px; }
                .ts-range input { min-width:0; }
                .ts-actions { display:flex; justify-content:space-between; align-items:center; gap:10px; padding-top:4px; }
                .ts-status { min-height:20px; color:#56707f; font-size:12px; }
                .ts-status.error { color:#a63d3d; }
                .ts-action { border:1px solid #c8dce7; border-radius:8px; padding:9px 13px; cursor:pointer; font-weight:700; }
                .ts-action.secondary { background:#fff; color:#345566; }
                .ts-action.primary { background:#0f6f8e; border-color:#0f6f8e; color:#fff; }
                .ts-action:disabled { cursor:wait; opacity:.65; }
                @media (max-width:700px) { .ts-grid, .ts-keyword-row { grid-template-columns:1fr; } .ts-check { min-width:100%; } .ts-actions { align-items:stretch; flex-direction:column; } .ts-action { width:100%; } .ts-contract { display:none; } }
            `;
        }

        groupContract() {
            const key = this.state.group === 'traditional_medicine' ? 'traditional' : this.state.group;
            return this.state.contract?.groups?.[key] || null;
        }

        fieldMeta(name) {
            return this.groupContract()?.fields?.find(field => field.name === name) || null;
        }

        render() {
            const contract = this.state.contract;
            if (!contract) return;
            const group = this.groupContract();
            const fields = group.fields || [];
            const searchable = fields.filter(field => field.searchable);
            const filterable = fields.filter(field => field.filterable);
            const groupButtons = Object.keys(contract.groups).map(key => `
                <button type="button" class="ts-tab" data-group="${html(key)}" aria-selected="${key === this.state.group}">${html(GROUP_LABELS[key] || contract.groups[key].schema_group)}</button>`).join('');
            const subtypes = (group.source_types || []).map(source => `
                <label class="ts-check"><input type="checkbox" data-source-type="${html(source.key)}" ${this.state.sourceTypes.includes(source.key) ? 'checked' : ''}><span>${html(source.label)}</span></label>`).join('');
            const fieldOptions = [`<option value="">Tất cả trường tìm kiếm</option>`]
                .concat(searchable.map(field => `<option value="${html(field.name)}" ${field.name === this.state.searchField ? 'selected' : ''}>${html(field.label)}</option>`)).join('');
            const filters = filterable.map(field => this.renderFilter(field)).join('');
            const sortOptions = [`<option value="">Không sắp xếp riêng</option>`]
                .concat((group.sort_fields || []).map(name => {
                    const field = this.fieldMeta(name);
                    return `<option value="${html(name)}" ${name === this.state.sortField ? 'selected' : ''}>${html(field?.label || name)}</option>`;
                })).join('');
            const activeSummary = this.activeSummary();

            this.shadowRoot.innerHTML = `
                <style>${this.styles()}</style>
                <section class="ts-search" aria-label="Tìm kiếm dữ liệu MSC">
                    <div class="ts-heading"><div><h2>${html(GROUP_LABELS[this.state.group] || group.schema_group)}</h2><p>Tra cứu trực tiếp trên dữ liệu MSC đầy đủ</p></div><span class="ts-contract">${html(contract.serving_generation)} · ${html(contract.contract_version)}</span></div>
                    <div class="ts-tabs" role="tablist" aria-label="Nhóm dữ liệu">${groupButtons}</div>
                    <fieldset class="ts-subtypes"><legend>Loại nguồn</legend><label class="ts-check"><input type="checkbox" data-all-sources ${this.state.sourceTypes.length === 0 ? 'checked' : ''}><span>Tất cả trong nhóm</span></label>${subtypes}</fieldset>
                    <div class="ts-grid">
                        <div class="ts-field ts-keyword"><label for="ts-keyword">Từ khóa</label><div class="ts-keyword-row"><input id="ts-keyword" type="search" autocomplete="off" placeholder="Nhập từ khóa tìm kiếm…" value="${html(this.state.text)}"><select id="ts-search-field" aria-label="Trường tìm kiếm">${fieldOptions}</select></div><ul class="ts-suggestions" hidden></ul></div>
                        <h3 class="ts-section-title">Bộ lọc nâng cao</h3>
                        ${filters || '<p class="ts-status">Nhóm này chưa có trường lọc.</p>'}
                        <h3 class="ts-section-title">Sắp xếp và phân trang</h3>
                        <div class="ts-field"><label for="ts-sort-field">Sắp xếp theo</label><select id="ts-sort-field">${sortOptions}</select></div>
                        <div class="ts-field"><label for="ts-sort-order">Thứ tự</label><select id="ts-sort-order"><option value="desc" ${this.state.sortOrder === 'desc' ? 'selected' : ''}>Giảm dần</option><option value="asc" ${this.state.sortOrder === 'asc' ? 'selected' : ''}>Tăng dần</option></select></div>
                        <div class="ts-field"><label for="ts-page-size">Số dòng mỗi trang</label><select id="ts-page-size"><option value="25" ${this.state.limit === 25 ? 'selected' : ''}>25</option><option value="50" ${this.state.limit === 50 ? 'selected' : ''}>50</option><option value="100" ${this.state.limit === 100 ? 'selected' : ''}>100</option><option value="200" ${this.state.limit === 200 ? 'selected' : ''}>200</option></select></div>
                    </div>
                    <div class="ts-actions"><div class="ts-status" role="status" aria-live="polite">${html(activeSummary || 'Chọn điều kiện, sau đó bấm Tra cứu.')}</div><div><button type="button" class="ts-action secondary" data-action="reset">Đặt lại</button> <button type="button" class="ts-action primary" data-action="apply">${this.state.loading ? 'Đang tra cứu…' : 'Tra cứu'}</button></div></div>
                </section>`;
            this.bindEvents();
        }

        renderFilter(field) {
            const current = this.state.structuredFilters[field.name];
            const values = current?.in || current?.eq || (Array.isArray(current) ? current : []);
            const value = Array.isArray(values) ? values.join(', ') : String(values || '');
            if (field.name === 'partition_date') {
                const range = this.state.dateRanges.partition_date || {};
                return `<div class="ts-field"><label>${html(field.label)}</label><div class="ts-range"><input type="date" data-date-from="partition_date" value="${html(range.from || '')}" aria-label="${html(field.label)} từ"><input type="date" data-date-to="partition_date" value="${html(range.to || '')}" aria-label="${html(field.label)} đến"></div></div>`;
            }
            if (field.type === 'float' || field.type === 'int32') {
                const range = this.state.ranges[field.name] || {};
                return `<div class="ts-field"><label>${html(field.label)}</label><div class="ts-range"><input type="number" step="any" data-range-min="${html(field.name)}" value="${html(range.min ?? '')}" placeholder="Từ" aria-label="${html(field.label)} tối thiểu"><input type="number" step="any" data-range-max="${html(field.name)}" value="${html(range.max ?? '')}" placeholder="Đến" aria-label="${html(field.label)} tối đa"></div></div>`;
            }
            return `<div class="ts-field"><label for="ts-filter-${html(field.name)}">${html(field.label)}</label><input id="ts-filter-${html(field.name)}" type="text" data-structured-filter="${html(field.name)}" value="${html(value)}" placeholder="Giá trị chính xác; ngăn cách nhiều giá trị bằng dấu phẩy" autocomplete="off"></div>`;
        }

        bindEvents() {
            const root = this.shadowRoot;
            root.querySelectorAll('[data-group]').forEach(button => button.addEventListener('click', () => {
                this.state.group = button.dataset.group;
                this.state.sourceTypes = [];
                this.state.structuredFilters = {};
                this.state.ranges = {};
                this.state.dateRanges = {};
                this.state.searchField = '';
                this.state.sortField = '';
                this.state.page = 1;
                this.render();
                this.requestPreview();
            }));
            root.querySelector('[data-all-sources]')?.addEventListener('change', event => {
                if (event.target.checked) {
                    this.state.sourceTypes = [];
                    root.querySelectorAll('[data-source-type]').forEach(input => { input.checked = false; });
                }
                this.state.page = 1;
                this.requestPreview();
            });
            root.querySelectorAll('[data-source-type]').forEach(input => input.addEventListener('change', () => {
                this.state.sourceTypes = Array.from(root.querySelectorAll('[data-source-type]:checked')).map(item => item.dataset.sourceType);
                const all = root.querySelector('[data-all-sources]');
                if (all) all.checked = this.state.sourceTypes.length === 0;
                this.state.page = 1;
                this.requestPreview();
            }));
            const keyword = root.getElementById('ts-keyword');
            keyword?.addEventListener('input', () => {
                this.state.text = keyword.value;
                this.state.page = 1;
                this.queueAutocomplete(keyword.value);
            });
            keyword?.addEventListener('keydown', event => {
                if (event.key === 'Enter') { event.preventDefault(); this.submit(); }
            });
            root.getElementById('ts-search-field')?.addEventListener('change', event => {
                this.state.searchField = event.target.value;
                this.state.page = 1;
                this.render();
                this.requestPreview();
            });
            root.querySelectorAll('[data-structured-filter]').forEach(input => input.addEventListener('input', () => {
                const values = splitValues(input.value);
                if (values.length) this.state.structuredFilters[input.dataset.structuredFilter] = values.length === 1 ? { eq: values[0] } : { in: values };
                else delete this.state.structuredFilters[input.dataset.structuredFilter];
                this.state.page = 1;
                this.requestPreview();
            }));
            root.querySelectorAll('[data-range-min], [data-range-max]').forEach(input => input.addEventListener('input', () => {
                const field = input.dataset.rangeMin || input.dataset.rangeMax;
                const range = this.state.ranges[field] || {};
                const key = input.dataset.rangeMin ? 'min' : 'max';
                if (input.value === '') delete range[key]; else range[key] = Number(input.value);
                if (Object.keys(range).length) this.state.ranges[field] = range; else delete this.state.ranges[field];
                this.state.page = 1;
                this.requestPreview();
            }));
            root.querySelectorAll('[data-date-from], [data-date-to]').forEach(input => input.addEventListener('change', () => {
                const range = this.state.dateRanges.partition_date || {};
                const key = input.dataset.dateFrom ? 'from' : 'to';
                if (input.value) range[key] = input.value; else delete range[key];
                if (Object.keys(range).length) this.state.dateRanges.partition_date = range; else delete this.state.dateRanges.partition_date;
                this.state.page = 1;
                this.requestPreview();
            }));
            root.getElementById('ts-sort-field')?.addEventListener('change', event => { this.state.sortField = event.target.value; this.state.page = 1; this.requestPreview(); });
            root.getElementById('ts-sort-order')?.addEventListener('change', event => { this.state.sortOrder = event.target.value; this.state.page = 1; this.requestPreview(); });
            root.getElementById('ts-page-size')?.addEventListener('change', event => { this.state.limit = Number(event.target.value) || 50; this.state.page = 1; });
            root.querySelector('[data-action="apply"]')?.addEventListener('click', () => this.submit());
            root.querySelector('[data-action="reset"]')?.addEventListener('click', () => this.resetAllFilters());
        }

        queueAutocomplete(keyword) {
            clearTimeout(this.autocompleteTimer);
            this.closeSuggestions();
            const field = this.fieldMeta(this.state.searchField);
            if (!keyword.trim() || !field?.autocomplete) return;
            this.autocompleteTimer = setTimeout(() => this.fetchAutocomplete(keyword.trim()), 220);
        }

        async fetchAutocomplete(keyword) {
            if (this.abortController) this.abortController.abort();
            this.abortController = new AbortController();
            const seq = ++this.autocompleteSeq;
            try {
                const response = await (window.bidfinderAuthorizedFetch || fetch)(`${apiBaseUrl()}/api/autocomplete`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: this.abortController.signal,
                    body: JSON.stringify({ scope: GROUP_SCOPE[this.state.group], group: this.state.group, field: this.state.searchField, keyword, sourceTypes: this.state.sourceTypes, searchFields: [this.state.searchField], limit: 8 })
                });
                const payload = await response.json();
                if (seq !== this.autocompleteSeq || !response.ok) return;
                this.showSuggestions(Array.isArray(payload?.data) ? payload.data : []);
            } catch (error) {
                if (error?.name !== 'AbortError') console.warn('Autocomplete failed:', error);
            }
        }

        showSuggestions(values) {
            const list = this.shadowRoot.querySelector('.ts-suggestions');
            if (!list) return;
            list.replaceChildren();
            values.forEach(value => {
                const button = document.createElement('button');
                button.type = 'button';
                button.textContent = value;
                button.addEventListener('click', () => {
                    this.state.text = value;
                    this.render();
                    this.shadowRoot.getElementById('ts-keyword')?.focus();
                    this.requestPreview();
                });
                const item = document.createElement('li');
                item.appendChild(button);
                list.appendChild(item);
            });
            list.hidden = values.length === 0;
        }

        closeSuggestions() {
            const list = this.shadowRoot?.querySelector('.ts-suggestions');
            if (list) list.hidden = true;
        }

        requestPreview() {
            clearTimeout(this.previewTimer);
            this.previewTimer = setTimeout(() => this.dispatchEvent(new CustomEvent('preview-filters', { detail: this.collectFilterPayload(), bubbles: true, composed: true })), 300);
        }

        collectFilterPayload() {
            const sort = this.state.sortField ? [{ column: this.state.sortField, order: this.state.sortOrder }] : [];
            return {
                scope: GROUP_SCOPE[this.state.group] || 'all',
                group: this.state.group,
                sourceTypes: [...this.state.sourceTypes],
                text: this.state.text.trim(),
                searchFields: this.state.searchField ? [this.state.searchField] : [],
                filters: {},
                structuredFilters: { ...this.state.structuredFilters },
                ranges: { ...this.state.ranges },
                dateRanges: { ...this.state.dateRanges },
                exactIdentifiers: {},
                sort,
                page: this.state.page,
                limit: this.state.limit,
                queryMode: 'search'
            };
        }

        activeSummary() {
            const request = this.collectFilterPayload();
            const count = request.sourceTypes.length + Object.keys(request.structuredFilters).length + Object.keys(request.ranges).length + Object.keys(request.dateRanges).length + (request.text ? 1 : 0) + request.sort.length;
            return count ? `${count} điều kiện đang chọn` : '';
        }

        submit() {
            const request = this.collectFilterPayload();
            for (const range of Object.values(request.ranges)) {
                if (range.min !== undefined && range.max !== undefined && range.min > range.max) {
                    this.showStatus('Giá trị tối thiểu không được lớn hơn giá trị tối đa.', true);
                    return;
                }
            }
            const dateRange = request.dateRanges.partition_date;
            if (dateRange?.from && dateRange?.to && dateRange.from > dateRange.to) {
                this.showStatus('Ngày bắt đầu không được sau ngày kết thúc.', true);
                return;
            }
            this.state.loading = true;
            this.render();
            this.dispatchEvent(new CustomEvent('apply-filters', { detail: request, bubbles: true, composed: true }));
        }

        resetAllFilters() {
            this.state.sourceTypes = [];
            this.state.text = '';
            this.state.searchField = '';
            this.state.structuredFilters = {};
            this.state.ranges = {};
            this.state.dateRanges = {};
            this.state.sortField = '';
            this.state.sortOrder = 'desc';
            this.state.page = 1;
            this.state.loading = false;
            this.render();
            this.dispatchEvent(new CustomEvent('reset-filters', { bubbles: true, composed: true }));
        }

        applyPayload(payload) {
            const next = payload || {};
            if (next.group) this.state.group = next.group === 'traditional_medicine' ? 'traditional' : next.group;
            this.state.pendingPayload = null;
            this.state.sourceTypes = Array.isArray(next.sourceTypes) ? [...next.sourceTypes] : [];
            this.state.text = String(next.text || '');
            this.state.searchField = Array.isArray(next.searchFields) ? String(next.searchFields[0] || '') : '';
            this.state.structuredFilters = next.structuredFilters && typeof next.structuredFilters === 'object' ? { ...next.structuredFilters } : {};
            this.state.ranges = next.ranges && typeof next.ranges === 'object' ? { ...next.ranges } : {};
            this.state.dateRanges = next.dateRanges && typeof next.dateRanges === 'object' ? { ...next.dateRanges } : {};
            this.state.sortField = Array.isArray(next.sort) ? String(next.sort[0]?.column || '') : '';
            this.state.sortOrder = next.sort?.[0]?.order === 'asc' ? 'asc' : 'desc';
            this.state.page = Math.max(1, Number(next.page || 1));
            this.state.limit = Math.min(200, Math.max(25, Number(next.limit || 50)));
        }

        setFilterPayload(payload = {}) {
            if (!this.state.contract) { this.state.pendingPayload = payload; return; }
            this.applyPayload(payload);
            this.render();
        }

        setPage(page) { this.state.page = Math.max(1, Number(page || 1)); }

        setApplyLoading(loading = false) { this.state.loading = Boolean(loading); if (this.state.contract) this.render(); }

        setPreviewResult({ idle = false, loading = false, error = false, errorMessage = '', total = null, totalLabel = '' } = {}) {
            if (!this.shadowRoot) return;
            const status = this.shadowRoot.querySelector('.ts-status');
            if (!status) return;
            status.classList.toggle('error', error);
            if (idle) status.textContent = this.activeSummary() || 'Chọn điều kiện, sau đó bấm Tra cứu.';
            else if (loading) status.textContent = 'Đang ước tính số kết quả…';
            else if (error) status.textContent = errorMessage || 'Không ước tính được số kết quả.';
            else if (total !== null || totalLabel) status.textContent = `Có ${totalLabel || Number(total || 0).toLocaleString('vi-VN')} kết quả`;
        }

        showStatus(message, error = false) {
            const status = this.shadowRoot?.querySelector('.ts-status');
            if (status) { status.textContent = message; status.classList.toggle('error', error); }
        }

        showError(message) { this.renderShell(message); this.shadowRoot.querySelector('.ts-loading')?.classList.add('ts-error'); }
        hasVisiblePreviewEstimate() { return /Có\s+.+\s+kết quả/.test(this.shadowRoot?.querySelector('.ts-status')?.textContent || ''); }
        activatePane() {}
        getPreferredPaneForOpen() { return 'keyword'; }
        focusActiveField() { this.shadowRoot?.getElementById('ts-keyword')?.focus(); }
    }

    customElements.define('typesense-search-form', TypesenseSearchForm);
})();
