import itertools

import numpy as np
import pytest
from scipy.optimize._numdiff import approx_derivative

from horse_racing.analysis.jeju_conditional_order import (
    ConditionalOrderMLP,
    build_layout,
    score_loss_gradient,
)


def test_score_gradient_including_boundary_ties():
    layout = build_layout([4, 3], [[(0, 1, 2), (0, 1, 3)], [(0, 1, 2), (1, 0, 2)]])
    scores = np.array([0.2, -0.8, 1.1, 0.4, 0.7, -0.5, 0.2])
    loss, grad = score_loss_gradient(scores, layout)
    numeric = approx_derivative(lambda s: score_loss_gradient(s, layout)[0], scores).ravel()
    np.testing.assert_allclose(grad, numeric, atol=1e-7)
    assert loss > 0 and abs(grad.sum()) < 1e-12


def test_single_order_matches_conditional_pl_and_nonpodium_has_zero_gradient():
    scores = np.array([0.7, 0.1, -0.4, 100.0])
    loss, grad = score_loss_gradient(scores, build_layout([4], [[(0, 1, 2)]]))
    w = np.exp(scores[:3])
    p = w[0] / w.sum() * w[1] / (w[1] + w[2])
    assert loss == pytest.approx(-np.log(p)) and grad[3] == 0
    assert score_loss_gradient(scores + 100, build_layout([4], [[(0, 1, 2)]]))[0] == pytest.approx(
        loss
    )


def test_all_tied_orders_have_unit_probability_and_zero_gradient():
    loss, grad = score_loss_gradient(
        np.array([0.8, -0.9, 0.3]), build_layout([3], [list(itertools.permutations(range(3)))])
    )
    assert abs(loss) < 1e-12
    np.testing.assert_allclose(grad, 0, atol=1e-12)


def test_uniform_set_weight_not_duplicate_order_weight():
    layout = build_layout([4], [[(0, 1, 2), (1, 0, 2), (0, 1, 3)]])
    loss, _ = score_loss_gradient(np.zeros(4), layout)
    assert np.exp(-loss) == pytest.approx((2 / 6 + 1 / 6) / 2)


def test_network_gradient_and_deterministic_training():
    rng = np.random.default_rng(4)
    x = rng.normal(size=(6, 2))
    layout = build_layout([3, 3], [[(0, 1, 2)], [(1, 2, 0)]])
    model = ConditionalOrderMLP(hidden_dim=2, max_iter=3)
    theta = rng.normal(size=9) * 0.1
    loss, g = model.loss_gradient(theta, x, layout)
    numerical = approx_derivative(lambda t: model.loss_gradient(t, x, layout)[0], theta).ravel()
    np.testing.assert_allclose(g, numerical, atol=1e-7)
    kwargs = dict(tune=(x, [3, 3], [[(0, 1, 2)], [(1, 2, 0)]]), seed=17)
    a = model.fit(x, [3, 3], [[(0, 1, 2)], [(1, 2, 0)]], **kwargs)
    b = ConditionalOrderMLP(hidden_dim=2, max_iter=3).fit(
        x, [3, 3], [[(0, 1, 2)], [(1, 2, 0)]], **kwargs
    )
    np.testing.assert_array_equal(a.predict(x), b.predict(x))


def test_invalid_layout():
    with pytest.raises(ValueError):
        build_layout([2], [[(0, 1, 2)]])
    with pytest.raises(ValueError):
        build_layout([3], [[(0, 1, 3)]])
    with pytest.raises(ValueError):
        build_layout([3], [[(0, 1, 2), (0, 1, 2)]])
