"""Compare the reviewed database against the pre-review backup, read-only."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "thoroughbred/data/core_api_2010_20260929_v1"
OLD = OUT / "backups/20261001_before_remaining_closure_cancel_review_v3/thoroughbred_core.duckdb"
NEW = OUT / "thoroughbred_core.duckdb"


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def main():
    con = duckdb.connect(str(NEW), read_only=True)
    old_literal = "'" + str(OLD).replace("'", "''") + "'"
    con.execute(f"ATTACH {old_literal} AS prior (READ_ONLY)")
    old_objects = con.execute("SELECT table_name, table_type FROM information_schema.tables "
                              "WHERE table_catalog='prior' AND table_schema='main'").fetchall()
    changed = {"calendar_days", "annual_summary", "race_nonexecution_adjudication",
               "official_closure_intervals", "source_manifests", "race_execution_adjudicated",
               "race_nonexecution_subtype_review"}
    preservation = {}
    for name, kind in old_objects:
        if name in changed:
            continue
        q = identifier(name)
        forward = con.execute(f"SELECT count(*) FROM (SELECT * FROM {q} EXCEPT ALL SELECT * FROM prior.main.{q})").fetchone()[0]
        reverse = con.execute(f"SELECT count(*) FROM (SELECT * FROM prior.main.{q} EXCEPT ALL SELECT * FROM {q})").fetchone()[0]
        preservation[name] = {"kind": kind, "new_only_rows": forward, "old_only_rows": reverse}
    checks = {"all_other_tables_and_views_unchanged": all(
        not r["new_only_rows"] and not r["old_only_rows"] for r in preservation.values())}
    for name in ("calendar_days", "annual_summary", "race_nonexecution_adjudication"):
        q = identifier(name)
        copy = identifier(name + "_prior_review")
        checks[name + "_prior_copy_exact"] = con.execute(
            f"SELECT NOT EXISTS(SELECT * FROM {copy} EXCEPT ALL SELECT * FROM prior.main.{copy}) "
            f"AND NOT EXISTS(SELECT * FROM prior.main.{copy} EXCEPT ALL SELECT * FROM {copy})").fetchone()[0]
    permitted = {"official_closure_reason", "official_closure_source_url", "race_day_status"}
    permitted.update("adjudication_" + s + "_count" for s in (
        "official_day_cancelled", "reported_day_cancelled", "official_closure_nonexecution",
        "race_cancelled", "race_invalid", "reason_recorded_outcome_unclassified"))
    fields = [r[0] for r in con.execute("DESCRIBE calendar_days").fetchall() if r[0] not in permitted]
    columns = ','.join(map(identifier, fields))
    checks["calendar_other_columns_unchanged"] = con.execute(
        f"SELECT NOT EXISTS(SELECT {columns} FROM calendar_days EXCEPT ALL SELECT {columns} FROM prior.main.calendar_days) "
        f"AND NOT EXISTS(SELECT {columns} FROM prior.main.calendar_days EXCEPT ALL SELECT {columns} FROM calendar_days)").fetchone()[0]
    checks["116_keys_verdicts_unchanged"] = con.execute(
        "SELECT NOT EXISTS(SELECT meet,date,race_no,execution_verdict FROM race_nonexecution_adjudication "
        "EXCEPT ALL SELECT meet,date,race_no,execution_verdict FROM prior.main.race_nonexecution_adjudication) "
        "AND (SELECT count(*) FROM race_nonexecution_adjudication)=116").fetchone()[0]
    checks["adjudicated_view_only_two_busan_keys_changed"] = con.execute(
        "WITH changes AS (SELECT * FROM race_execution_adjudicated EXCEPT ALL SELECT * FROM prior.main.race_execution_adjudicated) "
        "SELECT count(*)=2 AND bool_and(meet='3' AND date='20150329' AND race_no IN ('5','6') "
        "AND adjudication_status='race_cancelled') FROM changes").fetchone()[0]
    fields = [r[0] for r in con.execute("DESCRIBE race_nonexecution_adjudication").fetchall()
              if r[0] not in {'adjudication_status','supporting_reason','evidence_files','evidence_urls',
                              'evidence_kind','source_state','verified_date','decision_note'}]
    columns = ','.join(map(identifier, fields))
    checks["adjudication_nonreview_columns_unchanged"] = con.execute(
        f"SELECT NOT EXISTS(SELECT {columns} FROM race_nonexecution_adjudication EXCEPT ALL SELECT {columns} FROM prior.main.race_nonexecution_adjudication) "
        f"AND NOT EXISTS(SELECT {columns} FROM prior.main.race_nonexecution_adjudication EXCEPT ALL SELECT {columns} FROM race_nonexecution_adjudication)").fetchone()[0]
    checks["other_114_adjudications_exact"] = con.execute(
        "SELECT NOT EXISTS(SELECT * FROM race_nonexecution_adjudication WHERE NOT(meet='3' AND date='20150329' AND race_no IN ('5','6')) "
        "EXCEPT ALL SELECT * FROM prior.main.race_nonexecution_adjudication WHERE NOT(meet='3' AND date='20150329' AND race_no IN ('5','6')))").fetchone()[0]
    checks["old_closure_intervals_preserved"] = con.execute(
        "SELECT NOT EXISTS(SELECT * FROM prior.main.official_closure_intervals "
        "EXCEPT ALL SELECT * FROM official_closure_intervals)").fetchone()[0]
    fields = [r[0] for r in con.execute("DESCRIBE annual_summary").fetchall()
              if r[0] != 'official_closure_calendar_days_documented']
    columns = ','.join(map(identifier, fields))
    checks["annual_other_columns_unchanged"] = con.execute(
        f"SELECT NOT EXISTS(SELECT {columns} FROM annual_summary EXCEPT ALL SELECT {columns} FROM prior.main.annual_summary) "
        f"AND NOT EXISTS(SELECT {columns} FROM prior.main.annual_summary EXCEPT ALL SELECT {columns} FROM annual_summary)").fetchone()[0]
    status_counts = dict(con.execute("SELECT adjudication_status,count(*) FROM race_nonexecution_adjudication GROUP BY 1").fetchall())
    checks["review_29_cancelled_zero_unknown"] = dict(con.execute(
        "SELECT reviewed_status,count(*) FROM race_nonexecution_subtype_review GROUP BY 1").fetchall()) == {
            "race_cancelled": 29}
    closure_rows, closure_days, conflicts = con.execute(
        "SELECT (SELECT count(*) FROM official_closure_intervals), "
        "count(*) FILTER(WHERE coalesce(official_closure_source_url,'')<>''), "
        "count(*) FILTER(WHERE coalesce(official_closure_source_url,'')<>'' AND cast(executed_race_count AS INTEGER)>0) "
        "FROM calendar_days").fetchone()
    checks["closures_77_intervals_540_venue_days_no_conflicts"] = (closure_rows, closure_days, conflicts) == (77, 540, 0)
    checks["new_closure_days_exact_90_zero_execution"] = con.execute(
        "WITH changes AS (SELECT n.* FROM calendar_days n JOIN prior.main.calendar_days o USING(meet,date) "
        "WHERE coalesce(n.official_closure_source_url,'')<>coalesce(o.official_closure_source_url,'')) "
        "SELECT count(*)=90 AND bool_and(meet IN ('1','3') AND date BETWEEN '2020-09-01' AND '2020-10-15' "
        "AND cast(executed_race_count AS INTEGER)=0) FROM changes").fetchone()[0]
    checks["two_api_delimited_boundaries_explicit"] = con.execute(
        "SELECT count(*)=2 AND bool_and(end_boundary_method='day_before_first_api_executed_race' "
        "AND end_date='2020-10-15' AND api_resumption_date='2020-10-16' "
        "AND explicit_official_end_notice_found='false') FROM closure_boundary_review").fetchone()[0]
    checks["secondary_leads_not_promoted"] = con.execute(
        "SELECT count(*)=10 AND count(*) FILTER(WHERE cast(api_executed_races AS INTEGER)>0)=3 "
        "AND bool_and(confidence='reported_not_official_original') FROM reported_closure_interval_leads").fetchone()[0]
    checks["no_pre2016_closure_added"] = con.execute(
        "SELECT NOT EXISTS(SELECT * FROM official_closure_intervals WHERE start_date<'2016-01-01' "
        "EXCEPT ALL SELECT * FROM prior.main.official_closure_intervals)").fetchone()[0]
    manifest = json.loads((OUT / "manifest.json").read_text())
    checks["builder_all_checks_pass"] = all(manifest["checks"].values())
    review_manifest=json.loads((HERE / "manifest.json").read_text())
    checks["all_review_evidence_hashes_match"] = all(
        hashlib.sha256((ROOT / r["path"]).read_bytes()).hexdigest()==r["sha256"]
        for r in review_manifest["pinned_files"])
    digest = hashlib.sha256()
    with NEW.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    checks["db_hash_matches_manifest"] = digest.hexdigest() == manifest["database_sha256"]
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "baseline_database": str(OLD.relative_to(ROOT)), "database": str(NEW.relative_to(ROOT)),
              "checks": checks, "all_passed": all(checks.values()),
              "unchanged_objects": preservation, "status_counts": status_counts,
              "closure_intervals": closure_rows, "closure_venue_days": closure_days,
              "builder_check_count": len(manifest["checks"])}
    (HERE / "root_verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    con.close()
    print(json.dumps({k:v for k,v in report.items() if k != 'unchanged_objects'}, ensure_ascii=False, indent=2))
    if not report["all_passed"]:
        raise RuntimeError("Database preservation verification failed")


if __name__ == "__main__":
    main()
