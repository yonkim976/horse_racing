"""Pre-race failure clusters and low-ranked podium signals on frozen predictions."""

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from sklearn.cluster import KMeans

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = R.parents[1]
OUT = HERE / "outputs"
S = R / "20261009_section_style_finish_v1/outputs"
V = R / "20261009_axis_pool_validation_v1/outputs"
P = R / "20261009_pair_trio_budget_v1/outputs"
KEY = ["race_key", "program_no", "horse_id"]
SEED = 20261009


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def check():
    for p, h in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / p) == h, p


def prepare():
    pred = pd.read_parquet(V / "runner_inputs.parquet")
    pred = pred[pred.year.ge(2024)]
    base = pred[pred.model.eq("month_gate_weight22")].drop(columns=["model", "period"])
    candidate = pred[pred.model.eq("style_history53")].copy()
    candidate = candidate.sort_values(
        ["race_key", "score", "program_no"], ascending=[True, False, True]
    )
    candidate["rank53"] = candidate.groupby("race_key").cumcount() + 1
    history = pd.read_parquet(S / "features.parquet")
    cols = [
        "race_no",
        "horse_name",
        "history_source_date",
        "cutoff_date",
        "profile_source_date",
        "previous_age",
        "previous_sex",
        "days_since_last",
        "moist_last3_record_index_mean",
        "moist_last5_record_index_best",
        "moist_last5_record_index_count",
        "profile_trend",
        "profile_std5",
        "current_vs_previous_carried_weight",
        "section_previous_distance",
        "section_same_distance_n5",
        "section_early_mean3",
        "section_early_n5",
        "section_last600_mean3",
        "section_last600_n5",
        "section_late_mean3",
        "section_late_n5",
        "style_role0_rate5",
        "style_role_n5",
        "style_recovery_mean5",
        "style_recovery_n5",
        "style_fade_mean5",
    ]
    f = base.merge(history[KEY + cols], on=KEY, validate="one_to_one")
    f = f.merge(candidate[KEY + ["rank53"]], on=KEY, validate="one_to_one")
    f = f.sort_values(
        ["race_date", "race_key", "score", "program_no"], ascending=[True, True, False, True]
    ).reset_index(drop=True)
    f["model_rank"] = f.groupby("race_key").cumcount() + 1
    f["top3"] = f.outcome.between(1, 3).astype(int)
    f["prob_top3"] = np.nan
    for _, ix in f.groupby("race_key", sort=False).indices.items():
        g = f.iloc[ix]
        combos = np.array(list(itertools.combinations(range(len(g)), 3)))
        energy = np.sort((g.score.to_numpy() / g.tau.iloc[0])[combos], axis=1).sum(axis=1)
        q = np.exp(energy - logsumexp(energy))
        marginal = np.zeros(len(g))
        for j in range(3):
            np.add.at(marginal, combos[:, j], q)
        f.loc[ix, "prob_top3"] = marginal
    for source, name, ascending in [
        ("section_early_mean3", "early_pct", False),
        ("section_last600_mean3", "g3f_pct", False),
        ("section_late_mean3", "g1f_pct", False),
        ("moist_last5_record_index_best", "best_pct", True),
        ("moist_last3_record_index_mean", "recent_pct", True),
    ]:
        f[name] = f.groupby("race_key")[source].rank(
            method="average", ascending=ascending, pct=True
        )
    f["distance_delta"] = f.distance_m - f.section_previous_distance
    f["rest_log"] = np.log1p(f.days_since_last)
    f["best_recent_gap"] = f.moist_last5_record_index_best - f.moist_last3_record_index_mean
    f["section_support"] = (
        f[["section_early_n5", "section_last600_n5", "section_late_n5"]].min(axis=1) / 5
    )
    f["distance_band"] = pd.cut(
        f.distance_m, [-1, 1300, 1600, 10000], labels=["short", "middle", "long"]
    ).astype(str)
    f["grade_band"] = np.select(
        [f.grade.eq(6), f.grade.eq(5), f.grade.between(1, 4)], ["6", "5", "1_4"], default="other"
    )
    f["field_band"] = pd.cut(
        f.field_size, [0, 9, 11, 100], labels=["6_9", "10_11", "12plus"]
    ).astype(str)
    f["rank_band"] = pd.cut(
        f.model_rank, [0, 5, 7, 9, 100], labels=["top5", "6_7", "8_9", "10plus"]
    ).astype(str)
    f["recent_gap"] = f.moist_last3_record_index_mean - f.groupby(
        "race_key"
    ).moist_last3_record_index_mean.transform("mean")
    f.to_parquet(OUT / "runner_inputs.parquet", index=False)
    metrics = pd.read_csv(V / "race_metrics.csv")
    metrics = metrics[metrics.period.eq("development_2024_2026") & metrics.policy.eq("global6")]
    b = metrics[metrics.model.eq("month_gate_weight22")].set_index("race_key")
    c = metrics[metrics.model.eq("style_history53")].set_index("race_key")
    bets = pd.read_parquet(P / "race_metrics.parquet")
    bets = bets[bets.policy.eq("global6")].pivot(index="race_key", columns="bet", values="hit")
    rows = []
    for rid, g in f.groupby("race_key", sort=False):
        a = g.iloc[0]
        w = g[g.top3.eq(1)]
        rows.append(
            dict(
                race_key=rid,
                race_date=a.race_date,
                year=int(a.year),
                meet=int(a.meet),
                distance_m=a.distance_m,
                grade=a.grade,
                field_size=len(g),
                mean_history=g.history_count.mean(),
                few_history_fraction=g.history_count.le(2).mean(),
                zero_history_fraction=g.history_count.eq(0).mean(),
                changed_distance_fraction=g.distance_delta.abs().ge(200).mean(),
                front_mass=g.style_role0_rate5.where(g.style_role_n5.ge(3)).mean(),
                late_support=g.section_support.ge(0.6).mean(),
                axis_prob=float(b.loc[rid, "p_axis"]),
                six_probability=float(b.loc[rid, "six_probability"]),
                gap12=float((g.score.iloc[0] - g.score.iloc[1]) / a.tau),
                hit_trio=int(bets.loc[rid, "trio"]),
                hit_qpl=int(bets.loc[rid, "quinella_place"]),
                hit_quinella=int(bets.loc[rid, "quinella"]),
                hit53=int(c.loc[rid, "six_hit"]),
                outside5_count=int(w.model_rank.gt(5).sum()),
                worst_winner_rank=int(w.model_rank.max()),
                axis_miss=int(a.top3 == 0),
                distance_band=a.distance_band,
                grade_band=a.grade_band,
                field_band=a.field_band,
            )
        )
    races = pd.DataFrame(rows)
    races["trio_fail"] = 1 - races.hit_trio
    races["trio_fail_residual"] = races.six_probability - races.hit_trio
    races["failure_kind"] = np.select(
        [races.hit_trio.eq(1), races.outside5_count.ge(2), races.outside5_count.eq(1)],
        ["hit", "two_or_more_outside5", "one_outside5"],
        default="inside5_unselected",
    )
    races.to_parquet(OUT / "race_inputs.parquet", index=False)
    racecols = [
        "distance_m",
        "grade",
        "field_size",
        "mean_history",
        "few_history_fraction",
        "zero_history_fraction",
        "changed_distance_fraction",
        "front_mass",
        "late_support",
        "axis_prob",
        "six_probability",
        "gap12",
    ]
    horsecols = [
        "history_count",
        "rest_log",
        "distance_delta",
        "current_vs_previous_carried_weight",
        "profile_trend",
        "profile_std5",
        "recent_gap",
        "best_recent_gap",
        "best_pct",
        "early_pct",
        "g3f_pct",
        "g1f_pct",
        "style_role0_rate5",
        "style_recovery_mean5",
        "style_fade_mean5",
        "section_support",
        "previous_age",
    ]
    save(
        OUT / "feature_contract.json",
        dict(
            race_cluster=racecols,
            runner_cluster=horsecols,
            clustering_fit_year=2024,
            low_rank_definition="model_rank>=6",
            forbidden=["outcome", "top3", "hit_trio", "axis_miss"],
        ),
    )
    return f, races, racecols, horsecols


