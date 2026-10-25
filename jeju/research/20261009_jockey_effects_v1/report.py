"""Write the research report from the completed, verified result tables."""
import pandas as pd
from data import HERE, save

def main():
    e = pd.read_csv(HERE/'effects01/jockey_effects.csv', dtype={'jockey_id':str})
    a = pd.read_csv(HERE/'forecast01/assignment.csv', dtype={'jockey_id':str})
    t = e[(e.period=='2026') & (e.variant=='primary') & (e.target=='time') & e.support].copy()
    a26 = a[a.period=='2026'].set_index('jockey_id')
    rows=[]
    for r in t.sort_values('effect',ascending=False).itertuples():
        x=a26.loc[r.jockey_id]
        old=e[(e.period=='2024_2025') & (e.variant=='primary') & (e.target=='time') & (e.jockey_id==r.jockey_id)].iloc[0]
        rows.append(f'| {r.name} | {r.starts:,} | {100*x.raw_top3:.1f}% | {100*x.expected_top3:.1f}% | {old.effect:+.3f} | {r.effect:+.3f} | [{r.date_low:+.3f}, {r.date_high:+.3f}] | [{r.horse_low:+.3f}, {r.horse_high:+.3f}] | {r.BH_q:.3f} | '+('지지' if r.direction_supported else '미확정')+' |')
    text='''# 제주 기수의 배정 수준·추가 기록 기여·전개 특성

2026-10-09 완료. **좋은 말을 타는 정도와 기수의 추가 신호는 모두 관찰된다.** 원시 입상률만으로 기수 능력을 평가하기 어렵고, 말의 과거 수행과 조건을 고려한 뒤에도 기수 정보는 이후 기간의 상대기록·입상확률 예측을 작게 개선했다. 현재 자료에서는 박성광 기수의 빠른 기록 방향과 초반 첫집단 확보가 두 후기 기간에 반복됐다. 말×기수 조합의 별도 상호작용은 추가 개선이 없어 채택하지 않는다.

순수 기승능력·교체의 인과효과·기수별 고정 초 보정·운영 채택을 뜻하지 않는다. 거리별 전문성과 각질별 상호작용은 이번에 별도 추정하지 않았다.

## 기간과 자료

2017-01-13~2026-09-19 정상완주 완전 편성 **52,155출전·5,206경주·2,813두·기수 40명·조교사 25명**. 2026년은 부분연도다. 대상은 800·900·1000·1110·1200·1300·1400·1610m이며, 400m와 제외마 3005648은 제외한다. 조교사 ID 결측은 0건이다.

기존 품질선정 원천과 T−2 시점 최근 최대 10회/730일 이력을 재사용했다. 공식 출전 ID·기수 ID·말 ID·날짜·거리·결과 payload SHA를 로컬 DB의 읽기전용 조회와 대조했다. 이름으로 ID를 추측하지 않으며 동일 ID의 최신 관측명을 표시한다. 원시 구간기록의 보류·NULL에 대체값을 넣지 않는다. 통과조 괄호는 내측→외측이며 개별 확정 순위가 아닌 구간 순위 범위로 사용한다. 1300m는 사용자 정정 출발→2C→S1F 순서다. G3F 기록은 마지막 600m 시간이며 통과조가 아니다.

## 좋은 말의 배정과 원시 성적

각 연도 이전 자료로 학습한 H0(말의 과거 수행·편성·조건, 말/기수/조교사 ID 없음)의 예상 Top3 확률을 기수별로 평균했다. 현재 결과로 좋은 말을 정의하지 않았다. 이 예상치는 과거 기수 영향과 현재 조건도 포함한 기대수행 지표이며, 순수한 말 자체의 능력이 아니다.

2026년 박성광 기승마 298출전의 실제 Top3는 **53.7%**, H0 평균 기대는 **40.2%**, 경주 내 H0 기대 상위 1/3 배정 비율은 **64.4%**다. 임재광은 실제 47.2%·기대 38.6%, 양민재는 실제 16.4%·기대 23.5%다. 기수별 배정 수준이 다르다. 실제−기대 격차를 아래 고정효과의 기수 계수와 동일시하지 않는다.

100출전 이상 기수의 원시 Top3와 H0 기대 Top3 간 Pearson 상관은 2024~2025년 0.948(26명), 2026년 0.965(17명)이다. 이는 배정과 성적의 연관이며, 상관의 제곱을 능력 또는 배정의 인과 설명률로 해석하지 않는다. 전체 기수·기간의 원시/기대 분모는 [배정 표](forecast01/assignment.csv)에 보존했다.

## 말·거리·경주를 고려한 기록 차이

말×정확거리 고정효과와 경주 고정효과, T−2 과거 수행·공백·이력 수, 게이트·부담중량·마체중·조교사를 고려했다. 경주 효과는 함수율·월·등급·상대편성·공통 페이스를 흡수한다. 기수 계수는 기간 내 출전가중 평균을 0으로 놓았다. **양수는 조건을 고려한 평균보다 빠른 방향의 초 차이**다. 서로 다른 기간의 평균이 달라 계수 변화를 순수 능력 변화로 해석하지 않는다.

아래는 2026년 최소 100출전·20경주일·30두를 충족한 17명 전원이다. 날짜와 말 군집 95% 구간이 모두 0을 제외하고, 기간×목표별 전체 기수 BH q<0.05를 만족해야 방향을 지지한다. 정렬은 점추정 순서이며 확정 순위가 아니다.

| 기수 | 2026 출전 | 실제 Top3 | H0 기대 Top3 | 2024~25 초 | 2026 초 | 날짜 95% 구간 | 말 95% 구간 | BH q | 2026 방향 |
|---|---:|---:|---:|---:|---:|---|---|---:|---|
'''+ '\n'.join(rows)+'''

박성광은 전체기간 +0.377초, 2024~2025년 +0.556초, 2026년 +0.463초로 빠른 방향이 반복됐다. 2026년 말 고정효과(거리 통합) 민감도 +0.393초, 과거 수행 통제 제외 민감도 +0.453초에서도 방향이 유지됐다. 이것은 **개별 경주마다 0.46초를 보장하거나 기록에서 일괄 차감하는 보정값이 아니다.** 문현진의 2026년 +0.335초는 양쪽 개별 구간이 양수지만 전체 기수 다중비교 후 q=0.097로 주 기준을 통과하지 못했다. 나머지 현재 기수의 미확정은 능력 차이가 없다는 증명이 아니다.

전체·최근·2026년의 40개 ID와 5개 목표, 시간 민감도, 분모·관측일·출전두수 범위는 [전체 효과 표](effects01/jockey_effects.csv)에 보존했다. 설명 모형의 Top3 계수는 선형확률 차이(%p)이며 미래 확률의 고정 가산치가 아니다.

## 전개 특성에서 반복된 부분

박성광의 S1F **첫집단 확보** 조정 차이는 2024~2025년 **+8.1%p**, 2026년 **+18.1%p**였다. 2026년 날짜 구간 +7.6~+28.7%p, 말 구간 +4.2~+32.0%p, BH q=0.024다. 두 기간 모두 지지돼 초반 자리 확보 특성의 후보로 볼 수 있다. 첫집단은 단독 선두나 의도적인 선행 전법과 같지 않다.

임재광의 2024~2025년 첫집단 +6.5%p와 4C→G1F 확실 2두 이상 전진 +5.1%p는 지지됐지만, 2026년에는 반복 확정되지 않았다. 전현준·문현진·김홍권의 2024~2025년 G3F 상대순위 우세 역시 2026년에는 양쪽 군집 구간·다중비교 기준을 함께 통과하지 못했다. 박성광의 후반 전진·G3F 우세도 최근 두 기간에 반복 확정되지 않았다.

따라서 현재는 **초반 자리 확보의 제한적인 반복 근거가 있고, 추입 전문·후반 전문의 고정 명칭을 줄 근거는 부족하다.** 영상 없이 주행경로·추진 기술·승부 의도를 확정하지 않는다. G3F 상대순위 계수의 단위는 순위분율×100이며 초 또는 입상확률 %p가 아니다.

## 이후 기간의 실제 예측 개선

2024·2025·2026년마다 1월 1일−2일까지의 자료만으로 전처리와 모형을 고정했다. 평가 17,412출전·1,779경주를 동일하게 비교하고 경주별 동일 가중을 사용했다. 시간 목표는 **실제 경주평균 대비 상대 주파시간**이며 절대 완주시간 예측이 아니다. MAE는 상대기록의 평균절대오차(초), logloss는 Top3 확률오차(작을수록 좋음)다.

| 평가 기간 | 출전/경주 | H0 MAE | H1 기수 추가 MAE | H0 logloss | H1 logloss |
|---|---:|---:|---:|---:|---:|
| 2024~2025 | 12,739 / 1,291 | 0.9513 | 0.9403 | 0.5693 | 0.5608 |
| 2026~09-19 | 4,673 / 488 | 0.8924 | 0.8845 | 0.5775 | 0.5692 |

기수 ID 추가의 MAE 개선은 각각 **0.0110초·0.0079초**다. H1−H0의 날짜 구간은 각각 −0.0133~−0.0088초, −0.0127~−0.0030초이며 말 군집 구간도 모두 음수다. 두 기간×두 주지표의 BH 후에도 모두 개선을 지지한다. 통계적 반복 근거가 있지만 개선 크기는 작다.

H2는 H0+말 ID+기수 ID+조교사 ID, H3는 H2+말×기수 ID다. H3−H2는 2024~2025년 MAE **+0.0021초**, 2026년 **+0.0022초**로 오히려 나빠졌고 Top3 logloss도 나빠졌다. 과거 3회 이상 같은 조합 부분집합에서도 두 기간에 반복된 추가 개선은 없었다. 말과 기수의 호흡 자체가 없다는 증명이 아니라, 이번 고정 모형의 별도 조합 항목을 채택할 근거가 없다는 뜻이다.

전체 지표·동일표본 비교·양쪽 군집 4,000회 부트스트랩 구간·BH는 [지표](forecast01/metrics.csv), [비교](forecast01/comparisons.csv)에 있다. Ridge alpha=20, Logistic C=0.3을 고정했고 탐색하지 않았다. Top3는 개별 이진확률로 합계를 3으로 강제하지 않은 연구 지표다. 같은 원천을 재사용한 후향 개발 평가이며, 현재 기수·조교사·체중·부담·등급의 사전 공개/변경 시각을 검증한 서비스 재생은 아니다.

## 같은 말의 기수 교체 비교

2017~2023년 추정 기수 기록 점수를 고정한 뒤, 2024년 이후 같은 말·정확거리의 직전 같은거리 관측과 2~60일인 쌍을 비교했다. 다른 거리 출전이 사이에 있을 수 있다. 목표는 H0 예상 대비 실제 상대기록 오차의 변화다. 현재 결과로 기수 점수를 다시 만들지 않았다.

기수 교체만 보면 2024~2025년 3,064쌍에서 과거 점수상 1초 우세한 기수로의 변경에 대응하는 오차 변화 기울기는 **−1.007**(날짜 구간 −1.177~−0.837, 말 −1.206~−0.808), 2026년 974쌍은 **−0.784**(날짜 −1.050~−0.519, 말 −1.089~−0.480)였다. 음수는 예상보다 빠른 쪽이다. 부담차 1kg·함수율차 3%p 이내 비교에서도 같은 방향이었다(2026년 607쌍 중 교체 242쌍).

이는 과거 기수 평가와 후기 상대기록 변화의 연관을 보강한다. 교체가 무작위가 아니며 컨디션·교체 사유·관리 변화를 모두 관측하지 못하므로 **교체만으로 0.78초 빨라진다는 인과효과로 해석하지 않는다.** 전체 9,907쌍과 민감도는 [쌍 표](pairs01/pairs_and_frozen_scores.csv), [계수·구간](pairs01/effects.csv)에 보존했다.

## 연구 결정과 다음 적용 범위

기수 정보를 말의 과거 수행을 보완하는 연구 입력 후보로 유지한다. 원시 승률·입상률에 단순 가산하거나 기수별 고정 초를 기록에 더하지 않는다. 말×기수 상호작용 항목은 이번 결과로 추가하지 않는다. 기수 특성은 기간·표본·불확실성을 붙여 표시하며 박성광의 초반 첫집단 확보 후보 외에 고정 전법 명칭을 확정하지 않는다. 거리별·말의 각질별 전문성은 별도 후속 질문으로 남긴다. 이번 결과 저장은 운영 모형 변경이나 배포가 아니다.

정상완주 완전 편성의 선정 자료여서 중단·사고·제외 위험 전체를 대표하지 않는다. 경주 고정효과는 공동 페이스를 통한 기수 영향도 흡수하며, 말×거리 효과는 성장·당일 컨디션·배정 선택을 모두 제거하지 못한다. 그래서 순수 기수 능력의 정확한 분리는 아직 보장할 수 없다.

## 재현과 검증

[사전 계획](PLAN.md) → [입력 코드](data.py) → [효과](effects.py) → [연도 고정 예측](forecast.py) → [교체쌍](pairs.py) 순서로 계산했다. [입력 계보](input01/source_manifest.json)와 [이전 자료지원 감사](../20261009_jockey_research_feasibility_v1/README.md)를 연결한다.

[주 검증](verification01/verification.json) 통과: 공식 payload 52,155건, 연도별 두 목표 예측 139,296개 재계산, 16개 지표 행 재계산, 고정효과 22개 모형·521,388행 재계산, 평균0 제약·BH·훈련 상한·현재 결과 교란 불변성·교체쌍 9,907개를 확인했다. [추가 검증](verification_extra01/verification.json)도 통과: 기수 효과와 양쪽 군집 구간 684개, 배정 52행, 교체 회귀와 구간 6개 재계산. DB 전후 SHA가 같고 운영 모형·공통 앱 변경은 없다.

[중앙 기수 결론](../conclusions/08_JOCKEY_PROFILE.md), [연구 목록](../conclusions/README.md)에 함께 등록한다. 파일 보관 해시는 artifact_manifest.json, 중앙 등록 후 원본 불변·크기·링크 확인은 publication_verification.json에 기록한다.
'''
    (HERE/'README.md').write_text(text)
    save(HERE/'decision.json',{
        'status':'conditional_jockey_effects_and_temporal_forecast_comparison_completed',
        'effect_estimation_completed':True,'jockey_ranking_estimated':False,
        'pure_jockey_ability_identified':False,'operationally_applied':False,
        'source_starts':52155,'source_races':5206,'source_horses':2813,'source_jockeys':40,
        'source_through':'2026-09-19','partial_2026':True,
        'allocation_differences_observed':True,'jockey_information_small_repeated_forecast_gain':True,
        'relative_time_MAE_gain_2024_2025_s':0.010969921320153054,
        'relative_time_MAE_gain_2026_s':0.00786160870449838,
        'pair_interaction_adopted':False,'fixed_record_seconds_adopted':False,
        'repeat_supported_early_first_pack_display_name':'박성광',
        'distance_and_running_style_specialization_estimated':False,
        'switch_association_causal':False,
        'previous_style_study':'completed_saved_revisit_later_per_user'})
    # Verify the displayed identity against the official-ID table.
    d=__import__('json').loads((HERE/'decision.json').read_text())
    park=e[(e.period=='2026')&(e.variant=='primary')&(e.target=='time')&(e.name=='박성광')].iloc[0]
    d['repeat_supported_early_first_pack_candidate']=park.jockey_id
    save(HERE/'decision.json',d)
    print('Report saved; current supported-sample riders',len(rows),flush=True)

if __name__=='__main__':main()
