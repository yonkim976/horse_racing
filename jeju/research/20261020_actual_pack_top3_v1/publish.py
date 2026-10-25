"""Index observed-position results separately from past-style results."""
import copy,json,re,shutil
from analysis import HERE,ROOT,sha,save
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for name in ['verification01/verification.json','verification01/export_verification.json']:assert json.loads((HERE/name).read_text())['status']=='passed'
 for r in json.loads((HERE/'source_manifest.json').read_text())['files']:
  p=(ROOT/r['path']).resolve();assert p.is_relative_to(ROOT/'jeju') and sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics']);d=json.loads((HERE/'decision.json').read_text());link='../'+HERE.name+'/README.md'
 paths=[c/n for n in ['07_RUNNING_STYLE.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths}
 for p in paths:
  r=next(x for x in old if x['path']==str(p.relative_to(ROOT)));assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]}
 p=c/'07_RUNNING_STYLE.md';head,body=p.read_text().split('\n\n',1)
 add=f'''2026-10-20 사용자 정정에 따른 최신 비교는 [실제 통과조 세 그룹별 입상률]({link})이다. **과거 각질이 아니라 해당 경주의 실제 S1F 첫 묶음/두 번째 묶음/세 번째 이후를 비교하면 출전당 Top3는48.22/35.64/21.30%다.** 앞선 사전 각질34.65/32.46/32.63%와는 분모·질문이 다르다.

## 해당 경주의 실제 초반 위치와 입상

2017-01-13~2026-09-19 정상완주 완전편성 원천5,206경주·52,155출전에서S1F불명확6경주·60출전을경주전체로제외해5,200경주·52,095출전을비교했다. 현재8거리·400m/제외말제외·2026부분연도다. 묶음안순서를개별착순으로만들지않으며첫묶음은여러말일수있다. 두번째를전통선입/레일2선으로,뒤쪽을추입형/추입성공으로자동확정하지않는다.

| 실제 S1F 위치 | Top3/그룹출전 | 출전당 Top3 | 전체입상마중 구성비 |
|---|---:|---:|---:|
| 첫 묶음 선두 | 5,007/10,384 | 48.22% | 32.10% |
| 두 번째 묶음 | 4,246/11,913 | 35.64% | 27.22% |
| 세 번째 이후 뒤쪽 | 6,347/29,798 | 21.30% | 40.69% |

뒤쪽은평균약5.7두,선두는약2두라입상마전체구성비는뒤쪽이많아도개별말의입상률은낮다. 최소1두입상한경주비율도선두75.12/두번째66.52/뒤쪽81.11%로다르며그룹존재경주가분모이고중복사건이다.

| 거리 | 유효경주 | 선두 | 두번째 | 뒤쪽 |
|---|---:|---:|---:|---:|
| 800m | 1,258 | 61.10% | 40.29% | 16.46% |
| 900m | 888 | 50.61% | 36.61% | 19.74% |
| 1000m | 1,421 | 44.92% | 33.84% | 22.25% |
| 1110m | 988 | 39.56% | 35.05% | 24.15% |
| 1200m | 485 | 41.85% | 29.64% | 26.02% |
| 1300m | 63 | 40.46% | 33.61% | 26.91% |
| 1400m | 88 | 34.38% | 36.21% | 28.68% |
| 1610m | 9 | 43.75% | 36.84% | 26.53% |

800m는선두원시입상률이특히높다.1400m는두번째가조금높고1610m는9경주·그룹별16/19/49출전으로일반화보류다.2026년488경주·4,673출전전체는46.11/37.35/23.39%이며최근800m3경주·1300m20·1400m14·1610m6경주는소표본이다.1110/1610m S1F는210m,1300m는사용자순서2C→S1F를유지한다.

보충4C는5,201경주·52,107출전에서54.30/41.04/20.26%다. 측정단면·분모가달라S1F에서이동시키는효과가아니다. **[경주별 초반3그룹 CSV](../{HERE.name}/경주별_초반3그룹.csv)**는5,200경주한줄씩원문·거리·그룹두수/입상수/우승수/비율을제공한다. 원연구의말별그룹·경주별묶음상세·제외원장도보존했다.

독립상태기계파서로10,401원문·104,202말별배치·31,203경주그룹행,SQL162비율셀·54분모행을검산했다. 경주별입상3두·우승1두·입상마구성비합계100%와5,200행수출표62,400값을확인했다. 실제위치에조건부인후향관측이며말의능력·전략·정상완주선택이남는다. 사전예측확률/선행전환인과효과·고정가산·운영반영아님. DB개방/쓰기·외부수집없음.

## 앞선 과거 각질별 비교

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text();line=next(v for v in s.splitlines() if '| [통과조 기반 각질과 전개]' in v);s=s.replace(line,'| [통과조 기반 각질과 전개](07_RUNNING_STYLE.md) | 실제초반 첫/둘째/뒤 묶음 Top3 48.22/35.64/21.30%, 사전각질과 분리 | 5,200경주 실제위치·경주별 표 검산 완료, 운영미반영 |');s+=f'\n[해당 경주의 실제 통과조와 입상]({link}): S1F첫/둘째/셋째이후로5,200경주·52,095출전을분류, 출전당48.22/35.64/21.30%. 거리별·2026·4C·입상마구성비와경주별5,200행을저장했다. 과거각질과다르고뒤쪽이추입성공을뜻하지않으며사전확률/인과가산미채택.\n';p.write_text(s)
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n2026-10-20 실제위치 정정 후속: [통과조 첫 묶음·두번째·그뒤의 입상]({link}) — S1F5,200경주·52,095출전·불명확6경주제외. 전체48.22/35.64/21.30%, 거리·최근·4C및경주별CSV. 독립파서/SQL/경주별회계검산완료, 실제초반위치에조건부인관측과사전각질확률을분리.\n')
 topic=next(t for t in reg['topics'] if t['id']=='running_style');previous=topic.get('latest_source');topic.update(status=d['status'],latest_source=link,previous_past_style_top3_source=previous);topic['actual_pack_top3_followup']={**d,'source':link}
 for t in topics:
  if t['id']!='running_style':assert next(x for x in reg['topics'] if x['id']==t['id'])==t
 reg.update(updated_at='2026-10-20',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json'])
 save(HERE/'artifact_manifest.json',{'status':d['status'],'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'excludes':'self and final publication receipt'});files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files];assert not {r['path'] for r in rows}&{r['path'] for r in old};m['files']+=rows
 m.update(updated_at='2026-10-20',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status'])
 m['verification'].update(status='passed_actual_pack_top3_publication_scoped',scope='new study and four central management files; unrelated source entries retained without revalidation',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),all_previous_research_output_files_unchanged=None,all_previous_nonmanagement_source_entries_unchanged=None,prior_external_sources_revalidated=False,prior_source_metadata_preserved_except_four_management_files=True,actual_pack_management_paths_changed=sorted(changed));m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in rows:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 for r in old:
  current=next(x for x in m['files'] if x['path']==r['path'])
  if r['path'] not in changed:assert current==r
 for p in paths:
  r=next(x for x in m['files'] if x['path']==str(p.relative_to(ROOT)));assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 links=0
 for p in [HERE/'README.md',c/'07_RUNNING_STYLE.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','verification_scope':'new actual-position study and four central management files','new_study_files_verified':len(rows),'new_study_bytes':sum(r['bytes'] for r in rows),'old_source_metadata_retained_except_four_management':len(old)-4,'unrelated_historical_sources_revalidated':False,'other_topic_objects_preserved':len(topics)-1,'central_manifest_entries':len(m['files']),'central_manifest_sha256':sha(mp),'previous_management_hashes':before,'local_links_verified':links,'past_style_comparison_retained_separately':True,'database_opened':False,'operationally_applied':False});print('Actual pack study saved and indexed',len(rows),'files',flush=True)
if __name__=='__main__':main()
