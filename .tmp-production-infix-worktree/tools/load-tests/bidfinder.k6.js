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
const BULK_PROFILE = __ENV.BULK_PROFILE || "synthetic";
const BULK_DIVERSITY_MODE = __ENV.BULK_DIVERSITY_MODE || "price";
const BULK_PRICE_LIMIT = Number(__ENV.BULK_PRICE_LIMIT || 3);
const BULK_PRODUCT_LIMIT = Number(__ENV.BULK_PRODUCT_LIMIT || 3);
const REALISTIC_BULK_RATE = Number(__ENV.REALISTIC_BULK_RATE || 0.02);
const REALISTIC_FORUM_RATE = Number(__ENV.REALISTIC_FORUM_RATE || 0);
const REALISTIC_AUTOCOMPLETE_PREVIEW_RATE = Number(__ENV.REALISTIC_AUTOCOMPLETE_PREVIEW_RATE || 0.2);
const REALISTIC_QUERY_RATE = Number(__ENV.REALISTIC_QUERY_RATE || 0.7);
const REALISTIC_MIN_THINK_SECONDS = Number(__ENV.REALISTIC_MIN_THINK_SECONDS || 10);
const REALISTIC_MAX_THINK_SECONDS = Number(__ENV.REALISTIC_MAX_THINK_SECONDS || 30);
const REALISTIC_BULK_MIN_THINK_SECONDS = Number(__ENV.REALISTIC_BULK_MIN_THINK_SECONDS || 20);
const REALISTIC_BULK_MAX_THINK_SECONDS = Number(__ENV.REALISTIC_BULK_MAX_THINK_SECONDS || 60);
const FORUM_COMMENTS_LIMIT = Number(__ENV.FORUM_COMMENTS_LIMIT || 20);
const SKIP_AUTOCOMPLETE = (__ENV.SKIP_AUTOCOMPLETE || "").toLowerCase() === "true";
const SKIP_PREVIEW = (__ENV.SKIP_PREVIEW || "").toLowerCase() === "true";
const SKIP_QUERY = (__ENV.SKIP_QUERY || "").toLowerCase() === "true";
const SKIP_BULK = (__ENV.SKIP_BULK || "").toLowerCase() === "true";
const SKIP_FORUM = (__ENV.SKIP_FORUM || "").toLowerCase() === "true";

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
const forumTopicsLatency = new Trend("bidfinder_forum_topics_ms");
const forumDetailLatency = new Trend("bidfinder_forum_detail_ms");

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
    bidfinder_forum_topics_ms: ["p(95)<2500"],
    bidfinder_forum_detail_ms: ["p(95)<2500"],
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

