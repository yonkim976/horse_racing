"""Backfill official API78 equipment-card +/- history into local and Supabase DBs.

One API request is shared by both databases. Completed source documents are a
resume checkpoint, and their hash-verified local raw files can be replayed when
only one database finished. Historical responses are observed *now*, not at the
original race's pre-race publication time.

Run without --apply to inspect the target count. This script does not modify
API24 equipment history and never guesses +/- from consecutive equipment lists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import time

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, joinedload

from horse_racing.collectors.kra_api import (
    FetchedPage,
    KraApiClient,
    KraApiRateLimitError,
)
from horse_racing.config import get_settings
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import IngestionRun, Race, Racecourse, RaceEntry, SourceDocument
from horse_racing.parsers.gate_entry_sheet import GateEntrySheetItem, parse_gate_entry_sheet_page
from horse_racing.services.gate_entry_sheet import _name_key, _write_gate_numbers
from horse_racing.services.raw_store import store_kra_page


ROOT = Path(__file__).resolve().parents[1]
LOCAL_URL = f"sqlite:///{ROOT / 'data/horse_racing.sqlite3'}"
PROJECT_REF = "xkykmhhkjtosptoibduo"
ENDPOINT = "/API78/chulmainfo"


@dataclass(frozen=True)
class SavedDocument:
    document: SourceDocument
    run_status: str
    run_data_type: str


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def _targets(engine: Engine, start: date, end: date) -> list[tuple[str, int]]:
    with Session(engine) as session:
        rows = session.execute(
            select(Race.race_date_local, Racecourse.kra_meet_code)
            .join(Racecourse, Race.racecourse_id == Racecourse.id)
            .join(RaceEntry, RaceEntry.race_id == Race.id)
            .where(
                Race.race_date_local.between(start, end),
                Racecourse.kra_meet_code.in_((1, 2, 3)),
            )
            .distinct()
            .order_by(Race.race_date_local, Racecourse.kra_meet_code)
        ).all()
    return [(day.strftime("%Y%m%d"), meet) for day, meet in rows]


def _saved_documents(
    engine: Engine,
) -> dict[tuple[str, int], list[SavedDocument]]:
    result: dict[tuple[str, int], list[SavedDocument]] = defaultdict(list)
    with Session(engine) as session:
        rows = session.execute(
            select(SourceDocument, IngestionRun.status, IngestionRun.data_type)
            .join(IngestionRun, IngestionRun.id == SourceDocument.ingestion_run_id)
            .where(SourceDocument.endpoint == ENDPOINT)
            .order_by(SourceDocument.retrieved_at_ms.desc(), SourceDocument.id.desc())
        ).all()
        for document, status, data_type in rows:
            try:
                params = json.loads(document.request_params_json)
                key = (str(params["race_dt"]), int(params["rccrs_cd"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            result[key].append(SavedDocument(document, status, data_type))
    return result


def _has_processed(docs: list[SavedDocument], *, retry_partial: bool) -> bool:
    return any(
        saved.run_status == "completed"
        or (
            saved.run_status == "partial"
            and saved.run_data_type == "equipment_history_api78"
            and not retry_partial
        )
        for saved in docs
    )


def _cached_pages(
    documents_by_origin: dict[str, list[SavedDocument]],
) -> list[FetchedPage] | None:
    # Local and remote ingestion IDs are independent sequences. Keep their
    # page groups separate even when the numeric run IDs happen to coincide.
    by_run: dict[tuple[str, int], list[SourceDocument]] = defaultdict(list)
    for origin, docs in documents_by_origin.items():
        for saved in docs:
            by_run[(origin, saved.document.ingestion_run_id)].append(saved.document)
    for _, run_docs in sorted(
        by_run.items(),
        key=lambda pair: max(doc.retrieved_at_ms for doc in pair[1]),
        reverse=True,
    ):
        pages: list[FetchedPage] = []
        for document in run_docs:
            path = Path(document.local_path)
            if not path.is_absolute():
                path = ROOT / path
            if not path.is_file():
                break
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != document.sha256:
                break
            try:
                payload = json.loads(body)
                params = json.loads(document.request_params_json)
            except (ValueError, json.JSONDecodeError):
                break
            pages.append(
                FetchedPage(
                    endpoint=ENDPOINT,
                    operation=document.operation or "chulmainfo",
                    source_url=document.source_url,
                    public_params=params,
                    requested_at_ms=document.requested_at_ms,
                    retrieved_at_ms=document.retrieved_at_ms,
                    status_code=document.http_status_code or 200,
                    content_type=document.content_type,
                    body=body,
                    payload=payload,
                )
            )
        else:
            pages.sort(key=lambda page: int(page.public_params.get("pageNo", 1)))
            try:
                _validate_pages(pages)
            except ValueError:
                continue
            return pages
    return None


def _validate_pages(pages: list[FetchedPage]) -> list[GateEntrySheetItem]:
    if not pages:
        raise ValueError("API78 응답 페이지가 없습니다.")
    parsed = [parse_gate_entry_sheet_page(page.payload) for page in pages]
    items = [item for page in parsed for item in page.items]
    if len(items) != parsed[0].total_count:
        raise ValueError(
            f"API78 페이지가 불완전합니다: fetched={len(items)} total={parsed[0].total_count}"
        )
    expected_pages = list(range(1, len(parsed) + 1))
    if [page.page_no for page in parsed] != expected_pages:
        raise ValueError("API78 응답 페이지 순서가 불완전합니다.")
    day = str(pages[0].public_params["race_dt"])
    if any(item.race_date.strftime("%Y%m%d") != day for item in items):
        raise ValueError("API78 응답의 경주일이 요청일과 다릅니다.")
    keys = [(item.race_number, item.gate_number) for item in items]
    if len(keys) != len(set(keys)):
        raise ValueError("API78 출전마 키가 중복됩니다.")
    return items


def _existing_card_count(engine: Engine, day: str, meet: int) -> int:
    with Session(engine) as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(RaceEntry)
                .join(Race, Race.id == RaceEntry.race_id)
                .join(Racecourse, Racecourse.id == Race.racecourse_id)
                .where(
                    Race.race_date_local == _parse_date(day),
                    Racecourse.kra_meet_code == meet,
                    RaceEntry.equipment_card_observed_at_ms.is_not(None),
                )
            )
            or 0
        )


def _matched_items(
    session: Session, *, day: str, meet: int, items: list[GateEntrySheetItem]
) -> tuple[list[GateEntrySheetItem], dict[str, int]]:
    """Never attach an old card to a runner without exact race/gate/name proof."""
    race_rows = session.execute(
        select(Race.id, Race.race_number)
        .join(Racecourse, Racecourse.id == Race.racecourse_id)
        .where(
            Race.race_date_local == _parse_date(day),
            Racecourse.kra_meet_code == meet,
        )
    ).all()
    race_by_number = {number: race_id for race_id, number in race_rows}
    entries: dict[int, list[RaceEntry]] = defaultdict(list)
    if race_by_number:
        for entry in session.scalars(
            select(RaceEntry)
            .options(joinedload(RaceEntry.horse))
            .where(RaceEntry.race_id.in_(race_by_number.values()))
        ):
            entries[entry.race_id].append(entry)

    matched: list[GateEntrySheetItem] = []
    issues: dict[str, int] = defaultdict(int)
    for item in items:
        race_id = race_by_number.get(item.race_number)
        if race_id is None:
            issues["race_absent"] += 1
            continue
        candidates = entries.get(race_id, [])
        entry = next(
            (row for row in candidates if row.horse_number == item.gate_number), None
        )
        if entry is None:
            if any(_name_key(row.horse.name_ko) == _name_key(item.horse_name) for row in candidates):
                issues["gate_conflict"] += 1
            else:
                issues["entry_absent"] += 1
            continue
        if _name_key(entry.horse.name_ko) != _name_key(item.horse_name):
            issues["name_conflict"] += 1
            continue
        if entry.gate_number is not None and entry.gate_number != item.gate_number:
            issues["stored_gate_conflict"] += 1
            continue
        matched.append(item)
    return matched, dict(issues)


def _apply_card(
    engine: Engine,
    *,
    day: str,
    meet: int,
    pages: list[FetchedPage],
    matched: list[GateEntrySheetItem],
    issues: dict[str, int],
    raw_data_dir: Path,
) -> int:
    now_ms = time.time_ns() // 1_000_000
    observed_at_ms = max(page.retrieved_at_ms for page in pages)
    total_items = len(_validate_pages(pages))
    with Session(engine) as session:
        try:
            run = IngestionRun(
                source="data.go.kr/B551015/API78",
                data_type="equipment_history_api78",
                started_at_ms=now_ms,
                status="running",
                records_fetched=total_items,
            )
            session.add(run)
            session.flush()
            for page in pages:
                page_no = int(page.public_params["pageNo"])
                stored = store_kra_page(
                    page,
                    raw_data_dir=raw_data_dir,
                    data_type="gate_entry_sheet",
                    race_date=day,
                    meet=meet,
                    run_id=run.id,
                    page_no=page_no,
                )
                session.add(
                    SourceDocument(
                        ingestion_run_id=run.id,
                        source_url=page.source_url,
                        endpoint=page.endpoint,
                        operation=page.operation,
                        request_params_json=json.dumps(
                            page.public_params,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        requested_at_ms=page.requested_at_ms,
                        retrieved_at_ms=page.retrieved_at_ms,
                        http_status_code=page.status_code,
                        content_type=page.content_type,
                        response_bytes=len(page.body),
                        local_path=str(stored.path),
                        sha256=stored.sha256,
                    )
                )
            written = _write_gate_numbers(
                session, meet=meet, items=matched, observed_at_ms=observed_at_ms
            )
            run.records_written = written
            run.status = "partial" if issues else "completed"
            run.error_message = json.dumps(issues, sort_keys=True) if issues else None
            run.completed_at_ms = time.time_ns() // 1_000_000
            session.commit()
            return written
        except Exception:
            session.rollback()
            raise


def _get_pages(
    key: tuple[str, int],
    documents_by_origin: dict[str, list[SavedDocument]],
    client: KraApiClient,
) -> tuple[list[FetchedPage], int]:
    cached = _cached_pages(documents_by_origin)
    if cached is not None:
        return cached, 0
    day, meet = key
    pages = list(client.iter_gate_entry_sheet_pages(race_date=day, meet=meet))
    return pages, len(pages)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="20170101")
    parser.add_argument("--end", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--max-days", type=int)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument(
        "--retry-partial",
        action="store_true",
        help="Reprocess days with a partial historical match after correcting source links",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    start, end = _parse_date(args.start), _parse_date(args.end)
    if start > end:
        parser.error("--start는 --end보다 늦을 수 없습니다.")
    if args.max_days is not None and args.max_days < 1:
        parser.error("--max-days는 양수여야 합니다.")
    if not 1 <= args.workers <= 4:
        parser.error("--workers는 1~4 사이여야 합니다.")

    settings = get_settings()
    if not settings.database_url.startswith("postgresql") or PROJECT_REF not in settings.database_url:
        raise SystemExit("설정된 원격 DB가 horse-racing-prod 프로젝트가 아닙니다.")
    if settings.data_go_kr_service_key is None:
        raise SystemExit("공공데이터포털 서비스키가 없습니다.")

    engines = {
        "local": create_engine_for_url(LOCAL_URL),
        "remote": create_engine_for_url(settings.database_url),
    }
    try:
        targets = _targets(engines["local"], start, end)
        remote_targets = set(_targets(engines["remote"], start, end))
        if set(targets) != remote_targets:
            raise SystemExit(
                "로컬과 Supabase의 경주일·경마장 대상이 다릅니다. "
                f"local_only={len(set(targets)-remote_targets)} "
                f"remote_only={len(remote_targets-set(targets))}"
            )
        saved = {name: _saved_documents(engine) for name, engine in engines.items()}
        pending = [
            key
            for key in targets
            if not all(
                _has_processed(
                    saved[name].get(key, []), retry_partial=args.retry_partial
                )
                for name in engines
            )
        ]
        print(f"target_meet_days={len(targets)} pending={len(pending)}")
        if not args.apply:
            print("dry run only; --apply를 지정해야 공식 API 조회와 DB 저장을 실행합니다.")
            return 0

        if args.max_days is not None:
            pending = pending[: args.max_days]
        api_calls = 0
        applied = {"local": 0, "remote": 0}
        partial_days = 0
        unmatched_rows = 0
        failed: list[tuple[str, int, str]] = []
        with (
            KraApiClient(
                settings.data_go_kr_service_key.get_secret_value(),
                base_url=settings.kra_api_base_url,
                timeout_seconds=settings.http_timeout_seconds,
            ) as client,
            ThreadPoolExecutor(max_workers=args.workers) as pool,
        ):
            futures: dict[tuple[str, int], Future[tuple[list[FetchedPage], int]]] = {}
            upcoming = iter(pending)

            def submit_next() -> None:
                try:
                    next_key = next(upcoming)
                except StopIteration:
                    return
                docs = {
                    name: saved[name].get(next_key, []) for name in engines
                }
                futures[next_key] = pool.submit(_get_pages, next_key, docs, client)

            for _ in range(min(args.workers, len(pending))):
                submit_next()
            for index, key in enumerate(pending, start=1):
                day, meet = key
                completed = {
                    name: _has_processed(
                        saved[name].get(key, []), retry_partial=args.retry_partial
                    )
                    for name in engines
                }
                try:
                    pages, pages_fetched = futures.pop(key).result()
                    submit_next()
                    api_calls += pages_fetched
                    items = _validate_pages(pages)
                    if not items:
                        raise ValueError("출전마가 있는 경주일인데 API78 응답이 0행입니다.")
                    matched: dict[str, list[GateEntrySheetItem]] = {}
                    issues: dict[str, dict[str, int]] = {}
                    for name, engine in engines.items():
                        if completed[name]:
                            continue
                        if (
                            not args.retry_partial
                            and _existing_card_count(engine, day, meet)
                        ):
                            raise ValueError(
                                f"{name}에 관측 시각이 있는 출마표가 이미 있어 "
                                "사후 조회로 덮어쓸 수 없습니다."
                            )
                        with Session(engine) as session:
                            matched[name], issues[name] = _matched_items(
                                session, day=day, meet=meet, items=items
                            )
                    if len(matched) == 2 and {
                        (item.race_number, item.gate_number) for item in matched["local"]
                    } != {
                        (item.race_number, item.gate_number) for item in matched["remote"]
                    }:
                        raise ValueError("로컬·Supabase의 출전마 연결 범위가 다릅니다.")
                    for name, engine in engines.items():
                        if completed[name]:
                            continue
                        applied[name] += _apply_card(
                            engine,
                            day=day,
                            meet=meet,
                            pages=pages,
                            matched=matched[name],
                            issues=issues[name],
                            raw_data_dir=settings.raw_data_dir,
                        )
                    day_issues = next(iter(issues.values()), {})
                    if day_issues:
                        partial_days += 1
                        unmatched_rows += sum(day_issues.values())
                except KraApiRateLimitError as exc:
                    print(f"rate_limit_at={day}/{meet}: {exc}", flush=True)
                    return 2
                except Exception as exc:
                    failed.append((day, meet, f"{type(exc).__name__}: {exc}"))
                    print(f"failed={day}/{meet} {type(exc).__name__}: {exc}", flush=True)
                if index % 25 == 0 or index == len(pending):
                    print(
                        f"progress={index}/{len(pending)} api_pages={api_calls} "
                        f"local_rows={applied['local']} remote_rows={applied['remote']} "
                        f"partial_days={partial_days} unmatched_api_rows={unmatched_rows} "
                        f"failed_days={len(failed)}",
                        flush=True,
                    )
        print(f"complete failed_days={len(failed)}")
        return 1 if failed else 0
    finally:
        for engine in engines.values():
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
