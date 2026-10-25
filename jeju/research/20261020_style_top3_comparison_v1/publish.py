"""Append a verified study; preserve unrelated source metadata without refreshing it."""
import copy,json,re,shutil
from analysis import HERE,ROOT,sha,save
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 verification=json.loads((HERE/'verification01/verification.json').read_text());assert verification['status']=='passed'
 source=json.loads((HERE/'source_manifest.json').read_text())
 for r in source['files']:
  p=(ROOT/r['path']).resolve();assert p.is_relative_to(ROOT/'jeju') and sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics']);d=json.loads((HERE/'decision.json').read_text());link='../'+HERE.name+'/README.md'
 names=['07_RUNNING_STYLE.md','README.md','SOURCES.md','research_register.json'];paths=[c/name for name in names];changed={str(p.relative_to(ROOT)) for p in paths}
 for p in paths:
  r=next(r for r in old if r['path']==str(p.relative_to(ROOT)));assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],p
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]}
 p=c/'07_RUNNING_STYLE.md';head,body=p.read_text().split('\n\n',1)
 add=f'''2026-10-20 사용자 요청으로 [사전 각질별 입상률 비교]({link})를 재개했다. **거리 통합 이력의 원시 Top3는 선행형34.65%, 선입형32.46%, 추입 후보32.63%로 선행형이 근소하게 높다. 능력·편성 고려 후 안정적인 선행 우위는 확인하지 못했다.** 다른 각질 예측·편성 확장과 기수 연구는 추후 재개 상태를 유지한다.

## 사전 각질별 입상률 후속

기존 검증 입력의2017-01-13~2026-09-19 정상완주 완전편성52,155출전·5,206경주·2,813두에서 집계했다. 현재8거리·400m/제외말제외이며2026년은부분연도다. 세 유형 판정은8,571출전·933두이고 다른/혼합31,309·이력부족등미판정12,275출전은억지로편입하지않았다.

T−2까지730일 내 최근최대10회·유효S1F5회/60%이상이다. 선행은전방60%·첫집단60%이상, 선입은전방60%·첫집단60%미만, 추입후보는중후방60%·유효4C→G1F최소5쌍중확실2두전진60%이상이다. 현재입상/실제위치로과거각질을정하지않고후미마전체를추입으로부르지않는다.

| 사전 유형 | 전체 Top3/출전 · 비율 | 2024~2025 | 2026 |
|---|---:|---:|---:|
| 선행형 | 1,433/4,136 · 34.65% | 394/1,069 · 36.86% | 128/356 · 35.96% |
| 선입형 | 1,378/4,245 · 32.46% | 383/1,187 · 32.27% | 153/451 · 33.92% |
| 추입 후보 | 62/190 · 32.63% | 31/93 · 33.33% | 3/29 · 10.34% |

입상은최종1~3착이며한번출전당비율이다. 추입후보는전체49두/2026년11두로작고2026년3/29를일반확률로사용하지않는다. 800/900/1110/1200m는원시선행우세,1000m는선입35.10%대선행32.30%다.1300/1400/1610m와모든거리별추입후보는소표본이라우세일반화를보류한다.

같은경주효과와게이트·부담·과거전체/동일거리착순·상대시간·초반/막판시간·출전수·공백을고려했다. 전체선입−선행은−1.50%p(날짜95%−6.32~+3.32),2024~2025년−5.87%p(−15.14~+3.40),2026년+5.82%p(−8.62~+20.26)로불확실하고방향도바뀐다. 엄격추입후보의전체음수차이는개별구간상0보다낮지만BH q0.143·다른정의불안정·최근지원부족으로고정감점미채택이다.3대비×3기간주9가설의미지원을p=1로포함했고지원/최근반복0개다.

동일거리이력만쓰면추입후보33.33%(42/126),선행30.16%(589/1,953),선입26.92%(613/2,277)로원시순서가달라진다. 전진반복40%로완화하면추입후보29.71%(268/902)다. 각질정의에민감하므로고정확률/가산을채택하지않는다.

독립라벨156,465행·SQL261비율셀과구간·27지원대비·9모형의합동경주효과/군집공분산·BH를검산했다. 후향정상완주·각질관측선택·미관측능력/전략·게시시각미확정한계를보존했다. DB개방/쓰기·외부수집·운영반영없음. 이전연구의원본은보존했고이번에다룬입상률비교외의보류상태는유지한다.

## 앞선 각질 편성과 전개 연구

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text().replace('2026년 10월 17일 기준.','2026년 10월 20일 기준.',1);line=next(v for v in s.splitlines() if '| [통과조 기반 각질과 전개]' in v)
 s=s.replace(line,'| [통과조 기반 각질과 전개](07_RUNNING_STYLE.md) | 사전 선행34.65/선입32.46/추입후보32.63%, 조정 우위 미확정·추입 소표본 | 각질별 입상률 비교 재개·검산 완료, 다른 전개 확장 추후·운영미반영 |')
 s+=f'\n[제주 사전 각질별 입상률 비교]({link}): 2017~2026-09-19 거리통합 과거이력의 선행34.65%, 선입32.46%, 추입후보32.63%. 선행 원시근소우세이나 능력·편성 고려 후 주9가설지원0개·최근반복0개. 동일거리/추입완화 정의에 민감하며 추입후보190출전·최근29출전의 한계를 보존했다.\n';p.write_text(s)
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n2026-10-20 각질별 입상률 재개: [사전 선행·선입·추입 후보의 Top3 비교]({link}) — 52,155출전 중 세유형8,571출전·933두. 거리통합 원시34.65/32.46/32.63%, 같은경주·과거능력 고려 주9가설지원0개. 거리별분모·동일거리/완화정의·최근지원부족 및 독립SQL/9모형 검산을 보존. 개별미래확률/각질보너스·운영미채택.\n')
 topic=next(v for v in reg['topics'] if v['id']=='running_style');previous=topic.get('latest_source');topic.update(status=d['status'],latest_source=link,previous_style_density_source=previous,style_top3_resumed_by_user=True,other_style_followups_remain_deferred=True)
 topic['style_top3_comparison_followup']={**d,'source':link}
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
 m['verification'].update(status='passed_style_top3_publication_scoped',scope='new study inputs and outputs plus four central management files; unrelated historical source entries retained without revalidation',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),all_previous_research_output_files_unchanged=None,all_previous_nonmanagement_source_entries_unchanged=None,prior_external_sources_revalidated=False,prior_source_metadata_preserved_except_four_management_files=True,style_top3_management_paths_changed=sorted(changed))
 m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in rows:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
 for r in old:
  current=next(x for x in m['files'] if x['path']==r['path'])
  if r['path'] not in changed:assert current==r
 for p in paths:
  record=next(x for x in m['files'] if x['path']==str(p.relative_to(ROOT)));assert sha(p)==record['sha256'] and p.stat().st_size==record['bytes']
 links=0
 for p in [HERE/'README.md',c/'07_RUNNING_STYLE.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','verification_scope':'new study and four central management files only','new_study_files_verified':len(rows),'new_study_bytes':sum(r['bytes'] for r in rows),'old_source_metadata_entries_retained_except_four_management':len(old)-4,'unrelated_historical_sources_revalidated':False,'other_topic_objects_preserved':len(topics)-1,'central_manifest_entries':len(m['files']),'central_manifest_sha256':sha(mp),'previous_management_hashes':before,'local_links_verified':links,'style_top3_resumed_by_user':True,'other_style_and_jockey_followups_deferred':True,'database_opened':False,'operationally_applied':False})
 print('Style Top3 comparison saved and indexed',len(rows),'new files',flush=True)
if __name__=='__main__':main()
