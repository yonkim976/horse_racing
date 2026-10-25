"""Read verified rider types; aggregate only pre-cutoff observed training rows."""
from pathlib import Path
import hashlib,json,sqlite3
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
DB=ROOT/'jeju/data/jeju_native_core.sqlite3'
SOURCE=ROOT/'jeju/research/20261016_layoff_return_v1/input01/starts.csv'
IDS=['horse_id','jockey_id','trainer_id','owner_id']
BASE=['body_kg','carried_weight_kg','gate_scaled','h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean','h_any_n','h_same_n','previous_rank_fraction','previous_relative_time','log_gap']
WINDOWS=[7,14,28];PERIODS=['all','2024_2025','2026']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def periods(a):return {'all':a,'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}
def features(a,tr):
 groups={h:g.sort_values(['training_date','daily_training_api_row_id']) for h,g in tr.groupby('horse_id',sort=False)};rows=[];lineage=[]
 for h,g in a.groupby('horse_id',sort=False):
  t=groups.get(h,tr.iloc[:0]);dates=t.training_date.to_numpy(dtype='datetime64[D]');ids=t.daily_training_api_row_id.to_numpy();typ=t.rider_type.to_numpy();jok=typ=='기수';unknown=typ=='미분류';pr=t.prNo_raw.fillna('').to_numpy();valid=t.prNo_raw.fillna('').str.fullmatch(r'\d{6}').to_numpy();duration=t.duration_seconds.to_numpy(float)
  for r in g.itertuples():
   end=np.datetime64(r.history_cutoff,'D');race=np.datetime64(r.race_date,'D');prev=np.datetime64(r.previous_race_date,'D') if pd.notna(r.previous_race_date) else None
   for w in WINDOWS:
    start=race-np.timedelta64(w,'D')
    if prev is not None:start=max(start,prev+np.timedelta64(1,'D'))
    lo,hi=np.searchsorted(dates,start,'left'),np.searchsorted(dates,end,'right')
    assert hi>=lo
    ix=slice(lo,hi);n=hi-lo;nj=int(jok[ix].sum());nu=int(unknown[ix].sum());badj=int((jok[ix]&~valid[ix]).sum());same=jok[ix]&valid[ix]&(pr[ix]==r.jockey_id);ns=int(same.sum());complete=n>0 and nu==0;identity=complete and badj==0
    group='no_rows' if n==0 else 'same_jockey' if ns else 'other_jockey_only' if nj and identity else 'non_jockey_only' if complete and nj==0 else 'uncertain'
    row={'api_record_id':r.api_record_id,'window_days':w,'window_start':str(start),'window_end':str(end),'training_rows':n,'training_days':len(np.unique(dates[ix])),'unknown_type_rows':nu,'known_jockey_rows':nj,'known_jockey_days':len(np.unique(dates[ix][jok[ix]])),'invalid_jockey_id_rows':badj,'same_jockey_rows':ns,'same_jockey_days':len(np.unique(dates[ix][same])),'role_complete':complete,'identity_complete':identity,'any_jockey':nj>0,'same_jockey':ns>0,'observed_group':group,'duration_known_rows':int(np.isfinite(duration[ix]).sum()),'training_minutes':float(np.nansum(duration[ix])/60),'duration_missing_rows':int(np.isnan(duration[ix]).sum())};rows.append(row)
    for k in ids[ix]:lineage.append({'api_record_id':r.api_record_id,'window_days':w,'daily_training_api_row_id':int(k)})
 return pd.DataFrame(rows),pd.DataFrame(lineage)
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False);before=sha(DB)
 a=pd.read_csv(SOURCE,dtype={c:str for c in IDS},low_memory=False)
 assert len(a)==52155 and not a.horse_id.eq('3005648').any()
 c=sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True);c.execute('PRAGMA query_only=ON')
 cols='daily_training_api_row_id,daily_training_api_artifact_id,source_row_index,horse_id,training_date,rider_type,rider_type_status,prGubun_raw,prNo_raw,jockey_name,jockey_name_status,duration_seconds,source_sha256,rider_type_website_sha256'
 q='SELECT '+cols+' FROM daily_training_rider_types_analysis_2026 WHERE training_date BETWEEN ? AND ? ORDER BY horse_id,training_date,daily_training_api_row_id'
 tr=pd.read_sql_query(q,c,params=('2016-12-16','2026-09-17'),dtype={'horse_id':str,'prNo_raw':str});c.close();tr=tr[tr.horse_id.isin(set(a.horse_id))].copy()
 assert tr.daily_training_api_row_id.is_unique and not tr.horse_id.eq('3005648').any()
 tr.to_csv(out/'training_rows.csv',index=False,encoding='utf-8-sig');a.to_csv(out/'starts.csv',index=False,encoding='utf-8-sig')
 f,l=features(a,tr);assert not f.duplicated(['api_record_id','window_days']).any() and len(f)==3*len(a)
 f.to_csv(out/'features.csv',index=False,encoding='utf-8-sig');l.to_csv(out/'lineage.csv',index=False,encoding='utf-8-sig')
 census=[]
 for period,g in periods(a).items():
  z=f[f.api_record_id.isin(g.api_record_id)]
  for w,v in z.groupby('window_days'):
   census.append({'period':period,'window_days':int(w),'starts':len(v),'no_rows':int(v.training_rows.eq(0).sum()),'role_complete':int(v.role_complete.sum()),'identity_complete':int(v.identity_complete.sum()),'unknown_type_window':int(v.unknown_type_rows.gt(0).sum()),'any_yes_complete':int((v.role_complete&v.any_jockey).sum()),'any_no_complete':int((v.role_complete&~v.any_jockey).sum()),'same_yes_complete':int((v.identity_complete&v.any_jockey&v.same_jockey).sum()),'other_only_complete':int((v.identity_complete&v.any_jockey&~v.same_jockey).sum()),'any_yes_observed':int(v.any_jockey.sum()),'same_yes_observed':int(v.same_jockey.sum())})
 save(out/'denominator_census.json',census);after=sha(DB);assert before==after
 sources=[SOURCE,ROOT/'jeju/research/20261015_training_rider_types/README.md',ROOT/'jeju/research/20261015_training_rider_types/verification/production_full_html_verification.json',ROOT/'jeju/research/20261015_training_rider_identity/README.md',ROOT/'jeju/docs/JEJU_TRAINING_API_INPUT_CONTRACT_2026-10-01.md',HERE/'PLAN.md']
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'database_path':str(DB.relative_to(ROOT)),'database_sha256_before':before,'database_sha256_after':after,'database_bytes':DB.stat().st_size,'training_rows_extracted':len(tr),'training_horses':tr.horse_id.nunique(),'cohort_starts':len(a),'lineage_links':len(l),'data_upper':'2026-09-19','partial_2026':True,'database_read_only':True,'database_written':False,'training_date_not_publication_time':True,'window_contract':'race-minus-window through T-2, after previous observed actual start; all original training row IDs retained'})
 print(json.dumps(census,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
