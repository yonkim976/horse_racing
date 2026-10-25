"""Preserve previous central documents and register this read-only comparison."""
from pathlib import Path
import hashlib
import json
import shutil
import re
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
CENTRAL=HERE.parent/'conclusions'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
assert json.loads((HERE/'outputs/independent_verification.json').read_text())['passed']
backup=HERE/'publication_before'
backup.mkdir(exist_ok=False)
names=['README.md','SOURCES.md','research_register.json','source_manifest.json','09_FIELD_RELATIVE_ABILITY.md']
before={}
for name in names:
    p=CENTRAL/name
    before[name]=dict(sha256=sha(p),bytes=p.stat().st_size)
    shutil.copyfile(p,backup/name)
target=CENTRAL/'10_OPERATING_MODEL_COMPARISON.md'
assert not target.exists()
target.write_text('''# 제주 운영 모델과 새 모델의 비교

같은2026년1월2일~9월12일467경주·4,475출전에서는 운영 HY_R_FORM이 새 J0·R1보다 앞선다. 날짜·경주번호·전체 말ID·번호·거리·Top3 정답을 맞춘 회고 비교이며 새 독립 검증은 아니다.

| 지표 | 운영 HY_R_FORM | J0 | R1 |
|---|---:|---:|---:|
| Brier ↓ | 0.187645 | 0.202563 | 0.199224 |
| log loss ↓ | 0.555417 | 0.592488 | 0.584759 |
| 최고점1두 입상 | 61.03% | 50.54% | 54.39% |
| 상위5두 입상마 전부 | 38.97% | 26.77% | 26.12% |
| 집합분포 상위6조합 적중 | 30.84% | 21.41% | 21.41% |

6조합은 각 모델의 기존 집합확률 전체에서 최대6개를 재구성한 비교 지표다. 과거 실제 게시 추천표나 수익률이 아니다. 운영 모델의 PL 분포와 새 모델의 점수합 분포를 각각 보존했다.

R1−운영 Brier 차이+0.011579(경주일95% +0.007978~+0.015120),6조합−9.42%p(−13.97~−4.71)다. 70경주일 대응bootstrap5,000회·점별구간이다. 상위3두 단일집합 차이는0을 포함한다.

운영 모델은 선택108열·순서68열로 상대능력·전개경쟁·기수·게이트·중량·구간 등 더 많은 정보를 쓴다. 새 모델은 원기록 기준 J0 13열, 상대능력 추가 R1 21열이다. 운영 학습은2025년6월까지, 새 모델 재학습은2024년까지여서 같은 학습조건의 변수별 효과 비교는 아니다. 원천 스냅샷·정정 이력과 과거 공개 시각 미확정 한계도 유지한다.

새 모델을 묶음별로 발전시키되 운영 모델을 계속 대조군으로 둔다. R1의 J0 대비 확률 개선과 운영 모델 대비 열세를 함께 기록한다. 운영 모델 교체·DB 변경·추가 학습·재보정은 없다.

[전체 방법·표본·한계](../20261009_operating_model_comparison_v1/README.md),[검증](../20261009_operating_model_comparison_v1/outputs/verification.json),[원 하이브리드 함수 독립 재계산](../20261009_operating_model_comparison_v1/outputs/independent_verification.json).
''')
p=CENTRAL/'README.md'
s=p.read_text();needle='| [원 연구와 버전 목록](SOURCES.md)'
assert needle in s
s=s.replace(needle,'| [운영 모델과 새 기준선 비교](10_OPERATING_MODEL_COMPARISON.md) | 동일467경주에서 HY_R_FORM이 J0·R1보다 확률·후보·6조합 우세 | 저장 예측 비교 완료, 운영 유지 |\n'+needle)
p.write_text(s)
p=CENTRAL/'SOURCES.md'
p.write_text(p.read_text()+'\n- [20261009_operating_model_comparison_v1](../20261009_operating_model_comparison_v1/README.md): 운영 HY_R_FORM과 J0·R1의2026년 공통467경주·4,475출전 비교. 원 집합분포·주변확률 재현,상위6개 집합 재구성,70경주일 대응구간. 운영 우세·학습조건 차이·운영 변경 없음.\n')
p=CENTRAL/'09_FIELD_RELATIVE_ABILITY.md'
p.write_text(p.read_text()+'\n후속 [운영 모델과 비교](10_OPERATING_MODEL_COMPARISON.md): 공통2026년467경주에서는 HY_R_FORM Brier0.187645·6조합30.84%,R1 Brier0.199224·6조합21.41%였다. R1의 J0 대비 개선을 운영 우위로 해석하지 않는다. 학습 분할·입력 정보·원천 스냅샷이 달라 변수별 기여를 분리한 실험은 아니다.\n')
p=CENTRAL/'research_register.json'
reg=json.loads(p.read_text());assert isinstance(reg['topics'],list)
reg['topics'].append(dict(id='operating_model_comparison',title='운영 모델과 새 기준선의 같은 경주 비교',
    conclusion=target.name,latest_source='../'+HERE.name+'/README.md',period_start='2026-01-02',
    period_end='2026-09-12',partial_2026=True,evaluation_races=467,evaluation_rows=4475,
    status='operating_model_ahead_on_matched_retrospective_cohort',operationally_applied=False,
    independent_holdout=False,models=['HY_R_FORM','J0','R1'],
    six_combo_definition='top6_sets_from_each_native_distribution_reconstructed_not_published_tickets'))
