"""Add the interval topic, retaining every existing topic and immutable study."""
import copy,json,re,shutil
from data import HERE,ROOT,save,sha
def main():
 receipt=HERE/'publication_verification.json';assert not receipt.exists()
 for p in [HERE/'verification01/verification.json',HERE/'report01/verification.json']:assert json.loads(p.read_text())['status']=='passed'
 c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';m=json.loads(mp.read_text());old=copy.deepcopy(m['files']);reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics']);d=json.loads((HERE/'decision.json').read_text())
 paths=[c/v for v in ['README.md','SOURCES.md','research_register.json']];changed={str(p.relative_to(ROOT)) for p in paths};newdoc=c/'25_START_INTERVAL.md';assert not newdoc.exists() and not any(t['id']=='start_interval' for t in topics)
 for r in old:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 snap=HERE/'publication_snapshot';snap.mkdir(exist_ok=False)
 for p in paths+[mp]:shutil.copyfile(p,snap/p.name)
 before={str(p.relative_to(ROOT)):sha(p) for p in paths+[mp]};link='../'+HERE.name+'/README.md'
 newdoc.write_text(f'''# 제주마 출전 간격과 성적 변화

최신 [출전 간격 연구]({link})에서는 **8~14일 간격이15~28일보다 우세한 조건부 연관이2024~2025년과2026년에 반복됐다.** 개인별최적주기나일찍재출전시키는인과효과를확정한것은아니다. 고정초·입상가산·운영반영은없다.

## 표본과 주기

2017-01-13~2026-09-19 정상완주완전편성52,155출전·5,206경주·2,813두에서보유원장의직전관측출전을확인한50,209출전·2,638두를분석했다. 중앙간격21일,사분위14~34일,평균35.94일이다. 현재8거리·원천7~13두,400m/제외말미편입,2026은09-19부분연도다. 직전미관측1,946건은신마나0일로대입하지않았다.

직전연결은선정경주끼리만하지않고2002~2026제주후보원장에서같은공식말ID의정상착순또는실제출전코드91/92를찾았다. 현재코호트말의66,619원행중65,269관측출전을사용하고취소/제외/미확정코드1,350행은실제출전으로추정하지않았다. 기존선정코호트간격과다른3,798건을정리했다. 보유원장밖경력누락가능성이있어완전한생애직전출전은아니다.

## 조건을 고려한 결과

경주및말×정확거리효과에말의최근착순·상대기록·이력수·직전성적,부담·체중·게이트·기수·조교사를고려했다. 경주효과는편성·등급·함수율·월·공통환경/페이스를흡수한다. 간격을이미쓴H1예측및간격변수는주조정에서제외했다. 기록은편성평균대비상대기록이다.

| 8~14일 대15~28일 | 기록 우세 | 10두 환산 착순 우세 | Top3 차이 |
| --- | ---: | ---: | ---: |
| 전체기간 | 0.153초 | +0.334위 | +3.90%p |
| 2024~2025 | 0.113초 | +0.248위 | +3.52%p |
| 2026 부분연도 | 0.200초 | +0.511위 | +6.88%p |

2026날짜95%구간은각각0.086~0.315초 / +0.176~+0.845위 / +1.27~+12.50%p,말95%는0.085~0.316초 / +0.188~+0.834위 / +0.69~+13.08%p다. 2024~2025도양쪽군집구간이같은방향이고전체거리57주검정BH를통과했다. 말효과단위변경/과거성적통제제외민감도도같은방향이었다. 이는미래개별확률에더하는가산점이아니다.

2026원시성적은8~14일1,249건평균5.04위·Top3 33.1%,15~28일1,713건5.28위·31.2%,29~42일353건5.59위·27.5%,43~60일263건5.49위·31.2%,61~90일384건5.50위·31.3%,91~180일394건5.56위·32.0%,181일이상126건5.90위·25.4%다. 181일이상은직전7.82위에서평균1.91위개선됐지만다른주기군대비우세를뜻하지않는다. 공백전부진·평균회귀·능력배정차이를구분한다.

29일이상은전체기간기록에서느린연관이있었으나최근일정한불리방향은대부분미확정이다. 장기공백의일괄감점근거로채택하지않는다. 최근2024~2026선정코호트1~7일표본은0으로과거1,974건의결과를최근에확장하지않는다. 실제휴양/부상원인은미관측이다.

## 거리별 범위와 한계

전체기간8~14일기록우세는900/1000/1110m에서거리별189검정BH지원을받았다. 800/1200/1300/1400m는미확정,1610m는84출전·9경주로보류다. 거리별최근두기간반복지원은0개이며2026년800/1300/1400/1610m모형은표본부족으로보류했다. 전체거리계수를각거리의확정초보정으로복사하지않는다. 거리별각군표본·말수·날짜·구간·소표본은원연구전체표를따른다.

좋은상태의말을일찍재출전시키는선택,컨디션·관리·공백사유가남는다. 정상완주원천조건부로사고/미완주/취소위험전체를평가하지않는다. 과거입력T−2·최대10회/730일,현재선언/체중등게시시각가정,같은과거기간재사용이다. 독립미래검증·개인최적주기·신규예측추가개선은미확인이다.

## 검증과 연결

APIID/해시/착순/시간/두수와52,155직전연결을대조했다. SQL LAG와별도말별순회,원시34기간셀의구간,27적합81목표모형의합동고정효과정규방정식·군집공분산·513지원효과행·두BH가족을독립재계산했다.6개모형보류도저장했다. DB읽기전용·원천해시전후불변,기존기수전체/각질의추후재개상태유지다. [최근경기력](05_RECENT_FORM.md)·[마체중/부담](04_WEIGHT_SPEED.md)은별도연구다.
''')
 p=c/'README.md';s=p.read_text();s=s.replace('2026년 10월 11일 기준.','2026년 10월 15일 기준.',1);needle='| [원 연구와 버전 목록](SOURCES.md)';i=s.index(needle);s=s[:i]+'| [출전 간격과 성적 변화](25_START_INTERVAL.md) | 8~14일의15~28일 대비 조건부 우세가 최근 두기간 반복, 거리별 반복·개인 최적주기는 미확정 | 관찰연구 완료, 고정 보정·운영 미반영 |\n'+s[i:];p.write_text(s)
 p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n새 주제: [제주마 출전 간격과 성적 변화]({link}) — 직전관측50,209출전,중앙21일.8~14일 대15~28일의최근두기간 기록/환산착순/Top3조건부우세.전체거리57/거리별189검정,개인최적·고정가산·운영미채택.\n')
 reg['topics'].append({'id':'start_interval','title':'제주마 출전 간격과 성적 변화','conclusion':newdoc.name,'latest_source':link,**d});reg['scope']+='·출전 간격과 성적 변화'
 for oldtopic in topics:assert next(t for t in reg['topics'] if t['id']==oldtopic['id'])==oldtopic
 reg.update(updated_at='2026-10-15',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);save(c/'research_register.json',reg)
 files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json'])
 save(HERE/'artifact_manifest.json',{'status':'completed_verified_observational_interval_research','files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'listed_files':len(files),'listed_bytes':sum(p.stat().st_size for p in files),'excludes':'self and final publication receipt'});files.append(HERE/'artifact_manifest.json')
 for r in m['files']:
  if r['path'] in changed:
   p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
 rows=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in files];rows.append({'path':str(newdoc.relative_to(ROOT)),'role':'conclusion_or_management','sha256':sha(newdoc),'bytes':newdoc.stat().st_size});assert not {r['path'] for r in rows}&{r['path'] for r in old};m['files']+=rows
 m.update(updated_at='2026-10-15',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status']);m['verification'].update(status='passed_start_interval_publication',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),previous_entries_verified_before_current_publication=len(old),all_previous_nonmanagement_source_entries_unchanged=True,interval_management_paths_changed=sorted(changed),new_topic_document=str(newdoc.relative_to(ROOT)))
 m['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in m['files']);save(mp,m)
 for r in m['files']:
  p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
 for r in old:
  if r['path'] not in changed:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 links=0
 for p in [HERE/'README.md',newdoc,c/'README.md',c/'SOURCES.md']:
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
 save(receipt,{'status':'passed','prior_entries_verified':len(old),'prior_unchanged_except_three_management_files':len(old)-3,'all_existing_topic_objects_preserved':len(topics),'new_study_files':len(files),'new_study_bytes':sum(p.stat().st_size for p in files),'new_conclusion_bytes':newdoc.stat().st_size,'central_entries_verified':len(m['files']),'central_manifest_sha256':sha(mp),'prepublication_management_hashes':before,'updated_management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in paths+[newdoc,mp]},'local_links_verified':links,'jockey_and_style_pause_preserved':True,'database_read_only':True,'operationally_applied':False})
 print('Interval study published and verified:',len(files),'files;',len(m['files']),'central entries',flush=True)
if __name__=='__main__':main()
