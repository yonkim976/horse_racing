"""Strict evaluation helpers for the confirmed-starter E5-B study."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
import polars as pl

from horse_racing.analysis.confirmed_starter_e5_r3r4 import (
    E5R3R4ContractError,
    group_slices,
    soft_labels_from_winners,
)
from horse_racing.analysis.metrics import expected_topk_inclusion

KEY_COLUMNS = ["race_id", "race_entry_id"]
EPSILON = 1e-15
SUM_TOLERANCE = 1e-8
RELOAD_TOLERANCE = 1e-12


class E5BContractError(ValueError):
    """Raised when an E5-B input, prediction, or comparison is invalid."""


def array_sha256(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


def key_sha256(frame: pl.DataFrame) -> str:
    keys = sorted((int(a), int(b)) for a, b in frame.select(KEY_COLUMNS).iter_rows())
    return hashlib.sha256(json.dumps(keys, separators=(",", ":")).encode()).hexdigest()


def validate_exact_keys(expected: pl.DataFrame, actual: pl.DataFrame, *, name: str) -> None:
    for side, frame in (("expected", expected), ("actual", actual)):
        duplicates = frame.group_by(KEY_COLUMNS).len().filter(pl.col("len") != 1)
        if duplicates.height:
            raise E5BContractError(f"{name}: duplicate {side} keys={duplicates.height}")
    expected_keys = set(expected.select(KEY_COLUMNS).iter_rows())
    actual_keys = set(actual.select(KEY_COLUMNS).iter_rows())
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    if missing or extra:
        raise E5BContractError(f"{name}: missing={len(missing)}, extra={len(extra)}")


def validate_prediction_frame(
    expected: pl.DataFrame, predictions: pl.DataFrame, *, name: str
) -> tuple[pl.DataFrame, dict[str, Any]]:
    required = {*KEY_COLUMNS, "horse_number", "raw_margin", "prob_win"}
    absent = sorted(required - set(predictions.columns))
    if absent:
        raise E5BContractError(f"{name}: missing columns={absent}")
    validate_exact_keys(expected, predictions, name=name)
    joined = expected.join(predictions, on=KEY_COLUMNS, how="left", suffix="_prediction")
    if joined.height != expected.height:
        raise E5BContractError(f"{name}: left join changed denominator")
    horse_mismatch = joined.filter(pl.col("horse_number") != pl.col("horse_number_prediction"))
    if horse_mismatch.height:
        raise E5BContractError(f"{name}: horse_number mismatch={horse_mismatch.height}")
    raw = joined["raw_margin"].to_numpy()
    probabilities = joined["prob_win"].to_numpy()
    non_finite_raw = int((~np.isfinite(raw)).sum())
    non_finite_probability = int((~np.isfinite(probabilities)).sum())
    outside_probability = int(((probabilities < 0.0) | (probabilities > 1.0)).sum())
    if non_finite_raw or non_finite_probability or outside_probability:
        raise E5BContractError(
            f"{name}: invalid raw/probability values "
            f"{non_finite_raw=}, {non_finite_probability=}, {outside_probability=}"
        )
    sums = joined.group_by("race_id").agg(pl.col("prob_win").sum().alias("probability_sum"))
    max_sum_error = float((sums["probability_sum"] - 1.0).abs().max() or 0.0)
    if max_sum_error > SUM_TOLERANCE:
        raise E5BContractError(f"{name}: max race probability-sum error={max_sum_error}")
    return joined, {
        "expected_rows": expected.height,
        "prediction_rows": predictions.height,
        "expected_races": expected["race_id"].n_unique(),
        "missing_rows": 0,
        "extra_rows": 0,
        "duplicate_rows": 0,
        "horse_number_mismatches": 0,
        "raw_non_finite": non_finite_raw,
        "probability_non_finite": non_finite_probability,
        "probability_outside_0_1": outside_probability,
        "max_race_probability_sum_error": max_sum_error,
        "probability_sum_tolerance": SUM_TOLERANCE,
        "coverage": 1.0,
    }


def stable_race_losses(
    logits: np.ndarray, winners: np.ndarray, groups: np.ndarray, *, beta: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return soft-label CE and winner-set NLL without probability clipping."""
    scores = np.asarray(logits, dtype=np.float64)
    labels = np.asarray(winners)
    if scores.ndim != 1 or labels.shape != scores.shape or not np.isfinite(scores).all():
        raise E5BContractError("loss inputs must be same-length finite vectors")
    if not math.isfinite(beta) or beta <= 0.0:
        raise E5BContractError("beta must be finite and positive")
    try:
        q = soft_labels_from_winners(labels, groups)
        blocks = group_slices(groups, scores.size)
    except E5R3R4ContractError as exc:
        raise E5BContractError(str(exc)) from exc
    ce = np.empty(len(blocks), dtype=np.float64)
    winner_set = np.empty(len(blocks), dtype=np.float64)
    for index, block in enumerate(blocks):
        scaled = beta * (scores[block] - scores[block].max())
        all_lse = float(np.logaddexp.reduce(scaled))
        winner_lse = float(np.logaddexp.reduce(scaled[labels[block].astype(bool)]))
        ce[index] = all_lse - float(np.dot(q[block], scaled))
        winner_set[index] = all_lse - winner_lse
    if not np.isfinite(ce).all() or not np.isfinite(winner_set).all():
        raise E5BContractError("stable race loss became non-finite")
    return ce, winner_set


