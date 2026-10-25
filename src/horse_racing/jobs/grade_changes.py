"""Manually refresh official grade-change history in Supabase; no I/O without --apply.

The API documents a latest-month default, but its live response may also include
older effective dates. Store the verified response without trimming those rows.
Existing history and horse profiles are preserved. No schedule is installed.
"""

from __future__ import annotations

import argparse
import re
import shutil
import time
from collections import Counter
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import (
    HORSE_GRADE_CHANGE_ENDPOINT,
    HORSE_GRADE_CHANGE_OPERATION,
)
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import Horse, HorseGradeChange, IngestionRun, SourceDocument
from horse_racing.jobs import local_race_day as live
from horse_racing.jobs.canonical_post_race import document, write_json
from horse_racing.jobs.weekly_entry_cards import KST, emit, require_complete_pages
from horse_racing.parsers.race_day import parse_items
from horse_racing.parsers.race_supplemental import HorseGradeChangeItem

FIELDS = (
    "id",
    "horse_id",
    "meet_code",
    "blood_type",
    "grade_before",
    "grade_after",
    "start_date_local",
    "end_date_local",
    "observed_at_ms",
)


def item_key(item):
    return item.horse_id, item.start_date, item.grade_before, item.grade_after


def row_key(row, horse_ids):
    return horse_ids[row.horse_id], row.start_date_local, row.grade_before, row.grade_after


def direction(before, after):
    values = [re.fullmatch(r"[국외제]?([1-6])(?:등급)?", x or "") for x in (before, after)]
    if not all(values):
        return "initial_or_other"
    left, right = (int(x.group(1)) for x in values)
    return "promotion" if right < left else "demotion" if right > left else "same_grade"


def validate_items(items, meet):
    unique = {}
    for item in items:
        if item.meet_code != meet or item.start_date is None or not item.grade_after:
            raise ValueError("grade_source_missing_or_wrong_key")
        if item.end_date is not None and item.end_date < item.start_date:
            raise ValueError("grade_source_invalid_date_range")
        key = item_key(item)
        if key in unique and unique[key].model_dump() != item.model_dump():
            raise ValueError("grade_source_conflicting_natural_key")
        unique[key] = item
    return list(unique.values())


def snapshot(session):
    return [
        {name: getattr(row, name) for name in FIELDS}
        for row in session.scalars(select(HorseGradeChange).order_by(HorseGradeChange.id))
    ]


def apply_items(session, items, observed_at_ms):
    horses = {h.kra_horse_id: h for h in session.scalars(select(Horse))}
    horse_ids = {h.id: key for key, h in horses.items()}
    rows = {}
    for row in session.scalars(select(HorseGradeChange)):
        key = row_key(row, horse_ids)
        if key in rows:
            raise ValueError("stored_grade_natural_key_duplicate")
        rows[key] = row
    summaries = {meet: Counter() for meet in (1, 2, 3)}
    for item in items:
        summary = summaries[item.meet_code]
        horse = horses.get(item.horse_id)
        if horse is None:
            horse = Horse(kra_horse_id=item.horse_id, name_ko=item.horse_name)
            session.add(horse)
            session.flush()
            horses[item.horse_id] = horse
            summary["horses_added"] += 1
        key = item_key(item)
        row = rows.get(key)
        values = (item.meet_code, item.blood_type, item.end_date)
        if row is None:
            row = HorseGradeChange(
                horse_id=horse.id,
                start_date_local=item.start_date,
                grade_before=item.grade_before,
                grade_after=item.grade_after,
                observed_at_ms=observed_at_ms,
            )
            session.add(row)
            rows[key] = row
            summary["new"] += 1
            summary["new_" + direction(item.grade_before, item.grade_after)] += 1
        elif (row.meet_code, row.blood_type, row.end_date_local) != values:
            summary["changed"] += 1
        else:
            summary["unchanged"] += 1
        row.meet_code, row.blood_type, row.end_date_local = values
        row.observed_at_ms = observed_at_ms
    session.flush()
    return {str(meet): dict(counts) for meet, counts in summaries.items()}


