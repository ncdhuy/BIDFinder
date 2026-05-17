# Cloud Run Backend

Production-lite setup for the FastAPI backend. Render remains available as backup through `apps/api/Procfile`.

## Baseline

```text
Cloud Run:
  CPU: 1
  Memory: 512Mi or 1Gi
  Concurrency: 10
  Min instances: 0
  Max instances: 4
  Workers: 1
  DB_POOL_MAX_SIZE: 4

Neon:
  Min CU: 1
  Max CU: 4
  Connection string: pooled
```

Connection budget:

```text
max_instances x workers x DB_POOL_MAX_SIZE
4 x 1 x 4 = 16 app-side DB connections
```

Use one Uvicorn worker on Cloud Run because Cloud Run scales by creating more instances. More workers inside each container multiply DB pools and make connection usage harder to control.

## First Setup

Enable the required Google Cloud services:

```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

Create the Neon URL secret. Use the pooled Neon connection string.

```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST/DB?sslmode=require"
$env:DATABASE_URL | gcloud secrets create bidfinder-neon-database-url --data-file=-
```

Update an existing secret:

```powershell
$env:DATABASE_URL | gcloud secrets versions add bidfinder-neon-database-url --data-file=-
```

## Deploy

From the repository root:

```powershell
.\apps\api\deploy-cloud-run.ps1 `
  -ServiceName bidfinder-api-staging `
  -Region asia-southeast1 `
  -MaxInstances 4 `
  -Concurrency 10 `
  -FrontendUrl "https://bidfinder.vn"
```

The backend container uses:

```text
uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
```

## Env Vars

Keep secrets in Secret Manager. Keep tuning values as normal env vars.

```text
ENV=production
DB_POOL_MAX_SIZE=4
TRUST_PROXY_HEADERS=true
FRONTEND_URL=https://bidfinder.vn
ALLOWED_ORIGINS=https://bidfinder.vn,https://www.bidfinder.vn,https://bidfinder.netlify.app
QUERY_RATE_LIMIT_PER_MINUTE=2000
AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE=3000
PREVIEW_RATE_LIMIT_PER_MINUTE=3000
FILTER_CONFIG_RATE_LIMIT_PER_MINUTE=1000
AUTH_RATE_LIMIT_PER_MINUTE=500
```

Update runtime values:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-env-vars DB_POOL_MAX_SIZE=4,QUERY_RATE_LIMIT_PER_MINUTE=5000,AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE=5000,PREVIEW_RATE_LIMIT_PER_MINUTE=5000
```

Inspect current env:

```powershell
gcloud run services describe bidfinder-api-staging `
  --region asia-southeast1 `
  --format="yaml(spec.template.spec.containers[0].env)"
```

## Tuning Rules

- Use `min-instances=1` only if cold starts hurt real users.
- Raise capacity in this order: `max-instances 2 -> 4 -> 6`, then `concurrency 10 -> 15 -> 20`.
- Increase `DB_POOL_MAX_SIZE` only if pool wait is visible and Neon CPU still has headroom.
- Keep Render backup separate; do not tune Render numbers based on Cloud Run behavior.

For Render, connection budget is:

```text
instances x uvicorn_workers x DB_POOL_MAX_SIZE
```

## Checks

After deploy:

```powershell
curl https://SERVICE_URL/health
curl https://SERVICE_URL/ready
```

Expected:

```text
/health -> {"status":"ok"}
/ready  -> {"status":"ready"}
```
