from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_text import KraTextClient
from horse_racing.db.models import (
    Horse,
    IngestionRun,
    Jockey,
    RunningTrial,
    RunningTrialResult,
    SourceDocument,
    Trainer,
)
from horse_racing.parsers.running_trials import (
    RunningTrialData,
    RunningTrialResultData,
    parse_running_trial_report,
)
from horse_racing.services.raw_store import store_kra_text_report


@dataclass(frozen=True, slots=True)
class RunningTrialIngestionSummary:
    run_id: int
    files: int
    trials: int
    records_fetched: int
    records_written: int
    horses_linked: int
    horses_unresolved: int


def ingest_running_trials(
    session: Session,
    client: KraTextClient,
    *,
    start_date: date,
    end_date: date,
    meets: list[int],
    raw_data_dir: Path,
) -> RunningTrialIngestionSummary:
    started_at_ms = _now_ms()
    run = IngestionRun(
        source="race.kra.co.kr/dbdata",
        data_type="running_trials",
        started_at_ms=started_at_ms,
        status="running",
    )
    session.add(run)
    session.commit()

    files_count = 0
    trial_count = 0
    fetched_count = 0
    written_count = 0
    linked_count = 0
    unresolved_count = 0
    horse_candidates_by_name = _horse_candidates_by_name(
        session.scalars(select(Horse)).all()
    )
    jockey_by_name = _unique_name_map(session.scalars(select(Jockey)).all())
    trainer_by_name = _unique_name_map(session.scalars(select(Trainer)).all())

    try:
        for meet in meets:
            for listed_file in client.iter_running_trial_files(
                meet=meet,
                start_date=start_date,
                end_date=end_date,
            ):
                fetched = client.fetch_file(listed_file)
                stored = store_kra_text_report(fetched, raw_data_dir=raw_data_dir)
                document = SourceDocument(
                    ingestion_run_id=run.id,
                    source_url=fetched.source_url,
                    endpoint="/dbdata/fileDownLoad.do",
                    operation="dacom23",
                    request_params_json=json.dumps(
                        {
                            "meet": meet,
                            "fn": listed_file.remote_path,
                            "list_page": listed_file.list_page,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
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

                trials = parse_running_trial_report(fetched.body, meet=meet)
                for trial_data in trials:
                    trial, was_written, linked, unresolved = _write_trial(
                        session,
                        meet=meet,
                        data=trial_data,
                        source_document_id=document.id,
                        observed_at_ms=fetched.retrieved_at_ms,
                        horse_candidates_by_name=horse_candidates_by_name,
                        jockey_by_name=jockey_by_name,
                        trainer_by_name=trainer_by_name,
                    )
                    trial_count += 1
                    fetched_count += len(trial_data.results)
                    written_count += was_written
                    linked_count += linked
                    unresolved_count += unresolved
                    session.flush()
                    if trial.id is None:
                        raise RuntimeError("주행심사 경주 ID가 생성되지 않았습니다.")
                files_count += 1
                session.commit()
                time.sleep(0.05)

        run.status = "completed"
        run.completed_at_ms = _now_ms()
        run.records_fetched = fetched_count
        run.records_written = written_count
        session.commit()
    except Exception as exc:
        session.rollback()
        failed_run = session.get(IngestionRun, run.id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.completed_at_ms = _now_ms()
            failed_run.records_fetched = fetched_count
            failed_run.records_written = written_count
            failed_run.error_message = str(exc)[:2000]
            session.commit()
        raise

    return RunningTrialIngestionSummary(
        run_id=run.id,
        files=files_count,
        trials=trial_count,
        records_fetched=fetched_count,
        records_written=written_count,
        horses_linked=linked_count,
        horses_unresolved=unresolved_count,
    )


def _write_trial(
    session: Session,
    *,
    meet: int,
    data: RunningTrialData,
    source_document_id: int,
    observed_at_ms: int,
    horse_candidates_by_name: dict[str, list[Horse]],
    jockey_by_name: dict[str, Jockey],
    trainer_by_name: dict[str, Trainer],
) -> tuple[RunningTrial, int, int, int]:
    trial = session.scalar(
        select(RunningTrial).where(
            RunningTrial.meet_code == meet,
            RunningTrial.trial_date_local == data.trial_date,
            RunningTrial.trial_race_number == data.trial_race_number,
        )
    )
    if trial is None:
        trial = RunningTrial(
            meet_code=meet,
            trial_date_local=data.trial_date,
            trial_race_number=data.trial_race_number,
            distance_m=data.distance_m,
            observed_at_ms=observed_at_ms,
        )
        session.add(trial)
        session.flush()
    trial.source_document_id = source_document_id
    trial.trial_round = data.trial_round
    trial.distance_m = data.distance_m
    trial.weather = data.weather
    trial.track_condition = data.track_condition
    trial.track_moisture_percent = data.track_moisture_percent
    trial.observed_at_ms = observed_at_ms

    written = 0
    linked = 0
    unresolved = 0
    for item in data.results:
        horse = _resolve_horse(
            horse_candidates_by_name.get(item.horse_name, []),
            meet=meet,
            trial_date=data.trial_date,
            sex=item.sex,
            age=item.age,
        )
        jockey = jockey_by_name.get(item.jockey_name or "")
        trainer = trainer_by_name.get(item.trainer_name or "")
        result = session.scalar(
            select(RunningTrialResult).where(
                RunningTrialResult.running_trial_id == trial.id,
                RunningTrialResult.horse_number == item.horse_number,
            )
        )
        if result is None:
            result = RunningTrialResult(
                running_trial_id=trial.id,
                horse_number=item.horse_number,
                horse_name_raw=item.horse_name,
                observed_at_ms=observed_at_ms,
            )
            session.add(result)
        _assign_result(
            result,
            item,
            horse_id=horse.id if horse else None,
            jockey_id=jockey.id if jockey else None,
            trainer_id=trainer.id if trainer else None,
            observed_at_ms=observed_at_ms,
        )
        written += 1
        if horse is None:
            unresolved += 1
        else:
            linked += 1
    return trial, written, linked, unresolved


def _assign_result(
    result: RunningTrialResult,
    item: RunningTrialResultData,
    *,
    horse_id: int | None,
    jockey_id: int | None,
    trainer_id: int | None,
    observed_at_ms: int,
) -> None:
    result.horse_id = horse_id
    result.jockey_id = jockey_id
    result.trainer_id = trainer_id
    result.horse_name_raw = item.horse_name
    result.finish_position = item.finish_position
    result.finish_rank_raw = item.finish_rank_raw
    result.origin_country = item.origin_country
    result.sex = item.sex
    result.age = item.age
    result.carried_weight_base_kg = item.carried_weight_base_kg
    result.carried_weight_extra_kg = item.carried_weight_extra_kg
    result.carried_weight_raw = item.carried_weight_raw
    result.jockey_name_raw = item.jockey_name
    result.trainer_name_raw = item.trainer_name
    result.body_weight_kg = item.body_weight_kg
    result.finish_time_ms = item.finish_time_ms
    result.margin_text = item.margin_text
    result.judgement = item.judgement
    result.failure_reason = item.failure_reason
    result.inspection_reason = item.inspection_reason
    result.g3f_ms = item.g3f_ms
    result.s1f_ms = item.s1f_ms
    result.corner_3_ms = item.corner_3_ms
    result.corner_4_ms = item.corner_4_ms
    result.g1f_ms = item.g1f_ms
    result.section_400_ms = item.section_400_ms
    result.final_400_ms = item.final_400_ms
    result.passing_order_raw = item.passing_order_raw
    result.observed_at_ms = observed_at_ms


def _horse_candidates_by_name(entities: list[Horse]) -> dict[str, list[Horse]]:
    candidates: dict[str, list[Horse]] = {}
    for entity in entities:
        candidates.setdefault(entity.name_ko, []).append(entity)
    return candidates


def _resolve_horse(
    candidates: list[Horse],
    *,
    meet: int,
    trial_date: date,
    sex: str | None,
    age: int | None,
) -> Horse | None:
    same_meet = [horse for horse in candidates if horse.meet_code == meet]
    if len(same_meet) == 1:
        return same_meet[0]
    if len(candidates) == 1:
        return candidates[0]
    if age is None:
        return None
    signature_matches = [
        horse
        for horse in candidates
        if horse.birth_date is not None
        and trial_date.year - horse.birth_date.year == age
        and (sex is None or horse.sex == sex)
    ]
    return signature_matches[0] if len(signature_matches) == 1 else None


def _unique_name_map[T: Jockey | Trainer](entities: list[T]) -> dict[str, T]:
    candidates: dict[str, list[T]] = {}
    for entity in entities:
        name = entity.name_ko
        candidates.setdefault(name, []).append(entity)
    return {name: values[0] for name, values in candidates.items() if len(values) == 1}


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
