"""Register independent aptitude research while preserving concurrent shared work."""
from pathlib import Path
import hashlib,json,re
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={a['path']:a for a in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']};bp=O/'shared_edits_baseline.json';op=O/'shared_own_edits.json';before={a['path']:a for a in json.loads(bp.read_text())['files']} if bp.exists() else {};own={a['path']:a for a in json.loads(op.read_text())['files']} if op.exists() else {}
def mutate(p,new,expected):
 old=p.read_text();assert old==expected,'Concurrent edit: read latest contents';name=str(p.relative_to(ROOT))
 if name not in before:before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);own[name]=dict(path=name,own_delta_bytes=0)
 if old!=new:assert p.read_text()==old;p.write_text(new);own[name]['own_delta_bytes']+=len(new.encode())-len(old.encode())
 own[name]['own_final_bytes']=before[name]['bytes']+own[name]['own_delta_bytes'];bp.write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');op.write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(own.values())),ensure_ascii=False,indent=2)+'\n')
central=R/'conclusions/27_HORSE_DISTANCE_APTITUDE.md';title='# 말별 적정거리 후보와 검증';assert not central.exists() or central.read_text().startswith(title)
central.write_text(title+'''

2026-10-08. 말별 거리 후보는 계산 가능하지만 단일 적정거리의 확정 근거는 부족했다. 서울·부산1000~1800m 정상148,126출전에서 경주 효과·부담중량·연령·rating·과거 성적을 맞추고 말 기본 수준과 중심화한 말×거리 편차를 ridge로 분리했다. 미경험 거리와1900m 이상으로 외삽하지 않는다.

전체15회·두 거리 이상 각각5회 조건을 충족한2,634두의 임시 후보를 보존했다. 최근 공통 기준일2026-09-20까지365일 내 관측된 비교 가능 그룹은760개다. 최종 후보는 관측기간 평균적 조건부 선호이며 개인 신뢰구간·생리적 최적값·현역 등록 확인이 아니다. 2,625그룹의1·2순위 차이가 표시 기준0.10 상대척도보다 작았고,나머지9개도 확정 적성으로 표현하지 않는다.

2018~2022학습→2023선택에서 거리 penalty100을 고른 뒤2024·2025년을 각각 이전 연도까지만 학습했다. 두 거리 이상 근거가 있는6,180출전·1,022두에서 MAE0.619480→0.619325,차이−0.000155 [−0.000552,+0.000243]로 약0.025% 감소했으나 불확실했다. 실제 초 평균오차 감소약0.000221초는 거리 변경의 시간 이득이 아니다. 한 지역/연도 하위집단의 개선을 일반화하지 않는다.

이후 후보거리와 다른 지원거리에서 각각2회 이상 뛴2024년120두/2025년131두의 선택 일치율은55.0%/49.6%였다. 후보거리−다른거리 조정 성과는+0.056 [−0.074,+0.187],+0.085 [−0.041,+0.212]로 불확실했다. 거리 선택이 비무작위이며 후보 수가 달라50%와의 단순 우열·인과 개선·출전 전략 최적화를 입증하지 않는다.

태양으뜸은1200m42회/1400m6회 근거에서1200m가 후보이고,소리태풍은1800m35회/1600m13회에서 두 거리를 함께 표시했다. 후보거리·가까운 대안·거리별 횟수·최근 관측일·판단 보류를 함께 제공한다. 한 번의 최고기록이나 승률만으로 고르지 않는다. 개인 평균0은 다른 말과 같은 능력을 뜻하지 않는다.

원문18파일148,126행·19개 입력 해시를 확인했다. 독립 희소 설계/경주 평균 투영/LSMR로10개 모형을 재계산하고4,882검사를 통과했다. 마필/실제 날짜 군집은 지역을 넘는 같은 말과 같은 날짜의 의존을 포함한다. 현재 결과 변조가 예측값에 들어가지 않는 계약도 확인했다. 검증 경주의 실제 평균은 결과 평가용이며 예측 입력이 아니다. 정상 완주자 상대기록 검증과 실시간 출전표 전원·절대시간·우승확률 검증은 구분한다.

새 독립 연구로 중앙 목록에 추가했다. 기존 함수율/구간/체중 연구와 운영 평가표·모델·DB·웹 배포는 변경하지 않았다. 수치 검증을 인과적 거리 적성이나 생리 기전의 입증으로 표현하지 않는다.

[보고서](../20261008_horse_distance_aptitude/README.md) · [말별 후보](../20261008_horse_distance_aptitude/outputs/horse_candidates.csv) · [최근 후보](../20261008_horse_distance_aptitude/outputs/recent_horse_candidates.csv) · [출처](../20261008_horse_distance_aptitude/SOURCES.md) · [검증](../20261008_horse_distance_aptitude/outputs/verification.json) · [게시요약](../20261008_horse_distance_aptitude/PUBLICATION.md) · [용량](../20261008_horse_distance_aptitude/outputs/artifact_inventory.json).
''')
mark='<!-- horse_distance_aptitude_v1 -->';cp=R/'conclusions/README.md';old=cp.read_text();numbers=[int(v) for v in re.findall(r'^\| (\d+) \|',old,re.M)];count=max(numbers);study=int(re.search(r'^\| (\d+) \| 말별 적정거리 후보와 검증',old,re.M)[1]) if mark in old else count+1
if mark not in old:
 new=re.sub(r'연구 (\d+)개',f'연구 {study}개',old);new=re.sub(r'(\d+)개 연구와 결정 문서',f'{study}개 연구와 결정 문서',new)
 marker='| [원 보고서 목록]';new=new.replace(marker,'| [말별 적정거리 후보](27_HORSE_DISTANCE_APTITUDE.md) | 같은 경주·말 기본 수준·거리 편차의 분리,2024/2025 검증과 개인 후보 미확정 |\n'+marker,1)
 lines=new.splitlines();last=max(i for i,line in enumerate(lines) if re.match(r'^\| '+str(count)+r' \|',line));lines.insert(last+1,f'| {study} | 말별 적정거리 후보와 검증 | 2,634두 후보 계산 가능,이후 MAE 개선약0.025% 불확실 | 단일 적정거리 미확정·연구 후보·운영 미반영 |');new='\n'.join(lines)+'\n';new=new.rstrip()+'\n\n[말별 적정거리 후보 원 보고서](../20261008_horse_distance_aptitude/README.md) · [중앙27](27_HORSE_DISTANCE_APTITUDE.md). '+mark+'\n'
