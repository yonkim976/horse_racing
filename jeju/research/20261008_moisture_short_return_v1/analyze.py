"""Short-interval and return-condition corroboration; read-only source and DB."""
from pathlib import Path
import importlib.util
import hashlib
import json
import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent;ROOT=H.parents[2]
PREV=H.parent/'20261008_record_normalization_pairs_v3'
spec=importlib.util.spec_from_file_location('prior',PREV/'analyze.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
BANDS=a.BANDS;ENV=['band_'+b for b in BANDS[1:]];SEED=20261008
def sha(p):return a.sha(p)
def save(n,v):
    with (H/n).open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
def csv(n,v):
    with (H/n).open('x') as f:v.to_csv(f,index=False)
def weights(g):return (1/g.groupby('race_id').key.transform('size')).to_numpy().copy()
def fitted(g,names,kind='huber'):
    m=a.fit(g[names].to_numpy(float),g.y.to_numpy(),weights(g),kind)
    assert m['converged'],(len(g),names,kind)
    return m
def model_record(m,names):return a.record(m,names)

def population():
    q,_=a.get_data();grp=q.groupby(['horse_id','race_distance_m'],sort=False)
    left=grp.shift(1);right=grp.shift(-1)
    days=pd.to_datetime(q.race_date);lg=(days-pd.to_datetime(left.race_date)).dt.days
    rg=(pd.to_datetime(right.race_date)-days).dt.days
    # All category definitions are input labels only; no outcome-derived feature selection.
    names=['weight','log_starts','field_n','race_number']+ENV
    for cat in ['grade','sex']:
        for level in sorted(q[cat].unique())[1:]:
            name=cat+'='+level;q[name]=(q[cat]==level).astype(float);names.append(name)
    left=q.groupby(['horse_id','race_distance_m'],sort=False).shift(1)
    right=q.groupby(['horse_id','race_distance_m'],sort=False).shift(-1)
    def construct(mask,design):
        b=q[mask].reset_index(drop=True);l=left[mask].reset_index(drop=True);r=right[mask].reset_index(drop=True)
        gap1=lg[mask].to_numpy();gap2=rg[mask].to_numpy()
        w3=gap1/(gap1+gap2) if design=='return' else np.zeros(len(b));w1=1-w3
        out=pd.DataFrame({'key':b.api_record_id.astype(int),'horse_id':b.horse_id,'distance':b.race_distance_m.astype(int),
            'race_id':b.race_id,'date':b.race_date,'year':b.year.astype(int),'month':b.month.astype(int),
            'before_id':l.api_record_id.astype(int),'before_date':l.race_date,'before_race':l.race_id,'before_band':l.band,
            'band':b.band,'before_sha':l.api4_3_payload_sha256,'sha':b.api4_3_payload_sha256,
            'before_time':l.finish_time_seconds,'time':b.finish_time_seconds,'gap1':gap1,'w1':w1,'w3':w3,
            'same_grade':b.grade.eq(l.grade),'same_month':b.month.eq(l.month),
            'start_date':l.race_date,'end_date':b.race_date})
        if design=='return':
            for col,src in [('after_id','api_record_id'),('after_date','race_date'),('after_race','race_id'),('after_band','band'),('after_sha','api4_3_payload_sha256'),('after_time','finish_time_seconds')]:out[col]=r[src]
            out['after_id']=out.after_id.astype(int);out['end_date']=r.race_date;out['gap2']=gap2
            out['same_grade']&=b.grade.eq(r.grade);out['same_month']&=b.month.eq(r.month)
            out['y']=b.finish_time_seconds-w1*l.finish_time_seconds-w3*r.finish_time_seconds
            out['span_days']=gap1+gap2;out['gap_asymmetry']=gap2-gap1
        else:out['y']=b.finish_time_seconds-l.finish_time_seconds;out['span_days']=gap1;out['gap_asymmetry']=0.
        for name in names:
            out[name]=b[name].to_numpy()-w1*l[name].to_numpy()-(w3*r[name].to_numpy() if design=='return' else 0)
        for month in range(2,13):out['calendar_month_'+str(month)]=(b.month==month).astype(float)
        out['changed']=out.band.ne(out.before_band);out['transition']=out.before_band+'→'+out.band
        out['design']=design
        assert out.key.is_unique and out[names+['y']].notna().all().all()
        assert l.horse_id.eq(b.horse_id).all()
        if design=='return':assert r.horse_id.eq(b.horse_id).all() and l.band.eq(r.band).all()
        return out
    kp=lg.between(7,30)&q.year.eq(left.year)&q.month.eq(left.month)
    kt=lg.between(7,30)&rg.between(7,30)&q.year.eq(left.year)&q.year.eq(right.year)&left.band.eq(right.band)
    frames=[construct(kp,'pair'),construct(kt,'return')]
    columns=['span_days','gap_asymmetry']+[n for n in names if n not in ENV]+['calendar_month_'+str(i) for i in range(2,13)]+ENV
    return q,frames,columns

def estimate(g,names,reps=0,horse_reps=0):
    m=fitted(g,names);coef=a.rawcoef(m);results=[];boot=[]
    for cluster,repetitions in [('block',reps),('horse',horse_reps)]:
        if not repetitions:continue
        ids=a.block_ids(g.date) if cluster=='block' else g.horse_id.to_numpy()
        levels,code=np.unique(ids,return_inverse=True);rng=np.random.default_rng(SEED)
        draws=[];w=weights(g);x=g[names].to_numpy(float)
        for _ in range(repetitions):
            count=np.bincount(rng.integers(0,len(levels),len(levels)),minlength=len(levels))
            mm=a.fit(x,g.y.to_numpy(),w*count[code]);assert mm['converged']
            draws.append(a.rawcoef(mm))
        boot.append({'mode':cluster,'clusters':len(levels),'columns':names,'coefficients':np.array(draws).tolist()})
    bm={s['mode']:np.array(s['coefficients']) for s in boot}
    for band in BANDS:
        ix=names.index('band_'+band) if band!='건조' else None
        value=coef[ix] if ix is not None else 0.
        r={'band':band,'effect_s':float(value),'adjustment_s':float(-value)}
        for key,draws in bm.items():
            vals=draws[:,ix] if ix is not None else np.zeros(len(draws));lo,hi=np.quantile(vals,[.025,.975])
            r.update({key+'_lo':float(lo),key+'_hi':float(hi)})
        results.append(r)
    return results,model_record(m,names),boot

def race_stats(g,residual):
    v=g[['race_id','date','transition']].copy();v['residual']=residual
    r=v.groupby(['race_id','date','transition'],as_index=False).residual.mean()
    group=r.groupby('transition').residual.agg(['mean','size']);group=group[group['size']>=10]
    if len(group)<2:bias=None
    else:
        center=np.average(group['mean'],weights=group['size'])
        bias=float(np.sqrt(np.average((group['mean']-center)**2,weights=group['size'])))
    # MAE at runner level first, then equal ending/middle race.
    mae=float(pd.DataFrame({'race':g.race_id,'ae':np.abs(residual)}).groupby('race').ae.mean().mean())
    return bias,mae,group

def main():
    refs=[H/'PLAN.json',H/'analyze.py',PREV/'analyze.py',a.OLD/'audit/source_rows.csv',PREV/'latest_models.json',ROOT/'jeju/data/horse_exclusions.json']
    manifest=[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in refs]
    save('source_manifest.json',manifest);dbhash=sha(a.DB)
    q,frames,names=population();allrows=pd.concat(frames,ignore_index=True)
    csv('endpoint_lineage.csv',allrows)
    csv('annual_support.csv',allrows.groupby(['design','distance','year','changed']).agg(observations=('key','size'),horses=('horse_id','nunique'),anchor_races=('race_id','nunique'),anchor_dates=('date','nunique')).reset_index())
    exclusions=json.loads((ROOT/'jeju/data/horse_exclusions.json').read_text())
    # Preserved prior extraction already applied exclusion policy; assert designated deleted ID absent.
    assert '3005648' not in set(allrows.horse_id)
    effects=[];models=[];boots=[];directions=[];sens=[]
    for frame in frames:
        design=frame.design.iloc[0]
        for distance in [1000,1110]:
            base=frame[frame.distance==distance].copy()
            for label,start,end in [('full','2017-01-01','2026-09-19'),('past','2017-01-01','2023-12-31'),('confirmation','2024-01-01','2025-12-31'),('2026partial','2026-01-01','2026-09-19')]:
                g=base[base.start_date.ge(start)&base.end_date.le(end)]
                reps=200 if label in ['full','confirmation'] else 0;hr=100 if label=='full' else 0
                es,mo,bs=estimate(g,names,reps,hr)
                info={'design':design,'distance':distance,'period':label,'observations':len(g),'horses':g.horse_id.nunique(),'races':g.race_id.nunique()}
                effects.extend([info|r for r in es]);models.append(info|{'model':mo});boots.append(info|{'draws':bs})
                # Remove only nuisance prediction from this descriptive model, then orient directions.
                mm={k:np.array(v) if k in ['beta','mean','sd'] else v for k,v in mo.items() if k!='columns'}
                co=a.rawcoef(mm);ev=g[ENV].to_numpy(float)@co[[names.index(n) for n in ENV]]
                residual=g.y.to_numpy()-(a.predict(mm,g[names].to_numpy(float))-ev)
                temp=g.copy();temp['nuisance_adjusted']=residual
                for (before,after),v in temp[temp.changed].groupby(['before_band','band']):
                    sign=1 if BANDS.index(after)>BANDS.index(before) else -1
                    value=v.groupby('race_id').nuisance_adjusted.mean().mean()*sign
                    directions.append(info|{'from_band':before,'to_band':after,'ordered_contrast':BANDS[min(BANDS.index(before),BANDS.index(after))]+' vs '+BANDS[max(BANDS.index(before),BANDS.index(after))],
                                      'direction_observations':len(v),'direction_races':v.race_id.nunique(),'oriented_effect_s':value})
                print('Estimated',design,distance,label,len(g),flush=True)
            # Fixed fullperiod sensitivity, no selecting the most favorable specification.
            variants={'ols':base,'stable_grade_weight':base[base.same_grade&base.weight.abs().le(1)]}
            if design=='pair':variants['gap21']=base[base.gap1.le(21)]
            else:variants['same_month']=base[base.same_month]
            for label,g in variants.items():
                if len(g)<30:continue
                mo=fitted(g,names,'ols' if label=='ols' else 'huber');co=a.rawcoef(mo)
                for band in BANDS:
                    val=co[names.index('band_'+band)] if band!='건조' else 0.
                    sens.append({'design':design,'distance':distance,'variant':label,'observations':len(g),'changed_observations':int(g.changed.sum()),'band':band,'effect_s':val,'adjustment_s':-val})
    csv('effects.csv',pd.DataFrame(effects));save('models.json',models);save('bootstrap_draws.json',boots)
    csv('direction_estimates.csv',pd.DataFrame(directions));csv('sensitivities.csv',pd.DataFrame(sens))
    # Frozen past-only pair coefficients provide the same correction to both validation designs.
    frozen=[];checks=[];predictions=[];groupmeans=[]
    for distance in [1000,1110]:
        pm=next(m for m in models if m['design']=='pair' and m['distance']==distance and m['period']=='past')['model']
        coeff=np.array(pm['beta'])[1:]/np.array(pm['sd']);ec=coeff[[names.index(n) for n in ENV]]
        frozen.append({'distance':distance,'source':'same_month_pair2017_2023','moisture_effects':dict(zip(BANDS,[0.]+ec.tolist()))})
    save('frozen_before_confirmation.json',{'rates':[0,.25,.5,1.],'coefficients':frozen,'selection':'none; all fixed diagnostics'})
    for frame in frames:
        design=frame.design.iloc[0]
        for distance in [1000,1110]:
            g=frame[frame.distance==distance];tr=g[g.end_date.le('2023-12-31')]
            ec=np.array(list(next(f for f in frozen if f['distance']==distance)['moisture_effects'].values())[1:])
            nn=[n for n in names if n not in ENV]
            for rate in [0,.25,.5,1.]:
                train=tr.copy();train['y']=tr.y-rate*(tr[ENV].to_numpy()@ec)
                m=fitted(train,nn)
                for period,start,end in [('confirmation','2024-01-01','2025-12-31'),('2026partial','2026-01-01','2026-09-19')]:
                    te=g[g.start_date.ge(start)&g.end_date.le(end)].copy()
                    env=te[ENV].to_numpy()@ec;res=te.y-a.predict(m,te[nn].to_numpy())-rate*env
                    bias,mae,groups=race_stats(te,res)
                    checks.append({'design':design,'distance':distance,'period':period,'rate':rate,'transition_disparity_rms_s':bias,'race_equal_MAE_s':mae,'supported_transition_groups':len(groups),'observations':len(te),'races':te.race_id.nunique()})
                    for transition,r in groups.iterrows():groupmeans.append({'design':design,'distance':distance,'period':period,'rate':rate,'transition':transition,'mean_residual_s':r['mean'],'races':int(r['size'])})
                    te['rate']=rate;te['period']=period;te['environment_difference_s']=env;te['residual_s']=res
                    predictions.append(te[['design','distance','key','race_id','date','transition','changed','rate','period','y','environment_difference_s','residual_s']])
    csv('held_checks.csv',pd.DataFrame(checks));csv('held_transition_means.csv',pd.DataFrame(groupmeans));csv('held_predictions.csv',pd.concat(predictions,ignore_index=True))
    # Bound approximate seasonal curvature using preserved old fullperiod curve, diagnostic only.
    curv=[]
    for item in json.loads((PREV/'latest_models.json').read_text()):
        d=item['distance'];cols=item['model']['columns'];c=np.array(item['model']['beta'])[1:]/np.array(item['model']['sd'])
        g=frames[1][frames[1].distance==d];v=[]
        for dt in ['date','before_date','after_date']:
            th=a.phase(g[dt]);v.append(sum(c[cols.index(f'sin{k}')]*np.sin(k*th)+c[cols.index(f'cos{k}')]*np.cos(k*th) for k in [1,2]))
        s=v[0]-g.w1.to_numpy()*v[1]-g.w3.to_numpy()*v[2]
        curv.append({'distance':d,'median_absolute_month_curvature_s':float(np.median(abs(s))),'p95_absolute_s':float(np.quantile(abs(s),.95)),'max_absolute_s':float(max(abs(s)))})
    save('month_curvature_diagnostic.json',curv)
    assert all(sha(r['path'])==r['sha256'] for r in manifest)
    assert sha(a.DB)==dbhash
    save('verification.json',{'status':'passed','source_and_database_unchanged':True,'database_sha256':dbhash,'all_model_and_bootstrap_fits_converged':True,'official_id_and_exact_distance_checked':True,'return_date_weights_sum_one':True,'top3_used':False,'no_operational_write':True,'counterfactual_truth_observed':False})
    print(pd.DataFrame(effects).query("band=='포화'").to_string(index=False),flush=True)
    print(pd.DataFrame(checks).to_string(index=False),flush=True)

if __name__=='__main__':main()
