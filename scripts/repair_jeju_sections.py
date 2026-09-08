"""Audit/replay retained official Jeju section records; --apply backs up SQLite first."""

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from horse_racing.db.session import SessionLocal
from horse_racing.parsers.dacom11 import parse_dacom11_report
from horse_racing.parsers.race_day import parse_items
from horse_racing.parsers.race_section import RaceResultSectionItem, parse_section_values

CODES = ("S1F", "1C", "2C", "3C", "4C", "G3F", "G1F")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        entries = session.execute(
            text("""
            SELECT e.id, r.race_date_local, r.race_number, e.horse_number,
                   h.name_ko, r.distance_m
            FROM race_entries e JOIN races r ON r.id=e.race_id
            JOIN racecourses c ON c.id=r.racecourse_id JOIN horses h ON h.id=e.horse_id
            WHERE c.kra_meet_code=2 AND r.status='completed'
        """)
        ).all()
        lookup = {(r[1], r[2], r[3]): r for r in entries}
        desired, provenance, seen, skipped = {}, {}, set(), []
        counts = Counter()

        def accept(key, name, distance, values, source):
            row = lookup.get(key)
            if row is None:
                skipped.append((key, "entry not found"))
                return
            # Horse names may change; date/race/number/distance is the stored result key.
            if row[5] != distance:
                raise ValueError(f"Distance mismatch: {key}")
            seen.add(row[0])
            provenance[row[0]] = str(source)
            for code in CODES:
                desired[row[0], code] = values.get(code, (None, None))
            counts[distance, "source_entries"] += 1

        for path in sorted(Path("data/raw/kra_text/dacom11/meet=2").rglob("*.rpt")):
            for race in parse_dacom11_report(path.read_bytes()):
                for entry in race.entries:
                    values = {
                        "S1F": (entry.s1f_ms, None),
                        "G3F": (entry.g3f_ms, None),
                        "G1F": (entry.g1f_ms, None),
                    }
                    values.update({c: (t, None) for c, t in entry.corner_times_ms.items()})
                    passing = (entry.passing_order_raw or "").split("-")
                    if len(passing) == 6:
                        for code, value in zip(
                            ("S1F", "1C", "2C", "3C", "4C", "G1F"), passing, strict=True
                        ):
                            value = value.strip()
                            if re.fullmatch(r"\d+", value) and 0 < int(value) < 90:
                                values[code] = (values.get(code, (None, None))[0], int(value))
                    accept(
                        (race.race_date.isoformat(), race.race_number, entry.horse_number),
                        entry.horse_name,
                        race.distance_m,
                        values,
                        path,
                    )

        # Newer API originals take precedence over historical reports.
        docs = session.execute(
            text("""
            SELECT d.local_path FROM source_documents d JOIN ingestion_runs i
            ON i.id=d.ingestion_run_id WHERE i.data_type='race_result_sections'
            ORDER BY d.retrieved_at_ms,d.id
        """)
        ).scalars()
        for filename in docs:
            if "/meet_2/" not in filename:
                continue
            payload = json.loads(Path(filename).read_text())
            for item in parse_items(payload, RaceResultSectionItem):
                values = {
                    v.section_code: (v.elapsed_time_ms, v.position)
                    for v in parse_section_values(item, 2)
                }
                accept(
                    (item.race_date.isoformat(), item.race_number, item.horse_number),
                    item.horse_name,
                    item.distance_m,
                    values,
                    filename,
                )

        existing = {
            (r[0], r[1]): (r[2], r[3])
            for r in session.execute(
                text("""
            SELECT s.race_entry_id,s.section_code,s.elapsed_time_ms,s.position
            FROM race_section_results s JOIN race_entries e ON e.id=s.race_entry_id
            JOIN races r ON r.id=e.race_id JOIN racecourses c ON c.id=r.racecourse_id
            WHERE c.kra_meet_code=2
        """)
            )
        }
        changes = []
        by_distance, by_code = Counter(), Counter()
        distances = {r[0]: r[5] for r in entries}
        for (entry_id, code), value in desired.items():
            old = existing.get((entry_id, code))
            new = None if value == (None, None) else value
            if old == new:
                continue
            action = "insert" if old is None else "delete" if new is None else "update"
            changes.append(
                dict(
                    entry_id=entry_id,
                    code=code,
                    old=old,
                    new=new,
                    action=action,
                    source=provenance[entry_id],
                )
            )
            by_distance[distances[entry_id], action] += 1
            by_code[code, action] += 1
        summary = dict(
            entries=len(entries),
            source_covered_entries=len(seen),
            uncovered_entries=len(entries) - len(seen),
            skipped=skipped,
            changes=len(changes),
            by_distance={f"{d}/{a}": n for (d, a), n in sorted(by_distance.items())},
            by_code={f"{c}/{a}": n for (c, a), n in sorted(by_code.items())},
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if not args.apply:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = Path("data/logs") / f"jeju_section_repair_{stamp}"
        folder.mkdir(parents=True)
        (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        with (folder / "changes.jsonl").open("w") as output:
            for change in changes:
                output.write(json.dumps(change, ensure_ascii=False) + "\n")
        dbpath = session.get_bind().url.database
        backup = Path("data/backups") / f"before_jeju_section_repair_{stamp}.sqlite3"
        backup.parent.mkdir(exist_ok=True)
        with sqlite3.connect(dbpath) as src, sqlite3.connect(backup) as dst:
            src.backup(dst)
        for change in changes:
            params = dict(entry=change["entry_id"], code=change["code"])
            if change["new"] is None:
                session.execute(
                    text("""DELETE FROM race_section_results
                    WHERE race_entry_id=:entry AND section_code=:code"""),
                    params,
                )
            else:
                params.update(time=change["new"][0], position=change["new"][1])
                session.execute(
                    text("""
                    INSERT INTO race_section_results
                    (race_entry_id,section_code,elapsed_time_ms,position)
                    VALUES (:entry,:code,:time,:position)
                    ON CONFLICT(race_entry_id,section_code) DO UPDATE SET
                    elapsed_time_ms=excluded.elapsed_time_ms,position=excluded.position
                """),
                    params,
                )
        session.commit()
        print(f"Saved {len(changes)} changes; audit={folder}; backup={backup}")


if __name__ == "__main__":
    main()
