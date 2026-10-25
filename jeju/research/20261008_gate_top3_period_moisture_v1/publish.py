"""Publish reviewable local report and update the authorized Jeju research index."""
from pathlib import Path
import hashlib
import json
import re
import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent;ROOT=H.parents[2];C=H.parent/'conclusions'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def jwrite(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def newtext(name,v):
    with (H/name).open('x',encoding='utf-8') as f:f.write(v)
def signed(x,d=2):return f'{x:+.{d}f}'.replace('-','−')
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,r))+' |' for r in rows])+'\n'
def interval(r):return f'{signed(r.ci_lo_pp)}~{signed(r.ci_hi_pp)}'

manifest=json.loads((C/'source_manifest.json').read_text());previous={i['path']:i['sha256'] for i in manifest['files'] if i['role']=='conclusion_or_management'}
for i in manifest['files']:
    if i['role'].startswith('source'):assert sha(ROOT/i['path'])==i['sha256'],i['path']
for folder in ['20261008_gate_record_seconds_v1','20261008_gate_2017_2026_v1']:
    folder=H.parent/folder;mm=json.loads((folder/'artifact_manifest.json').read_text())
    for i in mm if isinstance(mm,list) else mm['files']:assert sha(folder/i['path'])==i['sha256'],i['path']
e=pd.read_csv(H/'adjusted_contrasts.csv',dtype={'level':str});p=e[e.variant.eq('primary')];raw=pd.read_csv(H/'raw_gate.csv');rl=pd.read_csv(H/'raw_lateral.csv');ry=pd.read_csv(H/'raw_year_lateral.csv');weights=pd.read_csv(H/'annual_moisture_support.csv');rev=pd.read_csv(H/'reversal_checks.csv');checks=json.loads((H/'verification.json').read_text())
assert checks['status']=='passed' and json.loads((H/'calculation_verification.json').read_text())['status']=='passed'
assert not rev.confirmed_reversal.any()
overall=p[p.kind.eq('overall')].set_index('distance');annual=p[p.kind.eq('year')];band=p[p.kind.eq('band')]
gate_tables=[]
for distances in [[800,900,1000,1110,1200],[1300,1400,1610]]:
    headers=['출발번호']+[f'{dd}m' for dd in distances];rows=[]
    for k in range(1,11):rows.append([k]+[f'{raw[(raw.race_distance_m==dd)&(raw.horse_number==k)].top3_pct.iloc[0]:.2f}%' for dd in distances])
    gate_tables.append(table(headers,rows))
raw_groups=rl.pivot(index='race_distance_m',columns='lateral',values='top3_pct')
group_rows=[]
for dd in [800,900,1000,1110,1200,1300,1400,1610]:
    nr=int(raw[raw.race_distance_m.eq(dd)].races.iloc[0]);g=raw_groups.loc[dd]
    adj=overall.loc[dd] if dd in overall.index else None
    group_rows.append([f'{dd}m',nr,f'{g.inner:.2f}%',f'{g.outer:.2f}%',signed(g.inner-g.outer),signed(adj.effect_pp) if adj is not None else '미추정',interval(adj) if adj is not None else '—',f'{adj.q_BH:.4f}' if adj is not None else '—'])
raw_annual=ry.pivot(index=['race_distance_m','year'],columns='lateral',values='top3_pct')
raw_annual['difference_pp']=raw_annual.inner-raw_annual.outer
raw_annual['races']=ry.groupby(['race_distance_m','year']).races.first()
negative=raw_annual[(raw_annual.difference_pp<0)&(raw_annual.races>=30)]
neg_rows=[]
for (dd,yy),r in negative.iterrows():
    z=annual[(annual.distance==dd)&annual.level.eq(str(yy))].iloc[0]
    neg_rows.append([f'{int(dd)}m',yy,int(r.races),f'{r.inner:.2f}%',f'{r.outer:.2f}%',signed(r.difference_pp),signed(z.effect_pp),interval(z)])
