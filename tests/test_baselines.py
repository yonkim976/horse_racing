"""M3 기준 모델(baselines.py) 테스트."""

from __future__ import annotations

import polars as pl
import pytest

from horse_racing.analysis.baselines import (
    PROBABILITY_COLUMN,
    BaselineInputError,
    assign_split,
    fit_softmax_beta,
    market_probabilities,
    render_baseline_report,
    run_baselines,
    score_softmax_probabilities,
    uniform_probabilities,
)


def test_assign_split_boundaries() -> None:
    frame = pl.DataFrame(
        {
            "race_date_local": [
                "2025-01-03", "2026-02-28", "2026-03-01",
                "2026-05-31", "2026-06-01", "2026-08-23",
            ]
        }
    )
    splits = assign_split(frame)["split"].to_list()
    assert splits == ["train", "train", "valid", "valid", "test", "test"]


def test_uniform_probabilities_sum_to_one() -> None:
    frame = pl.DataFrame({"race_id": [1, 1, 1, 2, 2]})
    result = uniform_probabilities(frame)
    assert result[PROBABILITY_COLUMN].to_list() == pytest.approx([1 / 3] * 3 + [0.5] * 2)


def test_softmax_beta_zero_is_uniform() -> None:
    frame = pl.DataFrame({"race_id": [1] * 4, "rating": [80.0, 60.0, 40.0, 20.0]})
    result = score_softmax_probabilities(frame, "rating", beta=0.0)
    assert result[PROBABILITY_COLUMN].to_list() == pytest.approx([0.25] * 4)


def test_softmax_orders_by_score() -> None:
    frame = pl.DataFrame({"race_id": [1] * 3, "rating": [80.0, 60.0, 40.0]})
    probs = score_softmax_probabilities(frame, "rating", beta=1.0)[PROBABILITY_COLUMN].to_list()
    assert probs[0] > probs[1] > probs[2]
    assert sum(probs) == pytest.approx(1.0)


def test_softmax_lower_is_better_flips_order() -> None:
    frame = pl.DataFrame({"race_id": [1] * 3, "form": [0.1, 0.5, 0.9]})
    probs = score_softmax_probabilities(
        frame, "form", beta=1.0, higher_is_better=False
    )[PROBABILITY_COLUMN].to_list()
    assert probs[0] > probs[1] > probs[2]


def test_softmax_null_scores_get_race_mean() -> None:
    frame = pl.DataFrame({"race_id": [1] * 3, "rating": [80.0, None, 40.0]})
    probs = score_softmax_probabilities(frame, "rating", beta=1.0)[PROBABILITY_COLUMN].to_list()
    # null은 z=0(경주 평균) → 중간 확률
    assert probs[0] > probs[1] > probs[2]


def test_softmax_all_null_race_is_uniform() -> None:
    frame = pl.DataFrame(
        {"race_id": [1] * 3, "rating": [None, None, None]},
        schema_overrides={"rating": pl.Float64},
    )
    probs = score_softmax_probabilities(frame, "rating", beta=2.0)[PROBABILITY_COLUMN].to_list()
    assert probs == pytest.approx([1 / 3] * 3)


def test_softmax_missing_column_raises() -> None:
    frame = pl.DataFrame({"race_id": [1]})
    with pytest.raises(BaselineInputError):
        score_softmax_probabilities(frame, "rating", beta=1.0)


def _informative_frame(n_races: int = 40, seed: int = 7) -> pl.DataFrame:
    """레이팅이 높을수록 이길 확률이 높은 합성 데이터."""
    import random

    rng = random.Random(seed)
    rows = []
    for race_id in range(n_races):
        ratings = sorted((rng.uniform(20, 90) for _ in range(6)), reverse=True)
        # 최고 레이팅 말이 60% 확률로 승리
        winner_index = 0 if rng.random() < 0.6 else rng.randrange(1, 6)
        for horse_index, rating in enumerate(ratings):
            rows.append(
                {
                    "race_id": race_id,
                    "race_date_local": "2026-01-10",
                    "rating": rating,
                    "form_recent5_pct": 1 - rating / 100 + rng.uniform(-0.05, 0.05),
                    "horse_number": horse_index + 1,
                    "win": 1 if horse_index == winner_index else 0,
                }
            )
    return pl.DataFrame(rows)


