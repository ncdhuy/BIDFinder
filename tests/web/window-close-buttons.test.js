const assert = require('node:assert/strict');
const fs = require('node:fs');

const index = fs.readFileSync('apps/web/index.html', 'utf8');
const style = fs.readFileSync('apps/web/style.css', 'utf8');
const script = fs.readFileSync('apps/web/script.js', 'utf8');

const closeButtonIds = [
    'close-feedback-modal',
    'close-history',
    'close-bulk-search-modal',
    'close-filter-panel',
    'close-insight-drawer'
];

for (const id of closeButtonIds) {
    const idIndex = index.indexOf(`id="${id}"`);
    const buttonStart = index.lastIndexOf('<button', idIndex);
    const buttonEnd = index.indexOf('</button>', idIndex);
    assert.ok(idIndex >= 0 && buttonStart >= 0 && buttonEnd >= 0, `Missing close button: ${id}`);
    const buttonMarkup = index.slice(buttonStart, buttonEnd + '</button>'.length);
    assert.match(buttonMarkup, /class="[^"]*\bwindow-close-button\b[^"]*"/i);
    assert.match(buttonMarkup, /type="button"/i);
    assert.match(buttonMarkup, /aria-label="Đóng"/i);
    assert.match(buttonMarkup, /data-feather="x"/i);
}

const authCloseId = index.indexOf('id="auth-close-btn"');
const authCloseStart = index.lastIndexOf('<button', authCloseId);
const authCloseEnd = index.indexOf('</button>', authCloseId);
assert.match(index.slice(authCloseStart, authCloseEnd + '</button>'.length), /window-close-button/);
assert.match(style, /\.window-close-button\s*\{[\s\S]*?width:\s*36px;[\s\S]*?height:\s*36px;[\s\S]*?border-radius:\s*10px;/i);
assert.match(style, /\.window-close-button:hover\s*\{[\s\S]*?color:\s*#c43d3d;/i);
assert.match(style, /\.window-close-button:hover\s+svg\s*\{[\s\S]*?color:\s*inherit;/i);
assert.match(style, /\.window-close-button:focus-visible\s*\{/i);
assert.match(style, /\.insight-drawer\s*\{[\s\S]*?display:\s*none;/i);
assert.match(style, /\.insight-drawer\.show,\s*\n\.insight-drawer\.is-closing\s*\{[\s\S]*?display:\s*block;/i);
assert.match(script, /getElementById\('close-insight-drawer'\)\?\.addEventListener\('click', closeInsightDrawer\)/);

console.log('Window close button consistency contract passed');
