"""부담중량과 성적의 연관성을 교란을 구분해 분석한다.

원시 상관, 경주 내 상대중량, 부담방식별 성과, 2025년 이후 사전 능력·성별·연령 등을
통제한 경주 고정효과 선형모형, 같은 말의 유사 조건 연속 출전 비교를 함께 산출한다.
관찰자료이므로 인과효과로 해석하지 않는다.
"""

from __future__ import annotations

import argparse
import math
import sqlite3
from pathlib import Path

import numpy as np
import polars as pl

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "data" / "horse_racing.sqlite3"
DEFAULT_OUTPUT = REPO / "data" / "exports" / "carried_weight"
MIN_STARTERS = 5
RECENT_START = "2025-01-01"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2026-08-29")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def load_frame(conn: sqlite3.Connection, start: str, end: str) -> pl.DataFrame:
    query = """
    SELECT
      r.id AS race_id,
      r.race_date_local AS race_date,
      rc.name_ko AS course,
      r.distance_m,
      r.grade AS grade_raw,
      r.burden_type,
      r.track_condition,
      e.horse_id,
      e.jockey_id,
      e.trainer_id,
      e.gate_number,
      e.carried_weight_kg,
      e.body_weight_kg,
      e.rating,
      h.sex,
      h.birth_date,
      rr.finish_position
    FROM races r
    JOIN racecourses rc ON rc.id = r.racecourse_id
    JOIN race_entries e ON e.race_id = r.id
    JOIN horses h ON h.id = e.horse_id
    JOIN race_results rr ON rr.race_entry_id = e.id
    WHERE r.status = 'completed'
      AND r.race_date_local BETWEEN ? AND ?
      AND e.scratched = 0
      AND rr.disqualified = 0
      AND rr.finish_position BETWEEN 1 AND 89
      AND e.carried_weight_kg IS NOT NULL
    ORDER BY r.race_date_local, r.id, e.horse_number
    """
    frame = pl.read_database(query, conn, execute_options={"parameters": (start, end)})
    frame = frame.with_columns(
        pl.col("race_date").str.to_date(),
        pl.col("birth_date").str.to_date(strict=False),
        pl.len().over("race_id").alias("starters"),
        (pl.col("finish_position") == 1).sum().over("race_id").alias("winner_slots"),
        (pl.col("finish_position") <= 3).sum().over("race_id").alias("top3_slots"),
    ).filter(
        (pl.col("starters") >= MIN_STARTERS)
        & (pl.col("winner_slots") > 0)
        & pl.col("carried_weight_kg").is_between(45, 80)
    )
    burden_from_grade = pl.col("grade_raw").fill_null("")
    burden_raw = pl.col("burden_type").fill_null("")
    frame = frame.with_columns(
        pl.when(burden_raw.str.contains("핸디캡") | burden_from_grade.str.contains("핸디캡"))
        .then(pl.lit("핸디캡"))
        .when(burden_raw.str.contains("마령") | burden_from_grade.str.contains("마령"))
        .then(pl.lit("마령"))
        .when(burden_raw.str.starts_with("별정") | burden_from_grade.str.contains("별정"))
        .then(pl.lit("별정"))
        .otherwise(pl.lit("기타/미상"))
        .alias("burden_group"),
        ((pl.col("starters") - pl.col("finish_position")) / (pl.col("starters") - 1))
        .alias("finish_score"),
        (pl.col("finish_position") == 1).cast(pl.Float64).alias("win"),
        (pl.col("finish_position") <= 3).cast(pl.Float64).alias("top3"),
        (pl.col("winner_slots") / pl.col("starters")).alias("expected_win"),
        (pl.col("top3_slots") / pl.col("starters")).alias("expected_top3"),
        (
            pl.col("carried_weight_kg")
            - pl.col("carried_weight_kg").mean().over("race_id")
        ).alias("relative_weight_kg"),
        (
            pl.col("carried_weight_kg").rank("average").over("race_id")
            / pl.col("starters")
        ).alias("weight_rank_pct"),
        ((pl.col("gate_number") - 1) / (pl.col("starters") - 1)).alias("gate_pct"),
    )
    frame = frame.sort(["race_date", "race_id", "horse_id"])
    history_specs = (
        ("horse_id", 5, 3.0, "horse_form"),
        ("jockey_id", 100, 50.0, "jockey_form"),
        ("trainer_id", 200, 100.0, "trainer_form"),
    )
    for entity, window, prior_count, output in history_specs:
        history_sum = (
            pl.col("finish_score")
            .shift(1)
            .rolling_sum(window_size=window, min_samples=1)
            .over(entity)
        )
        history_count = (
            pl.col("finish_score")
            .shift(1)
            .is_not_null()
            .cast(pl.Int64)
            .rolling_sum(window_size=window, min_samples=1)
            .over(entity)
        )
        frame = frame.with_columns(
            ((history_sum.fill_null(0.0) + 0.5 * prior_count) / (history_count + prior_count))
            .alias(output)
        )
    return frame.with_columns(
        pl.when(pl.col("weight_rank_pct") <= 1 / 3)
        .then(pl.lit("가벼운 1/3"))
        .when(pl.col("weight_rank_pct") <= 2 / 3)
        .then(pl.lit("중간 1/3"))
        .otherwise(pl.lit("무거운 1/3"))
        .alias("weight_tertile"),
        pl.when(pl.col("relative_weight_kg") <= -1.5)
        .then(pl.lit("-1.5kg 이하"))
        .when(pl.col("relative_weight_kg") < -0.5)
        .then(pl.lit("-1.5~-0.5kg"))
        .when(pl.col("relative_weight_kg") <= 0.5)
        .then(pl.lit("-0.5~+0.5kg"))
        .when(pl.col("relative_weight_kg") < 1.5)
        .then(pl.lit("+0.5~+1.5kg"))
        .otherwise(pl.lit("+1.5kg 이상"))
        .alias("relative_weight_band"),
    )


