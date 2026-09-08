"""확률 예측 평가 지표 (MODELING_ROADMAP §7).

모든 지표는 외부 의존성 없이 polars + 순수 파이썬으로 계산한다.
경주 단위 지표(top1 적중률, top3 포함률)는 확률 동점을 기대값으로
처리한다 — 균등확률 기준 모델(B0)이 공짜 적중을 얻지 않게 하기 위함이다.
"""

from __future__ import annotations

import math

import polars as pl

from horse_racing.analysis.dataset import compute_auc

PROB_EPSILON = 1e-15


def log_loss(probabilities: list[float], labels: list[int]) -> float:
    """이진 로그 손실. 확률은 [eps, 1-eps]로 클리핑한다."""
    if len(probabilities) != len(labels):
        raise ValueError("probabilities와 labels 길이가 다릅니다.")
    if not probabilities:
        raise ValueError("빈 입력입니다.")
    total = 0.0
    for prob, label in zip(probabilities, labels, strict=True):
        clipped = min(max(prob, PROB_EPSILON), 1 - PROB_EPSILON)
        total += -math.log(clipped) if label == 1 else -math.log(1 - clipped)
    return total / len(probabilities)


def brier_score(probabilities: list[float], labels: list[int]) -> float:
    if not probabilities:
        raise ValueError("빈 입력입니다.")
    return sum(
        (prob - label) ** 2 for prob, label in zip(probabilities, labels, strict=True)
    ) / len(probabilities)


def expected_calibration_error(
    probabilities: list[float],
    labels: list[int],
    *,
    n_bins: int = 10,
) -> float:
    """동일 폭 구간 ECE. 각 구간의 |평균확률 − 실제빈도|를 표본 가중 평균한다."""
    if not probabilities:
        raise ValueError("빈 입력입니다.")
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for prob, label in zip(probabilities, labels, strict=True):
        index = min(int(prob * n_bins), n_bins - 1)
        bins[index].append((prob, label))
    total = len(probabilities)
    ece = 0.0
    for bucket in bins:
        if not bucket:
            continue
        confidence = sum(prob for prob, _ in bucket) / len(bucket)
        accuracy = sum(label for _, label in bucket) / len(bucket)
        ece += abs(confidence - accuracy) * len(bucket) / total
    return ece


def calibration_table(
    probabilities: list[float],
    labels: list[int],
    *,
    n_bins: int = 10,
) -> list[dict[str, float | int]]:
    """calibration curve용 구간별 (평균확률, 실제빈도, 표본수)."""
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for prob, label in zip(probabilities, labels, strict=True):
        index = min(int(prob * n_bins), n_bins - 1)
        bins[index].append((prob, label))
    rows: list[dict[str, float | int]] = []
    for bin_index, bucket in enumerate(bins):
        if not bucket:
            continue
        rows.append(
            {
                "bin": bin_index,
                "mean_probability": sum(p for p, _ in bucket) / len(bucket),
                "observed_rate": sum(y for _, y in bucket) / len(bucket),
                "count": len(bucket),
            }
        )
    return rows


def race_level_metrics(
    frame: pl.DataFrame,
    probability_column: str,
    *,
    label_column: str = "win",
    race_column: str = "race_id",
) -> dict[str, float]:
    """경주 단위 top1 적중률·top3 포함률 (동점은 기대값 처리).

    - top1: 우승마보다 확률이 높은 말이 없으면 동점 말 수 t에 대해 1/t 점.
    - top3: 우승마보다 높은 말 g < 3이면, 남은 (3−g) 슬롯을 동점 t마리가
      나눠 가지므로 min(1, (3−g)/t) 점.
    """
    per_race = frame.select(race_column, probability_column, label_column)
    top1_total = 0.0
    top3_total = 0.0
    n_races = 0
    for (_, group) in per_race.group_by(race_column):
        winner_probs = group.filter(pl.col(label_column) == 1)[probability_column].to_list()
        if not winner_probs:
            continue
        n_races += 1
        winner_prob = max(winner_probs)
        probs = group[probability_column].to_list()
        greater = sum(1 for p in probs if p > winner_prob)
        tied = sum(1 for p in probs if p == winner_prob)
        if greater == 0:
            top1_total += 1.0 / tied
        if greater < 3:
            top3_total += min(1.0, (3 - greater) / tied)
    if n_races == 0:
        raise ValueError("우승마가 있는 경주가 없습니다.")
    return {
        "top1_hit_rate": top1_total / n_races,
        "top3_inclusion_rate": top3_total / n_races,
        "n_races": float(n_races),
    }


def evaluate_probabilities(
    frame: pl.DataFrame,
    probability_column: str,
    *,
    label_column: str = "win",
    race_column: str = "race_id",
) -> dict[str, float]:
    """행 단위 + 경주 단위 지표를 한 번에 계산한다.

    확률이 null인 행은 제외하고 coverage로 보고한다 (B3 시장 기준처럼
    일부 경주에 원천이 없는 경우).
    """
    total_rows = frame.height
    scored = frame.filter(pl.col(probability_column).is_not_null())
    if scored.height == 0:
        raise ValueError(f"'{probability_column}'가 전부 null입니다.")

    probs = scored[probability_column].cast(pl.Float64).to_list()
    labels = scored[label_column].cast(pl.Int64).to_list()

    metrics: dict[str, float] = {
        "log_loss": log_loss(probs, labels),
        "brier": brier_score(probs, labels),
        "ece": expected_calibration_error(probs, labels),
        "coverage": scored.height / total_rows,
        "n_rows": float(scored.height),
    }
    auc = compute_auc(probs, labels)
    if auc is not None:
        metrics["auc"] = auc
    metrics.update(
        race_level_metrics(
            scored,
            probability_column,
            label_column=label_column,
            race_column=race_column,
        )
    )
    return metrics
