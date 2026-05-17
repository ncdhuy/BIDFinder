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
