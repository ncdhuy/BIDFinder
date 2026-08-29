(function () {
  const LOCAL_API_BASE_URL = 'http://127.0.0.1:8001';
  const CLOUD_RUN_API_BASE_URL = 'https://bidfinder-api-staging-774667987564.asia-southeast1.run.app'; //https://bidfinder.onrender.com
  const RENDER_BACKUP_API_BASE_URL = 'https://bidfinder.onrender.com';

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
    : (configuredApiBase || CLOUD_RUN_API_BASE_URL);

  window.BIDFINDER_CONFIG = {
    ...(window.BIDFINDER_CONFIG || {}),
    apiBaseUrl,
    primaryApiBaseUrl: CLOUD_RUN_API_BASE_URL,
    backupApiBaseUrl: RENDER_BACKUP_API_BASE_URL,
  };

  window.API_BASE_URL = apiBaseUrl;
  window.API_BACKUP_BASE_URL = RENDER_BACKUP_API_BASE_URL;
})();
