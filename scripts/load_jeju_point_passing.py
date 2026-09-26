"""Store Jeju scorecard passing groups for native-Jeju research races.

The official page rank line is S1F-1C-2C-3C-4C-G1F. G-3F on that page is the
closing time and has no passing rank or passing group. Groups are S-1F, C1-C4,
and G-1F. 2017-2024 text is the scorecard source. 2025-2026 keep stored groups
when they match API corner_rank and fill races the API has that the sheet lacks.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from horse_racing.collectors.kra_api import (
    RACE_PASSING_SUMMARY_ENDPOINT,
    RACE_PASSING_SUMMARY_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
DACOM = ROOT / "data/raw/kra_text/dacom11/meet=2"
LABELS = {"S-1F": "S1F", "C1": "1C", "C2": "2C", "C3": "3C", "C4": "4C", "G-1F": "G1F"}
API_GROUPS = {
    "corner_1": "1C",
    "corner_2": "2C",
    "corner_3": "3C",
    "corner_4": "4C",
    "corner_7": "S1F",
    "corner_8": "G1F",
}


def api_items(payload: dict) -> list[dict]:
    def walk(obj):
        if isinstance(obj, dict):
            item = obj.get("item")
            if isinstance(item, list) and item and isinstance(item[0], dict):
                return item
            if isinstance(item, dict):
                return [item]
            for value in obj.values():
                found = walk(value)
                if found is not None:
                    return found
        return None

    return walk(payload) or []


def iso_date(value: object) -> str:
    text = str(int(value))
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def parse_dacom(year: int) -> dict[tuple[str, int], dict[str, str]]:
    race_pat = re.compile(r"제\s*(\d+)\s*경주")
    line_pat = re.compile(r"(S-1F|C1|C2|C3|C4|G-1F|G-3F)\s*:\s*(.*?)\s*$")
    found: dict[tuple[str, int], dict[str, str]] = {}
    root = DACOM / f"year={year}"
    if not root.exists():
        return found
    for path in sorted(root.rglob("*.rpt")):
        stem = path.stem
        date = f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
        current = None
        for line in path.read_text(encoding="cp949", errors="replace").splitlines():
            header = race_pat.search(line)
            if header and line.startswith("제목"):
                current = int(header.group(1))
                found.setdefault((date, current), {})
            match = line_pat.search(line)
            if match and current is not None:
                if match.group(1) == "G-3F" and match.group(2).strip():
                    raise ValueError(f"Unexpected G3F passing group in {path}")
                value = match.group(2).strip()
                if value and match.group(1) != "G-3F":
                    found[(date, current)][LABELS[match.group(1)]] = value
    return found


def fetch_corner_rank(year: int) -> list[dict]:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("KRA service key unavailable")
    with KraApiClient(
        settings.data_go_kr_service_key.get_secret_value(),
        base_url=settings.kra_api_base_url,
        timeout_seconds=90,
    ) as client:
        fetched = client._fetch_json(
            RACE_PASSING_SUMMARY_ENDPOINT,
            RACE_PASSING_SUMMARY_OPERATION,
            {"meet": 2, "rc_year": str(year), "_type": "json", "pageNo": 1, "numOfRows": 20000},
            service_key_parameter="ServiceKey",
        )
    rows = api_items(fetched.payload)
    count = int(response_body(fetched.payload).get("totalCount") or 0)
    if len(rows) != count:
        raise ValueError(f"corner_rank {year} incomplete {len(rows)} != {count}")
    return rows


def replace_groups(con: sqlite3.Connection, groups: dict[tuple[str, int], dict[str, str]], races: set) -> int:
    con.execute("DELETE FROM passing_group")
    written = 0
    for (date, number), points in sorted(groups.items()):
        if (date, number) not in races:
            continue
        for point, notation in points.items():
            con.execute(
                "INSERT INTO passing_group VALUES (2, ?, ?, ?, ?)",
                (date, number, point, notation),
            )
            written += 1
    return written


def load_year(year: int) -> None:
    db_path = ROOT / f"data/research/jeju_{year}_score_20260925/jeju_{year}.sqlite3"
    con = sqlite3.connect(db_path)
    con.execute("BEGIN")
    races = {(date, number) for date, number in con.execute("SELECT race_date, race_number FROM race")}
    g3f_positions = con.execute(
        "SELECT COUNT(*) FROM section_time WHERE point_code='G3F' AND position IS NOT NULL"
    ).fetchone()[0]
    dacom = parse_dacom(year)
    covered = {key for key in races if dacom.get(key)}
    source = "kept"
    mismatch = 0
    inserted = 0
    if covered == races and dacom:
        inserted = replace_groups(con, dacom, races)
        source = "dacom11"
    else:
        stored = {
            (date, number, point): notation
            for date, number, point, notation in con.execute(
                "SELECT race_date, race_number, point_code, notation_raw FROM passing_group"
            )
        }
        api_groups: dict[tuple[str, int, str], str] = {}
        for row in fetch_corner_rank(year):
            if row.get("meet") not in (None, "제주"):
                raise ValueError(f"Out-of-scope meet {row.get('meet')}")
            date, number = iso_date(row["rcDate"]), int(row["rcNo"])
            if (date, number) not in races:
                continue
            for field, point in API_GROUPS.items():
                raw = row.get(field)
                if raw in (None, "", "-", "X"):
                    continue
                api_groups[(date, number, point)] = raw
        if not stored and api_groups:
            for (date, number, point), notation in api_groups.items():
                con.execute(
                    "INSERT INTO passing_group VALUES (2, ?, ?, ?, ?)",
                    (date, number, point, notation),
                )
                inserted += 1
            source = "api303"
        else:
            for key, notation in api_groups.items():
                if stored.get(key) != notation:
                    mismatch += 1
            missing = [key for key in api_groups if key not in stored]
            for date, number, point in missing:
                con.execute(
                    "INSERT INTO passing_group VALUES (2, ?, ?, ?, ?)",
                    (date, number, point, api_groups[(date, number, point)]),
                )
                inserted += 1
            source = "kept_api" if not inserted else "kept_plus_api"
    g3f_groups = con.execute("SELECT COUNT(*) FROM passing_group WHERE point_code='G3F'").fetchone()[0]
    if g3f_groups or g3f_positions:
        raise ValueError("Jeju G3F rank or group was stored")
    con.commit()
    print(
        json.dumps(
            {
                "year": year,
                "source": source,
                "score_races": len(races),
                "dacom_covered_races": len(covered),
                "group_rows": con.execute("SELECT COUNT(*) FROM passing_group").fetchone()[0],
                "races_with_group": con.execute(
                    "SELECT COUNT(DISTINCT race_date || ':' || race_number) FROM passing_group"
                ).fetchone()[0],
                "inserted": inserted,
                "api_mismatch_kept": mismatch,
                "g3f_positions": g3f_positions,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    load_year(args.year)
