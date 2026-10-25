"""Publish audited local weight research and extend the central research register."""
from pathlib import Path
import hashlib
import json
import re
import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent;ROOT=H.parents[2];C=H.parent/'conclusions';V1=H.parent/'20261008_weight_speed_v1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def new(name,v):
    with (H/name).open('x',encoding='utf-8') as f:f.write(v)
def f(v,n=3):return f'{v:+.{n}f}'.replace('-','−')
def ci(r):return f'{f(r.ci_lo)}~{f(r.ci_hi)}'
def qtext(v):return '<0.0001' if v<.0001 else f'{v:.4f}'
def table(head,rows):return '\n'.join(['| '+' | '.join(head)+' |','|'+'|'.join(['---']*len(head))+'|']+['| '+' | '.join(map(str,r))+' |' for r in rows])+'\n'

central=json.loads((C/'source_manifest.json').read_text());previous={i['path']:i['sha256'] for i in central['files'] if i['role']=='conclusion_or_management'}
assert all(sha(ROOT/i['path'])==i['sha256'] for i in central['files'])
audit=json.loads((H/'input_audit.json').read_text());verify=json.loads((H/'verification.json').read_text());calc=json.loads((H/'calculation_verification.json').read_text());assert verify['status']==calc['status']=='passed'
e=pd.read_csv(H/'effects.csv');cor=pd.read_csv(H/'body_burden_correlations.csv');groups=pd.read_csv(H/'raw_change_groups.csv');rawcorr=pd.read_csv(H/'raw_pair_correlations.csv');bodygroups=pd.read_csv(H/'body_load_groups.csv')
main=e.query("family=='row' and period=='full' and variant=='primary' and exposure=='burden' and target=='time_s'").set_index('distance')
speed=e.query("family=='row' and period=='full' and variant=='primary' and exposure=='burden' and target=='log_time100'").set_index('distance')
pair=e.query("family=='pair' and period=='full' and variant=='primary' and exposure=='increase_kg' and target=='time_s'").set_index('distance')
c0=cor[cor.distance.eq(0)].iloc[0]
crows=[[('전체' if r.distance==0 else f'{r.distance}m'),r.rows,f'{r.pearson_raw:.3f}',f'{r.raw_horse_boot_lo:.3f}~{r.raw_horse_boot_hi:.3f}',f'{r.within_horse_pearson:.3f}',f'{r.race_horse_residual_pearson:.3f}'] for r in cor.itertuples()]
mrows=[]
for distance,r in main.iterrows():
    s=speed.loc[distance];mrows.append([f'{distance}m',r.rows,f(r.effect),ci(r),f'{s.speed_change_pct_per_kg:+.3f}%'.replace('-','−'),f'{s.speed_ci_lo_pct:+.3f}~{s.speed_ci_hi_pct:+.3f}%'.replace('-','−'),qtext(r.q_BH)])
prows=[[f'{distance}m',r.rows,f(r.effect),ci(r),qtext(r.q_BH)] for distance,r in pair.iterrows()]
recent=e.query("variant=='primary' and target=='time_s' and exposure in ['burden','increase_kg'] and period in ['confirmation','2026partial']")
rrows=[[('同馬·同경주 효과' if r.family=='row' else '연속 출전 증량'),r.period,f'{r.distance}m',r.rows,f(r.effect),ci(r),qtext(r.q_BH)] for r in recent.itertuples()]
rawrows=[]
labels={'stableUnder1':'−1kg 초과~+1kg 미만','up1toUnder3':'+1kg 이상~+3kg 미만','up3toUnder5':'+3kg 이상~+5kg 미만','up5plus':'+5kg 이상'}
for key in labels:
    r=groups[(groups.distance==1000)&groups.change_group.eq(key)].iloc[0];rawrows.append([labels[key],r.pairs,f'{r.mean_burden_change_kg:+.2f}kg',f'{r.mean_time_delta_s:+.3f}초',f'{r.mean_previous_finish_fraction:.3f}'])
