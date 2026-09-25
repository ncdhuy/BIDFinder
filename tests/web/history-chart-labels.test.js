const assert = require('node:assert/strict');
const fs = require('node:fs');

const script = fs.readFileSync('apps/web/script.js', 'utf8');
const indexHelper = script.match(/function getHistoryValueLabelIndexes\(pointCount, chartWidth\) \{[\s\S]*?\n\}/);
assert.ok(indexHelper, 'history chart label index helper not found');
const getHistoryValueLabelIndexes = eval(`(${indexHelper[0]})`);

const currencyHelper = script.match(/function formatHistorySummaryCurrency\(value\) \{[\s\S]*?\n\}/);
assert.ok(currencyHelper, 'history summary currency formatter not found');
const formatHistorySummaryCurrency = eval(`(${currencyHelper[0]})`);
assert.equal(formatHistorySummaryCurrency(80988835100), '80,99 tỷ');
assert.equal(formatHistorySummaryCurrency(337880000), '337,88 triệu');

assert.deepEqual(getHistoryValueLabelIndexes(30, 800), [0, 7, 15, 22, 29]);
assert.deepEqual(getHistoryValueLabelIndexes(180, 300), [0, 90, 179]);
assert.equal(getHistoryValueLabelIndexes(180, 2000).length, 6, 'wide charts should keep a readable label count');
assert.deepEqual(getHistoryValueLabelIndexes(2, 800), [0, 1]);
assert.deepEqual(getHistoryValueLabelIndexes(0, 800), []);
assert.match(script, /id: 'history-value-labels',[\s\S]*?afterDatasetsDraw\(chart\)/);
assert.match(script, /for \(let offset = 1; offset <= 3; offset \+= 1\)/);
assert.match(script, /borderDash: context =>/);
assert.ok(
    script.includes("const label = `${String(labels[index] || '').replace('-', '/')}: ${value.toLocaleString('vi-VN')} gói thầu`;"),
    'selected day labels should use dd/mm: count gói thầu format'
);

const tooltipStart = script.indexOf('let actionTooltipElement = null;');
const tooltipEnd = script.indexOf('async function initializeAppData()', tooltipStart);
assert.ok(tooltipStart >= 0 && tooltipEnd > tooltipStart, 'action tooltip block not found');

const listeners = {};
const buttonAttributes = { 'aria-label': 'Lịch sử cập nhật', title: 'Lịch sử cập nhật' };
buttonAttributes.id = 'open-run-history';
let historyModalOpen = false;
const button = {
    id: 'open-run-history',
    dataset: {},
    addEventListener: (name, handler) => { listeners[name] = handler; },
    getAttribute: name => buttonAttributes[name] || null,
    setAttribute: (name, value) => { buttonAttributes[name] = value; },
    removeAttribute: name => { delete buttonAttributes[name]; },
    getBoundingClientRect: () => ({ left: 10, right: 42, top: 10, bottom: 42, width: 32, height: 32 })
};
const tooltipAttributes = {};
const tooltipClasses = new Set();
let tooltip;
const windowListeners = {};
const document = {
    querySelectorAll: () => [button],
    getElementById: id => id === 'history-modal'
        ? { classList: { contains: className => historyModalOpen && className === 'show' } }
        : null,
    createElement: () => {
        tooltip = {
            style: {},
            setAttribute: (name, value) => { tooltipAttributes[name] = value; },
            getBoundingClientRect: () => ({ width: 100, height: 24 }),
            classList: {
                add: name => tooltipClasses.add(name),
                remove: name => tooltipClasses.delete(name),
                contains: name => tooltipClasses.has(name)
            }
        };
        return tooltip;
    },
    body: { appendChild: () => {} }
};
const window = {
    innerWidth: 1024,
    innerHeight: 768,
    addEventListener: (name, handler) => { windowListeners[name] = handler; }
};
const tooltipApi = new Function('document', 'window', `${script.slice(tooltipStart, tooltipEnd)}; return { initActionTooltips };`)(document, window);

tooltipApi.initActionTooltips();
listeners.mouseenter();
assert.equal(tooltipAttributes['aria-hidden'], 'false', 'tooltip should show on hover');
assert.equal(tooltipClasses.has('is-visible'), true);
listeners.click();
assert.equal(tooltipAttributes['aria-hidden'], 'true', 'tooltip should hide when its action button is clicked');
assert.equal(tooltipClasses.has('is-visible'), false);
assert.equal(buttonAttributes['aria-describedby'], undefined);

listeners.mouseenter();
assert.equal(tooltipClasses.has('is-visible'), true);
windowListeners.blur();
assert.equal(tooltipClasses.has('is-visible'), false, 'tooltip should hide when the browser window loses focus');

historyModalOpen = true;
listeners.focusin();
assert.equal(tooltipClasses.has('is-visible'), false, 'history tooltip should stay hidden while its modal is open');

console.log('History chart labels and action tooltip lifecycle passed');
