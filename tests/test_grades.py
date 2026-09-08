"""Parse every distinct ``races.grade`` value observed in the local SQLite DB.

Counts below are from ``SELECT grade, COUNT(*) FROM races GROUP BY grade``
on 2026-08-26 (4,145 completed races; 0 NULL / empty grades).
"""

from __future__ import annotations

import pytest

from horse_racing.analysis.grades import ParsedGrade, parse_race_grade

# (raw, mix, tier, is_open, db_count)
KNOWN_GRADES: list[tuple[str, str | None, int | None, bool, int]] = [
    ("국6등급", "국산", 6, False, 784),
    ("국5등급", "국산", 5, False, 768),
    ("혼4등급", "혼합", 4, False, 434),
    ("제5등급", "제주", 5, False, 409),
    ("국4등급", "국산", 4, False, 297),
    ("제4등급", "제주", 4, False, 281),
    ("혼3등급", "혼합", 3, False, 228),
    ("제6등급", "제주", 6, False, 222),
    ("제3등급", "제주", 3, False, 161),
    ("2등급", None, 2, False, 144),
    ("국3등급", "국산", 3, False, 140),
    ("제2등급", "제주", 2, False, 78),
    ("1등급", None, 1, False, 70),
    ("제1등급", "제주", 1, False, 40),
    ("혼OPEN", "혼합", None, True, 39),
    ("국OPEN", "국산", None, True, 37),
    ("제OPEN", "제주", None, True, 13),
]


@pytest.mark.parametrize(
    ("raw", "mix", "tier", "is_open"),
    [(raw, mix, tier, is_open) for raw, mix, tier, is_open, _count in KNOWN_GRADES],
)
def test_parse_every_observed_grade(
    raw: str, mix: str | None, tier: int | None, is_open: bool
) -> None:
    parsed = parse_race_grade(raw)
    assert parsed == ParsedGrade(raw=raw, mix=mix, tier=tier, is_open=is_open)


def test_known_grades_cover_all_observed_labels() -> None:
    labels = [raw for raw, *_rest in KNOWN_GRADES]
    assert len(labels) == 17
    assert len(set(labels)) == 17
    assert sum(count for *_rest, count in KNOWN_GRADES) == 4145


def test_null_and_blank_grades_are_safe() -> None:
    assert parse_race_grade(None) == ParsedGrade(
        raw=None, mix=None, tier=None, is_open=False
    )
    assert parse_race_grade("") == ParsedGrade(raw="", mix=None, tier=None, is_open=False)
    assert parse_race_grade("   ") == ParsedGrade(
        raw="   ", mix=None, tier=None, is_open=False
    )
    assert parse_race_grade("\t\n") == ParsedGrade(
        raw="\t\n", mix=None, tier=None, is_open=False
    )


def test_bare_open_has_no_mix_class() -> None:
    """Bare OPEN is not in the DB, but follows the same grammar as ``1등급``."""
    assert parse_race_grade("OPEN") == ParsedGrade(
        raw="OPEN", mix=None, tier=None, is_open=True
    )


def test_unknown_patterns_do_not_raise() -> None:
    for raw in ("외4등급", "국", "4등급OPEN", "국 6등급", "abc"):
        parsed = parse_race_grade(raw)
        assert parsed == ParsedGrade(raw=raw, mix=None, tier=None, is_open=False)


@pytest.mark.parametrize(
    ("raw", "mix", "tier", "is_open"),
    [
        ("국6", "국산", 6, False),
        ("제OPEN 핸디캡", "제주", None, True),
        ("한4등급별정A", "한라", 4, False),
        ("한오픈 마령", "한라", None, True),
    ],
)
def test_historical_grade_variants(
    raw: str, mix: str | None, tier: int | None, is_open: bool
) -> None:
    parsed = parse_race_grade(raw)
    assert parsed == ParsedGrade(raw=raw, mix=mix, tier=tier, is_open=is_open)


def test_whitespace_around_known_grade_is_parsed() -> None:
    parsed = parse_race_grade("  국6등급  ")
    assert parsed.mix == "국산"
    assert parsed.tier == 6
    assert parsed.is_open is False
    assert parsed.raw == "  국6등급  "
