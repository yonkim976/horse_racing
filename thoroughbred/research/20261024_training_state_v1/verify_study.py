"""Independent raw-row feature calculations, serialized models and full cohort checks."""
import argparse,json,math
import study_common as c
import build_features as b
import duckdb
import numpy as np
import pandas as pd
import lightgbm as lgb

def raw_basic(raw,date,lag,calendar):
    end=pd.Timestamp(date)-pd.Timedelta(days=lag);start=end-pd.Timedelta(days=27)
    window=raw[(raw.event_date>=start)&(raw.event_date<=end)]
    days={}
    for day,g in window.groupby('event_date'):
        total=0.;valid=True
        for _,s in g.groupby(['started_at_raw','ended_at_raw'],dropna=False):
            ds=pd.to_numeric(s.duration_seconds_raw,errors='coerce').to_numpy(float)
            okay=bool(np.isfinite(ds).all() and (ds>0).all() and (ds<=7200).all()
                and s.qa_flags_json.eq('[]').all() and s.duration_seconds_raw.nunique(dropna=False)==1)
            if okay:total+=float(ds[0])/60
            else:valid=False
        days[pd.Timestamp(day)]=(total if valid else np.nan,valid)
    out={}
    for w in [7,14,28]:
        use=[v for d,v in days.items() if d>=end-pd.Timedelta(days=w-1)]
        out[f'train_days{w}']=float(len(use))
        out[f'train_minutes{w}']=sum(v[0] for v in use) if use and all(v[1] for v in use) else np.nan
    out['train_minutes_per_day14']=out['train_minutes14']/out['train_days14'] if out['train_days14'] else np.nan
    out['train_gap_days28']=float((pd.Timestamp(date)-max(days)).days) if days else np.nan
    out['train_qa_days28']=float(sum(not v[1] for v in days.values()))
    support=calendar[(calendar.event_date>=start)&(calendar.event_date<=end)]
    out['train_coverage28']=float(support.supported.sum())/28
    if out['train_coverage28']<1:
        for k in c.BASIC:
            if k!='train_coverage28':out[k]=np.nan
    return out

