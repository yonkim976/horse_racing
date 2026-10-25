"""Read-only post-refresh verification for the Jeju core database.

``verify_refresh`` accepts the refreshed SQLite database, a baseline database
or baseline directory/manifest, and the refresh manifest.  It does not write
to either database and returns a JSON-serializable result with explicit
failures rather than silently accepting incomplete evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any


FIXED_CUTOFF = "2026-09-19"
EXCLUDED_HORSE_ID = "3005648"
CORE_CURRENT_VIEWS: dict[str, str] = {
    "horse_profile_refresh_current": "observed_kst_date",
    "race_current": "race_date",
    "trial_current": "trial_date",
    "daily_training_api_rows_current": "training_date",
    "daily_training_riders_current": "training_date",
    "training_current": "training_date",
    "starting_training_website_rows_current": "training_date",
    "starting_training_current": "training_date",
    "medical_api_rows_current": "clinic_date",
    "medical_current": "clinic_date",
    "starting_exam_api_rows_current": "exam_date",
    "exam_current": "exam_date",
    "sections_current": "race_date",
}
OPTIONAL_CURRENT_VIEWS: dict[str, str] = {
    "starting_training_api_current": "training_date",
    "api6_section_records_current": "race_date",
}
RAW_CURRENT_VIEW_SOURCES: dict[str, str] = {
    "starting_training_api_current": "refresh_starting_training_api",
    "api6_section_records_current": "refresh_section_records",
}
CURRENT_VIEW_KEYS: dict[str, str] = {
    "horse_profile_refresh_current": "horse_id",
    "race_current": "api_record_id",
    "trial_current": "api_record_id",
    "daily_training_api_rows_current": "daily_training_api_row_id",
    "daily_training_riders_current": "daily_training_api_row_id",
    "training_current": "daily_training_api_row_id",
    "starting_training_website_rows_current": "starting_training_website_row_id",
    "starting_training_current": "starting_training_website_row_id",
    "starting_training_api_current": "api_record_id",
    "medical_api_rows_current": "medical_api_row_id",
    "medical_current": "medical_api_row_id",
    "starting_exam_api_rows_current": "starting_exam_api_row_id",
    "exam_current": "starting_exam_api_row_id",
    "sections_current": "api_record_id",
    "api6_section_records_current": "race_date, meet_code, race_number",
}
REVIEW_TABLES = (
    "section_internal_conflict_reviews",
    "race_section_order_reviews",
    "race_section_time_reviews",
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RefreshVerificationError(ValueError):
    """Raised when verification inputs are missing or malformed."""


def _read_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value
    path = Path(value)
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _quote_identifier(value: str) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise RefreshVerificationError(f"Unsafe SQLite identifier in metadata: {value!r}")
    return '"' + value.replace('"', '""') + '"'


def _schema_objects(conn: sqlite3.Connection) -> dict[str, tuple[str, str | None]]:
    return {
        str(row[0]): (str(row[1]), row[2])
        for row in conn.execute(
            "SELECT name, type, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    }


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _view_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        )
    }


def _table_count(conn: sqlite3.Connection, name: str) -> int:
    return int(conn.execute(f"SELECT count(*) FROM {_quote_identifier(name)}").fetchone()[0])


def _rows_value(entry: Any) -> int | None:
    if isinstance(entry, bool):
        return None
    if isinstance(entry, int):
        return entry
    if isinstance(entry, Mapping):
        for key in ("rows", "row_count", "count"):
            value = entry.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def _snapshot_tables(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {}
    direct = snapshot.get("tables")
    if isinstance(direct, Mapping):
        return dict(direct)
    return {
        str(name): value
        for name, value in snapshot.items()
        if isinstance(name, str) and _SAFE_IDENTIFIER.fullmatch(name)
    }


def _manifest_table_snapshots(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    before_raw = manifest.get("before")
    after_raw = manifest.get("after")
    before = _snapshot_tables(before_raw if isinstance(before_raw, Mapping) else None)
    after = _snapshot_tables(after_raw if isinstance(after_raw, Mapping) else None)

    # Older/alternate manifests may place table snapshots under a `tables`
    # key, e.g. {table: {before: ..., after: ...}}.
    tables = manifest.get("tables")
    if isinstance(tables, Mapping):
        for name, value in tables.items():
            if not isinstance(value, Mapping) or not _SAFE_IDENTIFIER.fullmatch(str(name)):
                continue
            if "before" in value and str(name) not in before:
                before[str(name)] = value["before"]
            if "after" in value and str(name) not in after:
                after[str(name)] = value["after"]
            if str(name) not in after and _rows_value(value) is not None:
                after[str(name)] = value
    return before, after


def _manifest_view_summaries(manifest: Mapping[str, Any]) -> dict[str, Any]:
    checks = manifest.get("checks")
    if isinstance(checks, Mapping) and isinstance(checks.get("current_views"), Mapping):
        return dict(checks["current_views"])
    current = manifest.get("current_views")
    return dict(current) if isinstance(current, Mapping) else {}


def _baseline_inputs(baseline: Any) -> tuple[Path | None, dict[str, Any]]:
    if isinstance(baseline, Mapping):
        data = dict(baseline)
        db_value = data.get("database") or data.get("database_path") or data.get("backup_path")
        return (Path(db_value) if db_value else None), data

    path = Path(baseline)
    if path.is_dir():
        manifest_path = path / "baseline_manifest.json"
        db_path = path / "jeju_native_core.sqlite3"
        if not db_path.is_file():
            raise RefreshVerificationError(f"Baseline database is missing: {db_path}")
        data = _read_json(manifest_path) if manifest_path.is_file() else {}
        return db_path, dict(data)

    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        return path, {}
    data = _read_json(path)
    if not isinstance(data, Mapping):
        raise RefreshVerificationError("Baseline manifest must contain a JSON object")
    db_value = data.get("database") or data.get("database_path") or data.get("backup_path")
    db_path = Path(db_value) if db_value else None
    if db_path is not None and not db_path.is_absolute():
        db_path = path.parent / db_path
    if db_path is None:
        sibling = path.parent / "jeju_native_core.sqlite3"
        if sibling.is_file():
            db_path = sibling
    return db_path, dict(data)


def _digest_rows(conn: sqlite3.Connection, table: str) -> dict[str, Any] | None:
    if table not in _table_names(conn):
        return None
    columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table)})")]
    if not columns:
        return None
    quoted = ", ".join(_quote_identifier(column) for column in columns)
    ordering = ", ".join(_quote_identifier(column) for column in columns)
    digest = hashlib.sha256()
    count = 0
    for row in conn.execute(f"SELECT {quoted} FROM {_quote_identifier(table)} ORDER BY {ordering}"):
        values = []
        for value in row:
            if isinstance(value, bytes):
                values.append({"bytes_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)})
            else:
                values.append(value)
        digest.update(json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
        count += 1
    return {"rows": count, "sha256": digest.hexdigest()}


def _view_summary(
    conn: sqlite3.Connection,
    view: str,
    date_column: str,
    *,
    key_column: str | None = None,
    include_section_guards: bool = False,
) -> dict[str, Any]:
    quoted_view = _quote_identifier(view)
    quoted_date = _quote_identifier(date_column)
    select_parts = [
        "count(*)",
        f"min({quoted_date})",
        f"max({quoted_date})",
        f"sum(CASE WHEN {quoted_date} > ? THEN 1 ELSE 0 END)",
    ]
    params: list[Any] = [FIXED_CUTOFF]
    if key_column is not None:
        quoted_key = _quote_identifier(key_column)
        select_parts.extend(
            [
                f"count(DISTINCT {quoted_key})",
                f"sum(CASE WHEN {quoted_key} IS NULL THEN 1 ELSE 0 END)",
            ]
        )
    if include_section_guards:
        select_parts.extend(
            [
                "sum(CASE WHEN horse_id = ? THEN 1 ELSE 0 END)",
                "sum(CASE WHEN race_date = ? AND race_number = ? AND horse_id = ? "
                "THEN 1 ELSE 0 END)",
                "sum(CASE WHEN race_date = ? AND race_number = ? AND horse_id = ? "
                "AND g1f_time_seconds IS NULL "
                "AND g1f_time_status = 'unresolved_official_website_anomaly' "
                "THEN 1 ELSE 0 END)",
            ]
        )
        params.extend(
            [
                EXCLUDED_HORSE_ID,
                "2026-01-17",
                5,
                "3016494",
                "2026-01-17",
                5,
                "3016494",
            ]
        )
    row = conn.execute(
        f"SELECT {', '.join(select_parts)} FROM {quoted_view}", params
    ).fetchone()
    result = {
        "rows": int(row[0] or 0),
        "min_date": row[1],
        "max_date": row[2],
        "rows_after_2026_09_19": int(row[3] or 0),
    }
    column_index = 4
    if key_column is not None:
        result["distinct_keys"] = int(row[column_index] or 0)
        result["null_key_rows"] = int(row[column_index + 1] or 0)
        column_index += 2
    if include_section_guards:
        result["excluded_horse_rows"] = int(row[column_index] or 0)
        result["kwanghae_rows"] = int(row[column_index + 1] or 0)
        result["kwanghae_null_guard_rows"] = int(row[column_index + 2] or 0)
    return result


def _check_unique_key(conn: sqlite3.Connection, view: str, key: str) -> dict[str, int]:
    quoted_view = _quote_identifier(view)
    key_columns = [part.strip() for part in key.split(",")]
    quoted_keys = ", ".join(_quote_identifier(part) for part in key_columns)
    null_predicate = " OR ".join(f"{_quote_identifier(part)} IS NULL" for part in key_columns)
    rows = int(conn.execute(f"SELECT count(*) FROM {quoted_view}").fetchone()[0])
    distinct_keys = int(
        conn.execute(
            f"SELECT count(*) FROM (SELECT {quoted_keys} FROM {quoted_view} "
            f"GROUP BY {quoted_keys})"
        ).fetchone()[0]
    )
    null_key_rows = int(
        conn.execute(
            f"SELECT count(*) FROM {quoted_view} WHERE {null_predicate}"
        ).fetchone()[0]
    )
    return {
        "rows": rows,
        "distinct_keys": distinct_keys,
        "null_key_rows": null_key_rows,
    }


def _horse_id_column_exists(conn: sqlite3.Connection, view: str) -> bool:
    return "horse_id" in {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({_quote_identifier(view)})")
    }


def _section_status_snapshot(
    conn: sqlite3.Connection,
    view: str,
    status_column: str,
    value_column: str,
    statuses: tuple[str, ...],
    held_statuses: tuple[str, ...],
) -> dict[str, int]:
    quoted_view = _quote_identifier(view)
    quoted_status = _quote_identifier(status_column)
    quoted_value = _quote_identifier(value_column)
    status_terms = [
        f"coalesce(sum(CASE WHEN {quoted_status} = ? THEN 1 ELSE 0 END), 0)"
        for _ in statuses
    ]
    held_placeholders = ", ".join("?" for _ in held_statuses)
    leak_term = (
        f"coalesce(sum(CASE WHEN {quoted_status} IN ({held_placeholders}) "
        f"AND {quoted_value} IS NOT NULL THEN 1 ELSE 0 END), 0)"
    )
    row = conn.execute(
        f"SELECT {', '.join(status_terms + [leak_term])} FROM {quoted_view}",
        (*statuses, *held_statuses),
    ).fetchone()
    result = {status: int(row[index] or 0) for index, status in enumerate(statuses)}
    result["held_nonnull_values"] = int(row[len(statuses)] or 0)
    return result


def _append_check(checks: list[dict[str, Any]], name: str, ok: bool, detail: Any) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def verify_refresh(db: Any, baseline: Any, manifest: Any) -> dict[str, Any]:
    """Compare a refreshed Jeju DB to its baseline and refresh manifest.

    ``db`` may be a database path or an already-open ``sqlite3.Connection``.
    ``baseline`` may be the baseline database path, its containing directory,
    or a baseline manifest object/path. ``manifest`` may be a mapping or JSON
    path. Connections opened here use SQLite URI ``mode=ro`` and
    ``PRAGMA query_only=ON``.
    """

    manifest_data = _read_json(manifest)
    if not isinstance(manifest_data, Mapping):
        raise RefreshVerificationError("Refresh manifest must contain a JSON object")
    baseline_db_path, baseline_data = _baseline_inputs(baseline)
    baseline_tables = _snapshot_tables(baseline_data)
    before_tables, after_tables = _manifest_table_snapshots(manifest_data)
    expected_view_summaries = _manifest_view_summaries(manifest_data)
    checks: list[dict[str, Any]] = []
    opened_refresh = False
    opened_baseline = False

    if isinstance(db, sqlite3.Connection):
        refresh_conn = db
        refresh_conn.execute("PRAGMA query_only = ON")
    else:
        refresh_conn = _readonly_connection(Path(db))
        opened_refresh = True

    baseline_conn: sqlite3.Connection | None = None
    if baseline_db_path is not None and baseline_db_path.is_file():
        baseline_conn = _readonly_connection(baseline_db_path)
        opened_baseline = True

    try:
        after_objects = _schema_objects(refresh_conn)
        after_tables_set = _table_names(refresh_conn)
        after_views_set = _view_names(refresh_conn)

        integrity_rows = [str(row[0]) for row in refresh_conn.execute("PRAGMA integrity_check")]
        _append_check(checks, "sqlite_integrity_check", integrity_rows == ["ok"], integrity_rows[:10])
        fk_rows = [tuple(row) for row in refresh_conn.execute("PRAGMA foreign_key_check")]
        _append_check(checks, "foreign_key_check", not fk_rows, {"violations": len(fk_rows), "sample": fk_rows[:10]})

        # Existing schema objects, especially every fixed legacy view, must be
        # byte-for-byte the same SQL as in the baseline.
        baseline_views = baseline_data.get("views") if isinstance(baseline_data.get("views"), Mapping) else {}
        baseline_objects = baseline_data.get("schema_metadata") if isinstance(baseline_data.get("schema_metadata"), Mapping) else {}
        if baseline_conn is not None:
            baseline_objects_live = _schema_objects(baseline_conn)
            existing_schema_changes = {
                name: {
                    "baseline": definition,
                    "refresh": after_objects.get(name),
                }
                for name, definition in baseline_objects_live.items()
                if after_objects.get(name) != definition
            }
            baseline_views = {
                name: value[1]
                for name, value in baseline_objects_live.items()
                if value[0] == "view"
            }
            _append_check(
                checks,
                "baseline_schema_preserved",
                not existing_schema_changes,
                {"changed_existing_objects": len(existing_schema_changes), "sample": dict(list(existing_schema_changes.items())[:5])},
            )
        elif baseline_views or baseline_objects:
            existing_view_changes = {}
            expected_objects: dict[str, Any] = dict(baseline_views)
            expected_objects.update(baseline_objects)
            for name, expected in expected_objects.items():
                if isinstance(expected, Mapping):
                    expected_sql = expected.get("sql")
                    expected_type = expected.get("type")
                else:
                    expected_sql = expected
                    expected_type = None
                current = after_objects.get(str(name))
                if (
                    current is None
                    or (expected_type is not None and current[0] != expected_type)
                    or (expected_sql is not None and current[1] != expected_sql)
                ):
                    existing_view_changes[str(name)] = {
                        "baseline_sql_present": expected_sql is not None,
                        "refresh_type": current[0] if current else None,
                    }
            _append_check(
                checks,
                "baseline_views_preserved",
                not existing_view_changes,
                {"changed_or_missing_views": len(existing_view_changes), "sample": dict(list(existing_view_changes.items())[:5])},
            )
        else:
            _append_check(checks, "baseline_schema_preserved", False, "No baseline DB or schema manifest supplied")

        missing_views = sorted(set(CORE_CURRENT_VIEWS) - after_views_set)
        _append_check(checks, "current_views_present", not missing_views, missing_views)

        current_definition_names = set(CORE_CURRENT_VIEWS) | {
            "horse_current",
            "jeju_race_population_candidate_passing_orders_current",
            "jeju_race_candidate_passing_with_corner_rank_current",
            "jeju_race_section_time_values_current",
            "jeju_race_section_times_current",
            "jeju_race_section_order_values_current",
            "jeju_race_section_orders_current",
            "jeju_race_section_order_quality_values_current",
            "jeju_race_section_order_quality_current",
            "jeju_race_postrace_sections_current",
            "jeju_race_postrace_sections_reviewed_current",
        }
        current_definition_names.update(
            view for view in OPTIONAL_CURRENT_VIEWS if view in after_views_set
        )
        cutoff_matches = {
            name: after_objects[name][1]
            for name in sorted(current_definition_names)
            if name in after_objects
            and after_objects[name][0] == "view"
            and after_objects[name][1]
            and FIXED_CUTOFF in after_objects[name][1]
        }
        _append_check(
            checks,
            "current_view_definitions_unbounded_by_fixed_cutoff",
            not cutoff_matches,
            {"views_with_cutoff_literal": sorted(cutoff_matches)},
        )

        summaries: dict[str, Any] = {}
        key_checks: dict[str, Any] = {}
        current_views = dict(CORE_CURRENT_VIEWS)
        for view, date_column in OPTIONAL_CURRENT_VIEWS.items():
            if view in after_views_set:
                current_views[view] = date_column
        for view, date_column in current_views.items():
            if view not in after_views_set:
                continue
            is_sections = view == "sections_current"
            summaries[view] = _view_summary(
                refresh_conn,
                view,
                date_column,
                key_column=CURRENT_VIEW_KEYS[view] if "," not in CURRENT_VIEW_KEYS[view] else None,
                include_section_guards=is_sections,
            )
            if is_sections:
                key_result = {
                    key: summaries[view][key]
                    for key in ("rows", "distinct_keys", "null_key_rows")
                }
            else:
                key_result = _check_unique_key(refresh_conn, view, CURRENT_VIEW_KEYS[view])
            key_checks[view] = key_result
            _append_check(
                checks,
                f"current_key_unique:{view}",
                key_result["rows"] == key_result["distinct_keys"] and key_result["null_key_rows"] == 0,
                key_result,
            )
        raw_source_checks: dict[str, Any] = {}
        for view, source_table in RAW_CURRENT_VIEW_SOURCES.items():
            if view not in after_views_set:
                continue
            source_count = _table_count(refresh_conn, source_table)
            view_count = int(
                refresh_conn.execute(
                    f"SELECT count(*) FROM {_quote_identifier(view)}"
                ).fetchone()[0]
            )
            missing_provenance = int(
                refresh_conn.execute(
                    f"SELECT count(*) FROM {_quote_identifier(view)} "
                    "WHERE payload_json IS NULL OR payload_sha256 IS NULL "
                    "OR source_artifact_id IS NULL OR artifact_sha256 IS NULL "
                    "OR raw_relative_path IS NULL"
                ).fetchone()[0]
            )
            raw_source_checks[view] = {
                "source_table_rows": source_count,
                "view_rows": view_count,
                "missing_payload_or_provenance_rows": missing_provenance,
            }
            _append_check(
                checks,
                f"raw_payload_provenance_join:{view}",
                source_count == view_count and missing_provenance == 0,
                raw_source_checks[view],
            )
        view_bound_results: dict[str, Any] = {}
        for view, expected in expected_view_summaries.items():
            if view not in summaries or not isinstance(expected, Mapping):
                continue
            actual = summaries[view]
            expected_rows = _rows_value(expected)
            expected_first = expected.get("first", expected.get("min_date"))
            expected_latest = expected.get("latest", expected.get("max_date"))
            checks_for_view = {
                "actual": actual,
                "expected": {
                    "rows": expected_rows,
                    "first": expected_first,
                    "latest": expected_latest,
                },
            }
            checks_for_view["matches"] = (
                (expected_rows is None or actual["rows"] == expected_rows)
                and (expected_first is None or actual["min_date"] == expected_first)
                and (expected_latest is None or actual["max_date"] == expected_latest)
            )
            view_bound_results[view] = checks_for_view
        expected_summary_views = set(current_views)
        missing_view_summaries = sorted(expected_summary_views - set(expected_view_summaries))
        bounds_available = bool(view_bound_results) and not missing_view_summaries
        bounds_match = bounds_available and all(
            detail["matches"] for detail in view_bound_results.values()
        )
        _append_check(
            checks,
            "current_view_date_bounds_match_manifest",
            bounds_match,
            {
                "matched_views": view_bound_results,
                "manifest_current_view_entries": sorted(expected_view_summaries),
                "missing_current_view_entries": missing_view_summaries,
                "actual_bounds": summaries,
            },
        )

        # The four legacy 2026 views are intentionally cutoff-bound. Their
        # current counterparts must be supersets over the same source rows.
        for legacy, current in (
            ("daily_training_api_rows_analysis_2026", "daily_training_api_rows_current"),
            ("starting_training_website_rows_analysis_2026", "starting_training_website_rows_current"),
            ("medical_api_rows_analysis_2026", "medical_api_rows_current"),
            ("starting_exam_api_rows_analysis_2026", "starting_exam_api_rows_current"),
        ):
            if legacy in after_views_set and current in after_views_set:
                legacy_rows = int(refresh_conn.execute(f"SELECT count(*) FROM {_quote_identifier(legacy)}").fetchone()[0])
                current_rows = int(refresh_conn.execute(f"SELECT count(*) FROM {_quote_identifier(current)}").fetchone()[0])
                _append_check(
                    checks,
                    f"current_scope_superset:{current}",
                    current_rows >= legacy_rows,
                    {"legacy_rows": legacy_rows, "current_rows": current_rows},
                )

        # Profile ages remain 2026-based in every current event view that has
        # those fields, independent of the system date or event date.
        for view in ("horse_current", "race_current", "trial_current"):
            if view not in after_views_set:
                continue
            columns = {str(row[1]) for row in refresh_conn.execute(f"PRAGMA table_info({_quote_identifier(view)})")}
            if {"age_2026", "age_reference_year", "birth_year"}.issubset(columns):
                mismatches = int(
                    refresh_conn.execute(
                        f"SELECT count(*) FROM {_quote_identifier(view)} "
                        "WHERE age_reference_year IS NOT 2026 "
                        "OR (birth_year IS NOT NULL AND age_2026 IS NOT (2026 - birth_year))"
                    ).fetchone()[0]
                )
                _append_check(checks, f"fixed_2026_age_policy:{view}", mismatches == 0, {"mismatches": mismatches})

        # Never re-import the user-excluded horse into any current profile or
        # event-facing view. Raw evidence archives are intentionally outside
        # this query-level prohibition.
        excluded_views: dict[str, int] = {}
        for view in ("horse_current", *current_views.keys()):
            if view not in after_views_set or not _horse_id_column_exists(refresh_conn, view):
                continue
            if view == "sections_current" and view in summaries:
                excluded_views[view] = summaries[view]["excluded_horse_rows"]
            else:
                excluded_views[view] = int(
                    refresh_conn.execute(
                        f"SELECT count(*) FROM {_quote_identifier(view)} WHERE horse_id = ?",
                        (EXCLUDED_HORSE_ID,),
                    ).fetchone()[0]
                )
        if excluded_views:
            no_excluded_horse = all(count == 0 for count in excluded_views.values())
            _append_check(checks, "excluded_horse_not_reimported", no_excluded_horse, excluded_views)
        else:
            _append_check(checks, "excluded_horse_not_reimported", False, "No current horse_id views available")

        # Preserve the reviewed section quality policy. Counts are expressed
        # at the normalized field/race level, not multiplied by runners.
        section_checks: dict[str, Any] = {}
        order_quality_view = (
            "jeju_race_section_order_quality_values_current"
            if "jeju_race_section_order_quality_values_current" in after_views_set
            else "jeju_race_section_order_quality_values"
        )
        if order_quality_view in after_views_set:
            order_snapshot = _section_status_snapshot(
                refresh_conn,
                order_quality_view,
                "quality_order_status",
                "quality_order_value",
                (
                    "unresolved_official_internal_conflict",
                    "website_corrected",
                    "api_source_changed_since_review",
                ),
                (
                    "unresolved_official_internal_conflict",
                    "api_source_changed_since_review",
                ),
            )
            section_checks["unresolved_order_fields"] = order_snapshot[
                "unresolved_official_internal_conflict"
            ]
            section_checks["website_corrected_order_fields"] = order_snapshot["website_corrected"]
            section_checks["order_source_sha_mismatch_rows"] = order_snapshot[
                "api_source_changed_since_review"
            ]
            order_hold_value_leaks = order_snapshot["held_nonnull_values"]
            section_checks["order_hold_nonnull_values"] = order_hold_value_leaks
            _append_check(
                checks,
                "section_order_review_policy",
                section_checks["unresolved_order_fields"] == 70
                and section_checks["website_corrected_order_fields"] == 14
                and order_hold_value_leaks == 0,
                section_checks,
            )
        else:
            _append_check(checks, "section_order_review_policy", False, "quality order view missing")

        if "jeju_race_section_group_quality_values" in after_views_set:
            group_snapshot = _section_status_snapshot(
                refresh_conn,
                "jeju_race_section_group_quality_values",
                "group_status",
                "group_value",
                (
                    "unresolved_official_internal_conflict",
                    "api_source_changed_since_conflict_review",
                ),
                (
                    "unresolved_official_internal_conflict",
                    "api_source_changed_since_conflict_review",
                ),
            )
            section_checks["unresolved_group_points"] = group_snapshot[
                "unresolved_official_internal_conflict"
            ]
            section_checks["group_source_sha_mismatch_rows"] = group_snapshot[
                "api_source_changed_since_conflict_review"
            ]
            group_hold_value_leaks = group_snapshot["held_nonnull_values"]
            section_checks["group_hold_nonnull_values"] = group_hold_value_leaks
            _append_check(
                checks,
                "section_group_review_policy",
                section_checks["unresolved_group_points"] == 20
                and group_hold_value_leaks == 0,
                section_checks,
            )
        else:
            _append_check(checks, "section_group_review_policy", False, "quality group view missing")

        conflict_review_count = (
            _table_count(refresh_conn, "section_internal_conflict_reviews")
            if "section_internal_conflict_reviews" in after_tables_set
            else None
        )
        _append_check(
            checks,
            "section_conflict_review_ledger",
            conflict_review_count == 90,
            {"rows": conflict_review_count, "expected_order_and_group_reviews": 90},
        )

        if "sections_current" in after_views_set:
            section_summary = summaries["sections_current"]
            anomaly_rows = section_summary["kwanghae_rows"]
            null_guard_rows = section_summary["kwanghae_null_guard_rows"]
            anomaly_ok = anomaly_rows == 1 and null_guard_rows == 1
            _append_check(
                checks,
                "kwanghae_cheongmyeong_g1f_remains_null",
                anomaly_ok,
                {
                    "matching_rows": anomaly_rows,
                    "null_with_anomaly_status_rows": null_guard_rows,
                },
            )

            section_count = section_summary["rows"]
            race_count = summaries["race_current"]["rows"] if "race_current" in summaries else -1
            _append_check(
                checks,
                "sections_current_matches_race_current",
                section_count == race_count,
                {"sections_rows": section_count, "race_rows": race_count},
            )

        for table in REVIEW_TABLES:
            if table not in after_tables_set:
                _append_check(checks, f"review_table_preserved:{table}", False, "review table missing")
                continue
            after_digest = _digest_rows(refresh_conn, table)
            baseline_digest = _digest_rows(baseline_conn, table) if baseline_conn is not None else None
            if baseline_digest is None:
                _append_check(checks, f"review_table_preserved:{table}", False, "baseline review table unavailable")
            else:
                _append_check(
                    checks,
                    f"review_table_preserved:{table}",
                    after_digest == baseline_digest,
                    {"baseline": baseline_digest, "refresh": after_digest},
                )

        table_count_checks: dict[str, Any] = {}
        for table, after_snapshot in after_tables.items():
            if table not in after_tables_set:
                table_count_checks[table] = {"error": "manifest table missing from refreshed DB"}
                continue
            expected_after = _rows_value(after_snapshot)
            actual_after = _table_count(refresh_conn, table)
            check = {"expected_after_rows": expected_after, "actual_after_rows": actual_after}
            if expected_after is not None:
                check["after_matches_manifest"] = expected_after == actual_after
            before_snapshot = before_tables.get(table)
            baseline_snapshot = baseline_tables.get(table)
            expected_before = _rows_value(before_snapshot)
            baseline_expected = _rows_value(baseline_snapshot)
            if expected_before is None:
                expected_before = baseline_expected
            baseline_actual = None
            if baseline_conn is not None and table in _table_names(baseline_conn):
                baseline_actual = _table_count(baseline_conn, table)
            if expected_before is not None:
                check["expected_before_rows"] = expected_before
            if baseline_expected is not None:
                check["baseline_manifest_rows"] = baseline_expected
                check["before_matches_baseline_manifest"] = (
                    expected_before is None or expected_before == baseline_expected
                )
            if baseline_actual is not None:
                check["baseline_actual_rows"] = baseline_actual
            if expected_before is not None and expected_after is not None:
                check["inserted_rows"] = expected_after - expected_before
            table_count_checks[table] = check
        table_count_ok = all(
            "error" not in value
            and value.get("after_matches_manifest", True)
            and ("baseline_actual_rows" not in value or "expected_before_rows" not in value or value["baseline_actual_rows"] == value["expected_before_rows"])
            and value.get("before_matches_baseline_manifest", True)
            and value.get("actual_after_rows", 0) >= value.get("baseline_actual_rows", 0)
            for value in table_count_checks.values()
        )
        _append_check(checks, "manifest_table_counts", table_count_ok, table_count_checks)

        metadata = []
        if "jeju_current_view_metadata" in after_views_set:
            metadata = [tuple(row) for row in refresh_conn.execute(
                "SELECT view_name, temporal_scope, profile_policy, source_and_quality_policy "
                "FROM jeju_current_view_metadata ORDER BY view_name"
            )]
        metadata_names = {str(row[0]) for row in metadata}
        expected_metadata = set(CORE_CURRENT_VIEWS) | {"horse_current"}
        expected_metadata.update(
            view for view in OPTIONAL_CURRENT_VIEWS if view in after_views_set
        )
        _append_check(
            checks,
            "current_scope_metadata_explicit",
            expected_metadata.issubset(metadata_names),
            {"expected": sorted(expected_metadata), "actual": sorted(metadata_names)},
        )

        failures = [item for item in checks if not item["ok"]]
        return {
            "ok": not failures,
            "database": str(db) if not isinstance(db, sqlite3.Connection) else "<sqlite3.Connection>",
            "baseline_database": str(baseline_db_path) if baseline_db_path else None,
            "refresh_manifest": str(manifest) if not isinstance(manifest, Mapping) else "<mapping>",
            "current_view_date_bounds": summaries,
            "current_view_keys": key_checks,
            "section_policy": section_checks,
            "checks": checks,
            "failure_count": len(failures),
        }
    finally:
        if opened_refresh:
            refresh_conn.close()
        if opened_baseline and baseline_conn is not None:
            baseline_conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Refreshed SQLite DB, opened read-only")
    parser.add_argument("--baseline", required=True, help="Baseline DB, baseline directory, or baseline manifest")
    parser.add_argument("--manifest", required=True, help="Refresh manifest JSON")
    args = parser.parse_args(argv)
    result = verify_refresh(args.db, args.baseline, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["RefreshVerificationError", "verify_refresh"]
