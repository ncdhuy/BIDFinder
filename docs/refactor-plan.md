# Kế hoạch refactor BIDFinder

## 1. Mục tiêu

Refactor theo từng PR nhỏ, giữ nguyên hành vi đang chạy tốt, giảm code trùng, tách ranh giới trách nhiệm, và đưa file sinh ra trong quá trình vận hành ra khỏi source tree chính.

Kết quả mong muốn:

- Frontend, API và crawler có ranh giới rõ; mỗi entrypoint chỉ điều phối.
- Logic dùng chung có một nguồn duy nhất.
- File generated/audit/repair/fixture được phân loại, có chủ sở hữu và quy tắc lưu giữ.
- Có test đặc tả hành vi trước khi di chuyển logic.
- Giữ tương thích với Cloud Run, Render, frontend tĩnh và các lệnh crawler hiện có.

## 2. Ngoài phạm vi

- Không đổi FastAPI, Postgres, Selenium hoặc frontend tĩnh sang framework khác.
- Không thiết kế lại UI, schema DB hay thuật toán nghiệp vụ trong cùng đợt refactor.
- Không chạy repair/backfill hoặc migration trên DB thật để “kiểm tra”.
- Không xóa file `temp_`, `tmp_`, `audit_`, `repair_` chỉ dựa vào tên.
- Không gộp refactor với tối ưu hiệu năng chưa có số đo.

## 3. Baseline đã khảo sát

### 3.1 Cấu trúc và trạng thái

- Ba vùng chính: `apps/web`, `apps/api`, `crawler_engine`.
- Production: frontend gọi FastAPI trên Cloud Run; Render là backend dự phòng; dữ liệu ở Neon Postgres.
- Worktree hiện có thay đổi người dùng tại `crawler_engine/schema_config.py` và file `AGENTS.md` chưa track. Không được ghi đè hoặc đưa chúng vào PR refactor ngoài ý muốn.
- `.env` của API/crawler đang được ignore và không được Git track.
- Có hai file report đã track dù hiện khớp rule ignore: `crawler_engine/reports/existing_vendor_fill_risk_20260420_061304.xlsx` và `crawler_engine/reports/existing_vendor_fill_risk_20260420_061608.xlsx`.

### 3.2 Quy mô và hotspot

Số liệu không tính `.git`, cache Python và các thư mục data runtime đã ignore:

- 109 file; `crawler_engine` 63 file, `apps` 36 file.
- `apps/web/script.js`: 7.667 dòng.
- `apps/web/style.css`: 7.315 dòng.
- `crawler_engine/s2_daily_manager.py`: 5.464 dòng.
- `crawler_engine/s1_crawler.py`: 5.405 dòng.
- `crawler_engine/s3_etl_pipeline.py`: 4.014 dòng.
- `apps/api/server.py`: 3.366 dòng, 93 hàm top-level, 20 request/model class, 24 route.
- `apps/web/search-form.js`: 3.178 dòng; riêng `connectedCallback` chiếm khoảng 1.598 dòng.
- `crawler_engine/test_module.py`: 2.624 dòng, 100 hàm top-level nhưng chỉ có một hàm tên `test_*`; đây không phải test suite đúng nghĩa.

### 3.3 Trùng lặp đáng xử lý

- `s1_crawler.py` và `test_module.py`: 60 tên hàm chung; 19 hàm giống AST hoàn toàn, khoảng 175 dòng bản sao có thể bỏ.
- `s2_daily_manager.py` và `s3_etl_pipeline.py`: 37 tên hàm chung; 16 hàm giống AST hoàn toàn, khoảng 134 dòng bản sao có thể bỏ.
- `s2_daily_manager.py`/`s3_etl_pipeline.py` còn trùng tên với `schema_normalization_shared.py`; nội dung không hoàn toàn giống, cần test để xác định khác biệt có chủ đích hay drift.
- Frontend nạp đồng thời bản minified và non-minified của Chart.js 4.4.0.

### 3.4 File và asset

