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

Phase 2 MSC ingestion is isolated under `crawler_engine/msc/`. It uses only
anonymous public search, local SQLite operational checkpoints, and optional
canonical JSONL validation output. The legacy crawler remains unchanged.

```text
crawler_engine/msc/
  config.py          Safe request, retry, pacing, and partition defaults
  models.py          Contracts, intervals, metrics, and checkpoint value objects
  contracts.py       Seven frozen verified source definitions
  client.py          POST /search_prc transport and request builder
  partitioning.py    Adaptive one-second-overlap time partitioning
  validation.py      Envelope, pagination, UUID, drift, and count gates
  normalize.py       Pure seven-source to three-group normalization
  checkpoint.py      Local SQLite source/date state
  sink.py            Sink protocol, in-memory sink, and JSONL sink
  engine.py          Sequential parent-partition orchestration
  cli.py             Explicit validate/crawl operator commands
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
uvicorn server:app --reload --host 127.0.0.1 --port 8001
```

Open frontend locally:

```text
apps/web/index.html
```

Run k6:

```powershell
k6 run .\tools\load-tests\bidfinder.k6.js
```

Phase 3A adds the isolated Typesense data plane under `crawler_engine/msc/`:

```text
crawler_engine/msc/
  typesense_schema.py   Frozen V1 collection schemas and search allow-lists
  typesense_client.py   Stdlib Typesense HTTP client and generation lifecycle
  sink.py               TypesenseSink with batched import/upsert semantics
  checkpoint.py         Sink-target-aware SQLite operational state

infra/typesense/compose.yml  Disposable Typesense 30.2 development service
docs/typesense-data-plane-runbook.md
```

The crawler writes only to explicit versioned physical collections. Stable
aliases are managed by the Typesense CLI and are not used by staging writes.
FastAPI and `apps/web/` remain unchanged in Phase 3A.
