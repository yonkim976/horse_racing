"""Independent final-price exploration accounting, with no worker imports."""
import hashlib
import json
import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
INPUTS = {
 'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet': '0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6',
 'jeju/research/20261013_pair_qpl_roi_v1/race_returns.csv': '8e1b1a2485d6c625445315bd856d7988fa9da54e3de0bd10b2dac02086179afa',
 'jeju/research/20261013_prepurchase_ev_audit_v1/SOURCE_PAGE_INDEX.json': '1dac9ab751fe0be8ad4da2e139f862500ea68f3a23ab290def9b42f3dfda6fb0',
 'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy': 'd141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd',
}


def sha(b):
 return hashlib.sha256(b).hexdigest()


def equivalent(got, want):
 if want is None or pd.isna(want):
  assert pd.isna(got), (got, want)
 else:
  assert math.isclose(float(got), float(want), rel_tol=0, abs_tol=1e-8), (got, want)


def make_references():
 for path, digest in INPUTS.items():
  assert sha((ROOT/path).read_bytes()) == digest
 full = pd.read_parquet(ROOT/list(INPUTS)[0])
 returns = pd.read_csv(ROOT/list(INPUTS)[1])
 methods = {'jockey_id_candidate': ('selected_jockey_id_candidate', 'jockey_id_candidate_calibrated_probability'),
            'jockey_basic_candidate': ('selected_jockey_basic_candidate', 'candidate_calibrated_probability')}
 frames = {}
 for name, (flag, probability) in methods.items():
  selected = full.loc[full[flag].eq(1) & full.evaluation_year.isin([2025, 2026])].set_index('race_id')
  rows = returns.loc[returns.selector.eq(name)].set_index('race_id').reindex(selected.index).copy()
  assert len(rows) == len(selected) == 1142 and rows.index.is_unique
  assert rows.selected_pair.eq(selected.horse_i.astype(int).astype(str)+'-'+selected.horse_j.astype(int).astype(str)).all()
  assert rows.hit.eq(selected.y_pair).all()
  rows['p'] = selected[probability]
  rows['score'] = rows.p*rows.qpl_quote_odds-1
  assert rows.qpl_quote_odds.notna().all() and rows.qpl_quote_odds.gt(0).all() and not rows.qpl_quote_odds.eq(9999.9).any()
  assert np.allclose(rows.return_krw, rows.hit*rows.qpl_quote_odds*10000, rtol=0, atol=1e-8)
  frames[name] = rows
 # Reconstruct final quotes from prior complete registry inventory independently.
 wanted = {(rid, r.selected_pair) for frame in frames.values() for rid, r in frame.iterrows()}
 latest = {}; cache = {}; raw_quotes = {}
 index = json.loads((ROOT/list(INPUTS)[2]).read_text())
 assert len(index) == 889
 for page in index:
  path = (ROOT/page['path_relative']).resolve()
  assert path.is_relative_to(ROOT.resolve())
  if path not in cache:
   data = path.read_bytes(); cache[path] = (sha(data), json.loads(data))
  digest, payload = cache[path]
  assert digest == page['expected_sha256'] == page['actual_sha256']
  container = payload['response'].get('body', {}).get('items') or {}
  items = container.get('item', []) if isinstance(container, dict) else []
  if isinstance(items, dict): items = [items]
  for item in items:
   if item.get('pool') != 'QPL' or item.get('meet') != '제주': continue
   day = str(item['rcDate']); rid = f"{day[:4]}-{day[4:6]}-{day[6:]}_2_{int(item['rcNo'])}"
   pair = '-'.join(map(str, sorted([int(item['chulNo']), int(item['chulNo2'])])))
   key = (rid, pair)
   order = (page['retrieved_at_ms'], page['document_id'])
   if key in wanted and (key not in latest or order > latest[key][0]):
    latest[key] = (order, float(item['odds']))
   if key in wanted:
    raw_quotes[(rid,pair,digest)] = float(item['odds'])
 assert set(latest) == wanted and len(wanted) == 1179
 for frame in frames.values():
  for rid, row in frame.iterrows(): equivalent(latest[(rid,row.selected_pair)][1],row.qpl_quote_odds)
 dates = sorted(full.race_date.unique())
 schedule = np.load(ROOT/list(INPUTS)[3],allow_pickle=False)
 assert len(dates) == 269 and schedule.shape == (2000,269) and schedule.dtype == np.int32
 weights = np.stack([np.bincount(row,minlength=269) for row in schedule])
 stats = []
 for name, frame in frames.items():
  conditions = {'all_purchase': frame.p.ge(0), 'p_ge_0_30': frame.p.ge(.3), 'p_ge_0_40': frame.p.ge(.4)}
  conditions.update({f'ev_ge_{x:.2f}':frame.score.ge(x) for x in [0,.05,.1,.2,.5,1]})
  conditions.update({f'p_ge_0_30_ev_ge_{x:.2f}':frame.p.ge(.3)&frame.score.ge(x) for x in [0,.1,.2]})
  for condition, mask in conditions.items():
   for scope in ['all','2025','2026']:
    active = mask & (True if scope == 'all' else frame.year.eq(int(scope)))
    q = frame.loc[active]; n = len(q); pay = int(q.return_krw.sum()); hit = int(q.hit.sum())
    ids = pd.Categorical(q.race_date,categories=dates).codes
    dn = np.bincount(ids,minlength=269); dh = np.bincount(ids,weights=q.hit,minlength=269)
    dr = np.bincount(ids,weights=q.return_krw,minlength=269)
    bn,bh,br = weights@dn,weights@dh,weights@dr; valid=bn>0
    row = {'selector':name,'condition':condition,'scope':scope,'n_races':n,'hits':hit,
     'hit_rate_pct':100*hit/n if n else None,'mean_p':q.p.mean() if n else None,
     'mean_quote':q.qpl_quote_odds.mean() if n else None,'median_quote':q.qpl_quote_odds.median() if n else None,
     'mean_score':q.score.mean() if n else None,
     'mean_paid_odds_on_hit':q.loc[q.hit.eq(1),'qpl_quote_odds'].mean() if hit else None,
     'stake_krw':n*10000,'return_krw':pay,'net_krw':pay-n*10000,
     'net_roi_pct':100*(pay/(n*10000)-1) if n else None,
     'ci_hit_rate_pct':np.quantile(bh[valid]/bn[valid]*100,[.025,.975]).tolist() if valid.any() else None,
     'ci_net_roi_pct':np.quantile((br[valid]/(bn[valid]*10000)-1)*100,[.025,.975]).tolist() if valid.any() else None,
     'empty_draws_dropped':int((~valid).sum())}
    order = q.sort_values(['return_krw','race_id'] if 'race_id' in q.columns else ['return_krw'],ascending=False)
    # Select largest winning returns; tie ordering cannot affect aggregate sensitivity.
    winning = q.loc[q.hit.eq(1)].sort_values('return_krw',ascending=False)
    for k in [1,3,5]:
     cut = winning.head(k); remain=n-len(cut); remain_pay=pay-int(cut.return_krw.sum())
     row[f'drop_top{k}_roi_pct'] = 100*(remain_pay/(remain*10000)-1) if remain else None
    stats.append(row)
 c=sqlite3.connect((ROOT/'data/horse_racing.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
 c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
 official={}
 for day,number,horse in c.execute('''SELECT r.race_date_local,r.race_number,e.horse_number
   FROM races r JOIN racecourses t ON t.id=r.racecourse_id JOIN race_entries e ON e.race_id=r.id
   JOIN race_results z ON z.race_entry_id=e.id
   WHERE t.kra_meet_code=? AND r.race_date_local BETWEEN ? AND ? AND z.finish_position BETWEEN ? AND ?''',
   (2,'2025-01-01','2026-09-19',1,3)):
  official.setdefault(f'{day}_2_{number}',set()).add(horse)
 for frame in frames.values():
  for rid,row in frame.iterrows():
   assert len(official[rid])==3
   assert row.hit==int(set(map(int,row.selected_pair.split('-'))).issubset(official[rid]))
 c.close()
 return frames, stats, raw_quotes


def check_outputs(frames, stats, raw_quotes):
 def read_period_csv(name):
  table=pd.read_csv(STUDY/name,dtype={'period':str})
  table['period']=table.period.replace({'2026_partial':'2026'})
  return table
 mapping={'all_purchase':'all_purchase','p_ge_0_30':'p_ge_030','p_ge_0_40':'p_ge_040',
  'ev_ge_0.00':'score_ge_0','ev_ge_0.05':'score_ge_005','ev_ge_0.10':'score_ge_010',
  'ev_ge_0.20':'score_ge_020','ev_ge_0.50':'score_ge_050','ev_ge_1.00':'score_ge_100',
  'p_ge_0_30_ev_ge_0.00':'p030_score_ge_0','p_ge_0_30_ev_ge_0.10':'p030_score_ge_010',
  'p_ge_0_30_ev_ge_0.20':'p030_score_ge_020'}
 summary=read_period_csv('summary.csv').set_index(['selector','condition_id','period'])
 ci=read_period_csv('bootstrap_ci.csv').set_index(['selector','condition_id','period'])
 assert len(summary)==len(ci)==72 and summary.index.is_unique and ci.index.is_unique
 names={'n':'n_races','hits':'hits','hit_rate_pct':'hit_rate_pct','p_mean':'mean_p','quote_mean':'mean_quote',
  'quote_median':'median_quote','posthoc_score_mean':'mean_score','mean_hit_final_quote':'mean_paid_odds_on_hit',
  'stake_krw':'stake_krw','payout_krw':'return_krw','net_krw':'net_krw','roi_pct':'net_roi_pct'}
 for ref in stats:
  key=(ref['selector'],mapping[ref['condition']],ref['scope']);s=summary.loc[key];b=ci.loc[key]
  for col,target in names.items(): equivalent(s[col],ref[target])
  for k in [1,3,5]: equivalent(s[f'roi_without_top{k}_hit_pct'],ref[f'drop_top{k}_roi_pct'])
  equivalent(s.coverage_pct,ref['n_races']/(1142 if ref['scope']=='all' else 654 if ref['scope']=='2025' else 488)*100)
  equivalent(s.coverage_of_fixed_1142_pct,ref['n_races']/1142*100)
  for prefix,target in [('roi','ci_net_roi_pct'),('hit_rate','ci_hit_rate_pct')]:
   for suffix,index in [('low',0),('high',1)]: equivalent(b[f'{prefix}_ci_{suffix}_pct'],ref[target][index])
  assert b.undefined_draws_excluded==ref['empty_draws_dropped']
  assert b.valid_draws+b.undefined_draws_excluded==b.draw_count==2000
 rows=pd.read_csv(STUDY/'race_rows.csv').set_index(['selector','race_id'])
 assert len(rows)==2284 and rows.index.is_unique
 for selector,frame in frames.items():
  got=rows.loc[selector].reindex(frame.index)
  assert got.pair.equals(frame.selected_pair.rename('pair'))
  assert got.price_valid.eq(1).all()
  for col,target in [('p','p'),('final_quote','qpl_quote_odds'),('ev_proxy','score'),('hit','hit'),
                     ('stake_krw','stake_krw'),('return_krw','return_krw'),('net_krw','net_krw')]:
   assert np.allclose(got[col],frame[target],rtol=0,atol=1e-12)
  for rid,r in got.iterrows(): equivalent(raw_quotes[(rid,r.pair,r.source_hash)],r.final_quote)
 bins=read_period_csv('bin_summary.csv')
 assert len(bins)==42
 bounds={'below_-1':(-np.inf,-1),'[-1,0)':(-1,0),'[0,0.10)':(0,.1),'[0.10,0.25)':(.1,.25),
  '[0.25,0.50)':(.25,.5),'[0.50,1.00)':(.5,1),'[1.00,inf)':(1,np.inf)}
 for row in bins.itertuples():
  frame=frames[row.selector];lo,hi=bounds[row.score_bin]
  part=frame.loc[frame.score.ge(lo)&frame.score.lt(hi)&(True if row.period=='all' else frame.year.eq(int(row.period)))]
  n=len(part);pay=int(part.return_krw.sum());hits=int(part.hit.sum())
  for col,val in [('n',n),('hits',hits),('stake_krw',n*10000),('payout_krw',pay),('net_krw',pay-n*10000),
    ('roi_pct',(pay/(n*10000)-1)*100 if n else None),('hit_rate_pct',hits/n*100 if n else None),
    ('p_mean',part.p.mean() if n else None),('posthoc_score_mean',part.score.mean() if n else None)]:
   equivalent(getattr(row,col),val)
 top=read_period_csv('top5.csv')
 for key,g in top.groupby(['selector','condition_id','period']):
  selector,condition,period=key;frame=frames[selector]
  ref=next(r for r in stats if r['selector']==selector and mapping[r['condition']]==condition and r['scope']==period)
  reverse={v:k for k,v in mapping.items()};rule=reverse[condition]
  if rule=='all_purchase':mask=frame.p.ge(0)
  elif rule.startswith('p_ge_0_30_ev_ge_'):mask=frame.p.ge(.3)&frame.score.ge(float(rule.rsplit('_',1)[1]))
  elif rule.startswith('ev_ge_'):mask=frame.score.ge(float(rule[len('ev_ge_'):]))
  else:mask=frame.p.ge(.3 if rule=='p_ge_0_30' else .4)
  if period!='all':mask &= frame.year.eq(int(period))
  expected=frame.loc[mask & frame.hit.eq(1)].reset_index().sort_values(['return_krw','race_id'],ascending=[False,True]).head(5)
  assert g.sort_values('rank_by_realized_payout').race_id.tolist()==expected.race_id.tolist()
  assert g.return_krw.sum()==expected.return_krw.sum()
 source_hashes=json.loads((STUDY/'SOURCE_HASHES.json').read_text())
 for name,digest in source_hashes['outputs_sha256'].items(): assert sha((STUDY/name).read_bytes())==digest
 review={'status':'PASS','scope':'Post-race final-price conditional exploration only; arithmetic and source review',
  'selector_race_rows_verified':2284,'unique_selected_pairs_verified':1179,'raw_source_pages_independently_verified':889,
  'fixed_condition_period_summaries_verified':72,'score_bin_period_summaries_verified':42,
  'date_bootstrap_rows_verified':72,'date_bootstrap_ci_limits_verified':288,'top5_rows_verified':len(top),
  'actual_prepurchase_strategy_validated':False,'profitability_confirmed':False,'models_or_database_changed':False,
  'report_sha256':sha((STUDY/'REPORT.json').read_bytes()),
  'reviewed_output_sha256':{p.name:sha(p.read_bytes()) for p in STUDY.iterdir() if p.is_file() and p.name!='ROOT_REVIEW.json'}}
 (STUDY/'ROOT_REVIEW.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in review.items() if k!='reviewed_output_sha256'}))


if __name__ == '__main__':
 frames, stats, raw_quotes = make_references()
 reference = {'input_sha256':INPUTS,'source_pages_verified':889,'unique_pairs_verified':1179,'summary':stats}
 (STUDY/'ROOT_REFERENCE.json').write_text(json.dumps(reference,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
 check_outputs(frames,stats,raw_quotes)
