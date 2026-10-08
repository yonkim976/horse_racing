"""Argument parser for the horse-racing command line."""

import argparse

from horse_racing.cli._common import valid_race_date
from horse_racing.services.entry_sheet import MEET_METADATA


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="horse-racing")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("db-info", help="Show database connection information")
    entry_sheet_parser = subparsers.add_parser(
        "collect-entry-sheet",
        help="Collect a KRA entry sheet from data.go.kr",
    )
    entry_sheet_parser.add_argument("--date", required=True, type=valid_race_date)
    entry_sheet_parser.add_argument(
        "--meet", required=True, type=int, choices=sorted(MEET_METADATA)
    )
    entry_sheet_parser.add_argument("--page-size", type=int, default=100)
    race_day_parser = subparsers.add_parser(
        "collect-race-day",
        help="Collect plans, entries, results, details, and final dividends",
    )
    race_day_parser.add_argument("--date", required=True, type=valid_race_date)
    race_day_parser.add_argument("--meet", required=True, type=int, choices=sorted(MEET_METADATA))
    race_day_parser.add_argument("--page-size", type=int, default=1000)
    schedule_parser = subparsers.add_parser(
        "collect-schedule",
        help="Collect race plans, entry sheets, and official gate numbers",
    )
    schedule_parser.add_argument("--dates", required=True, nargs="+", type=valid_race_date)
    schedule_parser.add_argument(
        "--meets", nargs="+", type=int, choices=sorted(MEET_METADATA), default=sorted(MEET_METADATA)
    )
    schedule_parser.add_argument("--page-size", type=int, default=1000)
    gate_parser = subparsers.add_parser(
        "collect-gate-numbers",
        help="Collect and validate official KRA API78 gate numbers",
    )
    gate_parser.add_argument("--date", required=True, type=valid_race_date)
    gate_parser.add_argument("--meet", required=True, type=int, choices=sorted(MEET_METADATA))
    gate_parser.add_argument("--page-size", type=int, default=1000)
    gate_backfill_parser = subparsers.add_parser(
        "backfill-gates",
        help="Collect API78 gate numbers for stored entries missing them",
    )
    gate_backfill_parser.add_argument("--start", required=True, type=valid_race_date)
    gate_backfill_parser.add_argument("--end", required=True, type=valid_race_date)
    gate_backfill_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    gate_backfill_parser.add_argument("--page-size", type=int, default=1000)
    backfill_parser = subparsers.add_parser(
        "backfill-results",
        help="Discover and collect every completed race day in a date range",
    )
    backfill_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    backfill_parser.add_argument("--page-size", type=int, default=1000)
    backfill_parser.add_argument("--skip-dividends", action="store_true")
    dividend_parser = subparsers.add_parser(
        "backfill-dividends",
        help="Collect final dividends for stored result days missing them",
    )
    dividend_parser.add_argument("--start", required=True, type=valid_race_date)
    dividend_parser.add_argument("--end", required=True, type=valid_race_date)
    dividend_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    dividend_parser.add_argument("--page-size", type=int, default=20_000)
    section_parser = subparsers.add_parser(
        "collect-race-sections",
        help="Collect per-horse section records for a completed race day",
    )
    section_parser.add_argument("--date", required=True, type=valid_race_date)
    section_parser.add_argument("--meet", required=True, type=int, choices=sorted(MEET_METADATA))
    section_parser.add_argument("--page-size", type=int, default=1000)
    backfill_sections_parser = subparsers.add_parser(
        "backfill-sections",
        help="Collect section records for stored result days missing them",
    )
    backfill_sections_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_sections_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_sections_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    backfill_sections_parser.add_argument("--page-size", type=int, default=1000)
    passing_parser = subparsers.add_parser(
        "collect-race-passing",
        help="Collect official race-level passing groups and track tempo",
    )
    passing_parser.add_argument("--date", required=True, type=valid_race_date)
    passing_parser.add_argument(
        "--meet", required=True, type=int, choices=sorted(MEET_METADATA)
    )
    passing_parser.add_argument("--page-size", type=int, default=1000)
    backfill_passing_parser = subparsers.add_parser(
        "backfill-race-passing",
        help="Collect official passing groups for stored race days missing them",
    )
    backfill_passing_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_passing_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_passing_parser.add_argument(
        "--meets",
        nargs="+",
        type=int,
        choices=sorted(MEET_METADATA),
        default=sorted(MEET_METADATA),
    )
    backfill_passing_parser.add_argument("--page-size", type=int, default=1000)
    backfill_passing_years_parser = subparsers.add_parser(
        "backfill-race-passing-years",
        help="Efficiently backfill official passing groups by year",
    )
    backfill_passing_years_parser.add_argument("--start-year", required=True, type=int)
    backfill_passing_years_parser.add_argument("--end-year", required=True, type=int)
    backfill_passing_years_parser.add_argument(
        "--meets",
        nargs="+",
        type=int,
        choices=sorted(MEET_METADATA),
        default=sorted(MEET_METADATA),
    )
    backfill_passing_years_parser.add_argument("--page-size", type=int, default=1000)
    ratings_parser = subparsers.add_parser(
        "collect-ratings",
        help="Collect current horse rating snapshots",
    )
    ratings_parser.add_argument(
        "--date",
        type=valid_race_date,
        help="스냅샷 저장용 날짜 YYYYMMDD (기본: 오늘)",
    )
    ratings_parser.add_argument("--page-size", type=int, default=1000)
    weights_parser = subparsers.add_parser(
        "collect-weights",
        help="Collect entry horse body weights for a race day",
    )
    weights_parser.add_argument("--date", required=True, type=valid_race_date)
    weights_parser.add_argument("--meet", required=True, type=int, choices=sorted(MEET_METADATA))
    weights_parser.add_argument("--page-size", type=int, default=1000)
    training_parser = subparsers.add_parser(
        "collect-training",
        help="Collect daily training records for a date",
    )
    training_parser.add_argument("--date", required=True, type=valid_race_date)
    training_parser.add_argument("--meet", required=True, type=int, choices=sorted(MEET_METADATA))
    training_parser.add_argument("--page-size", type=int, default=1000)
    medical_parser = subparsers.add_parser(
        "collect-medical",
        help="Collect horse clinic records for a date",
    )
    medical_parser.add_argument("--date", required=True, type=valid_race_date)
    medical_parser.add_argument("--meet", required=True, type=int, choices=sorted(MEET_METADATA))
    medical_parser.add_argument("--page-size", type=int, default=1000)
    profiles_parser = subparsers.add_parser(
        "collect-horse-profiles",
        help="Collect horse detail profiles (pedigree, grade, career stats)",
    )
    profiles_parser.add_argument(
        "--meets",
        nargs="+",
        type=int,
        choices=(1, 2, 3),
        default=[1, 2, 3],
    )
    profiles_parser.add_argument(
        "--date",
        type=valid_race_date,
        help="스냅샷 저장용 날짜 YYYYMMDD (기본: 오늘)",
    )
    profiles_parser.add_argument("--page-size", type=int, default=1000)
    profiles_parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="현역 대신 비현역(act_gubun=n) 목록을 수집",
    )
    backfill_weights_parser = subparsers.add_parser(
        "backfill-weights",
        help="Collect horse weights over a date range",
    )
    backfill_weights_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_weights_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_weights_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    backfill_weights_parser.add_argument("--page-size", type=int, default=1000)
    backfill_training_parser = subparsers.add_parser(
        "backfill-training",
        help="Collect daily training over a date range",
    )
    backfill_training_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_training_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_training_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    backfill_training_parser.add_argument("--page-size", type=int, default=1000)
    backfill_medical_parser = subparsers.add_parser(
        "backfill-medical",
        help="Collect clinic records over a date range",
    )
    backfill_medical_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_medical_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_medical_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    backfill_medical_parser.add_argument("--page-size", type=int, default=1000)
    jockey_chg_parser = subparsers.add_parser(
        "collect-jockey-changes",
        help="Collect jockey change records for a race day",
    )
    jockey_chg_parser.add_argument("--date", required=True, type=valid_race_date)
    jockey_chg_parser.add_argument("--meet", required=True, type=int, choices=sorted(MEET_METADATA))
    jockey_chg_parser.add_argument("--page-size", type=int, default=1000)
    scratch_parser = subparsers.add_parser(
        "collect-scratches",
        help="Collect race scratch (cancel) records for a race day",
    )
    scratch_parser.add_argument("--date", required=True, type=valid_race_date)
    scratch_parser.add_argument("--meet", required=True, type=int, choices=sorted(MEET_METADATA))
    scratch_parser.add_argument("--page-size", type=int, default=1000)
    equipment_parser = subparsers.add_parser(
        "collect-equipment",
        help="Collect equipment and bleeding records for a race day",
    )
    equipment_parser.add_argument("--date", required=True, type=valid_race_date)
    equipment_parser.add_argument("--meet", required=True, type=int, choices=sorted(MEET_METADATA))
    equipment_parser.add_argument("--page-size", type=int, default=1000)
    grade_parser = subparsers.add_parser(
        "collect-grade-changes",
        help="Collect horse grade change history snapshots",
    )
    grade_parser.add_argument(
        "--meets",
        nargs="*",
        type=int,
        choices=(1, 2, 3),
        help="경마장 필터 (생략 시 전체)",
    )
    grade_parser.add_argument(
        "--date",
        type=valid_race_date,
        help="스냅샷 저장용 날짜 YYYYMMDD (기본: 오늘)",
    )
    grade_parser.add_argument("--page-size", type=int, default=1000)
    start_training_parser = subparsers.add_parser(
        "collect-start-training",
        help="Collect start-gate training records for a date",
    )
    start_training_parser.add_argument("--date", required=True, type=valid_race_date)
    start_training_parser.add_argument(
        "--meet", required=True, type=int, choices=sorted(MEET_METADATA)
    )
    start_training_parser.add_argument("--page-size", type=int, default=1000)
    steward_parser = subparsers.add_parser(
        "collect-steward-reports",
        help="Collect steward (judge) reports for a race day",
    )
    steward_parser.add_argument("--date", required=True, type=valid_race_date)
    steward_parser.add_argument("--meet", required=True, type=int, choices=sorted(MEET_METADATA))
    steward_parser.add_argument("--page-size", type=int, default=1000)
    backfill_jockey_chg_parser = subparsers.add_parser(
        "backfill-jockey-changes",
        help="Collect jockey changes over a date range",
    )
    backfill_jockey_chg_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_jockey_chg_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_jockey_chg_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    backfill_jockey_chg_parser.add_argument("--page-size", type=int, default=1000)
    backfill_scratch_parser = subparsers.add_parser(
        "backfill-scratches",
        help="Collect race scratches over a date range",
    )
    backfill_scratch_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_scratch_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_scratch_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    backfill_scratch_parser.add_argument("--page-size", type=int, default=1000)
    backfill_equipment_parser = subparsers.add_parser(
        "backfill-equipment",
        help="Collect equipment/bleeding over a date range",
    )
    backfill_equipment_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_equipment_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_equipment_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    backfill_equipment_parser.add_argument("--page-size", type=int, default=1000)
    backfill_start_training_parser = subparsers.add_parser(
        "backfill-start-training",
        help="Collect start-gate training over a date range",
    )
    backfill_start_training_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_start_training_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_start_training_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    backfill_start_training_parser.add_argument("--page-size", type=int, default=1000)
    backfill_steward_parser = subparsers.add_parser(
        "backfill-steward-reports",
        help="Collect steward reports over a date range",
    )
    backfill_steward_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_steward_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_steward_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    backfill_steward_parser.add_argument("--page-size", type=int, default=1000)
    running_trials_parser = subparsers.add_parser(
        "collect-running-trials",
        help="Collect KRA dacom23 running-trial reports over a date range",
    )
    running_trials_parser.add_argument("--start", required=True, type=valid_race_date)
    running_trials_parser.add_argument("--end", required=True, type=valid_race_date)
    running_trials_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    text_archive_parser = subparsers.add_parser(
        "download-text-archive",
        help="Download KRA Text archive files with a resumable manifest",
    )
    text_archive_parser.add_argument(
        "--file-type",
        required=True,
        help="자료실 fileType (예: dacom11, dacom01, db7)",
    )
    text_archive_parser.add_argument(
        "--code-name",
        help="자료실 화면명. 알려진 fileType은 생략 가능",
    )
    text_archive_parser.add_argument(
        "--start", type=valid_race_date, help="파일 날짜 시작 YYYYMMDD"
    )
    text_archive_parser.add_argument("--end", type=valid_race_date, help="파일 날짜 종료 YYYYMMDD")
    text_archive_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    text_archive_parser.add_argument("--max-pages", type=int, default=500)
    text_archive_parser.add_argument(
        "--max-files",
        type=int,
        help="검증용 최대 파일 수. 생략하면 기간 내 전체",
    )
    text_archive_parser.add_argument(
        "--delay-ms",
        type=int,
        default=100,
        help="파일 요청 사이 대기시간(ms)",
    )
    text_ingest_parser = subparsers.add_parser(
        "ingest-text-results",
        help="Validate or ingest downloaded dacom11 race results",
    )
    text_ingest_parser.add_argument("--start", required=True, type=valid_race_date)
    text_ingest_parser.add_argument("--end", required=True, type=valid_race_date)
    text_ingest_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    text_ingest_parser.add_argument(
        "--validate-only",
        action="store_true",
        help="기존 API 경주와 대조만 하고 신규 경주는 저장하지 않음",
    )
    text_ingest_parser.add_argument(
        "--allow-synthetic-horses",
        action="store_true",
        help="공식 마번 미해결 말에 text: 임시 ID 생성을 허용",
    )
    dashboard_parser = subparsers.add_parser(
        "serve-dashboard",
        help="Run the local race schedule and result dashboard",
    )
    dashboard_parser.add_argument("--host", default="127.0.0.1")
    dashboard_parser.add_argument("--port", type=int, default=8000)
    dashboard_parser.add_argument("--reload", action="store_true")
    subparsers.add_parser(
        "repair-entry-links",
        help="Repair missing trainer and owner links from stable horse history",
    )
    subparsers.add_parser(
        "repair-planned-weather",
        help="Backfill pre-race weather fields from stored racePlan source documents",
    )
    sync_parser = subparsers.add_parser(
        "sync-daily",
        help="Collect upcoming schedules and recent results for local refresh",
    )
    sync_parser.add_argument(
        "--mode",
        choices=("schedule", "results", "all"),
        default="all",
        help="schedule=upcoming cards, results=recent results, all=both",
    )
    sync_parser.add_argument(
        "--as-of",
        type=valid_race_date,
        help="기준일 YYYYMMDD (기본값: 오늘 로컬 날짜)",
    )
    sync_parser.add_argument(
        "--meets",
        nargs="+",
        type=int,
        choices=sorted(MEET_METADATA),
        default=sorted(MEET_METADATA),
    )
    sync_parser.add_argument(
        "--schedule-days",
        type=int,
        default=3,
        help="오늘부터 앞으로 일정/출전표를 받을 일수",
    )
    sync_parser.add_argument(
        "--result-lookback-days",
        type=int,
        default=1,
        help="오늘 포함 과거 며칠의 결과를 재확인할지",
    )
    sync_parser.add_argument("--page-size", type=int, default=1000)
    sync_parser.add_argument("--skip-dividends", action="store_true")
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API 호출 없이 동기화 대상만 출력",
    )
    latest_parser = subparsers.add_parser(
        "sync-latest",
        help="Collect every current operational source in one refresh",
    )
    latest_parser.add_argument(
        "--as-of",
        type=valid_race_date,
        help="기준일 YYYYMMDD (기본값: 오늘 로컬 날짜)",
    )
    latest_parser.add_argument(
        "--meets",
        nargs="+",
        type=int,
        choices=sorted(MEET_METADATA),
        default=sorted(MEET_METADATA),
    )
    latest_parser.add_argument("--schedule-days", type=int, default=7)
    latest_parser.add_argument("--recent-lookback-days", type=int, default=7)
    latest_parser.add_argument("--history-lookback-days", type=int, default=14)
    latest_parser.add_argument("--trial-lookback-days", type=int, default=14)
    latest_parser.add_argument("--page-size", type=int, default=1000)
    latest_parser.add_argument("--skip-dividends", action="store_true")
    latest_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="외부 호출 없이 전체 갱신 계획만 출력",
    )
    build_dataset_parser = subparsers.add_parser(
        "build-dataset",
        help="Build a leakage-free training dataset as Parquet with a manifest",
    )
    build_dataset_parser.add_argument("--version", required=True, help="데이터셋 버전 (예: v1)")
    build_dataset_parser.add_argument(
        "--as-of",
        default="start_minus_30m",
        choices=["start_minus_30m", "day_before_18"],
        help="예측 시점 정책",
    )
    build_dataset_parser.add_argument("--start", type=valid_race_date, default=None)
    build_dataset_parser.add_argument("--end", type=valid_race_date, default=None)
    build_dataset_parser.add_argument(
        "--meets",
        nargs="+",
        type=int,
        choices=(1, 2, 3),
        default=None,
        help="학습 대상 경마장 코드(예: 제주 전용은 --meets 2)",
    )
    build_dataset_parser.add_argument(
        "--output-dir",
        default="data/datasets",
        help="출력 디렉터리 (기본: data/datasets)",
    )
    build_dataset_parser.add_argument(
        "--no-features",
        action="store_true",
        help="feature 계산 없이 라벨·기본 컬럼만 생성",
    )
    build_dataset_parser.add_argument(
        "--feature-set",
        choices=[
            "rich",
            "history_core",
            "racefit_rich",
            "racefit_history",
            "racefit_v2_rich",
            "racefit_v2_history",
            "racefit_canonical_rich",
            "racefit_canonical_history",
        ],
        default="rich",
        help=(
            "rich=2025+ 전체 원천, history_core=장기 백필 공통 원천, racefit_*=에너지·잠재상태 포함"
        ),
    )
    catalog_parser = subparsers.add_parser(
        "write-feature-catalog",
        help="Generate docs/FEATURE_CATALOG.md from the feature registry",
    )
    catalog_parser.add_argument("--output", default="docs/FEATURE_CATALOG.md")
    baselines_parser = subparsers.add_parser(
        "run-baselines",
        help="M3 기준 모델 B0~B3 실행·평가·기록 (test는 기본 제외)",
    )
    baselines_parser.add_argument("--version", required=True, help="데이터셋 버전 (예: v1_full)")
    baselines_parser.add_argument(
        "--as-of",
        default="start_minus_30m",
        choices=["start_minus_30m", "day_before_18"],
        help="예측 시점 정책",
    )
    baselines_parser.add_argument(
        "--dataset-dir",
        default="data/datasets",
        help="데이터셋 루트 (기본: data/datasets)",
    )
    baselines_parser.add_argument(
        "--include-test",
        action="store_true",
        help="test split도 평가 (G1 판정 1회 원칙 — 평상시 금지)",
    )
    train_model_parser = subparsers.add_parser(
        "train-model",
        help="M4 LightGBM win/top2/top3 모델 학습·보정·valid 평가",
    )
    train_model_parser.add_argument("--version", required=True, help="데이터셋 버전")
    train_model_parser.add_argument(
        "--as-of",
        default="start_minus_30m",
        choices=["start_minus_30m", "day_before_18"],
        help="예측 시점 정책",
    )
    train_model_parser.add_argument("--dataset-dir", default="data/datasets")
    train_model_parser.add_argument("--output-dir", default="data/experiments/models")
    train_model_parser.add_argument("--report-dir", default="data/experiments/reports")
    train_model_parser.add_argument("--seed", type=int, default=42)
    train_model_parser.add_argument(
        "--calibration",
        choices=["auto", "raw", "sigmoid", "isotonic"],
        default="auto",
        help="확률 보정법 (auto는 valid log loss로 선택)",
    )
    train_model_parser.add_argument(
        "--profile",
        choices=[
            "legacy_all",
            "ability_v2",
            "ability_v2_strict",
            "ability_v2_core",
            "ability_v2_gate",
            "racefit_v1_core",
            "racefit_v4_gate_pace",
            "racefit_v5_sand",
            "racefit_v5_sand_event",
            "racefit_v6_remediation",
            "racefit_v5_sand_state",
            "racefit_v5_sand_gate_pace",
            "racefit_v2_core",
            "racefit_v2_no_live",
        ],
        default="legacy_all",
        help="학습 feature 프로필 (ability_v2는 배당·레이팅 제외)",
    )
    walk_forward_parser = subparsers.add_parser(
        "run-walk-forward",
        help="과거 연도별 expanding-window LightGBM 평가",
    )
    walk_forward_parser.add_argument("--version", required=True)
    walk_forward_parser.add_argument(
        "--as-of",
        default="day_before_18",
        choices=["start_minus_30m", "day_before_18"],
    )
    walk_forward_parser.add_argument("--dataset-dir", default="data/datasets")
    walk_forward_parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=[2022, 2023, 2024, 2025],
    )
    walk_forward_parser.add_argument("--output-dir", default="data/experiments/walk_forward")
    walk_forward_parser.add_argument("--report-dir", default="data/experiments/reports")
    walk_forward_parser.add_argument("--seed", type=int, default=42)
    walk_forward_parser.add_argument(
        "--calibration",
        choices=["raw", "sigmoid", "isotonic"],
        default="sigmoid",
    )
    walk_forward_parser.add_argument(
        "--profile",
        choices=[
            "legacy_all",
            "ability_v2",
            "ability_v2_strict",
            "ability_v2_core",
            "ability_v2_gate",
            "racefit_v1_core",
            "racefit_v4_gate_pace",
            "racefit_v5_sand",
            "racefit_v5_sand_event",
            "racefit_v6_remediation",
            "racefit_v5_sand_state",
            "racefit_v5_sand_gate_pace",
            "racefit_v2_core",
            "racefit_v2_no_live",
        ],
        default="ability_v2_core",
    )
    walk_forward_parser.add_argument(
        "--model",
        choices=[
            "binary",
            "ranking",
            "full_ranking",
            "top5_ranking",
            "racefit",
            "pace",
            "pace_ranking",
            "segment",
        ],
        default="binary",
        help=(
            "binary=승리 분류, ranking=경주 단위 LambdaRank, "
            "full_ranking=순서 top3 Plackett-Luce, "
            "top5_ranking=1~5위 순위분포 Plackett-Luce, "
            "racefit=에너지·컨디션·페이스 시나리오 혼합, "
            "pace=2단계 전개 이진모델, pace_ranking=2단계 전개 순위모델, "
            "segment=제주·장거리 보정"
        ),
    )
    walk_forward_parser.add_argument(
        "--relevance-mode",
        choices=["finish_order", "margin"],
        default="finish_order",
        help="Top5 LambdaRank 정답: 고정 착순점수 또는 착차 기반 점수",
    )
    walk_forward_parser.add_argument(
        "--margin-performance",
        action="store_true",
        help="Top5 순위모델에 연속 착차 성능 회귀축을 보정구간 선택 비중으로 결합",
    )
    ranking_parser = subparsers.add_parser(
        "train-ranking",
        help="LightGBM LambdaRank 학습·softmax 보정·valid 평가",
    )
    ranking_parser.add_argument("--version", required=True)
    ranking_parser.add_argument(
        "--as-of",
        default="day_before_18",
        choices=["start_minus_30m", "day_before_18"],
    )
    ranking_parser.add_argument("--dataset-dir", default="data/datasets")
    ranking_parser.add_argument("--output-dir", default="data/experiments/models")
    ranking_parser.add_argument("--report-dir", default="data/experiments/reports")
    ranking_parser.add_argument("--seed", type=int, default=42)
    ranking_parser.add_argument(
        "--calibration-objective",
        choices=["winner", "full_top3", "full_top5"],
        default="full_top3",
        help=("winner=기존 단승 softmax, full_top3=순서 top3, full_top5=순서 top5 Plackett-Luce"),
    )
    ranking_parser.add_argument(
        "--relevance-depth",
        choices=[3, 5],
        type=int,
        default=3,
        help="LambdaRank relevance 깊이 (Top5 모델은 5)",
    )
    ranking_parser.add_argument(
        "--relevance-mode",
        choices=["finish_order", "margin"],
        default="finish_order",
        help="Top5 LambdaRank 정답: 고정 착순점수 또는 착차 기반 점수",
    )
    ranking_parser.add_argument(
        "--margin-performance",
        action="store_true",
        help="Top5 순위모델에 연속 착차 성능 회귀축을 보정구간 선택 비중으로 결합",
    )
    ranking_parser.add_argument(
        "--regularization",
        choices=["default", "jeju_moderate", "jeju_strong", "jeju_jockey_soft"],
        default="default",
        help="표본이 작은 제주 전용 모델의 복잡도 규제 사전설정",
    )
    ranking_parser.add_argument(
        "--profile",
        choices=[
            "legacy_all",
            "ability_v2",
            "ability_v2_strict",
            "ability_v2_core",
            "ability_v2_gate",
            "racefit_v1_core",
            "racefit_v4_gate_pace",
            "racefit_v5_sand",
            "racefit_v5_sand_event",
            "racefit_jeju_v2",
            "racefit_v6_remediation",
            "racefit_v5_sand_state",
            "racefit_v5_sand_gate_pace",
            "racefit_v2_core",
            "racefit_v2_no_live",
        ],
        default="ability_v2_core",
    )
    racefit_parser = subparsers.add_parser(
        "train-racefit",
        help="RaceFit V1 에너지·컨디션·페이스 시나리오 혼합 순위모델",
    )
    racefit_parser.add_argument("--version", required=True)
    racefit_parser.add_argument(
        "--as-of",
        default="day_before_18",
        choices=["start_minus_30m", "day_before_18"],
    )
    racefit_parser.add_argument("--dataset-dir", default="data/datasets")
    racefit_parser.add_argument("--output-dir", default="data/experiments/models")
    racefit_parser.add_argument("--report-dir", default="data/experiments/reports")
    racefit_parser.add_argument("--seed", type=int, default=42)
    racefit_parser.add_argument(
        "--profile",
        choices=[
            "legacy_all",
            "ability_v2",
            "ability_v2_strict",
            "ability_v2_core",
            "ability_v2_gate",
            "racefit_v1_core",
            "racefit_v4_gate_pace",
            "racefit_v5_sand",
            "racefit_v5_sand_event",
            "racefit_v6_remediation",
            "racefit_v5_sand_state",
            "racefit_v5_sand_gate_pace",
            "racefit_v2_core",
            "racefit_v2_no_live",
        ],
        default="ability_v2_core",
    )
    catboost_parser = subparsers.add_parser(
        "train-catboost",
        help="M4 CatBoost win/top2/top3 비교 모델 학습·보정·valid 평가",
    )
    catboost_parser.add_argument("--version", required=True, help="데이터셋 버전")
    catboost_parser.add_argument(
        "--as-of",
        default="start_minus_30m",
        choices=["start_minus_30m", "day_before_18"],
    )
    catboost_parser.add_argument("--dataset-dir", default="data/datasets")
    catboost_parser.add_argument("--output-dir", default="data/experiments/models")
    catboost_parser.add_argument("--report-dir", default="data/experiments/reports")
    catboost_parser.add_argument("--seed", type=int, default=42)
    catboost_parser.add_argument(
        "--calibration",
        choices=["auto", "raw", "sigmoid", "isotonic"],
        default="auto",
    )
    catboost_parser.add_argument(
        "--profile",
        choices=[
            "legacy_all",
            "ability_v2",
            "ability_v2_strict",
            "ability_v2_core",
            "ability_v2_gate",
            "racefit_v1_core",
            "racefit_v4_gate_pace",
            "racefit_v5_sand",
            "racefit_v5_sand_event",
            "racefit_v6_remediation",
            "racefit_v5_sand_state",
            "racefit_v5_sand_gate_pace",
            "racefit_v2_core",
            "racefit_v2_no_live",
        ],
        default="legacy_all",
        help="학습 feature 프로필 (ability_v2는 배당·레이팅 제외)",
    )
    ablation_parser = subparsers.add_parser(
        "run-ablation",
        help="LightGBM win 모델의 feature-group 제거 실험 (test 미사용)",
    )
    ablation_parser.add_argument("--version", required=True, help="데이터셋 버전")
    ablation_parser.add_argument(
        "--as-of",
        default="start_minus_30m",
        choices=["start_minus_30m", "day_before_18"],
    )
    ablation_parser.add_argument("--dataset-dir", default="data/datasets")
    ablation_parser.add_argument("--report-dir", default="data/experiments/reports")
    ablation_parser.add_argument("--seed", type=int, default=42)
    ablation_parser.add_argument(
        "--profile",
        choices=[
            "legacy_all",
            "ability_v2",
            "ability_v2_strict",
            "ability_v2_core",
            "ability_v2_gate",
            "racefit_v1_core",
            "racefit_v4_gate_pace",
            "racefit_v5_sand",
            "racefit_v5_sand_event",
            "racefit_v6_remediation",
            "racefit_v5_sand_state",
            "racefit_v5_sand_gate_pace",
            "racefit_v2_core",
            "racefit_v2_no_live",
        ],
        default="legacy_all",
    )
    ensemble_parser = subparsers.add_parser(
        "build-ensemble",
        help="모델 run들의 확률 평균 ensemble 생성",
    )
    ensemble_parser.add_argument("run_ids", nargs="+", metavar="RUN_ID")
    ensemble_parser.add_argument("--dataset-dir", default="data/datasets")
    ensemble_parser.add_argument("--output-dir", default="data/experiments/models")
    ensemble_parser.add_argument("--report-dir", default="data/experiments/reports")
    ensemble_parser.add_argument(
        "--allow-cross-dataset",
        action="store_true",
        help="첫 run의 feature frame에서 더 이른 as-of 모델을 함께 결합",
    )
    ensemble_parser.add_argument("--win-weights", nargs="+", type=float)
    ensemble_parser.add_argument("--top2-weights", nargs="+", type=float)
    ensemble_parser.add_argument("--top3-weights", nargs="+", type=float)
    ensemble_parser.add_argument("--top4-weights", nargs="+", type=float)
    ensemble_parser.add_argument("--top5-weights", nargs="+", type=float)
    ensemble_parser.add_argument("--reference-version")
    ensemble_parser.add_argument(
        "--reference-as-of",
        choices=["start_minus_30m", "day_before_18"],
    )
    g1_parser = subparsers.add_parser(
        "run-g1-gate",
        help="고정 후보로 holdout test를 한 번 평가하고 Gate G1 판정",
    )
    g1_parser.add_argument("--run-id", required=True, help="고정된 M4 후보 run_id")
    g1_parser.add_argument("--dataset-dir", default="data/datasets")
    g1_parser.add_argument("--report-dir", default="data/experiments/reports")
    g1_parser.add_argument(
        "--confirm-test",
        action="store_true",
        help="holdout test 1회 사용을 명시적으로 확인",
    )
    g2_parser = subparsers.add_parser(
        "run-g2-gate",
        help="G1 PASS 후보를 최종 단승배당과 1회 비교하고 Gate G2 판정",
    )
    g2_parser.add_argument("--run-id", required=True, help="G1을 통과한 고정 M4 후보 run_id")
    g2_parser.add_argument("--dataset-dir", default="data/datasets")
    g2_parser.add_argument("--report-dir", default="data/experiments/reports")
    g2_parser.add_argument("--bootstrap-iterations", type=int, default=1_000)
    g2_parser.add_argument(
        "--confirm-test-market",
        action="store_true",
        help="holdout test의 최종배당 시장평가 1회 사용을 명시적으로 확인",
    )
    ordered_triple_parser = subparsers.add_parser(
        "run-ordered-triple-value",
        help="상위 N두의 Plackett-Luce 순서 3두 확률과 확정배당 EV를 valid에서 진단",
    )
    ordered_triple_parser.add_argument("--run-id", required=True)
    ordered_triple_parser.add_argument("--dataset-dir", default="data/datasets")
    ordered_triple_parser.add_argument("--report-dir", default="data/experiments/reports")
    ordered_triple_parser.add_argument("--top-n", type=int, default=4)
    ordered_triple_parser.add_argument(
        "--ev-thresholds",
        nargs="+",
        type=float,
        default=[0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.00],
    )
    ordered_triple_parser.add_argument("--bootstrap-iterations", type=int, default=1_000)
    publish_predictions_parser = subparsers.add_parser(
        "publish-predictions",
        help="경주 전 확률 파일을 append-only 공개 검증 원장에 고정",
    )
    publish_predictions_parser.add_argument("--run-id", required=True)
    publish_predictions_parser.add_argument("--predictions-file", required=True)
    publish_predictions_parser.add_argument(
        "--feature-cutoff",
        required=True,
        help="feature 기준시각(epoch ms 또는 ISO-8601; timezone 생략 시 Asia/Seoul)",
    )
    publish_predictions_parser.add_argument(
        "--mode",
        choices=["live", "historical"],
        default="live",
    )
    publish_predictions_parser.add_argument("--confirm-historical", action="store_true")
    publish_predictions_parser.add_argument("--notes")
    build_prediction_frame_parser = subparsers.add_parser(
        "build-prediction-frame",
        help="예정 경주의 label-free feature frame을 고정 model run 계약에 맞춰 생성",
    )
    build_prediction_frame_parser.add_argument("--run-id", required=True)
    build_prediction_frame_parser.add_argument("--date", required=True, type=valid_race_date)
    build_prediction_frame_parser.add_argument(
        "--mode",
        choices=["live", "historical"],
        default="live",
    )
    build_prediction_frame_parser.add_argument(
        "--race-id",
        dest="race_ids",
        action="append",
        type=int,
        help="특정 race_id만 생성 (반복 지정 가능)",
    )
    build_prediction_frame_parser.add_argument("--output-dir", default="data/predictions")
    predict_publish_parser = subparsers.add_parser(
        "predict-and-publish",
        help="예정 경주 feature 생성 → 고정 모델 추론 → 불변 예측 원장 발행",
    )
    predict_publish_parser.add_argument("--run-id", required=True)
    predict_publish_parser.add_argument("--date", required=True, type=valid_race_date)
    predict_publish_parser.add_argument(
        "--mode",
        choices=["live", "historical"],
        default="live",
    )
    predict_publish_parser.add_argument("--confirm-historical", action="store_true")
    predict_publish_parser.add_argument(
        "--race-id",
        dest="race_ids",
        action="append",
        type=int,
        help="특정 race_id만 발행 (반복 지정 가능)",
    )
    predict_publish_parser.add_argument("--output-dir", default="data/predictions")
    predict_publish_parser.add_argument(
        "--probability-calibration",
        help="OOF로 적합한 사후 확률 보정 artifact (.pkl)",
    )
    predict_publish_parser.add_argument("--notes")
    settle_predictions_parser = subparsers.add_parser(
        "settle-predictions",
        help="결과가 완료된 공개 예측을 1회 정산 (ID 생략 시 준비된 전체)",
    )
    settle_predictions_parser.add_argument("--public-id")
    list_predictions_parser = subparsers.add_parser(
        "list-predictions",
        help="공개 예측·정산 원장 목록",
    )
    list_predictions_parser.add_argument(
        "--mode",
        choices=["all", "live", "historical"],
        default="all",
    )
    verify_predictions_parser = subparsers.add_parser(
        "verify-predictions",
        help="저장된 예측 payload SHA-256 재검증",
    )
    verify_predictions_parser.add_argument("--public-id", required=True)
    evaluate_model_parser = subparsers.add_parser(
        "evaluate-model",
        help="저장된 M4 모델 평가 (기본 valid, test는 명시적으로만)",
    )
    evaluate_model_parser.add_argument("--run-id", required=True)
    evaluate_model_parser.add_argument("--dataset-dir", default="data/datasets")
    evaluate_model_parser.add_argument("--report-dir", default="data/experiments/reports")
    evaluate_model_parser.add_argument(
        "--include-test",
        action="store_true",
        help="test split 평가 (Gate G1 1회 판정 — 평상시 금지)",
    )
    list_runs_parser = subparsers.add_parser(
        "list-model-runs",
        help="List recorded model experiment runs",
    )
    list_runs_parser.add_argument(
        "--metric",
        help="지표 이름 (지정 시 해당 지표 내림차순 정렬)",
    )
    compare_runs_parser = subparsers.add_parser(
        "compare-runs",
        help="Compare metrics, hyperparameters, and feature hashes across runs",
    )
    compare_runs_parser.add_argument("run_ids", nargs="+", metavar="RUN_ID")
    return parser
