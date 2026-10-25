"""Research report, individual examples, uncertainty figures and publication data."""
from pathlib import Path
import json,re
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
H=Path(__file__).resolve().parent;O=H/'outputs';F=H/'figures';m=pd.read_csv(O/'evaluation_metrics.csv');p=pd.read_parquet(O/'horse_distance_profiles.parquet');c=pd.read_csv(O/'horse_candidates.csv',dtype={'horse_id':str});s=json.loads((O/'profile_summary.json').read_text());v=json.loads((O/'verification.json').read_text());sel=json.loads((O/'selected_model.json').read_text());assert v['passed']
font=Path('/System/Library/Fonts/AppleSDGothicNeo.ttc')
if font.exists():font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']=[font_manager.FontProperties(fname=str(font)).get_name(),'DejaVu Sans']
plt.rcParams.update({'axes.unicode_minus':False,'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':170})
main=m[m.meet.eq('전체')&m.scope.eq('supported')];pool=main[main.window.eq('2024_2025')].iloc[0];improve=(pool.baseline_mae-pool.distance_mae)/pool.baseline_mae*100
fig,ax=plt.subplots(figsize=(9.5,4.8));ys=np.arange(len(main));ax.errorbar(main.estimate,ys,xerr=np.array([main.estimate-main.lower,main.upper-main.estimate]),fmt='o',color='#326bab',capsize=4);ax.axvline(0,color='#888');ax.set_yticks(ys,['2024년 · 2,883출전','2025년 · 3,297출전','두 해 합계 · 6,180출전']);ax.invert_yaxis();ax.set_xlabel('거리 항 추가 후 MAE 변화 · 상대척도 · 음수가 개선');ax.grid(axis='x',alpha=.15);fig.suptitle('거리 적성의 추가 예측 이득은 작고 불확실했다',fontsize=15);fig.text(.5,.02,f'과거만 학습 · 말/실제 날짜 군집95%구간 · 두 해 합계 MAE 감소 {improve:.3f}% · 실전 우승확률 평가가 아님',ha='center',fontsize=9);fig.tight_layout(rect=[0,.09,1,.92]);fig.savefig(F/'future_validation.png');plt.close(fig)
fig,axs=plt.subplots(1,2,figsize=(11.5,5.2))
for ax,name in zip(axs,['태양으뜸','소리태풍']):
 q=p[p.horse_name.eq(name)&p.meet.eq('부산')].sort_values('distance_m');good=q.n.ge(5);ax.axhline(0,color='#aaa',lw=1);ax.scatter(q.loc[good,'distance_m'],q.loc[good,'aptitude_effect'],s=55+q.loc[good,'n']*3,color='#326bab',label='5회 이상');ax.scatter(q.loc[~good,'distance_m'],q.loc[~good,'aptitude_effect'],s=45,marker='x',color='#999',label='1~4회 · 비교 후보 제외')
 for r in q.itertuples():ax.annotate(f'{r.n}회',(r.distance_m,r.aptitude_effect),xytext=(0,10),textcoords='offset points',ha='center',fontsize=9)
 ax.set_title(name+' · 부산');ax.set_xlabel('실제 관측 거리 m');ax.set_ylabel('자기 평균 대비 거리 편차 · 높을수록 좋음');ax.set_xticks(q.distance_m);ax.set_ylim(q.aptitude_effect.min()-.04,q.aptitude_effect.max()+.05);ax.grid(axis='y',alpha=.15);ax.legend(fontsize=8,loc='lower left')
