# ruff: noqa: E501
"""Publish normalization amounts without claiming predictive improvement."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
CENTRAL = HERE.parent / "conclusions/04B_RECORD_NORMALIZATION_SECONDS.md"


def table(frame):
    def value(x):
        if pd.isna(x):
            return "보류"
        if isinstance(x, (float, np.floating)):
            return f"{x:+.2f}" if x != 0 else "0"
        return str(x).replace("|", "\\|")

    lines = ["| " + " | ".join(frame.columns.astype(str)) + " |", "|" + "---|" * len(frame.columns)]
    lines.extend(
        "| " + " | ".join(value(x) for x in r) + " |"
        for r in frame.itertuples(index=False, name=None)
    )
    return "\n".join(lines)


def main():
    assert json.loads((OUT / "verification.json").read_text())["passed"]
    summary = json.loads((OUT / "summary.json").read_text())
    c = pd.read_csv(OUT / "conservative_candidates.csv", dtype={"level": str})
    m = c[c.kind.eq("month")].copy()
    m["month"] = m.level.astype(int)
    focus = m[m.candidate_nonzero].groupby(["meet", "distance_m"]).size().index
    p = m.set_index(["meet", "distance_m"]).loc[list(focus)].reset_index()
    monthly_table = p.pivot(
        index=["meet", "distance_m"], columns="month", values="candidate_add_seconds"
    ).reset_index()
    monthly_table = monthly_table.rename(
        columns={"meet": "지역", "distance_m": "거리m", **{i: f"{i}월" for i in range(1, 13)}}
    )
    monthly_table.to_csv(OUT / "monthly_candidate_table.csv", index=False)
    sensitivity = m[
        [
            "meet",
            "distance_m",
            "month",
            "all_mad4_effect",
            "recent_mad4_effect",
            "candidate_add_seconds",
        ]
    ].copy()
    for rate in [0.25, 0.5, 0.75]:
        sensitivity[f"full_effect_fraction_{int(rate * 100)}_add"] = (
            -rate * sensitivity.all_mad4_effect
        )
    sensitivity.to_csv(OUT / "monthly_scale_sensitivity.csv", index=False)
    main = """**기록 비교용 보수적 초안은 기존 함수율 보정을 유지하고, 일부 지역·거리·월에만 −0.11~+0.09초를 추가하는 방식이다. 게이트·실제 주행 내외측·날짜별 추가량은 기본 적용을 보류한다.** 다음 경주 예측 개선을 판정한 결과는 아니다.

월·게이트 입상률 %p를 시간으로 바꾸지 않고 완주시간 자체를 새로 분석했다. 같은 말의 반복 출전과 등급×연도·정확한 함수율·두수·중량·체중·레이팅·과거 이력 등을 통제해 월과 게이트를 같은 모형에서 추정했다. 통제한 말 특성 자체를 기록에서 차감하지 않는다.

기존 채택 범위의 건조 기준 함수율 보정초에 아래 월 추가초를 더한다. 양수는 빨라 보이는 기록에 시간을 더하고, 음수는 느려 보이는 기록에서 시간을 뺀다는 뜻이다. 0은 이번 규칙에서 추가 적용을 보류했다는 뜻이며 환경 차이의 부재가 아니다. 아래 표는 연구 후보로 현재 채택 기준을 바꾸지 않는다.
"""
    amounts = """## 월별 추가량을 작게 잡은 근거

전체기간4MAD 모형에서 서울1200m는 연간 평균 대비1월+0.28초·9월−0.23초, 부산1400m는1월+0.38초·8월−0.29초였다. 최근2024년 이후 부산1400m는 각각+0.78초·−0.65초로 크기가 커졌다. 방향이 같아도 보정량이 기간에 따라 달라 전량 적용을 권하지 않는다. 앞선 겨울 대비 월 차이와 이번 연간 평균 대비 차이는 기준과 통제가 다르므로 같은 수치가 아니다.

단순25%·50%·75% 적용표를 함께 보존했다. 권장 초안은 점추정의 절반보다 더 보수적이다. 전체·최근95% 구간에서0에 가까운 끝 중 작은 절댓값의50%만 남기고, 다섯 민감도 모두의 표본 지원·같은 방향 및 전체·최근 BH q<0.05를 요구했다. 월±0.30초·게이트±0.20초 상한과0.01초 단위0 방향 버림을 계산 전에 정했다. 실제 월 후보는−0.11~+0.09초로 상한에 닿지 않았다. 정책적 완화 규칙이며 최적량을 데이터가 증명한 것은 아니다.

월168셀 중35셀이0이 아닌 후보로 남았으며 서울1200·1300·1400·1800m, 부산1200·1400m에 해당한다. 다른 거리로 복제하지 않는다. 원래 월 네 항 곡선은12개월 평균0이나 선별·버림한 최종 추가표는 평균0을 강제하지 않았다. 지역·거리별 월 동일가중 평균의 이동은 최대0.0134초다. 엄밀한 연간 기준점을 유지하려면 이후 전체 곡선의 수축 방식을 별도로 정해야 한다.
"""
    gate = """## 게이트와 실제 내외측의 적용량

