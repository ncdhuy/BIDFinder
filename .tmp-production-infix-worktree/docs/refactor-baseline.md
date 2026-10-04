# Refactor baseline

Baseline captured on 2026-07-14 before source changes. This document records compatibility surfaces; it does not authorize production access.

## API routes

All routes are defined by `apps/api/server.py:app`. Methods, paths, handlers, and top-level success payloads must remain compatible.

| Method | Path | Handler | Success contract baseline |
|---|---|---|---|
| `GET`, `HEAD` | `/health` | `health` | `{"status": ...}` or empty `200` for `HEAD` |
| `GET` | `/ready` | `ready` | `{"status": ...}`; unavailable returns `503` |
| `GET` | `/api/auth/config` | `get_auth_config` | `success` plus auth configuration |
| `POST` | `/api/auth/register` | `register_user` | shared auth success response |
| `POST` | `/api/auth/login` | `login_user` | shared auth success response |
| `POST` | `/api/auth/google` | `login_user_with_google` | shared auth success response |
| `GET` | `/api/auth/me` | `get_current_user` | `success`, `user`, `auth` |
| `POST` | `/api/auth/logout` | `logout_user` | shared logout response |
| `PATCH` | `/api/auth/profile` | `patch_profile` | `success`, `message`, `user` |
| `POST` | `/api/auth/forgot-password` | `forgot_password` | `success`, `message` |
| `POST` | `/api/auth/reset-password` | `reset_password` | shared auth success response |
| `POST` | `/api/auth/change-password` | `patch_password` | `success`, `message`, `user`, auth configuration |
| `POST` | `/api/feedback` | `create_feedback` | `success`, `id`, `message` |
| `GET` | `/api/feedback/topics` | `list_feedback_topics` | `success`, `topics`, `is_admin` |
| `POST` | `/api/feedback/topics` | `create_feedback_topic` | `success`, `topic`, `message` |
| `GET` | `/api/feedback/topics/{topic_id}` | `get_feedback_topic` | `success`, `topic`, `replies`, pagination fields, `is_admin` |
| `PATCH` | `/api/feedback/topics/{topic_id}` | `update_feedback_topic` | `success`, `topic`, `message` |
| `POST` | `/api/feedback/topics/{topic_id}/replies` | `create_feedback_reply` | `success`, `reply`, `message` |
| `GET` | `/api/filter-config` | `get_filter_config` | `success`, `fields` |
| `POST` | `/api/query` | `query_data` | query result payload; locked by Phase 1 characterization test |
| `POST` | `/api/bulk-query` | `bulk_query_data` | bulk result payload; locked by Phase 1 characterization test |
| `POST` | `/api/query-preview` | `preview_query` | preview result payload; locked by Phase 1 characterization test |
| `GET` | `/api/warmup` | `warmup_database` | `success` plus timing/wakeup fields |
| `POST` | `/api/autocomplete` | `autocomplete` | `success`, `field`, `data`, `timing_ms` |
| `GET` | `/api/metadata` | `get_metadata` | metadata payload; locked by Phase 1 characterization test |

The plan's “24 routes” counts `/health` as one route even though it accepts both `GET` and `HEAD`; source currently has 25 path decorators/entries when `/health` is counted once alongside the other 24 paths above. Automated route snapshots are authoritative after Phase 1.

## Production compatibility

- Cloud Run, from `apps/api`: `uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1`.
- Render, from `apps/api`: `uvicorn server:app --host 0.0.0.0 --port $PORT --workers 2`.
- Compatibility entrypoint remains `apps/api/server.py:app`.
- No production deployment or environment mutation is part of this refactor run.

## Crawler entrypoints

Run from `crawler_engine` so existing sibling imports resolve:

```powershell
python s0_init_db.py
python s1_crawler.py
python s2_daily_manager.py
python s3_etl_pipeline.py --mode etl --date YYYYMMDD --schema all
python s3_etl_pipeline.py --mode audit-retro --date YYYYMMDD --schema all
```

`s0` performs schema migration and writes to DB. `s1` crawls and writes DB/storage. `s2` is an interactive manager with write/delete operations; only its explicit previews are safe. `s3` ETL and retro-audit connect to DB. None is a credential-free local dry-run, so this refactor must use pure fixtures/tests instead.

Environment variable names required by current entrypoints include `DATABASE_URL`, `ADMIN_EMAILS`, `BASE_DIR`, `CHROME_PROFILE_PATH`, `CHROMEDRIVER_PATH`, `USE_LOCAL_CHROMEDRIVER`, `ROOT_DATA_DIR`, and `LOCAL_TEMP_ROOT`; crawler search/storage options add more optional names. Values are intentionally omitted.

## Smoke checklist

- [ ] Open `apps/web/index.html`; no console error.
- [ ] Search and advanced filters preserve request and result rendering.
- [ ] Bulk search, download, and history preserve behavior.
- [ ] Register/login/Google/profile/logout/password flows preserve paths and Vietnamese text.
- [ ] Feedback list/detail/create/reply/update flows preserve paths and payloads.
- [ ] Autocomplete and metadata load with unchanged response handling.
- [ ] Table resize/reorder/storage, chart, map, and export work on desktop and mobile.
- [ ] Analytics event names and firing points remain unchanged.
- [ ] `apps/api/server.py:app` imports without a real DB connection.
- [ ] API route/method/response snapshots pass with mocks.
- [ ] ETL golden fixtures preserve schema, row count, normalized values, and anomaly classification.
- [ ] Crawler parser/wait tests run without Selenium or production storage.
- [ ] Staging Cloud Run and Render smoke pass before any production rollout.

Rollback for Phase 0: remove documentation only. Later phases revert one batch at a time while retaining compatibility entrypoints and classic script order.
