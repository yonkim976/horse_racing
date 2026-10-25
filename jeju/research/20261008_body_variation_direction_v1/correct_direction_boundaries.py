"""Apply decimal-time boundary tolerance; preserve all initial estimates."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent
p=pd.read_csv(H/'pair_features.csv',dtype={'horse_id':str});raw=pd.read_csv(H/'raw_direction_groups.csv');old=raw.copy();periods=json.loads((H/'PLAN.json').read_text())['periods'];cache={};changed=0
for i,r in raw.iterrows():
    key=(r['period'],r['variant'])
    if key not in cache:
        lo,hi=periods[r['period']];mode='same_distance' if r['variant']=='same_distance_baseline' else 'personal';z=p[p.year.between(lo,hi)&p[mode+'_mean'].notna()].copy();threshold=z[mode+'_mean']+(z[mode+'_sd'] if r['variant']=='large_threshold' else 0);d=z.body_change_kg
        z['selected_group']=np.where(d.eq(0),'zero',np.where(d.gt(0),np.where(d.le(threshold),'gain_within','gain_above'),np.where(-d<=threshold,'loss_within','loss_above')))
        if r['variant']=='stable_conditions':z=z[z.month.eq(z.previous_month)&z.band.eq(z.previous_band)&z.burden_change.abs().le(1)]
        cache[key]=z
    z=cache[key];g=z[z.distance.eq(r['distance'])&z.selected_group.eq(r['group'])];assert len(g)==r['rows']
    for outcome,col in [('raw','time_delta'),('relative','relative_time_delta')]:
        v=g[col];rounded=v.round(6);raw.loc[i,outcome+'_exact_equal_count']=int(rounded.eq(0).sum())
        for margin,label in [(.5,'half'),(1.,'one')]:
            counts=[]
            for tag,mask in [('improved',v< -margin-1e-8),('similar',v.abs()<=margin+1e-8),('worsened',v>margin+1e-8)]:
                # Independent decimal rounding must produce exactly the same counts.
                check=rounded.lt(-margin) if tag=='improved' else rounded.abs().le(margin) if tag=='similar' else rounded.gt(margin)
                assert mask.equals(check)
                ck=f'{outcome}_{label}_{tag}_count';rk=f'{outcome}_{label}_{tag}_rate';changed+=int(mask.sum()!=r[ck]);raw.loc[i,ck]=int(mask.sum());raw.loc[i,rk]=mask.mean();counts.append(int(mask.sum()))
            assert sum(counts)==len(g)
        raw.loc[i,outcome+'_absolute_record_change_mean_s']=v.abs().mean();raw.loc[i,outcome+'_absolute_record_change_p90_s']=v.abs().quantile(.9)
with (H/'raw_direction_groups_v2.csv').open('x') as f:raw.to_csv(f,index=False)
result={'reason':'Race-median relative deltas contain binary floating point residuals at exactly0.5/1.0s boundaries. Use1e-8s tolerance, independently matched to six-decimal rounding. No statistical estimates, CIs, p values, q values or body groups changed.','final_descriptive_file':'raw_direction_groups_v2.csv','original_preserved':'raw_direction_groups.csv','changed_count_cells':changed,'all_groups_partition_and_decimal_checks_passed':True,'record_magnitude_columns':'Additional descriptive absolute record change mean/p90; no new significance claims.'}
with (H/'boundary_correction_verification.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
print(json.dumps(result))