fig.suptitle('개인 표는 한 거리의 정답보다 근거와 후보 범위를 보여준다',fontsize=14);fig.text(.5,.02,'점은 ridge 조건부 추정치이며 신뢰구간 아님 · 말마다 자기 평균0 · 미경험 거리는 추정하지 않음 · 개인 확정 적성/출전 권고 아님',ha='center',fontsize=9);fig.tight_layout(rect=[0,.07,1,.92]);fig.savefig(F/'individual_distance_examples.png');plt.close(fig)
validation=['| 검증 기간 | 비교 출전 | 거리 항 제외 MAE | 거리 항 추가 MAE | 차이 [95%구간] |','|---|---:|---:|---:|---:|']
for r in main.itertuples():validation.append(f'| {r.window} | {r.n:,} | {r.baseline_mae:.6f} | {r.distance_mae:.6f} | {r.estimate:+.6f} [{r.lower:+.6f}, {r.upper:+.6f}] |')
rep=['| 이후 연도 | 두 거리 이상 반복 비교한 말 | 과거 후보와 이후 최고거리 일치 | 후보거리−다른거리 성과 [95%구간] |','|---|---:|---:|---:|']
for r in s['replication']:rep.append(f"| {r['window']} | {r['n_horses']}두 | {r['agreement']*100:.1f}% | {r['candidate_minus_other']:+.3f} [{r['lower']:+.3f}, {r['upper']:+.3f}] |")
examples=['| 말과 지역 | 실제 근거 | 임시 후보 | 읽는 방법 |','|---|---|---|---|']
for name in ['태양으뜸','소리태풍','발키리','리치트리']:
 r=c[c.horse_name.eq(name)&c.comparison_supported].iloc[0];q=p[p.horse_key.eq(r.horse_key)&p.n.ge(5)].sort_values('distance_m');counts=' · '.join(f'{a.distance_m}m {a.n}회' for a in q.itertuples());near=str(r.near_candidates);interp='후보 차이가 작아 함께 표시' if not r.distinguishable_display else '표시 기준상 1순위 · 통계적 확정 아님';examples.append(f'| {name} · {r.meet} | {counts} | {near}m | {interp} |')
