"""One-time registration and self-inclusive byte inventory for this feasibility audit."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = json.loads(Path('/private/tmp/medical_feasibility_baseline.json').read_text())
CENTRAL = ROOT / 'thoroughbred/research/conclusions/55_MEDICAL_RECORD_FEASIBILITY.md'
MARK = '<!-- medical_record_feasibility_20261014 -->'

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def dump(p, data):
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

# Fail before changing shared documents if another task has edited them.
for item in BASE['shared']:
    assert digest(ROOT/item['path']) == item['sha256'], item['path']
for item in BASE['references']:
    assert digest(ROOT/item['path']) == item['sha256'], item['path']
BASE['new_study_folder_existed_before_work'] = False
dump(HERE/'outputs/baseline.json',BASE)
refs = '\n'.join(f"- `{x['path']}`: {x['bytes']} bytes; SHA-256 `{x['sha256']}`" for x in BASE['references'])
(HERE/'SOURCES.md').write_text('# 의료기록 자료 점검의 출처\n\n'+refs+'\n\n'
    '연구 코어 `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`를 읽기 전용으로 조회했다. '
    '원 DB는 참조 입력이며 신규 용량에 넣지 않는다. 전체 DB 해시는 이번 점검에서 새로 산출하지 않았다. '
    '현재 조회 결과와 기존 적재 수치를 대조했으며 원문 의미 문서는 임상 중증도나 성적 효과의 근거로 사용하지 않았다.\n')
note = ('의료기록의 경주 연결 가능성을 점검했다. API 243,411관측·공식 번호 연결 2,631두, '
        '정확한 중복 튜플 축소 후 226,770개 중 앞뒤 경주 159,547개. '
        '오래된 자료의 대상 말 부족과 Text 공식 번호 부재를 확인했다. '
        '항목별 성적 효과 미추정, 독립 효과 연구 수·운영 유지.')
for filename,link in [
 ('thoroughbred/research/README.md','20261014_medical_record_feasibility/README.md'),
 ('thoroughbred/research/conclusions/README.md','55_MEDICAL_RECORD_FEASIBILITY.md'),
 ('thoroughbred/research/conclusions/SOURCES.md','55_MEDICAL_RECORD_FEASIBILITY.md')]:
    p=ROOT/filename
    assert MARK not in p.read_text()
    p.write_text(p.read_text()+f'\n\n{MARK}\n[의료기록과 이후 경주 성적의 분석 가능성]({link}): {note}\n')

verification = {'status':'passed','scope':'feasibility_only',
 'source_documents_preserved':len(BASE['references']),
 'sql_bisect_temporal_comparisons':453540,
 'effects_estimated':False,'db_connection_read_only':True,
 'checks':json.loads((HERE/'outputs/feasibility.json').read_text())['checks']}
assert all(verification['checks'].values())
dump(HERE/'outputs/verification.json',verification)

manifest_path=ROOT/'thoroughbred/research/conclusions/source_manifest.json'
manifest=json.loads(manifest_path.read_text())
tracked=[HERE/'README.md',HERE/'PUBLICATION.md',HERE/'SOURCES.md',HERE/'audit.py',
         HERE/'outputs/feasibility.json',HERE/'outputs/verification.json']
for p in tracked:
    manifest['sources'].append({'path':str(p.relative_to(ROOT)),'sha256':digest(p)})
manifest['conclusions'].append({'path':str(CENTRAL.relative_to(ROOT)),'sha256':digest(CENTRAL)})
manifest['medical_record_feasibility_added']=True
manifest['medical_record_feasibility_note']=note
manifest.setdefault('data_end_by_study',{})['medical_record_feasibility_20261014']={
 'medical':'2026-09-29','seoul_races':'2026-09-20','busan_races':'2026-09-18',
 'yeongcheon_races':'2026-09-20','status':'feasibility_only_no_effect_estimates'}
# Refresh occurrences of the shared indexes we changed, without rewriting unrelated entries.
changed={item['path'] for item in BASE['shared'][:3]}
for key in ['sources','conclusions']:
    for entry in manifest[key]:
        if entry.get('path') in changed:
            entry['sha256']=digest(ROOT/entry['path'])
dump(manifest_path,manifest)

inv=HERE/'outputs/artifact_inventory.json'
size=HERE/'outputs/artifact_size.md'
log=ROOT/'thoroughbred/research/ARTIFACT_SIZE_LOG.md'
original_log=log.read_text()
assert MARK not in original_log
inv.write_text('{}\n');size.write_text('')
last=None
for _ in range(30):
    fresh=sorted([p for p in HERE.rglob('*') if p.is_file()]+[CENTRAL])
    new=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size} for p in fresh]
    modified=[]
    for item in BASE['shared']:
        p=ROOT/item['path'];n=p.stat().st_size
        modified.append({'path':item['path'],'before_bytes':item['bytes'],'final_bytes':n,
                         'own_delta_bytes':n-item['bytes'],'external_delta_bytes':0})
    total=sum(x['bytes'] for x in new);delta=sum(x['own_delta_bytes'] for x in modified)
    data={'new_file_count':len(new),'new_total_bytes':total,'new_total_mib':f'{total/1048576:.6f}',
          'new_files':new,'modified_files':modified,'modified_file_count':len(modified),
          'modified_final_bytes':sum(x['final_bytes'] for x in modified),
          'own_modified_delta_bytes':delta,'net_added_bytes':total+delta,
          'self_included':True,'unchanged_inputs_db_and_temporary_files_excluded':True}
    dump(inv,data)
    size.write_text('# 의료기록 자료 점검의 용량\n\n'+
        f'신규 {len(new)}파일, {total:,} bytes ({total/1048576:.6f} MiB). '
        f'기존 {len(modified)}파일 수정, 자체 순증감 {delta:+,} bytes. '
        '명세·용량 문서 및 중앙 결론을 포함한다. DB·기존 자료·임시 파일은 제외한다.\n')
    log.write_text(original_log+f'\n{MARK}\n'
        f'- 2026-10-14 의료기록 분석 가능성 점검: 신규 {len(new)}파일 {total:,} bytes '
        f'({total/1048576:.6f} MiB), 기존 {len(modified)}파일 자체 순증감 {delta:+,} bytes. '
        '[명세](20261014_medical_record_feasibility/outputs/artifact_inventory.json).\n')
    state=(total,delta,inv.stat().st_size,size.stat().st_size,log.stat().st_size)
    if state==last:
        break
    last=state
else:
    raise AssertionError('size inventory did not converge')
for x in data['new_files']:
    assert (ROOT/x['path']).stat().st_size==x['bytes'],x['path']
for x in BASE['references']:
    assert digest(ROOT/x['path'])==x['sha256']
print(json.dumps({k:data[k] for k in ['new_file_count','new_total_bytes','new_total_mib',
                                       'modified_file_count','own_modified_delta_bytes']}))
