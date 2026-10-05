"""Create readable tables, source notes and a publication payload from verified results."""

# ruff: noqa: E501
import json

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from analyze import BANDS, GRADES, HERE, OUT
from evaluate_record import evaluate

LABELS = {
    "early": "출발200m",
    "middle1": "200~800m(600m)",
    "middle2": "800~1200m(400m)",
    "late": "마지막200m",
    "finish": "전체1400m",
    "last600": "마지막600m",
    "last400": "마지막400m(부산 직접계측)",
}
SUPPORTED = GRADES


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
        "distance": 1400,
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
        "# 서울·부산1400m 등급×주로상태 기준표",
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
            "등급 참조도 따로 확인한다. 서울1등급118기록·11일, 국OPEN97기록·7일, 혼OPEN53기록·4일, 부산1등급124기록·11일, 2등급202기록·18일, 국OPEN49기록·4일, 혼OPEN40기록·3일은 소표본이다. 비어 있는 주로조합을 추정해도 참조 집단이 커지는 것은 아니다.",
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
        evaluate("서울", "국5", "건조", "finish", 90.0),
        evaluate("서울", "국5", "포화", "finish", 90.0),
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
        distance_m=1400,
        created_on="2026-10-05",
        data_end=summary["input_end"],
        reference_start="2024-01-01",
        unit="seconds",
        venues=["서울", "부산"],
        bands=BANDS,
        grade_order=GRADES,
        sections=dict(
            labels=LABELS, disjoint_metres=dict(early=200, middle1=600, middle2=400, late=200)
        ),
        scope="Research preparation; operating correction and public website unchanged",
        whole_time_cells=json.loads(whole.to_json(orient="records", force_ascii=False)),
        section_cells=json.loads(table.to_json(orient="records", force_ascii=False)),
        grade_coverage=json.loads(cov.to_json(orient="records", force_ascii=False)),
        warnings=[
            "Seoul last400 unavailable; no invented split",
            "No current benchmark without same-grade reference",
            "Grade1, OPEN, and Busan grade2 have sparse recent grade references",
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
    (OUT / "web_benchmarks1400.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    counts = d.groupby("meet").agg(
        records=("row_key", "size"), races=("source_key", "nunique"), days=("date", "nunique")
    )
    shares = pd.DataFrame(summary["threshold_validation"])[
        ["meet", "fast20_share", "slow20_share"]
    ].copy()
    for c in ["fast20_share", "slow20_share"]:
        shares[c] = shares[c].map(lambda v: f"{v * 100:.2f}%")
    effects = pd.read_csv(OUT / "state_effects.csv")
    common = (
        effects[effects.part.eq("finish") & effects.grade.eq("국5")]
        .pivot(index="meet", columns="band", values="shift_from_dry")
        .reindex(columns=BANDS)
        .reset_index()
    )
    for band in BANDS:
        common[band] = common[band].map(lambda v: f"{v:+.3f}")
    common = common.rename(columns={"meet": "지역"})
    no_observation = int(whole.observed_n.eq(0).sum())
    small_cell = int(whole.status.eq("small_recent_sample").sum())
    strong_cell = int(whole.status.eq("observed_supported").sum())
    sparse = dry[dry.grade_reference_status.ne("supported")][
        ["meet", "grade", "reference_n", "reference_days", "grade_reference_status"]
    ]
    metrics_display = mv.rename(
        columns={
            "meet": "지역",
            "method": "비교 기준",
            "cells": "평가 조합",
            "cell_mean_mae": "기준평균 오차(초)",
        }
    )
    metrics_display["비교 기준"] = metrics_display["비교 기준"].replace(
        {
            "benchmark_shift_reference": "함수율 정렬 기준",
            "cell_raw_fallback": "원시 상태평균/등급평균 대체",
        }
    )
    text = f"""# 서울·부산1400m 등급·주로상태 기록 기준v1

2026-10-05. **10개 원천등급×5개 주로상태×2개 지역의100조합과 전체·구간650행을 만들었다.** 평균·중앙값·P10/P20/P80/P90, 빠른20%·가운데60%·느린20%의 평균과 인원, 실제 착순 집단과 기록점수를 함께 보존했다. 영천·제주와 주로빠르기는 제외했다. 기존 거리의 초 단위 효과를 입력하지 않고1400m로 다시 학습·검증했다.

## 주로상태별 추정 평균

단위는 초다. 최근2024년 이후 같은 등급의 모든 상태 기록을 목표 상태로 맞춘 공통 참조분포의 평균이다. 실제 해당 상태 출전마만의 원시 평균과 구분한다. 건조1~5%, 양호6~9%, 다습10~14%, 포화15~19%, 불량20% 이상이다.

{markdown(state)}

[100조합 상세표](ALL_BENCHMARKS.md)에 관측 평균·추정 평균·기록 수·날짜 수·상하위 경계를 같이 표시했다. 최근 원관측이 없는 조합은{no_observation}개, 소표본 조합은{small_cell}개다. 최근200기록·20경주·20일을 모두 충족한 조합은{strong_cell}개다. 등급 전체 참조의 표본과 그 등급×상태의 관측 표본은 별도로 확인한다.

## 건조 기준과 기록 분포

{markdown(dry_display)}

P20 이하는 빠른20%, P80 이상은 느린20% 경계다. 꼬리 집단의 평균은 경계값과 다르다. 동률의 실제 비중을 보존하므로 집단 비중이 정확히20%가 아닐 수 있다. 평균과 중앙값도 구분한다.

등급 자체의 최근 참조가 부족한 집단:

{markdown(sparse)}

OPEN은3~7일에 집중되어 안정적인 기준으로 보기 어렵다. 상태 추정5개를 제공해도 참조 날짜가 늘지 않는다. 국산·혼합·OPEN을 임의로 합치거나 등급순으로 기록을 강제 정렬하지 않았다. OPEN을1등급과 동일한 능력집단으로 읽지 않는다.

## 구간 기준

독립 구간은 **초반200m + 중간600m(200~800m) + 후반400m(800~1200m) + 마지막200m =1400m**다. 중간600m=전체−출발200−막판600, 후반400m=막판600−막판200이다. 아래는 건조 추정 평균이다.

{markdown(sections)}

지점 정의는[마사회 계측 설명](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1)에 따른다. 서울 개별 누적시간 차와 부산 개별 구간시간을 사용했고 경주 선두마의 통과/펄롱시간으로 말별 시간을 대체하지 않았다. 부산 직접 마지막400m는1000~1400m로 후반400m와 위치가 다르다. 서울 마지막400m는 없어 제공하지 않는다. 마지막600·400은 독립 구간과 겹치는 보조 지표이며 점수를 합산하지 않는다.

## 자료와 제외 기준

2018년 이후 원천1400m29,678행 → 기존 정상·완전착순·함수율/통과원천 검증 모집단28,262행 → 추가 구간품질 제외4행 → **28,258행**이다. 최근2024년 이후 참조는11,343행(서울6,716·부산4,627)이다. 종료일은 서울2026-09-20·부산2026-09-11이다.

{markdown(counts.reset_index())}

기존 모집단은6두 이상, 정상완주·순위1~출전두수 완전 연결·프로그램번호·함수율·통과원천을 검증한 경주다. 기존 선택 밖1,416행과 추가4행을[선택 원장](outputs/selection_ledger.csv)과[제외 원장](outputs/excluded_sections.csv)에 남겼다. 추가 넓은 품질 범위는 전체70~130초·초반10~25초·중간600m24~65초·후반400m16~45초·마지막200m8~25초이며 결측도 제외했다. 정상 빠른/느린 꼬리를 비율로 절사하지 않았고 위 범위를 최적 컷오프로 검증한 것은 아니다.

원API28,258행의 날짜·경주·말·거리·착순·전체/구간을 직접 대조해 불일치0을 확인했다. 부산2019-11-17의 직접400m14.9초는 넓은 품질 범위 미달로 해당 보조 구간만 제외했으며 나머지 기록은 유지했다. 원API18개 파일과 입력Parquet/DB 해시를 보존했고 코어DuckDB는읽기 전용으로 읽었다.

## 추정과 불확실성

지역별 Ridge alpha10으로 등급·상태·year/month·성별·연령·부담중량·rating·과거착순/초반위치 이력을 통제했다. 과거 이력은 다른 거리도 포함한 최근5회이며 현재 출전보다 이전 날짜만 사용한다. 주요 독립 구간의 경주별 총 가중치를 같게 했다. 2021~2023 개발기간에 등급×상태 완화 강도0/0.3/1/3을 비교하고 최소오차+0.01초 안의 단순 후보를 선택했다. 서울·부산 모두0이 선택되어 각 지역 안에서 등급들이 같은 상태 차이를 공유한다.

최근 동일등급의 기록에서 자기 상태 효과를 빼고 목표 상태 효과를 더했다. 상태별 분산·꼬리 변화까지 추정한 모형은 아니다. 전체시간과 막판600m는 독립 구간 모형의 합으로 일관성을 유지한다. 건조 대비 전체시간 추정 차이(초):

{markdown(common)}

양수는 느린 방향, 음수는 빠른 방향이다. 양호/다습을 건조보다 강제로 빠르게 만들지 않았다. 관측 연관 추정값이며 별도 채택한 서울80%·부산90%의 기록환산 연구나 구간보정 보류를 개정한 값이 아니다.

날짜 단위200회 재표집으로 모형계수와 최근 참조를 함께 재추정했다. 전처리 구조는 고정했다. 참조가 없는 반복은 해당 등급에서 제외하며 유효 반복90% 미만이면 평균·분위수 신뢰구간을 비운다. 이번 최소 유효 반복은{check["min_valid_bootstrap"]}/200이다.95% 구간은 평균·분위수의 불확실성이며 개별 말 기록 범위가 아니다. 재표집으로 OPEN의 적은 원관측 날짜가 충분해지는 것은 아니다.

## 시간순 검증

각2024·2025·2026 평가연도보다 이전 자료만 학습하고 직전3년 참조분포로 평가했다. 아래는 등급×상태×연도 조합의 실제 평균과 기준 평균의 절대오차를 조합별 동일 가중치로 평균한 값이다.

{markdown(metrics_display)}

관측된 조합을 통째로 숨긴 뒤 미래 평균을 복원한69조합의 검증:

{markdown(hm)}

빠른/느린20% 경계의 실제 평가연도 비중:

{markdown(shares)}

원시 평균과 추정 기준은 같은 참조기간을 썼다. 기준 평균 오차는 개별 말의 기록오차·적중률·수익과 다르다. 실제 관측이 없는 주로의 정답이나 OPEN의 안정성을 검증한 것은 아니다. 부산 느린20% 비중26.93%처럼 꼬리와 연도 이동은 남아 있다. [독립 검증](outputs/verification.json)은{check["numeric_checks"]:,}개 수치 대조·{check["chronological_score_checks"]:,}개 시간순 점수 대조와 원천 보존을 포함한다.

## 한 기록의 평가

{markdown(ec)}

같은90.0초도 주로상태에 따라 상대 위치가 달라진다. 같은등급 점수는 자신보다 느린 참조 비율×100이며 동률은 절반이다. 전체등급 점수는 같은 지역1400m의10등급을 건조로 맞춘 분포와 비교한다. 한 기록의 상대 수준이며 우승확률·종합능력·마사회/Timeform rating이 아니다. 다른 거리·지역과 공통 절대척도를 공유하지 않는다. 최종표는 후향 기준이고 시간순 점수는 각 평가연도 이전 참조를 사용했다.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261005_1400_benchmarks/evaluate_record.py --meet 서울 --grade 국5 --band 건조 --time 90.0
```

## 보존과 게시 준비

[계획](PLAN.md),[출처](SOURCES.md),[100조합 상세표](ALL_BENCHMARKS.md),[게시용 요약](PUBLICATION.md),[기준CSV](outputs/estimated_benchmarks.csv),[게시JSON](outputs/web_benchmarks1400.json),[중앙 결론](../conclusions/13_BENCHMARK1400.md),[산출물 용량](outputs/artifact_inventory.json)에 연결한다. 기존 완료 연구·운영 모델·웹 화면·배포는 변경하지 않았다.

![1400m 건조 기준](outputs/dry_grade_benchmarks1400.png)
"""
    (HERE / "README.md").write_text(text)
    publication = f"""# 1400m 기록은 어느 정도가 빠른가

서울·부산1400m의10개 등급×5개 주로상태100조합을 정리했다. 최근2024년 이후11,343기록을 같은 상태로 맞춘 연구용 추정이며 원시 관측 평균과 구분한다. 단위는 초로 낮을수록 빠르다.

{markdown(state)}

건조 기준 평균과 빠른/느린20% 경계, 꼬리 집단 평균:

{markdown(dry_display)}

1등급·OPEN과 부산2등급은 최근 등급 참조가 적다. 특히 OPEN은3~7일이므로 표본과 관측/추정 표시를 함께 확인한다. 추정 주로상태를 늘려도 원관측이 늘지는 않는다.

구간은 초반200m·중간600m·후반400m·마지막200m로 나눈다. 마지막600m와 부산 직접 마지막400m는 보조 지표로 제공한다. 서울 마지막400m는 없어 채우지 않는다. 전체시간과 중복 구간점수를 합산하지 않는다.

한 번의 기록을 읽는 기준이며 확정 운영 보정·우승확률·종합능력 점수가 아니다. [표본·방법·검증](README.md),[100조합 상세표](ALL_BENCHMARKS.md),[게시데이터](outputs/web_benchmarks1400.json)를 함께 보존한다. 실제 웹 게시와 운영 적용은 별도 작업이다.
"""
    (HERE / "PUBLICATION.md").write_text(publication)
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    fig, axes = plt.subplots(1, 2, figsize=(14, 8))
    for ax, meet in zip(axes, ["서울", "부산"], strict=True):
        g = dry[dry.meet.eq(meet)].set_index("grade").loc[GRADES]
        y = np.arange(len(GRADES))
        ax.hlines(y, g.p20, g.p80, color="#246b95", lw=8, alpha=0.25, label="P20~P80")
        ax.scatter(g["mean"], y, color="#246b95", s=45, label="추정평균", zorder=3)
        ax.scatter(g.fast20_mean, y, color="#29885e", marker="<", s=40, label="빠른20%평균")
        ax.scatter(g.slow20_mean, y, color="#a65543", marker=">", s=40, label="느린20%평균")
        labels = [
            x + (" *" if g.loc[x, "grade_reference_status"] != "supported" else "") for x in GRADES
        ]
        ax.set_yticks(y, labels)
        ax.invert_yaxis()
        ax.set_title(f"{meet} · 1400m 건조", fontsize=16)
        ax.set_xlabel("기록(초) · 왼쪽이빠름")
        ax.set_xlim(83, 99)
        ax.grid(axis="x", alpha=0.15)
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2, frameon=False, fontsize=10)
    fig.suptitle("등급별1400m 기록기준v1", fontsize=20)
    fig.text(
        0.5,
        0.025,
        "* 최근등급참조소표본 · OPEN은3~7일 · 최근2024년이후참조",
        ha="center",
        fontsize=11,
    )
    fig.subplots_adjust(top=0.87, bottom=0.18, wspace=0.17)
    fig.savefig(OUT / "dry_grade_benchmarks1400.png", dpi=160, facecolor="white")
    plt.close(fig)
    print("1400 reports and publication data written")


if __name__ == "__main__":
    main()