- 41 file data/binary đang track, tổng khoảng 37,34 MB.
- `apps/web/Vietnam34.geojson` khoảng 31,7 MB không có tham chiếu tên file trong HTML/JS/CSS; `Vietnam34.map.json` đang được tham chiếu.
- 12 asset ảnh không có tham chiếu tĩnh trong HTML/JS/CSS: nhiều bản `logo*`, `pointer.png`, `resize.png`, `search_bar*.png`.
- 27 candidate liên quan audit/repair/temp/report. Đây là candidate để phân loại, không phải danh sách xóa.

### 3.5 Chất lượng và test

- Không thấy CI, lint, formatter, type-check hoặc test suite chuẩn.
- Test thực tế chủ yếu là script crawler/debug và k6 load test.
- Refactor lớn trước khi có characterization test sẽ có rủi ro cao, đặc biệt với query SQL, normalize Excel, browser selector và static global JS.

### 3.6 Bảo mật

- Không đưa `.env`, token, URL DB hoặc credential vào log, fixture, snapshot hay tài liệu.
- Credential từng xuất hiện trong IDE/chat/log phải được rotate, không tái sử dụng.

## 4. Nguyên tắc triển khai

1. Mỗi PR chỉ thay một ranh giới; tránh “big bang”.
2. Viết characterization test trước khi chuyển logic.
3. Move trước, cải tiến sau; không vừa di chuyển vừa đổi thuật toán.
4. Giữ compatibility shim tại entrypoint cũ trong suốt quá trình chuyển đổi.
5. Không thêm framework/bundler/dependency nếu stdlib hoặc cấu trúc hiện có đủ dùng.
6. Mọi file xóa phải có bằng chứng: không được tham chiếu, không phải entrypoint vận hành, không phải audit evidence, và được owner duyệt.
7. Mọi thao tác DB chỉ dùng read-only, dry-run hoặc DB test riêng.
8. Mỗi PR phải có rollback độc lập bằng revert, không phụ thuộc PR sau.

## 5. Kiến trúc đích tối thiểu

Không tạo nhiều layer ngay từ đầu. Chỉ tách theo domain đã tồn tại.

```text
apps/
  api/
    server.py              # tạo app, middleware, lifecycle, include router; giữ server:app
    db.py                  # pool, transaction/read helpers
    search_api.py          # query/preview/bulk/autocomplete/metadata
    search_queries.py      # pure query builders và filter normalization
    auth_api.py            # auth routes; gọi auth_utils
    auth_utils.py          # auth/session/password service hiện có
    feedback_api.py        # feedback routes và DB operations

  web/
    index.html
    config.js
    auth.js
    search-form.js
    table.js               # render, resize, reorder, storage
    search.js              # request, filter, result state
    charts.js              # chart/map/metadata visualization
    bulk.js                # bulk query/download/history
    script.js              # bootstrap và compatibility globals còn lại
    base.css
    table.css
    panels.css
    responsive.css

crawler_engine/
  s0_init_db.py            # giữ CLI/entrypoint
  s1_crawler.py            # giữ orchestration/compatibility
  s2_daily_manager.py      # giữ orchestration/compatibility
  s3_etl_pipeline.py       # giữ orchestration/compatibility
  browser_runtime.py       # Selenium setup, wait, tab/runtime helpers
  procurement_parsing.py   # mã thông báo, URL, JSON/table parsers
  schema_normalization_shared.py
  db.py                    # kết nối/helper DB dùng chung
  storage_adapter.py
  ops/
    audit/
    repair/
    backfill/
  experiments/             # script/notebook điều tra còn cần giữ

tests/
  api/
  crawler/
  fixtures/
```

Lưu ý:

- Cấu trúc trên là trạng thái cuối, không phải một PR duy nhất.
- `server.py` và `s0`–`s3` tiếp tục tồn tại để không phá deploy, scheduler và tài liệu vận hành.
- Frontend trước mắt vẫn dùng classic script theo thứ tự hiện tại để hỗ trợ mở `index.html` trực tiếp. Chỉ chuyển ES modules khi cách serve frontend đã được chuẩn hóa và có browser smoke test.
- Chỉ tạo `ops/` sau khi đã xác nhận cách các script được gọi và sửa import/CWD an toàn.

