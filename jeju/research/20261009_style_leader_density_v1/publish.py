"""Publish completed research into the established local conclusion collection."""
import json,re
from features import HERE,ROOT,sha,save

def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for file in ['verification01/verification.json','verification_extra01/verification.json']:assert json.loads((HERE/file).read_text())['status']=='passed'
 central=ROOT/'jeju/research/conclusions';mp=central/'source_manifest.json';manifest=json.loads(mp.read_text());frozen=[r for r in manifest['files'] if r['role']!='conclusion_or_management']
 for r in frozen:assert sha(ROOT/r['path'])==r['sha256'],r['path']
 link='../'+HERE.name+'/README.md';decision=json.loads((HERE/'decision.json').read_text())
 p=central/'07_RUNNING_STYLE.md';text=p.read_text();head,body=text.split('\n\n',1);assert link not in text
 intro=f'''최신 각질 편성 후속은 [선입·추입형과 사전 선행형 수]({link})다. 과거 T−2 이력으로 선입형과 중후방+4C→G1F 확실2두전진 반복 추입 후보를 구분했다. 같은거리 선입형의 현재 첫/둘째/셋째이후 Top3는38.3%(292/762)·26.4%(190/721)·16.5%(131/792), 추입 후보는 셋째이후32.5%(38/117)이며 첫·둘째는3·6회뿐이다.

편성 비교는 거리통합 각질판정률80% 이상3,599경주다. 선행형0/1/2/3두이상별 선입형 입상률33.2/31.4/34.8/36.2%, 엄격 추입 후보38.7/28.8/32.6/21.4%다. 선입형 조정1두당+0.55%p(날짜95%−0.98~+2.08), 추입 후보−3.59%p(−12.05~+4.87)로 일반적인 절대입상률 증가를 확인하지 못했다. 추입 후보는185출전이고 최근 추정은 최소표본 미달이다. 완화40% 전진후보860출전도 안정적 이점 미확인이다.

같은경주의 선행형 대비 선입형 상대우세는2026년에 탐색신호가 있지만 전체/2024~25년 반복 지지가 부족하다. 사후추가탐색으로 구분하며2026년 선행형3두이상 동시비교16경주의 작은지지범위를 보존했다. 선행형3두이상 중 실제 첫집단에 과거선행형2두이상 동시진입은46.2%로 숫자가 곧 경합·빠른페이스는 아니다. 각질 보너스·인과효과·운영 반영 없음.

'''
 p.write_text(head+'\n\n'+intro+body)
 p=central/'README.md';text=p.read_text();old=next(x for x in text.splitlines() if '| [통과조 기반 각질과 전개]' in x)
 new='| [통과조 기반 각질과 전개](07_RUNNING_STYLE.md) | 선행형35.1/비첫24.5%. 선행형 다수편성의 다른각질 절대입상 증가 미확인,2026 선입 상대우세 탐색신호 | 관찰·탐색 연구,추입 소표본,운영 미반영 |';p.write_text(text.replace(old,new))
 p=central/'SOURCES.md';text=p.read_text();assert link not in text
 text=text.replace('같은 출전 자료가 여러 버전에 중복되므로',f'새 후속: [{HERE.name}]({link}) — 선입·추입 후보 실제위치별 입상과 선행형 편성수.3,599경주에서 일반적인 절대입상률 증가 미확인.2026 선입 상대우세는 사후탐색 신호로 별도 보존.추입 반복기준40%·동일거리·판정률100% 민감도,21개설명모형·104,310이력창 재계산.\n\n같은 출전 자료가 여러 버전에 중복되므로',1);p.write_text(text)
 p=central/'research_register.json';reg=json.loads(p.read_text());reg['updated_at']='2026-10-09'
 for topic in reg['topics']:
  if topic['id']=='running_style':
   topic['previous_style_performance_source']=topic['latest_source'];topic['latest_source']=link
   topic['leader_density_style_followup']={'source':link,**decision};topic['status']='style_conditional_performance_and_leader_density_completed_observational_exploratory_no_operational_change'
 save(p,reg)
 files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']]
 entries=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
 save(HERE/'artifact_manifest.json',{'status':'completed','files':entries,'listed_files':len(entries),'listed_bytes':sum(r['bytes'] for r in entries),'excludes':'self and final publication receipt'})
 files.append(HERE/'artifact_manifest.json')
 for r in manifest['files']:
  if r['role']=='conclusion_or_management':
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 new=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
 assert not {r['path'] for r in manifest['files']}&{r['path'] for r in new};manifest['files']+=new
 manifest['verification'].update(status='passed',all_previous_source_hashes_unchanged=True,latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)))
 manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in manifest['files']);save(mp,manifest)
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 links=0
 for p in [HERE/'README.md',central/'07_RUNNING_STYLE.md',central/'README.md',central/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),target;links+=1
 save(receipt,{'status':'passed','prior_immutable_files_verified':len(frozen),'new_study_files_in_central_manifest':len(new),'new_study_bytes':sum(r['bytes'] for r in new),
  'central_manifest_entries_verified':len(manifest['files']),'central_manifest_sha256':sha(mp),'local_links_verified':links,
  'management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in [central/'07_RUNNING_STYLE.md',central/'README.md',central/'SOURCES.md',central/'research_register.json',mp]},'no_database_or_operational_model_changes':True})
 print('Publication passed',len(new),sum(r['bytes'] for r in new),flush=True)
if __name__=='__main__':main()
