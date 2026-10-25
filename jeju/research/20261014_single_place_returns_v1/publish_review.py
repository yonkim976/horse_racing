"""Publish independently verified fixed single-anchor historical diagnostics."""
import hashlib
import json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
CENTRAL=ROOT/'jeju/research/conclusions'
TOPIC='23_SINGLE_PLACE_RETURNS.md'
NAMES=[TOPIC,'README.md','SOURCES.md','research_register.json','source_manifest.json']
KEY='single_place_returns_20261014'

def sha(b):return hashlib.sha256(b).hexdigest()
def encode(v):return (json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()

def main():
 review=json.loads((STUDY/'ROOT_REVIEW.json').read_text());assert review['status']=='PASS'
 for path,digest in review['reviewed_output_sha256'].items():assert sha((STUDY/path).read_bytes())==digest
 table=pd.read_csv(STUDY/'outputs/single_place_summary.csv',dtype={'group':str})
 price=table[table.cohort.eq('payout_2025_2026')];overall=price[price.dimension.eq('all')].iloc[0]
 assert overall.race_n==1142 and overall.place_hit_n==654 and overall.gross_return_krw==925100
 prose=('# 제주마: 경주당 연승 축 한 마리의 확률과 사후 수익\n\n'
 'GPT-6 Luna xhigh가 저장된 F1_STYLE6 말 평가를 유지해 집계했고 감독이 모든 선택·확률·배당·요약·신뢰구간을 독립 검산했다. '
 '**매 경주 1,000원씩 산 사후 수익률은 −18.99%였다. 확률이 높은 경주만 고른 사전 고정 임계값에서도 수익은 마이너스였다.**\n\n'
 '말 평가는 재학습·보정하지 않았다. 기존 말별 Top3 확률은 저장 점수와 연도별 기존 온도로 만든 무순서 Top3 집합 분포의 주변확률이다. '
 '각 경주의 최고 점수 한 마리를 선택하고 정확한 점수 동률은 작은 마번으로 정했다. 이 분포에서 점수 최대 말은 수학적으로 Top3 확률 최대 말과 같다. '
 '계산상 1 ULP 차이로 동률 선택이 바뀌지 않게 했으며 선택한 말의 확률은 저장값을 그대로 사용했다. 두 말 동시입상 확률을 단일 말 확률로 변환하지 않았다.\n\n'
 '전체 평가는 2024-01-05~2026-09-19의 1,779경주·269일·17,412출전이다. 이미 여러 연구에서 사용한 과거 개발 자료이며 2026년은 부분연도다. '
 '수익률은 사후 연승 배당이 있는 2025년 654경주와 2026년 488경주, 총 1,142경주에서 계산했다. 2024년 637경주는 가격이 없어 수익 계산에 넣지 않았다.\n\n'
 '연승 기준은 8두 이상이면 Top3, 7두 이하면 Top2다. 현재 모델에 Top2 확률이 없어 7두 36경주는 동일한 최고 점수 축으로 실제 Top2 적중·수익만 계산하고 '
 '연승 예측확률을 NULL로 남겼다. 확률 구간에는 전체 1,743경주, 가격 보유기간에는 1,106경주가 포함된다. '
 '[마사회 연승 안내](https://park.kra.co.kr/race_guide_.pdf), '
 '[배당 확정과 환급 절차](https://race.kra.co.kr/raceguide/RaceProcessGetService.do).\n\n'
 '## 확률 구간별 결과\n\n'
 '아래는 **같은 2025~2026년 가격 보유·확률 지원 경주**의 결과다. 평균 배당은 실제 적중한 선택마의 배당 평균이다.\n\n'
 '| 예측확률 구간 | 경주 | 평균 예측확률 | 실제 적중률 | 평균 적중배당 | 수익률 | 날짜 95% 수익률 구간 |\n'
 '|---|---:|---:|---:|---:|---:|---:|\n')
 bands=price[price.dimension.eq('probability_band')&price.race_n.gt(0)]
 for row in bands.itertuples():
  prose+=f'| {row.group} | {row.race_n} | {100*row.mean_p:.2f}% | {100*row.place_hit_rate:.2f}% | {row.mean_hit_odds:.2f}배 | {100*row.roi:+.2f}% | [{100*row.roi_ci_low:+.2f}, {100*row.roi_ci_high:+.2f}]% |\n'
 prose+= ('\n가격 보유기간에는 30% 미만·90% 이상 선택 사례가 없었다. 80~90% 구간은 23경주뿐이며, '
 '그 기간의 실제 적중률 69.57%를 전기간 58경주의 81.03%와 혼동하지 않는다. '
 '전기간 90% 이상은 2024년 단 1경주로 적중했지만 가격이 없다. 단일 관측이나 전부 실패인 작은 집단의 '
 '경험적 bootstrap 구간이 축소되는 현상은 실제 확률 또는 미래 수익이 확정됐다는 뜻이 아니다.\n\n'
 '## 확신이 높은 경주만 구매한 경우\n\n'
 '| 사전 고정 확률 기준 | 경주 | 실제 적중률 | 평균 예측확률 | 수익률 | 날짜 95% 수익률 구간 |\n'
 '|---|---:|---:|---:|---:|---:|\n')
 for row in price[price.dimension.eq('probability_threshold')&price.race_n.gt(0)].itertuples():
  prose+=f'| {row.group} | {row.race_n} | {100*row.place_hit_rate:.2f}% | {100*row.mean_p:.2f}% | {100*row.roi:+.2f}% | [{100*row.roi_ci_low:+.2f}, {100*row.roi_ci_high:+.2f}]% |\n'
 prose+= ('\n90% 이상은 가격 보유기간에 사례가 없다. 위 임계값은 성과를 보기 전에 고정했으며 최적 구매 기준으로 선택하지 않았다.\n\n'
 '## 전체 손익과 해석\n\n'
 '- 1,142경주에서 654회 적중: 실제 연승 적중률 57.27%.\n'
 '- 총 투입 1,142,000원, 총환급 925,100원, 손익 −216,900원. 수익률 −18.99%, 날짜 95% 구간 −23.57~−14.59%.\n'
 '- 평균 적중배당 1.4145배. 같은 평균 적중배당에서 손익분기 적중률은 70.70%다. 실제 57.27%와 차이가 크다.\n'
 '- 실제 적중률을 고정하면 손익분기 평균 적중배당은 1.7462배다. 두 손익분기 수치는 사후 기술통계이며 구매 전 배당 기준이 아니다.\n'
 '- 연도별 수익률은 2025년 −17.54%, 2026년 −20.94%. 7두 경주만 보면 18/36 적중, 수익률 −25.28%(구간 −48.49~+5.72%).\n\n'
 '전체 확률 지원 1,743경주의 평균 예측확률은 58.12%, 실제 적중률 57.26%이며 차이(실제−예측)는 −0.86%p, '
 '날짜 95% 구간 −3.18~+1.33%p다. 가격 보유 확률 지원 1,106경주는 평균 예측 57.88%, 실제 57.50%다. '
 '전체 확률 평균이 가까운 것과 수익이 나는 것은 별개이며, 이번 자료에서는 높은 확률에 낮은 적중배당이 함께 나타났다. '
 '70~80% 구간은 73.39%를 맞혔지만 평균 적중배당 1.2077배로 수익률 −11.37%였다.\n\n'
 '이번 결과는 높은 입상확률만으로 연승 구매를 결정할 근거를 제공하지 않는다. 현재 말 평가는 유지하며 '
 '고확률 구간 자체가 수익성을 보장한다고 해석하지 않는다. 후속 연구는 한 마리 연승 사건에 대한 시간순 확률 검증, '
 '7두 Top2 확률 지원과 실제 사전 배당 가용성을 구분해야 한다. 사전 배당이 없는 현재 자료로 실행 가능한 가격 필터 성능을 주장하지 않는다.\n\n'
 '## 원천·검증·계산 계약\n\n'
 'API301 PLC 원문에서 최신 완전 run의 506개 페이지를 확인해 1,142경주 모든 11,083두의 가격을 확보했다. '
 '원문 표시배당을 원금 포함 환급배수로 사용해 적중 시 1,000원×배당, 미적중 시 0원으로 계산한 사후 표시배당 기준 수익이다. '
 '미적중마에도 quote가 존재하지만 그 가격을 지급 환급으로 합산하지 않았다. 추가 공제 전 계산이며 원문에는 개인별 실제 지급액·공식 최초 가격 공표시각이 없다. '
 '동착·취소·불완전 편성은 고정 정상 완주 cohort에 없으므로 예외 정산 계약을 검증했다고 주장하지 않는다.\n\n'
 '감독은 저장 점수·기존 온도로 17,412개 확률을 재현하고, 공식 말 ID·마번·착순·실제 출전두수를 읽기 전용 DB와 대조했다. '
 '직접 원문 JSON 추출 가격과 계산 코드의 입력·출력을 독립 대조해 1,779개 선택, 49개 요약과 392개 CI 경계를 재계산했다. '
 '날짜 bootstrap은 기존 2,000×269 일정의 표본 날짜 ID를 날짜 빈도 가중치로 변환해 사용했다. '
 '구간/임계값의 빈 집단과 분모 0인 반복도 보존했다. DB·운영 등록부·기존 모델을 수정하지 않았고 새 학습·보정은 없다.\n\n'
 '[사전 계획](PLAN.md), [원천 감사](source_audit/SOURCE_AUDIT.md), [독립 검토](ROOT_REVIEW.json), '
 '[전체 요약 49행](outputs/single_place_summary.csv), [경주별 결과](outputs/single_place_race_results.csv), '
 '[계산 영수증](outputs/single_place_analysis_receipt.json).\n')
 readme=STUDY/'README.md';assert not readme.exists();readme.write_text(prose)
 local=[p for p in STUDY.rglob('*') if p.is_file() and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts and p.name!='ARTIFACT_MANIFEST.json']
 manifest_path=STUDY/'ARTIFACT_MANIFEST.json';assert not manifest_path.exists()
 manifest_path.write_bytes(encode({'status':'PASS','study':STUDY.name,'manifest_self_excluded':True,
  'local_artifacts':[{'path':str(p.relative_to(STUDY)),'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(local)],
  'external_source_hashes':json.loads((STUDY/'ROOT_PROBABILITY_PREFLIGHT.json').read_text())['source_hashes'],
  'final_review_sha256':sha((STUDY/'ROOT_REVIEW.json').read_bytes()),'model_fit_or_recalibration_runs':0}))
 before={n:(CENTRAL/n).read_bytes() if (CENTRAL/n).exists() else None for n in NAMES};assert before[TOPIC] is None
 after={k:v for k,v in before.items()}
 central_text=prose.replace('(PLAN.md)','(../'+STUDY.name+'/PLAN.md)').replace('(source_audit/','(../'+STUDY.name+'/source_audit/').replace('(ROOT_REVIEW.json)','(../'+STUDY.name+'/ROOT_REVIEW.json)').replace('(outputs/','(../'+STUDY.name+'/outputs/')
 after[TOPIC]=central_text.encode()
 after['README.md']+=('\n- [単一 연승 축 확률·사후 수익](23_SINGLE_PLACE_RETURNS.md): F1_STYLE6 말 평가 고정, '
  '1,142경주 654회 적중·수익률 −18.99%(날짜 95% 구간 −23.57~−14.59%). '
  '70% 이상 147경주도 −13.40%. 7두 Top2 확률 미지원36경주 별도, 독립 검산 PASS·운영 유지.\n').replace('単一','단일').encode()
 after['SOURCES.md']+=('\n- [20261014_single_place_returns_v1](../'+STUDY.name+'/README.md): '
  '고정 말 평가 경주당 연승 한 마리, 확률 구간·임계값별 적중/표시배당 수익. '
  '[원천 감사](../'+STUDY.name+'/source_audit/SOURCE_AUDIT.md), '
  '[감독 독립 검산](../'+STUDY.name+'/ROOT_REVIEW.json). 확률 평가1,743경주·수익1,142경주, 새 학습 없음.\n').encode()
 register=json.loads(before['research_register.json']);old_topics=list(register['topics']);assert all(t['id']!=KEY for t in old_topics)
 register['updated_at']='2026-10-14';register['topics'].append({'id':KEY,'title':'단일 연승 축 확률구간과 사후 배당수익',
  'conclusion':TOPIC,'latest_source':'../'+STUDY.name+'/README.md','independent_validation':'../'+STUDY.name+'/ROOT_REVIEW.json',
  'study_manifest':'../'+STUDY.name+'/ARTIFACT_MANIFEST.json','study_date':'2026-10-14','period_start':'2024-01-05','period_end':'2026-09-19','partial_2026':True,
  'evaluation_races':1779,'probability_supported_races':1743,'top2_probability_unsupported_races':36,'payout_races':1142,
  'payout_hits':654,'stake_krw':1142000,'gross_return_krw':925100,'net_krw':-216900,'ROI':float(overall.roi),
  'ROI_date_bootstrap_95pct_CI':[float(overall.roi_ci_low),float(overall.roi_ci_high)],'new_fit_or_recalibration_runs':0,
  'source_timing':'archived final post-race PLC display odds; pre-purchase availability not established',
  'independent_calculation_validation':'PASS','independent_future_validation':False,'operationally_applied':False,
  'status':'fixed_single_anchor_historical_return_negative_no_automatic_purchase_or_model_promotion'})
 after['research_register.json']=encode(register)
 central_manifest=json.loads(before['source_manifest.json']);old_rows={r['path']:r for r in central_manifest['files']};rows=dict(old_rows)
 for n in NAMES[:-1]:
  key=(CENTRAL/n).relative_to(ROOT).as_posix();rows[key]={**rows.get(key,{}),'path':key,'sha256':sha(after[n]),'bytes':len(after[n])}
 new=[p for p in STUDY.rglob('*') if p.is_file() and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts]
 for p in new:
  assert p.resolve().is_relative_to(STUDY.resolve()) and not p.is_symlink()
  key=p.relative_to(ROOT).as_posix();assert key not in rows
  rows[key]={'path':key,'role':'single_place_probability_and_return_research','sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
 central_manifest['updated_at']='2026-10-14';central_manifest['files']=sorted(rows.values(),key=lambda r:r['path'])
 central_manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in rows.values())
 central_manifest['verification'][KEY]={'status':'PASS','new_source_rows':len(new),'previous_topics_preserved':25,'operational_change':False}
 after['source_manifest.json']=encode(central_manifest)
 backup=STUDY/'publication/before';backup.mkdir(parents=True,exist_ok=False)
 for n,b in before.items():
  if b is not None:(backup/n).write_bytes(b)
 def unchanged(n):return (CENTRAL/n).read_bytes()==before[n] if before[n] is not None else not (CENTRAL/n).exists()
 assert all(unchanged(n) for n in NAMES),'Concurrent publication'
 for n in NAMES:
  assert unchanged(n),'Concurrent publication'
  tmp=CENTRAL/(n+'.single_place.tmp');assert not tmp.exists();tmp.write_bytes(after[n]);tmp.replace(CENTRAL/n)
 changed={(CENTRAL/n).relative_to(ROOT).as_posix() for n in NAMES[:-1]};assert all(rows[k]==v for k,v in old_rows.items() if k not in changed)
 assert register['topics'][:-1]==old_topics and len(register['topics'])==26
 assert all((CENTRAL/n).read_bytes()==after[n] for n in NAMES)
 receipt={'status':'PASS','before':{n:sha(b) if b is not None else None for n,b in before.items()},'after':{n:sha(b) for n,b in after.items()},
  'new_study_source_rows':len(new),'source_rows':len(rows),'topic_count':26,'all25_previous_topics_preserved':True,
  'operating_model_or_DB_modified':False,'old_nonmanagement_rows_preserved':len(old_rows)-3}
 (STUDY/'publication/RECEIPT.json').write_bytes(encode(receipt));print(json.dumps(receipt))

if __name__=='__main__':main()
