from datetime import date, timedelta

import polars as pl
import pytest

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.form import FEATURES, GROUP, add_features

_EXPECTED_NAMES = [
    "career_starts",
    "is_debut",
    "finish_pos_last",
    "form_recent3_pct",
    "form_recent5_pct",
    "form_recent5_median_pct",
    "form_recent5_best_pct",
    "top3_rate_recent5",
    "win_rate_career",
    "top3_rate_career",
    "days_since_last_race",
    "long_layoff",
    "speed_avg_mps_3",
    "speed_avg_mps_5",
    "speed_best_mps_5",
    "speed_rel_avg5",
    "speed_rel_median5",
    "speed_rel_best5",
    "distance_change_m",
    "dist_band_starts",
    "dist_band_top3_rate",
    "exact_distance_starts",
    "exact_distance_top3_rate",
    "meet_starts",
    "meet_win_rate",
]


def _ms(distance_m: int, mps: float) -> int:
    return int(round(distance_m * 1000.0 / mps))


def _stored_mps(distance_m: int, mps: float) -> float:
    """finish_time_ms 정수 반올림을 거친 뒤의 실제 m/s."""
    return distance_m / (_ms(distance_m, mps) / 1000.0)


def _pct(position: int, starters: int) -> float:
    if starters <= 1:
        return 0.0
    return (position - 1) / (starters - 1)


def _past_row(
    *,
    horse_id: int,
    entry_id: int,
    race_id: int,
    race_date: date,
    meet_code: int,
    distance_m: int,
    finish_position: int,
    starters: int,
    mps: float,
) -> dict:
    return {
        "horse_id": horse_id,
        "jockey_id": 1,
        "trainer_id": 1,
        "race_entry_id": entry_id,
        "race_id": race_id,
        "meet_code": meet_code,
        "race_date": race_date,
        "distance_m": distance_m,
        "body_weight_kg": 480,
        "finish_position": finish_position,
        "finish_time_ms": _ms(distance_m, mps),
        "starters": starters,
    }


def _frame_from_past(past: pl.DataFrame, *, decoy_position: int = 99) -> pl.DataFrame:
    """데이터셋 행. finish_position/win/top3는 라벨(현재 결과)이라 feature에 쓰면 안 된다."""
    return past.select(
        "race_id",
        "race_entry_id",
        "horse_id",
        "jockey_id",
        "trainer_id",
        "meet_code",
        "race_date",
        "distance_m",
        "starters",
    ).with_columns(
        pl.lit(decoy_position).alias("finish_position"),
        pl.lit(1).alias("win"),
        pl.lit(1).alias("top2"),
        pl.lit(1).alias("top3"),
        pl.lit(1).alias("race_number"),
        pl.lit(50.0).alias("rating"),
        pl.lit(55.0).alias("carried_weight_kg"),
    )


def test_feature_specs_cover_contract_names() -> None:
    names = [spec.name for spec in FEATURES]
    assert names == _EXPECTED_NAMES
    assert GROUP == "C. 말 Form"
    assert all(spec.group == GROUP for spec in FEATURES)
    assert all(spec.leakage_note for spec in FEATURES)


