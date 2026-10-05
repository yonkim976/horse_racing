"""Same-horse, same-distance paired estimates of historical track effects.

This is an observational pilot, not a causal speed-figure or production model.
All source databases are opened read-only. Run from repository root with:
  .venv/bin/python research/section_track_adjustment_20260926/within_horse_track_effect.py
"""

from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd
from analyze import GOING, MEETS, ROOT, TEMPO, load

OPERATING_DB = ROOT / "data/horse_racing.sqlite3"
PARTS = ("start_200", "last_200", "last_600", "finish_sec_per_km")
GOING_LEVELS = ("건조", "양호", "다습", "포화", "불량")


def load_runner_records() -> pd.DataFrame:
    section_data, _ = load()
    identity = [
        "race_entry_id",
        "meet",
        "race_date",
        "race_number",
        "distance_m",
        "horse_id",
        "grade",
        "track_condition",
        "tempo_raw",
        "finish_time_ms",
    ]
    metadata = section_data.drop_duplicates("race_entry_id")[identity].set_index("race_entry_id")
    sections = section_data.pivot(index="race_entry_id", columns="part", values="section_seconds")
    records = metadata.join(sections)
    with sqlite3.connect(f"file:{OPERATING_DB}?mode=ro", uri=True) as con:
        controls = pd.read_sql_query(
            """
            SELECT e.id AS race_entry_id, e.carried_weight_kg, e.gate_number,
                   r.field_size, e.jockey_id
            FROM race_entries e JOIN races r ON r.id=e.race_id
            WHERE r.race_date_local BETWEEN '2018-01-01' AND '2026-09-20'
            """,
            con,
        ).set_index("race_entry_id")
    records = records.join(controls, how="left")
    records["grade"] = records["grade"].fillna("unknown")
    records["gate_fraction"] = ((records["gate_number"] - 1) / (records["field_size"] - 1)).clip(
        0, 1
    )
    records["finish_sec_per_km"] = records["finish_time_ms"] / records["distance_m"]
    speed = records["distance_m"] / (records["finish_time_ms"] / 1000)
    low = np.where(records["meet"].eq("jeju"), 8, 10)
    high = np.where(records["meet"].eq("jeju"), 16, 20)
    records.loc[~speed.between(low, high), "finish_sec_per_km"] = np.nan
    return records.reset_index()


def make_pairs(records: pd.DataFrame, part: str, max_days: int) -> pd.DataFrame:
    ordered = (
        records[records[part].notna()]
        .sort_values(["meet", "horse_id", "distance_m", "race_date", "race_number"])
        .copy()
    )
    group = ordered.groupby(["meet", "horse_id", "distance_m"], sort=False)
    fields = [
        "race_date",
        "grade",
        "track_condition",
        "tempo_raw",
        part,
        "carried_weight_kg",
        "gate_fraction",
        "field_size",
        "jockey_id",
    ]
    for name in fields:
        ordered[f"previous_{name}"] = group[name].shift(1)
    ordered["days_apart"] = (ordered["race_date"] - ordered["previous_race_date"]).dt.days
    valid = (
        ordered["days_apart"].between(1, max_days)
        & ordered["grade"].eq(ordered["previous_grade"])
        & ordered["track_condition"].isin(GOING)
        & ordered["previous_track_condition"].isin(GOING)
        & ordered["tempo_raw"].isin(TEMPO)
        & ordered["previous_tempo_raw"].isin(TEMPO)
    )
    pairs = ordered[valid].copy()
    pairs["delta_time"] = pairs[part] - pairs[f"previous_{part}"]
    pairs["delta_carried_weight"] = (
        pairs["carried_weight_kg"] - pairs["previous_carried_weight_kg"]
    ).fillna(0)
    pairs["delta_gate_fraction"] = (
        pairs["gate_fraction"] - pairs["previous_gate_fraction"]
    ).fillna(0)
    pairs["delta_field_size"] = (pairs["field_size"] - pairs["previous_field_size"]).fillna(0)
    pairs["same_jockey"] = pairs["jockey_id"].eq(pairs["previous_jockey_id"])
    return pairs


