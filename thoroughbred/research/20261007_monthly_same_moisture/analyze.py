"""Reuse verified monthly fits; derive paired month contrasts and annual matched checks."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "20261007_seasonal_same_moisture/outputs"
OUT = HERE / "outputs"
KEY = ["meet", "distance_m", "band", "part"]
PARTS = ["early", "middle1", "middle2", "late", "finish", "last600"]
INPUTS = [
    "controlled_month_season_contrasts.csv",
    "date_bootstrap_contrasts.parquet",
    "recent_complete_year_contrasts.csv",
    "race_means.parquet",
    "verification.json",
    "summary.json",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(value):
    return json.loads(pd.DataFrame(value).to_json(orient="records", force_ascii=False))


def monthly(source):
    d = pd.read_csv(source, dtype={"label": str})
    d = d.loc[d.kind.eq("month")].copy()
    d["month"] = d.label.astype(int)
    d["uncertainty_available"] = d.bootstrap_valid_n.ge(180)
    d["interpretation_support"] = d.status.eq("supported") & d.uncertainty_available
    return d.sort_values(KEY + ["month"]).reset_index(drop=True)


def paired(levels, bootstrap):
    """Subtract within each joint date bootstrap, never subtract CI endpoints."""
    by = bootstrap.loc[bootstrap.kind.eq("month")].copy()
    by["month"] = by.label.astype(int)
    groups = {
        k: g.pivot(index="replicate", columns="month", values="difference")
        for k, g in by.groupby(KEY, observed=True)
    }
    result = []
    pairs = [(m, 12 if m == 1 else m - 1, "adjacent") for m in range(1, 13)]
    pairs.append((10, 8, "october_vs_august_exploratory"))
    for key, d in levels.groupby(KEY, observed=True):
        d = d.set_index("month")
        pivot = groups.get(key)
        for target, reference, comparison in pairs:
            a, b = d.loc[target], d.loc[reference]
            point = a.difference - b.difference
            reps = np.array([], dtype=float)
            if pivot is not None and target in pivot and reference in pivot:
                reps = (pivot[target] - pivot[reference]).dropna().to_numpy()
            lo, hi = np.quantile(reps, [0.025, 0.975]) if len(reps) >= 180 else (np.nan, np.nan)
            result.append(
                dict(zip(KEY, key, strict=True))
                | dict(
                    comparison=comparison,
                    target_month=target,
                    reference_month=reference,
                    difference=point,
                    ci_low=lo,
                    ci_high=hi,
                    bootstrap_valid_n=len(reps),
                    target_status=a.status,
                    reference_status=b.status,
                    interpretation_support=bool(
                        a.interpretation_support and b.interpretation_support and len(reps) >= 180
                    ),
                    ci_excludes_zero=bool(np.isfinite(lo) and (hi < 0 or lo > 0)),
                    reference_note=(
                        "same-calendar-year monthly coefficients; not a chronological Dec-Jan event"
                    )
                    if target == 1
                    else "target minus reference month; exploratory pointwise interval",
                )
            )
    return pd.DataFrame(result)


def annual_matches(races):
    """Annual sensitivity only: exact grade/moisture matched race means, no ability controls.

    March-November versus pooled winter races, 2018-2025 complete calendar years.
    This reference differs from equal-weight winter month coefficients in the main fit.
    """
    records, strata = [], []
    for (meet, distance), all_races in races.groupby(["meet", "distance_m"], observed=True):
        for band in ["전체", "건조", "양호", "다습", "포화", "불량"]:
            data = all_races if band == "전체" else all_races.loc[all_races.band.eq(band)]
            for year in range(2018, 2026):
                year_data = data.loc[data.year.eq(year)]
                winter = year_data.loc[year_data.month.isin([12, 1, 2])]
                for month in range(3, 12):
                    target = year_data.loc[year_data.month.eq(month)]

                    def aggregate(d, suffix):
                        return d.groupby(["grade", "moisture"], observed=True).agg(
                            **{
                                suffix + "_mean": ("finish", "mean"),
                                suffix + "_races": ("finish", "size"),
                            }
                        )

                    match = aggregate(target, "target").join(
                        aggregate(winter, "winter"), how="inner"
                    )
                    match["weight"] = (
                        match.target_races
                        * match.winter_races
                        / (match.target_races + match.winter_races)
                    )
                    match["difference"] = match.target_mean - match.winter_mean
                    identity = dict(
                        meet=meet, distance_m=int(distance), band=band, year=year, month=month
                    )
                    strata.extend(identity | row for row in match.reset_index().to_dict("records"))
                    valid_keys = set(match.index)
                    t = target.loc[
                        [k in valid_keys for k in zip(target.grade, target.moisture, strict=True)]
                    ]
                    w = winter.loc[
                        [k in valid_keys for k in zip(winter.grade, winter.moisture, strict=True)]
                    ]
                    supported = (
                        len(match) >= 2
                        and len(t) >= 3
                        and len(w) >= 3
                        and t.date.nunique() >= 2
                        and w.date.nunique() >= 2
                    )
                    records.append(
                        identity
                        | dict(
                            matched_strata=len(match),
                            target_races=len(t),
                            winter_races=len(w),
                            target_days=t.date.nunique(),
                            winter_days=w.date.nunique(),
                            difference=np.average(match.difference, weights=match.weight)
                            if len(match)
                            else np.nan,
                            descriptive_support=bool(supported),
                        )
                    )
    return pd.DataFrame(records), pd.DataFrame(strata)


def main():
    OUT.mkdir(exist_ok=True)
    hashes = {name: sha(SOURCE / name) for name in INPUTS}
    inherited = json.loads((SOURCE / "verification.json").read_text())
    assert inherited["passed"] and inherited["inputs_unchanged"]
    levels = monthly(SOURCE / INPUTS[0])
    assert len(levels) == 8208 and not levels.duplicated(KEY + ["month"]).any()
    recent = monthly(SOURCE / "recent_complete_year_contrasts.csv")
    transitions = paired(levels, pd.read_parquet(SOURCE / "date_bootstrap_contrasts.parquet"))
    races = pd.read_parquet(SOURCE / "race_means.parquet")
    annual, strata = annual_matches(races)
    stability = []
    for key, d in annual.groupby(["meet", "distance_m", "band", "month"], observed=True):
        d = d.loc[d.descriptive_support]
        stability.append(
            dict(zip(["meet", "distance_m", "band", "month"], key, strict=True))
            | dict(
                eligible_years=len(d),
                faster_years=int(d.difference.lt(0).sum()),
                slower_years=int(d.difference.gt(0).sum()),
                year_list=",".join(d.year.astype(str)),
                median_difference=d.difference.median(),
                minimum=d.difference.min(),
                maximum=d.difference.max(),
                threshold="at least 2 matched strata; each group >=3 races and >=2 dates",
            )
        )
    stability = pd.DataFrame(stability)
    for name, data in [
        ("monthly_levels.csv", levels),
        ("paired_month_differences.csv", transitions),
        ("recent_monthly_levels.csv", recent),
        ("yearly_monthly_matches.csv", annual),
        ("yearly_matched_strata.csv", strata),
        ("monthly_year_stability.csv", stability),
    ]:
        data.to_csv(OUT / name, index=False)
    summary = dict(
        version="monthly_same_moisture_v1",
        completed_on="2026-10-07",
        source_study="20261007_seasonal_same_moisture",
        new_ols_fit=False,
        runner_records=151074,
        races=len(races),
        venue_distance_pairs=19,
        distance_count=11,
        dates=races[["meet", "date"]].drop_duplicates().shape[0],
        monthly_rows=len(levels),
        paired_rows=len(transitions),
        annual_rows=len(annual),
        monthly_supported_with_interval=int(levels.interpretation_support.sum()),
        complete_year_sensitivity="2024-2025 source fit; no new bootstrap",
        yearly_matching=(
            "2018-2025; March-November vs pooled winter, exact grade and numeric moisture; "
            "no ability controls"
        ),
        input_sha256=hashes,
        prior_benchmarks_changed=False,
        adopted_correction=False,
    )
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    assert hashes == {name: sha(SOURCE / name) for name in INPUTS}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