def test_shift_excludes_current_race_result() -> None:
    """현재 경주가 past_results에 있어도 shift(1) 때문에 자기 착순·속도가 feature에 안 들어간다."""
    past = pl.DataFrame(
        [
            _past_row(
                horse_id=1,
                entry_id=101,
                race_id=11,
                race_date=date(2026, 1, 1),
                meet_code=1,
                distance_m=1200,
                finish_position=1,
                starters=10,
                mps=15.0,
            ),
            _past_row(
                horse_id=1,
                entry_id=102,
                race_id=12,
                race_date=date(2026, 1, 15),
                meet_code=1,
                distance_m=1400,
                finish_position=5,
                starters=10,
                mps=15.0,
            ),
            _past_row(
                horse_id=1,
                entry_id=103,
                race_id=13,
                race_date=date(2026, 2, 1),
                meet_code=1,
                distance_m=1200,
                finish_position=3,
                starters=8,
                mps=10.0,  # 서울 대역(12~18) 밖 → 속도 null
            ),
            _past_row(
                horse_id=1,
                entry_id=104,
                race_id=14,
                race_date=date(2026, 6, 1),
                meet_code=3,
                distance_m=1600,
                finish_position=2,
                starters=12,
                mps=16.0,
            ),
        ]
    )
    result = add_features(_frame_from_past(past), SourceFrames(past_results=past)).sort(
        "race_entry_id"
    )
    rows = {row["race_entry_id"]: row for row in result.iter_rows(named=True)}

    debut = rows[101]
    assert debut["career_starts"] == 0
    assert debut["is_debut"] == 1
    assert debut["finish_pos_last"] is None
    assert debut["form_recent3_pct"] is None
    assert debut["form_recent5_pct"] is None
    assert debut["win_rate_career"] is None
    assert debut["top3_rate_career"] is None
    assert debut["days_since_last_race"] is None
    assert debut["long_layoff"] is None
    assert debut["speed_avg_mps_3"] is None
    assert debut["dist_band_starts"] == 0
    assert debut["dist_band_top3_rate"] is None
    assert debut["meet_starts"] == 0
    assert debut["meet_win_rate"] is None

    second = rows[102]
    assert second["career_starts"] == 1
    assert second["is_debut"] == 0
    assert second["finish_pos_last"] == 1
    assert second["form_recent3_pct"] == pytest.approx(_pct(1, 10))
    assert second["win_rate_career"] == pytest.approx(1.0)
    assert second["top3_rate_career"] == pytest.approx(1.0)
    assert second["days_since_last_race"] == 14
    assert second["long_layoff"] == 0
    assert second["speed_avg_mps_3"] == pytest.approx(15.0)
    # 현재 1400, 과거 1200 → |200| 이내. 현재 착순 5는 쓰지 않음
    assert second["dist_band_starts"] == 1
    assert second["dist_band_top3_rate"] == pytest.approx(1.0)
    assert second["meet_starts"] == 1
    assert second["meet_win_rate"] == pytest.approx(1.0)

    third = rows[103]
    assert third["career_starts"] == 2
    assert third["finish_pos_last"] == 5  # 현재 착순 3이 아님
    assert third["form_recent3_pct"] == pytest.approx((_pct(1, 10) + _pct(5, 10)) / 2)
    assert third["win_rate_career"] == pytest.approx(0.5)
    assert third["top3_rate_career"] == pytest.approx(0.5)
    assert third["days_since_last_race"] == 17
    assert third["speed_avg_mps_3"] == pytest.approx(
        (_stored_mps(1200, 15.0) + _stored_mps(1400, 15.0)) / 2
    )
    assert third["dist_band_starts"] == 2
    assert third["dist_band_top3_rate"] == pytest.approx(0.5)

    last = rows[104]
    assert last["career_starts"] == 3
    assert last["is_debut"] == 0
    assert last["finish_pos_last"] == 3  # 현재 착순 2가 아님 → 현재 경주 제외 증명
    expected_form3 = (_pct(1, 10) + _pct(5, 10) + _pct(3, 8)) / 3
    assert last["form_recent3_pct"] == pytest.approx(expected_form3)
    assert last["form_recent5_pct"] == pytest.approx(expected_form3)
    assert last["win_rate_career"] == pytest.approx(1 / 3)
    assert last["top3_rate_career"] == pytest.approx(2 / 3)
    assert last["days_since_last_race"] == 120
    assert last["long_layoff"] == 1
    # 과거 속도 15, 15, null(필터). 현재 16 m/s는 평균·최고에 들어가면 안 됨
    past_speeds = [_stored_mps(1200, 15.0), _stored_mps(1400, 15.0)]
    assert last["speed_avg_mps_3"] == pytest.approx(sum(past_speeds) / 2)
    assert last["speed_avg_mps_5"] == pytest.approx(sum(past_speeds) / 2)
    assert last["speed_best_mps_5"] == pytest.approx(max(past_speeds))
    # 1600 기준 ±200: 1400만 포함 (1200 두 번은 제외). 그 경주 착순 5 → top3=0
    assert last["dist_band_starts"] == 1
    assert last["dist_band_top3_rate"] == pytest.approx(0.0)
    assert last["meet_starts"] == 0  # 과거는 서울만, 현재는 부산
    assert last["meet_win_rate"] is None


