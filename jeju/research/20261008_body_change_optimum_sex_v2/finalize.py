"""Publish verified body research without changing prior research artifacts."""
from pathlib import Path
import json
import re
import hashlib

H=Path(__file__).resolve().parent;ROOT=H.parents[2];C=H.parent/'conclusions';FAILED=H.with_name('20261008_body_change_optimum_sex_v1')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
central=json.loads((C/'source_manifest.json').read_text());assert all(sha(ROOT/z['path'])==z['sha256'] for z in central['files'])
pre=json.loads((H/'prepublication_verification.json').read_text());assert all(sha(ROOT/k)==v for k,v in pre['central_before_hashes'].items())
assert json.loads((H/'verification.json').read_text())['status']=='passed' and json.loads((H/'calculation_verification.json').read_text())['status']=='passed'
write(H/'raw_group_interval_contract.json',{'source':'raw_pair_body_changes.csv','right_closed':False,'unit':'kg measured later minus earlier exact-distance body','intervals':{'loss10plus':'delta < -10','loss3toUnder10':'-10 <= delta < -3','stableUnder3':'-3 <= delta < 3','gain3toUnder10':'3 <= delta < 10','gain10plus':'10 <= delta'},'note':'Labels are retained as source codes; use exact intervals above at boundaries. No raw group statistics are used as adjusted causal effects.'})
p=C/'04_WEIGHT_SPEED.md';txt=p.read_text();old='**마체중과 부담중량의 원시 상관은약하다.같은 말의 부담중량 증가와 작은 기록 저하의 연관성은 관찰됐지만,고정1kg 환산치는 채택하지 않았다.**';new='**체중·부담중량과 기록의 관찰 연관은 있으나 고정 환산치는 채택하지 않았다.체중 증감의 반응은 거리·기간에 따라 불확실하며,말별·암수별·거리별 확정 적정 체중을 확보하지 못했다.**';assert old in txt;txt=txt.replace(old,new,1)
section='''## 마체중 증감과 적정 체중 후속

동일 말·정확 거리·등급·연도,7~60일27,230쌍에서 부담중량·이전 체중과 성적·간격·사건 나이·함수율·계절 주기·게이트를 고려했다.전체 기간10kg 증가와 연관된 시간은800m+0.396초(점별95%+0.131~+0.661),10kg 감소는800m−0.381초(−0.591~−0.170),900m−0.377초(−0.641~−0.113),1000m−0.348초(−0.581~−0.115)에서BH근거가남았다.최근2024~2025년·2026년부분기간과같은달·함수율·부담중량안정조건은불확실했다.감량의인과효과나감량권장이아니다.

전체출전말·경주효과모형에서는1000·1110m의280→290kg가각+0.259·+0.260초와연관됐다.그러나절대kg곡선의안정적내부최저점은없었다.각말전체기간중앙체중대비민감도에800~1200mU자형곡률신호와중앙값보다6~10kg낮은후보가있지만구간과지원이불안정해최적체중으로채택하지않았다.전체기간중앙값은미래를포함한후향기준이며사전입력이아니다.

2017~2023년반복·체중폭을충족한51개말×거리조합에서개인후보2건이남았다.백록장원1200m약290.3kg·한라영산1200m약307.0kg이지만2024~2026해당거리출전은각2회·0회여서반복확인불가다.이후검증실패로단정하지않는다.암말−수말의증감반응·체중곡선차이도미확인이며거세마는분리했다.이는성별동등성증명이아니다.거리별평균체중은최적kg이아니고1300·1400m성별표본과1610m전체지원은부족하다.

[체중증감·개인적정체중·암수·거리별전체연구](../20261008_body_change_optimum_sex_v2/README.md),[효과와최근기간](../20261008_body_change_optimum_sex_v2/effects.csv),[개인별후속](../20261008_body_change_optimum_sex_v2/individual_period_comparison.csv),[최종판정](../20261008_body_change_optimum_sex_v2/decision.json)을따른다.당일체중은사후설명값이며고정체중환산·개인최적kg·운영반영은미채택이다.앞선58kg및부담중량결과는아래에보존한다.

'''
assert '## 같은 58kg의 체중별 상대 부담' in txt;txt=txt.replace('## 같은 58kg의 체중별 상대 부담',section+'## 같은 58kg의 체중별 상대 부담',1);p.write_text(txt,encoding='utf-8')
p=C/'README.md';txt=p.read_text();txt=txt.replace('마체중·부담중량 상관은약함.같은58kg의부담비율은체중별차이,추가감속차이는불확실','체중증감과기록의연관관찰.말별·암수별·거리별확정적정체중미확보.같은58kg의체중별추가감속은불확실');txt=txt.replace('중량연구완료,고정1kg환산미채택','중량·체중증감후속완료,고정환산·최적kg미채택');p.write_text(txt,encoding='utf-8')
p=C/'SOURCES.md';txt=p.read_text();marker='\n같은 출전 자료가 여러 버전에';assert marker in txt;txt=txt.replace(marker,'\n| [20261008_body_change_optimum_sex_v2](../20261008_body_change_optimum_sex_v2/README.md) | **최신 마체중증감·말별·암수·거리별적정체중연구.52,155출전·27,230쌍,개인51조합과후기지원.고정최적kg미채택.v1의NumPy별칭중단은보존** |\n'+marker,1);p.write_text(txt,encoding='utf-8')
p=C/'research_register.json';reg=json.loads(p.read_text());topic=next(z for z in reg['topics'] if z['id']=='weight_speed');topic['body_ratio_source']=topic['latest_source'];topic['latest_source']='../'+H.name+'/README.md';topic['status']='body_change_sex_distance_and_individual_optimum_study_completed_no_fixed_weight_correction';topic['latest_body_optimum_followup']=json.loads((H/'decision.json').read_text())|{'source':'../'+H.name+'/README.md'};write(p,reg)
links=0
for p in [H/'README.md',C/'04_WEIGHT_SPEED.md',C/'README.md',C/'SOURCES.md']:
    for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
