"""Append follow-up 28C while preserving concurrent shared-index changes."""
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
central=R/'conclusions/28C_FIELD_PACE_PREDICTION.md';title='# 편성 안의 초반 위치와 후반 움직임 예측';assert not central.exists() or central.read_text().startswith(title)
central.write_text(title+'''

2026-10-08. 연구28·28A·28B의 후속28C. S1F 통과조의 선행·선입·중단·후미를 유지했다. 선행은 첫 마군 전체이며 단독 선두나 직접 전술 의도가 아니다.

서울·부산2018년~2026-09-20/09-18 전체 명단159,014출전·14,636경주·12,516두를 보존했다. 통과조 관측155,387출전과 정상 구간기록151,074출전을 재사용하고 원문18개에서 기수·조교사·연령을 확인했다. 신마와 결측 상대도 편성에 남겼다. 과거 실제5/10슬롯·T−2·730일, 기수/조교사는 직전365일·T−2를 적용했다. 현재 경주 구간·착순·시간·rating·체중·함수율·배당을 예측 입력에 넣지 않았다.

2024·2025년 시간순 평가36,638출전·4,405두·3,465경주에서 초반 분류 정확도는 최근5전 빈도44.5%, 위치·성적·메타 이력48.7%, 자기 구간 추가49.4%, 편성 추가51.5%, 기수/조교사 추가51.6%였다. 주 비교의 Brier 차이 J−S=−0.019324[−0.021169,−0.017480]다. 편성 추가 F−S=−0.016924, 기수/조교사 추가 J−F=−0.002400으로 각각 개선했다. 기존28A와 공통인24,613출전에서는 최근5전45.8%→최종53.0%다. 현재 위치 정답을 맞히는 회고 시간순 실험이지 직접 의도나 우승확률 검증이 아니다.

상위1·2등급 대 국5·국6의 지역×정확거리×연도×이력수×연령 공통24셀·4,033출전에서 강한 과거 각질 비율32.7% 대35.9%, 차이−3.15%p[−8.92,+2.63]였다. 다음 최빈 각질 반복률44.1% 대47.3%, 차이−3.17%p[−8.14,+1.80]였다. 두 대비 BH q=0.2845다. 상위등급에서 무조건 더 뚜렷해진다는 근거는 이 공통 범위에서 확인되지 않았다.

현재 실제 구간 없이 후반 순위 회복36,531출전과 앞선 뒤 순위 후퇴36,609출전의 사전 확률도 검증했다. 최종 모형 AUC는 각각0.748·0.768이다. 예측 상위/하위20% 실제 발생률은 회복42.8%/3.9%, 후퇴36.5%/2.1%였다. 회복은 결승 전600m에서 뒤쪽 말의 상대순위0.25 이상 개선, 후퇴는 초반 선행/선입의 상대순위0.30 이상 악화다. 추입 의도나 육체적 붕괴를 직접 입증하지 않는다.

자료 마지막 날짜 마지막 경주를 고정해 두 편성21두의 확률을 보존했다. 프라임시크릿의 선행확률72.3%는 실제 첫 마군과 맞았지만, 스타마타는 후미90.1% 예상과 달리 첫 마군에 들어갔다. 각질확률을 고정 작전으로 읽지 않는다. 2026-09-22 기준12,516두의 구간·위치·회복/후퇴 프로필도 저장했으며 최근365일 출전3,204두, 유효5전 지원2,601두다. 이번 편성 미지정 말에는 위치확률을 발행하지 않았다.

직접 추진·제어·진로·작전 지시 자료와 의도 정답이 없고, 최종 출전 명단의 당시 사전 공표시각도 감사하지 않았다. 기수/조교사 빈도는 간접 단서이며 완전 능력 보정이나 원인 추정이 아니다. 독립 SQL 실제슬롯·환경모형 정상방정식·원문 식별자·미래 결과 변조·자기 제외 상대·별도 트리 해석·군집구간/BH·등급 공통셀을 검증했다. 기존 독립 연구 수·자료·DB·운영 모델·웹 배포는 유지했다.

[보고서](../20261008_field_pace_prediction/README.md) · [시간순 성능](../20261008_field_pace_prediction/outputs/early_metrics.csv) · [말별 프로필](../20261008_field_pace_prediction/outputs/latest_horse_pace_profiles.csv) · [같은 편성 사례](../20261008_field_pace_prediction/outputs/example_cards.csv) · [출처](../20261008_field_pace_prediction/SOURCES.md) · [검증](../20261008_field_pace_prediction/outputs/verification.json) · [게시요약](../20261008_field_pace_prediction/PUBLICATION.md) · [용량](../20261008_field_pace_prediction/outputs/artifact_inventory.json).
''')
mark='<!-- field_pace_prediction_v1 -->'
p=R/'conclusions/README.md';old=p.read_text();count_before=max(int(n) for n in re.findall(r'^\| (\d+) \|',old,re.M));new=old
if mark not in old:
 anchor='| [원 보고서 목록]';new=old.replace(anchor,'| [편성 안의 각질 예측](28C_FIELD_PACE_PREDICTION.md) | 연구28 후속·구간/상대/기수 이력의 시간순 평가, 직접 의도 미확정 |\n'+anchor,1);new=new.rstrip()+'\n\n[편성 안의 초반 위치와 후반 움직임 원 보고서](../20261008_field_pace_prediction/README.md) · [후속28C](28C_FIELD_PACE_PREDICTION.md). 독립 연구 수는 유지한다. '+mark+'\n'
