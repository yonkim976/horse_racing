"""학습 데이터셋(v1) 빌더.

정규화 DB에서 "경주 × 출전마" 행을 뽑아 라벨 정책과 예측 시점을 적용하고,
버전이 고정된 Parquet + manifest로 저장한다. 라벨 정책과 제외 규칙은
docs/MODELING_ROADMAP.md §2를 따른다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from horse_racing.analysis.experiments import current_git_commit, hash_feature_names, now_ms

KST = ZoneInfo("Asia/Seoul")

AS_OF_POLICIES = ("start_minus_30m", "day_before_18")

SPECIAL_FINISH_CODE_MIN = 90
MIN_STARTERS = 5

# v1 데이터셋의 통과(pass-through) 컬럼별 공개 시점 가정.
# 시각 단위 observed_at이 없는 컬럼은 이 가정을 manifest에 기록해 감사 가능하게 한다.
FIELD_PUBLICATION_ASSUMPTIONS: dict[str, str] = {
    "distance_m,grade_raw,burden_type,age_condition,sex_condition": "경주계획 공개(전일 이전)",
    "horse_number,gate_number,carried_weight_kg,rating,jockey_id,trainer_id": (
        "출전표 공개(전일 이전)"
    ),
    "weather_planned,track_condition_planned,track_moisture_percent_planned": (
        "경주계획 API 원본 재파싱 값(경주 전 관측 우선)"
    ),
    "body_weight_kg,body_weight_change_kg": (
        "경주 당일 계량 후 공개 — start_minus_30m에서만 사용 가능, "
        "day_before_18 정책에서는 자동 제외"
    ),
}

# 경주 당일에야 공개되는 컬럼: day_before_18 정책에서는 제거한다.
RACE_DAY_ONLY_COLUMNS = ("body_weight_kg", "body_weight_change_kg")

LABEL_COLUMNS = ("win", "top2", "top3")
AUXILIARY_TARGET_COLUMNS = ("finish_time_ms", "margin_text")


class DatasetValidationError(ValueError):
    """데이터셋 무결성 검증 실패."""


@dataclass
class ExclusionStats:
    scratched: int = 0
    special_finish_code: int = 0
    missing_finish_position: int = 0
    missing_result_row: int = 0
    small_field_races: int = 0
    small_field_rows: int = 0
    no_winner_races: int = 0
    no_winner_rows: int = 0
    missing_schedule_races: int = 0
    missing_schedule_rows: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class BuildResult:
    frame: pl.DataFrame
    manifest: dict[str, Any]
    dataset_path: Path | None = None
    manifest_path: Path | None = None
    exclusions: ExclusionStats = field(default_factory=ExclusionStats)


_BASE_QUERY = """
SELECT
    r.id AS race_id,
    e.id AS race_entry_id,
    rc.kra_meet_code AS meet_code,
    r.race_date_local AS race_date_local,
    r.race_number AS race_number,
    r.distance_m AS distance_m,
    r.grade AS grade_raw,
    r.burden_type AS burden_type,
    r.age_condition AS age_condition,
    r.sex_condition AS sex_condition,
    r.scheduled_at_ms AS scheduled_at_ms,
    r.weather_planned AS weather_planned,
    r.track_condition_planned AS track_condition_planned,
    r.track_moisture_percent_planned AS track_moisture_percent_planned,
    e.horse_id AS horse_id,
    e.jockey_id AS jockey_id,
    e.trainer_id AS trainer_id,
    e.horse_number AS horse_number,
    e.gate_number AS gate_number,
    e.carried_weight_kg AS carried_weight_kg,
    e.body_weight_kg AS body_weight_kg,
    e.body_weight_change_kg AS body_weight_change_kg,
    e.rating AS rating,
    e.scratched AS scratched,
    res.finish_position AS finish_position,
    res.finish_time_ms AS finish_time_ms,
    res.margin_text AS margin_text,
    res.id AS result_id
