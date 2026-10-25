"""Append this independent study to shared indexes, accounting only own mutations."""
from pathlib import Path
import hashlib,json,re
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={a['path']:a for a in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']};bp=O/'shared_edits_baseline.json';op=O/'shared_own_edits.json';before={a['path']:a for a in json.loads(bp.read_text())['files']} if bp.exists() else {};own={a['path']:a for a in json.loads(op.read_text())['files']} if op.exists() else {}
def mutate(p,new,expected):
 old=p.read_text();assert old==expected,'Concurrent edit: reread latest';name=str(p.relative_to(ROOT))
 if name not in before:before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);own[name]=dict(path=name,own_delta_bytes=0)
 if old!=new:assert p.read_text()==old;p.write_text(new);own[name]['own_delta_bytes']+=len(new.encode())-len(old.encode())
 own[name]['own_final_bytes']=before[name]['bytes']+own[name]['own_delta_bytes'];bp.write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');op.write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(own.values())),ensure_ascii=False,indent=2)+'\n')
central=R/'conclusions/28_RUNNING_STYLE_FOUNDATION.md';title='# 각질의 분류 근거와 말별 반복 성향';assert not central.exists() or central.read_text().startswith(title)
central.write_text(title+'''

2026-10-08. 말마다 반복되는 초반 위치 성향은 확인됐다. 그러나 자주 보인 전개가 가장 유리한 각질이라는 뜻은 아니다. 한 경주의 관측 위치·과거 반복 성향·성과에 유리한 전개를 분리한다.

서울·부산2018~2026년 검증된14,636경주의 원문 명단159,014행에서 완전한 공식 S1F 순위155,349출전을 분류했다. 기존 완주자 원장에 비정상486행을 복원했다. 91/92코드484행과0코드2행이며0의 실제 주행을 확정하지 않고 결측 관측으로 유지했다. 초반 유효 표본에는 결승착순이 유효하지 않은114출전도 포함한다. 부진 완주를 먼저 삭제하지 않았다.

선두(S1F1위),앞선(비선두 상대위치≤1/3),중단(1/3~2/3),후미(>2/3)의 연구용 구획과 원래 순위·연속 위치를 보존했다. G3F/G1F 위치와 S1F→G3F/막판 회복을 별도로 저장했다. 후미를 추입형·추입 성공으로 확정하지 않으며 단독 선행·기수 의도·경합은 순위만으로 판단하지 않는다.

T−2까지 실제 명단 최근5전 모두 유효하고730일 이내인2024/2025년24,613출전·3,084두에서 말 이력을 반영하면 초반 위치 정확도35.0%→44.2%,Brier0.708610→0.664997이었다. 주 차이−0.043613,말/실제 날짜 군집95% 구간[−0.049493,−0.037734]. 지역·거리·두수 빈도보다 말 이력의 반복 신호가 있었다. 우승확률·수익·고정 각질 확정 성능은 아니다.

최근5전 중4번 이상 같은 위치였던6,782출전의 다음 반복은56.9%였다. 강한 선두 성향의 다음 선두49.3%,강한 후미 성향의 다음 후미68.6%로 성향도 바뀔 수 있었다. 범주 변경을 의도적 각질 전환으로 해석하지 않는다. 같은 장소·거리 최근5전의 단순 빈도는 지원8,767출전에서 혼합거리 이력보다 추가 개선이 확인되지 않았다.

2026-09-22 기준 최근365일 관측3,204두 중 최근5전 지원2,132두,강한 반복629두다. 닥터시저 최근5전 선두5회,성실대로 앞선5회,킹아너 중단5회,스타티세 후미5회,태양으뜸 앞선1/중단2/후미2회로 설명했다. 현역 확인·작전 추천·적성 확정이 아니다. 분포·중반 위치·구간별 회복·관측수·기간을 함께 제공한다.

독립331,081검사에서 원문159,014행·19입력 해시·SQL 완전 순위·별도 rolling 이력·확률·Brier·군집 구간·현재/미래 결과 변조24사례를 검증했다. 359개 기존 관련 원본은 보존됐다. 각질 변경·게이트/상대 때문에 선행하지 못한 성적 손실·최적 각질의 인과효과는 후속 연구다. 운영 모델·DB·배포 변경 없음.

[보고서](../20261008_running_style_foundation/README.md) · [말별 프로필](../20261008_running_style_foundation/outputs/horse_style_profiles.csv) · [최근 관측 말](../20261008_running_style_foundation/outputs/recent_horse_style_profiles.csv) · [출처](../20261008_running_style_foundation/SOURCES.md) · [검증](../20261008_running_style_foundation/outputs/verification.json) · [게시요약](../20261008_running_style_foundation/PUBLICATION.md) · [용량](../20261008_running_style_foundation/outputs/artifact_inventory.json).
''')
mark='<!-- running_style_foundation_v1 -->';p=R/'conclusions/README.md';old=p.read_text();count=max(int(n) for n in re.findall(r'^\| (\d+) \|',old,re.M));study=int(re.search(r'^\| (\d+) \| 각질의 분류 근거와 말별 반복 성향',old,re.M)[1]) if mark in old else count+1
if mark not in old:
 new=re.sub(r'연구 (\d+)개',f'연구 {study}개',old);new=re.sub(r'(\d+)개 연구와 결정 문서',f'{study}개 연구와 결정 문서',new);marker='| [원 보고서 목록]';new=new.replace(marker,'| [각질의 근거와 반복 성향](28_RUNNING_STYLE_FOUNDATION.md) | 초반 위치·중반 이동·최근5전 분포·시간순 반복성,최적 각질 미확정 |\n'+marker,1)
 lines=new.splitlines();last=max(i for i,line in enumerate(lines) if re.match(r'^\| '+str(count)+r' \|',line));lines.insert(last+1,f'| {study} | 각질의 분류 근거와 말별 반복 성향 | 초반 위치155,349출전·최근5전 이력의 추가 예측 신호,강한 성향 다음 반복56.9% | 관측 성향·최적 각질 및 변경 원인 미확정·운영 미반영 |');new='\n'.join(lines)+'\n';new=new.rstrip()+'\n\n[각질의 분류 근거와 반복 성향 원 보고서](../20261008_running_style_foundation/README.md) · [중앙28](28_RUNNING_STYLE_FOUNDATION.md). '+mark+'\n'
