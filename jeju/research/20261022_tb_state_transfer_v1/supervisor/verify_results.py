"""Independent saved-model, calibration, full event and bootstrap verification.

No estimator fit and no experiment module import. Reuses only sealed supervisor
math, whose PL enumeration uses explicit remaining choice sets.
"""
import hashlib
import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
STUDY=HERE.parent
OUT=STUDY/'experiment/outputs'
STYLE=ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs'
OLD=ROOT/'jeju/research/20261022_dynamic_ability_pace_v1'
MATH=OLD/'supervisor/math_reference.py'
spec=importlib.util.spec_from_file_location('_sealed_independent_math',MATH)
ref=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)
ERRORS=defaultdict(float)
EDGES=np.array([0,.00001,.00005,.0001,.00025,.0005,.001,.0025,.005,.01,.025,.05,.1,.25,.5,.75,1.])


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def near(name,left,right,tol=1e-10):
    a,b=np.asarray(left,float),np.asarray(right,float)
    assert a.shape==b.shape and np.isfinite(a).all() and np.isfinite(b).all(),name
    error=float(np.max(np.abs(a-b))) if a.size else 0.
    ERRORS[name]=max(ERRORS[name],error)
    assert error<=tol,(name,error,tol)


def calibration(frame,raw,t):
    frame=frame.copy();frame['_raw']=np.asarray(raw)
    checks=[]
    for _,g in frame.groupby('race_id',sort=False):
        actual=np.argsort(g.finish_position.to_numpy())[:3]
        checks.append(ref.inverse_temperature_derivatives(g._raw.to_numpy(),actual,t))
    return np.mean(checks,axis=0)


def optimum(t,gradient):
    assert .35<=t<=4
    if t==.35:assert gradient<=2e-5
    elif t==4:assert gradient>=-2e-5
    else:assert abs(gradient)<2e-5,(t,gradient)


def top_keys(probs,k):
    remaining=probs.copy();keys=[]
    for _ in range(k):
        key,_=ref.stable_selection(remaining)
        keys.append(key);del remaining[key]
    return keys