def features():
    c.check();f=c.old.frame();d2=pd.read_parquet(c.OUT/'feature_delta_t2.parquet')
    sample=[]
    for meet in [1,3]:
        for year in [2017,2020,2024,2025,2026]:
            ids=f.index[f.meet.eq(meet)&f.year.eq(year)].to_numpy()
            sample.extend(np.random.default_rng(20261024+meet+year).choice(ids,4,replace=False).tolist())
    for mask in [d2.train_days28.eq(0),d2.train_qa_days28.gt(0),d2.train_self_history_n.lt(2)]:
        ids=np.flatnonzero(mask);sample.extend(ids[:4].tolist())
    sample=sorted(set(sample));selected=f.iloc[sample]
    pairs=selected[['meet','horse_id']].drop_duplicates();con=duckdb.connect(str(c.CORE),read_only=True);con.register('sample_pairs',pairs)
    raw=con.execute("""SELECT cast(t.meet AS INTEGER) meet,t.official_horse_id horse_id,t.event_date,
        t.started_at_raw,t.ended_at_raw,t.duration_seconds_raw,t.qa_flags_json
        FROM daily_training_raw t JOIN sample_pairs s ON cast(t.meet AS INTEGER)=s.meet AND t.official_horse_id=s.horse_id
        JOIN training_date_coverage v ON v.dataset=t.dataset AND v.meet=t.meet AND v.event_date=t.event_date
        AND v.selected_capture_id=t.capture_id
        WHERE v.coverage_status='complete_rows' AND NOT v.inventory_count_mismatch""").df()
    calendar=con.sql("""SELECT cast(meet AS INTEGER) meet,event_date,
        coverage_status IN ('complete_rows','complete_zero_rows') AND NOT inventory_count_mismatch supported
        FROM training_date_coverage WHERE dataset='daily_training'""").df();con.close()
    anchors=b.source_anchors();raw_groups={k:g for k,g in raw.groupby(['meet','horse_id'])}
    anchor_groups={k:g.race_date for k,g in anchors.groupby(['meet','horse_id'])}
    checks=0;max_error=0.;future_checks=0
    for lag in [2,7]:
        d=pd.read_parquet(c.OUT/f'feature_delta_t{lag}.parquet')
        for row in selected.itertuples():
            key=(row.meet,row.horse_id);r=raw_groups.get(key,raw.iloc[:0]);cal=calendar[calendar.meet.eq(row.meet)]
            z=raw_basic(r,row.race_date,lag,cal)
            pdays=anchor_groups[key];pdays=pdays[pdays<=row.race_date-pd.Timedelta(days=lag)].iloc[-3:]
            past=[raw_basic(r,date,lag,cal) for date in pdays]
            values=np.array([[p[k] for k in c.PERSONAL_SOURCE] for p in past],float).reshape(-1,6)
            values=values[np.isfinite(values).all(axis=1)];n=len(values)
            for j,k in enumerate(c.PERSONAL_SOURCE):z[k+'_delta_self3']=z[k]-values[:,j].mean() if n>=2 else np.nan
            z['train_self_history_n']=n;z['train_minutes14_self_sd3']=float(values[:,1].std()) if n>=2 else np.nan
            for k in c.BASIC+c.PERSONAL:
                expected=z[k];actual=float(d.loc[row.Index,k]);checks+=1
                if not math.isfinite(expected):assert np.isnan(actual),(lag,row.race_key,k,expected,actual)
                else:
                    err=abs(expected-actual);max_error=max(max_error,err);assert err<1e-8,(lag,row.race_key,k,expected,actual)
            # A synthetic future event cannot alter the independent cutoff calculation.
            bogus=pd.DataFrame([{'meet':row.meet,'horse_id':row.horse_id,'event_date':row.race_date,
                'started_at_raw':'future_start','ended_at_raw':'future_end','duration_seconds_raw':'7200','qa_flags_json':'[]'}])
            mutated=raw_basic(pd.concat([r,bogus],ignore_index=True),row.race_date,lag,cal)
            for k in c.BASIC:assert np.isclose(z[k],mutated[k],equal_nan=True)
            future_checks+=1
    result={'status':'passed','sample_starts':len(sample),'sample_raw_rows':len(raw),'feature_value_checks':checks,
        'max_error':max_error,'future_training_mutation_checks':future_checks,'source_event_cutoff_verified':True,
        'historical_publication_time_verified':False,'verifier_sha256':c.sha(__file__)}
    c.save(c.OUT/'feature_verification.json',result);print(result,flush=True)

