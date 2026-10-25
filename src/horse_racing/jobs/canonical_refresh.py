"""Rolling, audited Supabase refresh; immutable annual imports are never rewritten."""

from __future__ import annotations

import json
import time
from datetime import date

import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from horse_racing.collectors.kra_text import KraTextClient
from horse_racing.jobs import canonical_post_race as core
from horse_racing.jobs.local_race_day import LocalKraApiClient
from horse_racing.parsers.dacom11 import parse_dacom11_report
from horse_racing.parsers.race_supplemental import StewardReportItem


def deltas(old_rows, incoming, keys, fields):
    """Business-key comparison excludes observation/provenance timestamps."""
    prior = {tuple(row[k] for k in keys): row for row in old_rows}
    current = {tuple(row[k] for k in keys): row for row in incoming}
    core.require(len(current) == len(incoming), "duplicate_refresh_key")
    core.require(not (set(prior) - set(current)), "source_removed_existing_rows")
    added, changed, before = [], [], []
    for key, row in current.items():
        old = prior.get(key)
        if old is None:
            added.append(row)
        elif any(old[f] != row[f] for f in fields):
            changed.append(row)
            before.append(dict(old))
    return added, changed, before


SECTION_COLUMNS = (
    "race_entry_id",
    "point_code",
    "time_kind",
    "elapsed_time_ms",
    "position_raw",
    "source_name",
    "source_field",
)
GROUP_COLUMNS = ("race_id", "point_code", "notation_raw")
REPORT_COLUMNS = (
    "meet_code",
    "race_date_local",
    "race_number",
    "weather",
    "members",
    "judgement",
    "additional_judgement",
    "jockey_change_note",
)
DOC_COLUMNS = (
    "source_url",
    "endpoint",
    "operation",
    "request_params_json",
    "requested_at_ms",
    "retrieved_at_ms",
    "http_status_code",
    "content_type",
    "response_bytes",
    "local_path",
    "sha256",
)


def section_scope(snapshot, data, text_races):
    """A whole officially void race may be absent from dacom11; retain its result/raw evidence.

    Code 98 alone is NOT a void-race classification. Require every DB runner's
    explicit official remark and independently matching API4_3 identities/results.
    """
    by_race = {}
    for row in snapshot:
        by_race.setdefault(row["race_number"], []).append(row)
    void = {
        number
        for number, rows in by_race.items()
        if all(
            r["finish_position"] == 98
            and r["finish_time_ms"] is None
            and r.get("rank_remark") == "경주불성립"
            for r in rows
        )
    }
    if not void:
        return snapshot, data, text_races, []
    target = {
        (r["race_number"], r["horse_number"]): r for r in snapshot if r["race_number"] in void
    }
    observed = {}
    for raw in data["sections"]:
        key = (int(raw["rcNo"]), int(raw["chulNo"]))
        if key[0] not in void:
            continue
        core.require(key in target and key not in observed, "void_api_entry_key")
        row = target[key]
        core.require(
            str(raw["hrNo"]).zfill(7) == row["kra_horse_id"].zfill(7)
            and int(raw["rcDist"]) == row["distance_m"]
            and int(raw.get("ord") or 0) == 98
            and core.millis(raw.get("rcTime")) is None,
            "void_api_result_mismatch",
        )
        observed[key] = raw
    core.require(set(observed) == set(target), "void_api_entry_coverage")
    return (
        [r for r in snapshot if r["race_number"] not in void],
        {kind: [r for r in rows if int(r["rcNo"]) not in void] for kind, rows in data.items()},
        [r for r in text_races if r.race_number not in void],
        sorted(void),
    )


