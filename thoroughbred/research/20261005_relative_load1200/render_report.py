"""Render the normalized-load comparison and its research-only publication summary."""
# ruff: noqa: E501 -- Korean report prose templates

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
LABELS = dict(
    absolute="부담중량kg",
    total_ratio="총중량 대비 비율",
    weight_body="부담중량+마체중",
    weight_body_ratio="부담중량+마체중+비율",
    body_ratio="마체중 대비 비율",
    past_body_ratio="부담중량+과거체중+비율",
)
MAIN = ["absolute", "total_ratio", "weight_body", "weight_body_ratio"]


def md_table(columns, rows):
    return "\n".join(
        ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
        + ["| " + " | ".join(map(str, row)) + " |" for row in rows]
    )


def main():
    m = pd.read_csv(OUT / "prediction_metrics.csv")
    c = pd.read_csv(OUT / "paired_comparisons.csv")
    d = pd.read_parquet(OUT / "weight_population.parquet")
    pooled = m[m.year.eq(0)]
    pc = c[c.year.eq(0)]
    point = []
    rows = []
    for meet in ["서울", "부산"]:
        a = pooled[pooled.meet.eq(meet)].set_index("model")
        base = a.loc["absolute", "mae_seconds"]
        for name in MAIN:
            error = a.loc[name, "mae_seconds"]
            point.append(dict(meet=meet, model=name, mae_seconds=error, delta_seconds=error - base))
            rows.append(
                [
                    meet,
                    LABELS[name],
                    f"{error:.6f}",
                    f"{error - base:+.6f}",
                    f"{100 * (base - error) / base:+.3f}%",
                ]
            )
    main_table = md_table(
        ["지역", "중량 표현", "평균오차초", "기본 대비차이초", "오차감소율"], rows
    )
    annual = []
    for meet in ["서울", "부산"]:
        for year in [2024, 2025, 2026]:
            a = m[m.meet.eq(meet) & m.year.eq(year)].set_index("model")
            r = c[
                c.meet.eq(meet)
                & c.year.eq(year)
                & c.model.eq("total_ratio")
                & c.contrast.eq("vs_absolute")
            ].iloc[0]
            annual.append(
                [
                    meet,
                    year,
                    f"{a.loc['absolute', 'mae_seconds']:.6f}",
                    f"{a.loc['total_ratio', 'mae_seconds']:.6f}",
                    f"{r.delta_seconds:+.6f}",
                    f"[{r.ci_low:+.6f}, {r.ci_high:+.6f}]",
                ]
            )
    annual_table = md_table(
        ["지역", "연도", "부담중량kg 오차초", "비율 대체 오차초", "비율−기본초", "조건부95%구간초"],
        annual,
    )
    inc = []
    for meet in ["서울", "부산"]:
        for name in MAIN:
            r = pc[
                pc.meet.eq(meet) & pc.baseline.eq(name) & pc.contrast.eq("sectional_increment")
            ].iloc[0]
            inc.append(
                [
                    meet,
                    LABELS[name],
                    f"{r.delta_seconds:+.6f}",
                    f"[{r.ci_low:+.6f}, {r.ci_high:+.6f}]",
                ]
            )
    history_table = md_table(
        ["지역", "중량 표현", "구간이력 추가−미추가초", "조건부95%구간초"], inc
    )
    extras = []
    for meet in ["서울", "부산"]:
        for name, baseline, kind, label in [
            ("total_ratio", "absolute", "vs_absolute", "총중량 비율 대체 vs 부담중량kg"),
            ("weight_body", "absolute", "vs_absolute", "마체중 추가 vs 부담중량kg"),
            ("weight_body_ratio", "weight_body", "ratio_beyond_body", "체중 포함 후 비율 추가"),
            ("body_ratio", "total_ratio", "denominator_sensitivity", "마체중 분모 vs 총중량 분모"),
            ("past_body_ratio", "absolute", "vs_absolute", "과거체중+비율 vs 부담중량kg"),
            (
                "past_body_ratio_rs",
                "past_body_ratio",
                "sectional_increment",
                "과거체중 구조에 구간이력 추가",
            ),
        ]:
            r = pc[
                pc.meet.eq(meet)
                & pc.model.eq(name)
                & pc.baseline.eq(baseline)
                & pc.contrast.eq(kind)
            ].iloc[0]
            extras.append(
                [meet, label, f"{r.delta_seconds:+.6f}", f"[{r.ci_low:+.6f}, {r.ci_high:+.6f}]"]
            )
    extra_table = md_table(["지역", "비교", "추가−기본초", "조건부95%구간초"], extras)
    empty_delta = int(d.body_raw.str.contains(r"\(\s*\)", regex=True).sum())
    recent = d[d.year.ge(2024)]
    ranges = []
    for meet, a in recent.groupby("meet"):
        ranges.append(
            [
                meet,
                len(a),
                f"{a.body_kg.min():.0f}~{a.body_kg.max():.0f}",
                f"{a.load_share_pct.min():.2f}~{a.load_share_pct.max():.2f}",
                f"{a.load_share_pct.median():.2f}",
            ]
        )
    range_table = md_table(
        ["지역", "최근 출전", "마체중kg 범위", "부담중량비율% 범위", "비율 중앙값%"], ranges
    )

    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 11}
    )
    fig, ax = plt.subplots(figsize=(9, 4.5), layout="constrained")
    masses = np.linspace(380, 600, 150)
    for load in [50, 55, 60]:
        ax.plot(masses, 100 * load / (masses + load), label=f"부담중량 {load}kg", linewidth=2)
    ax.scatter([450, 550], [100 * 55 / 505, 100 * 55 / 605], color="#126e82", s=50, zorder=4)
    for mass, offset in [(450, (8, 10)), (550, (8, -15))]:
        value = 100 * 55 / (mass + 55)
        ax.annotate(
            f"{mass}kg · {value:.2f}%",
            (mass, value),
            xytext=offset,
            textcoords="offset points",
            fontsize=10,
        )
    ax.set_xlabel("말 체중 (kg)")
    ax.set_ylabel("부담중량 / (마체중+부담중량) ×100 (%)")
    ax.set_title("같은 부담중량도 말의 체중에 따라 비율이 달라짐")
    ax.legend()
    ax.grid(alpha=0.2)
    fig.savefig(OUT / "relative_load_definition.png", dpi=170)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), layout="constrained")
    for ax, contrast, names, title in [
        (
            axes[0],
            "vs_absolute",
            ["total_ratio", "weight_body", "weight_body_ratio", "past_body_ratio"],
            "중량 표현 변경 vs 부담중량kg",
        ),
        (
            axes[1],
            "sectional_increment",
            [x + "_rs" for x in MAIN],
            "같은 중량 표현에 과거 구간이력 추가",
        ),
    ]:
        a = pc[pc.contrast.eq(contrast) & pc.model.isin(names)].copy()
        a["sort"] = a.model.map({name: i for i, name in enumerate(names)})
        a = a.sort_values(["meet", "sort"])
        y = np.arange(len(a))
        ax.hlines(y, a.ci_low * 1000, a.ci_high * 1000, color="#126e82", linewidth=2)
        ax.scatter(a.delta_seconds * 1000, y, color="#126e82", s=40)
        ax.axvline(0, color="#aa4c38", linestyle="--", linewidth=1)
        ax.set_yticks(
            y,
            [f"{r.meet} · {LABELS[r.model.removesuffix('_rs')]}" for r in a.itertuples()],
            fontsize=9,
        )
        ax.invert_yaxis()
        ax.grid(axis="x", alpha=0.2)
        ax.set_title(title)
        ax.set_xlabel("추가 - 기본 평균오차 (밀리초) · 음수는 개선")
    fig.suptitle(
        "2024~2026년 합산 · 날짜 재표집 조건부95%구간\n후향 비교·여러 비교의 보정 전 탐색 결과",
        fontsize=13,
    )
    fig.savefig(OUT / "relative_load_prediction_comparison.png", dpi=170)
    plt.close(fig)

    report = f"""# 서울·부산1200m 총중량 대비 부담중량 연구

2026-10-05 완료. **부담중량kg을 마체중+부담중량 대비 비율로 바꾸면 전체시간 예측 결과가 소폭 달라졌다. 그러나 개선 크기는 서울 약0.0010초·부산 약0.0022초로 작고,마체중 자체를 추가해도 비슷한 결과였다. 마체중을 이미 포함한 뒤 비율을 더하는 독립적인 추가 가치는 확정하지 못했다. 중량을 비율로 바꿔도 과거 구간 상대속도의 추가 개선은 주 분석에서 뚜렷해지지 않았다.**

당일 체중을 사용한 모형은 후향 조건부 비교다. 체중의 과거 공개시각과 기본 피처 전체의 사전 발행 시점은 검증하지 않았다. 운영 모델·보정·DB·웹사이트는 변경하지 않았다. 기존 상대속도 공식은 유지하고 예측 모형의 중량 표현을 바꿔 비교했다.

## 질문과 계산

사용자 질문: 부담중량을 총중량 대비 비율로 계산하면 다른 결과가 나오는가?

`총중량 대비 부담중량% = 100 × 부담중량kg ÷ (마체중kg + 부담중량kg)`

| 마체중 | 부담중량 | 계산상 총중량 | 부담중량 비율 |
|---|---:|---:|---:|
| 450kg | 55kg | 505kg | 10.8911% |
| 550kg | 55kg | 605kg | 9.0909% |

기수체중·규정 장구는 공식 부담중량에 포함되므로 다시 더하지 않는다. 이 계산상 총중량은 공식 부담중량에서 제외하는 장비까지 모두 계측한 실제 총질량이 아니다. 마체중만을 분모로 사용하는 비율도 보조 비교했으며,두 비율은 단조 변환으로 순위와 정보가 같다.

![비율 정의](outputs/relative_load_definition.png)

## 자료와 같은 표본 비교

기존 정상1200m41,623행을 날짜·경주·공식 말ID로 보관API18파일과 대조했다. 부담중량 `wgBudam`과 체중 `wgHr`을 직접 읽었다. `530()` 같은 체중 증감 누락{empty_delta:,}건도 체중 숫자는 존재하므로 포함했다. 체중260~700kg·부담중량35~70kg 밖의 값은 없었고,**41,623행 전부 같은 표본으로12모형을 비교했다.** 임의 시간·체중 분위수 절사는 하지 않았다.

최근2024년 이후13,313행:서울7,897행·743경주·269일,부산5,416행·501경주·256일이다. 종료일은 서울2026-09-20·부산2026-09-18. 영천·제주·주행심사·주로빠르기는 제외했다.

{range_table}

주 비교는 부담중량kg만,총중량 비율로 대체,부담중량+체중,부담중량+체중+비율의4구조다. 각 구조에서 과거 구간 상대속도 블록을 추가/제외했다. 마체중 분모 비율과 과거 마지막 유효 체중을 사용하는2구조도 같은 방식으로 비교해 총12모형이다. 현재 체중 증감·전체기록·구간·착순은 입력하지 않았다. 현재 함수율은 앞선 예측 비교와 동일하게 제외했다. 당일 체중과 중량 비율만 해당 구조에서 입력한다.

등급·월·성별·연도·나이·rating·기존 기록·이력 횟수와 간격 등 기본 전처리를 유지하고 모든 구조에 Ridge alpha10을 적용했다. 추가 연도/지역별 후보를 테스트 결과에 맞춰 선택하지 않았다.2024·2025·2026년마다 이전 연도만 학습했고 전처리·결측 대체도 과거 자료에만 적합했다. 기존 부담중량kg 모형과 기존 구간이력 추가 모형은 이전 상대속도 연구의 출전별 예측13,313행을 오차1e-8초 이내로 재현했다. 따라서 이번 차이는 모집단 교체로 만든 차이가 아니다.

## 결과: 중량 표현을 바꾸면 얼마 달라지는가

아래는 각 연도 이전 자료로 예측한2024~2026년 결과를 합친 **경주 동일 가중 MAE**다. 단위는 초이며 음의 차이는 개선이다. 총중량 비율은 기존 부담중량kg 열을 대체한다. 부담중량+체중은 체중을 추가해 체격 정보와의 차이를 확인한다.

{main_table}

총중량 비율 대체의 합산95%구간은 서울[-0.001786,-0.000272]초·부산[-0.004152,-0.000158]초였다. 소폭 개선 방향이 관찰됐지만 오차 감소는 약0.095%·0.192%이고 연도 이동에 따라 달랐다. 부산2026년에는 오히려 약0.0020초 악화됐다.

{annual_table}

날짜2,000회 짝 재표집 구간은 적합된 모형을 고정한 **조건부 구간**이다. 학습 재적합·모형 선택·마체중 공개시점·개체의 날짜 간 의존성까지 모두 반영하지 않는다. 여러 구조·연도·지역을 비교한 탐색 결과이며 다중비교 보정은 하지 않았다. 작은 음의 구간만으로 확정적인 운영 개선을 선언하지 않는다. 이전에 분석한 기간의 후향 시간순 비교이며 신규 미관측 미래 테스트도 아니다.

## 체중 정보 때문인가,비율 자체 때문인가

{extra_table}

체중만 추가한 경우도 서울 약0.000858초·부산 약0.002159초 개선돼 비율 대체와 비슷했다. 체중을 이미 넣은 후 총중량 비율을 추가하는 효과는 서울-0.000330초·부산-0.000556초였고 두 지역 모두95%구간에0을 포함했다. **체중이 같은 부담중량의 의미를 구분하는 데 소량의 정보를 주지만,현재 회귀에서 비율의 고유한 추가 이점은 확정할 수 없다.**

마체중 분모와 총중량 분모의 평균오차 차이는0.00003초 미만이다. 서로 다른 물리 법칙을 확인한 차이가 아니라 동일 정보의 비선형 변환을 선형 회귀에 넣은 차이다. 과거 마지막 유효 정상1200m 체중으로 대체하면 기본 대비 개선을 확인하지 못했다. 당일 체중을 현재 측정 없이 정확히 알고 있다고 가정할 수 없다.

## 중량 정규화 이후 구간 상대속도는 도움이 되는가

구간 블록은 목표 날짜보다 앞선 정상1200m 최대3회의 출발200m·중간400m씩·마지막200m·마지막600m·지역별4C/400m 평균과 이력 수다. 이력 날짜는 현재보다 엄격히 이전이다. 현재 구간이나 최종par 후보를 입력하지 않는다.

{history_table}

서울은 주4구조 모두 구간이력 추가 후 점 추정이 악화됐고,부산은 소폭 개선 방향이지만 해당 개선 구간은 모두0을 포함했다. 서울 부담중량+체중+비율 구조는 미보정 합산 구간이0보다 아주 조금 높아 악화 방향이었다. **총중량 비율로 바꿔도 앞선 구간이력 추가 가치의 결론을 뒤집는 근거는 얻지 못했다.**

보조 과거체중 구조의 부산 구간이력 추가는-0.002707초,95%구간[-0.005334,-0.000035]초로 아주 작은 개선 방향이었다. 여러 비교의 미보정 구간이고 주 분석의 총중량 비율 효과와 다른 비교라 별도 탐색 관찰로 보존한다. 이 일부 값을 골라 구간 상대속도의 일반적인 개선으로 표현하지 않는다. 우승·착순·수익을 예측한 시험은 아니다.

![모형별 비교](outputs/relative_load_prediction_comparison.png)

## 비율이 높으면 기록이 느려지는가

단순 비율 대체 모형의 조건부 회귀계수는 비율1%p당 서울 약+0.073~+0.078초·부산+0.124~+0.165초였다. 해당 회귀 구조 안에서는 비율이 높을 때 느린 기록 방향의 상관이 있었다. 다만 부담중량의 배정·말의 체격·능력·컨디션·숨은 전개가 함께 섞이고,체중을 동시에 넣으면 계수 해석이 바뀐다. **1%p마다 이만큼 초를 보정하라는 수치가 아니다.**1kg 효과·말별 최적체중·물리적 에너지 손실을 식별하지 않았다.

등급별·비율5분위 관측 기록과 막판 비율은 [관측 분포](outputs/observed_load_quintiles.csv),전체 조건부 계수는 [회귀계수](outputs/conditional_coefficients.csv)에 보존한다. 관측 집단의 평균을 인과효과나 운영 보정으로 가산하지 않는다.

## 보존과 다음 적용

당일 마체중을 확인할 수 있는 시점의 연구용 비교 변수로 총중량 대비 부담중량 비율을 보존한다. 부담중량kg·마체중kg을 함께 보관해 필요 시 직접 비교한다. 이번12모형 가운데 운영 후보를 새로 승격하지 않았다. 전체시간 함수율 보정 서울80%·부산90% 및 구간 보정 보류는 유지한다.

- [계획](PLAN.md),[원천·계산 정의·시점](SOURCES.md),[분석](analyze.py),[독립 검증](verify.py),[검증 결과](outputs/verification.json),[해시·설정](outputs/summary.json).
- [모형별 오차](outputs/prediction_metrics.csv),[날짜 짝 비교](outputs/paired_comparisons.csv),[중량 모집단](outputs/weight_population.parquet),[출전별 예측](outputs/prediction_rows.parquet).
- [웹 게시용 요약](PUBLICATION.md),[작은 요약JSON](outputs/web_relative_load_summary.json),[중앙 결론](../conclusions/11_RELATIVE_LOAD1200.md),[작업 용량](outputs/artifact_inventory.json).

다음 검증에는 공식 당일 체중의 발행 시점 확인,체중 정보의 모델 구조별 반복성,별도의 착순 예측 검사가 필요하다. 현재 결과만으로 중량 비율을 기록 환산계수로 적용하지 않는다.
"""
    (HERE / "README.md").write_text(report, encoding="utf-8")
    publication = """# 같은55kg도 말의 체중에 따라 다르게 보기

2026-10-05 연구 요약. 서울·부산1200m,자료 종료일 서울2026-09-20·부산2026-09-18.

말 체중과 부담중량을 합한 값에서 부담중량이 차지하는 비율을 계산했다.450kg인 말에55kg을 부담시키면10.89%,550kg인 말에서는9.09%다. 같은 부담중량의 상대적인 크기를 읽는 보조 변수다.

실제41,623개 정상 출전에서2024~2026년13,313개 출전을 시간순 평가했다. 부담중량kg 대신 비율을 사용한 전체시간 예측의 합산 평균오차는 서울1.064284→1.063277초,부산1.148008→1.145806초였다. 소폭 개선 방향이지만 약0.0010초·0.0022초의 작은 변화이며,부산2026년에는 악화됐다.

부담중량에 마체중을 직접 추가해도 비슷한 결과였다. 체중을 이미 넣고 비율을 더하는 독립 효과는 명확하지 않았다. 중량을 정규화해도 과거 구간 상대속도의 추가 예측 가치가 주 분석에서 뚜렷해지지는 않았다.

비율은 체격과 부담중량을 함께 설명하는 연구 지표다. 높은 비율을 그만큼의 초 손실·우승확률 감소로 바꾸거나 말별 최적체중을 정할 수는 없다. 현재 체중은 결과API로 읽었고 과거 공개시각을 입증하지 못했으므로 후향 조건부 비교로 표시한다. 운영 모델과 기록 보정은 변경하지 않았다.

![같은 부담중량의 비율](outputs/relative_load_definition.png)

[전체 연구와 연도별 비교](README.md),[공식 정의·원자료](SOURCES.md),[검증](outputs/verification.json).
"""
    (HERE / "PUBLICATION.md").write_text(publication, encoding="utf-8")
    payload = dict(
        version="relative-load1200-research-20261005",
        status="retrospective_research",
        formula="100 * carried_weight_kg / (body_weight_kg + carried_weight_kg)",
        data_end_by_region={"서울": "2026-09-20", "부산": "2026-09-18"},
        source_rows=41623,
        evaluated_rows=13313,
        current_body_publication_time_verified=False,
        operating_model_applied=False,
        causal_correction=False,
        model_selection_performed=False,
        uncertainty="fixed-model date-cluster intervals; no multiplicity adjustment",
        main_pooled_metrics=point,
        selected_contrasts=pc[
            pc.model.isin(MAIN) & pc.contrast.isin(["vs_absolute", "ratio_beyond_body"])
        ][["meet", "model", "baseline", "contrast", "delta_seconds", "ci_low", "ci_high"]].to_dict(
            "records"
        ),
    )
    (OUT / "web_relative_load_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    print("Reports, research summary JSON and two figures rendered")


if __name__ == "__main__":
    main()