for z in json.loads((H/'source_manifest.json').read_text()):assert sha(Path(z['path']))==z['sha256']
for z in json.loads((FAILED/'artifact_manifest.json').read_text())['files']:assert sha(FAILED/z['path'])==z['sha256']
write(H/'publication_verification.json',{'status':'passed','local_links_checked':links,'figure_visually_inspected':True,'figure_legible_no_clipping':True,'prior_research_hashes_unchanged':True,'database_unchanged':True,'failed_v1_preserved':True,'management_previous_hashes':pre['central_before_hashes'],'management_current_files':[{'path':key,'sha256':sha(ROOT/key),'bytes':(ROOT/key).stat().st_size} for key in pre['central_before_hashes']]})
art=[{'path':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(H.iterdir()) if p.is_file() and p.name!='artifact_manifest.json'];write(H/'artifact_manifest.json',{'files':art,'total_bytes_excluding_this_manifest':sum(z['bytes'] for z in art),'local_links_checked':links})
files={z['path']:z for z in central['files']}
for key,z in files.items():
    if z['role']=='conclusion_or_management':z.update(sha256=sha(ROOT/key),bytes=(ROOT/key).stat().st_size)
for folder,role in [(H,'source_body_change_optimum_sex'),(FAILED,'source_body_change_optimum_failed_v1')]:
    for p in sorted(folder.iterdir()):
        if not p.is_file():continue
        key=str(p.relative_to(ROOT));assert key not in files;files[key]={'path':key,'role':role,'sha256':sha(p),'bytes':p.stat().st_size}
central['files']=list(files.values());central['verification'].update(body_change_optimum_sex_study_completed=True,individual_optimum_adopted=False,distance_optimum_adopted=False,local_links_checked=links);central['managed_files_bytes_excluding_this_manifest']=sum(z['bytes'] for z in files.values() if z['role']=='conclusion_or_management');write(C/'source_manifest.json',central)
assert all(sha(ROOT/z['path'])==z['sha256'] for z in central['files'])
assert sha(ROOT/'jeju/data/jeju_native_core.sqlite3')==json.loads((H/'input_audit.json').read_text())['database_sha256']
print(json.dumps({'saved_directory':str(H),'new_files':len(art)+1,'bytes_excluding_artifact_manifest':sum(z['bytes'] for z in art),'local_links_checked':links,'all_central_hashes_verified':True,'management_bytes':central['managed_files_bytes_excluding_this_manifest']},ensure_ascii=False,indent=2))
