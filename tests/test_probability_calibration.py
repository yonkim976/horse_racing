from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from horse_racing.analysis.probability_calibration import (
    apply_probability_calibration,
    fit_probability_calibration,
    load_probability_calibration,
    save_probability_calibration,
)


def _training_frame() -> pl.DataFrame:
    rows: list[dict[str, float | int]] = []
    for race_id in range(1, 21):
        for horse in range(1, 7):
            win = int(horse == 1)
            top2 = int(horse <= 2)
            top3 = int(horse <= 3)
            rows.append(
                {
                    "race_id": race_id,
                    "race_entry_id": race_id * 10 + horse,
                    "horse_number": horse,
                    "prob_win": [0.35, 0.25, 0.15, 0.1, 0.08, 0.07][horse - 1],
                    "prob_top2": [0.7, 0.55, 0.3, 0.2, 0.15, 0.1][horse - 1],
                    "prob_top3": [0.9, 0.8, 0.65, 0.35, 0.2, 0.1][horse - 1],
                    "win": win,
                    "top2": top2,
                    "top3": top3,
                }
            )
    return pl.DataFrame(rows)


def test_posthoc_calibration_preserves_race_constraints() -> None:
    frame = _training_frame()
    bundle = fit_probability_calibration(
        frame,
        source_run_id="source-run",
        fit_period="2025",
    )
    calibrated = apply_probability_calibration(bundle, frame)
    sums = calibrated.group_by("race_id").agg(
        pl.col("prob_win").sum(),
        pl.col("prob_top2").sum(),
        pl.col("prob_top3").sum(),
        pl.col("prob_rank2").sum(),
        pl.col("prob_rank3").sum(),
    )

    assert calibrated["prob_win_raw"].to_list() == pytest.approx(
        frame["prob_win"].to_list()
    )
    assert calibrated["prob_top2"].to_list() != pytest.approx(frame["prob_top2"].to_list())
    assert sums["prob_win"].to_list() == pytest.approx([1.0] * sums.height)
    assert sums["prob_top2"].to_list() == pytest.approx([2.0] * sums.height)
    assert sums["prob_top3"].to_list() == pytest.approx([3.0] * sums.height)
    assert sums["prob_rank2"].to_list() == pytest.approx([1.0] * sums.height)
    assert sums["prob_rank3"].to_list() == pytest.approx([1.0] * sums.height)
    values = calibrated.select("prob_win", "prob_top2", "prob_top3").to_numpy()
    assert np.all(values[:, 0] <= values[:, 1] + 1e-10)
    assert np.all(values[:, 1] <= values[:, 2] + 1e-10)
    assert {"prob_win_raw", "prob_top2_raw", "prob_top3_raw"} <= set(calibrated.columns)


def test_probability_calibration_round_trip(tmp_path) -> None:
    bundle = fit_probability_calibration(
        _training_frame(),
        source_run_id="source-run",
        fit_period="2025",
    )
    path = tmp_path / "calibration.pkl"
    save_probability_calibration(bundle, path)
    loaded = load_probability_calibration(path)

    assert loaded.source_run_id == "source-run"
    assert loaded.methods == {"win": "identity", "top2": "sigmoid", "top3": "sigmoid"}
    assert loaded.calibrators["top2"] == bundle.calibrators["top2"]
