"""Measure observed domestic career truncation for a 2017+ training cohort."""
from pathlib import Path
import hashlib
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / "data/research/thoroughbred_unified_20260918/parquet/entry_result.parquet"
STATUSES = ["finished", "did_not_finish", "disqualified"]


def assess(frame, cohort):
    first = cohort.sort_values(["race_date", "race_id"]).drop_duplicates("hr_no")
    history = frame.merge(first[["hr_no", "race_date"]].rename(columns={"race_date": "first_target_date"}), on="hr_no")
    history = history[history.race_date < history.first_target_date].sort_values(["hr_no", "race_date", "race_id"])
    pre2017 = history[history.race_date < "2017-01-01"]
    recent5 = history.groupby("hr_no").tail(5)
    rows = []
    for year in [2010, 2011, 2012, 2013, 2014, 2015, 2016]:
        cutoff = pd.Timestamp(year, 1, 1)
        lost = pre2017[pre2017.race_date < cutoff]
        recent_lost = recent5[recent5.race_date < cutoff]
        rows.append({"start_year": year, "horses_losing_observed_career_rows": lost.hr_no.nunique(), "observed_career_rows_lost": len(lost), "horses_losing_recent5_rows": recent_lost.hr_no.nunique(), "recent5_rows_lost": len(recent_lost)})
    return {"cohort_horses": len(first), "horses_with_observed_pre2017_starts": pre2017.hr_no.nunique(), "observed_pre2017_starts": len(pre2017), "earliest_observed_prior_date": str(pre2017.race_date.min().date()), "earliest_examples": pre2017.nsmallest(5, "race_date")[["hr_no", "horse_name_normalized", "venue_code", "race_date"]].to_dict("records"), "cutoff_comparison": rows}


def main():
    frame = pd.read_parquet(SOURCE, columns=["race_id", "venue_code", "race_date", "hr_no", "result_status", "horse_name_normalized"])
    frame = frame[frame.venue_code.isin(["SEOUL", "BUSAN"]) & frame.result_status.isin(STATUSES)].copy()
    frame["race_date"] = pd.to_datetime(frame.race_date)
    result = {"source": str(SOURCE.relative_to(ROOT)), "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(), "history_statuses": STATUSES, "source_end_date": str(frame.race_date.max().date()), "cohort_2017": assess(frame, frame[frame.race_date.dt.year.eq(2017)]), "cohort_2017_onward": assess(frame, frame[frame.race_date >= "2017-01-01"]), "limits": ["Observed domestic records only; no proof of complete official or overseas lifetime history.", "Counts use the existing frozen source, not a fresh operational DB export.", "Source-specific gaps, nonstandard outcome codes, horse-ID linkage and availability of pre-2017 sections/medical/training records need separate checks.", "Cohort membership after 2017 is used for this retrospective inventory only; prospective feature generation must not use future participation."], "training": False, "DB_writes": 0}
    with (HERE / "evidence.json").open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(result["cohort_2017_onward"], ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
