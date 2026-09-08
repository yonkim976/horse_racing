"""M4 CatBoost comparison using the same temporal and calibration policy."""

from __future__ import annotations

import json
import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl
from catboost import CatBoostClassifier

from horse_racing.analysis.baselines import assign_split
from horse_racing.analysis.lightgbm_model import (
    TARGET_TOTALS,
    FeatureEncoder,
    IsotonicCalibrator,
    ModelInputError,
    SigmoidCalibrator,
    _apply_calibrator,
    _evaluate_candidate,
    _fit_calibrators,
    fit_feature_encoder,
    normalize_race_probabilities,
    temporal_train_partitions,
)
from horse_racing.analysis.metrics import evaluate_probabilities

DEFAULT_CATBOOST_PARAMS: dict[str, Any] = {
    "loss_function": "Logloss",
    "eval_metric": "Logloss",
    "iterations": 1_200,
    "learning_rate": 0.03,
    "depth": 6,
    "l2_leaf_reg": 3.0,
    "random_strength": 1.0,
    "allow_writing_files": False,
    "verbose": False,
    "thread_count": -1,
}


@dataclass
class CatBoostTargetModel:
    label: str
    race_total: float
    estimator: CatBoostClassifier
    calibration_method: str
    calibrator: SigmoidCalibrator | IsotonicCalibrator | None
    best_iteration: int
    valid_candidates: dict[str, dict[str, float]] = field(default_factory=dict)

    def calibrate(self, raw_probabilities: np.ndarray) -> np.ndarray:
        if self.calibrator is None:
            return np.asarray(raw_probabilities, dtype=float)
        return np.asarray(self.calibrator.predict(raw_probabilities), dtype=float)


