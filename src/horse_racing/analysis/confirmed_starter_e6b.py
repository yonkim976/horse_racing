"""Strict fold and paired evaluation contracts for sealed E6-B development work."""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from horse_racing.analysis.confirmed_starter_e5b import (
    EPSILON,
    array_sha256,
    date_cluster_bootstrap,
    evaluate_predictions,
    paired_bootstrap,
    validate_exact_keys,
    validate_prediction_frame,
)
from horse_racing.analysis.confirmed_starter_e6a_v2 import run_e6b_fold

ARMS = ("BASE_136", "CURRENT_WEIGHT_A_PREV")
EXTRA_FEATURES = (
    "condition_carried_weight_kg",
    "condition_carried_weight_rel_A",
    "condition_carried_weight_delta_prev_start",
)
PARTITIONS = {
    "F1": {
        "fit": ("2025-01-04", "2025-03-30", 2767, 259, 24),
        "tune": ("2025-04-05", "2025-04-27", 883, 84, 8),
        "calibration": ("2025-05-03", "2025-05-31", 928, 94, 9),
        "evaluation": ("2025-06-01", "2025-07-27", 1693, 172, 17),
    },
    "F2": {
        "fit": ("2025-01-04", "2025-07-27", 6271, 609, 58),
        "tune": ("2025-08-02", "2025-08-31", 877, 85, 8),
        "calibration": ("2025-09-06", "2025-09-28", 860, 84, 8),
        "evaluation": ("2025-10-04", "2025-11-02", 834, 77, 7),
    },
    "F3": {
        "fit": ("2025-01-04", "2025-11-02", 8960, 866, 82),
        "tune": ("2025-11-08", "2025-11-30", 936, 88, 8),
        "calibration": ("2025-12-06", "2025-12-28", 941, 88, 8),
        "evaluation": ("2026-01-03", "2026-02-28", 1691, 158, 15),
    },
}
METRICS = (
    "race_equal_winner_set_nll",
    "race_equal_soft_label_ce",
    "entry_equal_binary_nll",
    "entry_equal_brier",
    "top1_winner_inclusion",
    "top3_winner_inclusion",
    "top5_winner_inclusion",
)


class E6BContractError(ValueError):
    """The sealed E6-B development comparison cannot proceed."""


def partition_frame(frame: pl.DataFrame, fold: str, stage: str) -> pl.DataFrame:
    start, end, rows, races, days = PARTITIONS[fold][stage]
    selected = frame.filter(
        (pl.col("race_date_local") >= start) & (pl.col("race_date_local") <= end)
    ).sort("race_date_local", "race_id", "race_entry_id", maintain_order=True)
    observed = (
        selected.height,
        selected["race_id"].n_unique(),
        selected["race_date_local"].n_unique(),
    )
    if observed != (rows, races, days):
        raise E6BContractError(f"{fold}/{stage}: count {observed} != {(rows, races, days)}")
    if selected["race_date_local"].min() != start or selected["race_date_local"].max() != end:
        raise E6BContractError(f"{fold}/{stage}: date bounds mismatch")
    groups = group_sizes(selected)
    if len(groups) != races or int(groups.sum()) != rows:
        raise E6BContractError(f"{fold}/{stage}: group mismatch")
    return selected


def group_sizes(frame: pl.DataFrame) -> np.ndarray:
    groups = frame.group_by("race_id", maintain_order=True).len()["len"].to_numpy()
    return groups.astype(np.int32)


def verify_feature_keyset(h1: pl.DataFrame, extra: pl.DataFrame) -> None:
    validate_exact_keys(h1, extra, name="E6-B H1-vs-E6A-v2")
    if extra.height != h1.height:
        raise E6BContractError("E6-A v2 feature rows do not equal H1 denominator")
    if (
        extra.filter(
            pl.col("condition_carried_weight_delta_prev_start").is_null()
            & (pl.col("previous_start_history_status") == "previous_actual_start_weight_unverified")
        ).height
        != 17
    ):
        raise E6BContractError("17 unverified prior weights were not kept null")
    if extra.filter(
        (pl.col("previous_start_history_status") == "previous_actual_start_weight_unverified")
        & pl.col("condition_carried_weight_delta_prev_start").is_not_null()
    ).height:
        raise E6BContractError("unverified prior weight was filled")


def verify_shared_base_matrices(
    base: dict[str, np.ndarray], expanded: dict[str, np.ndarray]
) -> dict[str, Any]:
    audit = {}
    for name, matrix in base.items():
        candidate = expanded[name]
        if candidate.shape != (matrix.shape[0], matrix.shape[1] + 3):
            raise E6BContractError(f"{name}: expanded matrix shape invalid")
        if array_sha256(candidate[:, : matrix.shape[1]]) != array_sha256(matrix):
            raise E6BContractError(f"{name}: existing 136 matrix cells changed")
        audit[name] = {
            "base_sha256": array_sha256(matrix),
            "expanded_base_slice_sha256": array_sha256(candidate[:, : matrix.shape[1]]),
            "expanded_sha256": array_sha256(candidate),
            "rows": matrix.shape[0],
        }
    return audit


