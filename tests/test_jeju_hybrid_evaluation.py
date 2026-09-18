import numpy as np
import pytest

from horse_racing.analysis.jeju_hybrid_evaluation import (
    accepted_layout,
    conditional_calibration_loss,
    evaluate_hybrid_race,
)
from horse_racing.analysis.jeju_place_probability import evaluate_place_race
from horse_racing.analysis.jeju_top3_evaluation import evaluate_race


@pytest.mark.parametrize("n", [3, 4, 10])
def test_preserves_ranker_sets_and_inclusion_changes_only_order(n):
    ids = [str(i) for i in range(n)]
    a = np.linspace(-2, 2, n)
    b = -a
    truth = [tuple(ids[-3:])]
    base = evaluate_race(ids, a, truth, beta=0.8)
    place = evaluate_place_race(ids, a, ids[-3:], beta=0.8)
    result = evaluate_hybrid_race(ids, a, b, truth, ids[-3:], beta_set=0.8, beta_order=1.2)
    assert result["predicted_set"] == base["predicted_set"]
    assert result["set_nll"] == pytest.approx(base["set_nll"], abs=1e-12)
    assert result["pick_horse_id"] == place["pick_horse_id"]
    np.testing.assert_allclose(result["pl_marginals"], place["pl_marginals"], atol=1e-12)
    assert result["predicted_order"] == ids[-3:]
    assert result["order_probability_sum"] == pytest.approx(1, abs=1e-12)
    assert result["set_probability_sum"] == pytest.approx(1, abs=1e-12)


def test_ties_and_calibration_match_full_evaluator():
    ids = ["d", "b", "a", "c"]
    a = np.array([0.2, -0.1, 0, 0.4])
    b = np.array([0.1, 0.3, -0.2, 0.5])
    truth = [("a", "b", "c"), ("a", "b", "d")]
    result = evaluate_hybrid_race(ids, a, b, truth, ids, beta_set=0.7, beta_order=1.3)
    layout = accepted_layout(ids, a, b, truth, 0.7)
    assert conditional_calibration_loss(np.log(1.3), [layout]) == pytest.approx(
        result["order_nll"], abs=1e-12
    )
    uniform = evaluate_hybrid_race(ids, np.zeros(4), np.zeros(4), truth, ids)
    assert uniform["pick_horse_id"] == "a"
    assert uniform["predicted_set"] == ["a", "b", "c"]
    assert uniform["set_nll"] == pytest.approx(np.log(2))
    assert uniform["order_nll"] == pytest.approx(np.log(12))
