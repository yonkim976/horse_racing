"""Read-only evidence inventory for the proposed 2017 training boundary; no fitting."""
from pathlib import Path
import hashlib
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / "data/research/thoroughbred_unified_20260918/parquet/model_training_entry.parquet"
WINDOWS = ROOT / "data/research/thoroughbred_offline_20260918_v5/window_effects.csv"


def aggregate(frame, keys):
    return frame.groupby(keys).agg(races=("race_id", "nunique"), runner_entries=("race_id", "size")).reset_index().to_dict("records")


def main():
    frame = pd.read_parquet(SOURCE)
    frame = frame[frame.venue_code.isin(["SEOUL", "BUSAN"])].copy()
    frame["year"] = pd.to_datetime(frame.race_date).dt.year
    recent = frame[frame.year >= 2017]
    result = {
        "scope": "Existing frozen 20260918 unified training-entry table; not a fresh inventory of corrected operational sections, and not a model comparison.",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "min_date": str(frame.race_date.min()),
        "max_date": str(frame.race_date.max()),
        "annual_counts": aggregate(frame, ["venue_code", "year"]),
        "all_since_2006": aggregate(frame, ["venue_code"]),
        "since_2017": aggregate(recent, ["venue_code"]),
        "since_2017_rank_labeled": aggregate(recent[recent.target_is_rank_label.eq(True)], ["venue_code"]),
        "2017_to_2020": aggregate(frame[frame.year.between(2017, 2020)], ["venue_code"]),
        "since_2017_by_distance": aggregate(recent, ["venue_code", "distance_m"]),
        "prior_window_comparison": pd.read_csv(WINDOWS).to_dict("records"),
        "window_source_sha256": hashlib.sha256(WINDOWS.read_bytes()).hexdigest(),
        "training_performed": False,
        "DB_writes": 0,
        "conclusion": "2017+ is a reasonable primary analysis cohort with substantial support; superiority to the full period is untested. Keep pre-2017 sources and compare fixed-start cohorts under identical evaluation contracts.",
    }
    with (HERE / "evidence.json").open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({key: result[key] for key in ("since_2017", "since_2017_rank_labeled", "2017_to_2020")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