## 6. Roadmap theo phase

Ước lượng dành cho một developer, chưa tính thời gian chờ review hoặc chạy crawler dài.

### Phase 0 — An toàn và inventory (0,5–1 ngày)

Mục tiêu: khóa baseline và tránh mất dữ liệu.

Công việc:

1. Tạo branch refactor từ `main` sạch; giữ riêng thay đổi hiện có ở `schema_config.py`.
2. Rotate credential từng bị lộ qua IDE/chat/log; không ghi giá trị vào ticket hoặc commit.
3. Ghi `docs/artifact-inventory.md` gồm: path, loại, nguồn tạo, người dùng, có tái tạo được không, nơi archive, quyết định keep/move/delete.
4. Ghi route/API baseline cho 24 endpoint hiện có.
5. Ghi các command production bắt buộc giữ:
   - Cloud Run: `server:app`, port 8080, một worker theo Dockerfile.
   - Render: `server:app`, `$PORT`, hai worker theo Procfile.
   - Crawler: cách gọi `s0`–`s3`, working directory và biến môi trường.
6. Tạo checklist smoke hiện tại cho search, bulk search, auth, feedback, autocomplete, metadata, map và crawler dry-run.

Gate hoàn tất:

- Không đổi source behavior.
- Mọi artifact candidate có trạng thái `unknown`, `fixture`, `evidence`, `generated` hoặc `runtime`.
- Credential liên quan đã rotate.

Rollback: không cần; phase chỉ thêm tài liệu và rotate secret ngoài Git.

### Phase 1 — Characterization tests và CI tối thiểu (2–4 ngày)

Mục tiêu: có tín hiệu phát hiện regression trước khi move code.

Công việc:

1. Dùng `unittest` stdlib cho Python; chưa thêm pytest nếu chưa cần.
2. API:
   - Test pure filter/query builders bằng input/output snapshot nhỏ, không chứa dữ liệu thật.
   - Test auth normalization, cookie/session expiry và error mapping bằng mock.
   - Ghi contract cho response shape của `/api/query`, `/api/bulk-query`, `/api/query-preview`, `/api/autocomplete`.
3. Crawler/ETL:
   - Tạo fixture Excel/CSV nhỏ, vô danh, đại diện cho group header, sparse row, summary row, numeric normalization và duplicate columns.
   - Golden test cho các hàm đang trùng giữa `s2` và `s3`.
   - Test parser/wait helper không cần mở browser nếu có thể tách pure logic.
4. Frontend:
   - `node --check` cho từng file JS.
   - Browser smoke checklist trên `index.html`; kiểm tra console error, search, filter, auth modal, table, chart, export.
   - Không thêm Playwright ngay; thêm khi smoke thủ công trở thành bottleneck.
5. CI tối thiểu chạy syntax check, `unittest`, secret scan theo pattern, và không truy cập DB production.

Gate hoàn tất:

- Có test đỏ khi cố ý đổi một query/filter/normalization behavior trọng yếu.
- CI chạy được từ clone sạch với `.env.example`, không cần credential thật.
- Test không ghi Neon/R2 và không mở Selenium ngoài job riêng.

Rollback: revert riêng PR test/CI; source production chưa đổi.

### Phase 2 — Cleanup chắc chắn, ít rủi ro (1–2 ngày)

Mục tiêu: giảm rác rõ ràng trước khi đổi kiến trúc.

Công việc:

1. Bỏ một trong hai `<script>` Chart.js 4.4.0; giữ bản minified cho production.
2. Xác minh `Vietnam34.geojson` không được CDN, script ngoài repo hoặc quy trình build dùng. Nếu đúng, archive/tag rồi bỏ khỏi Git; giữ `Vietnam34.map.json`.
3. Xác minh 12 ảnh không tham chiếu bằng source search, browser network và owner review; chỉ xóa file được xác nhận.
4. Với hai report đã track nhưng nằm trong ignored directory: archive kèm checksum, sau đó `git rm --cached` nếu không phải fixture/evidence bắt buộc trong repo.
5. Bổ sung `.env.example` chỉ chứa tên biến và giá trị giả; giữ `.env` ignored.
6. Không đổi tên/move audit/repair script ở phase này.

