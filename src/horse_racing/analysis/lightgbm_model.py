"""M4 LightGBM probability models with temporal fitting and calibration.

The historical train split is divided by race date into three ordered blocks:
model fitting, early-stopping tuning, and probability calibration.  The public
validation split is never used to fit either the estimator or calibrator.
"""

from __future__ import annotations

import json
import math
import pickle
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from horse_racing.analysis.baselines import SPLIT_BOUNDS, assign_split
from horse_racing.analysis.metrics import evaluate_probabilities, expected_calibration_error

TARGET_TOTALS: dict[str, float] = {"win": 1.0, "top2": 2.0, "top3": 3.0}
DEFAULT_PARAMS: dict[str, Any] = {
    "objective": "binary",
    "n_estimators": 1_200,
    "learning_rate": 0.03,
    "num_leaves": 31,
    "max_depth": -1,
    "min_child_samples": 80,
    "subsample": 0.9,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "verbosity": -1,
    "n_jobs": -1,
}


class ModelInputError(ValueError):
    """Raised when a dataset cannot be used for M4 training or evaluation."""


@dataclass
class FeatureEncoder:
    feature_names: list[str]
    categorical_features: list[str]
    category_maps: dict[str, dict[str, int]]

    @property
    def categorical_indices(self) -> list[int]:
        return [self.feature_names.index(name) for name in self.categorical_features]


@dataclass
class SigmoidCalibrator:
    model: LogisticRegression = field(
        default_factory=lambda: LogisticRegression(C=1_000.0, solver="lbfgs")
    )

    def fit(self, probabilities: np.ndarray, labels: np.ndarray) -> SigmoidCalibrator:
        self.model.fit(_probability_logits(probabilities).reshape(-1, 1), labels)
        return self

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(
            _probability_logits(probabilities).reshape(-1, 1)
        )[:, 1]


@dataclass
class IsotonicCalibrator:
    model: IsotonicRegression = field(
        default_factory=lambda: IsotonicRegression(out_of_bounds="clip")
    )

    def fit(self, probabilities: np.ndarray, labels: np.ndarray) -> IsotonicCalibrator:
        self.model.fit(probabilities, labels)
        return self

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict(probabilities), dtype=float)


@dataclass
class TargetModel:
    label: str
    race_total: float
    estimator: lgb.LGBMClassifier
    calibration_method: str
    calibrator: SigmoidCalibrator | IsotonicCalibrator | None
    best_iteration: int
    valid_candidates: dict[str, dict[str, float]] = field(default_factory=dict)

    def calibrate(self, raw_probabilities: np.ndarray) -> np.ndarray:
        if self.calibrator is None:
            return np.asarray(raw_probabilities, dtype=float)
        return np.asarray(self.calibrator.predict(raw_probabilities), dtype=float)


