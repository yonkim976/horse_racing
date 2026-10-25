"""Laptop-only closing dividends and recent result repair. Dry-run by default.

Uses the existing Supabase project; does not sync SQLite, predict or deploy.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import time
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import FINAL_DIVIDEND_ENDPOINT, FINAL_DIVIDEND_OPERATION
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import IngestionRun, SourceDocument
from horse_racing.jobs import local_race_day as live
from horse_racing.jobs.local_log_rotation import open_regular
from horse_racing.jobs.local_resilience import (
    connect_local_database,
    release_database_locks,
    safe_failure,
)
from horse_racing.jobs.weekly_entry_cards import KST, emit, require_complete_pages
from horse_racing.parsers.race_day import FinalDividendItem, parse_items
from horse_racing.services import closing_dividends as dividends
from horse_racing.services.discord_notifications import notification_failure, send_discord
from horse_racing.services.live_race_day import (
    apply_items,
    entry_index,
    load_races,
    race_has_complete_results,
    refresh_completion,
    validate_items,
)
from horse_racing.services.raw_store import store_kra_page

ROOT = live.ROOT
STATE_PATH = ROOT / "data/state/local-post-race.json"
REPAIR_STATUS_PATH = ROOT / "data/state/local-post-race-repair-status.json"


def write_execution_state(path, state, mode):
    live.write_state(path, state)
    if mode == "repair":
        # Frequent dividend ticks must not erase a failed daily repair or its alert.
        live.write_state(
            REPAIR_STATUS_PATH,
            {
                k: state[k]
                for k in (
                    "last_summary",
                    "last_failure",
                    "last_notification_summary",
                    "notification",
                )
                if k in state
            },
        )


def plan(*, mode, end, now, lookback):
    if mode not in {"dividends", "repair"} or not 1 <= lookback <= 7:
        raise ValueError("invalid_post_race_plan")
    if not now.date() - timedelta(days=6) <= end <= now.date():
        raise ValueError("post_race_date_outside_recent_seven_days")
    start = (
        end
        if mode == "dividends"
        else max(end - timedelta(days=lookback - 1), now.date() - timedelta(days=6))
    )
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def result_state(races):
    state = {}
    for race in races:
        for entry in race.entries:
            r = entry.result
            state[entry.id] = {
                "race": race.race_number,
                "horse_number": entry.horse_number,
                "finish": r.finish_position if r else None,
                "time_ms": r.finish_time_ms if r else None,
                "margin": r.margin_text if r else None,
                "remark": r.rank_remark if r else None,
                "prize": r.prize_money_krw if r else None,
                "bonus": r.bonus_prize_money_krw if r else None,
                "rating": entry.rating,
                "weight": entry.body_weight_kg,
                "weight_delta": entry.body_weight_change_kg,
                "weather": race.weather,
                "track": race.track_condition,
                "moisture": race.track_moisture_percent,
                "actual_start": race.actual_start_at_ms,
                "start_reason": race.start_time_change_reason,
                "race_status": race.status,
            }
    return state


def save_evidence(session, pages, *, run_id, key, state, raw_dir, day, meet, kind):
    digest = hashlib.sha256(b"".join(p.body for p in pages)).hexdigest()
    if state.get("hashes", {}).get(key) == digest:
        return digest
    for page in pages:
        stored = store_kra_page(
            page,
            raw_data_dir=raw_dir,
            data_type=f"post_race_{kind}",
            race_date=day.strftime("%Y%m%d"),
            meet=meet,
            run_id=run_id,
            page_no=int(page.public_params["pageNo"]),
        )
        session.add(
            SourceDocument(
                ingestion_run_id=run_id,
                endpoint=page.endpoint,
                operation=page.operation,
                source_url=page.source_url,
                request_params_json=json.dumps(page.public_params, sort_keys=True),
                requested_at_ms=page.requested_at_ms,
                retrieved_at_ms=page.retrieved_at_ms,
                http_status_code=page.status_code,
                content_type=page.content_type,
                response_bytes=len(page.body),
                local_path=str(stored.path),
                sha256=stored.sha256,
            )
        )
    return digest


def fetch(client, kind, day, meet):
    if kind == "dividends":
        endpoint, operation, model = (
            FINAL_DIVIDEND_ENDPOINT,
            FINAL_DIVIDEND_OPERATION,
            FinalDividendItem,
        )
        params = {"meet": meet, "rc_date": day.strftime("%Y%m%d"), "_type": "json"}
        page_size = 20000
    else:
        endpoint, operation, model = live.STAGES[kind]
        params = {"rccrs_cd": meet, "race_dt": day.strftime("%Y%m%d"), "_type": "json"}
        page_size = 1000
    pages = list(
        client.iter_pages(
            endpoint=endpoint, operation=operation, public_params=params, page_size=page_size
        )
    )
    items = [i for page in pages for i in parse_items(page.payload, model)]
    require_complete_pages(pages, len(items))
    return pages, items


def result_stage(session, *, pages, items, kind, day, meet):
    races = [r for r in load_races(session, day) if r.racecourse.kra_meet_code == meet]
    entries = entry_index(races)
    items = validate_items(items, kind=kind, day=day, meet=meet, entries=entries)
    before = result_state(races)
    apply_items(
        session,
        kind=kind,
        items=items,
        entries=entries,
        observed_ms=max(p.retrieved_at_ms for p in pages),
    )
    refresh_completion(races)
    session.flush()
    after = result_state(races)
    # Verify published result values before commit; API155 never rewrites existing results.
    for item in items:
        entry = entries[(meet, item.race_number, item.horse_id)]
        if item.finish_position is not None:
            row = entry.result
            if row is None or (kind == "details" and row.finish_position != item.finish_position):
                raise ValueError("result_post_write_rank_mismatch")
            if (
                kind == "details"
                and item.finish_time_ms is not None
                and (row.finish_time_ms != item.finish_time_ms)
            ):
                raise ValueError("result_post_write_time_mismatch")
    changes = [
        {"entry_id": k, "before": before[k], "after": after[k]}
        for k in before
        if before[k] != after[k]
    ]
    published = {(i.race_number, i.horse_id) for i in items if i.finish_position is not None}
    return {
        "changed_entries": len(changes),
        "changes": changes,
        "uncovered_source_entries": sum(
            (r.race_number, e.horse.kra_horse_id) not in published
            for r in races
            for e in r.entries
            if not e.scratched
        ),
    }


def collect(session, client, *, days, mode, now, state, state_path, raw_dir):
    run = IngestionRun(
        source="laptop/post-race/v1",
        data_type=f"local_post_race_{mode}",
        started_at_ms=time.time_ns() // 1_000_000,
        status="running",
    )
    session.add(run)
    session.commit()
    run_id = run.id
    observations, errors, pending, audit = [], [], [], []
    for day in days:
        races = load_races(session, day)
        meets = sorted({r.racecourse.kra_meet_code for r in races})
        for meet in meets:
            venue = [r for r in races if r.racecourse.kra_meet_code == meet]
            if day == now.date() and not any(
                r.scheduled_at_ms and r.scheduled_at_ms <= int(now.timestamp() * 1000)
                for r in venue
            ):
                continue
            stages = ("results", "details", "dividends") if mode == "repair" else ("dividends",)
            for kind in stages:
                if kind == "dividends":
                    venue = [
                        r for r in load_races(session, day) if r.racecourse.kra_meet_code == meet
                    ]
                    if not any(dividends.settled(r) for r in venue):
                        continue
                key = f"{day}:{meet}:{kind}"
                session.rollback()  # API requests hold no write transaction.
                try:
                    pages, items = fetch(client, kind, day, meet)
                    if kind == "dividends":
                        venue = [
                            r
                            for r in load_races(session, day)
                            if r.racecourse.kra_meet_code == meet
                        ]
                        ready, expected, zeros, missing = dividends.prepare(
                            items, day=day, meet=meet, races=venue
                        )
                        result = dividends.reconcile(
                            session,
                            ready=ready,
                            expected=expected,
                            zeros=zeros,
                            observed_ms=max(p.retrieved_at_ms for p in pages),
                        )
                        result["ready_races"] = len(ready)
                        result["pending_races"] = missing
                        pending.extend(
                            {"day": str(day), "meet": meet, "race": n, "kind": kind}
                            for n in missing
                        )
                    else:
                        result = result_stage(
                            session, pages=pages, items=items, kind=kind, day=day, meet=meet
                        )
                    if kind == "details" and result["uncovered_source_entries"]:
                        pending.append(
                            {
                                "day": str(day),
                                "meet": meet,
                                "kind": "details_source",
                                "uncovered_entries": result["uncovered_source_entries"],
                            }
                        )
                    digest = save_evidence(
                        session,
                        pages,
                        run_id=run_id,
                        key=key,
                        state=state,
                        raw_dir=raw_dir,
                        day=day,
                        meet=meet,
                        kind=kind,
                    )
                    changes = result.pop("changes", [])
                    if changes:
                        # Preserve old values before committing their replacements.
                        live.write_state(
                            ROOT / f"data/state/post-race-change-{run_id}-{day}-{meet}-{kind}.json",
                            {"day": str(day), "meet": meet, "stage": kind, "changes": changes},
                        )
                    session.commit()
                    # Re-read committed dividend values as an independent persistence check.
                    if kind == "dividends":
                        stored = dividends.read_existing(session, ready)
                        if any(
                            k not in stored or abs(stored[k][1] - v) > 1e-8
                            for k, v in expected.items()
                        ):
                            raise ValueError("dividend_post_commit_mismatch")
                    elif changes:
                        session.expire_all()
                        committed = result_state(
                            [
                                r
                                for r in load_races(session, day)
                                if r.racecourse.kra_meet_code == meet
                            ]
                        )
                        if any(committed.get(c["entry_id"]) != c["after"] for c in changes):
                            raise ValueError("result_post_commit_mismatch")
                    if changes:
                        audit.append(
                            {"day": str(day), "meet": meet, "stage": kind, "changes": changes}
                        )
                    state.setdefault("hashes", {})[key] = digest
                    live.write_state(state_path, state)
                    row = {
                        "day": str(day),
                        "meet": meet,
                        "stage": kind,
                        "rows": len(items),
                        **result,
                    }
                    observations.append(row)
                    emit("post_race_stage_complete", **row)
                except Exception as exc:
                    session.rollback()
                    error = {
                        "day": str(day),
                        "meet": meet,
                        "stage": kind,
                        "type": type(exc).__name__,
                        **safe_failure(exc),
                    }
                    errors.append(error)
                    emit("post_race_stage_failed", **error)
            if mode == "repair":
                venue = [r for r in load_races(session, day) if r.racecourse.kra_meet_code == meet]
                pending.extend(
                    {"day": str(day), "meet": meet, "race": r.race_number, "kind": "results"}
                    for r in venue
                    if not race_has_complete_results(r)
                    and (day < now.date() or (r.scheduled_at_ms or 0) < int(now.timestamp() * 1000))
                )
    run = session.get(IngestionRun, run_id)
    run.status = (
        "failed" if errors and not observations else "partial" if errors or pending else "completed"
    )
    run.completed_at_ms = time.time_ns() // 1_000_000
    run.records_fetched = sum(o["rows"] for o in observations)
    run.records_written = sum(
        o.get("changed_entries", 0) + o.get("inserted", 0) + o.get("updated", 0)
        for o in observations
    )
    run.error_message = (
        json.dumps({"errors": errors, "pending": pending}) if errors or pending else None
    )
    session.commit()
    summary = {
        "run_id": run_id,
        "mode": mode,
        "start": str(days[0]),
        "end": str(days[-1]),
        "status": run.status,
        "observations": observations,
        "errors": errors,
        "pending": pending,
        "elapsed_seconds": round((run.completed_at_ms - run.started_at_ms) / 1000, 2),
    }
    live.write_state(
        ROOT / f"data/state/post-race-audit-{run_id}.json", {"summary": summary, "audit": audit}
    )
    return summary


def notify(settings, summary, *, scheduled):
    rows = summary["observations"]
    inserted = sum(r.get("inserted", 0) for r in rows)
    updated = sum(r.get("updated", 0) for r in rows)
    repaired = sum(r.get("changed_entries", 0) for r in rows)
    if (
        scheduled
        and summary["mode"] == "dividends"
        and not (inserted or updated or summary["errors"])
    ):
        return {"status": "skipped"}
    content = (
        f"경마 사후 수집 {summary['mode']} · {summary['status']}\n"
        f"{summary['start']}~{summary['end']}\n"
        f"배당 신규 {inserted:,} / 수정 {updated:,}행, 결과 등 변경 {repaired}행\n"
        f"미완료 {len(summary['pending'])}건 / 오류 {len(summary['errors'])}건\n"
        f"실행 {summary['run_id']} · {summary['elapsed_seconds']}초"
    )
    for error in summary["errors"][:4]:
        content += (
            f"\n오류: {error.get('error_type', error.get('type', 'UnknownError'))}"
            f" / {error.get('error_reason', 'unclassified')}"
        )
    try:
        message_id = send_discord(settings.discord_webhook_url, content)
        emit("post_race_discord_sent", message_id=message_id)
        return {"status": "delivered", "message_id": message_id}
    except Exception as exc:
        emit("post_race_discord_failed", **notification_failure(exc))
        return {"status": "failed", **notification_failure(exc)}


def execute(
    *, mode, apply=False, scheduled=False, through=None, lookback=7, now=None, state_path=STATE_PATH
):
    now = now or datetime.now(KST)
    if scheduled and through is not None:
        raise ValueError("scheduled_date_override_forbidden")
    days = plan(mode=mode, end=through or now.date(), now=now, lookback=lookback)
    emit(
        "post_race_plan",
        mode=mode,
        start=str(days[0]),
        end=str(days[-1]),
        apply=apply,
        scheduled=scheduled,
        predictions=False,
    )
    if not apply:
        return 0  # No secrets, network, filesystem writes or DB connection.
    if scheduled and mode == "dividends" and not 9 <= now.hour < 22:
        emit("post_race_skipped_outside_daytime")
        return 0
    if shutil.disk_usage(ROOT).free < 2 * 1024**3:
        emit("post_race_failed", error_type="local_disk_below_2GiB_guard")
        return 1
    state_path.parent.mkdir(parents=True, exist_ok=True)
    live.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Share the live worker's local and DB locks: never race result/odds updates.
    with os.fdopen(
        open_regular(live.STATE_PATH.with_suffix(".lock"), os.O_CREAT | os.O_RDWR), "a"
    ) as local_lock:
        try:
            fcntl.flock(local_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit("post_race_skipped_concurrent_local")
            return 0
        state = live.read_state(state_path)
        if state.get("day") != str(now.date()):
            state["day"], state["counts"] = str(now.date()), {}
        settings = None
        phase = "settings"
        try:
            settings = live.load_settings()
            raw_dir = settings.raw_data_dir
            if not raw_dir.is_absolute():
                raw_dir = ROOT / raw_dir
            engine = create_engine_for_url(settings.database_url)
            try:
                phase = "connect"
                with connect_local_database(engine, emit) as lock:
                    acquired = []
                    try:
                        for key in (live.LOCK_KEY, dividends.BACKFILL_LOCK):
                            ok = lock.scalar(
                                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                            )
                            lock.commit()
                            if not ok:
                                emit("post_race_skipped_concurrent_database")
                                return 0
                            acquired.append(key)
                        phase = "work"
                        with Session(engine, expire_on_commit=False) as session:
                            if mode == "dividends" and scheduled:
                                races = load_races(session, now.date())
                                if not live.in_window(races, now):
                                    emit("post_race_skipped_no_active_window")
                                    return 0
                            with live.LocalKraApiClient(
                                settings.data_go_kr_service_key.get_secret_value(),
                                base_url=settings.kra_api_base_url,
                                timeout_seconds=15,
                            ) as client:
                                live.attach_budget(
                                    client, state=state, state_path=state_path, maximum=300
                                )
                                summary = collect(
                                    session,
                                    client,
                                    days=days,
                                    mode=mode,
                                    now=now,
                                    state=state,
                                    state_path=state_path,
                                    raw_dir=raw_dir,
                                )
                    finally:
                        release_database_locks(lock, acquired, emit)
            finally:
                engine.dispose()
            state["last_summary"] = summary
            state.pop("last_failure", None)
            state.pop("last_notification_summary", None)
            state["notification"] = {"status": "sending"}
            write_execution_state(state_path, state, mode)
            emit("post_race_summary", **summary)
            state["notification"] = notify(settings, summary, scheduled=scheduled)
            write_execution_state(state_path, state, mode)
            return 1 if summary["errors"] else 0
        except Exception as exc:
            failure = {
                "mode": mode,
                "observed_at": now.isoformat(),
                "through": str(days[-1]),
                "failure_phase": phase,
                **safe_failure(exc),
            }
            state["last_failure"] = failure
            emit("post_race_failed", **failure)
            failure_summary = {
                "mode": mode,
                "status": "failed",
                "start": str(days[0]),
                "end": str(days[-1]),
                "run_id": None,
                "elapsed_seconds": 0,
                "observations": [],
                "errors": [safe_failure(exc)],
                "pending": [],
            }
            state["last_notification_summary"] = failure_summary
            state["notification"] = {"status": "sending"}
            write_execution_state(state_path, state, mode)
            if settings is not None:
                state["notification"] = notify(settings, failure_summary, scheduled=scheduled)
            write_execution_state(state_path, state, mode)
            return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dividends", "repair"), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--through", type=date.fromisoformat)
    parser.add_argument("--lookback", type=int, choices=range(1, 8), default=7)
    args = parser.parse_args()
    raise SystemExit(execute(**vars(args)))


if __name__ == "__main__":
    main()
