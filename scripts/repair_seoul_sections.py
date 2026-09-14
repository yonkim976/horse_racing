"""Replay retained Seoul originals. Dry run by default; --apply backs up SQLite."""

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from horse_racing.config import get_settings
from horse_racing.parsers.dacom11 import parse_dacom11_report
from horse_racing.parsers.race_day import parse_items
from horse_racing.parsers.race_section import RaceResultSectionItem, parse_section_values

CODES = ("S1F", "1C", "2C", "3C", "4C", "G3F", "G1F")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        raise ValueError("This repair requires a local SQLite database")
    db = url.removeprefix("sqlite:///")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    entries = conn.execute("""
        SELECT e.id,r.race_date_local,r.race_number,e.horse_number,r.distance_m,
               rr.finish_time_ms,e.body_weight_kg,e.body_weight_change_kg,rr.margin_text
        FROM race_entries e JOIN races r ON r.id=e.race_id
        JOIN racecourses c ON c.id=r.racecourse_id
        JOIN race_results rr ON rr.race_entry_id=e.id
        WHERE c.kra_meet_code=1 AND r.status='completed'
    """).fetchall()
    lookup = {(e[1], e[2], e[3]): e for e in entries}
    wanted, origins, covered, finish_updates = {}, {}, set(), {}

    def accept(key, distance, values, source):
        entry = lookup.get(key)
        if entry is None:
            raise ValueError(f"Source entry missing from DB: {key}")
        if entry[4] != distance:
            raise ValueError(f"Distance mismatch: {key}")
        eid = entry[0]
        covered.add(eid)
        origins[eid] = str(source)
        for code in CODES:
            wanted[eid, code] = values.get(code)

    for path in sorted(Path("data/raw/kra_text/dacom11/meet=1").rglob("*.rpt")):
        for race in parse_dacom11_report(path.read_bytes()):
            for item in race.entries:
                key = (race.race_date.isoformat(), race.race_number, item.horse_number)
                old = lookup.get(key)
                if old is None:
                    raise ValueError(f"Report entry not stored: {key}")
                times = {
                    "S1F": item.s1f_ms,
                    "G3F": item.g3f_ms,
                    "G1F": item.g1f_ms,
                    **item.corner_times_ms,
                }
                positions = {}
                passing = (item.passing_order_raw or "").split("-")
                if len(passing) == 6:
                    for code, value in zip(
                        ("S1F", "1C", "2C", "3C", "4C", "G1F"), passing, strict=True
                    ):
                        if re.fullmatch(r"\s*\d+\s*", value) and 0 < int(value) < 90:
                            positions[code] = int(value)
                values = {}
                for code in CODES:
                    t, p = times.get(code), positions.get(code)
                    if t is not None or p is not None:
                        values[code] = (
                            t,
                            p,
                            "closing" if code in ("G3F", "G1F") else "cumulative",
                            "dacom11",
                            item.passing_order_raw,
                        )
                accept(key, race.distance_m, values, path)
                if old[5] is None and item.finish_time_ms:
                    finish_updates[old[0]] = dict(
                        time=item.finish_time_ms,
                        weight=item.body_weight_kg,
                        change=item.body_weight_change_kg,
                        margin=item.margin_text,
                        source=str(path),
                        old=list(old[5:]),
                    )

    docs = conn.execute("""
        SELECT d.local_path FROM source_documents d JOIN ingestion_runs i
        ON i.id=d.ingestion_run_id WHERE i.data_type='race_result_sections'
        AND d.local_path LIKE '%/meet_1/%' ORDER BY d.retrieved_at_ms,d.id
    """).fetchall()
    for (filename,) in docs:
        for item in parse_items(json.loads(Path(filename).read_text()), RaceResultSectionItem):
            key = (item.race_date.isoformat(), item.race_number, item.horse_number)
            values = {
                s.section_code: (s.elapsed_time_ms, s.position, s.time_basis, "api4_3", None)
                for s in parse_section_values(item, 1)
            }
            accept(key, item.distance_m, values, filename)
            finish_updates.pop(lookup[key][0], None)
    if len(covered) != len(entries):
        raise ValueError(f"Uncovered entries: {len(entries) - len(covered)}")
    existing = {
        (r[0], r[1]): tuple(r[2:])
        for r in conn.execute("""
        SELECT s.race_entry_id,s.section_code,s.elapsed_time_ms,s.position,s.time_basis,
               s.source_kind,s.group_notation_raw FROM race_section_results s
        JOIN race_entries e ON e.id=s.race_entry_id JOIN races r ON r.id=e.race_id
        JOIN racecourses c ON c.id=r.racecourse_id WHERE c.kra_meet_code=1
    """)
    }
    changes = []
    counts = Counter()
    for key, new in wanted.items():
        old = existing.get(key)
        if old == new:
            continue
        action = "insert" if old is None else "delete" if new is None else "update"
        counts[action] += 1
        if old and new and old[0] != new[0]:
            counts["changed_times"] += 1
        changes.append(
            dict(entry=key[0], code=key[1], old=old, new=new, action=action, source=origins[key[0]])
        )
    summary = dict(
        entries=len(entries),
        covered=len(covered),
        changes=len(changes),
        counts=dict(counts),
        restored_finishes=len(finish_updates),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.apply:
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = Path("data/logs") / f"seoul_section_repair_{stamp}"
    folder.mkdir(parents=True)
    backup = Path("data/backups") / f"before_seoul_replay_{stamp}.sqlite3"
    backup.parent.mkdir(exist_ok=True)
    with sqlite3.connect(backup) as dst:
        conn.backup(dst)
    conn.close()
    with (folder / "changes.jsonl").open("w") as f:
        for change in changes:
            f.write(json.dumps(change, ensure_ascii=False) + "\n")
    (folder / "finish_updates.json").write_text(
        json.dumps(finish_updates, ensure_ascii=False, indent=2)
    )
    with sqlite3.connect(db) as writable:
        writable.execute("PRAGMA foreign_keys=ON")
        writable.execute("BEGIN IMMEDIATE")
        for change in changes:
            eid, code, new = change["entry"], change["code"], change["new"]
            if new is None:
                writable.execute(
                    "DELETE FROM race_section_results WHERE race_entry_id=? AND section_code=?",
                    (eid, code),
                )
            else:
                writable.execute(
                    """
                    INSERT INTO race_section_results
                    (race_entry_id,section_code,elapsed_time_ms,position,time_basis,source_kind,group_notation_raw)
                    VALUES (?,?,?,?,?,?,?) ON CONFLICT(race_entry_id,section_code) DO UPDATE SET
                    elapsed_time_ms=excluded.elapsed_time_ms,position=excluded.position,
                    time_basis=excluded.time_basis,source_kind=excluded.source_kind,
                    group_notation_raw=excluded.group_notation_raw
                """,
                    (eid, code, *new),
                )
        for eid, value in finish_updates.items():
            writable.execute(
                """UPDATE race_results
                              SET finish_time_ms=?,margin_text=COALESCE(margin_text,?)
                              WHERE race_entry_id=? AND finish_time_ms IS NULL""",
                (value["time"], value["margin"], eid),
            )
            writable.execute(
                """UPDATE race_entries SET body_weight_kg=COALESCE(body_weight_kg,?),
                              body_weight_change_kg=COALESCE(body_weight_change_kg,?) WHERE id=?""",
                (value["weight"], value["change"], eid),
            )
    summary.update(backup=str(backup), applied=True)
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(folder)


if __name__ == "__main__":
    main()
