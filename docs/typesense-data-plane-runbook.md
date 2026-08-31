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

## Phase 3B-S empirical sizing result — 2026-08-30

The bounded sizing gate passed using a fresh disposable Typesense `30.2`
generation and the existing MSC ingestion path. It indexed 500,013 real
canonical documents across all seven source contracts, with deterministic
dates spanning 2023–2026, zero failed partitions, zero rejected documents,
and exact UUID/count parity across the three physical collections:
`goods=426,843`, `medicines=55,347`, and `traditional_medicine=17,823`.

The milestone OS measurements were:

| Milestone | Documents | RSS delta | `/data` delta |
| --- | ---: | ---: | ---: |
| Baseline | 0 | 0 B | 0 B |
| 50k | 55,741 | 200,744,960 B | 117,593,620 B |
| 100k | 100,467 | 246,554,624 B | 220,767,449 B |
| 250k | 253,253 | 436,113,408 B | 564,214,374 B |
| 500k | 500,013 | 561,414,144 B | 1,111,889,208 B |

After a graceful restart of the same data directory, all counts restored;
restart RSS delta was 597,524,480 B and `/data` delta was 1,140,740,603 B.
The largest-sample slopes were 1,122.824 RSS B/document and 2,223.721 data
directory B/document. Projection to 9,801,385 documents is 11.01 GB RAM and
21.80 GB data directory, with 13.21/26.15 GB at +20% and 16.51/32.69 GB at
+50%. `/metrics.json` did not expose usable memory counters in this runtime;
the report keeps those fields unavailable rather than substituting estimates.

Decision: 32 GB/node is sufficient under the 70% steady-state target
(conservative projected utilization 32.0%). Recommended starting shape is
Typesense Cloud HA, 3 nodes, 32 GB RAM and 8 vCPU per node, with at least
200 GB provider disk allocation per node. Self-hosted alternative is three
Typesense `30.2` nodes with 32 GB RAM, 8 vCPU, and at least 200 GB persistent
SSD each. Keep 50% free before creating a new generation, warn below 35%, and
block below 20%; retain rollback generations.

The final sizing evidence is in
[`typesense-sizing-report.json`](../typesense-sizing-report.json) and the
readable [`typesense-sizing-report.md`](../typesense-sizing-report.md). This
run did not perform the full historical backfill, activate aliases, change
FastAPI/frontend routing, or write Neon/Postgres.

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

## Historical backfill boundary

Phase 3B-R adds readiness tooling only. It does not populate a historical
generation, change FastAPI/frontend routing, or activate aliases. Historical
imports must target physical `bidfinder_<group>_v1_<generation>` collections
through `TypesenseSink`; the dedicated runner never calls alias operations.

Before any future import, inspect the manifest capacity estimate and remote
`/health` plus `/metrics.json` when available. Pause before disk/RAM exhaustion.
After import, run source-range coverage, UUID provenance, physical-count,
sample-parity, and search-benchmark audits before a separately approved alias
activation.

The bounded search benchmark is explicit and physical-generation scoped:

```powershell
python -m crawler_engine.msc.cli benchmark --generation hist_2026g1 --repeats 3
```

## Local dogfood / local production-like mode

Use the native Ubuntu/WSL filesystem for persistent Typesense data:
`~/.local/share/bidfinder/typesense/data`. The operator wrapper uses
Typesense `30.2`, HTTP, `127.0.0.1:8108`, and a key loaded from the local
operator environment file; it does not enable CORS or public binding.

```bash
bash infra/typesense/local-typesense.sh start
bash infra/typesense/local-typesense.sh health
bash infra/typesense/local-typesense.sh status
bash infra/typesense/local-typesense.sh restart
bash infra/typesense/local-typesense.sh stop
```

Run the bounded real-MSC proof with
`python tools/local_typesense_canary.py` from WSL. Its generation-specific
checkpoint, UUID audit, reports, snapshots, and logs stay outside Git. The
canary must pass parent pre/post, unique-source, normalized, and accepted
counts, with zero rejected documents and zero UUID conflicts. Stable aliases
remain untouched; browsers must not call Typesense directly.

Back up only through `POST /operations/snapshot` (the wrapper's `snapshot`
operation), storing the result outside `data/`. For restore proof, copy the
snapshot into a separate disposable data directory, start it on a temporary
loopback port, validate collection counts and search, then stop it. Never copy
the live data directory as a backup.

Keep substantial disk headroom beyond the approximately 22 GB full-generation
estimate, and monitor WSL memory, Typesense RSS, CPU, and swap. Avoid sustained
swap thrashing and other memory-heavy local workloads. Prevent Windows Sleep or
Hibernate during backfill or serving. This is a single-node local dogfood
target; HA is deferred to the later dedicated Linux/Hetzner stage.
