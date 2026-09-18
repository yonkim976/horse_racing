"""Read-only query layer for forecast, validation, and personal analysis pages.

The pages intentionally expose only measurements already present in the database.
Heuristic running-style labels are described as estimates and are never presented as
model probabilities.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from itertools import combinations
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from horse_racing.db.models import (
    Horse,
    Jockey,
    ModelPrediction,
    PredictionOutcome,
    PredictionRun,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RaceSectionResult,
)
from horse_racing.web.formatting import MAX_NORMAL_FINISH

KST = ZoneInfo("Asia/Seoul")
MEET_NAMES = {1: "서울", 2: "제주", 3: "부산경남", 4: "영천"}


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def displayed_win_points(value: float | None) -> int | None:
    if value is None:
        return None
    percent = int(round(value * 100))
    if value > 0 and percent == 0:
        percent = 1
    return percent


def format_win_pct(value: float | None) -> str | None:
    percent = displayed_win_points(value)
    return None if percent is None else f"{percent}%"


_CLOSE_PP = 5
_AXIS_PP = 8
_MIXED_PP = 8
_CHALLENGER_PP = 8
_INCLUDE_PP = 12
WIN_LABELS = ("강축", "축", "상대", "복병", "접전", "혼전", "후착혼전")


def assign_win_labels(
    entries: Sequence[tuple[int, float | None, bool]],
) -> dict[int, str]:
    """Assign one of the seven contention terms from displayed win percents."""
    ranked = sorted(
        (
            (entry_id, points)
            for entry_id, probability, scratched in entries
            if not scratched
            for points in (displayed_win_points(probability),)
            if points is not None
        ),
        key=lambda item: (-item[1], item[0]),
    )
    if not ranked:
        return {}

    points = [item[1] for item in ranked]
    count = len(ranked)
    top = points[0]
    second = points[1] if count > 1 else None
    top_gap = 0 if second is None else top - second

    def cluster(start: int, anchor: int) -> list[int]:
        return [
            index
            for index, value in enumerate(points)
            if index >= start and anchor - value <= _CLOSE_PP
        ]

    def fill_rest(start: int, *, allow_challenger: bool) -> dict[int, str]:
        labels: dict[int, str] = {}
        challengers = 0
        previous_value: int | None = None
        previous_label: str | None = None
        for index in range(start, count):
            entry_id, value = ranked[index]
            if previous_label is not None and value == previous_value:
                labels[entry_id] = previous_label
                continue
            if allow_challenger and challengers < 2 and value >= _CHALLENGER_PP:
                label = "상대"
                challengers += 1
            else:
                label = "복병"
            labels[entry_id] = label
            previous_value = value
            previous_label = label
        return labels

    if count == 1:
        return {ranked[0][0]: "강축" if top >= _AXIS_PP else "축"}

    leader_cluster = cluster(0, top)
    place_cluster = cluster(1, second) if second is not None else []

    if top_gap >= _AXIS_PP and len(place_cluster) >= 2:
        labels = {ranked[0][0]: "강축"}
        labels.update({ranked[index][0]: "후착혼전" for index in place_cluster})
        labels.update(fill_rest(max(place_cluster) + 1, allow_challenger=False))
        return labels

    if len(leader_cluster) >= 4:
        pack_end = leader_cluster[-1]
        while pack_end + 1 < count and top - points[pack_end + 1] <= _MIXED_PP:
            pack_end += 1
        labels = {ranked[index][0]: "혼전" for index in range(pack_end + 1)}
        labels.update(fill_rest(pack_end + 1, allow_challenger=False))
        return labels

    if 2 <= len(leader_cluster) <= 3:
        last = leader_cluster[-1]
        next_points = points[last + 1] if last + 1 < count else 0
        bunched_field = [index for index, value in enumerate(points) if top - value <= _MIXED_PP]
        if last + 1 < count and points[last] - next_points < _CLOSE_PP and len(bunched_field) >= 4:
            labels = {ranked[index][0]: "혼전" for index in bunched_field}
            labels.update(fill_rest(bunched_field[-1] + 1, allow_challenger=False))
            return labels
        labels = {ranked[index][0]: "접전" for index in leader_cluster}
        labels.update(fill_rest(last + 1, allow_challenger=True))
        return labels

    if top_gap >= _AXIS_PP:
        labels = {ranked[0][0]: "강축"}
        if second is not None and (second >= _INCLUDE_PP or top_gap <= 15):
            labels[ranked[1][0]] = "축"
            labels.update(fill_rest(2, allow_challenger=True))
        else:
            labels.update(fill_rest(1, allow_challenger=True))
        return labels

    labels = {ranked[0][0]: "축"}
    if second is not None and top_gap <= _CLOSE_PP:
        labels[ranked[1][0]] = "축"
        labels.update(fill_rest(2, allow_challenger=True))
    else:
        labels.update(fill_rest(1, allow_challenger=True))
    return labels


_SKIP_TRIAL_JUDGEMENTS = {"출", "심", "주"}
_TRIAL_FORM_MARKS = {"합", "불", "연", "유"}


def format_trial_form_token(position: int | None, judgement: str | None) -> str | None:
    """Compact running-trial token such as 1합, 7, or 연."""
    code = (judgement or "").strip()
    if code in _SKIP_TRIAL_JUDGEMENTS:
        return None
    pos = str(position) if position is not None and 1 <= position <= MAX_NORMAL_FINISH else ""
    mark = code if code in _TRIAL_FORM_MARKS else ""
    token = f"{pos}{mark}"
    return token or None


def format_trial_form_line(tokens: Sequence[str], *, limit: int = 5) -> str:
    picked = [token for token in tokens if token][:limit]
    if not picked:
        return ""
    return "심 " + "-".join(picked)


def latest_win_probabilities(session: Session, race_ids: Sequence[int]) -> dict[int, float]:
    """Latest published run's top-3 probability keyed by race entry id."""
    if not race_ids:
        return {}
    rows = session.execute(
        select(
            ModelPrediction.race_id,
            ModelPrediction.race_entry_id,
            ModelPrediction.prob_top3,
            PredictionRun.id,
        )
        .join(PredictionRun, PredictionRun.id == ModelPrediction.prediction_run_id)
        .where(ModelPrediction.race_id.in_(list(race_ids)))
        .order_by(PredictionRun.published_at_ms.desc(), PredictionRun.id.desc())
    ).all()
    chosen_run: dict[int, int] = {}
    probabilities: dict[int, float] = {}
    for race_id, entry_id, probability, run_id in rows:
        if race_id not in chosen_run:
            chosen_run[race_id] = run_id
        if run_id != chosen_run[race_id]:
            continue
        probabilities[entry_id] = probability
    return probabilities


