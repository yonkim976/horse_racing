# ruff: noqa: E501
"""Render three-position contrasts and uncertainty without probability promotion."""

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/horse-racing-three-position-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
MEETS = {1: "서울", 3: "부산"}
POINTS = {1: ["S1F", "3C", "4C", "G1F"], 3: ["S1F", "G4F", "G3F", "G1F"]}


def profiles(results, period, gate):
    frame = results[
        results.period.eq(period)
        & results.point.eq("gate").eq(gate)
        & (results.distance_m.notna() if gate else results.distance_m.isna())
    ]
    keys = ["meet", "distance_m"] if gate else ["meet", "point"]
    rows = []
    for key, group in frame.groupby(keys):
        m = group.set_index("contrast")
        inner, outer = -m.loc["middle-inner", "effect_pp"], m.loc["outer-middle", "effect_pp"]
        rows.append(
            {
                "meet": int(key[0]),
                "distance_m" if gate else "point": int(key[1]) if gate else key[1],
                "races": int(group.races.iloc[0]),
                "days": int(group.days.iloc[0]),
                "inner_pp": float(inner),
                "middle_pp": 0.0,
                "outer_pp": float(outer),
                "q_middle_inner": float(m.loc["middle-inner", "q_family"]),
                "q_outer_inner": float(m.loc["outer-inner", "q_family"]),
                "q_outer_middle": float(m.loc["outer-middle", "q_family"]),
            }
        )
    return pd.DataFrame(rows)


