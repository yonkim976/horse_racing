"""Publish the individual follow-up while preserving the aggregate study."""
import copy,json,re,shutil
from data import HERE,ROOT,sha,save
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for name in ['verification02/verification.json','report01/verification.json']:
  assert json.loads((HERE/name).read_text())['status']=='passed'
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';audit=json.loads((HERE/'prepublication_audit01.json').read_text());assert not audit['drift'] and sha(mp)==audit['central_manifest_sha256'];m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics']);d=json.loads((HERE/'decision.json').read_text());paths=[c/v for v in ['06_TRAINING_RECORD.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths}
 for r in old:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]};link='../'+HERE.name+'/README.md';p=c/'06_TRAINING_RECORD.md';s=p.read_text();head,body=s.split('\n\n',1);body=body.replace('최신 [기수의 직접 조교 참여와 경주 성적]','앞선 [전체 기수의 직접 조교 참여와 경주 성적]',1)
 add=f'''최신 [기수별 본인 조교 후 기승 성적]({link})에서는 **기수별 원시 성적 차이는 있지만, 같은 말·거리·기수 조합과 편성을 고려한 개인 우세는 확인하지 못했다.** 전체기간36명·2024~2025년5명·2026년1명이 주지원, 주126검정·H1기대초과6검정·소표본153검정에서 방향지원0개·최근반복0개다. 고정기수조교가점은 채택하지 않았다.

## 기수별 직접 조교 후 기승 비교

앞선 불변52,155출전·5,206경주·2,813두(2017-01-13~2026-09-19,현재8거리·원천7~13두·정상완주완전편성·400m/제외말결과미편입·2026부분연도)와검산된조교피처를사용했다. D−14~D−2·직전실제출전이후의종류/ID완전확인34,490출전에서같은기수의본인참여/미참여를비교했다. 미참여에는다른기수만과확인된다른종류만이모두포함된다. 미분류·무원행을미참여로세지않았다. DB접속·외부수집·쓰기없음.

경주효과와말×정확거리×기수의짝효과를동시에제거하고기수별조교항을함께추정했다. 과거수행·직전성적·간격·부담·체중·게이트·조교사·조교량을고려해짝의고정능력/친숙도와편성차이를일부줄였다. 개인주지원은양쪽각50출전·20두·15경주일·교차말10두이며결과산출전고정했다. 앞선집단100/30/20/20기준지원은진단으로보존했다. 주/엄격기준기수수는전체36/35,2024~2025년5/1,2026년1/0이다.

| 전체기간 예시 | 본인참여 / 미참여 출전 | 미참여 → 본인참여 Top3 | 조정Top3 차이와 날짜95% |
|---|---:|---:|---:|
| 안득수 | 854 / 930 | 26.13% → 38.41% | +5.17%p (−6.07~+16.40) |
| 한영민 | 740 / 673 | 32.84% → 40.14% | +3.70%p (−8.01~+15.40) |
| 강수한 | 870 / 724 | 35.91% → 42.99% | +2.99%p (−9.30~+15.28) |
| 문현진 | 784 / 1,169 | 38.58% → 45.41% | +2.60%p (−10.81~+16.02) |
| 김준호 | 604 / 979 | 34.53% → 39.40% | +7.36%p (−6.01~+20.73) |

예시는2026고정코호트출전관측·전체주지원기수중원시Top3증가폭상위5명이며조정우세순위가아니다. 박성광도717/667출전·원시41.56%대37.78%이나조정+2.94%p(날짜−11.08~+16.96)로불확실하다. 원유일의음수차이도확정하지않았다. 전체한영민기록+0.135초·전현준+0.233초·김준호+0.127초의구간도0을포함한다. 기록은편성평균대비상대기록이고빠름양수다.

2024~2025주지원은한영민·김준호·김홍권·이성민·박재희5명이며모두불확실하다.2026주지원은한영민73/66출전·교차15두뿐이고기록−0.053초(날짜−1.949~+1.844·말−2.170~+2.064)로최근반복우세가아니다. 미분류창2,907/4,673출전의정보공백과동일짝비교의정보감소가남아넓은구간을효과0으로해석하지않는다.

짝효과를빼는덜엄격한민감도에서한영민기록+0.217초·안득수Top3+9.50%p등점별양수구간이생기지만,주검정의발견으로승격하지않는다.7/28일·조교량제외·다른기수만·소표본을보존했다. 공동기수차이6검정도BH후차이를확인하지못했다. 개인126주검정은날짜/말각95%와날짜BH를함께적용했으며양수·음수모두지원0개다.

지원644셀·원시183셀/구간·개인846효과와공분산·BH/공동검정/최근반복을독립합동정규방정식Schur소거로재계산했다. 원천해시·바이트불변,중단한직접분해시도와최종검산을구분해보존했다. 비무작위말배정·건강/승부선택·조교강도·과거게시시각미관측이남고,효과없음의증명·개인가산·새예측추가개선·운영반영은아니다. 기존기수전체/각질추후재개상태를유지했다.

## 앞선 전체평균 조교 참여 연구

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text();line=next(v for v in s.splitlines() if '| [조교와 기록 향상]' in v);s=s.replace(line,'| [조교와 기록 향상](06_TRAINING_RECORD.md) | 전체평균·기수별 직접참여의 안정적 조정 우세 미확인, 개인주126검정 지원0개 | 기수별 후속·독립 검산 완료, 운영 미반영 |');s+=f'\n[기수별 본인 조교 후 기승]({link}): 전체36명/2024~2025년5명/2026년1명 주지원. 같은 말·거리·기수짝과편성고려후126주검정에서우세기수미확정·최근반복0개. 원시개선사례와개인보류·민감도를보존,고정가점미채택.\n';p.write_text(s)
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n기수별 조교 후속: [본인 직접 조교한 말에 기승할 때의 개인차]({link}) — 불변52,155출전·종류확인34,490·D−14~D−2. 같은기수의본인참여/미참여와경주·말거리기수짝효과. 개인주126/H1 6/소표본153검정 양수지원0개·최근반복0개. 원시사례·모형민감도·846효과 독립검산 저장, 가산·운영미채택.\n')
 topic=next(v for v in reg['topics'] if v['id']=='training_record');previous=topic['latest_source'];topic.update(d,latest_source=link,previous_aggregate_training_source=previous);topic['individual_jockey_training_followup']={**d,'source':link,'raw_improvement_examples_are_not_adjusted_discoveries':True}
 for v in topics:
  if v['id']!='training_record':assert next(x for x in reg['topics'] if x['id']==v['id'])==v
 reg.update(updated_at='2026-10-17',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']);save(HERE/'artifact_manifest.json',{'status':'completed_verified_individual_jockey_training_research','files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'listed_files':len(files),'listed_bytes':sum(p.stat().st_size for p in files),'excludes':'self and final publication receipt'});files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files];assert not {r['path'] for r in rows}&{r['path'] for r in old};m['files']+=rows;m.update(updated_at='2026-10-17',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);m['verification'].update(status='passed_individual_jockey_training_publication',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),all_previous_research_output_files_unchanged=True,all_previous_nonmanagement_source_entries_unchanged=True,individual_jockey_training_management_paths_changed=sorted(changed));m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in m['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 links=0
 for p in [HERE/'README.md',c/'06_TRAINING_RECORD.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'previous_entries_unchanged_except_four_management_files':len(old)-4,'other_topic_objects_preserved':len(topics)-1,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'central_entries_verified':len(m['files']),'central_manifest_sha256':sha(mp),'prepublication_management_hashes':before,'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[mp]},'local_links_verified':links,'database_opened':False,'operationally_applied':False,'jockey_and_style_revisit_later_preserved':True});print('Individual jockey training published and verified',len(files),'files',len(m['files']),'entries',flush=True)
if __name__=='__main__':main()