annual_rows=[]
for r in annual.itertuples():
    rr=raw_annual.loc[(r.distance,int(r.level))];m=weights[(weights.distance==r.distance)&weights.year.eq(int(r.level))].iloc[0]
    annual_rows.append([f'{r.distance}m',r.level,r.races,signed(rr.difference_pp),signed(r.effect_pp),interval(r),f'{r.q_BH:.4f}',f'{100*m.standardization_weight_on_unobserved_bands:.1f}%'])
band_rows=[]
for bb,label in [('건조','건조 1~5%'),('양호','양호 6~9%'),('다습','다습 10~14%'),('포화','포화 15~19%'),('불량','불량 20% 이상')]:
    row=[label]
    for dd in [800,900,1000,1110,1200]:
        z=band[(band.distance==dd)&band.level.eq(bb)]
        row.append((f'{signed(z.iloc[0].effect_pp)} [{interval(z.iloc[0])}]' if len(z) else '표본 부족'))
    band_rows.append(row)
era=p[p.kind.eq('era_band')];era_rows=[[f'{r.distance}m',r.level,r.races,r.dates,signed(r.effect_pp),interval(r),f'{r.q_BH:.4f}'] for r in era.itertuples()]
body='''# 제주 출발번호별 입상률과 함수율을 고려한 시기별 내외측 차이

2017년부터 2026년 9월 19일까지 정상 완전순위·정확히 10두·출발번호 1~10인 3,930경주, 39,300출전을 비교했다. **800m와 900m는 전체기간에 내측 1~3번의 Top3 입상 이점이 관찰됐다. 일부 연도와 함수율에서는 외측 8~10번의 비율이 높았지만, 조정·불확실성·다중비교 기준을 함께 충족한 시기별 우세 반전은 확인하지 못했다.** 모든 시기에 내측이 유리하다는 뜻은 아니다.

시간 차이가 전혀 관측되지 않았다는 결론도 아니다. [별도 시간 연구](../20261008_gate_record_seconds_v1/README.md)에서 800m 내측−외측은 전체 −0.385초, 2024~2025년 −0.496초였다. 다른 거리의 초 단위 고정 환산 근거는 불확실했다. 입상률 차이를 초 단위 보정치로 바꾸지 않는다.

## 출발번호별 실제 Top3 입상률

Top3는 최종 1~3착이다. 아래 값은 **조정 전 실제 입상 횟수 ÷ 출전 횟수**다. 10두 편성만 비교하므로 거리마다 각 번호의 출전수는 경주수와 같다. 800m 1,057회, 900m 690회, 1000m 1,067회, 1110m 700회, 1200m 304회다. 10개 번호의 평균은 각 거리에서 정확히 30%다.

'''+gate_tables[0]+'''
1300m는 번호당 47회, 1400m는 63회, 1610m는 2회뿐이다. 특히 1610m의 0%·50%는 두 경주의 관측값이며 게이트 성능을 판단할 근거로 사용하지 않는다.

'''+gate_tables[1]+'''
정확한 분자·분모와 서술용 Wilson 구간은 [번호별 전체 원시 집계](raw_gate.csv)에 있다. 이 구간은 반복말·같은 날의 상관을 반영한 회귀 구간과 다르다. [연도별 번호](raw_year_gate.csv), [함수율별 번호](raw_band_gate.csv), [연도와 함수율별 번호](raw_year_band_gate.csv)도 보존했다.

## 내측과 외측의 전체기간 비교

원시 비율은 관측값이고, 조정 차이는 같은 말·같은 경주 효과와 과거 동일거리 이력·부담중량·사건 당시 나이·성별·출전 경험·간격을 고려한 추정치다. 각 거리 전체기간의 함수율 구성을 모든 연도에 동일하게 적용했다. 양수는 내측 입상률이 높다는 뜻이며 단위는 %p다.

'''+table(['거리','경주','원시 내측','원시 외측','원시 차이 %p','조정 차이 %p','점별 95% 구간','BH q'],group_rows)+'''
800·900m의 전체기간 내측 우세는 경주 효과만 사용하는 분석과 과거 기록 변수를 제외한 분석에서도 방향이 유지됐다. 1000·1110m는 양수 추정이지만 이번 보수적 구간은 0을 포함했다. 1300·1400m는 제한표본, 1610m는 미추정이다. [모든 조정 결과와 민감도](adjusted_contrasts.csv)를 함께 확인한다.

이전 Top3 보고서는 경주 효과·개별 번호 모형과 날짜 군집 구간을 사용했다. 이번에는 말 고정효과를 추가하고 내측·중간·외측 그룹 및 연도·함수율 상호작용을 적합했으며 날짜와 말의 군집 공분산을 더했다. 따라서 이전 효과와 수치·구간이 달라질 수 있다. 이전 원본은 보존하고 최신 판단에서 불확실성을 확대했다.

## 외측의 실제 입상률이 높았던 연도

800·900m는 보유 모든 연도에서 원시 내측 입상률이 외측보다 높았고, 보고 가능한 연도별 조정 추정도 모두 양수였다. 800m의 2026년은 3경주뿐이라 연도별 조정 결과를 제시하지 않았다. 900m는 2024년 원시 차이가 +0.69%p로 작았고 2025년 +13.06%p, 2026년 부분기간 +2.85%p였다. 이 연간 변동을 입증된 효과 변화로 단정하지 않는다.

30경주 이상인 연도 중 외측 원시 입상률이 높았던 구간은 아래 네 개다.

'''+table(['거리','연도','경주','내측','외측','원시 차이 %p','함수율 조정 차이 %p','점별 95% 구간'],neg_rows)+'''
모두 조정 구간이 0을 포함한다. 1110m 2022년은 원시 비율에서 외측이 앞섰지만 조정값은 내측 방향으로 바뀌었다. 반대로 1000m·1110m의 2026년 부분기간은 원시 비율이 내측 방향인데 조정 추정은 각각 −0.77·−2.56%p다. 두 구간 모두 0을 포함하므로 어느 쪽 우세도 확정하지 않는다.

연도별 내외측 대비 37개에 BH를 적용했다. 개별 연도의 내측 우세로 q<0.05인 것은 800m 2019년 한 구간이었다. **외측 우세로 q<0.05인 연도는 없었고, 양쪽 연도의 반대 방향 우세·연도 간 변화·민감도 방향 일치를 함께 요구한 반전도 0개였다.** 전체기간의 800·900m 내측 연관성이 모든 연도에서 각각 유의하다는 뜻은 아니다. [연도 쌍 전체 변화](year_pair_changes.csv)와 [반전 판정](reversal_checks.csv)을 보존했다.

![연도별 실제 차이와 함수율을 고려한 조정 차이](annual_inner_outer.png)

회색은 실제 내측−외측 비율, 파란색은 함수율 표준화 및 경주·말 효과 조정값과 점별 95% 구간이다. [그림 PDF](annual_inner_outer.pdf)를 제공한다.

## 함수율에 따른 차이

아래는 각 함수율 구간을 거리별 전체기간의 같은 연도 구성으로 표준화한 내측−외측 차이다. 단위는 %p, 대괄호는 점별 95% 구간이다. 함수율 자체가 입상률을 높이는 효과가 아니라 **해당 함수율에서 내외측 차이가 얼마였는지**를 비교한다.

'''+table(['함수율','800m','900m','1000m','1110m','1200m'],band_rows)+'''
800m는 모든 함수율에서 내측 방향 추정이었다. 다만 함수율별 24개 대비에 BH를 적용하면 건조와 양호 두 구간에서 내측 우세 근거가 남고, 다른 구간의 크기는 불확실하다. 900m 역시 모든 함수율에서 내측 방향이지만 각각의 구간을 확정하지 못했다.

함수율 20% 이상에서 1000m는 −8.19%p(−21.71~+5.33), 1110m는 −6.83%p(−22.30~+8.65)로 외측 방향 추정이었다. 두 구간 모두 0을 포함한다. ‘비가 오거나 함수율이 높으면 외측이 유리해진다’는 규칙으로 채택할 근거는 부족하다. 실제 비율에서도 800m 2020년 다습 36경주는 외측이 0.93%p 높았지만, 이 한 구간을 우세 반전으로 해석하지 않는다.

연도와 함수율의 가산 상호작용 가정을 점검하려고 미리 고정한 2017~2020·2021~2023·2024~2026 부분기간 각각에서 함수율별 회귀를 별도로 적합했다. 46개 지원 구간 모두 BH 기준을 통과하지 못했다. 이 세부 분석은 같은 말이 해당 구간에서 여러 게이트에 출전한 정보가 적어 일부 구간의 추정과 구간이 매우 불안정했다. 선형확률모형의 구간은 ±100%p를 넘을 수 있으며 이런 값을 개별 말의 확률로 사용하지 않는다. 세부 셀의 불확실성 때문에 국소적인 반전을 배제할 수도 없다.

## 기간 및 함수율 조정의 범위

연도별 단순 분할만으로는 젖은 주로 경주 비중의 변화와 게이트 효과 변화를 구별하기 어렵다. 거리마다 경주·말 고정효과 선형확률모형에 내측·외측 지시변수, 연도×내외측, 함수율 구간×내외측을 함께 넣었다. 같은 경주의 함수율 주효과는 경주 고정효과에 흡수되지만, 함수율에 따라 내외측 차이가 바뀌는 항은 직접 추정했다. 중간 4~7번을 기준으로 사용했다.

모든 연도의 내외측 차이에 동일한 전체기간 함수율 비중을 적용해 구성 차이를 통제했다. 이는 연도별 변화와 함수율별 변화를 더하는 구조이며, 모든 연도×함수율 조합을 완전히 독립적으로 추정한 모형은 아니다. 관측되지 않은 조합도 이 가정으로 환산한다. 예컨대 800m 2018년에는 건조 표본이 없고 표준화 비중 27.8%, 900m 2018년에는 건조 표본이 없고 34.5%다. 이 연도 추정은 해당 부분의 외삽에 의존한다. [연도별 실제 함수율 지원](annual_moisture_support.csv)과 [고정 표준화 가중치](standardization_weights.csv)를 확인한다.

최소 30경주·20일 이상인 구간만 조정 결과를 공개했다. 100경주·40일 미만은 제한표본으로 표시한다. 전체 회귀에는 소표본 연도도 포함하되 해당 연도 추정치는 공개하지 않는다. 1300·1400m는 보고 가능한 연도가 하나도 없고 1610m는 전체도 미추정이다. 1300m 분석 표본은 2024년부터, 1400m는 2020년부터, 1610m는 2025년부터다. 2017년 시작이라고 이 거리들의 2017년 표본이 존재하는 것은 아니다.

기존 quality 추출을 재사용했으며 2026년은 9월 19일까지다. 400m는 2025·2026년 보유 시행 기록이 없어 과거 워밍업으로 남겼다. 같은 공식 말 ID·정확 거리의 T−2 이전 이력만 통제변수에 사용했고 제외 말은 재편입하지 않았다. 실제 경주 당시 원문 나이를 사용했으며 현재 2026년 고정 나이를 과거 나이로 설명하지 않는다.

날짜 군집 공분산과 말 군집 공분산을 교차항 차감 없이 더해 보수적으로 계산하고, 흡수한 고정효과의 잔여 자유도와 작은 군집 수의 t 임계값을 사용했다. 통제변수만 ridge 1로 수축하고 게이트·상호작용은 수축하지 않았다. BH는 전체기간·연도·함수율·시대와 함수율·연도 쌍 변화의 각 검정군에서 모든 지원 거리에 적용했다. 95% 구간은 동시 구간이 아닌 점별 구간이다.

## 연도별 전체 조정표

마지막 열은 해당 연도에 실제 관측되지 않은 함수율에 배정된 표준화 비중이다. 0%여도 각 세부 셀의 표본이 충분하다는 뜻은 아니다.

'''+table(['거리','연도','경주','원시 차이 %p','조정 차이 %p','점별 95% 구간','BH q','미관측 함수율 비중'],annual_rows)+'''
## 시대와 함수율별 세부 확인

최소 지원을 충족한 별도 회귀만 표시한다. 모두 탐색적 세부 연관성이며 새 독립 검증으로 세지 않는다.

'''+table(['거리','시대와 함수율','경주','일','조정 차이 %p','점별 95% 구간','BH q'],era_rows)+'''
## 저장과 검증

[분석 계획](PLAN.json)을 새 효과 추정 전에 고정했다. [실행 코드](analyze.py), [별도 재검산 코드](verify_plot.py), [입력 해시](source_manifest.json), [출전별 원천 연결](source_lineage.csv), [지원 및 보류](support.csv), [계수와 공분산](models.json), [검증](verification.json), [분자·분모·구간·군집 계산 재검산](calculation_verification.json)을 보존했다. 원천 집계 8종과 67모형의 대비·구간을 재검산하고, 7거리의 주 모형 군집 공분산을 별도 NumPy 누적으로 확인했다. 전체 희소 고정효과 연립식과 투영식의 계수 최대 차이는 9.36×10⁻¹¹이었다.

같은 말의 다른 게이트 출전도 무작위 실험은 아니며 시간에 따라 변하는 능력·기수·전개 등 잔여 교란이 남는다. 출발번호와 입상의 관찰 연관성이고 실제 주행 내외측 위치의 인과효과를 확정하지 않는다. 기존 자료를 반복 사용한 후향 연구다. 순위 연구에서 시간 환산률을 선택하지 않았고 DB·운영 모델도 변경하지 않았다. 결과는 [주제별 결론](../conclusions/01_GATE_LATERAL.md)에 연결했다.
'''
newtext('README.md',body)

