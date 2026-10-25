"""Independent arithmetic/inference and temporal audits, without new model fitting."""
import bisect,itertools,json
from datetime import date,timedelta
import numpy as np
import pandas as pd
from audit import HERE,DB,sha,save,csv
from modeling import load,features,NUM,CAT

def transform(q,record):
    a=q[NUM].to_numpy(copy=True);missing=np.isnan(a);a=np.where(missing,np.asarray(record['numeric_imputer_statistics']),a)
    indicators=missing[:,record['numeric_indicator_indices']].astype(float)
    a=np.column_stack([a,indicators]);a=(a-record['scale_mean'])/record['scale_std']
    cats=[]
    for c,levels in zip(CAT,record['category_levels']):
        for level in levels:cats.append((q[c].to_numpy()==level).astype(float))
    if cats:a=np.column_stack([a]+cats)
    return a@np.asarray(record['coef']).reshape(-1)+float(np.asarray(record['intercept']).reshape(-1)[0])

def independent_marginals(q,z,tau):
    p=np.zeros(len(q))
    for _,inds in q.groupby('race_id',sort=False).indices.items():
        x=z[inds]/tau;w=np.exp(x-x.max());n=len(w);den=0.;num=np.zeros(n)
        for trip in itertools.combinations(range(n),3):
            mass=np.prod(w[list(trip)]);den+=mass
            for i in trip:num[i]+=mass
        p[inds]=num/den
    return p

