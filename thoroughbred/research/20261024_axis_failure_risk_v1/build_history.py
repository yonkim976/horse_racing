"""Generate genuinely out-of-training base axes for 2020 through 2023."""
import json,time
import failure_common as c
import numpy as np
import pandas as pd
import lightgbm as lgb

def main():
    c.check();f=c.old.frame();features=c.old.features()['state_gbm']
    for meet in [1,3]:
        one=f[f.meet.eq(meet)].reset_index(drop=True)
        for year in [2020,2021,2022,2023]:
            folder=c.base_folder(meet,year)
            if (folder/'metadata.json').exists():
                m=json.loads((folder/'metadata.json').read_text())
                assert m['input_fingerprint']==c.sha(c.OUT/'input_manifest.json') and m['model_sha256']==c.sha(folder/'model.txt')
                continue
            folder.mkdir(parents=True,exist_ok=True);start=time.time();print('History',meet,year,flush=True)
            train=one.year.between(2017,year-3);valid=one.year.eq(year-2);cal=one.year.eq(year-1);test=one.year.eq(year)
            x,vocab=c.old.base.encode(one,features,mask=train);y=one.outcome.between(1,3).astype(int)
            params=c.old.base.cfg()['training'].copy();params.pop('max_rounds');early=params.pop('early_stopping_rounds');params['seed']=20261004
            def dataset(mask):return lgb.Dataset(x.loc[mask],label=y[mask],weight=1/one.loc[mask,'field_size'])
            history={}
            initial=lgb.train(params,dataset(train),num_boost_round=800,valid_sets=[dataset(valid)],
                callbacks=[lgb.early_stopping(early,verbose=False),lgb.record_evaluation(history)])
            model=lgb.train(params,dataset(train|valid),num_boost_round=initial.best_iteration)
            model.save_model(str(folder/'model.txt'))
            cs=model.predict(x.loc[cal],raw_score=True,num_threads=4)
            temp=c.old.base.set_temperature(one.loc[cal].reset_index(drop=True),cs)
            ts=model.predict(x.loc[test],raw_score=True,num_threads=4)
            pd.concat([pd.DataFrame({'row_number':one.loc[cal,'row_number'],'score':cs,'phase':'calibration'}),
                pd.DataFrame({'row_number':one.loc[test,'row_number'],'score':ts,'phase':'evaluation'})],ignore_index=True).to_parquet(
                    folder/'scores.parquet',index=False,compression='zstd')
            c.save(folder/'learning_curve.json',history)
            c.save(folder/'metadata.json',{'meet':meet,'evaluation_year':year,'train_end_year':year-2,'calibration_year':year-1,
                'features':features,'category_vocabulary':vocab,'temperature':temp,'trees':int(initial.best_iteration),
                'train_end_date':str(one.loc[train|valid,'race_date'].max().date()),
                'calibration_end_date':str(one.loc[cal,'race_date'].max().date()),'evaluation_start_date':str(one.loc[test,'race_date'].min().date()),
                'model_sha256':c.sha(folder/'model.txt'),'input_fingerprint':c.sha(c.OUT/'input_manifest.json'),'elapsed_s':time.time()-start})
            c.storage();print('History ready',meet,year,'trees',initial.best_iteration,flush=True)
    c.save(c.OUT/'history_complete.json',{'final_models':8,'initial_fits':8,'existing_final_models_referenced':6})

if __name__=='__main__':main()
