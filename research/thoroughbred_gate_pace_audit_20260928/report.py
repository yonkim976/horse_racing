"""Render the observed results, without refitting or selecting a model."""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import *

VENUE={'BUSAN':'부산','SEOUL':'서울'}
def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,r))+' |' for r in rows])+'\n'
def effect(v):return f'{v*100:+.2f}'
def interval(l,h):return f'{l*100:+.2f} ~ {h*100:+.2f}'

def main():
    a=pd.read_parquet(OUT/'adjusted_strata.parquet');q=pd.read_parquet(OUT/'quarter_effects.parquet')
    c=pd.read_parquet(OUT/'standardized_conditions.parquet');c=c[c.variant.eq('primary')&c.condition.ne('UNKNOWN')]
    s=pd.read_parquet(OUT/'sensitivity_quarters.parquet');pa=pd.read_parquet(OUT/'pack_outcome_associations.parquet')
    quality=json.loads((OUT/'quality.json').read_text());pq=json.loads((OUT/'passing_quality.json').read_text());raw=json.loads((OUT/'raw_rank_checks.json').read_text())
    fig,axs=plt.subplots(2,1,figsize=(13.5,8.5),sharex=True,constrained_layout=True)
    for ax,venue in zip(axs,['SEOUL','BUSAN']):
        z=q[q.venue.eq(venue)].sort_values('quarter');x=np.arange(len(z));y=z.standardized_effect.to_numpy()*100
        ax.axhline(0,color='#555',lw=1);ax.axhline(z.long_run_effect.iloc[0]*100,color='#667085',ls='--',lw=1,label='Long-run average')
        ax.errorbar(x,y,yerr=np.vstack([(z.standardized_effect-z.standardized_ci_low)*100,(z.standardized_ci_high-z.standardized_effect)*100]),fmt='none',ecolor='#a8b2c4',capsize=2,lw=1)
        ax.scatter(x,y,c=np.where(y>0,'#2563eb','#dc604e'),s=28,zorder=3)
        flag=z.period_candidate.to_numpy();ax.scatter(x[flag],y[flag],facecolors='none',edgecolors='#101828',s=80,lw=1,zorder=4,label='Differs from long-run, BH q < .05')
        ax.set_title(f'{venue} | outer minus inner: top-3 finish rate',loc='left',weight='bold');ax.set_ylabel('Percentage points');ax.grid(axis='y',alpha=.16);ax.set_ylim(-34,28)
        ax.spines[['top','right']].set_visible(False)
    labels=q[q.venue.eq('SEOUL')].sort_values('quarter').quarter.to_list();ticks=[i for i,v in enumerate(labels) if v.endswith('Q1')]
    axs[-1].set_xticks(ticks,[labels[i][:4] for i in ticks]);axs[-1].set_xlabel('Calendar quarter (2026 Q3 ends September 20)');axs[0].legend(loc='upper left',fontsize=8,frameon=False)
    fig.suptitle('Gate advantage changes across periods',fontsize=17,weight='bold')
    fig.savefig(OUT/'quarter_gate_effects.png',dpi=180);plt.close(fig)

    parts=['# 서울·부산 게이트와 통과조 관찰 분석 — 2026-09-28\n',
    '**결론: 장기 평균은 내측 게이트 우세지만, 거리와 기간을 함께 보아야 한다. 부산 1600m는 장기 평균에서 외측 우세이고, 부산에서는 같은 거리 구성으로 비교해도 외측 우세 분기와 내측 우세 분기가 번갈아 나타났다. 서울 역시 기간 차이가 있었다. 이 결과는 주로·전개 연구를 계속할 근거이며, 특정 말의 확률을 그대로 올릴 수 있는 가중치는 아니다.**\n',
    '사용자 요청에 따라 예측모델을 바꾸기 전에 현재 보유 자료만 진단했다. 운영 DB는 읽기 전용으로 조회했고, 기존 A/B/C 모델·운영 확률·모델 등록부를 수정하지 않았다. 외부 자료는 통과조 기호 해석을 위한 KRA 공식 설명만 참고했다.\n',
    '**대상과 수치의 의미**\n',
    '서울 2017-01-07~2026-09-20의 9,506경주·102,421두 출전, 부산 2017-01-06~2026-09-18의 6,727경주·73,345두 출전을 분석했다. 출전취소/제외를 제거한 뒤 6두 이상, 전원 정상 완주, 1~N위가 중복 없이 완성된 경주만 썼다. 동착·순위 불완전 229경주 및 비정상/누락 결과 74경주는 제외했다. 사고·동착 경주까지 포괄한 결과가 아니다.\n',
    '입상은 **최종 1~3위**다. 출전 게이트 순서를 내측·중간·외측으로 3등분하고 각 경주에 같은 비중을 주었다. DB 게이트 값은 이 표본에서 마번과 전부 같고, dacom11 적재 코드도 마번을 gate_number로 넣는다. 실제 출발대 이동이나 취소 후 물리적인 빈 칸의 처리까지 독립 관측한 것은 아니다. 따라서 엄밀히는 **등록된 출발번호 기준 비교**다.\n',
    '표의 차이는 모두 **외측−내측 입상률, 단위 %p**다. 음수는 내측 우세, 양수는 외측 우세다. 이는 집단 간 관측 차이이며 모델의 예측 확률 또는 인과효과가 아니다. 레이팅·부담중량·나이·직전 날짜까지 최근 5회 성적/입상/초반위치·출전 경험·출전 간격을 보정했고 경주별 고정효과를 사용했다. 기수·마방·마체중 등 모든 차이를 통제한 것은 아니다. 괄호의 95% 구간은 경주일 단위 군집 오차를 반영한 개별 구간이며 동시 신뢰구간이 아니다.\n',
    '**전체와 거리별 차이**\n']
    overall=a[a.scope.eq('all')&a.target.eq('top3')]
    parts.append(table(['장소','경주 수','보정 차이(%p)','95% 구간','해석'],[[VENUE[r.venue],r.races,effect(r.effect),interval(r.ci_low,r.ci_high),'내측 우세'] for r in overall.itertuples()]))
    dist=a[a.scope.eq('distance')&a.target.eq('top3')]
    parts.append(table(['장소','거리(m)','경주 수','보정 차이(%p)','95% 구간'],[[VENUE[r.venue],r.level,r.races,effect(r.effect),interval(r.ci_low,r.ci_high)] for r in dist.itertuples()]))
    parts.append('서울·부산 1000m는 내측 우세가 약 10%p로 크다. 반대로 부산 1600m는 외측이 +7.43%p(95% +5.22~+9.65) 높았다. 추가 거리×상태 비교에서도 부산 1600m 외측 우세는 건조 +6.19, 양호 +9.06, 다습 +16.00%p에서 관측됐고, 포화는 +2.40%p이나 구간이 0을 포함했다. 거리별 출발 구조 등이 가능한 설명이지만 이번 분석으로 물리적 원인을 확정하지 않았다.\n')
    parts.append('개별 번호도 단순히 작을수록 좋지는 않았다. 1~12번이 모두 출전한 12두 경주만 비교한 추가 분석에서 부산 3번은 1번보다 입상률 +4.34%p(95% +1.79~+6.88, 탐색적 q=.0038) 높았다. 서울 12번은 1번보다 −7.40%p(95% −10.17~−4.63)였다. 이 비교는 부산 2,324경주·서울 2,497경주에 한정된다. 출전 두수가 다른 절대 번호별 단순 입상률은 별도 보존했지만 서로 동일 조건인 것처럼 비교하지 않았다.\n')
    parts.append('외측의 S1F 상대순위는 내측보다 서울 14.24%p, 부산 9.27%p 뒤였다. S1F 상대순위는 `(초반순위−1)/(출전두수−1)`이므로 초 단위 기록이나 최종 입상률 차이와 다르다. 부산 1600m에서는 이 차이가 1.59%p로 작았다. 게이트와 초반 자리잡기의 연관성이 있고, 초반 자리와 최종 결과의 관계는 거리별로 달랐다.\n')
    parts.append('**주로 상태: 건조와 포화를 같은 게이트 효과로 취급하면 안 된다**\n')
    parts.append('아래는 게이트×분기, 게이트×거리, 게이트×주로 상태를 함께 고려하고 각 장소의 전체 기간 거리·분기 구성에 표준화한 결과다. 단순 상태별 비교와 다르며, 모든 거리에서 상태 효과가 같다는 가정이 들어간다.\n')
    parts.append(table(['장소','주로 상태','보정 차이(%p)','95% 구간','건조 대비 변화(%p)','건조 대비 탐색적 q'],[[VENUE[r.venue],r.condition,effect(r.effect),interval(r.ci_low,r.ci_high),effect(r.vs_dry_effect),f'{r.vs_dry_q_within_variant:.3f}'] for r in c.itertuples()]))
    parts.append('서울 건조에서는 내측 +5.52%p, 포화에서는 내측 +0.84%p였다. 포화−건조 변화는 외측 방향 +4.68%p이고, 상태 비교의 다중검정 보정 후에도 차이가 남았다(q=.0239). 그러나 포화 자체의 외측−내측 구간은 −3.47~+1.79%p로 0을 포함한다. **내측 우세가 약해지는 것과 외측 우세가 확정되는 것은 다르다.** 부산 상태 차이는 이번 표본과 보정에서 명확하게 확정되지 않았다. 불량까지 일관되게 외측에 유리해지는 단순 함수도 관측되지 않았다.\n')
    parts.append('**기간 한정 차이: 일부 분기는 장기 평균과 크게 달랐다**\n')
    parts.append('효과를 보기 전에 2017Q1~2026Q3의 달력 분기를 고정했다. 분기별 거리·주로 구성 차이를 보정하고, 각 분기의 차이가 장기 평균과 다른지 서울·부산 총 78개 검정을 함께 보정했다. 50경주·20경주일 이상 및 BH q<.05를 탐색적 후보 기준으로 삼았다. 서울 10개·부산 13개 분기가 후보였다. 아래는 방향과 크기를 설명하기 위한 일부 사례이며 전체 78개는 뒷부분에 공개했다. 후보 선택 뒤의 크기는 과대평가될 수 있으므로 미래에 같은 차이가 재현된다고 가정하지 않는다.\n')
    chosen={('BUSAN','2019Q1'),('BUSAN','2022Q2'),('BUSAN','2024Q3'),('BUSAN','2025Q1'),('SEOUL','2025Q1'),('SEOUL','2026Q1')}
    z=q[[ (v,k) in chosen for v,k in zip(q.venue,q.quarter)]]
    parts.append(table(['장소','분기','경주/일수','표준화 차이(%p)','95% 구간','장기 평균 대비 q'],[[VENUE[r.venue],r.quarter,f'{r.races}/{r.days}',effect(r.standardized_effect),interval(r.standardized_ci_low,r.standardized_ci_high),f'{r.deviation_q:.3g}'] for r in z.itertuples()]))
    parts.append('부산 2019Q1·2022Q2·2025Q1은 외측 우세, 2024Q3은 강한 내측 우세였다. 서울 2025Q1·2026Q1도 강한 내측 우세였다. 공통 거리 1200·1300·1400m만 남기거나, 8두 이상에서 안쪽 3개/바깥쪽 3개 번호로 바꿔도 이 여섯 사례의 방향과 장기 평균 대비 유의성이 유지됐다. 특정 하루씩을 빼는 단순 평균 점검에서도 방향이 바뀌지 않았다. 다만 두 방법은 같은 자료를 다시 나눈 것이므로 독립 재현 검증은 아니다.\n')
    parts.append(f'![분기별 게이트 차이]({OUT}/quarter_gate_effects.png)\n')
    parts.append('그래프에서 0 위는 외측 우세, 0 아래는 내측 우세다. 세로선은 개별 95% 구간, 검은 테두리는 장기 평균과 차이가 있는 탐색적 분기다. 이 분기의 시작일/종료일이 실제 주로 편향의 시작/종료일이라는 뜻은 아니다.\n')
    parts.append('최근 2026Q3(9월20일까지)는 서울 −4.28%p(95% −11.23~+2.68), 부산 −4.18%p(−13.16~+4.80)였다. 둘 다 구간이 0을 포함하고 장기 평균과의 뚜렷한 차이도 없다. **과거 특정 분기의 큰 차이를 현재 편향으로 이어서 적용할 근거는 부족하다.** 실제 출발시각은 전부 비어 있으므로 특정 오후 시간대 효과는 판정하지 않았다. 경주번호 1~3/4~6/7이상으로 나눈 장기 평균은 두 장소 모두 내측 방향이었지만, 이는 시간대별·일자별 효과 검정의 대체물이 아니다.\n')
    parts.append('**전개 원문: 게이트와 실제 상대 주행위치를 분리할 수 있다**\n')
    parts.append('KRA 공식 설명에 따르면 통과조의 괄호 안은 1마신 미만 간격의 무리이며, 안쪽에 있는 말부터 번호를 적는다. 이는 해당 무리 내부의 상대 위치다. 레일에서 몇 m 떨어졌는지, 몇 번째 절대 라인인지, 실제로 몇 m 더 달렸는지는 알 수 없다. [한국마사회 공식 통과조 설명](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1).\n')
    parts.append('실제 부산 2024-09-01 1경주의 원문은 S1F `4,(2,5,6),(1,7,12),(8,9),(3,11)`, G1F `4-(8,2)=(1,5,9),(3,7)=(6,11),12`였다. 8번은 초반 9위에서 G1F 2위, 최종 1위로 올라왔다. G1F의 `(8,2)`는 그 무리 안에서 **8번이 2번보다 내측**이었다는 뜻이다. 번호가 바깥쪽이라는 이유만으로 경주 내내 외곽을 주행했다고 볼 수 없다. 이 사례만으로 주로 유불리를 판단하지 않는다.\n')
    parts.append(f'원문 표본 4경주·{pq["raw_source_samples"]}개 통과 지점을 DB와 대조해 공백을 제외한 원문이 모두 일치했다. 전체 대상 통과조 {pq["counts"]["eligible_point_rows"]:,}행 중 문법과 출전마 연결이 완전한 {pq["counts"]["parsed_and_roster_verified"]:,}행({pq["counts"]["parsed_and_roster_verified"]/pq["counts"]["eligible_point_rows"]:.2%})을 사용했다. 해석하지 않은 `·` 등의 표기 1,592행과 출전마 집합 불일치 396행은 분석에서 제외하고 원문·이유를 남겼다. 이는 모두 원천 오류라는 뜻은 아니다. 이미 제외된 경주마, 특수 상태 등 추가 확인이 필요하다.\n')
    parts.append('초반에는 내측 번호 말이 자기 무리의 가장 내측에 있었던 비율이 서울 60.25%, 부산 59.21%였다. 외측 번호 말이 가장 외측에 있었던 비율은 서울 58.90%, 부산 59.14%였다. 나머지에는 단독 주행 및 무리 중간 위치도 포함된다. G1F에서는 이 관계가 약해졌다. 출발번호와 주행위치는 연관되지만 동일한 값이 아니다.\n')
    parts.append('각 지점에서 **같은 무리의 가장 외측 말−가장 내측 말**의 최종 입상 여부를 짝지어 비교했다. 아래는 능력 보정 없는 후향적 위치 연관성으로, 앞의 게이트 보정 효과와 직접 같은 수치로 비교하면 안 된다.\n')
    parts.append(table(['장소','지점','경주 수','짝 수','입상률 차이(%p)','95% 구간'],[[VENUE[r.venue],r.point,r.races,r.pairs,effect(r.difference),interval(r.ci_low,r.ci_high)] for r in pa.itertuples()]))
    parts.append('S1F에서는 같은 무리의 내측 말이 최종 입상률 약 2.40%p 높았다. 반면 G1F에서는 외측 말이 서울 +7.93%p·부산 +3.79%p 높았다. **이 반전은 외측 주로의 물리적 우세를 증명하지 않는다.** 기수의 진로 선택, 안쪽의 혼잡, 외측 추월, 남은 힘 등 경주 진행의 결과가 위치에 섞인다. 이번 경주의 실제 G1F 위치를 그 경주의 사전예측 입력에 넣으면 시점 누수다.\n')
    parts.append('**확인 범위와 다음 작업**\n')
    parts.append('이번에 확인한 것은 ① 번호·초반 자리·결과의 연관성, ② 거리별 차이, ③ 상태와 기간에 따른 차이다. 아직 확정하지 않은 것은 ① 주로 안쪽/바깥쪽 표면 자체의 인과효과, ② 모래 보충·정비가 변화의 원인인지, ③ 특정 시간대만의 편향, ④ 이 변수가 예측 적중률을 얼마나 높이는지다. 같은 날 주로 전체가 빨라진 효과는 경주 내 비교에서 공통으로 제거되지만, 주로 속도 보정 연구의 계수를 이번 입상률에 더하지 않았다. 기존 기록 보정과 중복 보정하지 않아야 한다.\n')
    parts.append('다음 단계는 현재 자료를 날짜순으로 다시 재생하여, **그날 이전 경주만으로** 거리×게이트 기본 성향과 최근 기간의 편향을 얼마나 빨리 파악할 수 있었는지 확인하는 것이다. 통과조는 같은 무리의 상대 내외측, 앞선/중간/뒤 무리, 초반에서 종반까지의 이동을 과거 경주 이력으로 만들 수 있다. 현재 경주에는 과거 초반능력·게이트·선행 경쟁에서 예상한 전개만 넣어야 한다. 표본이 적은 최근 상태는 장기 평균 쪽으로 완화해야 하며, 전체 자료로 얻은 분기 효과를 해당 분기 과거 예측에 넣어서는 안 된다. 이 진단을 마친 후에야 기존 모델 단독 대비 추가 변수의 시간순 외부 평가를 진행할 수 있다. 새 주간 자료를 기다리지 않고 현재 보유 이력에서 수행 가능하다.\n')
    parts.append('**재현과 검증**\n')
    parts.append(f'`PROTOCOL.md`·원 분석 코드의 SHA-256을 효과 분석 전에 고정했다. `sensitivity.py`와 `cross_checks.py`는 1차 결과를 확인한 뒤 추가한 탐색적 견고성 점검이며 사전등록 검증으로 표현하지 않는다. 기본 계약 테스트 4개가 통과했고, 모든 과거 이력 날짜가 대상 날짜보다 앞서는지, 원천 키 중복/순위 완결성, 회귀 대비값의 추정 가능성을 확인했다. 추가 적합의 수치상 추정 불가능 성분은 최대 2.7e−12 이하였으며 원 분기 결과를 1e−9 이내로 재현했다.\n')
    parts.append(f'독립 정규식으로 원문 첫 성적표에서 추출한 {raw["checked_races"]:,}경주·{raw["checked_entries"]:,}두의 마번/최종순위를 분석 자료와 대조해 모두 일치했다. 각 장소·분기의 첫/마지막 날짜를 정했으나 2025~2026년 해당 날짜의 로컬 dacom11 원문 파일 28개는 없어 이 대조에서 제외했다. 따라서 최신 결과 전수를 원문과 재검증했다고 주장하지 않는다. 주로상태 미상 서울 16경주는 회귀에서 별도 범주로 유지했으나 상태 유불리로 해석하지 않았다.\n')
    parts.append('과거 성적 이력은 2015년 이후 DB 기록부터 누적했으므로 그 이전 출전 경험은 잘릴 수 있다. 레이팅은 서울 77,395/102,421두·부산 55,182/73,345두에서 관측됐다. 결측 여부를 통제했으나 결측 값을 완전한 능력 정보로 복구한 것은 아니다. 표준오차는 경주일 군집 기준이므로 장기간 반복 출전마·마방 효과와 미관측 요인의 불확실성이 모두 해결됐다고 볼 수 없다.\n')
    parts.append('코드 실행 순서: `build.py → analyze.py → passing_analysis.py → sensitivity.py → cross_checks.py → report.py → verify.py`. 환경은 프로젝트 `.venv/bin/python`, `OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1`이다. 당시 추출 자료와 원천 배치 해시를 보존했으므로 DB가 나중에 갱신돼도 보존된 표본에서 재분석할 수 있다. 전체 산출물과 보고서 해시는 최종 `manifest.json`에 기록한다.\n')
    parts.append('**전체 분기 표**\n\n장기 평균 대비 q는 “이 분기가 평소와 다른가”에 대한 값이다. 표준화 효과가 0보다 큰지/작은지에 대한 검정과 다르다. `후보`는 아래 사전 기준을 만족한 탐색 결과이고, 2026Q3은 불완전 분기다.\n')
    parts.append(table(['장소','분기','경주/일수','차이(%p)','95% 구간','장기 평균 대비 q','후보'],[[VENUE[r.venue],r.quarter,f'{r.races}/{r.days}',effect(r.standardized_effect),interval(r.standardized_ci_low,r.standardized_ci_high),f'{r.deviation_q:.4g}','예' if r.period_candidate else '—'] for r in q.itertuples()]))
    report=ROOT/'docs/THOROUGHBRED_GATE_PACE_BIAS_REVIEW_2026-09-28.md';report.write_text('\n'.join(parts))
    print(report)

if __name__=='__main__':main()