sens=e.query("period=='full' and target=='time_s' and exposure in ['burden','increase_kg','burden_body']")
sensrows=[[r.family,f'{r.distance}m',r.variant,r.exposure,f(r.effect),ci(r),qtext(r.q_BH)] for r in sens.itertuples()]
rcrows=[[f'{r.distance}m',r.pairs,f'{r.weight_delta_time_delta_pearson:.3f}',f'{r.weight_delta_speed_delta_pearson:.3f}'] for r in rawcorr[rawcorr.selection.eq('all_changes')].itertuples()]
bodyrows=[[f'{int(r.race_distance_m)}m',r.body_bin,r.starts,f'{r.body_mean_kg:.1f}',f'{r.burden_mean_kg:.2f}',f'{r.load_mean_pct:.2f}%'] for r in bodygroups[bodygroups.race_distance_m.isin([1000,1110])].itertuples()]
body='''# 제주 마체중과 부담중량 및 증량에 따른 속도 변화

2017년부터 2026년 9월 19일까지 정상 완전순위인 5,206경주·52,155출전·2,813두를 분석했다. **마체중과 부담중량의 원시 상관은 약하다. 같은 말의 부담중량이 커질 때 완주시간이 소폭 늘어나는 연관성은 관찰됐지만, 직전 대비 증량의 일정한 초 단위 효과는 최근 기간과 설계에 따라 불확실해 고정 보정률을 채택하지 않았다.**

이전 환경·게이트 연구의 해석은 [능력 평가와 환경 조건 해석 보존](../20261008_weight_speed_v1/CONTEXT_SNAPSHOT.md)에 저장했다. 말의 반복 수행과 최근 상태를 평가 중심에 두되, 함수율·월·게이트 영향을 없다고 처리하지 않는다. 이번 연구는 Top3 선택이 아닌 완주시간과 평균속도의 관찰 연구다.

## 마체중과 부담중량의 상관관계

전체 Pearson 상관은 **r=0.117**, 말 단위 재표집 95% 구간은0.091~0.143이었다. Spearman은0.092다. 같은 말 안에서 평균을 뺀 상관은−0.010, 경주와 말의 공통 효과를 모두 분리한 잔여 상관은−0.030이었다. 다른 말끼리 큰 말이 조금 더 무거운 부담중량을 지는 경향은 있으나, 같은 말의 마체중 증가와 부담중량 증가는 거의 함께 움직이지 않았다. 이것은 중량 배정 규칙이나 원인의 검증이 아니다.

'''+table(['거리','출전','원시 Pearson r','말 재표집 95% 구간','같은 말 안 r','경주·말 분리 잔여 r'],crows)+'''
1610m는84출전이지만9경주뿐이라 일반화하지 않는다. 전체 평균 마체중은278.23kg, 부담중량은55.07kg이며 출전별 부담중량÷마체중의 평균은19.90%다. 평균 중량끼리 나눈 값과 출전별 비율의 평균은 다르다. [상관 전체 표](body_burden_correlations.csv)를 보존했다.

1000m·1110m의 체중 구간별 관측 부담 비율은 다음과 같다. 경계는 결과에 따른 최적화가 아닌 서술용 구간이다.

'''+table(['거리','마체중 구간 kg','출전','평균 마체중 kg','평균 부담 kg','평균 부담 비율'],bodyrows)+'''
작은 말은 산술적으로 같은 부담중량의 체중 대비 비율이 높다. 그러나 부담중량×마체중 상호작용은 어느 거리에서도 BH 기준을 통과하지 못했다. ‘작은 말은1kg 증가에 몇 배 더 손해’ 또는 최적 마체중·부담 비율은 확정하지 않았다. 이 구간 평균은 체중 변화의 속도 효과가 아니다.

## 같은 말과 경주를 고려한 부담중량과 기록의 관계

거리별로 경주와 말 고정효과를 동시에 분리했다. 최근 동일거리 기록, 마지막 동일거리 착순 비율, 경력·간격·사건 당시 나이·마체중과 그 제곱·성별·출발번호를 고려했다. 아래는 **부담중량1kg 증가당 조건부 연관성**이다. 같은 경주 공통 함수율·월·등급·평균 페이스 수준은 경주 효과에 흡수된다. 완주시간의 양수는 느려진 방향이며 속도는 거리÷완주시간인 평균속도다.

'''+table(['거리','출전','시간 차이 초/kg','점별 95% 구간','평균속도 변화 %/kg','속도 95% 구간','시간 BH q'],mrows)+'''
800~1200m의 전체기간 시간·속도 결과는 다중비교 후에도 느려지는 연관성이 남았다.1000m는+0.056초/kg,1110m는+0.069초/kg이며 평균속도는 각각약−0.066%·−0.072%/kg다.1300·1400m는 시간 구간이0을 포함하고1610m는 표본 부족으로 회귀 미추정이다.이번 분석은10두에 제한하지 않아 게이트 연구의47·63·2경주 대신1300·1400·1610m가63·88·9경주다.게이트 연구의 적용 범위 자체를 변경한 것이 아니다.

마체중을 일정하게 두는 선형 모형에서1000m+3kg의 설명값은약+0.17초다. 이는 평균 연관성을3배한 값이며, 해당 말의 다음 경주가 실제로0.17초 느려진다는 예측이나 채택된 기록 환산값이 아니다. 중량 배정은 무작위가 아니며 변하는 능력·기수·전개 등 잔여 교란이 남는다.

말 효과를 빼고 경주 효과만 사용하면800~1200m의 부담중량 계수는 오히려 빠른 방향으로 바뀌었다. 능력이 좋은 말의 중량 배정과 말 자체 능력이 섞이는 문제를 보여준다. 말 효과를 포함한 모형의 양수 계수도 순수 물리효과의 인과 인증은 아니다. [전체 계수와 민감도](effects.csv)를 확인한다.

![마체중과 부담중량 및 증량 관련 기록 변화](body_load_speed.png)

파란색은 경주·말 고정효과의 중량 수준 비교, 주황색은 다음 절의 같은 말 연속 출전에서 양의 중량 변화에 대한 기울기다. 두 설계의 비교 대상은 완전히 같지 않다. [그림 PDF](body_load_speed.pdf)를 제공한다.

## 같은 말이 같은 거리와 등급에 연속 출전했을 때

같은 공식 말 ID·정확 거리·원문 등급·연도를 유지하고7~60일 간격으로 이어지는 적격 정상 출전27,230쌍을 비교했다. 사이에 부적격 경주나 다른 거리 출전이 있을 수 있으므로 경력 전체에서 바로 직전 출전이라고 설명하지 않는다. 양의 부담 증감과 음의 부담 증감을 별도 기울기로 적합했다. 마체중 변화·이전 부담중량·간격·이전 상대 기록과 착순·함수율·연중 시점·출발번호·두수 변화 등을 고려했다.

아래는 부담중량이 증가하는 쪽의1kg당 시간 차이다.

'''+table(['거리','출전 쌍','증량 시간 차이 초/kg','점별 95% 구간','BH q'],prows)+'''
전체기간900·1000m는 증량과 느려진 시간의 연관성이 다중비교 후에도 남았다.1110m는+0.066초/kg이지만 시간 구간이0을 약간 포함했다.같은 주로상태·같은 달·마체중 변화5kg 이내로 제한하거나 같은 기수로 제한하면 표본이 줄고 모든 거리의 시간 대비가 BH 기준을 통과하지 못했다.이는 효과가 없다는 증명이 아니다.

전체 연속 출전의 조정 전 상관은 다음과 같다.증감량과 시간 변화의 양수는 증량할수록 느려진 방향,증감량과 속도 변화의 음수는 증량할수록 속도가 낮아진 방향이다.

'''+table(['거리','출전 쌍','중량 증감과 시간 변화 r','중량 증감과 속도 변화 r'],rcrows)+'''
1000m의 원시 상관은 시간과+0.210,속도와−0.215였으나,증량한 출전만 보면+0.147·−0.151로 약했다.관측 자체로 직접적인 감속 원인을 확정하지 않는다.[원시 쌍 상관 전체](raw_pair_correlations.csv)에 증가 출전만의 결과도 보존했다.

## 원시 시간 차이를 중량 효과로 읽으면 안 되는 이유

1000m에서 부담 증감 폭으로 나눈 단순 집계는 다음과 같다.마지막 열의 직전 착순 비율은0이1착,1이최하위이므로 작을수록 직전 성적이 좋다.

'''+table(['부담 증감군','출전 쌍','평균 증감','평균 원기록 변화','직전 착순 비율'],rawrows)+'''
증량군은 직전 성적이 훨씬 좋다.직전의 좋은 성적에서 다음 경주에 평균 쪽으로 돌아오는 현상과 경주 조건 변화가 증량의 영향에 섞인다.1000m에서 직전 성적 통제를 빼면 양의 변화 계수는+0.204초/kg,넣으면+0.065초/kg였다.1110m는+0.240에서+0.066초/kg로 줄었다.통제 방식도 정답은 아니므로 두 결과와 한계를 함께 보존했다.원시0.4~0.8초 차이를 전부 증량 탓으로 환산하지 않는다.

## 최근 기간에서 재현되는가

기간 표기는 confirmation=2024~2025년,2026partial=2026년1월부터9월19일까지다. 같은 과거 자료를 다시 나눈 후향 비교이며 신규 독립 검증이나 과거 계수를 고정한 미래 예측 평가가 아니다.

'''+table(['설계','기간','거리','출전 또는 쌍','시간 차이 초/kg','점별 95% 구간','BH q'],rrows)+'''
경주·말 효과를 분리한 수준 비교에서는2024~2025년1000·1110·1200m가 느려지는 방향으로 재현됐고,2026년 부분기간은1110·1200m가 BH 기준을 충족했다.1000m2026년 시간 구간은0을 조금 포함했다.그러나 **연속 출전의 양의 증량 기울기는2024~2025년과2026년 모두 어느 거리에서도 BH 기준을 통과하지 못했다.** 최근 고정1kg 보정치를 확정하기에 설계와 기간의 일치가 부족하다.

## 연구 범위와 방법

현재 시행 기록이 있는8개 거리를 대상으로2017년 이후 정상 완전순위 경주를 사용했고,400m와2017년 이전은 현재 대상 효과 추정에서 제외했다.7~13두 편성을 포함하며 말 ID 제외 정책을 지켰다.보유 상한은2026-09-19,2026년은 부분연도다.마체중 원문은200~367kg,부담중량은49~74kg로 모두 양수이며 임의의 값으로 교정하지 않았다.1kg 기울기는 전 범위의 선형 근사다.

기존 quality 뷰에서 보존한 추출의 시간·착순·조건을 그대로 사용하고,공식 출전 API ID로 읽기 전용DB의 마체중 원문·기수를1:1 연결했다.부담중량은quality 추출과 전수 일치했고,고정 무작위 표본과 극단값260출전은 원본API의wgHr·wgBudam에 직접 대조했다.마체중 괄호 안 원문은 보존하지만 동일거리 이전 체중 차이로 가정하지 않았다.쌍의 체중 변화는 두 출전의 실제 체중으로 계산했다.

현재 경주의 마체중과 실제 부담중량은 사후 설명 자료다.당일 마체중이T−2에 알려졌다고 간주하거나 기존 모델의 과거 체중 변수를 바꾸지 않는다.능력 통제 이력은 공식 말 ID·정확 거리의T−2 이전 출전만 사용했고 사건 당시 원문 나이를 사용했다.현재2026년 고정 나이를 과거 나이로 쓰지 않았다.

주 모형의 경주·말 고정효과는 희소 연립식으로 분리하고 표적 중량·마체중 계수에는 수축을 주지 않았다.통제변수만 표준화해ridge1을 적용했다.연속 출전은 이전 성적 등을 포함한 차분 회귀다.날짜 군집과 말 군집 공분산을 교차항 차감 없이 더하고 잔여 자유도 및 작은 군집 수의t 임계값을 사용했다.연속 출전의 날짜 군집은 뒤 출전일 기준이라 서로 다른 말이 앞 출전일만 공유할 때의 상관은 완전히 반영하지 못한다.중첩 쌍과 동일말 반복은 말 군집에 포함되지만 이 날짜 한계는 남는다.

BH는 설계·기간·민감도·노출별로 지원 거리와 두 시간 목표 전체에 적용했다.점별95%구간은 동시 신뢰구간이 아니다.속도 변화는100×log(시간)의 계수b를100×(exp(−b/100)−1)로 바꿨으며 순수 순간속도나 단순 회귀평균 실제 속도 차이로 설명하지 않는다.

주 모형은30경주·20일·30두 이상,연속 출전은100쌍·30일·30두 이상과 잔여 자유도20 초과만 추정했다.미지원 구간은0으로 채우지 않았다.[지원과 보류](support.csv),[연도별 출전](annual_support.csv),[연도별 쌍](pair_support.csv)을 보존했다.

## 전체기간 민감도 표

row=경주·말 수준 모형,pair=연속 출전 변화 모형이다.race_only=말 효과 제외,no_history=이전 수행 통제 제외,exact_ten=정확10두,interaction=중량×마체중,no_previous_performance=직전 수행 통제 제외,stable_conditions=같은 함수율 구간·달·마체중 변화5kg 이내,same_jockey=같은 기수다.burden_body는 마체중10kg 증가당 초/kg 기울기의 변화다.

'''+table(['설계','거리','민감도','노출','기울기','점별 95% 구간','BH q'],sensrows)+'''
## 저장과 검증

[계획](PLAN.json),[실행 코드](analyze.py),[재검산 코드](verify_plot.py),[입력 해시](source_manifest.json),[입력 감사](input_audit.json),[출전 연결](source_lineage.csv),[두 출전 연결](pair_lineage.csv),[모형 계수와 공분산](models.json),[분석 검증](verification.json),[계산 재검산](calculation_verification.json)을 보존했다.176개 결과 모형의 대비·구간·속도 환산·BH를 확인하고14개 주 모형의 계수와 군집 점수를 별도 NumPy 계산으로 확인했다.고정효과의 전체 희소 연립식과 투영식 계수 차이는최대2.16×10⁻⁸이었다.

첫v1은API ID가 인덱스와 열에 동시에 있어1:1 연결 단계에서 중단됐으며 효과 추정은0회였다.[실행 중단 기록](../20261008_weight_speed_v1/IMPLEMENTATION_FAILURE.json)을 보존하고 인덱스 처리만 수정한v2에서 같은 사전 계획을 실행했다.앞선 환경 해석의 보존본은v1에 그대로 남겼다.

**연구 결과는 작은 감속 연관성의 근거이며 고정1kg당 환산표의 채택은 아니다.** 신규 미래 검증·물리적 인과 실험·입상 확률 개선을 수행하지 않았다.DB·공통 운영 앱·모델 등록부를 변경하지 않았다.결론은[마체중과 부담중량 주제 문서](../conclusions/04_WEIGHT_SPEED.md)에 연결했다.
'''
new('README.md',body)
decision={'objective':'body_mass_carried_weight_and_weight_increase_average_speed','period_start':'2017-01-01','period_end':'2026-09-19','source_rows':52155,'races':5206,'horses':2813,'same_horse_distance_year_grade_pairs':27230,
          'pooled_body_burden_pearson':float(c0.pearson_raw),'pooled_within_horse_body_burden_pearson':float(c0.within_horse_pearson),
          'row_full_slower_seconds_BH_distances':main[main.q_BH.lt(.05)&main.effect.gt(0)].index.astype(int).tolist(),
          'pair_full_increase_slower_seconds_BH_distances':pair[pair.q_BH.lt(.05)&pair.effect.gt(0)].index.astype(int).tolist(),
          'pair_recent_significant_slower_seconds_cells':int(((recent.family=='pair')&(recent.effect>0)&(recent.q_BH<.05)).sum()),
          'body_size_modifier_confirmed':False,'fixed_perkg_correction_adopted':False,'causal_physical_effect_identified':False,'future_independent_validation':False,'operational_change':False}
