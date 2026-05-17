import http from "k6/http";
import { check, fail, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

const BASE_URL = (__ENV.BASE_URL || "https://bidfinder-api-staging-774667987564.asia-southeast1.run.app").replace(/\/+$/, "");
const VUS = Number(__ENV.VUS || 100);
const DURATION = __ENV.DURATION || "10m";
const RAMP_UP = __ENV.RAMP_UP || "2m";
const RAMP_DOWN = __ENV.RAMP_DOWN || "1m";
const SEARCH_MODE = __ENV.SEARCH_MODE || "standard";
const QUERY_LIMIT = Number(__ENV.QUERY_LIMIT || 200);
const TEST_MODE = __ENV.TEST_MODE || "journey";
const BULK_ROWS = Number(__ENV.BULK_ROWS || 10);
const BULK_LIMIT = Number(__ENV.BULK_LIMIT || 1000);
const BULK_DIVERSITY_MODE = __ENV.BULK_DIVERSITY_MODE || "price";
const BULK_PRICE_LIMIT = Number(__ENV.BULK_PRICE_LIMIT || 3);
const BULK_PRODUCT_LIMIT = Number(__ENV.BULK_PRODUCT_LIMIT || 3);
const REALISTIC_BULK_RATE = Number(__ENV.REALISTIC_BULK_RATE || 0.02);
const REALISTIC_AUTOCOMPLETE_PREVIEW_RATE = Number(__ENV.REALISTIC_AUTOCOMPLETE_PREVIEW_RATE || 0.2);
const REALISTIC_QUERY_RATE = Number(__ENV.REALISTIC_QUERY_RATE || 0.7);
const REALISTIC_MIN_THINK_SECONDS = Number(__ENV.REALISTIC_MIN_THINK_SECONDS || 10);
const REALISTIC_MAX_THINK_SECONDS = Number(__ENV.REALISTIC_MAX_THINK_SECONDS || 30);
const REALISTIC_BULK_MIN_THINK_SECONDS = Number(__ENV.REALISTIC_BULK_MIN_THINK_SECONDS || 20);
const REALISTIC_BULK_MAX_THINK_SECONDS = Number(__ENV.REALISTIC_BULK_MAX_THINK_SECONDS || 60);
const SKIP_AUTOCOMPLETE = (__ENV.SKIP_AUTOCOMPLETE || "").toLowerCase() === "true";
const SKIP_PREVIEW = (__ENV.SKIP_PREVIEW || "").toLowerCase() === "true";
const SKIP_QUERY = (__ENV.SKIP_QUERY || "").toLowerCase() === "true";
const SKIP_BULK = (__ENV.SKIP_BULK || "").toLowerCase() === "true";

const LOGIN_EMAIL = __ENV.LOGIN_EMAIL || "";
const LOGIN_PASSWORD = __ENV.LOGIN_PASSWORD || "";
const SESSION_COOKIE_NAME = __ENV.SESSION_COOKIE_NAME || "bidfinder_session";
const LOGIN_MODE = __ENV.LOGIN_MODE || "per-vu";
const PRELOGIN_VUS = (__ENV.PRELOGIN_VUS || "").toLowerCase() === "true";
const LOGIN_TIMEOUT = __ENV.LOGIN_TIMEOUT || "120s";
const LOGIN_STAGGER_SECONDS = Number(__ENV.LOGIN_STAGGER_SECONDS || 0);
const SETUP_TIMEOUT = __ENV.SETUP_TIMEOUT || "5m";

let vuSession = null;

const errors = new Rate("bidfinder_errors");
const rateLimited = new Counter("bidfinder_429s");
const authFailures = new Counter("bidfinder_auth_failures");
const serverFailures = new Counter("bidfinder_5xxs");
const clientFailures = new Counter("bidfinder_4xxs");
const queryLatency = new Trend("bidfinder_query_ms");
const bulkLatency = new Trend("bidfinder_bulk_ms");
const previewLatency = new Trend("bidfinder_preview_ms");
const autocompleteLatency = new Trend("bidfinder_autocomplete_ms");

export const options = {
  setupTimeout: SETUP_TIMEOUT,
  scenarios: {
    active_search_users: {
      executor: "ramping-vus",
      stages: [
        { duration: RAMP_UP, target: VUS },
        { duration: DURATION, target: VUS },
        { duration: RAMP_DOWN, target: 0 },
      ],
      gracefulRampDown: "30s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.05"],
    bidfinder_errors: ["rate<0.05"],
    bidfinder_429s: ["count<50"],
    bidfinder_5xxs: ["count<20"],
    bidfinder_query_ms: ["p(95)<5000"],
    bidfinder_bulk_ms: ["p(95)<15000"],
    bidfinder_preview_ms: ["p(95)<2500"],
    bidfinder_autocomplete_ms: ["p(95)<1500"],
  },
};

const SEARCH_CASES = [
  {
    scope: "medicine",
    filters: {
      drugName: { tokens: [{ value: "paracetamol", op: "OR" }] },
    },
  },
  {
    scope: "medicine",
    filters: {
      activeIngredient: { tokens: [{ value: "amoxicillin", op: "OR" }] },
    },
  },
  {
    scope: "medicine",
    filters: {
      winner: { tokens: [{ value: "CÔNG TY CỔ PHẦN DƯỢC HẬU GIANG", op: "OR" }] },
    },
  },
  {
    scope: "goods",
    filters: {
      drugName: { tokens: [{ value: "bơm tiêm", op: "OR" }] },
    },
  },
  {
    scope: "goods",
    filters: {
      drugName: { tokens: [{ value: "máy xét nghiệm", op: "OR" }] },
    },
  },
  {
    scope: "all",
    filters: {
      winner: { tokens: [{ value: "CÔNG TY CỔ PHẦN DƯỢC HẬU GIANG", op: "OR" }] },
    },
  },
];

const AUTOCOMPLETE_CASES = [
  { scope: "all", field: "drugName", keyword: "para" },
  { scope: "all", field: "activeIngredient", keyword: "amo" },
  { scope: "all", field: "winner", keyword: "công" },
  { scope: "all", field: "manufacturer", keyword: "dược" },
  { scope: "goods", field: "drugName", keyword: "máy" },
  { scope: "goods", field: "country", keyword: "việt" },
];

const BULK_CASES = [
  {
    scope: "medicine",
    fields: ["drugName"],
    values: [
      { drugName: "paracetamol" },
      { drugName: "amoxicillin" },
      { drugName: "ceftriaxone" },
      { drugName: "insulin" },
      { drugName: "omeprazole" },
      { drugName: "metformin" },
      { drugName: "atorvastatin" },
      { drugName: "salbutamol" },
      { drugName: "azithromycin" },
      { drugName: "lidocain" },
    ],
  },
  {
    scope: "medicine",
    fields: ["activeIngredient"],
    values: [
      { activeIngredient: "paracetamol" },
      { activeIngredient: "amoxicillin" },
      { activeIngredient: "ceftriaxone" },
      { activeIngredient: "insulin" },
      { activeIngredient: "omeprazole" },
      { activeIngredient: "metformin" },
      { activeIngredient: "atorvastatin" },
      { activeIngredient: "salbutamol" },
      { activeIngredient: "azithromycin" },
      { activeIngredient: "lidocain" },
    ],
  },
  {
    scope: "medicine",
    fields: ["drugName", "country"],
    values: [
      { drugName: "paracetamol", country: "Việt Nam" },
      { drugName: "amoxicillin", country: "Ấn Độ" },
      { drugName: "ceftriaxone", country: "Việt Nam" },
      { drugName: "insulin", country: "Đức" },
      { drugName: "omeprazole", country: "Ấn Độ" },
    ],
  },
  {
    scope: "goods",
    fields: ["goodsName"],
    values: [
      { goodsName: "bơm tiêm" },
      { goodsName: "máy xét nghiệm" },
      { goodsName: "khẩu trang" },
      { goodsName: "găng tay" },
      { goodsName: "kim luồn" },
      { goodsName: "ống nghiệm" },
      { goodsName: "máy siêu âm" },
      { goodsName: "máy thở" },
      { goodsName: "hóa chất" },
      { goodsName: "vật tư" },
    ],
  },
  {
    scope: "goods",
    fields: ["technicalSpec"],
    values: [
      { technicalSpec: "xét nghiệm" },
      { technicalSpec: "siêu âm" },
      { technicalSpec: "tiệt trùng" },
      { technicalSpec: "monitor" },
      { technicalSpec: "hóa chất" },
    ],
  },
];

function extractSession(res) {
  if (!res || !res.body) {
    return { cookie: "", token: "" };
  }
  let cookieValue = res.cookies[SESSION_COOKIE_NAME]?.[0]?.value || "";
  if (!cookieValue) {
    const setCookie = String(res.headers["Set-Cookie"] || "");
    const match = setCookie.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`));
    cookieValue = match?.[1] || "";
  }
  let token = "";
  try {
    token = res.json("token") || "";
  } catch (error) {
    token = "";
  }

  return {
    cookie: cookieValue ? `${SESSION_COOKIE_NAME}=${cookieValue}` : "",
    token,
  };
}

function loginSession(userAgent = "BIDFinder-loadtest/login") {
  if (LOGIN_STAGGER_SECONDS > 0) {
    sleep(Math.random() * LOGIN_STAGGER_SECONDS);
  }

  const res = http.post(
    `${BASE_URL}/api/auth/login`,
    JSON.stringify({ email: LOGIN_EMAIL, password: LOGIN_PASSWORD }),
    {
      headers: { "Content-Type": "application/json", "User-Agent": userAgent },
      timeout: LOGIN_TIMEOUT,
    },
  );

  check(res, {
    "login ok": (r) => r.status === 200 && Boolean(r.json("success")),
    "login session cookie returned": (r) => Boolean(r.cookies[SESSION_COOKIE_NAME]?.[0]?.value),
  });

  const session = extractSession(res);
  if (res.status !== 200 || !session.cookie) {
    console.error(`login failed: status=${res.status} body=${String(res.body || "").slice(0, 500)}`);
    console.error(`set-cookie=${String(res.headers["Set-Cookie"] || "").slice(0, 300)}`);
    fail("LOGIN_EMAIL/LOGIN_PASSWORD did not produce a session cookie; aborting authenticated load test.");
  }
  return session;
}

function getSession() {
  if (!LOGIN_EMAIL || !LOGIN_PASSWORD) {
    return {};
  }
  if (LOGIN_MODE === "shared") {
    return {};
  }
  if (!vuSession) {
    vuSession = loginSession(`BIDFinder-loadtest/vu-${__VU}`);
  }
  return vuSession;
}

function params(session = {}) {
  const headers = {
    "Content-Type": "application/json",
    "User-Agent": `BIDFinder-loadtest/vu-${__VU}`,
  };
  if (session.token) {
    headers.Authorization = `Bearer ${session.token}`;
  }
  if (session.cookie) {
    headers.Cookie = session.cookie;
  }
  return { headers, timeout: "65s" };
}

function postJson(path, payload, session, trend) {
  const started = Date.now();
  const res = http.post(`${BASE_URL}${path}`, JSON.stringify(payload), params(session));
  trend.add(Date.now() - started);

  const ok = check(res, {
    [`${path} status is 2xx`]: (r) => r.status >= 200 && r.status < 300,
    [`${path} returns JSON`]: (r) => (r.headers["Content-Type"] || "").includes("application/json"),
  });

  if (res.status === 429) {
    rateLimited.add(1);
  }
  if (res.status === 401 || res.status === 403) {
    authFailures.add(1);
  }
  if (res.status >= 400 && res.status < 500) {
    clientFailures.add(1);
  }
  if (res.status >= 500) {
    serverFailures.add(1);
  }
  if (!ok && __ITER < 3) {
    console.error(`${path} failed: status=${res.status} body=${String(res.body || "").slice(0, 300)}`);
  }
  errors.add(!ok);
  return res;
}

function pick(items) {
  return items[Math.floor(Math.random() * items.length)];
}

function sleepBetween(minSeconds, maxSeconds) {
  const safeMin = Math.max(0, Number(minSeconds) || 0);
  const safeMax = Math.max(safeMin, Number(maxSeconds) || safeMin);
  sleep(safeMin + Math.random() * (safeMax - safeMin));
}

function buildBulkPayload() {
  const bulkCase = pick(BULK_CASES);
  const rows = [];
  for (let i = 0; i < BULK_ROWS; i += 1) {
    rows.push(bulkCase.values[i % bulkCase.values.length]);
  }
  return {
    scope: bulkCase.scope,
    fields: bulkCase.fields,
    rows,
    diversityMode: BULK_DIVERSITY_MODE,
    priceLimit: BULK_PRICE_LIMIT,
    productLimit: BULK_PRODUCT_LIMIT,
    limit: BULK_LIMIT,
    searchMode: SEARCH_MODE,
  };
}

function runAutocomplete(session) {
  if (SKIP_AUTOCOMPLETE) return;
  const autocompleteCase = pick(AUTOCOMPLETE_CASES);
  postJson(
    "/api/autocomplete",
    {
      ...autocompleteCase,
      filters: {},
      excludeSelf: true,
      limit: 5,
    },
    session,
    autocompleteLatency,
  );
}

function runPreview(session, searchCase) {
  if (SKIP_PREVIEW) return;
  postJson(
    "/api/query-preview",
    {
      scope: searchCase.scope,
      filters: searchCase.filters,
    },
    session,
    previewLatency,
  );
}

function runQuery(session, searchCase = pick(SEARCH_CASES)) {
  if (SKIP_QUERY) return;
  postJson(
    "/api/query",
    {
      scope: searchCase.scope,
      filters: searchCase.filters,
      sort: [{ column: "approvalDate", order: "desc" }],
      limit: QUERY_LIMIT,
      searchMode: SEARCH_MODE,
    },
    session,
    queryLatency,
  );
}

function runBulk(session) {
  if (SKIP_BULK) return;
  postJson("/api/bulk-query", buildBulkPayload(), session, bulkLatency);
}

export function setup() {
  if (!LOGIN_EMAIL || !LOGIN_PASSWORD) {
    return {};
  }
  if (LOGIN_MODE === "per-vu" && PRELOGIN_VUS) {
    const sessions = [];
    for (let i = 1; i <= VUS; i += 1) {
      sessions.push(loginSession(`BIDFinder-loadtest/prelogin-${i}`));
    }
    return { sessions };
  }
  if (LOGIN_MODE !== "shared") {
    return {};
  }

  return loginSession("BIDFinder-loadtest/setup");
}

export default function (data) {
  let session = {};
  if (LOGIN_MODE === "shared") {
    session = { token: data.token || "", cookie: data.cookie || "" };
  } else if (Array.isArray(data.sessions) && data.sessions[__VU - 1]) {
    session = data.sessions[__VU - 1];
  } else {
    session = getSession();
  }
  const searchCase = pick(SEARCH_CASES);

  if (TEST_MODE === "query") {
    runQuery(session, searchCase);
    sleep(1 + Math.random() * 4);
    return;
  }

  if (TEST_MODE === "bulk") {
    runBulk(session);
    sleep(2 + Math.random() * 6);
    return;
  }

  if (TEST_MODE === "mixed") {
    const roll = Math.random();
    if (roll < 0.7) {
      runBulk(session);
      sleep(2 + Math.random() * 6);
    } else if (roll < 0.9) {
      runQuery(session, searchCase);
      sleep(1 + Math.random() * 4);
    } else {
      runAutocomplete(session);
      sleep(Math.random() * 1.5);
      runPreview(session, searchCase);
      sleep(1 + Math.random() * 3);
    }
    return;
  }

  if (TEST_MODE === "realistic") {
    const roll = Math.random();
    const bulkCutoff = Math.max(0, Math.min(1, REALISTIC_BULK_RATE));
    const autocompletePreviewCutoff = Math.max(
      bulkCutoff,
      Math.min(1, bulkCutoff + Math.max(0, REALISTIC_AUTOCOMPLETE_PREVIEW_RATE)),
    );
    const queryCutoff = Math.max(
      autocompletePreviewCutoff,
      Math.min(1, autocompletePreviewCutoff + Math.max(0, REALISTIC_QUERY_RATE)),
    );

    if (roll < bulkCutoff) {
      runBulk(session);
      sleepBetween(REALISTIC_BULK_MIN_THINK_SECONDS, REALISTIC_BULK_MAX_THINK_SECONDS);
    } else if (roll < autocompletePreviewCutoff) {
      runAutocomplete(session);
      sleepBetween(0.5, 2);
      runPreview(session, searchCase);
      sleepBetween(REALISTIC_MIN_THINK_SECONDS, REALISTIC_MAX_THINK_SECONDS);
    } else if (roll < queryCutoff) {
      runQuery(session, searchCase);
      sleepBetween(REALISTIC_MIN_THINK_SECONDS, REALISTIC_MAX_THINK_SECONDS);
    } else {
      sleepBetween(REALISTIC_MIN_THINK_SECONDS, REALISTIC_MAX_THINK_SECONDS);
    }
    return;
  }

  runAutocomplete(session);
  sleep(Math.random() * 1.5);
  runPreview(session, searchCase);
  sleep(Math.random() * 2);
  runQuery(session, searchCase);
  sleep(1 + Math.random() * 4);
}

export function handleSummary(data) {
  return {
    stdout: JSON.stringify(
      {
        metrics: {
          http_reqs: data.metrics.http_reqs?.values,
          http_req_failed: data.metrics.http_req_failed?.values,
          http_req_duration: data.metrics.http_req_duration?.values,
          bidfinder_query_ms: data.metrics.bidfinder_query_ms?.values,
          bidfinder_bulk_ms: data.metrics.bidfinder_bulk_ms?.values,
          bidfinder_preview_ms: data.metrics.bidfinder_preview_ms?.values,
          bidfinder_autocomplete_ms: data.metrics.bidfinder_autocomplete_ms?.values,
          bidfinder_4xxs: data.metrics.bidfinder_4xxs?.values,
          bidfinder_5xxs: data.metrics.bidfinder_5xxs?.values,
          bidfinder_auth_failures: data.metrics.bidfinder_auth_failures?.values,
        },
      },
      null,
      2,
    ) + "\n",
  };
}
