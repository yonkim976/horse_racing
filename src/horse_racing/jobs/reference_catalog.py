"""Local-only adapters for validated trainer catalog and running-trial refreshes."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import response_body
from horse_racing.collectors.kra_text import KraTextClient
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    IngestionRun,
    Jockey,
    RunningTrial,
    RunningTrialResult,
    SourceDocument,
    Trainer,
    TrainerAffiliationSnapshot,
    TrainerHistoricalRegion,
    TrainerStatusObservation,
)
from horse_racing.jobs.canonical_post_race import document, require, write_json
from horse_racing.jobs.local_race_day import LocalKraApiClient
from horse_racing.jobs.weekly_entry_cards import require_complete_pages
from horse_racing.parsers.horse_history import parse_meet_code
from horse_racing.parsers.running_trials import parse_running_trial_report
from horse_racing.services.running_trials import ingest_running_trials
from scripts.sync_trainer_affiliations import (
    fetch_listings,
    parse_api_response,
)
from scripts.sync_trainer_historical_regions import fetch_sources

REGIONS = {1: "SEOUL", 2: "JEJU", 3: "YEONGNAM"}


def archive_bytes(path, body, url, endpoint):
    now = int(time.time() * 1000)
    return document(
        SimpleNamespace(
            body=body,
            source_url=url,
            endpoint=endpoint,
            operation=endpoint.rsplit("/", 1)[-1],
            public_params={},
            requested_at_ms=now,
            retrieved_at_ms=now,
            status_code=200,
            content_type=None,
        ),
        path,
    )


def record_sources(session, docs, *, kind, count):
    now = int(time.time() * 1000)
    run = IngestionRun(
        source="KRA official API and website",
        data_type=kind,
        started_at_ms=now,
        completed_at_ms=now,
        status="completed",
        records_fetched=count,
        records_written=count,
    )
    session.add(run)
    session.flush()
    for doc in docs:
        session.add(SourceDocument(ingestion_run_id=run.id, **doc))
    return run.id


def assign(row, values):
    for key, value in values.items():
        setattr(row, key, value)


def refresh_trainers(settings, *, now, directory):
    # These retained script readers do not open SQLite or write files on import.
    former, raw_api, raw_retired = fetch_sources(now.date())
    active = [r for meet, raw in raw_api.items() for r in parse_api_response(raw, meet)]
    web, raw_active = fetch_listings()

    def signature(row):
        return row.kra_trainer_id, row.name_ko, row.meet_code, row.stable_part

    require(
        {signature(r) for r in active} == {signature(r) for r in web}, "trainer_api_web_disagree"
    )
    require(
        len({r.kra_trainer_id for r in active}) == len(active), "active_trainer_regions_conflict"
    )
    require(
        not ({r.kra_trainer_id for r in active} & {r.kra_trainer_id for r in former}),
        "active_ended_trainer_conflict",
    )
    docs = []
    for meet in (1, 2, 3):
        docs.append(
            archive_bytes(
                directory / f"active_{meet}.html",
                raw_active[meet],
                f"https://race.kra.co.kr/trainer/profileTrainerList.do?meet={meet}",
                "/trainer/profileTrainerList.do",
            )
        )
        docs.append(
            archive_bytes(
                directory / f"api_{meet}.json",
                raw_api[meet],
                f"https://apis.data.go.kr/B551015/API308/trainerInfo?meet={meet}",
                "/API308/trainerInfo",
            )
        )
        docs.append(
            archive_bytes(
                directory / f"retired_{meet}.html",
                raw_retired[meet],
                f"https://race.kra.co.kr/trainer/profileTrainerListRetire.do?meet={meet}",
                "/trainer/profileTrainerListRetire.do",
            )
        )
    engine = create_engine_for_url(settings.database_url)
    try:
        with Session(engine) as session:
            session.execute(select(Trainer).limit(0))
            if engine.dialect.name == "postgresql":
                from sqlalchemy import text

                session.execute(text("SELECT pg_advisory_xact_lock(26071007)"))
            trainers = {t.kra_trainer_id: t for t in session.scalars(select(Trainer))}
            chosen_former = [r for r in former if r.kra_trainer_id in trainers]
            before = [
                {"id": t.id, "official_id": t.kra_trainer_id, "name": t.name_ko}
                for t in trainers.values()
            ]
            write_json(directory / "before_trainers.json", before)
            changed_names = 0
            for item in active:
                tr = trainers.get(item.kra_trainer_id)
                if tr is None:
                    tr = Trainer(kra_trainer_id=item.kra_trainer_id, name_ko=item.name_ko)
                    session.add(tr)
                    session.flush()
                    trainers[item.kra_trainer_id] = tr
                changed_names += int(tr.name_ko != item.name_ko)
                tr.name_ko = item.name_ko
                row = session.get(TrainerAffiliationSnapshot, (tr.id, now.date()))
                if row is None:
                    row = TrainerAffiliationSnapshot(trainer_id=tr.id, observed_on=now.date())
                    session.add(row)
                assign(
                    row,
                    dict(
                        meet_code=item.meet_code,
                        stable_part=item.stable_part,
                        official_name_ko=item.name_ko,
                        stats_as_of=item.stats_as_of,
                        observed_at_ms=int(now.timestamp() * 1000),
                        source_url=item.source_url,
                        source_sha256=item.source_sha256,
                    ),
                )
            statuses = []
            for item in active:
                statuses.append(
                    dict(
                        official_tr_no=item.kra_trainer_id,
                        canonical_name_ko=item.name_ko,
                        region_code=REGIONS[item.meet_code],
                        status_code="active",
                        status_label_ko="현역",
                        source_end_date=None,
                        classification_basis="API308 open registration and KRA active list agree",
                        source_url=item.source_url,
                        source_api_sha256=item.source_sha256,
                        retired_list_sha256=None,
                    )
                )
            for item in chosen_former:
                tr = trainers[item.kra_trainer_id]
                require(tr.name_ko == item.name_ko, "former_trainer_name_conflict")
                meet = next(m for m, r in REGIONS.items() if r == item.region_code)
                row = session.get(TrainerHistoricalRegion, (tr.id, item.region_code, now.date()))
                if row is None:
                    row = TrainerHistoricalRegion(
                        trainer_id=tr.id, region_code=item.region_code, observed_on=now.date()
                    )
                    session.add(row)
                assign(
                    row,
                    dict(
                        source_end_date=item.source_end_date,
                        retired_list_confirmed=item.retired_list_confirmed,
                        observed_at_ms=int(now.timestamp() * 1000),
                        source_url=item.source_url,
                        source_sha256=item.source_sha256,
                    ),
                )
                statuses.append(
                    dict(
                        official_tr_no=item.kra_trainer_id,
                        canonical_name_ko=item.name_ko,
                        region_code=item.region_code,
                        status_code="retired_confirmed"
                        if item.retired_list_confirmed
                        else "domestic_registration_ended",
                        status_label_ko="은퇴 확정"
                        if item.retired_list_confirmed
                        else "국내 등록 종료(은퇴 미확인)",
                        source_end_date=item.source_end_date,
                        classification_basis="API308 end date; KRA retired-list membership checked",
                        source_url=item.source_url,
                        source_api_sha256=item.source_sha256,
                        retired_list_sha256=hashlib.sha256(raw_retired[meet]).hexdigest(),
                    )
                )
            for values in statuses:
                row = session.get(TrainerStatusObservation, (values["official_tr_no"], now.date()))
                if row is None:
                    row = TrainerStatusObservation(
                        official_tr_no=values["official_tr_no"], observed_on=now.date()
                    )
                    session.add(row)
                assign(row, values)
            run_id = record_sources(
                session, docs, kind="trainer_catalog_refresh", count=len(statuses)
            )
            session.commit()
            summary = dict(
                status="completed",
                active=len(active),
                ended=len(chosen_former),
                changed_names=changed_names,
                run_id=run_id,
            )
            write_json(directory / "report.json", summary)
            return summary
    finally:
        engine.dispose()


def trial_key(meet, day, race, horse):
    return meet, day, int(race), int(horse)


def validate_trial_api(meet, trials, api_rows, *, allow_text_jockey_fallback=False):
    parsed = {
        trial_key(meet, t.trial_date, t.trial_race_number, r.horse_number): r
        for t in trials
        for r in t.results
    }
    require(len(parsed) == sum(len(t.results) for t in trials), "trial_text_duplicate_key")
    official = {}
    for raw in api_rows:
        day = date.fromisoformat(
            str(raw["trainDate"])[:4]
            + "-"
            + str(raw["trainDate"])[4:6]
            + "-"
            + str(raw["trainDate"])[6:]
        )
        key = trial_key(meet, day, raw["trainNo"], raw["chulNo"])
        require(parse_meet_code(raw["meet"]) == meet, "trial_wrong_meet")
        require(key in parsed and key not in official, "trial_api_key")
        item = parsed[key]
        require(item.horse_name == str(raw["hrName"]).strip(), "trial_horse_name")
        api_jockey_name = str(raw.get("jkName") or "").strip()
        missing_jockey_id = raw.get("jkNo") in (None, "")
        fallback = allow_text_jockey_fallback and (not api_jockey_name or missing_jockey_id)
        if fallback:
            require(bool(item.jockey_name), "trial_text_jockey_missing")
            require(
                not api_jockey_name or item.jockey_name == api_jockey_name,
                "trial_jockey_name",
            )
        else:
            require(item.jockey_name == api_jockey_name, "trial_jockey_name")
        require(item.trainer_name == str(raw["trName"]).strip(), "trial_trainer_name")
        from horse_racing.jobs.canonical_post_race import millis

        require(item.finish_time_ms == millis(raw.get("rcTime")), "trial_finish_time")
        if item.finish_position is not None:
            require(item.finish_position == int(raw["ord"]), "trial_finish_rank")
        for field, text_name in (("hrNo", "horse"), ("jkNo", "jockey"), ("trNo", "trainer")):
            if field == "jkNo" and fallback and missing_jockey_id:
                continue  # No name-only identity resolution, including namesakes.
            width = 7 if text_name == "horse" else 6
            value = str(raw.get(field) or "").zfill(width)
            require(
                value != "0" * width and bool(re.fullmatch(r"[0-9A-Z]{" + str(width) + "}", value)),
                "trial_official_id",
            )
        # A normalized copy only: the archived API response remains untouched.
        official[key] = dict(raw)
        if fallback:
            official[key].update(
                jkName=item.jockey_name,
                jkNo=None if missing_jockey_id else raw["jkNo"],
                jockey_name_source="official_dacom23",
                jockey_id_status="not_provided" if missing_jockey_id else "api_provided",
            )
    require(set(parsed) == set(official), "trial_api_text_coverage")
    return official


class CachedTrialClient:
    def __init__(self, files, reports):
        self.files, self.reports = files, reports

    def iter_running_trial_files(self, *, meet, **_):
        return iter([f for f in self.files if f.meet == meet])

    def fetch_file(self, file):
        return self.reports[(file.meet, file.remote_path)]


def refresh_trials(settings, *, start, end, directory):
    results, pending, errors = [], [], []
    with (
        KraTextClient() as text_client,
        LocalKraApiClient(settings.data_go_kr_service_key.get_secret_value()) as api,
    ):
        for meet in (1, 2, 3):
            try:
                files = list(
                    text_client.iter_running_trial_files(meet=meet, start_date=start, end_date=end)
                )
            except Exception as exc:
                errors.append(dict(meet=meet, stage="listing", error_type=type(exc).__name__))
                continue
            for file in files:
                context = dict(meet=meet, date=str(file.file_date))
                try:
                    folder = directory / f"meet_{meet}_{file.file_date}"
                    folder.mkdir()
                    result = refresh_trial_file(settings, text_client, api, file, folder)
                    if result["status"] == "waiting_for_publication":
                        pending.append({**context, **result})
                    else:
                        results.append({**context, **result})
                except Exception as exc:
                    # Do not forward URLs, SQL or arbitrary exception messages.
                    errors.append({**context, "error_type": type(exc).__name__})
    if errors:
        status = "partial" if results else "failed"
    elif pending:
        status = "partial" if results else "waiting_for_publication"
    elif results:
        status = "partial" if any(r.get("unlinked_rows", 0) for r in results) else "completed"
    else:
        status = "not_published"
    result = dict(
        status=status,
        files=sum(r.get("files", 0) for r in results),
        trials=sum(r.get("trials", 0) for r in results),
        runners=sum(r.get("runners", 0) for r in results),
        unlinked_rows=sum(r.get("unlinked_rows", 0) for r in results),
        text_jockey_fallback_rows=sum(r.get("text_jockey_fallback_rows", 0) for r in results),
        api_jockey_ids_missing=sum(r.get("api_jockey_ids_missing", 0) for r in results),
        results=results,
        pending=pending,
        errors=errors,
    )
    write_json(directory / "report.json", result)
    return result


def refresh_trial_file(settings, text_client, api, file, directory):
    """Validate and commit one meet/date; other files can progress independently."""
    meet = file.meet
    fetched = text_client.fetch_file(file)
    docs = [archive_bytes(directory / "dacom23.rpt", fetched.body, fetched.source_url, "dacom23")]
    trials = parse_running_trial_report(fetched.body, meet=meet)
    require(all(t.trial_date == file.file_date for t in trials), "trial_text_date")
    text_runners = sum(len(t.results) for t in trials)
    require(text_runners > 0, "trial_text_empty")
    pages = list(
        api.iter_pages(
            endpoint="/API20_1/ridingTestResult_1",
            operation="ridingTestResult_1",
            public_params={
                "meet": meet,
                "tr_date": file.file_date.strftime("%Y%m%d"),
                "_type": "json",
            },
            page_size=1000,
        )
    )
    raw_rows = []
    for n, page in enumerate(pages):
        docs.append(document(page, directory / f"api20_{n}.json"))
        items = (response_body(page.payload).get("items") or {}).get("item") or []
        raw_rows.extend([items] if isinstance(items, dict) else items)
    write_json(directory / "sources.json", docs)
    require_complete_pages(pages, len(raw_rows))
    if not raw_rows:
        # A normal zero-count API response is publication pending, not proof of
        # absent horses. Preserve evidence and leave existing operational rows alone.
        return dict(
            status="waiting_for_publication",
            reason="api_empty_text_present",
            text_trials=len(trials),
            text_runners=text_runners,
            api_runners=0,
        )
    official = validate_trial_api(meet, trials, raw_rows, allow_text_jockey_fallback=True)
    fallback_rows = [
        dict(
            meet=key[0],
            date=str(key[1]),
            trial=key[2],
            horse_number=key[3],
            horse_name=raw["hrName"],
            jockey_name=raw["jkName"],
            jockey_name_source=raw["jockey_name_source"],
            jockey_id_status=raw["jockey_id_status"],
        )
        for key, raw in official.items()
        if raw.get("jockey_name_source") == "official_dacom23"
    ]
    write_json(directory / "text_jockey_fallbacks.json", fallback_rows)
    return persist_trials(
        settings,
        files=[file],
        reports={(meet, file.remote_path): fetched},
        official=official,
        docs=docs,
        start=file.file_date,
        end=file.file_date,
        directory=directory,
    )


def persist_trials(settings, *, files, reports, official, docs, start, end, directory):
    meets = sorted({file.meet for file in files})
    engine = create_engine_for_url(settings.database_url)
    try:
        with Session(engine) as session:
            people = {}
            for model, col, label in (
                (Horse, "kra_horse_id", "horse"),
                (Jockey, "kra_jockey_id", "jockey"),
                (Trainer, "kra_trainer_id", "trainer"),
            ):
                people[label] = {getattr(r, col): r for r in session.scalars(select(model))}
            identity = {}
            for key, raw in official.items():
                ids = []
                for model, col, label, id_field, name_field, width in (
                    (Horse, "kra_horse_id", "horse", "hrNo", "hrName", 7),
                    (Jockey, "kra_jockey_id", "jockey", "jkNo", "jkName", 6),
                    (Trainer, "kra_trainer_id", "trainer", "trNo", "trName", 6),
                ):
                    if label == "jockey" and raw[id_field] is None:
                        ids.append(None)
                        continue
                    ref = str(raw[id_field]).zfill(width)
                    row = people[label].get(ref)
                    if row is None:
                        row = model(**{col: ref, "name_ko": str(raw[name_field]).strip()})
                        session.add(row)
                        session.flush()
                        people[label][ref] = row
                    # A historical label need not equal today's canonical display name.
                    ids.append(row.id)
                identity[key] = tuple(ids)
            before = (
                session.execute(
                    select(RunningTrialResult.__table__)
                    .join(RunningTrial, RunningTrial.id == RunningTrialResult.running_trial_id)
                    .where(
                        RunningTrial.trial_date_local.between(start, end),
                        RunningTrial.meet_code.in_(meets),
                    )
                )
                .mappings()
                .all()
            )
            write_json(
                directory / "before_trials.json",
                json.loads(json.dumps([dict(r) for r in before], default=str)),
            )
            # A later incomplete API must not erase a previously verified link.
            trial_numbers = {
                t.id: (t.meet_code, t.trial_date_local, t.trial_race_number)
                for t in session.scalars(
                    select(RunningTrial).where(
                        RunningTrial.trial_date_local.between(start, end),
                        RunningTrial.meet_code.in_(meets),
                    )
                )
            }
            for previous in before:
                key = (*trial_numbers[previous["running_trial_id"]], previous["horse_number"])
                if (
                    key in identity and identity[key][1] is None
                    and previous["jockey_id"] is not None
                ):
                    require(
                        previous["jockey_name_raw"] == official[key]["jkName"],
                        "trial_existing_jockey_conflict",
                    )
                    horse_id, _, trainer_id = identity[key]
                    identity[key] = (horse_id, previous["jockey_id"], trainer_id)
            session.commit()
            summary = ingest_running_trials(
                session,
                CachedTrialClient(files, reports),
                start_date=start,
                end_date=end,
                meets=meets,
                raw_data_dir=directory / "raw",
                official_identity=identity,
            )
            record_sources(
                session, docs, kind="running_trial_identity_refresh", count=len(identity)
            )
            session.commit()
            missing = session.execute(
                select(RunningTrialResult.id)
                .join(RunningTrial)
                .where(
                    RunningTrial.trial_date_local.between(start, end),
                    RunningTrial.meet_code.in_(meets),
                    (
                        RunningTrialResult.horse_id.is_(None)
                        | RunningTrialResult.jockey_id.is_(None)
                        | RunningTrialResult.trainer_id.is_(None)
                    ),
                )
            ).all()
            result = dict(
                status="partial" if missing else "completed",
                files=len(files),
                trials=summary.trials,
                runners=summary.records_written,
                unlinked_rows=len(missing),
                text_jockey_fallback_rows=sum(
                    r.get("jockey_name_source") == "official_dacom23" for r in official.values()
                ),
                api_jockey_ids_missing=sum(r.get("jkNo") is None for r in official.values()),
                run_id=summary.run_id,
            )
            write_json(directory / "saved.json", result)
            return result
    finally:
        engine.dispose()
