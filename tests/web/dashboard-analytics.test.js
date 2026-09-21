const assert = require('node:assert/strict');
const fs = require('node:fs');

const script = fs.readFileSync('apps/web/script.js', 'utf8');
const html = fs.readFileSync('apps/web/index.html', 'utf8');

assert.match(html, /data-view="dashboard-panel"/);
assert.match(html, /Dashboard phân tích kết quả tìm kiếm/);
assert.match(html, /data-dashboard-kpi="total_awarded_value"/);
assert.match(html, /id="dashboard-province-map"/);
assert.match(html, /id="dashboard-top-products"/);
assert.match(html, /id="dashboard-timeline-chart"/);
assert.match(html, /id="dashboard-price-chart"/);
assert.match(html, /id="dashboard-top-investors"/);

assert.match(script, /function buildDashboardAnalyticsRequest\(request = currentQueryRequest, selection = dashboardSelection\)/);
assert.match(script, /columnFilters: request\?\.columnFilters \|\| \{\}/);
assert.match(script, /dashboardSelection: \{/);
assert.match(script, /getAuthorizedFetch\(\)\(`\$\{API_BASE_URL\}\/api\/dashboard-analytics`/);
assert.match(script, /dashboardAnalyticsController\?\.abort\(\)/);
assert.match(script, /function setDashboardSelection\(key, value\)/);
assert.match(script, /onProvinceSelect: province => setDashboardSelection\('province', province\)/);
assert.match(script, /setDashboardSelection\('product', product\.name\)/);
assert.match(script, /setDashboardSelection\('investor', investor\.name\)/);
assert.match(script, /function renderDashboardEmpty\(/);
assert.match(script, /analytics_complete/);
assert.match(script, /tension: 0/);

console.log('Dashboard analytics contract passed');
