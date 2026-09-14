'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const formSource = fs.readFileSync(path.join(root, 'apps/web/typesense-search-form.js'), 'utf8');
const chatSource = fs.readFileSync(path.join(root, 'apps/web/ai-search-chat.js'), 'utf8');
const indexSource = fs.readFileSync(path.join(root, 'apps/web/index.html'), 'utf8');
const styleSource = fs.readFileSync(path.join(root, 'apps/web/style.css'), 'utf8');
const scriptSource = fs.readFileSync(path.join(root, 'apps/web/script.js'), 'utf8');
const netlifySource = fs.readFileSync(path.join(root, 'netlify.toml'), 'utf8');
const legacyEmbeddedAiPattern = /data-ai-message|renderAiSearch|bindAiEvents|state\.ai|ai-search-panel/;
const assistantMarkupStart = indexSource.indexOf('<div class="workspace-actions toolbar-actions">');
const assistantMarkupEnd = indexSource.indexOf('<script src="https://accounts.google.com/gsi/client"', assistantMarkupStart);
const assistantMarkup = indexSource.slice(assistantMarkupStart, assistantMarkupEnd);

assert.doesNotMatch(formSource, legacyEmbeddedAiPattern);
assert.doesNotMatch(indexSource, legacyEmbeddedAiPattern);
assert.doesNotMatch(scriptSource, legacyEmbeddedAiPattern);
assert.doesNotMatch(indexSource, /id="ai-search-launcher"/);
assert.doesNotMatch(chatSource, /ai-search-launcher/);
assert.doesNotMatch(styleSource, /ai-search-launcher/);
assert.match(indexSource, /id="ai-search-chat"/);
assert.match(indexSource, /src="ai-search-chat\.js"/);
assert.match(indexSource, /id="open-ai-search"[^>]+aria-label="Tìm kiếm AI"[^>]+title="Tìm kiếm AI"/);
assert.match(assistantMarkup, /id="open-filter-panel"[\s\S]*?<\/button>\s*<button[^>]+id="open-ai-search"[\s\S]*?<\/button>\s*<button[^>]+id="open-insight-drawer"/);
assert.match(assistantMarkup, /Trợ lý AI/);
assert.doesNotMatch(assistantMarkup, /data-ai-chat-menu|data-ai-chat-menu-content|data-ai-chat-clear|Xóa cuộc trò chuyện/);
assert.match(chatSource, /const openButton = document\.getElementById\('open-ai-search'\)/);
assert.match(chatSource, /openButton\.addEventListener\('click', \(\) => setOpen\(!state\.open\)\)/);
assert.match(chatSource, /openButton\.setAttribute\('aria-expanded', String\(state\.open\)\)/);
assert.match(chatSource, /data-ai-chat-close[\s\S]*?setOpen\(false\)/);
assert.match(chatSource, /event\.key === 'Escape' && state\.open/);
assert.match(assistantMarkup, /placeholder="Nhập yêu cầu tìm kiếm…"/);
assert.match(assistantMarkup, /rows="1"/);
assert.equal((assistantMarkup.match(/<textarea id="ai-chat-input"/g) || []).length, 1);
assert.match(assistantMarkup, /<label class="sr-only" for="ai-chat-input">/);
assert.doesNotMatch(assistantMarkup, /Đang tải hạn mức AI/);
assert.match(styleSource, /\.ai-search-chat \.sr-only\s*\{/);
assert.doesNotMatch(assistantMarkup, />Xóa</);
assert.doesNotMatch(assistantMarkup, />Đóng</);
assert.doesNotMatch(assistantMarkup, />Gửi</);
[
  'Tôi có thể giúp tìm kiếm nhanh hơn.',
  'Mô tả điều bạn cần tìm; mỗi tin nhắn là một yêu cầu độc lập.',
  'Mô tả yêu cầu tìm kiếm',
  'Enter để gửi · Shift+Enter để xuống dòng · Mỗi tin nhắn là một yêu cầu mới',
  'BIDFinder hiểu yêu cầu như sau',
  'Xem trước: tìm thấy',
  'Chỉnh sửa điều kiện'
].forEach(text => {
  assert.doesNotMatch(assistantMarkup, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.doesNotMatch(chatSource, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
});
assert.match(indexSource, /src="typesense-search-form\.js"/);
assert.match(indexSource, /src="script\.js"/);
assert.match(indexSource, /href="style\.css(?:\?[^\"]*)?"/);
assert.match(netlifySource, /for = "\/\*"/);
assert.match(netlifySource, /Cache-Control = "public, max-age=0, must-revalidate"/);
assert.equal((indexSource.match(/data-ai-chat-group=/g) || []).length, 3);
assert.match(indexSource, /Hàng hóa/);
assert.match(indexSource, /Thuốc/);
assert.match(indexSource, /Dược liệu/);
assert.match(styleSource, /\.ai-chat-groups \{[^}]*gap: 7px/);
assert.match(styleSource, /\.ai-chat-groups button \{[^}]*border: 1px solid/);
assert.doesNotMatch(styleSource, /\.ai-chat-groups \{[^}]*border:/);
assert.doesNotMatch(styleSource, /\.ai-chat-input-row \{[^}]*border:/);
assert.match(styleSource, /\.ai-chat-input-row textarea \{[^}]*border: 1px solid[^}]*border-radius: 8px/);
assert.match(assistantMarkup, /<button[^>]+data-ai-chat-group="goods"/);
assert.match(assistantMarkup, /<button[^>]+data-ai-chat-group="medicines"/);
assert.match(assistantMarkup, /<button[^>]+data-ai-chat-group="traditional"/);

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
assert.match(chatSource, /usageStatus: 'loading'/);
assert.match(chatSource, /state\.usageStatus = 'unavailable'/);
assert.match(chatSource, /usageRoot\.replaceChildren\(\)/);
assert.match(chatSource, /setTimeout\([\s\S]*?1200/);
assert.match(chatSource, /if \(response\.ok && payload\?\.success && updateUsage\(payload\)\)/);
assert.match(chatSource, /if \(state\.usageStatus !== 'loading'\) return;/);
assert.match(chatSource, /state\.usageStatus = 'available'/);
assert.match(chatSource, /usageRoot\.textContent = `\$\{remaining\}% còn lại`/);
assert.match(chatSource, /event\.key === 'Enter' && !event\.shiftKey/);
assert.match(chatSource, /composer\.requestSubmit\(\)/);
assert.match(chatSource, /Không có kết quả/);
assert.match(chatSource, /Xem kết quả/);
assert.match(chatSource, /aria-label="Chỉnh sửa"/);
assert.match(chatSource, /resizeInput/);
assert.doesNotMatch(chatSource, /clearHistory|data-ai-chat-clear|data-ai-chat-menu/);
assert.match(chatSource, /data-ai-chat-action="edit"/);
assert.match(chatSource, /data-ai-chat-action="execute"/);
assert.match(chatSource, /new CustomEvent\('apply-filters'/);
assert.match(scriptSource, /const PANEL_CONFIG/);
assert.match(scriptSource, /open-filter-panel/);
assert.match(chatSource, /Hàng hóa/);
assert.match(chatSource, /Thuốc/);
assert.match(chatSource, /Dược liệu/);

assert.match(scriptSource, /const AI_COMPILED_REQUEST_MARKER/);
assert.match(scriptSource, /currentQueryRequest = payload\?\.\[AI_COMPILED_REQUEST_MARKER\]/);
assert.match(scriptSource, /\?\s*payload\s*:\s*enrichLegacyQueryRequest\(payload\);/);
assert.doesNotMatch(scriptSource, /console\.log\('Applying filters with query request:/);
assert.match(scriptSource, /filters: queryRequest\?\.filters \|\| \{\}/);

console.log('AI search UI contract passed');
