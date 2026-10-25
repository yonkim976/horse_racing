"""Independent chronology, runner/rank, saved-model and paired-date checks."""

import itertools
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import run as experiment
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"


def main():
    experiment.check_inputs()
    f = pd.read_parquet(OUT / "stack_features.parquet")
    original = pd.read_parquet(experiment.W / "features_month_gate_weight22.parquet")
    assert f[experiment.BASE].equals(original[experiment.BASE])
    assert f[experiment.KEY + ["outcome", "race_date"]].equals(
        original[experiment.KEY + ["outcome", "race_date"]]
    )
    assert len(f) == 178497
    contracts = json.loads((OUT / "stack_feature_contract.json").read_text())
    excluded = {
        "outcome",
        "race_date",
        "aux_early",
        "aux_recovery",
        "aux_fade",
        "horse_id",
        "race_key",
    }
    for cols in contracts.values():
        assert not excluded.intersection(cols)
        assert not any("jockey" in c or "trainer" in c for c in cols)
    h = pd.read_parquet(OUT / "history_observations.parquet")
    ix = np.load(OUT / "history_slots.npy", allow_pickle=False)
    checks = 0
    dates = h.race_date.to_numpy("datetime64[D]")
    now = f.race_date.to_numpy("datetime64[D]")
    cutoff = f.cutoff_date.to_numpy("datetime64[D]")
    for j in range(5):
        ok = ix[:, j] >= 0
        assert (dates[ix[ok, j]] <= cutoff[ok]).all()
        assert (
            ((now[ok] - dates[ix[ok, j]]).astype(int) >= 2)
            & ((now[ok] - dates[ix[ok, j]]).astype(int) <= 730)
        ).all()
        assert (h.horse_id.to_numpy()[ix[ok, j]] == f.horse_id.to_numpy()[ok]).all()
        checks += int(ok.sum()) * 4
    # Rebuild actual-slot order by explicit horse/date filtering rather than searchsorted.
    rng = np.random.default_rng(20261009)
    sample = np.unique(
        np.r_[
            rng.choice(len(f), 2000, replace=False),
            np.flatnonzero(f.year.eq(2017))[:50],
            np.flatnonzero(f.history_count.eq(0))[:50],
        ]
    )
    by_horse = {horse: g for horse, g in h.groupby("horse_id", sort=False)}
    for row in sample:
        q = f.iloc[row]
        g = by_horse.get(q.horse_id)
        actual = [] if g is None else g[g.race_date.le(q.cutoff_date)].tail(5).index[::-1].tolist()
        actual = [x if (q.race_date - h.race_date.iloc[x]).days <= 730 else -1 for x in actual]
        actual = np.array(actual + [-1] * (5 - len(actual)), int)
        assert np.array_equal(actual, ix[row])
        for part in experiment.PARTS:
            v = np.array([h.iloc[j][part] if j >= 0 else np.nan for j in actual], float)
            known = np.isfinite(v)
            expected = [
                v[0],
                np.nanmean(v[:3]) if np.isfinite(v[:3]).any() else np.nan,
                np.nanmin(v) if known.any() else np.nan,
                float(known.sum()),
            ]
            cols = ["raw_section_" + part + "_" + x for x in ["last", "mean3", "best5", "n5"]]
            assert np.allclose(
                f.loc[row, cols].to_numpy(float), expected, equal_nan=True, atol=1e-12
            )
            checks += 4
        valid = np.array([h.role.iloc[j] if j >= 0 else np.nan for j in actual], float)
        for j in range(4):
            expected = (
                float((valid[np.isfinite(valid)] == j).mean())
                if np.isfinite(valid).any()
                else np.nan
            )
            assert np.allclose(
                f.loc[row, "style_role" + str(j) + "_rate5"], expected, equal_nan=True
            )
            checks += 1
    # Self-excluded field aggregates, using explicit peers.
    for _, g in f[f.year.eq(2026)].groupby("race_key"):
        for row in g.itertuples():
            peers = g[g.program_no.ne(row.program_no)]
            for c in [
                "section_early_mean3",
                "section_last600_mean3",
                "section_late_mean3",
                "style_role0_rate5",
                "style_recovery_mean5",
            ]:
                expected = peers[c].mean()
                assert np.allclose(
                    getattr(row, "field_other_" + c), expected, equal_nan=True, atol=1e-12
                )
                assert np.allclose(
                    getattr(row, "field_support_" + c),
                    peers[c].notna().sum() / (len(g) - 1),
                    atol=1e-12,
                )
                checks += 2
            value = row.section_early_mean3
            expected = (
                float((peers.section_early_mean3 < value).sum()) if np.isfinite(value) else np.nan
            )
            assert np.allclose(row.field_faster_early_n, expected, equal_nan=True)
            checks += 1
    # The current outcome is absent from every feature construction path.
    changed = f.iloc[sample].copy().reset_index(drop=True)
    changed["outcome"] = -999
    hist1 = experiment.historical_features(
        f.iloc[sample].reset_index(drop=True), h, ix[sample], True
    )
    hist2 = experiment.historical_features(changed, h, ix[sample], True)
    assert hist1.equals(hist2)
    environment_models = 0
    for folder in sorted((OUT / "environment").iterdir()):
        year = int(folder.name)
        complete = json.loads((folder / "complete.json").read_text())
        assert pd.Timestamp(complete["source_max"]).year < year
        for model in json.loads((folder / "models.json").read_text()):
            assert pd.Timestamp(model["source_max"]).year < year
            environment_models += 1
        for name, expected in complete["hashes"].items():
            assert experiment.sha(folder / name) == expected
        month = pd.read_parquet(folder / "months.parquet")
        for (_, _, part), g in month.groupby(["meet", "distance_m", "section"]):
            assert len(g) == 12 and abs(g.month_add.mean()) < 1e-12
            assert g.month_add.abs().max() <= experiment.S.CAPS[part][2] + 1e-12
        gate = pd.read_parquet(folder / "gates.parquet")
        for part, g in gate.groupby("section"):
            assert g.base_add_seconds.abs().max() <= experiment.S.CAPS[part][0] + 1e-12
            assert g.state_add_seconds.abs().max() <= experiment.S.CAPS[part][1] + 1e-12
        moist = pd.read_parquet(folder / "moisture.parquet")
        dry = moist[moist.band.eq("건조") & moist.supported]
        assert dry.moisture_add.abs().max() < 1e-12
    # Re-infer every chronological auxiliary model on all of its predicted-year rows.
    max_error = 0.0
    for path in sorted((OUT / "pace_models").glob("*.json")):
        meta = json.loads(path.read_text())
        year = meta["year"]
        assert pd.Timestamp(meta["train_end"]).year < year
        x = f.loc[f.year.eq(year), meta["features"]].copy()
        for col, vocab in meta["category_vocabulary"].items():
            x[col] = pd.Categorical(x[col], categories=vocab)
        p = lgb.Booster(model_file=str(path.with_suffix(".txt"))).predict(x, num_threads=4)
        cols = (
            ["pace_p" + str(j) for j in range(4)]
            if meta["task"] == "early"
            else ["pace_" + meta["task"]]
        )
        expected = f.loc[f.year.eq(year), cols].to_numpy()
        p = p if p.ndim == 2 else p[:, None]
        assert np.allclose(p, expected, atol=1e-12, rtol=0)
        max_error = max(max_error, float(abs(p - expected).max()))
        checks += p.size
    assert f.loc[f.year.lt(2020), ["pace_p0", "pace_recovery", "pace_fade"]].isna().all().all()
    predictions = pd.read_parquet(OUT / "runner_predictions.parquet")
    races = pd.read_csv(OUT / "race_metrics.csv")
    # Frozen baseline replay independently aligned by runner identity.
    old = pd.read_parquet(experiment.W / "runner_predictions.parquet")
    old = old[old.variant.eq("month_gate_weight22")]
    new = predictions[predictions.variant.eq("baseline22") & predictions.target.eq(3)]
    p = new.merge(old, on=experiment.KEY, validate="one_to_one", suffixes=("_new", "_old"))
    assert len(p) == 50754
    assert np.allclose(p.raw_score, p.raw_top3_score, atol=1e-12, rtol=0)
    assert np.allclose(p.target_probability, p.prob_top3, atol=1e-12, rtol=0)
    heads = 0
    temperatures = {}
    for folder in sorted((OUT / "finish_models").iterdir()):
        meta = json.loads((folder / "metadata.json").read_text())
        year = meta["evaluation_year"]
        assert pd.Timestamp(meta["train_end"]).year <= year - 2
        assert meta["calibration_year"] == year - 1 and meta["validation_year"] == year - 2
        target = meta["target"]
        meet = int(folder.name.split("_")[-2])
        temperatures[(target, meta["variant"], meet, year)] = meta["temperature"]
        q = f[f.year.eq(year) & f.meet.eq(meet)]
        x = q[meta["features"]].copy()
        for col, vocab in meta["category_vocabulary"].items():
            x[col] = pd.Categorical(x[col], categories=vocab)
        model = folder / "model.txt"
        if meta.get("reused_frozen_model"):
            model = experiment.W / "models" / f"{meet}_{year}_month_gate_weight22/top3.txt"
        score = lgb.Booster(model_file=str(model)).predict(x, raw_score=True, num_threads=4)
        saved = pd.read_parquet(folder / "runners.parquet")
        aligned = (
            q[experiment.KEY]
            .assign(replayed_score=score)
            .merge(saved, on=experiment.KEY, validate="one_to_one")
        )
        assert np.allclose(aligned.replayed_score, aligned.raw_score, atol=1e-12, rtol=0)
        checks += len(score)
        heads += 1
    race_index = races.set_index(["target", "variant", "race_key"], verify_integrity=True)
    # Independent ticket-set definitions, rather than ordinal-position helper.
    for (target, variant, rid), g in predictions.groupby(
        ["target", "variant", "race_key"], sort=False
    ):
        a = g.sort_values(["raw_score", "program_no"], ascending=[False, True])
        actual = set(a.loc[a.outcome.between(1, 2), "program_no"])
        assert len(actual) == 2
        programs = a.program_no.tolist()
        row = race_index.loc[(target, variant, rid)]
        expected = dict(
            quinella_one=int(actual == set(programs[:2])),
            axis_top2=int(programs[0] in actual),
            axis_top3=int(a.outcome.iloc[0] in [1, 2, 3]),
            axis_win=int(a.outcome.iloc[0] == 1),
            axis_next3=int(programs[0] in actual and actual <= set(programs[:4])),
            quinella_box4=int(actual <= set(programs[:4])),
        )
        assert all(int(row[k]) == v for k, v in expected.items())
        probs = a.target_probability.to_numpy()
        assert np.isfinite(probs).all() and ((probs >= 0) & (probs <= 1 + 1e-12)).all()
        assert abs(probs.sum() - target) < 1e-10
        actual_target = a.outcome.between(1, target).to_numpy(float)
        assert abs(float(np.mean((probs - actual_target) ** 2)) - row.target_brier) < 1e-12
        choices = np.array(list(itertools.combinations(range(len(a)), target)), dtype=int)
        temperature = temperatures[(target, variant, int(row.meet), int(row.year))]
        scores = a.raw_score.to_numpy()
        energy = np.sort(scores[choices], axis=1).sum(axis=1) / temperature
        weights = np.exp(energy - logsumexp(energy))
        independent = np.zeros(len(a))
        np.add.at(independent, choices.ravel(), np.repeat(weights, target))
        assert np.allclose(independent, probs, rtol=0, atol=1e-12)
        truth_energy = np.sort(scores[actual_target.astype(bool)]).sum() / temperature
        assert abs(float(logsumexp(energy) - truth_energy) - row.set_logloss) < 1e-12
        checks += len(expected) + len(a) + 1
    assert races.groupby(["target", "variant"]).size().eq(4799).all()
    # Replay one fixed main paired comparison's date bootstrap with the saved seed.
    audit = json.loads((OUT / "paired_differences.json").read_text())
    chosen = next(
        r
        for r in audit["comparisons"]
        if r["target"] == 3
        and r["variant"] == "field_context"
        and r["reference"] == "baseline22"
        and r["meet"] == 0
        and r["period"] == "all"
        and r["metric"] == "quinella_one"
    )
    aa = races[races.target.eq(3) & races.variant.eq("field_context")].set_index("race_key")
    bb = (
        races[races.target.eq(3) & races.variant.eq("baseline22")]
        .set_index("race_key")
        .loc[aa.index]
    )
    delta = aa.quinella_one - bb.quinella_one
    days = (
        pd.DataFrame({"date": aa.race_date, "delta": delta})
        .groupby("date")
        .delta.agg(["sum", "size"])
        .to_numpy()
    )
    draw = days[
        np.random.default_rng(chosen["bootstrap_seed"]).integers(
            0, len(days), size=(2000, len(days))
        )
    ].sum(axis=1)
    assert np.allclose(
        np.quantile(draw[:, 0] / draw[:, 1], [0.025, 0.975]) * 100,
        chosen["date_bootstrap_95_pp"],
        atol=1e-12,
    )
    experiment.check_inputs()
    experiment.save(
        OUT / "verification.json",
        dict(
            passed=True,
            numeric_checks=checks,
            finish_heads_replayed=heads,
            auxiliary_heads_replayed=len(list((OUT / "pace_models").glob("*.json"))),
            annual_environment_models=environment_models,
            max_prediction_error=max_error,
            frozen_baseline_runners_reproduced=len(p),
            independent_history_rows=len(sample),
            original22_unchanged=True,
            chronology_verified=True,
            input_hashes_unchanged=True,
            production_changed=False,
        ),
    )
    print(json.dumps(json.loads((OUT / "verification.json").read_text()), indent=2))


if __name__ == "__main__":
    main()
