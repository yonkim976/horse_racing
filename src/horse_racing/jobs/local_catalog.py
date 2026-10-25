"""Local scheduled reference-data refresh into validated Supabase; dry-run by default."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import time
from datetime import date, datetime, timedelta

from sqlalchemy import text

from horse_racing.db.engine import create_engine_for_url
from horse_racing.jobs import canonical_refresh, horse_profile_medical
from horse_racing.jobs import local_race_day as live
from horse_racing.jobs import weekly_entry_cards as cards
from horse_racing.jobs.local_log_rotation import open_regular
from horse_racing.jobs.local_resilience import (
    connect_local_database,
    release_database_locks,
    safe_failure,
)
from horse_racing.services.discord_notifications import notification_failure, send_discord

MODES = ("cards", "medical", "profiles", "trials", "canonical")
LABELS = {mode: f"com.horse-racing.catalog-{mode}" for mode in MODES}
SCHEDULES = {
    "cards": [{"Weekday": 3, "Hour": hour, "Minute": 10} for hour in (15, 16)],
    "medical": [{"Hour": 18, "Minute": 10}],
    "profiles": [{"Weekday": 3, "Hour": 17, "Minute": 40}, {"Hour": 18, "Minute": 40}],
    "trials": [
        {"Weekday": 4, "Hour": 15, "Minute": 10},
        {"Weekday": 4, "Hour": 19, "Minute": 10},
        {"Weekday": 5, "Hour": 9, "Minute": 10},
    ],
    "canonical": [{"Hour": 21, "Minute": 0}, {"Hour": 9, "Minute": 15}],
}
TITLES = {
    "cards": "주간 출마표",
    "medical": "진료기록·진단명 연결",
    "profiles": "말 기본정보·조교사",
    "trials": "주행심사",
    "canonical": "심판리포트·구간·통과기록",
}


def last_racing_day(connection, today):
    # The weekly card cycle starts Wednesday, including Monday holiday meetings.
    start = today - timedelta(days=(today.weekday() - 2) % 7)
    return connection.scalar(
        text("""SELECT max(race_date_local) FROM races
        WHERE race_date_local BETWEEN :start AND :end"""),
        {"start": start, "end": start + timedelta(days=6)},
    )


def profiles_due(now, last_day):
    return (now.weekday() == 2 and 17 <= now.hour < 18) or (
        now.date() == last_day and now.hour >= 18
    )


def collect(mode, settings, now, directory, *, canonical_date=None, canonical_days=14):
    from horse_racing.jobs import reference_catalog

    day = now.date()
    if mode == "medical":
        return horse_profile_medical.refresh(
            settings,
            start=day - timedelta(days=13),
            end=day,
            directory=directory,
            include_profiles=False,
        )
    if mode == "profiles":
        parts = {}
        # Failures are independent: a trainer publication issue must not block horses.
        for name, worker in (
            (
                "horses",
                lambda folder: horse_profile_medical.refresh(
                    settings, start=day, end=day, directory=folder, include_medical=False
                ),
            ),
            (
                "trainers",
                lambda folder: reference_catalog.refresh_trainers(
                    settings, now=now, directory=folder
                ),
            ),
        ):
            folder = directory / name
            folder.mkdir()
            try:
                parts[name] = worker(folder)
            except Exception as exc:
                parts[name] = {"status": "failed", "error_type": type(exc).__name__}
        return {
            "status": "completed"
            if all(p.get("status", "completed") == "completed" for p in parts.values())
            else "failed"
            if all(p.get("status") == "failed" for p in parts.values())
            else "partial",
            **parts,
        }
    if mode == "trials":
        return reference_catalog.refresh_trials(
            settings, start=day - timedelta(days=13), end=day, directory=directory
        )
    if mode == "canonical":
        day = canonical_date or day
        return canonical_refresh.refresh(
            settings, start=day - timedelta(days=canonical_days - 1), end=day, directory=directory
        )
    raise ValueError("unexpected_catalog_mode")


def notify(settings, mode, result):
    status = result.get("status", "completed")
    display_status = {
        "waiting_for_publication": "API 공개 대기",
        "not_published": "미공개",
    }.get(status, status)
    if mode == "trials" and status == "partial":
        display_status = (
            "일부 실패"
            if result.get("errors")
            else "일부 저장 · API 공개 대기"
            if result.get("pending")
            else "결과 저장 · 일부 공식 ID 미제공"
        )
    # Only safe counters, never source payloads, credentials or exception messages.
    lines = [
        f"[경마 DB] {TITLES[mode]} {display_status}",
        "노트북 → Supabase",
        f"확인: {datetime.now(cards.KST):%Y-%m-%d %H:%M:%S KST}",
    ]
    if "start" in result and "end" in result:
        lines.append(f"조회 범위: {result['start']} ~ {result['end']}")
    for key in (
        "files",
        "trials",
        "runners",
        "unlinked_rows",
        "text_jockey_fallback_rows",
        "api_jockey_ids_missing",
        "active",
        "ended",
        "profile_snapshots_added",
        "diagnosis_terms_added",
    ):
        if key in result:
            lines.append(f"{key}: {result[key]}")
    if mode == "canonical":
        for key in (
            "sections_new",
            "sections_changed",
            "groups_new",
            "groups_changed",
            "reports_new",
            "reports_changed",
        ):
            lines.append(f"{key}: {sum(r.get(key, 0) for r in result.get('results', []))}")
        lines.append(
            f"확인 필요: {len(result.get('pending', []))} · 오류: {len(result.get('errors', []))}"
        )
        for error in result.get("errors", [])[:4]:
            lines.append(
                f"원천/검증 오류: {error.get('day')} / 지역 {error.get('meet')} / "
                f"{error.get('stage', '구간')} / {error.get('type', 'UnknownError')}"
            )
    if mode == "trials":
        pending, errors = result.get("pending", []), result.get("errors", [])
        lines.append(f"API 공개 대기: {len(pending)} · 오류: {len(errors)}")
        regions = {1: "서울", 2: "제주", 3: "부경"}
        for row in pending[:6]:
            lines.append(
                f"대기: {regions.get(row['meet'], '지역 미상')} {row['date']} · "
                f"Text {int(row['text_runners'])}두 / API 0두 · 기존 기록 유지"
            )
        for row in errors[:6]:
            safe_type = row.get("error_type", "UnknownError")
            lines.append(
                f"오류: {regions.get(row['meet'], '지역 미상')} "
                f"{row.get('date', '목록 조회')} / {safe_type}"
            )
        lines.append("저장 집계는 검증 완료된 날짜만 포함하며 신규 건수는 아닙니다.")
        lines.append("재확인: 목요일 19:10 · 금요일 09:10 KST. 검증된 날짜·지역만 저장합니다.")
    if "medical_changes" in result:
        lines.append("진료 변경: " + json.dumps(result["medical_changes"], ensure_ascii=False))
    if mode == "profiles":
        lines.extend(
            f"{name}: {result.get(name, {}).get('status', 'completed')}"
            for name in ("horses", "trainers")
        )
        trainer = result.get("trainers", {})
        lines.append(f"현역 {trainer.get('active', 0)} · 등록종료 {trainer.get('ended', 0)}명")
    if "error_type" in result:
        lines.append(f"오류 유형: {result['error_type']}")
        if "error_reason" in result:
            lines.append(f"오류 분류: {result['error_reason']}")
    lines.append("예측 재실행·배포·로컬 SQLite 쓰기는 포함하지 않습니다.")
    message_id = send_discord(settings.discord_webhook_url, "\n".join(lines)[:1900])
    cards.emit("local_catalog_discord_sent", mode=mode, message_id=message_id)
    return {"status": "delivered", "message_id": message_id}


def execute(
    *, mode, apply=False, scheduled=False, now=None, canonical_date=None, canonical_days=14
):
    if mode not in MODES:
        raise ValueError("unexpected_catalog_mode")
    now = now or datetime.now(cards.KST)
    if canonical_date is not None or canonical_days != 14:
        if mode != "canonical" or scheduled:
            raise ValueError("canonical_manual_scope_only")
        if not 1 <= canonical_days <= 14 or not (
            now.date() - timedelta(days=13) <= (canonical_date or now.date()) <= now.date()
        ):
            raise ValueError("canonical_scope_outside_recent_fourteen_days")
    cards.emit(
        "local_catalog_plan",
        mode=mode,
        apply=apply,
        scheduled=scheduled,
        date=str(now.date()),
        sqlite_writes=False,
        predictions=False,
    )
    if not apply:
        return 0  # No secret reads, filesystem writes, network or DB connection.
    if shutil.disk_usage(live.ROOT).free < 2 * 1024**3:
        cards.emit("local_catalog_failed", error_type="local_disk_below_2GiB_guard")
        return 1
    live.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(
        open_regular(live.STATE_PATH.with_suffix(".lock"), os.O_CREAT | os.O_RDWR), "a"
    ) as local_lock:
        phase = "local_lock"
        try:
            # Wait boundedly so adjacent local collectors do not silently drop a daily run.
            deadline = time.monotonic() + 45
            while True:
                try:
                    fcntl.flock(local_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        cards.emit("local_catalog_busy", mode=mode)
                        return 75
                    time.sleep(1)
            phase = "settings"
            settings = live.load_settings()
            engine = create_engine_for_url(settings.database_url)
            try:
                phase = "connect"
                with connect_local_database(engine, cards.emit) as lock:
                    ok = lock.scalar(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": live.LOCK_KEY}
                    )
                    lock.commit()
                    if not ok:
                        cards.emit("local_catalog_busy_database", mode=mode)
                        return 75
                    phase = "work"
                    try:
                        if (
                            scheduled
                            and mode == "profiles"
                            and not profiles_due(now, last_racing_day(lock, now.date()))
                        ):
                            cards.emit("local_catalog_skipped_not_profile_day")
                            return 0
                        prefix = (
                            "score_point_updates_auto"
                            if mode == "canonical"
                            else "local_catalog_" + mode
                        )
                        directory = (
                            live.ROOT
                            / "data/research"
                            / f"{prefix}_{now:%Y%m%d_%H%M%S}_{time.time_ns()}"
                        )
                        directory.mkdir(mode=0o700, parents=True)
                        if mode == "cards":
                            # Weekly worker owns the cross-cloud/local lock and notification.
                            code = cards.execute(
                                live.PROJECT_REF,
                                as_of=now.date(),
                                force=False,
                                dry_run=False,
                                settings_override=settings,
                            )
                            result = {
                                "status": "worker_finished" if code == 0 else "failed",
                                "worker_exit_code": code,
                            }
                        else:
                            result = collect(
                                mode,
                                settings,
                                now,
                                directory,
                                canonical_date=canonical_date,
                                canonical_days=canonical_days,
                            )
                    finally:
                        release_database_locks(lock, [live.LOCK_KEY], cards.emit)
            finally:
                engine.dispose()
        except Exception as exc:
            result = {"status": "failed", "failure_phase": phase, **safe_failure(exc)}
            if "settings" not in locals():
                cards.emit("local_catalog_failed", mode=mode, **result)
                return 1
        state = dict(mode=mode, observed_at=now.isoformat(), **result)
        live.write_state(live.ROOT / f"data/state/local-catalog-{mode}.json", state)
        if "directory" in locals():
            live.write_state(directory / "summary.json", state)
        cards.emit("local_catalog_summary", **state)
        try:
            if mode != "cards":
                state["notification"] = {"status": "sending"}
                live.write_state(live.ROOT / f"data/state/local-catalog-{mode}.json", state)
                state["notification"] = notify(settings, mode, result)
        except Exception as exc:
            state["notification"] = {"status": "failed", **notification_failure(exc)}
            cards.emit("local_catalog_notification_failed", **notification_failure(exc))
        live.write_state(live.ROOT / f"data/state/local-catalog-{mode}.json", state)
        return 1 if result.get("status") == "failed" else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--canonical-date", type=date.fromisoformat)
    parser.add_argument("--canonical-days", type=int, choices=range(1, 15), default=14)
    args = parser.parse_args()
    raise SystemExit(execute(**vars(args)))


if __name__ == "__main__":
    main()
