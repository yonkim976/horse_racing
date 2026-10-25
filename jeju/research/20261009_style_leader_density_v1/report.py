"""Readable distinction between absolute Top3 probability and relative style advantage."""
import pandas as pd
from features import HERE,save
STYLE={'lead':'선행형','front':'선입형','closing':'추입 후보'}
def main():
 p=HERE/'run02';actual=pd.read_csv(p/'actual_pack_rates.csv',dtype={'key':str});crowd=pd.read_csv(p/'crowd_rates.csv',dtype={'key':str,'group':str});eff=pd.read_csv(p/'adjusted_effects.csv',dtype={'key':str})
 text='''# 선입 추입형 입상과 선행형 편성 수의 관계

2017년부터2026-09-19까지 보유자료로 비교했다. **선행형이 많을수록 선입·추입형의 입상률이 항상 높아진다는 명제는 현재 자료로 확인되지 않았다.** 선입형에는2026년 같은 경주에서 선행형 대비 상대적으로 유리해지는 탐색 신호가 있다. 추입형은 엄격 기준 표본이 적고 반복 기준을 완화해도 일관된 이점이 확인되지 않는다. 실제 빠른 페이스의 이점과 과거 선행형의 숫자는 구분한다.

## 각질의 사전 정의

경주 T−2일까지730일 내 최근최대10출전을 사용한다. 유효 S1F5회 이상·유효비율60% 이상이 공통 요건이다. 같은거리와 거리통합을 모두 계산했다. 이번 경주 입상·통과조는 각질 분류에 쓰지 않는다.

- 선행형: 확실 전방60% 이상이며 첫집단 소속60% 이상.
- 선입형: 확실 전방60% 이상이며 첫집단 소속60% 미만.
- 추입 후보: 확실 중단·후미 합계60% 이상이며, 유효4C→G1F5쌍 이상 중 순위범위로 확실하게2두 이상 전진한 비율60% 이상. 후미대기와 구분한다. 입상 여부는 정의에 포함하지 않는다.

전방·중단·후미는 집단 순위범위 전체가 각각 출전두수의 앞·중간·뒤1/3에 들어가는 보수 판정이다. 괄호 내부 내외측순서를 개별 순위로 만들지 않는다. 추입 후보는 전통각질의 정답이 아니라 반복 전진 대용치이며 G1F 이후만 추입하는 말은 놓칠 수 있다. 60%는 기존 위치/전진 반복 연구의 설명 기준이지 최적 기준이 아니다.

## 실제 초반 위치별 입상률

앞선 선행형 연구와 같은 **동일거리 과거 이력 기준**이다. 실제 위치는 S1F 통과조 집단이며 단독선행·전통선입과 동일하지 않다. 출발번호를 뜻하지 않는다. 최종1~3착을 Top3로 센다.

| 사전 각질 | 현재 첫 집단 | 현재 둘째 집단 | 현재 셋째 이후 |
| --- | ---: | ---: | ---: |
'''
 for sty in ['front','closing']:
  r=actual[(actual.scope=='same')&(actual['style']==sty)&(actual.view=='all')].set_index('group');cells=[]
  for group in ['first','second','farther']:
   z=r.loc[group];cells.append(f'{int(z.top3)}/{int(z.starts)} · {100*z.rate:.1f}%'+(' (소표본)' if z.low_support else ''))
  text+='| '+STYLE[sty]+' | '+' | '.join(cells)+' |\n'
 text+='''
동일거리 선입형2,277출전 중 현재집단불명2회를 제외했다. 추입 후보126출전에서 실제 첫·둘째집단은 각각3·6회뿐이므로 그 비율을 일반화하지 않는다. 주로 셋째이후에 있던 추입 후보는38/117=32.5%다. 뒤에 있을수록 유리하다는 인과 해석은 아니다.

거리 통합 이력으로는 선입형4,245출전, 추입 후보190출전이다. 통합 선입형의 현재 첫/둘째/셋째이후 Top3는41.2%(614/1,490) /31.2%(429/1,377) /24.2%(333/1,374)다. 통합 추입 후보의 셋째이후는32.6%(58/178), 첫·둘째는3·9회로 극소표본이다. 이전 동일거리 선행형35.1%와 통합 선행형39.7%를 같은 분모로 섞지 않는다. [초반 집단별 전체표](run02/actual_pack_rates.csv)와 [확실 선행권·선입권·중단·후미·모호 전체표](run02/actual_strict_rates.csv)에 날짜·두수·분자분모·군집구간을 보존했다.

## 선행형이 많은 편성의 개별 입상률

주비교는 거리 통합 과거 각질로 판정 가능 비율80% 이상인3,599경주·36,331출전이다. 동일거리 기준으로는 이 조건을 만족하는 경주가763개여서 통합을 주정의로 먼저 정했다. 통합 선입형3,667출전, 엄격 추입 후보185출전이 이 편성 조건에 포함됐다.

아래 숫자는 입상한 각질의 총마릿수가 아니라 **해당 각질 말 한 번 출전당 Top3 비율**이다. 선행형 수는 사전에 관측된 편성 전체 숫자이며 선입·추입 후보 본인은 포함되지 않는다.

| 사전 선행형 수 | 선입형 입상/출전 · 비율 | 추입 후보 입상/출전 · 비율 |
| --- | ---: | ---: |
'''
 for label,display in [('0','0두'),('1','1두'),('2','2두'),('3plus','3두 이상')]:
  cells=[]
  for sty in ['front','closing']:
   z=crowd[(crowd.configuration=='any80')&(crowd['style']==sty)&(crowd.view=='all')&(crowd.group==label)].iloc[0];cells.append(f'{int(z.top3)}/{int(z.starts)} · {100*z.rate:.1f}%')
  text+='| '+display+' | '+' | '.join(cells)+' |\n'
 text+='''
선입형의2두이상−0두 차이는+1.97%p(날짜군집95%−1.72~+5.77, 말군집−1.82~+5.89)로 불확실하다. 추입 후보는−8.89%p(날짜95%−25.44~+7.08, 말−26.77~+7.82)이며 표본이 적다. 추입이 불리하다고 확정한 결과도 아니다.0·1·2·3+ 순서의 단조 증가가 확인되지 않는다.

판정 불가능한 말1,651출전은 선행형이 아니라고 확정하지 않는다. 관측된 선행형 수는 현재 정의로 확인된 숫자이며, 미분류마에 추가 선행형이 있을 수 있다. 판정률100%인2,322경주만 남긴 민감도와 동일거리80% 민감도도 별도 계산했다. [기간·연도·거리별 원시비율](run02/crowd_rates.csv), [2두이상−0두 차이](run02/raw_contrasts.csv), [편성 가용 범위](run02/coverage.csv).

## 능력과 조건을 고려한 절대 입상률 변화

각질별 설명 로짓 모형에 거리·연도·월·두수·게이트·함수율·등급·부담중량·자기 과거착순/상대시간/초반·막판구간순위/공백/이력수·상대과거능력·각질판정률을 넣었다. 과거능력은 모두 T−2 이전 이력이며 상대평균에서 자신을 제외했다. 현재 실제 초반위치·구간시간·최종착순은 설명 입력에 쓰지 않는다.

아래는 관측 범위 안에서 사전 선행형을1두 추가했을 때의 평균 표준화 입상률 변화다. 인과효과 또는 확정 보정치가 아니다.

| 각질·기간 | 출전 | 1두당 변화 | 날짜군집95% 구간 | 주6가설 BH q |
| --- | ---: | ---: | ---: | ---: |
'''
 for r in eff[(eff.configuration=='any80')&eff['style'].isin(['front','closing'])].itertuples():
  period='전체' if r.view=='all' else r.key.replace('_','~')
  value=f'{r.marginal_delta_pp:+.2f}%p' if pd.notna(r.marginal_delta_pp) else '사전 최소표본 미달'
  interval=f'{r.date_low_pp:+.2f}~{r.date_high_pp:+.2f}%p' if pd.notna(r.marginal_delta_pp) else '추정 보류'
  text+=f'| {STYLE[r.style]}·{period} | {r.starts:,} | {value} | {interval} | {r.primary_BH_q:.3f} |\n'
 text+='''
선입형은 전체+0.55%p,2024~25년+2.75%p,2026년+2.73%p로 양의 점추정이지만 구간이 모두0을 포함하며 다중비교 후 지지가 없다. 엄격 추입 후보는 전체−3.59%p(말95%−12.13~+4.95), 최근은 사전100출전 기준에 못 미쳐 추정 보류했다. 엄격 추입 전체 모형도185출전에51개 설명계수로 불안정할 수 있어 방향을 단정하지 않는다.

판정률100% 선입형은+0.30%p(날짜−1.57~+2.18), 동일거리80% 선입형은+0.57%p(−3.88~+5.01)로 역시 불확실하다. 전진 반복을40%로 완화한 추입 후보860출전에서도−1.26%p(−4.13~+1.62),2024~25년+1.48%p(−3.93~+6.90)로 안정적인 증가를 확인하지 못했다. 완화 기준으로 주정의를 교체하지 않는다.

참고 선행형 자체는 전체1두당−1.70%p(날짜−3.06~−0.33, 말−3.38~−0.02), 최근 각각−2.06·−4.71%p지만 최근구간은0을 포함한다. 선행형의 성적이 떨어지는 것과 특정 다른 각질의 입상률이 안정적으로 오르는 것은 별도 명제다. 선행형은 주6가설 밖의 참고결과다. [조정 전체표](run02/adjusted_effects.csv), [계수·군집공분산](run02/model_parameters.json), [전체 재계산확률](run02/model_predictions.csv).

## 선행형 대비 상대적 우세는 있는가

주원시표를 본 뒤 추가한 **탐색 분석**이다. 동일 경주 안의 선행·선입·추입 후보를 비교하는 경주 고정효과 모형으로 거리·주로·월·연도·등급·두수를 상쇄하고, 게이트·부담중량·과거능력의 차이를 고려했다. 선행형 수가 증가할수록 선입−선행 입상률 격차가 커지는지를 살폈다. 절대 입상률 증가와 다른 질문이다.

| 기간 | 선입−선행 상대 변화, 선행형1두당 | 날짜95% 구간 | 탐색6가설 BH q |
| --- | ---: | ---: | ---: |
'''
 rel=pd.read_csv(HERE/'relative01/effects.csv',dtype={'period':str})
 for r in rel[rel.contrast=='front_minus_lead'].itertuples():
  text+=f'| {("전체" if r.period=="all" else r.period.replace("_","~"))} | {r.relative_delta_pp_per_leader:+.2f}%p | {r.date_low_pp:+.2f}~{r.date_high_pp:+.2f}%p | {r.exploratory_BH_q:.3f} |\n'
 text+='''
2026년에는 상대 선입 우세 신호가 있으며 과거능력 통제를 뺀 단순모형에서도+19.23%p(날짜95%+8.50~+29.95)로 방향이 유지됐다. 그러나 전체·2024~25년의 기간별 반복 확인은 부족하고, 결과를 본 뒤 추가한 모형이므로 확인 가설로 승격하지 않는다.2026년 선입형·선행형이 함께 나온 경주 중 선행형1/2/3두이상 그룹은75/34/16경주다. 같은 경주의 평균 선입−선행 원시 격차는 각각−16.5/+9.9/+33.6%p다. 특히 마지막16경주에 기대어 여러 마리 증가의 고정 효과로 외삽하지 않는다. 추입−선행 상대변화는 모든 기간에서 구간이0을 포함한다.

따라서 **선입형의 상대적 이점 후보는 있으나, 선행형이 많으면 추입·선입 모두 우세하다는 일반 법칙은 아직 아니다.** [탐색 계획과 추가시점](EXPLORATORY_PLAN.md), [경주 고정효과 결과](relative01/effects.csv), [단순모형·동시출전 원시표](relative02/minimal_adjustment.csv), [동시출전 경주수](relative02/paired_raw_summary.csv).

## 선행형 수와 실제 경합의 차이

이 역시 주분석 뒤의 탐색 진단이다. 현재 S1F가 전두수 유효한 편성에서, 과거 선행형 중2두 이상이 실제 같은 첫집단에 들어간 경주는 사전 선행형2두 편성의181/710=25.5%(날짜95%22.3~28.6),3두이상 편성의150/325=46.2%(40.8~51.6)였다. 선행형이3두 이상이어도 절반 이상에서는 이 동시선두 조건이 성립하지 않았다.

동일집단은 실제 경합·소모전·빠른 페이스의 직접 측정이 아니다. 숫자만으로 경합을 가정하지 말고, 향후에는 초반속도·실제 경합·각질 적합성의 상호작용을 별도로 검증할 필요가 있다. [현재 선두집단 중복 진단](explore01/summary.csv).

## 범위와 검증

원천은2017~2026-09-19 정상완주 완전경주52,155출전·5,206경주·2,813두다.2026년은 부분연도,400m는 워밍업 제외, 제외마3005648을 유지했다.1300m는 사용자 정정인 출발→2C→S1F로 해석한다. 거리별 작은 분모와 관측기간을 전체기간 대표수치로 숨기지 않는다. 현재자료 선정은 사후 계약이며 게시시각 검증을 갖춘 서비스 재생자료가 아니다. 현재 주로·부담·등급 통제도 공개시각 미확정 설명값이다. 운영모델은 변경하지 않았다.

날짜·말 군집 부트스트랩 각4,000회, seed20261009, 조정모형은 날짜·말 군집 샌드위치95% 구간이다. 출전100회 또는 경주30개 또는 날짜20개 미만은 소표본으로 표시했다. 기간·거리별 구간은 개별 설명구간이며 유의한 셀만 골라 일반화하지 않는다. 주6가설과 사후탐색6가설은 별개다. 표본부족으로 최근 모형을 추정하지 못한 가설은 가족에서 제거하지 않고 p=1로 유지했다.

[사전계획](PLAN.md), [각질 입력 코드](features.py), [주분석 코드](analyze.py), [출전별 입력](features01/start_features.csv), [원천 ID·해시](features01/source_manifest.json), [독립검증](verification01/verification.json), [탐색검증](verification_extra01/verification.json)을 보존했다. 원천 과거627,338출전 참조·104,310이력창의 전진 분자분모,991개 비율표,21개 모형20,487확률행을 재계산했다. 앞선 선행형 판정과 동일하고 현재결과 교란에도 각질이 불변이다. 최대 확률 재계산오차1.11e−16이다. 최초run01은 BH구현이6개 모형 모두 추정 가능하다고 가정한 점검 실패로 보존했고, 사전 최소표본 기준과6가설 가족을 유지한run02가 최종이다.
'''
 (HERE/'README.md').write_text(text)
 save(HERE/'decision.json',{'status':'absolute_style_advantage_unconfirmed_relative_front_2026_exploratory_signal','operationally_applied':False,
  'period_end':'2026-09-19','source_starts':52155,'primary_races':3599,'primary_front_starts':3667,'primary_closing_starts':185,
  'primary_front_rate_by_leaders':[427/1285,418/1331,258/742,112/309],
  'primary_closing_rate_by_leaders':[24/62,19/66,14/43,3/14],
  'supported_primary_positive_tests':0,'relative_front_2026_signal':'post_primary_exploratory_not_confirmatory',
  'relative_front_2026_3plus_paired_races':16,'general_more_leaders_benefits_all_other_styles_confirmed':False,
  'no_effect_proven':False,'causal_effect':False,'fixed_style_bonus_adopted':False})
 print('Report saved',flush=True)
if __name__=='__main__':main()
