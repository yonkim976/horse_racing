"""Publish reviewed historical calibration diagnostics without changing model policy."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
STUDY=ROOT/'jeju/research/20261013_odds_calibration_conditions_v1'
CENTRAL=ROOT/'jeju/research/conclusions'
NAMES=['22_DIRECT_PAIR_TOP3_MODEL.md','README.md','SOURCES.md','research_register.json','source_manifest.json']
KEY='odds_calibration_conditions_20261013'


def sha(b):return hashlib.sha256(b).hexdigest()


def encode(v):return (json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()


def main():
 review=json.loads((STUDY/'ROOT_REVIEW.json').read_text());assert review['status']=='PASS'
 assert review['report_sha256']==sha((STUDY/'REPORT.json').read_bytes())
 for name,digest in review['reviewed_output_sha256'].items():assert sha((STUDY/name).read_bytes())==digest
 ref=json.loads((STUDY/'ROOT_REFERENCE.json').read_text())
 current=[r for r in ref['odds_reference'] if r['selector']=='jockey_id_candidate' and r['period']=='all']
 before={n:(CENTRAL/n).read_bytes() for n in NAMES};after=dict(before)
 section=('\n## 2026-10-13 후속: 최종배당 구간별 확률 과대·과소평가 및 조건 진단\n\n'
 '현재 기수 ID 후보와 직전 기수 기본 후보의 말 평가·선택쌍·확률을 고정했다. 같은 배당 보유 '
 '2025년 654경주와 2026-09-19까지 488경주에서 최종 QPL 가격별 확률 잔차를 분석했다. '
 '2026년은 부분연도이고 같은 기간을 반복 사용한 개발 진단이다. 최종배당은 사후 조건이며 '
 '사전 실행 가능한 입력·수익성 검증으로 사용하지 않았다. 양수 차이는 과대평가, 음수는 과소평가다.\n\n'
 '| 최종 복연 표시배당 | 경주 | 평균 예측확률 | 실제 입상률 | 차이 | 날짜 95% 구간 |\n'
 '|---|---:|---:|---:|---:|---:|\n')
 for row in current:
  if row['odds_bin']=='all':continue
  section+=f"| {row['odds_bin']} | {row['n']} | {row['p_mean']*100:.2f}% | {row['hit_rate_pct']:.2f}% | {row['gap_pp']:+.2f}%p | [{row['gap_ci_low_pp']:+.2f},{row['gap_ci_high_pp']:+.2f}]%p |\n"
 section+= ('\n전체 평균 예측확률 24.23%·실제 입상률 24.78%가 가깝더라도 배당층별 오차는 크다. '
 '2배 미만 과소평가와 5~10배 과대평가 방향은 두 연도 모두 같았다. 10배 이상은 0/68이지만 '
 '경험적 bootstrap은 관측되지 않은 성공을 생성하지 못하므로 실제 확률 0이나 확정 배제 '
 '규칙을 뜻하지 않는다. 1610m 0/9에도 같은 주의가 필요하다.\n\n'
 '거리·등급·두수·최소 경력·최소 동일거리 유효기록·최대 출전 간격·두 말 점수 차이·'
 '과거 초반 위치 이력 중복의 8개 조건 가족을 조사하고 조건 내부 배당층 잔차도 보존했다. '
 '경력 3~9회 528경주(+3.16%p), 제5등급 386경주(+2.62%p), 1000m 338경주(+2.68%p)의 '
 '날짜 구간은 모두 0을 포함했다. 신마·저경력 전체의 일괄 열세는 확인되지 않았다. '
 '작은 표본과 다중 탐색을 고려해 거리·등급·경력의 고정 감점 계수를 채택하지 않았다.\n\n'
 '미적중 859경주 중 한 마리만 Top3인 경우는 648경주(75.44%), 둘 다 미입상은 211경주였다. '
 '이 집계는 선택한 짝의 불확실성 연구 단서이며 개별 미적중의 원인을 확정하지 않는다. '
 '다음 후보는 말 점수를 유지하면서 쌍 단계의 근거량·최근 기록 편차·조건부 확률 보정을 '
 '제한적으로 비교하는 방향이다. 최종배당별 관측률은 사전 예측에 그대로 대입하지 않는다.\n\n'
 '감독은 원본 특성·평가 점수·저장 예측에서 2,284개 context, 1,567개 진단 행과 552개 '
 'CI 경계를 독립 재계산했다. T−2·최신 이력일과 원천/출력 해시도 확인했다. 검산 PASS는 '
 '미래 성능·인과·수익성의 검증이 아니며 새 학습·보정·DB·운영 변경은 없다. '
 '[감독 검토와 개선 방향](../20261013_odds_calibration_conditions_v1/REVIEW_AND_NEXT_STEPS.md), '
 '[원 분석](../20261013_odds_calibration_conditions_v1/README.md), '
 '[독립 검토](../20261013_odds_calibration_conditions_v1/ROOT_REVIEW.json).\n')
 after[NAMES[0]]+=section.encode()
 after['README.md']+= ('\n[배당 구간별 확률 잔차와 오류 조건](../20261013_odds_calibration_conditions_v1/REVIEW_AND_NEXT_STEPS.md): '
 '현재 후보의 2배 미만은 −21.93%p 과소평가, 5~10배는 +7.68%p 과대평가였다. '
 '미적중 859경주 중 648경주는 한 마리만 입상했다. 주요 경력·등급·거리 과대평가 후보의 '
 '구간은 0을 포함해 고정 감점 근거는 미확정이다. 최종배당 사후 진단·독립 계산 PASS; 운영 변경 없음.\n').encode()
 after['SOURCES.md']+= ('\n- [20261013_odds_calibration_conditions_v1](../20261013_odds_calibration_conditions_v1/README.md): '
 '고정 1,142경주·2선택기의 최종배당 5구간과 사전 조건 8가족 진단. '
 '[감독 해석](../20261013_odds_calibration_conditions_v1/REVIEW_AND_NEXT_STEPS.md), '
 '[독립 재구성](../20261013_odds_calibration_conditions_v1/ROOT_REVIEW.json). '
 '고정 날짜 schedule 재사용, 말 평가·선택쌍 유지, 새 fit·보정·수집 없음.\n').encode()
 register=json.loads(before['research_register.json']);register['updated_at']='2026-10-13'
 topic=next(t for t in register['topics'] if t['id']=='pair_top3_direct_20261011');assert KEY not in topic
 topic[KEY]={'source':'../20261013_odds_calibration_conditions_v1/README.md',
 'review_and_next_steps':'../20261013_odds_calibration_conditions_v1/REVIEW_AND_NEXT_STEPS.md',
 'review':'../20261013_odds_calibration_conditions_v1/ROOT_REVIEW.json','fixed_races_per_selector':1142,
 'current_odds_diagnostics':current,'condition_families':8,'checked_table_rows':review['table_rows_verified'],
 'diagnostic_price_timing':'post-race final QPL quotes only','zero_event_bootstrap_limitation':True,
 'uniform_probability_discount_or_condition_rule_adopted':False,'new_fit_recalibration_or_operational_change':False}
 after['research_register.json']=encode(register)
 manifest=json.loads(before['source_manifest.json']);old_rows={r['path']:r for r in manifest['files']};rows=dict(old_rows)
 assert len(rows)==len(manifest['files'])
 for name in NAMES[:-1]:
  key=(CENTRAL/name).relative_to(ROOT).as_posix();rows[key]={**rows[key],'sha256':sha(after[name]),'bytes':len(after[name])}
 new=[p for p in STUDY.rglob('*') if p.is_file() and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts]
 for p in new:
  key=p.relative_to(ROOT).as_posix();assert key not in rows;data=p.read_bytes()
  rows[key]={'path':key,'role':'odds_calibration_condition_diagnostic','sha256':sha(data),'bytes':len(data)}
 manifest['updated_at']='2026-10-13';manifest['files']=sorted(rows.values(),key=lambda r:r['path'])
 manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in rows.values())
 manifest['verification'][KEY]={'status':'PASS','new_source_rows':len(new),'old_nonmanagement_rows_preserved':True,
 'arithmetic_and_source_audit_only':True,'zero_event_limit_disclosed':True,'operational_change':False}
 after['source_manifest.json']=encode(manifest)
 backup=STUDY/'publication/before';backup.mkdir(exist_ok=False)
 for name,data in before.items():(backup/name).write_bytes(data)
 assert all((CENTRAL/n).read_bytes()==before[n] for n in NAMES),'Concurrent edit'
 for n in NAMES:
  assert (CENTRAL/n).read_bytes()==before[n],'Concurrent edit'
  temp=CENTRAL/(n+'.odds_diagnostic.tmp');temp.write_bytes(after[n]);temp.replace(CENTRAL/n)
 changed={(CENTRAL/n).relative_to(ROOT).as_posix() for n in NAMES[:-1]}
 assert all(rows[path]==row for path,row in old_rows.items() if path not in changed)
 old_topics={t['id']:t for t in json.loads(before['research_register.json'])['topics']}
 new_topics={t['id']:t for t in register['topics']};assert old_topics.keys()==new_topics.keys()
 for ident,old in old_topics.items():
  got=dict(new_topics[ident])
  if ident=='pair_top3_direct_20261011':del got[KEY]
  assert old==got
 receipt={'status':'PASS','before':{n:sha(v) for n,v in before.items()},'after':{n:sha(v) for n,v in after.items()},
 'new_source_rows':len(new),'old_nonmanagement_rows_preserved':len(old_rows)-4,'topic_count':len(new_topics),'prior_topic_values_preserved':True}
 (STUDY/'publication/RECEIPT.json').write_bytes(encode(receipt));print(json.dumps(receipt))


if __name__=='__main__':main()
