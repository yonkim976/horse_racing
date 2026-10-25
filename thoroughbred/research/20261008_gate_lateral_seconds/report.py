# ruff: noqa: E501
"""Publish conditional time differences and the unchanged correction decision."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
CENTRAL = HERE.parent / "conclusions/04C_GATE_LATERAL_SECONDS.md"


def table(d):
    def value(x):
        if pd.isna(x):
            return "미지원"
        if isinstance(x, (float, np.floating)):
            return f"{x:+.3f}" if x != 0 else "0"
        return str(x).replace("|", "\\|")

    lines = ["| " + " | ".join(d.columns) + " |", "|" + "---|" * len(d.columns)]
    lines.extend(
        "| " + " | ".join(value(x) for x in row) + " |"
        for row in d.itertuples(index=False, name=None)
    )
    return "\n".join(lines)


def main():
    assert json.loads((OUT / "verification.json").read_text())["passed"]
    summary = json.loads((OUT / "summary.json").read_text())
    d = pd.read_csv(OUT / "seconds_profiles.csv", dtype={"level": str})
    gate = []
    for meet, distance, block, level in [
        ("서울", 1600, "exact10", "10"),
        ("부산", 1600, "exact12", "1"),
        ("부산", 1400, "exact12", "1"),
    ]:
        g = d[
            d.kind.eq("gate")
            & d.meet.eq(meet)
            & d.distance_m.eq(distance)
            & d.block.eq(block)
            & d.level.eq(level)
            & d.family.eq("number")
            & d.adjustment.eq("dual")
        ].set_index("period")
        a, b = g.loc["all_mad4"], g.loc["recent_mad4"]
        gate.append(
            {
                "지역·거리·조건": f"{meet}{distance}m·{block[5:]}두·{level}번",
                "전체 차이초": a.effect_seconds,
                "최근 차이초": b.effect_seconds,
                "전체q": f"{a.q:.4f}",
                "최근q": f"{b.q:.4f}",
                "기본 추가보정초": 0,
            }
        )
    gate = pd.DataFrame(gate)
    gate.to_csv(OUT / "gate_focus_table.csv", index=False)
    lateral = []
    for meet, point, block in [
        ("서울", "3C", "triple"),
        ("서울", "4C", "pair"),
        ("서울", "G1F", "triple"),
        ("부산", "G4F", "triple"),
        ("부산", "G1F", "pair"),
    ]:
        g = d[
            d.kind.eq("lateral")
            & d.meet.eq(meet)
            & d.point.eq(point)
            & d.distance_m.eq(0)
            & d.block.eq(block)
            & d.level.eq("outer-inner")
            & d.metric.eq("finish")
        ].set_index("period")
        a, b = g.loc["all_mad4"], g.loc["recent_mad4"]
        lateral.append(
            {
                "지역·지점·마군": f"{meet} {point} {'2두' if block == 'pair' else '3두이상'}",
                "전체 외측−내측초": a.effect_seconds,
                "전체95%": f"[{a.ci_low:+.3f},{a.ci_high:+.3f}]",
                "최근 외측−내측초": b.effect_seconds,
                "전체q": f"{a.q:.5g}",
                "최근q": f"{b.q:.4f}",
            }
        )
    lateral = pd.DataFrame(lateral)
    lateral.to_csv(OUT / "lateral_focus_table.csv", index=False)
    pooled = d[d.kind.eq("lateral") & d.distance_m.eq(0)]
    pooled.to_csv(OUT / "pooled_lateral_seconds.csv", index=False)
    opening = """**같은 경주와 같은 말을 통제해도 게이트·주행위치의 시간 차이는 일부 남았다. 그러나 최근 자료와 여러 비교를 함께 고려한 사전 규칙에서 고정 게이트 보정 후보는0개였고, 실제 내외측도 자동 시간 보정은 보류한다.** 기존 함수율 기준과 월별 소액 후보를 유지하며 이번에 새 계수를 채택하지 않는다. 다음 경주 예측 성능은 평가하지 않았다.

게이트는 같은 경주 안에서 비교해 경주 전체의 함수율·월·등급·전개 공통 영향을 통제했다. 실제 위치는 같은 마군 안에서 비교했다. 두 분석 모두 같은 말의 반복 출전과 중량·체중·레이팅·이전 성적 등을 조정했다. 이는 과거에 관측된 조건부 시간 차이이며 무작위 배정이나 실제 경로 길이의 측정은 아니다.
"""
    gate_text = """## 게이트의 초 단위 차이와 보정 판단

