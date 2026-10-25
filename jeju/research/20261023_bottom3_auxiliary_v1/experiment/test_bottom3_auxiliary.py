"""Synthetic-only contract tests for bottom3_auxiliary.py."""
from __future__ import annotations

import importlib.util
import itertools
import math
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("bottom3_auxiliary.py")
SPEC = importlib.util.spec_from_file_location("bottom3_auxiliary_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Bottom3SyntheticContractTests(unittest.TestCase):
    def test_exact_subset_distribution_and_marginal_sum(self) -> None:
        utilities = np.asarray([0.7, -0.4, 0.1, 0.8, -0.2])
        subsets, probabilities, marginal = MODULE.bottom3_subset_distribution(utilities, 1.3)
        logits = np.asarray([sum(utilities[list(s)]) / 1.3 for s in itertools.combinations(range(5), 3)])
        independent = np.exp(logits - np.max(logits))
        independent /= independent.sum()
        self.assertEqual(len(subsets), math.comb(5, 3))
        np.testing.assert_allclose(probabilities, independent, rtol=0.0, atol=1e-15)
        self.assertAlmostEqual(float(probabilities.sum()), 1.0, places=14)
        self.assertAlmostEqual(float(marginal.sum()), 3.0, places=13)
        self.assertTrue(np.all((marginal >= 0.0) & (marginal <= 1.0)))

    def test_uniform_and_three_runner_degenerate_support(self) -> None:
        _, p6, m6 = MODULE.bottom3_subset_distribution(np.zeros(6), 2.0)
        np.testing.assert_allclose(p6, np.full(20, 0.05), rtol=0.0, atol=1e-15)
        np.testing.assert_allclose(m6, np.full(6, 0.5), rtol=0.0, atol=1e-14)
        subsets, p3, m3 = MODULE.bottom3_subset_distribution([0.3, 0.2, 0.1], 0.35)
        self.assertEqual(subsets, [(0, 1, 2)])
        np.testing.assert_array_equal(p3, [1.0])
        np.testing.assert_array_equal(m3, [1.0, 1.0, 1.0])

    def test_exact_bottom_three_labels_and_fail_closed_rank_validation(self) -> None:
        np.testing.assert_array_equal(MODULE._bottom3_labels([1, 2, 3, 4, 5], 5),
                                      [False, False, True, True, True])
        np.testing.assert_array_equal(MODULE._bottom3_labels(np.arange(1, 11), 10),
                                      [False] * 7 + [True] * 3)
        for ranks, field_n in (([1, 2, 3.5], 3), ([1, 2, np.nan], 3), ([1, 1, 3], 3),
                               ([1, 2], 2), ([1, 2, 3], 3.5)):
            with self.subTest(ranks=ranks, field_n=field_n):
                with self.assertRaises((RuntimeError, ValueError, TypeError)):
                    MODULE._bottom3_labels(ranks, field_n)

    def test_temperature_objective_matches_independent_single_race_formula(self) -> None:
        utility = np.asarray([0.5, 0.2, -0.1, 0.3, -0.3])
        truth = (2, 3, 4)
        temperature = 1.7
        objective = MODULE.bottom3_set_nll(utility, temperature, truth)
        terms = [sum(utility[list(s)]) / temperature for s in itertools.combinations(range(5), 3)]
        log_z = float(np.log(np.exp(np.asarray(terms) - max(terms)).sum()) + max(terms))
        expected = log_z - sum(utility[list(truth)]) / temperature
        self.assertAlmostEqual(objective, expected, places=14)
        with self.assertRaises((RuntimeError, ValueError, TypeError)):
            MODULE.bottom3_set_nll(utility, temperature, (0, 1.5, 2))

    def test_bounded_temperature_diagnostics_include_both_endpoints(self) -> None:
        records = [
            {"utilities": [0.5, 0.2, -0.1, 0.3, -0.3], "truth_indices": (2, 3, 4)},
            {"utilities": [-0.4, 0.1, 0.8, 0.2, 0.0], "truth_indices": (0, 3, 4)},
        ]
        result = MODULE.fit_bottom3_temperature(records)
        self.assertGreaterEqual(result["temperature"], 0.35)
        self.assertLessEqual(result["temperature"], 4.0)
        self.assertEqual(set(result["endpoint_objectives"]), {"0.35", "4.0"})
        self.assertEqual(MODULE.TEMPERATURE_FIT_CALLS, 0)

    def test_selection_tolerance_and_horse_number_tiebreak(self) -> None:
        selected = MODULE.choose_bottom3([0.9, 0.7, 0.2, 0.5, -0.1], [9, 1, 4, 6, 8])
        self.assertEqual([9, 1, 6], [int([9, 1, 4, 6, 8][i]) for i in selected])
        tied = MODULE.choose_bottom3([1.0, 1.0 - 0.5e-12, 0.0, -1.0], [7, 2, 5, 3])
        self.assertEqual(tied[0], 1)

    def test_one_race_reliability_is_accumulated_without_retained_history(self) -> None:
        accumulator = MODULE._new_reliability_accumulator()
        MODULE._accumulate_reliability(accumulator, arm="B", year=2026,
                                       set_probabilities=np.asarray([0.2, 0.3, 0.5]),
                                       true_subset_index=2,
                                       runner_probabilities=np.asarray([0.1, 0.5, 0.8]),
                                       runner_labels=np.asarray([0, 1, 1]))
        frame = MODULE._reliability_frame(accumulator)
        self.assertEqual(len(frame), 2 * 2 * 4 * 16)
        self.assertEqual(int(frame.loc[(frame.arm == "B") & (frame.probability_kind == "set") &
                                       (frame.period == "ALL"), "event_count"].sum()), 3)
        self.assertEqual(int(frame.loc[(frame.arm == "B") & (frame.probability_kind == "runner") &
                                       (frame.period == "2026"), "event_count"].sum()), 3)
        self.assertTrue(all(not isinstance(value, np.ndarray) for value in accumulator.values()))

    def test_race_ledger_preserves_actual_set_and_exclusion_contract(self) -> None:
        record = {"race_id": "synthetic", "race_date": "2026-01-01", "year": 2026,
                  "n": 5, "horse_numbers": np.asarray([5, 1, 8, 3, 7]),
                  "utilities": np.asarray([0.8, 0.6, -0.2, -0.1, -0.4]),
                  "ranks": np.asarray([1, 2, 5, 4, 3]), "truth_indices": (2, 3, 4)}
        metrics, runners, event_data = MODULE._evaluate_arm_race(record, arm="B", temperature=1.0)
        self.assertEqual(metrics["actual_bottom3_horse_numbers"], [3, 7, 8])
        self.assertEqual(metrics["all_top3_retained"], not metrics["any_top3_excluded"])
        self.assertEqual(len(runners), 5)
        self.assertAlmostEqual(sum(row["p_bottom3"] for row in runners), 3.0, places=12)
        self.assertNotIn("subsets", event_data)

    def test_callback_counters_remain_zero(self) -> None:
        self.assertEqual(MODULE.LIGHTGBM_TRAIN_CALLS, 0)
        self.assertEqual(MODULE.TEMPERATURE_FIT_CALLS, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
