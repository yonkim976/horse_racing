"""Bounded, race-first analysis of observations dated before the selected race.

These are retrospective source records, not a sealed pre-race prediction snapshot.
No target-day result, training, trial or jockey performance is used as evidence.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean
from types import SimpleNamespace
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from horse_racing.db.models import (
    Horse,
    HorseStartTraining,
    HorseTraining,
    Jockey,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RaceSectionResult,
    RunningTrial,
    RunningTrialResult,
    Trainer,
)
from horse_racing.web.analysis_archive import load_verified_archive
from horse_racing.web.formatting import (
    MAX_NORMAL_FINISH,
    age_years,
    format_clock,
    format_finish_position,
    format_race_time,
    today_seoul,
)
from horse_racing.web.insights import (
    assign_win_labels,
    format_trial_form_token,
    format_win_pct,
    latest_win_probabilities,
    win_probability_sort_key,
)
from horse_racing.web.race_video import race_video_url, running_trial_video_url

SECTION_CODES = ("S1F", "1C", "2C", "3C", "4C", "G3F", "G1F")
BUSAN_SECTION_CODES = ("S1F", "G8F", "G6F", "G4F", "G3F", "G2F", "G1F")
MEET_NAMES = {1: "서울", 2: "제주", 3: "부산경남", 4: "영천"}
MAX_RUNNERS = 40
MAX_TRIALS = 12
MAX_TRAINING = 112


@dataclass(slots=True)
class AnalysisRace:
    id: int
    date: str
    meet: str
    meet_code: int
    number: int
    start_time: str
    distance: int
    grade: str
    name: str
    field_size: int
    runner_names: list[str] = field(default_factory=list)
    status: str = "scheduled"


@dataclass(slots=True)
class PastStart:
    race_id: int | None
    entry_id: int
    date: str
    meet: str
    race_number: int
    distance: int
    grade: str
    condition: str
    gate: str
    carried_weight: str
    body_weight: str
    jockey: str
    finish: str
    finish_sort: int
    time: str
    sections: dict[str, str]
    video_url: str | None = None
    valid_finish: bool = False
    finish_position: int | None = None
    finish_time_ms: int | None = None
    field_size: int | None = None
    days_since_previous: int | None = None
    section_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    early_position: int | None = None
    early_normalized: float | None = None
    meet_code: int | None = None
    remark: str = ""
    source_label: str = "운영 DB 공식 경주기록"
    horse_number: int | None = None


@dataclass(slots=True)
class TrialStart:
    id: int | None
    date: str
    meet: str
    meet_code: int
    number: int
    distance: int
    condition: str
    finish: str
    judgement: str
    reason: str
    time: str
    body_weight: str
    jockey: str
    sections: dict[str, str]
    section_details: dict[str, dict[str, Any]]
    video_url: str | None
    finish_time_ms: int | None = None
    passing_order: str = "—"
    source_label: str = "운영 DB 공식 주행심사"
    horse_number: int | None = None
    form_token: str | None = None


@dataclass(slots=True)
class AnalysisRunner:
    entry_id: int
    horse_id: int
    number: int
    gate: str
    horse: str
    jockey: str
    trainer: str
    weight: str
    rating: str
    state: str
    starts: int
    top3: int
    same_distance_starts: int
    section_starts: int
    history: list[PastStart]
    jockey_id: int | None = None
    profile: dict[str, Any] = field(default_factory=dict)
    history_total: int = 0
    trials: list[TrialStart] = field(default_factory=list)
    trial_total: int = 0
    training: list[dict[str, Any]] = field(default_factory=list)
    start_training: list[dict[str, Any]] = field(default_factory=list)
    training_summary: dict[str, Any] = field(default_factory=dict)
    jockey_stats: dict[str, Any] = field(default_factory=dict)
    combination_stats: dict[str, Any] = field(default_factory=dict)
    style: str = "자료 부족"
    style_note: str = "초반 통과순위가 확인된 과거 경주가 없습니다."
    early_normalized: float | None = None
    early_sample: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    pace_stages: dict[str, dict[str, Any]] = field(default_factory=dict)
    win_pct: str | None = None
    win_prob: float | None = None
    win_label: str | None = None
    form_kind: str = ""
    form_tokens: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RaceAnalysisPage:
    races: list[AnalysisRace]
    selected_race: AnalysisRace | None
    runners: list[AnalysisRunner]
    section_codes: tuple[str, ...]
    rows: list[dict[str, object]]
    filters: dict[str, object]
    date_options: list[str] = field(default_factory=list)
    selected_date: str = ""
    selection_note: str = ""
    history_limit: int = 12
    pace: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    pace_board: list[PaceBoardLane] = field(default_factory=list)
    pace_summaries: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class PaceBoardChip:
    entry_id: int
    number: int
    horse: str
    samples: int


@dataclass(slots=True)
class PaceBoardLane:
    key: str
    title: str
    hint: str
    slots: list[list[PaceBoardChip]]
    missing: list[PaceBoardChip]
    has_marks: bool


def load_race_analysis_page(
    session: Session,
    *,
    race_id: int | None = None,
    race_date: date | None = None,
    history_limit: int = 12,
    start: date | None = None,
    end: date | None = None,
    meet: int | None = None,
    distance: int | None = None,
    grade: str = "",
) -> RaceAnalysisPage:
    """Keep all reads bounded and batch the selected field's supporting records."""
    history_limit = 60 if history_limit == 60 else 12
    today = today_seoul()
    conditions = _race_conditions(meet=meet, distance=distance, grade=grade)
    dates = _available_dates(session, conditions, around=race_date or today)
    selected = _race_by_id(session, race_id) if race_id is not None else None
    if selected and (
        (race_date is not None and selected.date != race_date.isoformat())
        or (meet is not None and selected.meet_code != meet)
        or (distance is not None and selected.distance != distance)
        or (grade and selected.grade != grade)
    ):
        selected = None
    requested_date = race_date or (date.fromisoformat(selected.date) if selected else today)
    selected_date = requested_date
    selection_note = ""
    if race_date is None and selected is None and dates and requested_date not in dates:
        selected_date = min(dates, key=lambda item: (abs((item - today).days), item < today))
        selection_note = (
            f"오늘({today.isoformat()})은 공개된 출전표가 없어 "
            f"가장 가까운 공개 경주일 {selected_date.isoformat()}을 표시합니다."
        )
    races = _races_on_date(
        session,
        _race_conditions(meet=None, distance=distance, grade=grade),
        selected_date,
    )
    if selected is not None and selected.date == selected_date.isoformat():
        selected = next((item for item in races if item.id == selected.id), selected)
        if meet is not None and selected.meet_code != meet:
            selected = None
    if selected is None:
        if meet is not None:
            selected = next((item for item in races if item.meet_code == meet), None)
        if selected is None:
            selected = races[0] if races else None
    filters = {
        "race_id": selected.id if selected else None,
        "race_date": selected_date.isoformat(),
        "start": start.isoformat() if start else "",
        "end": end.isoformat() if end else "",
        "meet": meet,
        "distance": distance,
        "grade": grade,
        "history_limit": history_limit,
    }
    page = RaceAnalysisPage(
        races=races,
        selected_race=selected,
        runners=[],
        section_codes=BUSAN_SECTION_CODES
        if selected and selected.meet_code in {3, 4}
        else SECTION_CODES,
        rows=[],
        filters=filters,
        date_options=sorted({item.isoformat() for item in dates} | {selected_date.isoformat()}),
        selected_date=selected_date.isoformat(),
        selection_note=selection_note,
        history_limit=history_limit,
        notes=[
            "과거 경주·심사·조교·기수 집계는 선택한 경주일 전날까지의 기록만 사용합니다.",
            "나중에 수집·정정된 과거 자료를 포함하는 참고 분석이며, "
            "당시 공개정보를 동결한 예측은 아닙니다.",
            "운영 DB에 연결된 공식 기록을 사용하며, "
            "검증된 보존자료가 있는 경우 공식 고유번호로 연결해 보충합니다.",
            "주행심사는 합격 여부와 준비 상태를 보는 기록으로, 실전 기록과 직접 비교하지 않습니다.",
        ],
    )
    if selected is None:
        page.selection_note = selection_note or "선택한 날짜·조건에 공개된 출전표가 없습니다."
        return page

    cutoff = date.fromisoformat(selected.date)
    entries = (
        session.execute(
            select(
                RaceEntry.id.label("entry_id"),
                RaceEntry.horse_id,
                RaceEntry.horse_number.label("number"),
                RaceEntry.gate_number.label("gate"),
                Horse.name_ko.label("horse"),
                Horse.kra_horse_id,
                Horse.sex,
                Horse.birth_date,
                Horse.origin_country,
                RaceEntry.jockey_id,
                Jockey.name_ko.label("jockey"),
                Trainer.name_ko.label("trainer"),
                RaceEntry.carried_weight_kg,
                RaceEntry.rating,
                RaceEntry.scratched,
            )
            .join(Horse, Horse.id == RaceEntry.horse_id)
            .outerjoin(Jockey, Jockey.id == RaceEntry.jockey_id)
            .outerjoin(Trainer, Trainer.id == RaceEntry.trainer_id)
            .where(RaceEntry.race_id == selected.id)
            .order_by(RaceEntry.horse_number)
            .limit(MAX_RUNNERS)
        )
        .mappings()
        .all()
    )
    win_probs = latest_win_probabilities(session, [selected.id])
    horse_ids = [row["horse_id"] for row in entries]
    jockey_ids = list({row["jockey_id"] for row in entries if row["jockey_id"] is not None})
    histories, totals = _load_histories(
        session,
        horse_ids,
        cutoff,
        history_limit,
        start=start,
        end=end,
    )
    trials, trial_totals = _load_trials(session, horse_ids, cutoff)
    distance_stats = _load_distance_stats(
        session,
        horse_ids,
        cutoff,
        distance=selected.distance,
        meet=selected.meet_code,
        start=start,
        end=end,
    )
    archive_coverage = _merge_archive(
        session,
        entries,
        histories,
        totals,
        trials,
        trial_totals,
        cutoff=cutoff,
        history_limit=history_limit,
        start=start,
        end=end,
        distance_stats=distance_stats,
        selected_distance=selected.distance,
        selected_meet=selected.meet_code,
    )
    training, start_training, training_summaries = _load_training(session, horse_ids, cutoff)
    jockey_stats, combinations = _load_jockey_stats(session, jockey_ids, horse_ids, cutoff)

    for entry in entries:
        horse_id = entry["horse_id"]
        history = histories.get(horse_id, [])
        valid = [item for item in history if item.valid_finish]
        early = [item.early_normalized for item in valid if item.early_normalized is not None][:6]
        early_mean = round(mean(early), 4) if early else None
        style, style_note = _pace_style(early)
        displayed_section_count = sum(
            any(
                detail["time_ms"] is not None or detail["position"] is not None
                for detail in item.section_details.values()
            )
            for item in history
        )
        horse_trials = trials.get(horse_id, [])
        form_kind, form_tokens = _record_form(history, horse_trials)
        runner = AnalysisRunner(
            entry_id=entry["entry_id"],
            horse_id=horse_id,
            number=entry["number"],
            gate=str(entry["gate"]) if entry["gate"] is not None else "—",
            horse=entry["horse"],
            jockey=entry["jockey"] or "미정",
            trainer=entry["trainer"] or "—",
            weight=_weight(entry["carried_weight_kg"]),
            rating=f"{entry['rating']:g}" if entry["rating"] is not None else "—",
            state="출전취소"
            if entry["scratched"]
            else ("경주 완료" if selected.status == "completed" else "출전 예정"),
            starts=len(history),
            top3=sum(item.finish_sort <= 3 for item in valid),
            same_distance_starts=distance_stats.get(horse_id, {}).get("starts", 0),
            section_starts=displayed_section_count,
            history=history,
            jockey_id=entry["jockey_id"],
            profile={
                "sex": entry["sex"],
                "age": age_years(entry["birth_date"], cutoff),
                "origin": entry["origin_country"],
            },
            history_total=totals.get(horse_id, 0),
            trials=horse_trials,
            trial_total=trial_totals.get(horse_id, 0),
            training=training.get(horse_id, []),
            start_training=start_training.get(horse_id, []),
            training_summary=training_summaries.get(horse_id, _empty_training_summary()),
            jockey_stats=jockey_stats.get(entry["jockey_id"], _stats()),
            combination_stats=combinations.get((horse_id, entry["jockey_id"]), _stats()),
            style=style,
            style_note=style_note,
            early_normalized=early_mean,
            early_sample=len(early),
            metrics=_metrics(
                history,
                selected.distance,
                selected.meet_code,
                cutoff,
                distance_stats.get(horse_id, {}),
            ),
            pace_stages=_pace_stages(history, selected.meet_code),
            win_pct=format_win_pct(win_probs.get(entry["entry_id"])),
            win_prob=win_probs.get(entry["entry_id"]),
            form_kind=form_kind,
            form_tokens=form_tokens,
        )
        page.runners.append(runner)
        for item in history:
            page.rows.append(
                {
                    "date": item.date,
                    "meet": item.meet,
                    "race": item.race_number,
                    "distance": item.distance,
                    "grade": item.grade,
                    "track_condition": item.condition,
                    "horse": runner.horse,
                    "jockey": item.jockey,
                    "finish": item.finish,
                    "time": item.time,
                    **{code: item.sections.get(code, "—") for code in page.section_codes},
                }
            )
    page.pace = {
        "race": {
            "id": selected.id,
            "date": selected.date,
            "meet": selected.meet,
            "meet_code": selected.meet_code,
            "number": selected.number,
            "distance": selected.distance,
        },
        "runners": [
            {
                "entry_id": runner.entry_id,
                "horse_id": runner.horse_id,
                "number": runner.number,
                "name": runner.horse,
                "gate": int(runner.gate) if runner.gate.isdigit() else None,
                "scratched": entry["scratched"],
                "style": runner.style,
                "early_normalized": runner.early_normalized,
                "early_sample": runner.early_sample,
                "stages": runner.pace_stages,
            }
            for runner, entry in zip(page.runners, entries, strict=True)
        ],
        "cutoff_label": f"{selected.date} 이전 · 최근 6회 정상 완주 내 지점별 실제 통과순위",
    }
    page.coverage = {
        "runners": len(page.runners),
        "with_history": sum(bool(r.history) for r in page.runners),
        "with_trials": sum(bool(r.trials) for r in page.runners),
        "with_training": sum(bool(r.training) for r in page.runners),
        "with_pace": sum(r.early_sample >= 2 for r in page.runners),
        "history_limit": history_limit,
        "trial_limit": MAX_TRIALS,
        "cutoff": selected.date,
        "truncated_field": selected.field_size > MAX_RUNNERS,
        **archive_coverage,
    }
    win_labels = assign_win_labels(
        [
            (runner.entry_id, runner.win_prob, runner.state == "출전취소")
            for runner in page.runners
        ]
    )
    for runner in page.runners:
        runner.win_label = win_labels.get(runner.entry_id)
    if any(runner.win_prob is not None for runner in page.runners):
        page.runners.sort(
            key=lambda runner: win_probability_sort_key(
                scratched=runner.state == "출전취소",
                number=runner.number,
                win_prob=runner.win_prob,
                has_field_predictions=True,
            )
        )
    page.pace_board, page.pace_summaries = _pace_board(page.runners)
    return page


