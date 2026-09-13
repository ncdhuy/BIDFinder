const assert = require('node:assert/strict');
const path = require('node:path');

class FakeClassList {
    constructor() { this.values = new Set(); }
    add(...names) { names.forEach(name => this.values.add(name)); }
    remove(...names) { names.forEach(name => this.values.delete(name)); }
    toggle(name, force) {
        const next = force === undefined ? !this.values.has(name) : Boolean(force);
        if (next) this.add(name); else this.remove(name);
        return next;
    }
}

class FakeNode {
    constructor(tagName = 'div') {
        this.tagName = tagName;
        this.children = [];
        this.listeners = {};
        this.dataset = {};
        this.classList = new FakeClassList();
        this.textContent = '';
        this.value = '';
        this._innerHTML = '';
        this.cache = new Map();
    }
    set innerHTML(value) { this._innerHTML = String(value); this.children = []; this.cache.clear(); }
    get innerHTML() { return this._innerHTML; }
    append(...nodes) { this.children.push(...nodes); }
    setAttribute(name, value) { this.attributes ||= {}; this.attributes[name] = String(value); }
    addEventListener(type, listener) { this.listeners[type] = listener; }
    click() { this.listeners.click?.(); }
    keydown(key, options = {}) { this.listeners.keydown?.({ key, shiftKey: false, preventDefault() {}, ...options }); }
    focus() {}
    setSelectionRange() {}
    getElementById(id) { return this.querySelector(`#${id}`); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    querySelectorAll(selector) {
        if (this.cache.has(selector)) return this.cache.get(selector);
        if (selector === '#criterion-keyword') {
            const result = this._innerHTML.includes('id="criterion-keyword"') ? [new FakeNode('input')] : [];
            this.cache.set(selector, result);
            return result;
        }
        if (selector === '[data-autocomplete-dropdown]') {
            const result = this._innerHTML.includes('data-autocomplete-dropdown') ? [new FakeNode('ul')] : [];
            this.cache.set(selector, result);
            return result;
        }
        if (selector === '[data-autocomplete-index]') {
            const result = this.children.filter(node => node?.dataset?.autocompleteIndex !== undefined);
            this.cache.set(selector, result);
            return result;
        }
        const tokenSelector = selector.match(/^\[data-(token-operator|token-edit|token-remove)\]$/);
        if (tokenSelector) {
            const attr = tokenSelector[1];
            const dataKey = attr.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
            const result = [...this._innerHTML.matchAll(new RegExp(`data-${attr}="(\\d+)"`, 'g'))].map(match => {
                const node = new FakeNode('button'); node.dataset[dataKey] = match[1]; return node;
            });
            this.cache.set(selector, result);
            return result;
        }
        return [];
    }
}

class FakeSummaryNode extends FakeNode {
    constructor(owner) { super('div'); this.owner = owner; }
    set innerHTML(value) {
        super.innerHTML = value;
        this.owner.cache.delete('[data-chip-field]');
        this.owner.cache.delete('[data-remove-field]');
        this.owner.cache.delete('[data-field],[data-chip-field]');
    }
    get innerHTML() { return this._innerHTML; }
}

class FakeContentRoot extends FakeNode {
    constructor() { super('div'); this.className = 'search-form-root'; this.renderCount = 0; this.summaryList = null; this.topbar = null; this.tokenEditor = null; }
    set innerHTML(value) { super.innerHTML = value; this.renderCount += 1; this.summaryList = null; this.topbar = null; this.tokenEditor = null; }
    get innerHTML() { return this._innerHTML; }
    querySelectorAll(selector) {
        if (this.cache.has(selector)) return this.cache.get(selector);
        let result;
        if (selector === '[data-group]') {
            result = [...this._innerHTML.matchAll(/<button[^>]*data-group="([^"]+)"[^>]*>/g)].map(match => {
                const node = new FakeNode('button');
                node.dataset.group = match[1];
                return node;
            });
            this.cache.set(selector, result);
            return result;
        }
        if (selector === '[data-field],[data-chip-field]') {
            const source = `${this._innerHTML}${this.summaryList?.innerHTML || ''}`;
            result = [...source.matchAll(/<button[^>]*data-(field|chip-field)="([^"]+)"[^>]*>/g)].map(match => {
                const node = new FakeNode('button');
                if (match[1] === 'field') node.dataset.field = match[2]; else node.dataset.chipField = match[2];
                return node;
            });
            this.cache.set(selector, result);
            return result;
        }
        if (selector === '[data-field]') {
            result = [...this._innerHTML.matchAll(/<button[^>]*data-field="([^"]+)"[^>]*>/g)].map(match => {
                const node = new FakeNode('button'); node.dataset.field = match[1]; return node;
            });
            this.cache.set(selector, result);
            return result;
        }
        if (selector === '[data-chip-field]' || selector === '[data-remove-field]') {
            const attr = selector.slice(1, -1);
            const dataKey = attr.replace(/^data-/, '').replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
            const source = this.summaryList?.innerHTML || this._innerHTML;
            result = [...source.matchAll(new RegExp(`<button[^>]*${attr}="([^"]+)"[^>]*>`, 'g'))].map(match => {
                const node = new FakeNode('button'); node.dataset[dataKey] = match[1]; return node;
            });
            this.cache.set(selector, result);
            return result;
        }
        if (selector === '.active-filters-topbar') {
            if (!this.topbar) this.topbar = new FakeNode('div');
            return [this.topbar];
        }
        if (selector === '.active-filters-list') {
            if (!this.summaryList) this.summaryList = new FakeSummaryNode(this);
            return [this.summaryList];
        }
        if (selector === '[data-token-editor]') {
            if (!this.tokenEditor && this._innerHTML.includes('data-token-editor')) {
                this.tokenEditor = new FakeNode('div');
                this.tokenEditor.innerHTML = this._innerHTML.match(/data-token-editor>([\s\S]*?)<\/div>/)?.[1] || '';
            }
            return this.tokenEditor ? [this.tokenEditor] : [];
        }
        if (selector === '[data-autocomplete-dropdown]' || selector === '[data-autocomplete-index]') {
            return this.querySelector('[data-token-editor]')?.querySelectorAll(selector) || [];
        }
        const exactField = selector.match(/^\[data-field="([^"]+)"\]$/);
        if (exactField) return this.querySelectorAll('[data-field]').filter(node => node.dataset.field === exactField[1]);
        if (selector === '[data-plain-criterion],#criterion-min,#criterion-max') return [];
        if (selector === '#criterion-keyword' || selector === '#criterion-keyword,#criterion-value,#criterion-min,#criterion-max') {
            const input = this.querySelector('[data-token-editor]')?.querySelector('#criterion-keyword');
            return input ? [input] : [];
        }
        const tokenSelector = selector.match(/^\[data-(token-operator|token-edit|token-remove)\]$/);
        if (tokenSelector) {
            return this.querySelector('[data-token-editor]')?.querySelectorAll(selector) || [];
        }
        if (selector === 'select') return [];
        if (selector.startsWith('[data-action=')) return [new FakeNode('button')];
        if (selector === '.preview-estimate') {
            if (!this.cache.has(selector)) this.cache.set(selector, [new FakeNode('div')]);
            return this.cache.get(selector);
        }
        if (selector === '.ts-loading') return [new FakeNode('div')];
        if (selector === '.search-form') return this._innerHTML.includes('class="search-form"') ? [new FakeNode('section')] : [];
        return [];
    }
}

