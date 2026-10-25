"""One frozen-budget evaluation, with no score-based subgroup selection."""
import json
from collections import defaultdict
import numpy as np
import pandas as pd
import common as c
import joint

def main():
    c.check_inputs()
    assert (c.OUT/'training_complete.json').exists()
    assert not (c.OUT/'evaluation_complete.json').exists(),'No repeated candidate search'
    f=c.frame();f=f[f.year>=2024].copy()
    flags=pd.read_parquet(c.BASE/'outputs/population_flags.parquet')
    f=f.merge(flags[c.KEY+['normal_finisher','ambiguous_flag']],on=c.KEY,validate='one_to_one')
    assert len(f)==50754 and f.race_key.nunique()==4799
    metrics=[];tickets=[];runners=[];cal=defaultdict(lambda:[0,0.,0.,0.])
    for variant,cols in c.features().items():
        for meet in [1,3]:
            for year in [2024,2025,2026]:
                folder=c.OUT/'models'/f'{variant}_{meet}_{year}'
                meta=json.loads((folder/'metadata.json').read_text())
                assert c.sha(c.ROOT/meta['model_path'])==meta['model_sha256']
                one=f[f.meet.eq(meet)&f.year.eq(year)].reset_index(drop=True)
                if variant=='state_joint':
                    encoding=json.loads((folder/'encoding.json').read_text())
                    x,_=joint.encode(one,cols,meta=encoding)
                    model=joint.restore(c.ROOT/meta['model_path'],meta['inputs'])
                else:
                    scores=pd.read_parquet(folder/'scores.parquet').query("phase=='evaluation'").set_index('row_number').score
                    one['prediction']=one.row_number.map(scores)
                    assert one.prediction.notna().all()
                for ix in one.groupby('race_key',sort=False).indices.values():
                    g=one.iloc[ix]
                    if variant=='state_joint':
                        orders,mass=joint.distribution(model,x[ix],meta['temperature'])
                        s=c.prob.marginals(len(g),orders,mass)['top3']
                    else:
                        s=g.prediction.to_numpy(float)
                        q=c.prob.trio_distribution(s,meta['temperature'])
                        orders,mass=c.prob.ordered_distribution(s,q,meta['order_temperature'])
                    row,tt,rr=c.scorer.score_race(g,s,orders,mass,variant,'all_starters',calibration=cal)
                    metrics.append(row);tickets.extend(tt);runners.append(rr)
                print('Evaluated',variant,meet,year,one.race_key.nunique(),flush=True)
    pd.DataFrame(metrics).to_parquet(c.OUT/'race_metrics.parquet',index=False,compression='zstd')
    pd.DataFrame(tickets).to_parquet(c.OUT/'tickets.parquet',index=False,compression='zstd')
    pd.concat(runners,ignore_index=True).to_parquet(c.OUT/'runner_probabilities.parquet',index=False,compression='zstd')
    records=[]
    for (variant,year,meet,name,b),v in cal.items():
        records.append(dict(variant=variant,year=year,meet=meet,target=name,bin=b,observations=int(v[0]),
            race_weight=v[1],probability_sum=v[2],hit_sum=v[3],predicted=v[2]/v[1],observed=v[3]/v[1]))
    c.save(c.OUT/'calibration_bins.json',records)
    c.save(c.OUT/'evaluation_complete.json',{'race_rows':len(metrics),'runner_rows':sum(map(len,runners)),
        'ticket_rows':len(tickets),'max_coherence_error':max(r['coherence_max_error'] for r in metrics),
        'variants':list(c.features()),'new_independent_test':False})
    print('Evaluation complete bytes',c.storage_check(),flush=True)

if __name__=='__main__':main()
