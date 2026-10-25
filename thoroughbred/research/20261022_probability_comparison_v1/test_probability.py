import itertools
import unittest

import numpy as np
import pandas as pd
from probability import (
    fit_order_temperature,
    fit_pair_beta,
    marginals,
    ordered_distribution,
    pair_features,
    support,
    trio_distribution,
)
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp


def exhaustive_distribution(scores, temp, order_temp, pair_x=None, beta=None):
    """Small independent enumerator used as a reference in tests."""
    scores = np.asarray(scores, dtype=float)
    triples = list(itertools.combinations(range(len(scores)), 3))
    energies = []
    for index, trio in enumerate(triples):
        value = sum(scores[horse] for horse in trio) / temp
        if pair_x is not None and beta is not None:
            value += float(np.dot(pair_x[index], beta))
        energies.append(value)
    weights = np.exp(np.asarray(energies) - max(energies))
    q = weights / weights.sum()

    orders = []
    masses = []
    for trio, q_trio in zip(triples, q, strict=True):
        for order in itertools.permutations(trio):
            remaining = list(trio)
            pl = 1.0
            for horse in order:
                choice_weights = np.exp(scores[remaining] / order_temp)
                pl *= choice_weights[remaining.index(horse)] / choice_weights.sum()
                remaining.remove(horse)
            orders.append(order)
            masses.append(q_trio * pl)
    return np.asarray(orders, dtype=int), np.asarray(masses), q


