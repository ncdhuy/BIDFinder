const assert = require('node:assert/strict');
const fs = require('node:fs');

const script = fs.readFileSync('apps/web/script.js', 'utf8');
const index = fs.readFileSync('apps/web/index.html', 'utf8');

assert.match(script, /function ensureChartJsLoaded\(\)/);
assert.match(script, /if \(redrawCharts\) \{\s*insightChartsDirty = true;\s*if \(isInsightDrawerOpen\(\)\)/s);
assert.match(script, /if \(!isInsightDrawerOpen\(\)\) \{\s*insightChartsDirty = true;\s*return;/s);
assert.doesNotMatch(script, /function initEmptyCharts\(\)[\s\S]*?renderProvinceValueMap\(\[\]\)/);
assert.doesNotMatch(index, /chart\.umd\.min\.js/);

console.log('Chart lazy loading contract passed');
