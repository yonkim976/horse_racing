"""M3 기준 모델 4종 (MODELING_ROADMAP §6).

- B0: 균등확률 1/N — 지표 하한
- B1: 레이팅 z-score softmax (스케일 계수 β를 train에서 적합)
- B2: 최근 5경주 착순 백분위 z-score softmax (동일 방식, 낮을수록 좋음)
- B3: 시장 — 단승 확정배당 암시확률 (경주 전 정보 아님, 비교 전용)

시간 분할은 경주 날짜 기준으로 고정한다. test는 G1·G2 판정 전까지
평가하지 않는다 (기본 제외, --include-test로만 접근).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any

import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from horse_racing.analysis.metrics import evaluate_probabilities

# 경주 날짜(문자열 비교) 기준 시간 분할. MODELING_ROADMAP §6.
SPLIT_BOUNDS: dict[str, tuple[str | None, str | None]] = {
    "train": (None, "2026-02-28"),
    "valid": ("2026-03-01", "2026-05-31"),
    "test": ("2026-06-01", None),
}

PROBABILITY_COLUMN = "probability"

BASELINE_IDS = ("B0", "B1", "B2", "B3")


class BaselineInputError(ValueError):
    """기준 모델 계산에 필요한 입력이 없거나 잘못됨."""


def assign_split(
    frame: pl.DataFrame,
    *,
    date_column: str = "race_date_local",
    split_bounds: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> pl.DataFrame:
    """race_date_local 기준으로 train/valid/test 분할 컬럼을 추가한다."""
    bounds = SPLIT_BOUNDS if split_bounds is None else split_bounds
    train_end = bounds["train"][1]
    valid_end = bounds["valid"][1]
    if train_end is None or valid_end is None:
        raise ValueError("train 종료일과 valid 종료일이 필요합니다.")
    date = pl.col(date_column).cast(pl.Utf8)
    expr = pl.when(date <= train_end).then(pl.lit("train"))
    expr = expr.when(date <= valid_end).then(pl.lit("valid"))
    expr = expr.otherwise(pl.lit("test"))
    return frame.with_columns(expr.alias("split"))


def uniform_probabilities(frame: pl.DataFrame, *, race_column: str = "race_id") -> pl.DataFrame:
    """B0: 경주 내 균등확률 1/N."""
    return frame.with_columns(
        (1.0 / pl.len().over(race_column)).alias(PROBABILITY_COLUMN)
    )


def _oriented_zscore(
    score_column: str,
    *,
    higher_is_better: bool,
    race_column: str,
) -> pl.Expr:
    """경주 내 z-score. 결측·표준편차 0은 0(경주 평균)으로 둔다."""
    score = pl.col(score_column).cast(pl.Float64)
    mean = score.mean().over(race_column)
    std = score.std().over(race_column)
    z = ((score - mean) / std).fill_nan(0.0).fill_null(0.0)
    z = pl.when(std > 0).then(z).otherwise(0.0).fill_null(0.0)
    return z if higher_is_better else -z


def score_softmax_probabilities(
    frame: pl.DataFrame,
    score_column: str,
    *,
    beta: float,
    higher_is_better: bool = True,
    race_column: str = "race_id",
) -> pl.DataFrame:
    """경주 내 z-score에 softmax(β·z)를 적용한 확률 컬럼을 추가한다.

    z-score 정규화로 경주 간 스케일 차이를 제거하므로 β 하나로 전 경주에
    일관된 온도를 걸 수 있다. β=0이면 균등확률과 같다.
    """
    if score_column not in frame.columns:
        raise BaselineInputError(f"점수 컬럼 없음: {score_column}")
    z = _oriented_zscore(
        score_column, higher_is_better=higher_is_better, race_column=race_column
    )
    logits = (z * beta).alias("_logit")
    result = frame.with_columns(logits)
    # 수치 안정화: 경주 내 최대 logit을 빼고 exp
    result = result.with_columns(
        (pl.col("_logit") - pl.col("_logit").max().over(race_column)).exp().alias("_exp")
    )
    result = result.with_columns(
        (pl.col("_exp") / pl.col("_exp").sum().over(race_column)).alias(PROBABILITY_COLUMN)
    )
    return result.drop(["_logit", "_exp"])


def _softmax_log_loss(
    frame: pl.DataFrame,
    score_column: str,
    beta: float,
    *,
    higher_is_better: bool,
    label_column: str,
    race_column: str,
) -> float:
    scored = score_softmax_probabilities(
        frame,
        score_column,
        beta=beta,
        higher_is_better=higher_is_better,
        race_column=race_column,
    )
    loss = scored.select(
        pl.when(pl.col(label_column) == 1)
        .then(-pl.col(PROBABILITY_COLUMN).clip(1e-15, 1.0).log())
        .otherwise(-(1 - pl.col(PROBABILITY_COLUMN)).clip(1e-15, 1.0).log())
        .mean()
    ).item()
    return float(loss)


def fit_softmax_beta(
    frame: pl.DataFrame,
    score_column: str,
    *,
    higher_is_better: bool = True,
    label_column: str = "win",
    race_column: str = "race_id",
    beta_max: float = 50.0,
    iterations: int = 60,
) -> float:
    """train에서 로그 손실을 최소화하는 β를 황금분할 탐색으로 적합한다.

    softmax 로그 손실은 β에 대해 볼록하므로 단봉 탐색으로 충분하다.
    """
    low, high = 0.0, beta_max
    golden = (math.sqrt(5) - 1) / 2

    def loss_at(beta: float) -> float:
        return _softmax_log_loss(
            frame,
            score_column,
            beta,
            higher_is_better=higher_is_better,
            label_column=label_column,
            race_column=race_column,
        )

    inner_low = high - golden * (high - low)
    inner_high = low + golden * (high - low)
    loss_low = loss_at(inner_low)
    loss_high = loss_at(inner_high)
    for _ in range(iterations):
        if loss_low < loss_high:
            high, inner_high, loss_high = inner_high, inner_low, loss_low
            inner_low = high - golden * (high - low)
            loss_low = loss_at(inner_low)
        else:
            low, inner_low, loss_low = inner_low, inner_high, loss_high
            inner_high = low + golden * (high - low)
            loss_high = loss_at(inner_high)
        if high - low < 1e-4:
            break
    return (low + high) / 2


def fetch_win_odds(session: Session) -> pl.DataFrame:
    """단승(WIN) 확정배당을 경주×출주번호 단위로 읽는다 (경주별 최신 관측)."""
    rows = session.execute(
        text(
            """
            SELECT race_id,
                   CAST(selection_key AS INTEGER) AS horse_number,
                   odds
            FROM odds_snapshots
            WHERE bet_type = 'WIN'
              AND (race_id, selection_key, observed_at_ms) IN (
                  SELECT race_id, selection_key, MAX(observed_at_ms)
                  FROM odds_snapshots
                  WHERE bet_type = 'WIN'
                  GROUP BY race_id, selection_key
              )
            """
        )
    ).mappings().all()
    if not rows:
        return pl.DataFrame(
            schema={"race_id": pl.Int64, "horse_number": pl.Int64, "odds": pl.Float64}
        )
    return pl.DataFrame([dict(row) for row in rows], infer_schema_length=None)


def market_probabilities(
    frame: pl.DataFrame,
    odds: pl.DataFrame,
    *,
    race_column: str = "race_id",
) -> pl.DataFrame:
    """B3: 암시확률 p_i ∝ 1/odds_i (경주 내 정규화). 배당 없는 행은 null.

    한 경주에서 일부 말만 배당이 있으면 정규화가 왜곡되므로 그 경주 전체를
    null 처리한다. overround(Σ1/odds)는 `market_overround` 컬럼으로 남긴다.
    """
    joined = frame.join(
        odds.select(race_column, "horse_number", "odds"),
        on=[race_column, "horse_number"],
        how="left",
    )
    joined = joined.with_columns(
        (1.0 / pl.col("odds")).alias("_implied"),
        pl.col("odds").is_null().any().over(race_column).alias("_incomplete"),
    )
    joined = joined.with_columns(
        pl.when(pl.col("_incomplete"))
        .then(None)
        .otherwise(pl.col("_implied").sum().over(race_column))
        .alias("market_overround")
    )
    joined = joined.with_columns(
        pl.when(pl.col("_incomplete"))
        .then(None)
        .otherwise(pl.col("_implied") / pl.col("market_overround"))
        .alias(PROBABILITY_COLUMN)
    )
    return joined.drop(["odds", "_implied", "_incomplete"])


@dataclass
class BaselineResult:
    baseline_id: str
    model_type: str
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    # split 이름 → 지표 dict
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    notes: str = ""


def run_baselines(
    frame: pl.DataFrame,
    *,
    odds: pl.DataFrame | None = None,
    label_column: str = "win",
    race_column: str = "race_id",
    evaluate_splits: tuple[str, ...] = ("train", "valid"),
) -> list[BaselineResult]:
    """B0~B3를 실행한다. β는 train에서만 적합하고 지정 split에서 평가한다."""
    for split in evaluate_splits:
        if split not in SPLIT_BOUNDS:
            raise BaselineInputError(f"알 수 없는 split: {split}")

    with_split = assign_split(frame)
    train = with_split.filter(pl.col("split") == "train")
    if train.height == 0:
        raise BaselineInputError("train split이 비어 있습니다.")

    def evaluate(
        probability_frame: pl.DataFrame,
    ) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for split in evaluate_splits:
            subset = probability_frame.filter(pl.col("split") == split)
            if subset.height == 0:
                continue
            out[split] = evaluate_probabilities(
                subset,
                PROBABILITY_COLUMN,
                label_column=label_column,
                race_column=race_column,
            )
        return out

    results: list[BaselineResult] = []

    # B0: 균등확률
    results.append(
        BaselineResult(
            baseline_id="B0",
            model_type="baseline_uniform",
            metrics=evaluate(uniform_probabilities(with_split, race_column=race_column)),
            notes="지표 하한 (1/N)",
        )
    )

    # B1: 레이팅 softmax
    beta_rating = fit_softmax_beta(
        train, "rating", higher_is_better=True,
        label_column=label_column, race_column=race_column,
    )
    results.append(
        BaselineResult(
            baseline_id="B1",
            model_type="baseline_rating_softmax",
            hyperparameters={"beta": beta_rating, "score": "rating"},
            metrics=evaluate(
                score_softmax_probabilities(
                    with_split, "rating", beta=beta_rating,
                    higher_is_better=True, race_column=race_column,
                )
            ),
            notes="경주 내 레이팅 z-score softmax, β는 train 적합",
        )
    )

    # B2: 최근 5경주 착순 백분위 softmax (낮을수록 좋음: 0=1착)
    beta_form = fit_softmax_beta(
        train, "form_recent5_pct", higher_is_better=False,
        label_column=label_column, race_column=race_column,
    )
    results.append(
        BaselineResult(
            baseline_id="B2",
            model_type="baseline_form_softmax",
            hyperparameters={"beta": beta_form, "score": "form_recent5_pct"},
            metrics=evaluate(
                score_softmax_probabilities(
                    with_split, "form_recent5_pct", beta=beta_form,
                    higher_is_better=False, race_column=race_column,
                )
            ),
            notes="최근 5경주 착순 백분위 z-score softmax, β는 train 적합",
        )
    )

    # B3: 시장 암시확률 (비교 전용 — 경주 전 정보 아님)
    if odds is not None and odds.height > 0:
        market = market_probabilities(with_split, odds, race_column=race_column)
        overround = (
            market.filter(pl.col("market_overround").is_not_null())
            .select(race_column, "market_overround")
            .unique()
        )
        results.append(
            BaselineResult(
                baseline_id="B3",
                model_type="baseline_market_implied",
                hyperparameters={"source": "odds_snapshots.WIN(final)"},
                metrics=evaluate(market),
                notes=(
                    "확정배당 암시확률 — 사실상 상한 참조, feature 사용 금지. "
                    f"overround 중앙값 {overround['market_overround'].median():.4f} "
                    f"(경주 {overround.height:,}건)"
                ),
            )
        )

    return results


def render_baseline_report(
    results: list[BaselineResult],
    *,
    dataset_version: str,
    as_of_policy: str,
    evaluate_splits: tuple[str, ...],
) -> str:
    """기준 모델 결과를 마크다운 리포트로 렌더링한다."""
    lines = [
        "# M3 기준 모델 리포트",
        "",
        f"- 데이터셋: `{dataset_version}` / 정책 `{as_of_policy}`",
        f"- 분할: train ≤ {SPLIT_BOUNDS['train'][1]}, "
        f"valid {SPLIT_BOUNDS['valid'][0]} ~ {SPLIT_BOUNDS['valid'][1]}, "
        f"test ≥ {SPLIT_BOUNDS['test'][0]} (G1 판정 전 미평가)",
        f"- 평가 split: {', '.join(evaluate_splits)}",
        "",
    ]
    metric_order = (
        "log_loss", "brier", "auc", "ece",
        "top1_hit_rate", "top3_inclusion_rate", "coverage", "n_races",
    )
    for split in evaluate_splits:
        lines.append(f"## {split}")
        lines.append("")
        header = "| 기준 | " + " | ".join(metric_order) + " |"
        lines.append(header)
        lines.append("|" + "---|" * (len(metric_order) + 1))
        for result in results:
            metrics = result.metrics.get(split)
            if metrics is None:
                continue
            cells = [
                f"{metrics[name]:.4f}" if name in metrics else "—"
                for name in metric_order
            ]
            lines.append(f"| {result.baseline_id} | " + " | ".join(cells) + " |")
        lines.append("")
    lines.append("## 기준별 설정")
    lines.append("")
    for result in results:
        params = ", ".join(f"{k}={v}" for k, v in result.hyperparameters.items())
        lines.append(f"- **{result.baseline_id}** ({result.model_type}): {result.notes}")
        if params:
            lines.append(f"  - {params}")
    lines.append("")
    return "\n".join(lines)
