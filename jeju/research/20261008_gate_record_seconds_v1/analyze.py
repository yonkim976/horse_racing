"""Within-race and within-horse gate seconds; local retrospective research."""
from pathlib import Path
import importlib.util
import json
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu
from scipy.stats import t,norm

H=Path(__file__).resolve().parent;ROOT=H.parents[2]
PRIOR=H.parent/'20261008_gate_2017_2026_v1'
sp=importlib.util.spec_from_file_location('gate_prior',PRIOR/'analyze.py');old=importlib.util.module_from_spec(sp);sp.loader.exec_module(old)
PLAN=json.loads((H/'PLAN.json').read_text());DIST=PLAN['distances'];SEED=20261008
def sha(p):return old.sha(Path(p))
def save(name,v):
    with (H/name).open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
def csv(name,v):
    with (H/name).open('x') as f:v.to_csv(f,index=False)

def fe_matrix(g,horse=True):
    r,rv=pd.factorize(g.race_id,sort=True);nr=len(rv);nh=0;components=nr
    rows=np.arange(len(g));ri=rows;ci=r
    if horse:
        h,hv=pd.factorize(g.horse_id,sort=True);nh=len(hv)
        graph=coo_matrix((np.ones(2*len(g)),(np.r_[r,nr+h],np.r_[nr+h,r])),shape=(nr+nh,nr+nh)).tocsr()
        components,labels=connected_components(graph,directed=False)
        anchors=pd.Series(np.arange(nh)).groupby(labels[nr:]).min().to_numpy()
        keep=np.ones(nh,bool);keep[anchors]=False;mapping=np.full(nh,-1);mapping[keep]=np.arange(sum(keep))+nr
        mask=keep[h];ri=np.r_[rows,rows[mask]];ci=np.r_[r,mapping[h[mask]]]
    ncols=nr+(nh-components if horse else 0)
    z=coo_matrix((np.ones(len(ri)),(ri,ci)),shape=(len(g),ncols)).tocsc()
    lu=splu((z.T@z).tocsc())
    return z,lu,{'rank':ncols,'components':components,'races':nr,'horses':int(g.horse_id.nunique())}

def cluster_cov(x,res,bread,ids,df):
    score=x*res[:,None];s=pd.DataFrame(score).groupby(np.asarray(ids)).sum().to_numpy()
    count=len(s);factor=count/max(1,count-1)*(len(res)-1)/df
    return bread@(s.T@s)@bread*factor

def fit(g,variant='primary'):
    x,spec=old.design(g,mode='gate');columns=spec['columns']
    if variant=='no_history':
        keep=[i for i,c in enumerate(columns) if c not in ['hist_mean','hist_last','hist_mean_missing','hist_last_missing']]
        x=x[:,keep];spec={**spec,'columns':[columns[i] for i in keep],'means':[spec['means'][i] for i in keep],'sd':[spec['sd'][i] for i in keep]};columns=spec['columns']
    y=g.finish_time_seconds.to_numpy();z,lu,info=fe_matrix(g,variant!='race_only')
    v=np.column_stack([y,x]);residualized=v-z@lu.solve(np.asarray(z.T@v));yr=residualized[:,0];xr=residualized[:,1:]
    orth=float(np.max(np.abs(z.T@residualized)));assert orth<1e-7,orth
    gi=[i for i,c in enumerate(columns) if c.startswith('number_')];ni=[i for i in range(x.shape[1]) if i not in gi]
    nuisance=xr[:,ni];gate=xr[:,gi]
    if len(ni):gate=gate-nuisance@np.linalg.lstsq(nuisance,gate,rcond=1e-9)[0]
    rank=int(np.linalg.matrix_rank(gate,tol=1e-7));assert rank==9,rank
    df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7);assert df>20,df
    penalty=np.eye(xr.shape[1]);penalty[gi,gi]=0.
    bread=np.linalg.inv(xr.T@xr+penalty);beta=bread@(xr.T@yr);res=yr-xr@beta
    dc=cluster_cov(xr,res,bread,g.race_date,df);hc=cluster_cov(xr,res,bread,g.horse_id,df);cov=dc+hc
    vectors=np.array([old.gate_vector(spec,k) for k in range(1,11)])
    crit=float(t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1))
    return {'beta':beta.tolist(),'spec':spec,'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'cov':cov.tolist(),
            'gate_effects':(vectors@beta).tolist(),'gate_cov':(vectors@cov@vectors.T).tolist(),'crit':crit,
            'residual_df':int(df),'projection_max_orthogonality':orth,'gate_rank':rank,'fe':info}

