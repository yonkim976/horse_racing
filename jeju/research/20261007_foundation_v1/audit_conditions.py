"""Audit raw race-condition fields, not reviewed section values. Never write DB."""

import json
import sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
FIELDS = ("rank", "rcName", "ageCond", "sexCond", "prizeCond", "budam", "weather", "rating", "sjG3fOrd")


def main():
    before = DB.stat()
    con = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    # Read raw conditions only; do not use raw section times/orders as features.
    rows = [(day, json.loads(payload)) for day, payload in con.execute(
        "SELECT q.race_date,a.payload_json FROM jeju_race_postrace_sections_quality_2026 q "
        "JOIN api_records a ON a.api_record_id=q.api_record_id"
    )]
    result = {}
    for name, sample in (("all_candidate_rows", rows), ("2017_plus_candidate_rows", [(d,p) for d,p in rows if d >= "2017-01-01"])):
        entries = []
        for field in FIELDS:
            present = [(d,p[field]) for d,p in sample if field in p and p[field] is not None and str(p[field]).strip() not in ("", "-")]
            entries.append({"api_field": field, "denominator": len(sample), "present_count_including_zero": len(present),
                            "missing_rate": 1-len(present)/len(sample), "zero_count": sum(v == 0 for _,v in present),
                            "first_present_date": min((d for d,_ in present), default=None),
                            "last_present_date": max((d for d,_ in present), default=None),
                            "most_common_raw_values": Counter(str(v) for _,v in present).most_common(15)})
        result[name] = entries
    con.close()
    after = DB.stat()
    assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    with (HERE / "condition_inventory.json").open("x",encoding="utf-8") as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2,allow_nan=False)
        handle.write("\n")
    print("Race-condition audit completed without DB mutation",flush=True)


if __name__ == "__main__":
    main()
