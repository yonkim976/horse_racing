"""Strict, provenance-aware normalization of historical section observations.

The raw database rows are never changed.  A value with an unknown ``time_basis``
stays unavailable: numeric magnitude and racecourse are deliberately not used to
guess whether a value is cumulative or closing.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import polars as pl

CANONICAL_SECTION_VERSION = "canonical_sections_v1"
NORMAL_FINISH_MAX = 89
CHECKPOINT_TOLERANCE_MS = 100


def s1f_distance_m(meet_code: int | None, race_distance_m: int | None) -> int | None:
    """Return only officially documented S1F measurement distances."""
    if meet_code == 2 and race_distance_m in {1110, 1610}:
        return 210
    if meet_code in {1, 2, 3} and race_distance_m is not None and race_distance_m >= 200:
        return 200
    return None


def _positive(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _single(rows: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
    matches = [row for row in rows if row.get("section_code") == code]
    # Multiple measurements with the same semantic code are ambiguous even when
    # their numeric values happen to match.
    return matches[0] if len(matches) == 1 else None


def _canonical_pair(
    row: dict[str, Any] | None,
    finish_ms: int | None,
) -> tuple[int | None, int | None, str | None]:
    """Return (cumulative, closing, evidence), accepting explicit basis only."""
    if row is None:
        return None, None, None
    raw = _positive(row.get("elapsed_time_ms"))
    basis = row.get("time_basis")
    source = row.get("source_kind")
    if raw is None or basis not in {"cumulative", "closing"}:
        return None, None, None
    evidence = f"{basis}:{source or 'source_unknown'}"
    if basis == "cumulative":
        if finish_ms is None or raw >= finish_ms:
            return None, None, evidence
        return raw, finish_ms - raw, evidence
    if finish_ms is None or raw >= finish_ms:
        return None, None, evidence
    return finish_ms - raw, raw, evidence


def _checkpoint_order_valid(
    first_distance: int,
    first_time: int,
    second_distance: int,
    second_time: int,
) -> bool:
    if first_distance == second_distance:
        return abs(first_time - second_time) <= CHECKPOINT_TOLERANCE_MS
    if first_distance < second_distance:
        return first_time < second_time
    return first_time > second_time


def canonicalize_sections(sections: pl.DataFrame) -> pl.DataFrame:
    """Create one strict canonical observation per historical race entry."""
    required = {
        "horse_id",
        "race_entry_id",
        "race_id",
        "meet_code",
        "race_date",
        "distance_m",
        "section_code",
        "elapsed_time_ms",
        "time_basis",
        "source_kind",
        "finish_position",
        "finish_time_ms",
    }
    if sections.height == 0 or not required <= set(sections.columns):
        return pl.DataFrame()

    groups: dict[object, list[dict[str, Any]]] = defaultdict(list)
    for row in sections.iter_rows(named=True):
        groups[row["race_entry_id"]].append(row)

    output: list[dict[str, Any]] = []
    for race_entry_id, rows in groups.items():
        first = rows[0]
        finish_position = _positive(first.get("finish_position"))
        finish_ms = _positive(first.get("finish_time_ms"))
        normal = finish_position is not None and finish_position <= NORMAL_FINISH_MAX
        if not normal:
            finish_ms = None

        race_distance = _positive(first.get("distance_m"))
        g3_cum, last_600, g3_evidence = _canonical_pair(_single(rows, "G3F"), finish_ms)
        g1_cum, last_200, g1_evidence = _canonical_pair(_single(rows, "G1F"), finish_ms)
        if race_distance is None or race_distance < 600:
            g3_cum = last_600 = None
        if race_distance is None or race_distance < 200:
            g1_cum = last_200 = None
        s1 = _single(rows, "S1F")
        early_ms = None
        early_evidence = None
        early_distance = s1f_distance_m(first.get("meet_code"), race_distance)
        if s1 is not None and s1.get("time_basis") == "cumulative":
            candidate = _positive(s1.get("elapsed_time_ms"))
            if candidate is not None and finish_ms is not None and candidate < finish_ms:
                early_ms = candidate
                early_evidence = f"cumulative:{s1.get('source_kind') or 'source_unknown'}"

        g3_distance = race_distance - 600 if race_distance is not None else None
        g1_distance = race_distance - 200 if race_distance is not None else None
        if (
            early_ms is not None
            and g3_cum is not None
            and early_distance is not None
            and g3_distance is not None
            and not _checkpoint_order_valid(early_distance, early_ms, g3_distance, g3_cum)
        ):
            # At an equal checkpoint neither conflicting observation is preferred.
            if early_distance == g3_distance:
                g3_cum = last_600 = None
            early_ms = None
        if (
            early_ms is not None
            and g1_cum is not None
            and early_distance is not None
            and g1_distance is not None
            and not _checkpoint_order_valid(early_distance, early_ms, g1_distance, g1_cum)
        ):
            early_ms = None
        if (
            g3_cum is not None
            and g1_cum is not None
            and g3_distance is not None
            and g1_distance is not None
            and not _checkpoint_order_valid(g3_distance, g3_cum, g1_distance, g1_cum)
        ):
            g3_cum = last_600 = g1_cum = last_200 = None

        middle_400 = None
        if last_600 is not None and last_200 is not None and last_600 > last_200:
            middle_400 = last_600 - last_200

        output.append(
            {
                "horse_id": first["horse_id"],
                "race_entry_id": race_entry_id,
                "race_id": first["race_id"],
                "meet_code": first["meet_code"],
                "race_date": first["race_date"],
                "distance_m": first["distance_m"],
                "canonical_finish_time_ms": finish_ms,
                "canonical_s1f_ms": early_ms,
                "canonical_s1f_distance_m": early_distance if early_ms is not None else None,
                "canonical_g3f_cumulative_ms": g3_cum,
                "canonical_g1f_cumulative_ms": g1_cum,
                "canonical_last_600_ms": last_600,
                "canonical_last_200_ms": last_200,
                "canonical_middle_400_ms": middle_400,
                "canonical_s1f_evidence": early_evidence,
                "canonical_g3f_evidence": g3_evidence,
                "canonical_g1f_evidence": g1_evidence,
                "canonical_profile_available": int(
                    early_ms is not None and last_600 is not None and last_200 is not None
                ),
            }
        )
    return pl.DataFrame(output, infer_schema_length=None)
