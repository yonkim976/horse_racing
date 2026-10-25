"""Append research28B and track only this task's changes to five shared files."""
from pathlib import Path
import hashlib,json,re
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial={r['path']:r for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']}
bp=O/'shared_edits_baseline.json';op=O/'shared_own_edits.json';before={r['path']:r for r in json.loads(bp.read_text())['files']} if bp.exists() else {};own={r['path']:r for r in json.loads(op.read_text())['files']} if op.exists() else {}
def mutate(p,new,expected):
 old=p.read_text();assert old==expected,'Concurrent edit; reread latest shared content';name=str(p.relative_to(ROOT))
 if name not in before:before[name]=dict(path=name,bytes=len(old.encode()),sha256=sha(p),outside_task_delta_before_edit=len(old.encode())-initial[name]['bytes']);own[name]=dict(path=name,own_delta_bytes=0)
 if old!=new:assert p.read_text()==old;p.write_text(new);own[name]['own_delta_bytes']+=len(new.encode())-len(old.encode())
 own[name]['own_final_bytes']=before[name]['bytes']+own[name]['own_delta_bytes'];bp.write_text(json.dumps(dict(recorded_immediately_before_each_own_edit=True,files=list(before.values())),ensure_ascii=False,indent=2)+'\n');op.write_text(json.dumps(dict(task_only_deltas_captured_at_each_mutation=True,files=list(own.values())),ensure_ascii=False,indent=2)+'\n')
central=R/'conclusions/28B_HORSE_STYLE_PERFORMANCE.md';title='# 말별 평소 각질·좋은 경기력·최근 변화';assert not central.exists() or central.read_text().startswith(title)
central.write_text(title+'''

2026-10-08. 연구28·28A의 후속28B. 출발 후200m S1F 통과조의 선행·선입·중단·후미 정의를 유지했다. 선행은 첫 마군 전체이며 단독 선두나 기수 의도, 후미는 추입 적성의 확정이 아니다.

서울·부산2018~2026년 명단159,014출전·12,516두, 통과조 관측155,387출전, 조건부 기록 비교151,065출전·13,927경주를 사용했다. 최근5전 지원2,601두, 최근5전과 그전5전 비교1,349두다. 미관측을 건너뛰거나 후미로 대체하지 않았다. 기준일2026-09-22(T−2), 자료 종료 서울09-20·부산09-18이다.

실제5위 이내69,634출전과 각질을 넣지 않은 조건부 기록 잔차 상위20%27,134출전의 각질을 구분했다. 동일 경주 공통 조건, 말 기본 수준·말×정확거리·연령·부담중량·마체중·rating·과거 성적 등을 부분 풀링으로 맞췄다. 회고적 잔차이며 개인 적성이나 사전 예측 입력은 아니다.

동일 거리에서 반복 비교 가능한1,753두·2,001 말×거리의 기록 우세 잠정후보를 만들었다. 최근365일 관측553두다. 개인 편차 추가의2024/2025 조건부 설명 검증에서 지원1,995출전의 MAE 차이는−0.001116[−0.003768,+0.001536]로 작고 불확실했다. 현재 경주의 실제 각질을 사용하므로 출전 전 예측 검증이 아니다. 과거 후보의 이후 같은 거리 비교도2024년에는 오히려 낮았고2025년에는 불확실했다. 개인 최적 각질의 안정적인 재현은 미확정이다.

최근5전과 그전5전의 우세 각질이 다른302두를 변화 후보로 표시했다. BH 다중검정 통과0두이며 거리 구성도 대부분 달라 순수 전술변경의 확정이 아니다. 과거 첫 변화사건1,094건 중 이후 실제5전 지원734두에서 새 각질3/5 유지252두·34.3%였다. 새 각질 출현율39.7%·이전33.3%, 차이+6.43%p[+2.85,+10.01]다. 후속 미지원과 작은 비교 창의 한계가 남는다.

닥터시저는 최근5전과 좋은8경기 모두 선행이지만 다른 각질의 동일거리 비교가 부족했다. 태양으뜸은 선행 중심에서 중·후미로 이동하며 성적이 낮아졌고, 블랙질주는 같은1200m에서 뒤쪽으로 이동하면서 최근 성적이 좋아졌다. 위치와 성적의 동반 변화는 전술 변경의 인과효과가 아니다.

독립 SQL·초기하 순열/BH·계수 복원/정상방정식·시간순 설명값·개인 효과·군집구간·실제 후속 슬롯을 검증했다. 기존136파일을 보존했다. 개인 최적각질·강제 선행실패 원인/인과손실·운영 반영은 미확정이다. 독립 연구 수·기존 결과·DB·모델·배포는 변경하지 않았다.

[보고서](../20261008_horse_style_performance/README.md) · [최근 말 프로필](../20261008_horse_style_performance/outputs/recent_horse_profiles.csv) · [거리별 비교](../20261008_horse_style_performance/outputs/horse_distance_style.csv) · [변화 후보](../20261008_horse_style_performance/outputs/current_change_candidates.csv) · [출처](../20261008_horse_style_performance/SOURCES.md) · [검증](../20261008_horse_style_performance/outputs/verification.json) · [게시요약](../20261008_horse_style_performance/PUBLICATION.md) · [용량](../20261008_horse_style_performance/outputs/artifact_inventory.json).
''')
mark='<!-- horse_style_performance_v1 -->'
p=R/'conclusions/README.md';old=p.read_text();count_before=max(int(n) for n in re.findall(r'^\| (\d+) \|',old,re.M));new=old
if mark not in old:
 anchor='| [원 보고서 목록]';new=old.replace(anchor,'| [말별 각질과 경기력](28B_HORSE_STYLE_PERFORMANCE.md) | 연구28 후속·평소/좋은 경기/최근 변화, 개인 최적각질 미확정 |\n'+anchor,1);new=new.rstrip()+'\n\n[말별 각질과 경기력 원 보고서](../20261008_horse_style_performance/README.md) · [후속28B](28B_HORSE_STYLE_PERFORMANCE.md). 독립 연구 수는 유지한다. '+mark+'\n'
mutate(p,new,old);count_after=max(int(n) for n in re.findall(r'^\| (\d+) \|',new,re.M));assert count_before==count_after
p=R/'README.md';old=p.read_text();entry='[말별 평소 각질·좋은 경기력·최근 변화](20261008_horse_style_performance/README.md): S1F 통과조 최근5전2,601두, 동일거리 각질 비교 후보1,753두, 변화 후보302두. 이후 검증에서 개인 최적각질은 미확정이다. 연구28의 후속28B이며 독립 연구 수와 운영을 유지한다. [최근 말 표](20261008_horse_style_performance/outputs/recent_horse_profiles.csv) · [중앙28B](conclusions/28B_HORSE_STYLE_PERFORMANCE.md).';mutate(p,old if mark in old else old.rstrip()+'\n\n'+entry+' '+mark+'\n',old)
p=R/'conclusions/SOURCES.md';old=p.read_text();entry='## 말별 각질과 경기력 후속28B\n\n[원 보고서](../20261008_horse_style_performance/README.md) · [중앙28B](28B_HORSE_STYLE_PERFORMANCE.md) · [입력3개 해시](../20261008_horse_style_performance/SOURCES.md) · [독립 검증](../20261008_horse_style_performance/outputs/verification.json) · [게시요약](../20261008_horse_style_performance/PUBLICATION.md) · [용량](../20261008_horse_style_performance/outputs/artifact_inventory.json). 평소 각질·좋은 경기·최근 변화와 개인 최적각질/전술 변경 원인을 구분한다. 기존 연구 수와 원본을 유지한다.';mutate(p,old if mark in old else old.rstrip()+'\n\n'+entry+' '+mark+'\n',old)
p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(rec)
  else:m[key][idx]=rec
m['horse_style_performance_added']=True;m['horse_style_performance_note']='연구28 후속28B. 평소/좋은 경기/최근 변화의 말별 표. 조건부 기록 설명 검증이며 개인 최적각질·전술 변경 인과효과·출전 전 예측개선은 미확정. 독립 연구 수와 운영 유지.';m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();marker='<!-- '+H.name+' -->';mutate(p,old if marker in old else old.rstrip()+'\n| 2026-10-08 | 말별 각질과 경기력 | 집계 중 | '+marker+'\n',old)
dump=dict(followup='28B',independent_study_count_before=count_before,independent_study_count_after=count_after,shared_files=5);(O/'registration.json').write_text(json.dumps(dump,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dump,ensure_ascii=False))
