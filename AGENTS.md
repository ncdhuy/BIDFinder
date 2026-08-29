# AGENTS.md

Instruction manual for AI coding agents working in this repository.

## Project Summary

BIDFinder is a procurement search product with three main parts:

- `apps/web/`: static frontend assets and browser JavaScript.
- `apps/api/`: FastAPI backend used by the frontend.
- `crawler_engine/`: crawler, database initialization, ETL, repair, audit, and data-quality tooling.

Production routing is documented as:

```text
Frontend -> Cloud Run FastAPI backend -> Neon Postgres
Backup backend: Render -> Neon Postgres
```

See also:

- `README.md`
- `docs/project-structure.md`
- `docs/cloud-run.md`
- `docs/backend-routing.md`
- `tools/load-tests/README.md`

## Repository Layout

```text
apps/
  api/              FastAPI backend, Dockerfile, Render Procfile, Cloud Run deploy script
  web/              Static frontend, auth, analytics, filters, result rendering

crawler_engine/     Existing crawler/data pipeline, intentionally still at repo root
docs/               Operations and handover documentation
tools/load-tests/   k6 load-test scripts and notes
```

## Command Rules

This workspace has a local instruction to prefix shell commands with `rtk`.

Examples:

```powershell
rtk rg --files
rtk git status --short
rtk powershell -NoProfile -Command Get-Content -LiteralPath README.md
rtk npm run build
rtk pytest -q
```

When using PowerShell built-ins such as `Get-Content`, invoke them through `powershell -Command` under `rtk`; `rtk Get-Content ...` may not resolve because `Get-Content` is a cmdlet, not a standalone executable.

## Local Development

Run the backend locally:

```powershell
cd apps\api
uvicorn server:app --reload --host 127.0.0.1 --port 8001
```

Open the frontend locally:

```text
apps/web/index.html
```

Run k6 load tests:

```powershell
k6 run .\tools\load-tests\bidfinder.k6.js
```

Backend API base URLs are centralized in:

```text
apps/web/config.js
```

## Important Code Areas

### Frontend

- `apps/web/index.html`: page shell.
- `apps/web/config.js`: API base URL selection.
- `apps/web/script.js`: query flow, rendering, map loading, metadata, bulk query, feedback.
- `apps/web/search-form.js`: custom search form and advanced filters.
- `apps/web/auth.js`: auth UI and auth API client behavior.
- `apps/web/analytics.js` and `apps/web/analytics-config.js`: PostHog integration.

### Backend

- `apps/api/server.py`: main FastAPI app, database pool, routes, query building, feedback, auth endpoints.
- `apps/api/auth_utils.py`: auth/session/password-reset helper logic.
- `apps/api/explain_hot_queries.py`: query inspection/debugging utility.
- `apps/api/deploy-cloud-run.ps1`: Cloud Run deployment helper.

### Crawler And Data Pipeline

- `crawler_engine/s0_init_db.py`: database initialization.
- `crawler_engine/s1_crawler.py`: crawler and package tracking core.
- `crawler_engine/s2_daily_manager.py`: daily/backfill management workflows.
- `crawler_engine/s3_etl_pipeline.py`: Excel/data normalization and ETL into Postgres.
- `crawler_engine/storage_adapter.py`: local/R2 storage adapter.
- `crawler_engine/schema_config.py` and `crawler_engine/schema_normalization_shared.py`: schema and normalization helpers.

## Temporary, Audit, And Repair Files

Do not delete, rename, or "clean up" temporary-looking files without confirming their purpose.

This repository intentionally contains files used to check, audit, or correct data issues. Some are named with prefixes such as:

- `temp_`
- `tmp_`
- `audit_`
- `repair_`

Examples include:

- `crawler_engine/temp_audit_existing_vendor_fill_risk.py`
- `crawler_engine/temp_repair_mismatch_units_from_audit.py`
- `crawler_engine/tmp_ib2500452628_analysis.txt`
- `crawler_engine/tmp_uq_dups.csv`
- `crawler_engine/audit_processed_unit_row_counts.py`
- `crawler_engine/repair_missing_local_files.py`
- `crawler_engine/repair_numeric_x10_bug.py`
- `crawler_engine/processed_unit_row_count_audit*.xlsx`

These files may encode one-off investigations, reproducible checks, data repair previews, or evidence for prior corrections. Treat them as project artifacts unless the user explicitly asks for cleanup.

## Data And Secrets Safety

- Do not print `.env` contents or secrets in chat.
- Do not commit credentials, database URLs, API keys, cookies, or tokens.
- `crawler_engine/.env` and `apps/api/.env`-style files are environment-specific.
- `DATABASE_URL` points at Postgres and may affect production-like data. Be careful with scripts that write to the database.
- Storage settings for R2/S3-like artifact storage live in environment variables used by `crawler_engine/storage_adapter.py`.

## Database Caution

Many crawler and repair scripts write to Postgres. Before running any script that might modify data:

1. Identify whether it writes, updates, deletes, or archives records.
2. Prefer dry-run, preview, audit, or read-only modes when available.
3. Confirm the active `DATABASE_URL` target if there is any risk of modifying shared data.
4. Avoid running broad repair/backfill scripts unless the user specifically requested it.

## Editing Guidance

- Follow existing structure and naming. `crawler_engine/` is intentionally not yet reorganized.
- Keep changes scoped to the requested behavior.
- Avoid unrelated refactors while fixing a bug.
- Preserve Vietnamese user-facing text unless the task asks to change it.
- Prefer existing helper functions and normalization logic over duplicating new versions.
- For frontend work, keep the static architecture unless the user asks for a framework migration.
- For backend work, keep FastAPI/asyncpg patterns already used in `apps/api/server.py`.
- For crawler work, inspect the relevant audit/repair scripts before changing ETL behavior.

## Validation Checklist

Use the narrowest useful validation for the change:

- Frontend-only: open `apps/web/index.html` or run a local static check when applicable.
- Backend API: run or import-check the FastAPI app, and test changed endpoints if feasible.
- Crawler/ETL: prefer small sample runs, dry runs, or audit scripts before broad execution.
- Load/performance routing: use `tools/load-tests/bidfinder.k6.js` and follow `tools/load-tests/README.md`.

Before finishing, report:

- What changed.
- What validation was run.
- Any validation that could not be run.
- Any database or environment assumptions.

## Git Safety

- Do not revert user changes unless explicitly asked.
- Do not use destructive commands such as `git reset --hard` or broad deletes unless the user explicitly approves.
- A dirty worktree may contain intentional user work; inspect before editing touched files.
