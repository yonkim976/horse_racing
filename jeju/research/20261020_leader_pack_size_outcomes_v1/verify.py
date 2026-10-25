"""Runner-derived race outcomes and independent SQL exact-event distributions."""
import json,sqlite3
import numpy as np
import pandas as pd
from analysis import HERE,ROOT,OLD,sha,save
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 d=pd.read_csv(OLD/'run01/runner_groups.csv');d=d[d.point.eq('s1f')&d.group_code.eq(0)];raw=pd.read_csv(HERE/'run01/race_outcomes.csv');rates=pd.read_csv(HERE/'run01/rates.csv',dtype={'period':str,'distance':str});assert len(raw)==5200 and not raw.race_id.duplicated().any()
 rec=d.groupby('race_id').agg(entries=('api_record_id','size'),top3=('top3','sum'));rec['wins']=d.finish_position.eq(1).groupby(d.race_id).sum()
 for r in raw.itertuples():
  v=rec.loc[r.race_id];assert (r.entries,r.top3_count,r.winner_count)==(v.entries,v.top3,v.wins);assert r.winner_count<=r.top3_count<=min(3,r.entries)
 c=sqlite3.connect(':memory:');c.execute('CREATE TABLE races(id TEXT,year INTEGER,distance INTEGER,n INTEGER,k INTEGER,w INTEGER,day TEXT)');c.executemany('INSERT INTO races VALUES(?,?,?,?,?,?,?)',[(r.race_id,int(r.year),int(r.race_distance_m),int(r.entries),int(r.top3_count),int(r.winner_count),r.race_date) for r in raw.itertuples()]);checks=0
 for r in rates.itertuples():
  lo,hi=(2024,2025) if r.period=='2024_2025' else (2026,2026) if r.period=='2026' else (0,9999);where='year BETWEEN ? AND ? AND n=?';params=[lo,hi,int(r.leader_count)]
  if r.distance!='all':where+=' AND distance=?';params.append(int(r.distance))
  result=c.execute('SELECT COUNT(*),COALESCE(SUM(n),0),COALESCE(SUM(k),0),COALESCE(SUM(w),0),COALESCE(SUM(k=0),0),COALESCE(SUM(k=1),0),COALESCE(SUM(k=2),0),COALESCE(SUM(k=3),0),COUNT(DISTINCT day) FROM races WHERE '+where,params).fetchone();R,E,K,W,k0,k1,k2,k3,days=result
  assert result==(r.races,r.leader_starts,r.top3_horses,r.winner_horses,r.zero_top3_races,r.one_top3_races,r.two_top3_races,r.three_top3_races,r.days)
  assert R==k0+k1+k2+k3 and E==R*r.leader_count and K==k1+2*k2+3*k3 and W<=K and r.two_plus_top3_races==k2+k3 and r.any_top3_races==k1+k2+k3
  fields=['individual_top3_pct','individual_win_pct','group_win_pct','zero_top3_pct','one_top3_pct','two_top3_pct','three_top3_pct','two_plus_top3_pct','any_top3_pct']
  if not R:assert all(pd.isna(getattr(r,f)) for f in fields) and r.sample_status=='무표본';checks+=1;continue
  expected=[100*K/E,100*W/E,100*W/R,100*k0/R,100*k1/R,100*k2/R,100*k3/R,100*(k2+k3)/R,100*(k1+k2+k3)/R];assert np.allclose([getattr(r,f) for f in fields],expected)
  assert np.isclose(r.zero_top3_pct+r.one_top3_pct+r.two_plus_top3_pct,100) and np.isclose(r.group_win_pct,r.individual_win_pct*r.leader_count)
  assert r.sample_status==('소표본' if E<100 or R<30 or days<20 else '기준 충족')
  if r.leader_count==1:assert k2==k3==0
  if r.leader_count==2:assert k3==0
  checks+=1
 c.close();parent=pd.read_csv(OLD/'run01/rates.csv',dtype={'period':str,'distance':str});parent=parent[parent.point.eq('s1f')&parent.group_code.eq(0)];partitions=0
 for (period,dist),g in rates.groupby(['period','distance']):
  p=parent[(parent.period==period)&(parent.distance==dist)].iloc[0];assert (g.races.sum(),g.leader_starts.sum(),g.top3_horses.sum(),g.winner_horses.sum())==(p.eligible_races,p.starts,p.top3,p.wins);partitions+=1
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 save(out/'verification.json',{'status':'passed','race_outcomes_independently_from_runners':len(raw),'SQL_cells_and_exact_event_distributions':checks,'parent_partition_totals_matched':partitions,'exclusive_event_probabilities_sum_100':True,'individual_and_group_win_denominators_verified':True,'zero_sample_and_structural_zero_distinguished':True,'source_hashes_bytes_unchanged':True,'database_opened':False,'operationally_applied':False});print('Pack-size outcome verification passed',checks,flush=True)
if __name__=='__main__':main()
