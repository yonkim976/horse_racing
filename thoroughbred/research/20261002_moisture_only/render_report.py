"""Render the saved study summary and a static scientific figure."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/horse-racing-moisture-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
MEETS = {1: "서울", 3: "부산"}
PARTS = {
    "start_200": "출발200m",
    "last_200": "마지막200m",
    "last_600": "마지막600m",
    "finish": "전체시간",
}


def interval(ci):
    return "근거 부족" if ci is None else f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    primary, sensitivity = (summary["scenarios"][name] for name in ("quality_filtered", "all_api"))
    next_frame = pd.read_parquet(OUT / "quality_filtered/next_evaluation.parquet")
    next_frame = next_frame[next_frame.scope.eq("all_previous_dates")].copy()
    next_frame["delta"] = next_frame.fixed_day - next_frame.fixed_none
    cells = (
        next_frame.groupby(["meet", "part", "distance_m", "prev_band"])
        .agg(
            runs=("delta", "size"), source_days=("prev_day_key", "nunique"), delta=("delta", "mean")
        )
        .reset_index()
    )
    cells = cells[cells.runs.ge(30) & cells.source_days.ge(20)]
    cells.to_csv(OUT / "quality_filtered/next_exploratory_cells.csv", index=False)
    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 11}
    )
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    labels = ["양호\n6–9%", "다습\n10–14%", "포화\n15–19%", "불량\n20% 이상"]
    bands = ["양호", "다습", "포화", "불량"]
    for ax, part in zip(axes.flat, PARTS, strict=True):
        for meet, offset, color in ((1, -0.08, "#2463a6"), (3, 0.08, "#da6b31")):
            rows = [
                next(
                    r
                    for r in primary["contrasts"]
                    if r["meet"] == meet
                    and r["part"] == part
                    and r["distance_m"] == 1200
                    and r["exposure"] == "band"
                    and r["level"] == band
                )
                for band in bands
            ]
            estimates = [r["seconds"] for r in rows]
            errors = [
                [r["seconds"] - r["ci95"][0] for r in rows],
                [r["ci95"][1] - r["seconds"] for r in rows],
            ]
            ax.errorbar(
                [i + offset for i in range(4)],
                estimates,
                yerr=errors,
                fmt="o",
                capsize=4,
                color=color,
                label=MEETS[meet],
                markersize=5,
            )
        ax.axhline(0, color="#7c8795", linewidth=1)
        ax.set_xticks(range(4), labels)
        ax.set_title(PARTS[part], loc="left", fontweight="bold")
        ax.set_ylabel("건조 대비 시간 차이 (초)")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.15)
    axes[0, 0].legend(frameon=False)
    fig.suptitle("1200m 함수율 구간별 관찰 차이", fontsize=17, x=0.08, ha="left")
    fig.text(
        0.08,
        0.025,
        "점: 말별 사전 기대시간을 뺀 잔차의 조건별 차이 · 막대: 경주일 군집 95% 근사구간\n음수는 건조보다 빠른 방향. 개별 말의 확정 주로 효과를 뜻하지 않음.",
        fontsize=10,
        color="#475569",
    )
    fig.tight_layout(rect=(0, 0.08, 1, 0.94))
    fig.savefig(OUT / "moisture_1200m.png", dpi=180, facecolor="white")
    plt.close(fig)

    lines = [
        "# 함수율 기반 주로환경 후속 연구 — 1차 결과",
        "",
        "작성일: 2026-10-02 · 서울·부산 · 연구용, 운영 미적용",
        "",
        "## 연구과제와 판단",
        "",
        "주로빠르기를 완전히 제외하고, 과거 경주기록에 섞인 함수율별 공통 시간 차이를 다시 추정했다. 다음 경주 예측까지 좋아지는지는 별도 질문으로 검증했다.",
        "",
        "**함수율에 따른 관찰 차이는 확인됐고, 전체시간·출발200m의 경주 공통 잔차 예측에도 도움이 됐다. 다만 직전 잔차를 보정해 기존 기대시간에 더하는 방식은 다음 경주 예측을 개선하지 못했다.** 과거 기록 해석용 추정은 추가 검증 필요, 운영 자동 보정은 사용 보류다.",
        "",
        "## 방식과 표본",
        "",
        "[결과 확인 전 고정한 계획](PLAN.md)에 따라 새 API 자료의 숫자 함수율로 건조 1~5%, 양호 6~9%, 다습 10~14%, 포화 15~19%, 불량 20% 이상을 유도했다. 실제 원문 상태는 품질 표시에만 사용했다. 주로빠르기·tempo_raw는 모델·보정식·평가에 사용하지 않았다.",
        "",
        f"원자료는 2018-01-01~2026-09-20 정상 완주 출전행 {sensitivity['runners']:,}개다. 주 분석은 상태·숫자 충돌 70경주와 유효시간 원문이 다른 서울 12경주의 합집합 **{summary['excluded_races']}경주·{summary['excluded_runners']:,}행**을 제외한 **{primary['runners']:,}행**이다. 모두 포함한 API 원문 분석도 민감도로 수행했다.",
        "",
        f"목표별 이전 동일 거리 기록이 있는 출전에서 연도 외부 예측 잔차 {primary['horse_residuals']:,}개를 만들고, 기대시간 적격 말 4두 이상인 경주·목표 조합 {primary['race_residuals']:,}개를 분석했다. 한 경주가 네 목표에 반복 포함되므로 이 두 수는 고유 출전수·고유 경주수가 아니다.",
        "",
        "기대시간은 경기장·정확한 거리의 직전 1·2회 시간, 1~365일 출전 간격, 등급·월·부담중량·마번 대용 게이트로 Ridge α=20을 학습했다. 경주 실제시간·해당 경주 함수율은 이 기대시간 입력에 없다. 대상 연도 이전 자료로만 학습·전처리했다. 경주 공통 변동은 말별 `실제시간 − 기대시간`의 중앙값이다.",
        "",
        "공통 잔차 예측은 동일한 거리·월·연도추세·경주번호 통제에 `함수율 없음 / 선형 % / 숫자 기반 5구간 / 5구간+정수 %`를 추가한 Ridge α=25로 비교했다. 2024~2026년은 이미 관찰한 후향 평가 기간이며 새 독립 테스트가 아니다.",
        "",
        "설명용 관찰 차이는 2020~2026년 외부 예측 잔차를 모아 거리·연도·월·경주번호를 조정한 OLS다. 경주마다 같은 비중을 주고, 경주일 군집 95% 근사구간을 계산했다. 조건과 기준 각각 20일 미만이면 근거 부족으로 표시한다. 표시 구간은 다중비교 보정 없이 계산한 근사구간이다.",
        "",
        "## 함수율 구간별 대략적인 초 차이",
        "",
        "아래는 **1200m, 건조 1~5% 대비** 차이다. 양수는 느린 방향, 음수는 빠른 방향이다. 전체기간의 관찰 추정치이며 운영 보정표가 아니다. 마지막200m와 마지막600m는 중첩되므로 더하지 않는다.",
        "",
        "![1200m 함수율 구간별 차이](outputs/moisture_1200m.png)",
        "",
        "| 경기장·구간 | 비교 경주/경주일 | 출발200m | 마지막200m | 마지막600m | 전체시간 | 전체시간 95% 구간 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for meet in MEETS:
        for band in bands:
            rows = {
                part: next(
                    r
                    for r in primary["contrasts"]
                    if r["meet"] == meet
                    and r["part"] == part
                    and r["distance_m"] == 1200
                    and r["exposure"] == "band"
                    and r["level"] == band
                )
                for part in PARTS
            }
            r = rows["finish"]
            lines.append(
                f"| {MEETS[meet]}·{band} | {r['races']:,}/{r['days']}일 | "
                + " | ".join(f"{rows[p]['seconds']:+.3f}" for p in PARTS)
                + f" | {interval(r['ci95'])} |"
            )
    lines.extend(
        [
            "",
            "건조의 기준 경주일은 서울 218일·부산 336일이다. 포화는 서울 약 0.55초·부산 약 0.71초, 불량은 서울 약 1.32초·부산 약 1.10초 빠른 방향이었다. 반면 양호의 전체시간 차이는 양수이고 구간이 0을 포함한다. 함수율이 증가할 때마다 기록이 일정하게 빨라진다는 단조·선형 규칙은 확인한 것이 아니다.",
            "",
            "불량은 기존 함수율 결측을 복구한 뒤 1200m에서 서울 38일·부산 29일의 기대시간 적격 경주가 분석됐다. 모든 거리를 모은 전체시간 잔차에서는 서울 41일·부산 33일이다. 따라서 이전 연구의 서울 11일·부산 7일보다 표본 근거가 늘었다. 기존 숫자와의 차이는 원천·표본·품질 계약 변경이 섞인 것이므로 원천 하나의 개선 효과로 해석하지 않는다.",
            "",
            "정수 %별 관찰 차이는 [전체 추정치](outputs/quality_filtered/contrasts.json)에 4% 기준으로 보존했다. **23%는 서울 3경주·1일뿐**이므로 별도 확정 보정값으로 사용하지 않는다. 20이라는 숫자의 실제 정밀도·상한 표시 관행도 확정되지 않아 고함수율의 세밀한 물리 반응으로 해석하기 어렵다.",
            "",
            "## 시간순 검증 ① — 경주 공통 잔차",
            "",
            "MAE(초)는 작을수록 좋다. 실제 경주의 잔차는 평가용 정답이며 예측 입력이 아니다.",
            "",
            "| 경기장 | 목표 | 평가 경주 | 없음 | 선형 % | 5구간 | 5구간+정수 % |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for r in primary["race_validation"]:
        if r["year"] == "all":
            lines.append(
                f"| {MEETS[r['meet']]} | {PARTS[r['part']]} | {r['n']:,} | "
                + " | ".join(f"{r['mae'][v]:.4f}" for v in ("none", "linear", "band", "exact"))
                + " |"
            )
    lines.extend(
        ["", "| 전체시간, 5구간−없음 | MAE 차이 | 경주일 부트스트랩 95% 구간 |", "|---|---:|---|"]
    )
    for r in primary["race_validation"]:
        if r["year"] == "all" and r["part"] == "finish":
            delta = r["deltas"]["band"]
            lines.append(
                f"| {MEETS[r['meet']]} | {delta['mae_difference']:+.4f}초 | {interval(delta['day_cluster_ci95'])} |"
            )
    lines.extend(
        [
            "",
            "서울·부산 전체시간은 세 평가연도 각각에서도 구간 모델이 함수율 없는 기준보다 나았다. 출발200m도 개선 방향과 경주일 구간이 유지됐다. 막판 구간의 구간 모델 개선은 작고 구간이 0을 포함한다. 부산 막판200·600에서는 정수 % 추가가 구간 모델보다 오히려 나빴다.",
            "",
            "서울 전체시간에서는 선형 % 모델의 평균 오차가 가장 작았고 부산에서는 구간 모델이 가장 작았다. 이것만으로 물리적 효과가 선형이라는 결론을 내리지 않는다. 정수 % 세분화는 경기장·목표에 걸쳐 안정적인 추가 이득을 보이지 않았으므로, 현 단계의 설명 단위는 넓은 함수율 구간을 기본으로 유지한다.",
            "",
            "## 시간순 검증 ② — 말의 다음 경주",
            "",
            "각 과거 경주의 조건 보정계수는 그 **과거 경주 연도 이전** 자료만 사용해 고정했다. 당일 잔차 후보는 그 경주를 뺀 다른 완료 경주 최소 3개의 값을 경주번호 간격으로 가중·수축했다. 이를 이용하는 다음 경주는 반드시 이후 날짜다. 자기 경주 결과는 자기 조건 계수·당일 효과를 만들지 않는다.",
            "",
            "바로 직전 동일 거리 기록 자체에 기대시간이 없는 경우 제외했고, 다른 과거 출전을 대신 직전 출전으로 바꾸지 않았다. 다음 경주 기대시간에 `0.5 × (직전 잔차 − 보정효과)`를 추가한 고정 비교다. 기대시간은 이미 직전 1·2회 원시기록을 사용하므로 추가 잔차 반영의 유용성과 환경 보정의 유용성을 구분해야 한다.",
            "",
            "다음 표는 **직전 경주가 이전 연도인 제한 표본**이다.",
            "",
            "| 경기장 | 목표 | 다음 출전 | 기대시간만 | 직전 잔차 그대로 | 구간 보정 | 정수 % 보정 | 구간+다른 경주 당일 |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for r in primary["next_validation"]["cross_year"]:
        if r["year"] == "all":
            lines.append(
                f"| {MEETS[r['meet']]} | {PARTS[r['part']]} | {r['n']:,} | "
                + " | ".join(
                    f"{r['mae'][v]:.3f}"
                    for v in (
                        "expected_only",
                        "fixed_none",
                        "fixed_band",
                        "fixed_exact",
                        "fixed_day",
                    )
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "직전 경주가 같은 연도여도 이전 날짜의 완료 경주이면 포함한 확대 표본에서도 결론은 같다.",
            "",
            "| 전체시간 확대 표본 | 다음 출전 | 기대시간만 | 직전 잔차 그대로 | 구간+당일 보정 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for r in primary["next_validation"]["all_previous_dates"]:
        if r["year"] == "all" and r["part"] == "finish":
            lines.append(
                f"| {MEETS[r['meet']]} | {r['n']:,} | {r['mae']['expected_only']:.3f} | {r['mae']['fixed_none']:.3f} | {r['mae']['fixed_day']:.3f} |"
            )
    lines.extend(
        [
            "",
            "네 목표·두 경기장 모두 기대시간만 쓰는 기준이 가장 정확했다. 각 보정 후보의 잔차 반영률을 {0,0.25,0.5,0.75,1} 중 **이전 평가연도**에서만 선택해도, 모든 경기장·목표·평가연도·범위에서 0이 선택됐다. 따라서 0.5라는 고정 반영률만의 문제로 설명하기도 어렵다. 다만 이는 기존 기대시간에 잔차를 덧붙이는 구조의 결과다. 과거 기록 피처 자체를 환경 보정값으로 바꿔 모델을 재학습한 결과는 아니다.",
            "",
            "## 품질 제외의 민감도와 실패 사례",
            "",
            "82경주를 전부 포함해도 포화·불량이 빠른 방향, 전체시간·출발200m의 잔차 예측 개선, 다음 경주 기대시간 기준의 우위가 유지됐다.",
            "",
            "| 1200m 전체시간 관찰 차이 | 주 분석 | 모두 포함 |",
            "|---|---:|---:|",
        ]
    )
    for meet in MEETS:
        for band in ("포화", "불량"):
            values = [
                next(
                    r["seconds"]
                    for r in scenario["contrasts"]
                    if r["meet"] == meet
                    and r["part"] == "finish"
                    and r["distance_m"] == 1200
                    and r["exposure"] == "band"
                    and r["level"] == band
                )
                for scenario in (primary, sensitivity)
            ]
            lines.append(f"| {MEETS[meet]}·{band} | {values[0]:+.3f} | {values[1]:+.3f} |")
    lines.extend(
        [
            "",
            "전체시간 공통 잔차의 구간 MAE는 모두 포함 시 서울 0.7260초·부산 0.8447초였다. 주 분석과 방향이 같다. 정수 % 추가는 모두 포함한 부산 전체시간에서는 구간 모델과 거의 같지만, 안정적 추가 이득으로 판단할 크기와 불확실성 근거는 없었다.",
            "",
            "다음 경주의 거리×직전 함수율 구간별 악화 사례는 [탐색적 세부 집계](outputs/quality_filtered/next_exploratory_cells.csv)에 보존했다. 평가 후 살펴본 하위집단이므로 확정 규칙이나 새로운 독립 검증으로 취급하지 않는다. 30출전·직전 경주일 20일 이상인 집단만 표시한다.",
            "예를 들어 직전 경주가 서울 2000m 건조인 153회 다음 출전(직전 경주일 26일)의 마지막600m에서는 구간+당일 후보가 직전 잔차 그대로 반영하는 후보보다 MAE +0.013초 악화했다. 해당 집단 마지막200m도 +0.009초 악화했다. 작은 탐색적 차이이며 개별 조건의 확정 실패 규칙은 아니다.",
            "",
            "## 해석과 다음 연구",
            "",
            "- **추가 검증 필요:** 완료된 과거 기록을 해석할 때 함수율 구간별 관찰 차이·표본·불확실성을 함께 표시한다. 공식 원시기록은 보존한다. `보정기록 = 원시기록 − 추정 환경효과`에서 음의 효과는 빠르게 나온 방향이다. 예컨대 관찰 차이가 −0.55초이면 건조 기준 기술적 환산은 원시값에 0.55초를 더하는 방향이나, 해당 말이 실제로 그만큼 이득을 봤다는 판정은 아니다.",
            "- **사용 보류:** 기존 기대시간에 직전 잔차를 보정해 추가하는 운영 방식. 다음 경주 성능 개선 근거가 없다. 우승·Top2·Top3·추천 조합 성능은 이번에 평가하지 않았다.",
            "- **다음 가설:** 보정값을 기대시간에 추가하는 대신, 학습에 들어가는 과거 기록 피처 자체를 당시 이용 가능한 환경 보정기록으로 교체해 재학습한다. 원시기록 기준과 같은 평가 경주에서 비교하고, 구간별·거리별 반응 및 전개·참가마 구성의 영향을 더 분리한다.",
            "",
            "현재 잔차에는 훈련·컨디션·부상·기수·편성·전개·관리·날씨의 미설명 차이가 섞인다. 당일 공통 잔차도 주로의 물리 영향만을 뜻하지 않는다. 경주일 군집 구간은 반복 출전한 같은 말의 모든 의존성이나 구조적 편향을 없애지 않는다. 기수·게이트의 역사적 공개 시점과 새 API 메타정보의 사전 이용 가능성도 별도 계약 검증이 필요하다.",
            "",
            "## 재현·검증",
            "",
            "```bash",
            "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261002_moisture_only/analyze.py",
            "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261002_moisture_only/render_report.py",
            ".venv/bin/ruff check thoroughbred/research/20261002_moisture_only/*.py",
            "```",
            "",
            "분석은 기존 outputs가 있으면 덮어쓰지 않고 중단한다. 새 실행은 복사한 코드의 새 버전 출력 경로에서 수행한다. 입력 스냅샷 해시는 [전체 요약](outputs/summary.json)에 기록했고 실행 전후 동일했다. 원천 DB·등록부·기존 연구는 수정하지 않았다.",
            "",
            "직전 말·경주 연결의 유일성, `prev_target == prev_time`, 이전 날짜 조건, 기대시간/환경계수의 이전 연도 조건, 평가 범위 내 키 중복 부재를 검사했다. 주 분석과 민감도 모두 통과했다. 코드 검사도 통과했다. 입력·잔차·평가·계수 Parquet와 전체 결과 JSON은 로컬 outputs에 남기고 Git에서는 제외한다.",
            "",
        ]
    )
    (HERE / "README.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
