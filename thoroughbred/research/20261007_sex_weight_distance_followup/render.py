"""Build local report, publication data and scientific figures from saved estimates."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures';F.mkdir(exist_ok=True)
r=pd.read_csv(O/'joint_contrasts.csv');s=pd.read_csv(O/'weight_and_population_summary.csv');counts=pd.read_csv(O/'distance_group_counts.csv')
assert json.loads((O/'verification.json').read_text())['passed']
font='/System/Library/Fonts/AppleSDGothicNeo.ttc'
if Path(font).exists():font_manager.fontManager.addfont(font);plt.rcParams['font.family']=[font_manager.FontProperties(fname=font).get_name(),'DejaVu Sans']
plt.rcParams.update({'axes.unicode_minus':False,'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':180})

def take(scope='time_joint',spec='full',window='all',parts=None,target='암',reference='수'):
 q=r[r.scope.eq(scope)&r.specification.eq(spec)&r.window.eq(window)&r.target.eq(target)&r.reference.eq(reference)].copy()
 if parts:q=q[q.part.isin(parts)]
 return q

def ci(row,dp=3):
 return f'{row.difference:+.{dp}f} [{row.lower:+.{dp}f}, {row.upper:+.{dp}f}]' if row.supported else f'{row.difference:+.{dp}f} [지원 부족]'

def table(q):
 txt=['| 지역 | 지표 | 단거리 암−수 | 중거리 암−수 | 중거리−단거리 직접 대비 |','|---|---|---:|---:|---:|']
 labels={'finish':'전체 초','seconds_per_1000m':'1000m당 초','early':'출발200m 초','late':'마지막200m 초','win':'우승 %p','top3':'3위 이내 %p'}
 for (meet,part),g in q.groupby(['meet','part'],sort=False):
  z=g.set_index('contrast');dp=2 if part in ['win','top3'] else 3
  txt.append(f'| {meet} | {labels[part]} | '+ ' | '.join(ci(z.loc[c],dp) for c in ['short_gap','middle_gap','middle_minus_short'])+' |')
 return '\n'.join(txt)

v=s[s.scope.eq('venue')].set_index(['meet','sex']);colors=['#c74a73','#4166af','#3a8d79']
fig,axes=plt.subplots(1,2,figsize=(10,4),sharey=True)
for ax,meet in zip(axes,['서울','부산']):
 vals=[v.loc[(meet,sex),'body_weight_mean'] for sex in ['암','수','거']]
 ax.bar(['암말','수말','거세마'],vals,color=colors,width=.62)
 for i,y in enumerate(vals):ax.text(i,y+1,f'{y:.1f}kg',ha='center')
 ax.set_title(meet);ax.set_ylim(0,550);ax.set_ylabel('평균 마체중 kg' if meet=='서울' else '')
fig.suptitle('암말의 평균 마체중은 수말보다 약21kg 가볍다',y=.98)
fig.text(.5,.01,'출전행 동일 가중 · 정상 완주151,074행 · 2018년 이후, 2026년9월까지',ha='center',fontsize=9)
fig.tight_layout(rect=[0,.06,1,.92]);fig.savefig(F/'body_mass.png');plt.close(fig)
fig,axes=plt.subplots(1,3,figsize=(13,4.8))
for ax,part,title,unit in zip(axes,['finish','seconds_per_1000m','top3'],['전체 기록','거리 증가 직접 대비','같은 경주 3위 이내'],['초 · 양수는 암말이 느림','초/1000m · 중거리 격차−단거리 격차','%p · 음수는 암말 성과가 낮음']):
 q=take('race_joint' if part=='top3' else 'time_joint','race_full' if part=='top3' else 'full',parts=[part])
 if part=='seconds_per_1000m':q=q[q.contrast.eq('middle_minus_short')]
 else:q=q[q.contrast.ne('middle_minus_short')]
 q=q.sort_values(['meet','contrast'],ascending=[False,False]);ys=np.arange(len(q))
 ax.axvline(0,color='#999',linewidth=1)
 for y,(_,a) in zip(ys,q.iterrows()):ax.errorbar(a.difference,y,xerr=[[a.difference-a.lower],[a.upper-a.difference]],fmt='o',color='#4166af',capsize=4)
 labels=[a.meet+(' 단거리' if a.contrast=='short_gap' else (' 중거리' if a.contrast=='middle_gap' else '')) for _,a in q.iterrows()]
 ax.set_yticks(ys,labels);ax.invert_yaxis();ax.set_title(title);ax.set_xlabel(unit,fontsize=9);ax.grid(axis='x',alpha=.15)
fig.suptitle('암말의 단거리 전체 우세는 확인되지 않는다',y=.98)
fig.text(.5,.01,'같은 조건 + 중량·마체중·rating·과거 성적 통제 · 점별95%구간 · 관찰된 조건부 차이',ha='center',fontsize=9)
fig.tight_layout(rect=[0,.07,1,.92]);fig.savefig(F/'distance_comparison.png');plt.close(fig)

wt=['| 지역 | 분류 | 출전 수 | 마체중 평균 kg | 중앙값 | 빠른 표현 대신 가벼운20% 경계 | 무거운20% 경계 | 말별 동일 가중 평균 kg | 부담중량 평균 kg |','|---|---|---:|---:|---:|---:|---:|---:|---:|']
for meet in ['서울','부산']:
 for sex in ['암','수','거']:
  a=v.loc[(meet,sex)];wt.append(f'| {meet} | {sex} | {a.n:,.0f} | {a.body_weight_mean:.2f} | {a.body_weight_median:.0f} | {a.body_weight_p20:.0f} | {a.body_weight_p80:.0f} | {a.body_weight_horse_equal_mean:.2f} | {a.weight_mean:.2f} |')
wt='\n'.join(wt).replace('빠른 표현 대신 가벼운20% 경계','가벼운20% 경계')
pair=['| 지역 | 비교 | 원시 마체중 차이 kg | 같은 조건·등급 차이 kg |','|---|---|---:|---:|']
for meet in ['서울','부산']:
 for a,b in [('암','수'),('거','수'),('암','거')]:
  z=r[r.scope.eq('weight')&r.meet.eq(meet)&r.target.eq(a)&r.reference.eq(b)&r.part.eq('body_weight')].set_index('specification')
  pair.append(f'| {meet} | {a}−{b} | {ci(z.loc["raw"],2)} | {ci(z.loc["context_grade"],2)} |')
ns=['| 지역 | 분석 | 입력 쌍 행수 | 공통 행수 | 단거리 암/수 | 중거리 암/수 | 제외율 |','|---|---|---:|---:|---:|---:|---:|']
for scope,spec in [('time_joint','full'),('race_joint','race_full')]:
 for _,a in take(scope,spec,parts=['finish']).query("contrast=='short_gap'").iterrows():
  ns.append(f'| {a.meet} | {scope} | {a.input_pair_n:,} | {a.common_n:,} | {a.short_target_n:.0f}/{a.short_reference_n:.0f} | {a.middle_target_n:.0f}/{a.middle_reference_n:.0f} | {a.excluded_fraction:.1%} |')
text=f'''# 암말 수말 거세마의 체중과 거리별 경기력

2026-10-07. **암말은 평균적으로 수말보다 약21kg, 거세마보다 약15kg 가볍다. 그러나 단거리 경주 전체에서 암말이 더 잘 뛴다는 주장은 이번 자료에서 확인되지 않았다.** 출발200m는 암말이 조금 빠르지만, 전체시간과 같은 경주 입상 성과는 다른 결과를 보인다. 중거리에서 암말의 열세가 더 커지는지는 지표·지역에 따라 불확실하다.

## 자료와 비교 범위

[기존 성별 연구](../20261007_sex_ability_gap/README.md)의 검증된 서울·부산 실전151,074출전·13,928경주·12,435두를 읽기 전용으로 재사용했다. 2018년 이후 자료이며 종료일은 서울2026-09-20·부산2026-09-18, 거리별 종료일은 다르다. 2026년은 부분 연도다. 출전 당시 암·수·거 분류이며 거세마는 수컷의 거세 상태를 포함한 분류다. 주행심사·제주·영천과 주로빠르기는 사용하지 않았다.

단거리는1000·1200·1300·1400m, 중거리는1600·1700·1800m라는 연구용 묶음이다. 공식 거리 분류를 주장하지 않는다.1900m 이상은 별도이며 아래 결론을 확장하지 않는다. 정상 완주·구간 품질 선택을 계승했고 정상적인 빠르거나 느린 기록을 추가 제거하지 않았다. 이 선택에 따른 한계와 넓은 모집단 민감도는 원 연구에 보존돼 있다.

## 마체중과 부담중량

마체중은 말 몸의 무게이고 부담중량은 경주에서 짊어지는 중량이다. 아래 기본 평균은 출전행 동일 가중이어서 자주 출전한 말의 비중이 크다. 말별 동일 가중은 각 말의 해당 분류·지역 평균을 먼저 만든 뒤 평균했다. 수→거로 바뀐 말은 각 출전 당시 분류에 속할 수 있다.

{wt}

![지역별 평균 마체중](figures/body_mass.png)

다음 괄호는 마필·날짜 의존성을 반영한 점별95%구간이다. 같은 조건은 지역별 정확 거리·연도·월·나이·함수율 숫자·등급이 모두 같은 층 중 양쪽 분류가 관측된 경우다.

{chr(10).join(pair)}

말별 동일 가중에서도 암−수 차이는 서울−21.70kg·부산−21.86kg로 남는다. 부담중량은 암말이 수말보다 원시 평균 약1.31~1.32kg 적었다. 이는 관측 평균이며 연도별 공식 감량 규정의 수치로 해석하지 않는다. 가볍다는 사실만으로 더 빠르거나 체중 때문에 기록 차이가 난다고 단정할 수 없다.

## 전체 기록과 초반 및 막판

아래는 정확 거리·연도·월·나이·등급·함수율을 맞추고 부담중량·마체중(제곱항 포함),rating(제곱항 포함)·과거 기록/성과·출전수·공백을 추가 통제한 조건부 차이다. 통제 기울기는 단거리와 중거리에서 각각 추정했다. **암−수의 시간 양수는 암말이 느린 방향**이며 괄호는 점별95%구간이다.

{table(take(parts=['finish','seconds_per_1000m','early','late']))}

단거리 전체시간의 암말 열세는 서울+0.131초·부산+0.119초다. 출발200m는 각각−0.041초·−0.052초로 암말이 빠르지만, 마지막200m는+0.097초·+0.111초로 느리다. 초반이 빠른 현상을 단거리 경주 전체의 우세로 바꿔 읽을 수 없다. 중거리 전체시간은+0.231초·+0.224초로 점추정상 격차가 더 크지만, 중거리−단거리 직접 대비의95%구간은 양 지역 모두0을 포함한다.

경주가 길면 동일 비율 차이도 초 차이가 커질 수 있어1000m당 관측시간으로 재확인했다. 이 단위는 가상의1000m 경주 환산이나 환경 보정이 아니다. 중거리에서 암말 격차가 늘어나는 정도는 서울+0.034초/1000m·부산+0.039초/1000m이며 양쪽 모두 구간이0을 포함한다. 거리 증가의 일반 법칙으로 확정하기 어렵다.

중량·체중·rating·이력을 넣기 전 같은 조건·등급만 맞춘 결과도 보존한다. 이 단계에서 암말은 단거리/중거리 모두 느린 방향이다. 서울 전체 초의 거리 증가 대비만 양수 구간이나1000m당 대비는0을 포함한다. 전부 통제한 값은 동등한 등급·중량·이력의 말 사이 질문이며 전체 출전 집단의 격차가 없어졌다는 뜻이 아니다.

{table(take(spec='grade',parts=['finish','seconds_per_1000m']))}

## 같은 경주의 실제 성과

원래 출전자 구성이 전부 유지된 정상 혼합 경주에서 해당 두 분류가 실제 함께 출전한 경우만 비교했다. 암말 제한 편성과 비표준 원래 편성은 제외했다. 같은 경주 효과에 나이·중량·체중·rating·과거 성적 등을 더한 선형 확률 차이다. 우승/3위 이내는 시간과 별도의 성과이며 **음수는 암말 성과가 낮은 방향**이다. 아래 %p는 우승확률 예측값이 아니다.

{table(take('race_joint','race_full',parts=['win','top3']))}

서울에서는 중거리의3위 이내 성과 격차가 단거리보다−3.11%p 더 낮았고 점별 구간은0을 포함하지 않는다. 부산의−1.52%p 직접 대비는0을 포함한다. 양쪽의 단거리3위 이내 성과는 수말보다 낮은 방향이다. 통제 없는 같은 경주 결과까지 함께 제공한다.

{table(take('race_joint','race',parts=['win','top3']))}

![거리별 기록과 성과 비교](figures/distance_comparison.png)

## 표본과 최근 기간의 한계

{chr(10).join(ns)}

기록 분석의 입력 쌍은 해당 지역1000~1800m 암·수 전체이고, 같은 경주 분석 입력 쌍은 먼저 정상 완전 혼합 편성으로 제한한 수다. 제외율은 각각의 입력 대비 공통층/동반 출전 조건에서 빠진 비중이므로 서로 같은 모집단의 제외율이 아니다. 전체 성별 수·거리별 수·쌍별 공통수는 결과 CSV에 있다.

2024~2025 완결연도만 재분석하면 아래와 같다. 방향은 대체로 유지되지만 중거리 전체시간 구간은 양 지역 모두0을 포함하며, 부산 단거리도0을 포함한다. 서울의 중거리−단거리3위 이내 차이도 최근 표본에서는 불확실하다. 이는 같은 자료의 민감도이며 독립 미래 검증이 아니다.

{table(take(window='complete_2024_2025',parts=['finish','seconds_per_1000m']))}

{table(take('race_joint','race_full',window='complete_2024_2025',parts=['top3']))}

1900m 이상은 서울 암말203행·수말1,228행·거세마552행, 부산 암말134행·수말522행·거세마309행뿐이다. 여러 정확 거리·연도·월·나이·등급·함수율을 맞추면 암말 공통 비교가 더 희소해진다. 이 자료로 장거리의 보편적 성별 우열을 새로 확정하지 않았다. 특히 부산1900은2020년에 종료하는 오래된 관측이다.

거세마는 수말보다 평균 약6.3~6.5kg 가볍지만 경기력을 체중 순서대로 나열할 수 없다. 전부 통제한 전체시간 거−수는 서울 단거리−0.048초[−0.090,−0.006], 중거리−0.022초[−0.101,+0.057], 부산 단거리−0.012초[−0.067,+0.044], 중거리−0.004초[−0.091,+0.084]다. 거세의 인과효과나 일관된 순위로 해석하지 않는다. 세 쌍의 모든 결과를 공개해 특정 비교만 선택하지 않았다.

## 계산과 검증

공통층 내 회귀와 성별×거리묶음 상호작용의 직접 대비를 썼다. 공변량 결측은 분석행렬 안에서 중앙값과 결측 지시자로 처리하고 원천 null은 유지했다. 말 고정효과나 기존 성별 보정 잔차를 사용하지 않았다. 공통층 내 양쪽 표본수에 따라 가중되는 비교이고 정확 거리들의 동일 가중 평균이 아니다. 각 쌍의 공통 모집단이 다르므로 서로 뺄셈해 다른 쌍을 만들지 않는다.

마필·지역별 날짜의 이원 군집 분산과 각 단독 군집 분산 중 최대를 쓰고 층 자유도·t 보정을 적용했다. 경주는 날짜 군집 안에 들어간다. 각 거리묶음 양쪽100행·30두·20날짜·20층과 대비 식별을 구간 제공 요건으로 삼았다. 다수 비교의 점별 탐색95%구간으로 동시 신뢰구간은 아니다. 자기선택·편성·건강·훈련 등 미관측 요인이 남아 생물학적 인과 결론이나 자동 성별 보정의 근거로 쓰지 않는다.

입력4개 해시·행/경주 고유성·분류·마체중 유효성을 확인했다. DuckDB로 원시·말별 동일 가중 체중을 대조하고, 모든 상호작용 대비/구간 산식을 검사했다. 별도 QR 회귀·pandas 군집 합으로 세 성별 쌍의 주 모형126행을 재계산하고4개 명시적 희소 고정효과 회귀로 주요 계수를 확인했다. 총524수치 검사가 통과했다. 원문 성별·날짜·구간 합의 재검증 기록은 원 연구의 감사 결과를 계승한다.

## 산출물과 재현

[계획](PLAN.md), [출처와 방법](SOURCES.md), [모든816대비](ALL_RESULTS.md), [결과 CSV](outputs/joint_contrasts.csv), [체중·표본표](outputs/weight_and_population_summary.csv), [독립 검증](outputs/verification.json), [독립 계산표](outputs/independent_model_checks.csv), [게시 요약](PUBLICATION.md), [게시 데이터](outputs/publication_summary.json), [용량 명세](outputs/artifact_inventory.json)를 보존한다. 기존 연구·운영 DB·기준표·배포는 변경하지 않았다.

프로젝트 루트에서 순서대로 실행한다. 기존 원 연구는 재실행하지 않는다.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261007_sex_weight_distance_followup/analyze.py
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python thoroughbred/research/20261007_sex_weight_distance_followup/verify.py
MPLCONFIGDIR=/private/tmp/sex_weight_plot PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261007_sex_weight_distance_followup/render.py
```
'''
# Verification row count and check total are read instead of assumed.
ver=json.loads((O/'verification.json').read_text());text=text.replace('주 모형126행',f"주 모형{ver['checked_primary_model_rows']}행").replace('총524수치',f"총{len(ver['checks'])}수치")
(H/'README.md').write_text(text)
(H/'PUBLICATION.md').write_text('''# 암말의 체중과 단거리 경기력

암말은 서울·부산에서 수말보다 평균 약21kg, 거세마보다 약15kg 가볍다. 말별 평균을 동일하게 반영하거나 나이·등급·거리 등의 조건을 맞춰도 체중 차이가 남는다.

그러나 단거리 경주 전체에서 암말이 더 잘 뛴다는 통념은 확인되지 않았다.1000~1400m에서 조건·중량·체중·기존 성적을 맞춘 전체 기록은 암말이 서울 약0.13초·부산 약0.12초 느렸다. 출발200m는0.04~0.05초 빠르지만 마지막200m는 약0.10~0.11초 느렸다. 초반의 빠른 출발을 경주 전체의 우세로 해석하면 안 된다.

예를 들어 같은 조건의 단거리에서 출발200m가 빠른 암말의 기록을 평가할 때, 전체시간과 막판200m도 함께 읽는다. 체중이 가볍다는 사실이나 성별 평균을 그 말의 우승확률 또는 고정된 기록 가산·감산으로 바꾸지 않는다.

1600~1800m에서는 전체시간 암−수 차이가 약+0.22~0.23초로 더 크지만, 단거리와의 차이를 직접 비교한95%구간은 양 지역 모두0을 포함한다. 같은 경주3위 이내 성과는 서울에서 중거리 열세가 더 컸고 부산은 불확실했다.1900m 이상은 암말 표본이 적어 일반화하지 않았다.

2018년 이후 정상 완주151,074행, 서울2026-09-20·부산2026-09-18까지의 관찰 연구다.2024~2025년만 쓰면 불확실성이 더 커진다. 거리 묶음은 연구용이고, 거세마는 수컷의 거세 상태를 포함한 분류다. 인과효과·성별 보정·운영 예측 개선을 확정한 결과가 아니다.

[자세한 결과와95%구간](README.md), [평균 마체중 그림](figures/body_mass.png), [거리별 비교 그림](figures/distance_comparison.png), [게시 데이터](outputs/publication_summary.json). 게시 준비 자료이며 웹사이트 배포는 별도다.
''')
primary=pd.concat([take(parts=['finish','seconds_per_1000m','early','late']),take('race_joint','race_full',parts=['win','top3']),take(window='complete_2024_2025',parts=['finish']),take('race_joint','race_full',window='complete_2024_2025',parts=['top3'])])
obj=dict(title='암말의 체중과 단거리 경기력',status='research_publication_prepared',causal=False,operational_correction=False,source_method='source_and_method.json',weight_summary=s[s.scope.eq('venue')].to_dict('records'),primary_contrasts=primary.to_dict('records'),distance_group_counts=counts.to_dict('records'),figures=['figures/body_mass.png','figures/distance_comparison.png'])
# pandas provides valid JSON nulls rather than nonstandard NaN.
(O/'publication_summary.json').write_text(pd.Series(obj).to_json(force_ascii=False,indent=2)+'\n')
alltext=['# 성별 체중과 거리 대비 전체 결과','\n양수 시간은 target이 느림, 양수 %p는 target의 성과가 높음. 체중은kg. 각 쌍의 공통 표본이 다르다. 모든 구간은 점별95%이며 최근 재분석은 민감도다.\n','| 범위 | 지역 | 기간 | 통제 | 비교 | 지표 | 대비 | 차이 | 95%구간 | 공통행 | 지원 |','|---|---|---|---|---|---|---|---:|---|---:|---|']
for _,a in r.iterrows():alltext.append(f'| {a.scope} | {a.meet} | {a.window} | {a.specification} | {a.target}−{a.reference} | {a.part} ({a.unit}) | {a.contrast} | {a.difference:+.5f} | '+(f'[{a.lower:+.5f},{a.upper:+.5f}]' if a.supported else 'null')+f' | {a.common_n} | {a.supported} |')
(H/'ALL_RESULTS.md').write_text('\n'.join(alltext)+'\n')
print('rendered reports and figures')
