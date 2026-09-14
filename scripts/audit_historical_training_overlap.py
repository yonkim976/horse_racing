"""Compare a completed KRA monthly training year with existing training rows."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from horse_racing.config import get_settings
from horse_racing.db.models import Horse, HorseTraining
from horse_racing.db.session import SessionLocal


def _items(payload: dict) -> list[dict]:
    value = payload["response"]["body"].get("items", {}).get("item", [])
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _as_int(value: object) -> int | None:
    return None if value in (None, "") else int(value)


def audit(year: int) -> dict:
    root = get_settings().raw_data_dir / "kra_api_monthly" / "horse_training"
    results: dict[str, dict] = {}
    for meet in (1, 2, 3):
        raw: dict[tuple[str, str, str, str], dict] = {}
        duplicates = 0
        for path in sorted((root / f"meet_{meet}").glob(f"{year}*/page_*.json")):
            for item in _items(json.loads(path.read_bytes())):
                key = (
                    str(item["hrNo"]),
                    str(item["trDate"]),
                    str(item.get("stTime") or ""),
                    str(item.get("spTime") or ""),
                )
                duplicates += key in raw
                raw[key] = item
        with SessionLocal() as session:
            rows = session.execute(
                select(
                    Horse.kra_horse_id,
                    HorseTraining.training_date_local,
                    HorseTraining.started_at_raw,
                    HorseTraining.ended_at_raw,
                    HorseTraining.duration_seconds,
                    HorseTraining.canter_count,
                    HorseTraining.gallop_count,
                    HorseTraining.trainer_name,
                )
                .join(Horse, Horse.id == HorseTraining.horse_id)
                .where(
                    HorseTraining.meet_code == meet,
                    HorseTraining.training_date_local >= f"{year}-01-01",
                    HorseTraining.training_date_local < f"{year + 1}-01-01",
                )
            ).all()
        db = {
            (row[0], row[1].strftime("%Y%m%d"), str(row[2] or ""), str(row[3] or "")): row
            for row in rows
        }
        common = raw.keys() & db.keys()
        differences: Counter[str] = Counter()
        trainer_examples: list[dict] = []
        for key in common:
            source = raw[key]
            target = db[key]
            for field, stored, original in (
                ("duration", target[4], source.get("trTerm")),
                ("canter", target[5], source.get("run1Cnt")),
                ("gallop", target[6], source.get("run2Cnt")),
            ):
                differences[field] += stored != _as_int(original)
            if (target[7] or None) != (source.get("trName") or None):
                differences["trainer"] += 1
                if len(trainer_examples) < 10:
                    trainer_examples.append(
                        {
                            "horse_id": key[0],
                            "date": key[1],
                            "db_trainer": target[7],
                            "source_trainer": source.get("trName"),
                        }
                    )
        results[str(meet)] = {
            "source_rows": len(raw) + duplicates,
            "source_unique_keys": len(raw),
            "duplicate_source_keys": duplicates,
            "db_rows": len(rows),
            "db_unique_keys": len(db),
            "missing_in_db": len(raw.keys() - db.keys()),
            "extra_in_db": len(db.keys() - raw.keys()),
            "value_differences": dict(differences),
            "trainer_difference_examples": trainer_examples,
        }
    return {"year": year, "meets": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.year)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({meet: x["missing_in_db"] for meet, x in result["meets"].items()}))


if __name__ == "__main__":
    main()
