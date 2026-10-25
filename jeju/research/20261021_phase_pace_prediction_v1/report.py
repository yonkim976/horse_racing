"""Readable Korean report and standalone scientific comparison figure."""
import json,os
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/jeju_phase_pace_matplotlib')
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import *

LABEL={'s1f':'초반 S1F','c3':'중반 3코너','c4':'종반 진입 4코너','g1f':'결승 전 200m',
       'middle_advance':'초반→3코너 2계단 전진','late_advance':'4코너→G1F 2계단 전진',
       'last200_recovery':'마지막 200m 2계단 회복','front_fade':'초반 선두 묶음 이후 후퇴'}
def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,r))+' |' for r in rows])
def pct(x):return f'{100*x:.1f}%'
def pick(df,**kwargs):
    for k,v in kwargs.items():df=df[df[k].eq(v)]
    assert len(df)==1,(kwargs,len(df));return df.iloc[0]

def main():
    assert json.loads((OUT/'verification.json').read_text())['status']=='passed'
    m=pd.read_csv(OUT/'metrics.csv',dtype={'distance':str});c=pd.read_csv(OUT/'candidate_metrics.csv',dtype={'distance':str})
    b=pd.read_csv(OUT/'binary_metrics.csv');contr=pd.read_csv(OUT/'paired_comparisons.csv');count=pd.read_csv(OUT/'count_metrics.csv')
    support=pd.read_csv(OUT/'distance_support.csv');coverage=pd.read_csv(OUT/'target_coverage.csv')
    build=json.loads((OUT/'build_receipt.json').read_text());verify=json.loads((OUT/'verification.json').read_text())
    rows=[]
    for t in POINTS:
        h=pick(m,task=t,model='H',period='all_eval',distance='all');p=pick(m,task=t,model='P',period='all_eval',distance='all');f=pick(m,task=t,model='F',period='all_eval',distance='all')
        hc=pick(c,task=t,model='H',period='all_eval',distance='all');pc=pick(c,task=t,model='P',period='all_eval',distance='all');fc=pick(c,task=t,model='F',period='all_eval',distance='all')
        rows.append([LABEL[t],f'{int(f.rows):,}',f'{int(f.races):,}',pct(h.accuracy),pct(f.accuracy),f'{h.brier:.4f} → {p.brier:.4f} → {f.brier:.4f}',f'{pct(hc.hit_rate)} → {pct(pc.hit_rate)} → {pct(fc.hit_rate)}'])
    main_table=table(['구간','정답 출전','경주','단순 빈도 정확도','F 정확도','Brier H→P→F','최고 후보 첫 묶음 H→P→F'],rows)
    rows=[]
    for year in ['2024','2025','2026']:
        for t in POINTS:
            h=pick(m,task=t,model='H',period=year,distance='all');f=pick(m,task=t,model='F',period=year,distance='all')
            fc=pick(c,task=t,model='F',period=year,distance='all')
            rows.append([year,LABEL[t],f'{int(f.races):,}',f'{pct(h.accuracy)} → {pct(f.accuracy)}',f'{h.brier:.4f} → {f.brier:.4f}',f'{int(fc.hits)}/{int(fc.races)}={pct(fc.hit_rate)}',f'[{pct(fc.date_low)}, {pct(fc.date_high)}]'])
    annual_table=table(['연도','구간','경주','정확도 H→F','Brier H→F','F 첫 묶음 최고 후보','후보 포함률 날짜 95%'],rows)
    rows=[]
    for t in POINTS:
        for ref in ['H','P']:
            r=pick(contr,task=t,comparison='F-'+ref,period='all_eval')
            rows.append([LABEL[t],r.comparison,f'{r.estimate:+.5f}',f'[{r.low:+.5f}, {r.high:+.5f}]',f'{r.bh_q_primary8:.4g}'])
    contrast_table=table(['구간','비교','Brier 차이','날짜 95%','8비교 BH q'],rows)
    rows=[]
    for dist in DISTANCES:
        vals=[];ns=[]
        for t in POINTS:
            z=c[(c.task==t)&c.model.eq('F')&c.period.eq('2026')&c.distance.eq(str(dist))]
            gate=pick(support,year=2026,task=t,distance=dist)
            if t=='c3' and dist==800:vals.append('S1F와 같은 지점');continue
            if z.empty:vals.append('무표본');continue
            r=z.iloc[0];star='' if gate.supported else ' *'
            vals.append(f'{int(r.hits)}/{int(r.races)} {pct(r.hit_rate)}{star}')
            ns.append(int(r.races))
        rows.append([f'{dist}m']+vals)
    distance_table=table(['거리','S1F 후보 포함','3C 후보 포함','4C 후보 포함','G1F 후보 포함'],rows)
    rows=[]
    for t in EVENTS:
        for period in ['all_eval','2026']:
            h=pick(b,task=t,model='H',period=period);f=pick(b,task=t,model='F',period=period)
            rows.append([LABEL[t],period,f'{int(f.rows):,}',pct(f.prevalence),f'{h.binary_brier:.4f} → {f.binary_brier:.4f}',f'{f.auc:.3f}',f'{pct(f.low20_rate)} / {pct(f.high20_rate)}'])
    binary_table=table(['사건','기간','정답 출전','실제 발생','이진 Brier H→F','F AUC','F 확률 하위/상위20% 발생'],rows)
    rows=[]
    for period in ['all_eval','2024','2025','2026']:
        for name in ['H','I','J']:
            r=pick(count,model=name,period=period)
            rows.append([period,name,f'{int(r.races):,}',pct(r.accuracy),f'{r.brier:.4f}',f'{r.nll:.4f}',f'{r.count_mae:.3f}두'])
    count_table=table(['기간','두수 모형','경주','1/2/3+ 정확도','Brier','로그손실','실제 두수 MAE'],rows)
    rows=[]
    for t in POINTS:
        r=pick(c,task=t,model='F',period='2026',distance='all')
        rows.append([LABEL[t],f'{int(r.races):,}',f'{int(r.hits):,}',f'{int(r.misses):,}',f'{int(r.miss_second)} ({pct(r.miss_second_rate)})',f'{int(r.miss_behind)} ({pct(1-r.miss_second_rate)})'])
    failure_table=table(['구간','정답 경주','첫 묶음 적중','실패','실패 중 둘째 묶음','실패 중 셋째 이후'],rows)
    example=pd.read_csv(OUT/'example_last_race.csv');er=example.race_id.iloc[0]
    rows=[]
    for r in example.sort_values('horse_number').itertuples():
        rows.append([r.horse_number,r.horse_name,pct(r.s1f_p0),pct(r.c3_p0),pct(r.c4_p0),pct(r.g1f_p0),pct(r.last200_recovery_p1),
                     '/'.join(str(int(getattr(r,'y_'+t))) if pd.notna(getattr(r,'y_'+t)) else '?' for t in POINTS)])
    example_table=table(['번호','말','S1F 첫 묶음','3C 첫 묶음','4C 첫 묶음','G1F 첫 묶음','막판 2계단 회복','실제 묶음 0/1/2'],rows)
    primary=contr[contr.primary]
    supported=int(((primary.high<0)&(primary.bh_q_primary8<.05)).sum())
    s1=pick(c,task='s1f',model='F',period='2026',distance='all');s1h=pick(c,task='s1f',model='H',period='2026',distance='all')
    s1p=pick(c,task='s1f',model='P',period='2026',distance='all')
    count_h=pick(count,model='H',period='2026');count_j=pick(count,model='J',period='2026')
    text=f'''# 제주 초반 중반 종반 전개 예측 결과

2026-10-21 연구 후보. **2026년 초반 최고 선두 후보가 실제 첫 묶음에 들어간 비율은 단순 과거빈도 {pct(s1h.hit_rate)}에서 F {pct(s1.hit_rate)}로 바뀌었다.** 초반·3코너·4코너·결승 전 200m 위치 확률과 구간별 회복·후퇴 확률을 학습했다. 아래 정확도는 최종 우승·입상 적중률이 아니다.

## 자료와 시점

전체 명단은 {build['start']}~{build['end']}의 **{build['races']:,}경주·{build['rows']:,}출전·{build['horses']:,}두**다. 400m와 사용자 제외 말을 제외한 현재 8거리이며 2026년은 9월19일까지 부분연도다. 정상완주 {build['normal_rows']:,}출전과 실격·주행중지 {build['dnf_dq_rows']}출전을 명단에 보존했다. 지점별 통과조가 전두수와 일치하고 품질 상태가 허용되는 경주에만 해당 위치 정답을 부여했다. 미관측을 후미나 사건 없음으로 채우지 않았다. 이전 5,200경주 분석은 정상완주 완전편성 조건이었으므로 이번 분모와 직접 혼합하지 않는다.

예측 전에 알 수 있는 과거 이력은 T−2까지 730일 내 최근 5/10개 실제 출전 슬롯, 같은 정확거리 최근 10슬롯이다. 과거 결측을 건너뛰어 10개 관측을 채우지 않는다. 현재 경주의 구간·착순·함수율·마체중·rating·기수/조교사 배정·배당은 새 모형에 넣지 않았다. 현재 거리·출발번호·명단은 사후 확정 자료를 사전 명단의 대리값으로 썼으므로 당시 공표시각까지 확인한 실전 발행 실적은 아니다.

2024년은 2023-12-30까지, 2025년은 2024-12-30까지, 2026년은 2025-12-30까지 학습했다. 평가연도 튜닝·조기종료는 하지 않았다. 이미 반복 사용한 과거 기간의 시간순 후향 개발 비교이며 독립 미래검증으로 부르지 않는다.

## 구간과 모델의 의미

| 구간 | 관측 기준 | 해석 |
| --- | --- | --- |
| 초반 | S1F | 기본 출발 후 200m, 1110/1610m는 210m |
| 중반 대용 | 3코너 | 거리의 정확한 정중앙이 아니다. 800m는 S1F와 같은 지점이므로 별도 평가 제외 |
| 종반 진입 | 4코너 | 3코너 이후 위치 변화와 함께 확인 |
| 종반 위치 | G1F | 결승 전 200m 지점의 위치 |
| 마지막 구간 | G1F→결승 | 공식 순위 2계단 이상 회복 여부 |

각 지점의 3종은 **첫 묶음 / 둘째 묶음 / 셋째 이후**다. 첫 묶음은 여러 말일 수 있다. 둘째 묶음을 전통적인 선입이나 내측 2선으로, 뒤쪽을 추입형으로 자동 해석하지 않는다. 괄호 내부의 가로 배열을 개별 착순으로 만들지 않았다. 제주 G3F 시간으로 통과조를 만들지 않았고 1300m는 출발→2C→S1F 순서를 유지했다.

H는 과거 위치/사건 빈도에 학습기간 기준빈도 3회 강도를 더한 단순 기준이다. P는 자기 위치·구간·성적·이동 이력과 거리·월·두수를 사용한다. F는 P에 출발번호, 편성 내 과거 초반·종반 우위, 자기보다 낮고 높은 번호의 앞선 후보 구성을 더했다. P {build['P_columns']}열, F {build['F_columns']}열이며 평균·횟수·범위 변환을 포함한 열 수이지 독립 원천의 수가 아니다. 기수·조교사 성향과 ID는 이번 연구에서 제외했다. 원초 단위 시간은 같은 정확거리 이력에서만 사용해 200m와 210m를 섞지 않았다.

LightGBM 180나무·15잎·학습률0.04·최소잎100·L2=10을 고정하고 경주별 동일가중으로 학습했다. 말별 세 확률의 합은1이며 경주 전체 선두 확률의 합이1인 것은 아니다. 중·종반 모델은 경주 전에 각 지점의 주변확률을 직접 예측한다. 실제 현재 초반을 중반 입력으로 넘기지 않는다. 네 시점 전체의 공동 경로나 진로를 생성하는 모델은 아니다.

## 전체 시간순 평가

평가 기간은 2024~2026-09-19다. Brier는 세 확률과 실제 범주의 제곱오차 합을 경주별 평균한 값이며 낮을수록 좋다. 정확도는 가장 높은 확률의 범주를 맞힌 비율의 경주별 평균이다. 뒤쪽 범주가 다수이므로 정확도만으로 선행 예측력을 판단하지 않고, 경주마다 첫 묶음 확률 최고1두의 실제 포함률을 함께 본다.

{main_table}

## 연도별 재현

{annual_table}

후보 포함률의 분모는 말 출전수가 아닌 전두수 관측 경주수다. 최고 후보가 첫 묶음에 들어왔다는 의미이며 첫 묶음 전체 명단·단독 선두·최종 입상을 맞혔다는 뜻은 아니다.

## 상대마와 출발번호의 추가 정보

{contrast_table}

차이는 F−기준으로 음수가 개선이다. 주 비교 8개 중 95%구간이 모두 음수이며 BH q<0.05인 대비는 {supported}개였다. 날짜 군집 bootstrap 2,000회 구간이며 개별 말의 예측 보장 범위가 아니다. F−P는 상대마·출발번호 묶음의 추가 가치이고 게이트만의 인과효과가 아니다. 거리별 수치를 본 뒤 입력이나 학습 설정을 바꾸지 않았다.

다만 **확률분포의 오차 개선과 최고 선두 후보 교체의 개선은 다르다.** 2026년 초반 최고 후보는 P {int(s1p.hits)}/{int(s1p.races)}={pct(s1p.hit_rate)}, F {int(s1.hits)}/{int(s1.races)}={pct(s1.hit_rate)}로 F가 1경주 적었다. 4C·G1F도 같은 해 최고 후보 포함률은 P가 F보다 높았다. 상대 편성을 더하면 모든 목표에서 후보 선정까지 개선된다고 주장하지 않는다.

## 2026년 거리별 첫 묶음 후보

{distance_table}

*는 해당 지점의 학습50경주·평가30경주·평가15일 중 하나라도 부족한 경우다. 1300·1400·1610m, 최근800m의 큰 비율은 작은 표본에 영향을 받는다. 날짜 95%구간과 전 기간/연도별 수치는 [후보 원표](outputs/candidate_metrics.csv), [지원 원표](outputs/distance_support.csv)에 보존했다. 800m의 별도 중반 성능은 만들지 않았다.

## 선두 두수와 공동분포

{count_table}

H는 이전 학습기간 선두두수 빈도다. I는 말별 F 선두확률을 독립 베르누이로 두고 공집합을 제외한 부분집합 분포다. J는 I를 별도 경주 두수모형의 1/2/3+ 확률에 맞춰 재가중한다. 3+ 안의 세부두수는 I의 조건부 분포를 유지한다. 말별 소속확률 합=예상두수, 단독소속확률 합=선두1두 확률을 만족한다.

J는 두수범주 확률을 맞추는 구조이며 후보의 순서는 I와 같다. 두수 예측 개선을 최고 선행 후보 선정 개선으로 읽지 않는다. 첫 묶음 두수는 관측된 경합 강도나 말들이 나란히 달리는 정도가 아니다. 독립 가정과 두수별 재가중은 실제 마필 간 전략 상관관계를 모두 설명하지 못한다. I/J와 별도 F 두수모형의 전체 원표는 [두수 평가](outputs/count_metrics.csv)에 있다.

**2026년 선두두수는 단순 빈도보다 좋아지지 않았다.** 1/2/3+ 정확도는 H {pct(count_h.accuracy)} 대 J {pct(count_j.accuracy)}, Brier는 {count_h.brier:.4f} 대 {count_j.brier:.4f}, 실제두수 MAE는 {count_h.count_mae:.3f}두 대 {count_j.count_mae:.3f}두였다. 선두두수·단독 선행의 정교한 공동예측을 검증된 기능으로 채택할 근거가 부족하다.

## 중반 전진과 종반 회복 후퇴

{binary_table}

전진·회복 사건은 공식 통과순위가 2계단 이상 좋아진 경우다. 앞선 후퇴는 S1F 첫 묶음 소속이고 최종순위가 당시 묶음의 최소순위보다 3계단 이상 뒤인 복합 사건이다. 모든 유효 정답 출전을 대상으로 사전 확률을 예측했으며 현재 실제 선두/후미인 말만 사전 선별하지 않았다. 미완주나 지점 보류로 이동을 알 수 없는 경우는 해당 정답을 비워 두었다. 800m의 S1F→3C는 같은 지점이므로 제외했다.

이 표의 이진 Brier는 말 출전 기준 (확률−사건)의 제곱평균으로 세 범주 Brier와 척도가 다르다. AUC는 사건이 일어나는 말을 더 높게 배열하는 능력이다. 상위20% 실제 발생률은 그 집단의 예측 확률 자체와 다르다. 뒤쪽 위치·빠른 G1F·실제 순위회복·최종입상은 각각 다른 관측이다. 순위 회복이 육체적 체력·추입 의도·최적 작전의 직접 증거는 아니다. [이진 원표](outputs/binary_metrics.csv)와 [교정표](outputs/calibration.csv)를 함께 본다.

## 2026년 최고 선두 후보가 빗나간 위치

{failure_table}

둘째/그 뒤의 분모는 전체 경주가 아니라 해당 지점의 첫 묶음 후보가 빗나간 경주수다. 둘째 묶음을 전통적인 선입으로 바꾸어 표시하지 않는다.

## 마지막 경주의 회고 사례

결과에 관계없이 마지막 날짜의 마지막 경주 **{er}**를 선택했다. 표는 각 지점의 첫 묶음 확률이며 둘째/셋째 이후를 포함한 전체 확률은 [사례 원표](outputs/example_last_race.csv)에 있다. 실제 묶음 0=첫째,1=둘째,2=셋째 이후다.

{example_table}

표의 네 확률을 곱해 경로 전체의 확률로 해석하지 않는다. 실제 결과 열은 사후 대조에만 썼다.

## 저장과 검증

{verify['models_reinferred']}개 모델을 텍스트 형식으로 저장하고 전부 다시 추론해 최대 오차 {verify['max_reinference_error']:.3g}를 확인했다. 독립 파서로 지점별 묶음을 재구성하고 모든 이력창·평균·유효수·상대 제외를 검산했다. {verify['joint_races_independently_enumerated']:,}경주의 J 부분집합을 별도 곱셈식으로 전수열거해 최대 오차 {verify['max_joint_error']:.3g}를 확인했다. 현재/미래 사후값을 바꾼 이력 재집계와 8개 주 비교 bootstrap 재계산을 통과했다.

첫 원천 대조는 거리800.0과800을 문자열로 비교해 학습 전에 중단됐고 숫자 동등성 비교로 바로잡았다. 첫 학습 호출도 읽기 전용 가중치 배열의 제자리 나눗셈에서 모델 적합 전에 중단돼 복사본을 사용하도록 수정했다. 지표 계산 후 사례 추출에서는 고정 메타열의 누락된 import를 보완하고 동일 지표를 재계산했다. 원천이나 목표·학습 설정은 바꾸지 않았으며 [원천 대조 기록](outputs/initial_source_check_failure.json), [초기 학습 기록](failed_attempt01/failure.json), [사례 추출 기록](failed_attempt02/failure.json)을 보존했다.

연구 후보는 저장했지만 운영 HY_R_FORM·등록부·웹·DB는 변경하지 않았다. 이 전개 예측이 최종 우승·입상 예측을 개선하는지는 이번에 검증하지 않았다. 더러브렛 선행 후보 포함률과는 자료·거리·정답·평가기간이 달라 숫자만으로 모델 우열을 비교하지 않는다.

[사전 계획](PLAN.md) · [입력 계약](outputs/feature_contract.json) · [모델별 학습 절단](outputs/fit_audit.json) · [전체 지표](outputs/metrics.csv) · [전 출전 예측](outputs/predictions.parquet) · [초반 공동분포](outputs/joint_early_predictions.parquet) · [입력 검증](outputs/build_verification.json) · [모델 검증](outputs/verification.json) · [원천](outputs/source_manifest.json)

![구간별 위치 예측 비교](outputs/phase_prediction_comparison.png)
'''
    (HERE/'README.md').write_text(text)
    decision={'status':'phase_pace_research_candidate_completed','period_start':build['start'],'period_end':build['end'],
        'roster_races':build['races'],'roster_rows':build['rows'],'primary_comparisons_supported':supported,
        'early_2026_H_hit':float(s1h.hit_rate),'early_2026_F_hit':float(s1.hit_rate),
        'early_2026_P_hit':float(s1p.hit_rate),'leader_count_2026_better_than_frequency':False,
        'research_interpretation':'F probability distributions improve Brier; highest-candidate gain over P is not consistent; leader-count J unsupported',
        'model_count':verify['models_reinferred'],'primary_points':POINTS,'800m_c3_same_as_s1f':True,
        'production_changed':False,'final_finish_model_increment_tested':False,'independent_future_validation':False}
    save(HERE/'decision.json',decision)
    fig,axes=plt.subplots(1,3,figsize=(14,4.5),layout='constrained')
    colors={'H':'#9ca3af','P':'#6ca4cd','F':'#164e75'};labels=['S1F','3C (except 800m)','4C','G1F'];x=np.arange(4)
    for j,name in enumerate(['H','P','F']):
        vals=[pick(m,task=t,model=name,period='all_eval',distance='all').brier for t in POINTS]
        axes[0].bar(x+(j-1)*.23,vals,.23,label=name,color=colors[name])
    axes[0].set_xticks(x,labels,rotation=15);axes[0].set_title('Position probability error');axes[0].set_ylabel('3-class Brier (lower is better)');axes[0].legend()
    for name in ['H','P','F']:
        vals=[100*pick(c,task='s1f',model=name,period=y,distance='all').hit_rate for y in ['2024','2025','2026']]
        axes[1].plot([2024,2025,2026],vals,'o-',label=name,color=colors[name])
    axes[1].set_title('Highest-probability S1F candidate');axes[1].set_ylabel('In actual first pack (%)');axes[1].set_xticks([2024,2025,2026]);axes[1].legend();axes[1].grid(alpha=.2)
    for name in ['H','I','J']:
        vals=[pick(count,model=name,period=y).brier for y in ['2024','2025','2026']]
        axes[2].plot([2024,2025,2026],vals,'o-',label=name)
    axes[2].set_title('First-pack count: 1 / 2 / 3+');axes[2].set_ylabel('Count Brier (lower is better)');axes[2].set_xticks([2024,2025,2026]);axes[2].legend();axes[2].grid(alpha=.2)
    fig.suptitle('Jeju phase prediction | retrospective 2024–2026-09-19',fontsize=13)
    fig.savefig(OUT/'phase_prediction_comparison.png',dpi=160);plt.close(fig)
    print('Report and decision saved',flush=True)

if __name__=='__main__':main()