def orchestrate_fold(
    expected: tuple[str, str], order: tuple[str, str], prepare: Any, evaluate: Any
) -> dict[str, Any]:
    """Production fold entry point for the E6-A v2 gate; never bypass it."""
    result = run_e6b_fold(expected, order, prepare, evaluate)
    if not result.approved:
        raise E6BContractError(result.failure_reason or "E6-B common gate rejected fold")
    if result.validation_call_count != 2 or set(result.validation_results) != set(expected):
        raise E6BContractError("fold gate did not evaluate both expected arms exactly once")
    return result.validation_results


def evaluate_arm(
    expected: pl.DataFrame, predictions: pl.DataFrame, *, temperature: float, name: str
) -> dict[str, Any]:
    joined, coverage = validate_prediction_frame(expected, predictions, name=name)
    metrics, per_race = evaluate_predictions(joined, beta=1.0 / temperature)
    if metrics["rows"] != expected.height or metrics["races"] != expected["race_id"].n_unique():
        raise E6BContractError(f"{name}: evaluation denominator changed")
    return {"joined": joined, "coverage": coverage, "metrics": metrics, "per_race": per_race}


def pooled_metrics(joined: pl.DataFrame, per_race: pl.DataFrame) -> dict[str, Any]:
    """Pool already-calibrated fold losses, never recalibrating pooled margins."""
    if joined.height != 4218 or per_race.height != 407:
        raise E6BContractError("pooled evaluation denominator changed")
    if joined["race_id"].n_unique() != per_race.height:
        raise E6BContractError("pooled race denominator changed")
    probabilities = joined["prob_win"].to_numpy().astype(np.float64)
    labels = joined["win"].to_numpy().astype(np.float64)
    if not np.isfinite(probabilities).all() or not np.isin(labels, [0.0, 1.0]).all():
        raise E6BContractError("pooled prediction or label invalid")
    clipped = np.clip(probabilities, EPSILON, 1.0 - EPSILON)
    return {
        "rows": joined.height,
        "races": per_race.height,
        "race_equal_winner_set_nll": float(per_race["winner_set_nll"].mean()),
        "race_equal_soft_label_ce": float(per_race["soft_label_ce"].mean()),
        "entry_equal_binary_nll": float(
            np.mean(-(labels * np.log(clipped) + (1.0 - labels) * np.log1p(-clipped)))
        ),
        "entry_equal_brier": float(np.mean((probabilities - labels) ** 2)),
        "binary_nll_epsilon": EPSILON,
        "binary_nll_clipping_count": int(
            ((probabilities < EPSILON) | (probabilities > 1.0 - EPSILON)).sum()
        ),
        "primary_winner_set_clipping": False,
        "top1_winner_inclusion": float(per_race["top1"].mean()),
        "top3_winner_inclusion": float(per_race["top3"].mean()),
        "top5_winner_inclusion": float(per_race["top5"].mean()),
        "official_dead_heat_races": int((per_race["winner_count"] > 1).sum()),
        "score_tie_races": int(per_race["score_tie"].sum()),
        "probability_tie_races": int(per_race["probability_tie"].sum()),
        "probability_ties_at_top1_boundary": int(per_race["probability_tie_top1"].sum()),
        "probability_ties_at_top3_boundary": int(per_race["probability_tie_top3"].sum()),
        "probability_ties_at_top5_boundary": int(per_race["probability_tie_top5"].sum()),
        "probability_underflow_zero_count": int(per_race["probability_underflow_zero"].sum()),
    }


def paired_comparison(
    results: dict[str, dict[str, Any]], *, expected_races: int
) -> tuple[dict[str, Any], pl.DataFrame]:
    if set(results) != set(ARMS):
        raise E6BContractError("both arms required for paired comparison")
    base, expanded = (results[name] for name in ARMS)
    base_races = base["per_race"]
    added_races = expanded["per_race"]
    validate_exact_keys(
        base_races.select("race_id").with_columns(pl.lit(0).alias("race_entry_id")),
        added_races.select("race_id").with_columns(pl.lit(0).alias("race_entry_id")),
        name="paired-race",
    )
    paired = (
        base_races.select(
            "race_id",
            "race_date",
            pl.col("winner_set_nll").alias("base_winner_set_nll"),
            pl.col("soft_label_ce").alias("base_soft_label_ce"),
        )
        .join(
            added_races.select(
                "race_id",
                pl.col("winner_set_nll").alias("added_winner_set_nll"),
                pl.col("soft_label_ce").alias("added_soft_label_ce"),
            ),
            on="race_id",
            validate="1:1",
        )
        .with_columns(
            (pl.col("added_winner_set_nll") - pl.col("base_winner_set_nll")).alias("delta"),
            (pl.col("added_soft_label_ce") - pl.col("base_soft_label_ce")).alias(
                "soft_label_ce_delta"
            ),
        )
        .sort("race_id")
    )
    if paired.height != expected_races:
        raise E6BContractError(f"paired race denominator {paired.height} != {expected_races}")
    metrics = {name: results[name]["metrics"] for name in ARMS}
    deltas = {key: metrics[ARMS[1]][key] - metrics[ARMS[0]][key] for key in METRICS}
    summary = {
        "metrics": metrics,
        "metric_deltas_added_minus_base": deltas,
        "bootstrap": {
            "paired_race": paired_bootstrap(paired["delta"].to_numpy()),
            "race_date_cluster": date_cluster_bootstrap(paired),
        },
        "paired_rows": paired.height,
        "delta_definition": "CURRENT_WEIGHT_A_PREV - BASE_136",
        "negative_loss_delta_favors_added": True,
    }
    return summary, paired
