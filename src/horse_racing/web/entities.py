from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple
from urllib.parse import quote, urlencode

from sqlalchemy import Select, case, extract, func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from horse_racing.db.models import (
    EntryEquipment,
    Horse,
    HorseGradeChange,
    HorseMedical,
    HorseProfileSnapshot,
    HorseStartTraining,
    HorseTraining,
    HorseWeightHistory,
    IngestionRun,
    Jockey,
    JockeyAffiliationSnapshot,
    JockeyChange,
    Owner,
    OwnerCatalogSnapshot,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RaceScratch,
    RunningTrial,
    RunningTrialResult,
    Trainer,
    TrainerAffiliationSnapshot,
    TrainerHistoricalRegion,
    TrainerIdentityResolution,
    TrainerStatusObservation,
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
from horse_racing.web.horse_directory import (
    GRADE_LABELS,
    ORIGIN_LABELS,
    grade_bucket,
    load_horse_directory_summary,
    origin_bucket,
)
from horse_racing.web.horse_evaluation import HorseEvaluation, load_horse_evaluation

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
MAX_HISTORY_ROWS = 200
MAX_HORSE_AUX_ROWS = 30

PERFORMANCE_PERIOD_LABELS = {"month": "최근 1개월", "year": "최근 1년", "career": "통산"}

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


class RecentHorseStart(NamedTuple):
    finish: str
    race_id: int
    title: str


class TrainerDirectoryStats(NamedTuple):
    stable: str = "—"
    managed_count: int = 0
    month_record: str = "0전 0/0/0"
    year_record: str = "0전 0/0/0"
    career_record: str = "0전 0/0/0"
    performance: DirectoryPerformanceStats | None = None


class DirectoryPerformanceStats(NamedTuple):
    starts: int = 0
    wins: int = 0
    seconds: int = 0
    thirds: int = 0
    win_rate: str = "—"
    quinella_rate: str = "—"
    place_rate: str = "—"


JockeyDirectoryStats = DirectoryPerformanceStats


@dataclass(frozen=True, slots=True)
class JockeyPerformanceRow:
    label: str
    stats: DirectoryPerformanceStats
    start: date | None = None


@dataclass(frozen=True, slots=True)
class JockeyPartnerRow:
    name: str
    href: str
    stats: DirectoryPerformanceStats

    @property
    def places(self) -> int:
        return self.stats.wins + self.stats.seconds + self.stats.thirds


@dataclass(frozen=True, slots=True)
class JockeyDetailData:
    region: str
    affiliation_date: date | None
    periods: list[JockeyPerformanceRow]
    years: list[JockeyPerformanceRow]
    trainers: list[JockeyPartnerRow]
    owners: list[JockeyPartnerRow]
    as_of: date
    partner_period: str = "career"
    partner_start: date | None = None
    debut_date: str = "—"
    riding_weight: str = "—"

    @property
    def partner_period_label(self) -> str:
        return PERFORMANCE_PERIOD_LABELS[self.partner_period]


@dataclass(frozen=True, slots=True)
class EntityListItem:
    id: int
    official_id: str
    name_ko: str
    subtitle: str
    entry_count: int
    last_race_rating: str
    recent_five: str
    career_record: str
    win_rate: str
    place_rate: str
    status_label: str | None = None
    status_key: str | None = None
    trainer_name: str = "—"
    owner_name: str = "—"
    trainer_href: str | None = None
    owner_href: str | None = None
    recent_starts: tuple[RecentHorseStart, ...] = ()
    trainer_stats: TrainerDirectoryStats | None = None
    jockey_stats: JockeyDirectoryStats | None = None
    owner_stats: DirectoryPerformanceStats | None = None
    owner_current_count: int | None = None
    owner_regional_counts: tuple[tuple[str, int], ...] = ()


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
    status_filter: str = "all"
    meet_filter: int | None = None
    affiliation_observed_on: date | None = None
    period: str = "career"
    period_label: str = "통산"
    period_start: date | None = None
    period_end: date | None = None
    grade_filter: str = ""
    origin_filter: str = ""
    horse_summary: dict | None = None


@dataclass(frozen=True, slots=True)
class HistoryRow:
    race_date: date
    course_name: str
    race_number: int
    distance: str
    condition: str
    horse_number: int
    horse_name: str
    horse_id: str | None
    jockey_name: str
    jockey_id: str | None
    trainer_name: str
    trainer_id: str | None
    owner_name: str
    owner_id: str | None
    finish_position: str
    finish_sort: int
    finish_time: str
    margin: str
    dashboard_href: str


@dataclass(frozen=True, slots=True)
class TrainerManagedHorse:
    official_id: str
    name_ko: str
    meet_label: str
    grade: str
    age: str
    rating: str


@dataclass(frozen=True, slots=True)
class RatingRow:
    race_date: date
    meet_label: str
    race_label: str
    rating: str


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
    location: str = "—"


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
    managed_horses: list[TrainerManagedHorse]
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
    evaluation: HorseEvaluation | None = None
    status_label: str | None = None
    status_key: str | None = None
    jockey_detail: JockeyDetailData | None = None


def load_entity_list(
    session: Session,
    *,
    kind_slug: str,
    query: str = "",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort: str = "",
    status: str = "all",
    meet: int | None = None,
    grade: str = "",
    origin: str = "",
    directory_only: bool = False,
    include_summary: bool = True,
    period: str = "career",
) -> EntityListPage | None:
    kind = ENTITY_KINDS.get(kind_slug)
    if kind is None:
        return None

    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    cleaned_query = query.strip()
    default_sort = ({"horses": "rating", "owners": "owned"}
                    .get(kind.slug, "starts"))
    allowed_sorts = ({"owned", "owned_asc", "name", "starts"} if kind.slug == "owners" else
                     {"starts", "name", "rating"} if kind.slug == "horses" else {"starts", "name"})
    if kind.slug == "owners" and sort == "registered":
        sort = "owned"  # Existing bookmarked count-sort URLs now use current ownership.
    sort_key = sort if sort in allowed_sorts else default_sort
    status_filter = (
        status
        if kind.slug == "horses"
        and status
        in {
            "all",
            "active",
            "retired",
            "unknown",
        }
        else "all"
    )
    meet_filter = (
        meet if kind.slug in {"horses", "trainers", "jockeys", "owners"}
        and meet in {1, 2, 3} else None
    )
    model = kind.model
    owner_run_id = (session.scalar(select(IngestionRun.id).where(
        IngestionRun.data_type == "owner_catalog_full", IngestionRun.status == "completed",
    ).order_by(IngestionRun.started_at_ms.desc(), IngestionRun.id.desc()).limit(1))
        if kind.slug == "owners" else None)
    grade_filter = grade if kind.slug == "horses" and grade in GRADE_LABELS else ""
    origin_filter = origin if kind.slug == "horses" and origin in ORIGIN_LABELS else ""
    if kind.slug == "horses" and directory_only:
        return EntityListPage(
            kind=kind, items=[], query=cleaned_query, sort=sort_key, page=1,
            page_size=page_size, total_count=0, total_pages=1, page_items=[1],
            status_filter="active", meet_filter=meet_filter,
            horse_summary=load_horse_directory_summary(session, meet_filter, sort_key),
        )
    has_performance = kind.slug in {"jockeys", "owners", "trainers"}
    period_key = period if has_performance and period in PERFORMANCE_PERIOD_LABELS else "career"
    official_id_column = getattr(model, kind.id_attr)
    affiliation_observed_on = (
        session.scalar(select(func.max(TrainerAffiliationSnapshot.observed_on)))
        if kind.slug == "trainers"
        else None
    )
    jockey_affiliations = {}
    if kind.slug == "jockeys":
        affiliation_observed_on = session.scalar(
            select(func.max(JockeyAffiliationSnapshot.observed_on))
        )
        jockey_affiliations = {
            row.jockey_id: row for row in session.scalars(
                select(JockeyAffiliationSnapshot).where(
                    JockeyAffiliationSnapshot.observed_on == affiliation_observed_on,
                )
            )
        }
    active_trainer_roster = (
        select(
            TrainerAffiliationSnapshot.trainer_id.label("trainer_id"),
            TrainerAffiliationSnapshot.meet_code.label("meet_code"),
        )
        .where(TrainerAffiliationSnapshot.observed_on == affiliation_observed_on)
        .subquery()
        if kind.slug == "trainers"
        else None
    )

    owner_counts = None
    if kind.slug == "owners":
        # Aggregate the selected cohort before filtering, sorting and pagination.
        # A partially unknown regional total must remain unknown, not a partial sum.
        owner_counts = select(
            OwnerCatalogSnapshot.owner_id.label("entity_id"),
            case((
                func.count() == func.count(OwnerCatalogSnapshot.current_owned_horses),
                func.sum(OwnerCatalogSnapshot.current_owned_horses),
            )).label("entry_count"),
        ).where(
            OwnerCatalogSnapshot.ingestion_run_id == owner_run_id,
            OwnerCatalogSnapshot.owner_id.is_not(None),
            *([OwnerCatalogSnapshot.meet_code == meet_filter] if meet_filter else []),
        ).group_by(OwnerCatalogSnapshot.owner_id).subquery()

    filters = []
    if kind.slug == "owners" and not cleaned_query:
        filters.append(Owner.id.in_(select(owner_counts.c.entity_id).where(
            owner_counts.c.entry_count > 0,
        )))
    if kind.slug == "owners" and meet_filter is not None:
        filters.append(select(OwnerCatalogSnapshot.kra_owner_id).where(
            OwnerCatalogSnapshot.ingestion_run_id == owner_run_id,
            OwnerCatalogSnapshot.owner_id == Owner.id,
            OwnerCatalogSnapshot.meet_code == meet_filter,
        ).exists())
    if kind.slug == "horses":
        if grade_filter:
            filters.append(grade_bucket() == grade_filter)
        if origin_filter:
            filters.append(origin_bucket() == origin_filter)
        if meet_filter is not None:
            filters.append(Horse.meet_code == meet_filter)
        if status_filter == "active":
            filters.append(Horse.is_active.is_(True))
        elif status_filter == "retired":
            filters.append(Horse.is_active.is_(False))
        elif status_filter == "unknown":
            filters.append(Horse.is_active.is_(None))
    elif kind.slug == "trainers" and meet_filter is not None:
        region = {1: "SEOUL", 2: "JEJU", 3: "YEONGNAM"}[meet_filter]
        filters.append(or_(
            active_trainer_roster.c.meet_code == meet_filter,
            (active_trainer_roster.c.trainer_id.is_(None)) & or_(
                select(TrainerStatusObservation.official_tr_no).where(
                    TrainerStatusObservation.official_tr_no == Trainer.kra_trainer_id,
                    TrainerStatusObservation.region_code == region,
                ).exists(),
                select(TrainerHistoricalRegion.trainer_id).where(
                    TrainerHistoricalRegion.trainer_id == Trainer.id,
                    TrainerHistoricalRegion.region_code == region,
                ).exists(),
                select(RaceEntry.id).join(RaceEntry.race).join(Race.racecourse).where(
                    RaceEntry.trainer_id == Trainer.id,
                    Racecourse.kra_meet_code == meet_filter,
                ).exists(),
            ),
        ) if cleaned_query else active_trainer_roster.c.meet_code == meet_filter)
    if kind.slug == "jockeys":
        # The latest complete official roster controls membership, including searches.
        # Exchange/Yeongcheon race entries never determine a jockey's base affiliation.
        filters.append(Jockey.id.in_([
            jockey_id for jockey_id, affiliation in jockey_affiliations.items()
            if meet_filter is None or affiliation.meet_code == meet_filter
        ]))
    if cleaned_query:
        pattern = f"%{cleaned_query}%"
        filters.append(
            or_(
                model.name_ko.like(pattern),
                official_id_column.like(pattern),
            )
        )

    count_statement: Select[tuple[int]] = select(func.count()).select_from(model)
    if active_trainer_roster is not None:
        count_statement = count_statement.join(
            active_trainer_roster,
            active_trainer_roster.c.trainer_id == Trainer.id,
            isouter=bool(cleaned_query),
        )
    if filters:
        count_statement = count_statement.where(*filters)
    total_count = int(session.scalar(count_statement) or 0)
    total_pages = max((total_count + page_size - 1) // page_size, 1) if total_count else 1
    page = min(page, total_pages)

    entry_foreign_key = _entry_foreign_key(kind)
    entry_counts = (
        select(
            entry_foreign_key.label("entity_id"),
            func.count(RaceEntry.id).label("entry_count"),
        )
        .where(entry_foreign_key.is_not(None))
        .group_by(entry_foreign_key)
        .subquery()
    )
    if kind.slug == "jockeys":
        entry_counts = _jockey_directory_counts_statement(
            list(jockey_affiliations), period_key,
        ).subquery()
    elif kind.slug == "owners":
        entry_counts = owner_counts
    elif kind.slug == "trainers":
        entry_counts = _trainer_directory_counts_statement(period_key).subquery()
    entry_count = (entry_counts.c.entry_count if kind.slug == "owners" else
                   func.coalesce(entry_counts.c.entry_count, 0)).label("entry_count")
    statement = select(model, entry_count).outerjoin(
        entry_counts,
        entry_counts.c.entity_id == (Trainer.kra_trainer_id if kind.slug == "trainers"
                                   else model.id),
    )
    if active_trainer_roster is not None:
        statement = statement.join(
            active_trainer_roster,
            active_trainer_roster.c.trainer_id == Trainer.id,
            isouter=bool(cleaned_query),
        )
    sort_name = model.name_ko
    if kind.slug == "jockeys":
        statement = statement.join(
            JockeyAffiliationSnapshot,
            (JockeyAffiliationSnapshot.jockey_id == Jockey.id)
            & (JockeyAffiliationSnapshot.observed_on == affiliation_observed_on),
        ).add_columns(*[
            func.coalesce(getattr(entry_counts.c, name), 0)
            for name in ("wins", "seconds", "thirds")
        ])
        sort_name = JockeyAffiliationSnapshot.official_name_ko
    if sort_key == "rating":
        ranked_ratings = (
            _last_race_ratings_statement()
            .where(RaceEntry.horse_id.in_(select(Horse.id).where(*filters)))
            .subquery()
        )
        latest_ratings = select(ranked_ratings).where(ranked_ratings.c.position == 1).subquery()
        statement = statement.outerjoin(
            latest_ratings, latest_ratings.c.horse_id == Horse.id,
        ).order_by(
            case((latest_ratings.c.rating > 0, latest_ratings.c.rating)).desc().nulls_last(),
            Horse.name_ko, Horse.id,
        )
    elif sort_key == "name":
        statement = statement.order_by(sort_name, model.id)
    elif sort_key in {"owned", "owned_asc"}:
        count_order = entry_count.asc() if sort_key == "owned_asc" else entry_count.desc()
        statement = statement.order_by(count_order.nulls_last(), sort_name, model.id)
    elif kind.slug == "owners" and sort_key == "starts":
        performance_counts = _directory_counts_statement(
            RaceEntry.owner_id, select(Owner.id).where(*filters), period_key, meet_filter,
        ).subquery()
        statement = statement.outerjoin(
            performance_counts, performance_counts.c.entity_id == Owner.id,
        ).order_by(
            func.coalesce(performance_counts.c.entry_count, 0).desc(), sort_name, model.id,
        )
    else:
        statement = statement.order_by(entry_count.desc(), sort_name, model.id)
    if filters:
        statement = statement.where(*filters)
    statement = statement.offset((page - 1) * page_size).limit(page_size)
    result_rows = session.execute(statement).all()
    jockey_stats = ({
        row[0].id: _jockey_stats_from_counts(*row[1:]) for row in result_rows
    } if kind.slug == "jockeys" else {})
    rows = [(row[0], row[1]) for row in result_rows]
    horse_ids = [entity.id for entity, _ in rows] if kind.slug == "horses" else []
    history_stats = _load_horse_list_history(session, horse_ids) if horse_ids else {}
    trainer_stats = (_load_trainer_directory_stats(
        session, [entity for entity, _ in rows], affiliation_observed_on, meet_filter, period_key,
    ) if kind.slug == "trainers" else {})
    owner_stats = (_load_owner_directory_stats(
        session, [entity.id for entity, _ in rows], period_key, meet_filter,
    ) if kind.slug == "owners" else {})
    owner_regional_counts: dict[int, list[tuple[str, int]]] = {}
    if kind.slug == "owners" and rows:
        for snapshot in session.scalars(select(OwnerCatalogSnapshot).where(
            OwnerCatalogSnapshot.ingestion_run_id == owner_run_id,
            OwnerCatalogSnapshot.owner_id.in_([entity.id for entity, _ in rows]),
            OwnerCatalogSnapshot.current_owned_horses.is_not(None),
            *([OwnerCatalogSnapshot.meet_code == meet_filter] if meet_filter else []),
        ).order_by(OwnerCatalogSnapshot.meet_code)):
            owner_regional_counts.setdefault(snapshot.owner_id, []).append((
                {1: "서울", 3: "부산", 2: "제주"}[snapshot.meet_code],
                snapshot.current_owned_horses,
            ))

    items = [
        EntityListItem(
            id=entity.id,
            official_id=getattr(entity, kind.id_attr),
            name_ko=(jockey_affiliations[entity.id].official_name_ko
                     if kind.slug == "jockeys" else entity.name_ko),
            subtitle=({1: "서울", 3: "부산", 2: "제주"}[jockey_affiliations[entity.id].meet_code]
                      if kind.slug == "jockeys" else _list_subtitle(kind, entity)),
            entry_count=int(entry_total or 0),
            last_race_rating=history_stats.get(entity.id, HorseListStats()).rating,
            recent_five=history_stats.get(entity.id, HorseListStats()).recent_five,
            career_record=history_stats.get(entity.id, HorseListStats()).career_record,
            win_rate=history_stats.get(entity.id, HorseListStats()).win_rate,
            place_rate=history_stats.get(entity.id, HorseListStats()).place_rate,
            trainer_name=history_stats.get(entity.id, HorseListStats()).trainer_name,
            owner_name=history_stats.get(entity.id, HorseListStats()).owner_name,
            trainer_href=history_stats.get(entity.id, HorseListStats()).trainer_href,
            owner_href=history_stats.get(entity.id, HorseListStats()).owner_href,
            recent_starts=history_stats.get(entity.id, HorseListStats()).recent_starts,
            trainer_stats=trainer_stats.get(entity.id),
            jockey_stats=jockey_stats.get(entity.id),
            owner_stats=owner_stats.get(entity.id),
            owner_current_count=entry_total if kind.slug == "owners" else None,
            owner_regional_counts=tuple(owner_regional_counts.get(entity.id, [])),
            status_label=_horse_status(entity.is_active)[0] if isinstance(entity, Horse) else None,
            status_key=_horse_status(entity.is_active)[1] if isinstance(entity, Horse) else None,
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
        status_filter=status_filter,
        meet_filter=meet_filter,
        affiliation_observed_on=affiliation_observed_on,
        period=period_key, period_label=PERFORMANCE_PERIOD_LABELS[period_key],
        period_start=_directory_period_start(period_key) if has_performance else None,
        period_end=today_seoul() if has_performance else None,
        grade_filter=grade_filter,
        origin_filter=origin_filter,
        horse_summary=(load_horse_directory_summary(session, meet_filter, sort_key)
                       if kind.slug == "horses" and include_summary else None),
    )


def load_entity_detail(
    session: Session, *, kind_slug: str, official_id: str, partner_period: str = "career",
) -> EntityDetail | None:
    kind = ENTITY_KINDS.get(kind_slug)
    if kind is None:
        return None

    entity = session.scalar(
        select(kind.model).where(getattr(kind.model, kind.id_attr) == official_id)
    )
    if entity is None:
        return None

    entity_id = entity.id

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
    managed_horses = (
        _load_trainer_managed_horses(session, entity.kra_trainer_id)
        if isinstance(entity, Trainer)
        else []
    )
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
    status_label: str | None = None
    status_key: str | None = None
    jockey_detail = None
    if kind.slug == "jockeys":
        jockey_detail = _load_jockey_detail(session, entity_id, partner_period)
        if jockey_detail.affiliation_date:
            status_label, status_key = "현역", "active"
    if kind.slug == "horses":
        assert isinstance(entity, Horse)
        status_label, status_key = _horse_status(entity.is_active)
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
        rating_count = int(
            session.scalar(
                _completed_starts_statement()
                .where(RaceEntry.horse_id == entity_id)
                .with_only_columns(func.count(RaceEntry.id))
            )
            or 0
        )
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
            ratings[0] if ratings else None,
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
        managed_horses=managed_horses,
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
        evaluation=load_horse_evaluation(session, entity) if isinstance(entity, Horse) else None,
        status_label=status_label,
        status_key=status_key,
        jockey_detail=jockey_detail,
    )


def load_entity_official_id(session: Session, *, kind_slug: str, internal_id: int) -> str | None:
    """Resolve a legacy database primary key to its public KRA identifier."""
    kind = ENTITY_KINDS.get(kind_slug)
    if kind is None:
        return None
    return session.scalar(
        select(getattr(kind.model, kind.id_attr)).where(kind.model.id == internal_id)
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


def _directory_period_starts() -> tuple[date, date]:
    as_of = today_seoul()
    previous_month = as_of.month - 1 or 12
    previous_year = as_of.year - (as_of.month == 1)
    month_start = date(previous_year, previous_month,
                       min(as_of.day, monthrange(previous_year, previous_month)[1]))
    year_start = date(as_of.year - 1, as_of.month,
                      min(as_of.day, monthrange(as_of.year - 1, as_of.month)[1]))
    return month_start, year_start


def _directory_period_start(period: str) -> date | None:
    month_start, year_start = _directory_period_starts()
    return {"month": month_start, "year": year_start}.get(period)


def _directory_counts_statement(entity_fk, entity_ids, period: str, meet: int | None = None):
    statement = _completed_starts_statement().where(entity_fk.in_(entity_ids))
    if meet is not None:
        statement = statement.join(Race.racecourse).where(Racecourse.kra_meet_code == meet)
    start = _directory_period_start(period)
    if start:
        statement = statement.where(Race.race_date_local >= start)
    return statement.with_only_columns(
        entity_fk.label("entity_id"), func.count().label("entry_count"),
        *[func.count().filter(
            RaceResult.finish_position == rank, RaceResult.disqualified.is_(False),
        ).label(name) for rank, name in ((1, "wins"), (2, "seconds"), (3, "thirds"))],
    ).group_by(entity_fk)


def _jockey_directory_counts_statement(jockey_ids: list[int], period: str) -> Select:
    return _directory_counts_statement(RaceEntry.jockey_id, jockey_ids, period)


def _jockey_stats_from_counts(
    starts: int, wins: int, seconds: int, thirds: int,
) -> JockeyDirectoryStats:
    return JockeyDirectoryStats(
        starts=starts, wins=wins, seconds=seconds, thirds=thirds,
        win_rate=_win_rate(wins, starts),
        quinella_rate=_win_rate(wins + seconds, starts),
        place_rate=_win_rate(wins + seconds + thirds, starts),
    )


def _load_jockey_directory_stats(
    session: Session, jockey_ids: list[int], period: str = "career",
) -> dict[int, JockeyDirectoryStats]:
    if not jockey_ids:
        return {}
    records = {row[0]: _jockey_stats_from_counts(*row[1:]) for row in session.execute(
        _jockey_directory_counts_statement(jockey_ids, period),
    )}
    return {jockey_id: records.get(jockey_id, JockeyDirectoryStats()) for jockey_id in jockey_ids}


def _load_jockey_detail(
    session: Session, jockey_id: int, partner_period: str = "career",
) -> JockeyDetailData:
    partner_period = partner_period if partner_period in PERFORMANCE_PERIOD_LABELS else "career"
    roster_date = session.scalar(select(func.max(JockeyAffiliationSnapshot.observed_on)))
    profile = session.scalar(select(JockeyAffiliationSnapshot).where(
        JockeyAffiliationSnapshot.jockey_id == jockey_id,
    ).order_by(JockeyAffiliationSnapshot.observed_on.desc()).limit(1))
    affiliation = profile if profile and profile.observed_on == roster_date else None
    base = _completed_starts_statement().where(RaceEntry.jockey_id == jockey_id)
    # Aggregate the entire history, independently of the 200-row display limit.
    columns = []
    starts = (*_directory_period_starts(), None)
    for start in starts:
        in_period = Race.race_date_local >= start if start else Race.id.is_not(None)
        columns.append(func.count().filter(in_period))
        columns.extend(func.count().filter(
            in_period, RaceResult.finish_position == rank,
            RaceResult.disqualified.is_(False),
        ) for rank in (1, 2, 3))
    counts = session.execute(base.with_only_columns(*columns)).one()
    periods = [JockeyPerformanceRow(
        label, _jockey_stats_from_counts(*counts[index * 4:index * 4 + 4]), start,
    ) for index, (label, start) in enumerate(zip(
        PERFORMANCE_PERIOD_LABELS.values(), starts, strict=True,
    ))]
    year = extract("year", Race.race_date_local)
    years = [JockeyPerformanceRow(f"{int(row[0])}년", _jockey_stats_from_counts(*row[1:]))
             for row in session.execute(base.with_only_columns(
                 year, func.count(),
                 *[func.count().filter(
                     RaceResult.finish_position == rank, RaceResult.disqualified.is_(False),
                 ) for rank in (1, 2, 3)],
             ).group_by(year).order_by(year.desc()))]
    return JockeyDetailData(
        region={1: "서울", 3: "부산", 2: "제주"}.get(
            affiliation.meet_code if affiliation else None, "—",
        ),
        affiliation_date=affiliation.observed_on if affiliation else None,
        periods=periods, years=years,
        trainers=_load_jockey_partners(session, jockey_id, "trainers", partner_period),
        owners=_load_jockey_partners(session, jockey_id, "owners", partner_period),
        as_of=today_seoul(),
        partner_period=partner_period, partner_start=_directory_period_start(partner_period),
        debut_date=profile.debut_date.strftime("%Y.%m.%d")
        if profile and profile.debut_date else "—",
        riding_weight=_jockey_riding_weight(profile),
    )


def _jockey_riding_weight(profile: JockeyAffiliationSnapshot | None) -> str:
    if profile is None:
        return "—"
    own, other = profile.riding_weight_own_kg, profile.riding_weight_other_kg
    if own is not None and own == other:
        return f"{float(own):g}kg"
    return " · ".join(f"{label} {float(value):g}kg"
                      for label, value in (("소속조", own), ("타조", other))
                      if value is not None) or "—"


def _load_jockey_partners(
    session: Session, jockey_id: int, kind: str, period: str = "career",
) -> list[JockeyPartnerRow]:
    statement = _completed_starts_statement().where(RaceEntry.jockey_id == jockey_id)
    start = _directory_period_start(period)
    if start is not None:
        statement = statement.where(Race.race_date_local >= start)
    if kind == "trainers":
        canonical = aliased(Trainer)
        partner_id = func.coalesce(TrainerIdentityResolution.official_tr_no,
                                   Trainer.kra_trainer_id)
        partner_name = func.coalesce(canonical.name_ko, Trainer.name_ko)
        statement = (statement.join(RaceEntry.trainer)
                     .outerjoin(TrainerIdentityResolution,
                                (TrainerIdentityResolution.temporary_trainer_ref
                                 == Trainer.kra_trainer_id)
                                & (TrainerIdentityResolution.resolution_status == "confirmed"))
                     .outerjoin(canonical, canonical.kra_trainer_id == partner_id))
    else:
        partner_id, partner_name = Owner.kra_owner_id, Owner.name_ko
        statement = statement.join(RaceEntry.owner)
    starts = func.count()
    podium = [func.count().filter(
        RaceResult.finish_position == rank, RaceResult.disqualified.is_(False),
    ) for rank in (1, 2, 3)]
    places = podium[0] + podium[1] + podium[2]
    return [JockeyPartnerRow(
        name=row[1], href=f"/{kind}/{quote(row[0], safe='')}",
        stats=_jockey_stats_from_counts(*row[2:]),
    ) for row in session.execute(statement.with_only_columns(
        partner_id, partner_name, starts, *podium,
    ).group_by(partner_id, partner_name).having(places > 0)
      .order_by(places.desc(), podium[0].desc(), starts.desc(), partner_name, partner_id)
      .limit(10))]


def _load_owner_directory_stats(
    session: Session, owner_ids: list[int], period: str, meet: int | None,
) -> dict[int, DirectoryPerformanceStats]:
    if not owner_ids:
        return {}
    records = {row[0]: _jockey_stats_from_counts(*row[1:]) for row in session.execute(
        _directory_counts_statement(RaceEntry.owner_id, owner_ids, period, meet),
    )}
    return {owner_id: records.get(owner_id, DirectoryPerformanceStats()) for owner_id in owner_ids}


def _load_trainer_directory_stats(
    session: Session, trainers: list[Trainer], roster_date: date | None,
    meet_filter: int | None, period: str = "career",
) -> dict[int, TrainerDirectoryStats]:
    if not trainers:
        return {}
    ids = [trainer.id for trainer in trainers]
    refs = [trainer.kra_trainer_id for trainer in trainers]
    roster = {row.trainer_id: row for row in session.scalars(
        select(TrainerAffiliationSnapshot).where(
            TrainerAffiliationSnapshot.trainer_id.in_(ids),
            TrainerAffiliationSnapshot.observed_on == roster_date,
        ),
    )}
    # Count each active horse once, using its latest affiliation rather than race history.
    latest_profile = select(
        HorseProfileSnapshot.horse_id,
        func.max(HorseProfileSnapshot.observed_at_ms).label("observed_at_ms"),
    ).where(HorseProfileSnapshot.horse_id.in_(
        select(Horse.id).where(Horse.is_active.is_(True)),
    )).group_by(HorseProfileSnapshot.horse_id).subquery()
    managed = dict(session.execute(
        select(HorseProfileSnapshot.trainer_kra_id, func.count())
        .join(latest_profile,
              (latest_profile.c.horse_id == HorseProfileSnapshot.horse_id)
              & (latest_profile.c.observed_at_ms == HorseProfileSnapshot.observed_at_ms))
        .where(HorseProfileSnapshot.trainer_kra_id.in_(refs))
        .group_by(HorseProfileSnapshot.trainer_kra_id),
    ).all())
    month_start, year_start = _directory_period_starts()
    # Reviewed temporary IDs belong to the same official trainer; never merge by name.
    canonical_ref = func.coalesce(
        TrainerIdentityResolution.official_tr_no, Trainer.kra_trainer_id,
    )
    columns = [canonical_ref.label("trainer_ref")]
    for start in (month_start, year_start, None):
        in_period = Race.race_date_local >= start if start else Race.id.is_not(None)
        columns.append(func.count().filter(in_period))
        columns.extend(func.count().filter(
            in_period, RaceResult.finish_position == rank,
            RaceResult.disqualified.is_(False),
        ) for rank in (1, 2, 3))
    records = {row[0]: row[1:] for row in session.execute(
        _completed_starts_statement()
        .join(RaceEntry.trainer)
        .outerjoin(TrainerIdentityResolution,
                   (TrainerIdentityResolution.temporary_trainer_ref == Trainer.kra_trainer_id)
                   & (TrainerIdentityResolution.resolution_status == "confirmed"))
        .where(canonical_ref.in_(refs))
        .with_only_columns(*columns)
        .group_by(canonical_ref),
    )}
    stats = {}
    for trainer in trainers:
        affiliation = roster.get(trainer.id)
        stable = "—"
        if affiliation:
            region = {1: "서울", 2: "제주", 3: "부산"}[affiliation.meet_code]
            prefix = f"{region} " if meet_filter is None else ""
            stable = f"{prefix}{affiliation.stable_part}조"
        counts = records.get(trainer.kra_trainer_id, (0,) * 12)
        offset = {"month": 0, "year": 4, "career": 8}[period]
        stats[trainer.id] = TrainerDirectoryStats(
            stable=stable, managed_count=managed.get(trainer.kra_trainer_id, 0),
            month_record=_format_place_record(*counts[:4]),
            year_record=_format_place_record(*counts[4:8]),
            career_record=_format_place_record(*counts[8:12]),
            performance=_jockey_stats_from_counts(*counts[offset:offset + 4]),
        )
    return stats


def _trainer_directory_counts_statement(period: str) -> Select:
    # Include reviewed aliases in the same selected-period ordering as the displayed records.
    canonical_ref = func.coalesce(
        TrainerIdentityResolution.official_tr_no, Trainer.kra_trainer_id,
    )
    statement = (
        _completed_starts_statement().join(RaceEntry.trainer)
        .outerjoin(TrainerIdentityResolution,
                   (TrainerIdentityResolution.temporary_trainer_ref == Trainer.kra_trainer_id)
                   & (TrainerIdentityResolution.resolution_status == "confirmed"))
    )
    start = _directory_period_start(period)
    if start:
        statement = statement.where(Race.race_date_local >= start)
    return statement.with_only_columns(
        canonical_ref.label("entity_id"), func.count().label("entry_count"),
    ).group_by(canonical_ref)


def _load_trainer_managed_horses(
    session: Session, trainer_kra_id: str
) -> list[TrainerManagedHorse]:
    latest_profile = (
        select(
            HorseProfileSnapshot.horse_id.label("horse_id"),
            func.max(HorseProfileSnapshot.observed_at_ms).label("observed_at_ms"),
        )
        .group_by(HorseProfileSnapshot.horse_id)
        .subquery()
    )
    rows = session.execute(
        select(Horse, HorseProfileSnapshot)
        .join(
            HorseProfileSnapshot,
            HorseProfileSnapshot.horse_id == Horse.id,
        )
        .join(
            latest_profile,
            (latest_profile.c.horse_id == HorseProfileSnapshot.horse_id)
            & (HorseProfileSnapshot.observed_at_ms == latest_profile.c.observed_at_ms),
        )
        .where(
            HorseProfileSnapshot.trainer_kra_id == trainer_kra_id,
            Horse.is_active.is_(True),
        )
        .order_by(Horse.name_ko, Horse.kra_horse_id)
    ).all()
    last_race_ratings = _load_last_race_rating_values(session, [horse.id for horse, _ in rows])
    return [
        TrainerManagedHorse(
            official_id=horse.kra_horse_id,
            name_ko=horse.name_ko,
            meet_label=_meet_label(profile.meet_code),
            grade=profile.grade or "—",
            age=format_age(horse.birth_date, today_seoul()),
            rating=last_race_ratings.get(horse.id, "—"),
        )
        for horse, profile in rows
    ]


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
    last_race: RatingRow | None,
) -> list[tuple[str, str]]:
    as_of = today_seoul()
    rows = [
        ("마번", horse.kra_horse_id),
        ("현역 상태", _horse_status(horse.is_active)[0]),
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
        ("마지막 경주 레이팅", last_race.rating if last_race else "—"),
    ]
    if last_race is not None:
        rows.append(
            (
                "레이팅 기준 경주",
                f"{last_race.race_date:%Y.%m.%d} {last_race.meet_label} {last_race.race_label}",
            )
        )
    if horse.active_status_observed_at_ms is not None:
        rows.append(("상태 확인", _format_observed_ms(horse.active_status_observed_at_ms)))
    if profile is not None:
        rows.extend(
            [
                ("프로필 관측", profile.observed_label),
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


def _horse_status(is_active: bool | None) -> tuple[str, str]:
    if is_active is True:
        return "현역", "active"
    if is_active is False:
        return "은퇴", "retired"
    return "미확인", "unknown"


def _history_row(entry: RaceEntry) -> HistoryRow:
    race = entry.race
    condition = (race.grade or "").replace("등급", "").strip()
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
        condition=f"{condition}등급" if condition.isdecimal() else condition or "—",
        horse_number=entry.horse_number,
        horse_name=entry.horse.name_ko,
        horse_id=entry.horse.kra_horse_id,
        jockey_name=entry.jockey.name_ko if entry.jockey else "—",
        jockey_id=entry.jockey.kra_jockey_id if entry.jockey else None,
        trainer_name=entry.trainer.name_ko if entry.trainer else "—",
        trainer_id=entry.trainer.kra_trainer_id if entry.trainer else None,
        owner_name=entry.owner.name_ko if entry.owner else "—",
        owner_id=entry.owner.kra_owner_id if entry.owner else None,
        finish_position=finish_label,
        finish_sort=finish_sort,
        finish_time=format_race_time(result.finish_time_ms if result else None),
        margin=format_margin(result.margin_text if result else None, missing="-"),
        dashboard_href=f"/races/{race.id}",
    )


def _load_ratings(session: Session, horse_id: int) -> list[RatingRow]:
    rows = list(
        session.scalars(
            _completed_starts_statement()
            .where(RaceEntry.horse_id == horse_id)
            .options(joinedload(RaceEntry.race).joinedload(Race.racecourse))
            .order_by(Race.race_date_local.desc(), Race.race_number.desc(), RaceEntry.id.desc())
            .limit(MAX_HORSE_AUX_ROWS)
        )
    )
    return [
        RatingRow(
            race_date=row.race.race_date_local,
            meet_label=row.race.racecourse.name_ko,
            race_label=f"{row.race.race_number}R",
            rating=format_rating(row.rating),
        )
        for row in rows
    ]


def _completed_starts_statement() -> Select[tuple[RaceEntry]]:
    """Actual past starts only; never substitute a card or API77 snapshot.

    Include a stopped/disqualified runner, but exclude cancellations and result
    placeholders. Keep a missing rating on the last start instead of falling
    back to an older non-null value.
    """
    return (
        select(RaceEntry)
        .join(RaceEntry.race)
        .join(RaceEntry.result)
        .where(
            Race.status == "completed",
            Race.race_date_local <= today_seoul(),
            RaceEntry.scratched.is_(False),
            or_(
                RaceResult.finish_position > 0,
                RaceResult.finish_time_ms > 0,
                RaceResult.disqualified.is_(True),
            ),
            or_(
                RaceResult.finish_position.is_(None),
                RaceResult.finish_position.not_in([91, 92, 94, 95, 99]),
            ),
        )
    )


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
            position=(f"{result.finish_position}위" if result.finish_position is not None else "—"),
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
            location=row.location_raw or "—",
        )
        for row in rows
    ]


def _load_horse_jockey_changes(session: Session, horse_id: int) -> list[HorseJockeyChangeRow]:
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


def _format_stable(part: int | None, number: int | str | None) -> str:
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
            f"{row.prize_money_total_krw:,}원" if row.prize_money_total_krw is not None else "—"
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
    return f"{starts or 0}전 {wins or 0}/{seconds or 0}/{thirds or 0}"


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
    parts = [f"{label} {milliseconds / 1000:.1f}" for label, milliseconds in values if milliseconds]
    return " · ".join(parts) if parts else "—"


def _format_trial_reason(failure: str | None, inspection: str | None) -> str:
    parts = [part for part in (failure, inspection) if part]
    return " · ".join(parts) if parts else "—"


def _count_for_horse(session: Session, model: type, horse_id: int) -> int:
    return int(
        session.scalar(select(func.count()).select_from(model).where(model.horse_id == horse_id))
        or 0
    )


class HorseListStats(NamedTuple):
    rating: str = "—"
    recent_five: str = "—"
    career_record: str = "—"
    win_rate: str = "—"
    place_rate: str = "—"
    trainer_name: str = "—"
    owner_name: str = "—"
    trainer_href: str | None = None
    owner_href: str | None = None
    recent_starts: tuple[RecentHorseStart, ...] = ()


def _affiliation_name(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned if cleaned not in {"", "-", "—", "없음", "미상"} else None


def _profile_affiliation_links(session: Session, profiles: dict, model: type,
                               role: str, slug: str) -> dict[int, str]:
    """Resolve profile identities in bulk; ambiguous names go to search results."""
    names = {_affiliation_name(getattr(profile, f"{role}_name"))
             for profile in profiles.values()} - {None}
    ids = {getattr(profile, f"{role}_kra_id") for profile in profiles.values()} - {None, ""}
    id_column = getattr(model, f"kra_{role}_id")
    people = session.execute(select(id_column, model.name_ko).where(
        or_(id_column.in_(ids), model.name_ko.in_(names)),
    )).all() if names else []
    by_id = {official_id for official_id, _ in people}
    by_name: dict[str, list[str]] = {}
    for official_id, name in people:
        by_name.setdefault(name, []).append(official_id)
    links = {}
    for horse_id, profile in profiles.items():
        name = _affiliation_name(getattr(profile, f"{role}_name"))
        if not name:
            continue
        official_id = getattr(profile, f"{role}_kra_id")
        matches = by_name.get(name, [])
        if official_id not in by_id:
            official_id = matches[0] if len(matches) == 1 else None
        links[horse_id] = (f"/{slug}/{quote(official_id, safe='')}" if official_id
                           else f"/{slug}?{urlencode({'q': name})}")
    return links


def _load_horse_list_history(session: Session, horse_ids: list[int]) -> dict[int, HorseListStats]:
    if not horse_ids:
        return {}
    starts = session.execute(
        _completed_starts_statement()
        .join(Race.racecourse)
        .outerjoin(RaceEntry.trainer)
        .outerjoin(RaceEntry.owner)
        .where(RaceEntry.horse_id.in_(horse_ids))
        .with_only_columns(
            RaceEntry.horse_id, RaceEntry.rating,
            RaceResult.finish_position, RaceResult.disqualified,
            Trainer.name_ko.label("trainer_name"), Owner.name_ko.label("owner_name"),
            Trainer.kra_trainer_id, Owner.kra_owner_id,
            Race.id.label("race_id"), Race.race_date_local, Race.race_number,
            Racecourse.name_ko.label("course_name"),
        )
        .order_by(Race.race_date_local.desc(), Race.race_number.desc(), RaceEntry.id.desc())
    ).all()
    by_horse: dict[int, list] = {horse_id: [] for horse_id in horse_ids}
    for row in starts:
        by_horse[row.horse_id].append(row)

    latest_profile = select(
        HorseProfileSnapshot.horse_id,
        func.max(HorseProfileSnapshot.observed_at_ms).label("observed_at_ms"),
    ).where(HorseProfileSnapshot.horse_id.in_(horse_ids)).group_by(
        HorseProfileSnapshot.horse_id,
    ).subquery()
    profiles = {row.horse_id: row for row in session.scalars(
        select(HorseProfileSnapshot).join(
            latest_profile,
            (latest_profile.c.horse_id == HorseProfileSnapshot.horse_id)
            & (latest_profile.c.observed_at_ms == HorseProfileSnapshot.observed_at_ms),
        )
    )}
    trainer_links = _profile_affiliation_links(session, profiles, Trainer, "trainer", "trainers")
    owner_links = _profile_affiliation_links(session, profiles, Owner, "owner", "owners")
    stats = {}
    for horse_id, rows in by_horse.items():
        counts = (len(rows), *[sum(row.finish_position == rank and not row.disqualified
                                  for row in rows) for rank in (1, 2, 3)])
        profile = profiles.get(horse_id)
        if profile is not None:
            official = (profile.race_count_total, profile.win_count_total,
                        profile.second_count_total, profile.third_count_total)
            # Use one complete source; never mix official starts with partial result counts.
            if (all(value is not None and value >= 0 for value in official)
                    and official[0] >= counts[0] and sum(official[1:]) <= official[0]):
                counts = official
        recent = []
        for row in rows[:5]:
            label = "실격" if row.disqualified else format_finish_position(row.finish_position)[0]
            recent.append(RecentHorseStart(
                label.removesuffix("위"), row.race_id,
                f"{row.race_date_local:%Y.%m.%d} · {row.course_name} {row.race_number}R · {label}",
            ))
        total, wins, seconds, thirds = counts
        stats[horse_id] = HorseListStats(
            rating=format_rating(rows[0].rating) if rows else "—",
            recent_five=" · ".join(start.finish for start in recent) if recent else "—",
            career_record=_format_place_record(total, wins, seconds, thirds),
            win_rate=_win_rate(wins, total),
            place_rate=_win_rate(wins + seconds + thirds, total),
            trainer_name=(
                _affiliation_name(profile.trainer_name if profile else None)
                or _affiliation_name(rows[0].trainer_name if rows else None) or "—"
            ),
            owner_name=(
                _affiliation_name(profile.owner_name if profile else None)
                or _affiliation_name(rows[0].owner_name if rows else None) or "—"
            ),
            trainer_href=(trainer_links.get(horse_id) or (
                f"/trainers/{quote(rows[0].kra_trainer_id, safe='')}"
                if rows and rows[0].kra_trainer_id else None
            )),
            owner_href=(owner_links.get(horse_id) or (
                f"/owners/{quote(rows[0].kra_owner_id, safe='')}"
                if rows and rows[0].kra_owner_id else None
            )),
            recent_starts=tuple(recent),
        )
    return stats


def _last_race_ratings_statement():
    return _completed_starts_statement().with_only_columns(
        RaceEntry.horse_id.label("horse_id"),
        RaceEntry.rating.label("rating"),
        func.row_number().over(
            partition_by=RaceEntry.horse_id,
            order_by=(Race.race_date_local.desc(), Race.race_number.desc(), RaceEntry.id.desc()),
        ).label("position"),
    )


def _load_last_race_rating_values(session: Session, horse_ids: list[int]) -> dict[int, str]:
    if not horse_ids:
        return {}
    last_start = _last_race_ratings_statement().where(RaceEntry.horse_id.in_(horse_ids)).subquery()
    rating_rows = session.execute(
        select(last_start.c.horse_id, last_start.c.rating).where(last_start.c.position == 1)
    ).all()
    return {horse_id: format_rating(rating) for horse_id, rating in rating_rows}