def safe_corr(frame: pl.DataFrame, left: str, right: str) -> float:
    pair = frame.select(left, right).drop_nulls()
    if pair.height < 3:
        return math.nan
    x = pair[left].to_numpy().astype(float)
    y = pair[right].to_numpy().astype(float)
    if np.std(x) == 0 or np.std(y) == 0:
        return math.nan
    return float(np.corrcoef(x, y)[0, 1])


def association_summary(frame: pl.DataFrame) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    course_values: list[str | None] = [None, *sorted(frame["course"].unique().to_list())]
    burden_values: list[str | None] = [None, "핸디캡", "별정", "마령", "기타/미상"]
    for course in course_values:
        for burden in burden_values:
            use = frame
            if course is not None:
                use = use.filter(pl.col("course") == course)
            if burden is not None:
                use = use.filter(pl.col("burden_group") == burden)
            if use.height < 100:
                continue
            rows.append(
                {
                    "course": course or "전체",
                    "burden_group": burden or "전체",
                    "races": use["race_id"].n_unique(),
                    "starts": use.height,
                    "mean_weight_kg": use["carried_weight_kg"].mean(),
                    "raw_corr_weight_finish_score": safe_corr(
                        use, "carried_weight_kg", "finish_score"
                    ),
                    "within_race_corr_weight_finish_score": safe_corr(
                        use, "relative_weight_kg", "finish_score"
                    ),
                    "raw_corr_load_ratio_finish_score": safe_corr(
                        use.filter(pl.col("body_weight_kg") > 0).with_columns(
                            (pl.col("carried_weight_kg") / pl.col("body_weight_kg"))
                            .alias("load_ratio")
                        ),
                        "load_ratio",
                        "finish_score",
                    ),
                }
            )
    return pl.DataFrame(rows).sort(["course", "burden_group"])


