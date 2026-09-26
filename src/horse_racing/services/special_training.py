from __future__ import annotations

import json
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from horse_racing.collectors.special_training import (
    HILL_TRAINING_ENDPOINT,
    HILL_TRAINING_OPERATION,
    SWIM_TRAINING_ENDPOINT,
    SWIM_TRAINING_OPERATION,
    FetchedXmlPage,
    KraXmlApiClient,
)
from horse_racing.db.models import (
    Horse,
    HorseHillTraining,
    HorseSwimTraining,
    IngestionRun,
    SourceDocument,
)
from horse_racing.parsers.special_training import HillTrainingItem, SwimTrainingItem
from horse_racing.services.entry_sheet import IngestionSummary
from horse_racing.services.raw_store import store_kra_xml_page


def ingest_swim_training(
    session: Session,
    client: KraXmlApiClient,
    *,
    start_year: int,
    end_year: int,
    raw_data_dir: Path,
    page_size: int = 20_000,
) -> IngestionSummary:
    if start_year < 1900 or end_year < start_year:
        raise ValueError("수영조교 연도 범위가 올바르지 않습니다.")
    run = _start_run(session, "data.go.kr/B551015/API216", "horse_swim_training")
    pages = fetched_count = written_count = 0
    try:
        for year in range(start_year, end_year + 1):
            for fetched in client.iter_pages(
                endpoint=SWIM_TRAINING_ENDPOINT,
                operation=SWIM_TRAINING_OPERATION,
                public_params={"tr_year": str(year)},
                page_size=page_size,
                service_key_parameter="ServiceKey",
            ):
                page_no = int(fetched.public_params["pageNo"])
                document_id = _store_source_document(
                    session,
                    fetched,
                    raw_data_dir=raw_data_dir,
                    data_type="horse_swim_training",
                    partition_date=f"{year:04d}0101",
                    partition_name=f"year_{year:04d}",
                    run_id=run.id,
                    page_no=page_no,
                )
                items = [SwimTrainingItem.model_validate(item) for item in fetched.items]
                fetched_count += len(items)
                unique_items = _dedupe_swim_items(items)
                written_count += _upsert_swim_items(
                    session,
                    unique_items,
                    source_document_id=document_id,
                    observed_at_ms=fetched.retrieved_at_ms,
                )
                pages += 1
                _checkpoint_run(session, run, fetched_count, written_count)
        return _complete_run(session, run, pages, fetched_count, written_count)
    except Exception as exc:
        _fail_run(session, run.id, exc)
        raise


