"""Data collection, backfill, repair, and daily sync commands."""

import sys
import time
from datetime import datetime, timedelta

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from horse_racing.cli._common import _print_aligned_table, _require_service_key, database_path
from horse_racing.collectors.kra_api import KraApiClient, KraApiError, KraApiRateLimitError
from horse_racing.collectors.kra_text import TEXT_FILE_TYPES, KraTextClient, KraTextError
from horse_racing.config import get_settings
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.session import SessionLocal
from horse_racing.services.dacom11 import ingest_dacom11_reports
from horse_racing.services.daily_sync import (
    compute_latest_sync_window,
    compute_sync_window,
    format_yyyymmdd,
)
from horse_racing.services.entry_sheet import MEET_METADATA, ingest_entry_sheet
from horse_racing.services.gate_entry_sheet import ingest_gate_numbers
from horse_racing.services.horse_history import (
    ingest_horse_profiles,
    ingest_medical,
    ingest_ratings,
    ingest_training,
    ingest_weights,
)
from horse_racing.services.race_day import (
    final_dividend_is_complete,
    ingest_final_dividends,
    ingest_race_day,
    ingest_race_schedule,
    race_day_is_complete,
    repair_missing_entry_people,
    repair_planned_weather,
    result_data_exists,
    result_day_is_stored,
)
from horse_racing.services.race_passing import (
    ingest_race_passing_summaries,
    passing_summary_data_exists,
    passing_summary_day_is_stored,
)
from horse_racing.services.race_sections import (
    ingest_race_sections,
    section_data_exists,
    section_day_is_stored,
)
from horse_racing.services.race_supplemental import (
    ingest_equipment,
    ingest_grade_changes,
    ingest_jockey_changes,
    ingest_scratches,
    ingest_start_training,
    ingest_steward_reports,
)
from horse_racing.services.running_trials import ingest_running_trials
from horse_racing.services.text_archive import download_text_archive


def db_info() -> int:
    settings = get_settings()
    engine = create_engine_for_url(settings.database_url)
    inspector = inspect(engine)

    path = database_path(settings.database_url)
    safe_url = make_url(settings.database_url).render_as_string(hide_password=True)
    print(f"database: {path or safe_url}")
    print(f"dialect: {engine.dialect.name}")
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            sqlite_version = connection.execute(text("select sqlite_version()")).scalar_one()
            journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
            foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
            print(f"sqlite_version: {sqlite_version}")
            print(f"journal_mode: {journal_mode}")
            print(f"foreign_keys: {'on' if foreign_keys else 'off'}")
        else:
            server_version = connection.execute(text("select version()")).scalar_one()
            current_schema = connection.execute(text("select current_schema()")).scalar_one()
            print(f"server_version: {server_version}")
            print(f"schema: {current_schema}")
    print(f"tables: {', '.join(sorted(inspector.get_table_names())) or '(none)'}")
    return 0


def collect_entry_sheet(race_date: str, meet: int, page_size: int) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print(
            "HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다. "
            ".env에 공공데이터포털 일반 인증키(Decoding)를 입력하세요.",
            file=sys.stderr,
        )
        return 2

    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_entry_sheet(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )

    meet_name = MEET_METADATA[meet][1]
    print(
        f"수집 완료: run={summary.run_id}, 경마장={meet_name}, 날짜={race_date}, "
        f"pages={summary.pages}, fetched={summary.records_fetched}, "
        f"written={summary.records_written}"
    )
    return 0


def collect_race_day(race_date: str, meet: int, page_size: int) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print(
            "HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다. "
            ".env에 공공데이터포털 일반 인증키(Decoding)를 입력하세요.",
            file=sys.stderr,
        )
        return 2

    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_race_day(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )

    meet_name = MEET_METADATA[meet][1]
    print(f"하루치 수집 완료: 경마장={meet_name}, 날짜={race_date}")
    for stage_name, stage in summary.stages.items():
        print(
            f"  {stage_name}: run={stage.run_id}, pages={stage.pages}, "
            f"fetched={stage.records_fetched}, written={stage.records_written}"
        )
    print(f"합계: fetched={summary.records_fetched}, written={summary.records_written}")
    return 0