class ProbabilityTests(unittest.TestCase):
    def test_support_enumeration_and_small_field_boundaries(self):
        triples3, pairs3 = support(3)
        self.assertEqual(triples3.tolist(), [[0, 1, 2]])
        self.assertEqual(pairs3.tolist(), [[0, 1], [0, 2], [1, 2]])
        triples4, pairs4 = support(4)
        self.assertEqual(triples4.tolist(), [list(x) for x in itertools.combinations(range(4), 3)])
        self.assertEqual(pairs4.tolist(), [list(x) for x in itertools.combinations(range(4), 2)])
        self.assertEqual(support(2)[0].shape, (0, 3))
        self.assertEqual(support(1)[1].shape, (0, 2))
        self.assertFalse(triples4.flags.writeable)
        self.assertFalse(pairs4.flags.writeable)
        self.assertIs(support(4)[0], triples4)
        with self.assertRaises(ValueError):
            triples4[0, 0] = 9
        with self.assertRaises(ValueError):
            trio_distribution([1.0, 2.0], 1.0)

    def test_joint_distribution_matches_independent_enumeration(self):
        scores = np.array([1.7, -0.4, 0.2, 1.0])
        temp, order_temp = 0.83, 1.21
        x = np.array(
            [[0.1, -0.5, 0.4], [0.7, 0.0, -0.2], [-0.3, 0.9, 0.1], [0.2, -0.2, 0.8]]
        )
        beta = np.array([0.25, -0.15, 0.1])
        expected_orders, expected_mass, expected_q = exhaustive_distribution(
            scores, temp, order_temp, x, beta
        )
        q = trio_distribution(scores, temp, x, beta)
        orders, mass = ordered_distribution(scores, q, order_temp)
        self.assertTrue(np.allclose(q, expected_q, atol=1e-12, rtol=0))
        self.assertEqual(orders.tolist(), expected_orders.tolist())
        self.assertFalse(orders.flags.writeable)
        self.assertIs(ordered_distribution(scores, q, order_temp)[0], orders)
        self.assertTrue(np.allclose(mass, expected_mass, atol=1e-12, rtol=0))
        self.assertAlmostEqual(float(q.sum()), 1.0, places=12)
        self.assertAlmostEqual(float(mass.sum()), 1.0, places=12)

        values = marginals(4, orders, mass)
        self.assertAlmostEqual(float(values["win"].sum()), 1.0, places=12)
        self.assertAlmostEqual(float(values["top2"].sum()), 2.0, places=12)
        self.assertAlmostEqual(float(values["top3"].sum()), 3.0, places=12)
        self.assertAlmostEqual(float(values["quinella"].sum() / 2), 1.0, places=12)
        self.assertAlmostEqual(float(values["qpl"].sum() / 2), 3.0, places=12)
        self.assertAlmostEqual(float(values["exacta"].sum()), 1.0, places=12)
        self.assertTrue(np.allclose(values["quinella"].sum(axis=1), values["top2"]))
        self.assertTrue(np.allclose(values["qpl"].sum(axis=1), 2 * values["top3"]))
        self.assertTrue(np.allclose(values["quinella"], values["quinella"].T))
        self.assertTrue(np.allclose(values["qpl"], values["qpl"].T))
        self.assertTrue(np.all(np.diag(values["quinella"]) == 0))
        self.assertTrue(np.all(np.diag(values["qpl"]) == 0))
        self.assertTrue(np.all(np.diag(values["exacta"]) == 0))
        self.assertTrue(np.all(values["win"] <= values["top2"] + 1e-12))
        self.assertTrue(np.all(values["top2"] <= values["top3"] + 1e-12))
        self.assertTrue(np.all(values["quinella"] <= values["qpl"] + 1e-12))
        for i in range(4):
            for j in range(4):
                if i != j:
                    self.assertLessEqual(values["qpl"][i, j], values["top3"][i] + 1e-12)
                    self.assertLessEqual(values["qpl"][i, j], values["top3"][j] + 1e-12)
        duplicate_orders = orders.copy()
        duplicate_orders[0] = duplicate_orders[1]
        with self.assertRaises(ValueError):
            marginals(4, duplicate_orders, mass)
        fractional_orders = orders.astype(float)
        fractional_orders[0, 0] += 0.5
        with self.assertRaises(ValueError):
            marginals(4, fractional_orders, mass)

    def test_vectorized_n14_matches_independent_enumeration(self):
        scores = np.linspace(-1.1, 1.3, 14)
        x = np.column_stack(
            (
                np.linspace(0.0, 0.4, 364),
                np.sin(np.arange(364) / 17.0),
                np.cos(np.arange(364) / 23.0),
            )
        )
        beta = np.array([0.2, -0.12, 0.08])
        q = trio_distribution(scores, 0.91, x, beta)
        expected_orders, expected_mass, expected_q = exhaustive_distribution(
            scores, 0.91, 1.17, x, beta
        )
        orders, mass = ordered_distribution(scores, q, 1.17)
        self.assertEqual(orders.shape, (2184, 3))
        self.assertEqual(orders.tolist(), expected_orders.tolist())
        self.assertTrue(np.allclose(q, expected_q, atol=1e-13, rtol=0))
        self.assertTrue(np.allclose(mass, expected_mass, atol=1e-13, rtol=0))
        self.assertAlmostEqual(float(mass.sum()), 1.0, places=12)
        actual_marginals = marginals(14, orders, mass)
        expected_marginals = {
            "win": np.zeros(14),
            "top2": np.zeros(14),
            "top3": np.zeros(14),
            "quinella": np.zeros((14, 14)),
            "qpl": np.zeros((14, 14)),
            "exacta": np.zeros((14, 14)),
        }
        for (first, second, third), probability in zip(
            expected_orders, expected_mass, strict=True
        ):
            expected_marginals["win"][first] += probability
            expected_marginals["top2"][[first, second]] += probability
            expected_marginals["top3"][[first, second, third]] += probability
            expected_marginals["quinella"][first, second] += probability
            expected_marginals["quinella"][second, first] += probability
            expected_marginals["exacta"][first, second] += probability
            for left, right in ((first, second), (first, third), (second, third)):
                expected_marginals["qpl"][left, right] += probability
                expected_marginals["qpl"][right, left] += probability
        for name in actual_marginals:
            self.assertTrue(
                np.allclose(actual_marginals[name], expected_marginals[name], atol=1e-13, rtol=0),
                name,
            )

    def test_three_runner_boundary_and_tied_scores(self):
        scores = np.zeros(4)
        q = trio_distribution(scores, 1.0)
        self.assertTrue(np.allclose(q, np.full(4, 0.25)))
        orders, mass = ordered_distribution(scores, q, 1.0)
        self.assertEqual(len(orders), 24)
        self.assertTrue(np.allclose(mass, np.full(24, 1 / 24)))
        values = marginals(4, orders, mass)
        self.assertTrue(np.allclose(values["win"], 0.25))
        self.assertTrue(np.allclose(values["top2"], 0.5))
        self.assertTrue(np.allclose(values["top3"], 0.75))

        q3 = trio_distribution([0.2, 0.2, 0.2], 2.0)
        orders3, mass3 = ordered_distribution([0.2, 0.2, 0.2], q3, 4.0)
        self.assertEqual(orders3.shape, (6, 3))
        self.assertTrue(np.allclose(mass3, np.full(6, 1 / 6)))
        self.assertTrue(np.allclose(marginals(3, orders3, mass3)["top3"], 1.0))

    def test_pair_feature_ranks_ties_and_missing_histories(self):
        frame = pd.DataFrame(
            {
                "front_gate_probability": [0.5, np.nan, 0.2, 0.8],
                "section_last600_mean3": [10.0, 12.0, 10.0, np.nan],
                "section_late_mean3": [14.0, np.nan, 13.0, 11.0],
            }
        )
        x = pair_features(frame)
        self.assertEqual(x.shape, (4, 3))
        # The first trio is (0,1,2). Its pair means are independently computed
        # from the specified p-front products and centered average ranks.
        self.assertAlmostEqual(x[0, 0], 0.1 / 3)
        self.assertAlmostEqual(x[0, 1], (-2 / 3 + 1 / 3 - 2 / 3) / 3)
        self.assertAlmostEqual(x[0, 2], (-2 / 3 + 0.0 + 0.0) / 3)
        # Missing p-front and one-sided late history contribute zero.
        self.assertAlmostEqual(x[1, 0], (0.4 + 0.0 + 0.0) / 3)
        self.assertAlmostEqual(x[1, 2], (-2 / 3 + 0.0 + 0.0) / 3)

    def test_fit_order_temperature_and_reject_tied_or_missing_top3(self):
        races = [
            (np.array([1.4, 0.8, -0.2, -0.7]), np.array([1, 2, 3, 91])),
            (np.array([-0.2, 1.2, 0.7, -1.0]), np.array([3, 1, 2, 92])),
        ]
        temperature = fit_order_temperature(races, bounds=(0.35, 4.0))
        self.assertGreaterEqual(temperature, 0.35)
        self.assertLessEqual(temperature, 4.0)
        self.assertTrue(np.isfinite(temperature))

        ordered_scores = np.asarray(
            [
                [scores[np.flatnonzero(outcome == rank)[0]] for rank in (1, 2, 3)]
                for scores, outcome in races
            ]
        )

        def scalar_reference(inverse_temp):
            losses = []
            for row in ordered_scores:
                utility = row * inverse_temp
                loss = logsumexp(utility) - utility[0]
                loss += np.logaddexp(utility[1], utility[2]) - utility[1]
                losses.append(loss)
            return float(np.mean(losses))

        optimized = minimize_scalar(
            scalar_reference, bounds=(1 / 4.0, 1 / 0.35), method="bounded"
        )
        candidates = [optimized.x, 1 / 4.0, 1 / 0.35]
        expected_temperature = 1 / min(candidates, key=scalar_reference)
        self.assertAlmostEqual(temperature, expected_temperature, places=8)
        with self.assertRaises(ValueError):
            fit_order_temperature([(races[0][0], [1, 1, 3, 91])])
        with self.assertRaises(ValueError):
            fit_order_temperature([(races[0][0], [1, 2, 92, 93])])

    def test_fit_pair_beta_returns_bounded_coefficients_and_diagnostics(self):
        scores = np.array([1.0, 0.4, -0.2, -0.8])
        features = np.array(
            [[0.0, 0.2, -0.4], [0.3, -0.2, 0.1], [-0.1, 0.6, 0.2], [0.4, 0.1, -0.3]]
        )
        races = [
            (scores, 1.0, np.array([1, 2, 3, 91]), features),
            (scores[::-1], 0.9, np.array([3, 2, 1, 92]), features[::-1]),
            (scores + 0.15, 1.1, np.array([2, 1, 3, 92]), features * -0.7),
        ]
        beta, diagnostics = fit_pair_beta(races, ridge=0.01, bound=2.0, maxiter=100)
        self.assertEqual(beta.shape, (3,))
        self.assertTrue(np.isfinite(beta).all())
        self.assertTrue(np.all(np.abs(beta) <= 2.0))
        self.assertTrue(diagnostics["success"])
        self.assertLessEqual(diagnostics["iterations"], 100)
        self.assertTrue(np.isfinite(diagnostics["objective"]))
        with self.assertRaises(ValueError):
            fit_pair_beta([(scores, 1.0, [1, 1, 3, 91], features)])

    def test_invalid_probability_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            trio_distribution([0, 1, 2], 0)
        with self.assertRaises(ValueError):
            trio_distribution([0, 1, 2, 3], 1, np.zeros((4, 2)))
        with self.assertRaises(ValueError):
            ordered_distribution([0, 1, 2], [0.8], 1)
        with self.assertRaises(ValueError):
            ordered_distribution([0, 1, 2], [1.1], 1)


if __name__ == "__main__":
    unittest.main()
