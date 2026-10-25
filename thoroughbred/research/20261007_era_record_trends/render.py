"""Render era-change results with support and comparison-period sensitivity."""

# ruff: noqa: E501
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
CENTRAL = HERE.parent / "conclusions"
LABELS = {
    "early": "출발200m",
    "middle1": "중간1(거리−800m)",
    "middle2": "중간2 400m",
    "late": "마지막200m",
    "finish": "전체시간",
    "last600": "마지막600m(중복)",
    "early_relative_pct": "초반 상대속도",
    "late_relative_pct": "막판200m 상대속도",
    "last600_relative_pct": "막판600m 상대속도",
}
WINDOW_LABELS = {
    "common_jan_aug": "2018~2023 대2024~2026, 각1~8월",
    "complete_2024_2025": "2018~2023 대2024~2025, 완결연도",
    "nearby_complete": "2021~2023 대2024~2025, 완결연도",
    "all_available_partial_2026": "2018~2023 대2024~2026 관측 전체(2026부분연도)",
}


def num(x, n=2):
    return "—" if pd.isna(x) else f"{x:+.{n}f}"


def table(headers, rows):
    return (
        "| "
        + " | ".join(headers)
        + " |\n|"
        + "|".join(["---"] * len(headers))
        + "|\n"
        + "".join("| " + " | ".join(str(x) for x in row) + " |\n" for row in rows)
    )


