"""Saved-model replay, fixed ticket identity, and direct history/score checks."""
import json
import numpy as np
import pandas as pd
import support as s
import calibrate as cal
import lightgbm as lgb

def history_check(f):
    h=s.oldstate.observations();byhorse=h.groupby('horse_id',sort=False).indices
    byrace=h.groupby('race_key',sort=False).indices
    sample=f[f.year.ge(2024)].sample(120,random_state=20261025)
    largest=0.
    for row in sample.itertuples():
        indices=byhorse.get(row.horse_id,[]);past=h.iloc[indices]
        past=past[past.race_date.le(row.cutoff_date)].sort_values('race_date');v=[]
        for r in past.itertuples():
            if r.result_status!='finished' or not pd.notna(r.finish_order) or r.finish_order<=0:
                v.append(np.nan);continue
            field=h.iloc[byrace[r.race_key]]
            opponents=[x.finish_order for x in field.itertuples() if x.horse_id!=r.horse_id and x.result_status=='finished' and pd.notna(x.finish_order) and x.finish_order>0]
            if not opponents:v.append(np.nan);continue
            v.append(sum(1. if r.finish_order<rank else .5 if r.finish_order==rank else 0. for rank in opponents)/len(opponents))
        v=np.array(v,dtype=float)
        def mean(x):return float(np.nanmean(x)) if np.isfinite(x).any() else np.nan
        def std(x):return float(np.nanstd(x,ddof=1)) if np.isfinite(x).sum()>1 else np.nan
        expected=[v[-1] if len(v) else np.nan,mean(v[-3:]),mean(v[-5:]),std(v[-5:]),mean(v),float(np.isfinite(v).sum()),float(np.isfinite(v[-5:]).sum())]
        actual=[getattr(row,k) for k in s.SIMPLE[:7]]
        np.testing.assert_allclose(actual,expected,atol=1e-10,rtol=0,equal_nan=True)
        d=np.abs(np.array(actual)-np.array(expected));largest=max(largest,float(np.nanmax(d)))
    return {'rows':len(sample),'maximum_error':largest}

