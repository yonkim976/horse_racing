"""Save a Korean report and distance comparison figure from fixed results."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/horse-racing-moisture-distance-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
MEETS = {1: "서울", 3: "부산"}
PARTS = {
    "finish": "전체시간",
    "start_200": "출발200m",
    "last_200": "마지막200m",
    "last_600": "마지막600m",
}


def interval(ci):
    return "근거 부족" if ci is None else f"[{ci[0]:+.4f}, {ci[1]:+.4f}]"


def main():
    saved = json.loads((OUT / "summary.json").read_text())
    primary = saved["scenarios"]["quality_filtered"]
    sensitivity = saved["scenarios"]["all_api"]
    selected = [
        r
        for r in primary["distances"]
        if r["part"] == "finish"
        and r["year"] == "all"
        and r["distance_m"] in (1200, 1300, 1400, 1600, 1700, 1800)
    ]
    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 11}
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.6), sharex=True)
    for ax, (meet, name) in zip(axes, MEETS.items(), strict=True):
        rows = [r for r in selected if r["meet"] == meet]
        for variant, offset, color, label in (
            ("pooled", -0.1, "#718096", "거리 공통 구간 보정"),
            ("distance", 0.1, "#2463a6", "거리×구간 보정"),
        ):
            points = [r["delta_vs_raw"][variant]["seconds"] for r in rows]
            bounds = [r["delta_vs_raw"][variant]["ci95"] for r in rows]
            ax.errorbar(
                points,
                [i + offset for i in range(len(rows))],
                xerr=[
                    [p - b[0] for p, b in zip(points, bounds, strict=True)],
                    [b[1] - p for p, b in zip(points, bounds, strict=True)],
                ],
                fmt="o",
                capsize=3,
                color=color,
                label=label,
                markersize=5,
            )
        ax.axvline(0, color="#7c8795", linewidth=1)
        ax.set_xticks([-0.03, -0.02, -0.01, 0], ["-0.03", "-0.02", "-0.01", "0"])
        ax.set_yticks(range(len(rows)), [f"{r['distance_m']}m · {r['n']:,}출전" for r in rows])
        ax.invert_yaxis()
        ax.set_title(name, loc="left", fontweight="bold")
        ax.set_xlabel("원시기록 입력 대비 MAE 차이 (초)\n← 개선                악화 →")
        ax.grid(axis="x", alpha=0.15)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False, loc="lower left", fontsize=9)
    fig.suptitle(
        "과거 기록을 함수율로 보정한 뒤 재학습 — 거리별 다음 출전", x=0.07, ha="left", fontsize=16
    )
    fig.text(
        0.07,
        0.015,
        "2024~2026년 이전 연도 학습 · 전체시간 · 같은 학습/평가행 비교\n점: 평균오차 차이 · 막대: 경주일 군집 95% 구간 · 하위 거리 결과는 다중비교 보정 없는 탐색 결과",
        fontsize=9,
        color="#475569",
    )
    fig.tight_layout(rect=(0, 0.09, 1, 0.92))
    fig.savefig(OUT / "distance_prediction_mae.png", dpi=180, facecolor="white")
    plt.close(fig)
    lines = [
        "# 함수율·거리별 과거 기록 재학습 — 결과",
        "",
        "작성일: 2026-10-02 · 서울·부산 · 연구용, 운영 미적용",
        "",
        "## 판단",
        "",
        "**과거 기록 피처를 함수율로 보정한 뒤 다시 학습하는 방식에서는 다음 출전 전체시간 MAE가 작게 개선됐다. 거리 상호작용까지 넣는 추가 이득은 작고 경기장·거리별로 일정하지 않다.**",
        "",
        "서울 전체 MAE는 원시기록 1.2565초에서 거리×구간 보정 1.2500초로 0.0065초(약 0.52%) 줄었다. 부산은 원시기록 1.3626초에서 공통 구간 보정 1.3495초로 0.0131초(약 0.96%) 줄었다. 모두 같은 학습·평가 표본을 사용했다. 이 두 후보는 결과를 본 뒤 경기장별로 선택한 것이므로 운영 선택 규칙으로 채택하지 않는다.",
        "",
        "이전 단계의 직전 잔차 추가 방식은 개선하지 못했고 이번 피처 교체·재학습 방식은 작은 개선을 보였다. 두 단계의 표본과 학습범위가 다르므로 단계 간 MAE 숫자를 직접 비교하지 않는다. 함수율 관찰 차이가 0.5~1초 이상이라는 결과와 다음 출전 예측 개선이 수 밀리초~십여 밀리초라는 결과도 서로 다른 질문이다.",
        "",
        "## 방법·공통 표본",
        "",
        "[결과 계산 전에 고정한 계약](PLAN.md)을 따랐다. 숫자 함수율 1~5% 건조, 6~9% 양호, 10~14% 다습, 15~19% 포화, 20% 이상 불량을 사용했다. 주로빠르기는 입력·계수·평가에서 제외했다.",
        "",
        "환경 계수는 앞선 연구의 2020년 이후 연도 외부 말별 잔차를 경주 중앙값으로 모아 추정했다. 적격 말 4두 이상인 경주를 계수 학습에 사용했다. 동일한 거리·월·연도추세·경주번호를 통제하는 Ridge α=25에 구간 효과, 또는 구간+거리×구간 효과를 넣었다. 완전 독립적인 거리별 회귀가 아니라 수축하는 상호작용 모형이다.",
        "",
        "각 과거 기록의 환경계수는 그 경주 연도보다 이전 연도 잔차만으로 고정했다. `보정기록 = 원시기록 − (해당 함수율 예측 − 같은 조건의 건조 예측)`으로 직전 1·2회 시간 피처를 바꾸고 Ridge α=20 기대시간 모형을 각각 재학습했다. 현재 경주의 함수율·결과·착순은 다음 출전 예측 입력에 없다. 현재 실제 원시시간이 평가 정답이다.",
        "",
        "원시기록·공통 구간 보정·거리×구간 보정 후보 모두 같은 학습행과 평가행을 사용했다. 직전 동일 거리 유효 출전을 건너뛰지 않았고, 두 번째 기록이 실제로 없을 때만 직전 값을 복제했다. 존재하는 과거 기록에 계수가 없으면 행을 제외했다. 2021년부터 계수가 있으므로 학습행도 그 이후의 과거 기록을 가진 공통 표본으로 제한된다. 2024년 이전 실제 학습 날짜는 저장된 fits에 보존했다.",
        "",
        "평가는 2024·2025·2026년을 매번 이전 연도까지 학습해 수행했다. 2026년은 9월 20일까지다. 기존부터 본 후향 기간이므로 새 독립 테스트가 아니다. 주 분석은 앞선 품질 제외 82경주·953행을 유지했고 API 원문 전부 포함한 민감도도 실행했다.",
        "",
        "전체시간 평가 출전은 서울 21,277개·부산 15,654개, 합계 36,931개(4,729경주·4,575두)다. 이번에는 원천의 과거 기록에 직접 계수를 적용하므로 이전 단계의 '직전 경주 자체에도 기대시간이 있어야 함' 제한은 없다. 직전 1·2회 계수 필요 조건만으로 서울 원시 적격 21,287행 중 10행, 부산 15,655행 중 1행이 제외됐다.",
        "",
        "## 전체시간: 거리별 다음 출전",
        "",
        "MAE는 초 단위, 작을수록 좋다. 차이는 거리×구간 보정−원시기록이다. 군집 95% 구간은 현재 경주일을 단위로 1,000회 대응 부트스트랩했다. 거리별 결과에는 다중비교 보정을 하지 않았다.",
        "",
        "![거리별 다음 출전 오차 차이](outputs/distance_prediction_mae.png)",
        "",
        "| 경기장·거리 | 출전 | 원시기록 | 공통 구간 보정 | 거리×구간 보정 | 차이 | 차이 95% 구간 | 과거 계수 지원 부족 행 |",
        "|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for r in selected:
        delta = r["delta_vs_raw"]["distance"]
        lines.append(
            f"| {MEETS[r['meet']]}·{r['distance_m']}m | {r['n']:,} | {r['mae']['raw']:.4f} | {r['mae']['pooled']:.4f} | {r['mae']['distance']:.4f} | {delta['seconds']:+.4f} | {interval(delta['ci95'])} | {r['low_support_historical_rows']:,} |"
        )
    lines += [
        "",
        "서울 1200·1300m는 거리×구간 보정 차이의 구간이 0을 포함한다. 서울 1400·1700m는 개선 방향을 보였고 1800m는 상한이 거의 0이어서 경계적이다. 서울 1600m는 과거 계수 지원 부족 행이 1,137개 중 759개라 해석을 특히 유보한다. 부산은 지정한 1200·1300·1400·1600·1800m 모두 거리×구간 보정 차이의 구간이 음수지만, 공통 구간 보정보다 항상 낫지는 않다.",
        "",
        "과거 계수 지원 부족은 직전 1·2회 중 하나라도 해당 거리의 함수율 조건 또는 건조 기준의 계수 학습 경주일이 20일 미만인 경우다. Ridge 수축값은 계산되지만 충분한 거리별 관찰 근거가 있다는 뜻은 아니다. 1000m는 평가 출전이 서울 93개·부산 64개로 판단 보류다. 서울 2000m는 441출전이지만 391행, 부산 2000m는 209출전 중 204행의 과거 계수가 지원 부족이다. 숫자만으로 장거리 보정 채택을 주장하지 않는다.",
        "",
        "## 전체·연도별 안정성",
        "",
        "| 경기장·연도 | 출전 | 원시기록 | 공통 구간 | 거리×구간 | 거리×구간 차이 95% 구간 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in primary["overall"]:
        if r["part"] == "finish":
            lines.append(
                f"| {MEETS[r['meet']]}·{r['year']} | {r['n']:,} | {r['mae']['raw']:.4f} | {r['mae']['pooled']:.4f} | {r['mae']['distance']:.4f} | {interval(r['delta_vs_raw']['distance']['ci95'])} |"
            )
    lines += [
        "",
        "서울 2024년은 거리×구간 차이의 구간이 0을 포함하고, 2025·2026년은 개선 방향을 유지했다. 부산은 세 연도 모두 개선 방향을 유지했다. 거리×구간−공통 구간의 전체 차이는 서울 −0.0008초, 부산 +0.0003초로 추가 이득은 매우 작다.",
        "",
        "## 직전 함수율·지원 부족 민감도",
        "",
        "아래는 결과를 확인한 뒤 전체시간의 직전 함수율별로 집계한 탐색 결과다. 다음 경주일을 표시한 것이며 과거 경주의 계수 학습 지원 일수와 다르다.",
        "",
        "| 경기장·직전 함수율 | 출전 | 다음 경주일 | 거리×구간−원시기록 MAE |",
        "|---|---:|---:|---:|",
    ]
    extra = {}
    for scenario in saved["scenarios"]:
        frame = pd.read_parquet(OUT / scenario / "prediction_evaluation.parquet")
        frame = frame[frame.part.eq("finish")].copy()
        frame["delta"] = frame.err_distance - frame.err_raw
        if scenario == "quality_filtered":
            for (meet, band), cell in frame.groupby(["meet", "prev_band"]):
                lines.append(
                    f"| {MEETS[meet]}·{band} | {len(cell):,} | {cell.day_key.nunique()} | {cell.delta.mean():+.4f} |"
                )
        extra[scenario] = []
        for meet, cell in frame.groupby("meet"):
            high = (
                cell.prev_distance_band_training_days.ge(20)
                & cell.prev_distance_dry_training_days.ge(20)
                & cell.prev2_distance_band_training_days.ge(20)
                & cell.prev2_distance_dry_training_days.ge(20)
            )
            sample = cell[high]
            extra[scenario].append(
                {"meet": int(meet), "n": len(sample), "delta": float(sample.delta.mean())}
            )
    lines += [
        "",
        "포화·불량 과거 기록에서 차이가 상대적으로 컸다. 부산 다습에서는 +0.0032초 악화했다. 하위집단의 여러 편성·출전 선택 요인이 섞이고, 위 표는 구간 검정 없이 평균만 제시하므로 함수율별 확정 채택 규칙으로 해석하지 않는다.",
        "",
        "과거 계수 지원 부족 행을 결과 집계에서 제외해도 거리×구간 보정의 평균 개선 방향은 남았다(모형을 다시 학습한 민감도는 아님). 서울 19,498행 −0.0045초, 부산 14,166행 −0.0054초였다. 특히 부산의 전체 −0.0128초 개선 일부는 지원 부족 조건의 행에 집중된다.",
        "",
        "## 원천 품질 민감도·보조 목표",
        "",
        "| 경기장 | 주 분석 거리×구간−원시기록 | 모두 포함 거리×구간−원시기록 |",
        "|---|---:|---:|",
    ]
    for meet in MEETS:
        a = next(
            r
            for r in primary["overall"]
            if r["meet"] == meet and r["part"] == "finish" and r["year"] == "all"
        )
        b = next(
            r
            for r in sensitivity["overall"]
            if r["meet"] == meet and r["part"] == "finish" and r["year"] == "all"
        )
        lines.append(
            f"| {MEETS[meet]} | {a['delta_vs_raw']['distance']['seconds']:+.4f} | {b['delta_vs_raw']['distance']['seconds']:+.4f} |"
        )
    lines += [
        "",
        "품질 제외를 풀어도 전체시간의 방향은 유지됐다. 보조 목표는 아래와 같아 전체시간 결과를 구간 모두의 개선으로 확대할 수 없다.",
        "",
        "| 경기장·목표 | 거리×구간−원시기록 | 95% 구간 |",
        "|---|---:|---|",
    ]
    for r in primary["overall"]:
        if r["year"] == "all" and r["part"] != "finish":
            d = r["delta_vs_raw"]["distance"]
            lines.append(
                f"| {MEETS[r['meet']]}·{PARTS[r['part']]} | {d['seconds']:+.4f} | {interval(d['ci95'])} |"
            )
    lines += [
        "",
        "경주 공통 잔차 모형 자체의 전체시간 오차는 서울 공통 0.7269초·거리×구간 0.7268초, 부산 공통 0.8464초·거리×구간 0.8459초였다. 거리 상호작용의 추가 이득이 작다는 점은 여기서도 일치한다. 상세 거리·연도별 값은 summary.json에 보존했다.",
        "",
        "## 적용 판단과 다음 연구",
        "",
        "1. 전체시간 과거 기록 피처의 함수율 보정은 후속 후보로 유지한다. 큰 개선 또는 개별 말의 물리적인 주로 이득 식별로 주장하지 않는다.",
        "2. 거리별 완전 독립 보정표나 모든 거리의 상호작용을 즉시 채택할 근거는 부족하다. 공통 구간 보정을 비교 기준으로 유지하고 1400·1800m 등 개선 가능성이 있는 거리의 추가 반응을 검증한다. 서울 1200·1300m 개선은 아직 불확실하다.",
        "3. 이 시점 이후 확보한 미관측 기간으로 규칙을 고정한 검증이 필요하다. 우승·Top3 성능, 말별 적성, 전개·편성·참가마 구성 조정은 별도 과제이며 이번에 확인하지 않았다.",
        "4. 환경 잔차에는 날씨·편성·기수·컨디션 등 미설명 차이가 남는다. 과거 보정계수의 추정오차 전체와 말 반복 출전 의존성을 이번 경주일 구간이 모두 반영하지는 못한다. 게이트 대용 마번·중량·등급 메타정보의 역사적 공개 시점도 기존 연구의 한계다. 운영 모형·공식 DB·등록부는 변경하지 않았다.",
        "",
        "## 재현·검증",
        "",
        "```bash",
        "PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python thoroughbred/research/20261002_moisture_distance_retrain/analyze.py",
        "PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python thoroughbred/research/20261002_moisture_distance_retrain/verify.py",
        "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261002_moisture_distance_retrain/render_report.py",
        ".venv/bin/ruff check thoroughbred/research/20261002_moisture_distance_retrain/*.py",
        "```",
        "",
        "분석은 outputs가 있으면 덮어쓰지 않고 중단한다. 새 실행은 새 버전 디렉터리에서 수행한다. 원천 스냅샷·기존 잔차·계획·분석 코드의 SHA256은 실행 전후 동일했다. 기대시간·환경계수 이전 연도 조건, 과거 날짜, 동일 말·경주·거리·시간 연결, 키 유일성, 같은 학습·평가행, 유한 예측을 검사했다.",
        "",
        "독립 검증에서는 저장된 MAE를 재계산하고 2024년 전체시간 학습을 두 경기장에서 재구성했다. 현재 경주 시간·착순·함수율을 의도적으로 바꿔도 예측이 동일했고 저장된 예측을 재현했다. [검증 결과](outputs/independent_verification.json), [전체 결과](outputs/summary.json), [품질 제외 상세](outputs/quality_filtered/summary.json)를 보존했다. 원천 DB·이전 연구를 수정하지 않았다.",
    ]
    (OUT / "support_sensitivity.json").write_text(json.dumps(extra, ensure_ascii=False, indent=2))
    (HERE / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
