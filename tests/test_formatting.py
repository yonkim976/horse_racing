from datetime import date

from horse_racing.web.formatting import (
    adjacent_dates,
    age_years,
    display_race_title,
    dividend_label,
    format_age,
    format_finish_position,
    format_margin,
    format_rating,
    group_dates_by_month,
    page_window,
)


def test_age_years_matches_completed_birthdays() -> None:
    birth = date(2023, 3, 22)

    assert age_years(birth, date(2026, 6, 14)) == 3
    assert age_years(birth, date(2026, 3, 21)) == 2
    assert age_years(birth, date(2026, 3, 22)) == 3
    assert age_years(None, date(2026, 8, 23)) is None
    assert format_age(birth, date(2026, 6, 14)) == "3세"
    assert format_age(None, date(2026, 8, 23)) == "—"


def test_finish_position_uses_special_labels() -> None:
    assert format_finish_position(1) == ("1위", 1, False)
    assert format_finish_position(94) == ("출전제외", 1094, True)
    assert format_finish_position(99) == ("경주취소", 1099, True)
    assert format_finish_position(94, scratched=True) == ("출전제외", 1094, True)
    assert format_finish_position(None, scratched=True) == ("취소", 2000, True)
    assert format_rating(0) == "—"
    assert format_rating(45) == "45"
    assert display_race_title("국6등급", "일반") == "국6등급"
    assert display_race_title("국6등급", "대통령배") == "대통령배"
    assert format_margin("½") == "½"
    assert format_margin(" - ") == "—"
    assert format_margin(None) == "—"


def test_triple_dividend_labels_match_stored_combination_shape() -> None:
    assert dividend_label("TRI") == "삼쌍승"
    assert dividend_label("TLA") == "삼복승"


def test_date_and_page_helpers() -> None:
    dates = [date(2026, 8, 23), date(2026, 8, 22), date(2026, 7, 26)]
    groups = group_dates_by_month(dates)
    assert [label for label, _ in groups] == ["2026년 8월", "2026년 7월"]
    older, newer = adjacent_dates(dates, date(2026, 8, 22))
    assert older == date(2026, 7, 26)
    assert newer == date(2026, 8, 23)
    assert page_window(1, 1) == [1]
    assert page_window(5, 10) == [1, 0, 3, 4, 5, 6, 7, 0, 10]
