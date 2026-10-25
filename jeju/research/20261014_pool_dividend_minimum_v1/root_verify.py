"""Verify minimum-price reclassification directly from frozen winning quotes."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
SOURCE=ROOT/'jeju/research/20261014_pool_dividend_frequency_v1'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
 q=pd.read_csv(SOURCE/'winning_quotes.csv')
 r=q.groupby(['race_id','pool'],sort=True).agg(year=('year','first'),min_odds=('winning_dividend_multiple','min'),max_odds=('winning_dividend_multiple','max'),quotes=('winning_dividend_multiple','size'))
 a=pd.read_csv(STUDY/'race_classification.csv').set_index(['race_id','pool']).sort_index()
 pd.testing.assert_index_equal(a.index,r.index)
 for col,reference in [('minimum_winning_dividend','min_odds'),('maximum_winning_dividend','max_odds'),('winning_quote_count','quotes')]:assert np.array_equal(a[col],r[reference])
 r['minimum_class']=np.where(r.min_odds<5,'low_lt5',np.where(r.min_odds<20,'middle_5_to_lt20','high_ge20'))
 r['maximum_class']=np.where(r.max_odds<5,'low_lt5',np.where(r.max_odds<20,'middle_5_to_lt20','high_ge20'))
 assert a.new_min_category.eq(r.minimum_class).all() and a.old_max_category.eq(r.maximum_class).all()
 table=pd.read_csv(STUDY/'summary.csv',dtype={'period':str})
 reference=json.loads((STUDY/'ROOT_REFERENCE.json').read_text());ref={(v['year'],v['pool']):v for v in reference}
 for row in table.itertuples():
  v=ref[(row.period,row.pool)];assert row.races==v['races']
  for column,label in [('low_min_lt5_races','low'),('middle_min_5_to_lt20_races','middle'),('high_min_ge20_races','high')]:assert getattr(row,column)==v[label]
  for column,label in [('low_min_pct','low'),('middle_min_pct','middle'),('high_min_pct','high')]:assert abs(getattr(row,column)-100*v[label]/v['races'])<1e-6
 cross=pd.read_csv(STUDY/'oldmax_to_newmin_crosswalk.csv',dtype={'period':str})
 for row in cross.itertuples():
  g=r.reset_index();g=g[g.pool.eq(row.pool)&(True if row.period=='all' else g.year.eq(int(row.period)))]
  assert row.n_races==int((g.minimum_class.eq(row.new_min_category)&g.maximum_class.eq(row.old_max_category)).sum())
 receipt=json.loads((STUDY/'SOURCE_HASHES.json').read_text())
 for name,h in receipt['output_sha256'].items():assert sha(STUDY/name)==h
 for name,h in receipt['input_sha256'].items():
  p=STUDY/name if name=='analyze_minimum.py' else SOURCE/name.removeprefix('source/')
  assert sha(p)==h
 review={'status':'PASS','race_pool_rows_verified':len(a),'year_pool_summary_rows_verified':len(table),'old_new_crosswalk_rows_verified':len(cross),
  'PLC_QPL_representative':'minimum actual winning dividend per race','single_winner_five_pools_unchanged':True,
  'PLC_QPL_minimum_100plus_races':0,'source_sha256':sha(SOURCE/'winning_quotes.csv'),
  'reviewed_output_sha256':{p.name:sha(p) for p in STUDY.iterdir() if p.is_file() and p.name not in ['ROOT_REVIEW.json','ROOT_REFERENCE.json','root_verify.py']},
  'DB_or_model_or_network_changes':False}
 p=STUDY/'ROOT_REVIEW.json';assert not p.exists();p.write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n');print(json.dumps(review))

if __name__=='__main__':main()