def cluster(frame, cols, k, name):
    train = frame.year.eq(2024)
    x = frame[cols].to_numpy(float)
    lo = np.nanquantile(x[train], 0.01, axis=0)
    hi = np.nanquantile(x[train], 0.99, axis=0)
    median = np.nanmedian(x[train], axis=0)
    missing = np.isnan(x)
    missingcols = np.flatnonzero(missing[train].any(axis=0))
    z = np.where(missing, median, np.clip(x, lo, hi))
    z = np.column_stack([z, missing[:, missingcols].astype(float)])
    mean = z[train].mean(axis=0)
    std = z[train].std(axis=0)
    std[std == 0] = 1
    scaled = (z - mean) / std
    km = KMeans(n_clusters=k, random_state=SEED, n_init=20).fit(scaled[train])
    assignments = km.predict(scaled)
    save(
        OUT / (name + "_clusters.json"),
        dict(
            features=cols,
            clusters=k,
            fit_year=2024,
            seed=SEED,
            n_init=20,
            lower=lo.tolist(),
            upper=hi.tolist(),
            median=median.tolist(),
            missingcols=missingcols.tolist(),
            mean=mean.tolist(),
            std=std.tolist(),
            centers=km.cluster_centers_.tolist(),
        ),
    )
    return assignments


