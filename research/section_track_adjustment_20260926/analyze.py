"""Read-only rolling-origin study of sectional-time track corrections.

Run from the repository root:
  .venv/bin/python research/section_track_adjustment_20260926/analyze.py

No operational, model, or research source database is changed. The only output
is JSON on stdout. The 2025+ Seoul closing splits are derived from official
finish and cumulative time, and are separately flagged in the output.
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
SECTION_DB = ROOT / "data/research/section_point_db_20260925/section_points_adjudicated.sqlite3"
OPERATING_DB = ROOT / "data/horse_racing.sqlite3"
MEETS = {1: "seoul", 2: "jeju", 3: "busan"}
PARTS = {"S1F": "start_200", "G1F": "last_200", "G3F": "last_600"}
TEMPO = {char: index for index, char in enumerate("①②③④⑤⑥⑦⑧⑨", 1)}
GOING = {"건조", "양호", "다습", "포화", "불량"}
VARIANTS = ("raw", "going", "tempo", "joint")


def load() -> tuple[pd.DataFrame, dict[str, object]]:
    with sqlite3.connect(f"file:{SECTION_DB}?mode=ro", uri=True) as con:
        con.execute(f"ATTACH DATABASE 'file:{OPERATING_DB}?mode=ro' AS ops")
        rows = pd.read_sql_query(
            """
            SELECT c.race_entry_id, c.meet_code, c.race_date, c.race_number,
                   c.distance_m, c.point_code, c.time_kind, c.elapsed_time_ms,
                   c.classification, re.horse_id, re.gate_number,
                   r.grade, r.track_condition, p.tempo_raw,
                   rr.finish_position, rr.finish_time_ms
            FROM common_point c
            JOIN ops.race_entries re ON re.id=c.race_entry_id
            JOIN ops.races r ON r.id=re.race_id
            JOIN ops.race_results rr ON rr.race_entry_id=c.race_entry_id
            JOIN ops.race_passing_summaries p ON p.race_id=r.id
            WHERE c.race_date>='2018-01-01' AND c.race_date<='2026-09-20'
              AND c.meet_code IN (1,2,3)
              AND c.point_code IN ('S1F','G1F','G3F')
              AND rr.finish_position BETWEEN 1 AND 20
              AND rr.finish_time_ms>0
              AND r.track_condition IN ('건조','양호','다습','포화','불량')
              AND p.tempo_raw IN ('①','②','③','④','⑤','⑥','⑦','⑧','⑨')
            """,
            con,
        )
    key = ["race_entry_id", "point_code", "time_kind"]
    duplicates = int(rows.duplicated(key).sum())
    if duplicates:
        raise ValueError(f"Unexpected duplicate section keys: {duplicates}")
    wide = rows.pivot(
        index="race_entry_id", columns=["point_code", "time_kind"], values="elapsed_time_ms"
    )
    wide.columns = [f"{point}_{kind}" for point, kind in wide.columns]
    metadata = rows.drop_duplicates("race_entry_id").set_index("race_entry_id")
    frame = metadata.join(wide)
    # A published 200m closing time is preferred. Seoul API4_3 in 2025+
    # only supplies cumulative passing times; subtraction is marked derived.
    long: list[pd.DataFrame] = []
    for point, part in PARTS.items():
        item = frame.copy()
        item["part"] = part
        direct = item.get(f"{point}_closing", pd.Series(np.nan, index=item.index))
        if point == "S1F":
            item["section_ms"] = item["S1F_cumulative"]
            item["provenance"] = "official_200m_cumulative"
        else:
            cumulative = item.get(f"{point}_cumulative", pd.Series(np.nan, index=item.index))
            item["section_ms"] = direct.fillna(item["finish_time_ms"] - cumulative)
            item["provenance"] = np.where(
                direct.notna(), "official_closing", "finish_minus_cumulative"
            )
        long.append(
            item[
                [
                    "meet_code",
                    "race_date",
                    "race_number",
                    "distance_m",
                    "horse_id",
                    "gate_number",
                    "grade",
                    "track_condition",
                    "tempo_raw",
                    "finish_position",
                    "finish_time_ms",
                    "part",
                    "section_ms",
                    "provenance",
                ]
            ].reset_index()
        )
    data = pd.concat(long, ignore_index=True)
    data["meet"] = data["meet_code"].map(MEETS)
    data["race_date"] = pd.to_datetime(data["race_date"])
    data["year"] = data["race_date"].dt.year
    data["month"] = data["race_date"].dt.month
    data["tempo_level"] = data["tempo_raw"].map(TEMPO)
    data["race_key"] = (
        data["meet"]
        + ":"
        + data["race_date"].dt.strftime("%Y-%m-%d")
        + ":"
        + data["race_number"].astype(str)
    )
    data["distance_grade"] = data["distance_m"].astype(str) + ":" + data["grade"].fillna("unknown")
    # Fixed broad physical bounds, independent of holdout-year distributions.
    bounds = {"start_200": (10, 40), "last_200": (8, 45), "last_600": (30, 100)}
    before = data.groupby(["meet", "part"], observed=True).size()
    valid = data["section_ms"].notna() & (data["section_ms"] < data["finish_time_ms"])
    for part, (lower, upper) in bounds.items():
        selected = data["part"].eq(part)
        valid &= ~selected | data["section_ms"].between(lower * 1000, upper * 1000)
    data = data[valid].copy()
    # The two closing distances must be coherent when both are available.
    closing = data[data["part"].isin(("last_200", "last_600"))].pivot(
        index="race_entry_id", columns="part", values="section_ms"
    )
    bad = closing.index[closing["last_200"].gt(closing["last_600"])].tolist()
    data = data[~data["race_entry_id"].isin(bad)].copy()
    data["section_seconds"] = data["section_ms"] / 1000
    coverage = {
        "raw_rows_after_metadata_join": len(rows),
        "runner_parts_before_filter": {f"{a}/{b}": int(n) for (a, b), n in before.items()},
        "runner_parts_after_filter": {
            f"{a}/{b}": int(n) for (a, b), n in data.groupby(["meet", "part"]).size().items()
        },
        "excluded_incoherent_runners": len(bad),
        "provenance": {
            f"{a}/{b}/{c}": int(n)
            for (a, b, c), n in data.groupby(["meet", "part", "provenance"]).size().items()
        },
        "date_min": data["race_date"].min().strftime("%Y-%m-%d"),
        "date_max": data["race_date"].max().strftime("%Y-%m-%d"),
    }
    return data, coverage


def race_pars(data: pd.DataFrame) -> pd.DataFrame:
    # Median of all valid runners is robust to one very slow/stopped horse.
    counts = (
        data.groupby(["part", "race_key"], sort=False)
        .agg(par=("section_seconds", "median"), runners=("section_seconds", "size"))
        .reset_index()
    )
    counts = counts[counts["runners"] >= 5]
    fields = [
        "meet",
        "race_date",
        "year",
        "month",
        "distance_m",
        "distance_grade",
        "track_condition",
        "tempo_raw",
    ]
    return counts.merge(
        data.drop_duplicates(["part", "race_key"])[["part", "race_key", *fields]],
        on=["part", "race_key"],
        validate="one_to_one",
    )


def prior_history(data: pd.DataFrame) -> pd.DataFrame:
    ordered = data.sort_values(
        ["meet", "part", "horse_id", "distance_m", "race_date", "race_number"]
    ).copy()
    groups = ordered.groupby(["meet", "part", "horse_id", "distance_m"], sort=False)
    for name in [
        "race_date",
        "section_seconds",
        "track_condition",
        "tempo_raw",
        "year",
        "month",
        "distance_grade",
        "provenance",
    ]:
        ordered[f"previous_{name}"] = groups[name].shift(1)
    ordered["history_days"] = (ordered["race_date"] - ordered["previous_race_date"]).dt.days
    return ordered[ordered["history_days"].between(1, 365)].copy()


def fit(train: pd.DataFrame, variant: str) -> Pipeline:
    columns = ["distance_grade", "year", "month"]
    if variant in ("going", "joint"):
        columns.append("track_condition")
    if variant in ("tempo", "joint"):
        columns.append("tempo_raw")
    model = Pipeline(
        [
            (
                "onehot",
                ColumnTransformer(
                    [("categories", OneHotEncoder(handle_unknown="ignore"), columns)]
                ),
            ),
            ("ridge", Ridge(alpha=10.0)),
        ]
    )
    model.fit(train, train["par"])
    return model


def correction(model: Pipeline, prior: pd.DataFrame, variant: str, meet: str) -> np.ndarray:
    actual = prior[
        [
            "previous_distance_grade",
            "previous_year",
            "previous_month",
            "previous_track_condition",
            "previous_tempo_raw",
        ]
    ].rename(columns=lambda name: name.removeprefix("previous_"))
    reference = actual.copy()
    if variant in ("going", "joint"):
        reference["track_condition"] = "건조"
    if variant in ("tempo", "joint"):
        reference["tempo_raw"] = "③" if meet == "jeju" else "⑤"
    return model.predict(actual) - model.predict(reference)


def per_race_pair_accuracy(data: pd.DataFrame, metric: str, target: str) -> pd.DataFrame:
    rows: list[tuple[str, pd.Timestamp, int, float]] = []
    for race_key, race in data.groupby("race_key", sort=False):
        if len(race) < 3:
            continue
        predicted = race[metric].to_numpy(float)
        actual = race[target].to_numpy(float)
        left, right = np.triu_indices(len(race), 1)
        truth = actual[left] - actual[right]
        prediction = predicted[left] - predicted[right]
        valid = truth != 0
        if valid.sum() < 3:
            continue
        products = truth[valid] * prediction[valid]
        accuracy = float(np.mean(np.where(products > 0, 1.0, np.where(products == 0, 0.5, 0.0))))
        rows.append((race_key, race["race_date"].iloc[0], len(race), accuracy))
    return pd.DataFrame(rows, columns=["race_key", "race_date", "runners", metric])


def score(
    meet: str, part: str, year: int, pars: pd.DataFrame, history: pd.DataFrame
) -> tuple[dict[str, object], pd.DataFrame]:
    training = pars[(pars["meet"] == meet) & (pars["part"] == part) & (pars["year"] < year)]
    current = history[
        (history["meet"] == meet) & (history["part"] == part) & (history["year"] == year)
    ].copy()
    current["raw"] = current["previous_section_seconds"]
    for variant in VARIANTS[1:]:
        model = fit(training, variant)
        current[variant] = current["raw"] - correction(model, current, variant, meet)
    outputs = []
    result: dict[str, object] = {
        "meet": meet,
        "part": part,
        "year": year,
        "train_races": len(training),
        "test_history_rows": len(current),
    }
    for target in ("section_seconds", "finish_position"):
        merged: pd.DataFrame | None = None
        for variant in VARIANTS:
            part_scores = per_race_pair_accuracy(current, variant, target)
            merged = (
                part_scores
                if merged is None
                else merged.merge(
                    part_scores[["race_key", variant]], on="race_key", validate="one_to_one"
                )
            )
        assert merged is not None
        merged["target"] = target
        merged["meet"] = meet
        merged["part"] = part
        merged["year"] = year
        merged = merged.merge(
            current.drop_duplicates("race_key")[["race_key", "distance_m"]],
            on="race_key",
            validate="one_to_one",
        )
        outputs.append(merged)
        result[target] = {
            "test_races": len(merged),
            "test_days": merged["race_date"].nunique(),
            "accuracy": {v: round(float(merged[v].mean()), 5) for v in VARIANTS},
        }
    return result, pd.concat(outputs, ignore_index=True)


def paired_day_bootstrap(data: pd.DataFrame, baseline: str, candidate: str) -> dict[str, object]:
    if data.empty:
        return {"delta": None, "ci_95": None}
    dates = data.groupby("race_date").agg(
        n=("race_key", "size"), delta=(candidate, "sum"), baseline=(baseline, "sum")
    )
    effect = (dates["delta"] - dates["baseline"]).to_numpy()
    counts = dates["n"].to_numpy()
    rng = np.random.default_rng(20260926)
    draws = rng.integers(0, len(dates), (2000, len(dates)))
    estimates = effect[draws].sum(1) / counts[draws].sum(1)
    return {
        "delta": round(float((data[candidate] - data[baseline]).mean()), 5),
        "ci_95": [round(float(x), 5) for x in np.quantile(estimates, [0.025, 0.975])],
    }


def summarize(scores: pd.DataFrame) -> dict[str, object]:
    output: dict[str, object] = {}
    for (meet, part, target), group in scores.groupby(["meet", "part", "target"]):
        output[f"{meet}/{part}/{target}"] = {
            "races": len(group),
            "days": group["race_date"].nunique(),
            "raw_accuracy": round(float(group["raw"].mean()), 5),
            "going_vs_raw": paired_day_bootstrap(group, "raw", "going"),
            "tempo_vs_raw": paired_day_bootstrap(group, "raw", "tempo"),
            "joint_vs_raw": paired_day_bootstrap(group, "raw", "joint"),
            "joint_vs_tempo": paired_day_bootstrap(group, "tempo", "joint"),
            "yearly": [
                {
                    "year": int(year),
                    "races": len(by_year),
                    "tempo_vs_raw": round(float((by_year["tempo"] - by_year["raw"]).mean()), 5),
                    "joint_vs_tempo": round(float((by_year["joint"] - by_year["tempo"]).mean()), 5),
                }
                for year, by_year in group.groupby("year")
            ],
            "distance": [
                {
                    "distance_m": int(distance),
                    "races": len(by_distance),
                    "tempo_vs_raw": round(
                        float((by_distance["tempo"] - by_distance["raw"]).mean()), 5
                    ),
                }
                for distance, by_distance in group.groupby("distance_m")
                if len(by_distance) >= 100
            ],
        }
    return output


def par_validation(pars: pd.DataFrame) -> dict[str, object]:
    """Does same-race going/tempo explain held-out sectional par variation?"""
    answer: dict[str, object] = {}
    for meet in MEETS.values():
        for part in PARTS.values():
            pieces = []
            for year in (2024, 2025, 2026):
                training = pars[
                    (pars["meet"] == meet) & (pars["part"] == part) & (pars["year"] < year)
                ]
                test = pars[
                    (pars["meet"] == meet) & (pars["part"] == part) & (pars["year"] == year)
                ].copy()
                for variant in VARIANTS:
                    model = fit(training, variant)
                    test[variant] = np.abs(test["par"] - model.predict(test))
                pieces.append(test)
            combined = pd.concat(pieces, ignore_index=True)
            answer[f"{meet}/{part}"] = {
                "test_races": len(combined),
                "mae_seconds": {
                    variant: round(float(combined[variant].mean()), 4) for variant in VARIANTS
                },
                "tempo_mae_reduction_vs_raw": paired_day_bootstrap(combined, "tempo", "raw"),
                "joint_mae_reduction_vs_tempo": paired_day_bootstrap(combined, "joint", "tempo"),
            }
    return answer


def fitted_environment_effects(pars: pd.DataFrame) -> dict[str, object]:
    """Descriptive second-scale effects from a pre-2026 fitted joint model."""
    answer: dict[str, object] = {}
    for meet in MEETS.values():
        for part in PARTS.values():
            training = pars[
                (pars["meet"] == meet) & (pars["part"] == part) & (pars["year"] <= 2025)
            ]
            model = fit(training, "joint")
            reference = training.iloc[[0]][
                ["distance_grade", "year", "month", "track_condition", "tempo_raw"]
            ].copy()
            reference["track_condition"] = "건조"
            reference["tempo_raw"] = "③" if meet == "jeju" else "⑤"
            neutral = float(model.predict(reference)[0])
            tempo_effects = {}
            for label in sorted(training["tempo_raw"].unique(), key=TEMPO.get):
                candidate = reference.copy()
                candidate["tempo_raw"] = label
                race_days = int(training[training["tempo_raw"] == label]["race_date"].nunique())
                tempo_effects[label] = {
                    "seconds_vs_neutral": round(float(model.predict(candidate)[0] - neutral), 4),
                    "train_days": race_days,
                }
            going_effects = {}
            for label in ("건조", "양호", "다습", "포화", "불량"):
                candidate = reference.copy()
                candidate["track_condition"] = label
                going_effects[label] = {
                    "seconds_vs_dry": round(float(model.predict(candidate)[0] - neutral), 4),
                    "train_days": int(
                        training[training["track_condition"] == label]["race_date"].nunique()
                    ),
                }
            answer[f"{meet}/{part}"] = {
                "training_races_through_2025": len(training),
                "tempo_effect_seconds": tempo_effects,
                "going_effect_seconds": going_effects,
            }
    return answer


def main() -> None:
    data, coverage = load()
    pars = race_pars(data)
    history = prior_history(data)
    results = [
        score(meet, part, year, pars, history)
        for meet in MEETS.values()
        for part in PARTS.values()
        for year in (2024, 2025, 2026)
    ]
    all_scores = pd.concat([part[1] for part in results], ignore_index=True)
    answer = {
        "definition": (
            "Same-venue, exact-distance, most recent section within 365 days; "
            "separate prior-year-fitted race-median par model per meet and "
            "section; test 2024/2025/2026; race-mean pairwise accuracy; "
            "day-block paired bootstrap"
        ),
        "coverage": coverage,
        "race_pars": len(pars),
        "history_rows": len(history),
        "test_years": [part[0] for part in results],
        "pooled": summarize(all_scores),
        "par_validation": par_validation(pars),
        "joint_effects_descriptive": fitted_environment_effects(pars),
    }
    print(json.dumps(answer, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
