"""Maintain research indexes and a self-inclusive, bounded artifact inventory."""
import json,re
import axis_common as c

CONCLUSION=c.R/'conclusions/58E_BUSAN_GRADE5_AXIS_DIAGNOSIS.md'
MARKER='busan_grade5_axis_20261022';INVENTORY=c.OUT/'artifact_inventory.json'
BEFORE=json.loads((c.OUT/'preexisting_files.json').read_text())

def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def upsert(path,body):
    start=f'<!-- {MARKER}:start -->';end=f'<!-- {MARKER}:end -->';old=path.read_text()
    block=f'{start}\n{body.rstrip()}\n{end}'
    if start in old:
        a=old.index(start);b=old.index(end,a)+len(end);value=old[:a]+block+old[b:]
    else:
        assert c.sha(path)==BEFORE[str(path.relative_to(c.ROOT))]['sha256'],path
        value=old+'\n\n'+block+'\n'
    path.write_text(value)

def sources():
    path=c.R/'conclusions/source_manifest.json';m=json.loads(path.read_text())
    if MARKER not in m['data_end_by_study']:assert c.sha(path)==BEFORE[str(path.relative_to(c.ROOT))]['sha256']
    files=[p for p in c.HERE.rglob('*') if p.is_file() and p.suffix in {'.py','.md','.json'} and p!=INVENTORY]
    for key,paths in [('sources',files),('conclusions',[CONCLUSION])]:
        lookup={v['path']:i for i,v in enumerate(m[key])}
        for p in sorted(paths):
            entry={'path':str(p.relative_to(c.ROOT)),'sha256':c.sha(p)}
            if entry['path'] in lookup:m[key][lookup[entry['path']]]=entry
            else:m[key].append(entry)
    m['data_end_by_study'][MARKER]={'study':c.HERE.name,'evaluation_start':'2024-01-05','evaluation_end':'2026-09-20',
        'target':'Busan domestic grade5 1300m/1600m','target_races':210,'target_2026_races':72,'all_busan_races':1961,
        'all_comparison_races':4799,'new_base_models':0,'new_final_switch_models':3,'pilot_fits':3,
        'new_independent_test':False,'production_changed':False}
    m['updated_at']='2026-10-22';dump(path,m)

def inventory():
    paths=[p for p in c.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[CONCLUSION]
    files=[{'path':str(p.relative_to(c.ROOT)),'bytes':p.stat().st_size} for p in sorted(paths)]
    modified=[]
    for name,v in BEFORE.items():
        p=c.ROOT/name
        modified.append({'path':name,'bytes_before':v['bytes'],'bytes_after':p.stat().st_size,
            'delta_bytes':p.stat().st_size-v['bytes'],'sha256_before':v['sha256'],'sha256_after':c.sha(p)})
    total=sum(x['bytes'] for x in files);assert total+139_039_058<300_000_000
    summary={'new_file_count':len(files),'new_bytes':total,'largest_file':max(files,key=lambda x:x['bytes']),
        'modified_file_count':5,'modified_final_bytes':sum(x['bytes_after'] for x in modified),
        'modified_delta_bytes':sum(x['delta_bytes'] for x in modified),
        'previous_five_studies_new_bytes':139_039_058,'combined_new_bytes':139_039_058+total}
    return {'study':c.HERE.name,'status':'complete','summary':summary,'new_files':files,'modified_existing_files':modified,
        'self_inclusive':True,'units':'logical bytes; MiB=bytes/1048576','excluded':'Referenced existing DB, full features/states/models and transient cache/virtualenv'}

def indexes(note,s):
    title='연구58E 부산 국5등급 1300·1600m 축 실패 진단'
    upsert(c.R/'README.md',f'[{title}]({c.HERE.name}/README.md): {note} 대상210경주·2026년72경주·운영 유지.')
    upsert(c.R/'conclusions/README.md',f'[{title}]({CONCLUSION.name}): {note}')
    upsert(c.R/'conclusions/SOURCES.md',f'[{title}]({CONCLUSION.name}) · [원문](../{c.HERE.name}/README.md) · '
        f'[진단](../{c.HERE.name}/outputs/diagnostics.json) · [교체 결과](../{c.HERE.name}/outputs/switch_results.json) · '
        f'[검증](../{c.HERE.name}/outputs/verification.json). {note}')
    upsert(c.R/'ARTIFACT_SIZE_LOG.md',
        '| 날짜 | 작업 | 신규 파일 | 신규 bytes | MiB | 수정 파일 | 수정 최종 bytes | 순증감 bytes | 명세 |\n'
        '|---|---|---:|---:|---:|---:|---:|---:|---|\n'
        f'| 2026-10-22 | 부산 국5등급 축 진단·교체 시험 | {s["new_file_count"]} | {s["new_bytes"]} | {s["new_bytes"]/1048576:.6f} | '
        f'5 | {s["modified_final_bytes"]} | {s["modified_delta_bytes"]:+d} | [명세]({c.HERE.name}/outputs/artifact_inventory.json) |\n\n'
        f'최대 `{s["largest_file"]["path"]}` {s["largest_file"]["bytes"]:,} bytes. 연속 여섯 연구 합계 {s["combined_new_bytes"]:,} / 300,000,000 bytes. 기존 DB/전체특징/상태/기본모델은 참조했다.')

def finish(note):
    c.check();assert json.loads((c.OUT/'verification.json').read_text())['status']=='passed'
    c.save(c.OUT/'completion_checks.json',{'status':'passed','bounded_experiment_complete':True,'base_models_trained':0,
        'final_switch_models':3,'pilot_models':3,'source_database_unchanged':True,'operating_registry_unchanged':True,
        'additional_tuning_stopped':True,'production_changed':False,'future_independent_validation':False})
    if not INVENTORY.exists():dump(INVENTORY,{})
    summary=inventory()['summary']
    for _ in range(20):
        indexes(note,summary);sources();value=inventory();dump(INVENTORY,value);after=inventory()
        if value==after and summary==after['summary']:break
        summary=after['summary']
    else:raise RuntimeError('Inventory did not converge')
    assert json.loads(INVENTORY.read_text())==inventory()
    links=0
    for path in [c.HERE/'README.md',c.HERE/'PUBLICATION.md',c.HERE/'CASES_2026.md',CONCLUSION]:
        for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if '://' in link or link.startswith('#'):continue
            assert (path.parent/link.split('#')[0]).exists(),(path,link)
            links+=1
    m=json.loads((c.R/'conclusions/source_manifest.json').read_text())
    entries=[x for key in ['sources','conclusions'] for x in m[key] if c.HERE.name in x['path'] or x['path']==str(CONCLUSION.relative_to(c.ROOT))]
    assert all(c.sha(c.ROOT/x['path'])==x['sha256'] for x in entries)
    print(json.dumps({'status':'passed',**summary,'local_links_checked':links,'source_hashes_checked':len(entries)},ensure_ascii=False))
