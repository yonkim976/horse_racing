from datetime import date, timedelta

import numpy as np

from horse_racing.analysis.jeju_rebound_features import (
    FEATURES,
    adjusted_history,
    build_features,
)


def history_race(day, rid=1, distance=900, elo_other=1500):
    return [
        dict(
            entry_id=rid * 10 + i,
            race_id=rid,
            event_date=day,
            horse_id=str(i),
            distance_m=distance,
            field_size=3,
            finish_position=i,
            global_elo_pre=1500 if i == 1 else elo_other,
            track_moisture_percent=4,
            closing_speed_quality=(3 - i) / 2,
            time_minus_race_median_ms=(i - 2) * 1000,
        )
        for i in [1, 2, 3]
    ]


def target(day):
    return dict(entry_id=999, event_date=day, horse_id="1", distance_m=900)


def test_opponent_strength_changes_surprise_for_same_finish():
    weak = adjusted_history(history_race(date(2025, 1, 1), elo_other=1100))[0]["surprise"]
    strong = adjusted_history(history_race(date(2025, 1, 1), elo_other=1900))[0]["surprise"]
    assert 0 < weak < strong < 1


def test_ties_are_half_wins_and_dnf_has_no_surprise():
    rows = history_race(date(2025, 1, 1))
    rows[1]["finish_position"] = 1
    rows[2]["finish_position"] = None
    x = adjusted_history(rows)
    assert x[0]["surprise"] == 0 and x[1]["surprise"] == 0
    assert x[2]["surprise"] is None


def test_distance_cutoff_and_current_target_weather_do_not_leak():
    day = date(2025, 2, 1)
    h = history_race(day - timedelta(days=3))
    before, lineage = build_features([target(day)], h)
    h += history_race(day, 2) + history_race(day - timedelta(days=5), 3, distance=1000)
    t = target(day)
    t["track_moisture_percent"] = 99
    t["finish_position"] = 3
    after, _ = build_features([t], h)
    np.testing.assert_allclose(
        [before[0][f] for f in FEATURES], [after[0][f] for f in FEATURES], equal_nan=True
    )
    assert lineage[0]["max_history_date"] == day - timedelta(days=3)


def test_small_sample_shrink_and_unknown_wet_not_zero_performance():
    day = date(2025, 2, 1)
    rows, _ = build_features([target(day)], history_race(day - timedelta(days=3)))
    r = rows[0]
    assert r["distance_surprise_mean3"] == 0.5 / 4
    assert r["distance_valid_count6"] == 1
    assert r["wet_distance_count6"] == 0 and np.isnan(r["wet_distance_surprise_mean6"])
    assert np.isnan(r["distance_surprise_trend3v3"])


def test_trend_uses_two_complete_same_distance_windows():
    day = date(2025, 3, 1)
    h = []
    for i in range(6):
        rows = history_race(day - timedelta(days=10 - i), i + 1)
        if i < 3:
            rows[0]["finish_position"] = 3
            rows[2]["finish_position"] = 1
        h += rows
    features, _ = build_features([target(day)], h)
    assert features[0]["distance_surprise_trend3v3"] == 0.5
    assert features[0]["distance_valid_count6"] == 6
