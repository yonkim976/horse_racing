"""Synthetic, source-free checks for the G47 audit consumer contract."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from gate_pace_input_contract import FEATURE_COLUMNS, validate_audited_inputs


ARTIFACT_PATH = "jeju/research/20261025_s_gate_pace_interaction_v1/audit/gate_pace_features.parquet"
ARTIFACT_BYTES = 512
ARTIFACT_SHA = "a" * 64
NUMERIC_RULES = {"cutoff_lag_days": 2, "lookback_days": 730, "max_history_slots": 10,
                 "prior_positive": 1, "prior_strength": 3, "adjacent_number_gap": 1}


def _q(mean: float | None, count: int) -> float:
    return ((0.0 if count == 0 else float(mean)) * count + 1.0) / (count + 3.0)


def _make_race(race_id: str, first_api_id: int, horses: list[dict[str, Any]],
               race_date: date = date(2020, 1, 10)) -> list[dict[str, Any]]:
    field_n = len(horses)
    rows: list[dict[str, Any]] = []
    for pos, horse in enumerate(sorted(horses, key=lambda item: item["number"])):
        number, mean, count, slots = horse["number"], horse["mean"], horse["n"], horse["slots"]
        api_id = first_api_id + pos
        q = _q(mean, count)
        history_dates = [(race_date - timedelta(days=2 + i)).isoformat() for i in range(slots)]
        history_ids = [api_id * 100 + i for i in range(slots)]
        row: dict[str, Any] = {
            "api_record_id": api_id, "race_id": race_id, "race_date": race_date.isoformat(),
            "horse_id": f"H{race_id}-{number}", "horse_number": number, "field_n": field_n,
            "race_distance_m": 800, "h10_s1f_0_mean": np.nan if count == 0 else mean,
            "h10_s1f_0_n": count, "h10_slots": slots, "early_tendency_q": q,
            "history_cutoff": (race_date - timedelta(days=2)).isoformat(),
            "history_lower": (race_date - timedelta(days=730)).isoformat(),
            "h10_ids": history_ids, "h10_dates": history_dates,
        }
        rows.append(row)

    number_to_row = {row["horse_number"]: row for row in rows}
    for row in rows:
        b = row["horse_number"]
        rivals = {
            "inner": [x for x in rows if x["horse_number"] < b],
            "outer": [x for x in rows if x["horse_number"] > b],
            "adjacent_inner": [x for x in rows if x["horse_number"] == b - 1],
            "adjacent_outer": [x for x in rows if x["horse_number"] == b + 1],
        }
        row["pace_own_early_tendency"] = row["early_tendency_q"]
        row["pace_own_label_support_fraction_max10"] = row["h10_s1f_0_n"] / 10.0
        row["pace_inner_interaction"] = row["early_tendency_q"] * sum(x["early_tendency_q"] for x in rivals["inner"])
        row["pace_outer_interaction"] = row["early_tendency_q"] * sum(x["early_tendency_q"] for x in rivals["outer"])
        row["pace_adjacent_inner_interaction"] = row["early_tendency_q"] * sum(x["early_tendency_q"] for x in rivals["adjacent_inner"])
        row["pace_adjacent_outer_interaction"] = row["early_tendency_q"] * sum(x["early_tendency_q"] for x in rivals["adjacent_outer"])
        opponents = [x for x in rows if x["api_record_id"] != row["api_record_id"]]
        row["pace_opponent_observed_fraction"] = (
            sum(x["h10_s1f_0_n"] > 0 for x in opponents) / len(opponents) if opponents else 0.0
        )
        for prefix, peers in rivals.items():
            ordered = sorted(peers, key=lambda x: x["horse_number"])
            row[f"{prefix}_rival_api_record_ids"] = [x["api_record_id"] for x in ordered]
            row[f"{prefix}_rival_horse_ids"] = [x["horse_id"] for x in ordered]
            row[f"{prefix}_rival_horse_numbers"] = [x["horse_number"] for x in ordered]
            row[f"{prefix}_rival_h10_s1f_0_n"] = [x["h10_s1f_0_n"] for x in ordered]
            row[f"{prefix}_rival_support"] = [x["h10_s1f_0_n"] > 0 for x in ordered]
            row[f"{prefix}_rival_q"] = [x["early_tendency_q"] for x in ordered]
            row[f"{prefix}_rival_q_sum"] = sum(x["early_tendency_q"] for x in ordered)
    return rows


def _contract(rows: int, races: int) -> dict[str, Any]:
    return {
        "spec_id": "s_gate_pace_v1_7f",
        "feature_columns": list(FEATURE_COLUMNS),
        "input_artifact": {"path": ARTIFACT_PATH, "bytes": ARTIFACT_BYTES,
                           "sha256": ARTIFACT_SHA, "rows": rows},
        "source_references": [{"path": "jeju/research/20261021_phase_pace_prediction_v1/outputs/features_and_targets.parquet",
                               "bytes": 2048, "sha256": "b" * 64, "role": "historical phase inputs"}],
        "numeric_rules": dict(NUMERIC_RULES),
        "support": {"rows": rows, "races": races},
        "limitations": ["synthetic fixture; no publication-time evidence"],
    }


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    # Three horses allow a clean inside/outside exchange around number 3.
    rows += _make_race("exchange_a", 100, [
        {"number": 2, "mean": 0.0, "n": 1, "slots": 1},
        {"number": 3, "mean": 0.5, "n": 2, "slots": 2},
        {"number": 4, "mean": 1.0, "n": 3, "slots": 3},
    ])
    rows += _make_race("exchange_b", 200, [
        {"number": 2, "mean": 1.0, "n": 3, "slots": 3},
        {"number": 3, "mean": 0.5, "n": 2, "slots": 2},
        {"number": 4, "mean": 0.0, "n": 1, "slots": 1},
    ])
    # Number 5 has a missing 3 but actual adjacent runners at 4 and 6.
    rows += _make_race("gapped", 300, [
        {"number": 2, "mean": None, "n": 0, "slots": 0},
        {"number": 4, "mean": 0.25, "n": 2, "slots": 2},
        {"number": 5, "mean": 0.5, "n": 1, "slots": 1},
        {"number": 6, "mean": 0.75, "n": 3, "slots": 3},
    ])
    # One-runner fixture makes self-exclusion and empty-peer handling explicit.
    rows += _make_race("self_only", 400, [
        {"number": 1, "mean": None, "n": 0, "slots": 0},
    ])
    audit = pd.DataFrame(rows)
    target = audit.loc[:, ["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "field_n"]].copy()
    target["distance_m"] = 800
    return target, audit


def _validate(target: pd.DataFrame, audit: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    return validate_audited_inputs(
        target, audit, _contract(len(target), int(target.race_id.nunique())),
        artifact_path=ARTIFACT_PATH, artifact_bytes=ARTIFACT_BYTES,
        artifact_sha256=ARTIFACT_SHA, expected_rows=len(target),
        expected_races=int(target.race_id.nunique()),
    )


def _must_fail(target: pd.DataFrame, audit: pd.DataFrame) -> None:
    try:
        _validate(target, audit)
    except (ValueError, TypeError):
        return
    raise AssertionError("malformed synthetic contract unexpectedly passed")


def run_tests() -> dict[str, Any]:
    target, audit = _frames()
    model, receipt = _validate(target, audit)
    assert list(model.columns) == ["api_record_id", "race_id", *FEATURE_COLUMNS]
    assert receipt["status"] == "PASS_AUDITED_G47_INPUTS"

    five = audit.loc[audit.race_id.eq("gapped") & audit.horse_number.eq(5)].iloc[0]
    assert five.adjacent_inner_rival_horse_numbers == [4]
    assert five.adjacent_outer_rival_horse_numbers == [6]
    assert 2 not in five.adjacent_inner_rival_horse_numbers
    assert 5 not in five.inner_rival_horse_numbers + five.outer_rival_horse_numbers
    assert five.pace_adjacent_inner_interaction > 0 and five.pace_adjacent_outer_interaction > 0

    no_history = audit.loc[audit.race_id.eq("gapped") & audit.horse_number.eq(2)].iloc[0]
    assert np.isnan(no_history.h10_s1f_0_mean)
    assert no_history.early_tendency_q == 1 / 3
    assert no_history.pace_own_label_support_fraction_max10 == 0.0
    assert no_history.pace_opponent_observed_fraction == 1.0
    one_history = audit.loc[audit.race_id.eq("gapped") & audit.horse_number.eq(5)].iloc[0]
    assert one_history.pace_own_label_support_fraction_max10 == 0.1
    singleton = audit.loc[audit.race_id.eq("self_only")].iloc[0]
    assert singleton.pace_inner_interaction == singleton.pace_outer_interaction == 0.0
    assert singleton.pace_opponent_observed_fraction == 0.0

    a = audit.loc[audit.race_id.eq("exchange_a") & audit.horse_number.eq(3)].iloc[0]
    b = audit.loc[audit.race_id.eq("exchange_b") & audit.horse_number.eq(3)].iloc[0]
    assert a.pace_inner_interaction < b.pace_inner_interaction
    assert a.pace_outer_interaction > b.pace_outer_interaction
    assert np.isclose(a.pace_inner_interaction, b.pace_outer_interaction, atol=1e-12)
    assert np.isclose(a.pace_outer_interaction, b.pace_inner_interaction, atol=1e-12)

    corrupted = audit.copy(deep=True)
    idx = corrupted.index[corrupted.race_id.eq("gapped") & corrupted.horse_number.eq(5)][0]
    corrupted.at[idx, "adjacent_inner_rival_horse_numbers"] = [2]
    _must_fail(target, corrupted)
    leaked = audit.copy(deep=True)
    idx = leaked.index[leaked.race_id.eq("exchange_a") & leaked.horse_number.eq(3)][0]
    leaked.at[idx, "h10_dates"] = ["2020-01-09", "2020-01-10"]
    _must_fail(target, leaked)
    wrong_q = audit.copy(deep=True)
    idx = wrong_q.index[wrong_q.race_id.eq("gapped") & wrong_q.horse_number.eq(5)][0]
    wrong_q.at[idx, "early_tendency_q"] = 0.0
    _must_fail(target, wrong_q)
    return {"status": "PASS_SYNTHETIC", "cases": 5, "fit_calls": 0,
            "source_rows_read": 0, "candidate_probabilities_or_outcomes": False,
            "feature_columns": list(FEATURE_COLUMNS)}


if __name__ == "__main__":
    print(run_tests())
