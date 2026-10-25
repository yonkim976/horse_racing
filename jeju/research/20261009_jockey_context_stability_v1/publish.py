"""Publish the six-question study and preserve previous research and pause states."""
import json,re
from data import HERE,ROOT,sha,save

def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 assert json.loads((HERE/'verification02/verification.json').read_text())['status']=='passed'
 central=ROOT/'jeju/research/conclusions';mp=central/'source_manifest.json';manifest=json.loads(mp.read_text())
 for r in manifest['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 frozen=[r for r in manifest['files'] if r['role']!='conclusion_or_management']
 link='../'+HERE.name+'/README.md';decision=json.loads((HERE/'decision.json').read_text())
 p=central/'08_JOCKEY_PROFILE.md';text=p.read_text();head,body=text.split('\n\n',1);body=body.replace('최신 결과는 [추입 수행·상위기수 교체·기승 특성 후속]','앞선 추입·교체 결과는 [추입 수행·상위기수 교체·기승 특성 후속]',1)
 new=f'''최신 결과는 [초반 확보·경합 대응·수행 안정성과 조건별 추가 정보]({link})다. **외측·경합·부진 방지의 새로운 전문 기수는 최근 두 기간에 반복 확정되지 않았다. 최근 폼은2024~2025년에 작게 개선됐지만2026년에는 불확실했고,거리·조교사 조합도 반복 추가 개선이 없었다.** 기존 기수 기본 효과와 박성광의 기본 초반 확보 후보는 유지하며 새 전문 태그·고정 가중치·운영 변경은 없다.

## 최신 조건별 연구

2017-01-13~2026-09-19 정상완주 완전 편성52,155출전·5,206경주·기수40명,2026부분연도다. 외측 출전16,156건,사전각질 가용80% 이상 경합가능 분석36,331출전 중 상대선행형2두 이상9,248건이었다. 말×정확거리·경주 고정효과,과거 초반/후반 수행·게이트·상대압력·부담·체중·조교사를 고려하고 일반 기수 우세와 상황 특이적 차이를 분리했다. 두 후기기간 반복 지지된 외측·경합·부진 방지 전문 대비는 없었다. 외측에서도 잘하는 것과 외측 불리를 특별히 상쇄하는 것은 같지 않다.

기수 정보를 포함한 연도 고정 H1예상 상대기록보다1.5초 초과 느린 큰 부진은2024~2025년1,313/12,739=10.3%,2026년420/4,673=9.0%였다. 말·조건·기대수행을 고려한 부진 빈도·폭·절대오차에서 반복 확정된 기수별 우세는 없었다. 이는 차이 부재나 순수 분산 안정성을 증명하지 않는다. 사고·중단 위험 전체의 평가도 아니다.

90/180/365일 최근 폼은 해당 경주T−2 이전의 연도 고정 H0기대초과 수행으로 만들었다. 최소20/40/80관측과n/(n+50)축소를 고정했다. H1에 추가하면2024~2025년 상대기록 MAE0.940326→0.938899초,Top3logloss0.560798→0.558643으로 개선됐지만2026년0.884533→0.884407초·0.569229→0.567696은 구간/BH 기준에서 불확실했다. 거리별 기수ID 추가와 조교사×기수 조합 추가도 반복 개선이 없어 별도 항목은 미채택이다. 개별 거리 전문성이나 호흡이 없다는 증명은 아니다.

평가17,412출전·1,779경주는 모든 모형에서 같고 경주 동일가중이다.3비교×2기간×2주지표의12가설BH와 날짜·말 군집4,000회 구간을 보존했다.24개 설명 모형·1,244개 대비/구간·234,898개 예측·69,892개 최근 폼 창을 재계산했다. 현재17명 프로필·전체 표·원천·코드는 원 연구에 있고 이전 원본은 보존했다. 현재 선언 정보의 공개/변경시각이 검증된 서비스 재생이나 독립 표본은 아니다.

## 앞선 기수 연구와 연결

'''
 p.write_text(head+'\n\n'+new+body)
 p=central/'README.md';text=p.read_text();old=next(s for s in text.splitlines() if '| [기수 특성과 좋은말 배정]' in s)
 text=text.replace(old,'| [기수 특성과 좋은말 배정](08_JOCKEY_PROFILE.md) | 기수 기본 정보 유지. 외측·경합·부진 방지 특화 미확정, 최근 폼은2024~25만 개선 | 여섯 후속 질문 완료, 새 전문 태그·조건 가중치·운영 미반영 |');p.write_text(text)
 p=central/'SOURCES.md';text=p.read_text();assert link not in text;p.write_text(text+f'\n후속: [{HERE.name}]({link}) — 외측 초반확보·사전 선행형 경합가능 편성·큰 기대미달과 기수 차이,기수×거리·T−2 최근폼·조교사×기수의 연도 고정 추가 비교. 최종input02/effects02/verification02. 최근폼2024~25부분기간 개선,새 전문 태그·운영 미채택.\n')
 p=central/'research_register.json';reg=json.loads(p.read_text());reg['updated_at']='2026-10-09';assert next(t for t in reg['topics'] if t['id']=='running_style')['user_work_phase']=='current_findings_saved_revisit_later_2026_10_09'
 topic=next(t for t in reg['topics'] if t['id']=='jockey_profile');previous_source=topic['latest_source'];topic.update(decision,latest_source=link,previous_source=previous_source);save(p,reg)
 files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']]
 entries=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
 save(HERE/'artifact_manifest.json',{'status':'completed_verified_research_only','files':entries,'listed_files':len(entries),'listed_bytes':sum(r['bytes'] for r in entries),'excludes':'self and final publication receipt'})
 files.append(HERE/'artifact_manifest.json')
 for r in manifest['files']:
  if r['role']=='conclusion_or_management':
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 new=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)];assert not {r['path'] for r in manifest['files']}&{r['path'] for r in new};manifest['files']+=new
 manifest['verification'].update(status='passed',all_previous_source_hashes_unchanged=True,latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)));manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in manifest['files']);save(mp,manifest)
 for r in manifest['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 links=0
 for p in [HERE/'README.md',central/'08_JOCKEY_PROFILE.md',central/'README.md',central/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),target;links+=1
 save(receipt,{'status':'passed','prior_immutable_files_verified':len(frozen),'new_source_files':len(files),'new_source_bytes':sum(p.stat().st_size for p in files),'central_manifest_entries_verified':len(manifest['files']),'central_manifest_sha256':sha(mp),'local_links_verified':links,'management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in [central/'08_JOCKEY_PROFILE.md',central/'README.md',central/'SOURCES.md',central/'research_register.json',mp]},'no_database_or_operational_model_changes':True,'previous_style_pause_preserved':True})
 print('Publication passed',len(files),'new files;',len(frozen),'prior sources unchanged',flush=True)
if __name__=='__main__':main()