보수적 규칙을 통과한 게이트 번호·그룹 추가초는0개다. 이는 게이트의 시간 효과가 없다는 결론이 아니다. 서울1600m 정확10두의10번은 같은 두수 평균 대비 전체4MAD+0.517초(95%+0.238~+0.796,q=0.035), 최근+0.627초(+0.287~+0.967,q=0.017)로 느린 방향이었다. 무제외+0.339초·양끝5% 제외+0.381초·완결2024~2025년+0.381초로 방향은 유지됐다. 그러나 완결2년의10번은92출전으로 사전100출전 지원 기준을 넘지 못했다. 임계값을 결과에 맞춰 낮추지 않고 우선 별도 관찰 대상으로 남긴다.

부산1600m 정확12두의1번도 전체4MAD+0.473초(95%+0.262~+0.684,q=0.0028)로 느린 차이가 남았지만 최근 번호별 다중비교에서는 확정 차이로 남지 않았다. 한 번호의 결과를 같은 내외측 모든 번호에 적용하지 않는다. 집단·번호·두수별 기준을 유지한다.

실제 내외측은 같은 마군 안의 상대 순서이며 레일부터의 거리나 추가 주행미터가 아니다. 막판 외측에는 추월·남은 힘·말의 상태가 포함된다. 이번의 월·게이트 시간 모형에 실제 위치를 넣어 능력과 함께 차감하지 않았다. 기본 추가 적용은0으로 보류하며, 날짜·주말·연월의 편차도 중복 가산하지 않는다. 날짜별 시간 효과는 새로 추정하지 않았다.
"""
    examples = """## 계산 사례

`후보 환산시간 = 원시 완주시간 + 기존 함수율 보정초 + 월 후보초 + 게이트 후보초`

- 서울1200m·9월·불량72.00초:72.00+1.034383+0.07=**73.10초**.
- 서울1200m·1월·양호72.00초:72.00−0.095185−0.07=**71.83초**.
- 부산1400m·8월·포화87.00초:87.00+0.681469+0.08=**87.76초**.

게이트는 이번 초안에서 추가0이다. 원시 기록을 보존하고 함수율·월·게이트 기여를 별도 열로 둔다. 함수율 기준이 보류된 셀은 종합 환산시간도 비워 두었다. 1000m·2000m의 월·게이트 추정이 존재해도 기존 함수율 채택 범위가 아니므로 종합 후보를 제공하지 않는다. 구간기록에는 전체시간 보정을 배분하거나 복제하지 않는다.
"""
    methods = """## 자료와 검증 범위

서울2018-01-06~2026-09-20·부산2018-01-05~2026-09-18의151,074출전을 기존 게이트 모집단에 모두 연결했고 완주시간이 정확히 일치했다. 구간 품질 때문에 게이트 원천보다41행 적다. 19지역×거리 중14개를 적합해149,624출전·13,792경주·지역별 날짜1,580개를 분석했다. 희소1900·2200·2300m 등은 미지원이며 최근1000m·서울2000m는 적합 표본이 부족하다.

마필 고정효과와 경주 동일가중을 사용했다. 정확 마번1~10/1~12 경주는 번호별, 나머지는 취소 후 마번순 세 그룹을 두수 구간별로 추정했다. 물리적 출발대 이동을 독립 확인한 것은 아니다. 월은 연간1·2차 사인·코사인 네 항이다. 정확 함수율을 범주형 통제해 월·게이트 계수는 기존 함수율 오프셋 유무에 불변이었다. 현재 착순·배당·주로빠르기·풍향·풍속은 입력에서 제외했다.

초기 전체기간 모형 잔차로4MAD 밖1,286행(0.86%)을 제외했고, 양끝5% 제외15,157행을 민감도로 비교했다. 이 초기 잔차와 제외 기준은 후향 전체기간에서 만들었으므로 시간순 예측 검증으로 해석하지 않는다. 무제외·4MAD·양끝5%·최근2024년 이후·완결2024~2025년64모형을 비교했다. 전체와 최근 표본은 겹치므로 독립된 재현 실험도 아니다.

마필·경주일 이원 군집 점별95% 구간과 각 기간의 월·번호·그룹별 별도 BH를 사용했다. 지원 조건과 모형 통제를 바꾸면 결과가 달라질 수 있고, 경주 전개·주로 관리·마필 상태를 모두 측정한 인과효과는 아니다. 군집 추론은 긴 시계열 의존성을 완전히 제거하지 못한다. 여러 모형을 거친 최종 후보량의95% 보장을 뜻하지 않는다.

별도 최소제곱64개·군집 공분산14개·함수율 오프셋 불변14개와3,256개 프로필·722개 후보 규칙을 검증했다. 종합 환산은 기존 함수율 지원133,223출전에서만 생성했다. 알려진 과거 전체자료로 만든2026년 연구용 참고표이며 이전 경주 당시 이용할 수 있었던 계수는 아니다. 다음 경주 예측 개선 검증은 사용자 요청대로 뒤로 두었다. 기존 보정 채택·거리 기준표·원천 DB·운영 모델을 변경하지 않았다.
"""
    links = """## 자료와 검증

