# BIDFinder Load Tests

k6 tests for backend capacity and heavy task checks.

## Install

```powershell
winget install k6.k6
```

## Common Setup

Set these once per terminal session. Use a real test account; do not commit credentials.

```powershell
$env:BASE_URL="https://bidfinder-api-staging-774667987564.asia-southeast1.run.app"
$env:LOGIN_EMAIL="your-login-email"
$env:LOGIN_PASSWORD="your-login-password"
$env:LOGIN_MODE="shared"
$env:PRELOGIN_VUS="false"
$env:SETUP_TIMEOUT="5m"
$env:LOGIN_TIMEOUT="120s"
```

Use Render backup only by changing:

```powershell
$env:BASE_URL="https://bidfinder.onrender.com"
```

## Recommended Capacity

Use this for normal 300-user capacity checks.

```powershell
$env:TEST_MODE="realistic"
$env:VUS="300"
$env:RAMP_UP="2m"
$env:DURATION="5m"
$env:RAMP_DOWN="2m"

$env:REALISTIC_BULK_RATE="0.02"
$env:REALISTIC_FORUM_RATE="0"
$env:REALISTIC_AUTOCOMPLETE_PREVIEW_RATE="0.2"
$env:REALISTIC_QUERY_RATE="0.7"
$env:REALISTIC_MIN_THINK_SECONDS="10"
$env:REALISTIC_MAX_THINK_SECONDS="30"
$env:REALISTIC_BULK_MIN_THINK_SECONDS="20"
$env:REALISTIC_BULK_MAX_THINK_SECONDS="60"

k6 run .\tools\load-tests\bidfinder.k6.js
```

## Heavy Realistic

Use this after the recommended test passes. It mixes normal search, forum reads, and user-like Excel bulk uploads for both medicine and goods. Goods upload is intentionally heavier because product diversity partitions by the merged goods search blob.

```powershell
$env:TEST_MODE="realistic"
$env:VUS="300"
$env:RAMP_UP="2m"
$env:DURATION="5m"
$env:RAMP_DOWN="2m"

$env:QUERY_LIMIT="300"
$env:BULK_PROFILE="upload-mix"
$env:BULK_ROWS="200"
$env:BULK_LIMIT="1000"
$env:BULK_DIVERSITY_MODE="product"
$env:BULK_PRODUCT_LIMIT="5"
$env:FORUM_COMMENTS_LIMIT="50"

$env:REALISTIC_BULK_RATE="0.01"
$env:REALISTIC_FORUM_RATE="0.1"
$env:REALISTIC_AUTOCOMPLETE_PREVIEW_RATE="0.2"
$env:REALISTIC_QUERY_RATE="0.6"
$env:REALISTIC_MIN_THINK_SECONDS="8"
$env:REALISTIC_MAX_THINK_SECONDS="24"
$env:REALISTIC_BULK_MIN_THINK_SECONDS="30"
$env:REALISTIC_BULK_MAX_THINK_SECONDS="90"

k6 run .\tools\load-tests\bidfinder.k6.js
```

## Focused Checks

Medicine upload:

```powershell
$env:TEST_MODE="bulk"
$env:VUS="5"
$env:RAMP_UP="1m"
$env:DURATION="5m"
$env:RAMP_DOWN="1m"
$env:BULK_PROFILE="medicine-upload"
$env:BULK_ROWS="124"
$env:BULK_LIMIT="1000"
$env:BULK_DIVERSITY_MODE="product"
$env:BULK_PRODUCT_LIMIT="5"
k6 run .\tools\load-tests\bidfinder.k6.js
```

Goods upload:

```powershell
$env:TEST_MODE="bulk"
$env:VUS="3"
$env:RAMP_UP="1m"
$env:DURATION="5m"
$env:RAMP_DOWN="1m"
$env:BULK_PROFILE="goods-upload"
$env:BULK_ROWS="124"
$env:BULK_LIMIT="1000"
$env:BULK_DIVERSITY_MODE="product"
$env:BULK_PRODUCT_LIMIT="5"
k6 run .\tools\load-tests\bidfinder.k6.js
```

Forum:

```powershell
$env:TEST_MODE="forum"
$env:VUS="100"
$env:RAMP_UP="1m"
$env:DURATION="5m"
$env:RAMP_DOWN="1m"
$env:FORUM_COMMENTS_LIMIT="50"
k6 run .\tools\load-tests\bidfinder.k6.js
```

## Modes And Profiles

```text
TEST_MODE:
  realistic   user-like mixed workload with think time
  query       query endpoint only
  bulk        bulk-query endpoint only
  forum       forum topic list/detail only
  mixed       old tight-loop stress mode; harsher than real usage

BULK_PROFILE:
  synthetic        older random medicine/goods cases
  medicine-upload  user-like medicine Excel upload
  goods-upload     user-like goods Excel upload
  upload-mix       alternates medicine-upload and goods-upload
```

## Read Results

Normal targets:

```text
http_req_failed                 below 1-5%
bidfinder_429s                 near zero
bidfinder_5xxs                 zero or near zero
bidfinder_query_ms p95         below 5s
bidfinder_preview_ms p95       below 2.5s
bidfinder_autocomplete_ms p95  below 1.5s
bidfinder_forum_* p95          below 2.5s
```

Bulk targets depend on workload size. For heavy upload tests, `bulk p95` can be much higher than normal endpoint latency; use it to find the practical limit for concurrent bulk uploads.

Watch Neon CPU/CU, active connections, pooler client connections, Cloud Run instance count, Cloud Run CPU/memory, and request latency during every run.