def collect_schedule(race_dates: list[str], meets: list[int], page_size: int) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print(
            "HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.",
            file=sys.stderr,
        )
        return 2

    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        gate_failures = 0
        for race_date in race_dates:
            for meet in meets:
                meet_name = MEET_METADATA[meet][1]
                summary = ingest_race_schedule(
                    session,
                    client,
                    race_date=race_date,
                    meet=meet,
                    raw_data_dir=settings.raw_data_dir,
                    page_size=page_size,
                )
                fetched = summary.records_fetched
                if fetched:
                    print(
                        f"일정 수집: 날짜={race_date}, 경마장={meet_name}, "
                        f"fetched={fetched}",
                        flush=True,
                    )
                if summary.stages["entry_sheet"].records_written:
                    try:
                        gate_summary = ingest_gate_numbers(
                            session,
                            client,
                            race_date=race_date,
                            meet=meet,
                            raw_data_dir=settings.raw_data_dir,
                            page_size=page_size,
                        )
                    except (KraApiError, ValueError) as exc:
                        gate_failures += 1
                        print(
                            f"출발번호 확인 실패: 날짜={race_date}, 경마장={meet_name} / {exc}",
                            file=sys.stderr,
                            flush=True,
                        )
                    else:
                        print(
                            f"출발번호 확인: 날짜={race_date}, 경마장={meet_name}, "
                            f"fetched={gate_summary.records_fetched}, "
                            f"written={gate_summary.records_written}",
                            flush=True,
                        )
                session.expunge_all()
    if gate_failures:
        print(f"출발번호 확인 실패 {gate_failures}건", file=sys.stderr, flush=True)
        return 1
    return 0


