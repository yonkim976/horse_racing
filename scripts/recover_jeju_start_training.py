"""Validate API22 against saved website dates, then recover a bounded Jeju gap.

Default is a no-I/O plan. --apply uses Supabase only, preserves website authority
and records before/after rows, source payloads, and multiplicity verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import START_TRAINING_ENDPOINT, START_TRAINING_OPERATION
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import Horse, HorseStartTraining
from horse_racing.jobs.canonical_post_race import write_json as write_json_exclusive
from horse_racing.jobs.daily_training import LOCK_KEY, DateCheckedApi
from horse_racing.jobs.local_race_day import KST, ROOT, LocalKraApiClient, load_settings
from horse_racing.parsers.race_day import parse_items
from horse_racing.parsers.race_supplemental import StartTrainingItem
from horse_racing.services.race_supplemental import ingest_start_training


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_exclusive(path, json.loads(json.dumps(value, default=str)))


def saved_rows(session, beginning, end):
    return [
        dict(row)
        for row in session.execute(
            select(HorseStartTraining.__table__, Horse.kra_horse_id)
            .join(Horse, Horse.id == HorseStartTraining.horse_id)
            .where(
                HorseStartTraining.meet_code == 2,
                HorseStartTraining.training_date_local.between(beginning, end),
            )
            .order_by(HorseStartTraining.id)
        ).mappings()
    ]


def source_signature(item):
    return item.horse_id, item.stable_part, item.stable_number, item.rider_name, item.remark


def saved_signature(row):
    return (
        row["kra_horse_id"],
        row["stable_part"],
        row["stable_number"],
        row["rider_name"],
        row["remark"],
    )


class CachedPages:
    def __init__(self, pages):
        self.pages = pages

    def iter_pages(self, **kwargs):
        if kwargs["endpoint"] != START_TRAINING_ENDPOINT or kwargs["public_params"]["meet"] != 2:
            raise ValueError("cached_source_scope_mismatch")
        day = kwargs["public_params"]["tr_date"]
        return iter(self.pages[day])


def execute(*, start, end, apply=False):
    today = datetime.now(KST).date()
    if not today - timedelta(days=13) <= start <= end <= today:
        raise ValueError("Only the latest 14 KST dates are allowed")
    print(
        json.dumps(
            {
                "start": str(start),
                "end": str(end),
                "apply": apply,
                "target": "Supabase",
                "sqlite_writes": False,
            }
        ),
        flush=True,
    )
    if not apply:
        return 0
    settings = load_settings()
    engine = create_engine_for_url(settings.database_url)
    directory = ROOT / "data/research" / f"jeju_start_api_recovery_{today:%Y%m%d}_{time.time_ns()}"
    directory.mkdir(mode=0o700)
    try:
        with engine.connect() as lock:
            if not lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}):
                print('{"status":"busy"}', flush=True)
                return 75
            lock.commit()
            try:
                with (
                    Session(engine) as session,
                    LocalKraApiClient(settings.data_go_kr_service_key.get_secret_value()) as api,
                ):
                    before = saved_rows(session, start - timedelta(days=8), end)
                    session.rollback()
                    write_json(directory / "before.json", before)
                    website = [r for r in before if r["source_kind"] == "kra_website"]
                    reference_days = sorted({r["training_date_local"] for r in website})[-4:]
                    if not reference_days:
                        raise ValueError("no_website_reference_dates")
                    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
                    checked, pages, items, references = DateCheckedApi(api), {}, {}, []
                    for day in sorted(set(reference_days + days)):
                        label = day.strftime("%Y%m%d")
                        pages[label] = list(
                            checked.iter_pages(
                                endpoint=START_TRAINING_ENDPOINT,
                                operation=START_TRAINING_OPERATION,
                                public_params={"meet": 2, "tr_date": label, "_type": "json"},
                                page_size=1000,
                            )
                        )
                        items[label] = [
                            i
                            for p in pages[label]
                            for i in parse_items(p.payload, StartTrainingItem)
                        ]
                        for n, page in enumerate(pages[label], 1):
                            write_json(
                                directory / "capture" / f"{label}_page_{n}.json",
                                {
                                    "endpoint": START_TRAINING_ENDPOINT,
                                    "public_params": dict(page.public_params),
                                    "sha256": hashlib.sha256(page.body).hexdigest(),
                                    "payload": page.payload,
                                },
                            )
                        if day in reference_days:
                            expected = Counter(
                                saved_signature(r)
                                for r in website
                                if r["training_date_local"] == day
                            )
                            incoming = Counter(source_signature(i) for i in items[label])
                            reference = {
                                "date": str(day),
                                "website_rows": sum(expected.values()),
                                "api_rows": sum(incoming.values()),
                                "missing": sum((expected - incoming).values()),
                                "extra": sum((incoming - expected).values()),
                            }
                            references.append(reference)
                    write_json(directory / "reference_checks.json", references)
                    if any(r["missing"] or r["extra"] for r in references):
                        raise ValueError("api_website_multiset_mismatch")
                    results = []
                    for day in days:
                        label = day.strftime("%Y%m%d")
                        summary = ingest_start_training(
                            session,
                            CachedPages(pages),
                            training_date=label,
                            meet=2,
                            raw_data_dir=directory / "raw",
                            page_size=1000,
                        )
                        saved = saved_rows(session, day, day)
                        expected = Counter(source_signature(i) for i in items[label])
                        actual = Counter(saved_signature(r) for r in saved)
                        # Empty API dates are publication waits, not evidence of no sessions.
                        if expected and expected != actual:
                            raise ValueError("post_write_multiset_mismatch")
                        results.append(
                            {
                                "date": str(day),
                                "run_id": summary.run_id,
                                "fetched": summary.records_fetched,
                                "processed": summary.records_written,
                                "stored": len(saved),
                                "missing_after_write": sum((expected - actual).values()),
                            }
                        )
                        session.rollback()
                    after = saved_rows(session, start - timedelta(days=8), end)
                    write_json(directory / "after.json", after)
                    old_ids = {r["id"] for r in before}
                    new_ids = {r["id"] for r in after}
                    if old_ids - new_ids:
                        raise ValueError("existing_record_removed")
                    # Website rows keep distinct locations and repeated sessions unchanged.
                    after_by_id = {r["id"]: r for r in after}
                    if any(after_by_id[r["id"]] != r for r in website):
                        raise ValueError("website_record_changed")
                    report = {
                        "status": "completed",
                        "references": references,
                        "results": results,
                        "added": len(new_ids - old_ids),
                        "removed": 0,
                        "website_rows_preserved": len(website),
                        "output": str(directory),
                    }
                    write_json(directory / "report.json", report)
                    print(json.dumps(report, ensure_ascii=False), flush=True)
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                lock.commit()
    finally:
        engine.dispose()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        return execute(start=args.start, end=args.end, apply=args.apply)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
