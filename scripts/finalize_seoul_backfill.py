"""Add source-preserving rating and dead-heat fields to the isolated Seoul DB."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path("data/research/seoul_backfill_20260915_v1")
EARLY_HEADING = re.compile(
    r"(?:;TI|\(서울\))\s*(\d{2,4})년\s*(\d{1,2})월\s*(\d{1,2})일.*?제\s*0*(\d+)경주"
)
WEIGHT_LINE = re.compile(r"^\s*(\d{1,2})\s+(\S+)\s+(\d{3})\s+([+-]\d+|0)\b")


def official_id(value: object, width: int) -> str:
    if value is None or str(value).strip() in {"", "0", "None"}:
        return ""
    raw = str(value).strip()
    return raw.zfill(width) if raw.isdigit() else raw


def main() -> None:
    con = sqlite3.connect(ROOT / "history.sqlite3")
    recovered = 0
    for (path_str,) in con.execute("""SELECT source_path FROM source_inventory
      WHERE source_type='dacom12' AND first_event_date IS NULL""").fetchall():
        path = Path(path_str)
        current = None
        first_event = None
        for line_no, line in enumerate(
            path.read_text(encoding="cp949", errors="replace").splitlines(), 1
        ):
            heading = EARLY_HEADING.search(line)
            if heading:
                yy, mm, dd, no = map(int, heading.groups())
                yy += 2000 if yy < 100 else 0
                current = (f"{yy:04d}-{mm:02d}-{dd:02d}", no)
                first_event = current[0] if first_event is None else min(first_event, current[0])
                con.execute(
                    "INSERT OR IGNORE INTO text_race_heading VALUES(?,?,?,?,?)",
                    ("dacom12", *current, path_str, line_no),
                )
            if current is None:
                continue
            match = WEIGHT_LINE.match(line)
            if not match:
                continue
            chul, name, kg, delta = match.groups()
            candidate = con.execute(
                """SELECT hr_no,horse_name FROM entry
              WHERE meet=1 AND race_date=? AND race_no=? AND chul_no=?""",
                (*current, int(chul)),
            ).fetchone()
            confirmed = bool(candidate and candidate[1] == name)
            con.execute(
                "INSERT OR IGNORE INTO race_day_weight VALUES(1,?,?,?,?,?,?,?,?,?,?)",
                (
                    *current,
                    int(chul),
                    name,
                    int(kg),
                    int(delta),
                    candidate[0] if confirmed else None,
                    "confirmed" if confirmed else "unmatched",
                    path_str,
                    line_no,
                ),
            )
            recovered += 1
        if first_event:
            con.execute(
                "UPDATE source_inventory SET first_event_date=? WHERE source_path=?",
                (first_event, path_str),
            )
    con.execute(
        "CREATE INDEX IF NOT EXISTS weight_hr_race ON race_day_weight(race_date,race_no,hr_no)"
    )
    con.execute("""UPDATE research_entry SET weight_source_status=
      CASE WHEN race_date<'2003-09-06' THEN 'text_source_unavailable_api_result_weight_present'
      WHEN EXISTS(SELECT 1 FROM race_day_weight w WHERE w.race_date=research_entry.race_date
        AND w.race_no=research_entry.race_no AND w.hr_no=research_entry.hr_no
        AND w.link_status='confirmed') THEN 'confirmed_text'
      ELSE 'source_observed_unlinked_or_missing' END""")
    con.execute("ALTER TABLE entry ADD COLUMN rating_raw REAL")
    con.execute("ALTER TABLE entry ADD COLUMN horse_origin_raw TEXT")
    con.execute("ALTER TABLE entry ADD COLUMN horse_sex_raw TEXT")
    con.execute("ALTER TABLE entry ADD COLUMN horse_age_raw INTEGER")
    con.execute("ALTER TABLE result ADD COLUMN is_dead_heat INTEGER NOT NULL DEFAULT 0")
    con.execute("ALTER TABLE race ADD COLUMN official_result_state TEXT")
    con.execute("CREATE INDEX result_rank_lookup ON result(race_date,race_no,finish_order)")
    con.execute("""UPDATE race SET official_result_state=CASE
      WHEN EXISTS(SELECT 1 FROM result x WHERE x.race_date=race.race_date
        AND x.race_no=race.race_no AND x.result_status='finished') THEN 'confirmed'
      WHEN EXISTS(SELECT 1 FROM result x WHERE x.race_date=race.race_date
        AND x.race_no=race.race_no AND x.result_status='void') THEN 'void'
      ELSE 'special_only_unresolved' END""")
    con.execute("""UPDATE result SET is_dead_heat=1 WHERE finish_order IS NOT NULL
      AND EXISTS(SELECT 1 FROM result other WHERE other.race_date=result.race_date
        AND other.race_no=result.race_no AND other.finish_order=result.finish_order
        AND other.hr_no!=result.hr_no)""")
    con.execute("CREATE INDEX IF NOT EXISTS entry_source_ref ON entry(source_path,source_row)")
    for path in sorted((ROOT / "raw_results").glob("*/page_*.json")):
        payload = json.loads(path.read_bytes())
        rows = payload["response"]["body"].get("items", {}).get("item", [])
        if isinstance(rows, dict):
            rows = [rows]
        batch = []
        for idx, row in enumerate(rows):
            batch.append(
                (row.get("rating"), row.get("name"), row.get("sex"), row.get("age"), str(path), idx)
            )
        con.executemany(
            """UPDATE entry SET rating_raw=?,horse_origin_raw=?,
          horse_sex_raw=?,horse_age_raw=? WHERE source_path=? AND source_row=?""",
            batch,
        )
    con.execute(
        "CREATE INDEX IF NOT EXISTS medical_name_date ON medical_event(horse_name,event_date)"
    )
    con.commit()
    (ROOT / "coverage_year_source.csv").unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "entries": con.execute("SELECT count(*) FROM entry").fetchone()[0],
                "rating_raw_nonnull": con.execute(
                    "SELECT count(*) FROM entry WHERE rating_raw IS NOT NULL"
                ).fetchone()[0],
                "dead_heat_entries": con.execute(
                    "SELECT count(*) FROM result WHERE is_dead_heat=1"
                ).fetchone()[0],
                "recovered_early_weight_rows": recovered,
            }
        )
    )
    con.close()


if __name__ == "__main__":
    main()
