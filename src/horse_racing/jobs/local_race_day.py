"""Laptop/manual race-day synchronization. Dry-run by default; never invokes an AI/model.

--apply: one manual run. --apply --scheduled: one time-gated launchd tick.
--apply --watch: foreground 120-second ticks, using the same locks and worker.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from tenacity import stop_after_attempt, wait_fixed

from horse_racing.collectors import kra_api as api
from horse_racing.config import Settings
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import IngestionRun, SourceDocument
from horse_racing.jobs.weekly_entry_cards import KST, emit, require_complete_pages, require_target
from horse_racing.parsers.horse_history import HorseWeightItem
from horse_racing.parsers.race_day import AiRaceResultItem, DetailedRaceResultItem, parse_items
from horse_racing.parsers.race_supplemental import JockeyChangeItem, RaceScratchItem
from horse_racing.services.discord_notifications import send_discord
from horse_racing.services.live_race_day import (
    apply_items,
    entry_index,
    load_races,
    race_has_complete_results,
    refresh_completion,
    snapshot,
    validate_items,
)
from horse_racing.services.raw_store import store_kra_page

PROJECT_REF = "xkykmhhkjtosptoibduo"
ROOT = Path(__file__).resolve().parents[3]
STATE_PATH = ROOT / "data/state/local-race-day.json"
LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"horse-racing-local-race-day-v1").digest()[:8], "big", signed=True
)
# Faster-changing independent stages remain usable when one result endpoint fails.
STAGES = {
    "weights": (api.ENTRY_HORSE_WEIGHT_ENDPOINT, api.ENTRY_HORSE_WEIGHT_OPERATION, HorseWeightItem),
    "jockeys": (api.JOCKEY_CHANGE_ENDPOINT, api.JOCKEY_CHANGE_OPERATION, JockeyChangeItem),
    "scratches": (api.RACE_HORSE_CANCEL_ENDPOINT, api.RACE_HORSE_CANCEL_OPERATION, RaceScratchItem),
    "results": (api.AI_RACE_RESULT_ENDPOINT, api.AI_RACE_RESULT_OPERATION, AiRaceResultItem),
    "details": (
        api.DETAILED_RACE_RESULT_ENDPOINT,
        api.DETAILED_RACE_RESULT_OPERATION,
        DetailedRaceResultItem,
    ),
}

# Historical backfills retry six times; live ticks retry at most twice.
_live_fetch = api.KraApiClient._fetch_json.retry_with(
    stop=stop_after_attempt(2), wait=wait_fixed(1)
)


class LocalKraApiClient(api.KraApiClient):
    def _fetch_json(self, *args, **kwargs):
        return _live_fetch(self, *args, **kwargs)


class LocalApiBudgetExceeded(RuntimeError):
    pass


def read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        json.dump(state, handle, ensure_ascii=False, sort_keys=True)
    temporary.replace(path)


def attach_budget(client, *, state: dict, state_path: Path, maximum: int) -> None:
    def count_request(request):
        endpoint = request.url.path.removeprefix("/B551015")
        counts = state.setdefault("counts", {})
        if counts.get(endpoint, 0) >= maximum:
            raise LocalApiBudgetExceeded("local_daily_budget_exhausted")
        counts[endpoint] = counts.get(endpoint, 0) + 1
        write_state(state_path, state)  # Include retries and failed HTTP attempts.

    client._client.event_hooks["request"].append(count_request)


def load_settings(settings: Settings | None = None) -> Settings:
    settings = settings or Settings(_env_file=(ROOT / ".env", ROOT / ".env.discord"))
    url = make_url(settings.database_url)
    if url.get_backend_name() != "postgresql":
        binary = shutil.which("gcloud") or "/Users/kimyongjin/google-cloud-sdk/bin/gcloud"
        result = subprocess.run(
            [
                binary,
                "secrets",
                "versions",
                "access",
                "3",
                "--secret=horse-racing-database-url",
                "--project=mapilog-509017",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("database_secret_unavailable")
        url = make_url(result.stdout.strip())
    require_target(url.render_as_string(hide_password=False), PROJECT_REF)
    direct = url.host == f"db.{PROJECT_REF}.supabase.co" and url.username == "postgres"
    pooled = (url.host or "").endswith(
        ".pooler.supabase.com"
    ) and url.username == f"postgres.{PROJECT_REF}"
    if not (direct or pooled):
        raise ValueError("unexpected_database_host")
    if settings.data_go_kr_service_key is None:
        raise ValueError("missing_kra_api_key")
    if settings.discord_webhook_url is None:
        raise ValueError("missing_existing_discord_webhook")
    url = url.set(drivername="postgresql+psycopg").update_query_dict(
        {"sslmode": "require", "connect_timeout": "15"}
    )
    return settings.model_copy(update={"database_url": url.render_as_string(hide_password=False)})


def in_window(races: list, now: datetime) -> bool:
    if not races:
        return False
    starts = [
        datetime.fromtimestamp(r.scheduled_at_ms / 1000, KST) for r in races if r.scheduled_at_ms
    ]
    if len(starts) != len(races):
        return 9 <= now.hour < 21  # Missing time: do not invent a precise race window.
    return min(starts) - timedelta(hours=1) <= now <= max(starts) + timedelta(hours=2)


def summarize_changes(before: dict, after: dict) -> dict:
    fields = {
        "weights": ("weight", "weight_delta"),
        "jockeys": ("jockey", "carried_weight"),
        "scratches": ("scratched",),
        "results": ("finish", "time_ms"),
    }
    changed = {kind: [] for kind in fields}
    for key, current in after.items():
        previous = before[key]
        for kind, names in fields.items():
            if any(previous[name] != current[name] for name in names):
                changed[kind].append(current)
    return changed


def notify(settings: Settings, summary: dict, *, state: dict, path: Path, manual=False) -> None:
    errors = summary.get("errors", [])
    signature = json.dumps(errors, sort_keys=True)
    now = int(time.time())
    changes = summary.get("changes", {})
    meaningful = (
        any(changes.values()) or summary.get("new_completed") or summary.get("completion_repairs")
    )
    failure_due = bool(errors) and (
        signature != state.get("last_alert_error") or now - state.get("last_alert_at", 0) >= 1800
    )
    recovered = not errors and bool(state.get("last_alert_error", "[]") != "[]")
    if not (meaningful or failure_due or recovered or manual):
        return
    # Persist intent first. Ambiguous Discord delivery is not automatically retried.
    state.update(last_alert_error=signature, last_alert_at=now)
    write_state(path, state)
    lines = [
        "[경마 DB] 당일 갱신 " + ("일부 실패" if errors else "완료"),
        f"기준: {summary['day']} / 노트북 → Supabase",
        f"확인 시각: {datetime.now(KST).strftime('%H:%M:%S KST')}",
        "변경: "
        + " · ".join(
            f"{label} {len(changes.get(kind, []))}두"
            for kind, label in (
                ("weights", "체중"),
                ("jockeys", "기수/부담중량"),
                ("scratches", "취소"),
                ("results", "착순/기록"),
            )
        ),
        f"새 완료 경주: {summary.get('new_completed', [])}",
    ]
    if summary.get("completion_repairs"):
        lines.append(f"불완전한 기존 완료 표기 보류: {summary['completion_repairs']}")
    names = {1: "서울", 2: "제주", 3: "부경", 4: "영천"}
    detail_count = 0
    for kind in ("jockeys", "scratches", "weights", "results"):
        for row in changes.get(kind, []):
            if detail_count >= 8:
                break
            prefix = f"{names[row['meet']]} {row['race']}R #{row['number']} {row['horse'][:30]}"
            value = {
                "jockeys": f"기수 {row['jockey_name']} / 부담 {row['carried_weight']}",
                "scratches": "출전취소" if row["scratched"] else "취소 상태 변경",
                "weights": f"체중 {row['weight']}kg / 증감 {row['weight_delta']}",
                "results": f"착순 코드 {row['finish']} / 기록 {row['time_ms']}ms",
            }[kind]
            lines.append(f"{prefix}: {value}")
            detail_count += 1
    if errors:
        lines.append("오류: " + ", ".join(f"{e['meet']}/{e['stage']}:{e['type']}" for e in errors))
    elif recovered:
        lines.append("이전 수집 오류에서 복구했습니다.")
    lines.append("예측 재실행·배당·구간기록·배포는 포함하지 않습니다.")
    try:
        message_id = send_discord(settings.discord_webhook_url, "\n".join(lines)[:1900])
        emit("discord_sent", message_id=message_id)
    except Exception as exc:
        emit("discord_failed", error_type=type(exc).__name__)


def collect(session, client, *, races, day, state, state_path, raw_dir, scheduled):
    index = entry_index(races)
    before = snapshot(races)
    complete_before = {r.id: race_has_complete_results(r) for r in races}
    statuses_before = {r.id: r.status for r in races}
    run = IngestionRun(
        source="laptop/live-race-day/v1",
        data_type="local_live_race_day",
        started_at_ms=time.time_ns() // 1_000_000,
        status="running",
    )
    session.add(run)
    session.commit()
    run_id = run.id
    errors, observations = [], []
    for meet in sorted({r.racecourse.kra_meet_code for r in races}):
        course_races = [r for r in races if r.racecourse.kra_meet_code == meet]
        finished = all(race_has_complete_results(r) for r in course_races)
        for kind, (endpoint, operation, model) in STAGES.items():
            stage_key = f"{day}:{meet}:{kind}"
            now = time.time()
            # Completed venues are checked every ten minutes for late corrections.
            if scheduled and finished and now - state.get("checks", {}).get(stage_key, 0) < 600:
                continue
            params = {"rccrs_cd": meet, "race_dt": day.strftime("%Y%m%d"), "_type": "json"}
            if kind in {"weights", "jockeys", "scratches"}:
                params = {"meet": meet, "rc_date": day.strftime("%Y%m%d"), "_type": "json"}
            session.rollback()  # No database transaction held while fetching API pages.
            try:
                pages = list(
                    client.iter_pages(
                        endpoint=endpoint,
                        operation=operation,
                        public_params=params,
                        page_size=1000,
                        service_key_parameter="ServiceKey"
                        if kind in {"weights", "jockeys", "scratches"}
                        else "serviceKey",
                    )
                )
                items = [item for page in pages for item in parse_items(page.payload, model)]
                require_complete_pages(pages, len(items))
                validate_items(items, kind=kind, day=day, meet=meet, entries=index)
                digest = hashlib.sha256(b"".join(p.body for p in pages)).hexdigest()
                stage_before = snapshot(races)
                apply_items(
                    session,
                    kind=kind,
                    items=items,
                    entries=index,
                    observed_ms=max(p.retrieved_at_ms for p in pages),
                )
                # Keep changed source evidence, not identical JSON copies every two minutes.
                if digest != state.get("hashes", {}).get(stage_key):
                    for page in pages:
                        stored = store_kra_page(
                            page,
                            raw_data_dir=raw_dir,
                            data_type=f"live_day_{kind}",
                            race_date=day.strftime("%Y%m%d"),
                            meet=meet,
                            run_id=run_id,
                            page_no=int(page.public_params["pageNo"]),
                        )
                        session.add(
                            SourceDocument(
                                ingestion_run_id=run_id,
                                endpoint=endpoint,
                                operation=operation,
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
                stage_diff = summarize_changes(stage_before, snapshot(races))
                changed_entries = len(
                    {
                        (row["meet"], row["race"], row["number"])
                        for rows in stage_diff.values()
                        for row in rows
                    }
                )
                observations.append(
                    {
                        "meet": meet,
                        "stage": kind,
                        "rows": len(items),
                        "pages": len(pages),
                        "changed_entries": changed_entries,
                    }
                )
                session.commit()
                state.setdefault("hashes", {})[stage_key] = digest
                state.setdefault("checks", {})[stage_key] = time.time()
                write_state(state_path, state)
                emit("live_stage_complete", **observations[-1])
            except Exception as exc:
                session.rollback()
                errors.append({"meet": meet, "stage": kind, "type": type(exc).__name__})
                emit("live_stage_failed", **errors[-1])
    # Reload after independent commits/rollbacks; no stale objects in completion validation.
    races = load_races(session, day)
    refresh_completion(races)
    session.flush()
    after = snapshot(races)
    new_completed = [
        f"{r.racecourse.name_ko} {r.race_number}R"
        for r in races
        if race_has_complete_results(r) and not complete_before[r.id]
    ]
    repairs = [
        f"{r.racecourse.name_ko} {r.race_number}R"
        for r in races
        if statuses_before[r.id] == "completed" and r.status != "completed"
    ]
    run = session.get(IngestionRun, run_id)
    run.status = "partial" if errors and observations else "failed" if errors else "completed"
    run.completed_at_ms = time.time_ns() // 1_000_000
    run.records_fetched = sum(o["rows"] for o in observations)
    run.records_written = sum(o["changed_entries"] for o in observations)
    run.error_message = json.dumps(errors) if errors else None
    session.commit()
    return {
        "day": str(day),
        "run_id": run_id,
        "observations": observations,
        "errors": errors,
        "changes": summarize_changes(before, after),
        "new_completed": new_completed,
        "completion_repairs": repairs,
        "elapsed_seconds": round((run.completed_at_ms - run.started_at_ms) / 1000, 2),
    }


def execute(*, apply=False, scheduled=False, max_requests=800, now=None, state_path=STATE_PATH):
    now = now or datetime.now(KST)
    emit(
        "local_live_plan",
        day=str(now.date()),
        apply=apply,
        scheduled=scheduled,
        interval_seconds=120,
        predictions=False,
        cloud_resources=False,
    )
    if not apply:
        return 0  # No settings, secrets, filesystem, network, or DB access.
    if now.date() != datetime.now(KST).date():
        raise ValueError("only_current_kst_day_allowed")
    if scheduled and not 8 <= now.hour < 22:
        emit("skipped_outside_daytime")
        return 0
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.with_suffix(".lock").open("a") as local_lock:
        os.chmod(state_path.with_suffix(".lock"), 0o600)
        try:
            fcntl.flock(local_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit("skipped_concurrent_local_sync")
            return 0
        state = read_state(state_path)
        if state.get("day") != str(now.date()):
            state = {"day": str(now.date()), "counts": {}, "hashes": {}, "checks": {}}
        settings = None
        try:
            settings = Settings(_env_file=(ROOT / ".env", ROOT / ".env.discord"))
            settings = load_settings(settings)
            raw_dir = settings.raw_data_dir
            if not raw_dir.is_absolute():
                raw_dir = ROOT / raw_dir
            engine = create_engine_for_url(settings.database_url)
            try:
                with engine.connect() as lock:
                    if not lock.scalar(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
                    ):
                        lock.commit()
                        emit("skipped_concurrent_database_sync")
                        return 0
                    lock.commit()
                    try:
                        with Session(engine, expire_on_commit=False) as session:
                            races = load_races(session, now.date())
                            if not races or (scheduled and not in_window(races, now)):
                                emit("skipped_no_active_race_window", races=len(races))
                                return 0
                            with LocalKraApiClient(
                                settings.data_go_kr_service_key.get_secret_value(),
                                base_url=settings.kra_api_base_url,
                                timeout_seconds=10,
                            ) as client:
                                attach_budget(
                                    client, state=state, state_path=state_path, maximum=max_requests
                                )
                                summary = collect(
                                    session,
                                    client,
                                    races=races,
                                    day=now.date(),
                                    state=state,
                                    state_path=state_path,
                                    raw_dir=raw_dir,
                                    scheduled=scheduled,
                                )
                    finally:
                        lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                        lock.commit()
            finally:
                engine.dispose()
            state["last_summary"] = {k: v for k, v in summary.items() if k != "changes"}
            write_state(state_path, state)
            emit(
                "local_live_summary",
                **state["last_summary"],
                change_counts={kind: len(rows) for kind, rows in summary["changes"].items()},
            )
            notify(settings, summary, state=state, path=state_path, manual=not scheduled)
            return 1 if summary["errors"] else 0
        except Exception as exc:
            emit("local_live_failed", error_type=type(exc).__name__)
            if settings is not None:
                notify(
                    settings,
                    {
                        "day": str(now.date()),
                        "errors": [{"meet": 0, "stage": "startup", "type": type(exc).__name__}],
                    },
                    state=state,
                    path=state_path,
                )
            return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument(
        "--max-api-requests",
        type=int,
        default=800,
        help="Local per-endpoint/day ceiling; NOT the actual account quota",
    )
    args = parser.parse_args()
    if not 1 <= args.max_api_requests <= 1000:
        parser.error("local API request ceiling must be 1..1000")
    if args.watch and not args.apply:
        parser.error("--watch requires --apply")
    while True:
        started = time.monotonic()
        code = execute(
            apply=args.apply,
            scheduled=args.scheduled or args.watch,
            max_requests=args.max_api_requests,
        )
        if not args.watch:
            raise SystemExit(code)
        time.sleep(max(1, 120 - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
