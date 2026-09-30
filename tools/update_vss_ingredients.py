"""Refresh the eLMIS lookup from raw XML once per day."""

import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

from import_vss_ingredients import (
    COLLECTION_ALIAS,
    aggregate_xml,
    import_counts,
    typesense_client_from_env,
)
from crawler_engine.vss.download_vss_data import ManifestStore, iter_dates


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = ROOT / "crawler_engine" / "vss_data"
SOURCE_SCRIPT = ROOT / "crawler_engine" / "vss" / "download_vss_data.py"
CATEGORIES = (1, 2, 3, 4)
HISTORY_START = date(2022, 1, 1)


def manifest_path(data_root: Path, loai: int) -> Path:
    return data_root / ("crawl_manifest.csv" if loai == 1 else f"crawl_manifest_{loai}.csv")


def last_published_date(data_root: Path, manifest: ManifestStore, loai: int) -> date | None:
    status_file = data_root / "vss_refresh_status.json"
    if status_file.exists():
        payload = json.loads(status_file.read_text(encoding="utf-8"))
        by_category = payload.get("published_through_by_loai", {})
        if str(loai) in by_category:
            return date.fromisoformat(by_category[str(loai)])
        if loai == 1 and payload.get("published_through"):
            return date.fromisoformat(payload["published_through"])
    if loai != 1:
        return None
    available = (
        date.fromisoformat(day) for day, row in manifest.rows.items()
        if row.get("status") in {"downloaded", "existing"}
        and row.get("raw_path") and Path(row["raw_path"]).exists()
    )
    return max(available, default=None)


def crawl_window(today: date, last_published: date | None, lookback_days: int) -> tuple[date, date]:
    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")
    recent_start = today - timedelta(days=lookback_days - 1)
    start = min(recent_start, last_published + timedelta(days=1)) if last_published else recent_start
    return start, recent_start


def crawl(data_root: Path, start: date, end: date, *, loai: int, force: bool) -> None:
    command = [
        sys.executable, str(SOURCE_SCRIPT),
        "--start-date", start.isoformat(), "--end-date", end.isoformat(),
        "--loai", str(loai),
        "--raw-dir", str(data_root / "downloads"),
        "--manifest-file", str(manifest_path(data_root, loai)),
        "--log-file", str(data_root / f"download_log_{loai}.log"),
    ]
    if force:
        command.append("--force")
    subprocess.run(command, check=True)


def validate_crawl(manifest: ManifestStore, start: date, end: date) -> None:
    failed = []
    for day in iter_dates(start, end):
        row = manifest.rows.get(day.isoformat(), {})
        path = Path(row["raw_path"]) if row.get("raw_path") else None
        if row.get("status") not in {"downloaded", "existing"} or not path or not path.is_file() or not path.stat().st_size:
            failed.append(day.isoformat())
    if failed:
        raise RuntimeError(f"eLMIS crawl incomplete for: {', '.join(failed)}")


def prune_old_collections(client, retain: int = 3) -> None:
    alias = client.get_alias(COLLECTION_ALIAS)
    if not alias:
        return
    active = alias["collection_name"]
    versions = sorted(
        (item for item in client.list_collections() if item["name"].startswith(f"{COLLECTION_ALIAS}_")),
        key=lambda item: (item.get("created_at", 0), item["name"]), reverse=True,
    )
    keep = {active}
    for item in versions:
        if len(keep) >= retain:
            break
        keep.add(item["name"])
    for item in versions:
        if item["name"] not in keep:
            client.delete_collection(item["name"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path(os.getenv("BIDFINDER_VSS_DATA_ROOT", DEFAULT_DATA_ROOT)))
    parser.add_argument("--lookback-days", type=int, default=3)
    parser.add_argument("--history-start", type=date.fromisoformat, default=HISTORY_START,
                        help="First publication date to backfill for new categories")
    parser.add_argument("--plan", action="store_true", help="Print the crawl window without changing data")
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    raw_dir = data_root / "downloads"
    if not raw_dir.is_dir():
        parser.error(f"eLMIS XML directory is missing: {raw_dir}")

    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    windows = {}
    for loai in CATEGORIES:
        manifest = ManifestStore(manifest_path(data_root, loai), raw_dir, loai=loai)
        published = last_published_date(data_root, manifest, loai)
        start, recent_start = crawl_window(today, published, args.lookback_days)
        if published is None and loai != 1:
            start = min(args.history_start, recent_start)
        windows[loai] = (start, recent_start)
    print(json.dumps({"windows": {str(loai): {"start": start.isoformat(), "recent_start": recent.isoformat()}
                                  for loai, (start, recent) in windows.items()}, "through": today.isoformat()}), flush=True)
    if args.plan:
        return

    for loai, (start, recent_start) in windows.items():
        if start < recent_start:
            crawl(data_root, start, recent_start - timedelta(days=1), loai=loai, force=False)
        crawl(data_root, recent_start, today, loai=loai, force=True)
        manifest = ManifestStore(manifest_path(data_root, loai), raw_dir, loai=loai)
        validate_crawl(manifest, start, today)

    counts = aggregate_xml(raw_dir)
    client = typesense_client_from_env()
    collection = import_counts(client, counts)
    status_file = data_root / "vss_refresh_status.json"
    temporary = status_file.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({
        "published_through": today.isoformat(), "collection": collection,
        "published_through_by_loai": {str(loai): today.isoformat() for loai in CATEGORIES},
        "source_rows": sum(counts.values()), "grouped_rows": len(counts),
        "published_at": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(),
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(status_file)
    print(f"Published {collection}: {sum(counts.values())} source rows, {len(counts)} groups", flush=True)
    try:
        prune_old_collections(client)
    except Exception as exc:
        print(f"Old eLMIS collection cleanup failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
