"""CAS publish reviewed descriptive pool frequencies while preserving prior topics."""
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
CENTRAL=ROOT/'jeju/research/conclusions'
TOPIC='24_POOL_DIVIDEND_FREQUENCY.md'
KEY='pool_dividend_frequency_20261014'
NAMES=[TOPIC,'README.md','SOURCES.md','research_register.json','source_manifest.json']

def sha(b):return hashlib.sha256(b).hexdigest()
def encode(v):return (json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()

def main():
 review=json.loads((STUDY/'ROOT_FINAL_REVIEW.json').read_text());assert review['status']=='PASS'
 for p,h in review['reviewed_output_sha256'].items():assert sha((STUDY/p).read_bytes())==h
 readme=(STUDY/'README.md').read_text()
 manifest_path=STUDY/'ARTIFACT_MANIFEST.json';assert not manifest_path.exists()
 local=[p for p in STUDY.rglob('*') if p.is_file() and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts]
 manifest_path.write_bytes(encode({'status':'PASS','manifest_self_excluded':True,'local_artifacts':[
  {'path':str(p.relative_to(STUDY)),'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(local)],
  'independent_review_sha256':sha((STUDY/'ROOT_FINAL_REVIEW.json').read_bytes()),'new_model_fit_or_probability_or_ROI':False}))
 before={n:(CENTRAL/n).read_bytes() if (CENTRAL/n).exists() else None for n in NAMES};assert before[TOPIC] is None
 after=dict(before)
 central=re.sub(r'\]\(([^)]+)\)',lambda m:']('+m[1]+')' if m[1].startswith(('http:','https:','#')) else '](../'+STUDY.name+'/'+m[1]+')',readme)
 central+='\n감독은 실제 당첨 13,560행·경주×승식 8,659행·히스토그램168행·요약21행을 독립 원문 추출과 대조했다. '
 central+='[최종 독립 검토](../'+STUDY.name+'/ROOT_FINAL_REVIEW.json)는 PASS이며 모델 선택·확률·수익 계산은 포함하지 않았다.\n'
 after[TOPIC]=central.encode()
 after['README.md']+=('\n- [승식별 실제 당첨배당 빈도]('+TOPIC+'): 2025~2026-09-19 정산가능 제주1,237경주. '
  '경주당 최고 당첨배당20배 이상 비율은 단승6.14%·연승0.24%·복승33.71%·복연승22.96%·쌍승53.52%·삼복승61.52%·삼쌍승95.07%. '
  '동착10·정상 podium 미확인27 공통제외, 당첨배당건수와 경주수 별도, 독립 검산PASS.\n').encode()
 after['SOURCES.md']+=('\n- [20261014_pool_dividend_frequency_v1](../'+STUDY.name+'/README.md): '
  '일곱 승식 실제 당첨배당13,560건, 경주별최댓값 분류와 개별배당8구간 전체/연도별 빈도. '
  '[독립 검토](../'+STUDY.name+'/ROOT_FINAL_REVIEW.json), '
  '[원천 감사](../'+STUDY.name+'/SOURCE_PREFLIGHT.json). 모델선택과 무관한 보유시장자료 기술통계.\n').encode()
 register=json.loads(before['research_register.json']);old_topics=list(register['topics']);assert len(old_topics)==26 and all(t['id']!=KEY for t in old_topics)
 register['updated_at']='2026-10-14';register['topics'].append({'id':KEY,'title':'승식별 실제 당첨배당 저·고 구간 빈도',
  'conclusion':TOPIC,'latest_source':'../'+STUDY.name+'/README.md','independent_validation':'../'+STUDY.name+'/ROOT_FINAL_REVIEW.json',
  'study_manifest':'../'+STUDY.name+'/ARTIFACT_MANIFEST.json','period_start':'2025-01-01','period_end':'2026-09-19','partial_2026':True,
  'candidate_races':1274,'eligible_races':1237,'eligible_year_counts':{'2025':707,'2026':530},'podium_tie_exclusions':10,
  'nonpodium_raw_0_or_99_exclusions':27,'actual_winning_dividends':13560,'pool_count':7,'low_lt':5,'high_ge':20,
  'race_category_rule':'maximum actual winning dividend per race and pool; low-all/middle/high-any',
  'race_low_high_frequency':json.loads((STUDY/'REPORT.json').read_text())['race_frequency_by_pool_year'],
  'model_selected_cohort':False,'probability_or_ROI_or_new_model':False,'independent_calculation_validation':'PASS','operationally_applied':False})
 after['research_register.json']=encode(register)
 manifest=json.loads(before['source_manifest.json']);old_rows={r['path']:r for r in manifest['files']};rows=dict(old_rows)
 for n in NAMES[:-1]:
  key=(CENTRAL/n).relative_to(ROOT).as_posix();rows[key]={**rows.get(key,{}),'path':key,'sha256':sha(after[n]),'bytes':len(after[n])}
 new=[p for p in STUDY.rglob('*') if p.is_file() and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts]
 for p in new:
  assert not p.is_symlink() and p.resolve().is_relative_to(STUDY.resolve())
  key=p.relative_to(ROOT).as_posix();assert key not in rows
  rows[key]={'path':key,'role':'pool_dividend_frequency_audit','sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
 manifest['updated_at']='2026-10-14';manifest['files']=sorted(rows.values(),key=lambda r:r['path']);manifest['managed_files_bytes_excluding_this_manifest']=sum(r['bytes'] for r in rows.values())
 manifest['verification'][KEY]={'status':'PASS','new_source_rows':len(new),'previous26_topics_preserved':True,'operational_change':False}
 after['source_manifest.json']=encode(manifest)
 backup=STUDY/'publication/before';backup.mkdir(parents=True,exist_ok=False)
 for n,b in before.items():
  if b is not None:(backup/n).write_bytes(b)
 def unchanged(n):return (CENTRAL/n).read_bytes()==before[n] if before[n] is not None else not (CENTRAL/n).exists()
 assert all(unchanged(n) for n in NAMES)
 for n in NAMES:
  assert unchanged(n),'Concurrent publication'
  tmp=CENTRAL/(n+'.pool_frequency.tmp');assert not tmp.exists();tmp.write_bytes(after[n]);tmp.replace(CENTRAL/n)
 changed={(CENTRAL/n).relative_to(ROOT).as_posix() for n in NAMES[:-1]}
 assert all(rows[k]==v for k,v in old_rows.items() if k not in changed)
 assert register['topics'][:-1]==old_topics and len(register['topics'])==27
 assert all((CENTRAL/n).read_bytes()==after[n] for n in NAMES)
 receipt={'status':'PASS','before':{n:sha(b) if b is not None else None for n,b in before.items()},'after':{n:sha(b) for n,b in after.items()},
  'new_study_source_rows':len(new),'source_rows':len(rows),'topic_count':27,'all26_prior_topics_preserved':True,
  'old_nonmanagement_rows_preserved':len(old_rows)-3,'DB_or_operating_model_changed':False}
 (STUDY/'publication/RECEIPT.json').write_bytes(encode(receipt));print(json.dumps(receipt))

if __name__=='__main__':main()
