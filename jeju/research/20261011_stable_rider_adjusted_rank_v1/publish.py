"""Publish conditional rank follow-up; preserve unrelated topics and all old research."""
import copy,json,re,shutil
from data import HERE,ROOT,save,sha
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for p in [HERE/'verification01/verification.json',HERE/'supplement_verification01/verification.json',HERE/'report01/verification.json']:assert json.loads(p.read_text())['status']=='passed'
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics']);decision=json.loads((HERE/'decision.json').read_text())
 paths=[c/v for v in ['20_TRAINER_PROFILE.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths}
 for r in old:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]};link='../'+HERE.name+'/README.md'
 p=c/'20_TRAINER_PROFILE.md';s=p.read_text();head,body=s.split('\n\n',1);body=body.replace('최신 [마방별 특정 기수 교체 후속]','앞선 [마방별 특정 기수 교체 후속]',1)
 add=f'''최신 [말 능력·편성 고려 후 교체 대 유지의 순위 변화]({link})에서는 **같은 마방×현재 기수의 유지 기승보다 추가 순위 상승이 확인된 조합은 없었다.** 원시 상승은 보존하되,조건부 우세·승부 의도·고정 가산점으로 채택하지 않는다. 효과0의 증명이나 모든 조합의 판정 완료를 뜻하지 않는다.

## 조건을 고려한 순위 변화와 유지 비교

기존43,024선택쌍에서 양쪽H1가용인2024~2025년9,970/2026년3,702쌍을 사용했다. 원천은2017-01-13~2026-09-19,현재8거리·정상완주 완전편성7~13두,400m/제외말미편입이다.2026은09-19부분연도다. 같은말·조교사·마주2~90일의직전선택출전과비교하며실제모든출전의직전과다를수있다.

같은마방×현재기수의 교체/유지를비교하고,직전착순·기대초과수행,전체/동일거리말이력,상대마과거평균착순/기록 및전후변화,현재/이전H1기대와편성내예상시간순위,신구기수365일성적,부담·체중·함수율·게이트·공백·거리/등급·시기를고려했다.20교체/20유지·전체15두/15일·양군각10두/10일지원은41/11조합,개별조건모형잔여자유도까지통과는30/8조합이다.10두환산/실제착순의76주검정에서날짜·말95%및BH긍정0개,두기간반복0개였다. 같은말고정효과·동일거리·다른교체민감도도별도저장했다.

2026년10두환산 유지대비조건부차이(교체/유지)는강영진→김홍권34/149건−0.04위(날짜95%−1.70~+1.62),심도연→임재광20/171건+1.98위(−1.08~+5.05),이태용→박성광41/126건−0.37위(−3.87~+3.13),고영덕→문현진24/123건+3.72위(−0.50~+7.94),박병진→박재희30/94건+2.09위(−0.60~+4.77)였다. 말구간도모두0포함이다. 원시전후상승과다른추정량이며큰점추정은불안정하다. 이준호→박성광/문현진은2026유지8/12건으로지원부족이다. 김대연→곽석과한상배→양민재는개별조건수대비자유도부족으로보류다.

모든지원조합에서조건계수를공통으로둔사후탐색보조41/11조합·104별도BH검정에서도긍정0개였다. 위5조합의보조점추정은+0.59/−0.27/+0.59/−0.53/+0.16위로여러방향이바뀌어견고한교체우세로보기어렵다. 한상배→양민재보조+1.65위(날짜+0.13~+3.17·말+0.25~+3.06)는BH q0.522로미지원이며이전유지7건이라반복미확인이다. 공통계수가정은별도한계이며주분석과혼합하지않는다.

615지원행·258주/민감도목표대비·104공통조건효과를전체말/조합더미확장최소제곱과군집분산으로검증했다. 상대마대용치104,310값·현재/이전예상순위27,344값도원천재계산했다. H1은연도고정연초T−2이전학습,과거입력T−2/10회/730일이며출전선언게시시각재생은아니다. 말잠재능력·컨디션·선택·평균회귀가남고같은기간재사용이다. 인과·승부의도·신규피처미래추가개선미확정,고정가산점·운영미채택,DB접속/쓰기없음,기수전체/각질추후재개상태유지다.

## 앞선 관측 결과

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text();line=next(v for v in s.splitlines() if '| [조교사 특성과 말의 수행 개선]' in v);p.write_text(s.replace(line,'| [조교사 특성과 말의 수행 개선](20_TRAINER_PROFILE.md) | 능력·편성 고려 및 유지 대비 추가 착순 상승 조합 미확정, 표본 보류 포함 | 조건부 착순 후속 완료, 운영 미반영 |'))
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n후속: [말 능력·편성 고려 후 교체 대 유지의 순위 변화]({link}) — 13,672선택쌍,조합별76주검정/공통조건104탐색검정에서긍정지원0·반복0. 전체615지원행,원시/환산순위와말고정효과민감도. 인과/승부의도/고정가산미채택.\n')
 topic=next(v for v in reg['topics'] if v['id']=='trainer_profile');prior=topic['latest_source'];topic.update(decision,latest_source=link,previous_adjusted_switch_source=prior);topic['adjusted_rank_followup']={'source':link,'status':decision['status'],'individual_primary_tests':76,'shared_exploratory_tests':104,'positive_supported':0,'operationally_applied':False}
 for v in topics:
  if v['id']!='trainer_profile':assert next(x for x in reg['topics'] if x['id']==v['id'])==v
 reg.update(updated_at='2026-10-11',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=decision['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json'])
 save(HERE/'artifact_manifest.json',{'status':'completed_verified_adjusted_observational_research','files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'listed_files':len(files),'listed_bytes':sum(p.stat().st_size for p in files),'excludes':'self and final publication receipt'});files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files];assert not {r['path'] for r in rows}&{r['path'] for r in old};m['files']+=rows
 m.update(updated_at='2026-10-11',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=decision['status']);m['verification'].update(status='passed_adjusted_rank_followup_publication',previous_entries_verified_before_current_publication=len(old),latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),all_previous_nonmanagement_source_entries_unchanged=True)
 m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in m['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 links=0
 for p in [HERE/'README.md',c/'20_TRAINER_PROFILE.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'prior_unchanged_except_four_management_files':len(old)-4,'other_topic_objects_preserved':len(topics)-1,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'central_entries_verified':len(m['files']),'central_manifest_sha256':sha(mp),'prepublication_management_hashes':before,'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[mp]},'local_links_verified':links,'jockey_and_style_pause_preserved':True,'database_opened':False,'operationally_applied':False})
 print('Adjusted rank study published and verified:',len(files),'files;',len(m['files']),'central entries',flush=True)
if __name__=='__main__':main()
