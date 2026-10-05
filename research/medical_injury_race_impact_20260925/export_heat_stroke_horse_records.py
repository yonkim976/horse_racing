#!/usr/bin/env python3
"""Export source records for the exact KRA glossary term and its compound terms."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT.parents[1] / "data" / "horse_racing.sqlite3"
AUDIT = ROOT / "comma_entry_review_v2_20260926.csv"
OUTPUT = ROOT / "heat_stroke_related_horse_records_20260926.csv"
METADATA = ROOT / "heat_stroke_related_horse_records_metadata_20260926.json"
PREFIX = "동물  "
TERM = "일,열사병"


def main() -> None:
    with AUDIT.open(encoding="utf-8-sig", newline="") as f:
        audit = {r["raw_text"]: r for r in csv.DictReader(f)}
    conn = sqlite3.connect(f"file:{DB.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    term_rows = conn.execute(
        "SELECT id, raw_text FROM medical_diagnosis_terms WHERE raw_text LIKE ? ORDER BY id",
        (f"%{TERM}%",),
    ).fetchall()
    selected = []
    for row in term_rows:
        body = row["raw_text"][len(PREFIX):] if row["raw_text"].startswith(PREFIX) else row["raw_text"]
        if TERM in body:
            selected.append((row["id"], row["raw_text"], "single_heat_stroke_term" if body == TERM else "heat_stroke_with_other_phrase"))
    ids = [x[0] for x in selected]
    placeholders = ",".join("?" for _ in ids)
    query = f"""
        SELECT d.horse_medical_id, d.source_slot, t.id AS term_id, t.raw_text,
               m.clinic_date_local, m.meet_code, m.diagnosis_1, m.diagnosis_2,
               m.observed_at_ms, h.kra_horse_id, h.name_ko
        FROM horse_medical_diagnoses d
        JOIN medical_diagnosis_terms t ON t.id=d.term_id
        JOIN horse_medical m ON m.id=d.horse_medical_id
        JOIN horses h ON h.id=m.horse_id
        WHERE d.term_id IN ({placeholders})
        ORDER BY t.id, m.clinic_date_local, h.name_ko, m.id, d.source_slot
    """
    records = conn.execute(query, ids).fetchall()
    term_type = {term_id: kind for term_id, _, kind in selected}
    fields = [
        "horse_medical_id", "source_slot", "term_id", "raw_text",
        "term_interpretation", "proposed_components_json", "clinic_date_local",
        "meet_code", "kra_horse_id", "horse_name", "diagnosis_1", "diagnosis_2",
        "observed_at_ms",
    ]
    counts = Counter()
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for record in records:
            interp = term_type[record["term_id"]]
            proposed = json.loads(audit[record["raw_text"]]["component_proposals_json"])
            counts[interp] += 1
            writer.writerow({
                "horse_medical_id": record["horse_medical_id"],
                "source_slot": record["source_slot"], "term_id": record["term_id"],
                "raw_text": record["raw_text"], "term_interpretation": interp,
                "proposed_components_json": json.dumps(proposed, ensure_ascii=False),
                "clinic_date_local": record["clinic_date_local"],
                "meet_code": record["meet_code"], "kra_horse_id": record["kra_horse_id"],
                "horse_name": record["name_ko"], "diagnosis_1": record["diagnosis_1"],
                "diagnosis_2": record["diagnosis_2"], "observed_at_ms": record["observed_at_ms"],
            })
    metadata = {
        "source_db": str(DB), "read_only": True,
        "definition": "User-provided KRA glossary entry: 일,열사병 (HEAT STROKE)",
        "matching_terms": [{"term_id": i, "raw_text": r, "interpretation": k} for i, r, k in selected],
        "medical_record_link_rows": len(records),
        "distinct_horse_ids": len({r["kra_horse_id"] for r in records}),
        "record_rows_by_interpretation": dict(counts),
        "output_file": OUTPUT.name,
        "no_clinical_or_eligibility_inference": True,
    }
    METADATA.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    conn.close()
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