def _tie_at_boundary(values: list[float], k: int) -> bool:
    boundary = sorted(values, reverse=True)[min(k, len(values)) - 1]
    return values.count(boundary) > 1


def evaluate_predictions(
    joined: pl.DataFrame, *, beta: float
) -> tuple[dict[str, Any], pl.DataFrame]:
    ordered = joined.sort("race_date_local", "race_id", "race_entry_id")
    groups = ordered.group_by("race_id", maintain_order=True).len()["len"].to_numpy()
    logits = ordered["raw_margin"].to_numpy()
    winners = ordered["win"].to_numpy()
    ce, winner_set = stable_race_losses(logits, winners, groups, beta=beta)
    rows: list[dict[str, Any]] = []
    for index, race in enumerate(ordered.partition_by("race_id", maintain_order=True)):
        probabilities = [float(value) for value in race["prob_win"]]
        raw_scores = [float(value) for value in race["raw_margin"]]
        labels = [int(value) for value in race["win"]]
        rows.append(
            {
                "race_id": int(race["race_id"][0]),
                "race_date": str(race["race_date_local"][0]),
                "soft_label_ce": float(ce[index]),
                "winner_set_nll": float(winner_set[index]),
                "winner_count": sum(labels),
                "top1": expected_topk_inclusion(probabilities, labels, k=1),
                "top3": expected_topk_inclusion(probabilities, labels, k=3),
                "top5": expected_topk_inclusion(probabilities, labels, k=5),
                "score_tie": int(len(set(raw_scores)) != len(raw_scores)),
                "probability_tie": int(len(set(probabilities)) != len(probabilities)),
                "probability_tie_top1": int(_tie_at_boundary(probabilities, 1)),
                "probability_tie_top3": int(_tie_at_boundary(probabilities, 3)),
                "probability_tie_top5": int(_tie_at_boundary(probabilities, 5)),
                "probability_underflow_zero": sum(value == 0.0 for value in probabilities),
                "contains_special_state": int(
                    any(value != "normal_finish" for value in race["outcome_state"])
                ),
            }
        )
    per_race = pl.DataFrame(rows).sort("race_id")
    probabilities = np.asarray(ordered["prob_win"], dtype=np.float64)
    labels = np.asarray(winners, dtype=np.float64)
    clipped = np.clip(probabilities, EPSILON, 1.0 - EPSILON)
    binary_nll = float(np.mean(-(labels * np.log(clipped) + (1.0 - labels) * np.log1p(-clipped))))
    metrics = {
        "rows": ordered.height,
        "races": per_race.height,
        "race_equal_winner_set_nll": float(per_race["winner_set_nll"].mean()),
        "race_equal_soft_label_ce": float(per_race["soft_label_ce"].mean()),
        "entry_equal_binary_nll": binary_nll,
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
    return metrics, per_race


def paired_bootstrap(
    deltas: np.ndarray, *, iterations: int = 5000, seed: int = 20260911
) -> dict[str, Any]:
    values = np.asarray(deltas, dtype=np.float64)
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations, dtype=np.float64)
    for index in range(iterations):
        samples[index] = rng.choice(values, len(values), replace=True).mean()
    return _bootstrap_summary(values, samples, "race", iterations, seed)


def date_cluster_bootstrap(
    paired: pl.DataFrame, *, iterations: int = 5000, seed: int = 20260911
) -> dict[str, Any]:
    blocks = [block["delta"].to_numpy() for block in paired.partition_by("race_date")]
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations, dtype=np.float64)
    for index in range(iterations):
        selected = rng.integers(0, len(blocks), len(blocks))
        samples[index] = np.concatenate([blocks[item] for item in selected]).mean()
    result = _bootstrap_summary(
        paired["delta"].to_numpy(), samples, "race_date_cluster", iterations, seed
    )
    result["blocks"] = len(blocks)
    result["cluster_policy"] = "all races on each sampled date retained"
    return result


def _bootstrap_summary(
    values: np.ndarray, samples: np.ndarray, unit: str, iterations: int, seed: int
) -> dict[str, Any]:
    return {
        "unit": unit,
        "iterations": iterations,
        "seed": seed,
        "observed_mean": float(values.mean()),
        "percentile_95_ci": [
            float(np.quantile(samples, 0.025)),
            float(np.quantile(samples, 0.975)),
        ],
        "fraction_bootstrap_deltas_below_zero": float(np.mean(samples < 0.0)),
    }
