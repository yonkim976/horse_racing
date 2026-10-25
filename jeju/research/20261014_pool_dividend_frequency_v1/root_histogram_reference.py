"""Independent arithmetic on independently extracted winning dividends."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

STUDY=Path(__file__).resolve().parent
POOLS=['WIN','PLC','QNL','QPL','EXA','TLA','TRI']

def main():
 assert json.loads((STUDY/'ROOT_APPROVAL.json').read_text())['approved'] is True
 f=pd.read_csv(STUDY/'ROOT_WINNING_QUOTES.csv',dtype={'selection':str})
 bounds=[1,2,3,5,10,20,50,100,np.inf];labels=['[1,2)','[2,3)','[3,5)','[5,10)','[10,20)','[20,50)','[50,100)','[100,inf)']
 histograms=[];summary=[];races=[]
 for pool,g in f.groupby('pool',sort=True):
  for rid,one in g.groupby('race_id',sort=True):
   races.append({'pool':pool,'race_id':rid,'year':int(one.year.iloc[0]),'quotes':len(one),'min_odds':one.odds.min(),'max_odds':one.odds.max(),
    'race_low_all':bool(one.odds.max()<5),'race_mid_max':bool(5<=one.odds.max()<20),'race_high_any':bool(one.odds.max()>=20),
    'race_low_any':bool(one.odds.min()<5),'race_high_all':bool(one.odds.min()>=20),'race_mixed_low_high':bool(one.odds.min()<5 and one.odds.max()>=20),
    'race_100plus_any':bool(one.odds.max()>=100)})
 rdf=pd.DataFrame(races)
 for period in ['all','2025','2026']:
  for pool in POOLS:
   q=f[f.pool.eq(pool)&(True if period=='all' else f.year.eq(int(period)))];r=rdf[rdf.pool.eq(pool)&(True if period=='all' else rdf.year.eq(int(period)))]
   for lo,hi,label in zip(bounds,bounds[1:],labels):
    n=int((q.odds.ge(lo)&q.odds.lt(hi)).sum())
    histograms.append({'period':period,'pool':pool,'bin':label,'quotes':n,'quote_n':len(q),'percentage':100*n/len(q)})
   row={'period':period,'pool':pool,'n_races':len(r),'n_quotes':len(q),'median_quote':float(q.odds.median()),
    'quote_low':int(q.odds.lt(5).sum()),'quote_mid':int((q.odds.ge(5)&q.odds.lt(20)).sum()),'quote_high':int(q.odds.ge(20).sum()),'quote_100plus':int(q.odds.ge(100).sum())}
   for name in ['race_low_all','race_mid_max','race_high_any','race_low_any','race_high_all','race_mixed_low_high','race_100plus_any']:
    row[name]=int(r[name].sum());row[name+'_pct']=100*row[name]/len(r)
   assert row['race_low_all']+row['race_mid_max']+row['race_high_any']==len(r)
   summary.append(row)
 for name,frame in [('ROOT_HISTOGRAM_REFERENCE.csv',pd.DataFrame(histograms)),('ROOT_SUMMARY_REFERENCE.csv',pd.DataFrame(summary)),('ROOT_RACE_FREQUENCY_REFERENCE.csv',rdf)]:
  path=STUDY/name;assert not path.exists();frame.to_csv(path,index=False)
 print(pd.DataFrame(summary).query("period=='all'").to_json(orient='records'))

if __name__=='__main__':main()
