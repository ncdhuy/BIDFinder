# Phase 4B Typesense Search Runbook

## Authority and generation

MSC is the search-data authority. The serving path is validated ingestion into
Typesense generation `serving_v1_20260901`. Legacy Postgres is retained for
compatibility, temporary fallback, and characterization of legacy controls; it
is not a population-parity gate.

The repository addresses only versioned physical collections. Stable aliases
remain inactive during Phase 4B.

## Query contract

The machine-readable source of truth is
[`typesense-search-contract.json`](../typesense-search-contract.json), exposed
read-only through `GET /api/search-contract`. Human-readable field coverage is
in [`typesense-search-contract.md`](../typesense-search-contract.md).

Three public families group the seven source identities:

| Group | Source subtypes |
|---|---|
| GOODS | `goods_general`, `medical_devices` |
| MEDICINES | `medicine_generic`, `medicine_originator`, `medicine_herbal` |
| TRADITIONAL | `herbal_material`, `traditional_medicine` |

Grouping reduces duplicated query logic. Source/subtype keys remain stable
filters and localized labels remain presentation metadata.

## Phase 4C requirement freeze

The first user-facing Typesense version must let users select GOODS,
MEDICINES, or TRADITIONAL; optionally select one or more subtypes; use every
approved search and filter field for that family; sort approved fields; and
paginate the complete serving data. A UI exposing only legacy Postgres fields
is not releasable.

No visual frontend redesign is part of Phase 4B. The existing API remains
compatible while the future UI consumes the shared search catalog.

## Backend switch and fallback

Backend selection is centralized:

```text
BIDFINDER_PROCUREMENT_BACKEND=typesense      # Phase 4C final default
BIDFINDER_PROCUREMENT_BACKEND=postgres       # explicit rollback mode
BIDFINDER_PROCUREMENT_BACKEND=controlled     # controlled verification mode
```

`BIDFINDER_CONTROLLED_TYPESENSE_ENABLED` enables the controlled mode, and
`BIDFINDER_PROCUREMENT_FALLBACK_ENABLED` enables bounded fallback. In the Phase
4C serving runtime fallback is enabled by default, and only Typesense
infrastructure failures may fall back to Postgres. Semantic or query-contract
errors must surface as errors. Postgres remains a degraded legacy subset.

## Shadow classification

Legacy Postgres versus complete Typesense population differences are classified
as `LEGACY_POPULATION_DIFFERENCE`; they are not P0 correctness failures.
Operational classifications are `QUERY_CONTRACT_FAILURE`,
`SHADOW_INFRA_ERROR`, `RANKING_DIFFERENCE`, and `PERFORMANCE_OUTLIER`.

## Validation

Run the deterministic corpus summary with:

```text
rtk python tools/typesense_query_validation.py --summary
```

Run live validation only in an environment with server-side Typesense
credentials configured. Do not print or commit credentials. Record aggregate
latency, invariant failures, resource state, and material outliers in the
validation artifact. The proven local execution is WSL from the repository
mount:

```bash
cd /mnt/d/startup/muasamcong/BIDFinder
set -a
. /home/ncdhuy/.config/bidfinder/typesense.env
set +a
export BIDFINDER_TYPESENSE_SHADOW_TIMEOUT_SECONDS=15
python3 tools/typesense_query_validation.py
```

The complete Phase 4B-R corpus is 212 cases: goods 68, medicines 74, and
traditional 70. The live gate checks source-grounded exact identifiers,
field-specific search, filter and subtype invariants, numeric and bounded ISO
`partition_date` ranges, every advertised sort direction, pagination, all 17
autocomplete fields, and aggregate relevance/performance/resource evidence.

The serving schema stores `partition_date` as an ISO string facet. Bounded
date ranges therefore use exact string date/month/year prefixes; generic
numeric range operators are not used for this field. The adapter intentionally
does not send `id:asc`: Typesense v30 rejects sorting on its implicit `id`
field in the frozen serving generation. Repeated live reads provide the
determinism check, and `id` is not an advertised sort capability.

Phase 4B-R evidence is recorded in
[`typesense-query-validation.json`](../typesense-query-validation.json) and
[`typesense-query-validation.md`](../typesense-query-validation.md). Any
Postgres-versus-Typesense population expansion remains informational and is
classified as `LEGACY_POPULATION_DIFFERENCE`; it is not a Phase 4B PASS gate.
