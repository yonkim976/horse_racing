"""Six chronological last-three models; selection never reads evaluation labels."""
import json,time
import risk_common as c
import numpy as np
import pandas as pd
import lightgbm as lgb

def main():
    c.check(); f = c.frame(); features = c.old.features()['state_gbm']
    for meet in [1,3]:
        one = f[f.meet.eq(meet)].reset_index(drop=True)
        for year in [2024,2025,2026]:
            folder = c.OUT/'models'/f'bottom3_{meet}_{year}'
            if (folder/'metadata.json').exists():
                m = json.loads((folder/'metadata.json').read_text())
                assert c.sha(folder/'model.txt') == m['model_sha256']
                assert m['input_fingerprint'] == c.sha(c.OUT/'input_manifest.json')
                print('Reuse',folder.name,flush=True); continue
            folder.mkdir(parents=True,exist_ok=True); start=time.time()
            print('Train',folder.name,flush=True)
            train=one.year.between(2017,year-3);valid=one.year.eq(year-2)
            cal=one.year.eq(year-1);test=one.year.eq(year)
            labeled=one.normal & ~one.boundary_tie
            x,vocab=c.old.base.encode(one,features,mask=train)
            params=c.old.base.cfg()['training'].copy()
            params.pop('max_rounds');early=params.pop('early_stopping_rounds');params['seed']=20261004
            def data(mask):
                mask=mask & labeled
                return lgb.Dataset(x.loc[mask],label=one.loc[mask,'bottom_truth'],weight=1/one.loc[mask,'field_size'])
            history={}
            initial=lgb.train(params,data(train),num_boost_round=800,valid_sets=[data(valid)],
                callbacks=[lgb.early_stopping(early,verbose=False),lgb.record_evaluation(history)])
            model=lgb.train(params,data(train|valid),num_boost_round=initial.best_iteration)
            model.save_model(str(folder/'model.txt'))
            cs=model.predict(x.loc[cal],raw_score=True,num_threads=4)
            cf=one.loc[cal].reset_index(drop=True)
            basefolder=c.PREV/'outputs/models'/f'state_gbm_{meet}_{year}'
            bs=pd.read_parquet(basefolder/'scores.parquet')
            bs=bs[bs.phase.eq('calibration')].set_index('row_number').score
            assert set(bs.index)==set(cf.row_number)
            base=bs.loc[cf.row_number].to_numpy(float)
            hits=c.policy_hits(cf,base,cs);lam=c.LAMBDAS[int(np.argmax(hits))]
            meta={'meet':meet,'evaluation_year':year,'train_end_year':year-2,'validation_year':year-2,
                'calibration_year':year-1,'features':features,'category_vocabulary':vocab,'trees':int(initial.best_iteration),
                'seed':20261004,'model_sha256':c.sha(folder/'model.txt'),'input_fingerprint':c.sha(c.OUT/'input_manifest.json'),
                'bottom_temperature':c.temperature(cf,cs),'baseline_bottom_temperature':c.temperature(cf,-base),
                'policy_lambda':lam,'calibration_policy_hits':dict(zip(map(str,c.LAMBDAS),map(int,hits))),
                'calibration_races':int(cf.race_key.nunique()),'training_labeled_rows':int(((train|valid)&labeled).sum()),
                'train_last_date':str(one.loc[train|valid,'race_date'].max().date()),
                'calibration_first_date':str(cf.race_date.min().date()),'calibration_last_date':str(cf.race_date.max().date()),
                'gain':dict(zip(features,map(float,model.feature_importance(importance_type='gain')))),
                'evaluation_labels_used_for_selection':False}
            # Persist the prior-year decision before predicting or scoring the evaluation year.
            c.save(folder/'selection.json',meta)
            ts=model.predict(x.loc[test],raw_score=True,num_threads=4)
            pd.concat([pd.DataFrame({'row_number':cf.row_number,'score':cs,'phase':'calibration'}),
                pd.DataFrame({'row_number':one.loc[test,'row_number'],'score':ts,'phase':'evaluation'})],ignore_index=True).to_parquet(
                    folder/'scores.parquet',index=False,compression='zstd')
            c.save(folder/'learning_curve.json',history)
            meta['elapsed_s']=time.time()-start;c.save(folder/'metadata.json',meta)
            print('Ready',folder.name,'trees',meta['trees'],'lambda',lam,'seconds',round(meta['elapsed_s'],1),flush=True)
            c.storage()
    c.save(c.OUT/'training_complete.json',{'final_models':6,'initial_fits':6,'model_families':1,
        'lightgbm':lgb.__version__,'numpy':np.__version__,'torch':c.torch.__version__,'device':'cpu'})

if __name__=='__main__':main()
