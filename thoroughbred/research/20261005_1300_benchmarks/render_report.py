"""Create readable tables, source notes and a publication payload from verified results."""

# ruff: noqa: E501
import json

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from analyze import BANDS, GRADES, HERE, OUT, PARTS
from evaluate_record import evaluate

LABELS = {
    "early": "출발200m",
    "middle1": "200~700m(500m)",
    "middle2": "700~1100m(400m)",
    "late": "마지막200m",
    "finish": "전체1300m",
    "last600": "마지막600m",
    "last400": "마지막400m(부산 직접계측)",
}
SUPPORTED = ["국6", "국5", "국4", "혼4"]


def num(v):
    return "자료 부족" if pd.isna(v) else f"{v:.2f}"


def markdown(frame):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    header = "| " + " | ".join(cell(c) for c in frame.columns) + " |"
    divider = "| " + " | ".join("---" for _ in frame.columns) + " |"
    rows = [
        "| " + " | ".join(cell(c) for c in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join([header, divider, *rows])


def main():
    d = pd.read_parquet(OUT / "population.parquet")
    table = pd.read_csv(OUT / "estimated_benchmarks.csv")
    whole = pd.read_csv(OUT / "whole_time_benchmarks.csv")
    summary = json.loads((OUT / "summary.json").read_text())
    check = json.loads((OUT / "verification.json").read_text())
    # Complete the unsupported cells' metadata without inventing time distributions.
    missing = whole["mean"].isna()
    for column, value in {
        "distance": 1300,
        "part": "finish",
        "observed_n": 0,
        "observed_races": 0,
        "observed_days": 0,
        "reference_n": 0,
        "reference_days": 0,
        "bootstrap_valid_n": 0,
        "grade_reference_status": "unavailable",
        "reference_version": summary["version"],
    }.items():
        whole.loc[missing, column] = value
    whole.to_csv(OUT / "whole_time_benchmarks.csv", index=False)
    coverage = []
    for meet in ["서울", "부산"]:
        for grade in GRADES:
            h = d[d.meet.eq(meet) & d.grade.eq(grade)]
            rr = h[h.year.ge(2024)]
            coverage.append(
                dict(
                    meet=meet,
                    grade=grade,
                    historical_n=len(h),
                    historical_races=h.source_key.nunique(),
                    historical_days=h.date.nunique(),
                    first_date=str(h.date.min().date()) if len(h) else None,
                    last_date=str(h.date.max().date()) if len(h) else None,
                    historical_mean=h.finish.mean(),
                    recent_n=len(rr),
                    recent_days=rr.date.nunique(),
                    recent_races=rr.source_key.nunique(),
                )
            )
    cov = pd.DataFrame(coverage)
    cov.to_csv(OUT / "grade_coverage.csv", index=False)
    historic = []
    from analyze import stats

    for (meet, grade, band), g in d[d.grade.isin(["국3", "혼3"])].groupby(
        ["meet", "grade", "band"]
    ):
        for part in PARTS:
            if g[part].notna().any():
                historic.append(
                    dict(
                        meet=meet,
                        grade=grade,
                        band=band,
                        part=part,
                        n=int(g[part].count()),
                        days=g.date.nunique(),
                        first_date=str(g.date.min().date()),
                        last_date=str(g.date.max().date()),
                        status="historical_only_not_current_benchmark",
                        **stats(g[part]),
                    )
                )
    pd.DataFrame(historic).to_csv(OUT / "historical_only_grade_distributions.csv", index=False)
    dry = table[table.part.eq("finish") & table.band.eq("건조")].copy()
    dry_display = dry[
        [
            "meet",
            "grade",
            "reference_n",
            "reference_days",
            "mean",
            "p20",
            "median",
            "p80",
            "fast20_mean",
            "slow20_mean",
        ]
    ].copy()
    for c in ["mean", "p20", "median", "p80", "fast20_mean", "slow20_mean"]:
        dry_display[c] = dry_display[c].map(num)
    dry_display.columns = [
        "지역",
        "등급",
        "참조 기록",
        "참조 일수",
        "추정 평균",
        "빠른20% 경계",
        "중앙값",
        "느린20% 경계",
        "빠른20% 평균",
        "느린20% 평균",
    ]
    state = (
        table[table.part.eq("finish")]
        .pivot(index=["meet", "grade"], columns="band", values="mean")
        .reindex(columns=BANDS)
        .reset_index()
    )
    for b in BANDS:
        state[b] = state[b].map(num)
    state = state.rename(columns={"meet": "지역", "grade": "등급"})
    sections = (
        table[table.band.eq("건조")]
        .pivot(index=["meet", "grade"], columns="part", values="mean")
        .reindex(columns=["early", "middle1", "middle2", "late", "last600", "last400"])
        .reset_index()
    )
    for c in sections.columns[2:]:
        sections[c] = sections[c].map(num)
    sections = sections.rename(columns={"meet": "지역", "grade": "등급", **LABELS})
    details = [
        "# 서울·부산1300m 등급×주로상태 기준표",
        "단위 초. 최근2024년 이후 같은 등급의 전체 주로 기록을 목표 상태에 맞춘 연구용 추정치다. 관측 평균은 해당 상태에서 실제 관찰한 평균이다. 둘은 참조집단이 다르다. 빠른20% 경계(P20) 이하, 느린20% 경계(P80) 이상으로 읽으며 꼬리 평균과 경계는 다르다. 동률 때문에 집단 비중이 정확히20%가 아닐 수 있다.",
    ]
    for meet in ["서울", "부산"]:
        for band in BANDS:
            z = whole[whole.meet.eq(meet) & whole.band.eq(band)].copy()
            z = z.set_index("grade").reindex(GRADES).reset_index()
            fields = [
                "grade",
                "observed_n",
                "observed_days",
                "historical_n",
                "reference_n",
                "reference_days",
                "observed_mean",
                "mean",
                "p20",
                "median",
                "p80",
                "fast20_mean",
                "slow20_mean",
                "status",
                "grade_reference_status",
            ]
            z = z[fields]
            for c in [
                "observed_mean",
                "mean",
                "p20",
                "median",
                "p80",
                "fast20_mean",
                "slow20_mean",
            ]:
                z[c] = z[c].map(num)
            for c in [
                "observed_n",
                "observed_days",
                "historical_n",
                "reference_n",
                "reference_days",
            ]:
                z[c] = z[c].fillna(0).astype(int)
            z.columns = [
                "등급",
                "관측 수",
                "관측 일수",
                "과거 수",
                "참조 수",
                "참조 일수",
                "관측 평균",
                "추정 평균",
                "P20",
                "중앙",
                "P80",
                "빠른20% 평균",
                "느린20% 평균",
                "상태 표본",
                "등급 참조",
            ]
            details.extend([f"## {meet} {band}", markdown(z), ""])
    details.extend(
        [
            "## 상태와 해석",
            "observed_supported: 최근200기록·20경주·20일 이상. small_recent_sample: 하나라도 미달. no_recent_observation: 최근 해당 상태 미관측. no_recent_grade_reference: 최근 해당 등급의 비교 집단 자체가 없어 시간 추정을 제공하지 않음. 등급 참조supported/small/very_sparse는 주로상태의 표본과 별도로 확인한다.",
            "부산 국4는2024-08-11 한 경주10두의 분포다. 다른 상태를 계산해도 근거가 늘지 않는다. 날짜 재표집200회 중140회만 그 경주가 남아90% 유효 기준에 미달했으므로 평균·분위수 신뢰구간은 비워 두었다. 부산 혼4는86기록·8일, 서울 국4는227기록·18일이다.",
            "각 구간의 전체 분포와 P10/P90·꼬리평균·95% 평균/분위수 재표집 구간은outputs/estimated_benchmarks.csv, 원시 분포는outputs/observed_time_distribution.csv에 있다. 시간순 평가 기준은 최종표와 별개다.",
        ]
    )
    (HERE / "ALL_BENCHMARKS.md").write_text("\n\n".join(details) + "\n")
    metrics = pd.DataFrame(summary["mean_validation"])
    mv = metrics[metrics.method.isin(["benchmark_shift_reference", "cell_raw_fallback"])][
        ["meet", "method", "cells", "cell_mean_mae"]
    ].copy()
    mv.cell_mean_mae = mv.cell_mean_mae.map(lambda x: f"{x:.3f}")
    hm = pd.DataFrame(summary["hidden_cell_validation"])[
        ["meet", "cells", "mean_abs_error", "p90_abs_error", "grade_fallback_mae"]
    ].copy()
    for c in hm.columns[2:]:
        hm[c] = hm[c].map(lambda x: f"{x:.3f}")
    examples = [
        evaluate("서울", "국5", "건조", "finish", 82.0),
        evaluate("서울", "국5", "포화", "finish", 82.0),
    ]
    (OUT / "record_score_examples.json").write_text(
        json.dumps(examples, ensure_ascii=False, indent=2) + "\n"
    )
    ec = pd.DataFrame(examples)[
        [
            "band",
            "time_seconds",
            "same_grade_record_score",
            "all_grade_distance_record_score",
            "same_grade_level",
        ]
    ]
    payload = dict(
        schema_version=1,
        benchmark_version=summary["version"],
        distance_m=1300,
        created_on="2026-10-05",
        data_end=summary["input_end"],
        reference_start="2024-01-01",
        unit="seconds",
        venues=["서울", "부산"],
        bands=BANDS,
        grade_order=GRADES,
        sections=dict(
            labels=LABELS, disjoint_metres=dict(early=200, middle1=500, middle2=400, late=200)
        ),
        scope="Research preparation; operating correction and public website unchanged",
        whole_time_cells=json.loads(whole.to_json(orient="records", force_ascii=False)),
        section_cells=json.loads(table.to_json(orient="records", force_ascii=False)),
        grade_coverage=json.loads(cov.to_json(orient="records", force_ascii=False)),
        warnings=[
            "Seoul last400 unavailable; no invented split",
            "No current benchmark without same-grade reference",
            "Busan national4 is ten runners on one date; provisional only",
            "Location-shift estimates are associations, not causal seconds",
            "Past-only temporal scores differ from retrospective final tables",
        ],
        validation=summary["mean_validation"],
        status_definitions={
            "observed_supported": "recent cell >=200 runners, >=20 races, >=20 days",
            "small_recent_sample": "below one or more recent cell thresholds",
            "no_recent_observation": "same-grade reference exists; recent cell absent",
            "no_recent_grade_reference": "no recent same-grade distribution; time fields null",
        },
        grade_reference_status_definitions={
            "supported": ">=200 records and >=20 days",
            "small": "below supported thresholds",
            "very_sparse": "<30 records or <5 days",
            "unavailable": "no recent same-grade reference",
        },
    )
    (OUT / "web_benchmarks1300.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    text = f"""# 서울·부산1300m 등급·주로상태 기록 기준v1

2026년10월5일. **1300m 자료로 별도 추정한 연구용 기준이다. 최근 국6·국5·국4·혼4의40개 등급×상태 조합에 전체·구간 기준260행을 만들었다. 나머지60조합은 등급 참조 부재로 비워 둔다.** 특히 부산 국4는 한 경주10두의 잠정 분포이며 안정적인 등급 기준으로 사용할 근거가 부족하다. 영천·제주는 제외했고 주로빠르기는 사용하지 않았다.

## 기록을 읽는 방법

평균은 전체 출전 기록의 중심, P20/P80은 빠른20%/느린20% 경계, fast20_mean/slow20_mean은 해당 집단 평균이다. 중앙값은50점 기준이다. 한 말의 한 기록을 평가하는 잣대이며 우승확률·종합능력 점수가 아니다. 국산·혼합 등급을 임의로 합치지 않았다. 전체등급 점수의 최근 참조등급은 국6·국5·국4·혼4이고1200m 전체등급 점수와 등급 구성이 다르다.

## 주로상태별 추정 평균

{markdown(state)}

건조1~5%, 양호6~9%, 다습10~14%, 포화15~19%, 불량20% 이상. 실제 해당 상태의 관측 평균과 공통 참조분포를 맞춘 추정 평균은 다르다. 건조값도 건조 출전마만의 원시 평균이 아니다. 전체100조합의 관측 수·평균·미관측 표시와 상하위 기준은[상세표](ALL_BENCHMARKS.md)에 보존했다.

## 건조 기준의 전체 기록과 상하위

{markdown(dry_display)}

서울 국4는18일, 부산 혼4는8일로 소표본이다. 부산 국4의10두·1일 수치는 등급 기준이 안정적으로 정해졌다는 뜻이 아니다. 국3·혼3의 과거 기록은[과거 전용 분포](outputs/historical_only_grade_distributions.csv)에 보존했으며 최근 기준으로 승격하지 않는다. 1·2등급과OPEN은 이 선택된1300m 자료에 관측이 없다. 근거 없는1200m 환산으로 채우지 않았다.

## 구간 기준

[마사회 계측 설명](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1)의 S1F200m·G3F막판600m·G1F막판200m 정의를 바탕으로, **초반200 + 중간500 + 후반400 + 마지막200 =1300m**로 나눴다. 개별 말의 원API 누적기록 차/구간기록을 사용했고 경주 선두마의 펄롱타임을 개별 말 기록으로 대체하지 않았다.

{markdown(sections)}

중간500m=전체−출발200−막판600. 후반400m=막판600−막판200. 부산 마지막400m는별도 직접계측값으로 후반400m와 위치가 다르다. 서울 마지막400m는 자료가 없어 제공하지 않았다. 막판600·400은 독립 구간과 겹치므로 점수를 합산하지 않는다.

## 자료·제외·추정 방법

2018년부터 서울2026-09-20·부산2026-09-18까지 원천1300m29,189행 → 기존 정상·완전착순·함수율/통과원천 검증 모집단27,909행 → 구간 품질 제외12행 → 최종27,897행(서울17,513·부산10,384). 최근2024년 이후7,881행(서울4,917·부산2,964)을 등급별 참조분포로 썼다. 경주 수는 서울1,630·부산960이다.

기존 모집단은6두 이상, 순위1~출전두수 완전 연결, 정상완주·프로그램번호·함수율·통과원천을 검증한 경주다. 이 선택 때문에 사고·비정상 완주·동착·미완전자료 등과 같은1280행이 분석 밖에 있으며 모든 출전의 무조건 평균이 아니다. 세부 선택 원장은[selection_ledger.csv](outputs/selection_ledger.csv), 추가12행은[excluded_sections.csv](outputs/excluded_sections.csv)에 있다. 추가 품질 범위는 전체65~120초·초반10~25초·중간500m20~55초·후반400m16~45초·마지막200m8~25초다. 결측도 제외했다. 정상 빠른/느린 꼬리를 일정 비율로 잘라내는 분위수 절사는 하지 않았다. 넓은 품질 범위를 최적 컷오프로 검증한 것은 아니다.

원API27,897행의 날짜·경주·말·거리·착순·전체/구간시간을 직접 대조했고 불일치0이다. 부산 마지막400m는남은 모든10,384행에서 품질 조건을 충족했다. DuckDB는read_only로 읽었고 DB·입력Parquet·18개 원API 압축파일 해시를 보존했다. [검증](outputs/verification.json)은{check["numeric_checks"]:,}개 수치 대조와{check["chronological_score_checks"]:,}개 시간순 점수 대조를 포함한다.

지역별 Ridge alpha10, 등급·상태·연월·성별·연령·부담중량·rating 및 엄격한 과거착순/초반위치 이력을 통제했다. year와month를 별도 입력했고 최근5회 착순/위치 이력은 다른 거리도 포함한다. 경주별 총 가중치를 같게 한다. 2021~2023 개발기간에서 등급×상태 추가효과의 완화 강도를0/0.3/1/3 중 선택했고, 최소오차+0.01초 안의 단순 후보를 선택했다. 결과는서울0, 부산0.3이며 부산에서는등급별 주로 차이가 조금 다르다. 1200m 효과를 사용하지 않았다.

전체/막판600은 독립 구간 모형의 합으로 만들어 일관성을 유지했다. 최종 전체기간의 상태 차이를 추정해 같은 등급 최근 모든 상태의 기록에서 자기 상태 차이를 빼고 목표 상태 차이를 더하는 위치 이동 분포다. 각 상태의 분산/꼬리 변화까지 추정한 모형은 아니다. 상태 차이는 관측 연관이며 별도 채택한 서울80%·부산90% 운영후보 보정률의 개정이나 인과 보정값이 아니다.

날짜 단위200회 재표집으로 모형계수와 최근 참조를 함께 다시 추정했다. 전처리 구조는 고정했다. 유효 반복90% 미만인 부산 국4(140/200)는평균·분위수 신뢰구간을 제공하지 않는다. 유효 반복200회라도8일/18일의 작은 참조집단 한계가 사라지지 않는다. 다른 셀의95% 구간은개별 말 기록이 들어갈 범위가 아니다.

## 시간순 검증

각2024·2025·2026 평가연도보다 이전 자료만 학습했고 직전3년을 기준분포로 사용했다. 연도별 비율은[임계값 검증](outputs/temporal_threshold_validation.csv)에 있다. 아래는등급×상태×연도 조합의 실제 평균과 기준 평균의 절대오차를 동일한 조합 가중치로 평균한 값이다.

{markdown(mv)}

서울0.436→0.393초, 부산0.592→0.554초로 원시 상태평균보다 오차가 작았다. 적중률이나 미래 말의 능력예측 개선을 검증한 결과는 아니다. 평가연도 전체에서 빠른20% 경계 안에 든 비율은서울21.48%·부산19.91%, 느린20%는서울21.72%·부산25.07%로 후반 꼬리와 연도 이동은완벽하지 않았다.

관측됐던 조합 전체를 학습에서 숨긴 후 미래 평균을 복원한41조합 검증:

{markdown(hm)}

실제로 과거에도 한 번도 없었던 상태의 정답이나 한 경주뿐인 부산 국4의 안정성을 검증한 것은 아니다. 같은 등급 참조가 없는 등급을 모델 계수만으로 채우지 않는다.

## 한 기록의 평가 예시

{markdown(ec)}

같은82.0초도 건조와 포화에서 상대 위치가 다르다. 같은등급 점수=자신보다 느린 참조 기록 비율×100(동률 절반). 전체등급 점수도 같은 지역1300m의 건조 정렬분포와 비교하는 보조 척도다. 최종표는후향 기준이고 과거 시점 검증에는별도 연도 이전 기준을 썼다.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261005_1300_benchmarks/evaluate_record.py --meet 서울 --grade 국5 --band 건조 --time 82.0
```

## 보존과 게시 준비

[계획](PLAN.md),[출처](SOURCES.md),[게시용 요약](PUBLICATION.md),[전체 기준CSV](outputs/estimated_benchmarks.csv),[100조합 전체시간CSV](outputs/whole_time_benchmarks.csv),[게시JSON](outputs/web_benchmarks1300.json),[중앙 결론](../conclusions/12_BENCHMARK1300.md)에 연결한다. 실제 웹 화면·배포·운영 모델은이번 연구에서 변경하지 않았다. [파일별 산출물 용량](outputs/artifact_inventory.json)은완료 시점의 모든 보관 산출물과 수정 문서의 순증감량을 기록한다.

![1300m 건조 기준](outputs/dry_grade_benchmarks1300.png)
"""
    (HERE / "README.md").write_text(text)
    publication = f"""# 1300m 기록은 어느 정도가 빠른가

서울·부산의1300m를 등급과 함수율 상태별로 따로 비교했다. 최근2024년 이후 기록7,881건을 같은 주로상태로 맞춘 연구용v1 기준이다. 초 단위이며 낮을수록 빠르다.

{markdown(state)}

건조 추정 기준 서울 국6은평균84.24초·빠른20% 경계82.86초·느린20% 경계85.42초, 국5는82.78초·81.70초·83.80초다. 부산 국6은84.38초·82.96초·85.70초, 국5는82.85초·81.70초·83.80초다. 빠른20% 집단의 평균과20% 경계는다른 값이다.

서울 국4는18일, 부산 혼4는8일의 참조로 소표본이며 부산 국4는한 경주10두뿐이라잠정치다. 국3·혼3은최근 참조가 없고1·2등급 및OPEN은자료가 없어 기준을 제공하지 않는다. 비어 있는 주로상태를 추정해도 원관측이 늘지 않는다.

구간은초반200m·중간500m·후반400m·마지막200m를 합쳐1300m로 나눈다. 마지막600m와부산 직접 마지막400m도별도로 제공한다. 구간점수는종합능력이나우승확률이 아니고 중복되는 구간을 더하지 않는다.

상태별 차이는연관관계로 추정했고 확정 초 단위 운영 보정값으로 채택하지 않았다. 시간순 기준평균 오차는서울0.393초·부산0.554초이며 개별말 기록오차나 적중률과다르다. [표본·원자료·방법·검증](README.md),[100조합 상세표](ALL_BENCHMARKS.md),[게시JSON](outputs/web_benchmarks1300.json)을 함께 확인한다. 웹사이트는게시 준비 단계다.
"""
    (HERE / "PUBLICATION.md").write_text(publication)
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    for ax, meet in zip(axes, ["서울", "부산"], strict=True):
        g = dry[dry.meet.eq(meet)].set_index("grade").loc[SUPPORTED]
        y = np.arange(4)
        ax.hlines(y, g.p20, g.p80, color="#246b95", lw=10, alpha=0.25, label="P20~P80")
        ax.scatter(g["mean"], y, color="#246b95", s=55, label="추정 평균", zorder=3)
        ax.scatter(g.fast20_mean, y, color="#29885e", marker="<", s=45, label="빠른20% 평균")
        ax.scatter(g.slow20_mean, y, color="#a65543", marker=">", s=45, label="느린20% 평균")
        labels = [
            x + (" *" if g.loc[x, "grade_reference_status"] != "supported" else "")
            for x in SUPPORTED
        ]
        ax.set_yticks(y, labels)
        ax.invert_yaxis()
        ax.tick_params(axis="y", labelleft=True)
        ax.set_title(f"{meet} · 1300m 건조", fontsize=16)
        ax.set_xlabel("기록(초) · 왼쪽이 빠름")
        ax.set_xlim(77.5, 88)
        ax.grid(axis="x", alpha=0.15)
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, -0.18), ncol=2, frameon=False, fontsize=10)
    fig.suptitle("등급별 1300m 기록 기준 v1", fontsize=20)
    fig.text(
        0.5,
        0.025,
        "* 소표본 · 부산 국4는 한 경주10두의 잠정치 · 최근2024년 이후 참조",
        ha="center",
        fontsize=11,
    )
    fig.subplots_adjust(top=0.83, bottom=0.24, wspace=0.17)
    fig.savefig(OUT / "dry_grade_benchmarks1300.png", dpi=160, facecolor="white")
    plt.close(fig)
    print("1300 reports and publication data written")


if __name__ == "__main__":
    main()
