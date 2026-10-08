"""Read-only descriptive horse profiles, using the frozen v1 research contract.

No model inference, rider inputs, gate corrections or database writes. References
are packaged small JSON assets; serving does not import the research toolchain.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from statistics import mean, stdev

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from horse_racing.db.models import Horse, Race, Racecourse, RaceEntry, RaceResult
from horse_racing.web.formatting import format_finish_position, format_race_time, today_seoul

REFERENCE_PATH = Path(__file__).with_name("data") / "horse_evaluation_v1.json"
MEETS = {1: "서울", 3: "부산경남"}


@dataclass(frozen=True, slots=True)
class EvaluationStart:
    race_date: date
    meet: int
    race_number: int
    distance: int
    grade: str
    finish_position: int | None
    finish_time_ms: int | None
    moisture: float | None
    disqualified: bool = False
    body_weight: int | None = None
    carried_weight: float | None = None
    race_id: int | None = None
    outcome_remark: str | None = None


@dataclass(frozen=True, slots=True)
class EvaluatedStart:
    source: EvaluationStart
    raw_index: float | None
    moist_index: float | None
    corrected_seconds: float | None
    supported: bool
    status: str
    raw_reference: tuple[float, float] | None = None
    moist_reference: tuple[float, float] | None = None

    @property
    def raw_seconds(self) -> float | None:
        return self.source.finish_time_ms / 1000 if self.source.finish_time_ms else None

    @property
    def correction_seconds(self) -> float | None:
        if self.corrected_seconds is None or self.raw_seconds is None:
            return None
        return self.corrected_seconds - self.raw_seconds

    @property
    def moisture_label(self) -> str:
        band = moisture_band(self.source.moisture)
        return f"{band} · 함수율 {self.source.moisture:g}%" if band else "함수율 미확인"

    @property
    def correction_explanation(self) -> str:
        delta = self.correction_seconds
        if delta is None:
            return "유효 전체기록이 없어 보정하지 않음"
        if not self.supported:
            return "보정 근거가 없어 원기록 유지"
        if abs(delta) < 0.005:
            return "추정한 시간 조정 없음"
        if delta > 0:
            return "주로가 기록을 빠르게 한 효과를 추정해 시간을 더함"
        return "주로가 기록을 느리게 한 효과를 추정해 시간을 뺌"

    @property
    def reference_gap(self) -> float | None:
        if self.moist_reference is None or self.corrected_seconds is None:
            return None
        return self.moist_reference[0] - self.corrected_seconds

    @property
    def comparison(self) -> str:
        if self.reference_gap is None:
            return "비교 기준 또는 유효 기록 없음"
        return _gap_description(self.reference_gap)

    @property
    def race_label(self) -> str:
        s = self.source
        return f"{MEETS.get(s.meet, '기타')} {s.race_number}R · {s.distance}m · {s.grade}"

    @property
    def href(self) -> str | None:
        return f"/races/{self.source.race_id}" if self.source.race_id is not None else None

    @property
    def finish_label(self) -> str:
        if self.source.disqualified:
            return "실격"
        if self.source.outcome_remark in ("중지", "주행중지"):
            return "주행중지"
        return format_finish_position(self.source.finish_position)[0]

    @property
    def time_label(self) -> str:
        return format_race_time(self.source.finish_time_ms)


@dataclass(frozen=True, slots=True)
class EvaluationMetric:
    label: str
    raw: float | None
    corrected: float | None
    evidence: str
    description: str
    interpretation: str


@dataclass(frozen=True, slots=True)
class HorseEvaluation:
    as_of: date
    cutoff: date
    status: str
    version: str
    metrics: list[EvaluationMetric]
    history: list[EvaluatedStart]
    state: list[tuple[str, str]]
    best: EvaluatedStart | None
    valid5: int
    supported5: int


@lru_cache(maxsize=1)
def load_references() -> dict:
    return json.loads(REFERENCE_PATH.read_text())


def moisture_band(value: float | None) -> str | None:
    if value is None or not math.isfinite(value) or not 0 < value <= 100:
        return None
    for upper, label in ((5, "건조"), (9, "양호"), (14, "다습"), (19, "포화")):
        if value <= upper:
            return label
    return "불량"


def evaluate_start(start: EvaluationStart, refs: dict) -> EvaluatedStart:
    seconds = start.finish_time_ms / 1000 if start.finish_time_ms else None
    valid = (
        start.meet in MEETS
        and start.race_date.year >= 2017
        and not start.disqualified
        and start.outcome_remark not in ("중지", "주행중지", "실격")
        and start.finish_position is not None
        and 1 <= start.finish_position <= 20
        and seconds is not None
        and seconds > 0
        and 10 <= start.distance / seconds <= 20
    )
    if not valid:
        return EvaluatedStart(start, None, None, None, False, "유효 전체기록 없음")
    key = f"{start.meet}:{start.race_date.year}:{start.distance}"
    band = moisture_band(start.moisture)
    correction = refs["corrections"].get(f"{key}:{band}") if band else None
    adjusted = seconds + (correction if correction is not None else 0)

    def index(name: str, time: float) -> float | None:
        ref = refs[name].get(key)
        return max(-10.0, min(10.0, (ref[0] - time) / ref[1])) if ref else None

    raw, moist = index("raw", seconds), index("moist", adjusted)
    status = (
        "비교 기준 없음"
        if moist is None
        else "주로 보정 적용"
        if correction is not None
        else "함수율 미확인 · 원기록 유지"
        if band is None
        else "보정 근거 부족 · 원기록 유지"
    )
    return EvaluatedStart(
        start,
        raw,
        moist,
        adjusted,
        correction is not None,
        status,
        tuple(refs["raw"][key]) if key in refs["raw"] else None,
        tuple(refs["moist"][key]) if key in refs["moist"] else None,
    )


def _gap_description(gap: float) -> str:
    if abs(gap) < 0.005:
        return "과거 중앙기록과 비슷함 (차이 0.01초 미만)"
    return f"과거 중앙기록보다 {abs(gap):.2f}초 {'빠름' if gap > 0 else '느림'}"


def _same_reference(rows: list[EvaluatedStart]) -> bool:
    """Only show aggregate seconds when venue, distance, year and scale agree."""
    return (
        bool(rows)
        and len(
            {
                (r.source.meet, r.source.distance, r.source.race_date.year, r.moist_reference)
                for r in rows
            }
        )
        == 1
    )


def metric_interpretations(history: list[EvaluatedStart]) -> dict[str, str]:
    recent = [r for r in history[:3] if r.moist_index is not None]
    previous = [r for r in history[3:6] if r.moist_index is not None]
    five = [r for r in history[:5] if r.moist_index is not None]
    ranked = sorted(five, key=lambda r: r.moist_index, reverse=True)

    def comparison(rows: list[EvaluatedStart], minimum: int = 1) -> str:
        if len(rows) < minimum:
            return "유효 기록이 부족해 해석 보류"
        if not _same_reference(rows):
            return "경마장·거리 또는 기준연도 혼합 · 출전별 시간차 확인 필요"
        gap = _gap_description(mean(r.reference_gap for r in rows))
        return f"{rows[0].source.distance}m 기준 · {gap}"

    trend = "최근·이전 3전의 유효 기록이 각각 2개 이상 필요"
    if len(recent) >= 2 and len(previous) >= 2:
        if _same_reference(recent + previous):
            change = mean(r.reference_gap for r in recent) - mean(r.reference_gap for r in previous)
            direction = "빨라짐" if change > 0 else "느려짐"
            trend = (
                "이전 3전과 최근 3전의 평균 기록 차이 0.01초 미만"
                if abs(change) < 0.005
                else f"이전 3전보다 최근 3전 평균 {abs(change):.2f}초 {direction}"
            )
        else:
            trend = "조건 혼합 · 환산 지수의 변화이며 초 단위로 합쳐 해석하지 않음"
    stability = "최근 5전에 유효 기록 3개 이상 필요"
    if len(five) >= 3:
        stability = (
            f"보정 기록의 표준편차 {stdev(r.corrected_seconds for r in five):.2f}초"
            " · 작을수록 기록 차이가 작음"
            if _same_reference(five)
            else "조건 혼합 · 시간 차이가 아닌 환산 지수의 변동 폭"
        )
    return {
        "last": comparison(history[:1] if history and history[0].moist_index is not None else []),
        "mean3": comparison(recent),
        "best5": comparison(ranked[:1]),
        "top2mean5": comparison(ranked[:2], minimum=2),
        "trend": trend,
        "std5": stability,
    }


def profile_metrics(values: list[float | None]) -> dict[str, float | int | None]:
    """Newest actual starts first. Missing starts retain their window positions."""
    a = [x for x in values[:3] if x is not None]
    b = [x for x in values[:5] if x is not None]
    c = [x for x in values[3:6] if x is not None]
    return {
        "last": values[0] if values else None,
        "mean3": mean(a) if a else None,
        "best5": max(b) if b else None,
        "top2mean5": mean(sorted(b)[-2:]) if len(b) >= 2 else None,
        "trend": mean(a) - mean(c) if len(a) >= 2 and len(c) >= 2 else None,
        "std5": stdev(b) if len(b) >= 3 else None,
        "count3": len(a),
        "count5": len(b),
        "previous3_count": len(c),
    }


def build_evaluation(
    starts: list[EvaluationStart], *, as_of: date, refs: dict | None = None
) -> HorseEvaluation:
    refs = load_references() if refs is None else refs
    cutoff = as_of - timedelta(days=2)
    eligible = sorted(
        (s for s in starts if s.race_date <= cutoff and s.meet in MEETS),
        key=lambda s: (s.race_date, s.race_number),
        reverse=True,
    )[:10]
    history = [evaluate_start(s, refs) for s in eligible]
    raw = profile_metrics([s.raw_index for s in history])
    moist = profile_metrics([s.moist_index for s in history])
    valid5 = int(moist["count5"])
    supported5 = sum(s.supported and s.moist_index is not None for s in history[:5])
    specs = [
        ("last", "직전 능력", f"최근 {min(1, len(history))}전", "직전 출전의 전체기록 지수"),
        (
            "mean3",
            "최근 능력",
            f"유효 {moist['count3']} / 최근 {min(3, len(history))}전",
            "최근 3전의 유효 기록 평균",
        ),
        (
            "best5",
            "최고 능력",
            f"유효 {valid5} / 최근 {min(5, len(history))}전",
            "최근 5전 중 가장 높은 기록 지수",
        ),
        ("top2mean5", "반복 능력", "유효 기록 2개 이상 필요", "최근 5전 중 상위 2개 기록의 평균"),
        (
            "trend",
            "최근 변화",
            f"최근 3전 {moist['count3']}개 · 이전 3전 {moist['previous3_count']}개",
            "최근 3전 평균 − 그 이전 3전 평균 · 양수면 기록 지수 상승",
        ),
        (
            "std5",
            "기록 변동성",
            "유효 기록 3개 이상 필요",
            "최근 5전의 표준편차 · 작을수록 기록이 일정",
        ),
    ]
    interpretations = metric_interpretations(history)
    metrics = [
        EvaluationMetric(label, raw[k], moist[k], evidence, desc, interpretations[k])
        for k, label, evidence, desc in specs
    ]
    available = [s for s in history[:5] if s.moist_index is not None]
    best = max(available, key=lambda s: s.moist_index) if available else None
    status = (
        "실전 이력 없음"
        if not history
        else "최근 5전 유효 지수 없음"
        if not valid5
        else "단일 관측"
        if valid5 == 1
        else "복수 관측"
    )
    state: list[tuple[str, str]] = []
    if history:
        last = history[0].source
        state = [
            ("마지막 출전", last.race_date.isoformat()),
            ("마지막 출전 후", f"{(as_of - last.race_date).days}일"),
            ("직전 마체중", f"{last.body_weight}kg" if last.body_weight else "—"),
            ("직전 부담중량", f"{last.carried_weight:g}kg" if last.carried_weight else "—"),
            ("최근 10전 거리", " · ".join(f"{d}m" for d in sorted({s.distance for s in eligible}))),
        ]
    return HorseEvaluation(
        as_of, cutoff, status, refs["version"], metrics, history, state, best, valid5, supported5
    )


def load_horse_evaluation(
    session: Session, horse: Horse, *, as_of: date | None = None
) -> HorseEvaluation | None:
    if horse.meet_code not in (None, 1, 3):
        return None
    as_of = as_of or today_seoul()
    # Bound the query per horse using ix_race_entries_horse_race; never scan the
    # entire result corpus or load scheduled entries to fill an actual-start window.
    entries = (
        session.scalars(
            select(RaceEntry)
            .join(RaceEntry.race)
            .join(Race.racecourse)
            .join(RaceEntry.result)
            .where(
                RaceEntry.horse_id == horse.id,
                Racecourse.kra_meet_code.in_([1, 3]),
                Race.status == "completed",
                Race.race_date_local <= as_of - timedelta(days=2),
                # Historical text-imported stops/DQs can have scratched=True.
                or_(
                    RaceEntry.scratched.is_(False),
                    RaceResult.disqualified.is_(True),
                    RaceResult.rank_remark.in_(["중지", "주행중지", "실격"]),
                ),
                or_(
                    RaceResult.finish_position.between(1, 20),
                    RaceResult.finish_position.in_([93, 96]),
                    RaceResult.disqualified.is_(True),
                    RaceResult.rank_remark.in_(["중지", "주행중지", "실격"]),
                ),
            )
            .options(
                joinedload(RaceEntry.race).joinedload(Race.racecourse), joinedload(RaceEntry.result)
            )
            .order_by(Race.race_date_local.desc(), Race.race_number.desc())
            .limit(10)
        )
        .unique()
        .all()
    )
    starts = [
        EvaluationStart(
            race_date=e.race.race_date_local,
            meet=e.race.racecourse.kra_meet_code,
            race_number=e.race.race_number,
            distance=e.race.distance_m,
            grade=e.race.grade or "—",
            finish_position=e.result.finish_position,
            finish_time_ms=e.result.finish_time_ms,
            moisture=e.race.track_moisture_percent,
            disqualified=e.result.disqualified,
            body_weight=e.body_weight_kg,
            carried_weight=e.carried_weight_kg,
            race_id=e.race.id,
            outcome_remark=e.result.rank_remark,
        )
        for e in entries
    ]
    if horse.meet_code is None and not starts:
        return None
    return build_evaluation(starts, as_of=as_of)
