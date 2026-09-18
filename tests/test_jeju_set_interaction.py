"""Set interaction objective, symmetric features and coherent predictions."""

from itertools import combinations, permutations

import numpy as np
from scipy.optimize import check_grad
from scipy.special import logsumexp

from horse_racing.analysis.jeju_joint_top3 import build_layout
from horse_racing.analysis.jeju_set_interaction import (
    INTERACTION_INPUTS,
    SetInteractionMLP,
    distribution,
    evaluate_set_race,
    interaction_features,
    set_loss_gradient,
)


def test_set_gradient_boundary_ties():
    layout = build_layout([4, 4], [[(0, 1, 2)], [(0, 1, 2), (0, 1, 3)]])
    logits = np.arange(8) * 0.17
    err = check_grad(
        lambda t: set_loss_gradient(t, layout)[0], lambda t: set_loss_gradient(t, layout)[1], logits
    )
    assert err < 1e-6
    assert abs(set_loss_gradient(logits, layout)[1].sum()) < 1e-12


def test_all_sets_accepted_zero_loss():
    layout = build_layout([4], [list(combinations(range(4), 3))])
    loss, grad = set_loss_gradient(np.arange(4.0), layout)
    assert abs(loss) < 1e-12
    np.testing.assert_allclose(grad, 0, atol=1e-12)


def test_network_gradient_with_interactions():
    rng = np.random.default_rng(17)
    x = rng.normal(size=(8, 3))
    z = rng.normal(size=(8, 2))
    layout = build_layout([4, 4], [[(0, 1, 2)], [(0, 1, 2), (0, 1, 3)]])
    m = SetInteractionMLP(hidden_dim=2)
    theta = rng.normal(0, 0.1, 3 * 2 + 2 * 2 + 1 + 2)
    err = check_grad(
        lambda t: m.loss_gradient(t, x, z, layout)[0],
        lambda t: m.loss_gradient(t, x, z, layout)[1],
        theta,
    )
    assert err < 1e-6


def test_features_are_symmetric_and_missing_safe():
    rng = np.random.default_rng(3)
    raw = rng.normal(size=(5, len(INTERACTION_INPUTS)))
    raw[0, 0] = np.nan
    raw[:, 1] = np.nan
    z = interaction_features(raw, [5])
    perm = np.array([3, 1, 4, 0, 2])
    shuffled = interaction_features(raw[perm], [5])
    lookup = {s: k for k, s in enumerate(combinations(range(5), 3))}
    for i, s in enumerate(combinations(range(5), 3)):
        np.testing.assert_allclose(shuffled[i], z[lookup[tuple(sorted(perm[list(s)]))]])
    assert z.shape == (10, 19) and np.isfinite(z).all()
    np.testing.assert_allclose(z[:, [1, 9]], 0)
    # Changing a later race cannot alter the first race's feature rows.
    a = interaction_features(np.vstack([raw, raw * 30]), [5, 5])
    np.testing.assert_allclose(a[:10], z)


def test_pair_terms_not_reducible_to_unary_sum():
    raw = np.repeat(np.arange(5.0)[:, None], len(INTERACTION_INPUTS), axis=1)
    z = interaction_features(raw, [5])
    design = np.zeros((10, 5))
    for i, s in enumerate(combinations(range(5), 3)):
        design[i, list(s)] = 1
    residual = design @ np.linalg.lstsq(design, z[:, 0], rcond=None)[0] - z[:, 0]
    assert np.linalg.norm(residual) > 0.01


def test_probability_mass_marginals_and_order():
    sets, orders, ls, lo, marg = distribution(np.arange(10.0) / 5, np.arange(5.0))
    assert abs(np.exp(ls).sum() - 1) < 1e-12
    assert abs(np.exp(lo).sum() - 1) < 1e-12
    assert abs(marg.sum() - 3) < 1e-12 and np.all((marg >= 0) & (marg <= 1))
    np.testing.assert_allclose(logsumexp(lo.reshape(-1, 6), axis=1), ls)
    brute = np.zeros(5)
    for order, lp in zip(orders, lo, strict=True):
        brute[order] += np.exp(lp)
    np.testing.assert_allclose(marg, brute)
    assert len(sets) == 10


def test_ties_and_pick_consistency():
    result = evaluate_set_race(
        [4, 3, 2, 1], [0.0] * 4, [0.0] * 4, [(1, 2, 3), (1, 2, 4)], [1, 2, 3, 4]
    )
    assert result["predicted_set"] == [1, 2, 3]
    assert result["predicted_order"] == [1, 2, 3]
    assert result["pick_horse_id"] == 1
    assert result["set_hit"] and result["order_hit"]
    assert abs(result["set_nll"] + np.log(0.5)) < 1e-12
    all_tie = evaluate_set_race(
        [1, 2, 3], [2.0], [0.0, 0.0, 0.0], list(permutations([1, 2, 3])), [1, 2, 3]
    )
    assert abs(all_tie["order_nll"]) < 1e-12


def test_fit_deterministic_and_tune_checkpoint():
    x = np.arange(12.0).reshape(4, 3) / 10
    z = np.zeros((4, 0))
    layout = build_layout([4], [[(0, 1, 2)]])
    a = SetInteractionMLP(hidden_dim=2, max_iter=3).fit(x, z, layout, tune=(x, z, layout), seed=17)
    b = SetInteractionMLP(hidden_dim=2, max_iter=3).fit(x, z, layout, tune=(x, z, layout), seed=17)
    np.testing.assert_array_equal(a.theta_, b.theta_)
    assert 0 <= a.selected_iteration_ <= 3
    assert np.isfinite(a.predict_sets(x, z, layout)).all()
