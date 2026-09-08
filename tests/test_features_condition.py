from datetime import date, timedelta
from math import sqrt

import polars as pl

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.condition import FEATURES, GROUP, add_features

RACE_DATE = date(2026, 8, 22)


def _days_before(days: int) -> date:
    return RACE_DATE - timedelta(days=days)


def _frame(**overrides: object) -> pl.DataFrame:
    data: dict[str, object] = {
        "race_id": [1],
        "race_entry_id": [106],
        "horse_id": [10],
        "meet_code": [1],
        "race_date": [RACE_DATE],
        "race_number": [5],
        "starters": [10],
        "body_weight_kg": [530],
        "body_weight_change_kg": [2],
    }
    data.update(overrides)
    return pl.DataFrame(data)


def test_feature_specs_cover_e_f_g_names() -> None:
    assert GROUP == "E~G. 체중·훈련·건강"
    names = [spec.name for spec in FEATURES]
    assert names == [
        "body_weight_prev_avg5",
        "body_weight_std5",
        "body_weight_dev",
        "train_n_3d",
        "train_n_7d",
        "train_n_14d",
        "train_n_28d",
        "train_dur_28d",
        "gallop_n_28d",
        "canter_n_28d",
        "days_since_training",
        "start_train_n_28d",
        "medical_n_14d",
        "medical_n_30d",
        "medical_n_60d",
        "days_since_medical",
        "bleeding_count_prior",
        "equipment_present",
        "equipment_changed",
    ]


def test_training_and_medical_windows_exclude_race_day() -> None:
    """당일 이벤트는 제외하고, 윈도우 경계(<=N일)만 포함한다."""
    training = pl.DataFrame(
        {
            "horse_id": [10] * 8,
            "event_date": [
                RACE_DATE,  # 당일 → 제외
                _days_before(1),  # 3/7/14/28
                _days_before(3),  # 3/7/14/28
                _days_before(4),  # 7/14/28
                _days_before(14),  # 14/28
                _days_before(15),  # 28
                _days_before(28),  # 28
                _days_before(29),  # 제외
            ],
            "duration_seconds": [999, 100, 200, 300, 400, 500, 600, 700],
            "canter_count": [9, 1, 2, 3, 4, 5, 6, 7],
            "gallop_count": [90, 10, 20, 30, 40, 50, 60, 70],
        }
    )
    start_training = pl.DataFrame(
        {
            "horse_id": [10, 10, 10],
            "event_date": [RACE_DATE, _days_before(28), _days_before(29)],
        }
    )
    medical = pl.DataFrame(
        {
            "horse_id": [10] * 6,
            "event_date": [
                RACE_DATE,  # 당일 → 제외
                _days_before(14),
                _days_before(15),
                _days_before(30),
                _days_before(31),
                _days_before(60),
            ],
            "diagnosis_1": ["a"] * 6,
        }
    )
    result = add_features(
        _frame(),
        SourceFrames(
            training=training,
            start_training=start_training,
            medical=medical,
        ),
    )
    row = result.row(0, named=True)

    assert row["train_n_3d"] == 2  # 1d, 3d
    assert row["train_n_7d"] == 3  # + 4d
    assert row["train_n_14d"] == 4  # + 14d
    assert row["train_n_28d"] == 6  # + 15d, 28d (29d·당일 제외)
    assert row["train_dur_28d"] == 100 + 200 + 300 + 400 + 500 + 600
    assert row["gallop_n_28d"] == 10 + 20 + 30 + 40 + 50 + 60
    assert row["canter_n_28d"] == 1 + 2 + 3 + 4 + 5 + 6
    assert row["days_since_training"] == 1
    assert row["start_train_n_28d"] == 1

    assert row["medical_n_14d"] == 1
    assert row["medical_n_30d"] == 3  # 14d, 15d, 30d
    assert row["medical_n_60d"] == 5  # + 31d, 60d (당일 제외)
    assert row["days_since_medical"] == 14


