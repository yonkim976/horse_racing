"""Frozen-score diagnostics for the confirmed-starter E4 study."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl

from horse_racing.analysis.confirmed_starter_e3 import (
    EPSILON,
    E3ContractError,
    validate_exact_keys,
)
from horse_racing.analysis.metrics import brier_score, expected_topk_inclusion, log_loss

KEY_COLUMNS = ["race_id", "race_entry_id"]
SUM_TOLERANCE = 1e-8


class E4ContractError(E3ContractError):
    """Raised when a frozen E4 input or declared diagnostic violates its contract."""


def race_softmax_loss_grad_hess_diag(
    logits: np.ndarray, soft_labels: np.ndarray
) -> tuple[float, np.ndarray, np.ndarray]:
    """Return soft-label CE, its exact gradient, and diagonal Hessian.

    The complete Hessian is ``diag(p) - p p.T``. The returned diagonal is exact
    elementwise but is only a diagonal approximation when consumed by a tree learner.
    """
    logits = np.asarray(logits, dtype=float)
    soft_labels = np.asarray(soft_labels, dtype=float)
    if logits.ndim != 1 or logits.shape != soft_labels.shape or logits.size == 0:
        raise ValueError("logits and soft_labels must be same-length non-empty vectors")
    if not np.isfinite(logits).all() or not np.isfinite(soft_labels).all():
        raise ValueError("logits and soft_labels must be finite")
    if (soft_labels < 0).any() or not np.isclose(soft_labels.sum(), 1.0, atol=1e-12):
        raise ValueError("soft_labels must be nonnegative and sum to one")
    shifted = logits - logits.max()
    exp_shifted = np.exp(shifted)
    probabilities = exp_shifted / exp_shifted.sum()
    logsumexp = logits.max() + math.log(float(exp_shifted.sum()))
    loss = float(logsumexp - np.dot(soft_labels, logits))
    gradient = probabilities - soft_labels
    hessian_diagonal = probabilities * (1.0 - probabilities)
    return loss, gradient, hessian_diagonal


def validate_win_output(
    expected: pl.DataFrame, output: pl.DataFrame, *, name: str
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Validate an output against the full denominator and return a left-joined frame."""
    required = {*KEY_COLUMNS, "horse_number", "prob_win"}
    missing_columns = sorted(required - set(output.columns))
    if missing_columns:
        raise E4ContractError(f"{name}: missing columns={missing_columns}")
    try:
        validate_exact_keys(expected, output, name=name)
    except E3ContractError as exc:
        raise E4ContractError(str(exc)) from exc
    joined = expected.join(output, on=KEY_COLUMNS, how="left", suffix="_prediction")
    if joined.height != expected.height:
        raise E4ContractError(f"{name}: left join changed denominator")
    if joined.filter(pl.col("horse_number") != pl.col("horse_number_prediction")).height:
        raise E4ContractError(f"{name}: horse_number mismatch")
    values = np.asarray(joined["prob_win"], dtype=float)
    non_finite = int((~np.isfinite(values)).sum())
    outside = int(((values < 0.0) | (values > 1.0)).sum())
    sums = joined.group_by("race_id").agg(pl.col("prob_win").sum().alias("prob_sum"))
    max_sum_error = float((sums["prob_sum"] - 1.0).abs().max() or 0.0)
    if non_finite or outside or max_sum_error > SUM_TOLERANCE:
        raise E4ContractError(
            f"{name}: non_finite={non_finite}, outside={outside}, "
            f"max_race_sum_error={max_sum_error}"
        )
    return joined, {
        "expected_rows": expected.height,
        "output_rows": output.height,
        "missing_rows": 0,
        "extra_rows": 0,
        "duplicate_keys": 0,
        "non_finite": non_finite,
        "outside_0_1": outside,
        "max_race_sum_error": max_sum_error,
        "sum_tolerance": SUM_TOLERANCE,
    }


