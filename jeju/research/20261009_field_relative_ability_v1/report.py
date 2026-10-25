"""Publish verified field-relative results; preserve prior central documents."""
import json
import re
import pandas as pd
import run as e

H=e.HERE;O=e.OUT;C=H.parent/'conclusions'


def write(p,text):
    with p.open('x',encoding='utf-8') as f:f.write(text)


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,r))+' |' for r in rows])


def main():
    e.check();assert json.loads((O/'final_verification.json').read_text())['passed']
    metrics=pd.read_csv(O/'metrics_by_group.csv');diff=pd.read_csv(O/'paired_differences.csv')
    runners=pd.read_csv(O/'runner_metrics.csv');rdiff=pd.read_csv(O/'runner_paired_differences.csv')
    overall=metrics[metrics.group.eq('all')].set_index('variant');d=diff[diff.group.eq('all')].set_index('metric')
    passed=bool(d.loc[['log_loss','brier'],'delta'].lt(0).all() and d.loc[['log_loss','brier'],'hi'].lt(0).any())
    decision='R1은 전체 확률 손실의 사전 유지 기준을 '+('충족했다. 확률 평가의 연구 기준선 후보로 유지하고 J0는 후보·조합 성능의 대조군으로 함께 보존한다.' if passed else '충족하지 못했다. J0를 기준선으로 유지하고 R1은 비교 후보로 보존한다.')
    status='R1_supported_research_candidate' if passed else 'J0_retained_R1_inconclusive'
    rows=[]
    for v in ['J0','R1']:
        r=overall.loc[v];rows.append([v,f'{r.log_loss:.6f}',f'{r.brier:.6f}',f'{r.top5_capture*100:.2f}%',f'{r.top5_all3*100:.2f}%',f'{r.six_combo_hit*100:.2f}%'])
    main_table=table(['모델','log loss ↓','Brier ↓','상위5두 입상마 포함','상위5두 3두 전부','6조합 적중'],rows)
    rows=[]
    for col,label,scale in [('log_loss','log loss',1),('brier','Brier',1),('top5_all3','상위5두 전부 포함 %p',100),('six_combo_hit','6조합 적중 %p',100)]:
        r=d.loc[col];rows.append([label,f'{r.delta*scale:+.6f}',f'{r.lo*scale:+.6f} ~ {r.hi*scale:+.6f}'])
    diff_table=table(['R1 − J0','차이','경주일 95% 구간'],rows)
    tradeoff='이번 결과에서 전체 확률 손실은 개선됐지만 상위5두 전부 포함률과 6조합 적중률의 점추정은 낮아졌고 차이 구간은0을 포함했다. 후보·조합 개선으로 설명하지 않으며 모든 목표에 우월한 모델로 확정하지 않는다. 2024년에는 확률 손실도 나빠지는 점추정이었고2025·2026년에는 개선돼 연도별 차이가 남는다.'
    yearly=[]
    for y in [2024,2025,2026]:
        for v in ['J0','R1']:
            r=metrics[metrics.group.eq('year')&metrics.value.eq(str(y))&metrics.variant.eq(v)].iloc[0]
            yearly.append([str(y)+(' 부분' if y==2026 else ''),v,int(r.races),f'{r.log_loss:.6f}',f'{r.brier:.6f}',f'{r.top5_all3*100:.2f}%',f'{r.six_combo_hit*100:.2f}%'])
    year_table=table(['기간','모델','경주','log loss','Brier','상위5두 전부','6조합'],yearly)
    distances=[]
    for k,g in metrics[metrics.group.eq('distance')].groupby('value',sort=False):
        g=g.set_index('variant');a=g.loc['J0'];b=g.loc['R1']
        ci=diff[diff.group.eq('distance')&diff.value.eq(k)&diff.metric.eq('brier')].iloc[0]
        distances.append([k,int(a.races),f'{a.brier:.6f}',f'{b.brier:.6f}',f'{ci.delta:+.6f} [{ci.lo:+.6f}, {ci.hi:+.6f}]',f'{a.six_combo_hit*100:.2f}% → {b.six_combo_hit*100:.2f}%'])
    dist_table=table(['거리 m','경주','J0 Brier','R1 Brier','차이와 95% 구간','6조합 J0 → R1'],distances)
    cold=runners[runners.group.eq('observed_starts')&runners.value.eq('0')].set_index('variant')
    a=cold.loc['J0'];b=cold.loc['R1'];ci=rdiff[rdiff.group.eq('observed_starts')&rdiff.value.eq('0')&rdiff.metric.eq('brier')].iloc[0]
    cold_text=f'관측 출전 이력 0인 {int(a.rows):,}출전에서 J0 Brier {a.brier:.6f} → R1 {b.brier:.6f}, 차이 {ci.delta:+.6f}(날짜95% {ci.lo:+.6f}~{ci.hi:+.6f})였다. 평균 예측은 {a.predicted*100:.2f}% → {b.predicted*100:.2f}%, 실제 입상 비율은 {a.actual*100:.2f}%다. 이는 runner 균등 하위군이며 전체 경주 균등 지표와 가중 방식이 다르다. 관측 이력 0은 공식 신마 판정이 아니다.'
    uniform=pd.read_csv(e.PRE/'outputs_v2/runner_metrics.csv')
    uniform=uniform[uniform.variant.eq('uniform')&uniform.group.eq('observed_starts')&uniform.value.eq('0')].iloc[0]
    cold_text+=f' 같은 무이력 집단의 기존 균등 확률 Brier는{uniform.brier:.6f}로, R1이 J0보다 개선됐어도 균등보다 낮은 오차를 확보한 것은 아니다. 무이력 평가가 해결됐다고 설명하지 않는다.'
    e.save(O/'interpretation_sources.json',dict(previous_uniform_runner_metrics=dict(path=str((e.PRE/'outputs_v2/runner_metrics.csv').relative_to(e.ROOT)),sha256=e.sha(e.PRE/'outputs_v2/runner_metrics.csv'))))
    examples=pd.DataFrame(json.loads((O/'example_fields.json').read_text()));exampletext='# 제주마 실제 편성의 상대능력 평가표\n\n2026년 9월 19일의 900·1000m 편성을 결과와 무관하게 날짜·거리로 선택했다. 원천 이력은 9월 17일까지다. 작은 시간이 빠르며 미관측은 0초로 채우지 않는다. 표시 마명은 최신 이름이다.\n'
    def fmt(x):return '미관측' if pd.isna(x) else f'{x:.3f}'
    for rid,g in examples.groupby('race_id',sort=False):
        exampletext+=f'\n## {rid} 편성\n\n'
        exampletext+=table(['말','마번','자기 평균 초','상대 중앙값 초','자기−상대 초','빠른 상대 수','상대 유효수','상대 가용률'],[
            [r.horse_name,int(r.horse_number),fmt(r.mean5_s),fmt(r.opp_mean5_median_s),fmt(r.mean5_minus_opp_median_s),fmt(r.opp_mean5_faster_n),int(r.opp_mean5_valid_n),f'{r.opp_mean5_valid_fraction*100:.1f}%'] for r in g.itertuples()])+'\n'
    exampletext+='\n자기 기록이 없으면 빠른 상대 수와 기록 차이는 미관측이다. 상대 중앙값·관측수는 보존한다. 이 값은 주로·부담·등급을 보정한 순수 능력 차이가 아니다. [모든 출전 ID와 상대 ID](outputs/example_fields.json), [계산 계약](CONTRACT.md).\n'
    write(H/'EXAMPLE_FIELDS.md',exampletext)
    body=f'''# 제주마 편성 대비 상대능력 추가 결과

{decision} J0의 말별 원기록 평가에 상대 기록과의 차이·순위·지원량을 추가한 첫 비교다. 같은 1,779경주·17,412출전의 2024~2026년 9월 19일 자료를 시간순으로 평가했다. 이미 본 기간의 후향 개발 비교이며 2026년은 부분연도다. 운영 모델과 DB는 변경하지 않았다.

## 추가한 입력과 계산 범위

J0의 13열은 그대로 유지하고 R1에 상대 유효 기록수·가용률·중앙값, 자기−상대 평균·중앙값·빠른2회 평균 차이, 빠른 상대 수·동률을 고려한 순위분율의 8열을 추가했다. J1의 최고·편차·추세 묶음은 승계하지 않았다. 기수·부담중량·게이트·전개·환경도 이번 입력에 추가하지 않았다. [사전 계약](CONTRACT.md), [추가·유지·제외 열](outputs/feature_contract.json).

모든 말의 동일거리 최근 실제 출전5회 원기록 평균을 T−2까지 계산한 이전 평가표를 사용한다. 자신을 상대 집계에서 제외했다. 과거 시간이 없는 상대는 미관측으로 남기고 유효 상대 수·비율을 함께 준다. 자기 기록이 없으면 기록 차이·비교 순위도 NULL이지만 상대의 수준은 보존한다. 계산 가능한 상대만 비교했으므로 가용률이 낮을 때 편성 전체의 확정 순위가 아니다. [실제 편성 사례](EXAMPLE_FIELDS.md).

2017년부터 학습한 기존 52,155출전·5,206경주의 정상 완전 편성을 그대로 유지했다. DNF·실격·동착·부분 편성은 경주 전체 제외된 사후 모집단이며, 무이력 말은 포함한다. 원천 품질 뷰의 이전 스냅샷·DB 해시와 모든 기존 열이 같음을 확인했다. [연도·거리·자료 가용 지원](outputs/support.csv), [결측](outputs/feature_missingness.csv), [이전 포함·제외 원장](../20261008_horse_profile_baseline_v1/outputs_v2/race_inclusion_ledger.csv).

## 전체 비교

log loss·Brier는 경주마다 말 평균을 낸 뒤 경주 균등 평균이며 낮을수록 좋다. 상위5두 입상마 포함률은 실제 입상마 3두 중 포함한 비율, 전부 포함률은 3두 모두 포함한 경주의 비율이다. 최대6조합은 서로 다른 순서 없는 삼복승 집합이다.

{main_table}

{diff_table}

{tradeoff}

손실 차이는 음수, 포함·적중률 차이는 양수가 개선이다. 경주일 paired bootstrap 2,000회 점별95% 구간이다. 같은 말의 장기 반복에 대한 별도 말 군집 추론은 하지 않았고, 하위군의 최고값을 확증으로 선택하지 않았다. 적중률은 수익률이 아니다. [모든 그룹 지표](outputs/metrics_by_group.csv), [차이·구간](outputs/paired_differences.csv).

## 연도와 거리 결과

{year_table}

{dist_table}

1300·1400·1610m는 학습 지원이 적거나 초기 평가에서 없어 외삽·불안정 가능성이 있다. 800m 2026년은3경주다. 희소 거리의 높은 적중률이나 점별 개선만으로 해당 거리 적용을 확정하지 않는다. 거리별 기간·분모·지원은 support.csv와 전체 표를 함께 본다.

## 이력이 없는 말과 확률 보정

{cold_text}

전체 관측 경력·동일거리 유효 이력의0·1~4·5+ 말별 결과와 paired 구간, 무이력/저경력 말이 포함된 편성의 결과를 분리했다. [말별 하위군](outputs/runner_metrics.csv), [하위군 차이와 구간](outputs/runner_paired_differences.csv), [확률 구간별 보정](outputs/calibration_bins.csv). 개별 집단의 평균 예측과 실제 비율 차이가 임의 확률 가산의 근거가 되지는 않는다.

## 동일 조건과 검증

초기 학습2017~Y−3·조기종료Y−2·재학습Y−2까지·온도 보정Y−1·평가Y를 유지했다. 기존과 같은 LightGBM 설정·seed·경주 가중치이며 결과 후 튜닝하지 않았다. 평가 기간 안에서는 T−2 과거 이력만 갱신한다. J0 3개와 R1 3개 모형을 새 폴더에서 학습했고 **기존 J0의17,412출전 점수·확률·지표가 모두 재현됐다.**

기존 가산 집합 모형을 사용해 집합 확률 합1·말별 Top3 합3을 유지했다. 말별 확률의 단순 곱을 공동확률로 쓰지 않았다. 동반입상 상호작용이나 선행 경합을 새로 학습한 결과가 아니다. [말별 예측](outputs/runner_predictions.parquet), [6조합](outputs/six_combinations.csv), [경주별 지표](outputs/race_metrics.csv).

모든52,155행의 상대능력 계산과 자기 제외, 기존 입력 불변·이력T−2를 검산했다. 결측·동률·순서 불변·상대 변화·현재 결과 교란 사례도 통과했다. [학습 전 검증](outputs/preflight_verification.json). 학습 후6개 모형 재로딩·온도·주변확률·조합·지표와 주요 구간을 다시 계산하고 보호 파일 해시 불변을 확인했다. [최종 검증](outputs/final_verification.json), [학습 전 동결 해시](outputs/prepared_lock.json), [학습 완료](outputs/training_completion.json).

## 해석과 다음 연구

{decision} 전체·연도·무이력 지표를 함께 판단하고 이번 자료만으로 독립 미래 검증이나 운영 승격을 주장하지 않는다. 다음 정보 묶음은 직전·이번 부담중량·증감이다. 기수·게이트·전개는 각각 별도 비교하며 현재기수·중량·출주집합의 당시 공개시각 가정은 분리해야 한다.

상대능력은 조건 보정 전 원기록 비교다. 과거 함수율·등급·부담·최근성 차이가 남는다. 현재 출주집합·거리·등급은 사후 원장에서 재구성했으며 당시 T−2 선언표·취소·게시·정정 시각을 검증하지 못했다. 비정상 경주까지 포함하는 운영 전체와 희소 거리의 안정성은 별도 과제다.

재현 순서는 `run.py prepare`, `verify.py preflight`, `run.py train`, `verify.py final`, `report.py`다. 기존 경로가 있으면 덮어쓰지 않고 중단한다. [계산·학습 코드](run.py), [별도 검산](verify.py). [이전 말별 평가표 기준선](../20261008_horse_profile_baseline_v1/README.md)의 계산·분할·확률 구조를 재사용했다. 더러브렛 코드·산출물과 DB·운영 모델은 변경하지 않았다.
'''
    write(H/'README.md',body)
    e.save(O/'decision.json',dict(status=status,retention_gate_passed=passed,operationally_applied=False,
        primary_comparison='R1-J0',gate='both_losses_lower_and_one_upper_CI_below_zero',
        independent_future_validation=False,already_seen_retrospective=True))
    publish(body,decision,status,main_table,diff_table,cold_text,tradeoff)
    print(decision,flush=True);print(main_table,flush=True)


