from datetime import date

import polars as pl
import pytest

from horse_racing.analysis.jeju_h3_features import (
    RELATIVE_SOURCES,
    add_people_history,
    add_relative,
    parse_card,
)


def test_rating_rows_and_allowance_are_parsed_without_losing_identity():
    rows = parse_card(
        [
            "제목 : 25.01.03 제 1 일 금요일 3경주;",
            " 900 M 출전:10두 제5등급 출발:12:00",
            "마번 마 명 기수 레이팅",
            " 1 출품작 제 암 3 52.5 (-3)임재광 윤덕상 송문관 12",
        ]
    )
    assert len(rows) == 1
    assert rows[0]["rating"] == 12 and rows[0]["grade"] == 5
    assert rows[0]["jockey_name"] == "임재광" and rows[0]["allowance"] == 3


def test_old_promotion_column_is_not_rating_and_header_resets():
    rows = parse_card(
        [
            "제목 : 2018.01.12 금요일 1경주;",
            "800M 출전:12두 3상",
            "마번 마 명 기수 승군순위",
            " 1 고공세상 제 암 4 59.0 김경훈 백인호 강기숙 12",
            "제목 : 2018.01.12 금요일 2경주;",
            " 1 다른말 제 거 4 55.0 김경훈 백인호 강기숙",
        ]
    )
    assert len(rows) == 2
    assert all(x["rating"] is None and x["grade"] is None for x in rows)


def h(day, identity="J1", win=1):
    return {
        "event_date": date(2025, 1, day),
        "horse_id": "H1",
        "jockey_name": "기사",
        "jockey_id": identity,
        "trainer_name": "조교",
        "trainer_id": "T1",
        "win": win,
        "top3": win,
    }


def target(day):
    return {
        "entry_id": day,
        "event_date": date(2025, 1, day),
        "horse_id": "H1",
        "jockey_name": "기사",
        "trainer_name": "조교",
    }


def test_people_history_excludes_yesterday_same_day_and_future():
    history = [h(1), h(4), h(5), h(6)]
    r = add_people_history([target(5)], history)[0]
    assert r["jockey_history_starts"] == 1
    assert r["horse_jockey_history_top3_rate"] == pytest.approx(4 / 11)
    assert r == add_people_history([target(5)], history[:1])[0]


def test_future_identity_collision_does_not_change_earlier_mapping():
    hist = [h(1), h(8, "J2")]
    a, b = add_people_history([target(5), target(11)], hist)
    assert a["jockey_identity_history_known"] == 1
    assert b["jockey_identity_history_known"] == 0 and b["jockey_history_starts"] == 0


def test_same_date_and_input_order_do_not_change_states():
    ts = [dict(target(5), entry_id=i) for i in [10, 20]]
    forward = add_people_history(ts, [h(1), h(3)])
    backward = add_people_history(ts[::-1], [h(3), h(1)])
    assert forward == backward


def test_relative_features_are_current_race_only_and_handle_nulls():
    frame = pl.DataFrame({"race_id": [1, 1, 2], **{k: [1.0, 3.0, None] for k in RELATIVE_SOURCES}})
    r = add_relative(frame)
    assert r["global_elo_pre__race_centered"].to_list() == [-1.0, 1.0, None]
    assert r["global_elo_pre__race_percentile"].to_list() == [0.0, 1.0, None]


def test_legacy_chulju_header_preserves_distance():
    rows = parse_card(
        [";TI2003.08.30 토요일 1경주;", "800M 출주:8두", " 1 말이름 제 수 5 55.0 기사 조교 마주"]
    )
    assert rows[0]["distance"] == 800
