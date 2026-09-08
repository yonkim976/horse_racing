from datetime import date

import polars as pl
import pytest

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.lifecycle import FEATURES, add_features


def test_lifecycle_features_encode_regime_and_non_linear_rest() -> None:
    frame = pl.DataFrame(
        {
            "horse_id": [1, 2, 3],
            "meet_code": [1, 2, 3],
            "race_date": [date(2026, 9, 4)] * 3,
            "horse_age_months": [84.0, 48.0, 36.0],
            "days_since_last_race": [91, 14, None],
        }
    )
    rows = add_features(frame, SourceFrames()).to_dicts()

    assert rows[0]["age_regime_stage"] == "seoul_busan_7plus"
    assert rows[0]["rest_cycle_bin"] == "d91_180"
    assert rows[0]["rest_excess_41d"] == pytest.approx(50.0)
    assert rows[0]["senior_long_layoff"] == 1
    assert rows[0]["young_short_cycle"] == 0

    assert rows[1]["age_regime_stage"] == "jeju_4"
    assert rows[1]["age_pre_peak_months"] == pytest.approx(6.0)
    assert rows[1]["rest_cycle_bin"] == "d14_20"
    assert rows[1]["young_short_cycle"] == 1

    assert rows[2]["age_regime_stage"] == "seoul_busan_3"
    assert rows[2]["rest_cycle_bin"] == "debut"
    assert rows[2]["rest_log_days"] is None
    assert rows[2]["senior_long_layoff"] is None


def test_lifecycle_specs_match_output() -> None:
    names = {spec.name for spec in FEATURES}
    frame = pl.DataFrame(
        {
            "horse_age_months": [42.0],
            "meet_code": [1],
            "days_since_last_race": [28],
        }
    )
    result = add_features(frame, SourceFrames())
    assert names <= set(result.columns)
