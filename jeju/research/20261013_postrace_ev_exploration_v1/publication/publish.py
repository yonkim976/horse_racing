"""Append reviewed final-price exploratory diagnostics; no strategy adoption."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STUDY = ROOT / 'jeju/research/20261013_postrace_ev_exploration_v1'
CENTRAL = ROOT / 'jeju/research/conclusions'
NAMES = ['22_DIRECT_PAIR_TOP3_MODEL.md', 'README.md', 'SOURCES.md', 'research_register.json','source_manifest.json']
KEY = 'postrace_ev_exploration_20261013'


def sha(b): return hashlib.sha256(b).hexdigest()


def encode(v): return (json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()


def main():
 review=json.loads((STUDY/'ROOT_REVIEW.json').read_text())
 assert review['status']=='PASS'
 assert review['report_sha256']==sha((STUDY/'REPORT.json').read_bytes())
 for name,digest in review['reviewed_output_sha256'].items():
  assert sha((STUDY/name).read_bytes())==digest
 reference=json.loads((STUDY/'ROOT_REFERENCE.json').read_text())
 current={r['condition']:r for r in reference['summary'] if r['selector']=='jockey_id_candidate' and r['scope']=='all'}
 before={n:(CENTRAL/n).read_bytes() for n in NAMES};after=dict(before)
 section=('\n## 2026-10-13 후속: 사후 확정배당을 이용한 선별 가능성 탐색\n\n'
  '사용자 지정에 따라 사전배당 자료 요건을 이번 가능성 탐색에서 해제하고 최종 QPL 표시배당을 '
  '이미 알고 있다는 조건으로 p×최종배당−1 점수를 계산했다. 현재 기수 ID 후보와 직전 기수 '
  '기본 후보의 말 평가·선택쌍·저장 확률은 각각 고정했다. 2025년 654경주와 2026-09-19까지 '
  '488경주, 합계 1,142경주에서 경주당 한 조합 10,000원이다. 미적중도 원문에 있는 정확 '
  '선택쌍 배당을 점수에 사용하고, 환급은 실제 적중 때만 계산했다. 사후배당을 선별에 '
  '사용한 기술통계이므로 실행 가능한 사전 수익성 검증이나 진정한 수익 상한은 아니다.\n\n'
  '| 현재 후보 선별 조건 | 경주 | 적중 | 적중률 | ROI |\n|---|---:|---:|---:|---:|\n')
 labels=[('all_purchase','전체 구매'),('p_ge_0_30','p≥30%'),('ev_ge_0.00','사후 점수≥0'),
  ('ev_ge_0.10','사후 점수≥10%'),('p_ge_0_30_ev_ge_0.00','p≥30% & 점수≥0'),
  ('p_ge_0_30_ev_ge_0.10','p≥30% & 점수≥10%'),('p_ge_0_30_ev_ge_0.20','p≥30% & 점수≥20%')]
 for key,label in labels:
  r=current[key];section+=f"| {label} | {r['n_races']} | {r['hits']} | {r['hit_rate_pct']:.2f}% | {r['net_roi_pct']:+.2f}% |\n"
 section+= ('\n점수≥0 집단의 평균 예측확률은 23.51%였지만 실제 입상률은 11.96%였다. 전체의 '
  '평균 예측확률 24.23%와 실제 입상률 24.78%가 가깝다는 사실만으로 배당 조건부 '
  '확률 정확성을 보장하지 않는다. 사후 EV 단독 선별은 전체보다 손실이 커졌고, '
  'p≥30% 혼합 집단에서만 작은 표본의 양수가 관찰됐다.\n\n'
  'p≥30% & 점수≥10%는 52경주에서 순손익 +105,000원·ROI +20.19%, 날짜 95% 구간 '
  '[−33.12%,+79.08%]였다. 점수≥20%는 39경주에서 +107,000원·+27.44%, 구간 '
  '[−43.23%,+105.53%]였다. 두 집단 모두 큰 당첨 세 경주와 그 투입을 제외하면 '
  'ROI가 각각 −13.47%, −17.78%로 바뀌었다. 연도별 양수도 표본·집중 위험을 없애지 않는다. '
  '직전 기수 기본 후보도 같은 혼합 두 조건에서 +18.51%, +24.25%로 유사한 현상이 있었다.\n\n'
  '고정 12조건과 6점수 구간을 전체/연도별로 보존하고 최적 조건을 채택하지 않았다. '
  '날짜 재표집은 기존 2,000×269 schedule 그대로이며 반복 개발자료·2024 배당 미보유·'
  '2026 부분연도라는 제한을 유지한다. 감독 독립 검산 PASS는 산술과 출처 검증이며 '
  '수익성 판정이 아니다. 복승은 정확 Top2 확률이 필요해 현재 Top3 확률로 EV를 계산하지 않았다. '
  'DB·모델·운영 기준 변경 없음. [전체 보고서](../20261013_postrace_ev_exploration_v1/README.md), '
  '[독립 검토](../20261013_postrace_ev_exploration_v1/ROOT_REVIEW.json).\n')
 after[NAMES[0]]+=section.encode()
 after['README.md']+= ('\n[사후배당을 이용한 선별 가능성 탐색](../20261013_postrace_ev_exploration_v1/README.md): '
  '현재 후보의 사후 EV≥0만 고르면 ROI −38.83%. p≥30%와 점수≥10%/20%를 함께 '
  '적용한 52/39경주는 +20.19%/+27.44%였지만 날짜 구간은 0을 포함하고 큰 당첨 '
  '세 경주 제외 시 음수였다. 최종배당을 선별에 이용한 조건부 후향 진단이며 규칙 채택·운영 변경 없음.\n').encode()
 after['SOURCES.md']+= ('\n- [20261013_postrace_ev_exploration_v1](../20261013_postrace_ev_exploration_v1/README.md): '
  '고정 현재/기수 기본 선택쌍과 최종 QPL 가격의 12조건·6구간 탐색. '
  '[조건별 집계](../20261013_postrace_ev_exploration_v1/summary.csv), '
  '[감독 독립 검산](../20261013_postrace_ev_exploration_v1/ROOT_REVIEW.json). '
  '최종배당을 미리 안다는 가정이며 사전 실행 가능성 검증이 아니다.\n').encode()
 register=json.loads(before['research_register.json']);register['updated_at']='2026-10-13'
 topic=next(t for t in register['topics'] if t['id']=='pair_top3_direct_20261011');assert KEY not in topic
 topic[KEY]={'source':'../20261013_postrace_ev_exploration_v1/README.md',
  'review':'../20261013_postrace_ev_exploration_v1/ROOT_REVIEW.json','fixed_cohort':1142,
  'decision_prices':'post-race final QPL quotes; unavailable pre-purchase',
  'current_all_scope_fixed_conditions':list(current.values()),'independent_arithmetic_review':'PASS',
  'future_profitability_verified':False,'condition_selected':False,'model_or_operational_change':False}
 after['research_register.json']=encode(register)
 manifest=json.loads(before['source_manifest.json']);old_rows={r['path']:r for r in manifest['files']};rows=dict(old_rows)
 assert len(rows)==len(manifest['files'])
 for name in NAMES[:-1]:
  path=(CENTRAL/name).relative_to(ROOT).as_posix();rows[path]={**rows[path],'sha256':sha(after[name]),'bytes':len(after[name])}
 new=[p for p in STUDY.rglob('*') if p.is_file() and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts]
 for p in new:
  path=p.relative_to(ROOT).as_posix();assert path not in rows;data=p.read_bytes()
  rows[path]={'path':path,'role':'postrace_ev_exploration','sha256':sha(data),'bytes':len(data)}
 manifest['updated_at']='2026-10-13';manifest['files']=sorted(rows.values(),key=lambda r:r['path'])
 manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in rows.values())
 manifest['verification'][KEY]={'status':'PASS','new_source_rows':len(new),'arithmetic_only':True,
  'old_source_rows_preserved_except_updated_management_files':True,'profitability_validated':False,'operational_change':False}
 after['source_manifest.json']=encode(manifest)
 backup=STUDY/'publication/before';backup.mkdir(exist_ok=False)
 for n,data in before.items():(backup/n).write_bytes(data)
 assert all((CENTRAL/n).read_bytes()==before[n] for n in NAMES),'Concurrent edit'
 for n in NAMES:
  assert (CENTRAL/n).read_bytes()==before[n],'Concurrent edit';tmp=CENTRAL/(n+'.postrace_ev.tmp');tmp.write_bytes(after[n]);tmp.replace(CENTRAL/n)
 changed={(CENTRAL/n).relative_to(ROOT).as_posix() for n in NAMES[:-1]}
 assert all(rows[path]==row for path,row in old_rows.items() if path not in changed)
 old_topics={t['id']:t for t in json.loads(before['research_register.json'])['topics']}
 new_topics={t['id']:t for t in register['topics']};assert old_topics.keys()==new_topics.keys()
 for ident,old in old_topics.items():
  got=dict(new_topics[ident])
  if ident=='pair_top3_direct_20261011':del got[KEY]
  assert got==old
 receipt={'status':'PASS','before':{n:sha(v) for n,v in before.items()},'after':{n:sha(v) for n,v in after.items()},
  'new_source_rows':len(new),'old_nonmanagement_rows_preserved':len(old_rows)-4,'topic_count':len(new_topics),'prior_topic_values_preserved':True}
 (STUDY/'publication/RECEIPT.json').write_bytes(encode(receipt));print(json.dumps(receipt))


if __name__=='__main__': main()
