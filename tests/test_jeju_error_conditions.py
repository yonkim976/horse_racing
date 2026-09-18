import pytest

from horse_racing.analysis.jeju_error_conditions import (
    changed,
    closing_quality,
    delta,
    flags,
    rank_quality,
    valid_rank,
)


def test_invalid_rank_and_field_do_not_become_ability():
    assert valid_rank(0, 10) is None
    assert valid_rank(94, 10) is None
    assert valid_rank(2.5, 10) is None
    assert rank_quality(1, 1) is None
    assert rank_quality(1, 10) == 1
    assert rank_quality(10, 10) == 0


def test_closing_quality_ties_exclude_self():
    assert closing_quality(15, [15, 15, 16]) == 0.75
    assert closing_quality(16, [15, 15, 16]) == 0
    assert closing_quality(15, [15]) is None
    assert closing_quality(14, [15, 16]) is None


def test_missing_is_unknown_not_zero_or_change():
    assert delta(None, 3) is None
    assert delta(float("nan"), 3) is None
    assert changed(None, "A") is None
    assert changed(" A ", "A") == 0
    assert all(v is None for v in flags({}).values())


def test_direction_and_boundary():
    f = flags(
        {
            "pre_burden_change_kg": -1,
            "post_closing_vs_history": -0.25,
            "post_early_to_finish_gain": -3,
            "post_bodyweight_change_kg": -10,
        }
    )
    assert f["pre_burden_down_1kg"] == 1
    assert f["post_closing_worsened_025"] == 1
    assert f["post_closing_improved_025"] == 0
    assert f["post_lost_3places_from_early"] == 1
    assert f["post_bodyweight_abs_change_10kg"] == 1
    assert delta(54, 55) == -1
    assert rank_quality(3, 10) == pytest.approx(7 / 9)


def test_grade_parser_does_not_turn_open_into_a_grade():
    from scripts.diagnose_jeju_grade_transitions import grade

    assert grade("제6등급") == 6
    assert grade("제5등급") == 5
    assert grade("제OPEN") is None
    assert grade(None) is None
    assert grade("한5등급") is None
