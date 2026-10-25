"""Collect literal day reports, link numbered horses, retain corrections in Supabase.

Dry-run by default. No model calls, external messages, SQLite writes or deletion.
The night scan includes today; the morning scan rechecks through yesterday.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from horse_racing.config import get_settings
from horse_racing.jobs.local_log_rotation import open_regular
from horse_racing.jobs.local_resilience import safe_failure
from horse_racing.jobs.weekly_entry_cards import KST, emit, require_target
from horse_racing.parsers.steward_website import link_fields, parse_day, require

ROOT = Path(__file__).resolve().parents[3]
ENDPOINT = "https://race.kra.co.kr/referee/StewardsReport.do"
PROJECT_REF = "xkykmhhkjtosptoibduo"
LOCK_KEY = 2026101748130
STATE_PATH = ROOT / "data/state/steward-horse-refresh.json"


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def save_json(path, value):
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")


def write_state(value):
    temporary = STATE_PATH.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        json.dump(value, handle, ensure_ascii=False, default=str)
        handle.write("\n")
    temporary.replace(STATE_PATH)


def connect(settings):
    require_target(settings.database_url, PROJECT_REF)
    url = make_url(settings.database_url).set(drivername="postgresql")
    return psycopg.connect(url.render_as_string(hide_password=False), sslmode="require",
                          connect_timeout=20, autocommit=True, row_factory=dict_row)


def fetch(client, *, meet, day, folder):
    params = {"Act": "06", "Sub": "12", "meet": meet, "rcDate": day.strftime("%Y%m%d")}
    requested = time.time_ns() // 1_000_000
    with client.stream("GET", ENDPOINT, params=params) as response:
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            require(size <= 8 * 1024**2, "website_response_too_large")
            chunks.append(chunk)
        body = b"".join(chunks)
        retrieved = time.time_ns() // 1_000_000
        sha = hashlib.sha256(body).hexdigest()
        raw = folder / f"meet_{meet}_{day}_{retrieved}_{sha[:12]}.html"
        with raw.open("xb") as f:
            f.write(body)
        meta = {"source_url": str(response.url), "params": params,
                "requested_at_ms": requested, "retrieved_at_ms": retrieved,
                "http_status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
                "response_bytes": len(body), "local_path": str(raw.relative_to(ROOT)),
                "sha256": sha}
        save_json(raw.with_suffix(".json"), meta)
        require(response.status_code == 200, "website_http_not_200")
        require(response.url.host == "race.kra.co.kr" and response.url.path ==
                "/referee/StewardsReport.do", "unexpected_website_endpoint")
    return body, meta


def store_document(c, meta, run_id):
    return c.execute("""insert into source_documents
        (ingestion_run_id,source_url,endpoint,operation,request_params_json,
         requested_at_ms,retrieved_at_ms,http_status_code,content_type,response_bytes,local_path,sha256)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
        (run_id, meta["source_url"], "/referee/StewardsReport.do", "official_day_report",
         dumps(meta["params"]), meta["requested_at_ms"], meta["retrieved_at_ms"],
         meta["http_status_code"], meta["content_type"], meta["response_bytes"],
         meta["local_path"], meta["sha256"])).fetchone()["id"]


