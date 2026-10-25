"""Preserve the completed study and reconcile mutable central research summaries."""
import json
import re
from features import HERE,ROOT,sha,save


def main():
    assert not (HERE/'publication_verification.json').exists()
    decision=json.loads((HERE/'decision.json').read_text())
    assert json.loads((HERE/'verification01/verification.json').read_text())['status']=='passed'
    central=ROOT/'jeju/research/conclusions';mp=central/'source_manifest.json';manifest=json.loads(mp.read_text())
    frozen=[r for r in manifest['files'] if r['role']!='conclusion_or_management']
    for r in frozen:assert sha(ROOT/r['path'])==r['sha256'],r['path']
    link='../'+HERE.name+'/README.md'
    p=central/'07_RUNNING_STYLE.md';text=p.read_text();head,body=text.split('\n\n',1)
    assert link not in text
    intro=f'''最新後続'''
    intro=f'''최신 후속은 [게이트 구간 재예측과 선행 후보 실패 위치]({link})다.1300m를 사용자 정정2C→S1F 계약으로 포함해 총17,412출전·1,779경주를 시간순 예측했다.주집단 정답은17,382출전·1,776경주이며2026년488경주다. 앞선1300제외 비교와 수치를 혼합하지 않는다.

기존 과거+연속게이트+상대구성M3에 내측/중간/외측 및거리별 효과를 더한M4는 안정적인 개선이 없었다.M3→M4 로그손실은2024~25년0.7954→0.8034,2026년0.8232→0.8290으로 나빠졌다. 첫집단 후보 적중도62.8%→62.3%,60.5%→59.8%다.새M4는 미채택하고 이 후향 비교의 연구 기준M3를 유지한다.운영 모델 변경은 아니다.

M4의2026년 첫집단 후보 실패196건 중 둘째집단109건55.6%(날짜95%48.5~62.9%),셋째이후87건44.4%다.같은실패의 확실선입은77건39.3%,중단·후미53건27.0%,범위경계 판정불명66건33.7%다.둘째집단을 전통선입으로 자동변환하지 않는다.실패 분모·정답가용 조건과 거리별 소표본을 보존했다.

800m는 첫집단·앞두집단 내측 방향,900m는 첫집단 차이 불확실·앞두집단 내측 방향,1400m는 원시초반 내측 방향이다.이 원시연관은 추가구간 입력의 예측개선·인과효과와 다르다.800m2026년3경주,1400m14경주,1300m20경주로 최근거리별 지원이 부족하다. [전체확률·오류분자분모·재계산검증]({link}#연구-기준과-보관)을 저장했다.

'''
    p.write_text(head+'\n\n'+intro+body)
    p=central/'01_GATE_LATERAL.md';text=p.read_text();head,body=text.split('\n\n',1)
    intro=f'''내중외 및전개 재예측 최신 후속: [800·900·1300·1400m 구간 비교]({link}).정확10두 최종Top3 내/중/외 원시비율은800m34.9/29.8/25.3%,900m33.9/29.8/26.4%,1400m39.7/26.6/24.9%다.1400m S1F첫집단은25.9/19.0/11.6%(63경주),800m22.5/19.3/17.2%(1057경주),900m22.3/19.0/20.8%(초반유효688경주)다.900m 첫집단 내외차이는 불확실하지만 앞두집단은49.1/43.2/40.7%로내측방향이다.

기존 능력·함수율 조정Top3 내측근거는800·900m에 남고1400m는+10.14%p(95%−7.68~+27.95)로불확실하다.기존gate·상대모형에 구간·거리별효과를추가한M4는추가개선을확인하지못해미채택했다.원시구간비율을미래확률의고정가산으로쓰지않는다.상세표는기간·분모·구간·BH·소표본을구분한다.

'''
    p.write_text(head+'\n\n'+intro+body)
    p=central/'README.md';text=p.read_text()
    oldline=next(x for x in text.splitlines() if '| [통과조 기반 각질과 전개]' in x)
    newline='| [통과조 기반 각질과 전개](07_RUNNING_STYLE.md) | 1300 포함 전개 재예측.추가 내중외 구간M4 개선 없음.2026 선행군후보 실패중 둘째집단55.6%·그뒤44.4% | M3 연구 비교 유지·M4 미채택,운영 미반영 |'
    p.write_text(text.replace(oldline,newline))
    p=central/'SOURCES.md';text=p.read_text();assert link not in text
    row=f'| [{HERE.name}]({link}) | 1400·800·900m내중외 초반·입상과1300포함재예측.1,779경주,주정답1,776경주.추가구간M4 미채택,2026 실패196건중둘째55.6%·그뒤44.4%.엄격선입/중단후미/불명별분모와전확률·계수·검증보존 |\n\n'
    p.write_text(text.replace('같은 출전 자료가 여러 버전에 중복되므로',row+'같은 출전 자료가 여러 버전에 중복되므로',1))
    p=central/'research_register.json';reg=json.loads(p.read_text())
    for topic in reg['topics']:
        if topic['id']=='running_style':
            topic['previous_position_prediction_source']=topic['latest_source'];topic['latest_source']=link
            topic['previous_position_prediction']=topic.get('position_prediction')
            topic['position_prediction']=decision
            topic['status']='outcome_taxonomy_change_followup_gate_region_reprediction_and_miss_destinations_completed'
        if topic['id']=='gate_lateral':topic['region_position_prediction_followup']={'source':link,**decision}
    save(p,reg)
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']]
    entries=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
    save(HERE/'artifact_manifest.json',{'status':'completed','files':entries,'listed_files':len(entries),
        'listed_bytes':sum(r['bytes'] for r in entries),'excludes':'self and final publication verification receipt'})
    files.append(HERE/'artifact_manifest.json')
    for r in manifest['files']:
        if r['role']=='conclusion_or_management':
            p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
    new=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
    assert not {r['path'] for r in manifest['files']}&{r['path'] for r in new}
    manifest['files']+=new;save(mp,manifest)
    for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'],r['path']
    for path in [HERE/'README.md',central/'07_RUNNING_STYLE.md',central/'01_GATE_LATERAL.md']:
        for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if '://' not in target:assert (path.parent/target.split('#')[0]).exists(),target
    save(HERE/'publication_verification.json',{'status':'passed','prior_immutable_files_verified':len(frozen),
        'new_study_files_in_central_manifest':len(new),'new_study_bytes':sum(r['bytes'] for r in new),
        'central_manifest_entries_verified':len(manifest['files']),'central_manifest_sha256':sha(mp),
        'local_links_verified':True,'management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in [central/'01_GATE_LATERAL.md',central/'07_RUNNING_STYLE.md',central/'README.md',central/'SOURCES.md',central/'research_register.json',mp]},
        'no_operational_database_web_or_registry_changes':True})
    print('Publication passed',len(new),sum(r['bytes'] for r in new),flush=True)


if __name__=='__main__':main()
