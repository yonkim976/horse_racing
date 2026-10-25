"""Research report, publication data and standalone figures from saved results."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE=Path(__file__).resolve().parent
OUT=HERE/'outputs'
font_manager.fontManager.addfont('/System/Library/Fonts/AppleSDGothicNeo.ttc')
plt.rcParams.update({'font.family':['Apple SD Gothic Neo','DejaVu Sans'],'axes.unicode_minus':False,'figure.dpi':160,'font.size':11,
                     'axes.spines.top':False,'axes.spines.right':False,'savefig.facecolor':'white'})
C=pd.read_csv(OUT/'contrasts.csv')
S=pd.read_csv(OUT/'supplement_contrasts.csv')
D=pd.read_parquet(OUT/'population.parquet')
A=json.loads((OUT/'source_audit.json').read_text())


def md(df):
    vals=df.fillna('—').astype(str)
    lines=['| '+' | '.join(df.columns)+' |','| '+' | '.join(['---']*len(df.columns))+' |']
    lines+=['| '+' | '.join(row)+' |' for row in vals.to_numpy()]
    return '\n'.join(lines)


def est(row):
    if row is None or not np.isfinite(row.difference):return '—'
    if row.supported:return f'{row.difference:+.2f} [{row.lower:+.2f}, {row.upper:+.2f}]'
    return f'{row.difference:+.2f} 잠정'


def choose(frame=C,**kwargs):
    mask=pd.Series(True,index=frame.index)
    for col,v in kwargs.items():mask &= frame[col].eq(v)
    return frame[mask]


def get(frame=C,**kwargs):
    q=choose(frame,**kwargs)
    return q.iloc[0] if len(q) else None


def stage_table(target='암',reference='수'):
    rows=[]
    for (meet,dist),g in choose(scope='distance',part='finish',target=target,reference=reference).groupby(['meet','distance_m']):
        row={'지역':meet,'m':dist}
        for spec,label in [('raw','원시'),('context','연령·환경'),('grade','등급 추가'),('load_body','중량·체중 추가'),('full','rating·이력 추가')]:
            z=g[g.specification.eq(spec)]
            row[label]=est(z.iloc[0]) if len(z) else '—'
        f=g[g.specification.eq('full')].iloc[0]
        row['등급 공통n']=int(f.common_n);row['제외%']=f'{100*f.excluded_fraction:.1f}'
        rows.append(row)
    return pd.DataFrame(rows)


def generic_table(q,fields):
    rows=[]
    labels={'race':'동일 경주만','race_age':'연령 추가','race_load_body':'연령·중량·체중','race_full':'rating·이력 추가',
            'early':'출발200m','middle1':'중간1','middle2':'후반400m','late':'마지막200m','finish':'전체',
            'last600':'막판600m(겹침)','last400':'관측 막판400m','early_relative_pct':'초반 상대속도','late_relative_pct':'막판 상대속도',
            'top3':'3위 이내','win':'우승','age':'연령','grade':'등급','jan_aug':'공통1~8월','complete_years':'완결연도','near_complete':'가까운 완결연도'}
    for r in q.itertuples():
        row={label:labels.get(getattr(r,name),getattr(r,name)) for name,label in fields}
        row['차이 [95%구간]']=est(r);row['공통n']=int(r.common_n)
        rows.append(row)
    return md(pd.DataFrame(rows))


def figures():
    fig,axes=plt.subplots(1,2,figsize=(13,6.5),sharex=True)
    for ax,meet in zip(axes,['서울','부산']):
        q=choose(scope='distance',part='finish',target='암',reference='수',specification='full',meet=meet)
        q=q[q.supported].sort_values('distance_m')
        for j,(t,color,offset) in enumerate([('암','#b34466',-.13),('거','#187d89',.13)]):
            z=choose(scope='distance',part='finish',target=t,reference='수',specification='full',meet=meet).set_index('distance_m').reindex(q.distance_m)
            y=np.arange(len(q))+offset
            ax.errorbar(z.difference,y,xerr=[z.difference-z.lower,z.upper-z.difference],fmt='o',capsize=3,color=color,label=t+'−수')
        ax.axvline(0,color='#777777',lw=1);ax.set_yticks(np.arange(len(q)),[f'{int(v)}m' for v in q.distance_m]);ax.invert_yaxis()
        ax.set_title(meet);ax.set_xlabel('전체시간 차이(초) · 양수는 수말보다 느림');ax.grid(axis='x',alpha=.2);ax.legend(loc='best')
    fig.suptitle('조건·중량·마체중·rating·과거 성적을 고려한 기록 차이',fontsize=17)
    fig.text(.5,.01,'점별95%구간 · 같은 연도/월/연령/등급/정확 함수율 · 관찰된 공통 출전 집단',ha='center',fontsize=10)
    fig.tight_layout(rect=[0,.04,1,.93]);fig.savefig(OUT/'controlled_time_gaps.png');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.9),sharey=True)
    specs=['raw_on_grade_common','context_on_grade_common','grade','load_body','full']
    labels=['원시\n공통 표본','연령·환경','등급 추가','중량·체중\n추가','rating·이력\n추가']
    for ax,meet in zip(axes,['서울','부산']):
        z=[get(scope='distance',meet=meet,distance_m=1200,target='암',reference='수',part='finish',specification=x) for x in specs]
        diff=np.array([x.difference for x in z]);low=np.array([x.lower for x in z]);high=np.array([x.upper for x in z])
        ax.errorbar(range(5),diff,yerr=[diff-low,high-diff],color='#b34466',fmt='o-',capsize=4,lw=2)
        ax.set_xticks(range(5),labels);ax.axhline(0,color='#777777',lw=1);ax.set_title(f'{meet}1200m · 동일 {z[0].common_n:,}행');ax.grid(axis='y',alpha=.2)
        for i,v in enumerate(diff):ax.annotate(f'{v:+.2f}',(i,v),xytext=(0,12),textcoords='offset points',ha='center')
    axes[0].set_ylabel('암말−수말 전체시간(초)')
    fig.suptitle('같은 표본에서도 통제 수준에 따라 질문과 차이가 달라진다',fontsize=16)
    fig.text(.5,.01,'순차 통제는 원인 분해가 아니다 · 모든 단계가 같은 등급 공통 표본 · 점별95%구간',ha='center',fontsize=10)
    fig.tight_layout(rect=[0,.05,1,.93]);fig.savefig(OUT/'same_sample_adjustment_stages.png');plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(12,8.3),sharey=True)
    for ax,(meet,dist) in zip(axes.flat,[('서울',1200),('부산',1200),('서울',1400),('부산',1400)]):
        q=choose(scope='distance',meet=meet,distance_m=dist,target='암',reference='수',specification='full').set_index('part').loc[['early','middle1','middle2','late']]
        ax.bar(range(4),q.difference,color=['#187d89' if x<0 else '#b34466' for x in q.difference],alpha=.85)
        ax.errorbar(range(4),q.difference,yerr=[q.difference-q.lower,q.upper-q.difference],fmt='none',ecolor='#333333',capsize=4)
        ax.axhline(0,color='#777777',lw=1);ax.set_xticks(range(4),['출발200m',f'중간{dist-800}m','후반400m','마지막200m']);ax.set_title(f'{meet}{dist}m');ax.grid(axis='y',alpha=.2)
    for ax in axes[:,0]:ax.set_ylabel('암말−수말 시간(초)')
    fig.suptitle('독립 구간의 차이: 전체시간 차이가 초반부터 일정하게 쌓이지 않는다',fontsize=16)
    fig.text(.5,.015,'전체 통제 · 점별95%구간 · 후반400m는 마지막600→200m 구간이며 서울 미계측 마지막400m가 아니다',ha='center',fontsize=10)
    fig.tight_layout(rect=[0,.05,1,.94]);fig.savefig(OUT/'independent_section_gaps.png');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,5.8),sharex=True)
    for ax,meet in zip(axes,['서울','부산']):
        q=choose(scope='era',meet=meet,target='암',reference='수',part='finish',contrast_kind='gap_change',window='jan_aug',specification='full')
        q=q[q.supported].sort_values('distance_m')
        ax.errorbar(q.difference,range(len(q)),xerr=[q.difference-q.lower,q.upper-q.difference],fmt='o',capsize=4,color='#7856a0')
        ax.set_yticks(range(len(q)),[f'{int(v)}m' for v in q.distance_m]);ax.invert_yaxis();ax.axvline(0,color='#777777');ax.grid(axis='x',alpha=.2)
        ax.set_title(meet);ax.set_xlabel('최근−과거의 암말−수말 격차 변화(초)')
    fig.suptitle('최근 격차의 일관된 확대·축소는 확인하기 어렵다',fontsize=16)
    fig.text(.5,.015,'각 연도1~8월 · 2018~2023 대2024~2026 · 전체 통제 · 점별95%구간 · 비교 불충분 거리는 제외',ha='center',fontsize=10)
    fig.tight_layout(rect=[0,.05,1,.93]);fig.savefig(OUT/'recent_gap_changes.png');plt.close(fig)


def main():
    figures()
    desc=pd.read_csv(OUT/'observed_distributions.csv')
    # Preserve human-readable distributions for focal distances.
    ds=desc[desc.scope.eq('distance')&desc.part.eq('finish')&desc.distance_m.isin([1200,1800])]
    dt=ds[['meet','distance_m','sex','n','mean','median','p20','p80']].copy()
    dt.columns=['지역','m','분류','n','평균초','중앙초','빠른20% 경계','느린20% 경계']
    for col in dt.columns[4:]:dt[col]=dt[col].map(lambda x:f'{x:.2f}')
    full=choose(scope='distance',part='finish',specification='full',target='암',reference='수')
    focal=full[full.distance_m.isin([1200,1300,1400,1600,1700,1800])]
    ft=generic_table(focal,[('meet','지역'),('distance_m','m')])
    sec=choose(scope='distance',target='암',reference='수',specification='full')
    sec=sec[sec.distance_m.eq(1200)&sec.part.isin(['early','middle1','middle2','late','finish','last600'])]
    st=generic_table(sec,[('meet','지역'),('part','구간')])
    age=choose(scope='age',target='암',reference='수',specification='full')
    ag=generic_table(age,[('meet','지역'),('subgroup','연령')])
    rate=choose(scope='same_race',part='top3',target='암',reference='수')
    rate=rate[rate.distance_m.isin([1200,1400,1700,1800])&rate.specification.isin(['race','race_load_body','race_full'])]
    rt=generic_table(rate,[('meet','지역'),('distance_m','m'),('specification','통제')])
    sel=pd.read_parquet(OUT/'selection_ledger.parquet').groupby('sex_raw').selected.agg(['size','sum','mean']).reset_index()
    sel['제외율%']=(100*(1-sel['mean'])).map(lambda x:f'{x:.2f}')
    sel=sel.rename(columns={'sex_raw':'분류','size':'감사 모집단','sum':'최종 모집단'})[['분류','감사 모집단','최종 모집단','제외율%']]
    recent=choose(scope='era',specification='full',window='jan_aug',contrast_kind='gap_change')
    recent_supported=recent[recent.supported]
    assert not ((recent_supported.lower>0)|(recent_supported.upper<0)).any()
    report=f'''# 암말·수말·거세마의 기록과 경기력 차이

2026-10-07 · 관찰 연구 완료 · 신규 성별 보정/성별 전용 기준표 미채택 · 운영 반영 없음.

**관찰된 출전 집단에서는 암말의 전체시간이 수말보다 느리고, 같은 경주 내 우승·3위 이내 성과도 낮은 방향이 나타났다. 다만 등급·중량·체중·기존 성적을 맞추면 기록 차이가 크게 작아진다. 수말과 거세마의 차이는 대체로 작고 방향이 일정하지 않다. 이를 생물학적·인과적 능력 차이로 읽을 수 없다.**

서울·부산 실전11거리 **151,074출전·13,928경주·12,435두**를 분석했다. 암60,066·수54,908·거36,100행이다. 같은 말이 수→거로 바뀐 경우 두 분류에 속할 수 있다. 거세마는 수컷의 거세 상태를 구분한 원천 경주 분류이며 생물학적 성별 세 개를 뜻하지 않는다. 기존 계절 모집단과 원문 성별·ID·구간기록을 전부 대조했다. 서울 종료일2026-09-20·부산2026-09-18, 거리별 종료일은 다르다.

## 전체시간 차이와 질문의 변화

서울1200m의 암−수 원시 평균차는 **+0.605초**, 부산은 **+0.583초**다. 연령·월·연도·정확 함수율만 맞춘 비교는 각각+0.490·+0.581초, 등급까지 같게 한 비교는+0.184·+0.281초다. 전체 통제 후 각각 **+0.114초 [0.038,0.191]**, **+0.119초 [0.040,0.198]**가 남는다. 양수는 앞 분류가 느린 방향이다. 점별95%구간이다.

비교 표본은 단계에 따라 달라진다. 예를 들어 서울1200m 암/수 원시20,191행 중 등급 공통 표본14,694행, 부산13,228행 중9,431행이 남았다. 같은 공통 표본의 원시 차이는 서울+0.419·부산+0.433초이고, 등급을 맞추기 전 연령·환경 차이는+0.315·+0.405초다. 전체 원시 차이에서 등급 통제 차이를 단순 빼서 등급이 설명한 비율로 해석할 수 없다.

같은 공통 표본에서 중량·마체중만 추가하면 서울−0.025·부산+0.004초로 줄지만 rating·이력을 추가하면+0.114·+0.119초가 된다. 통제가 늘 때 차이가 단조롭게 줄지 않는다. **같은 등급/rating은 이미 분류된 수준을 맞춘 다른 질문이고, 체중과 중량은 성별 집단의 구성·선발·중량 배정 경로 일부일 수 있다. 통제 계수는 총격차나 감량의 인과효과가 아니다.**

![동일 표본의 통제 단계](outputs/same_sample_adjustment_stages.png)

{ft}

전체 통제 암−수는 표본이 충분한 주요 거리에서 약0.1~0.3초가 남는 경우가 많다. 서울1700m+0.338초 [0.177,0.498]가 비교적 크고, 부산1600/1800은+0.234/+0.228초다. 서울1800은+0.203초이나 구간이0을 포함한다.1000m와 서울1600m에서는 암−수의 확실한 차이가 남지 않는다. 이 표는 각 거리의 다른 출전 집단이며 ‘거리가 길수록 격차가 반드시 커진다’는 상호작용 결론이 아니다.1900m 이상 암말 비교는 대체로 공통 표본이 작아 잠정 또는 미식별이다.

거−수 전체 통제 차이는 서울1200−0.056초 [−0.123,0.010], 부산1200+0.054초 [−0.041,0.149]다. 대부분0을 포함한다. 서울1000−0.160초 [−0.290,−0.029], 부산1400−0.103초 [−0.193,−0.013] 같은 국소 차이는 있지만 여러 탐색 비교 중 일부이며 거세마의 보편적 우월성 근거가 아니다. 암−거는 서울1200+0.160초 [0.074,0.246], 부산1400+0.264초 [0.157,0.370] 등이나 각 쌍의 공통 표본이 달라 다른 두 대비의 차로 만들 수 없다.

![거리별 전체 통제 결과](outputs/controlled_time_gaps.png)

## 전체·초반·중간·막판

1200m 전체 통제의 암−수 차이는 출발200m 서울−0.047·부산−0.056초로 암말이 조금 빠른 방향인 반면, 마지막200m는 서울+0.077·부산+0.116초로 느리다. 전체시간 차이가 모든 구간에 균일하게 있는 것은 아니다.1400m에서도 후반400m와 마지막200m에 느린 방향이 나타난다. 전개·기수·게이트·실제 주행 경로를 모두 통제하지 않아 지구력의 생물학적 차이로 해석하지 않는다.

{st}

![독립 구간 시간 차이](outputs/independent_section_gaps.png)

독립 구간은 출발200m+(거리−800)m+후반400m+마지막200m다. 여기서 후반400m는 마지막600→200m 사이이며 서울의 미계측 **마지막400m**가 아니다. 합은 전체시간과 같고 회귀 차이의 합도 별도 검증했다. 마지막600m는 겹치는 보조구간이다. 서울 마지막400m를 만들거나4C 명목530m를 임의로 바꾸지 않았다. 부산 관측 마지막400m는 유효 관측만 별도로 분석했다.

초반 상대속도는 자기 전체 평균속도 대비 비율이며 서울/부산1200 암−수+0.446/+0.503%p, 막판200 상대속도는−0.363/−0.586%p다. 절대 초 차이나 우승확률과 같은 척도가 아니다. 전체/겹치는 구간점수를 더하지 않는다.

## 분포·연령·등급·함수율

평균만이 아니라 중앙값·빠른20%/느린20% 경계를 확인했다. 아래는 원시 전체시간이며 조건을 맞춘 기준은 아니다. 모든 거리·연령·등급의 전체 및 구간 P10/P20/중앙/P80/P90, 구간 자체 꼬리와 전체시간 꼬리 집단의 구간 평균을 [분포CSV](outputs/observed_distributions.csv)에 보존했다. 동률을 경계에 포함하므로 실제 꼬리 인원은 정확히20%가 아닐 수 있다.

{md(dt)}

연령별 표는 같은 거리·등급·연도·월·정확 함수율을 맞춰 지역 안에서 묶은 암−수 결과다.3~5세 이상에서 작은 양의 차이가 대체로 남고,2세는 부산 거의0·서울 불확실하다. 연령 증가의 선형 법칙이나 서로 다른 연령 계수 간 유의차를 입증한 것은 아니다. 나이별 출전 선택과 남아 있는 말의 구성이 다르다.

{ag}

등급별 전체 통제 차이는 국5 서울+0.282·부산+0.245초, 국6은+0.054·+0.052초로 다르게 관찰됐다. 국6에는 rating/이력 결측이 많고, 국3·혼3 및 일부 상위 등급은 구간이0을 포함한다. OPEN은 편성·중량·표본 불균형과 민감도가 커 큰 계수를 일반화하지 않는다. 전체 등급표는 [상세 결과](ALL_RESULTS.md)에 있다.

1200/1400m 함수율 상태별로도 정확한 함수율 숫자·연령·등급·월을 유지한 보조 분석을 했다. 예를 들어 서울1200 건조+0.137초 [0.026,0.248], 불량+0.362초 [0.081,0.644], 부산1400 포화+0.493초 [0.047,0.940]다. 그러나 많은 상태별 구간은 넓고0을 포함한다. 상태간 상호작용의 별도 유의성/다중비교 검증을 하지 않았으므로 특정 주로에서 성별 격차가 커진다는 보정 근거로 사용하지 않는다. 유리한 일부 상태만 일반화하지 않도록 세 쌍·모든 상태 결과를 함께 보존했다.

## 같은 경주에서의 성과

원래 출전자 중 해당 두 분류가 실제로 함께 나온 경주만 비교했다. 암말 제한 경주는 혼합 경쟁으로 세지 않았다. 동일 경주 고정효과는 지역·거리·날짜·등급·함수율·편성의 공통 조건을 제거하지만 각 말의 능력과 선택까지 무작위로 만들지는 않는다. 3위 이내는 배당 규정과 구분한 실제 착순≤3 결과다. 단위 **%p**이며 음수는 암말의 비율이 낮은 방향이다.

{rt}

서울1200 같은 경주 내 암−수3위 이내 차이는 통제 전−8.294%p [−10.195,−6.392], 전체 통제−3.580%p [−5.748,−1.412]다. 부산1200은−9.347→−2.684%p다. 중량·체중 단계에서는 방향이 바뀔 수도 있으며 rating·이력 추가는 다시 다른 질문이다. 서울1700 전체 통제−7.314%p [−10.892,−3.736]처럼 차이가 더 남는 곳도 있으나 단일 기록 점수를 능력이나 우승확률로 바꾸는 근거가 아니다. 우승·상대착순 결과와 세 쌍 전체는 CSV에 별도 보존했다.

기존 정상 완주 선택의 영향을 점검하려고 같은 시행키의 원래 비제외 출전자 **159,014행·14,636경주**도 복원했다. 비정상 착순코드91/92의484행은 우승/3위 이내가 아닌 결과로만 포함하고 기록을 만들지 않았으며, 착순0의2행은 결과 미상 null로 남겼다. 이 확대 표본에서 암−수3위 이내 통제 전 차이는 서울1200−7.810%p, 부산1200−9.547%p로 방향이 유지됐다. 확대 표본에는 모든 과거 성적 통제를 갖춘 완전한 동일 모형을 적용하지 않았으며 `all_starters_load_body`는 기존 `race_load_body`와 같은 통제 수준으로 비교한다. 운영 확률이나 전수 미래 성능이 아니다.

## 최근과 과거

부분2026년의 영향을 줄이기 위해 모든 해1~8월을 맞춰 성별×최근시기 상호작용을 계산했다.2018~2023 대2024~2026 전체 통제의 지원 가능한 **{len(recent_supported)}개** 격차 변화(세 쌍·모든 지원 거리)는 모두 점별95%구간에0이 포함됐다. 최근 격차가 없어졌거나 동일하다는 동등성 증명이 아니라 변화의 방향·크기를 충분히 구별하지 못한 결과다.

서울1400 암−수의 등급 통제 변화는+0.390초 [0.079,0.701]지만 전체 통제는+0.097초 [−0.305,0.499]로 불확실해진다. 서울1200 전체 통제+0.120초 [−0.174,0.414], 부산1200−0.081초 [−0.394,0.233]다. 많은 장거리는 공통 시기 표본이 부족하다. 완결2024~2025·가까운2021~2023 민감도도 함께 보존했다. 같은 자료를 나눈 재분석이며 독립 미래 검증이 아니다.

![최근 격차 변화](outputs/recent_gap_changes.png)

## 선택·검증·적용 판단

{md(sel)}

기존 감사 모집단 대비 성별별 제외율은 약4.5~4.9%다. 거리별 제외율도 [선택CSV](outputs/selection_by_sex.csv)에 있다. 임의의 새 꼬리 절사를 하지 않았다. 더 넓은 양수 완주 표본의 같은등급 암−수 차이는 서울/부산1200+0.175/+0.277초로 본 분석+0.184/+0.281초와 가까웠다. 마필당 한 출전으로 줄인 민감도와 제한경주 제외, 이력 관측, 완전관측 민감도도 보존했다. 표본이 바뀌므로 동일 모형의 독립 재검증이라고 부르지 않는다.

rating 결측은 암22,990/60,066·수14,960/54,908·거6,707/36,100행이고 이전 상대착순 이력 결측은4,489·4,303·985행이다. 암말의 결측 비중이 더 크며 중앙값+결측 지시자만으로 모든 선택 편향을 해결하지 못한다. 완전관측1200 암−수는 서울+0.167초 [0.081,0.253], 부산+0.177초 [0.075,0.280]로 양의 방향이 남지만 비교 대상은 더 적다.

[본 검증](outputs/verification.json):151,074원문 행 대조,57개 SQL 분포,2,100공통 점수 직접 계산,169개 정확 매칭 차이,72개 별도 희소 더미 회귀·이원 군집 오차 대조가 통과했다. 최대 계수 오차 약2.2e−8초다. 보조 표본·상태별 분석과 독립구간 계수 합·꼬리 집계는 [보조 검증](outputs/supplement_verification.json)에 있다. 해시·중복·날짜·미지원 구간 null을 확인했다. 검증은 계산·출처의 일치이며 모형 가정이나 인과성을 입증한 것이 아니다.

**개별 말의 기록은 먼저 기존 공통 지역·거리·등급·함수율 기준으로 읽고, 당시 성별과 전개를 해석 맥락으로 참고하는 것이 적절하다. 이번 평균차를 모든 말의 기록에 일률 가산/감산하지 않는다.** 성별을 합친 최근 공통 경험분포 점수도 보조 계산했지만 새 공식 기준이나 종합능력이 아니다. 성별별로 따로50점이 되게 만드는 방식은 사용하지 않았다. 별도 성별 기준표는 실제 집단 분포를 보여주는 설명자료로 만들 수 있으나, 원래 격차를 숨기거나 운영 보정으로 채택할 근거는 이번 연구만으로 충분하지 않다.

서울80%·부산90%는 기존 환경 차이 보정의 반영률이며 원기록의 축소율이 아니다. 이번에는 원기록과 정확 함수율 통제를 사용했고 기존 보정·거리별 기준·구간 보류 결정을 바꾸지 않았다. 웹사이트 구현/배포와 운영 모델 반영은 하지 않았다.

[질문·계획](PLAN.md) · [원천·방법·재현](SOURCES.md) · [전체 결과](ALL_RESULTS.md) · [게시용 요약](PUBLICATION.md) · [게시용 데이터](outputs/web_sex_ability_gap.json) · [파일별 용량](outputs/artifact_inventory.json)
'''
    (HERE/'README.md').write_text(report)
    sections=['# 세 분류의 전체 결과\n\n차이는 앞 분류−뒤 분류다. 시간은 초, 성과는%p. 점별95%구간, 잠정은 지원 부족이며 미식별은—다. 원시 비교와 조건부 비교의 표본이 다르다. 상세 정의는 SOURCES.md를 따른다.']
    for target,ref in [('암','수'),('거','수'),('암','거')]:
        sections+=['\n## '+target+'−'+ref+' 전체시간\n\n'+md(stage_table(target,ref))]
    q=C[C.scope.isin(['age','grade'])&C.part.eq('finish')&C.specification.eq('full')]
    sections+=['\n## 연령·등급별 전체 통제\n\n'+generic_table(q,[('scope','범위'),('meet','지역'),('subgroup','구분'),('target','앞'),('reference','뒤')])]
    q=C[C.scope.eq('same_race')&C.part.isin(['top3','win'])&C.specification.eq('race_full')]
    sections+=['\n## 같은 경주 우승·3위 이내 전체 통제\n\n'+generic_table(q,[('meet','지역'),('distance_m','m'),('target','앞'),('reference','뒤'),('part','성과')])]
    q=C[C.scope.eq('distance')&C.distance_m.isin([1200,1400,1800])&C.specification.eq('full')]
    sections+=['\n## 주요 거리 독립·보조 구간\n\n'+generic_table(q,[('meet','지역'),('distance_m','m'),('target','앞'),('reference','뒤'),('part','구간'),('unit','단위')])]
    q=C[C.scope.eq('era')&C.contrast_kind.eq('gap_change')&C.specification.eq('full')]
    sections+=['\n## 기간별 격차 변화\n\n'+generic_table(q,[('meet','지역'),('distance_m','m'),('window','기간'),('target','앞'),('reference','뒤')])]
    q=S[S.scope.eq('moisture_panel')&S.specification.eq('full')]
    sections+=['\n## 함수율 상태별1200/1400 전체 통제\n\n'+generic_table(q,[('meet','지역'),('distance_m','m'),('subgroup','상태'),('target','앞'),('reference','뒤')])]
    sections+=['\n## 선택 민감도 전체 표\n\n선택 민감도는 [contrasts.csv](outputs/contrasts.csv)의 scope=sensitivity, 원래 출전자 성과는 [supplement_contrasts.csv](outputs/supplement_contrasts.csv)의 scope=original_starter_sensitivity에서 확인한다. 모든 통제 수준·표본수·제외율·표준오차·군집 수·지원 여부를 제공한다.']
    (HERE/'ALL_RESULTS.md').write_text('\n'.join(sections)+'\n')
    publication='''# 성별 분류에 따라 기록과 경기력이 다를까

서울·부산 실전151,074출전·13,928경주를 비교했다. 암말·수말·거세마는 당시 경주 결과의 분류다. 거세마는 수컷의 거세 상태를 구분한 집단이며 생물학적 성별 세 개를 뜻하지 않는다.

암말의 원시 평균 전체시간은1200m에서 수말보다 서울0.60초·부산0.58초 느렸다. 같은 연령·등급·정확 함수율·월을 맞추고 중량·체중·rating·과거 성적을 고려하면 차이는 서울0.11초 [0.04,0.19]·부산0.12초 [0.04,0.20]로 작아졌다. 같은 수준과 중량을 맞춘 차이는 전체 출전 집단의 차이와 다른 질문이다. 조건 통제 후 차이가 작다고 원래 격차가 없다는 뜻은 아니다.

1200m 암말은 출발200m에서 조금 빠른 방향이고 마지막200m에서 느린 방향이었다. 같은 경주에서 수말과 함께 경쟁한 암말의3위 이내 성과도 전체 통제 후 서울−3.58%p·부산−2.68%p로 낮은 방향이 남았다. 수말과 거세마의 전체시간 차이는 대부분 작고 일정한 우열을 보이지 않았다. 최근2024~2026년과 과거의 격차가 일관되게 변했다는 근거도 충분하지 않았다.

예를 들어 서울1200m 한 말의 기록은 기존 같은 지역·거리·등급·함수율 기준에서 먼저 읽고 당시 성별·전개를 함께 참고한다. 평균 성별 차이를 그 말의 기록에 자동 가산/감산하지 않는다. 공통 참조 기록점수는 한 출전의 기록을 설명하며 종합능력·우승확률이 아니다.

전체 원시표와 공통 표본, 제외율·95%구간을 함께 제공한다.1900m 이상 암말 비교, 일부 상위/OPEN·젖은 상태 및 최근 비교는 소표본 또는 큰 불확실성이 남는다. 결과는 관찰된 출전 집단의 조건부 연관이다. 거세 수술의 인과효과나 생물학적 능력 차이를 입증하지 않았다. 별도 성별 보정·성별 전용 운영 기준은 미채택이다.

자료:2018년 이후, 서울2026-09-20·부산2026-09-18까지이며 거리별 종료일은 다르다.2026년은 부분 연도여서 시기 비교는 공통1~8월과 완결연도 민감도를 사용했다. 기존 함수율 연구 기준과 구간 보류 결정은 유지했다. 게시 준비 문서이며 웹 구현·배포·운영 반영을 완료한 것은 아니다.

[전체 연구](README.md) · [방법과 출처](SOURCES.md) · [전체 표](ALL_RESULTS.md) · [게시 데이터](outputs/web_sex_ability_gap.json)
'''
    (HERE/'PUBLICATION.md').write_text(publication)
    rows=C[C.specification.isin(['raw','context','grade','load_body','full','race','race_load_body','race_full'])]
    data=dict(version='20261007_sex_ability_gap_v1',status='observational_research_not_adopted',published=False,operational_applied=False,
        rows=151074,races=13928,horses=12435,sex_counts=A['sex_counts'],date_start=A['source_start'],date_end=A['source_end'],
        periods=dict(primary='2018+; ends vary by distance',era='same Jan-Aug 2018-2023 vs 2024-2026'),
        direction='target minus reference; positive time means slower; positive win/top3 means higher rate in percentage points',
        uncertainty='pointwise approximate 95%, conservative max of two-way horse/date and one-way variances',
        limitations=['observational association, not biological/causal ability','conditional overlap populations differ','no predictive/future validation','no operational correction','unknown reference/unsupported CI=null'],
        figures=['controlled_time_gaps.png','same_sample_adjustment_stages.png','independent_section_gaps.png','recent_gap_changes.png'],
        estimates=json.loads(rows[[x for x in ['scope','meet','distance_m','subgroup','window','specification','target','reference','part','contrast_kind','unit','difference','lower','upper','supported','input_pair_n','common_n','target_n','reference_n','common_races','common_horses','common_days','excluded_fraction','q_primary_distance_finish'] if x in rows]].to_json(orient='records',force_ascii=False)),
        supplements=json.loads(S[[x for x in ['scope','meet','distance_m','subgroup','window','specification','target','reference','part','unit','difference','lower','upper','supported','common_n','excluded_fraction'] if x in S]].to_json(orient='records',force_ascii=False)),
        distributions=json.loads(desc[desc.scope.eq('distance')].to_json(orient='records',force_ascii=False)))
    (OUT/'web_sex_ability_gap.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('reports and four figures generated')


if __name__=='__main__':main()