def band_summary(frame: pl.DataFrame) -> pl.DataFrame:
    return (
        frame.group_by(["course", "burden_group", "weight_tertile"])
        .agg(
            pl.col("race_id").n_unique().alias("races"),
            pl.len().alias("starts"),
            pl.col("carried_weight_kg").mean().alias("mean_weight_kg"),
            pl.col("relative_weight_kg").mean().alias("mean_relative_weight_kg"),
            pl.col("win").sum().alias("wins"),
            pl.col("expected_win").sum().alias("expected_wins"),
            pl.col("top3").sum().alias("top3"),
            pl.col("expected_top3").sum().alias("expected_top3"),
            pl.col("finish_score").mean().alias("mean_finish_score"),
        )
        .with_columns(
            (100 * pl.col("wins") / pl.col("expected_wins")).alias("win_index"),
            (100 * pl.col("top3") / pl.col("expected_top3")).alias("top3_index"),
        )
        .sort(["course", "burden_group", "weight_tertile"])
    )


def relative_band_summary(frame: pl.DataFrame) -> pl.DataFrame:
    return (
        frame.group_by(["burden_group", "relative_weight_band"])
        .agg(
            pl.col("race_id").n_unique().alias("races"),
            pl.len().alias("starts"),
            pl.col("relative_weight_kg").mean().alias("mean_relative_weight_kg"),
            pl.col("top3").sum().alias("top3"),
            pl.col("expected_top3").sum().alias("expected_top3"),
        )
        .with_columns(
            (100 * pl.col("top3") / pl.col("expected_top3")).alias("top3_index")
        )
        .sort(["burden_group", "mean_relative_weight_kg"])
    )


def weight_rating_diagnostics(frame: pl.DataFrame) -> pl.DataFrame:
    recent = frame.filter(
        (pl.col("race_date") >= pl.lit(RECENT_START).str.to_date())
        & (pl.col("burden_group") == "핸디캡")
        & pl.col("rating").is_not_null()
    ).with_columns(
        (pl.col("rating") - pl.col("rating").mean().over("race_id")).alias(
            "relative_rating"
        )
    )
    rows: list[dict[str, object]] = []
    for course in sorted(recent["course"].unique().to_list()):
        use = recent.filter(pl.col("course") == course)
        weight = use["relative_weight_kg"].to_numpy().astype(float)
        rating = use["relative_rating"].to_numpy().astype(float)
        slope = float((weight @ rating) / (rating @ rating))
        residual = weight - slope * rating
        correlation = float(np.corrcoef(weight, rating)[0, 1])
        rows.append(
            {
                "course": course,
                "races": use["race_id"].n_unique(),
                "starts": use.height,
                "corr_relative_weight_rating": correlation,
                "relative_weight_sd_kg": float(np.std(weight)),
                "weight_residual_sd_after_rating_kg": float(np.std(residual)),
                "rating_only_r_squared": correlation**2,
            }
        )
    return pl.DataFrame(rows).sort("course")


def cluster_ols(
    frame: pl.DataFrame,
    outcome: str,
    predictors: list[str],
) -> tuple[np.ndarray, np.ndarray, float]:
    use = frame.select("race_id", outcome, *predictors).drop_nulls()
    matrix = use.select(predictors).to_numpy().astype(float)
    target = use[outcome].to_numpy().astype(float)
    cluster = use["race_id"].to_numpy()
    beta, *_ = np.linalg.lstsq(matrix, target, rcond=None)
    residual = target - matrix @ beta
    bread = np.linalg.pinv(matrix.T @ matrix)
    _, inverse = np.unique(cluster, return_inverse=True)
    group_count = int(inverse.max()) + 1
    scores = np.zeros((group_count, len(predictors)), dtype=float)
    np.add.at(scores, inverse, matrix * residual[:, None])
    meat = scores.T @ scores
    correction = group_count / max(1, group_count - 1)
    covariance = correction * bread @ meat @ bread
    se = np.sqrt(np.clip(np.diag(covariance), 0, None))
    return beta, se, float(np.linalg.cond(matrix.T @ matrix))


