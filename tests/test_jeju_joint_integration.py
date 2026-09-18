"""Independent enumerator versus training objective, including boundary ties."""

import numpy as np
import pytest
from scipy.optimize._numdiff import approx_derivative

from horse_racing.analysis.jeju_joint_evaluation import evaluate_joint_race
from horse_racing.analysis.jeju_joint_top3 import JointTop3MLP, build_layout


@pytest.mark.parametrize("weight", [0.0, 0.5, 1.0])
def test_enumerator_loss_and_gradient_match_multiple_tied_races(weight):
    sizes = [4, 5]
    orders = [[(0, 1, 2), (0, 1, 3)], [(0, 1, 2), (1, 0, 2)]]
    scores = np.random.default_rng(17).normal(size=(9, 2))
    layout = build_layout(sizes, orders)
    model = JointTop3MLP()
    loss, gradient = model.scores_loss_and_gradient(scores, layout, joint_weight=weight)
    independent = []
    offset = 0
    for size, accepted in zip(sizes, orders, strict=True):
        ids = [str(i) for i in range(size)]
        result = evaluate_joint_race(
            ids,
            scores[offset : offset + size, 0],
            scores[offset : offset + size, 1],
            [tuple(str(i) for i in order) for order in accepted],
            sorted({str(i) for order in accepted for i in order}),
        )
        independent.append((1 - weight) * result["set_nll"] + weight * result["order_nll"])
        offset += size
    assert loss == pytest.approx(np.mean(independent), abs=1e-12)
    numeric = approx_derivative(
        lambda x: model.scores_loss_and_gradient(x.reshape(9, 2), layout, joint_weight=weight)[0],
        scores.ravel(),
    ).ravel()
    np.testing.assert_allclose(gradient.ravel(), numeric, atol=1e-8, rtol=1e-6)


def test_shared_network_parameter_gradient_and_temperature_gradient():
    rng = np.random.default_rng(31)
    x = rng.normal(size=(9, 3))
    scores = rng.normal(size=(9, 2))
    layout = build_layout([4, 5], [[(0, 1, 2), (0, 1, 3)], [(1, 2, 3)]])
    model = JointTop3MLP(hidden_dim=2, l2=0.001)
    theta = rng.normal(scale=0.1, size=2 * 3 + 3 * 2 + 2)
    _, gradient, _, _ = model._loss_gradient_theta(theta, x, layout, 0.5)
    numeric = approx_derivative(
        lambda t: model._loss_gradient_theta(t, x, layout, 0.5)[0], theta
    ).ravel()
    np.testing.assert_allclose(gradient, numeric, atol=1e-8, rtol=1e-6)

    def calibration(logs):
        scaled = scores * np.exp(logs)
        value, score_gradient = model.scores_loss_and_gradient(scaled, layout, joint_weight=1.0)
        return value, np.sum(score_gradient * scaled, axis=0)

    logs = np.array([0.4, -0.3])
    numeric = approx_derivative(lambda b: calibration(b)[0], logs).ravel()
    np.testing.assert_allclose(calibration(logs)[1], numeric, atol=1e-8, rtol=1e-6)
