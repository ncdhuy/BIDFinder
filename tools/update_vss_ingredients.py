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


def last_published_date(data_root: Path, manifest: ManifestStore) -> date | None:
    status_file = data_root / "vss_refresh_status.json"
    if status_file.exists():
        payload = json.loads(status_file.read_text(encoding="utf-8"))
        return date.fromisoformat(payload["published_through"])
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


def crawl(data_root: Path, start: date, end: date, *, force: bool) -> None:
    command = [
        sys.executable, str(SOURCE_SCRIPT),
        "--start-date", start.isoformat(), "--end-date", end.isoformat(),
        "--raw-dir", str(data_root / "downloads"),
        "--manifest-file", str(data_root / "crawl_manifest.csv"),
        "--log-file", str(data_root / "download_log.log"),
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
    parser.add_argument("--plan", action="store_true", help="Print the crawl window without changing data")
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    raw_dir = data_root / "downloads"
    if not raw_dir.is_dir():
        parser.error(f"eLMIS XML directory is missing: {raw_dir}")

    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    manifest_path = data_root / "crawl_manifest.csv"
    manifest = ManifestStore(manifest_path, raw_dir)
    start, recent_start = crawl_window(today, last_published_date(data_root, manifest), args.lookback_days)
    print(json.dumps({"start": start.isoformat(), "recent_start": recent_start.isoformat(), "through": today.isoformat()}), flush=True)
    if args.plan:
        return

    if start < recent_start:
        crawl(data_root, start, recent_start - timedelta(days=1), force=False)
    crawl(data_root, recent_start, today, force=True)
    manifest = ManifestStore(manifest_path, raw_dir)
    validate_crawl(manifest, start, today)

    counts = aggregate_xml(raw_dir)
    client = typesense_client_from_env()
    collection = import_counts(client, counts)
    status_file = data_root / "vss_refresh_status.json"
    temporary = status_file.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({
        "published_through": today.isoformat(), "collection": collection,
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
