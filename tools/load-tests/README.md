# BIDFinder Load Test

This folder contains the k6 script for backend capacity checks.

## Install k6

```powershell
winget install k6.k6
```

## Recommended Test

Use `realistic` mode for user-capacity decisions. It includes think time, so `300` VUs is closer to 300 active users than the older tight-loop `mixed` mode.

```powershell
$env:BASE_URL="https://bidfinder-api-staging-774667987564.asia-southeast1.run.app"
$env:LOGIN_MODE="shared"
$env:PRELOGIN_VUS="false"
$env:SETUP_TIMEOUT="5m"
$env:LOGIN_TIMEOUT="120s"

$env:TEST_MODE="realistic"
$env:VUS="300"
$env:RAMP_UP="5m"
$env:DURATION="20m"
$env:RAMP_DOWN="3m"

$env:REALISTIC_BULK_RATE="0.02"
$env:REALISTIC_AUTOCOMPLETE_PREVIEW_RATE="0.2"
$env:REALISTIC_QUERY_RATE="0.7"
$env:REALISTIC_MIN_THINK_SECONDS="10"
$env:REALISTIC_MAX_THINK_SECONDS="30"
$env:REALISTIC_BULK_MIN_THINK_SECONDS="20"
$env:REALISTIC_BULK_MAX_THINK_SECONDS="60"

k6 run .\tools\load-tests\bidfinder.k6.js
```

Use Render backup by changing only:

```powershell
$env:BASE_URL="https://bidfinder.onrender.com"
```

Do not add spaces around the URL. If k6 says `invalid URL`, check:

```powershell
Write-Host "BASE_URL=[$env:BASE_URL]"
```

## Quick Endpoint Tests

```powershell
$env:TEST_MODE="query"
k6 run .\tools\load-tests\bidfinder.k6.js
```

```powershell
$env:TEST_MODE="bulk"
$env:BULK_ROWS="10"
$env:BULK_LIMIT="1000"
k6 run .\tools\load-tests\bidfinder.k6.js
```

Use old `mixed` mode only as a stress test. It is intentionally much harsher than real usage.

## Main Knobs

```text
BASE_URL
VUS
RAMP_UP
DURATION
RAMP_DOWN
TEST_MODE
LOGIN_EMAIL / LOGIN_PASSWORD
LOGIN_MODE
DB-side watch: Neon CPU, active connections, pooler connections
```

## How to read results

- `http_req_failed`: keep below 1-5%.
- `bidfinder_429s`: near zero for normal capacity tests.
- `bidfinder_5xxs`: zero or near zero.
- `bidfinder_query_ms p(95)`: target below 5s.
- `bidfinder_preview_ms p(95)`: target below 2.5s.
- `bidfinder_autocomplete_ms p(95)`: target below 1.5s.

If Neon CPU is low but latency is high, the backend host is likely the bottleneck. If Neon CPU is high, reduce concurrency, improve queries, or raise Neon CU.
