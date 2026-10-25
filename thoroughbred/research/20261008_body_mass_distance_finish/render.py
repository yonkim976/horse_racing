"""Readable report, hypothesis figures and publication-ready research data."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures'
c=pd.read_csv(O/'contrasts.csv');m=pd.read_csv(O/'models.csv');cat=pd.read_csv(O/'categorical_contrasts.csv');a=json.loads((O/'source_audit.json').read_text());v=json.loads((O/'verification.json').read_text());cv=json.loads((O/'categorical_verification.json').read_text());assert v['passed'] and cv['passed']
font=Path('/System/Library/Fonts/AppleSDGothicNeo.ttc')
if font.exists():font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']=[font_manager.FontProperties(fname=str(font)).get_name(),'DejaVu Sans']
plt.rcParams.update({'axes.unicode_minus':False,'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':170})
def select(metric,outcome,comparison,target,window='all',spec='main',meet='전체'):
 return c[c.metric.eq(metric)&c.outcome.eq(outcome)&c.comparison.eq(comparison)&c.target_kg.eq(target)&c.window.eq(window)&c.specification.eq(spec)&c.meet.eq(meet)&c.scope.eq('joint')].iloc[0]
def ci(r,scale=1):return f'{r.estimate*scale:+.3f} [{r.lower*scale:+.3f}, {r.upper*scale:+.3f}]'
def catselect(metric,outcome,group,target,window='all',spec='main',meet='전체'):
 return cat[cat.metric.eq(metric)&cat.outcome.eq(outcome)&cat.group.eq(group)&cat.target.eq(target)&cat.window.eq(window)&cat.specification.eq(spec)&cat.meet.eq(meet)].iloc[0]
fig,axs=plt.subplots(1,2,figsize=(12,5.5))
for ax,outcome,comparison,title,targets,scale in [(axs[0],'finish1000','short','단거리 전체시간 · 공통1200m 환산',[510,10],1.2),(axs[1],'late','long','1600~1800m 마지막200m',[450,-10],1)]:
 for j,(metric,target,label) in enumerate(zip(['absolute','past_relative'],targets,['다른 말 · 절대체중','같은 말 · 자기 기준'])):
  for offset,window,name,color in [(-.12,'all','2018~2026','#326bab'),(.12,'complete_2024_2025','2024~2025','#ca7844')]:
   r=select(metric,outcome,comparison,target,window);ax.errorbar(r.estimate*scale,j+offset,xerr=np.array([[(r.estimate-r.lower)*scale],[(r.upper-r.estimate)*scale]]),fmt='o',capsize=3,color=color,label=name if j==0 else None)
 ax.axvline(0,color='#999',lw=1);ax.set_yticks([0,1],['510kg 대 480kg' if outcome=='finish1000' else '450kg 대 480kg','자기 기준 +10kg' if outcome=='finish1000' else '자기 기준 −10kg']);ax.invert_yaxis();ax.set_ylim(1.5,-.5);ax.set_title(title);ax.set_xlabel('시간 차이 초 · 양수는 느림');ax.grid(axis='x',alpha=.15);ax.legend(fontsize=9)
fig.suptitle('큰 체격과 자기 체중의 증가는 다른 질문이다',fontsize=15);fig.text(.5,.025,'점별95%구간 · 같은 경주/부담중량/이력 통제 · 자기 기준은 같은 말도 통제 · 마지막200m는 앞선 전개를 추가 통제',ha='center',fontsize=9);fig.tight_layout(rect=[0,.08,1,.93]);fig.savefig(F/'hypothesis_contrasts.png');plt.close(fig)
fig,axs=plt.subplots(2,2,figsize=(12,8))
for i,metric in enumerate(['absolute','past_relative']):
 for j,(outcome,group,title,scale) in enumerate([('finish1000','short','단거리 전체시간 · 공통1200m 환산',1.2),('late','long','1600~1800m 마지막200m',1)]):
  ax=axs[i,j];labels=['≤430','431–450','451–469','470–489','490–509','510–529','≥530'] if metric=='absolute' else ['≤−15','−14–−6','−5–+5','+6–+14','≥+15'];base='470–489' if metric=='absolute' else '−5–+5'
  for offset,window,spec,name,color in [(-.12,'all','main','전체 기간','#326bab'),(.12,'complete_2024_2025','main','2024~2025','#ca7844')]:
   for k,label in enumerate(labels):
    if label==base:ax.scatter(k+offset,0,color=color,s=18);continue
    r=catselect(metric,outcome,group,label,window,spec);ax.errorbar(k+offset,r.estimate*scale,yerr=np.array([[(r.estimate-r.lower)*scale],[(r.upper-r.estimate)*scale]]),fmt='o' if r.supported else 'x',capsize=3,color=color,label=name if k==0 else None)
  ax.axhline(0,color='#999',lw=1);ax.set_xticks(range(len(labels)),labels,rotation=20);ax.set_title(('절대체중 · ' if metric=='absolute' else '자기 기준 편차 · ')+title);ax.set_xlabel('kg · 가운데 범주 참조');ax.set_ylabel('시간 차이 초 · 양수는 느림');ax.grid(axis='y',alpha=.15);ax.legend(fontsize=8)
fig.suptitle('극단 체중에서도 두 통념을 함께 지지하지 않았다',fontsize=15);fig.text(.5,.02,'제곱식 모양을 강제하지 않은 사후 탐색 · 점별95%구간 · ×는 지원 표본 부족 · 원래 체격과 같은 말의 변화를 구분',ha='center',fontsize=9);fig.tight_layout(rect=[0,.06,1,.94]);fig.savefig(F/'categorical_tail_checks.png');plt.close(fig)
primary=['| 질문과 체중 정의 | 전체 기간 차이 [95%구간] | 최근2024~2025 | 4세 이상 |','|---|---:|---:|---:|']
questions=[('absolute','finish1000','short',510,'단거리 · 절대510 대480kg',1.2),('past_relative','finish1000','short',10,'단거리 · 자기 기준+10kg',1.2),('absolute','late','long',450,'긴 거리 막판 · 절대450 대480kg',1),('past_relative','late','long',-10,'긴 거리 막판 · 자기 기준−10kg',1)]
for metric,outcome,comparison,target,label,scale in questions:primary.append(f'| {label} | {ci(select(metric,outcome,comparison,target),scale)} | {ci(select(metric,outcome,comparison,target,"complete_2024_2025"),scale)} | {ci(select(metric,outcome,comparison,target,"age4plus"),scale)} |')
direct=['| 직접 검정 | 시간 차이 [95%구간] | BH q |','|---|---:|---:|']
for metric,outcome,comparison,target,label,scale in [('absolute','finish1000','short_minus_long',510,'절대 무거움의 전체시간 효과 · 단거리−긴 거리',1),('past_relative','finish1000','short_minus_long',10,'자기 기준 무거움의 전체시간 효과 · 단거리−긴 거리',1),('absolute','late','long_minus_short',450,'절대 가벼움의 막판 효과 · 긴 거리−단거리',1),('past_relative','late','long_minus_short',-10,'자기 기준 가벼움의 막판 효과 · 긴 거리−단거리',1)]:
 r=select(metric,outcome,comparison,target);direct.append(f'| {label} | {ci(r,scale)} | {r.bh_q:.4f} |')
tail=['| 극단 범주와 참조 | 단거리 전체 · 공통1200m 환산 | 긴 거리 마지막200m | 단거리/긴 거리 범주 표본 |','|---|---:|---:|---:|']
for metric,labels in [('absolute',['≤430','≥530']),('past_relative',['≤−15','≥+15'])]:
 for label in labels:
  r=catselect(metric,'finish1000','short',label);s=catselect(metric,'late','long',label);tail.append(f'| '+('절대' if metric=='absolute' else '자기 기준')+f' {label}kg · 참조 {r.reference}kg | {ci(r,1.2)} | {ci(s)} | {int(r.n):,} / {int(s.n):,} |')
fade=['| 긴 거리의 비교 | 마지막200m | 마지막600m | 마지막200m−직전400m/2 |','|---|---:|---:|---:|']
for metric,target,label in [('absolute',450,'450 대480kg'),('absolute',510,'510 대480kg'),('past_relative',-10,'자기 기준−10kg'),('past_relative',10,'자기 기준+10kg')]:fade.append('| '+label+' | '+' | '.join(ci(select(metric,y,'long',target)) for y in ['late','last600','fade'])+' |')
observed=pd.read_csv(O/'observed_mass_sections.csv');raw=['| 지역·거리 | 절대체중 범주 | 출전 | 전체 평균 초 | 마지막200m 평균 초 | 둔화 평균 초 |','|---|---|---:|---:|---:|']
for meet in ['서울','부산']:
 for dist in [1200,1800]:
  for band in ['≤450','470–489','≥510']:
   r=observed[observed.meet.eq(meet)&observed.distance_m.eq(dist)&observed.mass_bin.eq(band)].iloc[0];raw.append(f'| {meet} {dist}m | {band}kg | {int(r.n):,} | {r.finish_mean:.3f} | {r.late_mean:.3f} | {r.fade_mean:.3f} |')
dt=['| 지역·거리 | 절대510 대480 전체 초 | 자기 기준+10 전체 초 | 절대450 대480 마지막200m 초 | 자기 기준−10 마지막200m 초 |','|---|---:|---:|---:|---:|']
for r in pd.read_csv(O/'eligibility.csv')[lambda q:q.eligible].itertuples():
 def point(metric,outcome,target):return c[c.scope.eq('distance')&c.metric.eq(metric)&c.outcome.eq(outcome)&c.target_kg.eq(target)&c.window.eq('all')&c.specification.eq('main')&c.meet.eq(r.meet)&c.distance_m.eq(r.distance_m)].iloc[0]
 dt.append(f'| {r.meet} {r.distance_m}m | {ci(point("absolute","finish1000",510),r.distance_m/1000)} | {ci(point("past_relative","finish1000",10),r.distance_m/1000)} | {ci(point("absolute","late",450))} | {ci(point("past_relative","late",-10))} |')
report=f'''# 체중이 무거우면 단거리에, 가벼우면 긴 거리 막판에 불리한가

2026-10-08. **검증할 구간 자료는 있지만, 이번 서울·부산 자료는 두 주장을 일반적인 법칙으로 뒷받침하지 않았다.** 원래 체격이 큰 말이 단거리에서 느리다는 결과는 없었다. 같은 말이 최근 평소 체중보다 무거워졌을 때 전체기록이 조금 느린 경향은 남았지만, 긴 거리보다 단거리에 특별히 더 불리하다는 차이는 확인되지 않았다. 가벼운 말이 긴 거리에서 막판에 더 처진다는 결과도 확인되지 않았다.

## 체격이 큰 것과 자기 체중이 늘어난 것을 구분한다

500kg가 자연스러운 말과 평소470kg인데500kg가 된 말은 다른 비교다. 절대체중 모형은 같은 경주에 나온 서로 다른 말의 당일450/480/510kg를 비교하며, 순수하게 타고난 골격의 효과를 분리한 것은 아니다. 같은 말 모형은 현재를 제외한 직전5개 관측 체중 평균(최소3개)에서 벗어난 정도를 비교한다. 현재·미래 체중으로 이 기준을 계산하지 않았다. 절대450/510kg는 비교 예시이며 정상/비정상이나 생리적 ‘과체중’의 경계가 아니다. 체지방·근육량·건강 상태는 관측하지 않았다.

대상은2018년 이후 서울2026-09-20·부산2026-09-18까지 정상151,074출전·13,928경주·12,435두다. 충분한13개 지역×거리의1000~1800m148,126출전을 비교했다. 이 보고서에서 단거리는1000~1400m, 긴 거리는1600~1800m다. 특히1900m 이상은 희소하여2200m 같은 장거리까지 일반화하지 않는다. 제주·영천·주행심사·주로빠르기는 제외했다.

절대체중 비교는 같은 경주·부담중량·연령·rating·과거 성과를 맞췄다. 자기 기준 비교는 같은 말과 같은 경주를 함께 맞췄다. 같은 경주 효과가 지역·거리·날짜·등급·정확 함수율 등 공유 환경을 포함한다. 두 설계는 다른 질문에 답하며, 말 고정효과로 체격이 원래 큰 말과 작은 말 사이의 차이를 추정했다고 하지 않는다. 성별별 기준이나 성별 주모형은 만들지 않았고 절대체중의 성별 통제는 민감도로 보존했다.

## 두 가설의 주분석

아래 첫 두 행은 단거리 공통 기울기를1200m로 환산한 전체시간 예시다. 서울1200m 또는 부산1200m만의 계수는 아래 거리별 표에서 따로 확인한다. 마지막 두 행은1600~1800m의 실제 마지막200m 초다. **양수는 느림, 음수는 빠름**이며 대괄호는 점별95% 불확실성 구간이다.

{chr(10).join(primary)}

절대510kg는480kg보다 단거리에서 느리지 않았다. 전기간 주모형에서는 약0.022초 빠른 방향이었지만, 성별을 추가하면{ci(select('absolute','finish1000','short',510,spec='sex_control'),1.2)}초이고4세 이상에서도0을 포함한다. 따라서 ‘무거우면 느리다’를 지지하지 않으며, 반대로 무조건 큰 말이 유리하다는 처방도 하지 않는다.

자기 기준보다10kg 무거운 출전은 공통1200m 환산 약0.042초 느렸다. 최근 완결연도와4세 이상에서도 느린 방향이 남는다. 그러나 같은+10kg의 긴 거리 전체기록 차이는 초/1000m 기준{ci(select('past_relative','finish1000','long',10))}로 나타났다. 이 경향을 단거리만의 약점으로 해석할 수 없다.

긴 거리에서 절대450kg는480kg보다 마지막200m가 약0.016초 빠른 방향이고, 자기 기준−10kg의 마지막200m 차이는0을 포함한다. 가벼움이 막판 시간 증가에 동반된다는 주가설은 지지되지 않았다. 차이가 작고 조정 조건에 의존하므로 가벼울수록 좋다는 주장으로 뒤집지 않는다.

![두 가설의 주대비](figures/hypothesis_contrasts.png)

## 단거리와 긴 거리의 차이를 직접 비교하면

‘한쪽만 유의하다’는 이유로 거리 차이를 주장하지 않고, 두 거리군의 차이를 같은 회귀에서 직접 비교했다. 첫 두 행의 단위는 초/1000m, 마지막 두 행은 마지막200m 초다. 가설 방향은 모두 양수이며 음수는 그 반대다. 주대비4개와 직접 차이4개를 합친8검정에 BH를 적용했다.

{chr(10).join(direct)}

자기 기준+10kg의 단거리−긴 거리 차이는0을 포함한다. 절대 무거움의 차이는 오히려 반대 방향이며 BH q는0.0508이다. 가벼움의 긴 거리−단거리 마지막200m 차이는 두 체중 정의 모두0을 포함한다. 따라서 질문의 거리별 비대칭 패턴은 확인되지 않았다. 미확정을 효과가 정확히0이라는 뜻으로 바꾸지 않는다.

## ‘너무 무겁거나 가벼운’ 꼬리 구간도 확인했다

주분석을 본 뒤 극단 범주를 추가한 **사후 탐색**이다. 절대체중의 참조는470~489kg, 자기 기준의 참조는−5~+5kg다. 제곱식 곡선을 강제하지 않았다. 극단 범주도 양 지역을 모은 비교 지점에서100행·30두·20일 이상 지원 조건을 충족했다. 실제 분포의 끝377/609kg 같은 개별 체중까지 충분히 검증했다는 뜻은 아니다.

{chr(10).join(tail)}

극단 무거움의 단거리 전체시간, 극단 가벼움의 긴 거리 마지막200m라는4개 주 탐색 대비의 별도 BH를 보존했다. 지원 표본과 최근/성별 통제 결과는 [범주형 표](outputs/categorical_contrasts.csv)에 모두 있다. 사후 범주 결과를 독립 검증으로 가산하지 않는다.

![체중 범주와 꼬리 구간](figures/categorical_tail_checks.png)

## 마지막이 느린 것과 실제로 속도가 떨어진 것을 구분했다

마지막200m만으로 체력 저하를 단정하지 않았다. 마지막200m 분석에는 출발200m·중간1·직전400m의 시간과 제곱을 통제했다. 마지막600m와 둔화 분석에는600m 이전 두 구간만 통제했다. 결과를 포함하는 전체시간·착순으로 막판을 통제하지 않았다. 전개는 체중과 함께 변할 수 있으므로 전개를 맞춘 관계는 전체 연관과 구분해야 한다. 전개를 빼면 긴 거리 가벼움의 마지막200m는 절대체중{ci(select('absolute','late','long',450,spec='no_pace'))}, 자기 기준{ci(select('past_relative','late','long',-10,spec='no_pace'))}초로 모두0을 포함하며, 가벼움의 불리함을 보여주지 않는다.

둔화 지표는 ‘마지막200m − 바로 앞400m의200m당 평균시간’이다. 양수면 마지막200m가 느려졌다는 뜻이다. 마지막600m에서 마지막200m를 뺀 앞400m를 사용했으며, 서울에서 계측하지 않은 마지막400m를 만든 것이 아니다. 곡선/직선 등 구간 여건 차이도 남아 있어 생리적 피로나 지구력을 직접 측정하지 않는다.

{chr(10).join(fade)}

위 표는 모두1600~1800m의 실제 초다. 가벼움에서 둔화가 커지는 관계는 확인되지 않았다. 자기 기준+10kg는 마지막200m와 둔화 지표 모두 느린 방향이지만, 단거리와의 차이는 각각{ci(select('past_relative','late','long_minus_short',10))}, {ci(select('past_relative','fade','long_minus_short',10))}초로0을 포함한다. 보조구간 결과는 탐색이며 마지막600m와 마지막200m가 겹쳐 독립 증거로 합산하지 않는다.

## 원시 평균과 거리별 결과

아래 평균은 출전 집단 그대로이며 편성·나이·부담중량·능력·전개가 다른 원시 관측이다. 같은 조건의 체중 효과와 구분한다. 전체 평균·중앙값·P20/P80과 구간 분포는 [원시 분포표](outputs/observed_mass_sections.csv)에 보존했다.

{chr(10).join(raw)}

아래는 각 정확한 지역·거리의 별도 주모형이다. 전체시간은 해당 거리의 실제 초로 환산했다. 거리별 탐색값의 점별95%구간이며13개 거리 전체에 별도 유의성 보정을 완료했다는 뜻은 아니다. 서로 다른 표본에서 얻은 계수들의 차이를 이 표만으로 유의한 차이라고 판단하지 않는다.

{chr(10).join(dt)}

## 표본과 독립 계산 검증

전기간 절대체중은 단거리111,036·긴 거리37,090출전이다. 과거 체중 기준을 만들 수 있고 말/경주 반복 비교가 가능한 자기 기준 표본은 단거리73,140·긴 거리31,612출전이다. 초기 체중 이력 결측과 말/경주 단독 관측을 제외한 표본이므로 전체 경주마의 생리 반응을 대표하는 실험은 아니다. 최근의 부산1000m는242행, 자기 기준 부산/서울1000m는 반복 제거 후0행으로 추정에서 제외했다. 미추정을 효과0으로 바꾸지 않았다. [표본 진단](outputs/diagnostics.csv)과 [제외표](outputs/skipped.csv)를 남겼다.

원문18파일151,074행의 말ID·날짜·체중·전체·마지막200/600m를 재대조하고,21개 입력 해시·구간 합·현재를 제외한 과거5개 기준·날짜를 검증했다. 희소 고정효과 LU 투영과 QR 회귀, 별도 pandas 군집 합산으로 **{v['independent_distance_models']}거리 모형·{v['independent_group_models']}거리군 모형·{v['independent_joint_models']}공동 비교·{len(v['checks']):,}수치검사**를 통과했다. 범주형도 별도 희소 투영/QR로{cv['independent_distance_coefficients']}거리 계수 묶음과 군집 표준오차를 확인했다.

지역×정확한 거리별로 통제변수를 따로 제거한 뒤 거리군 공통계수를 추정했다. 같은 말·실제 달력 날짜의 거리/지역 간 공분산을 포함했다. 말 단일·날짜 단일·이원 군집 중 대비분산 최대값과 자유도/t 보정을 썼다. 주분석은450/510kg와자기 기준±10kg 지점 각각±5kg 근방100행·30두·20일 지원을 요구한다. 말/경주 고정효과와 나이 선형항이 겹치는 경우를 고려해 SVD/QR 상대 rank 기준1e-10을 통일했다.

연령·성장·컨디션·훈련·휴양과 거리 선택 등의 관측하지 못한 차이가 남는다. 조건부 기록 관계를 체중의 인과효과나 지구력 기전으로 입증하지 않았다. 최근2024~2025와4세 이상은 같은 자료의 민감도이며 미래 예측 검증이 아니다. 체중이 증가한 이유나 근육·지방·수분 구성은 알 수 없다. 특정 kg 처방·확정 기록 보정·DB·운영 모델·배포를 변경하지 않았다.

## 기록을 읽을 때 참고할 점

절대체중만 보고 ‘무거우니 단거리 감점, 가벼우니 긴 거리 막판 감점’으로 적용할 근거는 얻지 못했다. 자기 과거 범위에서 크게 벗어났는지와 실제 앞선 전개·막판 기록을 함께 보는 편이 이번 관측 결과에 맞다. 기존 [체중 변화/적정체중 연구](../20261008_body_weight_change_optimum/README.md)의 개인 최적 kg 미확정 결론은 유지한다. 이번 결과는 서로 다른 말의 체격과 같은 말의 변화를 구분하고 거리별 통념을 직접 검토한 후속이다.

[분석 계획](PLAN.md) · [출처/방법](SOURCES.md) · [게시 요약](PUBLICATION.md) · [게시 데이터](outputs/publication_summary.json) · [독립 검증](outputs/verification.json) · [범주 검증](outputs/categorical_verification.json) · [파일 용량](outputs/artifact_inventory.json) · [중앙11D](../conclusions/11D_BODY_MASS_DISTANCE_FINISH.md).

루트에서 `OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261008_body_mass_distance_finish/analyze.py`를 실행하고 같은 경로의 `verify.py`, `tails.py`, `render.py` 순서로 재현한다. `register.py`는 공유 목록을 수정하므로 분석 재현에는 생략한다.
'''
(H/'README.md').write_text(report)
sources='''# 출처와 계산 범위

2026-10-08. 기존 검증 자료를 읽기 전용으로 사용하며 새로운 외부 조회는 하지 않았다. 입력 해시는 [source_audit.json](outputs/source_audit.json), 기존 파일 보존 기준은 [baseline_inventory.json](outputs/baseline_inventory.json)에 있다.

- [성별 연구 모집단](../20261007_sex_ability_gap/outputs/population.parquet): 151,074출전, 13,928경주, 12,435두. 서울2018-01-06~2026-09-20, 부산2018-01-05~2026-09-18. 원 모집단의 정상기록 선택을 유지한다. [원 모집단 정의](../20261007_sex_ability_gap/SOURCES.md).
- [과거 체중 특징](../20261008_body_weight_change_optimum/outputs/body_features.parquet): 현재를 제외한 직전5개 관측(최소3개) 평균과 편차. 개인 전체 관측평균은 이번 분석에서 사용하지 않는다. [정의와 결측](../20261008_body_weight_change_optimum/SOURCES.md).
- [선택 전 원장](../20261007_sex_ability_gap/outputs/selection_ledger.parquet): 과거5개 체중을 독립 재계산했다. 관측 이력 사이의 모든 공식 경주가 완전하다고 보장하지 않는다.
- 기존 보관 공식 API 원문18개 gzip: `20260929_calendar_api_v1/raw/race_execution_probe/{2018..2026}/meet_{1,3}.json.gz`. 각 행의 source_file/source_item_index로 식별자·날짜·체중·전체/마지막200/600m를 재대조했다. 원문까지 포함21개 해시를 [독립 검증](outputs/verification.json)에서 확인했다.

서울 마지막200/600m는 전체시간에서 `seG1fAccTime` / `seG3fAccTime`을 뺀 차이, 부산은 `bu_1fGTime` / `bu_3fGTime`이다. middle2는 마지막600m−마지막200m로 얻는 마지막200m 직전400m다. 출발200m+중간1(거리−800m)+직전400m+마지막200m의 독립 구간 합을 검증했다. 서울의 미계측 마지막400m나 실제 경로 길이를 새로 만들지 않았다.

절대체중은 경주 고정효과, 자기 기준 편차는 경주+말 고정효과다. 부담중량/제곱·나이/제곱·rating/제곱·과거 전체/초반/입상 성과·과거 출전수·공백을 통제한다. 마지막200m는 앞선 세 구간과 제곱, 마지막600m/둔화는 앞선 두 구간과 제곱을 추가한다. rating/이력 결측은 거리별 중앙값과 결측표시를 쓴다. 체중 이력 결측은 제외한다. 주모형 성별 변수 없음; 절대체중 민감도에서만 출전 당시 암/거 표시를 추가했다.

초/1000m 전체시간은 두 거리군 비교의 척도이며 실제 해당 거리의 시간 차이는 거리/1000을 곱한다. 마지막200/600m와 둔화는 실제 초다. 거리군은 자료 범위상 정의로 공식 경기 분류나1900m 이상 검증을 뜻하지 않는다. 동일 말/날짜 군집, 고정효과 자유도, 상대 rank1e-10,8개 주검정 BH와 사후 범주4개 탐색 BH를 보존했다. 기타 표의 점별구간 전체가 다중비교 보정된 것은 아니다.

주분석과 사후 극단 범주 분석을 [계획 및 실행 보완](PLAN.md)에서 구분했다. 원천검증과 수치 재계산은 인과적 검증·생리 기전·미래예측 성능 검증과 다르다. 기존 완료 연구를 재실행하거나 덮어쓰지 않았다.
'''
(H/'SOURCES.md').write_text(sources)
pub='''# 체중과 거리별 기록·막판 통념 확인

2026-10-08 · 서울·부산2018~2026 실전 자료 · 연구 관찰 결과

**절대체중이 무거우면 단거리에 불리하고 가벼우면 긴 거리 막판에 불리하다는 통념은 이번 자료에서 확인되지 않았다.** 같은 말이 자기 과거 평균보다 무거워졌을 때 전체기록이 조금 느린 관계는 있었지만, 단거리에 특별히 더 불리하지는 않았다.

공통1200m 환산에서 절대510 대480kg 차이는 약−0.022초, 자기 과거 기준+10kg는 약+0.042초였다. 전자는 성별 통제/4세 이상에서 불확실해져 큰 말의 이점을 확정하지 않는다.1600~1800m 마지막200m에서 절대450 대480kg는 약−0.016초, 자기 기준−10kg는 약−0.012초로 후자는0을 포함했다. 양수는 느림이다. 가벼움의 긴 거리 막판 불리함이나 단거리 대비 추가 손실은 확인되지 않았다.

예를 들어 과거5개 관측 평균470kg인 말이480kg가 된 경우와 원래480kg 체격의 말은 다르게 읽어야 한다. kg 하나로 거리별 감점을 주기보다 자기 체중 이탈과 실제 전개/막판을 함께 본다. 특정 kg를 처방하거나 이 차이를 확정된 기록 보정으로 적용하지 않는다.

전체151,074출전 중1000~1800m 충분한13지역×거리148,126출전을 사용했다. 자기 기준은 반복 비교 가능한104,752출전이다. 단거리1000~1400m/긴 거리1600~1800m 비교이며1900m 이상은 미검증이다. 같은 경주·부담중량·나이·rating·과거 성적, 자기 기준은 같은 말까지 고려했다. 막판은 앞선 전개와 직전 구간 대비 둔화를 따로 확인했다. 극단 체중 범주도 사후 탐색으로 남겼다.

자료 종료: 서울2026-09-20·부산2026-09-18. 조건부 관찰 연구이며 체중 구성·체력 기전·인과효과·미래예측을 입증하지 않았다. 연구 보존/게시 준비 상태이며 운영 반영이나 배포는 수행하지 않았다.

[전체 보고서와95%구간](README.md) · [원천/방법](SOURCES.md) · [게시 데이터](outputs/publication_summary.json) · [독립 검증](outputs/verification.json).
'''
(H/'PUBLICATION.md').write_text(pub)
records=[]
for metric,outcome,comparison,target,label,scale in questions:
 for window in ['all','complete_2024_2025','age4plus']:
  r=select(metric,outcome,comparison,target,window);records.append(dict(question=label,metric=metric,outcome=outcome,comparison=comparison,target_kg=target,window=window,estimate_seconds=float(r.estimate*scale),lower_seconds=float(r.lower*scale),upper_seconds=float(r.upper*scale),seconds_basis='common1200 illustration' if scale==1.2 else 'actual last200',supported=bool(r.supported),bh_q=float(r.bh_q) if pd.notna(r.bh_q) else None))
data=dict(title='체중과 거리별 기록 및 막판 가설',date='2026-10-08',population_n=151074,eligible_n=148126,within_horse_n=104752,source_end=a['source_end'],distance_groups=dict(short=[1000,1200,1300,1400],long=[1600,1700,1800]),causal=False,operational=False,forecast_validation=False,large_horse_sprint_disadvantage_confirmed=False,light_horse_long_late_disadvantage_confirmed=False,within_horse_heavy_slow_association=True,sprint_specific_heavy_disadvantage_confirmed=False,extreme_categories_post_primary_exploratory=True,primary_comparisons=records)
(O/'publication_summary.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print('Reports, publication data and two figures written')