def verify_saved(session, items, before, observed_at_ms):
    after = snapshot(session)
    horses = {h.id: h.kra_horse_id for h in session.scalars(select(Horse))}
    expected = {item_key(item): item for item in items}
    actual = {}
    by_id = {row["id"]: row for row in after}
    for row in after:
        key = (
            horses[row["horse_id"]],
            row["start_date_local"],
            row["grade_before"],
            row["grade_after"],
        )
        if key in actual:
            raise ValueError("saved_grade_natural_key_duplicate")
        actual[key] = row
    for key, item in expected.items():
        row = actual.get(key)
        if row is None or (
            row["meet_code"],
            row["blood_type"],
            row["end_date_local"],
            row["observed_at_ms"],
        ) != (item.meet_code, item.blood_type, item.end_date, observed_at_ms):
            raise ValueError("saved_grade_source_mismatch")
    for old in before:
        row = by_id.get(old["id"])
        if row is None:
            raise ValueError("existing_grade_history_deleted")
        key = (
            horses[old["horse_id"]],
            old["start_date_local"],
            old["grade_before"],
            old["grade_after"],
        )
        if key not in expected and row != old:
            raise ValueError("unobserved_grade_history_changed")
        if any(
            row[name] != old[name]
            for name in ("horse_id", "start_date_local", "grade_before", "grade_after")
        ):
            raise ValueError("existing_grade_identity_changed")
    return after


def execute(*, apply=False):
    now = datetime.now(KST)
    emit(
        "grade_changes_plan",
        apply=apply,
        date=str(now.date()),
        source_window="official_default_response",
        sqlite_writes=False,
        predictions=False,
        schedule_changes=False,
        discord=False,
    )
    if not apply:
        return 0
    if shutil.disk_usage(live.ROOT).free < 2 * 1024**3:
        raise RuntimeError("local_disk_below_2GiB_guard")
    settings = live.load_settings()
    directory = live.ROOT / "data/research" / f"grade_changes_refresh_{now:%Y%m%d}_{time.time_ns()}"
    directory.mkdir(mode=0o700)
    docs, items, sources = [], [], []
    with live.LocalKraApiClient(settings.data_go_kr_service_key.get_secret_value()) as client:
        for meet in (1, 2, 3):
            pages = list(
                client.iter_pages(
                    endpoint=HORSE_GRADE_CHANGE_ENDPOINT,
                    operation=HORSE_GRADE_CHANGE_OPERATION,
                    public_params={"meet": meet, "_type": "json"},
                    page_size=1000,
                    service_key_parameter="ServiceKey",
                )
            )
            for index, page in enumerate(pages, 1):
                docs.append(document(page, directory / f"api_{meet}_{index}.json"))
            parsed = [x for page in pages for x in parse_items(page.payload, HorseGradeChangeItem)]
            require_complete_pages(pages, len(parsed))
            unique = validate_items(parsed, meet)
            items.extend(unique)
            sources.append(
                dict(
                    meet=meet,
                    pages=len(pages),
                    fetched=len(parsed),
                    unique=len(unique),
                    latest_effective_date=str(max((x.start_date for x in unique), default=None)),
                )
            )
            emit("grade_changes_source_validated", **sources[-1])
    if len({item_key(item) for item in items}) != len(items):
        raise ValueError("grade_source_cross_region_key_conflict")
    engine = create_engine_for_url(settings.database_url)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SET LOCAL statement_timeout = '30s'"))
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            if not session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": live.LOCK_KEY}
            ):
                emit("grade_changes_busy")
                return 75
            before = snapshot(session)
            write_json(directory / "before.json", json_serializable(before))
            counts = apply_items(session, items, int(now.timestamp() * 1000))
            after = verify_saved(session, items, before, int(now.timestamp() * 1000))
            write_json(directory / "after.json", json_serializable(after))
            run = IngestionRun(
                source="data.go.kr/B551015/raceHorseRatingChangeInfo_2",
                data_type="horse_grade_changes",
                started_at_ms=int(now.timestamp() * 1000),
                completed_at_ms=int(time.time() * 1000),
                status="completed",
                records_fetched=sum(x["fetched"] for x in sources),
                records_written=len(items),
            )
            session.add(run)
            session.flush()
            for doc in docs:
                session.add(SourceDocument(ingestion_run_id=run.id, **doc))
            result = dict(
                status="completed",
                run_id=run.id,
                sources=sources,
                counts=counts,
                rows_before=len(before),
                rows_after=len(after),
                verified=len(items),
                directory=str(directory),
                existing_history_preserved=True,
            )
        # The completed report is written only after a successful DB commit.
        write_json(directory / "report.json", result)
        emit("grade_changes_completed", **result)
    finally:
        engine.dispose()
    return 0


def json_serializable(value):
    import json

    return json.loads(json.dumps(value, default=str))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        return execute(apply=args.apply)
    except Exception as exc:
        emit("grade_changes_failed", error_type=type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
