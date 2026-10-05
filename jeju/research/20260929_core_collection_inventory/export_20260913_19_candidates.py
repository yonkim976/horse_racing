"""Export the already-held Sep 13-19 Jeju scorecard extension with provenance."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCORECARD = ROOT / "data/research/jeju_2026_score_20260925/jeju_2026.sqlite3"
OPERATIONAL = ROOT / "data/horse_racing.sqlite3"
OUT = Path(__file__).resolve().parent
START = "2026-09-13"
END = "2026-09-19"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def main() -> None:
    score = read_only(SCORECARD)
    operational = read_only(OPERATIONAL)
    score.row_factory = sqlite3.Row
    operational.row_factory = sqlite3.Row
    output_rows: list[dict] = []
    missing_links: list[dict] = []
    races = score.execute(
        "SELECT * FROM race WHERE race_date BETWEEN ? AND ? ORDER BY race_date,race_number",
        (START, END),
    ).fetchall()
    for race in races:
        entrants = score.execute(
            "SELECT * FROM entry WHERE meet_code=? AND race_date=? AND race_number=? ORDER BY horse_number",
            (race["meet_code"], race["race_date"], race["race_number"]),
        ).fetchall()
        op_race = operational.execute(
            "SELECT * FROM races WHERE id=? AND racecourse_id=2",
            (race["operational_race_id"],),
        ).fetchone()
        for entry in entrants:
            op_entry = operational.execute(
                "SELECT re.*, h.kra_horse_id, j.kra_jockey_id, j.name_ko AS jockey_name, "
                "t.kra_trainer_id, t.name_ko AS trainer_name, o.kra_owner_id, o.name_ko AS owner_name "
                "FROM race_entries re JOIN horses h ON h.id=re.horse_id "
                "LEFT JOIN jockeys j ON j.id=re.jockey_id "
                "LEFT JOIN trainers t ON t.id=re.trainer_id "
                "LEFT JOIN owners o ON o.id=re.owner_id WHERE re.id=?",
                (entry["operational_race_entry_id"],),
            ).fetchone()
            matched = (
                op_race is not None
                and op_entry is not None
                and str(op_entry["kra_horse_id"]) == str(entry["kra_horse_id"])
                and op_entry["race_id"] == op_race["id"]
            )
            if not matched:
                missing_links.append({
                    "race_date": race["race_date"], "race_number": race["race_number"],
                    "horse_number": entry["horse_number"], "horse_id": entry["kra_horse_id"],
                    "operational_entry_id": entry["operational_race_entry_id"],
                })
            output_rows.append({
                "provenance_status": "cross_source_candidate_not_officially_reconciled",
                "scope": {"meet_code": race["meet_code"], "race_date": race["race_date"]},
                "scorecard_race": dict(race),
                "scorecard_entry": dict(entry),
                "operational_race": dict(op_race) if op_race else None,
                "operational_entry_and_people": dict(op_entry) if op_entry else None,
                "cross_source_key_match": bool(matched),
            })
    score.close()
    operational.close()

    target = OUT / "candidate_core_extension_20260913_19.jsonl"
    content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in output_rows)
    target.write_text(content, encoding="utf-8")
    manifest = {
        "collected_at_utc": datetime.now(UTC).isoformat(),
        "scope": {"meet_code": 2, "from": START, "through": END},
        "method": "read-only extraction of held Jeju scorecard entries joined by their operational race-entry IDs; race/entry/official horse ID cross-check retained per row",
        "status": "candidate_extension_not_officially_reconciled",
        "race_count": len(races),
        "entry_count": len(output_rows),
        "cross_source_key_matches": sum(row["cross_source_key_match"] for row in output_rows),
        "unresolved_links": missing_links,
        "output": str(target.relative_to(ROOT)),
        "output_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "inputs": [
            {"path": str(SCORECARD.relative_to(ROOT)), "sha256": sha256(SCORECARD)},
            {"path": str(OPERATIONAL.relative_to(ROOT)), "sha256": sha256(OPERATIONAL),
             "scope_note": "racecourse-level source; used only after exact scorecard race-entry ID and horse ID matches"},
        ],
        "caution": "Operational roster fields are preserved as source candidates and do not independently establish native breed or historical person profile validity.",
    }
    (OUT / "candidate_core_extension_20260913_19.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "races": manifest["race_count"], "entries": manifest["entry_count"],
        "exact_cross_source_matches": manifest["cross_source_key_matches"],
        "unresolved_links": len(missing_links), "output": str(target.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
