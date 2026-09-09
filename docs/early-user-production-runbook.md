# BIDFinder early-user production runbook

This is the temporary single-machine deployment. The application and
ingestion code remain Linux-portable; only the wrapper commands below assume
WSL2 with systemd user services.

## One-time install

From WSL:

```bash
cd /mnt/d/startup/muasamcong/BIDFinder
bash infra/runtime/bidfinder-install.sh install
```

The installer creates a user-owned Python environment and systemd units. It
does not create or commit secrets. Typesense configuration must already exist
at `~/.config/bidfinder/typesense.env`, mode `600`, with the local key and
loopback settings. If the installer cannot enable lingering, run:

```bash
sudo loginctl enable-linger "$USER"
```

## Start, stop, restart, status

```bash
bash infra/runtime/bidfinder-install.sh start
bash infra/runtime/bidfinder-install.sh stop
bash infra/runtime/bidfinder-install.sh restart
bash infra/runtime/bidfinder-install.sh status
```

`status` reports the two service states, `/ready`, serving generation,
coverage, incremental result, RAM/swap/disk, and timers. `/health` is only a
liveness check; `/ready` is the user-functionality check. Services run without
an interactive terminal and are owned by systemd. Both stop paths use SIGTERM
and bounded graceful waits; no SIGKILL fallback is configured.

## Daily ingestion and freshness

The installed timer runs at **04:00 Asia/Ho_Chi_Minh** every day, outside
normal Vietnam business hours. It processes only fully closed Vietnam days,
uses the active `serving_v1_20260901` generation, applies the three-day
lookback/revalidation policy, and holds:

```text
~/.local/share/bidfinder/runtime/locks/serving-maintenance.lock
```

If another run owns the lock, the new invocation exits safely with
`already running`. A manual equivalent is:

```bash
bash infra/runtime/bidfinder-install.sh catch-up
```

The compact report is:

```text
~/.local/share/bidfinder/typesense/reports/incremental-status.json
```

It includes run start/end/result, closed-day window, changed partitions,
accepted records, unresolved errors, coverage-through, and next expected
date. A failed source partition is not checkpointed as complete; the next run
resumes from the checkpoint rather than restarting history.

## Recovery snapshots

The installed timer creates one coherent bundle every Sunday at **05:30
Asia/Ho_Chi_Minh**. A bundle contains a Typesense snapshot plus checkpoint,
UUID provenance, serving report, and a validated manifest. Snapshot staging is
unique per run. Retention is three validated bundles; pruning runs only after
a new bundle is published, so the newest known-good bundle is retained.

Run one manually when needed:

```bash
bash infra/runtime/bidfinder-install.sh snapshot
```

Bundles are under:

```text
~/.local/share/bidfinder/typesense/recovery/bundle-*
```

Restore a validated bundle with the prior live data retained for rollback:

```bash
bash infra/runtime/bidfinder-install.sh restore \
  ~/.local/share/bidfinder/typesense/recovery/bundle-YYYYMMDDTHHMMSSZ-id
```

The restore activates only the existing serving generation. It does not create
a new generation or activate the historical generation.

## Fallback and return to Typesense

Fallback is an infrastructure-only degraded path for the legacy Postgres
subset. It is not a full-corpus substitute:

```bash
bash infra/runtime/bidfinder-install.sh fallback
bash infra/runtime/bidfinder-install.sh status
bash infra/runtime/bidfinder-install.sh typesense
```

The mode is stored outside Git in
`~/.config/bidfinder/backend.env`. The normal value is:

```text
BIDFINDER_PROCUREMENT_BACKEND=typesense
BIDFINDER_PROCUREMENT_FALLBACK_ENABLED=true
```

## Logs and common failures

```bash
bash infra/runtime/bidfinder-install.sh logs
journalctl --user-unit=bidfinder-api.service -f
journalctl --user-unit=bidfinder-typesense.service -f
```

Service output is in the user journal. The daily 03:30 Asia/Ho_Chi_Minh
timer vacuums user journals to approximately 250 MB and 14 days. Query/debug
logging is disabled by default; never paste `.env` or Typesense configuration
contents into a ticket.

If `/ready` is degraded immediately after a restart, Typesense may still be
loading the 10M-document generation. Wait for its health to become ready; do
not recreate data. If an incremental run fails, inspect its compact report and
the exact journal error, correct the external cause, and run `catch-up` again.
If disk free space falls below 25%, snapshot work warns; below 15% it stops.
If available RAM falls below 2 GiB it warns; below 1 GiB snapshot/incremental
work stops. Typesense RSS, available RAM, swap, and disk are visible in
`status`.

## Windows and WSL recovery

- A Windows reboot or WSL shutdown stops availability. After WSL starts, use
  `start` and then wait for `/ready`.
- Sleep/hibernate suspends service availability. Keep the machine plugged in
  and configure Windows power settings to prevent automatic sleep while it is
  acting as a server; review Windows Update/restart behavior separately.
