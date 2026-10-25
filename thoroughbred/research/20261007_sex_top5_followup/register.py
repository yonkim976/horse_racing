"""Append the top-five follow-up to current research indexes."""
from pathlib import Path
import json,hashlib
H=Path(__file__).resolve().parent;ROOT=H.parents[2];R=H.parent;O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((O/'baseline_inventory.json').read_text());initial={a['path']:a for a in b['related_existing_files']}
if not (O/'shared_edits_baseline.json').exists():
 rows=[]
 for name in b['shared_paths']:
  p=ROOT/name;rows.append(dict(path=name,bytes=p.stat().st_size,sha256=sha(p),outside_task_delta_before_edit=p.stat().st_size-initial[name]['bytes']))
 (O/'shared_edits_baseline.json').write_text(json.dumps(dict(recorded_immediately_before_own_shared_edits=True,files=rows),ensure_ascii=False,indent=2)+'\n')
central=R/'conclusions/25B_SEX_TOP5.md'
central.write_text('''# 5위 이내 성별 기록과 성과
2026-10-07.25번 성별·25A체중/거리 연구의 후속이다. 최종1~5위 출전69,639행을151,074행에서 선택했다. 평생 우수마나 고등급이 아닌 출전별 결과 선택이다. 이전 연구는 유지했다.

같은 정확 거리·연도·월·나이·등급·함수율과 중량·체중·rating·과거 성적을 맞춘5위 이내 전체시간 암−수는 서울 단거리+0.052초[+0.011,+0.093]·중거리+0.229초[+0.115,+0.343], 부산 단거리+0.068초[+0.017,+0.118]·중거리+0.013초[−0.084,+0.110]다. 연구용 단거리1000~1400m·중거리1600~1800m이며1900m 이상에 확장하지 않는다.

단거리 차이의 점추정은 전체 출전의 약0.13/0.12초보다 작아지지만 암말 우세로 바뀌지 않았다. 서울 중거리 수말 우세는 남고 부산 중거리는 불확실하다. 상위5위 단거리 초반200m는 암말이0.044/0.056초 빠르지만 막판은0.048/0.090초 느리다. 암말 마체중은 상위5위에서도 수말보다 약20~21kg·거세마보다 약14kg 가볍다.

전체 출전자에서 같은 경주5위 이내 성과를 비교하면 암−수는 서울 단거리−4.75%p·중거리−6.63%p, 부산−3.40%p·−5.15%p이며 네 점별95%구간은0보다 낮다. 이는 상위5위끼리만의 기록 차이와 다른 질문이다. 중거리−단거리 진입 성과 직접 대비는 양 지역 모두 불확실하다.

상위5위 선택에 따라 공통층 구성·가중치가 바뀐다. 같은 경주5위 이내끼리 기록을 비교하면 서울 단거리+0.021초 구간은0을 포함하고 중거리+0.143초는 느린 방향이 남는다. 부산은 단거리+0.060초·중거리+0.065초로 후자는0을 포함한다. 최근2024~2025·10두 이상 민감도에서도 세부 결과가 바뀌므로 고정된 거리/성별 법칙으로 보지 않는다.

[원 보고서](../20261007_sex_top5_followup/README.md) · [출처/방법/해시](../20261007_sex_top5_followup/SOURCES.md) · [1073검사/252독립 계산/432이전 결과 재현](../20261007_sex_top5_followup/outputs/verification.json) · [전체1704대비](../20261007_sex_top5_followup/ALL_RESULTS.md) · [게시 요약](../20261007_sex_top5_followup/PUBLICATION.md) · [용량 명세](../20261007_sex_top5_followup/outputs/artifact_inventory.json). 관찰 연구이며 결과 선택·미관측 편성/건강/훈련과 정상 완주 선택 한계가 남는다. 사전 예측·인과효과·성별 보정·운영 적용을 확정하지 않는다.
''')
mark='<!-- sex_top5_followup_v1 -->'
entries={R/'README.md':'''[5위 이내 성별 기록과 진입 성과 후속](20261007_sex_top5_followup/README.md):69,639상위5위 출전에서 단거리 암−수 차이는 작아지지만 암말 우세로 바뀌지 않는다. 서울 중거리 수말 우세와 부산 불확실성을 구분하고,전체 출전자5위 이내 성과·동일 경주 상위권 기록·최근/10두 이상 민감도를 검증했다. [중앙25B후속](conclusions/25B_SEX_TOP5.md), 결과 선택의 관찰 차이이며 운영 변경 없음.''',
R/'conclusions/README.md':'''## 5위 이내 성별 기록 후속

[25B후속 결론](25B_SEX_TOP5.md): 상위5위 출전69,639행에서 단거리 격차는 작아지지만 암말 전체 기록 우세는 확인되지 않았다. 서울 중거리는 수말이 빠른 방향이 남고 부산은 불확실하다. 상위권끼리의 기록과 전체 출전자에서5위 이내 진입 성과를 구분했다. [원 보고서](../20261007_sex_top5_followup/README.md).''',
R/'conclusions/SOURCES.md':'''## 5위 이내 성별 기록과 성과 후속

기존32번 성별 연구의 추가 후속으로 [상위5위 기록/전체 출전자 진입 성과](../20261007_sex_top5_followup/README.md)를 추가했다. 원151,074행 중69,639행·입력5개 해시·432이전 결과 재현·252독립 모형행·1073수치 검사를 보존했다. [중앙25B](25B_SEX_TOP5.md) · [출처](../20261007_sex_top5_followup/SOURCES.md) · [검증](../20261007_sex_top5_followup/outputs/verification.json) · [게시 요약](../20261007_sex_top5_followup/PUBLICATION.md) · [용량](../20261007_sex_top5_followup/outputs/artifact_inventory.json). 이전 연구·독립 연구 수·기준·운영 변경 없음.'''}
for p,entry in entries.items():
 old=p.read_text()
 if mark not in old:p.write_text(old.rstrip()+'\n\n\n'+entry+' '+mark+'\n')
p=R/'conclusions/source_manifest.json';m=json.loads(p.read_text())
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(rec)
  else:m[key][idx]=rec
m['sex_top5_followup_added']=True;m['sex_top5_followup_note']='기존 성별 연구의 추가 후속. 착순1~5위 선택 기록과 전체 출전자5위 이내 성과 분리. 기존 결과·기준·운영 변경 없음.'
m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18')
p.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n');print('registered top5 follow-up')
