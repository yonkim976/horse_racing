"""Fixed chronological train/refit/calibrate loops for three model families."""
import argparse,json,time
import numpy as np
import pandas as pd
import common as c
import joint
import lightgbm as lgb

def gbm(one,cols,year,folder,variant):
    train=one.year.between(2017,year-3);valid=one.year.eq(year-2)
    cal=one.year.eq(year-1);test=one.year.eq(year)
    x,vocab=c.base.encode(one,cols,mask=train);labels=one.outcome.between(1,3).astype(int)
    params=c.base.cfg()['training'].copy();params.pop('max_rounds');early=params.pop('early_stopping_rounds')
    params['seed']=20261004
    def data(mask):return lgb.Dataset(x.loc[mask],label=labels[mask],weight=1/one.loc[mask,'field_size'])
    history={}
    initial=lgb.train(params,data(train),num_boost_round=800,valid_sets=[data(valid)],
        callbacks=[lgb.early_stopping(early,verbose=False),lgb.record_evaluation(history)])
    model=lgb.train(params,data(train|valid),num_boost_round=initial.best_iteration)
    model_path=folder/'model.txt';model.save_model(str(model_path))
    cs=model.predict(x.loc[cal],raw_score=True,num_threads=4);ts=model.predict(x.loc[test],raw_score=True,num_threads=4)
    temp=c.base.set_temperature(one.loc[cal].reset_index(drop=True),cs)
    cf=one.loc[cal].reset_index(drop=True)
    scores=[cs[ix] for ix in cf.groupby('race_key',sort=False).indices.values()]
    outcomes=[cf.iloc[ix].outcome.to_numpy() for ix in cf.groupby('race_key',sort=False).indices.values()]
    order_temp=c.prob.fit_order_temperature(zip(scores,outcomes),bounds=(.35,4.))
    pd.concat([pd.DataFrame({'row_number':one.loc[cal,'row_number'],'score':cs,'phase':'calibration'}),
        pd.DataFrame({'row_number':one.loc[test,'row_number'],'score':ts,'phase':'evaluation'})],ignore_index=True).to_parquet(
            folder/'scores.parquet',index=False,compression='zstd')
    c.save(folder/'learning_curve.json',history)
    return {'trees':int(initial.best_iteration),'temperature':temp,'order_temperature':order_temp,
        'category_vocabulary':vocab,'model_path':str(model_path.relative_to(c.ROOT)),'model_sha256':c.sha(model_path),
        'gain':dict(zip(cols,model.feature_importance(importance_type='gain').tolist()))}

def neural(one,cols,year,folder):
    train=one.year.between(2017,year-3)
    x,encoding=joint.encode(one,cols,mask=train)
    data=joint.dataset(one,x);years=data[3]
    initial,best,curve=joint.fit(data,(years>=2017)&(years<=year-3),years==year-2,x.shape[1])
    del initial
    model,_,refit=joint.fit(data,(years>=2017)&(years<=year-2),None,x.shape[1],epochs=best,early=False)
    temp,cal=joint.calibrate(model,data,years==year-1)
    path=folder/'model.safetensors';joint.store(model,path)
    c.save(folder/'encoding.json',encoding);c.save(folder/'learning_curve.json',{'initial':curve,'refit':refit})
    return {'epochs':best,'temperature':temp,'inputs':x.shape[1],'parameters':sum(p.numel() for p in model.parameters()),
        'calibration':cal,'model_path':str(path.relative_to(c.ROOT)),'model_sha256':c.sha(path)}

def main(variant):
    c.check_inputs();f=c.frame();contracts=c.features()
    variants=list(contracts) if variant=='all' else [variant]
    for variant in variants:
        for meet in [1,3]:
            one=f[f.meet.eq(meet)].reset_index(drop=True)
            for year in [2024,2025,2026]:
                folder=c.OUT/'models'/f'{variant}_{meet}_{year}'
                if (folder/'metadata.json').exists():
                    meta=json.loads((folder/'metadata.json').read_text())
                    assert c.sha(c.ROOT/meta['model_path'])==meta['model_sha256']
                    print('Reuse',folder.name,flush=True);continue
                folder.mkdir(parents=True,exist_ok=True);start=time.time()
                print('Train',folder.name,flush=True)
                meta=neural(one,contracts[variant],year,folder) if variant=='state_joint' else gbm(one,contracts[variant],year,folder,variant)
                meta.update({'variant':variant,'venue':meet,'evaluation_year':year,'validation_year':year-2,
                    'calibration_year':year-1,'train_end_year':year-2,'features':contracts[variant],
                    'seed':joint.SEED if variant=='state_joint' else 20261004,'elapsed_s':time.time()-start,
                    'input_fingerprint':c.sha(c.OUT/'input_manifest.json'),
                    'state_fingerprint':c.sha(c.OUT/'state_features.parquet')})
                c.save(folder/'metadata.json',meta);c.storage_check()
                print('Ready',folder.name,'size',meta.get('trees',meta.get('epochs')),'seconds',round(meta['elapsed_s'],1),flush=True)
    folders=list((c.OUT/'models').glob('*/metadata.json'))
    if len(folders)==18:
        c.save(c.OUT/'training_complete.json',{'final_models':18,'initial_fits':18,'variants':list(contracts),
            'dependencies':{'torch':joint.torch.__version__,'lightgbm':lgb.__version__,'numpy':np.__version__},
            'device':'cpu','training_complete':True})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('variant',choices=['strong89','state_gbm','state_joint','all'])
    main(p.parse_args().variant)
