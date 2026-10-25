"""Independent state-machine pack parsing, SQL counts and race accounting."""
import json,sqlite3
import numpy as np
import pandas as pd
from scipy.stats import t
from analysis import HERE,ROOT,load,sha,save
def parse(value):
 s=str(value).replace(' ','');i=0;out=[]
 def number():
  nonlocal i
  if i<len(s) and s[i]=='^':i+=1
  start=i
  while i<len(s) and s[i].isdigit():i+=1
  assert i>start
  return int(s[start:i])
 while i<len(s):
  if s[i] in ',=≡-':i+=1;continue
  if s[i]=='(':
   i+=1;g=[number()]
   while i<len(s) and s[i]==',':i+=1;g.append(number())
   assert i<len(s) and s[i]==')';i+=1;out.append(g)
  else:out.append([number()])
 assert out
 return out
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 a,points=load();d=pd.read_csv(HERE/'run01/runner_groups.csv',dtype={'horse_id':str});rr=pd.read_csv(HERE/'run01/race_groups.csv');cc=pd.read_csv(HERE/'run01/race_census.csv');rates=pd.read_csv(HERE/'run01/rates.csv',dtype={'distance':str,'period':str});cov=pd.read_csv(HERE/'run01/coverage.csv',dtype={'distance':str,'period':str});px=points.set_index(['race_id','point']);ad={k:g for k,g in a.groupby('race_id')};dc=d.set_index(['point','api_record_id']);parsed=assigned=racechecks=rawchecks=0
 assert len(cc)==10412 and not cc.duplicated(['point','race_id']).any() and not d.duplicated(['point','api_record_id']).any()
 for c in cc.itertuples():
  g=ad[c.race_id];p=px.loc[(c.race_id,c.point)];usable=p.parse_status=='usable_group_interval' and g['y_'+c.point+'_pack3'].notna().all()
  if usable:
   groups=parse(p.group_value);numbers=[v for group in groups for v in group];usable=len(numbers)==len(g) and len(set(numbers))==len(g) and set(numbers)==set(g.horse_number)
  assert c.usable==usable
  if not usable:assert not ((d.point==c.point)&(d.race_id==c.race_id)).any();continue
  mapping={v:min(k,2) for k,group in enumerate(groups) for v in group};parsed+=1
  for r in g.itertuples():
   dr=dc.loc[(c.point,r.api_record_id)];assert dr.group_code==mapping[r.horse_number] and dr.top3==r.top3 and dr.finish_position==r.finish_position;assigned+=1
  records=rr[(rr.point==c.point)&(rr.race_id==c.race_id)];assert len(records)==3 and records.entries.sum()==len(g) and records.top3_count.sum()==3 and records.winner_count.sum()==1
  for r in records.itertuples():
   z=g[g.horse_number.map(mapping).eq(r.group_code)];k=int(z.top3.sum());assert (r.entries,r.top3_count,r.winner_count,r.present,r.has_top3)==(len(z),k,int(z.finish_position.eq(1).sum()),len(z)>0,k>0)
   if len(z):assert np.isclose(r.rate_pp,100*k/len(z))
   else:assert pd.isna(r.rate_pp)
   racechecks+=1
 con=sqlite3.connect(':memory:');con.execute('CREATE TABLE obs(point TEXT,race TEXT,day TEXT,year INTEGER,dist INTEGER,horse TEXT,grp INTEGER,top3 INTEGER,win INTEGER)');con.executemany('INSERT INTO obs VALUES(?,?,?,?,?,?,?,?,?)',[(r.point,r.race_id,r.race_date,int(r.year),int(r.race_distance_m),r.horse_id,int(r.group_code),int(r.top3),int(r.finish_position==1)) for r in d.itertuples()]);con.execute('CREATE INDEX ix ON obs(point,year,dist,grp)')
 for r in rates.itertuples():
  lo,hi=(2024,2025) if r.period=='2024_2025' else (2026,2026) if r.period=='2026' else (0,9999);where='point=? AND year BETWEEN ? AND ?';params=[r.point,lo,hi]
  if r.distance!='all':where+=' AND dist=?';params.append(int(r.distance))
  # Dynamic fragments are only these static clauses; all source values are bound.
  R,N=con.execute('SELECT COUNT(DISTINCT race),COUNT(*) FROM obs WHERE '+where,params).fetchone();n,k,w,h=con.execute('SELECT COUNT(*),COALESCE(SUM(top3),0),COALESCE(SUM(win),0),COUNT(DISTINCT horse) FROM obs WHERE '+where+' AND grp=?',params+[int(r.group_code)]).fetchone()
  assert (R,N,n,k,w,h)==(r.eligible_races,r.eligible_starts,r.starts,r.top3,r.wins,r.horses)
  if not n:assert pd.isna(r.rate_pp);rawchecks+=1;continue
  g=d[(d.point==r.point)&d.year.between(lo,hi)]
  if r.distance!='all':g=g[g.race_distance_m.eq(int(r.distance))]
  z=g[g.group_code.eq(r.group_code)];per=rr[(rr.point==r.point)&rr.race_id.isin(g.race_id.unique())&rr.group_code.eq(r.group_code)];present=per[per.entries>0]
  assert np.allclose([r.rate_pp,r.top3_share_pp,r.win_rate_pp,r.race_any_top3_pp,r.equal_race_mean_rate_pp,r.mean_group_size],[100*k/n,100*k/(3*R),100*w/n,100*(present.top3_count>0).mean(),present.rate_pp.mean(),per.entries.mean()])
  for label,key in [('date','race_date'),('horse','horse_id')]:
   s=z.groupby(key).top3.agg(['sum','count']);G=len(s)
   if G<=1:continue
   scores=100*s['sum']-r.rate_pp*s['count'];half=t.ppf(.975,G-1)*np.sqrt(float(scores@scores)/n**2*G/(G-1));assert np.allclose([r.rate_pp-half,r.rate_pp+half],[getattr(r,label+'_low'),getattr(r,label+'_high')])
  rawchecks+=1
 con.close()
 for r in cov.itertuples():
  lo,hi=(2024,2025) if r.period=='2024_2025' else (2026,2026) if r.period=='2026' else (0,9999);s=cc[(cc.point==r.point)&cc.year.between(lo,hi)]
  if r.distance!='all':s=s[s.race_distance_m.eq(int(r.distance))]
  assert (len(s),int((~s.usable).sum()),int(s.field_n.sum()),int(s.usable.sum()))==(r.source_races,r.excluded_races,r.source_starts,r.eligible_races)
 for _,g in rates.groupby(['point','period','distance']):
  if g.eligible_races.iloc[0]:assert np.isclose(g.top3_share_pp.sum(),100)
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 save(out/'verification.json',{'status':'passed','race_point_census_recomputed':len(cc),'valid_pack_strings_independently_parsed':parsed,'runner_group_assignments_recomputed':assigned,'race_group_rows_recomputed':racechecks,'SQL_raw_cells_and_cluster_intervals':rawchecks,'coverage_rows_recomputed':len(cov),'all_complete_races_top3_sum_three_and_wins_one':True,'top3_composition_sums_100':True,'sources_hashes_bytes_unchanged':True,'database_opened':False,'future_prediction_tested':False})
 print('Actual pack verification passed',parsed,assigned,racechecks,rawchecks,flush=True)
if __name__=='__main__':main()
