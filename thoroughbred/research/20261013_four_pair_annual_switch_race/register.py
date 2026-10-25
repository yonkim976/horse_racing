"""Append follow-up50D and refresh all shared manifest occurrences, preserving old research."""
from pathlib import Path
import json,re,hashlib
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={r['path']:r for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']};before={};owned={}
def mutate(p,new,expected):
 old=p.read_text();assert old==expected,'Concurrent edit; reread';name=str(p.relative_to(ROOT));before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);owned[name]=dict(path=name,own_delta_bytes=len(new.encode())-len(old.encode()),own_final_bytes=len(new.encode()));assert p.read_text()==old;p.write_text(new)
 (O/'shared_edits_baseline.json').write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');(O/'shared_own_edits.json').write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(owned.values())),ensure_ascii=False,indent=2)+'\n')
def main():
 central=R/'conclusions/50D_FOUR_PAIR_ANNUAL_SWITCH_RACE.md';assert not central.exists();pub=(H/'PUBLICATION.md').read_text();pub=re.sub(r'\]\((README.md|SOURCES.md|outputs/[^)]+|figures/[^)]+)\)',lambda z:f'](../{H.name}/{z.group(1)})',pub);central.write_text(pub+f'\n\n研究50/50A/50B/50C 후속50D,독립 연구 수 유지. [원 보고서](../{H.name}/README.md) · [용량](../{H.name}/outputs/artifact_inventory.json).\n'.replace('研究','연구'))
 title='네 마방 기수 조합의 연도별 변경 당일 성적';mark='<!-- four_pair_annual_switch_race_20261013 -->';summary='50C의입상개별개선4후보를2019~2025연도별/두기간과2026부분으로분리. 변경된그한경주240건만평가. 배대선→이동하2019~20집중,김동균→조한별2024순위/기록탐색신호이나변경7회·2025~26표본없음. 강환민/민장기최근입상보정방향양수이나과거와차이불확실,2026변경2/12회. 원래213조합BH미통과·사후선택·표본부족유지,운영유지.'
 p=R/'conclusions/README.md';old=p.read_text();assert mark not in old;count=max(map(int,re.findall(r'^\| (\d+) \|',old,re.M)));mutate(p,old.rstrip()+f'\n\n[{title}]({central.name}): {summary} [원본](../{H.name}/README.md). 연구50D 후속,독립수 유지. '+mark+'\n',old)
 p=R/'README.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n[{title}]({H.name}/README.md): {summary} [중앙](conclusions/{central.name}). '+mark+'\n',old)
 p=R/'conclusions/SOURCES.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n## {title}\n\n[원본](../{H.name}/README.md) · [중앙]({central.name}) · [출처·해시](../{H.name}/SOURCES.md) · [독립검증](../{H.name}/outputs/verification.json) · [게시 요약](../{H.name}/PUBLICATION.md) · [용량](../{H.name}/outputs/artifact_inventory.json). 50A의159,014분류 불변참조,79,551완결기간배경/8,674부분기간배경. 네후보조합의연도별/두기간/기간차/2026부분 대조,3모형×3결과전체희소LSQR/입상전구간·보조BH구간/전수SQL집계·고정BH/변경이벤트240건목표0경주 확인. 기존자료/DB/운영 변경없음. '+mark+'\n',old)
 p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
 for bucket,files in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central])]:
  for f in files:m[bucket].append(dict(path=str(f.relative_to(ROOT)),sha256=sha(f)))
 changed={str(f.relative_to(ROOT)):f for f in [R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md']}
 for bucket in ['sources','conclusions']:
  for item in m[bucket]:
   if item['path'] in changed:
    f=changed[item['path']];item['sha256']=sha(f)
    if 'bytes' in item:item['bytes']=f.stat().st_size
 m['four_pair_annual_switch_race_added']=True;m['four_pair_annual_switch_race_note']=summary;a=json.loads((O/'source_audit.json').read_text());m['data_end_by_study'][H.name]=dict(primary='2019~2025 annual and eras',recent_complete='2024~2025',partial_2026=a['partial_by_meet'],target_horizon_races=0,selection='four positive nominal candidates from original213; exploratory followup, not prediction test',followup='50D');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
 p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();mutate(p,old.rstrip()+f'\n| 2026-10-13 | {title} | 집계 중 | <!-- {H.name} -->\n',old)
 (O/'registration.json').write_text(json.dumps(dict(new_independent_study=False,followup='50D',central_document=central.name,independent_table_count_before=count,independent_table_count_after=count,shared_files=5),ensure_ascii=False,indent=2)+'\n');print('Registered follow-up50D, count',count)
if __name__=='__main__':main()
