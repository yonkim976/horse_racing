"""Build every calendar date from KRA API event keys and sourced closure intervals."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from build_nonexecution_adjudication import build_adjudication


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
START, END = date(2010, 1, 1), date(2026, 9, 29)
CLOSURES = [ROOT / "thoroughbred/research/20260929_closure_inventory_v1/closures.csv",
            HERE / "closure_addendum.csv"]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path: Path, headings: list[str], data: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headings)
        writer.writeheader()
        writer.writerows(data)


def main() -> None:
    adjudication_rows, adjudication_counts = build_adjudication()
    adjudication_by_day = defaultdict(Counter)
    for row in adjudication_rows:
        adjudication_by_day[(int(row["meet"]), row["date"])][row["adjudication_status"]] += 1

    plan = Counter((int(row["meet"]), row["date"]) for row in rows(HERE / "race_plan.csv"))
    trial = Counter((int(row["source_meet"]), row["date"]) for row in rows(HERE / "trial_sessions.csv"))
    race = defaultdict(Counter)
    unfinished_race_keys = set()
    for row in rows(HERE / "race_execution_flags.csv"):
        race[(int(row["meet"]), row["date"])][row["execution_status"]] += 1
        if row["execution_status"] == "planned_no_execution_evidence":
            unfinished_race_keys.add((int(row["meet"]), row["date"], int(row["race_no"])))
    closures = defaultdict(list)
    for row in [row for path in CLOSURES for row in rows(path)]:
        meet = int(row["meet_code"])
        day = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["end_date"])
        while day <= end:
            if START <= day <= END:
                closures[(meet, day.strftime("%Y%m%d"))].append(row)
            day += timedelta(days=1)
    nonexecution = defaultdict(list)
    for row in rows(HERE / "official_nonexecution_addendum.csv"):
        nonexecution[(int(row["meet_code"]), date.fromisoformat(row["date"]).strftime("%Y%m%d"))].append(row)
    reported_cancellations = defaultdict(list)
    for row in rows(HERE / "reported_race_cancellations.csv"):
        reported_cancellations[(int(row["meet"]), date.fromisoformat(row["date"]).strftime("%Y%m%d"))].append(row)
    scoretable_nonfinish = defaultdict(list)
    for row in rows(HERE / "kra_scoretable_nonfinish_reasons.csv"):
        scoretable_nonfinish[(int(row["meet"]), date.fromisoformat(row["date"]).strftime("%Y%m%d"))].append(row)
    calendar = []
    conflict = []
    for meet in (1, 3, 4):
        day = START
        while day <= END:
            d = day.strftime("%Y%m%d")
            c = closures.get((meet, d), [])
            n = nonexecution.get((meet, d), [])
            reported = reported_cancellations.get((meet, d), [])
            site_reasons = scoretable_nonfinish.get((meet, d), [])
            r = race[(meet, d)]
            executed = r["executed_plan_and_result"]
            if executed and c:
                conflict.append([meet, d, "execution_and_official_closure"])
            if executed and n:
                conflict.append([meet, d, "execution_and_official_nonexecution"])
            if len(reported) > r["planned_no_execution_evidence"]:
                conflict.append([meet, d, "reported_cancellations_exceed_unfinished_plan"])
            if len({int(x["race_no"]) for x in reported}) != len(reported):
                conflict.append([meet, d, "duplicate_reported_cancellation_race"])
            for item in reported:
                if (meet, d, int(item["race_no"])) not in unfinished_race_keys:
                    conflict.append([meet, d, f"reported_cancellation_not_unfinished_plan_R{item['race_no']}"])
            for item in site_reasons:
                if (meet, d, int(item["race_no"])) not in unfinished_race_keys:
                    conflict.append([meet, d, f"scoretable_nonfinish_not_unfinished_plan_R{item['race_no']}"])
            if len({int(x["race_no"]) for x in site_reasons}) != len(site_reasons):
                conflict.append([meet, d, "duplicate_scoretable_nonfinish_race"])
            if n and not plan[(meet, d)]:
                conflict.append([meet, d, "nonexecution_without_plan"])
            if executed:
                status = "executed_plan_and_result"
            elif c:
                status = "official_closure_recorded"
            elif n:
                status = "official_cancelled_day"
            elif site_reasons and len(site_reasons) == plan[(meet, d)] == r["planned_no_execution_evidence"]:
                status = "kra_scoretable_nonexecution_day"
            elif plan[(meet, d)]:
                status = "planned_no_execution_evidence"
            elif r["positive_result_without_plan_unverified"]:
                status = "positive_result_without_plan_unverified"
            else:
                status = "no_race_plan_or_execution_record"
            calendar.append({"meet": meet, "date": day.isoformat(), "weekday": day.strftime("%a"),
                             "race_day_status": status, "scheduled_race_count": plan[(meet, d)],
                             "executed_race_count": executed,
                             "planned_race_without_finish_count": r["planned_no_execution_evidence"],
                             "positive_result_without_plan_count": r["positive_result_without_plan_unverified"],
                             "trial_session_count_by_source_meet": trial[(meet, d)],
                             "trial_venue_caution": "Yeongnam_region_unresolved" if meet == 3 and d >= "20260913" and trial[(meet, d)] else "",
                             "official_closure_reason": ";".join(sorted({x["reason"] for x in c})),
                             "official_closure_source_url": ";".join(sorted({x["source_url"] for x in c})),
                             "official_nonexecution_reason": ";".join(sorted({x["reason"] for x in n})),
                             "official_nonexecution_source_url": ";".join(sorted({x["source_url"] for x in n})),
                             "reported_cancellation_count": len(reported),
                             "reported_cancellation_race_nos": ";".join(str(x) for x in sorted(int(x["race_no"]) for x in reported)),
                             "reported_cancellation_reason": ";".join(sorted({x["reported_reason"] for x in reported})),
                             "kra_scoretable_nonfinish_count": len(site_reasons),
                             "kra_scoretable_nonfinish_race_nos": ";".join(str(x) for x in sorted(int(x["race_no"]) for x in site_reasons)),
                             "kra_scoretable_source_url": site_reasons[0]["source_page"] if site_reasons else "",
                             "adjudicated_no_valid_completed_race_count": sum(adjudication_by_day[(meet, d)].values()),
                             **{f"adjudication_{status}_count": adjudication_by_day[(meet, d)][status]
                                for status in (
                                    "official_day_cancelled", "reported_day_cancelled",
                                    "official_closure_nonexecution", "race_cancelled", "race_invalid",
                                    "reason_recorded_outcome_unclassified")}})
            day += timedelta(days=1)
    write(HERE / "daily_calendar.csv", ["meet", "date", "weekday", "race_day_status",
                                         "scheduled_race_count", "executed_race_count",
                                         "planned_race_without_finish_count",
                                         "positive_result_without_plan_count",
                                         "trial_session_count_by_source_meet", "trial_venue_caution",
                                         "official_closure_reason", "official_closure_source_url",
                                         "official_nonexecution_reason", "official_nonexecution_source_url",
                                         "reported_cancellation_count", "reported_cancellation_race_nos",
                                         "reported_cancellation_reason", "kra_scoretable_nonfinish_count",
                                         "kra_scoretable_nonfinish_race_nos", "kra_scoretable_source_url",
                                         "adjudicated_no_valid_completed_race_count",
                                         "adjudication_official_day_cancelled_count",
                                         "adjudication_reported_day_cancelled_count",
                                         "adjudication_official_closure_nonexecution_count",
                                         "adjudication_race_cancelled_count",
                                         "adjudication_race_invalid_count",
                                         "adjudication_reason_recorded_outcome_unclassified_count"], calendar)
    annual = []
    for meet in (1, 3, 4):
        for year in range(2010, 2027):
            subset = [row for row in calendar if row["meet"] == meet and row["date"].startswith(str(year))]
            annual.append({"meet": meet, "year": year,
                           "planned_races": sum(row["scheduled_race_count"] for row in subset),
                           "executed_races_with_plan": sum(row["executed_race_count"] for row in subset),
                           "planned_race_days": sum(row["scheduled_race_count"] > 0 for row in subset),
                           "executed_race_days_with_plan": sum(row["executed_race_count"] > 0 for row in subset),
                           "trial_sessions_by_source_meet": sum(row["trial_session_count_by_source_meet"] for row in subset),
                           "trial_days_by_source_meet": sum(row["trial_session_count_by_source_meet"] > 0 for row in subset),
                           "official_closure_calendar_days_documented": sum(bool(row["official_closure_source_url"]) for row in subset),
                           "official_cancelled_race_days_documented": sum(bool(row["official_nonexecution_source_url"]) for row in subset),
                           "kra_scoretable_nonexecution_days_verified": sum(row["race_day_status"] == "kra_scoretable_nonexecution_day" for row in subset)})
    write(HERE / "annual_summary.csv", ["meet", "year", "planned_races", "executed_races_with_plan",
                                         "planned_race_days", "executed_race_days_with_plan",
                                         "trial_sessions_by_source_meet", "trial_days_by_source_meet",
                                         "official_closure_calendar_days_documented",
                                         "official_cancelled_race_days_documented",
                                         "kra_scoretable_nonexecution_days_verified"], annual)
    gaps = []
    for meet in (1, 3, 4):
        days = [date.fromisoformat(row["date"]) for row in calendar
                if row["meet"] == meet and row["executed_race_count"]]
        for left, right in zip(days, days[1:]):
            gap = (right - left).days - 1
            if gap >= 7:
                gaps.append({"meet": meet, "last_execution": left.isoformat(),
                             "next_execution": right.isoformat(), "days_between": gap,
                             "classification": "review_gap_not_automatically_closure"})
    write(HERE / "long_execution_gaps.csv", ["meet", "last_execution", "next_execution",
                                               "days_between", "classification"], gaps)
    summary = {"calendar_rows": len(calendar),
               "race_day_status_counts": dict(Counter(row["race_day_status"] for row in calendar)),
               "planned_race_without_finish_by_day_status": dict(Counter(
                   "partial_execution_day" if row["executed_race_count"] else row["race_day_status"]
                   for row in calendar
                   for _ in range(row["planned_race_without_finish_count"]))),
               "official_closure_calendar_rows": sum(bool(row["official_closure_source_url"]) for row in calendar),
               "official_cancelled_race_days_documented": sum(bool(row["official_nonexecution_source_url"]) for row in calendar),
               "kra_scoretable_nonfinish_races_verified": sum(row["kra_scoretable_nonfinish_count"] for row in calendar),
               "kra_scoretable_nonexecution_days_verified": sum(row["race_day_status"] == "kra_scoretable_nonexecution_day" for row in calendar),
               "adjudicated_no_valid_completed_race_count": sum(adjudication_counts.values()),
               "adjudication_status_counts": adjudication_counts,
               "execution_verdict_counts": dict(Counter(row["execution_verdict"] for row in adjudication_rows)),
               "execution_closure_conflicts": conflict,
               "long_execution_gap_count": len(gaps),
               "closure_coverage_warning": "Official closure intervals are a documented partial list, not a complete 2010-2026 closure calendar."}
    (HERE / "daily_calendar_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
