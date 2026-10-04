# Typesense primary procurement-search runbook (Phase 4C)

## Runtime defaults

Set these values for the intended user-serving FastAPI runtime:

```text
BIDFINDER_PROCUREMENT_BACKEND=typesense
BIDFINDER_PROCUREMENT_FALLBACK_ENABLED=true
BIDFINDER_TYPESENSE_SERVING_GENERATION=serving_v1_20260901
```

The frontend sends canonical application query parameters. FastAPI selects the centralized procurement backend and Typesense reads the explicit serving generation.

## Fallback policy

Fallback is enabled only for Typesense infrastructure failures (unavailable, timeout, connection, or transport errors classified as `SHADOW_INFRA_ERROR`). Semantic query-contract failures, unsupported fields, malformed queries, and application errors propagate visibly and never fall back.

When fallback occurs, operational logs record `DEGRADED_POSTGRES_FALLBACK`. The response is valid legacy Postgres coverage but is not equivalent to the complete Typesense corpus.

## Rollback

1. Change the runtime configuration:

   ```text
   BIDFINDER_PROCUREMENT_BACKEND=postgres
   BIDFINDER_PROCUREMENT_FALLBACK_ENABLED=false
   ```

2. Restart or reload the FastAPI application.

No frontend rollback is required. Postgres remains available for users/authentication/sessions/password reset/feedback/forum and other control-plane state. Procurement search in rollback mode covers only the legacy subset.

## Serving and incremental operations

Keep `BIDFINDER_TYPESENSE_SERVING_GENERATION=serving_v1_20260901` explicit. Stable aliases are intentionally inactive during this phase. The incremental CLI remains generation-explicit and must target this serving generation; do not run a historical backfill as part of Phase 4C.

Phase 4C performs no procurement write migration. Incremental ingestion continues through MSC → Typesense serving using the existing Phase 3C path.

## Safety checks

- Keep only one full serving generation live.
- Do not print or commit environment files, credentials, API keys, runtime databases, snapshots, or raw logs.
- Before any future repair/backfill, confirm the database target and prefer dry-run/audit modes.
- Re-run the cutover audit after any generation or fallback-policy change.
