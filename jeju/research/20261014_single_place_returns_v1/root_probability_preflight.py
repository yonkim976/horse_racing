"""Reproduce saved Top3 marginals without labels, refitting or return scoring."""
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
SOURCE=ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
 saved_path=SOURCE/'report/runner_predictions.parquet'
 assert sha(saved_path)=='706bca01e5f5e780a8ffbe9e2ad4553fea9e3d76df097b4c9648d7aabac44e56'
 cols=['api_record_id','race_id','race_date','year','horse_id','horse_number','field_n','variant','score','p_top3']
 f=pd.read_parquet(saved_path,columns=cols);f=f[f.variant.eq('F1_STYLE6')].copy()
 assert len(f)==17412 and f.race_id.nunique()==1779 and f.api_record_id.is_unique
 references=[];sources={str(saved_path.relative_to(ROOT)):sha(saved_path)}
 for year in [2024,2025,2026]:
  folder=SOURCE/f'F1_STYLE6_{year}';meta=json.loads((folder/'meta.json').read_text())
  scores=pd.read_parquet(folder/'evaluation_scores.parquet').set_index('api_record_id')
  one=f[f.year.eq(year)];assert np.array_equal(one.score,scores.loc[one.api_record_id].score)
  for path in [folder/'meta.json',folder/'evaluation_scores.parquet']:sources[str(path.relative_to(ROOT))]=sha(path)
  tau=meta['tau'];assert pd.Timestamp(meta['calibration_max'])<pd.to_datetime(one.race_date).min()
  for rid,g in one.groupby('race_id',sort=True):
   g=g.sort_values('horse_number');numbers=g.horse_number.to_numpy();z=g.score.to_numpy()
   triples=np.array(list(itertools.combinations(range(len(g)),3)))
   energy=np.sort(z[triples],axis=1).sum(axis=1)/tau
   q=np.exp(energy-energy.max());q/=q.sum()
   p=np.bincount(triples.reshape(-1),weights=np.repeat(q,3),minlength=len(g))
   assert np.allclose(g.p_top3,p,rtol=0,atol=1e-12) and abs(p.sum()-3)<1e-12
   assert g.field_n.eq(len(g)).all()
   # Monotone subset marginals and score agree on the same deterministic anchor.
   pick=int(np.argmax(z));assert p[pick]>=p.max()-1e-12
   row=g.iloc[pick]
   references.append({'race_id':str(rid),'race_date':str(pd.Timestamp(row.race_date).date()),'year':year,
    'horse_id':str(row.horse_id),'horse_number':int(row.horse_number),'api_record_id':str(row.api_record_id),
    'field_n':len(g),'score':float(row.score),'p_top3':float(row.p_top3),
    'p_place':float(row.p_top3) if len(g)>=8 else None,'place_finish_cutoff':3 if len(g)>=8 else 2})
 ref=pd.DataFrame(references);assert ref.field_n.eq(7).sum()==36
 target=STUDY/'ROOT_ANCHOR_REFERENCE.csv';assert not target.exists();ref.to_csv(target,index=False)
 report={'status':'PASS','target_labels_read':False,'fit_or_recalibration_runs':0,
  'races':1779,'runner_rows':17412,'native_probability_supported_races':1743,'Top2_probability_unavailable_races':36,
  'source_hashes':sources,'anchor_reference_sha256':sha(target)}
 dest=STUDY/'ROOT_PROBABILITY_PREFLIGHT.json';assert not dest.exists();dest.write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report))

if __name__=='__main__':main()
