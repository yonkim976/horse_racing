"""Append this follow-up to current indexes without rewriting earlier studies."""
from pathlib import Path
import json,hashlib
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs';R=H.parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
baseline=json.loads((O/'baseline_inventory.json').read_text());initial={a['path']:a for a in baseline['related_existing_files']}
# Freeze immediate pre-edit sizes once; rerunning registration does not move the baseline.
if not (O/'shared_edits_baseline.json').exists():
 files=[]
 for name in baseline['shared_paths']:
  p=ROOT/name;files.append(dict(path=name,bytes=p.stat().st_size,sha256=sha(p),outside_task_delta_before_edit=p.stat().st_size-initial[name]['bytes']))
 (O/'shared_edits_baseline.json').write_text(json.dumps(dict(recorded_immediately_before_own_shared_edits=True,files=files),ensure_ascii=False,indent=2)+'\n')
central=R/'conclusions/25A_SEX_WEIGHT_DISTANCE.md'
central.write_text('''# 성별 마체중과 단거리 중거리 경기력

2026-10-07. 기존25번 성별 연구의 체중·거리 질문을 직접 검증한 후속 결과다. 이전 완료 연구는 유지하고 새 분석을 별도 폴더에 보존했다.

암말의 출전 평균 마체중은 서울465.42kg·부산467.86kg, 수말486.99kg·489.01kg, 거세마480.70kg·482.54kg다. 암말은 수말보다 약21kg·거세마보다 약15kg 가볍다. 말별 동일 가중에서도 약22kg, 같은 나이·등급·거리·연도·월·정확 함수율을 맞춰도 암−수 약−18~−19kg 차이가 남는다. 부담중량의 관측 평균 차이는 약−1.31kg이며 공식 감량 규정 수치로 해석하지 않는다.

연구용1000~1400m 묶음에서 조건·중량·체중·rating·과거 성적 통제 후 전체시간 암−수는 서울+0.131초[+0.080,+0.181]·부산+0.119초[+0.064,+0.173]다. 암말이 단거리 경주 전체에서 더 우수하다는 주장은 확인되지 않았다. 출발200m는−0.041·−0.052초로 빠르지만 마지막200m는+0.097·+0.111초로 느리다.

1600~1800m 전체 암−수는 서울+0.231초·부산+0.224초다. 중거리−단거리 직접 대비는 서울+0.100초[−0.028,+0.227]·부산+0.105초[−0.023,+0.233]로 양쪽 모두0을 포함한다.1000m당 초 대비도 불확실하다. 같은 경주3위 이내 성과는 서울에서 중거리 열세가 단거리보다−3.11%p 더 컸지만 부산−1.52%p는 구간이0을 포함한다.2024~2025년만 쓰면 불확실성이 커진다.

1900m 이상은 암말 서울203행·부산134행으로 희소하고 정확 조건을 맞추면 더 줄어 보편적 우열을 판단하지 않았다. 거세마의 체중 순서를 경기력 순서나 거세 인과효과로 바꿀 수 없다. 모든 결과는 선택된 출전 집단의 관찰 연관이며 성별 보정·별도 기준표·운영 예측 개선을 확정하지 않는다.

[원 보고서](../20261007_sex_weight_distance_followup/README.md) · [출처와 방법](../20261007_sex_weight_distance_followup/SOURCES.md) · [524수치 검증](../20261007_sex_weight_distance_followup/outputs/verification.json) · [모든816대비](../20261007_sex_weight_distance_followup/ALL_RESULTS.md) · [게시 요약](../20261007_sex_weight_distance_followup/PUBLICATION.md) · [용량 명세](../20261007_sex_weight_distance_followup/outputs/artifact_inventory.json).
''')
marker='<!-- sex_weight_distance_followup_v1 -->'
entries={R/'README.md':'''[성별 평균 마체중과 단거리·중거리 우위 통념 후속](20261007_sex_weight_distance_followup/README.md): 암말은 수말보다 약21kg·거세마보다 약15kg 가볍다. 단거리 전체 암말 우세는 확인되지 않았고, 출발200m의 작은 우세와 전체/막판/착순을 구분했다. 거리 증가 직접 대비·1000m당 시간·같은 경주 성과·완결연도 민감도를 검증했다. [중앙 후속 결론](conclusions/25A_SEX_WEIGHT_DISTANCE.md), 기존25번 연구의 후속이며 운영 반영 없음.''',
 R/'conclusions/README.md':'''## 성별 체중과 거리별 성과 후속

[25번 후속 결론](25A_SEX_WEIGHT_DISTANCE.md): 암말 마체중은 수말보다 약21kg·거세마보다 약15kg 가볍지만 단거리 경주 전체의 우세는 확인되지 않았다. 초반200m와 전체/막판/입상을 구분하고 중거리−단거리 직접 대비와1000m당 시간을 검증했다.1900m 이상은 희소하며 최근 완결연도 결과는 더 불확실하다. [원 보고서](../20261007_sex_weight_distance_followup/README.md).''',
 R/'conclusions/SOURCES.md':'''## 성별 평균 체중과 거리별 성과 후속

기존32번 성별 연구의 후속으로 [마체중과 거리 상호작용](../20261007_sex_weight_distance_followup/README.md)을 추가했다.151,074행을 읽기 전용 재사용하고 세 성별 쌍·공동모형 직접 대비·같은 경주·완결2024~2025년 민감도를 계산했다. [중앙 결론](25A_SEX_WEIGHT_DISTANCE.md) · [출처/해시](../20261007_sex_weight_distance_followup/SOURCES.md) · [독립 검증](../20261007_sex_weight_distance_followup/outputs/verification.json) · [게시 자료](../20261007_sex_weight_distance_followup/PUBLICATION.md) · [용량](../20261007_sex_weight_distance_followup/outputs/artifact_inventory.json). 기존 독립 연구 수·기준·운영은 변경하지 않았다.'''}
for p,entry in entries.items():
 old=p.read_text()
 if marker not in old:p.write_text(old.rstrip()+'\n\n\n'+entry+' '+marker+'\n')
p=R/'conclusions/source_manifest.json';m=json.loads(p.read_text())
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));record=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(record)
  else:m[key][idx]=record
m['sex_weight_distance_followup_added']=True
m['sex_weight_distance_followup_note']='25번/기존32번 성별 연구의 후속. 마체중·거리 직접 대비·동반 출전 성과 새 계산. 기존 독립 연구 수·원 결과·기준·운영 변경 없음.'
m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18')
p.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
print('registered follow-up')