def design_matrix(pairs: pd.DataFrame, meet: str) -> tuple[np.ndarray, list[str]]:
    tempo_levels = list("①②③④⑤") if meet == "jeju" else list("①②③④⑤⑥⑦⑧⑨")
    neutral = "③" if meet == "jeju" else "⑤"
    vectors: list[np.ndarray] = [np.ones(len(pairs))]
    labels = ["intercept"]
    for level in tempo_levels:
        if level == neutral:
            continue
        vectors.append(
            pairs["tempo_raw"].eq(level).to_numpy(float)
            - pairs["previous_tempo_raw"].eq(level).to_numpy(float)
        )
        labels.append(f"tempo_{level}")
    for condition in GOING_LEVELS[1:]:
        vectors.append(
            pairs["track_condition"].eq(condition).to_numpy(float)
            - pairs["previous_track_condition"].eq(condition).to_numpy(float)
        )
        labels.append(f"going_{condition}")
    for current, previous, label in (
        ("delta_carried_weight", None, "weight_kg"),
        ("delta_gate_fraction", None, "gate_fraction"),
        ("delta_field_size", None, "field_size"),
    ):
        del previous
        vectors.append(pairs[current].to_numpy(float))
        labels.append(label)
    vectors.append(pairs["days_apart"].to_numpy(float) / 30)
    labels.append("gap_months")
    # Differences in calendar month/year account for broad season and era
    # shifts without using the target race's section as a covariate.
    for column, values in (
        ("month", list(range(2, 13))),
        ("year", list(range(2019, 2027))),
    ):
        current = getattr(pairs["race_date"].dt, column)
        previous = getattr(pairs["previous_race_date"].dt, column)
        for value in values:
            vectors.append(current.eq(value).to_numpy(float) - previous.eq(value).to_numpy(float))
            labels.append(f"{column}_{value}")
    return np.column_stack(vectors), labels


def cluster_ols(pairs: pd.DataFrame, meet: str) -> dict[str, object]:
    x, labels = design_matrix(pairs, meet)
    y = pairs["delta_time"].to_numpy(float)
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    residual = y - x @ beta
    xtx_inv = np.linalg.pinv(x.T @ x)
    score = x * residual[:, None]
    # Pairs sharing a horse are dependent. Sandwich SE clusters on horse ID.
    grouped = pd.DataFrame(score).groupby(pairs["horse_id"].to_numpy(), sort=False).sum().to_numpy()
    covariance = xtx_inv @ (grouped.T @ grouped) @ xtx_inv
    standard_error = np.sqrt(np.clip(np.diag(covariance), 0, None))
    estimates = {
        label: {
            "estimate": round(float(value), 4),
            "horse_cluster_95": [
                round(float(value - 1.96 * se), 4),
                round(float(value + 1.96 * se), 4),
            ],
        }
        for label, value, se in zip(labels, beta, standard_error, strict=True)
        if label.startswith(("tempo_", "going_"))
    }
    return {
        "pairs": len(pairs),
        "horses": int(pairs["horse_id"].nunique()),
        "race_days": int(pairs["race_date"].nunique()),
        "same_jockey_pair_share": round(float(pairs["same_jockey"].mean()), 4),
        "r2_change_model": round(float(1 - np.sum(residual**2) / np.sum((y - y.mean()) ** 2)), 4),
        "effects": estimates,
    }


def summarize_pairs(records: pd.DataFrame, max_days: int) -> dict[str, object]:
    outputs: dict[str, object] = {}
    for part in PARTS:
        pairs = make_pairs(records, part, max_days)
        for meet in MEETS.values():
            subset = pairs[pairs["meet"] == meet]
            if len(subset) < 100:
                continue
            # One percent on each tail limits accidents and bad timing values.
            lower, upper = subset["delta_time"].quantile((0.01, 0.99))
            trimmed = subset[subset["delta_time"].between(lower, upper)]
            outputs[f"{meet}/{part}"] = {
                "untrimmed_pairs": len(subset),
                **cluster_ols(trimmed, meet),
            }
    return outputs


def main() -> None:
    records = load_runner_records()
    result = {
        "method": (
            "Same horse, same venue, exact distance and grade; adjacent "
            "observed section runs; paired time difference regressed on "
            "condition and tempo indicator changes, weight/gate/field size, "
            "time gap and season/era changes; 1% tail trim; "
            "horse-cluster sandwich intervals"
        ),
        "records": len(records),
        "windows": {str(max_days): summarize_pairs(records, max_days) for max_days in (90, 180)},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
