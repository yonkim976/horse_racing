"""Register follow-up 28A without increasing the independent-study count."""
from pathlib import Path
import hashlib,json
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={a['path']:a for a in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']};bp=O/'shared_edits_baseline.json';op=O/'shared_own_edits.json';before={a['path']:a for a in json.loads(bp.read_text())['files']} if bp.exists() else {};own={a['path']:a for a in json.loads(op.read_text())['files']} if op.exists() else {}
def mutate(p,new,expected):
 old=p.read_text();assert old==expected,'Concurrent edit: reread latest';name=str(p.relative_to(ROOT))
 if name not in before:before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);own[name]=dict(path=name,own_delta_bytes=0)
 if old!=new:assert p.read_text()==old;p.write_text(new);own[name]['own_delta_bytes']+=len(new.encode())-len(old.encode())
 own[name]['own_final_bytes']=before[name]['bytes']+own[name]['own_delta_bytes'];bp.write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');op.write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(own.values())),ensure_ascii=False,indent=2)+'\n')
central=R/'conclusions/28A_PASSING_GROUP_STYLE.md';title='# 통과조 기준 각질 성향';assert not central.exists() or central.read_text().startswith(title)
central.write_text(title+'''

2026-10-08. 각질 연구28의 후속28A. 독립 연구 수를 늘리지 않고 이전 순위 기준을 보존한 채 통과조 정의를 비교했다. 공식 괄호는1마신 미만의 마군이고 내부 번호는 내측부터의 상대 순서다. 같은 첫 마군 소속을 선행권으로 분류하고 첫 마군1두와여러 두를 나눴다. 실제 경합·압박·기수 의도를 확정하지 않는다.

서울·부산2018~2026년 검증 명단159,014행에서 완전한 S1F 통과조155,387출전·14,309경주를 분류했다. 나머지327경주·3,627행은지원 불가 표기324경주/명단 불일치3경주로 보류했다. 정상 완주나상위 착순으로 먼저 제한하지 않았다. 원문 선택·문자열·간격 구분을 보존했다.

이전 순위 기준과공통155,349출전 중42,614출전(27.4%)이 달라졌다. 순위1위 밖에서 같은 선두마군에 속한23,314출전이 선행권에 포함됐다. 첫 마군1두2,966경주(20.7%),여러 두11,343경주(79.3%). 첫 마군1두 중2마신 이상 분리 보조 표식은119경주이며 단독 마군·독주·무압박은 같은 뜻이 아니다.

닥터시저는 최근5전 모두 초반1위지만 통과조에서는5회 모두 여러 두 선두마군이었다. 대박스타는1위1회이나 선두마군4회·앞선추종1회였다. 같은5전 비교가능2,601두에서1위3/5 이상112두,첫 마군3/5 이상488두로 넓어진 선행권 성향을 확인했다. 현역 여부·작전 추천·최적 각질의 판정은 아니다.

2024/2025년24,613출전·3,084두의4구분 시간순 검증에서 기준34.0%→말 이력45.8%,Brier0.715746→0.661501,차이−0.054246[−0.060389,−0.048102]였다. 말별 반복 신호가 있지만 이전 순위 정의44.2%와 표적이 다르므로 예측 개선으로 비교하지 않는다. 강한 선행권2,324출전의 다음 선행권 유지율은58.1%다. 앞선추종의 강한 성향은58출전으로 적고 유지율12.1%라 확정 선입형으로 채택하지 않는다.

공식 순위1위가 첫 마군 밖인 모순1경주를 원문대로 표식했고 제외 민감도에서도 변경률27.4%였다. API303 선택분만의 변경률은27.6%다. 다른 마군의1/3·2/3 경계는 연구용이며1/4·3/4 민감도에서14.1%가 달라졌다. 서울3C/부산G4F 보조자료는 공간이 달라 합치지 않는다.

독립 문자 스캐너가28,781지점을 재파싱하고 유효28,115/보류666지점,실제 명단 최근5전·T−2·확률·Brier·말/날짜 군집 구간·말별5/10전·결과 변조24사례를 검증했다. 1,657,062검사와64개 기존 파일 보존을 확인했다. 원 스냅샷 해시가 읽기 전용 매니페스트와 일치한다. 최적 각질·각질 변경 원인·선행 실패 성적 손실은 후속 연구이며 운영 모델·DB·배포 변경 없음.

[보고서](../20261008_passing_group_style/README.md) · [최근 말 프로필](../20261008_passing_group_style/outputs/recent_horse_profiles.csv) · [사례 원문](../20261008_passing_group_style/outputs/examples.csv) · [출처](../20261008_passing_group_style/SOURCES.md) · [검증](../20261008_passing_group_style/outputs/verification.json) · [게시요약](../20261008_passing_group_style/PUBLICATION.md) · [용량](../20261008_passing_group_style/outputs/artifact_inventory.json).
''')
mark='<!-- passing_group_style_v1 -->';p=R/'conclusions/README.md';old=p.read_text()
if mark not in old:
 marker='| [원 보고서 목록]';new=old.replace(marker,'| [통과조 기준 각질](28A_PASSING_GROUP_STYLE.md) | 연구28 후속·같은 선두마군·단독/동반 구분,분류27.4% 변경·최적 각질 미확정 |\n'+marker,1);new=new.rstrip()+'\n\n[통과조 기준 각질 성향 원 보고서](../20261008_passing_group_style/README.md) · [후속28A](28A_PASSING_GROUP_STYLE.md). 독립 연구 수는 유지한다. '+mark+'\n'
