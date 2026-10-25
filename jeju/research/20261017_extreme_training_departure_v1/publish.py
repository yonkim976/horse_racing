"""Publish verified extreme departures and reconcile exactly documented external drift."""
import copy,json,re,shutil,hashlib
from data import HERE,ROOT,PREVIOUS,sha,save
def guarded(relative):
 p=(ROOT/relative).resolve()
 assert p.is_relative_to(ROOT/'jeju') or p==ROOT/'config/prediction_model_registry.json'
 return p
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for name in ['verification01/verification.json','verification01/held_identifiability.json','report01/verification.json']:
  assert json.loads((HERE/name).read_text())['status']=='passed'
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';audit=json.loads((HERE/'prepublication_audit01.json').read_text())
 assert sha(mp)==audit['central_manifest_sha256']
 m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);drift={r['path']:r for r in audit['drift']}
 external={'jeju/AGENTS.md','jeju/data/jeju_native_core.sqlite3','jeju/review_documents/README.md'};assert set(drift)==external
 completion=ROOT/'jeju/research/20261017_older_training_rider_completion'
 ap=completion/'initial609.application_manifest.json';np=completion/'verification/initial609_preservation.json';app=json.loads(ap.read_text());native=json.loads(np.read_text());db=drift['jeju/data/jeju_native_core.sqlite3']
 assert app['status']=='applied' and app['phase']=='initial609' and app['updated_rows']==609
 assert app['database_sha256_before']==db['registered']['sha256']=='57593fe7156a78aa1e5f358fa97bfc9151c9be57779ffac46a8d29fba92e01d9'
 assert app['database_sha256_after']==db['actual']['sha256']=='f3700e12c8dcf0b791d497cca1e7b219e32778a3bba322ed5fe9a9b4a201defa'
 assert not app['schema_changed'] and native['passed'] and native['schema_unchanged'] and native['database_sha256']==db['actual']['sha256']
 assert native['changed_assignment_rows']==609 and native['unexpected_changes']==0 and native['all_planned_old_new_values_exact']
 assert native['tables_checked']==41 and native['rows_checked']==2783599 and native['tables']['daily_training_api_rows']['rows']==912913
 assert {'training_date','duration_seconds','raw_row_json'}<=set(native['tables']['daily_training_api_rows']['columns_checked'])
 # Verify that both documents contain only the known inserted guidance.
 agents=guarded('jeju/AGENTS.md').read_text();newlines=[s for s in agents.splitlines() if s.startswith('- 2026-10-17 과거 미분류 609행')];assert len(newlines)==1
 old_agents=agents.replace('\n'+newlines[0]+'\n','',1)
 review=guarded('jeju/review_documents/README.md').read_text();paras=review.split('\n\n')
 assert paras[1].startswith('최신 실제 반영과 후속 대조 상태는 **[2026-10-17 과거 일별조교 기승자 보완')
 assert paras[2].startswith('과거 미분류의 후속 원천 조사는 **[2026-10-17 과거 일별조교 공식 보완 원천')
 old_review='\n\n'.join(paras[:1]+paras[3:])
 for relative,text in [('jeju/AGENTS.md',old_agents),('jeju/review_documents/README.md',old_review)]:
  assert hashlib.sha256(text.encode()).hexdigest()==drift[relative]['registered']['sha256']
  assert len(text.encode())==drift[relative]['registered']['bytes']
 for r in old:
  p=guarded(r['path']);expected=drift[r['path']]['actual'] if r['path'] in external else r
  assert sha(p)==expected['sha256'] and p.stat().st_size==expected['bytes'],r['path']
 paths=[c/s for s in ['06_TRAINING_RECORD.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths};assert len(changed)==4
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 for name,text in [('AGENTS_current.md',agents),('AGENTS_registered_reconstructed.md',old_agents),('review_README_current.md',review),('review_README_registered_reconstructed.md',old_review)]: (snap/name).write_text(text)
 shutil.copyfile(ap,snap/'external_initial609_application_manifest.json');shutil.copyfile(np,snap/'external_initial609_preservation.json')
 save(HERE/'source_update_context.json',{'status':'documented_external_type_only_609_change','external_drift':audit['drift'],'external_evidence':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in [ap,np]],'previous_texts_reconstructed_exactly':True,'frozen_inputs_unchanged':True,'type_filter_used':False,'raw_dates_durations_preserved_by_external_verification':True,'database_opened_or_modified_by_this_study':False,'previous_central_manifest_sha256':sha(mp)})
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]};link='../'+HERE.name+'/README.md';d=json.loads((HERE/'decision.json').read_text())
 p=c/'06_TRAINING_RECORD.md';head,body=p.read_text().split('\n\n',1);body=body.replace('최신 [말별 평소 조교량 증감과 성적]','앞선 [말별 평소 조교량 증감과 성적]',1)
 add=f'''최신 [말별 평소 조교량의 큰 증감]({link})에서는 **일수±4일·시간±50% 이상의 안정적 조정 차이는 미확인이나, 일수 큰 감소의 일부 민감도에서 기록 악화 신호가 관측됐다.** 큰 변화도 효과가 없다고 확정하지 않는다. 주72/중간변화대비36/H1최근16/보충57검정의 BH 방향지원과 최근반복은0개다.

## 말별 조교량의 큰 변화 후속

앞선 고정입력의45,021출전·2,279두(원천2017-01-13~2026-09-19, 첫유효2017-02-03·2026부분연도)를 사용했다. 현재8거리·정상완주완전편성·원천7~13두·400m/제외말결과미편입·무원행과시간미제공은0미조교로채우지않는기준을 유지했다. 현재D−14~D−2·직전실제출전다음날이후, T−2까지완료한최근730일최대5회/최소3회중앙값의비교다. 현재와미래준비·성적은평소에서제외했다.

일수는±4일이상, 시간은평소의0.5배이하/1.5배이상으로정의하고 중간변화도별도범주로함께넣었다. 같은경주·말×정확거리×기수짝 효과, 과거수행·직전성적·출전간격·부담·체중·게이트·조교사·평소량·준비가능날짜를고려했다. 일수/시간동시모형의조건부차이며 양수초는편성대비빠름이다.

| 전체기간 평소범위 대비 | 출전 | 원시Top3 | 조정 빠름 초 (날짜95%) |
|---|---:|---:|---:|
| 일수4일이상감소 | 2,591 | 31.30% | −0.105 (−0.233~+0.024) |
| 일수4일이상증가 | 2,579 | 23.65% | −0.020 (−0.131~+0.091) |
| 누적시간50%이상감소 | 3,148 | 30.94% | −0.046 (−0.170~+0.079) |
| 누적시간50%이상증가 | 5,330 | 23.38% | −0.016 (−0.108~+0.075) |

평소범위 원시Top3는일수28.90%/시간29.73%다. 일수크게감소/증가그룹의출전간격17.29/53.60일·가능날짜8.56/12.99일로다르며 원시감소우세를처방으로쓰지않는다. 주기록·착순·입상률의날짜/말구간은0포함이고 최근2기간지원반복0개다. 2026큰감소/증가일수168/146출전·시간117/362출전이며 조정구간이더넓다.

일수단독모형의큰감소는−0.130초(−0.247~−0.012), 가능일당비율의큰감소는−0.213초(−0.379~−0.047)로양쪽군집에서느림방향이었다. 말거리효과+기수주효과에서도큰감소기록−0.148초와착순악화가있었고큰증가착순도약하게음수였다. 이5효과는개별민감도의점별구간이며사전주BH·최근반복지원이아니어서고정감점은미채택이다.

초극단±6일/시간75%이상감소·2배이상증가는전체400/170/709/1,258출전으로안정적조정지원미확인이다. 2026은각8/0/1/61출전이며초극단모형도11범주항중독립변화10개로식별보류다. 일수/시간모두큰감소1,814출전의−0.124초(−0.251~+0.003)도0포함, 2026모두감소49/증가87출전은지원부족이다. 관측일당시간50%감소는전체147·최근23/16출전이라판단이특히제한된다.

7/28일·10회중앙값·가능일당비율·현재절대량·짝효과변경·90일이하·평소4일/60분이상·일수/시간단독을보존했다. 원천해시와앞선준비/평소SQL검증을고정하고 새분류45,021행·경계38·지원282셀·원시98셀·효과/군집공분산793개와보류모형식별을독립검산했다. 별도승인609행종류보완의현재DB/지침/문서함해시변경은분리감사했고조교날짜/기간·고정CSV는보존됐다. 이번DB개방·쓰기·외부수집·운영반영없음. 말별최적량/컨디션진단/원인효과/새예측증분은미확정이며기수·각질추후재개상태는유지한다.

## 앞선 개인 조교량 증감 연구

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text();line=next(s for s in s.splitlines() if '| [조교와 기록 향상]' in s)
 s=s.replace(line,'| [조교와 기록 향상](06_TRAINING_RECORD.md) | 평소 대비 큰 증감의 주조정 차이 미확인, 일수 큰 감소의 일부 민감도 악화 신호 | 극단구간·지원부족 검산 완료, 고정가감·운영미반영 |')
 s+=f'\n[평소 조교량의 큰 변화]({link}): 일수±4일/시간±50%, 초극단±6일/시간75%감소·2배증가와동시변화까지확인. 주72/중간대비36/H1 16/보충57검정지원0개이나 일수큰감소의일부민감도악화신호는보존했다. 최근초극단소표본/식별보류·효과없음확정/고정감점미채택.\n';p.write_text(s)
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n개인 조교량 큰 증감 후속: [4일·50% 이상 변화와 6일·75%감소·2배증가]({link}) — 기존고정45,021출전·2,279두. 능력·편성·기수짝·간격등고려, 주72/직접중간대비36/H1 16/보충57검정지원0개. 일수큰감소의일부민감도기록악화·최근초극단식별보류를함께보존,793효과/군집검산·고정가산/운영미채택.\n')
 reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics']);topic=next(t for t in reg['topics'] if t['id']=='training_record');previous=topic['latest_source']
 topic.update(d,latest_source=link,previous_personal_training_source=previous,primary_BH_tests=72,H1_BH_tests=16,primary_supported_directions=0)
 topic['extreme_personal_training_followup']={**d,'source':link,'pointwise_sensitivity_signals':5,'stable_fixed_adjustment_adopted':False}
 for t in topics:
  if t['id']!='training_record':assert next(v for v in reg['topics'] if v['id']==t['id'])==t
 reg.update(updated_at='2026-10-17',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json'])
 save(HERE/'artifact_manifest.json',{'status':d['status'],'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'listed_files':len(files),'listed_bytes':sum(p.stat().st_size for p in files),'excludes':'self and final publication receipt'})
 files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed|external:
   p=guarded(r['path']);r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files];assert not {r['path'] for r in rows}&{r['path'] for r in old}
 m['files']+=rows;m.update(updated_at='2026-10-17',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status'])
 m['verification'].update(status='passed_extreme_personal_training_publication',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),all_previous_research_output_files_unchanged=True,all_previous_nonmanagement_source_entries_unchanged=False,extreme_training_management_paths_changed=sorted(changed),documented_external_metadata_refresh_paths=sorted(external),external_change_evidence=str((HERE/'source_update_context.json').relative_to(ROOT)))
 m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in m['files']:
  p=guarded(r['path']);assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed|external:assert sha(guarded(r['path']))==r['sha256'] and guarded(r['path']).stat().st_size==r['bytes']
 for relative,r in drift.items():assert sha(guarded(relative))==r['actual']['sha256'] and guarded(relative).stat().st_size==r['actual']['bytes']
 links=0
 for p in [HERE/'README.md',HERE/'PUBLICATION_PROVENANCE.md',c/'06_TRAINING_RECORD.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'previous_entries_unchanged_except_four_management_and_three_external':len(old)-7,'other_topic_objects_preserved':len(topics)-1,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'central_entries_verified':len(m['files']),'central_manifest_sha256':sha(mp),'prepublication_management_hashes':before,'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[mp]},'external_files_not_modified_by_this_study':True,'documented_external_changes':audit['drift'],'local_links_verified':links,'database_opened':False,'operationally_applied':False,'jockey_and_style_revisit_later_preserved':True})
 print('Extreme personal training published and verified',len(files),'files',len(m['files']),'entries',flush=True)
if __name__=='__main__':main()
