"""Publish personal cycle follow-up while preserving the absolute-gap research."""
import copy,json,re,shutil
from data import HERE,ROOT,save,sha
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for p in [HERE/'verification01/verification.json',HERE/'personal_verification01/verification.json',HERE/'report01/verification.json']:assert json.loads(p.read_text())['status']=='passed'
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics']);d=json.loads((HERE/'decision.json').read_text())
 paths=[c/v for v in ['25_START_INTERVAL.md','README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths}
 for r in old:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]};link='../'+HERE.name+'/README.md'
 p=c/'25_START_INTERVAL.md';s=p.read_text();head,body=s.split('\n\n',1);body=body.replace('최신 [출전 간격 연구]','앞선 [절대 출전간격 연구]',1)
 add=f'''최신 [개인 평소주기 이탈과 적정주기 후보]({link})에서는 **절대간격을고려한개인주기이탈의최근반복우세와개인별적정주기를확정하지못했다.** 평소주기와과거좋았던구간후보는별도정보로저장했다. 앞선8~14일의전체조건부우세를개인최적주기로확장하지않는다.

## 개인 평소주기 대비 수행

각경주T−2까지끝난최근5개간격의중앙값(종료최근730일·최소3개)을평소주기로계산했다. 현재간격/평소간격이0.75미만은짧음,0.75~1.25는평소,1.25초과~2는김,2초과는매우김이다. 현재간격은과거중앙값에포함하지않았다.2017-01-13~2026-09-19 원천52,155출전에서44,720출전·2,246두가충족했다. 직전미관측1,946건·평소주기이력부족5,489건은분리했다.2026은09-19부분연도·현재8거리·원천7~13두·400m/제외말결과미편입이다.

2026출전관측마중상한기준평소주기를계산한809두는중앙21일·사분위15~31일·10~90백분위14~55일로개인차이가있었다. 이최신프로필은09-19완료경주기준이며경주별T−2주기와시점이다르다.2026개인분류3,938출전의짧음1,176건평균4.96위·Top3 34.5%,평소1,309건5.26위·30.7%,김575건5.77위·25.7%,두배초과878건5.79위·27.1%였다.

경주·말거리효과와과거수행·직전성적·부담·체중·게이트·기수·조교사·평소주기수준/흩어짐·절대간격구간을함께고려했다. 전체기간짧음의기록차이는거의0초,김은0.077초·두배초과0.161초느린연관과10두환산0.205/0.347위열세가주BH를통과했다.2026짧음은0.111초빠름이나날짜95%−0.056~+0.278·말−0.057~+0.279초,김은0.177초느림이나날짜+0.006~+0.348·말−0.011~+0.365초,두배초과는0.283초느림이나날짜−0.067~+0.632·말−0.097~+0.662초로불확실하다. 전체거리27/거리별126지원검정에서최근두기간반복은0개다. 최근10개중앙값·절대간격통제제외민감도도보존했다.

## 말별 우수구간 후보와 이후 확인

주기변수없는과거조건모형의잔차로1~7/8~14/15~28/29~42/43~90/91일이상을비교했다. 총20출전·각5회이상인두구간을요구해2023-12-30이전532두,2025-12-30이전708두의과거후보를골랐다.708두중2026선정출전관측은251두이며현재활동마708두라는뜻은아니다. 훈련자료최대값선택은우세확인이아니다.

2024고정후보를바꾸지않고확인한집단H1기대초과기록차이는2024~2025년3,114출전·243두+0.191초(날짜95%+0.031~+0.351·말+0.043~+0.339,BH q0.039),2026년625출전·125두−0.040초(날짜−0.918~+0.838·말−1.062~+0.982,q0.928)로최근반복되지않았다. H1은절대간격·능력·편성등을이미고려한연도고정예상이며새H1을학습하지않았다.

개별말은20출전·일치/비일치각5회기준의2024~2025년35두에서양수BH지원0두,2026최대16/17회로주확인표본미충족이다. 최소10출전·각3회로완화한사후소표본탐색은96+11+31=138적합에서양수BH지원0개였다. 자료부족을효과0으로표시하지않고개인최적을미확정으로남긴다. 전농미르·유달리·청룡여제등예시와전체2,813두프로필에평소주기/훈련후보/이후지원상태를분리했다. 청룡여제의2026소표본+0.590초는날짜구간양수여도BH q0.134로미지원이다.

## 해석과 검증

104,310평소주기창·209현재/미래변경검사·81편차목표모형·5,626훈련후보프로필·173개인주/소표본모형·2집단이후모형을독립재계산했다. 원천과전체표·보류·계수/구간·시점계약을원연구에보존했다. 훈련과이후확인의시간은분리했으나기존역사자료반복사용이며독립새미래검증은아니다. 컨디션·관리·휴양사유와비무작위출전선택이남고정상완주조건부표본이다. 개인별최적확정·고정초/입상가산·새예측추가개선·운영반영은없다. DB접속/쓰기·외부수집없이기수전체/각질추후재개상태를유지했다.

## 앞선 절대간격 연구

'''
 p.write_text(head+'\n\n'+add+body)
 p=c/'README.md';s=p.read_text();line=next(v for v in s.splitlines() if '| [출전 간격과 성적 변화]' in v);p.write_text(s.replace(line,'| [출전 간격과 성적 변화](25_START_INTERVAL.md) | 절대8~14일 우세와 개인평소주기 이탈은 구분, 개인적정주기 미확정 | 개인주기·과거후보·이후확인 저장, 운영 미반영 |'))
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n개인주기 후속: [평소주기 이탈과 말별 적정주기 후보]({link}) — T−2최근5간격 중앙값44,720출전.절대간격고려후최근반복미확정.훈련후보532/708두,개인주/소표본173모형과집단이후2모형에서개인최적/최근반복미확정. 고정가산·운영미채택.\n')
 topic=next(v for v in reg['topics'] if v['id']=='start_interval');prior=topic['latest_source'];topic.update(d,latest_source=link,previous_absolute_interval_source=prior);topic['personal_cycle_followup']={'source':link,'usual_cycle':'T-2 last5 completed intervals /730days /minimum3','latest_historical_candidates':708,'confirmed_individual_optimum':False,'relative_departure_recent_repeated':0,'operationally_applied':False}
 for v in topics:
  if v['id']!='start_interval':assert next(x for x in reg['topics'] if x['id']==v['id'])==v
 reg.update(updated_at='2026-10-15',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json'])
 save(HERE/'artifact_manifest.json',{'status':'completed_verified_personal_interval_observational_research','files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'listed_files':len(files),'listed_bytes':sum(p.stat().st_size for p in files),'excludes':'self and final publication receipt'});files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files];assert not {r['path'] for r in rows}&{r['path'] for r in old};m['files']+=rows
 m.update(updated_at='2026-10-15',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);m['verification'].update(status='passed_personal_start_interval_publication',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),previous_entries_verified_before_current_publication=len(old),all_previous_nonmanagement_source_entries_unchanged=True,personal_cycle_management_paths_changed=sorted(changed));m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in m['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 links=0
 for p in [HERE/'README.md',c/'25_START_INTERVAL.md',c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'prior_unchanged_except_four_management_files':len(old)-4,'other_topic_objects_preserved':len(topics)-1,'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'central_entries_verified':len(m['files']),'central_manifest_sha256':sha(mp),'prepublication_management_hashes':before,'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[mp]},'local_links_verified':links,'database_opened':False,'jockey_and_style_pause_preserved':True,'operationally_applied':False});print('Personal cycle study published and verified',len(files),'files',len(m['files']),'central entries',flush=True)
if __name__=='__main__':main()