def flags(frame):
    f = frame
    return dict(
        few_history=f.history_count.le(2),
        long_rest=f.days_since_last.ge(56),
        distance_changed=f.distance_delta.abs().ge(200),
        weight_drop=f.current_vs_previous_carried_weight.le(-2),
        improving=f.profile_trend.ge(0.5),
        variable_record=f.profile_std5.ge(1),
        best_topthird=f.best_pct.ge(2 / 3) & f.moist_last5_record_index_count.ge(3),
        late_both_topthird=f.g3f_pct.ge(2 / 3)
        & f.g1f_pct.ge(2 / 3)
        & f.section_last600_n5.ge(3)
        & f.section_late_n5.ge(3),
        early_topthird=f.early_pct.ge(2 / 3) & f.section_early_n5.ge(3),
        front_often=f.style_role0_rate5.ge(0.6) & f.style_role_n5.ge(3),
        recover_often=f.style_recovery_mean5.ge(0.4) & f.style_recovery_n5.ge(3),
        sparse_sections=f.section_support.lt(0.6),
    )


def bootstrap_diff(frame, mask, value):
    z = pd.DataFrame(
        dict(date=frame.race_date, group=mask.to_numpy().astype(int), value=value.to_numpy())
    )
    ag = z.groupby(["date", "group"]).value.agg(["sum", "count"]).unstack(fill_value=0)
    for key in [("sum", 0), ("sum", 1), ("count", 0), ("count", 1)]:
        if key not in ag:
            ag[key] = 0
    rng = np.random.default_rng(SEED)
    ix = rng.integers(0, len(ag), size=(2000, len(ag)))
    gs = ag["sum", 1].to_numpy()[ix].sum(1)
    gn = ag["count", 1].to_numpy()[ix].sum(1)
    cs = ag["sum", 0].to_numpy()[ix].sum(1)
    cn = ag["count", 0].to_numpy()[ix].sum(1)
    draws = gs / np.maximum(gn, 1) - cs / np.maximum(cn, 1)
    return *np.quantile(draws, [0.025, 0.975]).tolist(), float(np.std(draws))


