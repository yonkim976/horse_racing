"""Publish retained research summaries; no deployment or further model selection."""

import json
import pandas as pd
import prepare as p


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,row))+' |' for row in rows])


def main():
    support=pd.read_csv(p.OUT/'distance_support.csv');metrics=pd.read_csv(p.OUT/'evaluation_metrics.csv')
    ci=pd.read_csv(p.OUT/'paired_intervals.csv');race=pd.read_csv(p.OUT/'race_metrics.csv')
    d=pd.read_parquet(p.OUT/'profiles.parquet');x=pd.read_parquet(p.OUT/'features.parquet')
    recent=d.year.ge(2024)
    coverage=d.loc[recent,['distance']].copy()
    for name,col,n in [('any_history','all_slots',1),('same_history3','same_slots',3),('style_history3','all_style_0_n',3)]:coverage[name]=x.loc[recent,col].ge(n).to_numpy()
    coverage.groupby('distance').agg(n=('any_history','size'),any_history=('any_history','sum'),same_history3=('same_history3','sum'),style_history3=('style_history3','sum')).to_csv(p.OUT/'history_coverage.csv')
    q=d.sort_values(['horse_id','distance','date','race_no']).copy()
    for col in ['style8','coarse_style']:q['prev_'+col]=q.groupby(['horse_id','distance'])[col].shift()
    pairs=q[q.year.ge(2024)&q.prev_style8.notna()&q.prev_style8.ne('미확인')&q.style8.ne('미확인')]
    p.save('style_repeat_summary.json',dict(pairs=len(pairs),fine8_repeat=float(pairs.style8.eq(pairs.prev_style8).mean()),coarse4_repeat=float(pairs.coarse_style.eq(pairs.prev_coarse_style).mean()),
        scope='consecutive normal Busan same-distance starts; unknown styles not replaced by older observations',not_prediction_accuracy=True))
    agg=[]
    for dist,g in race.groupby('distance'):
        agg.append(dict(distance=int(dist),races=len(g),B0_top3=int(g.B0_top3.sum()),B3_top3=int(g.B3_top3.sum()),
            top3_gain=int(g.B3_top3.sum()-g.B0_top3.sum()),B0_mae=float(g.B0_mae.mean()),B3_mae=float(g.B3_mae.mean())))
    pd.DataFrame(agg).to_csv(p.OUT/'distance_aggregate_metrics.csv',index=False)
    layout_table=table(['거리m','최소 구간 길이m','완전/전체 정상완주'],[
        [int(r.distance),r.lengths,f'{int(r.complete):,}/{int(r.rows):,}'] for r in support.itertuples()])
    names={'B0':'기본 기록 이력','B1':'+자기100 곡선','B2':'+실제 구간·초반 위치','B3':'+세부8각질'}
    full=metrics[metrics.scope.eq('all')]
    overall=table(['평가 묶음','입력수','기록 MAE 초/1000m','예측1위 실제Top3','예측1위 실제우승'],[
        [names[r.model],dict(B0=30,B1=54,B2=92,B3=101)[r.model],f'{r.mae:.6f}',f'{r.top3_hits}/1976 ({r.top3_rate*100:.2f}%)',f'{r.win_hits}/1976 ({r.win_rate*100:.2f}%)'] for r in full.itertuples()])
    annual=[]
    for year in [2024,2025,2026]:
        a=metrics[(metrics.scope.eq(str(year)))&metrics.model.eq('B0')].iloc[0]
        b=metrics[(metrics.scope.eq(str(year)))&metrics.model.eq('B3')].iloc[0]
        annual.append([year,int(a.races),f'{a.top3_rate*100:.2f}%',f'{b.top3_rate*100:.2f}%',f'{int(b.top3_hits-a.top3_hits):+d}',f'{a.mae:.6f}→{b.mae:.6f}'])
    year_table=table(['평가연도','경주','기본Top3','세부전체Top3','적중 차','기록 MAE 초/1000m'],annual)
    error_ci=ci[ci.scope.eq('all')&ci.metric.eq('mae')]
    ci_table=table(['추가 비교','MAE 차이 초/1000m','날짜95%구간'],[
        [r.new+'−'+r.old,f'{r.difference:+.6f}',f'[{r.low:+.6f}, {r.high:+.6f}]'] for r in error_ci.itertuples()])
    body=f'''# 부산 전 거리 구간 평가·각질8종과 다음 경주 기록 검증

2026-10-21. 연구57G. **부산10개 거리로 최소 계측구간 표시를 확장했고,전개 형태도8종으로 나눌 수 있었다. 하지만 세분화가 말 능력의 미래 판별을 크게 높인다는 근거는 확보하지 못했다. 편성 대비 실제 구간기록·초반 위치를 추가한 평균 기록 오차의 개선은 약0.001초/1000m로 아주 작고,세부8각질을 더한 효과는 불확실했다.**

[전 거리 평가표](outputs/viewer.html) · [실행 중 로컬 화면](http://127.0.0.1:8878/viewer.html) · [계획](PLAN.md)

## 거리별 최소 분할과100 기준

공식 명목 계측지점과 출발200m S1F를 합친다. 경주거리D·구간거리d·구간초t·완주초T에서 `환산초E=t×D/d`, `지수I=100T/E`, `차이Δ=I−100`이다.100m·300m·400m도 실제 길이로 환산하고 미관측200m를 만들지 않는다.100은 본인의 같은 경주 평균속도이며 예상완주·능력점수·확률·최적전개 기준이 아니다. [마사회 거리별 측정거리표](https://race.kra.co.kr/raceScore/cornerRecordDesc.do).

{layout_table}

부산2010-01-08~2026-09-18,양수 완주·착순1~30의 거리 확인133,755개 출전이다.완전 구간133,733개,결측/역순22건을 보존했다.1200m 기존 완전34,660건의 지수는 이전 결과와 재현 오차0이다.새 분석은 불완전22건의 구간 지수를 모두 보류하며,기존1200m의 개별 유효쌍만 계산한 부분값 정책과 이 부분이 다르다.불완전 슬롯은 과거5회 자리를 소비하고 오래된 기록으로 보충하지 않는다.

1500m는 보유2010~2015,1900m는 마지막2020-07-19 자료다.2200m는15경주160출전에 불과하다.현행개최를 이 표가 보장하지 않는다.주로실측 좌표·내외주로 경로·전체 역사 변경 이력의 미확정은 연구57E와 같이 남아 있다.원기록 비율이며 기존 월·게이트·중량·주로 보정을 채택/수정한 작업은 아니다.

![거리별 관측 곡선](outputs/distance_profile_curves.png)

그림은 최근 구간지수 평균과 개별출전P20~P80이며 최근 자료가 없는1500/1900m는 역사 자료다.그림의 점은 구간의 중간 위치에 표시한 평균속도이지 순간속도나 계측장비 위치가 아니다.서로 다른 길이·거리·등급의 지수를 동일 능력으로 비교하지 않는다.

## 세부 각질8종의 정의

관측 상대위치q=(통과순위−1)/(관측분모−1)로0~1에 놓았다.분모는 정상완주마들의 순위 최대값과 정상완주 수 중 큰 값이다.실제 전체 출발마가 확인된 분모가 아니며 비완주 위험은 이 분석 범위에 없다.

| 분류 | 해당 경주의 사후 관측 기준 |
| --- | --- |
|선행잔류|S1F1위·최종q≤1/3|
|선행이탈|S1F1위·최종q>1/3|
|선입잔류|선행 외 S1F q≤1/3·최종q≤1/3|
|선입이탈|선행 외 S1F q≤1/3·최종q>1/3|
|중반진출|앞선 네 유형 외,S1F→G3F q0.2 이상 개선|
|막판진출|이전 유형 외,G2F→결승 q0.2 이상 개선|
|후미정체|이전 유형 외,S1F q>2/3·최종 개선0.1 이하|
|중단혼합|나머지|

우선순위는 표 순서다.단일 유형 외에 마지막400m의 회복/유지/밀림 표식을 별도로 두어 중반 진출 후 다시 밀린 경우도 남긴다.잔류/이탈은 해당 출전 결과의 분류이지 체력 소진의 원인 판정이 아니다.현재 출전의 분류를 현재 사전예측에 넣지 않았다.

최근21,452출전의8종 분포는 선행잔류1,188·선행이탈783·선입잔류2,640·선입이탈3,020·중반진출2,585·막판진출4,091·후미정체1,970·중단혼합5,175다.같은 말·같은 거리의 연속 정상출전16,355쌍에서8종 반복률은25.95%,초반 큰4위치 반복률은43.25%다.분류 수가 다르고 경주 조건도 달라 이 비율을 두 분류의 우열이나 사전 각질 예측정확도로 읽지 않는다.단일 고정 라벨보다 최근 관측 분포와 유효n을 함께 보는 편이 적절하다.

## 미래 수행을 더 잘 판단하는가

별도 연구 비교용 회귀4종을 고정하고,2017년부터 이전연도까지 훈련한 뒤2024/2025/2026을 각각 평가했다.2010~2016은 warm-up 이력이다.최근5회는 부산 정상출전 기준이며 서울 이적 전 이력은 이번 입력에 포함하지 않았다.동일거리와 전체거리 이력의 날짜를 현재보다 엄격하게 앞당기고,현재 완주·구간·착순·각질을 입력하지 않았다.원천 공개시각까지 검증한 전향 실시간 평가가 아니라 이미 관측한 자료의 시간순 후향 개발 비교다.

목표는 `같은 경주 정상완주마 완주초 중앙값−본인 완주초`를1000m당초로 맞춘 상대 수행이다.순수 잠재능력이나 운영 입상확률과 다르다.정상완주6두 이상1,976경주21,452출전이며 비완주를 제외한 조건부 모집단이다.공통 시간 오프셋은 예측값의 경주 내 중앙값으로 중심을 맞췄고 현재 정답을 사용하지 않았다.

B0는 현재 거리·등급·성별·나이·중량·월,간격·이전거리/중량,과거 전체기록·편성상대기록·착순비율이다.B1은 같은 거리 구간별 자기100곡선과 공통초반/종반 이력,B2는 편성 대비 실제 구간초 우위·초반 위치 및 큰4각질 이력,B3는 과거8종 비율/n을 더한다.기수는 넣지 않았다.기존 운영103/122모델의 재평가가 아니고 추가 정보의 효과를 보는 별도30/54/92/101열 기준선이다.12개 모델만 고정 설정으로 학습했으며 테스트 조기종료·튜닝은 없다.

{overall}

{year_table}

2026은9월18일까지의 부분연도다.전체B3의예측1위Top3는기본대비4경주 증가(+0.20%p),95%날짜구간은−0.86~+1.26%p로0을 포함한다.우승포착은574→572로2경주 감소했다.2026만 보면Top3+10경주지만2024는−8,2025는+2다.연도별Top3차이도 모두0을 포함하는구간이다.

기록오차 비교는 경주 동일가중,날짜266개를 paired 재표집2000회한95%구간이다.음수가 오차 감소다.

{ci_table}

B2−B0의구간만0을벗어나지만개선은0.000970초/1000m(기본오차의약0.15%)로작다.복수정보묶음/지표를탐색한보정전구간이며개별계측정밀도나실전효용향상으로확대하지않는다.B3−B2는모든연도에서MAE점추정치가소폭높고각구간은0을포함했다.세부8종이추가능력판단을높였다는근거는없다.

![추가 정보의 기록오차 변화](outputs/next_race_effects.png)

거리별B3−B0의Top3 적중차이는1200m+1/525경주,1300m+5/279,1400m−6/445,1600m+6/333,1800m−1/322,1000m−1/40,2000m0/30,2200m0/2다.1500/1900m는최근평가표본이없다.거리별점추정만으로적용거리를선택하지않았다.2000/2200m의표본도특히부족하다.

최근1000m400출전중부산정상출전이력이한번이라도있는말은76건이고동일거리3회이상은0건이다.이것은실제신마라고확정한분류가아니며타지역이력·자료포함범위에따라달라진다.상세구간을늘려도과거기록자체가없으면개별말평가를안정화하기어렵다.

## 사용 방향과 검증

평가표는 구간초 수준·속도 배분·실제 위치 변화·관측수를 분리해 사용한다.각질8종은 설명용 태그와 과거 비율로 보존한다.이번 결과로 운영 교체·고정각질 입력 채택은 하지 않는다.확인된 작은 변화는 연속 구간값을 조건별로 더 검토할 근거 정도이며,새 방식 일반의 실패나 개선 한계의 증명도 아니다.

산식850,253개 구간값,기존1200m34,660건,과거평균/n12,037,950셀,원문20출전138시간셀(오차0),저장12모델21,452평가출전의원시예측/중심예측(오차0),경주지표를별도로재검산했다.DB와운영등록부의해시를보존했다.로컬HTML에는10거리×2경주예시와최근5이력이들어있으며,10거리전환·표시모드·실제구간합을브라우저에서확인했다.운영웹·DB·원천·제주·등록모델변경및배포는없다.새연구12모델은운영에승격하지않았다.

[사전계획](PLAN.md) · [평가계약](outputs/evaluation_contract.json) · [거리별구간](outputs/segment_layouts.csv) · [프로필](outputs/profiles.parquet) · [입력](outputs/features.parquet) · [입력묶음](outputs/feature_sets.json) · [8종분포](outputs/style_distribution.csv) · [이력지원](outputs/history_coverage.csv) · [연도평가](outputs/evaluation_metrics.csv) · [거리평가](outputs/distance_aggregate_metrics.csv) · [95%구간](outputs/paired_intervals.csv) · [모델해시](outputs/model_manifest.json) · [독립검증](outputs/verification.json) · [출처](outputs/official_sources.json) · [용량](outputs/artifact_inventory.json)
'''
    (p.HERE/'README.md').write_text(body)
    pub='''# 부산 전 거리 구간·각질 세분화의 효과

2026-10-21. 연구57G. 부산10거리의 실제 최소 계측구간을 전체거리로 환산해 자기평균100 지수와 부호차이를 제공했다.133,755정상완주 중133,733건이완전하다.100·300·400m 구간을200m로임의분할하지않았다.

선행/선입의잔류·이탈,중반/막판진출등8종은사후설명에사용할수있다.같은말·같은거리8종반복은25.95%이며고정각질이나예측정확도가아니다.미래평가에는이전출전분포만사용했다.

2017년부터각이전연도까지훈련하고2024~2026년1,976경주를평가했다.기본→전체추가입력의예측1위Top3는58.60→58.81%(+4경주),연도별−8/+2/+10으로엇갈리고95%구간은0을포함했다.실제구간·초반위치까지넣은기록오차개선은약0.001초/1000m로작고세부8종추가효과는불확실했다.

평가표와과거이력확인도구로활용할수있지만능력판별개선이나운영교체를확정하지않았다.정상완주마조건부·원기록·부산이력범위의연구이며1500/1900과2200소표본을구분한다.12연구모델을보존했고DB·원천·운영모델·기존웹은유지했다.게시용요약준비이며배포하지않았다.

[결과](README.md) · [평가표](outputs/viewer.html) · [검증](outputs/verification.json)
'''
    (p.HERE/'PUBLICATION.md').write_text(pub)
    central=p.R/'conclusions/57G_BUSAN_ALL_DISTANCE_PROFILES.md'
    central.write_text(pub.replace('(README.md)',f'(../{p.HERE.name}/README.md)').replace('(outputs/',f'(../{p.HERE.name}/outputs/'))
    marker='<!-- busan_all_distance_profiles_20261021 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        path=p.R/name;link=p.HERE.name+'/README.md' if name=='README.md' else central.name
        if marker not in path.read_text():
            with path.open('a') as f:f.write(f'\n\n{marker}\n[연구57G 부산 전거리 구간·8각질 검증]({link}): 정상133,755/완전133,733. 실제최소구간·자기100·최근5이력으로확장. 시간순1,976경주B0→B3 Top3 58.60→58.81%,연도−8/+2/+10·구간0포함. 세부각질추가효과미확정·운영유지.\n')
    p.save('official_sources.json',dict(checked_on='2026-10-21',sources=[dict(url='https://race.kra.co.kr/raceScore/cornerRecordDesc.do',scope='Official distance-specific measured interval definitions; no inferred200m splits.'),dict(path='thoroughbred/research/20261020_busan_section_certainty/README.md',scope='Historical route/survey ambiguity and official geometry discrepancies remain.'),dict(path='thoroughbred/research/20261020_busan1200_six_section_profile/README.md',scope='Preserved same-race self-mean index definition and1200 baseline.')],raw_time_evidence='raw_source_manifest.json',not_surveyed_trajectory=True,operating_model_comparison=False))


if __name__=='__main__':main()
