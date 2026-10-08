import pytest

from horse_racing.web.distance_benchmarks import build_distance_benchmark_view
from horse_racing.web.formatting import format_distance_seconds, format_race_time


def test_reference_values_and_sample_counts_are_preserved_without_pooling():
    seoul = build_distance_benchmark_view(
        meet_code=1, grade="국5등급", band="건조"
    )
    assert seoul is not None
    assert seoul["grade_supported"] is True
    finish = next(row for row in seoul["detail_rows"] if row["part"] == "finish")
    assert (finish["p20"], finish["median"], finish["middle60_mean"], finish["p80"]) == (
        "1:15.09",
        "1:16.10",
        "1:16.06",
        "1:17.10",
    )
    assert finish["estimate_mean"] == "1:16.18"
    assert finish["observed_mean"] == "1:16.29"

    busan = build_distance_benchmark_view(
        meet_code=3, grade="국6등급", band="건조"
    )
    assert busan is not None
    early = next(row for row in busan["detail_rows"] if row["part"] == "early")
    assert early["estimate_middle60_n"] == 1132
    assert early["middle60_n"] == 641
    assert early["estimate_fast20_n"] == 522
    assert early["fast20_n"] == 382


def test_grade_and_moisture_comparisons_are_separate_and_sections_are_available():
    all_grades = build_distance_benchmark_view(meet_code=1, grade="", band="포화")
    assert all_grades is not None
    assert len(all_grades["summary_rows"]) == 10
    assert all(row["band"] == "포화" for row in all_grades["summary_rows"])
    assert all(row["part"] == "finish" for row in all_grades["summary_rows"])

    selected_grade = build_distance_benchmark_view(
        meet_code=1, grade="국5등급", band="불량"
    )
    assert selected_grade is not None
    assert [row["band"] for row in selected_grade["state_finish_rows"]] == [
        "건조",
        "양호",
        "다습",
        "포화",
        "불량",
    ]
    parts = {row["part"] for row in selected_grade["detail_rows"]}
    assert {"finish", "early", "middle1", "middle2", "late", "last600"} <= parts
    assert "last400" not in parts


def test_unsupported_grades_and_missing_recent_observations_are_explicit():
    unsupported = build_distance_benchmark_view(
        meet_code=1, grade="국2등급", band="건조"
    )
    assert unsupported is not None
    assert unsupported["grade_supported"] is False
    assert unsupported["detail_rows"] == []

    no_recent = build_distance_benchmark_view(
        meet_code=3, grade="국3등급", band="포화"
    )
    assert no_recent is not None
    early = next(row for row in no_recent["detail_rows"] if row["part"] == "early")
    assert early["status"] == "no_recent_observation"
    assert early["observed_n"] == 0
    assert early["p20"] != "—"
    assert early["status_label"] == "관측 없음 · 추정 기준"


def test_benchmark_view_rejects_invalid_band_and_ignores_other_venues():
    assert build_distance_benchmark_view(meet_code=2, grade="", band="건조") is None
    with pytest.raises(ValueError, match="unsupported moisture band"):
        build_distance_benchmark_view(meet_code=1, grade="", band="비")


def test_distance_time_rounds_before_splitting_minutes():
    assert format_distance_seconds(13.6) == "13.60"
    assert format_distance_seconds(59.994) == "59.99"
    assert format_distance_seconds(59.999) == "1:00.00"
    assert format_distance_seconds(60) == "1:00.00"
    assert format_distance_seconds(75.087368499) == "1:15.09"
    assert format_race_time(75_090) == "1:15.1"
