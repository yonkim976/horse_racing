from datetime import date

import numpy as np

from horse_racing.analysis.jeju_context_features import (
    CONTEXT_FEATURES,
    FEATURES,
    FORM_FEATURES,
    build_features,
    parse_body_weight,
)


def _target(entry_id, horse_id, race_id=10):
    return {
        "entry_id": entry_id,
        "race_id": race_id,
        "event_date": date(2025, 1, 10),
        "horse_id": horse_id,
        "horse_number": entry_id,
        "field_size": 2,
        "global_elo_pre": float(entry_id),
        "distance_elo_pre": float(entry_id) / 2,
        "declared_burden_kg": 55.0,
        "jockey_name": "J1" if entry_id == 1 else "J2",
        "weather": "폭우",
        "track_moisture_percent": 99.0,
        "body_weight_kg": 999.0,
        "finish_position": 1,
    }


def _history(entry_id, horse_id, event_date, **updates):
    row = {
        "entry_id": entry_id,
        "race_id": entry_id + 100,
        "event_date": event_date,
        "horse_id": horse_id,
        "field_size": 6,
        "global_elo_pre": 100.0,
        "distance_elo_pre": 90.0,
        "jockey_name": "J1" if horse_id == "h1" else "J2",
        "jockey_id": None,
        "burden_kg": 54.0,
        "body_weight_kg": 260.0,
        "early_rank": 4,
        "late_rank": 2,
        "finish_position": 4,
        "finish_time_ms": 80_000,
        "outcome_status": "normal_completed",
        "weather": "맑음",
        "track_moisture_percent": 3.0,
        "time_minus_race_median_ms": 100.0,
    }
    row.update(updates)
    return row


def test_feature_groups_are_bounded_and_body_weight_parser_is_explicit():
    assert len(CONTEXT_FEATURES) + len(FORM_FEATURES) == len(FEATURES) <= 40
    assert parse_body_weight("264(+2)") == 264.0
    assert parse_body_weight("272(-5)") == 272.0
    assert parse_body_weight("unknown") is None


def test_future_and_same_day_history_cannot_change_target_features():
    targets = [_target(1, "h1"), _target(2, "h2")]
    history = [
        _history(101, "h1", date(2025, 1, 1)),
        _history(102, "h2", date(2025, 1, 1)),
    ]
    baseline = build_features(targets, history)
    perturbed = history + [
        _history(
            999,
            "h1",
            date(2025, 1, 10),
            finish_position=1,
            global_elo_pre=10_000.0,
            early_rank=1,
            late_rank=1,
            weather="폭우",
            track_moisture_percent=100.0,
            body_weight_kg=500.0,
        ),
        _history(
            1000,
            "h1",
            date(2025, 1, 11),
            finish_position=1,
            global_elo_pre=20_000.0,
            early_rank=1,
            late_rank=1,
        ),
    ]
    changed = build_features(targets, perturbed)
    for left, right in zip(baseline, changed, strict=True):
        for name in FEATURES:
            assert (np.isnan(left[name]) and np.isnan(right[name])) or left[name] == right[name]


def test_late_strength_and_progression_keep_dq_without_fake_outcome():
    target = _target(1, "h1")
    history = [
        _history(
            101,
            "h1",
            date(2025, 1, 1),
            early_rank=5,
            late_rank=1,
            finish_position=6,
        ),
        _history(
            102,
            "h1",
            date(2025, 1, 2),
            early_rank=None,
            late_rank=None,
            finish_position=None,
            finish_time_ms=None,
            outcome_status="disqualified",
        ),
    ]
    row = build_features([target], history)[0]
    assert row["last_early_late_gain"] != row["last_early_late_gain"]
    assert row["best_last5_performance"] == 0.0
    assert row["poor_last_but_good_late"] != row["poor_last_but_good_late"]
    assert row["dry_performance_count"] == 1.0


def test_future_identity_changes_do_not_rewrite_old_jockey_history():
    targets = [_target(1, "h1"), _target(2, "h2")]
    past = [_history(11, "h1", date(2025, 1, 1), jockey_id="A", early_rank=1)]
    baseline = build_features(targets, past)
    changed = build_features(
        targets, past + [_history(12, "h1", date(2025, 2, 1), jockey_id="B", early_rank=6)]
    )
    for a, b in zip(baseline, changed, strict=True):
        np.testing.assert_allclose(
            [a[k] for k in FEATURES], [b[k] for k in FEATURES], equal_nan=True
        )


def test_good_closing_speed_is_distinct_from_leading_before_finish():
    target = _target(1, "h1")
    fast = [
        _history(
            11, "h1", date(2025, 1, 1), finish_position=6, late_rank=6, closing_speed_quality=1.0
        )
    ]
    fading = [
        _history(
            11, "h1", date(2025, 1, 1), finish_position=6, late_rank=1, closing_speed_quality=0.0
        )
    ]
    assert build_features([target], fast)[0]["poor_last_but_good_late"] == 1.0
    assert build_features([target], fading)[0]["poor_last_but_good_late"] == 0.0


def test_stronger_opponents_and_declaration_number_pressure():
    t1 = _target(1, "h1")
    t2 = _target(2, "h2")
    t2["horse_number"] = 5
    past = [
        _history(11, "h1", date(2025, 1, 1), rival_elo_mean=1.0),
        _history(12, "h2", date(2025, 1, 1), early_rank=1),
    ]
    result = build_features([t1, t2], past)
    assert result[0]["current_vs_previous_rival_elo"] == 1.0
    assert result[0]["higher_number_early_pressure_count"] == 1.0
    assert result[1]["declared_horse_number_fraction"] == 1.0


def test_feature_definitions_complete_and_no_exact_alias():
    from horse_racing.analysis.jeju_context_features import FEATURE_DEFINITIONS

    assert len(FEATURES) == 40 and len(set(FEATURES)) == 40
    assert set(FEATURE_DEFINITIONS) == set(FEATURES)
    assert "historical_early_front_percentile" not in FEATURES


def test_track_percent_is_observed_not_inferred_from_weather_word():
    from horse_racing.analysis.jeju_context_features import parse_track_moisture

    assert parse_track_moisture("건조 (4%)") == 4.0
    assert parse_track_moisture("포화 (18%)") == 18.0
    assert parse_track_moisture("비") is None
    assert parse_track_moisture("0%") is None
    assert parse_track_moisture(None) is None
