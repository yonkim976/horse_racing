"""과거 주행 성향으로 추정한 선행 경합이 현재 성적에 미치는 영향을 분석한다.

현재 경주 구간은 사용하지 않는다. 각 말의 직전 최대 5경주 S1F 성향으로 경주 내
강선행형(과거 평균 S1F가 출전두수 상위 25%) 수를 세고, 개별 말 입장에서는
자기 자신을 제외한 강선행 경쟁자 수를 사용한다.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO / "data" / "datasets" / "v2_trials" / "start_minus_30m" / "dataset.parquet"
DEFAULT_OUTPUT = REPO / "data" / "exports" / "pace_competition"
COURSES = {1: "서울", 2: "제주", 3: "부산경남"}
MIN_HISTORY_COVERAGE = 2
MIN_RACE_STYLE_COVERAGE = 0.70
STYLE_ORDER = {"선행": 0, "선입": 1, "중위": 2, "추입": 3}
COMPETITION_ORDER = {"경합없음": 0, "1두경합": 1, "2두이상경합": 2}
PACE_ORDER = {"선행1두이하": 0, "선행2두": 1, "선행3두이상": 2}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_frame(path: Path) -> pl.DataFrame:
    full = pl.read_parquet(path).with_columns(
        pl.col("meet_code").replace_strict(COURSES).alias("course"),
        pl.col("race_date").dt.year().alias("race_year"),
        pl.col("win").sum().over("race_id").alias("winner_slots"),
        pl.col("top3").sum().over("race_id").alias("top3_slots"),
        (
            (pl.col("section_coverage5") >= MIN_HISTORY_COVERAGE)
            & pl.col("style_category").is_not_null()
        ).alias("style_known"),
        (
            pl.col("late_gain_avg5").rank("average").over("style_category")
            / pl.col("late_gain_avg5").count().over("style_category")
        ).alias("closing_quantile"),
    )
    full = full.with_columns(
        pl.col("style_known").sum().over("race_id").alias("known_style_count"),
        (pl.col("style_known") & (pl.col("early_pos_pct_avg5") < 0.25))
        .sum()
        .over("race_id")
        .alias("front_count"),
    ).with_columns(
        (pl.col("known_style_count") / pl.col("starters")).alias("known_style_share"),
        (pl.col("winner_slots") / pl.col("starters")).alias("expected_win"),
        (pl.col("top3_slots") / pl.col("starters")).alias("expected_top3"),
    )
    eligible = full.filter(
        pl.col("style_known")
        & (pl.col("known_style_share") >= MIN_RACE_STYLE_COVERAGE)
    ).with_columns(
        (
            pl.col("front_count")
            - (pl.col("early_pos_pct_avg5") < 0.25).cast(pl.Int64)
        ).alias("other_front_count")
    )
    return eligible.with_columns(
        pl.when(pl.col("other_front_count") == 0)
        .then(pl.lit("경합없음"))
        .when(pl.col("other_front_count") == 1)
        .then(pl.lit("1두경합"))
        .otherwise(pl.lit("2두이상경합"))
        .alias("competition_band"),
        pl.when(pl.col("front_count") <= 1)
        .then(pl.lit("선행1두이하"))
        .when(pl.col("front_count") == 2)
        .then(pl.lit("선행2두"))
        .otherwise(pl.lit("선행3두이상"))
        .alias("race_pace_band"),
        pl.when(pl.col("closing_quantile") <= 1 / 3)
        .then(pl.lit("낮음"))
        .when(pl.col("closing_quantile") <= 2 / 3)
        .then(pl.lit("중간"))
        .otherwise(pl.lit("높음"))
        .alias("closing_strength"),
    )


def aggregate(frame: pl.DataFrame, groups: list[str]) -> pl.DataFrame:
    return (
        frame.group_by(groups)
        .agg(
            pl.col("race_id").n_unique().alias("races"),
            pl.len().alias("starts"),
            pl.col("win").sum().alias("wins"),
            pl.col("expected_win").sum().alias("expected_wins"),
            pl.col("top3").sum().alias("top3"),
            pl.col("expected_top3").sum().alias("expected_top3"),
            pl.col("front_count").mean().alias("mean_front_count"),
            pl.col("known_style_share").mean().alias("mean_known_style_share"),
        )
        .with_columns(
            (100 * pl.col("wins") / pl.col("starts")).alias("win_rate_pct"),
            (100 * pl.col("wins") / pl.col("expected_wins")).alias("win_index"),
            (100 * pl.col("top3") / pl.col("starts")).alias("top3_rate_pct"),
            (100 * pl.col("top3") / pl.col("expected_top3")).alias("top3_index"),
        )
    )


def race_distribution(frame: pl.DataFrame) -> pl.DataFrame:
    races = frame.unique("race_id").select(
        "race_id",
        "race_year",
        "course",
        "distance_m",
        "starters",
        "known_style_count",
        "known_style_share",
        "front_count",
        "race_pace_band",
    )
    return (
        races.group_by(["course", "distance_m", "race_pace_band"])
        .agg(
            pl.len().alias("races"),
            pl.col("starters").mean().alias("mean_starters"),
            pl.col("known_style_share").mean().alias("mean_known_style_share"),
        )
        .sort(["course", "distance_m", "race_pace_band"])
    )


def fmt(value: object, digits: int = 1) -> str:
    return f"{float(value):.{digits}f}"


def write_report(
    path: Path,
    *,
    frame: pl.DataFrame,
    course_competition: pl.DataFrame,
    distance_competition: pl.DataFrame,
    yearly: pl.DataFrame,
    closer_strength: pl.DataFrame,
) -> None:
    eligible_races = frame["race_id"].n_unique()
    lines = [
        "# 선행 경합과 추입 성과 분석",
        "",
        f"표본: **{eligible_races:,}경주 / {frame.height:,}분석 대상 출전**  ",
        f"말 성향 조건: 직전 S1F 이력 **{MIN_HISTORY_COVERAGE}회 이상**  ",
        f"경주 조건: 출전마의 성향 확인 비율 **{MIN_RACE_STYLE_COVERAGE:.0%} 이상**",
        "",
        "강선행형은 과거 평균 S1F가 출전두수 상위 25%인 말이다. "
        "`경합없음/1두경합/2두이상경합`은 자기 자신을 제외한 강선행 경쟁자 수다.",
        "",
        "## 경기장 전체",
        "",
        "| 경기장 | 말 성향 | 선행 경쟁자 | 출전 | 승리지수 | 3위내지수 |",
        "|---|---|---|---:|---:|---:|",
    ]
    course_rows = sorted(
        course_competition.iter_rows(named=True),
        key=lambda row: (
            str(row["course"]),
            STYLE_ORDER[str(row["style_category"])],
            COMPETITION_ORDER[str(row["competition_band"])],
        ),
    )
    for row in course_rows:
        lines.append(
            f"| {row['course']} | {row['style_category']} | {row['competition_band']} | "
            f"{row['starts']} | {fmt(row['win_index'])} | {fmt(row['top3_index'])} |"
        )

    distance_races = (
        frame.group_by(["course", "distance_m"])
        .agg(pl.col("race_id").n_unique().alias("races"))
    )
    race_lookup = {
        (row["course"], row["distance_m"]): int(row["races"])
        for row in distance_races.iter_rows(named=True)
    }
    distance_lookup = {
        (
            row["course"],
            row["distance_m"],
            row["style_category"],
            row["competition_band"],
        ): row
        for row in distance_competition.iter_rows(named=True)
    }
    lines.extend(
        [
            "",
            "## 검증된 추입마만 비교",
            "",
            "과거 추입형 중 순위 향상도가 같은 성향의 상위 1/3인 말만 표시한다.",
            "",
            "| 경기장 | 강선행 경쟁자 | 출전 | 승리지수 | 3위내지수 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    closer_rows = sorted(
        closer_strength.filter(
            (pl.col("style_category") == "추입")
            & (pl.col("closing_strength") == "높음")
        ).iter_rows(named=True),
        key=lambda row: (
            str(row["course"]),
            COMPETITION_ORDER[str(row["competition_band"])],
        ),
    )
    for row in closer_rows:
        lines.append(
            f"| {row['course']} | {row['competition_band']} | {row['starts']} | "
            f"{fmt(row['win_index'])} | {fmt(row['top3_index'])} |"
        )

    lines.extend(
        [
            "",
            "## 거리별 핵심 비교",
            "",
            "경주 100회 이상, 해당 셀 출전 50회 이상만 표시한다.",
            "",
            "| 경기장 | 거리 | 경주 | 선행 무경합 | 선행 2두+경합 | "
            "추입 강선행1두이하 | 추입 강선행3두이상 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for (course, distance), races in sorted(race_lookup.items()):
        if races < 100:
            continue
        keys = [
            (course, distance, "선행", "경합없음"),
            (course, distance, "선행", "2두이상경합"),
            (course, distance, "추입", "경합없음"),
            (course, distance, "추입", "2두이상경합"),
        ]
        values = []
        for key in keys:
            row = distance_lookup.get(key)
            values.append(
                fmt(row["top3_index"]) if row and int(row["starts"]) >= 50 else "—"
            )
        lines.append(
            f"| {course} | {distance}m | {races} | " + " | ".join(values) + " |"
        )

    lines.extend(
        [
            "",
            "## 연도별 재현성",
            "",
            "| 연도 | 경기장 | 말 성향 | 선행 경쟁자 | 출전 | 3위내지수 |",
            "|---:|---|---|---|---:|---:|",
        ]
    )
    yearly_rows = sorted(
        yearly.filter(pl.col("style_category").is_in(["선행", "추입"])).iter_rows(
            named=True
        ),
        key=lambda row: (
            int(row["race_year"]),
            str(row["course"]),
            STYLE_ORDER[str(row["style_category"])],
            COMPETITION_ORDER[str(row["competition_band"])],
        ),
    )
    for row in yearly_rows:
        if int(row["starts"]) < 100:
            continue
        lines.append(
            f"| {row['race_year']} | {row['course']} | {row['style_category']} | "
            f"{row['competition_band']} | {row['starts']} | {fmt(row['top3_index'])} |"
        )

    lines.extend(
        [
            "",
            "## 해석 주의",
            "",
            "경주 전 과거 정보만 사용했지만 관찰 연구이므로 선행 경합의 인과효과를 확정하지 "
            "않는다. 강한 말의 주행 성향, 게이트, 등급, 주로 상태가 함께 작용한다. 모델에는 "
            "선행형 수 자체와 `경기장×거리×자기 성향×다른 선행마 수` 상호작용을 넣고 시간순 "
            "검증으로 증분 성능을 확인해야 한다.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame = load_frame(args.dataset)

    course_competition = aggregate(
        frame, ["course", "style_category", "competition_band"]
    )
    distance_competition = aggregate(
        frame,
        ["course", "distance_m", "style_category", "competition_band"],
    ).sort(["course", "distance_m", "style_category", "competition_band"])
    yearly = aggregate(
        frame,
        ["race_year", "course", "style_category", "competition_band"],
    ).sort(["race_year", "course", "style_category", "competition_band"])
    closer_strength = aggregate(
        frame,
        ["course", "style_category", "closing_strength", "competition_band"],
    ).sort(["course", "style_category", "closing_strength", "competition_band"])
    distribution = race_distribution(frame)

    outputs = {
        "race_pace_distribution.csv": distribution,
        "style_by_competition_course.csv": course_competition,
        "style_by_competition_distance.csv": distance_competition,
        "style_by_competition_year.csv": yearly,
        "style_closing_strength_by_competition.csv": closer_strength,
    }
    for name, result in outputs.items():
        result.write_csv(args.output_dir / name, include_bom=True)

    report_path = args.output_dir / "report.md"
    write_report(
        report_path,
        frame=frame,
        course_competition=course_competition,
        distance_competition=distance_competition,
        yearly=yearly,
        closer_strength=closer_strength,
    )
    print(f"eligible={frame['race_id'].n_unique():,} races / {frame.height:,} rows")
    for name in outputs:
        print(args.output_dir / name)
    print(report_path)


if __name__ == "__main__":
    main()
