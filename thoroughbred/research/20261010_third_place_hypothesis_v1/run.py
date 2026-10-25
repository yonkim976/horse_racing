"""Finish-place difficulty and favorite-collapse hypotheses on frozen scores."""

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
V = R / "20261009_axis_pool_validation_v1/outputs"
S = R / "20261009_section_style_finish_v1/outputs"
OP = R / "20261004_close_contenders_v1/outputs"
W = R / "20261008_profile_carried_weight_v1/outputs"
KEY = ["race_key", "program_no", "horse_id"]
SEED = 20261010


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def check():
    for path, expected in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / path) == expected, path


def refs():
    return (
        [HERE / n for n in ["PLAN.md", "run.py", "verify.py"]]
        + [V / n for n in ["runner_inputs.parquet", "verification.json"]]
        + [S / n for n in ["features.parquet", "verification.json"]]
        + [OP / n for n in ["operating_runner_predictions.parquet", "verification.json"]]
        + [W / "research_baseline_selection.json", ROOT / "config/prediction_model_registry.json"]
    )


def load():
    p = pd.read_parquet(V / "runner_inputs.parquet")
    p = p[p.year.ge(2024)].rename(columns={"score": "score", "model": "variant"})
    p["outcome"] = p.outcome.where(p.outcome.between(1, 20), 0).astype(int)
    p["prob_top3"] = np.nan
    for _, ix in p.groupby(["variant", "race_key"], sort=False).indices.items():
        g = p.iloc[ix]
        w = np.exp(g.score.to_numpy() / g.tau.iloc[0] - (g.score.to_numpy() / g.tau.iloc[0]).max())
        rest = w.sum() - w
        value = w * (rest**2 - (np.square(w).sum() - w**2)) / 2
        p.loc[p.index[ix], "prob_top3"] = value / (value.sum() / 3)
    op = pd.read_parquet(OP / "operating_runner_predictions.parquet")
    op["outcome"] = op.outcome.where(op.outcome.between(1, 20), 0).astype(int)
    op["original_race_key"] = op.race_key
    op["race_key"] = [
        f"{int(m)}:{str(d).replace('-', '')}:{int(str(k).rsplit(':', 1)[1])}"
        for m, d, k in zip(op.meet, op.race_date, op.race_key, strict=True)
    ]
    base = p[p.variant.eq("month_gate_weight22")]
    available = {
        k: set(zip(g.program_no, g.horse_id.astype(str), g.outcome.astype(int), strict=True))
        for k, g in base.groupby("race_key")
    }
    matched = []
    excluded = []
    for rid, g in op.groupby("race_key"):
        signature = set(
            zip(g.program_no, g.horse_id.astype(str), g.outcome.astype(int), strict=True)
        )
        (matched if available.get(rid) == signature else excluded).append(rid)
    assert len(matched) == 1258
    op = op[op.race_key.isin(matched)].copy()
    op["variant"] = "operating_snapshot2026"
    op["score"] = op.prob_top3
    op["tau"] = np.nan
    op["year"] = pd.to_datetime(op.race_date).dt.year
    op = op.merge(
        base[KEY + ["distance_m", "grade", "history_count"]], on=KEY, validate="one_to_one"
    )
    cols = KEY + [
        "variant",
        "score",
        "tau",
        "prob_top3",
        "meet",
        "race_date",
        "year",
        "outcome",
        "field_size",
        "distance_m",
        "grade",
        "history_count",
    ]
    p = (
        pd.concat([p[cols], op[cols]], ignore_index=True)
        .sort_values(
            ["variant", "race_key", "score", "program_no"], ascending=[True, True, False, True]
        )
        .reset_index(drop=True)
    )
    p["model_rank"] = p.groupby(["variant", "race_key"]).cumcount() + 1
    p["matched_2026"] = p.race_key.isin(matched)
    context = pd.read_parquet(S / "features.parquet")
    features = [
        "horse_name",
        "history_source_date",
        "profile_source_date",
        "cutoff_date",
        "moist_last3_record_index_mean",
        "moist_last5_record_index_best",
        "moist_last5_record_index_count",
        "profile_count3",
        "section_last600_mean3",
        "section_last600_n5",
        "section_late_mean3",
        "section_late_n5",
        "style_recovery_mean5",
        "style_recovery_n5",
    ]
    context = context[context.year.ge(2024)].copy()
    for source, name, ascending in [
        ("moist_last3_record_index_mean", "recent_percentile", True),
        ("moist_last5_record_index_best", "best_percentile", True),
        ("section_last600_mean3", "g3f_percentile", False),
        ("section_late_mean3", "g1f_percentile", False),
    ]:
        context[name] = context.groupby("race_key")[source].rank(
            ascending=ascending, pct=True, method="average"
        )
        features.append(name)
    p = p.merge(context[KEY + features], on=KEY, validate="many_to_one")
    p["late_recovery"] = (
        p.g3f_percentile.ge(2 / 3)
        & p.g1f_percentile.ge(2 / 3)
        & p.section_last600_n5.ge(3)
        & p.section_late_n5.ge(3)
        & p.style_recovery_mean5.ge(0.4)
        & p.style_recovery_n5.ge(3)
    )
    save(
        OUT / "cohort.json",
        dict(
            research_races=4799,
            research_runners_per_model=50754,
            operating_original_races=1265,
            matched_races=len(matched),
            excluded_operating_races=excluded,
            source_end=str(p.race_date.max()),
            operating_is_frozen_reinference=True,
        ),
    )
    p.to_parquet(OUT / "runners.parquet", index=False)
    return p