def win_probability_sort_key(
    *,
    scratched: bool,
    number: int | None,
    win_prob: float | None,
    has_field_predictions: bool,
) -> tuple:
    if not has_field_predictions:
        return (number or 99,)
    return (
        scratched,
        win_prob is None,
        -(win_prob or 0.0),
        number or 99,
    )


def _time(value: int | None) -> str:
    if not value:
        return "—"
    seconds = value / 1000
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def _timestamp(value: int | None) -> str:
    if value is None:
        return "—"
    from datetime import datetime

    return datetime.fromtimestamp(value / 1000, tz=KST).strftime("%Y-%m-%d %H:%M KST")


@dataclass(slots=True)
class ForecastRace:
    id: int
    date: str
    meet_code: int
    meet: str
    number: int
    distance: int
    grade: str
    name: str
    status: str
    field_size: int
    prediction_state: str


@dataclass(slots=True)
class ForecastRunner:
    entry_id: int
    horse_id: int
    number: int
    gate: int | None
    horse: str
    jockey: str
    weight: str
    scratched: bool
    state: str
    starts: int
    wins: int
    top3: int
    win_rate: str
    top3_rate: str
    average_finish: str
    same_distance: str
    recent_finishes: str
    recent_times: list[float | None]
    early_position: float | None
    closing_time: float | None
    style: str
    style_reason: str
    predicted_rank: int | None
    prob_win: str
    prob_top3: str


@dataclass(slots=True)
class ForecastPage:
    dates: list[str]
    meets: list[tuple[int, str]]
    distances: list[int]
    grades: list[str]
    selected_date: str
    selected_meet: int | None
    selected_distance: int | None
    selected_grade: str
    races: list[ForecastRace]
    selected_race: ForecastRace | None
    runners: list[ForecastRunner]
    model: dict[str, str] | None
    data_cutoff: str

    def pace_json(self) -> list[dict[str, Any]]:
        return [
            {
                "id": row.entry_id,
                "number": row.number,
                "name": row.horse,
                "style": row.style,
                "early": row.early_position,
                "closing": row.closing_time,
                "scratched": row.scratched,
            }
            for row in self.runners
        ]


