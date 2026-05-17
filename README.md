# BIDFinder

## Runbook

BIDFinder currently runs with Cloud Run as the main backend and Render as a backup.

- Project structure: [docs/project-structure.md](docs/project-structure.md)
- Deploy and tune backend: [docs/cloud-run.md](docs/cloud-run.md)
- Switch backend URL: [docs/backend-routing.md](docs/backend-routing.md)
- Run load tests: [tools/load-tests/README.md](tools/load-tests/README.md)

```text
Primary: Cloud Run -> Neon Postgres
Backup: Render -> Neon Postgres
```
