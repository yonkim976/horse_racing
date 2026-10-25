"""Append follow-up50B and refresh all shared manifest occurrences, preserving old research."""
from pathlib import Path
import json,re,hashlib
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={r['path']:r for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']};before={};owned={}
def mutate(p,new,expected):
 old=p.read_text();assert old==expected,'Concurrent edit; reread';name=str(p.relative_to(ROOT));before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);owned[name]=dict(path=name,own_delta_bytes=len(new.encode())-len(old.encode()),own_final_bytes=len(new.encode()));assert p.read_text()==old;p.write_text(new)
 (O/'shared_edits_baseline.json').write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');(O/'shared_own_edits.json').write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(owned.values())),ensure_ascii=False,indent=2)+'\n')
def main():
 central=R/'conclusions/50B_PLANNED_TRAINER_JOCKEY_PAIR_EFFECTS.md';assert not central.exists();pub=(H/'PUBLICATION.md').read_text();pub=re.sub(r'\]\((README.md|SOURCES.md|outputs/[^)]+|figures/[^)]+)\)',lambda z:f'](../{H.name}/{z.group(1)})',pub);central.write_text(pub+f'\n\n研究50/50A 후속50B,독립 연구 수 유지. [원 보고서](../{H.name}/README.md) · [용량](../{H.name}/outputs/artifact_inventory.json).\n'.replace('研究','연구'))
 title='특정 마방→기수 계획교체의 조건부 성적 차이';mark='<!-- planned_trainer_jockey_pair_effects_20261012 -->';summary='상위분류 미사용,계획교체지원37조합 중 유지비교지원20조합. 같은말/경주·과거상태·기수연도별수준·평소조합 통제 후 입상률20구간 모두0포함,순위/시간 포함 BH통과0. 동일마주/직전계획/연간지원해제·2026부분 재추정도 확정개선 없음. 효과0/승부의지 입증 아님,운영 유지.'
 p=R/'conclusions/README.md';old=p.read_text();assert mark not in old;count=max(map(int,re.findall(r'^\| (\d+) \|',old,re.M)));mutate(p,old.rstrip()+f'\n\n[{title}]({central.name}): {summary} [원본](../{H.name}/README.md). 연구50B 후속,독립수 유지. '+mark+'\n',old)
 p=R/'README.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n[{title}]({H.name}/README.md): {summary} [중앙](conclusions/{central.name}). '+mark+'\n',old)
 p=R/'conclusions/SOURCES.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n## {title}\n\n[원본](../{H.name}/README.md) · [중앙]({central.name}) · [출처·해시](../{H.name}/SOURCES.md) · [독립검증](../{H.name}/outputs/verification.json) · [게시 요약](../{H.name}/PUBLICATION.md) · [용량](../{H.name}/outputs/artifact_inventory.json). 50A의159,014분류 불변참조,25,535주표본/32,252확장. 교체/유지 충분20조합의 두대조 공동추정,주기간·2026전체희소LSQR/주20×2입상군집구간/전수SQL집계·BH 확인. 기존자료/DB/운영 변경없음. '+mark+'\n',old)
 p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
 for bucket,files in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central])]:
  for f in files:m[bucket].append(dict(path=str(f.relative_to(ROOT)),sha256=sha(f)))
 changed={str(f.relative_to(ROOT)):f for f in [R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md']}
 for bucket in ['sources','conclusions']:
  for item in m[bucket]:
   if item['path'] in changed:
    f=changed[item['path']];item['sha256']=sha(f)
    if 'bytes' in item:item['bytes']=f.stat().st_size
 m['planned_trainer_jockey_pair_effects_added']=True;m['planned_trainer_jockey_pair_effects_note']=summary;a=json.loads((O/'source_audit.json').read_text());m['data_end_by_study'][H.name]=dict(actual_results=a['data_end_by_meet'],card_end=a['card_end'],primary='2024~2025',confirmation='2026 partial, frozen pair list; reestimated effects, not prediction test',followup='50B');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
 p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();mutate(p,old.rstrip()+f'\n| 2026-10-12 | {title} | 집계 중 | <!-- {H.name} -->\n',old)
 (O/'registration.json').write_text(json.dumps(dict(new_independent_study=False,followup='50B',central_document=central.name,independent_table_count_before=count,independent_table_count_after=count,shared_files=5),ensure_ascii=False,indent=2)+'\n');print('Registered follow-up50B, count',count)
if __name__=='__main__':main()
