"""Human-readable comparison with explicit denominators and support limits."""
import json
import pandas as pd
from analysis import HERE,save,clean
NAMES={'lead':'선행형','front':'선입형','closing':'추입 후보'}
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,r))+' |' for r in rows])
def main():
 v=json.loads((HERE/'verification01/verification.json').read_text());assert v['status']=='passed'
 rates=pd.read_csv(HERE/'run02/rates.csv',dtype={'period':str,'distance':str});ef=pd.read_csv(HERE/'run02/adjusted_effects.csv',dtype={'period':str});primary=ef[ef.configuration.eq('any')];r=rates[rates.configuration.eq('any')&rates.distance.eq('all')&rates['style'].isin(NAMES)]
 rows=[]
 for style in NAMES:
  z=r[r['style'].eq(style)];a=z[z.period.eq('all')].iloc[0];b=z[z.period.eq('2024_2025')].iloc[0];c=z[z.period.eq('2026')].iloc[0]
  rows.append([NAMES[style],f'{int(a.top3):,}/{int(a.starts):,} · {a.rate_pp:.2f}%',f'{a.date_low:.2f}~{a.date_high:.2f}%',f'{int(b.top3)}/{int(b.starts):,} · {b.rate_pp:.2f}%',f'{int(c.top3)}/{int(c.starts)} · {c.rate_pp:.2f}%'])
 main_table=table(['사전 각질','전체 입상/출전 · 입상률','전체 날짜95%','2024~2025','2026'],rows)
 rows=[]
 for distance in [800,900,1000,1110,1200,1300,1400,1610]:
  row=[f'{distance}m']
  for style in NAMES:
   z=rates[rates.configuration.eq('any')&rates.period.eq('all')&rates.distance.eq(str(distance))&rates['style'].eq(style)].iloc[0];row.append(f'{z.rate_pp:.1f}% ({int(z.starts):,}출전)')
  rows.append(row)
 distance_table=table(['거리','선행형','선입형','추입 후보'],rows)
 rows=[]
 for z in primary.itertuples():
  period={'all':'전체','2024_2025':'2024~2025','2026':'2026'}[z.period]
  label=NAMES[z.positive]+' − '+NAMES[z.reference]
  if not z.support:rows.append([period,label,'지원 부족으로 보류','—','1.000']);continue
  rows.append([period,label,f'{z.effect_pp:+.2f}%p',f'{z.date_low:+.2f}~{z.date_high:+.2f}%p',f'{z.BH_q:.3f}'])
 adjusted_table=table(['기간','비교','조정 Top3 차이','날짜95%','주9가설 BH q'],rows)
 rows=[]
 for config,name in [('same','동일거리 이력만'),('any40','추입 전진반복40% 완화')]:
  for style in NAMES:
   z=rates[rates.configuration.eq(config)&rates.period.eq('all')&rates.distance.eq('all')&rates['style'].eq(style)].iloc[0];rows.append([name,NAMES[style],f'{int(z.top3):,}/{int(z.starts):,}',f'{z.rate_pp:.2f}%'])
 sensitivity_table=table(['다른 정의','유형','입상/출전','원시 Top3'],rows)
 text=f'''# 제주 사전 각질별 입상률 비교

거리 통합 과거 이력으로 분류한 전체 표본의 원시 Top3는 **선행형34.65%, 선입형32.46%, 추입 후보32.63%**다. 이 정의에서는 선행형이 조금 높지만, 능력·편성을 고려한 선행형 우위는 확정되지 않았다. 추입 후보는190출전·49두로 표본이 작고 같은거리 이력만 쓰면 원시 순서도 달라진다. 각질만으로 개별 말의 입상확률을 고정할 근거는 아니다.

## 기간과 각질 정의

2017-01-13~2026-09-19의 정상완주 완전편성52,155출전·5,206경주·2,813두를 원천으로 사용했다. 현재8거리이며400m와 사용자 제외말은 제외했다. 2026년은 부분연도이고 최신10월 경주까지 확장한 집계가 아니다.

이번 경주 출발 전 T−2까지730일 내 최근최대10회 이력으로 판정한다. 유효 S1F가5회 이상이고 유효비율60% 이상이어야 한다. 이번 경주의 실제 초반위치·최종착순은 분류에 쓰지 않았다.

- 선행형: 과거 확실 전방60% 이상이며 첫집단 소속60% 이상.
- 선입형: 확실 전방60% 이상이며 첫집단 소속60% 미만.
- 추입 후보: 중단·후미60% 이상이며 유효4C→G1F최소5쌍에서 확실하게2두 이상 전진한 비율60% 이상.

통과조의 순위범위 전체가 앞/중간/뒤1/3에 들어갈 때만 해당 위치로 판정한다. 괄호 내부 순서를 개별 순위로 만들지 않는다. 추입 후보는 단순 후미마가 아니며 G1F 이후만 추입하는 말은 놓칠 수 있다. 전통 각질의 확정 정답이 아니라 과거 반복 전진의 엄격한 대용치다. 이 분류는 이전 [각질 연구](../20261009_style_leader_density_v1/README.md)와 같다.

세 유형에 속하는 표본은8,571출전·933두다. 다른/혼합 성향31,309출전과 이력 부족 등 미판정12,275출전은 세 유형에 강제로 넣지 않았다. 따라서 전체 제주마 모두의 각질 분포나 생애 고정 각질을 설명하는 숫자는 아니다.

## 전체와 최근 입상률

입상은 최종1~3착이다. 아래는 해당 각질의 **한 번 출전당 입상 비율**이며 입상마 중 각질 구성비나 실제 선행에 성공한 말의 입상률과 다르다.

{main_table}

전체에서 선행형은 선입형보다2.19%p 높다. 추입 후보는 선입형과0.17%p 차이에 불과하고 구간이 넓어 두 유형의 순서를 확정하기 어렵다. 2026추입 후보10.34%는3/29·11두의 소표본이며 일반적인 추입형 확률로 사용하지 않는다. 같은 말이 여러 번 출전하므로 출전 수와 고유 말 수는 다르다.

## 거리별 원시 입상률

아래 역시 거리 통합 과거 이력으로 사전 각질을 정한 뒤 현재 출전거리로 나눈 값이다.

{distance_table}

800·900·1110·1200m는 원시 선행형 비율이 높고, 1000m는 선입형35.10%가 선행형32.30%보다 높다. 1300·1400·1610m의 유형별 분모는 작다. 추입 후보는 거리별로 모두100출전 미만이며,800m의60%나1200m의42.2%를 거리별 우세로 확정하지 않는다. 거리별 표는 조정 우세 검정이 아니다.

## 능력과 편성을 고려한 비교

세 유형 말만 남긴 같은경주 고정효과 모형으로 공통 거리·주로·월·등급·두수를 고려했다. 게이트·부담중량·과거 전체/동일거리 착순과 상대기록·초반/막판 구간시간·과거출전수·공백을 함께 사용했다. 현재 실제 전개나 최종결과를 설명 입력에 사용하지 않았다. 표본이 일부 유형으로 한정되므로 미관측 능력·선택까지 제거한 인과효과는 아니다.

각 비교 양쪽100출전·30두·20경주일·동시출전30경주와 식별·잔여자유도 조건을 고정했다. 날짜·말군집 t95%를 각각 계산하고 주9가설의 날짜BH q<.05와 양쪽구간의 같은 방향을 함께 요구했다. 미지원은 p=1로 가족에 보존했다.

{adjusted_table}

선입−선행은 전체−1.50%p이며 날짜/말구간 모두0을 포함한다. 최근점추정은2024~2025년−5.87%p,2026년+5.82%p로 방향도 바뀐다. **능력·편성 고려 후 항상 선행형이 유리하다고 확인하지 못했다.**

엄격 추입 후보의 전체 조정차이는 두 선행/선입 유형보다 음수이고 개별 날짜·말구간도0보다 낮다. 그러나 주9가설BH q는0.143으로 지원되지 않았고, 같은거리/완화정의 민감도에서는0을 포함했다.190출전·49두의 선택된 표본에 기반하므로 이를 고정 불리함이나 개별 확률 감점으로 채택하지 않는다. 최근추입 비교는 표본/말수 기준 미달로 보류했다. 주9가설 방향지원과 최근두기간 지원반복은모두0개다.

## 이력 범위를 바꾼 비교

{sensitivity_table}

동일거리 이력만 쓰면 추입 후보33.33%, 선행형30.16%, 선입형26.92%로 원시 순서가 달라진다.126출전의 추입 후보 우위를 확정하는 결과는 아니다. 전진반복 기준을40%로 완화하면 추입 후보902출전·29.71%로 낮아진다. 따라서 강한 추입말을 얼마나 좁게 고르는지가 비율에 영향을 준다. 같은거리 전체 조정 선입−선행은−0.78%p(날짜−9.01~+7.44), 추입−선행은−11.28%p(−43.13~+20.57)로 불확실하다.

현재 활용할 수 있는 결론은 거리 통합 정의의 원시표에서 선행형이 근소하게 높다는 점이다. 실제 평가에는 말의 능력과 이번 편성·예상위치가 필요하며 각질별 고정확률·보너스는 채택하지 않았다.

## 검산과 산출물

[계획](PLAN.md)과 [원천 해시](source_manifest.json)를 보존했다. 기존 과거 이력·현재결과 교란 검증을 고정 입력의 근거로 재사용하고, 이번 세 정의의 라벨{v['labels_recomputed']:,}행을 독립 조건문으로 재계산했다. 별도 메모리SQL의{v['SQL_raw_cells_and_cluster_intervals']}원시셀·구간, {v['support_cells']}지원대비와9모형의 합동 경주고정효과 정규방정식·군집공분산·BH를 검산했다. 최대계수차이는{v['maximum_beta_difference']:.3g}다. [검증 결과](verification01/verification.json)는통과다.

[입상률 전체](run02/rates.csv) · [조정 비교](run02/adjusted_effects.csv) · [모형 원장](run02/models.json) · [관측 범위](run02/coverage.json) · [최근 반복](verification01/recent_repeat.json).

정상완주 완전편성을 사후 선정한 후향 관측이다. 각질 관측선택·미관측 능력과 전략·게시시각 미확정이 남으며, 개별 미래확률의 성능검증이나 각질변경의 원인효과가 아니다. DB개방·수정·외부수집·운영모델변경은 없다. 최초run01의 코드 열이름 충돌 실패는 보존했고 통계정의를 바꾸지 않은run02와 독립 검증이 최종이다. 이번 사용자의 요청으로 각질별 입상률 비교를 재개했으며 다른 각질 예측·편성 확장과 기수 연구의 추후 재개 상태는 유지한다.
'''
 assert not (HERE/'README.md').exists();(HERE/'README.md').write_text(text)
 save(HERE/'decision.json',{'status':'style_top3_comparison_completed_raw_lead_highest_adjusted_advantage_unconfirmed','source_start':'2017-01-13','source_end':'2026-09-19','partial_2026':True,'primary_definition':'past_any_distance_strict','source_starts':52155,'primary_three_style_starts':8571,'primary_three_style_horses':933,'primary_rates':clean(r),'primary_BH_family':9,'primary_supported_directions':int(primary.direction_supported.sum()),'recent_repeated_supported':v['recent_repeated_supported'],'individual_future_probability_validated':False,'fixed_style_bonus_adopted':False,'database_opened':False,'operationally_applied':False,'style_top3_resumed_by_user':True,'other_style_and_jockey_followups_remain_deferred':True})
 print('Korean report saved',flush=True)
if __name__=='__main__':main()
