"""Render verified conditional-load curves and complete research/publication reports."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures';F.mkdir(exist_ok=True)
r=pd.read_csv(O/'load_contrasts.csv');m=pd.read_csv(O/'model_diagnostics.csv');v=json.loads((O/'verification.json').read_text());assert v['passed']
font=Path('/System/Library/Fonts/AppleSDGothicNeo.ttc')
if font.exists():font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']=[font_manager.FontProperties(fname=str(font)).get_name(),'DejaVu Sans']
plt.rcParams.update({'axes.unicode_minus':False,'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':180})

def select(window='all',spec='horse_race_full',part='finish',dist=None,contrast='load_change'):
 q=r[r.window.eq(window)&r.specification.eq(spec)&r.part.eq(part)&r.contrast.eq(contrast)]
 return q[q.distance_m.eq(dist)] if dist is not None else q

def ci(a):return f'{a.difference_seconds:+.3f} [{a.lower:+.3f}, {a.upper:+.3f}]' if a.supported else f'{a.difference_seconds:+.3f} [지원 부족]'

def kg_table(window='all',spec='horse_race_full'):
 q=select(window,spec,dist=1200);rows=['| 지역 | 마체중450kg | 마체중480kg | 마체중510kg |','|---|---:|---:|---:|']
 for meet in ['서울','부산']:
  g=q[q.meet.eq(meet)&q.to_load.eq(55)].set_index('body_kg');rows.append(f'| {meet} | '+' | '.join(ci(g.loc[b]) for b in [450,480,510])+' |')
 return '\n'.join(rows)
fig,axes=plt.subplots(1,2,figsize=(11.5,5),sharey=True)
colors=['#c74a73','#4166af','#3a8d79']
for ax,meet in zip(axes,['서울','부산']):
 ax.axhline(0,color='#999',lw=1);ax.axvline(54,color='#bbb',lw=1)
 for body,color in zip([450,480,510],colors):
  q=select(dist=1200);q=q[q.meet.eq(meet)&q.body_kg.eq(body)].copy();q=pd.concat([q,pd.DataFrame([dict(to_load=54,difference_seconds=0,lower=0,upper=0,supported=True)])]).sort_values('to_load');a=q[q.supported];bad=q[~q.supported]
  ax.plot(a.to_load,a.difference_seconds,'o-',color=color,label=f'마체중{body}kg');ax.fill_between(a.to_load,a.lower,a.upper,color=color,alpha=.10)
  ax.scatter(bad.to_load,bad.difference_seconds,facecolors='none',edgecolors=color,marker='s')
 ax.set_title(meet+'1200m');ax.set_xticks(range(52,59));ax.set_xlabel('부담중량 kg');ax.grid(alpha=.15);ax.legend(fontsize=9)
axes[0].set_ylabel('54kg 대비 전체시간 차이 초 · 양수는 느림');fig.suptitle('같은 말과 같은 경주를 맞춘 부담중량별 기록 차이',y=.98)
fig.text(.5,.01,'조건부 관찰 추정 · 음영 점별95%구간 · 빈 사각형은 체중/중량 지점 지원 부족 · 인과 손실 또는 운영 보정이 아님',ha='center',fontsize=9)
fig.tight_layout(rect=[0,.07,1,.92]);fig.savefig(F/'conditional_load_curves.png');plt.close(fig)
fig,axes=plt.subplots(1,2,figsize=(11.5,5.5))
for ax,meet in zip(axes,['서울','부산']):
 q=select(contrast='light_minus_heavy');q=q[q.meet.eq(meet)].sort_values('distance_m');ax.axvline(0,color='#999',lw=1)
 for y,(_,a) in enumerate(q.iterrows()):
  if a.supported:ax.errorbar(a.difference_seconds,y,xerr=[[a.difference_seconds-a.lower],[a.upper-a.difference_seconds]],fmt='o',capsize=3,color='#4166af')
  else:ax.scatter(a.difference_seconds,y,marker='s',facecolors='none',edgecolors='#999')
 ax.set_yticks(range(len(q)),[f'{x}m' for x in q.distance_m]);ax.invert_yaxis();ax.set_title(meet);ax.set_xlabel('450kg−510kg의 54→55kg 기록 차이 초');ax.grid(axis='x',alpha=.15)
fig.suptitle('가벼운 말의 중량 증가 손실이 더 크다는 관계는 일관되지 않는다',y=.98,fontsize=14)
fig.text(.5,.01,'양수는450kg 말의 추정 변화가 더 큼 · 점별95%구간 · 지원12개 직접 대비 BH q 최소 약0.34',ha='center',fontsize=9);fig.tight_layout(rect=[0,.07,1,.92]);fig.savefig(F/'body_modifier_by_distance.png');plt.close(fig)
q=select(dist=1200);wide=['| 지역 | 부담중량 | 450kg 말 | 480kg 말 | 510kg 말 |','|---|---:|---:|---:|---:|']
for meet in ['서울','부산']:
 for weight in range(52,59):
  if weight==54:vals=['0 기준']*3
  else:
   g=q[q.meet.eq(meet)&q.to_load.eq(weight)].set_index('body_kg');vals=[ci(g.loc[b]) for b in [450,480,510]]
  wide.append(f'| {meet} | {weight}kg | '+' | '.join(vals)+' |')
dist=['| 지역 | 거리 | 480kg 말의54→55kg 초 | 450−510kg의1kg 변화 차이 초 | BH q |','|---|---:|---:|---:|---:|']
for _,a in select(contrast='light_minus_heavy').iterrows():
 b=select(dist=a.distance_m).query('meet==@a.meet and body_kg==480 and to_load==55').iloc[0]
 dist.append(f'| {a.meet} | {a.distance_m} | {ci(b)} | {ci(a)} | '+(f'{a.modifier_bh_q:.3f}' if a.supported else 'null')+' |')
sel=m[m.distance_m.eq(1200)];diag=['| 지역 | 기간/표본 | 모형 | 입력 | 분석 | 제외 | 말 | 경주 | 중량 변화 말 |','|---|---|---|---:|---:|---:|---:|---:|---:|']
for a in sel.itertuples():diag.append(f'| {a.meet} | {a.window} | {a.specification} | {a.input_n} | {a.n} | {a.pruned_n} | {a.horses} | {a.races} | {a.changing_load_horses} |')
mod=select(contrast='light_minus_heavy',dist=1200).set_index('meet')
text=f'''# 마체중별 부담중량 증가와 기록 차이

2026-10-08. **부담중량별 조건부 기록 차이를 추정할 수 있다.1200m에서480kg 말의54→55kg 차이는 서울 약+0.055초·부산+0.031초다. 그러나 가벼운 말이 같은1kg 증가에 더 큰 손실을 본다는 관계는 충분히 확인되지 않았다.** 체중별 격차의 방향이 지역·거리·모형에 따라 바뀌며 인과적 손실이나운영 환산계수로 확정할 수 없다.

## 자료와 질문

[성별 연구의 검증된 모집단](../20261007_sex_ability_gap/README.md)151,074출전·13,928경주·12,435두를 읽기 전용 재사용했다.2018년 이후 서울2026-09-20·부산2026-09-18까지이며 거리별 종료일은 다르다. 출전 당시 체중·부담중량·성별을 쓰고,정상 완주/구간 품질 선택을 계승했다. 제주·영천·주행심사·주로빠르기는 제외했다.

[기존1200m 중량 비율 연구](../20261005_relative_load1200/README.md)는 부담중량 표현에 따른 예측오차 차이를 평가했다. 그 작은 오차 감소는1kg의 기록 손실이 아니었다. 이번 질문은 체중을 고정한 상태에서 부담중량 차이에 동반하는 시간 차이와 그 차이가 체중에 따라 달라지는가다. 물리 실험이나중량을 무작위 배정한 시험이 아니다.

주 분석은 같은 지역·정확 거리별2000행/100날짜 이상인1000~1800m의13개 조합이다. 기타 거리는 [지원표](outputs/distance_eligibility.csv)에 남기고 일반 손실을 추정하지 않았다. 전체 출전에서 먼저 추정하며5위 이내는1200m의 별도 민감도다. 예측 개선·우승확률·새 기록 보정은 평가하지 않았다.

## 같은 말과 같은 경주를 맞춘 1kg 차이

부담중량54kg를 기준으로55kg의 전체시간 차이다. **양수는 느린 방향**이며 괄호는 점별95%구간이다. 같은 말과 같은 경주의 효과에 나이·rating·과거 성과/출전수/공백 등을 더했다. 같은 경주 효과가 거리·날짜·등급·함수율·월 등 해당 경주에 공통인 조건을 흡수한다.

{kg_table()}

서울에서는450kg의+0.064초가510kg의+0.047초보다 크지만, 둘의 직접 차이는 {ci(mod.loc['서울'])}초로0을 포함한다. 부산은450kg+0.026초·510kg+0.036초로 반대 순서이며 직접 차이 {ci(mod.loc['부산'])}초도0을 포함한다. 따라서 체중이 가벼울수록 손실이 확실히 크다는 공식은 얻지 못했다.450kg 부산의1kg 차이 자체도0을 포함한다.

## 부담중량별 기록 차이

아래는 각각의 체중에서54kg 대비 차이다. 같은 체중의52kg과55kg를 비교할 때54kg 기준 차이끼리 단순히 독립값처럼 표준오차를 합치지 않는다. 결과표는 지정한54kg 대비 공동모형 대비를 제공한다.54kg 행의0은 정의상 기준이며 미관측값을0으로 채운 것이 아니다. 지원 부족은 점추정만 잠정 표시하고95%구간을 비웠다.

{chr(10).join(wide)}

![부담중량별 추정 곡선](figures/conditional_load_curves.png)

480kg의54→56kg 차이는 서울 약+0.106초·부산+0.063초,54→57kg는+0.151초·+0.097초다.57kg 부산480kg의구간은0을 포함한다. 제곱항을 포함했으므로1kg 추정치에 증가kg을 단순 곱한 표가 아니다.58kg은 대부분 체중/중량 지점의 표본이 부족해 강한 해석을 하지 않는다.

## 거리별로 같은가

{chr(10).join(dist)}

![거리별 체중 상호작용](figures/body_modifier_by_distance.png)

서울1400m의450−510kg 차이는 약+0.040초로 점별 구간이0보다 높다. 그러나 지원된12개 전체시간 체중 대비의다중비교를BH로 조정하면 최소q는 약0.345다. 이 일부 결과를 가벼운 말의 보편적 손실로 일반화하지 않는다. 서울1600m의체중 직접 대비는 지점 지원 부족으로구간을 제공하지 않았다. 다른 지표·중량표 전체의 다중비교 조정까지 완료했다는 뜻은 아니다.

## 모형을 바꾸면 결과가 달라지는가

부담중량 배정이 능력·편성·성별 등과 관련되므로 통제 방법에 따라 추정치가 달라진다. 아래 단계들은 같은 질문의 인과 분해가 아니다. 원시는 중량/체중 제곱항·상호작용만,같은 경주는 성별·나이·rating·이력 통제를 더한 값이다. 같은 말까지 맞춘 주 모형은 반복 출전 일부만 남는다.

원시1200m:

{kg_table(spec='raw')}

같은 경주와 이력 통제:

{kg_table(spec='race_full')}

같은 말/경주에서rating을 제외:

{kg_table(spec='horse_race_no_rating')}

같은 경주 통제만으로 일부 음의 값이 나오더라도 무거워지면 빨라지는 물리 효과로 해석하지 않는다. 좋은 말의 높은 중량 배정·성장/컨디션·통제 구조 등이 섞인다. 말 효과를 추가해도 중량 배정의 내생성은 남는다. rating 제외 시480kg의54→55kg는 서울 약+0.044초·부산+0.045초로 주 모형과 크기가 바뀐다.

## 최근 기간과 상위5위 민감도

2024~2025 완결연도만 쓰면480kg의1kg 차이는 서울 약+0.045초·부산+0.014초로 두 구간 모두0을 포함한다. 표본 감소와 시간 변화가 함께 있어 최근에도 같은 환산계수를 쓸 근거는 부족하다. 최근1000m는 같은 말/경주 반복 구조를 남긴 뒤 부산59행·서울32행에 불과해 생략했다. 사유와원수는 [모형 생략표](outputs/skipped_models.csv)에 있다.

{kg_table(window='complete_2024_2025')}

5위 이내만 고르면 서울480kg의차이는 약+0.008초로 작아지고0을 포함한다. 이미 잘 뛴 출전만 남긴 결과로 전체 부담중량 손실의 검증이 아니다. 전체 기록과 실제5위 이내 성과는 [직전 연구](../20261007_sex_top5_followup/README.md)에서 구분했다.

{kg_table(window='top5_selected')}

## 표본과 계산

{chr(10).join(diag)}

같은 말/경주 모형은 재귀적으로1행뿐인 말이나경주를 제거한다. 주1200m는 서울24,961→23,524행·부산16,662→15,509행이다. 제외는 기록의 좋고 나쁨을 기준으로 한 절사가 아니며,반복 비교 가능 집단으로 질문이 좁아진다. 각 거리의입력/분석/제외·연결요소·중량 변화 말수·수렴오차는 [진단표](outputs/model_diagnostics.csv)에 있다.

모형은 W=부담중량−54, B=(마체중−480)/50에 대해 W,W²,B,B²,W×B를 포함한다.1kg 차이는 W=0→1의대비이며450−510kg 체중 차이는공동계수의직접 대비다. 지역·거리별로 따로 적합한다. 모형 형태 밖의 비선형 관계나개별 말의 최적체중을 식별하지 않는다. 시간은초이며초반/마지막200m도모든 대비에 함께 보존했다. 겹치는600m를 합산하거나서울 미계측400m를 생성하지 않았다.

경주 및 말 효과는 번갈아 잔차화해 흡수했다. 이분 그래프 연결요소를 구해고정효과rank=말수+경주수−연결요소로 자유도를 계산했다. 동일 말에서 변하지 않는 성별의효과를 식별했다고 주장하지 않는다. 잔차행렬의SVD 기준을 적합·식별·자유도에 일관되게 적용해수치오차로 흡수된 변수를 자유도로 다시 세지 않았다. 원천 결측은 유지하고통제행렬 안에서만 중앙값과결측 지시자를 썼다.

불확실성은마필/지역별 날짜의이원 군집과각 단독 군집 중 최대 분산,고정효과 자유도와t(min군집−1) 보정이다. 각 체중지점±15kg·중량지점±0.5kg에100행·30두·20날짜가 있어야 구간을 표시했다.54→55kg는양 지점,450−510 대비는네 지점 모두를 요구했다. 이 근방 지원은같은 말의무작위1kg 변화나균형 배정을 보장하지 않는다. 다수 비교의점별 근사 구간이며인과적 보장을 주지 않는다.

## 검증과 보존

입력5개 해시·행/경주 고유성·중량/체중 유효성·구간 합을 확인했다. 기존1200m41,623행의공식 중량/체중과현재 입력이동일함을대조했다. DuckDB집계·모든구간 산식·독립BH계산도 확인했다. 반복 잔차화와 다른 방식인희소 고정효과 그래프의연결요소별 기준 제거·LU투영·QR회귀·pandas군집 합으로{v['independent_model_count']}모형/{v['independent_contrast_rows']}대비를 검증했고총{len(v['checks'])}수치 검사를 통과했다. 계산 검증이중량 배정의 인과성을 증명하지는 않는다.

[계획](PLAN.md) · [출처](SOURCES.md) · [전체3705대비](ALL_RESULTS.md) · [결과CSV](outputs/load_contrasts.csv) · [관측분포](outputs/observed_body_load_cells.csv) · [진단](outputs/model_diagnostics.csv) · [검증](outputs/verification.json) · [게시요약](PUBLICATION.md) · [게시데이터](outputs/publication_summary.json) · [용량명세](outputs/artifact_inventory.json).65모형을 적합했고사전지원13거리의최근2모형은생략했다. 기존 연구·운영·기준·배포는변경하지 않았다.

```sh
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python thoroughbred/research/20261008_body_load_time_loss/analyze.py
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python thoroughbred/research/20261008_body_load_time_loss/verify.py
MPLCONFIGDIR=/private/tmp/body_load_plot PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261008_body_load_time_loss/render.py
```
'''
text=text.replace('## 표본과 계산\n','## 표본과 계산\n\n관측 분포 CSV의420~540kg 네 구간은 열람용이다. 모형에는 이 구간 밖의 유효 체중도 포함했고, 체중이나 기록 분위수로 추가 절사하지 않았다.\n')
(H/'README.md').write_text(text)
(H/'PUBLICATION.md').write_text('''# 체중에 따라 부담중량의 기록 차이가 달라지는가

같은 말과 같은 경주 조건을 맞춘1200m에서,480kg 말의 부담중량54→55kg 차이는 서울 약+0.055초·부산+0.031초로 느린 방향이었다.54→56kg는 약+0.106초·+0.063초다. 관찰 자료의 조건부 추정이며 물리적 손실이나 기록 보정값으로 확정한 수치는 아니다.

450kg과510kg을 비교하면 서울은 가벼운 말의1kg 차이가 조금 크고 부산은 반대였다. 두 지역의 직접 대비95%구간은0을 포함했다. 거리별 일부 관찰도 다중비교를 고려하면 일반 법칙을 지지하지 않는다. 체중이 작다는 이유만으로 같은1kg에 일정 비율의 초 손실을 추가할 근거는 부족하다.

예를 들어480kg·55kg의 기록을54kg으로 읽고 싶더라도, 서울의 추정값+0.055초를 자동 차감하지 않는다. 해당 말의 건강·성장·능력 변화와 중량 배정 이유가 함께 섞이며, 최근2년만 분석하면1kg 차이의 구간도0을 포함한다.58kg과 일부 체중 지점은 지원이 부족하다. 상위5위만 고른 값은 이미 잘 뛴 출전의 선택 결과다.

2018년 이후 서울·부산 정상151,074출전 중 반복 비교가 가능한 표본을 썼다. 종료일은 서울2026-09-20·부산2026-09-18이며 거리별로 다르다. 예측 개선·우승확률·성별 또는 중량 보정·운영 적용은 확정하지 않았다.

[상세표와95%구간](README.md) · [부담중량 곡선](figures/conditional_load_curves.png) · [거리별 체중 대비](figures/body_modifier_by_distance.png) · [게시 데이터](outputs/publication_summary.json).
''')
primary=r[r.distance_m.eq(1200)&r.specification.eq('horse_race_full')]
obj=dict(title='마체중별 부담중량 증가와 기록 차이',status='research_publication_prepared',causal=False,operational_correction=False,input_n=151074,formula='W=load-54; B=(body-480)/50; W+W^2+B+B^2+W*B',primary1200=primary.to_dict('records'),all_distance_body_modifiers=select(contrast='light_minus_heavy').to_dict('records'),figures=['figures/conditional_load_curves.png','figures/body_modifier_by_distance.png'],source='source_and_method.json')
(O/'publication_summary.json').write_text(pd.Series(obj).to_json(force_ascii=False,indent=2)+'\n')
rows=['# 체중별 부담중량 전체 대비','\n조건부 시간 차이이며 인과 손실·운영 보정이 아니다. 양수는느린 방향. 지원 부족 구간은null.52~58kg은54kg 대비이며light_minus_heavy는450−510kg의54→55kg 직접 대비다.\n','| 지역 | 거리 | 기간/표본 | 모형 | 지표 | 대비 | 체중 | 중량 | 차이 초 | 점별95%구간 | 지원 |','|---|---|---|---|---|---|---|---|---:|---|---|']
for a in r.itertuples():rows.append(f'| {a.meet} | {a.distance_m} | {a.window} | {a.specification} | {a.part} | {a.contrast} | {a.body_kg} | {a.from_load}→{a.to_load} | {a.difference_seconds:+.5f} | '+(f'[{a.lower:+.5f},{a.upper:+.5f}]' if a.supported else 'null')+f' | {a.supported} |')
(H/'ALL_RESULTS.md').write_text('\n'.join(rows)+'\n');print('rendered reports and two figures')
