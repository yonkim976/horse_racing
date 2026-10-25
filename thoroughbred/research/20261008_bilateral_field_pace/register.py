"""Append follow-up 28D while preserving concurrent shared-index changes."""
from pathlib import Path
import json,hashlib,re
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={r['path']:r for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']}
bp=O/'shared_edits_baseline.json';op=O/'shared_own_edits.json';before={r['path']:r for r in json.loads(bp.read_text())['files']} if bp.exists() else {};own={r['path']:r for r in json.loads(op.read_text())['files']} if op.exists() else {}
def mutate(p,new,expected):
 old=p.read_text();assert old==expected,'Concurrent edit: reread latest shared content';name=str(p.relative_to(ROOT))
 if name not in before:before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);own[name]=dict(path=name,own_delta_bytes=0)
 if old!=new:assert p.read_text()==old;p.write_text(new);own[name]['own_delta_bytes']+=len(new.encode())-len(old.encode())
 own[name]['own_final_bytes']=before[name]['bytes']+own[name]['own_delta_bytes'];bp.write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');op.write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(own.values())),ensure_ascii=False,indent=2)+'\n')
public=json.loads((H/'PUBLICATION.json').read_text());summary=(H/'PUBLICATION.md').read_text().split('\n\n');intro='\n\n'.join(summary[1:3]);central=R/'conclusions/28D_BILATERAL_FIELD_PACE.md';title='# 출전마 전원과 게이트 안팎의 전개 예측';assert not central.exists() or central.read_text().startswith(title)
central.write_text(title+f'''

2026-10-08 · 연구28 후속28D. 이전28C를 보존하고 외측 상대와 전원의 각질·구간 구성을 추가 검증했다.

{intro}

전체159,014출전·14,636경주·12,516두를 유지했다. 현재 실제 전개를 입력하지 않고 과거5/10실제슬롯·T−2·730일과 전년까지의 환경 기준을 재사용했다. 기수/조교사 성향·식별자와 기수 교체 표식도 모두 제외했다. 기존 F에는 교체 표식이 남아 있어 새 N 기준과 구분했다. 첫 마군 전체를 선행으로 분류하며 단독 선두나 작전 의도가 아니다.

전체/안쪽/바깥쪽에 같은 방식으로 네 각질 분포, 초반200m·마지막600/200m 원초/잔차와 지원, 선행/앞선후보 수, 자기보다 빠른 상대 수·빠른 선행후보·빠른 상대의 선행성향 합을 계산했다. 자기 제외 전원이며 신마/결측 상대를 빼지 않는다. 빈 방향의 평균은 미관측, 상대수와 합은0이다. 바깥 선행합 하나는 기존 전체−안쪽에서 계산할 수 있어 새 독립 정보가 아니다. 바깥의 속도·각질 구성이 확장 대상이다.

고정 LightGBM 설정으로2024·2025년36,638출전을 비교했다. N157개·A202개·B297개다. B−A가 방향 구분의 주 비교, A−N은 전원 구성 확장, N−oldF는 기수 교체 제거다. 세 대비 BH와 말/실제날짜/교집합 군집의 최대분산95%구간을 보존했다. 후반 회복/후퇴의 N−B는 전체 확장 효과이며 외측만의 효과가 아니다.

28C와 같은 마지막 날 마지막 경주21두·상대200쌍을 고정 예시로 저장했다.2026 사례 모형은2025년까지 학습했다. 실제 사전 명단 공표시각은 미감사이며 회고 예시다. 전원 정보는 전체/방향별 요약으로 사용했고 전체 주행경로의 공동확률은 만들지 않았다. 후보 수를 실제 경합/압박, 앞선 후퇴를 체력 소진, 순위 회복을 추입 의도로 단정하지 않는다.

독립 SQL 전원/안팎·자기제외·결측 집계, 게이트 대칭, 현재 결과/기수 변조, 별도 트리 경로·예측 전수·확률/군집/BH/교정·사례 상대 전수 검증을 통과했다. 계산 전119파일 중 공유5개를 제외한114개를 보존했다. 독립 연구 수41·기존 연구·DB·운영 모델·웹 배포는 유지했다.

[보고서](../{H.name}/README.md) · [초반 평가](../{H.name}/outputs/early_metrics.csv) · [군집구간](../{H.name}/outputs/early_comparisons.csv) · [전원/안팎 사례](../{H.name}/outputs/example_cards.csv) · [모든 상대 쌍](../{H.name}/outputs/example_rival_pairs.csv) · [출처](../{H.name}/SOURCES.md) · [검증](../{H.name}/outputs/verification.json) · [게시요약](../{H.name}/PUBLICATION.md) · [용량](../{H.name}/outputs/artifact_inventory.json).
''')
mark='<!-- bilateral_field_pace_v1 -->'
p=R/'conclusions/README.md';old=p.read_text();count_before=max(int(n) for n in re.findall(r'^\| (\d+) \|',old,re.M));new=old
if mark not in old:
 anchor='| [원 보고서 목록]';new=old.replace(anchor,'| [전원·게이트 안팎 전개](28D_BILATERAL_FIELD_PACE.md) | 연구28 후속·전원 각질/구간과 안팎 상대, 기수 완전 제외 비교 |\n'+anchor,1);new=new.rstrip()+f'\n\n[전원·게이트 안팎 원 보고서](../{H.name}/README.md) · [후속28D](28D_BILATERAL_FIELD_PACE.md). 독립 연구 수는 유지한다. '+mark+'\n'
