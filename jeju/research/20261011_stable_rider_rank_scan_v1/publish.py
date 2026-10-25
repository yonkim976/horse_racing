"""Append the all-stable descriptive scan without replacing prior conclusions."""
import copy,json,re,shutil
from analyze import HERE,ROOT,save,sha
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 assert json.loads((HERE/'results01/verification.json').read_text())['status']=='passed'
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics'])
 paths=[c/v for v in ['20_TRAINER_PROFILE.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths}
 for r in old:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 link='../'+HERE.name+'/README.md'
 p=c/'20_TRAINER_PROFILE.md';s=p.read_text();at='## 실제 착순 상승 후속'
 add=f'''## 다른 마방의 착순 상승 사례

[전체 마방 후속 확인]({link})에서도 사례가 있다. 두 기간 각각20교체 이상이면서 원시·10두환산 평균 모두 상승인13지원조합 중6조합에는 기존 두마방 밖의 강영진→김홍권(2024~2025년73건+0.41위,2026년34건+0.65위)과 심도연→임재광(41건+0.15위,20건+0.55위)이 포함된다.2026년 실제 순위상승률은55.9%/45.0%이며 날짜·말95%구간은 모두0을 포함한다. 평균 부호 반복에 따른 사후 기술적 후보이지 확정 효과가 아니다.

한상배→양민재는2026년20건+1.55위이나 이전24건−1.13위,고영덕→문현진은24건+1.42위이나 이전77건−0.14위로 최근 상승에 그친다. 김대연→곽석은27건+0.78위이나 이전6건으로반복판단보류다.2026은09-19부분연도,7~13두 정상완주 완전편성의 같은말·조교사·마주2~90일선택쌍이다. 최근20건이상16조합 중 원시양수13/환산양수11조합이며,하락·보류를 포함한 전체표와3,119행재대조를 저장했다. 직전선택경주와실제직전경주는다를수있다. 원시착순변화의 새조정모형은없고 기존조건부교체미확정·승부의도미확정·운영미채택결론을 유지한다.

'''
 assert at in s;p.write_text(s.replace(at,add+at,1))
 p=c/'README.md';s=p.read_text();line=next(v for v in s.splitlines() if '| [조교사 특성과 말의 수행 개선]' in v);p.write_text(s.replace(line,'| [조교사 특성과 말의 수행 개선](20_TRAINER_PROFILE.md) | 다른 마방에서도 원시 착순 상승 사례, 조건부 반복 우세·승부 의도 미확정 | 전체 마방 착순 후속 저장, 운영 미반영 |'))
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n후속: [다른 마방의 착순 상승 사례]({link}) — 최근20교체 이상16조합 전수,두기간20건13조합 중 원시·환산방향반복6조합. 강영진→김홍권·심도연→임재광 포함,사후 기술통계·인과/승부 미확정.\n')
 t=next(v for v in reg['topics'] if v['id']=='trainer_profile');t['all_stable_rank_scan_followup']={'source':link,'status':'descriptive_all_stable_scan_saved_no_confirmed_effect','both_periods20':13,'raw_and_normalized_positive_both':6,'outside_previous_two_stables_positive_both':2,'operationally_applied':False}
 for v in topics:
  if v['id']!='trainer_profile':assert next(x for x in reg['topics'] if x['id']==v['id'])==v
 reg.update(updated_at='2026-10-11',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)));save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json'])
 save(HERE/'artifact_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'listed_files':len(files),'listed_bytes':sum(p.stat().st_size for p in files),'excludes':'self and final publication receipt'});files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files];assert not {r['path'] for r in rows}&{r['path'] for r in old};m['files']+=rows
 m.update(updated_at='2026-10-11',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)));m['verification'].update(status='passed_all_stable_rank_scan_publication',previous_entries_verified_before_current_publication=len(old),latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),all_previous_nonmanagement_source_entries_unchanged=True)
 m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in m['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed:assert sha(ROOT/r['path'])==r['sha256']
 links=0
 for p in [HERE/'README.md',c/'20_TRAINER_PROFILE.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'prior_unchanged_except_four_management_files':len(old)-4,'other_topic_objects_preserved':len(topics)-1,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'central_entries_verified':len(m['files']),'central_manifest_sha256':sha(mp),'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[mp]},'local_links_verified':links,'jockey_and_style_pause_preserved':True,'database_opened':False,'operationally_applied':False})
 print('All-stable rank scan published and verified:',len(files),'files;',len(m['files']),'central entries')
if __name__=='__main__':main()
