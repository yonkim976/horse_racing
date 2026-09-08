"""Build label-free feature frames for scheduled-race inference.

The training feature pipeline expects the current race to be present at the end
of each horse's history and uses ``shift(1)`` to exclude its result.  Scheduled
races do not have a result row, so this module appends a null-result anchor for
every target entry.  That preserves the training-time calculation without
inventing labels or allowing same-day results into the frame.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

import numpy as np
import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from horse_racing.analysis.dataset import (
    AS_OF_POLICIES,
    LABEL_COLUMNS,
    MIN_STARTERS,
    RACE_DAY_ONLY_COLUMNS,
    compute_prediction_at,
)
from horse_racing.analysis.experiments import ModelRun, hash_feature_names
from horse_racing.analysis.features import (
    FEATURE_SETS,
    all_feature_specs,
    apply_features,
    feature_names,
    load_source_frames,
)


class PredictionFrameError(ValueError):
    """Raised when a trustworthy inference frame cannot be built."""


PROBABILITY_COHERENCE_METHOD = "dykstra_l2_v1"


@dataclass(frozen=True, slots=True)
class PredictionFrameResult:
    frame: pl.DataFrame
    race_date_local: str
    as_of_policy: str
    feature_names: list[str]
    feature_hash: str
    excluded_small_field_race_ids: list[int]


_PREDICTION_BASE_QUERY = """
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
    e.rating AS rating
FROM race_entries AS e
JOIN races AS r ON r.id = e.race_id
JOIN racecourses AS rc ON rc.id = r.racecourse_id
WHERE r.race_date_local = :race_date
  AND e.scratched = 0
