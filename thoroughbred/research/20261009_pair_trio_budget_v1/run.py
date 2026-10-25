"""Frozen exact-Top2 and Top3-pair/trio budget comparison."""

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = R.parents[1]
OUT = HERE / "outputs"
A = R / "20261009_axis_collapse_v1/outputs"
S = R / "20261009_section_style_finish_v1/outputs"
KEY = ["race_key", "program_no", "horse_id"]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def check():
    for path, h in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / path) == h, path


def pair_data():
    p = pd.read_parquet(S / "runner_predictions.parquet")
    return p[p.target.eq(2) & p.variant.eq("baseline22")].sort_values(KEY).reset_index(drop=True)


def distributions(g, p):
    g = g.sort_values(["score", "program_no"], ascending=[False, True]).reset_index(drop=True)
    nums = g.program_no.to_numpy()
    tri = np.array(list(itertools.combinations(range(len(g)), 3)))
    pairs = np.array(list(itertools.combinations(range(len(g)), 2)))
    energies = np.sort((g.score.to_numpy() / g.tau.iloc[0])[tri], axis=1).sum(axis=1)
    tq = np.exp(energies - logsumexp(energies))
    pair_lookup = {tuple(t): i for i, t in enumerate(pairs)}
    pq = np.zeros(len(pairs))
    for t, q in zip(tri, tq, strict=True):
        for pair in itertools.combinations(t, 2):
            pq[pair_lookup[pair]] += q
    assert abs(pq.sum() - 3) < 1e-12
    p = p.set_index("program_no").loc[nums]
    assert np.array_equal(p.horse_id.to_numpy(), g.horse_id.to_numpy())
    assert np.array_equal(p.outcome.to_numpy(), g.outcome.to_numpy())
    meta = json.loads(
        (
            S
            / f"finish_models/2_baseline22_{int(g.meet.iloc[0])}_{int(g.year.iloc[0])}/metadata.json"
        ).read_text()
    )
    pe = np.sort((p.raw_score.to_numpy() / meta["temperature"])[pairs], axis=1).sum(axis=1)
    eq = np.exp(pe - logsumexp(pe))
    return g, dict(quinella=(pairs, eq), quinella_place=(pairs, pq), trio=(tri, tq))


def main():
    OUT.mkdir(exist_ok=True)
    sources = [HERE / n for n in ["PLAN.md", "run.py", "verify.py"]]
    sources += [
        A / "oof_runners.parquet",
        S / "runner_predictions.parquet",
        S / "features.parquet",
        ROOT / "config/prediction_model_registry.json",
        R / "20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json",
    ]
    for meet in [1, 3]:
        for year in [2024, 2025, 2026]:
            sources += [
                S / f"finish_models/2_baseline22_{meet}_{year}" / n
                for n in ["model.txt", "metadata.json"]
            ]
    assert not (OUT / "source_lock.json").exists()
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in sources})
    runners = pd.read_parquet(A / "oof_runners.parquet")
    runners = runners[runners.year.ge(2024)]
    pp = {rid: g for rid, g in pair_data().groupby("race_key", sort=False)}
    rows, tickets = [], []
    for rid, g in runners.groupby("race_key", sort=False):
        g, dist = distributions(g, pp[rid])
        nums = g.program_no.to_numpy()
        winners = set(g.loc[g.outcome.between(1, 3), "program_no"])
        top2 = set(g.loc[g.outcome.between(1, 2), "program_no"])
        for bet, (sets, q) in dist.items():
            ordered = sorted(range(len(sets)), key=lambda i: (-q[i], tuple(sorted(nums[sets[i]]))))
            inc = [i for i in ordered if 0 in sets[i] and (bet != "trio" or max(sets[i]) < 7)]
            exc = [i for i in ordered if 0 not in sets[i]]
            policies = dict(
                in3_out3=inc[:3] + exc[:3],
                in2_out1=inc[:2] + exc[:1],
                in3_out0=inc[:3],
                global3=ordered[:3],
                global6=ordered[:6],
            )
            for policy, ix in policies.items():
                trios = [set(nums[sets[i]]) for i in ix]
                hits = [int(t == top2 if bet == "quinella" else t <= winners) for t in trios]
                assert len(ix) == len(set(ix)) == (6 if policy in ["in3_out3", "global6"] else 3)
                rows.append(
                    dict(
                        race_key=rid,
                        race_date=g.race_date.iloc[0],
                        year=int(g.year.iloc[0]),
                        meet=int(g.meet.iloc[0]),
                        bet=bet,
                        policy=policy,
                        axis_number=int(nums[0]),
                        ticket_count=len(ix),
                        hit=int(any(hits)),
                        winning_tickets=sum(hits),
                    )
                )
                tickets.extend(
                    dict(
                        race_key=rid,
                        bet=bet,
                        policy=policy,
                        selection_rank=j + 1,
                        programs=",".join(map(str, sorted(t))),
                        probability=float(q[i]),
                        hit=h,
                    )
                    for j, (i, t, h) in enumerate(zip(ix, trios, hits, strict=True))
                )
    m = pd.DataFrame(rows)
    m.to_parquet(OUT / "race_metrics.parquet", index=False)
    pd.DataFrame(tickets).to_parquet(OUT / "tickets.parquet", index=False)
    summary = []
    for scope, mask in [("all", pd.Series(True, index=m.index))] + [
        (str(y), m.year.eq(y)) for y in [2024, 2025, 2026]
    ]:
        for (bet, policy), g in m[mask].groupby(["bet", "policy"]):
            summary.append(
                dict(
                    scope=scope,
                    bet=bet,
                    policy=policy,
                    races=len(g),
                    tickets_per_race=int(g.ticket_count.iloc[0]),
                    hits=int(g.hit.sum()),
                    hit_rate=float(g.hit.mean()),
                    winning_tickets=int(g.winning_tickets.sum()),
                )
            )
    pd.DataFrame(summary).to_csv(OUT / "summary.csv", index=False)
    check()
    print(pd.DataFrame(summary).query("scope=='all'").to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
