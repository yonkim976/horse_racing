"""Prior-year adjusted daily, Friday-Sunday, and year-month lateral/gate deviations."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
PREVIOUS = HERE.parent / "20261002_gate_lateral_bias"
SPEC = importlib.util.spec_from_file_location("bias", PREVIOUS / "analyze.py")
BIAS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BIAS)
METRICS = ["raw", "ability_adjusted", "expected", "deviation"]
YEARS = list(range(2020, 2027))


def numeric_metadata(train, keys, paired=False):
    result = {}
    for key in keys:
        v = (
            np.concatenate([train[f"inner_{key}"], train[f"outer_{key}"]])
            if paired
            else train[key].to_numpy(float)
        )
        finite = v[np.isfinite(v)]
        result[key] = {
            "median": float(np.median(finite)) if len(finite) else 0,
            "scale": float(finite.std()) if len(finite) and finite.std() > 1e-10 else 1,
        }
    return result


def ability_columns(frame, metadata, paired=False):
    vectors, labels = [], []
    for key, info in metadata.items():
        if paired:
            a, b = frame[f"inner_{key}"].to_numpy(float), frame[f"outer_{key}"].to_numpy(float)
            ma, mb = ~np.isfinite(a), ~np.isfinite(b)
            value = np.where(mb, info["median"], b) - np.where(ma, info["median"], a)
            missing = mb.astype(float) - ma.astype(float)
        else:
            v = frame[key].to_numpy(float)
            absent = ~np.isfinite(v)
            value = np.where(absent, info["median"], v) - info["median"]
            missing = absent.astype(float)
        vectors.extend([value / info["scale"], missing])
        labels.extend([f"ability:{key}", f"ability_missing:{key}"])
    return vectors, labels


def design(frame, levels, metadata, paired=False):
    if paired:
        vectors, labels = [np.ones(len(frame))], ["intercept"]
        for key, values in levels.items():
            for value in values[1:]:
                vectors.append(frame[key].eq(value).to_numpy(float))
                labels.append(f"condition:{key}:{value}")
    else:
        vectors, labels = [], []
        for side in ["middle", "outer"]:
            indicator = frame.gate_side.eq(side).to_numpy(float)
            vectors.append(indicator)
            labels.append(f"gate:{side}")
            for key, values in levels.items():
                for value in values[1:]:
                    vectors.append(indicator * frame[key].eq(value).to_numpy(float))
                    labels.append(f"gate:{side}:{key}:{value}")
    condition_columns = len(vectors)
    numeric, names = ability_columns(frame, metadata, paired)
    return np.column_stack(vectors + numeric), labels + names, condition_columns


def fit_prior(train, paired):
    keys = ["distance_m", "band", "month"] + ([] if paired else ["n"])
    levels = {key: sorted(train[key].unique().tolist()) for key in keys}
    metadata = numeric_metadata(train, BIAS.CONTROLS + (["gate_pct"] if paired else []), paired)
    x, labels, k = design(train, levels, metadata, paired)
    if paired:
        y = train.top3_difference.to_numpy(float)
    else:
        code = pd.factorize(train.race_key)[0]
        counts = np.bincount(code)
        x = x - np.column_stack([np.bincount(code, weights=v)[code] / counts[code] for v in x.T])
        y = train.top3.to_numpy(float, copy=True)
        y -= np.bincount(code, weights=y)[code] / counts[code]
    count = train.groupby("race_key").race_key.transform("size").to_numpy()
    weights = 1 / count
    xw, yw = x * np.sqrt(weights[:, None]), y * np.sqrt(weights)
    beta = np.linalg.pinv(xw.T @ xw, rcond=1e-10) @ (xw.T @ yw)
    assert np.isfinite(beta).all()
    return beta, levels, metadata, labels, k


def source_support(train, test):
    support = train.groupby("distance_m").agg(
        races=("race_key", "nunique"), days=("day_key", "nunique")
    )
    return np.array(
        [
            d in support.index and support.loc[d, "races"] >= 50 and support.loc[d, "days"] >= 20
            for d in test.distance_m
        ],
        bool,
    )


def frozen_races(runners, pairs):
    rows, models = [], []
    targets = [(int(meet), "gate", False, one) for meet, one in runners.groupby("meet")]
    targets += [
        (int(meet), point, True, one) for (meet, point), one in pairs.groupby(["meet", "point"])
    ]
    for meet, point, paired, source in targets:
        for year in YEARS:
            train, test = source[source.year.lt(year)].copy(), source[source.year.eq(year)].copy()
            if test.empty:
                continue
            beta, levels, metadata, labels, k = fit_prior(train, paired)
            x, _, _ = design(test, levels, metadata, paired)
            test["predicted_condition"] = x[:, :k] @ beta[:k]
            test["predicted_ability"] = x[:, k:] @ beta[k:]
            test["baseline_supported"] = source_support(train, test)
            meta = [
                "meet",
                "date",
                "dt",
                "year",
                "month",
                "race_no",
                "race_key",
                "day_key",
                "distance_m",
                "band",
                "baseline_supported",
            ]
            if paired:
                test["raw"] = test.top3_difference
                for name in ["raw", "predicted_condition", "predicted_ability"]:
                    test[name] = test.groupby("race_key")[name].transform("mean")
                race = test.drop_duplicates("race_key")[
                    meta + ["raw", "predicted_condition", "predicted_ability"]
                ].copy()
            else:
                means = (
                    test.groupby(["race_key", "gate_side"])[
                        ["top3", "predicted_condition", "predicted_ability"]
                    ]
                    .mean()
                    .unstack("gate_side")
                )
                race = test.drop_duplicates("race_key")[meta].set_index("race_key")
                for field, name in [
                    ("top3", "raw"),
                    ("predicted_condition", "predicted_condition"),
                    ("predicted_ability", "predicted_ability"),
                ]:
                    race[name] = means[field]["outer"] - means[field]["inner"]
                race = race.reset_index()
            race["ability_adjusted"] = race.raw - race.predicted_ability
            race["expected"] = race.predicted_condition
            race["deviation"] = race.ability_adjusted - race.expected
            race["point"] = point
            race["baseline_trained_through"] = int(train.year.max())
            assert train.year.max() < year
            assert race[METRICS].notna().all().all()
            rows.append(race.drop(columns=["predicted_condition", "predicted_ability"]))
            models.append(
                {
                    "meet": meet,
                    "point": point,
                    "year": year,
                    "trained_through": int(train.year.max()),
                    "train_rows": len(train),
                    "test_races": len(race),
                    "baseline_supported_races": int(race.baseline_supported.sum()),
                    "levels": levels,
                    "numeric_metadata": metadata,
                    "condition_columns": k,
                    "labels": labels,
                    "coefficients": beta.tolist(),
                }
            )
        print(f"Frozen annual baselines: meet={meet}, point={point}", flush=True)
    return pd.concat(rows, ignore_index=True), models


def interval_month(frame):
    values = frame.deviation
    n, days = len(frame), frame.day_key.nunique()
    if days < 2:
        return None, None
    mean = float(values.mean())
    scores = (values - mean).groupby(frame.day_key).sum()
    se = float(np.sqrt(days / (days - 1) * np.square(scores).sum() / n**2))
    cutoff = float(t.ppf(0.975, days - 1))
    p = float(2 * t.sf(abs(mean / se), days - 1)) if se > 1e-14 else 1.0
    return [(mean - cutoff * se) * 100, (mean + cutoff * se) * 100], p


def summarize_periods(races):
    rows = []
    rng = np.random.default_rng(20261003)
    for (meet, point), venue in races[races.baseline_supported].groupby(["meet", "point"]):
        for window in ["date", "weekend", "month"]:
            sample = venue if window != "weekend" else venue[venue.dt.dt.dayofweek.ge(4)]
            key = {"date": "date", "weekend": "weekend_start", "month": "year_month"}[window]
            distances = [None] + sorted(set(sample.distance_m) & set(BIAS.DISTANCES))
            for distance in distances:
                subset = sample if distance is None else sample[sample.distance_m.eq(distance)]
                for period, one in subset.groupby(key):
                    n, days = len(one), one.day_key.nunique()
                    minimum = (
                        {"date": 5, "weekend": 10, "month": 40}[window]
                        if distance is None
                        else {"date": 3, "weekend": 4, "month": 12}[window]
                    )
                    support = n >= minimum and days >= {"date": 1, "weekend": 2, "month": 6}[window]
                    row = {
                        "meet": int(meet),
                        "point": point,
                        "window": window,
                        "period": str(period),
                        "distance_m": None if distance is None else int(distance),
                        "races": n,
                        "days": int(days),
                        "supported": bool(support),
                        "start_date": one.date.min(),
                        "end_date": one.date.max(),
                        "mean_moisture_band": one.band.value_counts().to_dict(),
                        **{f"{name}_pp": float(one[name].mean()) * 100 for name in METRICS},
                    }
                    row["shrink_weight"] = n / (n + 40)
                    row["shrunk_deviation_pp"] = row["deviation_pp"] * row["shrink_weight"]
                    row["ci95_pp"], row["p"] = None, None
                    row["interval_kind"] = (
                        "not_available_with_two_or_three_day_clusters"
                        if window == "weekend"
                        else "day_cluster_t"
                        if window == "month"
                        else "race_resample_exploratory"
                    )
                    if window == "month":
                        row["ci95_pp"], row["p"] = interval_month(one)
                    elif window == "date" and n >= 3:
                        values = one.deviation.to_numpy(float)
                        picks = rng.integers(0, n, size=(1000, n))
                        row["ci95_pp"] = (
                            np.quantile(values[picks].mean(axis=1), [0.025, 0.975]) * 100
                        ).tolist()
                    rows.append(row)
    for is_gate in [True, False]:
        family = [
            r
            for r in rows
            if (r["point"] == "gate") == is_gate
            and r["window"] == "month"
            and r["distance_m"] is None
            and r["supported"]
            and r["p"] is not None
        ]
        for row, q in zip(family, BIAS.POSITION.bh([r["p"] for r in family]), strict=True):
            row["q_month"] = float(q)
    return pd.DataFrame(rows)


def monthly_permutation(races, period_table):
    rows = []
    rng = np.random.default_rng(20261004)
    for (meet, point), one in races[races.baseline_supported].groupby(["meet", "point"]):
        daily = (
            one.groupby("date")
            .agg(
                total=("deviation", "sum"),
                n=("deviation", "size"),
                year=("year", "first"),
                year_month=("year_month", "first"),
                weekday=("weekday", "first"),
            )
            .reset_index()
        )
        month_code, months = pd.factorize(daily.year_month, sort=True)
        years = np.array([int(str(month)[:4]) for month in months])
        eligible = period_table[
            period_table.meet.eq(meet)
            & period_table.point.eq(point)
            & period_table.window.eq("month")
            & period_table.distance_m.isna()
            & period_table.supported
        ].period
        mask = np.isin(months, eligible)
        if mask.sum() < 6:
            continue
        annual = daily.groupby("year").agg(total=("total", "sum"), n=("n", "sum"))
        reference = np.array([annual.loc[y, "total"] / annual.loc[y, "n"] for y in years])
        total, count = daily.total.to_numpy(), daily.n.to_numpy()
        blocks = [
            indices.to_numpy() for _, indices in daily.groupby(["year", "weekday"]).groups.items()
        ]

        def statistic(sums, ns):
            totals = np.bincount(month_code, weights=sums, minlength=len(months))
            counts = np.bincount(month_code, weights=ns, minlength=len(months))
            mean = totals / counts
            return float(
                np.sum(counts[mask] * np.square(mean[mask] - reference[mask])) / counts[mask].sum()
            )

        observed = statistic(total, count)
        null = []
        for _ in range(1000):
            permutation = np.arange(len(daily))
            for block in blocks:
                permutation[block] = rng.permutation(block)
            null.append(statistic(total[permutation], count[permutation]))
        p = (1 + int(np.sum(np.asarray(null) >= observed))) / 1001
        rows.append(
            {
                "meet": int(meet),
                "point": point,
                "eligible_months": int(mask.sum()),
                "observed_variance": observed,
                "null_median_variance": float(np.median(null)),
                "observed_to_null_median": observed / float(np.median(null)),
                "p": float(p),
            }
        )
    for is_gate in [True, False]:
        family = [r for r in rows if (r["point"] == "gate") == is_gate]
        for row, q in zip(family, BIAS.POSITION.bh([r["p"] for r in family]), strict=True):
            row["q"] = float(q)
    return rows


def day_phases(races):
    phases = races[races.baseline_supported].copy()
    phases["phase"] = np.where(
        phases.race_no.le(3), "early", np.where(phases.race_no.le(6), "middle", "late")
    )
    table = (
        phases.groupby(["meet", "point", "date", "phase"])
        .agg(
            races=("race_key", "size"),
            ability_adjusted=("ability_adjusted", "mean"),
            expected=("expected", "mean"),
            deviation=("deviation", "mean"),
        )
        .reset_index()
    )
    changes = []
    for (meet, point, date), group in table.groupby(["meet", "point", "date"]):
        indexed = group.set_index("phase")
        if (
            not {"early", "late"}.issubset(indexed.index)
            or min(indexed.loc["early", "races"], indexed.loc["late", "races"]) < 3
        ):
            continue
        early, late = indexed.loc["early"], indexed.loc["late"]
        changes.append(
            {
                "meet": int(meet),
                "point": point,
                "date": date,
                "early_races": int(early.races),
                "late_races": int(late.races),
                "early_adjusted_pp": float(early.ability_adjusted) * 100,
                "late_adjusted_pp": float(late.ability_adjusted) * 100,
                "early_deviation_pp": float(early.deviation) * 100,
                "late_deviation_pp": float(late.deviation) * 100,
                "late_minus_early_deviation_pp": float(late.deviation - early.deviation) * 100,
                "observed_direction_reversal": bool(
                    early.ability_adjusted * late.ability_adjusted < 0
                ),
            }
        )
    return table, pd.DataFrame(changes)


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite outputs")
    paths = [
        HERE / "PLAN.md",
        HERE / "analyze.py",
        PREVIOUS / "analyze.py",
        PREVIOUS / "outputs/runners.parquet",
        PREVIOUS / "outputs/pack_pairs.parquet",
        PREVIOUS / "outputs/summary.json",
        PREVIOUS / "outputs/verification.json",
    ]
    hashes = {str(p): BIAS.sha(p) for p in paths}
    OUT.mkdir()
    runners, pairs = pd.read_parquet(paths[3]), pd.read_parquet(paths[4])
    for frame in [runners, pairs]:
        frame["dt"] = pd.to_datetime(frame.date)
        frame["month"] = frame.dt.dt.month
        frame["race_no"] = frame.race_key.str.rsplit(":", n=1).str[-1].astype(int)
    races, models = frozen_races(runners, pairs)
    races["weekday"] = races.dt.dt.dayofweek
    races["year_month"] = races.dt.dt.strftime("%Y-%m")
    races["weekend_start"] = (
        races.dt - pd.to_timedelta((races.weekday - 4) % 7, unit="D")
    ).dt.strftime("%Y-%m-%d")
    assert not races.duplicated(["meet", "point", "race_key"]).any()
    assert (races.baseline_trained_through < races.year).all()
    races = races.sort_values(["meet", "point", "date", "race_no"]).reset_index(drop=True)
    races.to_parquet(OUT / "race_deviations.parquet", index=False)
    (OUT / "baseline_models.json").write_text(json.dumps(models, ensure_ascii=False, indent=2))
    print("Summarizing dates, weekends and months", flush=True)
    periods = summarize_periods(races)
    periods.to_parquet(OUT / "periods.parquet", index=False)
    for window in ["date", "weekend", "month"]:
        periods[periods.window.eq(window)].drop(columns=["mean_moisture_band"]).to_csv(
            OUT / f"{window}_effects.csv", index=False
        )
    print("Permuting complete day cards within year and weekday", flush=True)
    permutation = monthly_permutation(races, periods)
    phases, changes = day_phases(races)
    phases.to_csv(OUT / "day_phases.csv", index=False)
    changes.to_csv(OUT / "early_late_changes.csv", index=False)
    monthly = periods[
        periods.window.eq("month") & periods.distance_m.isna() & periods.supported
    ].copy()
    monthly[monthly.q_month.lt(0.05)].to_json(
        OUT / "supported_month_candidates.json", orient="records", force_ascii=False, indent=2
    )
    assert hashes == {str(p): BIAS.sha(p) for p in paths}
    summary = {
        "inputs_sha256": hashes,
        "baseline_models": len(models),
        "race_rows": len(races),
        "unsupported_baseline_race_rows": int((~races.baseline_supported).sum()),
        "non_weekend_race_rows": int(races.weekday.lt(4).sum()),
        "period_counts": periods.groupby(["meet", "point", "window"])
        .agg(rows=("period", "size"), supported=("supported", "sum"))
        .reset_index()
        .to_dict("records"),
        "monthly_summary": monthly.groupby(["meet", "point"])
        .agg(
            supported_months=("period", "size"),
            minimum_deviation_pp=("deviation_pp", "min"),
            maximum_deviation_pp=("deviation_pp", "max"),
        )
        .reset_index()
        .to_dict("records"),
        "monthly_candidates": monthly[monthly.q_month.lt(0.05)]
        .drop(columns=["mean_moisture_band"])
        .to_dict("records"),
        "monthly_permutation": permutation,
        "phase_reversals": changes.groupby(["meet", "point"])
        .agg(
            eligible_days=("date", "size"),
            observed_reversals=("observed_direction_reversal", "sum"),
        )
        .reset_index()
        .to_dict("records"),
        "validation": {
            "inputs_unchanged": True,
            "prior_year_baselines_only": True,
            "prior_baseline_supported_flag_preserved": True,
            "no_actual_time_of_day_claim": True,
        },
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary["monthly_summary"], ensure_ascii=False), flush=True)
    print(json.dumps(summary["monthly_candidates"], ensure_ascii=False), flush=True)
    print(json.dumps(permutation, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