Gate hoàn tất:

- Browser smoke pass; chart/map/export vẫn hoạt động.
- Clone sạch không thiếu asset runtime.
- Không xóa artifact trạng thái `unknown` hoặc `evidence` chưa archive.
- Repo có thể giảm ngay khoảng 31,7 MB nếu GeoJSON thực sự không dùng.

Rollback: revert PR; asset lớn phải có Git tag hoặc archive checksum trước khi xóa.

### Phase 3 — Hợp nhất shared logic crawler/ETL (4–7 ngày)

Mục tiêu: loại bản sao có bằng chứng trước, rồi xử lý semantic drift.

Công việc theo thứ tự:

1. Chuyển 16 hàm giống hoàn toàn giữa `s2_daily_manager.py` và `s3_etl_pipeline.py` vào module shared phù hợp; ưu tiên mở rộng `schema_normalization_shared.py` thay vì tạo module mới.
2. Chuyển 19 hàm giống hoàn toàn giữa `s1_crawler.py` và `test_module.py` vào `procurement_parsing.py` hoặc `browser_runtime.py` theo trách nhiệm.
3. Với 41 hàm cùng tên nhưng khác nội dung giữa `s1`/`test_module`, chạy golden test và phân loại:
   - khác có chủ đích: đổi tên rõ variant;
   - drift không chủ đích: chọn implementation chuẩn và dùng chung;
   - chỉ phục vụ thử nghiệm: giữ trong `experiments/`.
4. Với 21 hàm cùng tên nhưng khác nội dung giữa `s2`/`s3`, so sánh output trên fixture trước khi hợp nhất.
5. Đổi vai trò `test_module.py`: nếu là crawler/debug runner thì chuyển thành `experiments/khlcnt_debug_runner.py`; nếu có test thật thì chuyển test đó vào `tests/crawler`.
6. Tách Selenium runtime/wait/tab helpers khỏi business parsing; không thay selector trong cùng PR.
7. Tách DB connection/helper dùng chung; không tạo repository/service abstraction một implementation.

Gate hoàn tất:

- 35 exact duplicate function hiện biết giảm về 0.
- Mọi duplicate cùng tên còn lại có lý do hoặc issue theo dõi.
- Golden ETL output, số dòng, schema và anomaly classification không đổi.
- Crawler sample/dry-run pass; không ghi DB thật.

Rollback: mỗi nhóm helper là một PR; entrypoint cũ import helper mới nên revert độc lập.

### Phase 4 — Tách API theo domain (3–5 ngày)

Mục tiêu: `server.py` chỉ còn composition, lifecycle và middleware.

Thứ tự PR:

1. Tách `db.py`: pool lifecycle, connection/read helpers, transaction boundary.
2. Tách `search_queries.py`: filter normalization và SQL builder pure; giữ route tại chỗ.
3. Tách `search_api.py`: query, bulk, preview, autocomplete, metadata, warmup/filter config.
4. Tách `feedback_api.py`.
5. Tách `auth_api.py`; tiếp tục dùng `auth_utils.py`, chưa chia nhỏ auth service nếu chưa cần.
6. Giữ `server.py` export đúng `app`; không đổi Dockerfile/Procfile trừ import path nội bộ.

Ranh giới:

- Route xử lý HTTP/validation.
- Query builder tạo SQL và params, không mở connection.
- DB helper quản lý pool/transaction, không biết HTTP.
- Auth/feedback/search không import ngược `server.py`.

Gate hoàn tất:

- Danh sách 24 route, method, path và response shape không đổi.
- Import check `server:app` pass từ `apps/api`.
- API contract tests pass với DB mock/test.
- k6 smoke/load không regression đáng kể so với baseline.
- Deploy staging Cloud Run và Render smoke pass trước production.

Rollback: `server.py` luôn là compatibility entrypoint; revert từng router extraction.

### Phase 5 — Tách frontend static theo feature (4–7 ngày)

Mục tiêu: giảm global coupling mà không thêm framework hoặc bundler.

