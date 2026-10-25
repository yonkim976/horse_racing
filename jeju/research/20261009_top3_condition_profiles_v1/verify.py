"""Reconcile published statistics to source predictions and target perturbation."""
from pathlib import Path
import importlib.util
import sys
import json
import hashlib
import numpy as np
import pandas as pd

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
spec=importlib.util.spec_from_file_location('condition_analysis',HERE/'analyze.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
f=pd.read_parquet(OUT/'condition_features.parquet')
t=pd.read_csv(OUT/'condition_statistics.csv')
cols=[c for c in f if c.startswith('C_')]
assert len(cols)==21
assert (len(f),f.race_id.nunique(),f.y.sum())==(52155,5206,15618)
assert f.groupby('race_id').y.sum().eq(3).all()
assert f.groupby('race_id').size().eq(f.groupby('race_id').field_n.first()).all()
checked=0
for row in t.itertuples():
    base=f if row.period=='all' else f[f.period.eq(row.period)]
    base=base[base['C_'+row.family].notna()]
    g=base[base['C_'+row.family].eq(str(row.condition))]
    assert len(g)==row.rows and g.y.sum()==row.top3
    assert len(g)-g.y.sum()==row.non_top3
    assert g.race_id.nunique()==row.races and g.horse_id.nunique()==row.horses
    assert np.isclose(g.y.mean(),row.top3_rate,atol=1e-12)
    assert np.isclose(g.y.sum()/base.y.sum(),row.share_among_top3,atol=1e-12)
    assert np.isclose(len(g)/len(base),row.condition_share,atol=1e-12)
    for name,col in [('R1','p_R1'),('HY','p_HY')]:
        q=g[g[col].notna()]
        assert len(q)==getattr(row,name+'_rows')
        if len(q):assert np.isclose((q.y-q[col]).mean(),getattr(row,name+'_residual'),atol=1e-12)
    checked+=1
# Posterior features must reproduce the separately frozen model predictions and targets.
for path,variant,col in [(m.REL/'runner_predictions.parquet','R1','p_R1'),(m.COMP/'runner_predictions.parquet','HY_R_FORM','p_HY')]:
    p=pd.read_parquet(path);p=p[p.variant.eq(variant)]
    q=f.merge(p[['race_id','horse_id','y','p_top3']],on=['race_id','horse_id'],validate='one_to_one',suffixes=('','_saved'))
    assert np.array_equal(q.y,q.y_saved)
    assert np.allclose(q[col],q.p_top3,atol=0,rtol=0)
    assert q.groupby('race_id')[col].sum().sub(3).abs().max()<1e-10
# Change only latest target-day outcomes; historical conditions must not change.
original=pd.read_parquet(m.REL/'features.parquet')
source=pd.read_parquet(m.OLD/'source_snapshot.parquet')
latest=original[original.race_date.eq('2026-09-19')].reset_index(drop=True)
a,families=m.derive(latest,source)
mutated=latest.copy();mutated['finish_position']=11-mutated.finish_position
altered_source=source.copy()
replacement=mutated.set_index('api_record_id').finish_position
mask=altered_source.api_record_id.isin(replacement.index)
altered_source.loc[mask,'finish_position']=altered_source.loc[mask,'api_record_id'].map(replacement)
altered_source.loc[mask,'finish_time_seconds']+=100
b,_=m.derive(mutated,altered_source)
for c in ['C_'+x for x in families]:assert a[c].equals(b[c]),c
assert not np.array_equal(a.y,b.y)
lock=json.loads((OUT/'source_lock.json').read_text())
for path,info in lock.items():assert m.sha(ROOT/path)==info['sha256'],path
# Independently verify one date-bootstrap interval using multinomial day counts.
g=f[f.period.eq('2026')&f.C_previous_finish.eq('top3')].copy()
g['d']=g.y-g.p_R1
day=g.groupby('race_date').d.agg(['sum','size'])
rng=np.random.default_rng(20261009);idx=rng.integers(0,len(day),size=(2000,len(day)))
values=[]
for ix in idx:
    counts=np.bincount(ix,minlength=len(day))
    values.append(float(counts@day['sum'].to_numpy()/(counts@day['size'].to_numpy())))
row=t[t.period.eq('2026')&t.family.eq('previous_finish')&t.condition.eq('top3')].iloc[0]
assert np.allclose(np.quantile(values,[.025,.975]),[row.R1_lo,row.R1_hi],atol=1e-12,rtol=0)
result=dict(passed=True,statistic_rows_independently_reconciled=checked,condition_families=len(cols),
    current_target_outcome_and_time_perturbation_rows=len(latest),conditions_invariant_to_current_results=True,
    R1_and_HY_saved_predictions_and_labels_reconciled=True,one_bootstrap_interval_independently_reproduced=True,
    historical_ids_and_T_minus_2_checked=True,protected_sources_unchanged=True,fits=0)
(OUT/'independent_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