def boot(frame, values):
    daily = (
        pd.DataFrame(dict(date=frame.race_date.to_numpy(), value=np.asarray(values, float)))
        .groupby("date")
        .value.agg(["sum", "size"])
    )
    ix = np.random.default_rng(SEED).integers(0, len(daily), (2000, len(daily)))
    estimates = daily["sum"].to_numpy()[ix].sum(1) / daily["size"].to_numpy()[ix].sum(1)
    return np.quantile(estimates, [0.025, 0.975]).tolist()


def group_difference(frame, member, column):
    # Re-sample dates as shared blocks while retaining both observed groups.
    z = pd.DataFrame(
        dict(date=frame.race_date, member=np.asarray(member, int), value=frame[column])
    )
    by = z.groupby(["date", "member"]).value.agg(["sum", "size"]).unstack(fill_value=0)
    ix = np.random.default_rng(SEED).integers(0, len(by), (2000, len(by)))
    means = []
    for group in [1, 0]:
        means.append(
            by["sum", group].to_numpy()[ix].sum(1)
            / np.maximum(by["size", group].to_numpy()[ix].sum(1), 1)
        )
    return np.quantile(means[0] - means[1], [0.025, 0.975]).tolist()


def race_table(p):
    rows = []
    for (variant, rid), g in p.groupby(["variant", "race_key"], sort=True):
        g = g.sort_values("program_no").reset_index(drop=True)
        winners = g[g.outcome.between(1, 3)].set_index("outcome")
        assert set(winners.index) == {1, 2, 3}
        axis = g.loc[g.model_rank.idxmin()]
        axis_out = int(not 1 <= axis.outcome <= 3)
        record = dict(
            variant=variant,
            race_key=rid,
            race_date=axis.race_date,
            year=int(axis.year),
            meet=int(axis.meet),
            distance_m=float(axis.distance_m),
            grade=float(axis.grade) if pd.notna(axis.grade) else None,
            field_size=len(g),
            matched_2026=bool(axis.matched_2026),
            axis_out=axis_out,
            axis_probability=float(axis.prob_top3),
            top2_placed=int(g[g.model_rank.le(2)].outcome.between(1, 3).sum()),
        )
        for place in [1, 2, 3]:
            row = winners.loc[place]
            record[f"rank{place}"] = int(row.model_rank)
            record[f"outside{place}"] = int(row.model_rank >= 6)
            record[f"prob{place}"] = float(row.prob_top3)
        record["outside_count"] = sum(record[f"outside{j}"] for j in [1, 2, 3])
        record["miss_pattern"] = (
            "-".join(str(j) for j in [1, 2, 3] if record[f"outside{j}"]) or "none"
        )
        record["second_vs_third_correct"] = int(record["rank2"] < record["rank3"])
        record["first_vs_second_correct"] = int(record["rank1"] < record["rank2"])
        record["first_vs_third_correct"] = int(record["rank1"] < record["rank3"])
        if variant != "operating_snapshot2026":
            sets = np.array(list(itertools.combinations(range(len(g)), 3)), int)
            energy = np.sort((g.score.to_numpy() / g.tau.iloc[0])[sets], axis=1).sum(1)
            q = np.exp(energy - logsumexp(energy))
            axis_i = int(np.flatnonzero(g.model_rank.eq(1).to_numpy())[0])
            contains_axis = (sets == axis_i).any(1)
            n_outside = (g.model_rank.to_numpy()[sets] >= 6).sum(1)
            record["expected_outside_axis_in"] = float(
                q[contains_axis] @ n_outside[contains_axis] / q[contains_axis].sum()
            )
            record["expected_outside_axis_out"] = float(
                q[~contains_axis] @ n_outside[~contains_axis] / q[~contains_axis].sum()
            )
            record["expected_outside_observed_state"] = record[
                "expected_outside_axis_out" if axis_out else "expected_outside_axis_in"
            ]
            truth = np.flatnonzero(g.outcome.between(1, 3).to_numpy())
            truth_i = int(np.flatnonzero((sets == truth).all(1))[0])
            take = np.argsort(-energy, kind="stable")[:6]
            record["trio6"] = int(truth_i in take)
        rows.append(record)
    r = pd.DataFrame(rows)
    r["distance_band"] = pd.cut(
        r.distance_m, [-1, 1300, 1600, 10000], labels=["short", "middle", "long"]
    ).astype(str)
    r["field_band"] = pd.cut(
        r.field_size, [0, 9, 11, 100], labels=["6_9", "10_11", "12plus"]
    ).astype(str)
    r["grade_band"] = np.select(
        [r.grade.eq(6), r.grade.eq(5), r.grade.between(1, 4)], ["6", "5", "1_4"], default="other"
    )
    r["axis_probability_band"] = pd.cut(
        r.axis_probability,
        [-1, 0.5, 0.6, 0.7, 2],
        right=False,
        labels=["under50", "50_60", "60_70", "70plus"],
    ).astype(str)
    r.to_parquet(OUT / "races.parquet", index=False)
    return r


