"""Append follow-up 28G, preserving shared contents and recording own byte deltas."""
from pathlib import Path
import json,hashlib,re
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={x['path']:x for x in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']};before={};owned={}
def mutate(p,new,expected):
    old=p.read_text();assert old==expected,'Concurrent edit: reread latest';name=str(p.relative_to(ROOT))
    before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);owned[name]=dict(path=name,own_delta_bytes=len(new.encode())-len(old.encode()),own_final_bytes=len(new.encode()))
    assert p.read_text()==old;p.write_text(new)
    (O/'shared_edits_baseline.json').write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n')
    (O/'shared_own_edits.json').write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(owned.values())),ensure_ascii=False,indent=2)+'\n')
def main():
    central=R/'conclusions/28G_FRONT_DENSITY_CLOSER_BENEFIT.md';assert not central.exists()
    content=(H/'PUBLICATION.md').read_text();content=re.sub(r'\]\((README.md|outputs/[^)]+)\)',lambda z:f'](../{H.name}/{z.group(1)})',content)
    central.write_text(content+f'\n\n2026-10-09 · 연구28 후속28G. 이전28C~28F 보존. 독립 연구 수41 유지. [지역·거리표](../{H.name}/outputs/regional_distance_summary.csv) · [용량](../{H.name}/outputs/artifact_inventory.json).\n')
    mark='<!-- front_density_closer_benefit_v1 -->';title='선행 밀집과 뒤쪽형 회복·입상'
    p=R/'conclusions/README.md';old=p.read_text();assert mark not in old;count_before=max(map(int,re.findall(r'^\| (\d+) \|',old,re.M)))
    entry=f'| [{title}]({central.name}) | 연구28 후속·과거 선행형수/실제첫마군/실제초반페이스·회복과입상 구분 |\n'
    new=old.replace('| [원 보고서 목록]',entry+'| [원 보고서 목록]',1).rstrip()+f'\n\n[{title}](../{H.name}/README.md) · [후속28G]({central.name}). 독립 연구 수 유지. '+mark+'\n';mutate(p,new,old);count_after=max(map(int,re.findall(r'^\| (\d+) \|',new,re.M)));assert count_before==count_after
    p=R/'README.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n[{title}]({H.name}/README.md): 연구28 후속28G. 선행형이 많은 편성/빠른 실제초반페이스와 뒤쪽형 막판회복의 관측연결은 있으나,입상 증가와 실제첫마군수만의 이득은 미확정. 엄격공통셀/같은말/사후추가 가법조정과 표본피복을 분리했다. [중앙28G](conclusions/{central.name}). '+mark+'\n',old)
    p=R/'conclusions/SOURCES.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n## {title} 후속28G\n\n[보고서](../{H.name}/README.md) · [중앙28G]({central.name}) · [입력 해시](../{H.name}/SOURCES.md) · [검증](../{H.name}/outputs/verification.json) · [보조검증](../{H.name}/outputs/adjusted_verification.json) · [게시요약](../{H.name}/PUBLICATION.md) · [용량](../{H.name}/outputs/artifact_inventory.json). 원문159,014행S1F시간을 대조하고 전체명단 후보수·자기제외·과거연도 페이스참조를 검증했다. 회복과입상,사전성향과관측속도,주설계와탐색조정을구분한다. '+mark+'\n',old)
    p=R/'conclusions/source_manifest.json';old=p.read_text();manifest=json.loads(old)
    for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
        for f in paths:
            name=str(f.relative_to(ROOT));item=dict(path=name,sha256=sha(f));idx=next((i for i,x in enumerate(manifest[key]) if x['path']==name),None)
            if idx is None:manifest[key].append(item)
            else:manifest[key][idx]=item
    manifest['front_density_closer_benefit_added']=True;manifest['front_density_closer_benefit_note']='연구28 후속28G. 선행형수/실제첫마군수/S1F빠른3두와 뒤쪽형회복·입상. 관측연관성,입상가산점미확정,가법조정은사후탐색,새예측모델0개.'
    manifest['data_end_by_study'][H.name]=json.loads((O/'source_audit.json').read_text())['data_end_by_meet']|dict(primary_evaluation='2024~2025',followup='2026부분');mutate(p,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',old)
    p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();mutate(p,old.rstrip()+f'\n| 2026-10-09 | {title} | 집계 중 | <!-- {H.name} -->\n',old)
    (O/'registration.json').write_text(json.dumps(dict(followup='28G',independent_study_count_before=count_before,independent_study_count_after=count_after,shared_files=5),ensure_ascii=False,indent=2)+'\n');print('Registered 28G',count_before,count_after)
if __name__=='__main__':main()
