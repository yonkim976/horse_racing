"""Publish data-derived local research tables and reader summary."""

# ruff: noqa: E501 -- Generated Korean report paragraphs retain semantic lines.

import importlib.util
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("seoul_report_analysis", HERE / "analyze.py")
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)
LABELS = {
    "early": "초반200m",
    "middle1": "중반",
    "middle2": "600→200m의400m",
    "late": "마지막200m",
    "finish": "전체",
    "last600": "마지막600m",
}


def number(value):
    return "미제공" if pd.isna(value) else f"{value:+.3f}"


def table(frame, columns):
    rows = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in frame.itertuples(index=False, name=None):
        rows.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(rows)


def records(frame):
    return json.loads(frame.to_json(orient="records", force_ascii=False))


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    verification = json.loads((OUT / "verification.json").read_text())
    population, _ = S.load()
    f = pd.read_csv(OUT / "correction_components.csv", dtype={"level": str})
    effects = pd.read_csv(OUT / "effect_profiles.csv", dtype={"level": str})
    primary = f[f.variant.eq("tail25") & f.period.eq("all_mad4")]
    core = primary[primary.scope.eq("core")]
    primary[primary.family.eq("month")].to_csv(OUT / "month_primary.csv", index=False)
    primary[primary.family.isin(["number", "group"])].to_csv(OUT / "gate_primary.csv", index=False)
    primary[primary.scope.eq("corner") & primary.family.eq("moisture")].to_csv(
        OUT / "corner_moisture_primary.csv", index=False
    )
    cov = pd.read_csv(OUT / "coverage.csv")
    cov["original_races"] = [
        population[
            population.distance_m.eq(r.distance_m)
            & (population.year.ge(2024) if r.period == "recent_mad4" else True)
        ].race_key.nunique()
        for r in cov.itertuples()
    ]
    cov.to_csv(OUT / "coverage_detail.csv", index=False)
    # Record reason-neutral source-layout exceptions, never label these poor performances.
    bad = population[~population.corner_valid].copy()
    bad[["row_key", "distance_m", "date", *S.POINTS, "alias_valid"]].to_csv(
        OUT / "corner_layout_exclusions.csv", index=False
    )
    moisture = core[core.family.eq("moisture")]
    moisture_wide = moisture.pivot(
        index=["distance_m", "level"], columns="section", values="add_seconds"
    )
    moisture_wide.reset_index().to_csv(OUT / "core_moisture_table.csv", index=False)
    sat = moisture_wide.xs("포화", level="level").reindex(columns=S.CORE)
    sat_text = sat.map(number).reset_index()
    sat_text.insert(1, "中반거리", [f"{int(d) - 800}m" for d in sat_text.distance_m])
    sat_table = table(
        sat_text, ["경주거리", "중반거리", "초반200m", "중반", "후반400m", "마지막200m"]
    )
    rates = moisture.copy()
    rates["add_per_200m_average"] = rates.add_seconds * 200 / rates.length_m
    rates["interpretation"] = "mean per 200m, not observed individual 200m splits"
    rates.to_csv(OUT / "core_moisture_per200_average.csv", index=False)
    corner = primary[
        primary.scope.eq("corner") & primary.family.eq("moisture") & primary.level.eq("포화")
    ]
    corner = corner[corner.section.str.contains("_to_")]
    corner_text = corner[corner.distance_m.isin([1200, 1300, 1700])][
        ["distance_m", "section", "add_seconds"]
    ].copy()
    corner_text.add_seconds = corner_text.add_seconds.map(number)
    corner_table = table(corner_text, ["거리", "계측 구간", "시험 가산초"])
    range_rows = []
    for dist, group in core.groupby("distance_m"):
        for part in S.CORE:
            row = dict(distance_m=int(dist), section=part)
            for name, families in [("month", ["month"]), ("gate", ["number", "group"])]:
                z = group[group.section.eq(part) & group.family.isin(families) & group.available]
                row[name + "_min"] = z.add_seconds.min()
                row[name + "_max"] = z.add_seconds.max()
            range_rows.append(row)
    ranges = pd.DataFrame(range_rows)
    ranges.to_csv(OUT / "core_month_gate_ranges.csv", index=False)
    range_display = ranges[ranges.distance_m.isin([1200, 1300, 1600, 1700, 1800])].copy()
    range_display["월별"] = [
        number(a) + " ~ " + number(b)
        for a, b in zip(range_display.month_min, range_display.month_max, strict=True)
    ]
    range_display["게이트별"] = [
        number(a) + " ~ " + number(b)
        for a, b in zip(range_display.gate_min, range_display.gate_max, strict=True)
    ]
    range_display.section = range_display.section.map(LABELS)
    ranges_table = table(
        range_display[["distance_m", "section", "월별", "게이트별"]],
        ["거리", "구간", "월별 가산초 범위", "게이트별 가산초 범위"],
    )
    # Compare matched population direct coefficients to the earlier algebraic table.
    old = pd.read_parquet(S.E.OUT / "combined_correction_lookup.parquet")
    examples = json.loads((OUT / "application_examples.json").read_text())
    comparisons = []
    for e in examples:
        if e["scope"] != "core":
            continue
        for section, entry in e["sections"].items():
            z = old[
                old.meet.eq("서울")
                & old.distance_m.eq(e["distance_m"])
                & old.field_size.eq(10)
                & old["mode"].eq("number")
                & old.level.astype(str).eq("10")
                & old.band.eq("포화")
                & old.month.eq(7)
                & old.period.eq("all_mad4")
                & old.target.eq(section)
            ]
            comparisons.append(
                dict(
                    distance_m=e["distance_m"],
                    section=section,
                    old_v1_candidate=float(z.iloc[0].total_add_seconds)
                    if len(z) == 1 and z.iloc[0].complete
                    else None,
                    direct_trial_candidate=entry["total_add_seconds"],
                    note="Different shrink policy and primary cohort; not a performance comparison",
                )
            )
    pd.DataFrame(comparisons).to_csv(OUT / "previous_candidate_comparison.csv", index=False)
    sens = pd.read_csv(OUT / "tail_sensitivity.csv")
    matched = sens[
        sens.available
        & sens.available_baseline
        & sens.family.eq("moisture")
        & sens.scope.eq("core")
    ]
    sensitivity_max = float(abs(matched.candidate_change).max())
    shared_keys = ["distance_m", "scope", "variant", "family", "block", "level", "section"]
    full = effects[
        effects.period.eq("all_mad4")
        & effects.variant.eq("tail25")
        & effects.scope.eq("core")
        & effects.family.eq("moisture")
    ]
    recent = effects[
        effects.period.eq("recent_mad4")
        & effects.variant.eq("tail25")
        & effects.scope.eq("core")
        & effects.family.eq("moisture")
    ]
    pairs = full.merge(recent, on=shared_keys, suffixes=("_full", "_recent"))
    pairs["same_sign"] = np.sign(pairs.effect_seconds_full) == np.sign(pairs.effect_seconds_recent)
    pairs.to_csv(OUT / "recent_moisture_comparison.csv", index=False)
    plot(primary, sat)
    e1200 = next(e for e in examples if e["distance_m"] == 1200 and e["scope"] == "core")
    e1300 = next(e for e in examples if e["distance_m"] == 1300 and e["scope"] == "core")
    e1700 = next(e for e in examples if e["distance_m"] == 1700 and e["scope"] == "core")
    example_text = []
    for e in [e1200, e1300, e1700]:
        terms = [
            f"{LABELS[part]} {e['sections'][part]['total_add_seconds']:+.3f}초" for part in S.CORE
        ]
        example_text.append(
            f"- 서울{e['distance_m']}m: "
            + ", ".join(terms)
            + f". 합계 {e['sections']['finish']['total_add_seconds']:+.3f}초."
        )
    publication = f"""# 서울 구간별 함수율 월 게이트 보정

2026-10-11 연구 후보. 서울에서는 초반200m·중반D−800m·결승 전600→200m의400m·마지막200m를 기본으로 비교한다.1300m 중반500m와1700m 중반900m도 포함한다. 코너 누적기록 차이는 별도 분할로 보존한다.

포화 주로의 기록 차이는 마지막200m에만 집중되지 않았다.1300m와1700m에서는 중반 누적 차이가 컸고, 코너 분할에서는 각각S1F→3C,2C→3C가 눈에 띄었다. 긴 구간의 초 차이가 크다고 단위거리 효과도 그만큼 크다는 뜻은 아니다.

## 기본 구간의 포화 주로 시험값

단위 초. 원기록에 더한다. 건조 대비 공동 추정 효과의40%에 표본 축소를 더한 시험값이다. 월·게이트 항목은 이 표에 아직 더하지 않았다. 지원 여부는 관측 범위이며 통계적 확정과 다르다.

{sat_table}

1200m 중반400m의+0.060초는200m당 평균+0.030초이고,1700m 중반900m의+0.139초는200m당 평균+0.031초다. 실제200m 구간을 각각 계측했다는 뜻은 아니다. 원 추정 효과·신뢰구간·다른 주로상태는 상세표에서 함께 확인한다.

## 월과 게이트를 함께 반영하는 예

포화·7월·정상10두편성10번 기준, 전체기간의 이탈후미 제외 표본이다. 아래는 함수율+월+게이트의 합이며 이 조건 밖에 복제하지 않는다.

{chr(10).join(example_text)}

보정 후 기록=원기록+함수율 항목+월 항목+게이트 항목이다. 양의 값은 유리한 조건에서 빨랐던 기록을 늦춰 환산하는 방향이다. 음의 값은 반대다. 단일 구간의 기록이 빠른지와 전체 경주 성적이 좋은지는 별개다.

## 코너 구간은 별도

{corner_table}

코너 구간의 미확정 길이로200m 기록이나 속도를 만들지 않았다. 기본 분할과 코너 분할은 같은 시간을 나누는 대안이므로 서로 합산하지 않는다.1800m는S1F/1C가 겹쳐 이번 고정 코너 분할에 들어가지 않는 과거180행을 코너에서만 제외했다. 이를 불량 기록이나 느린 말로 판정한 것은 아니다.

## 적용 범위

2018-01-06~2026-09-20 서울{summary["population_rows"]:,}출전을 원자료와 대조했다.8거리{summary["models"]}개 조건부 모형,2024년 이후와 이탈후미 제외 전후도 별도 표로 보존했다.1900m28경주·2300m17경주는 모형 최소100경주에 미달한다.1600m 포화37경주,2000m 포화19경주는 상태별 최소50경주에 미달해 주 보정표에서 비워 두고 원 추정치·신뢰구간은 제공한다.1600m 월별 전체 주기와 일부 게이트 블록도 지원 부족을 표시했다.

40%·30%·30%와 축소 한도는 보수적 시험 설정이며 최적값으로 검증하지 않았다. 기존 전체시간 함수율 서울80% 채택은 유지한다. 이번 구간 합계와 기존80% 전체시간 보정을 한 출전에서 섞으면 합계가 달라진다. 운영 모델과 다음 경주 예측 성능 검증은 이번 범위에 포함하지 않는다.
"""
    (HERE / "PUBLICATION.md").write_text(publication)
    methods = f"""
## 표본과 방법

대상 원자료는 서울10거리{summary["population_rows"]:,}출전이다. 기존 모형 대상8거리{summary["eligible_rows"]:,}행에서4MAD 필터 후{summary["mad4_rows"]:,}행, 주 분석의 이탈후미 추가 제외 후{summary["tail25_rows"]:,}행이다.원 출전두수·게이트 순번과 분모는 유지한다. 함수율은 정확한 숫자별 요인으로 통제하고, 상태별 결과는 동일 거리·기간의4MAD 표본에서 고정한 숫자 혼합과 건조 혼합의 차이다.함수율1%당 직선 보정이 아니다.

마필 고정효과·경주 균등 가중,등급×연도·월1/2차 주기함수·출전두수·경주조건·연령·부담중량·마체중·rating·과거 성적을 공동 통제한다.마필/날짜 이원 군집 및 각 단일 군집 분산 중 대비별 최대를 사용한다.같은 경주 고정효과는 함수율·월을 흡수하므로 넣지 않는다. 날짜와 날씨의 미관측 영향까지 제거한 인과효과는 아니다. 실제 주행 내외측·상태별 게이트 상호작용·풍향·주로빠르기는 넣지 않는다.

월은12개월 평균 대비,게이트는 정상10/12두 연속번호 편성의 번호별 또는 나머지 편성의 순번3등분이다.기수 변경 등 모든 잠재 교란을 제거한 것은 아니다.게이트 조회에는 정제 후 남은 말이 아닌 원 출전명단이 필요하다.

## 월별 게이트별 보수적 후보 범위

아래는 전체기간 주 분석에서 이용 가능한 항목의 최솟값~최댓값이다. 실제 기록 분포·신뢰구간이 아니다. 게이트 범위는 서로 다른 출전두수 블록을 합쳐 요약했으므로 한 경주 내 최대 차이로 읽지 않는다.

{ranges_table}

## 보정 설정과 정합성

효과 반대 부호로 함수율40%·월30%·게이트30%×n/(n+100)를 가산한다.n은 상태 대비 양쪽 최소 경주수,해당 월 행수,해당 게이트 수준 행수다.월은 축소 후12개월 균등 평균0,게이트는 축소 후 해당 블록의 출전 노출 가중 평균0으로 다시 중심화한다.같은 프로필의 모든 구간에 공통 한도 배율을 적용하므로 구간합=새 후보 전체시간,후반400m+마지막200m=마지막600m를 유지한다.한도는PLAN.md에 고정했다. 지원 부족은0이 아니라null이다. 신뢰구간은 원 추정 효과의 구간이며 후보 합산값의 신뢰구간으로 옮겨 읽지 않는다.

4MAD와 이탈후미 추가 제외 간 지원 공통 함수율 후보의 최대 변화는{sensitivity_max:.6f}초다.이 값은 거리·상태·구간 중 최대이며 예측 성능 변화가 아니다.전체/최근 비교는recent_moisture_comparison.csv,정제 민감도는tail_sensitivity.csv에 있다.

직접 중반 추정과 전체−초반−막판600m 추정은 동일 표본·설계의 선형 회귀에서는 수학적으로 같아야 한다.기존 공동 추정의 공통 프로필{verification["legacy_joint_profiles_compared"]:,}개를 비교한 최대 차이는{verification["legacy_joint_max_error"]:.3g}초다.기존 최종 후보와 이번 후보의 숫자 차이는 주로 축소정책과 이탈후미 제외 기준 차이이며,새 능력 증거나 성능 개선이 아니다.새로 추가한 정보는 코너별 분해·거리 정의·일관된 직접 구간 후보와 검증이다.

## 검증

보관 공식API{summary["raw_verification"]["rows"]:,}행·계측값{summary["raw_verification"]["checkpoint_cells"]:,}개를 날짜·경주·마필·거리·완주기록과 대조했다.계측값 불일치0개.코너 분할 제외211행은1000m26행·1700m5행의 중복지점 미일치와1800m180행의S1F/1C 중복이다.기본 구간에는 유지한다.

전체{verification["models_checked"]}모형의 추정치·대비분산·신뢰구간·분할합과 후보{verification["candidate_rows_checked"]:,}행의합계·중심화를 확인했다.마필 더미를 명시한 독립 가중최소제곱{len(verification["independent_explicit_dummy_solves"])}회 재계산 최대 대비 차이는{verification["max_explicit_contrast_error"]:.3g}초다.조회 날짜 제한과 잘못된 입력{verification["invalid_requests_rejected"]}종을 검사했다.이는 추정 계산의 검증이며 다음 경주 예측 개선 검증은 아니다.

## 산출물과 재현

- effect_profiles.csv: 축소 전 효과·지원·군집 신뢰구간·다중비교q.
- correction_components.csv: 거리·분할·기간·정제·함수율/월/게이트별 시험 가산초.
- core_moisture_table.csv,core_month_gate_ranges.csv: 기본 구간 요약.
- checkpoint_ledger.parquet,corner_layout_exclusions.csv: 계측 연결과 분할 제외.
- parameters.npz,models.json,verification.json: 모형·독립 검증.
- application_examples.json,apply.py: 조건별 합산과 읽기 전용 조회.
- recent_moisture_comparison.csv,tail_sensitivity.csv: 기간·정제 민감도.
- previous_candidate_comparison.csv: 이전 정책과이번 정책 숫자 구분.
- web_research.json: 웹 게시 준비용 요약과표. 게시·배포하지 않음.

재현 순서:analyze.py→build.py→verify.py→report.py.루트의.venv/bin/python과PYTHONDONTWRITEBYTECODE=1,OPENBLAS_NUM_THREADS=1을 사용한다.운영 DB·모형은 읽기만 하고 기존 결과를 덮어쓰지 않는다.
"""
    (HERE / "README.md").write_text(publication + methods)
    sources = """# 서울 구간 환경 보정 출처

2026-10-11.새 웹 수집 없이 기존 검증 원자료를 읽기 전용으로 사용했다.

1.20261007_sex_ability_gap/outputs/population.parquet:2018년 이후 고정 모집단과 기본 구간.
2.20261002_gate_lateral_bias/outputs/runners.parquet:원 출전명단·게이트 번호/순번.
3.20261008_record_normalization_seconds의 원장:기존4MAD/trim5 표식.
4.20261008_detached_tail_sensitivity/outputs/runner_tail_flags.parquet:원 출전명단에서 만든 이탈후미 표식.
5.thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb의section_measurements_api:서울 지점 누적시간.원 응답 파일/행으로88,243출전 전수 대조.
6.20260929_calendar_api_v1/raw/race_execution_probe의2018~2026서울 보관 응답.파일 해시와 검사 건수는outputs/summary.json.
7.20261008_environment_correction_atlas와선행모형 코드:설계·군집 분산·지원 기준 및 비교 후보.
8.docs/SECTION_POINT_LOAD_PLAN_2026-09-24.md,docs/SEOUL_SECTION_REPAIR_2026-09-08.md,20261004_seoul4c_finish/SOURCES.md:계측 종류와코너 좌표 한계.
9.마사회 공식 지점 설명:https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1.앞선 대화에서 확인.일반530m 설명을 거리별 실제 경로 길이나200m 실측으로 바꾸지 않는다.

입력 DB·원장·실행 모듈의SHA-256은summary.json.시간종류를 수치 크기로 추정하지 않고원천 cumulative_time만 사용했다.
"""
    (HERE / "SOURCES.md").write_text(sources)
    S.dump(
        OUT / "web_research.json",
        dict(
            title="서울 구간별 함수율 월 게이트 보정",
            updated_on="2026-10-11",
            data_end=summary["end"],
            status="trial_only",
            production_changed=False,
            prediction_validation=False,
            publication=publication,
            definitions=records(pd.read_csv(OUT / "section_definitions.csv")),
            primary_components=records(primary),
            coverage=records(cov),
            month_gate_ranges=records(ranges),
            examples=examples,
        ),
    )
    S.dump(
        OUT / "report_summary.json",
        dict(
            primary_core_supported_components=int(core.available.sum()),
            max_moisture_candidate_tail_change=sensitivity_max,
            core_moisture_profiles_with_recent=len(pairs),
            core_moisture_both_periods_supported=int(
                (pairs.supported_full & pairs.supported_recent).sum()
            ),
            figure="section_corrections.png",
        ),
    )
    print("reports and web payload saved")