FROM race_entries AS e
JOIN races AS r ON r.id = e.race_id
JOIN racecourses AS rc ON rc.id = r.racecourse_id
LEFT JOIN race_results AS res ON res.race_entry_id = e.id
WHERE r.status = 'completed'
"""


def fetch_base_rows(
    session: Session,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pl.DataFrame:
    """완료 경주의 출전 행을 DB에서 읽어 polars DataFrame으로 반환한다."""
    query = _BASE_QUERY
    params: dict[str, str] = {}
    if start_date:
        query += " AND r.race_date_local >= :start_date"
        params["start_date"] = start_date
    if end_date:
        query += " AND r.race_date_local <= :end_date"
        params["end_date"] = end_date

    rows = session.execute(text(query), params).mappings().all()
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame([dict(row) for row in rows], infer_schema_length=None)


def compute_prediction_at(frame: pl.DataFrame, policy: str) -> pl.DataFrame:
    """as-of 정책에 따라 prediction_at_ms 컬럼을 추가한다."""
    if policy == "start_minus_30m":
        return frame.with_columns(
            (pl.col("scheduled_at_ms") - 30 * 60 * 1000).alias("prediction_at_ms")
        )
    if policy == "day_before_18":

        def _day_before_18(race_date: str | None) -> int | None:
            if race_date is None:
                return None
            day = datetime.strptime(str(race_date), "%Y-%m-%d").replace(tzinfo=KST)
            moment = (day - timedelta(days=1)).replace(hour=18, minute=0, second=0)
            return int(moment.timestamp() * 1000)

        return frame.with_columns(
            pl.col("race_date_local")
            .cast(pl.Utf8)
            .map_elements(_day_before_18, return_dtype=pl.Int64)
            .alias("prediction_at_ms")
        )
    raise ValueError(f"알 수 없는 as-of 정책: {policy}. 지원: {AS_OF_POLICIES}")


def apply_label_policy(frame: pl.DataFrame) -> tuple[pl.DataFrame, ExclusionStats]:
    """라벨 정책(MODELING_ROADMAP §2.2)을 적용해 학습 대상 행과 제외 통계를 반환한다."""
    stats = ExclusionStats()

    scratched = pl.col("scratched") == True  # noqa: E712 (SQLite 0/1 boolean)
    special = pl.col("finish_position") >= SPECIAL_FINISH_CODE_MIN
    no_result = pl.col("result_id").is_null()
    null_position = pl.col("result_id").is_not_null() & pl.col("finish_position").is_null()

    stats.scratched = frame.filter(scratched).height
    remaining = frame.filter(~scratched)
    stats.special_finish_code = remaining.filter(special.fill_null(False)).height
    remaining = remaining.filter(~special.fill_null(False))
    stats.missing_result_row = remaining.filter(no_result).height
    remaining = remaining.filter(~no_result)
    stats.missing_finish_position = remaining.filter(null_position).height
    remaining = remaining.filter(pl.col("finish_position").is_not_null())

    # 출주 두수(정상 완주 기준)와 경주 단위 필터
    remaining = remaining.with_columns(
        pl.len().over("race_id").alias("starters"),
        (pl.col("finish_position") == 1).sum().over("race_id").alias("_winner_count"),
    )

    small_field = remaining.filter(pl.col("starters") < MIN_STARTERS)
    stats.small_field_rows = small_field.height
    stats.small_field_races = small_field.select("race_id").n_unique()
    remaining = remaining.filter(pl.col("starters") >= MIN_STARTERS)

    no_winner = remaining.filter(pl.col("_winner_count") == 0)
    stats.no_winner_rows = no_winner.height
    stats.no_winner_races = no_winner.select("race_id").n_unique()
    remaining = remaining.filter(pl.col("_winner_count") > 0).drop("_winner_count")

    labeled = remaining.with_columns(
        (pl.col("finish_position") == 1).cast(pl.Int8).alias("win"),
        (pl.col("finish_position") <= 2).cast(pl.Int8).alias("top2"),
        (pl.col("finish_position") <= 3).cast(pl.Int8).alias("top3"),
    )
    return labeled, stats


def validate_dataset(frame: pl.DataFrame, *, as_of_policy: str = "start_minus_30m") -> None:
    """데이터셋 무결성을 검증한다. 실패 시 DatasetValidationError."""
    if frame.height == 0:
        raise DatasetValidationError("데이터셋이 비어 있습니다.")

    required = ["prediction_at_ms", *LABEL_COLUMNS]
    if as_of_policy == "start_minus_30m":
        required.append("scheduled_at_ms")
    for column in required:
        if column not in frame.columns:
            raise DatasetValidationError(f"필수 컬럼 누락: {column}")
        nulls = frame.filter(pl.col(column).is_null()).height
        if nulls:
            raise DatasetValidationError(f"'{column}'에 null {nulls}행이 있습니다.")

    not_before_start = frame.filter(
        pl.col("scheduled_at_ms").is_not_null()
        & (pl.col("prediction_at_ms") >= pl.col("scheduled_at_ms"))
    ).height
    if not_before_start:
        raise DatasetValidationError(
            f"prediction_at이 출발시각 이후인 행 {not_before_start}건이 있습니다."
        )

    race_checks = frame.group_by("race_id").agg(
        pl.col("win").sum().alias("winners"),
        pl.len().alias("rows"),
    )
    zero_winner = race_checks.filter(pl.col("winners") == 0).height
    if zero_winner:
        raise DatasetValidationError(f"1착 없는 경주 {zero_winner}건이 남아 있습니다.")
    small = race_checks.filter(pl.col("rows") < MIN_STARTERS).height
    if small:
        raise DatasetValidationError(f"두수 {MIN_STARTERS} 미만 경주 {small}건이 남아 있습니다.")


def compute_auc(scores: list[float], labels: list[int]) -> float | None:
    """rank 기반(Mann-Whitney) AUC. 외부 의존성 없이 계산한다."""
    pairs = [
        (score, label) for score, label in zip(scores, labels, strict=True) if score is not None
    ]
    positives = sum(1 for _, label in pairs if label == 1)
    negatives = len(pairs) - positives
    if positives == 0 or negatives == 0:
        return None

    ranked = sorted(pairs, key=lambda item: item[0])
    rank_sum = 0.0
    index = 0
    while index < len(ranked):
        tie_end = index
        while tie_end + 1 < len(ranked) and ranked[tie_end + 1][0] == ranked[index][0]:
            tie_end += 1
        average_rank = (index + tie_end) / 2 + 1
        for position in range(index, tie_end + 1):
            if ranked[position][1] == 1:
                rank_sum += average_rank
        index = tie_end + 1

    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def leakage_canary(
    frame: pl.DataFrame,
    feature_columns: list[str],
    *,
    label_column: str = "win",
    auc_threshold: float = 0.95,
) -> dict[str, float]:
    """단일 feature AUC가 비정상적으로 높은 컬럼을 찾아낸다.

    미래 정보(착순, 확정배당 등)가 feature에 섞이면 단독 AUC가 1에 가까워진다.
    반환값: {의심 컬럼: AUC}. 파이프라인의 누수 탐지 능력을 시험하는 데 쓴다.
    """
    labels = frame.get_column(label_column).cast(pl.Int64).to_list()
    flagged: dict[str, float] = {}
    for column in feature_columns:
        values = frame.get_column(column).cast(pl.Float64, strict=False).to_list()
        auc = compute_auc(values, labels)
        if auc is None:
            continue
        oriented = max(auc, 1 - auc)
        if oriented >= auc_threshold:
            flagged[column] = oriented
    return flagged


def build_dataset(
    session: Session,
    *,
    version: str,
    as_of_policy: str = "start_minus_30m",
    start_date: str | None = None,
    end_date: str | None = None,
    output_dir: Path | None = None,
    with_features: bool = True,
    feature_set: str = "rich",
) -> BuildResult:
    """데이터셋을 생성하고 Parquet + manifest를 기록한다."""
    if as_of_policy not in AS_OF_POLICIES:
        raise ValueError(f"알 수 없는 as-of 정책: {as_of_policy}. 지원: {AS_OF_POLICIES}")

    base = fetch_base_rows(session, start_date=start_date, end_date=end_date)
    if base.height == 0:
        raise DatasetValidationError("조건에 맞는 완료 경주가 없습니다.")

    total_rows = base.height
    labeled, stats = apply_label_policy(base)
    if as_of_policy == "start_minus_30m":
        missing_schedule = labeled.filter(pl.col("scheduled_at_ms").is_null())
        stats.missing_schedule_rows = missing_schedule.height
        stats.missing_schedule_races = missing_schedule.select("race_id").n_unique()
        labeled = labeled.filter(pl.col("scheduled_at_ms").is_not_null())
    frame = compute_prediction_at(labeled, as_of_policy)

    if as_of_policy == "day_before_18":
        frame = frame.drop([col for col in RACE_DAY_ONLY_COLUMNS if col in frame.columns])

    frame = frame.drop([col for col in ("scratched", "result_id") if col in frame.columns])

    dataset_feature_names: list[str] = []
    if with_features:
        from horse_racing.analysis.features import (
            apply_features,
            feature_names,
            load_source_frames,
        )

        sources = load_source_frames(session)
        frame = apply_features(frame, sources, feature_set=feature_set)
        from horse_racing.analysis.features.style import attach_early_position_target

        frame = attach_early_position_target(frame, sources)
        dataset_feature_names = feature_names(frame, feature_set=feature_set)

    frame = frame.sort(["race_date_local", "meet_code", "race_number", "horse_number"])
    validate_dataset(frame, as_of_policy=as_of_policy)

    date_range = frame.select(
        pl.col("race_date_local").cast(pl.Utf8).min().alias("min"),
        pl.col("race_date_local").cast(pl.Utf8).max().alias("max"),
    ).row(0)

    manifest: dict[str, Any] = {
        "version": version,
        "as_of_policy": as_of_policy,
        "created_at_ms": now_ms(),
        "git_commit": current_git_commit(),
        "row_count": frame.height,
        "race_count": frame.select("race_id").n_unique(),
        "source_row_count": total_rows,
        "date_range": {"start": date_range[0], "end": date_range[1]},
        "requested_range": {"start": start_date, "end": end_date},
        "exclusions": stats.as_dict(),
        "label_stats": {label: float(frame.get_column(label).mean()) for label in LABEL_COLUMNS},
        "auxiliary_target_coverage": {
            "early_position_pct_target": (
                float(frame["early_position_pct_target"].is_not_null().mean())
                if "early_position_pct_target" in frame.columns
                else 0.0
            ),
            **{
                column: float(frame[column].is_not_null().mean())
                for column in AUXILIARY_TARGET_COLUMNS
                if column in frame.columns
            },
        },
        "columns": {name: str(dtype) for name, dtype in frame.schema.items()},
        "feature_names": dataset_feature_names,
        "feature_hash": hash_feature_names(dataset_feature_names),
        "feature_set": feature_set if with_features else None,
        "field_publication_assumptions": FIELD_PUBLICATION_ASSUMPTIONS,
    }

    dataset_path: Path | None = None
    manifest_path: Path | None = None
    if output_dir is not None:
        target_dir = Path(output_dir) / version / as_of_policy
        target_dir.mkdir(parents=True, exist_ok=True)
        dataset_path = target_dir / "dataset.parquet"
        manifest_path = target_dir / "manifest.json"
        frame.write_parquet(dataset_path)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return BuildResult(
        frame=frame,
        manifest=manifest,
        dataset_path=dataset_path,
        manifest_path=manifest_path,
        exclusions=stats,
    )
