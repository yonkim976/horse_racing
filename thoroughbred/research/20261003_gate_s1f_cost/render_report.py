"""Render the verified S1F gate analysis in the established local research format."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/gate_s1f_mpl")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
NAMES = {1: "서울", 3: "부산"}


def sec(value):
    return f"{value:+.3f}"


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["status"] == "passed"
    effects = pd.read_csv(OUT / "effects.csv")
    outer = effects[effects.contrast.eq("gate:None:outer")].copy()
    primary = outer[outer.scenario.eq("primary")]
    rows = []
    for r in primary.itertuples():
        lo, hi = json.loads(r.ci95_seconds)
        rows.append(
            f"| {NAMES[r.meet]} | {r.distance_m} | {r.races:,} | {sec(r.raw_outer_minus_inner_seconds)} | {sec(r.effect_seconds)} | [{sec(lo)}, {sec(hi)}] | {r.q:.4g} |"
        )
    sensitivity = outer.pivot(
        index=["meet", "distance_m"], columns="scenario", values="effect_seconds"
    )
    sensitivity_rows = []
    for (meet, distance), r in sensitivity.iterrows():
        values = [
            sec(r.get(key)) if pd.notna(r.get(key)) else "지원 부족"
            for key in [
                "primary",
                "no_extreme_delay",
                "robust_races",
                "experienced",
                "horse_fe",
                "2024plus",
            ]
        ]
        sensitivity_rows.append(f"| {NAMES[meet]} | {distance} | " + " | ".join(values) + " |")
    competition = pd.read_csv(OUT / "competition_effects.csv")
    competition_rows = []
    for (meet, distance), one in competition.groupby(["meet", "distance_m"]):
        indexed = one.set_index("contrast")
        a, b, c = [indexed.loc[f"gate:{g}:outer"] for g in ["0-1", "2", "3+"]]
        change = indexed.loc["gate:3+:outer minus gate:0-1:outer"]
        lo, hi = json.loads(change.ci95_seconds)
        competition_rows.append(
            f"| {NAMES[meet]} | {distance} | {sec(a.effect_seconds)} ({a.races}) | {sec(b.effect_seconds)} ({b.races}) | {sec(c.effect_seconds)} ({c.races}) | {sec(change.effect_seconds)} [{sec(lo)}, {sec(hi)}] | {change.q:.3f} |"
        )
    plt.rcParams.update({"font.size": 10, "axes.unicode_minus": False})
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.8), sharex=True)
    for ax, meet in zip(axes, [1, 3], strict=True):
        distances = sorted(primary[primary.meet.eq(meet)].distance_m.unique())
        colors = {"primary": "#205b9b", "horse_fe": "#bd6a10", "2024plus": "#27815b"}
        for scenario, offset, label in [
            ("primary", -0.2, "2018-2026 adjusted"),
            ("horse_fe", 0, "Same horse + race effects"),
            ("2024plus", 0.2, "2024-2026 adjusted"),
        ]:
            one = outer[outer.meet.eq(meet) & outer.scenario.eq(scenario)]
            for i, distance in enumerate(distances):
                cell = one[one.distance_m.eq(distance)]
                if cell.empty:
                    continue
                row = cell.iloc[0]
                lo, hi = json.loads(row.ci95_seconds)
                ax.errorbar(
                    row.effect_seconds,
                    i + offset,
                    xerr=np.array([[row.effect_seconds - lo], [hi - row.effect_seconds]]),
                    fmt="o",
                    color=colors[scenario],
                    capsize=2,
                    markersize=4,
                    label=label
                    if i == (1 if scenario == "2024plus" and meet == 3 else 0)
                    else None,
                )
        ax.axvline(0, color="#888888", linewidth=1)
        ax.set_yticks(range(len(distances)), [f"{d}m" for d in distances])
        ax.invert_yaxis()
        ax.set_title("Seoul" if meet == 1 else "Busan")
        ax.grid(axis="x", alpha=0.2)
        ax.set_xlabel("Outer minus inner S1F time (seconds)")
        ax.legend(loc="lower right", fontsize=8)
    fig.suptitle(
        "First 200m: positive values mean slower outer starters\nDay-cluster 95% intervals; observational gate groups"
    )
    fig.tight_layout()
    fig.savefig(OUT / "gate_s1f_effects.png", dpi=180)
    plt.close(fig)
    text = """# 게이트별 첫 200m 시간 차이