def ingest_hill_training(
    session: Session,
    client: KraXmlApiClient,
    *,
    start_date: str,
    end_date: str,
    raw_data_dir: Path,
    page_size: int = 20_000,
) -> IngestionSummary:
    if len(start_date) != 8 or len(end_date) != 8 or end_date < start_date:
        raise ValueError("언덕주로 일자 범위는 YYYYMMDD 형식이어야 합니다.")
    run = _start_run(session, "data.go.kr/B551015/hilldriving", "horse_hill_training")
    pages = fetched_count = written_count = 0
    seen_hashes: set[str] = set()
    try:
        # Query both areas. The public API has sometimes ignored `areq` and returned
        # both farms; full-row hashes make the collector safe in either behavior.
        for area_code in (1, 2):
            for fetched in client.iter_pages(
                endpoint=HILL_TRAINING_ENDPOINT,
                operation=HILL_TRAINING_OPERATION,
                public_params={
                    "areq": area_code,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                page_size=page_size,
                service_key_parameter="serviceKey",
            ):
                page_no = int(fetched.public_params["pageNo"])
                document_id = _store_source_document(
                    session,
                    fetched,
                    raw_data_dir=raw_data_dir,
                    data_type="horse_hill_training",
                    partition_date=end_date,
                    partition_name=f"area_{area_code}",
                    run_id=run.id,
                    page_no=page_no,
                )
                parsed = [HillTrainingItem.model_validate(item) for item in fetched.items]
                fetched_count += len(parsed)
                unique_items = [
                    item
                    for item in parsed
                    if item.source_row_hash not in seen_hashes
                    and not seen_hashes.add(item.source_row_hash)
                ]
                written_count += _upsert_hill_items(
                    session,
                    unique_items,
                    source_document_id=document_id,
                    observed_at_ms=fetched.retrieved_at_ms,
                )
                pages += 1
                _checkpoint_run(session, run, fetched_count, written_count)
        return _complete_run(session, run, pages, fetched_count, written_count)
    except Exception as exc:
        _fail_run(session, run.id, exc)
        raise


def _start_run(session: Session, source: str, data_type: str) -> IngestionRun:
    run = IngestionRun(
        source=source,
        data_type=data_type,
        started_at_ms=_now_ms(),
        status="running",
    )
    session.add(run)
    session.commit()
    return run


def _store_source_document(
    session: Session,
    fetched: FetchedXmlPage,
    *,
    raw_data_dir: Path,
    data_type: str,
    partition_date: str,
    partition_name: str,
    run_id: int,
    page_no: int,
) -> int:
    stored = store_kra_xml_page(
        fetched,
        raw_data_dir=raw_data_dir,
        data_type=data_type,
        partition_date=partition_date,
        partition_name=partition_name,
        run_id=run_id,
        page_no=page_no,
    )
    document = SourceDocument(
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
    session.add(document)
    session.flush()
    return document.id


def _upsert_swim_items(
    session: Session,
    items: Sequence[SwimTrainingItem],
    *,
    source_document_id: int,
    observed_at_ms: int,
) -> int:
    horse_ids = _horse_id_map(session, (item.horse_id for item in items))
    rows = [
        {
            "source_document_id": source_document_id,
            "horse_id": horse_ids.get(item.horse_id),
            "kra_horse_id_raw": item.horse_id,
            "horse_name_raw": item.horse_name,
            "meet_code": item.meet_code,
            "training_date_local": item.training_date,
            "swim_count": item.swim_count,
            "quality_status": item.quality_status,
            "stable_part": item.stable_part,
            "stable_note": item.stable_note,
            "trainer_part": item.trainer_part,
            "trainer_name": item.trainer_name,
            "observed_at_ms": observed_at_ms,
        }
        for item in items
    ]
    for batch in _chunks(rows, 1_000):
        statement = _dialect_insert(session, HorseSwimTraining).values(batch)
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[
                "kra_horse_id_raw",
                "meet_code",
                "training_date_local",
            ],
            set_={
                "source_document_id": excluded.source_document_id,
                "horse_id": func.coalesce(
                    excluded.horse_id, HorseSwimTraining.__table__.c.horse_id
                ),
                "horse_name_raw": excluded.horse_name_raw,
                "swim_count": excluded.swim_count,
                "quality_status": excluded.quality_status,
                "stable_part": excluded.stable_part,
                "stable_note": excluded.stable_note,
                "trainer_part": excluded.trainer_part,
                "trainer_name": excluded.trainer_name,
                "observed_at_ms": excluded.observed_at_ms,
            },
        )
        session.execute(statement)
    return len(rows)


def _upsert_hill_items(
    session: Session,
    items: Sequence[HillTrainingItem],
    *,
    source_document_id: int,
    observed_at_ms: int,
) -> int:
    horse_ids = _horse_id_map(session, (item.horse_id for item in items))
    rows = [
        {
            "source_document_id": source_document_id,
            "horse_id": horse_ids.get(item.horse_id),
            "kra_horse_id_raw": item.horse_id,
            "horse_name_raw": item.horse_name,
            "farm_name": item.farm_name,
            "tag_id": item.tag_id,
            "chip_id": item.chip_id,
            "sex_raw": item.sex,
            "birth_date": item.birth_date,
            "sire_name_raw": item.sire_name,
            "dam_name_raw": item.dam_name,
            "training_operator_name": item.training_operator_name,
            "owner_name_raw": item.owner_name,
            "farm_entry_date": item.farm_entry_date,
            "farm_entry_reason": item.farm_entry_reason,
            "training_date_local": item.training_date,
            "training_time_local": item.training_time,
            "f1_seconds": item.f1_seconds,
            "f2_seconds": item.f2_seconds,
            "f3_seconds": item.f3_seconds,
            "total_seconds": item.total_seconds,
            "quality_status": item.quality_status,
            "source_row_hash": item.source_row_hash,
            "observed_at_ms": observed_at_ms,
        }
        for item in items
    ]
    for batch in _chunks(rows, 500):
        statement = _dialect_insert(session, HorseHillTraining).values(batch)
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=["source_row_hash"],
            set_={
                "source_document_id": excluded.source_document_id,
                "horse_id": func.coalesce(
                    excluded.horse_id, HorseHillTraining.__table__.c.horse_id
                ),
                "quality_status": excluded.quality_status,
                "observed_at_ms": excluded.observed_at_ms,
            },
        )
        session.execute(statement)
    return len(rows)


def _horse_id_map(session: Session, horse_numbers: Iterable[str]) -> dict[str, int]:
    distinct = sorted(set(horse_numbers))
    if not distinct:
        return {}
    result: dict[str, int] = {}
    for batch in _chunks(distinct, 5_000):
        result.update(
            {
                horse_number: horse_id
                for horse_number, horse_id in session.execute(
                    select(Horse.kra_horse_id, Horse.id).where(
                        Horse.kra_horse_id.in_(batch)
                    )
                )
            }
        )
    return result


def _dedupe_swim_items(
    items: Sequence[SwimTrainingItem],
) -> list[SwimTrainingItem]:
    unique: dict[tuple[str, int, Any], SwimTrainingItem] = {}
    for item in items:
        key = (item.horse_id, item.meet_code, item.training_date)
        prior = unique.get(key)
        if prior is None:
            unique[key] = item
            continue
        if prior.model_dump(exclude_none=False) != item.model_dump(exclude_none=False):
            raise ValueError(f"수영조교 자연키에 서로 다른 원문이 있습니다: {key}")
    return list(unique.values())


def _dialect_insert(session: Session, model: type[Any]) -> Any:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql_insert(model)
    if dialect == "sqlite":
        return sqlite_insert(model)
    raise RuntimeError(f"지원하지 않는 DB dialect: {dialect}")


def _chunks(values: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _checkpoint_run(
    session: Session,
    run: IngestionRun,
    records_fetched: int,
    records_written: int,
) -> None:
    run.records_fetched = records_fetched
    run.records_written = records_written
    session.commit()


def _complete_run(
    session: Session,
    run: IngestionRun,
    pages: int,
    records_fetched: int,
    records_written: int,
) -> IngestionSummary:
    run.status = "completed"
    run.completed_at_ms = _now_ms()
    run.records_fetched = records_fetched
    run.records_written = records_written
    session.commit()
    return IngestionSummary(
        run_id=run.id,
        pages=pages,
        records_fetched=records_fetched,
        records_written=records_written,
    )


def _fail_run(session: Session, run_id: int, exc: Exception) -> None:
    session.rollback()
    run = session.get(IngestionRun, run_id)
    if run is not None:
        run.status = "failed"
        run.completed_at_ms = _now_ms()
        run.error_message = str(exc)
        session.commit()


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
