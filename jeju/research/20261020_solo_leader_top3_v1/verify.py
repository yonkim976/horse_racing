"""Check first-token size and membership, SQL partitions and cluster intervals."""
import json,re,sqlite3
import numpy as np
import pandas as pd
from scipy.stats import t
from analysis import HERE,ROOT,OLD,inputs,sha,save
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 a,r=inputs();leaders=pd.read_csv(HERE/'run01/leaders.csv',dtype={'horse_id':str});solo=pd.read_csv(HERE/'run01/solo_starts.csv',dtype={'horse_id':str});rates=pd.read_csv(HERE/'run01/rates.csv',dtype={'period':str,'distance':str});original=a[a.group_code.eq(0)].set_index(['point','api_record_id']);assert len(original)==len(leaders) and not leaders.duplicated(['point','api_record_id']).any()
 by={(p,k):g for (p,k),g in leaders.groupby(['point','race_id'])};checked=0
 for row in r.itertuples():
  m=re.match(r'^\s*(?:\(([^)]*)\)|(\^?\d+))',row.group_value);assert m
  numbers=[int(v) for v in re.findall(r'\d+',m.group(1) if m.group(1) is not None else m.group(2))];g=by[(row.point,row.race_id)];assert len(numbers)==row.entries==len(g) and set(numbers)==set(g.horse_number)
  assert g.leader_pack_n.eq(len(numbers)).all()
  if len(numbers)==1:assert g.size_group.eq('solo').all() and g.race_id.nunique()==len(g)
  elif len(numbers)==2:assert g.size_group.eq('pair').all()
  else:assert g.size_group.eq('three_plus').all()
  assert int(g.top3.sum())==row.top3_count and int(g.finish_position.eq(1).sum())==row.winner_count;checked+=1
 for row in leaders.itertuples():
  old=original.loc[(row.point,row.api_record_id)];assert old.horse_id==row.horse_id and old.finish_position==row.finish_position and old.top3==row.top3
 pd.testing.assert_frame_equal(solo.reset_index(drop=True),leaders[leaders.leader_pack_n.eq(1)].reset_index(drop=True),check_dtype=False)
 c=sqlite3.connect(':memory:');c.execute('CREATE TABLE leaders(point TEXT,race TEXT,year INTEGER,dist INTEGER,horse TEXT,n INTEGER,top3 INTEGER,win INTEGER)');c.executemany('INSERT INTO leaders VALUES(?,?,?,?,?,?,?,?)',[(r.point,r.race_id,int(r.year),int(r.race_distance_m),r.horse_id,int(r.leader_pack_n),int(r.top3),int(r.finish_position==1)) for r in leaders.itertuples()]);c.execute('CREATE INDEX ix ON leaders(point,year,dist,n)');cells=0
 for r in rates.itertuples():
  lo,hi=(2024,2025) if r.period=='2024_2025' else (2026,2026) if r.period=='2026' else (0,9999);where='point=? AND year BETWEEN ? AND ?';params=[r.point,lo,hi]
  if r.distance!='all':where+=' AND dist=?';params.append(int(r.distance))
  clause={'solo':'n=1','pair':'n=2','three_plus':'n>=3','shared':'n>=2'}[r.category];row=c.execute('SELECT COUNT(*),COUNT(DISTINCT race),COUNT(DISTINCT horse),COALESCE(SUM(top3),0),COALESCE(SUM(win),0) FROM leaders WHERE '+where+' AND '+clause,params).fetchone();assert row==(r.starts,r.races,r.horses,r.top3,r.wins)
  if r.category=='solo':assert r.starts==r.races
  if not r.starts:assert pd.isna(r.top3_rate_pp) and pd.isna(r.win_rate_pp);cells+=1;continue
  g=leaders[(leaders.point==r.point)&leaders.year.between(lo,hi)]
  if r.distance!='all':g=g[g.race_distance_m.eq(int(r.distance))]
  if r.category=='solo':g=g[g.leader_pack_n.eq(1)]
  elif r.category=='pair':g=g[g.leader_pack_n.eq(2)]
  elif r.category=='three_plus':g=g[g.leader_pack_n.ge(3)]
  else:g=g[g.leader_pack_n.ge(2)]
  for name,y in [('top3',g.top3.astype(float)*100),('win',g.finish_position.eq(1).astype(float)*100)]:
   point=y.mean();assert np.isclose(point,getattr(r,name+'_rate_pp'))
   for label,key in [('date','race_date'),('horse','horse_id')]:
    agg=pd.DataFrame({'value':y,'key':g[key]}).groupby('key').value.agg(['sum','count']);G=len(agg)
    if G<2:continue
    score=agg['sum']-point*agg['count'];half=t.ppf(.975,G-1)*np.sqrt(float(score@score)/len(g)**2*G/(G-1));assert np.allclose([point-half,point+half],[getattr(r,name+'_'+label+'_low'),getattr(r,name+'_'+label+'_high')])
  cells+=1
 c.close();prior=pd.read_csv(OLD/'run01/rates.csv',dtype={'period':str,'distance':str});checks=0
 for (point,period,dist),g in rates.groupby(['point','period','distance']):
  old=prior[(prior.point==point)&(prior.period==period)&(prior.distance==dist)&prior.group_code.eq(0)].iloc[0];partition=g[g.category.isin(['solo','pair','three_plus'])];assert (partition.starts.sum(),partition.top3.sum(),partition.wins.sum())==(old.starts,old.top3,old.wins);shared=g[g.category=='shared'].iloc[0];parts=g[g.category.isin(['pair','three_plus'])];assert (parts.starts.sum(),parts.top3.sum(),parts.wins.sum())==(shared.starts,shared.top3,shared.wins);checks+=1
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 save(out/'verification.json',{'status':'passed','first_pack_tokens_and_rosters_recomputed':checked,'leader_rows_matched':len(leaders),'solo_export_rows_matched':len(solo),'SQL_cells_and_cluster_intervals':cells,'partitions_match_parent_cells':checks,'sources_hashes_bytes_unchanged':True,'database_opened':False,'operationally_applied':False});print('Solo leader verification passed',checked,cells,flush=True)
if __name__=='__main__':main()
