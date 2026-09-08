"""경기장 × 거리 × 출발 게이트별 성적 편향을 재현 가능하게 분석한다.

학습 데이터셋과 같은 정상 착순 정책을 사용한다. 단순 승률뿐 아니라 경주별 출전
두수와 동착 슬롯 수를 반영한 기대 승수/입상 수를 계산해 서로 다른 게이트를 비교한다.
"""

from __future__ import annotations

import argparse
import csv
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "data" / "horse_racing.sqlite3"
DEFAULT_OUTPUT = REPO / "data" / "exports" / "gate_bias"
MIN_STARTERS = 5


@dataclass
class Metric:
    starts: int = 0
    wins: int = 0
    top3: int = 0
    expected_wins: float = 0.0
    expected_top3: float = 0.0
    win_variance: float = 0.0
    top3_variance: float = 0.0
    finish_score_sum: float = 0.0
    races: set[int] | None = None

    def __post_init__(self) -> None:
        if self.races is None:
            self.races = set()

    def add(self, row: sqlite3.Row) -> None:
        win_p = row["winner_slots"] / row["starters"]
        top3_p = row["top3_slots"] / row["starters"]
        self.starts += 1
        self.wins += int(row["finish_position"] == 1)
        self.top3 += int(row["finish_position"] <= 3)
        self.expected_wins += win_p
        self.expected_top3 += top3_p
        self.win_variance += win_p * (1.0 - win_p)
        self.top3_variance += top3_p * (1.0 - top3_p)
        self.finish_score_sum += (row["starters"] - row["finish_position"]) / (
            row["starters"] - 1
        )
        assert self.races is not None
        self.races.add(row["race_id"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--start", default="2025-01-03")
    parser.add_argument("--end", default="2026-08-23")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def load_rows(conn: sqlite3.Connection, start: str, end: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        WITH normal AS (
          SELECT
            r.id AS race_id,
            r.race_date_local,
            CAST(strftime('%Y', r.race_date_local) AS INTEGER) AS race_year,
            rc.kra_meet_code AS meet_code,
            rc.name_ko AS course,
            r.distance_m,
            e.gate_number,
            rr.finish_position
          FROM races r
          JOIN racecourses rc ON rc.id = r.racecourse_id
          JOIN race_entries e ON e.race_id = r.id
          JOIN race_results rr ON rr.race_entry_id = e.id
          WHERE r.status = 'completed'
            AND r.race_date_local BETWEEN ? AND ?
            AND e.scratched = 0
            AND rr.finish_position BETWEEN 1 AND 89
            AND e.gate_number IS NOT NULL
        ),
        race_stats AS (
          SELECT
            race_id,
            COUNT(*) AS starters,
            SUM(finish_position = 1) AS winner_slots,
            SUM(finish_position <= 3) AS top3_slots
          FROM normal
          GROUP BY race_id
          HAVING COUNT(*) >= ? AND SUM(finish_position = 1) > 0
        )
        SELECT n.*, s.starters, s.winner_slots, s.top3_slots
        FROM normal n
        JOIN race_stats s USING (race_id)
        ORDER BY n.race_date_local, n.meet_code, n.race_id, n.gate_number
        """,
        (start, end, MIN_STARTERS),
    ).fetchall()


def zone_for(gate: int, starters: int) -> str:
    bucket = min(2, int((gate - 1) * 3 / starters))
    return ("안쪽", "중간", "바깥쪽")[bucket]


def index(observed: int, expected: float) -> float:
    return 100.0 * observed / expected if expected else math.nan


def z_score(observed: int, expected: float, variance: float) -> float:
    return (observed - expected) / math.sqrt(variance) if variance > 0 else math.nan


def p_value(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0)) if math.isfinite(z) else math.nan


def reliability(starts: int) -> str:
    if starts >= 200:
        return "높음"
    if starts >= 100:
        return "보통"
    if starts >= 50:
        return "낮음"
    return "판단보류"


def metric_row(key: tuple[object, ...], metric: Metric) -> dict[str, object]:
    win_z = z_score(metric.wins, metric.expected_wins, metric.win_variance)
    top3_z = z_score(metric.top3, metric.expected_top3, metric.top3_variance)
    return {
        "course": key[0],
        "distance_m": key[1],
        "gate_or_zone": key[2],
        "races": len(metric.races or ()),
        "starts": metric.starts,
        "wins": metric.wins,
        "win_rate_pct": 100.0 * metric.wins / metric.starts,
        "expected_win_rate_pct": 100.0 * metric.expected_wins / metric.starts,
        "win_index": index(metric.wins, metric.expected_wins),
        "win_z": win_z,
        "win_p_two_sided": p_value(win_z),
        "top3": metric.top3,
        "top3_rate_pct": 100.0 * metric.top3 / metric.starts,
        "expected_top3_rate_pct": 100.0 * metric.expected_top3 / metric.starts,
        "top3_index": index(metric.top3, metric.expected_top3),
        "top3_z": top3_z,
        "top3_p_two_sided": p_value(top3_z),
        "mean_finish_score": metric.finish_score_sum / metric.starts,
        "reliability": reliability(metric.starts),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def f(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def report_table(rows: list[dict[str, object]], *, limit: int = 12) -> list[str]:
    lines = [
        "| 경기장 | 거리 | 게이트 | 출전 | 승리 | 승리지수 | 3위내 | 3위내지수 | 신뢰도 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows[:limit]:
        formatted = dict(row)
        formatted["win_index"] = f(float(row["win_index"]))
        formatted["top3_index"] = f(float(row["top3_index"]))
        lines.append(
            "| {course} | {distance_m}m | {gate_or_zone} | {starts} | {wins} | "
            "{win_index} | {top3} | {top3_index} | {reliability} |".format(
                **formatted,
            )
        )
    return lines


def write_report(
    path: Path,
    *,
    start: str,
    end: str,
    rows: list[sqlite3.Row],
    exact_rows: list[dict[str, object]],
    zone_rows: list[dict[str, object]],
    course_zone_rows: list[dict[str, object]],
) -> None:
    race_count = len({row["race_id"] for row in rows})
    combos = len({(row["course"], row["distance_m"]) for row in rows})
    eligible = [row for row in exact_rows if int(row["starts"]) >= 100]
    favorable = sorted(eligible, key=lambda row: float(row["top3_index"]), reverse=True)
    unfavorable = sorted(eligible, key=lambda row: float(row["top3_index"]))
    significant = [
        row
        for row in eligible
        if float(row["top3_p_two_sided"]) < 0.05
    ]
    zone_use = [row for row in zone_rows if int(row["starts"]) >= 100]

    lines = [
        "# 경기장·거리·출발 게이트 유불리 분석",
        "",
        f"분석 기간: **{start}~{end}**  ",
        f"표본: **{race_count:,}경주 / {len(rows):,}정상 착순 / {combos}개 경기장·거리 조합**",
        "",
        "## 해석 기준",
        "",
        "- 승리지수와 3위내지수는 출전 두수와 동착 슬롯을 보정한다. 100이면 기대와 같고, "
        "120이면 무작위 게이트 기대보다 20% 많다.",
        "- `p<0.05`는 탐색용 표시일 뿐이다. 다수 게이트를 동시에 비교하므로 단독 확정 근거로 "
        "사용하지 않는다.",
        "- 표본 100회 미만은 결론보다 관찰 대상으로 취급한다.",
        "- 정상 착순(1~89)만 사용해 현재 학습 데이터셋의 라벨 정책과 맞췄다.",
        "",
        "## 경기장 전체 구역 요약",
        "",
        "| 경기장 | 구역 | 출전 | 승리지수 | 3위내지수 | 2025 3위내지수 | 2026 3위내지수 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in course_zone_rows:
        lines.append(
            f"| {row['course']} | {row['gate_or_zone']} | {row['starts']} | "
            f"{float(row['win_index']):.1f} | {float(row['top3_index']):.1f} | "
            f"{float(row['top3_index_2025']):.1f} | "
            f"{float(row['top3_index_2026']):.1f} |"
        )
    lines.extend(
        [
            "",
        "## 표본 100회 이상 게이트 중 3위내지수 상위",
        "",
        *report_table(favorable),
        "",
        "## 표본 100회 이상 게이트 중 3위내지수 하위",
        "",
        *report_table(unfavorable),
        "",
        "## 안쪽·중간·바깥쪽 요약",
        "",
        "게이트를 각 경주의 출전 두수 기준으로 3등분했다.",
        "",
        "| 경기장 | 거리 | 구역 | 출전 | 승리지수 | 3위내지수 |",
        "|---|---:|---|---:|---:|---:|",
        ]
    )
    zone_sort = lambda item: (  # noqa: E731 - 보고서 정렬 키를 읽기 쉽게 유지
        str(item["course"]),
        int(item["distance_m"]),
        str(item["gate_or_zone"]),
    )
    for row in sorted(zone_use, key=zone_sort):
        lines.append(
            f"| {row['course']} | {row['distance_m']}m | {row['gate_or_zone']} | "
            f"{row['starts']} | {float(row['win_index']):.1f} | "
            f"{float(row['top3_index']):.1f} |"
        )
    lines.extend(
        [
            "",
            "## 주의",
            "",
            f"표본 100회 이상 exact gate 셀은 {len(eligible)}개이고, 이 중 보정 전 양측 "
            f"`p<0.05`인 3위내 셀은 {len(significant)}개다. 이 수치는 다중비교 보정 전이므로 "
            "우연 신호가 포함될 수 있다. 다음 단계에서는 연도별 재현성과 말 능력·인기도를 "
            "통제한 경주 내 모델로 확인해야 한다.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    conn = open_readonly(args.db)
    rows = load_rows(conn, args.start, args.end)
    if not rows:
        raise SystemExit("분석 대상 행이 없습니다.")

    exact: defaultdict[tuple[object, ...], Metric] = defaultdict(Metric)
    zones: defaultdict[tuple[object, ...], Metric] = defaultdict(Metric)
    course_zones: defaultdict[tuple[object, ...], Metric] = defaultdict(Metric)
    yearly: defaultdict[tuple[object, ...], Metric] = defaultdict(Metric)
    yearly_course_zones: defaultdict[tuple[object, ...], Metric] = defaultdict(Metric)
    for row in rows:
        exact_key = (row["course"], row["distance_m"], row["gate_number"])
        zone_key = (
            row["course"],
            row["distance_m"],
            zone_for(row["gate_number"], row["starters"]),
        )
        year_key = (*exact_key, row["race_year"])
        course_zone_key = (row["course"], "전체", zone_key[2])
        exact[exact_key].add(row)
        zones[zone_key].add(row)
        course_zones[course_zone_key].add(row)
        yearly[year_key].add(row)
        yearly_course_zones[(*course_zone_key, row["race_year"])].add(row)

    exact_rows = [metric_row(key, value) for key, value in exact.items()]
    zone_rows = [metric_row(key, value) for key, value in zones.items()]
    course_zone_rows = [metric_row(key, value) for key, value in course_zones.items()]
    year_lookup = {
        key: metric_row(key[:3], value) for key, value in yearly.items()
    }
    for row in exact_rows:
        base_key = (row["course"], row["distance_m"], row["gate_or_zone"])
        for year in (2025, 2026):
            year_row = year_lookup.get((*base_key, year))
            row[f"starts_{year}"] = int(year_row["starts"]) if year_row else 0
            row[f"win_index_{year}"] = (
                float(year_row["win_index"]) if year_row else math.nan
            )
            row[f"top3_index_{year}"] = (
                float(year_row["top3_index"]) if year_row else math.nan
            )

    course_year_lookup = {
        key: metric_row(key[:3], value) for key, value in yearly_course_zones.items()
    }
    for row in course_zone_rows:
        base_key = (row["course"], "전체", row["gate_or_zone"])
        for year in (2025, 2026):
            year_row = course_year_lookup.get((*base_key, year))
            row[f"top3_index_{year}"] = (
                float(year_row["top3_index"]) if year_row else math.nan
            )

    exact_rows.sort(
        key=lambda row: (str(row["course"]), int(row["distance_m"]), int(row["gate_or_zone"]))
    )
    zone_order = {"안쪽": 0, "중간": 1, "바깥쪽": 2}
    zone_rows.sort(
        key=lambda row: (
            str(row["course"]),
            int(row["distance_m"]),
            zone_order[str(row["gate_or_zone"])],
        )
    )
    course_zone_rows.sort(
        key=lambda row: (
            str(row["course"]),
            zone_order[str(row["gate_or_zone"])],
        )
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    exact_path = args.output_dir / "by_gate.csv"
    zone_path = args.output_dir / "by_zone.csv"
    course_zone_path = args.output_dir / "by_course_zone.csv"
    report_path = args.output_dir / "report.md"
    write_csv(exact_path, exact_rows)
    write_csv(zone_path, zone_rows)
    write_csv(course_zone_path, course_zone_rows)
    write_report(
        report_path,
        start=args.start,
        end=args.end,
        rows=rows,
        exact_rows=exact_rows,
        zone_rows=zone_rows,
        course_zone_rows=course_zone_rows,
    )
    print(f"rows={len(rows):,} races={len({row['race_id'] for row in rows}):,}")
    print(exact_path)
    print(zone_path)
    print(course_zone_path)
    print(report_path)


if __name__ == "__main__":
    main()
