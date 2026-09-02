"""Bounded HTTP smoke for the persistent early-user runtime.

This tool intentionally uses urllib and the public API only. It is suitable
for a local, temporary anonymous-full validation window; it does not need or
accept a Typesense key.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_GROUP = {
    "goods": "goods",
    "medicines": "medicines",
    "traditional": "traditional",
}
PAGE_KEY = {
    "goods": "df2",
    "medicines": "df1",
    "traditional": "df3",
}
EXPECTED_SOURCES = {
    "goods_general",
    "medical_devices",
    "medicine_generic",
    "medicine_originator",
    "medicine_herbal",
    "herbal_material",
    "traditional_medicine",
}


@dataclass
class HttpResult:
    status: int
    elapsed_ms: float
    body: dict[str, Any]


class SmokeClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> HttpResult:
        data = None
        headers = {"Accept": "application/json", "User-Agent": "BIDFinder-early-user-smoke/1.0"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        started = time.perf_counter()
        try:
            with urlopen(
                Request(f"{self.base_url}{path}", data=data, headers=headers, method=method),
                timeout=self.timeout,
            ) as response:
                raw = response.read()
                status = response.status
        except HTTPError as exc:
            raw = exc.read()
            status = exc.code
        except URLError as exc:
            raise RuntimeError(f"HTTP transport failed for {path}: {exc.reason}") from exc
        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"non-JSON response for {path}: HTTP {status}") from exc
        return HttpResult(status=status, elapsed_ms=elapsed_ms, body=body)


def require_success(result: HttpResult, path: str) -> dict[str, Any]:
    if result.status < 200 or result.status >= 300:
        raise RuntimeError(f"{path}: HTTP {result.status}: {result.body.get('detail', result.body)}")
    if result.body.get("success") is False:
        raise RuntimeError(f"{path}: API reported failure")
    return result.body


def page_from(body: dict[str, Any], group: str) -> dict[str, Any]:
    page = body.get(PAGE_KEY[group])
    if not isinstance(page, dict) or not isinstance(page.get("data"), list):
        raise RuntimeError(f"{group}: response page is missing")
    return page


def journey_smoke(client: SmokeClient, contract: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    seen_sources: set[str] = set()
    for contract_group, group_contract in contract["groups"].items():
        if contract_group not in API_GROUP:
            continue
        api_group = API_GROUP[contract_group]
        for source in group_contract["source_types"]:
            source_key = source["key"]
            seen_sources.add(source_key)
            base = {
                "group": api_group,
                "sourceTypes": [source_key],
                "text": "",
                "searchMode": "standard",
                "limit": 1,
                "page": 1,
            }
            first = require_success(client.request("POST", "/api/query", base), "/api/query")
            first_page = page_from(first, contract_group)
            second_payload = {**base, "page": 2}
            second = require_success(client.request("POST", "/api/query", second_payload), "/api/query")
            second_page = page_from(second, contract_group)
            filtered = {
                **base,
                "dateRanges": {"partition_date": {"from": "2026-08-01", "to": "2026-08-31"}},
            }
            filtered_body = require_success(client.request("POST", "/api/query", filtered), "/api/query")
            filtered_page = page_from(filtered_body, contract_group)
            result[source_key] = {
                "status": "PASS",
                "page_1_count": first_page.get("count"),
                "page_1_displayed": first_page.get("displayed"),
                "page_2_count": second_page.get("count"),
                "filter_count": filtered_page.get("count"),
                "detail_row_present": bool(first_page["data"] and isinstance(first_page["data"][0], dict)),
                "backend": first.get("backend"),
            }
            if not result[source_key]["detail_row_present"]:
                raise RuntimeError(f"{source_key}: no display/detail row returned")
    if seen_sources != EXPECTED_SOURCES:
        raise RuntimeError(f"source journey mismatch: {sorted(seen_sources)}")
    return result


def probe_value(field: dict[str, Any]) -> dict[str, Any]:
    name = field["name"]
    if name == "partition_date":
        return {"eq": "2026-08-31"}
    if field["type"] in {"float", "int32"}:
        return {"min": 0}
    return {"eq": "__early_user_smoke__"}


def contract_smoke(client: SmokeClient, contract: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    counts = {"searchable": 0, "filterable": 0, "sortable": 0, "autocomplete": 0}
    for group, group_contract in contract["groups"].items():
        api_group = API_GROUP[group]
        for field in group_contract["fields"]:
            name = field["name"]
            if field["searchable"]:
                counts["searchable"] += 1
                body = {"group": api_group, "text": "__early_user_smoke__", "searchFields": [name], "limit": 1}
                result = client.request("POST", "/api/query", body)
                if not 200 <= result.status < 300:
                    failures.append({"kind": "searchable", "group": group, "field": name, "status": str(result.status)})
            if field["filterable"]:
                counts["filterable"] += 1
                body = {"group": api_group, "structuredFilters": {name: probe_value(field)}, "limit": 1}
                result = client.request("POST", "/api/query", body)
                if not 200 <= result.status < 300:
                    failures.append({"kind": "filterable", "group": group, "field": name, "status": str(result.status)})
            if field["sortable"]:
                counts["sortable"] += 1
                body = {"group": api_group, "sort": [{"column": name, "order": "asc"}], "limit": 1}
                result = client.request("POST", "/api/query", body)
                if not 200 <= result.status < 300:
                    failures.append({"kind": "sortable", "group": group, "field": name, "status": str(result.status)})
        for name in group_contract["autocomplete_fields"]:
            counts["autocomplete"] += 1
            body = {"group": api_group, "field": name, "keyword": "a", "limit": 3}
            result = client.request("POST", "/api/autocomplete", body)
            if not 200 <= result.status < 300:
                failures.append({"kind": "autocomplete", "group": group, "field": name, "status": str(result.status)})
    if failures:
        raise RuntimeError(f"field contract failures: {failures[:5]}")
    return {"status": "PASS", "counts": counts, "failures": failures}


def timed_requests(client: SmokeClient, path: str, payload: dict[str, Any], repeats: int = 5) -> dict[str, Any]:
    timings: list[float] = []
    for _ in range(repeats):
        result = client.request("POST", path, payload)
        require_success(result, path)
        timings.append(result.elapsed_ms)
    ordered = sorted(timings)
    p95 = ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))]
    return {
        "status": "PASS",
        "samples": len(timings),
        "p50_ms": round(statistics.median(timings), 3),
        "p95_ms": round(p95, 3),
        "max_ms": round(max(timings), 3),
    }


def performance_smoke(client: SmokeClient, contract: dict[str, Any]) -> dict[str, Any]:
    autocomplete_field = contract["groups"]["goods"]["autocomplete_fields"][0]
    return {
        "search": timed_requests(client, "/api/query", {"group": "goods", "text": "", "limit": 1}),
        "filter": timed_requests(client, "/api/query", {"group": "goods", "dateRanges": {"partition_date": {"from": "2026-08-01", "to": "2026-08-31"}}, "limit": 1}),
        "sort": timed_requests(client, "/api/query", {"group": "goods", "sort": [{"column": "quantity", "order": "desc"}], "limit": 1}),
        "autocomplete": timed_requests(client, "/api/autocomplete", {"group": "goods", "field": autocomplete_field, "keyword": "a", "limit": 3}),
    }


def concurrent_level(client: SmokeClient, level: int) -> dict[str, Any]:
    payload = {"group": "goods", "text": "", "limit": 1}

    def run_one(_: int) -> tuple[bool, float]:
        try:
            result = client.request("POST", "/api/query", payload)
            return 200 <= result.status < 300 and result.body.get("success") is not False, result.elapsed_ms
        except Exception:
            return False, client.timeout * 1000

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=level) as executor:
        outcomes = list(executor.map(run_one, range(level)))
    timings = sorted(item[1] for item in outcomes)
    p95 = timings[min(len(timings) - 1, max(0, int(len(timings) * 0.95) - 1))]
    return {
        "clients": level,
        "requests": len(outcomes),
        "errors": sum(not item[0] for item in outcomes),
        "error_rate": round(sum(not item[0] for item in outcomes) / len(outcomes), 4),
        "p95_ms": round(p95, 3),
        "wall_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--skip-contract", action="store_true")
    args = parser.parse_args()
    client = SmokeClient(args.base_url, args.timeout)
    report: dict[str, Any] = {"base_url": client.base_url, "started_at_epoch": time.time()}
    health = client.request("GET", "/health")
    ready = client.request("GET", "/ready")
    report["health"] = {"status": health.status, "body": health.body}
    report["ready"] = {"status": ready.status, "body": ready.body}
    contract_result = require_success(client.request("GET", "/api/search-contract"), "/api/search-contract")
    contract = contract_result["contract"]
    if not args.skip_contract:
        report["journeys"] = journey_smoke(client, contract)
        report["field_contract"] = contract_smoke(client, contract)
    report["performance"] = performance_smoke(client, contract)
    report["concurrency"] = [concurrent_level(client, level) for level in (1, 5, 10)]
    report["finished_at_epoch"] = time.time()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"SMOKE_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
