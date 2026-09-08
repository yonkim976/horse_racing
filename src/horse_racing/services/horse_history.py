from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import (
    DAILY_TRAINING_ENDPOINT,
    DAILY_TRAINING_OPERATION,
    ENTRY_HORSE_WEIGHT_ENDPOINT,
    ENTRY_HORSE_WEIGHT_OPERATION,
    RACE_HORSE_CLINIC_ENDPOINT,
    RACE_HORSE_CLINIC_OPERATION,
    RACE_HORSE_INFO_ENDPOINT,
    RACE_HORSE_INFO_OPERATION,
    RACE_HORSE_RATING_ENDPOINT,
    RACE_HORSE_RATING_OPERATION,
    KraApiClient,
)
from horse_racing.db.models import (
    Horse,
    HorseMedical,
    HorseProfileSnapshot,
    HorseRatingSnapshot,
    HorseTraining,
    HorseWeightHistory,
    IngestionRun,
    Owner,
    SourceDocument,
    Trainer,
)
from horse_racing.parsers.horse_history import (
    HorseDetailItem,
    HorseMedicalItem,
    HorseRatingItem,
    HorseTrainingItem,
    HorseWeightItem,
)
from horse_racing.parsers.race_day import parse_items
from horse_racing.services.entry_sheet import IngestionSummary
from horse_racing.services.race_day import DatasetDefinition
from horse_racing.services.raw_store import store_kra_page


def ingest_ratings(
    session: Session,
    client: KraApiClient,
    *,
    snapshot_date: str,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    observed_at_ms = _now_ms()
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="horse_ratings",
            source="data.go.kr/B551015/API77",
            endpoint=RACE_HORSE_RATING_ENDPOINT,
            operation=RACE_HORSE_RATING_OPERATION,
            public_params={"_type": "json"},
        ),
        item_model=HorseRatingItem,
        writer=lambda sess, _meet, items: _write_ratings(sess, items, observed_at_ms),
        race_date=snapshot_date,
        meet=0,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def ingest_weights(
    session: Session,
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    observed_at_ms = _now_ms()
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="horse_weights",
            source="data.go.kr/B551015/API25_1",
            endpoint=ENTRY_HORSE_WEIGHT_ENDPOINT,
            operation=ENTRY_HORSE_WEIGHT_OPERATION,
            public_params={"meet": meet, "rc_date": race_date, "_type": "json"},
        ),
        item_model=HorseWeightItem,
        writer=lambda sess, _meet, items: _write_weights(sess, items, observed_at_ms),
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def ingest_training(
    session: Session,
    client: KraApiClient,
    *,
    training_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    observed_at_ms = _now_ms()
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="horse_training",
            source="data.go.kr/B551015/API18_1",
            endpoint=DAILY_TRAINING_ENDPOINT,
            operation=DAILY_TRAINING_OPERATION,
            public_params={"meet": meet, "tr_date": training_date, "_type": "json"},
        ),
        item_model=HorseTrainingItem,
        writer=lambda sess, _meet, items: _write_training(sess, items, observed_at_ms),
        race_date=training_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def ingest_medical(
    session: Session,
    client: KraApiClient,
    *,
    clinic_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    observed_at_ms = _now_ms()
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="horse_medical",
            source="data.go.kr/B551015/API16_1",
            endpoint=RACE_HORSE_CLINIC_ENDPOINT,
            operation=RACE_HORSE_CLINIC_OPERATION,
            public_params={"meet": meet, "clinic_date": clinic_date, "_type": "json"},
        ),
        item_model=HorseMedicalItem,
        writer=lambda sess, _meet, items: _write_medical(sess, items, observed_at_ms),
        race_date=clinic_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def ingest_horse_profiles(
    session: Session,
    client: KraApiClient,
    *,
    meet: int,
    snapshot_date: str,
    raw_data_dir: Path,
    page_size: int = 1000,
    include_inactive: bool = False,
) -> IngestionSummary:
    observed_at_ms = _now_ms()
    public_params: dict[str, str | int] = {"meet": meet, "_type": "json"}
    if include_inactive:
        public_params["act_gubun"] = "n"
    else:
        public_params["act_gubun"] = "y"
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="horse_profiles",
            source="data.go.kr/B551015/API8_2",
            endpoint=RACE_HORSE_INFO_ENDPOINT,
            operation=RACE_HORSE_INFO_OPERATION,
            public_params=public_params,
        ),
        item_model=HorseDetailItem,
        writer=lambda sess, _meet, items: _write_profiles(sess, items, observed_at_ms),
        race_date=snapshot_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def _write_ratings(
    session: Session,
    items: list[HorseRatingItem],
    observed_at_ms: int,
) -> int:
    written = 0
    for item in items:
        horse = _upsert_horse(session, item.horse_id, item.horse_name)
        row = session.scalar(
            select(HorseRatingSnapshot).where(
                HorseRatingSnapshot.horse_id == horse.id,
                HorseRatingSnapshot.observed_at_ms == observed_at_ms,
            )
        )
        if row is None:
            row = HorseRatingSnapshot(horse_id=horse.id, observed_at_ms=observed_at_ms)
            session.add(row)
        row.meet_code = item.meet_code
        row.rating_1 = item.rating_1
        row.rating_2 = item.rating_2
        row.rating_3 = item.rating_3
        row.rating_4 = item.rating_4
        written += 1
    return written


