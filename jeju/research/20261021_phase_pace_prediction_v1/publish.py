"""Publish this study to the existing local research topic without promoting a model."""
import copy,json,re,shutil
from common import *

def main():
    assert not (HERE/'publication_verification.json').exists()
    verify=json.loads((OUT/'verification.json').read_text());assert verify['status']=='passed'
    assert (HERE/'README.md').exists() and (OUT/'phase_prediction_comparison.png').exists()
    assert json.loads((OUT/'visual_review.json').read_text())['status']=='passed'
    d=json.loads((HERE/'decision.json').read_text())
    c=ROOT/'jeju/research/conclusions';mp=c/'source_manifest.json';oldmanifest=json.loads(mp.read_text());old=copy.deepcopy(oldmanifest['files'])
    reg=json.loads((c/'research_register.json').read_text());topics=copy.deepcopy(reg['topics'])
    paths=[c/n for n in ['07_RUNNING_STYLE.md','README.md','SOURCES.md','research_register.json']]
    managed={str(p.relative_to(ROOT)) for p in paths}
    for p in paths:
        row=next(r for r in old if r['path']==str(p.relative_to(ROOT)))
        assert sha(p)==row['sha256'] and p.stat().st_size==row['bytes'],p
    snapshot=HERE/'publication_snapshot';snapshot.mkdir(exist_ok=False)
    for p in paths+[mp]:shutil.copyfile(p,snapshot/p.name)
    link='../'+HERE.name+'/README.md'
    text=f'''2026-10-21 최신 [초반·중반·종반 전개 예측]({link})은 2017~2026-09-19 출전 명단 {d['roster_races']:,}경주·{d['roster_rows']:,}출전에서 T−2 과거 이력만으로 2024·2025·2026년을 시간순 평가했다. **2026년 초반 최고 후보의 실제 첫 묶음 포함률은 과거빈도 {100*d['early_2026_H_hit']:.1f}% → 편성·출발번호 포함 F {100*d['early_2026_F_hit']:.1f}%**다. 이 수치는 최종입상률이 아니다.

## 초반 중반 종반 예측 후속

S1F·3C·4C·G1F의 첫/둘째/셋째이후 묶음 확률과 중반 전진·종반 전진·마지막200m회복·앞선후퇴를 구분했다. 800m의3C는S1F와같은지점이므로 독립중반 평가를 만들지 않았다. S1F200m/1110·1610m210m와1300m2C→S1F 계약을 유지했다. 관측 보류·미완주 이동 정답을0으로 채우지 않았고 현재 실제구간·착순은 사전 입력에서 제외했다.

H 단순빈도, P 자기과거, F 출발번호·상대과거까지의 같은설정 비교다. 기수/조교사 ID·성향은 이번 연구에서 제외했다. 선두두수1/2/3+를 별도로 예측하고 비어있지않은 부분집합 분포 I 및 두수별재가중 J를 저장했다. 중·종반은 지점별 주변확률이며 경로전체 공동분포가 아니다.

4지점 F−H/F−P 8개 사전비교 중 Brier 감소 날짜95%구간과BH q<0.05를 함께 만족한 것은 {d['primary_comparisons_supported']}개다. 상세연도·거리별 차이와 두수모형의 성능은 원보고서 원표를 따른다. 이미 반복사용한 과거기간의 후향개발평가이며 미래독립검증이나 당시사전발행실적이 아니다. {d['model_count']}개 저장모형 재추론·원천해시·모든이력창·부분집합독립열거·8개bootstrap 재검산을 완료했다.

최고선두후보는2026년 자기과거 P {100*d['early_2026_P_hit']:.1f}%가 F보다1경주 높아, 확률분포 개선과 후보선정 개선을 구분한다. 선두두수 J는2026년 단순빈도보다 정확도·Brier·실제두수MAE가 모두 나빠 공동두수예측의 검증된 채택은 보류한다.

이전5,200경주 연구는 정상완주완전편성의 사후연관표다. 이번 연구는 실격·주행중지도 입력명단에 남긴 더 넓은 출전명단이며 정답별분모를 분리한다. 운영 HY_R_FORM·DB·웹·등록부 변경과 최종성적모형 추가효과 검증은 없다. 연구후보의 저장을 운영채택으로 표시하지 않는다.

## 선두 두수별 실제 결과

'''
    p=c/'07_RUNNING_STYLE.md';head,body=p.read_text().split('\n\n',1);p.write_text(head+'\n\n'+text+body)
    p=c/'README.md';s=p.read_text();line=next(v for v in s.splitlines() if '| [통과조 기반 각질과 전개]' in v)
    s=s.replace(line,'| [통과조 기반 각질과 전개](07_RUNNING_STYLE.md) | 초반·3C·4C·G1F 사전 위치 확률과 선두두수·막판회복 후보 | 51개 연구모형·시간순 평가·운영미반영 |')
    p.write_text(s+f'\n[초반·중반·종반 전개 예측]({link}): 2024~2026 시간순 평가, 지점별 위치와 선두두수·회복·후퇴 구분. 800m S1F=3C 예외와 거리별 소표본 유지.\n')
    p=c/'SOURCES.md';p.write_text(p.read_text()+f'\n2026-10-21 전개 후속: [S1F·3C·4C·G1F와선두두수·막판회복예측]({link}) — {d["roster_rows"]:,}출전·{d["roster_races"]:,}경주 명단, T−2, 연도별 전년학습. 원천·51모형재추론·부분집합·주8비교 검산. 운영미반영.\n')
    topic=next(t for t in reg['topics'] if t['id']=='running_style');previous=topic.get('latest_source')
    topic.update(latest_source=link,status=d['status'],previous_pack_size_outcomes_source=previous)
    topic['phase_pace_prediction_followup']={**d,'source':link}
    for t in topics:
        if t['id']!='running_style':assert next(z for z in reg['topics'] if z['id']==t['id'])==t
    receipt=HERE/'publication_verification.json'
    reg.update(updated_at='2026-10-21',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status'])
    save(c/'research_register.json',reg)
    files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['artifact_manifest.json','publication_verification.json'])
    save(HERE/'artifact_manifest.json',{'status':d['status'],'files':manifest(files),'total_bytes':sum(p.stat().st_size for p in files),
                                    'excludes':'self, publication receipt, Python caches'})
    files.append(HERE/'artifact_manifest.json');newrows=manifest(files)
    for r in oldmanifest['files']:
        if r['path'] in managed:
            p=ROOT/r['path'];r.update(sha256=sha(p),bytes=p.stat().st_size)
    assert not {r['path'] for r in newrows}&{r['path'] for r in old}
    for r in newrows:r['role']='research_source'
    oldmanifest['files']+=newrows
    oldmanifest.update(updated_at='2026-10-21',latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)),latest_status=d['status'])
    oldmanifest['verification'].update(status='passed_phase_pace_publication_scoped',scope='new study and four management files only; prior source metadata retained without external-source revalidation',
        all_previous_research_output_files_unchanged=None,all_previous_nonmanagement_source_entries_unchanged=None,
        prior_external_sources_revalidated=False,prior_source_metadata_preserved_except_four_management_files=True,
        latest_study=str(HERE.relative_to(ROOT)),latest_verification=str(receipt.relative_to(ROOT)))
    oldmanifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in oldmanifest['files']);save(mp,oldmanifest)
    check_manifest(newrows)
    for r in old:
        if r['path'] not in managed:assert next(z for z in oldmanifest['files'] if z['path']==r['path'])==r
    check_manifest([r for r in oldmanifest['files'] if r['path'] in managed])
    links=0
    for p in [HERE/'README.md',c/'07_RUNNING_STYLE.md',c/'README.md',c/'SOURCES.md']:
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if '://' not in target:
                assert (p.parent/target.split('#')[0]).exists(),(p,target);links+=1
    save(receipt,{'status':'passed','new_study_files_verified':len(newrows),'new_study_bytes':sum(r['bytes'] for r in newrows),
        'other_topic_objects_preserved':len(topics)-1,'management_files_updated':sorted(managed),'local_links_checked':links,
        'prior_external_sources_revalidated':False,'operationally_applied':False,'database_written':False})
    print('Study indexed',len(newrows),'files',sum(r['bytes'] for r in newrows),'bytes',flush=True)

if __name__=='__main__':main()
