"""Append follow-up50E and refresh all shared manifest occurrences, preserving old research."""
from pathlib import Path
import json,re,hashlib
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={r['path']:r for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']};before={};owned={}
def mutate(p,new,expected):
 old=p.read_text();assert old==expected,'Concurrent edit; reread';name=str(p.relative_to(ROOT));before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);owned[name]=dict(path=name,own_delta_bytes=len(new.encode())-len(old.encode()),own_final_bytes=len(new.encode()));assert p.read_text()==old;p.write_text(new)
 (O/'shared_edits_baseline.json').write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');(O/'shared_own_edits.json').write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(owned.values())),ensure_ascii=False,indent=2)+'\n')
def main():
 central=R/'conclusions/50E_ALL_PAIR_NONPODIUM_SWITCH_IMPROVEMENT.md';assert not central.exists();pub=(H/'PUBLICATION.md').read_text();pub=re.sub(r'\]\((README.md|SOURCES.md|outputs/[^)]+|figures/[^)]+)\)',lambda z:f'](../{H.name}/{z.group(1)})',pub);central.write_text(pub+f'\n\n研究50/50A/50B/50C/50D 후속50E,독립 연구 수 유지. [원 보고서](../{H.name}/README.md) · [용량](../{H.name}/outputs/artifact_inventory.json).\n'.replace('研究','연구'))
 title='전체 마방 기수 조합의 비입상 개선과 변경 당일 성적';mark='<!-- all_pair_nonpodium_switch_improvement_20261013 -->';summary='전체3386관측조합·동결213보정.2019~2025계획변경40272중비입상29568,상대착순개선11807/동조건기록단축5108(중복3166).능력·직전성적/기록·편성·기수수준통제후전체기간유리한BH0.모든연도·최근44모형전수재현,최근통계신호는표본지원부족.사건빈도와비입상내성적·조건부선택을구분,변경그한경주만,운영유지.'
 p=R/'conclusions/README.md';old=p.read_text();assert mark not in old;count=max(map(int,re.findall(r'^\| (\d+) \|',old,re.M)));mutate(p,old.rstrip()+f'\n\n[{title}]({central.name}): {summary} [원본](../{H.name}/README.md). 연구50E 후속,독립수 유지. '+mark+'\n',old)
 p=R/'README.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n[{title}]({H.name}/README.md): {summary} [중앙](conclusions/{central.name}). '+mark+'\n',old)
 p=R/'conclusions/SOURCES.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n## {title}\n\n[원본](../{H.name}/README.md) · [중앙]({central.name}) · [출처·해시](../{H.name}/SOURCES.md) · [독립검증](../{H.name}/outputs/verification.json) · [게시 요약](../{H.name}/PUBLICATION.md) · [용량](../{H.name}/outputs/artifact_inventory.json). 50A의159,014분류 불변참조,79,551완결기간배경/8,674부분기간배경. 전체조합원시집계/213동결대조,주사건·비입상조건부4결과×11기간44모형전체희소LSQR/사전구간·모든BH구간/30,708원시그룹·44,341당일이벤트·고정BH 검증. 기존자료/DB/운영 변경없음. '+mark+'\n',old)
 p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
 for bucket,files in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central])]:
  for f in files:m[bucket].append(dict(path=str(f.relative_to(ROOT)),sha256=sha(f)))
 changed={str(f.relative_to(ROOT)):f for f in [R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md']}
 for bucket in ['sources','conclusions']:
  for item in m[bucket]:
   if item['path'] in changed:
    f=changed[item['path']];item['sha256']=sha(f)
    if 'bytes' in item:item['bytes']=f.stat().st_size
 m['all_pair_nonpodium_switch_improvement_added']=True;m['all_pair_nonpodium_switch_improvement_note']=summary;a=json.loads((O/'source_audit.json').read_text());m['data_end_by_study'][H.name]=dict(primary='2019~2025 overall and annual',recent_complete='2024~2025',partial_2026=a['partial_by_meet'],target_horizon_races=0,selection='all3386 observed historical pairs;213 frozen support family, no prior four selection',comparison='all-starts nonpodium improvement composites and conditional nonpodium performance, observational not causal',followup='50E');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
 p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();mutate(p,old.rstrip()+f'\n| 2026-10-13 | {title} | 집계 중 | <!-- {H.name} -->\n',old)
 (O/'registration.json').write_text(json.dumps(dict(new_independent_study=False,followup='50E',central_document=central.name,independent_table_count_before=count,independent_table_count_after=count,shared_files=5),ensure_ascii=False,indent=2)+'\n');print('Registered follow-up50E, count',count)
if __name__=='__main__':main()
