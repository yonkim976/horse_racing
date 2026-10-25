"""Descriptive placing changes from immutable selected-start pairs."""
from pathlib import Path
import csv, hashlib, json, math
import numpy as np
import pandas as pd
from scipy.stats import t

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PAIR=ROOT/'jeju/research/20261011_stable_rider_switch_v1/input01/pairs.csv'
SOURCE=ROOT/'jeju/research/20261009_jockey_closing_switch_v1/input01/starts.csv'
CELLS=['002029:003089','002034:003089','002029:003080']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def periods(a):
 return {'all':a,'past':a[a.year<=2023],'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year==2026]}
def summary(g):
 d=g.previous_finish_position-g.finish_position
 norm=9*(g.rank_quality-g.previous_rank_quality)
 same=g.field_n.eq(g.previous_field_n)
 r={'pairs':len(g),'horses':g.horse_id.nunique(),'days':g.race_date.nunique(),'first_date':g.race_date.min(),'last_date':g.race_date.max(),'previous_mean_rank':g.previous_finish_position.mean(),'current_mean_rank':g.finish_position.mean(),'mean_rank_gain':d.mean(),'median_rank_gain':d.median(),'up':int(d.gt(0).sum()),'equal':int(d.eq(0).sum()),'down':int(d.lt(0).sum()),'up_pct':100*d.gt(0).mean(),'equal_pct':100*d.eq(0).mean(),'down_pct':100*d.lt(0).mean(),'normalized10_mean_gain':norm.mean(),'normalized_up_pct':100*norm.gt(1e-9).mean(),'previous_mean_field_n':g.previous_field_n.mean(),'current_mean_field_n':g.field_n.mean(),'field_n_min':min(g.field_n.min(),g.previous_field_n.min()),'field_n_max':max(g.field_n.max(),g.previous_field_n.max()),'same_field_pairs':int(same.sum()),'same_field_mean_gain':d[same].mean() if same.any() else None,'small_sample_under20':len(g)<20}
 for name,v in [('raw',d),('normalized10',norm)]:
  for label,key in [('date','race_date'),('horse','horse_id')]:
   scores=(v-v.mean()).groupby(g[key]).sum();G=len(scores)
   half=t.ppf(.975,G-1)*np.sqrt((scores**2).sum()/len(g)**2*G/(G-1)) if G>1 else None
   r[name+'_'+label+'_low']=v.mean()-half if half is not None else None
   r[name+'_'+label+'_high']=v.mean()+half if half is not None else None
 return r
def main():
 out=HERE/'results01';out.mkdir(exist_ok=False)
 a=pd.read_csv(PAIR,dtype={c:str for c in ['horse_id','trainer_id','jockey_id','owner_id','previous_jockey_id','previous_trainer_id','previous_owner_id']},low_memory=False)
 assert len(a)==43024 and a.changed_jockey.sum()==18231
 assert not a.horse_id.eq('3005648').any() and a.race_date.max()=='2026-09-19'
 s=pd.read_csv(SOURCE,usecols=['api_record_id','finish_position','field_n']).set_index('api_record_id')
 for prefix,key in [('', 'api_record_id'),('previous_','previous_api_record_id')]:
  for col in ['finish_position','field_n']:assert np.array_equal(a[prefix+col],a[key].map(s[col]))
 assert np.allclose(a.rank_quality,1-(a.finish_position-1)/(a.field_n-1))
 assert np.allclose(a.previous_rank_quality,1-(a.previous_finish_position-1)/(a.previous_field_n-1))
 assert np.array_equal(a.rank_improved,9*(a.rank_quality-a.previous_rank_quality)>1e-9)
 rows=[];overall=[]
 for period,z in periods(a).items():
  for changed,g in z.groupby('changed_jockey'):overall.append({'period':period,'changed':bool(changed),**summary(g)})
  for (cell,changed),g in z.groupby(['cell','changed_jockey']):
   rows.append({'period':period,'cell':cell,'trainer_id':g.trainer_id.iloc[0],'trainer_name':g.trainer_name.iloc[-1],'jockey_id':g.jockey_id.iloc[0],'jockey_name':g.jockey_display_name.iloc[-1],'changed':bool(changed),**summary(g)})
 full=pd.DataFrame(rows);ex=full[full.cell.isin(CELLS)&full.period.isin(['2024_2025','2026'])&full.changed]
 assert len(ex)==6
 full.to_csv(out/'all_cells.csv',index=False,encoding='utf-8-sig');ex.to_csv(out/'examples.csv',index=False,encoding='utf-8-sig');pd.DataFrame(overall).to_csv(out/'overall.csv',index=False,encoding='utf-8-sig')
 # Independently parse and aggregate the six presented rows with stdlib csv.
 raw=list(csv.DictReader(PAIR.open(encoding='utf-8-sig')))
 for r in ex.to_dict('records'):
  g=[v for v in raw if v['cell']==r['cell'] and v['changed_jockey']=='True' and (2024<=int(v['year'])<=2025 if r['period']=='2024_2025' else int(v['year'])==2026)]
  dif=[float(v['previous_finish_position'])-float(v['finish_position']) for v in g]
  assert len(g)==r['pairs'] and math.isclose(sum(dif)/len(dif),r['mean_rank_gain'])
  for key,fn in [('up',lambda x:x>0),('equal',lambda x:x==0),('down',lambda x:x<0)]:assert sum(fn(v) for v in dif)==r[key]
  for label,key in [('date','race_date'),('horse','horse_id')]:
   score={}
   for v,d in zip(g,dif):score[v[key]]=score.get(v[key],0)+(d-sum(dif)/len(dif))
   G=len(score);half=t.ppf(.975,G-1)*math.sqrt(sum(v*v for v in score.values())/len(g)**2*G/(G-1))
   assert math.isclose(r['raw_'+label+'_high'],sum(dif)/len(dif)+half)
 assert (full.up+full.equal+full.down).eq(full.pairs).all()
 save(HERE/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in [PAIR,SOURCE,HERE/'PLAN.md',ROOT/'jeju/research/20261011_stable_rider_switch_v1/README.md']],'input_contract':'Inherited selected complete-field pairs, official IDs, T-2 histories; descriptive outcome only, no new prediction inputs','database_opened':False})
 save(out/'verification.json',{'status':'passed','source_current_and_previous_rank_and_field_values_verified':len(a)*4,'full_cell_rows':len(full),'presented_rows_independently_summed':len(ex),'presented_raw_intervals_independently_summed':12,'existing_normalized_up_indicator_verified':len(a),'counts_partition_verified':True,'no_database_or_operational_changes':True})
 print(ex[['period','cell','pairs','previous_mean_rank','current_mean_rank','mean_rank_gain','up_pct','equal_pct','down_pct','normalized10_mean_gain','raw_date_low','raw_date_high','raw_horse_low','raw_horse_high','same_field_pairs']].to_string(index=False))
if __name__=='__main__':main()
