import pickle

import numpy as np
import pytest

from horse_racing.analysis.jeju_top3_direct import (
    DirectTop3Linear,
    top3_objective_and_gradient,
)


def _finite_difference(function, values, epsilon=1e-6):
    numerical = np.zeros_like(values)
    for index in range(len(values)):
        plus = values.copy()
        minus = values.copy()
        plus[index] += epsilon
        minus[index] -= epsilon
        numerical[index] = (function(plus) - function(minus)) / (2.0 * epsilon)
    return numerical


def test_analytic_gradient_matches_finite_difference():
    X = np.array(
        [[1.0, 0.2], [-0.4, 1.1], [0.7, -0.8], [1.4, 0.3], [-1.0, 0.5], [0.2, -0.6]],
        dtype=float,
    )
    sizes = [3, 3]
    orders = [[(0, 1, 2)], [(1, 0, 2), (0, 1, 2)]]
    weights = np.array([0.37, -0.29])

    objective, gradient = top3_objective_and_gradient(weights, X, sizes, orders, l2=0.07)
    numerical = _finite_difference(
        lambda candidate: top3_objective_and_gradient(candidate, X, sizes, orders, l2=0.07)[0],
        weights,
    )

    assert np.isfinite(objective)
    assert gradient == pytest.approx(numerical, rel=2e-5, abs=2e-6)


def test_tied_accepted_orders_sum_their_pl_probabilities():
    # With four equally scored starters, each ordered triple is 1/(4*3*2).
    X = np.zeros((4, 1))
    weights = np.array([0.0])
    tied_objective, _ = top3_objective_and_gradient(
        weights, X, [4], [[(0, 1, 2), (1, 0, 2)]], l2=0.0
    )
    one_order_objective, _ = top3_objective_and_gradient(weights, X, [4], [[(0, 1, 2)]], l2=0.0)

    assert tied_objective == pytest.approx(-np.log(2.0 / 24.0))
    assert tied_objective == pytest.approx(one_order_objective - np.log(2.0))


def test_nonaccepted_starter_remains_in_pl_denominators():
    # The fourth starter is a DQ-like row: it cannot be in accepted_orders, but
    # it still dilutes every numerator probability.
    weights = np.array([0.0])
    with_dq, _ = top3_objective_and_gradient(weights, np.zeros((4, 1)), [4], [[(0, 1, 2)]], l2=0.0)
    without_dq, _ = top3_objective_and_gradient(
        weights, np.zeros((3, 1)), [3], [[(0, 1, 2)]], l2=0.0
    )

    assert with_dq == pytest.approx(np.log(4.0 * 3.0 * 2.0))
    assert without_dq == pytest.approx(np.log(3.0 * 2.0 * 1.0))
    assert with_dq > without_dq


def test_fit_reduces_race_averaged_objective_and_round_trips_pickle():
    rng = np.random.default_rng(43)
    race_count = 24
    starters = 4
    X = []
    orders = []
    for _ in range(race_count):
        latent = rng.normal(size=starters)
        X.extend(np.column_stack((latent, rng.normal(scale=0.2, size=starters))))
        ranking = np.argsort(-latent)
        orders.append([tuple(int(value) for value in ranking[:3])])
    X = np.asarray(X)
    sizes = [starters] * race_count
    initial = top3_objective_and_gradient(np.zeros(X.shape[1]), X, sizes, orders, l2=0.01)[0]

    model = DirectTop3Linear(l2=0.01, max_iter=100).fit(X, sizes, orders)

    assert model.objective_ < initial
    assert model.n_iter_ <= 100
    assert model.success_
    restored = pickle.loads(pickle.dumps(model))
    assert restored.predict(X) == pytest.approx(model.predict(X))
