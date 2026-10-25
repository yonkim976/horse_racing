"""Independent source counts, cluster score arithmetic, contrasts and static figures."""
from pathlib import Path
import importlib.util
import json
import numpy as np
import pandas as pd
from scipy.stats import t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

H=Path(__file__).resolve().parent
sp=importlib.util.spec_from_file_location('study',H/'analyze.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
d,h=a.old.load();q=a.old.all_features(d,h);q=q[q.strict&q.field_n.eq(10)&q.race_distance_m.isin(a.PLAN['distances'])].sort_values(['race_date','race_number','horse_number']).copy()
q['top3']=q.finish_position.le(3).astype(int);q['epoch']=np.select([q.year.le(2020),q.year.le(2023)],['2017_2020','2021_2023'],default='2024_2026partial')
line=pd.read_csv(H/'source_lineage.csv',dtype={'horse_id':str})
for col in line.columns:assert np.array_equal(line[col].to_numpy(),q[col].to_numpy()),col
checks=[]
for name,keys in [('gate',['race_distance_m','horse_number']),('year_gate',['race_distance_m','year','horse_number']),('band_gate',['race_distance_m','band','horse_number']),('year_band_gate',['race_distance_m','year','band','horse_number']),('lateral',['race_distance_m','lateral']),('year_lateral',['race_distance_m','year','lateral']),('year_band_lateral',['race_distance_m','year','band','lateral']),('epoch_band_lateral',['race_distance_m','epoch','band','lateral'])]:
    table=pd.read_csv(H/f'raw_{name}.csv').set_index(keys).sort_index()
    z=q.groupby(keys).agg(starts=('top3','size'),top3=('top3','sum'),races=('race_id','nunique'),dates=('race_date','nunique')).sort_index()
    assert table.index.equals(z.index)
    for col in z:assert np.array_equal(table[col],z[col]),(name,col)
    assert np.allclose(table.top3_pct,100*z.top3/z.starts)
    checks.append({'table':name,'cells':len(table),'count_rate_match':True})
gate=pd.read_csv(H/'raw_gate.csv');assert np.allclose(gate.groupby('race_distance_m').top3_pct.mean(),30.)
models=json.loads((H/'models.json').read_text());est=pd.read_csv(H/'adjusted_contrasts.csv',dtype={'level':str});pairs=pd.read_csv(H/'year_pair_changes.csv')
cov_checks=[]
for item in models:
    m=item['model'];distance=item['distance'];variant=item['variant'];g=q[q.race_distance_m.eq(distance)]
    if item['scope']=='annual_model':
        races=g.drop_duplicates('race_id');yw=races.year.value_counts(normalize=True).to_dict();bw=races.band.value_counts(normalize=True).to_dict()
        vv={yy:sum(w*a.vec(m,yy,bb) for bb,w in bw.items()) for yy in yw}
        for r in est[(est.distance==distance)&est.variant.eq(variant)&~est.kind.eq('era_band')].itertuples():
            if r.kind=='overall':v=sum(w*vv[yy] for yy,w in yw.items())
            elif r.kind=='year':v=vv[int(r.level)]
            else:v=sum(w*a.vec(m,yy,r.level) for yy,w in yw.items())
            pt=float(v@np.array(m['beta']))*100;se=float(np.sqrt(v@np.array(m['cov'])@v))*100;crit=t.ppf(.975,m['critical_df'])
            assert np.allclose([pt,pt-crit*se,pt+crit*se],[r.effect_pp,r.ci_lo_pp,r.ci_hi_pp])
        for r in pairs[(pairs.distance==distance)&pairs.variant.eq(variant)].itertuples():
            expected=a.estimate(m,vv[r.later]-vv[r.earlier]);assert np.allclose([expected['effect_pp'],expected['ci_lo_pp'],expected['ci_hi_pp']],[r.effect_pp,r.ci_lo_pp,r.ci_hi_pp])
        if variant=='primary':
            x,s=a.design(g);z,lu,fe=a.prior.fe_matrix(g);xr=x-z@lu.solve(np.asarray(z.T@x));yr=g.top3.to_numpy()-z@lu.solve(np.asarray(z.T@g.top3.to_numpy()))
            penalty=np.r_[np.ones(s['n_nuisance']),np.zeros(x.shape[1]-s['n_nuisance'])];bread=np.linalg.inv(xr.T@xr+np.diag(penalty));res=yr-xr@np.array(m['beta'])
            for ids,key in [(g.race_date,'date_cov'),(g.horse_id,'horse_cov')]:
                levels,codes=np.unique(ids,return_inverse=True);scores=np.zeros((len(levels),x.shape[1]));np.add.at(scores,codes,xr*res[:,None])
                cov=bread@(scores.T@scores)@bread*(len(levels)/(len(levels)-1)*(len(g)-1)/m['residual_df'])
                assert np.allclose(cov,m[key],atol=1e-8)
            cov_checks.append(distance)
    else:
        epoch,bb=item['scope'].split(':')[1:];r=est[(est.kind=='era_band')&est.distance.eq(distance)&est.level.eq(epoch+':'+bb)].iloc[0]
        v=a.vec(m);expected=a.estimate(m,v);assert np.allclose([expected['effect_pp'],expected['ci_lo_pp'],expected['ci_hi_pp']],[r.effect_pp,r.ci_lo_pp,r.ci_hi_pp])
def bh(p):
    p=np.asarray(p);o=np.argsort(p);s=p[o]*len(p)/np.arange(1,len(p)+1);out=np.empty(len(p));out[o]=np.minimum(1,np.minimum.accumulate(s[::-1])[::-1]);return out
for _,g in est.groupby(['variant','kind']):assert np.allclose(bh(g.p),g.q_BH)
for _,g in pairs.groupby('variant'):assert np.allclose(bh(g.p),g.q_BH)
common=[]
for (distance,yy),g in q.groupby(['race_distance_m','year']):
    full=q[q.race_distance_m.eq(distance)].drop_duplicates('race_id').band.value_counts(normalize=True)
    seen=set(g.band);missing=[b for b in full.index if b not in seen]
    common.append({'distance':distance,'year':yy,'races':g.race_id.nunique(),'observed_bands':'|'.join(b for b in a.BANDS if b in seen),'missing_full_period_bands':'|'.join(missing),'standardization_weight_on_unobserved_bands':float(full.loc[missing].sum())})
a.csv('annual_moisture_support.csv',pd.DataFrame(common))
for src in json.loads((H/'source_manifest.json').read_text()):assert a.sha(src['path'])==src['sha256']
assert a.sha(a.old.DB)==json.loads((H/'verification.json').read_text())['database_sha256']
a.save('calculation_verification.json',{'status':'passed','source_count_checks':checks,'all_estimates_CIs_and_BH_recomputed':True,'independent_numpy_cluster_score_covariance_distances':cov_checks,'database_and_inputs_unchanged':True,'reviewer':'same_agent_independent_count_and_cluster_arithmetic','annual_missing_band_support_recorded':True})

fig,axes=plt.subplots(2,3,figsize=(13,7),layout='constrained')
for ax,distance in zip(axes.ravel(),[800,900,1000,1110,1200]):
    z=est[(est.distance==distance)&est.variant.eq('primary')&est.kind.eq('year')].copy();z['year']=z.level.astype(int);z=z.sort_values('year')
    rr=pd.read_csv(H/'raw_year_lateral.csv');rr=rr[rr.race_distance_m.eq(distance)].pivot(index='year',columns='lateral',values='top3_pct')
    nr=q[q.race_distance_m.eq(distance)].groupby('year').race_id.nunique();ix=nr[nr>=30].index
    ax.plot(ix,(rr.inner-rr.outer).loc[ix],color='#94a3b8',ls='--',marker='.',label='Raw inner minus outer')
    ax.errorbar(z.year,z.effect_pp,yerr=np.vstack([z.effect_pp-z.ci_lo_pp,z.ci_hi_pp-z.effect_pp]),fmt='o',color='#2563eb',capsize=2,label='Moisture-standardized, race + horse FE')
    ax.axhline(0,color='#334155',lw=.9);ax.set(title=f'{distance} m',xticks=[2017,2019,2021,2023,2025,2026],ylabel='Top3 difference (percentage points)',ylim=(-35,50));ax.tick_params(axis='x',labelrotation=45);ax.grid(alpha=.12)
axes[1,2].axis('off');handles,labels=axes[0,0].get_legend_handles_labels();axes[1,2].legend(handles,labels,loc='upper left',frameon=False,fontsize=9)
axes[1,2].text(0,.65,'Positive: inner gates 1-3 ahead\nNegative: outer gates 8-10 ahead\n\nPointwise 95% date + horse cluster intervals\nAnnual reporting: >=30 races and >=20 dates\n2026 ends 19 September; partial year\nNo confirmed temporal reversal after BH checks',va='top',fontsize=10)
fig.suptitle('Jeju Top3 gate associations by year | Exactly 10 starters\nFixed full-period moisture weights within each distance; observational estimates',fontsize=13)
fig.savefig(H/'annual_inner_outer.png',dpi=180);fig.savefig(H/'annual_inner_outer.pdf')
print(json.dumps({'raw_tables_verified':len(checks),'model_contrasts_verified':len(models),'independent_covariances':len(cov_checks)},indent=2))
