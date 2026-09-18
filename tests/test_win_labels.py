from horse_racing.web.insights import WIN_LABELS, assign_win_labels


def labels_for(*percents: float | None, scratched: tuple[bool, ...] | None = None) -> list[str | None]:
    flags = scratched or tuple(False for _ in percents)
    assigned = assign_win_labels(
        [
            (index, None if value is None else value / 100, flags[index])
            for index, value in enumerate(percents)
        ]
    )
    return [assigned.get(index) for index in range(len(percents))]


def test_win_labels_cover_only_the_seven_terms():
    assert WIN_LABELS == ("강축", "축", "상대", "복병", "접전", "혼전", "후착혼전")
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


def test_clear_leader_is_strong_axis_with_include_and_challenger():
    assert labels_for(40, 18, 12, 8, 7, 5) == ["강축", "축", "상대", "상대", "복병", "복병"]


def test_close_top_two_or_three_are_dead_heat():
    assert labels_for(28, 26, 8, 6, 4) == ["접전", "접전", "상대", "복병", "복병"]
    assert labels_for(22, 21, 20, 7, 5) == ["접전", "접전", "접전", "복병", "복병"]


def test_bunched_field_is_open_scramble():
    assert labels_for(18, 16, 15, 14, 12, 8, 4) == [
        "혼전",
        "혼전",
        "혼전",
        "혼전",
        "혼전",
        "복병",
        "복병",
    ]


def test_clear_win_with_bunched_place_is_place_scramble():
    assert labels_for(35, 14, 13, 12, 6, 4) == [
        "강축",
        "후착혼전",
        "후착혼전",
        "후착혼전",
        "복병",
        "복병",
    ]


def test_tied_displayed_percents_share_the_same_label():
    assert labels_for(22, 17, 12, 11, 11, 11, 9) == [
        "접전",
        "접전",
        "상대",
        "상대",
        "상대",
        "상대",
        "복병",
    ]
    assert labels_for(100, None, scratched=(False, True)) == ["강축", None]
    assert labels_for(None, None) == [None, None]
