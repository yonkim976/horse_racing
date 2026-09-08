from datetime import date, timedelta

import polars as pl

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.trials import add_features

RACE_DATE = date(2026, 8, 21)


def _base() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 1],
            "race_entry_id": [101, 102],
            "horse_id": [10, 11],
            "race_date": [RACE_DATE, RACE_DATE],
        }
    )


def test_running_trial_features_use_only_strictly_prior_events() -> None:
    events = pl.DataFrame(
        {
            "horse_id": [10, 10, 10, 10],
            "trial_id": [1, 2, 3, 4],
            "event_date": [
                RACE_DATE - timedelta(days=200),
                RACE_DATE - timedelta(days=90),
                RACE_DATE - timedelta(days=20),
                RACE_DATE,
            ],
            "trial_race_number": [1, 2, 3, 4],
            "distance_m": [1000, 1000, 1000, 1000],
            "field_size": [10, 10, 10, 10],
            "finish_position": [1, 2, 8, 1],
            "finish_time_ms": [61_000, 62_000, 65_000, 59_000],
            "body_weight_kg": [480, 490, 500, 510],
            "judgement": ["합", "합", "불", "합"],
            "inspection_reason": [
                "주행미합(신)",
                "주행미합(신)",
                "장기휴양(재)",
                "주행미합(신)",
            ],
            "g3f_ms": [37_000, 37_500, 39_000, 36_000],
            "s1f_ms": [14_000, 14_100, 15_000, 13_800],
            "g1f_ms": [12_500, 12_700, 14_000, 12_000],
        }
    )

    rows = add_features(_base(), SourceFrames(running_trials=events)).sort("horse_id").to_dicts()
    horse10, horse11 = rows

    assert horse10["trial_n_180d"] == 2
    assert horse10["trial_pass_n_180d"] == 1
    assert horse10["trial_fail_n_180d"] == 1
    assert horse10["days_since_trial"] == 20
    assert horse10["last_trial_passed"] == 0
    assert horse10["last_trial_time_per_100m"] == 6.5
    assert horse10["last_trial_finish_percentile"] == 0.8
    assert horse10["last_trial_s1f_sec"] == 15.0
    assert horse10["last_trial_g3f_sec"] == 39.0
    assert horse10["last_trial_g1f_sec"] == 14.0
    assert horse10["last_trial_body_weight_kg"] == 500.0
    assert horse10["last_trial_newcomer_exam"] == 0

    assert horse11["trial_n_180d"] == 0
    assert horse11["days_since_trial"] is None
    assert horse11["last_trial_passed"] is None


def test_running_trial_features_empty_source_has_stable_schema() -> None:
    result = add_features(_base(), SourceFrames())

    assert result.get_column("trial_n_180d").to_list() == [0, 0]
    assert result.get_column("last_trial_time_per_100m").to_list() == [None, None]
    assert result.get_column("last_trial_newcomer_exam").to_list() == [None, None]
