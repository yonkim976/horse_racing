"""Strict evaluation helpers for the confirmed-starter E3 N-vs-A study."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
import polars as pl

from horse_racing.analysis.metrics import brier_score, expected_topk_inclusion, log_loss

KEY_COLUMNS = ["race_id", "race_entry_id"]
PROBABILITY_COLUMNS = ["prob_win", "prob_top2", "prob_top3"]
EPSILON = 1e-15
SUM_TOLERANCE = 1e-8


class E3ContractError(ValueError):
    """Raised when an E3 input, prediction, or paired comparison is incomplete."""


def sha256_file(path: Any) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def key_sha256(frame: pl.DataFrame) -> str:
    keys = sorted((int(race), int(entry)) for race, entry in frame.select(KEY_COLUMNS).iter_rows())
    payload = json.dumps(keys, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_exact_keys(expected: pl.DataFrame, actual: pl.DataFrame, *, name: str) -> None:
    for label, frame in (("expected", expected), ("actual", actual)):
        duplicates = frame.group_by(KEY_COLUMNS).len().filter(pl.col("len") != 1)
        if duplicates.height:
            raise E3ContractError(f"{name}: duplicate {label} keys={duplicates.height}")
    expected_keys = set(expected.select(KEY_COLUMNS).iter_rows())
    actual_keys = set(actual.select(KEY_COLUMNS).iter_rows())
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    if missing or extra:
        raise E3ContractError(f"{name}: missing={len(missing)}, extra={len(extra)}")


def validate_predictions(
    expected: pl.DataFrame, predictions: pl.DataFrame, *, name: str
) -> tuple[pl.DataFrame, dict[str, Any]]:
    required = {*KEY_COLUMNS, "horse_number", *PROBABILITY_COLUMNS}
    missing_columns = sorted(required - set(predictions.columns))
    if missing_columns:
        raise E3ContractError(f"{name}: missing prediction columns={missing_columns}")
    validate_exact_keys(expected, predictions, name=name)
    joined = expected.join(predictions, on=KEY_COLUMNS, how="left", suffix="_prediction")
    if joined.height != expected.height:
        raise E3ContractError(f"{name}: left join changed denominator")
    if joined.filter(pl.col("horse_number") != pl.col("horse_number_prediction")).height:
        raise E3ContractError(f"{name}: horse_number mismatch")

    probability_checks: dict[str, Any] = {}
    target_totals = {"prob_win": 1.0, "prob_top2": 2.0, "prob_top3": 3.0}
    for column in PROBABILITY_COLUMNS:
        values = np.asarray(joined[column], dtype=float)
        non_finite = int((~np.isfinite(values)).sum())
        outside = int(((values < 0) | (values > 1)).sum())
        if non_finite or outside:
            raise E3ContractError(
                f"{name}: {column} non_finite={non_finite}, outside_0_1={outside}"
            )
        sums = joined.group_by("race_id").agg(
            pl.col(column).sum().alias("sum"), pl.len().alias("starters")
        )
        errors = (
            sums["sum"] - sums["starters"].cast(pl.Float64).clip(upper_bound=target_totals[column])
        ).abs()
        max_error = float(errors.max() or 0.0)
        if max_error > SUM_TOLERANCE:
            raise E3ContractError(f"{name}: {column} max race-sum error={max_error}")
        probability_checks[column] = {
            "non_finite": non_finite,
            "outside_0_1": outside,
            "max_race_sum_error": max_error,
            "sum_tolerance": SUM_TOLERANCE,
        }
    return joined, {
        "expected_rows": expected.height,
        "prediction_rows": predictions.height,
        "missing_rows": 0,
        "extra_rows": 0,
        "coverage": 1.0,
        "probabilities": probability_checks,
    }


def validate_pre_normalization(
    raw: np.ndarray, calibrated: np.ndarray, *, arm: str, target: str
) -> dict[str, int]:
    result = {
        "raw_non_finite": int((~np.isfinite(raw)).sum()),
        "calibrated_non_finite": int((~np.isfinite(calibrated)).sum()),
    }
    if any(result.values()):
        raise E3ContractError(f"{arm}/{target}: non-finite before normalization: {result}")
    return result


def _probability_tie_at_boundary(probabilities: list[float], k: int) -> bool:
    boundary = sorted(probabilities, reverse=True)[min(k, len(probabilities)) - 1]
    return probabilities.count(boundary) > 1


def evaluate_validation(joined: pl.DataFrame) -> tuple[dict[str, Any], pl.DataFrame]:
    race_rows: list[dict[str, Any]] = []
    for race in joined.partition_by("race_id", maintain_order=True):
        probabilities = race["prob_win"].to_list()
        winners = race["win"].cast(pl.Int64).to_list()
        winner_probability = sum(
            probability
            for probability, winner in zip(probabilities, winners, strict=True)
            if winner
        )
        clipped = winner_probability < EPSILON
        race_rows.append(
            {
                "race_id": int(race["race_id"][0]),
                "race_date": str(race["race_date_local"][0]),
                "winner_nll": -math.log(max(winner_probability, EPSILON)),
                "winner_probability": winner_probability,
                "winner_probability_clipped": int(clipped),
                "top1": expected_topk_inclusion(probabilities, winners, k=1),
                "top3": expected_topk_inclusion(probabilities, winners, k=3),
                "top5": expected_topk_inclusion(probabilities, winners, k=5),
                "winner_count": sum(winners),
                "probability_tie_top1": int(_probability_tie_at_boundary(probabilities, 1)),
                "probability_tie_top3": int(_probability_tie_at_boundary(probabilities, 3)),
                "probability_tie_top5": int(_probability_tie_at_boundary(probabilities, 5)),
                "contains_special_state": int(
                    any(state != "normal_finish" for state in race["outcome_state"])
                ),
            }
        )
    per_race = pl.DataFrame(race_rows).sort("race_id")
    metrics: dict[str, Any] = {
        "rows": joined.height,
        "races": per_race.height,
        "race_equal_weight_winner_set_nll": float(per_race["winner_nll"].mean()),
        "winner_set_epsilon": EPSILON,
        "winner_set_clipping_count": int(per_race["winner_probability_clipped"].sum()),
        "top1_winner_inclusion": float(per_race["top1"].mean()),
        "top3_winner_inclusion": float(per_race["top3"].mean()),
        "top5_winner_inclusion": float(per_race["top5"].mean()),
        "official_dead_heat_races": int(per_race.filter(pl.col("winner_count") > 1).height),
        "probability_ties_at_top1_boundary": int(per_race["probability_tie_top1"].sum()),
        "probability_ties_at_top3_boundary": int(per_race["probability_tie_top3"].sum()),
        "probability_ties_at_top5_boundary": int(per_race["probability_tie_top5"].sum()),
        "binary_metrics_weighting": "entry-row equal weight",
    }
    for target in ("win", "top2", "top3"):
        probabilities = joined[f"prob_{target}"].to_list()
        labels = joined[target].cast(pl.Int64).to_list()
        metrics[f"{target}_binary_log_loss"] = log_loss(probabilities, labels)
        metrics[f"{target}_brier"] = brier_score(probabilities, labels)
        metrics[f"{target}_binary_clipping_count"] = sum(
            probability < EPSILON or probability > 1 - EPSILON for probability in probabilities
        )
    violations_win_top2 = joined.filter(pl.col("prob_win") > pl.col("prob_top2")).height
    violations_top2_top3 = joined.filter(pl.col("prob_top2") > pl.col("prob_top3")).height
    metrics["head_order_diagnostic"] = {
        "prob_win_gt_prob_top2": violations_win_top2,
        "prob_top2_gt_prob_top3": violations_top2_top3,
        "values_modified": False,
    }
    return metrics, per_race


def paired_bootstrap(
    paired: pl.DataFrame, *, iterations: int = 5000, seed: int = 20260911
) -> dict[str, Any]:
    values = np.asarray(paired["delta_a_minus_n"], dtype=float)
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations)
    for index in range(iterations):
        samples[index] = rng.choice(values, len(values), replace=True).mean()
    return {
        "unit": "race",
        "iterations": iterations,
        "seed": seed,
        "observed_mean": float(values.mean()),
        "percentile_95_ci": [
            float(np.quantile(samples, 0.025)),
            float(np.quantile(samples, 0.975)),
        ],
        "fraction_bootstrap_deltas_below_zero": float(np.mean(samples < 0)),
    }


def paired_date_cluster_bootstrap(
    paired: pl.DataFrame, *, iterations: int = 5000, seed: int = 20260911
) -> dict[str, Any]:
    blocks = [
        np.asarray(block["delta_a_minus_n"], dtype=float)
        for block in paired.partition_by("race_date", maintain_order=True)
    ]
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations)
    for index in range(iterations):
        choices = rng.integers(0, len(blocks), len(blocks))
        samples[index] = np.concatenate([blocks[item] for item in choices]).mean()
    values = np.asarray(paired["delta_a_minus_n"], dtype=float)
    return {
        "unit": "race_date cluster; all races on sampled dates retained",
        "blocks": len(blocks),
        "iterations": iterations,
        "seed": seed,
        "observed_mean": float(values.mean()),
        "percentile_95_ci": [
            float(np.quantile(samples, 0.025)),
            float(np.quantile(samples, 0.975)),
        ],
        "fraction_bootstrap_deltas_below_zero": float(np.mean(samples < 0)),
    }