def win_metrics(joined: pl.DataFrame) -> tuple[dict[str, Any], pl.DataFrame]:
    """Calculate E4 win-head metrics, including result-independent expected TopK."""
    race_rows: list[dict[str, Any]] = []
    for race in joined.partition_by("race_id", maintain_order=True):
        probabilities = race["prob_win"].to_list()
        winners = race["win"].cast(pl.Int64).to_list()
        winner_probability = sum(
            probability
            for probability, winner in zip(probabilities, winners, strict=True)
            if winner
        )
        race_rows.append(
            {
                "race_id": int(race["race_id"][0]),
                "race_date": str(race["race_date_local"][0]),
                "winner_nll": -math.log(max(winner_probability, EPSILON)),
                "winner_probability": winner_probability,
                "winner_probability_clipped": int(winner_probability < EPSILON),
                "winner_zero_probability": int(winner_probability == 0.0),
                "top1": expected_topk_inclusion(probabilities, winners, k=1),
                "top3": expected_topk_inclusion(probabilities, winners, k=3),
                "top5": expected_topk_inclusion(probabilities, winners, k=5),
                "contains_special_state": int(
                    any(value != "normal_finish" for value in race["outcome_state"])
                ),
            }
        )
    per_race = pl.DataFrame(race_rows).sort("race_id")
    probabilities = joined["prob_win"].to_list()
    labels = joined["win"].cast(pl.Int64).to_list()
    return {
        "rows": joined.height,
        "races": per_race.height,
        "race_equal_weight_winner_set_nll": float(per_race["winner_nll"].mean()),
        "win_binary_log_loss": log_loss(probabilities, labels),
        "win_brier": brier_score(probabilities, labels),
        "top1_winner_inclusion": float(per_race["top1"].mean()),
        "top3_winner_inclusion": float(per_race["top3"].mean()),
        "top5_winner_inclusion": float(per_race["top5"].mean()),
        "zero_probability_rows": int(sum(value == 0.0 for value in probabilities)),
        "one_probability_rows": int(sum(value == 1.0 for value in probabilities)),
        "winner_zero_probability_races": int(per_race["winner_zero_probability"].sum()),
        "winner_set_clipping_count": int(per_race["winner_probability_clipped"].sum()),
        "binary_clipping_count": int(
            sum(value < EPSILON or value > 1.0 - EPSILON for value in probabilities)
        ),
    }, per_race


def boundary_state(probabilities: list[float], k: int) -> dict[str, Any]:
    """Describe the exact tie group containing a TopK selection boundary."""
    effective_k = min(k, len(probabilities))
    boundary = sorted(probabilities, reverse=True)[effective_k - 1]
    above = sum(value > boundary for value in probabilities)
    tied = sum(value == boundary for value in probabilities)
    return {
        "k": k,
        "effective_k": effective_k,
        "boundary_probability": boundary,
        "count_above": above,
        "tie_group_size": tied,
        "crosses_boundary": above < effective_k < above + tied,
        "tie_group_ends_at_boundary": tied > 1 and above + tied == effective_k,
    }


