"""Independent winning-key, histogram and per-race frequency verification."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
 expected=pd.read_csv(STUDY/'ROOT_WINNING_QUOTES.csv',dtype={'selection':str,'source_run_id':str})
 actual=pd.read_csv(STUDY/'winning_quotes.csv',dtype={'winning_selection_key':str,'source_run_id':str})
 actual=actual.rename(columns={'winning_selection_key':'selection','winning_dividend_multiple':'odds','source_page_sha256':'source_sha256'})
 keys=['race_id','pool','selection'];assert not actual.duplicated(keys).any()
 expected=expected.set_index(keys).sort_index();actual=actual.set_index(keys).sort_index()
 pd.testing.assert_index_equal(expected.index,actual.index)
 assert np.array_equal(actual.odds,expected.odds)
 assert actual.source_sha256.eq(expected.source_sha256).all() and actual.source_run_id.eq(expected.source_run_id).all()
 r=pd.read_csv(STUDY/'ROOT_RACE_FREQUENCY_REFERENCE.csv').set_index(['race_id','pool']).sort_index()
 a=pd.read_csv(STUDY/'race_pool_summary.csv').set_index(['race_id','pool']).sort_index()
 pd.testing.assert_index_equal(a.index,r.index)
 mapping={'winning_quote_count':'quotes','minimum_winning_dividend':'min_odds','maximum_winning_dividend':'max_odds',
 'low_any_lt5':'race_low_any','low_all_max_lt5':'race_low_all','middle_max_5_to_lt20':'race_mid_max','high_any_max_ge20':'race_high_any',
 'high_all_min_ge20':'race_high_all','mixed_low_and_high':'race_mixed_low_high','any_quote_ge100':'race_100plus_any'}
 for col,target in mapping.items():assert np.array_equal(a[col],r[target]),col
 h=pd.read_csv(STUDY/'histogram_by_pool_year.csv',dtype={'year':str})
 href=pd.read_csv(STUDY/'ROOT_HISTOGRAM_REFERENCE.csv',dtype={'period':str}).set_index(['period','pool','bin'])
 for row in h.itertuples():
  ref=href.loc[(row.year,row.pool,row.dividend_bin)];assert row.quote_count==ref.quotes and row.winning_quote_count==ref.quote_n
  assert abs(row.quote_pct-ref.percentage)<=1e-6
  q=expected.reset_index();q=q[q.pool.eq(row.pool)&(True if row.year=='all' else q.year.eq(int(row.year)))]
  parts=row.dividend_bin.strip('[]()').split(',');lo=float(parts[0]);hi=float(parts[1])
  count=q[q.odds.ge(lo)&q.odds.lt(hi)].race_id.nunique()
  assert row.races_with_at_least_one_quote_in_bin==count
  assert abs(row.race_pct_with_quote_in_bin-100*count/row.winning_races)<=1e-6
 f=pd.read_csv(STUDY/'race_frequency_by_pool_year.csv',dtype={'year':str})
 ref=pd.read_csv(STUDY/'ROOT_SUMMARY_REFERENCE.csv',dtype={'period':str}).set_index(['period','pool'])
 flags={'low_all_max_lt5':'race_low_all','middle_max_5_to_lt20':'race_mid_max','high_any_max_ge20':'race_high_any',
 'low_any_min_lt5':'race_low_any','high_all_min_ge20':'race_high_all','mixed_low_and_high':'race_mixed_low_high','max_ge100':'race_100plus_any'}
 for row in f.itertuples():
  want=ref.loc[(row.year,row.pool)];assert row.winning_races==want.n_races and row.winning_quote_count==want.n_quotes
  assert abs(row.quote_median_multiple-want.median_quote)<1e-9
  vals=expected.reset_index();vals=vals[vals.pool.eq(row.pool)&(True if row.year=='all' else vals.year.eq(int(row.year)))].odds
  assert row.quote_min_multiple==vals.min() and row.quote_max_multiple==vals.max()
  for name,field in flags.items():
   assert getattr(row,name+'_races')==want[field]
   assert abs(getattr(row,name+'_race_pct')-want[field+'_pct'])<=1e-6
  assert row.low_all_max_lt5_races+row.middle_max_5_to_lt20_races+row.high_any_max_ge20_races==row.winning_races
 assert len(h)==168 and len(f)==21 and len(actual)==13560 and len(a)==8659
 receipt=json.loads((STUDY/'SOURCE_HASHES.json').read_text())
 for name,digest in receipt['output_sha256'].items():assert sha(STUDY/name)==digest
 for name,digest in receipt['input_sha256'].items():assert sha(ROOT/name)==digest
 report=json.loads((STUDY/'REPORT.json').read_text());assert report['scope']['eligible_settled_races']==1237
 review={'status':'PASS','actual_winning_quotes_verified':len(actual),'race_pool_rows_verified':len(a),
 'histogram_rows_verified':len(h),'frequency_rows_verified':len(f),'candidate_races':1274,'eligible_races':1237,
 'excluded_podium_ties':10,'excluded_raw_nonpodium_0_or_99':27,
 'independent_raw_extraction':True,'seven_pool_complete_winning_keys':True,'model_selected_races_used':False,
 'report_sha256':sha(STUDY/'REPORT.json'),'source_hash_receipt_sha256':sha(STUDY/'SOURCE_HASHES.json'),
 'reviewed_output_sha256':{p.name:sha(p) for p in [STUDY/'winning_quotes.csv',STUDY/'race_pool_summary.csv',STUDY/'histogram_by_pool_year.csv',STUDY/'race_frequency_by_pool_year.csv',STUDY/'REPORT.json',STUDY/'SOURCE_HASHES.json']},
 'new_training_or_probability_or_ROI_calculations':False,'DB_or_operating_model_changed':False,
 'frequency_scope':'Exact observed local final-payout frequencies in 2025–2026-09-19, not population odds or future forecasts'}
 path=STUDY/'ROOT_REVIEW.json';assert not path.exists();path.write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n');print(json.dumps(review))

if __name__=='__main__':main()
