"""Manual Supabase-only refresh of current horse profiles and recent clinics.

No operational SQLite, predictions, deployments or schedules are changed.
Medical raw diagnosis slots and their separate term links are maintained by the
existing ingestion service. Default is a no-I/O plan; --apply performs writes.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import RACE_HORSE_INFO_ENDPOINT
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    HorseMedical,
    HorseMedicalDiagnosis,
    HorseProfileSnapshot,
    MedicalDiagnosisTerm,
)
from horse_racing.jobs.canonical_post_race import KST, ROOT, write_json
from horse_racing.jobs.daily_training import changes
from horse_racing.jobs.local_race_day import LocalKraApiClient, load_settings
from horse_racing.jobs.weekly_entry_cards import require_complete_pages
from horse_racing.parsers.horse_history import HorseDetailItem, HorseMedicalItem
from horse_racing.parsers.race_day import parse_items
from horse_racing.services.horse_history import ingest_horse_profiles, ingest_medical

MEETS = (1, 2, 3)


class ScopeCheckedApi:
    def __init__(self, client):
        self.client = client

    def iter_pages(self, **kwargs):
        # Fetch and validate every page before the ingestion writer sees any row.
        pages = list(self.client.iter_pages(**kwargs))
        profile = kwargs["endpoint"] == RACE_HORSE_INFO_ENDPOINT
        model = HorseDetailItem if profile else HorseMedicalItem
        items = [item for page in pages for item in parse_items(page.payload, model)]
        require_complete_pages(pages, len(items))
        params = kwargs["public_params"]
        if any(item.meet_code != params["meet"] for item in items):
            raise ValueError("horse_api_meet_mismatch")
        if profile:
            if params.get("act_gubun") != "y" or not items:
                raise ValueError("active_profile_empty_or_wrong_scope")
            if len({item.horse_id for item in items}) != len(items):
                raise ValueError("duplicate_profile_horse")
        elif any(item.clinic_date.strftime("%Y%m%d") != params["clinic_date"] for item in items):
            raise ValueError("medical_api_date_mismatch")
        self.last_items = items
        return iter(pages)


def medical_coverage(session, items, *, day, meet):
    expected = {(i.horse_id, i.hospital_name, i.diagnosis_1, i.diagnosis_2) for i in items}
    saved = set(
        session.execute(
            select(
                Horse.kra_horse_id,
                HorseMedical.hospital_name,
                HorseMedical.diagnosis_1,
                HorseMedical.diagnosis_2,
            )
            .join(HorseMedical, HorseMedical.horse_id == Horse.id)
            .where(HorseMedical.clinic_date_local == day, HorseMedical.meet_code == meet)
        ).tuples()
    )
    if expected - saved:
        raise ValueError("medical_post_write_coverage_mismatch")
    return {
        "source_unique": len(expected),
        "missing_after_write": 0,
        "stored_only_preserved": len(saved - expected),
    }


def snapshot(session, model, condition=None):
    ignored = {"id", "observed_at_ms", "profile_observed_at_ms", "active_status_observed_at_ms"}
    statement = select(model.__table__)
    if condition is not None:
        statement = statement.where(condition)
    return {
        row["id"]: tuple(
            (c.name, row[c.name]) for c in model.__table__.columns if c.name not in ignored
        )
        for row in session.execute(statement).mappings()
    }


def emit(value):
    print(json.dumps(value, ensure_ascii=False, default=str), flush=True)


def refresh(settings, *, start, end, directory, include_profiles=True, include_medical=True):
    engine = create_engine_for_url(settings.database_url)
    results, errors = [], []
    with (
        Session(engine) as session,
        LocalKraApiClient(settings.data_go_kr_service_key.get_secret_value()) as client,
    ):
        checked = ScopeCheckedApi(client)
        scope = HorseMedical.clinic_date_local.between(start, end)
        before_medical = snapshot(session, HorseMedical, scope)
        before_horses = snapshot(session, Horse)
        before_terms = set(session.scalars(select(MedicalDiagnosisTerm.raw_text)))
        before_profiles = session.scalar(select(func.count()).select_from(HorseProfileSnapshot))
        session.commit()
        # Clinics can carry historical horse names; latest profiles are applied last.
        for offset in range((end - start).days + 1 if include_medical else 0):
            day = start + timedelta(days=offset)
            for meet in MEETS:
                try:
                    summary = ingest_medical(
                        session,
                        checked,
                        clinic_date=day.strftime("%Y%m%d"),
                        meet=meet,
                        raw_data_dir=directory / "raw",
                        page_size=1000,
                    )
                    result = {
                        "kind": "medical",
                        "meet": meet,
                        "date": str(day),
                        "run_id": summary.run_id,
                        "fetched": summary.records_fetched,
                        "processed": summary.records_written,
                        **medical_coverage(session, checked.last_items, day=day, meet=meet),
                    }
                    results.append(result)
                    emit(result)
                except Exception as exc:
                    session.rollback()
                    # Do not print URLs, parameters or SQL exceptions with credentials.
                    error = {
                        "kind": "medical",
                        "meet": meet,
                        "date": str(day),
                        "error_type": type(exc).__name__,
                    }
                    errors.append(error)
                    emit(error)
        for meet in MEETS if include_profiles else ():
            try:
                summary = ingest_horse_profiles(
                    session,
                    checked,
                    meet=meet,
                    snapshot_date=end.strftime("%Y%m%d"),
                    raw_data_dir=directory / "raw",
                    page_size=1000,
                )
                result = {
                    "kind": "active_profiles",
                    "meet": meet,
                    "run_id": summary.run_id,
                    "fetched": summary.records_fetched,
                    "processed": summary.records_written,
                }
                results.append(result)
                emit(result)
            except Exception as exc:
                session.rollback()
                error = {"kind": "active_profiles", "meet": meet, "error_type": type(exc).__name__}
                errors.append(error)
                emit(error)
        after_medical = snapshot(session, HorseMedical, scope)
        after_horses = snapshot(session, Horse)
        after_terms = set(session.scalars(select(MedicalDiagnosisTerm.raw_text)))
        after_profiles = session.scalar(select(func.count()).select_from(HorseProfileSnapshot))
        missing_links = 0
        for slot in (1, 2):
            diagnosis = getattr(HorseMedical, f"diagnosis_{slot}")
            missing_links += session.scalar(
                select(func.count())
                .select_from(HorseMedical)
                .where(
                    scope,
                    diagnosis.is_not(None),
                    func.trim(diagnosis).not_in(("", "-")),
                    ~select(HorseMedicalDiagnosis.horse_medical_id)
                    .where(
                        HorseMedicalDiagnosis.horse_medical_id == HorseMedical.id,
                        HorseMedicalDiagnosis.source_slot == slot,
                    )
                    .exists(),
                )
            )
        latest = session.execute(
            select(HorseMedical.meet_code, func.max(HorseMedical.clinic_date_local)).group_by(
                HorseMedical.meet_code
            )
        ).all()
        report = {
            "status": "failed"
            if errors and not results
            else ("partial" if errors or missing_links else "completed"),
            "as_of": datetime.now(KST).isoformat(),
            "start": str(start),
            "end": str(end),
            "target": "Supabase only",
            "results": results,
            "errors": errors,
            "medical_changes": changes(before_medical, after_medical),
            "horse_business_changes": changes(before_horses, after_horses),
            "profile_snapshots_added": after_profiles - before_profiles,
            "diagnosis_terms_added": len(after_terms - before_terms),
            "new_diagnosis_terms": sorted(after_terms - before_terms),
            "missing_diagnosis_links_in_window": missing_links,
            "medical_latest_dates": {str(m): str(d) for m, d in latest},
        }
        write_json(directory / "report.json", report)
        emit({k: v for k, v in report.items() if k != "results"})
    engine.dispose()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    today = datetime.now(KST).date()
    parser.add_argument("--start", type=date.fromisoformat, default=today - timedelta(days=6))
    parser.add_argument("--end", type=date.fromisoformat, default=today)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.start <= args.end <= today or (args.end - args.start).days > 31:
        parser.error("최근 32일 이내의 유효한 날짜 범위를 지정하세요")
    if not args.apply:
        emit(
            {
                "mode": "plan",
                "start": args.start,
                "end": args.end,
                "meets": MEETS,
                "target": "Supabase only",
                "writes": False,
            }
        )
        return
    settings = load_settings()
    directory = (
        ROOT
        / "data/research"
        / ("horse_profile_medical_refresh_" + datetime.now(KST).strftime("%Y%m%d_%H%M%S"))
    )
    directory.mkdir(exist_ok=False)
    report = refresh(settings, start=args.start, end=args.end, directory=directory)
    emit({"report": str((directory / "report.json").relative_to(ROOT))})
    if report["errors"] or report["missing_diagnosis_links_in_window"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
