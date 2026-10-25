"""Finalize the local report indexes and the self-inclusive storage record."""
import json,re
import support as s

CONCLUSION=s.R/'conclusions/58D_STATE_ABLATION_CALIBRATION.md'
MARKER='state_followup_20261022'
INVENTORY=s.OUT/'artifact_inventory.json'
BEFORE=json.loads((s.OUT/'preexisting_files.json').read_text())

def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def upsert(path,body):
    start=f'<!-- {MARKER}:start -->';end=f'<!-- {MARKER}:end -->';old=path.read_text()
    block=f'{start}\n{body.rstrip()}\n{end}'
    if start in old:
        a=old.index(start);b=old.index(end,a)+len(end);text=old[:a]+block+old[b:]
    else:
        assert s.sha(path)==BEFORE[str(path.relative_to(s.ROOT))]['sha256'],path
        text=old+'\n\n'+block+'\n'
    path.write_text(text)

def sources():
    path=s.R/'conclusions/source_manifest.json';value=json.loads(path.read_text())
    if MARKER not in value['data_end_by_study']:
        assert s.sha(path)==BEFORE[str(path.relative_to(s.ROOT))]['sha256']
    paths=[p for p in s.HERE.rglob('*') if p.is_file() and p.suffix in {'.md','.py','.json'} and p!=INVENTORY]
    for key,files in [('sources',paths),('conclusions',[CONCLUSION])]:
        lookup={item['path']:i for i,item in enumerate(value[key])}
        for p in sorted(files):
            item={'path':str(p.relative_to(s.ROOT)),'sha256':s.sha(p)}
            if item['path'] in lookup:value[key][lookup[item['path']]]=item
            else:value[key].append(item)
    value['data_end_by_study'][MARKER]={'study':s.HERE.name,'evaluation_start':'2024-01-05',
        'evaluation_end':'2026-09-20','races':4799,'runner_rows':50754,'new_models':18,
        'calibration_fits':12,'later_raw_races_audited':79,'later_raw_races_evaluated':0,
        'new_independent_test':False,'production_changed':False}
    value['updated_at']='2026-10-22';dump(path,value)

def inventory():
    paths=[p for p in s.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[CONCLUSION]
    files=[{'path':str(p.relative_to(s.ROOT)),'bytes':p.stat().st_size} for p in sorted(paths)]
    modifications=[]
    for name,before in BEFORE.items():
        p=s.ROOT/name
        modifications.append({'path':name,'bytes_before':before['bytes'],'bytes_after':p.stat().st_size,
            'delta_bytes':p.stat().st_size-before['bytes'],'sha256_before':before['sha256'],'sha256_after':s.sha(p)})
    total=sum(item['bytes'] for item in files);assert total+103_392_015<300_000_000
    summary={'new_file_count':len(files),'new_bytes':total,'largest_file':max(files,key=lambda x:x['bytes']),
        'modified_file_count':5,'modified_final_bytes':sum(x['bytes_after'] for x in modifications),
        'modified_delta_bytes':sum(x['delta_bytes'] for x in modifications),
        'previous_four_studies_new_bytes':103_392_015,'combined_new_bytes':103_392_015+total}
    return {'study':s.HERE.name,'status':'complete','summary':summary,'new_files':files,
        'modified_existing_files':modifications,'self_inclusive':True,'units':'logical bytes; MiB=bytes/1048576',
        'excluded':'Existing source DB/features/states/models and transient cache/bytecode/virtualenv dependencies'}

def indexes(note,summary):
    title='연구58D 상태 입력 분해와 고정 추천 확률 보정'
    upsert(s.R/'README.md',f'[{title}]({s.HERE.name}/README.md): {note} 같은 4,799경주·최종 18모델·보정 12회·운영 유지.')
    upsert(s.R/'conclusions/README.md',f'[{title}]({CONCLUSION.name}): {note}')
    upsert(s.R/'conclusions/SOURCES.md',f'[{title}]({CONCLUSION.name}) · [원문](../{s.HERE.name}/README.md) · '
        f'[결과](../{s.HERE.name}/outputs/results.json) · [검증](../{s.HERE.name}/outputs/verification.json). {note}')
    upsert(s.R/'ARTIFACT_SIZE_LOG.md',
        '| 날짜 | 작업 | 신규 파일 | 신규 bytes | MiB | 수정 파일 | 수정 최종 bytes | 순증감 bytes | 명세 |\n'
        '|---|---|---:|---:|---:|---:|---:|---:|---|\n'
        f'| 2026-10-22 | 상태 입력 분해·공동확률 보정 | {summary["new_file_count"]} | {summary["new_bytes"]} | '
        f'{summary["new_bytes"]/1048576:.6f} | 5 | {summary["modified_final_bytes"]} | {summary["modified_delta_bytes"]:+d} | '
        f'[명세]({s.HERE.name}/outputs/artifact_inventory.json) |\n\n'
        f'최대 `{summary["largest_file"]["path"]}` {summary["largest_file"]["bytes"]:,} bytes. '
        f'이번 연속 다섯 연구 합계 {summary["combined_new_bytes"]:,} bytes / 300,000,000 bytes. 기존 DB/전체특징/상태/모델은 참조했다.')

def finish(note):
    s.check();verification=json.loads((s.OUT/'verification.json').read_text());assert verification['status']=='passed'
    s.save(s.OUT/'completion_checks.json',{'status':'passed','final_models':18,'initial_training_fits':18,
        'calibrator_fits':12,'new_evaluation_variants':5,'new_race_rows':23995,
        'source_databases_unchanged':True,'operating_registry_unchanged':True,
        'bounded_experiment_complete':True,'additional_tuning_stopped':True,'production_changed':False,
        'later_raw_races_audited':79,'later_raw_races_evaluated':0})
    if not INVENTORY.exists():dump(INVENTORY,{})
    summary=inventory()['summary']
    for _ in range(20):
        indexes(note,summary);sources();value=inventory();dump(INVENTORY,value);after=inventory()
        if value==after and summary==after['summary']:break
        summary=after['summary']
    else:raise RuntimeError('Artifact inventory did not stabilize')
    assert json.loads(INVENTORY.read_text())==inventory()
    links=0
    for path in [s.HERE/'README.md',s.HERE/'PUBLICATION.md',CONCLUSION]:
        for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if '://' in link or link.startswith('#'):continue
            assert (path.parent/link.split('#')[0]).exists(),(path,link)
            links+=1
    manifest=json.loads((s.R/'conclusions/source_manifest.json').read_text())
    entries=[x for key in ['sources','conclusions'] for x in manifest[key]
        if s.HERE.name in x['path'] or x['path']==str(CONCLUSION.relative_to(s.ROOT))]
    assert all(s.sha(s.ROOT/x['path'])==x['sha256'] for x in entries)
    print(json.dumps({'status':'passed',**summary,'local_links_checked':links,'source_hashes_checked':len(entries)},ensure_ascii=False))
