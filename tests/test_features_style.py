from datetime import date, timedelta

import polars as pl
import pytest

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.style import (
    FEATURES,
    GROUP,
    add_features,
    attach_early_position_target,
)

_START = date(2026, 1, 3)


def _d(offset_weeks: int) -> date:
    return _START + timedelta(weeks=offset_weeks)


def _past(
    *,
    horse_id: int,
    entry_id: int,
    race_date: date,
    finish_position: int,
    starters: int = 10,
    race_id: int | None = None,
) -> dict:
    return {
        "horse_id": horse_id,
        "race_id": race_id if race_id is not None else entry_id,
        "race_entry_id": entry_id,
        "race_date": race_date,
        "meet_code": 1,
        "distance_m": 1200,
        "finish_position": finish_position,
        "starters": starters,
    }


def _sec(horse_id: int, race_date: date, code: str, position: int) -> dict:
    return {
        "horse_id": horse_id,
        "race_date": race_date,
        "section_code": code,
        "position": position,
        "elapsed_time_ms": 12_000,
    }


def _frame_row(
    *,
    horse_id: int,
    entry_id: int,
    race_date: date,
    finish_position: int = 99,
    win: int = 1,
    starters: int = 10,
) -> dict:
    """데이터셋 행. finish_position·win은 현재 경주 라벨(feature 계산에 쓰면 안 됨)."""
    return {
        "race_id": entry_id,
        "race_entry_id": entry_id,
        "horse_id": horse_id,
        "meet_code": 1,
        "race_date": race_date,
        "distance_m": 1200,
        "starters": starters,
        "finish_position": finish_position,
        "win": win,
    }


def _run(frame: pl.DataFrame, past: list[dict], sections: list[dict]) -> pl.DataFrame:
    return add_features(
        frame,
        SourceFrames(past_results=pl.DataFrame(past), sections=pl.DataFrame(sections)),
    )


def test_feature_registry() -> None:
    assert GROUP == "D. 주행 스타일"
    names = [spec.name for spec in FEATURES]
    assert names == [
        "early_pos_pct_avg5",
        "late_gain_avg5",
        "late_gain_pct_avg5",
        "early_pos_pct_std5",
        "corner4_pos_pct_avg5",
        "pace_fade_avg5",
        "style_category",
        "section_coverage5",
    ]
    assert all(spec.lookback == "최근 5경주" for spec in FEATURES)
    assert all(
        "공백" in spec.null_policy or "없으면" in spec.null_policy or "미만" in spec.null_policy
        for spec in FEATURES
    )


def test_early_position_target_is_training_only_current_race_label() -> None:
    race_date = _d(0)
    past = pl.DataFrame(
        [_past(horse_id=1, entry_id=1, race_date=race_date, finish_position=2)]
    )
    sections = pl.DataFrame([_sec(1, race_date, "S1F", 3)])
    frame = pl.DataFrame([_frame_row(horse_id=1, entry_id=1, race_date=race_date)])
    result = attach_early_position_target(
        frame,
        SourceFrames(past_results=past, sections=sections),
    )

    assert result["early_position_pct_target"].item() == pytest.approx(2 / 9)
    assert "early_position_pct_target" not in [spec.name for spec in FEATURES]


def test_excludes_current_race_sections_and_labels() -> None:
    """직전 1경주만 창에 들어가고, 현재 경주 구간·라벨은 평균을 바꾸지 못한다."""
    past_date, current_date = _d(0), _d(1)
    past = [
        _past(horse_id=1, entry_id=101, race_date=past_date, finish_position=2),
        _past(horse_id=1, entry_id=102, race_date=current_date, finish_position=1),
    ]
    sections = [
        _sec(1, past_date, "S1F", 8),
        _sec(1, past_date, "4C", 5),
        _sec(1, past_date, "G3F", 6),
        _sec(1, past_date, "G1F", 3),
        # 현재 경주: 포함되면 평균이 크게 달라진다
        _sec(1, current_date, "S1F", 1),
        _sec(1, current_date, "4C", 1),
        _sec(1, current_date, "G3F", 1),
        _sec(1, current_date, "G1F", 10),
    ]
    frame = pl.DataFrame(
        [_frame_row(horse_id=1, entry_id=102, race_date=current_date, finish_position=1)]
    )
    row = _run(frame, past, sections).row(0, named=True)

    assert row["early_pos_pct_avg5"] == pytest.approx(0.8)  # 8/10; 현재 1/10이면 0.1
    assert row["late_gain_avg5"] == pytest.approx(6.0)  # 8-2; 현재 라벨 쓰면 8-1 또는 1-1
    assert row["corner4_pos_pct_avg5"] == pytest.approx(0.5)  # 5/10; 현재면 0.1
    assert row["pace_fade_avg5"] == pytest.approx(-3.0)  # 3-6; 현재면 10-1=+9
    assert row["section_coverage5"] == 1
    assert row["style_category"] == "추입"


