"""Retrospective gate Top3 associations and moisture-adjusted annual profiles."""
from pathlib import Path
import importlib.util
import itertools
import json
import numpy as np
import pandas as pd
from scipy.stats import t
from scipy.sparse import bmat, csc_matrix, diags
from scipy.sparse.linalg import spsolve

H=Path(__file__).resolve().parent; ROOT=H.parents[2]
PRE=H.parent/'20261008_gate_record_seconds_v1'
sp=importlib.util.spec_from_file_location('preserved_seconds',PRE/'analyze.py')
prior=importlib.util.module_from_spec(sp);sp.loader.exec_module(prior)
old=prior.old; PLAN=json.loads((H/'PLAN.json').read_text()); BANDS=PLAN['bands']
sha=prior.sha
def save(name,v):
    with (H/name).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
def csv(name,v):
    with (H/name).open('x',encoding='utf-8') as f:v.to_csv(f,index=False)

def design(g,interactions=True,variant='primary'):
    nx,s=old.design(g,mode='gate')
    keep=[i for i,c in enumerate(s['columns']) if not c.startswith('number_')]
    if variant=='no_history':keep=[i for i in keep if s['columns'][i] not in ['hist_mean','hist_last','hist_mean_missing','hist_last_missing']]
    cols=[s['columns'][i] for i in keep]; parts=[nx[:,keep]]; n_nuisance=len(keep)
    years=sorted(g.year.unique().tolist());bands=[b for b in BANDS if b in set(g.band)]
    for side in ['inner','outer']:
        v=g.lateral.eq(side).to_numpy().astype(float);parts.append(v[:,None]);cols.append(side)
        if interactions:
            for yy in years[1:]:parts.append((v*g.year.eq(yy).to_numpy())[:,None]);cols.append(f'{side}:year:{yy}')
            for bb in bands[1:]:parts.append((v*g.band.eq(bb).to_numpy())[:,None]);cols.append(f'{side}:band:{bb}')
    return np.column_stack(parts),{'columns':cols,'n_nuisance':n_nuisance,'years':years,'bands':bands,'interactions':interactions}

def fit(g,interactions=True,variant='primary',joint_check=False):
    x,s=design(g,interactions,variant);y=g.top3.to_numpy(float)
    z,lu,fe=prior.fe_matrix(g,horse=variant!='race_only')
    v=np.column_stack([y,x]);rr=v-z@lu.solve(np.asarray(z.T@v));yr=rr[:,0];xr=rr[:,1:]
    orth=float(np.max(np.abs(z.T@rr)));assert orth<1e-7
    nn=s['n_nuisance'];gate=xr[:,nn:];nuisance=xr[:,:nn]
    gate=gate-nuisance@np.linalg.lstsq(nuisance,gate,rcond=1e-9)[0]
    rank=int(np.linalg.matrix_rank(gate,tol=1e-7));assert rank==gate.shape[1],('exposure_rank',rank,gate.shape[1])
    df=int(len(g)-fe['rank']-np.linalg.matrix_rank(xr,tol=1e-7));assert df>20,('df',df)
    penalty=np.r_[np.ones(nn),np.zeros(x.shape[1]-nn)]
    bread=np.linalg.inv(xr.T@xr+np.diag(penalty));beta=bread@(xr.T@yr);res=yr-xr@beta
    dc=prior.cluster_cov(xr,res,bread,g.race_date,df);hc=prior.cluster_cov(xr,res,bread,g.horse_id,df);cov=dc+hc
    critical_df=int(min(g.race_date.nunique(),g.horse_id.nunique())-1)
    joint_error=None
    if joint_check:
        xx=csc_matrix(x);zy=z.T@y;xy=x.T@y
        a=bmat([[z.T@z,z.T@xx],[xx.T@z,xx.T@xx+diags(penalty)]],format='csc')
        full=spsolve(a,np.r_[zy,xy]);joint_error=float(np.max(np.abs(full[z.shape[1]:]-beta)));assert joint_error<1e-7,joint_error
    return {'beta':beta.tolist(),'cov':cov.tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'spec':s,
            'fe':fe,'residual_df':df,'critical_df':critical_df,'orthogonality':orth,'exposure_rank':rank,'joint_beta_max_error':joint_error}

def vec(model,year=None,band=None):
    s=model['spec'];cols=s['columns'];v=np.zeros(len(cols))
    for side,sign in [('inner',1),('outer',-1)]:
        v[cols.index(side)]=sign
        for c in [f'{side}:year:{year}',f'{side}:band:{band}']:
            if c in cols:v[cols.index(c)]=sign
    return v

def estimate(model,v):
    b=np.asarray(model['beta']);c=np.asarray(model['cov']);p=float(v@b);se=float(np.sqrt(max(0,v@c@v)))
    cr=float(t.ppf(.975,model['critical_df']))
    return {'effect_pp':p*100,'ci_lo_pp':(p-cr*se)*100,'ci_hi_pp':(p+cr*se)*100,'se_pp':se*100,
            'p':float(2*t.sf(abs(p/se),model['critical_df'])) if se>0 else 1.}

