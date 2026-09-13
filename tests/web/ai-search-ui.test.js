'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const formSource = fs.readFileSync(path.join(root, 'apps/web/typesense-search-form.js'), 'utf8');
const scriptSource = fs.readFileSync(path.join(root, 'apps/web/script.js'), 'utf8');

assert.match(formSource, /data-ai-message/);
assert.match(formSource, /data-ai-action="request"/);
assert.match(formSource, /Nhóm hiện tại:/);
assert.match(formSource, /data-ai-alt/);
assert.match(formSource, /data-ai-remove-concept/);
assert.match(formSource, /data-ai-remove-date/);
assert.match(formSource, /data-ai-field/);
assert.match(formSource, /ai_planning === true/);
assert.match(formSource, /field\.ai_planner_role === role/);

const requestMethod = formSource.slice(
    formSource.indexOf('        async requestAiPreview('),
    formSource.indexOf('        executeAiSearch()', formSource.indexOf('        async requestAiPreview('))
);
assert.match(requestMethod, /\{ group, message \}/);
assert.match(requestMethod, /\{ group, plan: JSON\.parse\(JSON\.stringify\(plan\)\) \}/);
assert.match(requestMethod, /\/api\/ai\/search-preview/);
assert.match(requestMethod, /AbortController/);
assert.match(requestMethod, /AI_PREVIEW_TIMEOUT_MS/);
assert.match(requestMethod, /mode: editedPlan \? 'edited_plan' : 'message'/);

const groupBinding = formSource.slice(
    formSource.indexOf("root.querySelectorAll('[data-group]')"),
    formSource.indexOf("root.querySelectorAll('[data-field]')")
);
assert.match(groupBinding, /this\.cancelAiPreview\(\)/);
assert.match(groupBinding, /this\.resetAiInterpretation\(\{ keepMessage: true \}\)/);

const interpretation = formSource.slice(
    formSource.indexOf('        renderAiInterpretation()'),
    formSource.indexOf('        markAiInterpretationDirty()')
);
assert.match(interpretation, /clause\.concepts/);
assert.match(interpretation, /conditions\.push\('<div class="ai-condition-join">VÀ<\/div>'\)/);
assert.match(interpretation, /alternatives\.join\(' \| '\)/);
assert.match(interpretation, /plan\.warnings/);
assert.match(formSource, /Không tìm thấy kết quả phù hợp/);

const execution = formSource.slice(
    formSource.indexOf('        executeAiSearch()'),
    formSource.indexOf('        bindAiEvents()', formSource.indexOf('        executeAiSearch()'))
);
assert.match(execution, /AI_COMPILED_REQUEST_MARKER/);
assert.match(execution, /detail: request/);
assert.match(execution, /new CustomEvent\('apply-filters'/);
assert.doesNotMatch(execution, /collectFilterPayload/);

assert.match(scriptSource, /const AI_COMPILED_REQUEST_MARKER/);
assert.match(scriptSource, /currentQueryRequest = payload\?\.\[AI_COMPILED_REQUEST_MARKER\]/);
assert.match(scriptSource, /\?\s*payload\s*:\s*enrichLegacyQueryRequest\(payload\);/);
assert.match(scriptSource, /filters: queryRequest\?\.filters \|\| \{\}/);

console.log('AI search UI contract passed');