def publish(body,decision,status,main_table,diff_table,cold_text,tradeoff):
    names=['README.md','SOURCES.md','07_HORSE_PROFILE_BASELINE.md','research_register.json','source_manifest.json']
    previous={n:(C/n).read_text(encoding='utf-8') for n in names}
    backup=O/'publication_before';backup.mkdir(exist_ok=False)
    for n,text in previous.items():write(backup/n,text)
    conclusion='09_FIELD_RELATIVE_ABILITY.md'
    write(C/conclusion,f'''# 제주마 편성 대비 상대능력 추가 비교

{decision} 기존 J0와 동일한2024~2026년9월19일의1,779경주·17,412출전으로 비교했다. 2026년은 부분연도이며 이미 본 자료의 후향 개발 비교다.

{main_table}

{diff_table}

{tradeoff}

J0 13열에 자기 제외 상대 기록수·가용률·중앙값·기록 차이·빠른 상대 수·순위분율의8열을 추가한 R1 21열이다. 기록 없는 상대를 느린 말이나0초로 채우지 않았고 자기 기록이 없으면 능력 차이는NULL이다. 원기록 비교이며 환경 보정된 순수 능력이 아니다.

{cold_text}

기존 J0의17,412개 점수·확률·지표를 재현했고 모든 상대값·시점·모형·조합을 검산했다. 정상 완전 편성의 사후 선정·T−2 당시 선언집합과 공개/정정 시각 미확정·희소 거리 한계를 유지한다. 운영 모델과 DB 변경은 없다. 다음 묶음은 부담중량의 별도 비교다.

[전체 결과와 연도·거리](../20261009_field_relative_ability_v1/README.md), [실제 편성 사례](../20261009_field_relative_ability_v1/EXAMPLE_FIELDS.md), [사전 계약](../20261009_field_relative_ability_v1/CONTRACT.md), [최종 검증](../20261009_field_relative_ability_v1/outputs/final_verification.json).
''')
    changed={}
    marker='| [원 연구와 버전 목록](SOURCES.md)';assert marker in previous['README.md']
    changed['README.md']=previous['README.md'].replace(marker,f'| [편성 대비 상대능력]({conclusion}) | J0에 자기 제외 상대 기록·순위·지원량8열 추가 | {status}, 운영 미반영 |\n'+marker,1)
    changed['SOURCES.md']=previous['SOURCES.md']+'\n\n- [20261009_field_relative_ability_v1](../20261009_field_relative_ability_v1/README.md): 원기록 J0에 편성 대비 상대능력8열을 추가한 동일표본·시간순 비교. 기존 J0 재현과 무이력 하위군·출전 계보 검증.\n'
    changed['07_HORSE_PROFILE_BASELINE.md']=previous['07_HORSE_PROFILE_BASELINE.md']+f'\n\n## 편성 대비 상대능력 후속\n\n2026년10월9일 [편성 상대능력 비교]({conclusion})를 완료했다. {decision} 이전 J0·J1 결과와 입력 계약은 그대로 보존한다.\n'
    reg=json.loads(previous['research_register.json']);assert not any(x['id']=='field_relative_ability' for x in reg['topics'])
    reg['updated_at']='2026-10-09';reg['topics'].append(dict(id='field_relative_ability',title='편성 대비 상대능력 추가 비교',conclusion=conclusion,
        latest_source='../20261009_field_relative_ability_v1/README.md',period_start='2017-01-01',period_end='2026-09-19',
        evaluation_period_start='2024-01-01',evaluation_rows=17412,evaluation_races=1779,status=status,
        input_counts={'J0':13,'R1':21},operationally_applied=False))
    changed['research_register.json']=json.dumps(reg,ensure_ascii=False,indent=2)+'\n'
    for n,text in changed.items():
        assert (C/n).read_text(encoding='utf-8')==previous[n],f'Concurrent change {n}'
        (C/n).write_text(text,encoding='utf-8')
    checked=0
    for p in [H/'README.md',H/'EXAMPLE_FIELDS.md',C/conclusion]:
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if target.startswith(('http:','https:','#')):continue
            assert (p.parent/target.split('#')[0]).resolve().exists(),(p,target)
            checked+=1
    e.check()
    e.save(O/'publication_verification.json',dict(passed=True,local_links_checked=checked,old_inputs_and_models_unchanged=True,
        protected_hashes_unchanged=True,conclusions_updated=True))
    manifest=json.loads(previous['source_manifest.json']);entries={x['path']:x for x in manifest['files']}
    files=[p for p in H.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    files += [C/n for n in changed]+[C/conclusion]
    for p in files:
        rel=str(p.relative_to(e.ROOT));entries[rel]=dict(path=rel,role='field_relative_ability_research' if p.is_relative_to(H) else 'conclusion_or_management',sha256=e.sha(p),bytes=p.stat().st_size)
    manifest['files']=list(entries.values());manifest['updated_at']='2026-10-09'
    assert (C/'source_manifest.json').read_text(encoding='utf-8')==previous['source_manifest.json']
    (C/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    for p in files:assert e.sha(p)==entries[str(p.relative_to(e.ROOT))]['sha256']
    files += [C/'source_manifest.json']
    e.save(H/'ARTIFACT_INVENTORY.json',dict(files=[dict(path=str(p.relative_to(e.ROOT)),bytes=p.stat().st_size,sha256=e.sha(p)) for p in files],
        research_bytes_before_inventory=sum(p.stat().st_size for p in H.rglob('*') if p.is_file()),self_hash_excluded=True,
        previous_management_versions_preserved='outputs/publication_before'))


if __name__=='__main__':main()