const MEDICINE_UPLOAD_ROWS = [
  { activeIngredient: "Acarbose", concentration: "50mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Acetazolamid", concentration: "250mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Acetylcystein", concentration: "300mg", route: "Tiêm", dosageForm: "", unit: "Ống" },
  { activeIngredient: "Aciclovir", concentration: "5%; 5g", route: "Dùng Ngoài", dosageForm: "", unit: "Tuýp" },
  { activeIngredient: "Acid thioctic (Meglumin thioctat)", concentration: "300mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Adapalen + Clindamycin", concentration: "(15mg; 150mg) x 15g", route: "Dùng ngoài", dosageForm: "", unit: "Tuýp" },
  { activeIngredient: "Albendazol", concentration: "200mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Alendronat", concentration: "70mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Allopurinol", concentration: "300mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Alphachymotrypsin", concentration: "4200 đơn vị", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Amikacin", concentration: "500mg/2ml", route: "Tiêm", dosageForm: "", unit: "Ống" },
  { activeIngredient: "Amlodipin", concentration: "5mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Amoxicillin", concentration: "500mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Amoxicillin + Acid clavulanic", concentration: "875mg + 125mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Aspirin", concentration: "81mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Atorvastatin", concentration: "20mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Azithromycin", concentration: "500mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Betahistin", concentration: "16mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Cefixim", concentration: "100mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Ceftriaxon", concentration: "1g", route: "Tiêm", dosageForm: "", unit: "Lọ" },
  { activeIngredient: "Cetirizin", concentration: "10mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Ciprofloxacin", concentration: "500mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Clarithromycin", concentration: "500mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Clopidogrel", concentration: "75mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Diclofenac", concentration: "75mg/3ml", route: "Tiêm", dosageForm: "", unit: "Ống" },
  { activeIngredient: "Domperidon", concentration: "10mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Esomeprazol", concentration: "40mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Furosemid", concentration: "40mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Metformin", concentration: "500mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Omeprazol", concentration: "20mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Paracetamol", concentration: "500mg", route: "Uống", dosageForm: "", unit: "Viên" },
  { activeIngredient: "Salbutamol", concentration: "2mg", route: "Uống", dosageForm: "", unit: "Viên" },
];

const GOODS_UPLOAD_ROWS = [
  {
    goodsName: "Máy xét nghiệm sinh hóa tự động",
    technicalSpec: "Máy xét nghiệm sinh hóa tự động công suất tối thiểu 400 test/giờ, có bộ đọc quang học, khay mẫu, khay hóa chất, phần mềm quản lý kết quả",
    bidItem: "Máy xét nghiệm sinh hóa",
    model: "BS-400",
    brand: "Mindray",
  },
  {
    goodsName: "Máy xét nghiệm huyết học tự động",
    technicalSpec: "Máy xét nghiệm huyết học 5 thành phần bạch cầu, tối thiểu 60 mẫu/giờ, tự động hút mẫu, có màn hình cảm ứng và máy in",
    bidItem: "Máy huyết học",
    model: "BC-5380",
    brand: "Mindray",
  },
  {
    goodsName: "Máy siêu âm tổng quát",
    technicalSpec: "Máy siêu âm màu doppler, màn hình LCD, có đầu dò convex, linear, cardiac, lưu trữ hình ảnh và xuất dữ liệu DICOM",
    bidItem: "Máy siêu âm màu",
    model: "DC-40",
    brand: "Mindray",
  },
  {
    goodsName: "Máy thở xâm nhập và không xâm nhập",
    technicalSpec: "Máy thở ICU có các mode VCV, PCV, SIMV, PSV, CPAP, màn hình cảm ứng, pin dự phòng, cảnh báo áp lực và thể tích",
    bidItem: "Máy thở",
    model: "SV300",
    brand: "Mindray",
  },
  {
    goodsName: "Monitor theo dõi bệnh nhân",
    technicalSpec: "Monitor theo dõi bệnh nhân 5 thông số ECG, SpO2, NIBP, nhiệt độ, nhịp thở, màn hình 12 inch, có pin sạc",
    bidItem: "Monitor bệnh nhân",
    model: "iMEC12",
    brand: "Edan",
  },
  {
    goodsName: "Bơm tiêm điện",
    technicalSpec: "Bơm tiêm điện dùng cho syringe 5ml, 10ml, 20ml, 30ml, 50ml, có chức năng chống bolus và cảnh báo tắc nghẽn",
    bidItem: "Bơm tiêm điện",
    model: "SN-50C6",
    brand: "SinoMDT",
  },
  {
    goodsName: "Bơm truyền dịch",
    technicalSpec: "Bơm truyền dịch kiểm soát tốc độ truyền, tương thích nhiều loại dây truyền, có cảnh báo bọt khí, tắc nghẽn, hết dịch",
    bidItem: "Bơm truyền dịch",
    model: "BeneFusion VP5",
    brand: "Mindray",
  },
  {
    goodsName: "Máy điện tim 12 cần",
    technicalSpec: "Máy điện tim 12 kênh, màn hình màu, ghi đồng thời 12 đạo trình, có pin sạc, bộ nhớ trong và in giấy nhiệt",
    bidItem: "Máy điện tim",
    model: "ECG-1250",
    brand: "Nihon Kohden",
  },
  {
    goodsName: "Máy X quang kỹ thuật số",
    technicalSpec: "Hệ thống X quang kỹ thuật số DR, detector phẳng, máy phát cao tần, bàn chụp, trạm xử lý ảnh và phần mềm DICOM",
    bidItem: "Máy X quang DR",
    model: "DigitalDiagnost",
    brand: "Philips",
  },
  {
    goodsName: "Tủ an toàn sinh học cấp II",
    technicalSpec: "Tủ an toàn sinh học cấp II type A2, lọc HEPA, luồng khí đứng, đèn UV, kính chắn phía trước, cảnh báo tốc độ gió",
    bidItem: "Tủ an toàn sinh học",
    model: "BSC-1300IIA2",
    brand: "Biobase",
  },
  {
    goodsName: "Hóa chất xét nghiệm glucose",
    technicalSpec: "Hóa chất xét nghiệm glucose dùng cho máy sinh hóa tự động, phương pháp enzym, đóng gói dạng kit, có calibrator và control",
    bidItem: "Hóa chất glucose",
    model: "GLU-KIT",
    brand: "Roche",
  },
  {
    goodsName: "Hóa chất xét nghiệm creatinine",
    technicalSpec: "Hóa chất xét nghiệm creatinine phương pháp Jaffe hoặc enzym, dùng cho máy sinh hóa tự động, ổn định sau mở nắp",
    bidItem: "Hóa chất creatinine",
    model: "CREA-KIT",
    brand: "Beckman Coulter",
  },
  {
    goodsName: "Que thử đường huyết",
    technicalSpec: "Que thử đường huyết mao mạch, tương thích máy đo đường huyết cầm tay, dải đo rộng, đóng gói hộp 50 que",
    bidItem: "Que thử glucose",
    model: "Accu-Chek",
    brand: "Roche",
  },
  {
    goodsName: "Kim luồn tĩnh mạch",
    technicalSpec: "Kim luồn tĩnh mạch ngoại vi các cỡ 18G, 20G, 22G, 24G, vật liệu FEP hoặc PU, có cánh cố định, tiệt trùng",
    bidItem: "Kim luồn",
    model: "IV Catheter",
    brand: "B. Braun",
  },
  {
    goodsName: "Bơm tiêm dùng một lần",
    technicalSpec: "Bơm tiêm nhựa dùng một lần các cỡ 1ml, 3ml, 5ml, 10ml, 20ml, có kim, vô trùng, không độc",
    bidItem: "Bơm tiêm",
    model: "Disposable syringe",
    brand: "Vinahankook",
  },
  {
    goodsName: "Găng tay y tế",
    technicalSpec: "Găng tay khám bệnh nitrile hoặc latex, không bột, các cỡ S M L, dùng một lần, đạt tiêu chuẩn y tế",
    bidItem: "Găng tay khám bệnh",
    model: "Nitrile glove",
    brand: "Vglove",
  },
];

const UPLOAD_PROFILE_CONFIG = {
  "medicine-upload": {
    scope: "medicine",
    fields: ["activeIngredient", "concentration", "route", "dosageForm"],
    rows: MEDICINE_UPLOAD_ROWS,
  },
  "goods-upload": {
    scope: "goods",
    fields: ["goodsName", "technicalSpec"],
    rows: GOODS_UPLOAD_ROWS,
  },
};

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
  recordResponse(path, res, trend, started);
  return res;
}

