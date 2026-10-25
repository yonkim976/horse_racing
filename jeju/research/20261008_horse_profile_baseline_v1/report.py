"""Publish verified results into the existing Jeju research documentation."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import run as e

H=e.HERE;O=e.OUT;ROOT=e.ROOT


def write_new(path,text):
    with path.open('x',encoding='utf-8') as f:f.write(text)


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,row))+' |' for row in rows])


def main():
    verification=json.loads((O/'final_verification.json').read_text());assert verification['passed']
    audit=json.loads((O/'audit.json').read_text());lock=json.loads((O/'prepared_lock.json').read_text())
    e.check_protected(lock['protected'])
    metrics=pd.read_csv(O/'metrics_by_group.csv');pairs=pd.read_csv(O/'paired_differences.csv')
    allm=metrics[metrics.group.eq('all')].set_index('variant')
    pair=pairs[pairs.group.eq('all')&pairs.comparison.eq('J1-J0')].set_index('metric')
    supported=bool((pair.loc[['log_loss','brier'],'delta']<0).all() and (pair.loc[['log_loss','brier'],'hi']<0).any())
    status='research_baseline_J1_supported' if supported else 'J0_retained_J1_inconclusive'
    decision=('J1은 전체 확률 손실의 사전 유지 기준을 충족했다. 다음 비교의 연구 기준선 후보로 유지한다.' if supported else
              'J1은 전체 확률 손실의 사전 유지 기준을 충족하지 못했다. J0를 최소 기준선으로 유지하고 J1은 비교 후보로 보존한다.')
    rows=[]
    for v in ['uniform','J0','J1']:
        r=allm.loc[v];rows.append([v,f'{r.log_loss:.6f}',f'{r.brier:.6f}',f'{r.top5_capture*100:.2f}%',f'{r.top5_all3*100:.2f}%',f'{r.six_combo_hit*100:.2f}%'])
    main_table=table(['모델','Top3 log loss ↓','Brier ↓','상위5두 입상마 포함률','상위5두 3마리 전부','6조합 적중률'],rows)
    diffrows=[]
    for col,label,scale,unit in [('log_loss','Top3 log loss',1,''),('brier','Brier',1,''),('top5_capture','상위5두 입상마 포함',100,'%p'),('top5_all3','상위5두 전원 포함',100,'%p'),('six_combo_hit','6조합 적중',100,'%p')]:
        r=pair.loc[col];diffrows.append([label,f'{r.delta*scale:+.6f}{unit}',f'{r.lo*scale:+.6f} ~ {r.hi*scale:+.6f}{unit}'])
    diff_table=table(['J1 − J0','차이','경주일 bootstrap 95% 구간'],diffrows)
    yearly=[]
    for year in [2024,2025,2026]:
        for v in ['J0','J1']:
            r=metrics[metrics.group.eq('year')&metrics.value.eq(str(year))&metrics.variant.eq(v)].iloc[0]
            yearly.append([str(year)+(' 부분' if year==2026 else ''),v,int(r.races),f'{r.log_loss:.6f}',f'{r.brier:.6f}',f'{r.top5_all3*100:.2f}%',f'{r.six_combo_hit*100:.2f}%'])
    yearly_table=table(['평가 연도','모델','경주','log loss','Brier','상위5두 전원','6조합'],yearly)
    distance=[]
    for d in e.DISTANCES:
        one=metrics[metrics.group.eq('distance')&metrics.value.eq(str(d))].set_index('variant')
        if 'J0' not in one.index:continue
        a=one.loc['J0'];b=one.loc['J1'];distance.append([d,int(a.races),f'{a.brier:.6f}',f'{b.brier:.6f}',f'{a.six_combo_hit*100:.2f}%',f'{b.six_combo_hit*100:.2f}%'])
    dist_table=table(['거리 m','평가 경주','J0 Brier','J1 Brier','J0 6조합','J1 6조합'],distance)
    examples=json.loads((O/'example_scorecards.json').read_text())
    def fmt(v):return '미관측' if v is None else f'{v:.3f}' if isinstance(v,float) else str(v)
    examplerows=[[r['horse_name'],r['horse_id'],r['distance_m'],r['observed_starts'],r['same_starts'],fmt(r['last_time_s']),fmt(r['mean5_s']),r['valid_n5'],fmt(r['best5_s']),fmt(r['fast2mean5_s']),fmt(r['trend_s'])] for r in examples]
    example_table=table(['말','ID','거리','관측 출전','동일거리 출전','직전 초','최근5 평균 초','유효 n5','최고 초','빠른2 평균 초','변화 초'],examplerows)
    example_text=f'''# 제주마 말별 평가표 사례

2026년 9월 19일 대상 경주의 9월 17일까지 이력이다. 표시 마명은 최신 프로필명이다. 시간은 동일거리 원기록이며 주로·중량 보정 전이다. 관측 출전 0은 보유 이력 부재이고 공식 신마 판정이 아니다.

{example_table}

최근5회는 실제 동일거리 출전 창이므로 유효 시간 n이 5보다 작을 수 있다. 변화는 최근3회 평균−이전3회 평균이며 양쪽 유효 n≥2일 때만 계산한다. 음수는 최근 기록이 빨라진 방향이다. 각 값의 원천 출전 ID·날짜·NULL·당시 주로·등급·부담중량은 [평가표 JSON](outputs_v2/example_scorecards.json)에 보존했다. 최고 기록과 빠른2회 평균의 차이는 한 번의 기록에 얼마나 의존하는지 읽는 단서이며 반복 가능성의 확정 확률이 아니다.

[계산 계약](CONTRACT.md), [전체 평가표와 입력](outputs_v2/features.parquet), [학습 전 검산](outputs_v2/preflight_verification.json).
'''
    write_new(H/'EXAMPLE_SCORECARDS.md',example_text)
    body=f'''# 제주마 원기록 평가표와 첫 Top3 모델 비교

{decision} 아래 결과는 이미 여러 연구에 사용한 2024~2026년의 시간순 후향 개발 비교다. 운영 HY_R_FORM의 성능 비교나 독립 미래 검증이 아니며 DB·운영 모델은 변경하지 않았다.

## 비교한 입력과 대상

J0는 이번 거리·원문 등급·두수, 관측 경력·출전 간격·직전 사건 나이와 성별, 동일거리 이력수·최근성·직전 시간·최근5회 평균과 유효 수를 사용하는 13열 최소 모델이다. J1은 최근3회 평균과 수, 최근5회 최고·빠른2회 평균·편차, 이전3회 평균과 수, 최근−이전 변화의 8열을 더한 21열 모델이다. 이번 중량·번호·함수율·월·당일 체중·기수·구간·조교·심사·상대능력 입력은 이번 비교에 넣지 않았다. 임의의 종합 능력 점수도 만들지 않았다. [전체 입력과 계산식](CONTRACT.md), [추가·유지·제외 열](outputs_v2/feature_contract.json).

보유 품질 원천 {audit['source_rows']:,}행·{audit['source_races']:,}경주 중 2017년 이후 후보 {audit['label_candidate_races']:,}경주를 감사했다. 현재 800~1610m의 정상·완전 착순 1~N·6두 이상·전체 저장 결과와 같은 편성 {audit['included_races']:,}경주·{audit['included_rows']:,}출전을 포함했고 {audit['excluded_races']:,}경주는 거리·불완결·비정상 결과 등으로 제외했다. [경주별 포함·제외](outputs_v2/race_inclusion_ledger.csv), [연도·거리·무이력 지원](outputs_v2/population_support.csv). DNF·실격·동착·부분 편성은 경주 전체 제외하는 사후 모집단이다. 포함된 편성에서는 이력 결측을 이유로 말을 제거하지 않았다.

과거 이력은 2002년부터의 관측 출전 중 한국 날짜 T−2까지다. 동일거리 최근 실제 출전 창에서 DNF·시간 결측은 자리를 유지하고 시간만 NULL로 둔다. 다른 거리 기록을 환산하지 않았다. 과거 foundation의 최근 ‘유효 기록’ 창과 계산이 달라 새 버전으로 보존했다. [실제 6마리 평가표](EXAMPLE_SCORECARDS.md).

## 전체 확률과 후보 및 조합 결과

평가 {audit['evaluation_races']:,}경주·{audit['evaluation_rows']:,}출전, 2024년부터 2026년 9월 19일까지다. log loss·Brier는 경주별 말 평균 후 경주 균등 평균으로 작을수록 좋다. 상위5두 입상마 포함률은 실제 입상마 3두 중 포함한 비율, 전원 포함은 3두 모두 포함한 경주의 비율이다.

{main_table}

{diff_table}

확률 손실 차이는 음수가 개선, 포함·적중률 차이는 양수가 개선이다. 구간은 경주일 단위 paired bootstrap 2,000회의 점별 95% 구간이다. 같은 말의 장기 반복에 대한 별도 말 군집 추론은 하지 않았다. 여러 하위군의 최고 결과를 확증으로 사용하지 않는다. [전체 그룹 지표](outputs_v2/metrics_by_group.csv), [차이와 구간](outputs_v2/paired_differences.csv), [runner 균등과 이력군](outputs_v2/runner_metrics.csv), [확률 구간별 보정](outputs_v2/calibration_bins.csv).

## 연도와 거리별 차이

{yearly_table}

{dist_table}

2026년은 부분연도다. 1300·1400·1610m는 이전 학습 지원이 약하거나 없으므로 합동 모델 출력이 있어도 해당 거리 적성을 검증한 것으로 보지 않는다. 전체 이력 0·1~4·5+ 및 동일거리 유효 시간 0·1~4·5+의 말별 결과, 무이력·저경력 말 포함 경주별 결과는 전체 표에 분리했다. 이력 부재군은 공식 신마와 다르다. 번호 동점 정렬 때문에 무이력 말의 순위에 번호가 간접 작용할 수 있으며 번호 효과를 학습했다고 해석하지 않는다.

## 시간순 학습과 조합 확률

평가 Y마다 초기 학습 2017~Y−3, 조기종료 Y−2, 같은 트리 수로 Y−2까지 재학습, 온도 보정 Y−1, 평가 Y로 분리했다. 6개 LightGBM 모델에 동일 설정을 적용하고 결과 확인 후 튜닝하지 않았다. 평가 기간 중 과거 T−2 이력은 갱신하되 모델과 온도는 고정했다. 결측은 결측 분기, 원문 범주는 학습 어휘만 사용했다. 원시 입력 수와 모델이 실제 분기에 사용한 열 수는 다르다. 각 폴더의 model_meta.json에 시간 경계·입력·트리 수·온도·분기 gain을 저장했다. gain은 인과효과나 독립적 변수 중요도가 아니다.

순서 없는 3두 집합에 말별 점수 합의 softmax를 주고 집합에서 Top3 주변확률을 합산했다. 집합 합 1, 말별 Top3 합 3이다. 이는 가산 집합 가정이며 말들의 동반입상 상호작용을 별도로 학습하지 않았다. 말별 확률 3개의 단순 곱을 공동 확률로 사용하지 않았다. 최대6개 서로 다른 조합을 같은 규칙으로 선택했다. [말별 동결 예측](outputs_v2/runner_predictions.parquet), [6조합과 확률](outputs_v2/six_combinations.csv), [경주별 결과](outputs_v2/race_metrics.csv). 적중률은 수익률이 아니다.

## 확인된 결과와 남은 연구

확인된 사실은 같은 모집단·학습 설정에서 J0와 J1의 위 성능 차이, 원천 이력의 T−2 절단, NULL 보존, 전체 편성의 확률 합, 재로딩한 6개 모델의 예측 일치다. [학습 전 검증](outputs_v2/preflight_verification.json), [모델·확률·조합·지표 검증](outputs_v2/final_verification.json).

현재 조건은 결과 원장으로 재구성했고 과거 게시·정정 시각과 T−2 등록 출전집합을 입증하지 못했다. 현재 프로필 품종은 과거 품종의 확증이 아니며 보유 이력은 평생 전체 경력이 아니다. 정상 완전 편성의 사후 선택, 합동 거리 모델의 희소 거리 외삽, 환경 차이가 남은 원기록, 점별 반복 평가의 불확실성이 있다. 이번 비교는 보정 계수를 검증하거나 최근 상태를 생리적 건강으로 판정한 결과가 아니다.

{decision} 다음 묶음은 직전·이번 부담중량·증감 3열의 제한된 비교다. 현재 중량의 공개시점 가정은 별도로 표시하고 고정 초/kg 보정으로 바꾸지 않는다. 게이트·환경·구간·주행심사는 각각 이후 실험으로 분리한다. 새 설계의 확정에는 아직 보지 않은 향후 기간이 필요하다.

## 재현과 출처

실행 순서는 `run.py prepare`, `verify.py preflight`, `run.py train`, `verify.py final`, `report.py`다. 기존 결과 경로가 있으면 덮어쓰지 않고 중단한다. [코드](run.py), [별도 검산 코드](verify.py), [학습 전 해시와 버전](outputs_v2/prepared_lock.json), [완료 기록](outputs_v2/training_completion.json).

제주 [기초 계약](../20261007_foundation_v1/EXPERIMENT_PROTOCOL.md)·[환경 파일럿](../20261007_environment_correction_pilot_v1/RESEARCH_CONTRACT.md)·[연구 종합](../20261008_research_synthesis_v1/README.md)을 참조했다. 더러브렛 [말별 평가표 모델](../../../thoroughbred/research/20261008_horse_profile_model_v1/README.md)과 [부담중량 추가 비교](../../../thoroughbred/research/20261008_profile_carried_weight_v1/README.md)는 단계별 비교·시간순 분할·집합 확률 구조의 참고 출처다. 더러브렛의 보정계수·거리 정의·학습 산출물을 이식하지 않았다.
'''
    write_new(H/'README.md',body)
    e.save(O/'decision.json',dict(status=status,J1_retention_gate_passed=supported,operationally_applied=False,
        primary_comparison='J1-J0',gate='both_losses_lower_and_at_least_one_upper_CI_below_zero',
        already_seen_retrospective=True,independent_future_validation=False))
    # Preserve the exact prior management files and apply only this study's addition.
    C=H.parent/'conclusions';backup=O/'publication_before';backup.mkdir(exist_ok=False)
    names=['README.md','SOURCES.md','03_FOUNDATION.md','research_register.json','source_manifest.json']
    old={n:(C/n).read_text(encoding='utf-8') for n in names}
    for n,text in old.items():write_new(backup/n,text)
    conclusion='07_HORSE_PROFILE_BASELINE.md'
    concise=f'''# 제주마 원기록 말별 평가표와 Top3 기준선

{decision} 2017년부터 학습하고 2024~2026년 9월 19일의 {audit['evaluation_races']:,}경주·{audit['evaluation_rows']:,}출전을 시간순으로 평가했다. 2026년은 부분연도이고 기존에 본 기간의 후향 개발 비교다.

{main_table}

{diff_table}

J0는 원기록 중심 13열, J1은 최고·반복 수행·편차·변화·관측수 8열을 더한 21열이다. 무이력 말을 제외하지 않고 같은 정상 완전 편성에서 비교했다. 최근 동일거리 실제 출전 창의 시간 결측은 NULL로 유지한다. T−2 당시 등록 출전집합·게시/정정 시각은 재생하지 못했고, DNF·동착 등을 포함하는 운영 전체 성능은 이 결과로 확정하지 않는다. 1300·1400·1610m의 합동 모델 출력은 희소 학습 지원의 한계가 있다.

조합은 가산 집합 가정에서 계산했으며 동반입상 상호작용을 따로 학습하지 않았다. 이번 부담중량·번호·환경·구간·기수는 입력에서 제외했다. 운영 HY_R_FORM이나 DB를 변경하지 않았다. 다음 묶음은 부담중량 3열의 별도 비교다.

[전체 연구와 연도·거리 결과](../20261008_horse_profile_baseline_v1/README.md), [실제 평가표](../20261008_horse_profile_baseline_v1/EXAMPLE_SCORECARDS.md), [사전 계약](../20261008_horse_profile_baseline_v1/CONTRACT.md), [검증](../20261008_horse_profile_baseline_v1/outputs_v2/final_verification.json).
'''
    assert not (C/conclusion).exists()
    write_new(C/conclusion,concise)
    linkrow=f'| [말별 평가표와 첫 Top3 기준선]({conclusion}) | 원기록 J0와 능력·신뢰도 추가 J1의 같은 편성 시간순 비교 | {"J1 연구 유지 근거 확인" if supported else "J0 유지·J1 추가 개선 미확정"}, 운영 미반영 |\n'
    updated={}
    text=old['README.md'];marker='| [원 연구와 버전 목록](SOURCES.md)'
    assert marker in text;updated['README.md']=text.replace(marker,linkrow+marker,1)
    marker='같은 출전 자료가 여러 버전에 중복되므로'
    assert marker in old['SOURCES.md']
    updated['SOURCES.md']=old['SOURCES.md'].replace(marker,'| [20261008_horse_profile_baseline_v1](../20261008_horse_profile_baseline_v1/README.md) | 원기록 평가표 J0와 최고·반복·편차·변화 추가 J1의 Top3 확률·후보·6조합 비교. 정상 완전 편성, 무이력 유지, 후향 개발 평가, 운영 미반영 |\n\n'+marker,1)
    updated['03_FOUNDATION.md']=old['03_FOUNDATION.md']+f'\n\n## 원기록 평가표의 첫 모델 비교\n\n2026년 10월 8일 [J0와 J1 비교]({conclusion})를 완료했다. 최근 유효 기록을 건너뛰어 찾는 이전 기초 예시와 달리 실제 동일거리 출전 창의 NULL을 유지한다. 이전 기초 설계·예시는 보존하고 새 계산 계약과 실제 평가표는 새 연구에 연결한다. {decision}\n'
    register=json.loads(old['research_register.json'])
    assert not any(t['id']=='horse_profile_baseline' for t in register['topics'])
    register['topics'].append(dict(id='horse_profile_baseline',title='말별 평가표와 첫 Top3 기준선',conclusion=conclusion,
         latest_source='../20261008_horse_profile_baseline_v1/README.md',period_start='2017-01-01',period_end='2026-09-19',
         evaluation_period_start='2024-01-01',status=status,operationally_applied=False,
         input_counts={'J0':13,'J1':21},evaluation_races=audit['evaluation_races'],evaluation_rows=audit['evaluation_rows']))
    updated['research_register.json']=json.dumps(register,ensure_ascii=False,indent=2)+'\n'
    for n,text in updated.items():
        assert (C/n).read_text(encoding='utf-8')==old[n],f'Concurrent publication change: {n}'
        (C/n).write_text(text,encoding='utf-8')
    manifest=json.loads(old['source_manifest.json']);paths={x['path']:x for x in manifest['files']}
    new=[C/conclusion,C/'README.md',C/'SOURCES.md',C/'03_FOUNDATION.md',C/'research_register.json']
    new += [p for p in H.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'publication_before' not in p.parts]
    for p in new:
        rel=str(p.relative_to(ROOT));paths[rel]=dict(path=rel,role='horse_profile_baseline_research' if p.is_relative_to(H) else 'conclusion_or_management',sha256=e.sha(p),bytes=p.stat().st_size)
    manifest['files']=list(paths.values())
    assert (C/'source_manifest.json').read_text(encoding='utf-8')==old['source_manifest.json']
    (C/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for n in updated:assert (C/n).read_text(encoding='utf-8')==updated[n]
    # Validate each new listed hash and link destination without updating older research.
    for p in new:assert e.sha(p)==paths[str(p.relative_to(ROOT))]['sha256']
    inventory=[]
    for p in sorted(H.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            inventory.append(dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=e.sha(p)))
    for n in names+[conclusion]:
        p=C/n;inventory.append(dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=e.sha(p),role='updated_conclusion'))
    e.save(H/'ARTIFACT_INVENTORY.json',dict(files=inventory,new_research_bytes=sum(p.stat().st_size for p in H.rglob('*') if p.is_file()),
        modified_management_files=names+ [conclusion],previous_versions_preserved='outputs_v2/publication_before'))
    print(decision,flush=True)
    print(main_table,flush=True)


if __name__=='__main__':main()