2026-10-03. 서울·부산의 S1F 기록으로 외측 출발의 초반 시간 차이를 확인했다. 대부분의 거리에서 외측이 느리고, 서울 1600m와 1700m에서 차이가 특히 크다. 부산 1600m는 반대로 외측이 빠르다. 과거 초반 능력을 보정하고 동일 말의 게이트 변화로 비교해도 주요 방향이 유지된다. 이 차이는 관찰된 초반 시간 차이이며 대각선 이동 거리나 순수한 인과적 손실을 직접 측정한 값은 아니다.

## 자료와 비교 기준

기간은 {first}부터 {last}까지다. 기존 함수율·기록 불일치 제외 기준을 적용한 게이트 연구 자료에 API S1F 누적시간을 결합했다. 분석 자료는 {runners:,}건, {races:,}경주이며 기록이 빠진 부산 2019-03-10 2경주 전체 10두를 제외했다. 서울 8,181경주, 부산 5,746경주다. 원자료와 이전 연구 파일은 변경하지 않았다.

S1F는 출발 후 첫 200m 기록이다. [한국마사회 통과순위 설명](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1). 실제 기록은 모두 0.1초 단위다. 표의 0.001초는 많은 관측의 평균 추정값 표시이며 개별 말의 기록이 그 정밀도로 측정됐다는 뜻은 아니다.

내측·중간·외측은 출전한 말의 등록 마번 순서를 3등분한 기존 기준이다. 12두가 1~12번에 모두 출전했다면 내측 1~4번, 중간 5~8번, 외측 9~12번이다. 등록 마번을 물리적 출발칸의 대리변수로 사용했으며 별도 실제 출발칸 좌표는 없다. 아래 값은 외측 집단 평균과 내측 집단 평균의 비교로, 12번과 1번의 직접 비교가 아니다.

경마장·정확한 거리별로 같은 경주 내 S1F 차이를 회귀 분석했다. 경주 고정효과로 같은 날·같은 경주의 공통 주로와 함수율, 경주 수준 및 페이스 영향을 제거하고 각 경주의 총 가중치를 1로 맞췄다. 공통 환경의 제거가 게이트별 환경 반응 차이까지 모두 제거한다는 뜻은 아니다. 게이트×함수율의 별도 차이는 이번 분석 대상이 아니다.

말의 이전 S1F는 각 과거 경주 중앙값 대비 빠르거나 느린 정도를 최근 5회 평균으로 만들었다. 동일 경기장·거리의 최근 5회도 따로 사용했다. 과거 기록은 현재 경주일보다 앞선 것만 쓰고, 과거 특징 생성에서 10~25초 범위 밖의 극단 지연 기록은 제외했다. 평점·나이·부담중량·과거 착순과 초반 위치·경력·휴양 간격 및 결측 여부도 조정했다. 해당 경주의 실제 통과조와 최종배당은 주 모형의 설명 변수로 사용하지 않았다.

## 거리별 결과

단위는 초다. 양수는 외측이 느리고 음수는 외측이 빠르다. 95% 구간은 경주일 단위 군집 구간이며 q는 전체 15개 거리 대비의 BH 보정값이다. 비교 거리는 기존 게이트 연구의 1000·1200·1300·1400·1600·1700·1800·2000m로 고정하고, 50경주·20일 이상인 거리만 추정했다. 이 거리의 분석 대상은 13,870경주다. 1900·2200·2300m의 나머지 57경주는 원래 분석 스냅샷에는 보존하되 표의 회귀 비교에는 포함하지 않았다. 주 분석의 15개 대비 중 14개는 q<0.05이며 부산 2000m는 방향을 확정하기 어렵다.