Thứ tự PR:

1. Dùng 30 section marker có sẵn trong `script.js` để lập dependency map giữa table, search, panels, chart/map, metadata, cell/range, history, bulk và product journey.
2. Tách `table.js` trước vì vùng này đã có boundary rõ: render, resize, drag/drop, local storage.
3. Tách `charts.js`, sau đó `bulk.js`; đây là các feature tương đối độc lập.
4. Tách search/request state vào `search.js`.
5. Giữ `script.js` làm bootstrap; mỗi PR chỉ chuyển nguyên khối, không rewrite.
6. Với `search-form.js`, tách template dài khỏi lifecycle logic nhưng vẫn dùng file local/classic script; không fetch template khi chạy `file://`.
7. Tách CSS theo vùng đã ổn định: base, table, panels/modal/chart, responsive. Giữ thứ tự cascade và chạy visual comparison sau từng lần tách.
8. Chỉ gom global vào một namespace nhỏ khi collision/coupling thực tế yêu cầu; không dựng framework module riêng.

Gate hoàn tất:

- Mở trực tiếp `index.html` vẫn chạy nếu đây còn là luồng local được hỗ trợ.
- Không đổi DOM selector, Vietnamese UI text hoặc analytics event trong PR move.
- Console không có lỗi; search/auth/table/chart/map/export/bulk smoke pass.
- Visual diff các viewport desktop/mobile không có thay đổi ngoài ý muốn.

Rollback: giữ nguyên thứ tự `<script>` và `<link>`; mỗi extraction là một commit/PR có thể revert.

### Phase 6 — Sắp xếp ops, audit, repair và artifact (2–4 ngày)

Mục tiêu: source tree sạch nhưng không mất lịch sử điều tra.

Quy tắc phân loại:

- `runtime`: cần cho app/crawler chạy, ở package runtime.
- `tool`: script lặp lại được, chuyển vào `ops/audit`, `ops/repair` hoặc `ops/backfill`.
- `fixture`: dữ liệu nhỏ, deterministic, vô danh; chuyển vào `tests/fixtures`.
- `evidence`: kết quả audit/repair cần lưu; archive ở R2/release storage với checksum và link trong inventory.
- `generated`: tái tạo được; bỏ khỏi Git và thêm ignore rule.
- `unknown`: giữ nguyên cho đến khi owner xác nhận.

Công việc:

1. Chuẩn hóa mỗi ops script: module docstring, usage, input, output, read/write impact, dry-run, ngày/ticket liên quan.
2. Move bằng `git mv`; giữ wrapper cũ một release nếu scheduler/manual run còn dùng path cũ.
3. Notebook chỉ giữ nếu có runbook hoặc insight chưa chuyển sang test/script; output cell lớn phải clear trước commit.
4. Report version `v1`–`v5` được archive; chỉ giữ fixture nhỏ hoặc report cuối nếu có lý do nghiệp vụ.
5. Cập nhật `.gitignore` theo thư mục output mới.

Gate hoàn tất:

- Không còn file audit/repair/temp chưa phân loại.
- Mỗi tool ghi DB có `--dry-run` mặc định hoặc yêu cầu cờ xác nhận rõ.
- Link/checksum archive kiểm tra được.
- Runbook dùng path mới; wrapper cũ có thời hạn xóa cụ thể.

Rollback: wrapper path cũ và archive cho phép quay lại; không xóa evidence trực tiếp.

### Phase 7 — Chuẩn hóa vận hành và tài liệu (2–3 ngày)

Mục tiêu: kiến trúc mới trở thành cách làm mặc định.

Công việc:

1. Cập nhật `README.md`, `docs/project-structure.md`, Cloud Run/Render routing và crawler runbook.
2. Tạo một command kiểm tra local thống nhất bằng script ngắn hoặc Make-equivalent phù hợp Windows; không thêm task runner nếu PowerShell đủ dùng.
3. Thêm formatter/linter chỉ sau khi chốt cấu hình và chạy ở PR riêng, tránh trộn mechanical diff với refactor.
4. Ghi ADR ngắn cho ba quyết định: static frontend không bundler, compatibility entrypoint, chính sách artifact.
5. Xóa compatibility wrapper chỉ sau ít nhất một release ổn định và xác nhận không còn caller.