write(H/'decision.json',decision)

summary='''# 제주 마체중과 부담중량 및 속도 변화

2026년10월8일 완료.2017~2026-09-19 정상 완전순위5,206경주·52,155출전·2,813두의 관찰 연구다.7~13두 편성을 포함하며 앞선 정확10두 게이트 연구와 모집단이 다르다.2026년은 부분연도다.

**마체중과 부담중량의 원시 상관은약하다.같은 말의 부담중량 증가와 작은 기록 저하의 연관성은 관찰됐지만,고정1kg 환산치는 채택하지 않았다.**

## 마체중과 부담중량

전체Pearson r=0.117(말 재표집95%0.091~0.143),같은 말 안 r=−0.010이다.큰 말에 조금 더 무거운 중량이 배정되는 횡단면 연관성은 있지만,같은 말의 체중 증가와 중량 증가는 거의 함께 움직이지 않았다.마체중 평균278.23kg·부담55.07kg,출전별 부담÷마체중 평균19.90%다.마체중×부담중량 상호작용은어느 거리에서도BH를 통과하지 못해작은 말의 추가 손해나 최적 비율을 확정하지 않았다.

## 부담중량과 시간 및 평균속도

거리별 경주·말 고정효과와T−2 동일거리 최근 기록·경력·간격·원문 사건 나이·마체중·게이트 등을 고려했다.같은 경주 공통 함수율·월·등급·페이스 수준은경주 효과에 흡수된다.아래는관찰 연관성이지순수 물리효과나확정 보정표가 아니다.

'''+table(['거리','시간 차이 초/kg','점별95% 구간','평균속도 변화 %/kg'],[[f'{dd}m',f(main.loc[dd].effect),ci(main.loc[dd]),f'{speed.loc[dd].speed_change_pct_per_kg:+.3f}%'.replace('-','−')] for dd in [800,900,1000,1110,1200]])+'''
800~1200m 전체기간 시간·속도 대비는BH 기준을충족했다.1300·1400m는구간이0을포함,1610m는9경주로미추정이다.같은말·거리·등급·연도7~60일연속출전27,230쌍의양의증량기울기는900m+0.098초/kg(95%+0.041~+0.155),1000m+0.065초/kg(+0.022~+0.108)에서BH근거가남았다.

## 기간과 설계에 따른 불확실성

경주·말 수준 비교에서는2024~2025년1000·1110·1200m,2026년부분기간1110·1200m의느린방향이재현됐다.반면연속출전양의증량기울기는2024~2025년과2026년모두BH근거가남지않았다.같은기수나같은달·함수율·마체중변화5kg이내로제한해도불확실했다.

직전좋은성적으로증량되는선택과평균회귀가섞인다.1000m쌍모형은직전성적통제를빼면+0.204초/kg,포함하면+0.065초/kg다.마체중은현재경주의사후설명측정이며T−2가용입력으로간주하지않는다.쌍날짜군집은뒤출전일기준이라앞출전일을공유하는서로다른말의상관이완전히반영되지않을수있다.

현재고정1kg당환산·최적부담비율·운영반영은채택하지않았다.이후기간분할도같은과거자료의후향비교이며새독립미래검증이아니다.주로영향이없다고처리하지않는[앞선해석보존](../20261008_weight_speed_v1/CONTEXT_SNAPSHOT.md)을유지한다.

- [상세 연구와전체표](../20261008_weight_speed_v2/README.md)
- [상관과체중대비부담비율](../20261008_weight_speed_v2/body_burden_correlations.csv)
- [시간·속도효과와기간·민감도](../20261008_weight_speed_v2/effects.csv)
- [연속출전원시상관](../20261008_weight_speed_v2/raw_pair_correlations.csv)
- [원천감사](../20261008_weight_speed_v2/input_audit.json)와[계산재검산](../20261008_weight_speed_v2/calculation_verification.json)
'''
(C/'04_WEIGHT_SPEED.md').write_text(summary,encoding='utf-8')
p=C/'README.md';txt=p.read_text();needle='| [원 연구와 버전 목록]';assert needle in txt
txt=txt.replace(needle,'| [마체중과 부담중량 및 속도](04_WEIGHT_SPEED.md) | 마체중·부담중량 상관은약함.증량과작은감속연관,최근연속출전기울기불확실 | 중량연구완료,고정1kg환산미채택 |\n'+needle);txt=txt.replace('모델 기초·환경 보정·거리별 출발번호 연구다.','모델 기초·환경 보정·거리별 출발번호·마체중과 부담중량 연구다.');p.write_text(txt,encoding='utf-8')
p=C/'SOURCES.md';txt=p.read_text();needle='\n같은 출전 자료가 여러 버전에';assert needle in txt
txt=txt.replace(needle,'\n| [20261008_weight_speed_v2](../20261008_weight_speed_v2/README.md) | **최신 마체중·부담중량·증량과속도연구.52,155출전·27,230쌍,경주와말효과·최근기간·민감도.고정kg환산미채택.v1은효과추정전연결구현중단으로보존** |\n'+needle);p.write_text(txt,encoding='utf-8')
reg=json.loads((C/'research_register.json').read_text());assert not any(t['id']=='weight_speed' for t in reg['topics'])
reg['topics'].append({'id':'weight_speed','title':'마체중과 부담중량 및 속도 변화','conclusion':'04_WEIGHT_SPEED.md','latest_source':'../'+H.name+'/README.md','period_start':'2017-01-01','period_end':'2026-09-19','population':'normal_complete_all_fields_positive_body_and_carried_weight','distances_m':[800,900,1000,1110,1200,1300,1400,1610],'status':'observational_weight_speed_study_completed_no_fixed_perkg_correction','source_rows':52155,'races':5206,'pairs':27230,'body_burden_pearson':float(c0.pearson_raw),'fixed_perkg_correction_adopted':False,'operationally_applied':False,'decision_source':'../'+H.name+'/decision.json'});write(C/'research_register.json',reg)

