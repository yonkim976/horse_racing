"""Preserve native-source follow-up for shared-DB result gaps; read-only only."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261014_pool_dividend_frequency_v1"
SHARED_DB = ROOT / "data/horse_racing.sqlite3"
NATIVE_DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
MEET = 2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_shared_entries(races: list[dict]) -> dict[tuple[str, int], list[tuple[int, str | None]]]:
    connection = sqlite3.connect(f"file:{SHARED_DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    entries = {}
    for race in races:
        rows = connection.execute(
            """SELECT e.horse_number, h.kra_horse_id
               FROM races r JOIN racecourses c ON c.id = r.racecourse_id
               JOIN race_entries e ON e.race_id = r.id
               LEFT JOIN horses h ON h.id = e.horse_id
               WHERE c.kra_meet_code = ? AND r.race_date_local = ? AND r.race_number = ?
               ORDER BY e.horse_number""",
            (MEET, race["race_date"], race["race_number"]),
        ).fetchall()
        entries[(race["race_date"], race["race_number"])] = [
            (int(row["horse_number"]), None if row["kra_horse_id"] is None else str(row["kra_horse_id"]))
            for row in rows
        ]
    connection.close()
    return entries


def main() -> None:
    preliminary_path = STUDY / "SOURCE_PREFLIGHT.json"
    preliminary = json.loads(preliminary_path.read_text(encoding="utf-8"))
    candidates = preliminary["candidate_races"]
    ties = []
    missing_without_tie = []
    for race in candidates:
        counts = [int(race["official_rank1_3_counts"][str(rank)]) for rank in (1, 2, 3)]
        if any(count > 1 for count in counts):
            ties.append(race)
        elif any(count == 0 for count in counts):
            missing_without_tie.append(race)
    if len(ties) != 10 or len(missing_without_tie) != 27:
        raise ValueError("shared source podium exception split changed")

    shared_entries = read_shared_entries(missing_without_tie)
    connection = sqlite3.connect(f"file:{NATIVE_DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    detail = []
    raw_status_patterns: Counter[tuple[tuple[str, int], ...]] = Counter()
    raw_artifacts: dict[int, dict] = {}
    matched_races = 0
    for race in missing_without_tie:
        date_value, race_no = race["race_date"], int(race["race_number"])
        rows = connection.execute(
            """SELECT rr.api_record_id, rr.horse_number, rr.horse_id, rr.finish_position,
                      rr.finish_status_raw, rr.breed_assessment,
                      ar.payload_json, sa.source_artifact_id, sa.endpoint,
                      sa.raw_relative_path, sa.sha256
               FROM race_result_rows rr
               JOIN api_records ar ON ar.api_record_id = rr.api_record_id
               JOIN source_artifacts sa ON sa.source_artifact_id = ar.source_artifact_id
               WHERE rr.meet_code = ? AND rr.race_date = ? AND rr.race_number = ?
               ORDER BY rr.horse_number""",
            (MEET, date_value, race_no),
        ).fetchall()
        native_keys = [(int(row["horse_number"]), str(row["horse_id"])) for row in rows]
        shared_keys = sorted((number, horse_id) for number, horse_id in shared_entries[(date_value, race_no)])
        if sorted(native_keys) != shared_keys:
            raise ValueError(f"native/shared official entry keys differ: {date_value} R{race_no}")
        matched_races += 1

        ord_counts: Counter[str] = Counter()
        raw_result_time_positive = 0
        status_counts: Counter[str] = Counter()
        rank_counts: Counter[str] = Counter()
        assessments: Counter[str] = Counter()
        artifact_rows = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            raw_ord = str(payload.get("ord"))
            ord_counts[raw_ord] += 1
            status_counts[str(row["finish_status_raw"])] += 1
            rank_counts[str(row["finish_position"])] += 1
            assessments[str(row["breed_assessment"])] += 1
            try:
                raw_result_time_positive += int(float(payload.get("rcTime") or 0) > 0)
            except (TypeError, ValueError):
                pass
            artifact = {
                "source_artifact_id": int(row["source_artifact_id"]),
                "endpoint": str(row["endpoint"]),
                "raw_relative_path": str(row["raw_relative_path"]),
                "sha256": str(row["sha256"]),
            }
            artifact_rows[artifact["source_artifact_id"]] = artifact

        for artifact in artifact_rows.values():
            if not artifact["endpoint"].endswith("/API4_3/raceResult_3"):
                raise ValueError("native result record does not reference API4_3")
            raw_path = (ROOT / artifact["raw_relative_path"]).resolve()
            if not raw_path.is_relative_to(ROOT) or raw_path.is_symlink() or not raw_path.is_file():
                raise ValueError("native API4 source path failed boundary checks")
            if sha256(raw_path) != artifact["sha256"]:
                raise ValueError("native API4 source SHA-256 mismatch")
            raw_artifacts[artifact["source_artifact_id"]] = artifact

        raw_status_patterns[tuple(sorted(ord_counts.items()))] += 1
        detail.append(
            {
                "race_date": date_value,
                "race_number": race_no,
                "shared_entry_rows": len(shared_keys),
                "native_result_rows": len(rows),
                "exact_horse_number_and_id_keyset_matches_shared_entries": True,
                "raw_official_ord_counts": dict(sorted(ord_counts.items())),
                "native_finish_status_raw_counts": dict(sorted(status_counts.items())),
                "native_finish_position_counts": dict(sorted(rank_counts.items())),
                "raw_result_time_positive_rows": raw_result_time_positive,
                "breed_assessment_counts": dict(sorted(assessments.items())),
                "source_artifacts": sorted(artifact_rows.values(), key=lambda item: item["source_artifact_id"]),
            }
        )
    connection.close()

    formatting_path = ROOT / "src/horse_racing/web/formatting.py"
    contract_path = ROOT / "src/horse_racing/analysis/pre_race_field_contract.py"
    raw_99_races = sum(
        count for pattern, count in raw_status_patterns.items()
        if len(pattern) == 1 and pattern[0][0] == "99"
    )
    raw_0_races = sum(
        count for pattern, count in raw_status_patterns.items()
        if len(pattern) == 1 and pattern[0][0] == "0"
    )
    result = {
        "study": "20261014_pool_dividend_frequency_v1",
        "status": "native_result_followup_no_dividend_histograms",
        "preliminary_source_preflight_sha256": sha256(preliminary_path),
        "population_classification": {
            "candidate_races_stored_as_completed": len(candidates),
            "unique_top3_and_all_seven_pool_keys_covered": preliminary["population"]["unique_top3_and_all_seven_pool_keys_covered"],
            "top3_tie_races_excluded": len(ties),
            "no_top3_rank_and_no_tie_races_excluded": len(missing_without_tie),
            "native_result_match_for_all_27_missing_races": matched_races == len(missing_without_tie),
            "interpretation": "The shared results and native API4 result rows provide no valid unique 1st/2nd/3rd for these races. Raw 99 is the repository's documented race-cancelled/RACE_VOID code; raw 0 remains an unclassified no-rank outcome. Neither is reconstructed into a winning podium.",
        },
        "raw_rank_status_patterns": {
            "races_with_all_raw_ord_99": raw_99_races,
            "races_with_all_raw_ord_0": raw_0_races,
            "races_by_complete_raw_ord_pattern": [
                {"raw_ord_counts": dict(pattern), "races": count}
                for pattern, count in sorted(raw_status_patterns.items())
            ],
            "race_cancelled_code_reference": "src/horse_racing/web/formatting.py SPECIAL_FINISH_LABELS[99] and src/horse_racing/analysis/pre_race_field_contract.py SPECIAL_OUTCOMES[(99, '경주취소')]",
        },
        "source_artifacts": sorted(raw_artifacts.values(), key=lambda item: item["source_artifact_id"]),
        "missing_rank_races": detail,
        "read_only": {
            "shared_db_uri_mode": "ro",
            "native_db_uri_mode": "ro",
            "query_only": True,
            "cached_raw_file_sha256_checked": True,
            "network": False,
            "database_writes": False,
            "payout_amounts_or_histograms_computed": False,
        },
        "input_sha256": {
            "shared_db_file": sha256(SHARED_DB),
            "native_db_file": sha256(NATIVE_DB),
            "formatting_source": sha256(formatting_path),
            "field_contract_source": sha256(contract_path),
        },
    }
    output = STUDY / "SOURCE_PREFLIGHT_NATIVE_FOLLOWUP.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "population_classification": result["population_classification"],
        "raw_rank_status_patterns": result["raw_rank_status_patterns"],
        "source_artifacts": result["source_artifacts"],
        "read_only": result["read_only"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