decision={'question':'Top3 gate rates and temporal reversals considering moisture','period_end':'2026-09-19','field_n':10,'raw_negative_years_supported':[{'distance':int(dd),'year':int(yy),'races':int(r.races),'raw_inner_minus_outer_pp':float(r.difference_pp)} for (dd,yy),r in negative.iterrows()],
          'overall_inner_advantage_BH_distances':p[(p.kind=='overall')&(p.q_BH<.05)&(p.effect_pp>0)].distance.tolist(),
          'confirmed_temporal_reversals':int(rev.confirmed_reversal.sum()),'significant_outer_annual_contrasts':int(((annual.effect_pp<0)&(annual.q_BH<.05)).sum()),'absence_of_true_reversal_proven':False,
          'additive_year_band_interactions_assumed':True,'fixed_time_correction_changed':False,'operational_change':False,'causal_claim':False,'future_independent_validation':False}
jwrite(H/'decision.json',decision)

topic_doc=C/'01_GATE_LATERAL.md';oldtext=topic_doc.read_text();start=oldtext.index('## 最新') if '## 最新' in oldtext else oldtext.index('## 최신 초 단위')
intro='''# 제주 거리별 출발번호와 내외측 유불리

2026년 10월 8일 정리. **입상 연구의 최신 결과는 800·900m 전체기간 내측 우세, 함수율을 고려한 시기별 우세 반전은 미확인이다.** 시간 연구에서는 800m 내외측 차이가 재현됐으며 내측+0.10초·중간0초·외측−0.10초는 시험 예시다. 최적 보정률이나 확정 적용표로 채택하지 않았다.

## 최신 번호별 입상률과 시기 및 함수율 비교

2017~2026-09-19의 정상 완전순위·정확10두 3,930경주·39,300출전이다. 실제 입상률은 800m 내측34.94%·외측25.29%,900m33.86%·26.38%였다. 같은 말·같은 경주 효과, T−2 이전 이력 등과 연도×내외측·함수율×내외측을 함께 조정하고 동일 함수율 구성으로 표준화한 전체 차이는 800m+11.46%p(점별95%+7.91~+15.01),900m+7.39%p(+2.42~+12.37)로 BH 기준도 충족했다.1000·1110·1200m의 새 보수적 구간은0을 포함했다.1300·1400m는 제한표본,1610m는2경주로 미추정이다.

원시 비율에서 외측이 앞선 지원 연도는1000m2021·2023년,1110m2022년,1200m2023년이다. 함수율 및 말 효과를 고려한 차이는 모두0을 포함했다.800·900m는 원시 연간 비율과 보고 가능한 조정 추정 모두 내측 방향이었다.37개 연도 대비와 모든 연도 쌍 변화의 BH·민감도 조건을 충족한 반전은0개이며 실제 반전이 없음을 증명한 것은 아니다.800m2026년은3경주로 연도별 미추정이다.

함수율20% 이상에서1000m−8.19%p(−21.71~+5.33),1110m−6.83%p(−22.30~+8.65)로 외측 방향 추정이지만 불확실했다.800m는 모든 함수율에서 내측 방향이며 건조·양호의 BH 근거가 남았다.젖은 주로의 외측 가산 규칙을 채택하지 않았다.고정한3시대×함수율별46개 별도 모형도 불확실했다.

연도와 함수율의 가산 상호작용을 가정하며, 해당 연도에 없는 함수율도 모형으로 환산한다.800m2018년 건조 비중27.8%,900m2018년34.5%는 미관측 부분 외삽에 의존한다.세부 구간은 같은 말의 반복 출전이 적어 추정이 매우 불안정할 수 있다.관찰 연관성이고 실제 주행 위치의 인과효과가 아니다.입상률 차이를 초로 환산하거나 운영에 적용하지 않았다.

- [최신 번호별 실제 입상률과 전체 상세 보고서](../20261008_gate_top3_period_moisture_v1/README.md)
- [입상 횟수와 출전수](../20261008_gate_top3_period_moisture_v1/raw_gate.csv)
- [연도·함수율별 원시 번호 집계](../20261008_gate_top3_period_moisture_v1/raw_year_band_gate.csv)
- [조정 차이와 민감도](../20261008_gate_top3_period_moisture_v1/adjusted_contrasts.csv)
- [연도별 함수율 지원과 외삽 비중](../20261008_gate_top3_period_moisture_v1/annual_moisture_support.csv)
- [반전 판정](../20261008_gate_top3_period_moisture_v1/reversal_checks.csv)과 [재검산](../20261008_gate_top3_period_moisture_v1/calculation_verification.json)

'''
topic_doc.write_text(intro+oldtext[start:],encoding='utf-8')
readme=C/'README.md';txt=readme.read_text();txt=txt.replace('시간 연구에서도800m 내측 우세 재현.10두의 그룹 시험 예시+0.10·0·−0.10초,다른 거리와 개별 번호 고정치는 근거 부족','입상은800·900m 전체 내측 우세.함수율을 고려한 시기별 반전 미확인.시간은800m 그룹 시험 예시+0.10·0·−0.10초').replace('시간 연구 완료,시험 제안·확정 채택 구분','입상 시기·함수율 및 시간 연구 완료,확정 채택 없음');readme.write_text(txt,encoding='utf-8')
src=C/'SOURCES.md';txt=src.read_text();marker='\n같은 출전 자료가 여러 버전에';assert marker in txt
txt=txt.replace(marker,'\n| [20261008_gate_top3_period_moisture_v1](../20261008_gate_top3_period_moisture_v1/README.md) | **최신 게이트 입상률·기간·함수율 연구.번호별 실제 분자·분모,연도와 함수율 상호작용·말 및 경주 효과.800·900m 전체 내측 연관,시기별 외측 반전 확정 근거 부족.시간 보정 채택 변경 없음** |\n'+marker);src.write_text(txt,encoding='utf-8')
reg=json.loads((C/'research_register.json').read_text());topic=next(t for t in reg['topics'] if t['id']=='gate_lateral')
topic.update(latest_source='../'+H.name+'/README.md',latest_seconds_source='../20261008_gate_record_seconds_v1/README.md',status='top3_period_moisture_and_record_seconds_completed_no_fixed_correction_adopted',
             latest_top3_followup={'overall_inner_advantage_BH_distances':decision['overall_inner_advantage_BH_distances'],'supported_annual_contrasts':len(annual),'confirmed_temporal_reversals':0,'actual_reversals_ruled_out':False,'moisture_adjustment':'fixed_full_period_band_weights_additive_year_and_band_lateral_interactions','raw_negative_years_supported':decision['raw_negative_years_supported'],'source_rows':39300,'races':3930})