def profile(model,g,info):
    beta=np.array(model['beta']);cov=np.array(model['cov']);dc=np.array(model['date_cov']);hc=np.array(model['horse_cov']);crit=model['crit']
    vectors={k:old.gate_vector(model['spec'],k) for k in range(1,11)};rows=[];groups=[]
    def contrast(v):
        pt=float(v@beta);se=float(np.sqrt(max(0,v@cov@v)));lo=pt-crit*se;hi=pt+crit*se
        return {'effect_s':pt,'ci_lo':lo,'ci_hi':hi,'adjustment_s':-pt,'adjustment_lo':-hi,'adjustment_hi':-lo,
                'date_se':float(np.sqrt(max(0,v@dc@v))),'horse_se':float(np.sqrt(max(0,v@hc@v))),
                'p':float(2*t.sf(abs(pt/se),min(g.race_date.nunique(),g.horse_id.nunique())-1)) if se>0 else 1.}
    for k,v in vectors.items():rows.append(info|{'number':k}|contrast(v))
    gv={name:np.mean([vectors[k] for k in ks],axis=0) for name,ks in [('inner',[1,2,3]),('middle',[4,5,6,7]),('outer',[8,9,10])]}
    for name,v in gv.items():groups.append(info|{'contrast':name}|contrast(v))
    for left,right in [('inner','middle'),('outer','middle'),('inner','outer')]:groups.append(info|{'contrast':left+'_minus_'+right}|contrast(gv[left]-gv[right]))
    return rows,groups

