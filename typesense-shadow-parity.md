# BIDFinder Typesense Shadow Parity — Phase 4A-R

Status: **PARTIAL — preserved Phase 4A parity evidence; not a Phase 4B gate**

Branch: `refactor-msc-typesense-v1`  
Starting HEAD: `2010504bbe1d1a5eaec8ea6b085b4c09dc52a036`  
Serving generation: `serving_v1_20260901`  
Stable aliases: inactive; no alias was activated.

This artifact separates the existing offline synthetic baseline from the live
Postgres ↔ Typesense validation. It contains aggregate evidence only: no API
key, database credential, raw record, or raw query value.

Phase 4B reclassifies population-driven observations as
`LEGACY_POPULATION_DIFFERENCE`. `QUERY_CONTRACT_FAILURE` is reserved for an
advertised operation rejected by the live schema or adapter; ranking and slow
query observations remain `RANKING_DIFFERENCE` and `PERFORMANCE_OUTLIER`.

## Offline synthetic baseline

The existing deterministic baseline remains green: 13 synthetic records and 30
comparisons, with P0/P1/P2/P3 all zero. This is unit/tooling coverage and is
not production parity evidence.

## Live Postgres ↔ Typesense baseline

### Serving data plane

- Typesense health: PASS.
- Checkpoint coverage: `9,738 / 9,738`.
- Provenance rows: `10,211,267`; UUID conflicts: `0`; unresolved rejects: `0`.
- Physical/provenance parity: PASS.
- Physical counts: goods `9,593,796`; medicines `585,449`; traditional `32,022`.
- Exactly one physical serving generation was live: `serving_v1_20260901`.

The previous live attempt failed because the local Typesense process was not
running in the execution context. The existing WSL lifecycle/configuration was
valid; starting it with the repository lifecycle tooling restored reachability.
No database, collection, generation, key, or alias was recreated.

### Connectivity and identity bridge

Real FastAPI/Postgres connectivity passed, including a real procurement query.
The legacy tables contain serial `__row_id`-style identity only:

- goods: `id`, `ma_tbmt`, `so_qd`, `version`;
- medicines: `id`, `ma_tbmt`, `so_qd`, `version`, `ma_thuoc`.

No shared MSC/source UUID exists in the legacy tables. The comparator therefore
uses an internal SHA-256 fingerprint over normalized stable fields common to
both representations. It normalizes nulls, whitespace/Unicode, numerics, and
arrays; excludes serial IDs, Typesense metadata, ordering, and non-canonical
timestamps; and compares fingerprints as multisets. The public API remains
unchanged.

Collision audit: 845 identity rows, 844 unique fingerprints, one duplicated
fingerprint group, and one ambiguous collision group. That group is classified
as `IDENTITY_NOT_COMPARABLE`, not as a false P0.

### Live corpus and coverage

The deterministic live run executed 96 Postgres ↔ Typesense parity comparisons,
8 autocomplete comparisons, and 8 traditional adapter smoke cases (104 total
comparison operations including autocomplete). It covered real goods and
medicine values across historical/recent years, Unicode text, identifiers,
manufacturers/bidders, filters, price ranges, explicit sorts, pagination,
zero-result and broad queries. Traditional smoke covered item/scientific-name
queries, filters, pagination, sorts, broad and zero-result reads.

| Endpoint | Comparisons | P0 | P1 | P2 | P3 | Infra errors |
|---|---:|---:|---:|---:|---:|---:|
| `/api/query` | 60 | 21 | 1 | 31 | 0 | 0 |
| `/api/query-preview` | 12 | 0 | 1 | 0 | 0 | 0 |
| `/api/bulk-query` | 24 | 0 | 5 | 19 | 0 | 0 |

| Query class | Comparisons | P0 | P1 | P2 |
|---|---:|---:|---:|---:|
| `EXACT_IDENTIFIER` | 3 | 3 | 0 | 0 |
| `FILTER_ONLY` | 8 | 6 | 0 | 0 |
| `EXPLICIT_SORT` | 12 | 12 | 0 | 0 |
| `FULL_TEXT_RELEVANCE` | 73 | 0 | 7 | 50 |

The group totals were goods 45 and medicines 45. Traditional was validated as
direct adapter smoke because the current public legacy API has no traditional
route. All eight traditional cases reached Typesense; broad total was 32,022
and zero-result total was 0.

### Parity results — raw Phase 4A evidence and Phase 4B reclassification

- Raw Phase 4A severity counts remain **P0 21, P1 7, P2 50** for traceability.
  They were based on comparing unequal Postgres and Typesense populations.
- Phase 4B reclassifies the population-driven observations as
  `LEGACY_POPULATION_DIFFERENCE`: zero P0 correctness failures.
- Explicit-sort membership/order differences across unequal populations are
  `RANKING_DIFFERENCE`, not a population-parity gate.
