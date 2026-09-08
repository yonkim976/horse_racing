from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from horse_racing.db.models import RunningTrial, RunningTrialResult
from horse_racing.services.entry_sheet import MEET_METADATA
from horse_racing.web.formatting import format_race_time

JUDGEMENT_LABELS = {
    "합": "합격",
    "불": "불합격",
    "유": "유보",
    "연": "연습",
    "출": "심사제외",
    "심": "심사취소",
    "주": "주행중지",
}


@dataclass(frozen=True, slots=True)
class TrialResultRow:
    horse_id: int | None
    horse_number: int
    horse_name: str
    horse_meta: str
    jockey_id: int | None
    jockey_name: str
    trainer_id: int | None
    trainer_name: str
    finish_position: str
    finish_sort: int
    judgement: str
    judgement_class: str
    carried_weight: str
    body_weight: str
    finish_time: str
    margin: str
    s1f: str
    g3f: str
    g1f: str
    passing_order: str
    inspection_reason: str
    failure_reason: str
    row_class: str


@dataclass(frozen=True, slots=True)
class RunningTrialPageData:
    id: int
    course_name: str
    meet_code: int
    race_number: int
    trial_round: str
    date_label: str
    date_iso: str
    distance: str
    weather_track: str
    entries: list[TrialResultRow]
    pass_count: int
    fail_count: int
    back_query: str
    prev_trial_id: int | None
    next_trial_id: int | None


def load_running_trial_page(
    session: Session, *, trial_id: int
) -> RunningTrialPageData | None:
    trial = session.scalar(
        select(RunningTrial)
        .where(RunningTrial.id == trial_id)
        .options(
            selectinload(RunningTrial.results).joinedload(RunningTrialResult.horse),
            selectinload(RunningTrial.results).joinedload(RunningTrialResult.jockey),
            selectinload(RunningTrial.results).joinedload(RunningTrialResult.trainer),
        )
    )
    if trial is None:
        return None

    entries = [_result_row(row) for row in trial.results]
    entries.sort(key=lambda row: (row.finish_sort, row.horse_number))
    condition_parts = [part for part in (trial.weather, trial.track_condition) if part]
    if trial.track_moisture_percent is not None:
        condition_parts.append(f"함수율 {trial.track_moisture_percent:g}%")
    previous_id, next_id = _neighbor_trial_ids(session, trial)
    return RunningTrialPageData(
        id=trial.id,
        course_name=MEET_METADATA[trial.meet_code][1],
        meet_code=trial.meet_code,
        race_number=trial.trial_race_number,
        trial_round=f"제{trial.trial_round}회" if trial.trial_round is not None else "회차 미상",
        date_label=trial.trial_date_local.strftime("%Y.%m.%d"),
        date_iso=trial.trial_date_local.isoformat(),
        distance=f"{trial.distance_m:,}m",
        weather_track=" · ".join(condition_parts) or "주로 정보 없음",
        entries=entries,
        pass_count=sum(row.judgement == "합격" for row in entries),
        fail_count=sum(row.judgement == "불합격" for row in entries),
        back_query=(
            f"date={trial.trial_date_local.isoformat()}&meet={trial.meet_code}"
            f"&trial_id={trial.id}"
        ),
        prev_trial_id=previous_id,
        next_trial_id=next_id,
    )


def _result_row(result: RunningTrialResult) -> TrialResultRow:
    finish_sort = result.finish_position if result.finish_position is not None else 999
    judgement = JUDGEMENT_LABELS.get(result.judgement or "", result.judgement or "미판정")
    judgement_class = (
        "pass" if result.judgement == "합" else "fail" if result.judgement == "불" else "neutral"
    )
    horse_meta = " · ".join(
        part
        for part in (
            result.origin_country,
            result.sex,
            f"{result.age}세" if result.age is not None else None,
        )
        if part
    )
    carried_weight = result.carried_weight_raw
    if not carried_weight and result.carried_weight_base_kg is not None:
        carried_weight = f"{result.carried_weight_base_kg:g}kg"
        if result.carried_weight_extra_kg:
            carried_weight += f" +{result.carried_weight_extra_kg:g}"
    row_classes = []
    if finish_sort <= 3:
        row_classes.extend(("placed", f"placed-{finish_sort}"))
    if result.judgement not in {"합", None}:
        row_classes.append("non-finisher")
    return TrialResultRow(
        horse_id=result.horse_id,
        horse_number=result.horse_number,
        horse_name=result.horse.name_ko if result.horse else result.horse_name_raw,
        horse_meta=horse_meta or "정보 없음",
        jockey_id=result.jockey_id,
        jockey_name=(
            result.jockey.name_ko
            if result.jockey
            else result.jockey_name_raw or "—"
        ),
        trainer_id=result.trainer_id,
        trainer_name=(
            result.trainer.name_ko
            if result.trainer
            else result.trainer_name_raw or "—"
        ),
        finish_position=(
            f"{result.finish_position}위"
            if result.finish_position is not None
            else result.finish_rank_raw or "—"
        ),
        finish_sort=finish_sort,
        judgement=judgement,
        judgement_class=judgement_class,
        carried_weight=carried_weight or "—",
        body_weight=f"{result.body_weight_kg}kg" if result.body_weight_kg else "—",
        finish_time=format_race_time(result.finish_time_ms),
        margin=result.margin_text or "—",
        s1f=_format_section(result.s1f_ms),
        g3f=_format_section(result.g3f_ms),
        g1f=_format_section(result.g1f_ms),
        passing_order=result.passing_order_raw or "—",
        inspection_reason=result.inspection_reason or "—",
        failure_reason=result.failure_reason or "—",
        row_class=" ".join(row_classes),
    )


def _neighbor_trial_ids(
    session: Session, trial: RunningTrial
) -> tuple[int | None, int | None]:
    rows = list(
        session.execute(
            select(RunningTrial.id, RunningTrial.trial_race_number)
            .where(
                RunningTrial.meet_code == trial.meet_code,
                RunningTrial.trial_date_local == trial.trial_date_local,
            )
            .order_by(RunningTrial.trial_race_number)
        )
    )
    for index, (trial_id, _number) in enumerate(rows):
        if trial_id == trial.id:
            previous_id = rows[index - 1][0] if index > 0 else None
            next_id = rows[index + 1][0] if index + 1 < len(rows) else None
            return previous_id, next_id
    return None, None


def _format_section(value: int | None) -> str:
    return f"{value / 1000:.1f}초" if value is not None else "—"