# Validate the displayed full-period seconds/kg table independently from rendering.
for row in mrows:
    dd=int(row[0][:-1]);assert abs(float(row[2].replace('−','-'))-main.loc[dd].effect)<=.000501
    assert abs(float(row[4].replace('−','-').rstrip('%'))-speed.loc[dd].speed_change_pct_per_kg)<=.000501
links=0
for p in [H/'README.md',V1/'CONTEXT_SNAPSHOT.md',C/'04_WEIGHT_SPEED.md',C/'02_ENVIRONMENT_CORRECTION.md',C/'README.md',C/'SOURCES.md']:
    for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
write(H/'publication_verification.json',{'status':'passed','local_links_checked':links,'rendered_seconds_and_speed_table_checked':True,'prior_immutable_sources_unchanged':True,'figure_visual_review':'passed','management_previous_hashes':previous,'management_current_hashes':{key:sha(ROOT/key) for key in previous}})
v1items=[{'path':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(V1.iterdir()) if p.is_file() and p.name!='artifact_manifest.json'];write(V1/'artifact_manifest.json',{'files':v1items,'outcome_estimation_performed':False,'interpretation_checkpoint_valid':True,'total_bytes_excluding_this_manifest':sum(i['bytes'] for i in v1items)})
art=[{'path':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(H.iterdir()) if p.is_file() and p.name!='artifact_manifest.json'];write(H/'artifact_manifest.json',{'files':art,'total_bytes_excluding_this_manifest':sum(i['bytes'] for i in art),'local_links_checked':links,'v1_source_implementation_failure_preserved':True})
files={i['path']:i for i in central['files']}
for key,item in files.items():
    if item['role']=='conclusion_or_management':item.update(sha256=sha(ROOT/key),bytes=(ROOT/key).stat().st_size)
path=C/'04_WEIGHT_SPEED.md';key=str(path.relative_to(ROOT));files[key]={'path':key,'role':'conclusion_or_management','sha256':sha(path),'bytes':path.stat().st_size}
for name in ['README.md','PLAN.json','CONTEXT_SNAPSHOT.md','RETRY_PROVENANCE.json','analyze.py','verify_plot.py','publish.py','body_burden_correlations.csv','body_load_groups.csv','effects.csv','raw_pair_correlations.csv','raw_change_groups.csv','support.csv','source_manifest.json','input_audit.json','verification.json','calculation_verification.json','decision.json','publication_verification.json','artifact_manifest.json']:
    path=H/name;key=str(path.relative_to(ROOT));files[key]={'path':key,'role':'source_weight_speed','sha256':sha(path),'bytes':path.stat().st_size}
path=V1/'artifact_manifest.json';key=str(path.relative_to(ROOT));files[key]={'path':key,'role':'source_weight_speed_initial_failure','sha256':sha(path),'bytes':path.stat().st_size}
central['files']=list(files.values());central['verification'].update(local_links_checked=links,research_topics=4,weight_speed_completed=True,weight_fixed_perkg_correction_adopted=False,prior_research_sources_unchanged=True);central['managed_files_bytes_excluding_this_manifest']=sum(i['bytes'] for i in files.values() if i['role']=='conclusion_or_management');write(C/'source_manifest.json',central)
assert all(sha(ROOT/i['path'])==i['sha256'] for i in central['files'])
print(json.dumps({'study_files':len(art),'study_bytes':sum(i['bytes'] for i in art),'initial_failure_files':len(v1items),'links_checked':links,'central_source_hashes_verified':True,'research_topics':4},indent=2))
