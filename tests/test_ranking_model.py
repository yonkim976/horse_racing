from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from test_lightgbm_model import _synthetic_frame

from horse_racing.analysis.plackett_luce import (
    ordered_top3_probabilities,
    plackett_luce_marginals,
    plackett_luce_rank_marginals,
    plackett_luce_top3_nll,
    plackett_luce_topk_nll,
    valid_ordered_top3_indices,
    valid_ordered_topk_indices,
)
from horse_racing.analysis.ranking_model import (
    PERFORMANCE_WEIGHT_GRID,
    margin_aware_relevance,
    race_softmax,
    rank_comparison_frame,
    ranking_relevance,
    train_ranking_model,
)
from horse_racing.analysis.walk_forward import fold_bounds


def test_ranking_relevance_ignores_detailed_unplaced_order() -> None:
    frame = _synthetic_frame().head(6)
    relevance = ranking_relevance(frame)
    assert sorted(relevance.tolist()) == [0, 0, 0, 1, 2, 3]


def test_margin_relevance_softens_close_finish_and_penalizes_large_gap() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1, 1, 1],
            "finish_position": [1, 2, 3, 4, 5, 6],
            "finish_time_ms": [70_000, 70_020, 70_500, 71_000, 72_000, 70_030],
            "distance_m": [1_200] * 6,
        }
    )
    relevance = margin_aware_relevance(frame)

    assert relevance[0] == relevance[1] == 10
    assert relevance[1] > relevance[2] > relevance[3] > relevance[4]
    assert relevance[5] == 0


def test_margin_performance_auxiliary_is_fitted_for_top5() -> None:
    frame = _synthetic_frame().with_columns(
        pl.col("score")
        .rank("ordinal", descending=True)
        .over("race_id")
        .cast(pl.Int64)
        .alias("finish_position"),
        (70_000 - pl.col("score") * 100 + pl.col("race_id").mod(3).cast(pl.Float64)).alias(
            "finish_time_ms"
        ),
        pl.lit(1_200).alias("distance_m"),
    )
    result = train_ranking_model(
        frame,
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic_margin_performance",
        as_of_policy="start_minus_30m",
        seed=9,
        split_bounds=fold_bounds(2026),
        calibration_objective="full_top5",
        relevance_depth=5,
        margin_performance=True,
        hyperparameters={
            "n_estimators": 30,
            "learning_rate": 0.1,
            "num_leaves": 7,
            "min_child_samples": 5,
            "n_jobs": 1,
        },
    )

    assert result.bundle.performance_estimator is not None
    assert result.bundle.performance_best_iteration > 0
    assert result.bundle.performance_weight in PERFORMANCE_WEIGHT_GRID
    assert "prob_rank5" in result.valid_predictions.columns
    assert "rank_score_base" in result.valid_predictions.columns
    assert "margin_performance_score" in result.valid_predictions.columns


def test_race_softmax_sums_to_one() -> None:
    probabilities = race_softmax(
        np.array([1.0, 0.0, -1.0, 2.0, 1.0]),
        np.array([1, 1, 1, 2, 2]),
        beta=1.5,
    )
    assert probabilities[:3].sum() == pytest.approx(1.0)
    assert probabilities[3:].sum() == pytest.approx(1.0)
    assert probabilities[0] > probabilities[1] > probabilities[2]


def test_full_plackett_luce_probabilities_are_coherent() -> None:
    marginals = plackett_luce_marginals(
        np.array([2.0, 1.0, 0.0, -1.0, 0.5, -0.5]),
        np.array([1, 1, 1, 1, 2, 2]),
        beta=1.2,
    )
    assert marginals["prob_win"][:4].sum() == pytest.approx(1.0)
    assert marginals["prob_top2"][:4].sum() == pytest.approx(2.0)
    assert marginals["prob_top3"][:4].sum() == pytest.approx(3.0)
    assert marginals["prob_win"][4:].sum() == pytest.approx(1.0)
    assert marginals["prob_top2"][4:].sum() == pytest.approx(2.0)
    assert marginals["prob_top3"][4:].sum() == pytest.approx(2.0)
    assert np.all(marginals["prob_win"] <= marginals["prob_top2"])
    assert np.all(marginals["prob_top2"] <= marginals["prob_top3"])


def test_equal_scores_give_uniform_position_marginals() -> None:
    marginals = plackett_luce_marginals(
        np.zeros(4),
        np.ones(4),
        beta=3.0,
    )
    assert marginals["prob_win"].tolist() == pytest.approx([0.25] * 4)
    assert marginals["prob_top2"].tolist() == pytest.approx([0.5] * 4)
    assert marginals["prob_top3"].tolist() == pytest.approx([0.75] * 4)
    assert sum(ordered_top3_probabilities(np.zeros(4), beta=3.0).values()) == pytest.approx(1.0)


