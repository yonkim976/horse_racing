"""Create reader report, charts and publication data from verified estimates."""
from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures';F.mkdir(exist_ok=True)
r=pd.read_csv(O/'coefficients.csv');tv=pd.read_csv(O/'temporal_validation.csv');c=pd.read_csv(O/'candidates.csv');raw=pd.read_csv(O/'unadjusted_associations.csv');v=json.loads((O/'verification.json').read_text());assert v['passed']
font=Path('/System/Library/Fonts/AppleSDGothicNeo.ttc')
if font.exists():font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']=[font_manager.FontProperties(fname=str(font)).get_name(),'DejaVu Sans']
plt.rcParams.update({'axes.unicode_minus':False,'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':170})
def sel(meet='전체',window='all',spec='main',dist=0):return r[(r.meet==meet)&(r.window==window)&(r.specification==spec)&(r.distance_m==dist)].iloc[0]
def ci(a,scale=1):return f'{a.coefficient*scale:+.3f} [{a.lower*scale:+.3f}, {a.upper*scale:+.3f}]'
whole=sel();recent=sel(window='complete_2024_2025');e=pd.read_csv(O/'eligibility.csv');diag=pd.read_csv(O/'diagnostics.csv')
fig,axes=plt.subplots(1,2,figsize=(11,4.5))
for ax,meet in zip(axes,['서울','부산']):
 for i,(window,label,col) in enumerate([('all','전체 기간','#326bab'),('complete_2024_2025','2024~2025','#d07446')]):
  a=sel(meet,window);ax.errorbar(a.coefficient,i,xerr=[[a.coefficient-a.lower],[a.upper-a.coefficient]],fmt='o',capsize=5,color=col,label=label)
 ax.axvline(0,color='#888',lw=1);ax.set_yticks([0,1],['전체 기간','2024~2025']);ax.set_title(meet);ax.set_xlabel('1kg 증가의 시간 차이 · 초/1000m');ax.grid(axis='x',alpha=.15)
fig.suptitle('성별 구분 없이 추정한 부담중량 1kg의 평균 기록 차이',fontsize=14);fig.text(.5,.015,'같은 말×거리·같은 경주·과거 이력 통제 · 점별95%구간 · 최근 구간은0 포함 · 인과 효과 미확정',ha='center',fontsize=9);fig.tight_layout(rect=[0,.07,1,.91]);fig.savefig(F/'pooled_load_slopes.png');plt.close(fig)
fig,axes=plt.subplots(1,2,figsize=(11,5))
for ax,meet in zip(axes,['서울','부산']):
 q=r[(r.meet==meet)&r.distance_m.gt(0)&r.window.eq('all')&r.specification.eq('main')].sort_values('distance_m')
 ax.errorbar(q.seconds_per_kg,np.arange(len(q)),xerr=np.array([q.seconds_per_kg-q.lower_seconds_per_kg,q.upper_seconds_per_kg-q.seconds_per_kg]),fmt='o',capsize=3,color='#326bab');ax.axvline(0,color='#888',lw=1);ax.set_yticks(np.arange(len(q)),[f'{x}m' for x in q.distance_m]);ax.invert_yaxis();ax.set_title(meet);ax.set_xlabel('해당 거리의 1kg 증가 시간 차이 · 초');ax.grid(axis='x',alpha=.15)
