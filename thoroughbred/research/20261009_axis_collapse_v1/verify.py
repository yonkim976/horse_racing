"""Replay models and independently enumerate every evaluated six-ticket policy."""

import itertools
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
import run as e
from scipy.special import expit, logit, softmax


def main():
    e.check()
    f = pd.read_parquet(e.W / "features_month_gate_weight22.parquet")
    runners = pd.read_parquet(e.OUT / "oof_runners.parquet")
    races = pd.read_parquet(e.OUT / "race_inputs.parquet")
    pred = pd.read_parquet(e.OUT / "risk_predictions.parquet")
    metrics = pd.read_csv(e.OUT / "race_metrics.csv")
    tickets = pd.read_parquet(e.OUT / "six_tickets.parquet")
    assert len(pred) == 4799 * 3
    assert races.groupby("year").collapsed.count().loc[2024:2026].sum() == 4799
    assert len(runners) == len(runners.drop_duplicates(e.KEY))
    for c in ["history_source_date", "profile_source_date", "weight_source_date"]:
        assert (f[c].isna() | (f[c] <= f.cutoff_date)).all(), c
    base_replays = 0
    for meet in [1, 3]:
        for year in range(2020, 2027):
            dest = (
                e.OUT / "base_models" / f"{meet}_{year}"
                if year < 2024
                else e.W / "models" / f"{meet}_{year}_month_gate_weight22"
            )
            meta = json.loads((dest / "metadata.json").read_text())
            z = f[f.meet.eq(meet) & f.year.eq(year)].sort_values(e.KEY).reset_index(drop=True)
            r = (
                runners[runners.meet.eq(meet) & runners.year.eq(year)]
                .sort_values(e.KEY)
                .reset_index(drop=True)
            )
            assert np.array_equal(z[e.KEY].astype(str).to_numpy(), r[e.KEY].astype(str).to_numpy())
            x, _ = e.encode(z, meta["features"], vocabulary=meta["category_vocabulary"])
            model_file = dest / ("model.txt" if year < 2024 else "top3.txt")
            model = lgb.Booster(model_file=str(model_file))
            assert e.sha(model_file) == meta["model_sha256"]
            assert np.max(np.abs(model.predict(x, raw_score=True, num_threads=4) - r.score)) == 0
            assert np.allclose(r.tau, meta["temperature"], rtol=0, atol=1e-14)
            assert pd.Timestamp(meta["train_max" if year < 2024 else "train_end"]).year <= year - 2
            if year < 2024:
                cal = pd.read_parquet(dest / "calibration.parquet").sort_values(e.KEY)
                source = (
                    f[f.meet.eq(meet) & f.year.eq(year - 1)]
                    .sort_values(e.KEY)
                    .reset_index(drop=True)
                )
                cx, _ = e.encode(source, meta["features"], vocabulary=meta["category_vocabulary"])
                assert (
                    np.max(
                        np.abs(
                            model.predict(cx, raw_score=True, num_threads=4) - cal.score.to_numpy()
                        )
                    )
                    == 0
                )
                tau = e.temperature(source, cal.score.to_numpy())
                assert abs(tau - meta["temperature"]) < 1e-12
            base_replays += 1
    risk_replays = 0
    for (variant, year), pp in pred.groupby(["variant", "year"]):
        dest = e.OUT / "risk_models" / f"{variant}_{year}"
        meta = json.loads((dest / "metadata.json").read_text())
        z = races[races.year.eq(year)].sort_values("race_key").reset_index(drop=True)
        pp = pp.sort_values("race_key").reset_index(drop=True)
        ca = races[races.year.eq(year - 1)].sort_values("race_key").reset_index(drop=True)
        cal = (
            pd.read_parquet(dest / "calibration.parquet")
            .sort_values("race_key")
            .reset_index(drop=True)
        )
        assert meta["train_year_max"] == year - 2 and meta["calibration_year"] == year - 1
        assert "collapsed" not in meta["features"] and "outcome" not in meta["features"]
        if variant == "base_cal":
            raw, cr = z.base_risk.to_numpy(), ca.base_risk.to_numpy()
        else:
            x, _ = e.encode(z, meta["features"], vocabulary=meta["vocabulary"])
            cx, _ = e.encode(ca, meta["features"], vocabulary=meta["vocabulary"])
            model = lgb.Booster(model_file=str(dest / "model.txt"))
            raw, cr = model.predict(x, num_threads=4), model.predict(cx, num_threads=4)
            poison = z.copy()
            poison["collapsed"] = 1 - poison.collapsed
            poison["axis_number"] = -999
            px, _ = e.encode(poison, meta["features"], vocabulary=meta["vocabulary"])
            assert np.array_equal(raw, model.predict(px, num_threads=4))
            risk_replays += 1
        assert np.max(np.abs(raw - pp.raw_risk)) < 1e-15
        assert np.max(np.abs(cr - cal.raw_risk)) < 1e-15
        ab = e.calibrate(cr, ca.collapsed.to_numpy())
        assert np.max(np.abs(np.array(ab) - meta["platt"])) < 1e-5
        a, b = meta["platt"]
        assert np.max(np.abs(expit(a + b * logit(np.clip(raw, 1e-6, 1 - 1e-6))) - pp.risk)) < 1e-15
        threshold = float(np.quantile(cal.risk, 0.7))
        assert threshold == meta["threshold"]
        assert np.array_equal(pp.risk.ge(threshold), pp.flag)
    lookup = {rid: g.set_index("variant") for rid, g in pred.groupby("race_key")}
    saved = {
        (rid, pol): g.sort_values("selection_rank")
        for (rid, pol), g in tickets.groupby(["race_key", "policy"], sort=False)
    }
    tested = 0
    for rid, g in runners[runners.year.ge(2024)].groupby("race_key", sort=False):
        g = g.sort_values(["score", "program_no"], ascending=[False, True]).reset_index(drop=True)
        numbers = g.program_no.to_numpy()
        combos = list(itertools.combinations(range(len(g)), 3))
        scores = g.score.to_numpy() / g.tau.iloc[0]
        energies = np.array([sum(sorted(scores[list(t)])) for t in combos])
        q = softmax(energies)
        risk = sum(p for t, p in zip(combos, q, strict=True) if 0 not in t)
        truth = set(g.loc[g.outcome.between(1, 3), "program_no"])
        assert len(truth) == 3
        for variant in lookup[rid].index:
            assert abs(lookup[rid].loc[variant, "base_risk"] - risk) < 1e-12
            assert lookup[rid].loc[variant, "collapsed"] == int(numbers[0] not in truth)
        for policy in metrics.policy.unique():
            mode = policy
            pq = q.copy()
            if policy not in ["fixed7", "global6"]:
                variant, action = (
                    policy.split("_trigger_")
                    if "_trigger_" in policy
                    else (policy.removesuffix("_reweight"), "reweight")
                )
                pr = lookup[rid].loc[variant]
                if action == "reweight":
                    pq = np.array(
                        [
                            p * ((1 - pr.risk) / (1 - risk) if 0 in t else pr.risk / risk)
                            for t, p in zip(combos, q, strict=True)
                        ]
                    )
                    assert abs(pq.sum() - 1) < 1e-12
                    mode = "global6"
                else:
                    mode = ("global6" if action == "free" else "exclude") if pr.flag else "fixed7"
            ix = [
                i
                for i, t in enumerate(combos)
                if mode == "global6"
                or (mode == "fixed7" and 0 in t and max(t) < 7)
                or (mode == "exclude" and 0 not in t)
            ]
            ix.sort(key=lambda i: (-pq[i], tuple(sorted(numbers[list(combos[i])]))))
            want = ix[:6]
            old = saved[rid, policy]
            expected = [",".join(map(str, sorted(numbers[list(combos[i])]))) for i in want]
            assert old.programs.tolist() == expected, (rid, policy)
            assert np.max(np.abs(old.probability.to_numpy() - pq[want])) < 1e-12
            assert old.hit.sum() == int(any(set(map(int, t.split(","))) == truth for t in expected))
            tested += 1
    baseline = metrics.groupby("policy").hit.sum()
    assert baseline["fixed7"] == 1204 and baseline["global6"] == 1228
    # Recompute every paired date-bootstrap comparison from saved per-race events.
    comparisons = pd.read_csv(e.OUT / "paired_differences.csv")
    checked_differences = 0
    for _, row in comparisons.iterrows():
        z = metrics
        if row.scope in ["2024", "2025", "2026"]:
            z = z[z.year.eq(int(row.scope))]
        if row.scope in ["Seoul", "Busan"]:
            z = z[z.meet.eq(1 if row.scope == "Seoul" else 3)]
        if row.control == "base_raw":
            a = pred[pred.variant.eq(row.candidate)].sort_values("race_key")
            b = pred[pred.variant.eq("base_cal")].sort_values("race_key")
            y, p, q = a.collapsed.to_numpy(), a.risk.to_numpy(), b.base_risk.to_numpy()
            if row.metric == "brier":
                d = (p - y) ** 2 - (q - y) ** 2
            else:
                d = -(y * np.log(p) + (1 - y) * np.log1p(-p)) + (
                    y * np.log(q) + (1 - y) * np.log1p(-q)
                )
            dates = a.race_date.to_numpy()
        else:
            wide = z.pivot(index="race_key", columns="policy", values="hit")
            d = (wide[row.candidate] - wide[row.control]).to_numpy()
            dates = (
                z.drop_duplicates("race_key")
                .set_index("race_key")
                .loc[wide.index, "race_date"]
                .to_numpy()
            )
        aggregate = pd.DataFrame({"date": dates, "d": d}).groupby("date").d.agg(["sum", "size"])
        rng = np.random.default_rng(e.CFG["bootstrap_seed"])
        samples = rng.integers(len(aggregate), size=(2000, len(aggregate)))
        simulated = aggregate["sum"].to_numpy()[samples].sum(axis=1) / aggregate["size"].to_numpy()[
            samples
        ].sum(axis=1)
        expected = [np.mean(d), *np.quantile(simulated, [0.025, 0.975])]
        assert (
            np.max(np.abs(np.array(expected) - [row.difference, row.ci_low, row.ci_high])) < 1e-12
        )
        checked_differences += 1
    # Predictors use a whitelist: changing/deleting current outcomes must not change inputs.
    contract = json.loads((e.OUT / "feature_contract.json").read_text())
    assert not any(
        "outcome" in c or "finish" in c or "jockey" in c or "trainer" in c
        for cols in [contract["score"], contract["context"]]
        for c in cols
    )
    e.check()
    e.save(
        e.OUT / "verification.json",
        dict(
            status="passed",
            base_models_replayed=base_replays,
            risk_models_replayed=risk_replays,
            race_policies_enumerated=tested,
            tickets_verified=len(tickets),
            paired_comparisons_recomputed=checked_differences,
            prior_only_time_boundaries=True,
            calibration_and_threshold_prior_year=True,
            feature_label_poison_invariance=True,
            source_hashes_unchanged=True,
            baseline_hits_reproduced=True,
            current_carried_weight_pit_verified=False,
            caveat="Inherited weight source PIT limitation; retrospective reused evaluation.",
        ),
    )
    print("Verified", base_replays, risk_replays, tested, len(tickets), flush=True)


if __name__ == "__main__":
    main()
