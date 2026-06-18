# Cloud Run Backend

FastAPI backend deployment for BIDFinder.

## Baseline

```text
Cloud Run:
  CPU: 1
  Memory: 1Gi
  Concurrency: 10
  Min instances: 0
  Max instances: 6
  Workers: 1
  DB_POOL_MAX_SIZE: 4

Neon:
  Connection string: pooled
  Suggested max CU for heavy bulk tests: 2-4
```

Connection budget:

```text
max_instances x workers x DB_POOL_MAX_SIZE
6 x 1 x 4 = 24 app-side DB connections
```

Use one Uvicorn worker. Cloud Run scales by instances; more workers inside one container multiply DB pools and make connection usage harder to reason about.

## First Setup

Enable Google Cloud services once:

```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

Create or update secrets in Secret Manager. Do not put secret values in Git.

```powershell
$env:SECRET_VALUE="postgresql://USER:PASSWORD@HOST/DB?sslmode=require"
$env:SECRET_VALUE | gcloud secrets create bidfinder-neon-database-url --data-file=-
Remove-Item Env:SECRET_VALUE
```

For an existing secret:

```powershell
$env:SECRET_VALUE="new-secret-value"
$env:SECRET_VALUE | gcloud secrets versions add SECRET_NAME --data-file=-
Remove-Item Env:SECRET_VALUE
```

Recommended secret names:

```text
bidfinder-neon-database-url
bidfinder-google-client-id
bidfinder-resend-api-key
bidfinder-resend-from-email
```

Grant Cloud Run access to each secret once:

```powershell
gcloud secrets add-iam-policy-binding SECRET_NAME `
  --member="serviceAccount:774667987564-compute@developer.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

## Deploy

Use the deploy script when you want to build and deploy the backend from the current repo code. This creates a new Cloud Run revision and updates the env vars/secrets passed by the script.

Recommended staging deploy:

```powershell
.\apps\api\deploy-cloud-run.ps1 `
  -ServiceName bidfinder-api-staging `
  -Region asia-southeast1 `
  -Memory "1Gi" `
  -Cpu "1" `
  -MaxInstances 6 `
  -Concurrency 10 `
  -DbPoolMaxSize 4 `
  -FrontendUrl "https://bidfinder.vn" `
  -GoogleClientIdSecretName bidfinder-google-client-id `
  -ResendApiKeySecretName bidfinder-resend-api-key `
  -ResendFromEmailSecretName bidfinder-resend-from-email
```

For load testing, temporarily raise read/query rate limits in the same deploy:

```powershell
.\apps\api\deploy-cloud-run.ps1 `
  -ServiceName bidfinder-api-staging `
  -Region asia-southeast1 `
  -Memory "1Gi" `
  -Cpu "1" `
  -MaxInstances 6 `
  -Concurrency 10 `
  -DbPoolMaxSize 4 `
  -FrontendUrl "https://bidfinder.vn" `
  -QueryRateLimitPerMinute 10000 `
  -AutocompleteRateLimitPerMinute 10000 `
  -PreviewRateLimitPerMinute 10000 `
  -FeedbackReadRateLimitPerMinute 10000 `
  -GoogleClientIdSecretName bidfinder-google-client-id `
  -ResendApiKeySecretName bidfinder-resend-api-key `
  -ResendFromEmailSecretName bidfinder-resend-from-email
```

The script uses `--update-secrets`, so existing secret mappings are preserved when optional secret parameters are omitted. Keep using `--update-secrets`; only use `--set-secrets` when intentionally replacing all secret mappings.

## Patch Existing Service

Use `gcloud run services update` when you only want to patch an existing deployed service without rebuilding code.

Good cases for `gcloud run services update`:

```text
- Attach or restore a secret mapping.
- Change one or a few env vars quickly.
- Remove stale env vars.
- Hotfix config after a deploy.
```

Restore Google login and Resend secret mappings:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-secrets "GOOGLE_CLIENT_ID=bidfinder-google-client-id:latest,RESEND_API_KEY=bidfinder-resend-api-key:latest,RESEND_FROM_EMAIL=bidfinder-resend-from-email:latest"
```

Patch several env vars at once:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-env-vars "QUERY_RATE_LIMIT_PER_MINUTE=10000,AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE=10000,PREVIEW_RATE_LIMIT_PER_MINUTE=10000,FEEDBACK_READ_RATE_LIMIT_PER_MINUTE=10000"
```

If a value contains commas, use a custom delimiter:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --update-env-vars "^|^ALLOWED_ORIGINS=https://bidfinder.vn,https://www.bidfinder.vn,https://bidfinder.netlify.app,http://localhost:3000,http://127.0.0.1:3000|FRONTEND_URL=https://bidfinder.vn"
```

For Resend-only email, remove stale SMTP env vars:

```powershell
gcloud run services update bidfinder-api-staging `
  --region asia-southeast1 `
  --remove-env-vars "AUTH_SMTP_HOST,AUTH_SMTP_PORT,AUTH_SMTP_FROM_NAME,AUTH_SMTP_USE_TLS,AUTH_SMTP_USE_SSL,AUTH_SMTP_USERNAME,AUTH_SMTP_PASSWORD,AUTH_SMTP_FROM_EMAIL"
```

## Which Command To Use?

Use `deploy-cloud-run.ps1` when:

```text
- You changed backend code.
- You want one clean deploy with source build, capacity, env vars, and secret mappings together.
- You are changing Cloud Run runtime settings such as memory, CPU, concurrency, max instances, timeout, or DB pool defaults.
- You want the repo script to be the source of truth for normal deploys.
```

Use `gcloud run services update --update-env-vars` when:

```text
- You only need to change config on the already deployed revision.
- You do not need to rebuild code.
- You are testing a temporary value, such as higher load-test rate limits.
```

