"""Check the manually transcribed KRA period-scoretable findings against API keys."""

import csv
from pathlib import Path


HERE = Path(__file__).resolve().parent


def read(name):
    with (HERE / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def key(row):
    return row["meet"], row["date"].replace("-", ""), row["race_no"]


def main():
    flags = read("race_execution_flags.csv")
    unfinished = {key(row) for row in flags if row["execution_status"] == "planned_no_execution_evidence"}
    executed_days = {(row["meet"], row["date"]) for row in flags
                     if row["execution_status"] == "executed_plan_and_result"}
    site = read("kra_scoretable_nonfinish_reasons.csv")
    site_keys = {key(row) for row in site}
    assert len(site) == len(site_keys) == 64, "duplicate or missing KRA scoretable rows"
    assert site_keys <= unfinished, "KRA scoretable row conflicts with a finished race"
    assert all(row["kra_display_reason"] and row["source_page"] for row in site)
    partial = {key(row) for row in flags if row["execution_status"] == "planned_no_execution_evidence"
               and (row["meet"], row["date"]) in executed_days}
    assert len(partial) == 41 and partial <= site_keys, "partial-day gaps lack scoretable evidence"
    full_days = {(meet, day) for meet, day, _ in site_keys if (meet, day) not in executed_days}
    assert full_days == {("1", "20200809"), ("3", "20191129")}
    assert len(site_keys - partial) == 23
    reported = read("reported_race_cancellations.csv")
    assert len(reported) == 33 and {key(row) for row in reported} <= site_keys
    assert all(row["kra_display_reason"] == next(
        item["kra_display_reason"] for item in site if key(item) == key(row)) for row in reported)
    planless = read("planless_positive_result_review.csv")
    assert len(planless) == 20
    active_keys = {key(row) for row in flags}
    assert {key(row) for row in planless}.isdisjoint(active_keys), "excluded API anomalies reentered active race ledger"
    assert all(row["execution_status"] == "positive_result_without_plan_unverified"
               and row["kra_scoretable_period_lookup"] == "venue_date_no_rows" for row in planless)
    assert all(row["exact_horse_set"] == "yes" and row["matched_executed_date"]
               for row in planless)
    assert sum(row["comparison_note"] == "same_horses_and_times" for row in planless) == 18
    assert sum(row["comparison_note"] == "same_horses_modified_times" for row in planless) == 2
    nonfinish_anomalies = read("result_only_nonfinish_anomaly_review.csv")
    assert len(nonfinish_anomalies) == 52
    assert {key(row) for row in nonfinish_anomalies}.isdisjoint(active_keys)
    assert all(row["kra_scoretable_period_lookup"] == "venue_date_no_rows"
               and row["exact_horse_set"] == "yes"
               and row["positive_finish_rows"] == "0" for row in nonfinish_anomalies)
    print("KRA scoretable check: 64 nonfinish races (41 partial, 23 full-day); "
          "33 reported races reconciled; 72 result-only API anomalies excluded from active race ledger")


if __name__ == "__main__":
    main()
