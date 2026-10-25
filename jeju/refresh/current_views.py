"""Create additive, explicitly current-scope Jeju research views.

The legacy ``*_analysis_2026`` views remain fixed in place. This module copies
their SQL into new ``*_current`` views, removes only the documented
2026-09-19 event-date predicates, and adds indexed join-order helpers for the
current race/profile and reviewed section chains. It never commits the caller's
transaction.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass


FIXED_CUTOFF = "2026-09-19"
_SAVEPOINT = "jeju_apply_current_views"


@dataclass(frozen=True)
class _Recipe:
    target: str
    source: str | None = None
    cutoff_predicate: str | None = None
    identifier_replacements: tuple[tuple[str, str], ...] = ()
    add_current_jeju_profile_filter: bool = False
    select_sql: str | None = None
    optional: bool = False
    optional_table: str | None = None
    force_profile_join_order: bool = False
    force_race_api4_join_order: bool = False
    force_section_source_join_order: bool = False


_RECIPES: tuple[_Recipe, ...] = (
    # Preserve the legacy latest-profile projection and tie-break rules, but
    # make SQLite drive the PK lookups from the small ranked profile set.
    _Recipe(
        target="horse_profile_refresh_current",
        source="horse_profile_latest",
        force_profile_join_order=True,
    ),
    # Current profile policy is intentionally fixed to the latest API42
    # observation while the age reference year remains 2026.
    _Recipe(
        target="horse_current",
        source="horse_analysis_2026",
        identifier_replacements=(("horse_profile_latest", "horse_profile_refresh_current"),),
    ),
    _Recipe(
        target="jeju_race_population_candidate_passing_orders_current",
        source="jeju_race_population_candidate_passing_orders",
        force_race_api4_join_order=True,
    ),
    _Recipe(
        target="jeju_race_candidate_passing_with_corner_rank_current",
        source="jeju_race_candidate_passing_with_corner_rank",
        identifier_replacements=((
            "jeju_race_population_candidate_passing_orders",
            "jeju_race_population_candidate_passing_orders_current",
        ),),
    ),
    # Race and trial views have no 2026-09-19 predicate in their source SQL.
    # Keep their legacy candidate and explicit-Jeju source semantics.
    _Recipe(
        target="race_current",
        source="jeju_race_analysis_2026",
        identifier_replacements=(
            ("horse_profile_latest", "horse_profile_refresh_current"),
            (
                "jeju_race_candidate_passing_with_corner_rank",
                "jeju_race_candidate_passing_with_corner_rank_current",
            ),
        ),
        add_current_jeju_profile_filter=True,
    ),
    _Recipe(
        target="trial_current",
        source="jeju_trial_analysis_2026",
        identifier_replacements=(("horse_profile_latest", "horse_profile_refresh_current"),),
    ),
    # API18 source, rider identity and rider-type enrichments all reuse the
    # current API18 rows.  Only the analysis view's final event-date predicate
    # is removed.
    _Recipe(
        target="daily_training_api_rows_current",
        source="daily_training_api_rows_analysis_2026",
        cutoff_predicate="WHERE r.training_date <= '2026-09-19'",
    ),
    _Recipe(
        target="daily_training_riders_current",
        source="daily_training_riders_analysis_2026",
        identifier_replacements=((
            "daily_training_api_rows_analysis_2026",
            "daily_training_api_rows_current",
        ),),
    ),
    _Recipe(
        target="training_current",
        source="daily_training_rider_types_analysis_2026",
        identifier_replacements=((
            "daily_training_api_rows_analysis_2026",
            "daily_training_api_rows_current",
        ),),
    ),
    _Recipe(
        target="starting_training_website_rows_current",
        source="starting_training_website_rows_analysis_2026",
        cutoff_predicate="WHERE latest.training_date <= '2026-09-19'",
    ),
    _Recipe(
        target="starting_training_current",
        select_sql="SELECT * FROM starting_training_website_rows_current",
    ),
    # API22 is an independent raw source and must not be confused with the
    # canonical website starting-training table. Keep payload and provenance.
    _Recipe(
        target="starting_training_api_current",
        select_sql=(
            "SELECT x.*, a.payload_json, a.payload_sha256, a.source_artifact_id, "
            "a.record_index, sa.collected_at_utc, sa.sha256 AS artifact_sha256, "
            "sa.raw_relative_path "
            "FROM refresh_starting_training_api AS x "
            "JOIN api_records AS a USING (api_record_id) "
            "JOIN source_artifacts AS sa USING (source_artifact_id)"
        ),
        optional=True,
        optional_table="refresh_starting_training_api",
    ),
    _Recipe(
        target="medical_api_rows_current",
        source="medical_api_rows_analysis_2026",
        cutoff_predicate="WHERE r.clinic_date <= '2026-09-19'",
    ),
    _Recipe(target="medical_current", select_sql="SELECT * FROM medical_api_rows_current"),
    _Recipe(
        target="starting_exam_api_rows_current",
        source="starting_exam_api_rows_analysis_2026",
        cutoff_predicate="WHERE se.exam_date <= '2026-09-19'",
    ),
    _Recipe(target="exam_current", select_sql="SELECT * FROM starting_exam_api_rows_current"),
    # The raw time/order review-value views use the same candidate/API/source
    # join pattern as the race view. Preserve their exact fields and review
    # logic while making those provenance lookups race-row driven.
    _Recipe(
        target="jeju_race_section_time_values_current",
        source="jeju_race_section_time_values",
        force_section_source_join_order=True,
    ),
    _Recipe(
        target="jeju_race_section_times_current",
        source="jeju_race_section_times",
        identifier_replacements=((
            "jeju_race_section_time_values",
            "jeju_race_section_time_values_current",
        ),),
    ),
    _Recipe(
        target="jeju_race_section_order_values_current",
        source="jeju_race_section_order_values",
        force_section_source_join_order=True,
    ),
    _Recipe(
        target="jeju_race_section_orders_current",
        source="jeju_race_section_orders",
        identifier_replacements=((
            "jeju_race_section_order_values",
            "jeju_race_section_order_values_current",
        ),),
    ),
    _Recipe(
        target="jeju_race_section_order_quality_values_current",
        source="jeju_race_section_order_quality_values",
        identifier_replacements=((
            "jeju_race_section_order_values",
            "jeju_race_section_order_values_current",
        ),),
    ),
    _Recipe(
        target="jeju_race_section_order_quality_current",
        source="jeju_race_section_order_quality",
        identifier_replacements=((
            "jeju_race_section_order_quality_values",
            "jeju_race_section_order_quality_values_current",
        ),),
    ),
    # Rebuild the three-layer post-race chain from the quality view downward.
    # This keeps reviewed orders, 70/20 conflict holds, 14 website corrections,
    # the Kwanghae Cheongmyeong G1F NULL, and SHA mismatch guards intact.
    _Recipe(
        target="jeju_race_postrace_sections_current",
        source="jeju_race_postrace_sections_2026",
        identifier_replacements=(
            ("jeju_race_analysis_2026", "race_current"),
            ("jeju_race_section_times", "jeju_race_section_times_current"),
        ),
    ),
    _Recipe(
        target="jeju_race_postrace_sections_reviewed_current",
        source="jeju_race_postrace_sections_reviewed_2026",
        identifier_replacements=((
            "jeju_race_postrace_sections_2026",
            "jeju_race_postrace_sections_current",
        ), (
            "jeju_race_section_orders",
            "jeju_race_section_orders_current",
        )),
    ),
    _Recipe(
        target="sections_current",
        source="jeju_race_postrace_sections_quality_2026",
        identifier_replacements=(
            (
                "jeju_race_postrace_sections_reviewed_2026",
                "jeju_race_postrace_sections_reviewed_current",
            ),
            (
                "jeju_race_section_order_quality",
                "jeju_race_section_order_quality_current",
            ),
        ),
    ),
    # API6 is retained as a separately sourced raw observation.  It is not
    # folded into the API4/API303 quality view without a reviewed mapping.
    _Recipe(
        target="api6_section_records_current",
        select_sql=(
            "SELECT x.*, a.payload_json, a.payload_sha256, a.source_artifact_id, "
            "a.record_index, sa.collected_at_utc, sa.sha256 AS artifact_sha256, "
            "sa.raw_relative_path "
            "FROM refresh_section_records AS x "
            "JOIN api_records AS a USING (api_record_id) "
            "JOIN source_artifacts AS sa USING (source_artifact_id)"
        ),
        optional=True,
        optional_table="refresh_section_records",
    ),
)


_METADATA_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("horse_profile_refresh_current", "latest profile observations", "same API42 latest-observation ordering and 2026 age inputs as horse_profile_latest", "profile output plus payload/source provenance; join order fixed for indexed lookups"),
    ("horse_current", "latest profile observations", "API42 latest observation; age fixed to 2026", "horse_analysis_2026 with optimized current profile lookup"),
    ("jeju_race_population_candidate_passing_orders_current", "all eligible race-result candidates with API4 passing fields", "candidate eligibility as stored in jeju_race_population_candidates", "same projection and inner-join predicates as legacy passing-order view; PK lookups driven by race rows"),
    ("jeju_race_candidate_passing_with_corner_rank_current", "same event scope as jeju_race_population_candidate_passing_orders_current", "same candidate eligibility", "API4 current passing-order clone plus legacy optional API303 corner-rank joins"),
    ("race_current", "current eligible race source rows; no event-date ceiling", "latest API42 profile; require profile breed 제주마; age fixed to 2026", "optimized current API4 passing chain plus current profile check"),
    ("trial_current", "all explicit Jeju trial source rows; no event-date ceiling", "latest API42 profile; age fixed to 2026", "jeju_trial_analysis_2026"),
    ("daily_training_api_rows_current", "all loaded API18 training dates; no 2026-09-19 ceiling", "latest API42 name; age fixed to 2026", "daily_training_api_rows_analysis_2026 with only final date predicate removed"),
    ("daily_training_riders_current", "same event scope as daily_training_api_rows_current", "existing witness-payload SHA guard retained", "daily_training_riders_analysis_2026 over current API18 rows"),
    ("training_current", "same event scope as daily_training_api_rows_current", "existing type and jockey-name rules retained", "daily_training_rider_types_analysis_2026 over current API18 rows"),
    ("starting_training_website_rows_current", "all latest-per-date website artifacts; no 2026-09-19 ceiling", "latest API42 name; age fixed to 2026", "starting_training_website_rows_analysis_2026 with only final date predicate removed"),
    ("starting_training_current", "same event scope as starting_training_website_rows_current", "same as source current view", "alias of starting_training_website_rows_current"),
    ("starting_training_api_current", "all loaded API22 dates; no event-date ceiling", "raw API22 horse_id; no profile enrichment or age field", "separate raw API22 records with payload SHA and source-artifact provenance; not a website-equivalent table"),
    ("medical_api_rows_current", "all loaded clinic dates; no 2026-09-19 ceiling", "current API42 profile breed 제주마; age fixed to 2026", "medical_api_rows_analysis_2026 with only final date predicate removed"),
    ("medical_current", "same event scope as medical_api_rows_current", "same as source current view", "alias of medical_api_rows_current"),
    ("starting_exam_api_rows_current", "all loaded exam dates; no 2026-09-19 ceiling", "latest API42 profile; age fixed to 2026", "starting_exam_api_rows_analysis_2026 with only final date predicate removed"),
    ("exam_current", "same event scope as starting_exam_api_rows_current", "same as source current view", "alias of starting_exam_api_rows_current"),
    ("jeju_race_section_time_values_current", "all current eligible race-result candidate rows by time field", "same source and observed values as jeju_race_section_time_values; website review and API SHA guard retained", "same field projection with race-row-driven API/source lookups"),
    ("jeju_race_section_times_current", "same event scope as jeju_race_section_time_values_current", "website corrections, NULL holds and API SHA guards retained", "aggregate of current time-value rows"),
    ("jeju_race_section_order_values_current", "all current eligible race-result candidate rows by order field", "same source and observed values as jeju_race_section_order_values; website review and API SHA guard retained", "same field projection with race-row-driven API/source lookups"),
    ("jeju_race_section_orders_current", "same event scope as jeju_race_section_order_values_current", "website corrections and API SHA guards retained", "aggregate of current order-value rows"),
    ("jeju_race_section_order_quality_values_current", "same event scope as jeju_race_section_order_values_current", "70 internal-conflict holds; API SHA mismatch remains blocked", "quality values over current order-value rows"),
    ("jeju_race_section_order_quality_current", "same event scope as jeju_race_section_order_quality_values_current", "70 internal-conflict holds remain NULL with review status", "aggregate of current order-quality values"),
    ("sections_current", "current eligible race rows; no event-date ceiling", "same as race_current", "quality chain; reviewed corrections, conflict holds and source-SHA guards retained"),
    ("api6_section_records_current", "all loaded API6 race dates; separate raw source", "not horse-profile joined", "raw API6 observations; not merged into reviewed section-quality fields"),
)


def _object_type(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ? AND type IN ('table','view')",
        (name,),
    ).fetchone()
    return str(row[0]) if row else None


def _source_view_sql(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = ?",
        (name,),
    ).fetchone()
    if not row or not row[0]:
        raise RuntimeError(f"Required source view is missing: {name}")
    return str(row[0])


def _replace_view_header(sql: str, source: str, target: str) -> str:
    pattern = re.compile(
        rf"\A\s*CREATE\s+VIEW\s+{re.escape(source)}\s+AS\b",
        flags=re.IGNORECASE,
    )
    match = pattern.match(sql)
    if match is None:
        raise RuntimeError(f"Unexpected SQL header for source view {source}")
    return f"CREATE VIEW {target} AS" + sql[match.end() :]


def _replace_identifier(sql: str, source: str, target: str) -> str:
    return re.sub(rf"\b{re.escape(source)}\b", target, sql)


def _build_view_sql(conn: sqlite3.Connection, recipe: _Recipe) -> str | None:
    if recipe.select_sql is not None:
        if (
            recipe.optional
            and recipe.optional_table
            and _object_type(conn, recipe.optional_table) is None
        ):
            return None
        return f"CREATE VIEW {recipe.target} AS {recipe.select_sql}"

    assert recipe.source is not None
    sql = _replace_view_header(
        _source_view_sql(conn, recipe.source), recipe.source, recipe.target
    )
    if recipe.force_profile_join_order:
        join_pattern = re.compile(
            r"FROM\s+ranked\s+r\s+"
            r"JOIN\s+api_records\s+a\s+ON\s+a\.api_record_id\s*=\s*r\.api_record_id\s+"
            r"JOIN\s+source_artifacts\s+sa\s+ON\s+sa\.source_artifact_id\s*=\s*a\.source_artifact_id\s+"
            r"WHERE\s+r\.observation_rank\s*=\s*1",
            flags=re.IGNORECASE,
        )
        replacement = (
            "FROM ranked r "
            "CROSS JOIN api_records a "
            "CROSS JOIN source_artifacts sa "
            "WHERE a.api_record_id = r.api_record_id "
            "AND sa.source_artifact_id = a.source_artifact_id "
            "AND r.observation_rank = 1"
        )
        sql, count = join_pattern.subn(replacement, sql)
        if count != 1:
            raise RuntimeError(
                "Unexpected horse_profile_latest join shape; expected one ranked/API/source join"
            )

    if recipe.force_race_api4_join_order:
        join_pattern = re.compile(
            r"FROM\s+jeju_race_population_candidates\s+c\s+"
            r"JOIN\s+api_records\s+a\s+ON\s+a\.api_record_id\s*=\s*c\.api_record_id\s+"
            r"JOIN\s+source_artifacts\s+sa\s+ON\s+sa\.source_artifact_id\s*=\s*a\.source_artifact_id",
            flags=re.IGNORECASE,
        )
        replacement = (
            "FROM jeju_race_population_candidates c "
            "CROSS JOIN api_records a "
            "CROSS JOIN source_artifacts sa "
            "WHERE a.api_record_id = c.api_record_id "
            "AND sa.source_artifact_id = a.source_artifact_id"
        )
        sql, count = join_pattern.subn(replacement, sql)
        if count != 1:
            raise RuntimeError(
                "Unexpected race passing-order join shape; expected one candidate/API/source join"
            )

    if recipe.force_section_source_join_order:
        join_pattern = re.compile(
            r"FROM\s+jeju_race_population_candidates\s+r\s+"
            r"JOIN\s+api_records\s+a\s+ON\s+a\.api_record_id\s*=\s*r\.api_record_id\s+"
            r"JOIN\s+source_artifacts\s+s\s+ON\s+s\.source_artifact_id\s*=\s*a\.source_artifact_id\s+"
            r"CROSS\s+JOIN\s+fields\s+f",
            flags=re.IGNORECASE,
        )
        replacement = (
            "FROM jeju_race_population_candidates r "
            "CROSS JOIN api_records a "
            "CROSS JOIN source_artifacts s "
            "CROSS JOIN fields f"
        )
        sql, count = join_pattern.subn(replacement, sql)
        if count != 1:
            raise RuntimeError(
                "Unexpected section-value join shape; expected one candidate/API/source/fields join"
            )
        review_join = re.compile(
            r"(LEFT\s+JOIN\s+known_reviews\s+k\s+ON\s+"
            r"\(k\.race_date\s*,\s*k\.meet_code\s*,\s*k\.race_number\s*,\s*"
            r"k\.horse_number\s*,\s*k\.horse_id\s*,\s*k\.field_name\)\s*=\s*"
            r"\(r\.race_date\s*,\s*r\.meet_code\s*,\s*r\.race_number\s*,\s*"
            r"r\.horse_number\s*,\s*r\.horse_id\s*,\s*f\.field_name\))",
            flags=re.IGNORECASE,
        )
        sql, count = review_join.subn(
            r"\1 WHERE a.api_record_id = r.api_record_id "
            "AND s.source_artifact_id = a.source_artifact_id",
            sql,
        )
        if count != 1:
            raise RuntimeError(
                "Unexpected section review join shape; could not preserve inner-join predicates"
            )

    for source, target in recipe.identifier_replacements:
        sql = _replace_identifier(sql, source, target)
    # All current clones should read the optimized profile lookup and the
    # current profile analysis projection where those dependencies occur.
    if recipe.target not in {"horse_profile_refresh_current", "horse_current"}:
        sql = _replace_identifier(
            sql, "horse_profile_latest", "horse_profile_refresh_current"
        )
        sql = _replace_identifier(sql, "horse_analysis_2026", "horse_current")

    if recipe.cutoff_predicate is not None:
        occurrences = sql.count(recipe.cutoff_predicate)
        if occurrences != 1:
            raise RuntimeError(
                f"Expected one documented cutoff predicate in {recipe.source}; "
                f"found {occurrences}"
            )
        sql = sql.replace(recipe.cutoff_predicate, "", 1)
        if FIXED_CUTOFF in sql:
            raise RuntimeError(
                f"Unexpected fixed cutoff remains in current view {recipe.target}"
            )

    if recipe.add_current_jeju_profile_filter:
        if re.search(r"\bWHERE\b", sql, flags=re.IGNORECASE):
            raise RuntimeError("Race analysis source gained an unexpected WHERE clause")
        sql = sql.rstrip() + "\nWHERE pc.breed_label_raw = '제주마'"
    return sql


def _canonical_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().rstrip(";").casefold()


def _metadata_view_sql(include_api6: bool, include_api22: bool) -> str:
    rows = [
        row
        for row in _METADATA_ROWS
        if row[0] != "api6_section_records_current" or include_api6
        if row[0] != "starting_training_api_current" or include_api22
    ]
    selects = []
    for index, (view_name, temporal, profile, source) in enumerate(rows):
        prefix = "SELECT" if index == 0 else "UNION ALL SELECT"
        values = tuple("'" + value.replace("'", "''") + "'" for value in (view_name, temporal, profile, source))
        selects.append(
            f"{prefix} {values[0]} AS view_name, {values[1]} AS temporal_scope, "
            f"{values[2]} AS profile_policy, {values[3]} AS source_and_quality_policy"
        )
    return "CREATE VIEW jeju_current_view_metadata AS\n" + "\n".join(selects)


def apply_current_views(conn: sqlite3.Connection) -> list[str]:
    """Create current-scope views inside an existing caller transaction.

    No legacy view is altered or dropped, and this function never commits.  A
    caller must start a transaction first; SQLite DDL can otherwise autocommit
    and make the no-commit contract impossible to guarantee.

    Returns the names created during this call. Existing views with the same
    canonical definition are accepted as an idempotent re-run; mismatched
    objects cause an error and are never replaced.
    """

    if not conn.in_transaction:
        raise RuntimeError(
            "apply_current_views requires an existing caller-owned transaction; "
            "it never begins or commits one"
        )

    fixed_names = {recipe.source for recipe in _RECIPES if recipe.source}
    fixed_before = {
        name: _source_view_sql(conn, name)
        for name in fixed_names
        if name is not None
    }

    conn.execute(f"SAVEPOINT {_SAVEPOINT}")
    created: list[str] = []
    try:
        for recipe in _RECIPES:
            sql = _build_view_sql(conn, recipe)
            if sql is None:
                continue
            existing_type = _object_type(conn, recipe.target)
            if existing_type is not None:
                if existing_type != "view":
                    raise RuntimeError(
                        f"Current view name is occupied by a {existing_type}: {recipe.target}"
                    )
                existing = _source_view_sql(conn, recipe.target)
                if _canonical_sql(existing) != _canonical_sql(sql):
                    raise RuntimeError(
                        f"Existing current view has a different definition: {recipe.target}"
                    )
                continue
            conn.execute(sql)
            created.append(recipe.target)

        metadata_sql = _metadata_view_sql(
            _object_type(conn, "refresh_section_records") is not None,
            _object_type(conn, "refresh_starting_training_api") is not None,
        )
        metadata_type = _object_type(conn, "jeju_current_view_metadata")
        if metadata_type is None:
            conn.execute(metadata_sql)
            created.append("jeju_current_view_metadata")
        elif metadata_type != "view":
            raise RuntimeError(
                "Current metadata view name is occupied by a non-view object"
            )
        elif _canonical_sql(_source_view_sql(conn, "jeju_current_view_metadata")) != _canonical_sql(metadata_sql):
            raise RuntimeError("Existing jeju_current_view_metadata has a different definition")

        fixed_after = {
            name: _source_view_sql(conn, name)
            for name in fixed_before
        }
        if fixed_after != fixed_before:
            raise RuntimeError("Legacy source view definitions changed unexpectedly")
        conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
        return created
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
        conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
        raise


__all__ = ["apply_current_views", "FIXED_CUTOFF"]
