"""Materialize the confirmed-result Jeju race-time ID research ledger.

This uses only the previously archived official result rows, the read-only DB
reconciliation, and the independently supported owner-ID overlay. It does not
alter operational tables or any model artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def entry_key(row: dict) -> tuple:
    return (row["race_date"], int(row["race_number"]), row["horse_id"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--original", type=Path, default=Path("data/research/jeju_race_time_official_ids_20260914"))
    ap.add_argument("--owner-review", type=Path, default=Path("data/research/jeju_owner_conflict_followup_20260914_v4"))
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    original_path = a.original / "race_time_official_id_links.jsonl"
    original_unresolved_path = a.original / "unresolved_rows.jsonl"
    owner_path = a.owner_review / "supported_race_specific_owNo.jsonl"
    excluded_path = a.owner_review / "no_positive_result_races.jsonl"
    original = read_jsonl(original_path)
    owner_rows = read_jsonl(owner_path)
    owner_hash = sha(owner_path)
    owner = {entry_key(row): (row, line_no) for line_no, row in enumerate(owner_rows, 1)}
    if len(owner) != 1133:
        raise ValueError("Owner overlay key count changed")
    no_positive = {(row["race_date"], int(row["race_number"])) for row in read_jsonl(excluded_path)}
    db_only = defaultdict(list)
    for row in read_jsonl(original_unresolved_path):
        if row.get("issue") == "db_row_absent_from_official_native_race":
            db_only[(row["race_date"], int(row["race_number"]), int(row["horse_number"]))].append(row)
    linked, unresolved = [], []
    for row in original:
        if (row["race_date"], int(row["race_number"])) in no_positive:
            continue
        ids = dict(row["linked_official_ids"])
        issues = list(row["issues"])
        support = None
        match = owner.get(entry_key(row))
        if "conflicting_owNo" in issues:
            if match is None:
                raise ValueError(f"Owner conflict lacks verified overlay: {entry_key(row)}")
            overlay, line_no = match
            if overlay["race_time_owNo"] != str(row["raw_ids"]["owNo"]).zfill(6):
                raise ValueError(f"Owner overlay differs from official result: {entry_key(row)}")
            ids["owNo"] = overlay["race_time_owNo"]
            issues.remove("conflicting_owNo")
            support = {"path": str(owner_path), "line": line_no, "sha256": owner_hash,
                       "decision": overlay["decision"], "text_evidence": overlay["text_evidence"],
                       "entry_sheet_source_pages": overlay["official_entry_sheet_evidence"]}
        if any(value is not None and (not isinstance(value, str) or not value.isdecimal()) for value in ids.values()):
            raise ValueError(f"Non-string or nondecimal linked ID: {entry_key(row)}")
        final = {
            "meet": 2, "race_date": row["race_date"], "race_number": row["race_number"],
            "horse_id": row["horse_id"], "horse_number": row["horse_number"],
            "hrNo": ids["hrNo"], "trNo": ids["trNo"], "owNo": ids["owNo"],
            "db_entry_id": row["db_entry_id"], "rank": row["rank"],
            "official_result_evidence": row["evidence"], "owner_review_evidence": support,
        }
        if issues or not all(ids.values()):
            final["issues"] = issues
            final["api_raw_ids"] = row["raw_ids"]
            final["db_values"] = row["db_values"]
            final["names"] = row["names"]
            if "official_row_absent_from_db" in issues:
                final["same_number_db_candidates"] = db_only[(row["race_date"], int(row["race_number"]), int(row["horse_number"]))]
            unresolved.append(final)
        else:
            linked.append(final)
    linked.sort(key=lambda r: (r["race_date"], r["race_number"], r["horse_id"]))
    unresolved.sort(key=lambda r: (r["race_date"], r["race_number"], r["horse_id"]))
    if len(linked) != 90863 or len(unresolved) != 29:
        raise ValueError(f"Unexpected final counts: {len(linked)} linked, {len(unresolved)} unresolved")
    if len({entry_key(r) for r in linked + unresolved}) != 90892:
        raise ValueError("Duplicate or missing natural key")
    if sum("official_row_absent_from_db" in r["issues"] for r in unresolved) != 4:
        raise ValueError("Horse-key conflict count changed")
    if sum("missing_official_trNo" in r["issues"] for r in unresolved) != 25:
        raise ValueError("Trainer placeholder count changed")
    write_jsonl(a.output / "linked_official_ids.jsonl", linked)
    write_jsonl(a.output / "unresolved_29.jsonl", unresolved)
    annual = []
    for year in range(2002, 2027):
        good = [r for r in linked if r["race_date"].startswith(str(year))]
        bad = [r for r in unresolved if r["race_date"].startswith(str(year))]
        races = {(r["race_date"], r["race_number"]) for r in good + bad}
        annual.append({"year": year, "confirmed_positive_result_races": len(races),
                       "confirmed_race_rows": len(good) + len(bad),
                       "three_official_ids_linked": len(good), "unresolved_rows": len(bad),
                       "link_rate": round(len(good) / (len(good) + len(bad)), 8) if good or bad else None})
    (a.output / "annual_coverage.json").write_text(json.dumps(annual, ensure_ascii=False, indent=2) + "\n")
    manifest = {
        "scope": "meet=2, explicit rank 제, at least one normal numeric finish with positive race time in race",
        "period": ["2002-07-28", "2026-09-12"],
        "source_labeled_races_with_no_positive_result_quarantined": len(no_positive),
        "rows_linked": len(linked), "rows_unresolved": len(unresolved),
        "unresolved_issues": dict(Counter(issue for r in unresolved for issue in r["issues"])),
        "input_sha256": {str(p): sha(p) for p in (original_path, original_unresolved_path, owner_path, excluded_path)},
        "output_sha256": {p.name: sha(p) for p in a.output.iterdir() if p.is_file()},
        "rules": ["Original DB and raw responses are read only", "No name-only matching",
                  "Owner number supported by race-specific official result and Text or official entry sheet",
                  "0BBBBB is not an individual trainer ID", "No training/medical person attribution or model change"],
    }
    (a.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"linked": len(linked), "unresolved": len(unresolved), "races": sum(r["confirmed_positive_result_races"] for r in annual)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
