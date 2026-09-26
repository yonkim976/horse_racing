"""Store Seoul G3F-point ranks and scorecard passing groups in a research DB.

The official score page rank line is S1F-1C-2C-3C-G3F-4C-G1F. G3F there is the
cumulative point (API seG3fAccTime / sjG3fOrd), and 3F-G is the separate closing
time. Passing groups on that page have S-1F, corners, and G-1F, and no G3F line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from horse_racing.collectors.kra_api import (
    RACE_PASSING_SUMMARY_ENDPOINT,
    RACE_PASSING_SUMMARY_OPERATION,
    RACE_RESULT_WITH_SECTIONS_ENDPOINT,
    RACE_RESULT_WITH_SECTIONS_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data/research/seoul_api4_3_sections_20260926"
DACOM = ROOT / "data/raw/kra_text/dacom11/meet=1"
ORDS = {
    "S1F": "sjS1fOrd",
    "1C": "sj_1cOrd",
    "2C": "sj_2cOrd",
    "3C": "sj_3cOrd",
    "4C": "sj_4cOrd",
    "G3F": "sjG3fOrd",
    "G1F": "sjG1fOrd",
}
GROUP_LABELS = {"S-1F": "S1F", "C1": "1C", "C2": "2C", "C3": "3C", "C4": "4C", "G-1F": "G1F"}
API_GROUPS = {
    "corner_1": "1C",
    "corner_2": "2C",
    "corner_3": "3C",
    "corner_4": "4C",
    "corner_7": "S1F",
    "corner_8": "G1F",
}


def items(payload: dict) -> list[dict]:
    wrapped = response_body(payload).get("items") or {}
    value = wrapped.get("item") if isinstance(wrapped, dict) else None
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    raise ValueError("Unexpected API item structure")


def atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def fetch_year(client: KraApiClient, endpoint: str, operation: str, year: int, folder: str) -> list[dict]:
    root = ARCHIVE / folder / str(year)
    page_no = 1
    rows: list[dict] = []
    while True:
        path = root / f"page_{page_no:04d}.json"
        if path.exists():
            body = path.read_bytes()
            payload = json.loads(body)
        else:
            fetched = client._fetch_json(
                endpoint,
                operation,
                {"meet": 1, "rc_year": str(year), "_type": "json", "pageNo": page_no, "numOfRows": 20000},
                service_key_parameter="ServiceKey",
            )
            body, payload = fetched.body, fetched.payload
            atomic_write(path, body)
            event = {
                "year": year, "folder": folder, "page": page_no,
                "sha256": hashlib.sha256(body).hexdigest(),
                "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            ledger = ARCHIVE / "request_ledger.jsonl"
            with ledger.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, sort_keys=True) + "\n")
        batch = items(payload)
        body_json = response_body(payload)
        count = int(body_json.get("totalCount") or 0)
        size = int(body_json.get("numOfRows") or 20000)
        rows.extend(batch)
        if page_no >= max(1, math.ceil(count / max(size, 1))):
            if len(rows) != count:
                raise ValueError(f"{folder} {year} incomplete {len(rows)} != {count}")
            return rows
        page_no += 1


def positive_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    number = int(float(value))
    return number if number > 0 else None


def seconds_ms(value: object) -> int | None:
    if value is None or value == "":
        return None
    seconds = float(value)
    if seconds <= 0:
        return None
    return int(round(seconds * 1000))


def iso_date(value: object) -> str:
    text = str(int(value))
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def parse_dacom_groups(year: int) -> dict[tuple[str, int], dict[str, str]]:
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
                label = match.group(1)
                if label == "G-3F":
                    raise ValueError(f"Unexpected G3F passing group in {path}")
                value = match.group(2).strip()
                if value:
                    found[(date, current)][GROUP_LABELS[label]] = value
    return found


def load_year(year: int) -> None:
    db_path = ROOT / f"data/research/seoul_{year}_score_20260925/seoul_{year}.sqlite3"
    con = sqlite3.connect(db_path)
    con.execute("BEGIN")
    entries = {
        (date, number, horse): horse_id
        for date, number, horse, horse_id in con.execute(
            "SELECT race_date, race_number, horse_number, kra_horse_id FROM entry"
        )
    }
    races = {(date, number) for date, number in con.execute("SELECT race_date, race_number FROM race")}
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("KRA service key unavailable")
    with KraApiClient(
        settings.data_go_kr_service_key.get_secret_value(),
        base_url=settings.kra_api_base_url,
        timeout_seconds=90,
    ) as client:
        section_rows = fetch_year(
            client, RACE_RESULT_WITH_SECTIONS_ENDPOINT, RACE_RESULT_WITH_SECTIONS_OPERATION, year, "sections"
        )
        group_rows = fetch_year(
            client, RACE_PASSING_SUMMARY_ENDPOINT, RACE_PASSING_SUMMARY_OPERATION, year, "corner_rank"
        )

    inserted = agreed = mismatched = skipped = 0
    position_filled = position_mismatch = 0
    for row in section_rows:
        if row.get("meet") != "서울" or int(row["rcDate"]) // 10000 != year:
            raise ValueError("Out-of-scope Seoul section row")
        key = (iso_date(row["rcDate"]), int(row["rcNo"]), int(row["chulNo"]))
        horse_id = entries.get(key)
        if horse_id is None or horse_id != str(row["hrNo"]):
            skipped += 1
            continue
        g3f_ms = seconds_ms(row.get("seG3fAccTime"))
        g3f_pos = positive_int(row.get("sjG3fOrd"))
        if g3f_ms is None and g3f_pos is None:
            continue
        existing = con.execute(
            """
            SELECT elapsed_time_ms, position FROM section_time
            WHERE meet_code=1 AND race_date=? AND race_number=? AND kra_horse_id=?
              AND point_code='G3F' AND time_kind='cumulative'
            """,
            (key[0], key[1], horse_id),
        ).fetchone()
        if existing is None:
            con.execute(
                """
                INSERT INTO section_time
                VALUES (1, ?, ?, ?, 'G3F', 'cumulative', ?, ?, 'api4_3')
                """,
                (key[0], key[1], horse_id, g3f_ms, g3f_pos),
            )
            inserted += 1
        else:
            time_ok = existing[0] == g3f_ms or (
                existing[0] is not None and g3f_ms is not None and abs(existing[0] - g3f_ms) <= 100
            )
            pos_ok = existing[1] == g3f_pos
            if time_ok and pos_ok:
                agreed += 1
            else:
                mismatched += 1
        for point, field in ORDS.items():
            if point == "G3F":
                continue
            position = positive_int(row.get(field))
            if position is None:
                continue
            current = con.execute(
                """
                SELECT position FROM section_time
                WHERE meet_code=1 AND race_date=? AND race_number=? AND kra_horse_id=?
                  AND point_code=? AND position IS NOT NULL
                """,
                (key[0], key[1], horse_id, point),
            ).fetchone()
            if current is None:
                updated = con.execute(
                    """
                    UPDATE section_time SET position=?
                    WHERE meet_code=1 AND race_date=? AND race_number=? AND kra_horse_id=?
                      AND point_code=? AND position IS NULL
                    """,
                    (position, key[0], key[1], horse_id, point),
                )
                position_filled += updated.rowcount
            elif current[0] != position:
                position_mismatch += 1

    dacom = parse_dacom_groups(year)
    dacom_races = {key for key, groups in dacom.items() if groups}
    groups_source = "kept"
    group_replaced = 0
    if dacom_races == races:
        con.execute("DELETE FROM passing_group")
        for (date, number), groups in sorted(dacom.items()):
            for point, notation in groups.items():
                con.execute(
                    "INSERT INTO passing_group VALUES (1, ?, ?, ?, ?)",
                    (date, number, point, notation),
                )
                group_replaced += 1
        groups_source = "dacom11"
    elif dacom_races:
        groups_source = f"kept_api_dacom_days_{len({date for date, _ in dacom_races})}"

    g3f_group = con.execute("SELECT COUNT(*) FROM passing_group WHERE point_code='G3F'").fetchone()[0]
    if g3f_group:
        raise ValueError("G3F passing group was stored")
    closing_positions = con.execute(
        "SELECT COUNT(*) FROM section_time WHERE point_code='G3F' AND time_kind='closing' AND position IS NOT NULL"
    ).fetchone()[0]
    if closing_positions:
        raise ValueError("Closing G3F row gained a position")
    con.commit()
    summary = {
        "year": year,
        "g3f_inserted": inserted,
        "g3f_agreed": agreed,
        "g3f_mismatched_kept": mismatched,
        "section_rows_not_on_card": skipped,
        "other_position_filled": position_filled,
        "other_position_mismatch": position_mismatch,
        "groups_source": groups_source,
        "group_rows": group_replaced or con.execute("SELECT COUNT(*) FROM passing_group").fetchone()[0],
        "api_corner_rows": len(group_rows),
        "g3f_cumulative": con.execute(
            "SELECT COUNT(*), SUM(position IS NOT NULL) FROM section_time WHERE point_code='G3F' AND time_kind='cumulative'"
        ).fetchone(),
        "g3f_closing": con.execute(
            "SELECT COUNT(*), SUM(position IS NOT NULL) FROM section_time WHERE point_code='G3F' AND time_kind='closing'"
        ).fetchone(),
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    load_year(args.year)