def main(output):
    out=HERE/output
    assert out.parent==HERE and out.name.startswith('verification_')
    out.mkdir(exist_ok=False)
    d,h=load();checks={}
    summary=json.loads((HERE/'audit/summary.json').read_text());checks['database_unchanged']=sha(DB)==summary['database_sha256'] and DB.stat().st_size==summary['bytes'] and DB.stat().st_mtime_ns==summary['mtime_ns']
    protected=[]
    for r in json.loads((HERE/'audit/reference_manifest.json').read_text()):
        if not r['path'].startswith(str(HERE)):protected.append({'path':r['path'],'unchanged':sha(r['path'])==r['sha256']})
    checks['all_references_and_jeju_models_unchanged']=all(x['unchanged'] for x in protected)
    save(out/'protected_reference_check.json',protected)
    checks['contract_lock_valid']=sha(HERE/'RESEARCH_CONTRACT.md')==json.loads((HERE/'contract_lock.json').read_text())['sha256']
    history_ok=True;count=0
    valid_groups={k:g for k,g in d[d.valid].groupby(['horse_id','race_distance_m'])}
    for (horse,dist),targets in d[d.year>=2017].groupby(['horse_id','race_distance_m']):
        g=valid_groups.get((horse,dist),d.iloc[:0]).rename_axis(None)
        g=g.sort_values(['race_date','race_number','api_record_id']);ds=g.race_date.to_numpy();ids=g.api_record_id.to_numpy()
        for r in targets.itertuples():
            cut=(date.fromisoformat(r.race_date)-timedelta(days=2)).isoformat();n=bisect.bisect_right(ds,cut)
            history_ok &= list(ids[max(0,n-5):n])==h[str(r.api_record_id)] and n==r.same_count;count+=1
    checks['all_history_lists_are_exact_T_minus_2_recent5']=bool(history_ok);checks['history_target_rows_checked']=count
    checks['synthetic_T_minus_2_included_T_minus_1_excluded']=bisect.bisect_right(['2026-09-17','2026-09-18','2026-09-19'],'2026-09-17')==1
    q=features(d,h);mut=d.copy();last=d.race_date.max();ix=d.race_date==last;mut.loc[ix,'finish_time_seconds']=999.;mut.loc[ix,'finish_position']=88;mut.loc[ix,'track_raw']='불량 (99%)'
    changed=features(mut,h)
    checks['same_day_target_outcomes_and_track_do_not_change_features']=q.loc[ix.reindex(q.index),NUM+CAT].equals(changed.loc[ix.reindex(q.index),NUM+CAT])
    ef=pd.read_csv(HERE/'analysis_02/record_effects.csv').set_index('api_record_id')
    known=ef.train_end.notna();checks['coefficient_train_end_precedes_record']=bool((ef.loc[known,'train_end']<ef.loc[known,'race_date']).all())
    checks['initial_2019_2020_not_backfilled']=bool(ef[ef.race_date<'2021-01-01'][['moisture_effect_s','month_effect_s','number_effect_s']].isna().all().all())
    gates=pd.read_csv(HERE/'analysis_02/number_coefficients.csv');checks['number_effects_average_zero']=bool(np.allclose(gates.groupby(['record_year','distance','target']).effect.mean(),0,atol=1e-10))
    checks['no_unvalidated_number_seconds_applied']=bool(ef.number_effect_s.isna().all())
    pred_errors=[];period_ok=True
    records=json.loads((HERE/'comparison_01/forecast_models.json').read_text())
    for rec in records:
        rates=rec['rates'];year=rec['year'];dist=rec['distance'];corr=sum((ef[c+'_effect_s'].fillna(0)*a for c,a in zip(['moisture','month','number'],rates)),start=pd.Series(0.,index=ef.index))
        f=features(d,h,corr);target=f[f.strict&(f.year==year)&(f.race_distance_m==dist)].sort_values(['race_date','race_number','horse_number'])
        z=transform(target,rec['top3_model']);pt=transform(target,rec['time_model']);p=independent_marginals(target,z,rec['tau'])
        tag='_'.join(str(int(a*100)) for a in rates);name=f'dev_{tag}_runner_predictions.csv' if year<=2023 else 'R0_runner_predictions.csv'
        saved=pd.read_csv(HERE/'comparison_01'/name).set_index('api_record_id').loc[target.index]
        pe=float(np.max(np.abs(p-saved.p_top3.to_numpy())));te=float(np.max(np.abs(pt-saved.predicted_time_s.to_numpy())))
        pred_errors.append({'year':year,'distance':dist,'rates':rates,'max_probability_error':pe,'max_time_error':te,'rows':len(target)})
        period_ok &= rec['train_end']<rec['cal_start']<=rec['cal_end']<target.race_date.min() and rec['train_end'][:4]<=str(year-2)
    checks['serialized_inference_matches_all_predictions']=all(r['max_probability_error']<1e-10 and r['max_time_error']<1e-9 for r in pred_errors)
    checks['forecast_train_calibration_evaluation_order']=bool(period_ok);save(out/'independent_inference_errors.json',pred_errors)
    refs=None;predictionsets=[]
    for name in ['R0','R1','R2','R3']:
        p=pd.read_csv(HERE/f'comparison_01/{name}_runner_predictions.csv');predictionsets.append(set(p.api_record_id))
        assert np.allclose(p.groupby('race_id').p_top3.sum(),3,atol=1e-9)
        assert (p.groupby('race_id').finish_position.apply(lambda x:(x<=3).sum())==3).all()
        y=(p.finish_position<=3).astype(float);ll=-y*np.log(p.p_top3)-(1-y)*np.log1p(-p.p_top3)
        assert np.allclose(ll,p.log_loss,atol=1e-10);assert np.allclose((y-p.p_top3)**2,p.brier,atol=1e-10)
        r=pd.read_csv(HERE/f'comparison_01/{name}_corrected_records.csv')
        assert np.allclose(r.corrected_time_s,r.original_time_s-r[['moisture_applied_s','month_applied_s','number_applied_s']].sum(axis=1))
        for c in ['moisture','month','number']:
            assert (r.loc[r[c+'_effect_s'].isna(),c+'_applied_s']==0).all()
        # Direct source lineage as a separate, non-overwriting artifact.
        trace=r[['api_record_id','horse_id','race_id','race_date','original_time_s','corrected_time_s']].merge(d[['api_record_id','api4_3_payload_sha256']].reset_index(drop=True),on='api_record_id',validate='one_to_one');trace['model']=name
        csv(out/f'{name}_correction_lineage.csv',trace)
    checks['identical_evaluation_population_all_variants']=all(x==predictionsets[0] for x in predictionsets)
    checks['probabilities_sum_three_and_valid_top3_labels']=True;checks['losses_and_correction_arithmetic']=True;checks['unsupported_effects_null_application_zero']=True
    for name in ['R1','R2','R3']:
        assert (pd.read_csv(HERE/f'comparison_01/{name}_runner_predictions.csv').p_top3==pd.read_csv(HERE/'comparison_01/R0_runner_predictions.csv').p_top3).all()
    checks['selected_zero_variants_exactly_equal_R0']=True
    versions={}
    for module in ['numpy','pandas','scipy','sklearn']:
        m=__import__(module);versions[module]=m.__version__
    flags={k:v for k,v in checks.items() if isinstance(v,bool)}
    assert all(flags.values()),flags
    save(out/'verification.json',{'status':'passed','checks':checks,'versions':versions,'database_sha256':sha(DB),'code_sha256':sha(HERE/'verify.py'),'independence':'separate arithmetic/inference implementation by same agent; no independent reviewer or future sample'})
    print(json.dumps(checks,ensure_ascii=False),flush=True)
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',default='verification_02');main(p.parse_args().output)
