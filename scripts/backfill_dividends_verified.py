"""Reconcile API301 closing dividends, without deleting data or changing schema.

Dry-run by default. Resume with the same --run-dir to reuse SHA-verified raw pages.
The two databases commit separately; retries are idempotent by race/pool/selection.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import shutil
import time
from datetime import date
from pathlib import Path

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import (
    FINAL_DIVIDEND_ENDPOINT,
    FINAL_DIVIDEND_OPERATION,
    FetchedPage,
    KraApiRateLimitError,
)
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import IngestionRun, OddsSnapshot, RaceEntry, RaceResult, SourceDocument
from horse_racing.jobs.local_race_day import LocalKraApiClient, load_settings
from horse_racing.jobs.weekly_entry_cards import require_complete_pages
from horse_racing.parsers.horse_history import parse_meet_code
from horse_racing.parsers.race_day import FinalDividendItem, parse_items

ROOT = Path(__file__).resolve().parents[1]
ARITY = {"WIN": 1, "PLC": 1, "QNL": 2, "QPL": 2, "EXA": 2, "TLA": 3, "TRI": 3}
LOCK = 63831012620261002
RACES = """SELECT r.id,r.race_number,r.status FROM races r
 JOIN racecourses c ON c.id=r.racecourse_id
 WHERE r.race_date_local=:day AND c.kra_meet_code=:meet"""


def save_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def inventory(session, day, meet):
    races = {
        r.race_number: (r.id, r.status)
        for r in session.execute(text(RACES), {"day": day, "meet": meet})
    }
    entries = {}
    grouped = {rid: [] for rid, _ in races.values()}
    for row in session.execute(
        select(
            RaceEntry.race_id,
            RaceEntry.horse_number,
            RaceResult.finish_position,
            RaceResult.rank_remark,
        )
        .outerjoin(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .where(RaceEntry.race_id.in_(grouped))
    ):
        grouped[row.race_id].append(row)
    for no, (rid, _) in races.items():
        rows = grouped[rid]
        entries[no] = {r.horse_number for r in rows}
        if not rows:
            raise ValueError("missing_entries")
        if not any(r.finish_position == 1 for r in rows):
            if not all(r.rank_remark == "경주취소" for r in rows):
                raise ValueError("no_winner_without_confirmed_cancellation")
            races[no] = (rid, "confirmed_cancelled")
    return races, entries


def validate(items, day, meet, races, entries):
    expected, ignored, duplicates = {}, 0, 0
    for item in items:
        if item.race_date.isoformat() != day or parse_meet_code(item.meet_name) != meet:
            raise ValueError("unexpected_source_date_or_venue")
        if item.race_number not in races:
            raise ValueError("source_race_missing_in_operational_database")
        if item.bet_type not in ARITY:
            raise ValueError("unexpected_pool")
        if item.odds is None:
            ignored += 1
            continue
        if races[item.race_number][1] == "confirmed_cancelled":
            # A cancelled whole race has no settled dividend, even if API301 has quotes.
            continue
        if not math.isfinite(item.odds) or item.odds <= 0:
            raise ValueError("invalid_positive_odds")
        if races[item.race_number][1] != "completed":
            raise ValueError("positive_dividend_for_unsettled_race")
        numbers = tuple(int(x) for x in item.selection_key.split("-"))
        if (
            len(numbers) != ARITY[item.bet_type]
            or len(set(numbers)) != len(numbers)
            or not set(numbers) <= entries[item.race_number]
        ):
            raise ValueError("invalid_selection")
        key = (item.race_number, item.bet_type, item.selection_key)
        if key in expected:
            if expected[key] != item.odds:
                raise ValueError("conflicting_source_duplicate")
            duplicates += 1
        expected[key] = item.odds
    for no, (_, status) in races.items():
        if status == "completed" and {k[1] for k in expected if k[0] == no} != set(ARITY):
            raise ValueError("settled_race_missing_official_pools")
    return expected, ignored, duplicates


def existing(session, races):
    result = {}
    numbers = {rid: no for no, (rid, _) in races.items()}
    rows = session.execute(
        select(
            OddsSnapshot.id,
            OddsSnapshot.race_id,
            OddsSnapshot.bet_type,
            OddsSnapshot.selection_key,
            OddsSnapshot.odds,
            OddsSnapshot.observed_at_ms,
        ).where(OddsSnapshot.race_id.in_(numbers))
    )
    for row in rows:
        key = (numbers[row.race_id], row.bet_type, row.selection_key)
        if key in result:
            raise ValueError("duplicate_database_business_key")
        result[key] = (row.id, row.odds, row.observed_at_ms)
    return result


def confirmed_nonstarter_zero_keys(session, races, items):
    """Explain extras using whole-race cancellation or nonstarter plus API zero.

    These rows are retained, not rewritten as zero (which would violate the schema).
    This is an audit exclusion, NOT a change to frontend serving filters.
    """
    numbers = {rid: no for no, (rid, _) in races.items()}
    nonstarters = set()
    for row in session.execute(
        select(
            RaceEntry.race_id,
            RaceEntry.horse_number,
            RaceEntry.scratched,
            RaceResult.finish_position,
        )
        .outerjoin(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .where(RaceEntry.race_id.in_(numbers))
    ):
        if row.scratched and row.finish_position in {91, 92, 93, 94, 95, 96, 99}:
            nonstarters.add((numbers[row.race_id], row.horse_number))
    cancelled_stored = {
        k for k in existing(session, races) if races[k[0]][1] == "confirmed_cancelled"
    }
    return cancelled_stored | {
        (i.race_number, i.bet_type, i.selection_key)
        for i in items
        if i.odds is None
        and any(
            (i.race_number, n) in nonstarters
            for n in (i.horse_number_1, i.horse_number_2, i.horse_number_3)
        )
    }


def reconcile(session, races, expected, stamp, apply, allowed_retained=None):
    before = existing(session, races)
    extra = set(before) - set(expected)
    if extra - (allowed_retained or set()):
        raise ValueError("stored_selection_absent_from_positive_official_response")
    additions, changes = [], []
    for key, odds in expected.items():
        no, pool, selection = key
        if key not in before:
            additions.append(
                dict(
                    race_id=races[no][0],
                    bet_type=pool,
                    selection_key=selection,
                    odds=odds,
                    observed_at_ms=stamp,
                )
            )
        elif not math.isclose(before[key][1], odds, rel_tol=0, abs_tol=1e-8):
            changes.append(
                dict(
                    row_id=before[key][0],
                    value=odds,
                    stamp=stamp,
                    old_odds=before[key][1],
                    old_stamp=before[key][2],
                    key=list(key),
                )
            )
    if apply:
        for offset in range(0, len(additions), 1000):
            session.execute(insert(OddsSnapshot.__table__), additions[offset : offset + 1000])
        if changes:
            session.execute(
                text(
                    "UPDATE odds_snapshots SET odds=:value,observed_at_ms=:stamp WHERE id=:row_id"
                ),
                [{k: r[k] for k in ("row_id", "value", "stamp")} for r in changes],
            )
        after = existing(session, races)
        if set(after) != set(expected) | extra or any(
            not math.isclose(after[k][1], v, rel_tol=0, abs_tol=1e-8) for k, v in expected.items()
        ):
            raise ValueError("post_write_official_mismatch")
    return {
        "inserted": len(additions),
        "updated": len(changes),
        "unchanged": len(expected) - len(additions) - len(changes),
        "changes": changes,
        "retained_nonstarter_zero_rows": sum(
            races[k[0]][1] != "confirmed_cancelled" for k in extra
        ),
        "retained_nonstarter_zero_values": [
            {
                "key": list(k),
                "id": before[k][0],
                "odds": before[k][1],
                "observed_at_ms": before[k][2],
            }
            for k in sorted(extra)
            if races[k[0]][1] != "confirmed_cancelled"
        ],
        "retained_cancelled_race_rows": sum(races[k[0]][1] == "confirmed_cancelled" for k in extra),
        "retained_cancelled_race_values": [
            {
                "key": list(k),
                "id": before[k][0],
                "odds": before[k][1],
                "observed_at_ms": before[k][2],
            }
            for k in sorted(extra)
            if races[k[0]][1] == "confirmed_cancelled"
        ],
        "verified": apply,
    }


def archive_pages(folder, day, meet):
    """Reuse only complete, SHA-verified official response page sets."""
    engine = create_engine_for_url(f"sqlite:///{ROOT / 'data/horse_racing.sqlite3'}")
    groups = {}
    with Session(engine) as session:
        rows = session.scalars(
            select(SourceDocument)
            .join(IngestionRun)
            .where(
                IngestionRun.data_type == "final_dividend",
                IngestionRun.status == "completed",
                SourceDocument.request_params_json.contains(day.replace("-", "")),
            )
            .order_by(SourceDocument.retrieved_at_ms.desc())
        )
        for row in rows:
            params = json.loads(row.request_params_json)
            if (
                str(params.get("rc_date")) != day.replace("-", "")
                or int(params.get("meet") or 0) != meet
            ):
                continue
            groups.setdefault(row.ingestion_run_id, []).append(row)
        for run_id, documents in groups.items():
            pages, metadata = [], []
            for row in sorted(
                documents, key=lambda d: int(json.loads(d.request_params_json)["pageNo"])
            ):
                path = Path(row.local_path)
                if not path.exists():
                    break
                body = path.read_bytes()
                if hashlib.sha256(body).hexdigest() != row.sha256:
                    break
                params = json.loads(row.request_params_json)
                page = FetchedPage(
                    endpoint=row.endpoint,
                    operation=row.operation,
                    source_url=row.source_url,
                    public_params=params,
                    requested_at_ms=row.requested_at_ms,
                    retrieved_at_ms=row.retrieved_at_ms,
                    status_code=row.http_status_code,
                    content_type=row.content_type,
                    body=body,
                    payload=json.loads(body),
                )
                pages.append(page)
                metadata.append(
                    dict(
                        endpoint=page.endpoint,
                        operation=page.operation,
                        source_url=page.source_url,
                        public_params=params,
                        requested_at_ms=page.requested_at_ms,
                        retrieved_at_ms=page.retrieved_at_ms,
                        status_code=page.status_code,
                        content_type=page.content_type,
                        local_path=str(path.resolve()),
                        sha256=row.sha256,
                    )
                )
            else:
                try:
                    count = sum(len(parse_items(p.payload, FinalDividendItem)) for p in pages)
                    require_complete_pages(pages, count)
                except ValueError:
                    continue
                save_json(folder / f"{day}_{meet}.json", metadata)
                save_json(
                    folder / f"{day}_{meet}.origin.json",
                    {"origin": "sha_verified_official_archive", "original_run_id": run_id},
                )
                return pages, metadata
    raise ValueError("complete_official_archive_not_found")


def pages_for(client, folder, day, meet, archive_before=None):
    path = folder / f"{day}_{meet}.json"
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        pages = []
        for metadata in cached:
            body = Path(metadata.pop("local_path")).read_bytes()
            if hashlib.sha256(body).hexdigest() != metadata.pop("sha256"):
                raise ValueError("cached_raw_hash_mismatch")
            pages.append(FetchedPage(**metadata, body=body, payload=json.loads(body)))
        return pages, json.loads(path.read_text(encoding="utf-8"))
    if archive_before and date.fromisoformat(day) < archive_before:
        return archive_pages(folder, day, meet)
    if shutil.disk_usage(ROOT).free < 2 * 1024**3:
        raise RuntimeError("local_disk_below_2GiB_guard")
    pages = list(
        client.iter_pages(
            endpoint=FINAL_DIVIDEND_ENDPOINT,
            operation=FINAL_DIVIDEND_OPERATION,
            public_params={"meet": meet, "rc_date": day.replace("-", ""), "_type": "json"},
            page_size=20000,
        )
    )
    metadata = []
    for page in pages:
        digest = hashlib.sha256(page.body).hexdigest()
        raw = folder / f"{day}_{meet}_p{page.public_params['pageNo']}_{digest[:12]}.raw.json"
        raw.write_bytes(page.body)
        metadata.append(
            dict(
                endpoint=page.endpoint,
                operation=page.operation,
                source_url=page.source_url,
                public_params=dict(page.public_params),
                requested_at_ms=page.requested_at_ms,
                retrieved_at_ms=page.retrieved_at_ms,
                status_code=page.status_code,
                content_type=page.content_type,
                local_path=str(raw),
                sha256=digest,
            )
        )
    save_json(path, metadata)
    return pages, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--archive-before", type=date.fromisoformat)
    args = parser.parse_args()
    if args.end.year != 2026:
        parser.error("This backfill is scoped to 2026")
    folder = args.run_dir.resolve()
    if not folder.is_relative_to(ROOT / "data"):
        parser.error("run-dir must be inside workspace/data")
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(args, folder)


def run(args, folder):
    settings = load_settings()
    engines = {
        "local": create_engine_for_url(f"sqlite:///{ROOT / 'data/horse_racing.sqlite3'}"),
        "supabase": create_engine_for_url(settings.database_url),
    }
    params = {"start": "2026-01-01", "end": args.end.isoformat()}
    query = text("""SELECT DISTINCT r.race_date_local,c.kra_meet_code FROM races r
      JOIN racecourses c ON c.id=r.racecourse_id WHERE r.race_date_local BETWEEN
      :start AND :end AND r.status='completed' ORDER BY r.race_date_local DESC,c.kra_meet_code""")
    scope = {}
    for name, engine in engines.items():
        with engine.connect() as connection:
            scope[name] = [(str(d), int(m)) for d, m in connection.execute(query, params)]
    if scope["local"] != scope["supabase"]:
        raise ValueError("local_supabase_race_day_scope_mismatch")
    report = {
        "start": params["start"],
        "end": params["end"],
        "apply": args.apply,
        "planned_pairs": len(scope["local"]),
        "pairs": [],
        "errors": [],
    }
    report_path = folder / "report.json"
    if args.apply and report_path.exists():
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        if previous["end"] != report["end"] or not previous["apply"]:
            raise ValueError("resume_scope_mismatch_use_new_run_dir")
        report["pairs"] = previous["pairs"]
        report["previous_errors"] = previous.get("previous_errors", []) + previous["errors"]
    done = {
        (r["day"], r["meet"])
        for r in report["pairs"]
        if all(v["verified"] for v in r["databases"].values())
    }
    with engines["supabase"].connect() as guard:
        if not guard.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK}):
            raise RuntimeError("dividend_backfill_already_running")
        try:
            with LocalKraApiClient(
                settings.data_go_kr_service_key.get_secret_value(),
                base_url=settings.kra_api_base_url,
                timeout_seconds=30,
            ) as client:
                for index, (day, meet) in enumerate(scope["local"], 1):
                    if (day, meet) in done:
                        continue
                    try:
                        pages, metadata = pages_for(client, folder, day, meet, args.archive_before)
                        items = [
                            x for p in pages for x in parse_items(p.payload, FinalDividendItem)
                        ]
                        require_complete_pages(pages, len(items))
                        row = {
                            "day": day,
                            "meet": meet,
                            "source_rows": len(items),
                            "pages": len(pages),
                            "databases": {},
                            "source_origin": "fresh_official_api",
                        }
                        if (folder / f"{day}_{meet}.origin.json").exists():
                            row["source_origin"] = "sha_verified_official_archive"
                        stamp = max(p.retrieved_at_ms for p in pages)
                        fingerprints = []
                        for engine in engines.values():
                            with Session(engine) as preflight:
                                check_races, check_entries = inventory(preflight, day, meet)
                                check_expected, _, _ = validate(
                                    items, day, meet, check_races, check_entries
                                )
                                fingerprints.append(
                                    (
                                        {n: s for n, (_, s) in check_races.items()},
                                        check_entries,
                                        check_expected,
                                    )
                                )
                        if fingerprints[0] != fingerprints[1]:
                            raise ValueError("local_remote_source_mapping_mismatch")
                        for name, engine in engines.items():
                            with Session(engine) as session, session.begin():
                                races, entries = inventory(session, day, meet)
                                expected, ignored, duplicate = validate(
                                    items, day, meet, races, entries
                                )
                                if (
                                    {n: s for n, (_, s) in races.items()},
                                    entries,
                                    expected,
                                ) != fingerprints[0]:
                                    raise ValueError("operational_mapping_changed_during_backfill")
                                row.update(
                                    positive_rows=len(expected),
                                    nonpositive_rows=ignored,
                                    cancelled_positive_source_rows=sum(
                                        i.odds is not None
                                        and races[i.race_number][1] == "confirmed_cancelled"
                                        for i in items
                                    ),
                                    source_duplicates=duplicate,
                                    race_count=len(races),
                                    cancelled_races=[
                                        no
                                        for no, (_, s) in races.items()
                                        if s == "confirmed_cancelled"
                                    ],
                                    sentinel_9999_9=sum(v == 9999.9 for v in expected.values()),
                                )
                                # Save old values before a commit, to make any update auditable.
                                retained = confirmed_nonstarter_zero_keys(session, races, items)
                                result = reconcile(session, races, expected, stamp, False, retained)
                                if row["source_origin"] == "sha_verified_official_archive" and (
                                    result["updated"] or result["retained_nonstarter_zero_rows"]
                                ):
                                    raise ValueError("archive_conflict_requires_fresh_api")
                                row["databases"][name] = result
                                save_json(folder / f"{day}_{meet}.changes.json", row)
                                if args.apply:
                                    result = reconcile(
                                        session, races, expected, stamp, True, retained
                                    )
                                    run = IngestionRun(
                                        source="kra_api",
                                        data_type="final_dividend",
                                        started_at_ms=int(time.time() * 1000),
                                        completed_at_ms=int(time.time() * 1000),
                                        status="completed",
                                        records_fetched=len(items),
                                        records_written=result["inserted"] + result["updated"],
                                    )
                                    session.add(run)
                                    session.flush()
                                    for p, meta in zip(pages, metadata, strict=True):
                                        session.add(
                                            SourceDocument(
                                                ingestion_run_id=run.id,
                                                source_url=p.source_url,
                                                endpoint=p.endpoint,
                                                operation=p.operation,
                                                request_params_json=json.dumps(
                                                    dict(p.public_params)
                                                ),
                                                requested_at_ms=p.requested_at_ms,
                                                retrieved_at_ms=p.retrieved_at_ms,
                                                http_status_code=p.status_code,
                                                content_type=p.content_type,
                                                response_bytes=len(p.body),
                                                local_path=meta["local_path"],
                                                sha256=meta["sha256"],
                                            )
                                        )
                                    result["ingestion_run_id"] = run.id
                                    row["databases"][name] = result
                        report["pairs"].append(row)
                        print(
                            json.dumps(
                                {
                                    "progress": f"{index}/{len(scope['local'])}",
                                    **{k: v for k, v in row.items() if k != "databases"},
                                    "writes": {
                                        n: {k: r[k] for k in ("inserted", "updated", "verified")}
                                        for n, r in row["databases"].items()
                                    },
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                    except Exception as exc:
                        # Never print transport exceptions/URLs which could include credentials.
                        error = {"day": day, "meet": meet, "type": type(exc).__name__}
                        if isinstance(exc, (ValueError, RuntimeError)) and str(exc).isidentifier():
                            error["reason"] = str(exc)
                        report["errors"].append(error)
                        print(json.dumps(error), flush=True)
                        if isinstance(exc, KraApiRateLimitError) or len(report["errors"]) >= 3:
                            save_json(report_path, report)
                            raise RuntimeError("backfill_stopped_inspect_report") from None
                    save_json(report_path, report)
        finally:
            guard.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK})
    print(
        json.dumps(
            {
                "report": str(report_path),
                "processed": len(report["pairs"]),
                "errors": len(report["errors"]),
            }
        ),
        flush=True,
    )
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
