"""Replay frozen inputs, chronological transforms and every saved model/distribution."""

import importlib.util
import itertools
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp, softmax
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("environment_ablation", HERE / "run.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def main():
    R.check_inputs()
    c = R.config()
    original = pd.read_parquet(R.B.RECORDS)
    records = pd.read_parquet(R.OUT / "record_components.parquet")
    baseline = pd.read_parquet(R.B.HERE / "outputs/features.parquet")
    predictions = pd.read_parquet(R.OUT / "runner_predictions.parquet")
    races = pd.read_csv(R.OUT / "race_metrics.csv", low_memory=False)
    tickets = pd.read_parquet(R.OUT / "recommendations.parquet")
    checks, max_error = 0, 0.0

    def compare(a, b, label, tolerance=1e-10):
        nonlocal checks, max_error
        a, b = np.asarray(a, float), np.asarray(b, float)
        assert np.allclose(a, b, equal_nan=True, atol=tolerance, rtol=0), label
        known = np.isfinite(a) & np.isfinite(b)
        if known.any():
            max_error = max(max_error, float(abs(a[known] - b[known]).max()))
        checks += a.size

    assert records[R.KEY].equals(original[R.KEY])
    for column in original.columns:
        assert records[column].equals(original[column]), column
    assert records.month_add_seconds.abs().max() <= 0.3 + 1e-12
    assert records.gate_add_seconds.abs().max() <= 0.2 + 1e-12
    nonzero = records.month_add_seconds.ne(0) | records.gate_add_seconds.ne(0)
    assert records.loc[nonzero, "supported"].all()
    assert records.loc[nonzero, "original_finish_valid"].notna().all()
    assert (
        records.loc[nonzero, "coefficient_source_max"]
        <= records.loc[nonzero, "race_date"] - pd.Timedelta(days=2)
    ).all()
    assert not nonzero[records.year.lt(2020)].any()
    population = R.population()
    model_count = 0
    for year in c["coefficient_years"]:
        dest = R.OUT / "coefficients" / str(year)
        complete = json.loads((dest / "complete.json").read_text())
        for name, expected in complete["hashes"].items():
            assert R.sha(dest / name) == expected
        masks = pd.read_parquet(dest / "outlier_masks.parquet")
        dates = masks[["row_key"]].merge(population[["row_key", "date"]], validate="one_to_one")
        assert dates.date.dt.year.lt(year).all()
        assert not masks.row_key.duplicated().any()
        models = json.loads((dest / "models.json").read_text())
        for model in models:
            assert max(model["source_years"]) < year
            assert pd.Timestamp(model["source_max"]).year < year
            assert model["coefficient_year"] == year
        model_count += len(models)
        month = pd.read_parquet(dest / "month_candidates.parquet")
        effects = pd.read_parquet(dest / "month_effects.parquet")
        lookup = effects.set_index(["meet", "distance_m", "kind", "block", "level", "period"])
        for row in month.itertuples():
            key = (row.meet, row.distance_m, row.kind, row.block, row.level)
            pieces = [
                lookup.loc[(*key, p)] if (*key, p) in lookup.index else None for p in R.N.PERIODS
            ]
            supported = all(p is not None and p.supported for p in pieces)
            signs = [np.sign(p.effect_seconds) for p in pieces if p is not None]
            stable = len(signs) == 5 and len(set(signs)) == 1 and signs[0] != 0
            primary, recent = pieces[1], pieces[3]
            sig = (
                primary is not None and recent is not None and primary.q < 0.05 and recent.q < 0.05
            )
            amount = 0.0
            if supported and stable and sig:
                nearest = min(
                    min(abs(p.ci_low), abs(p.ci_high)) if p.ci_low * p.ci_high > 0 else 0
                    for p in [primary, recent]
                )
                amount = -signs[0] * np.floor((min(0.3, 0.5 * nearest) + 1e-12) * 100) / 100
            compare([row.candidate_add_seconds], [amount], "monthly_policy")
        gate = pd.read_parquet(dest / "gate_candidates.parquet")
        for _, g in gate.groupby(
            ["meet", "distance_m", "field_size", "mode", "band"], observed=True
        ):
            weights = g.group_weight.to_numpy(float)
            for prefix, fraction, cap in [("base", 0.3, 0.15), ("state", 0.15, 0.05)]:
                n = g[prefix + "_n"].to_numpy(float)
                if prefix == "base":
                    raw = (
                        g.raw_base_effect.fillna(0).to_numpy(float)
                        if g.base_available.all()
                        else np.zeros(len(g))
                    )
                else:
                    raw = (
                        (g.raw_state_effect - g.raw_base_effect).fillna(0).to_numpy(float)
                        if g.state_available.all()
                        else np.zeros(len(g))
                    )
                amount = fraction * n / (n + 100) * raw
                amount -= np.average(amount, weights=weights)
                amount *= min(1, cap / max(abs(amount).max(), 1e-15))
                compare(g[prefix + "_add_seconds"], -amount, "gate_policy")
                assert abs(np.average(g[prefix + "_add_seconds"], weights=weights)) < 1e-12
            compare(g.gate_add_seconds, g.base_add_seconds + g.state_add_seconds, "gate_total")
    # Independent crop/refit of one complete historical cell catches accidental
    # use of the original full-2026 estimates or original full-period outlier masks.
    year, meet, dist = 2024, "서울", 1200
    past = population[
        population.year.lt(year) & population.meet.eq(meet) & population.distance_m.eq(dist)
    ].reset_index(drop=True)
    fitted, _, residual = R.N.fit(past, dict(meet=meet, distance_m=dist, period="all_raw"))
    saved = pd.read_parquet(R.OUT / "coefficients/2024/month_effects.parquet")
    keys = ["meet", "distance_m", "kind", "block", "level", "period"]
    aligned = pd.DataFrame(fitted).merge(
        saved, on=keys, validate="one_to_one", suffixes=("_a", "_b")
    )
    for column in ["effect_seconds", "se"]:
        compare(aligned[column + "_a"], aligned[column + "_b"], "historical_month_refit")
    mad, _, _, _ = R.N.mask_outliers(past, residual)
    saved_mask = pd.read_parquet(R.OUT / "coefficients/2024/outlier_masks.parquet").set_index(
        "row_key"
    )
    assert np.array_equal(mad.to_numpy(), saved_mask.loc[past.row_key, "mad4_keep"].to_numpy())
    sample = past[mad].reset_index(drop=True)
    for family, function, meta in [
        (
            "base",
            R.L.fit,
            dict(
                kind="gate",
                meet=meet,
                distance_m=dist,
                point="start",
                period="all_mad4",
                adjustment="dual",
            ),
        ),
        ("state", R.A.fit, dict(meet=meet, distance_m=dist, period="all_mad4", adjustment="dual")),
    ]:
        fitted, _ = function(sample, meta, {})
        saved = pd.read_parquet(R.OUT / f"coefficients/2024/{family}_effects.parquet")
        keys = ["meet", "distance_m", "family", "block", "level", "period"] + (
            ["band"] if family == "state" else []
        )
        aligned = pd.DataFrame(fitted).merge(
            saved, on=keys, validate="one_to_one", suffixes=("_a", "_b")
        )
        for column in ["effect_seconds", "se"]:
            compare(aligned[column + "_a"], aligned[column + "_b"], "historical_gate_refit")
    neutral, _ = R.record_indices(records, "profile19")
    compare(neutral.candidate_index, original.record_index, "neutral_record_index")
    compare(
        R.profile_frame(neutral, baseline)[R.DERIVED], baseline[R.DERIVED], "neutral_all_features"
    )
    baseline_races = races[races.variant.eq("profile19")].sort_values("race_key")
    baseline_runners = predictions[predictions.variant.eq("profile19")].sort_values(R.KEY)
    temperatures = []
    for variant in c["variants"]:
        f = pd.read_parquet(R.OUT / f"features_{variant}.parquet")
        assert f[R.KEY + R.B.BASE + ["outcome", "cutoff_date"]].equals(
            baseline[R.KEY + R.B.BASE + ["outcome", "cutoff_date"]]
        )
        assert (f.candidate_source_date.isna() | f.candidate_source_date.le(f.cutoff_date)).all()
        r = pd.read_parquet(R.OUT / f"records_{variant}.parquet")
        assert r[R.KEY].equals(original[R.KEY])
        expected = records.finish_valid.copy()
        if variant in ["month19", "month_gate19"]:
            expected += records.month_add_seconds
        if variant in ["gate19", "month_gate19"]:
            expected += records.gate_add_seconds
        compare(r.candidate_finish, expected, "component_seconds")
        history = pd.concat([records[["horse_id", "race_date"]], r[["candidate_index"]]], axis=1)
        groups = {
            horse: g.sort_values("race_date")
            for horse, g in history.groupby("horse_id", sort=False)
        }
        # Direct, non-rolling implementation on 600 stratified actual targets.
        for (_, _), stratum in f[f.year.isin(c["evaluation_years"])].groupby(["meet", "year"]):
            sampled = stratum.sample(n=min(100, len(stratum)), random_state=20261008)
            for row in sampled.itertuples():
                h = groups.get(row.horse_id)
                if h is None:
                    continue
                h = h[h.race_date.le(row.cutoff_date)]
                if not len(h):
                    continue
                q = h.candidate_index.to_numpy(float)
                a, b = q[-3:], q[-6:-3]
                valid3, prev3 = a[np.isfinite(a)], b[np.isfinite(b)]
                five = q[-5:]
                valid5 = five[np.isfinite(five)]
                actual = [
                    row.moist_last_record_index,
                    row.moist_last3_record_index_mean,
                    row.moist_last5_record_index_best,
                    row.moist_last5_record_index_count,
                    row.profile_top2mean5,
                    row.profile_previous3,
                    row.profile_trend,
                    row.profile_std5,
                    row.profile_count3,
                    row.profile_previous3_count,
                ]
                desired = [
                    q[-1],
                    valid3.mean() if len(valid3) else np.nan,
                    valid5.max() if len(valid5) else np.nan,
                    len(valid5),
                    np.sort(valid5)[-2:].mean() if len(valid5) >= 2 else np.nan,
                    prev3.mean() if len(prev3) else np.nan,
                    valid3.mean() - prev3.mean()
                    if len(valid3) >= 2 and len(prev3) >= 2
                    else np.nan,
                    valid5.std(ddof=1) if len(valid5) >= 3 else np.nan,
                    len(valid3),
                    len(prev3),
                ]
                compare(actual, desired, "direct_historical_window")
        pred = predictions[predictions.variant.eq(variant)].sort_values(R.KEY)
        assert (
            pred[R.KEY + ["outcome"]]
            .reset_index(drop=True)
            .equals(baseline_runners[R.KEY + ["outcome"]].reset_index(drop=True))
        )
        rr = races[races.variant.eq(variant)].sort_values("race_key")
        assert rr.race_key.tolist() == baseline_races.race_key.tolist() and len(rr) == 4799
        assert tickets[tickets.variant.eq(variant)].groupby("race_key").size().eq(6).all()
        for meet in [1, 3]:
            one = f[f.meet.eq(meet)].reset_index(drop=True)
            for year in c["evaluation_years"]:
                directory = R.OUT / "models" / f"{meet}_{year}_{variant}"
                meta = json.loads((directory / "metadata.json").read_text())
                assert meta["features"] == R.COLS and len(meta["features"]) == 19
                assert pd.Timestamp(meta["train_end"]).year == year - 2
                assert meta["validation_year"] == year - 2 and meta["calibration_year"] == year - 1
                assert R.sha(directory / "top3.txt") == meta["model_sha256"]
                model = lgb.Booster(model_file=str(directory / "top3.txt"))
                assert model.feature_name() == R.COLS and model.num_trees() == meta["trees"]
                x = one[R.COLS].copy()
                for col, vocabulary in meta["category_vocabulary"].items():
                    x[col] = pd.Categorical(x[col], categories=vocabulary)
                    assert vocabulary == sorted(
                        one.loc[one.year.between(2017, year - 3), col].dropna().unique().tolist()
                    )
                test = one.year.eq(year)
                test_frame = one[test].reset_index(drop=True)
                score = model.predict(x[test], raw_score=True, num_threads=4)
                saved = test_frame[R.KEY].merge(pred, on=R.KEY, validate="one_to_one")
                compare(score, saved.raw_top3_score, "model_replay")
                calibration = one.year.eq(year - 1)
                cal_score = model.predict(x[calibration], raw_score=True, num_threads=4)
                cal_frame = one[calibration].reset_index(drop=True)
                gradients = []
                temperature = meta["temperature"]
                for _, idx in cal_frame.groupby("race_key", sort=False).indices.items():
                    g = cal_frame.iloc[idx]
                    triples = np.array(list(itertools.combinations(range(len(g)), 3)))
                    energy = np.sort(cal_score[idx][triples], axis=1).sum(axis=1)
                    truth = np.flatnonzero(g.outcome.le(3).to_numpy())
                    gradients.append(
                        (
                            np.sort(cal_score[idx][truth]).sum()
                            - softmax(energy / temperature) @ energy
                        )
                        / temperature**2
                    )
                gradient = float(np.mean(gradients))
                if 0.3501 < temperature < 3.9999:
                    assert abs(gradient) < 1e-5
                elif temperature <= 0.3501:
                    assert gradient >= -1e-5
                else:
                    assert gradient <= 1e-5
                temperatures.append(
                    dict(
                        variant=variant,
                        meet=meet,
                        year=year,
                        temperature=temperature,
                        gradient=gradient,
                    )
                )
                race_index = rr.set_index("race_key")
                ticket_index = tickets[tickets.variant.eq(variant)].set_index(
                    ["race_key", "selection_rank"]
                )
                for race_key, ids in test_frame.groupby("race_key", sort=False).indices.items():
                    g = test_frame.iloc[ids]
                    assert g.program_no.is_monotonic_increasing
                    triples = np.array(list(itertools.combinations(range(len(g)), 3)))
                    energy = np.sort(score[ids][triples], axis=1).sum(axis=1) / temperature
                    probabilities = softmax(energy)
                    marginals = np.bincount(
                        triples.flatten(), weights=np.repeat(probabilities, 3), minlength=len(g)
                    )
                    compare(marginals, saved.prob_top3.iloc[ids], "marginal_probabilities")
                    compare([marginals.sum(), probabilities.sum()], [3, 1], "probability_sums")
                    selected = np.argsort(-probabilities, kind="stable")[:6]
                    order = np.argsort(-score[ids], kind="stable")
                    truth = set(np.flatnonzero(g.outcome.le(3).to_numpy()))
                    target = next(i for i, t in enumerate(triples) if set(t) == truth)
                    actual = race_index.loc[race_key]
                    desired = [
                        int(target in selected),
                        float(logsumexp(energy) - energy[target]),
                        float(np.mean((marginals - g.outcome.le(3).to_numpy()) ** 2)),
                        int(truth <= set(order[:5])),
                    ]
                    compare(
                        actual[["trio6_hit", "trio_nll", "top3_brier", "top5_contains_podium"]],
                        desired,
                        "race_metrics",
                    )
                    for rank, i in enumerate(selected, 1):
                        ticket = ticket_index.loc[(race_key, rank)]
                        assert ticket.programs == ",".join(
                            map(str, sorted(g.program_no.iloc[triples[i]].astype(int)))
                        )
                        assert ticket.hit == int(i == target)
                        compare([ticket.probability], [probabilities[i]], "ticket_probability")
    metrics = pd.read_csv(R.OUT / "metrics.csv")
    for row in metrics.itertuples():
        s = races[races.variant.eq(row.variant)]
        if row.meet:
            s = s[s.meet.eq(row.meet)]
        if row.period != "all":
            s = s[s.evaluation_year.eq(int(row.period))]
        assert row.races == len(s) and row.hits == s.trio6_hit.sum()
        compare(
            [row.trio6_hit, row.trio_nll, row.top3_brier, row.top5_contains_podium],
            [
                s.trio6_hit.mean(),
                s.trio_nll.mean(),
                s.top3_brier.mean(),
                s.top5_contains_podium.mean(),
            ],
            "aggregate_metrics",
        )
    R.check_inputs()
    result = dict(
        passed=True,
        numeric_comparisons=checks,
        max_absolute_error=max_error,
        chronological_environment_models=model_count,
        replayed_heads=18,
        candidate_evaluation_races=3 * 4799,
        baseline_neutral_rows=len(baseline),
        historical_refit="2024 서울1200 whole prior + fresh MAD + gate base/state",
        temperatures=temperatures,
        source_hashes_unchanged=True,
        production_changed=False,
    )
    R.save(R.OUT / "verification.json", result)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "temperatures"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    with threadpool_limits(limits=1):
        main()