function getJson(path, session, trend) {
  const started = Date.now();
  const res = http.get(`${BASE_URL}${path}`, params(session));
  recordResponse(path, res, trend, started);
  return res;
}

function recordResponse(path, res, trend, started) {
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
  const uploadProfile = BULK_PROFILE === "upload-mix"
    ? (__ITER % 2 === 0 ? UPLOAD_PROFILE_CONFIG["medicine-upload"] : UPLOAD_PROFILE_CONFIG["goods-upload"])
    : UPLOAD_PROFILE_CONFIG[BULK_PROFILE];

  if (uploadProfile) {
    const rows = [];
    for (let i = 0; i < BULK_ROWS; i += 1) {
      rows.push(uploadProfile.rows[i % uploadProfile.rows.length]);
    }
    return {
      scope: uploadProfile.scope,
      fields: uploadProfile.fields,
      rows,
      diversityMode: BULK_DIVERSITY_MODE,
      priceLimit: BULK_PRICE_LIMIT,
      productLimit: BULK_PRODUCT_LIMIT,
      limit: BULK_LIMIT,
      searchMode: SEARCH_MODE,
    };
  }

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

function runForum(session) {
  if (SKIP_FORUM) return;
  const topicsRes = getJson("/api/feedback/topics", session, forumTopicsLatency);
  if (topicsRes.status < 200 || topicsRes.status >= 300) return;

  let topics = [];
  try {
    topics = topicsRes.json("topics") || [];
  } catch (error) {
    topics = [];
  }
  if (!Array.isArray(topics) || topics.length === 0) return;

  const topic = pick(topics);
  const topicId = Number(topic?.id || 0);
  if (!topicId) return;

  const commentsLimit = Math.max(1, Math.min(50, FORUM_COMMENTS_LIMIT));
  getJson(`/api/feedback/topics/${topicId}?comments_limit=${commentsLimit}&comments_offset=0`, session, forumDetailLatency);
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

  if (TEST_MODE === "forum") {
    runForum(session);
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
    const forumCutoff = Math.max(
      bulkCutoff,
      Math.min(1, bulkCutoff + Math.max(0, REALISTIC_FORUM_RATE)),
    );
    const autocompletePreviewCutoff = Math.max(
      forumCutoff,
      Math.min(1, forumCutoff + Math.max(0, REALISTIC_AUTOCOMPLETE_PREVIEW_RATE)),
    );
    const queryCutoff = Math.max(
      autocompletePreviewCutoff,
      Math.min(1, autocompletePreviewCutoff + Math.max(0, REALISTIC_QUERY_RATE)),
    );

    if (roll < bulkCutoff) {
      runBulk(session);
      sleepBetween(REALISTIC_BULK_MIN_THINK_SECONDS, REALISTIC_BULK_MAX_THINK_SECONDS);
    } else if (roll < forumCutoff) {
      runForum(session);
      sleepBetween(REALISTIC_MIN_THINK_SECONDS, REALISTIC_MAX_THINK_SECONDS);
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
          bidfinder_forum_topics_ms: data.metrics.bidfinder_forum_topics_ms?.values,
          bidfinder_forum_detail_ms: data.metrics.bidfinder_forum_detail_ms?.values,
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