"""


def normalize_race_date(value: str | date) -> str:
    if isinstance(value, date):
        return value.isoformat()
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    raise PredictionFrameError("경주일은 YYYYMMDD 또는 YYYY-MM-DD 형식이어야 합니다.")


def fetch_prediction_base_rows(
    session: Session,
    *,
    race_date: str | date,
    publication_mode: str = "live",
    race_ids: list[int] | None = None,
) -> pl.DataFrame:
    """Read non-scratched entries without joining results or labels."""
    if publication_mode not in {"live", "historical"}:
        raise PredictionFrameError("publication_mode은 live 또는 historical이어야 합니다.")
    race_date_iso = normalize_race_date(race_date)
    query = _PREDICTION_BASE_QUERY
    if publication_mode == "live":
        query += " AND r.status = 'scheduled'"
    else:
        query += " AND r.status IN ('scheduled', 'completed')"
    rows = session.execute(text(query), {"race_date": race_date_iso}).mappings().all()
    if not rows:
        mode_name = "예정" if publication_mode == "live" else "예정/완료"
        raise PredictionFrameError(f"{race_date_iso}에 조건과 맞는 {mode_name} 경주가 없습니다.")
    frame = pl.DataFrame([dict(row) for row in rows], infer_schema_length=None)
    if race_ids:
        requested = set(race_ids)
        available = set(frame["race_id"].unique().to_list())
        missing = sorted(requested - available)
        if missing:
            raise PredictionFrameError(f"조건과 맞지 않는 race_id: {missing}")
        frame = frame.filter(pl.col("race_id").is_in(sorted(requested)))
    return frame


def _append_prediction_anchors(base: pl.DataFrame, past: pl.DataFrame) -> pl.DataFrame:
    """Append target rows with null outcomes to reproduce historical shift features."""
    race_date_expr = pl.col("race_date_local").cast(pl.Utf8).str.to_date("%Y-%m-%d")
    target_date = base.select(race_date_expr.min()).item()
    if past.height > 0:
        past = past.filter(pl.col("race_date") < target_date)
    anchors = base.select(
        "horse_id",
        "jockey_id",
        "trainer_id",
        "race_entry_id",
        "race_id",
        "meet_code",
        race_date_expr.alias("race_date"),
        "distance_m",
        "body_weight_kg",
        pl.lit(None).cast(pl.Int64).alias("finish_position"),
        pl.lit(None).cast(pl.Int64).alias("finish_time_ms"),
        "starters",
    )
    if past.height == 0:
        return anchors
    return pl.concat([past, anchors], how="diagonal_relaxed")


def validate_prediction_timing(frame: pl.DataFrame, *, at_ms: int) -> None:
    """Require a live build/publication to occur no later than its model as-of point."""
    late = frame.filter(pl.lit(at_ms) > pl.col("prediction_at_ms"))
    if late.height:
        race_ids = sorted(late["race_id"].unique().to_list())
        raise PredictionFrameError(
            "모델의 as-of 시각을 지난 경주가 있습니다: "
            f"race_id={race_ids}. 이 경주는 live 발행하지 않습니다."
        )


def _feature_set_for_contract(expected_feature_names: list[str]) -> str:
    """Choose the smallest registered feature set covering a model contract."""
    expected = set(expected_feature_names)
    candidates: list[tuple[int, str]] = []
    for feature_set in FEATURE_SETS:
        available = {spec.name for spec in all_feature_specs(feature_set=feature_set)}
        if expected <= available:
            candidates.append((len(available), feature_set))
    if not candidates:
        raise PredictionFrameError(
            "model feature 계약을 포함하는 등록 feature_set이 없습니다."
        )
    return min(candidates)[1]


def build_prediction_frame(
    session: Session,
    *,
    race_date: str | date,
    as_of_policy: str,
    expected_feature_names: list[str],
    publication_mode: str = "live",
    race_ids: list[int] | None = None,
) -> PredictionFrameResult:
    """Build one race day's label-free model input with an exact feature contract."""
    if as_of_policy not in AS_OF_POLICIES:
        raise PredictionFrameError(
            f"알 수 없는 as-of 정책: {as_of_policy}. 지원: {AS_OF_POLICIES}"
        )
    if not expected_feature_names:
        raise PredictionFrameError("model run의 feature 목록이 비어 있습니다.")

    race_date_iso = normalize_race_date(race_date)
    base = fetch_prediction_base_rows(
        session,
        race_date=race_date_iso,
        publication_mode=publication_mode,
        race_ids=race_ids,
    )
    if base.filter(pl.col("scheduled_at_ms").is_null()).height:
        missing = sorted(
            base.filter(pl.col("scheduled_at_ms").is_null())["race_id"].unique().to_list()
        )
        raise PredictionFrameError(f"예정 출발시각이 없는 race_id: {missing}")

    base = base.with_columns(pl.len().over("race_id").alias("starters"))
    small_ids = sorted(
        base.filter(pl.col("starters") < MIN_STARTERS)["race_id"].unique().to_list()
    )
    if small_ids:
        base = base.filter(~pl.col("race_id").is_in(small_ids))
    if base.height == 0:
        raise PredictionFrameError(
            f"최소 {MIN_STARTERS}두 조건을 만족하는 경주가 없습니다: {small_ids}"
        )

    frame = compute_prediction_at(base, as_of_policy)
    if as_of_policy == "day_before_18":
        frame = frame.drop([name for name in RACE_DAY_ONLY_COLUMNS if name in frame.columns])

    sources = load_source_frames(session)
    sources = replace(
        sources,
        past_results=_append_prediction_anchors(base, sources.past_results),
        sections=(
            sources.sections.filter(
                pl.col("race_date") < datetime.fromisoformat(race_date_iso).date()
            )
            if sources.sections.height > 0
            else sources.sections
        ),
    )
    feature_set = _feature_set_for_contract(expected_feature_names)
    frame = apply_features(frame, sources, feature_set=feature_set).sort(
        ["race_date_local", "meet_code", "race_number", "horse_number"]
    )

    forbidden = sorted(set((*LABEL_COLUMNS, "finish_position", "result_id")) & set(frame.columns))
    if forbidden:
        raise PredictionFrameError(f"예측 프레임에 결과/라벨 컬럼이 섞였습니다: {forbidden}")
    available_feature_names = feature_names(frame, feature_set=feature_set)
    expected_set = set(expected_feature_names)
    actual_feature_names = [
        name for name in available_feature_names if name in expected_set
    ]
    if actual_feature_names != expected_feature_names:
        missing = [name for name in expected_feature_names if name not in available_feature_names]
        out_of_order = [
            name for name in expected_feature_names if name in available_feature_names
        ] != actual_feature_names
        raise PredictionFrameError(
            "학습 run과 prediction feature 열/순서가 다릅니다. "
            f"missing={missing[:10]}, out_of_order={out_of_order}"
        )

    null_keys = frame.select(
        pl.any_horizontal(
            pl.col("race_id").is_null(),
            pl.col("race_entry_id").is_null(),
            pl.col("horse_number").is_null(),
        ).sum()
    ).item()
    if null_keys:
        raise PredictionFrameError(f"예측 식별자에 null이 {null_keys}행 있습니다.")

    return PredictionFrameResult(
        frame=frame,
        race_date_local=race_date_iso,
        as_of_policy=as_of_policy,
        feature_names=actual_feature_names,
        feature_hash=hash_feature_names(actual_feature_names),
        excluded_small_field_race_ids=small_ids,
    )


