"""Generate reproducible Korean temporal-bias report and scientific plots."""

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/horse-racing-time-window-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
MEETS = {1: "서울", 3: "부산"}


def value(x):
    return f"{x:+.2f}"


def interval(x):
    return "—" if x is None else f"[{x[0]:+.2f}, {x[1]:+.2f}]"


def month_table(frame, point=False):
    columns = (
        "장소 | "
        + ("지점 | " if point else "")
        + "월 | 경주/일 | 능력조정 외측−내측 | 과거 기준 | 기준 대비 편차 | 편차 95% 구간 | q"
    )
    lines = ["| " + columns + " |", "| " + " | ".join(["---"] * (9 if point else 8)) + " |"]
    for r in frame.itertuples():
        cells = [MEETS[r.meet]] + ([r.point] if point else [])
        cells += [
            r.period,
            f"{r.races}/{r.days}",
            value(r.ability_adjusted_pp),
            value(r.expected_pp),
            value(r.deviation_pp),
            interval(r.ci95_pp),
            f"{r.q_month:.4f}" if pd.notna(r.q_month) else "지원 부족",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["status"] == "passed"
    periods = pd.read_parquet(OUT / "periods.parquet")
    races = pd.read_parquet(OUT / "race_deviations.parquet")
    overall = periods[periods.distance_m.isna()]
    months = overall[overall.window.eq("month")]
    gate_months = months[months.point.eq("gate")]
    diagnostics = []
    for meet in MEETS:
        daily = overall[
            overall.meet.eq(meet)
            & overall.point.eq("gate")
            & overall.window.eq("date")
            & overall.supported
        ]
        weekends = overall[
            overall.meet.eq(meet)
            & overall.point.eq("gate")
            & overall.window.eq("weekend")
            & overall.supported
        ]
        keys = races[
            races.meet.eq(meet)
            & races.point.eq("gate")
            & races.baseline_supported
            & races.weekday.ge(4)
        ][["date", "weekend_start"]].drop_duplicates()
        days = daily.merge(keys, left_on="period", right_on="date")
        signs = days.groupby("weekend_start").ability_adjusted_pp.agg(["min", "max", "count"])
        diagnostics.append(
            {
                "meet": meet,
                "supported_dates": len(daily),
                "supported_weekends": len(weekends),
                "supported_day_median_races": float(daily.races.median()),
                "supported_weekend_median_races": float(weekends.races.median()),
                "daily_reference_ci_median_width_pp": float(
                    np.median([ci[1] - ci[0] for ci in daily.ci95_pp])
                ),
                "weekends_with_two_supported_dates": int(signs["count"].ge(2).sum()),
                "weekends_with_opposite_daily_signs": int(
                    (signs["count"].ge(2) & signs["min"].lt(0) & signs["max"].gt(0)).sum()
                ),
            }
        )
    (OUT / "temporal_diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2)
    )
    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 10}
    )
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    for ax, (meet, label) in zip(axes, MEETS.items(), strict=True):
        one = gate_months[gate_months.meet.eq(meet) & gate_months.supported].sort_values("period")
        x = pd.to_datetime(one.period + "-15")
        y = one.deviation_pp.to_numpy()
        lo = np.array([c[0] for c in one.ci95_pp])
        hi = np.array([c[1] for c in one.ci95_pp])
        ax.errorbar(
            x,
            y,
            yerr=[y - lo, hi - y],
            fmt="o",
            ms=3,
            color="#8190a1",
            ecolor="#c4cbd3",
            capsize=2,
            label="월 편차와 95% 참고구간",
        )
        significant = one.q_month.lt(0.05).to_numpy()
        ax.scatter(
            x[significant],
            y[significant],
            c=np.where(y[significant] > 0, "#bc5b24", "#155b89"),
            s=35,
            zorder=3,
        )
        ax.plot([], [], "o", color="#bc5b24", label="q < 0.05: 양의 편차")
        ax.plot([], [], "o", color="#155b89", label="q < 0.05: 음의 편차")
        ax.axhline(0, color="#333333", lw=0.8)
        ax.set_title(f"{label}: 과거 거리·함수율·달력월·두수 기준 대비 게이트 편차")
        ax.set_ylabel("외측 방향 편차 (%p)")
        ax.grid(alpha=0.18)
        ax.legend(loc="upper right", fontsize=8)
    axes[-1].xaxis.set_major_locator(mdates.YearLocator())
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle("2020~2026 월별 변화 · 각 연도 이전 자료로 기준을 학습", fontsize=14)
    fig.tight_layout()
    fig.savefig(OUT / "monthly_gate_deviations.png", dpi=170)
    plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    for ax, (meet, label) in zip(axes, MEETS.items(), strict=True):
        daily = overall[
            overall.meet.eq(meet)
            & overall.point.eq("gate")
            & overall.window.eq("date")
            & overall.period.ge("2026-08")
            & overall.supported
        ]
        weekly = overall[
            overall.meet.eq(meet)
            & overall.point.eq("gate")
            & overall.window.eq("weekend")
            & overall.period.ge("2026-08")
            & overall.supported
        ]
        xd = pd.to_datetime(daily.period)
        ax.scatter(
            xd,
            daily.ability_adjusted_pp,
            s=25,
            color="#758397",
            label="날짜별 능력조정 차이",
            zorder=3,
        )
        for r in weekly.itertuples():
            start = pd.Timestamp(r.period)
            ax.plot(
                [start, start + pd.Timedelta(days=2)],
                [r.ability_adjusted_pp] * 2,
                lw=3,
                color="#ba6329",
            )
        ax.plot([], [], color="#ba6329", lw=3, label="금~일 주말 평균")
        ax.axhline(0, color="#333333", lw=0.8)
        ax.set_title(f"{label}: 같은 주말에서도 날짜별 방향이 달라질 수 있음")
        ax.set_ylabel("외측 - 내측 (%p)")
        ax.grid(alpha=0.18)
        ax.legend(fontsize=8)
    axes[-1].xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.FR))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.suptitle("2026년 8~9월 날짜·주말 비교 · 소표본 관찰값, 정식 유의 판정 아님", fontsize=13)
    fig.tight_layout()
    fig.savefig(OUT / "recent_dates_and_weekends.png", dpi=170)
    plt.close(fig)
    g = races[races.point.eq("gate")]
    lines = [
        "# 게이트·상대 내외측 유불리: 날짜·주말·월별 분석",
        "",
        "2026-10-03. 2020-01-03~2026-09-20의 기존 품질 필터 적용 스냅샷을 재사용했다. 날짜별·금~일 주말별·YYYY-MM 월별로 나눴으며, 같은 날짜의 경주 진행 구간도 확인했다.",
        "",
        "## 이번 결과",
        "",
        "**연간 평균 하나로 표현하기에는 시기별 변화가 크다. 월별 변화는 서울·부산의 게이트 모두 남고, 상대 주행위치는 부산 G1F를 제외한 7개 지점에서 남는다.** 날짜와 주말의 방향도 달라지지만 하루 약 7~10경주이므로 개별 날짜를 확정적인 주로 편향으로 판정할 근거는 약하다.",
        "",
        "서울은 2025년 3월에 내측 게이트 쪽, 6~7월에는 외측 게이트 쪽으로 관찰 방향이 바뀌었다. 부산은 2024년 7~9월 내측 성향이 이어졌고 2026년 8월에는 과거 기준보다 외측 쪽으로 이동했다. 이는 같은 달을 여러 해 합친 계절 평균이 아니라 각각의 실제 연월이다.",
        "",
        "각 연도의 기준은 2018년부터 바로 전 연도까지의 자료로만 학습했다. 거리·숫자 함수율 구간·달력월·출전두수·말 능력 구성에 대한 과거 기대차이를 빼고 남은 편차를 비교했다. 주로빠르기는 사용하지 않았다. 이미 보았던 과거의 후향 연구이므로 신규 미래 성능 검증이라고 표현하지 않는다.",
        "",
        "## 수치의 의미",
        "",
        "단위는 모두 Top3 입상률 차이의 **%p**다. 외측−내측이 음수면 내측 쪽, 양수면 외측 쪽이다. 초 단위 기록 보정이나 개별 말 확률 가산값으로 읽으면 안 된다.",
        "",
        "- `능력조정 차이`: 그 기간 실제 외측−내측 입상률 차이에서 추정된 말 능력 차이를 제거한 관찰값.",
        "- `과거 기준`: 이전 연도 자료로 추정한 해당 거리·함수율·달력월 등의 기대 차이.",
        "- `기준 대비 편차`: 능력조정 차이−과거 기준. 양수여도 내측 불리함이 줄었을 뿐 실제 외측 우세가 아닐 수 있다.",
        "- 95% 구간과 q는 **기준 대비 편차**에 대한 값이다. 능력조정 차이 자체의 부호에 대한 검정이 아니다.",
        "",
        "## 월별 게이트: 대표 사례",
        "",
    ]
    selected = (
        gate_months.meet.eq(1) & gate_months.period.isin(["2025-03", "2025-06", "2025-07"])
    ) | (
        gate_months.meet.eq(3)
        & gate_months.period.isin(["2024-07", "2024-08", "2024-09", "2026-08"])
    )
    lines += month_table(gate_months[selected])
    lines += [
        "",
        "서울 3월과 7월의 능력조정 관찰 차이는 -18.79%p→+21.37%p로 약 40.16%p 달랐다. 기간 간 차이를 직접 검정한 값은 아니지만, 각 월의 과거 기준 대비 편차는 별도의 월 다중비교 후에도 남았다. 부산 2026년 8월은 과거 기준 -9.29%p→관찰 +3.11%p, 편차 +12.40%p다. +12.40%p를 그대로 실제 외측 우세 크기로 사용할 수 없다.",
        "",
        f"![월별 게이트 편차]({OUT / 'monthly_gate_deviations.png'})",
        "",
        "## 연도보다 세밀하게 나눴을 때 변화가 남는가",
        "",
        "같은 연도×요일 안에서 경주일 전체를 1,000번 무작위 재배치했다. 각 연도 평균을 제거한 월평균 편차의 분산이 무작위 날짜 배치보다 큰지 확인했다. 게이트 2개, 주행위치 8개를 각각 별도 BH 처리했다. q=0.0010 수준은 1,000회 순열의 해상도 제한을 받는다.",
        "",
        "| 장소 | 지점 | 지원 월 | 관측 분산/무작위 중앙값 | q |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in summary["monthly_permutation"]:
        lines.append(
            f"| {MEETS[r['meet']]} | {r['point']} | {r['eligible_months']} | {r['observed_to_null_median']:.2f}배 | {r['q']:.4f} |"
        )
    lines += [
        "",
        "월별 게이트 138개 비교 중 20개, 상대 주행위치 550개 비교 중 54개가 q<0.05다. 서로 인접한 월·같은 경주의 지점은 독립 증거가 아니다. 위 월내 변동 진단도 경주일의 연속 의존성을 완전히 제거하지 못하며, 실제 주로 관리·기상 변화와 전개·선택 효과를 분리한 인과 검정은 아니다.",
        "",
        "## 날짜와 주말: 평균이 가리는 차이",
        "",
        "주말은 금요일 시작, 일요일 종료로 고정했다. 서울의 보통 토·일, 부산의 보통 금·일을 같은 장소 안에서 묶는다. 월요일·목요일의 해당 모집단 경주는 서울 42경주·부산 8경주이며 날짜·월 표에는 포함하고 주말 표에서 제외했다.",
        "",
        "| 장소 | 지원 날짜 | 하루 중앙 경주수 | 지원 주말 | 주말 중앙 경주수 | 같은 주말 내 일별 부호 반전 | 하루 참고구간 중앙 폭 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for d in diagnostics:
        den = d["weekends_with_two_supported_dates"]
        num = d["weekends_with_opposite_daily_signs"]
        lines.append(
            f"| {MEETS[d['meet']]} | {d['supported_dates']} | {d['supported_day_median_races']:.0f} | {d['supported_weekends']} | {d['supported_weekend_median_races']:.0f} | {num}/{den} ({100 * num / den:.1f}%) | {d['daily_reference_ci_median_width_pp']:.1f}%p |"
        )
    lines += [
        "",
        "부호 반전은 지원되는 날짜가 2일 이상인 주말에서 날짜별 **능력조정 차이**의 양·음이 함께 있었던 비율이다. 우연도 많이 포함되므로 이 비율이 곧 실제 주로의 변화율은 아니다.",
        "",
        "아래는 최근 8~9월에서 고른 설명용 사례이며, 이 날짜들을 별도의 확증 검정 구간으로 삼지 않았다. 모든 날짜·주말 값은 전체 CSV에 보존했다.",
        "",
        "| 장소 | 단위 | 날짜 또는 금요일 시작일 | 경주/일 | 능력조정 외측−내측 | 기준 대비 편차 | 참고 완화 편차 | 편차 참고구간 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    examples = overall[
        overall.point.eq("gate")
        & (
            (
                overall.meet.eq(1)
                & (
                    (overall.window.eq("date") & overall.period.isin(["2026-09-05", "2026-09-06"]))
                    | (overall.window.eq("weekend") & overall.period.eq("2026-09-04"))
                )
            )
            | (
                overall.meet.eq(3)
                & (
                    (overall.window.eq("date") & overall.period.isin(["2026-08-14", "2026-08-16"]))
                    | (overall.window.eq("weekend") & overall.period.eq("2026-08-14"))
                )
            )
        )
    ]
    for r in examples.itertuples():
        lines.append(
            f"| {MEETS[r.meet]} | {'날짜' if r.window == 'date' else '주말'} | {r.period} | {r.races}/{r.days} | {value(r.ability_adjusted_pp)} | {value(r.deviation_pp)} | {value(r.shrunk_deviation_pp)} | {interval(r.ci95_pp)} |"
        )
    lines += [
        "",
        "서울 9월 5일은 +9.56%p, 6일은 -14.28%p였지만 두 날짜 주말 평균은 -1.73%p였다. 부산 8월 14일·16일도 +0.53%p→-3.96%p로 달랐다. 작은 값을 두고도 부호가 바뀌므로 방향 변화만으로 강한 신호라고 판단하면 안 된다.",
        "",
        "하루 구간은 경주를 재표집한 탐색용 구간이다. 여러 날짜를 훑어 극단일을 선택하는 데 따른 다중비교를 해결한 구간이 아니다. 주말은 독립 경주일이 보통 2일뿐이어서 정식 신뢰구간·유의 판정을 제공하지 않았다. 참고 완화값은 고정된 `n/(n+40)×편차`이고, 최적화된 운영 보정이 아니다.",
        "",
        f"![최근 날짜와 주말]({OUT / 'recent_dates_and_weekends.png'})",
        "",
        "## 상대 주행위치도 시기별로 다른가",
        "",
        "같은 마군의 가장 안쪽·가장 바깥쪽 짝을 비교하고 경주별 짝 가중치합을 1로 두었다. 서울 S1F/3C/4C/G1F, 부산 S1F/G4F/G3F/G1F를 각각 분석했다. 아래는 게이트와 별개의 관찰값이다.",
        "",
    ]
    lateral = months[months.point.ne("gate")]
    selected = (
        lateral.meet.eq(1)
        & (
            (lateral.point.eq("3C") & lateral.period.isin(["2024-09", "2025-07"]))
            | (lateral.point.eq("4C") & lateral.period.eq("2026-01"))
        )
    ) | (
        lateral.meet.eq(3)
        & lateral.point.isin(["S1F", "G4F", "G3F"])
        & lateral.period.eq("2024-08")
    )
    lines += month_table(lateral[selected], point=True)
    lines += [
        "",
        "서울 3C도 2024년 9월 -21.95%p에서 2025년 7월 +24.03%p로 달랐다. 부산 2024년 8월에는 게이트뿐 아니라 S1F/G4F/G3F의 상대 안쪽 성향도 같은 방향으로 관찰됐다. 다만 같은 경주에서 측정한 결과라 서로 독립적인 복제 검증은 아니다. 부산 G1F의 월별 변동은 무작위 진단 q=0.0999로 분명하지 않았다.",
        "",
        "[KRA 표기 설명](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1)의 마군 괄호는 상대적인 안쪽→바깥쪽 순서다. 실제 레일에서 몇 m 떨어졌는지, 더 달린 거리, 절대 내주로·외주로는 제공하지 않는다. 실제 주행위치는 경주 후 기록이며, 현재 경주의 사전 예측 입력으로 사용할 수 없다.",
        "",
        "## 같은 날 초반·중반·후반 경주",
        "",
        "경주번호 1~3/4~6/7이상으로 나눴다. 초반·후반 각각 3경주 이상인 날의 게이트 능력조정 차이 부호 반전은 서울 198/484일(40.9%), 부산 37/88일(42.0%)이었다. 부산은 7경주 이상 구간에 3경주가 있는 날만 남으므로 일부 긴 경주일에 치우친 표본이다.",
        "",
        "단순 부호 반전이며 초·후반의 거리·두수 차이가 크고 표본이 작다. 기준 대비 편차도 함께 저장했지만 이 비율을 오후 주로 변화의 확률로 읽으면 안 된다. 실제 출발시각이 없어서 오전·오후 효과는 분석하지 않았다. [진행 구간별 값](outputs/day_phases.csv), [초반·후반 비교](outputs/early_late_changes.csv)를 보존했다.",
        "",
        "## 거리별로 더 잘게 나누는 한계",
        "",
        "전체거리 합산은 과거 거리 기준을 뺀 편차를 비교한 것이다. 거리별 원시·능력조정·기준·편차 표도 모두 보존했다. 하지만 한 거리×한 날짜는 흔히 1~2경주여서 날짜별 보조 기준 3경주를 못 채운다. 거리별 월 표는 12경주·6일 이상을 요구했고 별도 월 다중비교 판정을 붙이지 않았다.",
        "",
        "예를 들어 부산 2024년 8월 1200m는 22경주·9일, 능력조정 차이 -30.19%p, 편차 -28.99%p(개별 95% 참고구간 [-44.70,-13.28])였다. 1600m는 9경주·5일, 1800m는 10경주·8일로 기준에 못 미쳤다. 2026년 8월도 1200/1600/1800m가 각각 10/11/11경주라 전체거리에서 발견한 월 신호를 거리마다 확정할 수 없다.",
        "",
        "## 현재 연도의 월별 상태",
        "",
        "2026년 서울은 1~2월 내측 관찰 차이가 컸지만 월 다중비교에서 q<0.05를 충족하지 않았다. 부산 8월은 충족했다. 2026년 9월은 자료 종료일 20일까지의 부분 월이고 부산은 30경주·4일로 월 지원 기준을 충족하지 않았다.",
        "",
    ]
    lines += month_table(gate_months[gate_months.period.str.startswith("2026")])
    lines += [
        "",
        "## 표본·추론·검증",
        "",
        f"- 게이트 모집단: 서울 {len(g[g.meet.eq(1)]):,}경주·{g[g.meet.eq(1)].day_key.nunique():,}일, 부산 {len(g[g.meet.eq(3)]):,}경주·{g[g.meet.eq(3)].day_key.nunique():,}일. 과거 거리 기준이 충분한 비교는 서울 5,953경주, 부산 4,202경주다.",
        f"- 총 {summary['race_rows']:,}개 경주×지점 행 중 과거 거리 50경주·20일을 못 채운 {summary['unsupported_baseline_race_rows']:,}행은 주 비교에서 제외하고 원본에 표시했다. 지점별로 중복되는 행이므로 이 수치는 고유 경주 수가 아니다.",
        "- 전체거리 지원 기준: 날짜 5경주, 주말 10경주·2일, 월 40경주·6일. 정확거리 보조는 날짜 3경주, 주말 4경주·2일, 월 12경주·6일. 월 표의 지원 유무는 검정 결과를 보고 정하지 않았다.",
        "- 월 구간: 경주일 군집 t 근사. 이전 기준 모형 계수의 불확실성은 통합하지 않았다. 달 간 연속 의존성, 모형의 선형 가정과 능력 통제의 불완전함도 남는다. 보고서의 유의 월은 후향 탐색 후보다.",
        "- 게이트는 등록 출발번호의 상대 순위를 사용했다. 실제 발주기 위치와 취소 후 이동을 독립 대조한 물리적 게이트 자료는 아니다. 상대 주행위치는 현재 경주의 전개·말 상태 선택 효과도 포함한다.",
        f"- 검증 통과: 이전 기준 모형 {verification['frozen_models_checked']}개, 경주별 분해 {verification['race_decompositions_checked']:,}행, 기간별 집계 {verification['period_rows_checked']:,}행, 월별 구간·p·BH, 날짜·금~일 규칙, 지원 표시, 입력 해시. 2026년 서울·부산 게이트와 서울3C·부산G3F는 별도 최소제곱 풀이로 재적합해 예측값을 대조했다. 순열은 동일 시드로 재현했다.",
        "- 기존 주로·구간 보정 문서, 원천 DB, 운영 모델·예측확률은 변경하지 않았다.",
        "",
        "## 재현 자료",
        "",
        "- [계산 전 계획](PLAN.md), [분석 코드](analyze.py), [검증 코드](verify.py), [보고서 생성](render_report.py)",
        "- [날짜 전체표](outputs/date_effects.csv), [주말 전체표](outputs/weekend_effects.csv), [월 전체표](outputs/month_effects.csv): 두 장소·각 주행 지점·전체거리/정확거리·지원 부족 포함.",
        "- [요약·입력 해시](outputs/summary.json), [검증 결과](outputs/verification.json), [세부 기간 진단](outputs/temporal_diagnostics.json)",
        "- `race_deviations.parquet`: 경주별 분해·지원 상태. `baseline_models.json`: 이전 연도 기준의 계수·훈련 기간·전처리.",
        "",
        "프로젝트 루트에서 `.venv/bin/python thoroughbred/research/20261003_gate_lateral_time_windows/analyze.py`, `verify.py`, `render_report.py` 순서로 실행한다. 분석은 기존 outputs를 덮어쓰지 않으므로 재계산은 보존 후 새 경로에서 한다.",
        "",
        "## 부록: 월 다중비교에서 남은 모든 게이트 후보",
        "",
    ]
    lines += month_table(gate_months[gate_months.q_month.lt(0.05)])
    lines += ["", "## 부록: 월 다중비교에서 남은 모든 상대 주행위치 후보", ""]
    lines += month_table(lateral[lateral.q_month.lt(0.05)], point=True)
    (HERE / "README.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {HERE / 'README.md'} and two figures")


if __name__ == "__main__":
    main()