def runner_summary(frame, mask, name, period, with_ci=False):
    g = frame[mask]
    control = frame[~mask]
    if len(g) == 0 or len(control) == 0:
        return None
    residual = frame.top3 - frame.prob_top3
    difference = float(residual[mask].mean() - residual[~mask].mean())
    rec = dict(
        condition=name,
        period=period,
        runners=len(g),
        actual_top3=int(g.top3.sum()),
        actual_rate=float(g.top3.mean()),
        predicted_rate=float(g.prob_top3.mean()),
        excess=float((g.top3 - g.prob_top3).mean()),
        control_rate=float(control.top3.mean()),
        excess_difference=difference,
        upgraded53_winners=int((g.top3.eq(1) & g.rank53.le(5)).sum()),
    )
    # Standardize controls to the group's overlapping condition-cell composition.
    strata = ["year", "meet", "distance_band", "grade_band", "field_band", "rank_band"]
    z = frame[strata + ["top3"]].copy()
    z["member"] = mask.to_numpy()
    cells = z.groupby(strata + ["member"]).top3.agg(["sum", "count"]).unstack(fill_value=0)
    if ("count", False) in cells and ("count", True) in cells:
        supported = cells[("count", False)].ge(3) & cells[("count", True)].ge(3)
        s = cells[supported]
        n = float(s[("count", True)].sum())
        if n > 0:
            actual = float(s[("sum", True)].sum() / n)
            matched_control = float(
                ((s[("sum", False)] / s[("count", False)]) * s[("count", True)]).sum() / n
            )
            rec.update(
                matched_runners=int(n),
                matched_actual_rate=actual,
                matched_control_rate=matched_control,
                matched_difference=actual - matched_control,
            )
    if with_ci and len(g) >= 30:
        lo, hi, sd = bootstrap_diff(frame, mask, residual)
        rec.update(excess_difference_ci_low=lo, excess_difference_ci_high=hi, bootstrap_sd=sd)
    return rec


def runner_analysis(f, cols):
    low = f[f.model_rank.ge(6)].copy().reset_index(drop=True)
    low["cluster"] = cluster(low, cols, 5, "runner")
    low.to_parquet(OUT / "low_rank_runners.parquet", index=False)
    baseflags = flags(low)
    rules = dict(baseflags)
    for a, b in itertools.combinations(baseflags, 2):
        rules[a + " & " + b] = baseflags[a] & baseflags[b]
    discovery = []
    d = low.year.eq(2024)
    for name, mask in rules.items():
        rec = runner_summary(
            low[d].reset_index(drop=True), mask[d].reset_index(drop=True), name, "2024"
        )
        if rec:
            discovery.append(rec)
    disc = pd.DataFrame(discovery)
    disc["selection_score"] = disc.excess_difference.clip(lower=0) * np.sqrt(disc.runners)
    eligible = disc[
        (disc.runners >= 80)
        & (disc.actual_top3 >= 8)
        & (disc.excess > 0)
        & (disc.excess_difference > 0)
    ]
    selected = (
        eligible.sort_values(["selection_score", "condition"], ascending=[False, True])
        .head(6)
        .condition.tolist()
    )
    save(
        OUT / "selected_conditions.json",
        dict(
            discovery_year=2024,
            conditions=selected,
            criteria="n>=80, podium>=8, positive excess and relative excess; top6 diff*sqrt(n)",
        ),
    )
    disc.to_csv(OUT / "discovery_conditions.csv", index=False)
    summaries = []
    for period, periodmask in [
        ("all", low.year.ge(2024)),
        ("2024", low.year.eq(2024)),
        ("2025", low.year.eq(2025)),
        ("2026", low.year.eq(2026)),
        ("2025_2026", low.year.ge(2025)),
    ]:
        one = low[periodmask].reset_index(drop=True)
        conditions = {
            n: rules[n][periodmask].reset_index(drop=True)
            for n in sorted(set(selected) | set(baseflags))
        }
        conditions.update({f"cluster_{i}": one.cluster.eq(i) for i in range(5)})
        for name, mask in conditions.items():
            rec = runner_summary(
                one, mask, name, period, with_ci=(name in selected or name.startswith("cluster_"))
            )
            if rec:
                summaries.append(rec)
    pd.DataFrame(summaries).to_csv(OUT / "runner_condition_summary.csv", index=False)
    profiles = (
        low.groupby(["year", "cluster"])[cols + ["prob_top3", "top3", "model_rank"]]
        .mean()
        .reset_index()
    )
    profiles.to_csv(OUT / "runner_cluster_profiles.csv", index=False)
    return low


def race_analysis(f, cols):
    f = f.copy()
    f["cluster"] = cluster(f, cols, 4, "race")
    f.to_parquet(OUT / "clustered_races.parquet", index=False)
    groups = {f"cluster_{i}": f.cluster.eq(i) for i in range(4)}
    for field in ["field_band", "distance_band", "grade_band"]:
        groups.update({field + "_" + str(v): f[field].eq(v) for v in sorted(f[field].unique())})
    groups.update(
        many_inexperienced=f.few_history_fraction.ge(0.25),
        no_inexperienced=f.few_history_fraction.eq(0),
        many_distance_changes=f.changed_distance_fraction.ge(0.5),
        many_front=f.front_mass.ge(0.4),
        low_axis_probability=f.axis_prob.lt(0.5),
    )
    rows = []
    for period, mask in [
        ("all", f.year.ge(2024)),
        ("2024", f.year.eq(2024)),
        ("2025", f.year.eq(2025)),
        ("2026", f.year.eq(2026)),
        ("2025_2026", f.year.ge(2025)),
    ]:
        one = f[mask].reset_index(drop=True)
        for name, membership in groups.items():
            member = membership[mask].reset_index(drop=True)
            g = one[member]
            if len(g) == 0 or len(g) == len(one):
                continue
            rec = dict(
                condition=name,
                period=period,
                races=len(g),
                trio_failure_rate=float(g.trio_fail.mean()),
                expected_trio_failure=float((1 - g.six_probability).mean()),
                failure_excess=float(g.trio_fail_residual.mean()),
                qpl_failure_rate=float((1 - g.hit_qpl).mean()),
                quinella_failure_rate=float((1 - g.hit_quinella).mean()),
                outside5_failure_share=float(
                    g.loc[g.trio_fail.eq(1), "outside5_count"].gt(0).mean()
                ),
                axis_miss_rate=float(g.axis_miss.mean()),
                candidate53_delta=float((g.hit53 - g.hit_trio).mean()),
            )
            if name.startswith("cluster_") and len(g) >= 30:
                residual = one.trio_fail_residual
                rec["excess_difference"] = float(residual[member].mean() - residual[~member].mean())
                lo, hi, sd = bootstrap_diff(one, member, residual)
                rec.update(
                    excess_difference_ci_low=lo, excess_difference_ci_high=hi, bootstrap_sd=sd
                )
            rows.append(rec)
    pd.DataFrame(rows).to_csv(OUT / "race_condition_summary.csv", index=False)
    f.groupby(["year", "cluster"])[cols + ["trio_fail", "axis_miss"]].mean().reset_index().to_csv(
        OUT / "race_cluster_profiles.csv", index=False
    )
    f.groupby(["year", "failure_kind"]).size().rename("races").reset_index().to_csv(
        OUT / "failure_decomposition.csv", index=False
    )
    return f


def main():
    OUT.mkdir(exist_ok=True)
    refs = [HERE / n for n in ["PLAN.md", "run.py", "verify.py"]] + [
        V / n for n in ["runner_inputs.parquet", "race_metrics.csv", "verification.json"]
    ]
    refs += [
        S / "features.parquet",
        P / "race_metrics.parquet",
        ROOT / "config/prediction_model_registry.json",
        R / "20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json",
    ]
    assert not (OUT / "source_lock.json").exists()
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in refs})
    f, r, rc, hc = prepare()
    print("Prepared", len(f), len(r), flush=True)
    runner_analysis(f, hc)
    print("Runner analysis complete", flush=True)
    race_analysis(r, rc)
    check()
    print("Race analysis complete", flush=True)


if __name__ == "__main__":
    main()
