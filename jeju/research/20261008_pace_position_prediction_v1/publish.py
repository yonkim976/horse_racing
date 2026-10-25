"""Append the completed study to mutable research management documents."""
from pathlib import Path
import json
import re
from features import HERE,ROOT,sha,save


def main():
    central=ROOT/'jeju/research/conclusions'
    manifestpath=central/'source_manifest.json'
    old=json.loads(manifestpath.read_text())
    immutable=[r for r in old['files'] if r['role']!='conclusion_or_management']
    for r in immutable:
        assert sha(ROOT/r['path'])==r['sha256'],r['path']
    verification=json.loads((HERE/'verification01/verification.json').read_text())
    assert verification['status']=='passed'
    decision=json.loads((HERE/'decision.json').read_text())
    relative='../'+HERE.name
    p=central/'07_RUNNING_STYLE.md';text=p.read_text()
    text=text.replace('최신 연구는 통과조 위치 범위에','앞선 유형 연구는 통과조 위치 범위에',1)
    text=text.replace('상태는 **전개 분류','앞선 유형·변화 연구의 상태는 **전개 분류',1)
    text=text.replace('[최신 상세 결과와 분류 기준]','[전개 결과 분류 기준]')
    text=text.replace('20261008_running_style_outcomes_v1/artifact_manifest.json','20261008_running_style_outcomes_v1/artifact_manifest_v2.json')
    addition=f'''최신 후속은 [과거 성향·게이트·상대 구성의 전개 예측]({relative}/README.md)이다.2017년부터 보유상한2026-09-19까지의 품질 원천을 쓰고2024·25·26년을 각각 과거로만 학습해 예측했다. 전체16,806출전·1,716경주,초반 집단 정답16,776출전·1,713경주다. 정상 완주·완전 편성을 사후 선별한 후향 비교이며 당시 선언 출전표·공개시각을 재현한 실서비스 검증은 아니다.

첫 집단 확률 최고1두가 실제 첫 집단에 속한 비율은2024~25년62.6%(날짜95%구간60.0~65.2%),2026년60.5%(56.3~64.3%)다. 무작위 기대는20.4%·20.8%다. 우승·단독 선행 적중률이 아니다. 모든 말의 첫/둘째/뒤 집단3종 정확도는64.1%·62.6%다.

자기 과거만 쓴 모형 대비 게이트·상대 구성 전체 모형의 초반 로그손실은0.8226→0.7967,0.8530→0.8271로 약3% 줄었다. 사전30비교 공동BH와 날짜·말 집단95%구간 기준에서 상대 추가 효과는 두 기간 재현됐고 게이트만 추가한 효과는2026년 불확실하다. 위치4종의 게이트 효과는 정답확정 부분집합에서 지지됐지만 전체표본 주 결론과 구분한다.

2026년 정확10두 편성의 외측8~10번 과거 초반 빠른1/3인307출전은 첫 집단40.4%·둘째 집단28.0%로 앞 두 집단68.4%였다. 외측 나머지526출전은20.2%다. 관찰 연관이며 게이트 인과효과가 아니다. 둘째 집단 상대 내측쪽 대용치는2026년에 예측이 악화됐고 레일2선·이동 경로는 관측 불가능해 정확한 내측2선 자리잡기 예측 근거는 부족하다.

2026 거리별 자료 지원은900·1000·1110·1200m다.800m3경주·1400m14경주·1610m6경주는 최근 소표본이며1300m 초반 정의 보류는 유지한다. 각질 고정라벨보다 이번 편성의 집단 위치 확률을 연구 입력으로 검토할 근거가 생겼지만 독립 미래검증·공동 전개·운영 적용은 미완료다. [확률·전체 지표·검증]({relative}/README.md#산출물과-검증)을 함께 보관했다.

---

'''
    title,body=text.split('\n\n',1)
    assert relative not in text
    p.write_text(title+'\n\n'+addition+body)
    p=central/'README.md';text=p.read_text()
    line=next(x for x in text.splitlines() if '| [통과조 기반 각질과 전개]' in x)
    replacement='| [통과조 기반 각질과 전개](07_RUNNING_STYLE.md) | 전개 분류·성향 변화와 다음 경주 집단 위치 예측.2026 첫 집단 후보60.5%,상대 구성 추가 개선 재현·내측2선 미확인 | 후향 예측 비교 완료,독립 미래·운영 미반영 |'
    p.write_text(text.replace(line,replacement))
    p=central/'SOURCES.md';text=p.read_text();assert relative not in text
    line=f'| [{HERE.name}]({relative}/README.md) | T−2 과거 위치·구간기록+게이트+상대 구성의 시간순 전개 예측.2024~26 전체1,716경주,초반 정답1,713경주.상대 구성의 추가 개선 재현,게이트 단독 최근 불확실·내측2선 대용치 최근 악화.계획·전 확률·이력ID·독립 재계산·실패 이력 보존 |\n\n'
    p.write_text(text.replace('같은 출전 자료가 여러 버전에 중복되므로',line+'같은 출전 자료가 여러 버전에 중복되므로',1))
    p=central/'research_register.json';reg=json.loads(p.read_text())
    topic=next(x for x in reg['topics'] if x['id']=='running_style')
    topic['previous_outcome_source']=topic['latest_source'];topic['latest_source']=relative+'/README.md'
    topic['future_prediction_tested']=True;topic['independent_future_validation']=False
    topic['status']='outcome_taxonomy_change_followup_and_retrospective_position_prediction_completed'
    topic['position_prediction']=decision
    reg['updated_at']='2026-10-08';save(p,reg)
    # Manifest excludes itself and the final verification receipt to avoid cycles.
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts
           and p.name not in ['artifact_manifest.json','publication_verification.json']]
    entries=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
    save(HERE/'artifact_manifest.json',{'status':'completed','files':entries,'listed_files':len(entries),
        'listed_bytes':sum(r['bytes'] for r in entries),'excludes':'this manifest and final publication verification receipt',
        'source_database_opened':False})
    files.append(HERE/'artifact_manifest.json')
    studyentries=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
    for r in old['files']:
        if r['role']=='conclusion_or_management':
            p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
    existing={r['path'] for r in old['files']};assert not existing&{r['path'] for r in studyentries}
    old['files']+=studyentries;old['updated_at']='2026-10-08';save(manifestpath,old)
    for r in old['files']:assert sha(ROOT/r['path'])==r['sha256']
    # Check local report links and required management additions.
    for textpath in [HERE/'README.md',central/'07_RUNNING_STYLE.md']:
        for link in re.findall(r'\]\(([^)]+)\)',textpath.read_text()):
            if '://' in link:continue
            assert (textpath.parent/link.split('#')[0]).exists(),link
    sizes={str((central/x).relative_to(ROOT)):(central/x).stat().st_size for x in ['07_RUNNING_STYLE.md','README.md','SOURCES.md','research_register.json','source_manifest.json']}
    save(HERE/'publication_verification.json',{'status':'passed','previous_immutable_sources_verified':len(immutable),
        'all_central_manifest_entries_verified':len(old['files']),'new_study_files_in_central_manifest':len(studyentries),
        'new_study_bytes_in_central_manifest':sum(r['bytes'] for r in studyentries),'management_bytes':sizes,
        'local_report_links_verified':True,'central_manifest_sha256':sha(manifestpath),
        'receipt_not_self_hashed_or_centrally_hashed':True,'no_operational_database_web_or_registry_changes':True})
    print('Publication verification passed',len(studyentries),sum(r['bytes'] for r in studyentries),flush=True)


if __name__=='__main__':main()
