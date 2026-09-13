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
        assert.ok(!contentRoot.innerHTML.includes('ai-search-panel'), `${label}: embedded AI panel removed`);
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

    const goodsGroup = contentRoot.querySelectorAll('[data-group]').find(button => button.dataset.group === 'goods');
    goodsGroup.click();
    assert.equal(form.state.group, 'goods', 'group switch changes active dataset');
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

    const buttons = [...contentRoot.innerHTML.matchAll(/<button\b[^>]*>/g)].map(match => match[0]);
    assert.ok(buttons.length > 0, 'component has controls');
    assert.ok(buttons.every(button => /class="[^"]*(sidebar-item|btn|pane-help-link|chip-select|chip-remove|token-operator|tag-text|token-remove|ai-condition-remove)[^"]*"/.test(button)), 'no raw button cloud');
    assert.match(contentRoot.innerHTML, /class="sidebar-item group-choice active"/);
    assert.match(contentRoot.innerHTML, /class="sidebar-item [^"]*active[^"]*" data-field=/);
    assert.equal(form.shadowRoot.children[0], styleNode, 'style is persistent shadow child');
    assert.equal(form.shadowRoot.children[1], contentRoot, 'content root is second shadow child');
    assert.ok(scheduled.length >= 2, 'previews scheduled without replacing shadow root');
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
