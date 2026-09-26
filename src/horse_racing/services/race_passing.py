from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import KraApiClient, response_body
from horse_racing.db.models import (
    IngestionRun,
    Race,
    Racecourse,
    RacePassingSummary,
    SourceDocument,
)
from horse_racing.parsers.race_day import parse_items
from horse_racing.parsers.race_passing import RacePassingSummaryItem
from horse_racing.services.entry_sheet import IngestionSummary, _upsert_racecourse
from horse_racing.services.race_day import _find_race
from horse_racing.services.raw_store import store_kra_page


def passing_summary_data_exists(
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
) -> bool:
    fetched = next(
        client.iter_race_passing_summary_pages(
            race_date=race_date,
            meet=meet,
            page_size=1,
        )
    )
    try:
        return int(response_body(fetched.payload).get("totalCount") or 0) > 0
    except (TypeError, ValueError):
        return False


def passing_summary_day_is_stored(
    session: Session,
    *,
    race_date: date,
    meet: int,
) -> bool:
    expected = session.scalar(
        select(func.count())
        .select_from(Race)
        .join(Race.racecourse)
        .where(
            Race.race_date_local == race_date,
            Racecourse.kra_meet_code == meet,
            Race.status == "completed",
        )
    )
    if not expected:
        return True
    stored = session.scalar(
        select(func.count())
        .select_from(RacePassingSummary)
        .join(Race, Race.id == RacePassingSummary.race_id)
        .join(Race.racecourse)
        .where(
            Race.race_date_local == race_date,
            Racecourse.kra_meet_code == meet,
        )
    )
    return int(stored or 0) >= int(expected or 0)


def ingest_race_passing_summaries(
    session: Session,
    client: KraApiClient,
    *,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
    race_date: str | None = None,
    race_year: int | None = None,
) -> IngestionSummary:
    if (race_date is None) == (race_year is None):
        raise ValueError("race_date 또는 race_year 중 하나만 지정해야 합니다.")
    partition_date = race_date or f"{race_year:04d}0101"
    run = IngestionRun(
        source="data.go.kr/B551015/API303",
        data_type="race_passing_summary",
        started_at_ms=_now_ms(),
        status="running",
    )
    session.add(run)
    session.commit()
    run_id = run.id
    pages = 0
    fetched_count = 0
    written_count = 0
    try:
        for fetched in client.iter_race_passing_summary_pages(
            meet=meet,
            race_date=race_date,
            race_year=race_year,
            page_size=page_size,
        ):
            page_no = int(fetched.public_params["pageNo"])
            stored = store_kra_page(
                fetched,
                raw_data_dir=raw_data_dir,
                data_type="race_passing_summary",
                race_date=partition_date,
                meet=meet,
                run_id=run_id,
                page_no=page_no,
            )
            source_document = SourceDocument(
                ingestion_run_id=run_id,
                source_url=fetched.source_url,
                endpoint=fetched.endpoint,
                operation=fetched.operation,
                request_params_json=json.dumps(
                    fetched.public_params,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                requested_at_ms=fetched.requested_at_ms,
                retrieved_at_ms=fetched.retrieved_at_ms,
                http_status_code=fetched.status_code,
                content_type=fetched.content_type,
                response_bytes=len(fetched.body),
                local_path=str(stored.path),
                sha256=stored.sha256,
            )
            session.add(source_document)
            session.flush()
            items = parse_items(fetched.payload, RacePassingSummaryItem)
            fetched_count += len(items)
            written_count += _upsert_items(
                session,
                meet=meet,
                items=items,
                source_document_id=source_document.id,
                observed_at_ms=fetched.retrieved_at_ms,
            )
            pages += 1
            run.records_fetched = fetched_count
            run.records_written = written_count
            session.commit()
        run.status = "completed"
        run.completed_at_ms = _now_ms()
        session.commit()
        return IngestionSummary(
            run_id=run_id,
            pages=pages,
            records_fetched=fetched_count,
            records_written=written_count,
        )
    except Exception as exc:
        session.rollback()
        failed_run = session.get(IngestionRun, run_id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.completed_at_ms = _now_ms()
            failed_run.error_message = str(exc)
            session.commit()
        raise


def _upsert_items(
    session: Session,
    *,
    meet: int,
    items: list[RacePassingSummaryItem],
    source_document_id: int,
    observed_at_ms: int,
) -> int:
    racecourse = _upsert_racecourse(session, meet)
    written = 0
    for item in items:
        race = _find_race(session, racecourse, item.race_date, item.race_number)
        if race is None:
            continue
        row = session.scalar(
            select(RacePassingSummary).where(RacePassingSummary.race_id == race.id)
        )
        if row is None:
            row = RacePassingSummary(race_id=race.id)
            session.add(row)
        row.source_document_id = source_document_id
        for index, value in enumerate(item.corner_values, 1):
            setattr(row, f"corner_{index}_raw", value)
        row.pass_time_3f_raw = item.pass_time_3f_raw
        row.pass_time_4f_raw = item.pass_time_4f_raw
        row.pass_time_3f_ms = item.pass_time_3f_ms
        row.pass_time_4f_ms = item.pass_time_4f_ms
        row.tempo_raw = item.tempo_raw
        row.tempo_level = item.tempo_level
        row.quality_status = item.quality_status
        row.source_row_hash = item.source_row_hash
        row.observed_at_ms = observed_at_ms
        written += 1
    return written


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