def plot(primary, sat):
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)
    dists = [1200, 1300, 1400, 1700, 1800]
    x = np.arange(len(dists))
    for i, part in enumerate(S.CORE):
        axes[0].bar(x + (i - 1.5) * 0.18, sat.loc[dists, part], 0.18, label=LABELS[part])
    axes[0].set_xticks(x, [str(d) for d in dists])
    axes[0].set_title("포화 대비 기본 구간 시험 가산초")
    axes[0].set_xlabel("경주거리 m · 중반 길이는 거리마다 다름")
    axes[0].set_ylabel("초 · 원기록에 가산")
    axes[0].legend(fontsize=9)
    g = primary[
        primary.scope.eq("corner")
        & primary.distance_m.eq(1700)
        & primary.family.eq("moisture")
        & primary.level.eq("포화")
    ]
    parts = ["early", *S.segments(1700), "late"]
    values = g.set_index("section").loc[parts, "add_seconds"]
    axes[1].barh(
        [LABELS.get(p, p.replace("_to_", "→")) for p in parts][::-1],
        values.to_numpy()[::-1],
        color="#307c87",
    )
    axes[1].set_title("서울1700m 코너 별도 분할 · 포화")
    axes[1].set_xlabel("시험 가산초 · 코너 구간 길이 미확정")
    fig.suptitle("전체기간 · 4MAD와 이탈후미 제외 · 함수율 항목만 · 연구 후보")
    fig.savefig(OUT / "section_corrections.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
