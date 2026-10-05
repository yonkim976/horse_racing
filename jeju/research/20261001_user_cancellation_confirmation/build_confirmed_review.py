"""Apply dated human cancellation confirmations to a new, auditable review ledger."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
PREVIOUS = HERE.parent / "20260930_zero_time_cause_audit/unresolved_76_review.jsonl"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def applies(assertion: dict, number: int) -> bool:
    scope = assertion["scope"]
    if scope == "all_races":
        return True
    if scope == "all_except_races":
        return number not in assertion["except_race_numbers"]
    if scope == "selected_races":
        return number in assertion["race_numbers"]
    raise ValueError(f"Unexpected assertion scope: {scope}")


def main() -> None:
    assertions = [json.loads(line) for line in (HERE / "user_assertions.jsonl").read_text(encoding="utf-8").splitlines()]
    by_date = {item["race_date"]: item for item in assertions}
    if len(assertions) != len(by_date):
        raise ValueError("Duplicate assertion dates")
    for item in assertions:
        date.fromisoformat(item["race_date"])
        if item["race_event_status"] != "cancelled" or item["reason_text"] is not None:
            raise ValueError("Expected cancellation confirmations without a supplied cause")

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        expanded = []
        for race_date, assertion in sorted(by_date.items()):
            races = conn.execute(
                """SELECT race_number,count(*) AS api_rows,
                          sum(CASE WHEN finish_time_seconds>0 THEN 1 ELSE 0 END) AS positive_finish_rows,
                          group_concat(DISTINCT rank_class_raw) AS rank_classes_raw,
                          group_concat(DISTINCT breed_assessment) AS breed_assessments,
                          sum(CASE WHEN EXISTS (
                              SELECT 1 FROM breed_evidence b WHERE b.horse_id=r.horse_id
                              AND b.breed_label_raw='제주' AND b.observed_event_date<=r.race_date
                          ) THEN 1 ELSE 0 END) AS prior_api20_jeju_rows,
                          sum(CASE WHEN EXISTS (
                              SELECT 1 FROM breed_evidence b WHERE b.horse_id=r.horse_id
                              AND b.breed_label_raw IN ('한라','한라(래)') AND b.observed_event_date<=r.race_date
                          ) THEN 1 ELSE 0 END) AS prior_api20_non_jeju_rows
                   FROM race_result_rows r WHERE meet_code=2 AND race_date=?
                   GROUP BY race_number ORDER BY race_number""",
                (race_date,),
            ).fetchall()
            if not races:
                raise ValueError(f"No API race rows for asserted date: {race_date}")
            existing_numbers = {row["race_number"] for row in races}
            if assertion["scope"] == "selected_races" and not set(assertion["race_numbers"]) <= existing_numbers:
                raise ValueError(f"Selected race missing in API: {race_date}")
            for race in races:
                number = race["race_number"]
                if not applies(assertion, number):
                    continue
                if race["positive_finish_rows"]:
                    raise ValueError(f"Cancellation contradicts positive API finish times: {race_date} {number}R")
                candidate_rows = conn.execute(
                    """SELECT count(*) FROM jeju_race_population_candidates
                       WHERE meet_code=2 AND race_date=? AND race_number=?""",
                    (race_date, number),
                ).fetchone()[0]
                expanded.append({
                    "race_date": race_date,
                    "meet_code": 2,
                    "race_number": number,
                    "api_rows": race["api_rows"],
                    "positive_api_finish_rows": race["positive_finish_rows"],
                    "rank_classes_raw": (race["rank_classes_raw"] or "").split(","),
                    "breed_assessments": race["breed_assessments"].split(","),
                    "native_population_candidate_rows": candidate_rows,
                    "prior_api20_jeju_observation_rows": race["prior_api20_jeju_rows"],
                    "prior_api20_non_jeju_observation_rows": race["prior_api20_non_jeju_rows"],
                    "race_event_status": "cancelled",
                    "cancellation_reason": None,
                    "cancellation_reason_status": "not_shown",
                    "confirmation_source": "user_review",
                    "confirmed_on": assertion["confirmed_on"],
                    "assertion_scope": assertion["scope"],
                    "original_user_text": assertion["original_user_text"],
                })

        review = [json.loads(line) for line in PREVIOUS.read_text(encoding="utf-8").splitlines()]
        if len(review) != 76 or sum(row["entrant_rows"] for row in review) != 680:
            raise ValueError("Expected the unchanged original 76-race review cohort")
        for row in review:
            assertion = by_date.get(row["race_date"])
            if row["official_website_cause"]:
                row.update({
                    "race_event_status": "cancelled",
                    "cancellation_confirmation_source": "official_website_explicit_reason",
                    "cancellation_reason_status": "specified",
                    "review_updated_on": "2026-10-01",
                })
            elif assertion and applies(assertion, row["race_number"]):
                row.update({
                    "race_event_status": "cancelled",
                    "cancellation_confirmation_source": "user_review",
                    "cancellation_confirmed_on": assertion["confirmed_on"],
                    "cancellation_reason_status": "not_shown",
                    "exact_cause_status": "not_shown_in_source",
                    "user_confirmation_text": assertion["original_user_text"],
                    "review_updated_on": "2026-10-01",
                })
            else:
                raise ValueError(f"Unresolved cancellation after user review: {row['race_date']} {row['race_number']}R")
        if sum(row["cancellation_confirmation_source"] == "user_review" for row in review) != 7:
            raise ValueError("Expected seven newly user-confirmed races")
        write_jsonl(HERE / "confirmed_76_review.jsonl", review)
        write_jsonl(HERE / "user_confirmed_jeju_races.jsonl", expanded)
        summary = {
            "confirmed_on": "2026-10-01",
            "database_access": "read_only",
            "user_assertion_dates": len(assertions),
            "original_review_races": len(review),
            "original_review_candidate_rows": sum(row["entrant_rows"] for row in review),
            "original_review_cancelled_races": len(review),
            "original_review_reason_specified_races": sum(row["cancellation_reason_status"] == "specified" for row in review),
            "original_review_reason_not_shown_races": sum(row["cancellation_reason_status"] == "not_shown" for row in review),
            "user_scope_api_cancelled_races": len(expanded),
            "user_scope_api_rows": sum(row["api_rows"] for row in expanded),
            "user_scope_native_candidate_races": sum(row["native_population_candidate_rows"] > 0 for row in expanded),
            "user_scope_native_candidate_rows": sum(row["native_population_candidate_rows"] for row in expanded),
            "by_assertion_date": {},
        }
        for race_date in sorted(by_date):
            rows = [row for row in expanded if row["race_date"] == race_date]
            summary["by_assertion_date"][race_date] = {
                "cancelled_api_race_numbers": [row["race_number"] for row in rows],
                "api_rows": sum(row["api_rows"] for row in rows),
                "native_candidate_race_numbers": [row["race_number"] for row in rows if row["native_population_candidate_rows"]],
                "native_candidate_rows": sum(row["native_population_candidate_rows"] for row in rows),
            }
        (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in summary.items() if key != "by_assertion_date"}, ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
