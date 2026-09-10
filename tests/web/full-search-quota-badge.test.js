const assert = require('node:assert/strict');
const fs = require('node:fs');

const script = fs.readFileSync('apps/web/script.js', 'utf8');
const formatterMatch = script.match(/function getResultTableCountLabel\(tableId, fallbackCount = 0\) \{[\s\S]*?\n\}/);
assert.ok(formatterMatch, 'result count formatter not found');

const workingSetAvailable = {
    'standard-table': true,
    'extended-table': true,
    'traditional-table': true
};
const currentQueryMeta = {
    df1WorkingCount: 1000,
    df1Total: 32190,
    df2WorkingCount: 2345,
    df2Total: 2345,
    df3WorkingCount: 5000,
    df3Total: 5000,
    df1WorkingSetTruncated: false,
    df2WorkingSetTruncated: false,
    df3WorkingSetTruncated: true,
    appliedLimitPerScope: 1000,
    searchMode: 'standard',
    bulkSearchMode: 'standard'
};
const getResultTableCountLabel = eval(`(${formatterMatch[0]})`);

assert.equal(getResultTableCountLabel('standard-table'), '1000');
currentQueryMeta.df1WorkingSetTruncated = true;
assert.equal(getResultTableCountLabel('standard-table'), '1000+');
currentQueryMeta.df1WorkingSetTruncated = false;
currentQueryMeta.searchMode = 'full';
currentQueryMeta.appliedLimitPerScope = 5000;
assert.equal(getResultTableCountLabel('extended-table'), '2345');
assert.equal(getResultTableCountLabel('traditional-table'), '5000+');
currentQueryMeta.searchMode = 'standard';
currentQueryMeta.appliedLimitPerScope = 1000;
workingSetAvailable['standard-table'] = false;
assert.equal(getResultTableCountLabel('standard-table'), '1000+');

assert.doesNotMatch(script, /rawValue > 1000 \|\| value > 1000/);
assert.doesNotMatch(script, /return '1000\+'/);

assert.match(script, /let fullSearchInFlight = false;/);
assert.match(script, /function reserveFullSearchQuota\(quota\)/);
assert.match(script, /reserveFullSearchQuota\(quotaSnapshot\);[\s\S]*?await fetchQueryResults/);
assert.match(script, /function rollbackFullSearchQuota\(quota\)/);
assert.match(script, /if \(serverAccepted\) \{[\s\S]*?releaseFullSearchQuotaReservation\(\);[\s\S]*?\} else \{[\s\S]*?rollbackFullSearchQuota\(quotaSnapshot\);/);
assert.match(script, /&& !fullSearchInFlight/);

console.log('Full search quota and badge contract passed');
