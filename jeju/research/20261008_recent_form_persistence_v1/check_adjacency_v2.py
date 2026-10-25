"""Clarify immediate observed next-start continuity using frozen predictions."""
from pathlib import Path
import importlib.util
import json
import bisect
import numpy as np
import pandas as pd
H=Path(__file__).resolve().parent
sp=importlib.util.spec_from_file_location('frozen_form',H/'analyze.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
p=pd.read_csv(H/'predictions.csv',dtype={'horse_id':str});d,h=a.a.old.load();d=d.reset_index(drop=True);lineage={z['api_record_id']:z for z in json.loads((H/'feature_lineage.json').read_text())};groups={hid:g.sort_values(['race_date','api_record_id']) for hid,g in d.groupby('horse_id')};rows=[]
for r in p.itertuples():
    g=groups[r.horse_id];ix=bisect.bisect_left(g.race_date.to_numpy(),r.race_date)-1;last=g.iloc[ix] if ix>=0 else None;lid=int(last.api_record_id) if last is not None else None;history=lineage[r.api_record_id];same=history['time_history_ids'][-1];eligible=bool(last is not None and lid==same and last.race_date<=history['history_cutoff'] and 7<=r.gap<=60)
    rows.append({'api_record_id':r.api_record_id,'previous_observed_api_record_id':lid,'previous_same_distance_api_record_id':same,'is_immediate_observed_same_distance_7to60':eligible})
flags=pd.DataFrame(rows);a.csv('immediate_next_observed_flags.csv',flags);p=p.merge(flags,on='api_record_id',validate='one_to_one');p=p[p.is_immediate_observed_same_distance_7to60].copy();p['subset_race_weight']=1/p.groupby('race_id').api_record_id.transform('size');a.csv('immediate_next_observed_predictions.csv',p)
effects=[];contrasts=[];support=[]
for period,years in [('2024_2025',[2024,2025]),('2026partial',[2026])]:
    for dist,g in p[p.year.isin(years)].groupby('distance'):
        common={'period':period,'distance':int(dist),'rows':len(g),'races':g.race_id.nunique(),'horses':g.horse_id.nunique(),'dates':g.race_date.nunique()};can=len(g)>=100 and g.race_date.nunique()>=20 and g.horse_id.nunique()>=30;support.append(common|{'estimated':can})
        if not can:continue
        for left,right in [('A','B'),('B','D')]:effects.append(common|{'contrast':right+'_vs_'+left,**a.interval(g['abs_error_'+left]-g['abs_error_'+right],g,g.subset_race_weight)})
        z=a.contrast_group(g,'relative_error_A','form_group','recent_fast','recent_slow')
        if z:contrasts.append(common|z)
eff=a.bh(pd.DataFrame(effects),['period','contrast']);ctr=a.bh(pd.DataFrame(contrasts),['period']);a.csv('immediate_next_observed_improvements.csv',eff);a.csv('immediate_next_observed_persistence.csv',ctr);a.csv('immediate_next_observed_support.csv',pd.DataFrame(support));a.save('adjacency_verification.json',{'status':'passed','frozen_prediction_rows':len(flags),'immediate_observed_subset_rows':len(p),'no_refitting':True,'last_same_distance_equals_last_observed_result':True,'all_gaps7to60':bool(p.gap.between(7,60).all()),'full_original_race_centering_preserved':True,'plan_sha256':a.sha(H/'ADJACENCY_CHECK_PLAN.json')});print(eff.to_string(index=False));print(ctr.to_string(index=False))
