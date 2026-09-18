"""Immutable 제주 native top-three target extraction.

This module owns the small, result-side contract used by the top-three model.
It deliberately does not build features or fit a model.  The database is
opened through SQLite's read-only URI and only named columns are selected from
the result tables.  ``accepted_orders`` contains compatible ordered triples
under official competition ranks; it does not manufacture negative
permutations.

The public ``build_top3_labels`` function is also useful for independent label
adapter tests and for callers which already have an extracted entry frame.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

EXPECTED_DB_SHA256 = "0f2871c2a8f931bb968d8bf7086c27f0644c0ef7332b41b7a1bd85ff637c638f"
KST = ZoneInfo("Asia/Seoul")
OFFICIAL_LINK_STATUS = "official_race_ids_linked"
RACE_POPULATION = "confirmed_native_normal_race"
NORMAL_MAX_RANK = 89
STARTED_SPECIAL_CODES = {91: "disqualified", 92: "dnf"}
NONSTART_CODES = {93, 94, 95}
QUARANTINE_CODES = {98, 99}
_HORSE_ID = re.compile(r"^[0-9]{7}$")


class DatasetContractError(ValueError):
    """Raised when the immutable extraction cannot satisfy the data contract."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cutoff(event_date: date) -> datetime:
    return datetime.combine(event_date - timedelta(days=1), time(18), tzinfo=KST)


def _split(event_date: date) -> str:
    if event_date < date(2018, 8, 31):
        return "history_burnin"
    if event_date <= date(2024, 12, 31):
        return "train"
    if event_date <= date(2025, 12, 27):
        return "development"
    if event_date <= date(2025, 12, 31):
        return "bridge"
    return "frozen_historical"


def _as_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y%m%d").date()


def _status(code: int | None) -> str:
    if code is None:
        return "unknown"
    if 1 <= code <= NORMAL_MAX_RANK:
        return "normal_completed"
    if code in STARTED_SPECIAL_CODES:
        return STARTED_SPECIAL_CODES[code]
    if code in NONSTART_CODES:
        return "nonstarter"
    if code in QUARANTINE_CODES:
        return "quarantined"
    return "unknown"


def _is_started(code: int | None) -> bool:
    return (code is not None and 1 <= code <= NORMAL_MAX_RANK) or code in STARTED_SPECIAL_CODES


def _rank_is_strict(ranks: Iterable[int]) -> bool:
    """Validate 1,2,2,4 style competition ranks without renumbering."""
    values = sorted(int(value) for value in ranks)
    if not values:
        return False
    expected = 1
    for rank in sorted(set(values)):
        if rank != expected:
            return False
        expected += values.count(rank)
    return True


def _top3_rank_is_strict(ranks: Iterable[int]) -> bool:
    """Validate competition ranks only through the third-place boundary.

    A source gap below third place (for example ``1,2,3,5``) is retained in
    ``rank_validation`` but cannot change a top-three label.  Gaps before the
    boundary (``1,2,4``) remain invalid.  This preserves the raw anomaly and
    avoids inventing a replacement rank.
    """
    values = sorted(int(value) for value in ranks)
    if len(values) < 3:
        return False
    expected = 1
    consumed = 0
    for rank in sorted(set(values)):
        if consumed >= 3:
            break
        if rank != expected:
            return False
        count = values.count(rank)
        consumed += min(count, 3 - consumed)
        expected += count
    return consumed >= 3


