"""Reader-facing Busan sectional candidates and carefully matched Seoul comparisons."""

# ruff: noqa: E501 -- Generated Korean prose uses semantic paragraph lines.

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
SPEC = importlib.util.spec_from_file_location("busan_report_analysis", HERE / "analyze.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
LABELS = dict(
    early="초반200m",
    middle1="중반",
    middle2="결승 전600→200m",
    late="마지막200m",
    finish="전체",
    last600="마지막600m",
    last400="마지막400m",
)


def number(value):
    return "미제공" if pd.isna(value) else f"{value:+.3f}"


def table(frame, headers):
    rows = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    rows += [
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join(rows)


def records(frame):
    return json.loads(frame.to_json(orient="records", force_ascii=False))


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    verification = json.loads((OUT / "verification.json").read_text())
    f = pd.read_csv(OUT / "correction_components.csv", dtype={"level": str})
    sf = pd.read_csv(B.SEOUL / "outputs/correction_components.csv", dtype={"level": str})
    primary = f[f.period.eq("all_mad4") & f.variant.eq("tail25")]
    s_primary = sf[sf.period.eq("all_mad4") & sf.variant.eq("tail25") & sf.scope.eq("core")]
    primary[primary.family.eq("month")].to_csv(OUT / "month_primary.csv", index=False)
    primary[primary.family.isin(["number", "group"])].to_csv(OUT / "gate_primary.csv", index=False)
    primary[primary.scope.eq("detail")].to_csv(OUT / "detail_primary.csv", index=False)
    core = primary[primary.scope.eq("core")]
    moist = core[core.family.eq("moisture")]
    moist.pivot(index=["distance_m", "level"], columns="section", values="add_seconds").to_csv(
        OUT / "core_moisture_table.csv"
    )
    sat = moist[moist.level.eq("포화")].pivot(
        index="distance_m", columns="section", values="add_seconds"
    )
    sat_text = sat[B.CORE].map(number).reset_index()
    sat_text.insert(1, "중반길이", [int(d) - 800 for d in sat_text.distance_m])
    sat_table = table(
        sat_text, ["경주거리m", "중반m", "초반200m", "중반", "후반400m", "마지막200m"]
    )
    combined = pd.concat(
        [core.assign(venue="부산"), s_primary.assign(venue="서울")], ignore_index=True
    )
    comparison = (
        combined[combined.family.eq("moisture")]
        .pivot(index=["distance_m", "level", "section"], columns="venue", values="add_seconds")
        .reset_index()
    )
    comparison["busan_minus_seoul_candidate"] = comparison["부산"] - comparison["서울"]
    comparison.to_csv(OUT / "core_moisture_comparison_table.csv", index=False)
    cand1200 = comparison[
        comparison.distance_m.eq(1200)
        & comparison.level.eq("포화")
        & comparison.section.isin(B.CORE)
    ].copy()
    cand1200 = cand1200.set_index("section").loc[B.CORE].reset_index()
    cand1200["section"] = cand1200.section.map(LABELS)
    for col in ["서울", "부산"]:
        cand1200[col] = cand1200[col].map(number)
    candidate_table = table(
        cand1200[["section", "서울", "부산"]], ["1200m 구간", "서울 시험초", "부산 시험초"]
    )
    raw = pd.read_csv(OUT / "venue_raw_direct_contrasts.csv", dtype={"level": str})
    common_raw = raw[raw.family.eq("moisture_common_mix")]
    common_raw.to_csv(OUT / "common_moisture_raw_comparison.csv", index=False)
    rs = common_raw[
        common_raw.period.eq("all_mad4")
        & common_raw.level.eq("포화")
        & common_raw.section.eq("finish")
    ].set_index("distance_m")
    r1200 = rs.loc[1200]
    ranges = []
    for (venue, dist, part), g in combined.groupby(["venue", "distance_m", "section"]):
        row = dict(venue=venue, distance_m=int(dist), section=part)
        for name, fams in [("month", ["month"]), ("gate", ["number", "group"])]:
            z = g[g.family.isin(fams) & g.available]
            row[name + "_min"], row[name + "_max"] = z.add_seconds.min(), z.add_seconds.max()
        ranges.append(row)
    ranges = pd.DataFrame(ranges)
    ranges.to_csv(OUT / "core_month_gate_ranges_comparison.csv", index=False)
    monthly = combined[combined.family.eq("month")]
    monthly.to_csv(OUT / "core_monthly_comparison.csv", index=False)
    selected = ranges[
        ranges.venue.eq("부산")
        & ranges.distance_m.isin([1200, 1300, 1600, 1800])
        & ranges.section.isin(B.CORE)
    ].copy()
    selected["month_range"] = [
        number(a) + "～" + number(b)
        for a, b in zip(selected.month_min, selected.month_max, strict=True)
    ]
    selected["gate_range"] = [
        number(a) + "～" + number(b)
        for a, b in zip(selected.gate_min, selected.gate_max, strict=True)
    ]
    selected.section = selected.section.map(LABELS)
    range_table = table(
        selected[["distance_m", "section", "month_range", "gate_range"]],
        ["거리m", "구간", "월별 후보 범위초", "게이트 후보 범위초"],
    )
    detail1200 = primary[
        primary.distance_m.eq(1200)
        & primary.scope.eq("detail")
        & primary.family.eq("moisture")
        & primary.level.eq("포화")
    ].set_index("section")
    detail = detail1200.loc[B.partition(1200), ["length_m", "add_seconds"]].reset_index()
    detail.section = detail.section.map(lambda p: LABELS.get(p, p.replace("_to_", "→")))
    detail.add_seconds = detail.add_seconds.map(number)
    detail.length_m = detail.length_m.astype(int)
    detail_table = table(detail, ["부산1200m 계측 구간", "길이m", "포화 시험 가산초"])
    # Same original roster/month/state for both venues, with explicit missing components.
    spec = importlib.util.spec_from_file_location("busan_report_apply", HERE / "apply.py")
    ap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ap)
    sh = importlib.util.spec_from_file_location("seoul_report_apply", B.SEOUL / "apply.py")
    sa = importlib.util.module_from_spec(sh)
    sh.loader.exec_module(sa)
    helpers = {"부산": ap.BusanSections(), "서울": sa.SeoulSections()}
    examples, example_rows = [], []
    for dist in [1200, 1300, 1400, 1600, 1800]:
        for venue, helper in helpers.items():
            e = helper.lookup(
                distance=dist,
                moisture=16,
                month=7,
                horse_number=10,
                roster=list(range(1, 11)),
                as_of="2026-10-13",
            )
            e["venue"] = venue
            examples.append(e)
            row = dict(venue=venue, distance_m=dist)
            row.update(
                {part: e["sections"][part]["total_add_seconds"] for part in B.CORE + ["finish"]}
            )
            example_rows.append(row)
    B.dump(OUT / "venue_application_examples.json", examples)
    ex = pd.DataFrame(example_rows)
    ex.to_csv(OUT / "venue_application_examples.csv", index=False)
    ex_text = ex[ex.distance_m.isin([1200, 1300, 1800])].copy()
    for part in B.CORE + ["finish"]:
        ex_text[part] = ex_text[part].map(number)
    example_table = table(
        ex_text, ["지역", "거리m", "초반200m", "중반", "후반400m", "마지막200m", "합계초"]
    )
    gate1600 = raw[
        raw.distance_m.eq(1600)
        & raw.period.eq("all_mad4")
        & raw.family.eq("number")
        & raw.block.eq("exact10")
        & raw.level.eq("1")
        & raw.section.eq("early")
    ].iloc[0]
    gate_candidate = combined[
        combined.distance_m.eq(1600)
        & combined.family.eq("number")
        & combined.block.eq("exact10")
        & combined.level.eq("1")
        & combined.section.eq("early")
    ].set_index("venue")
    bcount = int(
        moist[moist.distance_m.eq(1200) & moist.level.eq("포화") & moist.section.eq("finish")]
        .iloc[0]
        .n
    )
    scount = int(
        s_primary[
            s_primary.distance_m.eq(1200)
            & s_primary.level.eq("포화")
            & s_primary.family.eq("moisture")
            & s_primary.section.eq("finish")
        ]
        .iloc[0]
        .n
    )
    chart(primary, s_primary)
    publication = f"""# 부산 구간별 환경 보정과 서울 비교

부산도 서울과 같은 기본 구간으로 함수율·월·게이트 시험 보정치를 계산했다. 2018-01-05~2026-09-18의 62,831출전을 확인했다. 초반 200m·중반 D−800m·결승 전 600→200m의 400m·마지막 200m를 기본으로 사용하고, 1300m의 중반 500m도 포함했다.

부산 1200m는 200m씩 6구간으로 나눌 수 있다. 다른 거리의 100m·300m·400m는 실제 계측 간격대로 유지했다. 서울 코너와 부산 펄롱은 위치가 다르므로 세부 지점을 일대일 비교하지 않았다.

## 부산 기본 구간의 포화 주로 시험값

단위는 초이며 원기록에 더한다. 건조 대비 함수율 항목만 표시했고 월·게이트는 별도다. 효과의 40%에 표본 축소를 추가한 후보이며 최적값이나 운영 채택값이 아니다.

{sat_table}

1000m 포화는 상태별 최소 표본 기준 미달이다. 1900m 4경주·2000m 79경주·2200m 8경주는 모형 최소 100경주에 미달해 새 계수를 만들지 않았다. 빈 값은 0이 아니다.

## 서울과 비교하는 방법

{candidate_table}

후보에는 지역별 함수율 숫자의 분포와 표본 축소가 들어간다. 1200m 포화 대비의 축소 기준 경주수는 서울 {scount}·부산 {bcount}다. 따라서 이 표의 부산 값이 작다는 사실만으로 함수율의 영향도 작다고 판단하지 않는다.

정확한 함수율 숫자의 구성을 양 지역에 동일하게 맞춘 축소 전 1200m 전체시간 효과는 서울 {r1200.seoul_effect:+.3f}초·부산 {r1200.busan_effect:+.3f}초였다. 부산−서울 차이는 {r1200.busan_minus_seoul:+.3f}초, 95% 구간 [{r1200.ci_low:+.3f}, {r1200.ci_high:+.3f}]로 0을 포함한다. 부산에서 더 빨라지는 점추정이지만 지역 간 차이를 확정할 수 없다. 조건부 관측 연관성이며 함수율의 인과효과가 아니다.

## 월과 게이트는 지역별로 유지

월은 같은 주로상태와 연도·등급 등을 통제한 12개월 평균 대비다. 부산 1200m 중반 400m의 월 후보는 약 −0.016～+0.022초, 1600m 중반 800m는 약 −0.056～+0.050초다. 월별 곡선의 시기와 크기가 서울과 달라 서울 월표를 부산에 복사하지 않는다.

게이트는 1600m 초반에서 지역 차이가 눈에 띄었다. 정상 10두 편성 1번의 축소 전 초반 200m 효과는 서울 {gate1600.seoul_effect:+.3f}초·부산 {gate1600.busan_effect:+.3f}초, 부산−서울 {gate1600.busan_minus_seoul:+.3f}초(q={gate1600.q:.4f})다. 각 지역 동일 편성 평균 대비이므로 서울에서는 빠른 방향, 부산에서는 느린 방향이다. 보수적 시험 가산은 서울 {gate_candidate.loc["서울", "add_seconds"]:+.3f}초·부산 {gate_candidate.loc["부산", "add_seconds"]:+.3f}초다. 최근 기간의 번호별 직접 차이는 다중비교 후 확정하지 못했으며 영구적인 유불리로 단정하지 않는다.

## 부산1200m를 실제200m씩 분해

{detail_table}

마지막 600m는 위 표의 마지막 세 구간 합이다. 마지막 400m도 직접 분리할 수 있다. 서울의 4C를 부산 G2F와 같은 400m 지점으로 바꾸지 않는다.

## 세 항목을 합친 동일 조건 예

포화·7월·정상 10두 편성 10번, 전체기간 이탈후미 제외 기준이다. 아래 합계는 새 직접 구간 후보의 합계다.

{example_table}

기본 분할과 세부 분할은 대안이므로 서로 합산하지 않는다. 기존 전체시간 함수율 보정 서울 80%·부산 90%는 유지하며 이 새 후보와 혼용하지 않는다. 운영 모델과 다음 경주 예측 개선 검증은 이번에 변경하지 않았다.
"""
    (HERE / "PUBLICATION.md").write_text(publication)
    methods = f"""
## 표본과 추정

서울과동일한고정모집단에서부산9거리{summary["population_rows"]:,}행을확인했다.기존모형대상6거리{summary["eligible_rows"]:,}행,4MAD후{summary["mad4_rows"]:,}행,이탈후미추가제외후{summary["tail25_rows"]:,}행이다.기본/세부분할·전체/2024년이후·정제전후{summary["models"]}모형,{summary["profiles"]:,}대비프로필을보존했다.최신전체DB로모집단을교체한것은아니다.

경주균등가중과마필고정효과,등급×연도·정확함수율·월1/2차주기함수·출전두수·경주조건·연령·중량·체중·rating·과거성적을통제했다.같은경주고정효과는함수율과월을흡수하므로넣지않았다.마필/날짜군집분산의이원및각단일대비분산중최대를쓴다.날짜별미관측환경과모든경주전략을제거한인과추정은아니다.

서울PLAN.md의지원기준과build.py의40/30/30%,n/(n+100),구간한도,중심화계산을그대로재사용했다.세부구간한도는월.06·게이트.08초이며기본구간의한도도동시에적용한다.같은프로필의공통배율로구간합정합성을유지했다.효과와시험가산의부호는반대다.원신뢰구간은축소전효과의불확실성이며합산후보의신뢰구간이아니다.

## 부산 월별 게이트별 후보 범위

각거리의지원되는블록최소～최대다.신뢰구간·실제기록범위가아니며게이트의서로다른출전두수블록을합쳤으므로한경주내최대격차로읽지않는다.

{range_table}

## 부산 세부 계측 정의

S1F는출발200m,G8F/G6F/G4F/G3F/G2F/G1F는결승전1600/1200/800/600/400/200m다.거리순서대로누적시간을뺀다.1300m의G6F는출발100m이므로START→G6F100m,G6F→S1F100m,S1F→G4F300m,G4F→G3F200m,이후200m씩이다.기본중반500m는S1F→G4F300m+G4F→G3F200m다.1400m·1800m에는400m묶음이남는다.전체거리를200m마다계측했다고표현하지않는다.

원천G8F가거리밖에기록된1300m12행은사용하지않았고없는G6F를복사하지않았다.누락과비단조행은checkpoint_exceptions.csv에원값을보존했다.세부분할완전사례제외와4MAD/이탈후미제외는별개다.

## 지역간 직접 대비

같은거리·기간의두지역에공통으로관측된함수율숫자만사용하고,두지역4MAD원경주의통합숫자분포를고정가중치로썼다.양쪽건조혼합도동일하다.common_moisture_mix.json에숫자·가중치·지역별관측범위를보존했다.한쪽상태가희소하면직접대비지원도False다.

부산−서울차이를각지역의선형대비영향함수로계산했다.지역별유한표본배율을적용하고,실제공유마필과달력날짜에서점수합을합쳐교차공분산을포함했다.같은지역모형의대비벡터가식별되는지확인했다.월주기곡선과정상10/12두같은게이트번호도직접비교했다.기간×구간×항목별BH q를보존했다.서로다른거리/구간의효과를독립능력으로합산하지않는다.

지역별시험후보차이는venue_candidate_comparison.csv,공통함수율구성의축소전공식차이는venue_raw_direct_contrasts.csv다.축소크기·함수율분포·후미제외·경주및마필구성이달라둘의크기순서가반대일수있다.지역별모형에조건을넣어도출전능력분포가완전히동일해진비교는아니다.

## 검증과 산출물

보관공식API{summary["raw_verification"]["rows"]:,}행·계측값{summary["raw_verification"]["checkpoint_cells"]:,}개를전수대조했고불일치0개였다.전체{verification["models_checked"]}모형과후보{verification["candidate_rows_checked"]:,}행의분할합·추정치·신뢰구간·중심화를확인했다.마필더미를명시한독립가중최소제곱{len(verification["independent_explicit_dummy_solves"])}회최대차이는{verification["max_explicit_contrast_error"]:.3g}초다.기존부산공동추정원효과의공통프로필차이도{verification["legacy_joint_max_error"]:.3g}초였다.지역직접대비{verification["direct_venue_contrasts_checked"]:,}개를검사하고6개대표대비의마필/날짜/교차군집분산을독립재계산했다.잘못된입력{verification["invalid_requests_rejected"]}종도거부했다.

기본표는core_moisture_table.csv,월표month_primary.csv,게이트gate_primary.csv,세부표detail_primary.csv다.원효과·지원·CI·q는effect_profiles.csv,전체/최근·정제민감도는correction_components.csv와tail_sensitivity.csv,공통숫자비교는common_moisture_raw_comparison.csv다.모형계수·검증·원천해시·조회apply.py·게시준비web_research.json도같은폴더에보존한다.웹게시/배포는하지않았다.

재현순서:analyze.py→build.py→compare.py→verify.py→report.py.프로젝트.venv/bin/python,PYTHONDONTWRITEBYTECODE=1,OPENBLAS_NUM_THREADS=1사용.기존서울파일·운영DB·모델은읽기전용이다.
"""
    (HERE / "README.md").write_text(publication + methods)
    (HERE / "SOURCES.md").write_text("""# 부산 구간 보정과 서울 비교 출처

2026-10-13.기존검증원천을읽기전용으로사용했다.

1.20261007_sex_ability_gap/outputs/population.parquet:2018년이후서울/부산고정모집단.
2.20261002_gate_lateral_bias/outputs/runners.parquet:원출전명단·번호·게이트순번.
3.20261008_record_normalization_seconds와20261008_detached_tail_sensitivity:고정이상치/이탈후미표식.
4.thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb의section_measurements_api:누적시간과API원본경로/행번호.
5.20260929_calendar_api_v1/raw/race_execution_probe의2018~2026meet_3.json.gz:62,831행전수대조.원천별SHA-256은outputs/summary.json.
6.20261011_seoul_section_corrections:서울계측연결·계수·모형·후보·고정보정정책.이전서울파일은변경하지않았다.
7.20261008_environment_correction_atlas및선행모형코드:지원기준·통제변수·군집분산.
8.docs/SECTION_POINT_LOAD_PLAN_2026-09-24.md:부산펄롱/누적/막판구분.공식참조는https://race.kra.co.kr/raceScore/cornerRecordDesc.do 및https://race.kra.co.kr/chulmainfo/RacingcourseStructure.do?Act=02&Sub=10&meet=3.

이번새웹수집은없다.원천은숫자크기추정이아닌cumulative_time과bu*AccTime필드로구분했다.입력파일및재사용서울파일해시를summary.json에보존했다.
""")
    B.dump(
        OUT / "web_research.json",
        dict(
            title="부산 구간 환경 보정과 서울 비교",
            updated_on="2026-10-13",
            data_end=summary["end"],
            status="trial_only",
            publication=publication,
            production_changed=False,
            prediction_validation=False,
            primary_components=records(primary),
            definitions=records(pd.read_csv(OUT / "section_definitions.csv")),
            coverage=records(pd.read_csv(OUT / "coverage.csv")),
            moisture_comparison=records(comparison),
            month_gate_ranges=records(ranges),
            raw_common_moisture_comparison=records(common_raw),
            examples=examples,
        ),
    )
    B.dump(
        OUT / "report_summary.json",
        dict(
            primary_components=len(primary),
            primary_available_components=int(primary.available.sum()),
            figure="busan_seoul_sections.png",
            busan1200_saturated_effect=float(r1200.busan_effect),
            seoul1200_saturated_effect=float(r1200.seoul_effect),
            same_numeric_mix_difference=float(r1200.busan_minus_seoul),
        ),
    )
    print("Busan reports and Seoul comparison saved")


def chart(primary, seoul):
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), constrained_layout=True)
    for offset, label, f in [
        (-0.18, "서울", seoul),
        (0.18, "부산", primary[primary.scope.eq("core")]),
    ]:
        z = f[f.distance_m.eq(1200) & f.family.eq("moisture") & f.level.eq("포화")].set_index(
            "section"
        )
        axes[0].bar(np.arange(4) + offset, z.loc[B.CORE, "add_seconds"], 0.36, label=label)
        m = f[f.distance_m.eq(1200) & f.family.eq("month") & f.section.eq("middle1")].copy()
        m["month"] = m.level.astype(int)
        m = m.sort_values("month")
        axes[2].plot(m.month, m.add_seconds, marker="o", label=label)
    axes[0].set_xticks(np.arange(4), ["초반200", "중반400", "후반400", "막판200"])
    axes[0].set_title("1200m 포화 함수율 시험값")
    axes[0].set_ylabel("가산초 · 지역별 혼합과 표본 축소 포함")
    axes[0].legend()
    d = primary[
        primary.scope.eq("detail")
        & primary.distance_m.eq(1200)
        & primary.family.eq("moisture")
        & primary.level.eq("포화")
    ].set_index("section")
    axes[1].bar(np.arange(6), d.loc[B.partition(1200), "add_seconds"], color="#33858a")
    axes[1].set_xticks(
        np.arange(6),
        ["0–200", "200–400", "400–600", "600–800", "800–1000", "1000–1200"],
        rotation=35,
    )
    axes[1].set_title("부산1200m 실제200m 분할 · 포화")
    axes[1].set_ylabel("시험 가산초")
    axes[2].set_title("1200m 중반400m 월별 시험값")
    axes[2].set_xticks(range(1, 13))
    axes[2].set_xlabel("월")
    axes[2].set_ylabel("가산초 · 12개월 평균 대비")
    axes[2].axhline(0, color="#555", linewidth=0.7)
    axes[2].legend()
    fig.suptitle("전체기간 · 4MAD와 이탈후미 제외 · 연구 후보 · 지역차 확정과 구분")
    fig.savefig(OUT / "busan_seoul_sections.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
