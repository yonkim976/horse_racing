"""Append trainer topic, save jockey pause, and verify every previous immutable file."""
import json,re,shutil
from data import HERE,ROOT,sha,save
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 assert json.loads((HERE/'verification01/verification.json').read_text())['status']=='passed'
 assert json.loads((HERE/'profile_verification.json').read_text())['status']=='passed'
 central=ROOT/'jeju/research/conclusions';mp=central/'source_manifest.json';manifest=json.loads(mp.read_text());oldrows=json.loads(json.dumps(manifest['files']));reg=json.loads((central/'research_register.json').read_text());prior_topics=json.loads(json.dumps(reg['topics']))
 changed=[central/f for f in ['08_JOCKEY_PROFILE.md','README.md','SOURCES.md','research_register.json']];changed_paths={str(p.relative_to(ROOT)) for p in changed}
 for r in oldrows:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 newdoc=central/'20_TRAINER_PROFILE.md';assert not newdoc.exists() and not any(t['id']=='trainer_profile' for t in reg['topics'])
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in changed+[mp]:shutil.copyfile(p,snap/p.name)
 snapshot_hashes={str(p.relative_to(ROOT)):sha(p) for p in changed+[mp]}
 link='../'+HERE.name+'/README.md'
 newdoc.write_text(f'''# 조교사별 특성과 말의 수행 개선

**조교사별 배정과 역사적 조건부 수행 차이는 관측되지만,말의 순수 능력을 올리는 개인별 순위는 미확정이다.** 최신 [조교사별 수행과 변경 전후 연구]({link})는2017-01-13~2026-09-19 정상완주 완전 편성52,155출전·5,206경주·2,813두·25명을 분석했다.2026부분연도,현재8거리,7~13두 편성이며400m와 제외 말은 편입하지 않았다.

## 배정과 조건부 특성

말의 과거 수행·경주 조건·기수를 이용하되 조교사ID를 쓰지 않는H1의 예상Top3와 실제Top3의 조교사간 상관은2024~2025년0.968,2026년0.852였다. 좋은말·조건 배정과 실적이 강하게 연관되며 인과 기여 비율은 아니다.2026년 심도연295출전 실제48.8%/기대37.1%,이태용333출전47.7%/45.2%,이준호339출전37.5%/32.6%였다. 단순 기대초과 실적을 조교사 효과로 확정하지 않는다.

경주와 말×정확거리 고정효과에 기수·체중·부담·게이트·T−2 과거 수행을 고려한 전체기간 대비에서 이준호는 평균 조교사보다0.390초 빠른 연관(날짜95%0.281~0.499·말95%0.256~0.524초),강영진은S1F첫통과조+6.37%p,김영래는+6.26%p,이태용은Top3+7.23%p 및 막판600m 상대시간순위+3.41%p가 관측됐다. 전체 양방향 표본·구간·단위와 소표본 상태는 원 연구 표를 따른다. 최근2024~2025/2026에 반복 지원된 주분석 특성은0개다. 이준호·심도연의2026시간점추정은 유리하나BH 기준을 통과하지 못했다. 김영래의2026선정 출전은 없다. 영구 선행·추입 전문가나 순수 능력 순위로 지정하지 않는다.

## 변경 전후와 이후 예측

직전 선택출전과 조교사ID가 달라진 사례2,771건·1,279두 중 같은말·정확거리·마주,2~120일,양쪽H1가용인2024+변경392쌍을 비교했다. 기대초과 상대기록의 전후개선은2024~2025년287쌍+0.645초(날짜95%0.432~0.856·말0.409~0.887초),2026년105쌍+0.952초(날짜0.590~1.314·말0.623~1.267초)였다. 변경 전 이미 기대보다0.604/0.693초 부진한 말이 선택돼 평균회귀·회복·기수교체·선택을 분리하지 못한다. 절대 기록 단축과 조교사 이적의 인과효과가 아니다.2026개별 조교사별20쌍·10두 지원은 모두 부족했다.

같은17,412출전·1,779경주의연도 고정 비교에서H1에조교사ID를더하면MAE2024~2025년0.940326→0.939138초,2026년0.884533→0.885143초였다. 말ID를 포함한 모형에서도2024~2025년만 작게 개선됐고2026년과Top3logloss에서 반복 개선이 없었다. 조교사 정보의 부재가 증명된 것은 아니다. 고정초 보정·능력 가산점·전문 태그·운영모델 변경은 미채택이다.

## 해석과 연결

말 성장·컨디션·휴양·마주 자원과 비무작위 변경이 남고,말 고정효과는 시간불변 차이만 제거한다. 과거 수행 조정은 누적 조교사 기여를 흡수할 수 있으며 경주 고정효과는 공통페이스를 제거한다. 정상완주 완전편성 결과는 사고·중단을 포함한 전체 관리능력 평가가 아니다. 과거 기간 재사용으로 독립 미래 검증이 아니고 선언정보 공개시각 재생도 아니다.

22설명모형·477대비/구간,139,296예측값과전처리,10,004선정쌍·64집계를 재계산했다.2026년100출전 이상18명 프로필,모든기간 전체표와 코드·원천·검증·정정 이력은 원 연구에 보존한다. DB접속·쓰기·외부수집·운영반영은 없다. 일별 운동량을 다룬 [조교와 기록 향상](06_TRAINING_RECORD.md)은 별도 연구이고,[기수 연구](08_JOCKEY_PROFILE.md)는2026-10-10사용자 요청으로 현 결론 저장 후 추후 재개 상태다.
''')
 p=central/'08_JOCKEY_PROFILE.md';s=p.read_text();head,body=s.split('\n\n',1);p.write_text(head+'\n\n2026-10-10 사용자 요청으로 기수 연구는 아래 결론까지 저장하고 추후 재개 상태로 둔다. 다음 주제는 [조교사별 특성과 말의 수행 개선](20_TRAINER_PROFILE.md)이다. 기존 결과와 미채택 판단은 유지한다.\n\n'+body)
 p=central/'README.md';s=p.read_text();line=next(x for x in s.splitlines() if '| [기수 특성과 좋은말 배정]' in x);s=s.replace(line,line.replace('여섯 후속 질문 완료, 새 전문 태그·조건 가중치·운영 미반영','현 결론 저장 후 추후 재개, 운영 미반영'));s=s.replace('공동 입상관계 비교다.','공동 입상관계 비교·조교사별 수행과 변경 전후 비교다.');s=s.replace(line.split('|')[0]+'| [기수 특성과 좋은말 배정]',line.split('|')[0]+'| [기수 특성과 좋은말 배정]') if False else s
 row='| [조교사 특성과 말의 수행 개선](20_TRAINER_PROFILE.md) | 배정과 역사적 수행 차이는 관측, 최근 반복 특성·인과 향상 순위 미확정 | 완료, 고정 가산점·운영 미반영 |'
 lines=s.splitlines();i=next(i for i,v in enumerate(lines) if '| [기수 특성과 좋은말 배정]' in v);lines.insert(i+1,row);p.write_text('\n'.join(lines)+'\n')
 p=central/'SOURCES.md';s=p.read_text();assert link not in s;p.write_text(s+f'\n후속: [{HERE.name}]({link}) — 조교사별 기대배정·말×거리/경주고정효과·초반/막판 특성·같은말 동일거리/마주 변경 전후·연도 고정 조교사ID 추가 비교. 최근 반복 특성 및 예측개선 미확정,최종쌍switch02·검증verification01. 기수 연구는현결론저장후추후재개.\n')
 reg['updated_at']='2026-10-10';j=next(t for t in reg['topics'] if t['id']=='jockey_profile');j['user_work_phase']='current_findings_saved_revisit_later_2026_10_10'
 for t in prior_topics:
  if t['id']!='jockey_profile':assert next(v for v in reg['topics'] if v['id']==t['id'])==t
 d=json.loads((HERE/'decision.json').read_text());reg['topics'].append({'id':'trainer_profile','title':'조교사별 특성과 말의 수행 개선','conclusion':newdoc.name,'latest_source':link,**d});reg.update(latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(central/'research_register.json',reg)
 files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']]
 entries=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
 save(HERE/'artifact_manifest.json',{'status':'completed_verified_research_only','files':entries,'listed_files':len(entries),'listed_bytes':sum(r['bytes'] for r in entries),'excludes':'self and final publication receipt'});files.append(HERE/'artifact_manifest.json')
 for r in manifest['files']:
  if r['path'] in changed_paths:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 new=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)];new.append({'path':str(newdoc.relative_to(ROOT)),'role':'conclusion_or_management','sha256':sha(newdoc),'bytes':newdoc.stat().st_size});assert not {r['path'] for r in manifest['files']}&{r['path'] for r in new};manifest['files']+=new
 manifest.update(updated_at='2026-10-10',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);manifest['verification'].update(status='passed_trainer_research_publication',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),previous_entries_verified_before_publication=len(oldrows),all_previous_nonmanagement_source_entries_unchanged=True,trainer_research_no_database_or_operating_model_changes=True,trainer_management_paths_changed=sorted(changed_paths));manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in manifest['files']);save(mp,manifest)
 for r in manifest['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in oldrows:
  if r['path'] not in changed_paths:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 links=0
 for p in [HERE/'README.md',newdoc,central/'08_JOCKEY_PROFILE.md',central/'README.md',central/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(oldrows),'prior_entries_unchanged_excluding_four_management_files':len(oldrows)-len(changed_paths),'previous_other_topic_objects_preserved':len(prior_topics)-1,'jockey_user_pause_saved':True,'running_style_user_pause_preserved':True,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'new_conclusion_file':str(newdoc.relative_to(ROOT)),'central_entries_verified':len(manifest['files']),'central_manifest_sha256':sha(mp),'links_checked':links,'prepublication_management_hashes':snapshot_hashes,'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in changed+[newdoc,mp]},'no_database_or_operational_changes':True})
 print('Trainer publication passed',len(files),'files',len(manifest['files']),'central entries',flush=True)
if __name__=='__main__':main()
