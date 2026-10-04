#!/usr/bin/env python3
"""Read-only discovery of the one validated BIDFinder serving state."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

GENERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def read_state(report: Path) -> dict[str, str]:
    payload = json.loads(report.read_text(encoding="utf-8"))
    generation = str(payload.get("serving_generation", "")).strip()
    if not GENERATION_RE.fullmatch(generation):
        raise ValueError(f"invalid serving generation in {report}")
    if payload.get("overall_status") not in {None, "PASS"}:
        raise ValueError(f"serving report is not PASS: {report}")
    root = report.parent.parent
    values = {
        "generation": generation,
        "checkpoint": str(root / "checkpoints" / f"{generation}.sqlite3"),
        "provenance": str(root / "checkpoints" / f"{generation}.uuid.sqlite3"),
        "report": str(report),
        "markdown": str(report.with_suffix(".md")),
    }
    for key in ("checkpoint", "provenance", "report"):
        if not Path(values[key]).is_file():
            raise FileNotFoundError(values[key])
    return values


def discover(reports_root: Path, requested: Path | None) -> dict[str, str]:
    if requested:
        return read_state(requested)
    candidates = []
    for report in sorted(reports_root.glob("serving-state-*.json")):
        try:
            candidates.append(read_state(report))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one validated serving report, found {len(candidates)}")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-root", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        state = discover(args.reports_root, args.report)
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed with a short message.
        print(f"serving-state: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(state, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
