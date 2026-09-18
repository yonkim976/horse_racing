"""Explain Jeju owner-ID conflicts without changing the original ID ledger or DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from horse_racing.parsers.dacom11 import parse_dacom11_report


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--links", type=Path, default=Path("data/research/jeju_race_time_official_ids_20260914/race_time_official_id_links.jsonl"))
    ap.add_argument("--database", type=Path, default=Path("data/horse_racing.sqlite3"))
    ap.add_argument("--text-root", type=Path, default=Path("data/raw/kra_text/dacom11/meet=2"))
    ap.add_argument("--entry-probe", type=Path, default=Path("data/research/jeju_owner_boundary_entry_sheets_20260914/five_native_entry_sheet_rows.json"))
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(f"file:{a.database}?mode=ro", uri=True)
    owner_names = {code: name for code, name in db.execute("SELECT kra_owner_id,name_ko FROM owners")}
    all_rows = [json.loads(line) for line in a.links.read_text().splitlines()]
    entry_probes = json.loads(a.entry_probe.read_text())
    by_entry_probe = {(r["race_date"], r["race_number"], r["horse_id"], r["horse_number"]): r for r in entry_probes}
    dates = {r["race_date"] for r in all_rows if "conflicting_owNo" in r["issues"] or "official_row_absent_from_db" in r["issues"]}
    text_cache = {}
    for day in dates:
        matches = list(a.text_root.rglob(f"{day}dacom11.rpt"))
        if len(matches) > 1:
            raise ValueError(f"Duplicate Text file: {day}")
        if not matches:
            text_cache[day] = None
            continue
        path = matches[0]
        raw = path.read_bytes()
        parsed = parse_dacom11_report(raw)
        by_key = defaultdict(list)
        for race in parsed:
            for entry in race.entries:
                by_key[(race.race_number, entry.horse_number)].append(entry)
        text_cache[day] = {"path": str(path), "sha256": sha(raw), "races": {r.race_number for r in parsed}, "entries": by_key}

    resolved, held, pair_counts = [], [], Counter()
    for r in all_rows:
        if "conflicting_owNo" not in r["issues"]:
            continue
        old_id = r["db_values"]["db_owNo"]
        old_name = owner_names.get(old_id)
        official_name = r["names"]["owName"]
        text = text_cache[r["race_date"]]
        candidates = text["entries"][(r["race_number"], r["horse_number"])] if text else []
        if len(candidates) != 1 or candidates[0].horse_name != r["names"]["hrName"]:
            raise ValueError(f"Text race/horse row not unique: {r['race_date']}, {r['race_number']}, {r['horse_number']}")
        text_name = candidates[0].owner_name
        pair_counts[(official_name, str(r["raw_ids"]["owNo"]), old_name, old_id)] += 1
        probe = by_entry_probe.get((r["race_date"], r["race_number"], r["horse_id"], r["horse_number"]))
        text_agreement = official_name == text_name == old_name
        two_official_sources = bool(probe and probe["owNo"] == str(r["raw_ids"]["owNo"]).zfill(6)
                                    and probe["owName"] == official_name
                                    and all(page["status_code"] == 200 for page in probe["source_pages"]))
        accept = (text_agreement or two_official_sources) and r["horse_id"] == r["db_values"]["horse_id"]
        item = {
            "meet": 2, "race_date": r["race_date"], "race_number": r["race_number"],
            "horse_id": r["horse_id"], "horse_number": r["horse_number"], "db_entry_id": r["db_entry_id"],
            "api_owner_name": official_name, "api_owNo": r["raw_ids"]["owNo"],
            "race_time_owNo": str(r["raw_ids"]["owNo"]).zfill(6) if accept else None,
            "db_owner_name": old_name, "db_owNo": old_id, "text_owner_name": text_name,
            "decision": "result_and_text_agree" if text_agreement else "result_and_entry_sheet_agree_text_differs" if two_official_sources else "hold_sources_disagree",
            "official_result_evidence": r["evidence"],
            "official_entry_sheet_evidence": probe["source_pages"] if probe else None,
            "text_evidence": {"path": text["path"], "sha256": text["sha256"],
                              "race_number": r["race_number"], "horse_number": r["horse_number"]},
        }
        (resolved if accept else held).append(item)
    if len(resolved) != 1133 or held:
        raise ValueError(f"Unexpected owner conflict classification: {len(resolved)}, {len(held)}")
    jsonl(a.output / "supported_race_specific_owNo.jsonl", resolved)
    jsonl(a.output / "held_owner_name_disagreements.jsonl", held)

    by_race = defaultdict(list)
    for r in all_rows:
        by_race[(r["race_date"], r["race_number"])].append(r)
    absent_races = []
    for (day, number), rows in sorted(by_race.items()):
        missing = [r for r in rows if "official_row_absent_from_db" in r["issues"]]
        if not missing:
            continue
        txt = text_cache[day]
        if len(missing) == len(rows):
            kind = "whole_race_absent_from_db"
            text_status = "no_text_file" if txt is None else "race_not_in_text_file" if number not in txt["races"] else "race_in_text_file"
        else:
            kind = "individual_horse_key_mismatch"
            text_status = "no_text_file" if txt is None else "race_in_text_file" if number in txt["races"] else "race_not_in_text_file"
        absent_races.append({"meet": 2, "race_date": day, "race_number": number, "kind": kind,
                             "official_rows": len(rows), "official_rows_absent_from_db": len(missing),
                             "text_status": text_status,
                             "text_path": txt["path"] if txt else None,
                             "text_sha256": txt["sha256"] if txt else None,
                             "official_row_evidence": [r["evidence"] for r in missing],
                             "horse_ids": [r["horse_id"] for r in missing]})
    jsonl(a.output / "api_rows_absent_from_db_by_race.jsonl", absent_races)
    source_rows = {}
    for year in range(2002, 2027):
        path = (Path(f"data/raw/jeju_native_results/native_results_{year}.jsonl") if year <= 2014
                else a.links.parent / f"official_native_results_{year}.jsonl")
        for line in path.read_text().splitlines():
            raw = json.loads(line)
            source_rows[(str(raw["rcDate"]), int(raw["rcNo"]), str(raw["hrNo"]))] = raw
    no_positive = []
    positive_keys = set()
    for (day, number), rows in sorted(by_race.items()):
        normal = any(
            1 <= int(source_rows[(day, number, r["horse_id"])].get("ord") or 0) < 90
            and float(source_rows[(day, number, r["horse_id"])].get("rcTime") or 0) > 0
            for r in rows
        )
        if normal:
            positive_keys.add((day, number))
        else:
            no_positive.append({"meet": 2, "race_date": day, "race_number": number,
                                "rows": len(rows), "db_matched_rows": sum(r["db_entry_id"] is not None for r in rows),
                                "ord_counts": dict(Counter(str(source_rows[(day, number, r["horse_id"])].get("ord")) for r in rows)),
                                "source_evidence": [r["evidence"] for r in rows]})
    jsonl(a.output / "no_positive_result_races.jsonl", no_positive)
    supported_keys = {(r["race_date"], r["race_number"], r["horse_id"]) for r in resolved}
    annual = []
    for year in range(2002, 2027):
        positive = [r for r in all_rows if r["race_date"].startswith(str(year))
                    and (r["race_date"], r["race_number"]) in positive_keys]
        old_full = sum(r["status"] == "linked_full" for r in positive)
        owner_fixed = sum((r["race_date"], r["race_number"], r["horse_id"]) in supported_keys
                          and r["issues"] == ["conflicting_owNo"] for r in positive)
        annual.append({"year": year, "races_with_positive_result": len({(r["race_date"], r["race_number"]) for r in positive}),
                       "rows_in_those_races": len(positive), "three_ids_linked_before_owner_review": old_full,
                       "owner_ids_supported_by_review": owner_fixed,
                       "three_ids_linked_after_owner_review": old_full + owner_fixed,
                       "unresolved_source_rows_after_owner_review": len(positive) - old_full - owner_fixed})
    (a.output / "positive_result_annual_coverage.json").write_text(json.dumps(annual, ensure_ascii=False, indent=2) + "\n")
    issue_patterns = Counter(tuple(sorted(r["issues"])) for r in all_rows if r["issues"])
    summary = {
        "inputs": {"links": str(a.links), "links_sha256": sha(a.links.read_bytes()),
                   "database": str(a.database), "database_sha256": sha(a.database.read_bytes()),
                   "entry_sheet_probe": str(a.entry_probe), "entry_sheet_probe_sha256": sha(a.entry_probe.read_bytes())},
        "owner_conflict_rows": len(resolved) + len(held),
        "race_specific_api_owNo_supported": len(resolved),
        "owner_name_disagreements_held": len(held),
        "pair_counts": [{"api_name": n, "api_owNo": x, "db_name": dn, "db_owNo": y, "rows": count}
                        for (n, x, dn, y), count in pair_counts.most_common()],
        "api_absent_db_races": [{"kind": k, "text_status": s, "races": count}
                               for (k, s), count in Counter((r["kind"], r["text_status"]) for r in absent_races).items()],
        "api_absent_db_rows": sum(r["official_rows_absent_from_db"] for r in absent_races),
        "races_without_positive_result": len(no_positive),
        "rows_without_positive_race_result": sum(r["rows"] for r in no_positive),
        "races_with_positive_result": len(positive_keys),
        "rows_in_positive_result_races": sum(r["rows_in_those_races"] for r in annual),
        "three_ids_linked_after_owner_review_in_positive_result_races": sum(r["three_ids_linked_after_owner_review"] for r in annual),
        "issue_combinations": [{"issues": list(k), "rows": v} for k, v in issue_patterns.most_common()],
        "outputs": {p.name: sha(p.read_bytes()) for p in a.output.iterdir() if p.is_file()},
    }
    (a.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("owner_conflict_rows", "race_specific_api_owNo_supported", "owner_name_disagreements_held", "api_absent_db_races", "api_absent_db_rows", "issue_combinations")}, ensure_ascii=False))
    db.close()


if __name__ == "__main__":
    main()
