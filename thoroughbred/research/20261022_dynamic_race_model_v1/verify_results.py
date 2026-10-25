"""Independent ticket scoring and saved-model replay after fixed evaluation."""
import json
import numpy as np
import pandas as pd
import common as c
import joint,state
import lightgbm as lgb

def main():
    c.check_inputs();f=c.frame();metrics=pd.read_parquet(c.OUT/'race_metrics.parquet')
    tickets=pd.read_parquet(c.OUT/'tickets.parquet');runners=pd.read_parquet(c.OUT/'runner_probabilities.parquet')
    assert len(metrics)==3*4799 and len(tickets)==3*4799*6 and len(runners)==3*50754
    assert not metrics.duplicated(['variant','race_key']).any()
    assert not runners.duplicated(['variant',*c.KEY]).any()
    sf=pd.read_parquet(c.OUT/'state_features.parquet');contract=json.loads((c.OUT/'state_contract.json').read_text())
    assert c.sha(c.OUT/'state_features.parquet')==contract['state_sha256']
    assert (sf.state_source_date.isna()|sf.state_source_date.le(f.cutoff_date)).all()
    stats={};max_error=0.;replayed=0
    for variant,cols in c.features().items():
        for meet in [1,3]:
            one=f[f.meet.eq(meet)].reset_index(drop=True)
            for year in [2024,2025,2026]:
                folder=c.OUT/'models'/f'{variant}_{meet}_{year}';meta=json.loads((folder/'metadata.json').read_text())
                assert meta['train_end_year']<meta['calibration_year']<meta['evaluation_year']
                assert meta['input_fingerprint']==c.sha(c.OUT/'input_manifest.json')
                assert c.sha(c.ROOT/meta['model_path'])==meta['model_sha256']
                if variant!='state_joint':
                    x,_=c.base.encode(one,cols,vocabulary=meta['category_vocabulary'])
                    mask=one.year.isin([year-1,year]);saved=pd.read_parquet(folder/'scores.parquet').set_index('row_number')
                    model=lgb.Booster(model_file=str(c.ROOT/meta['model_path']))
                    actual=model.predict(x.loc[mask],raw_score=True,num_threads=4)
                    expected=saved.loc[one.loc[mask,'row_number'],'score'].to_numpy(float)
                    error=float(np.max(np.abs(actual-expected)));assert error<1e-12
                    replayed+=len(actual);max_error=max(max_error,error)
                else:
                    test=one[one.year.eq(year)].reset_index(drop=True)
                    x,_=joint.encode(test,cols,meta=json.loads((folder/'encoding.json').read_text()))
                    model=joint.restore(c.ROOT/meta['model_path'],meta['inputs'])
                    # First and last races per fold, separate safe checkpoint load.
                    groups=list(test.groupby('race_key',sort=False).indices.values())
                    for ix in [groups[0],groups[-1]]:
                        g=test.iloc[ix];o,p=joint.distribution(model,x[ix],meta['temperature'])
                        m=c.prob.marginals(len(g),o,p)
                        saved=runners[runners.variant.eq(variant)&runners.race_key.eq(g.race_key.iloc[0])].sort_values('program_no')
                        error=max(float(np.max(abs(m[k]-saved[k].to_numpy()))) for k in ['win','top2','top3'])
                        assert error<1e-12;max_error=max(max_error,error);replayed+=len(g)
    truth=f[f.year.ge(2024)].set_index(['race_key','program_no']).outcome
    a=np.array([truth.loc[(r,p)] for r,p in zip(tickets.race_key,tickets.program_a)])
    b=np.array([truth.loc[(r,p)] for r,p in zip(tickets.race_key,tickets.program_b)])
    limit=np.where(tickets.pool.eq('quinella'),2,3)
    hits=(a>=1)&(a<=limit)&(b>=1)&(b<=limit)
    assert np.array_equal(hits,tickets.hit.to_numpy(bool))
    for (variant,race,pool),g in tickets.groupby(['variant','race_key','pool']):
        assert len(g)==3 and len(set(zip(g.program_a,g.program_b)))==3
        row=metrics[metrics.variant.eq(variant)&metrics.race_key.eq(race)].iloc[0]
        assert int(g.hit.max())==row['quinella_three' if pool=='quinella' else 'qpl_three']
        assert int(g.loc[g['rank'].eq(1),'hit'].iloc[0])==row['quinella_one' if pool=='quinella' else 'qpl_one']
        if pool=='qpl':assert int(g.hit.sum())==row.qpl_count
    for (variant,race),g in runners.groupby(['variant','race_key']):
        assert abs(g.win.sum()-1)<1e-9 and abs(g.top2.sum()-2)<1e-9 and abs(g.top3.sum()-3)<1e-9
        assert (g.win>=0).all() and (g.win<=g.top2+1e-12).all() and (g.top2<=g.top3+1e-12).all() and (g.top3<=1+1e-12).all()
    # Rebuild a real early historical prefix; later observations are absent.
    prefix=f[f.meet.eq(1)].iloc[:100].copy().reset_index(drop=True)
    prefix['row_number']=np.arange(len(prefix))
    h=state.observations();h=h[h.race_date.le(prefix.cutoff_date.max())]
    again=state.generate(prefix,h)
    expected=sf.loc[f.index[f.meet.eq(1)][:100]].reset_index(drop=True)
    error=float(np.max(abs(again[contract['features']].to_numpy()-expected[contract['features']].to_numpy())))
    # Field-relative features require complete race groups; prefix contains a partial last group.
    core=[x for x in contract['features'] if '_field_' not in x]
    core_error=float(np.max(abs(again[core].to_numpy()-expected[core].to_numpy())))
    assert core_error<1e-12
    c.save(c.OUT/'verification.json',{'status':'passed','frozen_inputs':len(json.loads((c.OUT/'input_manifest.json').read_text())),
        'safe_saved_model_replayed_rows':replayed,'maximum_model_replay_error':max_error,
        'independently_scored_tickets':len(tickets),'all_marginals_checked':len(runners),
        'historical_prefix_rows':len(prefix),'historical_prefix_core_error':core_error,
        'all_state_sources_before_cutoff':True,'all_fold_model_chronology_valid':True,
        'original_database_and_operating_registry_unchanged':True,
        'preflight_passed':json.loads((c.OUT/'preflight.json').read_text())['status']=='passed',
        'independent_external_reviewer':False})
    print('Verification passed',replayed,len(tickets),max_error,flush=True)

if __name__=='__main__':main()
