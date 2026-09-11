(function () {
  const LOCAL_API_BASE_URL = 'http://127.0.0.1:8001';
  const PRODUCTION_API_BASE_URL = 'https://api.bidfinder.vn';

  const isLocal =
    window.location.protocol === 'file:' ||
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1';

  const configuredApiBase =
    typeof window.BIDFINDER_API_BASE_URL === 'string'
      ? window.BIDFINDER_API_BASE_URL.trim()
      : '';

  const apiBaseUrl = isLocal
    ? LOCAL_API_BASE_URL
    : (configuredApiBase || PRODUCTION_API_BASE_URL);
  const rollbackApiBaseUrl =
    typeof window.BIDFINDER_ROLLBACK_API_BASE_URL === 'string'
      ? window.BIDFINDER_ROLLBACK_API_BASE_URL.trim()
      : '';

  window.BIDFINDER_CONFIG = {
    ...(window.BIDFINDER_CONFIG || {}),
    apiBaseUrl,
    primaryApiBaseUrl: apiBaseUrl,
    backupApiBaseUrl: rollbackApiBaseUrl,
  };

  window.API_BASE_URL = apiBaseUrl;
  window.API_BACKUP_BASE_URL = rollbackApiBaseUrl;
})();
