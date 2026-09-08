"""G3 group. Time-varying kickback/sand response state.

Explicit adverse reactions are extracted from historical steward text.  A
horse is not marked sensitive forever: the state decays with time and is
reduced when the horse later runs normally despite a high estimated kickback
exposure.  Target-day reports and results are always applied after target
features are emitted.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, timedelta

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames, as_date

GROUP = "G3. 모래반응·회복 상태"
_STATE_HALF_LIFE_DAYS = 365.0
_RECENT_DAYS = 365
_NEXT_HORSE_RE = re.compile(r"[①-⑳]\s*[“\"]")

_SEVERITY_CUES = (
    ("탄력이 급격히 떨어", 1.0),
    ("뛰지 않", 1.0),
    ("모래에 예민", 0.95),
    ("예민하게 반응", 0.9),
    ("머리를 들", 0.8),
    ("탄력이 떨어", 0.75),
    ("모래를 피하", 0.65),
    ("주행이 불량", 0.6),
)
_RECOVERY_CUES = (
    ("모래 반응이 크지 않", 1.0),
    ("반응도 크지 않", 1.0),
    ("모래에 대한 반응이 크지 않", 1.0),
    ("예민한 반응을 보이지 않", 0.9),
    ("모래를 맞고도 탄력이 유지", 0.9),
    ("모래를 맞았음에도 탄력이 유지", 0.9),
)
_CURRENT_ADVERSE_ANCHORS = (
    "모래를 맞자",
    "모래를 맞으며",
    "모래를 맞고 탄력이",
    "모래를 맞은 후",
    "모래를 맞아 탄력이",
    "모래를 맞게 되자 탄력이",
)

FEATURES = [
    FeatureSpec(
        name="sand_incident_count_prior",
        group=GROUP,
        description="심판보고서에서 확인된 과거 모래 이상반응 누적 횟수",
        source="race_steward_reports + 출전마명",
        lookback="전 기간",
        null_policy="명시 반응 없으면 0",
        leakage_note="대상 경주일 보고서는 다음 경주부터 반영",
    ),
    FeatureSpec(
        name="sand_incident_count_365d",
        group=GROUP,
        description="최근 365일 명시적 모래 이상반응 횟수",
        source="race_steward_reports",
        lookback="365일",
        null_policy="없으면 0",
        leakage_note="대상 경주일 제외",
    ),
    FeatureSpec(
        name="sand_days_since_incident",
        group=GROUP,
        description="마지막 명시적 모래 이상반응 후 경과일",
        source="race_steward_reports",
        lookback="직전 사건",
        null_policy="사건 없으면 null",
        leakage_note="대상 경주일 제외",
    ),
    FeatureSpec(
        name="sand_sensitivity_state",
        group=GROUP,
        description="재발·시간감쇠·후속 정상노출을 반영한 말별 모래 민감도(0~1)",
        source="명시 반응 + 후속 고노출 경주",
        lookback="전 기간, 365일 반감기",
        null_policy="사건 없으면 0",
        leakage_note="같은 날짜 feature 출력 후 상태 갱신",
    ),
    FeatureSpec(
        name="sand_recovery_evidence",
        group=GROUP,
        description="마지막 반응 이후 모래 고노출 추정 경주에서 정상 수행한 누적 증거",
        source="과거 S1F 위치·게이트·출전두수·착순",
        lookback="마지막 반응 이후",
        null_policy="증거 없으면 0",
        leakage_note="현재 경주 결과 제외",
    ),
    FeatureSpec(
        name="sand_recovery_score",
        group=GROUP,
        description="민감도 감소와 정상노출 증거를 결합한 회복 점수(0~1)",
        source="sand_sensitivity_state + recovery evidence",
        lookback="마지막 반응 이후",
        null_policy="반응 이력 없으면 0",
        leakage_note="현재 경주 결과 제외",
    ),
    FeatureSpec(
        name="sand_recovered_flag",
        group=GROUP,
        description="충분한 정상노출 증거와 낮은 현재 민감도를 함께 만족하면 1",
        source="회복 상태 규칙",
        lookback="마지막 반응 이후",
        null_policy="반응 이력 없거나 미회복이면 0",
        leakage_note="현재 경주 결과 제외",
    ),
    FeatureSpec(
        name="sand_exposure_risk",
        group=GROUP,
        description="이번 경주의 스타일·게이트·출전두수 기반 모래 노출 위험(0~1)",
        source="early_pos_pct_avg5 + horse_number_pct + starters",
        null_policy="결측 입력은 중립값",
        leakage_note="현재 출전표와 과거 스타일만 사용",
    ),
    FeatureSpec(
        name="sand_expected_penalty",
        group=GROUP,
        description="현재 민감도×모래 노출위험×상태 신뢰도",
        source="sand sensitivity state + exposure risk",
        null_policy="민감도 이력 없으면 0",
        leakage_note="모든 입력은 경주 전 정보",
    ),
    FeatureSpec(
        name="sand_state_reliability",
        group=GROUP,
        description="최근 사건과 회복증거 및 정보 최신성을 반영한 상태 신뢰도",
        source="사건·회복 상태",
        null_policy="정보 없으면 0",
        leakage_note="현재 경주 결과 제외",
    ),
]

FEATURE_NAMES = tuple(spec.name for spec in FEATURES)


@dataclass
class _SandState:
    sensitivity: float = 0.0
    incident_count: int = 0
    incident_dates: deque[date] = field(default_factory=deque)
    last_incident: date | None = None
    last_state_date: date | None = None
    last_evidence_date: date | None = None
    recovery_evidence: float = 0.0
    finish_ewma: float | None = None
    finish_observations: int = 0


def _horse_text_block(text: str, horse_name: str) -> str:
    candidates = [f"“{horse_name}”", f'"{horse_name}"']
    blocks: list[str] = []
    for marker in candidates:
        start = 0
        while True:
            index = text.find(marker, start)
            if index < 0:
                break
            next_match = _NEXT_HORSE_RE.search(text, index + len(marker))
            end = next_match.start() if next_match else len(text)
            blocks.append(text[index:end])
            start = index + len(marker)
    return " ".join(blocks)


def sand_reaction_severity(text: str, horse_name: str) -> float:
    """Return explicit adverse sand-reaction severity for one named runner."""
    block = _horse_text_block(text or "", horse_name)
    if "모래" not in block:
        return 0.0
    # A steward explanation can describe a horse's old/general tendency and
    # explicitly say that the reaction was small today.  Do not turn that
    # improvement statement into a new incident merely because words such as
    # "뛰지 않으려는 습성" also occur in the same block.
    if any(cue in block for cue, _ in _RECOVERY_CUES) and not any(
        anchor in block for anchor in _CURRENT_ADVERSE_ANCHORS
    ):
        return 0.0
    if "모래를 거의 맞지 않" in block and not any(
        cue in block for cue, _ in _SEVERITY_CUES
    ):
        return 0.0
    return max((weight for cue, weight in _SEVERITY_CUES if cue in block), default=0.0)


def sand_recovery_observation(text: str, horse_name: str) -> float:
    """Return strength of an explicit current-race reduced-reaction statement."""
    block = _horse_text_block(text or "", horse_name)
    if "모래" not in block:
        return 0.0
    return max((weight for cue, weight in _RECOVERY_CUES if cue in block), default=0.0)


def _reported_events(
    past: pl.DataFrame,
    reports: pl.DataFrame,
) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], float]]:
    required_past = {"race_id", "horse_id", "horse_name"}
    required_reports = {"race_id", "judgement", "additional_judgement"}
    if (
        past.height == 0
        or reports.height == 0
        or not required_past <= set(past.columns)
        or not required_reports <= set(reports.columns)
    ):
        return {}, {}
    entries = defaultdict(list)
    for row in past.select("race_id", "horse_id", "horse_name").unique().iter_rows(named=True):
        entries[int(row["race_id"])].append((int(row["horse_id"]), str(row["horse_name"])))
    incidents: dict[tuple[int, int], float] = {}
    recoveries: dict[tuple[int, int], float] = {}
    for row in reports.iter_rows(named=True):
        race_id = int(row["race_id"])
        text = " ".join(
            str(value) for value in (row.get("judgement"), row.get("additional_judgement")) if value
        )
        if "모래" not in text:
            continue
        for horse_id, horse_name in entries.get(race_id, []):
            severity = sand_reaction_severity(text, horse_name)
            recovery = sand_recovery_observation(text, horse_name)
            if severity > 0:
                key = (race_id, horse_id)
                incidents[key] = max(incidents.get(key, 0.0), severity)
            if recovery > 0:
                key = (race_id, horse_id)
                recoveries[key] = max(recoveries.get(key, 0.0), recovery)
    return incidents, recoveries


def _reported_incidents(
    past: pl.DataFrame,
    reports: pl.DataFrame,
) -> dict[tuple[int, int], float]:
    """Compatibility helper for diagnostics that only need adverse events."""
    incidents, _ = _reported_events(past, reports)
    return incidents


def _history_rows(
    past: pl.DataFrame,
    sections: pl.DataFrame,
    incidents: dict[tuple[int, int], float],
    recoveries: dict[tuple[int, int], float],
) -> list[dict[str, object]]:
    required = {
        "race_id",
        "horse_id",
        "race_date",
        "starters",
        "gate_number",
        "finish_position",
    }
    if past.height == 0 or not required <= set(past.columns):
        return []
    s1f = pl.DataFrame()
    if sections.height and {"race_id", "horse_id", "section_code", "position"} <= set(
        sections.columns
    ):
        s1f = (
            sections.filter((pl.col("section_code") == "S1F") & pl.col("position").is_not_null())
            .group_by("race_id", "horse_id")
            .agg(pl.col("position").first().cast(pl.Float64).alias("s1f_position"))
        )
    rows = past.select(*sorted(required))
    if s1f.height:
        rows = rows.join(s1f, on=["race_id", "horse_id"], how="left")
    else:
        rows = rows.with_columns(pl.lit(None).cast(pl.Float64).alias("s1f_position"))
    output = []
    for row in rows.iter_rows(named=True):
        # Scheduled/live entries can be present in the source query as null-result
        # anchors.  They are not historical evidence and must not update state.
        if row.get("finish_position") is None or row.get("starters") is None:
            continue
        row["incident_severity"] = incidents.get(
            (int(row["race_id"]), int(row["horse_id"])), 0.0
        )
        row["recovery_observation"] = recoveries.get(
            (int(row["race_id"]), int(row["horse_id"])), 0.0
        )
        output.append(row)
    return output


def _decay(state: _SandState, current_date: date) -> None:
    if state.last_state_date is not None:
        days = max(0, (current_date - state.last_state_date).days)
        state.sensitivity *= 0.5 ** (days / _STATE_HALF_LIFE_DAYS)
    state.last_state_date = current_date
    cutoff = current_date - timedelta(days=_RECENT_DAYS)
    while state.incident_dates and state.incident_dates[0] < cutoff:
        state.incident_dates.popleft()


def _historical_exposure(row: dict[str, object]) -> float:
    starters = max(2, int(row["starters"]))
    s1f = row.get("s1f_position")
    early_pct = (float(s1f) - 1.0) / (starters - 1.0) if s1f is not None else 0.5
    gate_pct = float(row["gate_number"]) / starters
    field_density = min(1.0, max(0.0, (starters - 6.0) / 8.0))
    return min(1.0, max(0.0, early_pct * field_density * (1.1 - 0.3 * gate_pct)))


def _finish_percentile(row: dict[str, object]) -> float:
    starters = max(2, int(row["starters"]))
    return min(1.0, max(0.0, (float(row["finish_position"]) - 1.0) / (starters - 1.0)))


def _update_state(state: _SandState, row: dict[str, object], current_date: date) -> None:
    _decay(state, current_date)
    severity = float(row.get("incident_severity") or 0.0)
    explicit_recovery = float(row.get("recovery_observation") or 0.0)
    finish_pct = _finish_percentile(row)
    exposure = _historical_exposure(row)
    if severity > 0:
        event_weight = 0.35 + 0.45 * severity
        state.sensitivity = 1.0 - (1.0 - state.sensitivity) * (1.0 - event_weight)
        state.incident_count += 1
        state.incident_dates.append(current_date)
        state.last_incident = current_date
        state.last_evidence_date = current_date
        state.recovery_evidence = 0.0
    else:
        if state.incident_count > 0 and explicit_recovery > 0:
            state.recovery_evidence += 0.75 * explicit_recovery
            state.sensitivity *= math.exp(-0.50 * explicit_recovery)
            state.last_evidence_date = current_date
    if (
        severity <= 0
        and
        state.incident_count > 0
        and state.finish_ewma is not None
        and state.finish_observations >= 2
        and exposure >= 0.25
        and finish_pct <= state.finish_ewma + 0.05
    ):
        state.recovery_evidence += exposure
        state.sensitivity *= math.exp(-0.80 * exposure)
        state.last_evidence_date = current_date
    alpha = 0.25
    state.finish_ewma = (
        finish_pct
        if state.finish_ewma is None
        else alpha * finish_pct + (1.0 - alpha) * state.finish_ewma
    )
    state.finish_observations += 1


def _current_exposure(row: dict[str, object]) -> float:
    starters = max(2.0, float(row.get("starters") or 10.0))
    early_pct = float(row.get("early_pos_pct_avg5") or 0.5)
    gate_pct = float(row.get("horse_number_pct") or 0.5)
    field_density = min(1.0, max(0.0, (starters - 6.0) / 8.0))
    return min(1.0, max(0.0, early_pct * field_density * (1.1 - 0.3 * gate_pct)))


def _feature_row(
    race_entry_id: int,
    row: dict[str, object],
    state: _SandState,
    current_date: date,
) -> dict[str, object]:
    _decay(state, current_date)
    days_since = (
        (current_date - state.last_incident).days if state.last_incident is not None else None
    )
    recovery_score = (
        (state.recovery_evidence / (state.recovery_evidence + 2.0))
        * (1.0 - state.sensitivity)
        if state.incident_count > 0
        else 0.0
    )
    age_days = (
        (current_date - state.last_evidence_date).days
        if state.last_evidence_date is not None
        else 10_000
    )
    evidence = len(state.incident_dates) + state.recovery_evidence
    reliability = (evidence / (evidence + 3.0)) * math.exp(-age_days / 730.0)
    exposure = _current_exposure(row)
    return {
        "race_entry_id": race_entry_id,
        "sand_incident_count_prior": state.incident_count,
        "sand_incident_count_365d": len(state.incident_dates),
        "sand_days_since_incident": days_since,
        "sand_sensitivity_state": state.sensitivity,
        "sand_recovery_evidence": state.recovery_evidence,
        "sand_recovery_score": recovery_score,
        "sand_recovered_flag": int(
            state.incident_count > 0
            and state.recovery_evidence >= 1.5
            and state.sensitivity < 0.25
        ),
        "sand_exposure_risk": exposure,
        "sand_expected_penalty": state.sensitivity * exposure * reliability,
        "sand_state_reliability": reliability,
    }


def _empty(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(0).cast(pl.Int64).alias("sand_incident_count_prior"),
        pl.lit(0).cast(pl.Int64).alias("sand_incident_count_365d"),
        pl.lit(None).cast(pl.Int64).alias("sand_days_since_incident"),
        pl.lit(0.0).alias("sand_sensitivity_state"),
        pl.lit(0.0).alias("sand_recovery_evidence"),
        pl.lit(0.0).alias("sand_recovery_score"),
        pl.lit(0).cast(pl.Int8).alias("sand_recovered_flag"),
        pl.lit(0.0).alias("sand_exposure_risk"),
        pl.lit(0.0).alias("sand_expected_penalty"),
        pl.lit(0.0).alias("sand_state_reliability"),
    )


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    past = as_date(sources.past_results, "race_date")
    sections = as_date(sources.sections, "race_date")
    reports = as_date(sources.steward_reports, "race_date")
    incidents, recoveries = _reported_events(past, reports)
    history = _history_rows(past, sections, incidents, recoveries)
    required_target = {"race_entry_id", "horse_id", "race_date", "starters"}
    if not history or not required_target <= set(frame.columns):
        return _empty(frame)

    history_by_day: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in history:
        history_by_day[row["race_date"]].append(row)  # type: ignore[index]
    target_by_day: dict[date, list[dict[str, object]]] = defaultdict(list)
    target_columns = [
        "race_entry_id",
        "horse_id",
        "race_date",
        "starters",
        *(name for name in ("early_pos_pct_avg5", "horse_number_pct") if name in frame.columns),
    ]
    for row in frame.select(*target_columns).iter_rows(named=True):
        target_by_day[row["race_date"]].append(row)  # type: ignore[index]

    states: dict[int, _SandState] = defaultdict(_SandState)
    output: list[dict[str, object]] = []
    for current_date in sorted(set(history_by_day) | set(target_by_day)):
        for row in target_by_day.get(current_date, []):
            horse_id = int(row["horse_id"])
            output.append(
                _feature_row(
                    int(row["race_entry_id"]),
                    row,
                    states[horse_id],
                    current_date,
                )
            )
        for row in history_by_day.get(current_date, []):
            _update_state(states[int(row["horse_id"])], row, current_date)

    if not output:
        return _empty(frame)
    features = pl.DataFrame(output, infer_schema_length=None).with_columns(
        pl.col("sand_incident_count_prior").cast(pl.Int64),
        pl.col("sand_incident_count_365d").cast(pl.Int64),
        pl.col("sand_days_since_incident").cast(pl.Int64),
        pl.col("sand_recovered_flag").cast(pl.Int8),
    )
    return frame.join(features, on="race_entry_id", how="left")
