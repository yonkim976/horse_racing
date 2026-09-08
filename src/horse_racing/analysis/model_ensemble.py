"""Probability-level ensembles for reproducible M4 model selection."""

from __future__ import annotations

import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl

from horse_racing.analysis.baselines import assign_split
from horse_racing.analysis.catboost_model import load_catboost_bundle
from horse_racing.analysis.lightgbm_model import ModelInputError, load_bundle
from horse_racing.analysis.metrics import evaluate_probabilities


@dataclass
class ProbabilityEnsembleBundle:
    dataset_version: str
    as_of_policy: str
    member_type: str
    member_run_ids: list[str]
    member_paths: list[str]
    feature_names: list[str]
    targets: list[str]
    member_types: list[str] = field(default_factory=list)
    target_member_weights: dict[str, list[float]] = field(default_factory=dict)
    created_at_ms: int = field(default_factory=lambda: time.time_ns() // 1_000_000)

    def predict(self, frame: pl.DataFrame) -> pl.DataFrame:
        member_predictions: list[pl.DataFrame] = []
        member_types = getattr(self, "member_types", []) or [self.member_type] * len(
            self.member_paths
        )
        for path_text, member_type in zip(self.member_paths, member_types, strict=True):
            path = Path(path_text)
            if member_type == "lightgbm_binary_bundle":
                bundle = load_bundle(path)
            elif member_type == "catboost_binary_bundle":
                bundle = load_catboost_bundle(path)
            elif member_type == "probability_ensemble":
                bundle = load_ensemble_bundle(path)
            elif member_type == "lightgbm_ranking_bundle":
                from horse_racing.analysis.ranking_model import load_ranking_bundle

                bundle = load_ranking_bundle(path)
            elif member_type == "racefit_scenario_bundle":
                from horse_racing.analysis.racefit_model import load_racefit_bundle

                bundle = load_racefit_bundle(path)
            else:
                raise ModelInputError(f"지원하지 않는 ensemble member: {member_type}")
            member_predictions.append(bundle.predict(frame))
        return average_predictions(
            member_predictions,
            targets=self.targets,
            target_member_weights=getattr(self, "target_member_weights", {}),
        )


def average_predictions(
    predictions: list[pl.DataFrame],
    *,
    targets: list[str],
    target_member_weights: dict[str, list[float]] | None = None,
) -> pl.DataFrame:
    if not predictions:
        raise ModelInputError("ensemble member가 없습니다.")
    key_columns = ["race_id", "race_entry_id", "horse_number"]
    reference = predictions[0].select(*key_columns)
    output = reference.clone()
    for label in targets:
        column = f"prob_{label}"
        arrays: list[np.ndarray] = []
        weights: list[float] = []
        configured = (target_member_weights or {}).get(label)
        if configured is not None and len(configured) != len(predictions):
            raise ModelInputError(f"{label} ensemble weight 수가 member 수와 다릅니다.")
        for index, frame in enumerate(predictions):
            if frame.select(*key_columns).to_dict(as_series=False) != reference.to_dict(
                as_series=False
            ):
                raise ModelInputError(f"ensemble member {index}의 예측 행 순서가 다릅니다.")
            weight = float(configured[index]) if configured is not None else 1.0
            if weight <= 0:
                continue
            if column not in frame.columns:
                raise ModelInputError(f"ensemble member {index}에 {column}이 없습니다.")
            arrays.append(np.asarray(frame[column].to_numpy(), dtype=float))
            weights.append(weight)
        if not arrays or sum(weights) <= 0:
            raise ModelInputError(f"{label}에 유효한 ensemble member가 없습니다.")
        normalized = np.asarray(weights, dtype=float) / sum(weights)
        values = np.average(np.vstack(arrays), axis=0, weights=normalized)
        output = output.with_columns(pl.Series(column, values))
    if "top5" in targets:
        ordered_targets = ["win", "top2", "top3", "top4", "top5"]
        missing = [label for label in ordered_targets if label not in targets]
        if missing:
            raise ModelInputError(
                "Top5 ensemble에는 누적 target win~top5가 모두 필요합니다: "
                + ", ".join(missing)
            )
        weight_vectors = []
        for label in ordered_targets:
            configured = (target_member_weights or {}).get(label)
            vector = configured if configured is not None else [1.0] * len(predictions)
            total = float(sum(max(0.0, float(value)) for value in vector))
            if total <= 0:
                raise ModelInputError(f"{label} ensemble weight 합이 0입니다.")
            weight_vectors.append(
                np.asarray([max(0.0, float(value)) / total for value in vector], dtype=float)
            )
        if any(
            not np.allclose(weight_vectors[0], vector, atol=1e-12, rtol=0.0)
            for vector in weight_vectors[1:]
        ):
            raise ModelInputError(
                "Top5 ensemble은 순위확률 일관성을 위해 win~top5에 동일한 member weight가 "
                "필요합니다."
            )
        cumulative_columns = ["prob_win", "prob_top2", "prob_top3", "prob_top4", "prob_top5"]
        cumulative = np.column_stack(
            [np.asarray(output[column].to_numpy(), dtype=float) for column in cumulative_columns]
        )
        if np.any(np.diff(cumulative, axis=1) < -1e-10):
            raise ModelInputError("Top5 ensemble 누적확률이 단조롭지 않습니다.")
        exact = np.column_stack([cumulative[:, 0], np.diff(cumulative, axis=1)])
        output = output.with_columns(
            *(pl.Series(f"prob_rank{rank}", exact[:, rank - 1]) for rank in range(1, 6))
        )
    return output


def evaluate_ensemble_bundle(
    bundle: ProbabilityEnsembleBundle,
    frame: pl.DataFrame,
    *,
    split: str = "valid",
) -> tuple[dict[str, dict[str, float]], pl.DataFrame]:
    if split not in {"train", "valid", "test"}:
        raise ModelInputError(f"알 수 없는 split: {split}")
    selected = assign_split(frame).filter(pl.col("split") == split).drop("split")
    if selected.height == 0:
        raise ModelInputError(f"{split} split이 비어 있습니다.")
    if "top5" in bundle.targets:
        from horse_racing.analysis.ranking_model import with_topk_labels

        selected = with_topk_labels(selected, max_rank=5)
    predictions = bundle.predict(selected)
    joined = selected.join(predictions, on=["race_id", "race_entry_id", "horse_number"])
    metrics = {
        label: evaluate_probabilities(joined, f"prob_{label}", label_column=label)
        for label in bundle.targets
    }
    return metrics, predictions


def save_ensemble_bundle(bundle: ProbabilityEnsembleBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(bundle, handle, protocol=pickle.HIGHEST_PROTOCOL)


def load_ensemble_bundle(path: Path) -> ProbabilityEnsembleBundle:
    if not path.exists():
        raise ModelInputError(f"ensemble artifact 없음: {path}")
    with path.open("rb") as handle:
        bundle = pickle.load(handle)  # noqa: S301 - trusted local experiment artifact
    if not isinstance(bundle, ProbabilityEnsembleBundle):
        raise ModelInputError(f"지원하지 않는 ensemble artifact: {path}")
    return bundle


def render_ensemble_report(
    bundle: ProbabilityEnsembleBundle,
    metrics: dict[str, dict[str, float]],
    *,
    run_id: str,
    split: str = "valid",
) -> str:
    lines = [
        "# M4 확률 평균 앙상블 리포트",
        "",
        f"- run_id: `{run_id}`",
        f"- 데이터셋: `{bundle.dataset_version}` / `{bundle.as_of_policy}`",
        f"- member type: `{bundle.member_type}`",
        f"- members: {', '.join(f'`{item}`' for item in bundle.member_run_ids)}",
        f"- target weights: `{getattr(bundle, 'target_member_weights', {}) or 'equal'}`",
        f"- 평가 split: `{split}`",
        "",
        "| target | log loss | brier | AUC | ECE | top1 | top3 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, values in metrics.items():
        lines.append(
            f"| {label} | {values['log_loss']:.4f} | {values['brier']:.4f} | "
            f"{values.get('auc', float('nan')):.4f} | {values['ece']:.4f} | "
            f"{values['top1_hit_rate']:.4f} | {values['top3_inclusion_rate']:.4f} |"
        )
    lines.extend(["", "test는 Gate G1의 1회 판정 전까지 평가하지 않는다.", ""])
    return "\n".join(lines)
