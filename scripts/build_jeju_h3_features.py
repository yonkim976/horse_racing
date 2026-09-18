"""Read-only reconstruction from dated declaration documents, not race results."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from horse_racing.analysis.jeju_h3_features import (
    BASE_FEATURES,
    RELATIVE_FEATURES,
    add_people_history,
    add_relative,
    parse_card,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"
OUT = ROOT / "data/research/jeju_native_h3_features_v1_20260916"
DB = ROOT / "data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3"


def main():
    assert not (OUT / "features.parquet").exists(), "Refuse overwrite"
    OUT.mkdir(exist_ok=True, parents=True)
    c = sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    entries = pl.read_parquet(DATA / "entries.parquet")
    # Extract only allowlisted result fields for PAST people history; no target result features.
    originals = {
        r["entry_id"]: dict(r)
        for r in c.execute("""SELECT e.id entry_id,e.horse_name,e.hr_no horse_id,
       v.event_date,v.event_number,e.horse_number,
       json_extract(s.normalized_json,'$.jkName') jockey_name,
       json_extract(s.normalized_json,'$.jkNo') jockey_id,
       json_extract(s.normalized_json,'$.trName') trainer_name,
       json_extract(s.normalized_json,'$.trNo') trainer_id
       FROM entry e JOIN event v ON e.event_id=v.id JOIN source_row s ON s.id=e.source_row_id
       WHERE v.event_type='race' """)
    }
    lookup = {
        (str(row["event_date"]).replace("-", ""), row["event_number"], row["horse_number"]): row
        for row in originals.values()
    }
    candidates = defaultdict(list)
    issues = []
    docs = []
    rawcount = 0
    for d in c.execute(
        "select d.id,d.file_date,d.retrieved_at_ms,d.remote_path,a.path,a.sha256 "
        "from text_document d join source_artifact a on a.id=d.source_artifact_id "
        "where d.text_type='dacom01' order by d.file_date,d.id"
    ):
        if not d["file_date"]:
            continue
        filedate = date.fromisoformat(d["file_date"])
        path = ROOT / d["path"]
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == d["sha256"], str(path)
        docs.append(dict(d))
        lines = content.decode("cp949", errors="replace").splitlines()
        for row in parse_card(lines):
            if row["breed"] != "제":
                continue
            rawcount += 1
            key = (row["event_date"].strftime("%Y%m%d"), row["event_number"], row["horse_number"])
            src = lookup.get(key)
            if not src or src["horse_name"] != row["horse_name"]:
                issues.append(
                    {
                        "reason": "entry_name_or_key_unresolved",
                        "document_id": d["id"],
                        "line_number": row["line_number"],
                    }
                )
                continue
            if filedate > row["event_date"] - timedelta(days=2):
                issues.append(
                    {
                        "reason": "document_date_too_late",
                        "document_id": d["id"],
                        "entry_id": src["entry_id"],
                    }
                )
                continue
            if not (1 <= row["age"] <= 30 and 30 <= row["burden"] <= 100):
                issues.append({"reason": "invalid_age_or_burden", "entry_id": src["entry_id"]})
                continue
            row.update(
                entry_id=src["entry_id"],
                document_id=d["id"],
                file_date=filedate,
                document_sha256=d["sha256"],
                source_line_sha256=hashlib.sha256(
                    lines[row["line_number"] - 1].encode()
                ).hexdigest(),
            )
            candidates[src["entry_id"]].append(row)
    targets = []
    lineage = []
    for e in entries.iter_rows(named=True):
        choices = candidates.get(e["entry_id"], [])
        variants = {
            tuple(
                x[k]
                for k in [
                    "age",
                    "sex",
                    "burden",
                    "jockey_name",
                    "trainer_name",
                    "rating",
                    "grade",
                    "distance",
                    "allowance",
                ]
            )
            for x in choices
        }
        if len(variants) > 1:
            issues.append({"reason": "conflicting_dated_cards", "entry_id": e["entry_id"]})
            choices = []
        chosen = min(choices, key=lambda x: (x["file_date"], x["document_id"])) if choices else None
        if chosen and chosen["distance"] != e["distance_m"]:
            issues.append({"reason": "distance_mismatch", "entry_id": e["entry_id"]})
            chosen = None
        record = {
            "entry_id": e["entry_id"],
            "race_id": e["race_id"],
            "horse_id": e["horse_id"],
            "event_date": e["event_date"],
            "split": e["split"],
            "card_observed": int(chosen is not None),
            "declared_horse_number": chosen["horse_number"] if chosen else None,
            "declared_age": chosen["age"] if chosen else None,
            "declared_female": int(chosen["sex"] == "암") if chosen else None,
            "declared_gelded": int(chosen["sex"] == "거") if chosen else None,
            "declared_burden_kg": chosen["burden"] if chosen else None,
            "declared_rating": chosen["rating"] if chosen else None,
            "declared_grade_number": chosen["grade"] if chosen else None,
            "declared_jockey_allowance_kg": chosen["allowance"] if chosen else None,
            "jockey_name": chosen["jockey_name"] if chosen else None,
            "trainer_name": chosen["trainer_name"] if chosen else None,
        }
        targets.append(record)
        lineage.append(
            {
                "entry_id": e["entry_id"],
                "source_document_id": chosen["document_id"] if chosen else None,
                "source_file_date": chosen["file_date"] if chosen else None,
                "source_line_number": chosen["line_number"] if chosen else None,
                "source_line_sha256": chosen["source_line_sha256"] if chosen else None,
                "jockey_name": record["jockey_name"],
                "trainer_name": record["trainer_name"],
                "availability_class": "DATED_DECLARATION_ASSUMED_PUBLICATION_NO_REVISION_ARCHIVE",
                "card_observed": record["card_observed"],
            }
        )
    history = []
    labels = pl.read_parquet(DATA / "labels.parquet")
    for r in labels.iter_rows(named=True):
        source = originals[r["entry_id"]]
        history.append(
            {
                "event_date": r["event_date"],
                "horse_id": r["horse_id"],
                "jockey_name": source["jockey_name"],
                "jockey_id": str(source["jockey_id"]) if source["jockey_id"] else None,
                "trainer_name": source["trainer_name"],
                "trainer_id": str(source["trainer_id"]) if source["trainer_id"] else None,
                "win": int(r["label_win"]),
                "top3": int(r["label_top3"]),
            }
        )
    augmented = pl.DataFrame(add_people_history(targets, history), infer_schema_length=None)
    features = augmented.select("entry_id", *BASE_FEATURES)
    states = pl.read_parquet(DATA / "horse_states.parquet")
    features = add_relative(states.join(features, on="entry_id", validate="1:1")).select(
        "entry_id", *BASE_FEATURES, *RELATIVE_FEATURES
    )
    features.write_parquet(OUT / "features.parquet")
    pl.DataFrame(lineage, infer_schema_length=None).write_parquet(OUT / "lineage.parquet")
    allframe = entries.join(features, on="entry_id")
    coverage = {}
    for split, s in allframe.partition_by("split", as_dict=True).items():
        coverage[split[0]] = {
            "entries": len(s),
            "races": s["race_id"].n_unique(),
            "cards": int(s["card_observed"].sum()),
            "feature_nonnull": {k: len(s) - s[k].null_count() for k in BASE_FEATURES},
        }
    report = {
        "dataset_manifest_sha256": hashlib.sha256(
            (DATA / "manifest.json").read_bytes()
        ).hexdigest(),
        "features": BASE_FEATURES + RELATIVE_FEATURES,
        "base_features": BASE_FEATURES,
        "relative_features": RELATIVE_FEATURES,
        "entries": len(features),
        "raw_native_card_rows": rawcount,
        "source_documents": len(docs),
        "coverage": coverage,
        "issues": dict(Counter(x["reason"] for x in issues)),
        "availability": (
            "document date <= race date-2d; "
            "actual historical publication and revision time not proven"
        ),
        "rating_policy": (
            "Only column explicitly headed 레이팅; 승군순위 is never interpreted asrating"
        ),
        "history_policy": (
            "actual past jockey/trainer official IDs mapped from names using only "
            "observations<=date-2d; ambiguous name unknown; "
            "no target actualjockey substituted"
        ),
        "gate_policy": "declared horse number only; physical stall mapping not verified",
        "fixed_priors": "people win(2/20),top3(6/20);horsejockeytop3(3/10); no fitted priors",
        "model_fit_count": 0,
    }
    for name, obj in [
        ("build_report.json", report),
        ("source_documents.json", docs),
        ("issues.json", issues),
    ]:
        (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ["features", "coverage"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(json.dumps(coverage, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
