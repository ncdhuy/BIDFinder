# MSC contract fixtures

Phase 1A request contracts, Phase 1B public-search proof, and Phase 1C overflow time-partition proof for seven source partitions behind the official winning-bid-data page.

Directory names are repository slugs only. They are not MSC discriminator values. Each source directory contains:

- `contract.json`: verified request, response, mapping, and normalization metadata.
- `search-request.json` / `search-response-sample.json`: sanitized public-search request and representative response.
- `export-request.json` / `export-response-sample.json`: historical/manual request shape and one-record parser sample only.

`search-only-validation.json` is the sanitized Phase 1B evidence record. It captures the selected page size, result-window rule, seven nonzero daily pagination probes, page metadata, counts, UUID summaries, field-name unions, and observed types without storing thousands of rows. [`partition-evidence.json`](partition-evidence.json) records the Phase 1C intraday range, overflow-day, boundary-overlap, and pre/post-count proof without storing full result sets.

Production path:

```text
MSC /search_prc -> source tab -> official day parent range -> agg.docCount
-> adaptive intraday safe leaves when needed -> page.content pagination
-> UUID union and full-parent count validation -> later normalization -> later Typesense upsert
```

`/search_prc/export` is not a production ingestion dependency. Interactive export requires username/password login, reCAPTCHA, Google Authenticator OTP/MFA, and an expiring session. BIDFinder must not automate login, bypass reCAPTCHA, automate MFA, copy browser cookies, or depend on a human-authenticated browser session. Historical export findings remain only for occasional human validation and offline parser coverage.

The public-search probe accepts one verified contract and applies a date. The developer-only Phase 1C mode validates overflow partitioning:

```powershell
python tools/msc_contract_probe.py --contract docs/msc-contracts/goods-general/contract.json --date 2026-08-25 --allow-weak-tls
python tools/msc_contract_probe.py --contract docs/msc-contracts/goods-general/contract.json --date 2026-08-28 --validate-partitioned-search --post-count --allow-weak-tls
```

The probe uses empty `keyWord`, reads `agg[0].buckets[0].docCount`, paginates `page.content`, validates page metadata and UUID uniqueness/overlap, and fails closed when a safe leaf exceeds `MAX_SAFE_SEARCH_RESULTS=9500`. It does not persist responses, cookies, or credentials. Normal tests never enable live mode.

`--allow-weak-tls` is a research-only compatibility flag for the official endpoint's currently weak DH parameters. It does not enable authentication and must not be carried into production code.

Normal tests never call the network. `export-response-sample.json` is parsed offline only to preserve historical Phase 1A parser coverage; no test requires authenticated MSC state.
