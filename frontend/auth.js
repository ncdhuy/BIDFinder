(function () {
  const API_BASE_URL =
    (window.location.protocol === 'file:' ||
      window.location.hostname === 'localhost' ||
      window.location.hostname === '127.0.0.1')
      ? 'http://127.0.0.1:8000'
      : 'https://bidfinder.onrender.com';

  const STORAGE_KEY = 'bidfinder:auth_token';
  const DATA_ACCESS_KEY = 'bidfinder:require_auth_for_data_access';
  const TOKEN_STORAGE = window.sessionStorage;
  const LEGACY_TOKEN_STORAGE = window.localStorage;
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function readStoredToken() {
    const sessionToken = TOKEN_STORAGE.getItem(STORAGE_KEY) || '';
    if (sessionToken) return sessionToken;

    const legacyToken = LEGACY_TOKEN_STORAGE.getItem(STORAGE_KEY) || '';
    if (!legacyToken) return '';

    TOKEN_STORAGE.setItem(STORAGE_KEY, legacyToken);
    LEGACY_TOKEN_STORAGE.removeItem(STORAGE_KEY);
    return legacyToken;
  }

  const state = {
    token: readStoredToken(),
    user: null,
    config: {
      google_enabled: false,
      google_client_id: null,
      position_options: [],
      position_option_groups: [],
      require_auth_for_data_access: false,
      require_auth_for_full_query: true,
      anonymous_access_level: 'full',  // none|preview|full
      allow_anonymous_preview: true,
      allow_anonymous_autocomplete: true,
      allow_anonymous_metadata: true,
      anonymous_single_char_numeric_only: true,
      anonymous_full_query_daily_limit: 10,
      anonymous_full_query_daily_used: 0,
      anonymous_full_query_daily_remaining: 10,
      anonymous_full_query_login_required: false,
      anonymous_full_query_limit_message: 'Bạn đã dùng hết lượt tra cứu hôm nay. Vui lòng đăng nhập để tiếp tục.',
      password_policy_message: 'Mật khẩu phải có ít nhất 9 ký tự, bao gồm ít nhất 1 chữ số và 1 chữ cái in hoa.'
    },
    currentMode: 'register',
    pendingIntent: null,
    googleRendered: false,
    googleErrorMessage: '',
    initialized: false
  };

  const els = {};

  function emit(name, detail = {}) {
    window.dispatchEvent(new CustomEvent(name, { detail }));
  }

  function cacheElements() {
    const ids = [
      'auth-modal',
      'auth-alert',
      'auth-close-btn',
      'auth-guest-view',
      'auth-profile-view',
      'auth-brand-guest-view',
      'auth-brand-profile-view',
      'auth-register-panel',
      'auth-login-panel',
      'auth-register-form',
      'auth-login-form',
      'auth-profile-form',
      'auth-profile-cancel-btn',
      'google-register-block',
      'google-login-block',
      'google-auth-slot-register',
      'google-auth-slot-login',
      'app-auth-shell',
      'auth-edit-profile-btn',
      'auth-logout-btn',
      'account-sidebar-name',
      'account-sidebar-email',
      'account-sidebar-provider',
      'account-sidebar-work-unit',
      'account-sidebar-position',
      'register-full-name',
      'register-email',
      'register-password',
      'register-work-unit',
      'register-position',
      'register-password-note',
      'login-email',
      'login-password',
      'profile-full-name',
      'profile-work-unit',
      'profile-position',
      'open-register-nav',
      'open-login-nav',
      'open-login-hero'
    ];

    ids.forEach((id) => {
      els[id] = document.getElementById(id);
    });

    els.overlay = document.querySelector('#auth-modal .auth-overlay');
    els.modeButtons = Array.from(document.querySelectorAll('[data-auth-mode]'));
  }

  function getApiUrl(path) {
    return `${API_BASE_URL}${path}`;
  }

  function isAuthenticated() {
    return Boolean(state.user);
  }

  function requiresDataAuth() {
    return Boolean(state.config?.require_auth_for_data_access);
  }

  function requiresFullQueryAuth() {
    return Boolean(state.config?.require_auth_for_full_query);
  }

  function getFullQueryGateMessage() {
    if (state.config?.anonymous_full_query_login_required && state.config?.anonymous_full_query_limit_message) {
      return state.config.anonymous_full_query_limit_message;
    }
    return 'Bạn cần đăng nhập để tra cứu dữ liệu.';
  }

  function saveToken(token) {
    state.token = token || '';
    if (state.token) {
      TOKEN_STORAGE.setItem(STORAGE_KEY, state.token);
      LEGACY_TOKEN_STORAGE.removeItem(STORAGE_KEY);
    } else {
      TOKEN_STORAGE.removeItem(STORAGE_KEY);
      LEGACY_TOKEN_STORAGE.removeItem(STORAGE_KEY);
    }
  }

  function persistAuthConfig() {
    localStorage.setItem(DATA_ACCESS_KEY, requiresDataAuth() ? '1' : '0');
  }

  function applyAuthConfig(nextConfig, { merge = true } = {}) {
    if (!nextConfig || typeof nextConfig !== 'object') return;
    state.config = merge ? { ...state.config, ...nextConfig } : nextConfig;
    persistAuthConfig();
    syncPasswordPolicyNote();
    populatePositionOptions();
    syncGoogleVisibility();
  }

  function getPasswordPolicyMessage() {
    return state.config?.password_policy_message
      || 'Mật khẩu phải có ít nhất 9 ký tự, bao gồm ít nhất 1 chữ số và 1 chữ cái in hoa.';
  }

  function isValidEmail(value) {
    return EMAIL_RE.test(String(value || '').trim());
  }

  function isValidRegisterPassword(value) {
    const password = String(value || '');
    return password.length >= 9 && /[A-Z]/.test(password) && /\d/.test(password);
  }

  function showValidationError(message, field) {
    setAlert(message, 'error');
    field?.focus?.();
  }

  function formatAuthProvider(provider) {
    if (provider === 'google') return 'Google';
    if (provider === 'hybrid') return 'Google + Email';
    return 'Email';
  }

  function setAlert(message = '', type = 'error') {
    if (!els['auth-alert']) return;

    if (!message) {
      els['auth-alert'].hidden = true;
      els['auth-alert'].textContent = '';
      els['auth-alert'].className = 'auth-alert';
      return;
    }

    els['auth-alert'].hidden = false;
    els['auth-alert'].textContent = message;
    els['auth-alert'].className = `auth-alert is-${type}`;
  }

  function setFormBusy(form, busy, busyLabel) {
    if (!form) return;

    const submit = form.querySelector('button[type="submit"]');
    if (!submit) return;

    if (!submit.dataset.defaultLabel) {
      submit.dataset.defaultLabel = submit.textContent || '';
    }

    submit.disabled = Boolean(busy);
    submit.textContent = busy ? (busyLabel || 'Đang xử lý...') : submit.dataset.defaultLabel;
  }

  function renderUserState() {
    const authed = isAuthenticated();

    els['app-auth-shell']?.classList.toggle('is-hidden', !authed);
    [els['open-register-nav'], els['open-login-nav'], els['open-login-hero']].forEach((el) => {
      if (!el) return;
      el.hidden = authed;
    });

    if (authed) {
      if (els['auth-edit-profile-btn']) {
        els['auth-edit-profile-btn'].textContent = 'Tài khoản';
      }
      if (els['account-sidebar-name']) {
        els['account-sidebar-name'].textContent = state.user.full_name || 'Người dùng BIDFinder';
      }
      if (els['account-sidebar-email']) {
        els['account-sidebar-email'].textContent = state.user.email || '';
      }
      if (els['account-sidebar-provider']) {
        els['account-sidebar-provider'].textContent = formatAuthProvider(state.user.auth_provider);
      }
      if (els['account-sidebar-work-unit']) {
        els['account-sidebar-work-unit'].textContent = state.user.work_unit || 'Chưa cập nhật';
      }
      if (els['account-sidebar-position']) {
        els['account-sidebar-position'].textContent = state.user.position || 'Chưa cập nhật';
      }
    }
  }

  function validateRegisterForm() {
    const fullName = els['register-full-name']?.value?.trim() || '';
    const email = els['register-email']?.value?.trim() || '';
    const password = els['register-password']?.value || '';

    if (!fullName) {
      showValidationError('Vui lòng nhập họ và tên.', els['register-full-name']);
      return false;
    }

    if (!email) {
      showValidationError('Vui lòng nhập email.', els['register-email']);
      return false;
    }

    if (!isValidEmail(email)) {
      showValidationError('Email không hợp lệ.', els['register-email']);
      return false;
    }

    if (!password) {
      showValidationError('Vui lòng nhập mật khẩu.', els['register-password']);
      return false;
    }

    if (!isValidRegisterPassword(password)) {
      showValidationError(getPasswordPolicyMessage(), els['register-password']);
      return false;
    }

    return true;
  }

  function validateLoginForm() {
    const email = els['login-email']?.value?.trim() || '';
    const password = els['login-password']?.value || '';

    if (!email) {
      showValidationError('Vui lòng nhập email.', els['login-email']);
      return false;
    }

    if (!isValidEmail(email)) {
      showValidationError('Email không hợp lệ.', els['login-email']);
      return false;
    }

    if (!password) {
      showValidationError('Vui lòng nhập mật khẩu.', els['login-password']);
      return false;
    }

    return true;
  }

  function validateProfileForm() {
    const fullName = els['profile-full-name']?.value?.trim() || '';

    if (!fullName) {
      showValidationError('Vui lòng nhập họ và tên.', els['profile-full-name']);
      return false;
    }

    return true;
  }

  function syncSelectPlaceholderState(select) {
    if (!select) return;
    select.classList.toggle('is-placeholder', !String(select.value || '').trim());
  }

  function populatePositionOptions() {
    const optionGroups = Array.isArray(state.config?.position_option_groups)
      ? state.config.position_option_groups
      : [];
    const options = Array.isArray(state.config?.position_options)
      ? state.config.position_options
      : [];
    ['register-position', 'profile-position'].forEach((fieldId) => {
      const select = els[fieldId];
      if (!select) return;

      const currentValue = select.value;
      select.innerHTML = '<option value="" disabled selected hidden>Vị trí</option>';

      if (optionGroups.length) {
        optionGroups.forEach((group) => {
          const groupLabel = String(group?.label || '').trim();
          const groupOptions = Array.isArray(group?.options) ? group.options : [];
          if (!groupLabel || !groupOptions.length) return;

          const optgroup = document.createElement('optgroup');
          optgroup.label = groupLabel;

          groupOptions.forEach((option) => {
            const optionText = String(option || '').trim();
            if (!optionText) return;
            const el = document.createElement('option');
            el.value = optionText;
            el.textContent = optionText;
            optgroup.appendChild(el);
          });

          if (optgroup.children.length) {
            select.appendChild(optgroup);
          }
        });
      } else {
        options.forEach((option) => {
          const el = document.createElement('option');
          el.value = option;
          el.textContent = option;
          select.appendChild(el);
        });
      }

      select.value = currentValue || '';
      syncSelectPlaceholderState(select);
    });
  }

  function populateProfileForm() {
    if (!state.user) return;
    populatePositionOptions();

    if (els['profile-full-name']) {
      els['profile-full-name'].value = state.user.full_name || '';
    }
    if (els['profile-work-unit']) {
      els['profile-work-unit'].value = state.user.work_unit || '';
    }
    if (els['profile-position']) {
      els['profile-position'].value = state.user.position || '';
    }
  }

  function syncPasswordPolicyNote() {
    if (els['register-password-note']) {
      els['register-password-note'].textContent = getPasswordPolicyMessage();
    }
  }

  function syncGoogleVisibility() {
    const enabled = Boolean(state.config?.google_enabled && state.config?.google_client_id && !state.googleErrorMessage);

    [els['google-register-block'], els['google-login-block']].forEach((block) => {
      if (!block) return;
      block.hidden = !enabled;
    });
  }

  function resolveGoogleRuntimeError() {
    if (window.location.protocol === 'file:') {
      return 'Đăng nhập Google chỉ hoạt động khi mở app qua địa chỉ http://localhost hoặc domain deploy, không dùng trực tiếp file HTML.';
    }

    return '';
  }

  function showGuestMode(mode = 'register') {
    state.currentMode = mode === 'login' ? 'login' : 'register';

    if (els['auth-guest-view']) els['auth-guest-view'].hidden = false;
    if (els['auth-profile-view']) els['auth-profile-view'].hidden = true;
    if (els['auth-brand-guest-view']) els['auth-brand-guest-view'].hidden = false;
    if (els['auth-brand-profile-view']) els['auth-brand-profile-view'].hidden = true;
    if (els['auth-register-panel']) {
      els['auth-register-panel'].hidden = state.currentMode !== 'register';
      els['auth-register-panel'].classList.toggle('active', state.currentMode === 'register');
    }
    if (els['auth-login-panel']) {
      els['auth-login-panel'].hidden = state.currentMode !== 'login';
      els['auth-login-panel'].classList.toggle('active', state.currentMode === 'login');
    }
    if (els['auth-register-form']) els['auth-register-form'].hidden = state.currentMode !== 'register';
    if (els['auth-login-form']) els['auth-login-form'].hidden = state.currentMode !== 'login';

    els.modeButtons?.forEach((button) => {
      button.classList.toggle('active', button.dataset.authMode === state.currentMode);
    });
  }

  function showProfileMode() {
    if (!isAuthenticated()) {
      showGuestMode('login');
      return;
    }

    if (els['auth-guest-view']) els['auth-guest-view'].hidden = true;
    if (els['auth-profile-view']) els['auth-profile-view'].hidden = false;
    if (els['auth-brand-guest-view']) els['auth-brand-guest-view'].hidden = true;
    if (els['auth-brand-profile-view']) els['auth-brand-profile-view'].hidden = false;
    renderUserState();
    populateProfileForm();
  }

  function focusFirstField() {
    const activePanel = els['auth-profile-view']?.hidden ? state.currentMode : 'profile';
    const focusMap = {
      register: els['register-full-name'],
      login: els['login-email'],
      profile: els['profile-full-name']
    };
    focusMap[activePanel]?.focus();
  }

  function openAuthModal(mode = 'register') {
    if (!els['auth-modal']) return;

    setAlert('');
    syncGoogleVisibility();
    scheduleGoogleButtonRender();

    if (mode === 'profile' && isAuthenticated()) {
      showProfileMode();
    } else {
      const guestMode = mode === 'profile'
        ? 'login'
        : mode === 'login'
        ? 'login'
        : 'register';
      showGuestMode(guestMode);
    }

    els['auth-modal'].classList.add('show');
    els['auth-modal'].setAttribute('aria-hidden', 'false');
    document.body.classList.add('auth-modal-open');

    if (window.feather?.replace) {
      window.feather.replace();
    }

    requestAnimationFrame(focusFirstField);
  }

  function closeAuthModal({ clearIntent = true } = {}) {
    if (!els['auth-modal']) return;

    els['auth-modal'].classList.remove('show');
    els['auth-modal'].setAttribute('aria-hidden', 'true');
    document.body.classList.remove('auth-modal-open');
    setAlert('');

    if (clearIntent) {
      state.pendingIntent = null;
    }
  }

  async function parseResponseBody(response) {
    const rawText = await response.text();
    if (!rawText) return {};

    try {
      return JSON.parse(rawText);
    } catch (err) {
      return {
        success: false,
        message: rawText
      };
    }
  }

  async function authorizedFetch(url, options = {}, extra = {}) {
    const headers = new Headers(options.headers || {});

    if (state.token) {
      headers.set('Authorization', `Bearer ${state.token}`);
    }

    const response = await fetch(url, {
      ...options,
      headers,
      credentials: 'include'
    });

    if (response.status === 401 && extra.handleUnauthorized !== false) {
      let message = '';
      try {
        const payload = await parseResponseBody(response.clone());
        message = payload?.message || payload?.error || '';
      } catch (err) {}

      clearSession({
        openLogin: true,
        reason: isAuthenticated() ? 'expired' : 'login_required',
        alertMessage: message || (isAuthenticated()
          ? 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
          : 'Vui lòng đăng nhập để tiếp tục.')
      });
    }

    return response;
  }

  async function submitJson(path, body, options = {}) {
    const response = options.authenticated
      ? await authorizedFetch(getApiUrl(path), {
          method: options.method || 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body || {})
        }, {
          handleUnauthorized: options.handleUnauthorized !== false
        })
      : await fetch(getApiUrl(path), {
          method: options.method || 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body || {}),
          credentials: 'include'
        });

    const payload = await parseResponseBody(response);

    if (!response.ok || payload.success === false) {
      const message = payload?.message || payload?.error || `HTTP ${response.status}`;
      throw new Error(message);
    }

    return payload;
  }

  function applyAuthResult(payload, source) {
    saveToken(payload.token || payload.legacy_token || '');
    state.user = payload.user || null;
    applyAuthConfig(payload.auth || state.config);
    renderUserState();
    closeAuthModal({ clearIntent: false });

    const completedIntent = state.pendingIntent;
    state.pendingIntent = null;

    emit('bidfinder:auth-changed', {
      authenticated: true,
      user: state.user,
      source,
      intent: completedIntent || 'enter-app'
    });
  }

  function clearSession({ emitEvent = true, openLogin = false, reason = 'logout', alertMessage = '' } = {}) {
    saveToken('');
    state.user = null;
    renderUserState();
    populatePositionOptions();

    if (openLogin) {
      openAuthModal('login');
      setAlert(alertMessage || 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.', 'error');
    }

    if (emitEvent) {
      emit('bidfinder:auth-changed', {
        authenticated: false,
        user: null,
        reason
      });
    }
  }

  async function restoreSession() {
    try {
      const response = await authorizedFetch(getApiUrl('/api/auth/me'), {
        method: 'GET'
      }, {
        handleUnauthorized: false
      });

      const payload = await parseResponseBody(response);
      if (!response.ok || payload.success === false || !payload.user) {
        clearSession({ emitEvent: false });
        return false;
      }

      state.user = payload.user;
      applyAuthConfig(payload.auth || state.config);
      renderUserState();
      return true;
    } catch (err) {
      clearSession({ emitEvent: false });
      return false;
    }
  }

  async function loadAuthConfig() {
    try {
      const response = await fetch(getApiUrl('/api/auth/config'), {
        credentials: 'include'
      });
      const payload = await parseResponseBody(response);
      if (response.ok && payload.success) {
        applyAuthConfig(payload, { merge: false });
      }
    } catch (err) {}

    syncPasswordPolicyNote();
    populatePositionOptions();
    syncGoogleVisibility();
    scheduleGoogleButtonRender();
  }

  async function handleRegisterSubmit(event) {
    event.preventDefault();
    setAlert('');

    if (!validateRegisterForm()) {
      return;
    }

    setFormBusy(els['auth-register-form'], true, 'Đang tạo tài khoản...');

    try {
      const payload = await submitJson('/api/auth/register', {
        full_name: els['register-full-name']?.value?.trim() || '',
        email: els['register-email']?.value?.trim() || '',
        password: els['register-password']?.value || '',
        work_unit: els['register-work-unit']?.value?.trim() || '',
        position: els['register-position']?.value || ''
      });

      applyAuthResult(payload, 'register');
    } catch (err) {
      setAlert(err.message || 'Không thể tạo tài khoản.', 'error');
    } finally {
      setFormBusy(els['auth-register-form'], false);
    }
  }

  async function handleLoginSubmit(event) {
    event.preventDefault();
    setAlert('');

    if (!validateLoginForm()) {
      return;
    }

    setFormBusy(els['auth-login-form'], true, 'Đang đăng nhập...');

    try {
      const payload = await submitJson('/api/auth/login', {
        email: els['login-email']?.value?.trim() || '',
        password: els['login-password']?.value || ''
      });

      applyAuthResult(payload, 'login');
    } catch (err) {
      setAlert(err.message || 'Không thể đăng nhập.', 'error');
    } finally {
      setFormBusy(els['auth-login-form'], false);
    }
  }

  async function handleProfileSubmit(event) {
    event.preventDefault();
    setAlert('');

    if (!validateProfileForm()) {
      return;
    }

    setFormBusy(els['auth-profile-form'], true, 'Đang lưu hồ sơ...');

    try {
      const payload = await submitJson('/api/auth/profile', {
        full_name: els['profile-full-name']?.value?.trim() || '',
        work_unit: els['profile-work-unit']?.value?.trim() || '',
        position: els['profile-position']?.value || ''
      }, {
        authenticated: true,
        method: 'PATCH'
      });

      state.user = payload.user || state.user;
      applyAuthConfig(payload.auth || state.config);
      renderUserState();
      populateProfileForm();
      setAlert(payload.message || 'Cập nhật hồ sơ thành công.', 'success');
    } catch (err) {
      setAlert(err.message || 'Không thể cập nhật hồ sơ.', 'error');
    } finally {
      setFormBusy(els['auth-profile-form'], false);
    }
  }

  async function handleLogout() {
    try {
      await submitJson('/api/auth/logout', {}, {
        authenticated: true
      });
    } catch (err) {
    } finally {
      clearSession({ emitEvent: true, reason: 'logout' });
      closeAuthModal();
    }
  }

  async function handleGoogleCredential(response) {
    const credential = response?.credential;
    if (!credential) {
      setAlert('Không nhận được credential từ Google.', 'error');
      return;
    }

    try {
      const payload = await submitJson('/api/auth/google', { credential });
      applyAuthResult(payload, 'google');
    } catch (err) {
      setAlert(err.message || 'Không thể đăng nhập bằng Google.', 'error');
    }
  }

  function tryRenderGoogleButtons() {
    if (state.googleRendered) {
      return true;
    }

    const clientId = state.config?.google_client_id;
    const slots = [els['google-auth-slot-register'], els['google-auth-slot-login']].filter(Boolean);

    if (!slots.length) {
      return true;
    }

    state.googleErrorMessage = resolveGoogleRuntimeError();
    if (state.googleErrorMessage) {
      syncGoogleVisibility();
      return true;
    }

    if (!state.config?.google_enabled || !clientId) {
      syncGoogleVisibility();
      return true;
    }

    if (!window.google?.accounts?.id) {
      return false;
    }

    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: handleGoogleCredential
    });

    slots.forEach((slot) => {
      slot.innerHTML = '';
      window.google.accounts.id.renderButton(slot, {
        theme: 'outline',
        size: 'large',
        shape: 'pill',
        width: 320,
        text: 'continue_with',
        locale: 'vi'
      });
    });

    state.googleRendered = true;
    return true;
  }

  function scheduleGoogleButtonRender() {
    syncGoogleVisibility();

    state.googleErrorMessage = resolveGoogleRuntimeError();
    if (state.googleErrorMessage) {
      syncGoogleVisibility();
      return;
    }

    if (!state.config?.google_enabled || !state.config?.google_client_id) {
      return;
    }

    let attempts = 0;

    const tick = () => {
      attempts += 1;
      if (tryRenderGoogleButtons()) return;
      if (attempts < 20) {
        window.setTimeout(tick, 400);
      }
    };

    tick();
  }

  function bindEvents() {
    els.modeButtons?.forEach((button) => {
      button.addEventListener('click', () => {
        showGuestMode(button.dataset.authMode);
        setAlert('');
      });
    });

    const openLogin = () => {
      openAuthModal('login');
    };

    const openRegister = () => {
      openAuthModal('register');
    };

    els['open-login-nav']?.addEventListener('click', openLogin);
    els['open-login-hero']?.addEventListener('click', openLogin);
    els['open-register-nav']?.addEventListener('click', openRegister);
    els['auth-close-btn']?.addEventListener('click', () => closeAuthModal());
    els.overlay?.addEventListener('click', () => closeAuthModal());

    els['auth-register-form']?.addEventListener('submit', handleRegisterSubmit);
    els['auth-login-form']?.addEventListener('submit', handleLoginSubmit);
    els['auth-profile-form']?.addEventListener('submit', handleProfileSubmit);
    els['auth-profile-cancel-btn']?.addEventListener('click', () => closeAuthModal({ clearIntent: false }));
    els['auth-edit-profile-btn']?.addEventListener('click', () => openAuthModal('profile'));
    els['auth-logout-btn']?.addEventListener('click', handleLogout);
    ['register-position', 'profile-position'].forEach((fieldId) => {
      els[fieldId]?.addEventListener('change', (event) => {
        syncSelectPlaceholderState(event.currentTarget);
      });
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && els['auth-modal']?.classList.contains('show')) {
        closeAuthModal();
      }
    });
  }

  async function init() {
    if (state.initialized) return;

    cacheElements();
    bindEvents();
    renderUserState();
    await loadAuthConfig();

    const restored = await restoreSession();
    state.initialized = true;

    emit('bidfinder:auth-ready', {
      authenticated: restored,
      user: state.user,
      config: state.config
    });
  }

  window.bidfinderAuthorizedFetch = authorizedFetch;
  window.BIDFinderAuth = {
    init,
    isAuthenticated,
    requiresDataAuth,
    requiresFullQueryAuth,
    getFullQueryGateMessage,
    getUser: () => state.user,
    getConfig: () => state.config,
    applyAuthConfig,
    openAuthModal,
    closeAuthModal,
    requestIntent(intent) {
      state.pendingIntent = intent || null;
    },
    clearIntent() {
      state.pendingIntent = null;
    },
    ensureAuthenticated(mode = 'login') {
      if (isAuthenticated()) return true;
      openAuthModal(mode);
      return false;
    }
  };
})();
