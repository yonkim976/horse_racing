"""Write a Korean research report and strength curves."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/horse-racing-moisture-strength-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
MEETS = {1: "서울", 3: "부산"}


def main():
    saved = json.loads((OUT / "summary.json").read_text())
    verification = json.loads((OUT / "verification.json").read_text())
    recommendation = {
        "status": "research_candidate_not_promoted",
        "target": "finish_seconds",
        "primary": saved["primary"],
        "track_speed_used": False,
        "environment_trained_through": 2025,
        "rate_selection_years": [2022, 2023, 2024, 2025],
        "selection_rule": "smallest_rate_within_0.002_seconds_of_minimum_validation_mae",
        "venue_rates": {
            str(s["meet"]): s["conservative"] for s in saved["selections"]
            if s["family"] == saved["primary"] and s["apply_year"] == 2026
        },
        "formula": "historical_finish_seconds + add_seconds_conservative",
        "requires_prediction_model_retraining": True,
        "supported_reference_cells": [r for r in saved["reference_seconds"] if r["supported"]],
        "unsupported_reference_cells": [r for r in saved["reference_seconds"] if not r["supported"]],
        "caution": "Retrospective research. Support-gated or rounded tables are not separately evaluated. No current-race or rank/return effect tested.",
    }
    (OUT / "recommendation.json").write_text(json.dumps(recommendation, ensure_ascii=False, indent=2))
    curves = pd.read_csv(OUT / "validation_curves.csv")
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 11})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7))
    for ax, (meet, name) in zip(axes, MEETS.items(), strict=True):
        for year, color in zip([2024, 2025, 2026], ["#9aa4b2", "#6394bd", "#165887"], strict=True):
            sample = curves[curves.meet.eq(meet) & curves.family.eq(saved["primary"]) & curves.apply_year.eq(year)]
            raw = float(sample[sample.rate.eq(0)].validation_mae.iloc[0])
            ax.plot(sample.rate * 100, sample.validation_mae - raw, label=f"{year} 적용률 선택용", color=color)
        choice = next(s for s in saved["selections"] if s["meet"] == meet and s["family"] == saved["primary"] and s["apply_year"] == 2026)
        ax.axvline(choice["best"] * 100, color="#df7830", linestyle=":", label=f"최소오차 {choice['best']:.0%}")
        ax.axvline(choice["conservative"] * 100, color="#248557", linestyle="--", label=f"보수적 {choice['conservative']:.0%}")
        ax.axhline(0, color="#333333", linewidth=0.7)
        ax.set_title(f"{name}: 이전 연도 검증곡선")
        ax.set_xlabel("함수율 추정 효과에 적용한 보정률 (%)")
        ax.set_ylabel("원시기록 대비 검증 MAE 차이 (초)")
        ax.grid(alpha=0.2)
        ax.legend(fontsize=8)
    fig.suptitle("함수율 보정률 선택 — 전체시간, 극단 잔차 제외", fontsize=14)
    fig.tight_layout()
    fig.savefig(OUT / "strength_curves.png", dpi=180)
    plt.close(fig)
    lines = ["# 함수율 보정률 탐색과 권장값", "", "2026-10-02. 주로빠르기를 제외한 전체 완주시간 연구. 운영 모델·원천 DB 미반영.", "", "## 권장률과 최소오차률", "", "2026 적용률은 2022~2025년의 시간순 예측 오차로 선택했다. 각 해의 예측모형은 이전 해까지 학습하고, 과거 경주의 환경계수도 그 경주의 이전 해까지 학습했다. 보수적 규칙은 선택기간 최저 MAE보다 0.002초 이내인 후보 중 가장 작은 보정률이다. 이 허용오차는 계산 전 고정한 실무 기준이며 신뢰구간이나 유의성 기준이 아니다.", "", "| 경기장 | 적용연도 | 선택기간 | 최소오차률 | 보수적률 | 검증 최소 MAE | 보수적 MAE |", "|---|---:|---|---:|---:|---:|---:|"]
    for s in saved["selections"]:
        if s["family"] == saved["primary"]:
            lines.append(f"| {MEETS[s['meet']]} | {s['apply_year']} | 2022~{s['selection_end']} | {s['best']:.0%} | {s['conservative']:.0%} | {s['minimum_mae']:.6f} | {s['conservative_mae']:.6f} |")
    lines += ["", "## 선택 규칙을 다음 연도에 적용한 성능", "", "현재 평가 정답은 추가 절단하지 않았다. 2024~2026년 합계 36,931두로 앞선 연구와 동일한 표본이다. 괄호는 원시기록 대비 MAE 차이의 경주일 군집 부트스트랩 95% 구간이다.", "", "| 경기장 | 평가기간 | 두수 | 원시 MAE | 최소오차 선택 MAE | 보수적 선택 MAE | 보수적 차이 [95%] |", "|---|---|---:|---:|---:|---:|---|"]
    for r in saved["evaluation"]:
        if r["distance_m"] is None:
            c = r["conservative"]
            lines.append(f"| {MEETS[r['meet']]} | {r['year']} | {r['n']:,} | {r['raw_mae']:.6f} | {r['best']['mae']:.6f} | {c['mae']:.6f} | {c['delta']:+.6f} [{c['ci95'][0]:+.6f}, {c['ci95'][1]:+.6f}] |")
    lines += ["", "## 건조 기준 과거시간 환산표", "", "2025년까지의 극단 잔차 제외 거리×함수율 계수에 위 2026 선택률을 적용했다. 건조 1~5%, 양호 6~9%, 다습 10~14%, 포화 15~19%, 불량 20% 이상. 1%마다 고정 선형 초를 붙이는 방식이 아니다. 표의 초를 과거 원시 완주시간에 더한다. 다른 함수율 사이에서 비교하려면 각각 건조 기준으로 바꾼 후 비교한다.", "", "| 경기장 | 거리 | 함수율 구간 | 보수적 가산 초 | 최소오차 가산 초 | 해당/건조 경주일 | 지원 |", "|---|---:|---|---:|---:|---|---|"]
    for r in saved["reference_seconds"]:
        if r["distance_m"] in [1000, 1200, 1300, 1400, 1600, 1700, 1800, 2000] and r["band"] != "건조":
            lines.append(f"| {MEETS[r['meet']]} | {r['distance_m']} | {r['band']} | {r['add_seconds_conservative']:+.3f} | {r['add_seconds_best']:+.3f} | {r['band_days']}/{r['dry_days']} | {'충분' if r['supported'] else '부족 — 권장 보류'} |")
    lines += ["", "지원 기준은 해당 거리의 함수율 조건·건조 경주일 각각20일 이상이다. 숫자가 표에 있더라도 지원 부족인 셀은 권장하지 않는다. 실제 시간순 예측 비교는 앞선 연구와 같이 전체 적격 셀의 Ridge 추정치를 사용했고, 위 표의 지원 제한으로 별도 재평가한 결과가 아니다. 반올림 표 자체를 다시 학습해 검증하지 않았으므로 실제 연구 구현은 원 계수와 보정률을 사용한다.", "", "## 이상치 방식 민감도", "", "주 분석은 말별 4 robust SD 이상 잔차 제외와 거리×함수율 효과로 계산 전에 고정했다. 다른 방법에서 평가기간 성적이 좋다는 이유로 주 분석을 교체하지 않았다. 아래는 2026 적용률을 고르는 2022~2025 선택기간의 최소오차률이다.", "", "| 경기장 | 방식 | 최소오차률 | 보수적률 | 선택기간 최소 MAE |", "|---|---|---:|---:|---:|"]
    for s in saved["selections"]:
        if s["apply_year"] == 2026:
            lines.append(f"| {MEETS[s['meet']]} | {s['family']} | {s['best']:.0%} | {s['conservative']:.0%} | {s['minimum_mae']:.6f} |")
    lines += ["", "## 검증과 해석 한계", "", "- 0~300%를10% 간격으로 비교했다. 100%를 넘는 값은 추정 효과의 확대를 허용한 예측용 강도이며 그 비율만큼 물리적 함수율 효과가 확정됐다는 뜻이 아니다.", "- 거리별·등급별 보정률은 따로 최적화하지 않았다. 거리별 환경계수는 유지하되 경기장별 보정률 하나를 사용한다. 앞선 등급 차이 검정에서 확실한 차이가 없어 등급별 가산은 만들지 않았다.", "- 과거1·2회 기록의 피처를 환산한 뒤 모형을 재학습한 실험이다. 기존 모형 예측값에 표의 초만 사후 가산하는 실험이 아니다. 현 경주의 함수율 효과를 예측에 더하는 절차도 이번에 검증하지 않았다.", "- 2024~2026년은 이미 이전 단계에서 관찰한 후향 기간이다. 시간순 분리를 지켰지만 새 미래 검증 결과는 아니다. 원시시간 MAE의 작은 개선이며 순위·입상·수익 개선을 주장하지 않는다.", "- 원시기록 및 기존100% 예측 재현, 모든 후보 오차 재계산, 모든 선택 재계산, 동일한 정답·평가행, 이전연도만 사용, 입력 SHA-256 동일을 확인했다. 보수적 선택 모형6개를 별도로 재학습해 예측을 재현했다.", "", f"독립 재현: {len(verification['six_reconstructed_folds'])}개 경기장·연도 모형. 자세한 수치는 [summary.json](outputs/summary.json), [검증](outputs/verification.json), [환산표 CSV](outputs/reference_seconds.csv).", "", "![이전 연도 선택곡선](outputs/strength_curves.png)", ""]
    (HERE / "README.md").write_text("\n".join(lines))
    print(str(HERE / "README.md"))


if __name__ == "__main__":
    main()
