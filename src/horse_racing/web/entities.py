from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload

from horse_racing.db.models import (
    EntryEquipment,
    Horse,
    HorseGradeChange,
    HorseMedical,
    HorseProfileSnapshot,
    HorseRatingSnapshot,
    HorseStartTraining,
    HorseTraining,
    HorseWeightHistory,
    Jockey,
    JockeyChange,
    Owner,
    Race,
    RaceEntry,
    RaceResult,
    RaceScratch,
    RunningTrial,
    RunningTrialResult,
    Trainer,
)
from horse_racing.web.formatting import (
    format_age,
    format_finish_position,
    format_margin,
    format_race_time,
    format_rating,
    page_window,
    today_seoul,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
MAX_HISTORY_ROWS = 200
MAX_HORSE_AUX_ROWS = 30

MEET_LABELS = {1: "서울", 2: "제주", 3: "부산경남", 4: "영천"}


@dataclass(frozen=True, slots=True)
class EntityKind:
    slug: str
    label: str
    plural_label: str
    id_label: str
    model: type
    id_attr: str


ENTITY_KINDS: dict[str, EntityKind] = {
    "horses": EntityKind(
        slug="horses",
        label="말",
        plural_label="말",
        id_label="마번",
        model=Horse,
        id_attr="kra_horse_id",
    ),
    "jockeys": EntityKind(
        slug="jockeys",
        label="기수",
        plural_label="기수",
        id_label="기수번호",
        model=Jockey,
        id_attr="kra_jockey_id",
    ),
    "trainers": EntityKind(
        slug="trainers",
        label="조교사",
        plural_label="조교사",
        id_label="조교사번호",
        model=Trainer,
        id_attr="kra_trainer_id",
    ),
    "owners": EntityKind(
        slug="owners",
        label="마주",
        plural_label="마주",
        id_label="마주번호",
        model=Owner,
        id_attr="kra_owner_id",
    ),
}


@dataclass(frozen=True, slots=True)
class EntityListItem:
    id: int
    official_id: str
    name_ko: str
    subtitle: str
    entry_count: int
    latest_rating: str
    weight_count: int
    training_count: int
    medical_count: int


@dataclass(frozen=True, slots=True)
class HorseHistoryCoverage:
    rating_snapshots: int
    weight_rows: int
    training_rows: int
    medical_rows: int
    horses_with_weights: int
    horses_with_training: int
    horses_with_medical: int


@dataclass(frozen=True, slots=True)
class EntityListPage:
    kind: EntityKind
    items: list[EntityListItem]
    query: str
    sort: str
    page: int
    page_size: int
    total_count: int
    total_pages: int
    page_items: list[int]
    history_coverage: HorseHistoryCoverage | None


@dataclass(frozen=True, slots=True)
class HistoryRow:
    race_date: date
    course_name: str
    race_number: int
    distance: str
    horse_number: int
    horse_name: str
    horse_id: int | None
    jockey_name: str
    jockey_id: int | None
    trainer_name: str
    trainer_id: int | None
    owner_name: str
    owner_id: int | None
    finish_position: str
    finish_sort: int
    finish_time: str
    margin: str
    dashboard_href: str


@dataclass(frozen=True, slots=True)
class RatingRow:
    observed_label: str
    meet_label: str
    rating_1: str
    rating_2: str
    rating_3: str
    rating_4: str


@dataclass(frozen=True, slots=True)
class WeightRow:
    race_date: date
    meet_label: str
    race_label: str
    body_weight: str
    change: str


@dataclass(frozen=True, slots=True)
class TrainingRow:
    training_date: date
    meet_label: str
    trainer_name: str
    duration: str
    canter: str
    gallop: str
    entry_plan: str


@dataclass(frozen=True, slots=True)
class MedicalRow:
    clinic_date: date
    meet_label: str
    hospital: str
    diagnosis: str


@dataclass(frozen=True, slots=True)
class RunningTrialRow:
    trial_date: date
    meet_label: str
    race_label: str
    distance: str
    judgement: str
    judgement_class: str
    position: str
    finish_time: str
    body_weight: str
    sections: str
    reason: str
    jockey_name: str
    trainer_name: str


@dataclass(frozen=True, slots=True)
class GradeChangeRow:
    start_date: str
    end_date: str
    meet_label: str
    grade_before: str
    grade_after: str
    blood_type: str


@dataclass(frozen=True, slots=True)
class EquipmentRow:
    race_date: date
    meet_label: str
    race_label: str
    equipment: str
    bleeding: str
    illness: str


@dataclass(frozen=True, slots=True)
class StartTrainingRow:
    training_date: date
    meet_label: str
    rider_name: str
    stable: str
    remark: str


@dataclass(frozen=True, slots=True)
class HorseJockeyChangeRow:
    race_date: date
    meet_label: str
    race_label: str
    before_name: str
    after_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class HorseScratchRow:
    race_date: date
    meet_label: str
    race_label: str
    reason: str


@dataclass(frozen=True, slots=True)
class ProfileSnapshotRow:
    observed_label: str
    meet_label: str
    grade: str
    rating: str
    career_record: str
    year_record: str
    prize_money: str
    trainer_name: str
    owner_name: str
    last_sale: str


@dataclass(frozen=True, slots=True)
class EntityDetail:
    kind: EntityKind
    id: int
    official_id: str
    name_ko: str
    meta_rows: list[tuple[str, str]]
    entry_count: int
    win_count: int
    place_count: int
    win_rate: str
    history: list[HistoryRow]
    ratings: list[RatingRow]
    weights: list[WeightRow]
    training: list[TrainingRow]
    medical: list[MedicalRow]
    running_trials: list[RunningTrialRow]
    rating_count: int
    weight_count: int
    training_count: int
    medical_count: int
    running_trial_count: int
    profile: ProfileSnapshotRow | None
    grade_changes: list[GradeChangeRow]
    equipment: list[EquipmentRow]
    start_training: list[StartTrainingRow]
    jockey_changes: list[HorseJockeyChangeRow]
    scratches: list[HorseScratchRow]
    grade_change_count: int
    equipment_count: int
    start_training_count: int
    jockey_change_count: int
    scratch_count: int


def load_entity_list(
    session: Session,
    *,
    kind_slug: str,
    query: str = "",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort: str = "starts",
) -> EntityListPage | None:
    kind = ENTITY_KINDS.get(kind_slug)
    if kind is None:
        return None

    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    cleaned_query = query.strip()
    sort_key = sort if sort in {"starts", "name"} else "starts"
    model = kind.model
    official_id_column = getattr(model, kind.id_attr)

    filters = []
    if cleaned_query:
        pattern = f"%{cleaned_query}%"
        filters.append(
            or_(
                model.name_ko.like(pattern),
                official_id_column.like(pattern),
            )
        )

    count_statement: Select[tuple[int]] = select(func.count()).select_from(model)
    if filters:
        count_statement = count_statement.where(*filters)
    total_count = int(session.scalar(count_statement) or 0)
    total_pages = max((total_count + page_size - 1) // page_size, 1) if total_count else 1
    page = min(page, total_pages)

    entry_count = (
        select(func.count(RaceEntry.id))
        .where(_entry_foreign_key(kind) == model.id)
        .correlate(model)
        .scalar_subquery()
    )
    statement = select(model, entry_count.label("entry_count"))
    if sort_key == "name":
        statement = statement.order_by(model.name_ko, model.id)
    else:
        statement = statement.order_by(entry_count.desc(), model.name_ko, model.id)
    if filters:
        statement = statement.where(*filters)
    statement = statement.offset((page - 1) * page_size).limit(page_size)
    rows = session.execute(statement).all()
    horse_ids = [entity.id for entity, _ in rows] if kind.slug == "horses" else []
    history_stats = _load_horse_list_history(session, horse_ids) if horse_ids else {}

    items = [
        EntityListItem(
            id=entity.id,
            official_id=getattr(entity, kind.id_attr),
            name_ko=entity.name_ko,
            subtitle=_list_subtitle(kind, entity),
            entry_count=int(entry_total or 0),
            latest_rating=history_stats.get(entity.id, ("—", 0, 0, 0))[0],
            weight_count=history_stats.get(entity.id, ("—", 0, 0, 0))[1],
            training_count=history_stats.get(entity.id, ("—", 0, 0, 0))[2],
            medical_count=history_stats.get(entity.id, ("—", 0, 0, 0))[3],
        )
        for entity, entry_total in rows
    ]
    return EntityListPage(
        kind=kind,
        items=items,
        query=cleaned_query,
        sort=sort_key,
        page=page,
        page_size=page_size,
        total_count=total_count,
        total_pages=total_pages,
        page_items=page_window(page, total_pages),
        history_coverage=_load_history_coverage(session) if kind.slug == "horses" else None,
    )


def load_entity_detail(session: Session, *, kind_slug: str, entity_id: int) -> EntityDetail | None:
    kind = ENTITY_KINDS.get(kind_slug)
    if kind is None:
        return None

    entity = session.get(kind.model, entity_id)
    if entity is None:
        return None

    fk_column = _entry_foreign_key(kind)
    entries = list(
        session.scalars(
            select(RaceEntry)
            .join(RaceEntry.race)
            .where(fk_column == entity_id)
            .options(
                joinedload(RaceEntry.race).joinedload(Race.racecourse),
                joinedload(RaceEntry.horse),
                joinedload(RaceEntry.jockey),
                joinedload(RaceEntry.trainer),
                joinedload(RaceEntry.owner),
                joinedload(RaceEntry.result),
            )
            .order_by(Race.race_date_local.desc(), Race.race_number.desc())
            .limit(MAX_HISTORY_ROWS)
        ).unique()
    )

    entry_count = int(
        session.scalar(select(func.count()).select_from(RaceEntry).where(fk_column == entity_id))
        or 0
    )
    win_count = int(
        session.scalar(
            select(func.count())
            .select_from(RaceResult)
            .join(RaceEntry)
            .where(fk_column == entity_id, RaceResult.finish_position == 1)
        )
        or 0
    )
    place_count = int(
        session.scalar(
            select(func.count())
            .select_from(RaceResult)
            .join(RaceEntry)
            .where(
                fk_column == entity_id,
                RaceResult.finish_position.is_not(None),
                RaceResult.finish_position <= 3,
            )
        )
        or 0
    )

    history = [_history_row(entry) for entry in entries]
    ratings: list[RatingRow] = []
    weights: list[WeightRow] = []
    training: list[TrainingRow] = []
    medical: list[MedicalRow] = []
    running_trials: list[RunningTrialRow] = []
    grade_changes: list[GradeChangeRow] = []
    equipment: list[EquipmentRow] = []
    start_training: list[StartTrainingRow] = []
    jockey_changes: list[HorseJockeyChangeRow] = []
    scratches: list[HorseScratchRow] = []
    rating_count = weight_count = training_count = medical_count = running_trial_count = 0
    grade_change_count = equipment_count = start_training_count = 0
    jockey_change_count = scratch_count = 0
    profile: ProfileSnapshotRow | None = None
    meta_rows = _detail_meta(kind, entity)
    if kind.slug == "horses":
        assert isinstance(entity, Horse)
        ratings = _load_ratings(session, entity_id)
        weights = _load_weights(session, entity_id)
        training = _load_training(session, entity_id)
        medical = _load_medical(session, entity_id)
        running_trials = _load_running_trials(session, entity_id)
        grade_changes = _load_grade_changes(session, entity_id)
        equipment = _load_equipment(session, entity_id)
        start_training = _load_start_training(session, entity_id)
        jockey_changes = _load_horse_jockey_changes(session, entity_id)
        scratches = _load_horse_scratches(session, entity_id)
        rating_count = _count_for_horse(session, HorseRatingSnapshot, entity_id)
        weight_count = _count_for_horse(session, HorseWeightHistory, entity_id)
        training_count = _count_for_horse(session, HorseTraining, entity_id)
        medical_count = _count_for_horse(session, HorseMedical, entity_id)
        running_trial_count = _count_for_horse(session, RunningTrialResult, entity_id)
        grade_change_count = _count_for_horse(session, HorseGradeChange, entity_id)
        equipment_count = _count_for_horse(session, EntryEquipment, entity_id)
        start_training_count = _count_for_horse(session, HorseStartTraining, entity_id)
        jockey_change_count = _count_for_horse(session, JockeyChange, entity_id)
        scratch_count = _count_for_horse(session, RaceScratch, entity_id)
        profile = _load_latest_profile(session, entity_id)
        meta_rows = _horse_detail_meta(
            entity,
            profile,
            weight_count,
            training_count,
            medical_count,
            running_trial_count,
        )

    return EntityDetail(
        kind=kind,
        id=entity.id,
        official_id=getattr(entity, kind.id_attr),
        name_ko=entity.name_ko,
        meta_rows=meta_rows,
        entry_count=entry_count,
        win_count=win_count,
        place_count=place_count,
        win_rate=_win_rate(win_count, entry_count),
        history=history,
        ratings=ratings,
        weights=weights,
        training=training,
        medical=medical,
        running_trials=running_trials,
        rating_count=rating_count,
        weight_count=weight_count,
        training_count=training_count,
        medical_count=medical_count,
        running_trial_count=running_trial_count,
        profile=profile,
        grade_changes=grade_changes,
        equipment=equipment,
        start_training=start_training,
        jockey_changes=jockey_changes,
        scratches=scratches,
        grade_change_count=grade_change_count,
        equipment_count=equipment_count,
        start_training_count=start_training_count,
        jockey_change_count=jockey_change_count,
        scratch_count=scratch_count,
    )


def _win_rate(wins: int, starts: int) -> str:
    if starts <= 0:
        return "—"
    return f"{wins / starts * 100:.1f}%"


def _entry_foreign_key(kind: EntityKind):
    mapping = {
        "horses": RaceEntry.horse_id,
        "jockeys": RaceEntry.jockey_id,
        "trainers": RaceEntry.trainer_id,
        "owners": RaceEntry.owner_id,
    }
    return mapping[kind.slug]


def _list_subtitle(kind: EntityKind, entity: Horse | Jockey | Trainer | Owner) -> str:
    if isinstance(entity, Horse):
        parts = [
            part
            for part in (
                format_age(entity.birth_date, today_seoul()),
                entity.origin_country,
                entity.sex,
                entity.grade,
            )
            if part and part != "—"
        ]
        return " · ".join(parts) if parts else "정보 없음"
    return kind.id_label


def _detail_meta(
    kind: EntityKind,
    entity: Horse | Jockey | Trainer | Owner,
) -> list[tuple[str, str]]:
    rows = [(kind.id_label, getattr(entity, kind.id_attr))]
    if isinstance(entity, Horse):
        as_of = today_seoul()
        rows.extend(
            [
                ("영문 마명", entity.name_en or "—"),
                ("나이", format_age(entity.birth_date, as_of)),
                ("성별", entity.sex or "—"),
                ("산지", entity.origin_country or "—"),
                (
                    "생년월일",
                    entity.birth_date.isoformat() if entity.birth_date is not None else "—",
                ),
            ]
        )
    else:
        rows.append(("영문 이름", entity.name_en or "—"))
    return rows


def _horse_detail_meta(
    horse: Horse,
    profile: ProfileSnapshotRow | None,
    weight_count: int,
    training_count: int,
    medical_count: int,
    running_trial_count: int,
) -> list[tuple[str, str]]:
    as_of = today_seoul()
    rows = [
        ("마번", horse.kra_horse_id),
        ("영문 마명", horse.name_en or "—"),
        ("나이", format_age(horse.birth_date, as_of)),
        ("성별", horse.sex or "—"),
        ("산지", horse.origin_country or "—"),
        (
            "생년월일",
            horse.birth_date.isoformat() if horse.birth_date is not None else "—",
        ),
        ("등급", horse.grade or "—"),
        ("소속", _meet_label(horse.meet_code) if horse.meet_code else "—"),
        ("부마", horse.sire_name or "—"),
        ("모마", horse.dam_name or "—"),
        ("거래가", horse.last_sale_amount_raw or "—"),
    ]
    if profile is not None:
        rows.extend(
            [
                ("프로필 관측", profile.observed_label),
                ("현재 레이팅", profile.rating),
                ("통산 성적", profile.career_record),
                ("올해 성적", profile.year_record),
                ("통산 상금", profile.prize_money),
                ("조교사", profile.trainer_name),
                ("마주", profile.owner_name),
            ]
        )
    if weight_count:
        rows.append(("체중 이력", f"{weight_count:,}건"))
    if training_count:
        rows.append(("훈련 이력", f"{training_count:,}건"))
    if medical_count:
        rows.append(("진료 이력", f"{medical_count:,}건"))
    if running_trial_count:
        rows.append(("주행심사", f"{running_trial_count:,}건"))
    return rows


def _history_row(entry: RaceEntry) -> HistoryRow:
    race = entry.race
    result = entry.result
    finish_position = result.finish_position if result is not None else None
    finish_label, finish_sort, _special = format_finish_position(
        finish_position, scratched=entry.scratched
    )
    return HistoryRow(
        race_date=race.race_date_local,
        course_name=race.racecourse.name_ko,
        race_number=race.race_number,
        distance=f"{race.distance_m:,}m",
        horse_number=entry.horse_number,
        horse_name=entry.horse.name_ko,
        horse_id=entry.horse_id,
        jockey_name=entry.jockey.name_ko if entry.jockey else "—",
        jockey_id=entry.jockey_id,
        trainer_name=entry.trainer.name_ko if entry.trainer else "—",
        trainer_id=entry.trainer_id,
        owner_name=entry.owner.name_ko if entry.owner else "—",
        owner_id=entry.owner_id,
        finish_position=finish_label,
        finish_sort=finish_sort,
        finish_time=format_race_time(result.finish_time_ms if result else None),
        margin=format_margin(result.margin_text if result else None, missing="-"),
        dashboard_href=f"/races/{race.id}",
    )


def _load_ratings(session: Session, horse_id: int) -> list[RatingRow]:
    rows = list(
        session.scalars(
            select(HorseRatingSnapshot)
            .where(HorseRatingSnapshot.horse_id == horse_id)
            .order_by(HorseRatingSnapshot.observed_at_ms.desc())
            .limit(MAX_HORSE_AUX_ROWS)
        )
    )
    return [
        RatingRow(
            observed_label=_format_observed_ms(row.observed_at_ms),
            meet_label=_meet_label(row.meet_code),
            rating_1=format_rating(row.rating_1),
            rating_2=format_rating(row.rating_2),
            rating_3=format_rating(row.rating_3),
            rating_4=format_rating(row.rating_4),
        )
        for row in rows
    ]


def _load_weights(session: Session, horse_id: int) -> list[WeightRow]:
    rows = list(
        session.scalars(
            select(HorseWeightHistory)
            .where(HorseWeightHistory.horse_id == horse_id)
            .order_by(
                HorseWeightHistory.race_date_local.desc(),
                HorseWeightHistory.race_number.desc(),
            )
            .limit(MAX_HORSE_AUX_ROWS)
        )
    )
    return [
        WeightRow(
            race_date=row.race_date_local,
            meet_label=_meet_label(row.meet_code),
            race_label=(
                f"{row.race_number}R · {row.horse_number}번"
                if row.race_number is not None and row.horse_number is not None
                else "—"
            ),
            body_weight=_format_kg(row.body_weight_kg),
            change=_format_change_kg(row.body_weight_change_kg),
        )
        for row in rows
    ]


def _load_training(session: Session, horse_id: int) -> list[TrainingRow]:
    rows = list(
        session.scalars(
            select(HorseTraining)
            .where(HorseTraining.horse_id == horse_id)
            .order_by(
                HorseTraining.training_date_local.desc(),
                HorseTraining.started_at_raw.desc(),
            )
            .limit(MAX_HORSE_AUX_ROWS)
        )
    )
    return [
        TrainingRow(
            training_date=row.training_date_local,
            meet_label=_meet_label(row.meet_code),
            trainer_name=row.trainer_name or "—",
            duration=_format_duration(row.duration_seconds),
            canter=_format_count(row.canter_count),
            gallop=_format_count(row.gallop_count),
            entry_plan=row.entry_plan or "—",
        )
        for row in rows
    ]


def _load_medical(session: Session, horse_id: int) -> list[MedicalRow]:
    rows = list(
        session.scalars(
            select(HorseMedical)
            .where(HorseMedical.horse_id == horse_id)
            .order_by(HorseMedical.clinic_date_local.desc())
            .limit(MAX_HORSE_AUX_ROWS)
        )
    )
    return [
        MedicalRow(
            clinic_date=row.clinic_date_local,
            meet_label=_meet_label(row.meet_code),
            hospital=row.hospital_name or "—",
            diagnosis=_format_diagnosis(row.diagnosis_1, row.diagnosis_2),
        )
        for row in rows
    ]


def _load_running_trials(session: Session, horse_id: int) -> list[RunningTrialRow]:
    rows = session.execute(
        select(RunningTrialResult, RunningTrial)
        .join(RunningTrial, RunningTrial.id == RunningTrialResult.running_trial_id)
        .where(RunningTrialResult.horse_id == horse_id)
        .order_by(
            RunningTrial.trial_date_local.desc(),
            RunningTrial.trial_race_number.desc(),
        )
        .limit(MAX_HORSE_AUX_ROWS)
    ).all()
    return [
        RunningTrialRow(
            trial_date=trial.trial_date_local,
            meet_label=_meet_label(trial.meet_code),
            race_label=f"{trial.trial_race_number}R",
            distance=f"{trial.distance_m:,}m",
            judgement=_trial_judgement_label(result.judgement),
            judgement_class=_trial_judgement_class(result.judgement),
            position=(
                f"{result.finish_position}위" if result.finish_position is not None else "—"
            ),
            finish_time=format_race_time(result.finish_time_ms),
            body_weight=_format_kg(result.body_weight_kg),
            sections=_format_trial_sections(result),
            reason=_format_trial_reason(result.failure_reason, result.inspection_reason),
            jockey_name=result.jockey_name_raw or "—",
            trainer_name=result.trainer_name_raw or "—",
        )
        for result, trial in rows
    ]


def _load_grade_changes(session: Session, horse_id: int) -> list[GradeChangeRow]:
    rows = list(
        session.scalars(
            select(HorseGradeChange)
            .where(HorseGradeChange.horse_id == horse_id)
            .order_by(HorseGradeChange.start_date_local.desc())
            .limit(MAX_HORSE_AUX_ROWS)
        )
    )
    return [
        GradeChangeRow(
            start_date=_format_date(row.start_date_local),
            end_date=_format_date(row.end_date_local),
            meet_label=_meet_label(row.meet_code),
            grade_before=row.grade_before or "—",
            grade_after=row.grade_after or "—",
            blood_type=row.blood_type or "—",
        )
        for row in rows
    ]


def _load_equipment(session: Session, horse_id: int) -> list[EquipmentRow]:
    rows = list(
        session.scalars(
            select(EntryEquipment)
            .where(EntryEquipment.horse_id == horse_id)
            .order_by(
                EntryEquipment.race_date_local.desc(),
                EntryEquipment.race_number.desc(),
            )
            .limit(MAX_HORSE_AUX_ROWS)
        )
    )
    return [
        EquipmentRow(
            race_date=row.race_date_local,
            meet_label=_meet_label(row.meet_code),
            race_label=f"{row.race_number}R",
            equipment=row.equipment_raw or "—",
            bleeding=_format_bleeding(row.bleeding_count, row.bleeding_date_raw),
            illness=row.illness_note or "—",
        )
        for row in rows
    ]


def _load_start_training(session: Session, horse_id: int) -> list[StartTrainingRow]:
    rows = list(
        session.scalars(
            select(HorseStartTraining)
            .where(HorseStartTraining.horse_id == horse_id)
            .order_by(HorseStartTraining.training_date_local.desc())
            .limit(MAX_HORSE_AUX_ROWS)
        )
    )
    return [
        StartTrainingRow(
            training_date=row.training_date_local,
            meet_label=_meet_label(row.meet_code),
            rider_name=row.rider_name or "—",
            stable=_format_stable(row.stable_part, row.stable_number),
            remark=row.remark or "—",
        )
        for row in rows
    ]


def _load_horse_jockey_changes(
    session: Session, horse_id: int
) -> list[HorseJockeyChangeRow]:
    rows = list(
        session.scalars(
            select(JockeyChange)
            .where(JockeyChange.horse_id == horse_id)
            .order_by(
                JockeyChange.race_date_local.desc(),
                JockeyChange.race_number.desc(),
            )
            .limit(MAX_HORSE_AUX_ROWS)
        )
    )
    return [
        HorseJockeyChangeRow(
            race_date=row.race_date_local,
            meet_label=_meet_label(row.meet_code),
            race_label=f"{row.race_number}R · {row.horse_number}번",
            before_name=row.jockey_before_name or "—",
            after_name=row.jockey_after_name or "—",
            reason=row.reason or "—",
        )
        for row in rows
    ]


def _load_horse_scratches(session: Session, horse_id: int) -> list[HorseScratchRow]:
    rows = list(
        session.scalars(
            select(RaceScratch)
            .where(RaceScratch.horse_id == horse_id)
            .order_by(
                RaceScratch.race_date_local.desc(),
                RaceScratch.race_number.desc(),
            )
            .limit(MAX_HORSE_AUX_ROWS)
        )
    )
    return [
        HorseScratchRow(
            race_date=row.race_date_local,
            meet_label=_meet_label(row.meet_code),
            race_label=(
                f"{row.race_number}R · {row.horse_number}번"
                if row.horse_number is not None
                else f"{row.race_number}R"
            ),
            reason=row.reason or "—",
        )
        for row in rows
    ]


def _format_date(value: date | None) -> str:
    return value.strftime("%Y.%m.%d") if value is not None else "—"


def _format_bleeding(count: int | None, date_raw: str | None) -> str:
    if count is None and not date_raw:
        return "—"
    parts = []
    if count is not None:
        parts.append(f"{count}회")
    if date_raw:
        parts.append(date_raw)
    return " · ".join(parts) if parts else "—"


def _format_stable(part: int | None, number: int | None) -> str:
    if part is None and number is None:
        return "—"
    if part is not None and number is not None:
        return f"{part}조 {number}"
    if part is not None:
        return f"{part}조"
    return str(number)


def _load_latest_profile(session: Session, horse_id: int) -> ProfileSnapshotRow | None:
    row = session.scalar(
        select(HorseProfileSnapshot)
        .where(HorseProfileSnapshot.horse_id == horse_id)
        .order_by(HorseProfileSnapshot.observed_at_ms.desc())
        .limit(1)
    )
    if row is None:
        return None
    return ProfileSnapshotRow(
        observed_label=_format_observed_ms(row.observed_at_ms),
        meet_label=_meet_label(row.meet_code),
        grade=row.grade or "—",
        rating=format_rating(row.rating),
        career_record=_format_place_record(
            row.race_count_total,
            row.win_count_total,
            row.second_count_total,
            row.third_count_total,
        ),
        year_record=_format_place_record(
            row.race_count_year,
            row.win_count_year,
            row.second_count_year,
            row.third_count_year,
        ),
        prize_money=(
            f"{row.prize_money_total_krw:,}원"
            if row.prize_money_total_krw is not None
            else "—"
        ),
        trainer_name=row.trainer_name or "—",
        owner_name=row.owner_name or "—",
        last_sale=row.last_sale_amount_raw or "—",
    )


def _format_place_record(
    starts: int | None,
    wins: int | None,
    seconds: int | None,
    thirds: int | None,
) -> str:
    if starts is None and wins is None and seconds is None and thirds is None:
        return "—"
    return (
        f"{starts or 0}전 "
        f"{wins or 0}/{seconds or 0}/{thirds or 0}"
    )


def _meet_label(meet_code: int | None) -> str:
    if meet_code is None:
        return "—"
    return MEET_LABELS.get(meet_code, str(meet_code))


def _format_observed_ms(observed_at_ms: int) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    when = datetime.fromtimestamp(observed_at_ms / 1000, tz=ZoneInfo("Asia/Seoul"))
    return when.strftime("%Y.%m.%d %H:%M")


def _format_number(value: float | None) -> str:
    if value is None:
        return "—"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _format_kg(value: int | None) -> str:
    return f"{value}kg" if value is not None else "—"


def _format_change_kg(value: int | None) -> str:
    if value is None:
        return "—"
    if value > 0:
        return f"+{value}"
    return str(value)


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    minutes, rem = divmod(seconds, 60)
    if minutes and rem:
        return f"{minutes}분 {rem}초"
    if minutes:
        return f"{minutes}분"
    return f"{rem}초"


def _format_count(value: int | None) -> str:
    return str(value) if value is not None else "—"


def _format_diagnosis(first: str | None, second: str | None) -> str:
    parts = [part for part in (first, second) if part]
    return " · ".join(parts) if parts else "—"


def _trial_judgement_label(value: str | None) -> str:
    labels = {
        "합": "합격",
        "불": "불합격",
        "유": "유보",
        "연": "연습",
        "출": "심사제외",
        "심": "심사취소",
        "주": "주행중지",
    }
    return labels.get(value or "", value or "—")


def _trial_judgement_class(value: str | None) -> str:
    if value == "합":
        return "pass"
    if value in {"불", "출", "심", "주"}:
        return "fail"
    return "neutral"


def _format_trial_sections(result: RunningTrialResult) -> str:
    values = (
        ("S1F", result.s1f_ms),
        ("G3F", result.g3f_ms),
        ("G1F", result.g1f_ms),
    )
    parts = [
        f"{label} {milliseconds / 1000:.1f}"
        for label, milliseconds in values
        if milliseconds
    ]
    return " · ".join(parts) if parts else "—"


def _format_trial_reason(failure: str | None, inspection: str | None) -> str:
    parts = [part for part in (failure, inspection) if part]
    return " · ".join(parts) if parts else "—"


def _count_for_horse(session: Session, model: type, horse_id: int) -> int:
    return int(
        session.scalar(select(func.count()).select_from(model).where(model.horse_id == horse_id))
        or 0
    )


def _load_history_coverage(session: Session) -> HorseHistoryCoverage:
    return HorseHistoryCoverage(
        rating_snapshots=int(
            session.scalar(select(func.count()).select_from(HorseRatingSnapshot)) or 0
        ),
        weight_rows=int(session.scalar(select(func.count()).select_from(HorseWeightHistory)) or 0),
        training_rows=int(session.scalar(select(func.count()).select_from(HorseTraining)) or 0),
        medical_rows=int(session.scalar(select(func.count()).select_from(HorseMedical)) or 0),
        horses_with_weights=int(
            session.scalar(select(func.count(func.distinct(HorseWeightHistory.horse_id)))) or 0
        ),
        horses_with_training=int(
            session.scalar(select(func.count(func.distinct(HorseTraining.horse_id)))) or 0
        ),
        horses_with_medical=int(
            session.scalar(select(func.count(func.distinct(HorseMedical.horse_id)))) or 0
        ),
    )


def _load_horse_list_history(
    session: Session,
    horse_ids: list[int],
) -> dict[int, tuple[str, int, int, int]]:
    if not horse_ids:
        return {}

    weight_counts = dict(
        session.execute(
            select(HorseWeightHistory.horse_id, func.count())
            .where(HorseWeightHistory.horse_id.in_(horse_ids))
            .group_by(HorseWeightHistory.horse_id)
        ).all()
    )
    training_counts = dict(
        session.execute(
            select(HorseTraining.horse_id, func.count())
            .where(HorseTraining.horse_id.in_(horse_ids))
            .group_by(HorseTraining.horse_id)
        ).all()
    )
    medical_counts = dict(
        session.execute(
            select(HorseMedical.horse_id, func.count())
            .where(HorseMedical.horse_id.in_(horse_ids))
            .group_by(HorseMedical.horse_id)
        ).all()
    )

    latest_rating_subq = (
        select(
            HorseRatingSnapshot.horse_id.label("horse_id"),
            func.max(HorseRatingSnapshot.observed_at_ms).label("max_observed"),
        )
        .where(HorseRatingSnapshot.horse_id.in_(horse_ids))
        .group_by(HorseRatingSnapshot.horse_id)
        .subquery()
    )
    rating_rows = session.execute(
        select(HorseRatingSnapshot.horse_id, HorseRatingSnapshot.rating_4)
        .join(
            latest_rating_subq,
            (HorseRatingSnapshot.horse_id == latest_rating_subq.c.horse_id)
            & (HorseRatingSnapshot.observed_at_ms == latest_rating_subq.c.max_observed),
        )
    ).all()
    ratings = {horse_id: format_rating(rating_4) for horse_id, rating_4 in rating_rows}

    return {
        horse_id: (
            ratings.get(horse_id, "—"),
            int(weight_counts.get(horse_id, 0)),
            int(training_counts.get(horse_id, 0)),
            int(medical_counts.get(horse_id, 0)),
        )
        for horse_id in horse_ids
    }
