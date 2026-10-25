"""Publication-ready seasonal tables, uncertainty and figures from verified analysis."""

# ruff: noqa: E501
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SEASONS = ["봄", "여름", "가을"]


def read(name):
    return pd.read_csv(OUT / name, dtype={"grade": str, "label": str})


def markdown(frame):
    def text(v):
        return "—" if pd.isna(v) else str(v).replace("|", "\\|").replace("\n", " ")

    rows = [
        "| " + " | ".join(map(text, frame.columns)) + " |",
        "| " + " | ".join(["---"] * len(frame.columns)) + " |",
    ]
    rows += [
        "| " + " | ".join(map(text, row)) + " |" for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join(rows)


def show(frame, names, numeric=()):
    f = frame[list(names)].copy()
    for key in numeric:
        f[key] = f[key].map(lambda v: "—" if pd.isna(v) else f"{v:+.2f}")
    return f.rename(columns=names)


def uncertainty(row):
    if pd.isna(row.difference):
        return "비교 불가"
    if row.status != "supported":
        return "소표본·잠정"
    if row.bootstrap_valid_n < 180:
        return "재표집 불안정·잠정"
    return "점별 구간 제공"


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    check = json.loads((OUT / "verification.json").read_text())
    assert check["passed"]
    estimates = read("controlled_month_season_contrasts.csv")
    primary = estimates[estimates.kind.eq("season") & estimates.part.eq("finish")]
    summer = primary[primary.label.eq("여름")]
    recent = read("recent_complete_year_contrasts.csv")
    yearly = read("yearly_exact_moisture_contrasts.csv")
    dryyear = yearly[yearly.band.eq("건조") & yearly.season.eq("여름") & yearly.part.eq("finish")]
    rows = []
    for (meet, distance), g in summer.groupby(["meet", "distance_m"]):
        dry = g[g.band.eq("건조")].iloc[0]
        pooled = g[g.band.eq("전체")].iloc[0]
        r = recent[
            recent.meet.eq(meet)
            & recent.distance_m.eq(distance)
            & recent.band.eq("건조")
            & recent.kind.eq("season")
            & recent.label.eq("여름")
            & recent.part.eq("finish")
        ]
        r = (
            r.iloc[0]
            if len(r)
            else pd.Series(
                {"difference": np.nan, "cluster_ci_low": np.nan, "cluster_ci_high": np.nan}
            )
        )
        y = dryyear[dryyear.meet.eq(meet) & dryyear.distance_m.eq(distance)]
        rows.append(
            dict(
                meet=meet,
                distance_m=distance,
                dry_difference=dry.difference,
                dry_ci_low=dry.ci_low,
                dry_ci_high=dry.ci_high,
                dry_status=uncertainty(dry),
                dry_informative_races=dry.informative_races,
                dry_bootstrap_valid_n=dry.bootstrap_valid_n,
                all_states_conditional_difference=pooled.difference,
                all_states_ci_low=pooled.ci_low,
                all_states_ci_high=pooled.ci_high,
                all_states_status=uncertainty(pooled),
                recent_complete_dry_difference=r.difference,
                recent_complete_dry_cluster_ci_low=r.cluster_ci_low,
                recent_complete_dry_cluster_ci_high=r.cluster_ci_high,
                yearly_matched_years=len(y),
                yearly_matched_faster_years=int(y.difference.lt(0).sum()),
            )
        )
    result = pd.DataFrame(rows)
    result.to_csv(OUT / "summer_distance_summary.csv", index=False)
    dry_display = show(
        result,
        dict(
            meet="지역",
            distance_m="거리m",
            dry_difference="여름−겨울",
            dry_ci_low="95% 하한",
            dry_ci_high="95% 상한",
            dry_informative_races="월간비교 경주",
            dry_status="해석",
        ),
        ["dry_difference", "dry_ci_low", "dry_ci_high"],
    )
    states = summer[summer.distance_m.isin([1200, 1400]) & ~summer.band.eq("전체")].copy()
    states["uncertainty_status"] = states.apply(uncertainty, axis=1)
    states_display = show(
        states,
        dict(
            meet="지역",
            distance_m="거리m",
            band="같은 상태",
            difference="여름−겨울",
            ci_low="95% 하한",
            ci_high="95% 상한",
            uncertainty_status="해석",
        ),
        ["difference", "ci_low", "ci_high"],
    )
    sections = estimates[
        estimates.distance_m.eq(1200)
        & estimates.band.eq("건조")
        & estimates.kind.eq("season")
        & estimates.label.eq("여름")
        & ~estimates.part.eq("last600")
    ]
    section_display = show(
        sections,
        dict(
            meet="지역", part="구간", difference="여름−겨울", ci_low="95% 하한", ci_high="95% 상한"
        ),
        ["difference", "ci_low", "ci_high"],
    )
    mix = read("seasonal_state_mix.csv")
    recentmix = mix[mix.period.eq("complete_2024_2025")]
    mixrows = []
    for (meet, season), g in recentmix.groupby(["meet", "season"]):
        mixrows.append(
            dict(
                지역=meet,
                계절=season,
                전체경주=int(g.all_season_races.iloc[0]),
                건조=f"{100 * g.loc[g.band.eq('건조'), 'share'].iloc[0]:.1f}%",
                다습포화불량=f"{100 * g.loc[g.band.isin(['다습', '포화', '불량']), 'share'].sum():.1f}%",
            )
        )
    mix_display = pd.DataFrame(mixrows)
    recentrows = result[
        [
            "meet",
            "distance_m",
            "dry_difference",
            "recent_complete_dry_difference",
            "yearly_matched_years",
            "yearly_matched_faster_years",
        ]
    ]
    recent_display = show(
        recentrows,
        dict(
            meet="지역",
            distance_m="거리m",
            dry_difference="전체기간 건조",
            recent_complete_dry_difference="2024~25 건조",
            yearly_matched_years="단순매칭 연수",
            yearly_matched_faster_years="여름이 빠른 연수",
        ),
        ["dry_difference", "recent_complete_dry_difference"],
    )
    docs = [
        "# 같은 주로상태의 월별·계절별 기록 차이",
        "단위 초. 모든 차이는겨울(12·1·2월을 같은 비중) 대비다. 음수는 빠른 방향이다. 같은 지역·거리·연도·경주등급·함수율 숫자 안의 월별 비교로 추정했으며 경주별 평균기록에 같은 가중치를 줬다. 표본 조건과 재표집 유효성을 함께 읽는다.",
    ]
    for meet in ["서울", "부산"]:
        for band in ["전체", "건조", "양호", "다습", "포화", "불량"]:
            f = primary[primary.meet.eq(meet) & primary.band.eq(band)].copy()
            f["uncertainty_status"] = f.apply(uncertainty, axis=1)
            docs += [
                f"## {meet} {band}",
                markdown(
                    show(
                        f,
                        dict(
                            distance_m="거리m",
                            label="계절",
                            difference="겨울 대비",
                            ci_low="95% 하한",
                            ci_high="95% 상한",
                            target_days="대상 일수",
                            winter_days="겨울 일수",
                            bootstrap_valid_n="유효 재표집",
                            uncertainty_status="해석",
                        ),
                        ["difference", "ci_low", "ci_high"],
                    )
                ),
            ]
    docs += [
        "## 월별·구간·지원",
        "[전체 월별 및 독립 구간CSV](outputs/controlled_month_season_contrasts.csv), [모형 표본지원](outputs/model_support.csv), [원관측 분포](outputs/observed_seasonal_distributions.csv), [최근 완결2년](outputs/recent_complete_year_contrasts.csv). 전체는 각 상태·함수율 차이를 고정효과로 통제한 공통 월효과이고, 개별 상태 행은 해당 상태만 따로 적합한 결과다. 부재 조합은0이나 다른 거리 값으로 채우지 않았다.",
    ]
    (HERE / "ALL_RESULTS.md").write_text("\n\n".join(docs) + "\n")
    methods = """지역·거리마다 경주별 유효 완주마 평균을 먼저 만들고 각 경주에 같은 가중치를 줬다. 같은 연도×등급×함수율 정수값의 고정효과를 제거한 월별 회귀를 적합했다. 등급은 해당 경주의 등급이다. 한 비교층에서 두 달 이상 관측된 경주만 사용해 월별 차이를 구했다. 상태가 같아도1%와5%,20%와그 이상을 같은 조건으로 취급하지 않는다.

연령·부담중량·rating·이전 날짜 최근5회 착순/입상/초반위치·출전수·공백·출전두수와 성별 구성·결측 비중을 함께 통제했다. rating0이하는 기존 기준과 같이 결측으로 처리했다. 평균 대체·표준화 구조는 고정하고, 날짜를 연도 안에서200회 재표집해 비교층의 가중평균과 계수를 매회 다시 계산했다. 대조가 식별 가능한 반복180회 이상일 때만95% 재표집 구간을 제공했다. 해는 가중 고정효과 내 변환과 일반최소제곱의 의사역행렬로 계산했다. 같은 날 여러 경주를 독립 날씨 표본처럼 세지 않았다.

표본 조건 충족은 비교100경주 이상·대상/겨울 각10일·각3년 이상·대조 식별 가능이다. 이 조건을 충족해도 재표집에서 식별이 자주 끊기면 잠정이다.95% 구간은 각 비교의 점별 구간이며 많은 월·거리·상태·구간을 동시에 탐색한 유의성 보장은 아니다."""
    readme = f"""# 같은 함수율 상태에서도 계절에 따라 기록이 달라지는가

2026-10-07. **같은 연도·등급·함수율 숫자로 비교해도 일부 거리에서 여름·가을의 기록이 겨울보다 빠른 방향이 남았다.** 건조1200m는 서울·부산 모두 여름이 빠르다. 모든 거리·상태에 공통 계수를 적용할 근거는 부족하다. 포화·불량 및 드문 장거리는 계절별 같은 조건의 비교가 부족하다.

기존11거리의 최종 품질 모집단 **{summary["input_n"]:,}출전기록·{summary["race_n"]:,}경주**를 사용했다. 실전1000·1200·1300·1400·1600·1700·1800·1900·2000·2200·2300m이며 서울/부산의 실제 존재 거리만 분석했다. 영천·제주·주행심사·주로빠르기는 제외했다. 원자료는2018년부터 서울2026-09-20·부산2026-09-18까지다.2026년은 완결된 연간 주기가 아니다.

## 건조 상태의 여름과 겨울

단위 초. **여름−겨울**, 음수는 여름이 빠른 방향이다. 같은 연도·등급·건조 상태의 실제 함수율 숫자까지 맞춘 뒤 출전마 구성 통제를 추가했다. 월별 비교층에 포함된 경주 수이며 원자료 전체 경주 수와 다르다.

{markdown(dry_display)}

서울1000/1600 및2000m 이상은 겨울3개월과 여름3개월을 같은 비중으로 비교할 월별 지원이 연결되지 않거나 없다. 서울1700/1800m 건조도 유효 재표집180회에 미달해 잠정이다. 단순 관측계절 평균이 존재한다고 통제된 월별 대조까지 식별되는 것은 아니다. 값을0으로 해석하지 않는다.

## 같은 상태를 따로 비교한1200·1400m

{markdown(states_display)}

1200m 서울 양호·다습과 부산 양호에서도 여름이 빠른 방향이지만, 포화·불량까지 같은 결론을 확장할 수 없다. 서울1200m 포화의 비교에는 큰 불확실성이 남는다. 상태별 차이는 서로 다른 조건의 경주를 별도로 적합한 결과이며 상태×계절의 인과적 상호작용을 검증한 것은 아니다.

## 여름의 젖은 주로 비중

완결된2024·2025년의 관측경주 비율이며 거리·등급 구성을 맞춘 비율은 아니다. 여기서 젖은 상태 합은 다습·포화·불량이다.

{markdown(mix_display)}

서울은 이 자료에서 여름이 겨울보다 건조 경주 비중이 높았고, 부산은 여름의 다습·포화·불량 합이 겨울보다 높았다. 여름이면 항상 젖은 주로가 더 많다고 전제하지 않았다. 기록 차이 회귀는 같은 함수율 숫자 안의 변동만 사용했다.

## 구간과 기간 안정성

1200m 건조의 독립구간200+400+400+200m 차이:

{markdown(section_display)}

개별 구간 점추정의 합이 전체 차이와 같다. 각 구간의 신뢰구간을 더해서 전체 신뢰구간을 만들지는 않는다. 막판600은 겹치는 보조 구간이다. 서울 직접 막판400은 생성하지 않았다.

{markdown(recent_display)}

최근2024~2025는 완결된 두 해만 다시 맞춘 민감도 분석이다. 단순 매칭 연수는 같은 연도·등급·함수율 숫자의 여름/겨울 관측 평균 차이가 있는 연수이며 회귀와 다르다. 날짜 비중·비교층이 다르고 출전마 구성 통제를 추가하지 않은 연도별 차이다. 매년 같은 방향은 아니며 기간을 바꾸면 크기도 달라진다. 최근 분석은 가을·겨울 관측이 덜 완성된2026년을 제외했다.

## 방법·해석

{methods}

같은 상태 안의 계절적 연관이다. 실제 기온·습도·풍속·일조·주로 관리·모래 교체·경주 편성·당일 능력을 모두 측정한 인과효과는 아니다. 과거 능력 이력과 당일 공개정보를 포함한 후향 설명이며 사전 예측 검증은 아니다. 기존 거리별 표에는 이미 월과 연도 통제가 들어 있어 이번 차이를 그대로 더하면 중복 보정이 될 수 있다. **새 계절 보정치나 기존 기준표 개정은 채택하지 않았다.**

전체 모집단의 원관측 평균은 마필 기록 평균이고, 계절 회귀는 경주평균에 동일 가중치를 줬으므로 기존 기준표의 산술평균과 집계 대상이 다르다. 정상적인 빠른/느린 기록을 새로 일정 비율 잘라내지 않고 완료된 거리별 품질 기준을 계승했다.

## 검증과 산출물

[독립검증](outputs/verification.json)은원천수치{check["individual_source_numeric_checks"]:,}개, 결과표수치{check["table_numeric_checks"]:,}개, 별도고정효과더미회귀{check["explicit_dummy_ols_checks"]}개대조를통과했다. [입력해시와모형정의](outputs/summary.json), [원천과방법](SOURCES.md), [계획](PLAN.md)을보존했다. 이전완료연구와DB·운영모형·웹배포는수정하지않았다.

[전체상태·계절표](ALL_RESULTS.md), [여름거리요약CSV](outputs/summer_distance_summary.csv), [월별·구간전체CSV](outputs/controlled_month_season_contrasts.csv), [게시요약](PUBLICATION.md), [게시JSON](outputs/web_seasonal_same_moisture.json), [중앙결론](../conclusions/22_SEASONAL_SAME_MOISTURE.md), [전체산출물용량](outputs/artifact_inventory.json)

![월별 건조 기록차이](outputs/monthly_dry_contrasts.png)
"""
    (HERE / "README.md").write_text(readme)
    public = f"""# 같은 주로에서도 남는 계절별 기록 차이

같은 연도·등급·함수율 숫자로 비교해도 일부 거리에서 여름이 겨울보다 빠른 방향이 남았다. 건조1200m는 서울·부산 모두 그 방향이며1400m도 같은 방향이다. 모든 상태·거리에 공통 보정으로 적용하지 않는다.

{markdown(states_display[states_display["거리m"].eq(1200)])}

차이는 여름−겨울(초)이며 음수는 여름이 빠르다는 뜻이다. 경주별 평균을 비교하고 출전마 구성을 함께 통제했다. 포화·불량과 드문 장거리는 표본이 부족하거나 비교를 식별할 수 없다. 근거가 없는 값은0으로 채우지 않는다. 최근 기간과 연도에 따라 크기가 달라지며 기온의 인과효과나 우승 예측 개선을 확인한 것은 아니다.

기존 거리 기준에는 이미 월·연도 통제가 있어 이 차이를 그대로 가산하지 않는다. 새 계절 보정이나 기준표 개정은 채택하지 않았다. [상세분포·방법·검증](README.md), [전체표](ALL_RESULTS.md), [게시데이터](outputs/web_seasonal_same_moisture.json).
"""
    (HERE / "PUBLICATION.md").write_text(public)
    payload = dict(
        version=summary["version"],
        created_on="2026-10-07",
        data_end=summary["input_end"],
        unit="seconds",
        reference=summary["reference"],
        seasons=summary["seasons"],
        difference_definition="target season/month minus equally weighted winter Dec/Jan/Feb; negative means faster",
        estimates=json.loads(estimates.to_json(orient="records", force_ascii=False)),
        distance_summer_summary=json.loads(result.to_json(orient="records", force_ascii=False)),
        state_mix=json.loads(mix.to_json(orient="records", force_ascii=False)),
        uncertainty="pointwise date-cluster bootstrap; withheld if <180/200 identifiable replicates",
        status_definitions=dict(
            supported="observational support threshold only; check bootstrap separately",
            limited_support="observational thresholds not reached; provisional",
            not_identifiable="contrast not identified; null, not zero",
            no_within_stratum_month_overlap="no same-year/grade/exact-moisture month comparison; null",
        ),
        adopted_correction=False,
        previous_benchmarks_changed=False,
        warnings=[
            "Conditional association, not causal temperature or win prediction",
            "Existing benchmark models already contain month and year; do not add this effect directly",
            "2026 is not a complete annual cycle; recent sensitivity uses complete 2024/2025",
            "Sparse states/distances and unstable bootstrap remain provisional",
            "Race-weighted seasonal means differ from runner-weighted benchmark averages",
        ],
    )
    (OUT / "web_seasonal_same_moisture.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharex=True)
    for ax, (meet, distance) in zip(
        axes.flat, [("서울", 1200), ("부산", 1200), ("서울", 1400), ("부산", 1400)], strict=True
    ):
        f = estimates[
            estimates.meet.eq(meet)
            & estimates.distance_m.eq(distance)
            & estimates.band.eq("건조")
            & estimates.kind.eq("month")
            & estimates.part.eq("finish")
        ].copy()
        f["month"] = f.label.astype(int)
        f = f.sort_values("month")
        valid = f.ci_low.notna() & f.status.eq("supported")
        ax.plot(f.month, f.difference, color="#246b95", lw=1.5, marker="o", markersize=4)
        ax.fill_between(
            f.month,
            np.where(valid, f.ci_low, np.nan),
            np.where(valid, f.ci_high, np.nan),
            color="#246b95",
            alpha=0.18,
        )
        ax.axhline(0, color="gray", lw=0.8, ls="--")
        ax.set_title(f"{meet} {distance}m · 같은 건조 함수율", fontsize=15)
        ax.set_xticks(range(1, 13))
        ax.set_ylabel("겨울 대비 기록차이(초)")
        ax.grid(alpha=0.12)
    axes[1, 0].set_xlabel("월")
    axes[1, 1].set_xlabel("월")
    fig.suptitle("같은 연도·등급·함수율 숫자에서 남는 월별 기록차이", fontsize=19)
    fig.text(
        0.5,
        0.025,
        "음수는 빠른 방향 · 음영은 점별95% 날짜 재표집 구간 · 출전마 구성 통제\n재표집 지원이 부족한 달은 음영 생략",
        ha="center",
        fontsize=11,
    )
    fig.tight_layout(rect=[0, 0.06, 1, 0.94])
    fig.savefig(OUT / "monthly_dry_contrasts.png", dpi=160, facecolor="white")
    plt.close(fig)
    topic = f"""# 같은 함수율에서도 남는 월별·계절별 기록 경향

2026-10-07. 기존11거리151,074출전기록·13,928경주에서같은지역·거리·연도·등급·함수율숫자를맞추고출전마구성을통제했다. 경주별평균에동일가중치를줬으며주로빠르기·영천·제주·주행심사는제외했다.

{markdown(states_display[states_display["거리m"].eq(1200)])}

음수는여름이겨울보다빠른방향이다. 겨울12·1·2월과여름6·7·8월은월별같은비중이다. 건조1200m는서울·부산모두계절차이가남고양호도빠른방향이다. 서울다습과포화의결론은다르며포화·불량으로공통효과를확장하지않는다.

{markdown(dry_display)}

최종표본의참조와같은조건의월간비교표본을구분한다. 희소장거리는통제된계절대조를못만드는경우가많다. 재표집유효180회미만은95%구간을비우고잠정으로표시한다. 기존모형의월·연도통제와중복될수있어새계절보정을가산하지않았다. 기간을바꾸면크기가달라지고기온의인과효과·우승예측개선을검증한것은아니다.

[원연구](../{HERE.name}/README.md), [전체표](../{HERE.name}/ALL_RESULTS.md), [게시요약](../{HERE.name}/PUBLICATION.md), [검증](../{HERE.name}/outputs/verification.json), [산출물용량](../{HERE.name}/outputs/artifact_inventory.json)
"""
    (HERE.parent / "conclusions/22_SEASONAL_SAME_MOISTURE.md").write_text(topic)
    print("Seasonal reports, publication payload, figure and central conclusion written")


if __name__ == "__main__":
    main()
