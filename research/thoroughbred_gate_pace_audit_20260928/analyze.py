import numpy as np
import pandas as pd
from scipy.stats import t as student_t
from common import *

NUM=['rating','carried_weight_kg','age','prior_finish5','prior_top3_5','prior_early5','log_starts','log_gap']
def controls(g):
    g=g.copy();g['log_starts']=np.log1p(g.prior_starts);g['log_gap']=np.log1p(g.days_since_last)
    cols=[];names=[]
    for name in NUM:
        x=g[name].to_numpy(float);miss=~np.isfinite(x);finite=x[~miss];median=np.median(finite) if len(finite) else 0
        x=np.where(miss,median,x);sd=x.std();x=(x-x.mean())/(sd if sd>1e-10 else 1)
        cols+=[x,miss.astype(float)];names+=[name,name+'_missing']
    return np.column_stack(cols),names

def cluster_fit(g,X,y):
    rc=pd.factorize(g.race_id)[0];dc=pd.factorize(g.race_date)[0];R=int(rc.max()+1);G=int(dc.max()+1);N=len(g)
    counts=np.bincount(rc)
    xc=np.column_stack([v-np.bincount(rc,weights=v)[rc]/counts[rc] for v in X.T])
    yc=y-np.bincount(rc,weights=y)[rc]/counts[rc]
    w=1/counts[rc];xw=xc*np.sqrt(w)[:,None];yw=yc*np.sqrt(w)
    inv=np.linalg.pinv(xw.T@xw,rcond=1e-10);beta=inv@(xw.T@yw);err=yw-xw@beta
    scores=xw*err[:,None];S=np.column_stack([np.bincount(dc,weights=v,minlength=G) for v in scores.T])
    rank=int(np.linalg.matrix_rank(xw.T@xw,tol=1e-8));correction=G/max(G-1,1)*(N-1)/max(N-R-rank,1)
    cov=inv@(S.T@S)@inv*correction
    return beta,cov,G,rank

def contrast(beta,cov,G,c):
    estimate=float(c@beta);se=float(np.sqrt(max(0,c@cov@c)));q=float(student_t.ppf(.975,G-1));p=float(2*student_t.sf(abs(estimate/se),G-1)) if se>1e-14 else (1. if abs(estimate)<1e-12 else 0.)
    return {'effect':estimate,'se':se,'ci_low':estimate-q*se,'ci_high':estimate+q*se,'p':p}

def bh(values):
    x=np.asarray(values,float);order=np.argsort(x);n=len(x);v=np.minimum.accumulate((x[order]*n/np.arange(1,n+1))[::-1])[::-1];out=np.empty(n);out[order]=np.clip(v,0,1);return out

def paired_raw(g,target):
    z=g.groupby(['race_id','race_date','band'])[target].mean().unstack('band')
    if not {'INNER','OUTER'}.issubset(z):return None
    z=(z.OUTER-z.INNER).dropna();n=len(z)
    if n<2:return None
    dates=z.index.get_level_values('race_date');e=z-z.mean();ss=e.groupby(dates).sum();G=len(ss)
    if G<2:return None
    se=np.sqrt(G/(G-1)*np.square(ss).sum()/n**2);q=student_t.ppf(.975,G-1)
    return {'raw_effect':float(z.mean()),'raw_ci_low':float(z.mean()-q*se),'raw_ci_high':float(z.mean()+q*se),'paired_races':n}

