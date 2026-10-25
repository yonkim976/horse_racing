"""Fixed chronological research ablation; never edits promoted model registry."""

import json

import lightgbm as lgb
import numpy as np
import pandas as pd

import prepare as p

PARAMS=dict(n_estimators=120,learning_rate=.04,num_leaves=15,min_child_samples=80,
            max_bin=63,reg_lambda=2,n_jobs=4,random_state=p.SEED,deterministic=True,
            force_col_wise=True,verbosity=-1)
COMPARISONS=[('B1','B0'),('B2','B0'),('B3','B0'),('B2','B1'),('B3','B2')]


def boot(d,new,old,rng):
    dates=d.groupby('date').agg(total=(new,'sum'),other=(old,'sum'),n=('race_no','size'))
    a=dates.total.to_numpy()-dates.other.to_numpy();n=dates.n.to_numpy()
    ix=rng.integers(0,len(dates),size=(2000,len(dates)))
    v=a[ix].sum(axis=1)/n[ix].sum(axis=1)
    return float(np.quantile(v,.025)),float(np.quantile(v,.975))


def summarize(rows):
    race=['date','race_no'];race_rows=[]
    for model in ['B0','B1','B2','B3']:
        error=(rows['pred_'+model]-rows.target).abs().groupby([rows.date,rows.race_no]).mean()
        selected=rows.sort_values(race+['pred_'+model,'program_no'],ascending=[True,True,False,True]).groupby(race).head(1).set_index(race)
        a=error.rename(model+'_mae').to_frame()
        a[model+'_top3']=selected.finish_rank.le(3).astype(int)
        a[model+'_win']=selected.finish_rank.eq(1).astype(int)
        race_rows.append(a)
    rr=pd.concat(race_rows,axis=1).reset_index()
    meta=rows.groupby(race).agg(year=('year','first'),distance=('distance','first'),normal_n=('horse_id','size'),
        sufficient_same_history=('same_slots','min')).reset_index()
    return rr.merge(meta,on=race,validate='one_to_one')


def main():
    contract=dict(params=PARAMS,years=[2024,2025,2026],train_labels_start=2017,
        target='(normal finisher median finish - own finish)*1000/distance',
        minimum_normal_finishers=6,metrics='race equal MAE;normal-finisher conditional selection rates',
        no_test_tuning=True,comparisons=COMPARISONS,bootstrap=2000,seed=p.SEED,
        baseline_is_research_not_production=True)
    path=p.OUT/'evaluation_contract.json'
    if path.exists():assert json.loads(path.read_text())==json.loads(json.dumps(contract))
    else:p.save('evaluation_contract.json',contract)
    d=pd.read_parquet(p.OUT/'profiles.parquet')
    x=pd.read_parquet(p.OUT/'features.parquet')
    sets=json.loads((p.OUT/'feature_sets.json').read_text())
    assert len(x)==len(d)
    predictions=[];models=[];new_fits=0
    for year in [2024,2025,2026]:
        train=d.year.between(2017,year-1)&d.normal_n.ge(6)
        test=d.year.eq(year)&d.normal_n.ge(6)
        assert d.loc[train,'date'].max()<d.loc[test,'date'].min()
        out=d.loc[test,['row_id','date','race_no','horse_id','program_no','distance','finish_rank','year','performance']].copy()
        out=out.rename(columns={'performance':'target'})
        out['same_slots']=x.loc[test,'same_slots'].to_numpy()
        for name,cols in sets.items():
            model_path=p.OUT/'models'/f'{name}_{year}.txt'
            if model_path.exists():
                model=lgb.Booster(model_file=str(model_path))
                assert model.feature_name()==cols
                print('Reused fixed model',name,year,flush=True)
            else:
                estimator=lgb.LGBMRegressor(**PARAMS)
                estimator.fit(x.loc[train,cols],d.loc[train,'performance'],sample_weight=1/d.loc[train,'normal_n'])
                model=estimator.booster_;model.save_model(str(model_path));new_fits+=1
                print('Fitted',name,year,'train',int(train.sum()),'test',int(test.sum()),flush=True)
            raw=model.predict(x.loc[test,cols],num_threads=4)
            centered=raw-pd.Series(raw,index=out.index).groupby([out.date,out.race_no]).transform('median').to_numpy()
            out['raw_'+name]=raw;out['pred_'+name]=centered
            models.append(dict(model=name,year=year,path=str(model_path.relative_to(p.ROOT)),
                sha256=p.sha(model_path),train_rows=int(train.sum()),test_rows=int(test.sum()),
                train_first=d.loc[train,'date'].min(),train_last=d.loc[train,'date'].max(),features=cols,
                feature_count=len(cols),trees=model.current_iteration()))
        predictions.append(out)
    pred=pd.concat(predictions).sort_values(['date','race_no','program_no']).reset_index(drop=True)
    pred.to_parquet(p.OUT/'predictions.parquet',index=False)
    rr=summarize(pred);rr.to_csv(p.OUT/'race_metrics.csv',index=False)
    metrics=[];intervals=[];rng=np.random.default_rng(p.SEED)
    scopes=[('all',rr)]+[(str(y),rr[rr.year.eq(y)]) for y in [2024,2025,2026]]
    for scope,g in scopes:
        for name in sets:
            metrics.append(dict(scope=scope,model=name,races=len(g),runner_rows=int(g.normal_n.sum()),
                mae=float(g[name+'_mae'].mean()),top3_hits=int(g[name+'_top3'].sum()),
                top3_rate=float(g[name+'_top3'].mean()),win_hits=int(g[name+'_win'].sum()),win_rate=float(g[name+'_win'].mean())))
        for new,old in COMPARISONS:
            for metric in ['mae','top3','win']:
                lo,hi=boot(g,new+'_'+metric,old+'_'+metric,rng)
                intervals.append(dict(scope=scope,new=new,old=old,metric=metric,
                    difference=float((g[new+'_'+metric]-g[old+'_'+metric]).mean()),low=lo,high=hi,dates=int(g.date.nunique())))
    pd.DataFrame(metrics).to_csv(p.OUT/'evaluation_metrics.csv',index=False)
    pd.DataFrame(intervals).to_csv(p.OUT/'paired_intervals.csv',index=False)
    distance=[]
    for (year,dist),g in rr.groupby(['year','distance']):
        for name in sets:
            distance.append(dict(year=int(year),distance=int(dist),model=name,races=len(g),
                mae=float(g[name+'_mae'].mean()),top3_rate=float(g[name+'_top3'].mean()),win_rate=float(g[name+'_win'].mean())))
    pd.DataFrame(distance).to_csv(p.OUT/'distance_year_metrics.csv',index=False)
    p.save('model_manifest.json',models)
    p.save('evaluation_summary.json',dict(models=len(models),new_fits_this_run=new_fits,
        rows=len(pred),races=len(rr),source_end='2026-09-18',years=[2024,2025,2026],
        target_is_performance_not_pure_ability=True,conditional_on_normal_finishers=True,
        operational_model_comparison=False,operating_model_changed=False,test_tuning=False))
    print(pd.DataFrame(metrics).to_string(index=False))
    print(pd.DataFrame(intervals).query("scope=='all' and metric=='mae'").to_string(index=False))


if __name__=='__main__':main()
