"""Verify frozen predictions, aggregation, calendar rules and cluster inference."""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("study", HERE / "analyze.py")
STUDY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STUDY)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bh(p):
    p = np.asarray(p, float)
    order = np.argsort(p)
    q = np.minimum.accumulate((p[order] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    answer = np.empty(len(p))
    answer[order] = np.minimum(q, 1)
    return answer


def matrix(frame, model):
    """Reconstruct saved feature labels without calling the study design helper."""
    vectors = []
    paired = model["point"] != "gate"
    for label in model["labels"]:
        pieces = label.split(":")
        if label == "intercept":
            v = np.ones(len(frame))
        elif pieces[0] == "gate":
            v = frame.gate_side.eq(pieces[1]).to_numpy(float)
            if len(pieces) == 4:
                v *= frame[pieces[2]].astype(str).eq(pieces[3]).to_numpy(float)
        elif pieces[0] == "condition":
            v = frame[pieces[1]].astype(str).eq(pieces[2]).to_numpy(float)
        else:
            info = model["numeric_metadata"][pieces[1]]
            columns = [f"inner_{pieces[1]}", f"outer_{pieces[1]}"] if paired else [pieces[1]]
            arrays = [frame[c].to_numpy(float) for c in columns]
            if pieces[0] == "ability_missing":
                values = [(~np.isfinite(a)).astype(float) for a in arrays]
            else:
                values = [
                    (np.where(np.isfinite(a), a, info["median"]) - info["median"]) / info["scale"]
                    for a in arrays
                ]
            v = values[1] - values[0] if paired else values[0]
        vectors.append(v)
    return np.column_stack(vectors)


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for path, expected in summary["inputs_sha256"].items():
        assert digest(path) == expected, path
    runners = pd.read_parquet(STUDY.PREVIOUS / "outputs/runners.parquet")
    pairs = pd.read_parquet(STUDY.PREVIOUS / "outputs/pack_pairs.parquet")
    for frame in [runners, pairs]:
        frame["dt"] = pd.to_datetime(frame.date)
        frame["month"] = frame.dt.dt.month
    races = pd.read_parquet(OUT / "race_deviations.parquet")
    periods = pd.read_parquet(OUT / "periods.parquet")
    models = json.loads((OUT / "baseline_models.json").read_text())
    assert len(races) == summary["race_rows"]
    assert not races.duplicated(["meet", "point", "race_key"]).any()
    assert (races.baseline_trained_through < races.year).all()
    assert races.year.between(2020, 2026).all()
    np.testing.assert_allclose(races.deviation, races.ability_adjusted - races.expected, atol=1e-12)
    np.testing.assert_array_equal(races.weekday, races.dt.dt.dayofweek)
    np.testing.assert_array_equal(races.year_month, races.dt.dt.strftime("%Y-%m"))
    friday = pd.to_datetime(races.weekend_start)
    assert friday.dt.dayofweek.eq(4).all()
    assert ((races.dt - friday).dt.days == (races.weekday - 4) % 7).all()
    checked_rows, refits = 0, []
    for model in models:
        paired = model["point"] != "gate"
        source = pairs if paired else runners
        source = source[source.meet.eq(model["meet"])]
        if paired:
            source = source[source.point.eq(model["point"])]
        train = source[source.year.lt(model["year"])]
        test = source[source.year.eq(model["year"])]
        assert len(train) == model["train_rows"]
        assert train.year.max() == model["trained_through"] < model["year"]
        for key, info in model["numeric_metadata"].items():
            values = (
                np.concatenate([train[f"inner_{key}"], train[f"outer_{key}"]])
                if paired
                else train[key].to_numpy(float)
            )
            finite = values[np.isfinite(values)]
            median = np.median(finite) if len(finite) else 0
            scale = finite.std() if len(finite) and finite.std() > 1e-10 else 1
            np.testing.assert_allclose([median, scale], [info["median"], info["scale"]], atol=1e-12)
        x = matrix(test, model)
        beta = np.asarray(model["coefficients"])
        k = model["condition_columns"]
        rebuilt = test[["race_key", "distance_m"]].copy()
        rebuilt["ability"] = x[:, k:] @ beta[k:]
        rebuilt["expected"] = x[:, :k] @ beta[:k]
        if paired:
            rebuilt["raw"] = test.top3_difference
            rebuilt = rebuilt.groupby("race_key").agg(
                raw=("raw", "mean"),
                ability=("ability", "mean"),
                expected=("expected", "mean"),
                distance_m=("distance_m", "first"),
            )
        else:
            rebuilt["raw"] = test.top3
            rebuilt["side"] = test.gate_side
            cells = (
                rebuilt.groupby(["race_key", "side"])[["raw", "ability", "expected"]]
                .mean()
                .unstack()
            )
            rebuilt = pd.DataFrame(
                {
                    key: cells[key]["outer"] - cells[key]["inner"]
                    for key in ["raw", "ability", "expected"]
                }
            )
            rebuilt["distance_m"] = test.groupby("race_key").distance_m.first()
        saved = (
            races[
                races.meet.eq(model["meet"])
                & races.point.eq(model["point"])
                & races.year.eq(model["year"])
            ]
            .set_index("race_key")
            .loc[rebuilt.index]
        )
        np.testing.assert_allclose(rebuilt.raw, saved.raw, atol=1e-12)
        np.testing.assert_allclose(rebuilt.expected, saved.expected, atol=1e-10)
        np.testing.assert_allclose(
            rebuilt.raw - rebuilt.ability, saved.ability_adjusted, atol=1e-10
        )
        support = train.groupby("distance_m").agg(
            n=("race_key", "nunique"), days=("day_key", "nunique")
        )
        expected_support = support.n.ge(50) & support.days.ge(20)
        np.testing.assert_array_equal(
            rebuilt.distance_m.map(expected_support).fillna(False), saved.baseline_supported
        )
        checked_rows += len(saved)
        if model["year"] == 2026 and model["point"] in ["gate", "3C", "G3F"]:
            xt = matrix(train, model)
            y = (
                train.top3_difference.to_numpy(float)
                if paired
                else train.top3.to_numpy(float, copy=True)
            )
            counts = train.groupby("race_key").race_key.transform("size").to_numpy()
            if not paired:
                xt = (
                    pd.DataFrame(xt, index=train.index)
                    - pd.DataFrame(xt, index=train.index).groupby(train.race_key).transform("mean")
                ).to_numpy()
                y = y - train.groupby("race_key").top3.transform("mean").to_numpy()
            sw = np.sqrt(1 / counts)
            independent, _, _, _ = np.linalg.lstsq(xt * sw[:, None], y * sw, rcond=1e-5)
            np.testing.assert_allclose(x @ independent, x @ beta, atol=1e-8, rtol=0)
            refits.append({"meet": model["meet"], "point": model["point"], "year": 2026})
    assert checked_rows == len(races)
    for window in ["date", "weekend", "month"]:
        sample = races[
            races.baseline_supported & (races.weekday.ge(4) if window == "weekend" else True)
        ].copy()
        sample["period"] = sample[
            {"date": "date", "weekend": "weekend_start", "month": "year_month"}[window]
        ]
        for exact in [False, True]:
            keys = ["meet", "point", "period"] + (["distance_m"] if exact else [])
            grouped = sample.groupby(keys)
            means = grouped[STUDY.METRICS].mean() * 100
            counts = grouped.agg(races=("race_key", "size"), days=("day_key", "nunique"))
            saved = periods[
                periods.window.eq(window)
                & (periods.distance_m.notna() if exact else periods.distance_m.isna())
            ].set_index(keys)
            means, counts = means.loc[saved.index], counts.loc[saved.index]
            np.testing.assert_allclose(saved[[f"{m}_pp" for m in STUDY.METRICS]], means, atol=1e-10)
            np.testing.assert_array_equal(saved[["races", "days"]], counts)
            minimum = (
                {"date": 3, "weekend": 4, "month": 12}[window]
                if exact
                else {"date": 5, "weekend": 10, "month": 40}[window]
            )
            np.testing.assert_array_equal(
                saved.supported,
                counts.races.ge(minimum)
                & counts.days.ge({"date": 1, "weekend": 2, "month": 6}[window]),
            )
        if window == "month":
            for row in periods[periods.window.eq("month")].itertuples():
                one = sample[
                    sample.meet.eq(row.meet)
                    & sample.point.eq(row.point)
                    & sample.period.eq(row.period)
                ]
                if pd.notna(row.distance_m):
                    one = one[one.distance_m.eq(row.distance_m)]
                if row.days < 2:
                    assert row.ci95_pp is None and pd.isna(row.p)
                    continue
                scores = (
                    one.groupby("day_key").deviation.sum()
                    - one.groupby("day_key").size() * one.deviation.mean()
                )
                se = np.sqrt(np.dot(scores, scores) * row.days / (row.days - 1)) / row.races
                ci = row.deviation_pp + np.array([-1, 1]) * t.ppf(0.975, row.days - 1) * se * 100
                p = 2 * t.sf(abs(row.deviation_pp / (se * 100)), row.days - 1) if se > 1e-14 else 1
                np.testing.assert_allclose(ci, row.ci95_pp, atol=1e-9)
                assert abs(p - row.p) < 1e-10
    np.testing.assert_allclose(
        periods.shrink_weight, periods.races / (periods.races + 40), atol=1e-12
    )
    np.testing.assert_allclose(
        periods.shrunk_deviation_pp, periods.deviation_pp * periods.shrink_weight, atol=1e-12
    )
    assert periods[periods.window.eq("weekend")].ci95_pp.isna().all()
    assert periods[periods.window.ne("month")].p.isna().all()
    families = {}
    for gate in [True, False]:
        family = periods[
            periods.window.eq("month")
            & periods.distance_m.isna()
            & periods.supported
            & periods.point.eq("gate").eq(gate)
        ]
        np.testing.assert_allclose(family.q_month, bh(family.p), atol=1e-12)
        families["gate" if gate else "lateral"] = {
            "comparisons": len(family),
            "q_below_05": int(family.q_month.lt(0.05).sum()),
        }
    phase = pd.read_csv(OUT / "day_phases.csv")
    eligible = races[races.baseline_supported].copy()
    eligible["phase"] = pd.cut(
        eligible.race_no, [0, 3, 6, np.inf], labels=["early", "middle", "late"]
    )
    rebuilt = eligible.groupby(["meet", "point", "date", "phase"], observed=True).agg(
        races=("race_key", "size"),
        ability_adjusted=("ability_adjusted", "mean"),
        expected=("expected", "mean"),
        deviation=("deviation", "mean"),
    )
    saved = phase.set_index(["meet", "point", "date", "phase"]).loc[rebuilt.index]
    np.testing.assert_allclose(saved, rebuilt, atol=1e-10)
    # Reproduce the complete permutation output with the saved seed and BH family.
    permutation = STUDY.monthly_permutation(races, periods)
    for a, b in zip(permutation, summary["monthly_permutation"], strict=True):
        assert a.keys() == b.keys()
        for key in a:
            assert (
                a[key] == b[key]
                if isinstance(a[key], str)
                else np.isclose(a[key], b[key], atol=1e-12)
            )
    result = {
        "status": "passed",
        "input_hashes_unchanged": True,
        "frozen_models_checked": len(models),
        "race_decompositions_checked": checked_rows,
        "independent_2026_solver_refits": refits,
        "period_rows_checked": len(periods),
        "monthly_bh_families": families,
        "calendar_and_support_rules": True,
        "month_cluster_ci_and_p": True,
        "phase_aggregates": True,
        "permutation_reproduced": True,
        "verification_sha256": digest(__file__),
    }
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
