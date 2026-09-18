from __future__ import annotations

import json

import numpy as np
import pytest

from horse_racing.analysis.jeju_place_probability import (
    JejuPlaceProbabilityError,
    evaluate_place_race,
    pl_top3_marginals,
)


def test_uniform_three_horse_marginals_sum_to_three() -> None:
    probabilities = pl_top3_marginals([0.0, 0.0, 0.0])
    assert probabilities.shape == (3,)
    assert probabilities.tolist() == pytest.approx([1.0, 1.0, 1.0])
    assert probabilities.sum() == pytest.approx(3.0)


def test_uniform_four_horse_marginals_are_three_quarters() -> None:
    probabilities = pl_top3_marginals([0.0] * 4)
    assert probabilities.tolist() == pytest.approx([0.75] * 4)
    assert probabilities.sum() == pytest.approx(3.0)


def test_extreme_scores_remain_finite_and_each_slot_sums_to_one() -> None:
    probabilities = pl_top3_marginals([1000.0, 1.0, 0.0, -1.0])
    assert np.all(np.isfinite(probabilities))
    assert np.all(probabilities >= 0)
    assert probabilities.sum() == pytest.approx(3.0, abs=1e-12)


def test_common_score_shift_and_source_permutation_preserve_marginals() -> None:
    original = pl_top3_marginals([1.2, -0.5, 3.0, 0.2], beta=1.7)
    shifted = pl_top3_marginals([101.2, 99.5, 103.0, 100.2], beta=1.7)
    permuted = pl_top3_marginals([0.2, 3.0, 1.2, -0.5], beta=1.7)
    assert shifted == pytest.approx(original)
    assert permuted == pytest.approx(original[[3, 2, 0, 1]])


def test_place_evaluation_returns_pick_hit_labels_and_entry_metrics() -> None:
    result = evaluate_place_race(["A", "B", "C", "D"], [4.0, 3.0, 2.0, 1.0], ["A", "B", "C"])
    assert result["pick_horse_id"] == "A"
    assert result["pick_hit"] is True
    assert result["pick_probability"] == pytest.approx(result["pl_marginals"][0])
    assert sum(result["pl_marginals"]) == pytest.approx(3.0)
    assert result["official_labels"] == [1, 1, 1, 0]
    assert result["native_brier"] is None
    assert json.loads(json.dumps(result)) == result


def test_boundary_tie_keeps_four_official_labels_and_expected_pick_hit() -> None:
    result = evaluate_place_race(["A", "B", "C", "D"], [2.0, 2.0, 1.0, 0.0], ["A", "B", "C", "D"])
    assert result["pick_horse_id"] == "A"
    assert result["pick_hit"] is True
    assert result["tie_expected_pick_hit"] == pytest.approx(1.0)
    assert result["official_labels"] == [1, 1, 1, 1]


def test_native_probabilities_produce_optional_metrics() -> None:
    result = evaluate_place_race(
        ["A", "B", "C"],
        [2.0, 1.0, 0.0],
        ["A", "B", "C"],
        native_probabilities={"A": 0.8, "B": 0.7, "C": 0.6},
    )
    assert result["native_pick_probability"] == pytest.approx(0.8)
    assert result["native_brier"] == pytest.approx(np.mean((np.array([0.8, 0.7, 0.6]) - 1) ** 2))
    assert result["native_logloss"] is not None


def test_pick_probability_is_top_three_inclusion_probability() -> None:
    result = evaluate_place_race(
        [str(index) for index in range(10)],
        [0.0] * 10,
        ["0", "1", "2"],
    )
    assert result["pick_probability"] == pytest.approx(0.3)
    assert result["pick_probability"] == pytest.approx(sum(result["pl_marginals"]) / 10)


def test_public_marginals_reject_fewer_than_three_scores() -> None:
    with pytest.raises(JejuPlaceProbabilityError):
        pl_top3_marginals([1.0, 2.0])


@pytest.mark.parametrize(
    "scores,official,native",
    [
        ([1.0, 2.0], ["A", "B", "C"], None),
        ([1.0, 2.0, 3.0], ["A", "A", "B"], None),
        ([1.0, 2.0, 3.0], ["A", "B", "D"], None),
        ([1.0, 2.0, 3.0], ["A", "B", "C"], [0.5, 0.5]),
    ],
)
def test_malformed_place_inputs_are_rejected(scores, official, native) -> None:
    with pytest.raises(JejuPlaceProbabilityError):
        evaluate_place_race(["A", "B", "C"], scores, official, native_probabilities=native)