def _race_conditions(*, meet: int | None, distance: int | None, grade: str) -> list:
    conditions = [select(RaceEntry.id).where(RaceEntry.race_id == Race.id).exists()]
    if meet is not None:
        conditions.append(Racecourse.kra_meet_code == meet)
    if distance is not None:
        conditions.append(Race.distance_m == distance)
    if grade:
        conditions.append(Race.grade == grade)
    return conditions


def _available_dates(session: Session, conditions: list, *, around: date) -> list[date]:
    base = select(Race.race_date_local).join(Racecourse).where(*conditions).distinct()
    past = session.scalars(
        base.where(Race.race_date_local <= around).order_by(Race.race_date_local.desc()).limit(45)
    ).all()
    future = session.scalars(
        base.where(Race.race_date_local > around).order_by(Race.race_date_local).limit(35)
    ).all()
    return sorted(set(past + future))


def _race_query():
    count = (
        select(func.count(RaceEntry.id))
        .where(RaceEntry.race_id == Race.id)
        .correlate(Race)
        .scalar_subquery()
    )
    return select(
        Race.id,
        Race.race_date_local,
        Racecourse.name_ko,
        Racecourse.kra_meet_code,
        Race.race_number,
        Race.scheduled_at_ms,
        Race.distance_m,
        Race.grade,
        Race.race_name,
        count,
        Race.status,
    ).join(Racecourse)


