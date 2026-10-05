"""Read-only, chronological pilot of going/tempo corrections to past times.

This is deliberately not a production speed figure or a prediction-model test.
Run from the repository root with ``.venv/bin/python
research/track_record_adjustment_20260926/analyze.py``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parents[2]
VALID_GOING = {"건조", "양호", "다습", "포화", "불량"}
TEMPO = {char: index for index, char in enumerate("①②③④⑤⑥⑦⑧⑨", start=1)}
MEETS = ("seoul", "busan", "jeju")
VARIANTS = ("raw", "going", "tempo", "joint")


def load_entries() -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    for meet in MEETS:
        pattern = f"{meet}_20??_score_20260925/{meet}_*.sqlite3"
        for path in sorted((ROOT / "data/research").glob(pattern)):
            if "_2017_" in str(path):  # Tempo is absent in all 2017 score sheets.
                continue
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
                frame = pd.read_sql_query(
                    """
                    SELECT r.race_date, r.race_number, r.distance_m, r.grade,
                           r.track_condition, r.tempo_raw, e.kra_horse_id,
                           e.finish_position, e.finish_time_ms
                    FROM race AS r JOIN entry AS e
                      ON e.meet_code=r.meet_code AND e.race_date=r.race_date
                     AND e.race_number=r.race_number
                    WHERE e.finish_position BETWEEN 1 AND 20
                      AND e.finish_time_ms > 0
                    """,
                    con,
                )
            frame.insert(0, "meet", meet)
            chunks.append(frame)
    entries = pd.concat(chunks, ignore_index=True)
    entries["race_date"] = pd.to_datetime(entries["race_date"])
    entries["year"] = entries["race_date"].dt.year
    entries["month"] = entries["race_date"].dt.month
    entries["tempo_level"] = entries["tempo_raw"].map(TEMPO)
    entries["speed_mps"] = entries["distance_m"] / (
        entries["finish_time_ms"] / 1000.0
    )
    lower = np.where(entries["meet"].eq("jeju"), 8.0, 10.0)
    upper = np.where(entries["meet"].eq("jeju"), 16.0, 20.0)
    entries = entries[
        entries["speed_mps"].between(lower, upper)
        & entries["track_condition"].isin(VALID_GOING)
        & entries["tempo_level"].notna()
    ].copy()
    entries["sec_per_km"] = entries["finish_time_ms"] / entries["distance_m"]
    entries["race_key"] = (
        entries["meet"]
        + ":"
        + entries["race_date"].dt.strftime("%Y-%m-%d")
        + ":"
        + entries["race_number"].astype(str)
    )
    entries["distance_grade"] = (
        entries["distance_m"].astype(str) + ":" + entries["grade"].fillna("unknown")
    )
    return entries


def race_par_observations(entries: pd.DataFrame) -> pd.DataFrame:
    top3 = entries[entries["finish_position"].le(3)]
    pars = top3.groupby("race_key", sort=False)["sec_per_km"].median().rename("par")
    races = entries.drop_duplicates("race_key")[
        [
            "race_key", "meet", "race_date", "year", "month", "distance_grade",
            "track_condition", "tempo_raw",
        ]
    ].merge(pars, on="race_key", how="inner")
    return races


def fit_par_model(races: pd.DataFrame, variant: str) -> Pipeline:
    features = ["distance_grade", "year", "month"]
    if variant in {"going", "joint"}:
        features.append("track_condition")
    if variant in {"tempo", "joint"}:
        features.append("tempo_raw")
    model = Pipeline(
        [
            (
                "categorical",
                ColumnTransformer(
                    [("onehot", OneHotEncoder(handle_unknown="ignore"), features)]
                ),
            ),
            ("regression", Ridge(alpha=10.0)),
        ]
    )
    model.fit(races, races["par"])
    return model


def previous_same_distance(entries: pd.DataFrame) -> pd.DataFrame:
    ordered = entries.sort_values(
        ["meet", "kra_horse_id", "distance_m", "race_date", "race_number"]
    ).copy()
    by_horse_distance = ordered.groupby(
        ["meet", "kra_horse_id", "distance_m"], dropna=False, sort=False
    )
    for column in (
        "race_date", "sec_per_km", "track_condition", "tempo_raw", "year",
        "month", "distance_grade",
    ):
        ordered[f"previous_{column}"] = by_horse_distance[column].shift(1)
    ordered["history_age_days"] = (
        ordered["race_date"] - ordered["previous_race_date"]
    ).dt.days
    return ordered[ordered["history_age_days"].between(1, 365)].copy()


def environment_effect(
    model: Pipeline, test: pd.DataFrame, variant: str, meet: str
) -> np.ndarray:
    previous = test[
        [
            "previous_distance_grade", "previous_year", "previous_month",
            "previous_track_condition", "previous_tempo_raw",
        ]
    ].rename(columns=lambda name: name.removeprefix("previous_")).copy()
    actual = previous
    neutral = actual.copy()
    if variant in {"going", "joint"}:
        neutral["track_condition"] = "건조"
    if variant in {"tempo", "joint"}:
        neutral["tempo_raw"] = "③" if meet == "jeju" else "⑤"
    return model.predict(actual) - model.predict(neutral)


def race_pair_accuracy(frame: pd.DataFrame, metric: str) -> pd.DataFrame:
    records: list[tuple[str, pd.Timestamp, float, int]] = []
    for race_key, group in frame.groupby("race_key", sort=False):
        if len(group) < 3:
            continue
        score = group[metric].to_numpy(dtype=float)
        rank = group["finish_position"].to_numpy(dtype=float)
        indices = np.triu_indices(len(group), 1)
        target = rank[indices[0]] - rank[indices[1]]
        candidate = score[indices[0]] - score[indices[1]]
        eligible = target != 0
        if eligible.sum() < 3:
            continue
        product = target[eligible] * candidate[eligible]
        accuracy = float(np.mean(np.where(product > 0, 1.0, np.where(product == 0, 0.5, 0.0))))
        records.append((race_key, group["race_date"].iloc[0], accuracy, len(group)))
    return pd.DataFrame(records, columns=["race_key", "date", "accuracy", "runners"])


def evaluate_year(
    meet: str, year: int, races: pd.DataFrame, histories: pd.DataFrame
) -> tuple[dict[str, object], pd.DataFrame]:
    train = races[(races["meet"] == meet) & races["year"].lt(year)]
    test = histories[(histories["meet"] == meet) & histories["year"].eq(year)].copy()
    test["raw"] = test["previous_sec_per_km"]
    for variant in VARIANTS[1:]:
        model = fit_par_model(train, variant)
        test[variant] = test["raw"] - environment_effect(model, test, variant, meet)
    measurements = {
        variant: race_pair_accuracy(test, variant) for variant in VARIANTS
    }
    common = measurements["raw"][["race_key", "date", "runners"]].copy()
    common = common.merge(
        test.drop_duplicates("race_key")[["race_key", "distance_m", "grade"]],
        on="race_key",
        validate="one_to_one",
    )
    for variant, measurement in measurements.items():
        common = common.merge(
            measurement[["race_key", "accuracy"]].rename(
                columns={"accuracy": variant}
            ),
            on="race_key",
            validate="one_to_one",
        )
    out: dict[str, object] = {
        "meet": meet,
        "test_year": year,
        "training_races": len(train),
        "eligible_test_races": len(common),
        "eligible_runners": int(common["runners"].sum()),
        "mean_pair_accuracy": {
            variant: round(float(common[variant].mean()), 5) for variant in VARIANTS
        },
    }
    for variant in VARIANTS[1:]:
        out[f"delta_{variant}_vs_raw"] = round(
            float((common[variant] - common["raw"]).mean()), 5
        )
    common.insert(0, "meet", meet)
    common.insert(1, "test_year", year)
    return out, common


def bootstrap_deltas(races: pd.DataFrame) -> dict[str, object]:
    """Resample racing days, retaining every race on a sampled day."""
    rng = np.random.default_rng(20260926)
    daily = races.groupby("date", sort=True).agg(
        n=("race_key", "size"),
        **{
            name: (name, "sum")
            for name in VARIANTS
        },
    )
    result: dict[str, object] = {
        "test_races": len(races),
        "test_days": len(daily),
        "pair_accuracy": {
            name: round(float(races[name].mean()), 5) for name in VARIANTS
        },
    }
    sampled = rng.integers(0, len(daily), size=(2000, len(daily)))
    n = daily["n"].to_numpy()
    denominator = n[sampled].sum(axis=1)
    for variant in VARIANTS[1:]:
        diff = (daily[variant] - daily["raw"]).to_numpy()
        estimates = diff[sampled].sum(axis=1) / denominator
        result[f"delta_{variant}_vs_raw"] = {
            "estimate": round(float((races[variant] - races["raw"]).mean()), 5),
            "day_bootstrap_95": [
                round(float(x), 5) for x in np.quantile(estimates, [0.025, 0.975])
            ],
        }
    diff = (daily["joint"] - daily["tempo"]).to_numpy()
    estimates = diff[sampled].sum(axis=1) / denominator
    result["delta_joint_vs_tempo"] = {
        "estimate": round(float((races["joint"] - races["tempo"]).mean()), 5),
        "day_bootstrap_95": [round(float(x), 5) for x in np.quantile(estimates, [0.025, 0.975])],
    }
    return result


def strata_deltas(races: pd.DataFrame, column: str) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for name, group in races.groupby(column, dropna=False):
        if len(group) < 100:
            continue
        summaries.append(
            {
                column: name,
                "races": len(group),
                "raw": round(float(group["raw"].mean()), 4),
                "tempo_vs_raw": round(float((group["tempo"] - group["raw"]).mean()), 4),
                "joint_vs_raw": round(float((group["joint"] - group["raw"]).mean()), 4),
                "joint_vs_tempo": round(float((group["joint"] - group["tempo"]).mean()), 4),
            }
        )
    return sorted(summaries, key=lambda item: item[column])


def main() -> None:
    entries = load_entries()
    races = race_par_observations(entries)
    histories = previous_same_distance(entries)
    evaluations = [
        evaluate_year(meet, year, races, histories)
        for meet in MEETS
        for year in (2024, 2025, 2026)
    ]
    race_accuracy = pd.concat([part[1] for part in evaluations], ignore_index=True)
    result = {
        "method": (
            "past same-venue exact-distance run <=365 days; "
            "per-race mean pairwise order accuracy; yearly refit using prior years only"
        ),
        "entries": len(entries),
        "race_pars": len(races),
        "results": [part[0] for part in evaluations],
        "pooled_by_meet": {
            meet: {
                **bootstrap_deltas(race_accuracy[race_accuracy["meet"].eq(meet)]),
                "by_distance": strata_deltas(
                    race_accuracy[race_accuracy["meet"].eq(meet)], "distance_m"
                ),
                "by_grade": strata_deltas(
                    race_accuracy[race_accuracy["meet"].eq(meet)], "grade"
                ),
            }
            for meet in MEETS
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