def controlled_models(frame: pl.DataFrame) -> pl.DataFrame:
    recent = frame.filter(pl.col("race_date") >= pl.lit(RECENT_START).str.to_date()).filter(
        pl.col("rating").is_not_null()
        & pl.col("body_weight_kg").is_between(150, 700)
        & pl.col("birth_date").is_not_null()
        & pl.col("gate_pct").is_not_null()
    )
    recent = recent.with_columns(
        ((pl.col("race_date") - pl.col("birth_date")).dt.total_days() / 365.25).alias(
            "age_years"
        ),
        (pl.col("sex") == "암").cast(pl.Float64).alias("is_female"),
        (pl.col("sex") == "거").cast(pl.Float64).alias("is_gelding"),
    )
    center_columns = [
        "finish_score",
        "top3",
        "carried_weight_kg",
        "rating",
        "gate_pct",
        "body_weight_kg",
        "age_years",
        "is_female",
        "is_gelding",
        "horse_form",
        "jockey_form",
        "trainer_form",
    ]
    recent = recent.with_columns(
        *[
            (pl.col(name) - pl.col(name).mean().over("race_id")).alias(f"c_{name}")
            for name in center_columns
        ]
    )
    recent = recent.with_columns(
        (pl.col("c_rating") / 10).alias("s_rating"),
        (pl.col("c_gate_pct") / 0.25).alias("s_gate_pct"),
        (pl.col("c_body_weight_kg") / 50).alias("s_body_weight_kg"),
        (pl.col("c_age_years") / 2).alias("s_age_years"),
        (pl.col("c_horse_form") / 0.10).alias("s_horse_form"),
        (pl.col("c_jockey_form") / 0.05).alias("s_jockey_form"),
        (pl.col("c_trainer_form") / 0.05).alias("s_trainer_form"),
    )
    controls = [
        "c_carried_weight_kg",
        "s_rating",
        "s_gate_pct",
        "s_body_weight_kg",
        "s_age_years",
        "c_is_female",
        "c_is_gelding",
        "s_horse_form",
        "s_jockey_form",
        "s_trainer_form",
    ]
    rows: list[dict[str, object]] = []
    course_values: list[str] = ["전체", *sorted(recent["course"].unique().to_list())]
    burden_values = ["전체", "핸디캡", "별정", "마령"]
    samples: list[tuple[str, pl.DataFrame]] = [("2025+ 전체", recent)]
    jeju = recent.filter(pl.col("course") == "제주")
    samples.extend(
        [
            ("제주 리셋 전", jeju.filter(pl.col("race_date") < pl.date(2025, 12, 28))),
            ("제주 리셋 후", jeju.filter(pl.col("race_date") >= pl.date(2025, 12, 28))),
        ]
    )
    for sample_period, sample in samples:
        sample_courses = course_values if sample_period == "2025+ 전체" else ["제주"]
        for course in sample_courses:
            for burden in burden_values:
                use = sample
                if course != "전체":
                    use = use.filter(pl.col("course") == course)
                if burden != "전체":
                    use = use.filter(pl.col("burden_group") == burden)
                if use.height < 500 or use["race_id"].n_unique() < 50:
                    continue
                for outcome, scale in (("c_finish_score", 1.0), ("c_top3", 100.0)):
                    raw_beta, raw_se, raw_condition = cluster_ols(
                        use, outcome, ["c_carried_weight_kg"]
                    )
                    adj_beta, adj_se, adj_condition = cluster_ols(use, outcome, controls)
                    rows.append(
                        {
                            "sample_period": sample_period,
                            "course": course,
                            "distance_m": None,
                            "burden_group": burden,
                            "outcome": "finish_score_per_kg"
                            if outcome == "c_finish_score"
                            else "top3_percentage_points_per_kg",
                            "races": use["race_id"].n_unique(),
                            "starts": use.height,
                            "unadjusted_coef": scale * raw_beta[0],
                            "unadjusted_se_cluster": scale * raw_se[0],
                            "adjusted_coef": scale * adj_beta[0],
                            "adjusted_se_cluster": scale * adj_se[0],
                            "adjusted_ci_low": scale * (adj_beta[0] - 1.96 * adj_se[0]),
                            "adjusted_ci_high": scale * (adj_beta[0] + 1.96 * adj_se[0]),
                            "unadjusted_condition_number": raw_condition,
                            "adjusted_condition_number": adj_condition,
                        }
                    )
    for course in sorted(recent["course"].unique().to_list()):
        distances = sorted(
            recent.filter(pl.col("course") == course)["distance_m"].unique().to_list()
        )
        for distance_m in distances:
            use = recent.filter(
                (pl.col("course") == course)
                & (pl.col("distance_m") == distance_m)
                & (pl.col("burden_group") == "핸디캡")
            )
            if use.height < 500 or use["race_id"].n_unique() < 50:
                continue
            for outcome, scale in (("c_finish_score", 1.0), ("c_top3", 100.0)):
                raw_beta, raw_se, raw_condition = cluster_ols(
                    use, outcome, ["c_carried_weight_kg"]
                )
                adj_beta, adj_se, adj_condition = cluster_ols(use, outcome, controls)
                rows.append(
                    {
                        "sample_period": "2025+ 거리별",
                        "course": course,
                        "distance_m": distance_m,
                        "burden_group": "핸디캡",
                        "outcome": "finish_score_per_kg"
                        if outcome == "c_finish_score"
                        else "top3_percentage_points_per_kg",
                        "races": use["race_id"].n_unique(),
                        "starts": use.height,
                        "unadjusted_coef": scale * raw_beta[0],
                        "unadjusted_se_cluster": scale * raw_se[0],
                        "adjusted_coef": scale * adj_beta[0],
                        "adjusted_se_cluster": scale * adj_se[0],
                        "adjusted_ci_low": scale * (adj_beta[0] - 1.96 * adj_se[0]),
                        "adjusted_ci_high": scale * (adj_beta[0] + 1.96 * adj_se[0]),
                        "unadjusted_condition_number": raw_condition,
                        "adjusted_condition_number": adj_condition,
                    }
                )
    return pl.DataFrame(rows).sort(
        ["outcome", "sample_period", "course", "distance_m", "burden_group"]
    )


