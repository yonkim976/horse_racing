"""Register the follow-up while retaining all earlier research and pause states."""
import json,re
from data import HERE,ROOT,sha,save

def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 assert json.loads((HERE/'verification02/verification.json').read_text())['status']=='passed'
 central=ROOT/'jeju/research/conclusions';mp=central/'source_manifest.json';manifest=json.loads(mp.read_text())
 for r in manifest['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 frozen=[r for r in manifest['files'] if r['role']!='conclusion_or_management']
 link='../'+HERE.name+'/README.md';oldlink='../20261009_jockey_effects_v1/README.md';decision=json.loads((HERE/'decision.json').read_text())
 p=central/'08_JOCKEY_PROFILE.md'
 p.write_text(f'''# 기수 특성과 좋은 말 배정 및 추가 기여

최신 결과는 [추입 수행·상위기수 교체·기승 특성 후속]({link})이다. **상향교체는 좋은 수행과 연결되지만 승부 의도나 변경 결정자는 관측하지 못한다. 추입 특화 기수는 최근 두 기간에 반복 확정되지 않았으며, 박성광의 초반 첫집단 확보만 반복 지지됐다.** 2017-01-13~2026-09-19 정상완주 완전 편성52,155출전·5,206경주·2,813두·기수40명,2026부분연도다. 공식 사건 마주234개ID를 읽기전용 연결했다.

## 말의 추입력을 특별히 살리는가

엄격 추입형은 전체190·2026년29출전으로 작다. T−2 충분한 초반 이력에서 중단·후미60% 이상인 대기 성향9,994출전(2026년919)을 함께 연구했다. 말×정확거리·경주 효과와 과거 후반 수행·부담·체중·게이트·조교사를 고려한 기수 주효과 및 대기 성향 상호작용을 분리했다. 전체기간 일부 기수의 대기 성향 수행은 좋았지만 일반 우세를 넘는 특이적 차이는 확정되지 않았고2026년 지지된 후반 대비도 없었다. 임재광의 G3F 좋은 방향 점추정은 보존하되 다중비교 후 미확정이다. 추입 전문이 없다는 증명이나 모든 말의 추입력 부재가 아니다.

## 상위기수로 교체하면 승부경주인가

상위는 경주T−2까지365일 선정출전100회 이상 기수 중 Top3율75백분위 이상이다. 새 기수가 상위이면서 이전보다 같은 과거창 Top3율5%p 이상 높으면 상향교체로 정의했다. 원시 성적 기준이므로 배정과 최근 폼이 포함된다. 동일 말의 직전 선정출전2~90일 쌍이며 선정 밖 출전이 사이에 있을 수 있다.

조교사·마주가 유지된2024~2025년 상향교체919출전의 Top3는40.8%, 그 외 교체2,760출전은23.3%였다.2026년 상향347출전은 직전 선정출전28.5%→현재39.5%, 그 외985출전은21.9%→25.0%였다. 원시 전후 차이는 회귀평균과 배정 선택을 포함한다.

과거 수행·직전 부진·기대수행·거리와 조건 변화·관계자ID를 고려한 상향 vs 기타교체 차이는 기수 정보를 포함한 H1기대 기준으로 상대기록이2024~2025년+0.267초,2026년+0.230초 좋은 방향이었다.2026년 날짜95%구간+0.083~+0.376초,말+0.085~+0.374초,BH q=0.0035다. H1 입상 차이는+10.1%p→+3.7%p이며2026년 구간이0을 포함해 반복 확정되지 않았다. 이 차이는 개별 기록 보정이나 전체 예측 MAE 개선량이 아니다.

상향교체의 수행 연관은 있지만 변경 결정자·이유·준비 상태·승부 의도 자료가 없다. H1의 최근 기수 폼 누락이나 배정 차이로도 잔차가 남을 수 있다. 따라서 승부경주 확정, 관계자별 승부 성향, 교체의 인과효과로 표시하지 않는다.2026년 관계자별 최소교체30/상향10 지원은 조교사14개·마주0개ID이며 기술표만 보존했다. 새 교체 신호의 예측 추가 개선이나 운영 적용은 검증하지 않았다.

## 기승 스타일과 앞선 기수 연구

측정 축은 초반 첫집단 확보·후반 확실 전진·G3F 상대 수행이다. 현재100출전 이상17명 전원의 원시·조정·구간·분모를 원 연구에 보존했다. 박성광은 첫집단+8.1%p(2024~2025)·+18.1%p(2026)로 반복 지지돼 초반 자리 확보 후보다. 임재광의 초반/후반전진,전현준·문현진·김홍권의 G3F 우세는2024~2025년 한정 신호다. 전 기수를 선행·선입·추입 전문으로 강제 분류하지 않는다. 첫집단은 단독 선두나 선행 의도가 아니고 G3F 우세도 추입과 동일하지 않다.

[앞선 기수 효과 연구]({oldlink})는 좋은 말 배정의 차이와 기수 정보의 작은 반복 예측 개선을 확인했다. 박성광 기록 기여는2024~2025년+0.556초·2026년+0.463초의 빠른 방향이었다. 전체 상대기록 MAE는 기수ID 추가로0.9513→0.9403초,0.8924→0.8845초로 개선했고 Top3 logloss도 개선됐다. 말×기수 별도 상호작용은 추가 개선이 없어 미채택이다. 상대기록 예측이며 절대 완주시간 예측이나 순수 기수 능력의 정확한 식별은 아니다.

이전 [자료지원 감사와 설계](../20261009_jockey_research_feasibility_v1/README.md),앞선 효과 원본은 보존한다. 후속 검증은 이력·과거기수창·교체정의·FE대비·군집구간·별도 최소제곱 해·BH를 재계산했다. DB·운영모델·고정초/확률가산 변경은 없다. [각질·편성 연구](07_RUNNING_STYLE.md)는 사용자 지정 저장 후 추후 재개 상태를 유지한다.
''')
 p=central/'README.md';text=p.read_text();old=next(s for s in text.splitlines() if '| [기수 특성과 좋은말 배정]' in s)
 text=text.replace(old,'| [기수 특성과 좋은말 배정](08_JOCKEY_PROFILE.md) | 상향교체의 좋은 수행 연관·승부 의도 미확인. 추입 특화 미확정, 박성광 초반 확보 반복 | 후속 조건부 비교 완료, 고정 스타일·교체 신호 운영 미채택 |');p.write_text(text)
 p=central/'SOURCES.md';text=p.read_text();assert link not in text
 p.write_text(text+f'\n후속: [{HERE.name}]({link}) — 기수×사전 대기 성향의 후반 수행, T−2 과거365일 상위기수 상향교체와 H0/H1 기대 초과, 사건 조교사·마주 유지 비교,17명 기승 특성 정리. 승부 의도·추입 전문 미확정, 교체 신호 운영 적용 없음.\n')
 p=central/'research_register.json';reg=json.loads(p.read_text());reg['updated_at']='2026-10-09'
 assert next(t for t in reg['topics'] if t['id']=='running_style')['user_work_phase']=='current_findings_saved_revisit_later_2026_10_09'
 topic=next(t for t in reg['topics'] if t['id']=='jockey_profile');topic.update(decision,latest_source=link,initial_jockey_effects_source=oldlink);save(p,reg)
 files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']]
 entries=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
 save(HERE/'artifact_manifest.json',{'status':'completed_verified_research_only','files':entries,'listed_files':len(entries),'listed_bytes':sum(r['bytes'] for r in entries),'excludes':'self and final publication receipt'})
 files.append(HERE/'artifact_manifest.json')
 for r in manifest['files']:
  if r['role']=='conclusion_or_management':
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 new=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
 assert not {r['path'] for r in manifest['files']}&{r['path'] for r in new};manifest['files']+=new
 manifest['verification'].update(status='passed',all_previous_source_hashes_unchanged=True,latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)))
 manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in manifest['files']);save(mp,manifest)
 for r in manifest['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 links=0
 for p in [HERE/'README.md',central/'08_JOCKEY_PROFILE.md',central/'README.md',central/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),target;links+=1
 save(receipt,{'status':'passed','prior_immutable_files_verified':len(frozen),'new_source_files':len(files),'new_source_bytes':sum(p.stat().st_size for p in files),'central_manifest_entries_verified':len(manifest['files']),'central_manifest_sha256':sha(mp),'local_links_verified':links,'management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in [central/'08_JOCKEY_PROFILE.md',central/'README.md',central/'SOURCES.md',central/'research_register.json',mp]},'no_database_or_operational_model_changes':True,'intent_observed':False})
 print('Publication passed',len(files),'new files;',len(frozen),'prior sources unchanged',flush=True)
if __name__=='__main__':main()
