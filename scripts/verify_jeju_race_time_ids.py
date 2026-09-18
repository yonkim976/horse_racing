"""Independently verify the isolated Jeju race-time ID research ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def verify(root: Path) -> dict:
    validation = json.loads((root / "validation.json").read_text())
    assert sha(Path(validation["input_database"]["path"])) == validation["input_database"]["sha256"]
    for name, expected in validation["outputs"].items():
        assert sha(root / name) == expected, name
    source_manifest = json.loads((root / "source_requests_and_hashes.json").read_text())
    for source in source_manifest["old_sources"]:
        assert sha(Path(source["path"])) == source["sha256"]
    for source in source_manifest["new_api_requests"]:
        assert sha(Path(source["filtered_path"])) == source["filtered_sha256"]
        assert all(page["status_code"] == 200 for page in source["source_pages"])
        assert sum(page["returned_rows"] for page in source["source_pages"]) == source["source_pages"][0]["total_count"]
    links = read_jsonl(root / "race_time_official_id_links.jsonl")
    unresolved = read_jsonl(root / "unresolved_rows.jsonl")
    excluded = read_jsonl(root / "unconfirmed_db_rows.jsonl")
    key_counts = Counter((r["meet"], r["race_date"], r["race_number"], r["horse_id"]) for r in links)
    assert max(key_counts.values(), default=0) == 1
    assert all(r["meet"] == 2 and r["rank"].startswith("제") and "20020728" <= r["race_date"] <= "20260912" for r in links)
    assert all(not value or not value.startswith("text:")
               for r in links for value in r["linked_official_ids"].values())
    assert all(not value or (len(value) == (7 if field == "hrNo" else 6) and value.isdecimal())
               for r in links for field, value in r["linked_official_ids"].items())
    assert all(r["linked_official_ids"]["hrNo"] == r["horse_id"] for r in links)
    assert len(links) == validation["metrics"]["joined_rows"]
    assert len(excluded) == validation["metrics"]["excluded_unconfirmed_db_rows"]
    assert len(unresolved) == validation["metrics"]["unresolved_source_rows"] + sum("issue" in r for r in unresolved)
    source_lines: dict[Path, list[str]] = {}
    source_hashes: dict[Path, str] = {}
    for r in links:
        evidence = r["evidence"]
        source_path = Path(evidence["path"])
        if source_path not in source_lines:
            source_lines[source_path] = source_path.read_text().splitlines()
            source_hashes[source_path] = sha(source_path)
        assert source_hashes[source_path] == evidence["filtered_file_sha256"]
        source = json.loads(source_lines[source_path][evidence["line"] - 1])
        assert source["rcDate"] == int(r["race_date"])
        assert source["rcNo"] == r["race_number"]
        assert source["hrNo"] == r["raw_ids"]["hrNo"]
        assert source["trNo"] == r["raw_ids"]["trNo"]
        assert source["owNo"] == r["raw_ids"]["owNo"]
        if r["status"] == "linked_full":
            assert all(r["linked_official_ids"].values()) and not r["issues"]
            if r["db_values"]:
                assert r["horse_number"] == r["db_values"]["horse_number"]
                for field, db_field in (("trNo", "db_trNo"), ("owNo", "db_owNo")):
                    old = r["db_values"][db_field]
                    assert old.startswith("text:") or old == r["linked_official_ids"][field]
    cases = {
        "first_2002_07_28": [r for r in links if r["race_date"] == "20020728"],
        "boundary_2015_01_09": [r for r in links if r["race_date"] == "20150109"],
        "no_temporary_2025": [r for r in links if r["race_date"].startswith("2025")],
    }
    assert len(cases["first_2002_07_28"]) == 8
    assert all(r["status"] == "linked_full" for r in cases["first_2002_07_28"])
    assert len(cases["boundary_2015_01_09"]) > 0
    assert len(cases["no_temporary_2025"]) == 7071
    assert all(r["status"] == "linked_full" and r["db_values"] and
               not str(r["db_values"]["db_trNo"]).startswith("text:") and
               not str(r["db_values"]["db_owNo"]).startswith("text:")
               for r in cases["no_temporary_2025"])
    return {"passed": True, "source_page_records_checked": sum(len(s["source_pages"]) for s in source_manifest["new_api_requests"]),
            "old_source_files_checked": len(source_manifest["old_sources"]),
            "row_evidence_checked": len(links), "unique_join_keys": len(key_counts),
            "unresolved_ledger_rows": len(unresolved), "case_rows": {k: len(v) for k, v in cases.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = verify(args.root)
    (args.root / "independent_verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