| 경기장 | 거리 m | 경주 수 | 원시 외측−내측 | 능력 보정 외측−내측 | 95% 구간 | q |
|---|---:|---:|---:|---:|---|---:|
{primary}

![게이트와 S1F 시간 차이](outputs/gate_s1f_effects.png)

서울 1200m는 +0.077초, 부산 1200m는 +0.036초다. 서울 1600m는 +0.230초, 1700m는 +0.189초로 상대적으로 크다. 부산 1600m는 −0.058초로 반대 방향이다. 이러한 거리별 차이 때문에 외곽에 동일한 초 단위 벌점을 일괄 적용하는 것은 적절하지 않다.

## 이상치와 동일 말 비교

주 분석은 기록이 있는 완전 경주의 극단 지연도 보존했다. 아래는 보조 비교이며 각 열의 추정 단위는 초다. 극단 제외는 S1F 10~25초 밖의 말이 있는 6경주 전체를 제외했다. 강건 경주는 경주 내 중앙값 ±max(0.8초, 4×1.4826×MAD) 밖의 말이 있는 경주를 제외하여 12,332경주를 남겼다. 이는 출발 실패 등 실제 사건도 제거할 수 있는 민감도 검사다.

전마 이력 3회 이상은 7,623경주이며 신마·경력 부족 말에 대한 보정 의존성을 점검한다. 동일 말 비교는 경주 고정효과와 말 고정효과를 함께 사용해 말의 고정적인 초반 특성을 추가로 제거했다. 경주와 말 효과의 자유도는 보수적인 상한으로 처리했다. 말의 시기에 따라 변하는 컨디션이나 기승 전략까지 제거하는 인과 모형은 아니다.

| 경기장 | 거리 m | 주 분석 | 극단 제외 | 강건 경주 | 전마 이력 3회 | 동일 말 비교 | 2024년 이후 |
|---|---:|---:|---:|---:|---:|---:|---:|
{sensitivity}

주요 방향은 비교 방법을 바꿔도 유지된다. 동일 말 비교에서 서울 1200m +0.071초, 서울 1600m +0.236초, 부산 1200m +0.041초, 부산 1600m −0.064초다. 최근 기간에서도 서울 1600m +0.232초, 1700m +0.202초, 부산 1600m −0.084초가 나타난다.

다만 최근 2024년 이후 서울 1800m는 +0.033초, 95% 구간 [−0.001, +0.067]이며 부산 1800m는 +0.001초, 구간 [−0.031, +0.034]로 0과 구분하기 어렵다. 서울 1000m·2000m도 최근 구간이 0을 포함한다. 부산 1000m·2000m의 최근 표본은 지원 기준에 미달한다. 장기 차이를 모든 현재 경주에 고정 적용할 근거는 부족하다. 보조 비교의 구간은 전체 다중비교를 추가 보정한 확정 판정이 아니다.

## 선행 성향 말 수와 외측 차이

전마 과거 S1F 이력 3회 이상인 경주에서 기존 과거 초반 위치 평균 prior_early≤0.20인 말을 선행 성향으로 분류했다. 이는 현재 실제 선행마 수나 경주의 실제 속도를 뜻하지 않는다. 세 그룹 모두 50경주·20일 이상인 거리만 비교했다. 그룹마다 능력 계수를 따로 추정한 단순 표가 아니라 한 모형의 게이트×그룹 상호작용으로 차이를 직접 검정했다.

각 그룹은 외측−내측 시간차이며 괄호는 경주 수다. 마지막 대비는 선행 성향 3두 이상에서의 외측 차이가 0~1두 때보다 얼마나 달라지는지 나타낸다. 8개 대비를 별도 BH 처리했다.

| 경기장 | 거리 m | 0~1두 | 2두 | 3두 이상 | 3두 이상−0~1두 및 95% 구간 | q |
|---|---:|---:|---:|---:|---|---:|
{competition}