class FakeShadowRoot extends FakeNode {
    constructor() { super('#shadow-root'); }
    append(...nodes) { this.children.push(...nodes); }
    querySelectorAll(selector) {
        if (selector === 'style') return this.children.filter(node => node.tagName === 'style');
        if (selector === '.search-form-root') return this.children.filter(node => node.className === 'search-form-root');
        return this.children.find(node => node.className === 'search-form-root')?.querySelectorAll(selector) || [];
    }
}

class FakeHTMLElement extends FakeNode {
    attachShadow() { this.shadowRoot = new FakeShadowRoot(); return this.shadowRoot; }
    dispatchEvent(event) { this.dispatchedEvents ||= []; this.dispatchedEvents.push(event); return true; }
}

const AUTOCOMPLETE_FIELDS = new Set([
    'item_name', 'medicine_name', 'active_ingredient_or_herbal_component',
    'manufacturer', 'scientific_name', 'winning_bidder_name',
    'bid_invitation_code', 'procuring_entity_name'
]);
const AI_PLANNER_ROLES = new Map([
    ['medicine_name', 'text'],
    ['active_ingredient_or_herbal_component', 'text'],
    ['strength', 'text'],
    ['manufacturer', 'text'],
    ['winning_bidder_name', 'text'],
    ['procuring_entity_name', 'text'],
    ['location', 'text'],
    ['result_posted_at', 'date'],
    ['decision_issued_at', 'date']
]);
const field = name => ({ name, type: 'string', filterable: true, autocomplete: AUTOCOMPLETE_FIELDS.has(name), ai_planning: AI_PLANNER_ROLES.has(name), ai_planner_role: AI_PLANNER_ROLES.get(name) });
const contract = {
    groups: {
        goods: { fields: ['item_name', 'unit', 'quantity', 'country_of_origin', 'hs_code', 'model_mark', 'brand', 'production_year', 'manufacturer', 'technical_specification', 'model', 'registration_or_import_permit_number', 'winning_unit_price', 'winning_bidder_id', 'procuring_entity_id', 'bidder_count', 'selection_method'].map(field) },
        medicines: { fields: ['medicine_name', 'active_ingredient_or_herbal_component', 'strength', 'marketing_authorization_or_import_permit', 'route_of_administration', 'dosage_form', 'shelf_life', 'manufacturer', 'production_country', 'packaging', 'unit', 'quantity', 'winning_unit_price', 'winning_bidder_id', 'procuring_entity_id', 'bidder_count', 'medicine_group', 'selection_method'].map(field) },
        traditional: { fields: ['item_name', 'used_part', 'scientific_name', 'origin', 'processing_method', 'registration_or_import_permit_number', 'manufacturer', 'production_country', 'packaging', 'unit', 'quantity', 'winning_unit_price', 'winning_bidder_id', 'procuring_entity_id', 'bidder_count', 'technical_group', 'selection_method'].map(field) }
    }
};

