"""Independent date-window calculation for the single rolling jockey feature."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
REVIEW = Path(__file__).resolve().parent
STUDY = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
SOURCE = ROOT / "jeju/research/20261009_jockey_effects_v1/input01/starts.csv"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
INPUT_CODE = STUDY / "jockey_input.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def independent_windows(targets: pd.DataFrame, starts: pd.DataFrame) -> pd.DataFrame:
    """Move a date-window over each rider's event rows; no candidate helpers."""
    history_by_rider = {}
    for rider, group in starts.groupby("jockey_id", sort=False):
        h = group.sort_values(["race_date", "api_record_id"], kind="mergesort")
        history_by_rider[str(rider)] = (
            h["race_date"].to_numpy(dtype="datetime64[D]"),
            (pd.to_numeric(h["finish_position"], errors="raise").to_numpy() <= 3),
            3.0 / pd.to_numeric(h["field_n"], errors="raise").to_numpy(dtype=float),
        )

    output = []
    for rider, group in targets.groupby("jockey_id", sort=False):
        g = group.sort_values(["race_date", "api_record_id"], kind="mergesort")
        target_dates = g["race_date"].to_numpy(dtype="datetime64[D]")
        history = history_by_rider.get(str(rider))
        left = right = 0
        n_all, s_all, e_all, last_all = [], [], [], []
        cursor = 0
        while cursor < len(g):
            day = target_dates[cursor]
            cutoff = day - np.timedelta64(2, "D")
            lower_exclusive = cutoff - np.timedelta64(365, "D")
            if history is not None:
                hdates, htop3, hexpected = history
                while right < len(hdates) and hdates[right] <= cutoff:
                    right += 1
                while left < right and hdates[left] <= lower_exclusive:
                    left += 1
                n = right - left
                s = int(htop3[left:right].sum())
                e = math.fsum(map(float, hexpected[left:right]))
                last = (pd.Timestamp(hdates[right - 1]).date().isoformat() if n else None)
            else:
                n, s, e, last = 0, 0, 0.0, None
            stop = cursor + 1
            while stop < len(g) and target_dates[stop] == day:
                stop += 1
            count = stop - cursor
            n_all.extend([n] * count)
            s_all.extend([s] * count)
            e_all.extend([e] * count)
            last_all.extend([last] * count)
            cursor = stop
        tmp = g[["api_record_id", "race_id", "race_date", "jockey_id"]].copy()
        tmp["n_independent"] = np.asarray(n_all, dtype=np.int64)
        tmp["s_independent"] = np.asarray(s_all, dtype=np.int64)
        tmp["e_independent"] = np.asarray(e_all, dtype=float)
        tmp["d_independent"] = np.where(
            tmp["n_independent"].eq(0), 0.0,
            (tmp["s_independent"] - tmp["e_independent"]) / (tmp["n_independent"] + 20.0),
        )
        tmp["cutoff"] = tmp["race_date"] - pd.Timedelta(days=2)
        tmp["latest_history_date"] = last_all
        output.append(tmp)
    return pd.concat(output, ignore_index=True).sort_values("api_record_id", kind="mergesort").reset_index(drop=True)


