"""Descriptive input and training diagnostics; no candidate selection."""
import json
import numpy as np
import pandas as pd
import common as c

def main():
    f=c.frame();one=f[f.year>=2024];rows=[]
    for meet,g in one.groupby('meet'):
        rows.append({'meet':int(meet),'runners':len(g),'races':int(g.race_key.nunique()),
            'no_rank_observations':int(g.state_rank_n.eq(0).sum()),
            'no_form_observations':int(g.state_form_n.eq(0).sum()),
            'no_early_observations':int(g.state_early_n.eq(0).sum()),
            'no_closing_observations':int(g.state_close_n.eq(0).sum()),
            'rank_sd_quantiles':g.state_rank_current_sd.quantile([0,.5,.9,1]).to_list(),
            'days_quantiles':g.state_days.quantile([0,.5,.9,1]).to_list()})
    trees=[]
    for p in sorted((c.OUT/'models').glob('*/metadata.json')):
        m=json.loads(p.read_text())
        if 'gain' in m:
            gain=m['gain'];total=sum(gain.values())
            trees.append({'model':p.parent.name,'iterations':m['trees'],
                'state_gain_fraction':sum(v for k,v in gain.items() if k.startswith('state_'))/total,
                'top_features':sorted(gain.items(),key=lambda z:-z[1])[:10]})
    calibration=[]
    if (c.OUT/'evaluation_complete.json').exists():
        bins=pd.DataFrame(json.loads((c.OUT/'calibration_bins.json').read_text()))
        old=pd.read_csv(c.BASE/'outputs/calibration_bins.csv')
        bins=pd.concat([bins,old[old.variant.eq('additive89')]],ignore_index=True)
        bins=bins.groupby(['variant','target','bin'])[['race_weight','probability_sum','hit_sum']].sum().reset_index()
        for (variant,target),g in bins.groupby(['variant','target']):
            calibration.append({'variant':variant,'target':target,
                'mean_predicted':float(g.probability_sum.sum()/g.race_weight.sum()),
                'mean_observed':float(g.hit_sum.sum()/g.race_weight.sum()),
                'ten_equal_width_bin_ece':float((g.probability_sum-g.hit_sum).abs().sum()/g.race_weight.sum())})
    c.save(c.OUT/'descriptive_diagnostics.json',{'evaluation_input_coverage':rows,'tree_training_diagnostics':trees,
        'calibration_descriptive_only':calibration,
        'importance_is_not_causal_or_a_validation_metric':True,'additional_training_or_selection':False})
    print(json.dumps(rows,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