report=f'''# 말별 적정거리 후보를 구하는 방식과 검증

2026-10-08. **말별로 비교 가능한 거리 후보는 구할 수 있다. 그러나 이번 자료로 각 말의 단일 적정거리를 확정할 근거는 부족했다.** 같은 말이 실제로 여러 거리에서 뛴 이력을 조건에 맞춰 비교하고, 표본이 적은 거리의 우연한 좋은 기록을 낮게 반영하는 방식이 적절하다. 현재 계산한 표는 ‘관측한 거리 중 잘 맞는 후보’이며 미경험 거리까지 알아낸 생리적 최적값은 아니다.

## 적정거리 후보를 구하는 네 단계

1. **거리별 기록을 비교 가능한 척도로 바꾼다.** 1200m의1분15초와1800m의1분58초, 또는 둘의1000m 환산 속도를 그대로 비교하지 않는다. 같은 경주의 상대 기록을 구하고, 학습기간의 지역×거리별 기록 차이 표준편차로 나눈다. 코스와 거리의 기록 구조가 다른 점을 반영하는 상대척도다.
2. **말의 기본 수준과 당시 상태를 분리한다.** 같은 경주 효과와 당시 부담중량·연령·rating·과거 전체/초반/입상 성과·출전수·공백을 고려하고, 말의 기본 수준에 더해 특정 거리에서 얼마나 더 좋았는지 추정한다. 모든 통제변수는 과거 학습 자료에서만 정규화한다. 성별별 기준이나 주로빠르기는 쓰지 않는다.
3. **반복 출전이 적으면 거리 차이를 줄여 잡는다.** 한 번 우승한 거리나 최고기록 한 개가 정답이 되지 않도록 ridge 축소를 쓴다. 말별 거리 편차는 학습 출전수로 가중한 자기 평균이0이 되도록 한다. 0은 자기 평균이고, 다른 말의0과 능력이 같다는 뜻은 아니다.
4. **과거로 고른 후보를 이후 자료에서 확인한다.** 2023년으로 축소 강도를 고른 뒤,2024년과2025년의 결과를 각각 이전 연도까지의 자료로 평가한다. 이후 기록을 보며 후보를 다시 골라 과거 예측처럼 표현하지 않는다.

전체시간을 주대상으로 삼았다. 막판200m만 좋다고 적정거리를 고르지는 않았다. 막판은 앞선 전개에 의존하고 전체시간과 겹치는 정보이므로, 향후 후보거리 설명의 보조 항목으로 다뤄야 한다. 혈통·체중 하나만으로 거리를 정하는 공식도 만들지 않았다.

## 어느 말까지 비교할 수 있었나

자료는 서울·부산2018년 이후 서울2026-09-20·부산2026-09-18까지다. 검증된 정상151,074출전 중1000~1800m13지역×거리148,126출전을 사용했다.1900m 이상·제주·영천·주행심사는 제외했다. 서로 다른 경마장은 별도 프로필로 계산했다.2026년은 부분연도이므로 최종 후보표에만 포함하고,이후 성과 검증은 완결된2024·2025년으로 구분했다.

| 구분 | 규모 |
|---|---:|
| 전체 고유 마필 | {s['unique_horses']:,}두 |
| 경마장을 구분한 말 그룹 | {s['horse_venue_groups']:,}개 |
| 전체15출전 이상, 두 거리 이상 각각5회 이상 | {s['comparison_supported']:,}그룹 · 고유{s['supported_unique_horses']:,}두 |
| 위 조건을 충족하고 최근365일 내 관측 | {s['recent_supported']:,}그룹 |
| 비교 근거 부족 | {s['insufficient']:,}그룹 |

한 거리만 뛴 말은 그 거리의 성과를 알 수 있어도 다른 거리보다 적합하다고 판단할 수 없다. 거리별1~4회는 근거 표에는 보존하되 최종 비교 후보에서 제외했다. 총15회는5회 이상인 두 거리뿐 아니라 같은 지역의 모든 해당 거리 출전을 합친 수다. 초기의 ‘두 거리 각각5회’ 점검2,827개는 총15회 조건을 붙이기 전의 경마장별 말 그룹 수다.5회/15회는 이번 연구의 최소 표시 기준이며 정확성을 보장하는 횟수가 아니다. 최근 관측을 현역 등록 확인과 동일시하지 않는다.

개인 후보의1·2순위 차이는2,634그룹 중2,625개에서0.10 상대척도 미만이었다. 나머지9개가 통계적으로 확정된 적성을 갖는다는 뜻은 아니다.0.10은 가까운 후보를 함께 보여주기 위한 표시 기준이고 개인 신뢰구간을 계산한 결과가 아니다. 작은 표본과 강한 축소로 후보 차이가 작아질 수 있어 ‘거리 적성이 없다’고 해석하지 않는다.

## 실제 개인 표는 이렇게 읽는다

아래 사례는 관측기간 전체로 만든 최신 연구 스냅샷의 설명용 예시다. 당시 출전 전에 제공한 추천이나 앞으로의 승률이 아니다.

{chr(10).join(examples)}

태양으뜸은1200m42회와1400m6회 근거에서1200m의 조건부 점추정이 높았다.1800m는2회라 비교 후보에서 빠진다. 소리태풍은1800m가1순위지만1600m와의 차이가 표시 기준보다 작아1600~1800m를 함께 남긴다. 연속 범위의 모든 중간 거리를 실제 검증했다는 뜻은 아니다. 리치트리의1200m는3회라 전체 후보 표의1·2순위 비교에는 포함하지 않았다.

![개인 거리 후보의 근거](figures/individual_distance_examples.png)

[말별 전체 후보 CSV](outputs/horse_candidates.csv),[최근 관측·비교 가능 후보 CSV](outputs/recent_horse_candidates.csv),[거리별 횟수와 추정치 parquet](outputs/horse_distance_profiles.parquet)에 마명·마필ID·지역·거리·관측수·가까운 후보·마지막 관측일을 보존했다. 우승확률·공식rating·확정 적성 점수가 아니다.

## 이후 기록에서 실제 도움이 됐나

2018~2022년을 학습하고2023년3,119개 비교 출전에서 거리 편차 축소 강도3/10/30/100을 비교했다. 선택값은100으로, 개인 거리 차이를 상당히 보수적으로 반영하는 방식이었다.2024·2025년 평가 후 이 값을 다시 선택하지 않았다.

2024년은2018~2023년,2025년은2018~2024년까지만 학습했다. 주 평가집단은 학습12출전 이상·검증거리3회 이상·다른 거리3회 이상인 말이다. 신마나 미경험 거리까지 포함한 전체 결과와 지역별 결과는 [평가표](outputs/evaluation_metrics.csv)에 따로 남겼다. 이 표의 MAE는 낮을수록 좋은 상대척도 오차이고 ‘차이’는 거리 항 추가−제외다.

{chr(10).join(validation)}

합계6,180출전·1,022두의 주 평가에서 MAE는0.619480→0.619325로 약{improve:.3f}% 줄었지만,차이95%구간은0을 포함했다. 실제 초로 바꾼 평균 절대오차는0.851671→0.851450초로 약0.000221초 감소했다. 이는 **예측오차 감소량**이며 적정거리로 옮겼을 때 빨라지는 시간이 아니다. 거리 적성 항의 추가 예측 가치를 확정하지 못했다.2024년 부산 한 하위집단의 감소만 골라 전체 개선이라고 주장하지 않는다.

![이후 기록의 시간순 검증](figures/future_validation.png)

실제 검증 경주의 평균은 결과 평가에서 공통 경주 효과를 없애는 데만 사용했다. 예측값은 이전 학습 계수와 해당 출전의 알려진 조건으로 계산했고,현재 경주의 실제 기록·착순을 입력으로 넣지 않았다. 정상 완주자 선택 모집단에서의 상대 기록 검증이므로 실전 출전표 전원의 절대시간·우승확률을 검증한 것은 아니다. 원천 정보의 공개시각을 복원한 실시간 검증과도 구분한다.

## 과거 후보거리가 이후에도 가장 좋았나

과거 두 거리 이상에서 각각3회·전체12회 이상 근거가 있고,이후 후보거리와 다른 지원거리에서 각각2회 이상 실제 뛴 말만 비교했다. 각 비교 거리도 이후2회 이상인 경우로 제한했다. 이후 성과는 과거에 추정한 통제/말 기본 수준을 제외하고,같은 경주의 다른 정상 완주자 평균을 결과 평가 참조로 삼았다. 미래 경쟁마의 결과는 평가용이며 예측 입력이 아니다.

{chr(10).join(rep)}

성과 차이는 상대척도이고 높을수록 후보거리에서 좋았다는 뜻이다. 두 해 모두 평균 방향은 후보거리 쪽이지만 불확실성 구간이0을 포함했다.55.0%와49.6%를 높은 정확도라고 해석하지 않는다. 말마다 후보 수와 거리 선택이 달라 단순한50%와의 우열도 검정하지 않았다. 다음 출전거리 자체가 훈련·성장·상태·편성에 따라 선택되므로 거리 변경의 인과 개선이나 최적 출전 전략을 입증하지 않는다.

## 적용 범위와 다음 판단

현재 결과는 ‘말별 비교표를 만들 수 있다’는 근거이고 ‘모든 말의 적정거리를 맞혔다’는 근거는 아니다. 개인 편차는 관측기간 평균적 선호를 고정한 모형으로,성장·훈련·부상·주법 변화에 따라 달라지는 적성을 완전히 추적하지 못한다. 당시 rating·과거 성적을 맞춘 조건부 적성이며,그 조정에 포함되는 능력 변화까지 모두 독립적인 거리 적성으로 분해한 것이 아니다.

기록을 읽을 때는 **후보거리·가까운 대안·거리별 출전수·최근 관측일·판단 보류**를 함께 표시하는 것이 맞다. 최소 표본을 충족해도 개인 확정 신뢰구간과 이후 개선 근거가 없으면 단일 거리로 단정하지 않는다. 아직 뛰지 않은 거리나1900m 이상 장거리로 외삽하지 않는다. 현재 연구는 후보표를 보존한 상태이며 운영 평가표·DB·모델·웹사이트 배포에 반영하지 않았다.

## 검증과 재현

원문18파일에서148,126행의 말ID·날짜·거리·전체기록과 최신 관측 마명을 대조하고19개 입력 해시를 확인했다. 별도 희소 설계행렬·경주 평균 투영·LSMR 회귀로10개모형을 재계산해 CG 결과와 비교했다. 독립 검증{len(v['checks']):,}개 검사를 통과했으며 계수 최대오차는 [독립 계산표](outputs/independent_fit_checks.csv)에 있다. 학습기간의 결측 중앙값/평균/표준편차·거리 척도·과거 지원수·개인 후보·미래 현재결과 변조에 대한 예측 불변을 확인했다.

말 군집은 경마장을 옮긴 같은 말도 함께 묶고,실제 날짜 군집은 두 지역의 같은 달력일을 함께 묶었다. 말 단일·날짜 단일·이원 군집 중 대비분산 최대값과 t 구간을 썼다. 주검정은 두 완결연도를 합친 사전 지정 MAE 차이1개이며 다른 표는 민감도/탐색이다. 수치 일치가 거리 적성의 인과성이나 생리적 기전을 입증하지 않는다.

[계획](PLAN.md) · [출처와 모형](SOURCES.md) · [게시 요약](PUBLICATION.md) · [게시 데이터](outputs/publication_summary.json) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json) · [중앙 결론](../conclusions/27_HORSE_DISTANCE_APTITUDE.md).

루트에서 `OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261008_horse_distance_aptitude/run.py`,같은 경로의 `verify.py`, `render.py` 순서로 재현한다. `--resume`은 같은 연구의 저장된 학습 모형을 읽어 파생표만 다시 계산하는 옵션이다. 공유 목록의 `register.py`는 재현 분석에서 생략한다.
'''
def tidy(text):return re.sub(r'([가-힣])(?=[0-9])',r'\1 ',text)
(H/'README.md').write_text(tidy(report))
sources='''# 원천과 거리 적성 모형

2026-10-08. [원 모집단](../20261007_sex_ability_gap/outputs/population.parquet)151,074행 중1000~1800m148,126행을 읽기 전용으로 사용했다. 경주/말 중복과 이전 이력 날짜를 확인했다. 원시 식별자/원문 포인터/성별 분류는 기존 자료 그대로이며 성별 기준을 추가하지 않았다. [원 모집단 방법](../20261007_sex_ability_gap/SOURCES.md)과 [입력 감사](outputs/source_audit.json)를 따른다. 완료된 기존 말 평가표와 [설계](../20261007_horse_profile_spec_v1/README.md)는 참조만 했다.

원천 기간은 서울2018-01-06~2026-09-20,부산2018-01-05~2026-09-18이다. 정상 완주·구간 품질 모집단의 선택을 유지했다. 마지막 몇 달을 완결연도와 혼합해 검증하지 않았다.2026년 부분연도는 최종 스냅샷에만 포함했다. 원문18파일은 `20260929_calendar_api_v1/raw/race_execution_probe/{2018..2026}/meet_{1,3}.json.gz`이며 source_file/source_item_index로 매칭한다. [마명 원천 해시](outputs/name_source_hashes.json)·[시작 파일 목록](outputs/baseline_inventory.json)을 보존했다.

학습 y는 −(전체초×1000/거리)/(해당 학습기간 지역×거리의 경주 내 잔차 표준편차)다. 같은 경주의 평균을 제거하며,상대척도 값이 높을수록 빠르다. 단순1000m 환산 시간 자체를 거리적성으로 비교하지 않았다. 공식rating·우승확률·기존 함수율 보정의 새 버전이 아니다. 경주 고정효과가 공유 등급·날짜·정확 함수율 등 환경을 흡수한다. 기존 서울80%·부산90% 환산 자산을 수정하거나 새 거리 계수로 대체하지 않았다.

설계 X는 지역×거리별 부담중량/제곱,나이/제곱,rating/제곱,과거 전체/초반/입상 성과,출전수,공백과 각 결측표시,경마장별 말 기본 수준,중심화한 말×거리 편차다. 값의 결측 중앙값·평균·표준편차는 학습 기간만 사용한다. 말 기본 수준 penalty10,통제변수1을 고정하고 거리 편차3/10/30/100 중2023년 주집단 MAE로100을 선택했다. 이산 거리별 편차만 추정하며 미경험 거리의 최적값을 생성하지 않는다. 미경험 말/거리의 예측 추가 효과0은 사전 평균값이고 적성 차이가 실제0이라는 판단이 아니다.

목적함수는 경주 평균을 제거한 제곱오차+각 계수의 ridge 벌점이다. 말×거리 설계에서 해당 말의 학습거리 비중 평균을 빼 말별 거리편차 가중평균을0으로 만든다. CG 정규방정식과 별도 LSMR 최소제곱을 비교했고 상대허용오차와 gradient를 [학습 진단](outputs/fit_diagnostics.csv)에 남겼다. 저장 모형의json/npz에는 척도·결측처리·마필/거리 식별자·학습 종료일·계수가 있으며 원자료를 복제하지 않았다.

2018~2022학습→2023선택 후2018~2023학습→2024검증,2018~2024학습→2025검증으로 진행했다. 평가 경주 실측 평균은 평가 결과 기준에만 사용했다. 조정치·표본·기록은 [출전별 예측 parquet](outputs/eval2024_predictions.parquet)와 [다음 연도](outputs/eval2025_predictions.parquet),[집계](outputs/evaluation_metrics.csv)에 있다. 주집단은 학습12회/검증거리3회/다른 거리3회 이상이다. 말과 실제 날짜의 교차 의존·t 구간을 반영했다. 모형 학습 불확실성을 모두 재표집한 개인 신뢰구간은 제공하지 않는다.

최종 후보는 전체15회/두 거리 이상 각각5회 이상,가까운 후보 범위는 최상위 편차−0.10 이내라는 표시 규칙이다. 평균적 조건부 선호의 점추정이며 유의성 판정이 아니다. [개인 표](outputs/horse_candidates.csv)의 비교 불가 상태와 [이후 반복 탐색](outputs/2024_replication.csv)·[2025](outputs/2025_replication.csv)를 함께 읽는다. 통계적 검증과 거리 선택의 인과효과,실시간 공개시각 검증,운영 채택을 구분한다. 외부 최신 규칙/생리적 문헌을 근거로 사용하지 않았다.
'''
(H/'SOURCES.md').write_text(tidy(sources))
publication=f'''# 말별 적정거리 후보와 신뢰할 수 있는 범위

2026-10-08 · 서울·부산1000~1800m · 연구 후보

**말별로 잘 맞는 거리 후보를 계산할 수 있지만,한 거리로 확정하려면 근거가 더 필요하다.** 거리별 최고기록이나 승률만으로 고르지 않고,같은 경주·부담중량·연령·rating·과거 성적을 맞춘 뒤 말의 기본 수준과 거리별 추가 성과를 분리한다. 출전이 적은 거리의 우연한 좋은 기록은 축소해 반영한다.

정상148,126출전에서 전체15회·두 거리 각각5회 이상을 충족한2,634두의 임시 후보를 만들었다. 최근365일 내 관측된 비교 가능 그룹은760개다. 태양으뜸은1200m42회/1400m6회 근거에서1200m가 높았고,소리태풍은1800m가1순위지만1600m와 차이가 작아 두 거리를 함께 표시했다. 둘 다 확정 적성이나 출전 권고는 아니다.

과거로 학습한2024·2025년6,180출전·1,022두 검증에서는 거리 항을 추가한 MAE 개선이 약{improve:.3f}%였고95%구간이0을 포함했다. 이후 실제 두 거리 이상에서 반복한 말의 후보 일치율은2024년55.0%,2025년49.6%였다. 후보거리의 평균 성과 우위도 불확실했다. 계산 가능한 표와 확정된 예측 효용을 구분한다.

거리 후보·가까운 대안·거리별 출전수·마지막 관측일·판단 보류를 함께 제공한다. 한 거리만 뛴 말과 미경험 거리는 적정거리 미확정이다. 관측기간 평균적 선호이며 성장·훈련 등으로 적성이 변할 수 있다.1900m 이상 장거리,생리적 최적값,거리 변경의 인과 개선을 확인하지 않았다. DB·운영 모델·기존 평가표·웹 배포는 변경하지 않았다.

자료 종료: 서울2026-09-20·부산2026-09-18. [말별 후보표](outputs/horse_candidates.csv) · [최근 후보표](outputs/recent_horse_candidates.csv) · [전체 보고서](README.md) · [출처](SOURCES.md) · [검증](outputs/verification.json).
'''
(H/'PUBLICATION.md').write_text(tidy(publication))
records=[]
for r in main.itertuples():records.append(dict(window=r.window,n=r.n,baseline_mae=r.baseline_mae,distance_mae=r.distance_mae,difference=r.estimate,lower=r.lower,upper=r.upper))
data=dict(title='말별 적정거리 후보와 검증',date='2026-10-08',eligible_starts=148126,comparison_supported_horses=s['supported_unique_horses'],recent_supported_groups=s['recent_supported'],lambda_distance=100,validation=records,relative_mae_improvement_percent=improve,replication=s['replication'],conditional_candidates=True,individual_optimum_confirmed=False,individual_confidence_intervals=False,causal=False,operational=False,real_time_publication_timestamps_reconstructed=False,data_end=s['final_asof_by_meet']);(O/'publication_summary.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print('Report, publication and two figures written')
