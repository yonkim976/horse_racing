"""Korean report, publication data, fixed examples and observed-study figures."""
from pathlib import Path
import json,hashlib
import pandas as pd,numpy as np,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
H=Path(__file__).resolve().parent;R=H.parent;O=H/'outputs';G=H/'figures';ROOT=H.parents[2]
font=FontProperties(fname='/System/Library/Fonts/AppleSDGothicNeo.ttc');plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':11,'figure.facecolor':'#f6f8fc','axes.facecolor':'white'})
NAMES={'past_back':'과거 뒤쪽형','back_repeat':'뒤쪽 반복회복 후보','back_low':'뒤쪽 회복반복 부족','past_lead':'과거 선행형','past_front':'과거 앞선권형','past_fore_strict':'엄격 선입형'}
EX={'past_lead_other_band':'상대 선행형3+ 대0~1','actual_pack_band':'실제 첫 마군3+ 대1','pace_band':'실제 빠른 페이스 대느린 페이스'}
def table(headers,rows):return '| '+' | '.join(headers)+' |\n|'+'|'.join(['---']*len(headers))+'|\n'+'\n'.join('| '+' | '.join(str(v) for v in row)+' |' for row in rows)
def pp(x):return f'{100*x:+.2f}'
def pct(x):return f'{100*x:.2f}%'
def ci(r,unit=100):return f'{unit*r.estimate:+.2f} [{unit*r.lower:+.2f}, {unit*r.upper:+.2f}]'
def clean(df):return json.loads(df.to_json(orient='records',force_ascii=False))
def main():
    d=pd.read_parquet(O/'analysis_rows.parquet');q=pd.read_parquet(O/'race_context.parquet');metrics=pd.read_csv(O/'cohort_metrics.csv');comp=pd.read_csv(O/'comparisons.csv');reg=pd.read_csv(O/'additive_adjusted_comparisons.csv');rp=pd.read_csv(O/'race_pace_comparisons.csv');ar=pd.read_csv(O/'additive_race_pace_comparisons.csv');following=pd.read_csv(O/'following_adjusted_comparisons.csv')
    main=d[d.year.between(2024,2025)];rmain=q[q.year.between(2024,2025)];repeat=metrics[(metrics.window=='2024_2025')&(metrics.scope=='all')&(metrics.cohort=='back_repeat')]
    lead=repeat[repeat.exposure=='past_lead_other_band'].set_index('status').loc[['0~1','2','3+']]
    leadrows=[[status,f'{r.n:,}',f'{r.recovery_n:,}',pct(r.recovery_mean),f'{r.top3_n:,}',pct(r.top3_mean)] for status,r in lead.iterrows()]
    opportunity=[]
    for window,full in [('2024_2025',main),('2026_partial',d[d.year.eq(2026)])]:
        for exposure in EX:
            for status,g in full[full.closer_candidate].groupby(exposure):
                eligible=g[g.p_g3f.ge(.5)&g.recovery.notna()];opportunity.append(dict(window=window,exposure=exposure,status=status,n=len(g),eligible_n=len(eligible),recovery_rate=float(eligible.recovery.mean()) if len(eligible) else None))
    pd.DataFrame(opportunity).to_csv(O/'recovery_given_opportunity.csv',index=False)
    regions=metrics[(metrics.window=='2024_2025')&(metrics.scope=='meet_distance')&(metrics.cohort=='back_repeat')&(metrics.exposure=='past_lead_other_band')].copy();regions.to_csv(O/'regional_distance_summary.csv',index=False)
    regrows=[]
    for label,g in regions.groupby('label'):
        z=g.set_index('status');lo=z.loc['0~1'] if '0~1' in z.index else None;hi=z.loc['3+'] if '3+' in z.index else None
        regrows.append([label.replace('|',' '),'—' if lo is None else f'{pct(lo.recovery_mean)} ({lo.recovery_n})','—' if hi is None else f'{pct(hi.recovery_mean)} ({hi.recovery_n})','—' if lo is None or hi is None else pp(hi.recovery_mean-lo.recovery_mean),'표본주의' if lo is None or hi is None or lo.small_sample or hi.small_sample else '관측 비교'])
    cases=d[d.source_key.isin(['부산:20260918:9','서울:20260920:11'])].sort_values(['source_key','gate']);cases.to_csv(O/'fixed_example_cards.csv',index=False)
    # Raw observed rates have different valid denominators, printed explicitly.
    fig,ax=plt.subplots(figsize=(12,5));x=np.arange(3);width=.34
    for offset,col,color,title,ncol in [(-width/2,'recovery_mean','#2864c3','후반 회복률','recovery_n'),(width/2,'top3_mean','#de8a2b','3위 이내율','top3_n')]:
        bars=ax.bar(x+offset,lead[col]*100,width,color=color,label=title)
        for bar,(_,r) in zip(bars,lead.iterrows()):ax.text(bar.get_x()+width/2,bar.get_height()+.8,f'{r[col]*100:.1f}%\nn={int(r[ncol]):,}',ha='center',va='bottom',fontsize=10)
    ax.set_xticks(x,['선행형0~1두','선행형2두','선행형3두 이상']);ax.set_ylim(0,55);ax.set_ylabel('관측 비율 (%)');ax.set_title('선행형이 많을 때 막판 회복은 늘었지만, 입상은 늘지 않았다',loc='left',fontweight='bold');ax.legend(loc='upper left',frameon=False);ax.spines[['top','right']].set_visible(False)
    fig.text(.07,.01,'서울·부산2024~2025 · 과거 뒤쪽 성향+회복2/5이상 후보 · 원시 비교, 조건 차이 포함',fontsize=10);fig.tight_layout(rect=[0,.04,1,1]);fig.savefig(G/'observed_recovery_top3.png',dpi=140);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,5),sharey=True)
    sub=reg[(reg.window=='2024_2025')&(reg.cohort=='back_repeat')]
    for ax,target,title in zip(axes,['recovery','top3'],['후반 회복률 차이','3위 이내율 차이']):
        z=sub[sub.target==target].set_index('exposure').loc[list(EX)];y=np.arange(3)
        ax.errorbar(z.estimate*100,y,xerr=[(z.estimate-z.lower)*100,(z.upper-z.estimate)*100],fmt='o',color='#2864c3',capsize=4);ax.axvline(0,color='#777',lw=1);ax.set_yticks(y,list(EX.values()));ax.set_xlim(-8,17);ax.set_xlabel('차이 (%p), 말·날짜 군집95%구간');ax.set_title(title,loc='left',fontweight='bold');ax.spines[['top','right']].set_visible(False)
    axes[0].invert_yaxis()
    fig.suptitle('보조 가법 조정: 회복 이득과 입상 이득을 구분해야 한다',x=.04,ha='left',fontweight='bold');fig.text(.04,.01,'2024~2025 반복회복 후보 · 정확조건셀 피복 부족 확인 후 추가한 탐색 분석 · 인과효과 아님',fontsize=10);fig.tight_layout(rect=[0,.04,1,.93]);fig.savefig(G/'adjusted_recovery_top3.png',dpi=140);plt.close(fig)
    fig,ax=plt.subplots(figsize=(11,4.5));labels=[]
    for j,exposure in enumerate(['past_lead_band','actual_pack_band']):
        label='과거 선행형3+ 대0~1' if j==0 else '실제 첫 마군3+ 대1';labels.append(label)
        for delta,source,color,name in [(-.1,rp,'#999','엄격 공통조건셀'),(.1,ar,'#2864c3','보조 가법 조정')]:
            r=source[(source.window=='2024_2025')&(source.exposure==exposure)].iloc[0];ax.errorbar(r.estimate,j+delta,xerr=[[r.estimate-r.lower],[r.upper-r.estimate]],fmt='o',capsize=4,color=color,label=name if j==0 else None)
    ax.axvline(0,color='#777',lw=1);ax.set_yticks(range(2),labels);ax.invert_yaxis();ax.set_xlim(-.19,.06);ax.set_xlabel('빠른3두 평균 S1F 초 차이 (음수=초반이 빠름), 날짜군집95%구간');ax.set_title('선행형 수와 실제 마군 크기의 페이스 연결은 강도가 다르다',loc='left',fontweight='bold');ax.legend(frameon=False,loc='lower left');ax.spines[['top','right']].set_visible(False);fig.tight_layout();fig.savefig(G/'density_early_seconds.png',dpi=140);plt.close(fig)
    focus=comp[(comp.window=='2024_2025')&(comp.cohort=='back_repeat')];adjust=reg[(reg.window=='2024_2025')&(reg.cohort=='back_repeat')]
    rows=[]
    for ex in EX:
        for target in ['recovery','top3']:
            r=adjust[(adjust.exposure==ex)&(adjust.target==target)].iloc[0];strict=focus[(focus.exposure==ex)&(focus.target==target)&(focus.method=='conditions')].iloc[0];same=focus[(focus.exposure==ex)&(focus.target==target)&(focus.method=='same_horse')].iloc[0]
            rows.append([EX[ex],'회복' if target=='recovery' else '3위',ci(strict),f'{strict.coverage*100:.1f}%',ci(same),ci(r),f'{r.bh_q:.3g}'])
    raw=focus[(focus.exposure=='past_lead_other_band')&(focus.target=='recovery')&(focus.method=='raw')].iloc[0]
    desc='선행형이 많은 편성과 빠른 초반 페이스에서 뒤쪽형의 막판 순위 회복이 늘어나는 근거는 있다. 그러나 추입형이나 선입형의3위 이내 확률이 일률적으로 오른다는 근거는 확인되지 않았다. 실제 첫 마군의 말 수만으로 뒤쪽형 유리를 판정하는 근거도 약하다.'
    pub=f'''# 선행형이 많으면 추입형이 유리한가

{desc}

서울·부산2024~2025 전체{len(main):,}출전·{len(rmain):,}경주를 바탕으로,현재 위치를 보기 전에 과거 각질을 고정했다. 반복회복 후보는 직전5실전의 중단·후미가3회이상이고 과거 후반회복이2회이상인 출전이다.

{table(['편성의 선행형 수','후보 출전','회복 유효','후반 회복률','3위 유효','3위 이내율'],leadrows)}

선행형3두이상 대0~1두의 회복률 차이는{ci(raw)}%p였다. 같은말·지역·정확거리·등급 비교에서도 회복률은+8.71%p[+3.32,+14.10]였지만,입상 이득은 확인되지 않았다. 위 비율은 조건 차이가 섞인 관측치이며 운영 확률 가산점이 아니다.

조건셀의 낮은 피복을 보완한 탐색 가법 조정에서는 반복회복 후보의 회복률 차이가 선행형3+ 대0~1에서+6.34%p[+2.29,+10.38],실제빠름 대느림에서+8.26%p[+4.28,+12.24]였다. 실제첫마군3+ 대1은+1.03%p[−2.20,+4.27]로 불확실했다. 세 경우 모두3위 이내율 증가의 구간은0을 포함했다. 엄격공통셀·같은말·보조조정은 서로 다른 표본과 가정을 쓴다.

원문S1F 빠른3두 평균초를 실제페이스로 측정했다. 보조조정에서 선행형3+는0~1보다0.100초[0.081,0.119] 빨랐고,실제첫마군3+는1보다0.023초[0.007,0.039] 빨랐다. 단,엄격공통셀 페이스 차이는 두 경우 모두 불확실했다. 초반200m 차이이며 전체기록 손실이나 경합강도로 환산하지 않는다.

부산2026-09-18 9경주는 과거선행형3두·실제첫마군3두였다. 반복후보 구디는G3F8위→결승5위로 회복했지만 입상하지 않았고,미스터키맨은G3F2위→결승2위로 입상했으나 후반대회복 사건은 아니었다. 같은 경주의 스타마타는5위→9위였다. 이 경주는 과거 동지역·거리·등급 페이스 참조30경주 미달로 빠름/느림을 판정하지 않았다.

선행형 수는 빠른 전개 가능성을 읽는 후보 정보이고,막판 회복 반복·상대능력·게이트·거리와 함께 봐야 한다. 선입형의 입상 이득도 별도 탐색에서 미확정이다. 현재페이스는 사후 관측이며 새 예측모델 개선·인과효과·작전 의도를 입증하지 않았다.2026부분 자료는 같은 설계의 후속관측이다.

[원 보고서](README.md) · [주검증](outputs/verification.json) · [보조검증](outputs/adjusted_verification.json).
'''
    (H/'PUBLICATION.md').write_text(pub)
    pubdata=dict(title='선행 밀집과 뒤쪽형의 회복·입상',followup='28G',status='research_candidate',primary_years=[2024,2025],primary_roster_n=len(main),primary_races=len(rmain),primary_horses=main.horse_id.nunique(),pace_valid_races=int(rmain.pace_valid.sum()),pace_reference_supported_races=int(rmain.pace_band.ne('unknown').sum()),conclusion=desc,raw_repeat_by_candidate_count=clean(lead.reset_index()),primary_conditions=clean(comp[(comp.window=='2024_2025')&(comp.method=='conditions')]),same_horse_repeat=clean(focus[focus.method=='same_horse']),exploratory_additive=clean(reg),race_pace_strict=clean(rp),race_pace_exploratory=clean(ar),following_exploratory=clean(following),predictive_models_trained=0,operating_model_changed=False,causal_effect_identified=False,current_pace_is_prerace_feature=False)
    (H/'PUBLICATION.json').write_text(json.dumps(pubdata,ensure_ascii=False,indent=2)+'\n')
    sample=[]
    for label,g in [('2024~2025',main),('2026부분',d[d.year.eq(2026)]),('2018~2023',d[d.year.le(2023)])]:
        race=q[q.source_key.isin(g.source_key)];sample.append([label,f'{len(g):,}',len(race),int(race.pace_valid.sum()),int(race.pace_band.ne('unknown').sum()),int(g.closer_candidate.sum())])
    phase=pd.read_csv(O/'position_opportunity.csv');phas=phase[(phase.window=='2024_2025')&(phase.cohort=='back_repeat')&(phase.exposure=='past_lead_other_band')].set_index('status')
    rep='''# 선행 밀집과 뒤쪽형 이득의 관측 검증

2026-10-09 · 연구28 후속28G · 연구 후보 · 새 예측모델/운영/DB/배포 변경 없음.

'''+desc+f'''

## 표본과 분류

{table(['기간','전체 출전','경주','S1F페이스 유효경주','과거페이스 기준 지원','반복회복후보 출전'],sample)}

전체159,014출전·14,636경주. 종료일 서울2026-09-20·부산2026-09-18. 첫연도2018은 과거 조정/이력이 제한적이며 주검정에 포함하지 않는다.2026은 부분연도 후속관측으로 독립 외부검증이나 완결연도 비교가 아니다.2018~2023 기술표도 저장했다. 제주·영천·심사·주로빠르기를 제외한다.

과거 선행형은T−2 기준730일 안의 직전5실제슬롯 모두 통과조 유효이며 선행3회이상이다. 뒤쪽형은중단+후미3/5,반복회복후보는뒤쪽형 중 직전5회복 사건 모두 유효이며2/5이상. 분류는 출전 시점마다 달라진다. 이력이 부족한 말은 비선행형으로 확정한 것이 아니라 미분류다. 전체명단의지원비율과80%이상 민감도를 별도 보존했다.

통과조 첫 마군은 모두 선행으로 분류한다. 첫마군3두는3두가 앞선 조에 있다는 뜻으로,나란히 경합·소모·선행의도·실제 내외측경로의 직접 측정이 아니다. 상대선행형수는 자기 과거선행형을 뺐다. 실제첫마군수는 경주 공통 노출이며 자기 현재첫마군을 뺀 분석도 별도로 했다.

후반회복은 공식G3F(결승600m전)의상대순위 p=(순위−1)/(두수−1)가0.5이상이고 결승까지0.25이상 좋아진 사건이다. 두수11일 때 최소3등 정도 회복이며,3위 입상과 별개다. 정상결승1..N이 아닌 기록/불완전통과순위는 지표별NaN,실패0으로 대체하지 않았다. 정상성적 기준3/5위율과비정상결승표시를 함께 저장했다.

## 원시 관측: 회복과 입상을 나누면 답이 달라진다

{table(['편성 선행형','후보 출전','회복 유효','회복률','3위 유효','3위율'],leadrows)}

![회복과 입상](figures/observed_recovery_top3.png)

선행형3+ 대0~1의 반복후보 회복 차이는{ci(raw)}%p,하지만3위율 차이는−2.13%p[−4.91,+0.65]로 이득을 확인하지 못했다. 전체 뒤쪽형에서도 선행형수에 따른 회복 증가가 관측됐다. 반복회복이 부족했던 뒤쪽형의 회복도 증가하므로 반복후보만의 특수 이득이라고 단정할 수 없다.

## 조건을 맞춘 비교와 보조 조정

아래는 반복회복 후보. 단위%p,대괄호95%구간. 엄격조건은지역×정확거리×등급×연도×정확두수×함수율상태×과거평균착순3구간의 공통셀(각상태5출전·2경주이상),같은말은말×지역×정확거리×등급(각1출전이상)이다. 조화표본가중 w=nA*nB/(nA+nB),각side의 전역가중평균 중심 영향함수. 피복은 두 상태의 해당 유효 출전 중 남은 비중이다.

{table(['노출 대비','지표','엄격조건 차이[구간]','피복','같은말 차이[구간]','보조조정 차이[구간]','보조BH q'],rows)}

엄격조건셀은 반복후보에서6~8% 정도만 남으므로 전체모집단의 정밀한 결론으로 일반화하지 않는다.2026반복후보의 선행형3+ 대0~1 엄격공통셀은 아예 없으며 결과0이 아니다. 같은말 비교에도 매 출전 컨디션·상대능력·주행경로 차이가 남는다.80%이력지원과현재자기첫마군제외 민감도도 comparisons.csv에 있다.

엄격셀 피복 부족을 확인한 뒤 **탐색 가법조정**을 추가했다. 지역×정확거리×등급×연도 절편+정확두수·정확함수율 범주+과거평균착순·편성평균과거착순·지원비율·게이트상대위치 일차/제곱과결측표시를 썼다. 회복/3위는 선형확률 연관성 회귀이며 예측확률 산출용이 아니다. 연속변수 결측은0.5와결측표시로 계산만 가능하게 했고 미관측마를 같은능력으로 확정하지 않았다. 주대비에 사후 승격하지 않았으며 미포함 상호작용/공통효과 가정이 있다.

![보조 조정](figures/adjusted_recovery_top3.png)

과거 뒤쪽형 전체의 엄격셀에서 선행형3+의 회복 차이는+9.46%p[+4.42,+14.49],BH q=.0068,피복11.2%였다. 보조조정에서는+8.31%p[+5.93,+10.69]. 반복후보는같은말+8.71%p[+3.32,+14.10],보조조정+6.34%p[+2.29,+10.38]로 방향이같았다. 단,엄격셀 반복후보 구간은0을 포함한다. 실제첫마군 크기의 회복 이득은 보조조정+1.03%p[−2.20,+4.27]로 불확실했다.

입상은다르다. 반복후보의 보조조정3위 차이는 선행형수−0.15%p[−3.47,+3.18],마군크기+1.13%p[−1.72,+3.98],실제빠름+1.64%p[−1.95,+5.22]. 선입/앞선권형도별도 탐색으로 확인했으나3위 이득은모두불확실했다(엄격선입 표본 특히작음). ‘뒤에 있으면 무조건 유리’ 또는 ‘선입이 대신입상’까지 확인된 것은아니다.

말·날짜·말날짜 점수합의 최대군집분산 max(V말,V날짜,V말+V날짜−V교차,0),t 자유도최소군집−1을 사용한다. 경주단위는horse_id대신경주ID여서 사실상날짜군집이다. 보조회귀는잔차자유도수정 n/(n−rankX). 주3노출×4집단×2결과를기간·방법별BH,선입보조는별도BH. 유의한값만골라전체결론으로표현하지않았다.

## 선행형 수가 실제 빠른 페이스와 연결되는가

S1F빠른3두 평균초. 전체명단 모두양수S1F·공식S1F완전순열일 때만유효이며,결승비정상마도초반관측이유효하면포함한다. 임의이상치절삭없음. 빠름/느림은평가연도이전3개연도 동일지역×정확거리×등급의경주30개이상 Q25/Q75(연초고정)로판정했다. 같은평가연도분위수를정답과함께만들지않았다. 기준부족은다른등급으로대체하지않았다.

{table(['노출','엄격조건 초 차이[95%]','경주수A/B·피복','보조조정 초 차이[95%]'],[[('과거선행형3+ 대0~1' if e=='past_lead_band' else '실제첫마군3+ 대1'),ci(rp[(rp.window=='2024_2025')&(rp.exposure==e)].iloc[0],1),f"{int(rp[(rp.window=='2024_2025')&(rp.exposure==e)].iloc[0].n_a)}/{int(rp[(rp.window=='2024_2025')&(rp.exposure==e)].iloc[0].n_b)} · {rp[(rp.window=='2024_2025')&(rp.exposure==e)].iloc[0].coverage*100:.1f}%",ci(ar[(ar.window=='2024_2025')&(ar.exposure==e)].iloc[0],1)] for e in ['past_lead_band','actual_pack_band']])}

표는소수2자리지만 보조추정정확값은선행형−0.100209초,마군−0.022851초다. 첫마군크기와초반속도는다른측정이다. 엄격공통셀은둘다0포함,보조가법에서는둘다빠른방향이나강도가다르다. 경주단위로집계해두수가많은경주를중복가중하지않았다. S1F는반응/가속/기수행동을포함하며순수반응시간이나경합소모가아니다. 빠른3두의시간은경주전체페이스의보조측정이며선두단독누적시간과같지않다.

![초반 기록 연결](figures/density_early_seconds.png)

반복후보의실제빠름/느림 원시회복률40.73%/34.44%,3위율26.78%/26.56%. 같은말회복차이+9.49%p[+3.68,+15.30],보조+8.26%p[+4.28,+12.24]지만엄격조건+11.97%p[−0.96,+24.91]는불확실하다. ‘선행형수→빠른전개→회복’의관측연결은있으나매개인과효과를분해한것이아니다.

## 회복할 기회와 지역·거리 차이

선행형0~1/2/3+에서반복후보의평균G3F상대위치는{phas.loc['0~1','p_g3f_mean']:.3f}/{phas.loc['2','p_g3f_mean']:.3f}/{phas.loc['3+','p_g3f_mean']:.3f}(클수록뒤)였다. 중간까지더뒤에있어회복기회가커지는부분이섞인다. 현재G3F뒤쪽절반에있었던경우만보면회복률47.04%(n2791)/50.00%(1228)/53.27%(1284)였다. 이는현재위치에조건을건사후기술치로사전예측/완전보정이아니다. 앞선의절대적인체력붕괴나막판절대속도향상으로동일시하지않는다.

지역전체 원시회복은서울33.07→43.54%,부산33.43→41.46%(0~1→3+)였다. 정확거리별은다음과같고,모든거리에서동일하지않았다. 부산1300과서울1800은점추정방향이반대다.2000이상과서울1700의고밀도등희소조건주의;거리별표는탐색기술이며통합효과를복제하지않는다.

{table(['지역·정확거리','선행형0~1 회복률(n)','선행형3+ 회복률(n)','원시차이%p','범위'],regrows)}

## 2026부분 후속관측과 고정사례

보조조정에서뒤쪽형전체 선행형수의회복차이+8.64%p[+4.15,+13.12],실제빠름+9.45%p[+5.20,+13.71]였다. 반복후보는+7.79%p[+0.58,+15.01]이나BH q=.118로불확실성증가,실제빠름+10.44%p[+3.21,+17.67],q=.020였다. 반복후보의3위이득은여전히불확실. 같은말회복도2026에는구간0을포함했다. 부분연도·일자범위가다르고경쟁마이력도공유하므로독립검증으로부르지않는다.

이전연구와같은2경주21두전원을 fixed_example_cards.csv에보존했다. 부산2026-09-18R9 1800m11두:선행형3두·첫마군3두·S1F빠른3두14.2667초. 동등급과거페이스참조미달이라속도등급미판정. 구디11→8→8→5(회복,비입상),스타마타3→5→7→9(회복실패),미스터키맨4→2→2→2(중간진출후입상,후반대회복사건아님). 서울2026-09-20R11 1200m10두:선행형1두·첫마군2두·S1F13.9333초·과거기준느림·이력지원50%. 이스트라코타9→10→10→6으로느린편성에서도회복했지만입상하지않았다. 사례는효과검정이나사전예측성공사례가아니다.

## 적용과 한계

편성의선행형수는빠른전개/뒤쪽순위회복의후보변수로쓸근거가있다. ‘선행형3두이상→추입형입상확률+몇%’의가산점은도출하지않았다. 실제빠름은경주후관측이므로사전에는전개모델로예측해야하며,그예측확률과후반회복/성적을연결한시간순추가가치검증이필요하다. 기수·조교사정보는추가하지않았다. 과거성향수·현재마군크기·실제속도·순위회복·입상을서로다른정보로보존한다. 이번실제페이스는초반200m의대리측정이며중반까지이어지는압박·지속경합을직접측정하지못했다.

관측연관성이며컨디션·상대편성의세부능력·작전·휴양·장비·실제경로·경합압력의인과효과가아니다. 미래과거구분을지켰어도선택편향이자동제거되지는않는다. 현재초반/G3F위치로수혜집단을먼저선택하지않았으나순위회복정의의기회차이는남는다. 전체포디엄자리수제한을고려해정확두수도맞췄다.2026의숫자를2024~2025의독립적인미래예측정확도로표현하지않는다.

## 검증·산출물

[사전설계와추가민감도](PLAN.md) · [출처/해시](SOURCES.md) · [출전자료](outputs/analysis_rows.parquet) · [경주자료](outputs/race_context.parquet) · [원시표](outputs/cohort_metrics.csv) · [조건/같은말/지원/자기제외](outputs/comparisons.csv) · [보조회귀](outputs/additive_adjusted_comparisons.csv) · [선입보조](outputs/following_adjusted_comparisons.csv) · [페이스참조](outputs/pace_thresholds.csv) · [지역거리](outputs/regional_distance_summary.csv) · [검증](outputs/verification.json) · [보조검증](outputs/adjusted_verification.json) · [게시MD](PUBLICATION.md) · [게시JSON](PUBLICATION.json) · [자기포함용량](outputs/artifact_inventory.json).

원문159,014행S1F시간·마필ID,경주전체명단과후보수·자기제외·첫마군수,過去年SQL분위수,1,508요약행,20,365공통셀과전역영향함수군집구간/BH,원래연구1,214파일해시를검증했다. 보조분석76개는독립적인전체설계행렬회귀/의사역행렬로잔차화계산과대조했다. 검증세부와게시후최종검토는각JSON을따른다. 예측모델0개,회귀는관측연관성의민감도분석이다.
'''
    (H/'README.md').write_text(rep)
    audit=json.loads((O/'source_audit.json').read_text());audit.update(prediction_models_trained=0,descriptive_regression_contrasts=76,models_trained_scope='prediction models; descriptive association contrasts reported separately');(O/'source_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
    sources=['# 출처와 재현\n','2026-10-09 · 원문과이전파생자료는수정하지않았다. 추가외부조회없음. 원문 API 보관본은실전명단과구간/통과순위의일차자료다.\n','| 입력 | 바이트 | SHA-256 |\n|---|---:|---|']
    for item in audit['inputs']:sources.append(f"| [{item['path']}]({'../'+str(Path(item['path']).relative_to('thoroughbred/research'))}) | {item['bytes']} | {item['sha256']} |")
    sources+=['\n28F의과거5슬롯/T−2/730일·공식순위품질·回復定義를재사용했다. 원문S1F시간은서울seS1fAccTime,부산buS1fTime. 관측페이스는전체명단빠른3두평균이다. 현시점마필정보·기수/조교사효과·주로빠르기추가없음.', '\n[원문/자료계약](../20261008_field_pace_prediction/SOURCES.md) · [기존각질/회복연구](../20261008_middle_late_style_validation/README.md) · [원문대조검증](outputs/verification.json) · [보조검증](outputs/adjusted_verification.json) · [변경전목록](outputs/baseline_inventory.json).']
    (H/'SOURCES.md').write_text('\n'.join(sources)+'\n');print('Published report, summaries, examples and 3 figures',flush=True)
if __name__=='__main__':main()
