"""Save the bounded followup and update mutable central conclusions."""
import importlib.util
import json
import re
from pathlib import Path
import pandas as pd
from analyze import HERE,ROOT,sha,save


def main():
    assert not (HERE/'README.md').exists()
    verification=json.loads((HERE/'run01/verification.json').read_text());assert verification['status']=='passed'
    early=pd.read_csv(HERE/'run01/early_gate_contrasts.csv')
    final=pd.read_csv(HERE/'run01/top3_group_counts.csv')
    adjusted=pd.read_csv(HERE/'run01/previous_adjusted_top3.csv').iloc[0]
    seconds=pd.read_csv(HERE/'run01/previous_adjusted_seconds.csv').iloc[0]
    rows=[]
    for r in early.itertuples():
        name=('2C' if r.point=='c2' else 'S1F')+(' 첫 집단' if r.event=='firstpack' else ' 앞 두 집단')
        rows.append(f'| {name} | {r.inner_rate*100:.1f}% | {r.outer_rate*100:.1f}% | +{r.difference_pp:.2f}%p | +{r.ci_lo_pp:.2f}~+{r.ci_hi_pp:.2f}%p | {r.BH_q:.4f} |')
    table='\n'.join(['| 관측 위치 | 내측1~3번 | 외측8~10번 | 원시 차이 | 날짜집단95%구간 | 탐색4비교BH q |','|---|---:|---:|---:|---|---:|']+rows)
    annual=[]
    for year in ['2024','2025','2026']:
        z=final[final.period.astype(str).eq(year)].set_index('gate_band')
        annual.append(f'| {year} | {int(z.loc["inner","races"])} | {z.loc["inner","top3_rate"]*100:.1f}% | {z.loc["outer","top3_rate"]*100:.1f}% |')
    text=f'''# 제주1300m의 측정 순서와 내측 출발번호 이점

2026-10-08. **1300m는 초반 자리잡기에서 내측 우세 방향이 관측된다. 최종 입상률도 전체 원시 비율은 내측이 높지만, 말의 능력·함수율 등을 고려한 크기와 최근 지속성은 불확실하다. ‘1300m 내측 우위 없음’으로 정리하지 않는다.**

사용자가 직접 알려준 **출발→2C→S1F** 순서와 곡선 시작 조건을 이번 연구의 지점 순서 계약으로 반영했다. 이 순서에서는2C 시간이S1F보다 작은 것을 초반 오류 또는 전 거리 보류 근거로 삼을 수 없다. 앞선 ‘S1F/2C 순서 미확정 때문에1300m 초반 전체 제외’ 판단은 이 계약으로 해제한다. 독립 공식 계측 명세를 새로 검증했다고 표시한 것은 아니며 사용자 제공 지점 순서가 근거다. 개별 품질 충돌·정정·결측 차단은 그대로 유지한다.

앞선 [전개 예측 연구](../20261008_pace_position_prediction_v1/README.md)는 실제로1300m를 제외한 비교였다. 그 확률·수치를 이번에1300m 포함 성능으로 바꾸지 않았다. 기존 원본을 보존하고 후속 분석부터 사용자 순서 계약으로1300m를 다룬다. 이전 연구의 미확정 표시는 당시 계약이며 최신 연구 기준은 이 후속 문서를 따른다.

## 초반 집단 위치와 게이트

기존 quality 조회에서 보존한 정상 완주·완전 경주1300m는606출전·63경주다. 그중 정확10두·마번1~10인470출전·47경주를 비교했다. 실제 표본 범위는2024-05-18~2026-09-04이며 데이터 원천 상한은2026-09-19다.2017년부터 조회했다고1300m의2017년 표본이 있는 것은 아니다. 내측·외측은 각각3개 마번으로141출전씩이다.

{table}

첫 집단은 통과조에서 관측된 집단 소속이며 단독 선행·개별1위가 아니다. 앞 두 집단도 물리적인 레일2선을 뜻하지 않는다. 같은 집단 안 내외측 순번을 개별 순위로 바꾸지 않았다.47개 날짜를 묶은10000회 부트스트랩 구간,날짜집단 정규근사p와4비교BH를 사용한 **탐색적 원시 연관**이다. 말의 초반 능력·각질·편성 차이를 통제한 게이트 인과효과 또는 조건부 추가 예측 개선으로 해석하지 않는다. 측정 지점이 다른2C와S1F의 첫 집단 크기도 다를 수 있다.

사용자가 알려준 곡선 시작 조건에서 내측 경로와 자리 선점의 이점은 검토할 가설이다. 관측된 초반 내측 방향은 이 가설과 부합하지만 실제 주행 거리·주행선·진로·기수 의도는 보유 통과조로 측정하지 못해 원인을 확정하지 않는다. 외측의 빠른 말이 선두군에 합류할 가능성도 배제하지 않는다.

## 최종 입상과 기록

같은47경주의 최종Top3는 내측49/141=34.75%,중간57/188=30.32%,외측35/141=24.82%다. 내측−외측 원시 차이는+9.93%p다. 기존 번호별 원표10개 분자·분모와 새 원천 집계를 모두 대조했다.

[이전 최신 함수율·시기 조정 연구](../20261008_gate_top3_period_moisture_v1/README.md)의 같은 말·같은 경주·과거 이력·연도·함수율 등을 고려한 차이는 **+{adjusted.effect_pp:.2f}%p,95%구간{adjusted.ci_lo_pp:.2f}~+{adjusted.ci_hi_pp:.2f}%p,BH q={adjusted.q_BH:.3f}**였다. 내측 방향의 추정이지만0을 포함하고 표본도 제한적이라 확정 효과로 채택하지 않았다. 초기 단순 연구의+13.28%p보다 최신 보수적 조정 결과를 현재 결론으로 사용한다.

[기존 완주시간 연구](../20261008_gate_record_seconds_v1/README.md)의 조정 내측−외측 시간은{seconds.effect_s:.3f}초,95%구간{seconds.ci_lo:.3f}~+{seconds.ci_hi:.3f}초다. 내측이 빠른 방향이지만 크기는 불확실하다. 입상률 차이를 초로 환산하지 않는다.

| 연도 | 10두 경주 | 내측Top3 | 외측Top3 |
|---|---:|---:|---:|
{chr(10).join(annual)}

연도별은8·24·15경주뿐이다.2026년 원시 차이는33.3%−31.1%=+2.2%p로 작아졌지만, 연도별 우세 변화·반전이나 내측 효과 소멸을 확인할 표본이 부족하다.2026년은 부분연도다.

## 연구 기준과 저장

1300m는2C의 최초 자리잡기와그 뒤S1F 위치를 나누어 보는 방향이 합당하다. 같은 지점을 뜻한다고 가정해 다른 거리와2C 시간을 직접 합치거나, 출발번호만으로 첫 집단을 확정하지 않는다. 현재 상태는 **측정 순서 계약 정정·초반 원시 연관 확인·최종 결과 재대조 완료, 고정 가산·시간 환산·운영 반영 없음**이다. 새로운 전체 예측모형의1300m 성능을 검증한 것은 아니다.

- [사전 계획과 사용자 정정 근거](PLAN.json), [실행 코드](analyze.py), [출처 해시](run01/source_manifest.json)
- [전체1300m 지점별 관측](run01/all1300_quality_pack_observations.csv), [정확10두 원천 관측](run01/exact10_observations.csv)
- [초반 집계](run01/early_gate_counts.csv), [초반 차이와 구간](run01/early_gate_contrasts.csv), [연도별 입상](run01/top3_group_counts.csv)
- [기존 조정 입상](run01/previous_adjusted_top3.csv), [기존 조정 시간](run01/previous_adjusted_seconds.csv), [검증](run01/verification.json)

126개 품질 통과조의 참가집합을 확인하고1880개 집단 사건을 순위 범위로 독립 대조했다. 이전 번호별Top3 분자·분모10개를 재현했고 원천 해시가 모두 유지됐다. 기존 DB·운영 모델·웹은 변경하지 않았다.
'''
    (HERE/'README.md').write_text(text)
    decision={'date':'2026-10-08','sequence':['start','2C','S1F'],'source':'direct_user_statement',
        'curve_start_source':'direct_user_statement','official_spec_independently_verified':False,
        'blanket_1300_early_hold_lifted_under_user_contract':True,'field_quality_holds_preserved':True,
        'early_raw_inner_association_observed':True,'early_ability_adjusted_effect_estimated':False,
        'final_adjusted_advantage_confirmed':False,'fixed_correction_adopted':False,'model_refit':False,
        'operationally_applied':False,'exact10_races':47,'exact10_source_start':'2024-05-18','exact10_source_end':'2026-09-04'}
    save(HERE/'decision.json',decision)
    central=ROOT/'jeju/research/conclusions';manifestpath=central/'source_manifest.json';manifest=json.loads(manifestpath.read_text())
    immutable=[r for r in manifest['files'] if r['role']!='conclusion_or_management']
    for r in immutable:assert sha(ROOT/r['path'])==r['sha256'],r['path']
    link='../'+HERE.name+'/README.md'
    p=central/'01_GATE_LATERAL.md';t=p.read_text();head,body=t.split('\n\n',1)
    addition=f'''最新1300m后续'''
    addition=f'''1300m 최신 후속: [2C→S1F 순서 정정과 초반 내측 비교]({link}). 사용자 제공 순서에 따라 초반 전거리 보류를 해제했다. 정확10두47경주에서2C 첫 집단은 내측34.0%·외측17.0%,S1F 첫 집단은27.0%·14.9%였다. 초반 능력 미조정 원시 연관이다. 최종Top3 원시 비율은34.75%·24.82%이며 최신 조정 차이는+6.05%p(95%−13.04~+25.13)로 불확실하다. 따라서 ‘1300m 내측 우위 없음’이 아니라 ‘초반 내측 방향 관찰,최종 조정 크기·최근 지속성 미확정’으로 정리한다.2026년은15경주이며 고정 보정·운영 반영은 하지 않았다.

'''
    p.write_text(head+'\n\n'+addition+body)
    p=central/'07_RUNNING_STYLE.md';t=p.read_text();head,body=t.split('\n\n',1)
    addition=f'''1300m 측정 순서 최신 정정: 사용자가 제공한 **출발→2C→S1F** 순서를 연구 계약으로 채택했다.2C 시간이S1F보다 작다는 이유의 초반 전거리 보류는 해제하며 개별 품질 보류는 유지한다. [1300m 후속]({link})에서 초반 내측 방향을 원시 관측으로 확인했다. 아래 기존 전개 예측·분류 결과는 당시1300m를 제외한 수치로 보존한다.1300m 포함 새 예측 성능을 검증했다고 표시하지 않는다. 공식 계측 명세 독립 확인이 아니라 사용자 지점 순서 정정이 근거다.

'''
    p.write_text(head+'\n\n'+addition+body)
    p=central/'README.md';t=p.read_text();marker='## 저장 구조'
    addition=f'''1300m 후속 정정: [2C→S1F 순서와 내측 자리잡기]({link}). 기존 전개 예측은1300m 제외 결과로 보존하고,후속 연구는 사용자 제공 순서를 적용한다. 초반 내측 원시 우세가 관측됐지만 최종 조정 효과는 불확실하다.

'''
    assert link not in t;p.write_text(t.replace(marker,addition+marker,1))
    p=central/'SOURCES.md';t=p.read_text();line=f'| [{HERE.name}]({link}) | 사용자1300m2C→S1F 정정·곡선 시작 계약.47개10두 경주에서2C/S1F 초반 내측 방향 원시 관측,최종 입상·시간 최신 조정 결과 재대조.전체1300m63경주·원천 해시·기존 결과 보존 |\n\n'
    p.write_text(t.replace('같은 출전 자료가 여러 버전에 중복되므로',line+'같은 출전 자료가 여러 버전에 중복되므로',1))
    p=central/'research_register.json';reg=json.loads(p.read_text())
    for topic in reg['topics']:
        if topic['id']=='gate_lateral':topic['1300_sequence_gate_followup']={'source':link,**decision}
        if topic['id']=='running_style':
            topic['early_definition_held_distances_m']=[]
            topic['measurement_sequence_correction']={'source':link,**decision}
            topic['previous_prediction_excluded_distances_m']=[1300]
    save(p,reg)
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']]
    entries=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(files)]
    save(HERE/'artifact_manifest.json',{'files':entries,'listed_files':len(entries),'listed_bytes':sum(r['bytes'] for r in entries),
        'excludes':'self and final publication receipt'})
    files.append(HERE/'artifact_manifest.json')
    for r in manifest['files']:
        if r['role']=='conclusion_or_management':
            p=ROOT/r['path'];r.update(bytes=p.stat().st_size,sha256=sha(p))
    new=[{'path':str(p.relative_to(ROOT)),'role':'research_source','bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(files)]
    assert not {r['path'] for r in manifest['files']}&{r['path'] for r in new}
    manifest['files']+=new;save(manifestpath,manifest)
    for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256']
    for p in [HERE/'README.md',central/'01_GATE_LATERAL.md',central/'07_RUNNING_STYLE.md']:
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),target
    save(HERE/'publication_verification.json',{'status':'passed','previous_immutable_source_files_verified':len(immutable),
        'new_source_files':len(new),'new_source_bytes':sum(r['bytes'] for r in new),'central_manifest_entries_verified':len(manifest['files']),
        'management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in [central/'01_GATE_LATERAL.md',central/'07_RUNNING_STYLE.md',central/'README.md',central/'SOURCES.md',central/'research_register.json',manifestpath]},
        'central_manifest_sha256':sha(manifestpath),'local_links_verified':True,'no_database_operational_or_web_change':True})
    print('Report and central correction saved',flush=True)


if __name__=='__main__':main()