def test_debut_with_only_current_sections_is_empty() -> None:
    """과거 경주가 없으면 현재 경주 구간이 있어도 coverage=0, 나머지는 null."""
    current_date = _d(0)
    past = [_past(horse_id=1, entry_id=1, race_date=current_date, finish_position=1)]
    sections = [
        _sec(1, current_date, "S1F", 1),
        _sec(1, current_date, "4C", 1),
        _sec(1, current_date, "G3F", 2),
        _sec(1, current_date, "G1F", 1),
    ]
    frame = pl.DataFrame([_frame_row(horse_id=1, entry_id=1, race_date=current_date)])
    row = _run(frame, past, sections).row(0, named=True)
    assert row["early_pos_pct_avg5"] is None
    assert row["late_gain_avg5"] is None
    assert row["corner4_pos_pct_avg5"] is None
    assert row["pace_fade_avg5"] is None
    assert row["style_category"] is None
    assert row["section_coverage5"] == 0


def test_rolling_window_uses_last_five_races_only() -> None:
    """6경주 이력이 있어도 직전 5경주만 사용한다. 두 시점 행이 서로 다른 창을 본다."""
    dates = [_d(i) for i in range(7)]  # 0..5 과거, 6 현재
    past = [
        _past(horse_id=1, entry_id=100 + i, race_date=dates[i], finish_position=i + 1)
        for i in range(7)
    ]
    sections: list[dict] = []
    for i, race_date in enumerate(dates):
        # S1F = i+1 → pct = 0.1, 0.2, ..., 0.7 (현재 0.7은 창에 들어가면 안 됨)
        sections.extend(
            [
                _sec(1, race_date, "S1F", i + 1),
                _sec(1, race_date, "4C", i + 2),
                _sec(1, race_date, "G3F", i + 1),
                _sec(1, race_date, "G1F", i + 3),
            ]
        )

    frame = pl.DataFrame(
        [
            _frame_row(horse_id=1, entry_id=102, race_date=dates[2]),  # 직전: 0,1
            _frame_row(horse_id=1, entry_id=106, race_date=dates[6]),  # 직전: 1..5
        ]
    )
    result = _run(frame, past, sections).sort("race_entry_id")
    early = result.get_column("early_pos_pct_avg5").to_list()
    late = result.get_column("late_gain_avg5").to_list()
    corner = result.get_column("corner4_pos_pct_avg5").to_list()
    fade = result.get_column("pace_fade_avg5").to_list()
    coverage = result.get_column("section_coverage5").to_list()

    # entry 102: races 0,1 → S1F pct 0.1, 0.2
    assert early[0] == pytest.approx(0.15)
    assert late[0] == pytest.approx(0.0)  # (1-1 + 2-2) / 2
    assert corner[0] == pytest.approx((2 / 10 + 3 / 10) / 2)
    assert fade[0] == pytest.approx(2.0)  # G1F-G3F = 2 always here
    assert coverage[0] == 2

    # entry 106: races 1..5 → pct 0.2..0.6 (race 0의 0.1과 현재 0.7 제외)
    assert early[1] == pytest.approx(0.4)
    assert late[1] == pytest.approx(0.0)
    assert corner[1] == pytest.approx((3 + 4 + 5 + 6 + 7) / 10 / 5)
    assert fade[1] == pytest.approx(2.0)
    assert coverage[1] == 5
    assert result.get_column("style_category").to_list() == ["선행", "선입"]


@pytest.mark.parametrize(
    ("s1f", "starters", "expected"),
    [
        (34, 100, "선행"),
        (35, 100, "선입"),
        (54, 100, "선입"),
        (55, 100, "중위"),
        (74, 100, "중위"),
        (75, 100, "추입"),
        (100, 100, "추입"),
    ],
)
def test_style_category_thresholds(s1f: int, starters: int, expected: str) -> None:
    past_date, current_date = _d(0), _d(1)
    past = [
        _past(
            horse_id=1,
            entry_id=1,
            race_date=past_date,
            finish_position=5,
            starters=starters,
        ),
        _past(
            horse_id=1,
            entry_id=2,
            race_date=current_date,
            finish_position=1,
            starters=starters,
        ),
    ]
    sections = [_sec(1, past_date, "S1F", s1f), _sec(1, current_date, "S1F", 1)]
    frame = pl.DataFrame(
        [
            _frame_row(
                horse_id=1,
                entry_id=2,
                race_date=current_date,
                starters=starters,
            )
        ]
    )
    row = _run(frame, past, sections).row(0, named=True)
    assert row["early_pos_pct_avg5"] == pytest.approx(s1f / starters)
    assert row["style_category"] == expected


