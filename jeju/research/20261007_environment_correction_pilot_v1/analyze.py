"""Annual out-of-year expectations, environment and within-race number estimates."""
import argparse, json
import numpy as np
import pandas as pd
from audit import HERE, DB, BANDS, sha, save, csv
from modeling import load,features,fit,model_record,design,ridge_solve,cluster_cov,contrast,interval,phase,paired_ci,SEED

def aggregate(q,residual,wide=False,mean=False):
    a=q.copy();a['residual']=residual
    a=a[a.valid & (a.same_count>0) & a.band.notna() & ((a.strict) if not wide else True)]
    agg=a.groupby('race_id').agg(race_date=('race_date','first'),year=('year','first'),month=('month','first'),distance=('race_distance_m','first'),band=('band','first'),moisture=('moisture','first'),grade=('grade','first'),race_number=('race_number','first'),field_n=('field_n','first'),event_age=('event_age','mean'),weight=('weight','mean'),log_starts=('log_starts','mean'),hist_mean=('hist_mean','mean'),eligible_n=('api_record_id','size'),residual=('residual','mean' if mean else 'median'),raw_time=('finish_time_seconds','mean'))
    agg['missing_fraction']=1-agg.eligible_n/agg.field_n
    return agg[agg.eligible_n>=4].reset_index()

def supports(g,band,min_days=30):
    x=g[g.band==band];dry=g[g.band==BANDS[0]]
    return dict(races=len(x),days=x.race_date.nunique(),years=x.year.nunique(),dry_races=len(dry),dry_days=dry.race_date.nunique(),dry_years=dry.year.nunique(),common_months=len(set(x.month)&set(dry.month)),common_grades=len(set(x.grade)&set(dry.grade)),supported=len(x)>=40 and x.race_date.nunique()>=min_days and x.year.nunique()>=2 and len(dry)>=40 and dry.race_date.nunique()>=min_days and dry.year.nunique()>=2 and len(set(x.month)&set(dry.month))>=6 and bool(set(x.grade)&set(dry.grade)))

def envfit(g,kind='median'):
    X,spec=design(g);y=g.residual.to_numpy();beta,bread=ridge_solve(X,y)
    w=None
    if kind=='huber':
        for _ in range(100):
            r=y-X@beta;scale=max(np.finfo(float).eps,1.4826*np.median(np.abs(r-np.median(r))))
            w=np.minimum(1,1.345*scale/np.maximum(np.abs(r),np.finfo(float).eps))
            new,bread=ridge_solve(X,y,weights=w)
            if np.max(np.abs(new-beta))<1e-8:beta=new;break
            beta=new
    cov=cluster_cov(X,y-X@beta,bread,g.race_date,w)
    return beta,spec,cov

def gatefit(g,target='time'):
    X,spec=design(g,mode='gate');y=g.finish_time_seconds.to_numpy() if target=='time' else (g.finish_position<=3).astype(float).to_numpy()
    y=y-pd.Series(y,index=g.index).groupby(g.race_id).transform('mean').to_numpy()
    beta,bread=ridge_solve(X,y,intercept=False)
    cov=cluster_cov(X,y-X@beta,bread,g.race_date)
    horse_cov=cluster_cov(X,y-X@beta,bread,g.horse_id)
    return beta,spec,cov,horse_cov

def gate_vector(spec,number):
    raw=[]
    for k in range(1,11):raw.append(contrast(spec,f'number_{k}') if k<10 else np.zeros(len(spec['columns'])))
    return raw[number-1]-np.mean(raw,axis=0)

def gate_validation(g,year):
    train=g[g.year<=year-2];val=g[g.year==year-1]
    info={'validation_year':year-1,'train_end':f'{year-2}-12-31','train_races':train.race_id.nunique(),'validation_races':val.race_id.nunique(),'validated':False}
    if train.race_id.nunique()<100 or train.race_date.nunique()<30 or train.year.nunique()<2 or val.race_id.nunique()<30:return info
    beta,spec,_,_=gatefit(train)
    X,_=design(train,mode='gate',spec=spec);V,_=design(val,mode='gate',spec=spec)
    inds=[i for i,c in enumerate(spec['columns']) if not c.startswith('number_')]
    yt=train.finish_time_seconds-train.groupby('race_id').finish_time_seconds.transform('mean')
    yv=val.finish_time_seconds-val.groupby('race_id').finish_time_seconds.transform('mean')
    b,_=ridge_solve(X[:,inds],yt.to_numpy(),intercept=False)
    z=val[['race_id','race_date']].copy();z['with_gate']=np.abs(yv.to_numpy()-V@beta);z['without_gate']=np.abs(yv.to_numpy()-V[:,inds]@b)
    a=z.groupby(['race_id','race_date']).with_gate.mean().reset_index(name='log_loss');base=z.groupby('race_id').without_gate.mean().reset_index(name='log_loss')
    ci=paired_ci(a,base);info.update(ci);info['validated']=ci['hi']<0
    return info

