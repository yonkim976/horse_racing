#!/usr/bin/env python3
"""Read-only provenance and coverage audit for canonical section research."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from horse_racing.analysis.features.canonical_sections import canonicalize_sections
from horse_racing.parsers.dacom11 import parse_dacom11_report

KST = ZoneInfo("Asia/Seoul")
API_FIELDS = {
    1: ("seS1fAccTime", "seG3fAccTime", "seG1fAccTime"),
    2: ("jeS1fTime", "jeG3fTime", "jeG1fTime"),
    3: ("buS1fAccTime", "buG3fAccTime", "buG1fAccTime"),
}
API_BASIS = {1: ("cumulative", "cumulative", "cumulative"),
             2: ("cumulative", "closing", "closing"),
             3: ("cumulative", "cumulative", "cumulative")}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _items(payload: dict) -> list[dict]:
    items = payload["response"]["body"]["items"]
    values = items.get("item", items) if isinstance(items, dict) else items
    return values if isinstance(values, list) else [values]


def _stored_values(
    connection: sqlite3.Connection,
    meet: int,
    race_date: str,
    race_number: int,
    horse_number: int,
) -> dict[str, int | None]:
    rows = connection.execute(
        """SELECT s.section_code, s.elapsed_time_ms
        FROM race_section_results s
        JOIN race_entries e ON e.id=s.race_entry_id
        JOIN races r ON r.id=e.race_id
        JOIN racecourses rc ON rc.id=r.racecourse_id
        WHERE rc.kra_meet_code=? AND r.race_date_local=?
          AND r.race_number=? AND e.horse_number=?
          AND s.section_code IN ('S1F','G3F','G1F')""",
        (meet, race_date, race_number, horse_number),
    )
    return dict(rows)


def _ms(value: object) -> int | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return round(number * 1000) if number > 0 else None


def _api_samples(root: Path, connection: sqlite3.Connection) -> list[dict]:
    samples = []
    for meet in (1, 2, 3):
        seen_distances: set[int] = set()
        candidates = sorted((root / "data/raw/kra/race_result_sections/2025").glob(
            f"**/meet_{meet}/**/*.json"
        ))
        for path in candidates:
            item = next(
                (
                    item
                    for item in _items(json.loads(path.read_text()))
                    if int(item.get("ord") or 0) < 90
                    and int(item.get("rcDist") or 0) not in seen_distances
                ),
                None,
            )
            if item is None:
                continue
            seen_distances.add(int(item["rcDist"]))
            fields = API_FIELDS[meet]
            raw = dict(
                zip(
                    ("S1F", "G3F", "G1F"),
                    map(lambda field: _ms(item.get(field)), fields),
                    strict=True,
                )
            )
            race_date = datetime.strptime(str(item["rcDate"]), "%Y%m%d").date().isoformat()
            stored = _stored_values(
                connection, meet, race_date, int(item["rcNo"]), int(item["chulNo"])
            )
            samples.append({
                "meet_code": meet, "source_kind": "api4_3",
                "source_path": str(path.relative_to(root)), "source_sha256": _sha256(path),
                "race_date": race_date, "race_number": int(item["rcNo"]),
                "distance_m": int(item["rcDist"]), "horse_number": int(item["chulNo"]),
                "raw_fields": dict(zip(("S1F", "G3F", "G1F"), fields, strict=True)),
                "documented_basis": dict(
                    zip(("S1F", "G3F", "G1F"), API_BASIS[meet], strict=True)
                ),
                "raw_ms": raw, "stored_ms": stored, "matches_stored": raw == stored,
            })
    return samples


def _dacom_samples(root: Path, connection: sqlite3.Connection) -> list[dict]:
    samples = []
    for meet in (1, 2, 3):
        seen_distances: set[int] = set()
        candidates = sorted((root / f"data/raw/kra_text/dacom11/meet={meet}/year=2024").glob(
            "**/*dacom11.rpt"
        ))
        for path in candidates:
            races = parse_dacom11_report(path.read_bytes())
            pair = next(
                (
                    (race, entry)
                    for race in races
                    for entry in race.entries
                    if race.distance_m not in seen_distances
                    and entry.s1f_ms
                    and entry.g3f_ms
                    and entry.g1f_ms
                ),
                None,
            )
            if pair is None:
                continue
            race, entry = pair
            seen_distances.add(race.distance_m)
            raw = {"S1F": entry.s1f_ms, "G3F": entry.g3f_ms, "G1F": entry.g1f_ms}
            stored = _stored_values(
                connection, meet, race.race_date.isoformat(), race.race_number,
                entry.horse_number,
            )
            samples.append({
                "meet_code": meet, "source_kind": "dacom11",
                "source_path": str(path.relative_to(root)), "source_sha256": _sha256(path),
                "race_date": race.race_date.isoformat(), "race_number": race.race_number,
                "distance_m": race.distance_m, "horse_number": entry.horse_number,
                "documented_basis": {"S1F": "cumulative", "G3F": "closing", "G1F": "closing"},
                "raw_ms": raw, "stored_ms": stored, "matches_stored": raw == stored,
            })
    return samples


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/horse_racing.sqlite3"))
    parser.add_argument("--end-date", default="2026-05-31")
    parser.add_argument("--output", type=Path,
                        default=Path("data/logs/canonical_section_source_audit_20260911.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    connection = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    coverage = [dict(row) for row in connection.execute(
        """SELECT rc.kra_meet_code meet_code, strftime('%Y',r.race_date_local) year,
        r.distance_m, s.section_code, COALESCE(s.time_basis,'unknown') time_basis,
        COALESCE(s.source_kind,'unknown') source_kind, COUNT(*) row_count,
        SUM(s.elapsed_time_ms IS NULL) null_count
        FROM race_section_results s JOIN race_entries e ON e.id=s.race_entry_id
        JOIN races r ON r.id=e.race_id JOIN racecourses rc ON rc.id=r.racecourse_id
        WHERE r.race_date_local <= ? GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3,4,5,6""",
        (args.end_date,),
    )]
    sample_rows = [dict(row) for row in connection.execute(
        """SELECT e.horse_id,e.id race_entry_id,r.id race_id,rc.kra_meet_code meet_code,
        r.race_date_local race_date,r.distance_m,s.section_code,s.elapsed_time_ms,
        s.time_basis,s.source_kind,res.finish_position,res.finish_time_ms,e.horse_number
        FROM race_section_results s JOIN race_entries e ON e.id=s.race_entry_id
        JOIN races r ON r.id=e.race_id JOIN racecourses rc ON rc.id=r.racecourse_id
        LEFT JOIN race_results res ON res.race_entry_id=e.id WHERE r.id=1681"""
    )]
    canonical = canonicalize_sections(pl.DataFrame(sample_rows, infer_schema_length=None))
    horse_map = pl.DataFrame(sample_rows).select("race_entry_id", "horse_number").unique()
    canonical = canonical.join(horse_map, on="race_entry_id")
    median = canonical["canonical_last_200_ms"].median()
    example = canonical.filter(pl.col("horse_number") == 6).to_dicts()[0]
    example["canonical_last_200_relative"] = math.log(
        median / example["canonical_last_200_ms"]
    ) * 100
    basis_totals: Counter[tuple[int, str, str]] = Counter()
    for row in coverage:
        basis_totals[(row["meet_code"], row["time_basis"], row["source_kind"])] += row[
            "row_count"
        ]
    payload = {
        "created_at": datetime.now(KST).isoformat(), "database": str(args.database),
        "query_end_date": args.end_date,
        "contract": {
            "unknown": "unavailable; not inferred from magnitude or venue",
            "cumulative_to_closing": "finish_time_ms - elapsed_time_ms",
            "special_results": "finish_position outside 1..89 unavailable",
        },
        "basis_source_totals": [
            {"meet_code": key[0], "time_basis": key[1], "source_kind": key[2],
             "row_count": count} for key, count in sorted(basis_totals.items())
        ],
        "coverage_by_meet_year_distance_section": coverage,
        "raw_samples": _api_samples(root, connection) + _dacom_samples(root, connection),
        "seoul_race_1681_horse_6": example,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
