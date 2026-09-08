"""Measure whether a fast outer front-runner gains from clustered inner speed."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import polars as pl

FRONT_THRESHOLD = 0.25
OUTER_THRESHOLD = 2.0 / 3.0
MIN_SECTION_COVERAGE = 2


def build_scenario_rows(frame: pl.DataFrame) -> pl.DataFrame:
    usable = frame.filter(
        pl.col("early_pos_pct_avg5").is_not_null()
        & (pl.col("section_coverage5") >= MIN_SECTION_COVERAGE)
        & pl.col("horse_number_pct").is_not_null()
    )
    output: list[dict[str, object]] = []
    optional = [name for name in ("prob_win", "prob_top3") if name in usable.columns]
    for key, group in usable.group_by("race_id"):
        front = group.filter(pl.col("early_pos_pct_avg5") <= FRONT_THRESHOLD).sort(
            "early_pos_pct_avg5"
        )
        if front.height < 3:
            continue
        fastest = float(front[0, "early_pos_pct_avg5"])
        second = float(front[1, "early_pos_pct_avg5"])
        unique_fastest = second - fastest > 1e-12
        for row in front.iter_rows(named=True):
            early = float(row["early_pos_pct_avg5"])
            is_fastest = unique_fastest and abs(early - fastest) <= 1e-12
            inside = front.filter(
                pl.col("horse_number_pct") < float(row["horse_number_pct"])
            ).height
            target = row.get("early_position_pct_target")
            item: dict[str, object] = {
                "race_id": int(key[0]),
                "race_date_local": str(row["race_date_local"]),
                "meet_code": int(row["meet_code"]),
                "distance_m": int(row["distance_m"]),
                "starters": int(row["starters"]),
                "front_count": front.height,
                "gate_pct": float(row["horse_number_pct"]),
                "inside_front_count": inside,
                "is_unique_fastest": is_fastest,
                "speed_margin": second - fastest if is_fastest else fastest - early,
                "actual_front": (
                    float(float(target) <= FRONT_THRESHOLD) if target is not None else None
                ),
                "win": float(row["win"]),
                "top3": float(row["top3"]),
                "finish_pct": (float(row["finish_position"]) - 1.0)
                / max(float(row["starters"]) - 1.0, 1.0),
            }
            for name in optional:
                item[name] = float(row[name])
            output.append(item)
    return pl.DataFrame(output, infer_schema_length=None).with_columns(
        (pl.col("gate_pct") > OUTER_THRESHOLD).alias("is_outer")
    )


def _values(frame: pl.DataFrame, column: str) -> np.ndarray:
    return frame[column].cast(pl.Float64).to_numpy()


def _mean(frame: pl.DataFrame, column: str) -> float:
    return float(np.nanmean(_values(frame, column)))


def _cluster_arrays(
    frame: pl.DataFrame,
    metric: str,
    race_ids: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    position = {int(race_id): index for index, race_id in enumerate(race_ids)}
    totals = np.zeros(len(race_ids), dtype=float)
    counts = np.zeros(len(race_ids), dtype=float)
    for race_id, value in frame.select("race_id", metric).iter_rows():
        if value is None or not np.isfinite(float(value)):
            continue
        index = position[int(race_id)]
        totals[index] += float(value)
        counts[index] += 1.0
    return totals, counts


def cluster_bootstrap_difference(
    first: pl.DataFrame,
    second: pl.DataFrame,
    metric: str,
    *,
    iterations: int,
    seed: int,
) -> tuple[float, float, float, float]:
    race_ids = np.unique(
        np.concatenate([first["race_id"].to_numpy(), second["race_id"].to_numpy()])
    )
    first_sum, first_n = _cluster_arrays(first, metric, race_ids)
    second_sum, second_n = _cluster_arrays(second, metric, race_ids)
    rng = np.random.default_rng(seed)
    draws: list[np.ndarray] = []
    batch_size = 500
    for start in range(0, iterations, batch_size):
        size = min(batch_size, iterations - start)
        sampled = rng.integers(0, len(race_ids), size=(size, len(race_ids)))
        first_mean = first_sum[sampled].sum(axis=1) / first_n[sampled].sum(axis=1)
        second_mean = second_sum[sampled].sum(axis=1) / second_n[sampled].sum(axis=1)
        draws.append(first_mean - second_mean)
    values = np.concatenate(draws)
    lower, median, upper = np.quantile(values, [0.025, 0.5, 0.975])
    return float(lower), float(median), float(upper), float(np.mean(values > 0.0))


def cluster_bootstrap_mean(
    frame: pl.DataFrame,
    metric: str,
    *,
    iterations: int,
    seed: int,
) -> tuple[float, float, float]:
    race_ids = frame["race_id"].unique().to_numpy()
    totals, counts = _cluster_arrays(frame, metric, race_ids)
    rng = np.random.default_rng(seed)
    draws: list[np.ndarray] = []
    for start in range(0, iterations, 500):
        size = min(500, iterations - start)
        sampled = rng.integers(0, len(race_ids), size=(size, len(race_ids)))
        draws.append(totals[sampled].sum(axis=1) / counts[sampled].sum(axis=1))
    lower, median, upper = np.quantile(np.concatenate(draws), [0.025, 0.5, 0.975])
    return float(lower), float(median), float(upper)


def _pct(value: float) -> str:
    return f"{value:.2%}"


def _summary_row(name: str, frame: pl.DataFrame) -> str:
    return (
        f"| {name} | {frame.height:,} | {_pct(_mean(frame, 'actual_front'))} | "
        f"{_pct(_mean(frame, 'win'))} | {_pct(_mean(frame, 'top3'))} | "
        f"{_pct(_mean(frame, 'finish_pct'))} |"
    )


def render_report(
    history: pl.DataFrame,
    recent: pl.DataFrame,
    *,
    iterations: int,
    seed: int,
) -> str:
    outer_fast = history.filter(
        pl.col("is_outer")
        & (pl.col("inside_front_count") >= 2)
        & pl.col("is_unique_fastest")
    )
    outer_not_fast = history.filter(
        pl.col("is_outer")
        & (pl.col("inside_front_count") >= 2)
        & ~pl.col("is_unique_fastest")
    )
    nonouter_fast = history.filter(~pl.col("is_outer") & pl.col("is_unique_fastest"))
    outer_fast_four = history.filter(
        pl.col("is_outer")
        & (pl.col("inside_front_count") >= 3)
        & (pl.col("front_count") >= 4)
        & pl.col("is_unique_fastest")
    )
    nonouter_fast_four = history.filter(
        ~pl.col("is_outer")
        & (pl.col("front_count") >= 4)
        & pl.col("is_unique_fastest")
    )

    lines = [
        "# 외곽 최속 선행마의 안쪽 혼잡 이용 가능성 통계",
        "",
        "## 정의",
        "",
        "- 경주 전 최근 5경주 S1F 평균 위치가 상위 25%이고 유효 구간기록이 "
        "2회 이상이면 예상 선행마로 분류했다.",
        "- 예상 선행마가 3두 이상인 경주만 분석했다.",
        "- 외곽은 출전두수 대비 게이트 위치가 2/3보다 큰 경우다.",
        "- 외곽 최속 선행마는 안쪽에 예상 선행마가 2두 이상 있고, 예상 S1F가 "
        "선행마 중 단독 1위인 말이다.",
        "- 실제 해당 경주의 S1F는 집단 정의에 사용하지 않고 결과 검증에만 사용했다.",
        "",
        f"장기 표본은 {history['race_date_local'].min()}~{history['race_date_local'].max()}, "
        f"선행 혼잡 경주 {history['race_id'].n_unique():,}개다.",
        "",
        "## 장기 관측 결과",
        "",
        "| 집단 | 출전 | 실제 S1F 선두권 | 승률 | Top3 | 평균 결승 백분위(낮을수록 좋음) |",
        "|---|---:|---:|---:|---:|---:|",
        _summary_row("외곽 최속·안쪽 선행 2두+", outer_fast),
        _summary_row("같은 외곽 조건의 비최속 선행마", outer_not_fast),
        _summary_row("안·중간 게이트 최속 선행마", nonouter_fast),
        _summary_row("선행 4두+·외곽 최속·안쪽 3두+", outer_fast_four),
        _summary_row("선행 4두+·안/중간 최속", nonouter_fast_four),
        "",
        "## 경주 단위 bootstrap 차이",
        "",
        f"{iterations:,}회 재표집한 95% 구간이다. 결승 백분위는 음수일수록 첫 집단이 유리하다.",
        "",
        "| 비교 | 지표 | 관측 차이 | 95% 구간 |",
        "|---|---|---:|---:|",
    ]
    comparisons = [
        ("외곽 최속 - 외곽 비최속", outer_fast, outer_not_fast),
        ("외곽 최속 - 안/중간 최속", outer_fast, nonouter_fast),
        ("선행 4두+ 외곽 최속 - 안/중간 최속", outer_fast_four, nonouter_fast_four),
    ]
    labels = {
        "actual_front": "실제 S1F 선두권",
        "win": "승률",
        "top3": "Top3",
        "finish_pct": "결승 백분위",
    }
    for comparison_index, (name, first, second) in enumerate(comparisons):
        for metric_index, metric in enumerate(labels):
            observed = _mean(first, metric) - _mean(second, metric)
            lower, _, upper, _ = cluster_bootstrap_difference(
                first,
                second,
                metric,
                iterations=iterations,
                seed=seed + comparison_index * 10 + metric_index,
            )
            lines.append(
                f"| {name} | {labels[metric]} | {observed:+.2%}p | "
                f"[{lower:+.2%}p, {upper:+.2%}p] |"
            )

    lines.extend(
        [
            "",
            "## 경마장별 외곽 최속 - 안/중간 최속",
            "",
            "| 경마장 | 외곽/비외곽 표본 | 지표 | 관측 차이 | 95% 구간 |",
            "|---|---:|---|---:|---:|",
        ]
    )
    for meet_index, (meet_code, meet_name) in enumerate(
        [(1, "서울"), (2, "부산경남"), (3, "제주")]
    ):
        first = outer_fast.filter(pl.col("meet_code") == meet_code)
        second = nonouter_fast.filter(pl.col("meet_code") == meet_code)
        sample_text = f"{first.height}/{second.height}"
        for metric_index, metric in enumerate(("actual_front", "win", "top3")):
            observed = _mean(first, metric) - _mean(second, metric)
            lower, _, upper, _ = cluster_bootstrap_difference(
                first,
                second,
                metric,
                iterations=iterations,
                seed=seed + 50 + meet_index * 10 + metric_index,
            )
            lines.append(
                f"| {meet_name} | {sample_text} | {labels[metric]} | "
                f"{observed:+.2%}p | [{lower:+.2%}p, {upper:+.2%}p] |"
            )

    recent_outer_fast = recent.filter(
        pl.col("is_outer")
        & (pl.col("inside_front_count") >= 2)
        & pl.col("is_unique_fastest")
    ).with_columns(
        (pl.col("win") - pl.col("prob_win")).alias("win_residual"),
        (pl.col("top3") - pl.col("prob_top3")).alias("top3_residual"),
    )
    lines.extend(
        [
            "",
            "## 2026 누수 없는 모델 기대확률 대비",
            "",
            f"해당 조건은 {recent_outer_fast.height}건이다. 기존 모델의 확률과 "
            "실제 결과 차이를 계산했다.",
            "",
            "| 지표 | 실제 | 모델 기대 | 잔차 | 잔차 95% 구간 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for index, (actual, expected, residual, label) in enumerate(
        [
            ("win", "prob_win", "win_residual", "승률"),
            ("top3", "prob_top3", "top3_residual", "Top3"),
        ]
    ):
        lower, _, upper = cluster_bootstrap_mean(
            recent_outer_fast,
            residual,
            iterations=iterations,
            seed=seed + 100 + index,
        )
        lines.append(
            f"| {label} | {_pct(_mean(recent_outer_fast, actual))} | "
            f"{_pct(_mean(recent_outer_fast, expected))} | "
            f"{_mean(recent_outer_fast, residual):+.2%}p | "
            f"[{lower:+.2%}p, {upper:+.2%}p] |"
        )

    lines.extend(
        [
            "",
            "## 해석",
            "",
            "- 예상 속도 1위라는 점은 외곽 선행마가 실제 선두권을 잡는 데 큰 도움이 된다.",
            "- 그러나 같은 외곽의 비최속 선행마와 비교한 승률·Top3 개선은 95% 구간이 0을 포함한다.",
            "- 안·중간 게이트의 예상 최속 선행마와 비교하면 외곽 최속마의 실제 "
            "선두권 확보와 최종 성적이 모두 낮다.",
            "- 따라서 현재 표본에서는 바깥의 깨끗한 공간이 외곽 거리 손실을 "
            "넘어서는 독립적인 가점이라는 증거가 없다.",
            "- 이 결과는 무작위 실험이 아닌 관측 통계다. 경마장·거리·기수 작전의 "
            "잔여 교란이 있으므로 인과효과로 단정하지 않는다.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", required=True, type=Path)
    parser.add_argument("--recent", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bootstrap-iterations", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=20260903)
    args = parser.parse_args()

    history = build_scenario_rows(pl.read_parquet(args.history))
    recent_source = pl.read_parquet(args.recent)
    predictions = pl.read_parquet(args.predictions).select(
        "race_id", "race_entry_id", "prob_win", "prob_top3"
    )
    recent = build_scenario_rows(
        recent_source.join(predictions, on=["race_id", "race_entry_id"], how="inner")
    )
    report = render_report(
        history,
        recent,
        iterations=args.bootstrap_iterations,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"report: {args.output}")


if __name__ == "__main__":
    main()
