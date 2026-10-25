"""Preserved selected starts, past-only closing measures and rider changes."""
from pathlib import Path
import hashlib,json,sqlite3
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OLD=ROOT/'jeju/research/20261009_jockey_effects_v1'
FE_NUM=['carried_weight_kg','body_kg','gate_scaled','h_any_n','h_same_n','h_any_gap_days','h_same_gap_days',
 'h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean',
 'h_any_s1ftime_mean','h_any_g3ftime_mean','h_any_g1ftime_mean','h_any_s1f_first_mean','h_any_s1f_front_mean','h_any_s1f_middle_mean','h_any_s1f_rear_mean']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def save(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False)
 style=ROOT/'jeju/research/20261009_style_leader_density_v1/features01/start_features.csv'
 trace=ROOT/'jeju/research/20261008_gate_region_pace_prediction_v2/features01/history_lineage.csv'
 sources=[HERE/'PLAN.md',OLD/'input01/starts.csv',OLD/'forecast01/predictions.csv',OLD/'effects01/jockey_effects.csv',style,trace,ROOT/'jeju/data/horse_exclusions.json']
 manifest={'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources]}
 a=pd.read_csv(sources[1],dtype={'horse_id':str,'jockey_id':str,'trainer_id':str},low_memory=False)
 s=pd.read_csv(style,usecols=['api_record_id','h_any_late_n','h_any_late_mean','style_any','style_any40'])
 a=a.merge(s,on='api_record_id',validate='one_to_one')
 a['back_prop']=a.h_any_s1f_middle_mean+a.h_any_s1f_rear_mean
 a['back']=a.h_any_s1f_n.ge(5)&a.h_any_s1f_n.ge(.6*a.h_any_n)&a.back_prop.ge(.6-1e-12)
 tr=pd.read_csv(trace,keep_default_na=False).set_index('api_record_id').loc[a.api_record_id]
 gm=a.set_index('api_record_id').g3f_rank;dm=a.set_index('api_record_id').race_date
 hist=[]; edges=0
 for row,ids in zip(a.itertuples(),tr.any_ids):
  ix=[int(v) for v in ids.split('|')] if ids else []
  if ix:assert dm.loc[ix].le(row.history_cutoff).all()
  v=gm.loc[ix];hist.append((int(v.notna().sum()),float(v.mean()) if v.notna().any() else np.nan));edges+=len(ix)
 a['h_g3f_rank_n']=[v[0] for v in hist];a['h_g3f_rank_mean']=[v[1] for v in hist]
 db=ROOT/'jeju/data/jeju_native_core.sqlite3';manifest['database_sha256_before']=sha(db)
 con=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON')
 owners=pd.read_sql_query('SELECT r.api_record_id,r.horse_id,r.jockey_id,r.trainer_id,r.owner_id,r.owner_name,a.payload_sha256 AS owner_source_sha FROM race_result_rows r JOIN api_records a ON a.api_record_id=r.api_record_id',con);con.close()
 for c in ['horse_id','jockey_id','trainer_id']:owners[c]=owners[c].astype('string')
 for c in ['jockey_id','trainer_id']:owners[c]=owners[c].str.zfill(6)
 a=a.merge(owners,on=['api_record_id','horse_id','jockey_id','trainer_id'],how='left',validate='one_to_one')
 assert len(a)==52155 and a.owner_source_sha.eq(a.result_payload_sha256).all()
 missing=int(a.owner_id.isna().sum());a.owner_id=a.owner_id.fillna('unknown').astype(str)
 a=a.sort_values(['horse_id','race_date','api_record_id']);previous=a.groupby('horse_id').shift(1)
 for c in ['api_record_id','race_date','jockey_id','trainer_id','owner_id','race_distance_m','class_clean','top3','relative_time','body_kg','carried_weight_kg','moisture','gate_scaled','h_any_relative_time_mean','h_any_finish_rank_mean']:
  a['previous_'+c]=previous[c]
 a['gap_days']=(pd.to_datetime(a.race_date)-pd.to_datetime(a.previous_race_date)).dt.days
 stats=[]
 for ds in sorted(a.race_date.unique()):
  cutoff=pd.Timestamp(ds)-pd.Timedelta(days=2);lo=(cutoff-pd.Timedelta(days=364)).strftime('%Y-%m-%d');hi=cutoff.strftime('%Y-%m-%d')
  g=a[a.race_date.between(lo,hi)].groupby('jockey_id').agg(n=('api_record_id','size'),top3_count=('top3','sum'),last_date=('race_date','max'))
  g['rate']=g.top3_count/g.n;eligible=g[g.n.ge(100)];q=float(eligible.rate.quantile(.75)) if len(eligible) else np.nan
  for j,r in g.iterrows():stats.append({'race_date':ds,'jockey_id':j,'n':int(r.n),'top3_count':int(r.top3_count),'rate':r.rate,'last_date':r.last_date,'cutoff':hi,'window_start':lo,'top_quartile_cutoff':q,'eligible_jockeys':len(eligible),'upper':bool(r.n>=100 and r.rate>=q)})
 stats=pd.DataFrame(stats);assert stats.last_date.le(stats.cutoff).all()
 for side,key in [('current','jockey_id'),('previous','previous_jockey_id')]:
  z=stats.rename(columns={c:side+'_rider_'+c for c in stats if c not in ['race_date','jockey_id']}).rename(columns={'jockey_id':key})
  a=a.merge(z,on=['race_date',key],how='left',validate='many_to_one')
 a['rider_stats_valid']=a.current_rider_n.ge(100)&a.previous_rider_n.ge(100)
 a['changed_jockey']=a.previous_jockey_id.notna()&a.jockey_id.ne(a.previous_jockey_id)
 a['rider_rate_gain']=a.current_rider_rate-a.previous_rider_rate
 a['upgrade']=a.changed_jockey&a.rider_stats_valid&a.current_rider_upper.fillna(False).astype(bool)&a.rider_rate_gain.ge(.05-1e-12)
 a['upgrade10']=a.changed_jockey&a.rider_stats_valid&a.current_rider_upper.fillna(False).astype(bool)&a.rider_rate_gain.ge(.1-1e-12)
 a['same_relations']=a.trainer_id.eq(a.previous_trainer_id)&a.owner_id.eq(a.previous_owner_id)&a.owner_id.ne('unknown')
 a['switch_group']=np.select([~a.rider_stats_valid,~a.changed_jockey,a.upgrade],['unavailable','retained','upgrade'],default='other_change')
 pr=pd.read_csv(OLD/'forecast01/predictions.csv')
 for model in ['H0','H1']:
  z=pr[pr.model.eq(model)][['api_record_id','time_prediction','prob_top3']].rename(columns={'time_prediction':model+'_time','prob_top3':model+'_prob'})
  a=a.merge(z,on='api_record_id',how='left',validate='one_to_one')
  a=a.merge(z.rename(columns={c:'previous_'+c for c in z}),on='previous_api_record_id',how='left',validate='many_to_one')
  a[model+'_time_adv']=a[model+'_time']-a.relative_time
  a[model+'_top3_excess']=100*(a.top3-a[model+'_prob'])
  a['previous_'+model+'_time_adv']=a['previous_'+model+'_time']-a.previous_relative_time
  a['previous_'+model+'_top3_excess']=100*(a.previous_top3-a['previous_'+model+'_prob'])
 a=a.sort_values(['race_date','race_id','horse_number']).reset_index(drop=True)
 assert not a.horse_id.eq('3005648').any()
 a.to_csv(out/'starts.csv',index=False,encoding='utf-8-sig');stats.to_csv(out/'prior365_jockey_stats.csv',index=False,encoding='utf-8-sig')
 manifest.update(database_sha256_after=sha(db),database_read_only=True,owner_missing=missing,owners=a.owner_id.nunique(),history_edges_checked=edges,source_payloads_checked=len(a))
 assert manifest['database_sha256_before']==manifest['database_sha256_after']
 assert all(sha(ROOT/r['path'])==r['sha256'] for r in manifest['files']);save(out/'source_manifest.json',manifest)
 print('Inputs saved',len(a),'owners',a.owner_id.nunique(),'missing',missing,'back',int(a.back.sum()),flush=True)
if __name__=='__main__':main()
