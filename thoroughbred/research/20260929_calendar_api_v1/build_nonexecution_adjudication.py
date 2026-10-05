"""Build the final per-race verdict ledger for planned races without finish evidence."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUT = HERE / "race_nonexecution_adjudication.csv"
EXPECTED_STATUS_COUNTS = {
    "official_day_cancelled": 35,
    "reported_day_cancelled": 11,
    "official_closure_nonexecution": 17,
    "race_cancelled": 22,
    "race_invalid": 2,
    "reason_recorded_outcome_unclassified": 29,
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, headings: list[str], data: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headings, extrasaction="raise")
        writer.writeheader()
        writer.writerows(data)


def day_key(meet: str | int, day: str) -> tuple[int, str]:
    return int(meet), day.replace("-", "")


def race_key(meet: str | int, day: str, race_no: str | int) -> tuple[int, str, int]:
    return int(meet), day.replace("-", ""), int(race_no)


def joined(values: list[str]) -> str:
    return ";".join(dict.fromkeys(value for value in values if value))


def build_adjudication() -> tuple[list[dict[str, str]], dict[str, int]]:
    """Write and return adjudications, enforcing full key coverage and source consistency."""
    flags = read_csv(HERE / "race_execution_flags.csv")
    plans = read_csv(HERE / "race_plan.csv")
    no_finish_flags = [row for row in flags if row["execution_status"] == "planned_no_execution_evidence"]
    keys = [race_key(row["meet"], row["date"], row["race_no"]) for row in no_finish_flags]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate planned-no-finish key in race_execution_flags.csv")
    if len(no_finish_flags) != 116:
        raise ValueError(f"Expected 116 planned races without finish evidence, found {len(no_finish_flags)}")

    plan_keys = {race_key(row["meet"], row["date"], row["race_no"]) for row in plans}
    flag_keys = {race_key(row["meet"], row["date"], row["race_no"]) for row in flags}
    if plan_keys != flag_keys:
        raise ValueError("race_plan.csv and race_execution_flags.csv do not have identical race keys")

    plan_by_day = Counter(day_key(row["meet"], row["date"]) for row in plans)
    no_finish_by_day = Counter(day_key(row["meet"], row["date"]) for row in no_finish_flags)
    flag_by_key = {race_key(row["meet"], row["date"], row["race_no"]): row for row in no_finish_flags}

    official_day = defaultdict(list)
    for row in read_csv(HERE / "official_nonexecution_addendum.csv"):
        official_day[day_key(row["meet_code"], row["date"])].append(row)

    closure_day = defaultdict(list)
    closure_path = ROOT / "thoroughbred/research/20260929_closure_inventory_v1/closures.csv"
    for row in read_csv(closure_path):
        meet = int(row["meet_code"])
        start = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["end_date"])
        current = start
        while current <= end:
            closure_day[(meet, current.strftime("%Y%m%d"))].append(row)
            current += timedelta(days=1)

    direct = {
        race_key(row["meet"], row["date"], row["race_no"]): row
        for row in read_csv(HERE / "kra_scoretable_nonfinish_reasons.csv")
    }
    reported = defaultdict(list)
    for row in read_csv(HERE / "reported_race_cancellations.csv"):
        reported[race_key(row["meet"], row["date"], row["race_no"])].append(row)
    partial_cancel = {
        race_key(row["meet"], row["date"], row["race_no"]): row
        for row in read_csv(HERE / "partial_day_cancellation_evidence.csv")
    }
    unresolved_day = {
        day_key(row["meet"], row["date"]): row
        for row in read_csv(HERE / "unresolved_race_day_review.csv")
    }

    for source_name, source_keys in (
        ("KRA scoretable", set(direct)),
        ("reported race cancellation", set(reported)),
        ("partial-day cancellation evidence", set(partial_cancel)),
    ):
        extras = source_keys - plan_keys
        if extras:
            raise ValueError(f"{source_name} contains races absent from race_plan.csv: {sorted(extras)}")
    if (set(direct) - set(keys)):
        raise ValueError("KRA scoretable nonfinish evidence includes a race without planned-no-finish status")
    if (set(partial_cancel) - set(keys)):
        raise ValueError("Partial-day cancellation evidence includes a race with positive finish evidence")

    reported_days = defaultdict(list)
    for key, rows in reported.items():
        reported_days[key[:2]].extend(rows)

    rows_out: list[dict[str, str]] = []
    for key in sorted(keys):
        meet, day, race_no = key
        flag = flag_by_key[key]
        day_id = (meet, day)
        score = direct.get(key)
        report_rows = reported.get(key, [])
        partial = partial_cancel.get(key)
        official_rows = official_day.get(day_id, [])
        closures = closure_day.get(day_id, [])

        if int(flag["positive_finish_rows"]) != 0:
            raise ValueError(f"Planned-no-finish row has positive finish rows: {key}")
        if official_rows:
            status = "official_day_cancelled"
            reason = "; ".join(dict.fromkeys(row["reason"] for row in official_rows))
            support = ""
            files = ["official_nonexecution_addendum.csv", "race_execution_flags.csv"]
            urls = [row["source_url"] for row in official_rows]
            kinds = [row["evidence_type"] for row in official_rows]
            states = ["official_yearbook_evidence"]
            verified = ""
            note = "KRA yearbook records the venue's entire race card as cancelled or not held that day."
        elif closures:
            status = "official_closure_nonexecution"
            reason = "; ".join(dict.fromkeys(row["reason"] for row in closures))
            support = "Official revised plan, page 6; planned entries persist in the earlier race-plan response."
            files = ["../20260929_closure_inventory_v1/closures.csv", "race_plan.csv", "race_execution_flags.csv"]
            urls = [row["source_url"] for row in closures]
            kinds = [row["evidence_kind"] for row in closures]
            states = ["official_revised_plan"]
            verified = ""
            note = "Official revised plan documents a COVID-19 suspension; this is schedule-level nonexecution."
        elif score and "경주불성립" in score["kra_display_reason"]:
            status = "race_invalid"
            reason = score["kra_display_reason"]
            support = ""
            files = ["kra_scoretable_nonfinish_reasons.csv", "race_execution_flags.csv"]
            urls = [score["source_page"]]
            kinds = ["kra_scoretable_live_ui"]
            states = [score["source_state"]]
            verified = score["verified_date"]
            note = "KRA display explicitly identifies an invalid race; the event may have started."
        elif partial:
            status = "race_cancelled"
            reason = score["kra_display_reason"] if score else partial["reason"]
            support = partial["reason"] if score and partial["reason"] != reason else ""
            files = ["partial_day_cancellation_evidence.csv", "race_execution_flags.csv"]
            urls = [partial["source_url"]]
            kinds = [partial["evidence_type"]]
            states = ["official_document_or_contemporaneous_KRA_quoted_report"]
            verified = score["verified_date"] if score else ""
            if score:
                files.append("kra_scoretable_nonfinish_reasons.csv")
                urls.append(score["source_page"])
                kinds.append("kra_scoretable_live_ui")
                states.append(score["source_state"])
            note = "Race-level cancellation is supported by the cited yearbook or contemporaneous report."
        elif score and "경주취소" in score["kra_display_reason"]:
            status = "race_cancelled"
            reason = score["kra_display_reason"]
            support = "; ".join(dict.fromkeys(row["reported_reason"] for row in report_rows))
            files = ["kra_scoretable_nonfinish_reasons.csv", "race_execution_flags.csv"]
            urls = [score["source_page"]]
            kinds = ["kra_scoretable_live_ui"]
            states = [score["source_state"]]
            verified = score["verified_date"]
            if report_rows:
                files.append("reported_race_cancellations.csv")
                urls.extend(row["kra_lookup_url"] for row in report_rows)
                kinds.extend(row["report_source"] for row in report_rows)
                urls.extend(row["independent_source_url"] for row in report_rows)
            note = "KRA display explicitly identifies cancellation."
        elif (day_id in unresolved_day and plan_by_day[day_id] == no_finish_by_day[day_id]
              and len(reported_days.get(day_id, [])) == plan_by_day[day_id]
              and any("추모" in row["reported_reason"] for row in reported_days[day_id])):
            status = "reported_day_cancelled"
            reason = score["kra_display_reason"] if score else ""
            support = "; ".join(dict.fromkeys(row["reported_reason"] for row in reported_days[day_id]))
            files = ["unresolved_race_day_review.csv", "reported_race_cancellations.csv",
                     "kra_scoretable_nonfinish_reasons.csv", "race_execution_flags.csv"]
            urls = [row["kra_lookup_url"] for row in reported_days[day_id]]
            urls.extend(row["independent_source_url"] for row in reported_days[day_id])
            if score:
                urls.append(score["source_page"])
            kinds = [row["report_source"] for row in reported_days[day_id]] + ["kra_scoretable_live_ui"]
            states = ["KRA_notice_quoted_by_press", "verified_live_ui_text_not_archived"]
            verified = score["verified_date"] if score else ""
            note = "The full race card has no finish evidence; the KRA mourning notice was quoted by contemporary press."
        elif score:
            status = "reason_recorded_outcome_unclassified"
            reason = score["kra_display_reason"]
            support = "; ".join(dict.fromkeys(row["reported_reason"] for row in report_rows))
            files = ["kra_scoretable_nonfinish_reasons.csv", "race_execution_flags.csv"]
            urls = [score["source_page"]]
            kinds = ["kra_scoretable_live_ui"]
            states = [score["source_state"]]
            verified = score["verified_date"]
            if report_rows:
                files.append("reported_race_cancellations.csv")
                urls.extend(row["kra_lookup_url"] for row in report_rows)
                urls.extend(row["independent_source_url"] for row in report_rows)
                kinds.extend(row["report_source"] for row in report_rows)
                states.extend(row["direct_KRA_result_capture"] for row in report_rows)
            note = ("KRA display text is retained verbatim, but it does not explicitly classify the race as "
                    "cancelled or invalid. No specific outcome or cause is inferred from the text.")
        else:
            raise ValueError(f"No adjudicating source found for planned race without finish evidence: {key}")

        rows_out.append({
            "meet": str(meet),
            "date": day,
            "race_no": str(race_no),
            "execution_verdict": "no_valid_completed_race",
            "adjudication_status": status,
            "nonexecution_scope": "",
            "reason_text": reason,
            "supporting_reason": support,
            "evidence_files": joined(files),
            "evidence_urls": joined(urls),
            "evidence_kind": joined(kinds),
            "source_state": joined(states),
            "verified_date": verified,
            "source_result_rows": flag["source_result_rows"],
            "positive_finish_rows": flag["positive_finish_rows"],
            "decision_note": note,
        })

    # Label full-card subtypes separately from race-level nonexecution.
    by_day: dict[tuple[int, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows_out:
        by_day[day_key(row["meet"], row["date"])].append(row)
    for row in rows_out:
        key = day_key(row["meet"], row["date"])
        if row["adjudication_status"] in {
            "official_day_cancelled", "reported_day_cancelled", "official_closure_nonexecution"
        }:
            row["nonexecution_scope"] = "whole_day"
        elif (row["adjudication_status"] == "race_cancelled"
              and len(by_day[key]) == plan_by_day[key]
              and no_finish_by_day[key] == plan_by_day[key]
              and all(item["adjudication_status"] == "race_cancelled" for item in by_day[key])):
            row["nonexecution_scope"] = "whole_day"
        else:
            row["nonexecution_scope"] = "race"

    counts = dict(Counter(row["adjudication_status"] for row in rows_out))
    if counts != EXPECTED_STATUS_COUNTS:
        raise ValueError(f"Unexpected adjudication subtype counts: {counts}")
    if len(rows_out) != len(keys) or {race_key(row["meet"], row["date"], row["race_no"]) for row in rows_out} != set(keys):
        raise ValueError("Adjudication ledger does not exactly cover planned races without finish evidence")
    if any(row["execution_verdict"] != "no_valid_completed_race" for row in rows_out):
        raise ValueError("Unexpected execution verdict in no-finish adjudication ledger")
    if any(not row["reason_text"] for row in rows_out):
        raise ValueError("Adjudication ledger has a race with no sourced reason text")

    write_csv(OUTPUT, [
        "meet", "date", "race_no", "execution_verdict", "adjudication_status", "nonexecution_scope",
        "reason_text", "supporting_reason", "evidence_files", "evidence_urls", "evidence_kind",
        "source_state", "verified_date", "source_result_rows", "positive_finish_rows", "decision_note",
    ], rows_out)
    return rows_out, counts


if __name__ == "__main__":
    ledger, counts = build_adjudication()
    print({"rows": len(ledger), "execution_verdicts": dict(Counter(row["execution_verdict"] for row in ledger)),
           "adjudication_status_counts": counts})
