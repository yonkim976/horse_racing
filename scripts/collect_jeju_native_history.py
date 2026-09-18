"""Archive only explicitly marked Jeju-native horse result rows from the KRA API.

The annual API also returns Halla and other races. Those rows are discarded in
memory and never written to this archive. This is a source archive, not a model
dataset or a reconstruction of pre-race availability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path

from horse_racing.collectors.kra_api import (
    RACE_RESULT_WITH_SECTIONS_ENDPOINT,
    RACE_RESULT_WITH_SECTIONS_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


def _items(payload: dict) -> list[dict]:
    wrapped = response_body(payload).get("items") or {}
    value = wrapped.get("item") if isinstance(wrapped, dict) else None
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("Unexpected result item structure")
    return value


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def collect_year(year: int, output_dir: Path) -> dict:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("KRA service key unavailable")
    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    source_pages: list[dict] = []
    with KraApiClient(
        settings.data_go_kr_service_key.get_secret_value(),
        base_url=settings.kra_api_base_url,
        timeout_seconds=60,
    ) as client:
        for page in client.iter_pages(
            endpoint=RACE_RESULT_WITH_SECTIONS_ENDPOINT,
            operation=RACE_RESULT_WITH_SECTIONS_OPERATION,
            public_params={"meet": 2, "rc_year": str(year), "_type": "json"},
            page_size=20_000,
            service_key_parameter="ServiceKey",
        ):
            source_pages.append(
                {
                    "sha256": hashlib.sha256(page.body).hexdigest(),
                    "response_bytes": len(page.body),
                    "status_code": page.status_code,
                    "retrieved_at_ms": page.retrieved_at_ms,
                    "source_url_without_key": page.source_url,
                    "total_count": int(response_body(page.payload).get("totalCount") or 0),
                }
            )
            for row in _items(page.payload):
                if not str(row.get("rank") or "").startswith("제"):
                    continue
                race_date = int(row["rcDate"])
                if race_date // 10_000 != year or row.get("meet") != "제주":
                    raise ValueError("Native row outside requested Jeju year")
                grouped[(race_date, int(row["rcNo"]))].append(row)

    for key, rows in grouped.items():
        if len({(row.get("rank"), row.get("rcDist")) for row in rows}) != 1:
            raise ValueError(f"Inconsistent native race: {key}")
        horse_ids = [str(row.get("hrNo") or "").strip() for row in rows]
        if any(not horse_id for horse_id in horse_ids) or len(set(horse_ids)) != len(rows):
            raise ValueError(f"Missing or duplicate horse ID: {key}")

    records = [row for key in sorted(grouped) for row in grouped[key]]
    content = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for row in records
    )
    result = {
        "year": year,
        "scope": "meet=2 and rank begins with 제",
        "source": "KRA API4_3 raceResult_3",
        "source_pages": source_pages,
        "native_races": len(grouped),
        "native_horse_result_rows": len(records),
        "first_race_date": min((key[0] for key in grouped), default=None),
        "last_race_date": max((key[0] for key in grouped), default=None),
        "native_rows_sha256": hashlib.sha256(content).hexdigest(),
        "non_native_rows_persisted": 0,
    }
    _atomic_write(output_dir / f"native_results_{year}.jsonl", content)
    _atomic_write(
        output_dir / f"native_results_{year}.manifest.json",
        (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2002)
    parser.add_argument("--end-year", type=int, default=2014)
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/jeju_native_results"))
    args = parser.parse_args()
    if not 2002 <= args.start_year <= args.end_year <= 2026:
        raise ValueError("Expected 2002 <= start-year <= end-year <= 2026")
    for year in range(args.start_year, args.end_year + 1):
        result = collect_year(year, args.output_dir)
        print(
            json.dumps(
                {key: result[key] for key in ("year", "native_races", "native_horse_result_rows")}
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
