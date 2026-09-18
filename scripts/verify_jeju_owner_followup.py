"""Verify the owner conflict resolution and non-result race classification."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    a = ap.parse_args()
    summary = json.loads((a.root / "summary.json").read_text())
    assert sha(Path(summary["inputs"]["links"])) == summary["inputs"]["links_sha256"]
    assert sha(Path(summary["inputs"]["database"])) == summary["inputs"]["database_sha256"]
    assert sha(Path(summary["inputs"]["entry_sheet_probe"])) == summary["inputs"]["entry_sheet_probe_sha256"]
    for name, expected in summary["outputs"].items():
        assert sha(a.root / name) == expected, name
    support = rows(a.root / "supported_race_specific_owNo.jsonl")
    held = rows(a.root / "held_owner_name_disagreements.jsonl")
    absent = rows(a.root / "api_rows_absent_from_db_by_race.jsonl")
    no_result = rows(a.root / "no_positive_result_races.jsonl")
    annual = json.loads((a.root / "positive_result_annual_coverage.json").read_text())
    probes = json.loads(Path(summary["inputs"]["entry_sheet_probe"]).read_text())
    by_probe = {(r["race_date"], r["race_number"], r["horse_id"], r["horse_number"]): r for r in probes}
    assert len(support) == 1133 and not held
    assert len({(r["race_date"], r["race_number"], r["horse_id"]) for r in support}) == 1133
    assert all(r["race_time_owNo"] == str(r["api_owNo"]).zfill(6) for r in support)
    assert Counter(r["decision"] for r in support) == {"result_and_text_agree": 1128,
                                                         "result_and_entry_sheet_agree_text_differs": 5}
    for row in support:
        if row["decision"] != "result_and_entry_sheet_agree_text_differs":
            continue
        probe = by_probe[(row["race_date"], row["race_number"], row["horse_id"], row["horse_number"])]
        assert probe["owNo"] == row["race_time_owNo"] and probe["owName"] == row["api_owner_name"]
    whole = [r for r in absent if r["kind"] == "whole_race_absent_from_db"]
    partial = [r for r in absent if r["kind"] == "individual_horse_key_mismatch"]
    assert len(whole) == 73 and sum(r["official_rows_absent_from_db"] for r in whole) == 724
    assert len(partial) == 4 and sum(r["official_rows_absent_from_db"] for r in partial) == 4
    no_result_keys = {(r["race_date"], r["race_number"]) for r in no_result}
    assert all((r["race_date"], r["race_number"]) in no_result_keys for r in whole)
    assert all((r["race_date"], r["race_number"]) not in no_result_keys for r in partial)
    assert len(no_result) == 135 and sum(r["rows"] for r in no_result) == 1316
    assert sum(r["rows_in_those_races"] for r in annual) == 90892
    assert sum(r["three_ids_linked_after_owner_review"] for r in annual) == 90863
    result = {"passed": True, "owner_rows_supported": 1133, "entry_sheet_boundary_rows": 5,
              "api_only_no_positive_result_rows": 724, "true_horse_key_mismatch_rows": 4,
              "positive_result_rows": 90892, "three_ids_linked": 90863}
    (a.root / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
