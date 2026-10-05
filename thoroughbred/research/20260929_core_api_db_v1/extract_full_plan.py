"""Preserve every field of the archived KRA API72_2 race-plan items."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CAL = ROOT / "thoroughbred/research/20260929_calendar_api_v1"
OUT = HERE / "race_plan_full_api.csv"
FIELDS = ("ageCond", "budam", "buga1", "buga2", "buga3", "chaksun1", "chaksun2",
          "chaksun3", "chaksun4", "chaksun5", "ilsu", "meet", "rank", "rcDate",
          "rcDist", "rcName", "rcNo", "schStTime", "sexCond", "spRating", "stRating")


def main() -> None:
    records = []
    for year in range(2010, 2027):
        for meet in (1, 3, 4):
            path = CAL / "raw/race_plan" / str(year) / f"meet_{meet}.json"
            body = path.read_bytes()
            payload = json.loads(body)
            source = payload["response"]["body"]
            items = source.get("items") or {}
            items = items.get("item") or []
            if isinstance(items, dict):
                items = [items]
            if len(items) != int(source.get("totalCount") or 0):
                raise ValueError(f"Incomplete source: {path}")
            digest = hashlib.sha256(body).hexdigest()
            for index, item in enumerate(items):
                day = str(item.get("rcDate"))
                if day[:4] != str(year):
                    raise ValueError(f"Request year mismatch: {path} item {index}")
                if not ("20100101" <= day <= "20260929"):
                    continue
                row = {"source_meet": meet, "race_date_key": day, "race_no_key": item["rcNo"],
                       "source_file": path.relative_to(ROOT).as_posix(),
                       "source_file_sha256": digest, "source_item_index": index,
                       "source_record_json": json.dumps(item, ensure_ascii=False, sort_keys=True,
                                                        separators=(",", ":"))}
                row.update({f"api_{field}": item.get(field) for field in FIELDS})
                records.append(row)
    keys = [(int(row["source_meet"]), row["race_date_key"], int(row["race_no_key"])) for row in records]
    if len(records) != 29826 or len(set(keys)) != len(keys):
        raise ValueError("Race-plan full API key/count validation failed")
    with (CAL / "race_plan.csv").open(encoding="utf-8", newline="") as stream:
        prior = {(int(row["meet"]), row["date"], int(row["race_no"])) for row in csv.DictReader(stream)}
    if set(keys) != prior:
        raise ValueError("Full API plan keys differ from calendar plan ledger")
    with OUT.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print(f"Preserved {len(records)} full plan items")


if __name__ == "__main__":
    main()
