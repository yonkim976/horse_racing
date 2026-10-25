"""Independent arithmetic and optimizer checks, fixed-prediction intervals, figures."""
from pathlib import Path
import importlib.util
import json
import numpy as np
import pandas as pd
from scipy.optimize import minimize
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

H=Path(__file__).resolve().parent
sp=importlib.util.spec_from_file_location('study',H/'analyze.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
q,frames,names=a.population();p=pd.read_csv(H/'endpoint_lineage.csv',dtype={'horse_id':str})
ref=q.set_index('api_record_id');assert len(p)==sum(len(f) for f in frames)
for design,g in p.groupby('design'):
    b=ref.loc[g.key];l=ref.loc[g.before_id]
    assert np.array_equal(b.horse_id.to_numpy(),g.horse_id)
    assert np.array_equal(l.horse_id.to_numpy(),g.horse_id)
    assert np.array_equal(b.race_distance_m.to_numpy(),g.distance)
    assert np.array_equal(l.race_distance_m.to_numpy(),g.distance)
    assert np.allclose(g.time,b.finish_time_seconds) and np.allclose(g.before_time,l.finish_time_seconds)
    assert g.gap1.between(7,30).all()
    if design=='pair':
        assert np.array_equal(b.month.to_numpy(),l.month)
        assert np.allclose(g.y,g.time-g.before_time)
    else:
        r=ref.loc[g.after_id.astype(int)]
        assert np.array_equal(r.horse_id.to_numpy(),g.horse_id)
        assert np.array_equal(r.race_distance_m.to_numpy(),g.distance)
        assert np.array_equal(b.year.to_numpy(),r.year)
        assert np.array_equal(l.band.to_numpy(),r.band)
        assert g.gap2.between(7,30).all()
        assert np.allclose(g.w1+g.w3,1)
        assert np.allclose(g.y,g.time-g.w1*g.before_time-g.w3*g.after_time)
        t=(pd.to_datetime(g.date)-pd.Timestamp('2017-01-01')).dt.days
        t1=(pd.to_datetime(g.before_date)-pd.Timestamp('2017-01-01')).dt.days
        t3=(pd.to_datetime(g.after_date)-pd.Timestamp('2017-01-01')).dt.days
        assert np.allclose(t-g.w1*t1-g.w3*t3,0)
    assert np.array_equal(b.year.to_numpy(),l.year)
excluded=json.loads((a.ROOT/'jeju/data/horse_exclusions.json').read_text())['horses']
assert not(set(p.horse_id)&{k for k,v in excluded.items() if not v['reimport_allowed']})
models=json.loads((H/'models.json').read_text());optim=[]
for item in models:
    if item['period']!='full':continue
    g=next(f for f in frames if f.design.iloc[0]==item['design']);g=g[g.distance==item['distance']]
    m=item['model'];n=m['columns'];x=g[n].to_numpy(float);w=a.weights(g);w*=len(w)/sum(w)
    z=np.column_stack([np.ones(len(g)),(x-np.array(m['mean']))/np.array(m['sd'])]);pen=np.eye(z.shape[1]);pen[0,0]=0
    init=np.linalg.solve(z.T@(w[:,None]*z)+pen,z.T@(w*g.y.to_numpy()));rr=g.y.to_numpy()-z@init
    def med(v):
        ix=np.argsort(v);return v[ix[np.searchsorted(np.cumsum(w[ix]),sum(w)/2)]]
    delta=1.345*max(1e-10,1.4826*med(abs(rr-med(rr))))
    def obj(b):
        r=g.y.to_numpy()-z@b;ab=abs(r)
        return w@np.where(ab<=delta,.5*r*r,delta*ab-.5*delta**2)+.5*b@pen@b
    def grad(b):return -z.T@(w*np.clip(g.y.to_numpy()-z@b,-delta,delta))+pen@b
    alt=minimize(obj,init,jac=grad,method='BFGS',options={'gtol':1e-7,'maxiter':1000});saved=np.array(m['beta'])
    difference=float(max(abs(z@(alt.x-saved))));assert difference<1e-5
    optim.append({'design':item['design'],'distance':item['distance'],'prediction_max_difference_s':difference,'gradient_max':float(max(abs(grad(saved))))})

support=p.groupby(['design','distance','year','before_band','band']).agg(observations=('key','size'),horses=('horse_id','nunique'),races=('race_id','nunique')).reset_index()
support.to_csv(H/'transition_support.csv',index=False)
special=[]
for (design,d),g in p.groupby(['design','distance']):
    for period,start,end in [('full','2017-01-01','2026-09-19'),('past','2017-01-01','2023-12-31'),('confirmation','2024-01-01','2025-12-31'),('2026partial','2026-01-01','2026-09-19')]:
        v=g[g.start_date.ge(start)&g.end_date.le(end)]
        for before,band in [('건조','포화'),('포화','건조')]:
            e=v[v.before_band.eq(before)&v.band.eq(band)]
            special.append({'design':design,'distance':int(d),'period':period,'from':before,'to':band,'observations':len(e),'races':e.race_id.nunique(),'horses':e.horse_id.nunique()})
pd.DataFrame(special).to_csv(H/'dry_saturated_direct_support.csv',index=False)

# Conditional on frozen model predictions. Fixed eligible transition groups across resamples.
pred=pd.read_csv(H/'held_predictions.csv');intervals=[]
assert np.max(abs(pred.loc[~pred.changed,'environment_difference_s']))<1e-12
frozen=json.loads((H/'frozen_before_confirmation.json').read_text())['coefficients']
held_models=[]
for frame in frames:
    for distance,g in frame.groupby('distance'):
        co=next(f for f in frozen if f['distance']==distance)['moisture_effects']
        ec=np.array([co[b] for b in a.BANDS[1:]])
        tr=g[g.end_date.le('2023-12-31')];nn=[n for n in names if n not in a.ENV]
        for rate in [0,.25,.5,1.]:
            train=tr.copy();train['y']=tr.y-rate*(tr[a.ENV].to_numpy()@ec)
            m=a.fitted(train,nn)
            held_models.append({'design':frame.design.iloc[0],'distance':int(distance),'rate':rate,'train_end':tr.end_date.max(),'model':a.model_record(m,nn)})
            for period,start,end in [('confirmation','2024-01-01','2025-12-31'),('2026partial','2026-01-01','2026-09-19')]:
                te=g[g.start_date.ge(start)&g.end_date.le(end)]
                res=te.y-a.a.predict(m,te[nn].to_numpy())-rate*(te[a.ENV].to_numpy()@ec)
                ss=pred[(pred.design==frame.design.iloc[0])&(pred.distance==distance)&(pred.period==period)&(pred.rate==rate)]
                saved=ss.set_index('key').loc[te.key,'residual_s'].to_numpy()
                assert np.allclose(res,saved,atol=1e-9)
(H/'held_nuisance_models.json').write_text(json.dumps(held_models,ensure_ascii=False,indent=2))
effects=pd.read_csv(H/'effects.csv')
for item in json.loads((H/'bootstrap_draws.json').read_text()):
    for draw in item['draws']:
        cc=np.array(draw['coefficients'])
        for band in a.BANDS[1:]:
            lo,hi=np.quantile(cc[:,draw['columns'].index('band_'+band)],[.025,.975])
            r=effects[(effects.design==item['design'])&(effects.distance==item['distance'])&(effects.period==item['period'])&(effects.band==band)].iloc[0]
            assert np.allclose([lo,hi],[r[draw['mode']+'_lo'],r[draw['mode']+'_hi']])
for (design,d,period),g in pred.groupby(['design','distance','period']):
    rates=sorted(g.rate.unique());tables=[]
    for rate in rates:
        e=g[g.rate==rate].copy()
        r=e.groupby(['race_id','date','transition'],as_index=False).residual_s.mean()
        r['block']=a.a.block_ids(r.date);tables.append(r)
    ids=sorted(set(tables[0].block));eligible=tables[0].groupby('transition').size();eligible=eligible[eligible>=10].index
    rng=np.random.default_rng(a.SEED);counts=np.array([np.bincount(rng.integers(0,len(ids),len(ids)),minlength=len(ids)) for _ in range(1000)])
    def biases(table):
        v=table[table.transition.isin(eligible)]
        sums=v.pivot_table(index='block',columns='transition',values='residual_s',aggfunc='sum',fill_value=0).reindex(index=ids,columns=eligible,fill_value=0).to_numpy()
        sizes=v.groupby(['block','transition']).size().unstack(fill_value=0).reindex(index=ids,columns=eligible,fill_value=0).to_numpy()
        if len(eligible)<2:return None
        num=counts@sums;den=counts@sizes;mean=np.divide(num,den,out=np.zeros_like(num),where=den>0)
        center=num.sum(axis=1)/den.sum(axis=1)
        return np.sqrt((den*(mean-center[:,None])**2).sum(axis=1)/den.sum(axis=1))
    base=biases(tables[0])
    for rate,table in zip(rates,tables):
        b=biases(table)
        if b is not None:
            lo,hi=np.quantile(b-base,[.025,.975]);intervals.append({'design':design,'distance':int(d),'period':period,'rate':float(rate),'metric':'transition_disparity_RMS_change','ci_lo':float(lo),'ci_hi':float(hi),'blocks':len(ids),'groups':len(eligible)})
        e=g[g.rate==rate].copy();e['ae']=abs(e.residual_s)
        rr=e.groupby(['race_id','date'],as_index=False).ae.mean();rr['block']=a.a.block_ids(rr.date)
        sums=rr.groupby('block').ae.sum().reindex(ids,fill_value=0).to_numpy();sizes=rr.groupby('block').size().reindex(ids,fill_value=0).to_numpy()
        ae=counts@sums/(counts@sizes)
        if rate==0:baseae=ae
        lo,hi=np.quantile(ae-baseae,[.025,.975]);intervals.append({'design':design,'distance':int(d),'period':period,'rate':float(rate),'metric':'MAE_change','ci_lo':float(lo),'ci_hi':float(hi),'blocks':len(ids),'groups':len(eligible)})
pd.DataFrame(intervals).to_csv(H/'held_metric_intervals.csv',index=False)

c=pd.read_csv(H/'effects.csv');fig,axes=plt.subplots(1,2,figsize=(10,4.6),layout='constrained')
for ax,d in zip(axes,[1000,1110]):
    for design,offset,color in [('pair',-.12,'#2563eb'),('return',.12,'#0f766e')]:
        e=c[(c.distance==d)&(c.design==design)&(c.period=='full')].set_index('band').loc[a.BANDS]
        point=-e.effect_s.to_numpy();lo=-e.block_hi.to_numpy();hi=-e.block_lo.to_numpy()
        ax.errorbar(point,np.arange(5)+offset,xerr=np.vstack([point-lo,hi-point]),fmt='o',capsize=3,color=color,label='Same-month pairs' if design=='pair' else 'Return-condition triples')
    ax.axvline(0,color='#64748b',lw=.8);ax.set(title=f'{d} m',yticks=range(5),yticklabels=['Dry','Good','Moist','Saturated','Wet / muddy'],xlabel='Adjustment to add vs dry (seconds)');ax.invert_yaxis();ax.grid(axis='x',alpha=.15)
axes[0].legend(loc='upper left',fontsize=8)
fig.suptitle('Jeju moisture corroboration | 2017 to 2026-09-19\nFull fitted candidates and pointwise 95% block-refit intervals; no adopted rate',fontsize=12)
fig.savefig(H/'moisture_corroboration.png',dpi=180);fig.savefig(H/'moisture_corroboration.pdf')
for src in json.loads((H/'source_manifest.json').read_text()):assert a.sha(src['path'])==src['sha256']
assert a.sha(a.a.DB)==json.loads((H/'verification.json').read_text())['database_sha256']
(H/'calculation_verification.json').write_text(json.dumps({'status':'passed','reviewer':'same_agent_independent_arithmetic_and_general_optimizer','official_endpoints_reconstructed':True,'date_linear_interpolation_cancels_linear_trend':True,'excluded_horses_absent':True,'unchanged_conditions_get_zero_environment_adjustment':True,'all_held_predictions_recalculated':True,'all_saved_coefficient_intervals_recalculated':True,'convex_optimizer_crosscheck':optim,'source_and_database_hashes_unchanged':True,'intervals':'1000 fixed-prediction block resamples, conditional on fixed coefficients and support groups'},ensure_ascii=False,indent=2))
print(pd.DataFrame(special).query("period in ['full','confirmation']").to_string(index=False))
print(pd.DataFrame(intervals).query("period=='confirmation' and rate==1").to_string(index=False))
