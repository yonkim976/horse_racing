"""Publish a readable report from completed frozen comparisons."""
import json
import pandas as pd
from features import HERE,save


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','|'+'---|'*len(headers)]+['| '+' | '.join(map(str,r))+' |' for r in rows])


def main():
    assert json.loads((HERE/'verification01/verification.json').read_text())['status']=='passed'
    assert json.loads((HERE/'run02/verification_v3.json').read_text())['status']=='passed'
    m=pd.read_csv(HERE/'run02/metrics.csv');top=pd.read_csv(HERE/'run02/top_first_pack.csv')
    cmp=pd.read_csv(HERE/'run02/paired_comparisons.csv');cv=pd.read_csv(HERE/'run02/target_coverage.csv')
    cells=pd.read_csv(HERE/'run02/gate_speed_cells.csv');ci=pd.read_csv(HERE/'supplement01/first_selection_intervals.csv')
    def metric(task,model,period,col='logloss'):
        return m[(m.task==task)&(m.model==model)&(m.period==period)&(m.subset=='all')&(m.distance=='all')].iloc[0][col]
    def hit(model,period):
        z=top[top.model.eq(model)];z=z[z.year.le(2025)] if period=='2024_2025' else z[z.year.eq(2026)]
        return z.hit.mean()
    pct=lambda v:f'{v*100:.1f}%'
    primary=[]
    for model,desc in [('M0','거리·출전두수'),('M1','+자기 과거 기록·위치'),('M2','+이번 게이트'),('M3','+상대 구성·안팎 경쟁')]:
        primary.append([model+' '+desc,*[f'{metric("s1f_pack3",model,p):.4f}' for p in ['2024_2025','2026_partial']],
                        *[pct(hit(model,p)) for p in ['2024_2025','2026_partial']]])
    primarytable=table(['입력','24~25 로그손실','26 로그손실','24~25 첫 집단 후보 적중','26 첫 집단 후보 적중'],primary)
    effects=[]
    for r in cmp[(cmp.task=='s1f_pack3')&cmp.confirmatory_family].itertuples():
        effects.append([r.period,r.comparison,f'{r.delta_logloss:.5f}',f'[{r.date_lo:.5f}, {r.date_hi:.5f}]',
                        f'[{r.horse_lo:.5f}, {r.horse_hi:.5f}]',f'{r.BH_q:.3g}','지지' if r.supported_improvement else '불확실'])
    effectstable=table(['기간','추가 비교','로그손실 차','날짜 95%구간','말 95%구간','BH q','기간 내 개선'],effects)
    distance=[]
    for dist in [800,900,1000,1110,1200,1400,1610]:
        r=ci[(ci.period=='2026_partial')&(ci.distance.astype(str)==str(dist))].iloc[0]
        status='지원' if dist in [900,1000,1110,1200] else '소표본·미지원'
        distance.append([dist,int(r.races),f'{pct(r.hit)} [{pct(r.hit_lo)}, {pct(r.hit_hi)}]',pct(r.random_baseline),status])
    disttable=table(['거리m','2026 경주','첫 집단 후보 적중 [날짜95%구간]','무작위 기대','표본 지원'],distance)
    gates=[]
    for r in cells[cells.period.eq('2026_partial')].itertuples():
        gates.append([r.gate_band,'빠른 1/3' if r.fast_third else '나머지',r.rows,pct(r.first_observed),pct(r.second_observed),
                      pct(r.first_observed+r.second_observed),pct(r.inside_observed),pct(r.inside_predicted)])
    gatetable=table(['마번','과거 초반 속도','출전수','첫 집단','둘째 집단','앞 두 집단','둘째 집단 내측쪽 관측','대용치 예측'],gates)
    auxiliaries=[]
    for task,label in [('c4_pack3','4C 집단3종'),('g1f_pack3','G1F 집단3종'),('s1f_position4','S1F 위치4종·정답확정 부분집합'),('s1f_second_inside','S1F 둘째 집단 내측쪽 대용치')]:
        r=cv[(cv.period=='2026_partial')&(cv.task==task)].iloc[0]
        auxiliaries.append([label,int(r.known_rows),pct(r.coverage),pct(metric(task,'M0','2026_partial','accuracy')),
                            pct(metric(task,'M3','2026_partial','accuracy')),f'{metric(task,"M1","2026_partial"):.4f} → {metric(task,"M3","2026_partial"):.4f}'])
    auxtable=table(['목표','2026 정답 출전수','정답 커버리지','기준 정확도','전체입력 정확도','과거만→전체 로그손실'],auxiliaries)
    text=f'''# 제주 과거 성향·게이트·상대 구성으로 다음 경주 위치를 예측할 수 있는가

2026-10-08 완료. **초반 집단 위치는 어느 정도 예측할 수 있고, 자기 과거 기록이 가장 큰 근거다. 상대의 초반 성향과 이번 안팎 경쟁 구성을 추가한 개선은 두 기간에서 재현됐다. 게이트만 추가한 개선은 2026년 주 대상에서 불확실하며, 실제 내측 2선 자리잡기는 확인하지 못했다.** 후향적 연구 후보이며 운영 적용은 하지 않았다.

## 자료와 시간순 비교

품질 보류·공식 말ID 연결을 유지한 2017-01-01~2026-09-19의52,155출전·5,206경주·2,813두를 원천으로 재사용했다. 1300m의 초반 측정 정의가 미확정이라 이번 예측 비교에서는 제외했다. 실제 모델 대상은51,549출전·5,143경주다. 400m는 워밍업 자료로 제외하며1610m는 소표본이다.

각 출전의 경주일−2일까지730일 안 최근10회를 전체거리와 같은거리로 각각 만들었다. 현재 경주 시간·착순·통과조·사후 유형과 최신 전체기간 프로필을 입력하지 않았다. 이름·공식 말ID·2026년 나이는 예측 피처가 아니다. 현재 거리·마번·실제 출전두수·참가목록을 알려진 것으로 가정한다. 자기 이력이 없는 말도 유지했다.

2024·2025·2026년 각각 연도 시작 이틀 전까지의 자료로 고정 로지스틱 모형을 학습하고 해당 연도를 예측했다. 2026년 상한은9월19일이다. 총16,806출전·1,716경주를 예측했고 주 대상 정답은16,776출전·1,713경주에서 가용하다. 2024~25는12,295출전·1,245경주,2026은4,481출전·468경주다. 모형60개 모두 사전 고정한 설정으로 수렴했고 성능을 보고 조정하지 않았다.

평가 표본은 정상 완주·완전 경주를 사후 선별한 실제 출전집합이다. 당시 선언 출전표·취소·기수 교체·공개시각을 재현한 실서비스 검증은 아니다. 이 기간은 앞선 연구에서도 사용했으므로 독립 미래 검증으로 부르지 않는다. 모든 입력과 평가 기준은 [사전 계획](PLAN.md)에 고정했다.

## 초반 집단 예측 성능

정답은 S1F의 **첫 집단 / 두 번째 집단 / 그 뒤 집단**이다. 첫 집단은 단독 선행·우승·최종입상이 아니다. 같은 집단 안 순서를 개별 순위로 바꾸지 않는다.

{primarytable}

로그손실은 틀린 곳에 높은 확률을 준 정도까지 평가하며 작을수록 좋다. 경주마다 같은 비중을 줬다. ‘첫 집단 후보 적중’은 첫 집단 확률이 가장 높은1두를 골랐을 때 실제 첫 집단에 속한 비율이다. M0는 같은 경주에서 모든 말의 확률이 같아 말ID 순서로 동률을 풀었으므로 후보 적중률을 무작위 성능으로 읽으면 안 된다.

M3의 첫 집단 후보 적중은2024~25년62.6%(날짜95%구간60.0~65.2%),2026년60.5%(56.3~64.3%)다. 실제 집단 크기를 고려한 무작위1두 기대 적중은 각각20.4%·20.8%다. 첫 집단에 여러 말이 들어갈 수 있다.

모든 말의3종 집단 위치 정확도는 M3에서64.1%·62.6%이며 M0는56.8%·55.7%다. 주 손실은 자기 과거만 쓰는 M1에서 M3로 각각0.8226→0.7967,0.8530→0.8271로 약3.1%·3.0% 줄었다. 후보 적중의 작은 증가 자체를 유의한 개선으로 검정한 것은 아니며 추가 입력 판정은 사전 고정한 로그손실을 따른다.

## 게이트와 상대 구성의 추가 가치

{effectstable}

5목표×2기간×3증분의30비교를 함께 BH 보정했다. 날짜2000회 짝지은 집단 부트스트랩과 말 집단 민감도에서 모두 손실 차95%구간이0 아래이고q<0.05인 경우만 기간 내 개선으로 표시했다. 주 대상에서 **상대 구성 M3−M2는 두 기간 모두 지지**, **게이트 M2−M1은2024~25만 지지**됐다. 게이트가 불필요하다는 증명이 아니라, 과거 기록이 이미 있는 상태의 추가 가치가 작고 최근 크기가 불확실하다는 결과다.

상대 입력에는 자기보다 안쪽·바깥쪽 말의 과거 첫 집단 성향 합, 강한 앞선 성향 말 수, 편성 안 상대 초반 속도, 자기보다 빠른 상대 수, 게이트와 경쟁 강도의 상호작용이 들어간다. 즉 같은 말도 안쪽에 빠른 말이 몇 두 있는지에 따라 확률이 달라지는 구조다. 인과적인 게이트 효과나 기수의 이동 의도를 추정한 것은 아니다.

## 외측의 빠른 말은 앞에 붙는가

정확10두·마번1~10 경주 중 과거 상대 S1F 시간3회 이상인 말들을 비교했다. 속도 이력이 유효한 말이8두 이상인 편성에서 빠른1/3을 정했다. 아래는2026년 조건부 원시 관측 비율이며 거리 통합·말/편성 선택이 남아 있다. 게이트를 무작위 배정한 효과나 동일 말의 이동 확률이 아니다.

{gatetable}

외측8~10번의 과거 빠른 말307출전은 첫 집단40.4%·둘째 집단28.0%, 합계68.4%였다. 외측의 나머지526출전은 첫 집단7.6%·둘째 집단12.5%, 합계20.2%였다. **외측이라는 이유만으로 후미를 예측하기보다 말의 초반 능력과 상대 구성을 함께 봐야 한다는 관찰 근거**다. 내측 빠른 말321출전의 앞 두 집단 비율은74.8%였다. 이 차이를 고정 보정치로 채택하지 않았다.

괄호 안 상대 내외측 순서로 ‘둘째 집단의 내측쪽’ 대용치는 만들 수 있지만 레일에서2번째 줄·앞말 바로 뒤·외측에서 들어온 이동 경로는 확인할 수 없다. 대용치는 둘째 집단2두 이상·내부 상대 순번0.5이하이며 홀수 중앙도 포함한다. 단독 둘째 집단은 이 복합사건에 해당하지 않는다.

이 대용치의2026년 로그손실은 과거만0.3580→게이트·상대포함0.3720으로 오히려 나빠졌다. 게이트 추가의 악화는 날짜·말 구간 모두0 위이고BH q=0.030이다. 외측 빠른 말의 실제 대용치 빈도9.8%에 예측은3.5%로 낮았다. 따라서 **내측 2선 자리잡기를 잘 예측한다고 말할 근거는 부족하다.** 대용치 미해당이 약88%여서88% 분류 정확도는 성능 근거가 되지 않는다.

## 거리별 지원과 막판 위치

{disttable}

날짜별2000회 부트스트랩 구간이다.2026년은900·1000·1110·1200m가 최소 학습50경주·평가30경주·평가15일 기준을 충족한다.800m는2024·25년에 각각106·43경주가 있지만2026년3경주라 최근 거리별 재현을 판단하지 않는다.1400m는 평가가 연14~24경주,1610m는 연0~6경주로 미지원이다. 거리별 후보 적중 수치는 차이의 유의성이나 거리 간 우열 검정이 아니다.

{auxtable}

4C·G1F도 현재 경주 초반 관측 없이 경주 전 과거 자료로 예측했다. 뒤 집단 비중이 달라 목표 간 정확도 수치를 그대로 비교하지 않는다. 선행권·선입권·중단·후미4종은 집단 순위 범위가 경계와 겹치지 않는 정답 확정68.5%에서만57.6% 정확도였다. 나머지31.5%까지 맞힌 것으로 해석하지 않는다. 이 조건부4종에서는 게이트 증분도 두 기간 지지됐지만 주 대상 전체표본 결론을 대체하지 않는다.

첫 집단 확률 구간별 관측률도 저장했다.2026년 예측 평균54.4%인206출전의 관측률은58.3%,예측64.8%인131출전의 관측률은58.8%였다. 개별 표시 확률을 정확한 미래 보증으로 보지 않으며 높은 확률 구간과 드문 내측 대용치는 더 불확실하다.

## 해석과 다음 적용 단위

기본 각질을 고정1개로 붙이는 방식보다 ‘이번 편성에서 첫/둘째/뒤 집단 확률’로 표시하는 연구 방향이 타당하다. 자기 최근 위치·초반 상대 시간·같은 거리 이력을 중심으로 이번 게이트와 안팎 경쟁을 함께 쓰면 된다. 예를 들어 ‘평소 앞선 성향이지만 안쪽 빠른 상대가 많아 첫 집단 확률이 낮아짐’,‘외측이나 상대 초반 능력 우위로 앞 두 집단 가능성 있음’처럼 입력에 근거한 설명이 가능하다.

이번 결과가 검증한 것은 집단 위치의 후향적 예측력이다. 빠른/느린 전체 페이스, 정확한 개별 통과순위, 진로, 레일2선, 선행 경합의 공동 확률, 최종입상은 이번 검증 대상이 아니다. 말별 집단 확률 합1과 경주 전체 배치 공동확률은 구분한다. 운영 입력 채택·웹 표시·DB 변경은 하지 않았다.

## 산출물과 검증

- [모든 출전 확률](run02/predictions.csv), [연도·기간·거리·이력수별 지표](run02/metrics.csv), [짝지은 비교](run02/paired_comparisons.csv)
- [첫 집단 후보와 실제 결과](run02/top_first_pack.csv), [거리별 구간](supplement01/first_selection_intervals.csv), [게이트×과거 속도 원표](run02/gate_speed_cells.csv)
- [확률 보정 진단](run02/calibration.csv), [목표 정답 커버리지](run02/target_coverage.csv), [거리 지원](run02/distance_support.csv)
- [최신800·1000·1110m 경주의 사전 확률과 사후 대조 예시](supplement01/latest_race_examples.csv): 맞힌 경주를 고르지 않고 거리별 마지막 경주를 선택했다.
- [입력·정답](features01/features_and_targets.csv), [출전별 과거 원천ID](features01/history_lineage.csv), [입력 해시](features01/source_manifest.json), [학습 절단·수렴](run02/fit_audit.json), [변환·계수](run02/model_parameters.json)
- [독립 재계산 검증](verification01/verification.json), [최종 실행 검증](run02/verification_v3.json)

독립 검사로104,310개 이력 창을 다시 선택하고, 상대 집계208,620건을 대조했다. 최신1000m 완전 경주의 모든 현재 사후 관측값을 교란해도 현재 입력·예측이 같음을 확인했다. 저장한 변환·계수로336,120개 확률 행과 경주별 로그손실을 재현하고 입력 해시를 대조했다.

첫 실행은 읽기 전용 NumPy 가중치 배열의 제자리 연산에서 학습 전에 중단됐다. 복사 후 별도run02에서 전체 학습·평가를 마쳤다. 최종 해시 확인 코드의 경로 연산 오타는 별도 검증 스크립트로 고쳤다. 초기 코드·실패 기록·모든 계산 결과를 보존했고 데이터·계획·모형 설정·평가값은 바꾸지 않았다.
'''
    (HERE/'README.md').write_text(text)
    decision={'status':'retrospective_position_prediction_completed','operationally_applied':False,'independent_holdout':False,
        'primary':'s1f_pack3','evaluation_rows':16806,'evaluation_races':1716,'primary_known_rows':16776,'primary_known_races':1713,
        'source_end':'2026-09-19','partial_2026':True,'gate_increment_replicated_primary':False,
        'opponent_increment_replicated_primary':True,'physical_inner_second_lane_observed':False,
        'second_pack_inside_proxy_2026_improved':False,'early_definition_held_distances':[1300],
        '2026_supported_distances':[900,1000,1110,1200],
        'M3_first_pack_selection_hit_2024_2025':hit('M3','2024_2025'),'M3_first_pack_selection_hit_2026':hit('M3','2026_partial')}
    save(HERE/'decision.json',decision)
    print('Report saved',flush=True)


if __name__=='__main__':main()
