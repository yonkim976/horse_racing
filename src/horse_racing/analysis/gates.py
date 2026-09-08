"""Gate G1 judgement helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class G1Decision:
    passed: bool
    criteria: dict[str, bool]


def judge_g1(
    *,
    candidate: dict[str, float],
    baseline_b1: dict[str, float],
    baseline_b2: dict[str, float],
    meet_candidate: dict[str, dict[str, float]],
    meet_b1: dict[str, dict[str, float]],
    ablation_passed: bool,
) -> G1Decision:
    criteria = {
        "overall_b1_improvement_3pct": (
            candidate["log_loss"] <= baseline_b1["log_loss"] * 0.97
        ),
        "overall_beats_b2": candidate["log_loss"] < baseline_b2["log_loss"],
        "ece_at_most_003": candidate["ece"] <= 0.03,
        "seoul_b1_improvement_3pct": (
            meet_candidate["1"]["log_loss"] <= meet_b1["1"]["log_loss"] * 0.97
        ),
        "busan_b1_improvement_3pct": (
            meet_candidate["3"]["log_loss"] <= meet_b1["3"]["log_loss"] * 0.97
        ),
        "ablation_not_single_group": ablation_passed,
    }
    return G1Decision(passed=all(criteria.values()), criteria=criteria)


def render_g1_report(
    *,
    candidate_run_id: str,
    candidate: dict[str, float],
    baseline_b1: dict[str, float],
    baseline_b2: dict[str, float],
    meet_candidate: dict[str, dict[str, float]],
    meet_b1: dict[str, dict[str, float]],
    meet_b2: dict[str, dict[str, float]],
    decision: G1Decision,
    beta_b1: float,
    beta_b2: float,
) -> str:
    meet_names = {"1": "서울", "2": "제주", "3": "부산경남"}
    lines = [
        "# Gate G1 test 1회 판정",
        "",
        f"- 고정 후보 run_id: `{candidate_run_id}`",
        "- test split: 2026-06-01 이후",
        "- 이 리포트 생성으로 holdout test를 1회 사용했다.",
        f"- 판정: **{'PASS' if decision.passed else 'FAIL'}**",
        "",
        "## 전체 test",
        "",
        "| 모델 | log loss | AUC | ECE | Top1 | Top3 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in (("B1", baseline_b1), ("B2", baseline_b2), ("후보", candidate)):
        lines.append(
            f"| {name} | {metrics['log_loss']:.4f} | "
            f"{metrics.get('auc', float('nan')):.4f} | {metrics['ece']:.4f} | "
            f"{metrics['top1_hit_rate']:.4f} | {metrics['top3_inclusion_rate']:.4f} |"
        )
    lines.extend(
        [
            "",
            f"B1 beta={beta_b1:.6f}, B2 beta={beta_b2:.6f} (train에서만 적합).",
            "",
            "## 경마장별 test",
            "",
            "| 경마장 | B1 LL | B2 LL | 후보 LL | B1 대비 개선 | B2 대비 개선 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for meet_code in ("1", "2", "3"):
        b1 = meet_b1[meet_code]["log_loss"]
        b2 = meet_b2[meet_code]["log_loss"]
        model = meet_candidate[meet_code]["log_loss"]
        lines.append(
            f"| {meet_names[meet_code]} | {b1:.4f} | {b2:.4f} | {model:.4f} | "
            f"{(b1 - model) / b1:.2%} | {(b2 - model) / b2:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 판정 조건",
            "",
            "| 조건 | 결과 |",
            "|---|---|",
        ]
    )
    labels = {
        "overall_b1_improvement_3pct": "전체 B1 대비 log loss 3% 이상 개선",
        "overall_beats_b2": "전체 B2보다 낮은 log loss",
        "ece_at_most_003": "ECE ≤ 0.03",
        "seoul_b1_improvement_3pct": "서울 B1 대비 3% 이상 개선",
        "busan_b1_improvement_3pct": "부산경남 B1 대비 3% 이상 개선",
        "ablation_not_single_group": "특정 feature 그룹 독점 의존 없음",
    }
    for key, passed in decision.criteria.items():
        lines.append(f"| {labels[key]} | {'PASS' if passed else 'FAIL'} |")
    lines.extend(
        [
            "",
            "제주는 표본·경주 체계 차이 때문에 G1 필수 조건이 아니라 참고로만 본다.",
            "",
        ]
    )
    return "\n".join(lines)


def segment_rows_by_key(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    return {str(row["segment"]): row for row in rows}
