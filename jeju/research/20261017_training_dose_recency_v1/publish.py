"""Publish dose, timing and duration follow-up; preserve every earlier study."""
import copy,json,re,shutil
from data import HERE,ROOT,sha,save
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for name in ['verification01/verification.json','report01/verification.json']:
  assert json.loads((HERE/name).read_text())['status']=='passed'
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';audit=json.loads((HERE/'prepublication_audit01.json').read_text());assert not audit['drift'] and sha(mp)==audit['central_manifest_sha256'];m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics']);d=json.loads((HERE/'decision.json').read_text());paths=[c/v for v in ['06_TRAINING_RECORD.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths}
 for r in old:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]};link='../'+HERE.name+'/README.md';p=c/'06_TRAINING_RECORD.md';s=p.read_text();head,body=s.split('\n\n',1);body=body.replace('최신 [기수별 본인 조교 후 기승 성적]','앞선 [기수별 본인 조교 후 기승 성적]',1)
 add=f'''최신 [본인 조교 일수·최근성·시간과 전체 조교량]({link})에서는 **더많은본인조교일수·경주근접참여·누적시간·전체관측량의안정적조정우세를확인하지못했다.** 통합90/H1기대초과17/기수별291검정에서방향지원과최근반복0개다. 실제일일시행횟수는미제공이며주창에서는관측행수와날짜수가같았다.

## 본인 조교의 일수·최근성·시간 후속

불변52,155출전·5,206경주·2,813두(2017-01-13~2026-09-19·현재8거리·원천7~13두·정상완주완전편성·400m/제외말미편입·2026부분연도)와641,228조교행을사용했다. D−14~D−2·직전실제출전일이후,본인은종류/ID완전확인34,490출전·참여18,492,전체량은원행/시간관측52,021출전이다. 미분류/무원행을미참여/미조교로채우지않고당일·전날은쓰지않았다.

| 본인 관측일수 | 전체 출전 수 | 원시Top3 | 2026 출전 수 |
|---|---:|---:|---:|
| 0일 | 15,998 | 30.00% | 626 |
| 1일 | 2,506 | 31.05% | 70 |
| 2~3일 | 2,372 | 30.27% | 67 |
| 4일 이상 | 13,614 | 29.85% | 1,003 |

경주효과와말×정확거리×기수짝효과,과거수행·직전성적·간격·부담·체중·게이트·조교사를고려했다. 본인일수/최근성/시간은다른조교량도함께고려했고전체행수·시간은같은모형의조건부비교다. 아래기록은편성평균대비상대기록,빠름양수초,날짜95%다. 말군집구간과환산착순/Top3도원연구에보존했다.

| 전체기간 조정 비교 | 빠름 초 (날짜95%) |
|---|---:|
| 본인2~3일 대1일 | +0.104 (−0.034~+0.241) |
| 본인4일이상 대1일 | +0.044 (−0.078~+0.167) |
| 마지막본인2~3일전 대4~7일전 | +0.133 (−0.088~+0.353) |
| 본인시간60분초과 대30~60분 | +0.006 (−0.193~+0.206) |
| 전체9행이상 대5~8행 | −0.010 (−0.065~+0.045) |
| 전체120분초과 대60~120분 | −0.011 (−0.061~+0.039) |

본인최근2~3일전16,015출전의원시Top3 29.90%,4~7일전1,757출전31.25%,8~14일전720출전30.97%로가까울수록단순개선하지않았다. 전체시간120분초과의원시32.01%대60~120분28.60%차이는조정Top3−0.05%p(날짜−2.08~+1.98)로불확실해졌다.2026원시시간방향도30.31%대31.81%로반대이며조정기록−0.155초(날짜−0.330~+0.019)로불확실하다.

2026본인참여1,140중1,003출전이4일이상,마지막2~3일전은1,008출전이다.1일70/2~3일67및마지막8일이전24는지원부족으로보류했다. 가까운2~3일대4~7일의2026조정기록+1.961초도구간−2.906~+6.827로넓어개선수치로쓰지않는다. 전체1~4행53출전도2026비교보류다. 모든보류·교차말·구간은원연구모형원장에있다.

기수별보충은본인참여창에서본인3일더관측/마지막3일가까움의연속기울기를함께추정하고본인시간·전체량을고려했다. 전체일수38명/최근성36명,2024~2025년17/6명,2026지원0명이다. 개인291검정지원0개·최근반복0개이며최적일수/마지막하루처방이아니다.7/28일·말거리효과+기수주효과·행수대신날짜수민감도도보존했다.

실제횟수API의전기간0은미제공이다. 이번14일주창52,021원행관측출전모두원행수=관측날짜수였으므로‘9행이상’은9개이상날짜관측이지하루안9번시행이아니다. 시간도입퇴장기간합계이며조교강도·속도·거리를측정한것은아니다. 지원은통합각100출전·30두·20일·교차20두,개인100참여출전·30두·20일·3피처값·짝내변화교차10두를사전고정했다. 계획117통합목표중지원90개/H1지원17개/개인291개를각BH가족으로검정했고날짜/말구간과BH후방향지원0개다.

156,465창SQL·20미래교란·지원352셀·원시48셀/구간·698효과/군집공분산과BH·최근반복을독립Schur정규방정식으로검산했다. 원천해시·바이트불변,DB접속/외부수집/쓰기없음. 정상완주·종류확인선택과건강/승부선택·강도·게시시각미관측,후향반복분석이남는다. 조교효과없음의증명·고정시간보정/가산·새예측증분·운영반영은아니다. 기수전체/각질추후재개상태는유지했다.

## 앞선 기수별 직접 조교 참여 연구

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text();line=next(v for v in s.splitlines() if '| [조교와 기록 향상]' in v);s=s.replace(line,'| [조교와 기록 향상](06_TRAINING_RECORD.md) | 본인조교 일수·최근성·시간 및 전체관측량의 안정적 조정 우세 미확인 | 통합90/개인291검정·검산 완료, 실제횟수미제공·운영미반영 |');s+=f'\n[본인 조교 일수·최근성·시간과 전체량]({link}): D−14~D−2·같은말거리기수짝/편성고려. 더많거나가까운본인조교,전체관측횟수/시간의통합90/H1 17/개인291검정에서지원0개. 실제일일시행횟수미제공·일수와행수동일·고정가산미채택.\n';p.write_text(s)
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n조교량·최근성 후속: [본인 관측일수와 마지막참여·누적시간·전체량]({link}) — 불변52,155출전·본인확인34,490/참여18,492·전체량52,021. 본인0/1/2~3/4+일·마지막2~3/4~7/8+일·본인30/60분·전체행수5~8/시간60~120기준. 통합90/H1 17/개인291검정지원0개·156,465창SQL/698효과검산완료,실횟수미제공·가산/운영미채택.\n')
 topic=next(v for v in reg['topics'] if v['id']=='training_record');previous=topic['latest_source'];topic.update(d,latest_source=link,previous_individual_training_source=previous);topic['dose_recency_training_followup']={**d,'source':link,'record_count_equals_observed_days_in_primary':True}
 for v in topics:
  if v['id']!='training_record':assert next(x for x in reg['topics'] if x['id']==v['id'])==v
 reg.update(updated_at='2026-10-17',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']);save(HERE/'artifact_manifest.json',{'status':'completed_verified_training_dose_recency_research','files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'listed_files':len(files),'listed_bytes':sum(p.stat().st_size for p in files),'excludes':'self and final publication receipt'});files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files];assert not {r['path'] for r in rows}&{r['path'] for r in old};m['files']+=rows;m.update(updated_at='2026-10-17',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);m['verification'].update(status='passed_training_dose_recency_publication',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),all_previous_research_output_files_unchanged=True,all_previous_nonmanagement_source_entries_unchanged=True,training_dose_recency_management_paths_changed=sorted(changed));m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in m['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 links=0
 for p in [HERE/'README.md',c/'06_TRAINING_RECORD.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'previous_entries_unchanged_except_four_management_files':len(old)-4,'other_topic_objects_preserved':len(topics)-1,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'central_entries_verified':len(m['files']),'central_manifest_sha256':sha(mp),'prepublication_management_hashes':before,'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[mp]},'local_links_verified':links,'database_opened':False,'operationally_applied':False,'jockey_and_style_revisit_later_preserved':True});print('Training dose/recency published and verified',len(files),'files',len(m['files']),'entries',flush=True)
if __name__=='__main__':main()
