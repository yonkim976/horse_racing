"""Generate the completed Busan diagnosis, cases, and indexed evidence report."""
import json,importlib.util
import pandas as pd
import axis_common as c

spec=importlib.util.spec_from_file_location('grade5_archive',c.HERE/'archive.py')
arc=importlib.util.module_from_spec(spec);spec.loader.exec_module(arc)

def main():
    c.check();d=json.loads((c.OUT/'diagnostics.json').read_text());r=json.loads((c.OUT/'switch_results.json').read_text())
    v=json.loads((c.OUT/'verification.json').read_text());e=json.loads((c.OUT/'decision_explanations.json').read_text())
    assert v['status']=='passed' and not r['retain'] and e['maximum_score_reconstruction_error']<1e-10
    cases=pd.read_parquet(c.OUT/'target_cases.parquet');out=pd.read_parquet(c.OUT/'axis_predictions.parquet')
    assert len(cases)==210 and int(cases.axis_hit.sum())==120
    assert r['comparisons']['candidate']['target']['net_hits']==-6 and r['comparisons']['selected']['switches']==0
    summaries={x['scope']:x for x in d['summary']}
    baseline=['| 기간·거리 | 경주 | 축 적중 | 축 실패 | 축 적중률 | 평균 예측확률 |',
        '|---|---:|---:|---:|---:|---:|']
    names={'all_target':'전체 대상','year_2024':'2024년','year_2025':'2025년','year_2026':'2026년(~9/20)',
        'distance_m_1300':'1,300m','distance_m_1600':'1,600m'}
    for key,label in names.items():
        z=summaries[key]
        baseline.append(f"| {label} | {z['races']} | {z['hits']} | {z['misses']} | {100*z['hit_rate']:.2f}% | {100*z['predicted_mean']:.2f}% |")
    controls=[];controltable=['| 연도 | 부산 전체 축 적중 | 국5 대상 1300·1600m | 국5 다른 거리 |',
        '|---|---:|---:|---:|']
    for year,g in out.groupby('year'):
        target=g[g.target];other=g[g.grade_raw.eq('국5등급')&~g.target]
        row={'year':int(year),'all_races':len(g),'all_hits':int(g.axis_hit.sum()),
            'target_races':len(target),'target_hits':int(target.axis_hit.sum()),'other_grade5_races':len(other),'other_grade5_hits':int(other.axis_hit.sum())}
        controls.append(row)
        fmt=lambda z:f"{100*z.axis_hit.mean():.2f}% ({int(z.axis_hit.sum())}/{len(z)})"
        controltable.append(f'| {year} | {fmt(g)} | {fmt(target)} | {fmt(other)} |')
    recent=cases[cases.year.eq(2026)];failed=recent[recent.axis_hit.eq(0)]
    extra={'post_hoc_descriptive_only':True,'year_controls':controls,
        'recent_failed_middle_or_back':int(failed.observed_role.isin([2,3]).sum()),
        'recent_failed_first_group_and_lost_last200':int((failed.observed_role.eq(0)&failed.observed_gain200.lt(0)).sum()),
        'recent_miss_second_recovers':int(failed.alt_hit.sum()),
        'recent_miss_only_third_recovers':int((failed.alt_hit.eq(0)&failed.third_hit.eq(1)).sum()),
        'recent_miss_neither_second_nor_third':int((failed.alt_hit.eq(0)&failed.third_hit.eq(0)).sum())}
    c.save(c.OUT/'descriptive_supplement.json',extra)
    conditions=['| 2026년 사전 조건 | 경주 | 축 적중 | 적중률 | 평균 예측확률 |',
        '|---|---:|---:|---:|---:|']
    labelmap={('axis_probability','<.55'):'예측확률 55% 미만',('axis_probability','.55-.70'):'예측확률 55~70%',
        ('axis_probability','>=.70'):'예측확률 70% 이상',('promoted','yes'):'직전 대비 승급',('promoted','no'):'승급 아님',
        ('promoted','missing'):'직전 등급 비교 불가',('same_distance','zero'):'최근5전 동거리 경험 없음',
        ('same_distance','one_or_more'):'최근5전 동거리 경험 있음',('faster_opponents','>=2'):'초반 더 빠른 상대 2두 이상',
        ('faster_opponents','<2'):'초반 더 빠른 상대 2두 미만',('days_since_last','<21'):'21일 미만 재출전',
        ('days_since_last','21-60'):'21~60일 재출전',('days_since_last','>60'):'60일 초과 휴양'}
    lookup={(z['condition'],z['value']):z for z in d['pre_race_conditions'] if z['scope']=='2026'}
    for key,label in labelmap.items():
        if key not in lookup:continue
        z=lookup[key];conditions.append(f"| {label} | {z['races']} | {z['hits']} | {100*z['hit_rate']:.2f}% | {100*z['predicted_mean']:.2f}% |")
    switches=['| 기간 | 기존 축 | 교체 원형 | 바꾼 경주 | 새 적중 / 기존 적중 누락 | 순증 |',
        '|---|---:|---:|---:|---:|---:|']
    for key,label in [('target','전체 대상'),('target_2024','2024'),('target_2025','2025'),('target_2026','2026')]:
        q=r['comparisons']['candidate'][key];n=int(out.candidate_switch.sum()) if key=='target' else int(out.loc[out.year.eq(int(label)),'candidate_switch'].sum())
        switches.append(f"| {label} | {q['baseline_hits']}/{q['races']} ({100*q['baseline_rate']:.2f}%) | {q['candidate_hits']}/{q['races']} ({100*q['candidate_rate']:.2f}%) | {n} | {q['gained']} / {q['lost']} | {q['net_hits']:+d} |")
    gates=['| 평가연도 | 전년도 H2 대상 경주 | 교체 | 대상 순증 | 부산 전체 적용시 순증 | 선택 |',
        '|---|---:|---:|---:|---:|---|']
    for z in r['selection']:
        gates.append(f"| {z['evaluation_year']} | {z['validation_target_races']} | {z['validation_target_switches']} | {z['validation_target_net']:+d} | {z['validation_all_busan_net']:+d} | {'교체' if z['selected'] else '기존 유지'} |")
    explanations=['| 모델 점수 기여 묶음 | 축 실패·2순위 입상 25경주 | 축 입상·2순위 실패 19경주 |',
        '|---|---:|---:|']
    q={x['case']:x for x in e['summary'] if x['period']=='2026'}
    enames={'dynamic_rank':'동적 순위 상태','historical_late_style':'과거 종반·회복/후퇴',
        'dynamic_close':'동적 종반 상태','historical_early_gate':'과거 초반·게이트',
        'historical_record_profile':'과거 기록·프로필','carried_weight':'부담중량'}
    for key,label in enames.items():
        explanations.append(f"| {label} | {q['axis_missed_alt_hit']['group_mean_contributions'][key]:+.4f} | {q['axis_hit_alt_missed']['group_mean_contributions'][key]:+.4f} |")
    case_table=['| 날짜·부산 경주 | 거리 | 원래 축(마번) | 예측 Top3 | 실제 | 2순위(마번) | 실제 |',
        '|---|---:|---|---:|---:|---|---:|']
    for row in failed.sort_values(['race_date','race_key']).itertuples():
        number=row.race_key.rsplit(':',1)[1]
        case_table.append(f'| {row.race_date:%m-%d} {number}R | {row.distance_m:.0f}m | {row.axis_horse_name_raw}({row.axis_program_no}) | {100*row.axis_probability:.2f}% | {row.axis_finish_order}위 | {row.alt_horse_name_raw}({row.alt_program_no}) | {row.alt_finish_order}위 |')
    changed=['| 경주 | 기존 마번·결과 | 교체 마번·결과 | 모델 기대득 | 실제 적중 차이 |',
        '|---|---|---|---:|---:|']
    for row in out[out.candidate_switch].sort_values(['race_date','race_key']).itertuples():
        changed.append(f'| {row.race_key} | {row.axis_program_no}번·{row.axis_outcome}위 | {row.alt_program_no}번·{row.alt_outcome}위 | {row.expected_gain:+.4f} | {row.candidate_hit-row.axis_hit:+d} |')
    (c.HERE/'CASES_2026.md').write_text(f'''# 2026년 부산 국5등급 대상 축 실패 36경주

대상은1,300m·1,600m이며 기준은 연구58C state_gbm이다. 최종 결과를 보고 모은 사후 사례표다. 운영의 당시 추천이었다는 뜻은 아니다. 확률은 기준 공동착순 분포에서 계산한Top3 주변확률이다.

{chr(10).join(case_table)}

## 교체 원형이 실제로 바꾼 15경주

새로 적중2·기존 적중 누락8·변화 없는5경주다. 전년도 선택 정책은 세 연도 모두 기존축을 유지했으므로 아래 변경을 실제 채택하지 않았다. 기대득은 교체만 적중할 확률과 기존축만 적중할 확률의 차이이며, 말 자체의 입상확률이 아니다.

{chr(10).join(changed)}

[해석과 검증](README.md) · [전체210경주 사례](outputs/target_cases.parquet) · [교체 예측](outputs/axis_predictions.parquet).
''')
    note='부산 국5등급 1300·1600m는 2026년 축 적중36/72였다. 전년도 학습 교체 원형은 전체120→114적중으로 악화해 채택하지 않았다.'
    report=f'''# 부산 국5등급 1,300m·1,600m 축 실패 진단과 교체 시험

2026-10-22 · 연구58E · 부산 대상 분석 · 역사적 개발 자료 · 운영 미반영.

**2026년 대상 72경주에서 축을 36번 놓쳤다. 그중 25경주는 기존 2순위가 입상했지만, 이를 미리 골라 바꾸는 이번 보완책은 실패했다.** 전년도 자료로 학습한 교체 원형을 적용하면 전체 대상 적중이 120→114로 줄었다. 사전 검증으로 사용 여부를 정한 정책은 세 연도 모두 기존 축 유지를 선택했다. 추가 적중 개선을 보고할 결과는 없으며, 실패 양상과 다음에 검증할 가설을 남긴다.

## 정확한 대상과 기준

기준 모델은 직전 연구에서 유지한 전체 상태29 + GBM(state_gbm)이다. 운영 모델의 성적이 아니다. 서울·부산 전체 4,799경주 중 부산 1,961경주를 보존하고, 국5등급 1,300m·1,600m의 210경주를 주집단으로 고정했다. 해당 집단은 앞선 2024~2026년 결과를 보고 골랐으므로 선택 편향이 있다. 2026년은 9월 20일까지의 부분연도이며 부산 원천의 마지막 경주는 9월 18일이다.

축은1두·3착 이내다. 복승/복연 쌍 추천은 바꾸지 않았고 기존 공동확률도 보존했다. 이번 실험은 추천 축을 기존1순위에서2순위로 바꿀지의 문제만 시험했다.

{chr(10).join(baseline)}

{chr(10).join(controltable)}

대상 적중률은61.90→60.00→50.00%로 낮아졌지만 평균 축 확률은매년61.6% 수준이었다. 반면2026년 부산 전체는64.04%, 국5등급의 다른 거리는66.67%였다. 이번 약점을 부산 전체의 동일한 악화로 해석하지 않는다. 이 표는 집단 난이도와 편성 변화까지 통제한 인과 비교가 아니다.

## 무엇을 놓쳤는가

2026년 실패36경주 중15경주는4~5위,21경주는6위 이하였고 비완주·실격은 없었다. 간발의3착 누락만으로 설명되지 않는다. 전체기간 실패90경주는4~5위36·6위 이하54였다.

실패36경주를 기존 후보 순위로 나누면 다음과 같다.

- 2순위가 입상한 경주25개.
- 2순위는 실패하고3순위가 입상한 경주6개.
- 2·3순위도 모두 실패한 경주5개.

즉 기존 상위3후보 중 실제 입상마는2026년67/72경주에 있었지만, 그중 한 두를 고르는 데 실패한 경우가 많았다. 67/72는 후보3두 중 최소1두가 입상했다는 사후 진단이며 축1두 적중률이나 실현 가능한 교체 성과가 아니다. 선택 예산을 늘려 성능 개선으로 포장하지 않는다.

2순위로 항상 바꾸는 방법도 일관되지 않았다. 2024년에는39→30적중(−9),2025년45→38(−7),2026년36→42(+6)이었다. 2026 결과를 본 뒤2순위를 고르면 좋아 보이지만, 전체기간에는120→110으로 더 나쁘다. 전년도 관계가2026에 그대로 이어지지 않은 점이 이번 교체학습의 어려움이다.

## 승급·거리 미경험 하나로 설명되지는 않는다

{chr(10).join(conditions)}

2026년 승급 축 22경주와 승급이 아닌 48경주의 적중률은 둘 다 50%다. 최근 5전 동거리 경험이 없는 축도 17/32(53.12%)로, 경험이 있는 축 19/40(47.50%)보다 나쁘지 않았다. 따라서 '승급하면 피한다', '동거리 경험이 없으면 축에서 뺀다'는 규칙은 이번 진단의 결론이 아니다. 직전 등급이 OPEN 등으로 숫자 비교가 되지 않는 2경주는 별도로 표시했다.

초반 더 빠른 상대가2두 이상인 경우2026년17/37(45.95%),2두 미만19/35(54.29%)였다. 전체기간에는각각53/106(50.00%)와67/104(64.42%)로 차이가 있었다. 이는 과거 구간으로 계산한 상대수와 실패의 연관성이다. 실제 경합이나 외곽 주행 손실을 측정한 값이 아니고, 여러 조건을 본 사후 기술통계이므로 독립 원인이나 배제규칙으로 확정하지 않는다. 휴양·짧은 재출전 구간은 표본이 특히 작다. [모든 사전 조건 집계](outputs/diagnostics.json).

확률70% 이상으로 평가한2026년16경주도 실제로는8경주만 맞혔다. 이 집단의 평균 예측은75.94%였다. 선택된 작은 집단에서 확신이 과했던 사례이며, 전체 모델의 모든70% 예측이50%라는 뜻은 아니다. 확률을 일괄 낮추는 보정은 같은 경주 안의 순위를 바꾸지 않으므로 그 자체로 축 적중을 높이지도 않는다.

## 사후 전개에서 확인한 두 가지 모습

실패36경주 중20경주의 축은 실제 초반에 중단/후미 마군에 있었다. 다른9경주는 초반 첫 마군에 있었으나 마지막200m에서 상대 순위를 잃었다. 두 집단은 겹치지 않는다. 남은7경주에도 다른 전개가 있어 한 가지 유형으로 묶을 수 없다.

전체적으로 실패축은마지막200m 순위 하락이21/36, 성공축은7/36이었다. 실패축의 마지막600m 평균은40.04초, 성공축은38.75초였다. 이는 이미 결과가 나온 뒤의 관측이며 거리·경주환경·편성까지 통제하지 않았다. 종반 순위이동 계산에는 최종착순도 들어가므로 실패와의 연관성이 일부 기계적이다. 체력 붕괴나 기수 의도 등의 원인을 확정하는 증거가 아니다. 현재 실제 구간·마군은 교체 판단 입력으로 쓰지 않았다.

## 모델은 왜 잘못된 축을 더 높게 보았나

교체 결과를 확정한 뒤, 기존 GBM의 입력별 점수 기여를 추가로 분해했다. LightGBM의 가산적 tree attribution을 1순위−2순위로 계산했다. 단위는 원모델 점수이며 확률 %p가 아니다. 표의 양수는 기존 축 쪽으로 점수를 올린 기여다. 집단은 2026년의 두 말 중 하나만 입상한 사례이며, 일부 묶음만 아래에 표시하고 전부는 JSON에 보존했다.

{chr(10).join(explanations)}

축을 놓치고2순위가 입상한25경주에서는 원점수 격차평균+0.4903 중 동적 순위 묶음이+0.3769였다. 특히 편성 내 현재거리 능력 차이·순위가 축 선정을 밀었다. 그러나 기존축만 맞힌19경주에서도 같은 묶음의기여는+0.3758로 거의 같았다. **순위 상태가 잘못된 축을 지지하기도 했다는 사실만으로 그 가중치를 일괄 낮추면 된다는 결론은 나오지 않는다.** 맞힌 선택도 같은 신호를 사용했다.

과거 초반·게이트 묶음의 평균 기여는 놓친25경주+0.0110,기존축만 맞힌19경주+0.0509였다. 순위 능력 우위가 실제 편성에서 실현될 조건을 더 구분할 필요가 있다는 후속 가설은 생긴다. 다만 이 집계는 결과로 나눈 사후 설명이고 입력 간 상호작용이 배분된 값이다. 새 가중치나 문턱을 정하는 인과 효과로 사용하지 않았다. [점수 분해](outputs/decision_explanations.json).

## 전년도 자료로 시험한 축 교체 결과

숫자 입력 29개와 결측 표식 29개를 사용해 '기존 축만 입상/두 말 모두 입상 또는 모두 미입상/2순위만 입상'의 세 경우를 학습했다. 점수 차이, 두수·거리·등급, 축의 이력·초반 상대·불확실성, 두 말의 기록·구간·거리 변경·승급·상태 차이를 썼다. 기존 기본모델은 새로 학습하지 않았다.

각 평가연도 Y의 기존 GBM은 Y−2까지 학습했고, 그 모델이 학습하지 않은 Y−1 점수로 교체모형을 적합했다. 전년도 상반기에 한 번 적합하고 하반기에서 대상 교체≥5·대상 순증>0·부산 전체에 적용했을 때 순증≥0이면 사용하기로 사전에 정했다. 최종 계수는 전년도 전체로 한 번 재적합했다. 같은 해 평가 정답을 학습·선택에 쓰지 않았다. 전체 평가기간 자체는 이미 여러 연구에서 봤다는 한계는 남는다.

평균 다항 NLL에 0.1/2×절편 제외 계수제곱을 더한 목적함수를 사용했다. 중앙값 대체·표준화는 학습 자료에서만 계산하고 표준화 값을 ±8로 제한했다. L-BFGS-B 최대 300회, 고정 교체 문턱은 0.05다. 교체 기대득=P(2순위만 입상)−P(기존 축만 입상)이며 말 자체의 입상확률은 아니다. 기대득>.05인 대상 경주에서만 2순위로 바꾼다. 사후 진단을 보고 변수나 문턱을 재탐색하지 않았다.

{chr(10).join(switches)}

원형은 15경주를 바꿔 새 적중 2·기존 적중 누락 8·동일 5, 순손실 6경주였다. 대상 적중률은 57.14→54.29%, 차이 −2.86%p(날짜 paired bootstrap 95% −5.83~0.00%p), 상대 −5.00%였다. 2026년만은 50.00→45.83%, −3경주다. 작은 표본이지만 개선 증거가 없다는 판단은 명확하다.

{chr(10).join(gates)}

전년도 선택정책은 세 연도 모두 기존 축 유지였다. 따라서 최종 선택정책의 대상 적중은 120/210, 2026년 36/72로 그대로다. 미래 실전에 적용한 결과가 아니라 시간순 개발 평가에서 적용 여부를 판정한 것이다. 사전 채택 조건인 대상 차이 95% 하한>0, 2026년 순증≥0, 전체 손실 없음을 통과하지 못했다.

부산 전체 원형은 1,210→1,204적중, 서울 포함 4,799경주에서는 3,051→3,045였다. 선택정책은 모두 기존과 같다. 복승/복연 추천은 경주별 기존 그대로이며, 축만 바꿔 복승 적중도 늘었다고 주장하지 않는다. 금전 수익률은 측정하지 않았다.

## 사례와 재현 검증

예를 들어 2026-06-07 부산 3경주는 파워타이거(5번)를 85.26%로 평가했지만 4위였고, 2순위 벌마의랜드(8번)는 1위였다. 2026-07-24 부산 4경주는 위대한하트(6번)를 73.29%로 평가했지만 9위, 2순위 서귀크레스트(5번)는 1위였다. 한편 2026-08-16 부산 2경주는 프라임제니(1번) 7위·스카이넥스(10번) 8위로 2순위 교체도 해결하지 못했다. 확신이 높았던 축의 실패와 동반 후보 실패가 함께 존재한다. [2026년 실패 36경주와 원형 교체 15경주 전체](CASES_2026.md).

- 모델 학습 전 합성 자료의 다항 목적함수 gradient, 결측·상수열 처리, 현재 정답/사후 구간 변조 시 예측 불변을 검사했다. [학습 전 검사](outputs/preflight.json).
- 기본 3모델의 저장 점수 {v['base_score_rows_replayed']:,}행 재현 차이 0, 저장 교체 계수의 평가 예측 {v['switch_probability_rows_replayed']:,}행 재현을 통과했다.
- 원형·선택정책 축 예측 {v['axis_predictions_directly_scored']:,}건을 DB의 공식 정상 착순으로 직접 채점했다. 대상 밖 추천 불변, 선택 축의 확률이 기존 공동분포 주변확률과 같음을 검사했다.
- 전년도 사전 선택을 재계산하고, 모든 4,104쌍의 입력을 원특징에서 다시 검산했다. 승급·직전 거리 원전적 100건과 source_date≤T−2를 확인했다. 현재 정답 변조에도 추천이 그대로였다.
- 가산적 점수 분해 420개 출전마의 합을 원점수와 비교한 최대 오차는 {e['maximum_score_reconstruction_error']:.3g}이었다. 새 설명모형을 학습하지 않았고, 분해는 교체모형 평가 뒤 추가한 사후 진단이다.
- 원천 DB·기존 특징/상태/모델·운영 레지스트리·동결 코드 해시는 같았다. [검증](outputs/verification.json). 외부 독립 리뷰어의 검증은 아니다.

## 결론과 한계

이번에는 상위 후보 중 한 두를 고르는 판단과, 추정 능력이 실제 편성에서 실현될 조건을 더 구분해야 한다는 근거를 얻었다. 승급이나 거리 미경험만으로 해결할 수 있다는 근거는 없었다. 시험한 교체 방식은 실패했으므로 기존 state_gbm을 연구 기준으로 유지한다. 상대 10% 적중 개선은 달성하지 못했다. 다음 가설은 능력 우위가 있어도 초반 위치 확보·종반 유지 근거가 약한 상황을 구분하는 것이며, 이번 결과만으로 고정 감점 규칙을 만들지 않는다.

이 집단은 이미 본 2026년 성적을 계기로 선정했고, 같은 2024~2026년 개발 자료를 반복 사용했다. 날짜 단위 bootstrap 2,000회·시드 20261025는 집단별 기술적 구간이며, 다중비교 보정이나 집단 선택 편향 해결이 아니다. 동일 말의 다른 날짜 간 상관도 완전히 처리하지 않는다. 2026년 소표본·부분연도·현재 부담중량/확정명단의 당시 공시시각 한계가 남는다. 주로빠르기·현재 실제 구간/배당을 입력에 추가하지 않았다. 새 미사용 기간 검증은 수행하지 않았다.

운영 모델 `thoroughbred-main-20260919-v1` / `thoroughbred-abc-current-a-b-c-20260919`는 변경하지 않았다. DB 쓰기·새 수집·예측 게시·배포·예약도 없다. 새 연구 보고서·중앙결론 58E·미게시 요약·중앙 5문서·자기포함 용량명세를 완성했다. 앞선 5연구 139,039,058 bytes와 합쳐 300,000,000 bytes 미만을 검사한다.

[사전계획](PLAN.md) · [진단](outputs/diagnostics.json) · [교체결과](outputs/switch_results.json) · [미게시요약](PUBLICATION.md) · [용량명세](outputs/artifact_inventory.json) · [선행58D](../20261022_state_followup_v1/README.md).
'''
    (c.HERE/'README.md').write_text(report)
    short=f'''# 부산 국5등급 축 실패를 더 살펴본 결과

2026-10-22 · 연구58E · 웹사이트 미게시 · 운영 미반영.

{note}

대상은 부산 국5등급 1,300m·1,600m다. 2026년 모델의 평균 축 입상 예측은 61.6%였지만 실제는 50%였다. 실패 36경주 중 25경주는 기존 2순위가 입상했다. 하지만 전체기간에 2순위로 일괄 교체하면 120→110적중으로 나빠진다.

전년도 자료로 교체 이득·손실을 학습한 보완책도 15경주 교체에서 새 적중 2·기존 적중 누락 8로 실패했다. 전년도 검증으로 선택한 정책은 세 연도 모두 기존 축 유지였다. 따라서 보완책을 채택하지 않는다.

승급 축과 승급이 아닌 축의 2026년 적중률은 둘 다 50%였고, 동거리 미경험만으로도 실패를 설명할 수 없었다. 사후 전개에는 초반 중단/후미와 선행 후 종반 후퇴가 함께 나타났다. 동적 순위 상태는 틀린 축과 맞힌 축 양쪽을 지지하므로 일괄 감점할 근거도 부족하다.

현재 결과는 반복 사용한 개발 자료의 진단이다. 원인 확정·미래 개선·수익률의 증거가 아니다. [전체 방법·결과·검증](README.md) · [실패 사례](CASES_2026.md).
'''
    (c.HERE/'PUBLICATION.md').write_text(short)
    arc.CONCLUSION.write_text(f'''# 부산 국5등급 1300·1600m 축 실패 진단

2026-10-22 · 연구58E · 진단·교체시험·재현검증 완료 · 운영미반영.

**{note}** 기존 state_gbm을 연구기준으로 유지한다.

{chr(10).join(baseline)}

2026실패36경주중2순위가입상한경주는25개다. 그러나전체기간에2순위로일괄교체하면120→110적중이고,전년도학습교체원형도새적중2·기존적중누락8로순손실6경주였다. 전년도검증선택정책은모두기존축유지이며추가개선0이다.

승급/동거리미경험하나로실패를설명하지못했다. 실패36경주중초반중단·후미20,초반첫마군후마지막200m순위하락9가관측됐다. 원모델점수기여에서동적순위묶음은틀린축25경주+0.3769,기존축만맞힌19경주+0.3758로비슷해일괄약화근거가없다. 사후전개·점수기여는물리적인과효과가아니다.

기본모델추가학습0·교체최종3/사전시험3. 기본점수44,653행오차0,축예측3,922건직접채점,과거이력100건·모든쌍입력4,104행검산,420개말점수기여합재현을통과했다. 같은개발자료에서고른소집단의후향결과이며독립미래검증이아니다. 원천DB·운영모델·복승/복연추천은유지했다.

[원보고서](../{c.HERE.name}/README.md) · [사례](../{c.HERE.name}/CASES_2026.md) · [계획](../{c.HERE.name}/PLAN.md) · [진단](../{c.HERE.name}/outputs/diagnostics.json) · [교체결과](../{c.HERE.name}/outputs/switch_results.json) · [검증](../{c.HERE.name}/outputs/verification.json) · [용량](../{c.HERE.name}/outputs/artifact_inventory.json).
''')
    arc.finish(note)

if __name__=='__main__':main()
