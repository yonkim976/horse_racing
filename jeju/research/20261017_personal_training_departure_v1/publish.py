"""Publish personal departures, retaining prior studies and documented external changes."""
import copy,json,re,shutil,hashlib
from data import HERE,ROOT,sha,save

def path(relative):
 p=(ROOT/relative).resolve()
 # The central manifest also pins one operational registry as a read-only guard.
 assert p.is_relative_to(ROOT/'jeju') or p==ROOT/'config/prediction_model_registry.json'
 return p

def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for name in ['verification01/verification.json','report01/verification.json']:
  assert json.loads((HERE/name).read_text())['status']=='passed'
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json'
 audit=json.loads((HERE/'prepublication_audit01.json').read_text())
 assert sha(mp)==audit['central_manifest_sha256']
 m=json.loads(mp.read_text());old=copy.deepcopy(m['files'])
 drift={r['path']:r for r in audit['drift']}
 external={'jeju/AGENTS.md','jeju/data/jeju_native_core.sqlite3','jeju/review_documents/README.md'}
 assert set(drift)==external
 completion=ROOT/'jeju/research/20261017_training_rider_website_completion'
 ap=completion/'application_manifest.json';np=completion/'verification/native_postapply_verification.json'
 app=json.loads(ap.read_text());native=json.loads(np.read_text())
 db=drift['jeju/data/jeju_native_core.sqlite3']
 assert app['status']=='applied' and app['updated_rows']==19885
 assert app['database_sha256_before']==db['registered']['sha256']
 assert app['database_sha256_after']==db['actual']['sha256']=='57593fe7156a78aa1e5f358fa97bfc9151c9be57779ffac46a8d29fba92e01d9'
 assert app['database_bytes_after']==db['actual']['bytes']
 assert not app['raw_training_rows_changed'] and not app['schema_changed']
 assert set(app['changed_columns'])=={'rider_type','type_status','website_type','website_label_raw','website_jockey_name','website_source_path','website_sha256'}
 assert native['passed'] and native['database_sha256']==db['actual']['sha256'] and native['schema_unchanged']
 assert native['assignment_changed_rows']==19885 and native['unexpected_assignment_changes']==0
 assert native['unchanged_source_snapshot_fields'] and native['old_and_new_plan_snapshots_exact']
 for table in ['daily_training_api_rows','api_records']:assert native['tables'][table]['changed_or_missing_rows']==0
 # Recover previous text exactly; do not edit the current external documents.
 agents=path('jeju/AGENTS.md').read_text();lines=agents.split('\n')
 removed=[v for v in lines if v.startswith('- 2026-10-17 사용자 승인으로 최근 6개월 미분류')];assert len(removed)==1
 old_agents='\n'.join(v for v in lines if v not in removed)
 review=path('jeju/review_documents/README.md').read_text();paragraphs=review.split('\n\n')
 assert paragraphs[1].startswith('최신 실제 반영은 **[2026-10-17 조교 기승자 홈페이지 보완')
 old_review='\n\n'.join(paragraphs[:1]+paragraphs[2:])
 for relative,text in [('jeju/AGENTS.md',old_agents),('jeju/review_documents/README.md',old_review)]:
  assert hashlib.sha256(text.encode()).hexdigest()==drift[relative]['registered']['sha256']
  assert len(text.encode())==drift[relative]['registered']['bytes']
 for r in old:
  p=path(r['path']);expected=drift[r['path']]['actual'] if r['path'] in external else r
  assert sha(p)==expected['sha256'] and p.stat().st_size==expected['bytes'],r['path']
 reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics'])
 d=json.loads((HERE/'decision.json').read_text())
 paths=[c/v for v in ['06_TRAINING_RECORD.md','README.md','SOURCES.md','research_register.json']]
 changed={str(p.relative_to(ROOT)) for p in paths};assert len(changed)==4
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 (snap/'AGENTS_current.md').write_text(agents);(snap/'AGENTS_registered_reconstructed.md').write_text(old_agents)
 (snap/'review_README_current.md').write_text(review);(snap/'review_README_registered_reconstructed.md').write_text(old_review)
 shutil.copyfile(ap,snap/'external_application_manifest.json');shutil.copyfile(np,snap/'external_native_postapply_verification.json')
 save(HERE/'source_update_context.json',{'status':'documented_external_type_only_change','external_drift':audit['drift'],'external_evidence':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in [ap,np]],'previous_texts_reconstructed_exactly':True,'frozen_input_hashes_unchanged':True,'type_filter_used_in_this_study':False,'training_dates_amounts_unchanged_in_external_verification':True,'database_opened_or_modified_by_this_study':False,'previous_manifest_sha256':sha(mp)})
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]}
 link='../'+HERE.name+'/README.md';p=c/'06_TRAINING_RECORD.md';s=p.read_text();head,body=s.split('\n\n',1)
 body=body.replace('최신 [본인 조교 일수·최근성·시간과 전체 조교량]','앞선 [본인 조교 일수·최근성·시간과 전체 조교량]',1)
 add=f'''최신 [말별 평소 조교량 증감과 성적]({link})에서는 **평소보다 일수·시간이 늘거나 줄었을 때의 안정적인 조정 성적 차이를 확인하지 못했다.** 원시 성적은 감소 그룹이 좋았지만 출전 간격·평소량 등도 달랐다. 주54검정/H1 최근12검정의 방향 지원과 최근 반복은 0개다.

## 말별 평소 조교량의 증감 후속

2017-01-13~2026-09-19 원천52,155출전·5,206경주·2,813두(현재8거리·정상완주완전편성·원천7~13두·2026부분연도), 조교641,228행을 사용했다. 실제 출전65,269행으로 준비 이력을 연결하고 결과선정 밖 실제 출전 준비도 평소에 포함했다. 현재 D−14~D−2·직전실제출전 다음날 이후와, T−2까지 완료한 최근730일 최대5회(최소3회)의 중앙값을 비교했다. 현재 준비·성적과 미래는 평소에서 제외했다. 무원행·시간미제공은0으로 채우지 않았다.

일수±2일 이상, 누적 시간±25% 이상을 감소/증가로 분류하고 관측일당 시간도 따로 봤다. 전체45,021출전·2,279두(첫유효2017-02-03), 2024~2025년11,280출전·2026년4,116출전이다. 원천 중 현재 미관측134와 평소이력 부족7,000을 분리했다. 경주효과·말×정확거리×기수짝, 과거수행·직전성적·간격·부담·체중·게이트·조교사·평소량·준비가능날짜를 고려했다. 일수/누적시간 증감은 같은 모형의 조건부 비교다.

| 전체 기간 평소 범위 대비 | 원시 Top3 | 조정 빠름 초 (날짜95%) | 조정 Top3 %p (날짜95%) |
|---|---:|---:|---:|
| 일수 감소 | 31.40% | −0.005 (−0.075~+0.065) | +1.56 (−1.25~+4.36) |
| 일수 증가 | 25.75% | +0.002 (−0.062~+0.066) | +0.81 (−1.76~+3.38) |
| 누적 시간 감소 | 30.21% | −0.041 (−0.105~+0.024) | −2.42 (−5.11~+0.28) |
| 누적 시간 증가 | 25.11% | −0.041 (−0.104~+0.022) | −0.78 (−3.29~+1.73) |

원시 평소범위 Top3는 일수28.90%, 누적시간29.73%다. 일수감소/증가 그룹 평균 출전간격24.14/49.57일로, 감소를 성적개선 처방으로 해석하지 않는다. 양수초는 편성대비 빠름이며 말군집 구간도0포함이다. 관측일당 시간±25%도 안정적 조정 우세는 없었다. 2026 원시 일수감소/평소/증가 Top3 35.88/30.55/26.48%이나 최근 조정·반복 지원은0개다.

7/28일·최근10회(최소5)·가능일당비율·현재절대량추가·짝효과변경·90일이하·단독모형을 보존했다. 90일이하 민감도의 누적시간감소 Top3 −3.03%p(날짜−5.98~−0.08)는 양쪽군집 음수였으나 주BH/최근반복을 충족한 결론이 아니며 고정감점으로 쓰지 않는다. 주54/H1 12검정은 날짜BH와 날짜/말구간 조건으로 지원0개다.

말별 최신 프로필은2,813두×3창이며 2026관측·14일창 이력지원849두의 평소중앙값은7.5일·102분이다. 이는2026-09-19까지 완료한 준비의 요약이며 경주별T−2기준·개인최적량과 다르다. 실제하루횟수/강도/속도/거리는 미제공이고 고정가산·컨디션판정·예측증분·운영반영은 하지 않았다.

SQL출전순서65,269·준비창170,142·평소기준312,930·프로필8,439·교란30·효과/공분산456개를 검산했다. 고정CSV 해시·바이트는 유지됐다. 별도 승인 기승자종류 보완으로 현재DB 해시는 바뀌었지만 조교 원행 날짜·기간은 그대로이고 이 연구는 종류선별을 쓰지 않았다. 외부변경3항목과 중앙해시 갱신근거는 원연구에 보존하며 DB를 개방·수정하지 않았다. 과거반복/정상완주·관측선택/미관측건강·강도·게시시각의 한계와 기수·각질 추후재개 상태는 유지한다.

## 앞선 절대 조교량과 최근성 연구

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text();line=next(v for v in s.splitlines() if '| [조교와 기록 향상]' in v)
 s=s.replace(line,'| [조교와 기록 향상](06_TRAINING_RECORD.md) | 개인 평소량 대비 증감·본인참여·전체량의 안정적 조정 우세 미확인 | 개인증감45,021출전 검산 완료, 고정가산·운영미반영 |')
 s+=f'\n[말별 평소 조교량 증감]({link}): T−2 과거5회(최소3)·730일 중앙값 대비 일수±2/시간±25%. 45,021출전·2,279두, 능력·편성·간격 등 고려 후 주54/H1 12검정 지원0개·최근반복0개. 원시 감소그룹 우세를 처방으로 쓰지 않으며 말별 평소 프로필을 보존했다.\n';p.write_text(s)
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n개인 조교량 증감 후속: [말별 평소 일수·누적시간·관측일당시간과 성적]({link}) — 과거 실제출전 준비, 현재/미래제외 T−2 최근730일 최대5회·최소3회. 전체45,021/2024~2025년11,280/2026년4,116출전. 54주검정·12H1 지원/최근반복0개, 170,142준비창·312,930기준·456효과 검산. 외부 종류보완의 해시변경은 분리 보존, 개인최적량/고정가산/운영미채택.\n')
 topic=next(v for v in reg['topics'] if v['id']=='training_record');previous=topic['latest_source']
 topic.update(d,latest_source=link,previous_absolute_training_source=previous)
 topic['personal_training_departure_followup']={**d,'source':link}
 for v in topics:
  if v['id']!='training_record':assert next(x for x in reg['topics'] if x['id']==v['id'])==v
 reg.update(updated_at='2026-10-17',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json'])
 save(HERE/'artifact_manifest.json',{'status':d['status'],'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'listed_files':len(files),'listed_bytes':sum(p.stat().st_size for p in files),'excludes':'self and final publication receipt'})
 files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed|external:
   p=path(r['path']);r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files]
 assert not {r['path'] for r in rows}&{r['path'] for r in old}
 m['files']+=rows;m.update(updated_at='2026-10-17',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status'])
 m['verification'].update(status='passed_personal_training_departure_publication',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),all_previous_research_output_files_unchanged=True,all_previous_nonmanagement_source_entries_unchanged=False,personal_training_departure_management_paths_changed=sorted(changed),documented_external_metadata_refresh_paths=sorted(external),external_change_evidence=str((HERE/'source_update_context.json').relative_to(ROOT)))
 m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in m['files']:
  p=path(r['path']);assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed|external:assert sha(path(r['path']))==r['sha256'] and path(r['path']).stat().st_size==r['bytes']
 for relative,r in drift.items():assert sha(path(relative))==r['actual']['sha256'] and path(relative).stat().st_size==r['actual']['bytes']
 links=0
 for p in [HERE/'README.md',HERE/'PUBLICATION_PROVENANCE.md',c/'06_TRAINING_RECORD.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'previous_entries_unchanged_except_four_management_and_three_external':len(old)-7,'other_topic_objects_preserved':len(topics)-1,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'central_entries_verified':len(m['files']),'central_manifest_sha256':sha(mp),'prepublication_management_hashes':before,'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[mp]},'documented_external_changes':audit['drift'],'external_files_not_modified_by_this_study':True,'local_links_verified':links,'database_opened':False,'operationally_applied':False,'jockey_and_style_revisit_later_preserved':True})
 print('Personal training departure published and verified',len(files),'files',len(m['files']),'entries',flush=True)
if __name__=='__main__':main()
