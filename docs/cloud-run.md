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

Reference values:

```powershell
# ENV=production
# ANONYMOUS_ACCESS_LEVEL=full
# ANONYMOUS_FULL_QUERY_DAILY_LIMIT=5
# APP_TIMEZONE=Asia/Ho_Chi_Minh
# DB_POOL_MAX_SIZE=4
# TRUST_PROXY_HEADERS=true
# FRONTEND_URL=https://bidfinder.vn
# APP_FRONTEND_URL=https://bidfinder.vn
# AUTH_PASSWORD_RESET_URL_BASE=https://bidfinder.vn
# ALLOWED_ORIGINS=https://bidfinder.vn,https://www.bidfinder.vn,https://bidfinder.netlify.app,http://localhost:3000,http://127.0.0.1:3000
# QUERY_RATE_LIMIT_PER_MINUTE=2000
# AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE=3000
# PREVIEW_RATE_LIMIT_PER_MINUTE=3000
# FILTER_CONFIG_RATE_LIMIT_PER_MINUTE=1000
# AUTH_RATE_LIMIT_PER_MINUTE=500
# DEFAULT_QUERY_LIMIT=200
# MAX_QUERY_LIMIT=1000
# FULL_SEARCH_DAILY_LIMIT=3
# STANDARD_QUERY_EXACT_COUNT_ENABLED=false
# PREVIEW_CACHE_TTL_SECONDS=15
# AUTOCOMPLETE_CACHE_TTL_SECONDS=20
```

Render-to-Cloud-Run env mapping:

```text
Set as Cloud Run secrets:
  DATABASE_URL
  GOOGLE_CLIENT_ID
  RESEND_API_KEY
  RESEND_FROM_EMAIL
  AUTH_SMTP_USERNAME
  AUTH_SMTP_PASSWORD
  AUTH_SMTP_FROM_EMAIL

Set as normal env vars:
  ENV
  ANONYMOUS_ACCESS_LEVEL
  ANONYMOUS_FULL_QUERY_DAILY_LIMIT
  APP_TIMEZONE
  FRONTEND_URL
  APP_FRONTEND_URL
  AUTH_PASSWORD_RESET_URL_BASE
  AUTH_SESSION_TOUCH_INTERVAL_SECONDS
  AUTH_SMTP_FROM_NAME
  AUTH_SMTP_HOST
  AUTH_SMTP_PORT
  AUTH_SMTP_USE_SSL
  AUTH_SMTP_USE_TLS
  RESEND_FROM_NAME
  TRUST_PROXY_HEADERS
  DB_POOL_MAX_SIZE
  DEFAULT_QUERY_LIMIT
  MAX_QUERY_LIMIT
  FULL_SEARCH_DAILY_LIMIT
  STANDARD_QUERY_EXACT_COUNT_ENABLED
  PREVIEW_CACHE_TTL_SECONDS
  AUTOCOMPLETE_CACHE_TTL_SECONDS

```

Do not copy Render's `DB_POOL_MAX_SIZE=16` to Cloud Run. Cloud Run scales by instances, so use `DB_POOL_MAX_SIZE=4` as the baseline.

## Auth And Email Secrets

Use Secret Manager for sensitive auth/email values. Do not put real values in docs or Git.

Create a secret:

```powershell
$env:SECRET_VALUE="paste-real-value-here"
$env:SECRET_VALUE | gcloud secrets create SECRET_NAME --data-file=-
Remove-Item Env:SECRET_VALUE
```

Update an existing secret:

```powershell
$env:SECRET_VALUE="paste-real-value-here"
$env:SECRET_VALUE | gcloud secrets versions add SECRET_NAME --data-file=-
Remove-Item Env:SECRET_VALUE
```

Recommended secret names:

```text
bidfinder-google-client-id
bidfinder-resend-api-key
bidfinder-resend-from-email
bidfinder-smtp-username
bidfinder-smtp-password
bidfinder-smtp-from-email
```

Create Google login secret:

```powershell
$env:SECRET_VALUE="your-google-client-id.apps.googleusercontent.com"
$env:SECRET_VALUE | gcloud secrets create bidfinder-google-client-id --data-file=-
Remove-Item Env:SECRET_VALUE
```

Grant Cloud Run permission to read a secret:

```powershell
gcloud secrets add-iam-policy-binding SECRET_NAME `
  --member="serviceAccount:774667987564-compute@developer.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

