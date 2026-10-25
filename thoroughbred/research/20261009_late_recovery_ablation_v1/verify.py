"""Reinfer saved models and independently reconstruct features/tickets/metrics."""

import itertools
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
import run as e


def main():
    e.check()
    f = pd.read_parquet(e.OUT / "features.parquet")
    p = pd.read_parquet(e.OUT / "runner_predictions.parquet")
    r = pd.read_parquet(e.OUT / "race_metrics.parquet")
    h = pd.read_parquet(e.OUT / "runner_metrics.parquet")
    tickets = pd.read_parquet(e.OUT / "six_tickets.parquet")
    contracts = json.loads((e.OUT / "feature_contract.json").read_text())
    assert len(f) == 178497 and f.year.ge(2024).sum() == 50754
    original = pd.read_parquet(e.S / "outputs/features.parquet").set_index(e.KEY)
    assert f[contracts["baseline22"]].equals(
        original.loc[pd.MultiIndex.from_frame(f[e.KEY]), contracts["baseline22"]].reset_index(
            drop=True
        )
    )
    for col in ["history_source_date", "profile_source_date"]:
        assert (f[col].isna() | (f[col] <= f.cutoff_date)).all()
    assert f.cutoff_date.le(f.race_date - pd.Timedelta(days=2)).all()
    for variant in ["baseline22", "late30", "recovery32", "pressure43", "reference53"]:
        assert len(p[p.variant.eq(variant)]) == 50754
        assert len(r[r.variant.eq(variant)]) == 4799
    base = r[r.variant.eq("baseline22")]
    assert (
        base.trio6.sum() == 1228 and base.axis_top3.sum() == 2862 and base.axis_top2.sum() == 2274
    )
    old = pd.read_parquet(e.V / "runner_inputs.parquet")
    old = old[old.model.eq("month_gate_weight22")]
    compare = p[p.variant.eq("baseline22")].merge(
        old[e.KEY + ["score", "tau"]], on=e.KEY, suffixes=("", "_old"), validate="one_to_one"
    )
    np.testing.assert_allclose(compare.raw_score, compare.score, atol=1e-12, rtol=0)
    np.testing.assert_allclose(compare.tau, compare.tau_old, atol=1e-12, rtol=0)
    # Re-inference uses stored feature vocabulary, not labels or current result columns.
    models = 0
    for folder in sorted((e.OUT / "models").iterdir()):
        meta = json.loads((folder / "metadata.json").read_text())
        variant = meta["variant"]
        meet = int(folder.name.split("_")[-2])
        year = meta["evaluation_year"]
        one = f[f.meet.eq(meet) & f.year.eq(year)].copy()
        x = one[meta["features"]].copy()
        for col, vocabulary in meta["category_vocabulary"].items():
            x[col] = pd.Categorical(x[col], categories=vocabulary)
        path = (
            e.W / "models" / f"{meet}_{year}_month_gate_weight22/top3.txt"
            if variant == "baseline22"
            else folder / "model.txt"
        )
        model = lgb.Booster(model_file=str(path))
        predicted = model.predict(x, raw_score=True, num_threads=4)
        stored = p[p.variant.eq(variant)].set_index(e.KEY).loc[pd.MultiIndex.from_frame(one[e.KEY])]
        np.testing.assert_allclose(predicted, stored.raw_score, atol=1e-12, rtol=0)
        assert meta["train_end"] < str(year - 1) and meta["calibration_year"] == year - 1
        if variant != "baseline22":
            assert e.sha(path) == meta["model_sha256"]
            models += 1
    assert models == 18
    # Direct peers: audit every held-out card and a deterministic historical sample.
    cards = f[f.year.ge(2024) | (f.index % 67 == 0)].race_key.unique()
    checks = 0
    for _, g in f[f.race_key.isin(cards)].groupby("race_key"):
        for ix, one in g.iterrows():
            other = g.drop(index=ix)
            for part in ["last600", "late"]:
                col = "section_" + part + "_mean3"
                adv = other[col].mean() - one[col]
                np.testing.assert_allclose(
                    one[part + "_relative_adv"], adv, atol=1e-12, equal_nan=True
                )
                valid = g[col].dropna()
                pct = (
                    ((valid > one[col]).sum() + ((valid == one[col]).sum() + 1) / 2) / len(valid)
                    if pd.notna(one[col])
                    else np.nan
                )
                np.testing.assert_allclose(
                    one[part + "_percentile"], pct, atol=1e-12, equal_nan=True
                )
            lead = other.style_role0_rate5.where(other.style_role_n5.ge(3)).dropna()
            mass = float(lead.sum()) if len(lead) else np.nan
            np.testing.assert_allclose(one.field_other_lead_mass, mass, atol=1e-12, equal_nan=True)
            strong = float(lead.ge(0.4).sum()) if len(lead) else np.nan
            np.testing.assert_allclose(one.field_strong_front_n, strong, atol=1e-12, equal_nan=True)
            early = other.section_early_mean3.where(other.section_early_n5.ge(3)).dropna()
            faster = (
                float(early.lt(one.section_early_mean3).sum())
                if len(early) and one.section_early_n5 >= 3 and pd.notna(one.section_early_mean3)
                else np.nan
            )
            np.testing.assert_allclose(one.field_early_faster_n, faster, atol=1e-12, equal_nan=True)
            np.testing.assert_allclose(
                one.field_early_support, len(early) / (len(g) - 1), atol=1e-12
            )
            checks += 1
    poison = f.copy()
    poison["outcome"] = -999
    derived = e.derive(poison)
    for col in derived:
        np.testing.assert_allclose(f[col], derived[col], equal_nan=True, atol=1e-12)
    # Indexed lookup avoids repeated full-table scans; checks are unchanged.
    ticket_groups = {key: value for key, value in tickets.groupby(["variant", "race_key"])}
    horse_groups = {key: value.sort_values("program_no") for key, value in h.groupby(["variant", "race_key"])}
    race_lookup = r.set_index(["variant", "race_key"])
    # Independent triple products, ordered by probability then original program tuple.
    for (variant, rid), g in p.groupby(["variant", "race_key"]):
        g = g.sort_values("program_no")
        scores = g.raw_score.to_numpy() / g.tau.iloc[0]
        weights = np.exp(scores - scores.max())
        combos = list(itertools.combinations(range(len(g)), 3))
        values = np.array([weights[a] * weights[b] * weights[c] for a, b, c in combos])
        probabilities = values / values.sum()
        # Preserve floating sum tie behavior using independently reconstructed energies.
        energies = [sum(sorted([scores[a], scores[b], scores[c]])) for a, b, c in combos]
        chosen = sorted(range(len(combos)), key=lambda j: (-energies[j], combos[j]))[:6]
        truth = tuple(np.flatnonzero(g.outcome.between(1, 3).to_numpy()))
        take = {"-".join(str(g.program_no.iloc[i]) for i in combos[j]) for j in chosen}
        t = ticket_groups[(variant, rid)]
        assert set(t.combination) == take and len(t) == 6
        truth_index = combos.index(truth)
        row = race_lookup.loc[(variant, rid)]
        assert row.trio6 == int(truth_index in chosen)
        marginal = np.zeros(len(g))
        for j, c in enumerate(combos):
            marginal[list(c)] += probabilities[j]
        stored = horse_groups[(variant, rid)]
        np.testing.assert_allclose(stored.probability, marginal, atol=1e-12)
        assert abs(marginal.sum() - 3) < 1e-12
        ranks = stored.model_rank.to_numpy()
        actual = g.outcome.between(1, 3).to_numpy()
        low = actual & (stored.baseline_rank.to_numpy() >= 6)
        assert int((low & (ranks <= 5)).sum()) == row.low_winners_up
        assert (
            int((actual & (stored.baseline_rank.to_numpy() <= 5) & (ranks >= 6)).sum())
            == row.old_winners_down
        )
        assert row.top5_contains_truth == int(ranks[actual].max() <= 5)
    e.check()
    e.save(
        e.OUT / "verification.json",
        dict(
            status="passed",
            fitted_outcome_models=models,
            frozen_baseline_models=6,
            evaluated_races_per_variant=4799,
            baseline_predictions_and_hits_reproduced=True,
            saved_models_reinferred=True,
            direct_peer_runner_checks=checks,
            target_poison_invariant=True,
            probability_and_ticket_selection_independently_recomputed=True,
            historical_source_dates_checked=True,
            source_hashes_unchanged=True,
            production_changed=False,
            selected_baseline_changed=False,
            database_access=False,
            jeju_access=False,
            future_period_evaluated=False,
        ),
    )
    print("Verified", models, checks, flush=True)


if __name__ == "__main__":
    main()