const originalSetTimeout = global.setTimeout;
const originalClearTimeout = global.clearTimeout;
const originalHTMLElement = global.HTMLElement;
const originalDocument = global.document;
const originalWindow = global.window;
const originalFetch = global.fetch;
const originalCustomElements = global.customElements;
const originalCustomEvent = global.CustomEvent;

const scheduled = [];
const autocompleteRequests = [];
const aiPreviewRequests = [];
global.setTimeout = callback => { scheduled.push(callback); return scheduled.length; };
global.clearTimeout = () => {};
global.HTMLElement = FakeHTMLElement;
global.document = { createElement: tagName => tagName === 'div' ? new FakeContentRoot() : new FakeNode(tagName) };
global.window = {
    API_BASE_URL: 'http://test.invalid',
    bidfinderAuthorizedFetch: async (url, options = {}) => {
        if (url.endsWith('/api/search-contract')) return { ok: true, status: 200, json: async () => ({ contract }) };
        if (url.endsWith('/api/autocomplete')) {
            autocompleteRequests.push({ url, options });
            return { ok: true, status: 200, text: async () => JSON.stringify({ data: ['Nefopam hydrochloride', 'Nefopam'] }) };
        }
        if (url.endsWith('/api/ai/search-preview')) {
            aiPreviewRequests.push({ url, options });
            return {
                ok: true,
                status: 200,
                json: async () => ({
                    success: true,
                    status: 'no_match',
                    plan: {
                        version: '1',
                        group: 'medicines',
                        clauses: [{
                            field: 'active_ingredient_or_herbal_component',
                            concepts: [
                                { alternatives: ['clavulanic', 'clavulanat'], match: 'text' },
                                { alternatives: ['amoxicilin', 'amoxicillin'], match: 'text' }
                            ],
                            join: 'AND'
                        }],
                        date_constraints: [],
                        warnings: [],
                        explanation: []
                    },
                    compiled_request: {
                        scope: 'medicine',
                        group: 'medicines',
                        sourceTypes: [],
                        filters: { activeIngredient: { groups: [
                            { alternatives: ['clavulanic', 'clavulanat'] },
                            { alternatives: ['amoxicilin', 'amoxicillin'] }
                        ] } },
                        text: '',
                        searchFields: [],
                        structuredFilters: {},
                        ranges: {},
                        dateRanges: {},
                        exactIdentifiers: {},
                        crossGroupSearch: false,
                        crossGroupSearchFields: []
                    },
                    preview: { total: 0 },
                    optimization: { outcome: 'no_match' },
                    meta: { planner_invoked: false }
                })
            };
        }
        return { ok: true, status: 200, json: async () => ({}) };
    }
};
global.fetch = async () => ({ ok: true, status: 200, json: async () => ({ contract }) });
global.CustomEvent = class CustomEvent { constructor(type, init) { this.type = type; Object.assign(this, init); } };
let FormClass;
global.customElements = { define: (_name, constructor) => { FormClass = constructor; } };

require(path.resolve(__dirname, '../../apps/web/typesense-search-form.js'));

const flush = () => new Promise(resolve => queueMicrotask(() => queueMicrotask(resolve)));

