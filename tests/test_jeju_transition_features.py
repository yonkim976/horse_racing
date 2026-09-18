from datetime import date, timedelta

import numpy as np
import pytest

from horse_racing.analysis.jeju_transition_features import BASIC, FEATURES, build_features, values


def sample():
    target = dict(
        entry_id=3,
        horse_id="1",
        event_date=date(2025, 5, 3),
        declared_grade_number=5,
        distance_m=1000,
        declared_burden_kg=55,
        rival_early_pressure_count=4,
    )
    previous = dict(
        entry_id=1,
        horse_id="1",
        event_date=date(2025, 4, 3),
        grade=6,
        distance_m=900,
        burden_kg=51,
        field_size=10,
        finish_position=1,
        outcome_status="normal_completed",
        rival_early_pressure_count=2,
    )
    return target, previous


def test_transition_and_products():
    t, p = sample()
    v = values(t, p)
    assert len(v) == 13 and len(BASIC) == 6
    assert v["transition_grade_change"] == -1 and v["transition_6to5"] == 1
    assert v["transition_finish_x_burden"] == 4
    assert v["transition_win_x_burden"] == 4
    assert v["transition_finish_x_distance100"] == 1
    assert v["transition_finish_x_pressure"] == 2


def test_cross_year_masks_grade_not_distance_or_prior_form():
    t, p = sample()
    p["event_date"] = date(2024, 12, 1)
    v = values(t, p)
    assert all(np.isnan(v[k]) for k in BASIC[:4])
    assert np.isnan(v["transition_up_x_finish"])
    assert v["transition_finish_x_burden"] == 4


def test_unknown_grade_and_bad_finish_remain_missing():
    t, p = sample()
    p["grade"] = "OPEN"
    p["outcome_status"] = "did_not_finish"
    v = values(t, p)
    assert np.isnan(v["transition_grade_up"])
    assert np.isnan(v["transition_previous_finish_quality"])
    assert np.isnan(v["transition_win_x_burden"])
    assert all(np.isnan(x) for x in values(t, None).values())


def test_current_outcome_invariance_and_future_history_exclusion():
    t, p = sample()
    future = dict(p, entry_id=2, event_date=t["event_date"] - timedelta(days=1), grade=1)
    first, line = build_features([t], [p, future])
    t.update(finish_position=10, body_weight_kg=999, g1f_seconds=1, grade=1)
    second, _ = build_features([t], [p, future])
    assert first == second and line[0]["previous_entry_id"] == 1
    assert set(first[0]) == {"entry_id", *FEATURES}


def test_exact_cutoff_and_missing_pressure_product():
    t, p = sample()
    p["event_date"] = t["event_date"] - timedelta(days=2)
    p["rival_early_pressure_count"] = None
    row, line = build_features([t], [p])
    assert line[0]["previous_entry_id"] == 1
    assert np.isnan(row[0]["transition_finish_x_pressure"])
    p["horse_id"] = "other"
    with pytest.raises(AssertionError):
        values(t, p)