아래는 정확히 마번1~10 또는1~12가 모두 있는 경주에서 같은 두수의 평균 게이트 대비 완주시간 차이다. 양수는 느린 기록 방향이며 보정한다면 차감 방향이다. 관찰 차이를 그대로 보정초로 사용하지 않는다. 최근은2024년 이후이며 전체기간에 포함된다.
"""
    gate_explain = """서울1600m10번의 전체95% 구간은+0.209~+0.773초, 최근은+0.246~+0.913초였다. 각각의 점별 구간은0을 넘지만 최근 번호별 다중비교q=0.0648로 미리 정한0.05 기준을 넘지 못했다. 완결2024~2025년의 차이+0.349초 구간은−0.108~+0.806초였다. 동일 경주만 통제한 보조모형은 전체+0.401초·최근+0.428초였다. 방향은 유지되지만 모형·기간에 따라 크기와 불확실성이 달라진다.

부산1600m12두1번은 전체+0.461초(95%+0.256~+0.667),최근+0.608초(+0.152~+1.063)였다. 부산1400m12두1번도 전체+0.315초·최근+0.503초의 느린 방향이었다. 하지만 최근 번호별q는 각각0.2764·0.0648이었다. 전체기간 주모형에서는 번호4개·그룹20개가q<0.05였지만 최근에는 번호·그룹 모두0개였다. 여러 거리·두수를 함께 비교한 범위에서의 판단이다.

이전100출전 기준은 유지했다. 이번에는50~99출전 셀도 별도B등급 탐색 대상으로 넣고, 같은 경주+마필의 다섯 표본·직전 마필 모형의 다섯 표본·경주만 통제한 두 표본의 방향을 대조했다. 이 확장은 이전 결과를 알고 설계한 탐색이며 기존 보류 셀의 확증적 승격이 아니다. 표본 연속 수축n/(n+100),95% 하한의50%,A0.15초/B0.05초 상한까지 정했지만 전체·최근의q<0.05 조건을 함께 넘은 셀이 없어 최종 증거 추가량은 모두0이다. 후보가 생기면 같은 두수 평균0으로 중심화할 구조와 표도 보존했다.
"""
    lateral_text = """## 같은 마군 안의 내외측과 완주시간

아래는 전체거리 통합의 외측−내측 차이다. 양수는 외측이 느린 방향,음수는 외측이 빠른 방향이다. 지역·지점마다 별도 모형이며 같은 말×거리와 같은 마군을 통제했다. 2두와3두 이상의 계수도 구분했다.
"""
    lateral_explain = """서울3C의3두 이상 마군에서는 외측이 내측보다 약0.30초 느린 차이가 관찰됐다. 서울G1F에서는 반대로 외측이 약0.14초 빨랐다. 부산G4F의3두 이상 외측은 약0.20초 느린 방향이었다. 이는 전체거리 평균의 조건부 연관이며 모든 거리·말에 같은 양을 적용할 근거가 아니다. 정확거리 표를 함께 보존했다.

최근 자료의 점추정 방향이 유지되는 셀이 있어도 이번 기간별 전체 비교에서 최근 내외측 대비는q<0.05가0개였다. 전체기간에는 완주시간36대비·남은 시간17대비가남았다. 전체거리와 정확거리·세 대비를 함께 검정한 범위이며, 일부 점별95% 구간이0을 넘는 결과와 구분해야 한다. 효과가 없다는 증명이나 최근 편향의 확정은 아니다.

막판 외측의 빠른 시간에는 추월 경로 선택·남은 힘·당일 상태가 포함될 수 있다. 상대 위치는 레일부터 몇 미터인지와 무관하며 마군에 속하게 된 과정도 선택의 결과다. 코너 외측의+0.30초를 그대로 빼거나 막판 외측의−0.14초만큼 시간을 더하면 말의 능력·전개까지 지울 수 있다. 서로 다른 지점의 값을 합산하지 않는다. 실제 내외측의 기본 자동 보정은0초로 보류하고 전개 설명용 시간표로 보존한다.
"""
    remaining = """## 통과 이후 남은 시간의 비교

계측 구간이 확인된 지점에서는 최종시간 외에 남은 시간도 같은 표본으로 비교했다. S1F는완주−초반200m,G1F는마지막200m,부산G3F는마지막600m다. 서울4C는기존 계측값이 있는1200m·2024년 이후만 사용했다. 부산G4F와서울3C의미계측 남은 시간을 임의로 생성하지 않았다.

