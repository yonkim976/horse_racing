"""Outcome-free synthetic checks for the fixed-date paired bootstrap helper."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from evaluate_candidate import _bootstrap_values  # noqa: E402


def main() -> None:
    # The date inventory keeps all three dates. The middle date has no primary
    # cohort races and therefore contributes zero to both numerator and count.
    pairs = pd.DataFrame({
        "race_date": ["d0", "d2"],
        "metric_candidate": [2.0, 8.0],
        "metric_baseline": [1.0, 5.0],
    })
    dates = ["d0", "d1", "d2"]
    schedule = np.asarray([[0, 1, 2], [1, 2, 1], [1, 1, 1]], dtype="int64")
    point, low, high, draws, valid = _bootstrap_values(pairs, "metric", dates, schedule)
    assert point == 2.0
    assert np.allclose(draws[:2], [2.0, 3.0], rtol=0, atol=0)
    assert np.isnan(draws[2]) and valid == 2
    assert low == 2.025 and high == 2.975
    assert len(draws) == 3


if __name__ == "__main__":
    main()
    print("evaluator synthetic bootstrap check passed")
