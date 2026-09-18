from datetime import date

from horse_racing.analysis.jeju_history_audit import (
    classify_missing,
    historical_rows,
    reconstruct_sections,
)


def row(i, day, early=2, closing=0.7, horse="1"):
    return dict(
        entry_id=i,
        event_date=date(2025, 1, day),
        horse_id=horse,
        early_rank=early,
        field_size=10,
        closing_speed_quality=closing,
    )


def test_cutoff_identity_and_current_outcome_exclusion():
    target = dict(event_date=date(2025, 1, 10), horse_id="1", finish_position=1)
    history = [row(4, 10), row(2, 8), row(3, 9), row(1, 7), row(5, 6, horse="2")]
    assert [r["entry_id"] for r in historical_rows(target, history)] == [1, 2]
    target["finish_position"] = 9
    assert [r["entry_id"] for r in historical_rows(target, history)] == [1, 2]


def test_recent_three_starts_not_recent_three_valid():
    history = [
        row(1, 1, closing=0.9),
        row(2, 2, closing=None),
        row(3, 3, closing=None),
        row(4, 4, closing=None),
    ]
    summary = reconstruct_sections(history)
    assert summary["closing_speed_quality_mean_3"] is None
    assert summary["historical_early_front_rate"] == 1


def test_missing_without_history_and_nonstarter_attribution():
    saved = {"historical_early_front_rate": float("nan"), "closing_speed_quality_mean_3": None}
    assert classify_missing([], [], saved)["reason"] == "no_prior_race_row_in_available_sources"
    assert (
        classify_missing([], [{"finish_position": 94}], saved)["reason"]
        == "only_prior_nonstarter_rows"
    )
    assert (
        classify_missing([], [{"finish_position": 1}], saved)["reason"]
        == "prior_source_race_excluded_requires_review"
    )


def test_feature_mismatch_not_silently_imputed():
    result = classify_missing([row(1, 1)], [], {})
    assert not result["features_match"] and result["reason"] == "feature_reconstruction_mismatch"


def test_rank_bounds_and_partial_valid_mean():
    summary = reconstruct_sections(
        [
            row(1, 1, early=0, closing=None),
            row(2, 2, early=11, closing=0.3),
            row(3, 3, early=3, closing=0.7),
        ]
    )
    assert summary["valid_early_count"] == 1 and summary["historical_early_front_rate"] == 1
    assert abs(summary["closing_speed_quality_mean_3"] - 0.5) < 1e-12
