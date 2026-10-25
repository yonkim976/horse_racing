"""Bounded, allowlisted SELECTs. Absence is a suspicion, not a source-side verdict."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, func, or_, select, text

from horse_racing.db.models import (
    Horse,
    HorseMedical,
    HorseStartTraining,
    HorseSwimTraining,
    HorseTraining,
    IngestionRun,
    Race,
    Racecourse,
    RaceEntry,
    RacePassingGroup,
    RaceResult,
    RaceSectionTime,
    RaceStewardReport,
    RunningTrial,
    RunningTrialResult,
    SourceDocument,
)
from horse_racing.services.training_read import (
    start_training_display_labels,
    training_display_fields,
)

KST = ZoneInfo("Asia/Seoul")
MEETS = {1: "서울", 2: "제주", 3: "영남", 4: "영천"}
# These are documented schedules, NOT a claim that launchd/Scheduler is alive.
CATEGORIES = (
    (
        "cards",
        "주간 출마표",
        ("weekly_entry_cards", "entry_sheet"),
        "수 15:10·16:10 로컬 / 17:10·18:10·19:10 Google",
        10 * 24,
    ),
    ("live", "경주 당일 변경·결과", ("local_live_race_day",), "개최일 조건부 · 2분 간격", None),
    ("training", "일반조교", ("horse_training",), "매일 14:30 Google · 최근 7일", 48),
    (
        "start",
        "출발조교",
        ("horse_start_training", "horse_start_training_website"),
        "매일 조교 작업에 포함 · 하루 여러 회차 보존",
        48,
    ),
    ("swim", "수영조교", ("horse_swim_training",), "매일 조교 작업에 포함", 48),
    ("hill", "언덕조교", ("horse_hill_training",), "매일 조교 작업에 포함", 48),
    ("training_job", "조교 전체 실행", ("daily_training_job",), "매일 14:30 Google", 48),
    ("medical", "진료·진단명 연결", ("horse_medical",), "매일 18:10 로컬 · 최근 14일", 48),
    (
        "canonical",
        "심판·구간·통과조",
        ("canonical_post_race_scan", "canonical_post_race_refresh", "canonical_post_race"),
        "매일 21:00 / 다음 날 09:15 로컬 · 최근 14일",
        48,
    ),
    (
        "profiles",
        "말 기본정보",
        ("horse_profiles",),
        "수 17:40 / 마지막 개최일 18:40 로컬",
        10 * 24,
    ),
    ("trainers", "조교사 소속·상태", ("trainer_catalog_refresh",), "기본정보 갱신과 함께", 10 * 24),
    ("trials", "주행심사", ("running_trials",), "목 15:10·19:10 / 금 09:10 로컬", 10 * 24),
    ("grades", "승급·강급", ("horse_grade_changes",), "자동화 보류 · 마지막 수동 수집 이력", None),
    (
        "dividends",
        "확정 배당",
        ("local_post_race_dividends",),
        "경주 종료 후 보완 · 실시간 변동 배당 아님",
        None,
    ),
    ("repair", "결과 정정·누락 보완", ("local_post_race_repair",), "로컬 경주 후 보완", None),
)


def now_kst():
    return datetime.now(KST)


def serialize_run(row):
    # Raw error messages can contain credential-bearing URLs or request parameters.
    # Report the error flag only. No untrusted collector log is exposed to a browser.
    return {
        "id": row.id,
        "data_type": row.data_type,
        "source": row.source,
        "started_at_ms": row.started_at_ms,
        "completed_at_ms": row.completed_at_ms,
        "status": row.status,
        "records_fetched": row.records_fetched,
        "records_written": row.records_written,
        "has_error": bool(row.error_message),
        "error_note": "오류 원문은 비밀값 보호를 위해 표시하지 않습니다."
        if row.error_message
        else None,
    }


def overview(session, now=None):
    now = now or now_kst()
    # ingestion_runs is small (~30k), unlike multi-million-row observation tables.
    # Order by actual start timestamp, not just insertion ID (historical imports exist).
    ranked = select(
        IngestionRun.id,
        func.row_number()
        .over(
            partition_by=IngestionRun.data_type,
            order_by=(IngestionRun.started_at_ms.desc(), IngestionRun.id.desc()),
        )
        .label("n"),
    ).subquery()
    latest = list(
        session.scalars(
            select(IngestionRun).join(ranked, ranked.c.id == IngestionRun.id).where(ranked.c.n == 1)
        )
    )
    successes = (
        select(
            IngestionRun.id,
            func.row_number()
            .over(
                partition_by=IngestionRun.data_type,
                order_by=(IngestionRun.started_at_ms.desc(), IngestionRun.id.desc()),
            )
            .label("n"),
        )
        .where(IngestionRun.status == "completed")
        .subquery()
    )
    successful = list(
        session.scalars(
            select(IngestionRun)
            .join(successes, successes.c.id == IngestionRun.id)
            .where(successes.c.n == 1)
        )
    )
    categories = []
    for key, name, types, schedule, grace_hours in CATEGORIES:
        last = max(
            (r for r in latest if r.data_type in types),
            key=lambda r: (r.started_at_ms, r.id),
            default=None,
        )
        success = max(
            (r for r in successful if r.data_type in types),
            key=lambda r: (r.started_at_ms, r.id),
            default=None,
        )
        age_hours = (now.timestamp() * 1000 - last.started_at_ms) / 3600000 if last else None
        state = "unknown" if not last else last.status
        if last and state == "running" and age_hours > 1:
            state = "long_running"
        elif last and state == "completed" and grace_hours and age_hours > grace_hours:
            state = "stale"
        categories.append(
            {
                "key": key,
                "name": name,
                "types": types,
                "schedule": schedule,
                "state": state,
                "latest": serialize_run(last) if last else None,
                "latest_success": serialize_run(success) if success else None,
                "empty_response": bool(
                    last and last.status == "completed" and not last.records_fetched
                ),
            }
        )
    return {
        "checked_at": now.isoformat(),
        "categories": categories,
        "data_types": sorted(r.data_type for r in latest),
        "recent": [
            serialize_run(r)
            for r in sorted(latest, key=lambda r: (r.started_at_ms, r.id), reverse=True)[:8]
        ],
        "notes": [
            "일정은 운영 문서 기준입니다. 예약 프로세스의 현재 활성 상태를 조회한 결과가 아닙니다.",
            "갱신 지연 의심은 일일 48시간·주간 10일의 완충 기준입니다. 공식 API 제공 지연일 수 있습니다.",
            "최신 이력은 해당 데이터 종류의 마지막 실행입니다. 모든 날짜·지역의 수집 완료를 보장하지 않습니다.",
            "수집·기록 수는 수집기가 남긴 값입니다. records_written을 신규 행 수로 단정하지 않습니다.",
        ],
    }


def history(session, start, end, *, data_type=None, status=None, before_id=None):
    start_ms = int(datetime.combine(start, datetime.min.time(), KST).timestamp() * 1000)
    end_ms = int(
        datetime.combine(end + timedelta(days=1), datetime.min.time(), KST).timestamp() * 1000
    )
    stmt = select(IngestionRun).where(
        IngestionRun.started_at_ms >= start_ms, IngestionRun.started_at_ms < end_ms
    )
    if data_type:
        stmt = stmt.where(IngestionRun.data_type == data_type)
    if status:
        stmt = stmt.where(IngestionRun.status == status)
    if before_id:
        stmt = stmt.where(IngestionRun.id < before_id)
    rows = list(session.scalars(stmt.order_by(IngestionRun.id.desc()).limit(51)))
    return {
        "rows": [serialize_run(r) for r in rows[:50]],
        "has_more": len(rows) > 50,
        "next_cursor": rows[49].id if len(rows) > 50 else None,
        "order_note": "실행 ID 역순(저장 순서) · 날짜 필터는 실행 시작 시각 KST 기준",
    }


def run_detail(session, run_id):
    row = session.get(IngestionRun, run_id)
    if not row:
        return None
    docs = (
        session.execute(
            select(
                SourceDocument.id,
                SourceDocument.endpoint,
                SourceDocument.operation,
                SourceDocument.retrieved_at_ms,
                SourceDocument.http_status_code,
                SourceDocument.response_bytes,
                SourceDocument.sha256,
            )
            .where(SourceDocument.ingestion_run_id == run_id)
            .order_by(SourceDocument.id.desc())
            .limit(21)
        )
        .mappings()
        .all()
    )
    safe_docs = []
    for document in docs[:20]:
        item = dict(document)
        # Even an accidentally stored credential-bearing endpoint must not escape.
        item["endpoint"] = (document["endpoint"] or "").split("?", 1)[0].split("#", 1)[0]
        if "://" in item["endpoint"] or "@" in item["endpoint"]:
            item["endpoint"] = "경로 비공개"
        safe_docs.append(item)
    return {
        "run": serialize_run(row),
        "documents": safe_docs,
        "documents_truncated": len(docs) > 20,
    }


def horse_search(session, query):
    # Escape wildcard operators; users cannot turn this into an all-horse export.
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = (
        session.execute(
            select(Horse.id, Horse.kra_horse_id, Horse.name_ko, Horse.is_active)
            .where(
                or_(Horse.kra_horse_id == query, Horse.name_ko.ilike(escaped + "%", escape="\\"))
            )
            .order_by(Horse.name_ko, Horse.id)
            .limit(21)
        )
        .mappings()
        .all()
    )
    return {"rows": [dict(r) for r in rows[:20]], "has_more": len(rows) > 20}


def race_filters(start, end, meet):
    conditions = [Race.race_date_local.between(start, end)]
    if meet:
        conditions.append(Racecourse.kra_meet_code == meet)
    return conditions


def search_data(session, kind, start, end, *, horse_id=None, meet=None, race_no=None):
    """Date-only reads use date indexes; large care tables require a horse ID."""
    notes = []
    if kind in {"training", "medical", "start", "swim", "hill"}:
        if not horse_id:
            return {
                "rows": [],
                "has_more": False,
                "notes": [
                    "말을 먼저 선택하세요. 대용량 조교·진료 테이블의 전체 검색은 제공하지 않습니다."
                ],
            }
        horse = session.get(Horse, horse_id)
        if not horse:
            return {"rows": [], "has_more": False, "notes": ["등록되지 않은 내부 말 ID입니다."]}
        if kind == "hill":
            # Canonical deduplicated read view, NEVER raw metadata-version rows.
            rows = (
                session.execute(
                    text("""
                SELECT training_date_local AS date, farm_name, training_time_local,
                       f1_seconds, f2_seconds, f3_seconds, total_seconds, quality_status,
                       metadata_version_count
                FROM horse_hill_training_current
                WHERE horse_id = :horse AND training_date_local BETWEEN :start AND :end
                ORDER BY training_date_local DESC, id DESC LIMIT 101
            """),
                    {"horse": horse_id, "start": start, "end": end},
                )
                .mappings()
                .all()
            )
            return {
                "rows": [dict(r) for r in rows[:100]],
                "has_more": len(rows) > 100,
                "notes": [
                    "언덕조교는 메타데이터 중복을 제외한 current 뷰 기준입니다. 지역 필터는 적용하지 않습니다."
                ],
            }
        model = {
            "training": HorseTraining,
            "medical": HorseMedical,
            "start": HorseStartTraining,
            "swim": HorseSwimTraining,
        }[kind]
        day_col = model.clinic_date_local if kind == "medical" else model.training_date_local
        stmt = select(model).where(model.horse_id == horse_id, day_col.between(start, end))
        if meet:
            stmt = stmt.where(model.meet_code == meet)
        saved = list(session.scalars(stmt.order_by(day_col.desc(), model.id.desc()).limit(101)))
        labels = (
            training_display_fields(session, saved[:100])
            if kind == "training"
            else (start_training_display_labels(session, saved[:100]) if kind == "start" else {})
        )
        rows = []
        for r in saved[:100]:
            item = {
                "date": getattr(r, day_col.key),
                "meet": MEETS.get(r.meet_code),
                "horse": horse.name_ko,
                "horse_no": horse.kra_horse_id,
            }
            if kind == "training":
                item.update(
                    rider=labels[r.id]["rider_display_label"],
                    duration_seconds=r.duration_seconds,
                    start=r.started_at_raw,
                    end=r.ended_at_raw,
                    canter=labels[r.id]["canter_count_display"],
                    gallop=labels[r.id]["gallop_count_display"],
                    evidence=labels[r.id]["rider_source_note"],
                )
            elif kind == "medical":
                item.update(
                    hospital=r.hospital_name, diagnosis_1=r.diagnosis_1, diagnosis_2=r.diagnosis_2
                )
            elif kind == "start":
                item.update(
                    rider=labels[r.id],
                    occurrence=r.occurrence_no,
                    stable=r.stable_number,
                    remark=r.remark,
                )
            else:
                item.update(swim_count=r.swim_count, quality_status=r.quality_status)
            rows.append(item)
        notes = [
            "조회 0건만으로 누락이라고 판단하지 않습니다. 출발조교의 같은 날 여러 회차는 각각 표시합니다."
        ]
        return {"rows": rows, "has_more": len(saved) > 100, "notes": notes}
    conditions = race_filters(start, end, meet)
    if race_no:
        conditions.append(Race.race_number == race_no)
    base_columns = [
        Race.id.label("race_id"),
        Race.race_date_local.label("date"),
        Racecourse.name_ko.label("meet"),
        Race.race_number.label("race_no"),
    ]
    if kind == "stewards":
        stmt = (
            select(
                *base_columns,
                RaceStewardReport.judgement,
                RaceStewardReport.additional_judgement,
                RaceStewardReport.jockey_change_note,
            )
            .join(Racecourse, Racecourse.id == Race.racecourse_id)
            .join(
                RaceStewardReport,
                and_(
                    RaceStewardReport.meet_code == Racecourse.kra_meet_code,
                    RaceStewardReport.race_date_local == Race.race_date_local,
                    RaceStewardReport.race_number == Race.race_number,
                ),
            )
        )
    elif kind == "groups":
        stmt = select(*base_columns, RacePassingGroup.point_code, RacePassingGroup.notation_raw)
        stmt = stmt.join(Racecourse, Racecourse.id == Race.racecourse_id).join(
            RacePassingGroup, RacePassingGroup.race_id == Race.id
        )
    elif kind in {"entries", "sections"}:
        cols = base_columns + [RaceEntry.horse_number, Horse.kra_horse_id, Horse.name_ko]
        if kind == "entries":
            cols += [
                RaceEntry.rating,
                RaceEntry.body_weight_kg,
                RaceEntry.scratched,
                RaceResult.finish_position,
                RaceResult.finish_time_ms,
            ]
        else:
            cols += [
                RaceSectionTime.point_code,
                RaceSectionTime.time_kind,
                RaceSectionTime.elapsed_time_ms,
                RaceSectionTime.position_raw,
            ]
        stmt = (
            select(*cols)
            .select_from(Race)
            .join(Racecourse)
            .join(RaceEntry, RaceEntry.race_id == Race.id)
            .join(Horse, Horse.id == RaceEntry.horse_id)
        )
        stmt = (
            stmt.outerjoin(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
            if (kind == "entries")
            else stmt.join(RaceSectionTime, RaceSectionTime.race_entry_id == RaceEntry.id)
        )
        if horse_id:
            conditions.append(RaceEntry.horse_id == horse_id)
    elif kind == "trials":
        stmt = select(
            RunningTrial.trial_date_local.label("date"),
            RunningTrial.meet_code,
            RunningTrial.trial_race_number.label("race_no"),
            RunningTrialResult.horse_name_raw,
            RunningTrialResult.finish_position,
            RunningTrialResult.finish_time_ms,
            RunningTrialResult.judgement,
            RunningTrialResult.failure_reason,
        ).join(RunningTrialResult)
        conditions = [RunningTrial.trial_date_local.between(start, end)]
        if meet:
            conditions.append(RunningTrial.meet_code == meet)
        if horse_id:
            conditions.append(RunningTrialResult.horse_id == horse_id)
        if race_no:
            conditions.append(RunningTrial.trial_race_number == race_no)
        stmt = stmt.order_by(
            RunningTrial.trial_date_local.desc(),
            RunningTrial.trial_race_number,
            RunningTrialResult.id,
        )
    else:  # routes validate the fixed enum; no arbitrary table/column strings
        raise ValueError("unsupported_kind")
    if kind not in {"entries", "sections", "trials"} and horse_id:
        conditions.append(
            exists(
                select(RaceEntry.id).where(
                    RaceEntry.race_id == Race.id, RaceEntry.horse_id == horse_id
                )
            )
        )
    if kind != "trials":
        stmt = stmt.order_by(Race.race_date_local.desc(), Race.id.desc())
    if kind in {"entries", "sections"}:
        stmt = stmt.order_by(RaceEntry.horse_number)
    if kind == "sections":
        stmt = stmt.order_by(RaceSectionTime.point_code, RaceSectionTime.time_kind)
    if kind == "groups":
        stmt = stmt.order_by(RacePassingGroup.point_code)
    found = session.execute(stmt.where(*conditions).limit(101)).mappings().all()
    return {
        "rows": [dict(r) for r in found[:100]],
        "has_more": len(found) > 100,
        "notes": [
            "최대 100행 · 구간·통과조는 전환된 정본 테이블 기준입니다. 빈 칸은 추정하지 않습니다."
        ],
    }


def suspected_gaps(session, now=None):
    now = now or now_kst()
    start = now.date() - timedelta(days=14)
    # Conservative calendar-day rule: exclude today AND yesterday from delayed-source checks.
    cutoff = now.date() - timedelta(days=2)
    races = session.execute(
        select(
            Race.id,
            Race.race_date_local,
            Race.race_number,
            Racecourse.kra_meet_code,
            Racecourse.name_ko,
            Race.field_size,
        )
        .join(Racecourse)
        .where(Race.race_date_local.between(start, cutoff), Race.status == "completed")
        .order_by(Race.race_date_local.desc(), Race.id.desc())
        .limit(501)
    ).all()
    scoped = races[:500]
    ids = [r.id for r in scoped]
    issues = []
    if ids:
        results = session.execute(
            select(
                RaceEntry.id,
                RaceEntry.race_id,
                RaceEntry.horse_number,
                Horse.name_ko,
                RaceEntry.scratched,
                RaceResult.id.label("result_id"),
                RaceResult.finish_position,
                RaceResult.finish_time_ms,
                RaceResult.disqualified,
            )
            .select_from(RaceEntry)
            .join(Horse)
            .outerjoin(RaceResult)
            .where(RaceEntry.race_id.in_(ids))
        ).all()
        section_ids = set(
            session.scalars(
                select(RaceSectionTime.race_entry_id)
                .where(
                    RaceSectionTime.race_entry_id.in_([r.id for r in results]),
                    RaceSectionTime.elapsed_time_ms.is_not(None),
                )
                .distinct()
            )
        )
        group_ids = set(
            session.scalars(
                select(RacePassingGroup.race_id)
                .where(
                    RacePassingGroup.race_id.in_(ids),
                    func.length(func.trim(RacePassingGroup.notation_raw)) > 0,
                )
                .distinct()
            )
        )
        reports = set(
            session.execute(
                select(
                    RaceStewardReport.meet_code,
                    RaceStewardReport.race_date_local,
                    RaceStewardReport.race_number,
                ).where(
                    RaceStewardReport.race_date_local.between(start, cutoff),
                    or_(
                        func.length(func.trim(RaceStewardReport.judgement)) > 0,
                        func.length(func.trim(RaceStewardReport.additional_judgement)) > 0,
                    ),
                )
            ).all()
        )
        by_race = {r.id: r for r in scoped}

        def add(r, kind, detail, horse=None):
            issues.append(
                {
                    "kind": kind,
                    "date": r.race_date_local,
                    "meet": r.name_ko,
                    "meet_code": r.kra_meet_code,
                    "race_no": r.race_number,
                    "race_id": r.id,
                    "horse": horse,
                    "detail": detail,
                    "severity": "review",
                }
            )

        for r in scoped:
            entries = [e for e in results if e.race_id == r.id]
            if not entries:
                add(r, "entries", "완료 표시된 경주에 출전행이 없습니다.")
            if r.id not in group_ids:
                add(r, "groups", "통과조 원문이 없습니다. 미공개·특수 경주 여부를 확인하세요.")
            if (r.kra_meet_code, r.race_date_local, r.race_number) not in reports:
                add(r, "stewards", "본문이 있는 심판리포트가 연결되지 않았습니다.")
        for e in results:
            if e.scratched:
                continue
            r = by_race[e.race_id]
            if e.result_id is None:
                add(
                    r,
                    "results",
                    f"{e.horse_number}번 비취소 출전행에 결과행이 없습니다.",
                    e.name_ko,
                )
            elif (
                e.finish_position
                and e.finish_position <= (r.field_size or 30)
                and e.finish_time_ms
                and not e.disqualified
                and e.id not in section_ids
            ):
                add(
                    r,
                    "sections",
                    f"{e.horse_number}번 정상 완주 기록에 구간시간이 하나도 없습니다.",
                    e.name_ko,
                )
    return {
        "checked_at": now.isoformat(),
        "start": start,
        "end": cutoff,
        "checked_races": len(scoped),
        "race_scope_truncated": len(races) > 500,
        "issues": issues[:200],
        "issue_count_in_scope": len(issues),
        "issues_truncated": len(issues) > 200,
        "notes": [
            "최근 14일 중 오늘·어제를 제외한 완료 경주, 최대 500경주를 관계 대조합니다.",
            "결과 없는 비취소 출전행 / 구간시간 전무인 정상 완주마 / 통과조·리포트 전무 경주만 탐지합니다.",
            "일부 지점·개별 순위 누락이나 원천과의 값 차이는 이 검사만으로 판정하지 않습니다.",
            "진료·조교는 기록 없는 날이 정상일 수 있어 단순 공백을 누락으로 표시하지 않습니다.",
            "0건은 위 범위·규칙에서 의심을 찾지 못했다는 뜻이며 전체 DB·공식 원천 대조 완료가 아닙니다.",
        ],
    }
