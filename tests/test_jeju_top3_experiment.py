import numpy as np
import pytest
from scipy.special import logsumexp

from scripts.run_jeju_top3_experiment import order_loss


def test_vectorized_calibration_likelihood_matches_independent_scalar():
    scores = np.array([1000.0, 999.0, 998.0, 997.0, -10.0, 3.0, 2.0, 1.0, 0.0])
    groups = [(0, 4, [(0, 1, 2), (1, 0, 2)]), (4, 9, [(1, 2, 3), (1, 2, 4)])]
    losses = []
    for lo, hi, orders in groups:
        logs = []
        for order in orders:
            remaining = list(range(lo, hi))
            lp = 0.0
            for local in order:
                absolute = lo + local
                lp += scores[absolute] * 2.3 - logsumexp(scores[remaining] * 2.3)
                remaining.remove(absolute)
            logs.append(lp)
        losses.append(-logsumexp(logs))
    assert order_loss(scores, groups, 2.3) == pytest.approx(np.mean(losses), abs=1e-10)