def _races_on_date(session: Session, conditions: list, race_date: date) -> list[AnalysisRace]:
    rows = session.execute(
        _race_query()
        .where(*conditions, Race.race_date_local == race_date)
        .order_by(Racecourse.kra_meet_code, Race.race_number)
        .limit(80)
    ).all()
    races = [_race_view(row) for row in rows]
    _attach_runner_names(session, races)
    return races


def _race_by_id(session: Session, race_id: int) -> AnalysisRace | None:
    row = session.execute(_race_query().where(Race.id == race_id)).one_or_none()
    return _race_view(row) if row is not None else None


def _race_view(row) -> AnalysisRace:
    return AnalysisRace(
        id=row[0],
        date=row[1].isoformat(),
        meet=row[2],
        meet_code=row[3],
        number=row[4],
        start_time=format_clock(row[5]),
        distance=row[6],
        grade=row[7] or "미정",
        name=row[8] or "일반",
        field_size=row[9],
        status=row[10],
    )


def _attach_runner_names(session: Session, races: list[AnalysisRace]) -> None:
    if not races:
        return
    by_race = {race.id: race for race in races}
    for race_id, horse_name in session.execute(
        select(RaceEntry.race_id, Horse.name_ko)
        .join(Horse)
        .where(RaceEntry.race_id.in_(by_race))
        .order_by(RaceEntry.race_id, RaceEntry.horse_number)
        .limit(80 * MAX_RUNNERS)
    ):
        by_race[race_id].runner_names.append(horse_name)


