"""Post-hoc uncertainty for the observed zero-history calibration discrepancy."""
import json
from pathlib import Path
import numpy as np
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
def main():
    out=ROOT/'data/research/jeju_debut_diagnosis_20260919'
    model=ROOT/'data/research/jeju_accuracy_candidates_20260919'
    states=pl.read_parquet(ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2/horse_states.parquet').select('race_id','horse_id','starts_pre','event_date')
    ties={r['race_id'] for r in json.loads((out/'race_classification.json').read_text()) if r['boundary_tie']}
    horses=pl.read_parquet(model/'horse_predictions.parquet').filter((pl.col('model')=='BASE')&(~pl.col('race_id').is_in(ties))).join(states,on=['race_id','horse_id'],validate='m:1').filter(pl.col('starts_pre')==0)
    result=[]
    for year in [2024,2025,2026,'ALL']:
        group=horses if year=='ALL' else horses.filter(pl.col('year')==year)
        days=group.group_by('event_date').agg(pl.len().alias('n'),(pl.col('p')-pl.col('y')).sum().alias('residual')).sort('event_date')
        rng=np.random.default_rng(17);total=np.zeros(5000);den=np.zeros(5000)
        for y in sorted(group['year'].unique().to_list()):
            part=days.filter(pl.col('event_date').dt.year()==y);ix=rng.integers(0,len(part),(5000,len(part)))
            total+=part['residual'].to_numpy()[ix].sum(axis=1);den+=part['n'].to_numpy()[ix].sum(axis=1)
        result.append(dict(year=year,entries=len(group),overprediction=float((group['p']-group['y']).mean()),simultaneous95_4=np.quantile(total/den,[.025/4,1-.025/4]).tolist(),posthoc_diagnostic=True))
    (out/'zero_history_calibration_uncertainty.json').write_text(json.dumps(dict(method='5000 year-stratified race-day bootstrap; 4 contrasts Bonferroni; descriptive after subgroup inspection, not a promotion test',results=result),indent=2))
if __name__=='__main__':main()
