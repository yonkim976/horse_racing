"""Joint date bootstrap for predefined four-cell finish-change contrasts."""
import numpy as np
import pandas as pd
import run as e


def main():
    d = pd.read_parquet(e.OUT/'runner_diagnostics.parquet')
    d = d[d.role_ok & (d.role4==0) & d.gate_band.isin(['inner','outer']) & d.usual_band.isin(['faster','similar'])].copy()
    d['cell'] = d.gate_band+'_'+d.usual_band
    cells = ['inner_similar','inner_faster','outer_similar','outer_faster']
    weights = {'outer_minus_inner_faster':np.array([0,-1,0,1]),
               'outer_faster_minus_similar':np.array([0,0,-1,1]),
               'difference_in_differences':np.array([1,-1,-1,1])}
    rows=[]
    for scope,z in [('all',d)]+[(str(y),d[d.year==y]) for y in [2024,2025,2026]]:
        for part in ['last600_worsen','late_worsen']:
            a=z.dropna(subset=[part])
            ag=a.groupby(['date','cell'])[part].agg(['sum','count'])
            sums=ag['sum'].unstack().reindex(columns=cells).fillna(0).to_numpy()
            ns=ag['count'].unstack().reindex(columns=cells).fillna(0).to_numpy()
            mean=sums.sum(axis=0)/ns.sum(axis=0)
            rng=np.random.default_rng(20261011)
            draw=rng.integers(0,len(sums),size=(2000,len(sums)))
            boot=sums[draw].sum(axis=1)/ns[draw].sum(axis=1)
            for name,w in weights.items():
                lo,hi=np.quantile(boot@w,[.025,.975])
                rows.append(dict(scope=scope,section=part,contrast=name,mean=float(mean@w),lo=float(lo),hi=float(hi),
                                 cell_counts=';'.join(str(int(n)) for n in ns.sum(axis=0))))
    pd.DataFrame(rows).to_csv(e.OUT/'finish_contrasts.csv',index=False)
    e.check()
    print(pd.DataFrame(rows).to_string(index=False))


if __name__=='__main__':
    main()
