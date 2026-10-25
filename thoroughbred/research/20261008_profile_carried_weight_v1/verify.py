"""Independently reconstruct historical weights and all saved test distributions."""

import importlib.util
import itertools
import json
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp, softmax
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("weight_ablation", HERE / "run.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def main():
    R.check_inputs()
    c = R.config()
    source = pd.read_parquet(R.OUT / "weight_source.parquet")
    history = pd.read_parquet(R.OUT / "weight_history.parquet")
    weights = pd.read_parquet(R.OUT / "weight_inputs.parquet")
    base = pd.read_parquet(R.source_frames()["profile19"])
    predictions = pd.read_parquet(R.OUT / "runner_predictions.parquet")
    races = pd.read_csv(R.OUT / "race_metrics.csv", low_memory=False)
    tickets = pd.read_parquet(R.OUT / "recommendations.parquet")
    contracts = json.loads((R.OUT / "feature_contract.json").read_text())
    checks, max_error = 0, 0.0

    def compare(a, b, label):
        nonlocal checks, max_error
        a, b = np.asarray(a, float), np.asarray(b, float)
        assert np.allclose(a, b, equal_nan=True, atol=1e-10, rtol=0), label
        known = np.isfinite(a) & np.isfinite(b)
        if known.any():
            max_error = max(max_error, float(abs(a[known] - b[known]).max()))
        checks += a.size

    assert weights[R.KEY].equals(base[R.KEY])
    assert not source.duplicated(R.KEY).any()
    assert len(history) == 326327
    current = base[R.KEY].merge(
        source[R.KEY + ["current_carried_weight"]], on=R.KEY, validate="one_to_one"
    )
    compare(weights.current_carried_weight, current.current_carried_weight, "current_source_keys")
    compare(
        weights.current_vs_previous_carried_weight,
        weights.current_carried_weight - weights.previous_carried_weight,
        "change_definition",
    )
    assert weights.current_carried_weight.between(40, 70).all()
    missing = base.history_count.eq(0)
    assert weights.loc[missing, "previous_carried_weight"].isna().all()
    assert weights.loc[missing, "current_vs_previous_carried_weight"].isna().all()
    assert weights.loc[missing, "current_carried_weight"].notna().all()
    # Separate searchsorted implementation over the exact starter history; does
    # not bridge a missing time/weight or use result-date observations from T-1.
    expected = np.full(len(base), np.nan)
    expected_date = np.full(len(base), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    groups = {
        horse: g.sort_values("race_date") for horse, g in history.groupby("horse_id", sort=False)
    }
    for horse, ids in base.groupby("horse_id", sort=False).indices.items():
        h = groups.get(horse)
        if h is None:
            continue
        days = h.race_date.to_numpy(dtype="datetime64[ns]")
        target = base.race_date.iloc[ids].to_numpy(dtype="datetime64[ns]") - np.timedelta64(2, "D")
        positions = np.searchsorted(days, target, side="right") - 1
        valid = positions >= 0
        expected[ids[valid]] = h.current_carried_weight.to_numpy(float)[positions[valid]]
        expected_date[ids[valid]] = days[positions[valid]]
    compare(weights.previous_carried_weight, expected, "direct_previous_weight_all_rows")
    assert pd.Series(expected_date).equals(weights.weight_source_date.astype("datetime64[ns]"))
    assert (
        weights.weight_source_date.isna() | weights.weight_source_date.le(base.cutoff_date)
    ).all()
    # Check source parsing with independently selected raw DB rows, not a second
    # call to the extraction helper. The connection cannot write to the database.
    with duckdb.connect(str(R.DB), read_only=True) as connection:
        for row in source.sample(n=24, random_state=20261008).itertuples():
            raw = connection.execute(
                """
                SELECT carried_weight_raw FROM confirmed_runners
                WHERE source_meet=? AND result_date=? AND result_race_no=?
                  AND horse_program_no_raw=? AND horse_id_raw=?
            """,
                [
                    str(row.meet),
                    row.race_date.strftime("%Y%m%d"),
                    str(row.race_no),
                    str(row.program_no),
                    row.horse_id,
                ],
            ).fetchall()
            assert len(raw) == 1
            compare([row.current_carried_weight], [float(raw[0][0])], "raw_database_weight")
    temperatures, heads = [], 0
    for baseline, variant in c["pairs"]:
        original = pd.read_parquet(R.source_frames()[baseline])
        f = pd.read_parquet(R.OUT / f"features_{variant}.parquet")
        assert f[original.columns].equals(original), "Existing frame changed"
        assert contracts[baseline] == R.BASE and contracts[variant] == R.COLS
        assert len(R.COLS) == len(set(R.COLS)) == 22
        assert not any("jockey" in column for column in R.COLS)
        compare(f[R.WEIGHT], weights[R.WEIGHT], "same_weight_bundle")
        prior = predictions[predictions.variant.eq(baseline)].sort_values(R.KEY)
        pred = predictions[predictions.variant.eq(variant)].sort_values(R.KEY)
        assert (
            pred[R.KEY + ["outcome"]]
            .reset_index(drop=True)
            .equals(prior[R.KEY + ["outcome"]].reset_index(drop=True))
        )
        rr = races[races.variant.eq(variant)]
        rb = races[races.variant.eq(baseline)]
        assert len(rr) == len(rb) == 4799
        assert sorted(rr.race_key) == sorted(rb.race_key)
        assert len(pred) == 50754
        assert tickets[tickets.variant.eq(variant)].groupby("race_key").size().eq(6).all()
        race_index = rr.set_index("race_key")
        ticket_index = tickets[tickets.variant.eq(variant)].set_index(
            ["race_key", "selection_rank"]
        )
        for meet in c["venues"]:
            one = f[f.meet.eq(meet)].reset_index(drop=True)
            for year in c["evaluation_years"]:
                directory = R.OUT / "models" / f"{meet}_{year}_{variant}"
                meta = json.loads((directory / "metadata.json").read_text())
                assert meta["features"] == R.COLS
                assert pd.Timestamp(meta["train_end"]).year == year - 2
                assert meta["validation_year"] == year - 2
                assert meta["calibration_year"] == year - 1
                assert R.sha(directory / "top3.txt") == meta["model_sha256"]
                model = lgb.Booster(model_file=str(directory / "top3.txt"))
                assert model.feature_name() == R.COLS and model.num_trees() == meta["trees"]
                x = one[R.COLS].copy()
                for column, vocabulary in meta["category_vocabulary"].items():
                    x[column] = pd.Categorical(x[column], categories=vocabulary)
                    assert vocabulary == sorted(
                        one.loc[one.year.between(2017, year - 3), column].dropna().unique().tolist()
                    )
                test = one.year.eq(year)
                frame = one[test].reset_index(drop=True)
                score = model.predict(x[test], raw_score=True, num_threads=4)
                saved = frame[R.KEY].merge(pred, on=R.KEY, validate="one_to_one")
                compare(score, saved.raw_top3_score, "saved_head_replay")
                cal = one.year.eq(year - 1)
                calibration = one[cal].reset_index(drop=True)
                cs = model.predict(x[cal], raw_score=True, num_threads=4)
                temperature = meta["temperature"]
                gradients = []
                for _, ids in calibration.groupby("race_key", sort=False).indices.items():
                    g = calibration.iloc[ids]
                    triples = np.array(list(itertools.combinations(range(len(g)), 3)))
                    energy = np.sort(cs[ids][triples], axis=1).sum(axis=1)
                    truth = np.flatnonzero(g.outcome.le(3).to_numpy())
                    gradients.append(
                        (np.sort(cs[ids][truth]).sum() - softmax(energy / temperature) @ energy)
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
                for race_key, ids in frame.groupby("race_key", sort=False).indices.items():
                    g = frame.iloc[ids]
                    assert g.program_no.is_monotonic_increasing
                    triples = np.array(list(itertools.combinations(range(len(g)), 3)))
                    energy = np.sort(score[ids][triples], axis=1).sum(axis=1) / temperature
                    probability = softmax(energy)
                    marginal = np.bincount(
                        triples.flatten(), weights=np.repeat(probability, 3), minlength=len(g)
                    )
                    compare(marginal, saved.prob_top3.iloc[ids], "marginal_probabilities")
                    compare([probability.sum(), marginal.sum()], [1, 3], "probability_sums")
                    selected = np.argsort(-probability, kind="stable")[:6]
                    order = np.argsort(-score[ids], kind="stable")
                    truth = set(np.flatnonzero(g.outcome.le(3).to_numpy()))
                    target = next(i for i, t in enumerate(triples) if set(t) == truth)
                    actual = race_index.loc[race_key]
                    desired = [
                        int(target in selected),
                        float(logsumexp(energy) - energy[target]),
                        float(np.mean((marginal - g.outcome.le(3).to_numpy()) ** 2)),
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
                        compare([ticket.probability], [probability[i]], "six_tickets")
                heads += 1
    summary = pd.read_csv(R.OUT / "metrics.csv")
    for row in summary.itertuples():
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
    differences = json.loads((R.OUT / "paired_differences.json").read_text())
    lookup = {(r["meet"], r["base"], r["candidate"], r["metric"]): r for r in differences}
    rng = np.random.default_rng(c["bootstrap_seed"])
    bootstrap_checks = 0
    for meet in [0, 1, 3]:
        s = races if not meet else races[races.meet.eq(meet)]
        for baseline, variant in c["pairs"]:
            a = s[s.variant.eq(baseline)].set_index("race_key")
            b = s[s.variant.eq(variant)].set_index("race_key").loc[a.index]
            for metric in ["trio6_hit", "trio_nll", "top3_brier", "top5_contains_podium"]:
                delta = b[metric] - a[metric]
                day = (
                    pd.DataFrame({"date": a.race_date, "delta": delta})
                    .groupby("date")
                    .delta.agg(["sum", "size"])
                    .to_numpy()
                )
                samples = day[rng.integers(len(day), size=(c["bootstrap_draws"], len(day)))].sum(
                    axis=1
                )
                interval = np.quantile(samples[:, 0] / samples[:, 1], [0.025, 0.975])
                saved = lookup[meet, baseline, variant, metric]
                compare(interval, saved["date_bootstrap_95"], "paired_date_bootstrap")
                compare([delta.mean()], [saved["difference"]], "paired_difference")
                bootstrap_checks += 1
    R.check_inputs()
    result = dict(
        passed=True,
        numeric_comparisons=checks,
        max_absolute_error=max_error,
        baseline_feature_rows_preserved=178497,
        previous_weight_reconstructed_rows=178497,
        replayed_heads=heads,
        candidate_evaluation_races=2 * 4799,
        bootstrap_comparisons=bootstrap_checks,
        temperature_checks=temperatures,
        source_hashes_unchanged=True,
        production_changed=False,
        current_weight_pit_verified=False,
    )
    R.save(R.OUT / "verification.json", result)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "temperature_checks"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    with threadpool_limits(limits=1):
        main()
