"""Render distance reports and publication data from completed, independently verified runs."""

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
DISTANCES = [1000, 1900, 2000, 2200, 2300]
GRADES = ["국6", "국5", "국4", "혼4", "국3", "혼3", "2", "1", "국OPEN", "혼OPEN"]
BANDS = ["건조", "양호", "다습", "포화", "불량"]
TOPICS = {d: f"{17 + i:02d}_BENCHMARK{d}.md" for i, d in enumerate(DISTANCES)}
NOTES = {
    1000: "서울·부산의 실전1000m이며 앞선 주행심사1000m 기준과 다르다. 최근 등급은 두 지역 모두 국6·혼4뿐이다. 부산 혼4는25기록·3일로 잠정 참조다.",
    1900: "서울의 최근 참조는2등급10기록·2026-05-30 한 경주뿐이다. 부산은2020-07-19 이후 선택 자료가 없어 최근 기준을 만들지 않았다. 부산의 과거 분포는 별도로 보존했다. 한 경주의 시간 기준과 보정 효과의 안정성을 구분해야 한다.",
    2000: "서울은1·2·국OPEN·혼OPEN, 부산은1·2·국OPEN의 최근 참조가 있다. 부산 국OPEN은16기록·한 날짜뿐이며 OPEN과 일반 등급의 순서를 강제로 정렬하지 않았다.",
    2200: "부산만 분석했다. 최근1등급8기록·한 날짜와2등급11기록·한 날짜, 총두 경주다. 최근 평가행 모두가 이전 같은 등급 참조 또는 이전 함수율 상태 지원 조건에 미달해 시간순 보정 효과를 검증할 수 없다. 전기간 포화 표본도 없어 포화 시간은 비워 뒀다.",
    2300: "서울만 분석했다. 최근1등급38기록·4일, 혼OPEN30기록·2일이다. 전기간 불량 표본이 없어 불량 시간은 비워 뒀다. 일부 재표집에서 혼OPEN 참조 자체가 없어지는 횟수를 반영했다. 이번에는 유효186/200회 이상이어서 신뢰구간을 제공하되, 원참조2일의 한계는 남는다.",
}


def read_csv(path, **kwargs):
    return pd.read_csv(path, dtype={"grade": str}, **kwargs)


def markdown(frame):
    def cell(v):
        return "—" if pd.isna(v) else str(v).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(map(cell, frame.columns)) + " |",
        "| " + " | ".join(["---"] * len(frame.columns)) + " |",
    ]
    lines += [
        "| " + " | ".join(map(cell, r)) + " |" for r in frame.itertuples(index=False, name=None)
    ]
    return "\n".join(lines)


def display(frame, names, numbers=()):
    result = frame[list(names)].copy()
    for name in numbers:
        result[name] = result[name].map(lambda x: "—" if pd.isna(x) else f"{x:.2f}")
    return result.rename(columns=names)


def records(frame):
    return json.loads(frame.to_json(orient="records", force_ascii=False))


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def render(distance):
    run, out = HERE / str(distance), HERE / str(distance) / "outputs"
    s = json.loads((out / "summary.json").read_text())
    v = json.loads((out / "verification.json").read_text())
    assert v["passed"] and v["input_hashes_unchanged"]
    source = json.loads((out / "raw_source_verification.json").read_text())
    population = pd.read_parquet(out / "population.parquet")
    table = read_csv(out / "estimated_benchmarks.csv")
    whole = read_csv(out / "whole_time_benchmarks.csv")
    absent_grade = whole.status.eq("no_recent_grade_reference")
    absent_state = whole.status.eq("no_historical_state_support")
    empty = whole["mean"].isna()
    for key, value in dict(
        distance=distance,
        part="finish",
        observed_n=0,
        observed_races=0,
        observed_days=0,
        bootstrap_valid_n=0,
        reference_version=s["version"],
    ).items():
        whole.loc[empty, key] = value
    for key, value in dict(
        reference_n=0, reference_days=0, grade_reference_status="unavailable"
    ).items():
        whole.loc[absent_grade, key] = value
    assert whole.loc[absent_state, "reference_n"].gt(0).all()
    whole.to_csv(out / "whole_time_benchmarks.csv", index=False)
    dry = table[table.band.eq("건조") & table.part.eq("finish")]
    state = (
        table[table.part.eq("finish")]
        .pivot(index=["meet", "grade"], columns="band", values="mean")
        .reindex(pd.MultiIndex.from_product([s["venues"], GRADES], names=["meet", "grade"]))
        .reindex(columns=BANDS)
        .reset_index()
    )
    state_md = markdown(
        display(state, dict(meet="지역", grade="등급", **{b: b for b in BANDS}), BANDS)
    )
    dry_md = markdown(
        display(
            dry,
            dict(
                meet="지역",
                grade="등급",
                reference_n="참조 기록",
                reference_days="참조 일수",
                mean="추정 평균",
                p20="빠른20% 경계",
                median="중앙",
                p80="느린20% 경계",
                fast20_mean="빠른20% 평균",
                slow20_mean="느린20% 평균",
            ),
            ["mean", "p20", "median", "p80", "fast20_mean", "slow20_mean"],
        )
    )
    labels = dict(
        early="출발200m",
        middle1=f"200~{distance - 600}m({distance - 800}m)",
        middle2=f"{distance - 600}~{distance - 200}m(400m)",
        late="마지막200m",
        last600="마지막600m",
        last400="부산 직접 마지막400m",
    )
    section = (
        table[table.band.eq("건조")]
        .pivot(index=["meet", "grade"], columns="part", values="mean")
        .reindex(columns=labels)
        .reset_index()
    )
    section_md = markdown(display(section, dict(meet="지역", grade="등급", **labels), labels))
    coverage, historical = [], []
    for meet in s["venues"]:
        for grade in GRADES:
            h = population[population.meet.eq(meet) & population.grade.eq(grade)]
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
                    for part in ["finish", *labels]:
                        values = group[part].dropna()
                        if len(values):
                            historical.append(
                                dict(
                                    meet=meet,
                                    grade=grade,
                                    band=band,
                                    part=part,
                                    n=len(values),
                                    days=group.date.nunique(),
                                    mean=values.mean(),
                                    median=values.median(),
                                    p20=values.quantile(0.2),
                                    p80=values.quantile(0.8),
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
    dev = read_csv(out / "development_validation.csv")
    support = (
        dev.groupby(["meet", "year"])[
            [
                "n",
                "original_test_n",
                "excluded_unseen_grade_n",
                "excluded_unseen_state_n",
                "train_n",
                "train_days",
            ]
        ]
        .first()
        .reset_index()
    )
    support.to_csv(out / "development_support.csv", index=False)
    skipped = read_csv(out / "temporal_reference_exclusions.csv")
    metrics = pd.DataFrame(
        s["mean_validation"],
        columns=["meet", "method", "cells", "cell_mean_mae", "cell_mean_bias", "runner_mae"],
    )
    metric_rows, interpretation = [], {}
    for meet in s["venues"]:
        ss = next(x for x in s["temporal_validation_support"] if x["meet"] == meet)
        m = metrics[metrics.meet.eq(meet)].set_index("method")
        raw = float(m.loc["cell_raw_fallback", "cell_mean_mae"]) if len(m) else None
        bench = float(m.loc["benchmark_shift_reference", "cell_mean_mae"]) if len(m) else None
        if ss["status"] == "none":
            result = "검증 불가"
            interpretation[meet] = "unavailable temporal validation; provisional reference"
        elif ss["status"] == "sparse":
            result = "희소 검증·효과 미확정"
            interpretation[meet] = (
                "provisional sparse reference; temporal improvement cannot be established"
            )
        elif bench < raw:
            result = "평균 오차 감소"
            interpretation[meet] = "research reference; lower temporal mean error"
        else:
            result = "개선 미확인·잠정"
            interpretation[meet] = "provisional research; temporal mean error not lower"
        metric_rows.append(
            dict(
                거리=distance,
                지역=meet,
                원시기준오차="—" if raw is None else f"{raw:.3f}",
                추정기준오차="—" if bench is None else f"{bench:.3f}",
                검증조합=ss["cells"],
                검증경주=ss["races"],
                검증일수=ss["days"],
                판단=result,
            )
        )
    metrics_md = markdown(pd.DataFrame(metric_rows))
    thin = dry[dry.grade_reference_status.ne("supported")]
    thin_md = markdown(
        display(
            thin,
            dict(
                meet="지역",
                grade="등급",
                reference_n="참조 기록",
                reference_days="참조 일수",
                bootstrap_valid_n="유효 재표집",
                grade_reference_status="등급 참조",
            ),
        )
    )
    effects = read_csv(out / "state_effects.csv")
    representatives = []
    examples = []
    for meet in s["venues"]:
        available = dry[dry.meet.eq(meet)]
        if available.empty:
            continue
        grade = "국6" if distance == 1000 else "2" if distance in [1900, 2000] else "1"
        if grade not in set(available.grade):
            grade = available.grade.iloc[0]
        selected = table[table.meet.eq(meet) & table.grade.eq(grade) & table.part.eq("finish")]
        for row in effects[
            effects.meet.eq(meet) & effects.grade.eq(grade) & effects.part.eq("finish")
        ].itertuples():
            representatives.append(
                dict(meet=meet, grade=grade, band=row.band, shift_from_dry=row.shift_from_dry)
            )
        time = round(float(available[available.grade.eq(grade)]["median"].iloc[0]), 1)
        for band in ["건조", "포화" if "포화" in set(selected.band) else "다습"]:
            process = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "evaluate_record.py"),
                    "--distance",
                    str(distance),
                    "--meet",
                    meet,
                    "--grade",
                    grade,
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
    dump(out / "record_score_examples.json", examples)
    ex_md = markdown(
        display(
            pd.DataFrame(examples),
            dict(
                meet="지역",
                grade="등급",
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
    )
    ef_md = markdown(
        display(
            pd.DataFrame(representatives),
            dict(meet="지역", grade="예시 등급", band="상태", shift_from_dry="건조 대비 차이"),
            ["shift_from_dry"],
        )
    )
    hidden = pd.DataFrame(
        s["hidden_cell_validation"],
        columns=["meet", "cells", "mean_abs_error", "grade_fallback_mae", "p90_abs_error"],
    )
    hidden_md = (
        markdown(
            display(
                hidden,
                dict(
                    meet="지역",
                    cells="숨긴 조합",
                    mean_abs_error="복원 오차",
                    grade_fallback_mae="원시 등급 대체 오차",
                    p90_abs_error="90% 오차",
                ),
                ["mean_abs_error", "grade_fallback_mae", "p90_abs_error"],
            )
        )
        if len(hidden)
        else "표본 조건(숨긴100기록·10일, 평가5일)을 충족하는 조합이 없어 검증하지 못했다."
    )
    shares = pd.DataFrame(
        s["threshold_validation"], columns=["meet", "n", "fast20_share", "slow20_share"]
    )
    for col in ["fast20_share", "slow20_share"]:
        shares[col] = shares[col].map(lambda x: f"{100 * x:.2f}%")
    shares_md = (
        markdown(
            shares.rename(
                columns=dict(
                    meet="지역",
                    n="평가 기록",
                    fast20_share="빠른20% 경계 이하",
                    slow20_share="느린20% 경계 이상",
                )
            )
        )
        if len(shares)
        else "시간순 평가 참조가 없어 이후 경계 비율을 계산하지 못했다."
    )
    end = "·".join(f"{m}{date}" for m, date in s["input_end"].items())
    quality = read_csv(out / "excluded_sections.csv")
    ledger = read_csv(out / "selection_ledger.csv")
    bounds = {
        1000: "전체45~100초·중간200m8~25초",
        1900: "전체105~190초·중간1100m44~110초",
        2000: "전체110~200초·중간1200m48~120초",
        2200: "전체120~220초·중간1400m56~140초",
        2300: "전체125~230초·중간1500m60~150초",
    }[distance]
    details = [
        f"# {distance}m 전체 등급·상태 기준표",
        "단위 초. 실제 상태의 관측 평균과 최근 같은 등급 모든 상태 기록을 맞춘 추정 기준을 구분한다. P20 이하와 P80 이상은 시간 기준의 빠른20%·느린20% 경계이며 꼬리 평균이나 착순 상위·하위 집단과 다르다.",
    ]
    for meet in s["venues"]:
        for band in BANDS:
            rows = whole[whole.meet.eq(meet) & whole.band.eq(band)]
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
                status="표본 상태",
                grade_reference_status="등급 참조",
            )
            details += [
                f"## {meet} {band}",
                markdown(
                    display(
                        rows,
                        names,
                        [
                            "observed_mean",
                            "mean",
                            "p20",
                            "median",
                            "p80",
                            "fast20_mean",
                            "slow20_mean",
                        ],
                    )
                ),
            ]
    definitions = "observed_supported는 최근200기록·20경주·20일 모두 충족, small_recent_sample은 하나라도 미달, no_recent_observation은 상태 미관측, no_recent_grade_reference는 최근 등급 참조 부재, no_historical_state_support는 해당 지역·거리에서 전기간 그 상태 지원 부재다. 마지막 두 경우 시간은 null이다. 등급 전체 참조는200기록·20일 이상 supported,30기록 미만 또는5일 미만 very_sparse, 나머지 small이다."
    details += [
        "## 해석",
        definitions,
        "추정으로 원관측 표본이 늘지는 않는다. [전체·구간CSV](outputs/estimated_benchmarks.csv)에 P10/P90·중간60% 인원 및 평균·95% 평균/분위수 재표집 구간을 함께 보존했다. 날짜 재표집 유효180/200 미만이면 신뢰구간을 비운다. 유효 반복수가 많아도 한두 날짜의 참조는 잠정이다. [원 보고서](README.md)의 검증 한계를 함께 읽는다.",
    ]
    (run / "ALL_BENCHMARKS.md").write_text("\n\n".join(details) + "\n")
    check_note = f"개별 원API{source['checked_rows']:,}행 식별·거리·착순·전체·구간 대조 불일치0. 부산 직접400m 추가 품질 결측{source['invalid_busan400']}행. 입력해시 보존 및 독립수치{v['numeric_checks']:,}개·시간순 점수{v['chronological_score_checks']:,}개 대조 통과."
    readme = f"""# {"·".join(s["venues"])}{distance}m 등급·주로상태 기준v1

2026-10-06. 최근 같은 등급 참조로 **{s["reference_cells"]}개 상태 조합·전체/구간{s["benchmark_rows"]}행**을 만들었다. {s["unsupported_whole_cells"]}조합은 비워 뒀다(최근 등급 참조 부재{s["unsupported_grade_cells"]}, 전기간 상태 지원 부재{s["unsupported_state_cells"]}). 영천·제주·주로빠르기는 제외했다.

{NOTES[distance]}

## 상태별 추정 평균

단위 초. 최근2024년 이후 같은 등급 모든 상태 기록을 목표 상태로 맞춘 분포다. 실제 해당 상태 출전마의 관측 평균과 다르다. 함수율 건조1~5%, 양호6~9%, 다습10~14%, 포화15~19%, 불량20% 이상이다.

{state_md}

{definitions}

[전체 상세표](ALL_BENCHMARKS.md)에는 관측 평균·과거 표본·등급 참조를 함께 표시했다. 최근 참조 없는 등급의 과거 분포는[별도CSV](outputs/historical_only_grade_distributions.csv)에 있다.

## 건조 분포와 참조 일수

{dry_md}

P20 이하와 P80 이상을 시간 기준 빠른20%·느린20%로 읽는다. 동률을 보존하므로 인원이 정확히20%가 아닐 수 있다. 실제 착순 상위3·하위3 집단은[착순 분포](outputs/observed_rank_cohorts.csv), 전체시간으로 선택한 집단의 구간 평균은[시간 집단](outputs/estimated_finish_cohorts.csv)에 별도로 있다.

{thin_md}

날짜 군집200회 재표집에서 유효180회 미만이면 평균·분위수 신뢰구간을 비운다. 조건을 충족해도 원참조 날짜가 적으면 잠정이다.95% 구간은 평균·분위수 불확실성이며 개별 기록 범위나 인과효과가 아니다.

## 구간 기준

독립 구간은 **200 + {distance - 800} + 400 + 200m**다. 중간=전체−출발200−막판600, 후반400=막판600−막판200이다. 건조 추정 평균:

{section_md}

막판600은 겹치는 보조 구간이다. 부산 직접 마지막400m({distance - 400}~{distance}m)는 후반400m와 별개다. 서울 직접 마지막400m는 원자료가 없어 만들지 않았다. 전체·겹치는 구간 점수를 합산하지 않는다. 중간 내부 페이스나 실제 주행 경로를 계측한 결과는 아니다.

## 모집단·원천 검증

원천 감사 거리 선택{len(ledger):,}행 → 기존 정상·완전 착순 모집단{len(population) + len(quality):,}행 → 넓은 품질 범위 제외{len(quality)}행 → 최종 **{len(population):,}행**, 최근 **{s["recent_n"]:,}행**이다. 종료일은{end}다.

추가 품질 범위는{bounds}·출발200m10~25초·후반400m16~45초·막판200m8~25초다. 부산 직접400m16~50초 및 막판200보다 길고 막판600보다 짧은 조건은 보조 구간에만 적용했다. 정상적인 빠른/느린 기록을 일정 비율로 제거하지 않았다. 넓은 범위를 검증된 최적 제외선이나 원천 오류 판정으로 해석하지 않는다.

[거리 선택 원장](outputs/selection_ledger.csv), [추가 제외 원장](outputs/excluded_sections.csv), [등급 과거/최근 표본](outputs/grade_coverage.csv)을 보존했다. 품질 제외 뒤에도 기존 출전두수·착순을 유지해 하위3 집단 정의를 바꾸지 않았다. {check_note}

## 방법과 개발 지원

지역별 Ridge alpha10으로 등급·상태·상호작용·연도·월·성별·연령·부담중량·rating·엄격한 이전 날짜 최근5회 착순 및 초반 위치 이력을 통제했다. 이력은 다른 거리도 포함한다. 경주별 총 가중치를 같게 했다. 독립 구간을 각각 맞추고 전체·막판600을 합으로 만들었다. 개발2021~2023에서0/0.3/1/3 중 조합평균 오차 최소값+0.01초 안의 가장 단순한 상호작용 강도를 선택했다. 개발기간에서 미관측 등급 또는 이전 상태 지원 없는 평가행은 제외했다. 선택강도{s["selected_interaction_scale"]}, 선택지원{s["development_selection_status"]}이다. 개발 표본이 없는 기본0은 검증된 최적값이 아니다.

{markdown(support)}

최근 같은 등급 기록에서 자기 상태 효과를 빼고 목표 효과를 더한 분포다. 상태별 분산·꼬리 모양의 변화까지 추정하지 않는다. 건조 대비 전체시간 차이 예시:

{ef_md}

음수는 빠른 방향, 양수는 느린 방향이다. 상태를 단조관계로 강제하지 않았다. 다른 거리의 초 단위 보정치를 입력하지 않았고 기존 전체보정 결정이나 구간보정 채택 보류를 변경하지 않았다.

## 시간순 검증과 한계

2024·2025·2026 이전 자료만 학습하고 이전3년 같은 등급을 참조했다. 모든 방법에 같은 평가 출전기록을 사용한다. 이전 같은 등급 참조 또는 전기간 이전 상태 지원 없는 **{s["temporal_excluded_rows"]}행**은 공통 제외했다.

{markdown(skipped)}

검증 대상{s["score_rows"]:,}행에서 등급×상태×연도 조합의 실제 평균과 기준 평균의 절대 차이를 같은 조합 가중치로 비교했다:

{metrics_md}

희소 검증은 평가20일 또는10조합에 미달하는 경우다. 한두 경주의 낮은 오차로 보정 효과를 확정하지 않는다. 개별 말 시간 예측·우승확률·적중률·수익 개선을 뜻하지 않는다. 숨긴 조합 복원:

{hidden_md}

이번1000m 두 지역과2000m 부산의 숨긴 조합 복원은 원시 등급 대체보다 오차가 컸다. 다른 지역·거리에서는 표본 조건을 충족하지 못했다. 시간순 평균 오차의 개선을 미관측 상태의 정확성까지 확장할 수 없다. 이전 P20/P80 경계가 이후 기록에서 차지한 비율:

{shares_md}

이후에도 정확히20%로 분류된다는 뜻이 아니다. {check_note}

## 한 기록의 수준

{ex_md}

같은등급 점수는 자신보다 느린 참조 비율×100에 동률 절반을 더한 값이다. 전체등급 점수는 같은 지역·거리의 최근 참조 등급 전체를 건조로 맞춘 분포와 비교한다. 지역별 등급 구성이 다르므로 종합능력·공식rating·우승확률로 읽지 않는다. 최종표는 후향 참조, 과거 점수는 해당 연도 이전 참조다. 지원 없는 조합은 평가 도구도 거부한다.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261006_remaining_distance_benchmarks/evaluate_record.py --distance {distance} --meet {examples[0]["meet"]} --grade {examples[0]["grade"]} --band 건조 --time {examples[0]["time_seconds"]}
```

[공통 계획](../PLAN.md), [원천](../SOURCES.md), [게시 요약](PUBLICATION.md), [게시JSON](outputs/web_benchmarks{distance}.json), [중앙 결론](../../conclusions/{TOPICS[distance]}), [전체 산출물 용량](../outputs/artifact_inventory.json)

![건조 분포](outputs/dry_grade_benchmarks{distance}.png)
"""
    (run / "README.md").write_text(readme)
    publication = f"""# {"·".join(s["venues"])}{distance}m 기록 기준

최근 같은 등급 참조로{s["reference_cells"]}개 상태 조합·전체/구간{s["benchmark_rows"]}행의 평균·중앙·빠른20%·느린20% 경계를 만들었다. 자료 없는{s["unsupported_whole_cells"]}조합은 시간 null이다. 실제 관측 평균과 상태를 맞춘 추정 기준을 구분한다.

{NOTES[distance]}

{state_md}

{metrics_md}

희소·검증 불가는 보정 효과의 개선을 확정하지 못한 상태다. 우승 예측이나 종합능력으로 읽지 않는다. 독립 구간200·{distance - 800}·400·200m와 겹치는 막판600·부산 직접 마지막400을 구분하며 서울 직접 마지막400은 없다.

[원자료·방법·분포·검증](README.md), [전체 조합](ALL_BENCHMARKS.md), [게시JSON](outputs/web_benchmarks{distance}.json). 웹 배포·운영 적용은 수행하지 않았다.
"""
    (run / "PUBLICATION.md").write_text(publication)
    payload = dict(
        benchmark_version=s["version"],
        distance_m=distance,
        created_on="2026-10-06",
        data_end=s["input_end"],
        reference_start="2024-01-01",
        unit="seconds",
        venues=s["venues"],
        bands=BANDS,
        grade_order=GRADES,
        sections=dict(labels=labels, disjoint_metres=s["disjoint_section_metres"]),
        whole_time_cells=records(whole),
        section_cells=records(table),
        grade_coverage=records(cov),
        benchmark_interpretation_by_venue=interpretation,
        validation=s["mean_validation"],
        temporal_validation_support=s["temporal_validation_support"],
        historical_state_support=s["historical_state_support"],
        development_selection_status=s["development_selection_status"],
        development_years_by_venue=s["development_years_by_venue"],
        temporal_excluded_rows=s["temporal_excluded_rows"],
        temporal_reference_exclusions=records(skipped),
        warnings=[
            NOTES[distance],
            "One or two race references remain provisional even if bootstrap count is sufficient",
            "Record level, not win probability or absolute ability",
            "Seoul direct last400 unavailable; overlapping section scores must not be summed",
        ],
        status_definitions=dict(
            observed_supported="recent >=200 records/20 races/20 days",
            small_recent_sample="below one or more cell thresholds",
            no_recent_observation="recent state absent with historical venue/distance state support",
            no_recent_grade_reference="no recent same-grade reference; time fields null",
            no_historical_state_support="no historical venue/distance state support; time fields null",
        ),
        grade_reference_status_definitions=dict(
            supported=">=200 records and >=20 days",
            small="below supported thresholds",
            very_sparse="<30 records or <5 days",
            unavailable="no recent same-grade reference",
        ),
        scope="Research preparation; operating model and website unchanged",
    )
    dump(out / f"web_benchmarks{distance}.json", payload)
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    fig, axes = plt.subplots(
        1, len(s["venues"]), figsize=(8 if len(s["venues"]) == 1 else 14, 8), squeeze=False
    )
    for ax, meet in zip(axes[0], s["venues"], strict=True):
        rows = dry[dry.meet.eq(meet)].set_index("grade").reindex(GRADES)
        y = np.arange(len(GRADES))
        ax.hlines(y, rows.p20, rows.p80, lw=8, color="#246b95", alpha=0.25, label="P20~P80")
        ax.scatter(rows["mean"], y, color="#246b95", label="추정 평균", zorder=3)
        ax.scatter(rows.fast20_mean, y, color="#29885e", marker="<", label="빠른20% 평균")
        ax.scatter(rows.slow20_mean, y, color="#a65543", marker=">", label="느린20% 평균")
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
        ax.set_title(f"{meet} · {distance}m 건조", fontsize=16)
        ax.set_xlabel("기록(초) · 왼쪽이 빠름")
        ax.grid(axis="x", alpha=0.15)
        values = rows[["p20", "p80", "fast20_mean", "slow20_mean"]].to_numpy()
        if np.isfinite(values).any():
            lo, hi = np.nanmin(values), np.nanmax(values)
            margin = max(1, (hi - lo) * 0.15)
            ax.set_xlim(lo - margin, hi + margin)
        else:
            ax.set_xticks([])
            ax.set_xlabel("")
            ax.text(
                0.5,
                0.5,
                "최근 참조 없음\n과거 전용 분포는 별도CSV",
                transform=ax.transAxes,
                ha="center",
                fontsize=14,
            )
    axes[0][0].legend(
        loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2, frameon=False, fontsize=10
    )
    fig.suptitle(f"등급별 {distance}m 기록 기준v1", fontsize=20)
    fig.text(
        0.5,
        0.025,
        "* 등급 참조 소표본 · P20~P80은 기록 범위이며 신뢰구간이 아님",
        ha="center",
        fontsize=10,
    )
    fig.subplots_adjust(
        top=0.87, bottom=0.24, wspace=0.22, left=0.22 if len(s["venues"]) == 1 else 0.1, right=0.96
    )
    fig.savefig(out / f"dry_grade_benchmarks{distance}.png", dpi=160, facecolor="white")
    plt.close(fig)
    conclusion = f"""# {"·".join(s["venues"])}{distance}m 등급·상태 기준

2026-10-06. 최종{s["input_n"]:,}기록, 최근{s["recent_n"]:,}기록에서{s["reference_cells"]}개 상태 조합·전체/구간{s["benchmark_rows"]}행을 만들었다. 지원 없는{s["unsupported_whole_cells"]}조합은 비웠다. 종료일{end}.

{NOTES[distance]}

{dry_md}

{thin_md}

독립 구간200·{distance - 800}·400·200m, 겹치는 막판600·부산 직접 마지막400을 구분했다. 서울 직접 마지막400은 없다. 시간 상하위 집단과 실제 착순 집단, 동일등급·전체등급 점수를 각각 보존했다.

{metrics_md}

모든 방법에 같은 평가행을 적용했다. 이전 같은 등급 참조 또는 이전 상태 지원 부재{s["temporal_excluded_rows"]}행을 공통 제외했다. 희소 평가의 낮은 오차로 보정 개선을 확정하지 않으며 우승확률·적중률 개선을 검증한 것도 아니다. 날짜 재표집 유효180/200 미만 신뢰구간은 제공하지 않는다. 기존 보정 결정·운영 모델·웹 배포를 변경하지 않았다.

[원 연구](../20261006_remaining_distance_benchmarks/{distance}/README.md), [전체 조합](../20261006_remaining_distance_benchmarks/{distance}/ALL_BENCHMARKS.md), [게시 요약](../20261006_remaining_distance_benchmarks/{distance}/PUBLICATION.md), [산출물 용량](../20261006_remaining_distance_benchmarks/outputs/artifact_inventory.json)
"""
    (HERE.parent / "conclusions" / TOPICS[distance]).write_text(conclusion)
    return s, metric_rows


def main():
    (HERE / "outputs").mkdir(exist_ok=True)
    summaries, results = [], []
    for distance in DISTANCES:
        s, rows = render(distance)
        summaries.append(s)
        results.extend(rows)
    pd.DataFrame(results).to_csv(HERE / "outputs/distance_validation_comparison.csv", index=False)
    index = pd.DataFrame(
        [
            dict(
                거리=d,
                지역="·".join(s["venues"]),
                원보고서=f"[연구]({d}/README.md)",
                상세표=f"[전체 조합]({d}/ALL_BENCHMARKS.md)",
                게시요약=f"[요약]({d}/PUBLICATION.md)",
            )
            for d, s in zip(DISTANCES, summaries, strict=True)
        ]
    )
    readme = f"""# 남은 거리 기록 기준 연구:1000·1900·2000·2200·2300m

2026-10-06. 동결한 서울·부산 원자료에서 아직 기준을 만들지 않은 실전5거리를 같은 방법으로 분석했다. 기존1200·1300·1400·1600·1700·1800m 연구와 앞선1000m 주행심사는 재실행하지 않았다. 공식 현재 편성 거리 전체를 따로 조사한 결과가 아니라 이 연구 모집단의 남은 거리 기준이다. [모집단 전체 거리 점검표](outputs/corpus_distance_coverage.csv)에 완료 범위를 보존했다.

최종 **{sum(s["input_n"] for s in summaries):,}기록**, 최근 **{sum(s["recent_n"] for s in summaries):,}기록**, 추정 가능 **{sum(s["reference_cells"] for s in summaries)}개 등급×상태**, 전체/구간 **{sum(s["benchmark_rows"] for s in summaries)}행**이다. 전체400조합 중 지원 없는{sum(s["unsupported_whole_cells"] for s in summaries)}조합은 null이다.

{markdown(index)}

## 시간순 검증

등급×상태×연도 조합별 평균기록 오차(초). 모든 방법은 동일한 평가 출전기록을 사용한다.

{markdown(pd.DataFrame(results))}

1900m 서울은 최근한 경주·부산은 최근참조 없음,2200m 부산은 최근두 경주여서 시간순 효과를 검증할 수 없다.2300m 서울도 최근6일로 잠정이다.2200m 포화와2300m 불량은 전기간 상태 지원이 없어 추정하지 않았다. 미관측 상태 추정과 미관측 상태의 정확성 검증을 구분한다.1000m는 실전이며 주행심사와 혼합하지 않았다.

[계획](PLAN.md), [원천·방법](SOURCES.md), [중앙 결론](../conclusions/README.md), [전체 산출물 용량](outputs/artifact_inventory.json). 거리별 게시Markdown·JSON은 준비했으며 웹 배포·운영 반영은 수행하지 않았다.
"""
    (HERE / "README.md").write_text(readme)
    print("Five distance reports, publication datasets and central conclusions written")


if __name__ == "__main__":
    main()
