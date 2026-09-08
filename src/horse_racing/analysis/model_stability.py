"""M4 stability checks: feature-group ablation and segment decomposition."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

import polars as pl

from horse_racing.analysis.baselines import assign_split
from horse_racing.analysis.features import all_feature_specs
from horse_racing.analysis.lightgbm_model import train_lightgbm_models
from horse_racing.analysis.metrics import evaluate_probabilities


@dataclass
class AblationRow:
    group: str
    feature_count: int
    valid_log_loss: float
    delta_log_loss: float
    valid_auc: float
    valid_ece: float


@dataclass
class AblationResult:
    baseline_log_loss: float
    baseline_auc: float
    baseline_ece: float
    rows: list[AblationRow]


def registered_feature_groups(feature_names: list[str]) -> dict[str, list[str]]:
    available = set(feature_names)
    groups: dict[str, list[str]] = {}
    registered: set[str] = set()
    for spec in all_feature_specs():
        if spec.name not in available:
            continue
        groups.setdefault(spec.group, []).append(spec.name)
        registered.add(spec.name)
    unregistered = [name for name in feature_names if name not in registered]
    if unregistered:
        groups["기타 미등록"] = unregistered
    return groups


def run_lightgbm_ablation(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    seed: int = 42,
) -> AblationResult:
    baseline = train_lightgbm_models(
        frame,
        feature_names=feature_names,
        dataset_version=dataset_version,
        as_of_policy=as_of_policy,
        seed=seed,
        calibration="raw",
        target_labels=("win",),
    ).valid_metrics["win"]
    rows: list[AblationRow] = []
    for group, group_features in registered_feature_groups(feature_names).items():
        kept = [name for name in feature_names if name not in set(group_features)]
        result = train_lightgbm_models(
            frame,
            feature_names=kept,
            dataset_version=dataset_version,
            as_of_policy=as_of_policy,
            seed=seed,
            calibration="raw",
            target_labels=("win",),
        ).valid_metrics["win"]
        rows.append(
            AblationRow(
                group=group,
                feature_count=len(group_features),
                valid_log_loss=result["log_loss"],
                delta_log_loss=result["log_loss"] - baseline["log_loss"],
                valid_auc=result.get("auc", float("nan")),
                valid_ece=result["ece"],
            )
        )
    rows.sort(key=lambda row: row.delta_log_loss, reverse=True)
    return AblationResult(
        baseline_log_loss=baseline["log_loss"],
        baseline_auc=baseline.get("auc", float("nan")),
        baseline_ece=baseline["ece"],
        rows=rows,
    )


def render_ablation_report(
    result: AblationResult,
    *,
    dataset_version: str,
    as_of_policy: str,
    seed: int,
) -> str:
    lines = [
        "# M4 LightGBM feature-group ablation",
        "",
        f"- 데이터셋: `{dataset_version}` / `{as_of_policy}`",
        f"- seed: {seed}",
        "- target: `win`, calibration: `raw`, test 미사용",
        f"- 전체 feature log loss: **{result.baseline_log_loss:.4f}**",
        "",
        "양수 delta는 해당 그룹을 제거했을 때 성능이 나빠져 유용했다는 뜻이다.",
        "",
        "| 제거 그룹 | feature 수 | valid log loss | delta | AUC | ECE |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in result.rows:
        lines.append(
            f"| {row.group} | {row.feature_count} | {row.valid_log_loss:.4f} | "
            f"{row.delta_log_loss:+.4f} | {row.valid_auc:.4f} | {row.valid_ece:.4f} |"
        )
    lines.extend(
        [
            "",
            "이 표는 valid에서 feature 의존성을 진단하는 용도이며 Gate G1 판정이 아니다.",
            "",
        ]
    )
    return "\n".join(lines)


def _with_segment_columns(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.when(pl.col("distance_m") <= 1200)
        .then(pl.lit("≤1200m"))
        .when(pl.col("distance_m") <= 1600)
        .then(pl.lit("1300–1600m"))
        .otherwise(pl.lit("≥1700m"))
        .alias("_distance_band"),
        pl.when(pl.col("starters") <= 8)
        .then(pl.lit("≤8두"))
        .when(pl.col("starters") <= 11)
        .then(pl.lit("9–11두"))
        .otherwise(pl.lit("≥12두"))
        .alias("_field_band"),
        pl.concat_str(
            [
                pl.col("grade_mix").fill_null("미상"),
                pl.col("grade_tier").cast(pl.String).fill_null("미상"),
            ],
            separator="/",
        ).alias("_grade_band"),
        pl.col("race_date_local").str.slice(0, 7).alias("_month"),
        pl.col("meet_code").cast(pl.String).alias("_meet"),
    )


def evaluate_win_segments(
    frame: pl.DataFrame,
    predictions: pl.DataFrame,
    *,
    split: str = "valid",
) -> dict[str, list[dict[str, Any]]]:
    selected = assign_split(frame).filter(pl.col("split") == split).drop("split")
    joined = selected.join(
        predictions.select("race_id", "race_entry_id", "prob_win"),
        on=["race_id", "race_entry_id"],
        how="inner",
    )
    joined = _with_segment_columns(joined)
    dimensions = {
        "경마장": "_meet",
        "거리대": "_distance_band",
        "등급": "_grade_band",
        "출전두수": "_field_band",
        "월": "_month",
    }
    output: dict[str, list[dict[str, Any]]] = {}
    for title, column in dimensions.items():
        rows: list[dict[str, Any]] = []
        values = joined[column].drop_nulls().unique().sort().to_list()
        for value in values:
            group = joined.filter(pl.col(column) == value)
            metrics = evaluate_probabilities(group, "prob_win", label_column="win")
            rows.append({"segment": str(value), **metrics})
        output[title] = rows
    return output


def render_segment_report(
    segments: dict[str, list[dict[str, Any]]],
    *,
    model_name: str,
    split: str,
) -> str:
    lines = [f"# {model_name} 구간별 평가", "", f"- split: `{split}`", "- target: `win`", ""]
    for title, rows in segments.items():
        lines.extend(
            [
                f"## {title}",
                "",
                "| 구간 | 경주 | 행 | log loss | AUC | ECE | Top1 | Top3 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in rows:
            lines.append(
                f"| {row['segment']} | {row['n_races']:.0f} | {row['n_rows']:.0f} | "
                f"{row['log_loss']:.4f} | {row.get('auc', float('nan')):.4f} | "
                f"{row['ece']:.4f} | {row['top1_hit_rate']:.4f} | "
                f"{row['top3_inclusion_rate']:.4f} |"
            )
        lines.append("")
    return "\n".join(lines)


def seed_summary(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("seed 결과가 비어 있습니다.")
    return {
        "mean": statistics.mean(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }
