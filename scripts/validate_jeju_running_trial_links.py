"""Independently check the isolated Jeju running-trial linkage artifacts."""

from __future__ import annotations

import collections
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_running_trial_links_20260915"


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def main() -> dict:
    sources = read(OUT / "text_source_manifest.jsonl")
    requests = read(OUT / "official_request_manifest.jsonl")
    cached = read(OUT / "official_response_cache.jsonl")
    profiles = read(OUT / "profile_request_manifest.jsonl")
    linked = read(OUT / "linked_native_trials_final.jsonl")
    unresolved = read(OUT / "unresolved_trials_final.jsonl")
    errors = []
    for source in sources:
        payload = (ROOT / source["path"]).read_bytes()
        if hashlib.sha256(payload).hexdigest() != source["sha256"]:
            errors.append(f"text_hash:{source['path']}")
    request_keys = [(r["date"], r["race_number"]) for r in requests]
    if len(request_keys) != len(set(request_keys)):
        errors.append("duplicate_request_key")
    official = {(r["date"], r["race_number"]): r for r in cached}
    if set(request_keys) != set(official):
        errors.append("request_cache_key_mismatch")
    profiles_by_id = {r["hrNo"]: r for r in profiles}
    native_race_ids = {
        str(r["hrNo"])
        for r in read(ROOT / "data/research/jeju_confirmed_race_time_ids_20260914/linked_official_ids.jsonl")
    }
    seen = set()
    breed_counts = collections.Counter()
    for row in linked:
        key = (row["trial_date"], row["trial_race_number"], row["horse_number"])
        if key in seen:
            errors.append(f"duplicate_link:{key}")
        seen.add(key)
        if not isinstance(row["hrNo"], str) or not row["hrNo"].isdigit():
            errors.append(f"nonstring_hrNo:{key}")
        if row["text_breed"] not in {"제", None}:
            errors.append(f"nonnative_text_breed:{key}")
        if hashlib.sha256((ROOT / row["text_source"]).read_bytes()).hexdigest() != row["text_sha256"]:
            errors.append(f"link_text_hash:{key}")
        cache = official.get(key[:2])
        if not cache or cache["request"].get("response_sha256") != row["official_response_sha256"]:
            errors.append(f"response_hash:{key}")
            continue
        matched = [r for r in cache["official_rows"] if r["horse_number"] == row["horse_number"]]
        if len(matched) != 1 or matched[0]["hrNo"] != row["hrNo"] or matched[0]["horse_name"] != row["horse_name"]:
            errors.append(f"official_match:{key}")
        if row["breed_evidence"] == "text_explicit_je":
            if row["text_breed"] != "제":
                errors.append(f"breed_text:{key}")
        elif row["breed_evidence"] == "official_horse_profile_jeju":
            profile = profiles_by_id.get(row["hrNo"])
            if not profile or profile.get("profile_hrNo") != row["hrNo"] or profile.get("breed") != "제주마" or profile.get("response_sha256") != row.get("profile_response_sha256"):
                errors.append(f"breed_profile:{key}")
        elif row["breed_evidence"] == "confirmed_native_race_hrNo":
            if row["hrNo"] not in native_race_ids:
                errors.append(f"breed_race_roster:{key}")
        else:
            errors.append(f"breed_evidence_unknown:{key}")
        breed_counts[row["breed_evidence"]] += 1
    unresolved_keys = {(r["trial_date"], r["trial_race_number"], r["horse_number"]) for r in unresolved}
    if seen & unresolved_keys:
        errors.append("linked_unresolved_overlap")
    if len(unresolved_keys) != len(unresolved):
        errors.append("duplicate_unresolved_key")
    annual = collections.Counter(r["trial_date"][:4] for r in linked)
    db_rows = {}
    connection = sqlite3.connect(f"file:{ROOT / 'data/horse_racing.sqlite3'}?mode=ro", uri=True)
    for day, race, horse_number, name, hr_no in connection.execute(
        "SELECT t.trial_date_local,t.trial_race_number,r.horse_number,r.horse_name_raw,h.kra_horse_id "
        "FROM running_trial_results r JOIN running_trials t ON t.id=r.running_trial_id "
        "LEFT JOIN horses h ON h.id=r.horse_id WHERE t.meet_code=2"
    ):
        db_rows[(day.replace("-", ""), race, horse_number)] = (name, hr_no)
    connection.close()
    text_2025 = {(r["date"], r["race_number"], x["horse_number"]): x["horse_name"]
                 for r in cached if r["date"] >= "20250101"
                 for x in r["official_rows"]}
    db_conflicts = []
    for row in linked:
        key = (row["trial_date"], row["trial_race_number"], row["horse_number"])
        if key not in db_rows:
            continue
        db_name, db_hr_no = db_rows[key]
        if db_name != row["horse_name"] or (db_hr_no and db_hr_no != row["hrNo"]):
            db_conflicts.append({"date": key[0], "race": key[1], "horse_number": key[2], "official_hrNo": row["hrNo"], "db_hrNo": db_hr_no, "official_name": row["horse_name"], "db_name": db_name})
    (OUT / "db_crosscheck_conflicts.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in db_conflicts), encoding="utf-8"
    )
    checks = {
        "passed": not errors,
        "errors": errors[:100],
        "text_source_hashes_checked": len(sources),
        "unique_official_requests": len(request_keys),
        "linked_rows_checked": len(linked),
        "unresolved_rows_checked": len(unresolved),
        "breed_evidence_counts": dict(breed_counts),
        "boundary_2003_07_11_linked": sum(r["trial_date"] == "20030711" for r in linked),
        "boundary_2015_linked": annual["2015"],
        "boundary_2025_linked": annual["2025"],
        "db_meet2_trial_rows": len(db_rows),
        "db_keys_absent_from_official_cache_2025plus": len(set(db_rows) - set(text_2025)),
        "db_official_id_conflicts_on_linked_rows": len(db_conflicts),
    }
    (OUT / "validation.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return checks


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