서울 1200m는 0~1두일 때 +0.059초, 3두 이상일 때 +0.083초지만 증가분 +0.024초의 구간은 [−0.016, +0.063]이다. 이번 기준에서는 선행 성향 말이 많아질수록 외곽 시간 불이익이 일관되게 커진다는 근거가 없었다. 8개 그룹 간 대비 모두 q≥0.05다. 과거 초반 위치만으로 만든 분류가 약할 수 있으므로 향후 출발 후 속도·선두 확보 빈도까지 활용한 사전 전개 성향을 별도 검증할 여지는 남는다.

## 통과조와 해석 범위

[S1F 전개별 기술 표](outputs/observed_s1f_roles.csv)에 단독선두·선두조·선입·중간·후미와 출발 게이트별 기록 및 입상률을 저장했다. 분석 대상 모든 말에 통과조 역할이 연결됐다. 이 표는 현재 경주의 결과로 나눈 사후 기술 표다. 선두를 확보한 말만 골라 비교하면 선택에 따른 왜곡이 생길 수 있어 주 게이트 효과나 사전 예측 성능을 대신하지 않는다. 통과조의 내외 순서는 같은 마군 안에서의 상대 위치이며 절대 레일 거리나 안쪽 진입 완료를 확인하지 못한다.

관찰된 S1F 차이에는 출발 반응, 가속 능력, 앞을 확보하려는 경쟁, 진입 경로와 거리별 출발 지점 조건 등이 함께 작용할 수 있다. 통과조·기록만으로 이 요소들의 기여를 분리하지 못한다. 따라서 S1F 차이에 속도를 곱한 값을 실제 대각선 거리 손실로 보고하지 않았다. 외측이 더 빨랐던 부산 1600m도 대각선 이동 자체가 거리를 줄인다는 뜻은 아니다.

현재 결과는 초반 기록 연구와 전개 예측 특징의 후보 근거로 사용한다. 실전 보정값이나 예측확률을 변경하지 않았다. 향후 S1F 게이트 효과를 과거 연도로만 추정해 다음 연도 예측의 개선을 확인해야 운영 반영 여부를 판단할 수 있다. 이번 분석은 이미 관측된 기간을 이용한 후향 연구이며 새로운 미래 검증은 아니다.

## 검산과 재현

입력 SHA256 일치, {runners:,}건의 S1F 원자료·등록 마번 일치, 13,927경주의 완전 출전명단, 과거 특징 1,000건의 엄격한 이전 날짜 사용을 확인했다. 전체 15개 주 외측 효과와 구간을 별도 최소제곱 해법으로 검산하고 서울 1200m·부산 1200m·1600m의 동일 말 비교를 두 고정효과가 포함된 직접 희소 최소제곱으로 검산했다. 두 BH 보정도 별도 구현으로 일치했다.

- [계획](PLAN.md), [분석 코드](analyze.py), [검산 코드](verify.py)
- [전체 효과와 민감도 CSV](outputs/effects.csv)
- [선행 성향 수 비교 CSV](outputs/competition_effects.csv)
- [요약 JSON](outputs/summary.json), [검산 결과](outputs/verification.json)

재현 명령은 프로젝트 루트에서 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python thoroughbred/research/20261003_gate_s1f_cost/analyze.py`다. 기존 outputs가 있으면 덮어쓰지 않고 중단한다. `verify.py`와 `render_report.py`로 검산 및 보고서를 생성한다. 최초 불완전 실행 결과는 별도 outputs_incomplete_absorption 폴더에 보존하며 최종 비교는 outputs만 사용한다.
""".format(
        first=summary["first_date"],
        last=summary["last_date"],
        runners=summary["analysis_runners"],
        races=summary["analysis_races"],
        primary="\n".join(rows),
        sensitivity="\n".join(sensitivity_rows),
        competition="\n".join(competition_rows),
    )
    (HERE / "README.md").write_text(text)
    print(str(HERE / "README.md"))


if __name__ == "__main__":
    main()
