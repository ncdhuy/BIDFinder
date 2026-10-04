"""Portable local Typesense paths and safety checks.

WSL/Windows process control belongs to the operator script.  This module keeps
the ingestion core usable on a normal Linux host later.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
import os
from pathlib import Path
import shutil
from typing import Any

from .config import TypesenseConfig
from .typesense_schema import validate_generation_id

LOCAL_TYPESENSE_VERSION = "30.2"
LOCAL_TYPESENSE_HOST = "127.0.0.1"
LOCAL_TYPESENSE_PORT = 8108
LOCAL_TYPESENSE_PROTOCOL = "http"
LOCAL_TYPESENSE_ROOT_ENV = "BIDFINDER_TYPESENSE_ROOT"
DEFAULT_LOCAL_TYPESENSE_ROOT = Path.home() / ".local" / "share" / "bidfinder" / "typesense"
FUTURE_HISTORICAL_GENERATION = "hist_v1_20260829"
FULL_RUN_AUTHORIZATION_PHRASE = "AUTHORIZE_PHASE_3B_HISTORICAL_BACKFILL"

# Phase 3B-S empirical policy.  These values are estimates, not a claim that
# a future full backfill is authorized.
PROJECTED_FULL_GENERATION_BYTES = 21_795_541_726
PROJECTED_TWO_GENERATIONS_BYTES = 43_591_083_452
OPERATIONAL_FREE_MARGIN_BYTES = 76_284_396_040
FREE_WARNING_FRACTION = 0.35
FREE_CRITICAL_FRACTION = 0.20
NEW_GENERATION_MIN_FREE_FRACTION = 0.50

EXPECTED_HISTORICAL_SOURCE_TOTALS = {
    "goods_general": 8_219_252,
    "medical_devices": 964_685,
    "medicine_generic": 494_698,
    "medicine_originator": 55_239,
    "medicine_herbal": 35_489,
    "herbal_material": 9_554,
    "traditional_medicine": 22_468,
}


@dataclass(frozen=True)
class LocalTargetPaths:
    """Separate persistent data and operational artifact locations."""

    root: Path
    data_dir: Path
    snapshots_dir: Path
    checkpoints_dir: Path
    reports_dir: Path
    logs_dir: Path
    run_dir: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "data_dir": str(self.data_dir),
            "snapshots_dir": str(self.snapshots_dir),
            "checkpoints_dir": str(self.checkpoints_dir),
            "reports_dir": str(self.reports_dir),
            "logs_dir": str(self.logs_dir),
            "run_dir": str(self.run_dir),
        }


def local_target_paths(
    root: str | Path | None = None,
    *,
    repo_root: str | Path | None = None,
    create: bool = False,
) -> LocalTargetPaths:
    """Return safe, generation-independent local runtime paths."""

    requested = root or os.getenv(LOCAL_TYPESENSE_ROOT_ENV) or DEFAULT_LOCAL_TYPESENSE_ROOT
    resolved_root = Path(requested).expanduser().resolve()
    if repo_root is not None:
        resolved_repo = Path(repo_root).expanduser().resolve()
        if resolved_root == resolved_repo or resolved_root.is_relative_to(resolved_repo):
            raise ValueError("local Typesense runtime root must be outside the repository")
    paths = LocalTargetPaths(
        resolved_root,
        resolved_root / "data",
        resolved_root / "snapshots",
        resolved_root / "checkpoints",
        resolved_root / "reports",
        resolved_root / "logs",
        resolved_root / "run",
    )
    if create:
        for path in (
            paths.root,
            paths.data_dir,
            paths.snapshots_dir,
            paths.checkpoints_dir,
            paths.reports_dir,
            paths.logs_dir,
            paths.run_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
    return paths


def local_generation_artifacts(paths: LocalTargetPaths, generation: str) -> dict[str, Path]:
    """Return generation-aware checkpoint, UUID, report, and snapshot paths."""

    validate_generation_id(generation)
    return {
        "checkpoint": paths.checkpoints_dir / f"{generation}.sqlite3",
        "uuid_audit": paths.checkpoints_dir / f"{generation}.uuid.sqlite3",
        "report": paths.reports_dir / f"{generation}.json",
        "snapshot": paths.snapshots_dir / f"{generation}.snapshot",
    }

def is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def validate_local_typesense_config(config: TypesenseConfig) -> None:
    """Reject non-local or TLS local modes before an operator starts a node."""

    if not is_loopback_host(config.host):
        raise ValueError("local Typesense target must bind to a loopback host")
    if config.protocol != LOCAL_TYPESENSE_PROTOCOL:
        raise ValueError("local Typesense target must use HTTP on loopback")
    if config.port != LOCAL_TYPESENSE_PORT:
        raise ValueError(f"local Typesense target must use port {LOCAL_TYPESENSE_PORT}")


def local_capacity_preflight(
    paths: LocalTargetPaths,
    *,
    projected_generation_bytes: int = PROJECTED_FULL_GENERATION_BYTES,
    two_generation_bytes: int = PROJECTED_TWO_GENERATIONS_BYTES,
    operational_margin_bytes: int = OPERATIONAL_FREE_MARGIN_BYTES,
) -> dict[str, Any]:
    """Apply Phase 3B-S disk policy without counting swap as capacity."""

    usage = shutil.disk_usage(paths.root)
    free_fraction = usage.free / usage.total if usage.total else 0.0
    required_for_new_generation = two_generation_bytes + operational_margin_bytes
    return {
        "decision": "PASS" if usage.free >= required_for_new_generation else "FAIL",
        "path": str(paths.root),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_fraction": round(free_fraction, 6),
        "projected_full_generation_bytes": projected_generation_bytes,
        "projected_two_generation_bytes": two_generation_bytes,
        "operational_free_margin_bytes": operational_margin_bytes,
        "required_free_bytes_for_new_generation": required_for_new_generation,
        "warning": free_fraction < FREE_WARNING_FRACTION,
        "critical": free_fraction < FREE_CRITICAL_FRACTION,
        "new_generation_blocked": free_fraction < NEW_GENERATION_MIN_FREE_FRACTION,
        "policy": {
            "warning_below_free_fraction": FREE_WARNING_FRACTION,
            "critical_below_free_fraction": FREE_CRITICAL_FRACTION,
            "block_new_generation_below_free_fraction": NEW_GENERATION_MIN_FREE_FRACTION,
        },
    }


def historical_source_count_deltas(actual: dict[str, int]) -> dict[str, dict[str, int | bool]]:
    """Compare revalidated MSC aggregation counts to the Phase 3B-R manifest."""

    return {
        key: {
            "previous": EXPECTED_HISTORICAL_SOURCE_TOTALS[key],
            "actual": int(actual[key]),
            "delta": int(actual[key]) - EXPECTED_HISTORICAL_SOURCE_TOTALS[key],
            "unchanged": int(actual[key]) == EXPECTED_HISTORICAL_SOURCE_TOTALS[key],
        }
        for key in EXPECTED_HISTORICAL_SOURCE_TOTALS
    }
