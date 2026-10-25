"""Reader report, publication data and figures for body-mass questions."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures';F.mkdir(exist_ok=True)
m=pd.read_csv(O/'models.csv');c=pd.read_csv(O/'contrasts.csv');audit=json.loads((O/'source_audit.json').read_text());v=json.loads((O/'verification.json').read_text());personal=json.loads((O/'individual_summary.json').read_text());variation=json.loads((O/'variation_summary.json').read_text());distbody=pd.read_csv(O/'distance_body_distribution.csv');assert v['passed']
font=Path('/System/Library/Fonts/AppleSDGothicNeo.ttc')
if font.exists():font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']=[font_manager.FontProperties(fname=str(font)).get_name(),'DejaVu Sans']
plt.rcParams.update({'axes.unicode_minus':False,'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':175})
def model(metric,meet='전체',window='all',spec='main',dist=0):return m[m.metric.eq(metric)&m.meet.eq(meet)&m.window.eq(window)&m.specification.eq(spec)&m.distance_m.eq(dist)].iloc[0]
def contrasts(metric,meet='전체',window='all',spec='main',dist=0):return c[c.metric.eq(metric)&c.meet.eq(meet)&c.window.eq(window)&c.specification.eq(spec)&c.distance_m.eq(dist)]
def one(metric,target,**kwargs):return contrasts(metric,**kwargs)[lambda q:q.target_kg.eq(str(target))].iloc[0]
def ci(a,scale=1):return f'{a.difference_per1000m*scale:+.3f} [{a.lower*scale:+.3f}, {a.upper*scale:+.3f}]'+(' 잠정' if not a.supported else '')
fig,axes=plt.subplots(1,2,figsize=(11.8,5))
for ax,metric,title in zip(axes,['change','past_relative'],['원문 증감 · 변화0kg 대비','과거5개 체중 평균 대비 편차']):
 for window,label,col in [('all','전체 기간','#326bab'),('complete_2024_2025','2024~2025','#cf7743')]:
  a=model(metric,window=window);xx=np.linspace(-20,20,121);ax.plot(xx,a.beta_linear*xx/10+a.beta_quadratic*(xx/10)**2,color=col,label=label)
  q=contrasts(metric,window=window).copy();q['kg']=pd.to_numeric(q.target_kg);q=q.sort_values('kg');ax.errorbar(q.kg,q.difference_per1000m,yerr=np.array([q.difference_per1000m-q.lower,q.upper-q.difference_per1000m]),fmt='o',capsize=3,color=col,alpha=.8)
 ax.axhline(0,color='#999',lw=1);ax.axvline(0,color='#aaa',lw=1);ax.set_title(title);ax.set_xlabel('체중 변화 또는 기준 대비 편차 kg');ax.set_ylabel('시간 차이 초/1000m · 양수는 느림');ax.grid(alpha=.15);ax.legend(fontsize=9)
fig.suptitle('같은 말에서 큰 체중 변화와 편차는 느린 기록에 동반됐다',fontsize=14);fig.text(.5,.015,'같은 말×거리·같은 경주·부담중량·이력 통제 · 점별95%구간 · 관찰 관계이며 증감 처방이나 인과 손실이 아님',ha='center',fontsize=9);fig.tight_layout(rect=[0,.07,1,.92]);fig.savefig(F/'body_change_curves.png');plt.close(fig)
fig,axes=plt.subplots(1,2,figsize=(11.8,5.2))
for ax,meet in zip(axes,['서울','부산']):
 q=distbody[distbody.scope.eq('all')&distbody.meet.eq(meet)].sort_values('distance_m');y=np.arange(len(q));ax.errorbar(q.body_median,y,xerr=np.array([q.body_median-q.body_p20,q.body_p80-q.body_median]),fmt='o',color='#326bab',capsize=4,label='전체 출전 P20~P80')
 older=distbody[distbody.scope.eq('age4plus')&distbody.meet.eq(meet)].set_index('distance_m').loc[q.distance_m];ax.scatter(older.body_median,y+.12,marker='s',color='#cf7743',s=25,label='4세 이상 중앙값');ax.set_yticks(y,[f'{x}m' for x in q.distance_m]);ax.invert_yaxis();ax.set_title(meet);ax.set_xlabel('관측 마체중 kg');ax.grid(axis='x',alpha=.15);ax.legend(fontsize=8)
fig.suptitle('거리별 출전 체중 분포를 최적체중으로 해석할 수는 없다',fontsize=14);fig.text(.5,.015,'선은 관측 P20~P80 · 신뢰구간이 아님 · 같은 말/경주 모형에서13거리의 절대 최적체중 후보는 확인되지 않음',ha='center',fontsize=9);fig.tight_layout(rect=[0,.07,1,.92]);fig.savefig(F/'distance_body_distributions.png');plt.close(fig)
fig,ax=plt.subplots(figsize=(10,4.8));values=[personal['eligible_groups'],personal['estimable_full'],personal['full_candidate_groups'],personal['full_candidate_bh05_groups']];labels=['표본 기준 충족','개별 곡선 추정 가능','점별 기준 U자 후보','다중비교 통과 후보'];ax.barh(labels,values,color=['#9baec3','#6d94bb','#cf7743','#c65354']);ax.invert_yaxis();ax.set_xlim(0,max(values)*1.18);ax.set_xlabel('같은 지역·거리의 말 그룹 수');ax.spines[['top','right']].set_visible(False)
for i,n in enumerate(values):ax.text(n+1,i,str(n),va='center')
fig.suptitle('말별로 확정할 수 있는 최적체중은 아직 부족하다',fontsize=14);fig.text(.5,.015,f"24출전·8체중값·20kg 범위 기준 · 시간 분할 학습 후보{personal['train_candidate_groups']}개 중 후기 추정 가능{personal['train_candidates_with_test_curve']}개 · BH 통과 반복 후보0개",ha='center',fontsize=9);fig.tight_layout(rect=[0,.07,1,.92]);fig.savefig(F/'individual_optimum_support.png');plt.close(fig)

def table(metric,scale=1.2):
 lines=['| 증감/편차 | 전체기간 차이 [95%구간] | 최근2024~2025 차이 [95%구간] |','|---|---:|---:|']
 for target in [-20,-10,-5,5,10,20]:lines.append(f'| {target:+}kg | {ci(one(metric,target),scale)} | {ci(one(metric,target,window="complete_2024_2025"),scale)} |')
 return '\n'.join(lines)
rel=model('relative');past=model('past_relative');change=model('change');absolute=model('absolute');absdist=m[m.metric.eq('absolute')&m.window.eq('all')&m.specification.eq('main')&m.distance_m.gt(0)];reldist=m[m.metric.eq('relative')&m.window.eq('all')&m.specification.eq('main')&m.distance_m.gt(0)];pastdist=m[m.metric.eq('past_relative')&m.window.eq('all')&m.specification.eq('main')&m.distance_m.gt(0)]
bins=['| 원문 증감 구간 | 0kg 대비 초/1000m [95%구간] |','|---|---:|']
for a in contrasts('change_bins').itertuples():bins.append(f'| {a.target_kg}kg | {ci(a)} |')
disttable=['| 지역 | 거리 | 관측 중앙체중 kg | 절대 최소체중 | 평균 대비 최소점 kg | 과거5개 대비 최소점 kg |','|---|---:|---:|---|---:|---:|']
for a in absdist.itertuples():
 b=model('relative',a.meet,dist=a.distance_m);p=model('past_relative',a.meet,dist=a.distance_m);median=distbody[distbody.scope.eq('all')&distbody.meet.eq(a.meet)&distbody.distance_m.eq(a.distance_m)].body_median.iloc[0]
 def vertex(z):return f'{z.vertex_kg:+.1f}'+('†' if z.curvature_bh_q>=.05 else '') if z.minimum_supported else '미확정'
 disttable.append(f'| {a.meet} | {a.distance_m}m | {median:.0f} | 미확정 | {vertex(b)} | {vertex(p)} |')
sens=['| 기준/표본 | 분석 출전 | −10kg 차이 초/1000m | +10kg 차이 초/1000m | 통계적 최소점 |','|---|---:|---:|---:|---|']
for metric,label in [('change','증감'),('relative','전기간 자기평균 편차'),('past_relative','과거5개 자기평균 편차')]:
 for window,spec,wlabel in [('all','main','전체'),('complete_2024_2025','main','2024~2025'),('age4plus','main','4세 이상'),('all','fe_only','이력 통제 제외')]:
  a=model(metric,window=window,spec=spec);sens.append(f'| {label} · {wlabel} | {int(a.n):,} | {ci(one(metric,-10,window=window,spec=spec))} | {ci(one(metric,10,window=window,spec=spec))} | '+(f'{a.vertex_kg:+.2f}kg 부근' if a.minimum_supported else '미확정')+' |')
same=audit['previous_observation_comparable'];matches=audit['previous_observation_matches']
report=f'''# 마체중 변화와 기록 및 적정체중

2026-10-08. **같은 말에서 체중의 큰 증감과 평소 체중에서 큰 편차가 느린 기록에 동반되는 관계가 관찰됐다. 반면 모든 말에 공통인 절대 최적체중이나 거리별로 정해진 최적 kg는 확인되지 않았다.** 말마다 체격이 다른 만큼 자기 체중 이력이 중요한 참조다. 다만 각 말의 최적점을 확정할 만큼 반복 표본과 검증이 충분하지는 않았다.

## 세 가지 체중 질문을 구분한다

‘지난번보다10kg 증가’는 현재 체중과 이전 체중의 변화다. ‘평소보다10kg 무거움’은 그 말의 기준 체중에서 벗어난 정도다. ‘현재500kg’은 절대체중이다.500kg 말이510kg가 됐어도 평소가510kg였다면 평소 체중으로 돌아온 것일 수 있어 세 질문을 섞을 수 없다.

자료는2018년 이후 서울2026-09-20·부산2026-09-18까지의 정상151,074출전·13,928경주·12,435두다.1000~1800m의13지역×정확 거리를 대상으로 같은 말과 같은 경주의 효과를 제거하고 부담중량·나이 제곱·rating·과거 성과·출전수·공백을 고려했다. 성별을 나누거나 성별 계수를 만들지 않았다. 제주·영천·주행심사·주로빠르기는 제외했다. 정상 완주 중 반복 비교가 가능한 말들이 대상이므로 모든 말의 신체 반응을 대표하는 시험은 아니다.

## 체중이 늘거나 줄면 기록은 어떻게 달라졌는가

원문 `wgHr`의 `496(+1)`처럼 체중과 함께 기록된 증감을 읽었다. 수치 증감은 {audit['raw_reported_change_observed']:,}행이다. 빈 괄호 {audit['raw_reported_change_missing']:,}행 중 직전 관측 날짜가 기존 과거 이력의 마지막 날짜와 일치하고 실제 두 체중도 같은 {audit['verified_zero_changes']:,}행만 ‘확인된0kg 변화’로 별도 복원했다. 남은 {audit['effective_change_missing']:,}행은 결측이다. 원래 빈 증감값과 복원 출처는 그대로 보존했다. 단독 말/경주를 제거한 증감 주 분석은 **{int(change.n):,}출전**이다.

아래는 변화0kg 대비 조건부 시간 차이를 **공통 모형에서1200m로 환산한 예시**다. 양수는 느림이다. 여러 거리의 시간/1000m 기울기를 합친 값으로 서울1200m나 부산1200m만의 별도 계수는 아니다. 같은 말의 원기록 두 개를 조건 없이 뺀 차이도 아니다.

{table('change')}

전체기간의−5kg는0kg와 뚜렷한 차이가 없고,큰 증감에서 느린 방향이 커진다. 제곱곡선의 최소점은 변화약{change.vertex_kg:+.1f}kg 부근이지만, 이를 모든 말에게 그만큼 감량하라는 처방으로 해석하지 않는다. 최근2024~2025년의 최소점과 선형항도 달라진다.

제곱식 모양을 강제하지 않은 증감 구간 모형에서도 큰 증감의 느린 방향이 남았다. 다만 작은 감량 구간은0kg와 확실히 구분되지 않아 모든1kg 변화를 벌점으로 처리할 근거는 없다.

{chr(10).join(bins)}

![증감과 과거 평균 편차의 곡선](figures/body_change_curves.png)

## 같은 말의 평소 체중에서 벗어나면

각 말의 전체 관측 평균체중을 기준으로 하면 그 평균에서 양쪽으로 벗어날수록 느린 U자형 관계가 나타났다. 공통 최소점은 평균대비약{rel.vertex_kg:+.2f}kg로 평균에 가깝다.1200m 환산에서−10kg는{one('relative',-10).difference_per1000m*1.2:+.3f}초,+10kg는{one('relative',10).difference_per1000m*1.2:+.3f}초다. 최근완결연도와4세이상에서도 이 관계가 남았다. 그러나 이 기준은 그 말의 나중 출전 체중까지 사용한 후향 참조이므로 그대로 실전 기준으로 쓸 수 없다.

그래서 **현재 출전을 제외한 직전5개 관측 체중 평균(최소3개)**으로 다시 계산했다. 이 기준을 만들 때 현재·미래 체중을 쓰지 않았다. 같은 말/경주와 이력을 맞춘 **{int(past.n):,}출전**에서 U자형 관계가 남았지만 차이는 더 작았다. 후향/과거 기준은 표본도 달라져 차이가 줄어든 원인을 참조방식 하나로 분해하지 않는다. 과거 관측 사이에 원자료에 없는 경주가 있을 수 있어 직전5개 ‘모든 공식 경주’를 완전히 복원했다는 뜻은 아니다.

다음 표는 과거5개 평균에서 벗어난 정도에 따른 **공통 모형의1200m 환산**이다.

{table('past_relative')}

예를 들어 과거5개 평균이500kg인 말의 현재510kg 출전은 기준500kg 출전보다 공통 모형상 약{one('past_relative',10).difference_per1000m*1.2:.3f}초 느린 방향이고,490kg는 약{one('past_relative',-10).difference_per1000m*1.2:.3f}초다. 이는 집단 평균의 예시이며 각 말에 같은 손실을 적용하는 처방은 아니다. ±5kg의 차이는 작고 ±20kg에서는 커진다. 최적 kg를 임의로 정하기보다 자기 이력의 안정된 범위와 큰 이탈을 함께 보는 근거다. 해당 차이를 확정된 기록 보정으로 채택하지 않았다.

## 말마다 적정체중이 있는가

반복 관측이8회 이상인 {variation['horses_at_least8_starts']:,}두의 말별 평균체중 P10~P90은 약{variation['usual_body_p10']:.0f}~{variation['usual_body_p90']:.0f}kg이고, 말 안의 체중 표준편차 중앙값은 약{variation['within_horse_sd_median']:.1f}kg다. 체격이 서로 다르다는 사실과 평소 범위에서 크게 벗어날 때 느려지는 집단 관계는 확인할 수 있다. 그러나 각 말의 평균체중이 그 말의 최적체중이라는 증명은 아니다.

개별 곡선은 같은 지역·거리에서24출전 이상·8개 체중값 이상·체중 범위20kg 이상을 요구했다. {personal['same_venue_distance_horse_groups']:,}개 말×지역×거리 중 **{personal['eligible_groups']}그룹·{personal['eligible_horses']}두**가 충족했고, rank와 자유도까지 통과해 추정 가능한 것은 {personal['estimable_full']}그룹이었다. 목표는 같은 경주의 다른 말 평균보다 몇초 빠르거나 느린지이며, 시간 추세·부담중량·rating·과거 기록을 고려한 별도 탐색이다. 이 개별 모형은 앞의 공동 말/경주 고정효과 모형과 동일하지 않다.

전체 개인 곡선에서 점별 기준을 통과한 U자형 최소 후보는 {personal['full_candidate_groups']}그룹이었다. **여러 말의 검정을 BH로 조정하면 통과 후보는 {personal['full_candidate_bh05_groups']}개**였다. 시간순60%/40%로 나눈 학습 후보는 {personal['train_candidate_groups']}개, 이후 구간에서 곡선을 추정할 수 있는 것은 {personal['train_candidates_with_test_curve']}개이고 그중 {personal['repeat_groups']}개가10kg 이내로 반복됐다. 학습 후보의 다중비교까지 통과한 반복 후보는 {personal['repeat_after_train_bh_groups']}개다. 후기 미추정1개를 반복 실패나 효과0으로 바꾸지 않았다. 이 작은 수로 개인 최적점의 재현율을 일반화하지 않는다.

따라서 **말마다 평소 범위를 따로 참고할 이유는 있지만,현재 자료로 각각의 최적체중을 확정할 수는 없다.** 가장 빨랐던 한 번의 체중이나1승 당시 체중을 그대로 정답으로 삼지 않는다. 시간 분할은 결과자료의 경주 평균을 사용하는 조건부 반복성 진단이며 미래 기록의 사전예측 검증이 아니다.

![개별 적정체중 후보의 표본과 검증](figures/individual_optimum_support.png)

## 거리별로 어울리는 절대체중이 있는가

같은 말과 경주를 맞춘 절대체중의 U자형 모형에서 **13개 거리 조합 모두 통계적으로 지원되는 절대 최소체중은 미확정**이었다. 제곱항이0을 포함하거나 음수이거나, 계산상 꼭짓점이 관측범위 밖이었다. 오목한 곡선의 최대점을 최적체중으로 바꾸지 않았다. ‘1200m는470kg,1800m는500kg’와 같은 공식은 얻지 못했다.

아래의 관측 중앙체중은 실제 출전 집단의 분포다. 최적체중과 구분한다. 상대 최소점은 공동 곡선상 평균 기준의 kg 편차다. †는 점별 기준은 충족하나13거리의 BH q가0.05 이상인 탐색값이다. 미확정은0kg로 채우지 않았다.

{chr(10).join(disttable)}

전기간 자기평균 기준에서는13개 중 {int((reldist.minimum_supported&reldist.curvature_bh_q.lt(.05)).sum())}개가 U자형 기준과 BH를 통과했다. 과거5개 기준으로 바꾸면 {int((pastdist.minimum_supported&pastdist.curvature_bh_q.lt(.05)).sum())}개다. 참조와 표본에 따라 차이가 있으며, 개별 거리의 최소점 차이를 직접 검정하지 않았으므로 거리가 늘수록 최적 편차가 커진다고 확정하지 않는다. 출전 말의 나이·등급·체격·거리 선택이 함께 바뀔 수 있어 거리별 분포를 거리적성의 인과증거로 보지 않는다.

![거리별 체중 분포](figures/distance_body_distributions.png)

## 최근 기간과 성장 영향을 바꿔도 같은가

아래는 초/1000m이며, 실제 거리의 초가 필요하면 거리/1000을 곱한다.4세 이상도 나이·시간 변화가 완전히 제거된 집단은 아니다. FE만 모형은 말/경주 외의 이력·부담중량 통제를 제외한 민감도다.

{chr(10).join(sens)}

과거5개 기준의 최근 부산 곡률 구간은0을 포함한다. 집계 전체의 관계가 각 지역·거리·말에 모두 확정됐다는 뜻은 아니다. 작은 감량의 방향·개별 최소점보다 큰 편차와 느린 기록의 동반 관계를 더 안정적인 결론으로 본다.

## 원천과 계산을 어떻게 검증했는가

공식 원문18파일의151,074행에서 말ID·날짜·거리·체중과 괄호 증감을 대조했다. 사용 가능한 직전 관측 차이와 증감의 비교 {same:,}건 중 {matches:,}건이 일치했다. 불일치187건 중186건은 자료의 직전 관측과 기존 이력의 마지막 날짜가 달라 관측 누락 가능성을 남겼다. 날짜까지 같은1건은 격리 원장에 남기고 그 행을 제외한 민감도를 추가했으며 주 결론이 거의 바뀌지 않았다. 원문 증감을 임의로 고치지 않았다. 구간 합·입력 해시·날짜·누락과 복원 출처를 확인했다.

고정효과 단독 말/경주는 재귀 제거했다. 고정효과 rank는 말+경주−연결요소이며, nuisance/체중 행렬의 rank를 SVD 상대 기준1e-10으로 맞췄다. 몸무게항은10kg 단위 선형+제곱이다. 시간은1000m 환산 후 거리별 통제를 따로 허용해 공통 모형으로 합쳤다. 같은 말/날짜의 거리 간·지역 간 공분산을 포함한 마필/실제 날짜 군집을 썼고, 각 단독과 이원 분산 중 최대·자유도·t 보정을 했다.

대비 지점±3kg에서100행/30두/20날짜, 전체100날짜를 지원 기준으로 삼았다. U최소 후보는 제곱항95%하한>0·꼭짓점P10~P90 안·근방 지원을 모두 요구한다. 분모가 불안정한 꼭짓점·관측범위 밖·오목 곡선은 최적 kg로 게시하지 않는다. 거리별 제곱항은 각 질문13개 family의 BH q를, 개인 곡선은 전체/학습별 BH q를 보존했다. 모든 대비표 전체의 다중비교를 완료했다는 뜻은 아니다.

독립적인 원문 문자열 분리·희소 고정효과 LU 투영·QR 회귀·pandas 군집 합·개인 HC3로 **{v['independent_distance_models']}거리 모형·{v['independent_pooled_models']}공통 모형·{v['independent_individual_models']}개인 모형·{len(v['checks'])}개 수치 검사**를 통과했다. 수치 검증은 체중 변화를 무작위 배정한 실험이나 인과성의 증명이 아니다. 몸무게 변화에 동반하는 성장·컨디션·훈련·휴양과 능력 변화가 남아 있다. 체중의 구성이나 왜 변했는지는 이 자료만으로 구분하지 못한다.

## 재현과 보존

[출처와 방법](SOURCES.md)·[게시 요약](PUBLICATION.md)·[게시 데이터](outputs/publication_summary.json)·[독립 검증](outputs/verification.json)·[파일 용량](outputs/artifact_inventory.json)·[중앙11C](../conclusions/11C_BODY_WEIGHT_CHANGE_OPTIMUM.md)를 남겼다. 기존 완료 연구·DB·운영·배포는 변경하지 않았다.

프로젝트루트에서 `OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/{H.name}/analyze.py`,동일경로의 `individual.py`, `describe.py`, `verify.py`, `render.py` 순서로재현한다. `--change-and-past-only`는실행중자료정의보완시절대/후향편차결과를보존하고나머지만새로계산한옵션이다. 깨끗한재현은옵션없이실행한다. `register.py`는공유목록을수정하므로분석재현시생략한다.
'''
(H/'README.md').write_text(report)
(H/'SOURCES.md').write_text(f'''# 마체중 변화 분석의 출처와 범위

2026-10-08. [성별 연구 모집단](../20261007_sex_ability_gap/outputs/population.parquet)151,074행과 [선택 원장](../20261007_sex_ability_gap/outputs/selection_ledger.parquet)158,528행,기존 보관 KRA 원문18파일을 읽기 전용 사용했다. 입력20파일의SHA-256·기간·원문체중 및 증감 검사·누락/복원 수는 [source_audit.json](outputs/source_audit.json)에 있다. 전출전 성별·체중·공식 부담중량의 원문 연결과 정상 완주 선택은 [기존 출처](../20261007_sex_ability_gap/SOURCES.md)를 계승한다. 새 API를 호출하거나 운영 DB를 조회하지 않았다.

원문 wgHr의 괄호 수치가 있으면 raw_reported_change로 보존했다. 빈 괄호는 일괄0으로 처리하지 않았다. 과거 이력 마지막 날짜와 직전 관측 날짜가 같고 두 관측 체중도 같은9,464행만 verified_zero로 복원했다.684행은 미해결 결측이다. 차이가난187행은 [불일치표](outputs/reported_vs_observed_mismatches.csv)에 있고,날짜까지 일치한1건 제외 모형을 별도 남겼다. 원문 괄호값의 기준과 자료의 직전 관측이 언제나 일치한다고 가정하지 않는다.

평소 체중의 두 정의는 전체 관측 평균과 직전5개 관측 평균(최소3개·현재 제외)이다. 전자는 후향 기술 참조이고 후자는 과거 체중만 쓰지만 발표 당시 최초 확보 시각까지 복원한 것은 아니다. 둘의 표본과 정보 범위가 다르다. 보고서의 시간순 개인곡선 반복은 미래 기록 사전예측 검증이 아니다.

체중 변화·절대체중·자기 평균 대비 편차를 따로 적합했다. 과거 부담중량 연구의 kg 계수를 체중 kg의 손실로 재사용하지 않았다. 같은 말/경주와 이력 통제·민감도·지원·BH·수치허용오차는 [보고서](README.md)와 [계획 및 실행 보충](PLAN.md)에 있다. 개인 모형은 같은 경주 다른 말 평균에 대한 상대시간의 별도 탐색이며 공동 고정효과와 구분한다. 같은 경주 평균을 관측 결과로 계산하므로 사전 능력 예측이 아니다.

원문 증감 파싱·체중 기준·개인 회귀·희소 LU/QR·군집 합과 BH는 [verify.py](verify.py)에서 독립 계산했다. [verification.json](outputs/verification.json), [개인 탐색 결과](outputs/individual_summary.json), [전체 모형](outputs/models.csv), [대비표](outputs/contrasts.csv)를 보존한다. 생물학적 최적체중·인과 손실·개별 체중 처방·채택 보정으로 일반화하지 않는다.

기존 관련150파일의 크기·해시는 [baseline_inventory.json](outputs/baseline_inventory.json), 공유파일 수정직전과 작업별 변경량은 shared_edits_baseline.json/shared_own_edits.json, 자기포함 용량은 [artifact_inventory.json](outputs/artifact_inventory.json)에 있다. code-security의 고정경로/입력보존 기준과 pages:write-page의 주장·수치 검토 기준을 적용했다. 독립 연구수를 바꾸지 않는 기존11번의11C후속으로 연결한다.
''')
pub=f'''# 마체중은 자기 이력과 비교해야 한다

체중이 늘거나 줄었다는 사실만으로 좋고 나쁨을 판단하기 어렵다. 같은 말과 경주,부담중량과 과거 성적을 맞추면 큰 증감이나 평소 범위에서 큰 이탈이 느린 기록에 동반됐다. 작은 변화의 차이는 작고 방향도 조건에 따라 달라진다.

현재를 제외한 과거5개 관측 평균보다10kg 무거운 출전의 차이는 공통 모형의1200m 환산으로 약{one('past_relative',10).difference_per1000m*1.2:.3f}초,10kg 가벼운 출전은 약{one('past_relative',-10).difference_per1000m*1.2:.3f}초 느린 방향이었다. 예를 들어 과거 평균500kg 말에게490/510kg를 비교하는 방식이다. 다른 말의500kg와 같은 의미는 아니다. 이는 집단의 조건부 관계이며 각 말에게 적용할 확정 손실은 아니다.

서울·부산1000~1800m13조합에서 모든 말에게 공통인 절대 최적체중은 확인되지 않았다. 거리별 출전 중앙체중도 그 거리에 유리한 체중을 뜻하지 않는다. 말마다 평소 범위를 따로 참고할 이유는 있지만,개인 최소체중 후보는 다중비교를 통과하지 못했고 이후 반복 검증도 소수였다.

정상완주와 반복 출전 선택,성장과 컨디션 등 미관측 변화가 남는다. 체중의 최초 공개시각을 복원한 사전예측이나 체중변화를 배정한 실험이 아니다. 기록 보정·개별 체중 처방은 채택하지 않았다. [보고서](README.md)·[출처](SOURCES.md)·[검증](outputs/verification.json)·[게시데이터](outputs/publication_summary.json).
'''
(H/'PUBLICATION.md').write_text(pub)
obj=dict(title='마체중 변화와 기록 및 적정체중',as_of='2026-10-08',status='conditional_observational_research; no operational correction',units='seconds per1000m; illustrative1200 values multiply1.2',key_contrasts=c[c.meet.eq('전체')&c.window.eq('all')&c.specification.eq('main')&c.distance_m.eq(0)].to_dict('records'),pooled_models=m[m.meet.eq('전체')&m.specification.eq('main')&m.distance_m.eq(0)].to_dict('records'),individual=personal,variation=variation,absolute_distance_minima_confirmed=int(absdist.minimum_supported.sum()),source_end=audit['source_end'],verified_zero_changes=audit['verified_zero_changes'],unresolved_change_missing=audit['effective_change_missing'],causal=False,operational=False,forecast_validation=False,limitations=['body-change causes not identified','selected normal repeated finishers','full-history mean is retrospective','prior-five references observed history, not necessarily complete racing history','individual exploration differs from main FE','individual and distance multiple comparisons','common-distance normalization imposes scaling'])
def clean(x):
 if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
 if isinstance(x,list):return [clean(v) for v in x]
 if isinstance(x,float) and not np.isfinite(x):return None
 return x
(O/'publication_summary.json').write_text(json.dumps(clean(obj),ensure_ascii=False,indent=2,allow_nan=False)+'\n');print('Body-weight reports, publication data and three figures saved')
