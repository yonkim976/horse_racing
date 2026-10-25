"""Recalculate saved results and plot scientific study summaries; no DB writes."""
from pathlib import Path
import json
import importlib.util
import numpy as np
import pandas as pd
from scipy.optimize import minimize
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

H=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('study',H/'analyze.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
q,p=a.get_data()
saved=pd.read_csv(H/'pair_source_lineage.csv',dtype={'horse_id':str})
assert len(p)==len(saved)==15862
assert np.array_equal(p.pair_id,saved.pair_id)
assert np.allclose(p.y,saved.y)
models=json.loads((H/'latest_models.json').read_text())
checks=[];cells=[]
for item in models:
    d=item['distance'];g=p[p.distance==d];x,names=a.design(g)
    m=item['model'];b=np.array(m['beta']);w=a.race_weights(g).copy();w*=len(w)/w.sum()
    z=np.column_stack([np.ones(len(x)),(x-np.array(m['mean']))/np.array(m['sd'])])
    pen=np.eye(z.shape[1]);pen[0,0]=0
    initial=np.linalg.solve(z.T@(w[:,None]*z)+pen,z.T@(w*g.y.to_numpy()))
    r0=g.y.to_numpy()-z@initial
    def med(v):
        ix=np.argsort(v);return v[ix[np.searchsorted(np.cumsum(w[ix]),w.sum()/2)]]
    delta=1.345*max(1e-10,1.4826*med(np.abs(r0-med(r0))))
    def obj(bb):
        r=g.y.to_numpy()-z@bb;ab=np.abs(r)
        return w@np.where(ab<=delta,.5*r*r,delta*ab-.5*delta**2)+.5*bb@pen@bb
    def grad(bb):
        r=g.y.to_numpy()-z@bb
        return -z.T@(w*np.clip(r,-delta,delta))+pen@bb
    # Independent general-purpose optimizer starts from OLS, not stored Huber solution.
    alt=minimize(obj,initial,jac=grad,method='BFGS',options={'gtol':1e-7,'maxiter':1000})
    max_prediction_delta=float(np.max(np.abs(z@(alt.x-b))))
    assert max_prediction_delta<1e-5
    assert np.max(np.abs(grad(b)))<1e-6
    checks.append({'distance':d,'saved_gradient_max':float(np.max(np.abs(grad(b)))),
                   'independent_optimizer_prediction_max_difference_s':max_prediction_delta,
                   'objective_difference':float(obj(b)-obj(alt.x))})
    ends=pd.concat([g[['race_id','race_date','band','month']],g[['previous_race_id','previous_date','previous_band','previous_month']].set_axis(['race_id','race_date','band','month'],axis=1)]).drop_duplicates('race_id')
    ends['year']=pd.to_datetime(ends.race_date).dt.year
    for month in range(1,13):
        for band in a.BANDS:
            e=ends[(ends.month==month)&(ends.band==band)]
            cells.append({'distance':d,'month':month,'band':band,'races':len(e),'dates':e.race_date.nunique(),'years':e.year.nunique(),
                          'interpretation':'additive_model_estimate_joint_cell_not_separately_fitted'})
pd.DataFrame(cells).to_csv(H/'joint_cell_support.csv',index=False)

pred=pd.read_csv(H/'confirmation_pair_predictions.csv')
assert np.allclose(pred.remaining_s,pred.y-pred.predicted_difference_s)
assert np.allclose(pred.predicted_difference_s,pred.nuisance_prediction_s+pred.f_rate*pred.moisture_difference_s+pred.m_rate*pred.month_difference_s)
rr=a.races(pred)
orig=pd.read_csv(H/'confirmation_race_metrics.csv')
keys=['variant','candidate','distance','year','race_id']
joined=rr.merge(orig,on=keys,validate='one_to_one',suffixes=('_new','_saved'))
assert np.allclose(joined.mae_new,joined.mae_saved)
assert np.allclose(joined.mse_new,joined.mse_saved)
joint=pd.read_csv(H/'latest_joint_reference.csv')
boots=json.loads((H/'coefficient_bootstrap.json').read_text())
for boot in boots:
    co=np.array(boot['block12weeks']['raw_coefficients']);names=boot['columns']
    for r in joint[joint.distance==boot['distance']].itertuples():
        v=a.effect_vector(names,r.band,r.date_reference)
        lo,hi=np.quantile(-(co@v),[.025,.975])
        assert np.allclose([lo,hi],[r.adjustment_ci_lo,r.adjustment_ci_hi])
assert np.allclose(joint.example_raw_s+joint.adjustment_s,joint.example_normalized_s)
for src in json.loads((H/'source_manifest.json').read_text()):assert a.sha(src['path'])==src['sha256']
assert a.sha(a.DB)==json.loads((H/'verification.json').read_text())['database_sha256']
(H/'independent_calculation_verification.json').write_text(json.dumps({'status':'passed','reviewer':'same_agent_separate_calculation_and_scipy_optimizer','pairs':len(p),'convex_objective_crosscheck':checks,'saved_predictions_and_race_metrics_recalculated':True,'joint_bootstrap_intervals_recalculated':True,'source_and_database_hashes_unchanged':True},ensure_ascii=False,indent=2))

c=pd.read_csv(H/'latest_coefficients.csv')
fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
labels=['Dry','Good','Moist','Saturated','Wet / muddy']
for row,d in enumerate([1000,1110]):
    m=c[(c.distance==d)&(c.component=='month')].sort_values('month')
    ax=axes[row,0]
    ax.fill_between(m.month,-m.ci_hi,-m.ci_lo,alpha=.18,color='#2563eb',label='Pointwise 95% block bootstrap')
    ax.plot(m.month,-m.effect_s,'o-',color='#2563eb',label='Full fitted candidate')
    ax.axhline(0,color='#64748b',lw=.8);ax.set(xticks=range(1,13),xlabel='Month (15th)',ylabel='Adjustment to add (seconds)',title=f'{d} m: month adjustment vs annual mean')
    ax.grid(alpha=.15)
    b=c[(c.distance==d)&(c.component=='moisture')].set_index('band').loc[a.BANDS]
    ax=axes[row,1];point=-b.effect_s.to_numpy();lo=-b.ci_hi.to_numpy();hi=-b.ci_lo.to_numpy()
    ax.errorbar(point,range(5),xerr=np.vstack([point-lo,hi-point]),fmt='o',capsize=3,color='#0f766e')
    ax.axvline(0,color='#64748b',lw=.8);ax.set(yticks=range(5),yticklabels=labels,xlabel='Adjustment to add (seconds)',title=f'{d} m: moisture adjustment vs dry')
    ax.invert_yaxis();ax.grid(axis='x',alpha=.15)
fig.suptitle('Jeju reference-time study | 2017 to 2026-09-19\nDescriptive 100% fitted effects; fixed deployment rate not established',fontsize=13)
fig.savefig(H/'adjustment_candidates.png',dpi=180)
fig.savefig(H/'adjustment_candidates.pdf')
print(json.dumps(checks,indent=2))
print(pd.DataFrame(cells).groupby('distance').agg(zero_cells=('races',lambda x:int((x==0).sum())),min_races=('races','min')).to_string())