- [계산 전 계획](PLAN.md) · [출처](SOURCES.md) · [게시 요약](PUBLICATION.md)
- [월 추가초 표](outputs/monthly_candidate_table.csv) · [적용률 민감도](outputs/monthly_scale_sensitivity.csv)
- [모든 초 단위 계수와 구간](outputs/joint_seconds_profiles.csv) · [보수적 후보와 보류](outputs/conservative_candidates.csv)
- [거리별 지원](outputs/distance_coverage.csv) · [보존한 함수율 기준](outputs/moisture_reference_preserved.csv)
- [출전별 환산 후보](outputs/runner_normalization_candidates.parquet) · [입력 해시](outputs/summary.json)
- [독립 검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json)
"""
    title = "# 함수율 월 게이트를 반영한 완주시간 보정량\n\n2026년 10월 8일. 기록 비교용 후보 연구이며 새 보정 채택은 아니다.\n\n"
    readme = (
        title
        + main
        + "\n"
        + table(monthly_table)
        + "\n\n단위는 원시시간에 더할 초다.0은 추가 적용 보류다.\n\n![월별 추가량](outputs/monthly_candidate_seconds.png)\n\n"
        + amounts
        + "\n![전체기간과 최근의 월별 관찰 차이](outputs/monthly_observed_seconds.png)\n\n"
        + "\n"
        + gate
        + "\n"
        + examples
        + "\n"
        + methods
        + "\n"
        + links
    )
    (HERE / "README.md").write_text(readme)
    (HERE / "PUBLICATION.md").write_text(
        title
        + main
        + "\n"
        + table(monthly_table)
        + "\n\n"
        + examples
        + "\n"
        + "같은 말과 조건을 통제한 관찰 연구이며 월 추가량은 보수적 정책 후보다. 게이트·실제 내외측은 기본 적용을 보류했다. 예측 개선이나 공식 능력등급을 뜻하지 않는다. [방법과 한계](README.md) · [검증](outputs/verification.json).\n"
    )
    (HERE / "SOURCES.md").write_text("""# 기록 보정량 연구의 출처

- [기존 성별 연구 모집단](../20261007_sex_ability_gap/outputs/population.parquet):151,074출전, 마필ID·등급·체중·성별 편성·과거 이력·전체시간.
- [게이트 모집단](../20261002_gate_lateral_bias/outputs/runners.parquet):151,115출전, 마번·취소 후 두수·게이트 그룹. 동일 출전151,074개와 완주시간을 대조했다.
- [기존 함수율 참고표](../20261002_moisture_strength_selection/outputs/reference_seconds.csv)와 [채택 결정](../conclusions/01_TRACK_MOISTURE.md):서울80%·부산90%, 건조 기준. 기존 채택거리·상태 지원을 유지한다.
- [통합 설계](../conclusions/04A_TRACK_TOTAL_CORRECTION.md) · [월별 연구](../conclusions/23_MONTHLY_SAME_MOISTURE.md) · [게이트 전용 후속](../conclusions/03C_GATE_ONLY_FOLLOWUP.md):배경이며 입상률%p를 시간으로 환산하지 않았다.
- [계획](PLAN.md), [계산](analyze.py), [독립 대조](verify.py), [입력SHA256](outputs/summary.json), [검증](outputs/verification.json).

새 DB 조회·외부 웹 수집은 없었다. 원천 종료일과 기존 품질 계약을 유지했다. 실제 경로 길이·풍향·풍속·주로빠르기는 보정 입력이 아니다. 알려진 과거자료를 설명하는 연구용 참고량이다.
""")
    central = (
        title
        + main
        + "\n"
        + table(monthly_table)
        + "\n\n"
        + amounts
        + "\n"
        + gate
        + "\n"
        + examples
    )
    central += "\n마필 고정효과·경주 동일가중·정확 함수율·등급×연도 등 통제,전체·최근·완결연도·이상치 민감도를 함께 사용했다.149,624출전·13,792경주에서64모형을 검증했다. 시간순 사전 계수나 인과효과가 아니며 새 보정 채택과 운영 변경은 없다.\n"
    central += f"\n[원 보고서와 한계](../{HERE.name}/README.md) · [계획](../{HERE.name}/PLAN.md) · [출처](../{HERE.name}/SOURCES.md) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [검증](../{HERE.name}/outputs/verification.json) · [용량](../{HERE.name}/outputs/artifact_inventory.json)\n"
    CENTRAL.write_text(central)
    payload = {
        "as_of": "2026-10-08",
        "status": "retrospective_normalization_candidate_not_adopted",
        "summary": summary,
        "monthly_candidates": json.loads(monthly_table.to_json(orient="records")),
        "all_candidates": json.loads(c.to_json(orient="records")),
        "moisture_reference": json.loads(
            pd.read_csv(OUT / "moisture_reference_preserved.csv").to_json(orient="records")
        ),
        "actual_lateral_additional_application": "pending_zero",
        "gate_additional_application": "pending_zero",
    }
    (OUT / "web_record_normalization.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    print("Research, central conclusion and publication payload saved.")


if __name__ == "__main__":
    main()
