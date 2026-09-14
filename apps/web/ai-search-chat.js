(function () {
    'use strict';

    const GROUPS = {
        goods: 'Hàng hóa',
        medicines: 'Thuốc',
        traditional: 'Dược liệu'
    };
    const STORAGE_KEY = 'bidfinder.ai-search-chat.v1';
    const HISTORY_LIMIT = 20;
    const REQUEST_TIMEOUT_MS = 35000;
    const COMPILED_REQUEST_MARKER = '__bidfinderPreserveCompiledRequest';
    const FALLBACK_FIELD_LABELS = {
        goods: {},
        medicines: {},
        traditional: {}
    };
    const state = {
        open: false,
        group: 'medicines',
        history: loadHistory(),
        usage: null,
        usageStatus: 'loading',
        usageRequestId: 0,
        contract: null,
        editingId: null,
        editPlan: null,
        controller: null,
        notice: ''
    };

    const openButton = document.getElementById('open-ai-search');
    const panel = document.getElementById('ai-search-chat');
    const messagesRoot = document.getElementById('ai-chat-messages');
    const composer = document.getElementById('ai-chat-composer');
    const input = document.getElementById('ai-chat-input');
    const usageRoot = document.getElementById('ai-chat-usage');
    const groupsRoot = document.getElementById('ai-chat-groups');

    if (!openButton || !panel || !messagesRoot || !composer || !input) return;

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function clone(value) {
        if (typeof structuredClone === 'function') return structuredClone(value);
        return JSON.parse(JSON.stringify(value));
    }

    function loadHistory() {
        try {
            const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
            return Array.isArray(parsed)
                ? parsed.filter(item => item && item.assistant && !item.assistant.loading).slice(-HISTORY_LIMIT)
                : [];
        } catch (_) {
            return [];
        }
    }

    function saveHistory() {
        try {
            const completed = state.history
                .filter(item => item && item.assistant && !item.assistant.loading)
                .slice(-HISTORY_LIMIT);
            localStorage.setItem(STORAGE_KEY, JSON.stringify(completed));
        } catch (_) {
            // Local history is an enhancement; search must still work when storage is unavailable.
        }
    }

    function apiBaseUrl() {
        return String(window.API_BASE_URL || '').replace(/\/$/, '');
    }

    function requestWithTimeout(options = {}) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
        state.controller = controller;
        return { ...options, signal: controller.signal, timeout };
    }

    async function fetchJson(path, options = {}) {
        const fetcher = window.bidfinderAuthorizedFetch || window.fetch.bind(window);
        const request = requestWithTimeout(options);
        try {
            const response = await fetcher(`${apiBaseUrl()}${path}`, request);
            let payload = {};
            try { payload = await response.json(); } catch (_) { payload = {}; }
            return { response, payload };
        } finally {
            clearTimeout(request.timeout);
            if (state.controller?.signal === request.signal) state.controller = null;
        }
    }

    function fieldLabels(group) {
        return window.BIDFinderDataColumns?.labels?.[group] || FALLBACK_FIELD_LABELS[group] || {};
    }

    function fieldLabel(group, field) {
        return fieldLabels(group)[field] || field || 'Điều kiện';
    }

    function formatCount(value) {
        const total = Number(value);
        return Number.isFinite(total) ? total.toLocaleString('vi-VN') : '0';
    }

    function usageFromPayload(payload) {
        const usage = payload?.ai_usage;
        if (!usage || usage.period !== 'daily' || !Number.isFinite(Number(usage.remaining_percent))) return null;
        return usage;
    }

    function renderUsage() {
        if (state.usageStatus === 'loading') {
            usageRoot.innerHTML = '<span class="ai-chat-usage-skeleton" aria-hidden="true"></span><span class="sr-only">Đang tải hạn mức AI</span>';
            return;
        }
        if (state.usageStatus !== 'available' || !state.usage) {
            usageRoot.replaceChildren();
            return;
        }
        const usage = state.usage;
        const remaining = Number.isFinite(Number(usage.remaining_percent))
            ? Math.max(0, Math.min(100, Number(usage.remaining_percent)))
            : 0;
        usageRoot.textContent = `${remaining}% còn lại`;
    }

    function updateUsage(payload) {
        const usage = usageFromPayload(payload);
        if (!usage) return false;
        state.usage = usage;
        state.usageStatus = 'available';
        return true;
    }

    async function loadUsage() {
        const requestId = ++state.usageRequestId;
        state.usage = null;
        state.usageStatus = 'loading';
        renderUsage();
        const loadingTimer = window.setTimeout(() => {
            if (state.usageRequestId !== requestId || state.usageStatus !== 'loading') return;
            state.usage = null;
            state.usageStatus = 'unavailable';
            renderUsage();
        }, 1200);
        try {
            const { response, payload } = await fetchJson('/api/ai/usage');
            if (state.usageRequestId !== requestId) return;
            if (response.ok && payload?.success && updateUsage(payload)) {
                renderUsage();
                return;
            }
            if (state.usageStatus !== 'loading') return;
            state.usage = null;
            state.usageStatus = 'unavailable';
            renderUsage();
        } catch (_) {
            if (state.usageRequestId !== requestId || state.usageStatus !== 'loading') return;
            state.usage = null;
            state.usageStatus = 'unavailable';
            renderUsage();
        } finally {
            window.clearTimeout(loadingTimer);
        }
    }

    async function loadContract() {
        if (state.contract) return state.contract;
        try {
            if (window.BIDFinderSearchContractPromise) {
                state.contract = await window.BIDFinderSearchContractPromise;
            } else {
                const { response, payload } = await fetchJson('/api/search-contract');
                if (response.ok && payload?.success) state.contract = payload.contract || payload;
            }
        } catch (_) {
            state.contract = null;
        }
        return state.contract;
    }

    function planConditions(group, plan) {
        const rows = [];
        (plan?.clauses || []).forEach(clause => {
            const values = (clause.concepts || []).map(concept =>
                (concept.alternatives || []).map(value => escapeHtml(value)).join(' / ')
            ).filter(Boolean);
            if (values.length) rows.push(`<li><strong>${escapeHtml(fieldLabel(group, clause.field))}</strong><span>${values.join('<br>')}</span></li>`);
        });
        (plan?.date_constraints || []).forEach(constraint => {
            const period = constraint.period || {};
            const unit = { days: 'ngày', months: 'tháng', years: 'năm' }[period.unit] || period.unit || '';
            const direction = period.direction === 'current' ? 'hiện tại' : 'gần nhất';
            rows.push(`<li><strong>${escapeHtml(fieldLabel(group, constraint.field))}</strong><span>${escapeHtml(`${period.amount || ''} ${unit} ${direction}`.trim())}</span></li>`);
        });
        return rows.length ? `<ul class="ai-chat-conditions">${rows.join('')}</ul>` : '<p class="ai-chat-muted">Chưa có điều kiện cụ thể.</p>';
    }

    function editPlanMarkup(item) {
        const plan = state.editPlan || item.assistant?.plan || {};
        const rows = [];
        (plan.clauses || []).forEach((clause, clauseIndex) => {
            (clause.concepts || []).forEach((concept, conceptIndex) => {
                rows.push(`<label class="ai-chat-edit-row"><span>${escapeHtml(fieldLabel(item.group, clause.field))}</span><input type="text" data-ai-chat-edit-alternatives data-clause="${clauseIndex}" data-concept="${conceptIndex}" value="${escapeHtml((concept.alternatives || []).join(' | '))}" title="Dùng | để tách lựa chọn OR"></label>`);
            });
        });
        (plan.date_constraints || []).forEach((constraint, index) => {
            const period = constraint.period || {};
            rows.push(`<div class="ai-chat-edit-row ai-chat-edit-date"><span>${escapeHtml(fieldLabel(item.group, constraint.field))}</span><div><input type="number" min="1" max="120" data-ai-chat-edit-date-amount="${index}" value="${escapeHtml(period.amount)}" aria-label="Số lượng thời gian"><select data-ai-chat-edit-date-unit="${index}" aria-label="Đơn vị thời gian">${[['days', 'ngày'], ['months', 'tháng'], ['years', 'năm']].map(([value, label]) => `<option value="${value}" ${period.unit === value ? 'selected' : ''}>${label}</option>`).join('')}</select><select data-ai-chat-edit-date-direction="${index}" aria-label="Khoảng thời gian"><option value="previous" ${period.direction === 'previous' ? 'selected' : ''}>gần nhất</option><option value="current" ${period.direction === 'current' ? 'selected' : ''}>hiện tại</option></select></div></div>`);
        });
        return `<div class="ai-chat-edit-box" data-ai-chat-edit-box="${escapeHtml(item.id)}">${rows.join('') || '<p class="ai-chat-muted">Không có điều kiện để chỉnh sửa.</p>'}<div class="ai-chat-actions"><button type="button" class="ai-chat-button secondary" data-ai-chat-action="cancel-edit">Hủy</button><button type="button" class="ai-chat-button primary" data-ai-chat-action="save-edit" data-id="${escapeHtml(item.id)}">Lưu</button></div></div>`;
    }

    function assistantMarkup(item) {
        const assistant = item.assistant || {};
        if (assistant.loading) return '<div class="ai-chat-loading" role="status" aria-live="polite"><span class="ai-chat-dots" aria-hidden="true"></span><span class="sr-only">Đang phân tích yêu cầu…</span></div>';
        if (assistant.error) return `<div class="ai-chat-error" role="alert">${escapeHtml(assistant.error)}</div>`;
        const total = Number(assistant.preview?.total);
        const resultLine = Number.isFinite(total) && total > 0
            ? `${formatCount(total)} kết quả`
            : 'Không có kết quả';
        const warningMarkup = (assistant.plan?.warnings || []).length
            ? `<div class="ai-chat-warning">${assistant.plan.warnings.map(warning => escapeHtml(warning)).join('<br>')}</div>`
            : '';
        const broadening = assistant.optimization?.outcome === 'matched_after_safe_broadening'
            ? '<p class="ai-chat-muted">Đã mở rộng an toàn phạm vi sản phẩm để tìm kết quả.</p>'
            : '';
        const isEditing = state.editingId === item.id;
        const actions = isEditing
            ? editPlanMarkup(item)
            : `<div class="ai-chat-actions"><button type="button" class="ai-chat-button primary" data-ai-chat-action="execute" data-id="${escapeHtml(item.id)}" ${assistant.executing ? 'disabled' : ''}>${assistant.executing ? 'Đang tải…' : 'Xem kết quả'}</button><button type="button" class="ai-chat-icon-button ai-chat-edit-button" data-ai-chat-action="edit" data-id="${escapeHtml(item.id)}" aria-label="Chỉnh sửa" title="Chỉnh sửa"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 17.5V20h2.5L18.9 7.6l-2.5-2.5L4 17.5zM15 6l2.5 2.5M13.5 20H20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></button></div>`;
        return `<div class="ai-chat-plan"><p class="ai-chat-result" role="status">${escapeHtml(resultLine)}</p>${planConditions(item.group, assistant.plan)}${warningMarkup}${broadening}${actions}</div>`;
    }

    function renderMessages() {
        const items = state.history;
        const wasAtBottom = messagesRoot.scrollHeight - messagesRoot.scrollTop - messagesRoot.clientHeight < 48;
        const previousLastId = messagesRoot.lastElementChild?.dataset.id;
        if (!items.length) {
            messagesRoot.innerHTML = '<div class="ai-chat-welcome"><span class="ai-chat-welcome-icon" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><path d="M12 2l1.7 6.3L20 10l-6.3 1.7L12 18l-1.7-6.3L4 10l6.3-1.7L12 2zm7 13l.7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7L19 15z" fill="currentColor"/></svg></span><p>Bạn muốn tìm gì?</p></div>';
        } else {
            messagesRoot.innerHTML = items.map(item => `<article class="ai-chat-exchange" data-id="${escapeHtml(item.id)}"><div class="ai-chat-message user">${escapeHtml(item.message)}</div><div class="ai-chat-assistant-row"><span class="ai-chat-avatar ai-chat-avatar-small" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><path d="M12 2l1.7 6.3L20 10l-6.3 1.7L12 18l-1.7-6.3L4 10l6.3-1.7L12 2zm7 13l.7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7L19 15z" fill="currentColor"/></svg></span><div class="ai-chat-message assistant">${assistantMarkup(item)}</div></div></article>`).join('');
        }
        const latestChanged = items.at(-1)?.id !== previousLastId;
        if (latestChanged || wasAtBottom) messagesRoot.scrollTop = messagesRoot.scrollHeight;
        renderUsage();
        openButton.setAttribute('aria-expanded', String(state.open));
        groupsRoot.querySelectorAll('[data-ai-chat-group]').forEach(button => {
            const active = button.dataset.aiChatGroup === state.group;
            button.setAttribute('aria-pressed', String(active));
            button.classList.toggle('active', active);
        });
    }

    function setOpen(open) {
        const wasOpen = state.open;
        state.open = Boolean(open);
        panel.hidden = !state.open;
        panel.classList.toggle('open', state.open);
        openButton.setAttribute('aria-expanded', String(state.open));
        openButton.classList.toggle('is-open', state.open);
        if (state.open) {
            loadUsage();
            loadContract();
            window.setTimeout(() => input.focus(), 0);
        } else if (wasOpen) {
            openButton.focus();
        }
    }

    function resizeInput() {
        input.style.height = 'auto';
        const maxHeight = 112;
        const height = Math.min(input.scrollHeight, maxHeight);
        input.style.height = `${height}px`;
        input.style.overflowY = input.scrollHeight > maxHeight ? 'auto' : 'hidden';
    }

    function findItem(id) {
        return state.history.find(item => item.id === id);
    }

    function setError(item, message) {
        if (!item) return;
        item.assistant = { ...(item.assistant || {}), loading: false, executing: false, error: message };
        saveHistory();
        renderMessages();
    }

    function publicError(payload, status, timedOut) {
        if (payload?.error === 'ai_daily_usage_exhausted') return 'Bạn đã dùng hết AI hôm nay.';
        if (timedOut) return 'AI phản hồi quá lâu. Thử lại.';
        if (status === 429) return 'AI đang quá tải. Thử lại sau.';
        if (status >= 500) return 'AI đang tạm thời không khả dụng.';
        return payload?.message || 'Không thể xử lý yêu cầu AI.';
    }

    async function sendMessage() {
        const message = String(input.value || '').trim();
        if (!message) return;
        if (state.usage && Number(state.usage.remaining_percent) <= 0) {
            const item = { id: `ai-${Date.now()}-${Math.random().toString(36).slice(2)}`, group: state.group, message, assistant: { error: 'Bạn đã dùng hết AI hôm nay.' } };
            state.history.push(item);
            state.history = state.history.slice(-HISTORY_LIMIT);
            input.value = '';
            resizeInput();
            saveHistory();
            renderMessages();
            return;
        }
        const item = { id: `ai-${Date.now()}-${Math.random().toString(36).slice(2)}`, group: state.group, message, assistant: { loading: true } };
        state.history.push(item);
        state.history = state.history.slice(-HISTORY_LIMIT);
        input.value = '';
        resizeInput();
        renderMessages();
        try {
            const { response, payload } = await fetchJson('/api/ai/search-preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ group: item.group, message: item.message })
            });
            if (!response.ok || payload?.success === false) {
                updateUsage(payload);
                setError(item, publicError(payload, response.status, false));
                return;
            }
            if (!payload?.plan || !payload?.compiled_request) {
                setError(item, 'AI trả về dữ liệu không hợp lệ. Thử lại.');
                return;
            }
            item.assistant = {
                loading: false,
                executing: false,
                error: '',
                plan: payload.plan,
                compiled_request: payload.compiled_request,
                preview: payload.preview || { total: 0 },
                optimization: payload.optimization || null
            };
            updateUsage(payload);
            saveHistory();
            renderMessages();
        } catch (error) {
            setError(item, publicError({}, 0, error?.name === 'AbortError'));
        }
    }

    function collectEditedPlan(item) {
        const plan = clone(state.editPlan || item.assistant?.plan);
        if (!plan) return null;
        let invalid = false;
        document.querySelectorAll('[data-ai-chat-edit-alternatives]').forEach(inputElement => {
            const alternatives = String(inputElement.value || '').split('|').map(value => value.trim()).filter(Boolean);
            if (!alternatives.length) invalid = true;
            const clause = plan.clauses?.[Number(inputElement.dataset.clause)];
            const concept = clause?.concepts?.[Number(inputElement.dataset.concept)];
            if (concept) concept.alternatives = alternatives;
        });
        document.querySelectorAll('[data-ai-chat-edit-date-amount]').forEach(inputElement => {
            const index = Number(inputElement.dataset.aiChatEditDateAmount);
            const constraint = plan.date_constraints?.[index];
            if (!constraint) return;
            const amount = Number(inputElement.value);
            const unit = document.querySelector(`[data-ai-chat-edit-date-unit="${index}"]`)?.value;
            const direction = document.querySelector(`[data-ai-chat-edit-date-direction="${index}"]`)?.value;
            if (!Number.isInteger(amount) || amount < 1 || amount > 120) invalid = true;
            constraint.period = { kind: 'relative', amount, unit, direction };
        });
        if (invalid) throw new Error('Mỗi điều kiện cần ít nhất một giá trị hợp lệ.');
        return plan;
    }

    async function saveEditedPlan(id) {
        const item = findItem(id);
        if (!item || !state.editPlan) return;
        let plan;
        try {
            plan = collectEditedPlan(item);
        } catch (error) {
            item.assistant.error = error.message;
            renderMessages();
            return;
        }
        item.assistant = { ...item.assistant, loading: true, error: '' };
        renderMessages();
        try {
            const { response, payload } = await fetchJson('/api/ai/search-preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ group: item.group, plan })
            });
            if (!response.ok || payload?.success === false) {
                item.assistant = { ...item.assistant, loading: false, error: publicError(payload, response.status, false) };
                updateUsage(payload);
            } else {
                item.assistant = { loading: false, executing: false, error: '', plan: payload.plan, compiled_request: payload.compiled_request, preview: payload.preview || { total: 0 }, optimization: payload.optimization || null };
                updateUsage(payload);
                state.editingId = null;
                state.editPlan = null;
                saveHistory();
            }
            renderMessages();
        } catch (error) {
            item.assistant = { ...item.assistant, loading: false, error: publicError({}, 0, error?.name === 'AbortError') };
            renderMessages();
        }
    }

    function executeSearch(id) {
        const item = findItem(id);
        const compiled = item?.assistant?.compiled_request;
        if (!item || !compiled || item.assistant.loading || item.assistant.executing) return;
        const request = clone(compiled);
        Object.defineProperty(request, COMPILED_REQUEST_MARKER, { value: true, enumerable: false, configurable: true });
        item.assistant.executing = true;
        item.assistant.error = '';
        renderMessages();
        const form = document.querySelector('typesense-search-form');
        if (!form) {
            setError(item, 'Không thể mở kết quả tìm kiếm.');
            return;
        }
        const finish = () => {
            item.assistant.executing = false;
            renderMessages();
        };
        document.addEventListener('bidfinder:query-result', finish, { once: true });
        document.addEventListener('bidfinder:query-error', finish, { once: true });
        form.dispatchEvent(new CustomEvent('apply-filters', { detail: request, bubbles: true, composed: true }));
    }

    function startEdit(id) {
        const item = findItem(id);
        if (!item?.assistant?.plan || item.assistant.loading) return;
        state.editingId = id;
        state.editPlan = clone(item.assistant.plan);
        renderMessages();
    }

    composer.addEventListener('submit', event => {
        event.preventDefault();
        sendMessage();
    });
    input.addEventListener('input', resizeInput);
    input.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            composer.requestSubmit();
        }
    });
    openButton.addEventListener('click', () => setOpen(!state.open));
    panel.querySelector('[data-ai-chat-close]')?.addEventListener('click', () => setOpen(false));
    groupsRoot.addEventListener('click', event => {
        const button = event.target.closest('[data-ai-chat-group]');
        if (!button) return;
        state.group = button.dataset.aiChatGroup;
        state.editingId = null;
        state.editPlan = null;
        renderMessages();
    });
    messagesRoot.addEventListener('click', event => {
        const action = event.target.closest('[data-ai-chat-action]');
        if (!action) return;
        const name = action.dataset.aiChatAction;
        if (name === 'edit') startEdit(action.dataset.id);
        if (name === 'save-edit') saveEditedPlan(action.dataset.id);
        if (name === 'cancel-edit') { state.editingId = null; state.editPlan = null; renderMessages(); }
        if (name === 'execute') executeSearch(action.dataset.id);
        if (name === 'new') { input.focus(); input.value = ''; }
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && state.open) setOpen(false);
    });

    renderMessages();
    resizeInput();
    window.BIDFinderAIChat = {
        open: () => setOpen(true),
        close: () => setOpen(false),
        sendMessage,
        refreshUsage: loadUsage,
        getState: () => ({ open: state.open, group: state.group, history: clone(state.history), usage: state.usage })
    };
})();