def main():
    lock=json.loads((OUT/'protocol_lock.json').read_text())
    for name,h in lock['files'].items():assert sha(OUT/name)==h,name
    d=pd.read_parquet(OUT/'runners.parquet');rows=[]
    groups=[('all',None),('distance','distance_m'),('condition','condition'),('year','year'),('month','month'),('quarter','quarter'),('race_order','race_order_band'),('prior_style','prior_style')]
    raw=[]
    for venue,f in d.groupby('venue'):
        for scope,key in groups:
            blocks=[('ALL',f)] if key is None else f.groupby(key)
            for level,g in blocks:
                for band,b in g.groupby('band'):
                    raw.append({'venue':venue,'scope':scope,'level':str(level),'band':band,'runners':len(b),'races':b.race_id.nunique(),'days':b.race_date.nunique(),'win_rate':b.win.mean(),'top3_rate':b.top3.mean(),'s1f_pct_mean':b.s1f_pct.mean(),'s1f_seconds_relative':b.s1f_ms_relative.mean()/1000,'mean_rating':b.rating.mean(),'mean_prior_top3':b.prior_top3_5.mean()})
                if scope=='quarter':continue # formal joint quarter model below
                for target in ['top3','s1f_pct']:
                    g2=g[g[target].notna()].copy()
                    if g2.race_id.nunique()<50 or g2.race_date.nunique()<20 or g2.band.nunique()<3:continue
                    C,names=controls(g2);X=np.column_stack([g2.band.eq('MIDDLE'),g2.band.eq('OUTER'),C]).astype(float)
                    b,V,G,rank=cluster_fit(g2,X,g2[target].to_numpy(float));c=np.zeros(X.shape[1]);c[1]=1
                    r={'venue':venue,'scope':scope,'level':str(level),'target':target,'runners':len(g2),'races':g2.race_id.nunique(),'days':G,**contrast(b,V,G,c)}
                    rr=paired_raw(g2,target)
                    if rr:r.update(rr)
                    rows.append(r)
        print('strata done',venue,flush=True)
    raw=pd.DataFrame(raw);raw.to_parquet(OUT/'raw_strata.parquet',index=False)
    ef=pd.DataFrame(rows);ef['q_exploratory']=bh(ef.p);ef.to_parquet(OUT/'adjusted_strata.parquet',index=False)
    # Absolute gate descriptions are pooled start rates, not race-standardized causal effects.
    absolute=d.groupby(['venue','gate_number']).agg(runners=('entry_id','size'),races=('race_id','nunique'),top3_rate=('top3','mean'),win_rate=('win','mean'),s1f_pct=('s1f_pct','mean')).reset_index()
    absolute.to_parquet(OUT/'absolute_gates.parquet',index=False)
    periods=[];models=[]
    for venue,g in d.groupby('venue'):
        g=g.copy();C,names=controls(g);columns=[g.band.eq('MIDDLE').to_numpy(float),g.band.eq('OUTER').to_numpy(float)];labels=['MIDDLE','OUTER'];cats={}
        for key in ['quarter','distance_m','condition']:
            vals=sorted(g[key].unique());cats[key]=vals
            for value in vals[1:]:
                for band in ['MIDDLE','OUTER']:
                    columns.append((g.band.eq(band)&g[key].eq(value)).to_numpy(float));labels.append(f'{band}:{key}:{value}')
        columns.extend(C.T);labels.extend(names);X=np.column_stack(columns)
        b,V,G,rank=cluster_fit(g,X,g.top3.to_numpy(float));idx={n:i for i,n in enumerate(labels)}
        races=g.drop_duplicates('race_id');weights={key:races[key].value_counts(normalize=True).to_dict() for key in cats}
        def vc(q):
            c=np.zeros(len(labels));c[idx['OUTER']]=1
            if q!=cats['quarter'][0]:c[idx[f'OUTER:quarter:{q}']]=1
            for key in ['distance_m','condition']:
                for value in cats[key][1:]:c[idx[f'OUTER:{key}:{value}']]=weights[key][value]
            return c
        mean=sum((vc(q)*weights['quarter'][q] for q in cats['quarter']),np.zeros(len(labels)))
        for q in cats['quarter']:
            block=g[g.quarter.eq(q)];stats=contrast(b,V,G,vc(q));change=contrast(b,V,G,vc(q)-mean)
            periods.append({'venue':venue,'quarter':q,'races':block.race_id.nunique(),'days':block.race_date.nunique(),'supported':bool(block.race_id.nunique()>=50 and block.race_date.nunique()>=20),'partial_quarter':q=='2026Q3',**{'standardized_'+k:v for k,v in stats.items()},**{'deviation_'+k:v for k,v in change.items()},'long_run_effect':float(mean@b)})
        models.append({'venue':venue,'rows':len(g),'races':len(races),'day_clusters':G,'columns':len(labels),'rank':rank,'coefficients':dict(zip(labels,b.tolist())),'distance_weights':{str(k):v for k,v in weights['distance_m'].items()},'condition_weights':weights['condition']})
        print('periods done',venue,flush=True)
    p=pd.DataFrame(periods);p['deviation_q']=bh(p.deviation_p);p['standardized_q']=bh(p.standardized_p)
    p['period_candidate']=p.supported&p.deviation_q.lt(.05)
    p.to_parquet(OUT/'quarter_effects.parquet',index=False);dump('period_models.json',models)
    print(ef[ef.scope.eq('all')][['venue','target','raw_effect','effect','ci_low','ci_high']].to_string(index=False),flush=True)
    print('quarter candidates',p[p.period_candidate].to_string(index=False),flush=True)
    dump('analysis_complete.json',{'stratum_effects':len(ef),'quarter_tests':len(p),'period_candidates':int(p.period_candidate.sum()),'new_predictive_models':0})
if __name__=='__main__':main()