def main():
    assert json.loads((OUT / "verification.json").read_text())["passed"]
    d = pd.read_csv(OUT / "era_contrasts.csv")
    summary = json.loads((OUT / "summary.json").read_text())
    annual = pd.read_csv(OUT / "annual_race_means.csv")
    main = d.loc[d.window.eq("common_jan_aug") & d.band.eq("전체")]
    whole = main.loc[main.part.eq("finish")]
    focal = []
    for meet, distance in [
        ("서울", 1200),
        ("부산", 1200),
        ("서울", 1300),
        ("부산", 1300),
        ("서울", 1400),
        ("부산", 1400),
        ("서울", 1700),
        ("서울", 1800),
        ("부산", 1800),
    ]:
        rows = whole.loc[whole.meet.eq(meet) & whole.distance_m.eq(distance)]
        a = rows.loc[rows.specification.eq("exact_matched")].iloc[0]
        b = rows.loc[rows.specification.eq("composition_adjusted")].iloc[0]
        focal.append(
            [
                f"{meet}{distance}m",
                num(a.raw_difference),
                num(a.difference),
                num(b.difference),
                f"{num(b.ci_low)} ~ {num(b.ci_high)}",
                f"{b.before_races}/{b.recent_races}",
            ]
        )
    whole_table = table(
        [
            "지역·거리",
            "원시 차이",
            "등급·함수율·월 매칭",
            "출전마 구성도 통제",
            "추가 통제의 점별95%구간",
            "공통층 경주 과거/최근",
        ],
        focal,
    )
    section = main.loc[
        main.specification.eq("composition_adjusted")
        & main.part.isin(["early", "middle1", "middle2", "late"])
        & (
            (main.meet.eq("서울") & main.distance_m.eq(1200))
            | (main.meet.eq("부산") & main.distance_m.eq(1400))
        )
    ]
    section_table = table(
        ["지역·거리", "구간", "최근−과거 차이(초)", "점별95%구간"],
        [
            [
                f"{r.meet}{r.distance_m}m",
                LABELS[r.part],
                num(r.difference, 3),
                f"{num(r.ci_low, 3)} ~ {num(r.ci_high, 3)}",
            ]
            for r in section.itertuples()
        ],
    )
    intro = """최근2024~2026년이 이전보다 모든 거리에서 일괄적으로 빨라졌다는 결과는 아니다. 전체시간 차이가 작은1200m에서도 중간과 막판의 기록 배분은 달라진 방향이 관찰된다. 서울1200m는 중간1 400m가 약0.15초 빨라지고 마지막200m가 약0.12초 느려졌으며, 이 방향은 비교 기간을 바꿔도 남았다. 부산1800m는 조건을 맞춘 공통층에서 최근 전체시간이 느린 방향이 여러 기간에 걸쳐 관찰됐다.

‘최근 − 과거’를 비교한 후향 관찰이다. 말의 품종 개량·체력 변화·기수 전략·주로 관리·계측체계 변경 중 어느 것이 원인인지는 분리하지 않았다.2024년에 구조 변화가 발생했다거나 해마다 한 방향으로 변하는 추세를 입증한 결과도 아니다.
"""
    interpretation = """서울·부산1200m의 전체시간 차이는 추가 통제 후 각각−0.058초·−0.080초이며95%구간이0을 포함한다. 현재 자료만으로 전체시간의 명확한 시대 개선이나 악화를 주장하기 어렵다. 서울1400m의 원시+0.504초 차이는 같은 등급·정확 함수율·월의 공통층에서+0.037초로 작아진다. 그러나 공통층과 원시 평균의 모집단이 다르므로 ‘차이의 몇%가 편성 탓’처럼 원인을 정량 분해한 것으로 읽지 않는다.

부산1800m는 주 비교에서 등급·함수율·월 매칭+0.856초, 출전마 구성 추가 통제+1.223초(점별95%:+0.619~+1.936)다. 완결2024~2025년·가까운2021~2023년 기준 비교에서도 추가 통제 후 느린 방향이 남았다. 다만 주 비교 공통층은 과거62경주·최근70경주이며 각 시기 전체의23.2%·30.0%에 해당한다. 전 경주 또는 모든 말의 능력 저하로 확대하지 않는다.

서울1700m는 오래된2018~2023년과 비교하면 최근 빨라진 방향이지만,2021~2023년과2024~2025년을 비교한 값은 방향이 달라지고 표본지원도 제한된다.1300m의 빠른 차이는 출전마 구성 통제 여부에 민감하다. 비교 기간·통제 방식에 의존하는 결과를 모든 거리의 시대 보정으로 묶지 않는다.
"""
    sections_text = """서울1200m에서 ‘중간1’은 출발200m 이후400m이고 ‘중간2’는 그다음400m다. 최근 전체시간은 크게 달라지지 않아도 중간1이 빨라지고 마지막200m가 느려지는 배분 변화가 보인다. 정확 매칭만 할 때도 각각−0.122초·+0.148초다. 완결연도·가까운연도 비교 모두 같은 방향이며 점별 구간이0을 포함하지 않았다.

부산1400m는 출발200m −0.140초·중간2 400m +0.346초로, 초반이 빨라지고 후반 일부가 느린 방향이다. 이 두 구간의 방향은 비교 기간과 통제 수준을 바꿔도 남았다. 이는 개별 말 기록을 경주평균으로 집계한 구간 배분 변화다. 선두마의 실제 경주 페이스를 직접 계측하거나 빠른 초반이 막판 저하를 일으킨 인과관계를 입증한 것은 아니다.

서울1200m의 마지막200m 상대속도는 추가 통제 후 약−0.842%p, 부산1400m의 마지막600m 상대속도는−0.757%p다. 상대속도는100×구간거리×전체시간/(경주거리×구간시간)이며 먼저 개별 말에서 계산한 뒤 경주평균을 냈다. 전체시간 대비 해당 구간의 비중 변화이고 시간과 산술적으로 연결되므로 독립적인 능력 신호로 중복 가산하지 않는다.
"""
    method = """- 입력은 앞선11거리 최종 품질 모집단151,074출전기록·13,928경주다. 서울·부산19개 지역×거리이며1000/1200/1300/1400/1600/1700/1800/1900/2000/2200/2300m를 포함한다. 영천·제주·주행심사·주로빠르기를 제외했다. 새 꼬리절사는 하지 않았다.
- **주 비교:2018~2023년 대2024~2026년, 모든 해의1~8월만 사용.**2026년은 서울9월20일·부산9월18일까지만 있으므로 부분9월과 없는10~12월을 피했다. 주 비교에서2026년9월 기록은 사용하지 않는다. 보조 창은 완결2024~2025년, 가까운2021~2023년 기준, 부분2026년을 포함한 관측 전체다. 각 창의 연도·월 목록은 요약JSON에 보존했다.
- 같은 지역·거리 안에서 **경주등급×정확 함수율 숫자×달력 월**이 두 시기에 모두 있는 층만 사용했다. 주 비교와 건조1~5% 별도 비교를 보존했다. 공통층 밖 기록은 해당 비교에서 제외하며 겹치는 비율을 공개한다. 지역·거리별로 참조집단은 다르다.
- 각 경주평균 동일가중이다. 첫 모형의 시기 차이는 층별 평균 차이를 n과거×n최근/(n과거+n최근)로 가중한 정확 매칭값과 같다. 두 번째는 연령·부담중량·rating·과거성적·초반위치·출전수·공백·두수·성별구성·결측비율을 통제한 회귀다. rating0이하는 결측으로 유지했다. 시대 지시변수와 중복되는 연도 고정효과는 넣지 않았다. 연도마다 같은 가중치를 준 모형이나 동일 말을 반복 추적한 패널은 아니다.
- 정확 층 고정효과를 가중 평균 제거로 계산했다.200회 날짜 군집 재표집에서 달력연도별로 날짜를 복원추출하고 매번 층 평균·계수를 다시 계산했다. 숫자 전처리는 고정했다. 전체시간과 마지막600m는 독립구간 계수와 재표집값을 더해 계산했다. 유효180회 미만이면 구간을 제공하지 않는다.
- 관측지원은 공통층20개 이상·두 시기 각각50경주/20일/2개년 이상·대비 식별 가능·잔차 자유도 양수다. `interpretation_support`는 여기에 재표집180회 조건까지 충족한 경우다. 이는 효과가0과 다르다는 보증이 아니다. 모든95%구간은 다중비교를 조정하지 않은 점별 탐색 구간이다. 기간별 민감도는 서로 겹치는 자료의 재분석이며 독립된 미래 표본의 재현 검증은 아니다.
- 연도별 원시 평균은 경주 동일가중, 개인 기록의 평균·P20·중앙값·P80은 출전기록 동일가중으로 구분했다. 최근 각 연도별 매칭은2018~2023년 기준과1~8월의 정확 공통층을 사용했지만 연도마다 겹치는 층이 달라 별도 기술 점검으로만 읽는다. 등급별 매칭차와 시기별 등급·함수율 구성도 보존했다.
- 독립4구간 합이 전체시간이고 마지막600m는 중간2+마지막200m다. 서울의 미계측 마지막400m는 생성하지 않았다. 부산 직접계측400m는 기존 자료에 있으나 이번 공통 비교에 넣지 않았다.
"""
    implication = """기록 기준은 오래된 전체기간 평균 하나로 고정하기보다 최근 분포를 중심으로 유지하고, 전체시간과 구간 배분의 변화를 따로 점검할 필요가 있다. 현재 최근2024년 이후 기준을 사용하는 방향과 일치한다. 이번 결과만으로 매년 일정한 초를 빼거나 더하는 시대 보정,2024년 기준 일괄 보정을 채택하지 않는다. 기존 함수율 보정·거리별 기준표·운영 모델은 그대로 유지했다.

자료는 정상 완주와 기존 검증 조건을 충족한 선택 모집단이다. 생존·출전·편성 구성과 과거 이력 측정이 시대별로 다를 수 있고, 같은 등급·rating도 장기간 동일한 잠재능력을 보장하지 않는다. 실제 기온·바람·주로 관리·기수·혈통·계측 프로토콜 변경을 별도 결합하지 않았다. 원인을 확인하거나 지속적인 향상을 판단하려면 연도별 조건 표준화·계측 정의 점검·시간순 재현성을 추가로 확인해야 한다.
"""
    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 10}
    )
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    ax = axes[0, 0]
    for meet, color in [("서울", "#176b9e"), ("부산", "#d87c20")]:
        a = annual.loc[
            annual.window.eq("jan_aug") & annual.meet.eq(meet) & annual.distance_m.eq(1200)
        ].sort_values("year")
        ax.plot(a.year, a.finish, "o-", label=meet, color=color)
    ax.set_title("1200m 연도별 원시 경주평균 · 각1~8월")
    ax.set_ylabel("전체시간(초)")
    ax.set_xticks(range(2018, 2027))
    ax.tick_params(axis="x", labelrotation=45)
    ax.legend()
    ax.grid(alpha=0.15)
    ax = axes[0, 1]
    cases = [
        ("서울", 1200),
        ("부산", 1200),
        ("서울", 1400),
        ("부산", 1400),
        ("서울", 1700),
        ("부산", 1800),
    ]
    for offset, spec, color, label in [
        (-0.13, "exact_matched", "#999999", "등급·함수율·월 매칭"),
        (0.13, "composition_adjusted", "#176b9e", "출전마 구성도 통제"),
    ]:
        for i, (meet, dist) in enumerate(cases):
            r = whole.loc[
                whole.meet.eq(meet) & whole.distance_m.eq(dist) & whole.specification.eq(spec)
            ].iloc[0]
            ax.errorbar(
                r.difference,
                i + offset,
                xerr=np.array([[r.difference - r.ci_low], [r.ci_high - r.difference]]),
                fmt="o",
                color=color,
                capsize=3,
                label=label if i == 0 else None,
            )
    ax.axvline(0, color="#888888", lw=0.8)
    ax.set_yticks(range(len(cases)), [f"{m}{d}m" for m, d in cases])
    ax.invert_yaxis()
    ax.set_xlabel("최근 - 과거 전체시간 차이(초)")
    ax.set_title("공통층의 전체시간 차이 · 점별95%구간")
    ax.legend(fontsize=8)
    ax.grid(axis="x", alpha=0.15)
    for ax, (meet, dist) in zip(axes[1], [("서울", 1200), ("부산", 1400)], strict=True):
        v = (
            section.loc[section.meet.eq(meet) & section.distance_m.eq(dist)]
            .set_index("part")
            .loc[["early", "middle1", "middle2", "late"]]
        )
        ax.bar(
            range(4),
            v.difference,
            color=["#176b9e" if x < 0 else "#d87c20" for x in v.difference],
            alpha=0.8,
        )
        ax.errorbar(
            range(4),
            v.difference,
            yerr=np.vstack([v.difference - v.ci_low, v.ci_high - v.difference]),
            fmt="none",
            ecolor="#333333",
            capsize=4,
        )
        ax.axhline(0, color="#888888", lw=0.8)
        ax.set_xticks(range(4), ["출발200m", f"중간1 {dist - 800}m", "중간2 400m", "마지막200m"])
        ax.set_ylabel("최근 - 과거 차이(초)")
        ax.set_title(f"{meet}{dist}m 독립구간 · 출전마 구성 추가 통제")
        ax.grid(axis="y", alpha=0.15)
    fig.suptitle("2024년 전후의 기록 수준과 구간 배분 변화", fontsize=17)
    fig.text(
        0.5,
        0.014,
        "주 비교:2018~2023 대2024~2026, 각1~8월 · 음수=빠름 · 구간은 다중비교 미조정\n원시 연도별 평균과 공통층의 통제 결과는 모집단이 다름 · 시대 원인·2024년 구조 변화 입증 아님",
        ha="center",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.96))
    fig.savefig(OUT / "era_record_changes.png", dpi=160)
    plt.close(fig)
    readme = "# 2024년 전후 전체 기록과 구간 배분의 변화\n\n2026-10-07 · 연구용 v1\n\n" + intro
    readme += (
        "\n## 전체시간 차이\n\n단위 초. 주 비교는 각 해1~8월의2018~2023년 대2024~2026년이며 음수는 최근이 빠른 방향이다. 원시 차이는 비교 창의 모든 경주, 매칭·추가 통제는 공통층 경주에서 계산했다.\n\n"
        + whole_table
        + "\n"
        + interpretation
    )
    readme += (
        "\n![연도별 기록과 구간 변화](outputs/era_record_changes.png)\n\n## 전체시간에 가려진 구간 변화\n\n"
        + section_table
        + "\n"
        + sections_text
    )
    readme += (
        "\n## 비교 기간과 통제 방법\n\n"
        + method
        + "\n## 기록 기준에 대한 의미와 한계\n\n"
        + implication
    )
    readme += """\n## 원 결과와 검증

- [모든 거리·기간·구간 결과](ALL_RESULTS.md), [원천과 계산 정의](SOURCES.md), [입력 해시·분석 창](outputs/summary.json)
- [시기 차이1710행](outputs/era_contrasts.csv), [공통층 지원과 제외 비율](outputs/overlap_support.csv), [경주별 분석 입력](outputs/analysis_race_means.parquet), [공통층 경주 키](outputs/model_membership.parquet)
- [정확 매칭층](outputs/exact_matched_strata.parquet), [날짜 재표집](outputs/date_bootstrap_contrasts.parquet), [연도별 경주평균](outputs/annual_race_means.csv), [연도별 개별기록 분포](outputs/annual_runner_distributions.csv)
- [등급·함수율 구성](outputs/era_grade_moisture_mix.csv), [등급별 매칭 변화](outputs/grade_matched_changes.csv), [최근 각 연도 매칭](outputs/recent_year_matched_changes.csv)
- [독립 수치 검증](outputs/verification.json), [별도 더미 회귀 대조](outputs/explicit_dummy_verification.csv), [게시·중앙문서 검증](outputs/final_verification.json)
- [게시 요약](PUBLICATION.md), [게시JSON](outputs/web_era_record_trends.json), [중앙 결론](../conclusions/24_ERA_RECORD_TRENDS.md), [산출물 용량](outputs/artifact_inventory.json)
"""
    (HERE / "README.md").write_text(readme)
    all_results = "# 시대별 기록 변화의 거리별 세부 결과\n\n2026-10-07. 모든 수치는 최근−과거다. 초 또는 상대속도%p를 구분한다. —는 식별 불가 또는 불확실성 지원 부재이며0이 아니다. `*`는 관측/재표집 지원 제한이다.\n\n"
    for window, label in WINDOW_LABELS.items():
        v = d.loc[d.window.eq(window) & d.band.eq("전체") & d.part.eq("finish")]
        rows = []
        for (meet, dist), g in v.groupby(["meet", "distance_m"], observed=True):
            a = g.loc[g.specification.eq("exact_matched")].iloc[0]
            b = g.loc[g.specification.eq("composition_adjusted")].iloc[0]
            rows.append(
                [
                    f"{meet}{dist}m",
                    num(a.raw_difference, 3),
                    num(a.difference, 3)
                    + ("*" if not a.interpretation_support and pd.notna(a.difference) else ""),
                    num(b.difference, 3)
                    + ("*" if not b.interpretation_support and pd.notna(b.difference) else ""),
                    f"{num(b.ci_low, 3)} ~ {num(b.ci_high, 3)}",
                    f"{b.before_overlap_share:.1%}/{b.recent_overlap_share:.1%}",
                ]
            )
        all_results += (
            f"## {label}\n\n"
            + table(
                [
                    "지역·거리",
                    "원시 차이",
                    "정확 매칭",
                    "출전마 구성도 통제",
                    "추가통제 점별95%",
                    "공통층 비율 과거/최근",
                ],
                rows,
            )
            + "\n"
        )
    v = main.loc[
        main.specification.eq("composition_adjusted")
        & main.part.isin(["early", "middle1", "middle2", "late"])
    ]
    all_results += "## 주 비교의 독립구간\n\n" + table(
        ["지역·거리", "구간", "차이(초)", "점별95%", "지원"],
        [
            [
                f"{r.meet}{r.distance_m}m",
                LABELS[r.part],
                num(r.difference, 3),
                f"{num(r.ci_low, 3)} ~ {num(r.ci_high, 3)}",
                "충족" if r.interpretation_support else "제한/식별불가",
            ]
            for r in v.itertuples()
        ],
    )
    a = annual.loc[annual.window.eq("jan_aug") & annual.distance_m.eq(1200)]
    all_results += (
        "\n## 1200m 연도별 원시 기록\n\n각1~8월의 경주평균이며 등급·주로·출전마 구성 통제가 없는 기술 통계다.\n\n"
        + table(
            ["지역", "연도", "경주", "전체시간", "중간1 400m", "마지막200m"],
            [
                [r.meet, r.year, r.races, f"{r.finish:.3f}", f"{r.middle1:.3f}", f"{r.late:.3f}"]
                for r in a.itertuples()
            ],
        )
    )
    (HERE / "ALL_RESULTS.md").write_text(all_results.replace("정확 매칭", "정확 매칭"))
    (HERE / "SOURCES.md").write_text("""# 원천과 계산 출처

2026-10-07. 새 DB 조회·날씨 결합 없이 기존 검증 모집단을 읽기 전용 사용했다.

- [직전 계절 연구](../20261007_seasonal_same_moisture/README.md)의 population.parquet·race_means.parquet·summary.json·verification.json이 입력이다. [그 원천 설명](../20261007_seasonal_same_moisture/SOURCES.md)에서 원11거리 품질 모집단과 계측 정의를 확인한다. 입력4개 SHA-256은 [요약](outputs/summary.json)에 보존했다.
- 전체·구간 초는 원 파일과 동일하며 개인 구간 상대속도만 추가 계산해 경주평균으로 붙였다. 모든 ratio의 분모는 해당 구간시간이고 단위는%다. 차이는%p로 표시한다. ratio의 평균과 경주평균 시간들의 비율을 혼동하지 않는다.
- 같은 등급·정확 함수율·월을 층 고정효과로 제거한 시기 지시변수 회귀다. 첫 모형은 정확 매칭의 조화가중 평균과 동치이고, 추가 통제는 출전마 구성과 결측비율이다. 자체 NumPy 계산이며 별도 SciPy 희소 더미 회귀로 대조했다. 원 계절 문서의 통계 공식 문서는 방법 참고다.
- 날짜 군집 재표집200회는 연도 안에서 날짜를 다시 뽑아 가중 층 평균과 회귀를 재추정했다. 전처리와 분석 창은 고정했고 유효180회 미만의 구간은 비웠다. 구간은 점별95%이며 여러 비교를 조정하지 않았다.
- [독립 검증](outputs/verification.json)에서 원 경주평균 보존, 개별 상대속도, DuckDB 매칭층, 별도 더미 회귀, 재표집 분위수, 연도별 원시 평균·개별 분위수 및 분석 창을 확인했다. [게시 정합성](outputs/final_verification.json)과 [자기포함 용량 명세](outputs/artifact_inventory.json)를 보존했다.

기온·바람·혈통·기수 전략·주로 관리·계측 프로토콜의 시대별 원인 자료는 결합하지 않았다.2024년의 인과적 전환점·지속적 능력 향상·사전 예측 개선을 입증한 것으로 표현하지 않는다.
""")
    publication = (
        "# 최근 경주 기록은 과거와 달라졌을까\n\n2026-10-07 · 연구 참고 · 새 보정 채택 없음\n\n"
        + intro
    )
    publication += (
        "\n주 비교는2018~2023년과2024~2026년의 각1~8월이다.2026년 부분연도의 계절 차이를 줄이기 위해 같은 완결8개월을 사용했다. 같은 지역·거리·등급·정확 함수율·월의 공통층만 비교했다.\n\n"
        + whole_table
        + "\n"
        + sections_text
        + "\n"
        + implication
    )
    publication += "\n[전체 보고서](README.md) · [기간별 결과](ALL_RESULTS.md) · [원천과 정의](SOURCES.md) · [게시JSON](outputs/web_era_record_trends.json)\n"
    (HERE / "PUBLICATION.md").write_text(publication)
    topic = (
        "# 24. 2024년 전후 기록 수준과 구간 배분 변화\n\n2026-10-07. [원 연구](../"
        + HERE.name
        + "/README.md) · [세부표](../"
        + HERE.name
        + "/ALL_RESULTS.md)\n\n"
        + intro
    )
    topic += (
        "\n주 비교:2018~2023 대2024~2026의 각1~8월. 단위 초, 음수=최근이 빠름. 원시와 공통층은 모집단이 다르다.\n\n"
        + whole_table
        + "\n"
        + interpretation
        + "\n"
        + section_table
        + "\n"
        + sections_text
        + "\n"
        + implication
    )
    topic += (
        "\n[숫자 검증](../"
        + HERE.name
        + "/outputs/verification.json) · [자료 정의](../"
        + HERE.name
        + "/SOURCES.md) · [게시 요약](../"
        + HERE.name
        + "/PUBLICATION.md) · [산출물 용량](../"
        + HERE.name
        + "/outputs/artifact_inventory.json)\n"
    )
    (CENTRAL / "24_ERA_RECORD_TRENDS.md").write_text(topic)

    def rec(frame):
        return json.loads(frame.to_json(orient="records", force_ascii=False, double_precision=12))

    web = dict(
        version=summary["version"],
        generated_on="2026-10-07",
        previous_benchmarks_changed=False,
        adopted_correction=False,
        main_window=summary["main_window"],
        windows=summary["windows"],
        difference_definition="recent minus before; negative=faster for seconds; ratios in percentage points",
        reference_population="normal retained race means; exact grade/numeric moisture/month common strata; one race equal weight; eras not year-equal weighted",
        source_runners=151074,
        source_races=13928,
        intervals="pointwise 95% within-year date bootstrap; 200 replicates; >=180 valid; not multiplicity adjusted",
        support_definition=summary["support"],
        warnings=[
            "2026 partial year; main comparison uses Jan-Aug only",
            "raw and matched cohorts differ; not causal composition decomposition",
            "no causal era/breed/management/measurement claim or validated operational correction",
            "null is not zero; retain limited support and overlap shares",
            "ratio is derived from time, not independent ability evidence",
        ],
        estimates=rec(d),
        overlap=rec(pd.read_csv(OUT / "overlap_support.csv")),
        annual_race_means=rec(annual),
        recent_year_matched=rec(pd.read_csv(OUT / "recent_year_matched_changes.csv")),
    )
    (OUT / "web_era_record_trends.json").write_text(
        json.dumps(web, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    )
    print("Rendered era report, figure, publication data and central topic24")


if __name__ == "__main__":
    main()
