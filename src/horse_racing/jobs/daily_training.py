"""Supabase-only daily training worker with optional post-commit Discord notifications.

Default is a no-I/O plan. --apply is reserved for the approved Cloud Run Job.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import (
    DAILY_TRAINING_ENDPOINT,
    KraApiClient,
    KraApiRateLimitError,
)
from horse_racing.collectors.special_training import KraXmlApiClient
from horse_racing.config import get_settings
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    HorseHillTraining,
    HorseStartTraining,
    HorseSwimTraining,
    HorseTraining,
    IngestionRun,
)
from horse_racing.jobs.weekly_entry_cards import KST, emit, require_complete_pages, require_target
from horse_racing.parsers.horse_history import HorseTrainingItem
from horse_racing.parsers.race_day import parse_items
from horse_racing.parsers.race_supplemental import StartTrainingItem
from horse_racing.parsers.special_training import HillTrainingItem, SwimTrainingItem
from horse_racing.services.discord_notifications import notify_training
from horse_racing.services.horse_history import ingest_training
from horse_racing.services.race_supplemental import ingest_start_training
from horse_racing.services.special_training import ingest_hill_training, ingest_swim_training_date
from horse_racing.services.start_training_website import ingest_jeju_start_training_website

PROJECT_REF = "xkykmhhkjtosptoibduo"
LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"horse-racing-daily-training-v1").digest()[:8], "big", signed=True
)
MODELS = {
    "daily": HorseTraining,
    "starting": HorseStartTraining,
    "swimming": HorseSwimTraining,
    "hill": HorseHillTraining,
}
OBSERVATION_ONLY = {"id", "observed_at_ms", "source_document_id", "source_row_no"}


def training_window(as_of: date) -> list[date]:
    return [as_of - timedelta(days=ago) for ago in range(6, -1, -1)]


class DateCheckedApi:
    def __init__(self, client):
        self.client = client

    def iter_pages(self, **kwargs):
        pages = list(self.client.iter_pages(**kwargs))
        model = (
            HorseTrainingItem
            if kwargs["endpoint"] == DAILY_TRAINING_ENDPOINT
            else StartTrainingItem
        )
        items = [item for page in pages for item in parse_items(page.payload, model)]
        require_complete_pages(pages, len(items))
        params = kwargs["public_params"]
        if any(
            item.training_date.strftime("%Y%m%d") != params["tr_date"]
            or item.meet_code != params["meet"]
            for item in items
        ):
            raise ValueError("조교 API 날짜·지역 불일치")
        return iter(pages)


class DateCheckedXml:
    def __init__(self, client):
        self.client = client

    def iter_pages(self, **kwargs):
        pages = list(self.client.iter_pages(**kwargs))
        params = kwargs["public_params"]
        model = SwimTrainingItem if "tr_date" in params else HillTrainingItem
        items = [model.model_validate(raw) for p in pages for raw in p.items]
        start = params.get("tr_date", params.get("start_date"))
        end = params.get("tr_date", params.get("end_date"))
        if (
            not pages
            or {p.total_count for p in pages} != {len(items)}
            or [int(p.public_params["pageNo"]) for p in pages] != list(range(1, len(pages) + 1))
            or any(not start <= item.training_date.strftime("%Y%m%d") <= end for item in items)
        ):
            raise ValueError("특수조교 API 날짜·전체 페이지 불일치")
        return iter(pages)


def snapshot(session: Session, name: str, start: date, end: date) -> dict:
    model = MODELS[name]
    table = model.__table__
    rows = session.execute(
        select(table).where(model.training_date_local.between(start, end))
    ).mappings()
    return {
        r["id"]: tuple((c.name, r[c.name]) for c in table.columns if c.name not in OBSERVATION_ONLY)
        for r in rows
    }


def changes(before: dict, after: dict) -> dict:
    common = before.keys() & after.keys()
    changed = sum(before[key] != after[key] for key in common)
    return {
        "new": len(after.keys() - before.keys()),
        "changed": changed,
        "unchanged": len(common) - changed,
        "removed_from_latest_snapshot": len(before.keys() - after.keys()),
    }


def run_tasks(session: Session, api, xml, website, *, days: list[date], raw_dir: Path) -> list:
    results = []
    quota_exhausted = False

    def task(name, callback, **context):
        nonlocal quota_exhausted
        if quota_exhausted:
            results.append({"kind": name, **context, "status": "not_attempted_quota"})
            return
        try:
            summary = callback()
            result = {
                "kind": name,
                **context,
                "status": "observed_empty" if not summary.records_fetched else "completed",
                "run_id": summary.run_id,
                "fetched": summary.records_fetched,
                "processed": summary.records_written,
            }
        except Exception as exc:
            session.rollback()
            quota_exhausted = isinstance(exc, KraApiRateLimitError)
            # URLs/SQL exception text can contain credentials: report type only.
            result = {"kind": name, **context, "status": "failed", "error_type": type(exc).__name__}
        session.rollback()
        results.append(result)
        emit("training_task", **result)

    for day in days:
        label = day.strftime("%Y%m%d")
        for meet in (1, 2, 3):
            task(
                "daily",
                lambda label=label, meet=meet: ingest_training(
                    session,
                    api,
                    training_date=label,
                    meet=meet,
                    raw_data_dir=raw_dir,
                ),
                day=label,
                meet=meet,
            )
            if meet != 2:
                task(
                    "starting",
                    lambda label=label, meet=meet: ingest_start_training(
                        session,
                        api,
                        training_date=label,
                        meet=meet,
                        raw_data_dir=raw_dir,
                    ),
                    day=label,
                    meet=meet,
                )
        task(
            "starting",
            lambda label=label: ingest_jeju_start_training_website(
                session,
                website,
                training_date=label,
                raw_data_dir=raw_dir,
            ),
            day=label,
            meet=2,
            source="kra_website",
        )
        task(
            "swimming",
            lambda label=label: ingest_swim_training_date(
                session,
                xml,
                training_date=label,
                raw_data_dir=raw_dir,
            ),
            day=label,
        )
    task(
        "hill",
        lambda: ingest_hill_training(
            session,
            xml,
            start_date=days[0].strftime("%Y%m%d"),
            end_date=days[-1].strftime("%Y%m%d"),
            raw_data_dir=raw_dir,
        ),
        start=str(days[0]),
        end=str(days[-1]),
    )
    return results


def execute(*, as_of: date, apply: bool = False) -> int:
    days = training_window(as_of)
    emit(
        "training_plan",
        days=days,
        timezone="Asia/Seoul",
        time="14:30",
        meets=[1, 2, 3],
        apply=apply,
        predictions=False,
        discord="opt_in_after_commit" if apply else False,
    )
    if not apply:
        return 0  # No settings/secrets, filesystem, network or DB access.
    if as_of != datetime.now(KST).date():
        raise ValueError("운영 쓰기는 현재 KST 날짜만 허용합니다.")
    settings = get_settings()
    require_target(settings.database_url, PROJECT_REF)
    if settings.data_go_kr_service_key is None:
        raise ValueError("KRA API 키 없음")
    raw_dir = settings.raw_data_dir.resolve()
    if os.getenv("CLOUD_RUN_JOB") or os.getenv("K_SERVICE"):
        if raw_dir != Path("/raw") or not os.getenv("HORSE_RACING_RAW_BUCKET"):
            raise ValueError("클라우드 원문은 영속 /raw 볼륨에 저장해야 합니다.")
    engine = create_engine_for_url(settings.database_url)
    started = time.time_ns() // 1_000_000
    try:
        with engine.connect() as lock:
            acquired = bool(
                lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY})
            )
            lock.commit()
            if not acquired:
                emit("skipped_concurrent_training")
                return 0
            try:
                with Session(engine, expire_on_commit=False) as session:
                    run = IngestionRun(
                        source="worker/daily_training/v1",
                        data_type="daily_training_job",
                        status="running",
                        started_at_ms=started,
                    )
                    session.add(run)
                    session.commit()
                    run_id = run.id
                    try:
                        results, diffs, latest = collect_window(session, settings, days, raw_dir)
                    except Exception as exc:
                        session.rollback()
                        failed = session.get(IngestionRun, run_id)
                        failed.status = "failed"
                        failed.completed_at_ms = time.time_ns() // 1_000_000
                        failed.error_message = type(exc).__name__
                        session.commit()
                        raise
                    failures = sum(r["status"] == "failed" for r in results)
                    run.status = "failed" if failures else "completed"
                    run.completed_at_ms = time.time_ns() // 1_000_000
                    run.records_fetched = sum(r.get("fetched", 0) for r in results)
                    run.records_written = sum(r.get("processed", 0) for r in results)
                    run.error_message = f"{failures} failed task(s)" if failures else None
                    session.add(run)
                    session.commit()
                    summary = {
                        "run_id": run.id,
                        "window_start": str(days[0]),
                        "window_end": str(days[-1]),
                        "failures": failures,
                        "elapsed_seconds": round((run.completed_at_ms - started) / 1000, 1),
                        "changes": diffs,
                        "latest_training_date_in_window": latest,
                        "results": results,
                    }
                    emit("training_summary", **summary)
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                lock.commit()
    finally:
        engine.dispose()
    # No database transaction/lock is held during the notification HTTP request.
    notify_training(settings.discord_webhook_url, emit=emit, summary=summary)
    return 1 if failures else 0


def collect_window(session, settings, days, raw_dir):
    before = {name: snapshot(session, name, days[0], days[-1]) for name in MODELS}
    session.rollback()
    key = settings.data_go_kr_service_key.get_secret_value()
    with (
        KraApiClient(key, base_url=settings.kra_api_base_url) as api,
        KraXmlApiClient(key, base_url=settings.kra_api_base_url) as xml,
        httpx.Client(timeout=30, headers={"User-Agent": "HorseRacingCollector/1.0"}) as web,
    ):
        results = run_tasks(
            session, DateCheckedApi(api), DateCheckedXml(xml), web, days=days, raw_dir=raw_dir
        )
    after = {name: snapshot(session, name, days[0], days[-1]) for name in MODELS}
    diffs = {name: changes(before[name], after[name]) for name in MODELS}
    latest = {
        name: max((dict(values)["training_date_local"] for values in rows.values()), default=None)
        for name, rows in after.items()
    }
    return results, diffs, latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        code = execute(as_of=args.as_of or datetime.now(KST).date(), apply=args.apply)
    except Exception as exc:
        emit("training_failed", error_type=type(exc).__name__)
        if args.apply:
            try:
                notify_training(
                    get_settings().discord_webhook_url, emit=emit, failure_type=type(exc).__name__
                )
            except Exception as notify_exc:
                emit("discord_failed", error_type=type(notify_exc).__name__)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