def load_prediction_bundle(run: ModelRun):
    """Load a supported fixed artifact and verify its feature/as-of contract."""
    artifact_raw = run.hyperparameters.get("artifact_path")
    if not artifact_raw:
        raise PredictionFrameError("model run에 artifact 경로가 없습니다.")
    artifact_path = Path(str(artifact_raw))
    if not artifact_path.exists():
        raise PredictionFrameError(f"model artifact 없음: {artifact_path}")

    if run.model_type == "lightgbm_binary_bundle":
        from horse_racing.analysis.lightgbm_model import load_bundle

        bundle = load_bundle(artifact_path)
        bundle_features = bundle.feature_encoder.feature_names
    elif run.model_type == "lightgbm_ranking_bundle":
        from horse_racing.analysis.ranking_model import load_ranking_bundle

        bundle = load_ranking_bundle(artifact_path)
        bundle_features = bundle.feature_encoder.feature_names
    elif run.model_type == "catboost_binary_bundle":
        from horse_racing.analysis.catboost_model import load_catboost_bundle

        bundle = load_catboost_bundle(artifact_path)
        bundle_features = bundle.feature_encoder.feature_names
    elif run.model_type == "probability_ensemble":
        from horse_racing.analysis.model_ensemble import load_ensemble_bundle

        bundle = load_ensemble_bundle(artifact_path)
        bundle_features = bundle.feature_names
    else:
        raise PredictionFrameError(f"추론을 지원하지 않는 model_type: {run.model_type}")

    try:
        _, run_as_of = run.dataset_version.split("/", maxsplit=1)
    except ValueError as exc:
        raise PredictionFrameError(f"지원하지 않는 dataset_version: {run.dataset_version}") from exc
    if bundle.dataset_version != run.dataset_version.split("/", maxsplit=1)[0]:
        raise PredictionFrameError("model run과 artifact의 dataset version이 다릅니다.")
    if bundle.as_of_policy != run_as_of:
        raise PredictionFrameError("model run과 artifact의 as-of 정책이 다릅니다.")
    if list(bundle_features) != run.feature_names:
        raise PredictionFrameError("model run과 artifact의 feature 열/순서가 다릅니다.")
    return bundle, artifact_path