def test_time_order_future_race_does_not_leak() -> None:
    """나중 경주의 좋은 착순이 앞 경주 feature에 스며들면 안 된다."""
    past = pl.DataFrame(
        [
            _past_row(
                horse_id=3,
                entry_id=301,
                race_id=31,
                race_date=date(2026, 3, 1),
                meet_code=1,
                distance_m=1200,
                finish_position=8,
                starters=8,
                mps=14.0,
            ),
            _past_row(
                horse_id=3,
                entry_id=302,
                race_id=32,
                race_date=date(2026, 4, 1),
                meet_code=1,
                distance_m=1200,
                finish_position=1,
                starters=8,
                mps=16.0,
            ),
        ]
    )
    result = add_features(_frame_from_past(past), SourceFrames(past_results=past)).sort(
        "race_entry_id"
    )
    early, later = result.rows(named=True)

    assert early["career_starts"] == 0
    assert early["win_rate_career"] is None
    assert early["finish_pos_last"] is None
    assert early["form_recent3_pct"] is None
    assert early["speed_best_mps_5"] is None
    assert early["dist_band_starts"] == 0

    assert later["career_starts"] == 1
    assert later["finish_pos_last"] == 8
    assert later["win_rate_career"] == pytest.approx(0.0)
    assert later["top3_rate_career"] == pytest.approx(0.0)
    assert later["form_recent3_pct"] == pytest.approx(_pct(8, 8))
    assert later["speed_avg_mps_3"] == pytest.approx(_stored_mps(1200, 14.0))
    assert later["speed_best_mps_5"] == pytest.approx(_stored_mps(1200, 14.0))  # 현재 16 제외
    assert later["days_since_last_race"] == 31
    assert later["long_layoff"] == 0


def test_percentile_solo_starter_is_zero() -> None:
    past = pl.DataFrame(
        [
            _past_row(
                horse_id=4,
                entry_id=401,
                race_id=41,
                race_date=date(2026, 1, 1),
                meet_code=1,
                distance_m=1200,
                finish_position=1,
                starters=1,
                mps=15.0,
            ),
            _past_row(
                horse_id=4,
                entry_id=402,
                race_id=42,
                race_date=date(2026, 1, 20),
                meet_code=1,
                distance_m=1200,
                finish_position=2,
                starters=5,
                mps=15.0,
            ),
        ]
    )
    result = add_features(_frame_from_past(past), SourceFrames(past_results=past)).sort(
        "race_entry_id"
    )
    later = result.row(1, named=True)
    assert later["form_recent3_pct"] == pytest.approx(0.0)
    assert later["form_recent5_pct"] == pytest.approx(0.0)


def test_form_recent5_uses_five_races_not_three() -> None:
    rows = []
    positions = [1, 5, 8, 2, 6, 3]
    starters = 9
    for index, position in enumerate(positions):
        rows.append(
            _past_row(
                horse_id=5,
                entry_id=500 + index,
                race_id=50 + index,
                race_date=date(2026, 1, 1) + timedelta(days=index * 7),
                meet_code=1,
                distance_m=1200,
                finish_position=position,
                starters=starters,
                mps=15.0,
            )
        )
    past = pl.DataFrame(rows)
    current = add_features(_frame_from_past(past), SourceFrames(past_results=past)).row(
        -1, named=True
    )
    past_pcts = [_pct(pos, starters) for pos in positions[:-1]]
    assert current["career_starts"] == 5
    assert current["form_recent3_pct"] == pytest.approx(sum(past_pcts[-3:]) / 3)
    assert current["form_recent5_pct"] == pytest.approx(sum(past_pcts[-5:]) / 5)
    assert current["form_recent3_pct"] != pytest.approx(current["form_recent5_pct"])


