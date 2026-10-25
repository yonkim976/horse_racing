"""Archive the completed source and reconcile the established conclusion index."""
import json,re
from analyze import HERE,ROOT,sha,save

def main():
    receipt=HERE/'publication_verification.json';assert not receipt.exists()
    assert json.loads((HERE/'verification01/verification.json').read_text())['status']=='passed'
    central=ROOT/'jeju/research/conclusions';mp=central/'source_manifest.json';manifest=json.loads(mp.read_text())
    frozen=[r for r in manifest['files'] if r['role']!='conclusion_or_management']
    for r in frozen:assert sha(ROOT/r['path'])==r['sha256'],r['path']
    decision=json.loads((HERE/'decision.json').read_text());link='../'+HERE.name+'/README.md'
    p=central/'07_RUNNING_STYLE.md';text=p.read_text();head,body=text.split('\n\n',1);assert link not in text
    intro=f'''최신 입상 연관 후속은 [선행형 말의 실제 초반 위치별 Top3]({link})다. 경주 전 T−2 동일거리 최근10회 중 유효5회 이상·선두집단/확실앞쪽 각각60% 이상인 선행형을 날짜별로 판정했다. 2017~2026-09-19 선행형1,953출전·411두 중 현재집단불명1회 제외. 실제 첫집단366/1,042=35.1%, 둘째136/526=25.9%, 셋째이후87/384=22.7%, 비첫합계223/910=24.5%다. 첫−비첫 차이+10.62%p(날짜95%+6.90~+14.53). 같은 말×거리 양쪽전개 관측 비교도 같은 방향이다.

2026년은 첫30/81=37.0%, 비첫22/79=27.8%로 방향은 같으나 차이의95% 구간−3.42~+22.20%p로 불확실하다. 1300m6출전·1400m28출전·1610m 선행형충족0출전이므로 거리별 일반화는 보류한다. 첫집단은 단독선행과 다르고 둘째집단은 전통선입과 다르다. 이 결과는 실제전개에 조건부인 관찰 입상률이며 인과효과·개별 미래확률·고정보정치가 아니다. 앞선 모델 최고확률 후보의 실패위치 비율과 다른 분모다. 운영모델 변경 없음.

'''
    p.write_text(head+'\n\n'+intro+body)
    p=central/'README.md';text=p.read_text().replace('2026년 10월 8일 기준.','2026년 10월 9일 기준.',1)
    old=next(x for x in text.splitlines() if '| [통과조 기반 각질과 전개]' in x)
    new='| [통과조 기반 각질과 전개](07_RUNNING_STYLE.md) | 과거 선행형의 실제 첫집단 입상35.1%·비첫24.5%. 전개예측 추가구간M4 개선 없음 | 관찰 연관,2026·장거리 소표본,운영 미반영 |'
    p.write_text(text.replace(old,new))
    p=central/'SOURCES.md';text=p.read_text().replace('2026년 10월 8일 기준.','2026년 10월 9일 기준.',1);assert link not in text
    text=text.replace('같은 출전 자료가 여러 버전에 중복되므로',f'새 후속: [{HERE.name}]({link}) — 경주 전 선행형1,953출전·411두의 실제 S1F 집단별 최종Top3. 첫집단35.1%·비첫24.5%, 날짜/말 군집구간·최근기간·거리·동일말거리 비교·104,310이력창 독립 재계산 보존. 고정확률·운영 반영 없음.\n\n같은 출전 자료가 여러 버전에 중복되므로',1)
    p.write_text(text)
    p=central/'research_register.json';reg=json.loads(p.read_text());reg['updated_at']='2026-10-09'
    for topic in reg['topics']:
        if topic['id']=='running_style':
            topic['previous_running_style_source']=topic['latest_source'];topic['latest_source']=link
            topic['conditional_top3_followup']={'source':link,**decision}
            topic['status']='running_style_position_prediction_and_conditional_top3_completed_observational_no_operational_change'
    save(p,reg)
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']]
    entries=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
    save(HERE/'artifact_manifest.json',{'status':'completed','files':entries,'listed_files':len(entries),'listed_bytes':sum(r['bytes'] for r in entries),'excludes':'self and publication receipt'})
    files.append(HERE/'artifact_manifest.json')
    for r in manifest['files']:
        if r['role']=='conclusion_or_management':
            p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
    new=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
    assert not {r['path'] for r in manifest['files']}&{r['path'] for r in new}
    manifest['files']+=new
    manifest['verification'].update(status='passed',all_previous_source_hashes_unchanged=True,latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)))
    manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in manifest['files'])
    save(mp,manifest)
    for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
    links=0
    for p in [HERE/'README.md',central/'07_RUNNING_STYLE.md',central/'README.md',central/'SOURCES.md']:
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if '://' not in target:assert (p.parent/target.split('#')[0]).exists(),target;links+=1
    save(receipt,{'status':'passed','prior_immutable_files_verified':len(frozen),'new_study_files_in_central_manifest':len(new),'new_study_bytes':sum(r['bytes'] for r in new),
                  'central_manifest_entries_verified':len(manifest['files']),'central_manifest_sha256':sha(mp),'local_links_verified':links,
                  'management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in [central/'07_RUNNING_STYLE.md',central/'README.md',central/'SOURCES.md',central/'research_register.json',mp]},
                  'no_database_or_operational_model_changes':True})
    print('Publication passed',len(new),sum(r['bytes'] for r in new),flush=True)
if __name__=='__main__':main()
