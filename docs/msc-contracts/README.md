# MSC contract fixtures

Phase 1A evidence for seven source partitions behind the official winning-bid-data page.

Directory names are repository slugs only. They are not MSC discriminator values.

Each source directory contains:

- `contract.json`: verified request, response, mapping, and normalization metadata.
- `search-request.json` / `search-response-sample.json`: one small live search capture.
- `export-request.json` / `export-response-sample.json`: export request shape and a one-record parser sample.

`zero-result-search-response.json` is the shared live zero-result envelope. The same HTTP 200, empty `page.content`, and zero aggregation count were verified with the reserved no-match keyword against all seven source filter combinations.

Search samples were captured without authentication. The public endpoint returned exact `page.content` and aggregation envelopes. In this environment, export requests returned HTTP 200 with an empty body because the page gates export behind login. Export envelopes in these fixtures use the Phase 0 verified `resultList` shape and the corresponding complete search record solely to exercise offline parsing; they are not live completeness evidence.

No fixture stores request headers, response headers, transient session material, or credentials.

The probe accepts these raw payload fixtures and optionally overrides the date filter:

```powershell
python tools/msc_contract_probe.py --request docs/msc-contracts/goods-general/search-request.json --source goods-general --date 2026-08-28
python tools/msc_contract_probe.py --request docs/msc-contracts/goods-general/export-request.json --source goods-general --date 2026-08-28 --with-export
```

Normal tests never call the network. The second command is an explicit research action and fails closed when the anonymous endpoint returns no JSON export body.
