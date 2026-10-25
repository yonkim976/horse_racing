"""Matched operating reference for rider-free candidates; no re-fitting."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;OUT=HERE/'outputs'
OPS=HERE.parent/'20261004_close_contenders_v1/outputs'

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    target=OUT/'operating_comparison.json'
    if target.exists():raise FileExistsError('Completed comparison')
    sources=[OUT/'race_metrics.csv',OUT/'runner_predictions.parquet',OPS/'race_diagnostics.csv',OPS/'operating_runner_predictions.parquet']
    hashes={str(p):sha(p) for p in sources}
    races=pd.read_csv(sources[0],low_memory=False);runners=pd.read_parquet(sources[1])
    op=pd.read_csv(sources[2]);op=op[op.variant.eq('operating_exact_2026')].copy();op_r=pd.read_parquet(sources[3])
    for f in [runners,op_r]:f['comparison_rank']=f.outcome.where(f.outcome.between(1,20),0).astype(int)
    old_sets=op_r.groupby('race_key').apply(lambda g:frozenset(zip(g.program_no,g.horse_id,g.comparison_rank)),include_groups=False)
    new_sets=runners[runners.variant.eq('no_jockey')].groupby('race_key').apply(
        lambda g:frozenset(zip(g.program_no,g.horse_id,g.comparison_rank)),include_groups=False)
    op['bridge']=(op.race_key.str.replace('RACE:SEOUL:','1:',regex=False).str.replace('RACE:BUSAN:','3:',regex=False)
                  .str.replace(r':0([1-9])$',r':\1',regex=True))
    matched=[row.bridge in new_sets.index and new_sets[row.bridge]==old_sets[row.race_key] for row in op.itertuples()]
    op=op[matched];rng=np.random.default_rng(20261006);rows=[]
    for meet in (0,1,3):
        for variant in sorted(races.variant.unique()):
            a=races[races.variant.eq(variant)];b=op
            if meet:a=a[a.meet.eq(meet)];b=b[b.meet.eq(meet)]
            p=a.merge(b,left_on='race_key',right_on='bridge',suffixes=('_new','_op'),validate='one_to_one')
            if len(p)!=len(b):raise ValueError('Lost operating comparison race')
            delta=p.trio6_hit_new-p.trio6_hit_op
            d=pd.DataFrame({'date':p.race_date_new,'delta':delta}).groupby('date').delta.agg(['sum','size']).to_numpy()
            draws=d[rng.integers(0,len(d),size=(2000,len(d)))].sum(axis=1)
            rows.append(dict(meet=meet,variant=variant,races=len(p),new_rate=float(p.trio6_hit_new.mean()),
                             operating_rate=float(p.trio6_hit_op.mean()),difference=float(delta.mean()),
                             date_bootstrap_95_interval=np.quantile(draws[:,0]/draws[:,1],[.025,.975]).tolist()))
    if any(sha(Path(p))!=h for p,h in hashes.items()):raise ValueError('Input changed')
    result=dict(inputs=hashes,matched_races=len(op),numeric_rank_and_program_and_horse_match=True,
                bootstrap_seed=20261006,bootstrap_draws=2000,comparisons=rows)
    target.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps([x for x in rows if x['meet']==0]))

if __name__=='__main__':main()
