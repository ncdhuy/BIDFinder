# BIDFinder

## Runbook

BIDFinder currently runs with Cloud Run as the main backend and Render as a backup.

- Project structure: [docs/project-structure.md](docs/project-structure.md)
- Deploy and tune backend: [docs/cloud-run.md](docs/cloud-run.md)
- Switch backend URL: [docs/backend-routing.md](docs/backend-routing.md)
- Run load tests: [tools/load-tests/README.md](tools/load-tests/README.md)

```text
Primary: Cloud Run -> Neon Postgres
Backup: Render -> Neon Postgres
```

## Local frontend verification

Run the current-checkout backend in a separate terminal first:

```powershell
cd apps\api
rtk python -m uvicorn server:app --reload --host 127.0.0.1 --port 8002
```

Serve the current checkout's `apps/web` directory with:

```powershell
rtk python tools/serve_web.py
```

Open `http://127.0.0.1:4173/`. The helper resolves `apps/web` from its own
location and sends no-cache headers, so local verification cannot silently
serve a different repository directory or an immutable release copy.
