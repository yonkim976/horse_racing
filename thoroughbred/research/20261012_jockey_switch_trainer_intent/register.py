"""Append a new independent entity study, preserving concurrently maintained indexes."""
from pathlib import Path
import hashlib,json,re
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={r['path']:r for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']};before={};owned={}
def mutate(p,new,expected):
    old=p.read_text();assert old==expected,'Concurrent edit; reread latest';name=str(p.relative_to(ROOT));before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);owned[name]=dict(path=name,own_delta_bytes=len(new.encode())-len(old.encode()),own_final_bytes=len(new.encode()));assert p.read_text()==old;p.write_text(new)
    (O/'shared_edits_baseline.json').write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');(O/'shared_own_edits.json').write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(owned.values())),ensure_ascii=False,indent=2)+'\n')
def main():
    central=R/'conclusions/50_JOCKEY_SWITCH_TRAINER_INTENT.md';assert not central.exists();pub=(H/'PUBLICATION.md').read_text();pub=re.sub(r'\]\((README.md|SOURCES.md|outputs/[^)]+|figures/[^)]+)\)',lambda z:f'](../{H.name}/{z.group(1)})',pub);central.write_text(pub+f'\n\n[연구 원본](../{H.name}/README.md) · [용량](../{H.name}/outputs/artifact_inventory.json). 새 독립 연구, 기존 결론 보존.\n')
    title='기수 교체·상위 기수와 조교사 기용 관계';mark='<!-- jockey_switch_trainer_intent_20261012 -->';summary='보통→상위 교체2,283출전 입상35.87%, 보통유지28.90%. 같은말/경주·과거상태 통제+4.21%p(95%+1.21~+7.21), 조교사 선호기수 추가효과 불확실. 승부의지 인과입증/운영반영 없음.'
    p=R/'conclusions/README.md';old=p.read_text();assert mark not in old;count_before=max(map(int,re.findall(r'^\| (\d+) \|',old,re.M)));nextnum=count_before+1
    line=f'| {nextnum} | [기수 교체·상위 기수·조교사 관계]({central.name}) | 전년도 상위기수·같은말/경주 통제·특정기수/조교사 기용 | 관찰 연관성·승부의지 및 예측개선 미확정 |\n'
    new=re.sub(rf'(^\| {count_before} \|[^\n]*\n)',lambda m:m.group(1)+line,old,count=1,flags=re.M);assert new!=old;new=new.rstrip()+f'\n\n[{title}]({central.name}): {summary} [원본](../{H.name}/README.md). '+mark+'\n';mutate(p,new,old)
    p=R/'README.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n[{title}]({H.name}/README.md): {summary} [중앙 결론](conclusions/{central.name}). '+mark+'\n',old)
    p=R/'conclusions/SOURCES.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n## {title}\n\n[원본](../{H.name}/README.md) · [중앙]({central.name}) · [출처/해시](../{H.name}/SOURCES.md) · [독립 검증](../{H.name}/outputs/verification.json) · [게시 요약](../{H.name}/PUBLICATION.md) · [용량](../{H.name}/outputs/artifact_inventory.json). 서울/부산159,014실제출전 신원·순위·시간·직전SQL슬롯·전년도 분류,공동회귀/군집구간을 확인했다. 기수ID영문55행 복원,마주동일 민감도,새 확률모델/DB 변경 없음. '+mark+'\n',old)
    p=R/'conclusions/source_manifest.json';old=p.read_text();manifest=json.loads(old)
    for key,files in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
        for f in files:
            name=str(f.relative_to(ROOT));item=dict(path=name,sha256=sha(f));i=next((i for i,r in enumerate(manifest[key]) if r['path']==name),None)
            if i is None:manifest[key].append(item)
            else:manifest[key][i]=item
    current_paths={str(f.relative_to(ROOT)):f for f in [R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md']}
    for bucket in ['sources','conclusions']:
        for item in manifest[bucket]:
            if item['path'] in current_paths:
                f=current_paths[item['path']];item['sha256']=sha(f)
                if 'bytes' in item:item['bytes']=f.stat().st_size
    manifest['jockey_switch_trainer_intent_added']=True;manifest['jockey_switch_trainer_intent_note']=summary;manifest['data_end_by_study'][H.name]=json.loads((O/'source_audit.json').read_text())['data_end_by_meet']|dict(primary='2024~2025',confirmation='2026 partial',prior_rank_reference='previous calendar year only');mutate(p,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',old)
    p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();mutate(p,old.rstrip()+f'\n| 2026-10-12 | {title} | 집계 중 | <!-- {H.name} -->\n',old)
    (O/'registration.json').write_text(json.dumps(dict(new_independent_study=True,central_document=central.name,independent_table_count_before=count_before,independent_table_count_after=nextnum,shared_files=5),ensure_ascii=False,indent=2)+'\n');print('Registered',central.name,nextnum)
if __name__=='__main__':main()
