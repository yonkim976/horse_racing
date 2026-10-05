"""Compare backed-up operational race and entry keys with the current database."""

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "data/horse_racing.sqlite3"
OTHER = [
    ROOT / "data/horse_racing_before_20260929_identity.sqlite3",
    ROOT / "data/horse_racing_pre_medical_terms_20260925.sqlite3",
    *sorted((ROOT / "data/backups").glob("*.sqlite3")),
]
OUTPUT = Path(__file__).with_name("operational_backup_key_deltas.json")


def keys(path: Path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    try:
        races = set(
            con.execute(
                "SELECT racecourse_id,race_date_local,race_number FROM races "
                "WHERE racecourse_id IN (1,3,4) AND race_date_local <= '2026-09-20'"
            )
        )
        entries = set(
            con.execute(
                "SELECT r.racecourse_id,r.race_date_local,r.race_number,e.horse_number "
                "FROM race_entries e JOIN races r ON r.id=e.race_id "
                "WHERE r.racecourse_id IN (1,3,4) AND r.race_date_local <= '2026-09-20'"
            )
        )
        return races, entries
    finally:
        con.close()


def main():
    base_races, base_entries = keys(BASE)
    out = {
        "comparison_basis": "distinct natural keys, not source truth or result validity",
        "cutoff": "2026-09-20",
        "included_meets": [1, 3, 4],
        "current_operational_race_keys": len(base_races),
        "current_operational_entry_keys": len(base_entries),
        "comparisons": [],
    }
    for path in OTHER:
        race_keys, entry_keys = keys(path)
        out["comparisons"].append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "race_keys": len(race_keys),
                "races_only_in_backup": sorted(race_keys - base_races),
                "races_only_in_current": sorted(base_races - race_keys),
                "entry_keys": len(entry_keys),
                "entry_keys_only_in_backup_count": len(entry_keys - base_entries),
                "entry_keys_only_in_current_count": len(base_entries - entry_keys),
                "entry_keys_only_in_backup_sample": sorted(entry_keys - base_entries)[:20],
            }
        )
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"backups={len(OTHER)} output={OUTPUT}")


if __name__ == "__main__":
    main()
