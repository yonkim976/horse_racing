"""Independent toy checks for coherent follow-up probability heads."""
from __future__ import annotations

from itertools import combinations, permutations
import unittest

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import expit, logsumexp

from heads import (
    fit_first_temperature,
    fit_mixture_weight,
    fit_third_temperature,
    mixed,
    top2_ordered,
)


def reference_distribution(scores2, scores_first, q, temp_third, temp_first):
    """Enumerate the specified factorization without using heads.py."""
    scores2 = np.asarray(scores2, dtype=float)
    scores_first = np.asarray(scores_first, dtype=float)
    triples = list(combinations(range(len(scores2)), 3))
    orders = []
    mass = []
    for trio, trio_probability in zip(triples, q, strict=True):
        third_logits = -scores2[list(trio)] / temp_third
        third_prob = np.exp(third_logits - logsumexp(third_logits))
        for first, second, third in permutations(trio):
            third_index = trio.index(third)
            first_probability = expit(
                (scores_first[first] - scores_first[second]) / temp_first
            )
            orders.append((first, second, third))
            mass.append(trio_probability * third_prob[third_index] * first_probability)
    return np.asarray(orders, dtype=np.int64), np.asarray(mass, dtype=float)


def reference_marginals(n, orders, mass):
    win = np.zeros(n)
    top2 = np.zeros(n)
    top3 = np.zeros(n)
    quinella = np.zeros((n, n))
    qpl = np.zeros((n, n))
    exacta = np.zeros((n, n))
    for (first, second, third), probability in zip(orders, mass, strict=True):
        win[first] += probability
        top2[[first, second]] += probability
        top3[[first, second, third]] += probability
        quinella[first, second] += probability
        quinella[second, first] += probability
        exacta[first, second] += probability
        for left, right in ((first, second), (first, third), (second, third)):
            qpl[left, right] += probability
            qpl[right, left] += probability
    return {
        "win": win,
        "top2": top2,
        "top3": top3,
        "quinella": quinella,
        "qpl": qpl,
        "exacta": exacta,
    }


def temperature_reference(records, kind, bounds):
    """Optimize scalar NLL independently and include both closed endpoints."""
    lower, upper = bounds
    if kind == "third":
        def loss(temp):
            per_race = []
            for scores, outcome in records:
                scores = np.asarray(scores, dtype=float)
                outcome = np.asarray(outcome, dtype=float)
                trio = [int(np.flatnonzero(outcome == rank)[0]) for rank in (1, 2, 3)]
                actual_third = trio[2]
                logits = -scores[trio] / temp
                per_race.append(float(logsumexp(logits) - logits[trio.index(actual_third)]))
            return float(np.mean(per_race))
    else:
        def loss(temp):
            per_race = []
            for scores, outcome in records:
                scores = np.asarray(scores, dtype=float)
                outcome = np.asarray(outcome, dtype=float)
                first = int(np.flatnonzero(outcome == 1)[0])
                second = int(np.flatnonzero(outcome == 2)[0])
                logit = (scores[first] - scores[second]) / temp
                per_race.append(float(np.logaddexp(0.0, -logit)))
            return float(np.mean(per_race))
    opt = minimize_scalar(loss, bounds=(lower, upper), method="bounded")
    candidates = [lower, upper, float(opt.x)]
    return min(candidates, key=loss)


