from horse_racing.web.insights import (
    WIN_LABELS,
    assign_win_labels,
    summarize_top3_field,
)


def labels_for(
    *percents: float | None,
    scratched: tuple[bool, ...] | None = None,
) -> list[str | None]:
    flags = scratched or tuple(False for _ in percents)
    assigned = assign_win_labels(
        [
            (index, None if value is None else value / 100, flags[index])
            for index, value in enumerate(percents)
        ]
    )
    return [assigned.get(index) for index in range(len(percents))]


def test_win_labels_cover_only_the_v1_terms():
    assert WIN_LABELS == (
        "강축",
        "축마",
        "공동축",
        "축 후보",
        "혼전권",
        "상대마",
        "후착후보",
        "입상후보",
        "후순위",
    )
    assigned = assign_win_labels(
        [
            (1, 0.40, False),
            (2, 0.18, False),
            (3, 0.12, False),
            (4, 0.08, False),
            (5, 0.07, False),
            (6, 0.05, False),
        ]
    )
    assert set(assigned.values()) <= set(WIN_LABELS)


def test_strong_axis_has_two_opponents_and_two_place_candidates():
    assert labels_for(80, 60, 50, 40, 30, 20, 10) == [
        "강축",
        "상대마",
        "상대마",
        "후착후보",
        "후착후보",
        "후순위",
        "후순위",
    ]


def test_joint_axis_uses_two_axes_and_three_place_candidates():
    assert labels_for(62, 60, 48, 42, 38, 20) == [
        "공동축",
        "공동축",
        "후착후보",
        "후착후보",
        "후착후보",
        "후순위",
    ]


def test_mixed_field_has_four_mixed_runners_and_one_candidate():
    assert labels_for(48, 41, 38, 36, 27, 20, 10) == [
        "혼전권",
        "혼전권",
        "혼전권",
        "혼전권",
        "입상후보",
        "후순위",
        "후순위",
    ]


def test_mixed_field_expands_to_six_when_fifth_and_sixth_are_indistinguishable():
    assert labels_for(48, 36, 35, 33, 29.4, 28.9, 23, 18) == [
        "혼전권",
        "혼전권",
        "혼전권",
        "혼전권",
        "입상후보",
        "입상후보",
        "후순위",
        "후순위",
    ]

    summary = summarize_top3_field(
        [
            (index, value / 100, False)
            for index, value in enumerate((48, 36, 35, 33, 29.4, 28.9, 23, 18))
        ]
    )
    assert summary.race_state == "혼전"
    assert summary.candidate_count == 6
    assert summary.prediction_count == 8
    assert summary.ranks == {index: index + 1 for index in range(8)}


def test_place_scramble_expands_to_six_even_with_an_axis():
    assert labels_for(63.2, 33.2, 23.6, 23.5, 23.5, 21.9, 15.9, 14.9) == [
        "축마",
        "상대마",
        "상대마",
        "후착후보",
        "후착후보",
        "후착후보",
        "후순위",
        "후순위",
    ]


def test_axis_and_axis_candidate_thresholds():
    assert labels_for(69, 55, 50, 40, 30, 20) == [
        "축마",
        "상대마",
        "상대마",
        "후착후보",
        "후착후보",
        "후순위",
    ]
    assert labels_for(58, 50, 45, 35, 25, 20) == [
        "축 후보",
        "상대마",
        "상대마",
        "후착후보",
        "후착후보",
        "후순위",
    ]


def test_missing_and_scratched_runners_are_not_labeled():
    assert labels_for(100, None, scratched=(False, True)) == ["강축", None]
    assert labels_for(None, None) == [None, None]

    empty = summarize_top3_field([(1, None, False), (2, 0.8, True)])
    assert empty.race_state is None
    assert empty.candidate_count == 0
    assert empty.prediction_count == 0
    assert empty.ranks == {}
