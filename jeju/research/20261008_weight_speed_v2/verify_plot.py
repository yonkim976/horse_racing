"""Recheck endpoints, counts, coefficients, cluster arithmetic and speed conversion."""
from pathlib import Path
import importlib.util
import json
import numpy as np
import pandas as pd
from scipy.stats import t, spearmanr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

H=Path(__file__).resolve().parent
sp=importlib.util.spec_from_file_location('study',H/'analyze.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
d,h=a.old.load();q=a.old.all_features(d,h);q=q[q.strict&q.race_distance_m.isin(a.DIST)].reset_index(drop=True)
line=pd.read_csv(H/'source_lineage.csv',dtype={'horse_id':str,'jockey_id':str});extra=line[['api_record_id','body_weight_raw','body_kg','jockey_id']]
q=q.merge(extra,on='api_record_id',validate='one_to_one').sort_values(['race_date','race_number','horse_number'])
assert q.api_record_id.is_unique and len(q)==52155
assert np.array_equal(pd.to_numeric(q.body_weight_raw.str.extract(r'^\s*(\d+(?:\.\d+)?)')[0]),q.body_kg)
for col in ['api_record_id','horse_id','race_id','race_date','race_distance_m','carried_weight_kg','api4_3_payload_sha256']:
    assert np.array_equal(line[col],q[col]),col
q['time']=q.finish_time_seconds;q['log_time100']=100*np.log(q.time);q['body10']=(q.body_kg-278)/10;q['body_squared']=q.body10**2;q['burden']=q.carried_weight_kg-55;q['burden_body']=q.burden*q.body10
finish=[]
for rid in q.api_record_id:
    ids=h[str(rid)];r=d.loc[ids[-1]] if ids else None
    finish.append((r.finish_position-1)/(r.field_n-1) if r is not None and r.field_n>1 and 1<=r.finish_position<=r.field_n else np.nan)
q['prior_finish_fraction']=finish
pairs=pd.read_csv(H/'pair_lineage.csv',dtype={'horse_id':str})
ref=q.set_index('api_record_id');first=ref.loc[pairs.previous_api_record_id];second=ref.loc[pairs.pair_id]
for col in ['horse_id','race_distance_m','year','grade']:assert np.array_equal(first[col],second[col]),col
assert np.allclose(pairs.body_change_kg,second.body_kg.to_numpy()-first.body_kg.to_numpy())
assert np.allclose(pairs.burden_change,second.carried_weight_kg.to_numpy()-first.carried_weight_kg.to_numpy())
assert np.allclose(pairs.time_delta,second.time.to_numpy()-first.time.to_numpy())
assert np.allclose(pairs.speed_change_pct,100*(first.time.to_numpy()/second.time.to_numpy()-1))
gap=(pd.to_datetime(second.race_date.to_numpy())-pd.to_datetime(first.race_date.to_numpy())).days
assert np.array_equal(gap,pairs.gap) and pairs.gap.between(7,60).all()
raw=[]
for distance,g in pairs.groupby('distance'):
    for label,part in [('all_changes',g),('increase_only',g[g.burden_change>0])]:
        raw.append({'distance':int(distance),'selection':label,'pairs':len(part),'horses':int(part.horse_id.nunique()),'weight_delta_time_delta_pearson':a.correlation(part.burden_change,part.time_delta),'weight_delta_speed_delta_pearson':a.correlation(part.burden_change,part.speed_change_pct),'weight_delta_time_delta_spearman':float(spearmanr(part.burden_change,part.time_delta).statistic) if len(part)>5 else None,'body_delta_weight_delta_pearson':a.correlation(part.body_change_kg,part.burden_change)})
a.csv('raw_pair_correlations.csv',pd.DataFrame(raw))
cor=pd.read_csv(H/'body_burden_correlations.csv')
for r in cor.itertuples():
    g=q if r.distance==0 else q[q.race_distance_m.eq(r.distance)]
    assert np.isclose(np.corrcoef(g.body_kg,g.carried_weight_kg)[0,1],r.pearson_raw)
    assert np.isclose(np.mean(100*g.carried_weight_kg/g.body_kg),r.mean_load_pct_body)
effects=pd.read_csv(H/'effects.csv');models=json.loads((H/'models.json').read_text());cov_checked=[];beta_checked=[]
def matrix(g,m):
    s=m['design'];values={}
    for col,mean,sd in zip(s['nuisance_columns'],s['nuisance_means'],s['nuisance_sd']):
        if col.endswith('_missing'):
            v=pd.to_numeric(g[col[:-8]],errors='coerce').isna().to_numpy(float)
        elif '=' in col and col not in s['nuisance_medians']:
            key,level=col.split('=',1);v=g[key].astype(str).eq(level).to_numpy(float)
        else:v=pd.to_numeric(g[col],errors='coerce').fillna(s['nuisance_medians'][col]).to_numpy(float)
        values[col]=(v-mean)/sd
    return np.column_stack([np.ones(len(g)) if col=='intercept' else values[col] if col in values else g[col].to_numpy(float) for col in m['columns']])
for item in models:
    m=item['model'];kind=item['family'];period=item['period'];distance=item['distance'];variant=item['variant']
    subset=effects[(effects.family==kind)&effects.period.eq(period)&effects.distance.eq(distance)&effects.variant.eq(variant)&effects.target.eq(m['target'])]
    for r in subset.itertuples():
        if r.exposure.startswith('burden_at_body'):
            body=int(r.exposure.removeprefix('burden_at_body').removesuffix('kg'));v=a.get_vector(m,'burden')+a.get_vector(m,'burden_body',(body-278)/10)
        else:v=a.get_vector(m,r.exposure)
        b=float(v@np.asarray(m['beta']));se=float(np.sqrt(max(0,v@np.asarray(m['cov'])@v)));cr=t.ppf(.975,m['critical_df'])
        assert np.allclose([b,b-cr*se,b+cr*se],[r.effect,r.ci_lo,r.ci_hi])
        if m['target']=='log_time100':assert np.allclose([100*np.expm1(-b/100),100*np.expm1(-(b+cr*se)/100),100*np.expm1(-(b-cr*se)/100)],[r.speed_change_pct_per_kg,r.speed_ci_lo_pct,r.speed_ci_hi_pct])
    if variant!='primary' or period!='full' or m['target']!='time_s':continue
    if kind=='row':
        g=q[q.race_distance_m.eq(distance)];x=matrix(g,m);y=g.time.to_numpy();z,lu,fe=a.prior.fe_matrix(g)
        xr=x-z@lu.solve(np.asarray(z.T@x));yr=y-z@lu.solve(np.asarray(z.T@y));nt=2
    else:
        g=pairs[pairs.distance.eq(distance)];x=matrix(g,m);xr=x;yr=g.time_delta.to_numpy();nt=2
    penalty=np.r_[np.zeros(nt),np.ones(x.shape[1]-nt)]
    if kind=='pair':penalty[m['columns'].index('intercept')]=0.
    bread=np.linalg.inv(xr.T@xr+np.diag(penalty));b=bread@(xr.T@yr);err=float(max(abs(b-np.asarray(m['beta']))));assert err<1e-7,err
    beta_checked.append({'family':kind,'distance':distance,'beta_error':err});res=yr-xr@b
    for ids,key in [(g.race_date,'date_cov'),(g.horse_id,'horse_cov')]:
        levels,codes=np.unique(ids,return_inverse=True);scores=np.zeros((len(levels),x.shape[1]));np.add.at(scores,codes,xr*res[:,None])
        covariance=bread@(scores.T@scores)@bread*(len(levels)/(len(levels)-1)*(len(g)-1)/m['residual_df'])
        assert np.allclose(covariance,m[key],atol=1e-7),(kind,distance,key)
    cov_checked.append({'family':kind,'distance':distance})
def bh(p):
    p=np.asarray(p);o=np.argsort(p);z=p[o]*len(p)/np.arange(1,len(p)+1);result=np.empty(len(p));result[o]=np.minimum(1,np.minimum.accumulate(z[::-1])[::-1]);return result
for _,g in effects.groupby(['family','period','variant','exposure']):assert np.allclose(bh(g.p),g.q_BH)
for src in json.loads((H/'source_manifest.json').read_text()):assert a.sha(src['path'])==src['sha256']
assert a.sha(a.old.DB)==json.loads((H/'verification.json').read_text())['database_sha256']
a.save('calculation_verification.json',{'status':'passed','official_id_distance_year_grade_pairs_checked':len(pairs),'body_changes_weight_changes_actual_speed_changes_recomputed':True,'source_rows_match_preserved_quality_extraction':True,'all_model_contrasts_intervals_speed_transforms_BH_checked':True,'independent_primary_full_coefficients':beta_checked,'independent_numpy_cluster_covariances':cov_checked,'input_and_database_hashes_unchanged':True,'reviewer':'same_agent_separate_endpoint_and_numpy_cluster_calculations'})

fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout='constrained')
hb=axes[0].hexbin(q.body_kg,q.carried_weight_kg,gridsize=38,mincnt=1,bins='log',cmap='Blues')
axes[0].set(xlabel='Horse body mass (kg)',ylabel='Actual carried weight (kg)',title='52,155 starts | Raw Pearson r = 0.117');fig.colorbar(hb,ax=axes[0],label='Starts (log scale)')
for family,color,offset,label in [('row','#2563eb',-.08,'Race + horse FE, weight level'),('pair','#d97706',.08,'Same horse / distance / grade, positive change')]:
    r=effects[(effects.family==family)&effects.period.eq('full')&effects.variant.eq('primary')&effects.target.eq('time_s')&effects.exposure.eq('burden' if family=='row' else 'increase_kg')&effects.distance.isin([800,900,1000,1110,1200])].sort_values('distance')
    axes[1].errorbar(np.arange(len(r))+offset,r.effect,yerr=np.vstack([r.effect-r.ci_lo,r.ci_hi-r.effect]),fmt='o',color=color,capsize=3,label=label)
axes[1].axhline(0,color='#64748b',lw=.8);axes[1].set(xticks=range(5),xticklabels=['800','900','1000','1110','1200'],xlabel='Exact distance (m)',ylabel='Seconds per additional kg',title='Positive = slower association | Pointwise 95% intervals');axes[1].legend(fontsize=8);axes[1].grid(alpha=.15)
fig.suptitle('Jeju body mass and load | 2017 to 2026-09-19\nObservational associations; no fixed correction adopted',fontsize=12)
fig.savefig(H/'body_load_speed.png',dpi=180);fig.savefig(H/'body_load_speed.pdf')
print(json.dumps({'model_outcomes_verified':len(models),'independent_primary_models':len(cov_checked),'pair_endpoints_checked':len(pairs)},indent=2))