def _write_weights(
    session: Session,
    items: list[HorseWeightItem],
    observed_at_ms: int,
) -> int:
    written = 0
    for item in items:
        horse = _upsert_horse(session, item.horse_id, item.horse_name)
        row = session.scalar(
            select(HorseWeightHistory).where(
                HorseWeightHistory.horse_id == horse.id,
                HorseWeightHistory.meet_code == item.meet_code,
                HorseWeightHistory.race_date_local == item.race_date,
                HorseWeightHistory.race_number == item.race_number,
                HorseWeightHistory.horse_number == item.horse_number,
            )
        )
        if row is None:
            row = HorseWeightHistory(
                horse_id=horse.id,
                meet_code=item.meet_code,
                race_date_local=item.race_date,
                race_number=item.race_number,
                horse_number=item.horse_number,
                observed_at_ms=observed_at_ms,
            )
            session.add(row)
        row.body_weight_kg = item.body_weight_kg
        row.body_weight_change_kg = item.body_weight_change_kg
        row.observed_at_ms = observed_at_ms
        written += 1
    return written


def _write_training(
    session: Session,
    items: list[HorseTrainingItem],
    observed_at_ms: int,
) -> int:
    written = 0
    for item in items:
        horse = _upsert_horse(session, item.horse_id, item.horse_name)
        row = session.scalar(
            select(HorseTraining).where(
                HorseTraining.horse_id == horse.id,
                HorseTraining.meet_code == item.meet_code,
                HorseTraining.training_date_local == item.training_date,
                HorseTraining.started_at_raw == item.started_at_raw,
                HorseTraining.ended_at_raw == item.ended_at_raw,
            )
        )
        if row is None:
            row = HorseTraining(
                horse_id=horse.id,
                meet_code=item.meet_code,
                training_date_local=item.training_date,
                started_at_raw=item.started_at_raw,
                ended_at_raw=item.ended_at_raw,
                observed_at_ms=observed_at_ms,
            )
            session.add(row)
        row.stable_part = item.stable_part
        row.stable_number = item.stable_number
        row.trainer_name = item.trainer_name
        row.rider_type = item.rider_type
        row.rider_id = item.rider_id
        row.duration_seconds = item.duration_seconds
        row.canter_count = item.canter_count
        row.gallop_count = item.gallop_count
        row.entry_plan = item.entry_plan
        row.observed_at_ms = observed_at_ms
        written += 1
    return written


def _write_medical(
    session: Session,
    items: list[HorseMedicalItem],
    observed_at_ms: int,
) -> int:
    written = 0
    for item in items:
        horse = _upsert_horse(session, item.horse_id, item.horse_name)
        row = session.scalar(
            select(HorseMedical).where(
                HorseMedical.horse_id == horse.id,
                HorseMedical.meet_code == item.meet_code,
                HorseMedical.clinic_date_local == item.clinic_date,
                HorseMedical.hospital_name == item.hospital_name,
                HorseMedical.diagnosis_1 == item.diagnosis_1,
                HorseMedical.diagnosis_2 == item.diagnosis_2,
            )
        )
        if row is None:
            row = HorseMedical(
                horse_id=horse.id,
                meet_code=item.meet_code,
                clinic_date_local=item.clinic_date,
                hospital_name=item.hospital_name,
                diagnosis_1=item.diagnosis_1,
                diagnosis_2=item.diagnosis_2,
                observed_at_ms=observed_at_ms,
            )
            session.add(row)
        row.stable_part = item.stable_part
        row.observed_at_ms = observed_at_ms
        written += 1
    return written