fig.suptitle('공통 평균은 거리별 차이를 요약한 값이다',fontsize=14);fig.text(.5,.015,'거리별 별도 추정 · 점별95%구간 · 서울1600m 등은0 포함 · 공통값이 모든 거리의 실제 효과라는 뜻은 아님',ha='center',fontsize=9);fig.tight_layout(rect=[0,.07,1,.91]);fig.savefig(F/'distance_load_slopes.png');plt.close(fig)
pool=['| 구분 | 전체 기간 초/(kg·1000m) | 2024~2025 초/(kg·1000m) |','|---|---:|---:|']
for meet in ['서울','부산','전체']:pool.append(f'| {meet} | {ci(sel(meet))} | {ci(sel(meet,"complete_2024_2025"))} |')
dist=['| 지역 | 거리 | 반복 비교 출전 수 | 1kg당 초 [95%구간] |','|---|---:|---:|---:|']
for a in r[r.distance_m.gt(0)&r.window.eq('all')&r.specification.eq('main')].itertuples():dist.append(f'| {a.meet} | {a.distance_m}m | {a.n:,} | {ci(a,a.distance_m/1000)} |')
sens=['| 모형 | 서울 전체 | 부산 전체 | 서울 최근 | 부산 최근 |','|---|---:|---:|---:|---:|']
for spec,label in [('main','말/경주+이력'),('fe_only','말/경주만'),('body_direct','말/경주+이력+체중 직접항')]:sens.append('| '+label+' | '+' | '.join(ci(sel(meet,window,spec)) for window in ['all','complete_2024_2025'] for meet in ['서울','부산'])+' |')
temporal=['| 지역 | 보류연도1~8월 | 날짜수/지원 | 이전 추정계수 | 보류기간 계수 [95%] | RMSE 변화 | MAE 변화 |','|---|---:|---|---:|---:|---:|---:|']
for a in tv.itertuples():
 test=sel(a.meet,f'test_{a.test_year}_jan_aug');support='충분' if test.supported else '부족'
 temporal.append(f'| {a.meet} | {a.test_year} | {int(test.dates)}/{support} | {a.train_coefficient:.3f} | {a.test_coefficient:.3f} [{a.test_lower:.3f}, {a.test_upper:.3f}] | {a.corrected_rmse-a.baseline_rmse:+.6f} | {a.corrected_mae-a.baseline_mae:+.6f} |')
illustrations=[]
for distance in [1000,1200,1300,1400,1600,1700,1800]:
 for burden in range(52,58):illustrations.append(dict(distance_m=distance,carried_kg=burden,reference_kg=54,illustrative_coefficient=.03,time_to_add_for54=-.03*(burden-54)*distance/1000,adopted=False))
