from __future__ import annotations

import itertools
import json
import math

import pytest

from horse_racing.analysis.jeju_joint_evaluation import (
    JejuJointEvaluationError,
    evaluate_joint_race,
)


def _all_orders(ids: tuple[str, str, str]) -> list[tuple[str, str, str]]:
    return list(itertools.permutations(ids))


def test_uniform_n4_factorizes_and_marginals_sum_to_three() -> None:
    result = evaluate_joint_race(
        ["A", "B", "C", "D"],
        [0.0] * 4,
        [0.0] * 4,
        [("A", "B", "C")],
        ["A", "B", "C"],
    )

    assert result["set_probability_sum"] == pytest.approx(1.0)
    assert result["order_probability_sum"] == pytest.approx(1.0)
    assert result["probability_sums"]["marginal"] == pytest.approx(3.0)
    assert result["set_nll"] == pytest.approx(math.log(4))
    assert result["order_nll"] == pytest.approx(math.log(24))
    assert result["predicted_set"] == ["A", "B", "C"]
    assert result["predicted_order"] == ["A", "B", "C"]
    assert result["pl_marginals"] == pytest.approx([0.75] * 4)
    assert result["place_probability"] == pytest.approx(0.75)
    assert json.loads(json.dumps(result)) == result


def test_factorized_mass_and_order_scores_are_separate() -> None:
    result = evaluate_joint_race(
        ["A", "B", "C", "D"],
        [4.0, 3.0, 2.0, 1.0],
        [0.0, 1.0, 2.0, 3.0],
        [("A", "B", "C")],
        ["A", "B", "C"],
    )

    assert result["predicted_set"] == ["A", "B", "C"]
    assert result["predicted_order"] == ["C", "B", "A"]
    assert result["order_confidence"] <= result["set_confidence"]
    assert result["set_hit"] is True
    assert result["order_hit"] is False
    assert result["order_given_set"] is False


def test_all_three_horses_have_probability_one() -> None:
    result = evaluate_joint_race(
        ["A", "B", "C"],
        [1000.0, 1.0, -1.0],
        [-1000.0, 0.0, 1000.0],
        _all_orders(("A", "B", "C")),
        ["A", "B", "C"],
    )

    assert result["set_confidence"] == pytest.approx(1.0)
    assert result["set_probability_sum"] == pytest.approx(1.0)
    assert result["order_probability_sum"] == pytest.approx(1.0)
    assert result["pl_marginals"] == pytest.approx([1.0, 1.0, 1.0])
    assert all(math.isfinite(value) for value in result["pl_marginals"])


def test_extreme_scores_remain_finite_and_json_safe() -> None:
    result = evaluate_joint_race(
        ["A", "B", "C", "D"],
        [1000.0, 1.0, 0.0, -1.0],
        [1000.0, 1.0, 0.0, -1.0],
        [("A", "B", "C")],
        ["A", "B", "C"],
        beta_set=3.0,
        beta_order=2.0,
    )

    for key in ("set_nll", "order_nll", "set_confidence", "order_confidence"):
        assert math.isfinite(result[key])
    assert result["set_probability_sum"] == pytest.approx(1.0)
    assert result["order_probability_sum"] == pytest.approx(1.0)
    assert json.loads(json.dumps(result)) == result


def test_ties_use_stable_ids_and_accepted_ties_sum_unique_sets_and_orders() -> None:
    accepted = _all_orders(("A", "B", "C")) + _all_orders(("A", "B", "D"))
    result = evaluate_joint_race(
        ["D", "C", "B", "A"],
        [0.0] * 4,
        [0.0] * 4,
        accepted,
        ["A", "B", "C", "D"],
    )

    assert result["predicted_set"] == ["A", "B", "C"]
    assert result["predicted_order"] == ["A", "B", "C"]
    assert result["set_nll"] == pytest.approx(math.log(2))
    assert result["order_nll"] == pytest.approx(math.log(2))
    assert result["tie_expected_pick_hit"] == pytest.approx(1.0)
    assert result["compatible_max_overlap"] == 3


def test_source_permutation_preserves_id_mapped_predictions_and_marginals() -> None:
    original = evaluate_joint_race(
        ["A", "B", "C", "D"],
        [1.2, -0.1, 0.8, 2.0],
        [2.0, 1.0, -0.5, 0.2],
        [("A", "B", "C")],
        ["A", "B", "C"],
    )
    permuted = evaluate_joint_race(
        ["D", "B", "A", "C"],
        [2.0, -0.1, 1.2, 0.8],
        [0.2, 1.0, 2.0, -0.5],
        [("A", "B", "C")],
        ["A", "B", "C"],
    )

    assert permuted["predicted_set"] == original["predicted_set"]
    assert permuted["predicted_order"] == original["predicted_order"]
    assert permuted["set_nll"] == pytest.approx(original["set_nll"])
    assert permuted["order_nll"] == pytest.approx(original["order_nll"])
    original_marginals = dict(zip(["A", "B", "C", "D"], original["pl_marginals"], strict=True))
    permuted_marginals = dict(zip(["D", "B", "A", "C"], permuted["pl_marginals"], strict=True))
    assert permuted_marginals == pytest.approx(original_marginals)


@pytest.mark.parametrize(
    "horse_ids,inclusion,ordering,accepted,official,beta_set",
    [
        (["A", "A", "C"], [1, 2, 3], [1, 2, 3], [("A", "B", "C")], ["A", "B", "C"], 1),
        (["A", "B", "C"], [1, 2], [1, 2, 3], [("A", "B", "C")], ["A", "B", "C"], 1),
        (["A", "B", "C"], [1, 2, 3], [1, 2, 3], [], ["A", "B", "C"], 1),
        (["A", "B", "C"], [1, 2, 3], [1, 2, 3], [("A", "B", "D")], ["A", "B", "C"], 1),
        (["A", "B", "C"], [1, 2, 3], [1, 2, 3], [("A", "A", "B")], ["A", "B", "C"], 1),
        (["A", "B", "C"], [1, 2, 3], [1, 2, 3], [("A", "B", "C")], ["A", "A", "C"], 1),
        (["A", "B", "C"], [1, 2, 3], [1, 2, 3], [("A", "B", "C")], ["A", "B", "D"], 1),
        (["A", "B", "C"], [1, 2, 3], [1, 2, 3], [("A", "B", "C")], ["A", "B", "C"], 0),
    ],
)
def test_malformed_inputs_are_rejected(
    horse_ids, inclusion, ordering, accepted, official, beta_set
) -> None:
    with pytest.raises(JejuJointEvaluationError):
        evaluate_joint_race(
            horse_ids,
            inclusion,
            ordering,
            accepted,
            official,
            beta_set=beta_set,
        )
