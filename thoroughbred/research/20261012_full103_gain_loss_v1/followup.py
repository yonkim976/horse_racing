"""Cross-tabulate the already observed diagnostic patterns; exploratory only."""
import numpy as np
import pandas as pd
import run as e


def main():
    e.check();d=pd.read_parquet(e.OUT/'races.parquet');rows=[]
    for period,z in e.windows(d):
        for cols in [['meet','grade'],['meet','distance_band'],['grade','new_front_support'],
                     ['grade','new_gate_band'],['new_front_band','new_fast_late'],
                     ['new_gate_band','new_vs_old_recent']]:
            for cell,g in z.groupby(cols,dropna=False,observed=True):
                rows.append(dict(period=period,strata='+'.join(cols),cell=str(cell),**e.summary(g)))
    pd.DataFrame(rows).to_csv(e.OUT/'cross_conditions.csv',index=False)
    rows=[];rng=np.random.default_rng(20261013)
    for matched in [False,True]:
        samples=[]
        for year in [2025,2026]:
            z=d[d.year.eq(year)]
            if matched: z=z[z.race_date.dt.strftime('%m-%d').le('09-20')]
            g=z.groupby('race_date').net.agg(['sum','size'])
            idx=rng.integers(len(g),size=(2000,len(g)))
            samples.append(g['sum'].to_numpy()[idx].sum(axis=1)/g['size'].to_numpy()[idx].sum(axis=1))
        lo,hi=np.quantile(samples[1]-samples[0],[.025,.975])
        rows.append(dict(matched=matched,ci_low=float(lo),ci_high=float(hi)))
    e.save(e.OUT/'year_interaction_ci.json',dict(seed=20261013,bootstrap=2000,unit='race_date',
        years_independently_resampled=True,comparisons=rows,multiplicity_adjusted=False))
    # Group-observed status required; no conversion of missing roles to negatives.
    rows=[]
    for period,z in e.windows(d):
        for kind in ['all_switches','gain','loss','both_hit','both_miss']:
            a=z[z.switched] if kind=='all_switches' else z[z.kind.eq(kind)]
            for side in ['old','new']:
                q=a[a[side+'_actual_role_valid'].eq(True)]
                pred=q[side+'_front_gate_probability'];actual=q[side+'_actual_role4'].eq(0)
                rows.append(dict(period=period,kind=kind,side=side,switches=len(a),observed=len(q),
                                 predicted_front=pred.mean(),actual_front=actual.mean(),
                                 brier=((pred-actual.astype(float))**2).mean()))
    pd.DataFrame(rows).to_csv(e.OUT/'observed_front_diagnostics.csv',index=False)
    e.check()


if __name__=='__main__': main()
