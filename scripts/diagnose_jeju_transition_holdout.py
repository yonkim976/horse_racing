"""Fixed promotion decision and full-cohort6to5 probability audit."""

import json

import numpy as np
import polars as pl

from scripts.freeze_jeju_transition_protocol import FEAT, OUT
from scripts.run_jeju_transition_holdout import save


def main():
    comparisons = json.loads((OUT / "paired_comparisons.json").read_text())
    decisions = []
    for row in comparisons:
        if row["reference"] != "HY_R_FORM":
            continue
        passed = (
            row["set_hit"]["primary_day_ci_97_5"][0] > 0
            and row["pick_hit"]["delta"] >= 0
            and row["order_hit"]["delta"] >= 0
        )
        decisions.append(
            dict(
                candidate=row["candidate"],
                passed=passed,
                set_delta=row["set_hit"]["delta"],
                set_primary_ci_97_5=row["set_hit"]["primary_day_ci_97_5"],
                pick_delta=row["pick_hit"]["delta"],
                order_delta=row["order_hit"]["delta"],
            )
        )
    eligible = [r for r in decisions if r["passed"]]
    chosen = (
        max(eligible, key=lambda r: (r["set_delta"], r["candidate"] == "HY_TRANSITION"))[
            "candidate"
        ]
        if eligible
        else "HY_R_FORM"
    )
    save(
        "decision.json",
        dict(
            primary_comparisons=decisions,
            retained_research_selection=chosen,
            production_replacement=False,
            evaluation_consumed=True,
            additional_fits_after_evaluation=0,
        ),
    )
    h = (
        pl.read_parquet(OUT / "horse_predictions.parquet")
        .join(
            pl.read_parquet(FEAT / "features.parquet").select("entry_id", "transition_6to5"),
            on="entry_id",
            validate="m:1",
        )
        .filter(~pl.col("boundary_tie"))
    )
    rows = []
    for model in sorted(h["model"].unique()):
        for group in ["6to5", "other_same_year", "unknown_or_cross_year"]:
            part = h.filter(pl.col("model") == model)
            condition = (
                pl.col("transition_6to5") == 1
                if group == "6to5"
                else pl.col("transition_6to5") == 0
                if group == "other_same_year"
                else ~pl.col("transition_6to5").is_finite()
            )
            part = part.filter(condition)
            if not len(part):
                continue
            y = part["official_top3"].to_numpy()
            p = part["pl_place_probability"].to_numpy()
            daily = (
                part.group_by("event_date")
                .agg(
                    (pl.col("pl_place_probability") - pl.col("official_top3")).sum().alias("error"),
                    pl.len().alias("n"),
                )
                .sort("event_date")
            )
            draw = np.random.default_rng(17).integers(0, len(daily), (5000, len(daily)))
            boot = daily["error"].to_numpy()[draw].sum(axis=1) / daily["n"].to_numpy()[draw].sum(
                axis=1
            )
            rows.append(
                dict(
                    model=model,
                    group=group,
                    entries=len(part),
                    races=part["race_id"].n_unique(),
                    days=len(daily),
                    observed_rate=float(y.mean()),
                    mean_probability=float(p.mean()),
                    bias=float((p - y).mean()),
                    bias_day_ci=np.quantile(boot, [0.025, 0.975]).tolist(),
                    brier=float(np.mean((p - y) ** 2)),
                )
            )
    save("grade_subgroups.json", rows)
    print(
        json.dumps(
            dict(
                decisions=decisions,
                grade6to5=[
                    r for r in rows if r["group"] == "6to5" and r["model"].startswith("HY_")
                ],
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
