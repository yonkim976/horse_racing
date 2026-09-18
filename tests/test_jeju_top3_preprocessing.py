import numpy as np
import polars as pl

from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor


def test_fit_only_unknown_categories_and_missing_are_finite():
    fit = pl.DataFrame(
        {"x": [1.0, 3.0, None], "constant": [1.0, 1.0, 1.0], "regime": ["a", "a", "b"]}
    )
    pre = FitPreprocessor().fit(fit, ["x", "constant", "regime"])
    before = pre.transform(fit).copy()
    future = pl.DataFrame({"x": [1e9, None], "constant": [9.0, None], "regime": ["new", "new"]})
    transformed = pre.transform(future)
    assert np.isfinite(transformed).all()
    np.testing.assert_array_equal(pre.transform(fit), before)
    assert "constant" not in pre.names
    assert pre.medians[0] == 2
    assert pre.regimes == ["a", "b"]
    assert not transformed[:, -2:].any()