def test_top5_rank_marginals_are_exact_and_coherent() -> None:
    marginals = plackett_luce_rank_marginals(
        np.zeros(6),
        np.ones(6),
        beta=2.0,
        max_rank=5,
    )
    for rank in range(1, 6):
        assert marginals[f"prob_rank{rank}"].tolist() == pytest.approx([1 / 6] * 6)
        cumulative = marginals["prob_win"] if rank == 1 else marginals[f"prob_top{rank}"]
        assert cumulative.tolist() == pytest.approx([rank / 6] * 6)
        assert cumulative.sum() == pytest.approx(float(rank))
    assert np.all(marginals["prob_top4"] <= marginals["prob_top5"])


def test_dead_heat_likelihood_marginalizes_valid_orders() -> None:
    valid_orders = valid_ordered_top3_indices(np.array([1, 2, 2, 4]))
    assert valid_orders == {(0, 1, 2), (0, 2, 1)}
    probabilities = ordered_top3_probabilities(np.array([3.0, 2.0, 1.0, 0.0]), beta=1.0)
    expected = -np.log(sum(probabilities[order] for order in valid_orders))
    actual = plackett_luce_top3_nll(
        np.array([3.0, 2.0, 1.0, 0.0]),
        np.ones(4),
        np.array([1, 2, 2, 4]),
        beta=1.0,
    )
    assert actual == pytest.approx(expected)


def test_top5_dead_heat_orders_and_likelihood() -> None:
    positions = np.array([1, 2, 3, 4, 4, 6])
    orders = valid_ordered_topk_indices(positions, max_rank=5)
    assert orders == {(0, 1, 2, 3, 4), (0, 1, 2, 4, 3)}
    nll = plackett_luce_topk_nll(
        np.array([5.0, 4.0, 3.0, 2.0, 1.0, 0.0]),
        np.ones(6),
        positions,
        beta=1.0,
        max_rank=5,
    )
    assert np.isfinite(nll)


def test_top5_likelihood_is_stable_for_five_runners_and_extreme_scores() -> None:
    nll = plackett_luce_topk_nll(
        np.array([100.0, 50.0, 0.0, -50.0, -100.0]),
        np.ones(5),
        np.array([1, 2, 3, 4, 5]),
        beta=30.0,
        max_rank=5,
    )
    assert np.isfinite(nll)


def test_ranking_model_produces_valid_race_probabilities() -> None:
    frame = _synthetic_frame()
    result = train_ranking_model(
        frame,
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic",
        as_of_policy="start_minus_30m",
        seed=4,
        split_bounds=fold_bounds(2026),
        calibration_objective="full_top3",
        hyperparameters={
            "n_estimators": 50,
            "learning_rate": 0.1,
            "num_leaves": 7,
            "min_child_samples": 5,
            "n_jobs": 1,
        },
    )
    sums = result.valid_predictions.group_by("race_id").agg(
        pl.col("prob_win").sum(),
        pl.col("prob_top2").sum(),
        pl.col("prob_top3").sum(),
    )
    assert sums["prob_win"].to_list() == pytest.approx([1.0] * sums.height)
    assert sums["prob_top2"].to_list() == pytest.approx([2.0] * sums.height)
    assert sums["prob_top3"].to_list() == pytest.approx([3.0] * sums.height)
    assert result.valid_metrics["auc"] > 0.8
    assert set(result.valid_target_metrics) == {"win", "top2", "top3"}
    assert result.ordered_top3_nll is not None
    assert result.bundle.softmax_beta > 0


def test_top5_ranking_model_outputs_actual_comparison() -> None:
    frame = _synthetic_frame().with_columns(
        pl.col("score")
        .rank("ordinal", descending=True)
        .over("race_id")
        .cast(pl.Int64)
        .alias("finish_position")
    )
    result = train_ranking_model(
        frame,
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic_top5",
        as_of_policy="start_minus_30m",
        seed=8,
        split_bounds=fold_bounds(2026),
        calibration_objective="full_top5",
        relevance_depth=5,
        hyperparameters={
            "n_estimators": 50,
            "learning_rate": 0.1,
            "num_leaves": 7,
            "min_child_samples": 5,
            "n_jobs": 1,
        },
    )
    sums = result.valid_predictions.group_by("race_id").agg(
        *[pl.col(f"prob_rank{rank}").sum() for rank in range(1, 6)],
        *[pl.col(f"prob_top{rank}").sum() for rank in range(2, 6)],
    )
    for rank in range(1, 6):
        assert sums[f"prob_rank{rank}"].to_list() == pytest.approx([1.0] * sums.height)
        if rank >= 2:
            assert sums[f"prob_top{rank}"].to_list() == pytest.approx([float(rank)] * sums.height)
    assert set(result.valid_target_metrics) == {"win", "top2", "top3", "top4", "top5"}
    assert result.ordered_topk_nll is not None
    assert result.topk_rps is not None
    assert result.actual_rank_nll is not None

    valid = frame.filter(
        pl.col("race_date_local").is_between(pl.lit("2026-01-01"), pl.lit("2026-12-31"))
    )
    comparison = rank_comparison_frame(valid, result.valid_predictions, max_rank=5)
    assert comparison.height == result.valid_predictions.height
    assert comparison["prob_actual_rank_bucket"].is_between(0.0, 1.0).all()
    assert comparison["expected_rank_bucket"].is_between(1.0, 6.0).all()
