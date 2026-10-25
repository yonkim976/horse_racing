"""Frozen axis-in/axis-out budget comparison; no fitting, network, or database."""

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
SRC = R / "20261009_axis_collapse_v1/outputs"
SEED = 20261009


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def check():
    for p, digest in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / p) == digest, p


def best(q, sets, numbers, mask, n):
    return sorted(np.flatnonzero(mask), key=lambda i: (-q[i], tuple(sorted(numbers[sets[i]]))))[:n]


def main():
    OUT.mkdir(exist_ok=True)
    sources = [
        SRC / n
        for n in [
            "oof_runners.parquet",
            "risk_predictions.parquet",
            "race_metrics.csv",
            "verification.json",
        ]
    ]
    sources += [
        HERE / "PLAN.md",
        HERE / "run.py",
        HERE / "verify.py",
        ROOT / "config/prediction_model_registry.json",
        R / "20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json",
    ]
    assert not (OUT / "source_lock.json").exists()
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in sources})
    f = pd.read_parquet(SRC / "oof_runners.parquet")
    f = f[f.year.ge(2024)]
    p = pd.read_parquet(SRC / "risk_predictions.parquet")
    flags = p[p.variant.eq("context")].set_index("race_key").flag.to_dict()
    rows, tickets = [], []
    for rid, g in f.groupby("race_key", sort=False):
        g = g.sort_values(["score", "program_no"], ascending=[False, True]).reset_index(drop=True)
        numbers = g.program_no.to_numpy()
        sets = np.array(list(itertools.combinations(range(len(g)), 3)))
        energy = np.sort((g.score.to_numpy() / g.tau.iloc[0])[sets], axis=1).sum(axis=1)
        q = np.exp(energy - logsumexp(energy))
        inside = (sets == 0).any(axis=1)
        fixed = best(q, sets, numbers, inside & (sets < 7).all(axis=1), 6)
        excluded = best(q, sets, numbers, ~inside, 6)
        free = best(q, sets, numbers, np.ones(len(sets), bool), 12)
        policies = {f"in{k}_out{6 - k}": fixed[:k] + excluded[: 6 - k] for k in range(7)}
        policies.update(
            global6=free[:6],
            global12=free,
            in6_out6=fixed + excluded,
            risk_add6=fixed + excluded if flags[rid] else fixed,
        )
        truth = set(g.loc[g.outcome.between(1, 3), "program_no"])
        for policy, ix in policies.items():
            assert len(ix) == len(set(ix))
            trios = [tuple(sorted(numbers[sets[i]])) for i in ix]
            hit = int(any(set(t) == truth for t in trios))
            rows.append(
                dict(
                    race_key=rid,
                    race_date=g.race_date.iloc[0],
                    year=int(g.year.iloc[0]),
                    meet=int(g.meet.iloc[0]),
                    policy=policy,
                    ticket_count=len(ix),
                    hit=hit,
                    axis_number=int(numbers[0]),
                    collapsed=int(numbers[0] not in truth),
                    flagged=bool(flags[rid]),
                )
            )
            tickets.extend(
                dict(
                    race_key=rid,
                    policy=policy,
                    selection_rank=j + 1,
                    programs=",".join(map(str, t)),
                    probability=float(q[i]),
                    hit=int(set(t) == truth),
                )
                for j, (i, t) in enumerate(zip(ix, trios, strict=True))
            )
    m = pd.DataFrame(rows)
    m.to_parquet(OUT / "race_metrics.parquet", index=False)
    pd.DataFrame(tickets).to_parquet(OUT / "tickets.parquet", index=False)
    summaries = []
    for scope, filt in [("all", pd.Series(True, index=m.index))] + [
        (str(y), m.year.eq(y)) for y in [2024, 2025, 2026]
    ]:
        for policy, g in m[filt].groupby("policy"):
            summaries.append(
                dict(
                    scope=scope,
                    policy=policy,
                    races=len(g),
                    hits=int(g.hit.sum()),
                    hit_rate=float(g.hit.mean()),
                    mean_tickets=float(g.ticket_count.mean()),
                    total_tickets=int(g.ticket_count.sum()),
                    hits_per_100_tickets=float(100 * g.hit.sum() / g.ticket_count.sum()),
                    hit_axis_survives=int(g.loc[g.collapsed.eq(0), "hit"].sum()),
                    hit_axis_collapses=int(g.loc[g.collapsed.eq(1), "hit"].sum()),
                )
            )
    pd.DataFrame(summaries).to_csv(OUT / "summary.csv", index=False)
    wide = m.pivot(index="race_key", columns="policy", values="hit")
    dates = m.drop_duplicates("race_key").set_index("race_key").loc[wide.index, "race_date"]
    differences = []
    for policy in wide.columns:
        control = "global12" if policy in ["in6_out6", "global12"] else "in6_out0"
        if policy == control:
            continue
        d = (wide[policy] - wide[control]).to_numpy()
        ag = (
            pd.DataFrame({"date": dates.to_numpy(), "d": d}).groupby("date").d.agg(["sum", "count"])
        )
        rng = np.random.default_rng(SEED)
        ix = rng.integers(0, len(ag), size=(2000, len(ag)))
        draws = ag["sum"].to_numpy()[ix].sum(axis=1) / ag["count"].to_numpy()[ix].sum(axis=1)
        lo, hi = np.quantile(draws, [0.025, 0.975])
        differences.append(
            dict(
                candidate=policy,
                control=control,
                delta=float(d.mean()),
                ci_low=float(lo),
                ci_high=float(hi),
                rescued=int((d == 1).sum()),
                lost=int((d == -1).sum()),
            )
        )
    pd.DataFrame(differences).to_csv(OUT / "paired_differences.csv", index=False)
    check()
    print(pd.DataFrame(summaries).query("scope == 'all'").to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
