"""Append the exact-size distance tables and workbook to the research indexes."""
import copy,json,re,shutil
from analysis import HERE,ROOT,sha,save
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for f in ['verification01/verification.json','outputs/20261020-leader-pack-size/workbook_verification.json','outputs/20261020-leader-pack-size/saved_workbook_verification.json','outputs/20261020-leader-pack-size/visual_review.json']:
  assert json.loads((HERE/f).read_text())['status']=='passed'
 for r in json.loads((HERE/'source_manifest.json').read_text())['files']:
  p=(ROOT/r['path']).resolve();assert p.is_relative_to(ROOT/'jeju') and sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics']);d=json.loads((HERE/'decision.json').read_text());link='../'+HERE.name+'/README.md';paths=[c/n for n in ['07_RUNNING_STYLE.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths}
 for p in paths:
  r=next(x for x in old if x['path']==str(p.relative_to(ROOT)));assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]};table=['| 선두 두수 | 경주 | 말 입상률 | 말 우승률 | 그룹 우승 | 정확1두 입상 | 2두이상 입상 |','|---|---:|---:|---:|---:|---:|---:|']
 for r in d['overall_rates']:table.append('| '+str(r['leader_count'])+' | '+f"{r['races']:,}"+' | '+' | '.join(f"{r[k]:.2f}%" for k in ['individual_top3_pct','individual_win_pct','group_win_pct','one_top3_pct','two_plus_top3_pct'])+' |')
 summary='\n'.join(table);p=c/'07_RUNNING_STYLE.md';head,body=p.read_text().split('\n\n',1)
 add=f'''2026-10-20 최신 [선두 묶음 두수와 거리별 입상·우승·동반입상]({link})에서는 **정확한1~7두×8거리의말기준입상/우승과그룹기준정확1두/2두이상입상을분리했다.** 전체선두2두2,148경주의정확1두입상56.15%·2두모두입상22.49%·전부비입상21.37%다.

## 선두 두수별 동반 입상 후속

기존S1F품질완전5,200경주·첫묶음10,384말출전(2017-01-13~2026-09-19·정상완주완전편성·현재8거리·400m/제외말제외·2026부분연도)을유지했다. 첫묶음크기를정확히나눠3두와3두이상을혼합하지않았다. 묶음내개별순위·경합강도는복원하지않는다.

{summary}

말입상/우승의분모는말출전수이고나머지그룹비율은해당조건경주수다. 그룹우승=말우승률×선두두수다.0두/정확1두/2두이상입상비율은배타적이며합계100%이고2두이상은정확2+정확3두다.2두첫묶음의1,206경주정확1두·483경주모두입상으로입상말합계는2,172두다.3두선두는정확2두306경주·정확3두40경주다.

800m선두2두의둘다입상34.75%,900m24.46%,1000m19.41%,1110m12.99%,1200m15.15%다. 전체기간거리별관측44조합과무표본12조합,전체/2024~2025/2026의189셀을보존했다.선두6두10경주·7두1경주는극소표본이며많은거리별5두이상도지원이작다.

[전체 거리별 엑셀](../{HERE.name}/{d['workbook']})은기간·거리·정확두수필터와말기준두율·그룹0/정확1/정확2/정확3/2이상/최소1두·그룹우승을제공한다. 원수치분자/분모를참조한1,701비율수식을재계산·복원·저장캐시·두시트시각검증으로확인했다. 원연구에5,200경주별첫묶음N/K/W와전체CSV·44조합요약을저장했다.

독립말별재집계와메모리SQL189셀·27분할합계·확률합100%·우승분모관계를검산했다. 실제위치·정상완주선택에조건부인기술통계이며능력/전략/거리/두수차이를제거한효과가아니다.사전예측/인과가산·운영반영없음,DB개방/쓰기·외부수집없음. S1F200m/1110·1610m210m및1300m2C→S1F계약을유지했다.

## 앞선 단독 선행 비교

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text();line=next(v for v in s.splitlines() if '| [통과조 기반 각질과 전개]' in v);s=s.replace(line,'| [통과조 기반 각질과 전개](07_RUNNING_STYLE.md) | 선두 정확1~7두·거리별 말입상/우승과 그룹1두/2두이상 입상 분리 | 189셀·엑셀 수식/저장 검산 완료, 운영미반영 |');s+=f'\n[선두 두수와 거리별 동반 입상]({link}): 정확1~7두·8거리.2두선두는정확1두56.15%,둘다22.49%,전부비입상21.37%.말출전/경주분모를분리하고관측44거리조합·무표본·최근분할을엑셀과원장으로보존했다.\n';p.write_text(s)
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n2026-10-20 정확선두두수 후속: [거리별입상·우승·그룹정확입상수]({link}) — S1F5,200경주·10,384첫묶음말출전.1~7두×전체및8거리×3기간189셀.정확0/1/2/3입상·2이상·그룹우승분모를분리,독립SQL/원수치분할과엑셀1,701수식·캐시·시각검증완료.\n')
 topic=next(t for t in reg['topics'] if t['id']=='running_style');previous=topic.get('latest_source');topic.update(status=d['status'],latest_source=link,previous_solo_leader_source=previous);topic['exact_leader_pack_size_outcomes_followup']={**d,'source':link}
 for t in topics:
  if t['id']!='running_style':assert next(x for x in reg['topics'] if x['id']==t['id'])==t
 reg.update(updated_at='2026-10-20',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and not {'__pycache__','node_modules'}.intersection(p.parts) and p.name not in ['artifact_manifest.json','publication_verification.json']);save(HERE/'artifact_manifest.json',{'status':d['status'],'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'excludes':'self, final publication receipt, runtime symlink and Python caches'});files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files];assert not {r['path'] for r in rows}&{r['path'] for r in old};m['files']+=rows;m.update(updated_at='2026-10-20',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);m['verification'].update(status='passed_leader_pack_size_outcomes_publication_scoped',scope='new study and four management files; unrelated historical sources retained without revalidation',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),all_previous_research_output_files_unchanged=None,all_previous_nonmanagement_source_entries_unchanged=None,prior_external_sources_revalidated=False,prior_source_metadata_preserved_except_four_management_files=True,leader_pack_size_management_paths_changed=sorted(changed));m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in rows:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 for r in old:
  if r['path'] not in changed:assert next(x for x in m['files'] if x['path']==r['path'])==r
 for p in paths:
  r=next(x for x in m['files'] if x['path']==str(p.relative_to(ROOT)));assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 links=0
 for p in [HERE/'README.md',c/'07_RUNNING_STYLE.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','verification_scope':'new pack-size study, workbook and four management files','new_study_files_verified':len(rows),'new_study_bytes':sum(r['bytes'] for r in rows),'old_source_metadata_retained_except_four_management':len(old)-4,'unrelated_historical_sources_revalidated':False,'other_topic_objects_preserved':len(topics)-1,'central_manifest_entries':len(m['files']),'central_manifest_sha256':sha(mp),'previous_management_hashes':before,'local_links_verified':links,'workbook_path':str((HERE/d['workbook']).relative_to(ROOT)),'database_opened':False,'operationally_applied':False});print('Exact leader-pack-size study saved and indexed',len(rows),'files',flush=True)
if __name__=='__main__':main()