서울G1F의3두 이상 외측−내측은 마지막200m에서 전체−0.146초(95%−0.192~−0.099),최근−0.136초(−0.236~−0.035)였다. 전체q<0.05였지만 최근q=0.411로 다중비교 후 미확정이었다. 막판 실제 위치를 당시 이후의 능력과 분리하는 문제는 이 비교에도 남는다.

서울1200m4C의최근2두 마군은 외측−내측 최종시간+0.279초,4C 이후 남은 시간+0.261초였다. 남은 시간의95%는+0.072~+0.449초였지만q=0.234였다.5,154출전마×지점·2,274마군·743경주 표본이며 마군에 속하지 않은 모든 서울1200m 출전의 평균이 아니다. 다른 거리의4C 이후나 마지막600m로 대체하지 않는다.
"""
    methods = """## 자료와 방법과 한계

자료 종료는 서울2026-09-20·부산2026-09-18이다. 기존151,074출전을 게이트 원천에 모두 연결하고 완주시간 일치를 확인했다. 직전 시간 연구에서 모형 지원된149,624출전만 재사용했다. 상대 위치 원천435,537행 중 연결 후 완결 마군431,274행·174,063마군을 확보했다. 연결 과정에서 비교 상대가 누락된 마군의98행을 제외했다. 직전4MAD 조건에서 이상치가 포함된 마군을 통째로 제외한 전체거리 주 표본은423,344출전마×지점·171,201마군이다. 지점이 겹치므로 고유 출전 수가 아니다.

게이트는경주 동일가중, 위치는경주 내마군 동일가중·마군 내위치 동일가중을 사용했다. 중간이 여러 말이면 그 위치의 합계 가중치를 끝말 한두의 위치 가중치와 같게 했다. 단독마에는 같은 마군 내 내외측 비교가 없으므로 포함하지 않는다. 마번은 취소 후 물리적 출발대의 대용값이며 그 이동을 독립 확인하지 않았다.

연결 성분마다 기준을 고정한 희소 가중 투영으로 두 고정효과를 함께 흡수했다. 나이·중량·마체중·레이팅·과거 성적/초반·경험·간격을 통제했고, 위치 모형에는 출발 게이트도 넣었다. 현재 착순·배당·주로빠르기·풍향·풍속은 입력에서 제외했다. 환경 보정의 인과효과와 당일 마필 상태를 완전히 분리한 모형은 아니다.

전체 무제외·4MAD·양끝5%·최근·완결연도의276모형과4,671프로필을 보존했다. 위치의정확거리에서는전체·최근·완결4MAD,전체거리에서는무제외·양끝5%도비교했다. 이상치 원장은 알려진 과거 전체자료로 만든 직전 연구의 경계를 유지해 시간순 예측 검증이 아니다. 전체와 최근 표본도 겹친다.

마필·경주일 이원 군집 점별95% 구간과 기간×분석×지표×대비가족별BH를 사용했다. 결합 분산이 단일 군집보다 작은 경우 더 큰 분산을 사용했다. 모형 지원과 계수 식별 여부를 분리했다. 미식별·미지원 행의 수치와구간은 적용에 쓰지 않는다. 정확거리와 전체거리 및 겹치는 구간은 독립 증거가 아니며 날짜·주말의 동적 초 보정을 새로 만들지 않았다.

별도의 명시적 희소 최소제곱23개,공분산12개,가중치·마군17개 표본을 대조했다.4,671프로필의계수·구간·BH,554게이트후보,438두수별중심화행과 입력해시를 확인했다. 실제 위치는 관찰된 결과 변수이므로 경주 전 예측 입력으로 사용할 수 없다. 연구용 기록 비교량의 탐구이며 새 보정 채택·운영 반영·다음 경주 예측 검증은 없다.
"""
    links = """## 자료와 검증

