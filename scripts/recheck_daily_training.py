"""Recheck one recent daily-training date/meet in Supabase; no I/O without --apply."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from horse_racing.db.engine import create_engine_for_url
from horse_racing.jobs import daily_training as training
from horse_racing.jobs import local_race_day as live
from horse_racing.jobs.canonical_post_race import write_json


def task_snapshot(session, day, meet):
    return {
        key: values
        for key, values in training.snapshot(session, "daily", day, day).items()
        if dict(values)["meet_code"] == meet
    }


def execute(*, day: date, meet: int, apply=False):
    today = datetime.now(training.KST).date()
    if meet not in (1, 2, 3) or not today - timedelta(days=13) <= day <= today:
        raise ValueError("Only one meet/date in the latest 14 days is allowed")
    training.emit(
        "daily_training_recheck_plan",
        date=str(day),
        meet=meet,
        apply=apply,
        sqlite_writes=False,
        predictions=False,
        discord=False,
    )
    if not apply:
        return 0
    if shutil.disk_usage(live.ROOT).free < 2 * 1024**3:
        raise RuntimeError("local_disk_below_2GiB_guard")
    settings = live.load_settings()
    engine = create_engine_for_url(settings.database_url)
    try:
        with engine.connect() as lock:
            if not lock.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": training.LOCK_KEY}
            ):
                training.emit("daily_training_recheck_busy")
                return 75
            lock.commit()
            try:
                directory = (
                    live.ROOT
                    / "data/research"
                    / f"daily_training_recheck_{today:%Y%m%d}_{time.time_ns()}"
                )
                directory.mkdir(mode=0o700)
                with Session(engine) as session:
                    before = task_snapshot(session, day, meet)
                    session.rollback()
                    write_json(
                        directory / "before.json", json.loads(json.dumps(before, default=str))
                    )
                    with live.LocalKraApiClient(
                        settings.data_go_kr_service_key.get_secret_value()
                    ) as api:
                        summary = training.ingest_training(
                            session,
                            training.DateCheckedApi(api),
                            training_date=day.strftime("%Y%m%d"),
                            meet=meet,
                            raw_data_dir=directory / "raw",
                        )
                    after = task_snapshot(session, day, meet)
                    result = dict(
                        date=str(day),
                        meet=meet,
                        run_id=summary.run_id,
                        fetched=summary.records_fetched,
                        processed=summary.records_written,
                        changes=training.changes(before, after),
                        status="completed" if summary.records_fetched else "observed_empty",
                    )
                    write_json(directory / "after.json", json.loads(json.dumps(after, default=str)))
                    write_json(directory / "report.json", result)
                    training.emit("daily_training_recheck_summary", **result)
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": training.LOCK_KEY})
                lock.commit()
    finally:
        engine.dispose()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--meet", required=True, type=int, choices=(1, 2, 3))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        return execute(day=args.date, meet=args.meet, apply=args.apply)
    except Exception as exc:
        training.emit("daily_training_recheck_failed", error_type=type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