def main():
    s.check();f=s.frame();metrics=pd.read_parquet(s.OUT/'race_metrics.parquet')
    readiness=json.loads((s.OUT/'later_period_readiness.json').read_text())
    for path,info in readiness['sources'].items():assert s.sha(s.ROOT/path)==info['sha256'],path
    tickets=pd.read_parquet(s.OUT/'tickets.parquet');runners=pd.read_parquet(s.OUT/'runner_probabilities.parquet')
    old=pd.read_parquet(s.PREV/'outputs/race_metrics.parquet');old=old[old.variant.eq('state_gbm')].set_index('race_key')
    oldtickets=pd.read_parquet(s.PREV/'outputs/tickets.parquet');oldtickets=oldtickets[oldtickets.variant.eq('state_gbm')]
    assert len(metrics)==4799*5 and len(runners)==50754*5 and len(tickets)==4799*5*6
    assert not runners.duplicated(['variant',*s.KEY]).any()
    sort=['race_key','pool','rank'];original=oldtickets.sort_values(sort).reset_index(drop=True)
    for v in ['cal_candidate','cal_selected']:
        g=tickets[tickets.variant.eq(v)].sort_values(sort).reset_index(drop=True)
        for name in ['race_key','pool','rank','program_a','program_b','hit']:assert g[name].equals(original[name]),(v,name)
        a=metrics[metrics.variant.eq(v)].set_index('race_key').loc[old.index]
        for name in ['axis_program_no','axis_top3','quinella_one','quinella_three','qpl_one','qpl_three','qpl_count']:
            assert np.array_equal(a[name],old[name]),(v,name)
    lookup=f[f.year.ge(2024)].set_index(['race_key','program_no']).outcome
    a=np.array([lookup.loc[(r,p)] for r,p in zip(tickets.race_key,tickets.program_a)])
    b=np.array([lookup.loc[(r,p)] for r,p in zip(tickets.race_key,tickets.program_b)])
    bound=np.where(tickets.pool.eq('quinella'),2,3)
    actual=(a>=1)&(a<=bound)&(b>=1)&(b<=bound);assert np.array_equal(actual,tickets.hit.to_numpy(bool))
    mm=metrics.set_index(['variant','race_key'])
    for (v,r,pool),g in tickets.groupby(['variant','race_key','pool']):
        m=mm.loc[(v,r)];assert len(g)==3 and len(set(zip(g.program_a,g.program_b)))==3
        assert g.hit.max()==m[pool+'_three'] and g.loc[g['rank'].eq(1),'hit'].iloc[0]==m[pool+'_one']
        if pool=='qpl':assert g.hit.sum()==m.qpl_count
    masschecks=runners.groupby(['variant','race_key'])[['win','top2','top3']].sum().to_numpy()
    assert abs(masschecks-np.array([1,2,3])).max()<1e-9
    assert (runners.win>=0).all() and (runners.win<=runners.top2+1e-12).all() and (runners.top2<=runners.top3+1e-12).all() and (runners.top3<=1+1e-12).all()
    max_error=0.;replayed=0;replayed_cal=0
    for variant,cols in s.contracts().items():
        for meet in [1,3]:
            one=f[f.meet.eq(meet)].reset_index(drop=True)
            for year in [2024,2025,2026]:
                folder=s.OUT/'models'/f'{variant}_{meet}_{year}';meta=json.loads((folder/'metadata.json').read_text())
                assert meta['train_end_year']<meta['calibration_year']<meta['evaluation_year']
                assert meta['input_fingerprint']==s.sha(s.OUT/'input_manifest.json')
                assert s.sha(s.ROOT/meta['model_path'])==meta['model_sha256']
                x,_=s.base.encode(one,cols,vocabulary=meta['category_vocabulary']);mask=one.year.isin([year-1,year])
                model=lgb.Booster(model_file=str(s.ROOT/meta['model_path']));p=model.predict(x.loc[mask],raw_score=True,num_threads=4)
                saved=pd.read_parquet(folder/'scores.parquet').set_index('row_number').loc[one.loc[mask,'row_number'],'score'].to_numpy()
                err=float(abs(p-saved).max());assert err<1e-12;max_error=max(max_error,err);replayed+=len(p)
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            params=json.loads((s.OUT/'calibrators'/f'{meet}_{year}.json').read_text())
            assert params['fit_year']==year-1 and params['pilot_base_temperature_uses_validation_half'] is False
            assert params['fit_months']==[1,6] and params['validation_months']==[7,12] and params['final_refit_months']==[1,12]
            assert params['selected_from_prior_year']==(params['prior_validation_mean_brier_difference']<0 and params['prior_validation_order_nll_difference']<=0)
            folder=s.PREV/'outputs/models'/f'state_gbm_{meet}_{year}';meta=json.loads((folder/'metadata.json').read_text())
            score=pd.read_parquet(folder/'scores.parquet').query("phase=='evaluation'").set_index('row_number').score
            one=f[f.meet.eq(meet)&f.year.eq(year)].copy();one['score']=one.row_number.map(score)
            groups=list(one.groupby('race_key',sort=False))
            for key,g in [groups[0],groups[-1]]:
                ss=g.score.to_numpy(float);orders,mass=s.prob.ordered_distribution(ss,s.prob.trio_distribution(ss,meta['temperature']),meta['order_temperature'])
                for variant,bkey in [('cal_candidate','beta'),('cal_selected','applied_beta')]:
                    adjusted,code,pattern,_=cal.transform(orders,mass,np.array(params[bkey]));m=s.prob.marginals(len(g),orders,adjusted)
                    saved=runners[runners.variant.eq(variant)&runners.race_key.eq(key)].sort_values('program_no')
                    err=max(float(abs(m[k]-saved[k].to_numpy()).max()) for k in ['win','top2','top3'])
                    assert err<1e-12;max_error=max(max_error,err);replayed_cal+=len(g)
                    aggregated=np.bincount(code,weights=adjusted,minlength=8)
                    assert abs(aggregated-cal.transform_patterns(pattern[None],np.array(params[bkey]))[0]).max()<1e-12
    hcheck=history_check(f)
    assert (f.simple_source_date.isna()|f.simple_source_date.le(f.cutoff_date)).all()
    s.save(s.OUT/'verification.json',{'status':'passed','model_replayed_rows':replayed,'calibrator_replayed_runner_rows':replayed_cal,
        'maximum_replay_error':max_error,'tickets_independently_scored':len(tickets),'runner_probabilities_checked':len(runners),
        'calibration_tickets_and_axis_exactly_unchanged':True,'calibration_temporal_selection_checked':True,
        'simple_history_direct_check':hcheck,'all_sources_before_cutoff':True,
        'frozen_inputs_checked':len(json.loads((s.OUT/'input_manifest.json').read_text())),
        'source_database_and_production_registry_unchanged':True,'later_period_source_hashes_checked':len(readiness['sources']),
        'independent_external_reviewer':False})
    print('Verification passed',replayed,replayed_cal,len(tickets),max_error,flush=True)

if __name__=='__main__':main()
