"""Render the monthly study and website-ready material from verified tables."""

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
PART_LABELS = {
    "early": "초반200m",
    "middle1": "중간1(거리−800m)",
    "middle2": "중간2 400m",
    "late": "마지막200m",
    "finish": "전체시간",
    "last600": "마지막600m(중복)",
}


def number(value, decimals=2):
    return "—" if pd.isna(value) else f"{value:+.{decimals}f}"


def table(headers, rows):
    return (
        "| "
        + " | ".join(headers)
        + " |\n|"
        + "|".join(["---"] * len(headers))
        + "|\n"
        + "".join("| " + " | ".join(str(x) for x in row) + " |\n" for row in rows)
    )


def records(data):
    return json.loads(data.to_json(orient="records", force_ascii=False, double_precision=12))


def main():
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["passed"]
    summary = json.loads((OUT / "summary.json").read_text())
    d = pd.read_csv(OUT / "monthly_levels.csv", dtype={"label": str})
    pairs = pd.read_csv(OUT / "paired_month_differences.csv")
    stability = pd.read_csv(OUT / "monthly_year_stability.csv")
    recent = pd.read_csv(OUT / "recent_monthly_levels.csv")
    dry = d.loc[d.band.eq("건조") & d.part.eq("finish")]
    focal = dry.loc[dry.distance_m.eq(1200)].pivot(
        index="month", columns="meet", values="difference"
    )
    monthly_table = table(
        ["월", "서울1200m", "부산1200m"],
        [
            [f"{m}월", number(focal.loc[m, "서울"]), number(focal.loc[m, "부산"])]
            for m in range(1, 13)
        ],
    )
    examples = pairs.loc[
        pairs.band.eq("건조")
        & pairs.part.eq("finish")
        & (
            (
                pairs.meet.eq("서울")
                & pairs.distance_m.eq(1200)
                & pairs.target_month.eq(10)
                & pairs.reference_month.eq(8)
            )
            | (
                pairs.meet.eq("부산")
                & pairs.distance_m.eq(1200)
                & pairs.target_month.eq(8)
                & pairs.reference_month.eq(7)
            )
            | (
                pairs.meet.eq("부산")
                & pairs.distance_m.eq(1400)
                & pairs.target_month.eq(10)
                & pairs.reference_month.eq(8)
            )
            | (
                pairs.meet.eq("서울")
                & pairs.distance_m.eq(1200)
                & pairs.target_month.eq(6)
                & pairs.reference_month.eq(5)
            )
        )
    ]
    pair_table = table(
        ["지역·거리", "비교(앞−뒤)", "차이(초)", "점별95% 구간"],
        [
            [
                f"{r.meet}{r.distance_m}m",
                f"{r.target_month}월−{r.reference_month}월",
                number(r.difference, 3),
                f"{number(r.ci_low, 3)} ~ {number(r.ci_high, 3)}",
            ]
            for r in examples.itertuples()
        ],
    )
    stat = (
        d.loc[d.part.eq("finish")]
        .groupby("band", observed=True)
        .agg(
            rows=("difference", "size"),
            identified=("difference", "count"),
            supported=("interpretation_support", "sum"),
        )
    )
    coverage = table(
        ["함수율 상태", "전체 지역·거리·월", "식별 가능", "관측지원+재표집구간 충족"],
        [
            [
                b,
                int(stat.loc[b, "rows"]),
                int(stat.loc[b, "identified"]),
                int(stat.loc[b, "supported"]),
            ]
            for b in ["전체", "건조", "양호", "다습", "포화", "불량"]
        ],
    )
    annual_focal = stability.loc[
        stability.band.eq("건조")
        & stability.distance_m.isin([1200, 1400])
        & stability.month.isin([6, 8, 10])
    ]
    annual_table = table(
        ["지역·거리", "월", "요건 충족 연도", "겨울보다 빠른 연도", "연도 목록"],
        [
            [
                f"{r.meet}{r.distance_m}m",
                r.month,
                r.eligible_years,
                r.faster_years,
                "—" if pd.isna(r.year_list) else r.year_list,
            ]
            for r in annual_focal.itertuples()
        ],
    )
    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 10}
    )
    fig, axes = plt.subplots(3, 2, figsize=(12, 10), sharex=True)
    for row, distance in enumerate([1200, 1300, 1400]):
        for col, meet in enumerate(["서울", "부산"]):
            ax = axes[row, col]
            v = dry.loc[dry.meet.eq(meet) & dry.distance_m.eq(distance)].sort_values("month")
            ax.axhline(0, color="#888888", lw=0.8)
            ax.plot(v.month, v.difference, color="#176b9e", lw=1.6)
            supported = v.interpretation_support.to_numpy()
            low = np.where(supported, v.ci_low, np.nan)
            high = np.where(supported, v.ci_high, np.nan)
            ax.fill_between(v.month, low, high, color="#59a5d8", alpha=0.22)
            ax.scatter(
                v.loc[supported, "month"], v.loc[supported, "difference"], s=24, color="#176b9e"
            )
            ax.scatter(
                v.loc[~supported, "month"],
                v.loc[~supported, "difference"],
                s=34,
                facecolors="white",
                edgecolors="#176b9e",
            )
            ax.set_title(f"{meet} {distance}m · 건조(1~5%)")
            ax.set_ylabel("겨울 월평균 대비 차이(초)")
            ax.set_xticks(range(1, 13))
            ax.grid(axis="y", alpha=0.15)
    fig.suptitle("같은 등급·연도·함수율 숫자를 통제한 월별 기록 차이", fontsize=16)
    fig.text(
        0.5,
        0.015,
        "음수=빠른 방향 · 겨울=(12월+1월+2월)/3 · 음영=점별95% 날짜 재표집 구간\n빈 점=관측지원 또는 재표집 지원 미충족 · 월별 순위·인과효과·채택된 보정값 아님",
        ha="center",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.96))
    fig.savefig(OUT / "monthly_dry_profiles.png", dpi=160)
    plt.close(fig)
    intro = """월별로 세분화하면 계절 평균에 가려진 지역·거리 차이가 보인다. 건조1200m의 서울은6~11월, 특히8~11월이 겨울보다 빠른 방향이고 부산은6~8월에 더 빠른 점추정치가 모인다. 그러나 서울의10월과8월, 부산의8월과7월 차이는95% 구간이0을 포함한다. ‘가장 빠른 한 달’의 확정 순위로 쓰기 어렵다.

이전 계절 연구가 이미 계산한 월별 회귀와 날짜 재표집 결과를 그대로 사용했다. 이번에 새로 계산한 것은 같은 재표집 회차끼리 뺀 월간 차이,2018~2025년 각 연도의 정확 함수율·등급 매칭 점검이다. 기존 회귀를 새로 학습하거나 기존 거리별 기준표를 바꾸지 않았다.
"""
    method = """- 서울·부산 실전11거리,19개 지역×거리,151,074출전기록을13,928개 경주평균으로 집계한 동일 모집단이다. 자료는2018-01부터 서울2026-09-20·부산2026-09-18까지이며2026년10~12월 관측은 없다. 영천·제주·주행심사는 제외했고 주로빠르기는 사용하지 않았다.
- 건조1~5%, 양호6~9%, 다습10~14%, 포화15~19%, 불량20% 이상을 나눈다. 같은 상태 안에서도 정확한 함수율 숫자, 연도, 경주등급을 맞춘 고정효과 회귀다. ‘전체’ 역시 서로 다른 함수율을 무조건 섞은 평균이 아니라 정확 함수율을 통제한 결과다.
- 한 경주평균에 같은 가중치를 주며 출전마의 나이·부담중량·rating·과거 성적·초반·출전횟수·공백·성별구성·두수와 결측비율을 통제한 원 모형을 재사용했다. rating0이하는 결측이다. 기존 품질 필터를 유지하고 새 상하위 절사는 하지 않았다.
- 표의 차이는 **해당 월 − (12월·1월·2월 월효과의 동일가중 평균)**이다. 음수는 더 빠른 방향이다.1월 기준도 아니고 겨울 전체 경주를 단순 평균한 값도 아니다. 월별 숫자를 실제 말의 원기록이나 확정 주로 보정으로 읽지 않는다.
- 원 연구의 날짜 군집 재표집200회를 사용한다. 월간 차이는 같은 회차에서 두 월을 뺀 뒤2.5/97.5분위수를 구했다. 각 월의 구간 끝을 빼지 않았다. 식별 가능한 회차가180개 미만이면 구간을 제공하지 않는다.
- 관측지원은 원 모형의 유효100경주 이상, 해당 월과 겨울 각10일·3년 이상, 대비 식별 가능 조건이다. 관측지원과 재표집 지원은 별개다. `interpretation_support`는 둘 다 충족한 셀이고 효과 유의성·예측 성능 보증이 아니다. 모든95% 구간은 다중비교를 조정하지 않은 점별 탐색 결과다.
- 연도별 점검은2018~2025년의3~11월만, 같은 지역·거리·연도·등급·정확 함수율에서 해당 월과 겨울 경주평균을 매칭했다. 조화가중치 n월×n겨울/(n월+n겨울)를 사용한다. 연도별 최소2매칭층·양쪽3경주·2일을 충족한 경우만 방향을 센다. 출전마 구성은 추가 통제하지 않고 겨울 기준도 관측 경주를 합친 평균이므로 주 회귀의 수치와 동일하지 않다. 연도 반복성의 보조 점검이며 확정 효과 검정이 아니다.
- 최근2024~2025년 완결2년 회귀는 원 결과를 그대로 보존했다. 별도 재표집이 없어 `ci_low/high`가 비어 있고 `cluster_ci_low/high`는 원 연구의 날짜 집단 구간이다.2년만으로3년 지원 요건을 충족했다고 표시하지 않는다.2026년 부분 연도는 연도 반복성 점검에서 제외한다.
- 초반200m+중간1(거리−800m)+중간2 400m+마지막200m=전체시간이다. 마지막600m는 중간2+마지막200m와 겹친다. 이번 표는 공통6항목이며 서울의 미계측 마지막400m를 생성하지 않았다. 부산 직접계측400m는 원 연구에 보존돼 있으나 이번 공통 월간 표에는 포함하지 않았다.
"""
    findings = """월별 차이의 크기도 거리별로 다르다. 부산 건조1400m는8월 −1.35초,10월 −0.60초로10월−8월 차이가+0.76초(점별95%:+0.39~+1.20)다. 탐색적 비교에서 차이가 남지만 이를 모든 부산 거리에 공통 적용할 수 없다. 서울 건조1400m의10·12월은 관측지원 제한을 함께 표시했다.

연도별 직접 매칭에서는 서울1200m 8월이 요건을 충족한3년 중3년 빠른 방향,10월은 요건 충족 연도가1년뿐이었다. 따라서 전체 회귀에서10월 점추정치가 가장 빠르다는 사실만으로 ‘매년10월이 최상’이라고 판단할 수 없다. 부산1200m 8월은4년 중3년 빠른 방향이었다. 이 보조 점검은 출전마 구성 통제와 겨울 참조가 주 회귀와 다르다.

구간도 일률적이지 않다. 서울 건조1200m 6월은 전체 −0.443초 중 초반200m −0.102초, 중간1 400m −0.292초, 중간2 400m −0.090초, 마지막200m +0.041초다. 마지막 구간의 점별95% 구간은0을 포함한다. 전체가 빨라진 만큼 마지막200m도 같은 비율로 빨라졌다고 환산하지 않는다.

건조의 관측·재표집 지원을 모두 충족한 전체시간 셀은228개 중99개다. 서울1700/1800m는 월별 점추정치가 있어도 날짜 재표집이 불안정하고, 서울1600m 및 여러 희소 거리에는 식별 불가 셀이 있다. 포화3개·불량0개만 이 요건을 충족하므로 비가 많은 달과 고함수율 상태를 일반화하지 않는다. 자료가 없는 값은0초로 채우지 않는다.
"""
    interpretation = """월별 기록을 해석할 때는 지역·거리·등급·함수율을 먼저 맞추고 월별 흐름을 참고한다. 예를 들어 서울 건조1200m의8월 기록이 겨울보다0.5초 빠르다면, 그 차이 일부가 월별 환경과 동반된 변화일 가능성을 검토할 수 있다. 특정 말의 능력이 정확히0.5초 개선됐다고 단정하거나 이번 월효과를 그대로 되돌려 더하지 않는다.

월말에서 다음 달로 넘어가자마자 보정치를 크게 바꾸는 방식은 피해야 한다. 후속 보정 후보는 월 경계를 연결하는 완만한 곡선과 소표본 수축으로 설계하되, 과거 자료만으로 추정한 계수의 시간순 검증이 필요하다. 이번에는 그런 곡선·보정률을 채택하지 않았다. 기존 거리별 기준 회귀는 이미 월·연도를 통제하므로 이번 월효과를 추가로 더하면 중복 보정될 수 있다. 기온·바람·관리·편성 등의 원인을 분리한 인과효과와 우승확률·수익 개선은 검증하지 않았다.
"""
    readme = (
        "# 같은 함수율 조건의 월별 기록 특성\n\n2026-10-07 · 연구용 v1 · 월별 세분화 후속 연구\n\n"
        + intro
    )
    readme += (
        "\n## 1200m 월별 기준 차이\n\n건조(함수율1~5%)·전체시간, 단위 초. 음수는 겨울 월평균보다 빠른 방향이다. 서울12월은 관측지원 제한이고 아래 표 자체에는 불확실성 구간을 생략했다. 세부 구간과 표본은 CSV에 있다.\n\n"
        + monthly_table
    )
    readme += (
        "\n![건조1200·1300·1400m의 월별 흐름](outputs/monthly_dry_profiles.png)\n\n## 한 달의 우열은 별도로 확인\n\n"
        + pair_table
        + "\n"
        + findings
    )
    readme += "\n## 연도별 반복성의 보조 점검\n\n" + annual_table
    readme += (
        "\n## 상태별 지원 범위\n\n아래는 전체시간의19지역·거리×12개월 셀이다. 식별과 충분한 표본·불확실성 지원을 구분했다.\n\n"
        + coverage
    )
    readme += "\n## 방법과 범위\n\n" + method + "\n## 어떻게 사용할 것인가\n\n" + interpretation
    readme += """\n## 보존 산출물

- [거리별 월표와 최근2년·구간 예시](ALL_RESULTS.md), [원천·방법 출처](SOURCES.md), [계산 정의와 입력 해시](outputs/summary.json)
- [모든 월·상태·공통구간8208행](outputs/monthly_levels.csv), [같은 재표집의 월간 차이8892행](outputs/paired_month_differences.csv), [최근 완결2년 월값](outputs/recent_monthly_levels.csv)
- [연도별 월 매칭](outputs/yearly_monthly_matches.csv), [그 매칭층](outputs/yearly_matched_strata.csv), [연도별 방향 요약](outputs/monthly_year_stability.csv)
- [독립 숫자 검증](outputs/verification.json), [게시 정합성 검증](outputs/final_verification.json), [게시 요약](PUBLICATION.md), [게시JSON](outputs/web_monthly_same_moisture.json)
- [중앙 결론](../conclusions/23_MONTHLY_SAME_MOISTURE.md), [전체 보관 파일·정확한 용량](outputs/artifact_inventory.json)

기존 연구와 원 모집단·재표집 파일은 복사하지 않고 읽기 전용 참조했다. 새 회귀·새 날씨 수집·운영 적용·웹 배포는 수행하지 않았다.
"""
    (HERE / "README.md").write_text(readme)
    full = "# 월별 세부 결과\n\n2026-10-07. 주 보고서의 정의를 따른다. 아래는 건조 전체시간, 겨울=(12·1·2월)/3 대비 초다. `*`는 관측 또는 재표집 지원 제한, `—`는 식별 불가다. 다른 상태와 모든 구간의 원값·구간·표본은 [월별CSV](outputs/monthly_levels.csv)에 보존했다.\n\n"
    for meet in ["서울", "부산"]:
        v = dry.loc[dry.meet.eq(meet)]
        distances = sorted(v.distance_m.unique())
        rows = []
        for month in range(1, 13):
            cells = []
            for distance in distances:
                r = v.loc[v.distance_m.eq(distance) & v.month.eq(month)].iloc[0]
                cells.append(
                    number(r.difference)
                    + ("*" if pd.notna(r.difference) and not r.interpretation_support else "")
                )
            rows.append([f"{month}월"] + cells)
        full += (
            f"## {meet} 건조 전체시간\n\n"
            + table(["월"] + [f"{x}m" for x in distances], rows)
            + "\n"
        )
    r = recent.loc[
        recent.band.eq("건조")
        & recent.part.eq("finish")
        & recent.distance_m.isin([1200, 1300, 1400])
        & recent.month.isin([6, 8, 10])
    ]
    full += (
        "## 최근 완결2024~2025년 감도 점검\n\n2년 원 회귀의 차이이며 새 재표집은 없다. 아래95%는 원 연구의 날짜 집단 구간이다. 전체기간의 재표집 구간과 같은 방법으로 표시하지 않는다. 모두3년 관측지원 요건 미달이다.\n\n"
        + table(
            ["지역·거리", "월", "겨울 대비 초", "날짜 집단95% 구간"],
            [
                [
                    f"{x.meet}{x.distance_m}m",
                    x.month,
                    number(x.difference, 3),
                    f"{number(x.cluster_ci_low, 3)} ~ {number(x.cluster_ci_high, 3)}",
                ]
                for x in r.itertuples()
            ],
        )
    )
    sections = d.loc[
        d.band.eq("건조")
        & d.distance_m.eq(1200)
        & d.month.isin([6, 8, 10])
        & d.part.isin(["early", "middle1", "middle2", "late"])
    ]
    full += (
        "\n## 1200m 건조의 독립구간 예시\n\n같은 달의4구간을 더하면 전체시간 차이다. 중간1은1200−800=400m이며 마지막600m를 또 더하지 않는다.95%는 원 날짜 재표집의 점별 구간이다.\n\n"
        + table(
            ["지역", "월", "구간", "차이(초)", "점별95% 구간"],
            [
                [
                    x.meet,
                    x.month,
                    PART_LABELS[x.part],
                    number(x.difference, 3),
                    f"{number(x.ci_low, 3)} ~ {number(x.ci_high, 3)}",
                ]
                for x in sections.itertuples()
            ],
        )
    )
    (HERE / "ALL_RESULTS.md").write_text(full)
    publication = (
        "# 같은 주로여도 달마다 기록 흐름이 다를까\n\n2026-10-07 · 연구 후보 · 기존 보정·운영 반영 없음\n\n"
        + intro
    )
    publication += (
        "\n건조1200m의 겨울 월평균 대비 전체시간 차이(초, 음수=빠른 방향):\n\n" + monthly_table
    )
    publication += (
        "\n서울12월은 관측지원 제한이다. 월별 점추정치와 확정 보정값을 구분해야 한다.\n\n"
        + pair_table
        + "\n"
        + interpretation
    )
    publication += "\n151,074출전기록·13,928경주·11거리를 분석한 앞선 연구의 월별 모형을 활용했다. 같은 연도·등급·정확 함수율 및 출전마 구성을 통제했고200회 날짜 재표집의 짝을 유지해 월간 차이를 계산했다. 월별 표본이 작아지는 포화·불량·희소 거리에서는 충분한 비교가 어렵다.2026년은9월까지만 있으며 연도 반복성 점검은2018~2025년만 사용했다. 점별95% 구간은 다중비교를 조정하지 않은 탐색 결과다.\n\n[전체 보고서](README.md) · [세부표](ALL_RESULTS.md) · [자료와 정의](SOURCES.md) · [게시JSON](outputs/web_monthly_same_moisture.json)\n"
    (HERE / "PUBLICATION.md").write_text(publication)
    (HERE / "PLAN.md").write_text(
        "# 월별 세분화 연구 범위\n\n2026-10-07. 사용자 요청은 계절을 월 단위로 더 세분화하는 것이다. 이전 계절 연구의 검증된 월별 회귀·날짜 재표집을 읽기 전용 재사용하고, 월간 차이는 같은 회차끼리 빼서 계산한다. 연도 반복성은 완결2018~2025년 정확 등급·함수율 매칭으로 별도 점검한다. 주로빠르기는 제외하고 원 모집단·기준표·기존 보정 결정을 유지한다. 결과와 한계·검증·중앙 결론·게시 자료·모든 산출물 용량을 보존한다.\n"
    )
    (HERE / "SOURCES.md").write_text("""# 원천과 계산 출처

2026-10-07. 외부 날씨 자료나 새로운 데이터베이스 조회 없이 기존 검증 자료를 재사용한 연구다.

- [직전 계절 연구](../20261007_seasonal_same_moisture/README.md)와 [그 원천·방법](../20261007_seasonal_same_moisture/SOURCES.md)이11거리 모집단·수치 회귀·날짜 재표집의 근거다. [원 숫자 독립 검증](../20261007_seasonal_same_moisture/outputs/verification.json)은151,074행의 입력 대조와 별도 고정효과 더미 회귀 검증을 포함한다.
- 입력6파일의 SHA-256은 [요약](outputs/summary.json)에 보존했다. 전체기간8208개 월별 행과 최근 완결2년 월별 행은 원 CSV와 직접 동일성을 검증했다. 원 회귀와 재표집을 이번에 다시 추정하지 않았다.
- 새 월간 차이는 원 `date_bootstrap_contrasts.parquet`에서 같은 지역·거리·상태·구간·재표집 회차의 두 월효과를 뺀 값이다. 유효180회 이상에서 점별95% 구간을 제공한다. 월별 겨울 참조가 두 값의 차에서 상쇄된다.
- 새 연도 점검은 원 `race_means.parquet`에서2018~2025년3~11월과 겨울을 같은 등급·함수율 숫자로 매칭한 경주평균이다. 겨울은 관측 경주를 합친 평균이고 출전마 구성은 추가 통제하지 않는다. 따라서 주 회귀와 참조·통제가 다르며 보조 점검으로만 읽는다. 독립 DuckDB 집계로 모든 매칭층·가중평균·경주 수를 대조했다.
- [이번 검증 결과](outputs/verification.json), [중앙 결론·게시 정합성](outputs/final_verification.json), [전체 산출물 명세](outputs/artifact_inventory.json)를 보존한다.

앞선 원천 문서에 보존한 공식 통계 문서와 구현 정의를 따른다. 이번 연구에서 외부 논문의 새로운 주장이나 실제 기온의 인과효과를 추가하지 않는다. 여러 월·거리·상태를 살핀 점별 탐색 결과이며 월별 최적 순위·확정 보정률·예측 성능을 입증하지 않는다.
""")
    topic = (
        "# 23. 같은 함수율의 월별 기록 특성\n\n2026-10-07. [원 연구](../"
        + HERE.name
        + "/README.md) · [세부표](../"
        + HERE.name
        + "/ALL_RESULTS.md)\n\n"
        + intro
    )
    topic += (
        "\n건조1200m 겨울 월평균 대비 차이(초):\n\n"
        + monthly_table
        + "\n서울12월은 관측지원 제한이다.\n\n"
        + pair_table
        + "\n"
        + findings
        + "\n"
        + interpretation
    )
    topic += (
        "\n기존 거리 기준·함수율 보정은 변경하지 않았다. [계산·원천](../"
        + HERE.name
        + "/SOURCES.md), [숫자 검증](../"
        + HERE.name
        + "/outputs/verification.json), [게시 요약](../"
        + HERE.name
        + "/PUBLICATION.md), [용량 명세](../"
        + HERE.name
        + "/outputs/artifact_inventory.json)에 근거와 지원 범위를 보존했다.\n"
    )
    (CENTRAL / "23_MONTHLY_SAME_MOISTURE.md").write_text(topic)
    fields = [
        "meet",
        "distance_m",
        "band",
        "month",
        "part",
        "difference",
        "ci_low",
        "ci_high",
        "status",
        "informative_races",
        "target_races",
        "target_days",
        "target_years",
        "winter_races",
        "winter_days",
        "winter_years",
        "bootstrap_valid_n",
        "interpretation_support",
    ]
    web = dict(
        version=summary["version"],
        generated_on="2026-10-07",
        adopted_correction=False,
        previous_benchmarks_changed=False,
        source_study=summary["source_study"],
        new_ols_fit=False,
        records=summary["runner_records"],
        races=summary["races"],
        date_end={"서울": "2026-09-20", "부산": "2026-09-18"},
        unit="seconds; negative means faster",
        reference="month minus equal mean of Dec/Jan/Feb coefficients",
        support_definition="identifiable; >=100 informative races; month and winter each >=10 dates and >=3 years; bootstrap >=180/200",
        interval_definition="pointwise 95% date-cluster bootstrap percentile; paired differences within same replicate; no multiplicity adjustment",
        annual_matching_reference="pooled winter race means, not equal month effects; no runner-composition controls; 2018-2025 complete years; March-November only",
        uncertainty_warning="limited support and non-identifiable cells must be displayed; null is not zero; no validated causal weather or prediction effect",
        recent_warning="2024-2025 source fit uses separate cluster_ci fields, no bootstrap intervals and <3-year support",
        estimates=records(d[fields]),
        paired_month_differences=records(pairs),
        annual_direction_sensitivity=records(stability),
        recent_estimates=records(
            recent[
                [x for x in fields if x in recent.columns] + ["cluster_ci_low", "cluster_ci_high"]
            ]
        ),
    )
    (OUT / "web_monthly_same_moisture.json").write_text(
        json.dumps(web, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    )
    print("Rendered report, monthly figure, central topic 23, publication Markdown and JSON")


if __name__ == "__main__":
    main()
