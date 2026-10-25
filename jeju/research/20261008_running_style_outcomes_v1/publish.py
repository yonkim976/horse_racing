"""Save readable tables/report and update the existing running-style topic."""
from pathlib import Path
import json
import re
import numpy as np
import pandas as pd
from extract import sha, save, HERE, ROOT

OUT = HERE / 'run01'
CENTRAL = ROOT / 'jeju/research/conclusions'


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)] +
                     ['| ' + ' | '.join(map(str, r)) + ' |' for r in rows])


def wilson(k, n):
    if not n:
        return np.nan, np.nan
    z = 1.959963984540054
    d = 1 + z*z/n
    m = (k/n + z*z/(2*n))/d
    h = z*np.sqrt(k/n*(1-k/n)/n + z*z/(4*n*n))/d
    return m-h, m+h


def ko_csv(name, data, mapping):
    data[list(mapping)].rename(columns=mapping).to_csv(HERE / name, index=False, encoding='utf-8-sig')


def main():
    assert json.loads((OUT / 'verification.json').read_text())['status'] == 'passed'
    assert json.loads((OUT / 'verification_independent.json').read_text())['status'] == 'passed'
    old = json.loads((CENTRAL / 'source_manifest.json').read_text())
    for r in old['files']:
        p = (ROOT / r['path']).resolve()
        assert p.is_relative_to(ROOT)
        assert sha(p) == r['sha256'], r['path']
    a = pd.read_csv(OUT / 'runner_types_and_evidence.csv', low_memory=False, dtype={'horse_id': str})
    h = pd.read_csv(OUT / 'horse_profiles.csv')
    hd = pd.read_csv(OUT / 'horse_distance_profiles.csv')
    changes = pd.read_csv(OUT / 'latest_nonoverlapping_changes.csv')
    events = pd.read_csv(OUT / 'first_transition_followup.csv')
    summary = json.loads((OUT / 'summary.json').read_text())
    from analyze import LABEL, CORE
    ko_csv('경주별_전개분류.csv', a.sort_values(['race_date', 'race_number', 'horse_number'], ascending=[False, True, True]), {
        'api_record_id': '출전ID', 'horse_id': '말ID', 'horse_name': '최신마명', 'race_date': '경주일',
        'race_number': '경주번호', 'race_distance_m': '거리m', 'horse_number': '마번', 'field_n': '출전두수',
        'early_position_label': '초반위치', 'type_label': '전개유형', 's1f_rank_lo': 'S1F순위하한',
        's1f_rank_hi': 'S1F순위상한', 'c4_rank_lo': '4C순위하한', 'c4_rank_hi': '4C순위상한',
        'g1f_rank_lo': 'G1F순위하한', 'g1f_rank_hi': 'G1F순위상한', 'finish_position': '최종착순',
        'g3f_time_seconds': '선택G3F초', 'g1f_time_seconds': '선택G1F초',
        'g3f_relative_rank_fraction': 'G3F상대순위_낮을수록빠름', 'g1f_relative_rank_fraction': 'G1F상대순위_낮을수록빠름',
        'fade_phase': '약화시점', 'core_type_match': '제안7유형해당'})
    profile_mapping = {'horse_id': '말ID', 'horse_name': '최신마명', 'distance_m': '거리m_0은통합',
        'last_date': '마지막대상출전일', 'window_n': '최근대상출전수', 's1f_valid_n': 'S1F유효수',
        'style_candidate': '기본성향후보', 'taxonomy_fit_status': '전개분류설명범위',
        'core_type_n': '제안7유형해당수', 'core_type_fraction': '제안7유형해당비율',
        'most_common_race_type': '최다관측전개', 'most_common_race_type_n': '최다관측전개수',
        'lead_hold_top3_count': '선행유지입상수', 'front_hold_top3_count': '선입유지입상수',
        'front_advance_top3_count': '선입전진입상수', 'closing_top3_count': '추입입상수',
        'closing_fail_count': '추입불발수', 'lead_fade_count': '선행약화수', 'front_fade_count': '선입약화수',
        'early_ambiguous_count': '초반집단경계불확실수'}
    for name, data in [('말별_각질평가.csv', h), ('거리별_말별_각질평가.csv', hd)]:
        ko_csv(name, data.sort_values('last_date', ascending=False), profile_mapping)
    change60 = changes[changes.threshold_in5 == 3].copy()
    ko_csv('최근_성향변화_전체.csv', change60.sort_values('last_date', ascending=False), {
        'horse_id': '말ID', 'horse_name': '최신마명', 'distance_m': '거리m', 'last_date': '마지막대상출전일',
        'change_status': '최근변화상태', 'A_style_label': '이전5회위치성향', 'B_style_label': '최근5회위치성향',
        'A_source_api_record_ids': '이전5회출전ID', 'B_source_api_record_ids': '최근5회출전ID',
        'A_top3_count': '이전5회입상수', 'B_top3_count': '최근5회입상수',
        'A_closing_top3_count': '이전5회추입입상수', 'B_closing_top3_count': '최근5회추입입상수',
        'A_closing_fail_count': '이전5회추입불발수', 'B_closing_fail_count': '최근5회추입불발수',
        'A_fade_count': '이전5회약화수', 'B_fade_count': '최근5회약화수'})
    late = change60[change60.A_style.notna()].copy()
    late['A_closing_total'] = late.A_closing_top3_count + late.A_closing_fail_count
    late['B_closing_total'] = late.B_closing_top3_count + late.B_closing_fail_count
    late['closing_count_change'] = late.B_closing_total - late.A_closing_total
    late['fade_count_change'] = late.B_fade_count - late.A_fade_count
    # Descriptive counts already prespecified; no new significance/optimal-style rule.
    ko_csv('후반추입빈도_변화.csv', late.sort_values('last_date', ascending=False), {
        'horse_id': '말ID', 'horse_name': '최신마명', 'distance_m': '거리m', 'last_date': '마지막대상출전일',
        'change_status': '초반성향변화상태', 'A_style_label': '이전위치', 'B_style_label': '최근위치',
        'A_closing_total': '이전5회추입관측', 'B_closing_total': '최근5회추입관측',
        'closing_count_change': '추입관측증감', 'A_closing_top3_count': '이전추입입상',
        'B_closing_top3_count': '최근추입입상', 'A_closing_fail_count': '이전추입불발',
        'B_closing_fail_count': '최근추입불발', 'fade_count_change': '약화관측증감'})
    ko_csv('성과동반변화_후속확인.csv', events.sort_values('change_end_date', ascending=False), {
        'horse_id': '말ID', 'horse_name': '최신마명', 'distance_m': '거리m', 'change_end_date': '첫변화판정종료일',
        'A_style_label': '이전5회성향', 'B_style_label': '변화5회성향', 'C_style_label': '후속성향',
        'A_top3_count': '이전5회입상', 'B_top3_count': '변화5회입상', 'C_n': '후속관측수',
        'C_top3_count': '후속입상', 'B_minus_A_relative_time_s': '변화기상대기록차초_음수개선',
        'C_minus_A_relative_time_s': '후속상대기록차초_음수개선',
        'performance_associated_change_candidate': '성과동반변화후보',
        'new_style_persists_in_C': '후속5회새성향유지', 'followup_supports_candidate': '후속지지후보',
        'A_grade_values': '이전편성', 'B_grade_values': '변화기편성', 'C_grade_values': '후속편성',
        'status': '관측상태'})
    # Pointwise descriptive uncertainty only; selection and serial dependence are not corrected.
    rng = np.random.default_rng(20261008)
    byid = a.set_index('api_record_id')
    uncertainty = []
    for r in events.itertuples():
        row = {'horse_id': r.horse_id, 'distance_m': r.distance_m, 'change_end_date': r.change_end_date}
        values = {}
        for p in ['A', 'B', 'C']:
            text = getattr(r, p + '_source_api_record_ids')
            ids = [] if pd.isna(text) else list(map(int, text.split('|')))
            q = byid.loc[ids] if ids else byid.iloc[:0]
            values[p] = q.relative_time_s.to_numpy()
            lo, hi = wilson(int(q.top3.sum()), len(q))
            row.update({p + '_n': len(q), p + '_top3_wilson95_lo': lo, p + '_top3_wilson95_hi': hi})
        base = rng.choice(values['A'], (2000, 5), replace=True).mean(axis=1)
        for p in ['B', 'C']:
            if len(values[p]) == 5:
                delta = rng.choice(values[p], (2000, 5), replace=True).mean(axis=1) - base
                lo, hi = np.quantile(delta, [.025, .975])
            else:
                lo, hi = np.nan, np.nan
            row.update({p + '_minus_A_time_bootstrap95_lo_s': lo, p + '_minus_A_time_bootstrap95_hi_s': hi})
        uncertainty.append(row)
    pd.DataFrame(uncertainty).to_csv(OUT / 'event_descriptive_intervals.csv', index=False, encoding='utf-8-sig')
    save(OUT / 'uncertainty_contract.json', {'status': 'post_primary_descriptive_uncertainty_only',
        'seed': 20261008, 'bootstrap_replicates': 2000, 'top3_interval': 'pointwise_Wilson',
        'time_interval': 'resample_five_target_races_within_each_block_independently',
        'selection_adjusted': False, 'serial_dependence_adjusted': False,
        'causal_or_optimal_style_confidence_interval': False, 'classification_or_candidate_gates_changed': False})
    core_table = table(['대표 전개 유형', '출전 수'], [[LABEL[c], f'{int(a.type_code.eq(c).sum()):,}'] for c in CORE])
    fit_table = table(['말×거리 최근 프로필 상태', '조합 수'], [[k, f'{v:,}'] for k,v in summary['horse_distance_taxonomy_fit'].items()])
    change_table = table(['이전5회와 최근5회 비교', '말×거리 조합 수'], [[k, f'{v:,}'] for k,v in summary['latest_change_status60'].items()])
    examples = []
    for horse, distance in [(3017983,1110),(3103290,1110),(3101513,1110),(3103288,1000)]:
        r = hd[(hd.horse_id == horse) & (hd.distance_m == distance)].iloc[0]
        examples.append([f'{r.horse_name} {distance}m', f'{r.window_n}회', r.style_candidate,
                         f'추입입상 {r.closing_top3_count}·불발 {r.closing_fail_count}·선행유지입상 {r.lead_hold_top3_count}·선행약화 {r.lead_fade_count}', r.last_date])
    example_table = table(['말과 거리', '최근 표본', '성향 후보', '핵심 전개 관측 수', '관측 종료일'], examples)
    latest_examples = []
    for horse, distance in [(3019040,1110),(3104260,1110),(3015769,1200)]:
        r = change60[(change60.horse_id == horse) & (change60.distance_m == distance)].iloc[0]
        delta = r.B_relative_time_mean_s - r.A_relative_time_mean_s
        latest_examples.append([f'{r.horse_name} {distance}m', f'{r.A_style_label}→{r.B_style_label}',
                                f'{int(r.A_top3_count)}/5→{int(r.B_top3_count)}/5', f'{delta:+.2f}초', r.last_date])
    latest_table = table(['말과 거리', '초반 성향 변화 후보', '입상 관측', '상대 기록 평균 차', '관측 종료일'], latest_examples)
    report = f'''# 제주마 전개 유형과 각질 성향 변화

통과조의 위치 범위와 막판 구간기록을 함께 사용하면 **추입 입상·추입불발·선행 및 선입 약화**를 구분할 수 있다. 초반 위치가 같은 말에서도 후반 전진 빈도의 변화가 관측된다. 다만 제안한7유형은 모든 전개를 덮지 못하며, 성향 변화 뒤 성과가 좋아졌다고 해서 맞는 각질을 찾았다고 확정할 수 없다.

2017-01-01~2026-09-19의 정상 완주·완전 경주 **52,155출전·5,206경주·2,813두**를 분석했다. 2026년은 부분연도다. 현재 거리8종이며400m는 제외했다. 경주별 유형, 말별 최근10회, 정확거리별 최근10회, 겹치지 않는5회 블록의 성향 변화를 저장했다. 전체 표본은 현재 등록마 전체가 아니며 비정상 종료 경주를 제외한 선택 표본이다.

## 분류 기준

기본 성향과 경주 결과를 분리한다. 초반은 S1F 통과조의 확실 전방·첫 집단이면 선행권, 확실 전방·첫 집단 밖이면 선입권, 나머지는 중단·후미다. 선행권은 단독 선행 확정이 아니다. 괄호 안 순서를 개별 순위로 만들지 않고 앞선 집단 두수로 가능한 순위 범위를 계산한다.

후반 전진은4C→G1F 또는G1F→결승에서 **범위 전체가 적어도2위 이상 좋아진 경우**다. 좋은 막판 구간은 같은 경주에서 G3F·G1F 모두 비교 가능하고 둘 중 하나가 빠른 쪽1/3인 경우다. 각 비교는 유효6두 이상·전체의80% 이상을 요구한다. 동시간은 평균순위를 사용한다. 빠른 절대 초의 기준을 모든 거리·주로에 공통 적용하지 않았다.

중단·후미에서 후반 전진과 좋은 구간이 함께 확인되면 입상 시 **추입 입상**, 미입상 시 **추입불발**이다. 전진 뒤 재하락은 별도 표시한다. 좋은 시간만 있고 순위 전진이 불확실하면 추입불발을 강제로 붙이지 않는다.

선행·선입 약화는 확실2위 이상 하락과 느린 쪽1/3의 구간기록을 함께 요구한다. S1F→4C+느린G3F는중반부터,4C→G1F+느린G3F는후반, G1F→결승+느린G1F는막판으로 구분한다. 후반·막판 약화는 그 시점까지 전방에 있던 경우다. 이 분류는 상대 수행 저하이며 체력 고갈이나 원인을 확정하지 않는다. 약화하면서도 입상한 경주는 입상 사실을 별도로 유지한다. G3F는 마지막600m 시간이며 통과조 지점으로 만들지 않았다.

1300m는S1F/2C 측정 정의가 미확정이라 초반 주 분류·성향 변화에서 보류했다.1610m는9경주로 소표본이다. 기존 충돌 지점·시간 보류를 우회하지 않았고, 같은 지점과 혼합되는 시간 파생도 보수적으로 차단했다. G3F·G1F를 모두 상대 비교할 수 있었던 출전은52,068개다. 양수 선택API 값은 전수 홈페이지 확인 완료를 뜻하지 않는다.

## 경주별 분류 결과

{core_table}

대표7유형은 **15,108출전(전체의29.0%)**을 설명했다. 나머지를 모두 기타 각질로 묶지 않고 이유를 남겼다. 초반 집단경계 불확실16,771출전, 후방 유지·움직임 미확정8,519출전, 빠른 구간이지만 전진 미확정2,660출전, 선행권→선입권 입상784출전 등이 있다.1300m606출전과초반 통과조 결측60출전은 별도 보류다.

**유형 밖이라는 것은 말이 잘못된 각질로 뛰었다는 뜻이 아니다.** 관측이 부족하거나 제안7유형에 포함하지 않은 전개가 있다는 뜻이다. 특히 전방에서 입상하지 못해도 순위 하락·느린 구간 근거가 없으면 약화로 단정하지 않는다. 유형의 입상률은 정의 자체에 입상을 사용하므로 독립적인 성과 검증이 아니다.

## 말별 반복 성향과 유형에 잘 들어맞는 사례

마지막 해당 대상 출전일 기준730일 안의 최근10회 대상 출전을 쓴다. 유효S1F 최소5회·커버리지60% 이상에서 성향 후보를 붙인다. 추입 입상+추입불발이 유효 관측의60% 이상이면 추입형 후보이고, 후미 위치만 반복하는 경우는 후미대기형으로 남긴다. 선행·선입·중단·후미 반복도60%를 사용한다. 이 경계는 설명용 사전 규칙이며 최적 기준이 아니다.

{example_table}

삼다장군1110m는 최근10회 모두 초반 후미지만, 추입 입상1회·추입불발5회로 구분된다. 흥부시대1000m는 초반 후미8회 중 전진+좋은구간을 충족한 추입불발은2회이고, 후방 유지·움직임 미확정이5회다. 같은 후미 위치라도 두 말의 후반 전개는 다르다.

흑룡시대1110m는 선행권 출발7회이지만 선행 유지·입상2회와 선행 약화5회가 함께 관측된다. 초반 위치만으로 앞에서 안정적으로 버틴다고 평가할 수 없다. 마마골드1110m의 선행 약화4회는 후반 약화2회·막판 약화2회로 나뉜다.

{fit_table}

유효한 최근 표본에서 대표7유형이60% 이상을 설명한 경우를 분류 체계로 대부분 설명되는 프로필로 표시했다. 이는 각질 적합성의 정답 판정이 아니다. 전체 말 통합에서는199두, 거리별에서는412조합이며, 집단경계 불확실·규칙 밖 전개·자료부족을 구분했다. 최근2025·2026 대상 출전이 관측된 말 통합1198두 중 이 조건을 충족한 말은100두다.

이전 연구와의 차이도 있다. 이전 선입형은 전방 반복을 먼저 보고 선두군형 기준에 미달하면 붙였다. 이번 선입권 반복은 **첫 집단 밖의 확실 전방**으로 더 좁게 정의했다. 따라서 말별 후보 수 변화가 구간기록 추가만의 효과는 아니다. [이전 위치 성향 연구](../20261008_passing_group_running_style_v1/README.md)는 별도 보존했다.

## 최근 각질 성향 변화와 후반 움직임 변화

정확거리별 최근10회를 이전5회와최근5회로 나눴다. 각 블록에서S1F 유효4회 이상이고 같은 초반 범주가 전체5회 중3회 이상이면 우세 성향이다. 불확실 관측도5회 분모에 남겼다.

{change_table}

초반 성향 변화 후보는29조합·29두이며, 그중2025·2026 대상 출전이 관측된 사례는11두다. 같은 말의 성향유지201조합과 최근 성향 집중236조합도 구분된다. 최근 성향 집중은 이전 혼합/불확실에서 최근 한 위치가 우세해졌다는 뜻이며 적합한 각질을 찾았다는 뜻은 아니다.

{latest_table}

상대 기록은 같은 경주 중앙값보다 얼마나 빠르거나 느렸는지의 초 차이다. 표는 최근5회 평균−이전5회 평균이며 음수가 개선이다. 편성·부담·함수율을 모두 보정한 효과가 아니다. 역발산1110m는 입상1/5→3/5 및−1.79초가 동반됐지만 편성도 달라지고 같은 거리 후속5회가 없어 아직 성과동반 변화 후보다. 동백천하1110m는 위치가 후미 쪽으로 바뀌었지만 입상 개선이 없었다. 새옹지마1200m도 초반 변화와 성과 개선이 같지 않음을 보여준다.

우세 기준을3/5에서4/5로 높이면 최근 변화 후보는29두에서1두(새옹지마1200m)로 줄었다. **변화 탐지는 기준에 민감하며 확정 전술 변경으로 읽으면 안 된다.** 소표본과 집단 관측 불확실성도 영향을 준다.

초반 위치가 같아도 후반 움직임의 빈도는 달라질 수 있다. 무비공1200m는 두 블록 모두 후미 성향이고 추입 관측(입상+불발)은0/5→3/5로 늘었다. 최근5회는 추입 입상2회·추입불발1회다. 모나파크1110m도 후미 성향을 유지하면서0/5→3/5(입상1회·불발2회)였다. 이 사례는 전체 빈도표 중 설명용으로 골랐으며 변화의 유의성이나 미래 지속을 검증한 결과가 아니다. [전체 후반 빈도 변화표](후반추입빈도_변화.csv)에는 증가·감소·동일을 모두 남겼다.

## 맞는 각질을 찾은 말이 있는가

이번 규칙에서 **후속 관측까지 지지된 후보는0두**다. 이는 그런 말이 없다는 증명이 아니다.

말×거리마다 성과를 보기 전에 초반 성향이 처음 바뀐 시점 하나를 고정했다. 과거5회A와변화5회B의 성향이 달랐던150사건·143두를 찾았다. B에서Top3가2회 이상 늘고 상대 기록 평균이0.5초 이상 개선된 사건은11건·11두였다. 이후365일 안의 같은 거리 대상 출전5회C를 확인했으며 B종료일+2일 이후만 연결했다.

11후보 중 **8두는후속5회부족**, **3두는후속5회확인가능**이었다. 이3두는헌마공신1110m·새옹지마1200m·천봉원수800m이며, 변화기의입상은각각2/5·3/5·3/5였지만후속5회입상은모두0/5였다. 새성향유지와입상·상대기록개선이함께이어지는사전기준은충족하지못했다. 후속관측이없는후보를실패로세지않았다.

전체150변화사건 중후속5회가있는52건에서는새초반성향이우세한경우가12건이었다. 나머지는다른성향9건·혼합/불확실31건이다. 후속5회부족98건은별도다. 이것은선택된첫변화사건의조건부관측이며모든각질의지속확률이나예측정확도가아니다.

기록개선경계를0.25초·0.5초·1.0초로바꾼후보는18·11·5건이었고후속지지후보는모두0건이다. 최신분류후보의성공여부를보고변경시점을다시고르지않았다. 개별사건각5회가작고성장·편성·부담·주로·상대편성과선택편향이남아있다. 맞는각질을찾았다는인과판정으로승격하지않는다.

## 파일과 검증

- [경주별 전개 분류](경주별_전개분류.csv): 모든 출전의 통과 범위·G3F/G1F·착순·약화 시점.
- [말별 각질 평가](말별_각질평가.csv), [거리별 말별 평가](거리별_말별_각질평가.csv): 최근 전개 빈도와 규칙 밖/자료 불확실성 구분.
- [최근 성향 변화 전체](최근_성향변화_전체.csv), [후반 추입 빈도 변화](후반추입빈도_변화.csv), [성과동반 변화와 후속 확인](성과동반변화_후속확인.csv).
- [거리·연도·출전두수별 전표](run01/type_counts_distance_year_field.csv), [시간 품질·커버리지](run01/time_quality_and_coverage.csv), [개별 출전 전체 근거](run01/runner_types_and_evidence.csv), [첫 변화·후속 원천ID](run01/first_transition_followup.csv), [임계값 민감도](run01/performance_threshold_sensitivity.csv).
- [입력 해시](input01/source_manifest.json), [DB 조회 검증](input01/verification.json), [분류 검증](run01/verification.json), [독립 계산 대조](run01/verification_independent.json), [사전 계획](PLAN.md), [추출 코드](extract.py), [계산 코드](analyze.py), [최종 검증 코드](verify_v2.py), [출판 코드](publish.py), [보관 크기와 해시](artifact_manifest.json).

개별사건의입상빈도Wilson점별95%구간과상대기록평균차의2000회블록내재표집구간은[기술적불확실성표](run01/event_descriptive_intervals.csv)에있다. 각5회관측을독립처럼재표집한작은표본의조건부구간이며성향변화선택·시간의존성·다중탐색을보정하지않았다. 후보선정규칙은바꾸지않았으며최적각질이나인과효과의신뢰구간이아니다. [계산계약](run01/uncertainty_contract.json)을함께본다.

독립계산으로104,310출전×시간순위·150개첫변화·10,641개말/거리프로필을대조했다. A/B/C출전ID비중복과시점제한을확인했다. 첫검증의CSV왕복극소오차2.2×10⁻¹⁷는절대허용오차를명시한최종검증에서해소했으며[초기시도](run01/verification_attempt1.json)와[초기코드](verify.py)를보존했다. 분석값·분류·선정결과는변경하지않았다. DB읽기전용·입력해시불변이며운영모델·웹반영은없다. 같은경주의사후유형을같은경주의사전입력에쓰지않았다. 이미사용된과거기간의후향연구이므로후속C도새독립미래검증이아니다.
'''
    # Normalize dense numeric boundaries and a few paragraphs without changing meaning.
    replacements = {
        '11후보 중 **8두는후속5회부족**, **3두는후속5회확인가능**이었다. 이3두는헌마공신1110m·새옹지마1200m·천봉원수800m이며, 변화기의입상은각각2/5·3/5·3/5였지만후속5회입상은모두0/5였다. 새성향유지와입상·상대기록개선이함께이어지는사전기준은충족하지못했다. 후속관측이없는후보를실패로세지않았다.':
        '11후보 중 **8두는 후속5회 부족**, **3두는 후속5회 확인 가능**이었다. 이3두는 헌마공신1110m·새옹지마1200m·천봉원수800m이며, 변화기의 입상은 각각2/5·3/5·3/5였지만 후속5회 입상은 모두0/5였다. 새 성향 유지와 입상·상대 기록 개선이 함께 이어지는 사전 기준은 충족하지 못했다. 후속 관측이 없는 후보를 실패로 세지 않았다.',
        '전체150변화사건 중후속5회가있는52건에서는새초반성향이우세한경우가12건이었다. 나머지는다른성향9건·혼합/불확실31건이다. 후속5회부족98건은별도다. 이것은선택된첫변화사건의조건부관측이며모든각질의지속확률이나예측정확도가아니다.':
        '전체150변화 사건 중 후속5회가 있는52건에서는 새 초반 성향이 우세한 경우가12건이었다. 나머지는 다른 성향9건·혼합/불확실31건이다. 후속5회 부족98건은 별도다. 이것은 선택된 첫 변화 사건의 조건부 관측이며 모든 각질의 지속 확률이나 예측 정확도가 아니다.',
        '기록개선경계를0.25초·0.5초·1.0초로바꾼후보는18·11·5건이었고후속지지후보는모두0건이다. 최신분류후보의성공여부를보고변경시점을다시고르지않았다. 개별사건각5회가작고성장·편성·부담·주로·상대편성과선택편향이남아있다. 맞는각질을찾았다는인과판정으로승격하지않는다.':
        '기록 개선 경계를0.25초·0.5초·1.0초로 바꾼 후보는18·11·5건이었고 후속 지지 후보는 모두0건이다. 최신 분류 후보의 성공 여부를 보고 변경 시점을 다시 고르지 않았다. 개별 사건 각5회가 작고 성장·편성·부담·주로·상대 편성과 선택 편향이 남아 있다. 맞는 각질을 찾았다는 인과 판정으로 승격하지 않는다.',
    }
    for before, after in replacements.items():
        report = report.replace(before, after)
    # The final technical paragraphs are kept explicit and readable.
    start = report.index('개별사건의입상빈도')
    report = report[:start] + '''개별 사건의 입상 빈도 Wilson 점별95% 구간과 상대 기록 평균 차의2000회 재표집 구간은 [기술적 불확실성표](run01/event_descriptive_intervals.csv)에 있다. 각5회 관측을 독립처럼 재표집한 작은 표본의 조건부 구간이며 성향 변화 선택·시간 의존성·다중 탐색을 보정하지 않았다. 후보 선정 규칙은 바꾸지 않았으며 최적 각질이나 인과 효과의 신뢰구간이 아니다. [계산 계약](run01/uncertainty_contract.json)을 함께 본다.

독립 계산으로104,310출전×시간 순위·150개 첫 변화·10,641개 말/거리 프로필을 대조했다. A/B/C 출전ID 비중복과 시점 제한을 확인했다. 첫 검증의 CSV 왕복 극소 오차2.2×10⁻¹⁷는 절대 허용 오차를 명시한 최종 검증에서 해소했으며 [초기 시도](run01/verification_attempt1.json)와 [초기 코드](verify.py)를 보존했다. 분석값·분류·선정 결과는 변경하지 않았다. DB 읽기 전용·입력 해시 불변이며 운영 모델·웹 반영은 없다. 같은 경주의 사후 유형을 같은 경주의 사전 입력에 쓰지 않았다. 이미 사용된 과거 기간의 후향 연구이므로 후속C도 새 독립 미래 검증이 아니다.
'''
    report = re.sub(r'(?<=[가-힣])(?=[A-Za-z0-9])', ' ', report)
    (HERE / 'README.md').write_text(report)
    topic = '''# 통과조 기반 말별 각질과 전개 결과

최신 연구는 통과조 위치 범위에 G3F·G1F 구간기록과 최종착순을 더해 추입 입상·추입불발·선행 및 선입 약화를 구분한다. 말의 반복 성향, 해당 경주의 전개 결과, 변화 뒤 성과를 분리한다. 선행권은 선두집단 소속이며 단독 선행을 확정하지 않는다. 후미 위치만으로 추입형을 붙이지 않는다.

2017-01-01~2026-09-19 정상 완주·완전 경주52,155출전·5,206경주·2,813두다. 2026년은 부분연도이고1300m 초반 판정은 정의 미확정으로 보류,1610m는9경주로 소표본이다. 기존 품질 보류를 유지했다.

대표7유형은15,108출전(29.0%)을 설명했다. 추입 입상2694·추입불발2858·선행 약화2883·선입 약화1071출전이다. 통과 범위에서 후반2위 이상 전진+같은 경주 막판 구간 상위1/3을 함께 요구하며, 약화는 확실 하락+느린 구간을 요구한다. 선행 유지·입상3657·선입 유지·입상1697·선입 전진·입상248출전도 구분했다. 유형 밖 전개와 관측 불확실성을 억지로 각질 실패로 해석하지 않는다.

말×거리 최근10회 중 대표7유형이60% 이상을 설명한 프로필은412조합이다. 삼다장군1110m는 추입 입상1회·추입불발5회, 흑룡시대1110m는 선행 유지·입상2회·선행 약화5회다. 기본 위치와 버팀·전진 결과가 다르다.

겹치지 않는 이전5회와 최근5회의 초반 우세 성향이 달라진 후보는29두이고 그중2025·2026 대상 출전 관측 말은11두다. 기준을3/5에서4/5로 높이면1두로 줄어 민감하다. 최근 성향 집중236조합과 성향 유지201조합도 분리했다. 후미 위치를 유지해도 무비공1200m의 추입 관측은0/5→3/5로 늘었다. 이는 후향적 빈도 사례다.

성과를 보기 전에 고정한 첫 변화150사건에서 입상·상대 기록이 좋아진 후보는11두였다. 8두는후속5회 부족,3두는후속5회에서 새 성향과 성과가 함께 유지되는 기준 미충족이다. **맞는 각질을 찾았다고 후속 지지할 후보는0두**이며 그런 말이 없다는 증명이 아니다. 편성·부담·주로·성장·선택 편향과 작은 표본이 남아 인과적인 최적 각질을 확정하지 않는다.

- [최신 상세 결과와 분류 기준](../20261008_running_style_outcomes_v1/README.md)
- [거리별 말별 평가](../20261008_running_style_outcomes_v1/거리별_말별_각질평가.csv), [경주별 전개](../20261008_running_style_outcomes_v1/경주별_전개분류.csv)
- [최근 성향 변화](../20261008_running_style_outcomes_v1/최근_성향변화_전체.csv), [추입 빈도 변화](../20261008_running_style_outcomes_v1/후반추입빈도_변화.csv), [성과동반 변화 후속](../20261008_running_style_outcomes_v1/성과동반변화_후속확인.csv)
- [최신 계획·원천·검증 목록](../20261008_running_style_outcomes_v1/artifact_manifest.json)
- [이전 위치 성향 후보 연구](../20261008_passing_group_running_style_v1/README.md):2813두·거리별7828조합. 이번 선입권은 첫 집단 밖의 확실 전방으로 좁혀 이전 후보 수와 직접 비교하지 않는다.

상태는 **전개 분류·비중첩 성향 변화·후속 관측 연구 완료, 최적 각질·인과효과·독립 미래 예측 미검증, 운영 미반영**이다. 같은 경주의 사후 유형을 같은 경주 사전 입력으로 쓰지 않는다.
'''
    (CENTRAL / '07_RUNNING_STYLE.md').write_text(re.sub(r'(?<=[가-힣])(?=[A-Za-z0-9])', ' ', topic))
    readme = (CENTRAL / 'README.md').read_text()
    lines = readme.splitlines()
    for i,line in enumerate(lines):
        if '](07_RUNNING_STYLE.md)' in line:
            lines[i] = '| [통과조 기반 각질과 전개](07_RUNNING_STYLE.md) | 추입불발·선행/선입 약화, 최근 성향 변화29두·성과동반 후보11두·후속 지지0두 | 분류·후속 관측 완료,최적 각질·운영 미반영 |'
    (CENTRAL / 'README.md').write_text('\n'.join(lines) + '\n')
    sources = (CENTRAL / 'SOURCES.md').read_text()
    addition = '| [20261008_running_style_outcomes_v1](../20261008_running_style_outcomes_v1/README.md) | 통과조+G3F/G1F+최종착순 전개 분류. 추입불발2858출전, 최근 위치 성향 변화29두, 첫 변화150사건·성과동반11두·후속 지지0두. 이전 위치 성향 연구의 후속이며 첫 검증의 극소 오차 허용 문제와 최종검증을 함께 보존 |\n\n'
    (CENTRAL / 'SOURCES.md').write_text(sources.replace('같은 출전 자료가 여러 버전에 중복되므로', addition + '같은 출전 자료가 여러 버전에 중복되므로'))
    reg = json.loads((CENTRAL / 'research_register.json').read_text())
    t = next(t for t in reg['topics'] if t['id'] == 'running_style')
    t.update({'previous_source': t['latest_source'], 'latest_source': '../20261008_running_style_outcomes_v1/README.md',
              'status': 'outcome_taxonomy_nonoverlapping_style_change_and_followup_completed',
              'core_taxonomy_starts': 15108, 'closing_fail_starts': 2858, 'closing_top3_starts': 2694,
              'latest_position_change_candidates': 29, 'first_transition_events': 150,
              'performance_associated_change_candidates': 11, 'followup_supported_candidates': 0,
              'causal_optimal_style_identified': False, 'minimum_block_starts': 5,
              'change_majority_threshold': .6, 'change80pct_candidates': 1,
              'future_prediction_tested': False, 'operationally_applied': False})
    save(CENTRAL / 'research_register.json', reg)
    links = 0
    for p in list(CENTRAL.glob('*.md')) + [HERE / 'README.md', HERE / 'PLAN.md']:
        for target in re.findall(r'\]\(([^)]+)\)', p.read_text()):
            if '://' in target or target.startswith('#'):
                continue
            if target.endswith('artifact_manifest.json'):
                continue
            assert (p.parent / target.split('#')[0]).resolve().exists(), (p, target)
            links += 1
    save(HERE / 'publication_verification.json', {'status': 'passed', 'all_previous_source_hashes_unchanged': True,
        'local_links_checked': links, 'source_entry_counts_reconciled': True,
        'verification_attempt1_preserved': True, 'final_independent_verifier': 'verify_v2.py',
        'candidate_followup_shortage_not_counted_as_failure': True, 'operational_change': False})
    files = [{'path': str(p.relative_to(HERE)), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(HERE.rglob('*'))
             if p.is_file() and p.name != 'artifact_manifest.json']
    save(HERE / 'artifact_manifest.json', {'self_excluded': True, 'files': files,
                                          'total_bytes_excluding_this_manifest': sum(r['bytes'] for r in files)})
    records = {r['path']: r for r in old['files']}
    for p in CENTRAL.iterdir():
        if p.is_file() and p.name != 'source_manifest.json':
            records[str(p.relative_to(ROOT))] = {'path': str(p.relative_to(ROOT)), 'role': 'conclusion_or_management', 'sha256': sha(p), 'bytes': p.stat().st_size}
    for p in HERE.rglob('*'):
        if p.is_file():
            records[str(p.relative_to(ROOT))] = {'path': str(p.relative_to(ROOT)), 'role': 'source_running_style_outcomes', 'sha256': sha(p), 'bytes': p.stat().st_size}
    old['files'] = list(records.values())
    old['verification'] = {'status': 'passed', 'all_previous_source_hashes_unchanged': True,
        'latest_study': str(HERE.relative_to(ROOT)), 'latest_verification': str((HERE/'publication_verification.json').relative_to(ROOT)), 'local_links_checked': links}
    old['managed_files_bytes_excluding_this_manifest'] = sum(r['bytes'] for r in old['files'])
    save(CENTRAL / 'source_manifest.json', old)
    assert all(sha(ROOT / r['path']) == r['sha256'] for r in old['files'])
    print(json.dumps({'published': str(HERE), 'files': len(files) + 1,
                      'bytes': sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file()), 'local_links_checked': links}, ensure_ascii=False))


if __name__ == '__main__':
    main()
