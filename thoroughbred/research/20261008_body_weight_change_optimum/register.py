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
central=R/'conclusions/11C_BODY_WEIGHT_CHANGE_OPTIMUM.md'
central.write_text('''# 마체중 변화와 기록 및 적정체중

2026-10-08. 같은 말과 같은 경주·부담중량·과거 성적을 맞추면 큰 체중 증감과 자기 평소 체중에서 큰 편차가 느린 기록에 동반됐다. 모든 말에 공통인 절대 최적체중이나 거리별 최적 kg는 확인되지 않았다. 기존11번 중량 연구의 후속이며 성별별 기준은 만들지 않았다.

151,074출전의 원문18파일에서 체중과 괄호 증감을 재검증했다. 수치 증감140,926행, 과거 이력 날짜와 두 관측 체중이 같아 확인된0변화9,464행, 미해결 결측684행을 구분했다. 원문 빈값을 일괄0으로 바꾸지 않았다. 반복 비교 가능한 증감133,681출전에서 변화0kg 대비−10kg/+10kg의 공통1200m 환산 차이는약+0.019/+0.057초,−20kg/+20kg는+0.115/+0.190초다. 구간 모형에서도 큰 증감의 느린 방향은 남았으나 작은 감량은 불확실했다.

각 말의 전체 관측 평균에서±10kg 벗어날 때 공통1200m 환산으로 약+0.096/+0.101초였다. 그러나 이 평균은 나중 출전도 사용하는 후향 참조다. 현재를 제외한 직전5개 관측 평균(최소3개)을 쓰면104,752출전에서−10kg/+10kg 차이가약+0.039/+0.047초로 작아졌으나 U자형 관계는 남았다. 서로 표본도 달라 감소 원인을 참조방식 하나로 분해하지 않는다.

1000~1800m13지역×거리에서 지원되는 절대 최소체중은 모두 미확정이다. 전기간 자기평균 대비 곡률은12개,과거5개 기준은2개가 점별 최소 기준과거리별BH를 통과했다. 관측 중앙체중은 최적체중이 아니며,거리별 최소점 차이를 직접 검정하지 않아 거리가 늘수록 최적체중이 증가한다는 공식을 만들지 않았다.

개인 탐색은 같은 지역·거리24출전/8체중값/20kg 범위 이상의103그룹·100두였다.84그룹의 곡선이 추정 가능했고 점별 U자형 최소 후보5그룹은BH 후0개였다. 시간분할 학습 후보2개 중 후기 곡선 추정 가능1개가10kg 이내로 반복됐지만 학습BH 통과 반복후보는0개다. 자료가 부족한 경우를 효과0이나 반복 실패로 바꾸지 않았다. 말마다 평소 체중 범위를 참고할 이유는 있지만 개별 최적 kg는 확정하지 않았다.

성장·컨디션·훈련·휴양과 능력 변화가 남는 조건부 관찰 연구다. 공동 말/경주 모형과 개인 상대기록 탐색을 구분했고,경주 평균을 결과자료로 사용하는 개인 반복 진단을 미래 기록 사전예측으로 표현하지 않았다. 기록 보정·체중 처방·운영·DB·배포는 변경하지 않았다.

[보고서](../20261008_body_weight_change_optimum/README.md) · [출처](../20261008_body_weight_change_optimum/SOURCES.md) · [독립 검증](../20261008_body_weight_change_optimum/outputs/verification.json) · [게시요약](../20261008_body_weight_change_optimum/PUBLICATION.md) · [용량](../20261008_body_weight_change_optimum/outputs/artifact_inventory.json). 원문151,074건,희소LU/QR182거리·42공통·24개인모형 및1,324수치검사를 보존했다. 이전 결과와 독립 연구수는 유지한다.
''')
mark='<!-- body_weight_change_optimum_v1 -->'
entries={R/'README.md':'''[마체중 변화와 기록 및 적정체중](20261008_body_weight_change_optimum/README.md): 같은 말/경주·이력을 맞춘 큰 증감과 자기 평균에서 큰 편차는 느린 기록에 동반됐다. 과거5개 평균−10kg/+10kg의 공통1200m 환산은약+0.039/+0.047초다.13거리의 절대 최적체중과 개인 최적 kg는 미확정이며 [중앙11C](conclusions/11C_BODY_WEIGHT_CHANGE_OPTIMUM.md)에 근거를 보존했다. 기록 보정·운영 변경 없음.''',
R/'conclusions/README.md':'''## 마체중 변화와 적정체중 후속

[11C 마체중 변화와 적정체중](11C_BODY_WEIGHT_CHANGE_OPTIMUM.md): 큰 증감과 자기 평소 범위의 큰 이탈은 느린 기록에 동반됐다. 미래를 제외한 과거5개 체중 평균의−10kg/+10kg 차이는 공통1200m 환산으로약+0.039/+0.047초다.13지역×거리의 절대 최소체중과 개인 최적 kg는 미확정이다. [원 보고서](../20261008_body_weight_change_optimum/README.md).''',
R/'conclusions/SOURCES.md':'''## 마체중 변화와 적정체중 후속

기존11번의 [마체중 변화·자기 기준 편차·절대 최소체중](../20261008_body_weight_change_optimum/README.md)을 연결했다. 원문18파일·151,074행과 확인된0변화 복원,과거5개 체중 참조,개인 곡선의 시간분할/BH를 보존했다. [중앙11C](11C_BODY_WEIGHT_CHANGE_OPTIMUM.md) · [출처](../20261008_body_weight_change_optimum/SOURCES.md) · [독립검증](../20261008_body_weight_change_optimum/outputs/verification.json) · [게시요약](../20261008_body_weight_change_optimum/PUBLICATION.md) · [용량](../20261008_body_weight_change_optimum/outputs/artifact_inventory.json). 공동 고정효과와개인 상대기록 탐색을 구분하며,인과손실·개별체중처방·미래예측검증·운영반영은아니다. 이전결과와독립연구수를유지했다.'''}
for p,entry in entries.items():
 old=p.read_text();new=old if mark in old else old.rstrip()+'\n\n\n'+entry+' '+mark+'\n';mutate(p,new,old)
p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(rec)
  else:m[key][idx]=rec
m['body_weight_change_optimum_followup_added']=True;m['body_weight_change_optimum_followup_note']='기존11번후속. 원문증감·자기평균/과거5개편차·개인곡선 반복성. 절대/개인최적kg 미확정,보정/처방미채택.'
m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();marker='<!-- '+H.name+' -->';new=old if marker in old else old.rstrip()+'\n| 2026-10-08 | 마체중 변화와 적정체중 | 집계 중 | '+marker+'\n';mutate(p,new,old)
print('Registered body-mass follow-up with task-only shared deltas')
