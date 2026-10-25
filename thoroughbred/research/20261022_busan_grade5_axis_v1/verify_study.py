"""Independent saved-score, input, recommendation, and timing verification."""
import json
import numpy as np
import pandas as pd
import duckdb
import axis_common as c
import switch_model as sm
import lightgbm as lgb

def main():
    c.check();f=c.frame();pairs=pd.read_parquet(c.OUT/'pairs.parquet');out=pd.read_parquet(c.OUT/'axis_predictions.parquet')
    audit=json.loads((c.OUT/'pairs_audit.json').read_text());assert audit['pair_sha256']==c.sha(c.OUT/'pairs.parquet')
    assert len(out)==1961 and out.race_key.is_unique and int(out.target.sum())==210
    assert int((out.target&out.year.eq(2026)).sum())==72
    assert c.target(out).equals(out.target)
    assert not any(x.startswith('observed_') or 'outcome' in x or 'hit' in x for x in c.FEATURES)
    metadata=[];replayed=0;maximum=0.;modelprobabilityrows=0
    one=f[f.meet.eq(3)].reset_index(drop=True)
    for year in [2024,2025,2026]:
        folder=c.PREV/'outputs/models'/f'state_gbm_3_{year}';meta=json.loads((folder/'metadata.json').read_text())
        x,_=c.old.base.encode(one,meta['features'],vocabulary=meta['category_vocabulary'])
        mask=one.year.isin([year-1,year]);model=lgb.Booster(model_file=str(c.ROOT/meta['model_path']))
        actual=model.predict(x.loc[mask],raw_score=True,num_threads=4)
        saved=pd.read_parquet(folder/'scores.parquet').set_index('row_number').loc[one.loc[mask,'row_number'],'score'].to_numpy()
        error=float(abs(actual-saved).max());assert error<1e-12;maximum=max(maximum,error);replayed+=len(saved)
        model=json.loads((c.OUT/'models'/f'{year}.json').read_text())
        assert model['input_fingerprint']==c.sha(c.OUT/'input_manifest.json') and model['pair_fingerprint']==c.sha(c.OUT/'pairs.parquet')
        assert meta['train_end_year']<year-1==model['fit_year']
        prior=pairs[pairs.fold_year.eq(year)&pairs.phase.eq('calibration')]
        half=prior[prior.race_date.dt.month.ge(7)];p,u=sm.predict(half,model['pilot'])
        active=u>.05;diff=half.switch_label.to_numpy()*active;t=half.target.to_numpy(bool)
        gate=bool((active&t).sum()>=5 and diff[t].sum()>0 and diff.sum()>=0)
        assert gate==model['selection']['selected']
        assert model['pilot']['fit_end']<f'{year-1}-07-01' and model['final']['fit_end']<f'{year}-01-01'
        test=out[out.year.eq(year)];p,u=sm.predict(test,model['final'])
        np.testing.assert_allclose(p[:,2],test.gain_probability,atol=1e-12,rtol=0)
        np.testing.assert_allclose(p[:,0],test.loss_probability,atol=1e-12,rtol=0)
        np.testing.assert_allclose(u,test.expected_gain,atol=1e-12,rtol=0)
        assert np.array_equal((u>.05)&test.target,test.candidate_switch)
        assert np.array_equal(test.candidate_switch&gate,test.selected_switch)
        mutated=test.copy();mutated['axis_outcome']=99;mutated['alt_outcome']=1;mutated['switch_label']=-test.switch_label
        mutated['axis_hit']=1-test.axis_hit;mutated['observed_role']=0
        p2,u2=sm.predict(mutated,model['final']);assert np.array_equal(p,p2) and np.array_equal(u,u2)
        modelprobabilityrows+=len(p)
    lookup=f.set_index(c.KEY)
    ai=pd.MultiIndex.from_arrays([pairs.race_key,pairs.axis_program_no,pairs.axis_horse_id],names=c.KEY)
    bi=pd.MultiIndex.from_arrays([pairs.race_key,pairs.alt_program_no,pairs.alt_horse_id],names=c.KEY)
    a=lookup.loc[ai].reset_index();b=lookup.loc[bi].reset_index()
    for name in c.AXIS:np.testing.assert_allclose(pairs['axis_'+name],a[name],equal_nan=True,atol=1e-12,rtol=0)
    for name in c.DIFF:np.testing.assert_allclose(pairs['diff_'+name],b[name]-a[name],equal_nan=True,atol=1e-12,rtol=0)
    history=f.groupby('horse_id').indices
    for row in a.sample(100,random_state=20261026).itertuples():
        past=f.iloc[history[row.horse_id]];past=past[past.race_date.le(row.cutoff_date)].sort_values('race_date')
        if len(past):
            latest=past.iloc[-1]
            assert row.previous_source_date==latest.race_date
            np.testing.assert_allclose([row.previous_grade,row.previous_distance],[latest.grade,latest.distance_m],equal_nan=True)
    with duckdb.connect(str(c.old.DB),read_only=True) as db:
        actual=db.execute("""SELECT CAST(canonical_meet AS VARCHAR)||':'||strftime(race_date,'%Y%m%d')||':'||CAST(race_no AS VARCHAR) race_key,
            chul_no program_no,finish_order,result_status FROM entry_result
            WHERE canonical_meet=? AND race_date BETWEEN ? AND ?""",[3,'2024-01-01','2026-09-20']).df()
    assert not actual.duplicated(['race_key','program_no']).any()
    truth=actual.set_index(['race_key','program_no']);checked=0
    runner=pd.read_parquet(c.PREV/'outputs/runner_probabilities.parquet').query("variant=='state_gbm'").set_index(['race_key','program_no'])
    for name in ['candidate','selected']:
        keys=pd.MultiIndex.from_arrays([out.race_key,out[name+'_program_no']],names=['race_key','program_no'])
        ranks=truth.loc[keys]
        hit=(ranks.result_status.eq('finished')&ranks.finish_order.between(1,3)).to_numpy(int)
        assert np.array_equal(hit,out[name+'_hit'])
        assert np.array_equal(out.loc[~out.target,name+'_program_no'],out.loc[~out.target,'axis_program_no'])
        probability=runner.loc[keys,'top3'].to_numpy()
        np.testing.assert_allclose(probability,out[name+'_axis_probability'],atol=1e-12,rtol=0)
        checked+=len(hit)
    results=json.loads((c.OUT/'switch_results.json').read_text())
    for name in ['candidate','selected']:
        assert results['comparisons'][name]['target']==c.paired(out[out.target],name+'_hit')
    c.save(c.OUT/'verification.json',{'status':'passed','base_score_rows_replayed':replayed,'maximum_replay_error':maximum,
        'switch_probability_rows_replayed':modelprobabilityrows,'axis_predictions_directly_scored':checked,
        'all_pair_feature_rows_checked':len(pairs),'past_grade_distance_direct_checks':100,
        'prior_year_pilot_selection_reproduced':True,'future_label_mutation_invariant':True,
        'outside_target_unchanged':True,'selected_axis_probabilities_match_unchanged_joint':True,
        'frozen_source_and_operating_registry_hashes_checked':True,'independent_external_reviewer':False})
    print('Verification passed',replayed,modelprobabilityrows,checked,flush=True)

if __name__=='__main__':main()