def consecutive_horse_summary(frame: pl.DataFrame) -> pl.DataFrame:
    ordered = frame.sort(["horse_id", "race_date", "race_id"]).with_columns(
        pl.col("race_date").shift(1).over("horse_id").alias("prev_date"),
        pl.col("course").shift(1).over("horse_id").alias("prev_course"),
        pl.col("distance_m").shift(1).over("horse_id").alias("prev_distance_m"),
        pl.col("grade_raw").shift(1).over("horse_id").alias("prev_grade_raw"),
        pl.col("burden_group").shift(1).over("horse_id").alias("prev_burden_group"),
        pl.col("carried_weight_kg").shift(1).over("horse_id").alias("prev_weight_kg"),
        pl.col("finish_score").shift(1).over("horse_id").alias("prev_finish_score"),
    )
    pairs = ordered.with_columns(
        (pl.col("race_date") - pl.col("prev_date")).dt.total_days().alias("days_since"),
        (pl.col("carried_weight_kg") - pl.col("prev_weight_kg")).alias("delta_weight_kg"),
        (pl.col("finish_score") - pl.col("prev_finish_score")).alias("delta_finish_score"),
    ).filter(
        pl.col("days_since").is_between(1, 180)
        & (pl.col("course") == pl.col("prev_course"))
        & (pl.col("distance_m") == pl.col("prev_distance_m"))
        & (pl.col("grade_raw").fill_null("(null)") == pl.col("prev_grade_raw").fill_null("(null)"))
        & (pl.col("burden_group") == pl.col("prev_burden_group"))
    )
    pairs = pairs.with_columns(
        pl.when(pl.col("delta_weight_kg") <= -1.0)
        .then(pl.lit("1kg 이상 감소"))
        .when(pl.col("delta_weight_kg") >= 1.0)
        .then(pl.lit("1kg 이상 증가"))
        .otherwise(pl.lit("±1kg 미만"))
        .alias("delta_weight_band")
    )
    grouped = (
        pairs.group_by(["course", "burden_group", "delta_weight_band"])
        .agg(
            pl.len().alias("pairs"),
            pl.col("delta_weight_kg").mean().alias("mean_delta_weight_kg"),
            pl.col("delta_finish_score").mean().alias("mean_delta_finish_score"),
        )
        .sort(["course", "burden_group", "mean_delta_weight_kg"])
    )
    overall = pl.DataFrame(
        [
            {
                "course": "전체",
                "burden_group": "전체",
                "delta_weight_band": "연속값 상관",
                "pairs": pairs.height,
                "mean_delta_weight_kg": pairs["delta_weight_kg"].mean(),
                "mean_delta_finish_score": pairs["delta_finish_score"].mean(),
                "corr_delta_weight_delta_finish_score": safe_corr(
                    pairs, "delta_weight_kg", "delta_finish_score"
                ),
            }
        ]
    )
    grouped = grouped.with_columns(pl.lit(None, dtype=pl.Float64).alias(
        "corr_delta_weight_delta_finish_score"
    ))
    return pl.concat([overall, grouped], how="diagonal_relaxed")


