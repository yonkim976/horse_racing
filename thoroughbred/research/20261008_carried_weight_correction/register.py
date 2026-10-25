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
central=R/'conclusions/11B_CARRIED_WEIGHT_CORRECTION.md'
central.write_text('''# 성별 구분 없는 부담중량 기록 보정계수

2026-10-08. 기존11번/11A의 후속이다. 모든 성별을 합치고 성별 피처·체중 상호작용을 제외한 단일 kg 계수를 새로 적합했다. 정상151,074행 중13개 지역×정확 거리에서 같은 말/경주와 과거 이력을 맞춘134,233출전이 주 분석에 남았다.

전체기간1kg의 평균 차이는1000m당 서울+0.030초·부산+0.033초,전체+0.031초(점별95% 약[+0.024,+0.038])다. 연구용 설명값0.03초/(kg·1000m)는1200m1kg+0.036초·3kg+0.108초에 해당한다.54kg환산=원시간−0.03×(부담중량−54)×거리/1000이다. 같은 원시간이면 더 무거운 중량에서 뛴 출전을 조금 높게 평가한다.

이는 거리 비례를 강제한 공통 관찰 계수다. 별도1200m 추정은 서울+0.059초/kg·부산+0.031초/kg이며 거리마다 다르다. 체중 직접항 추가는 공통계수를 거의 바꾸지 않았지만 이력/rating 없는 같은 말/경주 모형은 전체 약0.018초로 작아졌다. 실력·중량 배정의 시간 변화가 남아 순수한 인과 손실로 확정하지 않는다.

최근2024~2025년의 전체 공통계수는약+0.014초로 작아지고95%구간에0이 포함된다.2024/2025/2026각1~8월 보류진단의 오차 변화도작고,서울2026에서는소폭악화했다. 보류기간의말/경주·이력을그기간내맞췄으므로다음경주예측검증이아니다.0.03은평균설명용연구초안이고,추가고정보정채택은0(보류)이며효과가0이라는뜻이아니다. 운영 모델·기존기준·DB·배포는변경하지않았다.

[보고서](../20261008_carried_weight_correction/README.md) · [출처/방법](../20261008_carried_weight_correction/SOURCES.md) · [독립 검증](../20261008_carried_weight_correction/outputs/verification.json) · [게시요약](../20261008_carried_weight_correction/PUBLICATION.md) · [용량](../20261008_carried_weight_correction/outputs/artifact_inventory.json). 기존 독립연구수에 새 번호를 더하지 않는11번후속이며 이전 연구 원본을 보존했다.
''')
mark='<!-- carried_weight_correction_v1 -->'
entries={R/'README.md':'''[성별 구분 없는 부담중량 기록 보정계수](20261008_carried_weight_correction/README.md): 같은 말/경주·이력을 맞춘134,233출전의 전체 평균은1kg당1000m약0.031초다. 설명값0.03이면1200m3kg차이0.108초지만 최근 구간은0을 포함하고 거리별값도 달라 고정 보정 채택은 보류했다. [중앙11B](conclusions/11B_CARRIED_WEIGHT_CORRECTION.md), 다음 경주 예측 검증·운영 변경 없음.''',
R/'conclusions/README.md':'''## 성별 구분 없는 부담중량 평균 보정 후속

[11B 부담중량 평균](11B_CARRIED_WEIGHT_CORRECTION.md): 성별 피처·체중 상호작용 없이 같은 말/경주와 이력을 맞춘전체 평균은1kg당1000m+0.031초다.0.03초의연구용비교식을제시했지만최근구간·거리별차이로고정보정채택은보류했다. [원 보고서](../20261008_carried_weight_correction/README.md).''',
R/'conclusions/SOURCES.md':'''## 성별 구분 없는 부담중량 평균 보정 후속

기존11번의 [단일 kg 후속](../20261008_carried_weight_correction/README.md)을 추가했다.151,074행을읽기전용재사용해동일말/경주·이력을맞추고,최근완결연도와세연도의과거고정계수적용을진단했다. [중앙11B](11B_CARRIED_WEIGHT_CORRECTION.md) · [출처](../20261008_carried_weight_correction/SOURCES.md) · [독립검증](../20261008_carried_weight_correction/outputs/verification.json) · [게시요약](../20261008_carried_weight_correction/PUBLICATION.md) · [용량](../20261008_carried_weight_correction/outputs/artifact_inventory.json). 조건부관찰평균이며다음경주예측검증·고정보정채택·운영변경은아니다. 기존독립연구수와원결과를보존했다.'''}
for p,entry in entries.items():
 old=p.read_text();new=old if mark in old else old.rstrip()+'\n\n\n'+entry+' '+mark+'\n';mutate(p,new,old)
p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(rec)
  else:m[key][idx]=rec
m['carried_weight_correction_followup_added']=True;m['carried_weight_correction_followup_note']='기존11번후속. 성별/체중분류 없는 단일kg 관찰평균과기간안정성. 고정보정채택보류,사전예측검증아님.'
m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();marker='<!-- '+H.name+' -->';new=old if marker in old else old.rstrip()+'\n| 2026-10-08 | 성별 구분 없는 부담중량 평균 보정 | 집계 중 | '+marker+'\n';mutate(p,new,old)
print('Registered carried-load follow-up; captured exact own shared deltas')
