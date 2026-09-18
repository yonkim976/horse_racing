"""Verify whether archived '검' trial rows can be excluded from native Jeju.

This stores only aggregate breed counts and request/response hashes. Mixed-breed
official pages and non-native horse rows are never copied into the research set.
"""

from __future__ import annotations

import collections
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_jeju_running_trial_links import fetch_one, load_trials  # noqa: E402
from confirm_jeju_trial_breed_profiles import fetch_profile  # noqa: E402

OUT = ROOT / "data/research/jeju_native_200m_readiness_20260915"


def audit(workers: int = 4) -> dict:
    trials, _ = load_trials()
    inspection = []
    text_sources = set()
    for trial in trials:
        for row in trial["results"]:
            if row["origin_country"] == "검":
                inspection.append((trial["date"], trial["race_number"], row["horse_number"], row["horse_name"]))
                text_sources.add((trial["source_path"], trial["source_sha256"]))
    keys = sorted({(day, race) for day, race, _, _ in inspection})
    pages = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(fetch_one, key) for key in keys]):
            key, request, official = future.result()
            pages[key] = (request, official)
    matched_ids = []
    issues = collections.Counter()
    for day, race, number, name in inspection:
        request, rows = pages[(day, race)]
        if request.get("error"):
            issues["official_request_error"] += 1
            continue
        matches = [r for r in rows if r["horse_number"] == number and r["horse_name"] == name and r["meet"] == "2"]
        if len(matches) != 1:
            issues["official_row_missing_or_conflicting"] += 1
            continue
        matched_ids.append(matches[0]["hrNo"])
    profiles = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(fetch_profile, hr_no) for hr_no in sorted(set(matched_ids))]):
            hr_no, response = future.result()
            profiles[hr_no] = response
    breed_ids = collections.Counter()
    breed_rows = collections.Counter()
    for hr_no, response in profiles.items():
        if response.get("error") or response.get("profile_hrNo") != hr_no:
            issues["profile_identity_or_request_error"] += 1
            continue
        breed_ids[response.get("breed") or "unknown"] += 1
    for hr_no in matched_ids:
        response = profiles.get(hr_no)
        if response and response.get("profile_hrNo") == hr_no:
            breed_rows[response.get("breed") or "unknown"] += 1
    summary = {
        "text_code": "검",
        "text_rows": len(inspection),
        "text_files": len(text_sources),
        "official_pages": len(keys),
        "official_rows_matched": len(matched_ids),
        "unique_official_horse_ids": len(profiles),
        "profile_breed_unique_horses": dict(breed_ids),
        "profile_breed_rows": dict(breed_rows),
        "issues": dict(issues),
        "decision": "exclude_from_native_jeju_only_if_all_profiles_confirm_non_jeju",
        "source_file_sha256": [{"path": path, "sha256": sha} for path, sha in sorted(text_sources)],
        "official_request_hashes": [{"date": day, "race_number": race, "request_sha256": pages[(day, race)][0]["request_sha256"], "response_sha256": pages[(day, race)][0].get("response_sha256")} for day, race in keys],
        "profile_request_hashes": [{"request_sha256": response["request_sha256"], "response_sha256": response.get("response_sha256"), "breed": response.get("breed")} for response in profiles.values()],
    }
    assert len(inspection) == 29
    assert not issues, issues
    assert sum(breed_rows.values()) == len(inspection)
    assert all(breed not in {"제주마", "unknown"} for breed in breed_rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "inspection_exclusion_audit.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {k: v for k, v in summary.items() if k not in {"source_file_sha256", "official_request_hashes", "profile_request_hashes"}}


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
