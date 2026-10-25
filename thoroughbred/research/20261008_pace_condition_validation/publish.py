"""Korean report and publication assets from verified fixed predictions."""
from pathlib import Path
import json,os
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/horse_pace_condition_mpl')
import numpy as np,pandas as pd,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
H=Path(__file__).resolve().parent;O=H/'outputs';R=H.parent;ROOT=H.parents[2]
font=FontProperties(fname='/System/Library/Fonts/AppleSDGothicNeo.ttc');plt.rcParams['font.family']=font.get_name();plt.rcParams['axes.unicode_minus']=False
def table(df,cols,fmt=None):
    fmt=fmt or {};lines=['| '+' | '.join(cols.values())+' |','|'+'|'.join(['---']*len(cols))+'|']
    for _,r in df.iterrows():lines.append('| '+' | '.join(fmt[k](r[k]) if k in fmt else str(r[k]) for k in cols)+' |')
    return '\n'.join(lines)
def main():
    m=pd.read_csv(O/'condition_metrics.csv',dtype={'label':str});c=pd.read_csv(O/'standardized_contrasts.csv');cl=pd.read_csv(O/'class_metrics.csv',dtype={'label':str});co=pd.read_csv(O/'paired_comparisons.csv',dtype={'label':str});d=pd.read_parquet(O/'evaluation_rows.parquet');v=json.loads((O/'verification.json').read_text());assert v['passed']
    pct=lambda x:f'{100*x:.1f}%' if pd.notna(x) else '미산출';pp=lambda x:f'{100*x:+.2f}';integer=lambda x:f'{int(x):,}'
    selected=m[(m.model=='B')&m.group.eq('distance_m')].copy();selected['sort']=selected.label.astype(int);selected=selected.sort_values('sort')
    states=['건조','양호','다습','포화','불량'];mo=m[(m.model=='B')&m.group.eq('moisture_state')].set_index('label').loc[states].reset_index()
    bands=['1000~1300m','1400~1600m','1700m이상'];bm=m[(m.model=='B')&m.group.eq('distance_band')].set_index('label').loc[bands].reset_index()
    sup=d.groupby('distance_m').agg(n=('row_key','size'),races=('source_key','nunique'),supported5_rate=('supported5','mean'),valid_position5_mean=('valid_position5','mean')).reset_index();sup.to_csv(O/'history_support_by_distance.csv',index=False)
    disttable=table(selected,dict(label='거리(m)',n='출전',races='경주',accuracy='정확도',accuracy_lower='95% 하한',accuracy_upper='95% 상한'),dict(n=integer,races=integer,accuracy=pct,accuracy_lower=pct,accuracy_upper=pct))
    motable=table(mo,dict(label='함수율 상태',n='출전',races='경주',accuracy='정확도',accuracy_lower='95% 하한',accuracy_upper='95% 상한'),dict(n=integer,races=integer,accuracy=pct,accuracy_lower=pct,accuracy_upper=pct))
    matchedtable=table(c,dict(a='비교 조건',b='기준',matched_cells='공통 셀',coverage='표본 포함률',estimate='보정 차이(%p)',lower='95% 하한',upper='95% 상한',bh_q='BH q'),dict(matched_cells=integer,coverage=pct,estimate=pp,lower=pp,upper=pp,bh_q=lambda x:f'{x:.3f}'))
    overall=m[m.group.eq('all')];over=table(overall,dict(model='모형',n='출전',accuracy='정확도',brier='Brier'),dict(n=integer,accuracy=pct,brier=lambda x:f'{x:.6f}'))
    fore=cl[cl.class_id.eq(1)&cl.group.isin(['distance_band','moisture_state'])];foretable=table(fore,dict(label='조건',actual_n='실제 선입',predicted_n='선입 예측',correct_n='선입 적중',recall='선입 재현율'),dict(actual_n=integer,predicted_n=integer,correct_n=integer,recall=pct))
    intro='각질·구간 기록·편성을 이용한 초반 위치 예측에는 도움이 됐다. 최근5전 각질 빈도 H의44.46%에서 기수·조교사·교체 입력을 뺀 N은51.51%, 안팎 전원 확장 B는51.47%였다. B−H 정확도 차이는+7.00%p [6.48,7.53]이고 확률오차도 줄었다. 이 비교는 입력 묶음과 학습 방식 전체의 차이이며 개별 특징 하나의 효과가 아니다.'
    finding='거리별 관측 정확도는1000~1300m50.07%,1400~1600m52.05%,1700m이상53.63%였다. 공통 조건을 맞추면 중거리−단거리−0.66%p [-2.19,0.88],1700m이상−단거리+0.75%p [-1.45,2.95]로 차이가 불확실했다. 함수율별 관측 정확도는50.37~53.51%였으며 건조와의 네 상태 비교 모두 조건 일치 후95%구간이0을 포함했다. 거리·주로별 별도 모형이나 추가 보정의 개선이 입증된 결과는 아니다.'
    readme=f'''# 거리·함수율별 각질 예측 성능과 모델 활용

2026-10-08 · 연구28 후속28E · 서울·부산 · 평가2024~2025 · 연구 후보.

**{intro}**

{finding}

## 모델로 만들거나 기존 모델에 넣을 가치

이미28C/28D에서 초반200m 통과조 네 위치의 연구 모형을 만들었다. 선행은 첫 마군 전체, 선입은 그 밖의 마군 평균 상대위치1/3 이내, 중단은2/3 이내, 나머지는 후미다. 작전 의도·전체 주행경로·막판 추입 성공은 별도 목표다.

{over}

H는 이전28C에 저장된 최근5실제슬롯의 각질 빈도와 사전값을 이용한 기준 예측이고, N/A/B는28D의 고정 연도별 LightGBM이다. N157입력, A202입력, B297입력. N/A/B는 기수·조교사 식별자·성향·기수 교체 입력도 제외했다. 과거 말 기록 속 기수 영향까지 인과적으로 제거했다는 뜻은 아니다. B와 이전28C의 기준 B는 이름만 같고 다른 모형이므로 이번 문서의 B는28D 확장만 가리킨다.

N−H 정확도+7.04%p [6.52,7.57], Brier−0.067844 [-0.070674,-0.065014]. B−H는 정확도+7.00%p [6.48,7.53], Brier−0.068303 [-0.071155,-0.065451]. 거리3군·함수율5상태 모두 B−H 정확도와 Brier가 탐색 BH 후 개선 방향으로 남았다. 같은 기간에 측정한 동일 출전 쌍 비교다.

기존 전체 상대를 이미 반영한 N을 A/B로 더 확장한 효과는 훨씬 작다.28D의 A−N Brier−0.000502 개선과 B−A+0.000043 불확실 결론을 유지한다. 이번 B−A 정확도−0.02%p [-0.19,0.15], Brier95%구간[-0.000229,0.000315]. 전체정보가 유용하다는 결과를297입력이157입력보다 우수하다는 주장으로 바꾸지 않는다.

입상 모델에 연결하는 질문은 구분한다. [기존 연결 실험](../20261004_pace_finish_stack_v1/README.md)에서 직접 전개·게이트·기수·심사 이력 묶음 추가는 부산 삼복 상위6조합25.91→27.74%로 개선됐지만, 그 위에 당시 S1F/G3F 예측값을 추가하면 서울29.81→29.81%, 부산27.74→27.49%로 추가 개선이 확인되지 않았다. 그 모형은 이번 통과조 모형과 목표·기간·입력 범위가 다르다. 이번 새 네 확률을 현재 입상/운영 모델에 넣은 비교 학습은 하지 않았고, 그 개선은 미검증이다.

활용 후보는 출전마의 네 위치 확률과 과거 초반/막판·편성 정보를 함께 제공하는 것이다. 하나의 각질 이름으로 고정하기 전에 선입 문제를 보완하고, 입상 연결은 직접 입력 기준과 시간순 외부 예측 추가 후보를 같은 경주에서 비교해야 한다. 직접 정보와 예측값을 중복 가산하지 않는다. 별도 거리 모형·현재 함수율 추가·가중치 변경·운영 채택은 이번 결과로 확정하지 않았다.

## 거리별 결과

{disttable}

2200m8출전1경주,2300m58출전5경주는 안정적인 정확도로 읽을 수 없다.2200m은 경주일이1개여서 군집구간을 산출하지 않았다.2000m도762출전71경주로 구간이 넓다. 정확거리 전체와 지역별 결과는 [성능 원표](outputs/condition_metrics.csv)를 따른다.

1200m49.81%,1800m54.27%로 차이가 관측됐다. 서울은1200m48.92%/1800m53.00%, 부산은51.07%/55.52%였다. 연도별 거리군도2024년49.82/51.31/52.94%,2025년50.35/52.76/54.24%로 같은 순서였다. 그러나 같은 말·같은 등급/두수/지원의 거리 효과로 확정할 수 없다.

1000m613출전은 최근5슬롯 모두 유효 각질인 지원 표본이0%였고, 과거 유효 위치 평균은0.18전이었다. 반면1800m의 지원율90.69%,유효 위치 평균4.88전이다.1000m의37.85%를 거리 자체의 어려움이나 모든 신마의 정확도로 일반화하지 않는다. 이력 부족이 크게 섞인 관측이다. [이력 지원표](outputs/history_support_by_distance.csv).

## 주로 상태별 결과

실제 함수율을 사후 평가 조건으로 연결했다. 건조2~5%,양호6~9%,다습10~14%,포화15~19%,불량20%다. 기존 context의 함수율789결측도 API4_3 원문 track로 복구하여 전체36,638출전을 유지했다. 기존에 있던35,849개 함수율과 원문이 일치했다. 주로빠르기는 사용하지 않았다.

{motable}

불량이53.51%로 가장 높다고 비가 오면 더 잘 맞힌다고 말할 수 없다. 불량은2024년51.16%,2025년55.47%이고 표본도1,226출전119경주다. 다습은 서울49.59%/부산53.67%로 지역별 양상도 다르다. 원표에는 지역·연도·거리군×함수율 교차표를 모두 보존했다.

28D의 실제 경주 함수율은 원래 예측 입력에 없었다. 이번 층화 결과는 이미 만들어진 모형이 어떤 실제 상태에서 맞았는지를 확인한 것이며 현재 주로를 알고 예측한 성능이 아니다. T−2 예측시점에 실제 당일 함수율을 알 수 있다고 가정하지 않는다. [이전 함수율 실험](../20261003_pace_gate_moisture_v2/README.md)도 과거 전체기록의 함수율 환산 추가가 전개 순위를 더 개선했다는 근거는 얻지 못했다. 기록 비교의 환경 보정 가치와 현재 위치 예측 추가 가치는 구분한다.

## 공통 조건을 맞춘 차이

{matchedtable}

함수율 비교: 지역×정확거리×연도×등급×두수군(9이하/10~11/12이상)×최근5지원이 같은 셀. 거리군 비교: 지역×연도×등급×두수군×함수율 상태×지원이 같은 셀. 각 비교의 양쪽10출전·2경주 이상 셀만 포함하고 nA*nB/(nA+nB) 가중치로 셀 차이를 평균했다. 공통 표본에 한정한 기술적 표준화이며 전체 모집단 평균이나 인과효과가 아니다. 불량−건조 포함률21.51%로 특히 제한적이다. 두수군 안 잔여 차이·세부 능력·연령·현재 각질 구성·기수·작전 등은 남는다.

단순 거리군 차이+1.98/+3.56%p가 조건 일치 후−0.66/+0.75%p로 줄었다. 이력과 등급 등 표본 구성이 관측 차이에 기여한다는 해석과 맞지만 어느 변수 하나의 원인 비중을 분해한 결과는 아니다. 거리와 함수율 효과가 없다고 입증한 것도 아니다.6대비 BH q는 모두0.60이상이다.

## 선입 약점은 조건별로도 반복

{foretable}

실제 선입4,041건 중 최댓값 분류가 선입인 적중45건,재현율1.11%다. 전체 정확도51.47%와 네 클래스 재현율 평균43.50%를 함께 읽는다. 중단/후미 대 선행/선입의 두 범주 분류 정확도는75.13%지만 더 쉬운 다른 목표이므로 네 각질 정확도 개선처럼 표현하지 않는다. 선입 평균 확률10.56%와 실제 비율11.03%가 가까워도 각 말의 선입 확률이 교정됐거나 선입을 잘 식별한다는 증거는 아니다.

따라서 현재 후보는 큰 앞뒤 방향 설명에 활용 여지가 있고, 선행/선입을 세밀하게 고정하는 의사결정에는 약점이 있다. 순서형 위치 예측·앞뒤 단계 분류·확률 교정 등은 이후 비교할 후보이지 이번에 성능을 확인한 해결책은 아니다.

## 검증과 시점

평가2024년 모형은2023년까지,2025년은2024년까지 학습했다. 최근5/10실제슬롯·T−2·최대730일·전년까지의 환경 기준을 재사용한다. 이번에는 모형 재학습0개이며 실제 위치나 현재 함수율을 입력으로 다시 예측하지 않았다. 이미 이전 후속연구에서 사용한 평가기간이므로 미관측 미래의 새 검증 결과가 아니다. 역사적 명단 공표/정정시각은 미감사다. 유효 실제 각질이 있는 출전의 정확도이며 결측 정답을 후미로 메우지 않는다.

말·날짜·말날짜 점수합으로 이중 군집분산을 계산하며 단일 군집과 이중 군집 중 최대분산,t(최소군집수−1)의95%구간을 사용한다. 정확도 구간의0~1 밖 값은 자르지 않은 근사 구간이다. 작은 경주/날짜 표본은 별도 표시한다. 주 비교 전체3대비×2지표와 거리3군/상태5군×3대비×2지표는 별도 BH군이다. 공통 조건6대비도 별도 BH다. 자세한 계산 전 규칙은 [계획](PLAN.md)을 따른다.

독립 원문 경주/말 키 연결·SQL 평균/인원·원래 저장 확률 일치·다른 군집 집계·혼동표·공통셀/가중치·BH·이전 파일 보존 검증을 통과했다. 검사 {v['checks']:,}개,이전 공유 파일을 제외한 {v['prior_files_preserved']}파일 보존. [검증 JSON](outputs/verification.json). 운영/DB/웹 배포는 변경하지 않았다.

[출처](SOURCES.md) · [조건별 성능](outputs/condition_metrics.csv) · [각질별 성능](outputs/class_metrics.csv) · [혼동표](outputs/confusion_tables.csv) · [동일출전 차이](outputs/paired_comparisons.csv) · [공통조건 차이](outputs/standardized_contrasts.csv) · [공통 셀](outputs/standardized_cells.csv) · [게시요약](PUBLICATION.md) · [게시JSON](PUBLICATION.json) · [용량](outputs/SIZE_REPORT.md).

![거리와 함수율별 정확도](figures/condition_accuracy.png)

![조건을 맞춘 정확도 차이](figures/standardized_differences.png)
'''
    (H/'README.md').write_text(readme)
    summary=f'''# 거리·주로에 따라 전개 예측은 얼마나 달라지는가

{intro}

{finding}

기록은 우승확률이 아닌 출발200m 통과조 위치 확률로 읽는다. 네 위치 중 가장 큰 확률로 분류했을 때 선입 재현율은1.11%로 낮았다. 뒤쪽 두 범주를 함께 맞히는 정확도75.13%와 네 위치 정확도51.47%는 다른 목표다.

예를 들어1000m 정확도는37.85%,1800m54.27%였다. 그러나1000m 평가말의 최근5전 유효 각질 지원은0%,1800m90.69%로 차이가 컸다. 거리 자체 효과로 해석하지 않는다. 불량주로53.51%가 건조51.74%보다 높아 보여도 같은 조건 비교의 구간은0을 포함했다.

서울·부산2024~2025,36,638출전3,465경주4,405두의 기존 시간순 예측 재평가다. 실제 당일 함수율은 평가 조건으로만 사용했고 새로운 예측 입력으로 넣지 않았다. 현재 운영 입상 모델에 새 확률을 추가한 개선은 미검증이며 DB/운영/웹 배포는 유지한다.2200~2300m와 불량의 공통표본 제한을 표시한다.

[원 보고서](README.md) · [조건 원표](outputs/condition_metrics.csv) · [검증](outputs/verification.json).
'''
    (H/'PUBLICATION.md').write_text(summary)
    payload=dict(title='거리·함수율별 전개 예측 성능',followup='28E',status='research_candidate',evaluation_years=[2024,2025],n=len(d),races=d.source_key.nunique(),horses=d.horse_id.nunique(),accuracy_B=float(overall[overall.model.eq('B')].accuracy.iloc[0]),accuracy_H=float(overall[overall.model.eq('H')].accuracy.iloc[0]),distance_bands=bm[['label','n','races','accuracy']].to_dict('records'),moisture_states=mo[['label','n','races','accuracy']].to_dict('records'),standardized_differences=c[['group','a','b','coverage','estimate','lower','upper','bh_q']].to_dict('records'),fore_recall=45/4041,operational_change=False,models_refitted=0,current_moisture_is_input=False,new_finish_model_integration_tested=False)
    (H/'PUBLICATION.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    audit=json.loads((O/'source_audit.json').read_text());lines=['# 출처와 재현','', '입력은 기존 보존 자산을 읽기 전용으로 재사용했다. 원천 API4_3의 track는 실제 경주 함수율 확인용이고 사전 예측에 사용하지 않았다. 원문 말번호·날짜·경주번호·게이트·거리·지역을 검증했다. 파생 위치 정의와 이력 계약은28C/28D를 따른다.','', '| 경로 | 바이트 | SHA-256 |','|---|---:|---|']
    for r in audit['inputs']:lines.append(f"| [{r['path']}]({ROOT/r['path']}) | {r['bytes']} | {r['sha256']} |")
    lines+=['','구간 정의: S1F는 출발200m, G3F/G1F는 결승 전600/200m. 막판 겹치는 구간을 독립 능력으로 가산하지 않는다. 이번 목표는 S1F 통과조다. 함수율 층화는 실제 주로에서의 오차 진단이며 현재 주로를 넣은 비교 학습이 아니다.','', '코드: analyze.py(고정 예측 분석), verify.py(독립 검증), publish.py(보고서/그림), register.py(중앙 목록), record_inventory.py(자기 포함 용량).']
    (H/'SOURCES.md').write_text('\n'.join(lines)+'\n')
    fig,axes=plt.subplots(1,2,figsize=(13,5),layout='constrained')
    for ax,data,title in [(axes[0],selected[selected['sort'].le(2000)],'정확거리별 초반 네 각질 정확도'),(axes[1],mo,'실제 함수율 상태별 정확도')]:
        y=data.accuracy.to_numpy()*100;lo=data.accuracy_lower.to_numpy()*100;hi=data.accuracy_upper.to_numpy()*100;xx=np.arange(len(data));ax.errorbar(xx,y,yerr=np.array([y-lo,hi-y]),fmt='o',capsize=4,color='#245f82');ax.set_xticks(xx,data.label);ax.set_title(title);ax.set_ylabel('정확도 (%)');ax.grid(axis='y',alpha=.2);ax.set_ylim(30,65)
        for i,(_,r) in enumerate(data.iterrows()):ax.annotate(f'{r.accuracy*100:.1f}%\nn={int(r.n):,}',(i,r.accuracy_upper*100),xytext=(0,6),textcoords='offset points',ha='center',fontsize=8)
    fig.suptitle('서울·부산 2024~2025 저장 예측 · 모형 B · 말/날짜 군집95%구간',fontsize=14);fig.savefig(H/'figures/condition_accuracy.png',dpi=140);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,5),layout='constrained');y=np.arange(len(c));est=c.estimate.to_numpy()*100;lo=c.lower.to_numpy()*100;hi=c.upper.to_numpy()*100;ax.errorbar(est,y,xerr=[est-lo,hi-est],fmt='o',capsize=4,color='#245f82');ax.axvline(0,color='grey',linestyle='--');ax.set_yticks(y,[f'{r.a} - {r.b}' for r in c.itertuples()]);ax.invert_yaxis();ax.set_xlabel('공통 조건을 맞춘 정확도 차이 (%p) · 95%군집구간');ax.set_title('거리·주로 차이는 조건 일치 후 불확실\n각 비교 양쪽10출전·2경주 이상 공통 셀, 조화표본 가중');ax.grid(axis='x',alpha=.2);fig.savefig(H/'figures/standardized_differences.png',dpi=140);plt.close(fig)
    print('Published report, summary, JSON and two figures')
if __name__=='__main__':main()
