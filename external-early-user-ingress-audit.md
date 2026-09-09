# Phase 4E — Secure External Early-User Ingress Audit

Status: **PARTIAL**

## Starting state

- Branch: `refactor-msc-typesense-v1`
- Starting HEAD: `04f84bf63d06695afb3756aba638d74c0726eb08`
- Worktree: clean
- Existing Phase 4D service model preserved: systemd user services, FastAPI `127.0.0.1:8001`, Typesense `127.0.0.1:8108`, generation `serving_v1_20260901`.

## Chosen ingress

Cloudflare Tunnel is the simplest safe class for this machine. No BIDFinder
proxy or public 80/443 listener was installed, and a named tunnel avoids router
port forwarding while terminating HTTPS at the managed edge. The single origin
is `http://127.0.0.1:8001`; Caddy/nginx and a second proxy are not introduced.

The repository supplies an opt-in `bidfinder-ingress.service`, a validation/
run wrapper, and `cloudflared.yml.example`. The operator supplies externally:

```text
BIDFINDER_PUBLIC_URL=https://public.example.com
CLOUDFLARED_BIN=/usr/local/bin/cloudflared
CLOUDFLARED_CONFIG=/home/USER/.config/bidfinder/cloudflared.yml
```

The hostname, tunnel UUID, and credentials-file remain outside Git. During this
audit `cloudflared` and the named-tunnel config were absent, so no public
hostname was activated.

## Security boundary

FastAPI and Typesense remain loopback-bound. FastAPI now serves the existing
`apps/web` directory same-origin when running from the repository. A dynamic
`/config.js` response sets the browser API base to `window.location.origin`, so
public browser calls stay on the HTTPS tunnel and never need a Typesense key.

The Cloudflare example denies `/ready`, `/api/warmup`, `/docs`, `/redoc`, and
`/openapi.json`. `/health` is the safe public liveness target. Static web files
and product `/api/*` routes remain available; no WSL filesystem, runtime DB,
logs, environment files, or Typesense endpoint is routed.

## Auth, proxy, and abuse controls

Existing authentication policy remains enforced. Phase 4D already proved an
unauthenticated full query returns HTTP 401. Public mode adds the public origin
to the explicit CORS list, never `*`. Forwarded scheme/IP headers are accepted
only from configured loopback peers; arbitrary public headers are ignored.

Public cookies default to `Secure; HttpOnly; SameSite=Lax` when
`BIDFINDER_PUBLIC_URL` is configured. Same-origin web/API plus SameSite=Lax is
the MVP CSRF boundary. Existing process-local rate limits remain, with default
query 30/minute and autocomplete 120/minute. Request bodies cap at 2 MiB;
bulk requests cap at 100 child rows and 20 fields; child work stays sequential
(concurrency 1).

Security headers include `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Resource-Policy`, and
HSTS when the trusted HTTPS proxy scheme is active. Generic error responses do
not expose stack traces, filesystem paths, DB strings, or Typesense internals.
FastAPI access logs remain disabled; tunnel configuration does not enable
request-body logging.

## Lifecycle and rollback

Normal `start`, `stop`, and `restart` still control only local Typesense and
FastAPI. Public access is opt-in:

```bash
bash infra/runtime/bidfinder-install.sh public-start
bash infra/runtime/bidfinder-install.sh public-stop
bash infra/runtime/bidfinder-install.sh public-restart
bash infra/runtime/bidfinder-install.sh public-status
bash infra/runtime/bidfinder-install.sh public-enable
bash infra/runtime/bidfinder-install.sh public-disable
```

`public-stop` closes public access immediately without stopping local BIDFinder.
`public-disable` also removes ingress autostart. `public-enable` persists the
ingress user service across WSL user-service recovery. Systemd ordering is
Typesense, FastAPI, ingress; ingress uses a backoff and does not create a
backend restart loop. Rotate by replacing the external Cloudflare credential,
restarting ingress, and revoking the old tunnel credential in Cloudflare.

## Validation

Passed: Python compile, Bash syntax, changed-area API tests (43), web tests (5),
crawler tests (3), tracked secret scan, local `/health`, local static root,
local same-origin `/config.js`, and local `ss` proof that Typesense listens on
`127.0.0.1:8108` only. The existing Typesense service was active but still in
its normal large-generation loading window during the sampled audit health
checks; no data or schema action was taken.

Blocked: real HTTPS public response, certificate validation, external auth,
seven subtype journeys, 2022/January 2023/recent 2026 proof, external
Vietnamese/contextual autocomplete, external 1/5/10 concurrency, and local vs
external latency. These require the operator's Cloudflare account/tunnel
credential, hostname, and an external network. The full repository discovery
command also contains unrelated MSC package/import and long-running safety
issues; focused changed-area suites pass.

## Availability limitation

This remains single-machine hosting. Windows must run, WSL must be active, the
machine must not sleep, and Internet connectivity must remain available.
Windows reboot/update or WSL shutdown causes an outage. Run `public-start`
after recovery when public mode is not enabled. No HA is claimed.

Machine-specific evidence and the complete gate matrix are in
`external-early-user-ingress-audit.json`.

Real external early-stage users should **not** be opened yet: ingress
credentials and external proof are still required. After those operator-owned
steps pass, use the same runbook and stop switch; no search or data redesign is
needed.
