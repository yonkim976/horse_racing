"""Explicit exploratory group compression, after primary results; no adoption."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
H=Path(__file__).resolve().parent
models=json.loads((H/'models.json').read_text());plan=json.loads((H/'GROUP_DIAGNOSTIC.json').read_text());out=[]
for d in sorted({m['distance'] for m in models}):
    past=[m for m in models if m['period']=='past' and m['variant']=='primary' and m['distance']==d]
    if not past:continue
    original=np.array(past[0]['model']['gate_effects']);co=original.copy()
    for group in plan['groups']:
        ix=np.array(group)-1;co[ix]=original[ix].mean()
    assert abs(co.mean())<1e-10
    for period in ['confirmation','2026partial']:
        held=[m for m in models if m['period']==period and m['variant']=='primary' and m['distance']==d]
        if not held:continue
        m=held[0]['model'];target=np.array(m['gate_effects']);val,vec=np.linalg.eigh(m['gate_cov'])
        rng=np.random.default_rng(20261008);draw=target+rng.normal(size=(2000,10))@(vec*np.sqrt(np.maximum(val,0))).T
        base=np.sqrt(np.mean(draw**2,axis=1));baseline=float(np.sqrt(np.mean(target**2)))
        for rate in plan['rates']:
            rms=float(np.sqrt(np.mean((target-rate*co)**2)));delta=np.sqrt(np.mean((draw-rate*co)**2,axis=1))-base
            lo,hi=np.quantile(delta,[.025,.975]);out.append({'distance':d,'period':period,'rate':rate,'baseline_RMS_s':baseline,'corrected_RMS_s':rms,'change_s':rms-baseline,'ci_lo':float(lo),'ci_hi':float(hi),'status':'exploratory_after_primary_results_no_rate_selected'})
pd.DataFrame(out).to_csv(H/'exploratory_group_rate_checks.csv',index=False)
g=pd.read_csv(H/'lateral_seconds.csv');g=g[(g.period=='full')&(g.variant=='primary')&~g.contrast.str.contains('_minus_')].copy()
g['trial_rate']=.5;g['trial_adjustment_s']=g.adjustment_s*.5;g['trial_lo']=g.adjustment_lo*.5;g['trial_hi']=g.adjustment_hi*.5
g['status']='illustrative_half_effect_not_optimal_or_adopted'
g.to_csv(H/'illustrative_half_group_table.csv',index=False)
print(pd.DataFrame(out).query("period=='confirmation' and rate==.5").round(4).to_string(index=False))
