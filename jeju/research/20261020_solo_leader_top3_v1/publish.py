"""Save the solo-leader follow-up without altering the earlier pack comparisons."""
import copy,json,re,shutil
import pandas as pd
from analysis import HERE,ROOT,sha,save
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists();assert json.loads((HERE/'verification01/verification.json').read_text())['status']=='passed'
 export=pd.read_csv(HERE/'경주별_S1F_단독선행.csv');original=pd.read_csv(HERE/'run01/solo_starts.csv');original=original[original.point.eq('s1f')].sort_values('race_id');export=export.sort_values('경주ID');assert len(export)==1761 and export['경주ID'].nunique()==1761
 assert export['경주ID'].tolist()==original.race_id.tolist() and export['최종착순'].tolist()==original.finish_position.tolist() and export['입상'].tolist()==original.top3.tolist()
 for r in json.loads((HERE/'source_manifest.json').read_text())['files']:
  p=(ROOT/r['path']).resolve();assert p.is_relative_to(ROOT/'jeju') and sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics']);d=json.loads((HERE/'decision.json').read_text());link='../'+HERE.name+'/README.md';paths=[c/n for n in ['07_RUNNING_STYLE.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths}
 for p in paths:
  r=next(x for x in old if x['path']==str(p.relative_to(ROOT)));assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]}
 p=c/'07_RUNNING_STYLE.md';head,body=p.read_text().split('\n\n',1)
 add=f'''2026-10-20 최신 [첫 통과조가 한 마리인 단독 선행]({link})에서는 **S1F첫묶음이정확히1두였던1,761경주의입상률62.69%(1,104/1,761), 우승률34.75%(612/1,761)**를확인했다. 아래첫묶음전체48.22%와구분한다. 같은능력말을단독선행시키는인과효과나사전예측확률은아니다.

## 단독 선행 관측 후속

기존S1F품질완전5,200경주·52,095출전(2017-01-13~2026-09-19·정상완주완전편성·현재8거리·400m/제외말제외·2026부분연도)을유지했다. 첫묶음이여러말인경주에서임의의한마리를고르지않고,첫묶음1두인경주만단독관측으로분리했다. 한지점의선두이며거리차·편안함·경합부재·끝까지선행을보장하지않는다.

| S1F 첫 묶음 | 경주 수 | 말 출전 | Top3 | 우승 |
|---|---:|---:|---:|---:|
| 1두 | 1,761 | 1,761 | 62.69% | 34.75% |
| 2두 | 2,148 | 4,296 | 50.56% | 22.25% |
| 3두 이상 | 1,291 | 4,327 | 40.00% | 14.74% |
| 2두 이상 합계 | 3,439 | 8,623 | 45.26% | 18.49% |

모두첫묶음말한번출전당비율이며그룹최소1두입상확률과혼합하지않는다. 단독입상률날짜95%60.42~64.97%,말95%60.07~65.31%다. 전체첫묶음48.22%는1두/2두/3두이상의분자를합친평균이다.

| 거리 | 단독 관측 경주 | 단독말 Top3 | 단독말 우승 |
|---|---:|---:|---:|
| 800m | 412 | 78.64% | 48.30% |
| 900m | 285 | 67.37% | 42.11% |
| 1000m | 483 | 61.49% | 33.54% |
| 1110m | 354 | 49.72% | 22.88% |
| 1200m | 165 | 50.91% | 21.82% |
| 1300m | 20 | 55.00% | 15.00% |
| 1400m | 38 | 47.37% | 23.68% |
| 1610m | 4 | 50.00% | 50.00% |

1300/1400/1610m는소표본이다.2026년전체단독157경주·102입상64.97%·47우승29.94%,비단독첫묶음808말출전은42.45%·15.97%다. 최근거리별1~53경주비율은더불확실하다. 보충4C는별도더늦은단면이며S1F와혼합하지않는다. 1110/1610m S1F210m·1300m2C→S1F계약을유지했다.

[경주별 단독 선행 CSV](../{HERE.name}/경주별_S1F_단독선행.csv)에1,761경주·말ID/마명/마번·최종착순·원문을보존했다. 원문첫토큰/명단10,401경주지점·19,218첫묶음말출전·SQL216셀·54분할합계를독립검산해기존첫묶음전체와일치했다. 능력/전략/게이트/거리및정상완주선택차이가남는관찰통계다. 고정가산·개별미래확률·인과효과·운영반영미채택,DB개방/쓰기·외부수집없음.

## 앞선 실제 통과조 묶음 비교

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text();line=next(v for v in s.splitlines() if '| [통과조 기반 각질과 전개]' in v);s=s.replace(line,'| [통과조 기반 각질과 전개](07_RUNNING_STYLE.md) | S1F첫묶음1두의 입상62.69/우승34.75%, 묶음전체48.22%와 분리 | 단독1,761경주·거리별·최근검산 완료, 인과가산·운영미반영 |');s+=f'\n[첫 통과조가 한 마리인 단독 선행]({link}): S1F1,761경주에서Top3 62.69%·우승34.75%,2026년157경주64.97%·29.94%.2두이상첫묶음말의45.26%·18.49%와분리했다.거리별분모·단독말경주CSV·검산을보존,편안한전개/원인효과/고정가산미확정.\n';p.write_text(s)
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n2026-10-20 단독선행 후속: [첫 묶음 크기1/2/3두이상과입상·우승]({link}) — 기존첫묶음10,384말출전중단독1,761경주·입상1,104·우승612. 거리·기간·보충4C·원문첫토큰/SQL검산과단독경주목록을보존. 단독실제관측은사전각질이나경합부재의확정이아님.\n')
 topic=next(t for t in reg['topics'] if t['id']=='running_style');previous=topic.get('latest_source');topic.update(status=d['status'],latest_source=link,previous_actual_pack_source=previous);topic['solo_leader_top3_followup']={**d,'source':link}
 for t in topics:
  if t['id']!='running_style':assert next(x for x in reg['topics'] if x['id']==t['id'])==t
 reg.update(updated_at='2026-10-20',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']);save(HERE/'artifact_manifest.json',{'status':d['status'],'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'excludes':'self and final publication receipt'});files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files];assert not {r['path'] for r in rows}&{r['path'] for r in old};m['files']+=rows;m.update(updated_at='2026-10-20',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);m['verification'].update(status='passed_solo_leader_publication_scoped',scope='new study and four central management files; unrelated source entries retained without revalidation',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),all_previous_research_output_files_unchanged=None,all_previous_nonmanagement_source_entries_unchanged=None,prior_external_sources_revalidated=False,prior_source_metadata_preserved_except_four_management_files=True,solo_leader_management_paths_changed=sorted(changed));m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
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
 save(receipt,{'status':'passed','verification_scope':'new solo-leader study and four management files','new_study_files_verified':len(rows),'new_study_bytes':sum(r['bytes'] for r in rows),'solo_race_export_rows_verified':len(export),'old_source_metadata_retained_except_four_management':len(old)-4,'unrelated_historical_sources_revalidated':False,'other_topic_objects_preserved':len(topics)-1,'central_manifest_entries':len(m['files']),'central_manifest_sha256':sha(mp),'previous_management_hashes':before,'local_links_verified':links,'database_opened':False,'operationally_applied':False});print('Solo leader study saved and indexed',len(rows),'files',flush=True)
if __name__=='__main__':main()
