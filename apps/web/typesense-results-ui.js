(function () {
    const DEFAULT_COLUMNS = {
        goods: ['item_name', 'unit', 'quantity', 'winning_unit_price', 'winning_bidder_name', 'procuring_entity_name', 'bid_invitation_code', 'partition_date'],
        medicines: ['medicine_name', 'active_ingredient_or_herbal_component', 'strength', 'dosage_form', 'manufacturer', 'quantity', 'winning_unit_price', 'winning_bidder_name', 'bid_invitation_code', 'partition_date'],
        traditional: ['item_name', 'scientific_name', 'unit', 'origin', 'manufacturer', 'quantity', 'winning_unit_price', 'winning_bidder_name', 'bid_invitation_code', 'partition_date']
    };
    const GROUP_LABELS = { goods: 'Hàng hóa', medicines: 'Thuốc', traditional: 'Dược liệu / Vị thuốc cổ truyền' };
    const PAGE_KEYS = { goods: 'df2', medicines: 'df1', traditional: 'df3' };

    function html(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function displayValue(value, field) {
        if (value === null || value === undefined || value === '') return '—';
        if (Array.isArray(value)) return value.join(', ');
        if (field?.type === 'float' || field?.type === 'int32') return Number(value).toLocaleString('vi-VN', { maximumFractionDigits: 2 });
        if (field?.name?.includes('date') || field?.name?.endsWith('_at')) {
            const date = new Date(value);
            if (!Number.isNaN(date.getTime())) return date.toLocaleDateString('vi-VN');
        }
        return String(value);
    }

    class TypesenseResultsUi extends HTMLElement {
        connectedCallback() {
            this.contract = null;
            this.query = null;
            this.result = null;
            this.renderShell('Chưa có kết quả. Chọn nhóm dữ liệu để bắt đầu tra cứu.');
            document.body.classList.add('typesense-primary-ui');
            document.addEventListener('bidfinder:query-start', () => this.renderShell('Đang tải dữ liệu MSC…'));
            document.addEventListener('bidfinder:query-result', event => this.receiveResult(event.detail));
            document.addEventListener('bidfinder:query-error', event => this.renderShell(event.detail?.message || 'Không tải được kết quả.'));
            document.addEventListener('bidfinder:query-reset', () => this.renderShell('Chưa có kết quả. Chọn nhóm dữ liệu để bắt đầu tra cứu.'));
            (window.BIDFinderSearchContractPromise || Promise.resolve(null)).then(contract => { this.contract = contract; if (this.result) this.render(); });
        }

        styles() {
            return `
                :host { display:block; margin-top:16px; color:#183445; font:14px/1.45 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
                * { box-sizing:border-box; }
                .ts-results { border:1px solid #d3e2eb; border-radius:12px; background:#fff; box-shadow:0 10px 24px rgba(16,34,48,.06); overflow:hidden; }
                .ts-results-header { display:flex; justify-content:space-between; gap:14px; align-items:flex-start; padding:16px 18px; border-bottom:1px solid #e1edf2; background:#f7fbfd; }
                .ts-results-header h2 { margin:0; color:#0f5b77; font-size:18px; }
                .ts-results-header p { margin:4px 0 0; color:#6b8190; font-size:12px; }
                .ts-badge { border:1px solid #b9d9e4; border-radius:99px; padding:5px 9px; color:#0f6f8e; background:#edf8fb; font-size:11px; white-space:nowrap; }
                .ts-degraded { margin:12px 18px 0; padding:9px 11px; border:1px solid #f0d7a8; border-radius:8px; background:#fff9ec; color:#805d16; font-size:12px; }
                .ts-table-wrap { overflow-x:auto; }
                table { width:100%; min-width:900px; border-collapse:collapse; }
                th, td { padding:10px 12px; border-bottom:1px solid #edf2f5; vertical-align:top; text-align:left; }
                th { color:#56707f; background:#fafdfe; font-size:11px; text-transform:uppercase; letter-spacing:.03em; white-space:nowrap; }
                td { color:#183445; max-width:260px; word-break:break-word; }
                .ts-index { width:48px; color:#6b8190; text-align:center; }
                .ts-detail { margin-top:7px; }
                .ts-detail summary { color:#0f6f8e; cursor:pointer; font-size:12px; font-weight:700; }
                .ts-detail-grid { display:grid; grid-template-columns:repeat(2,minmax(220px,1fr)); gap:8px 18px; padding:10px; margin-top:7px; border:1px solid #d8e6ed; border-radius:8px; background:#f9fcfd; }
                .ts-detail-item { min-width:0; }
                .ts-detail-item dt { color:#56707f; font-size:11px; font-weight:700; }
                .ts-detail-item dd { margin:2px 0 0; white-space:pre-wrap; word-break:break-word; }
                .ts-empty, .ts-loading { padding:30px 18px; color:#6b8190; text-align:center; }
                .ts-error { color:#a63d3d; background:#fff7f7; }
                .ts-pager { display:flex; justify-content:space-between; align-items:center; gap:10px; padding:12px 18px; color:#56707f; font-size:12px; }
                .ts-pager button { border:1px solid #c8dce7; border-radius:7px; padding:7px 11px; background:#fff; color:#0f6f8e; cursor:pointer; }
                .ts-pager button:disabled { cursor:not-allowed; opacity:.45; }
                @media (max-width:700px) { .ts-results-header { flex-direction:column; } .ts-detail-grid { grid-template-columns:1fr; } .ts-pager { align-items:stretch; flex-direction:column; text-align:center; } }
            `;
        }

        renderShell(message, error = false) {
            this.innerHTML = `<style>${this.styles()}</style><section class="ts-results" aria-live="polite"><div class="ts-${error ? 'error' : 'empty'}">${html(message)}</div></section>`;
        }

        receiveResult(detail = {}) {
            this.query = detail.query || {};
            this.result = detail.result || {};
            if (!this.contract && window.BIDFinderSearchContractPromise) {
                window.BIDFinderSearchContractPromise.then(contract => { this.contract = contract; this.render(); });
            }
            this.render();
        }

        groupKey() {
            const group = this.query?.group || (this.result?.df3 ? 'traditional' : this.result?.df2 ? 'goods' : 'medicines');
            return group === 'traditional_medicine' ? 'traditional' : group;
        }

        pageData() {
            const key = PAGE_KEYS[this.groupKey()] || 'df1';
            return this.result?.[key] || { data: [], count: 0, displayed: 0, page: this.query?.page || 1, limit: this.query?.limit || 50, has_more: false };
        }

        fieldInfo(name) { return this.contract?.groups?.[this.groupKey()]?.fields?.find(field => field.name === name) || null; }
        fields() { return this.contract?.groups?.[this.groupKey()]?.fields || []; }

        columns(rows) {
            const known = new Set(this.fields().map(field => field.name));
            const preferred = (DEFAULT_COLUMNS[this.groupKey()] || []).filter(name => known.has(name));
            if (preferred.length) return preferred;
            return this.fields().filter(field => field.ui_visibility !== 'detail').slice(0, 8).map(field => field.name);
        }

        detailFields(row) {
            const contractFields = this.fields().map(field => field.name).filter(name => Object.prototype.hasOwnProperty.call(row, name));
            const extras = Object.keys(row).filter(name => !contractFields.includes(name) && !name.startsWith('__'));
            return [...contractFields, ...extras];
        }

        render() {
            if (!this.result) return;
            const page = this.pageData();
            const rows = Array.isArray(page.data) ? page.data : [];
            const group = this.groupKey();
            const fields = this.columns(rows);
            const contract = this.contract?.groups?.[group];
            const fallback = page.backend_fallback || this.result.backend_fallback;
            const total = Number(page.count || 0);
            const pageNumber = Number(page.page || this.query?.page || 1);
            const limit = Number(page.limit || this.query?.limit || 50);
            const backendLabel = fallback ? 'Postgres dự phòng · phạm vi dữ liệu cũ' : `Typesense · ${this.contract?.serving_generation || 'serving_v1_20260901'}`;
            const head = fields.map(name => `<th>${html(this.fieldInfo(name)?.label || name)}</th>`).join('');
            const body = rows.map((row, index) => {
                const cells = fields.map(name => `<td>${html(displayValue(row[name], this.fieldInfo(name)))}</td>`).join('');
                const detail = this.detailFields(row).map(name => `<div class="ts-detail-item"><dt>${html(this.fieldInfo(name)?.label || name)}</dt><dd>${html(displayValue(row[name], this.fieldInfo(name)))}</dd></div>`).join('');
                return `<tr><td class="ts-index">${(pageNumber - 1) * limit + index + 1}</td>${cells}<td><details class="ts-detail"><summary>Chi tiết đầy đủ</summary><dl class="ts-detail-grid">${detail || '<div class="ts-detail-item"><dd>Không có trường chi tiết.</dd></div>'}</dl></details></td></tr>`;
            }).join('');
            const empty = rows.length ? '' : '<div class="ts-empty">Không có kết quả phù hợp với điều kiện hiện tại.</div>';
            const nextDisabled = !page.has_more;
            this.innerHTML = `<style>${this.styles()}</style><section class="ts-results" aria-label="Kết quả tìm kiếm"><header class="ts-results-header"><div><h2>${html(GROUP_LABELS[group] || contract?.schema_group || group)}</h2><p>${total.toLocaleString('vi-VN')} kết quả · trang ${pageNumber}</p></div><span class="ts-badge">${html(backendLabel)}</span></header>${fallback ? '<div class="ts-degraded" role="status">Đang hiển thị dữ liệu dự phòng do Typesense gặp lỗi hạ tầng. Phạm vi Postgres là tập dữ liệu cũ, không tương đương toàn bộ MSC.</div>' : ''}${rows.length ? `<div class="ts-table-wrap"><table><thead><tr><th class="ts-index">STT</th>${head}<th>Trường chi tiết</th></tr></thead><tbody>${body}</tbody></table></div>` : empty}<footer class="ts-pager"><button type="button" data-page="${pageNumber - 1}" ${pageNumber <= 1 ? 'disabled' : ''}>‹ Trang trước</button><span>Đang xem ${rows.length.toLocaleString('vi-VN')} / ${total.toLocaleString('vi-VN')} · trang ${pageNumber}</span><button type="button" data-page="${pageNumber + 1}" ${nextDisabled ? 'disabled' : ''}>Trang sau ›</button></footer></section>`;
            this.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => {
                const nextPage = Number(button.dataset.page);
                if (nextPage > 0) document.dispatchEvent(new CustomEvent('bidfinder:page-request', { detail: { page: nextPage } }));
            }));
        }
    }

    customElements.define('typesense-results-ui', TypesenseResultsUi);
})();
