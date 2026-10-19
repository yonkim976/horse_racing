"""Bounded official profile snapshots for upcoming runners; no page-load HTTP."""

import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from horse_racing.db.models import (
    Horse,
    HorseTraining,
    HorseTrainingRiderObservation,
    IngestionRun,
    Race,
    RaceEntry,
    SourceDocument,
)
from horse_racing.parsers.training_riders_website import parse_training_riders
from horse_racing.services.training_rider_evidence import training_event_key, training_fingerprint

URL = "https://race.kra.co.kr/racehorse/profileTrainState.do"
MAX_PAGE_BYTES = 2 * 1024 * 1024


def upcoming_training_horses(session, *, as_of, race_ids=()):
    cards = (
        select(RaceEntry.horse_id)
        .join(Race, Race.id == RaceEntry.race_id)
        .where(RaceEntry.scratched.is_(False))
    )
    if race_ids:
        cards = cards.where(Race.id.in_(race_ids))
    else:
        cards = cards.where(
            Race.status == "scheduled",
            Race.race_date_local >= as_of,
            Race.race_date_local <= as_of + timedelta(days=7),
        )
    # An away fixture does not change the venue where the actual training took place.
    query = (
        select(Horse.id, Horse.kra_horse_id, Horse.name_ko, HorseTraining.meet_code)
        .join(HorseTraining, HorseTraining.horse_id == Horse.id)
        .where(
            Horse.id.in_(cards),
            HorseTraining.meet_code.in_((1, 2, 3)),
            HorseTraining.training_date_local >= as_of - timedelta(days=28),
            HorseTraining.training_date_local <= as_of,
        )
    )
    return session.execute(query.distinct().order_by(HorseTraining.meet_code, Horse.id)).all()


def ingest_training_riders(session, client, *, horse, as_of, raw_data_dir: Path):
    if session.new or session.dirty or session.deleted:
        raise ValueError("Commit caller changes before collecting rider evidence")
    horse_id, official_id, horse_name, meet = horse
    if not re.fullmatch(r"\d{1,12}", official_id) or meet not in (1, 2, 3):
        raise ValueError("Invalid official horse key")
    records = session.scalars(
        select(HorseTraining).where(
            HorseTraining.horse_id == horse_id,
            HorseTraining.meet_code == meet,
            HorseTraining.training_date_local >= as_of - timedelta(days=28),
            HorseTraining.training_date_local <= as_of,
        )
    ).all()
    if not records:
        return {"horse": official_id, "fetched": 0, "matched": 0, "ambiguous": 0}
    keys = defaultdict(list)
    fingerprints = {row.id: training_fingerprint(row) for row in records}
    for row in records:
        if (key := training_event_key(row)) is not None:
            keys[key].append(row.id)
    # End the read transaction before the public website request.
    session.rollback()
    requested = time.time_ns() // 1_000_000
    params = {"Act": "02", "Sub": "1", "hrNo": official_id, "meet": str(meet)}
    with client.stream("GET", URL, params=params, follow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError(f"Official training profile HTTP {response.status_code}")
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > MAX_PAGE_BYTES:
                raise ValueError("Training profile response too large")
        source_url = str(response.url)
        content_type = response.headers.get("content-type")
    rejected_rows = []
    rows = parse_training_riders(
        bytes(raw),
        horse_name=horse_name,
        start_date=as_of - timedelta(days=28),
        end_date=as_of,
        rejected_rows=rejected_rows,
    )
    observed = time.time_ns() // 1_000_000
    web_keys = defaultdict(list)
    for row in rows:
        web_keys[(row["date"], row["start"], row["end"], row["seconds"])].append(row)
    digest = hashlib.sha256(raw).hexdigest()
    directory = raw_data_dir / "kra" / "training_riders_website" / str(as_of)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{meet}_{official_id}_{observed}_{digest[:12]}.html"
    path.write_bytes(raw)
    run = IngestionRun(
        source="KRA horse-profile training rider legend",
        data_type="training_riders_website",
        started_at_ms=requested,
        status="running",
    )
    session.add(run)
    session.flush()
    document = SourceDocument(
        ingestion_run_id=run.id,
        source_url=source_url,
        endpoint="/racehorse/profileTrainState.do",
        operation="same_event_rider_evidence",
        request_params_json=json.dumps(params),
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
    # Re-read and lock: API updates after the HTTP request must not inherit stale evidence.
    current = {
        r.id: r
        for r in session.scalars(
            select(HorseTraining).where(HorseTraining.id.in_(list(fingerprints))).with_for_update()
        ).all()
    }
    values_to_write, ambiguous = [], 0
    for key, api_rows in keys.items():
        matches = web_keys.get(key, [])
        if len(api_rows) != 1 or len(matches) != 1:
            ambiguous += bool(matches)
            continue
        api, web = current.get(api_rows[0]), matches[0]
        if api is None or training_fingerprint(api) != fingerprints[api.id]:
            continue
        values = dict(
            horse_training_id=api.id,
            source_document_id=document.id,
            source_row_no=web["source_row_no"],
            source_fingerprint=training_fingerprint(api),
            rider_label_raw=web["raw"],
            rider_role=web["role"],
            jockey_name=web["name"],
            observed_at_ms=observed,
        )
        values_to_write.append(values)
    written = 0
    if values_to_write:
        insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
        statement = insert(HorseTrainingRiderObservation).values(values_to_write)
        result = session.execute(
            statement.on_conflict_do_update(
                index_elements=[HorseTrainingRiderObservation.horse_training_id],
                set_={
                    k: statement.excluded[k] for k in values_to_write[0] if k != "horse_training_id"
                },
                where=HorseTrainingRiderObservation.observed_at_ms
                <= statement.excluded.observed_at_ms,
            ).returning(HorseTrainingRiderObservation.horse_training_id)
        )
        written = len(result.scalars().all())
    run.status = "completed"
    run.completed_at_ms = observed
    run.records_fetched, run.records_written = len(rows), written
    if rejected_rows:
        run.error_message = f"Duration-inconsistent source rows skipped: {rejected_rows}"
    session.commit()
    return {
        "horse": official_id,
        "fetched": len(rows),
        "matched": written,
        "ambiguous": ambiguous,
        "rejected": len(rejected_rows),
    }
