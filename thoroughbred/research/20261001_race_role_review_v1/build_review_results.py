"""Build the event-keyed review ledger from captured official pages and prior evidence."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CAPTURE_ROWS = HERE / "official_scoretable_runner_rows.jsonl"
CAPTURE_MANIFEST = HERE / "official_scoretable_capture_manifest.json"
PRIOR_AUDIT = ROOT / "thoroughbred/research/20260930_missing_entity_source_audit_v1/race_role_gap_audit.jsonl"
RESULTS = HERE / "race_role_review_results.jsonl"
MANIFEST = HERE / "race_role_review_manifest.json"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        str(row["meet"]), str(row.get("date", row.get("race_date"))),
        str(row["race_no"]), str(row["horse_program_no"]), str(row["horse_id"]),
    )


def main() -> None:
    captured = read_jsonl(CAPTURE_ROWS)
    prior = read_jsonl(PRIOR_AUDIT)
    prior_by_key = {key(row): row for row in prior}
    results: list[dict] = []
    for row in captured:
        event_key = key(row)
        old = prior_by_key.get(event_key)
        official = row.get("exact_event_row") or {}
        result = {
            "meet": row["meet"],
            "date": row["date"],
            "race_no": row["race_no"],
            "horse_program_no": row["horse_program_no"],
            "horse_id": row["horse_id"],
            "source_kind": row["source_kind"],
            "horse_name_api4_3": row["horse_name_api4_3"],
            "source_trainer_id_raw": row["source_trainer_id_raw"],
            "source_trainer_name_raw": row["source_trainer_name_raw"],
            "source_owner_id_raw": row["source_owner_id_raw"],
            "source_owner_name_raw": row["source_owner_name_raw"],
            "result_rank_raw": row["result_rank_raw"],
            "finish_time_seconds_raw": row["finish_time_seconds_raw"],
            "positive_finish_evidence": row["positive_finish_evidence"],
            "review_status": row["review_status"],
            "verified_supplemental_trainer_id": row["verified_supplemental_trainer_id"],
            "verified_supplemental_trainer_name": row["verified_supplemental_trainer_name"],
            "verified_supplemental_owner_id": row["verified_supplemental_owner_id"],
            "verified_supplemental_owner_name": row["verified_supplemental_owner_name"],
            "official_web_source_file": row["official_web_source_file"],
            "official_web_source_hash": row["official_web_source_sha256"],
            "official_web_observed_at_utc": row["observed_at_utc"],
            "official_web_request_url": row["request_url"],
            "official_web_capture_status": row["capture_status"],
            "official_web_page_title": row.get("page_title"),
            "official_web_exact_event_row": official or None,
            "official_web_horse_name": official.get("horse_name_web"),
            "official_web_trainer_id_observed": official.get("trainer_id_from_event_row_link"),
            "official_web_trainer_name_observed": official.get("trainer_name_web"),
            "official_web_owner_id_observed": official.get("owner_id_from_event_row_link"),
            "official_web_owner_name_observed": official.get("owner_name_web"),
            "official_web_horse_profile_meet_link": official.get("meet_from_event_row_link"),
            "official_web_trainer_profile_meet_link": official.get("trainer_meet_from_event_row_link"),
            "official_web_owner_profile_meet_link": official.get("owner_meet_from_event_row_link"),
            "event_row_role_link_meet_mismatch": row.get("event_row_role_link_meet_mismatch", False),
            "horse_name_alias_difference": row.get("horse_name_alias_difference", False),
            "api4_3_source_file": row["api4_3_source_file"],
            "api4_3_source_item_index_zero_based": row["api4_3_source_item_index_zero_based"],
            "api4_3_source_sha256": old.get("api4_3_source_sha256") if old else None,
            "api26_recheck_source_file": old.get("api26_recheck_source_file") if old else None,
            "api26_recheck_sha256": old.get("api26_recheck_sha256") if old else None,
            "api26_recheck_trainer_id": old.get("api26_recheck_trainer_id") if old else None,
            "api26_recheck_owner_id": old.get("api26_recheck_owner_id") if old else None,
            "api26_recheck_item_index_zero_based": old.get("api26_recheck_item_index_zero_based") if old else None,
        }
        # Hash the original API4_3 response for every row, including the 23 sentinels
        # which are outside the earlier blank-field audit.
        api43 = ROOT / row["api4_3_source_file"]
        result["api4_3_source_sha256"] = digest(api43)
        if result["api26_recheck_source_file"]:
            api26 = ROOT / result["api26_recheck_source_file"]
            if digest(api26) != result["api26_recheck_sha256"]:
                raise ValueError(f"Prior API26 recheck hash mismatch for {event_key}")
        results.append(result)

    results.sort(key=lambda row: (row["date"], row["meet"], int(row["race_no"]), int(row["horse_program_no"])))
    if len(results) != 60 or len({key(row) for row in results}) != 60:
        raise ValueError("Expected 60 unique event-keyed review rows")
    missing = [row for row in results if row["source_kind"] == "source_missing"]
    placeholders = [row for row in results if row["source_kind"] == "placeholder_0AAAAA"]
    if len(missing) != 37 or len(placeholders) != 23:
        raise ValueError("Expected 37 source-missing and 23 placeholder rows")
    if any(not row["verified_supplemental_trainer_id"] or not row["verified_supplemental_owner_id"] for row in missing):
        raise ValueError("A source-missing row lacks one of the official linked person IDs")
    if any(row["verified_supplemental_trainer_id"] is not None for row in placeholders):
        raise ValueError("Placeholder trainer sentinel must not be converted to a supplemental person ID")
    if any(row["positive_finish_evidence"] != "0" for row in results):
        raise ValueError("Unexpected positive-finish evidence in target set")

    RESULTS.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in results), encoding="utf-8")
    status_counts = dict(Counter(row["review_status"] for row in results))
    alias_rows = [key(row) for row in results if row["horse_name_alias_difference"]]
    link_meet_rows = [key(row) for row in results if row["event_row_role_link_meet_mismatch"]]
    manifest = {
        "captured_at_utc": json.loads(CAPTURE_MANIFEST.read_text(encoding="utf-8"))["captured_at_utc"],
        "official_source": "KRA race.kra.co.kr ScoretableDetailList.do; exact event page row links were parsed from saved response HTML",
        "target_row_count": len(results),
        "source_missing_count": len(missing),
        "source_missing_both_trainer_owner_ids_recovered_count": sum(bool(row["verified_supplemental_trainer_id"] and row["verified_supplemental_owner_id"]) for row in missing),
        "placeholder_count": len(placeholders),
        "placeholder_web_rows_confirming_source_sentinel_count": sum(
            row["official_web_trainer_id_observed"] == "0AAAAA" and row["official_web_trainer_name_observed"] == "휴양마"
            for row in placeholders
        ),
        "review_status_counts": status_counts,
        "horse_name_alias_difference_count": len(alias_rows),
        "horse_name_alias_difference_keys": [list(value) for value in alias_rows],
        "role_profile_meet_differs_from_event_count": len(link_meet_rows),
        "role_profile_meet_differs_from_event_keys": [list(value) for value in link_meet_rows],
        "all_target_rows_positive_finish_evidence_zero": True,
        "results_file": RESULTS.relative_to(ROOT).as_posix(),
        "results_file_sha256": digest(RESULTS),
        "capture_rows_file": CAPTURE_ROWS.relative_to(ROOT).as_posix(),
        "capture_rows_sha256": digest(CAPTURE_ROWS),
        "capture_manifest_file": CAPTURE_MANIFEST.relative_to(ROOT).as_posix(),
        "capture_manifest_sha256": digest(CAPTURE_MANIFEST),
        "row_schema": list(results[0].keys()),
        "id_policy": "IDs are retained as strings from goTrainer/goOwner links on the exact event-specific horse/program row; no RPT-name-only joins or current-profile backfill.",
        "placeholder_policy": "Keep source 0AAAAA/휴양마 values unchanged; official web observed values are separate; supplemental trainer ID remains null.",
        "alias_policy": "Keep source/API and web horse names separately; exact horse ID and program number establish the row; preserve profile-meet link arguments independently from event meet.",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "rows": len(results),
        "status_counts": status_counts,
        "aliases": len(alias_rows),
        "event_role_link_meet_mismatch": len(link_meet_rows),
        "results_sha256": manifest["results_file_sha256"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
