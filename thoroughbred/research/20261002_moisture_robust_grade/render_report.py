"""Render robust effects, conservative-reference ranges and grade evidence."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/horse-racing-moisture-robust-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
MEETS = {1: "서울", 3: "부산"}
METHODS = {
    "baseline": "기존 중앙값",
    "horse_mad4": "말별 극단 잔차 제외",
    "horse_trim1": "말별 양쪽 1% 제외",
    "horse_trim5": "말별 양쪽 5% 제외",
    "race_mad4": "경주 극단 잔차 제외",
}


def cell(saved, method, meet, band, grade=None):
    return next(
        r
        for r in saved["scenarios"][method]["descriptive"]
        if r["meet"] == meet
        and r["part"] == "finish"
        and r["distance_m"] == 1200
        and r["grade"] == grade
        and r["level"] == band
    )


def interval(ci):
    return "지원 부족" if ci is None else f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"


def main():
    saved = json.loads((OUT / "summary.json").read_text())
    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 10}
    )
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True)
    for row_index, (meet, name) in enumerate(MEETS.items()):
        for column_index, band in enumerate(["포화", "불량"]):
            ax = axes[row_index, column_index]
            values = [cell(saved, method, meet, band) for method in METHODS]
            estimates = [r["seconds"] for r in values]
            ax.errorbar(
                estimates,
                range(5),
                xerr=[
                    [r["seconds"] - r["ci95"][0] for r in values],
                    [r["ci95"][1] - r["seconds"] for r in values],
                ],
                fmt="o",
                color="#2463a6",
                capsize=4,
            )
            ax.set_yticks(range(5), list(METHODS.values()))
            ax.invert_yaxis()
            ax.axvline(0, color="#7c8795", linewidth=1)
            ax.set_title(f"{name} · {band}", loc="left")
            ax.set_xlabel("건조 대비 전체시간 차이 (초)")
            ax.set_xticks([-1.5, -1, -0.5, 0])
            ax.grid(axis="x", alpha=0.15)
            ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("1200m 함수율 관찰 차이 — 이상치 제외 민감도", x=0.07, ha="left", fontsize=16)
    fig.text(
        0.07,
        0.018,
        "음수: 건조보다 빠른 방향 · 막대: 경주일 군집 95% 근사구간\n양쪽 5% 제외는 유효한 환경 반응도 지울 수 있는 강한 선별. 개별 말의 확정 환산값을 뜻하지 않음.",
        fontsize=9,
        color="#475569",
    )
    fig.tight_layout(rect=(0, 0.08, 1, 0.94))
    fig.savefig(OUT / "robust_1200m.png", dpi=180, facecolor="white")
    plt.close(fig)
    lines = [
        "# 함수율 보수적 환산·이상치·등급 검증",
        "",
        "작성일: 2026-10-02 · 주로빠르기 제외 · 원천/운영 미변경",
        "",
        "## 판단",
        "",
        "**함수율 조건별 평균 기록 차이는 이상치 제외 후에도 남는다. 다만 그 평균을 개별 말에 100% 적용할 확정 물리 환산값으로 볼 수는 없다. 25~50% 부분 반영은 작은 예측 개선을 유지하는 연구 후보다. 등급별 별도 환산계수를 확정할 근거는 아직 부족하다.**",
        "",
        "전체시간 1200m에서 원래 포화 효과는 서울 −0.551초·부산 −0.705초였다. 같은 거리·등급·연도 기대잔차의 양쪽 5%를 제외해도 서울 −0.441초·부산 −0.517초가 남았다. 불량도 서울 −1.318→−0.969초, 부산 −1.100→−0.754초로 작아지지만 빠른 방향이 유지됐다. 효과가 전부 극단 기록 몇 개에서 생겼다고 보기는 어렵다.",
        "",
        "기록의 '틀린 값 제거'와 '통계적으로 극단적인 유효 기록 제거'를 구분해야 한다. 후자는 함수율의 실제 큰 반응·컨디션 급변·과거 기록 이상에서 생긴 기대시간 오차까지 자를 수 있다. 제거 후 계수가 작아진다고 그 값이 자동으로 진짜 물리 효과가 되는 것은 아니다.",
        "",
        "## 기존에 제외했던 것",
        "",
        "앞선 연구는 정상순위 1~20·양수 완주 기록에서 API 상태/숫자 충돌 70경주와 유효시간 원문 차이 12경주의 합집합 82경주·953행을 제외했다. 두 원문의 차이가 모두 원천 오류라고 판정한 것은 아니며 품질 불확실성 때문에 분리한 것이다. 이 제외를 풀어도 앞선 주 결과 방향은 유지됐다.",
        "",
        "넓은 시간 유효범위도 적용했다. 출발200m 10~40초, 마지막200m 8~45초, 마지막600m 30~100초이며 각 구간은 전체시간보다 작아야 하고 마지막200m가 마지막600m보다 크면 두 구간을 결측 처리했다. 전체시간은 거리/시간의 평균 주행속도가 10~20m/s 범위인지 확인했다. 이 검사에 쓰인 주행속도는 제외한 마사회 주로빠르기 지표와 다른 값이다.",
        "",
        "경주 잔차는 적격 말 4두 이상에서 말별 잔차의 중앙값을 사용해 소수 극단 말의 영향을 줄였다. 하지만 기존에는 상하위 1%·5% 등의 통계적인 꼬리 절단을 하지 않았다. 예컨대 전체시간 기대잔차는 −31.10~+44.24초까지 남아 있었다. 원시 기록 자체가 그만큼 비정상이라는 뜻은 아니며 기대시간에 들어간 과거 기록의 문제도 섞일 수 있다.",
        "",
        "## 이번 추가 제외 기준",
        "",
        "[결과 계산 전에 고정한 계약](PLAN.md)을 따랐다. 원시 전체시간을 거리 구분 없이 자르지 않고, 연도 외부 모형의 `실제시간−기대시간` 잔차를 같은 경기장·목표·정확한 거리·등급·연도로 나눠 판별했다. 말별 100행/경주별 30행 미만이면 등급, 그다음 거리 구분을 빼는 사전 고정된 보완 분포를 사용했다.",
        "",
        "말별 극단 잔차는 중앙값±4×(1.4826×MAD) 범위를 벗어난 경우다. 말별 양쪽 1%·5%는 같은 분포의 분위수 밖을 제외했다. 경주 극단 잔차는 경주 중앙값 자체를 같은 방식으로 검사했다. 작은 분산을 위한 최저 robust SD와 모든 분포 보완 규칙은 계획 및 코드에 고정했다. 제거된 행과 기준·방향을 filter_ledger.parquet에 보존했다.",
        "",
        "전체시간 적격 말별 기대잔차 82,791행에서 제거량은 다음과 같다. 이 수는 원천 전체 출전수와 다르다. 경주 단위는 전체시간 9,731개의 경주 중앙값을 기준으로 한다. 1%·5%는 그룹별 명목 분위수이므로 실제 합산 제거율은 정확히 2%·10%와 같지 않다.",
        "",
        "| 추가 기준 | 빠른 쪽 제외 | 느린 쪽 제외 | 합계 | 제거율 |",
        "|---|---:|---:|---:|---:|",
    ]
    for method in METHODS:
        coverage = [r for r in saved["scenarios"][method]["coverage"] if r["part"] == "finish"]
        fast, slow, total = (
            sum(r[k] for r in coverage) for k in ["fast_removed", "slow_removed", "input_rows"]
        )
        lines.append(
            f"| {METHODS[method]} | {fast:,} | {slow:,} | {fast + slow:,} | {(fast + slow) / total * 100:.2f}% |"
        )
    lines += [
        "",
        "## 1200m 이상치 제외 후 평균 차이",
        "",
        "건조 대비 초 단위 관찰 차이다. 음수는 빠른 방향이다. 원래와 동일하게 연도·월·경주번호를 조정하고 경주일 군집 95% 근사구간을 계산했다. 모든 방법에서 아래 네 조건의 지원 기준과 음수 구간이 유지됐다.",
        "",
        "| 경기장·조건 | 기존 | 말별 극단 제외 | 양쪽 1% 제외 | 양쪽 5% 제외 | 경주 극단 제외 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for meet in MEETS:
        for band in ["포화", "불량"]:
            lines.append(
                f"| {MEETS[meet]}·{band} | "
                + " | ".join(
                    f"{cell(saved, method, meet, band)['seconds']:+.3f}" for method in METHODS
                )
                + " |"
            )
    lines += [
        "",
        "![1200m 이상치 제외 민감도](outputs/robust_1200m.png)",
        "",
        "양쪽 5% 제외의 95% 구간은 서울 포화 [−0.596, −0.287], 불량 [−1.158, −0.779], 부산 포화 [−0.736, −0.298], 불량 [−0.995, −0.514]초였다. 말별 극단 잔차만 제외하는 완만한 방법에서는 변화가 작았고, 전체시간의 느린 쪽 445행·빠른 쪽 113행을 제외했다.",
        "",
        "## 보수적인 참고 환산 범위",
        "",
        "설명용 연구 초안은 모든 방법에서 관찰된 효과의 절대값 중 가장 작은 값을 기준으로 25~50%만 반영했다. 각 방법의 95% 구간에서 0에 가장 가까운 상한보다 큰 제안은 제한했다. 이는 임의의 개별 말 효과를 확정하거나, 여러 분석의 불확실성을 동시에 보장하는 통계적 신뢰구간이 아니다.",
        "",
        "다음 범위는 **1200m 과거 원시기록을 건조 기준으로 기술적으로 환산할 때 더하는 초**다. 빠르게 나온 방향을 일부 되돌리므로 부호가 양수다. 거리·등급을 구분하지 않고 모든 기록에 같은 초를 더하는 운영 규칙으로 사용하지 않는다.",
        "",
        "| 경기장·조건 | 관찰 효과의 방법별 범위 | 최소 효과의 25~50% 참고 가산 |",
        "|---|---:|---:|",
    ]
    for r in saved["retrospective_reference_proposals"]:
        if r["all_filters_supported_fast"]:
            lo, hi = r["observed_effect_range"]
            low, high = r["add_seconds_025_050"]
            lines.append(
                f"| {MEETS[r['meet']]}·{r['band']} | {lo:+.3f}~{hi:+.3f}초 | +{low:.2f}~+{high:.2f}초 |"
            )
    lines += [
        "",
        "초안보다 조금 낮춰 잡은 실용적인 시작 범위는 서울 포화 +0.10~0.20초·불량 +0.20~0.45초, 부산 포화 +0.10~0.25초·불량 +0.15~0.35초 정도다. 이런 소수점 범위가 기록 측정 정밀도나 개별 말의 실제 이득 정밀도를 보장하지 않는다.",
        "",
        "이 고정 초안은 전체 후향 관찰 추정에서 만들어 예측평가에 직접 넣지 않았다. 아래 예측 검증은 각 과거 경주 연도보다 이전 자료에서 추정한 연도별·거리별 계수의 25~50%를 사용했다. 따라서 참고 표 자체가 사전 검증을 통과한 환산표라는 뜻은 아니다.",
        "",
        "## 부분 반영의 다음 출전 예측 검증",
        "",
        "기존 피처 재학습과 동일한 학습·평가행을 유지하고, 직전 1·2회 기록의 환경계수 반영률만 바꿔 각각 모델을 다시 학습했다. 이상치 제외는 환경계수 학습 잔차에 적용하고 현재 평가 정답·원시 과거기록은 삭제하지 않았다. 쉬운 평가행만 남기는 성능 비교가 아니다. 대상은 2024~2026년(2026년 9월 20일까지) 후향 자료다.",
        "",
        "| 경기장 | 출전 | 원시기록 | 계수 25% | 계수 50% | 계수 100% |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in saved["prediction_summary"]:
        if r["part"] == "finish" and r["year"] == "all":
            lines.append(
                f"| {MEETS[r['meet']]} | {r['n']:,} | "
                + " | ".join(
                    f"{r['mae'][key]:.4f}"
                    for key in ["raw", "baseline_025", "baseline_050", "baseline_100"]
                )
                + " |"
            )
    lines += [
        "",
        "단위는 MAE 초이며 작을수록 좋다. 50% 반영의 원시기록 대비 차이는 서울 −0.00525초(95% −0.00714~−0.00332), 부산 −0.00769초(−0.00939~−0.00602)였다. 세 평가연도 각각에서도 50% 반영의 방향과 구간이 유지됐다. 25%도 전체 평균 개선이 남았지만 크기는 더 작았다.",
        "",
        "이번 전체 평균에서는 100% 반영이 25~50%보다 정확했다. 따라서 절반 보정이 성능상 최적이라고 주장하지 않는다. 25~50%는 환산의 불확실성을 보수적으로 다루면서 일부 개선을 남기는 후보이고, 결과를 본 뒤 최적 반영률로 승격하지 않는다. 순위·Top3·수익률은 이번에 평가하지 않았다.",
        "",
        "이상치 제외 후 계수의 100%를 반영한 MAE는 아래와 같다. 말별 양쪽 5% 제외가 서울에서는 약간 더 낫고 부산에서는 기존 계수보다 나빴다. 더 많이 제거할수록 더 정확해지는 규칙도 아니다.",
        "",
        "| 계수 학습 기준 | 서울 MAE | 부산 MAE |",
        "|---|---:|---:|",
    ]
    finish = {
        r["meet"]: r
        for r in saved["prediction_summary"]
        if r["part"] == "finish" and r["year"] == "all"
    }
    for method in METHODS:
        key = f"{method}_100"
        lines.append(
            f"| {METHODS[method]} | {finish[1]['mae'][key]:.4f} | {finish[3]['mae'][key]:.4f} |"
        )
    lines += [
        "",
        "## 등급별 차이",
        "",
        "국/혼과 OPEN 원문 구분을 유지했다. 아래는 1200m 포화 전체시간의 등급별 관찰 추정이며 괄호는 해당 포화의 경주일 수다. 지원은 함수율 조건과 건조 각각 20일 이상이다. 등급에 따라 같은 거리에서도 추정값이 다르지만 각 추정값의 차이가 확정된 등급 효과를 뜻하지 않는다.",
        "",
        "| 경기장·등급 | 기존 포화 차이 | 양쪽 1% 제외 | 양쪽 5% 제외 | 기존 95% 구간 |",
        "|---|---:|---:|---:|---|",
    ]
    for meet in MEETS:
        for grade in ["국6등급", "국5등급", "국4등급", "혼4등급"]:
            try:
                a, b, c = [
                    cell(saved, method, meet, "포화", grade)
                    for method in ["baseline", "horse_trim1", "horse_trim5"]
                ]
            except StopIteration:
                continue
            lines.append(
                f"| {MEETS[meet]}·{grade} | {a['seconds']:+.3f}초 ({a['days']}일) | {b['seconds']:+.3f}초 | {c['seconds']:+.3f}초 | {interval(a['ci95'])} |"
            )
    lines += [
        "",
        "서울 1200m에서 국6등급 포화 −0.669초, 국5등급 −0.473초, 혼4등급 −0.505초였고 구간이 겹쳤다. 부산은 국6등급 포화에서만 35일의 지원이 있었고 다른 예시 등급은 7~18일이었다. 1200m 1·2등급은 거리 구성과 표본 때문에 별도 확정표를 제시하지 않는다. OPEN도 일반 숫자등급과 합치지 않았다.",
        "",
        "정식 등급 차이 검정은 숫자 1~6 등급의 국/혼 범주를 유지하고, 전체시간 잔차에 거리×함수율과 등급×함수율을 동시에 넣어 연도·월·경주번호·등급을 조정했다. 국6등급 대비 포화/불량 반응 차이 중 충분한 지원과 추정가능성이 있는 12개 대비를 두 경기장에서 모아 BH 보정했다. 기존 및 네 이상치 방법 모두 q<0.05는 0개였다. 이는 등급별 차이가 없다는 증명이 아니라 현재 자료로 별도 보정계수를 확정할 근거가 부족하다는 결과다.",
        "",
        "예를 들어 서울 국3등급 포화는 국6등급보다 약 +0.445초 덜 빠른 반응이라는 탐색값이 있었지만 q≈0.197로 확정하지 못했다. 실제로 별도 거리×등급×함수율 표를 만들면 지원이 더 약해진다. 1·2등급과 불량의 희소 표본에는 하위등급 계수를 그대로 확정 적용하거나 추정치를 강하게 따로 적용하지 않는다.",
        "",
        "## 한계·검증·재현",
        "",
        "추정 잔차에는 편성·전개·기수·컨디션·날씨·정비 등 미설명 차이가 남고, 함수율 20이 실제 정밀값인지 상한 표기인지도 미확정이다. 군집 구간은 모든 말 반복 출전 의존성과 전체 추정 절차의 불확실성을 전부 반영하지 않는다. 이상치로 제거한 유효 환경 반응 때문에 효과가 약해질 수 있고, 등급 joint 모형은 거리 반응과 등급 반응의 가산 구조를 가정한다.",
        "",
        "시점 조건은 과거 경주 연도 이전의 환경계수, 평가연도 이전의 기대시간 모델을 유지했다. 과거 연도 내 절단 분포는 이후 연도 계수 추정에만 들어갔다. 현재 평가 정답을 절단하지 않았고 모든 후보의 평가 키와 학습행은 동일하다. 기존 원시기록·100% 계수 예측도 1e−8 이내로 재현했다.",
        "",
        "```bash",
        "PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python thoroughbred/research/20261002_moisture_robust_grade/analyze.py",
        "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261002_moisture_robust_grade/verify.py",
        "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261002_moisture_robust_grade/render_report.py",
        ".venv/bin/ruff check thoroughbred/research/20261002_moisture_robust_grade/*.py",
        "```",
        "",
        "outputs가 있으면 분석은 덮어쓰지 않는다. 새 실행은 새 버전 폴더에서 수행한다. [전체 결과](outputs/summary.json), [독립 검증](outputs/verification.json), 각 시나리오의 filter_ledger·경주잔차·고정계수를 보존했다. 입력·기존 연구·공식 DB·운영 모델은 변경하지 않았다.",
    ]
    (HERE / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
