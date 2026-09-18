import numpy as np
import pytest
from scipy.optimize import check_grad

from horse_racing.analysis.jeju_experience_calibration import (
    ExperienceSetCalibrator,
    evaluate_policy,
    experience_design,
    objective_gradient,
)
from horse_racing.analysis.jeju_joint_top3 import build_layout
from horse_racing.analysis.jeju_set_interaction import distribution


def example():
    layout = build_layout([4, 5], [[(0, 1, 2)], [(0, 1, 2)]])
    rng = np.random.default_rng(17)
    base = rng.normal(size=14)
    design = rng.normal(size=(14, 5))
    y = np.array([1, 1, 1, 0, 1, 1, 1, 0, 0])
    return base, design, layout, y


def test_design_edges_and_missing():
    x, g, m = experience_design([0, 1, 2, 3, 5, 6, np.nan], [1] * 7, [1, 1, np.nan, 1, 1, 1, 1])
    assert g == ["0", "1-2", "1-2", "3-5", "3-5", "6+", "unknown"]
    np.testing.assert_array_equal(x[:, 0], [1, 0, 0, 0, 0, 0, 0])
    np.testing.assert_array_equal(x[:, 3], [0, 0, 0, 0, 0, 0, 1])
    assert m == [False, False, True, False, False, False, False]
    with pytest.raises(ValueError):
        experience_design([-1], [1], [1])


@pytest.mark.parametrize("grouped", [True, False])
def test_calibration_gradient(grouped):
    base, z, layout, y = example()
    if not grouped:
        z = z[:, :0]
    theta = np.arange(1 + z.shape[1]) * 0.015 + 0.1
    error = check_grad(
        lambda t: objective_gradient(t, base, z, layout, y)[0],
        lambda t: objective_gradient(t, base, z, layout, y)[1],
        theta,
    )
    assert error < 1e-6


def test_identity_and_probability_contract():
    base, z, _, _ = example()
    m = ExperienceSetCalibrator()
    m.theta_ = np.zeros(6)
    np.testing.assert_array_equal(m.predict_logits(base, z), base)
    _, _, ls, lo, p = distribution(m.predict_logits(base[:4], z[:4]), [0.0, 1.0, 2.0, 3.0])
    assert abs(np.exp(ls).sum() - 1) < 1e-12 and abs(np.exp(lo).sum() - 1) < 1e-12
    assert abs(p.sum() - 3) < 1e-12


def test_fit_deterministic_and_objective_improves():
    base, z, layout, y = example()
    a = ExperienceSetCalibrator().fit(base, z, layout, y)
    b = ExperienceSetCalibrator().fit(base, z, layout, y)
    assert a.success_ and a.objective_ <= objective_gradient(np.zeros(6), base, z, layout, y)[0]
    np.testing.assert_array_equal(a.theta_, b.theta_)


def test_boundary_tie_excluded():
    base, z, layout, y = example()
    y[:4] = 1
    with pytest.raises(ValueError, match="boundary"):
        ExperienceSetCalibrator().fit(base, z, layout, y)


def test_fixed_policy_preserves_actions_but_not_confidence():
    ids = [1, 2, 3, 4]
    fixed = {"pick_horse_id": 1, "predicted_set": [1, 2, 3], "predicted_order": [1, 2, 3]}
    args = (
        ids,
        np.array([-4.0, 0.0, 0.0, 2.0]),
        np.array([0.0, 1.0, 2.0, 3.0]),
        [(1, 2, 3)],
        [1, 2, 3],
        1.0,
    )
    a = evaluate_policy(*args, fixed=fixed)
    b = evaluate_policy(*args)
    assert a["predicted_set"] == [1, 2, 3] and a["predicted_order"] == [1, 2, 3]
    assert a["pick_horse_id"] == 1 and b["pick_horse_id"] != 1
    assert a["set_hit"] and not b["set_hit"]
    np.testing.assert_array_equal(a["pl_marginals"], b["pl_marginals"])
    assert a["set_confidence"] < b["set_confidence"]
    assert a["place_brier"] == b["place_brier"] and a["order_nll"] == b["order_nll"]


def test_three_starters_constant_loss():
    layout = build_layout([3], [[(0, 1, 2)]])
    loss, g = objective_gradient(
        np.zeros(6), np.zeros(1), np.ones((1, 5)), layout, np.ones(3), l2=0
    )
    assert loss < 1e-10
    np.testing.assert_allclose(g, 0, atol=1e-12)