- [계산 전 계획](PLAN.md) · [출처](SOURCES.md) · [게시 요약](PUBLICATION.md)
- [게이트 주요표](outputs/gate_focus_table.csv) · [내외측 주요표](outputs/lateral_focus_table.csv)
- [전체 초 단위 프로필](outputs/seconds_profiles.csv) · [전체거리 내외측](outputs/pooled_lateral_seconds.csv)
- [게이트 후보·보류](outputs/gate_correction_candidates.csv) · [두수별 적용 조회표](outputs/field_gate_lookup.csv) · [내외측 지원](outputs/lateral_coverage.csv)
- [모형과 입력 해시](outputs/summary.json) · [독립 검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json)
"""
    title = "# 게이트와 상대 주행위치의 완주시간 차이\n\n2026년10월8일. 기록 보정량 후속 탐구. 새 계수 채택 없음.\n\n"
    main = (
        title
        + opening
        + "\n"
        + gate_text
        + "\n"
        + table(gate)
        + "\n\n"
        + gate_explain
        + "\n![게이트 시간 차이](outputs/gate_seconds_focus.png)\n\n"
        + lateral_text
        + "\n"
        + table(lateral)
        + "\n\n"
        + lateral_explain
        + "\n![지점별 내외측 시간 차이](outputs/lateral_seconds_by_point.png)\n\n"
        + remaining
        + "\n"
        + methods
        + "\n"
        + links
    )
    (HERE / "README.md").write_text(main)
    (HERE / "PUBLICATION.md").write_text(
        title
        + opening
        + "\n"
        + gate_text
        + "\n"
        + table(gate)
        + "\n\n"
        + lateral_text
        + "\n"
        + table(lateral)
        + "\n\n"
        + lateral_explain
        + "\n서울1600m10번은 전체·최근 느린 방향이지만 보수적인 다중비교 조건을 통과하지 못했다. 기록에서 관찰 차이를 그대로 차감하지 않고 기존 함수율 기준과 월 소액 후보를 유지한다. [방법과 지원](README.md) · [검증](outputs/verification.json).\n"
    )
    (HERE / "SOURCES.md").write_text("""# 게이트와 상대 주행위치 시간 연구의 출처

- [기존151,074출전](../20261007_sex_ability_gap/outputs/population.parquet):마필·등급·중량·체중·과거 이력·전체와구간시간.
- [151,115출전 게이트](../20261002_gate_lateral_bias/outputs/runners.parquet):마번·취소 후두수·게이트그룹. 전체시간 일치를 대조했다.
- [2두 이상 상대위치](../20261003_joint_gate_lateral_smoothing/outputs/observations.parquet):435,537출전마×지점. 상대위치의 기존 파싱·마군 정의를 유지했다.
- [직전 시간 연구 원장](../20261008_record_normalization_seconds/outputs/runner_normalization_candidates.parquet) · [프로필](../20261008_record_normalization_seconds/outputs/joint_seconds_profiles.csv) · [코드](../20261008_record_normalization_seconds/analyze.py):149,624출전의이상치 기준과 마필모형 민감도. 원 기준을 바꾸지 않았다.
- [서울1200m4C계측](../20261004_seoul4c_finish/outputs/runner_4c_analysis.parquet):2024년이후7,897행의실제4C 이후시간을 해당 표본에만 연결했다.
- [계획](PLAN.md) · [계산](analyze.py) · [독립대조](verify.py) · [입력해시](outputs/summary.json) · [검증](outputs/verification.json).

새DB조회·외부자료 수집·풍향·풍속·주로빠르기 추가는 없다. 미계측 경로 길이·잔여거리 시간을 생성하지 않았다. 원 연구와운영모형·보정 채택은 변경하지 않았다.
""")
    central = (
        title
        + opening
        + "\n"
        + gate_text
        + "\n"
        + table(gate)
        + "\n\n"
        + gate_explain
        + "\n"
        + lateral_text
        + "\n"
        + table(lateral)
        + "\n\n"
        + lateral_explain
        + "\n"
        + remaining
    )
    central += f"\n276모형·4,671프로필의후향 조건부 비교다. 실제 위치는 경로 길이나 환경 인과효과가 아니며 미지원·미식별 셀은 적용하지 않는다. 이전100출전 기준과 새50~99 탐색 등급을 구분했다.\n\n[원 보고서와 한계](../{HERE.name}/README.md) · [계획](../{HERE.name}/PLAN.md) · [출처](../{HERE.name}/SOURCES.md) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [검증](../{HERE.name}/outputs/verification.json) · [용량](../{HERE.name}/outputs/artifact_inventory.json)\n"
    CENTRAL.write_text(central)
    payload = {
        "as_of": "2026-10-08",
        "data_end": {"서울": "2026-09-20", "부산": "2026-09-18"},
        "status": "conditional_seconds_no_new_correction_adopted",
        "summary": summary,
        "gate_focus": json.loads(gate.to_json(orient="records")),
        "lateral_focus": json.loads(lateral.to_json(orient="records")),
        "profiles": json.loads(d.to_json(orient="records")),
        "gate_candidates": json.loads(
            pd.read_csv(OUT / "gate_correction_candidates.csv").to_json(orient="records")
        ),
        "field_lookup": json.loads(
            pd.read_csv(OUT / "field_gate_lookup.csv").to_json(orient="records")
        ),
    }
    (OUT / "web_gate_lateral_seconds.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    print("Reports and publication payload saved.")


if __name__ == "__main__":
    main()