def test_fit_softmax_beta_positive_on_informative_score() -> None:
    frame = _informative_frame()
    beta = fit_softmax_beta(frame, "rating", higher_is_better=True)
    assert beta > 0.1


def test_fit_softmax_beta_near_zero_on_random_score() -> None:
    import random

    rng = random.Random(3)
    frame = _informative_frame().with_columns(
        pl.Series("rating", [rng.uniform(0, 100) for _ in range(240)])
    )
    beta = fit_softmax_beta(frame, "rating", higher_is_better=True)
    informative_beta = fit_softmax_beta(_informative_frame(), "rating", higher_is_better=True)
    assert beta < informative_beta


def test_market_probabilities_normalizes_overround() -> None:
    frame = pl.DataFrame(
        {"race_id": [1, 1, 1], "horse_number": [1, 2, 3], "win": [1, 0, 0]}
    )
    odds = pl.DataFrame(
        {"race_id": [1, 1, 1], "horse_number": [1, 2, 3], "odds": [2.0, 4.0, 4.0]}
    )
    result = market_probabilities(frame, odds)
    probs = result[PROBABILITY_COLUMN].to_list()
    assert sum(probs) == pytest.approx(1.0)
    assert probs[0] == pytest.approx(0.5)
    assert result["market_overround"][0] == pytest.approx(1.0)


def test_market_probabilities_nulls_incomplete_race() -> None:
    frame = pl.DataFrame(
        {"race_id": [1, 1, 2, 2], "horse_number": [1, 2, 1, 2], "win": [1, 0, 1, 0]}
    )
    odds = pl.DataFrame(
        {"race_id": [1, 1, 2], "horse_number": [1, 2, 1], "odds": [2.0, 2.0, 3.0]}
    )
    result = market_probabilities(frame, odds)
    race1 = result.filter(pl.col("race_id") == 1)[PROBABILITY_COLUMN].to_list()
    race2 = result.filter(pl.col("race_id") == 2)[PROBABILITY_COLUMN].to_list()
    assert race1 == pytest.approx([0.5, 0.5])
    assert race2 == [None, None]


def _multi_split_frame() -> pl.DataFrame:
    train = _informative_frame(n_races=30, seed=1)
    valid = _informative_frame(n_races=10, seed=2).with_columns(
        pl.lit("2026-04-01").alias("race_date_local"),
        (pl.col("race_id") + 1000).alias("race_id"),
    )
    return pl.concat([train, valid])


def test_run_baselines_returns_b0_b1_b2_without_odds() -> None:
    results = run_baselines(_multi_split_frame(), odds=None)
    ids = [result.baseline_id for result in results]
    assert ids == ["B0", "B1", "B2"]
    for result in results:
        assert "train" in result.metrics
        assert "valid" in result.metrics
        assert "test" not in result.metrics


def test_run_baselines_b1_beats_b0_on_informative_data() -> None:
    results = {r.baseline_id: r for r in run_baselines(_multi_split_frame(), odds=None)}
    assert (
        results["B1"].metrics["valid"]["log_loss"]
        < results["B0"].metrics["valid"]["log_loss"]
    )


def test_run_baselines_includes_market_when_odds_given() -> None:
    frame = _multi_split_frame()
    # 완벽하지 않지만 정보성 있는 배당: 레이팅 역수 기반
    odds = frame.select(
        "race_id",
        "horse_number",
        (100.0 / pl.col("rating")).alias("odds"),
    )
    results = {r.baseline_id: r for r in run_baselines(frame, odds=odds)}
    assert "B3" in results
    assert results["B3"].metrics["valid"]["coverage"] == pytest.approx(1.0)


def test_run_baselines_empty_train_raises() -> None:
    frame = _informative_frame().with_columns(pl.lit("2026-04-01").alias("race_date_local"))
    with pytest.raises(BaselineInputError):
        run_baselines(frame, odds=None)


def test_render_report_contains_all_baselines() -> None:
    results = run_baselines(_multi_split_frame(), odds=None)
    report = render_baseline_report(
        results,
        dataset_version="v_test",
        as_of_policy="start_minus_30m",
        evaluate_splits=("train", "valid"),
    )
    for baseline_id in ("B0", "B1", "B2"):
        assert baseline_id in report
    assert "## train" in report
    assert "## valid" in report
