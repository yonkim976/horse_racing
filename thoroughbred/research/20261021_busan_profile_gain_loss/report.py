"""Research diagnosis tables and figures; no new prediction rule or deployment."""

import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import analyze as a


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,row))+' |' for row in rows])


def main():
    cases=pd.read_parquet(a.OUT/'all_race_pairs.parquet');changed=cases[cases.changed].copy()
    years=pd.read_csv(a.OUT/'year_summary.csv');summary=json.loads((a.OUT/'analysis_summary.json').read_text())
    stats=pd.read_csv(a.OUT/'feature_summaries.csv');frozen=json.loads((a.OUT/'frozen2024_on2026.json').read_text())
    old_metrics=pd.read_csv(a.OLD/'../outputs/evaluation_metrics.csv')
    original2026=old_metrics[old_metrics.scope.eq('2026')].set_index('model')
    annual=table(['연도','전체 경주','말 교체','회복','상실','둘 다 적중/실패¹','순증'],[
        [int(r.year),int(r.races),int(r.changed),int(r.gain),int(r.loss),f'{r.both_hit}/{r.both_miss}',f'{int(r.net):+d}']for r in years.itertuples()])
    distances=pd.read_csv(a.OUT/'distance_counts.csv');grades=pd.read_csv(a.OUT/'grade_number_counts.csv')
    def cross(frame,label):
        rows=[]
        for value,g in frame[frame.year.isin([2024,2026])].groupby('condition'):
            by=g.set_index('year')
            if not {2024,2026}.issubset(by.index):continue
            a0,b0=by.loc[2024],by.loc[2026]
            rows.append([label(value),f'{int(a0.gain)}/{int(a0.loss)} ({int(a0.net):+d})',f'{int(b0.gain)}/{int(b0.loss)} ({int(b0.net):+d})'])
        return table(['조건','2024 회복/상실(순증)','2026 회복/상실(순증)'],rows)
    distance_table=cross(distances,lambda x:str(int(x))+'m')
    grade_table=cross(grades,lambda x:str(int(x))+'등급' if int(x)>0 else '숫자등급 없음')
    desired=['hist_same_n','hist_performance','hist_early200_field_adv_seconds','hist_late600_field_adv_seconds','hist_late200_field_adv_seconds','hist_late200_index']
    titles=['동일거리 이력 수 차이','과거 전체 편성상대기록 차이(초/1000m)','과거 초반200m 편성우위 차이(초)','과거 마지막600m 편성우위 차이(초)','과거 마지막200m 편성우위 차이(초)','과거 마지막200m 자기지수 차이']
    prior_rows=[]
    for metric,label in zip(desired,titles):
        row=[label]
        for year,outcome in [(2024,'gain'),(2024,'loss'),(2026,'gain'),(2026,'loss')]:
            q=stats[(stats.year.eq(year))&stats.outcome.eq(outcome)&stats.role.eq('delta')&stats.metric.eq(metric)].iloc[0]
            row.append(f'{q["mean"]:+.3f}')
        prior_rows.append(row)
    prior_table=table(['신규−기존의 과거 입력 차이','2024 회복16','2024 상실24','2026 회복22','2026 상실12'],prior_rows)
    raw_rows=[]
    for metric,title in [('same_early200_seconds','초반200m'),('same_late600_seconds','마지막600m'),('same_late200_seconds','마지막200m')]:
        row=[title]
        for year,outcome in [(2024,'gain'),(2024,'loss'),(2026,'gain'),(2026,'loss')]:
            q=stats[stats.year.eq(year)&stats.outcome.eq(outcome)&stats.role.eq('delta')&stats.metric.eq(metric)].iloc[0]
            row.append(f'{q["mean"]:+.3f}초 (n={int(q.n)})')
        raw_rows.append(row)
    raw_table=table(['같은 거리 과거5회 실제초 차이','2024 회복','2024 상실','2026 회복','2026 상실'],raw_rows)
    boundary=changed[changed.outcome.isin(['gain','loss'])].groupby(['year','outcome']).agg(n=('case_id','size'),
        old_rank_mean=('old_finish_rank','mean'),new_rank_mean=('new_finish_rank','mean'),
        old_rank4=('old_finish_rank',lambda x:int(x.eq(4).sum())),new_rank4=('new_finish_rank',lambda x:int(x.eq(4).sum())),
        old_same0=('old_hist_same_n',lambda x:int(x.eq(0).sum())),new_same0=('new_hist_same_n',lambda x:int(x.eq(0).sum())))
    boundary.to_csv(a.OUT/'finish_boundary_and_history.csv')
    groups=pd.read_csv(a.OUT/'score_group_differences.csv')
    groups.groupby(['year','outcome'])[['base_retrained_change','curve','section_position','style8']].agg(['mean','median']).to_csv(a.OUT/'score_group_summary.csv')
    contrib=pd.read_parquet(a.OUT/'feature_contribution_differences.parquet')
    contrib.groupby(['year','outcome','feature']).new_minus_old_contribution.agg(['mean','median','size']).reset_index().to_csv(a.OUT/'feature_contribution_summary.csv',index=False)
    # All six recovered1300m races are listed, not a favourable example subset.
    recover1300=changed[changed.year.eq(2026)&changed.distance.eq(1300)&changed.gain].copy()
    recover1300.to_csv(a.OUT/'2026_1300_recoveries.csv',index=False)
    case_table=table(['2026 날짜/경주','등급','기존 선택→실제','신규 선택→실제','과거 초반우위 차이','과거 종반200우위 차이'],[
        [r.date+' '+str(r.race_no)+'R',r.grade_label,f'{r.old_program_no} {r.old_horse_name}→{r.old_finish_rank}위',
            f'{r.new_program_no} {r.new_horse_name}→{r.new_finish_rank}위',f'{r.delta_hist_early200_field_adv_seconds:+.3f}초',f'{r.delta_hist_late200_field_adv_seconds:+.3f}초']for r in recover1300.itertuples()])
    actual_rows=[]
    for year,outcome in [(2024,'gain'),(2024,'loss'),(2026,'gain'),(2026,'loss')]:
        g=changed[changed.year.eq(year)&changed.outcome.eq(outcome)]
        actual_rows.append([str(year)+' '+('회복'if outcome=='gain'else'상실'),len(g),f'{g.delta_actual_early200_seconds.mean():+.3f}',f'{g.delta_actual_late600_seconds.mean():+.3f}',f'{g.delta_actual_late200_seconds.mean():+.3f}'])
    actual_table=table(['그룹','경주','실제 초반200 차이','실제 마지막600 차이','실제 마지막200 차이'],actual_rows)
    # Figures use English labels and raw event counts, not unexplained propensity scores.
    fig,axes=plt.subplots(1,2,figsize=(12,4.3),sharey=True)
    for ax,year in zip(axes,[2024,2026]):
        g=distances[distances.year.eq(year)];xx=np.arange(len(g))
        ax.bar(xx,g.gain,color='#2a7f9f',label='Recovered');ax.bar(xx,-g.loss,color='#c17c45',label='Lost')
        ax.plot(xx,g.net,'o-',color='#344653',label='Net');ax.axhline(0,color='#999',lw=.8)
        ax.set_xticks(xx,g.condition.astype(int),rotation=45);ax.set_xlabel('Race distance (m)')
        ax.set_title(str(year)+(' (through Sep18)'if year==2026 else' (full year)'));ax.legend(fontsize=9);ax.grid(axis='y',alpha=.15)
    axes[0].set_ylabel('Number of races');fig.tight_layout();fig.savefig(a.OUT/'gain_loss_by_distance.png',dpi=165);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4.4));categories=[(2024,'gain'),(2024,'loss'),(2026,'gain'),(2026,'loss')]
    rng=np.random.default_rng(a.SEED)
    for ax,metric,title in zip(axes,['delta_hist_early200_field_adv_seconds','delta_hist_late200_field_adv_seconds'],['Prior first200m field advantage','Prior last200m field advantage']):
        for i,(year,outcome) in enumerate(categories):
            v=changed[changed.year.eq(year)&changed.outcome.eq(outcome)][metric].dropna().to_numpy()
            ax.scatter(i+rng.uniform(-.13,.13,len(v)),v,s=20,color='#287b9d'if outcome=='gain'else'#bb7543',alpha=.65)
            ax.plot([i-.2,i+.2],[np.median(v)]*2,color='#1a3344',lw=2.5)
        ax.axhline(0,color='#aaa',ls='--');ax.set_xticks(np.arange(4),['2024 gain','2024 loss','2026 gain','2026 loss'],rotation=20)
        ax.set_title(title);ax.set_ylabel('New minus old (seconds); positive = more prior advantage');ax.grid(axis='y',alpha=.12)
    fig.tight_layout();fig.savefig(a.OUT/'past_early_late_differences.png',dpi=165);plt.close(fig)
    body=f'''# 부산 추가정보 모델:2024년 상실과2026년 회복의 조건

2026-10-21. 연구57H. **반전은2026년1300m·5등급과,초반보다 종반 우위가 큰 말로의 교체에서 두드러졌다. 그러나 같은 유형의 교체가2024년에는 실패도 많았다. 과거 종반의 자기100지수만으로 확실한 개선을 설명할 수 없고,원인과 적용 규칙은 아직 확정할 수 없다.**

기존 연구57G의B0(기본기록30열)와B3(전체추가101열),저장모델·입력·예측을 고정해 분석했다.운영 모델 비교가 아닌 별도 연구모델이고,정상완주마 조건부 평가다.새학습0·DB접근0·운영/원천/기존웹 변경0이다.

## 교체와 적중 변화

{annual}

¹선택마를 교체한 경주 안의 둘 다 적중/둘 다 실패다.회복은B0선택마4위이하/B3선택마3위이내,상실은그반대다.변경하지않은경주도전체원장에보존했다.전체1,976경주중교체209,회복/상실130경주다.말수가아닌경주수다.

2024도1월~9월18일로맞추면525경주에서회복10/상실17(−7),2026은536경주22/12(+10)로방향이유지된다.기간길이차이만으로설명되지않는다.같은기간거리×숫자등급공통16셀(양쪽10경주이상)을공통구성비로맞춘순증률도2024−1.876%p/2026+1.506%p다.지원범위는각456/525·467/536경주이며,그밖의조건이나인과효과를통제한것은아니다.

## 거리와 등급

{distance_table}

{grade_table}

숫자등급은국/혼구분을합친값이며원문등급도별도보존했다.1등급·2000/2200m는소표본이다.주요교차조건인 **1300m5등급은2024회복0/상실3,2026회복5/상실0** 이었다.2026의1300m전체회복6개중5개가5등급이다.반면1400m는2026에도5회복/7상실로좋아지지않았다.이사후집중만으로1300m전용채택규칙을만들지않았다.

![거리별 회복과 상실](outputs/gain_loss_by_distance.png)

## 과거 이력과 초반·종반 입력의 차이

아래는경주전에확인되는이전부산정상출전최근5회입력의 **신규선택마−기존선택마 평균차이** 다.편성우위는과거각경주의정상완주마중앙구간초대비빠른정도이며양수가새말우위다.현재두말이같은과거편성에서뛰었다는뜻은아니다.전체상대기록만초/1000m이고,구간우위는각실제200/600m의초단위로환산했다.

{prior_table}

- **2026회복22경주:** 새말이과거초반에서는평균0.152초열위였지만마지막600m우위가0.428초,마지막200m우위가0.285초더컸다.과거전체상대기록도+0.093초/1000m로좋았다.‘초반열위·종반우위’로바꾼교체39경주중18회복/6상실(나머지둘다적중/실패)이었다.
- **2026상실12경주:** 종반200m우위차이가+0.013초로작고과거전체상대기록은−0.111초/1000m였다.기존말의동일거리이력이0인경주가8/12였고,새말은전체이력이평균1.25회더많았다.관측수가많다고능력이더높다는뜻은아니다.
- **2024상실24경주:** 종반자기지수는+0.939로높았고과거편성우위도종반200m+0.120초였지만,전체상대기록은−0.061초/1000m였다.비율상종반이좋아보이는것과실제동일거리기록이좋은것을구분해야한다.
- **2024회복16경주:** 과거전체상대기록은+0.078초/1000m,종반200m우위차이는+0.129초였다.종반200m우위차이는2024회복과상실간에거의같아이변수하나로성공/실패를나눌수없었다.

이력수도일관된분리기준이아니었다.기존/신규모두동일거리3~5회인교체는2026에8경주6회복/0상실이었지만,2024에는4경주0회복/3상실이었다.회복말은양쪽연도모두오히려동일거리이력이적었다.유효n과기록수준을함께봐야하며3회이상게이트를새로채택하지않았다.

![과거 초반·종반 우위의 개별 차이](outputs/past_early_late_differences.png)

점은각교체경주,짧은가로선은중앙값이다.분포가겹친다.주요조건의회복−상실평균차이날짜재표집2000회95%구간은0을포함했다.예를들어2026종반200m차이의그룹대비는+0.272초,[−0.073,+0.610]이다.2024동일거리종반600m대비는−0.784초,[−1.736,+0.173]이다.결과로분류한소표본에대한복수조건탐색이므로유의한원인이나검증된선택필터라고해석하지않는다.

## 같은 거리의 과거 실제 구간초

아래는양쪽말모두동일거리이력이있는경주만쓴쌍별차이이며 **음수가신규말의실제기록이빠름** 이다.다른거리의초를그대로평균한표가아니다.

{raw_table}

2024상실은종반자기지수가더높아도동일거리마지막600m는평균0.388초느린편이었다(n16,중앙값+0.355초).반대로회복은0.396초빨랐다(n11).그러나차이의구간은0을포함한다.2026회복은평균상0.129초빠르지만중앙값은+0.425초로느린방향이라일부큰값의영향이있다.2026상실은비교가능한경주가2개뿐이므로평균을일반화하면안된다.누락을0초·동일능력으로채우지않았다.

## 1300m 회복6경주 전체

{case_table}

6경주지만신규말은5두다.아유레디가2회포함되어독립된6두의효과로해석하지않는다.예컨대1월11일아리드래곤은동일거리이력이0회였지만다른부산거리이력2회에서좋은종반우위를보였고선택후2위였다.각교체의정답을이미안뒤선별한일러스트이므로사전적중규칙이아니다.

## 실제 그날 기록:사전 입력과 분리

{actual_table}

이표는실제구간초의신규−기존차이이므로음수가빠르다.2026회복말은그날초반이평균0.132초느려도마지막600m는1.705초빨랐다.하지만완주결과로회복/상실을나눴으므로그날종반차이가성적과관련되는것은사후설명이고사전예측력의입증이아니다.모든회복말의종반이빨랐다는뜻도아니다.2026상실12경주중6개는신규말4위였고1400m상실7개중5개가4위였다.

## 모델 갱신의 영향과 무엇을 선택 점수에 반영했나

2024저장모델(학습종료2023)을같은2026입력에그대로적용하면기본329/536,전체335/536으로14회복/8상실(+6)이었다.현재2026저장모델(학습종료2025)은320/536,330/536으로22/12(+10)이다. **동일한2024모델도2024에서는감소,2026에서는증가하므로연도반전이새학습때문만은아니다.**

동시에모델갱신후2026의절대입상포착은기본−9/전체−5로둘다감소했다.순증이+6→+10으로커진것을절대성능개선으로읽으면안된다.기록MAE는동결기본{frozen['mae_seconds_per1000m']['B0']:.6f}→갱신{original2026.loc['B0','mae']:.6f},동결전체{frozen['mae_seconds_per1000m']['B3']:.6f}→갱신{original2026.loc['B3','mae']:.6f}초/1000m로조금줄었다.이연구모델은상대완주기록오차를학습하고Top3는보조평가라,기록오차감소와예측1위입상은다르게움직일수있다.동결모델의사후우위를보고운영모델로채택하지않았다.

교체209경주의두말점수차이를TreeSHAP로재현했다.합계오차는약1.4×10⁻¹⁵이하다.기본입력기여의재학습변화,자기100곡선,실제구간/위치,8각질을나눴다.2026회복의교체방향평균기여는각+0.0349/+0.0075/+0.0374/+0.0046초/1000m였고,상실은+0.0423/−0.0001/+0.0387/+0.0061이었다.세부8각질기여가상실에서더크기도하므로‘8각질이2026개선을만들었다’고말할수없다.추가입력만의순수인과효과가아니라전체모형의점수계산설명이다.

## 현재 판단

회복은상대적으로큰종반우위와기존전체기록수준을함께가진말에서많았고,상실에는종반비율이좋아도동일거리실제기록이강하지않거나전체기록우위가작은말이섞였다.다만2024·2026에서효과가일관되지않고주요조건차이의구간도넓다.고정‘1300m/5등급/이력3회’필터를새로적용할근거는아니다.다음가설을세우려면현재결과를개발자료로취급하고별도시간외검증이필요하다.

기존전체Top3차이의날짜95%구간도0을포함한다.이번작업은관측조건·점수계산을분해한연구이며연도반전의원인을확정한것은아니다.1976경주선택,2185개선택출전의과거구간평균8740개,입력단위·부호·모델재생·공통16셀표준화를독립확인했다.새학습·DB·운영·제주·기존웹변경없음.

[사전계획](PLAN.md) · [교체209경주](outputs/changed_races.csv) · [전체쌍](outputs/all_race_pairs.parquet) · [거리](outputs/distance_counts.csv) · [등급](outputs/grade_label_counts.csv) · [거리×등급](outputs/distance_grade_counts.csv) · [이력](outputs/same_history_pair_counts.csv) · [과거기록통계](outputs/feature_summaries.csv) · [그룹차이95%구간](outputs/gain_loss_contrasts.csv) · [표준화](outputs/standardization.json) · [동결모델재적용](outputs/frozen2024_on2026.json) · [점수기여](outputs/score_group_differences.csv) · [검증](outputs/verification.json) · [출처](outputs/sources.json) · [용량](outputs/artifact_inventory.json)
'''
    (a.HERE/'README.md').write_text(body)
    pub='''# 부산 모델의2024/2026 교체 적중 차이

2026-10-21. 연구57H. 저장된 기본/전체추가 연구모델을 고정해 비교했다.2024는16회복·24상실(−8),2026은22회복·12상실(+10)이었다.같은9월18일까지 맞춰도2024는−7로 방향이 유지됐다.

1300m5등급은2024에0회복/3상실,2026에5/0이었다.2026회복말은 과거 초반 우위가 조금 낮아도 종반 우위가 더 큰 편이었다.하지만2024에는 비슷한 교체가 실패도 많았고,주요 조건 차이의95%구간은0을 포함한다.과거 종반 자기지수가 높아도 동일거리 실제초가 강하지 않은 경우가 있었다.이력수 역시 단독 성공 기준이 아니었다.

2024 동결모델을2026에 적용해도+6경주여서 반전이 새 학습 때문만은 아니었다.갱신 후 기본/전체 모델의 절대입상 포착은 둘 다 낮아졌지만 기록오차는 소폭 줄었다.상대완주기록을 학습하는 목표와Top3 선택평가의 차이를 구분해야 한다.

결과는 사후 조건 진단으로 인과원인·새 필터·운영 채택을 확정하지 않는다.새학습0·DB접근0·운영/기존웹 변경0이며 게시용 요약만 준비했다.

[전체 결과](README.md) · [회복·상실 원장](outputs/changed_races.csv) · [독립 검증](outputs/verification.json)
'''
    (a.HERE/'PUBLICATION.md').write_text(pub)
    central=a.R/'conclusions/57H_BUSAN_PROFILE_GAIN_LOSS.md'
    central.write_text(pub.replace('(README.md)',f'(../{a.HERE.name}/README.md)').replace('(outputs/',f'(../{a.HERE.name}/outputs/'))
    marker='<!-- busan_profile_gain_loss_20261021 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        path=a.R/name;link=a.HERE.name+'/README.md'if name=='README.md'else central.name
        if marker not in path.read_text():
            with path.open('a')as f:f.write(f'\n\n{marker}\n[연구57H 부산2024/2026 교체 회복·상실]({link}): 2024회복16/상실24,2026 22/12.1300m5등급반전·종반우위/실제동일거리기록분리.동결2024모델의2026순증+6,조건차이불확실·새학습/운영변경없음.\n')
    a.save('sources.json',dict(checked_on='2026-10-21',source_run='20261021_busan_all_distance_profiles',
        data=['saved predictions','frozen profiles and features','saved B0/B3 models'],new_external_data=False,
        model_explanation='Within-pair TreeSHAP score differences are exact decompositions, not causal effects.',
        source_period='2010-01-08 through2026-09-18; training labels from2017',conditional_on_normal_finishers=True,
        no_training=True,no_database_access=True,production_changed=False))


if __name__=='__main__':main()
