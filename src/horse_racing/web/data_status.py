from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from horse_racing.db.models import IngestionRun

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True, slots=True)
class DataSourceStatus:
    label: str
    category: str
    row_count: int
    latest_date: str


@dataclass(frozen=True, slots=True)
class IngestionStatus:
    data_type: str
    status: str
    status_label: str
    completed_at: str
    fetched: int
    written: int
    error: str


@dataclass(frozen=True, slots=True)
class DataStatusPage:
    sources: list[DataSourceStatus]
    runs: list[IngestionStatus]
    total_rows: int
    completed_runs: int
    failed_runs: int


SOURCE_QUERIES = (
    ("공식 경주", "경주", "SELECT COUNT(*) row_count, MAX(race_date_local) latest_date FROM races"),
    (
        "경주 결과",
        "경주",
        "SELECT COUNT(*) row_count, MAX(r.race_date_local) latest_date "
        "FROM race_results x JOIN race_entries e ON e.id=x.race_entry_id "
        "JOIN races r ON r.id=e.race_id",
    ),
    (
        "확정배당",
        "경주",
        "SELECT COUNT(*) row_count, MAX(r.race_date_local) latest_date "
        "FROM odds_snapshots x JOIN races r ON r.id=x.race_id",
    ),
    (
        "구간기록",
        "경주",
        "SELECT COUNT(*) row_count, MAX(r.race_date_local) latest_date "
        "FROM race_section_results x JOIN race_entries e ON e.id=x.race_entry_id "
        "JOIN races r ON r.id=e.race_id",
    ),
    (
        "주행심사",
        "심사",
        "SELECT COUNT(*) row_count, MAX(trial_date_local) latest_date FROM running_trials",
    ),
    (
        "주행심사 결과",
        "심사",
        "SELECT COUNT(*) row_count, MAX(t.trial_date_local) latest_date "
        "FROM running_trial_results x JOIN running_trials t ON t.id=x.running_trial_id",
    ),
    (
        "마체중",
        "말 상태",
        "SELECT COUNT(*) row_count, MAX(race_date_local) latest_date "
        "FROM horse_weight_history",
    ),
    (
        "훈련",
        "말 상태",
        "SELECT COUNT(*) row_count, MAX(training_date_local) latest_date FROM horse_training",
    ),
    (
        "진료",
        "말 상태",
        "SELECT COUNT(*) row_count, MAX(clinic_date_local) latest_date FROM horse_medical",
    ),
    (
        "출발훈련",
        "말 상태",
        "SELECT COUNT(*) row_count, MAX(training_date_local) latest_date "
        "FROM horse_start_training",
    ),
    (
        "레이팅 스냅샷",
        "기준정보",
        "SELECT COUNT(*) row_count, "
        "DATE(MAX(observed_at_ms) / 1000, 'unixepoch', '+9 hours') latest_date "
        "FROM horse_rating_snapshots",
    ),
    (
        "말 프로필 스냅샷",
        "기준정보",
        "SELECT COUNT(*) row_count, "
        "DATE(MAX(observed_at_ms) / 1000, 'unixepoch', '+9 hours') latest_date "
        "FROM horse_profile_snapshots",
    ),
    (
        "등급변동",
        "기준정보",
        "SELECT COUNT(*) row_count, "
        "DATE(MAX(observed_at_ms) / 1000, 'unixepoch', '+9 hours') latest_date "
        "FROM horse_grade_changes",
    ),
    (
        "기수변경",
        "경주 보강",
        "SELECT COUNT(*) row_count, MAX(race_date_local) latest_date FROM jockey_changes",
    ),
    (
        "출전취소",
        "경주 보강",
        "SELECT COUNT(*) row_count, MAX(race_date_local) latest_date FROM race_scratches",
    ),
    (
        "장구·폐출혈",
        "경주 보강",
        "SELECT COUNT(*) row_count, MAX(race_date_local) latest_date FROM entry_equipment",
    ),
    (
        "심판리포트",
        "경주 보강",
        "SELECT COUNT(*) row_count, MAX(race_date_local) latest_date "
        "FROM race_steward_reports",
    ),
)

RUN_LABELS = {
    "running": "진행 중",
    "completed": "완료",
    "failed": "실패",
    "partial": "일부 완료",
}


def load_data_status(session: Session) -> DataStatusPage:
    sources: list[DataSourceStatus] = []
    for label, category, query in SOURCE_QUERIES:
        row = session.execute(text(query)).one()
        sources.append(
            DataSourceStatus(
                label=label,
                category=category,
                row_count=int(row.row_count),
                latest_date=str(getattr(row, "latest_date", None) or "—"),
            )
        )

    latest_ids = (
        select(func.max(IngestionRun.id).label("id"))
        .group_by(IngestionRun.data_type)
        .subquery()
    )
    run_rows = list(
        session.scalars(
            select(IngestionRun)
            .join(latest_ids, IngestionRun.id == latest_ids.c.id)
            .order_by(IngestionRun.started_at_ms.desc())
        )
    )
    runs = [
        IngestionStatus(
            data_type=row.data_type,
            status=row.status,
            status_label=RUN_LABELS.get(row.status, row.status),
            completed_at=_format_timestamp(row.completed_at_ms or row.started_at_ms),
            fetched=row.records_fetched,
            written=row.records_written,
            error=row.error_message or "—",
        )
        for row in run_rows
    ]
    return DataStatusPage(
        sources=sources,
        runs=runs,
        total_rows=sum(row.row_count for row in sources),
        completed_runs=sum(row.status == "completed" for row in runs),
        failed_runs=sum(row.status == "failed" for row in runs),
    )


def _format_timestamp(value: int | None) -> str:
    if value is None:
        return "—"
    return datetime.fromtimestamp(value / 1000, tz=KST).strftime("%Y.%m.%d %H:%M")
