"""Publish the limited jockey-training follow-up without reopening other topics."""
import copy,json,re,shutil
from data import HERE,ROOT,DB,sha,save
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for name in ['verification02/verification.json','report_verification01/verification.json']:
  assert json.loads((HERE/name).read_text())['status']=='passed'
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';audit=json.loads((HERE/'prepublication_audit01.json').read_text());assert sha(mp)==audit['central_manifest_sha256'];m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics']);d=json.loads((HERE/'decision.json').read_text())
 paths=[c/v for v in ['06_TRAINING_RECORD.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths};external={r['path']:r for r in audit['drift']};assert set(external)=={'jeju/data/jeju_native_core.sqlite3','jeju/review_documents/README.md'}
 extraction=json.loads((HERE/'input01/source_manifest.json').read_text());assert sha(DB)==extraction['database_sha256_after']==external['jeju/data/jeju_native_core.sqlite3']['observed']['sha256'];assert DB.stat().st_size==extraction['database_bytes']
 refreshpath=ROOT/'jeju/research/20261017_core_refresh/manual_applied/application_manifest_final.json';refresh=json.loads(refreshpath.read_text());assert refresh['status']=='applied_verified' and refresh['database_sha256_after']==sha(DB) and refresh['backup_pair']['source_database_sha256']==external['jeju/data/jeju_native_core.sqlite3']['registered']['sha256']
 ep=ROOT/'jeju/review_documents/README.md';previous=ROOT/'jeju/research/20261016_layoff_return_v1/publication_snapshot/external_review_documents_README.md';assert sha(previous)==external['jeju/review_documents/README.md']['registered']['sha256'];oldparts=previous.read_text().split('\n\n');newparts=ep.read_text().split('\n\n');assert oldparts[:1]+oldparts[2:]==newparts[:1]+newparts[2:];assert '20261017_training_rider_unclassified' in newparts[1]
 for r in old:
  p=ROOT/r['path'];expected=external[r['path']]['observed'] if r['path'] in external else r;assert sha(p)==expected['sha256'] and p.stat().st_size==expected['bytes'],r['path']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 shutil.copyfile(ep,snap/'external_review_documents_README.md');shutil.copyfile(previous,snap/'external_review_documents_previous.md')
 save(HERE/'source_update_context.json',{'preexisting_external_drift':audit['drift'],'external_current_paths_content_changed_by_this_study':False,'refresh_application_manifest':{'path':str(refreshpath.relative_to(ROOT)),'sha256':sha(refreshpath)},'external_review_only_first_paragraph_changed':True,'previous_dated_research_outputs_unchanged':True})
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]};link='../'+HERE.name+'/README.md';p=c/'06_TRAINING_RECORD.md';s=p.read_text();head,body=s.split('\n\n',1)
 add=f'''최신 [기수의 직접 조교 참여와 경주 성적]({link})에서는 **기수 참여 자체 및 이번 경주 기수의 직접 참여에 안정적인 조정 우세를 확인하지 못했다.** 기수 전체 연구의 추후 재개 상태는 유지하고 조교 참여에 관한 제한된 후속 결과만 추가했다.

## 기수 조교 참여 후속

기존2017-01-13~2026-09-19 정상완주완전편성52,155출전·5,206경주·2,813두에서 현재8거리·원천7~13두를 유지했다.400m/제외말 결과는 미편입이며2026은부분연도다. 최신 종류 조회의 조교641,228원행을 말ID로 연결했다. 주창은경주일−14~−2일이며 직전 실제 출전일 이후다. 원문 종류와 같은 사건 확인만 따르고 미분류·주로조교·후보생을 기수로 추정하지 않았다. 이번기수 여부는 공식 사번과 현재 경주 기수ID의 정확 일치다.

전체34,490출전의 종류 완전확인 창에서 기수참여21,414/다른종류만13,076을 비교했다. 기수참여 안에서는 이번기수18,492/다른기수만2,922다.2024~2025는전체4,730/기수3,552/다른종류1,178,이번기수3,268/다른기수284다.2026은종류완전확인1,766/기수1,217/다른종류549,이번기수1,140/다른기수77이다.2026전체4,673중미분류창2,907은 미참여로 채우지 않았다. 이번기수 비교의2026음성77건은최소100출전미달로조정결과를보류했다.

| 기간 | 다른 종류만 Top3 | 다른 기수만 Top3 | 이번 경주 기수 참여 Top3 |
|---|---:|---:|---:|
| 전체 | 31.16%〔13,076출전〕 | 24.81%〔2,922〕 | 30.07%〔18,492〕 |
| 2024~2025 | 34.47%〔1,178〕 | 24.65%〔284〕 | 30.45%〔3,268〕 |
| 2026 | 32.97%〔549〕 | 16.88%〔77〕 | 28.51%〔1,140〕 |

경주와말×정확거리효과,과거수행·직전성적·간격·부담·체중·게이트·기수/조교사·조교량을고려했다. 전체기수참여대다른종류만의조정기록은−0.008초(빠름양수,날짜95%−0.048~+0.033·말−0.054~+0.039),Top3+0.15%p(날짜−1.33~+1.62)다. 이번기수대다른기수만은+0.039초(날짜−0.042~+0.121·말−0.046~+0.125),Top3+0.54%p(날짜−2.52~+3.60)로불확실하다. 원시이번기수입상차이+5.26%p를직접조교효과로해석하지않는다.

2024~2025기수참여기록+0.153초와2026−0.176초는방향이다르고날짜구간은각각−0.116~+0.422/−0.666~+0.314초다. 이번기수의2024~2025−0.046초도−0.520~+0.427로불확실하다. 계획18주검정중지원15개와별도H1지원3개를BH보정했고방향지원0개·최근반복0개다.7/28일·조교량제외·확인된양성창확대민감도의기록구간도0을포함했다. 고정직접조교가점·새예측추가개선·운영반영은채택하지않았다.

156,465창·1,033,484원행ID연결·50미래교란·78목표계수와공분산·112기술통계셀/1,093구간을독립재계산했다. 종류완전확인의선택,미분류,건강/승부선택·훈련강도·과거게시시각미관측이남으며인과효과·효과없음의증명은아니다. DB는읽기전용이고추출전후SHA가같다. 별도10월17일DB갱신보고서의파일크기메타데이터한항목불일치와이번직접해시검사는원연구에구분해보존했다. 이전연구·기수전체/각질추후재개상태·운영모델은유지했다.

## 앞선 조교량 연구

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text().replace('2026년 10월 16일 기준.','2026년 10월 17일 기준.',1);line=next(v for v in s.splitlines() if '| [조교와 기록 향상]' in v);s=s.replace(line,'| [조교와 기록 향상](06_TRAINING_RECORD.md) | 조교량·기수 직접참여의 안정적 조정 우세 미확인, 미분류와 최근 소표본 구분 | 조교 참여 후속·독립 검산 완료, 운영 미반영 |');s+=f'\n[기수의 직접 조교 참여]({link}): 종류 완전확인34,490출전에서 기수 참여 자체와 이번 경주 기수 직접참여를 구분. 전체 원시이번기수Top3차이+5.26%p는 조정+0.54%p(95%−2.52~+3.60)로 불확실. 최근 반복0개·2026다른기수77건 보류·고정가점 미채택.\n';p.write_text(s)
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n조교 참여 후속: [기수 직접 조교 참여와 실제 성적]({link}) — 2017~2026-09-19,주창D−14~D−2·직전출전이후,종류완전확인34,490출전. 기수참여와이번경주기수참여의별도비교,주지원15/H1지원3검정에서안정우세미확인.미분류제외·2026음성77건보류·원시/조정·원천메타데이터차이를보존. 고정가점·운영미반영.\n')
 topic=next(v for v in reg['topics'] if v['id']=='training_record');prior=copy.deepcopy(topic);identity={k:topic[k] for k in ['id','title','conclusion']};topic.clear();topic.update(identity,**d,latest_source=link,previous_quantity_source=prior['latest_source'],previous_quantity_study=prior);topic['jockey_training_followup']={**d,'source':link,'all_same_jockey_adjusted_top3_pp':0.539756,'all_any_jockey_adjusted_top3_pp':0.145017,'unknown_type_is_not_absence':True}
 for v in topics:
  if v['id']!='training_record':assert next(x for x in reg['topics'] if x['id']==v['id'])==v
 reg.update(updated_at='2026-10-17',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']);save(HERE/'artifact_manifest.json',{'status':'completed_verified_jockey_training_observational_research','files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'listed_files':len(files),'listed_bytes':sum(p.stat().st_size for p in files),'excludes':'self and final publication receipt'});files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed or r['path'] in external:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files];assert not {r['path'] for r in rows}&{r['path'] for r in old};m['files']+=rows;m.update(updated_at='2026-10-17',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);m['verification'].update(status='passed_jockey_training_publication',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),all_previous_research_output_files_unchanged=True,all_previous_nonmanagement_source_entries_unchanged=False,jockey_training_management_paths_changed=sorted(changed),jockey_training_preexisting_external_drift=audit['drift'],jockey_training_external_current_paths_content_changed=False);m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in m['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed and r['path'] not in external:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 for path,r in external.items():assert sha(ROOT/path)==r['observed']['sha256'] and (ROOT/path).stat().st_size==r['observed']['bytes']
 links=0
 for p in [HERE/'README.md',HERE/'PUBLICATION_PROVENANCE.md',c/'06_TRAINING_RECORD.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'prior_entries_unchanged_except_four_management_updates_and_two_external_metadata_refreshes':len(old)-6,'all_previous_research_output_files_unchanged':True,'preexisting_external_drift':audit['drift'],'external_current_paths_content_changed_by_this_study':False,'other_topic_objects_preserved':len(topics)-1,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'central_entries_verified':len(m['files']),'central_manifest_sha256':sha(mp),'prepublication_management_hashes':before,'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[mp]},'local_links_verified':links,'database_written':False,'operationally_applied':False,'jockey_and_style_revisit_later_preserved':True});print('Jockey training study published and verified',len(files),'files',len(m['files']),'central entries',flush=True)
if __name__=='__main__':main()
