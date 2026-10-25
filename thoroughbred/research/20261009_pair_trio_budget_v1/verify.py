"""Replay Top2 models and enumerate unordered winning sets independently."""

import itertools
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
import run as e
from scipy.special import softmax


def main():
    e.check()
    f = pd.read_parquet(e.S / "features.parquet")
    p = e.pair_data()
    for meet in [1, 3]:
        for year in [2024, 2025, 2026]:
            path = e.S / f"finish_models/2_baseline22_{meet}_{year}"
            meta = json.loads((path / "metadata.json").read_text())
            x = f[f.meet.eq(meet) & f.year.eq(year)].sort_values(e.KEY).reset_index(drop=True)
            z = p[p.meet.eq(meet) & p.year.eq(year)].sort_values(e.KEY).reset_index(drop=True)
            assert np.array_equal(x[e.KEY].astype(str).to_numpy(), z[e.KEY].astype(str).to_numpy())
            x = x[meta["features"]].copy()
            for col, levels in meta["category_vocabulary"].items():
                x[col] = pd.Categorical(x[col].where(x[col].isin(levels)), categories=levels)
            model = lgb.Booster(model_file=str(path / "model.txt"))
            assert np.array_equal(
                model.predict(x, raw_score=True, num_threads=4), z.raw_score.to_numpy()
            )
            assert e.sha(path / "model.txt") == meta["model_sha256"]
            assert pd.Timestamp(meta["train_end"]).year <= year - 2
            assert meta["calibration_year"] == year - 1
    f = pd.read_parquet(e.A / "oof_runners.parquet")
    f = f[f.year.ge(2024)]
    pp = {rid: g for rid, g in p.groupby("race_key", sort=False)}
    tickets = pd.read_parquet(e.OUT / "tickets.parquet")
    saved = {
        (r, b, p): g.sort_values("selection_rank")
        for (r, b, p), g in tickets.groupby(["race_key", "bet", "policy"], sort=False)
    }
    metrics = pd.read_parquet(e.OUT / "race_metrics.parquet")
    tested = 0
    for rid, g in f.groupby("race_key", sort=False):
        g = g.sort_values(["score", "program_no"], ascending=[False, True]).reset_index(drop=True)
        nums = g.program_no.to_numpy()
        scores = g.score.to_numpy() / g.tau.iloc[0]
        triples = list(itertools.combinations(range(len(g)), 3))
        pairs = list(itertools.combinations(range(len(g)), 2))
        tq = softmax([sum(sorted(scores[list(t)])) for t in triples])
        pq = np.array(
            [
                sum(q for t, q in zip(triples, tq, strict=True) if set(pair) <= set(t))
                for pair in pairs
            ]
        )
        assert abs(pq.sum() - 3) < 1e-12
        p = pp[rid].set_index("program_no").loc[nums]
        meta = json.loads(
            (
                e.S
                / f"finish_models/2_baseline22_{int(g.meet.iloc[0])}_{int(g.year.iloc[0])}/metadata.json"
            ).read_text()
        )
        scores2 = p.raw_score.to_numpy() / meta["temperature"]
        eq = softmax([sum(sorted(scores2[list(t)])) for t in pairs])
        truth = set(g.loc[g.outcome.between(1, 3), "program_no"])
        top2 = set(g.loc[g.outcome.between(1, 2), "program_no"])
        for bet, sets, q in [
            ("quinella", pairs, eq),
            ("quinella_place", pairs, pq),
            ("trio", triples, tq),
        ]:
            order = sorted(
                range(len(sets)), key=lambda i: (-q[i], tuple(sorted(nums[list(sets[i])])))
            )
            inc = [i for i in order if 0 in sets[i] and (bet != "trio" or max(sets[i]) < 7)]
            exc = [i for i in order if 0 not in sets[i]]
            choices = dict(
                in3_out3=inc[:3] + exc[:3],
                in2_out1=inc[:2] + exc[:1],
                in3_out0=inc[:3],
                global3=order[:3],
                global6=order[:6],
            )
            for policy, ix in choices.items():
                old = saved[rid, bet, policy]
                want = [",".join(map(str, sorted(nums[list(sets[i])]))) for i in ix]
                assert old.programs.tolist() == want
                assert np.max(np.abs(old.probability.to_numpy() - q[ix])) < 1e-12
                for j, t in enumerate(want):
                    selected = set(map(int, t.split(",")))
                    expected = int(selected == top2 if bet == "quinella" else selected <= truth)
                    assert old.hit.iloc[j] == expected
                tested += 1
    summary = metrics.groupby(["bet", "policy"]).hit.sum()
    assert summary["trio", "in3_out3"] == 1026 and summary["trio", "global6"] == 1228
    assert metrics.groupby(["race_key", "bet", "policy"]).size().eq(1).all()
    assert metrics.bet.value_counts().eq(4799 * 5).all()
    for bet in ["quinella", "trio"]:
        assert metrics[metrics.bet.eq(bet)].winning_tickets.le(1).all()
    assert metrics[metrics.bet.eq("quinella_place")].winning_tickets.le(3).all()
    e.check()
    e.save(
        e.OUT / "verification.json",
        dict(
            status="passed",
            top2_models_replayed=6,
            race_policies=tested,
            tickets=len(tickets),
            probability_and_winners_independently_enumerated=True,
            place_pair_probability_sum_three=True,
            baseline_trio_reproduced=True,
            source_hashes_unchanged=True,
            budget_verified=True,
            axis_definition="same original Top3 score leader for all bet types",
            new_training=False,
            database_access=False,
            jeju_access=False,
            production_changed=False,
        ),
    )
    print("Verified", tested, len(tickets), flush=True)


if __name__ == "__main__":
    main()
