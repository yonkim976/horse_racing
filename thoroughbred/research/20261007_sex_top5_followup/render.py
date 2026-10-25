"""Generate top-five reports and figures from saved, verified results."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures';F.mkdir(exist_ok=True)
r=pd.read_csv(O/'contrasts.csv');s=pd.read_csv(O/'descriptives.csv');ver=json.loads((O/'verification.json').read_text());assert ver['passed']
font=Path('/System/Library/Fonts/AppleSDGothicNeo.ttc')
if font.exists():font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']=[font_manager.FontProperties(fname=str(font)).get_name(),'DejaVu Sans']
plt.rcParams.update({'axes.unicode_minus':False,'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':180})

def take(scope='time',cohort='top5',spec='full',window='all',parts=None,target='암',reference='수'):
 q=r[r.scope.eq(scope)&r.cohort.eq(cohort)&r.specification.eq(spec)&r.window.eq(window)&r.target.eq(target)&r.reference.eq(reference)]
 return q[q.part.isin(parts)] if parts else q

def ci(a,dp=3):return f'{a.difference:+.{dp}f} [{a.lower:+.{dp}f}, {a.upper:+.{dp}f}]' if a.supported else f'{a.difference:+.{dp}f} [지원 부족]'

def table(q):
 rows=['| 지역 | 지표 | 단거리 암−수 | 중거리 암−수 | 중거리−단거리 직접 대비 |','|---|---|---:|---:|---:|']
 labels={'finish':'전체 초','seconds_per_1000m':'1000m당 초','early':'출발200m 초','late':'마지막200m 초','top5':'5위 이내 %p','top3':'3위 이내 %p','win':'우승 %p'}
 for (meet,part),g in q.groupby(['meet','part'],sort=False):
  z=g.set_index('contrast');dp=2 if part in ['top5','top3','win'] else 3
  rows.append(f'| {meet} | {labels[part]} | '+' | '.join(ci(z.loc[c],dp) for c in ['short_gap','middle_gap','middle_minus_short'])+' |')
 return '\n'.join(rows)

fig,axes=plt.subplots(1,2,figsize=(11.5,5.0))
for ax,meet in zip(axes,['서울','부산']):
 ax.axvline(0,color='#999',lw=1)
 for i,(cohort,color,label) in enumerate([('all','#969696','전체 출전'),('top5','#4166af','5위 이내 출전')]):
  q=take(cohort=cohort,parts=['finish']);q=q[q.meet.eq(meet)].set_index('contrast')
  for j,c in enumerate(['short_gap','middle_gap']):
   a=q.loc[c];ax.errorbar(a.difference,j+(i-.5)*.18,xerr=[[a.difference-a.lower],[a.upper-a.difference]],fmt='o',capsize=4,color=color,label=label if j==0 else None)
 ax.set_yticks([0,1],['단거리1000~1400m','중거리1600~1800m']);ax.invert_yaxis();ax.set_title(meet);ax.set_xlabel('암−수 전체시간 초 · 양수는 암말이 느림');ax.grid(axis='x',alpha=.15);ax.legend(fontsize=9)
fig.suptitle('5위 이내로 좁히면 단거리 격차는 작아지고 중거리는 지역별로 다르다',fontsize=14,y=.98)
fig.text(.5,.01,'조건·중량·체중·rating·과거 성적 통제 · 점별95%구간 · 선택 전후 공통층 구성은 다름',ha='center',fontsize=9)
fig.tight_layout(rect=[0,.07,1,.91]);fig.savefig(F/'top5_time_comparison.png');plt.close(fig)
fig,ax=plt.subplots(figsize=(9,4.8));q=take('race_outcome','all','race_full',parts=['top5']);q=q[q.contrast.ne('middle_minus_short')].sort_values(['meet','contrast'],ascending=[False,False]);ax.axvline(0,color='#999',lw=1)
for i,(_,a) in enumerate(q.iterrows()):ax.errorbar(a.difference,i,xerr=[[a.difference-a.lower],[a.upper-a.difference]],fmt='o',capsize=4,color='#4166af')
ax.set_yticks(range(len(q)),[a.meet+(' 단거리' if a.contrast=='short_gap' else ' 중거리') for _,a in q.iterrows()]);ax.invert_yaxis();ax.set_xlabel('5위 이내 성과 암−수 %p · 음수는 암말 성과가 낮음');ax.grid(axis='x',alpha=.15)
ax.set_title('같은 경주의 전체 출전자에서는 암말의 5위 이내 성과가 낮다',pad=18)
fig.text(.5,.01,'5위 이내 결과로 표본을 제한하지 않음 · 나이·중량·체중·rating·과거 성적 통제 · 점별95%구간',ha='center',fontsize=9);fig.tight_layout(rect=[0,.07,1,1]);fig.savefig(F/'top5_entry_difference.png');plt.close(fig)

weights=['| 지역 | 분류 | 전체 출전 수 | 5위 이내 출전 수 | 전체 마체중 평균 kg | 5위 이내 평균 kg | 5위 이내 중앙값 kg | 말별 동일 가중 kg |','|---|---|---:|---:|---:|---:|---:|---:|']
v=s[s.scope.eq('venue')].set_index(['cohort','meet','sex'])
for meet in ['서울','부산']:
 for sex in ['암','수','거']:
  a=v.loc[('all',meet,sex)];b=v.loc[('top5',meet,sex)];weights.append(f'| {meet} | {sex} | {a.n:,.0f} | {b.n:,.0f} | {a.body_weight_mean:.2f} | {b.body_weight_mean:.2f} | {b.body_weight_median:.0f} | {b.body_weight_horse_equal_mean:.2f} |')
compare=['| 지역 | 거리 묶음 | 전체 출전 암−수 초 | 5위 이내 암−수 초 |','|---|---|---:|---:|']
for meet in ['서울','부산']:
 for contrast,label in [('short_gap','1000~1400m'),('middle_gap','1600~1800m')]:
  a=take(cohort='all',parts=['finish']).query('meet==@meet and contrast==@contrast').iloc[0];b=take(parts=['finish']).query('meet==@meet and contrast==@contrast').iloc[0]
  compare.append(f'| {meet} | {label} | {ci(a)} | {ci(b)} |')
ns=['| 지역 | 분석 | 입력 쌍 행 | 공통 행 | 단거리 암/수 | 중거리 암/수 | 제외율 |','|---|---|---:|---:|---:|---:|---:|']
for scope,cohort,spec in [('time','top5','full'),('time','all_in_top5_common_cells','full'),('race_outcome','all','race_full'),('race_selected_time','top5','race_full')]:
 for _,a in take(scope,cohort,spec,parts=['top5' if scope=='race_outcome' else 'finish']).query("contrast=='short_gap'").iterrows():
  ns.append(f'| {a.meet} | {scope}/{cohort} | {a.input_pair_n:,} | {a.common_n:,} | {a.short_target_n:.0f}/{a.short_reference_n:.0f} | {a.middle_target_n:.0f}/{a.middle_reference_n:.0f} | {a.excluded_fraction:.1%} |')
text=f'''# 5위 이내 암말 수말 거세마의 기록과 성과

2026-10-07. **5위 이내 출전만 비교하면 단거리 암−수 전체시간 차이는 작아지지만 암말 우세로 바뀌지는 않는다. 중거리는 서울에서 수말 우세가 남고, 부산에서는 명확한 차이가 사라진다.** 그러나 같은 경주의 전체 출전자에서5위 이내에 드는 성과는 암말이 수말보다 낮았다. 이미 상위권에 든 집단의 기록과 상위권에 진입하는 성과는 다른 질문이다.

## 상위권의 정의와 자료

사용자의5위 이내는 각 경주 최종 착순1~5위의 출전 기록으로 정의했다. 고등급·평생 우수마·사전 예측 상위5두를 뜻하지 않는다. [성별 원 연구](../20261007_sex_ability_gap/README.md)의151,074행·13,928경주·12,435두 중69,639행이 해당한다. 원 모집단에서 경주당5개보다1개 적은 것은 부산2025-11-23 제3경주3위 수말이 기존 구간 품질/부모 거리 선택에서 빠진 출전이며 복구하거나0으로 채우지 않았다. 원 출전자 전원이 유지된 경주는 모두5개씩 존재함을 검증했다.

서울2018-01-06~2026-09-20·부산2018-01-05~2026-09-18, 출전 당시 암·수·거 분류다. 거리별 종료일은 다르고2026년은 부분 연도다. 정상 완주·구간 품질 선택을 계승했다. 거세마는 수컷의 거세 상태를 포함한다. 제주·영천·주행심사·주로빠르기는 제외했다.

연구용 단거리는1000~1400m, 중거리는1600~1800m다.1900m 이상은 원 연구의 암말 희소성 때문에 새 일반 우열을 추정하지 않는다.6두 경주의5위와12두 경주의5위는 같은 상위비율이 아니다. 같은 경주 비교와10두 이상 경주 민감도를 함께 제시한다.

## 체중 차이는 유지된다

{chr(10).join(weights)}

상위5위 출전에서도 암말은 수말보다 서울20.35kg·부산20.98kg, 거세마보다 서울14.14kg·부산13.99kg 가볍다. 기존 전체 출전의 약21kg/15kg 차이와 방향이 같다. 평균이 조금 바뀌어도 체중 자체가 경기력 차이의 원인이라는 뜻은 아니다. 마체중·부담중량의 평균/중앙값/P20/P80과 말별 동일 가중값은 [관측표](outputs/descriptives.csv), 조건을 맞춘 차이는 [대비표](outputs/contrasts.csv)에 보존한다.

## 전체 출전과 5위 이내 기록

정확 거리·연도·월·나이·등급·함수율 숫자가 같은 층에서 비교하고, 부담중량·마체중·rating의 제곱항 및 과거 기록/성과·출전수·공백을 더했다. 거리묶음별 공변량 기울기를 따로 추정한다. **시간 암−수 양수는 암말이 느린 방향**이고 괄호는 마필/날짜 군집을 반영한 점별95%구간이다.

{chr(10).join(compare)}

단거리 격차의 점추정은 서울 약0.13→0.05초, 부산 약0.12→0.07초로 작아졌다. 서울 중거리는 약0.23초로 유지되고 부산 중거리는 약0.01초로0을 포함한다. 이는 서로 다른 선택 표본의 조건부 추정치 비교이며 격차 감소의 통계적 유의성이나 상위권만의 인과효과를 검정한 결과가 아니다.

![전체와5위 이내의 기록 비교](figures/top5_time_comparison.png)

5위 이내 표본의 전체·1000m당 시간·초반200m·마지막200m 및 중거리−단거리 직접 대비는 다음과 같다.

{table(take(parts=['finish','seconds_per_1000m','early','late']))}

암말은 상위5위 단거리에서도 초반200m가 서울 약0.044초·부산0.056초 빠르지만, 막판200m는0.048초·0.090초 느리다. 초반 속도만으로 단거리 경주 전체 우세를 주장하지 않는다. 서울에서는 중거리−단거리 전체 차이+0.177초와1000m당 차이+0.091초의 점별 구간이0을 포함하지 않는다. 부산에서는 두 직접 대비 모두 불확실하다. 최근/10두 이상으로 좁히면 서울의 거리 증가 대비도 불확실해진다.

## 같은 경주에서 5위 안에 드는 성과

이 비교는5위 이내로 표본을 제한하지 않는다. 원래 출전자 전원이 남은 정상 혼합 경주 중 암·수가 실제 동반 출전한 전체 출전자에서5위 이내 지시자를 비교했다. 같은 경주 효과와 나이·중량·체중·rating·과거 성적 등을 맞춘 선형 확률 차이이며 음수는 암말 성과가 낮은 방향이다. 우승·3위 이내도 함께 보존한다.

{table(take('race_outcome','all','race_full',parts=['top5','top3','win']))}

5위 이내 암−수 차이는 서울 단거리−4.75%p·중거리−6.63%p, 부산 단거리−3.40%p·중거리−5.15%p다. 네 점별95%구간 모두0보다 낮다. 그러나 중거리−단거리 성과 차이의 구간은 양 지역 모두0을 포함한다.5위 이내에 든 말끼리 기록이 비슷하다는 결과와 이 진입 성과는 모순되지 않는다. 개별 말의 우승확률 예측값이나 생물학적 인과효과로 사용하지 않는다.

![전체 출전자에서5위 이내 성과](figures/top5_entry_difference.png)

## 선택과 공통조건을 바꾼 점검

상위5위 양쪽 분류가 존재하는 정확 공통층으로 전체 출전도 제한하면 다음과 같다. 서울 중거리 전체 표본 암−수는+0.093초, 부산−0.070초로 원래 전체 표본과 달라진다. 상위5위 선택에 따라 어느 조건이 비교에 남는지도 변하기 때문이다. 이 점검에서도5위 이내와 전체의 층 내 구성·가중치·이력 분포는 완전히 같지 않다.

{table(take(cohort='all_in_top5_common_cells',parts=['finish']))}

다른 경주의 편성 차이를 더 줄여 같은 경주에서5위 이내에 든 암·수끼리 비교하면 서울 단거리+0.021초[−0.013,+0.055]·중거리+0.143초[+0.076,+0.210], 부산 단거리+0.060초[+0.018,+0.103]·중거리+0.065초[−0.004,+0.135]다. 이 비교도 이미 선택된 상위권끼리의 연관이다. 서울 단거리의 작은 격차는 이 방식에서 확실하지 않다.

{table(take('race_selected_time','top5','race_full',parts=['finish']))}

{chr(10).join(ns)}

입력 쌍 행수는 각 분석의 사전 선택까지 적용한 수다. 서로 다른 범위의 제외율을 전체151,074행 대비 비율로 혼동하지 않는다. 단거리/중거리 양쪽 분류100행·30두·20날짜·20공통층 및 대비 식별을 지원 요건으로 썼다. 전체 결과1704행은 이 묶음 기준을 통과했지만, 이는 개별 희소 장거리까지 지원한다는 뜻이 아니다.

## 최근 기간과 10두 이상 경주

2024~2025 완결연도만 보면 서울5위 이내 중거리 암−수+0.237초는 느린 방향이 남지만, 양 지역 단거리와 부산 중거리는 구간이0을 포함한다. 서울 거리 증가 직접 대비도0을 포함한다. 부산 최근 중거리−단거리 대비는 반대 방향의 점별 구간으로 나와, 일관된 거리 법칙을 확정하지 않는다. 같은 자료의 재분석이며 미래 검증이 아니다.

{table(take(window='complete_2024_2025',parts=['finish']))}

{table(take('race_outcome','all','race_full',window='complete_2024_2025',parts=['top5']))}

10두 이상 경주만 보면 서울5위 이내 중거리+0.148초의 느린 방향이 남고 부산 중거리는 약0이다. 서울 단거리+0.055초·부산+0.035초로 부산 단거리 구간은0을 포함한다. 같은 경주의5위 이내 진입 성과는 네 지역/거리 묶음 모두 암말이 낮은 방향이다.

{table(take(window='field_size_10plus',parts=['finish']))}

{table(take('race_outcome','all','race_full',window='field_size_10plus',parts=['top5']))}

거세마−수말의 상위5위 전체시간은 서울 단거리−0.052초[−0.086,−0.018]·중거리−0.030초[−0.087,+0.028], 부산 단거리−0.017초[−0.064,+0.029]·중거리−0.009초[−0.075,+0.058]다. 일관된 성별 순위나 거세의 인과효과로 해석하지 않는다. 모든 세 쌍·등급만 통제한 단계·원시 체중·원시 같은 경주 성과는 전체 결과에 있다.

## 검증과 해석 범위

입력5개 해시·행/경주 고유성·출전 당시 분류·착순/우승/3위 이내 지시자·경주별5위 이내 수·구간 합을 확인했다. DuckDB 집계로 선택수·체중 평균·말별 평균을 대조했다. 이전 보고서의432개 추정치를 정확히 재현했다. 별도QR 회귀와 pandas 군집 합으로 주 모형252행의 계수·표준오차를 대조했고4개 명시적 희소 고정효과 적합을 확인했다. 총{len(ver['checks'])}수치 검사가 통과했다.

반복 출전과 같은 날짜 의존성은 마필/날짜 이원 군집과 각 단독 군집 중 최대 분산, 고정효과 자유도와t 보정으로 반영했다. 이는 다수 비교의 점별95%구간이며 동시 보장이 아니다. 공변량 결측은 행렬 안에서 중앙값+결측 지시자만 쓰고 원천 null은 유지한다. 말 고정효과로 성별을 식별하거나 기존 성별 보정 잔차를 재사용하지 않았다.

5위 이내는 결과로 집단을 고른 것이어서 부진한 출전이 제거되고 통과한 말의 구성도 달라진다. 이를 영구적인 상위마 분류·사전 예측 능력·전체 집단의 동등함으로 바꾸어 해석할 수 없다. 정상 완주 모집단의 선택 편향은 [원 연구의 넓은 출전자 민감도](../20261007_sex_ability_gap/README.md)를 계승하지만 이번 상위5위 재분석은 그 넓은 모집단까지 새로 확장하지 않았다. 성별 보정·운영 반영·체중 인과 설명·웹사이트 배포는 채택하지 않았다.

## 산출물과 재현

[계획](PLAN.md) · [출처/방법](SOURCES.md) · [전체1704대비](ALL_RESULTS.md) · [관측표](outputs/descriptives.csv) · [선택표](outputs/selection_ledger.csv) · [대비 CSV](outputs/contrasts.csv) · [검증](outputs/verification.json) · [독립 계산표](outputs/independent_model_checks.csv) · [게시 요약](PUBLICATION.md) · [게시 데이터](outputs/publication_summary.json) · [파일별 용량](outputs/artifact_inventory.json).

프로젝트 루트에서 다음을 순서대로 실행한다. 기존 연구는 재실행하지 않는다.

```sh
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python thoroughbred/research/20261007_sex_top5_followup/analyze.py
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python thoroughbred/research/20261007_sex_top5_followup/verify.py
MPLCONFIGDIR=/private/tmp/sex_top5_plot PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261007_sex_top5_followup/render.py
```
'''
(H/'README.md').write_text(text)
(H/'PUBLICATION.md').write_text('''# 5위 이내 말만 비교하면 성별 차이가 달라지는가

5위 이내 출전만 비교하면 단거리의 암말·수말 기록 차이가 작아졌다. 같은 조건과 중량·체중·rating·과거 성적을 맞춘 암−수 전체시간은 서울 약+0.05초·부산+0.07초로 암말이 조금 느렸다. 단거리 전체에서 암말이 더 빠르다는 결과는 나오지 않았다.

1600~1800m에서는 서울+0.23초로 수말이 빠른 방향이 남지만, 부산+0.01초의 구간은0을 포함했다. 서울 단거리의 작은 차이도 같은 경주의5위 이내끼리 비교하거나 최근2년만 보면 불확실해진다. 상위권에서도 초반200m의 암말 우세와 전체 기록을 구분해야 한다.

예를 들어5위에 든 암말과 수말의 기록이 비슷하더라도, 두 집단이5위 안에 드는 성과까지 같다는 뜻은 아니다. 정상 완전 혼합 경주의 전체 출전자에서는 암말의5위 이내 성과가 수말보다 서울 단거리4.75%p·중거리6.63%p, 부산3.40%p·5.15%p 낮았다. 이는 조건부 성과 차이이며 개별 말의 예측확률이 아니다.

상위권은 각 출전 최종1~5위이며 고등급이나 평생 우수마가 아니다.2018년 이후 서울·부산151,074행 중69,639행을 선택했다. 서울 종료일2026-09-20·부산2026-09-18이고 거리별 종료일은 다르다. 결과를 보고 집단을 좁히면 비교 구성도 바뀐다.1900m 이상은 희소해 일반화하지 않았다. 체중 차이는 유지되며5위 이내 암말도 수말보다 약20~21kg 가볍다.

[전체 결과와95%구간](README.md) · [기록 그림](figures/top5_time_comparison.png) · [5위 이내 성과 그림](figures/top5_entry_difference.png) · [게시 데이터](outputs/publication_summary.json). 기존 기준·운영·웹사이트 배포를 변경한 결과가 아니다.
''')
primary=pd.concat([take(parts=['finish','early','late']),take(cohort='all',parts=['finish']),take('race_outcome','all','race_full',parts=['top5']),take('race_selected_time','top5','race_full',parts=['finish']),take(window='complete_2024_2025',parts=['finish'])])
obj=dict(title='5위 이내 말의 성별 기록과 성과',status='research_publication_prepared',selection='final rank 1..5, per outing',input_n=151074,selected_n=69639,causal=False,operational_correction=False,weight_summary=s[s.scope.eq('venue')].to_dict('records'),primary_contrasts=primary.to_dict('records'),figures=['figures/top5_time_comparison.png','figures/top5_entry_difference.png'],source='source_and_method.json')
(O/'publication_summary.json').write_text(pd.Series(obj).to_json(force_ascii=False,indent=2)+'\n')
rows=['# 5위 이내 성별 분석 전체 대비','\n시간은초/1000m당 초, 중량은kg, 성과는%p. target−reference이며 시간 양수는target이 느린 방향. 전체 대비의 점별95%구간이며 선택 집단과 전체 성과를 구분한다.\n','| 범위 | 표본 | 지역 | 기간 | 통제 | 비교 | 지표 | 대비 | 차이 | 95%구간 | 공통행 |','|---|---|---|---|---|---|---|---|---:|---|---:|']
for _,a in r.iterrows():rows.append(f'| {a.scope} | {a.cohort} | {a.meet} | {a.window} | {a.specification} | {a.target}−{a.reference} | {a.part} ({a.unit}) | {a.contrast} | {a.difference:+.5f} | [{a.lower:+.5f},{a.upper:+.5f}] | {a.common_n} |')
(H/'ALL_RESULTS.md').write_text('\n'.join(rows)+'\n');print('reports and two figures rendered')
