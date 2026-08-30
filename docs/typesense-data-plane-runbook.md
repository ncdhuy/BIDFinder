# Typesense data-plane runbook (Phase 3A)

Phase 3A adds a crawler-only Typesense data plane. It does not change FastAPI,
the browser, Postgres procurement reads, or production routing. It proves a
small controlled path from MSC public search through canonical normalization
and batched Typesense upsert.

## Supported runtime and configuration

The target server version is Typesense `30.2`. The crawler uses a small
stdlib HTTP client and supports any compatible endpoint configured through:

```text
TYPESENSE_HOST=localhost
TYPESENSE_PORT=8108
TYPESENSE_PROTOCOL=http
TYPESENSE_API_KEY=<write-capable local/admin key>
TYPESENSE_TIMEOUT_SECONDS=10
TYPESENSE_IMPORT_BATCH_SIZE=500
```

`TYPESENSE_CONNECTION_TIMEOUT_SECONDS` and `TYPESENSE_BATCH_SIZE` are accepted
compatibility aliases. The API key is never logged or sent to `apps/web`.
HTTPS uses normal certificate and hostname verification. MSC's source-specific
ECDHE TLS context is not used for Typesense.

## Disposable local server

From the repository root, set a development-only key and start the pinned
container:

```powershell
$env:TYPESENSE_API_KEY = "dev-only-change-me"
docker compose -f infra/typesense/compose.yml up -d
```

The service listens on `http://localhost:8108`. Its named Docker volume is
local development state. Do not point this compose file at a production
cluster or reuse a production key.

## Aliases and physical generations

Stable logical aliases are:

```text
bidfinder_goods
bidfinder_medicines
bidfinder_traditional
```

Crawler writes always target a versioned physical collection, for example:

```text
bidfinder_goods_v1_dev1
bidfinder_medicines_v1_dev1
bidfinder_traditional_v1_dev1
```

The generation identifier is supplied explicitly. It is validated as a safe
1–64 character collection-name suffix. Collection creation never activates an
alias and never deletes an older generation.

## Safe lifecycle

Create, validate, and activate are separate operator actions:

```powershell
python -m crawler_engine.msc.cli typesense create-generation --generation dev1
python -m crawler_engine.msc.cli typesense validate-generation --generation dev1
python -m crawler_engine.msc.cli typesense inspect
python -m crawler_engine.msc.cli typesense activate-generation --generation dev1
python -m crawler_engine.msc.cli typesense inspect
```

`create-generation` is idempotent only when an existing physical collection
has the exact expected fields, types, flags, and metadata. An incompatible
collection fails closed. `validate-generation` checks all three collections.
`activate-generation` validates first, then explicitly updates each alias.
The three aliases are independent Typesense API objects; keep the previous
generation as the rollback target during an activation.

Rollback one logical group to a known generation:

```powershell
python -m crawler_engine.msc.cli typesense rollback-alias --group goods --generation previous
```

The rollback target must be the matching physical V1 collection and pass the
same schema validation. No collection is dropped automatically.

## Crawl into a generation

Typesense writes require both `--sink typesense` and `--generation`:

```powershell
python -m crawler_engine.msc.cli crawl `
  --from 2026-08-25 --to 2026-08-25 `
  --sources goods_general,medical_devices,medicine_generic,medicine_originator,medicine_herbal,herbal_material,traditional_medicine `
  --sink typesense --generation dev1 `
  --checkpoint crawler_engine/.msc_state/phase3a.sqlite3
```

Use a dedicated checkpoint database for a controlled proof. Do not omit the
explicit date range. Do not use this command as a historical 2023-to-present
backfill command in Phase 3A.

The sink checks the physical generation schema, strips internal `source_key`
from the Typesense document, rejects fields outside the frozen canonical
schema, sorts by UUID, and sends sequential batches. Default batch size is
500; use `--typesense-batch-size` for a deliberate local override.

Every batch uses:

```text
POST /collections/<physical>/documents/import?action=upsert
```

The request is NDJSON. A successful HTTP response is not enough: every
response line must parse as an object with `success == true`, and response line
count must equal attempted document count. A false result or line mismatch
returns a rejected sink result, leaves the partition incomplete, records a
machine-readable Typesense error category, and stops later batches. Rerun the
full partition safely; stable MSC UUIDs and upsert semantics prevent duplicate
documents.

## Checkpoints and completion

Checkpoint identity is now:

```text
source_key × partition_date × sink_target
```

Existing Phase 2 rows are migrated in place as `sink_target=validation-jsonl`.
Typesense rows use `sink_target=typesense:<generation>`, so a completed
generation A partition never causes generation B to be skipped.

For a closed partition, completion requires all gates:

```text
parent_pre_count == parent_post_count == unique_source_count == normalized_count
normalized_count == Typesense sink accepted_count
```