pd.DataFrame(illustrations).to_csv(O/'illustrative_003_lookup.csv',index=False)
lookup=['| 거리 | 1kg당 | 3kg 차이 |','|---|---:|---:|']
for distance in [1000,1200,1400,1600,1800]:lookup.append(f'| {distance}m | {distance/1000*.03:.3f}초 | {distance/1000*.09:.3f}초 |')
unadjusted=raw[raw.window.eq('all')].set_index('meet')
body=f'''# 성별 구분 없는 부담중량 기록 보정계수

2026-10-08. **같은 말의 반복 출전과 같은 경주, 과거 성적을 맞추면 부담중량1kg 증가에 동반하는 평균 시간 차이는1000m당 전체 {whole.coefficient:.3f}초다.** 서울 {sel('서울').coefficient:.3f}초·부산 {sel('부산').coefficient:.3f}초로, 기록 비교를 위한 연구용 시작값은 **0.03초/(kg·1000m)**로 요약할 수 있다. 다만 최근 구간과 거리별 차이가 있어 고정 보정의 채택은 보류한다. 성별에 따른 기준이나 체중별 보정은 만들지 않았다.

## 무엇을 계산했는가

기존 정상151,074출전·13,928경주·12,435두를 읽기 전용 재사용했다. 원천은2018년 이후 서울2026-09-20·부산2026-09-18까지다.1000~1800m에서2000출전/100날짜 이상인13개 지역·정확 거리의 입력 {int(e[e.eligible].n.sum()):,}행을 사용하고, 단독 말/경주를 반복 제외한 **{int(whole.n):,}출전·{int(whole.horses):,}두·{int(whole.races):,}경주**가 주 모형에 남았다. 이는 정상 완주 중 반복 비교가 가능한 집단이다. 해당 경주 전체 출전원이 모두 남았다는 뜻은 아니다.1900m 이상·제주·영천·주행심사와 주로빠르기는 이번 범위에 없다.

잘 달리는 말이 더 무겁게 배정되는 문제를 줄이기 위해 지역×정확 거리별로 같은 말 효과와 같은 경주 효과를 제거했다. 경주 효과에는 등급·날짜·함수율·계절 등 같은 경주의 공통 조건이 포함된다. rating과 과거 착순 성과·초반 위치·출전수·공백·나이 제곱항도 통제했다. 성별 피처는 전혀 넣지 않았고 주 모형에는 체중 피처도 없다. 현재 착순·당일 전개는 통제하지 않는다. 선형 나이는 말과 경주 효과로 흡수되므로 별도 계수로 세지 않는다.

부담중량만 단순 비교하면 서울 {unadjusted.loc['서울','coefficient']:+.3f}·부산 {unadjusted.loc['부산','coefficient']:+.3f}초/(kg·1000m)다. 이 원시 비교는 지역·거리 절편만 맞춘 값으로, 말의 실력·편성 차이가 섞여 있다. 주 모형과 표본도 다르므로 두 값의 차이를 순수한 편향 크기로 분해하지 않는다. **어느 방향이든 원시 중량·시간 상관을 중량의 인과효과로 해석하지 않는다.**

## 전체 기간 평균과 최근 기간

양수는 부담중량 증가에 따라 느려지는 방향이다. 괄호는 마필/날짜 군집을 반영한 점별95%구간이다. 전체 계수는 지역×거리마다 별도로 제거한 통제 잔차를 합친 단일 기울기다. 단순 산술평균이 아니라 통제 후 남는 중량 변동이 큰 집단에 더 가중된 공통 계수다.

{chr(10).join(pool)}

최근2024~2025년의 전체 계수는 {recent.coefficient:.3f}초로 작아지고95%구간에0이 들어간다. 최근 반복 비교 {int(recent.n):,}행이며1000m는 반복 표본이 부족해 양 지역 모두 생략했다. 기간뿐 아니라 포함 거리·말 구성도 달라져 효과가 줄었다고 확정하지 않는다. 전체기간 평균의 양수 관계와 최근 고정값의 불확실성을 구분한다.

![지역별 평균과 최근 추정](figures/pooled_load_slopes.png)

## 기록을 비교할 때의 초안

평균 관찰값을 반올림한 **0.03초/(kg·1000m)**를 실험적 비교값으로 사용한다면 다음과 같다. 이 반올림은 최적 예측값을 선택한 결과가 아니다.

{chr(10).join(lookup)}

`54kg 환산 기록 = 원기록 − 0.03 × (부담중량−54) × 거리(m)/1000`

예를 들어1200m를75.000초에 뛴57kg 말은74.892초로,51kg 말은75.108초로 환산되는 계산이다. 다만 설명용 비교 범위는52~57kg이며51kg 사례는 외삽을 피하기 위해 실제 표에 사용하지 않는다. 실용 사례로52kg의75.000초는75.072초,57kg의75.000초는74.892초다. 같은 기록이라면 무거운 중량에서 뛴 출전을 약간 높게 평가한다.54kg는 계산의 기준점이며 공식 표준이나 최적 중량이라는 의미가 아니다. 기수 체중을 공식 부담중량에 다시 더하지 않는다.

이 공식은 거리 비례를 강제한 요약이다. 서울1200m의 별도 추정은0.059초/kg,부산은0.031초/kg로 공통값0.036초와 다르다.**모든 거리에서1kg 손실이 똑같다고 확인된 것은 아니다.**52~57kg 안의 작은 비교에 한정하며, 정상 완주 밖·다른 지역·큰 중량 변화에 외삽하지 않는다. 이 표는 공식 기록, 기존 함수율 보정, 채택된 거리별 기준에 자동 합산하지 않는다.

후보 선택용 보수적 기준은 전체와최근의95%구간 하한이 모두 양수일 때 두 점추정 중 작은 값의50%를0.005초 단위로0쪽 버림하는 것이다. 계획의양수조건을CI하한으로엄격히명시한실행보충을함께남겼다. 세 공통집계 모두최근 조건을 통과하지 못해 **추가 채택 후보는0(보류)**다. 이는 부담중량 효과가0이라고 추정한 값이 아니다. 관찰 평균0.03과0인채택상태를 구분하기 위해 [평균 설명표](outputs/illustrative_003_lookup.csv)와 [채택 보류표](outputs/correction_lookup.csv)를 따로 보존했다.50% 수축 정책 자체도 최적성 검증이 없는 초안이다.

## 거리별로 얼마나 다른가

{chr(10).join(dist)}

![거리별 kg 계수](figures/distance_load_slopes.png)

서울1400·1600·1700·1800m 등은0을 포함한다.1000m 전체기간 계수는 양수지만 최근 표본 부족과 구형 편성의 영향을 유의해야 한다. 개별 거리의 점별 구간을 다중비교 후 확정된 효과로 표현하지 않는다. 지역 간 계수 차이의 직접 검정 없이 서울/부산 효과가 다르다고 확정하지 않는다.

## 통제 방법과 체중을 바꾸면

단위는 모두초/(kg·1000m)다. 체중 직접항은체중과제곱항을 추가하며중량×체중 상호작용은넣지 않는다. 성별은모든모형에서제외한다.

{chr(10).join(sens)}

체중 직접항 추가는 전체계수를 거의 바꾸지 않았다. 반면 과거 이력·rating 통제 유무에 따라 값이 달라져, 전체기간에는 대략0.02~0.03초 범위로 읽는 것이 타당하다. 이것은 신뢰구간이나 최근에도 보장되는 범위가 아니다. 시간에 따라 바뀌는 실력·건강·훈련과 중량 배정의 관계는 남아 있으므로 **순수한 인과적 손실을 식별했다고 할 수 없다.**

## 연도를 넘겨 적용해 본 결과

2024/2025/2026년의1~8월을 보류하고 이전 연도들의1~8월로 추정한 계수를 고정 적용했다. 보류기간 내부에서 중량을 제외한 말/경주·이력을 다시 맞춘 뒤, 그 잔차에 과거 계수를 적용했다. 따라서 이것은 **조건부 보정량의 기간 안정성 진단이며 다음 경주의 사전예측 검증이 아니다.** 세 연도를 같은 월로 맞춰2026부분연도 차이를 줄였다.

{chr(10).join(temporal)}

계수와 오차는 1000m 환산 초다. 음의 오차 변화가 개선이며 변화는 매우 작다. 지역별 짧은 보류 구간은 65~68날짜로 100날짜 지원 조건을 못 채웠다. 전체 2024년도 99날짜다. 해당 구간과 점추정은 탐색 진단으로 보존하며 안정된 보정 근거로 채택하지 않는다. 서울 2026년에는 RMSE와 MAE가 모두 소폭 악화했다. 다른 지역/연도에서도 지표별 방향이 같지 않다. 강한 보정으로 성능이 좋아진다고 결론 내릴 수 없다. 보류기간 효과·통제를 사용했으므로 이 결과를 미래 새 말/경주 예측오차로 표시하지 않는다.

## 계산과 독립 검증

고정효과 단독 행은 재귀 제거했다. 부담중량−54의 단일 선형항을 사용하고, 거리별 전체시간을 1000m당 초로 바꾼 뒤 고정효과와 이력 통제를 제거하는 FWL 계산으로 추정했다. 공통 모형에서도 거리별 통제계수는 따로 허용한다. 중량 변화가 있는 말×거리 100쌍/날짜 100개·양의 잔차 중량 분산을 지원 기준으로 두고, 300행 미만 모형은 생략했다. [진단](outputs/diagnostics.csv)·[생략표](outputs/skipped.csv)·[전체 결과](outputs/coefficients.csv)에 표본과 기간·rank·변동량이 있다.

고정효과 rank는 말+경주−그래프 연결요소, nuisance rank는 SVD 상대 기준 1e-10이다. 분산은 마필·실제 날짜·교집합 군집을 계산해 마필 단독/날짜 단독/이원 중 최대값을 쓰고 자유도와 t 보정을 했다. 합친 모형은 동일 말·날짜의 거리 간 및 지역 간 공분산도 포함한다. 날짜는 같은 실제 날짜로 묶었다. 거리별 SE를 독립으로 합치지 않았다.

별도 희소 그래프 설계·LU 투영·QR 회귀·pandas 군집 합으로 **{v['independent_distance_models']}개 거리 모형·{v['independent_pooled_models']}개 공통 모형·{len(v['checks'])}개 수치 검사**를 통과했다. 입력 해시·중복·구간 합·군집 분산·기간 분할·고정계수 오차·보정 방향과 후보 선택식을 검증했다. 수치 검증은 무작위 중량 배정이나 인과성을 보증하지 않는다.

## 보존과 재현

원연구·DB·운영·배포는 변경하지 않았다. [출처와 방법](SOURCES.md), [게시 요약](PUBLICATION.md), [게시 데이터](outputs/publication_summary.json), [독립 검증](outputs/verification.json), [파일 용량 명세](outputs/artifact_inventory.json)를 남겼다. [중앙11B](../conclusions/11B_CARRIED_WEIGHT_CORRECTION.md)는 기존11번 중량 연구의 후속이다.

실행은 프로젝트 루트에서 `OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/{H.name}/analyze.py` 후 동일 경로의 `verify.py`, `render.py` 순서다. `register.py`는 공유 목록을 수정하므로 분석 재현만 필요하면 실행하지 않는다.
'''
# Keep all examples inside the stated support range.
body=body.replace('예를 들어1200m를75.000초에 뛴57kg 말은74.892초로,51kg 말은75.108초로 환산되는 계산이다. 다만 설명용 비교 범위는52~57kg이며51kg 사례는 외삽을 피하기 위해 실제 표에 사용하지 않는다. 실용 사례로','예를 들어1200m에서')
(H/'README.md').write_text(body)
(H/'SOURCES.md').write_text(f'''# 출처와 분석 범위

2026-10-08. 입력은 [기존 성별 연구 모집단](../20261007_sex_ability_gap/outputs/population.parquet) 151,074행이다. 원천18파일·정상 완주·품질 선택·마필ID·공식 부담중량의 정의는 [원연구 출처](../20261007_sex_ability_gap/SOURCES.md)를 계승한다. 이번 분석은 성별 열을 모형에 쓰지 않는다. 입력 SHA-256·기간·행/말/경주 수는 [source_and_method.json](outputs/source_and_method.json)에 있다. 새 API·공식 규정 조회는 필요하지 않았다.

기존 [비율 연구](../20261005_relative_load1200/README.md)의 예측오차 감소를 kg 손실로 바꾸지 않고, [체중 상호작용 연구](../20261008_body_load_time_loss/README.md)의 480kg 점추정을 평균효과로 재사용하지 않았다. 새 단일 선형 중량 모형을 적합했다. 부담중량은 공식 기록값이며 기수 체중을 중복 합산하지 않는다.

모형·변수·SVD 허용오차·군집 분산·기간 보류 진단은 [보고서](README.md)와 [계획/실행 보충](PLAN.md)에 있다. 모든 성별을 합치며 성별별 기준·체중 상호작용을 사용하지 않는다. 주 모형에는 체중항이 없고 체중 직접항은 민감도만이다. 성별에 영향받는 중량 배정 자체를 제거한 무작위 시험은 아니다. 미관측 컨디션과 배정의 내생성이 남는다.

검증은 본 분석의 반복 잔차화를 가져오지 않고 희소 설계행렬에서 연결요소당 말 한 열을 제거해 LU 투영과 QR을 계산했다. 동일 마필·날짜의 거리 간 상관을 유지한 공통 SE와 과거 고정계수의 보류 잔차 오차를 검증했다. 실행 중에 전체 공통값을 추가한 점과 CI 양수 조건의 엄격한 해석은 계획 보충에 명시했다. 별도 미래 예측 검증은 아니다.

code-security의 고정 경로·읽기 전용 입력 원칙과 pages:write-page의 수치/주장 검토 기준을 적용했다. 기존 관련104파일의 목록·해시는 [baseline_inventory.json](outputs/baseline_inventory.json), 공유 파일 수정 직전과 자체 변경량은 shared_edits_baseline.json/shared_own_edits.json, 자기포함 용량은 [artifact_inventory.json](outputs/artifact_inventory.json)에 있다. 원본·입력·다른 채팅 작업을 보존한다.
''')
pub=f'''# 부담중량은 어느 정도 기록 차이로 읽을까

같은 말과 같은 경주, 과거 성적을 맞춘 평균은 **1kg당1000m 약0.03초**다. 1200m에서는 약0.036초, 1800m에서는 약0.054초를 뜻한다. 모든 성별을 합친 값이며 성별·체중별 별도 기준이 아니다.

예를 들어1200m 75.000초의57kg 출전은54kg 기준74.892초, 52kg 출전은75.072초라는 연구용 계산이다. 공식은 `원시간−0.03×(부담중량−54)×거리/1000`이다. 원기록은 그대로 두고 비교용 값만 계산한다.

전체 평균의95%구간은 [{whole.lower:.3f},{whole.upper:.3f}]초/(kg·1000m)다. 그러나 최근2024~2025년은 {recent.coefficient:.3f}초이고 구간이0을 포함한다. 거리별 값도 다르고 연도 보류 진단의 오차 개선은 작고 일관되지 않다. 따라서 **관찰 평균의 설명값이며 확정된 물리 손실·채택 보정·미래 예측 개선은 아니다.** 보정 채택은 보류했다.

자료는 정상 완주 중 반복 비교 가능한 서울·부산1000~1800m이며1900m 이상과 다른 지역에는 일반화하지 않는다. [전체 보고서](README.md)·[방법/출처](SOURCES.md)·[검증](outputs/verification.json)·[게시 데이터](outputs/publication_summary.json).
'''
(H/'PUBLICATION.md').write_text(pub)
obj=dict(title='성별 구분 없는 부담중량 기록 차이',as_of='2026-10-08',status='observational_research_average; operational adoption held',unit='seconds per kg per1000m',pooled_estimates=r[r.distance_m.eq(0)&r.window.isin(['all','complete_2024_2025'])].to_dict('records'),illustrative_rounded_coefficient=.03,illustrative_reference_kg=54,formula='time54 = original_seconds -0.03*(carried_kg-54)*distance_m/1000',candidate_decisions=c.to_dict('records'),temporal_validation=tv.to_dict('records'),source_end=json.loads((O/'source_and_method.json').read_text())['source_end'],causal=False,operational=False,forecast_validation=False,limitations=['time-varying ability and weight assignment remain confounded','full vs recent samples and distances differ','common coefficient imposes distance scaling','selected normal finishers and repeated-comparison population','heldout FE/nuisance estimated within heldout, not prospective forecasts'])
# CSV pooled sec/kg fields intentionally have NA; JSON uses null, never NaN.
def clean(x):
 if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
 if isinstance(x,list):return [clean(v) for v in x]
 if isinstance(x,float) and not np.isfinite(x):return None
 return x
(O/'publication_summary.json').write_text(json.dumps(clean(obj),ensure_ascii=False,indent=2,allow_nan=False)+'\n');print('Reports and figures written')
