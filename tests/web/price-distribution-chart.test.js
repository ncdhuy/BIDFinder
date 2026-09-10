const assert = require('node:assert/strict');
const fs = require('node:fs');

const script = fs.readFileSync('apps/web/script.js', 'utf8');
const helperStart = script.indexOf('const MAX_EXACT_PRICE_VALUES = 10;');
const helperEnd = script.indexOf('const CHART_CONFIG =', helperStart);
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'price distribution helper section not found');

const helperSource = script.slice(helperStart, helperEnd);
const helpers = eval(`(() => {
    const getFirstRawColumnValue = (row, fields) => fields
        .map(field => row?.[field])
        .find(value => value !== undefined && value !== null && value !== '');
    ${helperSource};
    return { buildPriceDistribution, getChartRows };
})()`);
const { buildPriceDistribution, getChartRows } = helpers;

const chartRows = getChartRows([
    { winning_unit_price: 100000, total_value: 1000000, quantity: 10 },
    { winning_unit_price: 50000000001, total_value: 50000000001, quantity: 1 },
    { winning_unit_price: 100000, total_value: 60000000000, quantity: 2 }
]);
assert.equal(chartRows.length, 1, 'chart-only outlier filter should exclude rows above 50 billion');

const exact = buildPriceDistribution([10000, 50000, 100000, 100000]);
assert.equal(exact.mode, 'exact');
assert.deepEqual(exact.labels, [10000, 50000, 100000]);
assert.deepEqual(exact.values, [1, 1, 2]);
assert.deepEqual(exact.datasetData, [
    { x: 10000, y: 1 },
    { x: 50000, y: 1 },
    { x: 100000, y: 2 }
]);

const singleton = buildPriceDistribution([100000, 100000]);
assert.equal(singleton.mode, 'exact');
assert.deepEqual(singleton.labels, [100000]);

const binned = buildPriceDistribution(Array.from({ length: 11 }, (_, index) => (index + 1) * 10000));
assert.equal(binned.mode, 'binned');
assert.ok(binned.labels.length <= 10, 'binned chart should stay readable');
assert.equal(binned.values.reduce((sum, value) => sum + value, 0), 11);
assert.ok(binned.labels.every(label => label.includes('–')), 'binned labels should show price ranges');

const histogramConfig = script.slice(script.indexOf('histogram:', helperEnd), script.indexOf('timeline:', helperEnd));
assert.match(histogramConfig, /type: chartData\.mode === 'exact' && chartData\.labels\?\.length > 1 \? 'linear' : 'category'/);
assert.match(histogramConfig, /getType: \(chartData = \{\}\) => chartData\.mode === 'exact' && chartData\.labels\?\.length > 1 \? 'scatter' : 'bar'/);
assert.match(script, /data: chartType === 'scatter'[\s\S]*chartData\.datasetData \|\| chartData\.values/);
assert.match(script, /: chartData\.values,/);
assert.match(script, /function formatPriceAxis\(value\)/);
assert.match(script, /dataset\.parsing = \{ xAxisKey: 'x', yAxisKey: 'y' \}/);
assert.match(script, /chartType === 'scatter' \? \{\} : \{ labels: chartData\.labels \}/);
assert.match(script, /Unable to draw \$\{key\} insight chart/);

console.log('Price distribution chart contract passed');
