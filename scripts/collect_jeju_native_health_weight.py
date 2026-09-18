"""Archive ID-confirmed Jeju-native medical and measured weight API rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from horse_racing.collectors.kra_api import (
    ENTRY_HORSE_WEIGHT_ENDPOINT,
    ENTRY_HORSE_WEIGHT_OPERATION,
    RACE_HORSE_CLINIC_ENDPOINT,
    RACE_HORSE_CLINIC_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


def _horse_id(value: object) -> str | None:
    try:
        return str(int(str(value)))
    except (TypeError, ValueError):
        return None


def _items(payload: dict) -> list[dict]:
    wrapped = response_body(payload).get("items") or {}
    value = wrapped.get("item") if isinstance(wrapped, dict) else None
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("Unexpected item structure")
    return value


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def native_keys(results_dir: Path, database: Path) -> tuple[set[str], set[tuple[int, int, str]]]:
    ids: set[str] = set()
    race_horse: set[tuple[int, int, str]] = set()
    for path in sorted(results_dir.glob("native_results_*.jsonl")):
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            horse_id = _horse_id(row.get("hrNo"))
            if horse_id is None:
                raise ValueError(f"Missing horse ID: {path}")
            ids.add(horse_id)
            race_horse.add((int(row["rcDate"]), int(row["rcNo"]), horse_id))
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            """SELECT r.race_date_local, r.race_number, h.kra_horse_id
               FROM race_entries AS e
               JOIN races AS r ON r.id=e.race_id
               JOIN racecourses AS c ON c.id=r.racecourse_id
               JOIN horses AS h ON h.id=e.horse_id
               WHERE c.kra_meet_code=2 AND r.status='completed'"""
        )
        for race_date, race_no, raw_id in rows:
            horse_id = _horse_id(raw_id)
            if horse_id is None:
                raise ValueError("Missing horse ID in local Jeju race")
            ids.add(horse_id)
            race_horse.add((int(race_date.replace("-", "")), int(race_no), horse_id))
    return ids, race_horse


def collect_period(
    *,
    kind: str,
    period: str,
    ids: set[str],
    race_horse: set[tuple[int, int, str]],
    output_dir: Path,
) -> dict:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("KRA service key unavailable")
    if kind == "medical":
        if len(period) != 4:
            raise ValueError("Medical collection requires YYYY")
        endpoint = RACE_HORSE_CLINIC_ENDPOINT
        operation = RACE_HORSE_CLINIC_OPERATION
        params = {"meet": 2, "clinic_year": period, "_type": "json"}
    elif kind == "weight":
        if len(period) != 6:
            raise ValueError("Weight collection requires YYYYMM")
        endpoint = ENTRY_HORSE_WEIGHT_ENDPOINT
        operation = ENTRY_HORSE_WEIGHT_OPERATION
        params = {"meet": 2, "rc_month": period, "_type": "json"}
    else:
        raise ValueError(f"Unknown kind: {kind}")

    retained: list[dict] = []
    source_pages: list[dict] = []
    source_rows = 0
    diagnosed = 0
    with KraApiClient(
        settings.data_go_kr_service_key.get_secret_value(),
        base_url=settings.kra_api_base_url,
        timeout_seconds=60,
    ) as client:
        for page in client.iter_pages(
            endpoint=endpoint,
            operation=operation,
            public_params=params,
            page_size=20_000,
            service_key_parameter="ServiceKey",
        ):
            rows = _items(page.payload)
            source_rows += len(rows)
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
            for row in rows:
                event_date = str(row["clinicDate"] if kind == "medical" else row["rcDate"])
                if not event_date.startswith(period):
                    raise ValueError(f"API ignored requested {kind} period {period}: {event_date}")
                horse_id = _horse_id(row.get("hrNo"))
                if horse_id not in ids or row.get("meet") != "제주":
                    continue
                if kind == "weight":
                    key = (int(row["rcDate"]), int(row["rcNo"]), horse_id)
                    if key not in race_horse or int(row.get("wgHr") or 0) <= 0:
                        continue
                else:
                    if int(row["clinicDate"]) > int(date.today().strftime("%Y%m%d")):
                        continue
                    if any(
                        str(row.get(field) or "").strip() not in {"", "-"}
                        for field in ("illName1", "illName2")
                    ):
                        diagnosed += 1
                retained.append(row)

    retained.sort(
        key=lambda row: (
            int(row["clinicDate"] if kind == "medical" else row["rcDate"]),
            int(row.get("rcNo") or 0),
            _horse_id(row["hrNo"]) or "",
        )
    )
    content = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for row in retained
    )
    dates = [int(row["clinicDate"] if kind == "medical" else row["rcDate"]) for row in retained]
    result = {
        "period": period,
        "kind": kind,
        "population": "ID-confirmed native; weight requires native race-entry key",
        "source_pages": source_pages,
        "source_rows_all_jeju": source_rows,
        "native_rows": len(retained),
        "native_rows_with_diagnosis": diagnosed if kind == "medical" else None,
        "first_native_date": min(dates) if dates else None,
        "last_native_date": max(dates) if dates else None,
        "native_rows_sha256": hashlib.sha256(content).hexdigest(),
        "non_native_rows_persisted": 0,
    }
    _atomic_write(output_dir / f"{kind}_{period}.jsonl", content)
    _atomic_write(
        output_dir / f"{kind}_{period}.manifest.json",
        (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("medical", "weight"), required=True)
    parser.add_argument("--start-period", required=True, help="YYYY for medical, YYYYMM for weight")
    parser.add_argument("--end-period", required=True, help="YYYY for medical, YYYYMM for weight")
    parser.add_argument("--database", type=Path, default=Path("data/horse_racing.sqlite3"))
    parser.add_argument("--results-dir", type=Path, default=Path("data/raw/jeju_native_results"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/raw/jeju_native_health_weight")
    )
    args = parser.parse_args()
    if args.kind == "medical":
        if not 2002 <= int(args.start_period) <= int(args.end_period) <= 2026:
            raise ValueError("Medical period outside 2002-2026")
        periods = [str(year) for year in range(int(args.start_period), int(args.end_period) + 1)]
    else:
        start_year, start_month = int(args.start_period[:4]), int(args.start_period[4:])
        end_year, end_month = int(args.end_period[:4]), int(args.end_period[4:])
        if not (2002, 1) <= (start_year, start_month) <= (end_year, end_month) <= (2026, 9):
            raise ValueError("Weight period outside 200201-202609")
        if not 1 <= start_month <= 12 or not 1 <= end_month <= 12:
            raise ValueError("Invalid weight month")
        periods = [
            f"{year:04d}{month:02d}"
            for year in range(start_year, end_year + 1)
            for month in range(1, 13)
            if args.start_period <= f"{year:04d}{month:02d}" <= args.end_period
        ]
    ids, race_horse = native_keys(args.results_dir, args.database)
    for period in periods:
        result = collect_period(
            kind=args.kind,
            period=period,
            ids=ids,
            race_horse=race_horse,
            output_dir=args.output_dir,
        )
        print(
            json.dumps(
                {key: result[key] for key in ("kind", "period", "native_rows", "first_native_date")}
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
