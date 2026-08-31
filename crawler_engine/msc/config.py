"""Configuration and safe defaults for the MSC ingestion engine."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

MSC_SEARCH_ENDPOINT = (
    "https://muasamcong.mpi.gov.vn/"
    "o/egp-portal-winning-bid-data/services/smart/search_prc"
)
SEARCH_RESULT_WINDOW = 10_000
MAX_SAFE_SEARCH_RESULTS = 9_500
SEARCH_PAGE_SIZE = 1_000
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_REQUEST_DELAY_SECONDS = 1.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
DEFAULT_MAX_PARTITION_DEPTH = 16
DEFAULT_PARTITION_OVERLAP_SECONDS = 1.0
DEFAULT_MINIMUM_PARTITION_SPAN_MILLISECONDS = 1
DEFAULT_TYPESENSE_HOST = "127.0.0.1"
DEFAULT_TYPESENSE_PORT = 8108
DEFAULT_TYPESENSE_PROTOCOL = "http"
DEFAULT_TYPESENSE_TIMEOUT_SECONDS = 10.0
DEFAULT_TYPESENSE_BATCH_SIZE = 500
ENGINE_VERSION = "msc-ingestion-v1"
SCHEMA_VERSION = "msc-source-schema-v1"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHECKPOINT_PATH = _REPO_ROOT / "crawler_engine" / ".msc_state" / "checkpoints.sqlite3"
DEFAULT_OUTPUT_DIR = _REPO_ROOT / "crawler_engine" / "msc-output"


@dataclass(frozen=True)
class MSCConfig:
    """Validated runtime knobs; V1 intentionally stays sequential."""

    endpoint: str = MSC_SEARCH_ENDPOINT
    page_size: int = SEARCH_PAGE_SIZE
    max_safe_results: int = MAX_SAFE_SEARCH_RESULTS
    result_window: int = SEARCH_RESULT_WINDOW
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS
    max_partition_depth: int = DEFAULT_MAX_PARTITION_DEPTH
    partition_overlap_seconds: float = DEFAULT_PARTITION_OVERLAP_SECONDS
    minimum_partition_span_milliseconds: int = DEFAULT_MINIMUM_PARTITION_SPAN_MILLISECONDS

    def __post_init__(self) -> None:
        if self.endpoint != MSC_SEARCH_ENDPOINT:
            raise ValueError("MSC endpoint must be the public /search_prc endpoint")
        if self.page_size <= 0 or self.page_size > self.result_window:
            raise ValueError("page_size must be positive and within result window")
        if self.max_safe_results <= 0 or self.max_safe_results > self.result_window:
            raise ValueError("max_safe_results must be within result window")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.request_delay_seconds < 0:
            raise ValueError("request_delay_seconds cannot be negative")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")
        if self.max_partition_depth < 0:
            raise ValueError("max_partition_depth cannot be negative")
        if self.partition_overlap_seconds <= 0:
            raise ValueError("partition_overlap_seconds must be positive")
        if self.minimum_partition_span_milliseconds <= 0:
            raise ValueError("minimum_partition_span_milliseconds must be positive")


@dataclass(frozen=True)
class TypesenseConfig:
    """Standard Typesense transport settings; never shares MSC TLS settings."""

    host: str = DEFAULT_TYPESENSE_HOST
    port: int = DEFAULT_TYPESENSE_PORT
    protocol: str = DEFAULT_TYPESENSE_PROTOCOL
    api_key: str = field(default="", repr=False)
    timeout_seconds: float = DEFAULT_TYPESENSE_TIMEOUT_SECONDS
    batch_size: int = DEFAULT_TYPESENSE_BATCH_SIZE

    def __post_init__(self) -> None:
        if not self.host or "://" in self.host or "/" in self.host:
            raise ValueError("TYPESENSE_HOST must be a hostname or IP address without a scheme or path")
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise ValueError("TYPESENSE_PORT must be between 1 and 65535")
        if self.protocol not in {"http", "https"}:
            raise ValueError("TYPESENSE_PROTOCOL must be http or https")
        if not self.api_key:
            raise ValueError("TYPESENSE_API_KEY is required for Typesense operations")
        if self.timeout_seconds <= 0:
            raise ValueError("TYPESENSE_TIMEOUT_SECONDS must be positive")
        if self.batch_size <= 0:
            raise ValueError("TYPESENSE_IMPORT_BATCH_SIZE must be positive")

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"

    @classmethod
    def from_env(cls) -> "TypesenseConfig":
        """Load only Typesense variables; no Postgres or MSC settings are reused."""

        return cls(
            host=os.getenv("TYPESENSE_HOST", DEFAULT_TYPESENSE_HOST),
            port=int(os.getenv("TYPESENSE_PORT", str(DEFAULT_TYPESENSE_PORT))),
            protocol=os.getenv("TYPESENSE_PROTOCOL", DEFAULT_TYPESENSE_PROTOCOL).lower(),
            api_key=os.getenv("TYPESENSE_API_KEY", ""),
            timeout_seconds=float(os.getenv("TYPESENSE_TIMEOUT_SECONDS", os.getenv("TYPESENSE_CONNECTION_TIMEOUT_SECONDS", str(DEFAULT_TYPESENSE_TIMEOUT_SECONDS)))),
            batch_size=int(os.getenv("TYPESENSE_IMPORT_BATCH_SIZE", os.getenv("TYPESENSE_BATCH_SIZE", str(DEFAULT_TYPESENSE_BATCH_SIZE)))),
        )
