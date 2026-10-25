"""Publish the requested narrow trainer/rider switch follow-up without reopening paused work."""
import json,re,shutil
from data import HERE,ROOT,save,sha
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for p in [HERE/'verification02/verification.json',HERE/'report_verification.json']:assert json.loads(p.read_text())['status']=='passed'
 central=ROOT/'jeju/research/conclusions';mp=central/'source_manifest.json';manifest=json.loads(mp.read_text());old=json.loads(json.dumps(manifest['files']));reg=json.loads((central/'research_register.json').read_text());oldtopics=json.loads(json.dumps(reg['topics']));d=json.loads((HERE/'decision.json').read_text())
 paths=[central/f for f in ['20_TRAINER_PROFILE.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths}
 for r in old:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 snapshot=HERE/'publication_snapshot';snapshot.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snapshot/p.name)
 pre={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]};link='../'+HERE.name+'/README.md'
 p=central/'20_TRAINER_PROFILE.md';s=p.read_text();head,body=s.split('\n\n',1)
 new=f'''최신 [마방별 특정 기수 교체 후속]({link})은 **원시 입상률이 반복 상승한 조합은 있지만,말의 기대수행·직전 부진·기수 기본 성적을 고려한 교체 특이 우세와 승부 의도는 미확정**이라는 결과다. 고정 교체 가산점·승부 라벨·운영 반영은 없다. 앞선 조교사 기본 연구는 아래에 유지한다.

## 마방별 기수 교체 후속

2017-01-13~2026-09-19 원천52,155출전에서 같은말·조교사·마주 및2~90일인43,024선택출전쌍·2,516두,기수변경18,231건·조교사25명×기수40명의674조합을 확인했다.2026부분연도다. 원시표는2017~2026이며,양쪽 연도고정H1예측이 있는 조정비교는2024~2025년9,970/2026년3,702쌍이다. 선택 밖 실제 출전이 중간에 있을 수 있다.

원시Top3는 이준호→박성광2024~2025년21/57(36.8%)→39/57(68.4%),2026년6/23(26.1%)→12/23(52.2%)였다. 이태용→박성광은41/99(41.4%)→61/99(61.6%),2026년20/41(48.8%)→24/41(58.5%)였다. 이준호→문현진도 두 기간 원시상승 방향이다. 설명용 사후 후보이며 보정된 확정 규칙이 아니다.2026년 이준호→박성광의 원시+26.1%p 날짜95%구간은−4.2~56.4%p로 넓고,기대초과 기록 전후변화는−0.071초였다. 입상이 늘어도 새 기수·말의 기대를 넘는 기록 향상과 같지 않다.

같은마방의 다른교체 대비와 같은마방×기수의 유지 대비를 분리했다. 직전H1오차·입상·상대기록,현재H1기대·과거 말 수행,365일 신구기수성적 및차이,부담·체중·함수율·게이트 변화,공백과거리/등급·시기를 고려했다. 기간별20교체·20유지 등의 공통지원은42/9조합,일부자유도보류후186주검정을 날짜/말군집95%와BH로평가했고 긍정지원0개·최근반복확정0개였다. 박병진→박재희는 두 기간 점추정 방향이 유리하나 미확정이다.

유지기승이 적은 기수도 빠뜨리지 않기 위해 모든 적격 다른교체 비교를 탐색후속으로 확대했다.65/14지원조합·156검정의 별도BH에서도 긍정지원0개였다.2026년 이준호→박성광의 다른교체 대비 기록+0.149초(날짜95%−0.426~0.724·말−0.463~0.762초),Top3+7.3%p(날짜−24.6~39.3·말−21.4~36.1%p)로 불확실했다. 해당 조합은유지8건에불과해 유지20건주지원은 충족하지 못했다.

기수변경 자체나 특정 조합을 승부 의도로 확정하지 않는다. 관계자의 결정·교체사유·가용성·준비 상태가 없고 평균회귀와 선택이 남는다. 기존 상향교체의 평균 관찰연관은 유지하되 모든마방의 공통규칙으로 확장하지 않는다. 신규 교체피처의 이후 예측 추가 개선은 학습하지 않았다. 후향 개발자료 재사용이며 독립 미래 검증과 공개시각 재생이 아니다.

25마방의전체원표·기간87행요약·530원시전후구간과모든지원/보류를 원 연구에 저장했다.43,024연결·1,867지원행·3,119원표행·364목표대비를 확장최소제곱과군집공분산으로재계산했다.최종input01/analysis01/supplement02/report03/verification02이며 표조립·ID표시 정정이력과불변효과 확인을 함께 보존한다. DB접속·쓰기·운영변경 없고 기수전체/각질연구의추후재개상태는 유지한다.

## 앞선 조교사 기본 연구

'''
 p.write_text(head+'\n\n'+new+body)
 p=central/'README.md';s=p.read_text();oldline=next(v for v in s.splitlines() if '| [조교사 특성과 말의 수행 개선]' in v);s=s.replace(oldline,'| [조교사 특성과 말의 수행 개선](20_TRAINER_PROFILE.md) | 마방별 특정기수 교체의 원시 상승 후보 관측, 조정 후 반복 승부조합 미확정 | 교체 후속 완료, 고정 가산점·운영 미반영 |');p.write_text(s)
 p=central/'SOURCES.md';s=p.read_text();assert link not in s;p.write_text(s+f'\n후속: [{HERE.name}]({link}) — 동일마방·마주에서특정기수교체와다른교체/유지비교. 원시2017~2026,조정2024~2026.186주검정·156탐색A검정에서확정긍정없음. 최종supplement02/report03/verification02,승부의도·고정가산·운영미채택.\n')
 topic=next(t for t in reg['topics'] if t['id']=='trainer_profile');previous=topic['latest_source'];topic.update(d,latest_source=link,previous_source=previous,initial_trainer_effects_source='../20261010_trainer_effects_v1/README.md')
 for t in oldtopics:
  if t['id']!='trainer_profile':assert next(v for v in reg['topics'] if v['id']==t['id'])==t
 reg.update(updated_at='2026-10-11',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(central/'research_register.json',reg)
 files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']]
 entries=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)];save(HERE/'artifact_manifest.json',{'status':'completed_verified_observational_research_only','files':entries,'listed_files':len(entries),'listed_bytes':sum(r['bytes'] for r in entries),'excludes':'self and final publication receipt'});files.append(HERE/'artifact_manifest.json')
 for r in manifest['files']:
  if r['path'] in changed:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 newrows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)];assert not {r['path'] for r in old}&{r['path'] for r in newrows};manifest['files']+=newrows
 manifest.update(updated_at='2026-10-11',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);manifest['verification'].update(status='passed_stable_rider_switch_followup_publication',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),previous_entries_verified_before_current_publication=len(old),all_previous_nonmanagement_source_entries_unchanged=True,stable_rider_switch_management_paths_changed=sorted(changed));manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in manifest['files']);save(mp,manifest)
 for r in manifest['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 links=0
 for p in [HERE/'README.md',central/'20_TRAINER_PROFILE.md',central/'README.md',central/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'prior_entries_unchanged_excluding_four_management_files':len(old)-len(changed),'all_other_topic_objects_preserved':len(oldtopics)-1,'jockey_and_style_pause_preserved':True,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'central_entries_verified':len(manifest['files']),'central_manifest_sha256':sha(mp),'local_links_verified':links,'prepublication_management_hashes':pre,'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[mp]},'no_database_or_operational_changes':True})
 print('Stable rider switch publication passed',len(files),'new files',len(manifest['files']),'central entries',flush=True)
if __name__=='__main__':main()
