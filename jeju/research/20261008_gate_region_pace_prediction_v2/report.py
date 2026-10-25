"""Readable research report, preserving negative incremental results."""
import json
import pandas as pd
from features import HERE,save


def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'---|'*len(headers)]+['| '+' | '.join(map(str,r))+' |' for r in rows])


def main():
    for path in ['run01/verification.json','gate01/verification.json','failures01/verification.json','verification01/verification.json']:
        assert json.loads((HERE/path).read_text())['status']=='passed'
    m=pd.read_csv(HERE/'run01/metrics.csv');fc=pd.read_csv(HERE/'failures01/miss_destination_counts.csv')
    raw=pd.read_csv(HERE/'gate01/gate_region_counts.csv');effects=pd.read_csv(HERE/'gate01/early_region_contrasts.csv')
    cmp=pd.read_csv(HERE/'run01/paired_comparisons.csv');adj=pd.read_csv(HERE/'gate01/previous_adjusted_top3.csv')
    pr=pd.read_csv(HERE/'run01/predictions.csv',dtype={'horse_id':str})
    a=pd.read_csv(HERE/'features01/features_and_targets.csv',dtype={'horse_id':str},low_memory=False)
    pct=lambda x:f'{100*x:.1f}%'
    def metric(task,model,period,col='logloss',dist='all'):
        return m[(m.task==task)&(m.model==model)&(m.period==period)&(m.distance.astype(str)==str(dist))&(m.subset=='all')].iloc[0][col]
    def fail(model,period,dist='all'):
        return fc[(fc.kind=='top1_per_race')&(fc.model==model)&(fc.period==period)&(fc.distance.astype(str)==str(dist))&(fc.gate_band=='all')].iloc[0]
    def obs(distance,event,band,period='all'):
        return raw[(raw.distance==distance)&(raw.event==event)&(raw.gate_band==band)&(raw.period==period)].iloc[0]
    region=[]
    for d in [800,900,1300,1400]:
        for event,label in [('firstpack','S1F 첫 집단'),('first2packs','S1F 앞 두 집단'),('top3','최종Top3')]:
            vals=[obs(d,event,b) for b in ['inner','middle','outer']]
            region.append([d,label,int(vals[0].races),*[pct(v.rate) for v in vals]])
    regiontable=table(['거리m','사건','유효10두경주','내측1~3','중간4~7','외측8~10'],region)
    differences=[]
    for r in effects[effects.contrast.eq('inner-outer')].itertuples():
        differences.append([r.distance,r.event,f'{r.difference_pp:+.2f}%p',f'[{r.lo_pp:+.2f}, {r.hi_pp:+.2f}]',f'{r.BH_q:.4g}'])
    differencetable=table(['거리m','초반사건','내측−외측','날짜95%구간 %p','24탐색비교BH q'],differences)
    adjusted=[]
    for d in [800,900,1300,1400]:
        r=adj[adj.distance.eq(d)].iloc[0]
        adjusted.append([d,f'{r.effect_pp:+.2f}%p',f'[{r.ci_lo_pp:+.2f}, {r.ci_hi_pp:+.2f}]',f'{r.q_BH:.4f}'])
    adjtable=table(['거리m','기존조정Top3 내측−외측','기존95%구간 %p','기존검정군BH q'],adjusted)
    modelrows=[]
    for model,label in [('M1','자기 과거'),('M2','+기존 연속게이트'),('M3','+상대·안팎 경쟁'),('M4','+내중외 구간·거리별 효과')]:
        modelrows.append([model+' '+label,*[f'{metric("s1f_pack3",model,p):.4f}' for p in ['2024_2025','2026_partial']],
            *[pct(fail(model,p).hit_rate) for p in ['2024_2025','2026_partial']]])
    modeltable=table(['입력','24~25 로그손실','26 로그손실','24~25 첫집단후보 적중','26 첫집단후보 적중'],modelrows)
    compare=[]
    for r in cmp[(cmp.task=='s1f_pack3')&(cmp.distance.astype(str)=='all')].itertuples():
        compare.append([r.period,f'{r.delta_logloss:+.5f}',f'[{r.date_lo:+.5f}, {r.date_hi:+.5f}]',
                        f'[{r.horse_lo:+.5f}, {r.horse_hi:+.5f}]',f'{r.BH_q:.4f}'])
    comparetable=table(['기간','M4−M3 로그손실','날짜95%구간','말95%구간','20비교BH q'],compare)
    distrows=[]
    for d in [800,900,1000,1110,1200,1300,1400,1610]:
        for p in ['2024_2025','2026_partial']:
            r=fail('M4',p,d);old=fail('M3',p,d)
            c=cmp[(cmp.task=='s1f_pack3')&(cmp.distance.astype(str)==str(d))&(cmp.period==p)].iloc[0]
            distrows.append([d,p,int(r.known),pct(old.hit_rate),f'{pct(r.hit_rate)} [{pct(r.hit_lo)}, {pct(r.hit_hi)}]',
                f'{metric("s1f_pack3","M3",p,dist=d):.4f}→{metric("s1f_pack3","M4",p,dist=d):.4f}',
                '지원' if c.sample_supported else '소표본·미지원'])
    disttable=table(['거리m','기간','정답경주','M3 후보적중','M4 후보적중 [날짜95%]','M3→M4 손실','표본상태'],distrows)
    missrows=[];positionrows=[]
    for model in ['M3','M4']:
        for p in ['2024_2025','2026_partial']:
            r=fail(model,p)
            missrows.append([model,p,int(r.known),int(r.hits),int(r.misses),f'{int(r.second)} ({pct(r.second_given_miss)})',
                f'{int(r.behind)} ({pct(r.behind_given_miss)})',f'[{pct(r.second_lo)}, {pct(r.second_hi)}]'])
            positionrows.append([model,p,int(r.misses),f'{int(r.front)} ({pct(r.front_given_miss)})',
                f'{int(r.middle_rear)} ({pct(r.middle_rear_given_miss)})',f'{int(r.position_unknown)} ({pct(r.position_unknown_given_miss)})'])
    misstable=table(['모형','기간','정답경주','첫집단 적중','실패','실패중 둘째집단','실패중 셋째이후','둘째비율 날짜95%'],missrows)
    positiontable=table(['모형','기간','실패수','확실 선입권','확실 중단·후미','범위경계 판정불명'],positionrows)
    missdistance=[]
    for d in [800,900,1000,1110,1200,1300,1400,1610]:
        r=fail('M4','2026_partial',d)
        missdistance.append([d,int(r.known),int(r.misses),f'{int(r.second)} ({pct(r.second_given_miss)})',
            f'{int(r.behind)} ({pct(r.behind_given_miss)})',f'{int(r.front)}/{int(r.middle_rear)}/{int(r.position_unknown)}'])
    missdisttable=table(['거리m','2026 정답경주','失敗数'.replace('失敗数','실패수'),'둘째집단','셋째이후','확실선입/중단후미/불명'],missdistance)
    coverage=pd.read_csv(HERE/'run01/target_coverage.csv')
    cv=coverage[(coverage.task=='s1f_position4')&(coverage.period=='2026_partial')].iloc[0]
    four=pd.read_csv(HERE/'failures01/four_position_lead_failures.csv');four26=four[(four.model=='M4')&(four.period=='2026_partial')&(four.distance.astype(str)=='all')].iloc[0]
    examples=[]
    for d in [800,900,1300,1400]:
        r=a[a.year.eq(2026)&a.race_distance_m.eq(d)].sort_values(['race_date','race_number']).iloc[-1]
        z=pr[pr.task.eq('s1f_pack3')&pr.model.isin(['M3','M4'])&pr.race_id.eq(r.race_id)]
        examples.append(z.sort_values(['model','horse_number']))
    pd.concat(examples).to_csv(HERE/'latest_race_examples.csv',index=False,encoding='utf-8-sig')
    text=f'''# 제주 게이트 구간과 전개 재예측 및 선행 후보 실패 위치

2026-10-08 완료. **800·900m는 전체기간 최종 입상에서 내측 우세 근거가 있으며,1400m도 초반 집단 위치와 원시 입상률은 내측 방향이다. 그러나 기존 마번·상대 구성을 쓰는 모형에 내측/중간/외측 항목을 추가해도 예측이 안정적으로 개선되지는 않았다. 새 구간 모형M4는 채택하지 않고 이 비교의 연구 기준은M3를 유지한다. 운영 모델 변경은 없다.**

첫 집단 확률 최고1두를 고르는 M4의2026년 후보적중은292/488=59.8%다. 빗나간196건 가운데 둘째집단109건55.6%,셋째이후87건44.4%였다. **둘째집단을 자동으로 선입이라고 부르지 않는다.** 같은196건의 확실 선입권은77건39.3%,확실 중단·후미53건27.0%,범위 경계 판정불명66건33.7%다.

## 기간과 표본

2017-01-01~2026-09-19 품질 원천52,155출전·5,206경주·2,813두다.400m 워밍업 제외,현재8거리 유지.1300m는 사용자 정정 **출발→2C→S1F** 계약에 따라 이번 S1F 목표와 과거 이력에 포함했다. 기존 충돌·시간정정·NULL은 유지했다. 지점 순서를 공식 명세로 새로 독립 검증했다고 표시하지 않는다.

경주일−2일까지730일 안 최근10회 전체거리/같은거리 이력을 만들고2024·2025·2026년 각각 연도 시작 이틀 전까지로 모형을 학습했다. 예측년 학습은 고정하며 과거 이력만T−2로 갱신했다. 총17,412출전·1,779경주,주집단 정답17,382출전·1,776경주다.2024~25는12,709출전·1,288정답경주,2026은4,673출전·488경주다. 이름·ID·2026년 나이와 현재 경주 시간·착순·통과조는 입력하지 않았다. 무이력 말도 배제하지 않았다.

정상 완주·완전 경주를 사후 선별한 실제 출전목록을 경주 전에 안다고 가정한다. 당시 선언 출전표·취소·기수 변경·공개시각 재현이 아니며 이미 사용한 기간의 후향 개발 비교다. 새 독립 미래 검증으로 부르지 않는다. [사전 계약](PLAN.md)을 성능 확인 전에 고정했다.

## 내측 중간 외측의 관찰 차이

아래는 정확10두·원래마번1~10만 비교한 원시 비율이다. 내측1~3번,중간4~7번,외측8~10번이다. 각 말의 능력을 조정한 초반 차이가 아니다. 첫집단은 단독 선행·개별1위가 아니며 앞두집단은 물리적2선이 아니다.

{regiontable}

800m 표본은2017-01-13~2026-02-06,900m는2017-01-13~2026-09-18,1300m는2024-05-18~2026-09-04,1400m는2020-07-25~2026-07-11이다.900m 최종 입상690경주 가운데 S1F 품질 보류2경주는 초반 분모에서 빠져688경주다. 이를0으로 채우지 않았다.2026년은9월19일까지의 부분연도다.

{differencetable}

초반4거리×2사건×3대조의24탐색 비교를 함께BH 보정했다. 날짜집단10000회 부트스트랩 구간이며 집단 내 개별순위를 임의 복원하지 않는다. **800m는 첫집단·앞두집단에서 내측 방향,900m는 첫집단 차이는 불확실하지만 앞두집단 진입은 내측 방향**이다.1400m는 첫집단 내측−외측+14.29%p와 앞두집단+25.40%p의 원시 방향이 관측되지만63경주이고 말의 초반 능력 차이가 남는다.

최종 입상에 대한 기존 최신 같은말·같은경주·T−2 이력·연도·함수율 조정 결과는 다음과 같다. 초반 원시 차이와 구분하며 이번에 새로 추정하지 않았다.

{adjtable}

800m+11.46%p와900m+7.39%p는 기존 검정군 기준도 충족한다.1400m+10.14%p와1300m+6.05%p는 구간이0을 포함해 고정 가산으로 채택하지 않는다. 최신 원시1400m 입상률39.7%·26.6%·24.9%를 그대로 미래 확률에 붙이지 않는다. 과거 평균과 최근 효과를 구분하며800m2026년은10두3경주뿐이다.

## 게이트 구간을 추가한 재예측

M1은 자기 과거 위치·구간·최종기록·이력수·간격이다. M2는 기존 연속마번·제곱·거리 및 과거성향 상호작용,M3는 자기제외 상대 초반속도·앞선성향·안팎 경쟁을 더한다. M4는 여기에 내측/외측 지시변수·거리별 구간 상호작용·구간×과거성향/속도를 더한다. 중간이 구간 기준이다. 모두 같은 고정 로지스틱 설정이며 학습 전용 결측대치·표준화·경주가중치를 사용했고 조정 탐색을 하지 않았다.

다른 두수에서는 원래마번상대위치가 엄격히1/3미만=내측,2/3초과=외측,그 사이=중간이다. 빈마번은 압축하지 않는다.10두에서1~3/4~7/8~10과 일치한다. 원시 관찰표는10두만이며 예측표는7~13두 전체다. 모든거리·원시두수·구간을 저장했다.

{modeltable}

로그손실은 확률 예측의 틀림과 확신을 함께 평가하며 낮을수록 좋다. 후보 적중은 첫집단확률 최고1두가 실제 첫집단에 속한 비율이며 우승·단독선행 적중률이 아니다. M4의 주손실은2024~25년0.7954→0.8034,2026년0.8232→0.8290으로 M3보다 나빠졌다.

{comparetable}

주3종 전체+8거리×2기간과 보조4종 전체×2기간의20비교를 공동BH 보정했다.2024~25 주손실 악화는BH기준도 충족했으며2026 주손실은날짜·말 부트스트랩구간이0 위지만 날짜정규근사BH q=0.174로 다중검정 근거가 불충분하다. **M4의 안정적 추가 개선을 지지하는 거리는0개다.** 보조4종도2026년 손실1.0262→1.0369로 나빠졌다.

기존M3에도 마번과 안팎 상대가 들어 있어 원시 내측 우세가 발견됐다는 이유만으로 구간 지시변수를 더하면 반드시 좋아지는 것은 아니다.1300m·1610m의 학습이 적은 거리별 구간은 특히 불안정했다.2025년1300m는 학습 가능한 과거8경주뿐이다. 작은 거리별 셀의 과적합 가능성이 남지만 이번 결과를 본 뒤 수축률을 바꿔 최고값을 고르지 않았다. 게이트가 영향 없다는 증명도 아니다.

{disttable}

표본지원은 해당 평가년 학습거리50경주·평가30경주·평가일15일 기준이며 통합기간의 어느 평가년이라도 미지원이면 소표본으로 표시한다.1400m는2024~25정답38경주·2026년14경주,1300m는43·20경주다.800m는2024~25년149경주지만2026년3경주라 최근 검증이 부족하다. 큰 소표본 적중률을 안정적인 거리 성능으로 읽지 않는다.

## 선행군 후보가 빗나갔을 때 실제 위치

먼저 기존 연구와 같은 **경주마다 첫집단확률 최고1두 선택** 기준이다. 후보는 결과를 보기 전에 예측확률·동률말ID로 선택했다.2024~25년1,291선택 중 정답 없는3경주는 실패율 분모에서 제외했다.2026년488선택은 모두 집단 정답이 있다. 아래 둘째/셋째 비율의 분모는 전체 경주가 아니라 **첫집단 예측에 실패한 건수**다.

{misstable}

M4의2026년 실패196건 중 둘째집단109건55.6%(날짜95%48.5~62.9%),셋째이후87건44.4%다. 따라서 ‘선행을 못 하면 대부분 선입에 머문다’고 강하게 단정할 수 없다. 기존M3도 실패193건 가운데 둘째집단54.4%·그뒤45.6%로 비슷했다.

통과조의 둘째집단은 전통적 선입권과 같지 않다. 같은집단이 순위1/3 경계를 걸치면 확실 선입/중단을 판단하지 못한다. 그래서 동일 실패 말의 범위기반 실제 위치를 다음처럼 따로 집계했다. 모든 행의 세 범주는 실패건수를 분모로 합100%이며 판정불명을 임의로 선입이나 중단에 넣지 않는다.

{positiontable}

M4의2026년77/196=39.3%는 확실선입,53/196=27.0%는 확실중단·후미,66/196=33.7%는 판정불명이다. 판정 가능한130건만 보면 선입77/130=59.2%지만 이는 조건부 비율이다. 전체 실패의59.2%라고 바꾸어 말하지 않는다.

{missdisttable}

1400m는2026년11/14가첫집단에 들어갔고 실패3건은둘째집단2·셋째이후1이었다. 실패3건의 범위기반 판정은 모두선입권이다. 셋째집단도 앞쪽에 있을 수 있어 집단 번호와 전통 위치가 다를 수 있음을 보여준다.3건으로 일반화하지 않는다.800m 실패2건도 같은 이유로 최근 성향 결론을 내리지 않는다.

보조로 전체 말의 최다확률분류가첫집단인 예측들의 실패를 별도 표에 저장했다. 이는 경주1두 후보와 분모가 다르다. 또 위치4종 모형이‘선행권’으로 분류한2026년M4 예측은{int(four26.predicted_lead)}출전,정답확정{int(four26.known)}출전·미확정{int(four26.unknown)}출전이다. 확정표본에서틀린{int(four26.misses_known)}건 가운데선입{int(four26.front)}건{pct(four26.front_given_miss_known)},중단·후미{int(four26.middle_rear)}건{pct(four26.middle_rear_given_miss_known)}였다. 이것도 정답확정 부분집합의 조건부 결과다.

## 연구 기준과 보관

이번 결과에 따른 연구 기준은 **과거 초반 능력·위치 성향+기존 게이트+상대 안팎 경쟁인M3 유지,추가 내중외 구간M4 미채택**이다. 사용자에게는 첫/둘째/뒤집단 확률과 선행군 후보 실패 시 위치 분포를 함께 보여주는 방향이 적절하다. 전통선입과둘째집단,집단 위치와레일2선,개별확률과경주전체 공동배치는 구분한다. 정확한진로·물리주행거리·전체빠른/느린페이스·최종입상 예측을 이번 성능으로 주장하지 않는다. 운영 기준HY_R_FORM·DB·웹은 변경하지 않았다.

- [전출전 확률](run01/predictions.csv), [모형·기간·거리·두수 부분집합 지표](run01/metrics.csv), [구간추가 비교](run01/paired_comparisons.csv), [거리지원](run01/distance_support.csv)
- [원시 내중외 횟수](gate01/gate_region_counts.csv), [초반 구간과 다중비교](gate01/early_region_contrasts.csv), [기존조정Top3](gate01/previous_adjusted_top3.csv)
- [후보별 실제 위치](failures01/all_top1_candidates_with_destinations.csv), [오류분자분모·기간·거리·게이트](failures01/miss_destination_counts.csv), [위치4종선행오류](failures01/four_position_lead_failures.csv)
- [최신800·900·1300·1400m 예시](latest_race_examples.csv): 거리별 마지막경주를 날짜로 선택해 모든말의M3/M4확률을 저장했으며 적중 결과로 예시를 고르지 않았다.
- [입력·정답](features01/features_and_targets.csv), [과거원천ID](features01/history_lineage.csv), [입력해시](features01/source_manifest.json), [학습절단·수렴](run01/fit_audit.json), [변환·계수](run01/model_parameters.json), [확률진단](run01/calibration.csv), [정답커버리지](run01/target_coverage.csv)
- [피처 검증](features01/verification.json), [모형 검증](run01/verification.json), [독립 재계산](verification01/verification.json), [게이트 검증](gate01/verification.json), [오류 검증](failures01/verification.json)

104,310개 이력창과모든역사평균을 다시 계산하고 상대자기제외·내중외 정의를 확인했다.4개완전경주의현재사후관측을교란해도현재입력·예측이변하지않음을검사했다. 저장한전처리·계수로174,120개출전확률행,8,895개최고확률후보,경주로그손실을독립복원했다. 기존80개번호별Top3분자·분모도모두재현했다. 원천해시와초기자료를보존했다.
'''
    (HERE/'README.md').write_text(text)
    decision={'date':'2026-10-08','status':'gate_regions_reprediction_and_lead_miss_destinations_completed',
        'source_start':'2017-01-01','source_end':'2026-09-19','partial_2026':True,'independent_holdout':False,
        'prediction_rows':17412,'prediction_races':1779,'primary_known_rows':17382,'primary_known_races':1776,
        '1300_included_under_user_sequence_contract':True,'additional_region_model_adopted':False,'research_comparison_retained':'M3',
        'operationally_applied':False,'supported_improving_distance_comparisons':int(cmp.supported_improvement.sum()),
        'M4_2026_top1_hits':292,'M4_2026_top1_known':488,'M4_2026_top1_misses':196,
        'M4_2026_miss_second':109,'M4_2026_miss_thirdplus':87,'M4_2026_miss_front':77,
        'M4_2026_miss_middle_rear':53,'M4_2026_miss_position_unknown':66}
    save(HERE/'decision.json',decision)
    print('Report saved',flush=True)


if __name__=='__main__':main()
