(function () {
  const CONFIG = window.BIDFINDER_POSTHOG_CONFIG || {};
  const SAFE_USER_FIELDS = ['id', 'user_id', 'email', 'full_name', 'work_unit', 'position', 'auth_provider'];
  let initialized = false;
  let pending = [];

  function isConfigured() {
    return Boolean(CONFIG.enabled && CONFIG.apiKey && CONFIG.apiHost);
  }

  function loadPostHogSnippet() {
    if (!isConfigured() || window.posthog?.__loaded) return;

    !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group identify setPersonProperties setPersonPropertiesForFlags resetPersonPropertiesForFlags resetGroups onFeatureFlags addFeatureFlagsHandler onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
    window.posthog.__loaded = true;
  }

  function init() {
    if (initialized || !isConfigured()) return false;

    loadPostHogSnippet();

    window.posthog.init(CONFIG.apiKey, {
      api_host: CONFIG.apiHost,
      ui_host: CONFIG.uiHost,
      defaults: CONFIG.defaults,
      debug: Boolean(CONFIG.debug),
      autocapture: Boolean(CONFIG.autocapture),
      capture_pageview: false,
      person_profiles: CONFIG.personProfiles || 'identified_only'
    });

    initialized = true;
    flush();

    if (CONFIG.capturePageviews !== false) {
      page();
    }

    return true;
  }

  function sanitizeProperties(properties = {}) {
    const safe = {};

    Object.entries(properties || {}).forEach(([key, value]) => {
      if (value == null) return;
      if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        safe[key] = value;
      }
    });

    safe.path = window.location.pathname || '/';
    safe.host = window.location.host || '';
    return safe;
  }

  function getUserId(user = {}) {
    return String(user.id || user.user_id || user.email || '').trim();
  }

  function sanitizeUser(user = {}) {
    const safe = {};

    SAFE_USER_FIELDS.forEach((field) => {
      const value = user?.[field];
      if (value == null || value === '') return;
      safe[field] = value;
    });

    return safe;
  }

  function flush() {
    if (!initialized || !window.posthog) return;

    pending.forEach(([eventName, properties]) => {
      window.posthog.capture(eventName, properties);
    });
    pending = [];
  }

  function track(eventName, properties = {}) {
    if (!eventName || !isConfigured()) return;

    const safeProperties = sanitizeProperties(properties);
    if (!initialized) {
      pending.push([eventName, safeProperties]);
      return;
    }

    window.posthog.capture(eventName, safeProperties);
  }

  function identify(user) {
    if (!isConfigured() || CONFIG.identifyAuthenticatedUsers === false) return;

    const distinctId = getUserId(user);
    if (!distinctId) return;

    const safeUser = sanitizeUser(user);
    if (!initialized) init();
    window.posthog?.identify(distinctId, safeUser);
  }

  function reset() {
    if (!isConfigured()) return;
    window.posthog?.reset?.();
  }

  function page(properties = {}) {
    track('$pageview', {
      title: document.title || 'BIDFinder',
      ...properties
    });
  }

  function countFilters(queryRequest = {}) {
    const filters = queryRequest.filters || {};
    return Object.values(filters).reduce((count, value) => {
      if (value == null) return count;
      if (Array.isArray(value)) return count + (value.length ? 1 : 0);
      if (typeof value === 'string') return count + (value.trim() ? 1 : 0);
      if (typeof value === 'object' && Array.isArray(value.tokens)) return count + (value.tokens.length ? 1 : 0);
      return count + 1;
    }, 0);
  }

  function trackSearchSubmitted(queryRequest = {}, options = {}) {
    track('search_submitted', {
      scope: queryRequest.scope || 'all',
      search_mode: options.searchMode === 'full' ? 'full' : 'standard',
      filter_count: countFilters(queryRequest)
    });
  }

  function trackSearchCompleted(result = {}) {
    const total = Number(result.total_count || 0);
    const df1Displayed = Number(result.df1?.displayed || result.df1?.data?.length || 0);
    const df2Displayed = Number(result.df2?.displayed || result.df2?.data?.length || 0);

    track('search_completed', {
      search_mode: result.search_mode === 'full' ? 'full' : 'standard',
      total_count: total,
      displayed_count: df1Displayed + df2Displayed,
      total_count_exact: result.total_count_exact !== false,
      has_more: Boolean(result.df1?.has_more || result.df2?.has_more)
    });
  }

  function status() {
    const posthogLoaded = Boolean(window.posthog);
    return {
      configured: isConfigured(),
      initialized,
      posthogLoaded,
      pendingEvents: pending.length,
      apiHost: CONFIG.apiHost || '',
      debug: Boolean(CONFIG.debug),
      distinctId: window.posthog?.get_distinct_id?.() || null,
      optedOut: window.posthog?.has_opted_out_capturing?.() || false,
      currentUrl: window.location.href
    };
  }

  function debugCapture() {
    init();
    track('bidfinder_debug_event', {
      source: 'manual_console_test',
      timestamp: new Date().toISOString()
    });
    return status();
  }

  window.BIDFinderAnalytics = {
    init,
    identify,
    reset,
    page,
    track,
    trackSearchSubmitted,
    trackSearchCompleted,
    status,
    debugCapture,
    isEnabled: isConfigured
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
