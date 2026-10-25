"""Post-run audit: chronological sources, residual replay, direct labels, and probability mass."""
import json
import failure_common as c
import evaluate_failure as ev
import numpy as np
import pandas as pd
import lightgbm as lgb
import duckdb

def main():
    c.check();f=c.old.frame();f.index=f.row_number
    examples=pd.read_parquet(c.OUT/'axis_examples.parquet').set_index('race_key')
    rr=pd.read_parquet(c.OUT/'conditional_runners.parquet').set_index('row_number')
    results=pd.read_parquet(c.OUT/'race_predictions.parquet');byrace=results.set_index('race_key')
    audit=json.loads((c.OUT/'examples_audit.json').read_text())
    assert c.sha(c.OUT/'axis_examples.parquet')==audit['examples_sha256']
    assert c.sha(c.OUT/'conditional_runners.parquet')==audit['runners_sha256']
    assert set(results.race_key)==set(f.loc[f.year.ge(2024),'race_key']) and len(results)==4799
    for field in ['history_source_date','profile_source_date','weight_source_date']:
        assert (f[field].isna()|f[field].le(f.cutoff_date)).all()
    assert (f.cutoff_date<=f.race_date-pd.Timedelta(days=2)).all()
    assert json.loads((c.PREV/'outputs/state_contract.json').read_text())['all_sources_before_cutoff']

    with duckdb.connect(str(c.old.DB),read_only=True) as con:
        official=con.execute("""SELECT CAST(canonical_meet AS VARCHAR)||':'||strftime(race_date,'%Y%m%d')||':'||CAST(race_no AS VARCHAR) race_key,
            chul_no program_no,hr_no horse_id,finish_order,result_status FROM entry_result WHERE canonical_meet IN (1,3)""").df()
    axes=examples.reset_index().merge(official,left_on=['race_key','axis_program_no','axis_horse_id'],
        right_on=['race_key','program_no','horse_id'],validate='1:1')
    assert len(axes)==len(examples)
    truth=axes.result_status.eq('finished')&axes.finish_order.between(1,3)
    assert axes.axis_hit.eq(truth.astype(int)).all() and axes.failure.eq((~truth).astype(int)).all()
    direct=0
    for policy in ['control','raw','selected']:
        z=results.merge(official,left_on=['race_key',policy+'_program_no'],right_on=['race_key','program_no'],validate='1:1')
        assert len(z)==4799
        hit=z.result_status.eq('finished')&z.finish_order.between(1,3)
        assert z[policy+'_hit'].eq(hit.astype(int)).all();direct+=len(z)

    base_rows=0;base_error=0.;features_checked=0;cond_error=0.;tilt_error=0.;policy_checked=0;full_orders_checked=0
    for meet in [1,3]:
        for year in range(2020,2027):
            folder=c.base_folder(meet,year);meta=json.loads((folder/'metadata.json').read_text())
            assert meta['train_end_year']==year-2 and meta['calibration_year']==year-1
            scores=pd.read_parquet(folder/'scores.parquet').set_index('row_number')
            g=f.loc[scores.index];assert g.meet.eq(meet).all()
            assert g.loc[scores.phase.eq('calibration'),'year'].eq(year-1).all()
            assert g.loc[scores.phase.eq('evaluation'),'year'].eq(year).all()
            one=f[f.meet.eq(meet)]
            _,vocab=c.old.base.encode(one,meta['features'],mask=one.year.between(2017,year-3))
            assert vocab==meta['category_vocabulary']
            x,_=c.old.base.encode(g,meta['features'],vocabulary=vocab)
            model=lgb.Booster(model_file=str(folder/'model.txt'))
            pred=model.predict(x,raw_score=True,num_threads=4)
            err=float(abs(pred-scores.score).max());assert err<1e-12
            base_error=max(base_error,err);base_rows+=len(g)
            if year<2024:
                mask=scores.phase.eq('calibration')
                temp=c.old.base.set_temperature(g.loc[mask].reset_index(drop=True),pred[mask])
                assert abs(temp-meta['temperature'])<1e-10
            for _,race in g.loc[scores.phase.eq('evaluation')].groupby('race_key',sort=False):
                race=race.sort_values('program_no');score=scores.loc[race.row_number,'score'].to_numpy(float)
                reconstructed,conditional=c.race_example(race,score,meta['temperature'])
                ref=examples.loc[race.race_key.iloc[0]]
                actual=np.array([reconstructed[k] for k in c.FEATURES]);stored=ref[c.FEATURES].to_numpy(float)
                assert np.allclose(actual,stored,rtol=0,atol=1e-12,equal_nan=True)
                assert reconstructed['axis_program_no']==ref.axis_program_no and reconstructed['failure']==ref.failure
                mutated=race.copy();mutated['outcome']=92
                changed,_=c.race_example(mutated,score,meta['temperature'])
                assert np.allclose(actual,[changed[k] for k in c.FEATURES],rtol=0,atol=0,equal_nan=True)
                features_checked+=1
                saved=rr.loc[race.row_number]
                for col in ['base_top3','given_axis_in','given_axis_out']:
                    ce=float(abs(saved[col].to_numpy()-conditional[col].to_numpy()).max())
                    cond_error=max(cond_error,ce);assert ce<1e-12
                if year<2024:continue
                record=byrace.loc[race.race_key.iloc[0]]
                sets=c.old.base.triples(len(race));q=c.old.prob.trio_distribution(score,meta['temperature'])
                axis=int(np.flatnonzero(conditional.is_axis)[0]);event=(sets==axis).any(axis=1);pi=float(q[event].sum())
                for policy,risk,lam in [('control',record.control_risk,1.),('raw',record.model_risk,1.),
                    ('selected',record.model_risk,record.policy_lambda)]:
                    target=(1-lam)*pi+lam*(1-risk)
                    qt=q*np.where(event,target/pi,(1-target)/(1-pi))
                    assert abs(qt.sum()-1)<1e-10 and qt.min()>=0
                    p=np.bincount(sets.ravel(),weights=np.repeat(qt,3),minlength=len(race))
                    pe=float(abs(p-c.adjusted_top3(conditional,target)).max());tilt_error=max(tilt_error,pe);assert pe<1e-10
                    selected=int(c.order(p)[0])
                    assert int(race.iloc[selected].program_no)==record[policy+'_program_no']
                    assert abs(p[selected]-record[policy+'_probability'])<1e-10
                    policy_checked+=1
                # Full ordered-distribution check once per evaluation fold.
                if full_orders_checked < (0 if meet==1 else 3)+year-2023:
                    orders,mass=c.old.prob.ordered_distribution(score,q,meta['order_temperature'])
                    event_order=(orders==axis).any(axis=1);target=1-record.model_risk
                    weighted=mass*np.where(event_order,target/pi,(1-target)/(1-pi))
                    marg=c.old.prob.marginals(len(race),orders,weighted)
                    assert abs(weighted.sum()-1)<1e-10
                    assert np.allclose(marg['top3'],c.adjusted_top3(conditional,target),atol=1e-10)
                    assert np.max(marg['win']-marg['top2'])<1e-10 and np.max(marg['top2']-marg['top3'])<1e-10
                    full_orders_checked+=1
            print('Verified base/examples',meet,year,flush=True)

    risk_rows=0;risk_error=0.;folds=[]
    ex=examples.reset_index()
    groups={k:g.sort_values('program_no') for k,g in rr.reset_index().groupby('race_key',sort=False)}
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            folder=c.OUT/'risk_models'/f'axis_failure_{meet}_{year}';meta=json.loads((folder/'metadata.json').read_text())
            decision=json.loads((folder/'selection.json').read_text());assert all(meta[k]==value for k,value in decision.items())
            assert meta['features']==c.FEATURES and meta['train_end_year']==year-2 and meta['calibration_year']==year-1
            assert pd.Timestamp(meta['train_last_date'])<pd.Timestamp(meta['calibration_first_date'])
            assert meta['model_sha256']==c.sha(folder/'model.txt')
            predictions=pd.read_parquet(folder/'predictions.parquet').set_index('race_key')
            one=examples.loc[predictions.index]
            assert one.meet.eq(meet).all()
            model=lgb.Booster(model_file=str(folder/'model.txt'))
            raw=one.base_failure_logit.to_numpy(float)+model.predict(one[c.FEATURES],raw_score=True,num_threads=4)
            err=float(abs(raw-predictions.model_raw_score).max());risk_error=max(err,risk_error);assert err<1e-12;risk_rows+=len(one)
            mutated=one.copy();mutated['axis_outcome']=92;mutated['failure']=1-mutated.failure;mutated['axis_hit']=1-mutated.axis_hit
            assert np.array_equal(model.predict(mutated[c.FEATURES],raw_score=True,num_threads=4),model.predict(one[c.FEATURES],raw_score=True,num_threads=4))
            cal=predictions.phase.eq('calibration');cf=one.loc[cal]
            assert cf.year.eq(year-1).all() and one.loc[~cal,'year'].eq(year).all()
            rc=c.fit_calibration(raw[cal],cf.failure);bc=c.fit_calibration(cf.base_failure_logit,cf.failure)
            for name,value in [('risk_calibration',rc),('base_calibration',bc)]:
                for key in ['intercept','slope','objective']:assert abs(value[key]-meta[name][key])<1e-10
            assert np.allclose(c.calibrated(raw,rc),predictions.model_risk,rtol=0,atol=1e-12)
            assert np.allclose(c.calibrated(one.base_failure_logit,bc),predictions.control_risk,rtol=0,atol=1e-12)
            cp=predictions.loc[cal]
            hits=[sum(c.pick(groups[key],p,lam)[1] for key,p in zip(cp.index,cp.model_risk)) for lam in c.LAMBDAS]
            assert hits==list(meta['calibration_policy_hits'].values()) and c.LAMBDAS[int(np.argmax(hits))]==meta['policy_lambda']
            for name in ev.RISKS:assert abs(np.quantile(cp[name],.8)-meta['warning_thresholds'][name])<1e-12
            folds.append({'meet':meet,'year':year,'trees':meta['trees'],'lambda':meta['policy_lambda'],
                'training_races':meta['training_races'],'calibration_races':meta['calibration_races']})
            print('Verified risk',meet,year,flush=True)
    reference=pd.read_parquet(c.PREV/'outputs/race_metrics.parquet');reference=reference[reference.variant.eq('state_gbm')]
    z=results.merge(reference[['race_key','axis_program_no','axis_top3','axis_probability']],on='race_key',validate='1:1',suffixes=('','_old'))
    assert len(z)==4799 and z.axis_program_no.eq(z.axis_program_no_old).all() and z.axis_hit.eq(z.axis_top3).all()
    assert abs(z.base_axis_probability-z.axis_probability).max()<1e-12
    assert json.loads((c.OUT/'results.json').read_text())==ev.summarize(results)
    c.check()
    c.save(c.OUT/'verification.json',{'status':'passed','official_axis_training_labels_checked':len(axes),
        'official_candidate_axis_predictions_checked':direct,'base_score_rows_replayed':base_rows,'base_score_max_error':base_error,
        'axis_feature_records_reconstructed':features_checked,'conditional_probability_max_error':cond_error,
        'new_risk_predictions_replayed':risk_rows,'new_risk_max_error':risk_error,'coherent_policy_records_checked':policy_checked,
        'coherent_marginal_max_error':tilt_error,'full_ordered_distribution_folds_checked':full_orders_checked,
        'future_label_mutation_predictions_unchanged':True,'all_base_axes_and_probabilities_match':True,
        'all_learning_and_calibration_chronological':True,'previous_year_selection_reproduced':True,
        'past_source_dates_checked':True,'state_source_date_audit_referenced':True,
        'source_database_and_operating_registry_unchanged':True,'pair_tickets_unchanged':True,'folds':folds,
        'independent_external_review':False})
    print('Verification passed',base_rows,risk_rows,flush=True)

if __name__=='__main__':main()
