"""Read-only comparison of additive and interaction track corrections.

Run from repository root with:
  .venv/bin/python research/section_track_adjustment_20260926/condition_tempo_compare.py
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from analyze import MEETS, PARTS, fit, load, race_pars
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


def fit_interaction(training: pd.DataFrame) -> Pipeline:
    features = [
        "distance_grade",
        "year",
        "month",
        "track_condition",
        "tempo_raw",
        "condition_tempo",
    ]
    model = Pipeline(
        [
            (
                "onehot",
                ColumnTransformer(
                    [("categorical", OneHotEncoder(handle_unknown="ignore"), features)]
                ),
            ),
            ("ridge", Ridge(alpha=10.0)),
        ]
    )
    model.fit(training, training["par"])
    return model


def main() -> None:
    data, _ = load()
    pars = race_pars(data)
    pars["condition_tempo"] = pars["track_condition"] + "|" + pars["tempo_raw"]
    combined: dict[str, object] = {}
    bad_fast_holdout: dict[str, object] = {}
    cell_effects: dict[str, object] = {}
    conditions = ["건조", "양호", "다습", "포화", "불량"]
    levels = list("①②③④⑤⑥")
    for meet in MEETS.values():
        for part in PARTS.values():
            group = pars[(pars["meet"] == meet) & (pars["part"] == part)]
            error_rows = []
            for year in (2024, 2025, 2026):
                training = group[group["year"] < year]
                test = group[group["year"] == year].copy()
                additive = fit(training, "joint")
                interaction = fit_interaction(training)
                test["additive_error"] = abs(test["par"] - additive.predict(test))
                test["interaction_error"] = abs(test["par"] - interaction.predict(test))
                error_rows.append(test)
            errors = pd.concat(error_rows, ignore_index=True)
            # Bootstrap racing days, preserving race clusters within each day.
            daily = errors.groupby("race_date").agg(
                n=("race_key", "size"),
                delta=("additive_error", "sum"),
                interaction=("interaction_error", "sum"),
            )
            delta = (daily["delta"] - daily["interaction"]).to_numpy()
            counts = daily["n"].to_numpy()
            rng = np.random.default_rng(20260927)
            draw = rng.integers(0, len(daily), size=(2000, len(daily)))
            estimate = delta[draw].sum(axis=1) / counts[draw].sum(axis=1)
            combined[f"{meet}/{part}"] = {
                "holdout_races": len(errors),
                "additive_mae": round(float(errors["additive_error"].mean()), 4),
                "interaction_mae": round(float(errors["interaction_error"].mean()), 4),
                "interaction_mae_reduction": round(
                    float((errors["additive_error"] - errors["interaction_error"]).mean()), 4
                ),
                "day_bootstrap_95": [
                    round(float(value), 4) for value in np.quantile(estimate, [0.025, 0.975])
                ],
            }
            rare = errors[errors["tempo_raw"].eq("①") & errors["track_condition"].eq("불량")]
            bad_fast_holdout[f"{meet}/{part}"] = {
                "races": len(rare),
                "days": int(rare["race_date"].nunique()),
                "additive_mae": (
                    round(float(rare["additive_error"].mean()), 4) if len(rare) else None
                ),
                "interaction_mae": (
                    round(float(rare["interaction_error"].mean()), 4) if len(rare) else None
                ),
                "by_year": [
                    {
                        "year": int(year),
                        "races": len(in_year),
                        "days": int(in_year["race_date"].nunique()),
                        "additive_mae": round(float(in_year["additive_error"].mean()), 4),
                        "interaction_mae": round(float(in_year["interaction_error"].mean()), 4),
                    }
                    for year, in_year in rare.groupby("year")
                ],
            }

            # Description only: use all available data through 2025 to show
            # the size of a conditional correction, never to score holdouts.
            train_effect = group[group["year"] <= 2025]
            additive_effect = fit(train_effect, "joint")
            interaction_effect = fit_interaction(train_effect)
            reference = train_effect.iloc[[0]].copy()
            reference["tempo_raw"] = "③" if meet == "jeju" else "⑤"
            reference["track_condition"] = "건조"
            reference["condition_tempo"] = (
                reference["track_condition"] + "|" + reference["tempo_raw"]
            )
            neutral_add = float(additive_effect.predict(reference)[0])
            neutral_int = float(interaction_effect.predict(reference)[0])
            selected: dict[str, object] = {}
            for level, condition in [
                ("①", "불량"),
                ("②", "건조"),
                ("④", "다습"),
                ("⑤", "건조"),
                ("⑥", "건조"),
            ]:
                candidate = reference.copy()
                candidate["tempo_raw"] = level
                candidate["track_condition"] = condition
                candidate["condition_tempo"] = condition + "|" + level
                matching = train_effect[
                    train_effect["tempo_raw"].eq(level)
                    & train_effect["track_condition"].eq(condition)
                ]
                selected[f"{condition}/{level}"] = {
                    "training_races": len(matching),
                    "training_days": int(matching["race_date"].nunique()),
                    "additive_seconds_vs_neutral": round(
                        float(additive_effect.predict(candidate)[0] - neutral_add), 4
                    ),
                    "interaction_seconds_vs_neutral": round(
                        float(interaction_effect.predict(candidate)[0] - neutral_int), 4
                    ),
                }
            cell_effects[f"{meet}/{part}"] = selected
    support: dict[str, object] = {}
    for meet in MEETS.values():
        training = pars[
            (pars["meet"] == meet) & (pars["part"] == "last_600") & (pars["year"] <= 2025)
        ]
        days = training.groupby(["tempo_raw", "track_condition"])["race_date"].nunique()
        races = training.groupby(["tempo_raw", "track_condition"]).size()
        support[meet] = {
            level: {
                condition: {
                    "days": int(days.get((level, condition), 0)),
                    "races": int(races.get((level, condition), 0)),
                }
                for condition in conditions
            }
            for level in levels
        }
    print(
        json.dumps(
            {
                "support_through_2025": support,
                "validation": combined,
                "bad_fast_holdout": bad_fast_holdout,
                "selected_cell_effects": cell_effects,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