def _isotonic_row_projection(values: np.ndarray) -> np.ndarray:
    """L2 projection of three equally weighted values onto x0 <= x1 <= x2."""
    blocks: list[list[float | int]] = []
    for index, value in enumerate(values):
        blocks.append([float(value), 1, index, index])
        while len(blocks) >= 2 and float(blocks[-2][0]) > float(blocks[-1][0]):
            right = blocks.pop()
            left = blocks.pop()
            weight = int(left[1]) + int(right[1])
            mean = (
                float(left[0]) * int(left[1]) + float(right[0]) * int(right[1])
            ) / weight
            blocks.append([mean, weight, int(left[2]), int(right[3])])
    projected = np.empty(3, dtype=float)
    for mean, _, start, end in blocks:
        projected[int(start) : int(end) + 1] = float(mean)
    return projected


def _project_race_probabilities(values: np.ndarray) -> np.ndarray:
    """Project onto box, race totals, and nested-event monotonicity constraints."""
    runner_count = values.shape[0]
    targets = np.array(
        [1.0, float(min(2, runner_count)), float(min(3, runner_count))],
        dtype=float,
    )
    current = np.asarray(values, dtype=float).copy()
    corrections = [np.zeros_like(current) for _ in range(3)]

    def project_sums(matrix: np.ndarray) -> np.ndarray:
        return matrix + (targets - matrix.sum(axis=0)) / runner_count

    def project_box(matrix: np.ndarray) -> np.ndarray:
        return np.clip(matrix, 0.0, 1.0)

    def project_monotonic(matrix: np.ndarray) -> np.ndarray:
        return np.vstack([_isotonic_row_projection(row) for row in matrix])

    for _ in range(10_000):
        previous = current.copy()
        for index, projection in enumerate(
            (project_sums, project_box, project_monotonic)
        ):
            shifted = current + corrections[index]
            updated = projection(shifted)
            corrections[index] = shifted - updated
            current = updated
        if np.max(np.abs(current - previous)) < 1e-12:
            break
    else:
        raise PredictionFrameError("확률 일관성 projection이 수렴하지 않았습니다.")

    sum_error = float(np.max(np.abs(current.sum(axis=0) - targets)))
    order_error = float(np.max(current[:, :-1] - current[:, 1:]))
    if sum_error > 1e-8 or order_error > 1e-8:
        raise PredictionFrameError(
            "확률 일관성 projection 검증 실패: "
            f"sum_error={sum_error:.3g}, order_error={order_error:.3g}"
        )
    return current


def cohere_prediction_probabilities(predictions: pl.DataFrame) -> pl.DataFrame:
    """Make independently trained nested probabilities jointly coherent per race."""
    required = ["prob_win", "prob_top2", "prob_top3"]
    missing = [name for name in required if name not in predictions.columns]
    if missing:
        raise PredictionFrameError(f"예측 확률 컬럼이 없습니다: {missing}")
    groups: list[pl.DataFrame] = []
    for group in predictions.partition_by("race_id", maintain_order=True):
        values = group.select(required).to_numpy()
        projected = _project_race_probabilities(values)
        groups.append(
            group.with_columns(
                *[
                    pl.Series(column, projected[:, index])
                    for index, column in enumerate(required)
                ]
            )
        )
    return pl.concat(groups, how="vertical")


def predict_model_run(
    run: ModelRun,
    frame: pl.DataFrame,
    *,
    probability_calibration_path: Path | None = None,
) -> tuple[pl.DataFrame, Path]:
    bundle, artifact_path = load_prediction_bundle(run)
    missing = [name for name in run.feature_names if name not in frame.columns]
    if missing:
        raise PredictionFrameError(f"추론 frame에 feature가 없습니다: {missing[:10]}")
    predictions = bundle.predict(frame)
    calibration_raw = probability_calibration_path or run.hyperparameters.get(
        "probability_calibration_path"
    )
    if calibration_raw:
        from horse_racing.analysis.probability_calibration import (
            apply_probability_calibration,
            load_probability_calibration,
        )

        calibration_path = Path(str(calibration_raw))
        calibration = load_probability_calibration(calibration_path)
        predictions = apply_probability_calibration(calibration, predictions)
    else:
        predictions = cohere_prediction_probabilities(predictions)
    return predictions, artifact_path