def persist(c, *, race_id, fields, links, review, document_id, observed_ms):
    content = dumps(fields)
    digest = hashlib.sha256(content.encode()).hexdigest()
    with c.transaction():
        c.execute("set local lock_timeout='5s'")
        c.execute("set local statement_timeout='60s'")
        existing = c.execute("""select * from steward_report_versions
            where race_id=%s and content_sha256=%s for update""", (race_id, digest)).fetchone()
        previous = c.execute("""select id from steward_report_versions
            where race_id=%s and is_current for update""", (race_id,)).fetchone()
        created = existing is None
        if created:
            row = c.execute("""insert into steward_report_versions
                (race_id,source_document_id,latest_source_document_id,content_sha256,
                 report_fields_json,review_json,linkage_status,is_current,
                 first_observed_at_ms,last_observed_at_ms)
                values (%s,%s,%s,%s,%s,%s,%s,false,%s,%s) returning id""",
                (race_id, document_id, document_id, digest, content, dumps(review),
                 "needs_review" if review else "linked", observed_ms, observed_ms)).fetchone()
            version_id = row["id"]
        else:
            require(existing["report_fields_json"] == content, "content_hash_collision")
            version_id = existing["id"]
            c.execute("""update steward_report_versions set latest_source_document_id=%s,
                last_observed_at_ms=greatest(last_observed_at_ms,%s) where id=%s""",
                (document_id, observed_ms, version_id))
        if review:
            # Never replace a previously linked snapshot with an unresolved one.
            return {"version_id": version_id, "new_versions": int(created),
                    "inserted_mentions": 0, "current_changed": False, "needs_review": True}
        inserted = 0
        for link in links:
            refs = dumps(link["evidence"])
            cursor = c.execute("""insert into horse_steward_report_mentions
                (report_version_id,horse_id,race_entry_id,horse_number,source_field,
                 span_start_codepoint,span_end_codepoint,paragraph_text,mention_evidence_json)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (report_version_id,horse_id,source_field,span_start_codepoint,span_end_codepoint)
                do nothing""", (version_id, link["horse_id"], link["race_entry_id"],
                                  link["horse_number"], link["source_field"], link["start"],
                                  link["end"], link["paragraph_text"], refs))
            inserted += cursor.rowcount
        saved = c.execute("""select horse_id,race_entry_id,horse_number,source_field,
            span_start_codepoint,span_end_codepoint,paragraph_text,mention_evidence_json
            from horse_steward_report_mentions where report_version_id=%s""", (version_id,)).fetchall()
        expected = {(r["horse_id"], r["race_entry_id"], r["horse_number"], r["source_field"],
                     r["start"], r["end"], r["paragraph_text"], dumps(r["evidence"])) for r in links}
        actual = {tuple(r.values()) for r in saved}
        require(actual == expected and len(saved) == len(links), "mention_readback_mismatch")
        c.execute("update steward_report_versions set is_current=false where race_id=%s and is_current",
                  (race_id,))
        c.execute("""update steward_report_versions set is_current=true,linkage_status='linked',
            review_json='[]' where id=%s""", (version_id,))
        changed = previous is None or previous["id"] != version_id
    return {"version_id": version_id, "new_versions": int(created),
            "inserted_mentions": inserted, "current_changed": changed, "needs_review": False}


def verify(c, version_ids):
    if not version_ids:
        return {"checked_versions": 0, "span_mismatches": 0, "identity_mismatches": 0}
    row = c.execute("""select
        count(*) filter(where m.paragraph_text is distinct from substring(
            v.report_fields_json::jsonb->>m.source_field from m.span_start_codepoint+1
            for m.span_end_codepoint-m.span_start_codepoint)) span_mismatches,
        count(*) filter(where e.id is null or e.race_id<>v.race_id or e.horse_id<>m.horse_id
            or e.horse_number<>m.horse_number) identity_mismatches
        from horse_steward_report_mentions m
        join steward_report_versions v on v.id=m.report_version_id
        left join race_entries e on e.id=m.race_entry_id
        where v.id=any(%s)""", (version_ids,)).fetchone()
    require(row["span_mismatches"] == 0 and row["identity_mismatches"] == 0,
            "post_commit_integrity_failure")
    return {"checked_versions": len(set(version_ids)), **row}


