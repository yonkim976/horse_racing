"""Leakage-safe post-hoc calibration for cumulative race-rank probabilities.

The ranker remains untouched.  Calibrators operate on out-of-fold probabilities,
then the existing race-level projection restores the required probability totals
and nested-event ordering.
"""

from __future__ import annotations

import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression

from horse_racing.analysis.lightgbm_model import ModelInputError

CALIBRATION_TARGETS = ("win", "top2", "top3")
CALIBRATION_METHODS = {"identity", "sigmoid"}
PROBABILITY_CLIP = 1e-6


def _logit(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(
        np.asarray(probabilities, dtype=float),
        PROBABILITY_CLIP,
        1.0 - PROBABILITY_CLIP,
    )
    return np.log(clipped / (1.0 - clipped))


@dataclass(frozen=True, slots=True)
class LogitCalibration:
    """Serializable ``sigmoid(intercept + slope * logit(p))`` parameters."""

    intercept: float
    slope: float

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        linear = np.clip(self.intercept + self.slope * _logit(probabilities), -50.0, 50.0)
        return 1.0 / (1.0 + np.exp(-linear))


@dataclass
class ProbabilityCalibrationBundle:
    """Post-hoc calibrators fitted only from historical out-of-fold predictions."""

    source_run_id: str
    fit_period: str
    methods: dict[str, str]
    calibrators: dict[str, LogitCalibration | None]
    created_at_ms: int = field(default_factory=lambda: time.time_ns() // 1_000_000)

    def predict(self, predictions: pl.DataFrame, *, preserve_raw: bool = True) -> pl.DataFrame:
        required = [f"prob_{target}" for target in CALIBRATION_TARGETS]
        missing = [column for column in required if column not in predictions.columns]
        if missing:
            raise ModelInputError("확률 보정 입력 컬럼 없음: " + ", ".join(missing))

        output = predictions
        if preserve_raw:
            output = output.with_columns(
                *(pl.col(column).alias(f"{column}_raw") for column in required)
            )
        for target in CALIBRATION_TARGETS:
            column = f"prob_{target}"
            calibrator = self.calibrators.get(target)
            if calibrator is None:
                continue
            values = calibrator.predict(output[column].to_numpy())
            output = output.with_columns(pl.Series(column, values))
        return output


def fit_logit_calibration(
    probabilities: np.ndarray,
    labels: np.ndarray,
) -> LogitCalibration:
    probabilities = np.asarray(probabilities, dtype=float)
    labels = np.asarray(labels, dtype=int)
    if len(probabilities) != len(labels) or not len(labels):
        raise ModelInputError("확률과 라벨은 길이가 같은 비어 있지 않은 배열이어야 합니다.")
    if len(np.unique(labels)) != 2:
        raise ModelInputError("sigmoid 보정 학습에는 양성과 음성 라벨이 모두 필요합니다.")
    model = LogisticRegression(C=1_000.0, solver="lbfgs")
    model.fit(_logit(probabilities).reshape(-1, 1), labels)
    return LogitCalibration(
        intercept=float(model.intercept_[0]),
        slope=float(model.coef_[0, 0]),
    )


def fit_probability_calibration(
    frame: pl.DataFrame,
    *,
    source_run_id: str,
    fit_period: str,
    methods: dict[str, str] | None = None,
) -> ProbabilityCalibrationBundle:
    """Fit target-specific calibration from historical OOF prediction rows.

    The default deliberately leaves the already well-calibrated win marginal
    unchanged and calibrates the less reliable Top2/Top3 cumulative marginals.
    """

    selected = {"win": "identity", "top2": "sigmoid", "top3": "sigmoid"}
    if methods is not None:
        selected.update(methods)
    unknown_targets = sorted(set(selected) - set(CALIBRATION_TARGETS))
    unknown_methods = sorted(set(selected.values()) - CALIBRATION_METHODS)
    if unknown_targets:
        raise ModelInputError("지원하지 않는 보정 target: " + ", ".join(unknown_targets))
    if unknown_methods:
        raise ModelInputError("지원하지 않는 보정 방법: " + ", ".join(unknown_methods))

    required = [
        *(f"prob_{target}" for target in CALIBRATION_TARGETS),
        *CALIBRATION_TARGETS,
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ModelInputError("확률 보정 학습 컬럼 없음: " + ", ".join(missing))

    calibrators: dict[str, LogitCalibration | None] = {}
    for target in CALIBRATION_TARGETS:
        method = selected[target]
        calibrators[target] = (
            None
            if method == "identity"
            else fit_logit_calibration(
                frame[f"prob_{target}"].to_numpy(),
                frame[target].to_numpy(),
            )
        )
    return ProbabilityCalibrationBundle(
        source_run_id=source_run_id,
        fit_period=fit_period,
        methods=selected,
        calibrators=calibrators,
    )


def apply_probability_calibration(
    bundle: ProbabilityCalibrationBundle,
    predictions: pl.DataFrame,
    *,
    preserve_raw: bool = True,
) -> pl.DataFrame:
    """Calibrate, enforce race coherence, and refresh exact-rank marginals."""

    # Local import avoids coupling prediction-frame construction to this optional layer.
    from horse_racing.analysis.prediction_frame import cohere_prediction_probabilities

    coherent = cohere_prediction_probabilities(
        bundle.predict(predictions, preserve_raw=preserve_raw)
    )
    rank1 = coherent["prob_win"].to_numpy()
    rank2 = np.maximum(coherent["prob_top2"].to_numpy() - rank1, 0.0)
    rank3 = np.maximum(coherent["prob_top3"].to_numpy() - coherent["prob_top2"].to_numpy(), 0.0)
    replacements = {
        "prob_rank1": rank1,
        "prob_rank2": rank2,
        "prob_rank3": rank3,
        "prob_second": rank2,
        "prob_third": rank3,
    }
    return coherent.with_columns(
        *(pl.Series(name, values) for name, values in replacements.items())
    )


def save_probability_calibration(
    bundle: ProbabilityCalibrationBundle,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(bundle, handle, protocol=pickle.HIGHEST_PROTOCOL)


def load_probability_calibration(path: Path) -> ProbabilityCalibrationBundle:
    if not path.exists():
        raise ModelInputError(f"확률 보정 artifact 없음: {path}")
    with path.open("rb") as handle:
        bundle = pickle.load(handle)  # noqa: S301 - trusted local artifact
    if not isinstance(bundle, ProbabilityCalibrationBundle):
        raise ModelInputError(f"지원하지 않는 확률 보정 artifact: {path}")
    return bundle