mutate(p,new,old);count_after=max(int(n) for n in re.findall(r'^\| (\d+) \|',new,re.M));assert count_before==count_after
p=R/'README.md';old=p.read_text();entry='[편성 안의 초반 위치와 후반 움직임 예측](20261008_field_pace_prediction/README.md): 2024·2025년36,638출전 시간순 평가에서 최근5전44.5%→구간49.4%→편성·기수/조교사51.6%. 상위등급 반복성 증가는 공통셀에서 미확인, 직접 전술 의도·운영 반영은 미확정. 연구28 후속28C이며 독립 연구 수를 유지한다. [같은 편성 사례](20261008_field_pace_prediction/outputs/example_cards.csv) · [말별 프로필](20261008_field_pace_prediction/outputs/latest_horse_pace_profiles.csv) · [중앙28C](conclusions/28C_FIELD_PACE_PREDICTION.md).';mutate(p,old if mark in old else old.rstrip()+'\n\n'+entry+' '+mark+'\n',old)
p=R/'conclusions/SOURCES.md';old=p.read_text();entry='## 편성 안의 각질 예측 후속28C\n\n[원 보고서](../20261008_field_pace_prediction/README.md) · [중앙28C](28C_FIELD_PACE_PREDICTION.md) · [입력21개 해시](../20261008_field_pace_prediction/SOURCES.md) · [독립 검증](../20261008_field_pace_prediction/outputs/verification.json) · [게시요약](../20261008_field_pace_prediction/PUBLICATION.md) · [용량](../20261008_field_pace_prediction/outputs/artifact_inventory.json). 초반 위치 확보 확률과 후반 회복/후퇴, 기수·조교사 관측 성향을 직접 전술 의도와 구분한다. 기존 연구 수와 운영 유지.';mutate(p,old if mark in old else old.rstrip()+'\n\n'+entry+' '+mark+'\n',old)
p=R/'conclusions/source_manifest.json';old=p.read_text();m=json.loads(old)
for key,paths in [('sources',[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md']),('conclusions',[central,R/'conclusions/README.md',R/'conclusions/SOURCES.md'])]:
 for f in paths:
  name=str(f.relative_to(ROOT));rec=dict(path=name,sha256=sha(f));idx=next((i for i,a in enumerate(m[key]) if a['path']==name),None)
  if idx is None:m[key].append(rec)
  else:m[key][idx]=rec
m['field_pace_prediction_added']=True;m['field_pace_prediction_note']='연구28 후속28C. 과거 구간·편성·기수/조교사 이력의 시간순 초반 위치 및 후반 움직임 확률 연구. 직접 의도·실제 사전 공표시각·운영 반영 미확정. 독립 연구 수 유지.';m['data_end_by_study'][H.name]=dict(서울='2026-09-20',부산='2026-09-18');mutate(p,json.dumps(m,ensure_ascii=False,indent=2)+'\n',old)
p=R/'ARTIFACT_SIZE_LOG.md';old=p.read_text();marker='<!-- '+H.name+' -->';mutate(p,old if marker in old else old.rstrip()+'\n| 2026-10-08 | 편성 안의 각질 예측 | 집계 중 | '+marker+'\n',old)
result=dict(followup='28C',independent_study_count_before=count_before,independent_study_count_after=count_after,shared_files=5);(O/'registration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
