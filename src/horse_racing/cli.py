import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, text

from horse_racing.collectors.kra_api import KraApiClient, KraApiError, KraApiRateLimitError
from horse_racing.collectors.kra_text import TEXT_FILE_TYPES, KraTextClient, KraTextError
from horse_racing.config import Settings, get_settings
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


def database_path(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url == "sqlite:///:memory:":
        return None
    return Path(database_url.removeprefix(prefix)).resolve()


def db_info() -> int:
    settings = get_settings()
    engine = create_engine_for_url(settings.database_url)
    inspector = inspect(engine)

    with engine.connect() as connection:
        sqlite_version = connection.execute(text("select sqlite_version()")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()

    path = database_path(settings.database_url)
    print(f"database: {path or settings.database_url}")
    print(f"sqlite_version: {sqlite_version}")
    print(f"journal_mode: {journal_mode}")
    print(f"foreign_keys: {'on' if foreign_keys else 'off'}")
    print(f"tables: {', '.join(sorted(inspector.get_table_names())) or '(none)'}")
    return 0


def valid_race_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜는 YYYYMMDD 형식이어야 합니다.") from exc
    return value


def parse_timestamp_ms(value: str) -> int:
    """Parse epoch milliseconds or ISO-8601; naive timestamps mean Asia/Seoul."""
    if value.isdigit():
        return int(value)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"잘못된 시각: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return int(parsed.timestamp() * 1000)


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
        for race_date in race_dates:
            for meet in meets:
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
                        f"일정 수집: 날짜={race_date}, 경마장={MEET_METADATA[meet][1]}, "
                        f"fetched={fetched}",
                        flush=True,
                    )
                    gate_summary = ingest_gate_numbers(
                        session,
                        client,
                        race_date=race_date,
                        meet=meet,
                        raw_data_dir=settings.raw_data_dir,
                        page_size=page_size,
                    )
                    print(
                        f"출발번호 확인: 날짜={race_date}, 경마장={MEET_METADATA[meet][1]}, "
                        f"fetched={gate_summary.records_fetched}, "
                        f"written={gate_summary.records_written}",
                        flush=True,
                    )
                session.expunge_all()
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


def _require_service_key() -> Settings | None:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print("HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return None
    return settings


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
                    SELECT DISTINCT strftime('%Y%m%d', r.race_date_local) AS d,
                           c.kra_meet_code AS meet
                    FROM races r
                    JOIN racecourses c ON c.id = r.racecourse_id
                    WHERE r.race_date_local >= :start
                      AND r.race_date_local <= :end
                    """
                ),
                {"start": start.isoformat(), "end": end.isoformat()},
            ).all()
            race_day_set = {(str(row.d), int(row.meet)) for row in rows}

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
            lambda: collect_running_trials(trial_start, trial_end, meets),
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
        results.append((label, status))
        if code != 0:
            exit_code = code if exit_code == 0 else exit_code

    repair_code = repair_entry_links()
    results.append(("관계자 연결 복구", "완료" if repair_code == 0 else "미해결 있음"))

    print("\n통합 최신화 결과")
    _print_aligned_table(["데이터", "상태"], [[label, status] for label, status in results])
    return exit_code


def _print_aligned_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    fmt = "  ".join(f"{{:<{width}}}" for width in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * width for width in widths)))
    for row in rows:
        print(fmt.format(*row))


def _format_cell(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, dict | list):
        import json

        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def write_feature_catalog_command(output: str) -> int:
    from horse_racing.analysis.features.catalog import write_feature_catalog

    count = write_feature_catalog(Path(output))
    print(f"feature 카탈로그 생성 완료: {output} (등록 {count}개)")
    return 0


def build_dataset_command(
    version: str,
    as_of_policy: str,
    start_date: str | None,
    end_date: str | None,
    output_dir: str,
    with_features: bool = True,
    feature_set: str = "rich",
) -> int:
    from horse_racing.analysis.dataset import DatasetValidationError, build_dataset

    def to_iso(value: str | None) -> str | None:
        if value is None:
            return None
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"

    with SessionLocal() as session:
        try:
            result = build_dataset(
                session,
                version=version,
                as_of_policy=as_of_policy,
                start_date=to_iso(start_date),
                end_date=to_iso(end_date),
                output_dir=Path(output_dir),
                with_features=with_features,
                feature_set=feature_set,
            )
        except DatasetValidationError as exc:
            print(f"데이터셋 생성 실패: {exc}", file=sys.stderr)
            return 1

    manifest = result.manifest
    print(f"데이터셋 생성 완료: {result.dataset_path}")
    print(f"manifest: {result.manifest_path}")
    print(
        f"행 {manifest['row_count']:,} / 경주 {manifest['race_count']:,} "
        f"(원천 행 {manifest['source_row_count']:,}), "
        f"기간 {manifest['date_range']['start']} ~ {manifest['date_range']['end']}"
    )
    print(f"제외: {manifest['exclusions']}")
    print(
        "라벨 비율: "
        + ", ".join(f"{name}={value:.4f}" for name, value in manifest["label_stats"].items())
    )
    if manifest["feature_names"]:
        print(f"feature {len(manifest['feature_names'])}개, hash {manifest['feature_hash'][:12]}")
    return 0


def run_baselines_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    include_test: bool = False,
    report_dir: str = "data/experiments/reports",
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import (
        SPLIT_BOUNDS,
        BaselineInputError,
        fetch_win_odds,
        render_baseline_report,
        run_baselines,
    )
    from horse_racing.analysis.experiments import ModelRun, record_run

    dataset_path = Path(dataset_dir) / version / as_of_policy / "dataset.parquet"
    manifest_path = Path(dataset_dir) / version / as_of_policy / "manifest.json"
    if not dataset_path.exists():
        print(f"데이터셋 없음: {dataset_path} — build-dataset 먼저 실행", file=sys.stderr)
        return 1
    frame = pl.read_parquet(dataset_path)
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )

    with SessionLocal() as session:
        odds = fetch_win_odds(session)

    evaluate_splits: tuple[str, ...] = ("train", "valid")
    if include_test:
        evaluate_splits = ("train", "valid", "test")
        print("경고: test split 평가는 G1 판정 1회 원칙에 포함됩니다.", file=sys.stderr)

    try:
        results = run_baselines(frame, odds=odds, evaluate_splits=evaluate_splits)
    except BaselineInputError as exc:
        print(f"기준 모델 실행 실패: {exc}", file=sys.stderr)
        return 1

    manifest_slim = {
        key: manifest.get(key)
        for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
    }
    score_features = {"B1": ["rating"], "B2": ["form_recent5_pct"]}
    run_ids: dict[str, str] = {}
    for result in results:
        flat_metrics = {
            f"{split}_{name}": value
            for split, metrics in result.metrics.items()
            for name, value in metrics.items()
        }
        run = ModelRun(
            dataset_version=f"{version}/{as_of_policy}",
            dataset_manifest=manifest_slim,
            feature_names=score_features.get(result.baseline_id, []),
            model_type=result.model_type,
            hyperparameters=result.hyperparameters,
            seed=0,
            train_period=f"~{SPLIT_BOUNDS['train'][1]}",
            valid_period=f"{SPLIT_BOUNDS['valid'][0]}~{SPLIT_BOUNDS['valid'][1]}",
            test_period=f"{SPLIT_BOUNDS['test'][0]}~" if include_test else "",
            metrics=flat_metrics,
            notes=f"{result.baseline_id}: {result.notes}",
        )
        record_run(run)
        run_ids[result.baseline_id] = run.run_id

    report = render_baseline_report(
        results,
        dataset_version=version,
        as_of_policy=as_of_policy,
        evaluate_splits=evaluate_splits,
    )
    report_path = Path(report_dir) / f"baselines_{version}_{as_of_policy}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    for split in evaluate_splits:
        print(f"[{split}]")
        headers = ["기준", "log_loss", "brier", "auc", "ece", "top1", "top3", "coverage"]
        rows = []
        for result in results:
            metrics = result.metrics.get(split)
            if metrics is None:
                continue
            rows.append(
                [
                    result.baseline_id,
                    *[
                        _format_cell(metrics.get(name))
                        for name in (
                            "log_loss",
                            "brier",
                            "auc",
                            "ece",
                            "top1_hit_rate",
                            "top3_inclusion_rate",
                            "coverage",
                        )
                    ],
                ]
            )
        _print_aligned_table(headers, rows)
        print()
    print(f"리포트: {report_path}")
    for baseline_id, run_id in run_ids.items():
        print(f"기록됨 {baseline_id}: run_id={run_id}")
    return 0


def train_model_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    output_dir: str = "data/experiments/models",
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    calibration: str = "auto",
    profile: str = "legacy_all",
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import SPLIT_BOUNDS
    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.lightgbm_model import (
        ModelInputError,
        render_model_report,
        save_bundle,
        train_lightgbm_models,
    )
    from horse_racing.analysis.model_profiles import (
        PROFILES,
        ModelProfileError,
        select_profile_features,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    feature_names = list(manifest.get("feature_names") or [])
    if not feature_names:
        print(
            "manifest에 feature_names가 없습니다. build-dataset을 다시 실행하세요.",
            file=sys.stderr,
        )
        return 1
    try:
        feature_names = select_profile_features(feature_names, profile)
    except ModelProfileError as exc:
        print(f"모델 프로필 적용 실패: {exc}", file=sys.stderr)
        return 1

    frame = pl.read_parquet(dataset_path)
    try:
        result = train_lightgbm_models(
            frame,
            feature_names=feature_names,
            dataset_version=version,
            as_of_policy=as_of_policy,
            seed=seed,
            calibration=calibration,
        )
    except ModelInputError as exc:
        print(f"모델 학습 실패: {exc}", file=sys.stderr)
        return 1

    run_id = new_run_id()
    artifact_dir = Path(output_dir) / run_id
    model_path = artifact_dir / "model.pkl"
    predictions_path = artifact_dir / "predictions_valid.parquet"
    save_bundle(result.bundle, model_path)
    result.valid_predictions.write_parquet(predictions_path)

    report = render_model_report(result.bundle, result.valid_metrics, run_id=run_id)
    report_path = Path(report_dir) / f"lightgbm_{version}_{as_of_policy}_{run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    primary = result.valid_metrics["win"]
    flat_metrics = {
        "valid_log_loss": primary["log_loss"],
        "valid_brier": primary["brier"],
        "valid_auc": primary.get("auc", float("nan")),
        "valid_ece": primary["ece"],
        "valid_top1_hit_rate": primary["top1_hit_rate"],
        "valid_top3_inclusion_rate": primary["top3_inclusion_rate"],
    }
    for label, values in result.valid_metrics.items():
        for metric_name in ("log_loss", "brier", "auc", "ece"):
            if metric_name in values:
                flat_metrics[f"valid_{label}_{metric_name}"] = values[metric_name]

    manifest_slim = {
        key: manifest.get(key)
        for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
    }
    run = ModelRun(
        run_id=run_id,
        dataset_version=f"{version}/{as_of_policy}",
        dataset_manifest=manifest_slim,
        feature_names=feature_names,
        model_type="lightgbm_binary_bundle",
        hyperparameters={
            **result.bundle.hyperparameters,
            "model_profile": profile,
            "model_profile_description": PROFILES[profile].description,
            "artifact_path": str(model_path),
            "calibration_requested": calibration,
            "calibration_selected": {
                label: target.calibration_method for label, target in result.bundle.targets.items()
            },
            "best_iterations": {
                label: target.best_iteration for label, target in result.bundle.targets.items()
            },
        },
        seed=seed,
        train_period=f"~{result.bundle.split_dates['calibration_end']}",
        valid_period=f"{SPLIT_BOUNDS['valid'][0]}~{SPLIT_BOUNDS['valid'][1]}",
        test_period="",
        metrics=flat_metrics,
        notes=(f"M4 LightGBM win/top2/top3; profile={profile}; artifact={model_path}; test 미평가"),
    )
    record_run(run)

    print(f"M4 LightGBM 학습 완료: run_id={run_id}")
    print(f"artifact: {model_path}")
    print(f"valid predictions: {predictions_path}")
    print(f"report: {report_path}")
    print("target  calibration  best_iter  log_loss  AUC     ECE")
    for label, target in result.bundle.targets.items():
        metrics = result.valid_metrics[label]
        print(
            f"{label:<7} {target.calibration_method:<12} {target.best_iteration:<10} "
            f"{metrics['log_loss']:.4f}    {metrics.get('auc', float('nan')):.4f}  "
            f"{metrics['ece']:.4f}"
        )
    print("test split은 평가하지 않았습니다.")
    return 0


def run_walk_forward_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    years: list[int],
    output_dir: str = "data/experiments/walk_forward",
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    calibration: str = "sigmoid",
    profile: str = "ability_v2_core",
    model_kind: str = "binary",
    relevance_mode: str = "finish_order",
    margin_performance: bool = False,
) -> int:
    import polars as pl

    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.model_profiles import ModelProfileError, select_profile_features
    from horse_racing.analysis.walk_forward import (
        render_walk_forward_report,
        run_lightgbm_walk_forward,
        run_racefit_walk_forward,
        run_ranking_walk_forward,
        run_segment_walk_forward,
        run_two_stage_ranking_walk_forward,
        run_two_stage_walk_forward,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        selected_features = select_profile_features(
            list(manifest.get("feature_names") or []),
            profile,
        )
        frame = pl.read_parquet(dataset_path)
        if model_kind == "racefit":
            result = run_racefit_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
            )
        elif model_kind in {"ranking", "full_ranking", "top5_ranking"}:
            result = run_ranking_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
                calibration_objective=(
                    "full_top5"
                    if model_kind == "top5_ranking"
                    else "full_top3"
                    if model_kind == "full_ranking"
                    else "winner"
                ),
                relevance_depth=5 if model_kind == "top5_ranking" else 3,
                relevance_mode=relevance_mode,
                margin_performance=margin_performance,
            )
        elif model_kind == "pace":
            result = run_two_stage_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
            )
        elif model_kind == "pace_ranking":
            result = run_two_stage_ranking_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
            )
        elif model_kind == "segment":
            result = run_segment_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
            )
        else:
            result = run_lightgbm_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
                calibration=calibration,
            )
    except (ModelInputError, ModelProfileError, ValueError) as exc:
        print(f"walk-forward 실패: {exc}", file=sys.stderr)
        return 1

    run_id = new_run_id()
    artifact_dir = Path(output_dir) / run_id
    predictions_path = artifact_dir / "predictions.parquet"
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    result.predictions.write_parquet(predictions_path)
    comparison_path: Path | None = None
    if model_kind == "top5_ranking":
        from horse_racing.analysis.ranking_model import rank_comparison_frame

        comparison_path = artifact_dir / "rank_comparison.parquet"
        rank_comparison_frame(frame, result.predictions, max_rank=5).write_parquet(comparison_path)
    report = render_walk_forward_report(
        result,
        dataset_version=version,
        as_of_policy=as_of_policy,
        profile=profile,
        seed=seed,
        model_name=(
            "RaceFit V1 scenario-mixture ranking"
            if model_kind == "racefit"
            else "Top5 Plackett-Luce LambdaRank"
            if model_kind == "top5_ranking"
            else "Full Plackett-Luce LambdaRank"
            if model_kind == "full_ranking"
            else "LightGBM LambdaRank"
            if model_kind == "ranking"
            else "Two-stage learned pace + LambdaRank"
            if model_kind == "pace_ranking"
            else "Two-stage predicted pace + LightGBM"
            if model_kind == "pace"
            else "Common binary/ranking + Jeju/long correction"
            if model_kind == "segment"
            else "LightGBM binary"
        ),
    )
    report_path = Path(report_dir) / (
        f"walk_forward_{model_kind}_{version}_{as_of_policy}_{profile}_{run_id}.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    aggregate = result.aggregate_metrics
    metrics: dict[str, float | None] = {
        "walk_forward_log_loss": aggregate["log_loss"],
        "walk_forward_auc": aggregate.get("auc"),
        "walk_forward_ece": aggregate["ece"],
        "walk_forward_top1_hit_rate": aggregate["top1_hit_rate"],
        "walk_forward_top3_inclusion_rate": aggregate["top3_inclusion_rate"],
    }
    for target, target_values in result.aggregate_target_metrics.items():
        metrics[f"walk_forward_{target}_log_loss"] = target_values["log_loss"]
        metrics[f"walk_forward_{target}_auc"] = target_values.get("auc")
        metrics[f"walk_forward_{target}_ece"] = target_values["ece"]
    for metric_name, metric_value in result.aggregate_rank_metrics.items():
        metrics[f"walk_forward_{metric_name}"] = metric_value
    for fold in result.folds:
        metrics[f"year_{fold.year}_log_loss"] = fold.metrics["log_loss"]
        metrics[f"year_{fold.year}_auc"] = fold.metrics.get("auc")
        metrics[f"year_{fold.year}_top1"] = fold.metrics["top1_hit_rate"]
        metrics[f"year_{fold.year}_top3"] = fold.metrics["top3_inclusion_rate"]
    run = ModelRun(
        run_id=run_id,
        dataset_version=f"{version}/{as_of_policy}",
        dataset_manifest={
            key: manifest.get(key)
            for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
        },
        feature_names=selected_features,
        model_type=f"lightgbm_{model_kind}_walk_forward",
        hyperparameters={
            "years": sorted(set(years)),
            "profile": profile,
            "calibration": calibration,
            "model_kind": model_kind,
            "predictions_path": str(predictions_path),
            "comparison_path": str(comparison_path) if comparison_path else None,
            "report_path": str(report_path),
        },
        seed=seed,
        train_period="expanding through prior calendar year",
        valid_period=",".join(str(year) for year in sorted(set(years))),
        test_period="",
        metrics=metrics,
        notes="연도별 expanding-window 진단; 신규 미래 holdout 미사용",
    )
    record_run(run)

    print(f"walk-forward 완료: run_id={run_id}")
    for fold in result.folds:
        values = fold.metrics
        print(
            f"{fold.year}: races={values['n_races']:.0f}, "
            f"log_loss={values['log_loss']:.4f}, AUC={values.get('auc', float('nan')):.4f}, "
            f"Top1={values['top1_hit_rate']:.2%}, Top3={values['top3_inclusion_rate']:.2%}"
        )
    print(
        f"aggregate: log_loss={aggregate['log_loss']:.4f}, "
        f"AUC={aggregate.get('auc', float('nan')):.4f}, "
        f"Top1={aggregate['top1_hit_rate']:.2%}, "
        f"Top3={aggregate['top3_inclusion_rate']:.2%}"
    )
    print(f"predictions: {predictions_path}")
    if comparison_path is not None:
        print(f"actual comparison: {comparison_path}")
    print(f"report: {report_path}")
    return 0


def train_ranking_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    output_dir: str = "data/experiments/models",
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    profile: str = "ability_v2_core",
    calibration_objective: str = "full_top3",
    relevance_depth: int = 3,
    relevance_mode: str = "finish_order",
    margin_performance: bool = False,
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import assign_split
    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.model_profiles import ModelProfileError, select_profile_features
    from horse_racing.analysis.ranking_model import (
        rank_comparison_frame,
        render_ranking_report,
        save_ranking_bundle,
        train_ranking_model,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        selected_features = select_profile_features(
            list(manifest.get("feature_names") or []), profile
        )
        frame = pl.read_parquet(dataset_path)
        result = train_ranking_model(
            frame,
            feature_names=selected_features,
            dataset_version=version,
            as_of_policy=as_of_policy,
            seed=seed,
            calibration_objective=calibration_objective,
            relevance_depth=relevance_depth,
            relevance_mode=relevance_mode,
            margin_performance=margin_performance,
        )
    except (ModelInputError, ModelProfileError) as exc:
        print(f"Ranking 학습 실패: {exc}", file=sys.stderr)
        return 1

    run_id = new_run_id()
    artifact_dir = Path(output_dir) / run_id
    model_path = artifact_dir / "model.pkl"
    predictions_path = artifact_dir / "predictions_valid.parquet"
    comparison_path = artifact_dir / "rank_comparison_valid.parquet"
    save_ranking_bundle(result.bundle, model_path)
    result.valid_predictions.write_parquet(predictions_path)
    valid = assign_split(frame).filter(pl.col("split") == "valid").drop("split")
    rank_comparison_frame(
        valid,
        result.valid_predictions,
        max_rank=result.bundle.max_rank,
    ).write_parquet(comparison_path)
    report_path = Path(report_dir) / f"ranking_{version}_{as_of_policy}_{run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_ranking_report(
            result.bundle,
            result.valid_metrics,
            run_id=run_id,
            target_metrics=result.valid_target_metrics,
            ordered_top3_nll=result.ordered_top3_nll,
            ordered_topk_nll=result.ordered_topk_nll,
            topk_rps=result.topk_rps,
            actual_rank_nll=result.actual_rank_nll,
        ),
        encoding="utf-8",
    )
    metrics = result.valid_metrics
    record_run(
        ModelRun(
            run_id=run_id,
            dataset_version=f"{version}/{as_of_policy}",
            dataset_manifest={
                key: manifest.get(key)
                for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
            },
            feature_names=selected_features,
            model_type="lightgbm_ranking_bundle",
            hyperparameters={
                **result.bundle.hyperparameters,
                "artifact_path": str(model_path),
                "model_profile": profile,
                "best_iteration": result.bundle.best_iteration,
                "softmax_beta": result.bundle.softmax_beta,
                "calibration_objective": result.bundle.calibration_objective,
                "relevance_depth": result.bundle.relevance_depth,
                "relevance_mode": result.bundle.relevance_mode,
                "margin_performance": result.bundle.performance_estimator is not None,
                "performance_weight": result.bundle.performance_weight,
                "performance_scale": result.bundle.performance_scale,
                "performance_best_iteration": result.bundle.performance_best_iteration,
                "comparison_path": str(comparison_path),
            },
            seed=seed,
            train_period=f"~{result.bundle.split_dates['calibration_end']}",
            valid_period="2026-03-01~2026-05-31",
            test_period="",
            metrics={
                "valid_log_loss": metrics["log_loss"],
                "valid_brier": metrics["brier"],
                "valid_auc": metrics.get("auc"),
                "valid_ece": metrics["ece"],
                "valid_top1_hit_rate": metrics["top1_hit_rate"],
                "valid_top3_inclusion_rate": metrics["top3_inclusion_rate"],
                **{
                    f"valid_{target}_{metric_name}": metric_value
                    for target, target_values in result.valid_target_metrics.items()
                    for metric_name, metric_value in target_values.items()
                    if metric_name in {"log_loss", "brier", "auc", "ece"}
                },
                "valid_ordered_topk_nll": result.ordered_topk_nll,
                "valid_topk_rps": result.topk_rps,
                "valid_actual_rank_nll": result.actual_rank_nll,
            },
            notes=(
                "LightGBM LambdaRank; calibration block "
                f"{result.bundle.calibration_objective}; test 미평가"
            ),
        )
    )
    print(f"Ranking 학습 완료: run_id={run_id}")
    print(
        f"win: log_loss={metrics['log_loss']:.4f}, AUC={metrics.get('auc', float('nan')):.4f}, "
        f"Top1={metrics['top1_hit_rate']:.2%}, Top3={metrics['top3_inclusion_rate']:.2%}"
    )
    for target in ("top2", "top3", "top4", "top5"):
        target_metrics = result.valid_target_metrics.get(target)
        if target_metrics is not None:
            print(
                f"{target}: log_loss={target_metrics['log_loss']:.4f}, "
                f"AUC={target_metrics.get('auc', float('nan')):.4f}, "
                f"ECE={target_metrics['ece']:.4f}"
            )
    if result.ordered_top3_nll is not None:
        print(f"ordered top3 race NLL={result.ordered_top3_nll:.4f}")
    if result.bundle.max_rank > 3 and result.ordered_topk_nll is not None:
        print(f"ordered top{result.bundle.max_rank} race NLL={result.ordered_topk_nll:.4f}")
        print(
            f"top{result.bundle.max_rank} RPS={result.topk_rps:.4f}, "
            f"actual-rank bucket NLL={result.actual_rank_nll:.4f}"
        )
    print(f"artifact: {model_path}")
    print(f"actual comparison: {comparison_path}")
    print(f"report: {report_path}")
    print("test split은 평가하지 않았습니다.")
    return 0


def train_racefit_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    output_dir: str = "data/experiments/models",
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    profile: str = "ability_v2_core",
) -> int:
    import numpy as np
    import polars as pl

    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.model_profiles import ModelProfileError, select_profile_features
    from horse_racing.analysis.racefit_model import (
        render_racefit_report,
        save_racefit_bundle,
        train_racefit_model,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not str(manifest.get("feature_set", "")).startswith("racefit_"):
        print("RaceFit 학습에는 racefit_* feature_set 데이터셋이 필요합니다.", file=sys.stderr)
        return 1
    try:
        selected_features = select_profile_features(
            list(manifest.get("feature_names") or []), profile
        )
        result = train_racefit_model(
            pl.read_parquet(dataset_path),
            feature_names=selected_features,
            dataset_version=version,
            as_of_policy=as_of_policy,
            seed=seed,
        )
    except (ModelInputError, ModelProfileError, ValueError) as exc:
        print(f"RaceFit 학습 실패: {exc}", file=sys.stderr)
        return 1

    run_id = new_run_id()
    artifact_dir = Path(output_dir) / run_id
    model_path = artifact_dir / "model.pkl"
    predictions_path = artifact_dir / "predictions_valid.parquet"
    save_racefit_bundle(result.bundle, model_path)
    result.valid_predictions.write_parquet(predictions_path)
    report_path = Path(report_dir) / f"racefit_{version}_{as_of_policy}_{run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_racefit_report(result, run_id=run_id), encoding="utf-8")
    metrics = result.valid_target_metrics
    recorded_metrics: dict[str, float | None] = {
        "valid_ordered_top3_nll": result.ordered_top3_nll,
    }
    for target, values in metrics.items():
        recorded_metrics[f"valid_{target}_log_loss"] = values["log_loss"]
        recorded_metrics[f"valid_{target}_brier"] = values["brier"]
        recorded_metrics[f"valid_{target}_auc"] = values.get("auc")
        recorded_metrics[f"valid_{target}_ece"] = values["ece"]
    recorded_metrics["valid_top1_hit_rate"] = result.valid_metrics["top1_hit_rate"]
    recorded_metrics["valid_top3_inclusion_rate"] = result.valid_metrics["top3_inclusion_rate"]
    record_run(
        ModelRun(
            run_id=run_id,
            dataset_version=f"{version}/{as_of_policy}",
            dataset_manifest={
                key: manifest.get(key)
                for key in (
                    "version",
                    "as_of_policy",
                    "row_count",
                    "race_count",
                    "feature_hash",
                    "feature_set",
                )
            },
            feature_names=selected_features,
            model_type="racefit_scenario_bundle",
            hyperparameters={
                **result.bundle.base_bundle.hyperparameters,
                "artifact_path": str(model_path),
                "model_profile": profile,
                "best_iteration": result.bundle.base_bundle.best_iteration,
                "scenario_beta": float(np.exp(result.bundle.log_beta)),
                "objective_weights": result.bundle.objective_weights,
                "l2_penalty": result.bundle.l2_penalty,
                "calibration_metrics": result.bundle.calibration_metrics,
            },
            seed=seed,
            train_period=f"~{result.bundle.split_dates['calibration_end']}",
            valid_period="2026-03-01~2026-05-31",
            test_period="",
            metrics=recorded_metrics,
            notes="RaceFit V1 energy/state + three-pace scenario mixture PL; test 미평가",
        )
    )
    win = result.valid_metrics
    print(f"RaceFit 학습 완료: run_id={run_id}")
    print(
        f"win: log_loss={win['log_loss']:.4f}, AUC={win.get('auc', float('nan')):.4f}, "
        f"Top1={win['top1_hit_rate']:.2%}, Top3={win['top3_inclusion_rate']:.2%}"
    )
    print(
        f"top2 LL={metrics['top2']['log_loss']:.4f}, "
        f"top3 LL={metrics['top3']['log_loss']:.4f}, "
        f"ordered NLL={result.ordered_top3_nll:.4f}"
    )
    print(f"artifact: {model_path}")
    print(f"report: {report_path}")
    print("test split은 평가하지 않았습니다.")
    return 0


def train_catboost_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    output_dir: str = "data/experiments/models",
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    calibration: str = "auto",
    profile: str = "legacy_all",
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import SPLIT_BOUNDS
    from horse_racing.analysis.catboost_model import (
        render_catboost_report,
        save_catboost_bundle,
        train_catboost_models,
    )
    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.model_profiles import (
        PROFILES,
        ModelProfileError,
        select_profile_features,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    feature_names = list(manifest.get("feature_names") or [])
    if not feature_names:
        print("manifest에 feature_names가 없습니다.", file=sys.stderr)
        return 1
    try:
        feature_names = select_profile_features(feature_names, profile)
    except ModelProfileError as exc:
        print(f"모델 프로필 적용 실패: {exc}", file=sys.stderr)
        return 1

    frame = pl.read_parquet(dataset_path)
    try:
        result = train_catboost_models(
            frame,
            feature_names=feature_names,
            dataset_version=version,
            as_of_policy=as_of_policy,
            seed=seed,
            calibration=calibration,
        )
    except ModelInputError as exc:
        print(f"CatBoost 학습 실패: {exc}", file=sys.stderr)
        return 1

    run_id = new_run_id()
    artifact_dir = Path(output_dir) / run_id
    model_path = artifact_dir / "model.pkl"
    predictions_path = artifact_dir / "predictions_valid.parquet"
    save_catboost_bundle(result.bundle, model_path)
    result.valid_predictions.write_parquet(predictions_path)
    report = render_catboost_report(result.bundle, result.valid_metrics, run_id=run_id)
    report_path = Path(report_dir) / f"catboost_{version}_{as_of_policy}_{run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    primary = result.valid_metrics["win"]
    flat_metrics = {
        "valid_log_loss": primary["log_loss"],
        "valid_brier": primary["brier"],
        "valid_auc": primary.get("auc", float("nan")),
        "valid_ece": primary["ece"],
        "valid_top1_hit_rate": primary["top1_hit_rate"],
        "valid_top3_inclusion_rate": primary["top3_inclusion_rate"],
    }
    for label, values in result.valid_metrics.items():
        for metric_name in ("log_loss", "brier", "auc", "ece"):
            if metric_name in values:
                flat_metrics[f"valid_{label}_{metric_name}"] = values[metric_name]
    manifest_slim = {
        key: manifest.get(key)
        for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
    }
    run = ModelRun(
        run_id=run_id,
        dataset_version=f"{version}/{as_of_policy}",
        dataset_manifest=manifest_slim,
        feature_names=feature_names,
        model_type="catboost_binary_bundle",
        hyperparameters={
            **result.bundle.hyperparameters,
            "model_profile": profile,
            "model_profile_description": PROFILES[profile].description,
            "artifact_path": str(model_path),
            "calibration_requested": calibration,
            "calibration_selected": {
                label: target.calibration_method for label, target in result.bundle.targets.items()
            },
            "best_iterations": {
                label: target.best_iteration for label, target in result.bundle.targets.items()
            },
        },
        seed=seed,
        train_period=f"~{result.bundle.split_dates['calibration_end']}",
        valid_period=f"{SPLIT_BOUNDS['valid'][0]}~{SPLIT_BOUNDS['valid'][1]}",
        test_period="",
        metrics=flat_metrics,
        notes=(f"M4 CatBoost win/top2/top3; profile={profile}; artifact={model_path}; test 미평가"),
    )
    record_run(run)
    print(f"M4 CatBoost 학습 완료: run_id={run_id}")
    print(f"artifact: {model_path}")
    print(f"valid predictions: {predictions_path}")
    print(f"report: {report_path}")
    print("target  calibration  best_iter  log_loss  AUC     ECE")
    for label, target in result.bundle.targets.items():
        metrics = result.valid_metrics[label]
        print(
            f"{label:<7} {target.calibration_method:<12} {target.best_iteration:<10} "
            f"{metrics['log_loss']:.4f}    {metrics.get('auc', float('nan')):.4f}  "
            f"{metrics['ece']:.4f}"
        )
    print("test split은 평가하지 않았습니다.")
    return 0


def run_ablation_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    profile: str = "legacy_all",
) -> int:
    import polars as pl

    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.model_profiles import (
        ModelProfileError,
        select_profile_features,
    )
    from horse_racing.analysis.model_stability import (
        render_ablation_report,
        run_lightgbm_ablation,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    feature_names = list(manifest.get("feature_names") or [])
    try:
        feature_names = select_profile_features(feature_names, profile)
    except ModelProfileError as exc:
        print(f"모델 프로필 적용 실패: {exc}", file=sys.stderr)
        return 1
    result = run_lightgbm_ablation(
        pl.read_parquet(dataset_path),
        feature_names=feature_names,
        dataset_version=version,
        as_of_policy=as_of_policy,
        seed=seed,
    )
    report = render_ablation_report(
        result,
        dataset_version=version,
        as_of_policy=as_of_policy,
        seed=seed,
    )
    report_path = Path(report_dir) / f"ablation_{version}_{as_of_policy}_{profile}_seed{seed}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    run_id = new_run_id()
    metrics = {
        "valid_log_loss_full": result.baseline_log_loss,
        "valid_auc_full": result.baseline_auc,
        "valid_ece_full": result.baseline_ece,
    }
    for index, row in enumerate(result.rows):
        metrics[f"ablation_{index}_delta_log_loss"] = row.delta_log_loss
    run = ModelRun(
        run_id=run_id,
        dataset_version=f"{version}/{as_of_policy}",
        dataset_manifest={
            key: manifest.get(key)
            for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
        },
        feature_names=feature_names,
        model_type="lightgbm_feature_group_ablation",
        hyperparameters={
            "seed": seed,
            "model_profile": profile,
            "groups": [
                {
                    "name": row.group,
                    "feature_count": row.feature_count,
                    "delta_log_loss": row.delta_log_loss,
                }
                for row in result.rows
            ],
        },
        seed=seed,
        train_period="~2026-02-28",
        valid_period="2026-03-01~2026-05-31",
        test_period="",
        metrics=metrics,
        notes=(
            f"M4 win feature-group ablation; profile={profile}; report={report_path}; test 미평가"
        ),
    )
    record_run(run)
    print(f"Ablation 완료: run_id={run_id}")
    print(f"전체 log loss: {result.baseline_log_loss:.4f}")
    for row in result.rows:
        print(
            f"{row.group}: without={row.valid_log_loss:.4f}, "
            f"delta={row.delta_log_loss:+.4f} ({row.feature_count} features)"
        )
    print(f"report: {report_path}")
    print("test split은 평가하지 않았습니다.")
    return 0


def build_ensemble_command(
    run_ids: list[str],
    dataset_dir: str,
    *,
    output_dir: str = "data/experiments/models",
    report_dir: str = "data/experiments/reports",
    allow_cross_dataset: bool = False,
    target_member_weights: dict[str, list[float]] | None = None,
    reference_version: str | None = None,
    reference_as_of: str | None = None,
) -> int:
    import polars as pl

    from horse_racing.analysis.experiments import ModelRun, get_run, new_run_id, record_run
    from horse_racing.analysis.model_ensemble import (
        ProbabilityEnsembleBundle,
        evaluate_ensemble_bundle,
        render_ensemble_report,
        save_ensemble_bundle,
    )

    if len(run_ids) < 2:
        print("ensemble에는 2개 이상의 run_id가 필요합니다.", file=sys.stderr)
        return 2
    members = []
    for member_id in run_ids:
        run = get_run(member_id)
        if run is None:
            print(f"알 수 없는 run_id: {member_id}", file=sys.stderr)
            return 1
        members.append(run)
    model_types = {run.model_type for run in members}
    versions = {run.dataset_version for run in members}
    feature_hashes = {run.feature_hash for run in members}
    cross_dataset = len(versions) != 1 or len(feature_hashes) != 1
    if cross_dataset and not allow_cross_dataset:
        print("ensemble member의 데이터셋·feature가 일치하지 않습니다.", file=sys.stderr)
        return 1
    supported_types = {
        "lightgbm_binary_bundle",
        "catboost_binary_bundle",
        "probability_ensemble",
        "lightgbm_ranking_bundle",
    }
    if not model_types <= supported_types:
        unsupported = sorted(model_types - supported_types)
        print(f"ensemble을 지원하지 않는 model_type: {', '.join(unsupported)}", file=sys.stderr)
        return 1
    member_type = members[0].model_type if len(model_types) == 1 else "mixed"
    member_paths = [str(run.hyperparameters.get("artifact_path", "")) for run in members]
    if any(not item for item in member_paths):
        print("artifact 경로가 없는 member가 있습니다.", file=sys.stderr)
        return 1
    member_version, member_as_of_policy = members[0].dataset_version.split("/", maxsplit=1)
    version = reference_version or member_version
    as_of_policy = reference_as_of or member_as_of_policy
    as_of_order = {"day_before_18": 0, "start_minus_30m": 1}
    if cross_dataset:
        reference_order = as_of_order.get(as_of_policy)
        if reference_order is None:
            print(f"지원하지 않는 기준 as-of 정책: {as_of_policy}", file=sys.stderr)
            return 1
        for member in members[1:]:
            try:
                _, member_as_of = member.dataset_version.split("/", maxsplit=1)
            except ValueError:
                print(f"지원하지 않는 dataset_version: {member.dataset_version}", file=sys.stderr)
                return 1
            member_order = as_of_order.get(member_as_of)
            if member_order is None or member_order > reference_order:
                print(
                    "기준 데이터셋보다 늦은 정보시점의 member는 결합할 수 없습니다: "
                    f"reference={as_of_policy}, member={member_as_of}",
                    file=sys.stderr,
                )
                return 1
    dataset_path = Path(dataset_dir) / version / as_of_policy / "dataset.parquet"
    manifest_path = Path(dataset_dir) / version / as_of_policy / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"기준 데이터셋 또는 manifest 없음: {dataset_path.parent}", file=sys.stderr)
        return 1
    frame = pl.read_parquet(dataset_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_features = set().union(*(set(run.feature_names) for run in members))
    missing_features = sorted(required_features - set(frame.columns))
    if missing_features:
        print(
            f"기준 데이터셋에 ensemble member feature가 없습니다: {missing_features[:10]}",
            file=sys.stderr,
        )
        return 1
    reference_features = list(manifest.get("feature_names") or [])
    ensemble_features = [name for name in reference_features if name in required_features]
    if set(ensemble_features) != required_features:
        print("기준 manifest의 feature 순서로 ensemble 계약을 만들 수 없습니다.", file=sys.stderr)
        return 1
    targets = ["win", "top2", "top3"]
    if target_member_weights and "top5" in target_member_weights:
        if "top4" not in target_member_weights:
            print("Top5 ensemble에는 --top4-weights도 필요합니다.", file=sys.stderr)
            return 2
        targets.extend(["top4", "top5"])
    bundle = ProbabilityEnsembleBundle(
        dataset_version=version,
        as_of_policy=as_of_policy,
        member_type=member_type,
        member_run_ids=run_ids,
        member_paths=member_paths,
        feature_names=ensemble_features,
        targets=targets,
        member_types=[run.model_type for run in members],
        target_member_weights=target_member_weights or {},
    )
    metrics, predictions = evaluate_ensemble_bundle(bundle, frame, split="valid")
    ensemble_run_id = new_run_id()
    artifact_dir = Path(output_dir) / ensemble_run_id
    model_path = artifact_dir / "model.pkl"
    predictions_path = artifact_dir / "predictions_valid.parquet"
    save_ensemble_bundle(bundle, model_path)
    predictions.write_parquet(predictions_path)
    report = render_ensemble_report(bundle, metrics, run_id=ensemble_run_id)
    report_path = Path(report_dir) / f"ensemble_{version}_{as_of_policy}_{ensemble_run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    primary = metrics["win"]
    flat_metrics = {
        "valid_log_loss": primary["log_loss"],
        "valid_brier": primary["brier"],
        "valid_auc": primary.get("auc", float("nan")),
        "valid_ece": primary["ece"],
        "valid_top1_hit_rate": primary["top1_hit_rate"],
        "valid_top3_inclusion_rate": primary["top3_inclusion_rate"],
    }
    for label, values in metrics.items():
        for metric_name in ("log_loss", "brier", "auc", "ece"):
            if metric_name in values:
                flat_metrics[f"valid_{label}_{metric_name}"] = values[metric_name]
    run = ModelRun(
        run_id=ensemble_run_id,
        dataset_version=f"{version}/{as_of_policy}",
        dataset_manifest={
            key: manifest.get(key)
            for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
        },
        feature_names=ensemble_features,
        model_type="probability_ensemble",
        hyperparameters={
            "artifact_path": str(model_path),
            "member_type": member_type,
            "member_types": [run.model_type for run in members],
            "member_run_ids": run_ids,
            "member_dataset_versions": [run.dataset_version for run in members],
            "cross_dataset": cross_dataset,
            "target_member_weights": target_member_weights or {},
            "reference_dataset_version": f"{version}/{as_of_policy}",
        },
        seed=0,
        train_period=members[0].train_period,
        valid_period=members[0].valid_period,
        test_period="",
        metrics=flat_metrics,
        notes=(
            f"M4 probability mean ensemble; cross_dataset={cross_dataset}; "
            f"artifact={model_path}; test 미평가"
        ),
    )
    record_run(run)
    print(f"확률 평균 ensemble 완료: run_id={ensemble_run_id}")
    print(f"members: {', '.join(run_ids)}")
    for label, values in metrics.items():
        print(
            f"{label}: log_loss={values['log_loss']:.4f}, "
            f"AUC={values.get('auc', float('nan')):.4f}, ECE={values['ece']:.4f}"
        )
    print(f"artifact: {model_path}")
    print(f"report: {report_path}")
    print("test split은 평가하지 않았습니다.")
    return 0


def evaluate_model_command(
    run_id: str,
    dataset_dir: str,
    *,
    include_test: bool = False,
    report_dir: str = "data/experiments/reports",
) -> int:
    import polars as pl

    from horse_racing.analysis.experiments import get_run
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.model_stability import (
        evaluate_win_segments,
        render_segment_report,
    )

    run = get_run(run_id)
    if run is None:
        print(f"알 수 없는 run_id: {run_id}", file=sys.stderr)
        return 1
    artifact_path = run.hyperparameters.get("artifact_path")
    if not artifact_path:
        print(f"run에 모델 artifact 경로가 없습니다: {run_id}", file=sys.stderr)
        return 1
    try:
        version, as_of_policy = run.dataset_version.split("/", maxsplit=1)
    except ValueError:
        print(f"지원하지 않는 dataset_version: {run.dataset_version}", file=sys.stderr)
        return 1
    dataset_path = Path(dataset_dir) / version / as_of_policy / "dataset.parquet"
    if not dataset_path.exists():
        print(f"데이터셋 없음: {dataset_path}", file=sys.stderr)
        return 1

    split = "test" if include_test else "valid"
    if include_test:
        print("경고: test split 평가는 Gate G1 1회 판정에 해당합니다.", file=sys.stderr)
    frame = pl.read_parquet(dataset_path)
    try:
        if run.model_type == "catboost_binary_bundle":
            from horse_racing.analysis.catboost_model import (
                evaluate_catboost_bundle,
                load_catboost_bundle,
                render_catboost_report,
            )

            bundle = load_catboost_bundle(Path(str(artifact_path)))
            metrics, predictions = evaluate_catboost_bundle(bundle, frame, split=split)
            report = render_catboost_report(bundle, metrics, run_id=run_id, split=split)
            model_prefix = "catboost"
            model_name = "CatBoost"
        elif run.model_type == "probability_ensemble":
            from horse_racing.analysis.model_ensemble import (
                evaluate_ensemble_bundle,
                load_ensemble_bundle,
                render_ensemble_report,
            )

            bundle = load_ensemble_bundle(Path(str(artifact_path)))
            metrics, predictions = evaluate_ensemble_bundle(bundle, frame, split=split)
            report = render_ensemble_report(bundle, metrics, run_id=run_id, split=split)
            model_prefix = "ensemble"
            model_name = "Probability ensemble"
        else:
            from horse_racing.analysis.lightgbm_model import (
                evaluate_bundle,
                load_bundle,
                render_model_report,
            )

            bundle = load_bundle(Path(str(artifact_path)))
            metrics, predictions = evaluate_bundle(bundle, frame, split=split)
            report = render_model_report(bundle, metrics, run_id=run_id, split=split)
            model_prefix = "lightgbm"
            model_name = "LightGBM"
    except ModelInputError as exc:
        print(f"모델 평가 실패: {exc}", file=sys.stderr)
        return 1

    artifact_dir = Path(str(artifact_path)).parent
    predictions_path = artifact_dir / f"predictions_{split}.parquet"
    predictions.write_parquet(predictions_path)
    report_path = Path(report_dir) / f"{model_prefix}_{version}_{as_of_policy}_{run_id}_{split}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    segments = evaluate_win_segments(frame, predictions, split=split)
    segment_report = render_segment_report(
        segments,
        model_name=f"{model_name} {run_id}",
        split=split,
    )
    segment_path = (
        Path(report_dir) / f"{model_prefix}_{version}_{as_of_policy}_{run_id}_{split}_segments.md"
    )
    segment_path.write_text(segment_report, encoding="utf-8")
    print(f"{split} 평가 완료: {report_path}")
    print(f"구간별 평가: {segment_path}")
    for label, values in metrics.items():
        print(
            f"{label}: log_loss={values['log_loss']:.4f}, "
            f"AUC={values.get('auc', float('nan')):.4f}, ECE={values['ece']:.4f}"
        )
    return 0


def run_g1_gate_command(
    run_id: str,
    dataset_dir: str,
    *,
    report_dir: str = "data/experiments/reports",
    confirm_test: bool = False,
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import (
        assign_split,
        fit_softmax_beta,
        score_softmax_probabilities,
    )
    from horse_racing.analysis.experiments import (
        ModelRun,
        get_run,
        load_runs,
        new_run_id,
        record_run,
    )
    from horse_racing.analysis.gates import (
        judge_g1,
        render_g1_report,
        segment_rows_by_key,
    )
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.metrics import evaluate_probabilities
    from horse_racing.analysis.model_stability import evaluate_win_segments

    if not confirm_test:
        print("G1 test를 열려면 --confirm-test가 필요합니다.", file=sys.stderr)
        return 2
    candidate_run = get_run(run_id)
    if candidate_run is None:
        print(f"알 수 없는 후보 run_id: {run_id}", file=sys.stderr)
        return 1
    existing = [
        run
        for run in load_runs()
        if run.model_type == "g1_gate_evaluation"
        and run.hyperparameters.get("candidate_run_id") == run_id
    ]
    if existing:
        print(
            f"이 후보의 G1 test는 이미 평가했습니다: {existing[-1].run_id}",
            file=sys.stderr,
        )
        return 1
    artifact_path = candidate_run.hyperparameters.get("artifact_path")
    if not artifact_path:
        print("후보 run에 artifact 경로가 없습니다.", file=sys.stderr)
        return 1
    version, as_of_policy = candidate_run.dataset_version.split("/", maxsplit=1)
    dataset_path = Path(dataset_dir) / version / as_of_policy / "dataset.parquet"
    manifest_path = Path(dataset_dir) / version / as_of_policy / "manifest.json"
    frame = pl.read_parquet(dataset_path)
    split_frame = assign_split(frame)
    train = split_frame.filter(pl.col("split") == "train").drop("split")
    test = split_frame.filter(pl.col("split") == "test").drop("split")

    beta_b1 = fit_softmax_beta(train, "rating", higher_is_better=True)
    beta_b2 = fit_softmax_beta(train, "form_recent5_pct", higher_is_better=False)
    b1_scored = score_softmax_probabilities(test, "rating", beta=beta_b1, higher_is_better=True)
    b2_scored = score_softmax_probabilities(
        test, "form_recent5_pct", beta=beta_b2, higher_is_better=False
    )
    baseline_b1 = evaluate_probabilities(b1_scored, "probability", label_column="win")
    baseline_b2 = evaluate_probabilities(b2_scored, "probability", label_column="win")

    try:
        if candidate_run.model_type == "probability_ensemble":
            from horse_racing.analysis.model_ensemble import (
                evaluate_ensemble_bundle,
                load_ensemble_bundle,
            )

            bundle = load_ensemble_bundle(Path(str(artifact_path)))
            candidate_metrics, candidate_predictions = evaluate_ensemble_bundle(
                bundle, frame, split="test"
            )
        elif candidate_run.model_type == "catboost_binary_bundle":
            from horse_racing.analysis.catboost_model import (
                evaluate_catboost_bundle,
                load_catboost_bundle,
            )

            bundle = load_catboost_bundle(Path(str(artifact_path)))
            candidate_metrics, candidate_predictions = evaluate_catboost_bundle(
                bundle, frame, split="test"
            )
        else:
            from horse_racing.analysis.lightgbm_model import evaluate_bundle, load_bundle

            bundle = load_bundle(Path(str(artifact_path)))
            candidate_metrics, candidate_predictions = evaluate_bundle(bundle, frame, split="test")
    except ModelInputError as exc:
        print(f"G1 후보 평가 실패: {exc}", file=sys.stderr)
        return 1
    candidate = candidate_metrics["win"]

    b1_predictions = b1_scored.select(
        "race_id", "race_entry_id", pl.col("probability").alias("prob_win")
    )
    b2_predictions = b2_scored.select(
        "race_id", "race_entry_id", pl.col("probability").alias("prob_win")
    )
    meet_candidate = segment_rows_by_key(
        evaluate_win_segments(frame, candidate_predictions, split="test")["경마장"]
    )
    meet_b1 = segment_rows_by_key(
        evaluate_win_segments(frame, b1_predictions, split="test")["경마장"]
    )
    meet_b2 = segment_rows_by_key(
        evaluate_win_segments(frame, b2_predictions, split="test")["경마장"]
    )

    ablation_runs = [
        run
        for run in load_runs()
        if run.model_type == "lightgbm_feature_group_ablation"
        and run.dataset_version == candidate_run.dataset_version
    ]
    ablation_passed = False
    if ablation_runs:
        groups = ablation_runs[-1].hyperparameters.get("groups", [])
        largest_delta = max((float(item["delta_log_loss"]) for item in groups), default=1.0)
        valid_gain = 0.2905104392464778 - candidate_run.metrics["valid_log_loss"]
        ablation_passed = largest_delta < valid_gain * 0.5

    decision = judge_g1(
        candidate=candidate,
        baseline_b1=baseline_b1,
        baseline_b2=baseline_b2,
        meet_candidate=meet_candidate,
        meet_b1=meet_b1,
        ablation_passed=ablation_passed,
    )
    gate_run_id = new_run_id()
    report = render_g1_report(
        candidate_run_id=run_id,
        candidate=candidate,
        baseline_b1=baseline_b1,
        baseline_b2=baseline_b2,
        meet_candidate=meet_candidate,
        meet_b1=meet_b1,
        meet_b2=meet_b2,
        decision=decision,
        beta_b1=beta_b1,
        beta_b2=beta_b2,
    )
    report_path = Path(report_dir) / f"g1_{version}_{as_of_policy}_{gate_run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    predictions_path = Path(str(artifact_path)).parent / "predictions_test_g1.parquet"
    candidate_predictions.write_parquet(predictions_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metrics = {
        "test_log_loss": candidate["log_loss"],
        "test_brier": candidate["brier"],
        "test_auc": candidate.get("auc", float("nan")),
        "test_ece": candidate["ece"],
        "test_top1_hit_rate": candidate["top1_hit_rate"],
        "test_top3_inclusion_rate": candidate["top3_inclusion_rate"],
        "test_b1_log_loss": baseline_b1["log_loss"],
        "test_b2_log_loss": baseline_b2["log_loss"],
    }
    for meet_code in ("1", "2", "3"):
        metrics[f"test_meet_{meet_code}_log_loss"] = meet_candidate[meet_code]["log_loss"]
    gate_run = ModelRun(
        run_id=gate_run_id,
        dataset_version=candidate_run.dataset_version,
        dataset_manifest={
            key: manifest.get(key)
            for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
        },
        feature_names=candidate_run.feature_names,
        model_type="g1_gate_evaluation",
        hyperparameters={
            "candidate_run_id": run_id,
            "criteria": decision.criteria,
            "passed": decision.passed,
            "beta_b1": beta_b1,
            "beta_b2": beta_b2,
        },
        seed=0,
        train_period=candidate_run.train_period,
        valid_period=candidate_run.valid_period,
        test_period="2026-06-01~",
        metrics=metrics,
        notes=f"Gate G1 {'PASS' if decision.passed else 'FAIL'}; report={report_path}",
    )
    record_run(gate_run)
    print(f"Gate G1 {'PASS' if decision.passed else 'FAIL'}: run_id={gate_run_id}")
    print(
        f"후보 test log_loss={candidate['log_loss']:.4f}, "
        f"B1={baseline_b1['log_loss']:.4f}, B2={baseline_b2['log_loss']:.4f}, "
        f"ECE={candidate['ece']:.4f}"
    )
    for meet_code, meet_name in (("1", "서울"), ("2", "제주"), ("3", "부산경남")):
        print(
            f"{meet_name}: 후보={meet_candidate[meet_code]['log_loss']:.4f}, "
            f"B1={meet_b1[meet_code]['log_loss']:.4f}, "
            f"B2={meet_b2[meet_code]['log_loss']:.4f}"
        )
    print(f"report: {report_path}")
    return 0 if decision.passed else 1


def run_g2_gate_command(
    run_id: str,
    dataset_dir: str,
    *,
    report_dir: str = "data/experiments/reports",
    confirm_test_market: bool = False,
    bootstrap_iterations: int = 1_000,
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import assign_split, fetch_win_odds
    from horse_racing.analysis.experiments import (
        ModelRun,
        get_run,
        load_runs,
        new_run_id,
        record_run,
    )
    from horse_racing.analysis.market_gate import (
        apply_incremental_logit,
        backtest_win_ev,
        bootstrap_log_loss_improvement,
        evaluate_market_and_mix,
        fit_incremental_logit,
        judge_g2,
        overround_summary,
        prepare_market_comparison,
        render_g2_report,
        select_ev_threshold,
    )

    if not confirm_test_market:
        print("G2 test 시장평가를 열려면 --confirm-test-market이 필요합니다.", file=sys.stderr)
        return 2
    if bootstrap_iterations < 100:
        print("bootstrap은 최소 100회가 필요합니다.", file=sys.stderr)
        return 2
    candidate_run = get_run(run_id)
    if candidate_run is None:
        print(f"알 수 없는 후보 run_id: {run_id}", file=sys.stderr)
        return 1
    all_runs = load_runs()
    g1_runs = [
        run
        for run in all_runs
        if run.model_type == "g1_gate_evaluation"
        and run.hyperparameters.get("candidate_run_id") == run_id
        and run.hyperparameters.get("passed") is True
    ]
    if not g1_runs:
        print("PASS한 G1 기록이 없는 후보입니다. G2를 실행하지 않습니다.", file=sys.stderr)
        return 1
    existing = [
        run
        for run in all_runs
        if run.model_type == "g2_gate_evaluation"
        and run.hyperparameters.get("candidate_run_id") == run_id
    ]
    if existing:
        print(
            f"이 후보의 G2 test는 이미 평가했습니다: {existing[-1].run_id}",
            file=sys.stderr,
        )
        return 1
    artifact_path_raw = candidate_run.hyperparameters.get("artifact_path")
    if not artifact_path_raw:
        print("후보 run에 artifact 경로가 없습니다.", file=sys.stderr)
        return 1
    artifact_path = Path(str(artifact_path_raw))
    artifact_dir = artifact_path.parent
    valid_predictions_path = artifact_dir / "predictions_valid.parquet"
    test_predictions_path = artifact_dir / "predictions_test_g1.parquet"
    if not valid_predictions_path.exists() or not test_predictions_path.exists():
        print(
            "고정 valid 또는 G1 test prediction 파일이 없습니다. 재추론하지 않고 중단합니다.",
            file=sys.stderr,
        )
        return 1

    version, as_of_policy = candidate_run.dataset_version.split("/", maxsplit=1)
    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    frame = assign_split(pl.read_parquet(dataset_path))
    valid_frame = frame.filter(pl.col("split") == "valid").drop("split")
    test_frame = frame.filter(pl.col("split") == "test").drop("split")
    valid_predictions = pl.read_parquet(valid_predictions_path)
    test_predictions = pl.read_parquet(test_predictions_path)
    with SessionLocal() as session:
        odds = fetch_win_odds(session)

    valid_market = prepare_market_comparison(valid_frame, valid_predictions, odds)
    fit = fit_incremental_logit(valid_market)
    valid_scored = apply_incremental_logit(valid_market, fit)
    valid_market_metrics, valid_mixed_metrics = evaluate_market_and_mix(valid_scored)
    selected_threshold, threshold_rows = select_ev_threshold(valid_scored)

    # Holdout test access begins here.  Every choice above is fixed from valid.
    test_market = prepare_market_comparison(test_frame, test_predictions, odds)
    test_scored = apply_incremental_logit(test_market, fit)
    test_market_metrics, test_mixed_metrics = evaluate_market_and_mix(test_scored)
    ll_bootstrap = bootstrap_log_loss_improvement(
        test_scored,
        iterations=bootstrap_iterations,
    )
    test_backtest = backtest_win_ev(
        test_scored,
        threshold=selected_threshold,
        bootstrap_iterations=bootstrap_iterations,
    )
    decision = judge_g2(
        fit=fit,
        market_test_log_loss=test_market_metrics["log_loss"],
        mixed_test_log_loss=test_mixed_metrics["log_loss"],
        log_loss_bootstrap=ll_bootstrap,
        roi_bootstrap=test_backtest.roi_bootstrap,
    )

    gate_run_id = new_run_id()
    report = render_g2_report(
        candidate_run_id=run_id,
        fit=fit,
        valid_market_metrics=valid_market_metrics,
        valid_mixed_metrics=valid_mixed_metrics,
        test_market_metrics=test_market_metrics,
        test_mixed_metrics=test_mixed_metrics,
        valid_overround=overround_summary(valid_scored),
        test_overround=overround_summary(test_scored),
        selected_threshold=selected_threshold,
        threshold_rows=threshold_rows,
        test_backtest=test_backtest,
        log_loss_bootstrap=ll_bootstrap,
        decision=decision,
        valid_total_races=valid_frame["race_id"].n_unique(),
        test_total_races=test_frame["race_id"].n_unique(),
    )
    report_path = Path(report_dir) / f"g2_{version}_{as_of_policy}_{gate_run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    predictions_path = artifact_dir / "predictions_market_g2.parquet"
    pl.concat(
        [
            valid_scored.with_columns(pl.lit("valid").alias("split")),
            test_scored.with_columns(pl.lit("test").alias("split")),
        ],
        how="vertical",
    ).write_parquet(predictions_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roi_bootstrap = test_backtest.roi_bootstrap
    metrics = {
        "valid_market_log_loss": valid_market_metrics["log_loss"],
        "valid_mixed_log_loss": valid_mixed_metrics["log_loss"],
        "valid_model_beta": fit.model_coefficient,
        "valid_model_beta_cluster_se": fit.model_standard_error,
        "valid_model_beta_one_sided_p": fit.model_p_value_one_sided,
        "test_market_log_loss": test_market_metrics["log_loss"],
        "test_mixed_log_loss": test_mixed_metrics["log_loss"],
        "test_log_loss_improvement": (
            test_market_metrics["log_loss"] - test_mixed_metrics["log_loss"]
        ),
        "test_log_loss_bootstrap_lower_95": ll_bootstrap.lower_95,
        "test_log_loss_bootstrap_upper_95": ll_bootstrap.upper_95,
        "test_flat_roi": test_backtest.flat_roi,
        "test_n_bets": float(test_backtest.n_bets),
        "test_max_drawdown_units": test_backtest.max_drawdown_units,
        "test_max_consecutive_losses": float(test_backtest.max_consecutive_losses),
        "test_roi_bootstrap_median": roi_bootstrap.median if roi_bootstrap else None,
        "test_roi_bootstrap_lower_95": (roi_bootstrap.lower_95 if roi_bootstrap else None),
        "test_roi_bootstrap_upper_95": (roi_bootstrap.upper_95 if roi_bootstrap else None),
    }
    gate_run = ModelRun(
        run_id=gate_run_id,
        dataset_version=candidate_run.dataset_version,
        dataset_manifest={
            key: manifest.get(key)
            for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
        },
        feature_names=candidate_run.feature_names,
        model_type="g2_gate_evaluation",
        hyperparameters={
            "candidate_run_id": run_id,
            "g1_gate_run_id": g1_runs[-1].run_id,
            "status": decision.status,
            "criteria": decision.criteria,
            "selected_ev_threshold": selected_threshold,
            "bootstrap_iterations": bootstrap_iterations,
            "odds_source": "odds_snapshots.WIN(final latest; 9999.9 sentinel excluded)",
            "predictions_path": str(predictions_path),
        },
        seed=20260827,
        train_period=candidate_run.train_period,
        valid_period=candidate_run.valid_period,
        test_period="2026-06-01~",
        metrics=metrics,
        notes=f"Gate G2 {decision.status}; final-odds ex-post only; report={report_path}",
    )
    record_run(gate_run)
    print(f"Gate G2 {decision.status}: run_id={gate_run_id}")
    print(
        f"valid β(model)={fit.model_coefficient:.4f}, "
        f"cluster SE={fit.model_standard_error:.4f}, p(one-sided)={fit.model_p_value_one_sided:.6g}"
    )
    print(
        f"test LL 시장={test_market_metrics['log_loss']:.6f}, "
        f"혼합={test_mixed_metrics['log_loss']:.6f}, "
        f"bootstrap 95% CI=[{ll_bootstrap.lower_95:+.6f}, {ll_bootstrap.upper_95:+.6f}]"
    )
    if roi_bootstrap is not None:
        print(
            f"θ={selected_threshold:.2f}, bets={test_backtest.n_bets}, "
            f"flat ROI={test_backtest.flat_roi:+.2%}, "
            f"bootstrap median={roi_bootstrap.median:+.2%}, "
            f"95% CI=[{roi_bootstrap.lower_95:+.2%}, {roi_bootstrap.upper_95:+.2%}]"
        )
    print("주의: 확정배당 사후평가이며 구매시점 수익성 증거가 아닙니다.")
    print(f"report: {report_path}")
    return 0 if decision.status == "PASS" else 1


def run_ordered_triple_value_command(
    run_id: str,
    dataset_dir: str,
    *,
    report_dir: str = "data/experiments/reports",
    top_n: int = 4,
    ev_thresholds: list[float] | None = None,
    bootstrap_iterations: int = 1_000,
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import assign_split
    from horse_racing.analysis.experiments import (
        ModelRun,
        get_run,
        new_run_id,
        record_run,
    )
    from horse_racing.analysis.ordered_triple import (
        DEFAULT_EV_THRESHOLDS,
        ORDERED_TRIPLE_POOL,
        backtest_ordered_triple_value,
        fetch_ordered_triple_odds,
        prepare_ordered_triple_value,
        render_ordered_triple_report,
    )

    if top_n < 3:
        print("top-n은 최소 3이어야 합니다.", file=sys.stderr)
        return 2
    if bootstrap_iterations < 100:
        print("bootstrap은 최소 100회가 필요합니다.", file=sys.stderr)
        return 2
    thresholds = sorted(set(ev_thresholds or DEFAULT_EV_THRESHOLDS))
    if any(value < 0 for value in thresholds):
        print("EV 임계값은 0 이상이어야 합니다.", file=sys.stderr)
        return 2
    candidate_run = get_run(run_id)
    if candidate_run is None:
        print(f"알 수 없는 후보 run_id: {run_id}", file=sys.stderr)
        return 1
    artifact_path_raw = candidate_run.hyperparameters.get("artifact_path")
    if not artifact_path_raw:
        print("후보 run에 artifact 경로가 없습니다.", file=sys.stderr)
        return 1
    artifact_dir = Path(str(artifact_path_raw)).parent
    predictions_path = artifact_dir / "predictions_valid.parquet"
    if not predictions_path.exists():
        print(f"valid prediction 파일 없음: {predictions_path}", file=sys.stderr)
        return 1

    version, as_of_policy = candidate_run.dataset_version.split("/", maxsplit=1)
    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    frame = (
        assign_split(pl.read_parquet(dataset_path)).filter(pl.col("split") == "valid").drop("split")
    )
    predictions = pl.read_parquet(predictions_path)
    with SessionLocal() as session:
        odds = fetch_ordered_triple_odds(session)
    scored = prepare_ordered_triple_value(frame, predictions, odds, top_n=top_n)
    results = [
        backtest_ordered_triple_value(
            scored,
            threshold=value,
            bootstrap_iterations=bootstrap_iterations,
            seed=20260901 + index,
        )
        for index, value in enumerate(thresholds)
    ]

    diagnostic_run_id = new_run_id()
    report = render_ordered_triple_report(
        scored,
        results,
        candidate_run_id=run_id,
        top_n=top_n,
    )
    report_path = (
        Path(report_dir) / f"ordered_triple_value_{version}_{as_of_policy}_{diagnostic_run_id}.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    combinations_path = artifact_dir / f"ordered_triple_value_{diagnostic_run_id}.parquet"
    scored.write_parquet(combinations_path)

    metrics: dict[str, float | None] = {}
    for result in results:
        threshold_label = str(result.threshold).replace(".", "p")
        prefix = f"valid_ev_{threshold_label}"
        metrics.update(
            {
                f"{prefix}_bets": float(result.n_bets),
                f"{prefix}_races": float(result.n_races_bet),
                f"{prefix}_roi": result.flat_roi,
                f"{prefix}_profit": result.flat_profit,
                f"{prefix}_race_hit_rate": result.race_hit_rate,
                f"{prefix}_bootstrap_lower_95": (
                    result.roi_bootstrap.lower_95 if result.roi_bootstrap else None
                ),
                f"{prefix}_bootstrap_upper_95": (
                    result.roi_bootstrap.upper_95 if result.roi_bootstrap else None
                ),
            }
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record_run(
        ModelRun(
            run_id=diagnostic_run_id,
            dataset_version=candidate_run.dataset_version,
            dataset_manifest={
                key: manifest.get(key)
                for key in (
                    "version",
                    "as_of_policy",
                    "row_count",
                    "race_count",
                    "feature_hash",
                )
            },
            feature_names=candidate_run.feature_names,
            model_type="ordered_triple_value_diagnostic",
            hyperparameters={
                "candidate_run_id": run_id,
                "top_n": top_n,
                "ev_thresholds": thresholds,
                "bootstrap_iterations": bootstrap_iterations,
                "probability_model": "Plackett-Luce from calibrated P(win)",
                "odds_source": (
                    f"odds_snapshots.{ORDERED_TRIPLE_POOL}(final latest; 9999.9 sentinel excluded)"
                ),
                "combinations_path": str(combinations_path),
                "report_path": str(report_path),
            },
            seed=20260901,
            train_period=candidate_run.train_period,
            valid_period=candidate_run.valid_period,
            test_period="",
            metrics=metrics,
            notes=(
                "상위 N두 순서 3두 PL 확률과 확정배당 EV 사후진단; "
                f"실시간 구매시점 배당 아님; report={report_path}"
            ),
        )
    )
    print(f"ordered-triple 진단 완료: run_id={diagnostic_run_id}")
    for result in results:
        bootstrap = result.roi_bootstrap
        interval = (
            f"[{bootstrap.lower_95:+.2%}, {bootstrap.upper_95:+.2%}]"
            if bootstrap is not None
            else "—"
        )
        print(
            f"EV>{result.threshold:.2f}: bets={result.n_bets}, "
            f"races={result.n_races_bet}, ROI={result.flat_roi:+.2%}, "
            f"95% CI={interval}"
        )
    print("주의: 확정배당 사후평가이며 구매시점 수익성 증거가 아닙니다.")
    print(f"report: {report_path}")
    print(f"combinations: {combinations_path}")
    return 0


def publish_predictions_command(
    run_id: str,
    predictions_file: str,
    feature_cutoff: str,
    *,
    publication_mode: str = "live",
    confirm_historical: bool = False,
    notes: str | None = None,
) -> int:
    import polars as pl

    from horse_racing.analysis.experiments import get_run
    from horse_racing.services.prediction_ledger import (
        PredictionLedgerError,
        PredictionModelMetadata,
        publish_predictions,
        sha256_file,
    )

    if publication_mode == "historical" and not confirm_historical:
        print(
            "historical 발행에는 --confirm-historical이 필요합니다. 공개 실적과 분리됩니다.",
            file=sys.stderr,
        )
        return 2
    run = get_run(run_id)
    if run is None:
        print(f"알 수 없는 model run_id: {run_id}", file=sys.stderr)
        return 1
    artifact_raw = run.hyperparameters.get("artifact_path")
    if not artifact_raw:
        print("model run에 artifact 경로가 없습니다.", file=sys.stderr)
        return 1
    artifact_path = Path(str(artifact_raw))
    if not artifact_path.exists():
        print(f"model artifact 없음: {artifact_path}", file=sys.stderr)
        return 1
    prediction_path = Path(predictions_file)
    if not prediction_path.exists():
        print(f"prediction 파일 없음: {prediction_path}", file=sys.stderr)
        return 1
    if prediction_path.suffix.lower() == ".parquet":
        predictions = pl.read_parquet(prediction_path)
    elif prediction_path.suffix.lower() in {".csv", ".tsv"}:
        predictions = pl.read_csv(
            prediction_path,
            separator="\t" if prediction_path.suffix.lower() == ".tsv" else ",",
        )
    else:
        print("prediction 파일은 parquet/csv/tsv만 지원합니다.", file=sys.stderr)
        return 2
    try:
        cutoff_at_ms = parse_timestamp_ms(feature_cutoff)
        version, as_of_policy = run.dataset_version.split("/", maxsplit=1)
        with SessionLocal() as session:
            summary = publish_predictions(
                session,
                predictions,
                metadata=PredictionModelMetadata(
                    experiment_run_id=run.run_id,
                    model_type=run.model_type,
                    dataset_version=version,
                    as_of_policy=as_of_policy,
                    feature_hash=run.feature_hash,
                    model_artifact_sha256=sha256_file(artifact_path),
                ),
                feature_cutoff_at_ms=cutoff_at_ms,
                publication_mode=publication_mode,
                notes=notes,
            )
    except (PredictionLedgerError, ValueError) as exc:
        print(f"예측 발행 실패: {exc}", file=sys.stderr)
        return 1
    print(f"예측 원장 발행 완료: public_id={summary.public_id}")
    print(
        f"mode={summary.publication_mode}, date={summary.race_date_local}, "
        f"races={summary.race_count}, entries={summary.entry_count}"
    )
    print(f"predictions_sha256={summary.predictions_sha256}")
    return 0


def build_prediction_frame_command(
    run_id: str,
    race_date: str,
    *,
    publication_mode: str = "live",
    race_ids: list[int] | None = None,
    output_dir: str = "data/predictions",
) -> int:
    """Build and persist the exact label-free frame expected by one fixed run."""
    from horse_racing.analysis.experiments import get_run
    from horse_racing.analysis.prediction_frame import (
        PredictionFrameError,
        build_prediction_frame,
        validate_prediction_timing,
    )

    run = get_run(run_id)
    if run is None:
        print(f"알 수 없는 model run_id: {run_id}", file=sys.stderr)
        return 1
    try:
        _, as_of_policy = run.dataset_version.split("/", maxsplit=1)
        with SessionLocal() as session:
            result = build_prediction_frame(
                session,
                race_date=race_date,
                as_of_policy=as_of_policy,
                expected_feature_names=run.feature_names,
                publication_mode=publication_mode,
                race_ids=race_ids,
            )
        cutoff_at_ms = time.time_ns() // 1_000_000
        if publication_mode == "live":
            validate_prediction_timing(result.frame, at_ms=cutoff_at_ms)
    except (PredictionFrameError, ValueError) as exc:
        print(f"prediction frame 생성 실패: {exc}", file=sys.stderr)
        return 1

    target_dir = Path(output_dir) / result.race_date_local.replace("-", "")
    target_dir.mkdir(parents=True, exist_ok=True)
    frame_path = target_dir / f"features_{run_id}_{cutoff_at_ms}.parquet"
    manifest_path = target_dir / f"features_{run_id}_{cutoff_at_ms}.json"
    result.frame.write_parquet(frame_path)
    manifest_path.write_text(
        json.dumps(
            {
                "experiment_run_id": run_id,
                "race_date_local": result.race_date_local,
                "publication_mode": publication_mode,
                "as_of_policy": result.as_of_policy,
                "feature_cutoff_at_ms": cutoff_at_ms,
                "feature_names": result.feature_names,
                "feature_hash": result.feature_hash,
                "race_count": result.frame.select("race_id").n_unique(),
                "entry_count": result.frame.height,
                "excluded_small_field_race_ids": result.excluded_small_field_race_ids,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"prediction frame 생성 완료: {frame_path}")
    print(
        f"date={result.race_date_local}, races={result.frame.select('race_id').n_unique()}, "
        f"entries={result.frame.height}, features={len(result.feature_names)}"
    )
    print(f"feature_hash={result.feature_hash}")
    if result.excluded_small_field_race_ids:
        print(f"최소 두수 미달 제외 race_id={result.excluded_small_field_race_ids}")
    print(f"manifest: {manifest_path}")
    return 0


def predict_and_publish_command(
    run_id: str,
    race_date: str,
    *,
    publication_mode: str = "live",
    confirm_historical: bool = False,
    race_ids: list[int] | None = None,
    output_dir: str = "data/predictions",
    notes: str | None = None,
    probability_calibration_path: str | None = None,
) -> int:
    """Build features, run a fixed artifact, and atomically publish probabilities."""
    from horse_racing.analysis.experiments import get_run
    from horse_racing.analysis.prediction_frame import (
        PROBABILITY_COHERENCE_METHOD,
        PredictionFrameError,
        build_prediction_frame,
        predict_model_run,
        validate_prediction_timing,
    )
    from horse_racing.services.prediction_ledger import (
        PredictionLedgerError,
        PredictionModelMetadata,
        publish_predictions,
        sha256_file,
    )

    if publication_mode == "historical" and not confirm_historical:
        print(
            "historical 발행에는 --confirm-historical이 필요합니다. 공개 실적과 분리됩니다.",
            file=sys.stderr,
        )
        return 2
    run = get_run(run_id)
    if run is None:
        print(f"알 수 없는 model run_id: {run_id}", file=sys.stderr)
        return 1
    try:
        version, as_of_policy = run.dataset_version.split("/", maxsplit=1)
        with SessionLocal() as session:
            built = build_prediction_frame(
                session,
                race_date=race_date,
                as_of_policy=as_of_policy,
                expected_feature_names=run.feature_names,
                publication_mode=publication_mode,
                race_ids=race_ids,
            )
            calibration_path = (
                Path(probability_calibration_path)
                if probability_calibration_path is not None
                else None
            )
            predictions, artifact_path = predict_model_run(
                run,
                built.frame,
                probability_calibration_path=calibration_path,
            )
            cutoff_at_ms = time.time_ns() // 1_000_000
            if publication_mode == "live":
                validate_prediction_timing(built.frame, at_ms=cutoff_at_ms)

            target_dir = (
                Path(output_dir)
                / built.race_date_local.replace("-", "")
                / f"{cutoff_at_ms}_{run_id[:8]}"
            )
            target_dir.mkdir(parents=True, exist_ok=True)
            frame_path = target_dir / "features.parquet"
            predictions_path = target_dir / "predictions.parquet"
            built.frame.write_parquet(frame_path)
            predictions.write_parquet(predictions_path)
            audit_note = f"inference_artifacts={target_dir}"
            if calibration_path is not None:
                audit_note += f"; probability_calibration={calibration_path}"
            publication_notes = f"{notes}; {audit_note}" if notes else audit_note
            summary = publish_predictions(
                session,
                predictions,
                metadata=PredictionModelMetadata(
                    experiment_run_id=run.run_id,
                    model_type=run.model_type,
                    dataset_version=version,
                    as_of_policy=as_of_policy,
                    feature_hash=run.feature_hash,
                    model_artifact_sha256=sha256_file(artifact_path),
                ),
                feature_cutoff_at_ms=cutoff_at_ms,
                publication_mode=publication_mode,
                notes=publication_notes,
            )
            manifest_path = target_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "public_id": summary.public_id,
                        "experiment_run_id": run_id,
                        "race_date_local": built.race_date_local,
                        "publication_mode": publication_mode,
                        "as_of_policy": as_of_policy,
                        "feature_cutoff_at_ms": cutoff_at_ms,
                        "feature_hash": built.feature_hash,
                        "probability_coherence": PROBABILITY_COHERENCE_METHOD,
                        "predictions_sha256": summary.predictions_sha256,
                        "race_count": summary.race_count,
                        "entry_count": summary.entry_count,
                        "excluded_small_field_race_ids": built.excluded_small_field_race_ids,
                        "model_artifact": str(artifact_path),
                        "probability_calibration_artifact": (
                            str(calibration_path) if calibration_path is not None else None
                        ),
                        "probability_calibration_sha256": (
                            sha256_file(calibration_path) if calibration_path is not None else None
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    except (PredictionFrameError, PredictionLedgerError, ValueError) as exc:
        print(f"예측·발행 실패: {exc}", file=sys.stderr)
        return 1

    print(f"고정 모델 예측·원장 발행 완료: public_id={summary.public_id}")
    print(
        f"mode={summary.publication_mode}, date={summary.race_date_local}, "
        f"races={summary.race_count}, entries={summary.entry_count}"
    )
    print(f"predictions_sha256={summary.predictions_sha256}")
    print(f"audit artifacts: {target_dir}")
    return 0


def settle_predictions_command(public_id: str | None = None) -> int:
    from sqlalchemy import select

    from horse_racing.db.models import PredictionRun, PredictionSettlement
    from horse_racing.services.prediction_ledger import (
        PredictionLedgerError,
        settle_prediction_run,
    )

    with SessionLocal() as session:
        if public_id is not None:
            targets = [public_id]
        else:
            targets = list(
                session.scalars(
                    select(PredictionRun.public_id)
                    .outerjoin(
                        PredictionSettlement,
                        PredictionSettlement.prediction_run_id == PredictionRun.id,
                    )
                    .where(PredictionSettlement.id.is_(None))
                    .order_by(PredictionRun.published_at_ms)
                )
            )
        if not targets:
            print("미정산 prediction이 없습니다.")
            return 0
        settled = 0
        pending = 0
        for target in targets:
            try:
                summary = settle_prediction_run(session, target)
            except PredictionLedgerError as exc:
                if public_id is not None:
                    print(f"예측 정산 실패: {exc}", file=sys.stderr)
                    return 1
                pending += 1
                continue
            settled += 1
            print(
                f"정산 완료: prediction={target}, settlement={summary.public_id}, "
                f"races={summary.race_count}, excluded={summary.excluded_races}, "
                f"win_LL={summary.win_log_loss:.6f}"
            )
        print(f"정산 요약: completed={settled}, pending={pending}")
        return 0


def list_predictions_command(publication_mode: str = "all") -> int:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from horse_racing.db.models import PredictionRun

    with SessionLocal() as session:
        statement = select(PredictionRun).options(
            selectinload(PredictionRun.predictions),
            selectinload(PredictionRun.settlement),
        )
        if publication_mode != "all":
            statement = statement.where(PredictionRun.publication_mode == publication_mode)
        runs = session.scalars(statement.order_by(PredictionRun.published_at_ms.desc())).all()
    if not runs:
        print("발행된 prediction이 없습니다.")
        return 0
    headers = ["public_id", "mode", "race_date", "races", "entries", "status", "win_LL"]
    rows: list[list[str]] = []
    for run in runs:
        settlement = run.settlement
        rows.append(
            [
                run.public_id,
                run.publication_mode,
                run.race_date_local.isoformat(),
                str(len({item.race_id for item in run.predictions})),
                str(len(run.predictions)),
                "settled" if settlement else "published",
                _format_cell(settlement.win_log_loss if settlement else None),
            ]
        )
    _print_aligned_table(headers, rows)
    return 0


def verify_predictions_command(public_id: str) -> int:
    from horse_racing.services.prediction_ledger import (
        PredictionLedgerError,
        verify_prediction_hash,
    )

    with SessionLocal() as session:
        try:
            verified = verify_prediction_hash(session, public_id)
        except PredictionLedgerError as exc:
            print(f"검증 실패: {exc}", file=sys.stderr)
            return 1
    print(f"prediction hash: {'VERIFIED' if verified else 'MISMATCH'}")
    return 0 if verified else 1


def list_model_runs(metric: str | None = None, *, ledger_path: Path | None = None) -> int:
    from horse_racing.analysis.experiments import load_runs, sort_runs

    runs = load_runs(ledger_path=ledger_path)
    if not runs:
        print("기록된 모델 실험이 없습니다.")
        return 0

    if metric:
        runs = sort_runs(runs, metric, descending=True)
    else:
        runs = sorted(runs, key=lambda item: item.created_at_ms, reverse=True)

    metric_names = sorted({name for run in runs for name in run.metrics})
    if metric:
        metric_names = [metric] + [name for name in metric_names if name != metric]

    headers = ["run_id", "created_at", "model_type", "dataset_version", *metric_names]
    rows: list[list[str]] = []
    for run in runs:
        created = datetime.fromtimestamp(run.created_at_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
        row = [run.run_id, created, run.model_type, run.dataset_version]
        for name in metric_names:
            value = run.metrics.get(name)
            row.append(_format_cell(value))
        rows.append(row)
    _print_aligned_table(headers, rows)
    return 0


def compare_model_runs(run_ids: list[str], *, ledger_path: Path | None = None) -> int:
    from horse_racing.analysis.experiments import compare_runs, get_run, values_differ

    if len(run_ids) < 2:
        print("비교하려면 2개 이상의 run_id가 필요합니다.", file=sys.stderr)
        return 2

    runs = []
    missing: list[str] = []
    for run_id in run_ids:
        run = get_run(run_id, ledger_path=ledger_path)
        if run is None:
            missing.append(run_id)
        else:
            runs.append(run)
    if missing:
        print(f"알 수 없는 run_id: {', '.join(missing)}", file=sys.stderr)
        return 1

    comparison = compare_runs(runs)
    columns = comparison.run_ids

    identity_rows = [
        ["model_type", *[comparison.model_types[run_id] for run_id in columns]],
        ["dataset_version", *[comparison.dataset_versions[run_id] for run_id in columns]],
        ["seed", *[str(comparison.seeds[run_id]) for run_id in columns]],
        ["feature_hash", *[comparison.feature_hashes[run_id] for run_id in columns]],
    ]
    print("실험 비교")
    _print_aligned_table(["field", *columns], identity_rows)
    print("feature_hash 일치: " + ("no" if comparison.feature_hash_mismatch else "yes"))

    if comparison.metrics:
        print()
        print("지표")
        metric_rows: list[list[str]] = []
        for name, values in comparison.metrics.items():
            marker = "DIFF" if values_differ(values) else ""
            metric_rows.append(
                [name, *[_format_cell(values[run_id]) for run_id in columns], marker]
            )
        _print_aligned_table(["metric", *columns, ""], metric_rows)

    if comparison.hyperparameters:
        print()
        print("하이퍼파라미터")
        hparam_rows: list[list[str]] = []
        for name, values in comparison.hyperparameters.items():
            marker = "DIFF" if values_differ(values) else ""
            hparam_rows.append(
                [name, *[_format_cell(values[run_id]) for run_id in columns], marker]
            )
        _print_aligned_table(["param", *columns, ""], hparam_rows)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="horse-racing")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("db-info", help="Show local SQLite database information")
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
        "--meets", nargs="+", type=int, choices=sorted(MEET_METADATA), default=[1, 2, 3]
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
        choices=(1, 2, 3),
        default=[1, 2, 3],
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
        choices=(1, 2, 3),
        default=[1, 2, 3],
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
    args = parser.parse_args()

    if args.command == "db-info":
        return db_info()
    if args.command == "collect-entry-sheet":
        try:
            return collect_entry_sheet(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-race-day":
        try:
            return collect_race_day(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-schedule":
        try:
            return collect_schedule(args.dates, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"일정 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-gate-numbers":
        try:
            return collect_gate_numbers(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출발번호 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-gates":
        try:
            return backfill_gate_numbers(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출발번호 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-results":
        try:
            return backfill_results(
                args.start,
                args.end,
                args.meets,
                args.page_size,
                not args.skip_dividends,
            )
        except (KraApiError, ValueError) as exc:
            print(f"백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-dividends":
        try:
            return backfill_dividends(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"확정배당 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-race-sections":
        try:
            return collect_race_sections(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"구간기록 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-sections":
        try:
            return backfill_sections(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"구간기록 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-ratings":
        try:
            return collect_ratings(args.date, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"레이팅 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-weights":
        try:
            return collect_weights(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"체중 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-training":
        try:
            return collect_training(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"훈련 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-medical":
        try:
            return collect_medical(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"진료 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-horse-profiles":
        try:
            return collect_horse_profiles(
                args.meets,
                args.page_size,
                args.include_inactive,
                args.date,
            )
        except (KraApiError, ValueError) as exc:
            print(f"말 상세 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-weights":
        try:
            return backfill_weights(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"체중 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-training":
        try:
            return backfill_training(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"훈련 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-medical":
        try:
            return backfill_medical(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"진료 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-jockey-changes":
        try:
            return collect_jockey_changes(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"기수변경 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-scratches":
        try:
            return collect_scratches(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출전취소 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-equipment":
        try:
            return collect_equipment(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"장구·폐출혈 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-grade-changes":
        try:
            return collect_grade_changes(args.meets, args.page_size, args.date)
        except (KraApiError, ValueError) as exc:
            print(f"등급변동 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-start-training":
        try:
            return collect_start_training(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출발훈련 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-steward-reports":
        try:
            return collect_steward_reports(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"심판리포트 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-jockey-changes":
        try:
            return backfill_jockey_changes(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"기수변경 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-scratches":
        try:
            return backfill_scratches(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출전취소 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-equipment":
        try:
            return backfill_equipment(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"장구·폐출혈 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-start-training":
        try:
            return backfill_start_training(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"출발훈련 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-steward-reports":
        try:
            return backfill_steward_reports(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"심판리포트 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-running-trials":
        try:
            return collect_running_trials(args.start, args.end, args.meets)
        except (KraTextError, ValueError) as exc:
            print(f"주행심사 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "download-text-archive":
        try:
            return download_text_archive_command(
                args.file_type,
                args.code_name,
                args.start,
                args.end,
                args.meets,
                args.max_pages,
                args.max_files,
                args.delay_ms,
            )
        except (KraTextError, ValueError) as exc:
            print(f"Text 자료실 다운로드 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "ingest-text-results":
        try:
            return ingest_text_results_command(
                args.start,
                args.end,
                args.meets,
                validate_only=args.validate_only,
                allow_synthetic_horses=args.allow_synthetic_horses,
            )
        except (KraTextError, ValueError) as exc:
            print(f"dacom11 적재 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "serve-dashboard":
        return serve_dashboard(args.host, args.port, args.reload)
    if args.command == "repair-entry-links":
        return repair_entry_links()
    if args.command == "repair-planned-weather":
        return repair_planned_weather_command()
    if args.command == "sync-daily":
        try:
            return sync_daily(
                args.mode,
                as_of=args.as_of,
                meets=args.meets,
                schedule_days=args.schedule_days,
                result_lookback_days=args.result_lookback_days,
                page_size=args.page_size,
                include_dividends=not args.skip_dividends,
                dry_run=args.dry_run,
            )
        except (KraApiError, ValueError) as exc:
            print(f"일일 동기화 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "sync-latest":
        return sync_latest(
            as_of=args.as_of,
            meets=args.meets,
            schedule_days=args.schedule_days,
            recent_lookback_days=args.recent_lookback_days,
            history_lookback_days=args.history_lookback_days,
            trial_lookback_days=args.trial_lookback_days,
            page_size=args.page_size,
            include_dividends=not args.skip_dividends,
            dry_run=args.dry_run,
        )
    if args.command == "build-dataset":
        return build_dataset_command(
            args.version,
            args.as_of,
            args.start,
            args.end,
            args.output_dir,
            with_features=not args.no_features,
            feature_set=args.feature_set,
        )
    if args.command == "write-feature-catalog":
        return write_feature_catalog_command(args.output)
    if args.command == "run-baselines":
        return run_baselines_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            include_test=args.include_test,
        )
    if args.command == "train-model":
        return train_model_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            calibration=args.calibration,
            profile=args.profile,
        )
    if args.command == "run-walk-forward":
        return run_walk_forward_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            years=args.years,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            calibration=args.calibration,
            profile=args.profile,
            model_kind=args.model,
            relevance_mode=args.relevance_mode,
            margin_performance=args.margin_performance,
        )
    if args.command == "train-ranking":
        return train_ranking_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            profile=args.profile,
            calibration_objective=args.calibration_objective,
            relevance_depth=args.relevance_depth,
            relevance_mode=args.relevance_mode,
            margin_performance=args.margin_performance,
        )
    if args.command == "train-racefit":
        return train_racefit_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            profile=args.profile,
        )
    if args.command == "train-catboost":
        return train_catboost_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            calibration=args.calibration,
            profile=args.profile,
        )
    if args.command == "run-ablation":
        return run_ablation_command(
            args.version,
            args.as_of,
            args.dataset_dir,
            report_dir=args.report_dir,
            seed=args.seed,
            profile=args.profile,
        )
    if args.command == "build-ensemble":
        configured_weights = {
            label: values
            for label, values in {
                "win": args.win_weights,
                "top2": args.top2_weights,
                "top3": args.top3_weights,
                "top4": args.top4_weights,
                "top5": args.top5_weights,
            }.items()
            if values is not None
        }
        return build_ensemble_command(
            args.run_ids,
            args.dataset_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            allow_cross_dataset=args.allow_cross_dataset,
            target_member_weights=configured_weights or None,
            reference_version=args.reference_version,
            reference_as_of=args.reference_as_of,
        )
    if args.command == "run-g1-gate":
        return run_g1_gate_command(
            args.run_id,
            args.dataset_dir,
            report_dir=args.report_dir,
            confirm_test=args.confirm_test,
        )
    if args.command == "run-g2-gate":
        return run_g2_gate_command(
            args.run_id,
            args.dataset_dir,
            report_dir=args.report_dir,
            confirm_test_market=args.confirm_test_market,
            bootstrap_iterations=args.bootstrap_iterations,
        )
    if args.command == "run-ordered-triple-value":
        return run_ordered_triple_value_command(
            args.run_id,
            args.dataset_dir,
            report_dir=args.report_dir,
            top_n=args.top_n,
            ev_thresholds=args.ev_thresholds,
            bootstrap_iterations=args.bootstrap_iterations,
        )
    if args.command == "publish-predictions":
        return publish_predictions_command(
            args.run_id,
            args.predictions_file,
            args.feature_cutoff,
            publication_mode=args.mode,
            confirm_historical=args.confirm_historical,
            notes=args.notes,
        )
    if args.command == "build-prediction-frame":
        return build_prediction_frame_command(
            args.run_id,
            args.date,
            publication_mode=args.mode,
            race_ids=args.race_ids,
            output_dir=args.output_dir,
        )
    if args.command == "predict-and-publish":
        return predict_and_publish_command(
            args.run_id,
            args.date,
            publication_mode=args.mode,
            confirm_historical=args.confirm_historical,
            race_ids=args.race_ids,
            output_dir=args.output_dir,
            notes=args.notes,
            probability_calibration_path=args.probability_calibration,
        )
    if args.command == "settle-predictions":
        return settle_predictions_command(args.public_id)
    if args.command == "list-predictions":
        return list_predictions_command(args.mode)
    if args.command == "verify-predictions":
        return verify_predictions_command(args.public_id)
    if args.command == "evaluate-model":
        return evaluate_model_command(
            args.run_id,
            args.dataset_dir,
            include_test=args.include_test,
            report_dir=args.report_dir,
        )
    if args.command == "list-model-runs":
        return list_model_runs(args.metric)
    if args.command == "compare-runs":
        return compare_model_runs(args.run_ids)
    parser.error(f"unknown command: {args.command}")
    return 2
