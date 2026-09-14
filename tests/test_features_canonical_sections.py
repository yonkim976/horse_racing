from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.canonical_energy import add_features
from horse_racing.analysis.features.canonical_sections import canonicalize_sections


def _section_rows(
    *,
    race_entry_id: int = 1,
    race_id: int = 1,
    horse_id: int = 10,
    race_date: date = date(2025, 1, 4),
    basis: str | None = "cumulative",
    finish_ms: int | None = 76_600,
    finish_position: int | None = 1,
    distance_m: int = 1200,
) -> list[dict[str, object]]:
    values = {"S1F": 14_000, "G3F": 38_000, "G1F": 63_800}
    if basis == "closing":
        values = {"S1F": 14_000, "G3F": 38_600, "G1F": 12_800}
    return [
        {
            "horse_id": horse_id,
            "race_entry_id": race_entry_id,
            "race_id": race_id,
            "meet_code": 1,
            "race_date": race_date,
            "distance_m": distance_m,
            "section_code": code,
            "elapsed_time_ms": value,
            "time_basis": "cumulative" if code == "S1F" else basis,
            "source_kind": "fixture",
            "finish_position": finish_position,
            "finish_time_ms": finish_ms,
        }
        for code, value in values.items()
    ]


def test_cumulative_and_closing_representations_have_same_canonical_values() -> None:
    cumulative = canonicalize_sections(pl.DataFrame(_section_rows(basis="cumulative")))
    closing = canonicalize_sections(pl.DataFrame(_section_rows(basis="closing")))
    columns = [
        "canonical_s1f_ms",
        "canonical_g3f_cumulative_ms",
        "canonical_g1f_cumulative_ms",
        "canonical_last_600_ms",
        "canonical_last_200_ms",
        "canonical_middle_400_ms",
    ]
    assert cumulative.select(columns).equals(closing.select(columns))
    assert cumulative.select(columns).row(0) == (14_000, 38_000, 63_800, 38_600, 12_800, 25_800)


def test_unknown_negative_difference_duplicate_and_special_result_are_unavailable() -> None:
    unknown = canonicalize_sections(pl.DataFrame(_section_rows(basis=None)))
    assert unknown["canonical_last_600_ms"][0] is None
    assert unknown["canonical_last_200_ms"][0] is None

    missing_finish = canonicalize_sections(pl.DataFrame(_section_rows(finish_ms=None)))
    assert missing_finish["canonical_last_600_ms"][0] is None
    assert missing_finish["canonical_profile_available"][0] == 0

    negative = _section_rows(basis="cumulative")
    next(row for row in negative if row["section_code"] == "G1F")["elapsed_time_ms"] = 80_000
    assert canonicalize_sections(pl.DataFrame(negative))["canonical_last_200_ms"][0] is None

    duplicate = _section_rows(basis="cumulative")
    duplicate.append(dict(duplicate[-1]))
    assert canonicalize_sections(pl.DataFrame(duplicate))["canonical_last_200_ms"][0] is None

    special = canonicalize_sections(pl.DataFrame(_section_rows(finish_position=92)))
    assert special["canonical_finish_time_ms"][0] is None
    assert special["canonical_profile_available"][0] == 0


def test_jeju_special_s1f_distances_are_explicit() -> None:
    rows = _section_rows()
    for row in rows:
        row["meet_code"] = 2
        row["distance_m"] = 1110
    result = canonicalize_sections(pl.DataFrame(rows))
    assert result["canonical_s1f_distance_m"][0] == 210


def test_physical_checkpoint_order_and_race_distance_are_enforced() -> None:
    late_s1f = _section_rows()
    next(row for row in late_s1f if row["section_code"] == "S1F")["elapsed_time_ms"] = 70_000
    late_result = canonicalize_sections(pl.DataFrame(late_s1f))
    assert late_result["canonical_s1f_ms"][0] is None
    assert late_result["canonical_profile_available"][0] == 0

    too_short = canonicalize_sections(pl.DataFrame(_section_rows(distance_m=400)))
    assert too_short["canonical_last_600_ms"][0] is None
    assert too_short["canonical_profile_available"][0] == 0


def test_equal_s1f_and_g3f_checkpoint_allows_source_precision_tolerance() -> None:
    rows = _section_rows(distance_m=800)
    next(row for row in rows if row["section_code"] == "G3F")["elapsed_time_ms"] = 14_100
    result = canonicalize_sections(pl.DataFrame(rows))
    assert result["canonical_s1f_ms"][0] == 14_000
    assert result["canonical_g3f_cumulative_ms"][0] == 14_100
    assert result["canonical_profile_available"][0] == 1

    next(row for row in rows if row["section_code"] == "G3F")["elapsed_time_ms"] = 14_200
    invalid = canonicalize_sections(pl.DataFrame(rows))
    assert invalid["canonical_s1f_ms"][0] is None
    assert invalid["canonical_last_600_ms"][0] is None
    assert invalid["canonical_profile_available"][0] == 0


def _history_sources(include_target: bool = True, include_future: bool = False) -> SourceFrames:
    start = date(2025, 1, 1)
    past_rows = []
    section_rows = []
    for race_id, race_date in ((1, start), (2, start + timedelta(days=7))):
        for index, horse_id in enumerate((10, 20, 30), start=1):
            entry_id = race_id * 10 + index
            past_rows.append(
                {
                    "horse_id": horse_id,
                    "race_id": race_id,
                    "race_entry_id": entry_id,
                    "race_date": race_date,
                    "distance_m": 1200,
                }
            )
            rows = _section_rows(
                race_entry_id=entry_id,
                race_id=race_id,
                horse_id=horse_id,
                race_date=race_date,
                finish_ms=76_000 + index * 500,
            )
            section_rows.extend(rows)
    target_date = start + timedelta(days=14)
    past_rows.append(
        {
            "horse_id": 10,
            "race_id": 3,
            "race_entry_id": 100,
            "race_date": target_date,
            "distance_m": 1200,
        }
    )
    if include_target:
        section_rows.extend(
            _section_rows(
                race_entry_id=100,
                race_id=3,
                horse_id=10,
                race_date=target_date,
                finish_ms=99_000,
            )
        )
    if include_future:
        past_rows.append(
            {
                "horse_id": 10,
                "race_id": 4,
                "race_entry_id": 101,
                "race_date": target_date + timedelta(days=7),
                "distance_m": 1200,
            }
        )
        section_rows.extend(
            _section_rows(
                race_entry_id=101,
                race_id=4,
                horse_id=10,
                race_date=target_date + timedelta(days=7),
                finish_ms=120_000,
            )
        )
    return SourceFrames(
        past_results=pl.DataFrame(past_rows),
        sections=pl.DataFrame(section_rows),
    )


def test_target_and_future_results_do_not_change_target_prerace_features() -> None:
    target = pl.DataFrame(
        [
            {
                "horse_id": 10,
                "race_id": 3,
                "race_entry_id": 100,
                "race_date": date(2025, 1, 15),
                "distance_m": 1200,
            }
        ]
    )
    without_target = add_features(target, _history_sources(include_target=False))
    with_target = add_features(target, _history_sources(include_target=True))
    with_future = add_features(target, _history_sources(include_target=True, include_future=True))
    assert without_target.equals(with_target)
    assert with_target.equals(with_future)