For Google login:

```powershell
gcloud secrets add-iam-policy-binding bidfinder-google-client-id `
  --member="serviceAccount:774667987564-compute@developer.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

Create Resend email secrets:

```powershell
$env:SECRET_VALUE="re_xxxxxxxxxxxxxxxxx"
$env:SECRET_VALUE | gcloud secrets create bidfinder-resend-api-key --data-file=-
Remove-Item Env:SECRET_VALUE

$env:SECRET_VALUE="noreply@bidfinder.vn"
$env:SECRET_VALUE | gcloud secrets create bidfinder-resend-from-email --data-file=-
Remove-Item Env:SECRET_VALUE
```

Create Gmail SMTP secrets only if using Gmail SMTP instead of Resend:

```powershell
$env:SECRET_VALUE="bidfinder.vn@gmail.com"
$env:SECRET_VALUE | gcloud secrets create bidfinder-smtp-username --data-file=-
Remove-Item Env:SECRET_VALUE

$env:SECRET_VALUE="your-gmail-app-password"
$env:SECRET_VALUE | gcloud secrets create bidfinder-smtp-password --data-file=-
Remove-Item Env:SECRET_VALUE

$env:SECRET_VALUE="bidfinder.vn@gmail.com"
$env:SECRET_VALUE | gcloud secrets create bidfinder-smtp-from-email --data-file=-
Remove-Item Env:SECRET_VALUE
```

Attach Google login and Resend to Cloud Run:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-secrets "GOOGLE_CLIENT_ID=bidfinder-google-client-id:latest,RESEND_API_KEY=bidfinder-resend-api-key:latest,RESEND_FROM_EMAIL=bidfinder-resend-from-email:latest"
```

Set non-secret auth/email env vars:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-env-vars "APP_FRONTEND_URL=https://bidfinder.vn, AUTH_PASSWORD_RESET_URL_BASE=https://bidfinder.vn, RESEND_FROM_NAME=BIDFinder, 
```

Attach Gmail SMTP secrets only if using SMTP:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-secrets "AUTH_SMTP_USERNAME=bidfinder-smtp-username:latest,AUTH_SMTP_PASSWORD=bidfinder-smtp-password:latest,AUTH_SMTP_FROM_EMAIL=bidfinder-smtp-from-email:latest"
```

Use `--update-secrets` when adding or changing individual secrets on an existing service. Use `--set-secrets` only when intentionally replacing the full secret mapping.

Set Gmail SMTP non-secret env vars:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-env-vars "AUTH_SMTP_HOST=smtp.gmail.com, AUTH_SMTP_PORT=587, AUTH_SMTP_FROM_NAME=BIDFinder, AUTH_SMTP_USE_TLS=true, AUTH_SMTP_USE_SSL=false
```

Set non-secret env vars:

```
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-env-vars "FEEDBACK_READ_RATE_LIMIT_PER_MINUTE=60,FEEDBACK_RATE_LIMIT_PER_MINUTE=10,ADMIN_EMAILS=admin@bidfinder.vn,DB_POOL_MAX_SIZE=2"
```

Deploy script supports auth/email secrets as optional parameters:

```powershell
.\apps\api\deploy-cloud-run.ps1 `
  -ServiceName bidfinder-api-staging `
  -Region asia-southeast1 `
  -MaxInstances 4 `
  -Concurrency 10 `
  -FrontendUrl "https://bidfinder.vn" `
  -GoogleClientIdSecretName bidfinder-google-client-id `
  -ResendApiKeySecretName bidfinder-resend-api-key `
  -ResendFromEmailSecretName bidfinder-resend-from-email
```

Add several env vars in one command. Comma-separated values are OK for add/update when values do not contain commas:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-env-vars QUERY_RATE_LIMIT_PER_MINUTE=2000
```

If a value itself contains commas, use a custom delimiter:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-env-vars "^|^ALLOWED_ORIGINS=https://bidfinder.vn,https://www.bidfinder.vn,https://bidfinder.netlify.app,http://localhost:3000,http://127.0.0.1:3000|FRONTEND_URL=https://bidfinder.vn"
```

For repair work, update one env var per command:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-env-vars VARIABLE_NAME=VALUE
```

Remove one env var per command:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --remove-env-vars VARIABLE_NAME
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
