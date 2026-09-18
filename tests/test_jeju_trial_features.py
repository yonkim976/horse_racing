from datetime import date, timedelta

import numpy as np

from horse_racing.analysis.jeju_trial_features import build_features, section_value


def trial(i, day, finish=70000, s1=18000, g1=17000):
    sections = {}
    for code, value, point, basis in [
        ("S1F", s1, 200, "cumulative"),
        ("G1F", g1, 600, "closing"),
        ("G3F", 52000, 200, "closing"),
    ]:
        sections[code] = dict(
            source_value_ms=value,
            elapsed_from_start_ms=value if basis == "cumulative" else finish - value,
            distance_from_start_m=point,
            time_basis=basis,
            distance_is_approximate=0,
        )
    return dict(
        entry_id=i,
        horse_id="1",
        event_date=day,
        distance_m=800,
        record_status="normal_completed",
        segment_quality="usable",
        finish_time_ms=finish,
        sections=sections,
    )


def target(day):
    return dict(entry_id=100, horse_id="1", event_date=day, finish_position=1)


def test_cutoff_and_future_outcome_invariance():
    day = date(2025, 1, 10)
    t = target(day)
    a = trial(1, day - timedelta(days=2))
    future = trial(2, day - timedelta(days=1), s1=1000)
    rows, lin = build_features([t], [a, future])
    assert rows[0]["trial800_s1f_ms_mean3_365"] == 18000 and lin[0]["latest3_valid_ids"] == [1]
    t["finish_position"] = 9
    future["sections"]["S1F"]["source_value_ms"] = 50000
    other, _ = build_features([t], [a, future])
    np.testing.assert_equal(list(rows[0].values()), list(other[0].values()))


def test_window_and_recency_distinct():
    day = date(2025, 1, 10)
    rows, lin = build_features(
        [target(day)], [trial(1, day - timedelta(days=366)), trial(2, day - timedelta(days=365))]
    )
    assert rows[0]["trial800_valid_count365"] == 1
    assert rows[0]["trial800_days_since_last_valid"] == 365
    assert lin[0]["valid365_ids"] == [2]


def test_nonstarter_different_distance_and_id_excluded():
    day = date(2025, 1, 10)
    a = trial(1, day - timedelta(days=3))
    a["record_status"] = "non_positive_result_entry"
    b = trial(2, day - timedelta(days=4))
    b["distance_m"] = 900
    c = trial(3, day - timedelta(days=5))
    c["horse_id"] = "2"
    rows, _ = build_features([target(day)], [a, b, c])
    r = rows[0]
    assert r["trial800_valid_count365"] == 0 and r["trial800_days_since_last_attempt"] == 3
    assert np.isnan(r["trial800_s1f_ms_mean3_365"])


def test_section_semantics_and_geometry():
    a = trial(1, date(2025, 1, 1))
    assert section_value(a, "G1F") == 17000
    a["sections"]["G1F"]["time_basis"] = "cumulative"
    assert section_value(a, "G1F") is None
    a = trial(1, date(2025, 1, 1))
    a["sections"]["S1F"]["distance_from_start_m"] = 210
    assert section_value(a, "S1F") is None
    a = trial(1, date(2025, 1, 1))
    a["sections"]["G1F"]["elapsed_from_start_ms"] = 1
    assert section_value(a, "G1F") is None


def test_changes_last_two_and_no_skip_missing():
    day = date(2025, 1, 10)
    a = trial(1, day - timedelta(days=5))
    b = trial(2, day - timedelta(days=4), finish=69000, g1=16000)
    rows, _ = build_features([target(day)], [a, b])
    r = rows[0]
    assert (
        r["trial800_finish_change_last2_365"] == -1000
        and r["trial800_g1f_change_last2_365"] == -1000
    )
    assert r["trial800_complete_section_count3_365"] == 2
    b["sections"].pop("G1F")
    rows, _ = build_features([target(day)], [a, b])
    assert np.isnan(rows[0]["trial800_g1f_change_last2_365"])


def test_absence_is_missing_not_zero_time():
    rows, _ = build_features([target(date(2025, 1, 10))], [])
    assert rows[0]["trial800_valid_count365"] == 0
    assert rows[0]["trial800_complete_section_count3_365"] == 0
    assert np.isnan(rows[0]["trial800_g1f_ms_mean3_365"])
