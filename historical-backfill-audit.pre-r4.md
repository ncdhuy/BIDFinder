# Phase 3B historical backfill audit

- Status: `PARTIAL`
- Generation: `hist_v1_20260829`
- Range: `2023-02-01` to `2026-08-29`
- Manifest fingerprint: `18f2b6577b4645a17c7867fe45ed274976ea072a497fa2efaf07098ac3c84b9c`

## Counts

- Parent partitions: `9142`; completed `16`; skipped `6959`; failed `0`; quarantined `0`.
- Normalized: `7233697`; Typesense attempted `7233697`; accepted `7233697`; rejected `0`.

## Source coverage

| Source | Broad count | Checkpoint sum | Parity |
| --- | ---: | ---: | --- |
| `goods_general` | 8219041 | 6030244 | `False` |
| `medical_devices` | 964685 | 724982 | `False` |
| `medicine_generic` | 494698 | 386660 | `False` |
| `medicine_originator` | 55239 | 39531 | `False` |
| `medicine_herbal` | 35489 | 28364 | `False` |
| `herbal_material` | 9554 | 7458 | `False` |
| `traditional_medicine` | 22468 | 16458 | `False` |

- UUID conflicts: `0`; recovery bundles: `1`.
- Sample parity: `SKIPPED`; search benchmark errors: `0`.
- Clean restart: `False`.

Aliases remain inactive. FastAPI/frontend remain unchanged.
