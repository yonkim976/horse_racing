"""Create readable tables, source notes and a publication payload from verified results."""

# ruff: noqa: E501
import json

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from analyze import BANDS, GRADES, HERE, OUT, PARTS, stats
from evaluate_record import evaluate

LABELS = {
    "early": "출발200m",
    "middle1": "200~1000m(800m)",
    "middle2": "1000~1400m(400m)",
    "late": "마지막200m",
    "finish": "전체1600m",
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
        "distance": 1600,
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
        "# 서울·부산1600m 등급×주로상태 기준표",
        "단위 초. 최근2024년 이후 같은 등급의 전체 주로 기록을 목표 상태에 맞춘 연구용 추정치다. 관측 평균은 해당 상태에서 실제 관찰한 평균이다. 둘은 참조집단이 다르다. 빠른20% 경계(P20) 이하, 느린20% 경계(P80) 이상으로 읽으며 꼬리 평균과 경계는 다르다. 동률 때문에 집단 비중이 정확히20%가 아닐 수 있다.",
        "**서울 추정 기준은 잠정 연구값이다.** 시간순 평균 오차가 원시 기준보다 줄지 않아 관측 평균도 함께 확인해야 한다. 서울 국OPEN과 부산1등급은 극소표본이며, 서울 국OPEN의 평균·분위수 신뢰구간은 제공하지 않는다.",
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
            "서울 국6·국5·혼OPEN은 최근 등급 참조가 없어 시간 추정 자체를 비웠다. 서울 국OPEN20기록·2일과 부산1등급28기록·3일은 극소표본 잠정치다. 서울 국OPEN은 날짜 재표집 유효 반복이90% 미만이므로 평균·분위수 신뢰구간을 제공하지 않는다. 서울 추정 기준의 시간순 평균 오차는 원시 기준보다 작지 않아 잠정 연구값이다.",
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
        evaluate("서울", "국4", "건조", "finish", 103.0),
        evaluate("서울", "국4", "포화", "finish", 103.0),
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
        distance_m=1600,
        created_on="2026-10-06",
        data_end=summary["input_end"],
        reference_start="2024-01-01",
        unit="seconds",
        venues=["서울", "부산"],
        bands=BANDS,
        grade_order=GRADES,
        sections=dict(
            labels=LABELS, disjoint_metres=dict(early=200, middle1=800, middle2=400, late=200)
        ),
        scope="Research preparation; operating correction and public website unchanged",
        whole_time_cells=json.loads(whole.to_json(orient="records", force_ascii=False)),
        section_cells=json.loads(table.to_json(orient="records", force_ascii=False)),
        grade_coverage=json.loads(cov.to_json(orient="records", force_ascii=False)),
        warnings=[
            "Seoul last400 unavailable; no invented split",
            "No current benchmark without same-grade reference",
            "Seoul grades6/5/mixedOPEN have no recent reference; no time estimate",
            "Seoul nationalOPEN20 records on2 days; Busan grade1 only28 records on3 days",
            "Seoul benchmark shift did not improve temporal mean errors; provisional research",
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
    (OUT / "web_benchmarks1600.json").write_text(
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
        effects[effects.part.eq("finish") & effects.grade.eq("국4")]
        .pivot(index="meet", columns="band", values="shift_from_dry")
        .reindex(columns=BANDS)
        .reset_index()
    )
    for band in BANDS:
        common[band] = common[band].map(lambda v: f"{v:+.3f}")
    common = common.rename(columns={"meet": "지역"})
    no_observation = int(table[table.part.eq("finish")].observed_n.eq(0).sum())
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
    dev = pd.read_csv(OUT / "development_validation.csv")
    dev_support = (
        dev.groupby(["meet", "year"])[
            ["n", "original_test_n", "excluded_unseen_grade_n", "train_n", "train_days"]
        ]
        .first()
        .reset_index()
    )
    dev_support.to_csv(OUT / "development_support.csv", index=False)

    historic = []
    old = d[d.meet.eq("서울") & d.grade.eq("국5")]
    for band, g in old.groupby("band"):
        for part in PARTS:
            if g[part].notna().any():
                historic.append(
                    dict(
                        meet="서울",
                        grade="국5",
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
    rawcheck = json.loads((OUT / "raw_source_verification.json").read_text())
    # Keep estimator preference separate from the existence of candidate numeric references.
    web = json.loads((OUT / "web_benchmarks1600.json").read_text())
    web["benchmark_interpretation_by_venue"] = {
        "서울": "provisional research; temporal average error did not improve raw cell baseline",
        "부산": "research reference; temporal average error lower than raw cell baseline",
    }
    web["development_years_by_venue"] = summary["development_years_by_venue"]
    web["development_support"] = json.loads(
        dev_support.to_json(orient="records", force_ascii=False)
    )
    (OUT / "web_benchmarks1600.json").write_text(
        json.dumps(web, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    text = f"""# 서울·부산1600m 등급·주로상태 기록 기준v1

2026-10-06. **서울7개·부산10개 등급의85조합과 전체·구간560행을 만들고, 최근 등급 참조가 없는 서울15조합은 비워 두었다.** 서울의 상태 정렬 기준은 시간순 평균 오차가 원시 기준보다 작지 않아 잠정 연구값이다. 관측 평균을 함께 보존했다. 부산 기준의 오차는 줄었지만 작은 표본·연도 이동을 고려해야 한다. 영천·제주·주로빠르기는 제외했다.

## 주로상태별 추정 평균

단위 초. 최근2024년 이후 같은 등급의 모든 상태 기록을 목표 상태로 맞춘 참조분포의 평균이다. 실제 해당 상태 출전마만의 원시 평균과 다르다. 건조1~5%, 양호6~9%, 다습10~14%, 포화15~19%, 불량20% 이상이다.

{markdown(state)}

[전체100조합 상세표](ALL_BENCHMARKS.md)에는 서울 국6·국5·혼OPEN의15조합을 최근 등급 참조 부재로 표시했다. 서울 국5의74기록은2022~2023년 자료여서[과거 전용 분포](outputs/historical_only_grade_distributions.csv)에 별도 보존했다. 서울 국6·혼OPEN은선택된1600m모집단 자체에 없다. 다른 거리의 값을 빌려 채우지 않았다.

기준이 있는85조합 중 최근 해당 상태 미관측은{no_observation}개, 소표본은{small_cell}개,200기록·20경주·20일을 모두 충족한 관측지원은{strong_cell}개다. 등급 전체 참조와 해당 등급×상태 관측의 표본은 별개다. 부족한 상태를 추정해도 원관측이 늘지 않는다.

## 건조 기준과 기록 분포

{markdown(dry_display)}

P20 이하는 빠른 20%, P80 이상은 느린 20% 경계다. 꼬리 집단의 평균은 경계값과 다르다. 동률의 실제 비중을 보존하므로 집단이 정확히20%가 아닐 수 있다. 중앙값은50점 기준이며 평균과 구분한다. 실제 착순 상위 3두·하위 3두와 전체시간으로 선정한 집단의 구간 평균도 별도로 저장했다.

등급 참조 소표본:

{markdown(sparse)}

서울 국OPEN은20기록·2일, 부산1등급은28기록·3일로 잠정치다. 서울1등급은118기록·12일이고 부산 국3·2·OPEN도 날짜가 적다. 1등급이2등급보다 느리거나 OPEN이 다른 순서로 나타나도 강제로 정렬하지 않는다. 편성·최근 출전마 구성·소표본의 영향을 받는 기록 집단이며 동일 능력 수준의 순위를 확정한 것은 아니다.

## 구간 기준

독립구간은 **초반200m + 중간800m(200~1000m) + 후반400m(1000~1400m) + 마지막200m =1600m**다. 중간800m=전체−출발200−막판600, 후반400m=막판600−막판200이다. 아래는 건조 추정 평균이다.

{markdown(sections)}

지점정의는[마사회계측설명](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1)을따른다. 서울의 개별 누적시간 차와 부산의 개별 구간시간을 사용했고, 선두마의 경주 펄롱시간을 개별 말 기록으로 대체하지 않았다. 부산 직접 마지막400m는1200~1600m로 위 후반400m와 다르다. 서울 직접 마지막400m는 없어 채우지 않는다. 겹치는 구간 점수는 합산하지 않는다. 중간800m는 코너와 직선이 포함된 넓은 구간의 평균이며 내부의 세부 페이스를 확정할 수 없다.

## 자료와 제외 기준

고정스냅샷의2018년이후1600m원천13,158행 → 기존정상·완전착순·함수율/통과원천 검증모집단12,639행 → 구간품질1행 제외 → **12,638행(서울2,617·부산10,021)**이다. 최근2024년이후참조는5,342행(서울1,790·부산3,552)이다. 종료일은서울2026-09-19·부산2026-09-18이다.

{markdown(counts.reset_index())}

기존모집단은6두이상정상완주·순위1~출전두수완전연결·프로그램번호·함수율·통과원천을검증한경주다. 기존선택밖519행과추가1행의원장은[선택원장](outputs/selection_ledger.csv),[제외원장](outputs/excluded_sections.csv)에남겼다. 추가넓은품질범위는전체80~155초·초반10~25초·중간800m32~80초·후반400m16~45초·마지막200m8~25초다. 부산2019-12-06마지막200m31.2초의1행을제외했다. 정상적인 빠른/느린 기록을 일정 비율로 잘라내지 않았고, 위 범위를 최적 제외 기준으로 검증한 것은 아니다.

원API12,638행의날짜·경주·말·거리·착순·전체/구간을직접대조해불일치0이다. 부산직접400m추가품질결측은{rawcheck["invalid_busan400"]}행이다. 원API{len(rawcheck["raw_file_hashes"])}개파일과입력Parquet/DB해시를보존했다. 코어DuckDB는읽기전용이며완료된이전연구·원DB·운영모델을변경하지않았다.

## 추정과 개발기간의 제한

지역별 Ridge alpha10, 등급·상태·year/month·성별·연령·부담중량·rating·엄격한과거착순/초반위치이력을통제했다. 과거이력은다른거리도포함한최근5회이며현재보다이전날짜만쓴다. 주요독립구간의경주별총가중치를같게했다. 0/0.3/1/3중개발조합평균오차의최소값+0.01초안의단순후보를선택했다.

개발연도는부산2021~2023, 서울2022~2023이다. 선택된서울자료에2021년평가행이없어건너뛰었고2022년 학습에 없는 등급36행은 개발 손실 평가에서 제외했다. 아래표는각후보가사용한개발표본이다.

{markdown(dev_support)}

서울2022년학습은136기록·13일,2023년은332기록·32일로작다. 선택강도는{summary["selected_interaction_scale"]}다. 서울은 등급×상태 차이를 더 반영했고 부산은 지역 공통 차이를 사용했다. 서울의 등급별 주로 효과가 확정됐다는 뜻은 아니다. 개발 표본이 작고 서울의 미래 오차가 개선되지 않았으므로 최적 기준으로 승격하지 않는다. 평가연도2024~2026을 보고 다른 후보를 재선택하지 않았다.

최근 동일 등급의 모든 기록에서 자기 상태 효과를 빼고 목표 상태 효과를 더한 분포다. 각 상태의 분산·꼬리 변화까지 추정한 것은 아니다. 전체시간과 막판600m는 독립 구간 모형의 합이다. 아래는국4예시의건조대비전체시간차이(초)이며서울다른등급의값은[효과표](outputs/state_effects.csv)에서각각확인한다.

{markdown(common)}

양수는 느린 방향, 음수는 빠른 방향이다. 단조관계를 강제하지 않았고 기존1200/1300/1400m 계수를 사용하지 않았다. 관측 연관 추정값이며 별도로 채택한 서울80%·부산90% 환산 결정이나 구간보정 보류를 개정하지 않는다.

200회날짜재표집에서전처리구조는고정하고계수와최근참조를함께재추정했다. 유효반복90%미만은평균·분위수신뢰구간을비운다. 서울국OPEN은{int(dry[(dry.meet == "서울") & (dry.grade == "국OPEN")].bootstrap_valid_n.iloc[0])}/200으로미달해구간을제공하지않는다. 부산1등급의유효반복이충족해도3일이라는원참조한계는남는다.95%구간은평균/분위수불확실성이며개별기록범위나인과효과가아니다.

## 시간순 검증

각2024·2025·2026평가연도보다이전자료만학습하고직전3년을참조했다. 기준평균오차는등급×상태×연도각조합의실제평균과기준평균차이를동일조합가중치로평균했다.

{markdown(metrics_display)}

**부산은 원시 기준0.992→추정 기준0.879초, 서울은0.724→0.743초로 서울의 개선은 확인되지 않았다.** 서울 추정값은 조건을 맞춘 잠정 비교 후보로 보존하며 관측 평균을 함께 확인한다. 개발기간에서 선택한 후보를 고정해 이후 연도에서 평가했다.

관측된조합을통째로숨긴19조합복원:

{markdown(hm)}

서울4조합의 복원 오차도 등급 원시 대체보다 작지 않았다. 숨긴 조합의 오차는 실제로 한 번도 없던 상태의 정답이나 극소표본의 안정성을 검증한 결과가 아니다. 빠른/느린20%경계의실제평가연도비중:

{markdown(shares)}

서울 빠른25.08%·느린24.69%처럼 분포의 이동과 폭 변화가 남는다. 개별 말 예측·적중률·수익 개선을 확인한 수치가 아니다. [독립검증](outputs/verification.json)은{check["numeric_checks"]:,}개수치대조와{check["chronological_score_checks"]:,}개시간순점수대조·원천보존을포함한다.

## 한 기록의 평가

{markdown(ec)}

서울 국4의 같은103.0초도 상태별 상대 위치가 달라진다. 같은 등급 점수는 자신보다 느린 비율×100, 동률은 절반이다. 전체등급점수는같은지역1600m의최근참조등급을건조로맞춘분포와비교한다. 서울최근7등급·부산10등급으로참조구성이다르며시간순기준의직전3년구성도연도마다다를수있다. 한기록의수준으로우승확률·종합능력·공식rating이아니다. 최종표는후향기준이고과거점수는해당연도이전참조다.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261006_1600_benchmarks/evaluate_record.py --meet 서울 --grade 국4 --band 건조 --time 103.0
```

## 보존과 게시 준비

[계획](PLAN.md),[출처](SOURCES.md),[100조합상세표](ALL_BENCHMARKS.md),[게시요약](PUBLICATION.md),[기준CSV](outputs/estimated_benchmarks.csv),[게시JSON](outputs/web_benchmarks1600.json),[중앙결론](../conclusions/14_BENCHMARK1600.md),[산출물용량](outputs/artifact_inventory.json)에연결한다. 서울의 잠정 추정·참조 부재·극소표본 표시를 유지한다. 운영 보정·웹 구현·배포는 변경하지 않았다.

![1600m 건조기준](outputs/dry_grade_benchmarks1600.png)
"""
    (HERE / "README.md").write_text(text)
    publication = f"""# 1600m 기록 기준

서울·부산1600m의 등급·주로상태별85조합 기준을 만들었다. 서울7등급·부산10등급이며 서울 국6·국5·혼OPEN은 최근 참조가 없어 시간을 비워 두었다. 최근2024년 이후5,342기록을 각 상태로 맞춘 연구용 추정으로 실제 해당 상태의 관측 평균과 다르다.

{markdown(state)}

**서울 추정 기준은 시간순 평균 오차가 원시 기준보다 줄지 않아 잠정 연구값이다.** 부산은0.992→0.879초로 작아졌지만 서울은0.724→0.743초였다. 한 경주의 우승/적중 예측을 검증한 것은 아니다.

서울 국OPEN20기록·2일, 부산1등급28기록·3일은 극소표본이다. 서울 국OPEN의 평균/분위수 신뢰구간은 제공하지 않는다. 추정 상태를 늘려도 원관측이 늘지 않는다.

{markdown(dry_display)}

독립 구간은 초반200m·중간800m·후반400m·마지막200m다. 마지막600m와 부산 직접 마지막400m는 겹치는 보조지표로 제공하며 서울 마지막400m는 없다. 전체/중복 구간 점수를 합산하지 않는다. 점수는 한 기록의 상대 수준이며 우승확률·종합능력·공식rating이 아니다.

[표본・관측평균・방법・검증](README.md),[100조합상세표](ALL_BENCHMARKS.md),[게시데이터](outputs/web_benchmarks1600.json)를 함께 보존했다. 실제 웹 게시와 운영 모델 적용은 별도 작업이다.
"""
    (HERE / "PUBLICATION.md").write_text(publication)
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    fig, axes = plt.subplots(1, 2, figsize=(14, 8))
    for ax, meet in zip(axes, ["서울", "부산"], strict=True):
        g = dry[dry.meet.eq(meet)].set_index("grade").reindex(GRADES)
        y = np.arange(len(GRADES))
        ax.hlines(y, g.p20, g.p80, color="#246b95", lw=8, alpha=0.25, label="P20~P80")
        ax.scatter(g["mean"], y, color="#246b95", s=45, label="추정평균", zorder=3)
        ax.scatter(g.fast20_mean, y, color="#29885e", marker="<", s=40, label="빠른20%평균")
        ax.scatter(g.slow20_mean, y, color="#a65543", marker=">", s=40, label="느린20%평균")
        labels = [
            x
            + (
                " (없음)"
                if pd.isna(g.loc[x, "mean"])
                else " *"
                if g.loc[x, "grade_reference_status"] != "supported"
                else ""
            )
            for x in GRADES
        ]
        ax.set_yticks(y, labels)
        ax.invert_yaxis()
        ax.set_title(f"{meet} · 1600m 건조" + (" · 잠정" if meet == "서울" else ""), fontsize=16)
        ax.set_xlabel("기록(초) · 왼쪽이 빠름")
        ax.set_xlim(96, 112)
        ax.grid(axis="x", alpha=0.15)
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2, frameon=False, fontsize=10)
    fig.suptitle("등급별1600m 기록기준v1", fontsize=20)
    fig.text(
        0.5,
        0.025,
        "* 소표본 · 서울 국OPEN2일/부산1등급3일 · 서울 추정의 시간순 오차 개선 미확정",
        ha="center",
        fontsize=11,
    )
    fig.subplots_adjust(top=0.87, bottom=0.24, wspace=0.17)
    fig.savefig(OUT / "dry_grade_benchmarks1600.png", dpi=160, facecolor="white")
    plt.close(fig)
    print("1600 reports and publication data written")


if __name__ == "__main__":
    main()
