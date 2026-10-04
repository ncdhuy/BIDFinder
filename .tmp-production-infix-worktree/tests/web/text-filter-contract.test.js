'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..');
const script = fs.readFileSync(path.join(root, 'apps/web/script.js'), 'utf8');
const style = fs.readFileSync(path.join(root, 'apps/web/style.css'), 'utf8');

for (const operator of ['equals', 'notEquals', 'beginsWith', 'endsWith', 'contains', 'notContains']) {
  assert(script.includes(`${operator}:`), `Missing text filter operator: ${operator}`);
}

for (const token of [
  'Bộ lọc văn bản',
  'Bằng...',
  'Không bằng...',
  'Bắt đầu bằng...',
  'Kết thúc bằng...',
  'Chứa...',
  'Không chứa...',
  'Bộ lọc tùy chỉnh...',
  'Dùng ? cho một ký tự, * cho nhiều ký tự.'
]) {
  assert(script.includes(token), `Missing text filter UI token: ${token}`);
}

assert(script.includes('columnTextFilterState'), 'Text filters need per-table state');
assert(script.includes('matchesColumnTextFilterCondition'), 'Text filters need row matching');
assert(script.includes('columnTextFilterState[tableId]'), 'Text filter submit should update state');
assert(script.includes('replaceColumnFilterState'),
  'Text filter submit should replace the existing rule for the same canonical column');
assert(script.includes('getColumnTextFilterEntries'),
  'Text filtering should collapse equivalent column keys before matching');
assert(script.includes('getColumnValueFilterEntries'),
  'Value filtering should collapse equivalent column keys before matching');
assert(script.includes("firstValue.value = currentRule?.value || '';"),
  'Reopening a text filter should restore the active keyword');
assert(script.includes('stableStringify(currentRule) === stableStringify(normalizedRule)'),
  'Reapplying an unchanged custom filter should be idempotent');
assert(script.includes("!String(normalizedRule.secondValue || '').trim()"),
  'A custom filter with an empty second condition should match its first condition only');
assert(script.includes('let baseWorkingDf1 = null;'),
  'Column filters need an immutable working-set source');
assert(script.includes('const excludedKey = excludedColumnName === null'),
  'Facet lookup should exclude the active text-filter column by canonical key');
assert(script.includes("if (event.key !== 'Enter' || event.isComposing) return;"),
  'Enter should apply the text filter editor');
assert(script.includes("case 'toggle-text-filter'"), 'Column menu should open the text filter submenu');
assert(script.includes('clearColumnTextFilter'), 'Text filter should be removable');
assert(script.includes('columnFilters: collectColumnFiltersForUrl()'), 'Text filters should refresh URL state');
assert(style.includes('.column-text-filter-panel'), 'Text filter submenu needs dedicated styling');
assert(style.includes('.column-text-filter-option'), 'Text filter options need dedicated styling');

const matcherStart = script.indexOf('function normalizeColumnFilterValue');
const matcherEnd = script.indexOf('function getColumnRawValues');
const matcherContext = {
  TEXT_FILTER_OPERATORS: new Set(['equals', 'notEquals', 'beginsWith', 'endsWith', 'contains', 'notContains'])
};
vm.runInNewContext(
  `${script.slice(matcherStart, matcherEnd)}; this.matchesColumnTextFilter = matchesColumnTextFilter;`,
  matcherContext
);
assert.strictEqual(
  matcherContext.matchesColumnTextFilter(
    ['Tầm vông'],
    { custom: true, operator: 'equals', value: 'Tầm vông', logic: 'and', secondOperator: 'equals', secondValue: '' }
  ),
  true,
  'Custom filter with one populated condition should match the same rows as equal'
);

for (const operator of ['equals', 'notEquals', 'beginsWith', 'endsWith', 'contains', 'notContains']) {
  const quickRule = { operator, value: 'tầm vông' };
  const customRule = {
    custom: true,
    ...quickRule,
    logic: 'and',
    secondOperator: 'equals',
    secondValue: ''
  };
  for (const values of [['Tầm vông'], ['Tầm vông xanh'], ['Cây khác'], ['']]) {
    assert.strictEqual(
      matcherContext.matchesColumnTextFilter(values, customRule),
      matcherContext.matchesColumnTextFilter(values, quickRule),
      `Custom filter with one condition must preserve ${operator} behavior`
    );
  }
}

console.log('Text filter contract passed');
