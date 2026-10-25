"""Time-based observational validation of Jeju moisture/month normalization."""
from pathlib import Path
import json
import hashlib
import itertools
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = HERE.parent/'20261007_environment_correction_pilot_v1'
DB = ROOT/'jeju/data/jeju_native_core.sqlite3'
BANDS = ['건조','양호','다습','포화','불량']
ENV = ['band_'+b for b in BANDS[1:]] + ['sin1','cos1','sin2','cos2']
NUM = ['gap_days','weight','event_age','age_squared','log_starts','field_n','race_number']
SEED = 20261008


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(8*1024**2),b''):h.update(block)
    return h.hexdigest()


def save(name,obj):
    with (HERE/name).open('x',encoding='utf-8') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False)


def csv(name,frame):
    with (HERE/name).open('x',encoding='utf-8') as f:frame.to_csv(f,index=False)


def phase(ds):
    dt=pd.to_datetime(ds)
    return 2*np.pi*(dt.dt.dayofyear.to_numpy()-1)/np.where(dt.dt.is_leap_year,366,365)


def block_ids(ds):
    return ((pd.to_datetime(ds)-pd.Timestamp('2017-01-01')).dt.days//84).to_numpy()


def get_data():
    d=pd.read_csv(OLD/'audit/source_rows.csv',dtype={'horse_id':str},low_memory=False)
    d['field_n']=d.groupby('race_id').api_record_id.transform('size')
    q=d[d.strict & d.year.ge(2017) & d.race_distance_m.isin([1000,1110])].copy()
    q['event_age']=pd.to_numeric(q.age_at_race_raw,errors='coerce')
    q['age_squared']=q.event_age**2;q['weight']=q.carried_weight_kg
    q['log_starts']=np.log1p(q.observed_starts)
    q['grade']=q.rank_class_raw.fillna('unknown');q['sex']=q.sex_at_race_raw.fillna('unknown')
    theta=phase(q.race_date)
    for k in [1,2]:q[f'sin{k}']=np.sin(k*theta);q[f'cos{k}']=np.cos(k*theta)
    for b in BANDS[1:]:q['band_'+b]=(q.band==b).astype(float)
    assert q.band.isin(BANDS).all() and q.race_date.max()=='2026-09-19'
    q=q.sort_values(['horse_id','race_distance_m','race_date','race_number']).reset_index(drop=True)
    prev=q.groupby(['horse_id','race_distance_m'],sort=False).shift()
    gap=(pd.to_datetime(q.race_date)-pd.to_datetime(prev.race_date)).dt.days
    keep=gap.between(7,90)&q.year.eq(prev.year)
    a=prev[keep].reset_index(drop=True);b=q[keep].reset_index(drop=True)
    pairs=pd.DataFrame({'pair_id':b.api_record_id.astype(int),'previous_api_record_id':a.api_record_id.astype(int),
        'horse_id':b.horse_id,'distance':b.race_distance_m.astype(int),'year':b.year.astype(int),
        'race_id':b.race_id,'previous_race_id':a.race_id,'race_date':b.race_date,'previous_date':a.race_date,
        'month':b.month.astype(int),'previous_month':a.month.astype(int),'band':b.band,'previous_band':a.band,
        'grade':b.grade,'previous_grade':a.grade,'sex':b.sex,'previous_sex':a.sex,
        'time':b.finish_time_seconds,'previous_time':a.finish_time_seconds,
        'api_sha':b.api4_3_payload_sha256,'previous_api_sha':a.api4_3_payload_sha256,
        'gap_days':gap[keep].to_numpy(),'y':b.finish_time_seconds-a.finish_time_seconds})
    for c in NUM[1:]+ENV:pairs[c]=b[c]-a[c]
    assert pairs[NUM+ENV+['y']].notna().all().all()
    assert pairs.pair_id.is_unique and pairs.gap_days.between(7,90).all()
    assert (pd.to_datetime(pairs.previous_date)<pd.to_datetime(pairs.race_date)).all()
    ref=q.set_index('api_record_id')
    assert (ref.loc[pairs.previous_api_record_id,'horse_id'].to_numpy()==pairs.horse_id.to_numpy()).all()
    assert (ref.loc[pairs.previous_api_record_id,'race_distance_m'].to_numpy()==pairs.distance.to_numpy()).all()
    return q,pairs


def design(train,target=None,names=None):
    target=train if target is None else target
    if names is None:
        names=NUM.copy()
        for c in ['grade','sex']:
            levels=sorted(set(train[c])|set(train['previous_'+c]))
            names += [c+'='+level for level in levels[1:]]
        names+=ENV
    cols=[]
    for name in names:
        if '=' in name:
            c,level=name.split('=',1)
            cols.append((target[c]==level).astype(float).to_numpy()-(target['previous_'+c]==level).astype(float).to_numpy())
        else:cols.append(target[name].to_numpy(dtype=float))
    return np.column_stack(cols),names


def fit(x,y,weights,kind='huber',max_iter=80):
    mean=np.average(x,axis=0,weights=weights)
    sd=np.sqrt(np.average((x-mean)**2,axis=0,weights=weights));sd=np.where(sd>1e-12,sd,1.)
    z=np.column_stack([np.ones(len(x)),(x-mean)/sd])
    base=np.asarray(weights,dtype=float).copy();base*=len(base)/base.sum()
    w=base.copy();penalty=np.eye(z.shape[1]);penalty[0,0]=0
    beta=np.linalg.solve(z.T@(w[:,None]*z)+penalty,z.T@(w*y))
    steps=1;converged=kind!='huber'
    if kind=='huber':
        for steps in range(1,max_iter+1):
            r=y-z@beta;scale=max(1e-10,1.4826*np.median(np.abs(r-np.median(r))))
            w=base*np.minimum(1,1.345*scale/np.maximum(np.abs(r),1e-10))
            new=np.linalg.solve(z.T@(w[:,None]*z)+penalty,z.T@(w*y))
            if np.max(np.abs(new-beta))<1e-7:
                beta=new;converged=True;break
            beta=new
    return {'beta':beta,'mean':mean,'sd':sd,'iterations':steps,'converged':converged}


def predict(model,x):return model['beta'][0]+((x-model['mean'])/model['sd'])@model['beta'][1:]


def rawcoef(model):return model['beta'][1:]/model['sd']


def record(model,names):
    return {k:v.tolist() if isinstance(v,np.ndarray) else v for k,v in model.items()}|{'columns':names}


def race_weights(g):
    return (1/g.groupby('race_id').pair_id.transform('size')).to_numpy()


def rates_key(rates):return f'F{rates[0]:.2f}_M{rates[1]:.2f}'


def fold(train,target,rates,kind='huber',label='primary'):
    assert train.race_date.max()<target.race_date.min()
    x,names=design(train);v,_=design(train,target,names)
    y=train.y.to_numpy();w=race_weights(train)
    full=fit(x,y,w,kind);coef=rawcoef(full)
    fi=np.array([i for i,n in enumerate(names) if n.startswith('band_')]);mi=np.array([i for i,n in enumerate(names) if n in ['sin1','cos1','sin2','cos2']])
    ni=np.array([i for i,n in enumerate(names) if n not in ENV])
    ft=x[:,fi]@coef[fi];mt=x[:,mi]@coef[mi]
    fv=v[:,fi]@coef[fi];mv=v[:,mi]@coef[mi]
    predictions=[];stored=[]
    for rf,rm in rates:
        nuisance=fit(x[:,ni],y-rf*ft-rm*mt,w,kind)
        nuisance_prediction=predict(nuisance,v[:,ni]);environment=rf*fv+rm*mv
        out=target[['pair_id','horse_id','distance','year','race_id','race_date','previous_date','band','previous_band','month','previous_month','y','gap_days']].copy()
        out['f_rate']=rf;out['m_rate']=rm;out['candidate']=rates_key((rf,rm));out['variant']=label
        out['moisture_difference_s']=fv;out['month_difference_s']=mv
        out['nuisance_prediction_s']=nuisance_prediction;out['predicted_difference_s']=nuisance_prediction+environment
        out['remaining_s']=out.y-out.predicted_difference_s;out['absolute_error_s']=np.abs(out.remaining_s);out['squared_error_s']=out.remaining_s**2
        out['corrected_raw_difference_s']=out.y-environment
        predictions.append(out)
        stored.append({'rates':[rf,rm],'nuisance':record(nuisance,[names[i] for i in ni])})
    models={'variant':label,'distance':int(train.distance.iloc[0]),'held_year':int(target.year.iloc[0]),'train_start':train.previous_date.min(),'train_end':train.race_date.max(),'train_pairs':len(train),'test_pairs':len(target),'environment':record(full,names),'nuisance_models':stored}
    return pd.concat(predictions,ignore_index=True),models


def races(pred):
    return pred.groupby(['variant','candidate','f_rate','m_rate','distance','year','race_id','race_date'],as_index=False).agg(mae=('absolute_error_s','mean'),mse=('squared_error_s','mean'),pairs=('pair_id','size'))


def paired_stats(a,b,reps=1000):
    z=a[['race_id','race_date','mae','mse']].merge(b[['race_id','mae','mse']],on='race_id',suffixes=('','_base'),validate='one_to_one')
    assert len(z)==len(a)==len(b)
    z['delta']=z.mae-z.mae_base;z['block']=block_ids(z.race_date)
    agg=z.groupby('block').delta.agg(['sum','size']);rng=np.random.default_rng(SEED)
    ix=rng.integers(0,len(agg),(reps,len(agg)));draw=agg['sum'].to_numpy()[ix].sum(axis=1)/agg['size'].to_numpy()[ix].sum(axis=1)
    return {'delta_mae_s':float(z.delta.mean()),'ci_lo':float(np.quantile(draw,.025)),'ci_hi':float(np.quantile(draw,.975)),
        'se':float(draw.std(ddof=1)),'blocks':len(agg),'races':len(z),'rmse_s':float(np.sqrt(z.mse.mean())),
        'base_rmse_s':float(np.sqrt(z.mse_base.mean())),'mae_s':float(z.mae.mean()),'base_mae_s':float(z.mae_base.mean())}


def supports(g):
    ends=pd.concat([g[['previous_race_id','previous_date','previous_band','previous_month']].rename(columns={'previous_race_id':'race_id','previous_date':'race_date','previous_band':'band','previous_month':'month'}),g[['race_id','race_date','band','month']]]).drop_duplicates('race_id')
    ends['year']=pd.to_datetime(ends.race_date).dt.year
    band={b:{'races':int((ends.band==b).sum()),'days':int(ends[ends.band==b].race_date.nunique()),'years':int(ends[ends.band==b].year.nunique())} for b in BANDS}
    month={m:{'races':int((ends.month==m).sum()),'days':int(ends[ends.month==m].race_date.nunique()),'years':int(ends[ends.month==m].year.nunique())} for m in range(1,13)}
    return band,month


def effect_vector(names,band,dt,rates=(1.,1.)):
    v=np.zeros(len(names));theta=phase(pd.Series([dt]))[0]
    if band!='건조':v[names.index('band_'+band)]=rates[0]
    for k in [1,2]:
        v[names.index(f'sin{k}')]=rates[1]*np.sin(k*theta)
        v[names.index(f'cos{k}')]=rates[1]*np.cos(k*theta)
    return v


def bootstrap_coefficients(g,x,names,reps=100):
    result={};base=race_weights(g);rng=np.random.default_rng(SEED)
    for mode in ['block12weeks','horse']:
        cluster=block_ids(g.race_date) if mode=='block12weeks' else g.horse_id.to_numpy()
        levels,code=np.unique(cluster,return_inverse=True);draws=[];notconverged=0
        for j in range(reps):
            count=np.bincount(rng.integers(0,len(levels),len(levels)),minlength=len(levels));w=base*count[code]
            m=fit(x,g.y.to_numpy(),w);draws.append(rawcoef(m));notconverged+=not m['converged']
        result[mode]={'coefficients':np.asarray(draws),'clusters':len(levels),'not_converged':notconverged}
        print('Bootstrap',int(g.distance.iloc[0]),mode,reps,'not_converged',notconverged,flush=True)
    return result


def main():
    plan=json.loads((HERE/'PLAN.json').read_text())
    refs=[HERE/'PLAN.json',HERE/'analyze.py',OLD/'audit/source_rows.csv',OLD/'audit/summary.json',OLD/'audit/reference_manifest.json',OLD/'RESEARCH_CONTRACT.md',OLD/'RESULTS.md',HERE.parent/'20261008_record_normalization_objective_v1/README.md',ROOT/'jeju/AGENTS.md']
    manifest=[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in refs];save('source_manifest.json',manifest)
    st=DB.stat();dbsha=sha(DB);assert dbsha==json.loads((OLD/'audit/summary.json').read_text())['database_sha256']
    q,p=get_data();csv('pair_source_lineage.csv',p)
    csv('annual_support.csv',p.groupby(['distance','year']).agg(pairs=('pair_id','size'),horses=('horse_id','nunique'),races=('race_id','nunique'),days=('race_date','nunique')).reset_index())
    grid=list(itertools.product(plan['rates'],repeat=2));dev=[];models=[]
    for dist in [1000,1110]:
        for year in [2022,2023]:
            tr=p[(p.distance==dist)&(p.year<year)];te=p[(p.distance==dist)&(p.year==year)]
            out,m=fold(tr,te,grid);dev.append(out);models.append(m);print('Development',dist,year,flush=True)
    dev=pd.concat(dev,ignore_index=True);dr=races(dev);csv('development_race_metrics.csv',dr)
    selected={};selection=[];candidate_stats=[]
    for dist in [1000,1110]:
        r=dr[dr.distance==dist];base=r[r.candidate==rates_key((0,0))]
        means=r.groupby(['f_rate','m_rate']).mae.mean();best=tuple(means.idxmin());bestframe=r[r.candidate==rates_key(best)];near=[]
        for rf,rm in grid:
            a=r[r.candidate==rates_key((rf,rm))];s=paired_stats(a,base);b=paired_stats(a,bestframe)
            candidate_stats.append({'distance':dist,'f_rate':rf,'m_rate':rm,**s,'delta_to_best':b['delta_mae_s'],'se_to_best':b['se']})
            if b['delta_mae_s']<=b['se']+1e-12:near.append((rf,rm))
        chosen=min(near,key=lambda x:(sum(x),x[0],x[1]));s=paired_stats(r[r.candidate==rates_key(chosen)],base)
        passed=chosen!=(0,0) and s['ci_hi']<0 and s['rmse_s']<=s['base_rmse_s']
        selected[dist]=chosen if passed else (0.,0.)
        selection.append({'distance':dist,'best_rates':list(best),'one_se_smallest':list(chosen),'development_gate_passed':bool(passed),'selected_rates':list(selected[dist]),**s})
    csv('development_candidates.csv',pd.DataFrame(candidate_stats))
    save('selection_locked_before_confirmation.json',{'development_years':[2022,2023],'primary_metric':'race_equal_MAE_pair_time_change','selection':selection})
    print('Selection locked',selected,flush=True)
    confirm=[];sens=[]
    for dist in [1000,1110]:
        choices=list(dict.fromkeys([(0.,0.),selected[dist],(1.,1.),(.25,.25),(.5,.5)]))
        for year in [2024,2025,2026]:
            tr=p[(p.distance==dist)&(p.year<year)];te=p[(p.distance==dist)&(p.year==year)]
            out,m=fold(tr,te,choices);confirm.append(out);models.append(m)
            for label,kind,gap,modern in [('ols','ols',90,False),('gap45','huber',45,False),('gap60','huber',60,False),('modern2019','huber',90,True)]:
                tt=tr[tr.gap_days<=gap];vv=te[te.gap_days<=gap]
                if modern:tt=tt[tt.year>=2019]
                su,sm=fold(tt,vv,list(dict.fromkeys([(0.,0.),selected[dist]])),kind,label);sens.append(su);models.append(sm)
            print('Confirmation and sensitivity',dist,year,flush=True)
    confirm=pd.concat(confirm,ignore_index=True);sens=pd.concat(sens,ignore_index=True)
    csv('confirmation_pair_predictions.csv',confirm);csv('sensitivity_pair_predictions.csv',sens)
    cr=races(confirm);sr=races(sens);csv('confirmation_race_metrics.csv',cr);csv('sensitivity_race_metrics.csv',sr)
    stats=[];gates=[]
    for dist in [1000,1110]:
        r=cr[cr.distance==dist]
        for years,label in [([2024,2025],'2024_2025'),([2026],'2026_partial'),([2024,2025,2026],'2024_2026'),([2024],'2024'),([2025],'2025')]:
            rr=r[r.year.isin(years)];base=rr[rr.candidate==rates_key((0,0))]
            for key,a in rr.groupby('candidate'):
                stats.append({'variant':'primary','distance':dist,'period':label,'candidate':key,'f_rate':a.f_rate.iloc[0],'m_rate':a.m_rate.iloc[0],**paired_stats(a,base)})
        sel=next(s for s in selection if s['distance']==dist)
        rows=[s for s in stats if s['distance']==dist and s['candidate']==rates_key(selected[dist])]
        lookup={s['period']:s for s in rows}
        passed=bool(sel['development_gate_passed'] and lookup['2024_2025']['ci_hi']<0 and all(lookup[str(y)]['delta_mae_s']<=0 for y in [2024,2025]) and lookup['2026_partial']['delta_mae_s']<=0)
        gates.append({'distance':dist,'selected_rates':list(selected[dist]),'confirmation_gate_passed':passed,'status':'provisional_time_normalization_reference' if passed else 'descriptive_candidate_only_insufficient_confirmation'})
        for variant,rs in sr[sr.distance==dist].groupby('variant'):
            for years,label in [([2024,2025],'2024_2025'),([2026],'2026_partial'),([2024,2025,2026],'2024_2026')]:
                rr=rs[rs.year.isin(years)];base=rr[rr.candidate==rates_key((0,0))]
                key=rates_key(selected[dist]);a=rr[rr.candidate==key]
                stats.append({'variant':variant,'distance':dist,'period':label,'candidate':key,'f_rate':selected[dist][0],'m_rate':selected[dist][1],**paired_stats(a,base)})
    csv('confirmation_comparisons.csv',pd.DataFrame(stats));save('decision.json',{'objective':'time_normalization','distances':gates,'top3_used':False,'operational_change':False,'counterfactual_truth_observed':False})
    # Held-period conditional diagnostics, kept complete even if rates select zero.
    diag=[]
    for (dist,key),g in confirm.groupby(['distance','candidate']):
        for axis in ['band','month']:
            for val,a in g.groupby(axis):
                race=a.groupby('race_id').remaining_s.mean()
                diag.append({'distance':dist,'candidate':key,'axis':axis,'value':str(val),'pairs':len(a),'races':len(race),'mean_remaining_s':race.mean(),'mean_raw_corrected_difference_s':a.corrected_raw_difference_s.mean()})
        for changed,a in g.groupby(g.band!=g.previous_band):
            rr=a.groupby('race_id').absolute_error_s.mean()
            diag.append({'distance':dist,'candidate':key,'axis':'band_changed','value':str(changed),'pairs':len(a),'races':len(rr),'mean_absolute_error_s':rr.mean()})
    csv('condition_diagnostics.csv',pd.DataFrame(diag))
    # Latest descriptive coefficients and joint bootstrap intervals.
    latest=[];curves=[];bootstore=[];examples=[];latestmodels=[]
    for dist in [1000,1110]:
        g=p[p.distance==dist];x,names=design(g);full=fit(x,g.y.to_numpy(),race_weights(g));coef=rawcoef(full)
        boot=bootstrap_coefficients(g,x,names);ols=fit(x,g.y.to_numpy(),race_weights(g),'ols');bands,months=supports(g)
        latestmodels.append({'distance':dist,'train_start':g.previous_date.min(),'train_end':g.race_date.max(),'pairs':len(g),'model':record(full,names),'ols':record(ols,names),'support_bands':bands,'support_months':months})
        bootstore.append({'distance':dist,'columns':names,**{k:{'raw_coefficients':v['coefficients'].tolist(),'clusters':v['clusters'],'not_converged':v['not_converged']} for k,v in boot.items()}})
        def summarize(v):
            vals=boot['block12weeks']['coefficients']@v;hv=boot['horse']['coefficients']@v
            return {'effect_s':float(v@coef),'ci_lo':float(np.quantile(vals,.025)),'ci_hi':float(np.quantile(vals,.975)),'horse_ci_lo':float(np.quantile(hv,.025)),'horse_ci_hi':float(np.quantile(hv,.975)),'ols_effect_s':float(v@rawcoef(ols))}
        for band in BANDS:
            v=effect_vector(names,band,'2025-01-01',(1.,0.));supported=all(bands[b]['races']>=40 and bands[b]['days']>=30 and bands[b]['years']>=2 for b in [band,'건조'])
            latest.append({'distance':dist,'component':'moisture','band':band,'month':None,'supported':supported,**bands[band],**summarize(v)})
        for month in range(1,13):
            dt=f'2025-{month:02d}-15';v=effect_vector(names,'건조',dt,(0.,1.));sp=months[month];supported=sp['races']>=20 and sp['days']>=15 and sp['years']>=2
            latest.append({'distance':dist,'component':'month','band':None,'month':month,'supported':supported,**sp,**summarize(v)})
            for band in BANDS:
                vv=effect_vector(names,band,dt);s=summarize(vv);ok=supported and all(bands[b]['races']>=40 and bands[b]['days']>=30 and bands[b]['years']>=2 for b in [band,'건조'])
                curves.append({'distance':dist,'month':month,'band':band,'date_reference':dt,'supported':ok,'status':'descriptive_unshrunk_candidate','reference':'dry_and_annual_mean_month','adjustment_s':-s['effect_s'],'adjustment_ci_lo':-s['ci_hi'],'adjustment_ci_hi':-s['ci_lo'],'example_raw_s':80. if dist==1000 else 90.,'example_normalized_s':(80. if dist==1000 else 90.)-s['effect_s'],**s})
        actual=q[(q.race_distance_m==dist)&(q.year==2026)].sort_values(['race_date','race_number','horse_number'])
        # One original race record per band; selection is deterministic, not based on effect size.
        for band,a in actual.groupby('band',sort=False):
            r=a.iloc[0];v=effect_vector(names,band,r.race_date);s=summarize(v)
            vf=effect_vector(names,band,r.race_date,(1.,0.));vm=effect_vector(names,band,r.race_date,(0.,1.))
            examples.append({'distance':dist,'api_record_id':int(r.api_record_id),'horse_id':r.horse_id,'race_id':r.race_id,'race_date':r.race_date,'band':band,'moisture':r.moisture,'raw_time_s':r.finish_time_seconds,'moisture_adjustment_s':-float(vf@coef),'month_adjustment_s':-float(vm@coef),'total_adjustment_s':-s['effect_s'],'normalized_time_s':r.finish_time_seconds-s['effect_s'],'adjustment_ci_lo':-s['ci_hi'],'adjustment_ci_hi':-s['ci_lo'],'status':'latest_descriptive_unshrunk_candidate_not_historical_prediction','api_sha':r.api4_3_payload_sha256})
        print('Latest model',dist,flush=True)
    coeff=pd.DataFrame(latest)
    for c in ['effect_s','ci_lo','ci_hi','horse_ci_lo','horse_ci_hi','ols_effect_s']:coeff.loc[~coeff.supported,c]=np.nan
    curve=pd.DataFrame(curves)
    for c in ['effect_s','ci_lo','ci_hi','horse_ci_lo','horse_ci_hi','ols_effect_s','adjustment_s','adjustment_ci_lo','adjustment_ci_hi','example_normalized_s']:curve.loc[~curve.supported,c]=np.nan
    csv('latest_coefficients.csv',coeff);csv('latest_joint_reference.csv',curve);csv('real_record_examples.csv',pd.DataFrame(examples))
    save('rolling_models.json',models);save('latest_models.json',latestmodels);save('coefficient_bootstrap.json',bootstore)
    assert all(sha(Path(r['path']))==r['sha256'] for r in manifest)
    assert sha(DB)==dbsha and (DB.stat().st_size,DB.stat().st_mtime_ns)==(st.st_size,st.st_mtime_ns)
    assert np.allclose(curve.adjustment_s,-curve.effect_s,equal_nan=True)
    assert all(m['train_end']<str(m['held_year'])+'-01-01' for m in models)
    save('verification.json',{'status':'passed','all_sources_and_database_unchanged':True,'database_sha256':dbsha,'pairs':len(p),'same_horse_exact_distance_and7to90day_same_year_checked':True,'rolling_training_ends_before_held_year':True,'no_top3_objective_or_target':True,'joint_effect_and_adjustment_sign_checked':True,'bootstrap_rate_selection_uncertainty_included':False,'all_rolling_models_converged':all(m['environment']['converged'] and all(n['nuisance']['converged'] for n in m['nuisance_models']) for m in models)})
    print(pd.DataFrame(selection).to_string(index=False),flush=True)
    print(pd.DataFrame(stats).query("variant=='primary' and period in ['2024_2025','2026_partial']").to_string(index=False),flush=True)
    print(coeff.to_string(index=False),flush=True)


if __name__=='__main__':main()