def main():
    refs=[H/'PLAN.json',H/'analyze.py',PRIOR/'analyze.py',PRIOR/'number_effects.csv',PRIOR/'models.json',old.OLD/'audit/source_rows.csv',old.OLD/'audit/history_ids.json',old.OLD/'modeling.py',ROOT/'jeju/data/horse_exclusions.json']
    manifest=[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in refs];save('source_manifest.json',manifest)
    dbsha=sha(old.DB);d,h=old.load();q=old.all_features(d,h)
    q=q[q.strict&q.race_distance_m.isin(DIST)&q.field_n.eq(10)].sort_values(['race_date','race_number','horse_number']).copy()
    assert q.groupby('race_id').horse_number.apply(lambda v:sorted(v)==list(range(1,11))).all()
    assert q.api_record_id.is_unique and q.race_date.max()=='2026-09-19'
    excluded=json.loads((ROOT/'jeju/data/horse_exclusions.json').read_text())['horses']
    assert not(set(q.horse_id)&{k for k,v in excluded.items() if not v['reimport_allowed']})
    ref=d[['horse_id','race_distance_m','race_date']].to_dict('index');checked=0
    for r in q.itertuples():
        for i in h[str(r.api_record_id)][-5:]:
            s=ref[i];assert s['horse_id']==r.horse_id and s['race_distance_m']==r.race_distance_m and s['race_date']<=r.history_cutoff;checked+=1
    csv('source_lineage.csv',q[['api_record_id','race_id','horse_id','race_date','race_distance_m','horse_number','history_cutoff','api4_3_payload_sha256']])
    csv('annual_support.csv',q.groupby(['race_distance_m','year']).agg(races=('race_id','nunique'),dates=('race_date','nunique'),horses=('horse_id','nunique'),rows=('race_id','size')).reset_index())
    rows=[];groups=[];models=[];support=[]
    for period,(start,end) in PLAN['periods'].items():
        for dist in DIST:
            g=q[q.race_distance_m.eq(dist)&q.year.between(start,end)]
            info={'period':period,'distance':dist,'races':g.race_id.nunique(),'dates':g.race_date.nunique(),'horses':g.horse_id.nunique(),'years':g.year.nunique(),'rows':len(g),'first_date':g.race_date.min() if len(g) else None,'last_date':g.race_date.max() if len(g) else None}
            variants=['primary']+(['race_only','no_history'] if period in ['full','recent'] else [])
            for variant in variants:
                inf=info|{'variant':variant};can=info['races']>=30 and info['dates']>=20
                if not can:support.append(inf|{'estimated':False,'status':'insufficient_races_dates'});continue
                try:m=fit(g,variant)
                except AssertionError as exc:
                    support.append(inf|{'estimated':False,'status':'insufficient_identification_df','detail':str(exc)});continue
                support.append(inf|{'estimated':True,'status':'limited' if info['races']<100 else 'descriptive_supported','residual_df':m['residual_df']})
                nr,gr=profile(m,g,inf);rows.extend(nr);groups.extend(gr);models.append(inf|{'model':m})
                print(period,dist,variant,len(g),m['projection_max_orthogonality'],flush=True)
    numbers=pd.DataFrame(rows);group=pd.DataFrame(groups)
    for _,g in numbers.groupby(['period','variant']):numbers.loc[g.index,'q_BH']=old.bh(g.p)
    for _,g in group[group.contrast.str.contains('_minus_')].groupby(['period','variant']):group.loc[g.index,'q_BH']=old.bh(g.p)
    csv('number_seconds.csv',numbers);csv('lateral_seconds.csv',group);csv('support.csv',pd.DataFrame(support));save('models.json',models)
    # Fixed-rate reduction in estimated residual gate bias, not future finish-time prediction.
    checks=[]
    for dist in DIST:
        before=[m for m in models if m['period']=='past' and m['distance']==dist]
        if not before:continue
        past=np.array(before[0]['model']['gate_effects'])
        for period in ['confirmation','2026partial']:
            fits=[m for m in models if m['period']==period and m['distance']==dist]
            if not fits:continue
            mm=fits[0]['model'];target=np.array(mm['gate_effects']);cov=np.array(mm['gate_cov'])
            vals,vec=np.linalg.eigh(cov);assert vals.min()>-1e-8
            rng=np.random.default_rng(SEED);draw=target+rng.normal(size=(2000,10))@(vec*np.sqrt(np.maximum(vals,0))).T
            base=np.sqrt(np.mean(draw**2,axis=1));baseline=float(np.sqrt(np.mean(target**2)))
            for rate in [0,.25,.5,.75,1.]:
                out=target-rate*past;delta=np.sqrt(np.mean((draw-rate*past)**2,axis=1))-base;lo,hi=np.quantile(delta,[.025,.975])
                checks.append({'distance':dist,'period':period,'rate':rate,'baseline_gate_bias_RMS_s':baseline,'corrected_gate_bias_RMS_s':float(np.sqrt(np.mean(out**2))),
                               'change_s':float(np.sqrt(np.mean(out**2)))-baseline,'change_ci_lo':float(lo),'change_ci_hi':float(hi),
                               'races':fits[0]['races'],'meaning':'estimated_gate_bias_proxy_conditional_on_fixed_past_coefficients'})
    csv('frozen_rate_checks.csv',pd.DataFrame(checks))
    candidates=[]
    for dist in DIST:
        for k in range(1,11):
            r=numbers[(numbers.period=='full')&numbers.variant.eq('primary')&numbers.distance.eq(dist)&numbers.number.eq(k)]
            c=numbers[(numbers.period=='confirmation')&numbers.distance.eq(dist)&numbers.number.eq(k)]
            if r.empty:
                candidates.append({'distance':dist,'number':k,'status':'not_estimated','corroborated':False,'adopted_adjustment_s':None});continue
            r=r.iloc[0];reason=[];sign=np.sign(r.effect_s)
            if r.races<100 or r.dates<40 or r.years<2:reason.append('full_support')
            if c.empty:reason.append('confirmation_not_estimated')
            else:
                c=c.iloc[0]
                if c.races<100 or c.dates<40 or c.years<2:reason.append('confirmation_support')
                if sign!=np.sign(c.effect_s):reason.append('confirmation_sign')
                if c.q_BH>=.05:reason.append('confirmation_q')
            if r.q_BH>=.05:reason.append('full_q')
            for period,variant in [('recent','primary'),('full','race_only'),('recent','race_only'),('full','no_history'),('recent','no_history')]:
                z=numbers[(numbers.period==period)&numbers.variant.eq(variant)&numbers.distance.eq(dist)&numbers.number.eq(k)]
                if z.empty or np.sign(z.iloc[0].effect_s)!=sign:reason.append(period+'_'+variant+'_sign')
            candidates.append({'distance':dist,'number':k,'status':'corroborated_descriptive_candidate' if not reason else 'not_corroborated',
                               'corroborated':not reason,'descriptive_adjustment_s':r.adjustment_s,'adjustment_ci_lo':r.adjustment_lo,'adjustment_ci_hi':r.adjustment_hi,
                               'adopted_adjustment_s':0.,'reasons':'|'.join(reason),'meaning':'no_fixed_rate_adoption_even_if_corroborated'})
    csv('candidate_status.csv',pd.DataFrame(candidates))
    assert np.allclose(numbers.groupby(['period','variant','distance']).effect_s.mean(),0,atol=1e-10)
    assert np.allclose(numbers.adjustment_s,-numbers.effect_s)
    assert all(sha(m['path'])==m['sha256'] for m in manifest) and sha(old.DB)==dbsha
    save('verification.json',{'status':'passed','source_and_database_unchanged':True,'database_sha256':dbsha,'history_endpoints_checked':checked,'source_rows':len(q),
        'projection_orthogonality_max':max(m['model']['projection_max_orthogonality'] for m in models),'gate_effects_mean_zero':True,
        'no_top3_target':True,'no_operational_change':True,'counterfactual_truth_observed':False,'corroborated_gate_cells':sum(r['corroborated'] for r in candidates)})
    print(numbers.query("period=='full' and variant=='primary'")[['distance','number','effect_s','adjustment_s','q_BH']].to_string(index=False),flush=True)
    print(pd.DataFrame(checks).query("period=='confirmation'").to_string(index=False),flush=True)
    print(pd.DataFrame(candidates).query('corroborated').to_string(index=False),flush=True)

if __name__=='__main__':main()
