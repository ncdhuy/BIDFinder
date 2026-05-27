(function () {
  const API_BASE_URL =
    window.API_BASE_URL ||
    window.BIDFINDER_CONFIG?.apiBaseUrl ||
    ((window.location.protocol === 'file:' ||
        window.location.hostname === 'localhost' ||
        window.location.hostname === '127.0.0.1')
      ? 'http://127.0.0.1:8000'
      : 'https://bidfinder-api-staging-774667987564.asia-southeast1.run.app');
  const AUTH_API_CANDIDATE_URLS = Array.from(new Set([
    API_BASE_URL,
    window.BIDFINDER_CONFIG?.primaryApiBaseUrl,
    window.BIDFINDER_CONFIG?.backupApiBaseUrl
  ].filter(Boolean).map((value) => String(value).replace(/\/+$/, ''))));

  const STORAGE_KEY = 'bidfinder:auth_token';
  const DATA_ACCESS_KEY = 'bidfinder:require_auth_for_data_access';
  const AUTH_HINT_KEY = 'bidfinder:auth_hint';
  const TOKEN_STORAGE = window.sessionStorage;
  const LEGACY_TOKEN_STORAGE = window.localStorage;
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const PROFILE_SECTIONS = ['profile', 'password'];
  const SESSION_VERIFY_INTERVAL_MS = 5 * 60 * 1000;

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
      full_search_enabled: true,
      full_search_daily_limit: 3,
      full_search_daily_used: 0,
      full_search_daily_remaining: 3,
      full_search_limit_message: 'Bạn đã dùng hết lượt full search hôm nay. Vui lòng quay lại vào ngày mai.',
      password_policy_message: 'Mật khẩu phải có ít nhất 9 ký tự, bao gồm ít nhất 1 chữ số và 1 chữ cái in hoa.',
      password_reset_enabled: false,
      password_reset_status: 'unknown'
    },
    currentMode: 'register',
    pendingIntent: null,
    resetPasswordToken: '',
    googleRendered: false,
    googleErrorMessage: '',
    initialized: false,
    configLoaded: false,
    readyPromise: null,
    lastSessionVerifyAt: 0,
    sessionVerifyPromise: null
  };
  state.authApiBaseUrl = API_BASE_URL.replace(/\/+$/, '');

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
      'auth-forgot-password-panel',
      'auth-reset-password-panel',
      'auth-register-form',
      'auth-login-form',
      'auth-forgot-password-form',
      'auth-reset-password-form',
      'auth-profile-form',
      'auth-change-password-form',
      'auth-profile-cancel-btn',
      'auth-profile-section-toggle',
      'auth-password-section-toggle',
      'auth-profile-section-detail',
      'auth-password-section-detail',
      'auth-forgot-password-btn',
      'auth-back-to-login-btn',
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
      'forgot-password-email',
      'reset-password-new',
      'reset-password-confirm',
      'reset-password-note',
      'profile-full-name',
      'profile-work-unit',
      'profile-position',
      'change-password-current-field',
      'change-password-current',
      'change-password-new',
      'change-password-confirm',
      'change-password-note',
      'auth-password-title',
      'auth-password-desc',
      'open-account-nav',
      'open-feedback-nav',
      'open-register-nav',
      'open-login-nav',
      'open-register-app',
      'open-login-app',
      'open-login-hero'
    ];

    ids.forEach((id) => {
      els[id] = document.getElementById(id);
    });

    els.overlay = document.querySelector('#auth-modal .auth-overlay');
    els.modeButtons = Array.from(document.querySelectorAll('[data-auth-mode]'));
    els.modeSwitch = document.querySelector('.auth-mode-switch');
    els.guestPanels = Array.from(document.querySelectorAll('.auth-mode-panel'));
  }

  function getApiUrl(path) {
    const baseUrl = String(path || '').startsWith('/api/auth')
      ? state.authApiBaseUrl
      : API_BASE_URL;
    return `${baseUrl}${path}`;
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

  function hasOptimisticAuthHint() {
    try {
      return window.localStorage.getItem(AUTH_HINT_KEY) === 'authed';
    } catch (err) {
      return false;
    }
  }

  function hasSessionCandidate() {
    return Boolean(state.token) || Boolean(state.user) || hasOptimisticAuthHint();
  }

  function setAuthHint(isAuthed) {
    try {
      if (isAuthed) {
        window.localStorage.setItem(AUTH_HINT_KEY, 'authed');
      } else {
        window.localStorage.removeItem(AUTH_HINT_KEY);
      }
    } catch (err) {}
  }

  function applyAuthConfig(nextConfig, { merge = true } = {}) {
    if (!nextConfig || typeof nextConfig !== 'object') return;
    state.config = merge ? { ...state.config, ...nextConfig } : nextConfig;
    persistAuthConfig();
    syncPasswordPolicyNote();
    populatePositionOptions();
    syncGoogleVisibility();
    syncPasswordResetAvailability();
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
    const optimisticAuthed = !state.initialized && hasSessionCandidate();
    const authed = isAuthenticated() || optimisticAuthed;

    document.body.classList.toggle('auth-state-authed', authed);
    document.body.classList.toggle('auth-state-guest', !authed);

    els['app-auth-shell']?.classList.toggle('is-hidden', !authed);
    if (els['open-account-nav']) {
      els['open-account-nav'].hidden = !authed;
    }
    [els['open-register-nav'], els['open-login-nav'], els['open-register-app'], els['open-login-app'], els['open-login-hero']].forEach((el) => {
      if (!el) return;
      el.hidden = authed;
    });

    if (isAuthenticated()) {
      const user = state.user || {};
      if (els['auth-edit-profile-btn']) {
        els['auth-edit-profile-btn'].textContent = 'Tài khoản';
      }
      if (els['account-sidebar-name']) {
        els['account-sidebar-name'].textContent = user.full_name || 'Người dùng BIDFinder';
      }
      if (els['account-sidebar-email']) {
        els['account-sidebar-email'].textContent = user.email || '';
      }
      if (els['account-sidebar-provider']) {
        els['account-sidebar-provider'].textContent = formatAuthProvider(user.auth_provider);
      }
      if (els['account-sidebar-work-unit']) {
        els['account-sidebar-work-unit'].textContent = user.work_unit || 'Chưa cập nhật';
      }
      if (els['account-sidebar-position']) {
        els['account-sidebar-position'].textContent = user.position || 'Chưa cập nhật';
      }
    }

  }

  function markAuthInitialized() {
    state.initialized = true;
    renderUserState();
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

  function isValidPasswordConfirmation(password, confirmPassword) {
    return String(password || '') === String(confirmPassword || '');
  }

  function validateForgotPasswordForm() {
    const email = els['forgot-password-email']?.value?.trim() || '';

    if (!email) {
      showValidationError('Vui lòng nhập email.', els['forgot-password-email']);
      return false;
    }

    if (!isValidEmail(email)) {
      showValidationError('Email không hợp lệ.', els['forgot-password-email']);
      return false;
    }

    return true;
  }

  function validateResetPasswordForm() {
    const password = els['reset-password-new']?.value || '';
    const confirmPassword = els['reset-password-confirm']?.value || '';

    if (!password) {
      showValidationError('Vui lòng nhập mật khẩu mới.', els['reset-password-new']);
      return false;
    }

    if (!isValidRegisterPassword(password)) {
      showValidationError(getPasswordPolicyMessage(), els['reset-password-new']);
      return false;
    }

    if (!confirmPassword) {
      showValidationError('Vui lòng nhập lại mật khẩu mới.', els['reset-password-confirm']);
      return false;
    }

    if (!isValidPasswordConfirmation(password, confirmPassword)) {
      showValidationError('Mật khẩu nhập lại chưa khớp.', els['reset-password-confirm']);
      return false;
    }

    return true;
  }

  function validateChangePasswordForm() {
    const hasPassword = Boolean(state.user?.has_password);
    const currentPassword = els['change-password-current']?.value || '';
    const newPassword = els['change-password-new']?.value || '';
    const confirmPassword = els['change-password-confirm']?.value || '';

    if (hasPassword && !currentPassword) {
      showValidationError('Vui lòng nhập mật khẩu hiện tại.', els['change-password-current']);
      return false;
    }

    if (!newPassword) {
      showValidationError('Vui lòng nhập mật khẩu mới.', els['change-password-new']);
      return false;
    }

    if (!isValidRegisterPassword(newPassword)) {
      showValidationError(getPasswordPolicyMessage(), els['change-password-new']);
      return false;
    }

    if (!confirmPassword) {
      showValidationError('Vui lòng nhập lại mật khẩu mới.', els['change-password-confirm']);
      return false;
    }

    if (!isValidPasswordConfirmation(newPassword, confirmPassword)) {
      showValidationError('Mật khẩu nhập lại chưa khớp.', els['change-password-confirm']);
      return false;
    }

    if (hasPassword && currentPassword === newPassword) {
      showValidationError('Mật khẩu mới cần khác mật khẩu hiện tại.', els['change-password-new']);
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

    syncPasswordSection();
  }

  function syncPasswordPolicyNote() {
    if (els['register-password-note']) {
      els['register-password-note'].textContent = getPasswordPolicyMessage();
    }
    if (els['reset-password-note']) {
      els['reset-password-note'].textContent = getPasswordPolicyMessage();
    }
    if (els['change-password-note']) {
      els['change-password-note'].textContent = getPasswordPolicyMessage();
    }
  }

  function measurePanelHeight(panel) {
    if (!panel) return 0;

    const wasHidden = panel.hidden;
    const previousDisplay = panel.style.display;
    const previousPosition = panel.style.position;
    const previousVisibility = panel.style.visibility;
    const previousPointerEvents = panel.style.pointerEvents;
    const previousInset = panel.style.inset;

    panel.hidden = false;
    panel.style.display = 'block';
    panel.style.position = 'absolute';
    panel.style.inset = '0 auto auto 0';
    panel.style.visibility = 'hidden';
    panel.style.pointerEvents = 'none';

    const height = panel.offsetHeight;

    panel.hidden = wasHidden;
    panel.style.display = previousDisplay;
    panel.style.position = previousPosition;
    panel.style.visibility = previousVisibility;
    panel.style.pointerEvents = previousPointerEvents;
    panel.style.inset = previousInset;

    return height;
  }

  function syncGuestViewHeight() {
    if (!els['auth-guest-view']) return;

    (els.guestPanels || []).forEach((panel) => {
      panel.style.minHeight = '';
    });

    const panelHeights = (els.guestPanels || []).map((panel) => measurePanelHeight(panel)).filter(Boolean);
    if (!panelHeights.length) return;

    const maxHeight = Math.max(...panelHeights);
    els['auth-guest-view'].style.minHeight = `${maxHeight}px`;
    (els.guestPanels || []).forEach((panel) => {
      panel.style.minHeight = `${maxHeight}px`;
    });
  }

  function syncPasswordSection() {
    const hasPassword = Boolean(state.user?.has_password);

    if (els['change-password-current-field']) {
      els['change-password-current-field'].hidden = !hasPassword;
    }
    if (els['change-password-current']) {
      els['change-password-current'].required = hasPassword;
      els['change-password-current'].value = '';
    }
    if (els['auth-password-title']) {
      els['auth-password-title'].textContent = hasPassword ? 'Đổi mật khẩu' : 'Tạo mật khẩu đăng nhập';
    }
    if (els['auth-password-desc']) {
      els['auth-password-desc'].textContent = hasPassword
        ? 'Bạn có thể cập nhật mật khẩu để bảo vệ tài khoản tốt hơn.'
        : 'Tài khoản này chưa có mật khẩu email. Bạn có thể tạo mới để đăng nhập bằng email sau này.';
    }

    els['auth-change-password-form']?.reset();
  }

  function setActiveProfileSection(section = null) {
    const nextSection = PROFILE_SECTIONS.includes(section) ? section : null;
    const isProfileSection = nextSection === 'profile';
    const isPasswordSection = nextSection === 'password';

    if (els['auth-profile-section-toggle']) {
      els['auth-profile-section-toggle'].classList.toggle('active', isProfileSection);
      els['auth-profile-section-toggle'].setAttribute('aria-expanded', String(isProfileSection));
    }
    if (els['auth-password-section-toggle']) {
      els['auth-password-section-toggle'].classList.toggle('active', isPasswordSection);
      els['auth-password-section-toggle'].setAttribute('aria-expanded', String(isPasswordSection));
    }
    if (els['auth-profile-section-detail']) {
      els['auth-profile-section-detail'].hidden = !isProfileSection;
      els['auth-profile-section-detail'].classList.toggle('active', isProfileSection);
    }
    if (els['auth-password-section-detail']) {
      els['auth-password-section-detail'].hidden = !isPasswordSection;
      els['auth-password-section-detail'].classList.toggle('active', isPasswordSection);
    }
  }

  function syncGoogleVisibility() {
    const enabled = Boolean(state.config?.google_enabled && state.config?.google_client_id && !state.googleErrorMessage);

    [els['google-register-block'], els['google-login-block']].forEach((block) => {
      if (!block) return;
      block.hidden = !enabled;
    });
  }

  function syncPasswordResetAvailability() {
    const enabled = Boolean(state.config?.password_reset_enabled);

    if (els['auth-forgot-password-btn']) {
      els['auth-forgot-password-btn'].hidden = !enabled;
    }

    if (!enabled && state.currentMode === 'forgot-password') {
      showGuestMode('login');
    }
  }

  function resolveGoogleRuntimeError() {
    if (window.location.protocol === 'file:') {
      return 'Đăng nhập Google chỉ hoạt động khi mở app qua địa chỉ http://localhost hoặc domain deploy, không dùng trực tiếp file HTML.';
    }

    return '';
  }

  function getPasswordResetUnavailableMessage() {
    const status = state.config?.password_reset_status || 'unknown';
    if (status === 'missing_smtp_host') {
      return 'Chức năng gửi email đặt lại mật khẩu chưa được cấu hình: thiếu AUTH_SMTP_HOST trên backend.';
    }
    if (status === 'missing_smtp_port') {
      return 'Chức năng gửi email đặt lại mật khẩu chưa được cấu hình: thiếu AUTH_SMTP_PORT trên backend.';
    }
    if (status === 'missing_from_email') {
      return 'Chức năng gửi email đặt lại mật khẩu chưa được cấu hình: thiếu AUTH_SMTP_FROM_EMAIL trên backend.';
    }
    return 'Chức năng gửi email đặt lại mật khẩu chưa được cấu hình.';
  }

  function showGuestMode(mode = 'register') {
    state.currentMode = ['register', 'login', 'forgot-password', 'reset-password'].includes(mode)
      ? mode
      : 'register';

    els['auth-modal']?.classList.remove('is-profile');
    if (els['auth-guest-view']) els['auth-guest-view'].hidden = false;
    if (els['auth-profile-view']) els['auth-profile-view'].hidden = true;
    if (els['auth-brand-guest-view']) els['auth-brand-guest-view'].hidden = false;
    if (els['auth-brand-profile-view']) els['auth-brand-profile-view'].hidden = true;
    if (els.modeSwitch) {
      els.modeSwitch.hidden = !['register', 'login'].includes(state.currentMode);
    }
    if (els['auth-register-panel']) {
      els['auth-register-panel'].hidden = state.currentMode !== 'register';
      els['auth-register-panel'].classList.toggle('active', state.currentMode === 'register');
    }
    if (els['auth-login-panel']) {
      els['auth-login-panel'].hidden = state.currentMode !== 'login';
      els['auth-login-panel'].classList.toggle('active', state.currentMode === 'login');
    }
    if (els['auth-forgot-password-panel']) {
      els['auth-forgot-password-panel'].hidden = state.currentMode !== 'forgot-password';
      els['auth-forgot-password-panel'].classList.toggle('active', state.currentMode === 'forgot-password');
    }
    if (els['auth-reset-password-panel']) {
      els['auth-reset-password-panel'].hidden = state.currentMode !== 'reset-password';
      els['auth-reset-password-panel'].classList.toggle('active', state.currentMode === 'reset-password');
    }
    if (els['auth-register-form']) els['auth-register-form'].hidden = state.currentMode !== 'register';
    if (els['auth-login-form']) els['auth-login-form'].hidden = state.currentMode !== 'login';
    if (els['auth-forgot-password-form']) els['auth-forgot-password-form'].hidden = state.currentMode !== 'forgot-password';
    if (els['auth-reset-password-form']) els['auth-reset-password-form'].hidden = state.currentMode !== 'reset-password';

    els.modeButtons?.forEach((button) => {
      button.classList.toggle('active', button.dataset.authMode === state.currentMode);
    });

    syncGuestViewHeight();
  }

  function showProfileMode() {
    if (!isAuthenticated()) {
      showGuestMode('login');
      return;
    }

    els['auth-modal']?.classList.add('is-profile');
    if (els['auth-guest-view']) els['auth-guest-view'].hidden = true;
    if (els['auth-profile-view']) els['auth-profile-view'].hidden = false;
    if (els['auth-brand-guest-view']) els['auth-brand-guest-view'].hidden = true;
    if (els['auth-brand-profile-view']) els['auth-brand-profile-view'].hidden = false;
    renderUserState();
    populateProfileForm();
    setActiveProfileSection(null);
  }

  function focusFirstField() {
    const activePanel = els['auth-profile-view']?.hidden ? state.currentMode : 'profile';
    const focusMap = {
      register: els['register-full-name'],
      login: els['login-email'],
      'forgot-password': els['forgot-password-email'],
      'reset-password': els['reset-password-new'],
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
        : mode === 'forgot-password'
        ? 'forgot-password'
        : mode === 'reset-password'
        ? 'reset-password'
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

    requestAnimationFrame(() => {
      syncGuestViewHeight();
      focusFirstField();
    });
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
    setAuthHint(true);
    state.user = payload.user || null;
    applyAuthConfig(payload.auth || state.config);
    renderUserState();
    closeAuthModal({ clearIntent: false });
    window.BIDFinderAnalytics?.identify?.(state.user);
    window.BIDFinderAnalytics?.track?.('auth_success', {
      source: source || 'unknown',
      auth_provider: state.user?.auth_provider || source || 'unknown',
      has_work_unit: Boolean(state.user?.work_unit),
      has_position: Boolean(state.user?.position)
    });

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
    if (emitEvent) {
      window.BIDFinderAnalytics?.track?.('auth_session_cleared', {
        reason
      });
    }
    window.BIDFinderAnalytics?.reset?.();
    saveToken('');
    setAuthHint(false);
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
    state.lastSessionVerifyAt = Date.now();

    if (!hasSessionCandidate()) {
      state.user = null;
      markAuthInitialized();
      return false;
    }

    try {
      const response = await authorizedFetch(getApiUrl('/api/auth/me'), {
        method: 'GET'
      }, {
        handleUnauthorized: false
      });

      const payload = await parseResponseBody(response);
      if (!response.ok || payload.success === false || !payload.user) {
        clearSession({ emitEvent: false });
        markAuthInitialized();
        return false;
      }

      state.user = payload.user;
      setAuthHint(true);
      applyAuthConfig(payload.auth || state.config);
      renderUserState();
      window.BIDFinderAnalytics?.identify?.(state.user);
      return true;
    } catch (err) {
      setAuthHint(false);
      clearSession({ emitEvent: false });
      markAuthInitialized();
      return false;
    }
  }

  async function verifySessionIfNeeded({ force = false } = {}) {
    if (!state.initialized || !isAuthenticated()) return true;
    if (state.sessionVerifyPromise) return state.sessionVerifyPromise;

    const elapsed = Date.now() - Number(state.lastSessionVerifyAt || 0);
    if (!force && elapsed < SESSION_VERIFY_INTERVAL_MS) return true;

    state.sessionVerifyPromise = restoreSession()
      .finally(() => {
        state.sessionVerifyPromise = null;
      });

    return state.sessionVerifyPromise;
  }

  async function loadAuthConfig() {
    try {
      for (const baseUrl of AUTH_API_CANDIDATE_URLS) {
        try {
          const response = await fetch(`${baseUrl}/api/auth/config`, {
            credentials: 'include'
          });
          const payload = await parseResponseBody(response);
          if (response.ok && payload.success) {
            state.authApiBaseUrl = baseUrl;
            applyAuthConfig(payload, { merge: false });
            break;
          }
        } catch (err) {
          continue;
        }
      }
    } finally {
      state.configLoaded = true;
    }

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

  async function handleForgotPasswordSubmit(event) {
    event.preventDefault();
    setAlert('');

    if (!validateForgotPasswordForm()) {
      return;
    }

    setFormBusy(els['auth-forgot-password-form'], true, 'Đang gửi email...');

    try {
      const payload = await submitJson('/api/auth/forgot-password', {
        email: els['forgot-password-email']?.value?.trim() || ''
      });

      setAlert(payload.message || 'Đã gửi email hướng dẫn đặt lại mật khẩu.', 'success');
      els['auth-forgot-password-form']?.reset();
    } catch (err) {
      setAlert(err.message || 'Không thể gửi email đặt lại mật khẩu.', 'error');
    } finally {
      setFormBusy(els['auth-forgot-password-form'], false);
    }
  }

  async function handleResetPasswordSubmit(event) {
    event.preventDefault();
    setAlert('');

    if (!state.resetPasswordToken) {
      setAlert('Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.', 'error');
      return;
    }

    if (!validateResetPasswordForm()) {
      return;
    }

    setFormBusy(els['auth-reset-password-form'], true, 'Đang cập nhật...');

    try {
      const payload = await submitJson('/api/auth/reset-password', {
        token: state.resetPasswordToken,
        new_password: els['reset-password-new']?.value || ''
      });

      applyAuthResult(payload, 'reset-password');
      clearResetPasswordTokenFromUrl();
    } catch (err) {
      setAlert(err.message || 'Không thể đặt lại mật khẩu.', 'error');
    } finally {
      setFormBusy(els['auth-reset-password-form'], false);
    }
  }

  async function handleChangePasswordSubmit(event) {
    event.preventDefault();
    setAlert('');

    if (!validateChangePasswordForm()) {
      return;
    }

    setFormBusy(els['auth-change-password-form'], true, 'Đang lưu mật khẩu...');

    try {
      const payload = await submitJson('/api/auth/change-password', {
        current_password: els['change-password-current']?.value || '',
        new_password: els['change-password-new']?.value || ''
      }, {
        authenticated: true
      });

      state.user = payload.user || state.user;
      applyAuthConfig(payload.auth || state.config);
      renderUserState();
      syncPasswordSection();
      setAlert(payload.message || 'Đổi mật khẩu thành công.', 'success');
    } catch (err) {
      setAlert(err.message || 'Không thể đổi mật khẩu.', 'error');
    } finally {
      setFormBusy(els['auth-change-password-form'], false);
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
    console.info('BIDFinder Google Sign-In runtime config', {
      origin: window.location.origin,
      client_id: clientId
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
      if (tryRenderGoogleButtons()) {
        syncGuestViewHeight();
        return;
      }
      if (attempts < 20) {
        window.setTimeout(tick, 400);
      }
    };

    tick();
  }

  function readResetPasswordTokenFromUrl() {
    try {
      const url = new URL(window.location.href);
      return url.searchParams.get('reset_password_token') || '';
    } catch (err) {
      return '';
    }
  }

  function clearResetPasswordTokenFromUrl() {
    try {
      const url = new URL(window.location.href);
      url.searchParams.delete('reset_password_token');
      window.history.replaceState({}, document.title, url.toString());
    } catch (err) {}

    state.resetPasswordToken = '';
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
    els['open-login-app']?.addEventListener('click', openLogin);
    els['open-login-hero']?.addEventListener('click', openLogin);
    els['open-register-nav']?.addEventListener('click', openRegister);
    els['open-register-app']?.addEventListener('click', openRegister);
    els['open-account-nav']?.addEventListener('click', () => openAuthModal('profile'));
    els['auth-close-btn']?.addEventListener('click', () => closeAuthModal());
    els.overlay?.addEventListener('click', () => closeAuthModal());

    els['auth-register-form']?.addEventListener('submit', handleRegisterSubmit);
    els['auth-login-form']?.addEventListener('submit', handleLoginSubmit);
    els['auth-forgot-password-form']?.addEventListener('submit', handleForgotPasswordSubmit);
    els['auth-reset-password-form']?.addEventListener('submit', handleResetPasswordSubmit);
    els['auth-profile-form']?.addEventListener('submit', handleProfileSubmit);
    els['auth-change-password-form']?.addEventListener('submit', handleChangePasswordSubmit);
    els['auth-profile-cancel-btn']?.addEventListener('click', () => closeAuthModal({ clearIntent: false }));
    els['auth-profile-section-toggle']?.addEventListener('click', () => {
      const expanded = els['auth-profile-section-toggle']?.getAttribute('aria-expanded') === 'true';
      setActiveProfileSection(expanded ? null : 'profile');
      setAlert('');
      if (!expanded) {
        els['profile-full-name']?.focus();
      }
    });
    els['auth-password-section-toggle']?.addEventListener('click', () => {
      const expanded = els['auth-password-section-toggle']?.getAttribute('aria-expanded') === 'true';
      setActiveProfileSection(expanded ? null : 'password');
      setAlert('');
      if (!expanded) {
        const targetField = state.user?.has_password ? els['change-password-current'] : els['change-password-new'];
        targetField?.focus();
      }
    });
    els['auth-forgot-password-btn']?.addEventListener('click', async () => {
      if (!state.configLoaded) {
        await loadAuthConfig();
      }

      if (!state.config?.password_reset_enabled) {
        setAlert(getPasswordResetUnavailableMessage(), 'error');
        return;
      }

      showGuestMode('forgot-password');
      if (els['forgot-password-email']) {
        els['forgot-password-email'].value = els['login-email']?.value?.trim() || '';
      }
      setAlert('');
      focusFirstField();
    });
    els['auth-back-to-login-btn']?.addEventListener('click', () => {
      showGuestMode('login');
      setAlert('');
      focusFirstField();
    });
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

    window.addEventListener('focus', () => {
      verifySessionIfNeeded().catch(() => {});
    });

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        verifySessionIfNeeded().catch(() => {});
      }
    });
  }

  async function init() {
    if (state.initialized) {
      return {
        authenticated: isAuthenticated(),
        user: state.user,
        config: state.config
      };
    }

    if (state.readyPromise) return state.readyPromise;

    state.readyPromise = (async () => {
      cacheElements();
      bindEvents();
      renderUserState();
      await loadAuthConfig();
      window.BIDFinderAnalytics?.init?.();
      state.resetPasswordToken = readResetPasswordTokenFromUrl();
      syncGuestViewHeight();

      const restored = await restoreSession();
      markAuthInitialized();

      if (state.resetPasswordToken) {
        openAuthModal('reset-password');
      }

      const readyDetail = {
        authenticated: restored,
        user: state.user,
        config: state.config
      };
      emit('bidfinder:auth-ready', readyDetail);
      return readyDetail;
    })();

    return state.readyPromise;
  }

  function whenReady() {
    if (state.initialized) {
      return Promise.resolve({
        authenticated: isAuthenticated(),
        user: state.user,
        config: state.config
      });
    }
    return state.readyPromise || init();
  }

  window.bidfinderAuthorizedFetch = authorizedFetch;
  window.BIDFinderAuth = {
    init,
    whenReady,
    verifySession: () => verifySessionIfNeeded({ force: true }),
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
