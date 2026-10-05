"""Audit every going × tempo ①–⑥ cell without changing source databases.

Run from repository root:
  .venv/bin/python research/section_track_adjustment_20260926/all_condition_tempo_cells.py

The 2024/2025/2026 race-par tests each use only earlier-year training.
Final descriptive correction magnitudes use data through 2025 and are not
the predictions used to score those holdouts.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from analyze import MEETS, PARTS, fit, load, race_pars
from condition_tempo_compare import fit_interaction

LEVELS = list("①②③④⑤⑥")
CONDITIONS = ("건조", "양호", "다습", "포화", "불량")


def day_bootstrap(frame: pd.DataFrame, before: str, after: str) -> list[float] | None:
    """Paired day-block interval for MAE reduction; not a causal interval."""
    daily = frame.groupby("race_date").agg(
        n=("race_key", "size"),
        before=(before, "sum"),
        after=(after, "sum"),
    )
    if len(daily) < 10:
        return None
    rng = np.random.default_rng(20260927)
    draws = rng.integers(0, len(daily), (2000, len(daily)))
    changes = (daily["before"] - daily["after"]).to_numpy()
    counts = daily["n"].to_numpy()
    estimates = changes[draws].sum(axis=1) / counts[draws].sum(axis=1)
    return [round(float(value), 4) for value in np.quantile(estimates, (0.025, 0.975))]


def effect(model: object, reference: pd.DataFrame, candidate: pd.DataFrame) -> float:
    return round(float(model.predict(candidate)[0] - model.predict(reference)[0]), 4)


def evaluate_group(pars: pd.DataFrame, meet: str, part: str) -> dict[str, object]:
    group = pars[(pars["meet"] == meet) & (pars["part"] == part)]
    scored = []
    for year in (2024, 2025, 2026):
        training = group[group["year"] < year]
        test = group[group["year"] == year].copy()
        for name, model in (
            ("raw", fit(training, "raw")),
            ("additive", fit(training, "joint")),
            ("interaction", fit_interaction(training)),
        ):
            test[f"{name}_error"] = abs(test["par"] - model.predict(test))
        scored.append(test)
    holdout = pd.concat(scored, ignore_index=True)
    descriptive = group[group["year"] <= 2025]
    add_model = fit(descriptive, "joint")
    interaction_model = fit_interaction(descriptive)
    reference = descriptive.iloc[[0]].copy()
    reference["tempo_raw"] = "③" if meet == "jeju" else "⑤"
    reference["track_condition"] = "건조"
    reference["condition_tempo"] = reference["track_condition"] + "|" + reference["tempo_raw"]
    cells = []
    for level in LEVELS:
        for condition in CONDITIONS:
            train_cell = descriptive[
                descriptive["tempo_raw"].eq(level) & descriptive["track_condition"].eq(condition)
            ]
            initial_cell = train_cell[train_cell["year"] <= 2023]
            held_cell = holdout[
                holdout["tempo_raw"].eq(level) & holdout["track_condition"].eq(condition)
            ]
            candidate = reference.copy()
            candidate["tempo_raw"] = level
            candidate["track_condition"] = condition
            candidate["condition_tempo"] = condition + "|" + level
            if len(held_cell):
                raw_mae = round(float(held_cell["raw_error"].mean()), 4)
                additive_mae = round(float(held_cell["additive_error"].mean()), 4)
                interaction_mae = round(float(held_cell["interaction_error"].mean()), 4)
                raw_to_add = round(
                    float((held_cell["raw_error"] - held_cell["additive_error"]).mean()), 4
                )
                add_to_interaction = round(
                    float((held_cell["additive_error"] - held_cell["interaction_error"]).mean()), 4
                )
            else:
                raw_mae = additive_mae = interaction_mae = None
                raw_to_add = add_to_interaction = None
            cells.append(
                {
                    "condition": condition,
                    "tempo": level,
                    "train_races_through_2023": len(initial_cell),
                    "train_days_through_2023": int(initial_cell["race_date"].nunique()),
                    "train_races_through_2025": len(train_cell),
                    "train_days_through_2025": int(train_cell["race_date"].nunique()),
                    "holdout_races_2024_2026": len(held_cell),
                    "holdout_days_2024_2026": int(held_cell["race_date"].nunique()),
                    "additive_effect_seconds": (
                        effect(add_model, reference, candidate) if len(train_cell) else None
                    ),
                    "interaction_effect_seconds": (
                        effect(interaction_model, reference, candidate) if len(train_cell) else None
                    ),
                    "raw_mae": raw_mae,
                    "additive_mae": additive_mae,
                    "interaction_mae": interaction_mae,
                    "raw_to_additive_reduction": raw_to_add,
                    "additive_to_interaction_reduction": add_to_interaction,
                    "raw_to_additive_day_ci": (
                        day_bootstrap(held_cell, "raw_error", "additive_error")
                        if len(held_cell)
                        else None
                    ),
                    "additive_to_interaction_day_ci": (
                        day_bootstrap(held_cell, "additive_error", "interaction_error")
                        if len(held_cell)
                        else None
                    ),
                    "by_year": [
                        {
                            "year": int(year),
                            "races": len(in_year),
                            "days": int(in_year["race_date"].nunique()),
                            "raw_to_additive_reduction": round(
                                float((in_year["raw_error"] - in_year["additive_error"]).mean()), 4
                            ),
                            "additive_to_interaction_reduction": round(
                                float(
                                    (
                                        in_year["additive_error"] - in_year["interaction_error"]
                                    ).mean()
                                ),
                                4,
                            ),
                        }
                        for year, in_year in held_cell.groupby("year")
                    ],
                }
            )
    return {
        "total_holdout_races": len(holdout),
        "overall_mae": {
            name: round(float(holdout[f"{name}_error"].mean()), 4)
            for name in ("raw", "additive", "interaction")
        },
        "cells": cells,
    }


def main() -> None:
    data, _ = load()
    pars = race_pars(data)
    pars["condition_tempo"] = pars["track_condition"] + "|" + pars["tempo_raw"]
    results = {
        f"{meet}/{part}": evaluate_group(pars, meet, part)
        for meet in MEETS.values()
        for part in PARTS.values()
    }
    print(json.dumps(results, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
