# BIDFinder Windows + WSL production runbook

This runbook is for the existing validated Typesense node. It does not rebuild,
copy, migrate, or reimport the Typesense dataset.

## Runtime layout

The application release tree is native WSL storage:

```text
~/.local/share/bidfinder/production/
  current -> releases/<git-commit>
  releases/<git-commit>/
  shared/venv -> ~/.local/share/bidfinder/runtime/venv
```

The validated state remains in its existing location:

```text
~/.local/share/bidfinder/typesense/data
~/.local/share/bidfinder/typesense/checkpoints
~/.local/share/bidfinder/typesense/reports
```

The AI usage ledger is stored in the application PostgreSQL database in
`app_ai_daily_usage`. Run the repository database initializer before cutover;
the ledger then survives API restart, release switch, reboot, and WSL recovery.

Secrets remain in `~/.config/bidfinder/*.env` with mode `600`. Nothing in the
production release tree contains API keys, Neon credentials, or tunnel tokens.

## Release and rollback

From WSL, after committing and reviewing the code:

```bash
bash infra/runtime/bidfinder-prod-deploy.sh deploy HEAD
bash ~/.local/share/bidfinder/production/current/infra/runtime/bidfinder-status.sh
```

The deploy script archives the exact Git commit into a new release, validates
the current serving report and Typesense health, atomically switches `current`,
renders user units, and restarts only FastAPI. It refuses a dirty checkout or a
running incremental service. Typesense is not restarted.

Rollback is release-local and also restarts only FastAPI:

```bash
bash infra/runtime/bidfinder-prod-deploy.sh rollback <previous-commit>
```

## Services and timers

These are user systemd units, not root services. `loginctl enable-linger`
is already enabled for the WSL user.

```text
bidfinder-typesense.service
bidfinder-api.service
bidfinder-incremental.service (oneshot)
bidfinder-incremental.timer  04:00 Asia/Ho_Chi_Minh
bidfinder-snapshot.service (oneshot)
bidfinder-snapshot.timer     Sunday 05:30 Asia/Ho_Chi_Minh
bidfinder-log-prune.timer    daily 03:30
bidfinder-ingress.service    disabled until Cloudflare credentials/config exist
```

Incremental and snapshot jobs share a non-blocking `flock` maintenance lock,
have bounded systemd start timeouts, and never invoke migration, repair, or a
full rebuild automatically.

## Windows reboot recovery

Install the idempotent per-user Task Scheduler supervisor from an elevated or
normal PowerShell session belonging to the Windows user that owns `Ubuntu`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\infra\windows\install-bidfinder-wsl-supervisor.ps1
```

The installer copies the supervisor to `%LOCALAPPDATA%\BIDFinder\bin` and the
task runs that stable copy. It uses `AtLogOn`, `IgnoreNew` duplicate policy, a named mutex, and a
long-lived `wsl.exe` keepalive. It starts the registered distro, ensures the
Typesense/API/timer units are running, and checks both local health endpoints.
It does not contain secrets. Logs are under
`%LOCALAPPDATA%\BIDFinder\logs\wsl-supervisor.log`.

Health check:

```powershell
powershell -NoProfile -File .\infra\windows\bidfinder-wsl-health.ps1
```

Remove only the supervisor task with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\infra\windows\uninstall-bidfinder-wsl-supervisor.ps1
```

Do not use `wsl --shutdown` during service hours. After a real Windows reboot,
log in, wait for the supervisor, and run the health command plus the Phase 14
acceptance checks. That reboot test is intentionally not run automatically by
deployment.

## WSL resources and power

The current `.wslconfig` remains conservative and unchanged:

```ini
[wsl2]
memory=20GB
swap=8GB
```

The host has approximately 27.8 GiB physical RAM; Typesense has been observed
at approximately 14.5 GiB steady RSS and 17.8 GiB during heavy operations.
Current swap use is zero, so increasing the WSL cap is not justified for this
personal laptop.

The AC sleep timeout is set to `0` (never sleep while serving); AC hibernate
was already `0`. DC behavior is unchanged. Existing settings were captured in
the deployment report before the change. Roll back AC sleep with:

```powershell
powercfg /change standby-timeout-ac 180
```

If a lid-close action is exposed by the firmware/power model, set it through
the normal Windows advanced power UI; no registry workaround is used here.

## Network and Cloudflare

Typesense and FastAPI must remain loopback-only:

```text
127.0.0.1:8108  Typesense
127.0.0.1:8001  FastAPI
```

The browser uses `https://api.bidfinder.vn`; it never receives a Typesense key.
The old backend remains a deployment-level rollback option and is not an
automatic browser fallback.

Cloudflared is prepared in the repository but is not activated until the
operator supplies the named tunnel credentials. The minimal external action is:

1. Install `cloudflared` in WSL.
2. Authenticate or provide the existing tunnel UUID and JSON credentials under
   `~/.cloudflared/`.
3. Create `~/.config/bidfinder/ingress.env` mode `600`, with
   `BIDFINDER_PUBLIC_URL=https://api.bidfinder.vn` and the protected config
   path expected by `infra/ingress/bidfinder-cloudflared.sh`.
4. Set the tunnel DNS route for `api.bidfinder.vn` and run
   `bidfinder-install.sh public-enable`.

The ingress config routes only to `http://127.0.0.1:8001` and has a terminal
404. It denies readiness, warmup, OpenAPI, and documentation paths publicly.

## Backups and restore

Run a local rotating snapshot after a validated release:

```bash
bash ~/.local/share/bidfinder/production/current/infra/runtime/bidfinder-snapshot.sh
```

The bundle contains a Typesense recovery snapshot, serving report/markdown,
incremental status, checkpoint, and provenance. The snapshot script validates
the SQLite files and generation before publishing the bundle; retention is 3.
Never restore over the live data directory. Use the existing restore script
against a separate recovery directory/port and validate health, collection
counts, and serving metadata before any activation.

No off-device destination is configured. This is the remaining production
durability caveat: a laptop or WSL filesystem failure can destroy the local
backup set. Add an authorized off-device command/hook only after selecting and
approving its destination; do not put credentials in Git.

## Cutover gate

Cutover is `READY` only after local status is PASS, Cloudflare public HTTPS and
auth have been tested, and Netlify is configured to `https://api.bidfinder.vn`.
Keep Cloud Run and any Render service available during soak. Ensure only this
WSL node runs incremental ingestion before disabling old scheduled producers.
If Netlify, Cloudflare, GCP, or Render credentials are unavailable, stop at the
manual dashboard/CLI boundary and retain the old backend for rollback.
