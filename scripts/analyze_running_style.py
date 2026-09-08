"""경기장·거리별 초반 위치와 추입 성향의 성과를 분석한다.

두 관점을 분리한다.
1) 현재 경주의 S1F 위치 → 최종 착순: 코스 전개에 대한 사후 설명용
2) 직전 최대 5경주의 주행 성향 → 현재 착순: 실제 예측에 사용할 수 있는 사전 정보
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import polars as pl

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "data" / "horse_racing.sqlite3"
DEFAULT_DATASET = REPO / "data" / "datasets" / "v2_trials" / "start_minus_30m" / "dataset.parquet"
DEFAULT_OUTPUT = REPO / "data" / "exports" / "running_style"
COURSES = {1: "서울", 2: "제주", 3: "부산경남"}
STYLE_ORDER = {"선행": 0, "선입": 1, "중위": 2, "추입": 3}
CURRENT_STYLE_ORDER = {"초반앞": 0, "초반선입": 1, "초반중위": 2, "초반뒤": 3}
MIN_STARTERS = 5
MIN_HISTORY_COVERAGE = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--start", default="2025-01-03")
    parser.add_argument("--end", default="2026-08-23")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def rows_to_frame(rows: list[sqlite3.Row]) -> pl.DataFrame:
    return pl.DataFrame([dict(row) for row in rows], infer_schema_length=None)


def load_current_flow(conn: sqlite3.Connection, start: str, end: str) -> pl.DataFrame:
    """S1F가 정상 착순마 전원에게 있는 완전 경주만 반환한다."""
    rows = conn.execute(
        """
        WITH normal AS (
          SELECT
            r.id AS race_id,
            r.race_date_local,
            CAST(strftime('%Y', r.race_date_local) AS INTEGER) AS race_year,
            rc.name_ko AS course,
            r.distance_m,
            e.id AS race_entry_id,
            rr.finish_position,
            s.position AS s1f_position
          FROM races r
          JOIN racecourses rc ON rc.id = r.racecourse_id
          JOIN race_entries e ON e.race_id = r.id
          JOIN race_results rr ON rr.race_entry_id = e.id
          LEFT JOIN race_section_results s
            ON s.race_entry_id = e.id AND s.section_code = 'S1F'
          WHERE r.status = 'completed'
            AND r.race_date_local BETWEEN ? AND ?
            AND e.scratched = 0
            AND rr.finish_position BETWEEN 1 AND 89
        ),
        race_stats AS (
          SELECT
            race_id,
            COUNT(*) AS starters,
            SUM(s1f_position IS NOT NULL) AS s1f_covered,
            SUM(finish_position = 1) AS winner_slots,
            SUM(finish_position <= 3) AS top3_slots
          FROM normal
          GROUP BY race_id
          HAVING COUNT(*) >= ? AND SUM(finish_position = 1) > 0
        )
        SELECT n.*, s.starters, s.winner_slots, s.top3_slots
        FROM normal n
        JOIN race_stats s USING (race_id)
        WHERE s.s1f_covered = s.starters
        ORDER BY n.race_date_local, n.course, n.race_id, n.s1f_position
        """,
        (start, end, MIN_STARTERS),
    ).fetchall()
    frame = rows_to_frame(rows)
    early_pct = pl.col("s1f_position") / pl.col("starters")
    return frame.with_columns(
        early_pct.alias("early_position_pct"),
        (pl.col("s1f_position") - pl.col("finish_position")).alias("late_gain"),
        pl.when(early_pct < 0.35)
        .then(pl.lit("초반앞"))
        .when(early_pct < 0.55)
        .then(pl.lit("초반선입"))
        .when(early_pct < 0.75)
        .then(pl.lit("초반중위"))
        .otherwise(pl.lit("초반뒤"))
        .alias("current_early_group"),
        (pl.col("winner_slots") / pl.col("starters")).alias("expected_win"),
        (pl.col("top3_slots") / pl.col("starters")).alias("expected_top3"),
        (pl.col("finish_position") == 1).cast(pl.Int64).alias("win"),
        (pl.col("finish_position") <= 3).cast(pl.Int64).alias("top3"),
    )


def aggregate_performance(frame: pl.DataFrame, groups: list[str]) -> pl.DataFrame:
    return (
        frame.group_by(groups)
        .agg(
            pl.col("race_id").n_unique().alias("races"),
            pl.len().alias("starts"),
            pl.col("win").sum().alias("wins"),
            pl.col("expected_win").sum().alias("expected_wins"),
            pl.col("top3").sum().alias("top3"),
            pl.col("expected_top3").sum().alias("expected_top3"),
            pl.col("late_gain").mean().alias("mean_late_gain"),
        )
        .with_columns(
            (100 * pl.col("wins") / pl.col("starts")).alias("win_rate_pct"),
            (100 * pl.col("wins") / pl.col("expected_wins")).alias("win_index"),
            (100 * pl.col("top3") / pl.col("starts")).alias("top3_rate_pct"),
            (100 * pl.col("top3") / pl.col("expected_top3")).alias("top3_index"),
        )
    )


def current_race_summary(frame: pl.DataFrame, groups: list[str]) -> pl.DataFrame:
    return (
        frame.group_by(groups)
        .agg(
            pl.col("race_id").n_unique().alias("races"),
            pl.len().alias("starts"),
            pl.col("win").sum().alias("winner_slots"),
            (
                100
                * ((pl.col("win") == 1) & (pl.col("s1f_position") <= 3)).sum()
                / pl.col("win").sum()
            ).alias("winner_s1f_top3_pct"),
            (
                100
                * ((pl.col("win") == 1) & (pl.col("early_position_pct") > 0.5)).sum()
                / pl.col("win").sum()
            ).alias("winner_from_back_half_pct"),
            (
                100
                * ((pl.col("top3") == 1) & (pl.col("s1f_position") <= 3)).sum()
                / pl.col("top3").sum()
            ).alias("top3_already_s1f_top3_pct"),
            pl.col("late_gain").filter(pl.col("win") == 1).mean().alias("winner_mean_late_gain"),
        )
        .sort(groups)
    )


def load_past_style(dataset_path: Path) -> pl.DataFrame:
    # 슬롯 수는 이력이 부족해 분석에서 제외되는 말까지 포함한 원래 경주에서 계산한다.
    frame = pl.read_parquet(dataset_path).with_columns(
        pl.col("win").sum().over("race_id").alias("winner_slots"),
        pl.col("top3").sum().over("race_id").alias("top3_slots"),
    ).filter(
        (pl.col("section_coverage5") >= MIN_HISTORY_COVERAGE)
        & pl.col("style_category").is_not_null()
        & pl.col("late_gain_avg5").is_not_null()
    )
    return frame.with_columns(
        pl.col("meet_code").replace_strict(COURSES).alias("course"),
        pl.col("race_date").dt.year().alias("race_year"),
    ).with_columns(
        (pl.col("winner_slots") / pl.col("starters")).alias("expected_win"),
        (pl.col("top3_slots") / pl.col("starters")).alias("expected_top3"),
        # 같은 초반 성향 안에서 과거 순위 향상도가 어느 정도인지 3등분한다.
        (
            pl.col("late_gain_avg5").rank("average").over("style_category")
            / pl.len().over("style_category")
        ).alias("closing_quantile"),
    ).with_columns(
        pl.when(pl.col("closing_quantile") <= 1 / 3)
        .then(pl.lit("낮음"))
        .when(pl.col("closing_quantile") <= 2 / 3)
        .then(pl.lit("중간"))
        .otherwise(pl.lit("높음"))
        .alias("closing_strength")
    )


def aggregate_past_style(frame: pl.DataFrame, groups: list[str]) -> pl.DataFrame:
    return (
        frame.group_by(groups)
        .agg(
            pl.col("race_id").n_unique().alias("races"),
            pl.len().alias("starts"),
            pl.col("win").sum().alias("wins"),
            pl.col("expected_win").sum().alias("expected_wins"),
            pl.col("top3").sum().alias("top3"),
            pl.col("expected_top3").sum().alias("expected_top3"),
            pl.col("early_pos_pct_avg5").mean().alias("mean_past_early_position_pct"),
            pl.col("late_gain_avg5").mean().alias("mean_past_late_gain"),
            pl.col("section_coverage5").mean().alias("mean_history_coverage"),
        )
        .with_columns(
            (100 * pl.col("wins") / pl.col("starts")).alias("win_rate_pct"),
            (100 * pl.col("wins") / pl.col("expected_wins")).alias("win_index"),
            (100 * pl.col("top3") / pl.col("starts")).alias("top3_rate_pct"),
            (100 * pl.col("top3") / pl.col("expected_top3")).alias("top3_index"),
        )
    )


def fmt(value: object, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def write_report(
    path: Path,
    *,
    start: str,
    end: str,
    current: pl.DataFrame,
    flow_course: pl.DataFrame,
    flow_distance: pl.DataFrame,
    current_groups_course: pl.DataFrame,
    past_style_course: pl.DataFrame,
    past_style_distance: pl.DataFrame,
    closing_course: pl.DataFrame,
) -> None:
    lines = [
        "# 경기장·거리별 초반 위치와 추입 성향 분석",
        "",
        f"분석 기간: **{start}~{end}**  ",
        f"현재 경주 S1F 완전 표본: **{current['race_id'].n_unique():,}경주 / "
        f"{current.height:,}출전**  ",
        f"사전 성향 최소 이력: **직전 경주 S1F {MIN_HISTORY_COVERAGE}회 이상**",
        "",
        "## 두 분석의 차이",
        "",
        "- 현재 경주 S1F 분석은 코스 전개를 설명하지만 경주 전에 알 수 없는 사후 정보다.",
        "- 과거 주행 성향 분석은 현재 경주를 제외한 직전 최대 5경주만 사용해 예측 특성으로 "
        "활용할 수 있다.",
        "",
        "## 현재 경주 전개: 경기장 전체",
        "",
        "| 경기장 | 경주 | 우승마가 S1F 3위내 | 후방 절반 출발 우승마 | "
        "최종 3위내가 S1F 3위내 | 우승마 평균 추입 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in flow_course.iter_rows(named=True):
        lines.append(
            f"| {row['course']} | {row['races']} | {fmt(row['winner_s1f_top3_pct'])}% | "
            f"{fmt(row['winner_from_back_half_pct'])}% | "
            f"{fmt(row['top3_already_s1f_top3_pct'])}% | "
            f"{fmt(row['winner_mean_late_gain'], 2)}칸 |"
        )

    lines.extend(
        [
            "",
            "## 현재 경주 초반 위치별 성과",
            "",
            "| 경기장 | 초반 위치 | 출전 | 승리지수 | 3위내지수 | 평균 순위변화 |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    current_group_rows = sorted(
        current_groups_course.iter_rows(named=True),
        key=lambda row: (str(row["course"]), CURRENT_STYLE_ORDER[str(row["current_early_group"])]),
    )
    for row in current_group_rows:
        lines.append(
            f"| {row['course']} | {row['current_early_group']} | {row['starts']} | "
            f"{fmt(row['win_index'])} | {fmt(row['top3_index'])} | "
            f"{fmt(row['mean_late_gain'], 2)} |"
        )

    lines.extend(
        [
            "",
            "## 경주 전 사용 가능한 과거 성향",
            "",
            "| 경기장 | 과거 성향 | 출전 | 승률 | 승리지수 | 3위내율 | 3위내지수 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    past_rows = sorted(
        past_style_course.iter_rows(named=True),
        key=lambda row: (str(row["course"]), STYLE_ORDER[str(row["style_category"])]),
    )
    for row in past_rows:
        lines.append(
            f"| {row['course']} | {row['style_category']} | {row['starts']} | "
            f"{fmt(row['win_rate_pct'])}% | {fmt(row['win_index'])} | "
            f"{fmt(row['top3_rate_pct'])}% | {fmt(row['top3_index'])} |"
        )

    # 거리별 표는 표본이 충분한 거리만 출력한다.
    distance_races = {
        (row["course"], row["distance_m"]): row["races"]
        for row in flow_distance.iter_rows(named=True)
    }
    style_lookup = {
        (row["course"], row["distance_m"], row["style_category"]): row
        for row in past_style_distance.iter_rows(named=True)
    }
    lines.extend(
        [
            "",
            "## 거리별 과거 성향의 3위내지수",
            "",
            "경주 100회 이상 거리만 표시했다.",
            "",
            "| 경기장 | 거리 | 경주 | 선행 | 선입 | 중위 | 추입 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for key, races in sorted(distance_races.items()):
        if int(races) < 100:
            continue
        course, distance = key
        indices = []
        for style in ("선행", "선입", "중위", "추입"):
            row = style_lookup.get((course, distance, style))
            indices.append(fmt(row["top3_index"]) if row and int(row["starts"]) >= 50 else "—")
        lines.append(
            f"| {course} | {distance}m | {races} | " + " | ".join(indices) + " |"
        )

    lines.extend(
        [
            "",
            "## 같은 초반 성향 안에서 과거 추입력 비교",
            "",
            "과거 순위 향상도를 각 성향 내부에서 낮음·중간·높음으로 3등분했다.",
            "",
            "| 경기장 | 성향 | 추입력 | 출전 | 승리지수 | 3위내지수 |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    closing_rows = sorted(
        closing_course.iter_rows(named=True),
        key=lambda row: (
            str(row["course"]),
            STYLE_ORDER[str(row["style_category"])],
            {"낮음": 0, "중간": 1, "높음": 2}[str(row["closing_strength"])],
        ),
    )
    for row in closing_rows:
        lines.append(
            f"| {row['course']} | {row['style_category']} | {row['closing_strength']} | "
            f"{row['starts']} | {fmt(row['win_index'])} | {fmt(row['top3_index'])} |"
        )

    lines.extend(
        [
            "",
            "## 해석 주의",
            "",
            "현재 S1F 위치와 최종 착순의 관계는 강하지만 S1F는 경주 후 정보이므로 모델 입력에 "
            "직접 사용할 수 없다. 모델에는 과거 성향만 사용해야 한다. 또한 과거 추입량은 과거 "
            "착순을 포함하므로 말의 능력과 섞여 있다. 다음 단계에서는 레이팅·부담중량·게이트·경주 "
            "등급을 통제한 뒤 증분 효과를 검증한다.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    current = load_current_flow(open_readonly(args.db), args.start, args.end)
    flow_course = current_race_summary(current, ["course"])
    flow_distance = current_race_summary(current, ["course", "distance_m"])
    current_groups = aggregate_performance(
        current, ["course", "distance_m", "current_early_group"]
    ).sort(["course", "distance_m", "current_early_group"])
    current_groups_course = aggregate_performance(
        current, ["course", "current_early_group"]
    )

    past = load_past_style(args.dataset)
    past_style = aggregate_past_style(
        past, ["course", "distance_m", "style_category"]
    ).sort(["course", "distance_m", "style_category"])
    past_style_course = aggregate_past_style(past, ["course", "style_category"])
    past_style_year = aggregate_past_style(
        past, ["race_year", "course", "style_category"]
    ).sort(["race_year", "course", "style_category"])
    closing = aggregate_past_style(
        past,
        ["course", "distance_m", "style_category", "closing_strength"],
    ).sort(["course", "distance_m", "style_category", "closing_strength"])
    closing_course = aggregate_past_style(
        past, ["course", "style_category", "closing_strength"]
    )

    outputs = {
        "current_race_summary.csv": flow_distance,
        "current_early_position.csv": current_groups,
        "past_style.csv": past_style,
        "past_style_by_year.csv": past_style_year,
        "past_style_closing_strength.csv": closing,
    }
    for name, frame in outputs.items():
        frame.write_csv(args.output_dir / name, include_bom=True)

    report_path = args.output_dir / "report.md"
    write_report(
        report_path,
        start=args.start,
        end=args.end,
        current=current,
        flow_course=flow_course,
        flow_distance=flow_distance,
        current_groups_course=current_groups_course,
        past_style_course=past_style_course,
        past_style_distance=past_style,
        closing_course=closing_course,
    )
    print(f"current_flow={current['race_id'].n_unique():,} races / {current.height:,} rows")
    print(f"past_style={past.height:,} rows (coverage >= {MIN_HISTORY_COVERAGE})")
    for name in outputs:
        print(args.output_dir / name)
    print(report_path)


if __name__ == "__main__":
    main()