mutate(p,new,old);count_after=max(int(n) for n in re.findall(r'^\| (\d+) \|',new,re.M));assert count_before==count_after
p=R/'README.md';old=p.read_text();entry=f'[출전마 전원과 게이트 안팎의 전개 예측]({H.name}/README.md): 네 각질·초반/막판·선행 후보를 전원/안쪽/바깥쪽으로 비교했다. 기수·조교사 성향과 교체 표식 모두 제외, 같은36,638출전에서 전원 확장과 안팎 구분의 효과를 분리했다. 연구28 후속28D이며 독립 연구 수와 운영 유지. [상대 전수 쌍]({H.name}/outputs/example_rival_pairs.csv) · [중앙28D](conclusions/28D_BILATERAL_FIELD_PACE.md).';mutate(p,old if mark in old else old.rstrip()+'\n\n'+entry+' '+mark+'\n',old)
p=R/'conclusions/SOURCES.md';old=p.read_text();entry=f'## 전원·게이트 안팎 후속28D\n\n[보고서](../{H.name}/README.md) · [중앙28D](28D_BILATERAL_FIELD_PACE.md) · [직접7입력과 원문 전이 출처](../{H.name}/SOURCES.md) · [독립 검증](../{H.name}/outputs/verification.json) · [게시요약](../{H.name}/PUBLICATION.md) · [용량](../{H.name}/outputs/artifact_inventory.json). 자기 제외 전원과 게이트 방향별 상대 구성을 비교하며 기수·조교사·교체 입력은 모두 제외한다. 실제 경합·작전 의도·주행경로의 공동확률과 구분한다. 기존 연구 수와 운영 유지.';mutate(p,old if mark in old else old.rstrip()+'\n\n'+entry+' '+mark+'\n',old)
p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(rec)
  else:m[key][idx]=rec
m['bilateral_field_pace_added']=True;m['bilateral_field_pace_note']='연구28 후속28D. 전원 네 각질·구간 이력과 게이트 안팎 상대 구성의 시간순 비교. 기수/조교사/교체 입력 모두 제외. 직접 의도·운영 반영 미확정, 독립 연구 수 유지.';m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();marker='<!-- '+H.name+' -->';mutate(p,old if marker in old else old.rstrip()+'\n| 2026-10-08 | 출전마 전원·게이트 안팎 | 집계 중 | '+marker+'\n',old)
result=dict(followup='28D',independent_study_count_before=count_before,independent_study_count_after=count_after,shared_files=5);(O/'registration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