@dataclass
class CatBoostModelBundle:
    dataset_version: str
    as_of_policy: str
    feature_encoder: FeatureEncoder
    targets: dict[str, CatBoostTargetModel]
    hyperparameters: dict[str, Any]
    seed: int
    split_dates: dict[str, str]
    created_at_ms: int = field(default_factory=lambda: time.time_ns() // 1_000_000)

    def predict(self, frame: pl.DataFrame) -> pl.DataFrame:
        matrix = transform_catboost_features(frame, self.feature_encoder)
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
class CatBoostTrainResult:
    bundle: CatBoostModelBundle
    valid_predictions: pl.DataFrame
    valid_metrics: dict[str, dict[str, float]]


def transform_catboost_features(frame: pl.DataFrame, encoder: FeatureEncoder) -> pd.DataFrame:
    data: dict[str, Any] = {}
    for name in encoder.feature_names:
        if name in encoder.category_maps:
            data[name] = ["__MISSING__" if value is None else str(value) for value in frame[name]]
            continue
        series = frame[name]
        if series.dtype == pl.Boolean:
            series = series.cast(pl.Int8)
        try:
            values = np.array(series.cast(pl.Float64).to_numpy(), dtype=float, copy=True)
        except (TypeError, ValueError) as exc:
            raise ModelInputError(f"숫자 변환 불가 feature: {name}") from exc
        values[~np.isfinite(values)] = np.nan
        data[name] = values
    return pd.DataFrame(data, columns=encoder.feature_names)


def train_catboost_models(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    seed: int = 42,
    calibration: str = "auto",
    hyperparameters: dict[str, Any] | None = None,
    target_labels: tuple[str, ...] | None = None,
) -> CatBoostTrainResult:
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

    fit, tune, calibration_frame, split_dates = temporal_train_partitions(frame)
    valid = assign_split(frame).filter(pl.col("split") == "valid").drop("split")
    if valid.height == 0:
        raise ModelInputError("valid split이 비어 있습니다.")

    train_all = pl.concat([fit, tune, calibration_frame], how="vertical")
    encoder = fit_feature_encoder(train_all, feature_names)
    matrices = {
        "fit": transform_catboost_features(fit, encoder),
        "tune": transform_catboost_features(tune, encoder),
        "fit_tune": transform_catboost_features(
            pl.concat([fit, tune], how="vertical"), encoder
        ),
        "calibration": transform_catboost_features(calibration_frame, encoder),
        "valid": transform_catboost_features(valid, encoder),
    }
    cat_features = encoder.categorical_features
    params = {**DEFAULT_CATBOOST_PARAMS, **(hyperparameters or {})}
    params["random_seed"] = seed

    targets: dict[str, CatBoostTargetModel] = {}
    valid_metrics: dict[str, dict[str, float]] = {}
    predictions = valid.select("race_id", "race_entry_id", "horse_number")
    fit_tune = pl.concat([fit, tune], how="vertical")

    for label in selected_labels:
        target_total = TARGET_TOTALS[label]
        selector = CatBoostClassifier(**params)
        selector.fit(
            matrices["fit"],
            fit[label].to_numpy(),
            cat_features=cat_features,
            eval_set=(matrices["tune"], tune[label].to_numpy()),
            early_stopping_rounds=80,
            use_best_model=True,
            verbose=False,
        )
        best_iteration = int(selector.get_best_iteration() + 1)
        final_params = {**params, "iterations": best_iteration}
        estimator = CatBoostClassifier(**final_params)
        estimator.fit(
            matrices["fit_tune"],
            fit_tune[label].to_numpy(),
            cat_features=cat_features,
            verbose=False,
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
        targets[label] = CatBoostTargetModel(
            label=label,
            race_total=target_total,
            estimator=estimator,
            calibration_method=selected,
            calibrator=calibrators[selected],
            best_iteration=best_iteration,
            valid_candidates=candidate_metrics,
        )

    bundle = CatBoostModelBundle(
        dataset_version=dataset_version,
        as_of_policy=as_of_policy,
        feature_encoder=encoder,
        targets=targets,
        hyperparameters=params,
        seed=seed,
        split_dates=split_dates,
    )
    return CatBoostTrainResult(bundle, predictions, valid_metrics)


def evaluate_catboost_bundle(
    bundle: CatBoostModelBundle,
    frame: pl.DataFrame,
    *,
    split: str = "valid",
) -> tuple[dict[str, dict[str, float]], pl.DataFrame]:
    if split not in {"train", "valid", "test"}:
        raise ModelInputError(f"알 수 없는 split: {split}")
    selected = assign_split(frame).filter(pl.col("split") == split).drop("split")
    if selected.height == 0:
        raise ModelInputError(f"{split} split이 비어 있습니다.")
    predictions = bundle.predict(selected)
    joined = selected.join(predictions, on=["race_id", "race_entry_id", "horse_number"])
    metrics = {
        label: evaluate_probabilities(joined, f"prob_{label}", label_column=label)
        for label in bundle.targets
    }
    return metrics, predictions


def save_catboost_bundle(bundle: CatBoostModelBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(bundle, handle, protocol=pickle.HIGHEST_PROTOCOL)


def load_catboost_bundle(path: Path) -> CatBoostModelBundle:
    if not path.exists():
        raise ModelInputError(f"모델 artifact 없음: {path}")
    with path.open("rb") as handle:
        bundle = pickle.load(handle)  # noqa: S301 - trusted local experiment artifact
    if not isinstance(bundle, CatBoostModelBundle):
        raise ModelInputError(f"지원하지 않는 CatBoost artifact: {path}")
    return bundle


def render_catboost_report(
    bundle: CatBoostModelBundle,
    metrics: dict[str, dict[str, float]],
    *,
    run_id: str,
    split: str = "valid",
) -> str:
    lines = [
        "# M4 CatBoost 모델 리포트",
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
    for label, target in bundle.targets.items():
        values = metrics[label]
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
            "- LightGBM과 같은 데이터·시간 분할·확률 합 제약을 사용했다.",
            "- calibration 후보 선택에는 valid를 사용했으므로 이 수치는 모델 선택용이다.",
            "- test는 Gate G1의 1회 판정 전까지 평가하지 않는다.",
            "",
        ]
    )
    return "\n".join(lines)
