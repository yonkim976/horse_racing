"""Independent augmented FE equations and inference arithmetic; scientific figure."""
from pathlib import Path
import importlib.util
import json
import numpy as np
import pandas as pd
from scipy.sparse import bmat,csc_matrix,diags
from scipy.sparse.linalg import splu
from scipy.stats import t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

H=Path(__file__).resolve().parent
sp=importlib.util.spec_from_file_location('study',H/'analyze.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
d,h=a.old.load();q=a.old.all_features(d,h);q=q[q.strict&q.field_n.eq(10)&q.race_distance_m.isin(a.DIST)]
models=json.loads((H/'models.json').read_text());num=pd.read_csv(H/'number_seconds.csv');group=pd.read_csv(H/'lateral_seconds.csv')
checks=[]
for item in models:
    if item['variant']!='primary' or item['period'] not in ['full','confirmation']:continue
    start,end=a.PLAN['periods'][item['period']]
    g=q[q.race_distance_m.eq(item['distance'])&q.year.between(start,end)].sort_values(['race_date','race_number','horse_number'])
    m=item['model'];x,spec=a.old.design(g,mode='gate');z,lu,info=a.fe_matrix(g,True);y=g.finish_time_seconds.to_numpy()
    gi=[i for i,n in enumerate(spec['columns']) if n.startswith('number_')];pen=np.ones(x.shape[1]);pen[gi]=0.
    zx=csc_matrix(z.T@x);gram=bmat([[z.T@z,zx],[zx.T,csc_matrix(x.T@x)+diags(pen)]],format='csc')
    coef=splu(gram).solve(np.r_[np.asarray(z.T@y),x.T@y]);beta=coef[z.shape[1]:]
    error=float(max(abs(beta-np.array(m['beta']))));assert error<1e-6,error
    resid=y-z@coef[:z.shape[1]]-x@beta
    xr=x-z@lu.solve(np.asarray(z.T@x));bread=np.linalg.inv(xr.T@xr+np.diag(pen))
    # Independent cluster score accumulation with add.at, not pandas groupby.
    covs=[]
    for ids,key in [(g.race_date,'date_cov'),(g.horse_id,'horse_cov')]:
        levels,codes=np.unique(ids,return_inverse=True);scores=np.zeros((len(levels),x.shape[1]));np.add.at(scores,codes,xr*resid[:,None])
        factor=len(levels)/(len(levels)-1)*(len(g)-1)/m['residual_df'];cov=bread@(scores.T@scores)@bread*factor
        assert np.allclose(cov,m[key],atol=1e-8);covs.append(cov)
    assert np.allclose(sum(covs),m['cov'],atol=1e-8)
    checks.append({'period':item['period'],'distance':item['distance'],'augmented_vs_projected_beta_max_difference':error,
                   'joint_FE_residual_orthogonality_max':float(np.max(abs(z.T@resid)))})
for item in models:
    m=item['model'];b=np.array(m['beta']);cov=np.array(m['cov'])
    v=np.array([a.old.gate_vector(m['spec'],k) for k in range(1,11)]);effect=v@b
    assert abs(effect.mean())<1e-10
    assert np.allclose(v@cov@v.T,m['gate_cov'])
    r=num[(num.period==item['period'])&(num.variant==item['variant'])&(num.distance==item['distance'])].sort_values('number')
    se=np.sqrt(np.maximum(0,np.einsum('ij,jk,ik->i',v,cov,v)))
    assert np.allclose(r.effect_s,effect) and np.allclose(r.ci_lo,effect-m['crit']*se)
    assert np.allclose(r.adjustment_s,-effect)
    gg=group[(group.period==item['period'])&(group.variant==item['variant'])&(group.distance==item['distance'])].set_index('contrast')
    for name,ix in [('inner',[0,1,2]),('middle',[3,4,5,6]),('outer',[7,8,9])]:assert np.isclose(gg.loc[name,'effect_s'],effect[ix].mean())
    assert np.isclose(gg.loc['inner_minus_outer','effect_s'],gg.loc['inner','effect_s']-gg.loc['outer','effect_s'])
for _,r in num.groupby(['period','variant']):assert np.allclose(a.old.bh(r.p),r.q_BH)
for _,r in group[group.contrast.str.contains('_minus_')].groupby(['period','variant']):assert np.allclose(a.old.bh(r.p),r.q_BH)
source=pd.read_csv(H/'source_lineage.csv',dtype={'horse_id':str});ref=d.set_index('api_record_id',drop=False)
check=ref.loc[source.api_record_id]
for col in ['horse_id','race_id','horse_number','race_date','race_distance_m','api4_3_payload_sha256']:
    assert np.array_equal(check[col].to_numpy(),source[col].to_numpy())
# Recompute frozen correction arithmetic and draw quantiles from stored model vectors.
rate=pd.read_csv(H/'frozen_rate_checks.csv')
for distance in a.DIST:
    past=[m for m in models if m['period']=='past' and m['distance']==distance and m['variant']=='primary']
    if not past:continue
    before=np.array(past[0]['model']['gate_effects'])
    for period in ['confirmation','2026partial']:
        held=[m for m in models if m['period']==period and m['distance']==distance and m['variant']=='primary']
        if not held:continue
        mm=held[0]['model'];target=np.array(mm['gate_effects']);val,vec=np.linalg.eigh(mm['gate_cov'])
        rng=np.random.default_rng(a.SEED);draw=target+rng.normal(size=(2000,10))@(vec*np.sqrt(np.maximum(val,0))).T
        base=np.sqrt(np.mean(draw**2,axis=1))
        for r in rate[(rate.distance==distance)&(rate.period==period)].itertuples():
            rr=np.sqrt(np.mean((target-r.rate*before)**2));lo,hi=np.quantile(np.sqrt(np.mean((draw-r.rate*before)**2,axis=1))-base,[.025,.975])
            assert np.allclose([rr,lo,hi],[r.corrected_gate_bias_RMS_s,r.change_ci_lo,r.change_ci_hi])
for src in json.loads((H/'source_manifest.json').read_text()):assert a.sha(src['path'])==src['sha256']
assert a.sha(a.old.DB)==json.loads((H/'verification.json').read_text())['database_sha256']
(H/'calculation_verification.json').write_text(json.dumps({'status':'passed','reviewer':'same_agent_independent_augmented_equations_and_cluster_arithmetic',
    'augmented_checks':checks,'all_gate_vectors_intervals_group_contrasts_BH_recomputed':True,'frozen_rate_draws_recomputed':True,
    'source_records_and_hashes_checked':True,'database_unchanged':True,'no_independent_future_validation_claim':True},ensure_ascii=False,indent=2))

fig,axes=plt.subplots(2,3,figsize=(12,7),layout='constrained')
for ax,dist in zip(axes.ravel(),[800,900,1000,1110,1200]):
    for period,offset,color in [('full',-.08,'#2563eb'),('confirmation',.08,'#0f766e')]:
        g=num[(num.variant=='primary')&(num.period==period)&(num.distance==dist)].sort_values('number')
        ax.errorbar(g.number+offset,g.adjustment_s,yerr=np.vstack([g.adjustment_s-g.adjustment_lo,g.adjustment_hi-g.adjustment_s]),fmt='o',capsize=2,color=color,markersize=3,label='2017 to 2026-09-19' if period=='full' else '2024-2025')
    ax.axhline(0,color='#64748b',lw=.8);ax.set(title=f'{dist} m',xticks=range(1,11),xlabel='Start number',ylabel='Adjustment to add (seconds)');ax.grid(alpha=.15)
axes[1,2].axis('off');axes[0,0].legend(fontsize=7)
fig.suptitle('Jeju gate seconds | Exactly 10 runners, race and horse fixed effects\nDescriptive 100% candidates; pointwise conservative date + horse cluster intervals',fontsize=12)
fig.savefig(H/'gate_candidates.png',dpi=180);fig.savefig(H/'gate_candidates.pdf')
summary=group[(group.variant=='primary')&(group.contrast=='inner_minus_outer')&(group.period.isin(['full','confirmation','2026partial']))]
summary.to_csv(H/'inner_outer_summary.csv',index=False)
num[(num.variant=='primary')&(num.period=='full')].pivot(index='number',columns='distance',values='adjustment_s').to_csv(H/'full_gate_adjustment_table.csv')
print(json.dumps({'verified_models':len(models),'independent_augmented_models':len(checks),'source_records':len(source)},indent=2))
