"""Look up a single record against immutable, versioned benchmark distributions."""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
GRADES = ["국6", "국5", "국4", "혼4", "국3", "혼3", "2", "1", "국OPEN", "혼OPEN"]
BANDS = ["건조", "양호", "다습", "포화", "불량"]
PARTS = ["finish", "early", "middle1", "middle2", "late", "last600", "last400"]


def percentile_score(reference, time):
    values = np.asarray(reference, dtype=float)
    values = np.round(values[np.isfinite(values)], 9)
    time = np.round(time, 9)
    if not len(values):
        raise ValueError("No observed reference for this section")
    return float(
        100
        * (
            np.count_nonzero(values > time + 1e-7)
            + 0.5 * np.count_nonzero(np.abs(values - time) <= 1e-7)
        )
        / len(values)
    )


def evaluate(meet, grade, band, part, time):
    if (
        meet not in ["서울", "부산"]
        or grade not in GRADES
        or band not in BANDS
        or part not in PARTS
    ):
        raise ValueError("Unsupported venue, grade, state or section")
    if not math.isfinite(time) or time <= 0:
        raise ValueError("Time must be a finite positive number of seconds")
    if meet == "서울" and part == "last400":
        raise ValueError("Seoul has no direct last400 reference in this research")
    table = pd.read_csv(OUT / "estimated_benchmarks.csv")
    cell = table[
        table.meet.eq(meet) & table.grade.eq(grade) & table.band.eq(band) & table.part.eq(part)
    ]
    if len(cell) != 1:
        raise ValueError("Benchmark cell is unavailable")
    row = cell.iloc[0]
    ref = pd.read_parquet(OUT / "reference_dry_times.parquet")
    ref = ref[ref.meet.eq(meet)]
    dry_time = time - row.state_shift_from_dry
    own = ref.loc[ref.grade.eq(grade), part]
    own_score = percentile_score(own, dry_time)
    pooled_score = percentile_score(ref[part], dry_time)
    level = (
        "매우 빠름"
        if own_score >= 90
        else "빠름"
        if own_score >= 80
        else "보통 범위"
        if own_score >= 20
        else "느림"
        if own_score >= 10
        else "매우 느림"
    )
    return {
        "version": row.reference_version,
        "meet": meet,
        "distance_m": 1200,
        "grade": grade,
        "band": band,
        "section": part,
        "time_seconds": time,
        "same_grade_record_score": round(own_score, 2),
        "all_grade_distance_record_score": round(pooled_score, 2),
        "same_grade_level": level,
        "estimated_mean_seconds": round(float(row["mean"]), 3),
        "estimated_median_seconds": round(float(row["median"]), 3),
        "fast20_boundary_seconds": round(float(row.p20), 3),
        "slow20_boundary_seconds": round(float(row.p80), 3),
        "seconds_faster_than_mean": round(float(row["mean"] - time), 3),
        "estimated_dry_equivalent_seconds": round(float(dry_time), 3),
        "observed_rows_in_cell": int(row.observed_n),
        "reference_rows_in_grade": int(row.reference_n),
        "cell_status": row.status,
        "interpretation": (
            "One performance relative to reference times; not win probability or absolute ability"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="서울·부산1200m 한 번의 전체·구간 기록 평가")
    parser.add_argument("--meet", choices=["서울", "부산"], required=True)
    parser.add_argument("--grade", choices=GRADES, required=True)
    parser.add_argument("--band", choices=BANDS, required=True)
    parser.add_argument("--part", choices=PARTS, default="finish")
    parser.add_argument("--time", type=float, required=True, help="초 단위 원시 기록")
    args = parser.parse_args()
    try:
        result = evaluate(args.meet, args.grade, args.band, args.part, args.time)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
