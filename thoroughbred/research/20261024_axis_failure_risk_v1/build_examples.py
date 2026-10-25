"""One prior-trained base axis per race, plus compact conditional marginals."""
import json
import failure_common as c
import numpy as np
import pandas as pd

def main():
    c.check();f=c.old.frame();f.index=f.row_number;rows=[];runner_rows=[];sources=[]
    for meet in [1,3]:
        for year in range(2020,2027):
            folder=c.base_folder(meet,year);meta=json.loads((folder/'metadata.json').read_text())
            assert meta['train_end_year']==year-2 and meta['calibration_year']==year-1
            s=pd.read_parquet(folder/'scores.parquet');s=s[s.phase.eq('evaluation')].set_index('row_number').score
            one=f.loc[s.index];assert one.meet.eq(meet).all() and one.year.eq(year).all()
            for _,g in one.groupby('race_key',sort=False):
                g=g.sort_values('program_no')
                row,rr=c.race_example(g,s.loc[g.row_number].to_numpy(float),meta['temperature'])
                rows.append(row);runner_rows.append(rr)
            sources.append({'meet':meet,'year':year,'train_end_year':year-2,'temperature_year':year-1,
                'model':str((folder/'model.txt').relative_to(c.ROOT)),'model_sha256':c.sha(folder/'model.txt'),
                'scores_sha256':c.sha(folder/'scores.parquet'),'races':int(one.race_key.nunique()),'runners':len(one)})
            print('Examples',meet,year,flush=True)
    examples=pd.DataFrame(rows).sort_values(['race_date','meet','race_key']).reset_index(drop=True)
    runners=pd.concat(runner_rows,ignore_index=True)
    assert not examples.race_key.duplicated().any() and not runners.duplicated(c.KEY).any()
    assert all(pd.api.types.is_numeric_dtype(examples[k]) for k in c.FEATURES)
    ev=examples[examples.year.ge(2024)];assert len(ev)==4799
    ref=pd.read_parquet(c.PREV/'outputs/race_metrics.parquet');ref=ref[ref.variant.eq('state_gbm')]
    a=ev.merge(ref[['race_key','axis_program_no','axis_top3','axis_probability']],on='race_key',validate='1:1',suffixes=('','_reference'))
    assert len(a)==4799 and a.axis_program_no.eq(a.axis_program_no_reference).all() and a.axis_hit.eq(a.axis_top3).all()
    assert np.max(abs(a.base_axis_probability-a.axis_probability))<1e-12
    examples.to_parquet(c.OUT/'axis_examples.parquet',index=False,compression='zstd')
    runners.to_parquet(c.OUT/'conditional_runners.parquet',index=False,compression='zstd')
    c.save(c.OUT/'examples_audit.json',{'races':len(examples),'runners':len(runners),'evaluation_races':4799,
        'evaluation_failures':int(ev.failure.sum()),'all_axes_from_earlier_trained_models':True,
        'no_same_year_temperature_labels_used':True,'baseline_axis_and_probability_reproduced':True,
        'examples_sha256':c.sha(c.OUT/'axis_examples.parquet'),'runners_sha256':c.sha(c.OUT/'conditional_runners.parquet'),
        'source_models':sources})
    print('Examples ready',len(examples),len(runners),flush=True);c.storage()

if __name__=='__main__':main()