def test_style_category_null_when_no_s1f_history() -> None:
    past_date, current_date = _d(0), _d(1)
    past = [
        _past(horse_id=1, entry_id=1, race_date=past_date, finish_position=4),
        _past(horse_id=1, entry_id=2, race_date=current_date, finish_position=3),
    ]
    # 과거 경주에 S1F 없음, 현재 경주에만 있음 → 분류 불가
    sections = [_sec(1, current_date, "S1F", 1)]
    frame = pl.DataFrame([_frame_row(horse_id=1, entry_id=2, race_date=current_date)])
    row = _run(frame, past, sections).row(0, named=True)
    assert row["early_pos_pct_avg5"] is None
    assert row["style_category"] is None
    assert row["section_coverage5"] == 0


def test_missing_sections_keep_null_and_coverage_counts_s1f_only() -> None:
    dates = [_d(i) for i in range(6)]
    past = [
        _past(horse_id=1, entry_id=10 + i, race_date=dates[i], finish_position=3)
        for i in range(6)
    ]
    sections = [
        _sec(1, dates[0], "S1F", 4),  # 4C·G* 없음
        _sec(1, dates[1], "S1F", 6),
        _sec(1, dates[1], "G3F", 5),  # G1F 없음 → pace_fade 제외
        _sec(1, dates[2], "4C", 8),  # S1F 없음
        _sec(1, dates[3], "S1F", 2),
        _sec(1, dates[3], "4C", 3),
        _sec(1, dates[3], "G3F", 7),
        _sec(1, dates[3], "G1F", 4),
        # dates[4] 원천 공백일
        _sec(1, dates[5], "S1F", 1),  # 현재 — 사용 금지
        _sec(1, dates[5], "4C", 1),
        _sec(1, dates[5], "G3F", 1),
        _sec(1, dates[5], "G1F", 1),
    ]
    frame = pl.DataFrame([_frame_row(horse_id=1, entry_id=15, race_date=dates[5])])
    row = _run(frame, past, sections).row(0, named=True)

    # 창 = dates[0..4]: S1F 있는 경주 0,1,3 (공백일 4, S1F 없는 2)
    assert row["section_coverage5"] == 3
    assert row["early_pos_pct_avg5"] == pytest.approx((0.4 + 0.6 + 0.2) / 3)
    assert row["late_gain_avg5"] == pytest.approx((4 - 3 + 6 - 3 + 2 - 3) / 3)
    # 4C: dates[2]=8/10, dates[3]=3/10
    assert row["corner4_pos_pct_avg5"] == pytest.approx((0.8 + 0.3) / 2)
    # pace_fade: dates[3]만 G1F·G3F 둘 다 있음 (4-7)
    assert row["pace_fade_avg5"] == pytest.approx(-3.0)
    assert row["style_category"] == "선입"


def test_empty_sources_yield_nulls_and_zero_coverage() -> None:
    frame = pl.DataFrame([_frame_row(horse_id=1, entry_id=1, race_date=_d(0))])
    row = add_features(frame, SourceFrames()).row(0, named=True)
    assert row["early_pos_pct_avg5"] is None
    assert row["late_gain_avg5"] is None
    assert row["corner4_pos_pct_avg5"] is None
    assert row["pace_fade_avg5"] is None
    assert row["style_category"] is None
    assert row["section_coverage5"] == 0


def test_empty_sections_keep_coverage_zero() -> None:
    past_date, current_date = _d(0), _d(1)
    past = [
        _past(horse_id=1, entry_id=1, race_date=past_date, finish_position=4),
        _past(horse_id=1, entry_id=2, race_date=current_date, finish_position=3),
    ]
    frame = pl.DataFrame([_frame_row(horse_id=1, entry_id=2, race_date=current_date)])
    row = _run(frame, past, []).row(0, named=True)
    assert row["early_pos_pct_avg5"] is None
    assert row["corner4_pos_pct_avg5"] is None
    assert row["pace_fade_avg5"] is None
    assert row["late_gain_avg5"] is None
    assert row["style_category"] is None
    assert row["section_coverage5"] == 0