def _load_histories(session, horse_ids, cutoff, limit, *, start, end):
    histories: dict[int, list[PastStart]] = defaultdict(list)
    totals: dict[int, int] = {}
    if not horse_ids:
        return histories, totals
    conditions = [RaceEntry.horse_id.in_(horse_ids), Race.race_date_local < cutoff]
    if start:
        conditions.append(Race.race_date_local >= start)
    if end:
        conditions.append(Race.race_date_local <= end)
    ranked = (
        select(
            RaceEntry.horse_id,
            RaceEntry.id.label("entry_id"),
            Race.id.label("race_id"),
            Race.race_date_local.label("date"),
            Racecourse.name_ko.label("meet"),
            Racecourse.kra_meet_code.label("meet_code"),
            Race.race_number,
            Race.distance_m,
            Race.grade,
            Race.weather,
            Race.track_condition,
            Race.track_moisture_percent,
            RaceEntry.gate_number,
            RaceEntry.horse_number,
            RaceEntry.carried_weight_kg,
            RaceEntry.body_weight_kg,
            Jockey.name_ko.label("jockey"),
            RaceResult.finish_position,
            RaceResult.finish_time_ms,
            RaceResult.disqualified,
            RaceResult.rank_remark,
            RaceEntry.scratched,
            Race.field_size,
            Race.status,
            func.row_number()
            .over(
                partition_by=RaceEntry.horse_id,
                order_by=(Race.race_date_local.desc(), Race.id.desc()),
            )
            .label("rn"),
            func.count().over(partition_by=RaceEntry.horse_id).label("total"),
            func.lag(Race.race_date_local)
            .over(
                partition_by=RaceEntry.horse_id,
                order_by=(Race.race_date_local, Race.id),
            )
            .label("previous_date"),
        )
        .join(Race, Race.id == RaceEntry.race_id)
        .join(Racecourse)
    )
    ranked = (
        ranked.join(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .outerjoin(Jockey, Jockey.id == RaceEntry.jockey_id)
        .where(*conditions)
        .subquery()
    )
    rows = (
        session.execute(
            select(ranked).where(ranked.c.rn <= limit).order_by(ranked.c.horse_id, ranked.c.rn)
        )
        .mappings()
        .all()
    )
    section_rows = (
        session.execute(
            select(RaceSectionResult).where(
                RaceSectionResult.race_entry_id.in_([row["entry_id"] for row in rows]),
            )
        )
        .scalars()
        .all()
        if rows
        else []
    )
    sections = defaultdict(dict)
    for section in section_rows:
        sections[section.race_entry_id][section.section_code] = section
    # Field sizes in source plans may be absent; count historical entries in one batch.
    missing_sizes = list({row["race_id"] for row in rows if not row["field_size"]})
    sizes = (
        dict(
            session.execute(
                select(RaceEntry.race_id, func.count())
                .where(RaceEntry.race_id.in_(missing_sizes))
                .group_by(RaceEntry.race_id),
            ).all()
        )
        if missing_sizes
        else {}
    )
    for row in rows:
        totals[row["horse_id"]] = row["total"]
        normal = (
            row["finish_position"] is not None
            and 0 < row["finish_position"] <= MAX_NORMAL_FINISH
            and not row["disqualified"]
            and not row["scratched"]
        )
        finish_label, finish_sort, _ = format_finish_position(
            row["finish_position"],
            scratched=row["scratched"],
        )
        if row["disqualified"]:
            finish_label, finish_sort = "실격", 3000
        finish_ms = row["finish_time_ms"] if normal else None
        codes = BUSAN_SECTION_CODES if row["meet_code"] in {3, 4} else SECTION_CODES
        details = {
            code: _section_detail(
                code,
                sections[row["entry_id"]].get(code),
                finish_ms=finish_ms,
                meet=row["meet_code"],
                distance=row["distance_m"],
                valid_finish=normal,
            )
            for code in codes
        }
        field_size = row["field_size"] or sizes.get(row["race_id"])
        early_position = details["S1F"]["position"]
        normalized = _normalized_position(early_position, field_size) if normal else None
        previous = row["previous_date"]
        if isinstance(previous, str):
            previous = date.fromisoformat(previous)
        histories[row["horse_id"]].append(
            PastStart(
                race_id=row["race_id"],
                entry_id=row["entry_id"],
                date=row["date"].isoformat(),
                meet=row["meet"],
                race_number=row["race_number"],
                distance=row["distance_m"],
                grade=row["grade"] or "—",
                condition=_condition(
                    row["weather"], row["track_condition"], row["track_moisture_percent"]
                ),
                gate=str(row["gate_number"]) if row["gate_number"] is not None else "—",
                carried_weight=_weight(row["carried_weight_kg"]),
                body_weight=_weight(row["body_weight_kg"]),
                jockey=row["jockey"] or "—",
                finish=finish_label,
                finish_sort=finish_sort,
                time=format_race_time(finish_ms),
                sections={code: detail["display"] for code, detail in details.items()},
                video_url=race_video_url(
                    meet_code=row["meet_code"],
                    race_date=row["date"],
                    race_number=row["race_number"],
                    status=row["status"],
                ),
                valid_finish=normal,
                finish_position=row["finish_position"],
                finish_time_ms=finish_ms,
                field_size=field_size,
                days_since_previous=(row["date"] - previous).days if previous else None,
                section_details=details,
                early_position=early_position,
                early_normalized=normalized,
                meet_code=row["meet_code"],
                remark=row["rank_remark"] or "",
                horse_number=row["horse_number"],
            )
        )
    return histories, totals


def _section_detail(code, section, *, finish_ms, meet, distance, valid_finish):
    raw = section.elapsed_time_ms if section is not None else None
    basis = section.time_basis if section is not None else None
    source = section.source_kind if section is not None else None
    position = section.position if section is not None else None
    normalized = None
    early_distance = 210 if meet == 2 and distance in {1110, 1610} else 200
    label = f"초반 {early_distance}m" if code == "S1F" else f"{code} 통과 누적"
    if code == "G3F":
        label = "마지막 600m"
    elif code == "G1F":
        label = "마지막 200m"
    note = ""
    if raw is not None and raw > 0:
        if not valid_finish:
            note = "비정상 결과: 구간 원문은 보존하되 비교·각질 집계에서 제외"
        elif basis not in {"cumulative", "closing"}:
            note = "시간 기준 미확인: 원문 수치를 표시하며 구간 비교 집계에서 제외"
        elif code in {"G3F", "G1F"}:
            if basis == "closing" and (finish_ms is None or raw < finish_ms):
                normalized = raw
                note = "결승선까지의 구간 기록"
            elif basis == "cumulative" and finish_ms is not None and raw < finish_ms:
                normalized = finish_ms - raw
                note = "전체 기록 − 해당 지점 통과 누적시간"
        elif basis == "cumulative" and (finish_ms is None or raw < finish_ms):
            normalized = raw
            note = "출발부터 해당 지점까지의 누적시간"
    if normalized is not None:
        display = _format_section(normalized, position)
    elif raw is not None and raw > 0:
        display = f"원문 {format_race_time(raw)}"
        if position is not None:
            display += f" · {position}위"
        display += " · 기준 미확인" if basis is None else " · 비교 제외"
    else:
        display = _format_section(None, position)
    return {
        "label": label,
        "time": format_race_time(normalized),
        "time_ms": normalized,
        "raw_time_ms": raw,
        "position": position,
        "basis": basis,
        "source": source or "미확인",
        "note": note,
        "display": display,
        "distance_from_start_m": getattr(section, "distance_from_start_m", None),
    }


def _load_trials(session, horse_ids, cutoff):
    output, totals = defaultdict(list), {}
    if not horse_ids:
        return output, totals
    ranked = (
        select(
            RunningTrialResult.id,
            func.row_number()
            .over(
                partition_by=RunningTrialResult.horse_id,
                order_by=(
                    RunningTrial.trial_date_local.desc(),
                    RunningTrial.trial_race_number.desc(),
                    RunningTrialResult.id.desc(),
                ),
            )
            .label("rn"),
            func.count().over(partition_by=RunningTrialResult.horse_id).label("total"),
        )
        .join(RunningTrial)
        .where(
            RunningTrialResult.horse_id.in_(horse_ids),
            RunningTrial.trial_date_local < cutoff,
        )
        .subquery()
    )
    rows = session.execute(
        select(RunningTrialResult, RunningTrial, ranked.c.total)
        .join(ranked, ranked.c.id == RunningTrialResult.id)
        .join(RunningTrial)
        .where(ranked.c.rn <= MAX_TRIALS)
        .order_by(RunningTrial.trial_date_local.desc()),
    ).all()
    for result, trial, total in rows:
        totals[result.horse_id] = total
        details = {}
        finish_ms = (
            result.finish_time_ms
            if (
                result.finish_position is not None
                and 1 <= result.finish_position <= MAX_NORMAL_FINISH
                and result.finish_time_ms is not None
                and result.finish_time_ms > 0
            )
            else None
        )
        for code, value, label, basis in (
            ("S1F", result.s1f_ms, "초반 200m", "cumulative"),
            ("3C", result.corner_3_ms, "3코너 통과 누적", "cumulative"),
            ("4C", result.corner_4_ms, "4코너 통과 누적", "cumulative"),
            ("G3F", result.g3f_ms, "마지막 600m", "closing"),
            ("G1F", result.g1f_ms, "마지막 200m", "closing"),
            ("400M", result.section_400_ms, "초반 S1F 이후 중간 400m", "segment"),
            ("FINAL400", result.final_400_ms, "마지막 400m", "closing"),
        ):
            valid_value = (
                value
                if (value is not None and value > 0 and finish_ms is not None and value < finish_ms)
                else None
            )
            details[code] = {
                "label": label,
                "time": format_race_time(valid_value),
                "time_ms": valid_value,
                "raw_time_ms": value,
                "position": None,
                "basis": basis,
                "source": "dacom23",
                "note": "공식 주행심사 기록",
            }
        judgement = _trial_judgement(result.judgement)
        output[result.horse_id].append(
            TrialStart(
                id=trial.id,
                date=trial.trial_date_local.isoformat(),
                meet=MEET_NAMES.get(trial.meet_code, str(trial.meet_code)),
                meet_code=trial.meet_code,
                number=trial.trial_race_number,
                distance=trial.distance_m,
                condition=_condition(
                    trial.weather, trial.track_condition, trial.track_moisture_percent
                ),
                finish=format_finish_position(result.finish_position)[0]
                if result.finish_position is not None
                else (result.finish_rank_raw or "—"),
                judgement=judgement,
                reason=" · ".join(x for x in (result.failure_reason, result.inspection_reason) if x)
                or "—",
                time=format_race_time(finish_ms),
                body_weight=_weight(result.body_weight_kg),
                jockey=result.jockey_name_raw or "—",
                sections={code: detail["time"] for code, detail in details.items()},
                section_details=details,
                video_url=running_trial_video_url(
                    meet_code=trial.meet_code,
                    trial_date=trial.trial_date_local,
                    trial_race_number=trial.trial_race_number,
                ),
                finish_time_ms=finish_ms,
                passing_order=result.passing_order_raw or "—",
                horse_number=result.horse_number,
                form_token=format_trial_form_token(result.finish_position, result.judgement),
            )
        )
    return output, totals


def _load_distance_stats(session, horse_ids, cutoff, *, distance, meet, start, end):
    if not horse_ids:
        return {}
    conditions = [
        RaceEntry.horse_id.in_(horse_ids),
        Race.race_date_local < cutoff,
        Race.distance_m == distance,
        Racecourse.kra_meet_code == meet,
        RaceResult.finish_position.between(1, MAX_NORMAL_FINISH),
        RaceResult.disqualified.is_(False),
        RaceEntry.scratched.is_(False),
    ]
    if start:
        conditions.append(Race.race_date_local >= start)
    if end:
        conditions.append(Race.race_date_local <= end)
    rows = session.execute(
        select(RaceEntry.horse_id, func.count(), func.min(RaceResult.finish_time_ms))
        .select_from(RaceEntry)
        .join(Race)
        .join(Racecourse)
        .join(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .where(*conditions)
        .group_by(RaceEntry.horse_id),
    )
    return {horse_id: {"starts": starts, "best_ms": best} for horse_id, starts, best in rows}


def _merge_archive(
    session,
    entries,
    histories,
    totals,
    trials,
    trial_totals,
    *,
    cutoff,
    history_limit,
    start,
    end,
    distance_stats,
    selected_distance,
    selected_meet,
):
    """Merge verified evidence by natural identity, never by the archive's PK."""
    official = {row["horse_id"]: str(row["kra_horse_id"]).zfill(7) for row in entries}
    archived = load_verified_archive(list(official.values()), cutoff, limit_per_horse=500)
    summary = {
        "archive_races_added": 0,
        "archive_trials_added": 0,
        "archive_sections_verified": 0,
        "archive_available": bool(archived),
        "archive_truncated": False,
    }
    if not archived:
        return summary
    horse_ids = [key for key, official_id in official.items() if official_id in archived]
    race_keys = _operational_keys(session, horse_ids, cutoff, trials=False, start=start, end=end)
    trial_keys = _operational_keys(session, horse_ids, cutoff, trials=True)
    for horse_id in horse_ids:
        evidence = archived[official[horse_id]]
        summary["archive_truncated"] |= bool(
            evidence.get("races_truncated") or evidence.get("trials_truncated")
        )
        existing = {
            (item.date, item.meet_code, item.race_number): item
            for item in histories.get(horse_id, [])
        }
        source_races = [
            row
            for row in evidence["races"]
            if row["date"] < cutoff.isoformat()
            and (start is None or row["date"] >= start.isoformat())
            and (end is None or row["date"] <= end.isoformat())
        ]
        operational = race_keys.get(horse_id, set())
        extra = []
        for row in source_races:
            key = (row["date"], row["meet"], row["event_number"])
            if key in existing:
                current = existing[key]
                # Metadata can repair an ambiguous legacy display only when both
                # independently stored observations match exactly.
                if current.finish_time_ms == row["time_ms"] and row["time_analysis_eligible"]:
                    for code, raw_section in row["sections"].items():
                        detail = current.section_details.get(code)
                        if (
                            detail
                            and detail["basis"] is None
                            and detail["raw_time_ms"] == raw_section["raw_ms"]
                        ):
                            current.section_details[code] = _archive_section_detail(
                                code,
                                raw_section,
                                row,
                                position=detail["position"],
                            )
                            current.sections[code] = current.section_details[code]["display"]
                            summary["archive_sections_verified"] += 1
            elif key not in operational:
                # Above 500 starts, older identities are intentionally not guessed.
                if totals.get(horse_id, 0) > 500:
                    summary["archive_truncated"] = True
                    continue
                extra.append(_archive_start(row))
        totals[horse_id] = totals.get(horse_id, 0) + len(extra)
        for item in extra:
            if (
                item.valid_finish
                and item.distance == selected_distance
                and item.meet_code == selected_meet
            ):
                stats = distance_stats.setdefault(horse_id, {"starts": 0, "best_ms": None})
                stats["starts"] += 1
                if item.finish_time_ms is not None:
                    stats["best_ms"] = (
                        min(stats["best_ms"], item.finish_time_ms)
                        if stats["best_ms"] is not None
                        else item.finish_time_ms
                    )
        summary["archive_races_added"] += len(extra)
        combined = sorted(
            [*histories.get(horse_id, []), *extra],
            key=lambda row: (row.date, row.race_number),
            reverse=True,
        )
        all_dates = sorted({key[0] for key in operational} | {row["date"] for row in source_races})
        previous = {
            day: all_dates[index - 1] if index else None for index, day in enumerate(all_dates)
        }
        for item in combined:
            previous_date = previous.get(item.date)
            item.days_since_previous = (
                (date.fromisoformat(item.date) - date.fromisoformat(previous_date)).days
                if previous_date
                else None
            )
        histories[horse_id] = combined[:history_limit]
        existing_trials = trial_keys.get(horse_id, set())
        extra_trials = []
        for row in evidence["trials"]:
            if row["date"] >= cutoff.isoformat():
                continue
            key = (row["date"], row["meet"], row["event_number"])
            if key not in existing_trials:
                if trial_totals.get(horse_id, 0) > 500:
                    summary["archive_truncated"] = True
                    continue
                extra_trials.append(_archive_trial(row))
        trial_totals[horse_id] = trial_totals.get(horse_id, 0) + len(extra_trials)
        summary["archive_trials_added"] += len(extra_trials)
        trials[horse_id] = sorted(
            [*trials.get(horse_id, []), *extra_trials],
            key=lambda row: (row.date, row.number),
            reverse=True,
        )[:MAX_TRIALS]
    return summary


def _operational_keys(session, horse_ids, cutoff, *, trials, start=None, end=None):
    """At most 500 compact identities per horse for archive deduplication."""
    if trials:
        horse_column = RunningTrialResult.horse_id
        date_column = RunningTrial.trial_date_local
        query = select(
            horse_column.label("horse_id"),
            date_column.label("date"),
            RunningTrial.meet_code.label("meet"),
            RunningTrial.trial_race_number.label("number"),
            func.row_number()
            .over(partition_by=horse_column, order_by=date_column.desc())
            .label("rn"),
        )
        query = query.select_from(RunningTrialResult).join(
            RunningTrial,
            RunningTrial.id == RunningTrialResult.running_trial_id,
        )
    else:
        horse_column = RaceEntry.horse_id
        date_column = Race.race_date_local
        query = select(
            horse_column.label("horse_id"),
            date_column.label("date"),
            Racecourse.kra_meet_code.label("meet"),
            Race.race_number.label("number"),
            func.row_number()
            .over(partition_by=horse_column, order_by=date_column.desc())
            .label("rn"),
        )
        query = (
            query.select_from(RaceEntry)
            .join(Race, Race.id == RaceEntry.race_id)
            .join(Racecourse, Racecourse.id == Race.racecourse_id)
            .join(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        )
    query = query.where(horse_column.in_(horse_ids), date_column < cutoff)
    if start:
        query = query.where(date_column >= start)
    if end:
        query = query.where(date_column <= end)
    ranked = query.subquery()
    result = defaultdict(set)
    for row in session.execute(select(ranked).where(ranked.c.rn <= 500)).mappings():
        result[row["horse_id"]].add((row["date"].isoformat(), row["meet"], row["number"]))
    return result


def _archive_section_detail(code, raw, row, *, position=None):
    source = SimpleNamespace(
        elapsed_time_ms=raw.get("raw_ms"),
        position=position,
        time_basis=raw.get("time_basis"),
        source_kind=raw.get("source_kind"),
        distance_from_start_m=raw.get("distance_from_start_m"),
    )
    normal = row["record_status"] == "normal_completed"
    detail = _section_detail(
        code,
        source,
        finish_ms=row["time_ms"],
        meet=row["meet"],
        distance=row["distance"],
        valid_finish=normal and row["time_analysis_eligible"],
    )
    detail["note"] = "검증된 공식 보존자료 · " + detail["note"]
    return detail


def _archive_start(row):
    normal = row["record_status"] == "normal_completed"
    finish_ms = row["time_ms"] if normal and row["time_analysis_eligible"] else None
    finish, finish_sort, _ = format_finish_position(row["finish_position"])
    details = {
        code: _archive_section_detail(code, row["sections"].get(code, {}), row)
        for code in SECTION_CODES
    }
    return PastStart(
        race_id=None,
        entry_id=-row["archive_entry_id"],
        date=row["date"],
        meet=MEET_NAMES[row["meet"]],
        race_number=row["event_number"],
        distance=row["distance"],
        grade=row["grade"] or "—",
        condition=_condition(row["weather"], row["track_condition"], row["track_moisture_percent"]),
        gate="—",
        carried_weight=_weight(row.get("carried_weight_kg")),
        body_weight=_weight(row.get("body_weight_kg")),
        jockey=row.get("jockey") or "—",
        finish=finish,
        finish_sort=finish_sort,
        time=format_race_time(finish_ms),
        sections={code: detail["display"] for code, detail in details.items()},
        video_url=race_video_url(
            meet_code=row["meet"],
            race_date=date.fromisoformat(row["date"]),
            race_number=row["event_number"],
            status="completed",
        ),
        valid_finish=normal,
        finish_position=row["finish_position"],
        finish_time_ms=finish_ms,
        field_size=row["field_size"],
        section_details=details,
        meet_code=row["meet"],
        remark=row["record_status"] if not normal else "",
        source_label=row["source_label"],
        horse_number=row.get("horse_number"),
    )


def _archive_trial(row):
    details = {
        code: _archive_section_detail(code, raw, row) for code, raw in row["sections"].items()
    }
    finish_ms = row["time_ms"] if row["time_analysis_eligible"] else None
    judgement = _trial_judgement(row.get("judgement"))
    return TrialStart(
        id=None,
        date=row["date"],
        meet=MEET_NAMES[row["meet"]],
        meet_code=row["meet"],
        number=row["event_number"],
        distance=row["distance"],
        condition=_condition(row["weather"], row["track_condition"], row["track_moisture_percent"]),
        finish=f"{row['finish_position']}위"
        if row["finish_position"] is not None
        else row.get("finish_rank_raw") or "—",
        judgement=judgement,
        reason=" · ".join(
            value for value in (row.get("failure_reason"), row.get("inspection_reason")) if value
        )
        or "—",
        time=format_race_time(finish_ms),
        body_weight=_weight(row.get("body_weight_kg")),
        jockey=row.get("jockey") or "—",
        sections={code: detail["display"] for code, detail in details.items()},
        section_details=details,
        video_url=running_trial_video_url(
            meet_code=row["meet"],
            trial_date=date.fromisoformat(row["date"]),
            trial_race_number=row["event_number"],
        ),
        finish_time_ms=finish_ms,
        passing_order=row.get("passing_order") or "—",
        source_label=row["source_label"],
        horse_number=row.get("horse_number"),
        form_token=format_trial_form_token(row.get("finish_position"), row.get("judgement")),
    )


def _record_form(
    history: list[PastStart],
    trials: list[TrialStart],
) -> tuple[str, list[str]]:
    if history:
        tokens = [
            str(item.finish_position) if item.valid_finish else "–" for item in history[:5]
        ]
        return "race", tokens
    tokens = [trial.form_token for trial in trials if trial.form_token][:5]
    if tokens:
        return "trial", tokens
    return "", []


def _trial_judgement(value):
    return {
        "합": "합격",
        "불": "불합격",
        "유": "유보",
        "연": "연습",
        "출": "심사제외",
        "심": "심사취소",
        "주": "주행중지",
    }.get(value, value or "미확인")


def _load_training(session, horse_ids, cutoff):
    training, starts, summaries = defaultdict(list), defaultdict(list), {}
    if not horse_ids:
        return training, starts, summaries
    beginning = cutoff - timedelta(days=28)
    for model, date_column, destination in (
        (HorseTraining, HorseTraining.training_date_local, training),
        (HorseStartTraining, HorseStartTraining.training_date_local, starts),
    ):
        ranked = (
            select(
                model.id,
                func.row_number()
                .over(partition_by=model.horse_id, order_by=(date_column.desc(), model.id.desc()))
                .label("rn"),
            )
            .where(model.horse_id.in_(horse_ids), date_column >= beginning, date_column < cutoff)
            .subquery()
        )
        records = session.scalars(
            select(model)
            .join(ranked, ranked.c.id == model.id)
            .where(ranked.c.rn <= MAX_TRAINING)
            .order_by(date_column.desc(), model.id.desc()),
        ).all()
        for record in records:
            item = {
                "date": record.training_date_local.isoformat(),
                "meet": MEET_NAMES.get(record.meet_code, str(record.meet_code)),
            }
            if model is HorseTraining:
                item.update(
                    duration_seconds=record.duration_seconds,
                    duration_minutes=round(record.duration_seconds / 60, 1)
                    if record.duration_seconds is not None
                    else None,
                    canter_count=record.canter_count,
                    gallop_count=record.gallop_count,
                    trainer=record.trainer_name,
                    rider_type=record.rider_type,
                    start_time=record.started_at_raw,
                    end_time=record.ended_at_raw,
                )
            else:
                item.update(rider=record.rider_name, remark=record.remark)
            destination[record.horse_id].append(item)
    for horse_id in horse_ids:
        rows = training[horse_id]
        durations = [row["duration_seconds"] for row in rows if row["duration_seconds"] is not None]
        canters = [row["canter_count"] for row in rows if row["canter_count"] is not None]
        gallops = [row["gallop_count"] for row in rows if row["gallop_count"] is not None]
        summaries[horse_id] = {
            "window_days": 28,
            "sessions": len(rows),
            "days": len({row["date"] for row in rows}),
            "minutes": round(sum(durations) / 60, 1) if durations else None,
            "canter_count": sum(canters) if canters else None,
            "gallop_count": sum(gallops) if gallops else None,
            "start_sessions": len(starts[horse_id]),
            "truncated": len(rows) == MAX_TRAINING or len(starts[horse_id]) == MAX_TRAINING,
        }
    return training, starts, summaries


def _load_jockey_stats(session, jockey_ids, horse_ids, cutoff):
    if not jockey_ids:
        return {}, {}
    conditions = [
        RaceEntry.jockey_id.in_(jockey_ids),
        Race.race_date_local >= cutoff - timedelta(days=365),
        Race.race_date_local < cutoff,
        RaceEntry.scratched.is_(False),
        RaceResult.finish_position.between(1, MAX_NORMAL_FINISH),
        RaceResult.disqualified.is_(False),
    ]
    columns = (
        func.count().label("starts"),
        func.sum(case((RaceResult.finish_position == 1, 1), else_=0)).label("wins"),
        func.sum(case((RaceResult.finish_position <= 3, 1), else_=0)).label("top3"),
    )
    base = select(*columns).select_from(RaceEntry).join(Race).join(RaceResult)
    jockey_rows = session.execute(
        base.add_columns(RaceEntry.jockey_id).where(*conditions).group_by(RaceEntry.jockey_id)
    ).all()
    pair_rows = session.execute(
        base.add_columns(RaceEntry.horse_id, RaceEntry.jockey_id)
        .where(*conditions, RaceEntry.horse_id.in_(horse_ids))
        .group_by(RaceEntry.horse_id, RaceEntry.jockey_id)
    ).all()
    return (
        {row[3]: _stats(*row[:3]) for row in jockey_rows},
        {(row[3], row[4]): _stats(*row[:3]) for row in pair_rows},
    )


def _stats(starts=0, wins=0, top3=0):
    return {
        "starts": starts,
        "wins": wins,
        "top3": top3,
        "win_rate": round(wins / starts * 100, 1) if starts else None,
        "top3_rate": round(top3 / starts * 100, 1) if starts else None,
        "window_days": 365,
        "basis": "선택 경주일 이전 365일 · 정상 완주",
    }


def _empty_training_summary():
    return {
        "window_days": 28,
        "sessions": 0,
        "days": 0,
        "minutes": None,
        "canter_count": None,
        "gallop_count": None,
        "start_sessions": 0,
        "truncated": False,
    }


PACE_LANE_META = (
    ("early", "초반", "출발 직후"),
    ("middle", "중반", "코너"),
    ("late", "종반", "결승 직전"),
)


def _pace_band(normalized: float | None) -> str:
    if normalized is None:
        return "기록 없음"
    if normalized <= 0.25:
        return "앞"
    if normalized <= 0.5:
        return "앞쪽"
    if normalized <= 0.75:
        return "뒤쪽"
    return "뒤"


def _pace_board(runners: list[AnalysisRunner]) -> tuple[list[PaceBoardLane], list[dict[str, Any]]]:
    active = [runner for runner in runners if runner.state != "출전취소"]
    lanes: list[PaceBoardLane] = []
    for key, title, hint in PACE_LANE_META:
        slots: list[list[PaceBoardChip]] = [[] for _ in range(11)]
        missing: list[PaceBoardChip] = []
        for runner in active:
            stage = runner.pace_stages.get(key) or {}
            normalized = stage.get("normalized")
            samples = int(stage.get("samples") or 0)
            chip = PaceBoardChip(
                entry_id=runner.entry_id,
                number=runner.number,
                horse=runner.horse,
                samples=samples,
            )
            if normalized is None or samples <= 0:
                missing.append(chip)
                continue
            slot = max(0, min(10, int(round((1 - float(normalized)) * 10))))
            slots[slot].append(chip)
        lanes.append(
            PaceBoardLane(
                key=key,
                title=title,
                hint=hint,
                slots=slots,
                missing=missing,
                has_marks=any(slots),
            )
        )
    summaries = []
    for runner in active:
        stages = runner.pace_stages or {}
        summaries.append(
            {
                "entry_id": runner.entry_id,
                "number": runner.number,
                "horse": runner.horse,
                "early": _pace_band((stages.get("early") or {}).get("normalized")),
                "middle": _pace_band((stages.get("middle") or {}).get("normalized")),
                "late": _pace_band((stages.get("late") or {}).get("normalized")),
            }
        )
    return lanes, summaries


def _normalized_position(position, field_size):
    if position is None or field_size is None or field_size <= 1 or not 1 <= position <= field_size:
        return None
    return (position - 1) / (field_size - 1)


def _pace_stages(history, default_meet):
    """Use reported checkpoint positions, never finishing ranks or interpolation."""
    recent = [row for row in history if row.valid_finish][:6]
    values = {stage: [] for stage in ("early", "middle", "late")}
    sources = {stage: defaultdict(int) for stage in values}
    for row in recent:
        selected_codes = {}
        meet = row.meet_code or default_meet
        candidates = {
            "early": ("S1F",),
            "middle": ("4C", "3C", "G3F") if meet in {3, 4} else ("4C", "3C"),
            "late": ("G1F",),
        }
        for stage, codes in candidates.items():
            for code in codes:
                detail = row.section_details.get(code, {})
                value = _normalized_position(detail.get("position"), row.field_size)
                if value is None:
                    continue
                # A 3C alias of S1F is still an early checkpoint, including when
                # the S1F position itself is missing from the source row.
                if stage != "early" and not _checkpoint_after(row, code, "S1F"):
                    continue
                if any(
                    not _checkpoint_after(row, code, earlier) for earlier in selected_codes.values()
                ):
                    continue
                values[stage].append(value)
                sources[stage][code] += 1
                selected_codes[stage] = code
                break
    fallback_labels = {
        "early": "S1F 통과순위",
        "middle": "G3F(결승 600m 전) 통과순위"
        if default_meet in {3, 4}
        else "4C 우선 · 없으면 3C 통과순위",
        "late": "G1F(결승 200m 전) 통과순위",
    }
    output = {}
    for stage in values:
        source_counts = dict(sources[stage])
        if source_counts:
            labels = []
            for code, count in source_counts.items():
                description = {"G3F": "G3F(결승 600m 전)", "G1F": "G1F(결승 200m 전)"}.get(
                    code, code
                )
                labels.append(f"{description} {count}회")
            label = " · ".join(labels) + " 통과순위"
        else:
            label = fallback_labels[stage] + " · 확인 자료 없음"
        output[stage] = {
            "normalized": round(mean(values[stage]), 4) if values[stage] else None,
            "samples": len(values[stage]),
            "label": f"{label} · 최근 {len(recent)}회 정상 완주 기준",
            "sources": source_counts,
        }
    return output


def _checkpoint_distance(row, code):
    recorded = row.section_details.get(code, {}).get("distance_from_start_m")
    if recorded is not None:
        return recorded
    if code == "S1F":
        return 210 if row.meet_code == 2 and row.distance in {1110, 1610} else 200
    if code in {"G3F", "G1F"}:
        return row.distance - (600 if code == "G3F" else 200)
    if row.meet_code == 2 and code in {"3C", "4C"}:
        return row.distance - (600 if code == "3C" else 400)
    if row.meet_code == 1 and row.distance == 1000 and code == "3C":
        return 200
    return None


def _checkpoint_cumulative(row, code):
    detail = row.section_details.get(code, {})
    raw = detail.get("raw_time_ms")
    if raw is None or raw <= 0:
        return None
    if detail.get("basis") == "cumulative":
        return raw
    if detail.get("basis") == "closing" and row.finish_time_ms is not None:
        return row.finish_time_ms - raw
    return None


def _checkpoint_after(row, code, earlier):
    """Reject equal/reversed checkpoints only where their order is evidenced."""
    if code == earlier:
        return False
    current_distance = _checkpoint_distance(row, code)
    earlier_distance = _checkpoint_distance(row, earlier)
    if current_distance is not None and earlier_distance is not None:
        return current_distance > earlier_distance
    current_time = _checkpoint_cumulative(row, code)
    earlier_time = _checkpoint_cumulative(row, earlier)
    if current_time is not None and earlier_time is not None:
        return current_time > earlier_time
    # Corner positions remain valid reported evidence when their exact metric
    # location is not recorded. No new coordinates or ranks are inferred.
    return True


def _pace_style(samples):
    if len(samples) < 2:
        return "자료 부족", f"확인 가능한 초반 통과순위 {len(samples)}회 · 최소 2회 필요"
    score = mean(samples)
    label = (
        "선행" if score <= 0.25 else "선입" if score <= 0.5 else "중단" if score <= 0.75 else "추입"
    )
    return label, (
        f"최근 {len(samples)}회 초반 상대위치 평균 {score * 100:.0f}% "
        "(0%=선두, 100%=후미). 통과순위 기반 추정이며 이번 경주의 확정 전개가 아닙니다."
    )


def _metrics(history, distance, meet, cutoff, distance_stats):
    normal = [item for item in history if item.valid_finish]
    result = {
        "normal_starts": len(normal),
        "abnormal_starts": len(history) - len(normal),
        "wins": sum(item.finish_position == 1 for item in normal),
        "top3_rate": round(sum(item.finish_position <= 3 for item in normal) / len(normal) * 100, 1)
        if normal
        else None,
        "avg_finish": round(mean(item.finish_position for item in normal), 1) if normal else None,
        "same_distance_best_ms": distance_stats.get("best_ms"),
        "same_distance_best": format_race_time(distance_stats.get("best_ms")),
        "same_distance_starts": distance_stats.get("starts", 0),
        "distance_scope": "기간 조건 내 같은 경기장·거리의 전체 정상 완주",
        "days_since_last": (cutoff - date.fromisoformat(history[0].date)).days if history else None,
        "last_start_days": (cutoff - date.fromisoformat(history[0].date)).days if history else None,
        "recent_finishes": [
            item.finish_position if item.valid_finish else None for item in history[:6]
        ],
        "history_scope": "표시된 최근 경주 내 집계",
    }
    expected_s1f = 210 if meet == 2 and distance in {1110, 1610} else 200
    for code in ("S1F", "G3F", "G1F"):
        values = []
        for item in normal:
            if item.meet_code != meet:
                continue
            if code == "S1F":
                observed_s1f = 210 if item.meet_code == 2 and item.distance in {1110, 1610} else 200
                if observed_s1f != expected_s1f:
                    continue
            value = item.section_details.get(code, {}).get("time_ms")
            if value is not None:
                values.append(value)
        result[f"avg_{code.lower()}_ms"] = round(mean(values)) if values else None
        result[f"avg_{code.lower()}_samples"] = len(values)
    result["s1f_distance_m"] = expected_s1f
    return result


def _condition(weather: str | None, track: str | None, moisture: float | None) -> str:
    parts = [value for value in (weather, track) if value]
    if moisture is not None:
        parts.append(f"함수율 {moisture:g}%")
    return " · ".join(parts) or "—"


def _weight(value):
    return f"{value:g}kg" if value is not None else "—"


def _format_section(elapsed_ms: int | None, position: int | None) -> str:
    parts = []
    if elapsed_ms is not None:
        parts.append(format_race_time(elapsed_ms))
    if position is not None:
        parts.append(f"{position}위")
    return " · ".join(parts) or "—"
