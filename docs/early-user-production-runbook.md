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