def collect_gate_numbers(race_date: str, meet: int, page_size: int) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_gate_numbers(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )
    print(
        f"출발번호 수집 완료: {race_date} {MEET_METADATA[meet][1]} / "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def backfill_gate_numbers(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    if start > end:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")

    with SessionLocal() as session:
        targets = session.execute(
            text(
                """
                SELECT DISTINCT r.race_date_local, c.kra_meet_code
                FROM race_entries AS e
                JOIN races AS r ON r.id = e.race_id
                JOIN racecourses AS c ON c.id = r.racecourse_id
                WHERE e.gate_number IS NULL
                  AND r.race_date_local BETWEEN :start_date AND :end_date
                ORDER BY r.race_date_local, c.kra_meet_code
                """
            ),
            {"start_date": start.isoformat(), "end_date": end.isoformat()},
        ).all()
    targets = [(day, meet) for day, meet in targets if meet in meets]
    if not targets:
        print("출발번호 백필 대상이 없습니다.")
        return 0

    fetched_total = 0
    written_total = 0
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        for day, meet in targets:
            race_date = str(day).replace("-", "")
            summary = ingest_gate_numbers(
                session,
                client,
                race_date=race_date,
                meet=meet,
                raw_data_dir=settings.raw_data_dir,
                page_size=page_size,
            )
            fetched_total += summary.records_fetched
            written_total += summary.records_written
            print(
                f"출발번호 백필: {race_date} {MEET_METADATA[meet][1]} / "
                f"fetched={summary.records_fetched}, written={summary.records_written}",
                flush=True,
            )
            session.expunge_all()
    print(
        f"출발번호 백필 완료: 대상일={len(targets)}, "
        f"fetched={fetched_total}, written={written_total}"
    )
    return 0


def backfill_results(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
    include_dividends: bool,
) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print(
            "HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.",
            file=sys.stderr,
        )
        return 2

    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    if start > end:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")

    checked = 0
    found = 0
    collected = 0
    skipped = 0
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        current = start
        while current <= end:
            race_date = current.strftime("%Y%m%d")
            for meet in meets:
                checked += 1
                day_is_complete = (
                    race_day_is_complete(session, race_date=current, meet=meet)
                    if include_dividends
                    else result_day_is_stored(session, race_date=current, meet=meet)
                )
                if day_is_complete:
                    found += 1
                    skipped += 1
                    print(
                        f"기존 완료 데이터 유지: {race_date} {MEET_METADATA[meet][1]}",
                        flush=True,
                    )
                    continue
                if not result_data_exists(client, race_date=race_date, meet=meet):
                    if checked % 21 == 0:
                        print(
                            f"결과일 탐색 중: {race_date} / 확인 {checked}건",
                            flush=True,
                        )
                    continue

                found += 1
                summary = ingest_race_day(
                    session,
                    client,
                    race_date=race_date,
                    meet=meet,
                    raw_data_dir=settings.raw_data_dir,
                    page_size=page_size,
                    include_dividends=include_dividends,
                )
                collected += 1
                print(
                    f"결과 수집 완료: {race_date} {MEET_METADATA[meet][1]} / "
                    f"fetched={summary.records_fetched}",
                    flush=True,
                )
                session.expunge_all()
            current += timedelta(days=1)

    print(
        f"백필 완료: 기간={start_date}~{end_date}, 확인={checked}, "
        f"경주일={found}, 신규수집={collected}, 기존완료={skipped}",
        flush=True,
    )
    return 0


def backfill_dividends(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print(
            "HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.",
            file=sys.stderr,
        )
        return 2

    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    if start > end:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")

    stored_days = 0
    collected = 0
    skipped = 0
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        current = start
        while current <= end:
            race_date = current.strftime("%Y%m%d")
            for meet in meets:
                if not result_day_is_stored(session, race_date=current, meet=meet):
                    continue
                stored_days += 1
                if final_dividend_is_complete(session, race_date=current, meet=meet):
                    skipped += 1
                    continue
                while True:
                    try:
                        summary = ingest_final_dividends(
                            session,
                            client,
                            race_date=race_date,
                            meet=meet,
                            raw_data_dir=settings.raw_data_dir,
                            page_size=page_size,
                        )
                    except KraApiRateLimitError as exc:
                        print(f"확정배당 호출 제한 대기: {exc}", flush=True)
                        time.sleep(55)
                        continue
                    break
                collected += 1
                print(
                    f"확정배당 수집 완료: {race_date} {MEET_METADATA[meet][1]} / "
                    f"pages={summary.pages}, fetched={summary.records_fetched}, "
                    f"written={summary.records_written}",
                    flush=True,
                )
                session.expunge_all()
            current += timedelta(days=1)

    print(
        f"확정배당 백필 완료: 저장된 경주일={stored_days}, 신규수집={collected}, "
        f"기존완료={skipped}",
        flush=True,
    )
    return 0


def serve_dashboard(host: str, port: int, reload: bool) -> int:
    import uvicorn

    uvicorn.run(
        "horse_racing.web.app:app",
        host=host,
        port=port,
        reload=reload,
    )
    return 0


def repair_entry_links() -> int:
    with SessionLocal() as session:
        summary = repair_missing_entry_people(session)
    print(
        f"관계자 연결 복구: 확인={summary.examined}, 복구={summary.repaired}, "
        f"미해결={summary.unresolved}"
    )
    return 0 if summary.unresolved == 0 else 1


def repair_planned_weather_command() -> int:
    with SessionLocal() as session:
        summary = repair_planned_weather(session)
    print(
        f"계획 날씨 복구: 문서={summary.documents}, 경주 갱신={summary.races_updated}, "
        f"이미 일치={summary.races_unchanged}, 미매칭={summary.races_unmatched}"
    )
    return 0


def collect_ratings(snapshot_date: str | None, page_size: int) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    if snapshot_date is None:
        snapshot_date = datetime.now().strftime("%Y%m%d")

    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_ratings(
            session,
            client,
            snapshot_date=snapshot_date,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )
    print(
        f"레이팅 수집 완료: snapshot={snapshot_date}, "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def collect_weights(race_date: str, meet: int, page_size: int) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_weights(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )
    print(
        f"체중 수집 완료: {race_date} {MEET_METADATA[meet][1]} / "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def collect_training(training_date: str, meet: int, page_size: int) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_training(
            session,
            client,
            training_date=training_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )
    print(
        f"훈련 수집 완료: {training_date} {MEET_METADATA[meet][1]} / "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def collect_medical(clinic_date: str, meet: int, page_size: int) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_medical(
            session,
            client,
            clinic_date=clinic_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )
    print(
        f"진료 수집 완료: {clinic_date} {MEET_METADATA[meet][1]} / "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def collect_horse_profiles(
    meets: list[int],
    page_size: int,
    include_inactive: bool,
    snapshot_date: str | None,
) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    if snapshot_date is None:
        snapshot_date = datetime.now().strftime("%Y%m%d")

    total_written = 0
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        for meet in meets:
            summary = ingest_horse_profiles(
                session,
                client,
                meet=meet,
                snapshot_date=snapshot_date,
                raw_data_dir=settings.raw_data_dir,
                page_size=page_size,
                include_inactive=include_inactive,
            )
            total_written += summary.records_written
            scope = "전체(비현역 포함)" if include_inactive else "현역"
            print(
                f"말 상세 수집 완료: {MEET_METADATA[meet][1]} {scope} / "
                f"run={summary.run_id}, pages={summary.pages}, "
                f"fetched={summary.records_fetched}, written={summary.records_written}"
            )
            time.sleep(0.2)
    print(f"말 상세 수집 합계 written={total_written}")
    return 0


def backfill_weights(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    return _backfill_dated(
        label="체중",
        start_date=start_date,
        end_date=end_date,
        meets=meets,
        page_size=page_size,
        runner=lambda session, client, day, meet, raw_dir, size: ingest_weights(
            session,
            client,
            race_date=day,
            meet=meet,
            raw_data_dir=raw_dir,
            page_size=size,
        ),
    )


def backfill_training(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    return _backfill_dated(
        label="훈련",
        start_date=start_date,
        end_date=end_date,
        meets=meets,
        page_size=page_size,
        runner=lambda session, client, day, meet, raw_dir, size: ingest_training(
            session,
            client,
            training_date=day,
            meet=meet,
            raw_data_dir=raw_dir,
            page_size=size,
        ),
    )


def backfill_medical(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    return _backfill_dated(
        label="진료",
        start_date=start_date,
        end_date=end_date,
        meets=meets,
        page_size=page_size,
        runner=lambda session, client, day, meet, raw_dir, size: ingest_medical(
            session,
            client,
            clinic_date=day,
            meet=meet,
            raw_data_dir=raw_dir,
            page_size=size,
        ),
    )


def collect_jockey_changes(race_date: str, meet: int, page_size: int) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_jockey_changes(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )
    print(
        f"기수변경 수집 완료: {race_date} {MEET_METADATA[meet][1]} / "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def collect_scratches(race_date: str, meet: int, page_size: int) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_scratches(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )
    print(
        f"출전취소 수집 완료: {race_date} {MEET_METADATA[meet][1]} / "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def collect_equipment(race_date: str, meet: int, page_size: int) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_equipment(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )
    print(
        f"장구·폐출혈 수집 완료: {race_date} {MEET_METADATA[meet][1]} / "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def collect_grade_changes(
    meets: list[int] | None,
    page_size: int,
    snapshot_date: str | None,
) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    if snapshot_date is None:
        snapshot_date = datetime.now().strftime("%Y%m%d")

    meet_list: list[int | None]
    if meets:
        meet_list = list(meets)
    else:
        meet_list = [None]

    total_written = 0
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        for meet in meet_list:
            summary = ingest_grade_changes(
                session,
                client,
                snapshot_date=snapshot_date,
                meet=meet,
                raw_data_dir=settings.raw_data_dir,
                page_size=page_size,
            )
            total_written += summary.records_written
            scope = MEET_METADATA[meet][1] if meet is not None else "전체"
            print(
                f"등급변동 수집 완료: {scope} / "
                f"run={summary.run_id}, pages={summary.pages}, "
                f"fetched={summary.records_fetched}, written={summary.records_written}"
            )
            time.sleep(0.2)
    print(f"등급변동 수집 합계 written={total_written}")
    return 0


def collect_start_training(training_date: str, meet: int, page_size: int) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_start_training(
            session,
            client,
            training_date=training_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )
    print(
        f"출발훈련 수집 완료: {training_date} {MEET_METADATA[meet][1]} / "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def collect_steward_reports(race_date: str, meet: int, page_size: int) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_steward_reports(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )
    print(
        f"심판리포트 수집 완료: {race_date} {MEET_METADATA[meet][1]} / "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def collect_running_trials(start_date: str, end_date: str, meets: list[int]) -> int:
    settings = get_settings()
    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    with (
        KraTextClient(timeout_seconds=settings.http_timeout_seconds) as client,
        SessionLocal() as session,
    ):
        summary = ingest_running_trials(
            session,
            client,
            start_date=start,
            end_date=end,
            meets=meets,
            raw_data_dir=settings.raw_data_dir,
        )
    print(
        f"주행심사 수집 완료: 기간={start_date}~{end_date}, 경마장={meets}, "
        f"files={summary.files}, trials={summary.trials}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}, "
        f"말연결={summary.horses_linked}, 미연결={summary.horses_unresolved}"
    )
    return 0


def download_text_archive_command(
    file_type: str,
    code_name: str | None,
    start_date: str | None,
    end_date: str | None,
    meets: list[int],
    max_pages: int,
    max_files: int | None,
    delay_ms: int,
) -> int:
    settings = get_settings()
    resolved_code_name = code_name or TEXT_FILE_TYPES.get(file_type)
    if resolved_code_name is None:
        raise ValueError("알 수 없는 file-type입니다. --code-name을 함께 지정하세요.")
    if (start_date is None) != (end_date is None):
        raise ValueError("--start와 --end는 함께 지정하거나 모두 생략해야 합니다.")
    start = datetime.strptime(start_date, "%Y%m%d").date() if start_date else None
    end = datetime.strptime(end_date, "%Y%m%d").date() if end_date else None
    with (
        KraTextClient(timeout_seconds=settings.http_timeout_seconds) as client,
        SessionLocal() as session,
    ):
        summary = download_text_archive(
            session,
            client,
            file_type=file_type,
            code_name=resolved_code_name,
            meets=meets,
            raw_data_dir=settings.raw_data_dir,
            start_date=start,
            end_date=end,
            max_pages=max_pages,
            max_files=max_files,
            delay_seconds=delay_ms / 1000,
        )
    print(
        f"KRA Text 다운로드 완료: type={file_type}, run={summary.run_id}, "
        f"발견={summary.files_discovered}, 호출={summary.files_fetched}, "
        f"신규={summary.files_written}, 건너뜀={summary.files_skipped}, "
        f"bytes={summary.bytes_fetched:,}"
    )
    print(f"manifest: {summary.manifest_path}")
    return 0


def ingest_text_results_command(
    start_date: str,
    end_date: str,
    meets: list[int],
    *,
    validate_only: bool,
    allow_synthetic_horses: bool,
) -> int:
    settings = get_settings()
    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    with SessionLocal() as session:
        summary = ingest_dacom11_reports(
            session,
            raw_data_dir=settings.raw_data_dir,
            start_date=start,
            end_date=end,
            meets=meets,
            validate_only=validate_only,
            allow_synthetic_horses=allow_synthetic_horses,
        )
    mode = "검증" if validate_only else "적재"
    print(
        f"dacom11 {mode} 완료: run={summary.run_id}, files={summary.files}, "
        f"parsed_races={summary.races_parsed}, parsed_entries={summary.entries_parsed}"
    )
    print(
        f"신규 경주={summary.races_written}, 신규 출전={summary.entries_written}, "
        f"기존 경주={summary.overlap_races}, 대조 출전={summary.overlap_entries}, "
        f"메타 갱신={summary.races_updated}, 불일치={summary.overlap_mismatches}, "
        f"임시 말 ID={summary.synthetic_horses}"
    )
    if validate_only:
        print(
            "신규 경주 말 연결: "
            f"공식 연결={summary.resolved_horse_entries}, "
            f"미해결={summary.unresolved_horse_entries}, "
            f"동명이인 모호={summary.ambiguous_horse_entries}"
        )
    return 0 if summary.overlap_mismatches == 0 else 1


def backfill_jockey_changes(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    return _backfill_dated(
        label="기수변경",
        start_date=start_date,
        end_date=end_date,
        meets=meets,
        page_size=page_size,
        runner=lambda session, client, day, meet, raw_dir, size: ingest_jockey_changes(
            session,
            client,
            race_date=day,
            meet=meet,
            raw_data_dir=raw_dir,
            page_size=size,
        ),
        race_days_only=True,
    )


def backfill_scratches(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    return _backfill_dated(
        label="출전취소",
        start_date=start_date,
        end_date=end_date,
        meets=meets,
        page_size=page_size,
        runner=lambda session, client, day, meet, raw_dir, size: ingest_scratches(
            session,
            client,
            race_date=day,
            meet=meet,
            raw_data_dir=raw_dir,
            page_size=size,
        ),
        race_days_only=True,
    )


def backfill_equipment(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    return _backfill_dated(
        label="장구·폐출혈",
        start_date=start_date,
        end_date=end_date,
        meets=meets,
        page_size=page_size,
        runner=lambda session, client, day, meet, raw_dir, size: ingest_equipment(
            session,
            client,
            race_date=day,
            meet=meet,
            raw_data_dir=raw_dir,
            page_size=size,
        ),
        race_days_only=True,
    )


def backfill_start_training(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    return _backfill_dated(
        label="출발훈련",
        start_date=start_date,
        end_date=end_date,
        meets=meets,
        page_size=page_size,
        runner=lambda session, client, day, meet, raw_dir, size: ingest_start_training(
            session,
            client,
            training_date=day,
            meet=meet,
            raw_data_dir=raw_dir,
            page_size=size,
        ),
    )


def backfill_steward_reports(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    return _backfill_dated(
        label="심판리포트",
        start_date=start_date,
        end_date=end_date,
        meets=meets,
        page_size=page_size,
        runner=lambda session, client, day, meet, raw_dir, size: ingest_steward_reports(
            session,
            client,
            race_date=day,
            meet=meet,
            raw_data_dir=raw_dir,
            page_size=size,
        ),
        race_days_only=True,
    )


def _backfill_dated(
    *,
    label: str,
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
    runner,
    race_days_only: bool = False,
) -> int:
    settings = _require_service_key()
    if settings is None:
        return 2

    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    if end < start:
        raise ValueError("종료일이 시작일보다 앞설 수 없습니다.")

    days = 0
    written = 0
    skipped = 0
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        race_day_set: set[tuple[str, int]] | None = None
        if race_days_only:
            rows = session.execute(
                text(
                    """
                    SELECT DISTINCT r.race_date_local AS d,
                           c.kra_meet_code AS meet
                    FROM races r
                    JOIN racecourses c ON c.id = r.racecourse_id
                    WHERE r.race_date_local >= :start
                      AND r.race_date_local <= :end
                    """
                ),
                {"start": start.isoformat(), "end": end.isoformat()},
            ).all()
            race_day_set = {
                (
                    row.d.strftime("%Y%m%d")
                    if hasattr(row.d, "strftime")
                    else str(row.d).replace("-", ""),
                    int(row.meet),
                )
                for row in rows
            }

        current = start
        while current <= end:
            day = current.strftime("%Y%m%d")
            day_used = False
            for meet in meets:
                if race_day_set is not None and (day, meet) not in race_day_set:
                    skipped += 1
                    continue
                try:
                    summary = runner(
                        session,
                        client,
                        day,
                        meet,
                        settings.raw_data_dir,
                        page_size,
                    )
                except (KraApiError, ValueError) as exc:
                    print(
                        f"{label} 수집 실패: {day} {MEET_METADATA[meet][1]} / {exc}",
                        file=sys.stderr,
                    )
                    day_used = True
                    continue
                written += summary.records_written
                print(
                    f"{label} 수집: {day} {MEET_METADATA[meet][1]} / "
                    f"fetched={summary.records_fetched}, written={summary.records_written}"
                )
                time.sleep(0.2)
                day_used = True
            if day_used:
                days += 1
            current += timedelta(days=1)

    extra = f", skipped_empty={skipped}" if race_days_only else ""
    print(f"{label} 백필 완료: days={days}, meets={meets}, written={written}{extra}")
    return 0


def collect_race_sections(race_date: str, meet: int, page_size: int) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print("HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 2

    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_race_sections(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )

    meet_name = MEET_METADATA[meet][1]
    print(
        f"구간기록 수집 완료: 경마장={meet_name}, 날짜={race_date}, "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def backfill_sections(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    if not meets:
        return 0
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print("HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 2

    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    if start > end:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")

    checked = 0
    found = 0
    collected = 0
    skipped = 0
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        current = start
        while current <= end:
            race_date = current.strftime("%Y%m%d")
            for meet in meets:
                checked += 1
                if section_day_is_stored(session, race_date=current, meet=meet):
                    skipped += 1
                    continue
                if not section_data_exists(client, race_date=race_date, meet=meet):
                    continue
                if not result_day_is_stored(session, race_date=current, meet=meet):
                    continue

                found += 1
                summary = ingest_race_sections(
                    session,
                    client,
                    race_date=race_date,
                    meet=meet,
                    raw_data_dir=settings.raw_data_dir,
                    page_size=page_size,
                )
                collected += 1
                print(
                    f"구간기록 수집 완료: {race_date} {MEET_METADATA[meet][1]} / "
                    f"fetched={summary.records_fetched}, written={summary.records_written}",
                    flush=True,
                )
                session.expunge_all()
            current += timedelta(days=1)

    print(
        f"구간기록 백필 완료: 기간={start_date}~{end_date}, 확인={checked}, "
        f"경주일={found}, 신규수집={collected}, 기존완료={skipped}",
        flush=True,
    )
    return 0


def collect_race_passing(race_date: str, meet: int, page_size: int) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print("HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 2
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_race_passing_summaries(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )
    print(
        f"공식 통과대열 수집 완료: 경마장={MEET_METADATA[meet][1]}, 날짜={race_date}, "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


def backfill_race_passing(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print("HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 2
    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    if start > end:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
    checked = collected = written = skipped = 0
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        current = start
        while current <= end:
            race_date = current.strftime("%Y%m%d")
            for meet in meets:
                checked += 1
                if passing_summary_day_is_stored(session, race_date=current, meet=meet):
                    skipped += 1
                    continue
                if not passing_summary_data_exists(client, race_date=race_date, meet=meet):
                    continue
                summary = ingest_race_passing_summaries(
                    session,
                    client,
                    race_date=race_date,
                    meet=meet,
                    raw_data_dir=settings.raw_data_dir,
                    page_size=page_size,
                )
                collected += 1
                written += summary.records_written
                print(
                    f"공식 통과대열 수집: {race_date} {MEET_METADATA[meet][1]} / "
                    f"fetched={summary.records_fetched}, written={summary.records_written}",
                    flush=True,
                )
            current += timedelta(days=1)
    print(
        f"공식 통과대열 백필 완료: 기간={start_date}~{end_date}, 확인={checked}, "
        f"신규수집={collected}, written={written}, 기존완료={skipped}",
        flush=True,
    )
    return 0


def backfill_race_passing_years(
    start_year: int,
    end_year: int,
    meets: list[int],
    page_size: int,
) -> int:
    if start_year > end_year:
        raise ValueError("시작연도는 종료연도보다 늦을 수 없습니다.")
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print("HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 2
    fetched = written = 0
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        for year in range(start_year, end_year + 1):
            for meet in meets:
                summary = ingest_race_passing_summaries(
                    session,
                    client,
                    race_year=year,
                    meet=meet,
                    raw_data_dir=settings.raw_data_dir,
                    page_size=page_size,
                )
                fetched += summary.records_fetched
                written += summary.records_written
                print(
                    f"공식 통과대열 연도 백필: {year} {MEET_METADATA[meet][1]} / "
                    f"fetched={summary.records_fetched}, written={summary.records_written}",
                    flush=True,
                )
    print(
        f"공식 통과대열 연도 백필 완료: {start_year}~{end_year}, "
        f"fetched={fetched}, written={written}",
        flush=True,
    )
    return 0


def sync_daily(
    mode: str,
    *,
    as_of: str | None,
    meets: list[int],
    schedule_days: int,
    result_lookback_days: int,
    page_size: int,
    include_dividends: bool,
    dry_run: bool,
) -> int:
    today = (
        datetime.strptime(as_of, "%Y%m%d").date()
        if as_of is not None
        else datetime.now().astimezone().date()
    )
    window = compute_sync_window(
        today,
        schedule_days=schedule_days,
        result_lookback_days=result_lookback_days,
    )
    schedule_labels = [format_yyyymmdd(value) for value in window.schedule_dates]
    result_start = format_yyyymmdd(window.result_start)
    result_end = format_yyyymmdd(window.result_end)
    meet_labels = ", ".join(MEET_METADATA[meet][1] for meet in meets)

    print(f"일일 동기화 계획: mode={mode}, as_of={format_yyyymmdd(window.as_of)}")
    print(f"  경마장: {meet_labels}")
    if mode in {"schedule", "all"}:
        print(f"  일정·출전표·출발번호 수집 대상: {' '.join(schedule_labels)}")
    if mode in {"results", "all"}:
        print(f"  결과 수집 기간: {result_start}~{result_end}")
        print(f"  확정배당 포함: {'yes' if include_dividends else 'no'}")
        print("  구간기록 포함: yes")
        print("  공식 통과대열·주로빠르기 포함: yes")

    if dry_run:
        print("dry-run: API 호출 없이 종료합니다.")
        return 0

    exit_code = 0
    if mode in {"schedule", "all"}:
        schedule_code = collect_schedule(schedule_labels, meets, page_size)
        if schedule_code != 0:
            exit_code = schedule_code
    if mode in {"results", "all"}:
        results_code = backfill_results(
            result_start,
            result_end,
            meets,
            page_size,
            include_dividends,
        )
        if results_code != 0 and exit_code == 0:
            exit_code = results_code
        sections_code = backfill_sections(result_start, result_end, meets, page_size)
        if sections_code != 0 and exit_code == 0:
            exit_code = sections_code
        passing_code = backfill_race_passing(result_start, result_end, meets, page_size)
        if passing_code != 0 and exit_code == 0:
            exit_code = passing_code
    return exit_code


def sync_latest(
    *,
    as_of: str | None,
    meets: list[int],
    schedule_days: int,
    recent_lookback_days: int,
    history_lookback_days: int,
    trial_lookback_days: int,
    page_size: int,
    include_dividends: bool,
    dry_run: bool,
) -> int:
    """최신 일정부터 주행심사까지 모든 운영 원천을 한 번에 갱신한다."""
    today = (
        datetime.strptime(as_of, "%Y%m%d").date()
        if as_of is not None
        else datetime.now().astimezone().date()
    )
    window = compute_latest_sync_window(
        today,
        schedule_days=schedule_days,
        recent_lookback_days=recent_lookback_days,
        history_lookback_days=history_lookback_days,
        trial_lookback_days=trial_lookback_days,
    )
    schedule_labels = [format_yyyymmdd(value) for value in window.schedule_dates]
    recent_start = format_yyyymmdd(window.recent_start)
    recent_end = format_yyyymmdd(window.recent_end)
    history_start = format_yyyymmdd(window.history_start)
    history_end = format_yyyymmdd(window.history_end)
    trial_start = format_yyyymmdd(window.trial_start)
    trial_end = format_yyyymmdd(window.trial_end)
    supplemental_end = schedule_labels[-1]

    print(f"통합 최신화 계획: as_of={format_yyyymmdd(window.as_of)}")
    print(f"  일정·출전표·출발번호: {' '.join(schedule_labels)}")
    print(f"  결과·구간: {recent_start}~{recent_end}")
    print(f"  경주 보강: {recent_start}~{supplemental_end}")
    print(f"  말 상태: {history_start}~{history_end}")
    print(f"  주행심사: {trial_start}~{trial_end}")
    print("  기준정보: 레이팅·현역 말 프로필·등급변동")
    print(f"  경마장: {', '.join(MEET_METADATA[m][1] for m in meets)}")
    if 4 in meets:
        print("  영천 주행심사: 원천 형식 검증 전으로 수집 보류")
    if dry_run:
        print("dry-run: 외부 호출 없이 종료합니다.")
        return 0

    steps = [
        ("일정·출전표·출발번호", lambda: collect_schedule(schedule_labels, meets, page_size)),
        (
            "경주 결과·확정배당",
            lambda: backfill_results(
                recent_start,
                recent_end,
                meets,
                page_size,
                include_dividends,
            ),
        ),
        (
            "구간기록",
            lambda: backfill_sections(recent_start, recent_end, meets, page_size),
        ),
        (
            "공식 통과대열·주로빠르기",
            lambda: backfill_race_passing(recent_start, recent_end, meets, page_size),
        ),
        (
            "기수변경",
            lambda: backfill_jockey_changes(recent_start, supplemental_end, meets, page_size),
        ),
        (
            "출전취소",
            lambda: backfill_scratches(recent_start, supplemental_end, meets, page_size),
        ),
        (
            "장구·폐출혈",
            lambda: backfill_equipment(recent_start, supplemental_end, meets, page_size),
        ),
        (
            "심판리포트",
            lambda: backfill_steward_reports(recent_start, recent_end, meets, page_size),
        ),
        (
            "체중",
            lambda: backfill_weights(history_start, history_end, meets, page_size),
        ),
        (
            "훈련",
            lambda: backfill_training(history_start, history_end, meets, page_size),
        ),
        (
            "진료",
            lambda: backfill_medical(history_start, history_end, meets, page_size),
        ),
        (
            "출발훈련",
            lambda: backfill_start_training(history_start, history_end, meets, page_size),
        ),
        (
            "주행심사",
            lambda: collect_running_trials(trial_start, trial_end, [m for m in meets if m != 4]),
        ),
        ("레이팅", lambda: collect_ratings(format_yyyymmdd(today), page_size)),
        (
            "현역 말 프로필",
            lambda: collect_horse_profiles(meets, page_size, False, format_yyyymmdd(today)),
        ),
        (
            "등급변동",
            lambda: collect_grade_changes(meets, page_size, format_yyyymmdd(today)),
        ),
    ]

    results: list[tuple[str, str]] = []
    exit_code = 0
    for label, runner in steps:
        print(f"\n[{label}] 시작", flush=True)
        try:
            code = runner()
        except (KraApiError, KraTextError, ValueError) as exc:
            print(f"[{label}] 실패: {exc}", file=sys.stderr, flush=True)
            results.append((label, "실패"))
            exit_code = 1
            continue
        status = "완료" if code == 0 else f"경고({code})"
        if code == 0 and 4 in meets and label == "주행심사":
            status = "영천 보류" if meets == [4] else "완료 (영천 보류)"
        results.append((label, status))
        if code != 0:
            exit_code = code if exit_code == 0 else exit_code

    repair_code = repair_entry_links()
    results.append(("관계자 연결 복구", "완료" if repair_code == 0 else "미해결 있음"))

    print("\n통합 최신화 결과")
    _print_aligned_table(["데이터", "상태"], [[label, status] for label, status in results])
    return exit_code
