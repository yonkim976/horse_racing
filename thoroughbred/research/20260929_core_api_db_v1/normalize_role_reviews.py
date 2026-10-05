"""Normalize audited official event links and verify their HTML evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
import duckdb

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "thoroughbred/research/20261001_role_review_v1"
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/backups/20261001_before_trainer_owner_review/thoroughbred_core.duckdb"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def official_row(path, horse_id, program, trial):
    soup = BeautifulSoup(path.read_bytes(), "html.parser")
    rows = []
    horse_function = "goPage1" if trial else "goHorse"
    pattern = re.compile(r"\b" + horse_function + r"\(\s*['\"]([^'\"]+)['\"]")
    for row in soup.select("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3 or cells[1].get_text(strip=True) != program:
            continue
        links = cells[2].find_all("a")
        ids = [m.group(1) for link in links for attribute in ("href", "onclick")
               for m in pattern.finditer(link.get(attribute, ""))]
        if horse_id in ids:
            rows.append(row)
    if len(rows) != 1:
        raise ValueError(f"Official event row not unique: {path}, {horse_id}, {program}")
    return rows[0]


def link_id(row, role, trial):
    function = {("trainer", True): "goPage3", ("trainer", False): "goTrainer",
                ("owner", False): "goOwner"}[(role, trial)]
    pattern = re.compile(r"\b" + function + r"\(\s*['\"]([^'\"]+)['\"]")
    ids = {m.group(1) for link in row.find_all("a") for attr in ("href", "onclick")
           for m in pattern.finditer(link.get(attr, ""))}
    if len(ids) != 1:
        raise ValueError(f"Official {role} ID link not unique: {ids}")
    return next(iter(ids))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--race-jsonl", type=Path, required=True)
    parser.add_argument("--trial-jsonl", type=Path, required=True)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    files = {}
    counts = {}
    con = duckdb.connect(str(DB), read_only=True)
    try:
        for kind, source, expected in (("race", args.race_jsonl, 60), ("trial", args.trial_jsonl, 224)):
            source = source.resolve()
            if not source.is_relative_to(ROOT):
                raise ValueError("Review source must be inside repository")
            rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(rows) != expected:
                raise ValueError(f"Unexpected {kind} audit size: {len(rows)}")
            normalized = []
            for item in rows:
                evidence_fields = (
                    ("official_web_source_file", "official_web_source_sha256" if kind == "trial" else "official_web_source_hash"),
                    ("source_api_file", "source_api_file_sha256"),
                    ("rpt_source_file", "rpt_source_sha256"),
                    ("api4_3_source_file", "api4_3_source_sha256"),
                    ("api26_recheck_source_file", "api26_recheck_sha256"),
                )
                for path_key, digest_key in evidence_fields:
                    if item.get(path_key) and item.get(digest_key):
                        evidence = (ROOT / item[path_key]).resolve()
                        if not evidence.is_relative_to(ROOT) or sha(evidence) != item[digest_key]:
                            raise ValueError(f"Source evidence changed: {item[path_key]}")
                        files[evidence.relative_to(ROOT).as_posix()] = {"sha256": sha(evidence)}
                row = {key: str(item[key]) for key in ("meet", "date", "horse_program_no")}
                row["horse_id"] = str(item["resolved_horse_id"] if kind == "trial" else item["horse_id"])
                row["review_status"] = item["review_status"]
                if kind == "trial":
                    row["trial_no"] = str(item["trial_no"])
                    row["participant_row_id"] = item["participant_row_id"]
                else:
                    row["race_no"] = str(item["race_no"])
                if kind == "trial":
                    baseline = con.execute("""
                        SELECT api_trNo, api_rcTime FROM trial_participants_entity_reviewed
                        WHERE participant_row_id=? AND source_meet_query=? AND api_trainDate=?
                          AND api_trainNo=? AND api_chulNo=? AND resolved_horse_id=?
                          AND trainer_entity_id IS NULL
                    """, [row["participant_row_id"], row["meet"], row["date"], row["trial_no"],
                          row["horse_program_no"], row["horse_id"]]).fetchall()
                else:
                    baseline = con.execute("""
                        SELECT trainer_id_raw, finish_time_seconds_raw
                        FROM confirmed_runners_entity_reviewed
                        WHERE source_meet=? AND result_date=? AND result_race_no=?
                          AND horse_program_no_raw=? AND horse_id_raw=?
                          AND trainer_entity_id_with_review IS NULL
                    """, [row["meet"], row["date"], row["race_no"], row["horse_program_no"],
                          row["horse_id"]]).fetchall()
                if len(baseline) != 1:
                    raise ValueError("Review target is not an exact baseline exception")
                for role in (("trainer",) if kind == "trial" else ("trainer", "owner")):
                    value = item.get(f"verified_supplemental_{role}_id")
                    if value is not None and (not isinstance(value, str) or value in ("", "-", "0AAAAA")):
                        raise ValueError(f"Invalid reviewed {role} ID type/value")
                    row[f"verified_{role}_id"] = value
                    row[f"verified_{role}_name"] = item.get(f"verified_supplemental_{role}_name") if value else None
                if baseline[0][0] == "0AAAAA" and row["verified_trainer_id"]:
                    raise ValueError("Cannot convert source placeholder to a person")
                observed = item.get("official_trainer_id_observed") if kind == "trial" else item.get("official_web_trainer_id_observed")
                row["trainer_exception_class"] = (
                    "resolved_official_event_link" if row["verified_trainer_id"] else
                    "confirmed_non_person_placeholder" if baseline[0][0] == "0AAAAA" or observed == "0AAAAA" else
                    "unresolved_no_exact_official_person_id"
                )
                if any(row.get(f"verified_{r}_id") for r in ("trainer", "owner")):
                    path = (ROOT / item["official_web_source_file"]).resolve()
                    if not path.is_relative_to(ROOT):
                        raise ValueError("Evidence path escaped repository")
                    digest_key = "official_web_source_sha256" if kind == "trial" else "official_web_source_hash"
                    if sha(path) != item[digest_key]:
                        raise ValueError("Official raw evidence changed")
                    html_row = official_row(path, row["horse_id"], row["horse_program_no"], kind == "trial")
                    if kind == "trial":
                        official_time = html_row.find_all("td", recursive=False)[12].get_text(strip=True)
                        match = re.fullmatch(r"(\d+):(\d+(?:\.\d+)?)", official_time)
                        api_time = float(baseline[0][1])
                        if (api_time > 0 and not match) or (match and abs(int(match[1])*60+float(match[2])-api_time) > 0.05):
                            raise ValueError("Official trial time differs from API")
                    for role in ("trainer", "owner"):
                        if row.get(f"verified_{role}_id") and link_id(html_row, role, kind == "trial") != row[f"verified_{role}_id"]:
                            raise ValueError(f"Reviewed {role} ID differs from official event link")
                row["audit_source_file"] = source.relative_to(ROOT).as_posix()
                normalized.append(row)
            name = "race_role_review.csv" if kind == "race" else "trial_trainer_review.csv"
            dest = OUT / name
            with dest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(normalized[0]))
                writer.writeheader()
                writer.writerows(normalized)
            table = "race_trainer_owner_review" if kind == "race" else "trial_trainer_review"
            counts[table] = len(normalized)
            for role in (("trainer",) if kind == "trial" else ("trainer", "owner")):
                counts[f"{kind}_new_{role}_ids"] = sum(bool(r.get(f"verified_{role}_id")) for r in normalized)
            # Pin upstream audits, scripts, manifests and every saved raw capture.
            for path in source.parent.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    files[path.relative_to(ROOT).as_posix()] = {"sha256": sha(path)}
            files[dest.relative_to(ROOT).as_posix()] = {"sha256": sha(dest)}
    finally:
        con.close()
    manifest = {"built_at_utc": datetime.now(timezone.utc).isoformat(),
                "worker_model": "gpt-6-luna", "worker_reasoning_effort": "xhigh",
                "counts": counts, "files": files,
                "checks": {"target_counts": True, "string_ids": True,
                           "verified_ids_match_exact_official_html_row_links": True}}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
