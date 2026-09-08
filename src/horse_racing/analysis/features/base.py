"""Feature 프레임워크 공통 요소.

- FeatureSpec: 각 feature의 원천·정의·누수 위험을 기록하는 명세 (카탈로그 자동 생성용)
- SourceFrames: feature 계산에 쓰는 원천 DataFrame 묶음 (DB에서 1회 로드)
- 롤링 윈도우·과거 이력 유틸: 모든 계산은 예측 대상 경주일 **이전** 데이터만 사용
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol

import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class FeatureSpec:
    """FEATURE_CATALOG.md 자동 생성에 쓰이는 feature 명세."""

    name: str
    group: str
    description: str
    source: str
    lookback: str = "-"
    null_policy: str = "null 유지"
    leakage_note: str = "low"


class FeatureModule(Protocol):
    GROUP: str
    FEATURES: list[FeatureSpec]

    def add_features(self, frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame: ...


@dataclass
class SourceFrames:
    """feature 계산 원천. 모든 frame의 race_date 계열 컬럼은 pl.Date로 정규화한다."""

    past_results: pl.DataFrame = field(default_factory=pl.DataFrame)
    sections: pl.DataFrame = field(default_factory=pl.DataFrame)
    training: pl.DataFrame = field(default_factory=pl.DataFrame)
    start_training: pl.DataFrame = field(default_factory=pl.DataFrame)
    medical: pl.DataFrame = field(default_factory=pl.DataFrame)
    equipment: pl.DataFrame = field(default_factory=pl.DataFrame)
    jockey_changes: pl.DataFrame = field(default_factory=pl.DataFrame)
    running_trials: pl.DataFrame = field(default_factory=pl.DataFrame)
    steward_reports: pl.DataFrame = field(default_factory=pl.DataFrame)
    horse_static: pl.DataFrame = field(default_factory=pl.DataFrame)


def as_date(frame: pl.DataFrame, *columns: str) -> pl.DataFrame:
    """SQLite에서 문자열로 온 날짜 컬럼을 pl.Date로 캐스팅한다."""
    exprs = []
    for column in columns:
        if column in frame.columns and frame.schema[column] != pl.Date:
            exprs.append(pl.col(column).cast(pl.Utf8).str.strptime(pl.Date, "%Y-%m-%d"))
    return frame.with_columns(exprs) if exprs else frame


_PAST_RESULTS_QUERY = """
SELECT
    e.horse_id AS horse_id,
    e.jockey_id AS jockey_id,
    e.trainer_id AS trainer_id,
    e.id AS race_entry_id,
    r.id AS race_id,
    rc.kra_meet_code AS meet_code,
    r.race_date_local AS race_date,
    r.race_number AS race_number,
    r.scheduled_at_ms AS scheduled_at_ms,
    r.distance_m AS distance_m,
    r.track_condition AS track_condition,
    r.track_moisture_percent AS track_moisture_percent,
    COALESCE(e.gate_number, e.horse_number) AS gate_number,
    e.horse_number AS program_number,
    h.name_ko AS horse_name,
    e.body_weight_kg AS body_weight_kg,
    res.finish_position AS finish_position,
    res.finish_time_ms AS finish_time_ms
FROM race_entries AS e
JOIN races AS r ON r.id = e.race_id
JOIN racecourses AS rc ON rc.id = r.racecourse_id
JOIN horses AS h ON h.id = e.horse_id
JOIN race_results AS res ON res.race_entry_id = e.id
WHERE r.status = 'completed'
  AND res.finish_position BETWEEN 1 AND 89
"""

_SECTIONS_QUERY = """
SELECT
    e.horse_id AS horse_id,
    r.id AS race_id,
    r.race_date_local AS race_date,
    s.section_code AS section_code,
    s.position AS position,
    s.elapsed_time_ms AS elapsed_time_ms
FROM race_section_results AS s
JOIN race_entries AS e ON e.id = s.race_entry_id
JOIN races AS r ON r.id = e.race_id
WHERE r.status = 'completed'
"""

_TRAINING_QUERY = """
SELECT ht.horse_id, ht.training_date_local AS event_date, ht.duration_seconds,
       ht.canter_count, ht.gallop_count, ht.rider_type, ht.rider_id,
       j.id AS rider_jockey_id