jwrite(C/'research_register.json',reg)

# Check every rendered raw gate cell against the numeric source, independent of prose.
for section,distances in zip(gate_tables,[[800,900,1000,1110,1200],[1300,1400,1610]]):
    lines=[ln for ln in section.splitlines() if re.match(r'\| \d+ \|',ln)];assert len(lines)==10
    for ln in lines:
        cells=[c.strip() for c in ln.strip('|').split('|')];k=int(cells[0])
        for dd,value in zip(distances,cells[1:]):
            actual=raw[(raw.race_distance_m==dd)&raw.horse_number.eq(k)].top3_pct.iloc[0];assert abs(float(value.rstrip('%'))-actual)<=.005001
links=0
for path in [H/'README.md',C/'01_GATE_LATERAL.md',C/'README.md',C/'SOURCES.md']:
    for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
        if '://' not in target:assert (path.parent/target.split('#')[0]).exists(),(path,target);links+=1
jwrite(H/'publication_verification.json',{'status':'passed','local_links_checked':links,'all_80_rendered_gate_rate_cells_verified':True,'prior_gate_seconds_and_top3_artifacts_unchanged':True,'figure_visual_review':'passed','management_previous_hashes':previous,'management_current_hashes':{key:sha(ROOT/key) for key in previous}})
art=[{'path':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(H.iterdir()) if p.is_file() and p.name!='artifact_manifest.json']
jwrite(H/'artifact_manifest.json',{'files':art,'total_bytes_excluding_this_manifest':sum(i['bytes'] for i in art),'local_links_checked':links})
files={i['path']:i for i in manifest['files']}
for key,item in files.items():
    if item['role']=='conclusion_or_management':item.update(sha256=sha(ROOT/key),bytes=(ROOT/key).stat().st_size)
for name in ['README.md','PLAN.json','analyze.py','verify_plot.py','publish.py','raw_gate.csv','raw_lateral.csv','raw_year_lateral.csv','raw_year_band_lateral.csv','adjusted_contrasts.csv','year_pair_changes.csv','reversal_checks.csv','annual_moisture_support.csv','support.csv','standardization_weights.csv','source_manifest.json','verification.json','calculation_verification.json','decision.json','publication_verification.json','artifact_manifest.json']:
    path=H/name;key=str(path.relative_to(ROOT));files[key]={'path':key,'role':'source_gate_top3_period_moisture','sha256':sha(path),'bytes':path.stat().st_size}
manifest['files']=list(files.values());manifest['verification'].update(local_links_checked=links,gate_top3_period_moisture_completed=True,gate_temporal_reversal_confirmed=False,prior_research_sources_unchanged=True)
manifest['managed_files_bytes_excluding_this_manifest']=sum(i['bytes'] for i in files.values() if i['role']=='conclusion_or_management');jwrite(C/'source_manifest.json',manifest)
assert all(sha(ROOT/i['path'])==i['sha256'] for i in manifest['files'])
print(json.dumps({'study_files':len(art),'study_bytes':sum(i['bytes'] for i in art),'links_checked':links,'confirmed_reversals':0,'all_central_hashes_verified':True},indent=2))
