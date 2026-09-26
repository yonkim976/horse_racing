"""Fill Busan cumulative passing ranks and scorecard passing groups.

The official score page rank line is S1F-G8F-G6F-G4F-G3F-G2F-G1F. Those ranks
belong on the cumulative point rows (API bu*Ord). Closing and segment rows stay
without a rank. Passing groups include G3F. 2017-2024 groups come from the
dacom scorecard text. 2025-2026 groups stay when they match API corner_rank.
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
SECTIONS = ROOT / "data/research/busan_api4_3_sections_20260925/raw"
DACOM = ROOT / "data/raw/kra_text/dacom11/meet=3"
ORDS = {
    "S1F": "buS1fOrd",
    "G8F": "buG8fOrd",
    "G6F": "buG6fOrd",
    "G4F": "buG4fOrd",
    "G3F": "buG3fOrd",
    "G2F": "buG2fOrd",
    "G1F": "buG1fOrd",
}
API_GROUPS = {
    "corner_1": "G8F",
    "corner_2": "G6F",
    "corner_3": "G4F",
    "corner_5": "G3F",
    "corner_7": "S1F",
    "corner_8": "G2F",
    "corner_9": "G1F",
}
LABELS = {"S1F": "S1F", "S-1F": "S1F", "G8F": "G8F", "G6F": "G6F", "G4F": "G4F", "G3F": "G3F", "G2F": "G2F", "G1F": "G1F", "G-1F": "G1F"}


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


def positive(value: object) -> int | None:
    if value is None or value == "":
        return None
    number = int(float(value))
    return number if number > 0 else None


def iso_date(value: object) -> str:
    text = str(int(value))
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def section_rows(year: int) -> list[dict]:
    rows: list[dict] = []
    for path in sorted((SECTIONS / str(year)).glob("*.json")):
        rows.extend(api_items(json.loads(path.read_text())))
    if not rows:
        raise ValueError(f"No Busan section archive for {year}")
    return rows


def parse_dacom(year: int) -> dict[tuple[str, int], dict[str, str]]:
    race_pat = re.compile(r"제\s*(\d+)\s*경주")
    line_pat = re.compile(r"(S-1F|S1F|G8F|G6F|G4F|G3F|G2F|G-1F|G1F)\s*:\s*(.*?)\s*$")
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
                value = match.group(2).strip()
                if value:
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
            {"meet": 3, "rc_year": str(year), "_type": "json", "pageNo": 1, "numOfRows": 20000},
            service_key_parameter="ServiceKey",
        )
    body = response_body(fetched.payload)
    rows = api_items(fetched.payload)
    count = int(body.get("totalCount") or 0)
    if len(rows) != count:
        raise ValueError(f"corner_rank {year} incomplete {len(rows)} != {count}")
    return rows


def load_year(year: int) -> None:
    db_path = ROOT / f"data/research/busan_{year}_score_20260925/busan_{year}.sqlite3"
    con = sqlite3.connect(db_path)
    con.execute("BEGIN")
    entries = {
        (date, number, horse): horse_id
        for date, number, horse, horse_id in con.execute(
            "SELECT race_date, race_number, horse_number, kra_horse_id FROM entry"
        )
    }
    races = {(date, number) for date, number in con.execute("SELECT race_date, race_number FROM race")}
    filled = agreed = mismatched = skipped = 0
    for row in section_rows(year):
        if row.get("meet") != "부산경남" or int(row["rcDate"]) // 10000 != year:
            raise ValueError("Out-of-scope Busan section row")
        key = (iso_date(row["rcDate"]), int(row["rcNo"]), int(row["chulNo"]))
        horse_id = entries.get(key)
        if horse_id is None or horse_id != str(row["hrNo"]):
            skipped += 1
            continue
        for point, field in ORDS.items():
            position = positive(row.get(field))
            if position is None:
                continue
            current = con.execute(
                """
                SELECT position FROM section_time
                WHERE meet_code=3 AND race_date=? AND race_number=? AND kra_horse_id=?
                  AND point_code=? AND time_kind='cumulative'
                """,
                (*key[:2], horse_id, point),
            ).fetchone()
            if current is None:
                continue
            if current[0] is None:
                con.execute(
                    """
                    UPDATE section_time SET position=?
                    WHERE meet_code=3 AND race_date=? AND race_number=? AND kra_horse_id=?
                      AND point_code=? AND time_kind='cumulative' AND position IS NULL
                    """,
                    (position, *key[:2], horse_id, point),
                )
                filled += 1
            elif current[0] == position:
                agreed += 1
            else:
                mismatched += 1

    dacom = parse_dacom(year)
    dacom_races = {key for key, groups in dacom.items() if groups}
    groups_source = "kept"
    group_rows = 0
    group_mismatch = 0
    if dacom_races == races:
        con.execute("DELETE FROM passing_group")
        for (date, number), groups in sorted(dacom.items()):
            for point, notation in groups.items():
                con.execute(
                    "INSERT INTO passing_group VALUES (3, ?, ?, ?, ?)",
                    (date, number, point, notation),
                )
                group_rows += 1
        groups_source = "dacom11"
    else:
        stored = {
            (date, number, point): notation
            for date, number, point, notation in con.execute(
                "SELECT race_date, race_number, point_code, notation_raw FROM passing_group"
            )
        }
        api_groups: dict[tuple[str, int, str], str] = {}
        for row in fetch_corner_rank(year):
            date, number = iso_date(row["rcDate"]), int(row["rcNo"])
            if (date, number) not in races:
                continue
            for field, point in API_GROUPS.items():
                raw = row.get(field)
                if raw in (None, "", "-", "X"):
                    continue
                api_groups[(date, number, point)] = raw
        if not stored:
            for (date, number, point), notation in api_groups.items():
                con.execute(
                    "INSERT INTO passing_group VALUES (3, ?, ?, ?, ?)",
                    (date, number, point, notation),
                )
            groups_source = "api303"
            group_rows = len(api_groups)
        else:
            for key, notation in api_groups.items():
                if stored.get(key) == notation:
                    continue
                group_mismatch += 1
            groups_source = "kept"
            group_rows = len(stored)

    closing_positions = con.execute(
        """
        SELECT COUNT(*) FROM section_time
        WHERE time_kind IN ('closing', 'segment') AND position IS NOT NULL
        """
    ).fetchone()[0]
    if closing_positions:
        raise ValueError("Closing or segment row has a passing rank")
    con.commit()
    print(
        json.dumps(
            {
                "year": year,
                "positions_filled": filled,
                "positions_agreed": agreed,
                "positions_mismatched_kept": mismatched,
                "rows_not_on_card": skipped,
                "groups_source": groups_source,
                "group_rows": group_rows,
                "group_api_mismatch": group_mismatch,
                "dacom_races": len(dacom_races),
                "score_races": len(races),
                "cumulative_with_rank": con.execute(
                    "SELECT COUNT(*) FROM section_time WHERE time_kind='cumulative' AND position IS NOT NULL"
                ).fetchone()[0],
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