def test_speed_filter_by_meet_band() -> None:
    """서울 11 m/s는 버리고 제주 11.5 m/s는 남긴다. 현재 경주 15 m/s는 평균에 안 넣는다."""
    past = pl.DataFrame(
        [
            _past_row(
                horse_id=10,
                entry_id=1001,
                race_id=101,
                race_date=date(2026, 1, 1),
                meet_code=1,
                distance_m=1200,
                finish_position=4,
                starters=10,
                mps=11.0,  # 서울 하한 미달
            ),
            _past_row(
                horse_id=10,
                entry_id=1002,
                race_id=102,
                race_date=date(2026, 1, 10),
                meet_code=2,
                distance_m=1000,
                finish_position=2,
                starters=10,
                mps=11.5,  # 제주 대역 안
            ),
            _past_row(
                horse_id=10,
                entry_id=1003,
                race_id=103,
                race_date=date(2026, 1, 15),
                meet_code=2,
                distance_m=1000,
                finish_position=3,
                starters=10,
                mps=14.0,  # 제주 상한 초과
            ),
            _past_row(
                horse_id=10,
                entry_id=1004,
                race_id=104,
                race_date=date(2026, 1, 20),
                meet_code=3,
                distance_m=1200,
                finish_position=1,
                starters=10,
                mps=18.5,  # 부산 상한 초과
            ),
            _past_row(
                horse_id=10,
                entry_id=1005,
                race_id=105,
                race_date=date(2026, 2, 1),
                meet_code=1,
                distance_m=1200,
                finish_position=1,
                starters=10,
                mps=15.0,  # 현재. 유효하지만 집계에서 제외되어야 함
            ),
        ]
    )
    current = add_features(_frame_from_past(past), SourceFrames(past_results=past)).row(
        -1, named=True
    )
    assert current["career_starts"] == 4
    jeju_mps = _stored_mps(1000, 11.5)
    assert current["speed_avg_mps_3"] == pytest.approx(jeju_mps)
    assert current["speed_avg_mps_5"] == pytest.approx(jeju_mps)
    assert current["speed_best_mps_5"] == pytest.approx(jeju_mps)


def test_long_layoff_threshold_is_strictly_over_90_days() -> None:
    past = pl.DataFrame(
        [
            _past_row(
                horse_id=6,
                entry_id=601,
                race_id=61,
                race_date=date(2026, 1, 1),
                meet_code=1,
                distance_m=1200,
                finish_position=4,
                starters=8,
                mps=15.0,
            ),
            _past_row(
                horse_id=6,
                entry_id=602,
                race_id=62,
                race_date=date(2026, 4, 1),  # 정확히 90일
                meet_code=1,
                distance_m=1200,
                finish_position=3,
                starters=8,
                mps=15.0,
            ),
            _past_row(
                horse_id=6,
                entry_id=603,
                race_id=63,
                race_date=date(2026, 7, 1),  # 91일
                meet_code=1,
                distance_m=1200,
                finish_position=2,
                starters=8,
                mps=15.0,
            ),
        ]
    )
    result = add_features(_frame_from_past(past), SourceFrames(past_results=past)).sort(
        "race_entry_id"
    )
    assert result.row(1, named=True)["days_since_last_race"] == 90
    assert result.row(1, named=True)["long_layoff"] == 0
    assert result.row(2, named=True)["days_since_last_race"] == 91
    assert result.row(2, named=True)["long_layoff"] == 1


def test_empty_past_results_marks_every_row_as_debut() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1],
            "race_entry_id": [9],
            "horse_id": [7],
            "jockey_id": [1],
            "trainer_id": [1],
            "meet_code": [1],
            "race_date": [date(2026, 8, 1)],
            "distance_m": [1200],
            "starters": [10],
            "finish_position": [1],
            "win": [1],
            "top3": [1],
        }
    )
    result = add_features(frame, SourceFrames())
    row = result.row(0, named=True)
    assert row["career_starts"] == 0
    assert row["is_debut"] == 1
    assert row["win_rate_career"] is None
    assert row["dist_band_starts"] == 0
    assert row["meet_starts"] == 0
    for name in _EXPECTED_NAMES:
        assert name in result.columns


def test_dataset_label_columns_are_not_used() -> None:
    """frame의 finish_position·win·top3가 1이어도 과거 착순 5를 써야 한다."""
    past = pl.DataFrame(
        [
            _past_row(
                horse_id=8,
                entry_id=801,
                race_id=81,
                race_date=date(2026, 1, 1),
                meet_code=1,
                distance_m=1200,
                finish_position=5,
                starters=10,
                mps=15.0,
            ),
            _past_row(
                horse_id=8,
                entry_id=802,
                race_id=82,
                race_date=date(2026, 1, 15),
                meet_code=1,
                distance_m=1200,
                finish_position=1,
                starters=10,
                mps=15.0,
            ),
        ]
    )
    frame = _frame_from_past(past, decoy_position=1)
    current = add_features(frame, SourceFrames(past_results=past)).row(1, named=True)
    assert current["finish_pos_last"] == 5
    assert current["win_rate_career"] == pytest.approx(0.0)
    assert current["form_recent3_pct"] == pytest.approx(_pct(5, 10))