async function run() {
    const form = new FormClass();
    const styleBeforeConnect = form.shadowRoot.querySelector('style');
    assert.ok(styleBeforeConnect, 'style node exists after constructor');
    assert.equal(form.shadowRoot.querySelectorAll('style').length, 1);
    form.connectedCallback();
    await flush();
    await new Promise(resolve => originalSetTimeout(resolve, 0));

    const styleNode = form.shadowRoot.querySelector('style');
    const contentRoot = form.shadowRoot.querySelector('.search-form-root');
    assert.ok(styleNode, 'style node exists after connected/render');
    assert.equal(styleNode, styleBeforeConnect, 'connectedCallback preserves constructor style');
    assert.equal(form.shadowRoot.querySelectorAll('style').length, 1);
    assert.ok(contentRoot.innerHTML.includes('class="search-form"'));
    assert.ok(contentRoot.innerHTML.includes('class="filter-layout"'));
    assert.ok(contentRoot.innerHTML.includes('class="filter-sidebar"'));
    assert.ok(contentRoot.innerHTML.includes('class="filter-content"'));
    assert.ok(contentRoot.innerHTML.includes('class="filter-pane active"'));
    assert.match(contentRoot.innerHTML, /data-action="reset" disabled/, 'reset is disabled without criteria');
    assert.match(contentRoot.innerHTML, /data-action="apply" disabled/, 'search is disabled without criteria');

    const cssText = styleNode.textContent;
    assert.match(cssText, /\.btn-primary:disabled\s*\{[^}]*background:\s*#e3e8ec;/, 'disabled advanced-search action uses a grey state');
    assert.match(cssText, /\.filter-content\s*\{[^}]*padding:\s*12px 20px 18px 14px;/, 'editor keeps right and bottom interaction space');
    const assertStyleSurvives = label => {
        assert.equal(form.shadowRoot.querySelector('style'), styleNode, `${label}: style identity`);
        assert.equal(form.shadowRoot.querySelectorAll('style').length, 1, `${label}: one style node`);
        assert.equal(form.shadowRoot.querySelector('.search-form-root'), contentRoot, `${label}: content root preserved`);
        assert.equal(styleNode.textContent, cssText, `${label}: CSS preserved`);
    };

    const assertLegacyStructure = (label, expectedFields) => {
        assert.ok(contentRoot.innerHTML.includes('category-panel'), `${label}: category panel`);
        assert.ok(contentRoot.innerHTML.includes('condition-panel'), `${label}: condition panel`);
        assert.ok(contentRoot.innerHTML.indexOf('class="field"') < contentRoot.innerHTML.indexOf('class="preview-estimate"'), `${label}: estimate follows editor`);
        assert.ok(contentRoot.innerHTML.indexOf('class="preview-estimate"') < contentRoot.innerHTML.indexOf('class="pane-help"'), `${label}: help follows estimate`);
        assert.ok(contentRoot.innerHTML.indexOf('class="pane-help"') < contentRoot.innerHTML.indexOf('class="editor-actions"'), `${label}: actions follow help`);
        assert.ok(!contentRoot.innerHTML.includes('class="ts-footer"'), `${label}: no full-width footer`);
        assert.ok(contentRoot.innerHTML.includes('class="sidebar-panel-title">Danh mục</div>'), `${label}: category title`);
        assert.ok(contentRoot.innerHTML.includes('class="sidebar-panel-title">Điều kiện</div>'), `${label}: condition title`);
        assert.equal((contentRoot.innerHTML.match(/class="condition-section /g) || []).length, 2, `${label}: two condition sections`);
        assert.ok(contentRoot.innerHTML.includes('Tính chất sản phẩm'), `${label}: product section`);
        assert.ok(contentRoot.innerHTML.includes('Thông tin thầu'), `${label}: tender section`);
        for (const field of expectedFields) assert.match(contentRoot.innerHTML, new RegExp(`data-field="${field}"`), `${label}: field ${field}`);
        for (const instruction of [
            '1. Gõ từ khóa',
            '2. Nhấn Enter để tạo một thẻ từ khóa',
            '3. Nếu có nhiều điều kiện, lặp lại bước 1 và 2',
            '4. Điều chỉnh bằng cách click OR AND NOT để tạo điều kiện',
            '5. Lưu ý vùng <strong>"Điều kiện tìm kiếm"</strong> ở trên cùng để quản lý điều kiện tìm kiếm',
            'Mẹo tìm kiếm'
        ]) assert.ok(contentRoot.innerHTML.includes(instruction), `${label}: instruction ${instruction}`);
        for (const forbidden of ['Nhóm dữ liệu', 'Mã nguồn MSC', 'Loại nguồn', 'Sắp xếp', 'Phân trang']) assert.ok(!contentRoot.innerHTML.includes(forbidden), `${label}: forbidden ${forbidden}`);
        for (const excluded of ['quantity', 'winning_unit_price', 'winning_bidder_id', 'procuring_entity_id', 'bidder_count']) assert.ok(!contentRoot.innerHTML.includes(`data-field="${excluded}"`), `${label}: excluded filter ${excluded}`);
        for (const removed of ['Nhập điều kiện cho biến đang chọn. Chỉ trình soạn thảo này được hiển thị.', '>Giá trị</label>', 'Xóa điều kiện', 'Thêm tiêu chí', 'Chọn biến, nhập điều kiện rồi thêm vào bộ lọc.', 'data-action="clear-criterion"', 'data-action="save-criterion"']) assert.ok(!contentRoot.innerHTML.includes(removed), `${label}: removed ${removed}`);
    };

    const representativeFields = {
        goods: ['item_name', 'selection_method'],
        medicines: ['medicine_name', 'medicine_group'],
        traditional: ['item_name', 'technical_group']
    };
    assertLegacyStructure('initial', representativeFields.medicines);

    form.state.ai.message = 'draft medicine request';
    form.state.ai.plan = { version: '1', group: 'medicines', clauses: [], date_constraints: [], warnings: [], explanation: [] };
    form.state.ai.compiledRequest = { group: 'medicines', filters: { activeIngredient: { groups: [] } } };
    const goodsGroup = contentRoot.querySelectorAll('[data-group]').find(button => button.dataset.group === 'goods');
    goodsGroup.click();
    assert.equal(form.state.group, 'goods', 'group switch changes active dataset');
    assert.equal(form.state.ai.plan, null, 'group switch clears AI interpretation');
    assert.equal(form.state.ai.compiledRequest, null, 'group switch clears compiled AI request');
    assert.equal(form.state.ai.message, 'draft medicine request', 'group switch keeps draft message without reusing plan');
    contentRoot.querySelectorAll('[data-group]').find(button => button.dataset.group === 'medicines').click();

    form.state.activeField = 'active_ingredient_or_herbal_component';
    form.state.criteria = {};
    form.render();
    let autocompleteInput = contentRoot.querySelector('#criterion-keyword');
    assert.ok(contentRoot.querySelector('[data-autocomplete-dropdown]'), 'autocomplete dropdown is rendered for supported text fields');
    autocompleteInput.value = 'nefo';
    autocompleteInput.listeners.input?.();
    const autocompleteTimer = scheduled[scheduled.length - 1];
    assert.equal(typeof autocompleteTimer, 'function', 'autocomplete uses a deferred request');
    autocompleteTimer();
    await flush();
    assert.equal(autocompleteRequests.length, 1, 'typing requests autocomplete through the authorized API seam');
    const autocompletePayload = JSON.parse(autocompleteRequests[0].options.body);
    assert.equal(autocompletePayload.group, null, 'cross-group autocomplete searches all data groups');
    assert.equal(autocompletePayload.scope, 'all');
    assert.deepEqual(autocompletePayload.sourceTypes, []);
    assert.equal(autocompletePayload.field, 'active_ingredient_or_herbal_component');
    assert.deepEqual(autocompletePayload.searchFields, [
        'item_name', 'model_mark', 'brand', 'technical_specification',
        'medicine_name', 'active_ingredient_or_herbal_component'
    ]);
    assert.equal(autocompletePayload.keyword, 'nefo');
    let suggestions = contentRoot.querySelector('[data-autocomplete-dropdown]').querySelectorAll('[data-autocomplete-index]');
    assert.equal(suggestions.length, 2, 'server suggestions are rendered in the dropdown');
    autocompleteInput.keydown('ArrowDown');
    autocompleteInput.keydown('Enter');
    assert.equal(form.state.criteria.active_ingredient_or_herbal_component.tokens[0].value, 'Nefopam hydrochloride', 'Enter selects the active suggestion as a token');

    const longSuggestion = 'Tên thiết bị y tế chuyên dụng dành cho bệnh viện và phòng khám - máy điện tim - phiên bản màn hình màu cảm ứng độ phân giải cao';
    form.renderAutocompleteSuggestions([longSuggestion], 'máy điện tim', form.shadowRoot);
    const longSuggestionNode = contentRoot.querySelector('[data-autocomplete-dropdown]').querySelectorAll('[data-autocomplete-index]')[0];
    assert.ok(longSuggestionNode.innerHTML.startsWith('...'), 'long suggestion keeps leading context marker');
    assert.ok(longSuggestionNode.innerHTML.includes('máy điện tim'), 'long suggestion keeps the searched phrase');
    assert.ok(longSuggestionNode.innerHTML.endsWith('...'), 'long suggestion keeps trailing context marker');
    assert.equal(longSuggestionNode.dataset.autocompleteValue, longSuggestion, 'full suggestion remains selectable');

    form.state.group = 'goods';
    form.state.activeField = 'item_name';
    form.state.criteria = { item_name: { kind: 'tokens', tokens: [{ value: '\u006d\u00e1y \u0111i\u1ec7n', op: 'OR' }] } };
    const phrasePayload = form.collectFilterPayload();
    assert.equal(phrasePayload.text, '\"\u006d\u00e1y \u0111i\u1ec7n\"', 'multi-word field tokens are sent as an exact phrase');
    assert.deepEqual(phrasePayload.searchFields, ['item_name', 'model_mark', 'brand', 'technical_specification'], 'goods phrase uses the shared four-column search scope');
    assert.equal(phrasePayload.filters.goodsKeyword, undefined, 'phrase is not downgraded to a word-level legacy filter');

    form.state.group = 'medicines';
    form.state.activeField = 'medicine_name';
    form.state.criteria = { medicine_name: { kind: 'tokens', tokens: [{ value: 'paracetamol', op: 'OR' }] } };
    const medicineCrossPayload = form.collectFilterPayload();
    assert.equal(medicineCrossPayload.scope, 'all');
    assert.equal(medicineCrossPayload.group, null);
    assert.deepEqual(medicineCrossPayload.sourceTypes, []);
    assert.deepEqual(medicineCrossPayload.crossGroupSearchFields, ['medicine_name']);
    assert.equal(medicineCrossPayload.filters.crossGroupProductKeyword.tokens[0].value, 'paracetamol');

    form.state.group = 'traditional';
    form.state.activeField = 'item_name';
    form.state.criteria = { item_name: { kind: 'tokens', tokens: [{ value: 'bạch linh', op: 'OR' }] } };
    const traditionalCrossPayload = form.collectFilterPayload();
    assert.equal(traditionalCrossPayload.scope, 'all');
    assert.equal(traditionalCrossPayload.group, null);
    assert.equal(traditionalCrossPayload.text, '"bạch linh"');
    assert.deepEqual(traditionalCrossPayload.crossGroupSearchFields, ['item_name']);
    assert.deepEqual(traditionalCrossPayload.searchFields, [
        'item_name', 'model_mark', 'brand', 'technical_specification',
        'medicine_name', 'active_ingredient_or_herbal_component'
    ]);

    form.state.group = 'medicines';
    form.state.activeField = 'active_ingredient_or_herbal_component';
    form.state.criteria = {};
    form.render();

    form.state.criteria.medicine_group = { kind: 'values', values: ['N1'] };
    form.render();
    assert.doesNotMatch(contentRoot.innerHTML, /data-action="reset" disabled/, 'reset enables when criteria exist');
    assert.doesNotMatch(contentRoot.innerHTML, /data-action="apply" disabled/, 'search enables when criteria exist');
    form.state.criteria = {};
    form.render();
    form.setPreviewResult({ total: 9596715, totalLabel: '9596715', exact: true });
    assert.equal(form.shadowRoot.querySelector('.preview-estimate').textContent, 'Có 100+ kết quả');
    form.setPreviewResult({ total: 37, totalLabel: '37', exact: true });
    assert.equal(form.shadowRoot.querySelector('.preview-estimate').textContent, 'Có 37 kết quả');
    form.setPreviewResult({ total: 0, totalLabel: '0', exact: true });
    assert.equal(form.shadowRoot.querySelector('.preview-estimate').textContent, 'Có 0 kết quả');
    assert.ok(form.shadowRoot.querySelector('.preview-estimate').classList.values.has('zero-result'), 'zero estimate has warning class');

    const clickGroup = (index, label, expectedGroup) => {
        const previewsBefore = scheduled.length;
        const group = contentRoot.querySelectorAll('[data-group]')[index];
        assert.ok(group, `${label}: group exists`);
        group.click();
        assertStyleSurvives(label);
        assert.equal(form.state.group, expectedGroup, `${label}: state group`);
        assert.equal(contentRoot.querySelectorAll('[data-group]').length, 3, `${label}: three groups`);
        assert.match(contentRoot.innerHTML, new RegExp(`class="sidebar-item group-choice active"[^>]*data-group="${expectedGroup}"`), `${label}: active group style`);
        assert.ok(contentRoot.innerHTML.includes('class="filter-sidebar"'), `${label}: sidebar retained`);
        assertLegacyStructure(label, representativeFields[expectedGroup]);
        assert.equal(scheduled.length, previewsBefore, `${label}: group switch does not request preview`);
        assert.ok(!(form.dispatchedEvents || []).some(event => event.type === 'dataset-group-change'), `${label}: group switch stays inside modal`);
    };

    clickGroup(0, 'Hàng hóa', 'goods');
    clickGroup(1, 'Thuốc', 'medicines');
    clickGroup(2, 'Dược liệu', 'traditional');

    assert.equal(form.dropdownOptions('technical_group').length, 7, 'traditional TCKT uses the medicine group option set');
    const technicalDropdown = form.renderDropdownControl('technical_group', { kind: 'values', values: ['N1'] });
    assert.doesNotMatch(technicalDropdown, /data-dropdown-apply|data-dropdown-cancel|>OK<|>Hủy</, 'dropdown applies selections without OK/Hủy actions');
    assert.match(technicalDropdown, /data-dropdown-option="technical_group"/, 'TCKT keeps multi-select checkbox options');
    assert.equal(form.optionLabel('medicine_group', 'UNKNOWN'), 'Chưa xác định được', 'unmapped medicine groups use the new label');
    assert.equal(form.optionLabel('technical_group', 'UNKNOWN'), 'Chưa xác định được', 'unmapped traditional groups use the new label');
    assert.equal(form.optionLabel('selection_method', 'DTRR'), 'Đấu thầu rộng rãi', 'selection method codes use the legacy display label');
    assert.equal(form.optionLabel('selection_method', 'LCNT_DB'), 'Đấu thầu rộng rãi', 'new selection method code uses the same legacy label');
    assert.equal(form.parseVietnameseDate('31/12/2025'), '2025-12-31', 'manual dates use Vietnamese day/month/year input');
    assert.equal(form.formatVietnameseDate('2025-12-31'), '31/12/2025', 'date picker values display in Vietnamese format');
    assert.match(form.renderDateRangeControl('result_posted_at', { kind: 'date-range', from: '2025-01-01', to: '2025-12-31' }), /placeholder="dd\/mm\/yyyy"/g, 'date editor is a range with Vietnamese placeholders');
    form.state.criteria.technical_group = { kind: 'values', values: ['N1'] };
    assert.deepEqual(form.collectFilterPayload().filters.drugGroup, ['N1'], 'traditional TCKT reuses the cleaned group payload');
    form.state.criteria.result_posted_at = { kind: 'date-range', from: '2025-01-01', to: '2025-12-31' };
    assert.deepEqual(form.collectFilterPayload().dateRanges.result_posted_at, { from: '2025-01-01', to: '2025-12-31' }, 'date range reaches the existing payload contract');
    delete form.state.criteria.technical_group;
    delete form.state.criteria.result_posted_at;

    const variable = contentRoot.querySelectorAll('[data-field]')[0];
    assert.ok(variable, 'selected variable exists');
    variable.click();
    assertStyleSurvives('selected variable');
    assertLegacyStructure('selected variable', representativeFields.traditional);

    form.setPreviewResult({ total: 37, totalLabel: '37', exact: true });
    const previewBeforeVariableSwitch = contentRoot.querySelector('.preview-estimate').textContent;
    const scheduledBeforeVariableSwitch = scheduled.length;
    contentRoot.querySelector('[data-field="used_part"]').click();
    assert.equal(contentRoot.querySelector('.preview-estimate').textContent, previewBeforeVariableSwitch, 'switching variables preserves the current preview estimate');
    assert.equal(scheduled.length, scheduledBeforeVariableSwitch, 'switching variables does not schedule a new preview');
    contentRoot.querySelector('[data-field="item_name"]').click();
    assert.equal(contentRoot.querySelector('.preview-estimate').textContent, previewBeforeVariableSwitch, 'returning to a variable preserves the current preview estimate');

    const renderCountBeforeTokens = contentRoot.renderCount;
    let keyword = contentRoot.querySelector('#criterion-keyword');
    keyword.value = 'Cam thảo';
    keyword.keydown('Enter');
    assert.equal(form.state.criteria.item_name.tokens.length, 1, 'Enter creates first keyword chip');
    assert.equal(contentRoot.renderCount, renderCountBeforeTokens, 'Enter does not rerender the whole component');
    assert.match(contentRoot.querySelector('[data-token-editor]').innerHTML, /class="token-tag"/, 'first chip rendered');
    assert.match(form.renderSummary(), /data-chip-field="item_name"/, 'criterion appears in summary');
    assert.equal(form.shadowRoot.querySelector('.preview-estimate').textContent, 'Đang ước tính...', 'preview loading state appears immediately');

    keyword = contentRoot.querySelector('#criterion-keyword');
    keyword.value = 'Đương quy';
    keyword.keydown('Enter');
    assert.equal(form.state.criteria.item_name.tokens.length, 2, 'second Enter creates second chip');
    assert.equal(contentRoot.renderCount, renderCountBeforeTokens, 'second Enter still avoids full rerender');
    assert.match(contentRoot.querySelector('[data-token-editor]').innerHTML, /class="token-operator"[^>]*>OR<\/button>/, 'legacy OR operator rendered');

    contentRoot.querySelectorAll('[data-token-operator]')[0].click();
    assert.equal(form.state.criteria.item_name.tokens[1].op, 'AND', 'operator cycles OR to AND');
    assert.equal(form.collectFilterPayload().filters.crossGroupProductKeyword.tokens[1].op, 'AND', 'AND reaches the cross-group token payload');
    contentRoot.querySelectorAll('[data-token-operator]')[0].click();
    assert.equal(form.state.criteria.item_name.tokens[1].op, 'NOT', 'operator cycles AND to NOT');
    assert.equal(form.collectFilterPayload().filters.crossGroupProductKeyword.tokens[1].op, 'NOT', 'NOT reaches the cross-group token payload');
    assert.match(form.renderSummary(), /\(NOT\)/, 'summary reflects token operator');

    contentRoot.querySelectorAll('[data-token-edit]')[1].click();
    assert.equal(contentRoot.querySelector('#criterion-keyword').value, 'Đương quy', 'existing token can be edited');
    assert.equal(form.state.criteria.item_name.tokens.length, 1, 'editing moves token back to input');
    assertStyleSurvives('token re-render');

    contentRoot.querySelectorAll('[data-field]')[1].click();
    const summaryCriterion = contentRoot.querySelectorAll('[data-chip-field]').find(node => node.dataset.chipField === 'item_name');
    assert.ok(summaryCriterion, 'existing summary criterion is selectable');
    summaryCriterion.click();
    assert.equal(form.state.activeField, 'item_name', 'summary criterion reopens its editor');

    const renderCountBeforeSubmit = contentRoot.renderCount;
    form.submit();
    assert.equal(contentRoot.renderCount, renderCountBeforeSubmit, 'apply does not rerender the whole component');
    assert.ok(form.dispatchedEvents.some(event => event.type === 'apply-filters'), 'apply event dispatched without page reload');

    form.state.group = 'medicines';
    form.state.ai.message = 'clavulanic và amoxicillin';
    await form.requestAiPreview();
    assert.equal(aiPreviewRequests.length, 1, 'initial AI preview uses the authorized API seam');
    const initialAiPayload = JSON.parse(aiPreviewRequests[0].options.body);
    assert.deepEqual(initialAiPayload, { group: 'medicines', message: 'clavulanic và amoxicillin' }, 'initial AI preview sends group and message');
    assert.equal(form.state.ai.preview.total, 0, 'captured no-match preview is accepted');
    assert.ok(form.state.ai.plan, 'no-match keeps the interpretation editable');

    form.updateAiConceptAlternatives(0, 0, 'clavulanic | clavulanat');
    assert.equal(form.state.ai.dirty, true, 'editing an interpretation marks it dirty');
    await form.requestAiPreview({ plan: form.state.ai.plan });
    assert.equal(aiPreviewRequests.length, 2, 'edited preview makes one deterministic request');
    const editedAiPayload = JSON.parse(aiPreviewRequests[1].options.body);
    assert.equal(editedAiPayload.group, 'medicines');
    assert.equal(editedAiPayload.message, undefined, 'edited preview does not send the natural-language message');
    assert.deepEqual(editedAiPayload.plan.clauses[0].concepts, [
        { alternatives: ['clavulanic', 'clavulanat'], match: 'text' },
        { alternatives: ['amoxicilin', 'amoxicillin'], match: 'text' }
    ], 'edited plan preserves independent AND concepts and OR alternatives');
    assert.deepEqual(form.state.ai.compiledRequest.filters.activeIngredient.groups, [
        { alternatives: ['clavulanic', 'clavulanat'] },
        { alternatives: ['amoxicilin', 'amoxicillin'] }
    ], 'compiled grouped Boolean request remains intact');

    form.executeAiSearch();
    const executedAiEvent = form.dispatchedEvents.at(-1);
    assert.equal(executedAiEvent.type, 'apply-filters', 'AI execution reuses the existing apply-filters event');
    assert.equal(executedAiEvent.detail, form.state.ai.compiledRequest, 'execution dispatches the exact backend compiled request');
    assert.deepEqual(executedAiEvent.detail.filters.activeIngredient.groups, form.state.ai.compiledRequest.filters.activeIngredient.groups, 'execution does not reconstruct through legacy flat tokens');
    form.updateAiConceptField(0, 1, 'strength');
    assert.equal(form.state.ai.plan.clauses[0].concepts.length, 1, 'reassigning one concept does not move its sibling');
    assert.equal(form.state.ai.plan.clauses[1].field, 'strength', 'reassigned concept becomes its own compatible-role clause');

    const buttons = [...contentRoot.innerHTML.matchAll(/<button\b[^>]*>/g)].map(match => match[0]);
    assert.ok(buttons.length > 0, 'component has controls');
    assert.ok(buttons.every(button => /class="[^"]*(sidebar-item|btn|pane-help-link|chip-select|chip-remove|token-operator|tag-text|token-remove|ai-condition-remove)[^"]*"/.test(button)), 'no raw button cloud');
    assert.match(contentRoot.innerHTML, /class="sidebar-item group-choice active"/);
    assert.match(contentRoot.innerHTML, /class="sidebar-item [^"]*active[^"]*" data-field=/);
    assert.equal(form.shadowRoot.children[0], styleNode, 'style is persistent shadow child');
    assert.equal(form.shadowRoot.children[1], contentRoot, 'content root is second shadow child');
    assert.ok(scheduled.length >= 3, 'previews scheduled without replacing shadow root');
}

run().finally(() => {
    global.setTimeout = originalSetTimeout;
    global.clearTimeout = originalClearTimeout;
    global.HTMLElement = originalHTMLElement;
    global.document = originalDocument;
    global.window = originalWindow;
    global.fetch = originalFetch;
    global.customElements = originalCustomElements;
    global.CustomEvent = originalCustomEvent;
}).catch(error => {
    console.error(error);
    process.exitCode = 1;
});