def _write_profiles(
    session: Session,
    items: list[HorseDetailItem],
    observed_at_ms: int,
) -> int:
    written = 0
    for item in items:
        horse = _upsert_horse(session, item.horse_id, item.horse_name)
        horse.name_ko = item.horse_name
        if item.sex:
            horse.sex = item.sex
        if item.birth_date is not None:
            horse.birth_date = item.birth_date
        if item.origin_country:
            horse.origin_country = item.origin_country
        if item.grade:
            horse.grade = item.grade
        if item.meet_code is not None:
            horse.meet_code = item.meet_code
        if item.sire_id:
            horse.sire_kra_id = item.sire_id
        if item.sire_name:
            horse.sire_name = item.sire_name
        if item.dam_id:
            horse.dam_kra_id = item.dam_id
        if item.dam_name:
            horse.dam_name = item.dam_name
        if item.last_sale_amount_raw:
            horse.last_sale_amount_raw = item.last_sale_amount_raw
        horse.profile_observed_at_ms = observed_at_ms

        if item.trainer_id:
            _upsert_person(session, Trainer, "kra_trainer_id", item.trainer_id, item.trainer_name)
        if item.owner_id:
            _upsert_person(session, Owner, "kra_owner_id", item.owner_id, item.owner_name)

        row = session.scalar(
            select(HorseProfileSnapshot).where(
                HorseProfileSnapshot.horse_id == horse.id,
                HorseProfileSnapshot.observed_at_ms == observed_at_ms,
            )
        )
        if row is None:
            row = HorseProfileSnapshot(horse_id=horse.id, observed_at_ms=observed_at_ms)
            session.add(row)
        row.meet_code = item.meet_code
        row.grade = item.grade
        row.rating = item.rating
        row.race_count_total = item.race_count_total
        row.race_count_year = item.race_count_year
        row.win_count_total = item.win_count_total
        row.win_count_year = item.win_count_year
        row.second_count_total = item.second_count_total
        row.second_count_year = item.second_count_year
        row.third_count_total = item.third_count_total
        row.third_count_year = item.third_count_year
        row.prize_money_total_krw = item.prize_money_total_krw
        row.last_sale_amount_raw = item.last_sale_amount_raw
        row.trainer_kra_id = item.trainer_id
        row.trainer_name = item.trainer_name
        row.owner_kra_id = item.owner_id
        row.owner_name = item.owner_name
        written += 1
    return written


def _upsert_person(
    session: Session,
    model: type[Trainer] | type[Owner],
    id_attribute: str,
    kra_id: str,
    name_ko: str | None,
) -> None:
    id_column = getattr(model, id_attribute)
    person = session.scalar(select(model).where(id_column == kra_id))
    if person is None:
        person = model(**{id_attribute: kra_id, "name_ko": name_ko or kra_id})
        session.add(person)
    if name_ko:
        person.name_ko = name_ko
    session.flush()


def _upsert_horse(session: Session, kra_horse_id: str, name_ko: str) -> Horse:
    horse = session.scalar(select(Horse).where(Horse.kra_horse_id == kra_horse_id))
    if horse is None:
        horse = Horse(kra_horse_id=kra_horse_id, name_ko=name_ko)
        session.add(horse)
        session.flush()
        return horse
    if name_ko and name_ko != "(이름없음)":
        horse.name_ko = name_ko
    session.flush()
    return horse


def _ingest_dataset[ItemT: BaseModel](
    session: Session,
    client: KraApiClient,
    *,
    definition: DatasetDefinition,
    item_model: type[ItemT],
    writer,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int,
) -> IngestionSummary:
    run = IngestionRun(
        source=definition.source,
        data_type=definition.data_type,
        started_at_ms=_now_ms(),
        status="running",
    )
    session.add(run)
    session.commit()
    run_id = run.id

    parsed_items: list[ItemT] = []
    pages = 0
    try:
        for fetched in client.iter_pages(
            endpoint=definition.endpoint,
            operation=definition.operation,
            public_params=definition.public_params,
            page_size=page_size,
            service_key_parameter="ServiceKey",
        ):
            page_no = int(fetched.public_params["pageNo"])
            stored = store_kra_page(
                fetched,
                raw_data_dir=raw_data_dir,
                data_type=definition.data_type,
                race_date=race_date,
                meet=meet,
                run_id=run_id,
                page_no=page_no,
            )
            session.add(
                SourceDocument(
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
            )
            parsed_items.extend(parse_items(fetched.payload, item_model))
            pages += 1
            run.records_fetched = len(parsed_items)
            session.commit()

        records_written = writer(session, meet, parsed_items)
        run.status = "completed"
        run.completed_at_ms = _now_ms()
        run.records_written = records_written
        session.commit()
        return IngestionSummary(
            run_id=run_id,
            pages=pages,
            records_fetched=len(parsed_items),
            records_written=records_written,
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


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
