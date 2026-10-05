"""Pooled date-cluster differences; replay completed supplementary calculations."""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd

OUT=Path(__file__).resolve().parent/'outputs'

def calculate():
    r=pd.read_csv(OUT/'race_metrics.csv',low_memory=False)
    rng=np.random.default_rng(20261005);rows=[]
    for a,b in [('raw','replace'),('raw','augment'),('raw_joint','replace_joint'),('raw_joint','augment_joint')]:
        x=r[r.variant.eq(a)].merge(r[r.variant.eq(b)],on='race_key',suffixes=('_a','_b'),validate='one_to_one')
        for metric in ['trio6_hit','trio_nll','top3_brier']:
            delta=x[metric+'_b']-x[metric+'_a']
            d=pd.DataFrame({'date':x.race_date_a,'delta':delta}).groupby('date').delta.agg(['sum','size']).to_numpy()
            samples=d[rng.integers(0,len(d),size=(2000,len(d)))].sum(axis=1)
            rows.append(dict(base=a,candidate=b,metric=metric,races=len(x),difference=float(delta.mean()),
                             date_bootstrap_95_interval=np.quantile(samples[:,0]/samples[:,1],[.025,.975]).tolist()))
    return rows

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    target=OUT/'pooled_differences.json';rows=calculate()
    if args.verify:
        if json.loads(target.read_text())!=rows:raise AssertionError('Pooled calculation changed')
        print('Pooled differences reproduced:',len(rows))
    else:
        if target.exists():raise FileExistsError('Completed pooled differences')
        target.write_text(json.dumps(rows,indent=2)+'\n')