else:new=old
mutate(p,new,old)
p=R/'README.md';old=p.read_text();entry='[통과조 기준 각질 성향](20261008_passing_group_style/README.md): 같은 첫 마군을 선행권으로 묶고 첫 마군1두/여러 두를 구분했다. 순위 기준과공통155,349출전의27.4%가달라졌고 순위1위 밖의23,314출전이선두마군에포함됐다. 연구28의후속이며 최적 각질·경합·선행실패효과는미확정이다. [최근 말 프로필](20261008_passing_group_style/outputs/recent_horse_profiles.csv) · [중앙28A](conclusions/28A_PASSING_GROUP_STYLE.md).';mutate(p,old if mark in old else old.rstrip()+'\n\n'+entry+' '+mark+'\n',old)
p=R/'conclusions/SOURCES.md';old=p.read_text();entry='## 통과조 각질 후속28A\n\n- [통과조 기준 각질 성향](../20261008_passing_group_style/README.md): 연구28의후속으로독립연구수를유지한다. [중앙28A](28A_PASSING_GROUP_STYLE.md) · [출처](../20261008_passing_group_style/SOURCES.md) · [프로필](../20261008_passing_group_style/outputs/horse_profiles.csv) · [검증](../20261008_passing_group_style/outputs/verification.json) · [게시요약](../20261008_passing_group_style/PUBLICATION.md) · [용량](../20261008_passing_group_style/outputs/artifact_inventory.json). 같은마군을함께분류하며단독선두·경합·최적각질을구분한다.';mutate(p,old if mark in old else old.rstrip()+'\n\n'+entry+' '+mark+'\n',old)
p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(rec)
  else:m[key][idx]=rec
m['passing_group_style_added']=True;m['passing_group_style_note']='연구28 후속28A. 독립 연구 수 유지. 같은 첫 마군 선행권·선두1두/여러 두 구분. 최적 각질·경합·선행 실패 인과효과 미확정.';m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();marker='<!-- '+H.name+' -->';mutate(p,old if marker in old else old.rstrip()+'\n| 2026-10-08 | 통과조 기준 각질 성향 | 집계 중 | '+marker+'\n',old);print('Registered follow-up28A; independent-study count unchanged')
