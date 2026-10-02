"""Current Jeju website snapshots, without importing research code or databases."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from horse_racing.db.models import Horse, HorseStartTraining, IngestionRun, SourceDocument
from horse_racing.parsers.start_training_website import parse_start_training_website
from horse_racing.services.entry_sheet import IngestionSummary

URL = "https://race.kra.co.kr/startingData/getStartingTrainListAll.do"


def ingest_jeju_start_training_website(
    session: Session,
    client: httpx.Client,
    *,
    training_date: str,
    raw_data_dir: Path,
) -> IngestionSummary:
    day = datetime.strptime(training_date, "%Y%m%d").date()
    if day.strftime("%Y%m%d") != training_date:
        raise ValueError("홈페이지 출발조교 날짜는 YYYYMMDD여야 합니다.")
    params = {
        "Act": "07",
        "Sub": "2",
        "meet": "2",
        "trDate": day.strftime("%Y/%m/%d"),
        "trDateReplace": training_date,
        "trNo": "",
        "trName": "",
    }
    requested = time.time_ns() // 1_000_000
    # Fixed public host; do not follow redirects to an unvalidated location.
    with client.stream("GET", URL, params=params, follow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError(f"제주 출발조교 홈페이지 HTTP {response.status_code}")
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("제주 출발조교 홈페이지 응답 크기 초과")
        source_url = str(response.url)
        content_type = response.headers.get("content-type")
    observed = time.time_ns() // 1_000_000
    records = parse_start_training_website(bytes(raw), training_date)
    run = IngestionRun(
        source="KRA Jeju starting-training website",
        data_type="horse_start_training_website",
        started_at_ms=requested,
        status="running",
    )
    session.add(run)
    session.commit()
    try:
        digest = hashlib.sha256(raw).hexdigest()
        directory = raw_data_dir / "kra" / "horse_start_training_website" / training_date
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"run_{run.id}_{observed}_{digest[:12]}.html"
        path.write_bytes(raw)
        document = SourceDocument(
            ingestion_run_id=run.id,
            source_url=source_url,
            endpoint="/startingData/getStartingTrainListAll.do",
            operation="verified_jeju_website_snapshot",
            request_params_json=json.dumps(params, ensure_ascii=False),
            requested_at_ms=requested,
            retrieved_at_ms=observed,
            http_status_code=200,
            content_type=content_type,
            response_bytes=len(raw),
            local_path=str(path),
            sha256=digest,
        )
        session.add(document)
        session.flush()
        if session.get_bind().dialect.name == "postgresql":
            # Same date lock as the API22 writer; both protect the website authority.
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": 200_000_000 + int(training_date)},
            )
        horses = dict(session.execute(select(Horse.kra_horse_id, Horse.id)).all())
        selected = [r for r in records if r["horse_id_raw"] in horses]
        existing = session.scalars(
            select(HorseStartTraining).where(
                HorseStartTraining.meet_code == 2,
                HorseStartTraining.training_date_local == day,
            )
        ).all()
        written = 0
        if selected and not any(r.observed_at_ms > observed for r in existing):
            slots = {(r.horse_id, r.occurrence_no): r for r in existing}
            occurrences, retained = Counter(), set()
            for item in selected:
                horse_id = horses[item["horse_id_raw"]]
                occurrences[horse_id] += 1
                key = (horse_id, occurrences[horse_id])
                row = slots.get(key)
                if row is None:
                    row = HorseStartTraining(
                        horse_id=horse_id,
                        meet_code=2,
                        training_date_local=day,
                        occurrence_no=key[1],
                    )
                    session.add(row)
                row.stable_part = item["stable_part"]
                row.stable_number = item["stable_number"]
                row.rider_name = item["rider"] or None
                row.remark = item["note"] or None
                row.location_raw = item["location"]
                row.source_kind = "kra_website"
                row.source_document_id, row.source_row_no = document.id, item["source_row_no"]
                row.observed_at_ms = observed
                retained.add(key)
                written += 1
            # Replace only a validated non-empty snapshot; raw prior versions stay archived.
            for key, row in slots.items():
                if key not in retained:
                    session.delete(row)
        run.records_fetched, run.records_written = len(records), written
        run.status, run.completed_at_ms = "completed", time.time_ns() // 1_000_000
        session.commit()
        return IngestionSummary(run.id, 1, len(records), written)
    except Exception as exc:
        session.rollback()
        saved = session.get(IngestionRun, run.id)
        saved.status, saved.completed_at_ms = "failed", time.time_ns() // 1_000_000
        saved.error_message = type(exc).__name__
        session.commit()
        raise
