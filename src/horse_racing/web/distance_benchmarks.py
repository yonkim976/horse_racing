"""Read-only 1,200m research reference tables packaged with the web app."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from horse_racing.web.formatting import format_distance_seconds

BENCHMARK_BANDS = ("건조", "양호", "다습", "포화", "불량")
RESEARCH_GRADES = ("국6", "국5", "국4", "혼4", "국3", "혼3", "2", "1", "국OPEN", "혼OPEN")
PART_ORDER = ("finish", "early", "middle1", "middle2", "late", "last600", "last400")
PART_LABELS = {
    "finish": "전체 1,200m",
    "early": "출발 200m · S1F",
    "middle1": "200–600m",
    "middle2": "600–1,000m",
    "late": "마지막 200m · G1F",
    "last600": "마지막 600m · G3F",
    "last400": "부산 마지막 400m",
}

_GRADE_TO_RESEARCH = {
    **{f"국{grade}등급": f"국{grade}" for grade in range(3, 7)},
    **{f"혼{grade}등급": f"혼{grade}" for grade in (3, 4)},
    "1등급": "1",
    "2등급": "2",
    "국OPEN": "국OPEN",
    "혼OPEN": "혼OPEN",
}
_RESEARCH_TO_GRADE = {value: key for key, value in _GRADE_TO_RESEARCH.items()}
_STATUS_LABELS = {
    "observed_supported": "관측 표본 충분",
    "small_recent_sample": "관측 소표본",
    "no_recent_observation": "관측 없음 · 추정 기준",
}
_ESTIMATE_FIELDS = (
    "meet",
    "distance",
    "grade",
    "band",
    "part",
    "status",
    "reference_version",
    "p20",
    "median",
    "middle60_mean",
    "p80",
    "mean",
    "fast20_mean",
    "fast20_n",
    "middle60_n",
    "slow20_mean",
    "slow20_n",
)
_OBSERVED_FIELDS = (
    "meet",
    "grade",
    "band",
    "part",
    "n",
    "races",
    "days",
    "p20",
    "median",
    "middle60_mean",
    "p80",
    "mean",
    "fast20_mean",
    "fast20_n",
    "middle60_n",
    "slow20_mean",
    "slow20_n",
)


@lru_cache(maxsize=1)
def _load_data() -> dict[str, Any]:
    path = Path(__file__).with_name("distance_1200_benchmarks.json")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _indexes() -> tuple[
    dict[tuple[str, str, str, str], dict],
    dict[tuple[str, str, str, str], dict],
]:
    data = _load_data()
    estimates = {
        (row["meet"], row["grade"], row["band"], row["part"]): row
        for row in data["benchmarks"]
    }
    observed = {
        (row["meet"], row["grade"], row["band"], row["part"]): row
        for row in data["observed_distribution"]
    }
    return estimates, observed


def _seconds(value: Any) -> str:
    return format_distance_seconds(value)


def _integer(value: Any) -> int:
    return 0 if value is None else int(value)


def _view_row(
    estimate: dict | None,
    observed: dict | None,
    *,
    meet: str,
    grade: str,
    band: str,
    part: str,
) -> dict[str, Any]:
    if estimate is None:
        observed = observed or {}
        return {
            "meet": meet,
            "grade": grade,
            "grade_label": _RESEARCH_TO_GRADE.get(grade, grade),
            "band": band,
            "part": part,
            "part_label": PART_LABELS[part],
            "status": "missing",
            "status_label": "기준 자료 없음",
            "observed_n": _integer(observed.get("n")),
            "observed_races": _integer(observed.get("races")),
            "observed_days": _integer(observed.get("days")),
            "p20": "—",
            "median": "—",
            "middle60_mean": "—",
            "p80": "—",
            "estimate_mean": "—",
            "observed_mean": _seconds(observed.get("mean")),
            "observed_median": _seconds(observed.get("median")),
            "observed_p20": "—",
            "observed_p80": "—",
            "fast20_mean": "—",
            "slow20_mean": "—",
            "estimate_fast20_n": _integer(estimate.get("fast20_n")) if estimate else 0,
            "estimate_middle60_n": _integer(estimate.get("middle60_n")) if estimate else 0,
            "estimate_slow20_n": _integer(estimate.get("slow20_n")) if estimate else 0,
            "fast20_n": _integer(observed.get("fast20_n")),
            "middle60_n": _integer(observed.get("middle60_n")),
            "slow20_n": _integer(observed.get("slow20_n")),
        }
    status = estimate["status"]
    observed = observed or {}
    return {
        "meet": meet,
        "grade": grade,
        "grade_label": _RESEARCH_TO_GRADE.get(grade, grade),
        "band": band,
        "part": part,
        "part_label": PART_LABELS[part],
        "status": status,
        "status_label": _STATUS_LABELS.get(status, "상태 미확인"),
        "observed_n": _integer(observed.get("n")),
        "observed_races": _integer(observed.get("races")),
        "observed_days": _integer(observed.get("days")),
        "p20": _seconds(estimate.get("p20")),
        "median": _seconds(estimate.get("median")),
        "middle60_mean": _seconds(estimate.get("middle60_mean")),
        "p80": _seconds(estimate.get("p80")),
        "estimate_mean": _seconds(estimate.get("mean")),
        "observed_mean": _seconds(observed.get("mean")),
        "observed_median": _seconds(observed.get("median")),
        "observed_p20": _seconds(observed.get("p20") if observed else None),
        "observed_p80": _seconds(observed.get("p80") if observed else None),
        "fast20_mean": _seconds(estimate.get("fast20_mean")),
        "slow20_mean": _seconds(estimate.get("slow20_mean")),
        "estimate_fast20_n": _integer(estimate.get("fast20_n")),
        "estimate_middle60_n": _integer(estimate.get("middle60_n")),
        "estimate_slow20_n": _integer(estimate.get("slow20_n")),
        "fast20_n": _integer(observed.get("fast20_n")),
        "middle60_n": _integer(observed.get("middle60_n")),
        "slow20_n": _integer(observed.get("slow20_n")),
    }


def build_distance_benchmark_view(
    *, meet_code: int, grade: str, band: str
) -> dict[str, Any] | None:
    """Return exact 1,200m research rows for Seoul/Busan, without pooling grades."""
    if meet_code not in {1, 3}:
        return None
    if band not in BENCHMARK_BANDS:
        raise ValueError("unsupported moisture band")

    meet = "서울" if meet_code == 1 else "부산"
    estimate_index, observed_index = _indexes()
    source = _load_data()["metadata"]

    def row_for(research_grade: str, row_band: str, part: str) -> dict[str, Any]:
        key = (meet, research_grade, row_band, part)
        return _view_row(
            estimate_index.get(key),
            observed_index.get(key),
            meet=meet,
            grade=research_grade,
            band=row_band,
            part=part,
        )

    if not grade:
        return {
            "meet": meet,
            "band": band,
            "grade": "",
            "grade_supported": True,
            "source": source,
            "summary_rows": [row_for(code, band, "finish") for code in RESEARCH_GRADES],
            "state_finish_rows": [],
            "detail_rows": [],
        }

    research_grade = _GRADE_TO_RESEARCH.get(grade)
    if research_grade is None or (meet, research_grade, band, "finish") not in estimate_index:
        return {
            "meet": meet,
            "band": band,
            "grade": grade,
            "grade_supported": False,
            "source": source,
            "summary_rows": [],
            "state_finish_rows": [],
            "detail_rows": [],
        }

    return {
        "meet": meet,
        "band": band,
        "grade": grade,
        "grade_supported": True,
        "source": source,
        "summary_rows": [],
        "state_finish_rows": [
            row_for(research_grade, row_band, "finish") for row_band in BENCHMARK_BANDS
        ],
        "detail_rows": [
            row_for(research_grade, band, part)
            for part in PART_ORDER
            if (meet, research_grade, band, part) in estimate_index
        ],
    }