Gate hoàn tất:

- Developer mới có thể clone, cấu hình `.env.example`, chạy checks và hiểu ba subsystem từ docs.
- CI xanh, staging smoke xanh, production metrics ổn định.
- Không còn tài liệu trỏ path cũ.

## 7. Chuỗi PR đề xuất

1. `docs: inventory refactor baseline and artifacts`
2. `test: add API and ETL characterization checks`
3. `chore: remove verified duplicate frontend assets`
4. `refactor: share exact ETL normalization helpers`
5. `refactor: share crawler parsing and browser helpers`
6. `refactor: classify crawler debug runner and real tests`
7. `refactor: extract API database and query builders`
8. `refactor: split API routes by domain`
9. `refactor: split frontend table and chart features`
10. `refactor: split frontend search and bulk features`
11. `chore: organize crawler ops and archive artifacts`
12. `docs: finalize architecture and runbooks`

Mỗi PR nên giữ dưới khoảng 500 dòng thay đổi logic. PR move thuần có thể lớn hơn nhưng không được kèm rewrite.

## 8. Ma trận validation

| Vùng | Check bắt buộc | Không được làm |
|---|---|---|
| Frontend | JS syntax, browser console, desktop/mobile smoke, search/auth/table/chart/map/export | đổi framework, đổi UI trong PR move |
| API | import `server:app`, contract test 24 route, query builder test, staging smoke, k6 | gọi DB production từ CI |
| Crawler | golden fixture, dry-run, sample crawl, output/schema/count comparison | broad repair/backfill trên DB thật |
| Artifact | source reference search, owner approval, checksum/archive restore | xóa theo tên hoặc tuổi file |
| Deploy | Cloud Run staging, Render staging/backup smoke, env parity | đổi entrypoint cùng lúc với domain logic |

## 9. Chỉ số hoàn tất

- 35 exact duplicate function đã biết giảm về 0.
- 97 nhóm tên hàm trùng trọng yếu (`60` và `37`) đều được hợp nhất hoặc ghi lý do khác biệt.
- `server.py` chỉ còn app composition/lifecycle/middleware và compatibility export.
- `script.js` không còn chứa toàn bộ table/search/chart/bulk trong một file.
- Một bản Chart.js được nạp.
- Zero artifact trạng thái `unknown` trong source tree mục tiêu.
- 24 API route giữ method/path/response contract.
- Critical ETL fixtures giữ schema, row count và normalized values.
- Repo giảm khoảng 31,7 MB nếu xác minh và loại `Vietnam34.geojson`; số MB là lợi ích phụ, không thay thế kiểm tra runtime.
- Không có credential trong Git, fixture, log CI hoặc tài liệu.

## 10. Điểm dừng và rollback production

Dừng rollout nếu có một trong các tín hiệu:

- API error rate, latency hoặc DB connection tăng so với baseline.
- Search result count/schema khác trên cùng request fixture.
- ETL row count, mapping hoặc anomaly classification khác ngoài thay đổi đã duyệt.
- Frontend console error, chart/map/export hỏng hoặc analytics event mất.
- Crawler cần ghi DB/R2 thật để chứng minh refactor đúng.

Khi dừng:

1. Revert PR gần nhất, không vá tiếp trên production.
2. Giữ artifact/log tối thiểu đã scrub secret.
3. Tái hiện bằng fixture hoặc staging.
4. Chỉ rollout lại khi gate của phase xanh.

## 11. Thứ tự ưu tiên thực tế

Nếu chỉ có thời gian cho ba việc đầu:

1. Thêm characterization tests cho API query và ETL normalization.
2. Hợp nhất exact duplicate crawler/ETL, giữ entrypoint cũ.
3. Xác minh rồi bỏ GeoJSON không dùng, bản Chart.js trùng và asset không tham chiếu.

Ba việc này giảm rủi ro và chi phí bảo trì rõ nhất mà chưa cần đổi kiến trúc lớn.