FROM horse_training AS ht
LEFT JOIN jockeys AS j ON j.kra_jockey_id = ht.rider_id
"""

_START_TRAINING_QUERY = """
SELECT horse_id, training_date_local AS event_date
FROM horse_start_training
"""

_MEDICAL_QUERY = """
SELECT horse_id, clinic_date_local AS event_date, diagnosis_1
FROM horse_medical
"""

_EQUIPMENT_QUERY = """
SELECT horse_id, race_date_local AS race_date, race_number,
       equipment_raw, bleeding_count, bleeding_date_raw
FROM entry_equipment
WHERE horse_id IS NOT NULL
"""

_JOCKEY_CHANGES_QUERY = """
SELECT horse_id, race_date_local AS race_date, race_number
FROM jockey_changes
WHERE horse_id IS NOT NULL
"""

_RUNNING_TRIALS_QUERY = """
SELECT
    rr.horse_id AS horse_id,
    rr.jockey_id AS jockey_id,
    rt.id AS trial_id,
    rt.trial_date_local AS event_date,
    rt.trial_race_number AS trial_race_number,
    rt.distance_m AS distance_m,
    COUNT(*) OVER (PARTITION BY rr.running_trial_id) AS field_size,
    rr.finish_position AS finish_position,
    rr.finish_time_ms AS finish_time_ms,
    rr.body_weight_kg AS body_weight_kg,
    rr.judgement AS judgement,
    rr.inspection_reason AS inspection_reason,
    rr.g3f_ms AS g3f_ms,
    rr.s1f_ms AS s1f_ms,
    rr.g1f_ms AS g1f_ms
FROM running_trial_results AS rr
JOIN running_trials AS rt ON rt.id = rr.running_trial_id
WHERE rr.horse_id IS NOT NULL
"""

_HORSE_STATIC_QUERY = """
SELECT id AS horse_id, birth_date, sex, origin_country
FROM horses
"""

_STEWARD_REPORTS_QUERY = """
SELECT
    r.id AS race_id,
    sr.race_date_local AS race_date,
    sr.meet_code AS meet_code,
    sr.race_number AS race_number,
    sr.judgement AS judgement,
    sr.additional_judgement AS additional_judgement
FROM race_steward_reports AS sr
JOIN racecourses AS rc ON rc.kra_meet_code = sr.meet_code
JOIN races AS r
  ON r.racecourse_id = rc.id
 AND r.race_date_local = sr.race_date_local
 AND r.race_number = sr.race_number
