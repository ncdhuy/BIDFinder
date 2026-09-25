const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

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
assert.doesNotMatch(html, /dashboard-products-measure/);
assert.doesNotMatch(html, /Số gói thầu có chứa sản phẩm\./);
assert.match(html, /id="dashboard-timeline-chart"/);
assert.match(html, /id="dashboard-trend-grain"[\s\S]{0,320}value="year"[\s\S]{0,120}value="quarter"[\s\S]{0,120}value="month"/);
assert.doesNotMatch(html, /id="dashboard-price-chart"|id="dashboard-price-stats"/);
assert.match(html, /data-dashboard-widget="bidder_price_bands"/);
assert.match(html, /id="dashboard-bidder-price-bands"/);
assert.match(html, /Top nhà thầu trúng thầu/);
assert.match(html, /Top chủ đầu tư/);
assert.doesNotMatch(html, /Xếp hạng theo số lần trúng thầu trong vùng giá|Xếp theo tổng giá trị trúng thầu\./);
assert.match(html, /dashboard-investors-table dashboard-price-band-table dashboard-resizable-table/);
assert.match(html, /<th scope="col">Tên nhà thầu[\s\S]{0,300}Đơn giá phổ biến[\s\S]{0,300}Tổng giá trị/);
assert.match(html, /id="dashboard-top-investors"/);
assert.match(html, /class="dashboard-widget-title"[\s\S]{0,160}data-feather="map-pin"/);
assert.match(html, /class="dashboard-widget-title"[\s\S]{0,160}data-feather="bar-chart-2"/);
assert.match(html, /class="dashboard-widget-title"[\s\S]{0,160}data-feather="trending-up"/);
assert.match(html, /<span>Tổng giá trị trúng thầu theo thời gian<\/span>/);
assert.match(style, /\.dashboard-main-grid[\s\S]{0,180}grid-auto-rows: clamp\(300px, 34vh, 320px\)/);
assert.match(style, /\.dashboard-main-grid \{[\s\S]{0,120}grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
assert.match(style, /\.dashboard-secondary-grid[\s\S]{0,180}grid-auto-rows: clamp\(220px, 25vh, 250px\)/);
assert.match(style, /\.dashboard-secondary-grid \{\s*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);\s*grid-auto-rows: clamp\(220px, 25vh, 250px\)/);
assert.match(style, /#dashboard-province-map svg[\s\S]{0,120}display: block;[\s\S]{0,120}width: calc\(100% - 196px\);[\s\S]{0,100}height: 100%;/);
assert.match(style, /\.dashboard-widget-head\s*\{[^}]*border-bottom: 0/);
assert.match(script, /function hideNoDataMessage\(canvasId\)[\s\S]{0,240}msg\.remove\(\)/);
assert.match(style, /\.province-map-legend-items[\s\S]{0,120}flex-direction: column/);
assert.match(style, /#dashboard-province-map \.province-map-legend[\s\S]{0,180}width: min\(184px, 30%\);[\s\S]{0,100}padding: 8px 9px/);
assert.match(style, /#dashboard-province-map \.province-map-legend-swatch[\s\S]{0,160}width: 14px[\s\S]{0,60}height: 14px/);
assert.match(style, /#dashboard-province-map \.province-map-legend-label[\s\S]{0,100}font-size: 10\.5px/);
assert.doesNotMatch(style, /province-map-legend-scale|province-map-legend-labels/);
assert.match(style, /\.dashboard-product-bar[\s\S]{0,260}grid-template-columns: 26px minmax\(145px, 0\.85fr\) minmax\(120px, 1\.4fr\)/);
assert.match(style, /\.dashboard-product-value[\s\S]{0,220}grid-column: 3[\s\S]{0,160}gap: 8px/);
assert.match(style, /\.dashboard-product-track[\s\S]{0,180}height: 18px[\s\S]{0,100}background: var\(--product-bar-color/);
assert.doesNotMatch(style, /dashboard-product-bar::before/);
assert.doesNotMatch(script, /--bar-width/);
assert.match(script, /track\.style\.setProperty\('--product-bar-color', PROVINCE_MAP_BUCKET_COLORS\[colorIndex\]\)/);
assert.match(script, /track\.style\.width = `\$\{Math\.max\(2\.5, countRatio \* 86\)\}%`/);
assert.doesNotMatch(script, /dashboard-product-fill/);
assert.match(script, /dashboardTimelineGrain = 'year'/);
assert.match(script, /plugins: \[dashboardTimelineLabelsPlugin\]/);
assert.match(script, /pointRadius: 5[\s\S]{0,100}pointHoverRadius: 7/);
assert.match(script, /borderColor: '#1677e8'/);
assert.match(script, /function formatDashboardTrendLabel\(value, unit\)[\s\S]{0,220}toLocaleString\('vi-VN'/);
assert.match(script, /minimumFractionDigits: 1, maximumFractionDigits: 1/);
assert.match(script, /function formatDashboardCurrency\(value\)[\s\S]{0,520}minimumFractionDigits: 1, maximumFractionDigits: 1/);
assert.match(script, /function formatDashboardCount\(value\)[\s\S]{0,180}number\.toLocaleString\('vi-VN'\)/);
assert.match(script, /function formatDashboardBandPrice\(value\)/);
assert.match(script, /function renderDashboardBidderPriceBands\(analysis = \{\}\)/);
assert.doesNotMatch(script, /analysis\.requires_product_selection/);
assert.match(script, /setDashboardSelection\('bidder', bidderName\)/);
assert.match(script, /aria-pressed', String\(sameDashboardIdentity\(dashboardSelection\.bidder, bidderName\)\)/);
assert.match(script, /bidder: selection\?\.bidder \|\| null/);
assert.match(script, /const unit = String\(band\.unit \|\| ''\)\.trim\(\)/);
assert.doesNotMatch(script, /formatDashboardCount\(band\.distinct_win_count\)|band\.median_price/);
assert.match(script, /band\.corresponding_awarded_value/);
assert.match(script, /updateDashboardTimelineChart\(payload\?\.timeline \|\| \{\}\)/);
assert.doesNotMatch(script, /unit_price_distribution|dashboardPriceDistributionPlugin|dashboardHistogramScale|getDashboardPriceBinGeometry|dashboard-price-chart/);
assert.match(html, /id="dashboard-bidder-price-bands"/);
assert.match(html, /data-dashboard-widget="bidder_price_bands"/);

assert.match(script, /function formatDashboardTimelinePeriod\(period\)[\s\S]{0,260}`Q\$\{quarter\[2\]\}\/\$\{quarter\[1\]\}`[\s\S]{0,180}`\$\{month\[2\]\}\/\$\{month\[1\]\}`/);
assert.match(script, /labels: timelinePoints\.map\(point => formatDashboardTimelinePeriod\(point\.period\)\)/);
assert.match(script, /title: items => formatDashboardTimelinePeriod\(items\[0\]\?\.label \|\| ''\)/);
assert.doesNotMatch(script, /formatDashboardTrendLabel[\s\S]{0,180}` tỷ`/);
assert.match(script, /function getDashboardTrendUnit\(values = \[\]\)/);
assert.match(script, /label: 'Tỷ đồng'/);
assert.match(script, /ticks: \{ callback: value => formatDashboardTrendLabel\(value, trendUnit\) \}/);
assert.match(script, /chart\.options\.plugins\.dashboardTimelineLabels\.unit = trendUnit/);
assert.match(script, /labelStep = Math\.max\(1, Math\.ceil\(points\.length \/ 6\)\)/);
assert.match(script, /const labelY = Math\.max\(12, point\.y - 12\)/);
assert.match(script, /function updateDashboardTimelineChart\(timeline = \{\}\)/);
assert.match(script, /chart\.update\('none'\)/);
assert.match(script, /!Array\.isArray\(dashboardAnalyticsData\.timeline\?\.series\?\.\[grain\]\)/);
assert.match(script, /refreshDashboardAnalytics\(\{ force: true \}\)/);
assert.equal((style.match(/\.dashboard-products\s*\{/g) || []).length, 1, 'product chart has one layout rule');
assert.match(style, /\.dashboard-products \{[\s\S]{0,180}grid-template-rows: none;[\s\S]{0,40}grid-auto-rows: 24px/);
assert.match(style, /\.dashboard-products \{[\s\S]{0,240}align-content: start/);
assert.doesNotMatch(script, /--dashboard-product-rows/);
assert.match(style, /\.dashboard-products-widget\s*\{[\s\S]{0,140}grid-template-rows: auto minmax\(0, 1fr\)/);
assert.match(style, /\.dashboard-product-row \{[\s\S]{0,120}min-height: 0/);
assert.equal((html.match(/dashboard-resizable-table/g) || []).length, 2);
assert.match(html, /data-min-width="96" style="width: 44%"/);
assert.match(script, /function resizeDashboardTableColumns\(/);
assert.match(script, /handle\.addEventListener\('pointerdown'/);
assert.match(script, /handle\.addEventListener\('keydown'/);
const resizeSource = script.match(/function resizeDashboardTableColumns\([\s\S]*?\n\}/)?.[0];
assert.ok(resizeSource);
const resizeTable = vm.runInNewContext(`(${resizeSource})`);
const columnWidths = [40, 220, 120, 120];
const resizeColumns = columnWidths.map((width, index) => ({
  dataset: { minWidth: String([40, 96, 92, 76][index]) },
  style: {},
  getBoundingClientRect() { return { width: Number.parseFloat(this.style.width) || width }; }
}));
const resizeTableElement = {
  dataset: {}, style: {},
  getBoundingClientRect() { return { width: Number.parseFloat(this.style.width) || 500 }; },
  querySelectorAll() { return resizeColumns; },
  querySelector() { return { setAttribute() {} }; }
};
resizeTable(resizeTableElement, 1, 200);
assert.equal(resizeTableElement.style.width, '700px', 'expanding a column grows the scrollable table');
assert.equal(resizeColumns[1].style.width, '420px');
assert.equal(resizeColumns[2].style.width, '120px', 'neighboring column retains its width');
resizeTable(resizeTableElement, 1, -100);
assert.equal(resizeTableElement.style.width, '600px', 'dragging back reduces the table width');
resizeTable(resizeTableElement, 1, -1000);
assert.equal(resizeTableElement.style.width, '500px', 'table cannot shrink below its original width');
assert.equal(resizeColumns[1].style.width, '96px', 'column respects its minimum width');
assert.match(style, /\.dashboard-investors-table th,[\s\S]{0,240}text-overflow: ellipsis; white-space: nowrap/);
assert.match(script, /packageCell\.title = packageCell\.textContent/);
assert.match(script, /valueCell\.title = valueCell\.textContent/);
const captureDashboardSelectionVisualSource = script.match(/function captureDashboardSelectionVisual\(key, payload = \{\}\)[\s\S]*?\n\}/)?.[0];
assert.ok(captureDashboardSelectionVisualSource, 'selection source snapshot helper exists');
const captureDashboardSelectionVisual = vm.runInNewContext(`(${captureDashboardSelectionVisualSource})`, {
  dashboardSelectionSourceFields: {
    product: 'top_products', province: 'geography', investor: 'top_investors', bidder: 'bidder_price_band_analysis'
  }
});
const visualSnapshotPayload = {
  top_products: Array.from({ length: 12 }, (_, index) => ({ name: `P${index}` })),
  top_investors: Array.from({ length: 7 }, (_, index) => ({ name: `I${index}` })),
  geography: Array.from({ length: 63 }, (_, index) => ({ province: `Province${index}` })),
  bidder_price_band_analysis: { items: Array.from({ length: 8 }, (_, index) => ({ bidder_name: `B${index}` })) }
};
assert.equal(captureDashboardSelectionVisual('product', visualSnapshotPayload).length, 10);
assert.equal(captureDashboardSelectionVisual('investor', visualSnapshotPayload).length, 5);
assert.equal(captureDashboardSelectionVisual('province', visualSnapshotPayload).length, 63);
assert.equal(captureDashboardSelectionVisual('bidder', visualSnapshotPayload).items.length, 5);
assert.match(script, /function mergeDashboardTopRows\(baseRows = \[\], filteredRows = \[\], identityField, limit = Infinity\)/);
const mergeDashboardTopRowsSource = script.match(/function mergeDashboardTopRows\([\s\S]*?\n\}/)?.[0];
assert.ok(mergeDashboardTopRowsSource, 'top-widget merge helper exists');
const normalizeDashboardIdentitySource = script.match(/function normalizeDashboardIdentity\(value\)[\s\S]*?\n\}/)?.[0];
assert.ok(normalizeDashboardIdentitySource, 'dashboard name identity normalizer exists');
const normalizeDashboardIdentity = vm.runInNewContext(`(${normalizeDashboardIdentitySource})`);
const mergeDashboardTopRows = vm.runInNewContext(`(${mergeDashboardTopRowsSource})`, { normalizeDashboardIdentity });
const mergedTopRows = mergeDashboardTopRows(
  [{ name: 'A', count: 8 }, { name: 'B', count: 5 }, { name: 'C', count: 2 }],
  [{ name: 'a', count: 3 }],
  'name'
);
assert.deepEqual(JSON.parse(JSON.stringify(mergedTopRows)), [
  { name: 'A', count: 8, _dashboardFilterMatch: true },
  { name: 'B', count: 5, _dashboardFilterMatch: false },
  { name: 'C', count: 2, _dashboardFilterMatch: false }
]);
const mergedBidderRows = mergeDashboardTopRows(
  [{ bidder_name: 'Bidder A', corresponding_awarded_value: 90 }, { bidder_name: 'Bidder B', corresponding_awarded_value: 40 }],
  [{ bidder_name: 'Bidder B', corresponding_awarded_value: 12 }],
  'bidder_name'
);
assert.deepEqual(JSON.parse(JSON.stringify(mergedBidderRows)), [
  { bidder_name: 'Bidder A', corresponding_awarded_value: 90, _dashboardFilterMatch: false },
  { bidder_name: 'Bidder B', corresponding_awarded_value: 40, _dashboardFilterMatch: true }
]);
const mergedWithNewFilteredCategory = mergeDashboardTopRows(
  [{ name: 'A' }, { name: 'B' }, { name: 'C' }],
  [{ name: 'D', count: 7 }, { name: 'A', count: 4 }],
  'name',
  3
);
assert.deepEqual(JSON.parse(JSON.stringify(mergedWithNewFilteredCategory)), [
  { name: 'A', _dashboardFilterMatch: true },
  { name: 'B', _dashboardFilterMatch: false },
  { name: 'C', _dashboardFilterMatch: false }
]);
assert.match(script, /row\.dataset\.dashboardFilterMatch = String\(product\._dashboardFilterMatch !== false\)/);
assert.match(script, /row\.dataset\.dashboardFilterMatch = String\(investor\._dashboardFilterMatch !== false\)/);
assert.match(script, /row\.dataset\.dashboardFilterMatch = String\(band\._dashboardFilterMatch !== false\)/);
assert.match(style, /\.dashboard-price-band-row\.is-dimmed[\s\S]{0,80}filter: grayscale\(1\);[\s\S]{0,40}opacity: 0\.3/);
assert.match(style, /--dashboard-selected-fill: #cfe2fc/);
assert.match(style, /--dashboard-selected-border: #2674d8/);
assert.match(style, /\.dashboard-product-row\.is-selected \.dashboard-product-bar[\s\S]{0,180}border: 1px solid var\(--dashboard-selected-border\);[\s\S]{0,80}background: var\(--dashboard-selected-fill\)/);
assert.match(style, /\.dashboard-investor-row\.is-selected td \{[\s\S]{0,180}border-top: 1px solid var\(--dashboard-selected-border\);[\s\S]{0,100}border-bottom: 1px solid var\(--dashboard-selected-border\);[\s\S]{0,100}background: var\(--dashboard-selected-fill\)/);
assert.match(style, /\.dashboard-investor-row\.is-selected td:first-child \{[\s\S]{0,100}border-left: 1px solid var\(--dashboard-selected-border\)/);
assert.match(style, /\.dashboard-investor-row\.is-selected td:last-child \{[\s\S]{0,100}border-right: 1px solid var\(--dashboard-selected-border\)/);
assert.match(style, /\.dashboard-product-row\.is-selected \.dashboard-product-rank,[\s\S]{0,100}\.dashboard-investor-row\.is-selected \.dashboard-rank-badge/);
assert.equal((script.match(/rankBadge\.className = 'dashboard-rank-badge'/g) || []).length, 2);
assert.doesNotMatch(style, /saturate\(1\.15\) brightness\(0\.82\)/);
assert.doesNotMatch(html, /dashboard-selection-bar|dashboard-selection-chips|Đang khám phá:/);
assert.doesNotMatch(script, /renderDashboardSelections|dashboard-clear-selections/);
assert.doesNotMatch(style, /dashboard-selection-(bar|chips|chip)/);
assert.match(script, /Boolean\(selectedProduct\) && row\.dataset\.dashboardFilterMatch === 'false' && !isSelected/);
assert.match(script, /path\.classList\.toggle\('is-dimmed', Boolean\(selectedProvinceKey\) && !isSelected\)/);
assert.match(script, /const dashboardSelectionSourceFields = \{[\s\S]*product: 'top_products',[\s\S]*province: 'geography',[\s\S]*investor: 'top_investors',[\s\S]*bidder: 'bidder_price_band_analysis'/);
assert.match(script, /dashboardSelectionVisualData\[key\] = captureDashboardSelectionVisual\(key, dashboardAnalyticsData\)/);
assert.match(script, /function captureDashboardSelectionVisual\(key, payload = \{\}\)/);
assert.doesNotMatch(script, /dashboardTopVisualBaseData|captureDashboardTopVisualData|hasDashboardExplorationSelection/);
assert.match(script, /const displayPayload = \{ \.\.\.payload \}/);
assert.match(script, /if \(key === 'product'\) \{[\s\S]*mergeDashboardTopRows\(sourceData, payload\?\.top_products/);
assert.match(script, /else if \(key === 'investor'\) \{[\s\S]*mergeDashboardTopRows\(sourceData, payload\?\.top_investors/);
assert.match(script, /items: mergeDashboardTopRows\(/);
assert.equal((script.match(/Boolean\(selected(?:Product|Investor|Bidder)\) && row\.dataset\.dashboardFilterMatch === 'false' && !isSelected/g) || []).length, 3);
assert.match(script, /renderDashboardSummary\(payload\?\.summary \|\| \{\}\)/);
assert.match(script, /updateDashboardTimelineChart\(payload\?\.timeline \|\| \{\}\)/);
assert.match(script, /if \(!dashboardAnalyticsData\) \{[\s\S]{0,200}Đang tải dữ liệu…/);
assert.match(script, /if \(baseChanged\) \{\s*resetDashboardSelection\(\);\s*dashboardAnalyticsData = null;/);
assert.doesNotMatch(script, /window\.location\.reload\(|location\.reload\(/);
assert.match(style, /\.dashboard-context-chip-label[\s\S]{0,180}text-overflow: ellipsis/);
assert.match(style, /\.dashboard-header-row[\s\S]{0,180}grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\)/);
assert.match(style, /\.dashboard-context-bar[\s\S]{0,220}min-height: 42px/);
assert.doesNotMatch(html, /dashboard-status|Phân tích toàn bộ kết quả phù hợp/);
assert.doesNotMatch(script, /setDashboardStatus|Phân tích toàn bộ kết quả phù hợp/);
assert.doesNotMatch(html, /dashboard-kpi-unit/);
assert.match(style, /\.dashboard-kpi-icon[\s\S]{0,220}width: 44px[\s\S]{0,80}height: 44px/);
assert.match(style, /\.dashboard-kpi-label[\s\S]{0,120}color: var\(--dashboard-navy\)/);
assert.match(style, /\.dashboard-kpi-card strong[\s\S]{0,160}color: var\(--dashboard-navy\)/);
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
assert.match(script, /const baseChanged = Boolean\(refreshDashboardAnalytics\.lastBaseKey && refreshDashboardAnalytics\.lastBaseKey !== baseKey\);[\s\S]{0,100}if \(baseChanged\) \{\s*resetDashboardSelection\(\);\s*dashboardAnalyticsData = null;/);
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
assert.match(script, /tension: 0/);
assert.match(script, /function renderDashboardBidderPriceBands\(analysis = \{\}\)/);
assert.doesNotMatch(script, /Chọn một sản phẩm trong Top 10 để phân tích vùng đơn giá trúng phổ biến/);
assert.match(script, /updateDashboardTimelineChart\(payload\?\.timeline \|\| \{\}\)/);
assert.doesNotMatch(script, /P25|P75|unit_price_distribution|dashboardPriceDistributionPlugin|bidder_unit_price_series/);

assert.match(script, /dashboard-context-chip-label/);
assert.match(script, /dashboardAnalyticsData\?\.analytics_complete === false[\s\S]{0,220}Phân tích tối đa/);
assert.match(script, /function getDashboardSearchKeyword\(request = \{\}\)/);
assert.match(script, /const keywordFields = \[/);
assert.match(script, /searchForm\.fieldLabel\(fieldName\)/);
assert.match(script, /crossGroupProductKeyword/);
assert.match(script, /goodsKeyword/);
assert.doesNotMatch(script, /function formatDashboardFilterValue/);
assert.doesNotMatch(script, /function formatDashboardFilterLabel/);
assert.match(style, /--dashboard-navy: #122e5a/);
assert.match(style, /--dashboard-blue: #0f62d6/);
assert.match(script, /const PROVINCE_MAP_BUCKET_COLORS = \[/);
assert.match(script, /'#70acef'[\s\S]{0,80}'#dde2e6'/);
assert.match(script, /mapNoData: '#f2f4f6'/);
assert.match(script, /function getNiceProvinceScaleBoundary\(lower, upper\)/);
assert.match(script, /function buildProvinceMapColorBuckets\(values = \[\]\)/);
assert.match(script, /const distinctValues = \[\]/);
assert.doesNotMatch(script, /min: 500_000_000/);
assert.match(script, /const targetCount = positiveValues\.length \* group \/ bucketCount/);
const provinceScaleSource = [
  script.match(/const PROVINCE_MAP_BUCKET_COLORS = \[[\s\S]*?\];/)?.[0],
  ...['formatProvinceScaleValue', 'getNiceProvinceScaleBoundary', 'buildProvinceMapColorBuckets', 'getProvinceFill']
    .map(name => script.match(new RegExp(`function ${name}\\([\\s\\S]*?\\n\\}`))?.[0])
];
assert.ok(provinceScaleSource.every(Boolean), 'province scale functions are available for behavior tests');
const provinceScale = vm.runInNewContext(
  `${provinceScaleSource.join('\n')}\n({ buildProvinceMapColorBuckets, getProvinceFill, formatProvinceScaleValue })`,
  { CHART_THEME: { mapNoData: '#f2f4f6' } }
);
const oneProvinceBuckets = provinceScale.buildProvinceMapColorBuckets([1_000_000_000]);
assert.equal(oneProvinceBuckets[0].label, '1 tỷ');
assert.equal(oneProvinceBuckets.length, 2, 'one value produces one color and the no-data swatch');
assert.equal(provinceScale.getProvinceFill(1_000_000_000, oneProvinceBuckets), oneProvinceBuckets[0].color);
assert.equal(provinceScale.buildProvinceMapColorBuckets([1_000_000_000, 1_000_000_000])[0].label, '1 tỷ');
assert.equal(provinceScale.buildProvinceMapColorBuckets([1_234_567_890])[0].label, '1 tỷ 234 triệu 567 nghìn 890 đ');
assert.equal(provinceScale.formatProvinceScaleValue(34_500_000_000), '34 tỷ 500 triệu');
assert.equal(provinceScale.formatProvinceScaleValue(1_200_000_000), '1 tỷ 200 triệu');
assert.equal(provinceScale.formatProvinceScaleValue(600_000_000), '600 triệu');
const roundedBillionValues = [0.3, 0.6, 1, 2, 3, 6, 12, 25, 34.4, 34.6, 35.1, 40, 50, 60, 70, 80, 100, 120, 150, 200, 250]
  .map(value => value * 1_000_000_000);
const roundedBillionBuckets = provinceScale.buildProvinceMapColorBuckets(roundedBillionValues);
assert.ok(roundedBillionBuckets.some(bucket => bucket.min === 35_000_000_000));
assert.ok(roundedBillionBuckets.every(bucket => !bucket.label.includes('34 tỷ 500 triệu')));
assert.equal(new Set(roundedBillionValues.map(value => provinceScale.getProvinceFill(value, roundedBillionBuckets))).size, 7);
assert.notEqual(provinceScale.getProvinceFill(34_600_000_000, roundedBillionBuckets),
  provinceScale.getProvinceFill(35_100_000_000, roundedBillionBuckets));
const closeValues = [1_000_000_000, 1_100_000_000, 1_200_000_000];
const closeBuckets = provinceScale.buildProvinceMapColorBuckets(closeValues);
assert.equal(new Set(closeValues.map(value => provinceScale.getProvinceFill(value, closeBuckets))).size, 3);
assert.ok(closeBuckets.every(bucket => !/\d,\d/.test(bucket.label)));
const provinceValues = Array.from({ length: 21 }, (_, index) => (index + 1) * 1_000_000);
const evenBuckets = provinceScale.buildProvinceMapColorBuckets(provinceValues);
assert.equal(evenBuckets.length, 8);
assert.equal(new Set(evenBuckets.slice(0, -1).map(bucket => bucket.color)).size, 7);
const colorCounts = new Map(evenBuckets.slice(0, -1).map(bucket => [bucket.color, 0]));
provinceValues.forEach(value => {
  const color = provinceScale.getProvinceFill(value, evenBuckets);
  colorCounts.set(color, colorCounts.get(color) + 1);
});
assert.ok([...colorCounts.values()].every(count => count >= 2 && count <= 4), 'province colors stay reasonably balanced');
const skewedValues = [...provinceValues, 1_000_000_000_000];
const skewedBuckets = provinceScale.buildProvinceMapColorBuckets(skewedValues);
assert.ok(new Set(skewedValues.map(value => provinceScale.getProvinceFill(value, skewedBuckets))).size >= 6,
  'an outlier must not collapse the map into one color');
assert.ok(skewedBuckets.every(bucket => !/\d,\d/.test(bucket.label)), 'legend labels use integer values');
assert.equal(provinceScale.getProvinceFill(0, skewedBuckets), '#f2f4f6');
assert.match(script, /function appendFeaturedProvinceLabels\(svg, valueByProvince, options = \{\}\)/);
assert.match(script, /function getProvinceMainlandAnchor\(svg, path, fallbackBox\)/);
assert.match(script, /const labelY = anchorY/);
assert.match(script, /const titleSize = 18 \* pixelsToUnits;[\s\S]{0,80}const valueSize = 18 \* pixelsToUnits/);
assert.match(script, /preserveAspectRatio', 'xMidYMid meet'/);
assert.match(script, /getComputedTextLength/);
assert.match(script, /connector\.setAttribute\('x2', String\(labelX\)\)/);
assert.match(script, /const lineGap = 6 \* pixelsToUnits/);
assert.match(script, /const labelGap = 88 \* pixelsToUnits/);
assert.match(script, /anchor\.setAttribute\('r', String\(6 \* pixelsToUnits\)\)/);
assert.match(style, /\.dashboard-widget-title[\s\S]{0,180}color: var\(--dashboard-navy\)/);
assert.match(style, /\.dashboard-widget-title svg[\s\S]{0,180}color: var\(--dashboard-blue\)/);
assert.match(style, /\.dashboard-widget-head h3[\s\S]{0,120}font-size: 16px/);
assert.match(html, /dashboard-price-band-table dashboard-resizable-table/);
assert.match(style, /\.dashboard-investors-table thead\s*\{\s*background: #edf4fc/);
assert.match(style, /\.dashboard-investors-table th\s*\{[\s\S]{0,180}font-size: 12px/);
assert.match(style, /\.dashboard-investors-table \{ min-width: 100%; height: auto; flex: 0 0 auto; align-self: flex-start; border-collapse: separate; border-spacing: 0; font-size: 11\.5px; \}/);
assert.match(style, /\.dashboard-price-widget \.dashboard-widget-head,[\s\S]{0,120}padding-bottom: 3px/);
assert.match(style, /\.dashboard-investors-wrap\s*\{\s*display: flex; min-height: 0; overflow-x: auto; overflow-y: auto; padding: 3px 10px 8px/);
assert.match(style, /\.dashboard-investors-table th,[\s\S]{0,80}\.dashboard-investors-table td \{ padding: 5px 8px; vertical-align: middle/);
assert.match(style, /\.dashboard-investor-link\s*\{\s*line-height: 1\.5/);
assert.match(style, /\.dashboard-investors-table th:nth-child\(3\),[\s\S]{0,120}text-align: center/);
assert.match(style, /\.dashboard-price-bands-wrap \.dashboard-price-band-table td:nth-child\(3\)\s*\{\s*text-align: center/);
assert.doesNotMatch(style, /dashboard-price-band-(bidder|price|total)/);

assert.match(style, /\.vietnam-province-map[\s\S]{0,320}background: transparent/);
assert.match(style, /\.province-map-feature-label[\s\S]{0,180}pointer-events: none/);
assert.match(style, /#dashboard-province-map svg[\s\S]{0,180}width: calc\(100% - 196px\)/);
assert.match(style, /#dashboard-province-map \.province-map-legend-label[\s\S]{0,100}font-size: 10\.5px/);
assert.doesNotMatch(html, /Phân bổ theo địa điểm trong toàn bộ kết quả phù hợp/);
assert.match(style, /\.dashboard-context-chip-label[\s\S]{0,160}text-overflow: ellipsis/);
assert.match(style, /color: #1d78e9;[\s\S]{0,50}background: #dcecff/);

const setSelectionSource = script.match(/function setDashboardSelection\(key, value\)[\s\S]*?\n\}/)?.[0];
assert.ok(setSelectionSource);
const scheduled = [];
let refreshCount = 0;
let abortCount = 0;
const selectionContext = {
  dashboardSelection: { product: null, province: null, investor: null, bidder: null },
  dashboardSelectionVisualData: {},
  dashboardSelectionSourceFields: {},
  dashboardAnalyticsData: null,
  dashboardAnalyticsController: { abort() { abortCount += 1; } },
  dashboardAnalyticsVersion: 0,
  dashboardAnalyticsRefreshTimer: null,
  sameDashboardIdentity: (left, right) => left === right,
  syncDashboardSelectionVisuals() {},
  isDashboardActive: () => true,
  clearTimeout(id) { if (id != null) scheduled[id].cancelled = true; },
  setTimeout(callback) { scheduled.push({ callback, cancelled: false }); return scheduled.length - 1; },
  refreshDashboardAnalytics() { refreshCount += 1; }
};
const setSelection = vm.runInNewContext(`(${setSelectionSource})`, selectionContext);
setSelection('product', 'A');
setSelection('product', 'B');
scheduled.filter(item => !item.cancelled).forEach(item => item.callback());
assert.equal(refreshCount, 1, 'rapid selections issue one dashboard request');
assert.equal(abortCount, 2, 'both selections invalidate the older request');

const renderDashboardAnalyticsSource = script.match(/function renderDashboardAnalytics\(payload\)[\s\S]*?\n\}/)?.[0];
assert.ok(renderDashboardAnalyticsSource);
const basePayload = {
  summary: {}, timeline: {}, geography: [],
  top_products: Array.from({ length: 10 }, (_, index) => ({ name: `P${index}`, count: 10 - index })),
  top_investors: Array.from({ length: 5 }, (_, index) => ({ name: `I${index}` })),
  bidder_price_band_analysis: { items: Array.from({ length: 5 }, (_, index) => ({ bidder_name: `B${index}` })) }
};
const rendered = {};
const explorationContext = {
  dashboardSelection: { product: null, province: null, investor: null, bidder: null },
  dashboardSelectionVisualData: {},
  dashboardSelectionSourceFields: {
    product: 'top_products', province: 'geography', investor: 'top_investors', bidder: 'bidder_price_band_analysis'
  },
  dashboardAnalyticsData: basePayload,
  dashboardAnalyticsController: null,
  dashboardAnalyticsVersion: 0,
  sameDashboardIdentity: (left, right) => left === right,
  captureDashboardSelectionVisual,
  mergeDashboardTopRows,
  syncDashboardSelectionVisuals() {},
  isDashboardActive: () => false,
  renderDashboardSummary() {},
  renderDashboardBaseContext() {},
  renderDashboardMap() {},
  renderDashboardProducts(rows) { rendered.products = rows; },
  renderDashboardInvestors(rows) { rendered.investors = rows; },
  renderDashboardBidderPriceBands(data) { rendered.bidders = data.items; },
  updateDashboardTimelineChart() {}
};
const exploration = vm.runInNewContext(
  `${setSelectionSource}\n${renderDashboardAnalyticsSource}\n({ setDashboardSelection, renderDashboardAnalytics })`,
  explorationContext
);
exploration.setDashboardSelection('bidder', 'B0');
assert.deepEqual(Object.keys(explorationContext.dashboardSelectionVisualData), ['bidder']);
const filteredPayload = {
  ...basePayload,
  top_products: basePayload.top_products.slice(0, 2),
  top_investors: basePayload.top_investors.slice(0, 1),
  bidder_price_band_analysis: { items: basePayload.bidder_price_band_analysis.items.slice(0, 1) }
};
exploration.renderDashboardAnalytics(filteredPayload);
assert.deepEqual([rendered.products.length, rendered.investors.length, rendered.bidders.length], [2, 1, 5],
  'only the selected bidder table keeps its original rows');
assert.equal(rendered.bidders.filter(row => row._dashboardFilterMatch === false).length, 4);
assert.equal(rendered.products.some(row => row._dashboardFilterMatch === false), false,
  'filtered product results contain no dimmed leftovers');
exploration.setDashboardSelection('investor', 'I0');
assert.equal(explorationContext.dashboardSelectionVisualData.investor.length, 1,
  'a newly selected table captures its current filtered rows');
exploration.renderDashboardAnalytics({ ...filteredPayload, top_products: filteredPayload.top_products.slice(0, 1) });
assert.deepEqual([rendered.products.length, rendered.investors.length, rendered.bidders.length], [1, 1, 5]);
exploration.setDashboardSelection('bidder', 'B0');
exploration.renderDashboardAnalytics(filteredPayload);
assert.deepEqual([rendered.products.length, rendered.investors.length, rendered.bidders.length], [2, 1, 1],
  'deselected bidder table uses filtered results');
exploration.setDashboardSelection('investor', 'I0');
exploration.renderDashboardAnalytics(basePayload);
assert.equal(Object.keys(explorationContext.dashboardSelectionVisualData).length, 0);
exploration.setDashboardSelection('product', 'P0');
exploration.renderDashboardAnalytics(filteredPayload);
assert.deepEqual([rendered.products.length, rendered.investors.length, rendered.bidders.length], [10, 1, 1],
  'the selected product chart keeps its original geometry while other tables filter');
exploration.setDashboardSelection('product', 'P0');
exploration.setDashboardSelection('product', 'P1');
exploration.renderDashboardAnalytics(filteredPayload);
assert.equal(rendered.products.length, 10, 'rapid reselection before the clear response preserves product rows');

console.log('Dashboard analytics contract passed');
