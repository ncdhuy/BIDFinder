# Refactor progress

## Phase 0 — safety and inventory

- Batch: `docs: inventory refactor baseline and artifacts`
- Scope: `docs/refactor-baseline.md`, `docs/artifact-inventory.md`, this progress log.
- Preserved behavior: all source, API routes, `server:app`, crawler `s0`–`s3`, static frontend, UI text, analytics.
- Validation: route AST inventory found 25 method/path contracts across 23 unique paths; artifact reference scan completed; `git diff --check` passed.
- Rollback: remove these three docs; no source/data rollback required.
- Status: repository gate complete. External credential rotation remains unverified because secret values/log history are outside safe repository scope.
- Protected existing work: `crawler_engine/schema_config.py`, untracked `AGENTS.md`, `docs/refactor-plan.md`, ignored `.env`, and all audit/repair/temp artifacts remain untouched.
- External blocker: credential rotation cannot be verified or performed from repository state without handling secret values. No secret value was read or printed.

## Phase 1 — characterization tests and minimal CI

- Batch: `test: add API and ETL characterization checks`.
- Scope: `.github/workflows/checks.yml`, `tests/`.
- Preserved behavior: production source unchanged; route snapshot records actual current decorators.
- Validation: pending `unittest`, Python compile, JS syntax, secret scan, and `git diff --check`.
- Rollback: remove tests, fixtures, and workflow; production source remains unchanged.
- Status: in progress.

Validation result: 9 `unittest` cases passed, Python compile passed, six frontend JS syntax checks passed, and `git diff --check` passed. Local `server:app` import is blocked by an incompatible globally installed FastAPI/Starlette pair; CI performs a clean dependency resolve. Phase gate is complete for credential-free checks.

## Phase 2 — verified low-risk cleanup

- Batch: `chore: remove verified duplicate frontend assets`.
- Scope: remove only the duplicate non-minified Chart.js include; add `crawler_engine/.env.example` with fake/local values.
- Preserved behavior: Chart.js version remains 4.4.0 through the existing minified production file; all runtime assets remain.
- Validation: exactly one `chart.umd.min.js` include remains; six JS syntax checks, 9 `unittest` cases, Python compile, and `git diff --check` passed.
- Rollback: restore the single removed `<script>` line and remove the example file.
- Status: blocked at browser gate. In-app/Chrome browser discovery returned no available browser, so chart/map/export visual smoke could not run. `Vietnam34.geojson`, 12 unreferenced images, and tracked reports are deliberately retained because runtime/owner/archive provenance is incomplete.

Phase 3 must not start until the Phase 2 browser gate is available or explicitly waived. No DB/R2/crawler write command was run.

Later phases are not started. Each batch records scope, preserved behavior, validation, rollback, and gate result before the next batch.
