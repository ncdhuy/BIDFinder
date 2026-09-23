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
assert.match(html, /id="dashboard-price-chart"/);
assert.match(html, /id="dashboard-price-stats"/);
assert.match(html, /data-dashboard-widget="unit_price_distribution"/);
assert.match(html, /Phân bố đơn giá trúng thầu/);
assert.doesNotMatch(html, /Top 5 nhà thầu theo tổng giá trị trúng thầu/);
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
assert.match(style, /\.dashboard-map-widget \.dashboard-widget-head[\s\S]{0,100}border-bottom: 0/);
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
assert.match(script, /function formatDashboardPriceAxis\(value\)[\s\S]{0,180}minimumFractionDigits: 1, maximumFractionDigits: 1/);
assert.match(script, /function formatDashboardCompactPrice\(value\)[\s\S]{0,360}triệu[\s\S]{0,120}nghìn/);
const compactPriceFormatterSource = script.match(/function formatDashboardCompactPrice\(value\) \{[\s\S]*?\n\}/)?.[0];
const formatDashboardCompactPrice = vm.runInNewContext(`(${compactPriceFormatterSource})`);
assert.equal(formatDashboardCompactPrice(10_000), '10 nghìn');
assert.equal(formatDashboardCompactPrice(500_000), '500 nghìn');
assert.equal(formatDashboardCompactPrice(1_000_000), '1 triệu');
assert.equal(formatDashboardCompactPrice(999_999), '1 triệu');
assert.match(script, /function formatProvinceScaleValue\(value\)[\s\S]{0,260}minimumFractionDigits: 1, maximumFractionDigits: 1/);
const markerDetailsSource = script.match(/function getDashboardPriceMarkerPosition\(chartArea, bins, value\) \{[\s\S]*?\n\}/)?.[0];
const markerPositionSource = script.match(/function getDashboardPriceMarkerX\(chartArea, bins, value\) \{[\s\S]*?\n\}/)?.[0];
const { getDashboardPriceMarkerX, getDashboardPriceMarkerPosition } = vm.runInNewContext(
    `(() => { ${markerDetailsSource}; ${markerPositionSource}; return { getDashboardPriceMarkerX, getDashboardPriceMarkerPosition }; })()`
);
const unevenMarkerBins = [
    { min: 0, max: 10 }, { min: 10, max: 110 }, { min: 110, max: 1_110 },
    { min: 1_110, max: 11_110 }, { min: 11_110, max: 111_110 },
    { min: 111_110, max: 1_111_110 }, { min: 1_111_110, max: 11_111_110 }
];
assert.equal(getDashboardPriceMarkerX({ left: 100, right: 800 }, unevenMarkerBins, 60), 250);
const coreAndOverflowBins = [
    { min: 0, max: 100 }, { min: 100, max: 200 }, { min: 200, max: 300 },
    { min: 300, max: 400 }, { min: 400, max: 500 }, { min: 500, max: 600 },
    { min: 600, max: 1_000_000_000_000, overflow: true }
];
assert.equal(getDashboardPriceMarkerPosition({ left: 100, right: 800 }, coreAndOverflowBins, 150).x, 250);
const clampedQuartile = getDashboardPriceMarkerPosition({ left: 100, right: 800 }, coreAndOverflowBins, 10_000);
assert.equal(clampedQuartile.x, 750);
assert.equal(clampedQuartile.clamped, true);
assert.equal(clampedQuartile.cutoff, 600);
const priceLabelHelpers = script.match(/function getDashboardPriceLabelParts\(value\) \{[\s\S]*?\n\}[\s\S]*?function formatDashboardPriceBinLabel\(bin, index, bins\) \{[\s\S]*?\n\}/)?.[0];
const { formatDashboardPriceBinLabel } = vm.runInNewContext(`(() => { ${priceLabelHelpers}; return { formatDashboardPriceBinLabel }; })()`);
const readablePriceBins = [
    { min: 0, max: 50_000 }, { min: 50_000, max: 100_000 }, { min: 100_000, max: 200_000 },
    { min: 200_000, max: 500_000 }, { min: 500_000, max: 1_000_000 },
    { min: 1_000_000, max: 2_000_000 }, { min: 2_000_000, max: 4_000_000, overflow: true }
];
assert.equal(readablePriceBins.length, 7);
assert.equal(formatDashboardPriceBinLabel(readablePriceBins[0], 0, readablePriceBins), '< 50 nghìn');
assert.equal(JSON.stringify(formatDashboardPriceBinLabel(readablePriceBins[1], 1, readablePriceBins)), JSON.stringify(['50–100', 'nghìn']));
assert.equal(formatDashboardPriceBinLabel(readablePriceBins[6], 6, readablePriceBins), '> 2 triệu');
assert.match(script, /unit_price_distribution/);
assert.match(script, /type: 'line'/);
assert.match(script, /const dashboardPriceDistributionPlugin =/);
assert.match(script, /key: 'p25', label: 'P25', color: '#16a34a'/);
assert.match(script, /key: 'median', label: 'Trung vị', color: '#1677e8'/);
assert.match(script, /key: 'p75', label: 'P75', color: '#f97316'/);
assert.match(script, /chart\.getDatasetMeta\(0\)\?\.data\.forEach/);
const priceStatsRendererSource = script.slice(
    script.indexOf('function renderDashboardPriceStats'),
    script.indexOf('function getDashboardTimelinePoints')
);
assert.match(priceStatsRendererSource, /\['Mean', 'mean'\], \['Median', 'median'\], \['Min', 'min'\], \['Max', 'max'\]/);
assert.doesNotMatch(priceStatsRendererSource, /P25|P75|IQR/);
assert.match(priceStatsRendererSource, /Các đơn giá ngoại lệ phía trên ngưỡng hiển thị được gộp vào cột cuối/);
const priceChartSource = script.slice(
  script.indexOf('async function renderDashboardCharts'),
  script.indexOf('function updateDashboardTimelineChart')
);
assert.match(priceChartSource, /plugins: \[dashboardPriceDistributionPlugin\]/);
assert.match(priceChartSource, /type: 'bar'/);
assert.match(priceChartSource, /priceBinLabels = priceBins\.map/);
assert.match(priceChartSource, /overflow: bin\?\.overflow === true/);
assert.match(priceChartSource, /maxTicksLimit: 7/);
assert.match(priceChartSource, /dashboardPriceDistribution: \{ bins: priceBins, statistics: priceStats \}/);
assert.match(priceChartSource, /title: items => items\[0\]\?\.label/);
assert.match(priceChartSource, /Số gói thầu:/);
assert.match(priceChartSource, /renderDashboardPriceStats\(hasPriceDistribution \? priceStats : null, priceBins\)/);
assert.doesNotMatch(priceChartSource, /bidder_unit_price_series|dashboardBidderPriceLabels|type: 'logarithmic'/);
assert.match(script, /function formatDashboardTimelinePeriod\(period\)[\s\S]{0,260}`Q\$\{quarter\[2\]\}\/\$\{quarter\[1\]\}`[\s\S]{0,180}`\$\{month\[2\]\}\/\$\{month\[1\]\}`/);
assert.match(script, /labels: timelinePoints\.map\(point => formatDashboardTimelinePeriod\(point\.period\)\)/);
assert.match(script, /title: items => formatDashboardTimelinePeriod\(items\[0\]\?\.label \|\| ''\)/);
assert.doesNotMatch(script, /formatDashboardTrendLabel[\s\S]{0,180}` tỷ`/);
assert.match(script, /function getDashboardTrendUnit\(values = \[\]\)/);
assert.match(script, /label: 'Tỷ đồng'/);
assert.match(script, /ticks: \{ callback: value => formatDashboardTrendLabel\(value, trendUnit\) \}/);
assert.match(script, /chart\.options\.plugins\.dashboardTimelineLabels\.unit = trendUnit/);
assert.match(script, /labelStep = Math\.max\(1, Math\.ceil\(points\.length \/ 6\)\)/);
assert.match(script, /function updateDashboardTimelineChart\(timeline = \{\}\)/);
assert.match(script, /chart\.update\('none'\)/);
assert.match(script, /!Array\.isArray\(dashboardAnalyticsData\.timeline\?\.series\?\.\[grain\]\)/);
assert.match(script, /refreshDashboardAnalytics\(\{ force: true \}\)/);
assert.match(style, /\.dashboard-products[\s\S]{0,160}justify-content: space-between/);
assert.match(style, /\.dashboard-product-row\.is-selected \.dashboard-product-bar[\s\S]{0,180}box-shadow: inset 0 0 0 1px var\(--dashboard-navy\)/);
assert.doesNotMatch(style, /saturate\(1\.15\) brightness\(0\.82\)/);
assert.match(style, /\.dashboard-selection-bar\[hidden\][\s\S]{0,60}display: none/);
assert.match(style, /\.dashboard-selection-chip-label[\s\S]{0,180}text-overflow: ellipsis/);
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
assert.match(script, /tension: 0/);
assert.match(script, /key: 'p25', label: 'P25'/);
assert.match(script, /key: 'median', label: 'Trung vị', color: '#1677e8'/);
assert.match(script, /key: 'p75', label: 'P75'/);
assert.match(script, /container\.title = `Min: \$\{minimum\} đ · Max: \$\{maximum\} đ\.\$\{overflowNote\}`/);
assert.match(script, /renderDashboardCharts\(payload\?\.timeline \|\| \{\}, payload\?\.unit_price_distribution \|\| \{\}\)/);
assert.doesNotMatch(script, /dashboardBidderPriceLabels|truncateDashboardBidderLabel|bidder_unit_price_series/);
assert.match(script, /dashboard-context-chip-label/);
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
assert.match(script, /function getNiceProvinceScaleStep\(maxValue, targetBucketCount = 7\)/);
assert.match(script, /function buildProvinceMapColorBuckets\(values = \[\]\)/);
assert.match(script, /Math\.ceil\(rawUpper \/ roundingStep\) \* roundingStep/);
assert.doesNotMatch(script, /min: 500_000_000/);
assert.match(script, /const quantileIndex = Math\.min/);
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
assert.match(style, /\.dashboard-price-stats[\s\S]{0,180}position: absolute/);
assert.match(style, /\.dashboard-price-stat strong[\s\S]{0,120}color: var\(--dashboard-navy\)/);
assert.match(style, /\.vietnam-province-map[\s\S]{0,320}background: transparent/);
assert.match(style, /\.province-map-feature-label[\s\S]{0,180}pointer-events: none/);
assert.match(style, /#dashboard-province-map svg[\s\S]{0,180}width: calc\(100% - 196px\)/);
assert.match(style, /#dashboard-province-map \.province-map-legend-label[\s\S]{0,100}font-size: 10\.5px/);
assert.doesNotMatch(html, /Phân bổ theo địa điểm trong toàn bộ kết quả phù hợp/);
assert.match(style, /\.dashboard-context-chip-label[\s\S]{0,160}text-overflow: ellipsis/);
assert.match(style, /color: #1d78e9;[\s\S]{0,50}background: #dcecff/);

console.log('Dashboard analytics contract passed');