def info(g):
    nr=int(g.race_id.nunique());nd=int(g.race_date.nunique())
    return {'races':nr,'dates':nd,'horses':int(g.horse_id.nunique()),'rows':len(g),
            'supported':bool(nr>=30 and nd>=20),'status':'basic_support' if nr>=100 and nd>=40 else 'limited' if nr>=30 and nd>=20 else 'insufficient_support'}

def raw(g,keys):
    a=g.groupby(keys,observed=True).agg(starts=('top3','size'),top3=('top3','sum'),races=('race_id','nunique'),dates=('race_date','nunique')).reset_index()
    a['top3_pct']=100*a.top3/a.starts
    # Wilson interval is descriptive binomial sampling only, not the clustered model interval.
    n=a.starts;p=a.top3/n;z=1.959963984540054;den=1+z*z/n
    center=(p+z*z/(2*n))/den;half=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    a['wilson_lo_pct']=100*(center-half);a['wilson_hi_pct']=100*(center+half)
    return a

def main():
    refs=[H/'PLAN.json',H/'analyze.py',PRE/'analyze.py',PRE/'PLAN.json',old.HERE/'analyze.py',old.OLD/'modeling.py',old.OLD/'audit/source_rows.csv',old.OLD/'audit/history_ids.json',ROOT/'jeju/data/horse_exclusions.json']
    sources=[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in refs];save('source_manifest.json',sources)
    dbsha=sha(old.DB);d,h=old.load();q=old.all_features(d,h)
    q=q[q.strict&q.field_n.eq(10)&q.race_distance_m.isin(PLAN['distances'])].sort_values(['race_date','race_number','horse_number']).copy()
    q['top3']=q.finish_position.le(3).astype(int)
    q['epoch']=np.select([q.year.le(2020),q.year.le(2023)],['2017_2020','2021_2023'],default='2024_2026partial')
    assert q.api_record_id.is_unique and q.race_date.max()=='2026-09-19'
    assert q.groupby('race_id').horse_number.apply(lambda x:sorted(x)==list(range(1,11))).all()
    assert q.groupby('race_id').top3.sum().eq(3).all()
    assert q.groupby('race_id').band.nunique().eq(1).all() and q.band.isin(BANDS).all()
    excluded=json.loads((ROOT/'jeju/data/horse_exclusions.json').read_text())['horses']
    assert not(set(q.horse_id)&{k for k,v in excluded.items() if not v['reimport_allowed']})
    ref=d[['horse_id','race_distance_m','race_date']].to_dict('index');hist_checked=0
    for r in q.itertuples():
        for i in h[str(r.api_record_id)][-5:]:
            a=ref[i];assert a['horse_id']==r.horse_id and a['race_distance_m']==r.race_distance_m and a['race_date']<=r.history_cutoff;hist_checked+=1
    csv('source_lineage.csv',q[['api_record_id','race_id','horse_id','race_date','race_distance_m','horse_number','finish_position','top3','year','moisture','band','history_cutoff','api4_3_payload_sha256']])
    for label,keys in [('gate',['race_distance_m','horse_number']),('year_gate',['race_distance_m','year','horse_number']),('band_gate',['race_distance_m','band','horse_number']),('year_band_gate',['race_distance_m','year','band','horse_number']),('lateral',['race_distance_m','lateral']),('year_lateral',['race_distance_m','year','lateral']),('year_band_lateral',['race_distance_m','year','band','lateral']),('epoch_band_lateral',['race_distance_m','epoch','band','lateral'])]:csv('raw_'+label+'.csv',raw(q,keys))
    estimates=[];models=[];support=[];pairs=[];weights=[]
    for distance,g in q.groupby('race_distance_m',sort=True):
        gi=info(g);races=g.drop_duplicates('race_id');yw=races.year.value_counts(normalize=True).sort_index().to_dict();bw=races.band.value_counts(normalize=True).to_dict()
        for kind,ww in [('year',yw),('band',bw)]:
            for level,w in ww.items():weights.append({'distance':int(distance),'kind':kind,'level':str(level),'weight':w})
        if not gi['supported']:support.append({'distance':int(distance),'scope':'full','variant':'all'}|gi);continue
        for variant in ['primary','race_only','no_history']:
            try:m=fit(g,variant=variant,joint_check=True)
            except AssertionError as exc:support.append({'distance':int(distance),'scope':'annual_model','variant':variant}|gi|{'estimated':False,'detail':str(exc)});continue
            models.append({'distance':int(distance),'scope':'annual_model','variant':variant,'model':m});support.append({'distance':int(distance),'scope':'annual_model','variant':variant}|gi|{'estimated':True})
            annual={yy:sum(w*vec(m,yy,bb) for bb,w in bw.items()) for yy in yw}
            overall=sum(w*annual[yy] for yy,w in yw.items())
            estimates.append({'distance':int(distance),'kind':'overall','level':'full','variant':variant}|gi|estimate(m,overall))
            supported_years=[]
            for yy,v in annual.items():
                iy=info(g[g.year.eq(yy)])
                if iy['supported']:
                    estimates.append({'distance':int(distance),'kind':'year','level':str(yy),'variant':variant}|iy|estimate(m,v));supported_years.append(yy)
                else:support.append({'distance':int(distance),'scope':f'year:{yy}','variant':variant}|iy|{'estimated':False,'detail':'annual effect suppressed below reporting support'})
            for bb in bw:
                ib=info(g[g.band.eq(bb)])
                if ib['supported']:
                    v=sum(w*vec(m,yy,bb) for yy,w in yw.items());estimates.append({'distance':int(distance),'kind':'band','level':bb,'variant':variant}|ib|estimate(m,v))
            for yy1,yy2 in itertools.combinations(supported_years,2):
                pairs.append({'distance':int(distance),'variant':variant,'earlier':int(yy1),'later':int(yy2)}|estimate(m,annual[yy2]-annual[yy1]))
            print('annual',distance,variant,len(g),m['joint_beta_max_error'],flush=True)
        for (epoch,bb),a in g.groupby(['epoch','band']):
            ai=info(a);entry={'distance':int(distance),'scope':f'era_band:{epoch}:{bb}','variant':'primary'}|ai
            if not ai['supported']:support.append(entry|{'estimated':False});continue
            try:m=fit(a,interactions=False,joint_check=True)
            except AssertionError as exc:support.append(entry|{'estimated':False,'detail':str(exc)});continue
            support.append(entry|{'estimated':True});models.append({'distance':int(distance),'scope':entry['scope'],'variant':'primary','model':m})
            estimates.append({'distance':int(distance),'kind':'era_band','level':f'{epoch}:{bb}','variant':'primary'}|ai|estimate(m,vec(m)))
            print('era_band',distance,epoch,bb,len(a),flush=True)
    est=pd.DataFrame(estimates);pair=pd.DataFrame(pairs)
    for _,a in est.groupby(['variant','kind']):est.loc[a.index,'q_BH']=old.bh(a.p)
    for _,a in pair.groupby('variant'):pair.loc[a.index,'q_BH']=old.bh(a.p)
    annual=est[(est.kind=='year')&est.variant.eq('primary')];reversals=[]
    for r in pair[pair.variant.eq('primary')].itertuples():
        a=annual[(annual.distance==r.distance)&annual.level.eq(str(r.earlier))].iloc[0];b=annual[(annual.distance==r.distance)&annual.level.eq(str(r.later))].iloc[0]
        opposite=a.effect_pp*b.effect_pp<0;signs=True
        for variant in ['race_only','no_history']:
            for yy,pt in [(r.earlier,a.effect_pp),(r.later,b.effect_pp)]:
                cell=est[(est.kind=='year')&est.variant.eq(variant)&est.distance.eq(r.distance)&est.level.eq(str(yy))]
                if cell.empty or np.sign(cell.iloc[0].effect_pp)!=np.sign(pt):signs=False
        reversals.append({'distance':r.distance,'earlier':r.earlier,'later':r.later,'earlier_pp':a.effect_pp,'later_pp':b.effect_pp,'earlier_q':a.q_BH,'later_q':b.q_BH,'change_pp':r.effect_pp,'change_q':r.q_BH,'opposite_point_signs':bool(opposite),'sensitivity_signs_agree':bool(signs),'confirmed_reversal':bool(opposite and signs and a.q_BH<.05 and b.q_BH<.05 and r.q_BH<.05)})
    csv('adjusted_contrasts.csv',est);csv('year_pair_changes.csv',pair);csv('reversal_checks.csv',pd.DataFrame(reversals));csv('support.csv',pd.DataFrame(support));csv('standardization_weights.csv',pd.DataFrame(weights));save('models.json',models)
    assert all(sha(Path(a['path']))==a['sha256'] for a in sources) and sha(old.DB)==dbsha
    assert all(np.linalg.eigvalsh(np.asarray(m['model']['cov'])).min()>-1e-7 for m in models)
    save('verification.json',{'status':'passed','source_rows':len(q),'races':int(q.race_id.nunique()),'history_endpoints_checked':hist_checked,'all_races_have_three_top3':True,'all_races_exact_gates_1_to_10':True,'sources_and_database_unchanged':True,'database_sha256':dbsha,'fitted_models':len(models),'joint_equation_beta_max_error':max(m['model']['joint_beta_max_error'] for m in models),'projection_orthogonality_max':max(m['model']['orthogonality'] for m in models),'confirmed_reversals':sum(r['confirmed_reversal'] for r in reversals),'no_operational_change':True,'future_validation':False})
    print(est[(est.variant=='primary')&(est.kind!='era_band')].to_string(index=False),flush=True)
    print(est[(est.kind=='era_band')&(est.effect_pp<0)].to_string(index=False),flush=True)
if __name__=='__main__':main()
