"""Publish hash-verified Jeju reward-head review and append central conclusions."""
from pathlib import Path
import hashlib,json,re
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
MAIN=HERE.parent/'20261025_top5_reward_learning_v1'
REVIEW=HERE.parent/'20261025_top5_reward_learning_review_v1'
CENTRAL=HERE.parent/'conclusions'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def record(p):return dict(path=str(p.relative_to(ROOT)),sha256=digest(p),bytes=p.stat().st_size)
def write_new(p,d):
    with p.open('x',encoding='utf-8') as f:
        if isinstance(d,str):f.write(d)
        else:json.dump(d,f,ensure_ascii=False,indent=2);f.write('\n')
def main():
    assert (MAIN/'FINAL_MANIFEST.json').is_file() and (REVIEW/'FINAL_REVIEW_MANIFEST.json').is_file()
    metrics=json.loads((HERE/'ROOT_OUTCOME_RECOMPUTATION.json').read_text())
    assert metrics['passed'] and metrics['primary']['candidate_hits']==434
    assert json.loads((HERE/'ROOT_PRESERVATION_AUDIT.json').read_text())['passed']
    assert json.loads((REVIEW/'INDEPENDENT_OUTCOME_AUDIT.json').read_text())['status']=='PASS'
    paths=[MAIN/'FINAL_MANIFEST.json',REVIEW/'FINAL_REVIEW_MANIFEST.json',REVIEW/'INDEPENDENT_OUTCOME_AUDIT.json']+list(HERE.glob('ROOT_*AUDIT.json'))+[HERE/'ROOT_MAIN_RECONCILIATION.json',HERE/'ROOT_OUTCOME_RECOMPUTATION.json']
    final=dict(status='COMPLETE_RETROSPECTIVE_REWARD_SELECTOR_VERIFIED_GATE_FAILED',executor_model='gpt-6-luna',reasoning_effort='xhigh',horse_assessment_frozen=True,base_model_training_calls=0,selection_head_training_calls=3,optimizer_retries=0,reward=dict(all_actual_top3_in_five=1,otherwise=-1),architecture='same fixed raw score prior plus additive 11-input head as previous selector; only loss changed',training_objective='negative exact stochastic expected reward + 0.5 * beta squared norm; lambda=1',deterministic_evaluation='maximum-energy exact five-set',period=['2024-01-05','2026-09-19'],partial_2026=True,primary_distances_m=[900,1000,1110,1200],primary=metrics['primary'],primary_vs_previous_selector=metrics['primary_vs_old'],full_secondary=metrics['full'],full_secondary_vs_previous_selector=metrics['full_vs_old'],primary_gate_passed=False,decision='retain existing raw-score Top5; do not adopt new reward head',limitations=['Repeated historical development cohort, not a fresh future holdout.','Stochastic training reward differs from deterministic argmax coverage.','Additive head has no explicit pair/field interactions.','Training policy distribution is not calibrated probability or evidence of market advantage.','Initial gradient aggregation bug was fixed before any optimizer; failed and passed audits preserved.'],database_opened=False,operating_model_or_registry_changed=False,evidence={str(p.relative_to(ROOT)):record(p) for p in paths})
    write_new(HERE/'ROOT_FINAL_REVIEW.json',final)
    write_new(HERE/'README.md',"""# Top5 보상형 선택기 감독 검토

GPT-6 Luna xhigh가 고정된 말 평가 위에 선택기 3개를 실제 학습했고, 감독은 목적함수·전체 학습 gradient·1,779경주 선택·정답 집계와 날짜 신뢰구간을 별도로 재계산했다. 독립 검토자 역시 학습과 선택·결과를 재현했다. 검산은 통과했으나 개선 기준은 실패했다.

| 방식 | 주4거리 1,503경주 | 전체 1,779경주(보조) |
|---|---:|---:|
| 기존 점수 Top5 | 439 (29.208%) | 519 (29.174%) |
| 직전 partial-event 선택기 | 435 (28.942%) | 520 (29.230%) |
| 이번 +1/−1 보상 선택기 | 434 (28.876%) | 515 (28.949%) |

주 평가에서 기존 점수 대비 새로 전원 포함 47경주·반대로 누락52경주, −0.333%p·날짜 paired bootstrap 95% 구간 [−1.646,+1.047]%p다. 직전 선택기 대비 새로43·누락44경주, −0.067%p·구간 [−1.318,+1.136]%p다. 두 비교 모두 개선 기준 미통과로 기존 점수 Top5를 유지한다.

모든 5두 집합에 실제 Top3가 모두 들어가면 +1, 하나라도 빠지면 −1을 준다. 그 확률적 선택정책의 기대 보상을 과거 경주에서 최대화했다. 입력·전처리·원점수 prior·학습기간·규제는 직전과 같고 손실함수만 바꿨다. 말 평가와 운영 모델·DB는 그대로다. 평가 시에는 가장 높은 에너지의 집합 하나를 선택하므로 훈련 보상과 실제 전원 포함률의 차이가 있다. 이번 작은 가법 head에는 말 사이의 별도 상호작용이 없다.

평가는 2024-01-05~2026-09-19이며 2026년은 부분연도다. 반복 사용한 개발기간으로 새 미래 검증이나 수익률·시장 우위를 뜻하지 않는다. 보상학습 전체의 실패를 뜻하지도 않는다. 다음 연구 가설은 기존 집합에서 말을 교체할 때 잃는 정보와 편성 상호작용을 별도로 검증하는 것이다. 새 조건이나 규칙은 이번 결과에 맞춰 추가하지 않았다.

학습 전 gradient 합산 오류를 발견해 optimizer 실행 전에 수정했다. 실패 감사와 수정 후 수치 검산을 함께 보존했다. 신규 산출물은 세 폴더 합계 3MB 안팎으로 제한하고 원천·DB·후보 전체 행렬은 복사하지 않았다.

[연구 보고서](../20261025_top5_reward_learning_v1/README.md), [독립 검토](../20261025_top5_reward_learning_review_v1/README.md), [최종 감독 기록](ROOT_FINAL_REVIEW.json), [원천·보존 검산](ROOT_PRESERVATION_AUDIT.json), [학습 검산](ROOT_FITTED_MODEL_AUDIT.json), [선택 검산](ROOT_CHOICES_AUDIT.json), [결과 재계산](ROOT_OUTCOME_RECOMPUTATION.json).
""")
    names=['19_JOINT_RELATIONSHIP.md','README.md','SOURCES.md','research_register.json','source_manifest.json']
    before={n:(CENTRAL/n).read_bytes() for n in names}
    marker='<!-- top5_reward_learning_v1_20261025 -->'
    append={
    '19_JOINT_RELATIONSHIP.md':"""## Top5 +1/−1 보상 목적 학습: 2026-10-25 후속

말 평가·11입력·전처리·학습 OOF·규제는 직전 그대로 두고 목적함수만 바꿔 선택기 3개를 실제 학습했다. 실제 Top3가 5두에 모두 있으면 +1, 누락 시 −1이며 모든 C(N,5)의 정확한 기대 보상을 계산한다. 실제 선택은 결정적 최대 에너지다. 훈련 정책은 보정된 예측확률이 아니고 가법 head에 별도 말 간 상호작용은 없다.

주4거리 1,503경주에서 기존 점수439회(29.208%), 직전 선택기435회(28.942%), 보상형434회(28.876%)다. 보상형−점수 −0.333%p·날짜95%구간 [−1.646,+1.047]%p, 새포함47·반대누락52다. 보상형−직전 −0.067%p·구간 [−1.318,+1.136]%p, 새포함43·누락44다. 전체1,779경주는 각각519/520/515회다. 두 주 비교 모두 개선 기준에 못 미쳐 기존 점수Top5를 유지한다.

2024-01-05~2026-09-19의 반복 개발표본·2026 부분연도다. 새 미래검증·시장우위·운영 반영을 뜻하지 않는다. 초기 gradient 집계 오류는 학습 전에 수정해 세 fit 모두 검산을 통과했다. 원천24개·보호파일5개 해시 유지, DB·기존 모델은 미변경이다.

[연구 원본](../20261025_top5_reward_learning_v1/README.md), [감독 검토](../20261025_top5_reward_learning_rootreview_v1/README.md), [독립 검토](../20261025_top5_reward_learning_review_v1/README.md).
""",
    'README.md':"""[Top5 보상형 선택기 실제 학습](19_JOINT_RELATIONSHIP.md): 고정 말 평가·동일11입력 위 선택기3fit, 전원포함+1/누락−1 기대보상. 주1,503경주 점수439·직전435·보상형434, 전체1,779경주519/520/515. 두 비교 CI에0포함·개선 미확인으로 점수Top5유지. [연구](../20261025_top5_reward_learning_v1/README.md), [감독](../20261025_top5_reward_learning_rootreview_v1/ROOT_FINAL_REVIEW.json).
""",
    'SOURCES.md':"""2026-10-25 보상학습 후속: [Top5 +1/−1 선택기](../20261025_top5_reward_learning_v1/README.md) — 기존 말 평가/전처리/11입력 고정·OOF expanding3fit·동일1,503/1,779경주. [독립 검토](../20261025_top5_reward_learning_review_v1/README.md), [감독 최종검토](../20261025_top5_reward_learning_rootreview_v1/ROOT_FINAL_REVIEW.json). 기대보상과 결정적 포함률 구분·개선기준실패·운영미반영.
"""}
    new={}
    for n,t in append.items():
        assert marker not in before[n].decode()
        new[n]=before[n]+('\n\n'+marker+'\n'+t).encode()
    register=json.loads(before['research_register.json']);topics=[x for x in register['topics'] if x['id']=='joint_relationship'];assert len(topics)==1
    assert 'top5_reward_learning_followup' not in topics[0]
    topics[0]['top5_reward_learning_followup']=dict(study='../20261025_top5_reward_learning_v1/README.md',manifest='../20261025_top5_reward_learning_v1/FINAL_MANIFEST.json',root_review='../20261025_top5_reward_learning_rootreview_v1/ROOT_FINAL_REVIEW.json',independent_review='../20261025_top5_reward_learning_review_v1/FINAL_REVIEW_MANIFEST.json',head_training_calls=3,base_model_training_calls=0,primary_races=1503,primary_hits=dict(raw=439,previous_selector=435,reward=434),full_races=1779,full_hits=dict(raw=519,previous_selector=520,reward=515),primary_reward_minus_raw_ci95_pp=[-1.6459112411176642,1.0467122306480943],primary_reward_minus_previous_ci95_pp=[-1.3184568723119485,1.1356045424181698],performance_gate_passed=False,operational_change=False)
    latest=dict(updated_at='2026-10-25',latest_study='jeju/research/20261025_top5_reward_learning_v1',latest_verification='jeju/research/20261025_top5_reward_learning_rootreview_v1/ROOT_FINAL_REVIEW.json',latest_status='reward_top5_learning_verified_improvement_not_confirmed')
    register.update(latest);new['research_register.json']=(json.dumps(register,ensure_ascii=False,indent=2)+'\n').encode()
    # Compare-and-swap management files: preserve every unrelated existing byte/record.
    for n in names:assert(CENTRAL/n).read_bytes()==before[n]
    for n,b in new.items():(CENTRAL/n).write_bytes(b)
    manifest=json.loads(before['source_manifest.json']);previous={x['path']:x for x in manifest['files']};updated=dict(previous)
    managed_paths=[CENTRAL/n for n in names if n!='source_manifest.json']
    new_files=[p for folder in [MAIN,REVIEW,HERE] for p in folder.rglob('*') if p.is_file()]
    assert not any('__pycache__' in p.parts for p in new_files)
    for p in managed_paths+new_files:
        rel=str(p.relative_to(ROOT));v=record(p);v['role']=previous.get(rel,{}).get('role','top5_reward_learning_20261025_evidence');updated[rel]=v
    manifest['files']=[updated[k] for k in sorted(updated)]
    manifest['verification']['top5_reward_learning_20261025']=dict(passed=True,scope='new three folders and five management files; root final manifest and publication receipt are generated afterwards to avoid circular references',previous_source_metadata_preserved=True,old_external_sources_revalidated=False,source_hashes_revalidated=24,protected_artifacts_revalidated=5,head_training_calls=3,base_model_training_calls=0,database_opened=False,performance_gate_passed=False)
    manifest.update(latest);manifest['managed_files_bytes_excluding_this_manifest']=sum(x['bytes'] for x in manifest['files'])
    assert(CENTRAL/'source_manifest.json').read_bytes()==before['source_manifest.json']
    (CENTRAL/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    changes={n:dict(before_sha256=hashlib.sha256(before[n]).hexdigest(),after_sha256=digest(CENTRAL/n),before_bytes=len(before[n]),after_bytes=(CENTRAL/n).stat().st_size) for n in names}
    net=sum(v['after_bytes']-v['before_bytes'] for v in changes.values())
    write_new(HERE/'ROOT_PUBLICATION_RECEIPT.json',dict(passed=True,changed_management_files=changes,management_net_added_bytes=net,prior_unrelated_source_records_preserved=True))
    owned=[p for p in HERE.rglob('*') if p.is_file() and p.name!='FINAL_MANIFEST.json']
    write_new(HERE/'FINAL_MANIFEST.json',dict(status='COMPLETE',files=[record(p) for p in sorted(owned)],external_final_manifests=[record(MAIN/'FINAL_MANIFEST.json'),record(REVIEW/'FINAL_REVIEW_MANIFEST.json')],management_net_added_bytes=net))
    total=sum(p.stat().st_size for folder in [MAIN,REVIEW,HERE] for p in folder.rglob('*') if p.is_file())
    assert total<10_000_000
    print(json.dumps(dict(passed=True,three_folders_bytes=total,management_net_added_bytes=net,total_new_net_bytes=total+net,root_final_manifest_sha256=digest(HERE/'FINAL_MANIFEST.json'))))
if __name__=='__main__':main()
