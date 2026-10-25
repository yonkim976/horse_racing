"""Publish a descriptive supplement; preserve all prior research and topic states."""
import copy,json,re,shutil
from analyze import HERE,ROOT,save,sha
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 assert json.loads((HERE/'results01/verification.json').read_text())['status']=='passed'
 central=ROOT/'jeju/research/conclusions';mp=central/'source_manifest.json'
 m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((central/'research_register.json').read_text());oldtopics=copy.deepcopy(reg['topics'])
 paths=[central/v for v in ['20_TRAINER_PROFILE.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths}
 for r in old:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 link='../'+HERE.name+'/README.md'
 p=central/'20_TRAINER_PROFILE.md';s=p.read_text();at='## 마방별 기수 교체 후속'
 follow=f'''## 실제 착순 상승 후속

[같은 사례의 착순 변화]({link})는 원시 입상률과 별도로 실제 착순 상승을 확인했다. 이준호→박성광은 2024~2025년 57건 평균 5.04→3.14위(+1.89위), 2026년 23건 5.17→3.96위(+1.22위)였다. 이태용→박성광은 99건 +0.78위 / 41건 +0.73위, 이준호→문현진은 84건 +0.46위 / 21건 +0.95위였다. 2026년 실제 순위 상승 비율은 각각 12/23(52.2%), 19/41(46.3%), 12/21(57.1%)다. 하락·동일도 평균의 분모에 포함한다.

2026년 10두 환산 평균 상승도 +1.27/+0.71/+0.95위로 방향이 유지된다. 상대마 능력 보정은 아니다. 원시 평균 상승의 날짜95% 구간은 각각 −0.51~+2.94 / −0.49~+1.95 / −0.70~+2.60위이며 말 군집 구간도 모두 0을 포함한다. 2026년은09-19까지 부분연도다. 같은 말·조교사·마주 및2~90일의 선택출전쌍 기술통계이며 실제 모든출전의 직전경주와 다를 수 있다. 원천 정상완주 완전편성은7~13두다. 모든기간·마방×기수×교체/유지 전체표와 정의·소표본·구간·검증을 저장했다. 조정된 교체 효과나 승부 의도 확정은 아니며 아래 조건부 비교·운영 미채택 결론을 유지한다.

'''
 assert at in s;p.write_text(s.replace(at,follow+at,1))
 p=central/'README.md';s=p.read_text();line=next(v for v in s.splitlines() if '| [조교사 특성과 말의 수행 개선]' in v);p.write_text(s.replace(line,'| [조교사 특성과 말의 수행 개선](20_TRAINER_PROFILE.md) | 특정기수 교체의 원시 입상률·평균 착순 상승 관측, 조정 후 반복 우세 미확정 | 착순 후속 저장, 고정 가산점·운영 미반영 |'))
 p=central/'SOURCES.md';p.write_text(p.read_text()+f'\n후속: [마방별 교체 뒤 실제 착순 변화]({link}) — 기존43,024선택쌍의 실제·10두환산 착순 변화, 모든조합/기간/교체여부 및 설명용6사례. 원시기술통계, 인과·승부의도 미확정.\n')
 topic=next(v for v in reg['topics'] if v['id']=='trainer_profile')
 topic['rank_change_followup']={'source':link,'status':'descriptive_rank_changes_saved_no_causal_or_intent_claim','period_end':'2026-09-19','partial_2026':True,'operationally_applied':False}
 for v in oldtopics:
  if v['id']!='trainer_profile':assert next(x for x in reg['topics'] if x['id']==v['id'])==v
 reg.update(updated_at='2026-10-11',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)));save(central/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json'])
 save(HERE/'artifact_manifest.json',{'status':'completed_verified_descriptive_research','files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'listed_files':len(files),'listed_bytes':sum(p.stat().st_size for p in files),'excludes':'self and final publication receipt'})
 files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files]
 assert not {r['path'] for r in old}&{r['path'] for r in rows};m['files']+=rows
 m.update(updated_at='2026-10-11',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)))
 m['verification'].update(status='passed_descriptive_rank_followup_publication',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),previous_entries_verified_before_current_publication=len(old),all_previous_nonmanagement_source_entries_unchanged=True)
 m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in m['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed:assert sha(ROOT/r['path'])==r['sha256']
 links=0
 for p in [HERE/'README.md',central/'20_TRAINER_PROFILE.md',central/'README.md',central/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'prior_unchanged_except_four_management_files':len(old)-4,'other_topic_objects_preserved':len(oldtopics)-1,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'central_entries_verified':len(m['files']),'central_manifest_sha256':sha(mp),'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[mp]},'local_links_verified':links,'database_opened':False,'operationally_applied':False,'jockey_and_style_pause_preserved':True})
 print('Rank follow-up publication verified:',len(files),'new files;',len(m['files']),'central entries')
if __name__=='__main__':main()