def fmt(value: object, digits: int = 3) -> str:
    if value is None or not math.isfinite(float(value)):
        return "—"
    return f"{float(value):.{digits}f}"


def write_report(
    path: Path,
    *,
    start: str,
    end: str,
    frame: pl.DataFrame,
    associations: pl.DataFrame,
    bands: pl.DataFrame,
    models: pl.DataFrame,
    pairs: pl.DataFrame,
    diagnostics: pl.DataFrame,
) -> None:
    overall = associations.filter(
        (pl.col("course") == "전체") & (pl.col("burden_group") == "전체")
    ).row(0, named=True)
    model_rows = models.filter(
        (pl.col("sample_period") == "2025+ 전체")
        & (pl.col("outcome") == "top3_percentage_points_per_kg")
        & (pl.col("course") != "전체")
        & (pl.col("burden_group").is_in(["핸디캡", "별정", "마령"]))
    ).iter_rows(named=True)
    pair_overall = pairs.row(0, named=True)
    distance_rows = models.filter(
        (pl.col("sample_period") == "2025+ 거리별")
        & (pl.col("outcome") == "top3_percentage_points_per_kg")
    ).iter_rows(named=True)
    jeju_reset_rows = models.filter(
        pl.col("sample_period").is_in(["제주 리셋 전", "제주 리셋 후"])
        & (pl.col("outcome") == "top3_percentage_points_per_kg")
        & (pl.col("burden_group") == "핸디캡")
    ).iter_rows(named=True)
    lines = [
        "# 부담중량과 경주 성적의 연관성",
        "",
        f"분석 기간: **{start}~{end}**  ",
        f"표본: **{frame['race_id'].n_unique():,}경주 / {frame.height:,}정상 완주 출전**",
        "",
        "## 결론",
        "",
        "부담중량과 성적에는 연관성이 있지만, 원시 수치를 중량의 순수 효과로 해석할 수 없다. "
        "핸디캡 경주에서는 강한 말이 더 무거운 중량을 받으므로 능력 배정 효과가 먼저 보인다. "
        "서울·부산경남은 능력 변수를 통제하면 중량의 독립 연관성이 거의 남지 않았다. "
        "제주는 음의 계수가 나왔지만 중량과 레이팅이 사실상 같은 신호여서 인과효과로 "
        "판정할 수 없다.",
        "",
        "## 전체 원시 연관성",
        "",
        "- 절대 부담중량과 정규화 착순점수 상관: "
        f"**{fmt(overall['raw_corr_weight_finish_score'])}**",
        f"- 경주 평균 대비 상대중량과 착순점수 상관: "
        f"**{fmt(overall['within_race_corr_weight_finish_score'])}**",
        f"- 같은 말·경기장·거리·등급·부담방식 연속 출전에서 중량 변화와 성적 변화 상관: "
        f"**{fmt(pair_overall['corr_delta_weight_delta_finish_score'])}** "
        f"({int(pair_overall['pairs']):,}쌍)",
        "",
        "착순점수는 1착=1, 최하위=0으로 출전두수를 보정했다. 양의 상관은 무거운 말의 성적이 "
        "더 좋았다는 뜻이고, 음의 상관은 더 나빴다는 뜻이다.",
        "",
        "## 핸디캡 중량과 레이팅의 중복",
        "",
        "| 경기장 | 출전 | 경주 내 중량·레이팅 상관 | 레이팅 제거 후 중량 표준편차 |",
        "|---|---:|---:|---:|",
    ]
    for row in diagnostics.iter_rows(named=True):
        lines.append(
            f"| {row['course']} | {int(row['starts']):,} | "
            f"{fmt(row['corr_relative_weight_rating'])} | "
            f"{fmt(row['weight_residual_sd_after_rating_kg'])}kg |"
        )
    lines.extend(
        [
            "",
            "제주는 경주 내 부담중량과 레이팅 상관이 거의 1이고, 레이팅으로 설명되지 않는 "
            "중량 변동이 0.34kg 정도뿐이다. 따라서 아래 제주 통제계수는 작은 잔여 변동에서 "
            "추정된 값으로 서울·부산보다 식별이 약하다.",
            "",
            "## 부담방식별 경주 내 상대중량",
            "",
            "| 경기장 | 부담방식 | 출전 | 원시 상관 | 경주 내 상관 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in associations.filter(
        (pl.col("course") != "전체") & (pl.col("burden_group") != "전체")
    ).iter_rows(named=True):
        lines.append(
            f"| {row['course']} | {row['burden_group']} | {int(row['starts']):,} | "
            f"{fmt(row['raw_corr_weight_finish_score'])} | "
            f"{fmt(row['within_race_corr_weight_finish_score'])} |"
        )
    lines.extend(
        [
            "",
            "## 2025년 이후 통제 모형",
            "",
            "계수는 같은 경주 안에서 부담중량이 1kg 높을 때의 3위 내 확률 차이(%p)다. "
            "레이팅, 최근 말·기수·조교사 성적, 게이트 위치, 마체중, 연령, 성별과 "
            "경주 고정효과를 통제했다.",
            "",
            "| 경기장 | 부담방식 | 경주 | 출전 | 통제 전 %p/kg | 통제 후 %p/kg | 95% CI |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in model_rows:
        lines.append(
            f"| {row['course']} | {row['burden_group']} | {int(row['races']):,} | "
            f"{int(row['starts']):,} | {fmt(row['unadjusted_coef'], 2)} | "
            f"{fmt(row['adjusted_coef'], 2)} | "
            f"[{fmt(row['adjusted_ci_low'], 2)}, {fmt(row['adjusted_ci_high'], 2)}] |"
        )
    lines.extend(
        [
            "",
            "### 제주 레이팅 리셋 전후 핸디캡",
            "",
            "| 구간 | 경주 | 출전 | 통제 후 %p/kg | 95% CI |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in jeju_reset_rows:
        lines.append(
            f"| {row['sample_period']} | {int(row['races']):,} | {int(row['starts']):,} | "
            f"{fmt(row['adjusted_coef'], 2)} | "
            f"[{fmt(row['adjusted_ci_low'], 2)}, {fmt(row['adjusted_ci_high'], 2)}] |"
        )
    lines.extend(
        [
            "",
            "### 경기장·거리별 핸디캡",
            "",
            "표본 50경주·500출전 이상인 거리만 표시한다.",
            "",
            "| 경기장 | 거리 | 경주 | 출전 | 통제 후 %p/kg | 95% CI |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in distance_rows:
        lines.append(
            f"| {row['course']} | {int(row['distance_m'])}m | {int(row['races']):,} | "
            f"{int(row['starts']):,} | {fmt(row['adjusted_coef'], 2)} | "
            f"[{fmt(row['adjusted_ci_low'], 2)}, {fmt(row['adjusted_ci_high'], 2)}] |"
        )
    lines.extend(
        [
            "",
            "## 해석 주의",
            "",
            "- 핸디캡 중량은 능력·레이팅에 따라 배정되므로 단순 상관은 중량 페널티가 아니라 "
            "강한 말 선별을 주로 반영한다.",
            "- 별정·마령 차이는 성별·연령·수습기수 감량과 연결되므로 중량만 "
            "독립적으로 바뀌지 않는다.",
            "- 레이팅과 중량이 강하게 연결된 핸디캡 경주에서는 통제 후 계수가 불안정할 수 있다. "
            "신뢰구간과 표본을 함께 본다.",
            "- 특히 제주의 중량·레이팅 상관은 0.992이므로 음의 통제계수를 곧바로 1kg의 "
            "인과 페널티로 사용하지 않는다.",
            "- 같은 말 연속 출전 비교도 직전 성적에 따른 중량·등급 조정과 평균회귀가 남아 있다.",
            "- 실제 예측 feature는 절대중량, 경주 평균 대비 중량, 체중 대비 부담비율, "
            "직전 대비 증감, 부담방식·성별·연령 상호작용으로 나눈다.",
            "",
            "## 산출물",
            "",
            "- `association_summary.csv`: 원시·경주 내 상관",
            "- `weight_tertile_summary.csv`: 경주 내 가벼운/중간/무거운 1/3 성과",
            "- `relative_weight_band_summary.csv`: 경주 평균 대비 kg 구간 성과",
            "- `controlled_models_2025plus.csv`: 경주 고정효과 통제모형",
            "- `weight_rating_diagnostics.csv`: 핸디캡 중량과 레이팅의 중복 정도",
            "- `consecutive_horse_pairs.csv`: 같은 말 유사 조건 연속 출전 비교",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with open_readonly(args.db) as conn:
        frame = load_frame(conn, args.start, args.end)
    associations = association_summary(frame)
    bands = band_summary(frame)
    relative_bands = relative_band_summary(frame)
    models = controlled_models(frame)
    pairs = consecutive_horse_summary(frame)
    diagnostics = weight_rating_diagnostics(frame)
    associations.write_csv(args.output_dir / "association_summary.csv")
    bands.write_csv(args.output_dir / "weight_tertile_summary.csv")
    relative_bands.write_csv(args.output_dir / "relative_weight_band_summary.csv")
    models.write_csv(args.output_dir / "controlled_models_2025plus.csv")
    diagnostics.write_csv(args.output_dir / "weight_rating_diagnostics.csv")
    pairs.write_csv(args.output_dir / "consecutive_horse_pairs.csv")
    write_report(
        args.output_dir / "report.md",
        start=args.start,
        end=args.end,
        frame=frame,
        associations=associations,
        bands=bands,
        models=models,
        pairs=pairs,
        diagnostics=diagnostics,
    )
    print(f"wrote {args.output_dir}")


if __name__ == "__main__":
    main()