- Power loss is not simulated against the live 10M-document store. On return,
  start the services, verify `/ready`, then inspect freshness and the last
  incremental result.
- This local deployment is not HA. Do not expose Typesense port 8108/8107.
  External users must reach a separately secured FastAPI/reverse-proxy path;
  the current service binds both Typesense and FastAPI to loopback.

## Operational limitations

Postgres fallback is a smaller legacy subset; broad global quantity sorting is
approximately 1–1.6 seconds; serving generation selection is explicit rather
than alias-based; local availability depends on Windows/WSL/network state;
and this is not a high-availability deployment.

## Early-user public HTTPS mode

Public access uses one Cloudflare Tunnel named tunnel. The tunnel connects to
FastAPI on `127.0.0.1:8001`; it does not expose Typesense, WSL, Postgres, or
the filesystem. Cloudflare terminates HTTPS and renews the certificate. No
router port forwarding is required. Caddy/nginx is not part of this path.

The API serves the existing `apps/web` directory same-origin when running from
the repository. `/config.js` then selects the public origin for browser API
calls. The checked-in frontend contains no Typesense key, Postgres DSN, tunnel
token, or private certificate.

### One-time public setup

Install `cloudflared` in WSL or set its absolute path. In Cloudflare, create a
named tunnel and DNS hostname, then copy the example and replace only the
placeholder values:

```bash
cp infra/ingress/cloudflared.yml.example ~/.config/bidfinder/cloudflared.yml
chmod 600 ~/.config/bidfinder/cloudflared.yml
```

Create `~/.config/bidfinder/ingress.env` with mode `600`:

```text
BIDFINDER_PUBLIC_URL=https://public.example.com
CLOUDFLARED_BIN=/usr/local/bin/cloudflared
CLOUDFLARED_CONFIG=/home/USER/.config/bidfinder/cloudflared.yml
```

Set the same `BIDFINDER_PUBLIC_URL` in `~/.config/bidfinder/runtime.env`.
This enables trusted proxy handling only for loopback peers and makes public
cookies `Secure; HttpOnly; SameSite=Lax`. Do not set `TRUSTED_PROXY_IPS` to a
public network; the ingress must continue to connect through loopback.

Install or refresh user units, then validate the external config:

```bash
bash infra/runtime/bidfinder-install.sh install
bash infra/runtime/bidfinder-install.sh public-status
bash infra/ingress/bidfinder-cloudflared.sh validate
```

### Public lifecycle

```bash
# Local only: ingress stopped; FastAPI and Typesense remain usable locally.
bash infra/runtime/bidfinder-install.sh public-stop

# Start/stop public access without changing local services.
bash infra/runtime/bidfinder-install.sh public-start
bash infra/runtime/bidfinder-install.sh public-stop
bash infra/runtime/bidfinder-install.sh public-restart
bash infra/runtime/bidfinder-install.sh public-status

# Persist public mode across WSL user-service startup.
bash infra/runtime/bidfinder-install.sh public-enable

# Immediate disable plus remove automatic startup.
bash infra/runtime/bidfinder-install.sh public-disable
```

`public-stop` is the immediate public-access safety switch and does not stop
FastAPI or Typesense. `public-disable` is the stronger rollback for local-only
mode. The tunnel service has no access log and uses systemd journal output;
query bodies, cookies, and authorization headers are not logged by BIDFinder.

Rotate access by creating a new Cloudflare tunnel credential, updating the
external `cloudflared.yml` path, restarting with `public-restart`, then
revoking the old tunnel/credential in Cloudflare. Never commit either file.

### Public route boundary

Allowed public surface is `/`, static assets, `/health`, and the existing
product `/api/*` routes for auth, search, autocomplete, metadata, feedback,
filter configuration, and search contract. `/ready`, `/api/warmup`,
`/docs`, `/redoc`, and `/openapi.json` are denied by the tunnel config because
they expose operator or diagnostic detail. `/health` is intentionally a
minimal anonymous liveness response.

The application keeps an explicit in-process rate limit for search,
autocomplete, auth, metadata, feedback, and contract routes. Public requests
are bounded to a 2 MiB body, 100 bulk child queries, 20 bulk fields, and
sequential bulk execution (concurrency 1). These are process-local MVP guards,
not distributed abuse protection.

### Windows/WSL availability

Keep Windows running, WSL active, the machine awake, and network connected.
Windows reboot, update, sleep, or WSL shutdown creates an outage. Existing
linger-backed BIDFinder services recover after WSL startup; if public mode is
not enabled, run `public-start` after the machine returns. There is no HA.

For troubleshooting, check `public-status`, `status`, and:

```bash
journalctl --user-unit=bidfinder-ingress.service -n 120 --no-pager
curl --fail --max-time 10 "$BIDFINDER_PUBLIC_URL/health"
```

If the backend is unavailable, stop ingress, verify local `health` and
`ready`, then start/restart the existing Typesense and API services before
re-enabling public access. Do not expose port `8108` or change Typesense
binding.
