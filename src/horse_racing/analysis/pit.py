"""Point-in-time(PIT) join 공통 유틸.

모든 feature는 예측 시점(`prediction_at`) 이전에 관측된 값만 사용해야 한다.
이 모듈은 이력 테이블을 "as-of 마지막 관측"으로 결합하는 공통 함수와,
수집 시점 스냅샷 테이블(과거 JOIN 시 누수)을 코드 레벨에서 차단하는
화이트리스트를 제공한다.
"""

from __future__ import annotations

import polars as pl

# 이벤트 발생 시점이 행에 기록되어 있어 PIT join이 허용되는 원천.
# 값은 join 기준으로 사용할 시각 컬럼 이름이다 (UTC epoch ms 또는 date).
PIT_ALLOWED_SOURCES: dict[str, str] = {
    "horse_weight_history": "observed_at_ms",
    "horse_training": "training_date_local",
    "horse_medical": "clinic_date_local",
    "horse_start_training": "training_date_local",
    "entry_equipment": "race_date_local",
    "horse_grade_changes": "start_date_local",
    "jockey_changes": "observed_at_ms",
    "race_scratches": "observed_at_ms",
    "odds_snapshots": "observed_at_ms",
    # 과거 경주의 결과·구간은 해당 경주 종료 후 공개되므로,
    # "이전 경주의 결과"로만 join해야 한다 (경주일 < 예측 대상 경주일).
    "race_results": "race_date_local",
    "race_section_results": "race_date_local",
}

# 수집 시점 스냅샷이라 과거 시점으로 JOIN하면 미래 정보가 새는 원천.
PIT_FORBIDDEN_SOURCES: dict[str, str] = {
    "horse_profile_snapshots": "수집 시점의 통산·올해 성적 스냅샷 — 과거 경주 feature로 사용 금지",
    "horse_rating_snapshots": "수집 시점 레이팅 스냅샷 — 백필 불가 기간이 있어 과거 JOIN 금지",
    "horses": "프로필 컬럼(등급·최근 거래가 등)이 최신 수집값이라 과거 JOIN 금지",
}


class ForbiddenSnapshotJoinError(ValueError):
    """화이트리스트에 없는 원천을 PIT join에 사용하려 할 때 발생."""


class FutureObservationError(ValueError):
    """예측 시점 이후의 관측이 데이터셋에 섞였을 때 발생."""


def ensure_pit_allowed(source_table: str) -> str:
    """원천 테이블이 PIT join 허용 목록에 있는지 검사하고 시각 컬럼을 반환한다."""
    if source_table in PIT_FORBIDDEN_SOURCES:
        raise ForbiddenSnapshotJoinError(
            f"'{source_table}'은 수집 시점 스냅샷이라 PIT join이 금지됩니다: "
            f"{PIT_FORBIDDEN_SOURCES[source_table]}"
        )
    if source_table not in PIT_ALLOWED_SOURCES:
        raise ForbiddenSnapshotJoinError(
            f"'{source_table}'은 PIT 허용 목록에 없습니다. "
            "공개 시점을 검토한 뒤 pit.PIT_ALLOWED_SOURCES에 명시적으로 등록하세요."
        )
    return PIT_ALLOWED_SOURCES[source_table]


def point_in_time_join(
    base: pl.DataFrame,
    history: pl.DataFrame,
    *,
    source_table: str,
    by: str | list[str],
    base_time_col: str,
    history_time_col: str | None = None,
    suffix: str = "_hist",
) -> pl.DataFrame:
    """base의 각 행에 대해 `history_time_col <= base_time_col`인 마지막 관측을 결합한다.

    `source_table`은 반드시 PIT_ALLOWED_SOURCES에 등록되어 있어야 한다.
    결합 후 미래 관측이 없음을 한 번 더 검증한다.
    """
    default_time_col = ensure_pit_allowed(source_table)
    time_col = history_time_col or default_time_col
    by_cols = [by] if isinstance(by, str) else list(by)

    if time_col not in history.columns:
        raise ValueError(f"history에 시각 컬럼 '{time_col}'이 없습니다.")
    if base_time_col not in base.columns:
        raise ValueError(f"base에 시각 컬럼 '{base_time_col}'이 없습니다.")

    base_sorted = base.sort(base_time_col)
    history_sorted = history.drop_nulls(time_col).sort(time_col)

    joined = base_sorted.join_asof(
        history_sorted,
        left_on=base_time_col,
        right_on=time_col,
        by=by_cols,
        strategy="backward",
        suffix=suffix,
    )

    joined_time_col = time_col if time_col != base_time_col else f"{time_col}{suffix}"
    if joined_time_col in joined.columns:
        assert_point_in_time(joined, observed_col=joined_time_col, as_of_col=base_time_col)
    return joined


def assert_point_in_time(
    frame: pl.DataFrame,
    *,
    observed_col: str,
    as_of_col: str,
) -> None:
    """관측 시각이 예측 시점을 넘는 행이 있으면 FutureObservationError를 던진다."""
    violations = frame.filter(
        pl.col(observed_col).is_not_null() & (pl.col(observed_col) > pl.col(as_of_col))
    )
    if violations.height > 0:
        raise FutureObservationError(
            f"미래 관측 {violations.height}행 발견: "
            f"'{observed_col}' > '{as_of_col}'. 예측 시점 이후 데이터가 섞였습니다."
        )
