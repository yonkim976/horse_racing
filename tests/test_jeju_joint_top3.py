import itertools
import pickle

import numpy as np

from horse_racing.analysis.jeju_joint_top3 import JointTop3MLP


def _finite_difference(model, scores, layout, weight):
    numeric = np.zeros_like(scores)
    for row in range(scores.shape[0]):
        for col in range(scores.shape[1]):
            plus = scores.copy()
            minus = scores.copy()
            plus[row, col] += 1e-6
            minus[row, col] -= 1e-6
            numeric[row, col] = (
                model.scores_loss_and_gradient(plus, layout, weight)[0]
                - model.scores_loss_and_gradient(minus, layout, weight)[0]
            ) / 2e-6
    return numeric


def test_score_gradient_matches_finite_difference():
    rng = np.random.default_rng(11)
    scores = rng.normal(size=(7, 2))
    orders = [[(0, 1, 2), (1, 0, 2)], [(0, 1, 2)]]
    model = JointTop3MLP()
    layout = model.prepare_layout([4, 3], orders)
    value, gradient = model.scores_loss_and_gradient(scores, layout, 0.5)
    assert np.isfinite(value)
    np.testing.assert_allclose(gradient, _finite_difference(model, scores, layout, 0.5), atol=2e-7)


def test_tied_order_union_has_normalized_set_and_joint_loss():
    model = JointTop3MLP()
    tied_set = list(itertools.permutations((0, 1, 2)))
    layout = model.prepare_layout([4], [tied_set])
    scores = np.zeros((4, 2))
    loss, gradient = model.scores_loss_and_gradient(scores, layout, 0.5)
    np.testing.assert_allclose(loss, np.log(4.0), atol=1e-12)
    assert np.all(np.isfinite(gradient))

    all_orders = []
    for selected in itertools.combinations(range(4), 3):
        all_orders.extend(itertools.permutations(selected))
    layout = model.prepare_layout([4], [all_orders])
    loss, _ = model.scores_loss_and_gradient(scores, layout, 1.0)
    np.testing.assert_allclose(loss, 0.0, atol=1e-12)


def test_fit_reduces_loss_is_deterministic_and_picklable():
    race_x = np.asarray([[2.0, 1.0], [0.0, 0.0], [-2.0, -1.0]])
    x = np.tile(race_x, (10, 1))
    sizes = [3] * 10
    orders = [[(0, 1, 2)]] * 10
    model = JointTop3MLP(max_iter=35)
    layout = model.prepare_layout(sizes, orders)
    initial, _ = model.scores_loss_and_gradient(np.zeros((len(x), 2)), layout, 1.0)
    model.fit(x, sizes, orders, tune=(x, sizes, orders), seed=17, joint_weight=1.0)
    assert model.loss(x, sizes, orders, joint_weight=1.0) < initial
    assert model.tune_objective_ is not None
    assert 0 <= model.selected_iteration_ <= model.n_iter_
    assert np.all(np.isfinite(model.predict(x)))

    restored = pickle.loads(pickle.dumps(model))
    np.testing.assert_array_equal(model.predict(x), restored.predict(x))
    repeated = JointTop3MLP(max_iter=35).fit(
        x, sizes, orders, tune=(x, sizes, orders), seed=17, joint_weight=1.0
    )
    np.testing.assert_array_equal(model.predict(x), repeated.predict(x))
