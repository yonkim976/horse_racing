"""Publish the verified study while preserving all earlier research sources."""
import json,re
from data import HERE,ROOT,sha,save

def main():
    receipt=HERE/'publication_verification.json'
    assert not receipt.exists()
    for p in ['verification01/verification.json','verification_extra01/verification.json']:
        assert json.loads((HERE/p).read_text())['status']=='passed'
    central=ROOT/'jeju/research/conclusions'; mp=central/'source_manifest.json'
    manifest=json.loads(mp.read_text())
    # Check management as well as immutable sources before making changes.
    for r in manifest['files']:
        p=ROOT/r['path']; assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
    frozen=[r for r in manifest['files'] if r['role']!='conclusion_or_management']
    link='../'+HERE.name+'/README.md'
    decision=json.loads((HERE/'decision.json').read_text())
    newcentral=central/'08_JOCKEY_PROFILE.md'
    newcentral.write_text(f'''# 기수 특성과 좋은 말 배정 및 추가 기여

최신 결과는 [기수 배정·추가 기록 기여·전개 특성]({link})이다. **좋은 말을 타는 정도는 기수별로 다르고, 말의 과거 수행과 조건을 고려한 후에도 기수 정보의 작지만 반복된 추가 신호가 있다.** 2017-01-13~2026-09-19 정상완주 완전 편성 52,155출전·5,206경주·2,813두·기수 40명이며 2026년은 부분연도다.

2026년 박성광 기승마의 실제 Top3는 53.7%, 기수 ID 없는 과거 수행 모형의 평균 기대는 40.2%였다. 이 기대는 배정된 말의 기대수행 지표이며 순수 말 능력이 아니다. 원시 입상률과 배정·조건을 고려한 기수 기여를 구분한다. 100출전 이상 기수의 실제/기대 입상률 상관은 2024~2025년 0.948, 2026년 0.965였으나 인과 설명률을 뜻하지 않는다.

말×정확거리·경주 고정효과와 과거 수행·게이트·부담·체중·조교사를 고려한 기록 차이는 박성광이 2024~2025년 +0.556초, 2026년 +0.463초로 빠른 방향을 반복했다. 양수는 기간 내 출전가중 평균보다 빠른 방향이다. 2026년 날짜 군집 95% 구간 +0.194~+0.733초, 말 군집 +0.142~+0.785초, BH q=0.023이다. 문현진의 +0.335초는 다중비교 후 미확정이고 다른 현재 기수도 확정 순위를 매기지 않는다. 전체 17명 지원표와 소표본 기수까지의 원표는 원 연구에 있다. 이 수치를 개별 경주의 고정 기록 보정값으로 사용하지 않는다.

박성광의 S1F 첫집단 확보 차이는 2024~2025년 +8.1%p, 2026년 +18.1%p로 반복 지지됐다. 단독 선두나 선행 의도와 동일하지 않다. 후반 전진·G3F의 반복 근거는 부족해 추입 전문 등의 고정 명칭은 보류한다. 거리별·각질별 전문성은 별도 추정하지 않았다.

연도 이전 자료로만 학습한 같은 표본의 예측 비교에서 기수 ID 추가는 상대기록 MAE를 2024~2025년 0.9513→0.9403초, 2026년 0.8924→0.8845초로 개선했다. Top3 logloss도 0.5693→0.5608, 0.5775→0.5692로 개선됐고 양쪽 군집 구간·BH 기준을 통과했다. 절대 완주시간 예측이 아니라 경주평균 대비 상대기록이다. 실제 출전표 공개/변경 시각이 검증된 서비스 재생은 아니다.

말·기수·조교사 ID 가산 모형에 말×기수 조합을 추가하면 두 기간의 MAE와 logloss가 나빠져 별도 조합 항목은 채택하지 않는다. 과거 3회 이상 조합도 반복 개선이 없었다. 호흡 자체가 없다는 증명은 아니다.

2017~2023년 기수 평가를 고정한 기수 교체 비교에서도 높은 과거 평가와 이후 상대기록 개선이 연결됐다. 같은 말·정확거리 2~60일 교체쌍은 2024~2025년 3,064쌍, 2026년 974쌍이다. 교체가 무작위가 아니어서 관측하지 못한 컨디션·교체 이유·관리 차이를 제거한 순수 기수 능력이나 인과효과를 뜻하지 않는다.

연구 입력 후보로 기수 정보를 유지하되 고정 초·입상확률 가산이나 운영 모델 반영은 없다. 공식 ID·payload·전처리 시점·예측·효과 구간·교체쌍 재계산을 통과하고 DB 전후 SHA가 같았다. 앞선 [자료지원 감사와 설계](../20261009_jockey_research_feasibility_v1/README.md)는 효과 추정 전 단계로 그대로 보존한다. [각질·편성 연구](07_RUNNING_STYLE.md)는 사용자 지시에 따라 저장 후 추후 재개 상태를 유지한다.
''')
    p=central/'README.md'; text=p.read_text()
    old=next(line for line in text.splitlines() if '| [기수 특성과 좋은말 배정]' in line)
    text=text.replace(old,'| [기수 특성과 좋은말 배정](08_JOCKEY_PROFILE.md) | 배정 차이와 기수 정보의 작은 반복 개선. 박성광 기록·초반 확보 반복, 조합 추가 개선 없음 | 조건부 효과·시간순 비교 완료, 순수 능력·고정 보정·운영 적용 미확정 |')
    text=text.replace('통과조 기반 각질 연구다.','통과조 기반 각질·기수 연구다.')
    p.write_text(text)
    p=central/'SOURCES.md';text=p.read_text();assert link not in text
    text+='\n| ['+HERE.name+']('+link+') | **최신 기수 연구. 좋은 말 배정·조건부 기록 기여·초반과 후반 특성·연도 고정 예측·과거 고정 점수의 교체 비교. 기수 추가의 작은 반복 개선, 말×기수 상호작용 미채택. 순수 능력 식별·운영 반영 없음.** |\n'
    p.write_text(text)
    p=central/'research_register.json';reg=json.loads(p.read_text());reg['updated_at']='2026-10-09'
    topic=next(t for t in reg['topics'] if t['id']=='jockey_profile')
    topic.update(decision,latest_source=link)
    save(p,reg)
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json']]
    entries=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
    save(HERE/'artifact_manifest.json',{'status':'completed_verified_research_only','files':entries,'listed_files':len(entries),'listed_bytes':sum(r['bytes'] for r in entries),'excludes':'self and final publication receipt'})
    files.append(HERE/'artifact_manifest.json')
    for r in manifest['files']:
        if r['role']=='conclusion_or_management':
            p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
    new=[{'path':str(p.relative_to(ROOT)),'role':'research_source','sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]
    assert not {r['path'] for r in manifest['files']}&{r['path'] for r in new}
    manifest['files']+=new
    manifest['verification'].update(status='passed',all_previous_source_hashes_unchanged=True,latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)))
    manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in manifest['files']);save(mp,manifest)
    for r in manifest['files']:
        p=ROOT/r['path'];assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
    links=0
    for p in [HERE/'README.md',newcentral,central/'README.md',central/'SOURCES.md']:
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if '://' not in target:
                assert (p.parent/target.split('#')[0]).exists(),target
                links+=1
    save(receipt,{'status':'passed','prior_immutable_files_verified':len(frozen),'new_source_files':len(files),
        'new_source_bytes':sum(p.stat().st_size for p in files),'central_manifest_entries_verified':len(manifest['files']),
        'central_manifest_sha256':sha(mp),'local_links_verified':links,
        'management_bytes':{str(p.relative_to(ROOT)):p.stat().st_size for p in [newcentral,central/'README.md',central/'SOURCES.md',central/'research_register.json',mp]},
        'effect_estimation_completed':True,'pure_jockey_ability_identified':False,'no_database_or_operational_model_changes':True})
    print('Publication passed',len(files),'new files;',len(frozen),'prior sources unchanged',flush=True)

if __name__=='__main__':main()
