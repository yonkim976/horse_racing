"""Extract training rows for confirmed native Jeju racers from archived API pages."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path


def _horse_id(value: object) -> str | None:
    try:
        return str(int(str(value)))
    except (TypeError, ValueError):
        return None


def confirmed_native_ids(results_dir: Path, database: Path) -> set[str]:
    ids: set[str] = set()
    for path in sorted(results_dir.glob("native_results_*.jsonl")):
        for line in path.open(encoding="utf-8"):
            horse_id = _horse_id(json.loads(line).get("hrNo"))
            if horse_id is None:
                raise ValueError(f"Missing horse ID in {path}")
            ids.add(horse_id)
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            """SELECT DISTINCT h.kra_horse_id
               FROM race_entries AS e
               JOIN races AS r ON r.id=e.race_id
               JOIN racecourses AS c ON c.id=r.racecourse_id
               JOIN horses AS h ON h.id=e.horse_id
               WHERE c.kra_meet_code=2 AND r.status='completed'"""
        )
        ids.update(horse_id for row in rows if (horse_id := _horse_id(row[0])))
    if not ids:
        raise ValueError("No confirmed native horse IDs")
    return ids


def _items(payload: dict) -> list[dict]:
    body = payload["response"]["body"]
    wrapper = body.get("items") or {}
    value = wrapper.get("item") if isinstance(wrapper, dict) else None
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("Unexpected training item structure")
    return value


def materialize(*, dataset: str, ids: set[str], raw_root: Path, output_root: Path) -> dict:
    source = raw_root / "kra_api_monthly" / dataset / "meet_2"
    paths = sorted(source.glob("*/page_*.json"))
    if not paths:
        raise ValueError(f"No archived pages: {source}")
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"{dataset}_confirmed_native.jsonl.gz"
    counts: Counter[str] = Counter()
    native_dates: list[int] = []
    source_sha256 = hashlib.sha256()
    with tempfile.NamedTemporaryFile(dir=output_root, delete=False) as stream:
        temporary = Path(stream.name)
        with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed:
            for path in paths:
                source_bytes = path.read_bytes()
                source_sha256.update(path.relative_to(source).as_posix().encode())
                source_sha256.update(hashlib.sha256(source_bytes).digest())
                payload = json.loads(source_bytes)
                body = payload["response"]["body"]
                rows = _items(payload)
                counts["source_rows"] += len(rows)
                if len(rows) > int(body.get("totalCount") or 0):
                    raise ValueError(f"Page exceeds reported totalCount: {path}")
                for row in rows:
                    if _horse_id(row.get("hrNo")) not in ids:
                        continue
                    if row.get("meet") != "제주":
                        raise ValueError(f"Non-Jeju training row: {path}")
                    training_date = int(row["trDate"])
                    native_dates.append(training_date)
                    counts["native_rows"] += 1
                    compressed.write(
                        (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode()
                    )
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    summary = {
        "dataset": dataset,
        "population": "confirmed native racers (2002-2014 result archive; 2015+ local DB)",
        "confirmed_native_horse_ids": len(ids),
        "source_pages": len(paths),
        "source_rows": counts["source_rows"],
        "native_rows": counts["native_rows"],
        "first_native_record_date": min(native_dates) if native_dates else None,
        "last_native_record_date": max(native_dates) if native_dates else None,
        "source_paths_and_hashes_sha256": source_sha256.hexdigest(),
        "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "output": str(destination),
        "network_requests": 0,
        "unconfirmed_horses_persisted": 0,
    }
    (output_root / f"{dataset}_confirmed_native.manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/horse_racing.sqlite3"))
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-root", type=Path, default=Path("data/raw/jeju_native_training"))
    args = parser.parse_args()
    ids = confirmed_native_ids(args.raw_root / "jeju_native_results", args.database)
    for dataset in ("horse_training", "start_training"):
        result = materialize(
            dataset=dataset,
            ids=ids,
            raw_root=args.raw_root,
            output_root=args.output_root,
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