def reconcile(connection, artifact, *, sections=True):
    core.require(
        artifact.resolve().is_relative_to((core.ROOT / "data/research").resolve()), "artifact_path"
    )
    source_hash = core.digest_file(artifact)
    batch = json.loads(artifact.read_text())
    for doc in batch["documents"]:
        source = (core.ROOT / doc["local_path"]).resolve()
        core.require(source.is_relative_to(artifact.parent.resolve()), "source_path")
        core.require(core.digest_file(source) == doc["sha256"], "source_hash")
    meet, day = batch["meet"], batch["race_day"]
    now = int(time.time() * 1000)
    result = {
        "meet": meet,
        "day": day,
        "sections_new": 0,
        "sections_changed": 0,
        "groups_new": 0,
        "groups_changed": 0,
        "reports_new": 0,
        "reports_changed": 0,
    }
    with connection.transaction():
        connection.execute("SET LOCAL lock_timeout='5s'")
        connection.execute("SET LOCAL statement_timeout='60s'")
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (26071005,))
        target = [
            r
            for r in connection.execute(core.SNAPSHOT_SQL, (day, day)).fetchall()
            if r["meet"] == meet
        ]
        core.require(target == batch["target_snapshot"], "target_changed_during_refresh")
        new_s, changed_s, before_s, new_g, changed_g, before_g = [], [], [], [], [], []
        if sections:
            prior_s = connection.execute(
                """SELECT s.*, b.source_file AS prior_source_file
                FROM race_section_times s JOIN race_point_source_batches b ON b.id=s.source_batch_id
                JOIN race_entries e ON e.id=s.race_entry_id JOIN races r ON r.id=e.race_id
                JOIN racecourses c ON c.id=r.racecourse_id
                WHERE c.kra_meet_code=%s AND r.race_date_local=%s""",
                (meet, day),
            ).fetchall()
            prior_g = connection.execute(
                """SELECT g.*,b.source_file AS prior_source_file
                FROM race_passing_groups g
                JOIN race_point_source_batches b ON b.id=g.source_batch_id
                JOIN races r ON r.id=g.race_id JOIN racecourses c ON c.id=r.racecourse_id
                WHERE c.kra_meet_code=%s AND r.race_date_local=%s""",
                (meet, day),
            ).fetchall()
            new_s, changed_s, before_s = deltas(
                prior_s,
                [dict(zip(SECTION_COLUMNS, r, strict=True)) for r in batch["sections"]],
                SECTION_COLUMNS[:3],
                SECTION_COLUMNS[3:5],
            )
            new_g, changed_g, before_g = deltas(
                prior_g,
                [dict(zip(GROUP_COLUMNS, r, strict=True)) for r in batch["groups"]],
                GROUP_COLUMNS[:2],
                GROUP_COLUMNS[2:],
            )
            for old in before_s + before_g:
                core.require(
                    old["prior_source_file"].startswith("data/research/score_point_updates_"),
                    "immutable_annual_source_conflict",
                )
        prior_r = connection.execute(
            """SELECT * FROM race_steward_reports
            WHERE meet_code=%s AND race_date_local=%s""",
            (meet, day),
        ).fetchall()
        # Missing delayed reports are not deletions; compare only published race numbers.
        incoming_r = [dict(zip(REPORT_COLUMNS, r, strict=True)) for r in batch["stewards"]]
        for r in incoming_r:
            r["race_date_local"] = date.fromisoformat(r["race_date_local"])
        published = {r["race_number"] for r in incoming_r}
        new_r, changed_r, before_r = deltas(
            [r for r in prior_r if r["race_number"] in published],
            incoming_r,
            REPORT_COLUMNS[:3],
            REPORT_COLUMNS[3:],
        )
        result.update(
            sections_new=len(new_s),
            sections_changed=len(changed_s),
            groups_new=len(new_g),
            groups_changed=len(changed_g),
            reports_new=len(new_r),
            reports_changed=len(changed_r),
        )
        count = sum(result[k] for k in result if k not in ("meet", "day"))
        if not count:
            return dict(result, status="unchanged", run_id=None)
        # Durable before-image is published BEFORE the short DB write transaction commits.
        audit = json.loads(
            json.dumps({"sections": before_s, "groups": before_g, "reports": before_r}, default=str)
        )
        core.write_json(artifact.parent / f"before_{time.time_ns()}.json", audit)
        source_id = None
        if new_s or changed_s or new_g or changed_g:
            source_id = connection.execute(
                """INSERT INTO race_point_source_batches
                (source_file,source_sha256,meet_code,race_year,section_row_count,
                 passing_group_row_count,loaded_at_ms) VALUES (%s,%s,%s,%s,%s,%s,%s)
                RETURNING id""",
                (
                    str(artifact.relative_to(core.ROOT)),
                    source_hash,
                    meet,
                    int(day[:4]),
                    len(batch["sections"]),
                    len(batch["groups"]),
                    now,
                ),
            ).fetchone()["id"]
        with connection.cursor() as cursor:
            if new_s or changed_s:
                cursor.executemany(
                    """INSERT INTO race_section_times
                    (race_entry_id,point_code,time_kind,elapsed_time_ms,position_raw,
                     source_name,source_field,source_batch_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(race_entry_id,point_code,time_kind) DO UPDATE SET
                    elapsed_time_ms=excluded.elapsed_time_ms,position_raw=excluded.position_raw,
                    source_name=excluded.source_name,source_field=excluded.source_field,
                    source_batch_id=excluded.source_batch_id""",
                    [[r[c] for c in SECTION_COLUMNS] + [source_id] for r in new_s + changed_s],
                )
            if new_g or changed_g:
                cursor.executemany(
                    """INSERT INTO race_passing_groups
                    (race_id,point_code,notation_raw,source_batch_id) VALUES (%s,%s,%s,%s)
                    ON CONFLICT(race_id,point_code) DO UPDATE SET
                    notation_raw=excluded.notation_raw,source_batch_id=excluded.source_batch_id""",
                    [[r[c] for c in GROUP_COLUMNS] + [source_id] for r in new_g + changed_g],
                )
            if new_r or changed_r:
                cursor.executemany(
                    """INSERT INTO race_steward_reports
                    (meet_code,race_date_local,race_number,weather,members,judgement,
                     additional_judgement,jockey_change_note,observed_at_ms)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(meet_code,race_date_local,race_number) DO UPDATE SET
                    weather=excluded.weather,members=excluded.members,judgement=excluded.judgement,
                    additional_judgement=excluded.additional_judgement,
                    jockey_change_note=excluded.jockey_change_note,observed_at_ms=excluded.observed_at_ms""",
                    [[r[c] for c in REPORT_COLUMNS] + [now] for r in new_r + changed_r],
                )
            run_id = connection.execute(
                """INSERT INTO ingestion_runs
                (source,data_type,started_at_ms,completed_at_ms,status,records_fetched,records_written)
                VALUES ('KRA API + official dacom11','canonical_post_race_refresh',%s,%s,
                'completed',%s,%s) RETURNING id""",
                (now, int(time.time() * 1000), len(target), count),
            ).fetchone()["id"]
            cursor.executemany(
                """INSERT INTO source_documents
                (ingestion_run_id,source_url,endpoint,operation,request_params_json,
                 requested_at_ms,retrieved_at_ms,http_status_code,content_type,response_bytes,
                 local_path,sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [[run_id] + [d[c] for c in DOC_COLUMNS] for d in batch["documents"]],
            )
        # Verify every incoming business value before committing the transaction.
        checks = [
            (
                incoming_r,
                REPORT_COLUMNS[:3],
                REPORT_COLUMNS,
                connection.execute(
                    "SELECT * FROM race_steward_reports WHERE meet_code=%s AND race_date_local=%s",
                    (meet, day),
                ).fetchall(),
            )
        ]
        if sections:
            checks.extend(
                [
                    (
                        new_s + changed_s,
                        SECTION_COLUMNS[:3],
                        SECTION_COLUMNS,
                        connection.execute(
                            """SELECT s.* FROM race_section_times s
                         JOIN race_entries e ON e.id=s.race_entry_id
                         JOIN races r ON r.id=e.race_id
                         JOIN racecourses c ON c.id=r.racecourse_id
                         WHERE c.kra_meet_code=%s AND r.race_date_local=%s""",
                            (meet, day),
                        ).fetchall(),
                    ),
                    (
                        new_g + changed_g,
                        GROUP_COLUMNS[:2],
                        GROUP_COLUMNS,
                        connection.execute(
                            """SELECT g.* FROM race_passing_groups g
                         JOIN races r ON r.id=g.race_id
                         JOIN racecourses c ON c.id=r.racecourse_id
                         WHERE c.kra_meet_code=%s AND r.race_date_local=%s""",
                            (meet, day),
                        ).fetchall(),
                    ),
                ]
            )
        for rows, keys, columns, saved in checks:
            indexed = {tuple(r[k] for k in keys): r for r in saved}
            for row in rows:
                actual = indexed.get(tuple(row[k] for k in keys))
                core.require(
                    actual is not None and all(actual[c] == row[c] for c in columns),
                    "refresh_readback_mismatch",
                )
    return dict(result, status="completed", run_id=run_id)


def refresh(settings, *, start, end, directory):
    url = make_url(settings.database_url).set(drivername="postgresql")
    results, pending, errors = [], [], []
    observed_documents = []
    started = int(time.time() * 1000)
    with (
        psycopg.connect(
            url.render_as_string(hide_password=False), autocommit=True, row_factory=dict_row
        ) as connection,
        LocalKraApiClient(settings.data_go_kr_service_key.get_secret_value()) as api,
        KraTextClient() as text_client,
    ):
        target = connection.execute(core.SNAPSHOT_SQL, (start, end)).fetchall()
        feeds = {}
        for meet, day in sorted({(r["meet"], r["race_day"]) for r in target}):
            subset = [r for r in target if r["meet"] == meet and r["race_day"] == day]
            folder = directory / f"{meet}_{day}"
            folder.mkdir()
            try:
                data, docs = {}, []
                data["stewards"], docs = core.fetch_api(api, "stewards", meet, day, folder)
                observed_documents.extend(docs)
                reports, seen = [], set()
                expected = {r["race_number"] for r in subset}
                for raw in data["stewards"]:
                    item = StewardReportItem.model_validate(raw)
                    core.require(
                        item.race_number in expected and item.race_number not in seen,
                        "steward_race_key",
                    )
                    core.require(bool(item.judgement), "empty_steward")
                    seen.add(item.race_number)
                    reports.append(
                        [
                            meet,
                            day,
                            item.race_number,
                            item.weather,
                            item.members,
                            item.judgement,
                            item.additional_judgement,
                            item.jockey_change_note,
                        ]
                    )
                base = {
                    "meet": meet,
                    "race_day": day,
                    "target_snapshot": subset,
                    "stewards": reports,
                    "sections": [],
                    "groups": [],
                    "documents": docs,
                }
                report_path = folder / "reports.json"
                core.write_json(report_path, base)
                results.append(reconcile(connection, report_path, sections=False))
                if seen != expected:
                    pending.append(
                        {
                            "meet": meet,
                            "day": day,
                            "kind": "stewards_not_published",
                            "races": sorted(expected - seen),
                        }
                    )
            except core.SourceMismatch as exc:
                pending.append(
                    {"meet": meet, "day": day, "stage": "stewards", "kind": str(exc)[:160]}
                )
                data, docs = {"stewards": []}, []
            except Exception as exc:
                errors.append(
                    {"meet": meet, "day": day, "stage": "stewards", "type": type(exc).__name__}
                )
                data, docs = {"stewards": []}, []
            try:
                for kind in ("sections", "groups", "race_detail"):
                    data[kind], new_docs = core.fetch_api(api, kind, meet, day, folder)
                    docs.extend(new_docs)
                    observed_documents.extend(new_docs)
                feed = 3 if meet == 4 else meet
                if feed not in feeds:
                    feeds[feed] = list(
                        text_client.iter_files(
                            meet=feed,
                            file_type="dacom11",
                            code_name="경마성적표",
                            start_date=start,
                            end_date=end,
                        )
                    )
                files = [f for f in feeds[feed] if str(f.file_date) == day]
                core.require(len(files) == 1, "text_not_published")
                fetched = text_client.fetch_file(files[0])
                text_doc = core.document(fetched, folder / "dacom11.rpt")
                docs.append(text_doc)
                observed_documents.append(text_doc)
                scoped_target, scoped_data, scoped_text, void_races = section_scope(
                    subset, data, parse_dacom11_report(fetched.body)
                )
                normalized = core.normalize_day(
                    meet,
                    day,
                    scoped_target,
                    scoped_data,
                    scoped_text,
                    require_stewards=False,
                )
                # Reconciliation still verifies the FULL immutable observation of this day.
                normalized["target_snapshot"] = subset
                normalized["excluded_void_races"] = void_races
                normalized["documents"] = docs
                path = folder / "canonical.json"
                core.write_json(path, normalized)
                results.append(reconcile(connection, path))
            except core.SourceMismatch as exc:
                # Fixed internal validation reasons only, never raw credential-bearing errors.
                pending.append({"meet": meet, "day": day, "kind": str(exc)[:160]})
            except Exception as exc:
                errors.append({"meet": meet, "day": day, "type": type(exc).__name__})
        status = "failed" if errors else "partial" if pending else "completed"
        # A zero-change scan must still be visible in the operational execution ledger.
        with connection.transaction():
            scan_id = connection.execute(
                """INSERT INTO ingestion_runs
                (source,data_type,started_at_ms,completed_at_ms,status,records_fetched,
                 records_written,error_message) VALUES
                ('KRA API + official dacom11','canonical_post_race_scan',%s,%s,%s,%s,%s,%s)
                RETURNING id""",
                (
                    started,
                    int(time.time() * 1000),
                    status,
                    len(target),
                    sum(
                        r.get(k, 0)
                        for r in results
                        for k in (
                            "sections_new",
                            "sections_changed",
                            "groups_new",
                            "groups_changed",
                            "reports_new",
                            "reports_changed",
                        )
                    ),
                    json.dumps({"pending": pending, "errors": errors}, ensure_ascii=False)
                    if pending or errors
                    else None,
                ),
            ).fetchone()["id"]
            unique_docs = {(d["source_url"], d["sha256"]): d for d in observed_documents}
            if unique_docs:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO source_documents
                        (ingestion_run_id,source_url,endpoint,operation,request_params_json,
                         requested_at_ms,retrieved_at_ms,http_status_code,content_type,
                         response_bytes,local_path,sha256)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        [[scan_id] + [d[c] for c in DOC_COLUMNS] for d in unique_docs.values()],
                    )
    summary = {
        "run_id": scan_id,
        "start": str(start),
        "end": str(end),
        "target_races": len({r["race_id"] for r in target}),
        "target_runners": len(target),
        "documents": len(unique_docs),
        "results": results,
        "pending": pending,
        "errors": errors,
        "status": "failed" if errors else "partial" if pending else "completed",
    }
    core.write_json(directory / "report.json", summary)
    return summary
