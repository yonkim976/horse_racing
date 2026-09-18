from __future__ import annotations

import json
import math

import pytest

from horse_racing.analysis.jeju_top3_evaluation import (
    JejuTop3EvaluationError,
    aggregate_race_metrics,
    evaluate_race,
    paired_day_cluster_bootstrap,
    paired_race_bootstrap,
)


def test_uniform_pl_probabilities_cover_every_order_and_set() -> None:
    result = evaluate_race(["A", "B", "C", "D"], [0.0] * 4, [("A", "B", "C")])

    assert result["n_horses"] * (result["n_horses"] - 1) * (result["n_horses"] - 2) == 4 * 3 * 2
    assert result["order_probability_sum"] == pytest.approx(1.0)
    assert result["set_probability_sum"] == pytest.approx(1.0)
    assert result["set_nll"] == pytest.approx(math.log(4))
    assert result["order_nll"] == pytest.approx(math.log(24))
    assert json.loads(json.dumps(result)) == result


def test_set_first_prediction_and_global_order_are_deterministic() -> None:
    result = evaluate_race(["A", "B", "C", "D"], [4.0, 3.0, 2.0, 1.0], [("A", "B", "C")])

    assert result["predicted_set"] == ["A", "B", "C"]
    assert result["predicted_order"] == ["A", "B", "C"]
    assert result["global_predicted_order"] == ["A", "B", "C"]
    assert result["set_hit"] is True
    assert result["order_hit"] is True
    assert result["global_order_hit"] is True


def test_score_and_source_row_permutation_do_not_change_the_result() -> None:
    original = evaluate_race(["A", "B", "C", "D"], [1.2, -0.1, 0.8, 2.0], [("A", "B", "C")])
    permuted = evaluate_race(["D", "B", "A", "C"], [2.0, -0.1, 1.2, 0.8], [("A", "B", "C")])

    assert permuted == original


def test_dead_heat_orders_and_boundary_sets_are_scored_as_compatible() -> None:
    result = evaluate_race(
        ["A", "B", "C", "D"],
        [0.0] * 4,
        [("A", "B", "C"), ("A", "B", "D")],
    )

    assert result["set_hit"] is True
    assert result["order_hit"] is True
    assert result["order_given_set"] is True
    assert result["set_nll"] == pytest.approx(math.log(2))
    assert result["order_nll"] == pytest.approx(math.log(12))
    assert result["compatible_max_overlap"] == 3
    assert result["max_tie_expected_set_hit"] == pytest.approx(2 / 4)
    assert result["max_tie_expected_order_hit"] == pytest.approx(2 / 24)


def test_uniform_max_tie_expected_hits_match_the_number_of_compatible_answers() -> None:
    result = evaluate_race(
        ["A", "B", "C", "D", "E"],
        [0.0] * 5,
        [("A", "B", "C"), ("A", "C", "B")],
    )

    assert result["max_tie_expected_set_hit"] == pytest.approx(1 / 10)
    assert result["max_tie_expected_order_hit"] == pytest.approx(2 / 60)
    assert result["top1_hit"] is True
    assert result["winner_in3"] is True


@pytest.mark.parametrize(
    "horse_ids,scores,accepted,beta",
    [
        (["A", "A", "C"], [1, 2, 3], [("A", "B", "C")], 1),
        (["A", "B"], [1, 2], [("A", "B", "C")], 1),
        (["A", "B", "C"], [1, 2], [("A", "B", "C")], 1),
        (["A", "B", "C"], [1, float("nan"), 3], [("A", "B", "C")], 1),
        (["A", "B", "C"], [1, 2, 3], [], 1),
        (["A", "B", "C"], [1, 2, 3], [("A", "B", "D")], 1),
        (["A", "B", "C"], [1, 2, 3], [("A", "A", "B")], 1),
        (["A", "B", "C"], [1, 2, 3], [("A", "B", "C")], 0),
    ],
)
def test_malformed_inputs_are_rejected(horse_ids, scores, accepted, beta) -> None:
    with pytest.raises(JejuTop3EvaluationError):
        evaluate_race(horse_ids, scores, accepted, beta=beta)


def test_paired_race_and_day_bootstraps_are_reproducible() -> None:
    rows = [
        {
            "race_id": 1,
            "race_date": "2026-01-01",
            "candidate": {"set_nll": 1.0},
            "reference": {"set_nll": 1.2},
        },
        {
            "race_id": 2,
            "race_date": "2026-01-01",
            "candidate": {"set_nll": 2.0},
            "reference": {"set_nll": 1.5},
        },
        {
            "race_id": 3,
            "race_date": "2026-01-02",
            "candidate": {"set_nll": 0.5},
            "reference": {"set_nll": 0.6},
        },
    ]
    race = paired_race_bootstrap(rows, metric="set_nll")
    cluster = paired_day_cluster_bootstrap(rows, metric="set_nll")

    assert race == paired_race_bootstrap(rows, metric="set_nll")
    assert cluster == paired_day_cluster_bootstrap(rows, metric="set_nll")
    assert race["iterations"] == 5000
    assert race["seed"] == 17
    assert cluster["blocks"] == 2
    assert cluster["unit"] == "race_date_cluster"


def test_aggregate_reports_conditional_order_accuracy() -> None:
    rows = [
        {
            "set_hit": True,
            "order_hit": True,
            "global_order_hit": True,
            "top1_hit": True,
            "winner_in3": True,
            "set_nll": 1.0,
            "order_nll": 2.0,
            "compatible_max_overlap": 3,
            "max_tie_expected_set_hit": 1.0,
            "max_tie_expected_order_hit": 1.0,
        },
        {
            "set_hit": False,
            "order_hit": False,
            "global_order_hit": False,
            "top1_hit": False,
            "winner_in3": True,
            "set_nll": 2.0,
            "order_nll": 3.0,
            "compatible_max_overlap": 2,
            "max_tie_expected_set_hit": 0.5,
            "max_tie_expected_order_hit": 0.25,
        },
    ]
    result = aggregate_race_metrics(rows)

    assert result["set_hit_rate"] == pytest.approx(0.5)
    assert result["order_hit_rate"] == pytest.approx(0.5)
    assert result["order_accuracy_given_set"] == pytest.approx(1.0)
    assert result["set_nll"] == pytest.approx(1.5)