MSC contract, partition, normalization, or count failures remain distinct from
Typesense infrastructure failures. Typesense categories include
`TYPESENSE_CONNECT_ERROR`, `TYPESENSE_SCHEMA_ERROR`,
`TYPESENSE_IMPORT_ERROR`, `TYPESENSE_PARTIAL_IMPORT`,
`TYPESENSE_IDENTITY_CONFLICT`, and `TYPESENSE_ALIAS_ERROR`.

## Direct search validation

`TypesenseClient.search_group()` uses the frozen group-specific `query_by`
configuration and rejects filter or sort fields outside the allow-list. Use
`get_document()` and `document_count()` to verify UUID identity and collection
counts after each controlled partition. Search smoke should cover a name,
active ingredient or manufacturer, bidder/code, a facet filter, a numeric
range, and a permitted sort for each logical group.

`TypesenseClient.multi_search_all()` sends goods, medicines, and traditional
queries to `/multi_search` in one request. This is a developer proof for a
future `scope=all` backend implementation; it is not exposed to the browser in
Phase 3A.

## Controlled proof and overflow

The controlled dataset must reach all seven verified source keys: goods-general,
medical-devices, medicine-generic, medicine-originator, medicine-herbal,
herbal-material, and traditional-medicine. Prefer a nonzero representative
partition for each source. The known `goods_general` 2026-08-28 overflow day
may be included when the disposable server has enough local resources. The
MSC engine must adaptively partition it, union UUIDs, and import batches into
the staging physical collection before validation.

Do not activate aliases until all selected partitions, counts, UUID samples,
schema checks, idempotent rerun checks, and search smoke checks pass. Do not
run the full historical backfill or switch FastAPI in this phase.

## Phase 3A-L live proof evidence

The bounded live gate passed on 2026-08-30 against a real disposable
Typesense `30.2` server started in WSL2 from the official Linux binary. Docker
and Podman were unavailable on the validation host, so no container workflow
was added. The proof used generation `live_gate_20260830g`; its physical
collections and aliases remain disposable and must not be treated as
production state.

Run the reusable gate only with a disposable local server and a fresh
generation:

```powershell
$env:TYPESENSE_HOST = "127.0.0.1"
$env:TYPESENSE_PORT = "8108"
$env:TYPESENSE_PROTOCOL = "http"
$env:TYPESENSE_API_KEY = "<disposable-local-key>"
python tools/typesense_live_integration.py --generation live_gate_<run-id> `
  --report typesense-integration-report.json
```

The gate creates a dedicated temporary SQLite checkpoint DB, calls only the
public MSC `/search_prc` endpoint, indexes the seven frozen representative
partitions plus `goods_general / 2026-08-28`, and records the complete proof
in the report. It does not connect to Postgres/Neon, use `/export`, use
cookies, run historical backfill, or change FastAPI/frontend routing.

Live evidence summary:

| Check | Result |
| --- | --- |
| Health/schema/collections | Typesense `30.2` healthy; three physical A collections created, inspected, and schema-validated |
| Seven sources | 27,491 accepted documents, 61 import batches, 0 rejects; all exact count/UUID/checkpoint invariants passed |
| Overflow | 16,248 rows, 4 adaptive leaves, 26 MSC page requests, 33 import batches, 0 rejects, completed checkpoint |
| Collections | Expected UUID union equaled actual counts: goods 27,232; medicines 172; traditional 87 |
| Alias/checkpoint proof | Activation, B switch, rollback to A, forced upsert, skip, generation separation, and legacy checkpoint separation passed |
| Query proof | Full-text, configured filters, ascending/descending price sort, and three-way multi-search passed |
| Partial import | Real HTTP 200 mixed fixture produced parser-detected 1 accepted/1 rejected; production sink remained fail-closed |

See [`typesense-integration-report.json`](../typesense-integration-report.json)
for structured metrics. Keep it free of API keys and full procurement rows.

## Troubleshooting

- `TYPESENSE_CONNECT_ERROR`: check server health, host/port/protocol, firewall,
  and local API key. No MSC source contract is quarantined for this failure.
- `TYPESENSE_SCHEMA_ERROR`: recreate a new generation name or inspect the
  incompatible physical collection; never write through an alias to work
  around it.
- `TYPESENSE_PARTIAL_IMPORT`: inspect the per-line diagnostics and rerun the
  complete partition. HTTP 200 can still contain failed documents.
- `TYPESENSE_ALIAS_ERROR`: validate the target physical collection and point
  only the intended logical alias.
- `COMPLETED` is missing: inspect checkpoint `sink_target`, accepted/rejected
  counts, and parent pre/post parity. A failed run is retryable; it is not a
  signal to delete state.