else:new=old
mutate(cp,new,old)
p=R/'README.md';old=p.read_text();entry='[말별 적정거리 후보와 이후 검증](20261008_horse_distance_aptitude/README.md): 같은 경주·말 기본 수준과 거리 편차를 분리해2,634두의 임시 후보를 보존했다. 2024/2025년6,180출전 검증의 추가 MAE 개선약0.025%는 불확실하며 단일 적정거리는 미확정이다. [전체 후보](20261008_horse_distance_aptitude/outputs/horse_candidates.csv) · [중앙27](conclusions/27_HORSE_DISTANCE_APTITUDE.md). 운영 변경 없음.';mutate(p,old if mark in old else old.rstrip()+'\n\n'+entry+' '+mark+'\n',old)
p=R/'conclusions/SOURCES.md';old=p.read_text()
if mark not in old:
 new=old.replace('2026년 10월 7일 갱신.','2026년 10월 8일 갱신.',1);new=re.sub(r'연령\d+개 연구',f'연령·말별 거리 적성{study}개 연구',new,count=1);new=new.rstrip()+f'\n\n## 말별 거리 적성\n\n- {study}. [말별 적정거리 후보와 이후 검증](../20261008_horse_distance_aptitude/README.md): [중앙27](27_HORSE_DISTANCE_APTITUDE.md) · [출처](../20261008_horse_distance_aptitude/SOURCES.md) · [개인 후보표](../20261008_horse_distance_aptitude/outputs/horse_candidates.csv) · [검증](../20261008_horse_distance_aptitude/outputs/verification.json) · [게시요약](../20261008_horse_distance_aptitude/PUBLICATION.md) · [용량](../20261008_horse_distance_aptitude/outputs/artifact_inventory.json). 2,634두 후보와작은/불확실한 이후 예측 개선을 구분하며 개인 최적거리·인과 개선·운영 채택은 미확정이다. '+mark+'\n'
else:new=old
mutate(p,new,old)
p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(rec)
  else:m[key][idx]=rec
m['scope']=re.sub(r'연구\d+개',f'연구{study}개',m['scope']);m['horse_distance_aptitude_added']=True;m['horse_distance_aptitude_note']=f'{study}번째 독립 연구. 말 기본 수준과 거리 편차,과거 학습→2024/2025 평가. 임시 후보2,634두,개인 적정거리와추가 예측 이득 미확정.';m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();marker='<!-- '+H.name+' -->';mutate(p,old if marker in old else old.rstrip()+'\n| 2026-10-08 | 말별 적정거리 후보와 검증 | 집계 중 | '+marker+'\n',old);print('Registered independent study',study)