def models():
    c.check();assert json.loads((c.OUT/'feature_verification.json').read_text())['status']=='passed'
    contract=json.loads((c.OUT/'feature_contract.json').read_text())
    for name,h in contract['files'].items():assert c.sha(c.ROOT/name)==h
    checked=0;max_score_error=0.;calibration_error=0.
    for variant,(lag,extra) in c.VARIANTS.items():
        f=c.frame(lag);cols=c.old.features()['state_gbm']+extra
        for meet in [1,3]:
            for year in [2024,2025,2026]:
                folder=c.OUT/'models'/f'{variant}_{meet}_{year}';meta=json.loads((folder/'metadata.json').read_text())
                assert meta['features']==cols and meta['train_end_year']==year-2 and meta['calibration_year']==year-1
                model=lgb.Booster(model_file=str(folder/'model.txt'));assert model.feature_name()==cols
                assert c.sha(folder/'model.txt')==meta['model_sha256']
                s=pd.read_parquet(folder/'scores.parquet');one=f.set_index('row_number').loc[s.row_number].copy()
                assert one.meet.eq(meet).all() and one.year.isin([year-1,year]).all()
                x,_=c.old.base.encode(one,cols,vocabulary=meta['category_vocabulary'])
                pred=model.predict(x,raw_score=True,num_threads=4);err=float(np.max(np.abs(pred-s.score.to_numpy())))
                assert err<1e-12;max_score_error=max(max_score_error,err);checked+=len(s)
                is_cal=s.phase.eq('calibration').to_numpy();cf=one.iloc[np.flatnonzero(is_cal)].reset_index(drop=True)
                cs=pred[is_cal];temp=c.old.base.set_temperature(cf,cs)
                records=[(cs[ix],cf.iloc[ix].outcome.to_numpy()) for ix in cf.groupby('race_key',sort=False).indices.values()]
                order=c.old.prob.fit_order_temperature(records,bounds=(.35,4.))
                er=max(abs(temp-meta['temperature']),abs(order-meta['order_temperature']));assert er<1e-9
                calibration_error=max(calibration_error,er)
                print('Verified model',variant,meet,year,flush=True)
    r=pd.read_parquet(c.OUT/'race_metrics.parquet');p=pd.read_parquet(c.OUT/'runner_probabilities.parquet')
    t=pd.read_parquet(c.OUT/'tickets.parquet');base=c.old.frame();base=base[base.year>=2024]
    incumbent=pd.read_parquet(c.PREV/'outputs/race_metrics.parquet');incumbent=incumbent[incumbent.variant.eq('state_gbm')]
    assert len(incumbent)==4799 and incumbent.axis_top3.sum()==3051
    assert r.coherence_max_error.max()<1e-9
    cohort=set(map(tuple,base[c.KEY].to_numpy()));axis_checks=0;prob_error=0.
    for variant,(lag,_) in c.VARIANTS.items():
        rr=r[r.variant.eq(variant)];pp=p[p.variant.eq(variant)];tt=t[t.variant.eq(variant)]
        assert len(rr)==4799 and set(rr.race_key)==set(incumbent.race_key)
        assert len(pp)==50754 and set(map(tuple,pp[c.KEY].to_numpy()))==cohort
        assert not pp.duplicated(c.KEY).any()
        assert pp.outcome.to_numpy().tolist()==base.set_index(c.KEY).loc[pd.MultiIndex.from_frame(pp[c.KEY]),'outcome'].tolist()
        for name,total in [('win',1),('top2',2),('top3',3)]:
            e=float(np.max(np.abs(pp.groupby('race_key')[name].sum()-total)));prob_error=max(prob_error,e);assert e<1e-9
        assert (pp.win<=pp.top2+1e-10).all() and (pp.top2<=pp.top3+1e-10).all()
        assert tt.groupby(['race_key','pool']).size().eq(3).all() and set(tt.pool)=={'quinella','qpl'}
        for meet in [1,3]:
            for year in [2024,2025,2026]:
                folder=c.OUT/'models'/f'{variant}_{meet}_{year}';m=json.loads((folder/'metadata.json').read_text())
                scores=pd.read_parquet(folder/'scores.parquet').query("phase=='evaluation'").set_index('row_number').score
                one=base[base.meet.eq(meet)&base.year.eq(year)].copy();one['s']=one.row_number.map(scores)
                mm=rr.set_index('race_key');pg=pp.set_index(c.KEY)
                for key,g in one.groupby('race_key',sort=False):
                    s=g.s.to_numpy();triples=c.old.base.triples(len(g));energy=s[triples].sum(1)/m['temperature']
                    mass=np.exp(energy-energy.max());mass/=mass.sum()
                    top3=np.bincount(triples.ravel(),weights=np.repeat(mass,3),minlength=len(g))
                    saved=pg.loc[pd.MultiIndex.from_frame(g[c.KEY]),'top3'].to_numpy()
                    e=float(np.max(np.abs(top3-saved)));prob_error=max(prob_error,e);assert e<1e-10
                    axis=int(np.argsort(-np.round(top3,12),kind='stable')[0]);actual=g.iloc[axis]
                    assert mm.loc[key,'axis_program_no']==actual.program_no
                    assert mm.loc[key,'axis_top3']==int(1<=actual.outcome<=3);axis_checks+=1
    result={'status':'passed','serialized_model_predictions':checked,'max_score_error':max_score_error,
        'recomputed_calibrations':18,'max_calibration_error':calibration_error,'all_axis_decisions_checked':axis_checks,
        'max_independent_probability_error':prob_error,'source_db_and_baseline_hashes_unchanged':True,
        'operating_registry_unchanged':True,'all_candidates_same_races':4799,'runners_per_candidate':50754,
        'feature_verification_sha256':c.sha(c.OUT/'feature_verification.json'),'verifier_sha256':c.sha(__file__)}
    c.save(c.OUT/'verification.json',result);print(result,flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['features','models']);args=parser.parse_args()
    features() if args.mode=='features' else models()