"""


def _fetch(session: Session, query: str, date_columns: tuple[str, ...]) -> pl.DataFrame:
    rows = session.execute(text(query)).mappings().all()
    if not rows:
        return pl.DataFrame()
    frame = pl.DataFrame([dict(row) for row in rows], infer_schema_length=None)
    return as_date(frame, *date_columns)


def load_source_frames(session: Session) -> SourceFrames:
    """feature 계산에 필요한 원천을 DB에서 한 번에 읽는다.

    past_results는 정상 착순(1~89)만 포함하며, 경주별 출주 두수(starters)를 붙인다.
    horse_static은 불변 속성(생년월일·산지)만 사용한다. sex는 현재 스냅샷 값이라
    거세 전 경주에 소급 적용될 수 있다(카탈로그에 누수 위험 med로 기록).
    """
    past = _fetch(session, _PAST_RESULTS_QUERY, ("race_date",))
    if past.height > 0:
        past = past.with_columns(pl.len().over("race_id").alias("starters"))
    return SourceFrames(
        past_results=past,
        sections=_fetch(session, _SECTIONS_QUERY, ("race_date",)),
        training=_fetch(session, _TRAINING_QUERY, ("event_date",)),
        start_training=_fetch(session, _START_TRAINING_QUERY, ("event_date",)),
        medical=_fetch(session, _MEDICAL_QUERY, ("event_date",)),
        equipment=_fetch(session, _EQUIPMENT_QUERY, ("race_date",)),
        jockey_changes=_fetch(session, _JOCKEY_CHANGES_QUERY, ("race_date",)),
        running_trials=_fetch(session, _RUNNING_TRIALS_QUERY, ("event_date",)),
        steward_reports=_fetch(session, _STEWARD_REPORTS_QUERY, ("race_date",)),
        horse_static=_fetch(session, _HORSE_STATIC_QUERY, ("birth_date",)),
    )


def rolling_event_counts(
    base: pl.DataFrame,
    events: pl.DataFrame,
    *,
    key: str,
    base_date_col: str,
    event_date_col: str = "event_date",
    windows_days: tuple[int, ...],
    prefix: str,
    value_columns: dict[str, str] | None = None,
) -> pl.DataFrame:
    """base 각 행에 대해 `event_date < base_date`인 이벤트의 윈도우 집계를 붙인다.

    당일(event_date == base_date) 이벤트는 공개 시점이 불확실하므로 **제외**한다
    (보수적 규칙, MODELING_ROADMAP §4 F그룹). 반환 컬럼:
    `{prefix}_n_{w}d` (건수), value_columns 지정 시 `{prefix}_{alias}_{w}d` (합).
    """
    if events.height == 0:
        exprs = []
        for window in windows_days:
            exprs.append(pl.lit(0).cast(pl.Int64).alias(f"{prefix}_n_{window}d"))
            for alias in (value_columns or {}).values():
                exprs.append(pl.lit(None).cast(pl.Float64).alias(f"{prefix}_{alias}_{window}d"))
        return base.with_columns(exprs)

    def normalize_day(value: object) -> date | None:
        if value is None:
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    source_columns = list((value_columns or {}).keys())
    selected = events.select(key, event_date_col, *source_columns)
    histories: dict[object, list[tuple[date, list[float]]]] = {}
    for row in selected.iter_rows(named=True):
        entity = row[key]
        event_day = normalize_day(row[event_date_col])
        if entity is None or event_day is None:
            continue
        values = [0.0 if row[column] is None else float(row[column]) for column in source_columns]
        histories.setdefault(entity, []).append((event_day, values))

    indexed: dict[object, tuple[list[date], list[list[float]]]] = {}
    for entity, rows in histories.items():
        rows.sort(key=lambda item: item[0])
        days = [item[0] for item in rows]
        cumulative = [[0.0] for _ in source_columns]
        for _, values in rows:
            for index, value in enumerate(values):
                cumulative[index].append(cumulative[index][-1] + value)
        indexed[entity] = days, cumulative

    counts = {window: [0] * base.height for window in windows_days}
    sums: dict[tuple[int, str], list[float | None]] = {
        (window, alias): [None] * base.height
        for window in windows_days
        for alias in (value_columns or {}).values()
    }
    base_rows = base.select(key, base_date_col).iter_rows(named=True)
    for row_index, row in enumerate(base_rows):
        entity = row[key]
        base_day = normalize_day(row[base_date_col])
        history = indexed.get(entity)
        if entity is None or base_day is None or history is None:
            continue
        days, cumulative = history
        high = bisect_left(days, base_day)  # 같은 날은 보수적으로 제외
        for window in windows_days:
            low = bisect_left(days, base_day - timedelta(days=window))
            counts[window][row_index] = high - low
            for source_index, alias in enumerate((value_columns or {}).values()):
                sums[(window, alias)][row_index] = (
                    cumulative[source_index][high] - cumulative[source_index][low]
                )

    columns: list[pl.Series] = []
    for window in windows_days:
        columns.append(pl.Series(f"{prefix}_n_{window}d", counts[window], dtype=pl.Int64))
        for alias in (value_columns or {}).values():
            columns.append(
                pl.Series(
                    f"{prefix}_{alias}_{window}d",
                    sums[(window, alias)],
                    dtype=pl.Float64,
                )
            )
    return base.with_columns(columns)


def days_since_last_event(
    base: pl.DataFrame,
    events: pl.DataFrame,
    *,
    key: str,
    base_date_col: str,
    event_date_col: str = "event_date",
    alias: str,
) -> pl.DataFrame:
    """base 각 행에 대해 마지막 이벤트(엄격히 이전 날짜) 이후 경과일을 붙인다."""
    if events.height == 0:
        return base.with_columns(pl.lit(None).cast(pl.Int64).alias(alias))

    joined = base.select(key, base_date_col).unique().join(events, on=key, how="inner")
    joined = joined.filter(pl.col(event_date_col) < pl.col(base_date_col))
    last = joined.group_by(key, base_date_col).agg(
        pl.col(event_date_col).max().alias("_last_event")
    )
    result = base.join(last, on=[key, base_date_col], how="left")
    return result.with_columns(
        (pl.col(base_date_col) - pl.col("_last_event")).dt.total_days().alias(alias)
    ).drop("_last_event")