else:new=old
mutate(p,new,old)
p=R/'README.md';old=p.read_text();entry='[각질의 분류 근거와 말별 반복 성향](20261008_running_style_foundation/README.md): 공식 초반 순위155,349출전에서 선두·앞선·중단·후미와중반/막판 이동을 분리했다. 2024/2025년24,613출전에서 말 최근5전 이력의 추가 반복 신호를 확인했으나 강한 성향도 다음 반복56.9%로 최적 각질은 미확정이다. [최근 말 프로필](20261008_running_style_foundation/outputs/recent_horse_style_profiles.csv) · [중앙28](conclusions/28_RUNNING_STYLE_FOUNDATION.md). 운영 변경 없음.';mutate(p,old if mark in old else old.rstrip()+'\n\n'+entry+' '+mark+'\n',old)
p=R/'conclusions/SOURCES.md';old=p.read_text()
if mark not in old:
 new=re.sub(r'\d+개 연구를 대상으로',f'{study}개 연구를 대상으로',old,count=1);new=new.rstrip()+f'\n\n## 각질의 관측 근거와 반복 성향\n\n- {study}. [각질의 분류 근거와 말별 반복 성향](../20261008_running_style_foundation/README.md): [중앙28](28_RUNNING_STYLE_FOUNDATION.md) · [출처](../20261008_running_style_foundation/SOURCES.md) · [프로필](../20261008_running_style_foundation/outputs/horse_style_profiles.csv) · [검증](../20261008_running_style_foundation/outputs/verification.json) · [게시요약](../20261008_running_style_foundation/PUBLICATION.md) · [용량](../20261008_running_style_foundation/outputs/artifact_inventory.json). 반복 성향과최적 각질을 구분하며 각질 변경·선행 실패 성적 손실은 후속 연구다. '+mark+'\n'
else:new=old
mutate(p,new,old)
p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(rec)
  else:m[key][idx]=rec
m['scope']=re.sub(r'연구\d+개',f'연구{study}개',m['scope']);m['running_style_foundation_added']=True;m['running_style_foundation_note']=f'{study}번째 독립 연구. 공식 초반 위치와과거 분포·시간순 반복성. 최적 각질·변경 원인·강제 선행 실패의 인과효과 미확정.';m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();marker='<!-- '+H.name+' -->';mutate(p,old if marker in old else old.rstrip()+'\n| 2026-10-08 | 각질의 분류 근거와 반복 성향 | 집계 중 | '+marker+'\n',old);print('Registered independent study',study)