def main():
    par=json.loads((OUT/'parameters.json').read_text())
    report=json.loads((OUT/'report.json').read_text())
    receipt=json.loads((OUT/'fit_run_receipt.json').read_text())
    assert receipt['status']=='COMPLETED_RESEARCH_ONLY'
    assert receipt['fit_counts']=={'final_models':6,'LightGBM_train_calls':12,
                                  'C_S_PL_temperature_optimizations':6,'R_temperature_optimizations':0}
    for item in receipt['artifacts']:
        path=ROOT/item['path']
        assert path.is_relative_to(STUDY) and sha(path)==item['sha256']
        assert path.stat().st_size==item['bytes']
    data=pd.read_parquet(STYLE/'features.parquet')
    state=pd.read_parquet(STUDY/'inputs/state_features.parquet')
    state_cols=par['features']['S'][30:]
    assert len(state_cols)==10 and len(par['features']['C'])==30
    data=data.merge(state[['api_record_id',*state_cols]],on='api_record_id',validate='one_to_one')
    data['race_date']=pd.to_datetime(data.race_date).dt.strftime('%Y-%m-%d')
    oos=pd.read_parquet(OUT/'candidate_oos_scores.parquet')
    assert not oos.duplicated(['arm','year','role','api_record_id']).any()
    fits={(f['arm'],int(f['year'])):f for f in par['models']}
    assert set(fits)==set(itertools.product(('C','S'),(2024,2025,2026)))
    temperatures={};model_replays=cal_checks=0;calibration_checks=[]
    for (arm,year),meta in fits.items():
        columns=par['features'][arm]
        assert meta['feature_names']==columns and meta['max_rounds']==800 and meta['early_stopping_rounds']==25
        initial=data.loc[data.year.between(2017,year-3)]
        valid=data.loc[data.year.eq(year-2)]
        cal=data.loc[data.year.eq(year-1)]
        evaluation=data.loc[data.year.eq(year)]
        assert meta['initial_train_rows']==len(initial) and meta['refit_rows']==len(initial)+len(valid)
        assert meta['calibration_rows']==len(cal) and meta['evaluation_rows']==len(evaluation)
        vocab={c:sorted(initial[c].dropna().astype(str).unique().tolist())
               for c in par['features']['categorical_columns']}
        assert vocab==meta['categorical_vocabulary']
        assert meta['parameters']==par['lightgbm_parameters']
        path=STUDY/f'experiment/models/{arm}_{year}.txt'
        assert sha(path)==meta['model_sha256']
        model=lgb.Booster(model_file=str(path))
        assert model.feature_name()==columns and model.current_iteration()==meta['best_iteration']
        cal_raw=None
        for role,target in [('calibration',cal),('evaluation',evaluation)]:
            saved=oos.loc[oos.arm.eq(arm)&oos.year.eq(year)&oos.role.eq(role)].set_index('api_record_id')
            assert len(saved)==len(target) and set(saved.index)==set(target.api_record_id)
            saved=saved.loc[target.api_record_id]
            x=target[columns].copy()
            for c,categories in vocab.items():x[c]=pd.Categorical(x[c].astype('string'),categories=categories)
            raw=model.predict(x,raw_score=True,num_threads=2)
            near('model_raw_replay',raw,saved.score)
            assert np.array_equal(saved.race_id,target.race_id)
            assert np.array_equal(saved.race_date,target.race_date)
            model_replays+=len(raw)
            if role=='calibration':cal_raw=raw
        t=meta['temperature_fit']['temperature'];temperatures[(arm,year)]=t
        loss,gradient,hessian=calibration(cal,cal_raw,t)
        near('C_S_calibration_nll',loss,meta['temperature_fit']['objective_nll'])
        optimum(t,gradient);assert hessian>0
        calibration_checks.append({'arm':arm,'year':year,'temperature':t,'gradient_inverse_T':float(gradient)})
        cal_checks+=1
    r_old=json.loads((OLD/'experiment/outputs/parameters.json').read_text())['R_reference_fits']
    for year in (2024,2025,2026):
        raw=pd.read_parquet(STYLE/f'F1_STYLE6_{year}/calibration_scores.parquet')
        frame=data.merge(raw,on='api_record_id',validate='one_to_one')
        assert frame.year.eq(year-1).all()
        t=par['R_temperatures_reused'][str(year)]['temperature']
        assert t==r_old[str(year)]['temperature']
        temperatures[('R',year)]=t
        loss,gradient,hessian=calibration(frame,frame.score,t)
        near('R_calibration_nll',loss,r_old[str(year)]['objective_nll'])
        optimum(t,gradient);assert hessian>0
        calibration_checks.append({'arm':'R','year':year,'temperature':t,'gradient_inverse_T':float(gradient)})
        cal_checks+=1
    print(json.dumps({'phase':'model_and_temperature_checks_passed','raw_predictions':model_replays,'calibrations':cal_checks}),flush=True)
    metrics=pd.read_parquet(OUT/'race_pool_metrics.parquet').set_index(['race_id','arm','pool'])
    selections=pd.read_parquet(OUT/'selected_ticket_ledger.parquet').set_index(['race_id','arm','pool'])
    marginals=pd.read_parquet(OUT/'evaluation_runner_marginals.parquet').set_index(['race_id','arm','horse_number'])
    axis=pd.read_parquet(OUT/'win_axis_ledger.parquet').set_index(['race_id','arm'])
    pairs=pd.read_parquet(OUT/'pair_selection_diagnostics.parquet').set_index(['race_id','arm','pool','k'])
    assert len(metrics)==len(selections)==37251 and len(marginals)==52236 and len(axis)==5337
    assert len(pairs)==21348 and pairs.index.is_unique
    r_raw=pd.concat([pd.read_parquet(STYLE/f'F1_STYLE6_{y}/evaluation_scores.parquet') for y in (2024,2025,2026)]).set_index('api_record_id')
    candidate=oos.loc[oos.role.eq('evaluation')].set_index(['arm','api_record_id'])
    bins=defaultdict(lambda:np.zeros((16,4)));recomputed=[];triples=0;pair_checks=0
    for rid,g in data.loc[data.year.ge(2024)].groupby('race_id',sort=True):
        g=g.sort_values('horse_number');numbers=g.horse_number.to_numpy(int);n=len(g)
        actual=tuple(np.argsort(g.finish_position.to_numpy())[:3]);year=int(g.year.iloc[0]);plc=3 if n>=8 else None
        for arm in ('R','C','S'):
            raw=(r_raw.loc[g.api_record_id,'score'].to_numpy() if arm=='R' else
                 candidate.xs(arm).loc[g.api_record_id,'score'].to_numpy())
            joint=ref.distribution(raw,temperatures[(arm,year)]);triples+=len(joint)
            pools,rank=ref.aggregate(joint,n,plc)
            for pool,probs in pools.items():
                if pool=='PLC' and plc is None:continue
                metric,keys,p,y=ref.score_events(pool,probs,actual,plc)
                saved=metrics.loc[(rid,arm,pool)]
                near('seven_pool_logloss',metric['log_loss'],saved.race_nll)
                near('seven_pool_brier',metric['brier'],saved.race_brier)
                assert saved.ticket_count==len(keys) and saved.event_count==y.sum()
                key,prob=ref.stable_selection(probs);selected=selections.loc[(rid,arm,pool)]
                assert json.loads(selected.selected_ticket_key)==[int(numbers[i]) for i in key]
                assert bool(selected.selected_hit)==(key in ref.winners(pool,actual,plc))
                near('selected_probability',prob,selected.selected_probability)
                indices=np.minimum(np.searchsorted(EDGES,p,side='right')-1,15)
                accum=np.column_stack([np.bincount(indices,minlength=16),
                                       np.bincount(indices,weights=p,minlength=16),
                                       np.bincount(indices,weights=y,minlength=16),
                                       np.bincount(indices,weights=(p-y)**2,minlength=16)])
                for period in ('ALL',str(year)):bins[(pool,arm,period)]+=accum
                recomputed.append({'race_id':rid,'race_date':g.race_date.iloc[0],'year':year,
                                   'distance_m':int(g.distance_m.iloc[0]),'arm':arm,'pool':pool,
                                   'nll':metric['log_loss'],'brier':metric['brier']})
            for i,number in enumerate(numbers):
                m=marginals.loc[(rid,arm,int(number))]
                near('all_marginals',[rank[i,0],rank[i,1],rank[i,2],rank[i,:2].sum(),rank[i].sum()],
                     m[['p_win','p_exact2','p_exact3','p_top2','p_top3']].to_numpy(float))
            key,prob=ref.stable_selection(pools['WIN']);ax=axis.loc[(rid,arm)]
            assert ax.selected_horse_number==numbers[key[0]] and bool(ax.selected_hit_top3)==(key[0] in actual)
            near('axis_probability',prob,ax.selected_probability)
            for pool in ('QNL','QPL'):
                truth=ref.winners(pool,actual,plc)
                chosen3=top_keys(pools[pool],3)
                for k in (1,3):
                    chosen=chosen3[:k];chosen_set=set(chosen);mass=np.zeros(4)
                    for order,q in joint.items():
                        realized=({tuple(sorted(order[:2]))} if pool=='QNL' else
                                  set(itertools.combinations(sorted(order),2)))
                        mass[len(chosen_set&realized)]+=q
                    saved=pairs.loc[(rid,arm,pool,k)]
                    expected_keys=[[int(numbers[i]) for i in key] for key in chosen]
                    assert json.loads(saved.selected_tickets_json)==expected_keys
                    near('pair_selected_probs',[pools[pool][key] for key in chosen],json.loads(saved.selected_probabilities_json))
                    near('pair_count_distribution',mass,saved[[f'count_probability_{i}' for i in range(4)]].to_numpy(float))
                    near('pair_union',sum(mass[1:]),saved.selected_union_probability)
                    near('pair_expected_hits',np.arange(4)@mass,saved.expected_hits)
                    assert int(saved.realized_hit_count)==len(chosen_set&truth)
                    pair_checks+=1
    reliability=pd.read_parquet(OUT/'reliability_bins.parquet')
    for row in reliability.itertuples(index=False):
        count,sp,sy,sb=bins[(row.pool,row.arm,str(row.evaluation_period))][row.bin_index]
        assert row.ticket_events==count
        if count:near('reliability_bins',[sp/count,sy/count,sb/count],
                      [row.mean_probability,row.observed_event_rate,row.mean_ticket_brier])
        else:assert pd.isna(row.mean_probability) and pd.isna(row.observed_event_rate) and pd.isna(row.mean_ticket_brier)
    checked=pd.DataFrame(recomputed)
    schedule=np.load(ROOT/'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy',allow_pickle=False)
    dates=sorted(checked.race_date.unique());assert len(dates)==269 and schedule.shape==(2000,269)
    def boot(delta):
        daily=delta.groupby(level='race_date').agg(['sum','count']).loc[dates]
        return daily['sum'].to_numpy()[schedule].sum(axis=1)/daily['count'].to_numpy()[schedule].sum(axis=1)
    def paired(source,field,left,right):
        matrix=source.pivot(index=['race_id','race_date'],columns='arm',values=field).astype(float)
        delta=matrix[left]-matrix[right]
        return matrix,delta,boot(delta)
    saved_draws=pd.read_parquet(OUT/'comparison_bootstrap_draws.parquet')
    reported={row['comparison']:row for row in report['comparisons']}
    axis_results=[];pair_results=[];gates={}
    for left,right in [('C','R'),('S','C'),('S','R')]:
        name=f'{left}_minus_{right}'
        tri=checked.loc[checked.pool.eq('TRI')]
        _,delta,draws=paired(tri,'nll',left,right)
        near('bootstrap_draws',draws,saved_draws.loc[saved_draws.comparison.eq(name)].sort_values('draw').tri_nll_difference)
        near('bootstrap_CI',np.quantile(draws,[.025,.975]),reported[name]['tri_delta_nll_ci95'])
        _,db,_=paired(tri,'brier',left,right)
        win=checked.loc[checked.pool.eq('WIN')]
        _,wn,_=paired(win,'nll',left,right);_,wb,_=paired(win,'brier',left,right)
        gate=bool(np.quantile(draws,.975)<0 and db.mean()<=0 and wn.mean()<=0 and wb.mean()<=0)
        assert gate==reported[name]['comparison_gate_pass'];gates[name]=gate
        matrix,delta,draws=paired(axis.reset_index(),'selected_hit_top3',left,right)
        lc=matrix[left].groupby(level='race_date').sum().loc[dates].to_numpy()[schedule].sum(axis=1)
        rc=matrix[right].groupby(level='race_date').sum().loc[dates].to_numpy()[schedule].sum(axis=1)
        axis_results.append({'comparison':name,'left_hits':int(matrix[left].sum()),'right_hits':int(matrix[right].sum()),
                             'difference':float(delta.mean()),'ci95':np.quantile(draws,[.025,.975]).tolist(),
                             'relative_change':float(matrix[left].sum()/matrix[right].sum()-1),
                             'relative_ci95':np.quantile(lc/rc-1,[.025,.975]).tolist()})
        a_report=next(row for row in report['win_axis_bootstrap'] if row['comparison']==name)
        near('axis_bootstrap_CI',np.quantile(draws,[.025,.975]),a_report['hit_rate_difference_ci95'])
        for pool,k in itertools.product(('QNL','QPL'),(1,3)):
            subset=pairs.reset_index().loc[lambda f:f.pool.eq(pool)&f.k.eq(k)].copy()
            subset['hit_any']=subset.realized_hit_count.gt(0)
            for metric in ('hit_any','realized_hit_count','expected_hits','selected_union_probability'):
                matrix,delta,draws=paired(subset,metric,left,right)
                pair_results.append({'comparison':name,'pool':pool,'k':k,'metric':metric,'races':len(delta),
                                     'left_mean':float(matrix[left].mean()),'right_mean':float(matrix[right].mean()),
                                     'delta':float(delta.mean()),'ci95':np.quantile(draws,[.025,.975]).tolist(),
                                     'gains':int((delta>0).sum()),'losses':int((delta<0).sum()),
                                     'bootstrap_draws':2000,'descriptive_only':True})
    assert report['overall_research_candidate_gate_pass']==(gates['S_minus_C'] and gates['S_minus_R'])
    assert int(axis.xs('R',level='arm').selected_hit_top3.sum())==1023
    # Aggregate proper-loss summaries are checked separately from reconstruction.
    for filename,groupby in [('pool_summary.parquet',['pool','arm']),('pool_year_summary.parquet',['pool','arm','year'])]:
        saved=pd.read_parquet(OUT/filename).set_index(groupby)
        grouped=checked.groupby(groupby).agg(races=('race_id','nunique'),nll=('nll','mean'),brier=('brier','mean'))
        saved=saved.loc[grouped.index]
        near('aggregate_race_count',grouped.races,saved.races)
        near('aggregate_nll',grouped.nll,saved.mean_race_nll)
        near('aggregate_brier',grouped.brier,saved.mean_race_brier)
    preserved=[]
    for item in json.loads((HERE/'SESSION_START.json').read_text())['preserve']:
        assert sha(ROOT/item['path'])==item['sha256'],item['path']
        preserved.append(item['path'])
    result={'passed':True,'model_files_replayed':6,'raw_prediction_values_replayed':model_replays,
            'calibrations_verified':cal_checks,'calibration_checks':calibration_checks,
            'evaluation_races':1779,'metric_rows_checked':len(metrics),'selection_rows_checked':len(selections),
            'marginal_rows_checked':len(marginals),'ordered_triples_reconstructed':triples,
            'pair_selection_count_distributions_checked':pair_checks,'reliability_rows_checked':len(reliability),
            'bootstrap_TRI_draws_compared':6000,'axis_comparisons':axis_results,
            'gates':gates,'overall_gate_pass':bool(gates['S_minus_C'] and gates['S_minus_R']),
            'maximum_errors':dict(ERRORS),'protected_files_unchanged':preserved,
            'fit_receipt_sha256':sha(OUT/'fit_run_receipt.json'),'verifier_sha256':sha(Path(__file__)),
            'math_reference_sha256':sha(MATH),'experiment_module_imported':False,'models_refitted':False,
            'bootstrap_scope':'fixed predictions; fit uncertainty excluded; reused development data'}
    with (HERE/'RESULT_VERIFICATION.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    with (HERE/'PAIR_BOOTSTRAP.json').open('x') as stream:json.dump(pair_results,stream,indent=2);stream.write('\n')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
