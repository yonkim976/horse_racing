"""Descriptive repeated-start time stability, separate from prediction accuracy."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("environment_ablation", HERE / "run.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def main():
    R.check_inputs()
    r = pd.read_parquet(R.OUT / "record_components.parquet")
    grades = pd.read_parquet(R.N.POP, columns=["row_key", "grade"])
    r = r.merge(grades, on="row_key", how="left", validate="one_to_one")
    r = r.sort_values(["horse_id", "race_date"]).reset_index(drop=True)
    r["profile19"] = r.finish_valid
    r["month19"] = r.finish_valid + r.month_add_seconds
    r["gate19"] = r.finish_valid + r.gate_add_seconds
    r["month_gate19"] = r.finish_valid + r.month_add_seconds + r.gate_add_seconds
    variants = ["profile19", *R.config()["variants"]]
    columns = ["race_date", "meet", "result_distance", "grade", "band", "month", "supported"]
    previous = r.groupby("horse_id", sort=False)[columns + variants].shift(1).add_prefix("prev_")
    r = pd.concat([r, previous], axis=1)
    # Invalid/intervening starts retain their positions and cannot be bridged.
    mask = (
        (r.race_date - r.prev_race_date).dt.days.between(3, 90)
        & r.race_date.ge("2024-01-01")
        & r.meet.eq(r.prev_meet)
        & r.result_distance.eq(r.prev_result_distance)
        & r.grade.notna()
        & r.grade.eq(r.prev_grade)
        & r.supported
        & r.prev_supported.fillna(False).astype(bool)
        & r.finish_valid.notna()
        & r.prev_profile19.notna()
    )
    pairs = r[mask].copy()
    for variant in variants:
        pairs[variant + "_abs"] = (pairs[variant] - pairs["prev_" + variant]).abs()
    pairs["changed_band"] = pairs.band.ne(pairs.prev_band)
    pairs["changed_month"] = pairs.month.ne(pairs.prev_month)
    rng = np.random.default_rng(20261008)
    results = []
    for meet, g in pairs.groupby("meet"):
        for subset, one in [
            ("all_pairs", g),
            ("changed_band", g[g.changed_band]),
            ("changed_month", g[g.changed_month]),
        ]:
            for variant in variants:
                delta = one[variant + "_abs"] - one.profile19_abs
                daily = (
                    pd.DataFrame({"date": one.race_date, "delta": delta})
                    .groupby("date")
                    .delta.agg(["sum", "size"])
                    .to_numpy()
                )
                draws = daily[rng.integers(len(daily), size=(2000, len(daily)))].sum(axis=1)
                results.append(
                    dict(
                        meet=int(meet),
                        subset=subset,
                        variant=variant,
                        pairs=len(one),
                        horses=int(one.horse_id.nunique()),
                        mean_abs_seconds=float(one[variant + "_abs"].mean()),
                        difference_from_profile19=float(delta.mean()),
                        date_bootstrap_95=np.quantile(
                            draws[:, 0] / draws[:, 1], [0.025, 0.975]
                        ).tolist(),
                    )
                )
    keep = R.KEY + ["race_date", "meet", "result_distance", "grade", "prev_race_date"]
    keep += ["changed_band", "changed_month"] + [v + "_abs" for v in variants]
    pairs[keep].to_parquet(R.OUT / "stability_pairs.parquet", index=False)
    R.save(R.OUT / "stability_diagnostic.json", results)
    R.check_inputs()
    print("Descriptive stability pairs", len(pairs), flush=True)


if __name__ == "__main__":
    main()
