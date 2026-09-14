"""E7-B-only arm, twelve-column and paired-evaluation contracts."""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from horse_racing.analysis.confirmed_starter_e5b import (
    array_sha256,
    date_cluster_bootstrap,
    paired_bootstrap,
    validate_exact_keys,
)
from horse_racing.analysis.confirmed_starter_e6a_v2 import run_e6b_fold
from horse_racing.analysis.confirmed_starter_e6b import (
    METRICS,
    PARTITIONS,
    evaluate_arm,
    pooled_metrics,
)
from horse_racing.analysis.confirmed_starter_e7a import FEATURES

ARMS = ("BASE_136", "SEQUENCE_12_AUDITED")


class E7BContractError(ValueError):
    """The sealed E7-B two-arm comparison must stop."""


def verify_sequence_contract(
    h1: pl.DataFrame, sequence: pl.DataFrame, evidence: pl.DataFrame
) -> None:
    if sequence.columns != ["race_id", "race_entry_id", *FEATURES]:
        raise E7BContractError("twelve feature names/order changed")
    if sequence.height != 15579 or evidence.height != 46737:
        raise E7BContractError("H1 feature/evidence denominator changed")
    validate_exact_keys(h1, sequence, name="E7-B H1-sequence")
    if evidence.select("race_id", "race_entry_id", "slot").n_unique() != evidence.height:
        raise E7BContractError("duplicate sequence evidence slot")
    for slot in (1, 2, 3):
        part = evidence.filter(pl.col("slot") == slot)
        validate_exact_keys(h1, part, name=f"E7-B evidence slot{slot}")
    for name in FEATURES:
        if sequence.schema[name] != pl.Float64:
            raise E7BContractError(f"non-Float64 feature: {name}")
        if not sequence[name].drop_nulls().is_finite().all():
            raise E7BContractError(f"nonfinite feature: {name}")
    for slot in (1, 2, 3):
        absent = evidence.filter((pl.col("slot") == slot) & pl.col("prior_race_entry_id").is_null())
        if absent.height:
            names = [
                f"sequence_start{slot}_{measure}"
                for measure in ("early_rel", "last200_rel", "speed_figure", "days_ago")
            ]
            joined = absent.select("race_id", "race_entry_id").join(
                sequence.select("race_id", "race_entry_id", *names),
                on=["race_id", "race_entry_id"],
                validate="1:1",
            )
            if joined.select(pl.any_horizontal(pl.col(names).is_not_null())).to_series().any():
                raise E7BContractError(f"slot{slot}: null isolation broken")


def verify_shared_base_matrices(
    base: dict[str, np.ndarray], expanded: dict[str, np.ndarray]
) -> dict[str, Any]:
    audit = {}
    for stage in ("fit", "tune", "calibration", "evaluation"):
        matrix = base[stage]
        candidate = expanded[stage]
        if matrix.shape[1] != 136 or candidate.shape != (matrix.shape[0], 148):
            raise E7BContractError(f"{stage}: 136/148 matrix shape changed")
        old_hash = array_sha256(matrix)
        if array_sha256(candidate[:, :136]) != old_hash:
            raise E7BContractError(f"{stage}: existing 136 matrix cells changed")
        audit[stage] = {
            "base_sha256": old_hash,
            "expanded_base_slice_sha256": old_hash,
            "expanded_sha256": array_sha256(candidate),
            "rows": matrix.shape[0],
        }
    return audit


def orchestrate_fold(
    expected: tuple[str, str], order: tuple[str, str], prepare: Any, evaluate: Any
) -> dict[str, Any]:
    if expected != ARMS:
        raise E7BContractError("sealed E7-B arm identities changed")
    result = run_e6b_fold(expected, order, prepare, evaluate)
    if not result.approved:
        raise E7BContractError(result.failure_reason or "common gate rejected fold")
    if result.validation_call_count != 2 or set(result.validation_results) != set(ARMS):
        raise E7BContractError("common gate did not evaluate both arms exactly once")
    return result.validation_results


def paired_comparison(
    results: dict[str, dict[str, Any]], *, expected_races: int
) -> tuple[dict[str, Any], pl.DataFrame]:
    if set(results) != set(ARMS):
        raise E7BContractError("both sealed E7-B arms required")
    base, expanded = (results[name] for name in ARMS)
    base_races = base["per_race"]
    added_races = expanded["per_race"]
    validate_exact_keys(
        base_races.select("race_id").with_columns(pl.lit(0).alias("race_entry_id")),
        added_races.select("race_id").with_columns(pl.lit(0).alias("race_entry_id")),
        name="E7-B paired races",
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
        raise E7BContractError(f"paired race count {paired.height} != {expected_races}")
    metrics = {name: results[name]["metrics"] for name in ARMS}
    return {
        "metrics": metrics,
        "metric_deltas_added_minus_base": {
            key: metrics[ARMS[1]][key] - metrics[ARMS[0]][key] for key in METRICS
        },
        "bootstrap": {
            "paired_race": paired_bootstrap(paired["delta"].to_numpy()),
            "race_date_cluster": date_cluster_bootstrap(paired),
        },
        "paired_rows": paired.height,
        "delta_definition": "SEQUENCE_12_AUDITED - BASE_136",
        "negative_loss_delta_favors_added": True,
    }, paired


__all__ = [
    "ARMS",
    "PARTITIONS",
    "E7BContractError",
    "evaluate_arm",
    "orchestrate_fold",
    "paired_comparison",
    "pooled_metrics",
    "verify_sequence_contract",
    "verify_shared_base_matrices",
]
