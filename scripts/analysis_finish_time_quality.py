"""T4. finish_time_ms (주파기록) 품질 검사. DB는 읽기 전용."""

from __future__ import annotations

import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "data" / "horse_racing.sqlite3"

NORMAL_POS_MIN = 1
NORMAL_POS_MAX = 89
SPEED_LOW_MPS = 12.0
SPEED_HIGH_MPS = 20.0
OUTLIER_LIST_CAP = 50
INVERSION_SAMPLE_CAP = 30


def format_clock(ms: int) -> str:
    minutes, remaining = divmod(ms, 60_000)
    seconds = remaining / 1000
    return f"{minutes}:{seconds:04.1f}" if minutes else f"{seconds:.1f}초"


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        raise ValueError("empty")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def open_readonly() -> sqlite3.Connection:
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def print_table(headers: list[str], rows: list[list[object]]) -> None:
    print("| " + " | ".join(headers) + " |")
    aligns = []
    for h in headers:
        aligns.append("---:" if any(ch in h.lower() for ch in ("수", "율", "%", "m/s", "ms", "p1", "p99", "min", "max", "중앙")) or h in {"건수", "결측", "보유", "정상", "비율"} else "---")
    print("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        print("| " + " | ".join(str(c) for c in row) + " |")
    print()


def pct(n: int, d: int) -> str:
    if d == 0:
        return "—"
    return f"{100.0 * n / d:.2f}%"


def main() -> None:
    checked = datetime.now(tz=SEOUL).strftime("%Y-%m-%d")
    print(f"# finish_time_ms quality  {checked}")
    print()
    conn = open_readonly()

    overview = conn.execute(
        """
        SELECT
          COUNT(DISTINCT r.id) AS race_count,
          MIN(r.race_date_local) AS min_date,
          MAX(r.race_date_local) AS max_date,
          COUNT(*) AS entry_count,
          SUM(CASE WHEN rr.id IS NULL THEN 1 ELSE 0 END) AS no_result,
          SUM(CASE WHEN rr.finish_position BETWEEN 1 AND 89 THEN 1 ELSE 0 END) AS normal_pos,
          SUM(CASE WHEN rr.finish_position >= 90 THEN 1 ELSE 0 END) AS special_pos,
          SUM(CASE WHEN rr.id IS NOT NULL AND rr.finish_position IS NULL THEN 1 ELSE 0 END) AS null_pos
        FROM race_entries e
        JOIN races r ON r.id = e.race_id
        LEFT JOIN race_results rr ON rr.race_entry_id = e.id
        """
    ).fetchone()
    print("## overview")
    print(
        f"races={overview['race_count']}  entries={overview['entry_count']}  "
        f"no_result={overview['no_result']}  normal={overview['normal_pos']}  "
        f"special={overview['special_pos']}  null_pos={overview['null_pos']}  "
        f"dates={overview['min_date']}~{overview['max_date']}"
    )
    print()

    # --- 1. missing rate by year x course ---
    print("## 1 missing rate (normal finish_position 1-89)")
    missing_rows = conn.execute(
        """
        SELECT
          strftime('%Y', r.race_date_local) AS year,
          c.kra_meet_code AS meet,
          c.name_ko AS course,
          COUNT(*) AS n,
          SUM(CASE WHEN rr.finish_time_ms IS NULL THEN 1 ELSE 0 END) AS n_null,
          SUM(CASE WHEN rr.finish_time_ms IS NOT NULL THEN 1 ELSE 0 END) AS n_time
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position BETWEEN 1 AND 89
        GROUP BY year, meet, course
        ORDER BY year, meet
        """
    ).fetchall()
    print_table(
        ["연도", "경마장", "meet", "정상착순", "기록보유", "기록결측", "결측률"],
        [
            [
                row["year"],
                row["course"],
                row["meet"],
                row["n"],
                row["n_time"],
                row["n_null"],
                pct(row["n_null"], row["n"]),
            ]
            for row in missing_rows
        ],
    )
    year_tot = conn.execute(
        """
        SELECT
          strftime('%Y', r.race_date_local) AS year,
          COUNT(*) AS n,
          SUM(CASE WHEN rr.finish_time_ms IS NULL THEN 1 ELSE 0 END) AS n_null
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        WHERE rr.finish_position BETWEEN 1 AND 89
        GROUP BY year
        ORDER BY year
        """
    ).fetchall()
    tot = conn.execute(
        """
        SELECT
          COUNT(*) AS n,
          SUM(CASE WHEN rr.finish_time_ms IS NULL THEN 1 ELSE 0 END) AS n_null
        FROM race_results rr
        WHERE rr.finish_position BETWEEN 1 AND 89
        """
    ).fetchone()
    print("year totals:")
    for row in year_tot:
        print(f"  {row['year']}: {row['n_null']}/{row['n']} = {pct(row['n_null'], row['n'])}")
    print(f"  ALL: {tot['n_null']}/{tot['n']} = {pct(tot['n_null'], tot['n'])}")
    print()

    missing_detail = conn.execute(
        """
        SELECT
          r.race_date_local AS race_date,
          c.name_ko AS course,
          c.kra_meet_code AS meet,
          r.race_number AS race_no,
          r.distance_m AS distance_m,
          r.status AS status,
          e.horse_number AS horse_no,
          rr.finish_position AS pos,
          rr.rank_remark AS remark,
          rr.disqualified AS dq,
          e.scratched AS scratched
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position BETWEEN 1 AND 89
          AND rr.finish_time_ms IS NULL
        ORDER BY r.race_date_local, c.kra_meet_code, r.race_number, e.horse_number
        """
    ).fetchall()
    print(f"missing detail count={len(missing_detail)}")
    by_date: dict[tuple, int] = defaultdict(int)
    for row in missing_detail:
        by_date[(row["race_date"], row["course"], row["meet"], row["race_no"], row["status"])] += 1
    print("missing clustered by race:")
    for key, n in sorted(by_date.items()):
        race_date, course, meet, race_no, status = key
        print(f"  {race_date} {course}(meet={meet}) R{race_no} status={status}: {n}두")
    if missing_detail:
        print("sample missing rows (all if <=40):")
        for row in missing_detail[:40]:
            print(
                f"  {row['race_date']} {row['course']} R{row['race_no']} "
                f"#{row['horse_no']} pos={row['pos']} remark={row['remark']!r} "
                f"dq={row['dq']} scratched={row['scratched']} dist={row['distance_m']}"
            )
    print()

    # --- 2. distribution by course x distance ---
    print("## 2 distribution (normal pos + non-null time)")
    dist_rows = conn.execute(
        """
        SELECT
          c.name_ko AS course,
          c.kra_meet_code AS meet,
          r.distance_m AS distance_m,
          rr.finish_time_ms AS finish_time_ms
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position BETWEEN 1 AND 89
          AND rr.finish_time_ms IS NOT NULL
          AND r.distance_m IS NOT NULL
        ORDER BY meet, distance_m
        """
    ).fetchall()
    groups: dict[tuple[str, int, int], list[int]] = defaultdict(list)
    for row in dist_rows:
        groups[(row["course"], row["meet"], row["distance_m"])].append(int(row["finish_time_ms"]))

    dist_table: list[list[object]] = []
    speed_stats_all: list[float] = []
    for (course, meet, distance_m), times in sorted(groups.items(), key=lambda x: (x[0][1], x[0][2])):
        times_sorted = sorted(times)
        speeds = [distance_m * 1000.0 / t for t in times_sorted]
        speed_stats_all.extend(speeds)
        speeds_sorted = sorted(speeds)
        dist_table.append(
            [
                course,
                meet,
                distance_m,
                len(times_sorted),
                times_sorted[0],
                round(percentile(times_sorted, 1)),
                round(percentile(times_sorted, 50)),
                round(percentile(times_sorted, 99)),
                times_sorted[-1],
                f"{min(speeds_sorted):.2f}",
                f"{percentile(speeds_sorted, 1):.2f}",
                f"{percentile(speeds_sorted, 50):.2f}",
                f"{percentile(speeds_sorted, 99):.2f}",
                f"{max(speeds_sorted):.2f}",
            ]
        )
    print_table(
        [
            "경마장",
            "meet",
            "거리(m)",
            "건수",
            "min_ms",
            "p1_ms",
            "중앙_ms",
            "p99_ms",
            "max_ms",
            "min_m/s",
            "p1_m/s",
            "중앙_m/s",
            "p99_m/s",
            "max_m/s",
        ],
        dist_table,
    )
    if speed_stats_all:
        ss = sorted(speed_stats_all)
        print(
            "overall implied speed: "
            f"n={len(ss)} min={ss[0]:.3f} p1={percentile(ss, 1):.3f} "
            f"median={percentile(ss, 50):.3f} p99={percentile(ss, 99):.3f} max={ss[-1]:.3f}"
        )
        print(
            f"mean={statistics.fmean(ss):.3f} stdev={statistics.pstdev(ss):.3f}"
        )
    print()

    # --- 3. outliers ---
    print(f"## 3 outliers (implied speed < {SPEED_LOW_MPS} or > {SPEED_HIGH_MPS})")
    outlier_rows = conn.execute(
        """
        SELECT
          r.race_date_local AS race_date,
          c.name_ko AS course,
          c.kra_meet_code AS meet,
          r.race_number AS race_no,
          e.horse_number AS horse_no,
          r.distance_m AS distance_m,
          rr.finish_position AS pos,
          rr.finish_time_ms AS finish_time_ms,
          CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms AS speed_mps,
          rr.rank_remark AS remark,
          rr.disqualified AS dq,
          rr.margin_text AS margin
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position BETWEEN 1 AND 89
          AND rr.finish_time_ms IS NOT NULL
          AND r.distance_m IS NOT NULL
          AND (
            CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms < ?
            OR CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms > ?
          )
        ORDER BY
          CASE
            WHEN CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms > ? THEN 0
            ELSE 1
          END,
          ABS(CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms - 16.0) DESC,
          r.race_date_local,
          c.kra_meet_code,
          r.race_number
        """,
        (SPEED_LOW_MPS, SPEED_HIGH_MPS, SPEED_HIGH_MPS),
    ).fetchall()

    n_fast = sum(1 for r in outlier_rows if r["speed_mps"] > SPEED_HIGH_MPS)
    n_slow = sum(1 for r in outlier_rows if r["speed_mps"] < SPEED_LOW_MPS)
    print(f"outlier total={len(outlier_rows)}  fast(>{SPEED_HIGH_MPS})={n_fast}  slow(<{SPEED_LOW_MPS})={n_slow}")
    by_course_out: dict[str, int] = defaultdict(int)
    by_year_out: dict[str, int] = defaultdict(int)
    for row in outlier_rows:
        by_course_out[row["course"]] += 1
        by_year_out[str(row["race_date"])[:4]] += 1
    print("by course:", dict(by_course_out))
    print("by year:", dict(by_year_out))

    listed = outlier_rows[:OUTLIER_LIST_CAP]
    print(f"listing {len(listed)} of {len(outlier_rows)}")
    print_table(
        ["경주일", "경마장", "R", "출주", "거리", "착순", "기록", "ms", "m/s", "비고"],
        [
            [
                row["race_date"],
                row["course"],
                row["race_no"],
                row["horse_no"],
                row["distance_m"],
                row["pos"],
                format_clock(int(row["finish_time_ms"])),
                row["finish_time_ms"],
                f"{row['speed_mps']:.2f}",
                (row["remark"] or row["margin"] or "")[:40],
            ]
            for row in listed
        ],
    )

    # --- 4. inversions ---
    print("## 4 intra-race inversions (better pos but slower time)")
    race_rows = conn.execute(
        """
        SELECT
          r.id AS race_id,
          r.race_date_local AS race_date,
          c.name_ko AS course,
          c.kra_meet_code AS meet,
          r.race_number AS race_no,
          r.distance_m AS distance_m,
          e.horse_number AS horse_no,
          rr.finish_position AS pos,
          rr.finish_time_ms AS finish_time_ms,
          rr.rank_remark AS remark,
          rr.disqualified AS dq
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position BETWEEN 1 AND 89
          AND rr.finish_time_ms IS NOT NULL
        ORDER BY r.id, rr.finish_position, e.horse_number
        """
    ).fetchall()
    by_race: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in race_rows:
        by_race[row["race_id"]].append(row)

    inverted_races: list[dict] = []
    inverted_pairs = 0
    dq_involved_races = 0
    for race_id, horses in by_race.items():
        pairs: list[tuple[sqlite3.Row, sqlite3.Row]] = []
        for i, a in enumerate(horses):
            for b in horses[i + 1 :]:
                if a["pos"] == b["pos"]:
                    continue
                better, worse = (a, b) if a["pos"] < b["pos"] else (b, a)
                if better["finish_time_ms"] > worse["finish_time_ms"]:
                    pairs.append((better, worse))
        if not pairs:
            continue
        inverted_pairs += len(pairs)
        sample = pairs[0]
        inverted_races.append(
            {
                "race_id": race_id,
                "race_date": sample[0]["race_date"],
                "course": sample[0]["course"],
                "meet": sample[0]["meet"],
                "race_no": sample[0]["race_no"],
                "distance_m": sample[0]["distance_m"],
                "n_pairs": len(pairs),
                "n_horses": len(horses),
                "has_dq": any(h["dq"] for h in horses),
                "pairs": pairs[:5],
            }
        )
        if any(h["dq"] for h in horses) or any(
            (p[0]["dq"] or p[1]["dq"]) for p in pairs
        ):
            dq_involved_races += 1

    inverted_races.sort(key=lambda x: (-x["n_pairs"], str(x["race_date"])))
    print(
        f"races_checked={len(by_race)}  inverted_races={len(inverted_races)}  "
        f"inverted_pairs={inverted_pairs}  dq_flag_races={dq_involved_races}"
    )
    print(f"sample up to {INVERSION_SAMPLE_CAP} inverted races:")
    for item in inverted_races[:INVERSION_SAMPLE_CAP]:
        a, b = item["pairs"][0]
        print(
            f"  {item['race_date']} {item['course']} R{item['race_no']} "
            f"dist={item['distance_m']} pairs={item['n_pairs']}/{item['n_horses']} dq={item['has_dq']} | "
            f"#{a['horse_no']} pos={a['pos']} {format_clock(a['finish_time_ms'])} "
            f"> #{b['horse_no']} pos={b['pos']} {format_clock(b['finish_time_ms'])} "
            f"remark=({a['remark']!r},{b['remark']!r})"
        )

    # inversions excluding disqualified
    inverted_no_dq = 0
    inverted_pairs_no_dq = 0
    for race_id, horses in by_race.items():
        clean = [h for h in horses if not h["dq"]]
        n_pairs = 0
        for i, a in enumerate(clean):
            for b in clean[i + 1 :]:
                if a["pos"] == b["pos"]:
                    continue
                better, worse = (a, b) if a["pos"] < b["pos"] else (b, a)
                if better["finish_time_ms"] > worse["finish_time_ms"]:
                    n_pairs += 1
        if n_pairs:
            inverted_no_dq += 1
            inverted_pairs_no_dq += n_pairs
    print(
        f"excluding disqualified rows: inverted_races={inverted_no_dq} pairs={inverted_pairs_no_dq}"
    )
    print()

    # time delta of inversions
    deltas: list[int] = []
    for item in inverted_races:
        for a, b in item["pairs"]:
            deltas.append(int(a["finish_time_ms"] - b["finish_time_ms"]))
        # also remaining pairs not stored... we only stored 5. recompute from race
    # recompute all deltas
    all_deltas: list[int] = []
    for race_id, horses in by_race.items():
        for i, a in enumerate(horses):
            for b in horses[i + 1 :]:
                if a["pos"] == b["pos"]:
                    continue
                better, worse = (a, b) if a["pos"] < b["pos"] else (b, a)
                if better["finish_time_ms"] > worse["finish_time_ms"]:
                    all_deltas.append(int(better["finish_time_ms"] - worse["finish_time_ms"]))
    if all_deltas:
        ds = sorted(all_deltas)
        print(
            "inversion time delta ms: "
            f"n={len(ds)} min={ds[0]} p50={round(percentile(ds, 50))} "
            f"p90={round(percentile(ds, 90))} max={ds[-1]}"
        )
        tiny = sum(1 for d in ds if d <= 100)
        print(f"  delta<=100ms: {tiny} ({pct(tiny, len(ds))})")
        print(f"  delta>=1000ms: {sum(1 for d in ds if d >= 1000)}")
    print()

    # --- 5. special / null position with time ---
    print("## 5 special/null position with finish_time_ms")
    special = conn.execute(
        """
        SELECT
          CASE
            WHEN rr.finish_position IS NULL THEN 'NULL'
            ELSE CAST(rr.finish_position AS TEXT)
          END AS pos_key,
          COUNT(*) AS n,
          SUM(CASE WHEN rr.finish_time_ms IS NOT NULL THEN 1 ELSE 0 END) AS n_time,
          SUM(CASE WHEN rr.finish_time_ms IS NULL THEN 1 ELSE 0 END) AS n_null
        FROM race_results rr
        WHERE rr.finish_position IS NULL OR rr.finish_position >= 90
        GROUP BY pos_key
        ORDER BY pos_key
        """
    ).fetchall()
    print_table(
        ["착순", "행수", "기록보유", "기록결측", "보유율"],
        [
            [row["pos_key"], row["n"], row["n_time"], row["n_null"], pct(row["n_time"], row["n"])]
            for row in special
        ],
    )
    spec_tot = conn.execute(
        """
        SELECT
          COUNT(*) AS n,
          SUM(CASE WHEN rr.finish_time_ms IS NOT NULL THEN 1 ELSE 0 END) AS n_time
        FROM race_results rr
        WHERE rr.finish_position IS NULL OR rr.finish_position >= 90
        """
    ).fetchone()
    print(f"special+null total with time: {spec_tot['n_time']}/{spec_tot['n']}")

    examples = conn.execute(
        """
        SELECT
          r.race_date_local AS race_date,
          c.name_ko AS course,
          r.race_number AS race_no,
          e.horse_number AS horse_no,
          rr.finish_position AS pos,
          rr.finish_time_ms AS finish_time_ms,
          rr.rank_remark AS remark,
          rr.disqualified AS dq,
          e.scratched AS scratched
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE (rr.finish_position IS NULL OR rr.finish_position >= 90)
          AND rr.finish_time_ms IS NOT NULL
        ORDER BY r.race_date_local, c.kra_meet_code, r.race_number
        LIMIT 20
        """
    ).fetchall()
    print("examples of special/null with time:")
    for row in examples:
        t = format_clock(int(row["finish_time_ms"])) if row["finish_time_ms"] else "—"
        print(
            f"  {row['race_date']} {row['course']} R{row['race_no']} "
            f"#{row['horse_no']} pos={row['pos']} t={t} remark={row['remark']!r} "
            f"dq={row['dq']} scratched={row['scratched']}"
        )
    print()

    # --- 6. recommended filter impact ---
    print("## 6 filter impact")
    usable = conn.execute(
        """
        SELECT
          COUNT(*) AS n_normal,
          SUM(CASE WHEN rr.finish_time_ms IS NOT NULL THEN 1 ELSE 0 END) AS n_with_time,
          SUM(
            CASE
              WHEN rr.finish_time_ms IS NOT NULL
               AND r.distance_m IS NOT NULL
               AND CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms >= ?
               AND CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms <= ?
              THEN 1 ELSE 0
            END
          ) AS n_speed_ok
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        WHERE rr.finish_position BETWEEN 1 AND 89
        """,
        (SPEED_LOW_MPS, SPEED_HIGH_MPS),
    ).fetchone()
    all_results = conn.execute("SELECT COUNT(*) AS n FROM race_results").fetchone()["n"]
    print(f"all race_results={all_results}")
    print(f"normal pos={usable['n_normal']}")
    print(f"normal + time={usable['n_with_time']}")
    print(f"normal + time + speed 12-20={usable['n_speed_ok']}")
    loss_from_normal = usable["n_normal"] - usable["n_speed_ok"]
    print(
        f"loss vs normal pos: {loss_from_normal}/{usable['n_normal']} "
        f"= {pct(loss_from_normal, usable['n_normal'])}"
    )
    print(
        f"loss vs normal+time: {usable['n_with_time'] - usable['n_speed_ok']}/"
        f"{usable['n_with_time']} = {pct(usable['n_with_time'] - usable['n_speed_ok'], usable['n_with_time'])}"
    )
    print(
        f"kept of all results: {usable['n_speed_ok']}/{all_results} "
        f"= {pct(usable['n_speed_ok'], all_results)}"
    )

    # also report zero/negative times — constraint should prevent
    bad_time = conn.execute(
        """
        SELECT COUNT(*) AS n FROM race_results
        WHERE finish_time_ms IS NOT NULL AND finish_time_ms <= 0
        """
    ).fetchone()["n"]
    print(f"non-positive finish_time_ms: {bad_time}")

    # dead heats: same position different times
    deadheat = conn.execute(
        """
        SELECT COUNT(*) AS n_races FROM (
          SELECT e.race_id, rr.finish_position
          FROM race_results rr
          JOIN race_entries e ON e.id = rr.race_entry_id
          WHERE rr.finish_position BETWEEN 1 AND 89
          GROUP BY e.race_id, rr.finish_position
          HAVING COUNT(*) > 1
        )
        """
    ).fetchone()["n_races"]
    print(f"dead-heat (same pos, 2+ horses) race-position groups: {deadheat}")

    # --- 7. course-specific bands (Jeju horses are slower) ---
    print()
    print("## 7 course-specific speed (normal pos + time)")
    course_speed = conn.execute(
        """
        SELECT
          c.name_ko AS course,
          c.kra_meet_code AS meet,
          COUNT(*) AS n,
          MIN(CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms) AS min_s,
          MAX(CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms) AS max_s,
          SUM(CASE WHEN CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms < 12 THEN 1 ELSE 0 END) AS below12,
          SUM(CASE WHEN CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms > 20 THEN 1 ELSE 0 END) AS above20,
          SUM(CASE WHEN CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms < 10 THEN 1 ELSE 0 END) AS below10,
          SUM(CASE WHEN CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms BETWEEN 12 AND 20 THEN 1 ELSE 0 END) AS in_12_20,
          SUM(CASE WHEN CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms BETWEEN 9.5 AND 14 THEN 1 ELSE 0 END) AS in_95_14,
          SUM(CASE WHEN CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms BETWEEN 13 AND 18 THEN 1 ELSE 0 END) AS in_13_18
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position BETWEEN 1 AND 89
          AND rr.finish_time_ms IS NOT NULL
          AND r.distance_m IS NOT NULL
        GROUP BY course, meet
        ORDER BY meet
        """
    ).fetchall()
    print_table(
        ["경마장", "n", "min_m/s", "max_m/s", "<10", "<12", ">20", "12-20", "9.5-14", "13-18"],
        [
            [
                row["course"],
                row["n"],
                f"{row['min_s']:.2f}",
                f"{row['max_s']:.2f}",
                row["below10"],
                row["below12"],
                row["above20"],
                f"{row['in_12_20']} ({pct(row['in_12_20'], row['n'])})",
                f"{row['in_95_14']} ({pct(row['in_95_14'], row['n'])})",
                f"{row['in_13_18']} ({pct(row['in_13_18'], row['n'])})",
            ]
            for row in course_speed
        ],
    )

    print("Seoul/Busan rows failing 12-20 m/s (full list):")
    tb_out = conn.execute(
        """
        SELECT
          r.race_date_local AS race_date,
          c.name_ko AS course,
          r.race_number AS race_no,
          e.horse_number AS horse_no,
          r.distance_m AS distance_m,
          rr.finish_position AS pos,
          rr.finish_time_ms AS finish_time_ms,
          CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms AS speed_mps,
          rr.margin_text AS margin,
          rr.rank_remark AS remark
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position BETWEEN 1 AND 89
          AND rr.finish_time_ms IS NOT NULL
          AND c.kra_meet_code IN (1, 3)
          AND (
            CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms < 12
            OR CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms > 20
          )
        ORDER BY speed_mps
        """
    ).fetchall()
    for row in tb_out:
        print(
            f"  {row['race_date']} {row['course']} R{row['race_no']} "
            f"#{row['horse_no']} {row['distance_m']}m pos={row['pos']} "
            f"{format_clock(int(row['finish_time_ms']))} {row['speed_mps']:.2f} m/s "
            f"margin={row['margin']!r} remark={row['remark']!r}"
        )
    print(f"seoul/busan 12-20 failures: {len(tb_out)}")
    print()

    # IQR outliers per course x distance on finish_time_ms
    print("## 8 Tukey IQR outliers per (course x distance) on finish_time_ms")
    iqr_counts: list[list[object]] = []
    extreme_rows: list[tuple] = []
    for (course, meet, distance_m), times in sorted(groups.items(), key=lambda x: (x[0][1], x[0][2])):
        ts = sorted(times)
        q1 = percentile(ts, 25)
        q3 = percentile(ts, 75)
        iqr = q3 - q1
        fence_1_5_lo = q1 - 1.5 * iqr
        fence_1_5_hi = q3 + 1.5 * iqr
        fence_3_lo = q1 - 3 * iqr
        fence_3_hi = q3 + 3 * iqr
        n_15 = sum(1 for t in ts if t < fence_1_5_lo or t > fence_1_5_hi)
        n_3 = sum(1 for t in ts if t < fence_3_lo or t > fence_3_hi)
        n_slow_3 = sum(1 for t in ts if t > fence_3_hi)
        n_fast_3 = sum(1 for t in ts if t < fence_3_lo)
        iqr_counts.append(
            [
                course,
                distance_m,
                len(ts),
                round(q1),
                round(q3),
                round(iqr),
                n_15,
                pct(n_15, len(ts)),
                n_3,
                n_fast_3,
                n_slow_3,
            ]
        )
        extreme_rows.append((course, meet, distance_m, fence_3_lo, fence_3_hi, n_3))

    print_table(
        ["경마장", "거리", "n", "Q1", "Q3", "IQR", "1.5IQR", "1.5IQR%", "3IQR", "3IQR빠름", "3IQR느림"],
        iqr_counts,
    )
    n_15_tot = sum(int(r[6]) for r in iqr_counts)
    n_3_tot = sum(int(r[8]) for r in iqr_counts)
    n_all = sum(int(r[2]) for r in iqr_counts)
    print(f"1.5IQR total={n_15_tot}/{n_all} = {pct(n_15_tot, n_all)}")
    print(f"3IQR total={n_3_tot}/{n_all} = {pct(n_3_tot, n_all)}")

    # list 3*IQR extremes
    print("3IQR extreme rows (full if <=80):")
    extremes = conn.execute(
        """
        SELECT
          r.race_date_local AS race_date,
          c.name_ko AS course,
          c.kra_meet_code AS meet,
          r.race_number AS race_no,
          e.horse_number AS horse_no,
          r.distance_m AS distance_m,
          rr.finish_position AS pos,
          rr.finish_time_ms AS finish_time_ms,
          CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms AS speed_mps,
          rr.margin_text AS margin
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position BETWEEN 1 AND 89
          AND rr.finish_time_ms IS NOT NULL
        ORDER BY meet, distance_m, rr.finish_time_ms DESC
        """
    ).fetchall()
    fences = {(c, d): (lo, hi) for (c, _m, d, lo, hi, _n) in extreme_rows}
    extreme_list = []
    for row in extremes:
        key = (row["course"], row["distance_m"])
        lo, hi = fences[key]
        t = int(row["finish_time_ms"])
        if t < lo or t > hi:
            extreme_list.append(row)
    print(f"3IQR listed={len(extreme_list)}")
    for row in extreme_list[:80]:
        print(
            f"  {row['race_date']} {row['course']} R{row['race_no']} "
            f"#{row['horse_no']} {row['distance_m']}m pos={row['pos']} "
            f"{format_clock(int(row['finish_time_ms']))} {row['speed_mps']:.2f} m/s "
            f"margin={row['margin']!r}"
        )
    print()

    # --- 9. NULL position clustering ---
    print("## 9 NULL/special with time clustering")
    null_cluster = conn.execute(
        """
        SELECT
          r.race_date_local AS race_date,
          c.name_ko AS course,
          c.kra_meet_code AS meet,
          COUNT(*) AS n,
          SUM(CASE WHEN rr.finish_time_ms IS NOT NULL THEN 1 ELSE 0 END) AS n_time,
          SUM(CASE WHEN rr.finish_position IS NULL THEN 1 ELSE 0 END) AS n_null_pos,
          SUM(CASE WHEN rr.finish_position >= 90 THEN 1 ELSE 0 END) AS n_special
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE (rr.finish_position IS NULL OR rr.finish_position >= 90)
          AND rr.finish_time_ms IS NOT NULL
        GROUP BY race_date, course, meet
        ORDER BY race_date, meet
        """
    ).fetchall()
    print_table(
        ["경주일", "경마장", "meet", "기록보유", "착순NULL", "특수코드"],
        [
            [row["race_date"], row["course"], row["meet"], row["n_time"], row["n_null_pos"], row["n_special"]]
            for row in null_cluster
        ],
    )

    pos91 = conn.execute(
        """
        SELECT
          r.race_date_local AS race_date,
          c.name_ko AS course,
          r.race_number AS race_no,
          e.horse_number AS horse_no,
          r.distance_m AS distance_m,
          rr.finish_position AS pos,
          rr.finish_time_ms AS finish_time_ms,
          rr.rank_remark AS remark,
          rr.disqualified AS dq,
          rr.margin_text AS margin
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position >= 90 AND rr.finish_time_ms IS NOT NULL
        """
    ).fetchall()
    print("special pos with time (all):")
    for row in pos91:
        print(
            f"  {row['race_date']} {row['course']} R{row['race_no']} "
            f"#{row['horse_no']} pos={row['pos']} {format_clock(int(row['finish_time_ms']))} "
            f"remark={row['remark']!r} dq={row['dq']} margin={row['margin']!r}"
        )

    null_no_time = conn.execute(
        """
        SELECT
          r.race_date_local AS race_date,
          c.name_ko AS course,
          COUNT(*) AS n
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position IS NULL AND rr.finish_time_ms IS NULL
        GROUP BY race_date, course
        ORDER BY race_date
        """
    ).fetchall()
    print("NULL pos AND NULL time by date:")
    for row in null_no_time:
        print(f"  {row['race_date']} {row['course']}: {row['n']}")

    # recommended filter: thoroughbred 12-18, jeju 10-13.5, plus 3IQR optional
    rec = conn.execute(
        """
        SELECT
          COUNT(*) AS n_normal,
          SUM(
            CASE
              WHEN rr.finish_time_ms IS NULL OR r.distance_m IS NULL THEN 0
              WHEN c.kra_meet_code = 2
               AND CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms >= 10.0
               AND CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms <= 13.5
              THEN 1
              WHEN c.kra_meet_code IN (1, 3)
               AND CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms >= 12.0
               AND CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms <= 18.0
              THEN 1
              ELSE 0
            END
          ) AS n_rec
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position BETWEEN 1 AND 89
        """
    ).fetchone()
    print()
    print("recommended course-specific band (Seoul/Busan 12-18, Jeju 10-13.5):")
    print(
        f"  kept={rec['n_rec']}/{rec['n_normal']} "
        f"loss={rec['n_normal'] - rec['n_rec']} "
        f"({pct(rec['n_normal'] - rec['n_rec'], rec['n_normal'])})"
    )

    rec_by = conn.execute(
        """
        SELECT
          c.name_ko AS course,
          COUNT(*) AS n_normal,
          SUM(
            CASE
              WHEN rr.finish_time_ms IS NULL OR r.distance_m IS NULL THEN 0
              WHEN c.kra_meet_code = 2
               AND CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms >= 10.0
               AND CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms <= 13.5
              THEN 1
              WHEN c.kra_meet_code IN (1, 3)
               AND CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms >= 12.0
               AND CAST(r.distance_m AS REAL) * 1000.0 / rr.finish_time_ms <= 18.0
              THEN 1
              ELSE 0
            END
          ) AS n_rec
        FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE rr.finish_position BETWEEN 1 AND 89
        GROUP BY course
        ORDER BY course
        """
    ).fetchall()
    for row in rec_by:
        print(
            f"  {row['course']}: kept={row['n_rec']}/{row['n_normal']} "
            f"loss={pct(row['n_normal'] - row['n_rec'], row['n_normal'])}"
        )

    # 3IQR drop additional
    n_3iqr_in_rec = 0
    n_rec_python = 0
    for (course, meet, distance_m), times in groups.items():
        ts = sorted(times)
        q1 = percentile(ts, 25)
        q3 = percentile(ts, 75)
        iqr = q3 - q1
        lo3 = q1 - 3 * iqr
        hi3 = q3 + 3 * iqr
        for t in times:
            speed = distance_m * 1000.0 / t
            if meet == 2:
                ok = 10.0 <= speed <= 13.5
            else:
                ok = 12.0 <= speed <= 18.0
            if ok:
                n_rec_python += 1
                if t < lo3 or t > hi3:
                    n_3iqr_in_rec += 1
    print(
        f"of course-band kept, additional 3IQR drop={n_3iqr_in_rec} "
        f"(kept would be {n_rec_python - n_3iqr_in_rec}/{tot['n']})"
    )

    conn.close()
    print("done")


if __name__ == "__main__":
    main()
