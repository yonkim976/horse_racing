"""Append 28E without replacing concurrent shared-index content."""
from pathlib import Path
import json,hashlib,re
import pandas as pd
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={r['path']:r for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']}
bp=O/'shared_edits_baseline.json';op=O/'shared_own_edits.json';before={r['path']:r for r in json.loads(bp.read_text())['files']} if bp.exists() else {};own={r['path']:r for r in json.loads(op.read_text())['files']} if op.exists() else {}
def mutate(p,new,expected):
    old=p.read_text();assert old==expected,'Concurrent edit: reread latest';name=str(p.relative_to(ROOT))
    if name not in before:before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);own[name]=dict(path=name,own_delta_bytes=0)
    if old!=new:assert p.read_text()==old;p.write_text(new);own[name]['own_delta_bytes']+=len(new.encode())-len(old.encode())
    own[name]['own_final_bytes']=before[name]['bytes']+own[name]['own_delta_bytes'];bp.write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');op.write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(own.values())),ensure_ascii=False,indent=2)+'\n')
central=R/'conclusions/28E_PACE_CONDITION_VALIDATION.md';assert not central.exists();intro=(H/'PUBLICATION.md').read_text().split('\n\n');central.write_text('# 거리·함수율별 전개 예측 성능과 모델 활용\n\n2026-10-08 · 연구28 후속28E. 이전28C/28D를 보존하고 같은2024~2025 예측을 조건별로 평가했다.\n\n'+'\n\n'.join(intro[1:])+'\n\n전체 상대를 반영한157개 입력 N과297개 입력 B의 분류 성능은 비슷했다. 개별 각질 이름보다 네 확률을 보존하고 선입 약점을 먼저 검증할 필요가 있다. 정확거리·함수율·지역·연도·교차표와 표본 지원, 독립 군집/공통셀 검증을 원 보고서에 보존했다. 독립 연구 수41과 운영을 유지한다.\n\n'+f'[보고서](../{H.name}/README.md) · [출처](../{H.name}/SOURCES.md) · [조건별 성능](../{H.name}/outputs/condition_metrics.csv) · [공통조건 차이](../{H.name}/outputs/standardized_contrasts.csv) · [검증](../{H.name}/outputs/verification.json) · [게시요약](../{H.name}/PUBLICATION.md) · [용량](../{H.name}/outputs/artifact_inventory.json).\n')
# Resolve local summary links for the central document's different directory.
text=central.read_text()
for target in ['README.md','outputs/condition_metrics.csv','outputs/verification.json']:text=text.replace(']('+target+')',f'](../{H.name}/{target})')
central.write_text(text)
mark='<!-- pace_condition_validation_v1 -->';p=R/'conclusions/README.md';old=p.read_text();count_before=max(int(n) for n in re.findall(r'^\| (\d+) \|',old,re.M));entry='| [거리·함수율별 전개 예측](28E_PACE_CONDITION_VALIDATION.md) | 연구28 후속·조건별 정확도/선입 약점·동일 조건 차이·모델 활용 |\n';new=old.replace('| [원 보고서 목록]',entry+'| [원 보고서 목록]',1);new=new.rstrip()+f'\n\n[거리·함수율별 전개 검증](../{H.name}/README.md) · [후속28E](28E_PACE_CONDITION_VALIDATION.md). 독립 연구 수 유지. '+mark+'\n';assert mark not in old;mutate(p,new,old);count_after=max(int(n) for n in re.findall(r'^\| (\d+) \|',new,re.M));assert count_before==count_after
p=R/'README.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n[거리·함수율별 각질 예측 성능]({H.name}/README.md): 연구28 후속28E. 최근각질 빈도 대비 학습 모형의 개선과 거리/주로별 관측 정확도, 공통조건 차이, 선입 재현율의 약점을 확인했다. 새 입상 연결·현재 함수율 입력·운영 변경은 미실험. [중앙28E](conclusions/28E_PACE_CONDITION_VALIDATION.md). '+mark+'\n',old)
p=R/'conclusions/SOURCES.md';old=p.read_text();mutate(p,old.rstrip()+f'\n\n## 거리·함수율별 전개 후속28E\n\n[보고서](../{H.name}/README.md) · [중앙28E](28E_PACE_CONDITION_VALIDATION.md) · [출처/해시](../{H.name}/SOURCES.md) · [검증](../{H.name}/outputs/verification.json) · [게시요약](../{H.name}/PUBLICATION.md) · [용량](../{H.name}/outputs/artifact_inventory.json). 기존28C/28D 시간순 확률과 API4_3 원문 함수율을 평가 전원에 연결했다. 실제 함수율 층화와 사전 입력을 구분하며 거리·주로 모형의 개선/입상 연결은 미확정이다. '+mark+'\n',old)
p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
    for f in paths:
        name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
        if idx is None:m[key].append(rec)
        else:m[key][idx]=rec
m['pace_condition_validation_added']=True;m['pace_condition_validation_note']='연구28 후속28E. 2024~2025 거리/실제 함수율별 저장 예측 성능, 조건 일치 차이와 선입 재현율 검증. 모형 재학습/입상 연결/운영 변경 없음.';dates=pd.read_parquet(O/'evaluation_rows.parquet',columns=['meet','date']).groupby('meet').date.max();m['data_end_by_study'][H.name]={k:str(v.date()) for k,v in dates.items()}|dict(scope='평가2024~2025; 기존 학습/자료 종료는28C/28D 계약 참조');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();mutate(p,old.rstrip()+'\n| 2026-10-08 | 거리·함수율별 전개 예측 | 집계 중 | <!-- '+H.name+' -->\n',old)
(O/'registration.json').write_text(json.dumps(dict(followup='28E',independent_study_count_before=count_before,independent_study_count_after=count_after,shared_files=5),ensure_ascii=False,indent=2)+'\n');print('Registered 28E',count_before,count_after)
