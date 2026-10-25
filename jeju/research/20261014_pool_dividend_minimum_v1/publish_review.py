"""Publish user-requested minimum winning-price convention as latest follow-up."""
import hashlib
import json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
CENTRAL=ROOT/'jeju/research/conclusions'
KEY='pool_dividend_frequency_20261014'
FOLLOWUP='minimum_winning_dividend_20261014'
NAMES=['24_POOL_DIVIDEND_FREQUENCY.md','README.md','SOURCES.md','research_register.json','source_manifest.json']

def sha(b):return hashlib.sha256(b).hexdigest()
def encode(v):return (json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()

def main():
 review=json.loads((STUDY/'ROOT_REVIEW.json').read_text());assert review['status']=='PASS'
 for name,h in review['reviewed_output_sha256'].items():assert sha((STUDY/name).read_bytes())==h
 table=pd.read_csv(STUDY/'summary.csv',dtype={'period':str});all_rows=table[table.period.eq('all')]
 text=('# 승식별 배당 빈도: 연승·복연승 최저 당첨배당 기준\n\n'
  '2026-10-14 사용자 정정에 따라 연승과 복연승은 **경주별 실제 당첨배당 중 최솟값**으로 판단한다. '
  '나머지 다섯 승식은 경주당 당첨배당이 하나이므로 동일하다. 저배당은 5배 미만, 중간은 5배 이상 20배 미만, 고배당은 20배 이상이다.\n\n'
  '보유 2025~2026-09-19 제주 경주의 동일한 정산 가능 코호트 1,237경주(2025년707·2026년530)를 사용했다. '
  '2026년은 부분연도이며, 동착10경주와 정상 1~3위가 없는 원문0/99코드27경주는 앞선 계약에 따라 제외했다. '
  '모델 선택·예측확률·수익률을 계산하지 않은 실제 당첨배당의 빈도다.\n\n'
  '| 승식 | 5배 미만 | 5~20배 미만 | 20배 이상 |\n|---|---:|---:|---:|\n')
 for row in all_rows.itertuples():
  text+=f'| {row.pool_korean} | {row.low_min_lt5_races:,} ({row.low_min_pct:.2f}%) | {row.middle_min_5_to_lt20_races:,} ({row.middle_min_pct:.2f}%) | {row.high_min_ge20_races:,} ({row.high_min_pct:.2f}%) |\n'
 text+= ('\n연승은 전 경주에서 실제 당첨배당 중 적어도 하나가5배 미만이었다. 복연승은 최저 당첨배당이5배 미만인 경주932개, '
  '5~20배 미만294개,20배 이상11개였다. 최저 당첨배당100배 이상은 두 승식 모두0경주다. '
  '가장 낮은 배당을 대표값으로 정한 것이며 같은 경주의 나머지 당첨배당도 낮다는 뜻은 아니다.\n\n'
  '연도별 복연승 저·중·고 빈도는2025년538·163·6경주,2026년394·131·5경주다. 연승은 두 연도 모두 저배당100%다. '
  '이전 최댓값 기준에서 복연승의20배 이상284경주 중121개는 최저배당5배 미만,152개는5~20배 미만,11개는20배 이상으로 분류된다.\n\n'
  'Luna xhigh가 동결 당첨배당13,560행에서 다시 계산했고 감독이 경주×승식8,659행·전체/연도21개 요약·'
  '최댓값→최솟값 교차표189행을 독립 검산했다. '
  '[방법](README.md), [요약](summary.csv), [경주별 대표값](race_classification.csv), [독립 검토](ROOT_REVIEW.json). '
  '이전 최댓값 기준은 [원 연구](../20261014_pool_dividend_frequency_v1/README.md)에 보존한다.\n')
 note=STUDY/'REVIEW_AND_RESULTS.md';assert not note.exists();note.write_text(text)
 manifest_path=STUDY/'ARTIFACT_MANIFEST.json';assert not manifest_path.exists()
 local=[p for p in STUDY.rglob('*') if p.is_file() and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts]
 manifest_path.write_bytes(encode({'status':'PASS','manifest_self_excluded':True,'local_artifacts':[
  {'path':str(p.relative_to(STUDY)),'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(local)]}))
 before={n:(CENTRAL/n).read_bytes() for n in NAMES};after=dict(before)
 central=text
 for name in ['README.md','summary.csv','race_classification.csv','ROOT_REVIEW.json']:central=central.replace(']('+name+')','](../'+STUDY.name+'/'+name+')')
 after[NAMES[0]]=central.encode()
 after['README.md']+=('\n[연승·복연승 대표배당 기준 정정]('+NAMES[0]+'): 2026-10-14 사용자 지시에 따라 최저 실제당첨배당 사용. '
  '연승 저배당100%, 복연승 저75.34%·중23.77%·고0.89%. 기존 최댓값 연구는 원본 보존.\n').encode()
 after['SOURCES.md']+=('\n- [20261014_pool_dividend_minimum_v1](../'+STUDY.name+'/REVIEW_AND_RESULTS.md): '
  '사용자 요청에 따른 연승·복연승 경주별 최저 당첨배당 대표값 정정. 같은1,237경주, 독립 검산PASS.\n').encode()
 register=json.loads(before['research_register.json']);old_topics=json.loads(before['research_register.json'])['topics'];topic=next(t for t in register['topics'] if t['id']==KEY)
 topic['previous_maximum_based_source']=topic['latest_source'];topic['previous_maximum_based_frequency']=topic['race_low_high_frequency']
 topic['latest_source']='../'+STUDY.name+'/REVIEW_AND_RESULTS.md';topic['independent_validation']='../'+STUDY.name+'/ROOT_REVIEW.json';topic['study_manifest']='../'+STUDY.name+'/ARTIFACT_MANIFEST.json'
 topic['race_category_rule']='PLC/QPL minimum actual winning dividend per race; other five pools singleton actual winning dividend'
 topic['race_low_high_frequency']=json.loads(table.to_json(orient='records'));topic[FOLLOWUP]={'status':'user_requested_representative_definition_updated','independent_calculation_validation':'PASS','date':'2026-10-14'}
 after['research_register.json']=encode(register)
 manifest=json.loads(before['source_manifest.json']);old_rows={r['path']:r for r in manifest['files']};rows=dict(old_rows)
 for n in NAMES[:-1]:
  key=(CENTRAL/n).relative_to(ROOT).as_posix();rows[key]={**rows[key],'sha256':sha(after[n]),'bytes':len(after[n])}
 new=[p for p in STUDY.rglob('*') if p.is_file() and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts]
 for p in new:
  assert not p.is_symlink() and p.resolve().is_relative_to(STUDY.resolve());key=p.relative_to(ROOT).as_posix();assert key not in rows
  rows[key]={'path':key,'role':'minimum_winning_payout_followup','sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
 manifest['files']=sorted(rows.values(),key=lambda r:r['path']);manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in rows.values());manifest['verification'][FOLLOWUP]={'status':'PASS','new_source_rows':len(new),'prior26_other_topics_preserved':True}
 after['source_manifest.json']=encode(manifest)
 backup=STUDY/'publication/before';backup.mkdir(parents=True,exist_ok=False)
 for n,b in before.items():(backup/n).write_bytes(b)
 assert all((CENTRAL/n).read_bytes()==before[n] for n in NAMES)
 for n in NAMES:
  assert (CENTRAL/n).read_bytes()==before[n];temp=CENTRAL/(n+'.minimum.tmp');assert not temp.exists();temp.write_bytes(after[n]);temp.replace(CENTRAL/n)
 assert len(register['topics'])==len(old_topics)==27
 for old in old_topics:
  if old['id']!=KEY:assert next(t for t in register['topics'] if t['id']==old['id'])==old
 changed={(CENTRAL/n).relative_to(ROOT).as_posix() for n in NAMES[:-1]};assert all(rows[k]==v for k,v in old_rows.items() if k not in changed)
 receipt={'status':'PASS','before':{n:sha(b) for n,b in before.items()},'after':{n:sha(b) for n,b in after.items()},'topic_count':27,'prior26_other_topics_preserved':True,'new_study_source_rows':len(new),'source_rows':len(rows),'DB_or_model_changes':False}
 (STUDY/'publication/RECEIPT.json').write_bytes(encode(receipt));print(json.dumps(receipt))

if __name__=='__main__':main()
