from datetime import date, timedelta

import polars as pl

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.remediation import add_features

RACE_DATE = date(2026, 8, 21)


def test_remediation_features_link_current_jockey_without_same_day_leakage() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1],
            "race_entry_id": [101, 102],
            "horse_id": [10, 11],
            "jockey_id": [200, 201],
            "race_number": [3, 3],
            "race_date": [RACE_DATE, RACE_DATE],
        }
    )
    past = pl.DataFrame(
        {
            "horse_id": [10],
            "race_date": [RACE_DATE - timedelta(days=20)],
            "jockey_id": [100],
            "race_number": [1],
        }
    )
    training = pl.DataFrame(
        {
            "horse_id": [10, 10, 10, 10],
            "rider_jockey_id": [200, 200, 999, 200],
            "event_date": [
                RACE_DATE - timedelta(days=28),
                RACE_DATE - timedelta(days=5),
                RACE_DATE - timedelta(days=2),
                RACE_DATE,
            ],
            "duration_seconds": [600, 900, 1_200, 2_000],
            "gallop_count": [1, 2, 5, 9],
        }
    )
    trials = pl.DataFrame(
        {
            "horse_id": [10, 10],
            "trial_id": [1, 2],
            "event_date": [RACE_DATE - timedelta(days=10), RACE_DATE],
            "trial_race_number": [1, 2],
            "field_size": [8, 8],
            "finish_position": [1, 8],
            "judgement": ["합", "합"],
            "inspection_reason": ["출발불량 주행지정(재)", "주행지정(재)"],
            "jockey_id": [200, 999],
        }
    )
    equipment = pl.DataFrame(
        {
            "horse_id": [10, 10],
            "race_date": [RACE_DATE - timedelta(days=20), RACE_DATE],
            "race_number": [1, 3],
            "equipment_raw": ["계란형큰고리재갈,망사눈가면", "반가지큰고리재갈"],
        }
    )

    rows = add_features(
        frame,
        SourceFrames(
            past_results=past,
            training=training,
            running_trials=trials,
            equipment=equipment,
        ),
    ).sort("horse_id").to_dicts()
    horse10, horse11 = rows

    assert horse10["current_jockey_train_n_28d"] == 2
    assert horse10["current_jockey_train_duration_28d"] == 1_500.0
    assert horse10["current_jockey_train_gallop_28d"] == 3.0
    assert horse10["current_jockey_train_2plus_28d"] == 1
    assert horse10["jockey_changed_from_last_start"] == 1
    assert horse10["remedial_trial_passed_since_start"] == 1
    assert horse10["remedial_trial_winner_since_start"] == 1
    assert horse10["remedial_trial_current_jockey"] == 1
    assert horse10["remedial_trial_current_jockey_winner"] == 1
    assert horse10["remedial_trial_new_jockey_winner"] == 1
    assert horse10["remedial_trial_finish_percentile"] == 0.125
    assert horse10["bit_changed_from_last_start"] == 1
    assert horse10["remedial_trial_bit_changed"] == 1

    assert horse11["current_jockey_train_n_28d"] == 0
    assert horse11["jockey_changed_from_last_start"] is None
    assert horse11["remedial_trial_passed_since_start"] == 0
    assert horse11["remedial_trial_finish_percentile"] is None
    assert horse11["bit_changed_from_last_start"] is None


def test_remedial_trial_before_last_start_is_not_reused() -> None:
    frame = pl.DataFrame(
        {
            "horse_id": [10],
            "jockey_id": [200],
            "race_number": [3],
            "race_date": [RACE_DATE],
        }
    )
    past = pl.DataFrame(
        {
            "horse_id": [10],
            "race_date": [RACE_DATE - timedelta(days=5)],
            "jockey_id": [200],
            "race_number": [2],
        }
    )
    trials = pl.DataFrame(
        {
            "horse_id": [10],
            "trial_id": [1],
            "event_date": [RACE_DATE - timedelta(days=10)],
            "trial_race_number": [1],
            "field_size": [8],
            "finish_position": [1],
            "judgement": ["합"],
            "inspection_reason": ["주행지정(재)"],
            "jockey_id": [200],
        }
    )

    row = add_features(
        frame, SourceFrames(past_results=past, running_trials=trials)
    ).to_dicts()[0]
    assert row["remedial_trial_passed_since_start"] == 0
    assert row["remedial_trial_current_jockey_winner"] == 0

