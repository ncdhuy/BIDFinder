const assert = require('node:assert/strict');
const fs = require('node:fs');

const script = fs.readFileSync('apps/web/script.js', 'utf8');
const helperStart = script.indexOf('function getInsightChartData(');
const helperEnd = script.indexOf('function getWorkingSetPage');
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'chart data helper section not found');

const helperSource = script.slice(helperStart, helperEnd);
const getInsightChartData = eval(`(${helperSource.match(/function getInsightChartData\(tableId, displayedData\) \{[\s\S]*?\n\}/)[0]})`);
const getInsightChartDataSets = eval(`(${helperSource.match(/function getInsightChartDataSets\(\) \{[\s\S]*?\n\}/)[0]})`);

const workingSetAvailable = {
    'standard-table': true,
    'extended-table': true,
    'traditional-table': true
};
const currentFilteredDf1 = [{ id: 'medicine-page-row' }];
const currentFilteredDf2 = [{ id: 'goods-page-row' }];
const currentFilteredDf3 = [{ id: 'traditional-page-row' }];
const workingSets = {
    'standard-table': [{ id: 'medicine-1' }, { id: 'medicine-2' }],
    'extended-table': [{ id: 'goods-1' }, { id: 'goods-2' }, { id: 'goods-3' }],
    'traditional-table': [{ id: 'traditional-1' }]
};
const getFilteredWorkingSet = tableId => workingSets[tableId];

const chartData = getInsightChartDataSets();
assert.deepEqual(chartData.df1, workingSets['standard-table']);
assert.deepEqual(chartData.df2, workingSets['extended-table']);
assert.deepEqual(chartData.df3, workingSets['traditional-table']);

workingSetAvailable['extended-table'] = false;
assert.deepEqual(
    getInsightChartData('extended-table', currentFilteredDf2),
    currentFilteredDf2,
    'legacy responses should keep their available data as a fallback'
);

console.log('Chart data scope passed: working set, not visible page');
