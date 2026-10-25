"""Immutable, already verified training features for jockey-specific comparisons."""
from pathlib import Path
import hashlib,json
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OLD=ROOT/'jeju/research/20261017_jockey_training_v1'
BASE=['body_kg','carried_weight_kg','gate_scaled','h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean','h_any_n','h_same_n','previous_rank_fraction','previous_relative_time','log_gap']
IDS=['horse_id','jockey_id','trainer_id','owner_id']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def periods(a):return {'all':a,'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}
def load():
 return pd.read_csv(OLD/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False),pd.read_csv(OLD/'input01/features.csv')
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False);a,f=load();assert len(a)==52155 and len(f)==3*len(a) and not a.horse_id.eq('3005648').any()
 t=pd.read_csv(OLD/'input01/training_rows.csv',usecols=['prNo_raw','jockey_name','rider_type'],dtype={'prNo_raw':str});t=t[t.rider_type.eq('기수')&t.jockey_name.notna()][['prNo_raw','jockey_name']].drop_duplicates();assert t.prNo_raw.is_unique
 names={r.prNo_raw:r.jockey_name for r in t.itertuples()};rows=[{'jockey_id':j,'jockey_name':names.get(j,j),'name_resolved':j in names} for j in sorted(a.jockey_id.unique())];pd.DataFrame(rows).to_csv(out/'jockey_names.csv',index=False,encoding='utf-8-sig')
 paths=[OLD/'input01/starts.csv',OLD/'input01/features.csv',OLD/'input01/training_rows.csv',OLD/'input01/source_manifest.json',OLD/'verification02/verification.json',OLD/'verification02/current_source_context.json',OLD/'analysis.py',OLD/'publication_verification.json',HERE/'PLAN.md']
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in paths],'source_starts':len(a),'source_races':a.race_id.nunique(),'source_horses':a.horse_id.nunique(),'source_jockeys':a.jockey_id.nunique(),'data_upper':'2026-09-19','partial_2026':True,'database_opened':False,'future_or_unknown_training_not_treated_as_negative':True})
 print('Frozen sources verified',len(a),'starts',len(rows),'jockey IDs',flush=True)
if __name__=='__main__':main()