@dataclass
class LightGBMModelBundle:
    dataset_version: str
    as_of_policy: str
    feature_encoder: FeatureEncoder
    targets: dict[str, TargetModel]
    hyperparameters: dict[str, Any]
    seed: int
    split_dates: dict[str, str]
    created_at_ms: int = field(default_factory=lambda: time.time_ns() // 1_000_000)

    def predict(self, frame: pl.DataFrame) -> pl.DataFrame:
        matrix = transform_features(frame, self.feature_encoder)
        result = frame.select("race_id", "race_entry_id", "horse_number")
        race_ids = frame["race_id"].to_numpy()
        for label, target in self.targets.items():
            raw = np.asarray(target.estimator.predict_proba(matrix)[:, 1], dtype=float)
            calibrated = target.calibrate(raw)
            normalized = normalize_race_probabilities(
                calibrated,
                race_ids,
                target_total=target.race_total,
            )
            result = result.with_columns(pl.Series(f"prob_{label}", normalized))
        return result


@dataclass
class TrainResult:
    bundle: LightGBMModelBundle
    valid_predictions: pl.DataFrame
    valid_metrics: dict[str, dict[str, float]]


def _probability_logits(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(clipped / (1 - clipped))


def fit_feature_encoder(frame: pl.DataFrame, feature_names: list[str]) -> FeatureEncoder:
    missing = [name for name in feature_names if name not in frame.columns]
    if missing:
        raise ModelInputError(f"데이터셋에 feature가 없습니다: {', '.join(missing[:8])}")

    categorical: list[str] = []
    category_maps: dict[str, dict[str, int]] = {}
    schema = frame.schema
    for name in feature_names:
        if schema[name] in (pl.String, pl.Categorical, pl.Enum):
            categorical.append(name)
            values = sorted(
                {str(value) for value in frame[name].drop_nulls().to_list()}
            )
            category_maps[name] = {value: index for index, value in enumerate(values)}
    return FeatureEncoder(feature_names, categorical, category_maps)


def transform_features(frame: pl.DataFrame, encoder: FeatureEncoder) -> np.ndarray:
    columns: list[np.ndarray] = []
    for name in encoder.feature_names:
        if name in encoder.category_maps:
            mapping = encoder.category_maps[name]
            values = frame[name].to_list()
            encoded = np.fromiter(
                (
                    np.nan if value is None else float(mapping.get(str(value), np.nan))
                    for value in values
                ),
                dtype=float,
                count=len(values),
            )
            columns.append(encoded)
            continue
        series = frame[name]
        if series.dtype == pl.Boolean:
            series = series.cast(pl.Int8)
        try:
            values = np.array(series.cast(pl.Float64).to_numpy(), dtype=float, copy=True)
        except (TypeError, ValueError) as exc:
            raise ModelInputError(f"숫자 변환 불가 feature: {name}") from exc
        values[~np.isfinite(values)] = np.nan
        columns.append(values)
    if not columns:
        raise ModelInputError("feature 목록이 비어 있습니다.")
    return np.column_stack(columns)


def temporal_train_partitions(
    frame: pl.DataFrame,
    *,
    fit_fraction: float = 0.70,
    tune_fraction: float = 0.15,
    split_bounds: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, dict[str, str]]:
    """Split the historical train period into ordered date blocks."""
    train = (
        assign_split(frame, split_bounds=split_bounds)
        .filter(pl.col("split") == "train")
        .drop("split")
    )
    dates = sorted(train["race_date_local"].unique().to_list())
    if len(dates) < 6:
        raise ModelInputError("시간 분할에는 최소 6개 경주일이 필요합니다.")

    fit_end_index = max(0, min(len(dates) - 3, math.ceil(len(dates) * fit_fraction) - 1))
    tune_end_index = max(
        fit_end_index + 1,
        min(len(dates) - 2, math.ceil(len(dates) * (fit_fraction + tune_fraction)) - 1),
    )
    fit_end = dates[fit_end_index]
    tune_end = dates[tune_end_index]
    fit = train.filter(pl.col("race_date_local") <= fit_end)
    tune = train.filter(
        (pl.col("race_date_local") > fit_end) & (pl.col("race_date_local") <= tune_end)
    )
    calibration = train.filter(pl.col("race_date_local") > tune_end)
    if min(fit.height, tune.height, calibration.height) == 0:
        raise ModelInputError("fit/tune/calibration 시간 분할 중 빈 구간이 있습니다.")
    boundaries = {
        "fit_end": str(fit_end),
        "tune_start": str(tune["race_date_local"].min()),
        "tune_end": str(tune_end),
        "calibration_start": str(calibration["race_date_local"].min()),
        "calibration_end": str(calibration["race_date_local"].max()),
    }
    return fit, tune, calibration, boundaries


def _scaled_probabilities(values: np.ndarray, target_total: float) -> np.ndarray:
    count = len(values)
    target = min(float(count), max(0.0, target_total))
    if target == 0:
        return np.zeros(count, dtype=float)
    if target == count:
        return np.ones(count, dtype=float)
    safe = np.clip(np.nan_to_num(values, nan=0.0), 0.0, 1.0)
    if safe.sum() <= 0:
        return np.full(count, target / count, dtype=float)
    low, high = 0.0, 1.0
    while np.minimum(1.0, safe * high).sum() < target:
        high *= 2.0
    for _ in range(60):
        middle = (low + high) / 2.0
        if np.minimum(1.0, safe * middle).sum() < target:
            low = middle
        else:
            high = middle
    return np.minimum(1.0, safe * ((low + high) / 2.0))


def normalize_race_probabilities(
    probabilities: np.ndarray,
    race_ids: np.ndarray,
    *,
    target_total: float,
) -> np.ndarray:
    """Project marginal probabilities to a race total while retaining [0, 1]."""
    probabilities = np.asarray(probabilities, dtype=float)
    race_ids = np.asarray(race_ids)
    if len(probabilities) != len(race_ids):
        raise ValueError("확률과 race_id 길이가 다릅니다.")
    result = np.empty_like(probabilities)
    groups: dict[Any, list[int]] = {}
    for index, race_id in enumerate(race_ids):
        groups.setdefault(race_id.item() if hasattr(race_id, "item") else race_id, []).append(index)
    for indices in groups.values():
        locations = np.asarray(indices, dtype=int)
        result[locations] = _scaled_probabilities(probabilities[locations], target_total)
    return result


def _fit_calibrators(
    probabilities: np.ndarray,
    labels: np.ndarray,
) -> dict[str, SigmoidCalibrator | IsotonicCalibrator | None]:
    return {
        "raw": None,
        "sigmoid": SigmoidCalibrator().fit(probabilities, labels),
        "isotonic": IsotonicCalibrator().fit(probabilities, labels),
    }


def _apply_calibrator(
    calibrator: SigmoidCalibrator | IsotonicCalibrator | None,
    probabilities: np.ndarray,
) -> np.ndarray:
    return probabilities if calibrator is None else calibrator.predict(probabilities)


def _evaluate_candidate(
    frame: pl.DataFrame,
    probabilities: np.ndarray,
    *,
    label: str,
    target_total: float,
) -> tuple[dict[str, float], np.ndarray]:
    pre_ece = expected_calibration_error(
        probabilities.tolist(), frame[label].cast(pl.Int64).to_list()
    )
    normalized = normalize_race_probabilities(
        probabilities,
        frame["race_id"].to_numpy(),
        target_total=target_total,
    )
    scored = frame.with_columns(pl.Series("probability", normalized))
    metrics = evaluate_probabilities(scored, "probability", label_column=label)
    metrics["ece_before_race_normalization"] = pre_ece
    return metrics, normalized


def train_lightgbm_models(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    seed: int = 42,
    calibration: str = "auto",
    hyperparameters: dict[str, Any] | None = None,
    target_labels: tuple[str, ...] | None = None,
    split_bounds: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> TrainResult:
    """Train three binary LightGBM models and evaluate only on validation."""
    if calibration not in {"auto", "raw", "sigmoid", "isotonic"}:
        raise ModelInputError(f"알 수 없는 calibration: {calibration}")
    selected_labels = target_labels or tuple(TARGET_TOTALS)
    unknown_labels = sorted(set(selected_labels) - set(TARGET_TOTALS))
    if unknown_labels:
        raise ModelInputError(f"알 수 없는 target: {', '.join(unknown_labels)}")
    required = {
        "race_id",
        "race_entry_id",
        "horse_number",
        "race_date_local",
        *selected_labels,
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ModelInputError(f"모델 입력 컬럼 없음: {', '.join(missing)}")

    fit, tune, calibration_frame, split_dates = temporal_train_partitions(
        frame,
        split_bounds=split_bounds,
    )
    valid = (
        assign_split(frame, split_bounds=split_bounds)
        .filter(pl.col("split") == "valid")
        .drop("split")
    )
    if valid.height == 0:
        raise ModelInputError("valid split이 비어 있습니다.")

    train_all = pl.concat([fit, tune, calibration_frame], how="vertical")
    encoder = fit_feature_encoder(train_all, feature_names)
    matrices = {
        "fit": transform_features(fit, encoder),
        "tune": transform_features(tune, encoder),
        "fit_tune": transform_features(pl.concat([fit, tune], how="vertical"), encoder),
        "calibration": transform_features(calibration_frame, encoder),
        "valid": transform_features(valid, encoder),
    }

    params = {**DEFAULT_PARAMS, **(hyperparameters or {})}
    params["random_state"] = seed
    targets: dict[str, TargetModel] = {}
    valid_metrics: dict[str, dict[str, float]] = {}
    predictions = valid.select("race_id", "race_entry_id", "horse_number")

    for label in selected_labels:
        target_total = TARGET_TOTALS[label]
        selector = lgb.LGBMClassifier(**params)
        selector.fit(
            matrices["fit"],
            fit[label].to_numpy(),
            eval_X=matrices["tune"],
            eval_y=tune[label].to_numpy(),
            eval_metric="binary_logloss",
            categorical_feature=encoder.categorical_indices,
            callbacks=[lgb.early_stopping(80, verbose=False), lgb.log_evaluation(0)],
        )
        best_iteration = int(selector.best_iteration_ or params["n_estimators"])
        final_params = {**params, "n_estimators": best_iteration}
        estimator = lgb.LGBMClassifier(**final_params)
        fit_tune = pl.concat([fit, tune], how="vertical")
        estimator.fit(
            matrices["fit_tune"],
            fit_tune[label].to_numpy(),
            categorical_feature=encoder.categorical_indices,
            callbacks=[lgb.log_evaluation(0)],
        )

        raw_calibration = np.asarray(
            estimator.predict_proba(matrices["calibration"])[:, 1], dtype=float
        )
        calibrators = _fit_calibrators(
            raw_calibration,
            calibration_frame[label].to_numpy(),
        )
        raw_valid = np.asarray(estimator.predict_proba(matrices["valid"])[:, 1], dtype=float)
        candidate_names = list(calibrators) if calibration == "auto" else [calibration]
        candidate_metrics: dict[str, dict[str, float]] = {}
        candidate_probs: dict[str, np.ndarray] = {}
        for method in candidate_names:
            calibrated = _apply_calibrator(calibrators[method], raw_valid)
            metrics, normalized = _evaluate_candidate(
                valid,
                calibrated,
                label=label,
                target_total=target_total,
            )
            candidate_metrics[method] = metrics
            candidate_probs[method] = normalized
        selected = min(candidate_names, key=lambda name: candidate_metrics[name]["log_loss"])
        selected_metrics = candidate_metrics[selected]
        selected_metrics["best_iteration"] = float(best_iteration)
        valid_metrics[label] = selected_metrics
        predictions = predictions.with_columns(
            pl.Series(f"prob_{label}", candidate_probs[selected])
        )
        targets[label] = TargetModel(
            label=label,
            race_total=target_total,
            estimator=estimator,
            calibration_method=selected,
            calibrator=calibrators[selected],
            best_iteration=best_iteration,
            valid_candidates=candidate_metrics,
        )

    bundle = LightGBMModelBundle(
        dataset_version=dataset_version,
        as_of_policy=as_of_policy,
        feature_encoder=encoder,
        targets=targets,
        hyperparameters=params,
        seed=seed,
        split_dates={
            **split_dates,
            **(
                {
                    "valid_start": str(split_bounds["valid"][0]),
                    "valid_end": str(split_bounds["valid"][1]),
                }
                if split_bounds is not None
                else {}
            ),
        },
    )
    return TrainResult(bundle, predictions, valid_metrics)


def evaluate_bundle(
    bundle: LightGBMModelBundle,
    frame: pl.DataFrame,
    *,
    split: str = "valid",
) -> tuple[dict[str, dict[str, float]], pl.DataFrame]:
    if split not in SPLIT_BOUNDS:
        raise ModelInputError(f"알 수 없는 split: {split}")
    selected = assign_split(frame).filter(pl.col("split") == split).drop("split")
    if selected.height == 0:
        raise ModelInputError(f"{split} split이 비어 있습니다.")
    predictions = bundle.predict(selected)
    joined = selected.join(predictions, on=["race_id", "race_entry_id", "horse_number"])
    metrics = {
        label: evaluate_probabilities(
            joined,
            f"prob_{label}",
            label_column=label,
        )
        for label in bundle.targets
    }
    return metrics, predictions


def save_bundle(bundle: LightGBMModelBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(bundle, handle, protocol=pickle.HIGHEST_PROTOCOL)


def load_bundle(path: Path) -> LightGBMModelBundle:
    if not path.exists():
        raise ModelInputError(f"모델 artifact 없음: {path}")
    with path.open("rb") as handle:
        bundle = pickle.load(handle)  # noqa: S301 - trusted local experiment artifact
    if not isinstance(bundle, LightGBMModelBundle):
        raise ModelInputError(f"지원하지 않는 모델 artifact: {path}")
    return bundle


def render_model_report(
    bundle: LightGBMModelBundle,
    metrics: dict[str, dict[str, float]],
    *,
    run_id: str,
    split: str = "valid",
) -> str:
    lines = [
        "# M4 LightGBM 모델 리포트",
        "",
        f"- run_id: `{run_id}`",
        f"- 데이터셋: `{bundle.dataset_version}` / `{bundle.as_of_policy}`",
        f"- 평가 split: `{split}` (test 미사용)",
        f"- feature: {len(bundle.feature_encoder.feature_names)}개",
        f"- seed: {bundle.seed}",
        "",
        "## 시간 분할",
        "",
        "```json",
        json.dumps(bundle.split_dates, ensure_ascii=False, indent=2),
        "```",
        "",
        f"## {split}",
        "",
        "| target | calibration | best iter | log loss | brier | AUC | ECE | top1 | top3 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label in bundle.targets:
        values = metrics[label]
        target = bundle.targets[label]
        lines.append(
            f"| {label} | {target.calibration_method} | {target.best_iteration} | "
            f"{values['log_loss']:.4f} | {values['brier']:.4f} | "
            f"{values.get('auc', float('nan')):.4f} | {values['ece']:.4f} | "
            f"{values['top1_hit_rate']:.4f} | {values['top3_inclusion_rate']:.4f} |"
        )
    lines.extend(["", "## Calibration 후보 (valid)", ""])
    for label, target in bundle.targets.items():
        lines.extend(
            [
                f"### {label}",
                "",
                "| 방법 | log loss | ECE (정규화 전) | ECE (정규화 후) |",
                "|---|---:|---:|---:|",
            ]
        )
        for method, values in target.valid_candidates.items():
            lines.append(
                f"| {method} | {values['log_loss']:.4f} | "
                f"{values['ece_before_race_normalization']:.4f} | {values['ece']:.4f} |"
            )
        lines.append("")
    lines.extend(
        [
            "## 해석 원칙",
            "",
            "- 보정기는 모델 학습과 분리된 과거 calibration 구간에서만 적합했다.",
            "- calibration 후보 선택에는 valid를 사용했으므로 이 수치는 모델 선택용이다.",
            "- test는 Gate G1의 1회 판정 전까지 평가하지 않는다.",
            "",
        ]
    )
    return "\n".join(lines)
