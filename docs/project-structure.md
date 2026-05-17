# Project Structure

This repository is organized by responsibility. `crawler_engine` intentionally stays at the root for now.

```text
apps/
  api/              FastAPI backend, Dockerfile, Render Procfile, Cloud Run deploy script
  web/              Static frontend assets and browser JavaScript

tools/
  load-tests/       k6 load-test scripts and load-test notes

docs/               Operations and handover documentation
crawler_engine/     Existing crawler/data pipeline, not reorganized yet
tmp_storage/        Local temporary storage
```

## Common Commands

Deploy backend to Cloud Run:

```powershell
.\apps\api\deploy-cloud-run.ps1 `
  -ServiceName bidfinder-api-staging `
  -Region asia-southeast1 `
  -MaxInstances 4 `
  -Concurrency 10 `
  -FrontendUrl "https://bidfinder.vn"
```

Run backend locally:

```powershell
cd apps\api
uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

Open frontend locally:

```text
apps/web/index.html
```

Run k6:

```powershell
k6 run .\tools\load-tests\bidfinder.k6.js
```
