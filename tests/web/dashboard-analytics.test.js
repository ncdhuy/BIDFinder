const assert = require('node:assert/strict');
const fs = require('node:fs');

const script = fs.readFileSync('apps/web/script.js', 'utf8');
const html = fs.readFileSync('apps/web/index.html', 'utf8');
const style = fs.readFileSync('apps/web/style.css', 'utf8');

assert.match(html, /data-view="dashboard-panel"/);
assert.match(html, /Dashboard phân tích kết quả tìm kiếm/);
assert.match(html, /class="dashboard-header-row"/);
assert.match(html, /class="dashboard-title-icon"[\s\S]{0,140}data-feather="bar-chart-2"/);
assert.match(html, /class="dashboard-context-bar"[\s\S]{0,220}data-feather="filter"/);
assert.match(html, /Bộ lọc đang áp dụng:/);
assert.match(html, /data-dashboard-kpi="total_awarded_value"/);
assert.match(html, /id="dashboard-province-map"/);
assert.match(html, /id="dashboard-top-products"/);
assert.match(html, /id="dashboard-timeline-chart"/);
assert.match(html, /id="dashboard-price-chart"/);
assert.match(html, /id="dashboard-top-investors"/);
assert.match(style, /\.dashboard-main-grid[\s\S]{0,180}grid-auto-rows: clamp\(300px, 34vh, 320px\)/);
assert.match(style, /\.dashboard-secondary-grid[\s\S]{0,180}grid-auto-rows: clamp\(220px, 25vh, 250px\)/);
assert.match(style, /#dashboard-province-map svg[\s\S]{0,120}display: block;[\s\S]{0,80}width: 100%;[\s\S]{0,40}height: 100%;/);
assert.match(style, /\.dashboard-product-bar[\s\S]{0,260}grid-template-rows: auto 4px/);
assert.match(style, /\.dashboard-product-track[\s\S]{0,220}border-radius: 4px/);
assert.match(style, /\.dashboard-selection-bar\[hidden\][\s\S]{0,60}display: none/);
assert.match(style, /\.dashboard-selection-chip-label[\s\S]{0,180}text-overflow: ellipsis/);
assert.match(style, /\.dashboard-header-row[\s\S]{0,180}grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\)/);
assert.match(style, /\.dashboard-context-bar[\s\S]{0,220}min-height: 42px/);
assert.match(style, /\.dashboard-header-status:empty[\s\S]{0,40}display: none/);
assert.match(style, /\.legacy-pagination\.is-dashboard-hidden\s*\{\s*display: none/);

assert.match(script, /function buildDashboardAnalyticsRequest\(request = currentQueryRequest, selection = dashboardSelection\)/);
assert.match(script, /columnFilters: request\?\.columnFilters \|\| \{\}/);
assert.match(script, /dashboardSelection: \{/);
assert.match(script, /getAuthorizedFetch\(\)\(`\$\{API_BASE_URL\}\/api\/dashboard-analytics`/);
assert.doesNotMatch(script, /refreshDashboardAnalytics[\s\S]{0,1800}requireAuthenticatedSession\('login', 'full_query'\)/);
assert.match(script, /dashboardAnalyticsController\?\.abort\(\)/);
assert.match(script, /function setDashboardSelection\(key, value\)/);
assert.match(script, /onProvinceSelect: province => setDashboardSelection\('province', province\)/);
assert.match(script, /setDashboardSelection\('product', product\.name\)/);
assert.match(script, /setDashboardSelection\('investor', investor\.name\)/);
assert.match(script, /function syncDashboardSelectionVisuals\(\)/);
assert.match(script, /row\.dataset\.dashboardProduct = product\.name/);
assert.match(script, /row\.dataset\.dashboardInvestor = investor\.name/);
assert.match(script, /const nextValue = value \? String\(value\)\.trim\(\) : ''/);
assert.match(script, /dashboardAnalyticsVersion \+= 1;[\s\S]{0,120}refreshDashboardAnalytics\.lastRequestKey = ''/);
assert.match(script, /const controller = new AbortController\(\)/);
assert.match(script, /signal: controller\.signal/);
assert.match(script, /if \(refreshDashboardAnalytics\.lastBaseKey && refreshDashboardAnalytics\.lastBaseKey !== baseKey\) \{\s*resetDashboardSelection\(\);/);
assert.match(script, /function getDashboardBaseRequest\(request = currentQueryRequest\)[\s\S]{0,260}delete base\.page;[\s\S]{0,80}delete base\.limit;/);
assert.match(script, /if \(!hasActiveQueryFilters\(currentQueryRequest\)[\s\S]{0,360}renderDashboardEmpty\(\);/);
assert.match(script, /const leavingDashboard = activeButton\?\.getAttribute\('data-view'\) === 'dashboard-panel'/);
assert.match(script, /path\.setAttribute\('role', 'button'\)/);
assert.match(script, /path\.addEventListener\('keydown', event =>/);
assert.match(script, /legacy-pagination[^\n]*is-dashboard-hidden/);
assert.match(script, /Tổng giá trị trúng thầu/);
const selectionResetSource = script.slice(
  script.indexOf('function resetDashboardSelection'),
  script.indexOf('function getDashboardBaseRequest')
);
assert.doesNotMatch(selectionResetSource, /currentQueryRequest/);
assert.match(script, /function renderDashboardEmpty\(/);
assert.match(script, /analytics_complete/);
assert.match(script, /tension: 0/);

console.log('Dashboard analytics contract passed');
