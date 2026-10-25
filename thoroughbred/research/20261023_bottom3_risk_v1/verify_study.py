"""Post-run verification; no training or policy changes."""
import json
import risk_common as c
import evaluate_risk as ev
import numpy as np
import pandas as pd
import lightgbm as lgb

def main():
    c.check();f=c.frame();f.index=f.row_number
    m=pd.read_parquet(c.OUT/'race_metrics.parquet')
    metrics_by_race=m.set_index('race_key')
    rr=pd.read_parquet(c.OUT/'runner_predictions.parquet').set_index('row_number')
    features=c.old.features()['state_gbm']
    assert len(features)==118
    forbidden={'outcome','finish_order','result_status','bottom_truth','normal','boundary_tie','win_odds','place_odds'}
    assert not set(features)&forbidden
    for col in ['history_source_date','profile_source_date','weight_source_date']:
        assert (f[col].isna()|f[col].le(f.cutoff_date)).all()
    assert (f.cutoff_date <= f.race_date-pd.Timedelta(days=2)).all()
    state_contract=json.loads((c.PREV/'outputs/state_contract.json').read_text())
    assert state_contract['all_sources_before_cutoff']

    # Independent label construction from official rank groups, allocating exactly three slots.
    independent=pd.Series(0.,index=f.index)
    for _,g in f.groupby('race_key',sort=False):
        slots=3
        normal=g[g.result_status.eq('finished')]
        for rank in sorted(normal.finish_order.unique(),reverse=True):
            ix=normal.index[normal.finish_order.eq(rank)]
            amount=min(slots,len(ix));independent.loc[ix]=amount/len(ix);slots-=amount
            if slots==0:break
        assert slots==0
    label_error=float(abs(independent-f.bottom_truth).max());assert label_error==0
    assert np.allclose(rr.bottom_truth,independent.loc[rr.index])
    assert not rr.reset_index().duplicated(c.KEY).any()
    assert set(m.race_key)==set(f.loc[f.year.ge(2024),'race_key']) and len(m)==4799

    # Read and score the official finish labels independently of the evaluation implementation.
    official=c.official();checks=m.melt(id_vars='race_key',value_vars=['base_axis','exclude_axis','selected_axis'],
        var_name='policy',value_name='program_no').merge(official,on=['race_key','program_no'],validate='m:1')
    checks['direct_hit']=checks.result_status.eq('finished')&checks.finish_order.between(1,3)
    for policy,g in checks.groupby('policy'):
        expected=m.set_index('race_key')[policy+'_hit']
        assert np.array_equal(g.direct_hit.to_numpy(int),expected.loc[g.race_key].to_numpy(int))

    replay_rows=0;base_rows=0;new_error=0.;base_error=0.;folds=[]
    for meet in [1,3]:
        one=f[f.meet.eq(meet)].copy()
        for year in [2024,2025,2026]:
            folder=c.OUT/'models'/f'bottom3_{meet}_{year}'
            meta=json.loads((folder/'metadata.json').read_text())
            decision=json.loads((folder/'selection.json').read_text())
            assert all(meta[k]==v for k,v in decision.items())
            assert meta['train_end_year']==year-2 and meta['calibration_year']==year-1
            assert pd.Timestamp(meta['train_last_date'])<pd.Timestamp(meta['calibration_first_date'])
            s=pd.read_parquet(folder/'scores.parquet').set_index('row_number')
            g=one.loc[s.index]
            assert g.loc[s.phase.eq('calibration'),'year'].eq(year-1).all()
            assert g.loc[s.phase.eq('evaluation'),'year'].eq(year).all()
            _,vocab=c.old.base.encode(one,features,mask=one.year.between(2017,year-3))
            assert vocab==meta['category_vocabulary']
            x,_=c.old.base.encode(g,features,vocabulary=vocab)
            model=lgb.Booster(model_file=str(folder/'model.txt'))
            assert c.sha(folder/'model.txt')==meta['model_sha256'] and model.num_trees()==meta['trees']
            predicted=model.predict(x,raw_score=True,num_threads=4)
            new_error=max(new_error,float(abs(predicted-s.score).max()));replay_rows+=len(g)
            assert np.allclose(predicted,s.score,rtol=0,atol=1e-12)
            mutated=g.copy()
            mutated['outcome']=92;mutated['finish_order']=-999;mutated['result_status']='changed';mutated['bottom_truth']=1.
            changed,_=c.old.base.encode(mutated,features,vocabulary=vocab)
            pd.testing.assert_frame_equal(x,changed)
            assert np.array_equal(model.predict(changed,raw_score=True,num_threads=4),predicted)

            bfolder=c.PREV/'outputs/models'/f'state_gbm_{meet}_{year}'
            bm=json.loads((bfolder/'metadata.json').read_text())
            bs=pd.read_parquet(bfolder/'scores.parquet').set_index('row_number').loc[g.index]
            bx,_=c.old.base.encode(g,bm['features'],vocabulary=bm['category_vocabulary'])
            base=lgb.Booster(model_file=str(bfolder/'model.txt')).predict(bx,raw_score=True,num_threads=4)
            base_error=max(base_error,float(abs(base-bs.score).max()));base_rows+=len(g)
            assert np.allclose(base,bs.score,rtol=0,atol=1e-12)
            cal=s.phase.eq('calibration').to_numpy();cf=g.loc[cal].reset_index(drop=True)
            hits=c.policy_hits(cf,base[cal],predicted[cal])
            assert meta['policy_lambda']==c.LAMBDAS[int(np.argmax(hits))]
            assert list(meta['calibration_policy_hits'].values())==list(hits)
            assert abs(c.temperature(cf,predicted[cal])-meta['bottom_temperature'])<1e-10
            assert abs(c.temperature(cf,-base[cal])-meta['baseline_bottom_temperature'])<1e-10
            for _,race in g.loc[~cal].groupby('race_key',sort=False):
                observed=rr.loc[race.row_number]
                scores=s.loc[race.row_number,'score'].to_numpy(float)
                original=bs.loc[race.row_number,'score'].to_numpy(float)
                for name,score in [('baseline',-original),('model',scores)]:
                    ix=c.order(score)[:3]
                    assert observed[name+'_selected'].sum()==3
                    assert np.array_equal(np.flatnonzero(observed[name+'_selected']),np.sort(ix))
                    p=observed[name+'_bottom_probability'].to_numpy(float)
                    assert np.isfinite(p).all() and p.min()>=0 and p.max()<=1+1e-10 and abs(p.sum()-3)<1e-10
                record=metrics_by_race.loc[race.race_key.iloc[0]]
                assert int(race.iloc[c.choose(original,scores,meta['policy_lambda'])].program_no)==record.selected_axis
                assert int(race.iloc[c.exclude_axis(original,scores)].program_no)==record.exclude_axis
            folds.append({'meet':meet,'year':year,'lambda':meta['policy_lambda'],'trees':meta['trees'],
                'train_rows':meta['training_labeled_rows'],'replay_rows':len(g),'calibration_races':len(cf.groupby('race_key'))})
            print('Verified',meet,year,flush=True)

    baseline=pd.read_parquet(c.PREV/'outputs/runner_probabilities.parquet')
    baseline=baseline[baseline.variant.eq('state_gbm')]
    joined=rr.reset_index().merge(baseline[c.KEY+['top3']],on=c.KEY,validate='1:1')
    assert len(joined)==50754
    for _,g in joined.groupby('race_key',sort=False):
        g=g.sort_values('program_no')
        ix=c.order(-g.top3.to_numpy(float))[:3]
        assert np.array_equal(np.flatnonzero(g.baseline_selected),np.sort(ix))
    results=json.loads((c.OUT/'results.json').read_text());assert results==ev.summarize(m)
    c.check()
    c.save(c.OUT/'verification.json',{'status':'passed','independent_official_label_rows':len(f),'label_max_error':label_error,
        'evaluation_races':len(m),'evaluation_runners':len(rr),'official_axis_predictions_checked':len(checks),
        'new_score_rows_replayed':replay_rows,'base_score_rows_replayed':base_rows,
        'new_score_max_error':new_error,'base_score_max_error':base_error,
        'baseline_lowest_top3_matches_all_races':True,'all_races_retained':True,'one_axis_per_race':True,
        'prior_year_only_selection_reproduced':True,'current_label_mutation_prediction_unchanged':True,
        'past_source_dates_checked':True,'state_date_audit_referenced':True,
        'source_database_and_registry_hashes_unchanged':True,'joint_top_probabilities_and_pair_tickets_unchanged':True,
        'bottom_marginals_sum_to_three':True,'folds':folds,'independent_external_review':False})
    print(json.dumps({'status':'passed','new_replay_rows':replay_rows,'base_replay_rows':base_rows,'axis_checks':len(checks)}),flush=True)

if __name__=='__main__':main()
