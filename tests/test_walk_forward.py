from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from horse_racing.analysis.walk_forward import (
    fold_bounds,
    render_walk_forward_report,
    run_lightgbm_walk_forward,
)


def _synthetic_frame() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = date(2025, 9, 1)
    race_id = 0
    entry_id = 0
    for day_index in range(36):
        race_date = start + timedelta(days=day_index * 7)
        for repeat in range(2):
            race_id += 1
            winner = (day_index + repeat) % 6
            scores = [6 - abs(horse - winner) for horse in range(6)]
            order = sorted(range(6), key=lambda horse: scores[horse], reverse=True)
            for horse in range(6):
                entry_id += 1
                rank = order.index(horse) + 1
                rows.append(
                    {
                        "race_id": race_id,
                        "race_entry_id": entry_id,
                        "horse_number": horse + 1,
                        "race_date_local": race_date.isoformat(),
                        "score": float(scores[horse]),
                        "meet": "서울" if repeat == 0 else "부산",
                        "win": int(rank == 1),
                        "top2": int(rank <= 2),
                        "top3": int(rank <= 3),
                    }
                )
    return pl.DataFrame(rows)


def test_fold_bounds_are_chronological() -> None:
    bounds = fold_bounds(2025)
    assert bounds["train"][1] == "2024-12-31"
    assert bounds["valid"] == ("2025-01-01", "2025-12-31")
    assert bounds["test"][0] == "2026-01-01"


def test_walk_forward_trains_on_prior_dates_and_reports() -> None:
    result = run_lightgbm_walk_forward(
        _synthetic_frame(),
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic",
        as_of_policy="start_minus_30m",
        years=[2026],
        seed=9,
        calibration="raw",
        hyperparameters={
            "n_estimators": 40,
            "learning_rate": 0.1,
            "num_leaves": 7,
            "min_child_samples": 5,
            "n_jobs": 1,
        },
    )

    assert [fold.year for fold in result.folds] == [2026]
    assert result.folds[0].train_end == "2025-12-31"
    assert result.aggregate_metrics["auc"] > 0.8
    assert result.predictions["fold_year"].unique().to_list() == [2026]
    report = render_walk_forward_report(
        result,
        dataset_version="synthetic",
        as_of_policy="start_minus_30m",
        profile="test",
        seed=9,
    )
    assert "2026" in report
    assert "전체 fold 결합" in report


def test_ranking_walk_forward_runs() -> None:
    from horse_racing.analysis.walk_forward import run_ranking_walk_forward

    result = run_ranking_walk_forward(
        _synthetic_frame(),
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic",
        as_of_policy="start_minus_30m",
        years=[2026],
        seed=3,
        calibration_objective="full_top3",
        hyperparameters={
            "n_estimators": 40,
            "learning_rate": 0.1,
            "num_leaves": 7,
            "min_child_samples": 5,
            "n_jobs": 1,
        },
    )
    assert result.aggregate_metrics["auc"] > 0.8
    assert "rank_score" in result.predictions.columns
    assert set(result.aggregate_target_metrics) == {"win", "top2", "top3"}
    assert "prob_top3" in result.predictions.columns


def test_top5_ranking_walk_forward_reports_rank_distribution() -> None:
    from horse_racing.analysis.walk_forward import run_ranking_walk_forward

    frame = _synthetic_frame().with_columns(
        pl.col("score")
        .rank("ordinal", descending=True)
        .over("race_id")
        .cast(pl.Int64)
        .alias("finish_position")
    )
    result = run_ranking_walk_forward(
        frame,
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic_top5",
        as_of_policy="start_minus_30m",
        years=[2026],
        seed=5,
        calibration_objective="full_top5",
        relevance_depth=5,
        hyperparameters={
            "n_estimators": 40,
            "learning_rate": 0.1,
            "num_leaves": 7,
            "min_child_samples": 5,
            "n_jobs": 1,
        },
    )
    assert set(result.aggregate_target_metrics) == {
        "win",
        "top2",
        "top3",
        "top4",
        "top5",
    }
    assert set(result.aggregate_rank_metrics) == {
        "topk_rps",
        "actual_rank_bucket_nll",
    }
    assert "prob_rank5" in result.predictions.columns
    assert "prob_top5" in result.predictions.columns
