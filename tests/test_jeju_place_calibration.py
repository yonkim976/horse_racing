import pickle

import numpy as np
import pytest

from horse_racing.analysis.jeju_place_calibration import (
    PositivePlattCalibrator,
    positive_platt_objective_and_gradient,
)


def test_weighted_objective_matches_manual_binary_logloss():
    scores = np.array([-1.0, 0.5, 2.0])
    labels = np.array([0.0, 1.0, 1.0])
    weights = np.array([1.0, 2.0, 3.0])
    params = np.array([np.log(2.0), -0.25])
    objective, gradient = positive_platt_objective_and_gradient(params, scores, labels, weights)
    logits = 2.0 * scores - 0.25
    manual = np.average(np.logaddexp(0.0, logits) - labels * logits, weights=weights)

    assert objective == pytest.approx(manual)
    assert np.all(np.isfinite(gradient))


def test_fit_has_positive_monotonic_slope_and_improves_calibration_loss():
    scores = np.array([-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0])
    labels = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    initial = positive_platt_objective_and_gradient(np.zeros(2), scores, labels)[0]
    model = PositivePlattCalibrator().fit(scores, labels)
    probabilities = model.predict(scores)

    assert model.scale_ > 0.0
    assert np.all(np.diff(probabilities) >= 0.0)
    assert probabilities[3] > probabilities[2]
    assert model.objective_ < initial
    assert model.success_


def test_pickle_round_trip_preserves_calibrated_probabilities():
    scores = np.array([-2.0, -0.5, 0.25, 1.5])
    labels = np.array([0.0, 0.0, 1.0, 1.0])
    model = PositivePlattCalibrator().fit(scores, labels)
    restored = pickle.loads(pickle.dumps(model))

    assert restored.predict(scores) == pytest.approx(model.predict(scores))
    assert restored.scale_ == pytest.approx(model.scale_)
    assert restored.intercept_ == pytest.approx(model.intercept_)


def test_extreme_finite_scores_produce_finite_fit_and_predictions():
    scores = np.array([-1e300, -1e100, 0.0, 1e100, 1e300])
    labels = np.array([0.0, 0.0, 0.0, 1.0, 1.0])
    model = PositivePlattCalibrator().fit(scores, labels)
    probabilities = model.predict(scores)

    assert np.isfinite(model.objective_)
    assert np.isfinite(probabilities).all()
    assert ((probabilities >= 0.0) & (probabilities <= 1.0)).all()


@pytest.mark.parametrize(
    "scores,labels,weights",
    [
        ([], [], None),
        ([0.0, 1.0], [0.0], None),
        ([0.0, 1.0], [0.0, 2.0], None),
        ([0.0, 1.0], [0.0, 1.0], [0.0, 0.0]),
        ([0.0, np.nan], [0.0, 1.0], None),
        ([0.0, 1.0], [0.0, 1.0], [-1.0, 1.0]),
    ],
)
def test_invalid_training_inputs_are_rejected(scores, labels, weights):
    with pytest.raises(ValueError):
        PositivePlattCalibrator().fit(scores, labels, weights)
