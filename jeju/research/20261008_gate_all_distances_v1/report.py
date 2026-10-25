"""Human-readable extension report and standalone uncertainty figure."""
import json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def md(df,formats=None):
    formats=formats or {};lines=['| '+' | '.join(map(str,df.columns))+' |','| '+' | '.join('---' for _ in df.columns)+' |']
    for _,r in df.iterrows():
        vals=[]
        for c,v in r.items():
            if pd.isna(v):v='—'
            elif c in formats:v=formats[c].format(v)
            elif isinstance(v,(float,np.floating)):v=f'{v:.3f}'
            vals.append(str(v))
        lines.append('| '+' | '.join(vals)+' |')
    return '\n'.join(lines)
def main():
    a=pd.read_csv(HERE/'lateral_contrasts.csv');n=pd.read_csv(HERE/'number_effects.csv');support=pd.read_csv(HERE/'support.csv');raw=pd.read_csv(HERE/'raw_lateral_rates.csv')
    main=a[(a.period=='2019_2025')&(a.target=='top3')&(a.contrast=='inner_minus_outer')].copy()
    table=main[['distance','ten_runner_races','days','effect','ci_lo','ci_hi','q_BH','status']].rename(columns={'distance':'거리m','ten_runner_races':'10두 경주','days':'일수','effect':'내−외 Top3 %p','ci_lo':'95%하한','ci_hi':'95%상한','q_BH':'확장 BH q','status':'지원 상태'})
    comparisons=a[(a.contrast=='inner_minus_outer')&(a.target=='top3')].pivot(index='distance',columns='period',values='effect').reindex(columns=['2019_2025','2024_2025','2026_partial','historical_2017_2018']).reset_index().rename(columns={'distance':'거리m','2019_2025':'2019~2025','2024_2025':'2024~2025','2026_partial':'2026 부분','historical_2017_2018':'2017~2018 과거층'})
    tt=a[(a.period=='2019_2025')&(a.target=='time')&(a.contrast=='inner_minus_outer')][['distance','effect','ci_lo','ci_hi','q_BH']].rename(columns={'distance':'거리m','effect':'내−외 시간초','ci_lo':'95%하한','ci_hi':'95%상한','q_BH':'확장 BH q'})
    numbers=n[(n.period=='2019_2025')&(n.target=='top3')].pivot(index='number',columns='distance',values='effect').reset_index().rename(columns={'number':'번호'})
    rawt=raw[raw.period=='2019_2025'].pivot(index='distance',columns='lateral',values='top3_rate')*100;rawt=rawt.reset_index().rename(columns={'distance':'거리m','inner':'내측 원시입상률%','middle':'중간 원시입상률%','outer':'외측 원시입상률%'})
    groups=[]
    for (dist,period),g in a[(a.target=='top3')&a.contrast.isin(['inner_minus_middle','outer_minus_middle'])].groupby(['distance','period']):
        if period!='2019_2025':continue
        ix=g.set_index('contrast');groups.append({'거리m':dist,'내측−중간 %p':ix.loc['inner_minus_middle','effect'],'중간 기준 %p':0.,'외측−중간 %p':ix.loc['outer_minus_middle','effect']})
    text=f'''# 제주 모든 거리 출발번호 내·중·외측 확장 결과

2026-10-08. **추가 거리 중800·900m에서 내측 번호의 입상·시간 우세 연관성이 뚜렷했다.1200m는 불분명하고,1300·1400m는 큰 내측 방향 추정이 있으나 표본이 제한적이다.1610m는 미추정이다.** 운영 모델/보정률/DB는 변경하지 않았다.

## 범위와 계산

기존 품질 뷰 추출본, 상한2026-09-19, 정상 완전순위·정확10두·마번1~10. 내측1~3/중간4~7/외측8~10으로 고정했다. 기존1000/1110m와 같은10번호 회귀를 거리별로 적합하고 같은 경주 안에서 과거 정확거리 기록·나이·중량·성별·관측경력·출전간격을 조정했다. 이력은 사건일T−2까지이며 현재 프로필의2026 고정나이를 사용하지 않았다. 기수·심판·tempo·시장·영상·현재 실제 주행위치 제외.

원천ID·payload SHA는 `source_lineage.csv`에 연결했다. 기존features의1000/1110m 제한만 새 코드에서 제거했고 동일거리의 피처·기존 번호 계수가 재현됨을 확인했다. 모든 거리를 한 계수로 합치거나 희소 거리에 다른거리 효과를 빌려주지 않았다.

## 주 기간2019~2025: 내측−외측 Top3 차이

양수는 내측 입상 우세 방향이다. %p는 확률의 퍼센트포인트 차이이며 상대증가율이나 초가 아니다. 구간은 날짜 cluster 점별95%이고 미측정 능력/배정/선택 영향이 남는 관찰 추정이다.

{md(table,{'내−외 Top3 %p':'{:+.2f}','95%하한':'{:+.2f}','95%상한':'{:+.2f}','확장 BH q':'{:.4g}'})}

800m는762경주/454일에서+10.41%p(95%+7.74~+13.08),900m는508경주/378일에서+8.21%p(+4.73~+11.69)로, 기본 지원과 확장 탐색 다중비교 조건을 갖춘 관찰이다.800m는내−중+5.52/외−중−4.89%p,900m는+5.02/−3.19%p다.800m 내·중·외의 세 대조는 모두 확장BH q<0.05,900m는내−중과내−외가 남고외−중은q약0.073이다. 세 위치의 확정 순위를 과도하게 일반화하지 않는다.

1200m는+1.72%p(−3.41~+6.85)로 명확한 내외측 차이를 확인하지 못했다.1300m+13.79%p는32경주/32일,1400m+16.61%p는57경주/57일이라 큰 점추정에도 제한표본으로 표시한다.1400m의 주 기간BH q<0.05 결과는 표본지원이 충분하거나 미래에도 같은 크기라는 뜻이 아니다.

400m는2019+ 자료가 없어 주 표를 비웠다.1610m는주 기간10두1경주로 최소추정30경주/20일을 충족하지 않아NULL이다. 기본지원100경주/40일/2개년 기준도 통계적 충분성을 보장하지 않는다.10두 이외의 자료는 `all_field_support.csv`에 따로 보존했다.

## 중간 번호를 기준으로 본 세 위치

아래는 조정 차이이며 각 집단의 절대 입상확률이 아니다.

{md(pd.DataFrame(groups))}

## 기간별 변화: 동일한 내−외 Top3 %p

{md(comparisons)}

- 800m:2024~2025에도+11.65%p(95%+5.78~+17.52), 확장BH q약0.0010.2026은10두3경주라미추정이고 최신유불리의 지속을 검증하지 못했다.
- 900m:2024~2025+9.09%p(+3.15~+15.02), q약0.016.2026부분82경주/54일에서는+2.77%p(−4.77~+10.31)로 작아지고 불확실하다.2026의 시간차이도 내측 빠름 방향이 남지 않았다. 과거 우위를 고정적인 현재 가산점으로 쓰지 않는다.
- 1200m:최근 완결+0.96%p(−5.32~+7.23),2026부분+5.54%p(−5.04~+16.12)로 모두 불확실하다.
- 1300m:주 기간과최근 완결의32경주는 **같은 표본**이다. 두 표의 같은 수치는 독립 재현이 아니다.2026은15경주라미추정이다.
- 1400m:최근 완결31경주에서+13.85%p(−0.59~+28.29)로 구간이0을 포함하며2026은6경주뿐이다.
- 400m:2017~2018 과거층82경주/76일에서+16.02%p(+4.33~+27.71). 시대가 다르고100경주 기본지원 미달이라 현대 제주 거리 효과로 일반화하지 않는다. 과거`제1`을현재`제1등급`으로 합치지 않았다.
- 1000/1110m도2026부분 결과를 모두 남겼다.1110m의2026부분 내−외는−0.21%p(−8.02~+7.61)로 뚜렷하지 않다. 주/최근 기간의내측방향을 항상 유지된다고 표현하지 않는다.

주/최근/부분연도는 겹치는 개발자료다.2026도 이미 관찰한 후향 자료이며 새로운 미래 독립검증이 아니다.

## 전체시간 차이

음수는 내측이 외측보다 빠른 방향이다. Top3 차이에서 환산한 값이 아니라 별도 시간 회귀의 결과다.

{md(tt,{'내−외 시간초':'{:+.3f}','95%하한':'{:+.3f}','95%상한':'{:+.3f}','확장 BH q':'{:.4g}'})}

800m 내측은 약0.371초,900m는0.221초 빠른 방향이며 두 구간이0을 포함하지 않는다. 최근2024~2025도 각각0.454초/0.442초 빠른 방향이다.1200m는약0.024초로 불확실하다.1300/1400의 시간 추정은 작은표본이라는 제한을 그대로 유지한다. 시간 관찰 차이가 입상 예측 개선을 입증한 것도 아니며 이 초를 과거기록에 적용하지 않았다.

## 번호별 Top3 효과와 원시 비율

10번호 전체평균 대비 조정 차이(%p)다. 번호별 최고·최저는 점추정이며 확정 순위가 아니다. 각번호95%구간/반복말 cluster 구간/전체번호 다중비교 q는 `number_effects.csv`에 있다.1300/1400열은제한표본이다.

{md(numbers)}

800m는1~3번이평균보다높고8~10번이낮은 형태,900m도비슷한모양이다.1200m는10번의점추정이높고5~6번이낮아 단순한 내측→외측 단조형태가 아니다. 이런 번호별 요철을 확정적인 편향 규칙으로 만들지 않는다.

원시입상률은 다음과 같고, 위 조정효과와 모집단은 같지만 말구성 통제 여부가 다르다. 각경주당내측3두/중간4두/외측3두이며 정확분모는 `raw_lateral_rates.csv`의 starts다.

{md(rawt)}

## 다중비교·모형 한계와 판단

주 기간의BH family는추정가능7거리×3대조×2정답=42개,최근완결42개,2026부분24개,400과거층6개다. 번호별family는각각140/140/80/20개다. 원 연구1000/1110만의12개 대비와family가달라q값도달라진다. **BH는같은family의p값분포에도의존하므로,검정수가늘어도항상q가커지지는않는다.**1000/1110의점추정·점별구간은기존과같고,이번확장family에서의q변화를새데이터로기존효과가강해진것처럼표현하지않는다. 가족별전체결과를보존했고유리한family만선택하지않는다.

날짜cluster구간은과거능력과선형사양/정규화/Ridge축소를고정한근사구간이다.반복말cluster민감도도별도로보존했으나모든미측정오차를포괄하지않는다.부담중량등당시가용성은기존회고가정이며,이력이없다는것을실제경력0/신마/능력0으로취급하지않았다.현재원문시간의빠르거나느린정답을추가로절단/삭제하지않았다.

실제물리게이트와번호의대응,경주중주행위치/레일거리,번호배정의외생성은미확정이다.정상완주사후선택모집단의연관성이라취소/DNF/동착을포함하는운영전체의인과효과로읽지않는다. **800·900m는거리별번호입력의예측가치를검증할우선후보**지만,이번에는새Top3예측모형의미래비교나보정률선택을하지않았다.고정입상확률가산·시간보정·운영적용은없다.

## 보존과 검증

`PLAN.md`를효과계산전에고정했다.코드 `analyze.py`와이보고서생성 `report.py`,참조파일경로/해시 `source_manifest.json`,모형설계/계수/두cluster공분산 `models.json`,전체거리/두수지원표,번호별/그룹별/기간별표,원시비율/출전ID·SHA연결을이새폴더에저장했다。

`verification.json`은기존1000/1110의피처동일성·번호계수재현(최대차4.44e−16),47,030건의기간중복포함이력연결/T−2·거리확인,그룹대조산술·번호평균0·10두/1~10완결성·미지원NULL·모든참조해시불변·DB SHA/크기/mtime불변을통과했다.같은에이전트의계산검증이며독립심사자검증은아니다。새출력은독점생성하므로같은폴더재실행은중단한다。재현시새폴더로코드와계약만복사하고 `PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python jeju/research/새폴더/analyze.py` → `report.py` 순서로실행한다。기존원천/DB 해시가같은지먼저확인한다。
'''
    with (HERE/'README.md').open('x',encoding='utf-8') as f:f.write(text)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(1,3,figsize=(14,6),sharey=True,layout='constrained')
    distances=[800,900,1000,1110,1200,1300,1400]
    for ax,period,title in zip(axs,['2019_2025','2024_2025','2026_partial'],['2019-2025','2024-2025','2026 partial (through Sep 19)']):
        z=a[(a.period==period)&(a.target=='top3')&(a.contrast=='inner_minus_outer')].set_index('distance')
        for j,dist in enumerate(distances):
            r=z.loc[dist];color='#1468a0' if r.status in ['basic_support','partial_year_exploratory'] else '#999999'
            if pd.notna(r.effect):ax.errorbar(r.effect,j,xerr=np.array([[r.effect-r.ci_lo],[r.ci_hi-r.effect]]),fmt='o',color=color,capsize=3)
            else:ax.text(-5,j,'Not estimated',color='gray',va='center',fontsize=8)
        ax.axvline(0,color='black',ls='--',lw=1);ax.set_title(title);ax.set_xlabel('Inner minus outer Top3 (percentage points)');ax.set_yticks(range(len(distances)),[f'{d}m' for d in distances]);ax.set_xlim(-15,33);ax.grid(axis='x',alpha=.15)
    axs[0].invert_yaxis();fig.suptitle('Jeju 10-runner races: start numbers 1-3 vs 8-10\nAdjusted observational associations, pointwise 95% date-cluster intervals | Gray: limited sample',fontsize=12)
    fig.savefig(HERE/'lateral_effects.png',dpi=150);fig.savefig(HERE/'lateral_effects.svg');plt.close(fig)
    inventory=[]
    for p in sorted(HERE.iterdir()):
        if p.is_file() and p.suffix!='.log':inventory.append({'path':p.name,'sha256':sha(p),'bytes':p.stat().st_size})
    with (HERE/'artifact_manifest.json').open('x',encoding='utf-8') as f:json.dump(inventory,f,ensure_ascii=False,indent=2)
    assert all(sha(HERE/r['path'])==r['sha256'] for r in inventory)
    print('Report complete',HERE/'README.md')
if __name__=='__main__':main()
