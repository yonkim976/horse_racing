"""Refresh one Wednesday-to-Tuesday card window in Supabase, never predictions.

Run at 17:10 KST Wednesday, with 18:10/19:10 publication rechecks. Once a
window succeeds, subsequent attempts skip writes only if its inputs are unchanged.
Raw files must live on a durable volume in Cloud Run. No schema is created here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import (
    RACE_PLAN_ENDPOINT,
    RACE_PLAN_OPERATION,
    FetchedPage,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import IngestionRun, SourceDocument
from horse_racing.parsers.entry_sheet import EntrySheetItem, parse_entry_sheet_page
from horse_racing.parsers.gate_entry_sheet import (
    GateEntrySheetItem,
    parse_equipment_changes,
    parse_gate_entry_sheet_page,
)
from horse_racing.parsers.race_day import RacePlanItem, parse_items
from horse_racing.services.discord_notifications import notify_weekly
from horse_racing.services.gate_entry_sheet import _name_key, ingest_gate_numbers
from horse_racing.services.race_day import ingest_race_schedule
from horse_racing.services.raw_store import store_kra_page

KST = ZoneInfo("Asia/Seoul")
LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"horse-racing-weekly-card-v1").digest()[:8],
    "big",
    signed=True,
)


def emit(event: str, **values: object) -> None:
    print(json.dumps({"event": event, **values}, ensure_ascii=False, default=str), flush=True)


def card_window(as_of: date) -> tuple[date, list[date]]:
    """Include holiday Monday/Tuesday following the usual weekend."""
    anchor = as_of - timedelta(days=(as_of.weekday() - 2) % 7)
    end = anchor + timedelta(days=6)
    return anchor, [as_of + timedelta(days=i) for i in range((end - as_of).days + 1)]


def require_target(database_url: str, project_ref: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Only the explicitly selected Supabase PostgreSQL is allowed")
    if project_ref not in (url.username or "") and project_ref not in (url.host or ""):
        raise ValueError("Unexpected database project")
    if url.port not in (None, 5432):
        raise ValueError("Session advisory locks require a direct/session connection")


def fingerprint(cards: list[Card]) -> str:
    payload = []
    for card in sorted(cards, key=lambda c: (c.day, c.meet)):
        payload.append(
            {
                "day": str(card.day),
                "meet": card.meet,
                "plans": [
                    x.model_dump(mode="json")
                    for x in sorted(card.plans, key=lambda x: x.race_number)
                ],
                "entries": [
                    x.model_dump(mode="json")
                    for x in sorted(card.entries, key=lambda x: (x.race_number, x.horse_number))
                ],
                "gates": [
                    x.model_dump(mode="json")
                    for x in sorted(card.gates, key=lambda x: (x.race_number, x.gate_number))
                ],
            }
        )
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


@dataclass
class Card:
    day: date
    meet: int
    plans: list[RacePlanItem]
    entries: list[EntrySheetItem]
    gates: list[GateEntrySheetItem]


class Replay:
    """Persist exactly the already validated response, without refetching."""

    def __init__(self) -> None:
        self.pages: dict[tuple[str, int, str], list[FetchedPage]] = {}

    def iter_pages(self, *, endpoint, public_params, **_kwargs):
        return iter(
            self.pages[(str(public_params["race_dt"]), int(public_params["rccrs_cd"]), endpoint)]
        )

    def iter_entry_sheet_pages(self, *, race_date, meet, **_kwargs):
        return iter(self.pages[(race_date, meet, "/API26_2/entrySheet_2")])

    def iter_gate_entry_sheet_pages(self, *, race_date, meet, **_kwargs):
        return iter(self.pages[(race_date, meet, "/API78/chulmainfo")])


def require_complete_pages(pages: list[FetchedPage], actual: int) -> None:
    if not pages or len({int(p.public_params["pageNo"]) for p in pages}) != len(pages):
        raise ValueError("Missing or duplicate response pages")
    totals = {int(response_body(p.payload).get("totalCount") or 0) for p in pages}
    if totals != {actual}:
        raise ValueError("Incomplete source pagination")


def validate_card(card: Card) -> None:
    if not card.plans or not card.entries or not card.gates:
        raise ValueError("Card not yet published")
    for items in (card.plans, card.entries, card.gates):
        if any(x.race_date != card.day for x in items):
            raise ValueError("Unexpected source date")
    plans = {x.race_number: x for x in card.plans}
    entries = {(x.race_number, x.horse_number): x for x in card.entries}
    gates = {(x.race_number, x.gate_number): x for x in card.gates}
    horse_keys = {(x.race_number, x.horse_id) for x in card.entries}
    if (
        len(plans) != len(card.plans)
        or len(entries) != len(card.entries)
        or len(horse_keys) != len(card.entries)
        or len(gates) != len(card.gates)
    ):
        raise ValueError("Duplicate source keys")
    if set(entries) != set(gates) or set(plans) != {x.race_number for x in card.entries}:
        raise ValueError("Plan/card/gate coverage mismatch")
    if any(
        _name_key(x.horse_name) != _name_key(gates[key].horse_name) for key, x in entries.items()
    ):
        raise ValueError("Horse name mismatch between cards")
    counts = Counter(x.race_number for x in card.entries)
    for number, plan in plans.items():
        if plan.field_size is not None and plan.field_size != counts[number]:
            raise ValueError("Published field size does not match card")
        if any(x.distance_m != plan.distance_m for x in card.entries if x.race_number == number):
            raise ValueError("Race distance mismatch")


def fetch_window(client: KraApiClient, days: list[date], meets: list[int]):
    replay, cards = Replay(), []
    for day in days:
        label = day.strftime("%Y%m%d")
        for meet in meets:
            pages = list(
                client.iter_pages(
                    endpoint=RACE_PLAN_ENDPOINT,
                    operation=RACE_PLAN_OPERATION,
                    public_params={"rccrs_cd": meet, "race_dt": label, "_type": "json"},
                    page_size=1000,
                )
            )
            plans = [x for p in pages for x in parse_items(p.payload, RacePlanItem)]
            require_complete_pages(pages, len(plans))
            replay.pages[(label, meet, RACE_PLAN_ENDPOINT)] = pages
            if not plans:
                emit("no_published_plan", day=label, meet=meet)
                continue
            ep = list(client.iter_entry_sheet_pages(race_date=label, meet=meet, page_size=1000))
            gp = list(
                client.iter_gate_entry_sheet_pages(
                    race_date=label,
                    meet=meet,
                    page_size=1000,
                )
            )
            entries = [x for p in ep for x in parse_entry_sheet_page(p.payload).items]
            gates = [x for p in gp for x in parse_gate_entry_sheet_page(p.payload).items]
            require_complete_pages(ep, len(entries))
            require_complete_pages(gp, len(gates))
            card = Card(day, meet, plans, entries, gates)
            validate_card(card)
            replay.pages[(label, meet, "/API26_2/entrySheet_2")] = ep
            replay.pages[(label, meet, "/API78/chulmainfo")] = gp
            cards.append(card)
            emit("source_validated", day=label, meet=meet, races=len(plans), runners=len(entries))
    if not cards:
        raise ValueError("No published race cards in the requested window")
    return replay, cards


SNAPSHOT = text("""SELECT r.race_number,r.status,r.scheduled_at_ms,e.id,e.scratched,
    h.kra_horse_id,e.horse_number,e.gate_number,e.carried_weight_kg,e.rating,
    e.equipment_card_raw,j.kra_jockey_id,t.kra_trainer_id,o.kra_owner_id
    FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id
    JOIN race_entries e ON e.race_id=r.id JOIN horses h ON h.id=e.horse_id
    LEFT JOIN jockeys j ON j.id=e.jockey_id LEFT JOIN trainers t ON t.id=e.trainer_id
    LEFT JOIN owners o ON o.id=e.owner_id
    WHERE r.race_date_local=:day AND rc.kra_meet_code=:meet""")


def snapshot(session: Session, card: Card):
    return {
        (r["race_number"], r["kra_horse_id"]): dict(r)
        for r in session.execute(SNAPSHOT, {"day": card.day, "meet": card.meet}).mappings()
    }


def validate_existing(card: Card, before: dict, now_ms: int) -> None:
    expected = {(x.race_number, x.horse_id) for x in card.entries}
    if before.keys() - expected:
        raise ValueError("Stored runners absent from refreshed card: manual review required")
    if any(
        r["status"] == "completed"
        or (r["scheduled_at_ms"] is not None and r["scheduled_at_ms"] <= now_ms)
        for r in before.values()
    ):
        raise ValueError("Cannot refresh completed/started races as an initial card")
    if card.day <= datetime.fromtimestamp(now_ms / 1000, KST).date():
        raise ValueError("Initial weekly worker only writes future race days")


def verify_saved(card: Card, before: dict, after: dict) -> None:
    expected = {(x.race_number, x.horse_id) for x in card.entries}
    if after.keys() != expected:
        raise ValueError("Saved runner coverage mismatch")
    gates = {(x.race_number, x.gate_number): x for x in card.gates}
    for item in card.entries:
        key = (item.race_number, item.horse_id)
        row = after[key]
        fields = {
            "horse_number": item.horse_number,
            "gate_number": item.horse_number,
            "carried_weight_kg": item.carried_weight_kg,
            "rating": item.rating,
            "kra_jockey_id": item.jockey_id,
            "kra_trainer_id": item.trainer_id,
            "kra_owner_id": item.owner_id,
        }
        if any(row[k] != v for k, v in fields.items()):
            raise ValueError("Saved runner values differ from source")
        raw = gates[(item.race_number, item.horse_number)].equipment_card_raw
        if raw is not None and raw != row["equipment_card_raw"]:
            raise ValueError("Saved equipment differs from source")
        if key in before and before[key]["scratched"] and not row["scratched"]:
            raise ValueError("Cancellation regressed")


def archive_scans(session: Session, replay: Replay, run_id: int, raw_dir: Path) -> None:
    for (day, meet, endpoint), pages in replay.pages.items():
        if endpoint != RACE_PLAN_ENDPOINT:
            continue
        for page in pages:
            stored = store_kra_page(
                page,
                raw_data_dir=raw_dir,
                data_type="weekly_plan_scan",
                race_date=day,
                meet=meet,
                run_id=run_id,
                page_no=int(page.public_params["pageNo"]),
            )
            session.add(
                SourceDocument(
                    ingestion_run_id=run_id,
                    source_url=page.source_url,
                    endpoint=page.endpoint,
                    operation=page.operation,
                    request_params_json=json.dumps(dict(page.public_params)),
                    requested_at_ms=page.requested_at_ms,
                    retrieved_at_ms=page.retrieved_at_ms,
                    http_status_code=page.status_code,
                    content_type=page.content_type,
                    response_bytes=len(page.body),
                    local_path=str(stored.path),
                    sha256=stored.sha256,
                )
            )
    session.commit()


def execute(project_ref: str, *, as_of: date, force: bool, dry_run: bool) -> int:
    settings = get_settings()
    require_target(settings.database_url, project_ref)
    anchor, days = card_window(as_of)
    emit("window", anchor=anchor, days=days, meets=[1, 2, 3, 4], dry_run=dry_run)
    if dry_run:
        return 0  # No network, DB connection, filesystem write, or secret access.
    if as_of != datetime.now(KST).date():
        raise ValueError("Writes must use the current KST date")
    if settings.data_go_kr_service_key is None:
        raise ValueError("API key unavailable")
    raw_dir = settings.raw_data_dir.resolve()
    if os.getenv("K_SERVICE") or os.getenv("CLOUD_RUN_JOB"):
        if raw_dir != Path("/raw") or not os.getenv("HORSE_RACING_RAW_BUCKET"):
            raise ValueError("Cloud execution requires the durable /raw volume")
    source = f"worker/weekly_entry_cards/{anchor:%Y%m%d}"
    engine = create_engine_for_url(settings.database_url)
    run_id = None
    acquired = False
    notification = None
    try:
        with engine.connect() as lock:
            acquired = bool(
                lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY})
            )
            lock.commit()
            if not acquired:
                emit("skipped_concurrent_execution")
                return 0
            try:
                with KraApiClient(
                    settings.data_go_kr_service_key.get_secret_value(),
                    base_url=settings.kra_api_base_url,
                    timeout_seconds=settings.http_timeout_seconds,
                ) as client:
                    replay, cards = fetch_window(client, days, [1, 2, 3, 4])
                # Re-scan even after success: another venue may publish late.
                source += "/" + fingerprint(cards)
                with Session(engine, expire_on_commit=False) as session:
                    known_pairs = set(
                        session.execute(
                            text("""SELECT DISTINCT
                        r.race_date_local,rc.kra_meet_code FROM races r
                        JOIN racecourses rc ON rc.id=r.racecourse_id
                        WHERE r.race_date_local BETWEEN :start AND :end
                        AND rc.kra_meet_code IN (1,2,3,4)"""),
                            {"start": days[0], "end": days[-1]},
                        )
                    )
                    if known_pairs - {(c.day, c.meet) for c in cards}:
                        raise ValueError("Known scheduled race days absent from plan scan")
                    for card in cards:
                        validate_existing(card, snapshot(session, card), int(time.time() * 1000))
                    done = session.scalar(
                        select(IngestionRun.id)
                        .where(
                            IngestionRun.source == source,
                            IngestionRun.status == "completed",
                        )
                        .limit(1)
                    )
                    if done and not force:
                        for card in cards:
                            current = snapshot(session, card)
                            verify_saved(card, current, current)
                        emit("skipped_unchanged_window", previous_run=done)
                        notification = {
                            "status": "unchanged" if cards else "no_published_plan",
                            "window_start": str(days[0]),
                            "window_end": str(days[-1]),
                            "run_id": done,
                            "races": sum(len(c.plans) for c in cards),
                            "runners": sum(len(c.entries) for c in cards),
                            "api_pages": sum(map(len, replay.pages.values())),
                        }
                        return 0
                    # No normalized writes until every published card is validated.
                    run = IngestionRun(
                        source=source,
                        data_type="weekly_entry_cards",
                        started_at_ms=int(time.time() * 1000),
                        status="running",
                        records_fetched=sum(len(c.entries) for c in cards),
                    )
                    session.add(run)
                    session.commit()
                    run_id = run.id
                    archive_scans(session, replay, run_id, raw_dir)
                    for card in cards:
                        before = snapshot(session, card)
                        validate_existing(card, before, int(time.time() * 1000))
                        session.rollback()
                        day = card.day.strftime("%Y%m%d")
                        summary = ingest_race_schedule(
                            session,
                            replay,
                            race_date=day,
                            meet=card.meet,
                            raw_data_dir=raw_dir,
                            page_size=1000,
                        )
                        gate = ingest_gate_numbers(
                            session,
                            replay,
                            race_date=day,
                            meet=card.meet,
                            raw_data_dir=raw_dir,
                            page_size=1000,
                        )
                        verify_saved(card, before, snapshot(session, card))
                        marks = list(
                            session.execute(
                                text("""SELECT m.race_entry_id,m.position,
                            m.equipment_name_raw,m.change_type FROM entry_equipment_changes m
                            JOIN race_entries e ON e.id=m.race_entry_id
                            JOIN races r ON r.id=e.race_id
                            JOIN racecourses rc ON rc.id=r.racecourse_id
                            WHERE r.race_date_local=:day AND rc.kra_meet_code=:meet"""),
                                {"day": card.day, "meet": card.meet},
                            )
                        )
                        saved = snapshot(session, card)
                        for item in card.entries:
                            row = saved[(item.race_number, item.horse_id)]
                            actual = sorted(
                                (p, n, t) for entry_id, p, n, t in marks if entry_id == row["id"]
                            )
                            if actual != parse_equipment_changes(row["equipment_card_raw"] or ""):
                                raise ValueError("Equipment mark verification failed")
                        emit(
                            "pair_saved",
                            day=day,
                            meet=card.meet,
                            gate_run=gate.run_id,
                            stage_runs={k: v.run_id for k, v in summary.stages.items()},
                            runners=len(card.entries),
                        )
                    run = session.get(IngestionRun, run_id)
                    run.status = "completed"
                    run.records_written = run.records_fetched
                    run.completed_at_ms = int(time.time() * 1000)
                    session.commit()
                    emit(
                        "completed",
                        run_id=run_id,
                        races=sum(len(c.plans) for c in cards),
                        runners=run.records_written,
                        api_pages=sum(map(len, replay.pages.values())),
                    )
                    notification = {
                        "status": "completed" if cards else "no_published_plan",
                        "window_start": str(days[0]),
                        "window_end": str(days[-1]),
                        "run_id": run_id,
                        "races": sum(len(c.plans) for c in cards),
                        "runners": run.records_written,
                        "api_pages": sum(map(len, replay.pages.values())),
                    }
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                lock.commit()
    except Exception as exc:
        if run_id is not None:
            with Session(engine) as session:
                run = session.get(IngestionRun, run_id)
                run.status = "failed"
                run.error_message = type(exc).__name__  # Never log credential-bearing exceptions.
                run.completed_at_ms = int(time.time() * 1000)
                session.commit()
        emit("failed", error_type=type(exc).__name__, run_id=run_id)
        notification = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "window_start": str(days[0]),
            "window_end": str(days[-1]),
        }
        return 1
    finally:
        engine.dispose()
        if notification is not None:
            notify_weekly(settings.discord_webhook_url, emit=emit, summary=notification)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-write", action="store_true")
    parser.add_argument("--force", action="store_true", help="Recheck even a completed window")
    args = parser.parse_args()
    if not args.dry_run and not args.confirm_write:
        parser.error("Writes require --confirm-write")
    try:
        return execute(
            args.project_ref,
            as_of=args.as_of or datetime.now(KST).date(),
            force=args.force,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        emit("failed", error_type=type(exc).__name__)
        if not args.dry_run:
            try:
                notify_weekly(
                    get_settings().discord_webhook_url,
                    emit=emit,
                    summary={"status": "failed", "error_type": type(exc).__name__},
                )
            except Exception as notify_exc:
                emit("discord_failed", error_type=type(notify_exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
