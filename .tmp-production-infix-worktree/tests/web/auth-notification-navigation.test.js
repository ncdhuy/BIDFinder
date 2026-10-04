'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..', '..');
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

const indexHtml = read('apps/web/index.html');
const authCss = read('apps/web/auth.css');
const authJs = read('apps/web/auth.js');
const scriptJs = read('apps/web/script.js');

const landingNavStart = indexHtml.indexOf('<nav class="bf-nav">');
const landingNavEnd = indexHtml.indexOf('</nav>', landingNavStart);
assert(landingNavStart >= 0 && landingNavEnd > landingNavStart, 'Landing navigation should exist');
const landingNav = indexHtml.slice(landingNavStart, landingNavEnd);
assert.deepStrictEqual(
  [...landingNav.matchAll(/id="([^"]+)"/g)].map((match) => match[1]),
  ['open-account-nav', 'open-register-nav', 'open-login-nav'],
  'Landing navigation should keep account/register/login text actions'
);
assert(!landingNav.includes('open-feedback-nav'), 'Landing navigation should not expose the old forum action');

const helpIndex = indexHtml.indexOf('id="open-product-journey"');
const notificationIndex = indexHtml.indexOf('id="open-feedback-modal"');
const accountIndex = indexHtml.indexOf('id="auth-edit-profile-btn"');
assert(helpIndex >= 0 && notificationIndex > helpIndex && accountIndex > notificationIndex,
  'App header should order guide, notification, then account');
assert(!indexHtml.includes('id="open-register-app"'), 'App header should not contain the legacy register action');
assert(!indexHtml.includes('id="open-login-app"'), 'App header should not contain the legacy login action');
assert(indexHtml.includes('aria-label="Thông báo"'), 'Notification action should have an accessible label');

assert(authCss.includes('body.auth-state-guest #open-register-nav'), 'Guest landing state should show register');
assert(authCss.includes('body.auth-state-guest #open-login-nav'), 'Guest landing state should show login');
assert(!authCss.includes('body.auth-state-guest #open-product-journey'), 'Guest app should keep the guide action visible');
assert(!authCss.includes('body.auth-state-guest #open-feedback-modal'), 'Guest app should keep notifications visible');

assert(authJs.includes('const openAccount = () =>'), 'Account action should handle guest and authenticated states');
assert(authJs.includes("els['auth-edit-profile-btn']?.addEventListener('click', openAccount)"),
  'App account action should open the auth/profile modal');
assert(!authJs.includes("classList.toggle('is-hidden'"), 'Guest account action should not be hidden by the old shell toggle');

const section = (name, nextName) => {
  const start = scriptJs.indexOf(name);
  const end = nextName ? scriptJs.indexOf(nextName, start + name.length) : scriptJs.length;
  assert(start >= 0, `Missing ${name}`);
  return scriptJs.slice(start, end >= 0 ? end : scriptJs.length);
};
assert(section('function showFeedbackTopicForm', 'function renderFeedbackTopicDetail').includes('requireFeedbackAuthentication'),
  'Creating a topic should require authentication');
assert(section('async function createFeedbackTopic', 'async function sendFeedbackReply').includes('requireFeedbackAuthentication'),
  'Topic submit should require authentication');
assert(section('async function sendFeedbackReply', 'function initFeedbackModalEvents').includes('requireFeedbackAuthentication'),
  'Reply submit should require authentication');
const feedbackEvents = section('function initFeedbackModalEvents', 'function getActiveResultViewContext');
assert(!feedbackEvents.includes("feedback-reply-body')?.addEventListener('focus'"),
  'Opening the anonymous reply composer should not immediately require authentication');
assert(section('function updateFeedbackReplyButtonState', 'function renderFeedbackReplies').includes('sendButton.disabled = isClosedForUser || !replyBody.value.trim()'),
  'Anonymous users should be able to submit a reply attempt and receive the login prompt at send time');
assert(scriptJs.includes('Hướng dẫn, thông báo và tài khoản'), 'Product guide should use the notification wording');
assert(!/diễn đàn|forum/i.test(indexHtml + authCss + authJs + scriptJs),
  'Visible web UI should not retain the old forum wording');

console.log('Auth, notification and navigation contract passed');
