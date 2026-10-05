"""Load reviewed role exceptions without changing the API source tables."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REVIEW = ROOT / "thoroughbred/research/20261001_role_review_v1"
ERROR_REVIEW = ROOT / "thoroughbred/research/20261001_trial_22_profile_absence_review_v1"
TABLES = {
    "race_trainer_owner_review": REVIEW / "race_role_review.csv",
    "trial_trainer_review": REVIEW / "trial_trainer_review.csv",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_role_reviews() -> dict:
    manifest = json.loads((REVIEW / "manifest.json").read_text(encoding="utf-8"))
    if not all(manifest["checks"].values()):
        raise ValueError("Role review normalization checks failed")
    for filename, record in manifest["files"].items():
        path = (ROOT / filename).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path) != record["sha256"]:
            raise ValueError(f"Role review evidence changed: {filename}")
    for table, path in TABLES.items():
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != manifest["counts"][table]:
            raise ValueError(f"Role review row count changed: {table}")
    return manifest


def verify_source_error_decisions() -> None:
    manifest = json.loads((ERROR_REVIEW / "resolution_manifest.json").read_text(encoding="utf-8"))
    if manifest["rows"] != 22 or manifest["cause_status"] != "unknown":
        raise ValueError("Unexpected source-error disposition scope")
    for record in manifest["pinned_files"]:
        path = (ROOT / record["path"]).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path) != record["sha256"]:
            raise ValueError("Changed source-error disposition evidence")


def load_role_reviews(connection, inputs: list, counts: dict) -> dict:
    manifest = verify_role_reviews()
    for table, path in TABLES.items():
        # Table identifiers are fixed constants. File paths are query parameters.
        connection.execute(
            f"CREATE TABLE {table} AS SELECT * FROM read_csv(?, header=true, all_varchar=true)",
            [str(path)],
        )
        counts[table] = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        inputs.append({"table": table, "path": path.relative_to(ROOT).as_posix(),
                       "sha256": sha(path), "rows": counts[table]})
        audit_paths = connection.execute(
            f"SELECT DISTINCT audit_source_file FROM {table}"
        ).fetchall()
        if len(audit_paths) != 1:
            raise ValueError(f"Expected one pinned audit ledger for {table}")
        audit = (ROOT / audit_paths[0][0]).resolve()
        if not audit.is_relative_to(ROOT.resolve()):
            raise ValueError("Audit ledger escaped repository")
        evidence_table = table + "_evidence"
        connection.execute(
            f"CREATE TABLE {evidence_table} AS SELECT * FROM read_json_auto(?, format='newline_delimited')",
            [str(audit)],
        )
        counts[evidence_table] = connection.execute(f"SELECT count(*) FROM {evidence_table}").fetchone()[0]
        inputs.append({"table": evidence_table, "path": audit.relative_to(ROOT).as_posix(),
                       "sha256": sha(audit), "rows": counts[evidence_table]})
    connection.execute("""
        CREATE VIEW confirmed_runners_entity_reviewed AS
        SELECT r.* EXCLUDE(trainer_entity_id_with_review, owner_entity_id_with_review),
            w.review_status AS trainer_owner_exception_review_status,
            w.trainer_exception_class,
            w.verified_trainer_id AS official_web_trainer_id_supplement,
            w.verified_owner_id AS official_web_owner_id_supplement,
            coalesce(nullif(r.trainer_name_raw, ''), r.reviewed_trainer_name,
                w.verified_trainer_name) AS trainer_name_with_review,
            coalesce(nullif(r.owner_name_raw, ''), r.reviewed_owner_name,
                w.verified_owner_name) AS owner_name_with_review,
            coalesce(r.trainer_entity_id_with_review, w.verified_trainer_id)
                AS trainer_entity_id_with_review,
            coalesce(r.owner_entity_id_with_review, w.verified_owner_id)
                AS owner_entity_id_with_review
        FROM confirmed_runners_entity_reviewed_before_role_review r
        LEFT JOIN race_trainer_owner_review w
          ON w.meet=r.source_meet AND w.date=r.result_date
         AND w.race_no=r.result_race_no AND w.horse_program_no=r.horse_program_no_raw
         AND w.horse_id=r.horse_id_raw
    """)
    connection.execute("""
        CREATE VIEW trial_participants_entity_reviewed AS
        SELECT p.*, coalesce(e.review_status, w.review_status) AS trainer_exception_review_status,
            coalesce(e.trainer_exception_class, w.trainer_exception_class) AS trainer_exception_class,
            w.verified_trainer_id AS official_web_trainer_id_supplement,
            coalesce(nullif(nullif(p.api_trName, ''), '-'), w.verified_trainer_name)
                AS trainer_name_with_review,
            coalesce(p.trainer_entity_id, w.verified_trainer_id)
                AS trainer_entity_id_with_review
        FROM trial_participants_entity_reviewed_before_role_review p
        LEFT JOIN trial_trainer_review w USING(participant_row_id)
        LEFT JOIN trial_trainer_source_error_decisions e USING(participant_row_id)
    """)
    connection.execute("""
        CREATE VIEW role_link_exceptions_current AS
        SELECT 'race' AS event_type, source_meet AS meet, result_date AS date,
            result_race_no AS event_no, horse_program_no_raw AS horse_program_no,
            horse_id_raw AS horse_id, horse_name_raw AS horse_name,
            'trainer' AS entity_type, trainer_id_raw AS source_id,
            trainer_name_raw AS source_name, trainer_exception_class,
            trainer_owner_exception_review_status AS review_status
        FROM confirmed_runners_entity_reviewed WHERE trainer_entity_id_with_review IS NULL
        UNION ALL
        SELECT 'trial', source_meet_query, api_trainDate, api_trainNo, api_chulNo,
            resolved_horse_id, resolved_horse_name, 'trainer', api_trNo, api_trName,
            trainer_exception_class, trainer_exception_review_status
        FROM trial_participants_entity_reviewed WHERE trainer_entity_id_with_review IS NULL
    """)
    counts["role_link_exceptions_current"] = connection.execute(
        "SELECT count(*) FROM role_link_exceptions_current"
    ).fetchone()[0]
    connection.execute("CREATE VIEW role_link_exceptions_pending AS "
                       "SELECT * FROM role_link_exceptions_current "
                       "WHERE trainer_exception_class='unresolved_no_exact_official_person_id'")
    connection.execute("CREATE VIEW trial_trainer_errors_closed AS "
                       "SELECT * FROM trial_trainer_source_error_decisions")
    counts["role_link_exceptions_pending"] = connection.execute(
        "SELECT count(*) FROM role_link_exceptions_pending").fetchone()[0]
    counts["trial_trainer_errors_closed"] = connection.execute(
        "SELECT count(*) FROM trial_trainer_errors_closed").fetchone()[0]
    checks = {
        "role_review_race_exact_targets": connection.execute("""
            SELECT count(*)=60 AND count(DISTINCT w.meet||'|'||w.date||'|'||w.race_no||'|'||
                w.horse_program_no||'|'||w.horse_id)=60
                AND count(r.source_file)=60
                AND count(*) FILTER(WHERE r.trainer_entity_id_with_review IS NULL)=60
            FROM race_trainer_owner_review w
            LEFT JOIN confirmed_runners_entity_reviewed_before_role_review r
              ON w.meet=r.source_meet AND w.date=r.result_date
             AND w.race_no=r.result_race_no AND w.horse_program_no=r.horse_program_no_raw
             AND w.horse_id=r.horse_id_raw
        """).fetchone()[0],
        "role_review_trial_exact_targets": connection.execute("""
            SELECT count(*)=224 AND count(DISTINCT w.participant_row_id)=224
                AND count(*) FILTER(WHERE p.participant_row_id IS NOT NULL
                    AND p.trainer_entity_id IS NULL AND w.meet=p.source_meet_query
                    AND w.date=p.api_trainDate AND w.trial_no=p.api_trainNo
                    AND w.horse_program_no=p.api_chulNo AND w.horse_id=p.resolved_horse_id)=224
            FROM trial_trainer_review w
            LEFT JOIN trial_participants_entity_linked p USING(participant_row_id)
        """).fetchone()[0],
        "role_review_no_placeholder_person_link": connection.execute("""
            SELECT
              (SELECT count(*) FROM confirmed_runners_entity_reviewed
               WHERE trainer_id_raw='0AAAAA' AND trainer_entity_id_with_review IS NOT NULL)=0
              AND (SELECT count(*) FROM trial_participants_entity_reviewed
               WHERE api_trNo='0AAAAA' AND trainer_entity_id_with_review IS NOT NULL)=0
        """).fetchone()[0],
        "role_review_join_cardinality": connection.execute("""
            SELECT (SELECT count(*) FROM confirmed_runners_entity_reviewed)=330465
              AND (SELECT count(*) FROM trial_participants_entity_reviewed)=61777
        """).fetchone()[0],
        "role_review_current_exception_partition": connection.execute("""
            SELECT count(*)=186
              AND count(*) FILTER(WHERE trainer_exception_class='confirmed_non_person_placeholder')=164
              AND count(*) FILTER(WHERE trainer_exception_class='source_error_unknown_cause'
                  AND review_status='closed_user_accepted_source_error')=22
            FROM role_link_exceptions_current
        """).fetchone()[0],
        "role_source_error_decisions_exact_original_22": connection.execute("""
            SELECT count(*)=22 AND count(DISTINCT e.participant_row_id)=22
              AND count(*) FILTER(WHERE w.trainer_exception_class='unresolved_no_exact_official_person_id'
                  AND w.meet=e.meet AND w.date=e.date AND w.trial_no=e.trial_no
                  AND w.horse_program_no=e.horse_program_no AND w.horse_id=e.horse_id)=22
            FROM trial_trainer_source_error_decisions e
            LEFT JOIN trial_trainer_review w USING(participant_row_id)
        """).fetchone()[0],
        "role_source_error_disposition_keeps_missing_id": connection.execute("""
            SELECT count(*)=22 AND count(*) FILTER(WHERE p.trainer_entity_id_with_review IS NULL
                AND p.api_trNo='-' AND p.api_trName='-'
                AND p.trainer_exception_class='source_error_unknown_cause'
                AND e.affected_fields='trainer_id,trainer_name'
                AND e.cause_status='unknown' AND e.record_validity='not_determined')=22
            FROM trial_trainer_source_error_decisions e
            JOIN trial_participants_entity_reviewed p USING(participant_row_id)
        """).fetchone()[0],
    }
    for table, role, expected in (
        ("race_trainer_owner_review", "trainer", manifest["counts"]["race_new_trainer_ids"]),
        ("race_trainer_owner_review", "owner", manifest["counts"]["race_new_owner_ids"]),
        ("trial_trainer_review", "trainer", manifest["counts"]["trial_new_trainer_ids"]),
    ):
        id_column = f"verified_{role}_id"
        checks[f"role_review_{table}_{role}_coverage"] = connection.execute(
            f"SELECT count({id_column})=? FROM {table}", [expected]
        ).fetchone()[0]
        checks[f"role_review_{table}_{role}_known_ids"] = connection.execute(
            f"SELECT count(*)=0 FROM {table} w WHERE w.{id_column} IS NOT NULL "
            "AND NOT EXISTS(SELECT 1 FROM entity_reference_roster r WHERE "
            f"r.entity_type=? AND r.entity_id_official_string=w.{id_column})", [role]
        ).fetchone()[0]
    if not all(checks.values()):
        raise ValueError(f"Role review DB checks failed: {checks}")
    return checks
