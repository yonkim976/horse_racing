"""Render verified distance-specific tables and publication data without refitting models."""

# ruff: noqa: E501
import json
import subprocess
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
GRADES = ["국6", "국5", "국4", "혼4", "국3", "혼3", "2", "1", "국OPEN", "혼OPEN"]
BANDS = ["건조", "양호", "다습", "포화", "불량"]


def markdown(frame):
    def cell(v):
        return str(v).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(map(cell, frame.columns)) + " |",
        "| " + " | ".join(["---"] * len(frame.columns)) + " |",
    ]
    lines += [
        "| " + " | ".join(map(cell, row)) + " |" for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join(lines)


def display(frame, names, time_fields):
    frame = frame[list(names)].copy()
    for name in time_fields:
        frame[name] = frame[name].map(lambda v: "—" if pd.isna(v) else f"{v:.2f}")
    return frame.rename(columns=names)


def render(distance):
    run, out = HERE / str(distance), HERE / str(distance) / "outputs"
    summary = json.loads((out / "summary.json").read_text())
    verification = json.loads((out / "verification.json").read_text())
    source = json.loads((out / "raw_source_verification.json").read_text())
    venues = summary["venues"]
    d = pd.read_parquet(out / "population.parquet")
    table = pd.read_csv(out / "estimated_benchmarks.csv")
    whole = pd.read_csv(out / "whole_time_benchmarks.csv")
    empty = whole["mean"].isna()
    for column, value in dict(
        distance=distance,
        part="finish",
        observed_n=0,
        observed_races=0,
        observed_days=0,
        reference_n=0,
        reference_days=0,
        bootstrap_valid_n=0,
        grade_reference_status="unavailable",
        reference_version=summary["version"],
    ).items():
        whole.loc[empty, column] = value
    whole.to_csv(out / "whole_time_benchmarks.csv", index=False)
    order = pd.MultiIndex.from_product([venues, GRADES], names=["meet", "grade"])
    dry = table[table.band.eq("건조") & table.part.eq("finish")].copy()
    state = (
        table[table.part.eq("finish")]
        .pivot(index=["meet", "grade"], columns="band", values="mean")
        .reindex(order)
        .reindex(columns=BANDS)
        .reset_index()
    )
    state_display = display(
        state, {"meet": "지역", "grade": "등급", **{b: b for b in BANDS}}, BANDS
    )
    dry_display = display(
        dry,
        dict(
            meet="지역",
            grade="등급",
            reference_n="참조 기록",
            reference_days="참조 일수",
            mean="추정 평균",
            p20="빠른20% 경계",
            median="중앙값",
            p80="느린20% 경계",
            fast20_mean="빠른20% 평균",
            slow20_mean="느린20% 평균",
        ),
        ["mean", "p20", "median", "p80", "fast20_mean", "slow20_mean"],
    )
    labels = dict(
        early="출발200m",
        middle1=f"200~{distance - 600}m({distance - 800}m)",
        middle2=f"{distance - 600}~{distance - 200}m(400m)",
        late="마지막200m",
        last600="마지막600m",
        last400="부산 직접 마지막400m",
    )
    sections = (
        table[table.band.eq("건조")]
        .pivot(index=["meet", "grade"], columns="part", values="mean")
        .reindex(columns=list(labels))
        .reset_index()
    )
    section_display = display(sections, {"meet": "지역", "grade": "등급", **labels}, list(labels))
    coverage = []
    historical = []
    from_stats = ["finish", "early", "middle1", "middle2", "late", "last600", "last400"]
    for meet in venues:
        for grade in GRADES:
            h = d[d.meet.eq(meet) & d.grade.eq(grade)]
            r = h[h.year.ge(2024)]
            coverage.append(
                dict(
                    meet=meet,
                    grade=grade,
                    historical_n=len(h),
                    historical_races=h.source_key.nunique(),
                    historical_days=h.date.nunique(),
                    recent_n=len(r),
                    recent_races=r.source_key.nunique(),
                    recent_days=r.date.nunique(),
                    first_date=str(h.date.min().date()) if len(h) else None,
                    last_date=str(h.date.max().date()) if len(h) else None,
                )
            )
            if len(h) and not len(r):
                for band, group in h.groupby("band"):
                    for part in from_stats:
                        v = group[part].dropna()
                        if len(v):
                            historical.append(
                                dict(
                                    meet=meet,
                                    grade=grade,
                                    band=band,
                                    part=part,
                                    n=len(v),
                                    days=group.date.nunique(),
                                    mean=v.mean(),
                                    median=v.median(),
                                    p20=v.quantile(0.2),
                                    p80=v.quantile(0.8),
                                    status="historical_only_not_current_benchmark",
                                )
                            )
    cov = pd.DataFrame(coverage)
    cov.to_csv(out / "grade_coverage.csv", index=False)
    pd.DataFrame(
        historical,
        columns=[
            "meet",
            "grade",
            "band",
            "part",
            "n",
            "days",
            "mean",
            "median",
            "p20",
            "p80",
            "status",
        ],
    ).to_csv(out / "historical_only_grade_distributions.csv", index=False)
    dev = pd.read_csv(out / "development_validation.csv")
    support = (
        dev.groupby(["meet", "year"])[
            ["n", "original_test_n", "excluded_unseen_grade_n", "train_n", "train_days"]
        ]
        .first()
        .reset_index()
    )
    support.to_csv(out / "development_support.csv", index=False)
    skipped = pd.read_csv(out / "temporal_reference_exclusions.csv")
    metrics = pd.DataFrame(summary["mean_validation"])
    metric_rows, interpretations = [], {}
    for meet in venues:
        by_method = metrics[metrics.meet.eq(meet)].set_index("method")
        raw = float(by_method.loc["cell_raw_fallback", "cell_mean_mae"])
        bench = float(by_method.loc["benchmark_shift_reference", "cell_mean_mae"])
        better = bench < raw
        interpretations[meet] = (
            "research reference; lower temporal mean error"
            if better
            else "provisional research; temporal mean error not lower"
        )
        metric_rows.append(
            dict(
                거리=distance,
                지역=meet,
                원시기준오차=f"{raw:.3f}",
                추정기준오차=f"{bench:.3f}",
                검증조합=int(by_method.loc["benchmark_shift_reference", "cells"]),
                판단="평균 오차 감소" if better else "개선 미확인·잠정",
            )
        )
    md_metrics = markdown(pd.DataFrame(metric_rows))
    hidden_display = display(
        pd.DataFrame(summary["hidden_cell_validation"]),
        dict(
            meet="지역",
            cells="숨긴 조합",
            mean_abs_error="복원 오차",
            grade_fallback_mae="원시 등급 대체 오차",
            p90_abs_error="90% 오차",
        ),
        ["mean_abs_error", "grade_fallback_mae", "p90_abs_error"],
    )
    effects = pd.read_csv(out / "state_effects.csv")
    representative = (
        effects[effects.part.eq("finish") & effects.grade.eq("국5")]
        .pivot(index="meet", columns="band", values="shift_from_dry")
        .reindex(columns=BANDS)
        .reset_index()
    )
    effect_display = display(representative, {"meet": "지역", **{b: b for b in BANDS}}, BANDS)
    thin = dry[dry.grade_reference_status.ne("supported")]
    thin_display = display(
        thin,
        dict(
            meet="지역",
            grade="등급",
            reference_n="참조 기록",
            reference_days="참조 일수",
            bootstrap_valid_n="유효 재표집",
            grade_reference_status="등급 참조",
        ),
        [],
    )
    cell_counts = whole.status.value_counts().to_dict()
    cell_note = (
        f"관측지원{cell_counts.get('observed_supported', 0)}개·"
        f"소표본{cell_counts.get('small_recent_sample', 0)}개·"
        f"최근 상태 미관측{cell_counts.get('no_recent_observation', 0)}개·"
        f"등급 참조 부재{cell_counts.get('no_recent_grade_reference', 0)}개"
    )
    end_note = "·".join(f"{m}{date}" for m, date in summary["input_end"].items())
    shares = pd.DataFrame(summary["threshold_validation"])[
        ["meet", "n", "fast20_share", "slow20_share"]
    ]
    for field in ["fast20_share", "slow20_share"]:
        shares[field] = shares[field].map(lambda x: f"{100 * x:.2f}%")
    shares = shares.rename(
        columns={
            "meet": "지역",
            "n": "평가 기록",
            "fast20_share": "빠른20% 경계 이하",
            "slow20_share": "느린20% 경계 이상",
        }
    )
    details = [
        f"# {distance}m 등급·주로상태 전체기록 기준표",
        "단위 초. 추정 기준은 최근 같은 등급의 모든 주로 기록을 목표 상태로 맞춘 분포다. 관측 평균은 실제 그 상태 출전마만의 평균이다. 빠른20% 경계 이하와 느린20% 경계 이상으로 읽고 꼬리 평균과 구분한다. 시간 수준은 우승확률이 아니다.",
    ]
    for meet in venues:
        for band in BANDS:
            t = (
                whole[whole.meet.eq(meet) & whole.band.eq(band)]
                .set_index("grade")
                .reindex(GRADES)
                .reset_index()
            )
            names = dict(
                grade="등급",
                observed_n="관측 기록",
                observed_days="관측 일수",
                historical_n="과거 기록",
                reference_n="참조 기록",
                reference_days="참조 일수",
                observed_mean="관측 평균",
                mean="추정 평균",
                p20="P20",
                median="중앙",
                p80="P80",
                fast20_mean="빠른20% 평균",
                slow20_mean="느린20% 평균",
                status="상태 표본",
                grade_reference_status="등급 참조",
            )
            t = display(
                t,
                names,
                ["observed_mean", "mean", "p20", "median", "p80", "fast20_mean", "slow20_mean"],
            )
            details += [f"## {meet} {band}", markdown(t)]
    details += [
        "## 표본 상태의 뜻",
        "observed_supported는 최근200기록·20경주·20일을 모두 충족한 조합이다. small_recent_sample은 하나라도 미달, no_recent_observation은 해당 상태 미관측, no_recent_grade_reference는 최근 같은 등급의 참조가 없어 시간 추정을 비운 조합이다. 등급 전체 참조의supported/small/very_sparse와 상태별 표본을 구분한다.",
        "등급×상태 조합을 추정해도 원관측 표본이 늘지는 않는다. 전체·구간의P10/P90, 중간60% 평균과 인원,95% 재표집 구간은 [기준CSV](outputs/estimated_benchmarks.csv)에 있다. 재표집 구간은 개별 기록 범위나 인과효과가 아니다.",
    ]
    (run / "ALL_BENCHMARKS.md").write_text("\n\n".join(details) + "\n")
    examples = []
    for meet in venues:
        time = round(float(dry[dry.meet.eq(meet) & dry.grade.eq("국5")]["median"].iloc[0]), 1)
        for band in ["건조", "포화"]:
            process = subprocess.run(
                [
                    sys.executable,
                    str(run / "evaluate_record.py"),
                    "--meet",
                    meet,
                    "--grade",
                    "국5",
                    "--band",
                    band,
                    "--time",
                    str(time),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            examples.append(json.loads(process.stdout))
    (out / "record_score_examples.json").write_text(
        json.dumps(examples, ensure_ascii=False, indent=2) + "\n"
    )
    example_display = display(
        pd.DataFrame(examples),
        dict(
            meet="지역",
            band="상태",
            time_seconds="실제 기록",
            estimated_mean_seconds="추정 평균",
            same_grade_record_score="같은등급 점수",
            all_grade_distance_record_score="전체등급 점수",
        ),
        [
            "time_seconds",
            "estimated_mean_seconds",
            "same_grade_record_score",
            "all_grade_distance_record_score",
        ],
    )
    absent = (
        cov[cov.recent_n.eq(0)][["meet", "grade", "historical_n", "last_date"]]
        .fillna("—")
        .rename(
            columns={
                "meet": "지역",
                "grade": "등급",
                "historical_n": "과거 기록",
                "last_date": "과거 마지막 날짜",
            }
        )
    )
    excluded = pd.read_csv(out / "excluded_sections.csv")
    ledger = pd.read_csv(out / "selection_ledger.csv")
    exclusion_display = excluded[
        ["meet", "date", "grade", "finish", "early", "middle1", "middle2", "late"]
    ].copy()
    exclusion_display["date"] = pd.to_datetime(exclusion_display.date).dt.strftime("%Y-%m-%d")
    if distance == 1700:
        specific = "서울 국6·국5를 포함한 최근5등급을 추정했다. 앞선 출전 여부 점검의 최근 국6는485기록이었고, 이번에 출발200m25.5초의1기록을 넓은 구간 품질 범위로 제외해484기록이 됐다. 경주·날짜 수는 유지했다. 이 제외가 원천 오류의 증명은 아니다. 국OPEN은30기록·3일로 극소표본이다."
        hidden_note = "1700m의 숨긴20조합 복원 오차는 원시 등급 대체보다 줄지 않았다. 시간순 관측 평균의 개선을 미관측 주로의 정확성까지 확장할 수 없다."
        bounds = "전체90~170초·출발200m10~25초·중간900m36~90초·후반400m16~45초·마지막200m8~25초"
        topic = "15_BENCHMARK1700.md"
    else:
        specific = "서울·부산은 최근9등급씩 추정했으며 두 지역 국6는 같은 거리의 참조가 없어 비워 뒀다. 서울 국5의457기록은 모두2024년 이후 선택 자료다.2024년 국5 평가31행은 이전3년 같은 등급 참조가 없어 모든 방법의 검증과 과거 기록점수에서 공통 제외했다. 최종 최근 기준에는457행을 사용한다. 상위등급·OPEN은 참조 날짜가 적다."
        hidden_note = "1800m 숨긴 조합 복원은 두 지역에서 원시 등급 대체보다 오차가 작았지만, 실제 미관측 상태의 정답이나 희소 등급의 안정성을 직접 검증한 것은 아니다."
        bounds = "전체95~185초·출발200m10~25초·중간1000m40~100초·후반400m16~45초·마지막200m8~25초"
        topic = "16_BENCHMARK1800.md"
    readme = f"""# {"·".join(venues)}{distance}m 등급·주로상태 기록 기준v1

2026-10-06. **같은 거리의 최근 등급 참조로{summary["reference_cells"]}개 상태 조합과 전체·구간{summary["benchmark_rows"]}행을 만들었다. 참조가 없는{summary["unsupported_whole_cells"]}조합은 시간을 비워 뒀다.** 영천·제주·주로빠르기는 제외했다. 현재 운영 모델이나 웹사이트 배포를 변경한 작업은 아니다.

{specific}

## 상태별 추정 평균

단위 초. 최근2024년 이후 같은 등급의 모든 상태 기록을 목표 상태로 맞춘 참조분포의 평균이다. 실제 해당 상태만의 관측 평균과 다르다. 함수율 건조1~5%·양호6~9%·다습10~14%·포화15~19%·불량20% 이상으로 구분했다.

{markdown(state_display)}

최근 등급 참조가 없는 조합의 과거 기록:

{markdown(absent)}

상태별 표본은{cell_note}다. 관측지원은200기록·20경주·20일 기준이며, 추정으로 소표본 문제 자체가 해소되지는 않는다. [전체 상세표](ALL_BENCHMARKS.md)에서 관측 평균과 추정 평균을 함께 읽는다. 과거 전용 분포는[별도CSV](outputs/historical_only_grade_distributions.csv)에 보존했다.

## 건조 기준의 분포와 등급 참조

{markdown(dry_display)}

P20 이하는 빠른20%, P80 이상은 느린20% 경계다. 꼬리 평균과 경계는 다르다. 동률을 보존하므로 실제 인원이 정확히20%가 아닐 수 있다. 실제 착순 상위3·하위3와 전체시간으로 선택한 집단의 구간 평균도 별도로 제공했다.1등급·2등급·OPEN의 평균 순서를 억지로 정렬하지 않았다.

{markdown(thin_display)}

등급 참조는200기록·20일 이상을supported로 표시하고,30기록 미만 또는5일 미만은very_sparse로 구분했다.200회 날짜 재표집에서 유효180회 미만이면 평균·분위수 신뢰구간을 비운다. 반복 수를 충족해도 원참조 날짜가 적다는 한계는 남는다.

## 구간 기록

독립 구간은 **출발200m + 중간{distance - 800}m(200~{distance - 600}m) + 후반400m({distance - 600}~{distance - 200}m) + 마지막200m**다. 중간=전체−출발200−막판600, 후반400=막판600−막판200이다. 건조 추정 평균:

{markdown(section_display)}

마지막600m는 겹치는 보조 구간이다. 부산 직접 마지막400m는{distance - 400}~{distance}m로 위 후반400m와 다르며 서울 직접 마지막400m는 없어 채우지 않았다. 전체·중복 구간 점수를 합산하지 않는다. 중간 구간 내부의 세부 페이스·실제 경로 길이를 계측한 결과는 아니다. 선두마의 펄롱시간으로 개별 말 구간을 대체하지 않았다.

## 자료와 제외

원천 감사 거리 선택{len(ledger):,}행 → 기존 정상·완전 착순 모집단{len(d) + len(excluded):,}행 → 넓은 구간 품질 제외{len(excluded)}행 → 최종 **{len(d):,}행**이다. 최근2024년 이후 참조는 **{summary["recent_n"]:,}행**이며 종료일은{end_note}다.

추가 품질 범위는{bounds}다. 정상적인 빠른/느린 기록을 일정 비율로 잘라내지 않았으며 최적 제외 기준을 검증한 것은 아니다. 제외 원장:

{markdown(exclusion_display)}

기존 경주의 출전두수와 착순을 보존해 착순 집단을 계산했다. 한 행을 품질 제외했다고 나머지 말의 하위3 정의를 바꾸지 않는다. 개별 원API{source["checked_rows"]:,}행에서 식별·거리·착순·전체·구간 기록을 대조했고 불일치0이다. 부산 직접400m의 추가 품질 결측은{source["invalid_busan400"]}행이다. 원API{len(source["raw_file_hashes"])}개와 입력DB·Parquet 해시를 보존했다.

## 추정 방법과 개발 표본

지역별 Ridge alpha10으로 등급·상태·연도·월·성별·연령·부담중량·rating·엄격한 과거 착순과 초반 위치 이력을 통제했다. 이전 날짜의 최근5회 이력만 쓰며 다른 거리도 포함한다. 독립 구간 모형의 경주별 총 가중치를 같게 했다. 개발2021~2023에서0/0.3/1/3 후보 중 조합 평균 오차 최소값+0.01초 안의 가장 단순한 강도를 선택했다. 선택은{summary["selected_interaction_scale"]}다. 평가기간 결과를 보고 후보를 재선택하지 않았다.

{markdown(support)}

최근 같은 등급 기록에서 자기 상태 효과를 빼고 목표 상태 효과를 더한 분포다. 상태별 분산·꼬리 변화까지 추정한 모형은 아니다. 건조 대비 전체시간 차이의 국5 예시:

{markdown(effect_display)}

양수는 느린 방향, 음수는 빠른 방향이다. 상태를 단조관계로 강제하지 않았다. 각 거리에서 새로 추정했으며1200/1300/1400/1600m의 초 단위 효과를 입력하지 않았다. 기존 전체시간 보정 결정이나 구간보정 채택 보류를 개정한 것은 아니다.

## 시간순 검증

2024·2025·2026 평가연도보다 이전 자료만 학습하고 직전3년 같은 등급을 참조했다. 모든 방법이 동일한 평가 출전기록을 사용한다. 참조 부재로 제외한 평가행은{summary["temporal_excluded_rows"]}개다.

{markdown(skipped)}

검증 대상{summary["score_rows"]:,}행에서 조합별 평균기록 오차를 비교했다. 이는 등급×상태×연도 조합의 실제 평균과 기준 평균 차이를 동일 조합 가중치로 평균한 값이다.

{md_metrics}

개별 말의 전체시간 예측 오차·우승확률·적중률·수익 개선과 구분한다. 숨긴 조합 복원:

{markdown(hidden_display)}

{hidden_note}

이전 참조의 빠른20%·느린20% 경계가 이후 기록에서 차지한 실제 비율:

{markdown(shares)}

분포 이동과 폭 변화가 남아 다음 기간도 정확히20%로 분류한다는 뜻은 아니다. 원시 기준·문맥 모형 비교도[검증 요약](outputs/summary.json)에 보존했다. 날짜 재표집은 전처리 구조를 고정하고 계수와 참조를 함께 재추정했다.95% 구간은 평균·분위수 불확실성이며 인과효과나 개별 기록 범위가 아니다.

[독립 검증](outputs/verification.json)은{verification["numeric_checks"]:,}개 수치 대조와{verification["chronological_score_checks"]:,}개 시간순 점수 대조를 통과했다.

## 한 기록의 상대 수준

같은 국5 기록을 건조·포화에서 비교한 예시:

{markdown(example_display)}

같은등급 점수는 자신보다 느린 비율×100, 동률 절반이다. 전체등급 점수는 같은 지역·거리의 최근 참조 등급 전체를 건조로 맞춘 분포와 비교한다. 지역·거리의 등급 구성과 직전3년 구성이 다를 수 있다. 한 기록의 상대 수준이며 종합능력·공식rating·우승확률이 아니다. 최종표는 후향 참조, 과거 기록점수는 해당 연도 이전 참조다.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261006_1700_1800_benchmarks/{distance}/evaluate_record.py --meet 서울 --grade 국5 --band 건조 --time {examples[0]["time_seconds"]}
```

[공통 계획](../PLAN.md), [원천·방법](../SOURCES.md), [게시 요약](PUBLICATION.md), [게시JSON](outputs/web_benchmarks{distance}.json), [중앙 결론](../../conclusions/{topic}), [전체 작업 용량](../outputs/artifact_inventory.json)

![건조 분포](outputs/dry_grade_benchmarks{distance}.png)
"""
    (run / "README.md").write_text(readme)
    publication = f"""# {"·".join(venues)}{distance}m 기록 기준

최근 같은 등급 참조로{summary["reference_cells"]}개 상태 조합의 평균·중앙값·빠른20%·느린20% 경계와 전체·구간{summary["benchmark_rows"]}행을 만들었다. 참조가 없는{summary["unsupported_whole_cells"]}조합은 시간을 비워 뒀다. 실제 해당 상태의 관측 평균과 조건을 맞춘 추정 기준을 구분한다.

{specific}

{markdown(state_display)}

시간순 검증의 조합별 평균기록 오차:

{md_metrics}

이 개선은 우승 예측이나 적중률 개선을 뜻하지 않는다. {hidden_note}

독립 구간은200·{distance - 800}·400·200m다. 막판600m와 부산 직접 마지막400m는 겹치는 보조지표이며 서울 직접 마지막400m는 없다. 겹치는 점수를 합산하지 않는다. 한 기록의 상대 수준을 평가하며 종합능력·공식rating으로 표현하지 않는다.

[관측 평균·표본·분포·방법·검증](README.md), [전체 상태 상세표](ALL_BENCHMARKS.md), [게시데이터](outputs/web_benchmarks{distance}.json)를 함께 보존했다. 실제 웹 배포·운영 모델 적용은 별도 작업이다.
"""
    (run / "PUBLICATION.md").write_text(publication)
    payload = dict(
        benchmark_version=summary["version"],
        distance_m=distance,
        created_on="2026-10-06",
        data_end=summary["input_end"],
        reference_start="2024-01-01",
        unit="seconds",
        venues=venues,
        bands=BANDS,
        grade_order=GRADES,
        sections=dict(labels=labels, disjoint_metres=summary["disjoint_section_metres"]),
        whole_time_cells=json.loads(whole.to_json(orient="records", force_ascii=False)),
        section_cells=json.loads(table.to_json(orient="records", force_ascii=False)),
        grade_coverage=json.loads(cov.to_json(orient="records", force_ascii=False)),
        benchmark_interpretation_by_venue=interpretations,
        validation=summary["mean_validation"],
        development_years_by_venue=summary["development_years_by_venue"],
        temporal_excluded_rows=summary["temporal_excluded_rows"],
        temporal_reference_exclusions=json.loads(
            skipped.to_json(orient="records", force_ascii=False)
        ),
        warnings=[
            specific,
            hidden_note,
            "Seoul direct last400 unavailable; overlapping section scores must not be summed",
            "Sparse grades and state cells remain sparse after estimation",
            "Record level, not win probability or absolute ability",
        ],
        status_definitions=dict(
            observed_supported="recent >=200 records/20 races/20 days",
            small_recent_sample="below one or more cell thresholds",
            no_recent_observation="same-grade reference exists; recent state absent",
            no_recent_grade_reference="no recent same-grade reference; time fields null",
        ),
        grade_reference_status_definitions=dict(
            supported=">=200 records and >=20 days",
            small="below supported thresholds",
            very_sparse="<30 records or <5 days",
            unavailable="no recent same-grade reference",
        ),
        scope="Research preparation; public website and operating models unchanged",
    )
    (out / f"web_benchmarks{distance}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    fig, axes = plt.subplots(
        1, len(venues), figsize=(8 if len(venues) == 1 else 14, 8), squeeze=False
    )
    for ax, meet in zip(axes[0], venues, strict=True):
        rows = dry[dry.meet.eq(meet)].set_index("grade").reindex(GRADES)
        y = np.arange(len(GRADES))
        ax.hlines(y, rows.p20, rows.p80, color="#246b95", lw=8, alpha=0.25, label="P20~P80")
        ax.scatter(rows["mean"], y, color="#246b95", s=45, label="추정 평균", zorder=3)
        ax.scatter(rows.fast20_mean, y, color="#29885e", marker="<", s=40, label="빠른20% 평균")
        ax.scatter(rows.slow20_mean, y, color="#a65543", marker=">", s=40, label="느린20% 평균")
        names = [
            g
            + (
                " (없음)"
                if pd.isna(rows.loc[g, "mean"])
                else " *"
                if rows.loc[g, "grade_reference_status"] != "supported"
                else ""
            )
            for g in GRADES
        ]
        ax.set_yticks(y, names)
        ax.invert_yaxis()
        ax.set_xlim(105 if distance == 1700 else 110, 124 if distance == 1700 else 128)
        ax.set_title(f"{meet} · {distance}m 건조", fontsize=16)
        ax.set_xlabel("기록(초) · 왼쪽이 빠름")
        ax.grid(axis="x", alpha=0.15)
    axes[0][0].legend(
        loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2, frameon=False, fontsize=10
    )
    fig.suptitle(f"등급별 {distance}m 기록 기준v1", fontsize=20)
    fig.text(
        0.5,
        0.025,
        "* 등급 참조 소표본 · 막대는 P20~P80 기록 범위이며 신뢰구간이 아님",
        ha="center",
        fontsize=10,
    )
    fig.subplots_adjust(
        top=0.87, bottom=0.24, wspace=0.22, left=0.22 if len(venues) == 1 else 0.10, right=0.96
    )
    fig.savefig(out / f"dry_grade_benchmarks{distance}.png", dpi=160, facecolor="white")
    plt.close(fig)
    topic_text = f"""# {"·".join(venues)}{distance}m 등급·주로상태 기준

2026-10-06. 최근 같은 등급 참조로{summary["reference_cells"]}개 상태 조합과 전체·구간{summary["benchmark_rows"]}행의 연구 기준을 만들었다. 자료가 없는{summary["unsupported_whole_cells"]}조합은 비워 뒀다. 최종 표본{summary["input_n"]:,}행, 최근 참조{summary["recent_n"]:,}행이다. 자료 종료일은{end_note}다.

{specific}

{markdown(dry_display)}

독립 구간200·{distance - 800}·400·200m와 겹치는 막판600m, 부산 직접 마지막400m를 구분했다. 서울 직접 마지막400m는 없다. 평균·중앙·시간 상하위·실제 착순 집단·구간·같은등급 및 전체등급 점수를 보존했다.

시간순 평균기록 오차:

{md_metrics}

모든 방법에 같은 평가 출전기록을 적용했고 이전 같은 등급 참조가 없는{summary["temporal_excluded_rows"]}행은 제외했다. {hidden_note} 개별 말 우승확률·적중률·수익 개선을 검증한 수치는 아니다.

{markdown(thin_display)}

등급 전체 참조와 해당 상태 표본을 구분한다. 날짜 재표집 유효180/200 미만의 평균·분위수 신뢰구간은 제공하지 않는다. 현재 운영 모델·웹 배포나 기존 보정 결정을 변경하지 않았다.

[원 연구](../20261006_1700_1800_benchmarks/{distance}/README.md), [전체 등급·상태 표](../20261006_1700_1800_benchmarks/{distance}/ALL_BENCHMARKS.md), [게시 요약](../20261006_1700_1800_benchmarks/{distance}/PUBLICATION.md), [전체 작업 용량](../20261006_1700_1800_benchmarks/outputs/artifact_inventory.json)
"""
    (HERE.parent / "conclusions" / topic).write_text(topic_text)
    return metric_rows


def main():
    out = HERE / "outputs"
    out.mkdir(exist_ok=True)
    results = [*render(1700), *render(1800)]
    pd.DataFrame(results).to_csv(out / "distance_validation_comparison.csv", index=False)
    readme = f"""# 서울1700m와 서울·부산1800m 기록 기준 연구

2026-10-06 사용자 요청에 따라 두 거리 연구를 한 폴더에 보존했다.1700m는 서울만,1800m는 서울·부산을 분석했다. 최근 등급·상태 기준은1700m25조합150행,1800m90조합585행이다. 전체24,452행에서 최근9,152행을 참조했다.

| 연구 | 원 보고서 | 상세 상태 표 | 게시 요약 |
|---|---|---|---|
| 서울1700m | [연구](1700/README.md) | [50조합 표](1700/ALL_BENCHMARKS.md) | [요약](1700/PUBLICATION.md) |
| 서울·부산1800m | [연구](1800/README.md) | [100조합 표](1800/ALL_BENCHMARKS.md) | [요약](1800/PUBLICATION.md) |

시간순 검증의 조합별 평균기록 오차(초):

{markdown(pd.DataFrame(results))}

1700m 국5·국6 기준을 포함했고 국OPEN3일 참조를 구분했다.1800m 국6는 두 지역 모두 같은 거리 참조가 없어 비워 뒀다.1800m 서울 국5의2024년31행은 이전 같은 등급 참조가 없어 시간순 검증에서 공통 제외했다.1700m 숨긴 조합 복원의 개선은 확인되지 않았으므로 미관측 상태의 안정성을 확정하지 않는다.

모든 기준은 기록 비교용 연구 결과다. 우승 확률·종합능력이나 기존 보정 채택 상태로 표현하지 않았다. 실제 웹 배포·운영 반영은 수행하지 않았다.

[계획](PLAN.md), [원천과 방법](SOURCES.md), [서울1700 중앙 결론](../conclusions/15_BENCHMARK1700.md), [1800 중앙 결론](../conclusions/16_BENCHMARK1800.md), [전체 산출물 용량](outputs/artifact_inventory.json)
"""
    (HERE / "README.md").write_text(readme)
    print("Both distance reports, publication datasets and central topic conclusions written")


if __name__ == "__main__":
    main()
