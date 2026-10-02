"""Restore one verified 2020 Seoul finisher missing from the operational DB.

The source row is the preserved official-result-derived research record. The
API78 card is independently hash-checked and supplies card-only equipment.
Run without --apply to validate without changing the database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/horse_racing.sqlite3"
RESEARCH_DB = ROOT / "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb"
RACE_DATE = "2020-11-22"
RACE_NUMBER = 3
HORSE_NUMBER = 2
HORSE_KRA_ID = "0041616"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    research = duckdb.connect(str(RESEARCH_DB), read_only=True)
    source = research.execute(
        """SELECT hr_no, horse_name_normalized, jockey_no, trainer_no,
                  owner_no, owner_name, burden_weight_kg, horse_weight_kg,
                  horse_weight_delta_kg, rating_raw, finish_order,
                  result_status, race_time_s
           FROM entry_result
           WHERE venue_code='SEOUL' AND race_date=? AND race_no=? AND chul_no=?""",
        [RACE_DATE, RACE_NUMBER, HORSE_NUMBER],
    ).fetchall()
    research.close()
    if len(source) != 1:
        raise ValueError(f"Expected one research result, got {len(source)}")
    row = source[0]
    if (row[0], row[1], row[10], row[11], row[12]) != (
        HORSE_KRA_ID, "돌아온셀라", 11, "finished", 90.0
    ):
        raise ValueError("Official-result-derived source row changed")

    db = sqlite3.connect(args.database)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        race = db.execute(
            """SELECT r.id, r.field_size FROM races r
               JOIN racecourses c ON c.id=r.racecourse_id
               WHERE c.kra_meet_code=1 AND r.race_date_local=?
                 AND r.race_number=?""",
            (RACE_DATE, RACE_NUMBER),
        ).fetchone()
        if race is None or race["field_size"] not in (10, 11):
            raise ValueError("Target race missing or unexpected field size")
        horse = db.execute(
            "SELECT id, name_ko FROM horses WHERE kra_horse_id=?", (HORSE_KRA_ID,)
        ).fetchone()
        if horse is None or horse["name_ko"] != row[1]:
            raise ValueError("Horse identity mismatch")

        def person_id(table: str, key: str, value: str) -> int:
            # table and key are fixed internal constants, never user input.
            found = db.execute(
                f"SELECT id FROM {table} WHERE {key}=?", (value,)
            ).fetchone()
            if found is None:
                raise ValueError(f"Missing {table} identity: {value}")
            return int(found["id"])

        jockey_id = person_id("jockeys", "kra_jockey_id", row[2])
        trainer_id = person_id("trainers", "kra_trainer_id", row[3])
        document = db.execute(
            """SELECT local_path, sha256, retrieved_at_ms FROM source_documents
               WHERE endpoint='/API78/chulmainfo'
                 AND json_extract(request_params_json, '$.race_dt')='20201122'
                 AND json_extract(request_params_json, '$.rccrs_cd')=1
               ORDER BY retrieved_at_ms DESC LIMIT 1"""
        ).fetchone()
        if document is None:
            raise ValueError("Missing saved API78 card")
        raw_path = ROOT / document["local_path"]
        body = raw_path.read_bytes()
        if hashlib.sha256(body).hexdigest() != document["sha256"]:
            raise ValueError("API78 source hash mismatch")
        items = json.loads(body)["response"]["body"]["items"]["item"]
        cards = [
            item for item in items
            if item.get("raceNo") == "제3경주"
            and int(item.get("gtno", -1)) == HORSE_NUMBER
        ]
        if len(cards) != 1 or cards[0].get("hrnm") != row[1]:
            raise ValueError("API78 card runner identity mismatch")
        equipment_card = cards[0].get("equipCrs")

        existing = db.execute(
            "SELECT id, horse_id FROM race_entries WHERE race_id=? AND horse_number=?",
            (race["id"], HORSE_NUMBER),
        ).fetchone()
        if existing is not None and existing["horse_id"] != horse["id"]:
            raise ValueError("Race/gate is occupied by a different horse")
        if not args.apply:
            print(json.dumps({"race_id": race["id"], "horse_id": horse["id"],
                              "existing_entry": existing is not None,
                              "finish_position": row[10], "equipment_card": equipment_card},
                             ensure_ascii=False))
            return

        with db:
            db.execute(
                "INSERT OR IGNORE INTO owners(kra_owner_id,name_ko) VALUES(?,?)",
                (row[4], row[5]),
            )
            owner_id = person_id("owners", "kra_owner_id", row[4])
            db.execute(
                """INSERT OR IGNORE INTO race_entries(
                      race_id,horse_id,jockey_id,trainer_id,owner_id,
                      horse_number,gate_number,carried_weight_kg,body_weight_kg,
                      body_weight_change_kg,rating,equipment_card_raw,
                      equipment_card_observed_at_ms,scratched)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (race["id"], horse["id"], jockey_id, trainer_id, owner_id,
                 HORSE_NUMBER, HORSE_NUMBER, row[6], row[7], row[8], row[9],
                 equipment_card, document["retrieved_at_ms"]),
            )
            entry = db.execute(
                "SELECT id,horse_id FROM race_entries WHERE race_id=? AND horse_number=?",
                (race["id"], HORSE_NUMBER),
            ).fetchone()
            if entry["horse_id"] != horse["id"]:
                raise ValueError("Race/gate identity changed during insert")
            result = db.execute(
                "SELECT finish_position,finish_time_ms FROM race_results WHERE race_entry_id=?",
                (entry["id"],),
            ).fetchone()
            if result is None:
                db.execute(
                    """INSERT INTO race_results(race_entry_id,finish_position,
                                                 finish_time_ms,disqualified)
                       VALUES(?,?,?,0)""",
                    (entry["id"], 11, 90000),
                )
            elif (result["finish_position"], result["finish_time_ms"]) != (11, 90000):
                raise ValueError("Existing result conflicts with official result")
            db.execute("UPDATE races SET field_size=11 WHERE id=?", (race["id"],))
        print(json.dumps({"race_id": race["id"], "entry_id": entry["id"],
                          "horse_id": horse["id"], "finish_position": 11,
                          "field_size": 11}, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