def main(output):
    assert sha(HERE/'RESEARCH_CONTRACT.md')==json.loads((HERE/'contract_lock.json').read_text())['sha256']
    out=HERE/output
    assert out.parent==HERE and out.name.startswith('analysis_')
    out.mkdir(exist_ok=False)
    d,h=load();q=features(d,h).sort_values(['race_date','race_number','horse_number'])
    residual=pd.Series(np.nan,index=q.index);alt3=residual.copy();modern=residual.copy();modelinfo=[]
    q3=features(d,h,n_recent=3).reindex(q.index)
    for year in range(2019,2027):
        for dist in [1000,1110]:
            train=q[(q.year<year)&q.strict&(q.race_distance_m==dist)];target=q[(q.year==year)&q.valid&(q.race_distance_m==dist)]
            assert train.race_date.max()<target.race_date.min()
            model=fit(train,'time');residual.loc[target.index]=target.finish_time_seconds-model.predict(target)
            rec={'year':year,'distance':dist,'train_rows':len(train),'train_races':train.race_id.nunique(),'train_end':train.race_date.max(),'target_rows':len(target),'model':model_record(model)};modelinfo.append(rec)
            m3=fit(q3.loc[train.index],'time');alt3.loc[target.index]=target.finish_time_seconds-m3.predict(q3.loc[target.index])
            mt=train[train.year>=2019]
            if len(mt)>=200:
                mm=fit(mt,'time');modern.loc[target.index]=target.finish_time_seconds-mm.predict(target)
        print('Out-of-year expectation',year,flush=True)
    save(out/'expectation_models.json',modelinfo)
    q['ooy_residual']=residual;csv(out/'out_of_year_residuals.csv',q[['api_record_id','race_id','horse_id','race_date','race_distance_m','same_count','finish_time_seconds','ooy_residual']])
    race=aggregate(q,residual);csv(out/'race_residuals.csv',race)
    variants={'median':race,'huber':race,'race_mean':aggregate(q,residual,mean=True),'recent3':aggregate(q3,alt3),'modern_expectation':aggregate(q,modern),'broader_normal_times':aggregate(q,residual,wide=True)}
    coefficient_rows=[];models={};month_rows=[];gate_rows=[];gate_models={};gate_checks=[];bootstrap_rows=[]
    gateq=q[q.strict&(q.field_n==10)&q.horse_number.between(1,10)].copy()
    for year in range(2021,2027):
        for dist in [1000,1110]:
            primary=race[(race.year<year)&(race.distance==dist)&(race.year>=2019)]
            for kind,races in variants.items():
                g=races[(races.year<year)&(races.distance==dist)&(races.year>=2019)].dropna(subset=['residual'])
                if len(g)<40:continue
                beta,spec,cov=envfit(g,kind)
                if kind=='median':models[(year,dist)]={'beta':beta,'spec':spec,'cov':cov,'g':g}
                for band in BANDS:
                    support=supports(g,band);v=np.zeros(len(beta)) if band==BANDS[0] else contrast(spec,'band_'+band)
                    point,lo,hi=interval(v,beta,cov)
                    coefficient_rows.append(dict(record_year=year,train_end=f'{year-1}-12-31',distance=dist,variant=kind,band=band,effect_s=point,ci_lo=lo,ci_hi=hi,support_20days=supports(g,band,20)['supported'],support_40days=supports(g,band,40)['supported'],**support))
                if kind=='median':
                    for month in range(1,13):
                        sub=g[g.month==month]
                        # Descriptive monthly reference: phase at monthly midpoint; correction uses actual day.
                        p=phase(pd.Series([f'2025-{month:02d}-15']))[0]
                        v=contrast(spec,{f'{fn}{k}':float(np.sin(k*p) if fn=='sin' else np.cos(k*p)) for k in [1,2] for fn in ['sin','cos']})
                        pt,lo,hi=interval(v,beta,cov)
                        month_rows.append(dict(record_year=year,distance=dist,month=month,effect_s=pt,ci_lo=lo,ci_hi=hi,races=len(sub),days=sub.race_date.nunique(),years=sub.year.nunique(),supported=len(sub)>=20 and sub.race_date.nunique()>=15 and sub.year.nunique()>=2))
                    if year==2026:
                        X,_=design(g,spec=spec);ys=g.residual.to_numpy();dates=np.unique(g.race_date);rng=np.random.default_rng(SEED);bs=[]
                        for _ in range(200):
                            counts=pd.Series(rng.choice(dates,len(dates),replace=True)).value_counts();w=g.race_date.map(counts).fillna(0).to_numpy();b,_=ridge_solve(X,ys,weights=w);bs.append(b)
                        for band in BANDS[1:]:
                            values=np.array(bs)@contrast(spec,'band_'+band)
                            bootstrap_rows.append(dict(distance=dist,band=band,reps=200,lo=float(np.quantile(values,.025)),hi=float(np.quantile(values,.975)),method='date_resample_frozen_expectations_and_scaling'))
            g=gateq[(gateq.year>=2019)&(gateq.year<year)&(gateq.race_distance_m==dist)]
            check=gate_validation(g,year);check.update(record_year=year,distance=dist);gate_checks.append(check)
            if len(g)>=100:
                for target in ['time','top3']:
                    b,s,c,hc=gatefit(g,target)
                    if target=='time':gate_models[(year,dist)]={'beta':b,'spec':s,'cov':c,'g':g,'validated':check['validated']}
                    for number in range(1,11):
                        v=gate_vector(s,number);pt,lo,hi=interval(v,b,c);_,hlo,hhi=interval(v,b,hc);scale=100 if target=='top3' else 1
                        gate_rows.append(dict(record_year=year,distance=dist,target=target,number=number,effect=pt*scale,ci_lo=lo*scale,ci_hi=hi*scale,horse_ci_lo=hlo*scale,horse_ci_hi=hhi*scale,unit='percentage_points' if target=='top3' else 'seconds',races=g.race_id.nunique(),days=g.race_date.nunique(),years=g.year.nunique(),prior_seconds_validated=check['validated']))
            print('Environment and number coefficients',year,dist,flush=True)
    coeff=pd.DataFrame(coefficient_rows);months=pd.DataFrame(month_rows);gates=pd.DataFrame(gate_rows)
    csv(out/'moisture_coefficients.csv',coeff);csv(out/'month_coefficients.csv',months);csv(out/'number_coefficients.csv',gates);save(out/'number_seconds_validation.json',gate_checks);save(out/'coefficient_date_bootstrap.json',bootstrap_rows)
    save(out/'environment_models.json',[{'record_year':y,'distance':dist,'beta':m['beta'].tolist(),'design':m['spec'],'day_cluster_cov':m['cov'].tolist()} for (y,dist),m in models.items()])
    effects=[]
    source=d[d.valid&d.race_distance_m.isin([1000,1110])]
    for r in source.itertuples():
        year=int(r.year);dist=int(r.race_distance_m);m=models.get((year,dist));entry={'api_record_id':r.api_record_id,'horse_id':r.horse_id,'race_id':r.race_id,'race_date':r.race_date,'distance':dist,'original_time_s':r.finish_time_seconds,'band':r.band if pd.notna(r.band) else None,'coefficient_version':f'JEJU_ENV_PILOT_Y{year}' if m else None,'train_end':f'{year-1}-12-31' if m else None}
        for component in ['moisture','month','number']:
            entry.update({component+'_effect_s':None,component+'_ci_lo':None,component+'_ci_hi':None,component+'_support_races':0,component+'_support_days':0,component+'_status':'not_estimated_raw_fallback'})
        if m:
            g=m['g'];bandrow=coeff[(coeff.record_year==year)&(coeff.distance==dist)&(coeff.variant=='median')&(coeff.band==r.band)]
            if len(bandrow):
                a=bandrow.iloc[0];entry.update(moisture_support_races=int(a.races),moisture_support_days=int(a.days))
                if a.supported:entry.update(moisture_effect_s=float(a.effect_s),moisture_ci_lo=float(a.ci_lo),moisture_ci_hi=float(a.ci_hi),moisture_status='supported_reference' if r.band==BANDS[0] else 'supported_candidate')
                else:entry['moisture_status']='insufficient_support_raw_fallback'
            mr=months[(months.record_year==year)&(months.distance==dist)&(months.month==r.month)].iloc[0]
            entry.update(month_support_races=int(mr.races),month_support_days=int(mr.days))
            if mr.supported:
                p=phase(pd.Series([r.race_date]))[0];v=contrast(m['spec'],{f'{fn}{k}':float(np.sin(k*p) if fn=='sin' else np.cos(k*p)) for k in [1,2] for fn in ['sin','cos']});pt,lo,hi=interval(v,m['beta'],m['cov'])
                entry.update(month_effect_s=pt,month_ci_lo=lo,month_ci_hi=hi,month_status='supported_candidate')
            else:entry['month_status']='insufficient_support_raw_fallback'
            gm=gate_models.get((year,dist));gr=gates[(gates.record_year==year)&(gates.distance==dist)&(gates.target=='time')&(gates.number==r.horse_number)]
            if r.strict and r.field_n==10 and gm and len(gr):
                a=gr.iloc[0];entry.update(number_support_races=int(a.races),number_support_days=int(a.days))
                if gm['validated'] and a.races>=100 and a.days>=30 and a.years>=2:entry.update(number_effect_s=float(a.effect),number_ci_lo=float(a.ci_lo),number_ci_hi=float(a.ci_hi),number_status='prior_seconds_validation_passed_candidate')
                else:entry['number_status']='seconds_not_validated_raw_fallback'
            else:entry['number_status']='unsupported_field_or_record_raw_fallback'
        effects.append(entry)
    csv(out/'record_effects.csv',pd.DataFrame(effects))
    save(out/'run_manifest.json',{'contract_sha256':sha(HERE/'RESEARCH_CONTRACT.md'),'db_sha256':sha(DB),'code_sha256':{n:sha(HERE/n) for n in ['audit.py','modeling.py','analyze.py']},'created_after_contract':True,'expectation_years':list(range(2019,2027)),'coefficient_years':list(range(2021,2027)),'primary_race_rows':len(race),'fit_count_expectation_primary':len(modelinfo),'variants':list(variants)})
    print('Analysis complete',out,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='analysis_01');main(p.parse_args().output)