def test_body_weight_rolling_excludes_current_race() -> None:
    past = pl.DataFrame(
        {
            "horse_id": [10] * 6,
            "race_entry_id": [101, 102, 103, 104, 105, 106],
            "race_date": [
                date(2026, 7, 1),
                date(2026, 7, 15),
                date(2026, 8, 1),
                date(2026, 8, 10),
                date(2026, 8, 20),
                RACE_DATE,
            ],
            "body_weight_kg": [480, 490, 500, 510, 520, 530],
            "finish_position": [1] * 6,
            "starters": [10] * 6,
        }
    )
    result = add_features(_frame(), SourceFrames(past_results=past))
    row = result.row(0, named=True)

    # 현재 530을 넣으면 평균 510이 되므로, shift(1)이 빠지면 이 assertion이 실패한다.
    assert row["body_weight_prev_avg5"] == 500.0
    assert abs(row["body_weight_std5"] - sqrt(250.0)) < 1e-9
    assert row["body_weight_dev"] == 30.0


def test_body_weight_dev_skipped_when_frame_lacks_current_weight() -> None:
    past = pl.DataFrame(
        {
            "horse_id": [10, 10],
            "race_entry_id": [105, 106],
            "race_date": [date(2026, 8, 20), RACE_DATE],
            "body_weight_kg": [520, 530],
        }
    )
    frame = _frame().drop("body_weight_kg", "body_weight_change_kg")
    result = add_features(frame, SourceFrames(past_results=past))

    assert "body_weight_dev" not in result.columns
    assert result.get_column("body_weight_prev_avg5").to_list() == [520.0]
    assert result.get_column("body_weight_std5").to_list() == [None]
    assert result.height == 1


def test_equipment_changed_uses_strictly_prior_race() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1, 2, 3],
            "race_entry_id": [201, 202, 203, 204],
            "horse_id": [10, 11, 12, 13],
            "meet_code": [1, 1, 1, 1],
            "race_date": [RACE_DATE] * 4,
            "race_number": [5, 5, 5, 5],
            "starters": [10] * 4,
            "body_weight_kg": [500, 500, 500, 500],
        }
    )
    equipment = pl.DataFrame(
        {
            "horse_id": [10, 10, 10, 10, 11, 11, 12, 13, 13],
            "race_date": [
                date(2026, 7, 1),  # 10: 더 오래된 이력
                date(2026, 8, 1),  # 10: 직전 (날짜 엄격 이전)
                RACE_DATE,  # 10: 같은 날 다른 경주 — 직전으로 쓰지 않음
                RACE_DATE,  # 10: 현재
                date(2026, 8, 1),  # 11: 직전과 동일
                RACE_DATE,  # 11: 현재
                RACE_DATE,  # 12: 현재만 (직전 없음)
                date(2026, 8, 1),  # 13: 직전만 (현재 행 없음)
                RACE_DATE,  # 13: 같은 날 다른 경주
            ],
            "race_number": [1, 11, 1, 5, 3, 5, 5, 2, 1],
            "equipment_raw": [
                "old",
                "blinker",
                "hood",  # 같은 날. 직전으로 쓰면 changed=0이 되어 실패
                "hood",
                "blinker",
                "blinker",
                "hood",
                "blinker",
                "same-day",
            ],
            "bleeding_count": [1, 2, 9, 3, 0, 1, 4, 5, 6],
            "bleeding_date_raw": [None] * 9,
        }
    )
    result = add_features(frame, SourceFrames(equipment=equipment)).sort("horse_id")
    rows = result.to_dicts()

    horse10, horse11, horse12, horse13 = rows
    assert horse10["bleeding_count_prior"] == 3
    assert horse10["equipment_present"] == 1
    assert horse10["equipment_changed"] == 1  # blinker → hood

    assert horse11["bleeding_count_prior"] == 1
    assert horse11["equipment_present"] == 1
    assert horse11["equipment_changed"] == 0  # blinker → blinker

    assert horse12["bleeding_count_prior"] == 4
    assert horse12["equipment_present"] == 1
    assert horse12["equipment_changed"] is None  # 직전 없음

    assert horse13["bleeding_count_prior"] is None
    assert horse13["equipment_present"] == 0
    assert horse13["equipment_changed"] is None  # 현재 행 없음. 같은 날 race 1은 직전 아님