save(p,reg)
# Preserve reasons for all non-overlap races from the original inclusion ledger.
a=pd.read_csv(HERE/'outputs/race_alignment.csv')
l=pd.read_csv(HERE.parent/'20261008_horse_profile_baseline_v1/outputs_v2/race_inclusion_ledger.csv')
a[a.reason.ne('matched')].merge(l,on='race_id',how='left').to_csv(HERE/'outputs/non_overlap_details.csv',index=False)
assert (a[a.reason.eq('new_only')].race_id.str[:10]>'2026-09-12').all()
assert not a[a.reason.eq('operating_only')].merge(l,on='race_id').included.any()
checked=0
for p in [HERE/'README.md',target,CENTRAL/'09_FIELD_RELATIVE_ABILITY.md']:
    for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if '://' in link or link.startswith('#'):continue
        assert (p.parent/link.split('#')[0]).exists(),(p,link)
        checked+=1
changed=[CENTRAL/n for n in names if n!='source_manifest.json']+[target]
after={str(p.relative_to(ROOT)):dict(sha256=sha(p),bytes=p.stat().st_size) for p in changed}
save(HERE/'outputs/publication_verification.json',dict(passed=True,previous_central_documents_preserved=before,
    changed_central_documents=after,local_links_checked=checked,operating_only_all_excluded_by_new_existing_rules=True,
    new_only_all_after_operating_evaluation_cap=True,operationally_applied=False))
manifest_path=CENTRAL/'source_manifest.json'
manifest=json.loads(manifest_path.read_text())
paths=changed+[p for p in HERE.rglob('*') if p.is_file() and p.name!='ARTIFACT_INVENTORY.json']
# The previous central manifest is preserved as a backup source, not replaced historically.
updates={str(p.relative_to(ROOT)):dict(path=str(p.relative_to(ROOT)),role='operating_model_comparison' if p.is_relative_to(HERE) else 'conclusion_or_management',sha256=sha(p),bytes=p.stat().st_size) for p in paths}
manifest['files']=[updates.pop(row['path'],row) for row in manifest['files']]+list(updates.values())
manifest['updated_at']='2026-10-09'
manifest.setdefault('verification',{})['operating_model_comparison']='20261009_operating_model_comparison_v1/outputs/independent_verification.json passed'
manifest['managed_files_bytes_excluding_this_manifest']=sum(row['bytes'] for row in manifest['files'])
save(manifest_path,manifest)
inventory={str(p.relative_to(HERE)):dict(sha256=sha(p),bytes=p.stat().st_size) for p in HERE.rglob('*') if p.is_file() and p.name!='ARTIFACT_INVENTORY.json'}
save(HERE/'ARTIFACT_INVENTORY.json',dict(files=inventory,files_count=len(inventory),total_bytes=sum(v['bytes'] for v in inventory.values())))
for path,info in inventory.items():assert sha(HERE/path)==info['sha256']
for p in changed:
    row=next(x for x in manifest['files'] if x['path']==str(p.relative_to(ROOT)))
    assert sha(p)==row['sha256']
print(json.dumps(dict(passed=True,files=len(inventory),bytes=sum(v['bytes'] for v in inventory.values()),local_links_checked=checked),ensure_ascii=False))
