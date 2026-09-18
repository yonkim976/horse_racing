"""Predeclared zero-race-experience slice and fixed selection decision."""

import json

import numpy as np
import polars as pl

from scripts.run_jeju_trial_experiment import OUT, data_frame, save


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    frame, _, _, _ = data_frame(protocol)
    context = frame.filter(pl.col("event_date").dt.year() == 2025).select(
        "entry_id",
        "race_id",
        "horse_id",
        "starts_pre",
        "trial800_s1f_ms_mean3_365",
        "trial800_valid_count365",
        "trial800_finish_change_last2_365",
    )
    context.write_parquet(OUT / "subgroup_context.parquet")
    h = pl.read_parquet(OUT / "horse_predictions.parquet").join(
        context, on=["race_id", "horse_id"], validate="m:1"
    )
    rows = []
    for model in sorted(h["model"].unique()):
        part = h.filter(
            (pl.col("model") == model) & (~pl.col("boundary_tie")) & (pl.col("starts_pre") == 0)
        )
        prob = part["pl_place_probability"].to_numpy()
        y = part["official_top3"].to_numpy()
        clipped = np.clip(prob, 1e-12, 1 - 1e-12)
        rows.append(
            dict(
                model=model,
                entries=len(part),
                races=part["race_id"].n_unique(),
                observed_rate=float(y.mean()),
                mean_probability=float(prob.mean()),
                brier=float(np.mean((prob - y) ** 2)),
                logloss=float(np.mean(-y * np.log(clipped) - (1 - y) * np.log1p(-clipped))),
                trial_section_observed=int(part["trial800_s1f_ms_mean3_365"].is_finite().sum()),
                trial_change_observed=int(
                    part["trial800_finish_change_last2_365"].is_finite().sum()
                ),
            )
        )
    save("zero_experience_diagnostic.json", rows)
    comparisons = json.loads((OUT / "paired_comparisons.json").read_text())
    decisions = []
    for row in comparisons:
        if row["reference"] != ("HY_R_FORM" if row["candidate"].startswith("HY_") else "R_FORM"):
            continue
        passed = (
            row["set_hit"]["day_ci"][0] > 0
            and row["pick_hit"]["delta"] >= 0
            and row["order_hit"]["delta"] >= 0
        )
        decisions.append(
            dict(
                candidate=row["candidate"],
                reference=row["reference"],
                passes_selection_criterion=passed,
                set_hit_day_ci=row["set_hit"]["day_ci"],
                pick_delta=row["pick_hit"]["delta"],
                order_delta=row["order_hit"]["delta"],
            )
        )
    assert len(decisions) == 4
    save(
        "decision.json",
        dict(
            comparisons=decisions,
            production_replacement=False,
            retained_selection="HY_R_FORM",
            interpretation="2025 repeated development; probability signal is distinct "
            "from selection adoption; no further fits.",
        ),
    )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
