"""Train risk corrections only on historically selected axes."""
import json,time
import failure_common as c
import numpy as np
import pandas as pd
import lightgbm as lgb

def main():
    c.check();f=pd.read_parquet(c.OUT/'axis_examples.parquet')
    rr=pd.read_parquet(c.OUT/'conditional_runners.parquet')
    groups={k:g.sort_values('program_no') for k,g in rr.groupby('race_key',sort=False)}
    for meet in [1,3]:
        one=f[f.meet.eq(meet)].reset_index(drop=True)
        for year in [2024,2025,2026]:
            folder=c.OUT/'risk_models'/f'axis_failure_{meet}_{year}'
            if (folder/'metadata.json').exists():
                m=json.loads((folder/'metadata.json').read_text())
                assert m['model_sha256']==c.sha(folder/'model.txt') and m['examples_sha256']==c.sha(c.OUT/'axis_examples.parquet')
                print('Reuse risk',meet,year,flush=True);continue
            folder.mkdir(parents=True,exist_ok=True);start=time.time();print('Risk',meet,year,flush=True)
            train=one.year.between(2020,year-3);valid=one.year.eq(year-2);cal=one.year.eq(year-1);test=one.year.eq(year)
            x=one[c.FEATURES];offset=one.base_failure_logit.to_numpy(float)
            params={'objective':'binary','metric':'binary_logloss','learning_rate':.03,'num_leaves':7,
                'min_data_in_leaf':75,'lambda_l2':10.,'num_threads':4,'deterministic':True,
                'force_col_wise':True,'verbosity':-1,'seed':20261024,'boost_from_average':False}
            def dataset(mask):return lgb.Dataset(x.loc[mask],label=one.loc[mask,'failure'],init_score=offset[mask])
            curve={}
            initial=lgb.train(params,dataset(train),num_boost_round=400,valid_sets=[dataset(valid)],
                callbacks=[lgb.early_stopping(30,verbose=False),lgb.record_evaluation(curve)])
            model=lgb.train(params,dataset(train|valid),num_boost_round=initial.best_iteration)
            model.save_model(str(folder/'model.txt'))
            cal_raw=offset[cal]+model.predict(x.loc[cal],raw_score=True,num_threads=4)
            cf=one.loc[cal].reset_index(drop=True);y=cf.failure.to_numpy(int)
            base_cal=c.fit_calibration(offset[cal],y);risk_cal=c.fit_calibration(cal_raw,y)
            risk=c.calibrated(cal_raw,risk_cal);control=c.calibrated(offset[cal],base_cal)
            hits=[]
            for lam in c.LAMBDAS:
                hits.append(sum(c.pick(groups[key],p,lam)[1] for key,p in zip(cf.race_key,risk)))
            selected=c.LAMBDAS[int(np.argmax(hits))]
            meta={'meet':meet,'evaluation_year':year,'train_start_year':2020,'train_end_year':year-2,
                'early_stopping_year':year-2,'calibration_year':year-1,'features':c.FEATURES,
                'trees':int(initial.best_iteration),'initial_score':'logit(1 - base axis top3 probability)',
                'risk_calibration':risk_cal,'base_calibration':base_cal,'policy_lambda':selected,
                'calibration_policy_hits':dict(zip(map(str,c.LAMBDAS),map(int,hits))),
                'warning_thresholds':{'base_risk':float(np.quantile(cf.base_risk,.8)),
                    'control_risk':float(np.quantile(control,.8)),'model_risk':float(np.quantile(risk,.8))},
                'training_races':int((train|valid).sum()),'calibration_races':int(cal.sum()),
                'train_last_date':str(one.loc[train|valid,'race_date'].max().date()),
                'calibration_first_date':str(cf.race_date.min().date()),'calibration_last_date':str(cf.race_date.max().date()),
                'examples_sha256':c.sha(c.OUT/'axis_examples.parquet'),'model_sha256':c.sha(folder/'model.txt'),
                'evaluation_outcomes_used_for_selection':False,
                'gain':dict(zip(c.FEATURES,map(float,model.feature_importance(importance_type='gain'))))}
            c.save(folder/'selection.json',meta)
            raw=offset[cal|test]+model.predict(x.loc[cal|test],raw_score=True,num_threads=4)
            pred=one.loc[cal|test,['race_key','race_date','year','meet','base_risk','base_failure_logit']].copy()
            pred['model_raw_score']=raw;pred['control_risk']=c.calibrated(pred.base_failure_logit,base_cal)
            pred['model_risk']=c.calibrated(raw,risk_cal)
            pred['phase']=np.where(pred.year.eq(year),'evaluation','calibration')
            pred.to_parquet(folder/'predictions.parquet',index=False,compression='zstd')
            c.save(folder/'learning_curve.json',curve);meta['elapsed_s']=time.time()-start
            c.save(folder/'metadata.json',meta);c.storage()
            print('Risk ready',meet,year,'trees',meta['trees'],'lambda',selected,flush=True)
    c.save(c.OUT/'training_complete.json',{'history_final_models':8,'history_initial_fits':8,'risk_final_models':6,'risk_initial_fits':6,
        'original_base_models_referenced':6,'torch':c.torch.__version__,'lightgbm':lgb.__version__,'numpy':np.__version__})

if __name__=='__main__':main()
