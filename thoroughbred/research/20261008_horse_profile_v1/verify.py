"""Independent rolling statistics, frozen feature comparison and cutoff checks."""
import importlib.util
import json
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('profile_implementation',HERE/'run.py')
RUN=importlib.util.module_from_spec(spec);spec.loader.exec_module(RUN)

def main():
    out=HERE/'outputs'
    p=pd.read_parquet(out/'profiles.parquet')
    assert len(p)==50754 and p.race_key.nunique()==4799 and not p.duplicated(RUN.KEY).any()
    assert (p.history_source_date.isna()|p.history_source_date.le(p.cutoff_date)).all()
    checks=0;max_error=0.0
    def compare(a,b,name):
        nonlocal checks,max_error
        a=np.asarray(a,float);b=np.asarray(b,float)
        assert np.allclose(a,b,atol=1e-9,rtol=0,equal_nan=True),name
        finite=np.isfinite(a)&np.isfinite(b)
        if finite.any():max_error=max(max_error,float(np.max(np.abs(a[finite]-b[finite]))))
        checks+=len(a)
    mapping={'last':'last_record_index','mean3':'last3_record_index_mean','best5':'last5_record_index_best',
             'count5':'last5_record_index_count','std5':'last5_record_index_std'}
    raw=pd.read_parquet(RUN.RAW,columns=RUN.KEY+list(mapping.values())+['history_count','days_since_last'])
    adjusted=pd.read_parquet(RUN.RESEARCH/'20261005_moisture_finish_v1/outputs/adjusted_features.parquet',
                             columns=RUN.KEY+list(mapping.values()))
    for variant,reference in [('raw',raw),('moist',adjusted)]:
        aligned=p[RUN.KEY].merge(reference,on=RUN.KEY,validate='one_to_one')
        for name,column in mapping.items():
            expected=aligned[column].to_numpy(float)
            if name=='count5':expected=np.nan_to_num(expected,nan=0.0)
            if name=='std5':expected=np.where(p[variant+'_count5'].ge(3),expected,np.nan)
            compare(p[variant+'_'+name],expected,variant+'_'+name)
        if variant=='raw':
            compare(p.history_count,aligned.history_count,'history_count')
            compare(p.days_since_last,aligned.days_since_last,'days_since_last')
    print('Frozen features reproduced',checks,flush=True)
    records=RUN.load_records()
    # Independent pandas states use whole ordered histories, rolling windows then as-of lookup.
    states=records[['horse_id','race_date','q_raw','q_moist']].copy()
    for variant in ['raw','moist']:
        g=states.groupby('horse_id',sort=False)['q_'+variant]
        states[variant+'_count3']=g.transform(lambda x:x.rolling(3,min_periods=1).count())
        states[variant+'_previous3_count']=g.transform(lambda x:x.shift(3).rolling(3,min_periods=1).count())
        states[variant+'_previous3']=g.transform(lambda x:x.shift(3).rolling(3,min_periods=1).mean())
        states[variant+'_mean3']=g.transform(lambda x:x.rolling(3,min_periods=1).mean())
        states[variant+'_trend']=(states[variant+'_mean3']-states[variant+'_previous3']).where(
            states[variant+'_count3'].ge(2)&states[variant+'_previous3_count'].ge(2))
        states[variant+'_top2mean5']=g.transform(lambda x:x.rolling(5,min_periods=2).apply(lambda v:np.sort(v[np.isfinite(v)])[-2:].mean(),raw=True))
    right=states.drop(columns=['q_raw','q_moist']).rename(columns={'race_date':'source_date'})
    left=p[RUN.KEY+['horse_id','cutoff_date']].loc[:,lambda x:~x.columns.duplicated()].copy()
    left['_row']=np.arange(len(left))
    aligned=pd.merge_asof(left.sort_values('cutoff_date'),right.sort_values('source_date'),
                          left_on='cutoff_date',right_on='source_date',by='horse_id',direction='backward').sort_values('_row')
    for variant in ['raw','moist']:
        for name in ['count3','previous3_count','previous3','trend','top2mean5']:
            expected=aligned[variant+'_'+name]
            if name.endswith('count') or name=='count3':expected=expected.fillna(0)
            compare(p[variant+'_'+name],expected,variant+'_'+name)
        assert p.loc[p[variant+'_count5'].lt(2),variant+'_top2mean5'].isna().all()
        assert p.loc[p[variant+'_count5'].lt(3),variant+'_std5'].isna().all()
        known=p[variant+'_top2mean5'].notna()
        assert p.loc[known,variant+'_top2mean5'].le(p.loc[known,variant+'_best5']+1e-12).all()
    assert p.loc[p.history_count.eq(0),'moist_mean3'].isna().all()
    assert (records.trained_through.isna()|records.trained_through.lt(records.year)).all()
    assert (records.environment_trained_through.isna()|records.environment_trained_through.lt(records.year)).all()
    # Historical assets are frozen. Perturbing outcomes/times after each query's cutoff cannot alter its profile.
    selected=p.drop_duplicates('horse_id').sample(24,random_state=20261008)
    targets=selected[RUN.KEY+['meet','race_date','race_no','distance_m','grade_raw','horse_name']]
    changed=records.copy()
    for row in selected.to_dict('records'):
        mask=changed.horse_id.eq(row['horse_id'])&changed.race_date.gt(row['cutoff_date'])
        changed.loc[mask,['q_raw','q_moist','raw_finish','moist_finish','age','body_weight','carried_weight']]=999
        changed.loc[mask,'outcome']=1
    computed=RUN.build_profiles(targets,changed)
    pd.testing.assert_frame_equal(computed.reset_index(drop=True),selected[computed.columns].reset_index(drop=True),check_dtype=False)
    checks+=len(computed)*len(computed.columns)
    # Explicit non-overlapping/invalid-start windows, and last start invalid preservation.
    s=RUN.metrics(np.array([np.nan,2.,4.,8.,np.nan,6.,100.]))
    assert s['last']!=s['last'] and s['mean3']==3 and s['previous3']==7 and s['trend']==-4
    assert s['count3']==2 and s['previous3_count']==2 and s['top2mean5']==6
    assert RUN.metrics(np.array([1.]))['std5']!=RUN.metrics(np.array([1.]))['std5']
    history=pd.read_parquet(out/'display_history.parquet')
    joined=history.merge(p[RUN.KEY+['cutoff_date']],on=RUN.KEY,validate='many_to_one')
    assert joined.history_date.le(joined.cutoff_date).all()
    sensitivity=pd.read_parquet(out/'gate_sensitivity_current_view.parquet')
    assert sensitivity.retrospective_only.all() and not sensitivity.usable_for_historical_prediction.any()
    assert sensitivity.analysis_as_of.eq('2026-10-08').all()
    class Counter(HTMLParser):
        def __init__(self):super().__init__();self.n=0
        def handle_starttag(self,tag,attrs):
            if tag=='article':self.n+=1
    html_text=(out/'profiles.html').read_text();counter=Counter();counter.feed(html_text)
    cards=pd.read_parquet(out/'display_cards.parquet')
    assert counter.n==len(cards)
    assert 'innerHTML' not in html_text
    assert RUN.fmt('<script>alert(1)</script>')=='&lt;script&gt;alert(1)&lt;/script&gt;'
    hashes=json.loads((out/'sources.json').read_text())
    for name,value in hashes.items():assert RUN.sha(RUN.ROOT/name)==value,name
    cases={
        'no_history':p[p.history_count.eq(0)],
        'one_prior_start':p[p.history_count.eq(1)],
        'previous_nonfinish':p[p.previous_outcome.isin([91,92])],
        'long_break_180d':p[p.days_since_last.ge(180)],
        'mixed_venue':p[p.mixed_venue_last10],
        'no_recent_valid_time':p[p.history_count.gt(0)&p.moist_count5.eq(0)],
    }
    example_cases=[]
    for kind,subset in cases.items():
        if len(subset):
            row=subset.sort_values('race_date').iloc[-1]
            example_cases.append({'case':kind,'race_key':row.race_key,'program_no':int(row.program_no),
                                  'horse_id':row.horse_id,'horse_name':row.horse_name,'cases':len(subset)})
    assert all(len(subset)>0 for subset in cases.values())
    RUN.save(out/'verification.json',dict(status='passed',numeric_checks=checks,max_error=max_error,
             independent_pandas_states=True,frozen_feature_reproduction=True,future_perturbation_cases=24,
             input_hashes_unchanged=True,html_cards=counter.n,cases=example_cases,gate_not_historical_prediction=True))
    print(json.dumps(dict(status='passed',checks=checks,max_error=max_error,examples=example_cases),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
