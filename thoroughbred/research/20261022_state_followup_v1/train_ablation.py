"""Identical training schedule and budget, changing only the feature blocks."""
import time,json
import numpy as np
import pandas as pd
import support as s
import lightgbm as lgb

def fit(one,cols,year,folder):
    train=one.year.between(2017,year-3);valid=one.year.eq(year-2)
    cal=one.year.eq(year-1);test=one.year.eq(year)
    x,vocab=s.base.encode(one,cols,mask=train);labels=one.outcome.between(1,3).astype(int)
    params=s.base.cfg()['training'].copy();params.pop('max_rounds');early=params.pop('early_stopping_rounds');params['seed']=20261004
    def data(mask):return lgb.Dataset(x.loc[mask],label=labels[mask],weight=1/one.loc[mask,'field_size'])
    history={}
    initial=lgb.train(params,data(train),num_boost_round=800,valid_sets=[data(valid)],
        callbacks=[lgb.early_stopping(early,verbose=False),lgb.record_evaluation(history)])
    model=lgb.train(params,data(train|valid),num_boost_round=initial.best_iteration)
    model_path=folder/'model.txt';model.save_model(str(model_path))
    cs=model.predict(x.loc[cal],raw_score=True,num_threads=4);ts=model.predict(x.loc[test],raw_score=True,num_threads=4)
    cf=one.loc[cal].reset_index(drop=True);temp=s.base.set_temperature(cf,cs)
    groups=cf.groupby('race_key',sort=False).indices.values()
    order_temp=s.prob.fit_order_temperature([(cs[ix],cf.iloc[ix].outcome.to_numpy()) for ix in groups],bounds=(.35,4.))
    pd.concat([pd.DataFrame({'row_number':one.loc[cal,'row_number'],'score':cs,'phase':'calibration'}),
        pd.DataFrame({'row_number':one.loc[test,'row_number'],'score':ts,'phase':'evaluation'})],ignore_index=True).to_parquet(
            folder/'scores.parquet',index=False,compression='zstd')
    s.save(folder/'learning_curve.json',history)
    return {'trees':int(initial.best_iteration),'temperature':temp,'order_temperature':order_temp,
        'category_vocabulary':vocab,'model_path':str(model_path.relative_to(s.ROOT)),'model_sha256':s.sha(model_path),
        'gain':dict(zip(cols,model.feature_importance(importance_type='gain').tolist()))}

def main():
    s.check();f=s.frame()
    for variant,cols in s.contracts().items():
        for meet in [1,3]:
            one=f[f.meet.eq(meet)].reset_index(drop=True)
            for year in [2024,2025,2026]:
                folder=s.OUT/'models'/f'{variant}_{meet}_{year}'
                if (folder/'metadata.json').exists():
                    meta=json.loads((folder/'metadata.json').read_text())
                    assert meta['input_fingerprint']==s.sha(s.OUT/'input_manifest.json')
                    assert s.sha(s.ROOT/meta['model_path'])==meta['model_sha256'];continue
                folder.mkdir(parents=True,exist_ok=True);start=time.time();print('Training',folder.name,flush=True)
                meta=fit(one,cols,year,folder)
                meta.update({'variant':variant,'venue':meet,'evaluation_year':year,'validation_year':year-2,
                    'calibration_year':year-1,'train_end_year':year-2,'features':cols,'seed':20261004,
                    'elapsed_s':time.time()-start,'input_fingerprint':s.sha(s.OUT/'input_manifest.json'),
                    'simple_fingerprint':s.sha(s.OUT/'simple_features.parquet')})
                s.save(folder/'metadata.json',meta);s.storage();print('Ready',folder.name,meta['trees'],flush=True)
    s.save(s.OUT/'training_complete.json',{'final_models':18,'initial_fits':18,'variants':list(s.contracts())})

if __name__=='__main__':main()
