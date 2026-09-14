'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const formSource = fs.readFileSync(path.join(root, 'apps/web/typesense-search-form.js'), 'utf8');
const chatSource = fs.readFileSync(path.join(root, 'apps/web/ai-search-chat.js'), 'utf8');
const indexSource = fs.readFileSync(path.join(root, 'apps/web/index.html'), 'utf8');
const scriptSource = fs.readFileSync(path.join(root, 'apps/web/script.js'), 'utf8');
const netlifySource = fs.readFileSync(path.join(root, 'netlify.toml'), 'utf8');
const legacyEmbeddedAiPattern = /data-ai-message|renderAiSearch|bindAiEvents|state\.ai|ai-search-panel/;

assert.doesNotMatch(formSource, legacyEmbeddedAiPattern);
assert.doesNotMatch(indexSource, legacyEmbeddedAiPattern);
assert.doesNotMatch(scriptSource, legacyEmbeddedAiPattern);
assert.match(indexSource, /id="ai-search-launcher"/);
assert.match(indexSource, /id="ai-search-chat"/);
assert.match(indexSource, /src="ai-search-chat\.js"/);
assert.match(indexSource, /src="typesense-search-form\.js"/);
assert.match(indexSource, /src="script\.js"/);
assert.match(indexSource, /href="style\.css(?:\?[^\"]*)?"/);
assert.match(netlifySource, /for = "\/\*"/);
assert.match(netlifySource, /Cache-Control = "public, max-age=0, must-revalidate"/);
assert.equal((indexSource.match(/data-ai-chat-group=/g) || []).length, 3);
assert.match(indexSource, /Hàng hóa/);
assert.match(indexSource, /Thuốc/);
assert.match(indexSource, /Dược liệu/);

assert.match(chatSource, /\/api\/ai\/search-preview/);
assert.match(chatSource, /body: JSON\.stringify\(\{ group: item\.group, message: item\.message \}\)/);
assert.match(chatSource, /body: JSON\.stringify\(\{ group: item\.group, plan \}\)/);
assert.doesNotMatch(chatSource, /history.*body|body: JSON\.stringify\(state\.history/);
assert.match(chatSource, /data-ai-chat-action="edit"/);
assert.match(chatSource, /data-ai-chat-action="execute"/);
assert.match(chatSource, /COMPILED_REQUEST_MARKER/);
assert.match(chatSource, /new CustomEvent\('apply-filters'/);
assert.match(chatSource, /\/api\/ai\/usage/);
assert.match(chatSource, /remaining_percent/);
assert.match(chatSource, /localStorage/);
assert.match(chatSource, /event\.key === 'Enter' && !event\.shiftKey/);
assert.match(chatSource, /composer\.requestSubmit\(\)/);
assert.match(chatSource, /Hàng hóa/);
assert.match(chatSource, /Thuốc/);
assert.match(chatSource, /Dược liệu/);

assert.match(scriptSource, /const AI_COMPILED_REQUEST_MARKER/);
assert.match(scriptSource, /currentQueryRequest = payload\?\.\[AI_COMPILED_REQUEST_MARKER\]/);
assert.match(scriptSource, /\?\s*payload\s*:\s*enrichLegacyQueryRequest\(payload\);/);
assert.doesNotMatch(scriptSource, /console\.log\('Applying filters with query request:/);
assert.match(scriptSource, /filters: queryRequest\?\.filters \|\| \{\}/);

console.log('AI search UI contract passed');
