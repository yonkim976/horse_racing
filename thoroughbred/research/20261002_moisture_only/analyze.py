"""Moisture-only retrospective study with frozen, prior-year models."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
AUDIT = HERE.parent / "20261002_track_source_reconciliation/results"
OUT = HERE / "outputs"
KEY = ["meet", "date", "race_no", "horse_id"]
PARTS = ["start_200", "last_200", "last_600", "finish"]
BANDS = ["건조", "양호", "다습", "포화", "불량"]
VARIANTS = ["none", "linear", "band", "exact"]
NEXT_VARIANTS = ["none", "band", "exact", "day"]
RATES = [0, 0.25, 0.5, 0.75, 1]
EXPECT_CAT = ["distance_m", "grade", "month"]
EXPECT_NUM = ["prev_time", "prev2_time", "gap_days", "weight", "gate"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(df):
    df = df.copy()
    df["dt"] = pd.to_datetime(df["date"])
    df["year"], df["month"] = df.dt.dt.year, df.dt.dt.month
    df["band"] = pd.cut(df.moisture, [0, 5, 9, 14, 19, np.inf], labels=BANDS).astype(str)
    df["moisture_exact"] = df.moisture.astype(int).astype(str)
    df["grade"] = df.grade.fillna("미상")
    df["race_key"] = df.meet.astype(str) + ":" + df.date + ":" + df.race_no.astype(str)
    df["day_key"] = df.meet.astype(str) + ":" + df.date
    for part in PARTS:
        df[part] = df[part] / 1000
    if df.duplicated(KEY).any() or df.moisture.isna().any():
        raise ValueError("Invalid population key or moisture")
    return df


def ridge_model(cats, nums, alpha):
    prep = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore"), cats),
            (
                "num",
                Pipeline(
                    [("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
                ),
                nums,
            ),
        ]
    )
    return Pipeline([("prep", prep), ("ridge", Ridge(alpha=alpha))])


def horse_residuals(rec):
    out = []
    for part in PARTS:
        hist = (
            rec[rec[part].notna()]
            .sort_values(["meet", "horse_id", "distance_m", "date", "race_no"])
            .copy()
        )
        group = hist.groupby(["meet", "horse_id", "distance_m"], sort=False)
        hist["prev_time"] = group[part].shift(1)
        hist["prev2_time"] = group[part].shift(2).fillna(hist.prev_time)
        hist["prev_date"] = group.dt.shift(1)
        hist["prev_key"] = group.race_key.shift(1)
        hist["gap_days"] = (hist.dt - hist.prev_date).dt.days
        hist = hist[hist.gap_days.between(1, 365)].copy()
        hist["gap_days"] = np.log1p(hist.gap_days)
        hist["target"], hist["part"] = hist[part], part
        for meet in (1, 3):
            one = hist[hist.meet.eq(meet)]
            for year in range(2020, 2027):
                train, test = one[one.year.lt(year)], one[one.year.eq(year)].copy()
                if len(train) < 100 or test.empty:
                    continue
                assert train.year.max() < year
                model = ridge_model(EXPECT_CAT, EXPECT_NUM, 20)
                model.fit(train, train.target)
                test["expected"] = model.predict(test)
                test["residual"] = test.target - test.expected
                test["expectation_trained_through"] = year - 1
                out.append(test)
    return pd.concat(out, ignore_index=True)


def races_from_horses(horse):
    key = ["meet", "part", "race_key"]
    races = (
        horse.groupby(key, sort=False)
        .agg(residual=("residual", "median"), runners=("residual", "size"))
        .reset_index()
    )
    fields = [
        "date",
        "dt",
        "year",
        "month",
        "distance_m",
        "race_no",
        "day_key",
        "band",
        "moisture",
        "moisture_exact",
    ]
    races = races.merge(horse.drop_duplicates(key)[key + fields], on=key, validate="one_to_one")
    return races[races.runners.ge(4)].copy()


def env_model(train, variant):
    cats, nums = ["distance_m", "month"], ["year", "race_no"]
    if variant in ("band", "exact"):
        cats.append("band")
    if variant == "exact":
        cats.append("moisture_exact")
    if variant == "linear":
        nums.append("moisture")
    model = ridge_model(cats, nums, 25)
    model.fit(train, train.residual)
    return model


def bootstrap(sample, differences, cluster="day_key"):
    frame = sample[[cluster]].copy()
    frame["diff"] = differences
    stats = frame.groupby(cluster).agg(total=("diff", "sum"), n=("diff", "size")).to_numpy()
    rng = np.random.default_rng(20261002)
    picks = rng.integers(0, len(stats), (1000, len(stats)))
    draws = stats[picks]
    values = draws[:, :, 0].sum(axis=1) / draws[:, :, 1].sum(axis=1)
    return [float(v) for v in np.quantile(values, [0.025, 0.975])]


def summarize_errors(frame, error_columns, baseline):
    result = []
    for (meet, part), one in frame.groupby(["meet", "part"]):
        for period in ["all", "2024", "2025", "2026"]:
            sample = one if period == "all" else one[one.year.eq(int(period))]
            if sample.empty:
                continue
            row = {
                "meet": int(meet),
                "part": part,
                "year": period,
                "n": len(sample),
                "days": sample.day_key.nunique(),
                "mae": {k: float(sample[v].mean()) for k, v in error_columns.items()},
                "deltas": {},
            }
            for variant, column in error_columns.items():
                if variant != baseline:
                    delta = sample[column] - sample[error_columns[baseline]]
                    row["deltas"][variant] = {
                        "mae_difference": float(delta.mean()),
                        "day_cluster_ci95": bootstrap(sample, delta),
                    }
            result.append(row)
    return result


def validate_race(race):
    rows, frozen = [], []
    for _, one in race.groupby(["meet", "part"]):
        for year in range(2021, 2027):
            train, test = one[one.year.lt(year)], one[one.year.eq(year)].copy()
            if len(train) < 100 or test.empty:
                continue
            reference = test.copy()
            reference["band"], reference["moisture"], reference["moisture_exact"] = "건조", 4, "4"
            for variant in VARIANTS:
                model = env_model(train, variant)
                prediction = model.predict(test)
                test[f"err_{variant}"] = np.abs(test.residual - prediction)
                test[f"effect_{variant}"] = (
                    prediction - model.predict(reference) if variant != "none" else 0.0
                )
                if variant == "exact":
                    test["percent_seen_in_training"] = test.moisture_exact.isin(
                        train.moisture_exact
                    )
            test["environment_trained_through"] = year - 1
            # Only other completed races from this source day enter the day estimate.
            test["leftover"] = test.residual - test.effect_band
            test["day_extra"] = 0.0
            for ix in test.groupby("day_key").groups.values():
                day = test.loc[ix]
                number = day.race_no.to_numpy(float)
                weights = np.exp(-np.abs(number[:, None] - number[None, :]) / 3)
                np.fill_diagonal(weights, 0)
                extra = weights @ day.leftover.to_numpy(float) / (weights.sum(axis=1) + 4)
                extra[(weights > 0).sum(axis=1) < 3] = 0
                test.loc[ix, "day_extra"] = extra
            test["effect_day"] = test.effect_band + test.day_extra
            frozen.append(test)
            if year >= 2024:
                rows.append(test)
    frozen_frame, evaluation = (
        pd.concat(frozen, ignore_index=True),
        pd.concat(rows, ignore_index=True),
    )
    summary = summarize_errors(evaluation, {v: f"err_{v}" for v in VARIANTS}, "none")
    for row in summary:
        sample = evaluation[evaluation.meet.eq(row["meet"]) & evaluation.part.eq(row["part"])]
        if row["year"] != "all":
            sample = sample[sample.year.eq(int(row["year"]))]
        row["unseen_exact_percent_races"] = int((~sample.percent_seen_in_training).sum())
        row["exact_minus_band"] = {
            "mae_difference": float((sample.err_exact - sample.err_band).mean()),
            "day_cluster_ci95": bootstrap(sample, sample.err_exact - sample.err_band),
        }
    return frozen_frame, evaluation, summary


def ols_contrasts(one, exposure, reference, distance):
    values = one[exposure].astype(str)
    levels = [reference] + sorted(v for v in values.unique() if v != reference)
    if reference not in set(values):
        return []
    design = pd.DataFrame(
        {"intercept": np.ones(len(one)), "race_no": one.race_no.to_numpy(float)}, index=one.index
    )
    cat = pd.Categorical(values, categories=levels)
    d = pd.get_dummies(
        pd.Series(cat, index=one.index), prefix="exposure", drop_first=True, dtype=float
    )
    design = pd.concat([design, d], axis=1)
    nuisance = ["year", "month"] + (["distance_m"] if distance is None else [])
    design = pd.concat(
        [design, pd.get_dummies(one[nuisance].astype(str), drop_first=True, dtype=float)], axis=1
    )
    x, y = design.to_numpy(float), one.residual.to_numpy(float)
    inverse = np.linalg.pinv(x.T @ x)
    beta = inverse @ x.T @ y
    errors = y - x @ beta
    scores = pd.DataFrame(x * errors[:, None]).groupby(one.day_key.to_numpy()).sum().to_numpy()
    covariance = inverse @ (scores.T @ scores) @ inverse
    g = len(scores)
    rank = np.linalg.matrix_rank(x)
    covariance *= g / max(g - 1, 1) * (len(one) - 1) / max(len(one) - rank, 1)
    results = []
    reference_days = one.loc[values.eq(reference), "day_key"].nunique()
    for level in levels[1:]:
        support = one[values.eq(level)]
        days = support.day_key.nunique()
        if support.empty:
            continue
        index = design.columns.get_loc("exposure_" + level)
        estimate, se = float(beta[index]), float(np.sqrt(max(covariance[index, index], 0)))
        enough = days >= 20 and reference_days >= 20
        results.append(
            {
                "meet": int(one.meet.iloc[0]),
                "part": one.part.iloc[0],
                "distance_m": distance,
                "exposure": exposure,
                "level": level,
                "reference": reference,
                "races": len(support),
                "days": days,
                "reference_days": reference_days,
                "seconds": estimate,
                "ci95": [estimate - 1.96 * se, estimate + 1.96 * se] if enough else None,
                "support_status": "supported" if enough else "insufficient_days",
            }
        )
    return results


def descriptive(race):
    out = []
    for _, one in race.groupby(["meet", "part"]):
        for distance in [None] + sorted(int(v) for v in one.distance_m.unique()):
            sample = one if distance is None else one[one.distance_m.eq(distance)]
            if len(sample) < 100:
                continue
            out.extend(ols_contrasts(sample, "band", "건조", distance))
            if distance in (None, 1200):
                out.extend(ols_contrasts(sample, "moisture_exact", "4", distance))
    return out


def next_validation(horse, frozen):
    prior = horse[["meet", "part", "horse_id", "race_key", "target", "expected", "year"]].rename(
        columns={
            "race_key": "prev_key",
            "target": "prev_target",
            "expected": "prev_expected",
            "year": "prev_year",
        }
    )
    # Require the immediate previous measured start itself to have an external expectation.
    h = horse.merge(
        prior, on=["meet", "part", "horse_id", "prev_key"], how="inner", validate="many_to_one"
    )
    effects = frozen[
        ["meet", "part", "race_key", "day_key", "band", "moisture", "environment_trained_through"]
        + [f"effect_{v}" for v in NEXT_VARIANTS]
    ].rename(
        columns={
            "race_key": "prev_key",
            "day_key": "prev_day_key",
            "band": "prev_band",
            "moisture": "prev_moisture",
        }
    )
    h = h.merge(effects, on=["meet", "part", "prev_key"], how="inner", validate="many_to_one")
    assert (h.prev_date < h.dt).all()
    assert (h.environment_trained_through < h.prev_year).all()
    h["prev_residual"] = h.prev_target - h.prev_expected
    for v in NEXT_VARIANTS:
        h[f"z_{v}"] = h.prev_residual - h[f"effect_{v}"]
        h[f"fixed_{v}"] = np.abs(h.target - (h.expected + 0.5 * h[f"z_{v}"]))
    h["err_expected"] = np.abs(h.target - h.expected)
    results, predictions, chosen = {}, [], []
    for scope in ("cross_year", "all_previous_dates"):
        source = h[h.prev_year.lt(h.year)].copy() if scope == "cross_year" else h.copy()
        evaluation = []
        for (meet, part), one in source.groupby(["meet", "part"]):
            for year in (2024, 2025, 2026):
                train, test = one[one.year.lt(year)], one[one.year.eq(year)].copy()
                if test.empty:
                    continue
                for v in NEXT_VARIANTS:
                    means = [
                        float(np.abs(train.target - (train.expected + r * train[f"z_{v}"])).mean())
                        for r in RATES
                    ]
                    rate = RATES[int(np.argmin(means))] if len(train) >= 100 else 0
                    chosen.append(
                        {
                            "scope": scope,
                            "meet": int(meet),
                            "part": part,
                            "year": year,
                            "variant": v,
                            "rate": rate,
                            "training_runs": len(train),
                            "training_year_max": int(train.year.max()) if len(train) else None,
                        }
                    )
                    test[f"selected_{v}"] = np.abs(
                        test.target - (test.expected + rate * test[f"z_{v}"])
                    )
                test["scope"] = scope
                evaluation.append(test)
        frame = pd.concat(evaluation, ignore_index=True)
        errors = {
            "expected_only": "err_expected",
            **{f"fixed_{v}": f"fixed_{v}" for v in NEXT_VARIANTS},
            **{f"selected_{v}": f"selected_{v}" for v in NEXT_VARIANTS},
        }
        results[scope] = summarize_errors(frame, errors, "expected_only")
        predictions.append(frame)
    return results, pd.concat(predictions, ignore_index=True), chosen


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite study outputs")
    OUT.mkdir()
    input_paths = [
        AUDIT / "api_study_population.parquet",
        AUDIT / "api_band_percent_conflicts.csv",
        AUDIT / "runner_clean_differences.csv",
        HERE / "PLAN.md",
    ]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in input_paths}
    api = pd.read_parquet(input_paths[0])
    bad = pd.read_csv(input_paths[1])[KEY[:3]].drop_duplicates()
    differences = pd.read_csv(input_paths[2], dtype={"horse_id": str})
    bad = pd.concat(
        [bad, differences[differences.status.eq("different")][KEY[:3]]]
    ).drop_duplicates()
    quality = api.merge(bad.assign(excluded=True), on=KEY[:3], how="left", validate="many_to_one")
    quality = quality[quality.excluded.isna()].drop(columns="excluded")
    summary = {
        "inputs_sha256": hashes,
        "excluded_races": len(bad),
        "excluded_runners": len(api) - len(quality),
        "no_track_speed": True,
        "scenarios": {},
    }
    for name, rec in (("quality_filtered", quality), ("all_api", api)):
        directory = OUT / name
        directory.mkdir()
        rec = prepare(rec)
        horse = horse_residuals(rec)
        race = races_from_horses(horse)
        frozen, evaluation, validation = validate_race(race)
        next_summary, next_frame, rates = next_validation(horse, frozen)
        contrasts = descriptive(race)
        horse.to_parquet(directory / "horse_residuals.parquet", index=False)
        race.to_parquet(directory / "race_residuals.parquet", index=False)
        frozen.to_parquet(directory / "frozen_environment_effects.parquet", index=False)
        evaluation.to_parquet(directory / "race_evaluation.parquet", index=False)
        next_frame.to_parquet(directory / "next_evaluation.parquet", index=False)
        counts = (
            race.groupby(["meet", "part", "band"], observed=True)
            .agg(
                races=("race_key", "size"), days=("day_key", "nunique"), runners=("runners", "sum")
            )
            .reset_index()
        )
        counts.to_csv(directory / "coverage.csv", index=False)
        desc = pd.DataFrame(contrasts)
        desc.to_json(directory / "contrasts.json", orient="records", force_ascii=False, indent=2)
        pd.DataFrame(rates).to_csv(directory / "selected_rates.csv", index=False)
        summary["scenarios"][name] = {
            "runners": len(rec),
            "horse_residuals": len(horse),
            "race_residuals": len(race),
            "coverage": counts.to_dict("records"),
            "race_validation": validation,
            "next_validation": next_summary,
            "selected_rates": rates,
            "contrasts": contrasts,
        }
        print(
            json.dumps(
                {
                    "scenario": name,
                    "runners": len(rec),
                    "race_residuals": len(race),
                    "finish_race_validation": [
                        r for r in validation if r["part"] == "finish" and r["year"] == "all"
                    ],
                    "finish_next_validation": [
                        r
                        for r in next_summary["cross_year"]
                        if r["part"] == "finish" and r["year"] == "all"
                    ],
                },
                ensure_ascii=False,
            )
        )
    assert hashes == {str(p.relative_to(ROOT)): sha(p) for p in input_paths}
    summary["inputs_unchanged"] = True
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
