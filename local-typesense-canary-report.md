# Local Typesense Canary Report

Status: **PASS**
Generation: `local_canary_20260831_29ef44`
Typesense: `30.2`
Persistent data: `/home/ncdhuy/.local/share/bidfinder/typesense/data`

## Gate summary

| Gate | Result |
| --- | --- |
| persistent_target_health | PASS |
| no_alias_activation | PASS |
| canary_size | PASS |
| all_seven_source_contracts | PASS |
| all_three_logical_groups | PASS |
| completeness_invariants | PASS |
| zero_rejected_documents | PASS |
| zero_uuid_conflicts | PASS |
| uuid_collection_count_parity | PASS |
| schema_validation | PASS |
| overflow_adaptive_partitioning | PASS |
| representative_uuid_parity | PASS |
| idempotent_force_and_checkpoint_skip | PASS |
| search_filter_sort_multi_search | PASS |
| bounded_concurrency | PASS |
| read_during_write | PASS |
| restart_cycle_1 | PASS |
| restart_cycle_2 | PASS |
| abrupt_recovery | PASS |
| snapshot_created | PASS |
| snapshot_restore | PASS |
| interruption_resume | PASS |
| historical_counts_revalidated | PASS |
| manifest_fingerprints_valid | PASS |
| future_historical_generation_not_populated | PASS |
| portable_core | PASS |
| no_full_backfill | PASS |
| no_fastapi_ui_cutover | PASS |

Canary documents: `67313`
Historical revalidation total: `9801380`
Future historical generation: `hist_v1_20260829`

Full historical backfill was not run. Stable aliases were not activated. FastAPI/UI behavior was not changed.
