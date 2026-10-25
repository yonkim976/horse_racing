"""Append this study without replacing other studies; self-inclusive byte accounting."""
import json,re
import study_common as c

CONCLUSION=c.R/'conclusions/58I_TRAINING_STATE_PREDICTION.md'
MARKER='training_state_20261024';INVENTORY=c.OUT/'artifact_inventory.json'
BEFORE=json.loads((c.OUT/'preexisting_files.json').read_text())
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def upsert(path,body):
    start=f'<!-- {MARKER}:start -->';end=f'<!-- {MARKER}:end -->';old=path.read_text();old_hash=c.sha(path)
    block=f'{start}\n{body.rstrip()}\n{end}'
    if start in old:
        a=old.index(start);b=old.index(end,a)+len(end);new=old[:a]+block+old[b:]
    else:new=old+'\n\n'+block+'\n'
    assert c.sha(path)==old_hash,'Concurrent write detected before append'
    path.write_text(new)
def sources():
    p=c.R/'conclusions/source_manifest.json';old_hash=c.sha(p);m=json.loads(p.read_text())
    files=[x for x in c.HERE.rglob('*') if x.is_file() and x.suffix in {'.py','.md','.json'} and x!=INVENTORY]
    for key,paths in [('sources',files),('conclusions',[CONCLUSION])]:
        index={v['path']:i for i,v in enumerate(m[key])}
        for x in sorted(paths):
            entry={'path':str(x.relative_to(c.ROOT)),'sha256':c.sha(x)}
            if entry['path'] in index:m[key][index[entry['path']]]=entry
            else:m[key].append(entry)
    m['data_end_by_study'][MARKER]={'study':c.HERE.name,'evaluation_start':'2024-01-05','evaluation_end':'2026-09-20',
        'venues':[1,3],'evaluation_races':4799,'evaluation_runners':50754,'final_models':18,'initial_fits':18,
        'main_candidate':'personal_t2','historical_publication_time_verified':False,'new_independent_test':False,'production_changed':False}
    m['updated_at']='2026-10-24';assert c.sha(p)==old_hash,'Concurrent manifest write detected';dump(p,m)
