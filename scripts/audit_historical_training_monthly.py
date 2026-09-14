"""Verify the completeness and integrity of archived monthly KRA training pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from collect_historical_training_monthly import _items, months_between

from horse_racing.collectors.kra_api import response_body
from horse_racing.config import get_settings
from horse_racing.parsers.horse_history import parse_meet_code


def audit(dataset: str, starts: dict[int, str], end: str) -> dict:
    root = get_settings().raw_data_dir / "kra_api_monthly" / dataset
    manifest_path = root / "manifest.jsonl"
    manifest: dict[str, dict] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        manifest[event["path"]] = event

    results: dict[str, dict] = {}
    for meet, start in sorted(starts.items()):
        rows = 0
        months_nonempty = 0
        pages = 0
        first_date: str | None = None
        last_date: str | None = None
        horse_ids: set[str] = set()
        field_nonnull: Counter[str] = Counter()
        year_rows: Counter[str] = Counter()
        year_field_nonnull: dict[str, Counter[str]] = defaultdict(Counter)
        duplicate_keys = 0
        exact_duplicate_keys = 0
        duplicate_examples: list[dict] = []
        for month in months_between(start, end):
            folder = root / f"meet_{meet}" / month
            first_path = folder / "page_0001.json"
            if not first_path.is_file():
                raise ValueError(f"Missing month: {meet} {month}")
            first_payload = json.loads(first_path.read_bytes())
            first_body = response_body(first_payload)
            total_count = int(first_body.get("totalCount") or 0)
            page_size = int(first_body.get("numOfRows") or 20000)
            expected_pages = max(1, math.ceil(total_count / max(page_size, 1)))
            paths = sorted(folder.glob("page_*.json"))
            if len(paths) != expected_pages:
                raise ValueError(f"Page count mismatch: {meet} {month}")
            month_rows = 0
            seen_keys: dict[tuple, dict] = {}
            for page_no, path in enumerate(paths, 1):
                if path.name != f"page_{page_no:04d}.json":
                    raise ValueError(f"Page sequence gap: {meet} {month}")
                raw = path.read_bytes()
                event = manifest.get(str(path))
                if event is None or event["sha256"] != hashlib.sha256(raw).hexdigest():
                    raise ValueError(f"Manifest hash mismatch: {path}")
                body = response_body(json.loads(raw))
                if int(body.get("totalCount") or 0) != total_count:
                    raise ValueError(f"Changing totalCount: {path}")
                for item in _items(json.loads(raw)):
                    if not isinstance(item, dict):
                        raise ValueError(f"Malformed item: {path}")
                    date = str(item.get("trDate", ""))
                    horse_id = str(item.get("hrNo", "")).strip()
                    if not date.startswith(month) or not horse_id:
                        raise ValueError(f"Invalid date or horse ID: {path}")
                    if parse_meet_code(item.get("meet")) != meet:
                        raise ValueError(f"Wrong racecourse: {path}")
                    key = (
                        horse_id,
                        date,
                        str(item.get("stTime", "")),
                        str(item.get("spTime", "")),
                        str(item.get("prName", "")),
                        str(item.get("remark", "")),
                    )
                    if key in seen_keys:
                        duplicate_keys += 1
                        same_payload = seen_keys[key] == item
                        exact_duplicate_keys += same_payload
                        if len(duplicate_examples) < 10:
                            duplicate_examples.append(
                                {
                                    "month": month,
                                    "horse_id": horse_id,
                                    "training_date": date,
                                    "same_payload": same_payload,
                                    "first": seen_keys[key],
                                    "second": item,
                                }
                            )
                    else:
                        seen_keys[key] = item
                    horse_ids.add(horse_id)
                    first_date = min(first_date, date) if first_date else date
                    last_date = max(last_date, date) if last_date else date
                    for field in (
                        "hrName",
                        "trName",
                        "trTerm",
                        "run1Cnt",
                        "run2Cnt",
                        "stTime",
                        "spTime",
                    ):
                        if item.get(field) not in (None, ""):
                            field_nonnull[field] += 1
                            year_field_nonnull[month[:4]][field] += 1
                    month_rows += 1
                pages += 1
            if month_rows != total_count:
                raise ValueError(f"Row count mismatch: {meet} {month}")
            rows += month_rows
            year_rows[month[:4]] += month_rows
            months_nonempty += month_rows > 0
        results[str(meet)] = {
            "start_scanned": start,
            "end_scanned": end,
            "months_scanned": len(months_between(start, end)),
            "months_nonempty": months_nonempty,
            "pages": pages,
            "rows": rows,
            "unique_horse_ids": len(horse_ids),
            "first_record_date": first_date,
            "last_record_date": last_date,
            "duplicate_keys": duplicate_keys,
            "exact_duplicate_keys": exact_duplicate_keys,
            "duplicate_examples": duplicate_examples,
            "field_nonnull": dict(field_nonnull),
            "year_rows": dict(sorted(year_rows.items())),
            "year_field_nonnull": {
                year: dict(counts) for year, counts in sorted(year_field_nonnull.items())
            },
        }
    return {"dataset": dataset, "source_manifest": str(manifest_path), "meets": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=["horse_training", "start_training"], required=True)
    parser.add_argument("--start", action="append", required=True, help="MEET:YYYYMM")
    parser.add_argument("--end", required=True, help="YYYYMM")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    starts = {int(meet): month for meet, month in (value.split(":") for value in args.start)}
    result = audit(args.dataset, starts, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({meet: x["rows"] for meet, x in result["meets"].items()}))


if __name__ == "__main__":
    main()
