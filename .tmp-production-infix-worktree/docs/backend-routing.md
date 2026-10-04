# Backend Routing

BIDFinder uses Cloud Run as primary and Render as backup.

## URLs

```text
Primary Cloud Run:
  https://bidfinder-api-staging-774667987564.asia-southeast1.run.app

Backup Render:
  https://bidfinder.onrender.com
```

## Frontend

The frontend API URL is centralized in:

```text
apps/web/config.js
```

Normal flow:

```text
Frontend -> Cloud Run -> Neon Postgres
```

To switch frontend to Render, edit `apps/web/config.js`:

```text
CLOUD_RUN_API_BASE_URL = 'https://bidfinder.onrender.com'
```

To switch back to Cloud Run:

```text
CLOUD_RUN_API_BASE_URL = 'https://bidfinder-api-staging-774667987564.asia-southeast1.run.app'
```

## Release boundary and frontend caching

At the 2026-09-14 AI assistant checkpoint, Netlify frontend production is
expected to serve commit `ef4c9a3e2e21bd8bf6e2f3572cce2778afa1e309`.
The expected current backend production commit remains
`18c4d4df6da37c3b642ebf2509cf6f5b61a70d57`, so the frontend may temporarily
receive `404` for `GET /api/ai/usage` until backend cutover.

Netlify branch auto-deploy is enabled for `refactor-msc-typesense-v1`.
Pushing that branch may automatically publish frontend changes; “do not
deploy” means do not run another explicit Netlify deployment command. The
frontend uses revalidating headers for `index.html` and mutable static assets,
so a normal reload picks up a new release without requiring `Ctrl+F5`.

## k6

Override `BASE_URL` when comparing backends.

Cloud Run:

```powershell
$env:BASE_URL="https://bidfinder-api-staging-774667987564.asia-southeast1.run.app"
k6 run .\tools\load-tests\bidfinder.k6.js
```

Render:

```powershell
$env:BASE_URL="https://bidfinder.onrender.com"
k6 run .\tools\load-tests\bidfinder.k6.js
```

Do not include spaces inside `BASE_URL`. Check with:

```powershell
Write-Host "BASE_URL=[$env:BASE_URL]"
```
