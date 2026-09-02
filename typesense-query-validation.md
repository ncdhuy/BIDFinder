# Typesense Query Contract Validation

Generation: `serving_v1_20260901`  
Runner: [`tools/typesense_query_validation.py`](tools/typesense_query_validation.py)

## Live result

Status: **PASS**. The 212-case deterministic corpus ran inside WSL after
sourcing `/home/ncdhuy/.config/bidfinder/typesense.env`; no credentials or raw
queries were written. The run returned zero adapter errors and zero invariant
failures.

| Group | Cases |
|---|---:|
| GOODS | 68 |
| MEDICINES | 74 |
| TRADITIONAL | 70 |
| **Total** | **212** |

Capability coverage was 45 text, 18 exact, 36 equality-filter, 26 multi-value
filter, 10 numeric-range, 3 date-range, 26 sort-direction, 12 pagination, 17
autocomplete, 7 subtype, 3 all-subtype, 3 combined, and 3 combined-page cases.
All live corpus cases passed their adapter invariants.

Operator-bearing case counts were: `eq` 36, `in` 26, numeric `min` 10,
numeric `max` 10, date `from` 3, date `to` 3, sort `asc` 13, sort `desc` 13,
exact zero-typo 18, and autocomplete prefix 17. Bounded cases count once in
the corpus and once under each operator they exercise.

## Schema and source-grounded checks

The live schema matched the contract with no mismatches. Goods/medicines/
traditional exposed 29/30/29 fields, 14/16/15 searchable fields, 11/13/12
filterable fields, 5/4/4 sortable fields, and 5/6/6 autocomplete fields.
Serving counts were 9,593,796 / 585,449 / 32,022. All seven subtype filters
passed without leakage.

Source-grounded supplemental checks passed equality filters 36/36, multi-value
filters 26/26, combined filters 3/3, numeric min/max/bounded ranges 10/10 in
each form, exact identifiers 17/17 available source values, and all 26 sort
directions. The goods registration identifier and goods model fields had no
non-empty value in the deterministic medical-device sample pool; this is a
data-availability note, not a schema mismatch. Direct ID lookup and three
zero-typo probes passed.

Bounded `partition_date` ranges passed for historical 2022 goods (8,647 hits),
January 2023 goods (36,772), and recent 2026 goods (61,150). The frozen field
is an ISO string facet, so the adapter uses exact date/month/year prefixes for
bounded windows rather than unreliable numeric range operators.

Field-specific search used only the selected `query_by` field. All 17 approved
autocomplete fields passed prefix, Unicode, limit, and deduplication checks;
subtype-context checks passed 3/3. The pragmatic relevance MVP check placed a
source-grounded primary record in the top five for all three groups.

## Performance and resources

| Query class | p50 ms | p95 ms | max ms |
|---|---:|---:|---:|
| text | 8.824 | 298.356 | 2517.693 |
| exact | 1.871 | 5.977 | 5.977 |
| filter-only equality | 4.914 | 827.744 | 2863.458 |
| multi-value filter | 31.370 | 1285.542 | 5228.093 |
| numeric range | 123.885 | 3232.849 | 3232.849 |
| date range | 7.963 | 28.135 | 28.135 |
| explicit sort | 30.560 | 1053.870 | 1100.598 |
| autocomplete | 8.130 | 334.542 | 334.542 |
| pagination | 34.088 | 594.547 | 594.547 |

There were 26 reads over 500 ms: combined-page 1, equality filter 4,
multi-value filter 4, pagination 2, numeric range 4, sort 8, subtype 1,
all-subtype 1, and text 1. These are documented `PERFORMANCE_OUTLIER`
observations; common paths did not show repeated multi-second errors or an
unsafe resource condition.

The preserved quantity-sort baseline was 978.508 ms ascending / 968.566 ms
descending. Three-run post-tuning medians were 982.953 / 974.566 ms, with
maxima 1016.484 / 1021.006 ms. This is not a material improvement, so no
speculative further tuning was applied.

The resource-sampled corpus observed one Typesense process, RSS
7,372,744–7,573,056 KB, WSL `MemAvailable` 10,872,304–11,245,452 KB, and
swap free 8,375,700 KB. Final steady state was RSS 7,355,704 KB and
`MemAvailable` 10,599,784 KB. No second serving generation or alias was live.

## Compatibility and classification

Search-contract metadata, Typesense-primary preview, bulk envelope, child
mapping, and malformed-child isolation passed. The backend default remains
`postgres`; Typesense primary remains opt-in and fallback remains infrastructure
only. Frontend files were unchanged.

The preserved Phase 4A Postgres-versus-Typesense population differences remain
informational `LEGACY_POPULATION_DIFFERENCE` evidence. They are not a Phase
4B correctness or PASS gate. Ranking differences are recorded separately;
there are no unresolved `QUERY_CONTRACT_FAILURE` results in the final live
corpus.