def inventory():
    paths=[p for p in c.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[CONCLUSION]
    files=[{'path':str(p.relative_to(c.ROOT)),'bytes':p.stat().st_size} for p in sorted(paths)]
    concurrent=json.loads((c.OUT/'concurrent_updates.json').read_text());modified=[]
    for name,v in BEFORE.items():
        p=c.ROOT/name;external=concurrent[name]['external_delta_bytes']
        modified.append({'path':name,'bytes_before':v['bytes'],'bytes_after':p.stat().st_size,
            'delta_bytes':p.stat().st_size-v['bytes'],'external_delta_bytes':external,
            'task_delta_bytes':p.stat().st_size-v['bytes']-external,'sha256_before':v['sha256'],'sha256_after':c.sha(p)})
    total=sum(v['bytes'] for v in files);assert total+c.PREVIOUS_BYTES<300_000_000
    s={'new_file_count':len(files),'new_bytes':total,'new_mib':total/1048576,'largest_file':max(files,key=lambda x:x['bytes']),
        'modified_file_count':5,'modified_final_bytes':sum(v['bytes_after'] for v in modified),
        'modified_delta_bytes':sum(v['delta_bytes'] for v in modified),
        'modified_external_delta_bytes':sum(v['external_delta_bytes'] for v in modified),
        'modified_task_delta_bytes':sum(v['task_delta_bytes'] for v in modified),
        'previous_eight_studies_new_bytes':c.PREVIOUS_BYTES,'combined_new_bytes':c.PREVIOUS_BYTES+total}
    return {'study':c.HERE.name,'status':'complete','summary':s,'new_files':files,'modified_existing_files':modified,
        'self_inclusive':True,'units':'logical bytes; MiB=bytes/1048576','excluded':'Referenced DB, existing full feature frame/state/base models, temporary connection-local tables and caches'}
def indexes(note,s):
    title='연구58I 일별조교와 말별 준비 변화 예측'
    upsert(c.R/'README.md',f'[{title}]({c.HERE.name}/README.md): {note} 서울·부산4,799경주·운영 유지.')
    upsert(c.R/'conclusions/README.md',f'[{title}]({CONCLUSION.name}): {note}')
    upsert(c.R/'conclusions/SOURCES.md',f'[{title}]({CONCLUSION.name}) · [원문](../{c.HERE.name}/README.md) · '
        f'[미사용 정보 감사](../{c.HERE.name}/CANDIDATE_AUDIT.md) · [결과](../{c.HERE.name}/outputs/results.json) · '
        f'[원천 감사](../{c.HERE.name}/outputs/source_audit.json) · [검증](../{c.HERE.name}/outputs/verification.json). {note}')
    upsert(c.R/'ARTIFACT_SIZE_LOG.md','| 날짜 | 작업 | 신규 파일 | 신규 bytes | MiB | 수정 파일 | 수정 최종 bytes | 순증감 bytes | 명세 |\n'
        '|---|---|---:|---:|---:|---:|---:|---:|---|\n'
        f'| 2026-10-24 | 일별조교·말별 준비 변화 예측 | {s["new_file_count"]} | {s["new_bytes"]} | {s["new_mib"]:.6f} | '
        f'5 | {s["modified_final_bytes"]} | {s["modified_delta_bytes"]:+d} | [명세]({c.HERE.name}/outputs/artifact_inventory.json) |\n\n'
        f'최대 `{s["largest_file"]["path"]}` {s["largest_file"]["bytes"]:,} bytes. 연속 아홉 연구 합계 {s["combined_new_bytes"]:,} / 300,000,000 bytes. '
        f'중앙5문서 수정 중 다른 작업 순증 {s["modified_external_delta_bytes"]:,} bytes는 보존했고, 이번 연구 순증은 {s["modified_task_delta_bytes"]:,} bytes다. '
        '기존 DB/전체특징/기본모델 참조, 신규 조교특징 차분2개와최종18모델 및 예측·검증만 보관.')
def finish(note):
    assert json.loads((c.OUT/'verification.json').read_text())['status']=='passed'
    if not (c.OUT/'concurrent_updates.json').exists():
        c.save(c.OUT/'concurrent_updates.json',{name:{'sha256_at_our_first_write':c.sha(c.ROOT/name),
            'bytes_at_our_first_write':(c.ROOT/name).stat().st_size,'external_delta_bytes':(c.ROOT/name).stat().st_size-v['bytes'],
            'changed_before_our_write':c.sha(c.ROOT/name)!=v['sha256'],
            'handling':'Preserve current file, append or replace only this study block; merge only own manifest entries.'} for name,v in BEFORE.items()})
    c.save(c.OUT/'completion_checks.json',{'status':'passed','bounded_experiment_complete':True,'initial_fits':18,'final_models':18,
        'original_base_models_referenced':6,'same_evaluation_races':4799,'source_database_unchanged':True,
        'operating_registry_unchanged':True,'further_evaluation_tuning_stopped':True,'published':False,'new_future_validation':False})
    if not INVENTORY.exists():dump(INVENTORY,{})
    summary=inventory()['summary']
    for _ in range(24):
        indexes(note,summary);sources();v=inventory();dump(INVENTORY,v);after=inventory()
        if v==after and summary==after['summary']:break
        summary=after['summary']
    else:raise RuntimeError('Inventory did not converge')
    assert json.loads(INVENTORY.read_text())==inventory()
    links=0
    for path in [c.HERE/'README.md',c.HERE/'PUBLICATION.md',c.HERE/'CANDIDATE_AUDIT.md',c.HERE/'CASES.md',CONCLUSION]:
        for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if '://' in target or target.startswith('#'):continue
            assert (path.parent/target.split('#')[0]).exists(),(path,target);links+=1
    m=json.loads((c.R/'conclusions/source_manifest.json').read_text())
    own=[v for k in ['sources','conclusions'] for v in m[k] if c.HERE.name in v['path'] or v['path']==str(CONCLUSION.relative_to(c.ROOT))]
    assert all(c.sha(c.ROOT/v['path'])==v['sha256'] for v in own)
    print(json.dumps({'status':'passed',**summary,'local_links_checked':links,'manifest_hashes_checked':len(own)},ensure_ascii=False))
