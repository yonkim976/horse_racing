"""Register the new load follow-up and capture exact task-only shared-file changes."""
from pathlib import Path
import hashlib,json
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((O/'baseline_inventory.json').read_text());initial={a['path']:a for a in b['related_existing_files']}
bp=O/'shared_edits_baseline.json';op=O/'shared_own_edits.json'
before={a['path']:a for a in json.loads(bp.read_text())['files']} if bp.exists() else {}
own={a['path']:a for a in json.loads(op.read_text())['files']} if op.exists() else {}
def save():
 bp.write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n')
 op.write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(own.values())),ensure_ascii=False,indent=2)+'\n')
def mutate(p,new,expected):
 old=p.read_text();assert old==expected,'Concurrent edit; reread before registering';name=str(p.relative_to(ROOT))
 if name not in before:
  before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes'])
  own[name]=dict(path=name,own_delta_bytes=0)
 if old!=new:
  assert p.read_text()==old,'Concurrent edit; reread before registering'
  p.write_text(new);own[name]['own_delta_bytes']+=len(new.encode())-len(old.encode())
 own[name]['own_final_bytes']=before[name]['bytes']+own[name]['own_delta_bytes'];save()
central=R/'conclusions/11A_BODY_LOAD_TIME.md'
central.write_text('''# 마체중별 부담중량 증가와 기록 차이

2026-10-08. 기존11번 중량 비율 연구의 후속이다. 정상151,074행을 읽기 전용 재사용해13개 지역/정확거리의 체중×부담중량 상호작용을 새로 계산했다. 이전 비율모형의 예측오차 감소를1kg 손실로 전환하지 않았다.

같은 말과 같은 경주,나이·rating·과거 이력 등을 맞춘1200m의 부담중량54→55kg 전체시간 차이는 마체중450/480/510kg에서 서울+0.064/+0.055/+0.047초,부산+0.026/+0.031/+0.036초다.480kg의95%구간은 서울[+0.033,+0.077]·부산[+0.007,+0.056]초다.480kg의54→56kg는 약+0.106/+0.063초다.

가벼운450kg 말의1kg 변화가510kg보다 더 큰지 직접 비교하면 서울+0.017초[−0.015,+0.049]·부산−0.009초[−0.048,+0.029]로 모두0을 포함한다. 거리별로 방향이 바뀌고,지원된12개 체중 대비의BH q 최소는 약0.345다. 가벼운 말이 항상 더 큰 손실을 본다는 공식은 지지되지 않았다.

최근2024~2025년의480kg 1kg 차이는 서울+0.045초·부산+0.014초로 두 구간 모두0을 포함한다. rating 제외·상위5위 선택에서도 크기가 바뀐다.58kg 등 일부 체중/중량 지점은지원이 부족하다. 중량 배정·성장·건강·훈련 등의 시간 변화가 남아 조건부 관찰 추정이며 확정 인과 손실·운영 환산계수로 사용하지 않는다.

65모형/3705대비를 보존했고 최근1000m2모형은 반복 비교 표본 부족으로 생략했다. 별도 희소 고정효과 투영·QR회귀·군집 합으로23모형/366대비,760수치 검사를 통과했다. [보고서](../20261008_body_load_time_loss/README.md) · [출처/방법/해시](../20261008_body_load_time_loss/SOURCES.md) · [검증](../20261008_body_load_time_loss/outputs/verification.json) · [게시요약](../20261008_body_load_time_loss/PUBLICATION.md) · [용량](../20261008_body_load_time_loss/outputs/artifact_inventory.json). 기존 연구·기준·운영·배포는 변경하지 않았다.
''')
mark='<!-- body_load_time_followup_v1 -->'
entries={R/'README.md':'''[마체중별 부담중량 증가와 기록 차이](20261008_body_load_time_loss/README.md): 같은 말/경주를 맞춘1200m480kg의54→55kg는 서울약+0.055초·부산+0.031초다.450−510kg의직접대비·13거리·rating제외·최근/상위5위민감도를 검증했으며,가벼운말의보편적추가손실이나인과환산계수는확정하지 않았다. [중앙11A후속](conclusions/11A_BODY_LOAD_TIME.md), 운영 변경 없음.''',
R/'conclusions/README.md':'''## 체중별 부담중량 기록 차이 후속

[11A중량 후속](11A_BODY_LOAD_TIME.md): 같은 말과 같은 경주를 맞춘1200m480kg의1kg 차이는 서울+0.055초·부산+0.031초다. 가벼운 말의추가 손실 직접 대비는 불확실하고,최근·모형별로크기가달라 확정 보정으로채택하지 않았다. [원 보고서](../20261008_body_load_time_loss/README.md).''',
R/'conclusions/SOURCES.md':'''## 마체중별 부담중량과 기록 차이 후속

기존11번의 [체중×중량 직접 대비](../20261008_body_load_time_loss/README.md)를 추가했다.151,074행 재사용·65모형/3705대비·23독립 모형/366대비·760수치검사를 보존했다. [중앙11A](11A_BODY_LOAD_TIME.md) · [출처](../20261008_body_load_time_loss/SOURCES.md) · [독립 검증](../20261008_body_load_time_loss/outputs/verification.json) · [게시요약](../20261008_body_load_time_loss/PUBLICATION.md) · [용량](../20261008_body_load_time_loss/outputs/artifact_inventory.json). 조건부 관찰 연구이며 기존 독립연구수·원 결과·운영은변경하지 않았다.'''}
for p,entry in entries.items():
 old=p.read_text();new=old if mark in old else old.rstrip()+'\n\n\n'+entry+' '+mark+'\n';mutate(p,new,old)
p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(rec)
  else:m[key][idx]=rec
m['body_load_time_followup_added']=True;m['body_load_time_followup_note']='기존11번 후속. 말/경주 효과·체중×중량 직접 대비와 최근/선택 민감도. 인과 손실·운영 보정 미확정.'
m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();marker='<!-- '+H.name+' -->';new=old if marker in old else old.rstrip()+'\n| 2026-10-08 | 마체중별 부담중량 기록 차이 | 집계 중 | '+marker+'\n';mutate(p,new,old)
print('registered body/load follow-up with task-only shared deltas')
