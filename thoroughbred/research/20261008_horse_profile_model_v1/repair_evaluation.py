"""One-time deterministic tie repair; never retrains or alters model weights."""
import importlib.util
import json
from pathlib import Path
import lightgbm as lgb
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('profile_model_repair',HERE/'run.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)

def main():
    audit=json.loads((R.OUT/'audit.json').read_text())
    if audit.get('numeric_tie_repair'):raise RuntimeError('Already repaired')
    changed=[]
    for name,value in audit['inputs'].items():
        actual=R.sha(R.ROOT/name)
        if actual!=value:
            assert (R.ROOT/name) in [HERE/'run.py',HERE/'PLAN.md']
            changed.append(dict(path=name,original_sha256=value,repaired_sha256=actual))
            audit['inputs'][name]=actual
    model_hashes={str(p.relative_to(R.OUT)):R.sha(p) for p in (R.OUT/'models').rglob('top3.txt')}
    c=R.cfg();f=pd.read_parquet(R.OUT/'features.parquet')
    outputs=[];predictions=[];tickets=[]
    for meet in c['venues']:
        one=f[f.meet.eq(meet)].reset_index(drop=True)
        for year in c['evaluation_years']:
            for variant,cols in R.CONTRACTS.items():
                directory=R.OUT/'models'/f'{meet}_{year}_{variant}'
                meta=json.loads((directory/'metadata.json').read_text());x=one[cols].copy()
                for column,vocabulary in meta['category_vocabulary'].items():x[column]=pd.Categorical(x[column],categories=vocabulary)
                model=lgb.Booster(model_file=str(directory/'top3.txt'))
                cal=one.year.eq(year-1);test=one.year.eq(year)
                cal_score=model.predict(x[cal],raw_score=True,num_threads=4)
                temperature=R.fit_temperature(R.parts(one[cal].reset_index(drop=True),cal_score),c)
                score=model.predict(x[test],raw_score=True,num_threads=4)
                a,b,d=R.evaluate(one[test].reset_index(drop=True),score,temperature,variant)
                outputs.append(a);predictions.append(b);tickets.append(d)
                meta['temperature_before_tie_repair']=meta['temperature'];meta['temperature']=temperature
                meta['deterministic_ties']='sorted triple scores; individual raw score; program order'
                R.save(directory/'metadata.json',meta)
                print('Re-evaluated',meet,year,variant,'hits',int(a.trio6_hit.sum()),flush=True)
    # Preserve the previous reference exactly, with its inherited tie policy.
    old_races=pd.read_csv(R.OUT/'race_metrics.csv',low_memory=False)
    old_predictions=pd.read_parquet(R.OUT/'runner_predictions.parquet')
    race=pd.concat(outputs+[old_races[old_races.variant.eq('reference258')]],ignore_index=True)
    runner=pd.concat(predictions+[old_predictions[old_predictions.variant.eq('reference258')]],ignore_index=True)
    ticket=pd.concat(tickets,ignore_index=True)
    race.to_csv(R.OUT/'race_metrics.csv',index=False);runner.to_parquet(R.OUT/'runner_predictions.parquet',index=False)
    ticket.to_parquet(R.OUT/'recommendations.parquet',index=False)
    R.summarize(race,c)
    for name,value in model_hashes.items():assert R.sha(R.OUT/name)==value
    audit['numeric_tie_repair']=dict(reason='Independent marginal sum and triple addition order changed mathematically tied ranks by ULPs',
                                    changed_source_hashes=changed,model_hashes_unchanged=True,models_retrained=0)
    R.save(R.OUT/'audit.json',audit)
    summary=json.loads((R.OUT/'summary.json').read_text());summary['numeric_tie_repair']=True
    R.save(R.OUT/'summary.json',summary)
    R.check_inputs()
    print('Tie repair completed; 18 model hashes unchanged',flush=True)

if __name__=='__main__':main()