def refresh(settings, *, start, end, now, folder):
    observations, pending, errors, versions = [], [], [], []
    with connect(settings) as c:
        locked = c.execute("select pg_try_advisory_lock(%s) ok", (LOCK_KEY,)).fetchone()["ok"]
        require(locked, "steward_worker_already_running")
        races = c.execute("""select r.id race_id,r.race_date_local as race_day,r.race_number,
            r.scheduled_at_ms,rc.kra_meet_code meet from races r
            join racecourses rc on rc.id=r.racecourse_id
            where r.race_date_local between %s and %s and rc.kra_meet_code in (1,2,3,4)
            order by r.race_date_local,rc.kra_meet_code,r.race_number""", (start, end)).fetchall()
        entries = c.execute("""select e.race_id,e.id entry_id,e.horse_id,e.horse_number,
            h.kra_horse_id,h.name_ko from race_entries e join horses h on h.id=e.horse_id
            join races r on r.id=e.race_id where r.race_date_local between %s and %s""",
            (start, end)).fetchall()
        rosters, groups = defaultdict(list), defaultdict(list)
        for entry in entries:
            rosters[entry["race_id"]].append(entry)
        for race in races:
            groups[(race["race_day"], race["meet"])].append(race)
        began = time.time_ns() // 1_000_000
        run_id = c.execute("""insert into ingestion_runs
            (source,data_type,started_at_ms,status,records_fetched,records_written)
            values ('KRA official day report','horse_steward_refresh',%s,'running',0,0)
            returning id""", (began,)).fetchone()["id"]
        save_json(folder / "plan.json", {"run_id": run_id, "start": start, "end": end,
                                        "race_keys": races})
        with httpx.Client(timeout=30, follow_redirects=False,
                          headers={"User-Agent": "horse-racing-steward-observer/1.0"}) as client:
            for (day, meet), targets in groups.items():
                key = {"day": str(day), "meet": meet}
                if day == now.date() and any((r["scheduled_at_ms"] or 0) >
                                             int(now.timestamp() * 1000) for r in targets):
                    pending.append({**key, "reason": "race_day_not_finished"})
                    continue
                try:
                    body, meta = fetch(client, meet=meet, day=day, folder=folder)
                    doc_id = store_document(c, meta, run_id)
                    reports = parse_day(body, meet=meet, day=day)
                    known = {r["race_number"] for r in targets}
                    require(set(reports) <= known, "website_race_not_in_operational_card")
                    for race in targets:
                        n = race["race_number"]
                        if n not in reports:
                            pending.append({**key, "race": n, "reason": "report_not_published"})
                            continue
                        if not rosters[race["race_id"]]:
                            pending.append({**key, "race": n, "reason": "operational_roster_missing"})
                            continue
                        fields = reports[n]
                        links, review, no_refs = link_fields(fields, rosters[race["race_id"]], day=day)
                        result = persist(c, race_id=race["race_id"], fields=fields, links=links,
                                         review=review, document_id=doc_id,
                                         observed_ms=meta["retrieved_at_ms"])
                        versions.append(result["version_id"])
                        if review:
                            pending.append({**key, "race": n, "reason": "identity_review",
                                            "paragraphs": review})
                        record = {**key, "race": n, "linked_paragraphs": len(links),
                                  "paragraphs_without_horse_reference": no_refs, **result}
                        observations.append(record)
                        emit("horse_steward_race", **record)
                except Exception as exc:
                    error = {**key, **safe_failure(exc)}
                    # Source errors contain fixed internal codes, never remote payloads.
                    if type(exc).__name__ == "StewardSourceError":
                        error["source_check"] = str(exc)
                    errors.append(error)
                    emit("horse_steward_source_failed", **error)
                time.sleep(0.25)
        integrity = verify(c, versions)
        status = "failed" if errors and not observations else "partial" if pending or errors else "completed"
        new = sum(r["inserted_mentions"] for r in observations)
        changed = sum(r["current_changed"] for r in observations)
        summary = {"run_id": run_id, "start": str(start), "end": str(end), "status": status,
                   "races_checked": len(races), "reports_observed": len(observations),
                   "inserted_mentions": new, "current_races_changed": changed,
                   "observations": observations, "pending": pending, "errors": errors,
                   "verification": integrity, "report_path": str((folder / "report.json").relative_to(ROOT))}
        c.execute("""update ingestion_runs set completed_at_ms=%s,status=%s,records_fetched=%s,
            records_written=%s,error_message=%s where id=%s""",
            (time.time_ns() // 1_000_000, status, len(observations), new,
             dumps({"pending": pending, "errors": errors}) if pending or errors else None, run_id))
        save_json(folder / "report.json", summary)
        return summary


def execute(*, apply=False, scheduled=False, through=None, lookback=14, now=None):
    now = now or datetime.now(KST)
    require(1 <= lookback <= 14, "lookback_outside_recent_fourteen_days")
    require(not scheduled or through is None, "scheduled_date_override_forbidden")
    end = through or (now.date() if now.hour >= 21 else now.date() - timedelta(days=1))
    require(now.date() - timedelta(days=13) <= end <= now.date(), "end_outside_recent_fourteen_days")
    start = max(end - timedelta(days=lookback - 1), now.date() - timedelta(days=13))
    emit("horse_steward_plan", start=str(start), end=str(end), apply=apply, scheduled=scheduled)
    if not apply:
        return 0
    lock_path = ROOT / "data/state/steward-horse-refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(open_regular(lock_path, os.O_CREAT | os.O_RDWR), "a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit("horse_steward_busy")
            return 75
        folder = ROOT / f"data/research/horse_steward_refresh_{now:%Y%m%d_%H%M%S}_{time.time_ns()}"
        folder.mkdir(parents=True, mode=0o700)
        try:
            summary = refresh(get_settings(), start=start, end=end, now=now, folder=folder)
        except Exception as exc:
            failure = {"status": "failed", "start": str(start), "end": str(end),
                       **safe_failure(exc), "folder": str(folder.relative_to(ROOT))}
            save_json(folder / "failure.json", failure)
            write_state(failure)
            emit("horse_steward_failed", **failure)
            return 1
        write_state(summary)
        emit("horse_steward_complete", run_id=summary["run_id"], status=summary["status"],
             inserted_mentions=summary["inserted_mentions"], changed=summary["current_races_changed"],
             pending=len(summary["pending"]), errors=len(summary["errors"]),
             report_path=summary["report_path"])
        return 1 if summary["errors"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--through", type=date.fromisoformat)
    parser.add_argument("--lookback", type=int, default=14)
    args = parser.parse_args()
    raise SystemExit(execute(**vars(args)))


if __name__ == "__main__":
    main()