class HeadTests(unittest.TestCase):
    def test_top2_joint_matches_independent_enumeration_and_preserves_trio_marginals(self):
        scores2 = np.array([0.8, -0.4, 1.1, 0.2])
        scores_first = np.array([1.3, -0.2, 0.5, 0.1])
        q = np.array([0.1, 0.2, 0.3, 0.4])
        temp_third, temp_first = 0.73, 1.24

        orders, mass = top2_ordered(scores2, scores_first, q, temp_third, temp_first)
        expected_orders, expected_mass = reference_distribution(
            scores2, scores_first, q, temp_third, temp_first
        )

        self.assertEqual(orders.shape, (24, 3))
        self.assertEqual(len({tuple(row) for row in orders}), 24)
        self.assertEqual(set(map(tuple, orders)), set(map(tuple, expected_orders)))
        actual_by_order = {tuple(row): value for row, value in zip(orders, mass, strict=True)}
        expected_by_order = {
            tuple(row): value for row, value in zip(expected_orders, expected_mass, strict=True)
        }
        for order, expected in expected_by_order.items():
            self.assertAlmostEqual(actual_by_order[order], expected, places=13)
        self.assertTrue(np.isfinite(mass).all())
        self.assertTrue((mass >= 0).all())
        self.assertAlmostEqual(float(mass.sum()), 1.0, places=13)

        values = reference_marginals(4, orders, mass)
        expected_values = reference_marginals(4, expected_orders, expected_mass)
        for key in values:
            self.assertTrue(np.allclose(values[key], expected_values[key], atol=1e-13, rtol=0), key)

        # Summing joint order mass over a trio returns q exactly, so top3 and
        # QPL depend only on the fixed EL trio distribution.
        for trio, q_trio in zip(combinations(range(4), 3), q, strict=True):
            selected = np.isin(orders, trio).all(axis=1)
            self.assertAlmostEqual(float(mass[selected].sum()), q_trio, places=13)
        expected_top3 = np.zeros(4)
        expected_qpl = np.zeros((4, 4))
        for trio, q_trio in zip(combinations(range(4), 3), q, strict=True):
            expected_top3[list(trio)] += q_trio
            for left, right in combinations(trio, 2):
                expected_qpl[left, right] += q_trio
                expected_qpl[right, left] += q_trio
        self.assertTrue(np.allclose(values["top3"], expected_top3, atol=1e-13, rtol=0))
        self.assertTrue(np.allclose(values["qpl"], expected_qpl, atol=1e-13, rtol=0))

        # Among a fixed trio and fixed third place, the first-vs-second split
        # follows the independent logistic head.
        trio = (0, 1, 2)
        for first, second in ((0, 1), (1, 0), (0, 2), (2, 0), (1, 2), (2, 1)):
            order = (first, second, next(horse for horse in trio if horse not in (first, second)))
            third_prob = np.exp(-scores2[list(trio)] / temp_third)
            third_prob /= third_prob.sum()
            expected = q[0] * third_prob[trio.index(order[2])] * expit(
                (scores_first[first] - scores_first[second]) / temp_first
            )
            self.assertAlmostEqual(actual_by_order[order], float(expected), places=13)
        self.assertTrue(np.allclose(values["exacta"].sum(axis=1), values["win"], atol=1e-13))
        self.assertTrue(np.allclose(values["exacta"].sum(axis=0), values["top2"] - values["win"], atol=1e-13))
        self.assertTrue(np.allclose(values["quinella"].sum(axis=1), values["top2"], atol=1e-13))

    def test_mixture_endpoints_and_linear_interpolation(self):
        el = np.array([0.2, 0.8])
        full = np.array([0.7, 0.3])
        self.assertTrue(np.array_equal(mixed(el, full, 1.0), el))
        self.assertTrue(np.array_equal(mixed(el, full, 0.0), full))
        self.assertTrue(np.allclose(mixed(el, full, 0.25), 0.25 * el + 0.75 * full))

    def test_mixture_weight_matches_known_scalar_optimum(self):
        # Values are each model's probability for the realized ordered result
        # in a race. Swapping the two asymmetric observations makes w=0.5 the
        # exact optimum of the equal-race mixture NLL.
        p_el_events = np.array([0.8, 0.2])
        p_full_events = np.array([0.2, 0.8])

        def objective(weight):
            probability = weight * p_el_events + (1.0 - weight) * p_full_events
            return float(-np.mean(np.log(probability)))

        optimized = minimize_scalar(objective, bounds=(0.0, 1.0), method="bounded")
        expected = min([0.0, 1.0, float(optimized.x)], key=objective)
        weight, diagnostic = fit_mixture_weight(p_el_events, p_full_events)
        self.assertGreaterEqual(float(weight), 0.0)
        self.assertLessEqual(float(weight), 1.0)
        self.assertAlmostEqual(float(weight), expected, places=7)
        self.assertAlmostEqual(float(weight), 0.5, places=7)
        self.assertTrue(isinstance(diagnostic, dict))
        self.assertTrue(diagnostic)

    def test_temperature_fits_match_independent_conditional_losses(self):
        records = [
            (np.array([1.2, 0.1, -0.7, 0.4]), np.array([1, 2, 3, 90])),
            (np.array([-0.3, 1.5, 0.6, -1.1]), np.array([3, 1, 2, 91])),
            (np.array([0.2, 0.9, 1.4, -0.2]), np.array([2, 3, 1, 92])),
        ]
        bounds = (0.35, 4.0)
        third = fit_third_temperature(records, bounds=bounds)
        first = fit_first_temperature(records, bounds=bounds)
        self.assertGreaterEqual(third, bounds[0])
        self.assertLessEqual(third, bounds[1])
        self.assertGreaterEqual(first, bounds[0])
        self.assertLessEqual(first, bounds[1])
        self.assertAlmostEqual(third, temperature_reference(records, "third", bounds), places=5)
        self.assertAlmostEqual(first, temperature_reference(records, "first", bounds), places=5)

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            mixed([0.2, 0.8], [0.3, 0.7], 1.1)
        with self.assertRaises(ValueError):
            mixed([0.2, 0.8], [0.3], 0.5)
        with self.assertRaises(ValueError):
            top2_ordered([1, 2, 3], [1, 2, 3], [0.5], 1.0, 1.0)
        with self.assertRaises(ValueError):
            top2_ordered([1, 2, 3], [1, 2, 3], [1.0], 0.0, 1.0)
        with self.assertRaises(ValueError):
            fit_third_temperature([])
        with self.assertRaises(ValueError):
            fit_first_temperature([([1, 2, 3], [1, 1, 3])])
        with self.assertRaises(ValueError):
            fit_mixture_weight([0.2, -0.1], [0.3, 0.8])


if __name__ == "__main__":
    unittest.main()
