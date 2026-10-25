"""Register the feasibility stage without implying estimated rider ability."""
import json,re
from audit import HERE,ROOT,sha,save

def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 assert json.loads((HERE/'audit01/verification.json').read_text())['status']=='passed'
 central=ROOT/'jeju/research/conclusions';mp=central/'source_manifest.json';manifest=json.loads(mp.read_text());frozen=[r for r in manifest['files'] if r['role']!='conclusion_or_management']
 for r in frozen:assert sha(ROOT/r['path'])==r['sha256'],r['path']
 link='../'+HERE.name+'/README.md';decision=json.loads((HERE/'decision.json').read_text())
 newcentral=central/'08_JOCKEY_PROFILE.md';assert not newcentral.exists()
 newcentral.write_text(f'''# 기수 특성과 좋은말 배정 및 추가 기여

최신 단계는 [기수 연구 자료 지원과 설계]({link})다.2017~2026-09-19 정상완주 전체경주52,155출전·5,206경주에서 공식기수ID40명이 결측 없이 연결된다. 같은말·거리의 직전 같은거리 관측과2~60일인31,320쌍 중 기수변경13,533쌍,2026년은974쌍이다. 부담차1kg·함수율차3%p 이내 기수변경은 전체3,572쌍·2026년242쌍이다. 비교쌍은 무작위 교체나 동일컨디션을 뜻하지 않는다.

연구는 좋은말 배정→말의 사전기대를 고려한 기수 추가기록/입상 기여→같은말 교체 비교→전개·거리·각질별 특성 및 말×기수 호흡→후기기간 재현성 순으로 진행할 수 있다. 원시 승률·입상률과 조합성적을 기수 능력으로 바로 바꾸지 않는다. 기록오차(초)와 입상확률(%p)을 목적별로 구분한다.

이번 결과는 자료지원 감사와 설계다. 기수별 능력·특성 효과·순위는 아직 산출하지 않았다. 공식ID 연결·교체쌍·기수별 출전수·전체 연결망을 보존했다. 기수 배정의 선택성·관측하지 못한 컨디션·교체 이유 때문에 순수 능력의 정확한 식별을 보장할 수 없다. 영상 없이 주행경로·추진·승부 의도를 확정하지 않는다.2026년은 부분연도,운영모델 변경 없음.

앞선 [각질·편성 연구](07_RUNNING_STYLE.md)는 사용자 지시에 따라 현재 결론으로 정리해 두고 추후 재개한다.
''')
 p=central/'07_RUNNING_STYLE.md';text=p.read_text();head,body=text.split('\n\n',1);marker='2026-10-09 사용자 지정: 각질·편성 연구는 현재 결론과 자료를 보존하고 추후 다시 진행한다. 다음 검토 주제는 [기수 연구](08_JOCKEY_PROFILE.md)다.\n\n';p.write_text(head+'\n\n'+marker+body)
 p=central/'README.md';text=p.read_text();assert '08_JOCKEY_PROFILE.md' not in text
 row='| [기수 특성과 좋은말 배정](08_JOCKEY_PROFILE.md) | 기수40명·52,155출전 연결,같은말거리60일 내 기수변경13,533쌍.배정·추가기여·전개·호흡 연구 설계 | 자료지원 감사 완료,기수 효과·랭킹 미추정 |\n'
 text=text.replace('| [원 연구와 버전 목록]',row+'| [원 연구와 버전 목록]',1);p.write_text(text)
 p=central/'SOURCES.md';text=p.read_text();assert link not in text
 text=text.replace('같은 출전 자료가 여러 버전에 중복되므로',f'새 주제: [{HERE.name}]({link}) — 기수 공식ID·출전지원·같은말거리 기수변경쌍·연결망 감사와 배정/추가기여/전개/호흡 연구설계.효과·랭킹 미산출.\n\n같은 출전 자료가 여러 버전에 중복되므로',1);p.write_text(text)
 p=central/'research_register.json';reg=json.loads(p.read_text());reg['updated_at']='2026-10-09'
 for topic in reg['topics']:
  if topic['id']=='running_style':topic['user_work_phase']='current_findings_saved_revisit_later_2026_10_09'
 assert not any(t['id']=='jockey_profile' for t in reg['topics'])
 reg['topics'].append({'id':'jockey_profile','title':'기수 특성·좋은말 배정·추가 기여와 말기수 호흡','conclusion':'08_JOCKEY_PROFILE.md','latest_source':link,**decision});save(p,reg)
 files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']]
 entries=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
 save(HERE/'artifact_manifest.json',{'status':'feasibility_completed_no_effect_estimation','files':entries,'listed_files':len(entries),'listed_bytes':sum(r['bytes'] for r in entries),'excludes':'self and final publication receipt'})
 files.append(HERE/'artifact_manifest.json')
 for r in manifest['files']:
  if r['role']=='conclusion_or_management':
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 new=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
 new.append({'path':str(newcentral.relative_to(ROOT)),'role':'conclusion_or_management','sha256':sha(newcentral),'bytes':newcentral.stat().st_size})
 assert not {r['path'] for r in manifest['files']}&{r['path'] for r in new};manifest['files']+=new
 manifest['verification'].update(status='passed',all_previous_source_hashes_unchanged=True,latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)))
 manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in manifest['files']);save(mp,manifest)
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 links=0
 for p in [HERE/'README.md',newcentral,central/'07_RUNNING_STYLE.md',central/'README.md',central/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),target;links+=1
 save(receipt,{'status':'passed','prior_immutable_files_verified':len(frozen),'new_source_files':len(files),'new_source_bytes':sum(p.stat().st_size for p in files),
  'central_manifest_entries_verified':len(manifest['files']),'central_manifest_sha256':sha(mp),'local_links_verified':links,
  'management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in [newcentral,central/'07_RUNNING_STYLE.md',central/'README.md',central/'SOURCES.md',central/'research_register.json',mp]},'effect_estimation_completed':False,'no_database_or_operational_model_changes':True})
 print('Publication passed',len(files),sum(p.stat().st_size for p in files),flush=True)
if __name__=='__main__':main()
