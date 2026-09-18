"""Verify the final isolated Jeju race-time ID research materialization."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    a = ap.parse_args()
    manifest = json.loads((a.root / "manifest.json").read_text())
    for path, expected in manifest["input_sha256"].items():
        assert sha(Path(path)) == expected, path
    for name, expected in manifest["output_sha256"].items():
        assert sha(a.root / name) == expected, name
    linked = rows(a.root / "linked_official_ids.jsonl")
    unresolved = rows(a.root / "unresolved_29.jsonl")
    all_rows = linked + unresolved
    keys = [(r["meet"], r["race_date"], r["race_number"], r["horse_id"]) for r in all_rows]
    assert len(linked) == 90863 and len(unresolved) == 29 and len(set(keys)) == 90892
    assert len({(r["race_date"], r["race_number"]) for r in all_rows}) == 9288
    assert all(r["meet"] == 2 and r["rank"].startswith("제") for r in all_rows)
    assert all(isinstance(r[field], str) and len(r[field]) == (7 if field == "hrNo" else 6)
               and r[field].isdecimal() for r in linked for field in ("hrNo", "trNo", "owNo"))
    assert all(r["hrNo"] == r["horse_id"] for r in all_rows)
    assert Counter(issue for r in unresolved for issue in r["issues"]) == {
        "missing_official_trNo": 25, "official_row_absent_from_db": 4}
    assert sum(r["owner_review_evidence"] is not None for r in linked) == 1132
    assert sum(r["owner_review_evidence"] is not None for r in unresolved) == 1
    source_cache: dict[Path, tuple[str, list[str]]] = {}
    for row in all_rows:
        evidence = row["official_result_evidence"]
        path = Path(evidence["path"])
        if path not in source_cache:
            source_cache[path] = (sha(path), path.read_text().splitlines())
        file_hash, lines = source_cache[path]
        assert file_hash == evidence["filtered_file_sha256"]
        raw = json.loads(lines[evidence["line"] - 1])
        assert str(raw["rcDate"]) == row["race_date"] and int(raw["rcNo"]) == row["race_number"]
        assert str(raw["hrNo"]) == row["horse_id"] and int(raw["chulNo"]) == row["horse_number"]
        assert row["owNo"] == str(raw["owNo"]).zfill(6)
        if row["trNo"] is not None:
            assert row["trNo"] == str(raw["trNo"]).zfill(6)
        else:
            assert raw["trNo"] == "0BBBBB"
    annual = json.loads((a.root / "annual_coverage.json").read_text())
    assert sum(x["three_official_ids_linked"] for x in annual) == len(linked)
    assert sum(x["unresolved_rows"] for x in annual) == len(unresolved)
    assert sum(x["confirmed_positive_result_races"] for x in annual) == 9288
    assert sum(x["confirmed_race_rows"] for x in annual) == len(all_rows)
    assert len([r for r in linked if r["race_date"] == "20020728"]) == 8
    result = {"passed": True, "verified_rows": len(all_rows), "linked": len(linked),
              "unresolved": len(unresolved), "races": 9288, "source_files_checked": len(source_cache),
              "owner_review_linked": 1132}
    (a.root / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
