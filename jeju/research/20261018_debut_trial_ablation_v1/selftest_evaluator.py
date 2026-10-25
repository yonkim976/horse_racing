"""Synthetic checks for fixed-date bootstrap aggregation and raw-score ties."""
from __future__ import annotations

import numpy as np
import pandas as pd

from evaluate_candidate import _pair_concordance_score, _primary_bootstrap


def main() -> None:
    # Empty dates remain in the fixed 4-date roster and add no race count or loss.
    cold = pd.DataFrame({
        "race_id": ["r1", "r1", "r2", "r2"],
        "race_date": ["d1", "d1", "d3", "d3"],
        "log_loss_candidate": [0.2, 0.4, 0.6, 0.8],
        "log_loss_baseline": [0.4, 0.6, 0.8, 1.0],
        "brier_candidate": [0.1, 0.3, 0.5, 0.7],
        "brier_baseline": [0.2, 0.4, 0.6, 0.8],
    })
    dates = ["d1", "d2", "d3", "d4"]
    schedule = np.asarray([[0, 1, 2, 3], [2, 2, 0, 1], [3, 1, 3, 0]], dtype="int64")
    summary, draws = _primary_bootstrap(cold, dates, schedule)
    assert summary.metric.tolist() == ["log_loss", "brier"]
    assert np.allclose(summary.delta_candidate_minus_baseline.to_numpy(float), [-0.2, -0.1])
    assert summary.valid_draws.eq(3).all() and len(draws) == 6
    assert _pair_concordance_score(np.asarray([1.0]), np.asarray([1.0])) == 0.5
    assert _pair_concordance_score(np.asarray([2.0, 3.0]), np.asarray([0.0, 1.0])) == 1.0
    assert _pair_concordance_score(np.asarray([0.0, 1.0]), np.asarray([2.0, 3.0])) == 0.0
    print("evaluator synthetic checks passed: fixed dates with empty support, race weighting, exact score ties")


if __name__ == "__main__":
    main()