def tie_and_rank_diagnostics(
    expected: pl.DataFrame,
    raw_output: pl.DataFrame,
    calibrated_output: pl.DataFrame,
) -> tuple[dict[str, Any], pl.DataFrame]:
    """Separate exact raw ties, newly created ties, and strict rank inversions."""
    validate_exact_keys(raw_output, calibrated_output, name="tie-rank-inputs")
    joined = (
        expected.select("race_id", "race_entry_id", "win")
        .join(raw_output.select(*KEY_COLUMNS, pl.col("prob_win").alias("raw")), on=KEY_COLUMNS)
        .join(
            calibrated_output.select(*KEY_COLUMNS, pl.col("prob_win").alias("calibrated")),
            on=KEY_COLUMNS,
        )
    )
    strict_inversions = 0
    raw_tie_pairs = 0
    new_tie_pairs = 0
    race_rows: list[dict[str, Any]] = []
    for race in joined.partition_by("race_id", maintain_order=True):
        raw = race["raw"].to_list()
        calibrated = race["calibrated"].to_list()
        winners = race["win"].cast(pl.Int64).to_list()
        race_inversions = 0
        race_raw_ties = 0
        race_new_ties = 0
        for left in range(len(raw)):
            for right in range(left + 1, len(raw)):
                raw_delta = raw[left] - raw[right]
                calibrated_delta = calibrated[left] - calibrated[right]
                race_raw_ties += int(raw_delta == 0.0)
                race_new_ties += int(raw_delta != 0.0 and calibrated_delta == 0.0)
                race_inversions += int(raw_delta * calibrated_delta < 0.0)
        strict_inversions += race_inversions
        raw_tie_pairs += race_raw_ties
        new_tie_pairs += race_new_ties
        row: dict[str, Any] = {
            "race_id": int(race["race_id"][0]),
            "strict_inversion_pairs": race_inversions,
            "raw_tie_pairs": race_raw_ties,
            "new_tie_pairs": race_new_ties,
        }
        for k in (1, 3, 5):
            raw_boundary = boundary_state(raw, k)
            calibrated_boundary = boundary_state(calibrated, k)
            raw_topk = expected_topk_inclusion(raw, winners, k=k)
            calibrated_topk = expected_topk_inclusion(calibrated, winners, k=k)
            changed_partition = (raw_boundary["count_above"], raw_boundary["tie_group_size"]) != (
                calibrated_boundary["count_above"],
                calibrated_boundary["tie_group_size"],
            )
            row.update(
                {
                    f"raw_boundary_crosses_top{k}": int(raw_boundary["crosses_boundary"]),
                    f"raw_boundary_tie_ends_top{k}": int(
                        raw_boundary["tie_group_ends_at_boundary"]
                    ),
                    f"calibrated_boundary_crosses_top{k}": int(
                        calibrated_boundary["crosses_boundary"]
                    ),
                    f"calibrated_boundary_tie_ends_top{k}": int(
                        calibrated_boundary["tie_group_ends_at_boundary"]
                    ),
                    f"boundary_partition_changed_top{k}": int(changed_partition),
                    f"top{k}_delta": calibrated_topk - raw_topk,
                    f"top{k}_change_explained_by_boundary": int(
                        calibrated_topk == raw_topk or changed_partition
                    ),
                }
            )
        race_rows.append(row)
    per_race = pl.DataFrame(race_rows).sort("race_id")
    summary: dict[str, Any] = {
        "strict_inversion_pairs": strict_inversions,
        "raw_tie_pairs": raw_tie_pairs,
        "new_tie_pairs": new_tie_pairs,
    }
    for prefix in ("raw", "calibrated"):
        for k in (1, 3, 5):
            summary[f"{prefix}_boundary_crossing_races_top{k}"] = int(
                per_race[f"{prefix}_boundary_crosses_top{k}"].sum()
            )
            summary[f"{prefix}_boundary_tie_ends_races_top{k}"] = int(
                per_race[f"{prefix}_boundary_tie_ends_top{k}"].sum()
            )
    for k in (1, 3, 5):
        changed = per_race.filter(pl.col(f"top{k}_delta") != 0.0)
        unexplained = changed.filter(pl.col(f"boundary_partition_changed_top{k}") == 0)
        summary[f"top{k}_changed_races"] = changed.height
        summary[f"top{k}_unexplained_changed_races"] = unexplained.height
    return summary, per_race


def decompose_race_nll(
    raw_n: pl.DataFrame,
    raw_a: pl.DataFrame,
    final_n: pl.DataFrame,
    final_a: pl.DataFrame,
) -> tuple[pl.DataFrame, dict[str, float]]:
    """Create the frozen-tree arithmetic decomposition and verify its identity."""
    columns = ["race_id", "winner_nll", "contains_special_state"]
    result = (
        raw_n.select(columns)
        .rename({"winner_nll": "raw_n_nll"})
        .join(
            raw_a.select("race_id", pl.col("winner_nll").alias("raw_a_nll")),
            on="race_id",
            validate="1:1",
        )
        .join(
            final_n.select("race_id", pl.col("winner_nll").alias("final_n_nll")),
            on="race_id",
            validate="1:1",
        )
        .join(
            final_a.select("race_id", pl.col("winner_nll").alias("final_a_nll")),
            on="race_id",
            validate="1:1",
        )
        .with_columns(
            (pl.col("final_a_nll") - pl.col("final_n_nll")).alias("final_a_minus_final_n"),
            (pl.col("raw_a_nll") - pl.col("raw_n_nll")).alias("raw_a_minus_raw_n"),
            (pl.col("final_a_nll") - pl.col("raw_a_nll")).alias("a_calibration_effect"),
            (pl.col("final_n_nll") - pl.col("raw_n_nll")).alias("n_calibration_effect"),
        )
        .with_columns(
            (
                pl.col("raw_a_minus_raw_n")
                + pl.col("a_calibration_effect")
                - pl.col("n_calibration_effect")
            ).alias("decomposed_delta")
        )
        .with_columns(
            (pl.col("final_a_minus_final_n") - pl.col("decomposed_delta")).alias("identity_error")
        )
        .sort("race_id")
    )
    return result, {
        "mean_final_a_minus_final_n": float(result["final_a_minus_final_n"].mean()),
        "mean_raw_a_minus_raw_n": float(result["raw_a_minus_raw_n"].mean()),
        "mean_a_calibration_effect": float(result["a_calibration_effect"].mean()),
        "mean_n_calibration_effect": float(result["n_calibration_effect"].mean()),
        "mean_decomposed_delta": float(result["decomposed_delta"].mean()),
        "max_absolute_identity_error": float(result["identity_error"].abs().max() or 0.0),
    }