def windows(r):
    yield "full", "all", r
    for year, g in r.groupby("year"):
        yield "full", str(year), g
    if r.matched_2026.any():
        yield "matched_2026", "all", r[r.matched_2026]


def analyze(p, r):
    positions, differences, collapse, patterns, matched, mechanics = [], [], [], [], [], []
    for variant, model in r.groupby("variant"):
        for cohort, period, one in windows(model):
            for place in [1, 2, 3]:
                rank = one[f"rank{place}"]
                horses = p[
                    p.variant.eq(variant) & p.race_key.isin(one.race_key) & p.outcome.eq(place)
                ]
                rec = dict(
                    variant=variant,
                    cohort=cohort,
                    period=period,
                    actual_place=place,
                    races=len(one),
                    mean_model_rank=float(rank.mean()),
                    median_model_rank=float(rank.median()),
                    mean_top3_probability=float(one[f"prob{place}"].mean()),
                    late_recovery_rate=float(horses.late_recovery.mean()),
                )
                for k in [3, 5, 7]:
                    rec[f"top{k}_hits"] = int(rank.le(k).sum())
                    rec[f"top{k}_capture"] = float(rank.le(k).mean())
                for name, support in [
                    ("recent_percentile", horses.profile_count3.ge(3)),
                    ("best_percentile", horses.moist_last5_record_index_count.ge(3)),
                ]:
                    supported = horses[support & horses[name].notna()]
                    rec[name + "_n"] = len(supported)
                    rec[name + "_mean"] = float(supported[name].mean())
                    rec[name + "_topthird"] = float(supported[name].ge(2 / 3).mean())
                positions.append(rec)
            for earlier in [1, 2]:
                for metric in ["rank", "top5_capture"]:
                    delta = (
                        one.rank3 - one[f"rank{earlier}"]
                        if metric == "rank"
                        else one.rank3.le(5).astype(int) - one[f"rank{earlier}"].le(5).astype(int)
                    )
                    lo, hi = boot(one, delta)
                    differences.append(
                        dict(
                            variant=variant,
                            cohort=cohort,
                            period=period,
                            comparison=f"third_minus_{earlier}",
                            metric=metric,
                            races=len(one),
                            difference=float(delta.mean()),
                            ci_low=lo,
                            ci_high=hi,
                        )
                    )
            conditions = {
                "axis_placed": one.axis_out.eq(0),
                "axis_out": one.axis_out.eq(1),
                "strong_axis_placed": one.axis_probability.ge(0.6) & one.axis_out.eq(0),
                "strong_axis_out": one.axis_probability.ge(0.6) & one.axis_out.eq(1),
            }
            conditions.update({f"top2_placed_{i}": one.top2_placed.eq(i) for i in range(3)})
            for condition, mask in conditions.items():
                g = one[mask]
                if len(g):
                    collapse.append(
                        dict(
                            variant=variant,
                            cohort=cohort,
                            period=period,
                            condition=condition,
                            races=len(g),
                            outside1=float(g.outside1.mean()),
                            outside2=float(g.outside2.mean()),
                            outside3=float(g.outside3.mean()),
                            rank3=float(g.rank3.mean()),
                            mean_outside_count=float(g.outside_count.mean()),
                        )
                    )
            group = one.axis_out.eq(1)
            for place in [1, 2, 3]:
                col = f"outside{place}"
                lo, hi = group_difference(one, group, col)
                differences.append(
                    dict(
                        variant=variant,
                        cohort=cohort,
                        period=period,
                        comparison="axis_out_minus_placed",
                        metric=col,
                        races=len(one),
                        difference=float(one.loc[group, col].mean() - one.loc[~group, col].mean()),
                        ci_low=lo,
                        ci_high=hi,
                    )
                )
            interaction = one.outside3 - one.outside2
            lo, hi = group_difference(one.assign(interaction=interaction), group, "interaction")
            differences.append(
                dict(
                    variant=variant,
                    cohort=cohort,
                    period=period,
                    comparison="axis_out_minus_placed",
                    metric="third_outside_minus_second_outside",
                    races=len(one),
                    difference=float(interaction[group].mean() - interaction[~group].mean()),
                    ci_low=lo,
                    ci_high=hi,
                )
            )
            strata = [
                "year",
                "meet",
                "distance_band",
                "grade_band",
                "field_band",
                "axis_probability_band",
            ]
            n = 0
            actual = np.zeros(3)
            standard = np.zeros(3)
            for _, cell in one.groupby(strata):
                cases = cell[cell.axis_out.eq(1)]
                controls = cell[cell.axis_out.eq(0)]
                if len(cases) >= 3 and len(controls) >= 3:
                    n += len(cases)
                    actual += cases[["outside1", "outside2", "outside3"]].sum().to_numpy()
                    standard += (
                        len(cases)
                        * controls[["outside1", "outside2", "outside3"]].mean().to_numpy()
                    )
            if n:
                for j in range(3):
                    matched.append(
                        dict(
                            variant=variant,
                            cohort=cohort,
                            period=period,
                            actual_place=j + 1,
                            matched_axis_out_races=n,
                            actual_rate=float(actual[j] / n),
                            standardized_axis_placed_rate=float(standard[j] / n),
                            difference=float((actual[j] - standard[j]) / n),
                        )
                    )
            for kind, g in [
                ("all", one),
                ("top5_roster_miss", one[one.outside_count.gt(0)]),
                ("trio6_fail", one[one.trio6.eq(0)] if "trio6" in one else one.iloc[:0]),
            ]:
                for pattern, count in g.miss_pattern.value_counts().items():
                    patterns.append(
                        dict(
                            variant=variant,
                            cohort=cohort,
                            period=period,
                            scope=kind,
                            pattern=pattern,
                            races=int(count),
                            denominator=len(g),
                            fraction=float(count / len(g)),
                        )
                    )
            if variant != "operating_snapshot2026":
                for state in [0, 1]:
                    g = one[one.axis_out.eq(state)]
                    residual = g.outside_count - g.expected_outside_observed_state
                    lo, hi = boot(g, residual)
                    mechanics.append(
                        dict(
                            variant=variant,
                            cohort=cohort,
                            period=period,
                            axis_out=state,
                            races=len(g),
                            actual_outside_count=float(g.outside_count.mean()),
                            expected_conditional_outside_count=float(
                                g.expected_outside_observed_state.mean()
                            ),
                            residual=float(residual.mean()),
                            ci_low=lo,
                            ci_high=hi,
                        )
                    )
    for name, values in [
        ("position_summary", positions),
        ("paired_differences", differences),
        ("collapse_summary", collapse),
        ("miss_patterns", patterns),
        ("matched_collapse", matched),
        ("conditional_mechanics", mechanics),
    ]:
        pd.DataFrame(values).to_csv(OUT / f"{name}.csv", index=False)
    # Ordering among real podium finishers is diagnostic, not an exacta/ordered-trio hit rate.
    order = r.groupby("variant")[
        ["first_vs_second_correct", "second_vs_third_correct", "first_vs_third_correct"]
    ].mean()
    order.to_csv(OUT / "pair_ordering.csv")


def main():
    OUT.mkdir(exist_ok=True)
    assert not (OUT / "source_lock.json").exists()
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in refs()})
    p = load()
    r = race_table(p)
    analyze(p, r)
    check()
    print("Analyzed", len(p), len(r), flush=True)


if __name__ == "__main__":
    main()