- The raw six >500 ms observations remain performance evidence and are
  `PERFORMANCE_OUTLIER` candidates, not search-contract failures.
- P3: **0** as a severity classification; six separate Typesense reads exceeded
  the 500 ms diagnostic threshold.
- Total-count agreement: 13 of 96 comparisons.
- Missing canonical identities: 422; extra canonical identities: 423.
- Explicit-sort agreement: 0 of 12.
- Field mismatches: 0 on comparable rows.
- Top-K overlap across parity comparisons: p50 `0.0`, p95 `1.0`.

The legacy Postgres read population is materially smaller than the full serving
population (goods 374,689; medicines 274,790). This is expected corpus
expansion, not a defect in the authoritative Typesense search data. Postgres
remains useful for legacy API characterization and bounded infrastructure
fallback only.

### Preview, bulk, and autocomplete

- `/api/query-preview`: 12 semantic shadow comparisons ran; the existing
  preview envelope and SQL/debug contract were preserved. Validation targets
  normalized semantic intent, not SQL text.
- `/api/bulk-query`: 24 bounded child comparisons ran. Child mapping and
  failure isolation passed; ordering/envelope stayed unchanged; no uncontrolled
  bulk load was used.
- `/api/autocomplete`: 8 comparisons reached Typesense with zero infrastructure
  errors. Empty-prefix, prefix, Unicode, limit, and deduplication cases ran;
  top-K overlap p50 was `0.2`, p95 `0.5`.

### Latency and slow-query evidence

| Read path | p50 (ms) | p95 (ms) |
|---|---:|---:|
| Postgres | 242.509 | 921.274 |
| Typesense | 27.944 | 579.397 |

Six Typesense reads exceeded 500 ms. Compact observed examples:

| Endpoint | Group | Class | Page/limit | Sort | Latency (ms) | Total hits |
|---|---|---|---|---|---:|---:|
| `/api/query` | goods | FILTER_ONLY | 1/5 | — | 579.397 | recorded in harness |
| `/api/query` | goods | EXPLICIT_SORT | 1/10 | `quantity:asc` | 978.508 | 9,593,796 |
| `/api/query` | goods | EXPLICIT_SORT | 1/10 | `quantity:desc` | 968.566 | 9,593,796 |

The remaining three slow rows are retained by the live harness output index;
the compact repository artifact intentionally omits raw query values. No
blind optimization was attempted.

### Primary-response isolation

Six baseline and six shadow-enabled FastAPI requests all returned HTTP 200.
Shadow was launched as an independent background task and did not delay the
primary response by the Typesense diagnostic timeout:

- Postgres-only p50/p95: `1075.353 / 1085.075 ms`;
- shadow-enabled p50/p95: `1130.199 / 1151.914 ms`;
- observed response overhead: `54.846 / 66.839 ms` p50/p95;
- public schema equal: yes; public data equal: yes; user waits for Typesense:
  no.

The controlled local validation used sample rate `1.0` and a 3-second bounded
diagnostic timeout. The application default remains 0.5 seconds.

### Failure isolation

An isolated process was pointed at an invalid shadow-only endpoint and then
restored. The Postgres request still returned HTTP 200; the shadow report
recorded one `SHADOW_INFRA_ERROR`; no HTTP 5xx was caused by shadow execution.

### Resources

- Typesense RSS: `7,371,396 KB` (about 7.03 GiB); CPU sample `63.6%`.
- WSL `MemAvailable`: `11,333,726,208` bytes.
- WSL swap: total `20,971,155,456` bytes; free `9,637,429,248` bytes. Swap was
  already in use and is recorded as an environment condition, not attributed
  to shadow traffic.
- FastAPI baseline: RSS `75,071,488` bytes; cumulative CPU `1.515625 s`.
- FastAPI shadow: RSS `77,189,120` bytes; cumulative CPU `1.953125 s`.

The bounded run showed a small FastAPI RSS delta. Typesense remains the
dominant resident process; no second generation was created.

## Gate decision

PASS evidence exists for service reachability, serving-data integrity,
Postgres access, the internal identity bridge, endpoint execution, failure
isolation, response isolation, public contract preservation, and resource
measurement. The historical Phase 4A parity gate remains **PARTIAL** as a
record of its old population-equality criterion. It is not a Phase 4B
correctness gate.

No frontend files, stable aliases, user traffic routing, or primary Typesense
behavior were changed by the preserved parity run.

## Recommendation

Use this report as preserved Phase 4A operational evidence. Phase 4B-R
correctness is recorded separately in `typesense-query-validation.json` and
passes its schema-derived search contract, source-grounded invariants,
relevance, and full-corpus latency/resource checks. Do not align or expand the
legacy Postgres population as a prerequisite for Typesense search cutover.
