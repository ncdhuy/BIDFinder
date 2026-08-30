"""Anonymous public MSC ``/search_prc`` transport."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from http.client import IncompleteRead
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import MSCConfig
from .models import SearchInterval, SourceContract
from .tls import create_msc_ssl_context
from .validation import parse_search_count

LOGGER = logging.getLogger(__name__)
USER_AGENT = "BIDFinder-msc-ingestion/1.0"
_ISO_BOUND_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class MSCClientError(RuntimeError):
    code = "MSC_HTTP_ERROR"


class MSCNetworkError(MSCClientError):
    pass


class MSCResponseError(MSCClientError):
    code = "MSC_CONTRACT_ERROR"


class MSCHttpError(MSCClientError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


@dataclass
class ClientStats:
    request_count: int = 0
    retry_count: int = 0
    http_error_count: int = 0
    elapsed_seconds: float = 0.0


def _msc_urlopen(request: Request, *, timeout: float) -> Any:
    return urlopen(request, timeout=timeout, context=create_msc_ssl_context())


def _validate_bound(value: str) -> None:
    if not isinstance(value, str) or not _ISO_BOUND_RE.fullmatch(value):
        raise ValueError("MSC interval bounds must use YYYY-MM-DDTHH:MM:SS.mmmZ")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except (TypeError, ValueError) as exc:
        raise ValueError("MSC interval bounds must use YYYY-MM-DDTHH:MM:SS.mmmZ") from exc


def build_search_request(
    contract: SourceContract,
    from_value: str,
    to_value: str,
    page_number: int,
    page_size: int,
    *,
    keyword: str = "",
    keyword_not_match: str = "",
) -> list[dict[str, Any]]:
    """Build the one verified MSC request shape used by every production call."""

    _validate_bound(from_value)
    _validate_bound(to_value)
    if datetime.strptime(from_value, "%Y-%m-%dT%H:%M:%S.%fZ") >= datetime.strptime(to_value, "%Y-%m-%dT%H:%M:%S.%fZ"):
        raise ValueError("MSC interval must have from < to")
    if page_number < 0 or page_size <= 0:
        raise ValueError("page_number must be non-negative and page_size must be positive")
    query = {
        "index": contract.request_index,
        "keyWord": keyword,
        "keyWordNotMatch": keyword_not_match,
        "matchType": "all-1",
        "matchFields": list(contract.match_fields),
        "filters": [
            {
                "fieldName": contract.date_filter,
                "searchType": "range",
                "from": from_value,
                "to": to_value,
            },
            *(item.to_dict() for item in contract.fixed_filters),
        ],
    }
    return [{"pageSize": page_size, "pageNumber": page_number, "query": [query]}]


class MSCClient:
    """Sequential, paced, bounded-retry public-search client."""

    def __init__(
        self,
        config: MSCConfig | None = None,
        *,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or MSCConfig()
        self._opener = opener or _msc_urlopen
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None
        self.stats = ClientStats()

    def _pace(self) -> None:
        if self._last_request_at is not None:
            wait = self.config.request_delay_seconds - (self._monotonic() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._monotonic()

    def _post(self, payload: list[dict[str, Any]]) -> Any:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        started = self._monotonic()
        last_network_error: str | None = None
        for attempt in range(self.config.max_retries + 1):
            self._pace()
            self.stats.request_count += 1
            request = Request(
                self.config.endpoint,
                data=body,
                method="POST",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                with self._opener(request, timeout=self.config.timeout_seconds) as response:
                    status = getattr(response, "status", 200)
                    raw = response.read()
            except HTTPError as exc:
                self.stats.http_error_count += 1
                status = exc.code
                raw = exc.read()
                if status not in {429, *range(500, 600)}:
                    raise MSCHttpError(status, f"MSC HTTP {status}") from None
                if attempt >= self.config.max_retries:
                    raise MSCHttpError(status, f"MSC HTTP {status} after bounded retries") from None
                self._retry_wait(attempt, status)
                continue
            except (IncompleteRead, TimeoutError, URLError, OSError) as exc:
                last_network_error = f"{type(exc).__name__}: {exc}"
                if attempt >= self.config.max_retries:
                    detail = f" ({last_network_error})" if last_network_error else ""
                    raise MSCNetworkError(f"MSC network failure after bounded retries{detail}") from exc
                self._retry_wait(attempt, 0)
                continue
            self.stats.elapsed_seconds += self._monotonic() - started
            if status != 200:
                self.stats.http_error_count += 1
                if status in {429, *range(500, 600)} and attempt < self.config.max_retries:
                    self._retry_wait(attempt, status)
                    continue
                raise MSCHttpError(status, f"MSC HTTP {status}")
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise MSCResponseError("MSC response is not valid JSON") from exc
        detail = f" ({last_network_error})" if last_network_error else ""
        raise MSCNetworkError(f"MSC request failed after bounded retries{detail}")

    def _retry_wait(self, attempt: int, status: int) -> None:
        self.stats.retry_count += 1
        delay = self.config.retry_backoff_seconds * (2**attempt)
        LOGGER.warning("msc_retry attempt=%s status=%s backoff_seconds=%s", attempt + 1, status or "network", delay)
        if delay:
            self._sleep(delay)

    def fetch_page(self, contract: SourceContract, interval: SearchInterval, page_number: int) -> dict[str, Any]:
        payload = build_search_request(
            contract, interval.from_value, interval.to_value, page_number, self.config.page_size
        )
        response = self._post(payload)
        if not isinstance(response, dict):
            raise MSCResponseError("MSC response must be a JSON object")
        return response

    def count_interval(self, contract: SourceContract, interval: SearchInterval) -> int:
        return parse_search_count(self.fetch_page(contract, interval, 0))
