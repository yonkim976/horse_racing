"""평가 지표(metrics.py) 테스트."""

from __future__ import annotations

import math

import polars as pl
import pytest

from horse_racing.analysis.metrics import (
    brier_score,
    calibration_table,
    evaluate_probabilities,
    expected_calibration_error,
    log_loss,
    race_level_metrics,
)


def test_log_loss_known_value() -> None:
    # -mean(log(0.8), log(1-0.2)) = -log(0.8)
    result = log_loss([0.8, 0.2], [1, 0])
    assert result == pytest.approx(-math.log(0.8))


def test_log_loss_clips_extreme_probabilities() -> None:
    result = log_loss([0.0, 1.0], [1, 0])
    assert math.isfinite(result)
    assert result > 30  # -log(1e-15) ≈ 34.5


def test_brier_known_value() -> None:
    # ((0.7-1)^2 + (0.3-0)^2) / 2 = 0.09
    assert brier_score([0.7, 0.3], [1, 0]) == pytest.approx(0.09)


def test_ece_perfectly_calibrated_bins() -> None:
    # 0.25 구간에 4개 중 1개 양성 → |0.25 - 0.25| = 0
    probs = [0.25, 0.25, 0.25, 0.25]
    labels = [1, 0, 0, 0]
    assert expected_calibration_error(probs, labels) == pytest.approx(0.0)


def test_ece_detects_overconfidence() -> None:
    # 0.95 확률인데 실제 0% → ECE ≈ 0.95
    probs = [0.95] * 10
    labels = [0] * 10
    assert expected_calibration_error(probs, labels) == pytest.approx(0.95)


def test_calibration_table_counts() -> None:
    rows = calibration_table([0.05, 0.15, 0.95], [0, 0, 1])
    assert sum(row["count"] for row in rows) == 3
    assert rows[-1]["observed_rate"] == 1.0


def _race_frame(probs: list[float], wins: list[int], race_ids: list[int]) -> pl.DataFrame:
    return pl.DataFrame({"race_id": race_ids, "probability": probs, "win": wins})


def test_top1_hit_when_winner_has_max_probability() -> None:
    frame = _race_frame([0.6, 0.3, 0.1], [1, 0, 0], [1, 1, 1])
    result = race_level_metrics(frame, "probability")
    assert result["top1_hit_rate"] == pytest.approx(1.0)
    assert result["top3_inclusion_rate"] == pytest.approx(1.0)


def test_top1_miss_when_winner_not_max() -> None:
    frame = _race_frame([0.6, 0.3, 0.1], [0, 0, 1], [1, 1, 1])
    result = race_level_metrics(frame, "probability")
    assert result["top1_hit_rate"] == pytest.approx(0.0)
    # 3두 경주라 top3 포함은 항상 1
    assert result["top3_inclusion_rate"] == pytest.approx(1.0)


def test_uniform_ties_get_expected_value_not_free_hit() -> None:
    # 5두 균등확률: top1 기대값 1/5, top3 기대값 3/5
    frame = _race_frame([0.2] * 5, [1, 0, 0, 0, 0], [1] * 5)
    result = race_level_metrics(frame, "probability")
    assert result["top1_hit_rate"] == pytest.approx(0.2)
    assert result["top3_inclusion_rate"] == pytest.approx(0.6)


def test_top3_excludes_winner_ranked_fourth() -> None:
    frame = _race_frame([0.4, 0.3, 0.2, 0.08, 0.02], [0, 0, 0, 1, 0], [1] * 5)
    result = race_level_metrics(frame, "probability")
    assert result["top3_inclusion_rate"] == pytest.approx(0.0)


def test_evaluate_probabilities_reports_coverage_for_nulls() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1, 1, 2, 2, 2],
            "probability": [0.5, 0.3, 0.2, None, None, None],
            "win": [1, 0, 0, 1, 0, 0],
        }
    )
    result = evaluate_probabilities(frame, "probability")
    assert result["coverage"] == pytest.approx(0.5)
    assert result["n_races"] == pytest.approx(1.0)


def test_evaluate_probabilities_all_null_raises() -> None:
    frame = pl.DataFrame(
        {"race_id": [1, 1], "probability": [None, None], "win": [1, 0]},
        schema_overrides={"probability": pl.Float64},
    )
    with pytest.raises(ValueError):
        evaluate_probabilities(frame, "probability")
