"""Read-only feasibility counts, never a jockey ability ranking."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def save(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
 out=HERE/'audit01';out.mkdir(exist_ok=False)
 lineage=ROOT/'jeju/research/20261008_weight_speed_v2/source_lineage.csv';features=ROOT/'jeju/research/20261008_gate_region_pace_prediction_v2/features01/features_and_targets.csv'
 sources=[HERE/'PLAN.md',lineage,features,ROOT/'jeju/data/horse_exclusions.json',ROOT/'jeju/research/20261009_style_leader_density_v1/publication_verification.json']
 save(out/'source_manifest.json',{'database_opened':False,'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources]})
 a=pd.read_csv(lineage,dtype={'horse_id':str,'jockey_id':str});f=pd.read_csv(features,usecols=['api_record_id','horse_id','race_id','race_date','race_distance_m','h_any_n','h_any_finish_rank_mean','h_same_n','h_same_finish_rank_mean'],dtype={'horse_id':str})
 a=a.merge(f,on=['api_record_id','horse_id','race_id','race_date','race_distance_m'],how='left',validate='one_to_one');assert len(a)==52155
 assert a.jockey_id.notna().all() and a.jockey_id.str.fullmatch(r'\d+').all() and not a.jockey_id.str.fullmatch('0+').any()
 a['jockey_id']=a.jockey_id.str.zfill(6);assert not a.horse_id.eq('3005648').any()
 a[['api_record_id','race_id','horse_id','jockey_id','race_date','race_distance_m','result_payload_sha256']].to_csv(out/'identity_lineage.csv',index=False,encoding='utf-8-sig')
 counts=[];support=[]
 for label,g in [('all',a),('2024_2025',a[a.year.isin([2024,2025])]),('2026',a[a.year.eq(2026)])]+[(str(y),g) for y,g in a.groupby('year')]:
  j=g.groupby('jockey_id').agg(starts=('api_record_id','size'),horses=('horse_id','nunique'),days=('race_date','nunique'),first_date=('race_date','min'),last_date=('race_date','max')).reset_index();j['period']=label;support.append(j)
  hd=g.groupby(['horse_id','race_distance_m']).jockey_id.nunique();h=g.groupby('horse_id').jockey_id.nunique();pair=g.groupby(['horse_id','jockey_id']).size()
  counts.append({'period':label,'starts':len(g),'races':g.race_id.nunique(),'horses':g.horse_id.nunique(),'jockeys':g.jockey_id.nunique(),
   'jockeys_100plus_starts':int(j.starts.ge(100).sum()),'jockeys_300plus_starts':int(j.starts.ge(300).sum()),
   'horses_2plus_jockeys':int(h.ge(2).sum()),'horse_distance_groups_2plus_jockeys':int(hd.ge(2).sum()),
   'horse_jockey_pairs':len(pair),'horse_jockey_pairs_5plus':int(pair.ge(5).sum()),'horse_jockey_pairs_10plus':int(pair.ge(10).sum()),
   'historical_any_5plus':int(g.h_any_n.ge(5).sum()),'historical_same_5plus':int(g.h_same_n.ge(5).sum()),
   'first_date':g.race_date.min(),'last_date':g.race_date.max()})
 pd.concat(support,ignore_index=True).to_csv(out/'jockey_support.csv',index=False,encoding='utf-8-sig');pd.DataFrame(counts).to_csv(out/'period_support.csv',index=False,encoding='utf-8-sig')
 a=a.sort_values(['horse_id','race_distance_m','race_date','api_record_id']).copy()
 cols=['api_record_id','race_date','jockey_id','carried_weight_kg','moisture'];prev=a.groupby(['horse_id','race_distance_m'])[cols].shift()
 gap=(pd.to_datetime(a.race_date)-pd.to_datetime(prev.race_date)).dt.days;valid=gap.between(2,60)&a.jockey_id.notna()&prev.jockey_id.notna()
 pairs=a.loc[valid,['api_record_id','horse_id','race_id','race_date','year','race_distance_m','jockey_id','carried_weight_kg','moisture']].copy()
 for c in cols:pairs['previous_'+c]=prev.loc[valid,c]
 pairs['gap_days']=gap[valid];pairs['changed_jockey']=pairs.jockey_id.ne(pairs.previous_jockey_id);pairs['similar_measured_conditions']=(pairs.carried_weight_kg-pairs.previous_carried_weight_kg).abs().le(1)&(pairs.moisture-pairs.previous_moisture).abs().le(3)
 assert pairs.api_record_id.is_unique and (pd.to_datetime(pairs.race_date)>pd.to_datetime(pairs.previous_race_date)).all()
 pairs.to_csv(out/'same_horse_distance_pairs.csv',index=False,encoding='utf-8-sig');paircounts=[]
 for label,g in [('all',pairs),('2024_2025',pairs[pairs.year.isin([2024,2025])]),('2026',pairs[pairs.year.eq(2026)])]:
  for variant,z in [('2to60days',g),('similar_conditions',g[g.similar_measured_conditions])]:paircounts.append({'period':label,'variant':variant,'pairs':len(z),'changed':int(z.changed_jockey.sum()),'retained':int((~z.changed_jockey).sum()),'horses':z.horse_id.nunique(),'jockeys':len(set(z.jockey_id)|set(z.previous_jockey_id))})
 pd.DataFrame(paircounts).to_csv(out/'pair_support.csv',index=False,encoding='utf-8-sig')
 # Bipartite connectivity is necessary for comparison, not sufficient for causal identification.
 parent={}
 def find(k):
  parent.setdefault(k,k)
  if parent[k]!=k:parent[k]=find(parent[k])
  return parent[k]
 for h,j in a[['horse_id','jockey_id']].drop_duplicates().itertuples(index=False,name=None):
  x,y=find('h:'+h),find('j:'+j);parent[y]=x
 comp={}
 for k in list(parent):comp.setdefault(find(k),[]).append(k)
 components=sorted([{'horses':sum(k.startswith('h:') for k in v),'jockeys':sum(k.startswith('j:') for k in v)} for v in comp.values()],key=lambda v:v['horses'],reverse=True)
 save(out/'connectivity.json',{'components':components,'caution':'connected observations do not identify pure jockey ability or random assignment'})
 # Independently verify aggregates and a bounded sample of same-horse pairs.
 assert a.groupby('jockey_id').size().sum()==len(a)
 idx=a.set_index('api_record_id')
 for r in pairs.iloc[::max(1,len(pairs)//500)].itertuples():
  p=idx.loc[int(r.previous_api_record_id)];assert p.horse_id==r.horse_id and p.race_distance_m==r.race_distance_m
  assert bool(r.changed_jockey)==(r.jockey_id!=p.jockey_id)
 manifest=json.loads((out/'source_manifest.json').read_text());assert all(sha(ROOT/r['path'])==r['sha256'] for r in manifest['files'])
 save(out/'verification.json',{'status':'passed','identity_join_rows':len(a),'no_missing_jockey_ids':True,'period_sums_verified':True,'pair_sample_checked':len(pairs.iloc[::max(1,len(pairs)//500)]),'source_hashes_unchanged':True,'no_database_opened':True,'no_effect_or_rank_estimation':True})
 print(pd.DataFrame(counts).head(3).to_string(index=False));print(pd.DataFrame(paircounts).to_string(index=False));print(components[:3])
if __name__=='__main__':main()
