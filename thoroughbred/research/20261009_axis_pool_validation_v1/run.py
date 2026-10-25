"""Thoroughbred-only frozen prediction policy validation; no fitting or DB access."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
R = HERE.parent
W = R / "20261008_profile_carried_weight_v1/outputs"
S = R / "20261009_section_style_finish_v1/outputs"
P = R / "20261009_axis_companion_pairs_v1/outputs"
OP = R / "20261004_close_contenders_v1/outputs"
KEY = ["race_key", "program_no", "horse_id"]
POLICIES = ["axis_pool5", "axis_pool6", "axis_pool7", "axis_all", "global6"]
CFG = json.loads((HERE / "config.json").read_text())


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as f:
        json.dump(
            value,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
            default=lambda x: x.item() if isinstance(x, np.generic) else str(x),
        )
        f.write("\n")


def refs():
    paths = [
        HERE / "PLAN.md",
        HERE / "config.json",
        HERE / "run.py",
        HERE / "verify.py",
        ROOT / "config/prediction_model_registry.json",
    ]
    paths += [
        W / n
        for n in [
            "features_month_gate_weight22.parquet",
            "runner_predictions.parquet",
            "recommendations.parquet",
            "research_baseline_selection.json",
            "verification.json",
        ]
    ]
    paths += [
        S / n for n in ["features.parquet", "runner_predictions.parquet", "verification.json"]
    ]
    paths += [
        P / n
        for n in [
            "oof_runners.parquet",
            "race_metrics.csv",
            "six_tickets.parquet",
            "final_verification.json",
        ]
    ]
    paths += [
        OP / n
        for n in [
            "race_diagnostics.csv",
            "operating_trio6.parquet",
            "operating_runner_predictions.parquet",
            "verification.json",
        ]
    ]
    for y in [2024, 2025, 2026]:
        for meet in [1, 3]:
            paths += [
                W / "models" / f"{meet}_{y}_month_gate_weight22" / n
                for n in ["top3.txt", "metadata.json"]
            ]
            paths += [
                S / "finish_models" / f"3_style_history_{meet}_{y}" / n
                for n in ["model.txt", "metadata.json"]
            ]
    for y in [2020, 2021, 2022, 2023]:
        for meet in [1, 3]:
            paths += [P / "base_models" / f"{meet}_{y}" / n for n in ["model.txt", "meta.json"]]
    return paths


def check():
    for p, h in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / p) == h, p


def load():
    context = pd.read_parquet(
        S / "features.parquet",
        columns=KEY
        + [
            "meet",
            "race_date",
            "year",
            "distance_m",
            "grade",
            "field_size",
            "history_count",
            "outcome",
        ],
    )
    context.horse_id = context.horse_id.astype(str)
    s = pd.read_parquet(S / "runner_predictions.parquet")
    rows = []
    w = pd.read_parquet(W / "runner_predictions.parquet")
    w = w[w.variant.eq("month_gate_weight22")].rename(columns={"raw_top3_score": "score"})
    prior = s[s.target.eq(3) & s.variant.eq("baseline22")]
    a = w.merge(prior[KEY + ["raw_score"]], on=KEY, validate="one_to_one")
    assert len(a) == len(w) == 50754 and np.allclose(a.score, a.raw_score, atol=1e-12, rtol=0)
    for name, scores in [
        ("month_gate_weight22", w[KEY + ["score"]]),
        (
            "style_history53",
            s[s.target.eq(3) & s.variant.eq("style_history")][KEY + ["raw_score"]].rename(
                columns={"raw_score": "score"}
            ),
        ),
    ]:
        g = scores.merge(context, on=KEY, validate="one_to_one")
        g["model"] = name
        g["period"] = "development_2024_2026"
        assert len(g) == 50754 and g.race_key.nunique() == 4799
        temperatures = {}
        for meet in [1, 3]:
            for year in [2024, 2025, 2026]:
                path = (
                    W / "models" / f"{meet}_{year}_month_gate_weight22/metadata.json"
                    if name == "month_gate_weight22"
                    else S / "finish_models" / f"3_style_history_{meet}_{year}/metadata.json"
                )
                temperatures[(meet, year)] = json.loads(path.read_text())["temperature"]
        g["tau"] = [temperatures[(int(m), int(y))] for m, y in zip(g.meet, g.year, strict=True)]
        rows.append(g)
    old = pd.read_parquet(P / "oof_runners.parquet")
    old = old[old.year.lt(2024)].rename(columns={"rid": "race_key", "number": "program_no"})
    g = old[KEY + ["score", "tau"]].merge(context, on=KEY, validate="one_to_one")
    g["model"] = "style_history53"
    g["period"] = "historical_2020_2023"
    assert g.race_key.nunique() == 5971
    rows.append(g)
    r = (
        pd.concat(rows, ignore_index=True)
        .sort_values(["model", "period", "race_key", "program_no"])
        .reset_index(drop=True)
    )
    r.race_date = pd.to_datetime(r.race_date).dt.strftime("%Y-%m-%d")
    return r


def card(g):
    """Selection uses scores and original numbers, never labels."""
    g = g.sort_values("program_no").reset_index(drop=True)
    n = len(g)
    programs = g.program_no.to_numpy(int)
    order = np.lexsort((programs, -g.score.to_numpy(float)))
    axis = int(order[0])
    ranks = np.empty(n, int)
    ranks[order] = np.arange(1, n + 1)
    sets = np.array(list(itertools.combinations(range(n), 3)), int)
    z = g.score.to_numpy(float) / float(g.tau.iloc[0])
    energy = np.sort(z[sets], axis=1).sum(axis=1)
    q = np.exp(energy - logsumexp(energy))
    includes_axis = np.any(sets == axis, axis=1)
    p_axis = float(q[includes_axis].sum())
    assert np.isclose(q.sum(), 1, atol=1e-12)
    selected = {}
    allowed = {}
    for policy in POLICIES:
        if policy == "global6":
            good = np.ones(len(sets), bool)
        elif policy == "axis_all":
            good = includes_axis
        else:
            max_rank = int(policy.removeprefix("axis_pool"))
            good = includes_axis & (ranks[sets].max(axis=1) <= max_rank)
        ix = np.flatnonzero(good)
        # Sets are lexicographic in the original, ascending program numbers.
        take = ix[np.argsort(-energy[ix], kind="stable")[:6]]
        assert len(take) == 6
        selected[policy] = take
        allowed[policy] = good
    return g, sets, ranks, axis, q, p_axis, selected, allowed


def evaluate(runners):
    race_rows, tickets, events = [], [], []
    for (model, period, key), g in runners.groupby(["model", "period", "race_key"], sort=True):
        g, sets, ranks, axis, q, p_axis, chosen, allowed = card(g)
        truth = np.flatnonzero(g.outcome.between(1, 3).to_numpy())
        assert len(truth) == 3
        ti = int(np.flatnonzero(np.all(sets == truth, axis=1))[0])
        axis_placed = int(axis in truth)
        p = g.program_no.to_numpy(int)
        outcomes = g.outcome.to_numpy(int)
        base_hit = int(ti in chosen["axis_pool5"])
        expanded_hit = int(ti in chosen["axis_pool7"])
        base_set = {tuple(sets[j]) for j in chosen["axis_pool5"]}
        new_set = {tuple(sets[j]) for j in chosen["axis_pool7"]}
        r = g.iloc[0]
        for policy in POLICIES:
            take = chosen[policy]
            hit = int(ti in take)
            pool_true = int(allowed[policy][ti])
            if policy == "global6":
                failure = "hit" if hit else "global_unselected"
            elif not axis_placed:
                failure = "axis_miss"
            elif not pool_true:
                failure = "companions_outside_pool"
            else:
                failure = "hit" if hit else "companions_inside_unselected"
            union = set(sets[take].ravel()) - {axis}
            race_rows.append(
                dict(
                    model=model,
                    period=period,
                    race_key=key,
                    race_date=r.race_date,
                    year=int(r.year),
                    meet=int(r.meet),
                    distance_m=float(r.distance_m),
                    grade=float(r.grade) if pd.notna(r.grade) else None,
                    field_size=len(g),
                    minimum_history=float(g.history_count.min()),
                    policy=policy,
                    axis_program=int(p[axis]),
                    axis_placed=axis_placed,
                    six_hit=hit,
                    pool_contains_truth=pool_true,
                    failure=failure,
                    p_axis=p_axis,
                    six_probability=float(q[take].sum()),
                    set_nll=float(-np.log(q[ti])),
                    distinct_companions=len(union),
                    largest_selected_rank=int(ranks[sets[take]].max()),
                    tickets_containing_rank6=int(np.any(ranks[sets[take]] == 6, axis=1).sum()),
                    tickets_containing_rank7=int(np.any(ranks[sets[take]] == 7, axis=1).sum()),
                )
            )
            for selection_rank, j in enumerate(take, 1):
                tickets.append(
                    dict(
                        model=model,
                        period=period,
                        race_key=key,
                        policy=policy,
                        selection_rank=selection_rank,
                        programs=",".join(map(str, p[sets[j]])),
                        model_ranks=",".join(map(str, sorted(ranks[sets[j]]))),
                        probability=float(q[j]),
                        hit=int(j == ti),
                    )
                )
        events.append(
            dict(
                model=model,
                period=period,
                race_key=key,
                race_date=r.race_date,
                year=int(r.year),
                meet=int(r.meet),
                axis_program=int(p[axis]),
                axis_placed=axis_placed,
                actual_programs=",".join(map(str, p[truth])),
                actual_model_ranks=",".join(map(str, sorted(ranks[truth]))),
                baseline_hit=base_hit,
                expanded_hit=expanded_hit,
                event="rescued"
                if expanded_hit and not base_hit
                else "lost"
                if base_hit and not expanded_hit
                else "both_hit"
                if base_hit
                else "both_miss",
                added_tickets=len(new_set - base_set),
                dropped_tickets=len(base_set - new_set),
                largest_actual_rank=int(ranks[truth].max()),
                axis_actual_finish=int(outcomes[axis]),
            )
        )
    return pd.DataFrame(race_rows), pd.DataFrame(tickets), pd.DataFrame(events)


def interval(frame, value, condition=False):
    if condition:
        frame = frame[frame.axis_placed.eq(1)]
    day = (
        frame.assign(_value=value.loc[frame.index]).groupby("race_date")._value.agg(["sum", "size"])
    )
    ix = np.random.default_rng(CFG["bootstrap_seed"]).integers(
        0, len(day), size=(CFG["bootstrap_draws"], len(day))
    )
    b = day["sum"].to_numpy()[ix].sum(axis=1) / day["size"].to_numpy()[ix].sum(axis=1)
    return dict(
        mean=float(value.loc[frame.index].mean()),
        lo=float(np.quantile(b, 0.025)),
        hi=float(np.quantile(b, 0.975)),
        races=len(frame),
        days=len(day),
    )


def comparison(a, b, conditional=False):
    z = a.merge(
        b[["race_key", "six_hit"]], on="race_key", suffixes=("", "_base"), validate="one_to_one"
    )
    if conditional:
        z = z[z.axis_placed.eq(1)]
    delta = z.six_hit - z.six_hit_base
    result = interval(z, delta)
    result.update(
        new_hits=int(z.six_hit.sum()),
        base_hits=int(z.six_hit_base.sum()),
        new_rate=float(z.six_hit.mean()),
        base_rate=float(z.six_hit_base.mean()),
        rescued=int(((z.six_hit == 1) & (z.six_hit_base == 0)).sum()),
        lost=int(((z.six_hit == 0) & (z.six_hit_base == 1)).sum()),
    )
    return result


def summarize(races, events):
    d = races.copy()
    d["distance_band"] = np.select(
        [d.distance_m.le(1300), d.distance_m.le(1600)],
        ["through1300", "1400_1600"],
        default="1700plus",
    )
    d["grade_band"] = np.select(
        [d.grade.eq(6), d.grade.eq(5), d.grade.between(1, 4)],
        ["grade6", "grade5", "grade1_4"],
        default="unknown",
    )
    d["field_band"] = np.select(
        [d.field_size.le(9), d.field_size.le(11)], ["6_9", "10_11"], default="12plus"
    )
    d["history_band"] = np.select(
        [d.minimum_history.eq(0), d.minimum_history.lt(5)],
        ["any_zero", "min1_4"],
        default="all5plus",
    )
    summary, paired = [], []
    for (model, period), group in d.groupby(["model", "period"]):
        groups = [("all", "all", group)]
        for col in [
            "year",
            "meet",
            "distance_band",
            "distance_m",
            "grade_band",
            "field_band",
            "history_band",
        ]:
            groups += [(col, str(k), v) for k, v in group.groupby(col, dropna=False)]
        for scope, value, g in groups:
            base = g[g.policy.eq("axis_pool5")]
            for policy, one in g.groupby("policy"):
                conditional = one[one.axis_placed.eq(1)]
                summary.append(
                    dict(
                        model=model,
                        period=period,
                        scope=scope,
                        value=value,
                        policy=policy,
                        races=len(one),
                        days=one.race_date.nunique(),
                        small_sample=bool(
                            len(one) < CFG["subgroup_support"]["min_races"]
                            or one.race_date.nunique() < CFG["subgroup_support"]["min_days"]
                        ),
                        hits=int(one.six_hit.sum()),
                        hit_rate=float(one.six_hit.mean()),
                        axis_rate=float(one.axis_placed.mean()),
                        companion_given_axis=float(conditional.six_hit.mean()),
                        axis_places=len(conditional),
                        pool_ceiling=float(one.pool_contains_truth.mean()),
                        forecast_mean=float(one.six_probability.mean()),
                        nll=float(one.set_nll.mean()),
                        mean_companions=float(one.distinct_companions.mean()),
                        changed_rank6_tickets=float(one.tickets_containing_rank6.mean()),
                        changed_rank7_tickets=float(one.tickets_containing_rank7.mean()),
                    )
                )
                if policy == "axis_pool5":
                    continue
                if policy == "axis_pool7" or scope in ["all", "year", "meet"]:
                    for cond in [False, True] if policy.startswith("axis_") else [False]:
                        paired.append(
                            dict(
                                model=model,
                                period=period,
                                scope=scope,
                                value=value,
                                policy=policy,
                                metric="companion_given_axis" if cond else "six_hit",
                                baseline="axis_pool5",
                                **comparison(one, base, cond),
                            )
                        )
    pd.DataFrame(summary).to_csv(OUT / "summary.csv", index=False)
    pd.DataFrame(paired).to_csv(OUT / "paired_differences.csv", index=False)
    failures = (
        races.groupby(["model", "period", "policy", "failure"]).size().rename("races").reset_index()
    )
    failures.to_csv(OUT / "failure_decomposition.csv", index=False)
    events.groupby(["model", "period", "event", "largest_actual_rank"]).size().rename(
        "races"
    ).reset_index().to_csv(OUT / "capture_by_rank.csv", index=False)
    bins = []
    for (model, period, policy), one in races.groupby(["model", "period", "policy"]):
        for label, g in one.groupby(
            pd.cut(one.six_probability, np.linspace(0, 1, 11), include_lowest=True), observed=True
        ):
            bins.append(
                dict(
                    model=model,
                    period=period,
                    policy=policy,
                    band=str(label),
                    races=len(g),
                    forecast=float(g.six_probability.mean()),
                    actual=float(g.six_hit.mean()),
                )
            )
    pd.DataFrame(bins).to_csv(OUT / "calibration_bins.csv", index=False)


def bridge(key):
    key = key.replace("RACE:SEOUL:", "1:").replace("RACE:BUSAN:", "3:")
    first, last = key.rsplit(":", 1)
    return first + ":" + str(int(last))


def operating(runners, races):
    old = pd.read_parquet(OP / "operating_runner_predictions.parquet")
    reference = pd.read_csv(OP / "race_diagnostics.csv")
    reference = reference[reference.variant.eq("operating_exact_2026")].copy()
    new = runners[
        (runners.model == "month_gate_weight22") & (runners.period == "development_2024_2026")
    ]

    def keys(g):
        outcome = g.outcome.where(g.outcome.between(1, 20), 0).astype(int)
        return frozenset(
            zip(g.program_no.astype(int), g.horse_id.astype(str), outcome, strict=True)
        )

    ns = {key: keys(g) for key, g in new.groupby("race_key")}
    os = {key: keys(g) for key, g in old.groupby("race_key")}
    mapping = {key: bridge(key) for key in os if bridge(key) in ns and os[key] == ns[bridge(key)]}
    assert len(mapping) == 1258
    reference["aligned_key"] = reference.race_key.map(mapping)
    reference = reference[reference.aligned_key.notna()]
    rows = []
    aligned_metrics = []
    for (model, policy), g in races[races.period.eq("development_2024_2026")].groupby(
        ["model", "policy"]
    ):
        a = g.merge(
            reference[["aligned_key", "trio6_hit"]],
            left_on="race_key",
            right_on="aligned_key",
            validate="one_to_one",
        )
        assert len(a) == 1258
        a["operating_hit"] = a.trio6_hit.astype(int)
        aligned_metrics.append(a)
        for meet in [0, 1, 3]:
            z = a if meet == 0 else a[a.meet.eq(meet)]
            delta = z.six_hit - z.operating_hit
            result = interval(z, delta)
            rows.append(
                dict(
                    model=model,
                    policy=policy,
                    meet=meet,
                    new_rate=float(z.six_hit.mean()),
                    operating_rate=float(z.operating_hit.mean()),
                    **result,
                )
            )
    pd.DataFrame(rows).to_csv(OUT / "operating_comparisons.csv", index=False)
    pd.concat(aligned_metrics, ignore_index=True).to_csv(
        OUT / "operating_matched_metrics.csv", index=False
    )
    save(
        OUT / "operating_alignment.json",
        dict(
            matched=1258,
            mapping=mapping,
            matching=(
                "same entire horse ID/program/normal finish codes; "
                "non-normal=0 for matching only"
            ),
            operating_selection_different=True,
        ),
    )


def main():
    OUT.mkdir(exist_ok=False)
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in refs()})
    assert (
        json.loads((W / "research_baseline_selection.json").read_text())["variant"]
        == "month_gate_weight22"
    )
    assert json.loads((P / "final_verification.json").read_text())["passed"]
    runners = load()
    runners.to_parquet(OUT / "runner_inputs.parquet", index=False)
    races, tickets, events = evaluate(runners)
    races.to_csv(OUT / "race_metrics.csv", index=False)
    tickets.to_parquet(OUT / "six_tickets.parquet", index=False)
    events.to_csv(OUT / "capture_events.csv", index=False)
    summarize(races, events)
    operating(runners, races)
    check()
    save(
        OUT / "completion.json",
        dict(
            new_model_fits=0,
            new_calibrations=0,
            selection_changed=False,
            operating_changed=False,
            database_opened=False,
            jeju_accessed=False,
            evaluation_rows=len(races),
            artifact_hashes={p.name: sha(p) for p in OUT.iterdir() if p.is_file()},
        ),
    )
    print(
        pd.read_csv(OUT / "summary.csv").query('scope == "all"').to_string(index=False), flush=True
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    main()
