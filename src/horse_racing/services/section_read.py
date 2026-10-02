"""Read the verified score-sheet sections, with legacy-only point fallback.

The score sheets can store cumulative and closing times for the same point.
This adapter keeps both values on one checkpoint observation. Official
segment durations are read separately so they cannot become passing points.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from horse_racing.db.models import RaceSectionResult, RaceSectionTime


@dataclass(frozen=True, slots=True)
class SectionObservation:
    race_entry_id: int
    section_code: str
    elapsed_time_ms: int | None
    position: int | None
    time_basis: str | None
    source_kind: str | None
    distance_from_start_m: int | None = None
    cumulative_time_ms: int | None = None
    closing_time_ms: int | None = None


def _time_priority(point_code: str, time_kind: str) -> int:
    preferred = ("closing", "cumulative") if point_code in {"G3F", "G1F"} else (
        "cumulative",
        "closing",
    )
    return preferred.index(time_kind) if time_kind in preferred else len(preferred)


def load_section_observations(
    session: Session, entry_ids: Sequence[int]
) -> dict[int, list[SectionObservation]]:
    """Use score-sheet values for matching points, old rows only for uncovered points."""
    if not entry_ids:
        return {}
    ids = sorted(set(entry_ids))
    canonical = []
    legacy = []
    for start in range(0, len(ids), 500):
        batch = ids[start : start + 500]
        canonical.extend(
            session.scalars(
                select(RaceSectionTime).where(
                    RaceSectionTime.race_entry_id.in_(batch),
                    RaceSectionTime.time_kind != "segment",
                )
            ).all()
        )
        legacy.extend(
            session.scalars(
                select(RaceSectionResult).where(RaceSectionResult.race_entry_id.in_(batch))
            ).all()
        )
    by_point: dict[tuple[int, str], list[RaceSectionTime]] = defaultdict(list)
    for row in canonical:
        by_point[(row.race_entry_id, row.point_code)].append(row)
    output: dict[int, list[SectionObservation]] = defaultdict(list)
    for (entry_id, point_code), rows in by_point.items():
        selected = min(
            rows,
            key=lambda row: (
                row.elapsed_time_ms is None,
                _time_priority(point_code, row.time_kind),
            ),
        )
        position_row = next(
            (
                row for row in rows if row.time_kind == "cumulative" and row.position_raw),
            None,
        )
        position = (position_row.position_raw if position_row else None) or next(
            (row.position_raw for row in rows if row.position_raw), None
        )
        output[entry_id].append(
            SectionObservation(
                race_entry_id=entry_id,
                section_code=point_code,
                elapsed_time_ms=selected.elapsed_time_ms,
                position=position,
                time_basis=selected.time_kind,
                source_kind=selected.source_name,
                cumulative_time_ms=next(
                    (
                        row.elapsed_time_ms for row in rows
                        if row.time_kind == "cumulative" and row.elapsed_time_ms is not None
                    ),
                    None,
                ),
                closing_time_ms=next(
                    (
                        row.elapsed_time_ms for row in rows
                        if row.time_kind == "closing" and row.elapsed_time_ms is not None
                    ),
                    None,
                ),
            )
        )
    for row in legacy:
        if row.time_basis == "segment":
            continue
        if (row.race_entry_id, row.section_code) in by_point:
            continue
        output[row.race_entry_id].append(
            SectionObservation(
                race_entry_id=row.race_entry_id,
                section_code=row.section_code,
                elapsed_time_ms=row.elapsed_time_ms,
                position=row.position,
                time_basis=row.time_basis,
                source_kind=row.source_kind,
                distance_from_start_m=row.distance_from_start_m,
                cumulative_time_ms=row.elapsed_time_ms if row.time_basis == "cumulative" else None,
                closing_time_ms=row.elapsed_time_ms if row.time_basis == "closing" else None,
            )
        )
    return output


def load_official_segment_times(
    session: Session, entry_ids: Sequence[int]
) -> dict[int, dict[str, int]]:
    """Keep score-sheet interval durations separate from checkpoint times."""
    output: dict[int, dict[str, int]] = defaultdict(dict)
    ids = sorted(set(entry_ids))
    for start in range(0, len(ids), 500):
        rows = session.scalars(
            select(RaceSectionTime).where(
                RaceSectionTime.race_entry_id.in_(ids[start : start + 500]),
                RaceSectionTime.time_kind == "segment",
            )
        )
        for row in rows:
            if row.elapsed_time_ms is not None:
                output[row.race_entry_id][row.point_code] = row.elapsed_time_ms
    return output
