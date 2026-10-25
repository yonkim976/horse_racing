"""Publish verified return-stage research and preserve earlier source studies."""
import copy,hashlib,json,re,shutil
from data import HERE,ROOT,save,sha

def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for name in ['verification01/verification.json','report01/verification.json']:
  assert json.loads((HERE/name).read_text())['status']=='passed'
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json'
 audit=json.loads((HERE/'prepublication_audit01.json').read_text())
 assert sha(mp)==audit['central_manifest_sha256']
 m=json.loads(mp.read_text());old=copy.deepcopy(m['files'])
 reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics'])
 d=json.loads((HERE/'decision.json').read_text())
 paths=[c/v for v in ['25_START_INTERVAL.md','README.md','SOURCES.md','research_register.json']]
 changed={str(p.relative_to(ROOT)) for p in paths}
 assert len(audit['drift'])==1
 drift=audit['drift'][0];external='jeju/review_documents/README.md';assert drift['path']==external
 ep=ROOT/external;parts=ep.read_text().split('\n\n')
 assert parts[1].startswith('최신 미분류 원인·보완 범위는')
 del parts[1];reconstructed='\n\n'.join(parts).encode('utf-8')
 assert len(reconstructed)==drift['registered']['bytes']
 assert hashlib.sha256(reconstructed).hexdigest()==drift['registered']['sha256']
 for r in old:
  p=ROOT/r['path'];expected=drift['observed'] if r['path']==external else r
  assert sha(p)==expected['sha256'] and p.stat().st_size==expected['bytes'],r['path']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 shutil.copyfile(ep,snap/'external_review_documents_README.md')
 (snap/'external_review_documents_previous_reconstructed.md').write_bytes(reconstructed)
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]};link='../'+HERE.name+'/README.md'
 p=c/'25_START_INTERVAL.md';s=p.read_text();head,body=s.split('\n\n',1)
 body=body.replace('최신 [개인 평소주기 이탈과 적정주기 후보]','앞선 [개인 평소주기 이탈과 적정주기 후보]',1)
 add=f'''최신 [장기 공백 복귀 첫째·둘째·셋째 경주]({link})에서는 **계속 같은 거리로 출전한 말의 전체기간 일부 개선은 관찰됐지만, 최근 반복 우세와 모든 복귀마의 회복 규칙은 확인하지 못했다.** 절대 출전간격·개인 평소주기·복귀 후 순번은 서로 다른 질문으로 보존한다.

## 장기 공백 복귀 후 순번별 성적

91일 이상 관측 출전 공백 뒤 첫 경주를 복귀로 정의했다. 실제 휴양·부상 사유 확인은 아니다. 첫 복귀 후 다음 두 실제 출전이 각각 60일 이내·합계 120일 이내인 사례를 추적했다. 65,269실제 출전 원장으로 순번을 세고 분석불가 출전을 건너뛰지 않았다. 정상 분석결과는 기존 52,155출전·5,206경주·2,813두, 2017-01-13~2026-09-19, 현재 8거리·7~13두·400m/제외말 결과 미편입이다. 자료 상한 때문에 첫 복귀는 2026-05-22까지로 제한했다. 이 상한 이후 첫 복귀 257건은 관찰기간 부족이며 후속 미출전으로 세지 않았다.

세 회차 모두 정상 분석자료가 있고 정확거리가 같은 주표본은 전체1,034사례·796두,2024~2025년272사례·243두,2026년48사례·48두다. 같은 대상의 조정 전 성적은 다음과 같다.

| 기간 | 첫째 평균 착순 / Top3 | 둘째 평균 착순 / Top3 | 셋째 평균 착순 / Top3 |
|---|---:|---:|---:|
| 전체 | 5.62위 / 28.0% | 5.46위 / 28.3% | 5.35위 / 31.5% |
| 2024~2025 | 5.27위 / 34.2% | 5.11위 / 32.7% | 4.97위 / 36.0% |
| 2026 | 5.17위 / 29.2% | 5.17위 / 27.1% | 5.00위 / 37.5% |

복귀 사례와 경주 효과, 해당 경주 다른 말과 전체 정상 배경, 과거 수행·부담·체중·게이트·기수·조교사를 고려했다. 주복귀마의 과거 수행은 첫 복귀 당시로 고정했다. 전체 둘째의 첫째 대비 기록은0.125초 빠름(날짜95%+0.034~+0.215·말+0.022~+0.227,BH q0.0438),셋째는10두환산0.405위 상승(날짜+0.195~+0.614·말+0.156~+0.653,q0.0030)과Top3+6.02%p(날짜+2.44~+9.60·말+1.85~+10.19,q0.0091)가 주18검정 기준을 충족했다. 셋째의 기록+0.094초와 둘째의Top3+1.15%p는 불확실했다. 원시 셋째Top3 증가는+3.48%p로 조정+6.02%p와 다르다. 최근 두 기간의 동일 비교 반복 지원은0개다.

2026년 둘째/셋째 기록은+0.111/+0.139초이나 날짜 구간은 각각−0.296~+0.517/−0.344~+0.621초였다. 셋째Top3+8.84%p의 구간도−9.93~+27.60%p로 넓다. 48사례의 개선 방향을 최근 확정 규칙으로 쓰지 않는다. 성적 산출 전 분모만 확인한 뒤 최소50사례를 공통30사례·30두·20첫 복귀일로 보완했으며, 최초50지원 여부와 원계획을 원연구에 보존했다.

전체4,746복귀 중120일 관찰가능4,489사례,정상 첫째4,144,정상 세회차2,215,정확거리 동일1,034다. 주표본 첫째 평균5.62위,나머지 정상 첫째6.17위로 계속 같은 거리로 출전한 말은 시작부터 순위가 더 좋았다. 셋째를 요구하지 않은 첫째·둘째2,014쌍의 기록차이는+0.047초(날짜−0.016~+0.110)로 약해졌다. 181일 이상227사례에서는 둘째+0.043/셋째−0.032초 모두 불확실했다. 최근 수행을 회차별로 갱신하면 주표본 둘째−0.007/셋째−0.050초로 추가 순번 기록차이가 확인되지 않았다. 기존 간격·능력·편성 기대를 포함한H1잔차의 최근4검정도 추가 지원은0개다.

원시81셀과59목표 모형·주BH18/H1 BH4검정·사례순서를 독립 재계산했다. 원천 CSV 해시·바이트는 유지했다. 정상 완주·후속 출전 선택과 미관측 건강·휴양사유·시간변동 능력이 남으며, 모든 복귀마의 인과적 회복·개인별 최적 복귀 순번·고정초/입상가산·새 예측 개선·운영 반영은 확정하지 않았다. DB접속/쓰기·외부수집 없이 완료했고 기수 전체·각질 추후 재개 상태를 유지했다.

## 앞선 개인 평소주기 연구

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text();s=s.replace('2026년 10월 15일 기준.','2026년 10월 16일 기준.',1)
 s=s.replace('공동 입상관계 비교·조교사별 수행과 변경 전후 비교다.','공동 입상관계 비교·조교사별 수행과 변경 전후·출전 간격·개인 평소주기·장기 공백 복귀 순번 비교다.',1)
 line=next(v for v in s.splitlines() if '| [출전 간격과 성적 변화]' in v)
 s=s.replace(line,'| [출전 간격과 성적 변화](25_START_INTERVAL.md) | 복귀 후 전체기간 일부 개선, 최근 반복·전체 복귀마 회복·개인 적정주기 미확정 | 간격·개인주기·복귀 순번 연구 저장, 운영 미반영 |')
 s+=f'\n[장기 공백 복귀 첫째·둘째·셋째 경주]({link}): 91일 이상 공백·관찰120일, 동일거리 정상3회1,034사례. 전체 둘째 기록+0.125초/셋째 환산착순+0.405위·Top3+6.02%p 조정 연관. 최근 반복0개·첫째둘째 쌍비교 약화·출전 선택이 남아 고정 복귀 가산 미채택.\n'
 p.write_text(s)
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n복귀 순번 후속: [장기 공백 뒤 첫째·둘째·셋째 경주]({link}) — 91일 이상, 추적120일·회차 간60일, 첫 복귀2026-05-22까지. 동일거리 정상3회 전체1,034/2024~25년272/2026년48사례. 능력·편성 조정 후 전체 일부 개선, 최근 반복0개. 출전 선택·쌍비교·181일 이상·최근폼·H1 추가효과와 지원 보완을 보존, 고정가산·운영 미채택.\n')
 topic=next(v for v in reg['topics'] if v['id']=='start_interval');prior=topic['latest_source']
 topic.update(d,latest_source=link,previous_personal_cycle_source=prior)
 topic['layoff_return_followup']={**d,'source':link,'raw_balanced_top3_percent':[28.046422,28.336557,31.528046],'adjusted_all_seconds_faster_second_vs_first':0.124559,'adjusted_all_rank10_better_third_vs_first':0.404549,'adjusted_all_top3_pp_third_vs_first':6.021292,'survivor_selection_remains':True,'pair12_all_episodes':2014,'pair12_seconds_faster_second_vs_first':0.046893,'H1_additional_stage_effect_supported':False}
 for v in topics:
  if v['id']!='start_interval':assert next(x for x in reg['topics'] if x['id']==v['id'])==v
 reg.update(updated_at='2026-10-16',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json'])
 save(HERE/'artifact_manifest.json',{'status':'completed_verified_layoff_return_observational_research','files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'listed_files':len(files),'listed_bytes':sum(p.stat().st_size for p in files),'excludes':'self and final publication receipt'})
 files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed or r['path']==external:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files]
 assert not {r['path'] for r in rows}&{r['path'] for r in old};m['files']+=rows
 m.update(updated_at='2026-10-16',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status'])
 m['verification'].update(status='passed_layoff_return_publication',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),previous_entries_verified_before_current_publication=len(old),all_previous_nonmanagement_source_entries_unchanged=False,all_previous_research_output_files_unchanged=True,layoff_return_management_paths_changed=sorted(changed),layoff_return_preexisting_external_index_drift=[drift],layoff_return_external_index_content_changed_by_this_study=False)
 m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in m['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed and r['path']!=external:
   assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 assert sha(ep)==drift['observed']['sha256'] and ep.stat().st_size==drift['observed']['bytes']
 links=0
 for p in [HERE/'README.md',HERE/'PUBLICATION_PROVENANCE.md',c/'25_START_INTERVAL.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:
    assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'prior_entries_preserved_except_four_management_updates_and_one_external_index_metadata_refresh':len(old)-5,'all_previous_research_output_files_unchanged':True,'preexisting_external_index_drift':drift,'external_index_previous_content_reconstructed_exactly':True,'external_index_content_changed':False,'other_topic_objects_preserved':len(topics)-1,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'central_entries_verified':len(m['files']),'central_manifest_sha256':sha(mp),'prepublication_management_hashes':before,'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[mp]},'local_links_verified':links,'database_opened':False,'database_written':False,'jockey_and_style_pause_preserved':True,'operationally_applied':False})
 print('Layoff return study published and verified',len(files),'files',len(m['files']),'central entries',flush=True)
if __name__=='__main__':main()
