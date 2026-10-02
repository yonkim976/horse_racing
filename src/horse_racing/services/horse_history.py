from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
    HorseMedicalDiagnosis,
    HorseProfileSnapshot,
    HorseRatingSnapshot,
    HorseTraining,
    HorseWeightHistory,
    IngestionRun,
    MedicalDiagnosisTerm,
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
    """Archive API77 raw responses without updating operational rating snapshots.

    Operational ratings come from race_entries (entry cards/results). Retaining
    the original responses keeps the legacy source auditable without repeating
    its horse-only, cross-meet snapshot overwrite.
    """
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
        writer=lambda _session, _meet, _items: 0,
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
        writer=lambda sess, _meet, items: _write_profiles(
            sess,
            items,
            observed_at_ms,
            is_active=True if not include_inactive else None,
        ),
        race_date=snapshot_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def ingest_horse_active_statuses(
    session: Session,
    client: KraApiClient,
    *,
    meets: list[int],
    snapshot_date: str,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    """Refresh official active/inactive status, with active winning cross-meet conflicts."""
    if not meets or any(meet not in {1, 2, 3} for meet in meets):
        raise ValueError("meets는 1(서울), 2(제주), 3(부산경남) 중 하나 이상이어야 합니다.")

    observed_at_ms = _now_ms()
    run = IngestionRun(
        source="data.go.kr/B551015/API8_2",
        data_type="horse_active_statuses",
        started_at_ms=observed_at_ms,
        status="running",
    )
    session.add(run)
    session.commit()
    run_id = run.id

    active_items: dict[str, HorseDetailItem] = {}
    inactive_items: dict[str, HorseDetailItem] = {}
    pages = 0
    records_fetched = 0
    try:
        # A horse can be inactive at an old meet and active at its current meet.
        # Collect both complete sets first, then let the active union take precedence.
        for is_active in (False, True):
            scope = "active" if is_active else "inactive"
            target = active_items if is_active else inactive_items
            act_gubun = "y" if is_active else "n"
            for meet in meets:
                for fetched in client.iter_pages(
                    endpoint=RACE_HORSE_INFO_ENDPOINT,
                    operation=RACE_HORSE_INFO_OPERATION,
                    public_params={
                        "meet": meet,
                        "act_gubun": act_gubun,
                        "_type": "json",
                    },
                    page_size=page_size,
                    service_key_parameter="ServiceKey",
                ):
                    page_no = int(fetched.public_params["pageNo"])
                    stored = store_kra_page(
                        fetched,
                        raw_data_dir=raw_data_dir,
                        data_type=f"horse_active_statuses_{scope}",
                        race_date=snapshot_date,
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
                    parsed = parse_items(fetched.payload, HorseDetailItem)
                    target.update({item.horse_id: item for item in parsed})
                    records_fetched += len(parsed)
                    pages += 1
                    run.records_fetched = records_fetched
                    session.commit()

        status_items = {**inactive_items, **active_items}
        horse_ids = list(status_items)
        existing: dict[str, Horse] = {}
        for start in range(0, len(horse_ids), 5000):
            batch = horse_ids[start : start + 5000]
            existing.update(
                {
                    horse.kra_horse_id: horse
                    for horse in session.scalars(select(Horse).where(Horse.kra_horse_id.in_(batch)))
                }
            )

        for horse_id, item in status_items.items():
            horse = existing.get(horse_id)
            if horse is None:
                horse = Horse(kra_horse_id=horse_id, name_ko=item.horse_name)
                session.add(horse)
                existing[horse_id] = horse
            elif item.horse_name and item.horse_name != "(이름없음)":
                horse.name_ko = item.horse_name

            is_active = horse_id in active_items
            horse.is_active = is_active
            horse.active_status_observed_at_ms = observed_at_ms
            horse.active_status_source = (
                f"data.go.kr/B551015/API8_2:act_gubun={'y' if is_active else 'n'}"
            )
            if is_active and item.meet_code is not None:
                horse.meet_code = item.meet_code

        run.status = "completed"
        run.completed_at_ms = _now_ms()
        run.records_written = len(status_items)
        session.commit()
        return IngestionSummary(
            run_id=run_id,
            pages=pages,
            records_fetched=records_fetched,
            records_written=len(status_items),
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


def _write_ratings(
    session: Session,
    items: list[HorseRatingItem],
    observed_at_ms: int,
) -> int:
    horses = _history_horses(session, items)
    horse_ids = [horse.id for horse in horses.values()]
    existing: dict[int, HorseRatingSnapshot] = {}
    for start in range(0, len(horse_ids), 500):
        for row in session.scalars(
            select(HorseRatingSnapshot).where(
                HorseRatingSnapshot.horse_id.in_(horse_ids[start : start + 500]),
                HorseRatingSnapshot.observed_at_ms == observed_at_ms,
            )
        ):
            existing[row.horse_id] = row
    written = 0
    for item in items:
        horse = horses[item.horse_id]
        row = existing.get(horse.id)
        if row is None:
            row = HorseRatingSnapshot(horse_id=horse.id, observed_at_ms=observed_at_ms)
            session.add(row)
            existing[horse.id] = row
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
    # A nullable start/end time does not participate in PostgreSQL UNIQUE the
    # way a non-null key does. Serialize overlapping collectors before reading
    # existing rows, including records whose times have not been published.
    # Lock only the DB write phase (source pages were fetched beforehand).
    if session.get_bind().dialect.name == "postgresql":
        for meet, day in sorted({(item.meet_code, item.training_date) for item in items}):
            session.execute(
                text("SELECT pg_advisory_xact_lock(:namespace, :scope)"),
                {"namespace": 181001, "scope": meet * 100_000_000 + int(day.strftime("%Y%m%d"))},
            )
    horses = _history_horses(session, items)
    horse_ids = [horse.id for horse in horses.values()]
    dates = {item.training_date for item in items}
    existing: dict[tuple, HorseTraining] = {}
    for start in range(0, len(horse_ids), 500):
        for row in session.scalars(
            select(HorseTraining).where(
                HorseTraining.horse_id.in_(horse_ids[start : start + 500]),
                HorseTraining.training_date_local.in_(dates),
            )
        ):
            existing[
                (
                    row.horse_id,
                    row.meet_code,
                    row.training_date_local,
                    row.started_at_raw,
                    row.ended_at_raw,
                )
            ] = row
    written = 0
    for item in items:
        horse = horses[item.horse_id]
        key = (horse.id, item.meet_code, item.training_date, item.started_at_raw, item.ended_at_raw)
        row = existing.get(key)
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
            existing[key] = row
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
    names = sorted(
        {
            text.strip()
            for item in items
            for text in (item.diagnosis_1, item.diagnosis_2)
            if text and text.strip() not in ("", "-")
        }
    )
    dialect_name = session.get_bind().dialect.name
    for start in range(0, len(names), 500):
        batch = names[start : start + 500]
        values = [{"raw_text": name} for name in batch]
        if dialect_name == "postgresql":
            statement = postgres_insert(MedicalDiagnosisTerm).values(values)
        elif dialect_name == "sqlite":
            statement = sqlite_insert(MedicalDiagnosisTerm).values(values)
        else:
            raise NotImplementedError(f"Unsupported medical term dialect: {dialect_name}")
        session.execute(statement.on_conflict_do_nothing(index_elements=["raw_text"]))
    terms: dict[str, MedicalDiagnosisTerm] = {}
    for start in range(0, len(names), 500):
        for term in session.scalars(
            select(MedicalDiagnosisTerm).where(
                MedicalDiagnosisTerm.raw_text.in_(names[start : start + 500])
            )
        ):
            terms[term.raw_text] = term

    written = 0
    records: list[tuple[HorseMedical, HorseMedicalItem]] = []
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
        records.append((row, item))
        written += 1

    if not records:
        return written
    session.flush()
    medical_ids = sorted({row.id for row, _ in records})
    existing_links: dict[tuple[int, int], HorseMedicalDiagnosis] = {}
    for start in range(0, len(medical_ids), 500):
        for link in session.scalars(
            select(HorseMedicalDiagnosis).where(
                HorseMedicalDiagnosis.horse_medical_id.in_(medical_ids[start : start + 500])
            )
        ):
            existing_links[(link.horse_medical_id, link.source_slot)] = link
    for row, item in records:
        for slot, raw_text in ((1, item.diagnosis_1), (2, item.diagnosis_2)):
            if not raw_text or raw_text.strip() in ("", "-"):
                continue
            key = (row.id, slot)
            term_id = terms[raw_text.strip()].id
            link = existing_links.get(key)
            if link is None:
                link = HorseMedicalDiagnosis(
                    horse_medical_id=row.id,
                    source_slot=slot,
                    term_id=term_id,
                )
                session.add(link)
                existing_links[key] = link
            elif link.term_id != term_id:
                link.term_id = term_id
    return written


def _write_profiles(
    session: Session,
    items: list[HorseDetailItem],
    observed_at_ms: int,
    *,
    is_active: bool | None,
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
        if is_active is not None:
            horse.is_active = is_active
            horse.active_status_observed_at_ms = observed_at_ms
            horse.active_status_source = "data.go.kr/B551015/API8_2:act_gubun=y"

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


def _history_horses(
    session: Session,
    items: list[HorseRatingItem] | list[HorseTrainingItem],
) -> dict[str, Horse]:
    """Resolve a history batch without a network round trip for every runner."""
    horse_ids = sorted({item.horse_id for item in items})
    horses: dict[str, Horse] = {}
    for start in range(0, len(horse_ids), 500):
        for horse in session.scalars(
            select(Horse).where(Horse.kra_horse_id.in_(horse_ids[start : start + 500]))
        ):
            horses[horse.kra_horse_id] = horse
    for item in items:
        horse = horses.get(item.horse_id)
        if horse is None:
            horse = Horse(kra_horse_id=item.horse_id, name_ko=item.horse_name)
            session.add(horse)
            horses[item.horse_id] = horse
        elif item.horse_name and item.horse_name != "(이름없음)":
            horse.name_ko = item.horse_name
    session.flush()
    return horses


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
    writer_with_sources=None,
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
    item_sources: list[tuple[int, int]] = []
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
            page_items = parse_items(fetched.payload, item_model)
            item_sources.extend((document.id, n) for n in range(1, len(page_items) + 1))
            parsed_items.extend(page_items)
            pages += 1
            run.records_fetched = len(parsed_items)
            session.commit()

        records_written = (
            writer_with_sources(session, meet, parsed_items, item_sources)
            if writer_with_sources is not None
            else writer(session, meet, parsed_items)
        )
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
