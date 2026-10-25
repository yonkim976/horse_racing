"""Same baseline learner and split; only the declared training features differ."""
import json,time
import study_common as c
import numpy as np
import pandas as pd
import lightgbm as lgb

def fit(one,cols,year,folder):
    train=one.year.between(2017,year-3);valid=one.year.eq(year-2)
    cal=one.year.eq(year-1);test=one.year.eq(year)
    x,vocab=c.old.base.encode(one,cols,mask=train);labels=one.outcome.between(1,3).astype(int)
    params=c.old.base.cfg()['training'].copy();params.pop('max_rounds');early=params.pop('early_stopping_rounds');params['seed']=20261004
    def data(mask):return lgb.Dataset(x.loc[mask],label=labels[mask],weight=1/one.loc[mask,'field_size'])
    history={};initial=lgb.train(params,data(train),num_boost_round=800,valid_sets=[data(valid)],
        callbacks=[lgb.early_stopping(early,verbose=False),lgb.record_evaluation(history)])
    model=lgb.train(params,data(train|valid),num_boost_round=initial.best_iteration)
    model_path=folder/'model.txt';model.save_model(str(model_path))
    cs=model.predict(x.loc[cal],raw_score=True,num_threads=4);ts=model.predict(x.loc[test],raw_score=True,num_threads=4)
    cf=one.loc[cal].reset_index(drop=True);temperature=c.old.base.set_temperature(cf,cs)
    records=[(cs[ix],cf.iloc[ix].outcome.to_numpy()) for ix in cf.groupby('race_key',sort=False).indices.values()]
    order_temp=c.old.prob.fit_order_temperature(records,bounds=(.35,4.))
    pd.concat([pd.DataFrame({'row_number':one.loc[cal,'row_number'],'score':cs,'phase':'calibration'}),
        pd.DataFrame({'row_number':one.loc[test,'row_number'],'score':ts,'phase':'evaluation'})],ignore_index=True).to_parquet(
        folder/'scores.parquet',index=False,compression='zstd')
    c.save(folder/'learning_curve.json',history)
    return {'trees':int(initial.best_iteration),'temperature':temperature,'order_temperature':order_temp,'category_vocabulary':vocab,
        'model_path':str(model_path.relative_to(c.ROOT)),'model_sha256':c.sha(model_path),
        'gain':dict(zip(cols,model.feature_importance(importance_type='gain').tolist())),
        'initial_train_races':int(one.loc[train,'race_key'].nunique()),'validation_races':int(one.loc[valid,'race_key'].nunique()),
        'refit_races':int(one.loc[train|valid,'race_key'].nunique()),'calibration_races':int(cf.race_key.nunique()),
        'evaluation_races':int(one.loc[test,'race_key'].nunique())}

def main():
    c.check();assert json.loads((c.OUT/'preflight.json').read_text())['status']=='passed'
    for variant,(lag,extra) in c.VARIANTS.items():
        f=c.frame(lag);cols=c.old.features()['state_gbm']+extra
        for meet in [1,3]:
            one=f[f.meet.eq(meet)].reset_index(drop=True)
            for year in [2024,2025,2026]:
                folder=c.OUT/'models'/f'{variant}_{meet}_{year}'
                if (folder/'metadata.json').exists():
                    m=json.loads((folder/'metadata.json').read_text());assert c.sha(folder/'model.txt')==m['model_sha256'];continue
                folder.mkdir(parents=True,exist_ok=True);start=time.time();print('Train',folder.name,flush=True)
                m=fit(one,cols,year,folder)
                m.update({'variant':variant,'venue':meet,'evaluation_year':year,'validation_year':year-2,'train_end_year':year-2,
                    'calibration_year':year-1,'features':cols,'lag':lag,'seed':20261004,'elapsed_s':time.time()-start,
                    'input_manifest_sha256':c.sha(c.OUT/'input_manifest.json'),'feature_sha256':c.sha(c.OUT/f'feature_delta_t{lag}.parquet')})
                c.save(folder/'metadata.json',m);c.storage();print('Ready',folder.name,'trees',m['trees'],'seconds',round(m['elapsed_s'],1),flush=True)
    assert len(list((c.OUT/'models').glob('*/metadata.json')))==18
    c.save(c.OUT/'training_complete.json',{'status':'complete','initial_fits':18,'final_models':18,'variants':list(c.VARIANTS),
        'lightgbm':lgb.__version__,'torch':c.torch.__version__,'numpy':np.__version__})
if __name__=='__main__':main()