def main() -> None:
    spec = importlib.util.spec_from_file_location("candidate_jockey_input", INPUT_CODE)
    candidate = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(candidate)

    starts = pd.read_csv(
        SOURCE,
        dtype={"api_record_id": "string", "race_id": "string", "horse_id": "string", "jockey_id": "string"},
        usecols=["api_record_id", "race_id", "horse_id", "race_date", "jockey_id", "field_n", "finish_position"],
    )
    starts["race_date"] = pd.to_datetime(starts["race_date"], errors="raise").dt.normalize()
    roster = pd.read_parquet(
        FEATURES,
        columns=["api_record_id", "race_id", "race_date", "year", "horse_id"],
        filters=[("year", ">=", 2019), ("year", "<=", 2026)],
    )
    for col in ("api_record_id", "race_id", "horse_id"):
        roster[col] = roster[col].astype("string")
    roster["race_date"] = pd.to_datetime(roster["race_date"], errors="raise").dt.normalize()
    joined = roster.merge(
        starts[["api_record_id", "race_id", "horse_id", "race_date", "jockey_id"]],
        on="api_record_id", how="left", validate="one_to_one", suffixes=("_feature", "_event"), indicator=True,
    )
    assert joined["_merge"].eq("both").all()
    for col in ("race_id", "horse_id", "race_date"):
        assert joined[f"{col}_feature"].eq(joined[f"{col}_event"]).all(), f"mismatched {col} after event-ID join"
    joined = joined.rename(columns={
        "race_id_feature": "race_id", "race_date_feature": "race_date", "horse_id_feature": "horse_id",
    }).drop(columns=["_merge", "race_id_event", "race_date_event", "horse_id_event"])

    independent = independent_windows(joined, starts)
    candidate_rows = candidate.rolling_features(joined, starts)
    compared = independent.merge(
        candidate_rows[["api_record_id", "jockey_id", "jockey365_n", "jockey365_top3", "jockey365_expected_top3", "jockey365_field_relative_top3"]],
        on=["api_record_id", "jockey_id"], how="outer", validate="one_to_one", indicator=True,
    )
    assert compared["_merge"].eq("both").all()
    assert compared["n_independent"].eq(compared["jockey365_n"]).all()
    assert compared["s_independent"].eq(compared["jockey365_top3"]).all()
    max_e_error = float((compared["e_independent"] - compared["jockey365_expected_top3"]).abs().max())
    max_d_error = float((compared["d_independent"] - compared["jockey365_field_relative_top3"]).abs().max())
    # Candidate code uses float64 prefix sums; subtracting large prefixes can
    # retain a few ulps against an independent math.fsum over each window.
    # These tolerances are numerical comparison bounds only and do not tune a
    # model parameter or alter the feature definition.
    assert max_e_error <= 1e-9, max_e_error
    assert max_d_error <= 1e-11, max_d_error
    cutoff = pd.to_datetime(compared["race_date"], errors="raise") - pd.Timedelta(days=2)
    latest = pd.to_datetime(compared["latest_history_date"], errors="coerce")
    assert (latest.isna() | (latest <= cutoff)).all()
    assert (compared.loc[compared["n_independent"].eq(0), "d_independent"] == 0.0).all()

    by_year = {}
    year_map = joined.set_index("api_record_id")["year"]
    compared["year"] = compared["api_record_id"].map(year_map).astype(int)
    for year, group in compared.groupby("year", sort=True):
        by_year[str(year)] = {
            "rows": int(len(group)),
            "zero_observed_history_rows": int(group["n_independent"].eq(0).sum()),
            "max_expected_sum_abs_error": float((group["e_independent"] - group["jockey365_expected_top3"]).abs().max()),
            "max_adjusted_rate_abs_error": float((group["d_independent"] - group["jockey365_field_relative_top3"]).abs().max()),
        }
    receipt = {
        "status": "PASS",
        "scope": "independent rolling-feature calculation only; no model fit, pair prediction or candidate outcome metric",
        "source_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in [SOURCE, FEATURES, INPUT_CODE]},
        "target_rows": int(len(compared)),
        "api_record_id_join_missing": 0,
        "same_event_jockey_id_missing": 0,
        "n_exact": True,
        "top3_count_exact": True,
        "max_expected_sum_abs_error": max_e_error,
        "max_adjusted_rate_abs_error": max_d_error,
        "numeric_tolerance": {"expected_sum": 1e-9, "adjusted_rate": 1e-11},
        "max_history_date_at_or_before_T_minus_2": True,
        "zero_history_neutral": True,
        "oldest_h1_window": {
            "race_date": "2019-01-11", "cutoff": "2019-01-09",
            "open_lower_bound": "2018-01-09", "first_included_date": "2018-01-10",
            "source_first_date": str(starts["race_date"].min().date()),
            "window_source_coverage_sufficient": starts["race_date"].min() <= pd.Timestamp("2018-01-10"),
        },
        "rows_by_target_year": by_year,
        "definition": "C=T-2 calendar days; history dates (C-365 days,C]; n/S/E from selected complete-finisher starts; d=(S-E)/(n+20), with n=0 -> d=0",
    }
    out = REVIEW / "rolling_feature_independent.json"
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