def _rank_groups(rows: Iterable[Mapping[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        position = row.get("finish_position")
        if position is not None and 1 <= int(position) <= NORMAL_MAX_RANK:
            groups[int(position)].append(dict(row))
    return [
        sorted(groups[key], key=lambda item: (str(item["horse_id"]), int(item["horse_number"])))
        for key in sorted(groups)
    ]


def _compatible_triples(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[tuple[dict[str, Any], ...]], bool]:
    """Return every order allowed by rank ties, preserving a boundary tie."""
    groups = _rank_groups(rows)
    if sum(len(group) for group in groups) < 3:
        return [], False
    top3_tie = False
    options: list[list[tuple[dict[str, Any], ...]]] = []
    remaining = 3
    for group in groups:
        if remaining <= 0:
            break
        if len(group) > 1:
            top3_tie = True
        if len(group) <= remaining:
            options.append(list(itertools.permutations(group)))
            remaining -= len(group)
            continue
        # The rank group crosses the 3rd-place boundary.  Select a subset and
        # let all its internal orders remain possible.
        top3_tie = True
        selected: list[tuple[dict[str, Any], ...]] = []
        for subset in itertools.combinations(group, remaining):
            selected.extend(itertools.permutations(subset))
        options.append(selected)
        remaining = 0
    if remaining:
        return [], top3_tie
    triples = [
        tuple(item for part in parts for item in part) for parts in itertools.product(*options)
    ]
    # Group sorting and horse IDs are deterministic; this also protects the
    # table against an accidental duplicate from a malformed source row.
    unique: dict[tuple[str, str, str], tuple[dict[str, Any], ...]] = {}
    for triple in triples:
        key = tuple(str(item["horse_id"]) for item in triple)
        unique[key] = triple
    return [unique[key] for key in sorted(unique)], top3_tie


def _empty_frames() -> dict[str, pl.DataFrame]:
    return {
        "entries": pl.DataFrame(),
        "labels": pl.DataFrame(),
        "races": pl.DataFrame(),
        "history_results": pl.DataFrame(),
        "exclusions": pl.DataFrame(),
        "accepted_orders": pl.DataFrame(),
        "accepted_sets": pl.DataFrame(),
    }


def _required_columns(frame: pl.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise DatasetContractError(f"{name} missing columns: {', '.join(missing)}")


def build_top3_labels(entries: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """Build labels and compatible top-three tables from an entry frame.

    The input must contain one row per kept starter and the result columns
    ``finish_position`` and ``finish_time_ms``.  ``race_id`` is the grouping
    key; horse IDs are never inferred from names or renumbered positions.
    """
    _required_columns(
        entries,
        {"race_id", "entry_id", "horse_id", "horse_number", "finish_position", "finish_time_ms"},
        "entries",
    )
    if entries.is_empty():
        empty_labels = pl.DataFrame()
        return {
            "labels": empty_labels,
            "accepted_orders": empty_labels,
            "accepted_sets": empty_labels,
        }

    input_rows = entries.to_dicts()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in input_rows:
        grouped[int(row["race_id"])].append(row)
    label_rows: list[dict[str, Any]] = []
    order_rows: list[dict[str, Any]] = []
    set_rows: list[dict[str, Any]] = []

    for race_id in sorted(grouped):
        rows = grouped[race_id]
        normal = [
            row
            for row in rows
            if row.get("finish_position") is not None
            and 1 <= int(row["finish_position"]) <= NORMAL_MAX_RANK
        ]
        strict = len(normal) >= 3 and _top3_rank_is_strict(
            int(row["finish_position"]) for row in normal
        )
        triples, boundary_tie = _compatible_triples(rows) if strict else ([], False)
        target_eligible = bool(strict and triples)
        set_keys: set[str] = set()
        for triple in triples:
            ids = tuple(str(item["horse_id"]) for item in triple)
            numbers = tuple(int(item["horse_number"]) for item in triple)
            order_key = ">".join(ids)
            set_key = "-".join(sorted(ids))
            set_keys.add(set_key)
            order_rows.append(
                {
                    "race_id": race_id,
                    "first_horse_id": ids[0],
                    "second_horse_id": ids[1],
                    "third_horse_id": ids[2],
                    "first_horse_number": numbers[0],
                    "second_horse_number": numbers[1],
                    "third_horse_number": numbers[2],
                    "order_key": order_key,
                    "selection_key": order_key,
                    "set_key": set_key,
                    "tie_case": bool(
                        boundary_tie or len({item["finish_position"] for item in triple}) < 3
                    ),
                    "singleton": len(triples) == 1,
                }
            )
        for set_key in sorted(set_keys):
            set_ids = tuple(set_key.split("-"))
            set_rows.append(
                {
                    "race_id": race_id,
                    "horse_ids": json.dumps(set_ids, ensure_ascii=False),
                    "set_key": set_key,
                    "set_size": len(set_ids),
                    "tie_case": bool(boundary_tie),
                    "singleton": len(set_keys) == 1,
                }
            )
        for row in rows:
            code = row.get("finish_position")
            normal_row = code is not None and 1 <= int(code) <= NORMAL_MAX_RANK
            status = _status(int(code) if code is not None else None)
            label_rows.append(
                {
                    "race_id": race_id,
                    "entry_id": int(row["entry_id"]),
                    "horse_id": str(row["horse_id"]),
                    "horse_number": int(row["horse_number"]),
                    "finish_position_raw": int(code) if code is not None else None,
                    "finish_time_ms_raw": int(row["finish_time_ms"])
                    if row.get("finish_time_ms") is not None
                    else None,
                    "finish_position": int(code) if normal_row else None,
                    "finish_time_ms": int(row["finish_time_ms"])
                    if normal_row and row.get("finish_time_ms") is not None
                    else None,
                    "finish_position_target": int(code) if normal_row else None,
                    "finish_time_ms_target": int(row["finish_time_ms"])
                    if normal_row and row.get("finish_time_ms") is not None
                    else None,
                    "outcome_status": status,
                    "rank_observed": bool(normal_row),
                    "time_observed": bool(normal_row and (row.get("finish_time_ms") or 0) > 0),
                    "rank_mask": bool(normal_row),
                    "time_mask": bool(normal_row and (row.get("finish_time_ms") or 0) > 0),
                    "label_win": int(normal_row and int(code) == 1),
                    "label_top3": int(normal_row and int(code) <= 3),
                    "top3_target_eligible": target_eligible,
                    "top3_candidate_tie": bool(boundary_tie),
                    "accepted_set_count": len(set_keys),
                    "accepted_order_count": len(triples),
                    "full_rank_target_mask": bool(
                        normal_row
                        and row.get(
                            "full_rank_valid",
                            _rank_is_strict(item["finish_position"] for item in normal),
                        )
                    ),
                }
            )

    # Add race-level fields to labels only when the source frame carries them;
    # the minimal hand-written adapter remains useful without those columns.
    labels = pl.DataFrame(label_rows, infer_schema_length=None)
    if "event_date" in entries.columns:
        dates = entries.select("race_id", "event_date").unique("race_id", keep="first")
        labels = labels.join(dates, on="race_id", how="left", validate="m:1")
    return {
        "labels": labels,
        "accepted_orders": pl.DataFrame(order_rows, infer_schema_length=None)
        if order_rows
        else pl.DataFrame(schema={"race_id": pl.Int64, "order_key": pl.String}),
        "accepted_sets": pl.DataFrame(set_rows, infer_schema_length=None)
        if set_rows
        else pl.DataFrame(schema={"race_id": pl.Int64, "set_key": pl.String}),
    }


def extract_dataset(db_path: Path) -> dict[str, pl.DataFrame]:
    """Extract immutable entries, labels, history, exclusions and top-three keys."""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise DatasetContractError(f"database not found: {db_path}")
    observed_hash = _sha256_file(db_path)
    if observed_hash != EXPECTED_DB_SHA256:
        raise DatasetContractError(f"database SHA-256 mismatch: {observed_hash}")

    uri = f"file:{db_path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        source_rows = connection.execute(
            """
            SELECT ev.id AS race_id, ev.event_date, ev.event_number, ev.distance_m,
                   ev.population_status, ent.id AS entry_id, ent.horse_number,
                   ent.hr_no AS horse_id, ent.finish_position, ent.finish_time_ms,
                   ent.segment_quality, ent.record_status, ent.identity_status,
                   ent.source_row_id, sr.row_sha256 AS source_row_hash
            FROM event AS ev
            JOIN entry AS ent ON ent.event_id = ev.id
            LEFT JOIN source_row AS sr ON sr.id = ent.source_row_id
            WHERE ev.event_type = 'race'
              AND ev.population_status = :population
            ORDER BY ev.event_date, ev.event_number, ent.horse_number, ent.id
            """,
            {"population": RACE_POPULATION},
        ).fetchall()
        quarantined_races = connection.execute(
            """
            SELECT id AS race_id, event_date, distance_m, population_status
            FROM event
            WHERE event_type = 'race' AND population_status != :population
            ORDER BY event_date, event_number, id
            """,
            {"population": RACE_POPULATION},
        ).fetchall()
    finally:
        connection.close()
    if not source_rows:
        raise DatasetContractError("confirmed native race population is empty")

    raw: list[dict[str, Any]] = []
    for source in source_rows:
        row = dict(source)
        if row["horse_id"] is None or not _HORSE_ID.fullmatch(str(row["horse_id"])):
            raise DatasetContractError(
                f"official 7-digit horse ID missing for entry {row['entry_id']}"
            )
        row["horse_id"] = str(row["horse_id"])
        row["event_date"] = _as_date(row["event_date"])
        row["finish_position"] = (
            int(row["finish_position"]) if row["finish_position"] is not None else None
        )
        row["finish_time_ms"] = (
            int(row["finish_time_ms"]) if row["finish_time_ms"] is not None else None
        )
        row["status"] = _status(row["finish_position"])
        raw.append(row)

    by_race: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        by_race[int(row["race_id"])].append(row)
    exclusions: list[dict[str, Any]] = []
    race_info: list[dict[str, Any]] = []
    complete_races: set[int] = set()
    rank_invalid_races: set[int] = set()
    for race_id, rows in by_race.items():
        first = rows[0]
        started = [row for row in rows if _is_started(row["finish_position"])]
        reasons: list[str] = []
        unresolved_started = [
            row for row in started if row["identity_status"] != OFFICIAL_LINK_STATUS
        ]
        if unresolved_started:
            reasons.append("unresolved_started_identity")
        if any(row["status"] in {"unknown", "quarantined"} for row in rows):
            reasons.append("unknown_or_quarantined_result_status")
        if len({row["horse_number"] for row in rows}) != len(rows):
            reasons.append("duplicate_horse_number")
        if len({row["horse_id"] for row in started}) != len(started):
            reasons.append("duplicate_started_horse_id")
        if reasons:
            for reason in reasons:
                exclusions.append(
                    {
                        "scope": "race",
                        "race_id": race_id,
                        "entry_id": None,
                        "event_date": first["event_date"],
                        "distance_m": first["distance_m"],
                        "reason_code": reason,
                        "action": "excluded",
                        "detail": None,
                    }
                )
            for row in unresolved_started:
                exclusions.append(
                    {
                        "scope": "entry",
                        "race_id": race_id,
                        "entry_id": row["entry_id"],
                        "event_date": row["event_date"],
                        "distance_m": row["distance_m"],
                        "reason_code": "unresolved_started_identity",
                        "action": "excluded",
                        "detail": row["identity_status"],
                    }
                )
            continue
        complete_races.add(race_id)
        normal = [row for row in started if row["status"] == "normal_completed"]
        rank_valid = len(normal) >= 3 and _rank_is_strict(row["finish_position"] for row in normal)
        top3_rank_valid = len(normal) >= 3 and _top3_rank_is_strict(
            row["finish_position"] for row in normal
        )
        if not rank_valid:
            rank_invalid_races.add(race_id)
            exclusions.append(
                {
                    "scope": "race",
                    "race_id": race_id,
                    "entry_id": None,
                    "event_date": first["event_date"],
                    "distance_m": first["distance_m"],
                    "reason_code": "full_rank_quality_warning",
                    "action": "retained_warning",
                    "detail": json.dumps(sorted(row["finish_position"] for row in normal)),
                }
            )
        if int(first["distance_m"] or 0) == 400:
            exclusions.append(
                {
                    "scope": "race",
                    "race_id": race_id,
                    "entry_id": None,
                    "event_date": first["event_date"],
                    "distance_m": first["distance_m"],
                    "reason_code": "distance_400_target_excluded",
                    "action": "target_excluded",
                    "detail": "retained in history_results",
                }
            )
        race_info.append(
            {
                "race_id": race_id,
                "event_date": first["event_date"],
                "event_number": int(first["event_number"]),
                "distance_m": int(first["distance_m"]) if first["distance_m"] is not None else None,
                "declared_field_size": len(rows),
                "field_size": len(started),
                "split": _split(first["event_date"]),
                "cutoff_at": _cutoff(first["event_date"]),
                "complete_race": True,
                "rank_validation": "valid" if rank_valid else "invalid",
                "full_rank_valid": bool(rank_valid),
                "top3_rank_valid": bool(top3_rank_valid),
                "official_top3_count": sum(1 for row in normal if row["finish_position"] <= 3),
                "podium_tie": bool(
                    any(
                        sum(1 for row in normal if row["finish_position"] == rank) > 1
                        for rank in (1, 2, 3)
                    )
                ),
                "boundary_tie": sum(row["finish_position"] <= 3 for row in normal) > 3,
                "target_eligible": bool(top3_rank_valid and int(first["distance_m"] or 0) != 400),
            }
        )

    # Keep the 135 no-positive-result race cohort visible in the exclusion
    # ledger even though its rows are intentionally outside the extraction
    # query.  This is a race-level provenance record, not a feature source.
    for source in quarantined_races:
        event_date = _as_date(source["event_date"])
        exclusions.append(
            {
                "scope": "race",
                "race_id": int(source["race_id"]),
                "entry_id": None,
                "event_date": event_date,
                "distance_m": source["distance_m"],
                "reason_code": "no_positive_result_race",
                "action": "excluded",
                "detail": source["population_status"],
            }
        )

    race_meta_by_id = {int(row["race_id"]): row for row in race_info}
    base_rows: list[dict[str, Any]] = []
    history_rows: list[dict[str, Any]] = []
    for race_id in sorted(
        complete_races, key=lambda value: (race_meta_by_id[value]["event_date"], value)
    ):
        info = race_meta_by_id[race_id]
        for row in by_race[race_id]:
            if not _is_started(row["finish_position"]):
                if row["status"] == "nonstarter":
                    exclusions.append(
                        {
                            "scope": "entry",
                            "race_id": race_id,
                            "entry_id": row["entry_id"],
                            "event_date": row["event_date"],
                            "distance_m": row["distance_m"],
                            "reason_code": "nonstarter_excluded",
                            "action": "target_excluded",
                            "detail": str(row["finish_position"]),
                        }
                    )
                continue
            common = {
                "entry_id": int(row["entry_id"]),
                "race_id": race_id,
                "horse_id": row["horse_id"],
                "event_date": row["event_date"],
                "event_number": int(row["event_number"]),
                "horse_number": int(row["horse_number"]),
                "distance_m": int(row["distance_m"]) if row["distance_m"] is not None else None,
                "field_size": info["field_size"],
                "declared_field_size": info["declared_field_size"],
                "cutoff_at": info["cutoff_at"],
                "split": info["split"],
                "full_rank_valid": info["full_rank_valid"],
                "top3_rank_valid": info["top3_rank_valid"],
                "source_row_id": int(row["source_row_id"]),
                "source_row_hash": row["source_row_hash"],
            }
            history_rows.append(
                {
                    **common,
                    "finish_position": row["finish_position"],
                    "finish_time_ms": row["finish_time_ms"],
                    "segment_quality": row["segment_quality"],
                    "outcome_status": row["status"],
                }
            )
            if int(row["distance_m"] or 0) != 400:
                base_rows.append(
                    {
                        **common,
                        "target_eligible": bool(info["target_eligible"]),
                        "finish_position": row["finish_position"],
                        "finish_time_ms": row["finish_time_ms"],
                    }
                )

    label_source = pl.DataFrame(base_rows, infer_schema_length=None)
    entries = label_source.select(
        "entry_id",
        "race_id",
        "horse_id",
        "event_date",
        "event_number",
        "horse_number",
        "distance_m",
        "field_size",
        "declared_field_size",
        "cutoff_at",
        "split",
        "target_eligible",
        "source_row_id",
        "source_row_hash",
    )
    history_results = pl.DataFrame(history_rows, infer_schema_length=None)
    label_parts = build_top3_labels(label_source)
    labels = label_parts["labels"]
    # Preserve entry metadata on labels while keeping result targets separate
    # from the feature frame.  The labels table remains one row per entry.
    labels = entries.select(
        "entry_id", "race_id", "horse_id", "event_date", "horse_number", "target_eligible"
    ).join(
        labels,
        on=["entry_id", "race_id", "horse_id", "horse_number", "event_date"],
        how="left",
        validate="1:1",
    )
    race_table = pl.DataFrame(race_info, infer_schema_length=None)
    # Add race-level accepted counts for rows even when the rank validation was
    # invalid; this makes filtering explicit for downstream folds.
    accepted_order_rows = label_parts["accepted_orders"]
    accepted_set_rows = label_parts["accepted_sets"]
    if not accepted_order_rows.is_empty():
        accepted_order_rows = accepted_order_rows.join(
            race_table.select("race_id", "event_date", "split"),
            on="race_id",
            how="left",
            validate="m:1",
        )
    if not accepted_set_rows.is_empty():
        accepted_set_rows = accepted_set_rows.join(
            race_table.select("race_id", "event_date", "split"),
            on="race_id",
            how="left",
            validate="m:1",
        )
    for table, name in (
        (accepted_order_rows, "accepted_order_count"),
        (accepted_set_rows, "accepted_set_count"),
    ):
        race_table = race_table.join(
            table.group_by("race_id").len(name=name), on="race_id", how="left", validate="1:1"
        ).with_columns(pl.col(name).fill_null(0))
    return {
        "entries": entries,
        "labels": labels,
        "races": race_table,
        "history_results": history_results,
        "exclusions": pl.DataFrame(exclusions, infer_schema_length=None)
        if exclusions
        else pl.DataFrame(),
        "accepted_orders": accepted_order_rows,
        "accepted_sets": accepted_set_rows,
    }


__all__ = [
    "EXPECTED_DB_SHA256",
    "DatasetContractError",
    "build_top3_labels",
    "extract_dataset",
]