def _forecast_options(session: Session) -> list[Any]:
    today = date.today()
    rows = session.execute(
        select(
            Race.race_date_local,
            Racecourse.kra_meet_code,
            Racecourse.name_ko,
            Race.distance_m,
            Race.grade,
        )
        .join(Racecourse, Racecourse.id == Race.racecourse_id)
        .where(Race.status == "scheduled", Race.race_date_local >= today)
        .order_by(Race.race_date_local, Racecourse.kra_meet_code, Race.race_number)
    ).all()
    # A stale local snapshot should still remain inspectable, with its scheduled label intact.
    if not rows:
        rows = session.execute(
            select(
                Race.race_date_local,
                Racecourse.kra_meet_code,
                Racecourse.name_ko,
                Race.distance_m,
                Race.grade,
            )
            .join(Racecourse, Racecourse.id == Race.racecourse_id)
            .where(Race.status == "scheduled")
            .order_by(Race.race_date_local.desc(), Racecourse.kra_meet_code, Race.race_number)
            .limit(200)
        ).all()
    return rows


def load_forecast_page(
    session: Session,
    *,
    selected_date: date | None = None,
    meet: int | None = None,
    distance: int | None = None,
    grade: str = "",
    race_id: int | None = None,
) -> ForecastPage:
    option_rows = _forecast_options(session)
    dates = sorted({row.race_date_local.isoformat() for row in option_rows})
    selected_date = selected_date or (date.fromisoformat(dates[0]) if dates else date.today())
    meets = sorted({(row.kra_meet_code, row.name_ko) for row in option_rows})
    distances = sorted({row.distance_m for row in option_rows})
    grades = sorted({row.grade for row in option_rows if row.grade})

    if race_id:
        conditions = [Race.id == race_id]
    else:
        conditions = [Race.status == "scheduled", Race.race_date_local == selected_date]
        if meet:
            conditions.append(Racecourse.kra_meet_code == meet)
        if distance:
            conditions.append(Race.distance_m == distance)
        if grade:
            conditions.append(Race.grade == grade)
    race_rows = session.execute(
        select(
            Race.id,
            Race.race_date_local,
            Racecourse.kra_meet_code,
            Racecourse.name_ko,
            Race.race_number,
            Race.distance_m,
            Race.grade,
            Race.race_name,
            Race.status,
            func.count(func.distinct(RaceEntry.id)),
            func.count(func.distinct(ModelPrediction.id)),
        )
        .join(Racecourse, Racecourse.id == Race.racecourse_id)
        .outerjoin(RaceEntry, RaceEntry.race_id == Race.id)
        .outerjoin(ModelPrediction, ModelPrediction.race_id == Race.id)
        .where(*conditions)
        .group_by(Race.id)
        .order_by(Race.race_number)
        .limit(40)
    ).all()
    races = [
        ForecastRace(
            id=row[0],
            date=row[1].isoformat(),
            meet_code=row[2],
            meet=row[3],
            number=row[4],
            distance=row[5],
            grade=row[6] or "미정",
            name=row[7] or "일반",
            status=row[8],
            field_size=row[9],
            prediction_state="발행 완료" if row[10] else "예측 미발행",
        )
        for row in race_rows
    ]
    selected = next((row for row in races if row.id == race_id), races[0] if races else None)
    if selected is None:
        return ForecastPage(
            dates,
            meets,
            distances,
            grades,
            selected_date.isoformat(),
            meet,
            distance,
            grade,
            races,
            None,
            [],
            None,
            "—",
        )

    entry_rows = session.execute(
        select(
            RaceEntry.id,
            RaceEntry.horse_id,
            RaceEntry.horse_number,
            RaceEntry.gate_number,
            Horse.name_ko,
            Jockey.name_ko,
            RaceEntry.carried_weight_kg,
            RaceEntry.scratched,
            RaceEntry.running_style,
        )
        .join(Horse, Horse.id == RaceEntry.horse_id)
        .outerjoin(Jockey, Jockey.id == RaceEntry.jockey_id)
        .where(RaceEntry.race_id == selected.id)
        .order_by(RaceEntry.horse_number)
    ).all()
    horse_ids = [row[1] for row in entry_rows]
    history_rows = []
    if horse_ids:
        history_rows = session.execute(
            select(
                RaceEntry.horse_id,
                Race.id,
                Race.race_date_local,
                Race.distance_m,
                RaceResult.finish_position,
                RaceResult.finish_time_ms,
                RaceSectionResult.section_code,
                RaceSectionResult.elapsed_time_ms,
                RaceSectionResult.position,
                RaceSectionResult.time_basis,
            )
            .join(Race, Race.id == RaceEntry.race_id)
            .join(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
            .outerjoin(RaceSectionResult, RaceSectionResult.race_entry_id == RaceEntry.id)
            .where(
                RaceEntry.horse_id.in_(horse_ids),
                Race.race_date_local < date.fromisoformat(selected.date),
                RaceResult.disqualified.is_(False),
                RaceResult.finish_position.is_not(None),
                RaceResult.finish_position < 90,
            )
            .order_by(Race.race_date_local.desc(), Race.id.desc())
        ).all()
    history: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in history_rows:
        race_history = history[row[0]].setdefault(
            row[1],
            {"date": row[2], "distance": row[3], "finish": row[4], "time": row[5], "sections": {}},
        )
        if row[6]:
            race_history["sections"][row[6]] = (row[7], row[8], row[9])

    run_row = session.execute(
        select(PredictionRun)
        .join(ModelPrediction, ModelPrediction.prediction_run_id == PredictionRun.id)
        .where(ModelPrediction.race_id == selected.id)
        .order_by(PredictionRun.published_at_ms.desc())
        .limit(1)
    ).scalar_one_or_none()
    prediction_by_entry: dict[int, Any] = {}
    if run_row:
        predictions = session.scalars(
            select(ModelPrediction)
            .where(
                ModelPrediction.prediction_run_id == run_row.id,
                ModelPrediction.race_id == selected.id,
            )
            .order_by(ModelPrediction.prob_win.desc())
        ).all()
        prediction_by_entry = {
            item.race_entry_id: (rank, item) for rank, item in enumerate(predictions, 1)
        }

    runners: list[ForecastRunner] = []
    for entry in entry_rows:
        records = list(history[entry[1]].values())
        recent = records[:5]
        starts = len(records)
        wins = sum(record["finish"] == 1 for record in records)
        top3 = sum(record["finish"] <= 3 for record in records)
        same_distance = [record for record in records if record["distance"] == selected.distance]
        early_positions = [
            value[1]
            for record in records[:10]
            for key, value in record["sections"].items()
            if key in {"S1F", "1C", "2C", "3C"} and value[1] is not None
        ]
        closing_times = [
            value[0] / 1000
            for record in records[:10]
            for key, value in record["sections"].items()
            if key == "G1F" and value[0] and value[2] in {"closing", None}
        ]
        early = sum(early_positions) / len(early_positions) if early_positions else None
        closing = sum(closing_times) / len(closing_times) if closing_times else None
        if entry[8]:
            style, reason = entry[8], "출전표 저장 전개 성향"
        elif early is not None:
            if early <= 2.5:
                style = "선행"
            elif early <= 5:
                style = "선입"
            else:
                style = "추입"
            reason = f"최근 구간 통과순위 평균 {early:.1f}위 기반 추정"
        else:
            style, reason = "자료 부족", "공식 위치·과거 구간 순위 없음"
        pred = prediction_by_entry.get(entry[0])
        if entry[7]:
            state = "출전 취소"
        elif entry[5] is None:
            state = "기수 미정"
        elif starts < 3:
            state = "이력 부족"
        else:
            state = "출전 예정"
        runners.append(
            ForecastRunner(
                entry_id=entry[0],
                horse_id=entry[1],
                number=entry[2],
                gate=entry[3],
                horse=entry[4],
                jockey=entry[5] or "미정",
                weight=f"{entry[6]:.1f}kg" if entry[6] else "—",
                scratched=entry[7],
                state=state,
                starts=starts,
                wins=wins,
                top3=top3,
                win_rate=_pct(wins / starts if starts else None),
                top3_rate=_pct(top3 / starts if starts else None),
                average_finish=(
                    f"{sum(r['finish'] for r in records) / starts:.1f}" if starts else "—"
                ),
                same_distance=(
                    f"{len(same_distance)}전 {sum(r['finish'] <= 3 for r in same_distance)}회 입상"
                    if same_distance
                    else "자료 없음"
                ),
                recent_finishes=" · ".join(str(r["finish"]) for r in recent) or "—",
                recent_times=[r["time"] / 1000 if r["time"] else None for r in recent],
                early_position=round(early, 2) if early is not None else None,
                closing_time=round(closing, 2) if closing is not None else None,
                style=style,
                style_reason=reason,
                predicted_rank=pred[0] if pred else None,
                prob_win=_pct(pred[1].prob_win) if pred else "—",
                prob_top3=_pct(pred[1].prob_top3) if pred else "—",
            )
        )
    model = None
    if run_row:
        model = {
            "mode": "사전 공개" if run_row.publication_mode == "live" else "과거 재현",
            "model": run_row.model_type,
            "version": run_row.dataset_version,
            "published": _timestamp(run_row.published_at_ms),
            "cutoff": _timestamp(run_row.feature_cutoff_at_ms),
            "policy": run_row.as_of_policy,
        }
    cutoff = (
        _timestamp(run_row.feature_cutoff_at_ms)
        if run_row
        else f"{selected.date} 출전표 · 과거 기록은 경주일 이전"
    )
    return ForecastPage(
        dates,
        meets,
        distances,
        grades,
        selected_date.isoformat(),
        meet,
        distance,
        grade,
        races,
        selected,
        runners,
        model,
        cutoff,
    )


@dataclass(slots=True)
class ValidationRow:
    mode: str
    mode_label: str
    model: str
    version: str
    date: str
    meet: str
    race_id: int
    race_number: int
    distance: int
    grade: str
    horse: str
    number: int
    predicted_rank: int
    actual_rank: str
    difference: str
    prob_win: str
    prob_top3: str
    result_state: str


@dataclass(slots=True)
class ValidationPage:
    rows: list[ValidationRow]
    meets: list[tuple[int, str]]
    models: list[str]
    grades: list[str]
    summary: dict[str, Any]
    mode_summaries: list[dict[str, Any]]
    filters: dict[str, Any]


def load_validation_page(
    session: Session,
    *,
    start: date | None = None,
    end: date | None = None,
    meet: int | None = None,
    distance: int | None = None,
    grade: str = "",
    model: str = "",
    mode: str = "",
    limit: int = 250,
) -> ValidationPage:
    metadata = session.execute(
        select(
            PredictionRun.race_date_local,
            PredictionRun.model_type,
            PredictionRun.dataset_version,
        ).order_by(PredictionRun.race_date_local)
    ).all()
    dates = [row[0] for row in metadata]
    start = start or (min(dates) if dates else None)
    end = end or (max(dates) if dates else None)
    conditions = []
    if start:
        conditions.append(Race.race_date_local >= start)
    if end:
        conditions.append(Race.race_date_local <= end)
    if meet:
        conditions.append(Racecourse.kra_meet_code == meet)
    if distance:
        conditions.append(Race.distance_m == distance)
    if grade:
        conditions.append(Race.grade == grade)
    if model:
        conditions.append(PredictionRun.dataset_version == model)
    if mode in {"live", "historical"}:
        conditions.append(PredictionRun.publication_mode == mode)
    raw = session.execute(
        select(
            PredictionRun.publication_mode,
            PredictionRun.model_type,
            Race.race_date_local,
            Racecourse.name_ko,
            Race.race_number,
            Race.distance_m,
            Race.grade,
            Race.id,
            Horse.name_ko,
            ModelPrediction.horse_number,
            ModelPrediction.prob_win,
            ModelPrediction.prob_top3,
            PredictionOutcome.finish_position,
            RaceResult.finish_position,
            PredictionOutcome.is_scored,
            PredictionOutcome.exclusion_reason,
            PredictionRun.dataset_version,
        )
        .join(ModelPrediction, ModelPrediction.prediction_run_id == PredictionRun.id)
        .join(Race, Race.id == ModelPrediction.race_id)
        .join(Racecourse, Racecourse.id == Race.racecourse_id)
        .join(RaceEntry, RaceEntry.id == ModelPrediction.race_entry_id)
        .join(Horse, Horse.id == RaceEntry.horse_id)
        .outerjoin(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .outerjoin(PredictionOutcome, PredictionOutcome.model_prediction_id == ModelPrediction.id)
        .where(*conditions)
        .order_by(Race.race_date_local.desc(), Race.race_number, ModelPrediction.prob_win.desc())
        .limit(limit)
    ).all()
    ranks: dict[tuple[str, int], int] = defaultdict(int)
    rows: list[ValidationRow] = []
    scored_by_mode: dict[str, list[Any]] = defaultdict(list)
    for item in raw:
        key = (item[0], item[7])
        ranks[key] += 1
        predicted_rank = ranks[key]
        if item[14]:
            result_state = "평가 포함"
        elif item[15]:
            result_state = f"제외 · {item[15]}"
        elif item[13] is not None:
            result_state = "미정산 · 지표 제외"
        else:
            result_state = "미정산"
        actual = item[12] if item[12] is not None else item[13]
        display_actual = actual if actual is not None and actual < 90 else None
        diff = "—" if display_actual is None else f"{predicted_rank - display_actual:+d}"
        rows.append(
            ValidationRow(
                mode=item[0],
                mode_label="사전 공개" if item[0] == "live" else "과거 재현",
                model=item[1],
                version=item[16],
                date=item[2].isoformat(),
                meet=item[3],
                race_id=item[7],
                race_number=item[4],
                distance=item[5],
                grade=item[6] or "—",
                horse=item[8],
                number=item[9],
                predicted_rank=predicted_rank,
                actual_rank=str(display_actual) if display_actual is not None else "—",
                difference=diff,
                prob_win=_pct(item[10]),
                prob_top3=_pct(item[11]),
                result_state=result_state,
            )
        )
        if item[14]:
            scored_by_mode[item[0]].append((item, predicted_rank))

    def summarize(items: list[Any]) -> dict[str, Any]:
        if not items:
            return {"entries": 0, "races": 0, "top1": "—", "top3": "—", "mae": "—", "log_loss": "—"}
        race_ids = {item[0][7] for item in items}
        winners = [item for item in items if item[0][12] == 1]
        top1 = sum(rank == 1 for _, rank in winners) / len(winners) if winners else None
        top3 = sum(rank <= 3 for _, rank in winners) / len(winners) if winners else None
        mae = sum(abs(rank - item[12]) for item, rank in items) / len(items)
        import math

        loss = -sum(
            math.log(max(min(item[10], 1 - 1e-15), 1e-15))
            if item[12] == 1
            else math.log(max(1 - min(max(item[10], 0), 1 - 1e-15), 1e-15))
            for item, _ in items
        ) / len(items)
        return {
            "entries": len(items),
            "races": len(race_ids),
            "top1": _pct(top1),
            "top3": _pct(top3),
            "mae": f"{mae:.2f}",
            "log_loss": f"{loss:.4f}",
        }

    all_scored = [item for values in scored_by_mode.values() for item in values]
    mode_summaries = []
    for key in sorted({item[0] for item in raw}):
        published = [item for item in raw if item[0] == key]
        item_summary = summarize(scored_by_mode[key])
        item_summary["published_entries"] = len(published)
        item_summary["published_races"] = len({item[7] for item in published})
        mode_summaries.append(
            {
                "mode": key,
                "label": "사전 공개" if key == "live" else "과거 재현",
                **item_summary,
            }
        )
    meets = session.execute(
        select(Racecourse.kra_meet_code, Racecourse.name_ko).order_by(Racecourse.kra_meet_code)
    ).all()
    models = sorted({row[2] for row in metadata})
    grades = sorted(
        {row[0] for row in session.execute(select(Race.grade).where(Race.grade.is_not(None))).all()}
    )
    return ValidationPage(
        rows=rows,
        meets=list(meets),
        models=models,
        grades=grades,
        summary=summarize(all_scored),
        mode_summaries=mode_summaries,
        filters={
            "start": start.isoformat() if start else "",
            "end": end.isoformat() if end else "",
            "meet": meet,
            "distance": distance,
            "grade": grade,
            "model": model,
            "mode": mode,
        },
    )


@dataclass(slots=True)
class AnalysisHorse:
    horse_id: int
    name: str
    starts: int
    wins: int
    top3: int
    win_rate: str
    top3_rate: str
    average_finish: str
    average_time: str
    jockey: str
    early_position: float | None
    closing_time: float | None
    section_sample: int
    trend: list[dict[str, Any]]
    distances: list[dict[str, Any]]


@dataclass(slots=True)
class AnalysisPage:
    horses: list[AnalysisHorse]
    candidates: list[tuple[int, str]]
    meets: list[tuple[int, str]]
    grades: list[str]
    jockeys: list[dict[str, Any]]
    horse_jockeys: list[dict[str, Any]]
    head_to_head: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    filters: dict[str, Any]

    def chart_json(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in self.horses]


def load_analysis_page(
    session: Session,
    *,
    start: date | None = None,
    end: date | None = None,
    meet: int | None = None,
    distance: int | None = None,
    grade: str = "",
    horse_ids: list[int] | None = None,
    jockey_id: int | None = None,
    query: str = "",
) -> AnalysisPage:
    latest = session.scalar(
        select(func.max(Race.race_date_local)).where(Race.status == "completed")
    )
    end = end or latest or date.today()
    start = start or end - timedelta(days=180)
    base_conditions = [
        Race.race_date_local >= start,
        Race.race_date_local <= end,
        RaceResult.finish_position.is_not(None),
        RaceResult.disqualified.is_(False),
        RaceResult.finish_position < 90,
    ]
    if meet:
        base_conditions.append(Racecourse.kra_meet_code == meet)
    if distance:
        base_conditions.append(Race.distance_m == distance)
    if grade:
        base_conditions.append(Race.grade == grade)
    if jockey_id:
        base_conditions.append(RaceEntry.jockey_id == jockey_id)
    horse_conditions = [*base_conditions]
    if query:
        horse_conditions.append(Horse.name_ko.contains(query))

    candidate_rows = session.execute(
        select(Horse.id, Horse.name_ko, func.count(RaceEntry.id).label("starts"))
        .join(RaceEntry, RaceEntry.horse_id == Horse.id)
        .join(Race, Race.id == RaceEntry.race_id)
        .join(Racecourse, Racecourse.id == Race.racecourse_id)
        .join(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .where(*horse_conditions)
        .group_by(Horse.id)
        .order_by(func.count(RaceEntry.id).desc(), Horse.name_ko)
        .limit(80)
    ).all()
    candidates = [(row[0], row[1]) for row in candidate_rows]
    selected_ids = list(dict.fromkeys(horse_ids or [row[0] for row in candidate_rows[:5]]))[:8]
    if not selected_ids:
        return AnalysisPage(
            [],
            candidates,
            [],
            [],
            [],
            [],
            [],
            [],
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "meet": meet,
                "distance": distance,
                "grade": grade,
                "horse_ids": [],
                "jockey_id": jockey_id,
                "query": query,
            },
        )

    detail_rows = session.execute(
        select(
            Horse.id,
            Horse.name_ko,
            Race.race_date_local,
            Race.id,
            Race.race_number,
            Racecourse.name_ko,
            Race.distance_m,
            Race.grade,
            RaceResult.finish_position,
            RaceResult.finish_time_ms,
            Jockey.id,
            Jockey.name_ko,
            RaceEntry.id,
        )
        .join(RaceEntry, RaceEntry.horse_id == Horse.id)
        .join(Race, Race.id == RaceEntry.race_id)
        .join(Racecourse, Racecourse.id == Race.racecourse_id)
        .join(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .outerjoin(Jockey, Jockey.id == RaceEntry.jockey_id)
        .where(*horse_conditions, Horse.id.in_(selected_ids))
        .order_by(Horse.id, Race.race_date_local.desc(), Race.id.desc())
        .limit(1000)
    ).all()
    by_horse: dict[int, list[Any]] = defaultdict(list)
    for row in detail_rows:
        by_horse[row[0]].append(row)
    section_rows = session.execute(
        select(
            RaceEntry.horse_id,
            RaceSectionResult.section_code,
            RaceSectionResult.elapsed_time_ms,
            RaceSectionResult.position,
            RaceSectionResult.time_basis,
        )
        .join(RaceEntry, RaceEntry.id == RaceSectionResult.race_entry_id)
        .where(
            RaceEntry.id.in_([row[12] for row in detail_rows]),
            RaceSectionResult.section_code.in_(["S1F", "1C", "2C", "3C", "G1F"]),
        )
    ).all()
    sections_by_horse: dict[int, list[Any]] = defaultdict(list)
    for row in section_rows:
        sections_by_horse[row[0]].append(row)
    horses: list[AnalysisHorse] = []
    for horse_id in selected_ids:
        records = by_horse[horse_id]
        if not records:
            continue
        starts = len(records)
        wins = sum(row[8] == 1 for row in records)
        top3 = sum(row[8] <= 3 for row in records)
        times = [row[9] for row in records if row[9]]
        distances_map: dict[int, list[Any]] = defaultdict(list)
        for row in records:
            distances_map[row[6]].append(row)
        sections = sections_by_horse[horse_id]
        early_positions = [
            row[3] for row in sections if row[1] in {"S1F", "1C", "2C", "3C"} and row[3] is not None
        ]
        closing_times = [
            row[2] / 1000
            for row in sections
            if row[1] == "G1F" and row[2] and row[4] in {"closing", None}
        ]
        horses.append(
            AnalysisHorse(
                horse_id=horse_id,
                name=records[0][1],
                starts=starts,
                wins=wins,
                top3=top3,
                win_rate=_pct(wins / starts),
                top3_rate=_pct(top3 / starts),
                average_finish=f"{sum(row[8] for row in records) / starts:.2f}",
                average_time=_time(round(sum(times) / len(times))) if times else "—",
                jockey=records[0][11] or "—",
                early_position=(
                    round(sum(early_positions) / len(early_positions), 2)
                    if early_positions
                    else None
                ),
                closing_time=(
                    round(sum(closing_times) / len(closing_times), 2) if closing_times else None
                ),
                section_sample=max(len(early_positions), len(closing_times)),
                trend=[
                    {
                        "date": row[2].isoformat(),
                        "finish": row[8],
                        "time": row[9] / 1000 if row[9] else None,
                        "distance": row[6],
                    }
                    for row in reversed(records[:12])
                ],
                distances=[
                    {
                        "distance": key,
                        "starts": len(values),
                        "top3": sum(row[8] <= 3 for row in values),
                        "rate": round(sum(row[8] <= 3 for row in values) / len(values), 4),
                    }
                    for key, values in sorted(distances_map.items())
                ],
            )
        )
    jockey_rows = session.execute(
        select(
            Jockey.id,
            Jockey.name_ko,
            func.count(RaceEntry.id),
            func.sum(case((RaceResult.finish_position == 1, 1), else_=0)),
            func.sum(case((RaceResult.finish_position <= 3, 1), else_=0)),
        )
        .join(RaceEntry, RaceEntry.jockey_id == Jockey.id)
        .join(Race, Race.id == RaceEntry.race_id)
        .join(Racecourse, Racecourse.id == Race.racecourse_id)
        .join(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .where(*base_conditions)
        .group_by(Jockey.id)
        .order_by(func.count(RaceEntry.id).desc())
        .limit(12)
    ).all()
    jockeys = [
        {
            "id": row[0],
            "name": row[1],
            "starts": row[2],
            "wins": row[3],
            "top3": row[4],
            "win_rate": _pct(row[3] / row[2]),
            "top3_rate": _pct(row[4] / row[2]),
        }
        for row in jockey_rows
    ]
    horse_jockey_groups: dict[tuple[int, int], list[Any]] = defaultdict(list)
    for row in detail_rows:
        if row[10] is not None:
            horse_jockey_groups[(row[0], row[10])].append(row)
    horse_jockeys = [
        {
            "horse": values[0][1],
            "jockey": values[0][11],
            "starts": len(values),
            "wins": sum(row[8] == 1 for row in values),
            "top3": sum(row[8] <= 3 for row in values),
            "top3_rate": _pct(sum(row[8] <= 3 for row in values) / len(values)),
        }
        for values in horse_jockey_groups.values()
    ]
    horse_jockeys.sort(key=lambda row: (-row["starts"], row["horse"], row["jockey"]))

    race_groups: dict[int, list[Any]] = defaultdict(list)
    for row in detail_rows:
        race_groups[row[3]].append(row)
    pair_results: dict[tuple[int, int], dict[str, Any]] = {}
    for values in race_groups.values():
        for first, second in combinations(sorted(values, key=lambda row: row[0]), 2):
            key = (first[0], second[0])
            result = pair_results.setdefault(
                key,
                {
                    "first": first[1],
                    "second": second[1],
                    "meetings": 0,
                    "first_wins": 0,
                    "second_wins": 0,
                    "ties": 0,
                },
            )
            result["meetings"] += 1
            if first[8] < second[8]:
                result["first_wins"] += 1
            elif second[8] < first[8]:
                result["second_wins"] += 1
            else:
                result["ties"] += 1
    head_to_head = sorted(pair_results.values(), key=lambda row: -row["meetings"])
    table_rows = [
        {
            "horse_id": row[0],
            "horse": row[1],
            "date": row[2].isoformat(),
            "race_id": row[3],
            "race": row[4],
            "meet": row[5],
            "distance": row[6],
            "grade": row[7] or "—",
            "finish": row[8],
            "time": _time(row[9]),
            "jockey": row[11] or "—",
        }
        for row in detail_rows[:250]
    ]
    meets = session.execute(
        select(Racecourse.kra_meet_code, Racecourse.name_ko).order_by(Racecourse.kra_meet_code)
    ).all()
    grades = sorted(
        {row[0] for row in session.execute(select(Race.grade).where(Race.grade.is_not(None))).all()}
    )
    return AnalysisPage(
        horses,
        candidates,
        list(meets),
        grades,
        jockeys,
        horse_jockeys[:16],
        head_to_head[:20],
        table_rows,
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "meet": meet,
            "distance": distance,
            "grade": grade,
            "horse_ids": selected_ids,
            "jockey_id": jockey_id,
            "query": query,
        },
    )