Use `gcloud run services update --update-secrets` when:

```text
- The secret already exists in Secret Manager and you only need Cloud Run to expose it as an env var.
- A secret mapping was accidentally removed and needs to be restored.
```

Use `gcloud secrets versions add` when:

```text
- The secret value itself changed, such as a new Resend API key or database URL.
```

## Inspect

Inspect env and secret mappings:

```powershell
gcloud run services describe bidfinder-api-staging `
  --region asia-southeast1 `
  --format="yaml(spec.template.metadata.annotations)"
```

```powershell
gcloud run services describe bidfinder-api-staging `
  --region asia-southeast1 `
  --format="yaml(spec.template.spec.containers[0].env)"
```

Inspect Cloud Run capacity:

```powershell
gcloud run services describe bidfinder-api-staging `
  --region asia-southeast1 `
  --format="yaml(spec.template.spec.containers[0].resources,spec.template.spec.containerConcurrency,spec.template.metadata.annotations)"
```

## Checks

After deploy:

```powershell
curl https://SERVICE_URL/health
curl https://SERVICE_URL/ready
curl https://SERVICE_URL/api/auth/config
```

Expected:

```text
/health -> {"status":"ok"}
/ready  -> {"status":"ready"}
```

## Tuning Rules

- Keep `DB_POOL_MAX_SIZE=4` unless Neon CPU is low and app-side pool wait is visible.
- Raise Cloud Run capacity in this order: `max-instances 2 -> 4 -> 6`, then `concurrency 10 -> 15 -> 20`.
- If Neon active CU keeps reaching max, raise Neon max CU or reduce heavy bulk concurrency.
- Bulk upload latency is usually a database/query-shape problem, not a forum or normal query problem.
- Keep Render backup separate; do not tune Render numbers based on Cloud Run behavior.

## Resource Strategy

Optimize for weekday public-sector usage: mostly Monday-Friday, 07:00-17:30 Vietnam time. Keep the app cheap during low traffic, but avoid making first-time users wait during office hours.

### Phase 1: Community Beta

Use this while the app has roughly 10-20 total users and low daily concurrency.

```text
Cloud Run:
  Min instances: 0
  Max instances: 2
  CPU: 1
  Memory: 512Mi or 1Gi
  Concurrency: 10
  DB_POOL_MAX_SIZE: 2-4

Neon:
  Min CU: 0.25-0.5
  Max CU: 1-2
```

Goals:

```text
- Keep cost very low.
- Accept occasional cold start.
- Run light load tests before public announcements.
- Watch query p95, 429s, 5xxs, Neon active CU, and pooler client connections.
```

### Phase 2: Early Adoption

Use this when there are 100-300 daily active users, with real office-hour traffic.

```text
Cloud Run:
  Min instances: 0 normally
  Optional min instances: 1 during office hours only, if cold starts hurt retention
  Max instances: 4-6
  CPU: 1
  Memory: 1Gi
  Concurrency: 10
  DB_POOL_MAX_SIZE: 4

Neon:
  Min CU: 0.5-1
  Max CU: 2-4
```

Goals:

```text
- Keep normal search p95 below 1-2s when warm.
- Keep autocomplete/preview p95 below 1s.
- Keep 5xx near zero.
- Treat bulk upload as a slower workflow, not as an instant endpoint.
```

Recommended office-hour posture:

```text
07:00-17:30:
  Prefer app responsiveness.
  Avoid heavy ETL.
  Allow small crawler tasks only if they do not compete with user queries.

17:30-23:00:
  Run crawler and ETL batches.
  Keep Cloud Run API max instances available for remaining users.
  Raise Neon max CU temporarily if ETL shares the same database.

23:00-06:30:
  Prefer maintenance, vacuum/analyze, materialized summaries, and heavier ETL.
```

### Phase 3: Public Scale

Use this when targeting 1000-3000 registered users with 100-300 active users per busy day.

```text
Cloud Run API:
  Min instances: 1 during office hours
  Max instances: 6-10
  CPU: 1-2
  Memory: 1Gi
  Concurrency: 10-20
  DB_POOL_MAX_SIZE: 4

Neon:
  Min CU: 1 during office hours
  Max CU: 4-8, depending on bulk and ETL pressure
```

At this stage, separate interactive traffic from heavy background work:

```text
API service:
  Handles login, query, autocomplete, preview, forum, and light bulk.

Worker or scheduled job:
  Handles crawler, ETL, large imports, reindexing, and expensive refresh tasks.
```

Do not let crawler/ETL consume the same runtime budget as user requests during office hours. If ETL must run while users are active, throttle it and keep database concurrency low.

### Bulk Upload Policy

Bulk upload is the main latency and database-cost risk.

```text
Short term:
  Keep product limit at 3-5.
  Keep realistic bulk rate around 0.5-1% in capacity tests.
  Document that 100-200 row uploads can take 10-45s.

Medium term:
  Add an app-side semaphore for bulk-query concurrency.
  Return a friendly "busy, try again shortly" message instead of letting bulk saturate DB.

Long term:
  Move large bulk uploads to async jobs.
  Store job status and let users download results when ready.
```

### Scaling Signals

Increase Cloud Run first when:

```text
- Cloud Run CPU or memory is high.
- Requests queue or return 429 while Neon active CU is not maxed.
- Instance count reaches max during office hours.
```

Increase Neon max CU when:

```text
- Neon active CU repeatedly reaches max.
- Query/bulk latency rises while Cloud Run still has headroom.
- ETL and user traffic overlap.
```

Optimize queries before buying more capacity when:

```text
- One endpoint dominates p95/p99 latency.
- Bulk upload p95 is high but normal query/autocomplete/forum are healthy.
- Pooler connections are low but active CU is high.
```
