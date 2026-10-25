"""Paired race/date comparisons for the fixed input and target experiments."""

from pathlib import Path

import numpy as np
import pandas as pd
import run as experiment

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
METRICS = ["quinella_one", "axis_top2", "axis_next3", "axis_top3", "quinella_box4"]


def paired(left, right, seed):
    p = left.merge(right, on="race_key", suffixes=("_new", "_base"), validate="one_to_one")
    assert len(p) == len(left) == len(right)
    rng = np.random.default_rng(seed)
    result = []
    for metric in METRICS:
        delta = p[metric + "_new"] - p[metric + "_base"]
        d = (
            pd.DataFrame({"date": p.race_date_new, "delta": delta})
            .groupby("date")
            .delta.agg(["sum", "size"])
            .to_numpy()
        )
        draw = d[rng.integers(0, len(d), size=(2000, len(d)))].sum(axis=1)
        result.append(
            dict(
                metric=metric,
                races=len(p),
                new_hits=int(p[metric + "_new"].sum()),
                base_hits=int(p[metric + "_base"].sum()),
                new_rate=float(p[metric + "_new"].mean()),
                base_rate=float(p[metric + "_base"].mean()),
                difference_pp=float(delta.mean() * 100),
                date_bootstrap_95_pp=(
                    np.quantile(draw[:, 0] / draw[:, 1], [0.025, 0.975]) * 100
                ).tolist(),
                new_only=int(((p[metric + "_new"] == 1) & (p[metric + "_base"] == 0)).sum()),
                base_only=int(((p[metric + "_new"] == 0) & (p[metric + "_base"] == 1)).sum()),
            )
        )
    return result


def aggregate(races):
    rows = []
    for (target, variant), group in races.groupby(["target", "variant"]):
        for scope in ["all", "meet", "year", "distance_band", "history_band", "grade_band"]:
            if scope == "all":
                groups = [("all", group)]
            else:
                groups = group.groupby(scope, observed=True)
            for name, g in groups:
                row = dict(
                    target=int(target), variant=variant, scope=scope, label=str(name), races=len(g)
                )
                for metric in METRICS + ["axis_win", "target_brier", "set_logloss"]:
                    row[metric] = float(g[metric].mean())
                    if metric in METRICS:
                        row[metric + "_hits"] = int(g[metric].sum())
                rows.append(row)
    return pd.DataFrame(rows)


def paired_losses(left, right, seed):
    p = left.merge(right, on="race_key", suffixes=("_new", "_base"), validate="one_to_one")
    assert len(p) == len(left) == len(right)
    rng = np.random.default_rng(seed)
    rows = []
    for metric in ["target_brier", "set_logloss"]:
        delta = p[metric + "_new"] - p[metric + "_base"]
        days = (
            pd.DataFrame({"date": p.race_date_new, "delta": delta})
            .groupby("date")
            .delta.agg(["sum", "size"])
            .to_numpy()
        )
        draw = days[rng.integers(0, len(days), size=(2000, len(days)))].sum(axis=1)
        rows.append(
            dict(
                metric=metric,
                races=len(p),
                new_value=float(p[metric + "_new"].mean()),
                base_value=float(p[metric + "_base"].mean()),
                difference=float(delta.mean()),
                date_bootstrap_95=np.quantile(draw[:, 0] / draw[:, 1], [0.025, 0.975]).tolist(),
            )
        )
    return rows


def operating(runners, races):
    path = (
        experiment.R / "20261004_close_contenders_v1/outputs/operating_runner_predictions.parquet"
    )
    old = pd.read_parquet(path)
    new = runners[runners.target.eq(3) & runners.variant.eq("baseline22")].copy()
    for g in [old, new]:
        g["comparison_rank"] = g.outcome.where(g.outcome.between(1, 20), 0).astype(int)
    ns = new.groupby("race_key").apply(
        lambda g: frozenset(zip(g.program_no, g.horse_id, g.comparison_rank, strict=True)),
        include_groups=False,
    )
    os = old.groupby("race_key").apply(
        lambda g: frozenset(zip(g.program_no, g.horse_id, g.comparison_rank, strict=True)),
        include_groups=False,
    )

    def bridge(r):
        r = r.replace("RACE:SEOUL:", "1:").replace("RACE:BUSAN:", "3:")
        a, b = r.rsplit(":", 1)
        return a + ":" + str(int(b))

    keys = {r: bridge(r) for r in os.index if bridge(r) in ns.index and ns[bridge(r)] == os[r]}
    assert len(keys) == 1258
    rows = []
    for key, g in old[old.race_key.isin(keys)].groupby("race_key"):
        for variant, score in [("operating_top3", "prob_top3"), ("operating_top2", "prob_top2")]:
            row = dict(
                race_key=keys[key],
                operating_key=key,
                meet=int(g.meet.iloc[0]),
                race_date=g.race_date.iloc[0],
                variant=variant,
            )
            row.update(
                experiment.rank_metrics(
                    g.sort_values([score, "program_no"], ascending=[False, True]).outcome.to_numpy()
                )
            )
            rows.append(row)
    op = pd.DataFrame(rows)
    op.to_csv(OUT / "operating_race_metrics.csv", index=False)
    results = []
    seed = 20261009
    for (target, variant), g in races[races.race_key.isin(keys.values())].groupby(
        ["target", "variant"]
    ):
        for comparator, o in op.groupby("variant"):
            for meet in [0, 1, 3]:
                left = g if meet == 0 else g[g.meet.eq(meet)]
                right = o if meet == 0 else o[o.meet.eq(meet)]
                for row in paired(left, right, seed):
                    results.append(
                        dict(
                            target=int(target),
                            variant=variant,
                            comparator=comparator,
                            meet=meet,
                            bootstrap_seed=seed,
                        )
                        | row
                    )
                seed += 1
    experiment.save(
        OUT / "operating_comparisons.json",
        dict(
            matched_races=1258,
            matching="same horse ID/program/numeric outcome",
            rank_based_not_joint_ticket=True,
            comparisons=results,
        ),
    )


