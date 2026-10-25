"""Append follow-up50C and refresh all shared manifest occurrences, preserving old research."""
from pathlib import Path
import json,re,hashlib
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={r['path']:r for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']};before={};owned={}
def mutate(p,new,expected):
 old=p.read_text();assert old==expected,'Concurrent edit; reread';name=str(p.relative_to(ROOT));before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);owned[name]=dict(path=name,own_delta_bytes=len(new.encode())-len(old.encode()),own_final_bytes=len(new.encode()));assert p.read_text()==old;p.write_text(new)
 (O/'shared_edits_baseline.json').write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');(O/'shared_own_edits.json').write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(owned.values())),ensure_ascii=False,indent=2)+'\n')
def main():
 central=R/'conclusions/50C_HISTORICAL_PLANNED_PAIR_SWITCH_RACE.md';assert not central.exists();pub=(H/'PUBLICATION.md').read_text();pub=re.sub(r'\]\((README.md|SOURCES.md|outputs/[^)]+|figures/[^)]+)\)',lambda z:f'](../{H.name}/{z.group(1)})',pub);central.write_text(pub+f'\n\n研究50/50A/50B 후속50C,독립 연구 수 유지. [원 보고서](../{H.name}/README.md) · [용량](../{H.name}/outputs/artifact_inventory.json).\n'.replace('研究','연구'))
 title='과거 기간을 확대한 마방별 기수변경 당일 성적';mark='<!-- historical_planned_pair_switch_race_20261012 -->';summary='2019~2025년 79,551출전 중 계획변경40,272건의 변경된 그 한 경주만 평가. 비교지원213조합(기존20),기존부족17중13복구. 능력·직전성적·기수수준·평소조합 통제 후 입상 개별개선4조합이나 주기간 입상/순위/시간 다중비교 개선0. 최근 재추정의 유의조합은 비교지원 부족,인과/예측효과 미확정,운영 유지.'
 p=R/'conclusions/README.md';old=p.read_text();assert mark not in old;count=max(map(int,re.findall(r'^\| (\d+) \|',old,re.M)));mutate(p,old.rstrip()+f'\n\n[{title}]({central.name}): {summary} [원본](../{H.name}/README.md). 연구50C 후속,독립수 유지. '+mark+'\n',old)
 p=R/'README.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n[{title}]({H.name}/README.md): {summary} [중앙](conclusions/{central.name}). '+mark+'\n',old)
 p=R/'conclusions/SOURCES.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n## {title}\n\n[원본](../{H.name}/README.md) · [중앙]({central.name}) · [출처·해시](../{H.name}/SOURCES.md) · [독립검증](../{H.name}/outputs/verification.json) · [게시 요약](../{H.name}/PUBLICATION.md) · [용량](../{H.name}/outputs/artifact_inventory.json). 50A의159,014분류 불변참조,79,551주표본/106,332확장. 교체/유지 충분213조합의 두대조 공동추정,주기간·최근기간 전체희소LSQR/사전지정군집구간/전수SQL집계·BH/변경이벤트목표0경주 확인. 기존자료/DB/운영 변경없음. '+mark+'\n',old)
 p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
 for bucket,files in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central])]:
  for f in files:m[bucket].append(dict(path=str(f.relative_to(ROOT)),sha256=sha(f)))
 changed={str(f.relative_to(ROOT)):f for f in [R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md']}
 for bucket in ['sources','conclusions']:
  for item in m[bucket]:
   if item['path'] in changed:
    f=changed[item['path']];item['sha256']=sha(f)
    if 'bytes' in item:item['bytes']=f.stat().st_size
 m['historical_planned_pair_switch_race_added']=True;m['historical_planned_pair_switch_race_note']=summary;a=json.loads((O/'source_audit.json').read_text());m['data_end_by_study'][H.name]=dict(primary='2019~2025',historical_reference='2018',excluded_partial_year='2026',target_horizon_races=0,confirmation='2024~2025 overlapping recent period, historical pair list frozen; reestimated effects, not prediction test',followup='50C');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
 p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();mutate(p,old.rstrip()+f'\n| 2026-10-12 | {title} | 집계 중 | <!-- {H.name} -->\n',old)
 (O/'registration.json').write_text(json.dumps(dict(new_independent_study=False,followup='50C',central_document=central.name,independent_table_count_before=count,independent_table_count_after=count,shared_files=5),ensure_ascii=False,indent=2)+'\n');print('Registered follow-up50C, count',count)
if __name__=='__main__':main()
