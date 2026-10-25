"""Single evaluation pass, retaining all races and fixed ticket budgets."""
import json
from collections import defaultdict
import numpy as np
import pandas as pd
import study_common as c

def main():
    c.check();assert (c.OUT/'training_complete.json').exists()
    assert not (c.OUT/'evaluation_complete.json').exists(),'Evaluation already completed'
    f=c.old.frame();f=f[f.year>=2024].copy()
    flags=pd.read_parquet(c.old.BASE/'outputs/population_flags.parquet')
    f=f.merge(flags[c.KEY+['normal_finisher','ambiguous_flag']],on=c.KEY,validate='one_to_one')
    assert len(f)==50754 and f.race_key.nunique()==4799
    metrics=[];tickets=[];runners=[];cal=defaultdict(lambda:[0,0.,0.,0.])
    c.save(c.OUT/'evaluation_started.json',{'protocol_sha256':c.sha(c.OUT/'protocol_frozen.json'),
        'model_metadata_hashes':{str(p.relative_to(c.ROOT)):c.sha(p) for p in sorted((c.OUT/'models').glob('*/metadata.json'))}})
    for variant in c.VARIANTS:
        for meet in [1,3]:
            for year in [2024,2025,2026]:
                folder=c.OUT/'models'/f'{variant}_{meet}_{year}';meta=json.loads((folder/'metadata.json').read_text())
                assert c.sha(folder/'model.txt')==meta['model_sha256']
                scores=pd.read_parquet(folder/'scores.parquet').query("phase=='evaluation'").set_index('row_number').score
                one=f[f.meet.eq(meet)&f.year.eq(year)].copy();one['prediction']=one.row_number.map(scores)
                assert one.prediction.notna().all()
                for _,g in one.groupby('race_key',sort=False):
                    score=g.prediction.to_numpy(float);q=c.old.prob.trio_distribution(score,meta['temperature'])
                    orders,mass=c.old.prob.ordered_distribution(score,q,meta['order_temperature'])
                    row,tt,rr=c.old.scorer.score_race(g,score,orders,mass,variant,'all_starters',calibration=cal)
                    metrics.append(row);tickets.extend(tt);runners.append(rr)
                print('Evaluated',variant,meet,year,flush=True)
    pd.DataFrame(metrics).to_parquet(c.OUT/'race_metrics.parquet',index=False,compression='zstd')
    pd.DataFrame(tickets).to_parquet(c.OUT/'tickets.parquet',index=False,compression='zstd')
    pd.concat(runners,ignore_index=True).to_parquet(c.OUT/'runner_probabilities.parquet',index=False,compression='zstd')
    c.save(c.OUT/'calibration_bins.json',[dict(variant=k[0],year=k[1],meet=k[2],target=k[3],bin=k[4],observations=int(v[0]),
        race_weight=v[1],predicted=v[2]/v[1],observed=v[3]/v[1]) for k,v in sorted(cal.items())])
    c.save(c.OUT/'evaluation_complete.json',{'race_rows':len(metrics),'runner_rows':sum(map(len,runners)),
        'ticket_rows':len(tickets),'max_coherence_error':max(v['coherence_max_error'] for v in metrics),
        'same_4799_races':True,'evaluation_search_completed':True,'new_independent_test':False})
if __name__=='__main__':main()
