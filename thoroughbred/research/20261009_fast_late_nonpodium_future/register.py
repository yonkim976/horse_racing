"""Register follow-up 28H without replacing previous studies or shared contents."""
from pathlib import Path
import hashlib,json,re
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={r['path']:r for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']};before={};owned={}
def mutate(p,new,expected):
    old=p.read_text();assert old==expected,'Concurrent edit: reread latest';name=str(p.relative_to(ROOT));before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);owned[name]=dict(path=name,own_delta_bytes=len(new.encode())-len(old.encode()),own_final_bytes=len(new.encode()));assert p.read_text()==old;p.write_text(new)
    (O/'shared_edits_baseline.json').write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');(O/'shared_own_edits.json').write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(owned.values())),ensure_ascii=False,indent=2)+'\n')
def main():
    central=R/'conclusions/28H_FAST_LATE_NONPODIUM_FUTURE.md';assert not central.exists();pub=(H/'PUBLICATION.md').read_text();pub=re.sub(r'\]\((README.md|outputs/[^)]+)\)',lambda z:f'](../{H.name}/{z.group(1)})',pub);central.write_text(pub+f'\n\n2026-10-09 · 연구28 후속28H. 이전연구 보존,독립 연구 수41 유지. [구간별주표](../{H.name}/outputs/primary_summary.csv) · [용량](../{H.name}/outputs/artifact_inventory.json).\n')
    title='막판 우수·비입상 이후 입상';mark='<!-- fast_late_nonpodium_future_v1 -->';p=R/'conclusions/README.md';old=p.read_text();assert mark not in old;count_before=max(map(int,re.findall(r'^\| (\d+) \|',old,re.M)));entry=f'| [{title}]({central.name}) | 연구28 후속·부산600/400/200·서울600/200·180일 다음/3전 입상·현재성적 조정 |\n';new=old.replace('| [원 보고서 목록]',entry+'| [원 보고서 목록]',1).rstrip()+f'\n\n[{title}](../{H.name}/README.md) · [후속28H]({central.name}). 독립 연구 수 유지. '+mark+'\n';mutate(p,new,old);count_after=max(map(int,re.findall(r'^\| (\d+) \|',new,re.M)));assert count_before==count_after
    p=R/'README.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n[{title}]({H.name}/README.md): 연구28 후속28H. 막판빠른비입상마의원시후속입상률은대체로높았으나현재착순·패배시간차·능력·초반조정후추가효과불확실. 실제다음슬롯/180일/3전지원과재출전선택,2026초반미재현을분리했다. [중앙28H](conclusions/{central.name}). '+mark+'\n',old)
    p=R/'conclusions/SOURCES.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n## {title} 후속28H\n\n[보고서](../{H.name}/README.md) · [중앙28H]({central.name}) · [출처/해시](../{H.name}/SOURCES.md) · [검증](../{H.name}/outputs/verification.json) · [민감도검증](../{H.name}/outputs/sensitivity_verification.json) · [게시요약](../{H.name}/PUBLICATION.md) · [용량](../{H.name}/outputs/artifact_inventory.json). 원문159,014행의막판/누적시간·독립SQL실제미래슬롯·180일성숙·문턱·후속입상·군집구간을검증했다. 부산600/400/200·서울600/200,중첩합산/서울400생성없음. '+mark+'\n',old)
    p=R/'conclusions/source_manifest.json';old=p.read_text();manifest=json.loads(old)
    for key,files in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
        for f in files:
            name=str(f.relative_to(ROOT));item=dict(path=name,sha256=sha(f));i=next((i for i,r in enumerate(manifest[key]) if r['path']==name),None)
            if i is None:manifest[key].append(item)
            else:manifest[key][i]=item
    manifest['fast_late_nonpodium_future_added']=True;manifest['fast_late_nonpodium_future_note']='연구28 후속28H. 부산600/400/200·서울600/200막판우수비입상과실제다음/3전입상. 원시연관있으나현재성적조정추가가치/2026재현미확정.180일만기·미래슬롯·재출전선택분리,새예측모델0.';audit=json.loads((O/'source_audit.json').read_text());manifest['data_end_by_study'][H.name]=audit['data_end_by_meet']|dict(primary_index='2024~2025',followup_index='2026-01-01~2026-03-22',common_followup_end=audit['common_followup_end']);mutate(p,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',old)
    p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();mutate(p,old.rstrip()+f'\n| 2026-10-09 | {title} | 집계 중 | <!-- {H.name} -->\n',old)
    (O/'registration.json').write_text(json.dumps(dict(followup='28H',independent_study_count_before=count_before,independent_study_count_after=count_after,shared_files=5),ensure_ascii=False,indent=2)+'\n');print('Registered 28H',count_before,count_after)
if __name__=='__main__':main()
