from datetime import date

import polars as pl
import pytest

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.training_state import FEATURES, add_features


def _base() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1],
            "horse_id": [10],
            "race_date": [date(2026, 9, 4)],
            "train_n_7d": [1],
            "train_n_28d": [1],
            "train_dur_28d": [750.0],
            "gallop_n_28d": [1.0],
            "canter_n_28d": [2.0],
        }
    )


def test_training_state_uses_prior_personal_baseline_and_excludes_race_day() -> None:
    training = pl.DataFrame(
        {
            "horse_id": [10] * 4,
            "event_date": [
                date(2026, 4, 1),
                date(2026, 5, 1),
                date(2026, 8, 20),
                date(2026, 9, 4),  # target day must not be counted
            ],
        }
    )
    row = add_features(_base(), SourceFrames(training=training)).row(0, named=True)

    # Three strictly prior events in 180d minus the one represented in the 28d input.
    assert row["train_prior_n_29_180d"] == 2
    expected = 2 * 28 / 152
    assert row["train_frequency_dev_28_prior"] == pytest.approx(1 - expected)
    assert row["train_frequency_ratio_7_28"] == pytest.approx(4 * 2 / 5)
    assert row["train_avg_duration_28d"] == pytest.approx(750.0)
    assert row["train_gallop_per_day_28d"] == pytest.approx(1.0)
    assert row["train_canter_per_day_28d"] == pytest.approx(2.0)


def test_training_state_empty_source_has_stable_schema() -> None:
    result = add_features(_base(), SourceFrames())
    assert {spec.name for spec in FEATURES} <= set(result.columns)
    assert result["train_prior_n_29_180d"].item() == 0
    assert result["train_frequency_dev_28_prior"].item() is None