def main():
    experiment.check_inputs()
    races = pd.read_csv(OUT / "race_metrics.csv")
    runners = pd.read_parquet(OUT / "runner_predictions.parquet")
    races["distance_band"] = np.where(
        races.distance_m.le(1300),
        "<=1300",
        np.where(races.distance_m.le(1600), "1400_1600", ">=1700"),
    )
    races["history_band"] = np.where(
        races.minimum_history.eq(0),
        "new_horse_present",
        np.where(races.minimum_history.lt(5), "low_history", "all_5plus"),
    )
    races["grade_band"] = np.where(
        races.grade.eq(6),
        "grade6",
        np.where(
            races.grade.eq(5),
            "grade5",
            np.where(races.grade.between(1, 4), "grade4plus", "open_unknown"),
        ),
    )
    summary = aggregate(races)
    summary.to_csv(OUT / "metrics.csv", index=False)
    pairs = [
        ("raw_sections", "baseline22"),
        ("adjusted_sections", "raw_sections"),
        ("style_history", "adjusted_sections"),
        ("field_context", "style_history"),
        ("pace_stack", "field_context"),
        ("adjusted_sections", "baseline22"),
        ("style_history", "baseline22"),
        ("field_context", "baseline22"),
        ("pace_stack", "baseline22"),
    ]
    rows = []
    seed = 20261009
    loss_rows = []
    for target in [3, 2]:
        for new, base in pairs:
            for meet in [0, 1, 3]:
                for period in ["all", "2024_2025", "2026_partial"]:
                    mask = races.target.eq(target)
                    if meet:
                        mask &= races.meet.eq(meet)
                    if period == "2024_2025":
                        mask &= races.year.le(2025)
                    if period == "2026_partial":
                        mask &= races.year.eq(2026)
                    a = races[mask & races.variant.eq(new)]
                    b = races[mask & races.variant.eq(base)]
                    for row in paired(a, b, seed):
                        rows.append(
                            dict(
                                target=target,
                                variant=new,
                                reference=base,
                                meet=meet,
                                period=period,
                                bootstrap_seed=seed,
                            )
                            | row
                        )
                    for row in paired_losses(a, b, seed + 100000):
                        loss_rows.append(
                            dict(
                                target=target,
                                variant=new,
                                reference=base,
                                meet=meet,
                                period=period,
                                bootstrap_seed=seed + 100000,
                            )
                            | row
                        )
                    seed += 1
    # Target change is separate from information-bundle effects.
    for variant in experiment.config()["variants"]:
        for row in paired(
            races[races.target.eq(2) & races.variant.eq(variant)],
            races[races.target.eq(3) & races.variant.eq(variant)],
            seed,
        ):
            rows.append(
                dict(
                    target=2,
                    variant=variant,
                    reference="same_inputs_target3",
                    meet=0,
                    period="all",
                    bootstrap_seed=seed,
                )
                | row
            )
        seed += 1
    experiment.save(
        OUT / "paired_differences.json",
        dict(comparisons=rows, draws=2000, multiple_comparisons_adjusted=False),
    )
    experiment.save(
        OUT / "paired_probability_differences.json",
        dict(
            comparisons=loss_rows,
            draws=2000,
            units="raw loss difference; lower is better",
            multiple_comparisons_adjusted=False,
        ),
    )
    operating(runners, races)
    calibration = []
    for (target, variant), g in runners.groupby(["target", "variant"]):
        bins = np.minimum((g.target_probability * 10).astype(int), 9)
        for band, z in g.groupby(bins):
            calibration.append(
                dict(
                    target=int(target),
                    variant=variant,
                    bin=int(band),
                    n=len(z),
                    predicted=float(z.target_probability.mean()),
                    actual=float(z.outcome.between(1, target).mean()),
                )
            )
    pd.DataFrame(calibration).to_csv(OUT / "calibration.csv", index=False)
    experiment.save(
        OUT / "analysis_complete.json",
        dict(
            races_per_candidate=int(races.groupby(["target", "variant"]).size().min()),
            candidates=12,
            comparisons=len(rows),
            date_start=races.race_date.min(),
            date_end=races.race_date.max(),
            retrospective=True,
            production_changed=False,
            current_weight_pit_verified=False,
        ),
    )
    print(
        summary[summary.scope.eq("all")][["target", "variant", "races", *METRICS]].to_string(
            index=False
        )
    )


if __name__ == "__main__":
    main()
