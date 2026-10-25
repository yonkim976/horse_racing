# ruff: noqa: E501
"""Generate evidence-linked reader reports from verified tables."""

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"


def table(d):
    def value(x):
        if pd.isna(x):
            return "보류"
        if isinstance(x, (float, np.floating)):
            return f"{x:.3f}"
        return str(x).replace("|", "\\|")

    rows = ["| " + " | ".join(map(str, d.columns)) + " |", "|" + "---|" * len(d.columns)]
    rows.extend(
        "| " + " | ".join(value(x) for x in row) + " |"
        for row in d.itertuples(index=False, name=None)
    )
    return "\n".join(rows)


def main():
    p = pd.read_csv(OUT / "matched_age_changes.csv")
    a = pd.read_csv(OUT / "age_profiles.csv")
    f = pd.read_csv(OUT / "inactivity_by_age.csv")
    t = pd.read_csv(OUT / "pre_inactivity_record_changes.csv")
    cov = pd.read_csv(OUT / "trend_coverage.csv")
    q = p[
        p.window.eq("all")
        & p.distance_m.eq(1200)
        & p.metric.eq("change_seconds")
        & p.match.eq("moisture")
        & p.age_from.between(2, 5)
    ]
    paired = table(
        q[["meet", "age_from", "age_to", "mean", "ci_low", "ci_high", "horses", "supported"]]
    )
    q = f[f.horizon_days.eq(365) & f.window.eq("all") & f.grouping.eq("age")]
    follow = table(
        q[
            [
                "meet",
                "age_bin",
                "rows",
                "no_start_count",
                "mean",
                "ci_low",
                "ci_high",
                "late_return_count",
            ]
        ]
    )
    q = t[
        t.horizon_days.eq(365)
        & t.window.eq("all")
        & t.age_bin.eq("all")
        & t.metric.eq("context_seconds_per60_change")
    ]
    trends = table(
        q[
            [
                "meet",
                "inactive",
                "rows",
                "mean",
                "ci_low",
                "ci_high",
                "not_worse_share",
                "worse_050_share",
            ]
        ]
    )
    methods = "기록"
    methods += """ 모집단은 서울·부산 실전 11거리의 2018년 이후151,074출전·13,928경주·12,435두다. 서울 종료일은2026-09-20,부산은2026-09-18이다. 기존 정상경주·구간 정합성 모집단을 그대로 사용했고 새 이상치 절사는 하지 않았다. 세부 곡선은100출전 이상인17개 지역×거리 조합에서 추정하며 희소 셀 지원은 별도다.

공식 출전 연령을 사용한다. 프로필 생일로 검증한151,074행 모두 `출전 연도−출생 연도=공식 연령`이 일치했다. 이는 생일이 지난 만 나이가 아니며, 같은3세 안의 월령 차이까지 정밀 추정한 결과가 아니다.

집단 곡선은 지역·거리별 연도×월×정확 함수율 고정효과, 당시 성별과 연령 범주를 함께 추정한다. 말×연령의 출전 가중치 합은1이다. 4세 대비 초로 표시하며8세 이상은 통합한다. 등급을 추가한 곡선은 다른 조건부 질문이다. 승급·rating·과거 성적이 성장 결과일 수 있어 주 곡선에서 제거하지 않았다. 부담중량·경험·훈련·세대 차이까지 분리한 생물학적 노화계수는 아니다. 말과 날짜의 이원 군집 분산과 단독 군집 분산 중 보수적 상한의 점별95%구간을 제공한다.

동일 말 비교는 같은 경마장·거리·달·정확 함수율에서 다음 해 연령+1을 매칭한다. 말×연령 전환마다 여러 셀을 평균한 뒤 같은 비중으로 집계한다. 함수율 구간 매칭,2022년 이후,2020~2021년 전환 제외를 민감도로 보존한다. 말·시작연도 군집 구간과 마필500회 재표집 구간을 구분한다. 30마필·3개 연도 미만은 소표본이다. 통합 거리 척도는 `시간 차이×60÷지역·거리 중앙시간`이며1200m 실제 초와 다르다.

출전 추적은2010년 이후 확정 실제 출발326,157행·22,250두를2026-09-18까지 읽었다. 정상 착순과91/92를 포함하고93/94/95 및해석 미확정0코드2행은 제외한다. 다른 거리·지역으로 옮긴 다음 출전도 확인했다. 서울·부산의2018~2024년 말별 연말 마지막 출전24,082건·10,666두가365일 관측을 충족한다. 730일 비교는완결2018~2023년20,749건으로 제한한다. 관측 종료에 가까운 말은 중단자로 처리하지 않는다.

중단 전 변화는 기준일 이전730일 내 정상 유효기록6회 이상인 경우 최근3회−그 이전3회로 계산한다. 2018년 이전 시간은 이 모집단에 없어 초기 연도의 이력 부족이 남는다. 지역·거리 중앙시간으로 맞춘 원시 척도와, 주 집단 모형의 연도·월·함수율 고정효과만 제거한 후향 척도를 함께 제공한다. 연령·성별·등급 효과는 빼지 않는다. 이 고정효과는 물리적 주로 영향만의 측정치가 아니며 기존 채택 함수율 보정표를 변경하지 않는다. 원시 지표와후향 지표 모두 중단 집단의 평균 악화 방향이다. 기록 6회 조건을 충족한 14,880건 중 후향 지표가 완전한 것은 14,790건이다. 전체 중단자의 정확한 마지막 6출전을 모두 관측한 결과가 아니므로 아래 가용성 표를 함께 읽는다.

결과를 본 뒤 마지막 실제 출전에도 유효 시간이 있는 조건으로 민감도를 추가했다. 무출전 집단의 하락하지 않은 비율은서울32.5%·부산30.9%로,주표의33.2%·32.4%와방향이같다. 이는 사후 보조 확인이며 독립검증은 아니다.
"""
    findings = """**2~4세의 성장 방향은 보이지만, 모든 말이 특정 나이에 정점을 찍고 일정한 초씩 하락한다는 기준은 아직 만들 수 없다.** 4세 전후 성장 둔화는 연구 출발점으로 삼을 수 있다. 고령까지 출전한 말의 집단 평균과 같은 말의 변화가 다르므로 출전 중단 선택을 함께 봐야 한다.

1200m의 같은 말·달·정확 함수율 비교에서 2→3세는 서울 −1.370초(41두), 부산 −1.011초(57두)다. 3→4세는 서울 −0.518초(95두), 부산 −0.770초(130두)다. 서울 3→4세의 95% 구간은 −1.040~+0.003초로 0을 포함한다. 4→5세는 서울 +0.090초·부산 +0.014초로 뚜렷한 변화가 없다. 5세 이후는 정확 매칭 표본이 급감하고 일부 구간 민감도에서 느린 방향이 나타나지만 보편적 하락률을 확정하지 않는다. 최근 기간·코로나 시기 제외에서 평균 크기와 불확실성이 달라져 전체 기간 값을 고정 보정으로 채택하지 않는다.

출전 집단의 1200m 곡선에서는 4세 대비 6세가 서울 −0.542초·부산 −0.313초로 오히려 빠르다. 같은 등급까지 고려하면 서울 +0.294초·부산 +0.502초로 방향이 바뀐다. 오래 남은 말의 능력 구성과 승급 차이가 중요하다는 신호이며, 이 차이를 생존 선택 하나의 인과효과로 분해한 것은 아니다.

2018~2024년 연말 마지막 출전 이후 365일 무출전율은 4세 서울 47.4%·부산 49.2%, 5세 56.7%·57.9%, 6세 63.0%·65.0%다. 높은 연령에서 잔존 관측이 줄어드는 경향은 2020~2021년 제외에서도 유지됐다. 365일 무출전 8,790건 중 294건은 이후 관측 종료 전에 복귀했다. 무출전은 영구 은퇴나 확정 퇴사와 같지 않다.

유효 기록 6회 이상인 무출전 집단의 최근 3회는 그 이전 3회보다 평균적으로 느렸다. 후향 환경 성분을 고려한 60초당 지표에서 서울 +0.351초·부산 +0.343초다. 그러나 서울 33.2%·부산 32.4%는 이 지표가 느려지지 않았다. 최종 출전에도 유효 기록이 있는 민감도에서도 약 3분의 1이다. **기록 하락을 보이지 않은 채 출전이 중단되는 사례는 있으나, 하락 전에 퇴사했다고 확정하거나 중단 이유를 능력으로 단정할 수 없다.** 부상·번식·매각·휴양·전환 등의 원인은 확인하지 않았다.
"""
    limits = """## 해석과 다음 능력 변화 연구

이번 곡선은 모든 등록마의 잠재 능력 곡선이 아니라 관측된 출전 기록의 평균이다. 같은 말 비교도 다음 연령까지 출전한 말에 한정된다. 퇴사 후 미관측 능력이나 중단하지 않았을 경우의 기록은 복원하지 않았다. 나이·연도·출생세대의 식별 문제 때문에 말 고정효과와 연도 고정효과를 동시에 넣어 순수 선형 노화효과를 구했다고 주장하지 않는다.

확정 퇴사·불용 정답은 이번 보유 코어에 없다. API8_2의 active/inactive 요청 목록으로 은퇴를 판정하지 않는다. 공식 마필종합 상세정보 API42는 등록·불용·입사·퇴사·휴양 정보의 제공을 설명하므로 다음 확인 경로가 되지만, 이번에 해당 원문을 전수 수집·검증하지 않았다. 마지막 퇴사일 하나도 영구 은퇴·일시 이동·재입사를 구분한 뒤 사용해야 한다.

개별 말 연구에서는 연령별 관측 경향을 작은 사전 기대값으로 삼고, 그 말의 최근 환경 보정기록·거리 적성·경험·중량·휴식·전개를 이용해 개별 변화가 평균에서 얼마나 벗어나는지 추정하는 방향이 적절하다. 이력이 적을 때만 평균 쪽으로 완화하고 현재 표의 초를 모든 말에게 일괄 가산하지 않는다. 학습용 연령곡선·환경계수는 평가시점 이전 자료로 다시 추정하고, 중단 라벨·후향 정규화값을 과거 예측 입력에 넣지 않는다.

새 성장·하락 보정률, 퇴사 예측기, 운영 모델 반영, 웹 구현·배포는 채택하지 않았다. 기존 함수율 서울 80%·부산 90%, 구간 보정 보류 및 거리별 기준은 유지한다.
"""
    links = """## 자료와 검증

- [계산 전 계획](PLAN.md) · [출처와 의미](SOURCES.md) · [상세 표](ALL_RESULTS.md)
- [원천 감사](outputs/source_audit.json) · [독립 검증](outputs/verification.json) · [보조 검증](outputs/supplement_verification.json)
- [전체 연령 곡선](outputs/age_profiles.csv) · [동일 말 변화](outputs/matched_age_changes.csv) · [출전 중단](outputs/inactivity_by_age.csv) · [중단 전 기록](outputs/pre_inactivity_record_changes.csv)
- [이력 가용성](outputs/trend_coverage.csv) · [최종 출전 유효 민감도](outputs/valid_final_start_sensitivity.csv)
- [게시용 요약](PUBLICATION.md) · [게시JSON](outputs/web_age_curve_exit.json) · [용량 명세](outputs/artifact_inventory.json)

검증은 원 모집단151,074행·생일/연령151,074행·구간합302,148건·SQL매칭6,080셀·말별전환5,162건·전환집계1,186행·코어 다음출전326,157행·연말기준24,082건·최근6기록14,790건을 대조했다. 별도희소더미 가중회귀144대비의최대오차는1.21e−10초미만이고,독립부분회귀로군집표준오차8개를확인했다. 기타집계516행과게시자료를검증했다.
"""
    readme = (
        "# 평균 연령 곡선과 출전 중단 전 기록 변화\n\n2026년 10월 7일 · 관찰 연구 완료 · 성장·하락 보정 미채택.\n\n"
        + findings
        + "\n## 같은 말의 1200m 연령 변화\n\n음수는 다음 해가 빠른 방향이다. 신뢰구간은 말·전환연도 군집 기준이다.\n\n"
        + paired
        + "\n\n![연령 곡선과 출전 중단](outputs/age_curve_and_inactivity.png)\n\n## 출전 중단 전 기록\n\n"
        + trends
        + "\n\ninactive=True는 이후 365일 무출전이다. not_worse_share는 최근 기록이 느려지지 않은 비율, worse_050_share는 60초당 0.5초를 초과해 느려진 비율이다.\n\n![중단 전 기록 변화](outputs/pre_inactivity_changes.png)\n\n## 대상과 방법\n\n"
        + methods
        + "\n"
        + limits
        + "\n"
        + links
    )
    (HERE / "README.md").write_text(readme)
    more = a[
        a.window.eq("all")
        & a.sex_group.eq("all")
        & a.part.eq("finish")
        & a.age.isin(["3", "5", "6"])
    ][
        [
            "meet",
            "distance_m",
            "specification",
            "age",
            "difference_seconds",
            "ci_low",
            "ci_high",
            "horses",
            "supported",
        ]
    ]
    pooled = p[p.window.eq("all") & p.distance_m.eq(0) & p.match.eq("moisture") & p.age_from.le(7)][
        ["meet", "age_from", "age_to", "mean", "ci_low", "ci_high", "horses", "supported"]
    ]
    (HERE / "ALL_RESULTS.md").write_text(
        "# 연령 곡선과 출전 중단 상세 표\n\n전체 CSV에는지원·민감도·성별·구간을포함한다. 아래는주요전체시간표다.\n\n## 1200m 동일 말 변화\n\n"
        + paired
        + "\n\n## 전 거리 통합 같은 말 변화\n\n단위는60초당초이며실제1200m초가아니다.\n\n"
        + table(pooled)
        + "\n\n## 거리별 집단 곡선\n\n4세대비초,context_grade는같은등급을추가한별도질문이다.\n\n"
        + table(more)
        + "\n\n## 연령별365일무출전\n\nmean은비율이며퇴사율이아니다.\n\n"
        + follow
        + "\n\n## 중단전변화\n\n"
        + trends
        + "\n\n## 관측이력 가용성\n\n"
        + table(cov)
        + "\n"
    )
    (HERE / "PUBLICATION.md").write_text(
        "# 말의 성장 곡선은 출전 중단과 함께 읽어야 한다\n\n"
        + findings
        + "\n![연령과출전중단](outputs/age_curve_and_inactivity.png)\n\n## 기록을 읽는 방법\n\n2~3세 말의 지난 기록과 4세 말의 지난 기록을 똑같은 현재 능력으로 고정하지 않는다. 반대로 6세라는 이유만으로 자동 감점하지 않는다. 연령 평균보다 그 말의 최근 여러 기록과 전개·거리 조건을 함께 확인한다. 예를 들어 6세 말이 최근 환경 보정 기록을 안정적으로 유지했다면, 연령 집단의 평균 하락 후보만으로 그 기록을 낮추지 않는다. 이 예시는 평가 원칙이며 새 보정 수치는 아니다.\n\n"
        + limits
        + "\n[전체보고서](README.md) · [출처](SOURCES.md) · [검증](outputs/verification.json)\n"
    )
    (HERE / "SOURCES.md").write_text("""# 연령 곡선과 출전 중단의 출처

## 고정 로컬 자료

- [기존 성별 연구 모집단](../20261007_sex_ability_gap/outputs/population.parquet):151,074행. 출전 당시 나이·성별·기록·함수율·등급·ID와 원문 포인터를 재사용한다. 기존 공통 백분위 점수는 사용하지 않는다.
- [코어DB](../../data/core_api_2010_20260929_v1/thoroughbred_core.duckdb):confirmed_runners와horse_profile_snapshot_membership를읽기전용조회. 실제출발추적과생일대조에만사용하며현재프로필성별·등급을과거에덮어쓰지않는다.
- [원천감사](outputs/source_audit.json):모집단SHA-256,코어추출해시,DB크기·수정시각,연령/생일일치,원시착순코드별수를보존한다.코어에는확정퇴사일·불용사유열이없고현재API8_2active/inactive요청범위는퇴사정답이아니다.
- [출전 추적 원장](outputs/observed_starts.parquet) · [연말 기준 원장](outputs/annual_followup_landmarks.parquet) · [정확 매칭 셀](outputs/matched_transition_cells.parquet).

## 외부 1차 자료

2026년10월7일조회했다. 외부자료의 해외 효과 크기를 한국 경마 보정값으로 가져오지 않는다.

- [Gramm와Marksteiner 2010, The Effect of Age on Thoroughbred Racing Performance](https://www.jstage.jst.go.jp/article/jes/21/4/21_4_73/_article/-char/en):미국수컷274두의Beyer속도지수로추정한모형에서평균정점4.45세를보고한다.별도집단·척도·모형의결과여서국내4.45세정점의증거가아니다.
- [2021, Drivers of exit and outcomes for Thoroughbred racehorses participating in the 2017–2018 Australian racing season](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0257581):비활동말의후속상태를조사해은퇴·사망·휴양등을구분한다.출전부재를모두은퇴로정의하지않는방법적근거로참고한다.국내중단사유를입증하지않는다.
- [한국마사회 경주마 상세정보API8_2](https://www.data.go.kr/data/15058115/openapi.do):생일등프로필정의의공식경로다.최신성적·상태의과거적용을허용하는근거가아니다.
- [한국마사회 마필종합 상세정보 API42](https://www.data.go.kr/data/15057985/openapi.do):공식설명에등록·불용·입사·퇴사·최종휴양정보가포함된다.이번에는명세존재만확인했고원문대량수집·퇴사이력검증은하지않았다.입퇴사와영구은퇴의의미를대조하는후속자료다.

## 계산과 한계

기상·월효과는회귀통제또는정확매칭으로맞췄다.게이트초단위보정·풍향·풍속·주로빠르기는넣지않았다.새연령보정계수나미관측은퇴후기록을만들지않았다.자세한식별·선택·시간순적용한계는[계획](PLAN.md)과[보고서](README.md)에보존했다.
""")
    central = HERE.parent / "conclusions/26_AGE_CURVE_EXIT.md"
    central.write_text(
        "# 말의 평균 연령 곡선과 출전 중단 전 변화\n\n2026년10월7일 · 관찰연구완료 · 성장·하락보정미채택.\n\n"
        + findings
        + "\n"
        + limits
        + f"\n[원보고서](../{HERE.name}/README.md) · [계획](../{HERE.name}/PLAN.md) · [출처](../{HERE.name}/SOURCES.md) · [상세표](../{HERE.name}/ALL_RESULTS.md) · [검증](../{HERE.name}/outputs/verification.json) · [게시요약](../{HERE.name}/PUBLICATION.md) · [용량명세](../{HERE.name}/outputs/artifact_inventory.json)\n"
    )
    print("Reader reports generated")


if __name__ == "__main__":
    main()
