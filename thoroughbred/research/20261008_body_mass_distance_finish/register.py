"""Append follow-up links, preserving other studies and shared-file task deltas."""
from pathlib import Path
import hashlib,json
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={a['path']:a for a in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']};bp=O/'shared_edits_baseline.json';op=O/'shared_own_edits.json';before={a['path']:a for a in json.loads(bp.read_text())['files']} if bp.exists() else {};own={a['path']:a for a in json.loads(op.read_text())['files']} if op.exists() else {}
def mutate(p,new,expected):
 old=p.read_text();assert old==expected,'Concurrent edit: reread latest contents';name=str(p.relative_to(ROOT))
 if name not in before:before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);own[name]=dict(path=name,own_delta_bytes=0)
 if old!=new:
  assert p.read_text()==old; p.write_text(new);own[name]['own_delta_bytes']+=len(new.encode())-len(old.encode())
 own[name]['own_final_bytes']=before[name]['bytes']+own[name]['own_delta_bytes'];bp.write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');op.write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(own.values())),ensure_ascii=False,indent=2)+'\n')
central=R/'conclusions/11D_BODY_MASS_DISTANCE_FINISH.md'
central.write_text('''# 체중과 거리별 기록·막판 통념 검토

2026-10-08. ‘절대체중이 무거우면 단거리에서 느리다’, ‘가벼우면 긴 거리에서 막판에 처진다’는 두 가설은 이번 자료에서 일반 법칙으로 확인되지 않았다. 기존 11번 중량 연구의 후속이며 독립 연구 수와 이전 결론을 유지한다.

서울·부산 정상 151,074출전 중 충분한 1000~1800m 13지역×거리 148,126출전을 사용했다. 절대체중은 같은 경주·부담중량·연령·rating·과거 성과를 맞춘 말 간 비교이고, 자기 기준은 현재를 제외한 과거5개 관측 평균(최소3개)에서 벗어난 정도를 같은 말과 경주 안에서 비교한 104,752출전이다. 당일 절대체중을 순수 골격·체지방 효과와 동일시하지 않는다.

단거리1000~1400m의 공통1200m 환산에서 절대510 대480kg는 −0.022초 [−0.039,−0.006]로 느리지 않았다. 성별 통제와4세 이상에서는0을 포함해 큰 말의 이점을 확정하지 않는다. 자기 기준+10kg는 +0.042초 [+0.023,+0.061]로 느린 경향이 최근 완결연도와4세 이상에서도 남았다. 다만 전체시간 효과의 단거리−1600~1800m 차이는 −0.015초/1000m [−0.045,+0.015]로 단거리에 특별히 불리하지 않았다.

1600~1800m의 마지막200m는 절대450 대480kg −0.016초 [−0.027,−0.005], 자기 기준−10kg −0.012초 [−0.028,+0.003]다. 앞선 전개를 맞췄을 때 가벼운 말의 막판 불리함은 확인되지 않았다. 전개 미통제·마지막600m·마지막200m와 직전400m의200m당 시간 차이도 가벼움의 처짐을 지지하지 않았다. 가벼움의 긴 거리−단거리 차이도0을 포함한다. 느린 막판과 피로/체력 고갈의 기전은 구분한다.

주분석 뒤 추가한 범주형 탐색에서530kg 이상 대470~489kg 단거리 차이는 공통1200m 환산 +0.018초 [−0.047,+0.083],430kg 이하의 긴 거리 마지막200m는 −0.019초 [−0.059,+0.021]로 불확실했다. 자기 기준+15kg 이상은 −5~+5kg 대비 단거리 공통1200m 환산 +0.144초 [+0.087,+0.202]였으나,−15kg 이하의 긴 거리 막판 불리함은 확인되지 않았다. 극단 탐색4검정 BH와 사전 주대비/거리 차이8검정 BH를 구분해 보존했다. 생리적 과체중 경계를 정한 것은 아니다.

1900m 이상은 희소하여 장거리 전체로 일반화하지 않는다. 같은 말·실제 날짜의 거리/지역 간 의존을 반영했고, 원문18파일151,074건과21개 해시를 검증했다. 별도 희소 고정효과/LU·QR·군집 합산으로456거리 모형·216거리군 모형·108공동 비교 및3,344수치검사를 통과했다. 범주형248거리 계수 묶음과932수치검사도 보존했다. 원천/수치 검증을 인과적 입증이나 미래예측 검증으로 표현하지 않는다. 확정 보정·체중 처방·DB·운영·배포 변경은 없다.

[보고서](../20261008_body_mass_distance_finish/README.md) · [출처](../20261008_body_mass_distance_finish/SOURCES.md) · [독립 검증](../20261008_body_mass_distance_finish/outputs/verification.json) · [게시요약](../20261008_body_mass_distance_finish/PUBLICATION.md) · [용량](../20261008_body_mass_distance_finish/outputs/artifact_inventory.json).
''')
mark='<!-- body_mass_distance_finish_v1 -->'
entries={R/'README.md':'''[체중과 거리별 기록·막판 통념 검토](20261008_body_mass_distance_finish/README.md): 절대체중이 무거우면 단거리에, 가벼우면1600~1800m 막판에 불리하다는 통념은 확인되지 않았다. 자기 과거 기준+10kg의 공통1200m 환산은 약+0.042초이나 단거리만의 추가 불리함은 미확정이다. 극단 체중 범주·막판 둔화·직접 거리 차이를 검토했다. [중앙11D](conclusions/11D_BODY_MASS_DISTANCE_FINISH.md). 연구 후속이며 보정·운영 변경 없음.''',R/'conclusions/README.md':'''## 체중과 거리별 기록·막판 가설 후속

[11D 체중과 거리별 기록·막판 통념](11D_BODY_MASS_DISTANCE_FINISH.md): 절대체중의 단거리 무거움/긴 거리 가벼움 불리함은 확인되지 않았다. 자기 기준 무거움은 느린 전체기록에 동반됐지만 단거리에 특별히 불리하지 않았다. [원 보고서](../20261008_body_mass_distance_finish/README.md).''',R/'conclusions/SOURCES.md':'''## 체중과 거리별 기록·막판 가설 후속

기존11번의 [체중과 거리별 기록·막판 통념 검토](../20261008_body_mass_distance_finish/README.md)를 연결했다. 절대체중과 현재를 제외한 과거5개 기준 편차, 단거리/1600~1800m 직접 차이, 마지막200m·600m·직전 구간 대비 둔화, 사후 극단 범주를 구분한다. [중앙11D](11D_BODY_MASS_DISTANCE_FINISH.md) · [출처](../20261008_body_mass_distance_finish/SOURCES.md) · [검증](../20261008_body_mass_distance_finish/outputs/verification.json) · [게시요약](../20261008_body_mass_distance_finish/PUBLICATION.md) · [용량](../20261008_body_mass_distance_finish/outputs/artifact_inventory.json). 체중 인과효과·피로 기전·1900m 이상 장거리·운영 보정을 확정하지 않는다. 이전 결과와 독립 연구 수를 유지한다.'''}
for p,entry in entries.items():
 old=p.read_text();mutate(p,old if mark in old else old.rstrip()+'\n\n'+entry+' '+mark+'\n',old)
p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(rec)
  else:m[key][idx]=rec
m['body_mass_distance_finish_followup_added']=True;m['body_mass_distance_finish_followup_note']='기존11번 후속. 절대체중 단거리 무거움/긴 거리 가벼움 불리함 미확인; 자기 기준 증가의 느린 관계와 거리 차이 구분. 극단 범주는 사후 탐색.';m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();marker='<!-- '+H.name+' -->';mutate(p,old if marker in old else old.rstrip()+'\n| 2026-10-08 | 체중과 거리별 기록·막판 가설 | 집계 중 | '+marker+'\n',old);print('Registered follow-up and task-only shared deltas')