def table_profiles(frame, gate):
    lines = [
        f"| 장소 | {'거리' if gate else '지점'} | 경주/일 | 내측 | 중간 | 외측 | 다중비교 후 남은 차이 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in frame.itertuples():
        names = [
            name
            for name, q in [
                ("중간−내측", row.q_middle_inner),
                ("외측−내측", row.q_outer_inner),
                ("외측−중간", row.q_outer_middle),
            ]
            if q < 0.05
        ]
        lines.append(
            f"| {MEETS[row.meet]} | {str(row.distance_m) + 'm' if gate else row.point} | {row.races}/{row.days} | {row.inner_pp:+.2f} | 0.00 | {row.outer_pp:+.2f} | {', '.join(names) if names else '뚜렷하지 않음'} |"
        )
    return lines


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    verified = json.loads((OUT / "verification.json").read_text())
    assert verified["status"] == "passed"
    results = pd.read_json(OUT / "contrasts.json")
    periods = pd.read_parquet(OUT / "periods.parquet")
    gates = profiles(results, "all", True)
    lateral = profiles(results, "all", False)
    recent_gates = profiles(results, "2024plus", True)
    recent_lateral = profiles(results, "2024plus", False)
    gates.to_csv(OUT / "gate_three_profiles.csv", index=False)
    lateral.to_csv(OUT / "lateral_three_profiles.csv", index=False)
    recent_gates.to_csv(OUT / "recent_gate_three_profiles.csv", index=False)
    recent_lateral.to_csv(OUT / "recent_lateral_three_profiles.csv", index=False)
    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 10}
    )
    fig, axes = plt.subplots(2, 4, figsize=(13, 7), sharey=True)
    for i, (meet, points) in enumerate(POINTS.items()):
        for j, point in enumerate(points):
            ax = axes[i, j]
            cell = results[
                results.period.eq("all")
                & results.meet.eq(meet)
                & results.point.eq(point)
                & results.distance_m.isna()
            ].set_index("contrast")
            a, b = cell.loc["middle-inner"], cell.loc["outer-middle"]
            values = [-a.effect_pp, 0, b.effect_pp]
            lo = [-a.ci95_pp[1], 0, b.ci95_pp[0]]
            hi = [-a.ci95_pp[0], 0, b.ci95_pp[1]]
            ax.plot(range(3), values, color="#bac4ce", lw=1)
            for x, y, lower, upper, color in zip(
                range(3), values, lo, hi, ["#175a84", "#69727c", "#bb6429"], strict=True
            ):
                ax.errorbar(
                    x, y, yerr=[[y - lower], [upper - y]], fmt="o", ms=6, color=color, capsize=3
                )
            ax.axhline(0, color="#444444", lw=0.7)
            ax.set_xticks(range(3), ["내측", "중간", "외측"])
            ax.set_title(f"{MEETS[meet]} {point}\n{int(a.races):,}경주")
            ax.grid(axis="y", alpha=0.2)
    for ax in axes[:, 0]:
        ax.set_ylabel("중간 대비 Top3 차이 (%p)")
    fig.suptitle("3두 이상 같은 마군에서의 세 위치 · 2018~2026년 능력조정 관찰 차이", fontsize=13)
    fig.text(
        0.5,
        0.015,
        "중간=0은 비교 기준. 양쪽 구간은 경주일 군집 개별 95% 구간이며 다중비교 판정과 구분.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.96))
    fig.savefig(OUT / "three_lateral_profiles.png", dpi=170)
    plt.close(fig)
    monthly = periods[periods.window.eq("month") & periods.distance_m.isna() & periods.supported]
    monthly_examples = monthly[
        monthly.point.eq("gate")
        & (
            (monthly.meet.eq(1) & monthly.period.isin(["2025-03", "2025-07"]))
            | (monthly.meet.eq(3) & monthly.period.isin(["2024-08", "2026-08"]))
        )
    ]
    lines = [
        "# 게이트와 주행위치의 내측 중간 외측 비교",
        "",
        "2026-10-03. 기존 연구에 중간을 추가해 세 위치를 같은 표본에서 비교했다. 서울·부산, 출발 게이트·실제 주행 지점, 전체기간·최근기간·거리·날짜·주말·월을 구분했다.",
        "",
        "**중간에 내측·외측의 평균값을 줄 수 없다.** 서울1200m 게이트와 서울3코너는 내측→중간→외측 순으로 낮아졌지만, 부산1200m 게이트는 중간·외측 차이가 불분명했다. 부산 G4F는 중간·내측 차이가 불분명한 가운데 외측이 낮았고, 부산 G1F는 전체기간에서 중간이 양쪽보다 낮았다.",
        "",
        "## 세 단계의 정의",
        "",
        "게이트는 기존 출전마 상대 마번순 3등분이다. 연속 마번 12두면 내측1~4·중간5~8·외측9~12, 10두면1~3·4~7·8~10, 14두면1~5·6~9·10~14다. 취소마를 제외한 남은 순위로 나누었으며 실제 발주대 이동을 독립 대조한 물리적 게이트 자료는 아니다.",
        "",
        "주행위치는 같은 마군의 맨 안쪽1두·사이 말들·맨 바깥쪽1두다. `(2,7,4)`이면 내측2·중간7·외측4, `(2,7,4,9)`이면 내측2·중간7/4·외측9다. 중간이 여러 두면 그 말들의 평균을 사용한다. 선행·중위·후미나 전체 출전마의 앞뒤 위치, 절대 레일부터의 몇 번째 라인을 뜻하지 않는다.",
        "",
        "[KRA 표기 설명](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1)에 따른 상대 내측→외측 순서를 사용했다. 3두 이상 마군만 세 위치를 동시에 비교할 수 있어 주행위치 주 분석에서1~2두 마군을 제외했다. 이 표본 변경으로 기존의2두 이상 내외측 결과와 값이 달라질 수 있다.",
        "",
        f"3두 이상 마군 {summary['lateral_coverage']['packs_3plus']:,}개, 출전마×지점 {summary['lateral_runner_rows']:,}행이다. 유효 통과표에서 제외된1두 마군164,009개·2두 마군114,169개도 수량을 기록했다. 마군·지점이 겹치는 수치이므로 고유 경주 수와 다르다.",
        "",
        "## 수치를 읽는 방법",
        "",
        "아래 표는 **중간을0으로 둔 상대 Top3 차이, 단위%p**다. 중간=0은 비교 기준이며 입상률이0이거나 중간 보정이 항상 불필요하다는 뜻이 아니다. 내측이+2라면 능력을 조정한 내측−중간 차이가+2%p라는 뜻이다. 실제 입상확률·기록 초·개별 말 확률 가산으로 사용하지 않는다.",
        "",
        "중간−내측, 외측−내측, 외측−중간의 세 비교를 검정했다. 마지막 열은 기간별 BH q<0.05를 충족한 비교만 표시한다. 단순히 추정값이 높은 위치와 차이가 분명한 위치를 구분해야 한다.",
        "",
        "## 출발 게이트 거리별 전체기간",
        "",
    ]
    lines += table_profiles(gates, True)
    lines += [
        "",
        "서울1200m는 내측>중간>외측 세 차이가 모두 남았다. 부산1200m는 내측이 중간·외측보다 높았지만 중간과 외측 사이 차이는 불분명하다. 부산1600m는 중간·외측이 내측보다 높았으나 외측이 중간보다 높다는 차이는 불분명하다. 서울1600m도 내측이 두 위치보다 높고 중간·외측 차이는 불분명하다.",
        "",
        "## 주행위치 전체기간",
        "",
    ]
    lines += table_profiles(lateral, False)
    lines += [
        "",
        "- 서울3C: 내측>중간>외측의 세 차이가 모두 남았다. 내측과 외측만 비교할 때보다 중간의 성격이 분명해진다.",
        "- 서울S1F: 내측이 중간·외측보다 높고 중간·외측 차이는 불분명하다. 서울4C는 세 위치 차이가 모두 불분명하다.",
        "- 서울G1F: 외측이 내측·중간보다 높고 내측·중간 차이는 불분명하다.",
        "- 부산G4F: 외측이 내측·중간보다 낮고 내측·중간 차이는 불분명하다. 부산G3F는 외측이 중간보다 낮다는 차이만 남았다.",
        "- 부산G1F: 외측>내측>중간의 세 차이가 모두 남았다. 부산S1F는 세 위치 차이가 불분명하다.",
        "",
        f"![세 주행위치 비교]({OUT / 'three_lateral_profiles.png'})",
        "",
        "G1F의 외측 관찰 차이를 외주로 표면의 이점으로 해석하지 않는다. 남은 힘·추월·진로선택 등 경주 진행의 결과가 실제 위치에 포함된다. 현재 경주의 실제 위치는 경주 후 자료다.",
        "",
        "## 2024년 이후 게이트",
        "",
    ]
    lines += table_profiles(recent_gates, True)
    lines += ["", "## 2024년 이후 주행위치", ""]
    lines += table_profiles(recent_lateral, False)
    lines += [
        "",
        "서울G1F의 외측 차이는 최근기간에도 내측·중간 각각 대비 남았다. 부산G4F의 외측−중간 차이도 최근 -6.41%p로 남았다. 서울3C의 내측 방향은 유지됐으나 최근 세 대비의 q값은 모두0.05이상이다. 부산G1F의 중간이 낮은 방향도 최근 관찰되지만 세 대비의 q값은 모두0.05이상이므로 장기 결과를 현재의 확정 보정으로 옮기기 어렵다.",
        "",
        "## 월별로 보면 중간의 성격도 바뀌는가",
        "",
        "2020~2026년 각 연도 이전 자료만으로 만든 기준을 사용했다. 게이트 기준 모형은 직전 세부기간 연구의 것을 그대로 재사용했고, 주행위치는 이번3두 이상 마군 표본과 마군 고정효과로 새로 학습했다.",
        "",
        "다음 표는 전체거리 합산의 **능력조정 관찰 차이**를 중간=0으로 표시한 것이다. 과거 거리·함수율·달력월 등의 기대차이를 뺀 편차와 그 q값은 전체표에 별도로 저장했다.",
        "",
        "| 장소 | 월 | 경주/일 | 내측 | 중간 | 외측 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for (meet, period), group in monthly_examples.groupby(["meet", "period"]):
        cell = group.set_index("contrast")
        a, b = cell.loc["middle-inner"], cell.loc["outer-middle"]
        lines.append(
            f"| {MEETS[meet]} | {period} | {int(a.races)}/{int(a.days)} | {-a.ability_adjusted_pp:+.2f} | 0.00 | {b.ability_adjusted_pp:+.2f} |"
        )
    lines += [
        "",
        "부산2026년8월은 내외측만 보면 외측이 내측보다+3.11%p 높았다. 세 위치로 보면 중간이 가장 높은 점추정이고 내측은 중간보다-5.26%p, 외측은-2.15%p였다. 어느 위치가 최고인지에 대한 확정 판정은 아니다. 이 달의 세 기준 대비 편차는 모두 삼단계 월별 다중비교 후 q≥0.05다.",
        "",
        "이번에는 세 대비까지 다중비교 가족에 포함했다. 게이트414개 지원 월 대비 중11개, 상대 주행위치1,269개 지원 월 대비 중1개가 q<0.05였다. 주행위치는 부산G4F 2020년7월 외측−내측 편차만 남았고 최근기간의 월별 세 대비는 남지 않았다. 같은 월이라도3두 이상 마군 표본이 줄고 비교가 늘어, 앞선 내외측 연구보다 판단이 보수적으로 바뀐다.",
        "",
        "서울2025년7월과 부산2026년8월의 게이트 외측−내측 편차는 이전 두 위치 연구에서는 q<0.05였지만 이번 세 대비 가족에서는 둘 다 q≈0.0521이다. 관찰값은 그대로이고 다중비교 범위가 넓어진 결과다. 과거 기준 모형 계수 불확실성은 구간에 통합하지 않았다.",
        "",
        "## 보정 설계에 주는 의미",
        "",
        "중간에 내외측의 산술 평균을 주는 규칙은 피해야 한다. 경기장×거리의 게이트, 경기장×지점의 주행위치에서 내측−중간·외측−중간 계수를 각각 추정하고, 최근 편차를 동일한 시간 감쇠·표본 완화 규칙으로 줄이는 구조가 적합한 연구 후보다. 두 위치 계수는 같은 표본에서 함께 추정해야 하며 독립적인 신호처럼 중복 가산하지 않는다.",
        "",
        "날짜·주말·월 값은 같은 경주를 겹쳐 포함하므로 별도 보정 세 개로 더하지 않는다. 주행위치 보정에는 사전 시점에 예상한 위치가 필요하다. 실제 현재 위치를 사용한 성적 연관성을 확률 가산·초 단위 환산으로 바로 채택하지 않았다. 시간순 예측 검증은 후속 단계다.",
        "",
        "## 방법과 검증",
        "",
        "게이트는 경주 고정효과·경주당 총가중치1. 주행위치는 같은 마군 고정효과·한 경주 안 마군 동일가중·마군 안 세 위치 동일가중이다. 중간 말이 여러 두여도 중간 전체의 가중치가 양쪽 각1두와 같도록 했다. 경주일 군집 t 근사95% 구간을 사용했다.",
        "",
        "레이팅·나이·부담중량·이전 날짜 최근5회 상대착순·Top3율·초반위치·출전수·간격을 조정했다. 주행위치에는 출발번호 상대위치도 조정했다. 현재 실제 초반위치·최종배당은 주 분석 통제에 사용하지 않았다. 함수율은 이전 기준의 숫자 함수율 구간이며 주로빠르기를 사용하지 않았다.",
        "",
        "전체·거리 비교는50경주·20일 이상. 전체거리 세부기간은 날짜5경주, 금~일 주말10경주·2일, 월40경주·6일을 요구했다. 정확거리 보조는3/4/12경주, 주말2일·월6일이다. 과거 거리50경주·20일 기준이 부족한 경주도 원본에 표시하고 세부기간 주 비교에서는 제외했다. 날짜·주말은 기술 값만 제공한다.",
        "",
        "게이트 거리별3대비×두 장소를 전체·최근 기간별로 별도 BH, 주행위치 전체거리3대비×8지점도 기간별 별도 BH 처리했다. 주행위치 거리별 표는 개별 보조구간이며 별도 확증 다중비교 판정을 붙이지 않았다. 세 대비는 서로 종속된다.",
        "",
        f"검증 통과: 원문 연결 {verified['source_runner_rows_checked']:,}행·{verified['source_three_packs_checked']:,}마군, 별도 가중 최소제곱·군집구간으로 전체기간 주요 {len(verified['independent_main_refits'])}모형 재현, 이전 연도 기준8개 지점의2026년 모형 별도 재현, 경주별 {verified['temporal_race_contrasts_checked']:,}대비·기간별 {verified['period_contrasts_checked']:,}대비 집계 대조. 세 대비의 산술 관계와 원천 능력값·가중치·월별 구간·BH·입력 해시도 확인했다.",
        "",
        "이미 관찰한 과거 자료의 재분석이며 독립적인 신규 미래 검증이 아니다. 기존 연구·원천 DB·운영 모델·합의된 함수율 보정은 변경하지 않았다.",
        "",
        "## 파일",
        "",
        "- [계산 전 계획](PLAN.md), [분석](analyze.py), [검증](verify.py), [보고서 생성](render_report.py)",
        "- [게이트 세 위치 요약](outputs/gate_three_profiles.csv), [주행위치 세 위치 요약](outputs/lateral_three_profiles.csv), [최근 게이트](outputs/recent_gate_three_profiles.csv), [최근 주행위치](outputs/recent_lateral_three_profiles.csv)",
        "- [날짜별 전체표](outputs/date_contrasts.csv), [주말별 전체표](outputs/weekend_contrasts.csv), [월별 전체표](outputs/month_contrasts.csv)",
        "- [모든 대비와 개별 구간](outputs/contrasts.json), [요약·입력 해시](outputs/summary.json), [검증 결과](outputs/verification.json)",
        "- `three_position_runners.parquet`: 모든3두 이상 마군의 위치·마번·능력값. `main_models.json`·`baseline_models.json`: 기준 계수. `race_contrasts.parquet`·`periods.parquet`: 세 대비 전체.",
        "",
        "프로젝트 루트에서 `.venv/bin/python thoroughbred/research/20261003_three_lateral_positions/analyze.py`, 같은 폴더의 `verify.py`, `render_report.py` 순서로 실행한다. 분석은 기존 outputs 덮어쓰기를 거부한다.",
        "",
    ]
    (HERE / "README.md").write_text("\n".join(lines))
    print(f"Wrote {HERE / 'README.md'}")


if __name__ == "__main__":
    main()
